"""MathSnip: Windows screen region -> Mathpix -> clipboard."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import math
import os
from pathlib import Path
import sys

from qt_loader import preload_qt

# Must run before the PySide6 imports: it repairs a Windows ICU that shadows Qt's own ICU lookup.
preload_qt()

from PySide6.QtCore import (
    QAbstractNativeEventFilter, QBuffer, QByteArray, QIODevice, QLockFile,
    QPoint, QRect, Qt, QThread, QTimer, Signal,
)
from PySide6.QtGui import QColor, QCursor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMenu, QMessageBox, QPushButton, QSystemTrayIcon, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget,
)

from core import DEFAULT_HOTKEYS, MODES, OcrError, OcrResult, format_output, recognize, validate_credentials
from windows_support import HotkeyRegistry, decrypt_key, encrypt_key

APP_NAME = "MathSnip"


def app_dir() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def make_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#2563eb"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(2, 2, 60, 60, 15, 15)
    painter.setPen(QColor("white"))
    painter.setFont(QFont("Segoe UI", 30, QFont.Weight.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "Σ")
    painter.end()
    return QIcon(pixmap)


def png_region(snapshot: QPixmap, rect: QRect, logical_width: int, logical_height: int) -> bytes:
    """Map logical selection to physical screenshot pixels (including mixed DPI)."""
    rect = rect.normalized().intersected(QRect(0, 0, logical_width, logical_height))
    sx, sy = snapshot.width() / logical_width, snapshot.height() / logical_height
    left, top = math.floor(rect.x() * sx), math.floor(rect.y() * sy)
    right = math.ceil((rect.x() + rect.width()) * sx)
    bottom = math.ceil((rect.y() + rect.height()) * sy)
    crop = snapshot.copy(left, top, right - left, bottom - top)
    crop.setDevicePixelRatio(1.0)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not crop.save(buffer, "PNG"):
        raise OcrError("无法编码截图，请重新框选。")
    buffer.close()
    return bytes(data)


class CaptureOverlay(QWidget):
    selected = Signal(bytes)
    cancelled = Signal()

    def __init__(self, screen, snapshot):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.snapshot = snapshot
        self.origin: QPoint | None = None
        self.selection = QRect()
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.winId()
        self.windowHandle().setScreen(screen)
        self.setGeometry(screen.geometry())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.snapshot)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 95))
        if not self.selection.isEmpty():
            painter.save()
            painter.setClipRect(self.selection)
            painter.drawPixmap(self.rect(), self.snapshot)
            painter.restore()
            painter.setPen(QPen(QColor("#60a5fa"), 2))
            painter.drawRect(self.selection)
        painter.fillRect(QRect(16, 16, min(self.width() - 32, 570), 38), QColor(15, 23, 42, 225))
        painter.setPen(Qt.GlobalColor.white)
        painter.setFont(QFont("Microsoft YaHei UI", 10))
        painter.drawText(QRect(28, 16, self.width() - 56, 38), Qt.AlignmentFlag.AlignVCenter,
                         "拖动框选公式 · 松开识别 · Esc / 右键取消 · 请在单个屏幕内框选")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.cancelled.emit()
        elif event.button() == Qt.MouseButton.LeftButton:
            self.origin = event.position().toPoint()
            self.selection = QRect()

    def mouseMoveEvent(self, event):
        if self.origin is not None:
            self.selection = QRect(self.origin, event.position().toPoint()).normalized().intersected(self.rect())
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.origin is None:
            return
        self.selection = QRect(self.origin, event.position().toPoint()).normalized().intersected(self.rect())
        self.origin = None
        if self.selection.width() < 8 or self.selection.height() < 8:
            self.cancelled.emit()
            return
        try:
            png = png_region(self.snapshot, self.selection, self.width(), self.height())
        except OcrError:
            self.cancelled.emit()
            return
        self.selected.emit(png)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()


class OcrWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, png, app_id, app_key, parent=None):
        super().__init__(parent)
        self.png, self.app_id, self.app_key = png, app_id, app_key

    def run(self):
        try:
            self.succeeded.emit(recognize(self.png, self.app_id, self.app_key))
        except (OcrError, ValueError) as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit("识别过程异常，请重新启动工具。")
        finally:
            self.png = b""
            self.app_key = ""


class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, registry, callback):
        super().__init__()
        self.registry, self.callback = registry, callback

    def nativeEventFilter(self, event_type, message):
        if sys.platform == "win32" and bytes(event_type) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam in self.registry.bindings:
                mode = self.registry.bindings[msg.wParam]
                QTimer.singleShot(0, lambda: self.callback(mode))
                return True, 0
        return False, 0


class MathSnipWindow(QWidget):
    def __init__(self, data_dir: Path | None = None, enable_native: bool = True):
        super().__init__()
        self.data_dir = data_dir or app_dir()
        self.config_path = self.data_dir / "settings.json"
        self.credentials = ("", "")
        self.hotkeys = dict(DEFAULT_HOTKEYS)
        self.notify_enabled = True
        self.worker: OcrWorker | None = None
        self.overlays: list[CaptureOverlay] = []
        self.capturing = False
        self.pending_quit = False
        self.last_mode = "latex"
        self.registry = HotkeyRegistry() if enable_native else None
        self.setWindowTitle("MathSnip · 公式截图")
        self.setWindowIcon(make_icon())
        self.resize(630, 560)
        self.build_ui()
        self.build_tray()
        self.load_settings()
        if self.registry is not None:
            self.native_filter = HotkeyFilter(self.registry, self.start_capture)
            QApplication.instance().installNativeEventFilter(self.native_filter)
            try:
                self.registry.replace(self.hotkeys)
            except ValueError as exc:
                self.status.setText(str(exc))
                QTimer.singleShot(0, self.show_settings)
        if not all(self.credentials):
            QTimer.singleShot(0, self.show_settings)
        QApplication.instance().aboutToQuit.connect(self.cleanup)

    def build_ui(self):
        layout = QVBoxLayout(self)
        title = QLabel("MathSnip")
        title.setStyleSheet("font-size: 25px; font-weight: 600; color: #1d4ed8;")
        layout.addWidget(title)
        layout.addWidget(QLabel("快捷键框选 → Mathpix 识别 → 自动复制"))
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        result_tab, settings_tab = QWidget(), QWidget()
        self.tabs.addTab(result_tab, "识别结果")
        self.tabs.addTab(settings_tab, "设置")
        result_layout = QVBoxLayout(result_tab)
        self.mode_hint = QLabel("识别结果可编辑；切换复制格式不会再次调用 API。")
        self.mode_hint.setWordWrap(True)
        result_layout.addWidget(self.mode_hint)
        self.editor = QTextEdit()
        self.editor.setAcceptRichText(False)
        self.editor.setPlaceholderText("这里显示最近一次识别结果…")
        self.editor.setFont(QFont("Consolas", 12))
        result_layout.addWidget(self.editor)
        capture = QPushButton("框选识别 LaTeX")
        capture.clicked.connect(lambda: self.start_capture("latex"))
        result_layout.addWidget(capture)
        copies = QHBoxLayout()
        for mode, text in MODES.items():
            button = QPushButton("复制 " + text)
            button.clicked.connect(lambda checked=False, m=mode: self.copy_result(m))
            copies.addWidget(button)
        result_layout.addLayout(copies)
        form = QFormLayout(settings_tab)
        self.app_id_input = QLineEdit()
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setPlaceholderText("只保存在本机，通过 Windows DPAPI 加密")
        form.addRow("Mathpix App ID", self.app_id_input)
        form.addRow("Mathpix API Key", self.key_input)
        self.hotkey_inputs = {}
        for mode, text in MODES.items():
            field = QLineEdit(self.hotkeys[mode])
            self.hotkey_inputs[mode] = field
            form.addRow(text + " 快捷键", field)
        self.notifications = QCheckBox("识别完成后显示托盘通知")
        self.notifications.setChecked(True)
        form.addRow(self.notifications)
        save = QPushButton("保存设置")
        save.clicked.connect(self.save_settings)
        form.addRow(save)
        help_text = QLabel(
            '<a href="https://console.mathpix.com/">打开 Mathpix API 控制台</a><br><br>'
            "API 账号需单独开通计费；Snip 会员不等于 API 额度。<br>"
            "截图会发往 Mathpix；不会在本机保存截图或识别历史。<br>"
            "Word：Alt+= 插入公式，选择 LaTeX 输入，粘贴后转换为专业格式。<br>"
            "多屏均可截图，每次请在同一屏幕内框选。"
        )
        help_text.setOpenExternalLinks(True)
        help_text.setWordWrap(True)
        form.addRow(help_text)
        self.status = QLabel("就绪")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        hide_button = QPushButton("收起到托盘")
        hide_button.clicked.connect(self.hide)
        layout.addWidget(hide_button)
        self.setStyleSheet(
            "QWidget {background: #f8fafc; color: #0f172a; font-family: 'Microsoft YaHei UI'; font-size: 12px;}"
            "QLineEdit, QTextEdit {background: white; border: 1px solid #cbd5e1; border-radius: 5px; padding: 7px;}"
            "QPushButton {background: #e2e8f0; border: none; border-radius: 5px; padding: 9px;}"
            "QPushButton:hover {background: #bfdbfe;} QTabWidget::pane {border: 1px solid #cbd5e1;}"
        )

    def build_tray(self):
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip("MathSnip · Alt+Q 框选公式")
        menu = QMenu()
        for mode, name in MODES.items():
            action = menu.addAction("框选 → " + name)
            action.triggered.connect(lambda checked=False, m=mode: self.start_capture(m))
        menu.addSeparator()
        menu.addAction("最近结果", self.show_result)
        menu.addAction("设置", self.show_settings)
        menu.addSeparator()
        menu.addAction("退出", self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.tray_activated)
        self.tray.messageClicked.connect(self.show_result)
        self.tray.show()

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_result()

    def raise_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def show_result(self):
        self.tabs.setCurrentIndex(0)
        self.raise_window()

    def show_settings(self):
        self.tabs.setCurrentIndex(1)
        self.raise_window()

    def load_settings(self):
        if not self.config_path.exists():
            return
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            app_id = data["app_id"]
            key = decrypt_key(data["encrypted_app_key"])
            validate_credentials(app_id, key)
            keys = data.get("hotkeys", DEFAULT_HOTKEYS)
            if set(keys) != set(DEFAULT_HOTKEYS) or not all(isinstance(v, str) for v in keys.values()):
                raise ValueError("快捷键设置异常")
            self.credentials = (app_id, key)
            self.hotkeys = {m: keys[m] for m in DEFAULT_HOTKEYS}
            self.notify_enabled = bool(data.get("notify", True))
            self.app_id_input.setText(app_id)
            self.key_input.setText(key)
            for m, field in self.hotkey_inputs.items():
                field.setText(self.hotkeys[m])
            self.notifications.setChecked(self.notify_enabled)
            self.tray.setToolTip(f"MathSnip · {self.hotkeys['latex']} 框选公式")
        except (OSError, ValueError, KeyError, TypeError):
            self.credentials = ("", "")
            self.status.setText("设置无法读取或密钥不能解密，请重新填写并保存。")

    def save_settings(self):
        if self.capturing or self.worker is not None:
            self.status.setText("请等本次截图或识别完成后保存设置。")
            return
        app_id, key = self.app_id_input.text().strip(), self.key_input.text().strip()
        new_keys = {mode: field.text().strip() for mode, field in self.hotkey_inputs.items()}
        old_keys = dict(self.registry.values) if self.registry else {}
        changed = False
        temporary = self.config_path.with_suffix(".tmp")
        try:
            validate_credentials(app_id, key)
            encrypted = encrypt_key(key)
            if self.registry is None:
                raise ValueError("全局快捷键仅支持 Windows。")
            self.registry.replace(new_keys)
            changed = True
            data = {"app_id": app_id, "encrypted_app_key": encrypted,
                    "hotkeys": new_keys, "notify": self.notifications.isChecked()}
            self.data_dir.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, self.config_path)
        except (ValueError, OSError) as exc:
            if changed:
                try:
                    self.registry.replace(old_keys)
                except ValueError:
                    self.status.setText("快捷键恢复失败，请重新保存设置。")
            temporary.unlink(missing_ok=True)
            # OSError may expose only a local path; never print any key or payload.
            message = str(exc) if isinstance(exc, ValueError) else "无法加密或保存设置，请检查当前 Windows 账户和文件权限。"
            QMessageBox.warning(self, APP_NAME, message)
            return
        self.credentials = (app_id, key)
        self.hotkeys = new_keys
        self.notify_enabled = self.notifications.isChecked()
        self.tray.setToolTip(f"MathSnip · {self.hotkeys['latex']} 框选公式")
        self.status.setText("已保存。按快捷键即可框选；保存设置不会调用 API。")

    def start_capture(self, mode):
        if self.pending_quit or self.capturing or self.worker is not None:
            return
        if not all(self.credentials):
            self.status.setText("请先填写 App ID 和 API Key 并保存设置。")
            self.show_settings()
            return
        self.last_mode = mode
        self.capturing = True
        self.hide()
        QTimer.singleShot(180, self.open_overlays)

    def open_overlays(self):
        if not self.capturing or self.pending_quit:
            return
        # Capture all screens BEFORE displaying any overlay, so overlays never enter OCR.
        captures = [(s, s.grabWindow(0)) for s in QApplication.screens()]
        if not captures or any(p.isNull() for _, p in captures):
            self.capturing = False
            self.on_failure("屏幕捕获失败，请检查远程桌面或受保护窗口。")
            return
        for screen, snapshot in captures:
            overlay = CaptureOverlay(screen, snapshot)
            overlay.selected.connect(self.submit_capture)
            overlay.cancelled.connect(self.cancel_capture)
            self.overlays.append(overlay)
        for overlay in self.overlays:
            overlay.show()
            overlay.raise_()
        cursor = QCursor.pos()
        target = next((o for o in self.overlays if o.geometry().contains(cursor)), self.overlays[0])
        target.activateWindow()
        target.setFocus()

    def close_overlays(self):
        for overlay in self.overlays:
            overlay.hide()
            overlay.deleteLater()
        self.overlays.clear()
        self.capturing = False

    def cancel_capture(self):
        self.close_overlays()
        self.status.setText("已取消，未调用 API。")

    def submit_capture(self, png):
        if not self.capturing:
            return
        self.close_overlays()
        self.status.setText("正在识别…")
        self.tray.setToolTip("MathSnip · 正在识别…")
        app_id, key = self.credentials
        self.worker = OcrWorker(png, app_id, key, self)
        self.worker.succeeded.connect(self.on_success)
        self.worker.failed.connect(self.on_failure)
        self.worker.finished.connect(self.worker_finished)
        self.worker.start()

    def on_success(self, result: OcrResult):
        self.editor.setPlainText(result.latex)
        output = format_output(result.latex, self.last_mode)
        QApplication.clipboard().setText(output)
        confidence = f" · 置信度 {result.confidence:.0%}" if result.confidence is not None else ""
        self.status.setText("已自动复制 " + MODES[self.last_mode] + confidence)
        self.mode_hint.setText("Word：Alt+= 插入公式，选择 LaTeX 输入，粘贴后转换为专业格式。"
                               if self.last_mode == "word" else "结果可编辑；下方复制按钮不会再次调用 API。")
        if self.notify_enabled and not self.pending_quit:
            self.tray.showMessage(APP_NAME, self.status.text(), QSystemTrayIcon.MessageIcon.Information, 1800)

    def on_failure(self, message):
        self.status.setText(message + " 原剪贴板内容保留。")
        if not self.pending_quit:
            self.show_result()

    def worker_finished(self):
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
        self.tray.setToolTip(f"MathSnip · {self.hotkeys['latex']} 框选公式")
        if self.pending_quit:
            QApplication.quit()

    def copy_result(self, mode):
        value = self.editor.toPlainText().strip()
        if not value:
            self.status.setText("暂无可复制内容。")
            return
        QApplication.clipboard().setText(format_output(value, mode))
        self.status.setText("已复制 " + MODES[mode])

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def quit_app(self):
        self.pending_quit = True
        self.close_overlays()
        if self.worker is not None:
            self.status.setText("等待正在进行的请求结束后退出…")
            self.show_result()
            return
        QApplication.quit()

    def cleanup(self):
        self.close_overlays()
        if self.registry:
            self.registry.close()
            QApplication.instance().removeNativeEventFilter(self.native_filter)
        self.tray.hide()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    if sys.platform != "win32":
        QMessageBox.critical(None, APP_NAME, "此工具用于 Windows 10/11，请在 Windows 上运行。")
        return 1
    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, APP_NAME, "系统托盘不可用，请在正常 Windows 桌面中运行。")
        return 1
    data_dir = app_dir()
    lock = QLockFile(str(data_dir / "instance.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, APP_NAME, "MathSnip 已经运行，请查看任务栏右侧托盘图标。")
        return 0
    window = MathSnipWindow(data_dir)
    try:
        return app.exec()
    finally:
        window.cleanup()
        lock.unlock()


def report_fatal_error() -> None:
    """Log the traceback and show a native dialog so a pythonw launch never dies silently."""
    import traceback

    details = traceback.format_exc()
    target = "(无法写入日志文件)"
    try:
        log_path = app_dir() / "error.log"
        log_path.write_text(details, encoding="utf-8")
        target = str(log_path)
    except OSError:
        pass
    last_line = details.strip().splitlines()[-1] if details.strip() else "未知错误"
    try:
        ctypes.windll.user32.MessageBoxW(
            None, f"MathSnip 启动失败：\n\n{last_line}\n\n完整信息：{target}", APP_NAME, 0x10
        )
    except Exception:
        pass


if __name__ == "__main__":
    try:
        exit_code = main()
    except BaseException:
        report_fatal_error()
        exit_code = 1
    sys.exit(exit_code)
