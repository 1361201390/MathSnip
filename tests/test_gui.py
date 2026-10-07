import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from qt_loader import preload_qt

# Keep the suite runnable on interpreters whose DLL path shadows Qt's ICU (e.g. Anaconda).
preload_qt()

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication

from core import OcrResult
from mathsnip import MathSnipWindow, OcrWorker, png_region


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_crop_at_various_dpi(self):
        for scale in (1, 1.25, 1.5, 2):
            pixmap = QPixmap(int(400 * scale), int(200 * scale))
            pixmap.fill(QColor("red"))
            pixmap.setDevicePixelRatio(scale)
            image = QImage.fromData(png_region(pixmap, QRect(30, 20, 80, 40), 400, 200))
            self.assertEqual(image.width(), int(80 * scale) if scale != 1.25 else 101)
            self.assertEqual(image.height(), int(40 * scale))
            self.assertEqual(image.pixelColor(0, 0), QColor("red"))

    def test_clipboard_success_failure_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            window = MathSnipWindow(Path(directory), enable_native=False)
            self.app.processEvents()
            window.notify_enabled = False
            self.app.clipboard().setText("old")
            window.on_failure("网络失败")
            self.assertEqual(self.app.clipboard().text(), "old")
            with patch("mathsnip.recognize") as api:
                window.cancel_capture()
                api.assert_not_called()
            self.assertEqual(self.app.clipboard().text(), "old")
            window.last_mode = "display"
            window.on_success(OcrResult(r"\frac{x}{y}", 0.9))
            self.assertEqual(self.app.clipboard().text(), "$$\n\\frac{x}{y}\n$$")
            with patch("mathsnip.recognize") as api:
                window.copy_result("latex")
                api.assert_not_called()
            self.assertEqual(self.app.clipboard().text(), r"\frac{x}{y}")
            window.cleanup()
            window.deleteLater()
            self.app.processEvents()

    def test_worker_releases_secrets_and_screenshot(self):
        worker = OcrWorker(b"png", "id", "key")
        output = []
        worker.succeeded.connect(output.append)
        with patch("mathsnip.recognize", return_value=OcrResult("x^2")):
            worker.run()
        self.assertEqual(output[0].latex, "x^2")
        self.assertEqual(worker.png, b"")
        self.assertEqual(worker.app_key, "")


if __name__ == "__main__":
    unittest.main()
