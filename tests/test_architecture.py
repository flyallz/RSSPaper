"""Guard the dependency boundaries that make future source additions maintainable."""

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src/journal_radar"


class ArchitectureTests(unittest.TestCase):
    def test_domain_is_independent_of_ui_network_storage_and_platform(self):
        for path in (PACKAGE / "domain").glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom):
                    self.assertLessEqual(node.level, 1, str(path))
                    module = node.module or ""
                    self.assertFalse(
                        module.startswith(("PySide6", "urllib.request", "requests")), str(path)
                    )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertFalse(alias.name.startswith(("PySide6", "requests")), str(path))

    def test_business_and_adapters_do_not_import_widgets(self):
        for folder in ("services", "adapters", "platform"):
            for path in (PACKAGE / folder).glob("*.py"):
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        module = (
                            node.module
                            if isinstance(node, ast.ImportFrom)
                            else " ".join(alias.name for alias in node.names)
                        )
                        self.assertNotIn("PySide6", module or "", str(path))

    def test_both_launchers_use_the_same_application(self):
        for folder in ("macos-v1.1", "v1.1"):
            path = ROOT / "src/universal" / folder / "app.py"
            tree = ast.parse(path.read_text(encoding="utf-8"))
            self.assertTrue(
                any(
                    isinstance(node, ast.ImportFrom) and node.module == "journal_radar.app"
                    for node in tree.body
                )
            )
            self.assertFalse(any(isinstance(node, ast.ClassDef) for node in tree.body))
