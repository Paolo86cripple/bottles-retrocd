from __future__ import annotations

import json
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import runtime_surface_audit as rsa


class RuntimeSurfaceAuditTests(unittest.TestCase):
    def payload(self, **overrides):
        raw = {
            "schema": 1,
            "uid": 1000,
            "xdg_runtime_dir": "/run/user/1000",
            "display": ":0",
            "wayland_display": "wayland-0",
            "dbus_address": "unix:path=/run/user/1000/bus",
            "dbus_names": ["org.freedesktop.DBus", "org.freedesktop.portal.Desktop"],
            "dbus_unique_count": 3,
            "runtime_entries": ["socket /run/user/1000/wayland-0"],
            "filesystem_sockets": ["/run/user/1000/wayland-0", "/tmp/.X11-unix/X0"],
            "proc_unix_names": ["/run/user/1000/wayland-0", "@/tmp/dbus-test"],
            "network_interfaces": ["lo"],
            "network_routes": [],
            "devices": ["char /dev/dri/renderD128 226:128"],
            "truncated": [],
            "warnings": [],
        }
        raw.update(overrides)
        return raw

    def output(self, **overrides):
        return rsa.AUDIT_PREFIX + json.dumps(self.payload(**overrides), separators=(",", ":")) + "\n"

    def test_probe_source_compiles(self):
        compile(rsa.runtime_surface_probe_source(), "<runtime-audit-probe>", "exec")

    def test_invocation_attaches_to_running_instance_without_debug_shell(self):
        args = rsa.bubblejail_runtime_audit_invocation("Bottles")
        self.assertEqual(args[:4], ["/usr/bin/bubblejail", "run", "--wait", "Bottles"])
        self.assertEqual(args[4:6], ["/usr/bin/python3", "-c"])
        self.assertNotIn("--debug-shell", args)
        self.assertNotIn("--debug-bwrap-args", args)

    def test_invalid_instance_is_rejected(self):
        for name in ("", "-Bottles", "../Bottles", "Bottles/name", "x" * 129):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                rsa.bubblejail_runtime_audit_invocation(name)

    def test_valid_json_record_is_parsed_exactly(self):
        report = rsa.parse_runtime_audit_output("bubblejail noise\n" + self.output())
        self.assertEqual(report.uid, 1000)
        self.assertEqual(report.network_interfaces, ("lo",))
        self.assertEqual(report.dbus_names, ("org.freedesktop.DBus", "org.freedesktop.portal.Desktop"))
        self.assertEqual(report.devices, ("char /dev/dri/renderD128 226:128",))

    def test_duplicate_evidence_record_is_rejected(self):
        text = self.output() + self.output()
        with self.assertRaisesRegex(RuntimeError, "ottenuti=2"):
            rsa.parse_runtime_audit_output(text)

    def test_wrong_schema_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "schema"):
            rsa.parse_runtime_audit_output(self.output(schema=2))

    def test_boolean_uid_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "uid"):
            rsa.parse_runtime_audit_output(self.output(uid=True))

    def test_oversized_list_is_rejected(self):
        values = [f"org.example.N{i}" for i in range(rsa.MAX_ITEMS + 1)]
        with self.assertRaisesRegex(RuntimeError, "dbus_names"):
            rsa.parse_runtime_audit_output(self.output(dbus_names=values))

    def test_oversized_total_output_is_rejected_before_json(self):
        with self.assertRaisesRegex(RuntimeError, "eccessivamente grande"):
            rsa.parse_runtime_audit_output("x" * (2 * 1024 * 1024 + 1))

    def test_formatter_is_diagnostic_not_policy_verdict(self):
        report = rsa.parse_runtime_audit_output(self.output())
        text = rsa.format_runtime_audit(report)
        self.assertIn("diagnostico read-only; nessuna policy modificata", text)
        self.assertIn("[DBUS] 2", text)
        self.assertIn("[SOCKET-FS] 2", text)
        self.assertIn("[DEVICE] 1", text)
        self.assertNotIn("[PASS]", text)
        self.assertNotIn("[FAIL]", text)

    def test_probe_is_bounded_and_uses_argv_subprocesses(self):
        source = rsa.runtime_surface_probe_source()
        self.assertIn("MAX_ITEMS = 256", source)
        self.assertIn("MAX_TEXT = 4096", source)
        self.assertIn("subprocess.run(", source)
        forbidden = (
            "shell" + "=True",
            "os.system" + "(",
            "ev" + "al(",
            "ex" + "ec(",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
