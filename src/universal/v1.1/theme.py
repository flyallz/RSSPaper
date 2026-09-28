"""Compatibility export of the shared stylesheet."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from journal_radar.ui.theme import STYLE
