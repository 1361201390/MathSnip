"""Mathpix transport and output formatting; no GUI or Windows dependency."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
import requests

API_URL = "https://api.mathpix.com/v3/text"
MODES = {"latex": "LaTeX", "display": "Markdown 块公式", "word": "Word LaTeX"}
DEFAULT_HOTKEYS = {"latex": "Alt+Q", "display": "Alt+W", "word": "Alt+E"}


class OcrError(Exception):
    """A sanitized, user-facing failure. Never contains credentials or a response body."""


@dataclass(frozen=True)
class OcrResult:
    latex: str
    confidence: float | None = None


def strip_math_delimiters(value: str) -> str:
    value = value.strip()
    for left, right in ((r"\[", r"\]"), (r"\(", r"\)"), ("$$", "$$"), ("$", "$")):
        if value.startswith(left) and value.endswith(right):
            inner = value[len(left):-len(right)].strip()
            # Only unwrap a single outer math block, not two adjacent formulas.
            if left not in inner and right not in inner:
                return inner
    return value


def parse_result(data: object) -> OcrResult:
    if not isinstance(data, dict):
        raise OcrError("Mathpix 返回格式异常，请稍后再试。")
    if data.get("error") or data.get("error_info"):
        info = data.get("error_info")
        code = info.get("id", "") if isinstance(info, dict) else ""
        hints = {
            "image_no_content": "没有检测到公式，请缩小框选范围。",
            "math_confidence": "识别置信度不足，请使用更清晰的公式截图。",
            "image_max_size": "截图过大，请缩小框选范围。",
            "image_not_supported": "截图格式不被支持。",
        }
        raise OcrError(hints.get(code, "Mathpix 未能识别这张图片，请检查账号并重新框选。"))
    value = data.get("latex_styled") or data.get("text")
    if not isinstance(value, str) or not value.strip():
        raise OcrError("没有识别到可复制的内容，请重新框选。")
    confidence = data.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        confidence = None
    elif not 0 <= confidence <= 1:
        confidence = None
    return OcrResult(strip_math_delimiters(value), confidence)


def format_output(latex: str, mode: str) -> str:
    if mode not in MODES:
        raise ValueError("未知输出格式")
    value = strip_math_delimiters(latex)
    return "$$\n" + value + "\n$$" if mode == "display" else value


def parse_hotkey(value: str) -> tuple[int, int]:
    """Return Win32 modifiers/VK. Supports Ctrl/Alt/Shift/Win + A-Z/0-9/F1-F24."""
    parts = [p.strip().upper() for p in value.split("+")]
    mods = {"ALT": 0x0001, "CTRL": 0x0002, "SHIFT": 0x0004, "WIN": 0x0008}
    if len(parts) < 2 or any(not p for p in parts):
        raise ValueError("快捷键必须包含修饰键，例如 Alt+Q 或 Ctrl+Shift+Q。")
    if len(set(parts[:-1])) != len(parts[:-1]) or any(p not in mods for p in parts[:-1]):
        raise ValueError("修饰键只能使用 Ctrl、Alt、Shift、Win，且不能重复。")
    modifier = sum(mods[p] for p in parts[:-1]) | 0x4000  # MOD_NOREPEAT
    key = parts[-1]
    if re.fullmatch(r"[A-Z0-9]", key):
        vk = ord(key)
    elif re.fullmatch(r"F([1-9]|1[0-9]|2[0-4])", key):
        vk = 0x70 + int(key[1:]) - 1
    else:
        raise ValueError("主键只能使用 A–Z、0–9 或 F1–F24。")
    return modifier, vk


def validate_credentials(app_id: str, app_key: str) -> None:
    for value in (app_id, app_key):
        if not value or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("App ID 和 API Key 必须填写，且不能包含空格或换行。")


def recognize(png: bytes, app_id: str, app_key: str) -> OcrResult:
    validate_credentials(app_id, app_key)
    if not png:
        raise OcrError("截图为空，请重新框选。")
    if len(png) > 5_000_000:
        raise OcrError("截图过大，请缩小到公式区域。")
    options = {
        "formats": ["latex_styled", "text"],
        "rm_spaces": True,
        "include_equation_tags": False,
        "metadata": {"improve_mathpix": False},
    }
    try:
        # One request only. Automatic retries could cause duplicate API charges.
        with requests.Session() as session:
            response = session.post(
                API_URL,
                headers={"app_id": app_id, "app_key": app_key},
                files={"file": ("formula.png", png, "image/png")},
                data={"options_json": json.dumps(options)},
                timeout=(10, 40),
                allow_redirects=False,  # never forward the custom auth headers
            )
            try:
                hints = {
                    401: "认证失败，请检查 App ID 和 API Key。",
                    403: "账号无权限，请检查 Mathpix API 状态。",
                    402: "API 余额或计费状态异常，请查看 Mathpix 控制台。",
                    413: "截图过大，请缩小框选范围。",
                    429: "调用过于频繁或额度不足，请稍后重试并查看控制台。",
                }
                if not 200 <= response.status_code < 300:
                    raise OcrError(hints.get(response.status_code, f"Mathpix 请求失败（HTTP {response.status_code}）。"))
                try:
                    payload = response.json()
                except ValueError:
                    raise OcrError("Mathpix 返回格式异常，请稍后再试。") from None
                return parse_result(payload)
            finally:
                response.close()
    except requests.exceptions.ConnectTimeout:
        # No byte was sent yet, so this failure cannot have been billed.
        raise OcrError("连接 api.mathpix.com 超时，请求没有发出，通常不计费。"
                       "请检查代理/TUN 是否放行该域名（也可用 HTTPS_PROXY 指定代理）。") from None
    except requests.exceptions.SSLError:
        # The TLS handshake died, so no OCR request reached Mathpix.
        raise OcrError("TLS 握手被中断，通常是代理/TUN 节点不稳定或该域名被重置。"
                       "请求未送达，一般不计费，可直接重试。") from None
    except requests.exceptions.ReadTimeout:
        raise OcrError("等待响应超时。未自动重试；本次可能已计费，请先查看控制台。") from None
    except requests.Timeout:
        raise OcrError("请求超时。未自动重试；本次可能已计费，请先查看控制台。") from None
    except requests.exceptions.ConnectionError:
        raise OcrError("连接 api.mathpix.com 失败，请检查代理或 TUN 设置"
                       "（也可在启动前设置 HTTPS_PROXY 指定代理端口）。") from None
    except requests.RequestException:
        raise OcrError("请求 api.mathpix.com 失败，请检查网络与代理设置。") from None
