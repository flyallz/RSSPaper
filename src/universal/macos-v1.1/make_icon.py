"""Render the shared SVG logo into a macOS .icns application icon."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def main() -> None:
    folder = Path(__file__).resolve().parent / "assets"
    renderer = QSvgRenderer(str(folder / "icon.svg"))
    if not renderer.isValid():
        raise RuntimeError("无法读取通用版图标")
    app = QGuiApplication([])
    with tempfile.TemporaryDirectory() as temporary:
        iconset = Path(temporary) / "JournalRadar.iconset"
        iconset.mkdir()
        for points in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                pixels = points * scale
                image = QImage(pixels, pixels, QImage.Format.Format_ARGB32)
                image.fill(Qt.GlobalColor.transparent)
                painter = QPainter(image)
                renderer.render(painter)
                painter.end()
                suffix = "@2x" if scale == 2 else ""
                if not image.save(str(iconset / f"icon_{points}x{points}{suffix}.png")):
                    raise RuntimeError("无法生成图标 PNG")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(folder / "icon.icns")], check=True)
    app.quit()


if __name__ == "__main__":
    main()
