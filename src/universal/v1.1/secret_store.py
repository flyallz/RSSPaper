"""Compatibility exports for the platform secret store."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from journal_radar.platform.secrets import load_api_key, save_api_key
