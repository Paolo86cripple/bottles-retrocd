from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from disc_bridge import JAIL_CD_TARGET, DiscBridge


class DiscBridgeTests(unittest.TestCase):
    def test_static_mount_bank_and_dynamic_selector(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            private_home = root / "home"
            media_root = root / "media"
            a = media_root / "disc-a"
            b = media_root / "disc-b"
            neutral = private_home / ".cache" / "empty"
            for path in (private_home, a, b, neutral):
                path.mkdir(parents=True, exist_ok=True)

            bridge = DiscBridge("Bottles", private_home, neutral, media_root)
            bridge.start(a, [a, b])
            self.assertTrue(str(bridge.jail_state_dir).startswith(str(Path.home())))
            args = bridge.bubblewrap_args()
            joined = " ".join(args)
            self.assertIn("ro-bind", args)
            self.assertIn(str(a), joined)
            self.assertIn(str(b), joined)
            self.assertIn(JAIL_CD_TARGET, joined)
            self.assertNotIn("/proc/", joined)
            self.assertNotIn(str(media_root) + " " + str(media_root), joined)

            selector = bridge.current_host
            self.assertIsNotNone(selector)
            self.assertTrue(selector.is_symlink())
            first = os.readlink(selector)
            bridge.neutralize()
            neutral_link = os.readlink(selector)
            self.assertTrue(neutral_link.endswith("/empty"))
            self.assertTrue((bridge.state_dir / "empty").is_dir())
            bridge.set_target(b)
            second = os.readlink(selector)
            self.assertNotEqual(first, second)
            self.assertTrue(second.endswith("disc-1"))


if __name__ == "__main__":
    unittest.main()
