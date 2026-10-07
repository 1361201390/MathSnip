import unittest
from unittest.mock import MagicMock, patch

import requests

from core import OcrError, format_output, parse_hotkey, parse_result, recognize, strip_math_delimiters


class CoreTests(unittest.TestCase):
    def test_outer_delimiters(self):
        for formula in (r"\[ \frac{x}{y} \]", r"\(\frac{x}{y}\)", r"$$\frac{x}{y}$$", r"$\frac{x}{y}$"):
            self.assertEqual(strip_math_delimiters(formula), r"\frac{x}{y}")
        self.assertEqual(strip_math_delimiters(r"\(x\) and \(y\)"), r"\(x\) and \(y\)")
        self.assertEqual(strip_math_delimiters(r"$x$ $y$"), r"$x$ $y$")

    def test_formats(self):
        self.assertEqual(format_output("x^2", "latex"), "x^2")
        self.assertEqual(format_output("x^2", "display"), "$$\nx^2\n$$")
        self.assertEqual(format_output("x^2", "word"), "x^2")
        with self.assertRaises(ValueError):
            format_output("x", "unknown")

    def test_parse(self):
        self.assertEqual(parse_result({"latex_styled": "x^2", "text": "wrong", "confidence": 0.9}).latex, "x^2")
        self.assertEqual(parse_result({"text": r"\(x\)"}).latex, "x")
        self.assertIsNone(parse_result({"text": "x", "confidence": "bad"}).confidence)
        self.assertIsNone(parse_result({"text": "x", "confidence": 3}).confidence)
        for value in ({}, [], {"text": 12}, {"text": " "}, {"error": "private response", "error_info": {"id": "math_confidence"}}):
            with self.assertRaises(OcrError):
                parse_result(value)

    def test_hotkeys(self):
        self.assertEqual(parse_hotkey("Alt+Q"), (0x4001, ord("Q")))
        self.assertEqual(parse_hotkey(" ctrl + shift + f12 "), (0x4006, 0x7b))
        self.assertEqual(parse_hotkey("Win+F24"), (0x4008, 0x87))
        for value in ("Q", "Alt+Alt+Q", "Alt+F25", "Alt+", "Ctrl++Q", "Meta+Q"):
            with self.assertRaises(ValueError):
                parse_hotkey(value)

    def transport(self, status=200, payload=None):
        session = MagicMock()
        session.__enter__.return_value = session
        response = session.post.return_value
        response.status_code = status
        response.json.return_value = payload if payload is not None else {"latex_styled": "x^2"}
        return session, response

    def test_request_and_no_retries(self):
        session, response = self.transport()
        with patch("core.requests.Session", return_value=session):
            self.assertEqual(recognize(b"png", "id", "secret").latex, "x^2")
        session.post.assert_called_once()
        kwargs = session.post.call_args.kwargs
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["timeout"], (10, 40))
        self.assertIn('"improve_mathpix": false', kwargs["data"]["options_json"])
        self.assertEqual(kwargs["files"]["file"][1], b"png")
        response.close.assert_called_once()

    def test_status_failures_do_not_expose_body(self):
        for status in (302, 401, 402, 403, 413, 429, 500):
            session, response = self.transport(status, {"secret": "sensitive"})
            with patch("core.requests.Session", return_value=session), self.assertRaises(OcrError) as ctx:
                recognize(b"png", "id", "secret")
            self.assertNotIn("sensitive", str(ctx.exception))
            response.close.assert_called_once()
            session.post.assert_called_once()

    def test_network_failure(self):
        cases = (
            (requests.ConnectTimeout("secret"), "请求没有发出"),
            (requests.ReadTimeout("secret"), "可能已计费"),
            (requests.exceptions.SSLError("secret"), "TLS 握手"),
            (requests.ConnectionError("secret"), "HTTPS_PROXY"),
        )
        for exception, hint in cases:
            session, _ = self.transport()
            session.post.side_effect = exception
            with patch("core.requests.Session", return_value=session), self.assertRaises(OcrError) as ctx:
                recognize(b"png", "id", "secret")
            self.assertNotIn("secret", str(ctx.exception))
            self.assertIn(hint, str(ctx.exception))
            session.post.assert_called_once()

    def test_malformed_response(self):
        session, response = self.transport()
        response.json.side_effect = ValueError("private")
        with patch("core.requests.Session", return_value=session), self.assertRaises(OcrError):
            recognize(b"png", "id", "secret")

    def test_invalid_credentials_and_empty_image_never_send(self):
        with patch("core.requests.Session") as session:
            for app_id, key in (("", "key"), ("id", "a\nb"), ("id", "含中文")):
                with self.assertRaises(ValueError):
                    recognize(b"png", app_id, key)
            with self.assertRaises(OcrError):
                recognize(b"", "id", "key")
            session.assert_not_called()


if __name__ == "__main__":
    unittest.main()
