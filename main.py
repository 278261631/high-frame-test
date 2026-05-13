from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from qhyccd_sdk import QHYCCD, QHYCCDError


APP_DIR = Path(__file__).resolve().parent


def append_trace(message: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S.%f}] {message}"
    print(line)
    with (APP_DIR / "test_qt_python_trace.log").open("a", encoding="utf-8") as log_file:
        log_file.write(line + "\n")


def make_safe_tag(raw: str) -> str:
    safe = re.sub(r"\W+", "_", raw, flags=re.ASCII).strip("_")
    return safe or "image"


def make_checkerboard_brush() -> QBrush:
    tile = QPixmap(24, 24)
    tile.fill(QColor(198, 198, 198))

    painter = QPainter(tile)
    painter.fillRect(0, 0, 12, 12, QColor(162, 162, 162))
    painter.fillRect(12, 12, 12, 12, QColor(162, 162, 162))
    painter.end()

    return QBrush(tile)


class CameraSingleWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("QHYCCD Single Mode Demo (Python + Qt)")
        self.resize(1000, 700)

        self.camera: QHYCCD | None = None
        self.last_image: QImage | None = None
        self.last_image_tag1 = "single"
        self.last_image_tag2 = "image"

        root_layout = QVBoxLayout(self)
        button_layout = QHBoxLayout()
        proc_layout = QHBoxLayout()

        self.connect_button = QPushButton("连接相机")
        self.capture_button = QPushButton("单帧拍摄")
        self.capture_proc_button = QPushButton("单帧拍摄(proc)")
        self.save_button = QPushButton("保存当前图像")
        self.capture_button.setEnabled(False)
        self.capture_proc_button.setEnabled(False)
        self.save_button.setEnabled(False)

        self.exposure_label = QLabel("曝光(us):")
        self.exposure_spin = QDoubleSpinBox()
        self.exposure_spin.setDecimals(0)
        self.exposure_spin.setRange(1.0, 60_000_000.0)
        self.exposure_spin.setSingleStep(1000.0)
        self.exposure_spin.setValue(100_000.0)
        self.exposure_spin.setSuffix(" us")

        button_layout.addWidget(self.connect_button)
        button_layout.addWidget(self.capture_button)
        button_layout.addWidget(self.capture_proc_button)
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.exposure_label)
        button_layout.addWidget(self.exposure_spin)

        self.proc_overscan_check = QCheckBox("proc_overscan")
        self.proc_binx_label = QLabel("proc_binx:")
        self.proc_binx_spin = QSpinBox()
        self.proc_binx_spin.setRange(1, 8)
        self.proc_binx_spin.setValue(1)
        self.proc_biny_label = QLabel("proc_biny:")
        self.proc_biny_spin = QSpinBox()
        self.proc_biny_spin.setRange(1, 8)
        self.proc_biny_spin.setValue(1)
        self.proc_bin_avg_check = QCheckBox("proc_bin_avg")

        proc_layout.addWidget(self.proc_overscan_check)
        proc_layout.addWidget(self.proc_binx_label)
        proc_layout.addWidget(self.proc_binx_spin)
        proc_layout.addWidget(self.proc_biny_label)
        proc_layout.addWidget(self.proc_biny_spin)
        proc_layout.addWidget(self.proc_bin_avg_check)

        self.status_label = QLabel("状态：未连接")
        self.image_label = QLabel()
        self.image_label.setMinimumSize(960, 540)
        self.image_label.setStyleSheet("color:#404040;")
        self.image_label.setAutoFillBackground(True)
        self.image_label.setBackgroundRole(QPalette.ColorRole.Window)
        image_palette = self.image_label.palette()
        image_palette.setBrush(QPalette.ColorRole.Window, make_checkerboard_brush())
        self.image_label.setPalette(image_palette)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setText("等待图像...")

        root_layout.addLayout(button_layout)
        root_layout.addLayout(proc_layout)
        root_layout.addWidget(self.status_label)
        root_layout.addWidget(self.image_label, 1)

        self.connect_button.clicked.connect(self.connect_camera)
        self.capture_button.clicked.connect(self.capture_single_frame)
        self.capture_proc_button.clicked.connect(self.capture_single_frame_proc)
        self.save_button.clicked.connect(self.save_current_image)

    def connect_camera(self) -> bool:
        append_trace("connect_camera: enter")
        if self.camera is None:
            try:
                self.camera = QHYCCD()
            except QHYCCDError as exc:
                QMessageBox.critical(self, "错误", str(exc))
                return False

        try:
            chip_info = self.camera.connect_first_camera(self.exposure_spin.value())
        except QHYCCDError as exc:
            append_trace(f"connect_camera: failed: {exc}")
            QMessageBox.critical(self, "错误", str(exc))
            return False

        self.status_label.setText(
            "状态：已连接，分辨率 "
            f"{chip_info.image_width} x {chip_info.image_height}，曝光 {self.exposure_spin.value():.0f} us"
        )
        self.capture_button.setEnabled(True)
        self.capture_proc_button.setEnabled(True)
        append_trace(
            "connect_camera: ok "
            f"w={chip_info.image_width} h={chip_info.image_height} bpp={chip_info.bpp}"
        )
        return True

    def capture_single_frame(self) -> None:
        if not self.connect_camera() or self.camera is None:
            return

        exposure_us = self.exposure_spin.value()
        self._run_busy_action("状态：正在单帧采集...", self._capture_single_frame_impl, exposure_us)

    def _capture_single_frame_impl(self, exposure_us: float) -> None:
        assert self.camera is not None
        frame = self.camera.capture_single_frame(exposure_us)
        self.render_frame_and_show_status(
            frame.width,
            frame.height,
            frame.bpp,
            frame.channels,
            frame.data,
            "GetQHYCCDSingleFrame",
            f"single_exp{int(exposure_us)}",
        )

    def capture_single_frame_proc(self) -> None:
        if not self.connect_camera() or self.camera is None:
            return

        exposure_us = self.exposure_spin.value()
        self._run_busy_action("状态：正在 proc 单帧采集...", self._capture_single_frame_proc_impl, exposure_us)

    def _capture_single_frame_proc_impl(self, exposure_us: float) -> None:
        assert self.camera is not None
        proc_overscan = self.proc_overscan_check.isChecked()
        proc_binx = self.proc_binx_spin.value()
        proc_biny = self.proc_biny_spin.value()
        proc_bin_avg = self.proc_bin_avg_check.isChecked()

        frame = self.camera.capture_single_frame_proc(
            exposure_us,
            proc_overscan,
            proc_binx,
            proc_biny,
            proc_bin_avg,
        )

        proc_desc = (
            "GetQHYCCDSingleFrame_proc("
            f"overscan={int(proc_overscan)}, binx={proc_binx}, "
            f"biny={proc_biny}, bin_avg={int(proc_bin_avg)})"
        )
        proc_tag = (
            f"proc_o{int(proc_overscan)}_x{proc_binx}_y{proc_biny}_"
            f"a{int(proc_bin_avg)}_exp{int(exposure_us)}"
        )
        self.render_frame_and_show_status(
            frame.width,
            frame.height,
            frame.bpp,
            frame.channels,
            frame.data,
            proc_desc,
            proc_tag,
        )

    def _run_busy_action(self, status: str, action, *args) -> None:
        self.status_label.setText(status)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()

        try:
            action(*args)
        except QHYCCDError as exc:
            self.status_label.setText(f"状态：采集失败，{exc}")
            QMessageBox.critical(self, "错误", str(exc))
        except Exception as exc:
            self.status_label.setText(f"状态：采集失败，{exc}")
            QMessageBox.critical(self, "错误", f"采集失败：{exc}")
        finally:
            QApplication.restoreOverrideCursor()

    def save_current_image(self) -> None:
        if self.last_image is None or self.last_image.isNull():
            self.status_label.setText("状态：没有可保存的图像")
            return

        target_dir = APP_DIR / datetime.now().strftime("%Y%m%d")
        target_dir.mkdir(parents=True, exist_ok=True)

        file_name = (
            f"{datetime.now():%H%M%S}_"
            f"{make_safe_tag(self.last_image_tag1)}_"
            f"{make_safe_tag(self.last_image_tag2)}.png"
        )
        file_path = target_dir / file_name
        if not self.last_image.save(str(file_path), "PNG"):
            self.status_label.setText("状态：保存 PNG 失败")
            return

        self.status_label.setText(f"状态：图像已保存到 {file_path}")

    def render_frame_and_show_status(
        self,
        width: int,
        height: int,
        bpp: int,
        channels: int,
        frame_data: bytes,
        source_name: str,
        file_tag2: str,
    ) -> None:
        if channels != 1:
            QMessageBox.warning(self, "提示", "示例当前仅显示单通道图像")
            return

        if bpp == 8:
            display_bytes = frame_data[: width * height]
        elif bpp == 16:
            pixel_count = width * height
            src16 = np.frombuffer(frame_data, dtype=np.uint16, count=pixel_count)
            min_v = int(src16.min())
            max_v = int(src16.max())
            if max_v == min_v:
                display_bytes = bytes(pixel_count)
            else:
                stretched = ((src16.astype(np.float32) - min_v) * (255.0 / (max_v - min_v))).astype(np.uint8)
                display_bytes = stretched.tobytes()
        else:
            QMessageBox.warning(self, "提示", "示例当前仅显示 8bit/16bit 单通道图像")
            return

        image = QImage(
            display_bytes,
            width,
            height,
            width,
            QImage.Format.Format_Grayscale8,
        ).copy()
        if image.isNull():
            QMessageBox.critical(self, "错误", "QImage 构建失败")
            return

        pixmap = QPixmap.fromImage(image)
        self.image_label.setPixmap(
            pixmap.scaled(
                self.image_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.last_image = image
        self.last_image_tag1 = "proc" if "_proc" in source_name else "single"
        self.last_image_tag2 = file_tag2
        self.save_button.setEnabled(True)
        self.status_label.setText(
            f"状态：采集成功 [{source_name}]，输出尺寸 {width} x {height}, bpp={bpp}, channels={channels}"
        )

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.camera is not None:
            self.camera.close()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    window = CameraSingleWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
