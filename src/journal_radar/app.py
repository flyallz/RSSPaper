"""App for both desktop platforms."""

from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from journal_radar.adapters.source_registry import fetch_source
from journal_radar.config import APP_NAME
from journal_radar.domain.sources import create_source
from journal_radar.platform.secrets import check_backend
from journal_radar.ui.theme import STYLE

from .platform.paths import default_font
from .ui.main_window import MainWindow


def self_test() -> int:
    from .adapters.rss import parse_rss

    source = create_source("示例", "rss", "https://example.org/feed.xml")
    papers = parse_rss(
        b"<rss><channel><item><title>Sample paper</title><link>https://example.org/paper</link></item></channel></rss>",
        source,
    )
    check_backend()
    return 0 if len(papers) == 1 and papers[0]["title"] == "Sample paper" else 1


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    if "--diagnose-feed" in sys.argv:
        index = sys.argv.index("--diagnose-feed")
        url = sys.argv[index + 1]
        papers = fetch_source(create_source("诊断", "rss", url))
        print(f"OK {len(papers)} {papers[0]['title']}")
        return 0
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont(default_font(), 10))
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    if "--gui-smoke" in sys.argv:
        QTimer.singleShot(1200, app.quit)
    return app.exec()
