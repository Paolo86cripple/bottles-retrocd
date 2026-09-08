from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from retro_optical import (  # noqa: E402
    OpticalExposure,
    bubblejail_optical_probe_invocation,
    bubblewrap_optical_control_mask_args,
    validate_optical_probe_output,
)


BASE = """\
OPT_VHBA_HIDDEN=1
OPT_CDEMU_DBUS_BLOCKED=1
"""

MASKED_BASE = """\
OPT_VHBA_MASKED_NULL=1
OPT_VHBA_DEVICE=1:3
OPT_CDEMU_DBUS_BLOCKED=1
"""


class RetroOpticalTests(unittest.TestCase):
    def test_no_optical_surface(self):
        exposure = OpticalExposure()
        result = validate_optical_probe_output(exposure, BASE + "OPT_MOUNT_ABSENT=1\n")
        self.assertTrue(result["vhba_hidden"])
        self.assertFalse(result["vhba_masked"])
        self.assertEqual(result["vhba_state"], "hidden")
        self.assertTrue(result["cdemu_dbus_blocked"])
        self.assertEqual(result["sr"], "")
        self.assertEqual(result["sg"], "")
        self.assertFalse(result["mount"])

    def test_masked_vhba_is_accepted_only_with_positive_marker(self):
        exposure = OpticalExposure()
        result = validate_optical_probe_output(exposure, MASKED_BASE + "OPT_MOUNT_ABSENT=1\n")
        self.assertFalse(result["vhba_hidden"])
        self.assertTrue(result["vhba_masked"])
        self.assertEqual(result["vhba_state"], "masked-null")

    def test_control_mask_binds_dev_null_over_vhba(self):
        args = bubblewrap_optical_control_mask_args()
        self.assertEqual(
            args,
            ["--debug-bwrap-args", "dev-bind", "/dev/null", "/dev/vhba_ctl"],
        )

    def test_ro_mount_only(self):
        exposure = OpticalExposure(mount_expected=True)
        text = BASE + "OPT_MOUNT_PRESENT=1\nOPT_MOUNT_DIRECTORY=1\nOPT_MOUNT_OPTIONS=ro,nosuid,nodev\n"
        result = validate_optical_probe_output(exposure, text)
        self.assertTrue(result["mount"])
        self.assertIn("ro", str(result["mount_options"]))

    def test_exact_sr_only(self):
        exposure = OpticalExposure(raw_expected=True, sr_path="/dev/sr3")
        text = BASE + "OPT_SR_VISIBLE=/dev/sr3\nOPT_MOUNT_ABSENT=1\n"
        result = validate_optical_probe_output(exposure, text)
        self.assertEqual(result["sr"], "/dev/sr3")
        self.assertEqual(result["sg"], "")

    def test_exact_sr_and_sg(self):
        exposure = OpticalExposure(
            raw_expected=True,
            sr_path="/dev/sr2",
            sg_expected=True,
            sg_path="/dev/sg7",
            mount_expected=True,
        )
        text = (
            BASE
            + "OPT_SR_VISIBLE=/dev/sr2\n"
            + "OPT_SG_VISIBLE=/dev/sg7\n"
            + "OPT_MOUNT_PRESENT=1\nOPT_MOUNT_DIRECTORY=1\nOPT_MOUNT_OPTIONS=ro,relatime\n"
        )
        result = validate_optical_probe_output(exposure, text)
        self.assertEqual(result["sr"], "/dev/sr2")
        self.assertEqual(result["sg"], "/dev/sg7")

    def test_rejects_visible_vhba_control(self):
        text = "OPT_VHBA_VISIBLE=1\nOPT_CDEMU_DBUS_BLOCKED=1\nOPT_MOUNT_ABSENT=1\n"
        with self.assertRaisesRegex(RuntimeError, "vhba_ctl"):
            validate_optical_probe_output(OpticalExposure(), text)

    def test_rejects_ambiguous_vhba_proof(self):
        text = (
            "OPT_VHBA_HIDDEN=1\nOPT_VHBA_MASKED_NULL=1\n"
            "OPT_CDEMU_DBUS_BLOCKED=1\nOPT_MOUNT_ABSENT=1\n"
        )
        with self.assertRaisesRegex(RuntimeError, "vhba_ctl"):
            validate_optical_probe_output(OpticalExposure(), text)

    def test_rejects_missing_stat_for_vhba_mask(self):
        text = "OPT_STAT_MISSING=1\nOPT_VHBA_VISIBLE=1\nOPT_CDEMU_DBUS_BLOCKED=1\nOPT_MOUNT_ABSENT=1\n"
        with self.assertRaisesRegex(RuntimeError, "stat"):
            validate_optical_probe_output(OpticalExposure(), text)

    def test_rejects_reachable_cdemu_dbus(self):
        text = "OPT_VHBA_HIDDEN=1\nOPT_CDEMU_DBUS_REACHABLE=1\nOPT_MOUNT_ABSENT=1\n"
        with self.assertRaisesRegex(RuntimeError, "raggiungibile"):
            validate_optical_probe_output(OpticalExposure(), text)

    def test_rejects_missing_dbus_proof_tool(self):
        text = "OPT_VHBA_HIDDEN=1\nOPT_GDBUS_MISSING=1\nOPT_MOUNT_ABSENT=1\n"
        with self.assertRaisesRegex(RuntimeError, "gdbus"):
            validate_optical_probe_output(OpticalExposure(), text)

    def test_rejects_unexpected_sr(self):
        text = BASE + "OPT_SR_VISIBLE=/dev/sr0\nOPT_MOUNT_ABSENT=1\n"
        with self.assertRaisesRegex(RuntimeError, "nodi /dev/srX"):
            validate_optical_probe_output(OpticalExposure(), text)

    def test_rejects_wrong_sr(self):
        exposure = OpticalExposure(raw_expected=True, sr_path="/dev/sr1")
        text = BASE + "OPT_SR_VISIBLE=/dev/sr2\nOPT_MOUNT_ABSENT=1\n"
        with self.assertRaisesRegex(RuntimeError, "nodi /dev/srX"):
            validate_optical_probe_output(exposure, text)

    def test_rejects_unexpected_sg(self):
        exposure = OpticalExposure(raw_expected=True, sr_path="/dev/sr0")
        text = BASE + "OPT_SR_VISIBLE=/dev/sr0\nOPT_SG_VISIBLE=/dev/sg0\nOPT_MOUNT_ABSENT=1\n"
        with self.assertRaisesRegex(RuntimeError, "nodi /dev/sgX"):
            validate_optical_probe_output(exposure, text)

    def test_rejects_rw_mount(self):
        exposure = OpticalExposure(mount_expected=True)
        text = BASE + "OPT_MOUNT_PRESENT=1\nOPT_MOUNT_DIRECTORY=1\nOPT_MOUNT_OPTIONS=rw,nosuid,nodev\n"
        with self.assertRaisesRegex(RuntimeError, "read-only"):
            validate_optical_probe_output(exposure, text)

    def test_rejects_mount_when_not_authorised(self):
        text = BASE + "OPT_MOUNT_PRESENT=1\nOPT_MOUNT_DIRECTORY=1\nOPT_MOUNT_OPTIONS=ro\n"
        with self.assertRaisesRegex(RuntimeError, "senza autorizzazione"):
            validate_optical_probe_output(OpticalExposure(), text)

    def test_rejects_sg_without_sr(self):
        exposure = OpticalExposure(sg_expected=True, sg_path="/dev/sg0")
        with self.assertRaisesRegex(RuntimeError, "senza /dev/srX"):
            exposure.validate()

    def test_rejects_invalid_device_names(self):
        with self.assertRaisesRegex(RuntimeError, "mapping sr"):
            OpticalExposure(raw_expected=True, sr_path="/dev/sda").validate()
        with self.assertRaisesRegex(RuntimeError, "mapping sg"):
            OpticalExposure(
                raw_expected=True,
                sr_path="/dev/sr0",
                sg_expected=True,
                sg_path="/dev/null",
            ).validate()

    def test_attached_probe_uses_running_instance_rpc(self):
        args = bubblejail_optical_probe_invocation("Bottles", "printf ok\\n")
        self.assertEqual(args[:4], ["bubblejail", "run", "--wait", "Bottles"])
        self.assertEqual(args[4:6], ["/bin/sh", "-c"])
        self.assertIn("PATH=/usr/bin:/bin", args[6])
        self.assertIn("printf ok", args[6])
        self.assertNotIn("--debug-shell", args)

    def test_rejects_option_like_instance(self):
        with self.assertRaisesRegex(RuntimeError, "Nome istanza"):
            bubblejail_optical_probe_invocation("--help", "true")


if __name__ == "__main__":
    unittest.main()
