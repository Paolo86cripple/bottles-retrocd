from __future__ import annotations

import json
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import runtime_bus_audit as rba


class RuntimeBusAuditTests(unittest.TestCase):
    def payload(self, **overrides):
        raw = {
            "schema": 2,
            "system_names": ["org.freedesktop.DBus", "org.freedesktop.login1"],
            "system_unique_count": 2,
            "dconf_talk": True,
            "dconf_detail": "Introspect riuscito: TALK effettivo",
            "warnings": [],
        }
        raw.update(overrides)
        return raw

    def output(self, **overrides):
        return rba.BUS_AUDIT_PREFIX + json.dumps(self.payload(**overrides), separators=(",", ":")) + "\n"

    def test_probe_source_compiles(self):
        compile(rba.runtime_bus_probe_source(), "<runtime-bus-audit-probe>", "exec")

    def test_probe_uses_read_only_real_dconf_method(self):
        source = rba.runtime_bus_probe_source()
        self.assertIn("org.freedesktop.DBus.Introspectable.Introspect", source)
        self.assertIn("/ca/desrt/dconf", source)
        self.assertNotIn("Peer.Ping", source)
        self.assertNotIn("ca.desrt.dconf.Writer", source)

    def test_invocation_attaches_without_debug_shell(self):
        args = rba.bubblejail_runtime_bus_audit_invocation("Bottles")
        self.assertEqual(args[:4], ["/usr/bin/bubblejail", "run", "--wait", "Bottles"])
        self.assertEqual(args[4:6], ["/usr/bin/python3", "-c"])
        self.assertNotIn("--debug-shell", args)
        self.assertNotIn("--debug-bwrap-args", args)

    def test_invalid_instance_is_rejected(self):
        for name in ("", "-Bottles", "../Bottles", "Bottles/name", "x" * 129):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                rba.bubblejail_runtime_bus_audit_invocation(name)

    def test_valid_report_is_parsed(self):
        report = rba.parse_runtime_bus_audit_output(self.output())
        self.assertEqual(report.system_names, ("org.freedesktop.DBus", "org.freedesktop.login1"))
        self.assertEqual(report.system_unique_count, 2)
        self.assertTrue(report.dconf_talk)
        self.assertEqual(report.dconf_detail, "Introspect riuscito: TALK effettivo")

    def test_duplicate_record_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "ottenuti=2"):
            rba.parse_runtime_bus_audit_output(self.output() + self.output())

    def test_wrong_schema_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "schema"):
            rba.parse_runtime_bus_audit_output(self.output(schema=1))

    def test_bool_unique_count_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "system_unique_count"):
            rba.parse_runtime_bus_audit_output(self.output(system_unique_count=True))

    def test_non_bool_talk_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "dconf_talk"):
            rba.parse_runtime_bus_audit_output(self.output(dconf_talk="yes"))

    def test_oversized_names_are_rejected(self):
        values = [f"org.example.N{i}" for i in range(rba.MAX_ITEMS + 1)]
        with self.assertRaisesRegex(RuntimeError, "system_names"):
            rba.parse_runtime_bus_audit_output(self.output(system_names=values))

    def test_formatter_stays_diagnostic(self):
        report = rba.parse_runtime_bus_audit_output(self.output())
        text = rba.format_runtime_bus_audit(report)
        self.assertIn("D-Bus system: well-known=2 unique=2", text)
        self.assertIn("ca.desrt.dconf: TALK consentito", text)
        self.assertIn("[DBUS-SYSTEM] 2", text)
        self.assertNotIn("[PASS]", text)
        self.assertNotIn("[FAIL]", text)


if __name__ == "__main__":
    unittest.main()
