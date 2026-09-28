"""Historical test entrypoint delegating to the shared suite."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

def load_tests(loader, tests, pattern):
    return loader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
