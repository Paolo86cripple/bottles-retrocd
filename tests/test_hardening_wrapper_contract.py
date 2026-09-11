from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARDENING = ROOT / "bottles-retro-cd-gui-hardening.py"
RUNTIME_AUDIT = ROOT / "bottles-retro-cd-gui-runtime-audit.py"


def _window_method(path: Path, name: str) -> ast.FunctionDef | None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Window":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == name:
                    return item
    return None


class HardeningWrapperContractTests(unittest.TestCase):
    def test_non_live_launch_lock_is_consolidated_in_hardening_wrapper(self):
        method = _window_method(HARDENING, "launch_bottles")
        self.assertIsNotNone(method)
        source = ast.unparse(method)
        self.assertIn("acquire_session_lock", source)
        self.assertIn("release_session_lock", source)
        self.assertIn("Journal CDEmu non risolto prima dell'avvio non-live", source)
        self.assertNotIn("with self._cdemu_operation()", source)

    def test_runtime_audit_does_not_override_launch_bottles(self):
        self.assertIsNone(_window_method(RUNTIME_AUDIT, "launch_bottles"))


if __name__ == "__main__":
    unittest.main()
