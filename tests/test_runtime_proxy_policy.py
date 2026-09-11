from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import runtime_proxy_policy as rpp


class RuntimeProxyPolicyTests(unittest.TestCase):
    def test_profile_policy_reads_gnome_toolkit_and_debug(self):
        dconf, raw = rpp.profile_dbus_policy({
            "gnome_toolkit": {"dconf_dbus": False},
            "debug": {"raw_dbus_session_args": ["--talk=org.example.App"]},
        })
        self.assertFalse(dconf)
        self.assertEqual(raw, ("--talk=org.example.App",))

    def test_profile_policy_rejects_non_boolean_dconf(self):
        with self.assertRaisesRegex(RuntimeError, "dconf_dbus"):
            rpp.profile_dbus_policy({"gnome_toolkit": {"dconf_dbus": "false"}})

    def test_exact_and_wildcard_dconf_policy_are_detected(self):
        args = (
            "--filter",
            "--see=ca.desrt.dconf",
            "--talk=ca.desrt.dconf",
            "--call=ca.desrt.*=org.freedesktop.DBus.Introspectable.Introspect@/ca/desrt/dconf",
            "--talk=org.example.App",
        )
        matched = rpp._dconf_policy_args(args)
        self.assertEqual(matched, (args[2], args[3]))

    def test_see_only_is_not_reported_as_dconf_call_grant(self):
        self.assertEqual(rpp._dconf_policy_args(("--see=ca.desrt.dconf",)), ())

    def test_inspect_finds_only_exact_instance_session_proxy(self):
        with tempfile.TemporaryDirectory() as td:
            proc = Path(td)
            pid = proc / "1234"
            pid.mkdir()
            import os
            socket = f"/run/user/{os.getuid()}/bubblejail/Bottles/dbus_session_proxy"
            argv = [
                "/usr/bin/xdg-dbus-proxy",
                "unix:path=/run/user/1000/bus",
                socket,
                "--filter",
                "--talk=ca.desrt.dconf",
                "--call=org.freedesktop.portal.Desktop=*",
            ]
            (pid / "cmdline").write_bytes(b"\x00".join(x.encode() for x in argv) + b"\x00")

            report = rpp.inspect_proxy_policy(
                "Bottles",
                {"gnome_toolkit": {"dconf_dbus": False}},
                proc_root=proc,
            )
            self.assertEqual(report.proxy_pids, (1234,))
            self.assertIn("--talk=ca.desrt.dconf", report.active_policy_args)
            self.assertEqual(report.dconf_policy_args, ("--talk=ca.desrt.dconf",))

    def test_validate_accepts_exact_filtered_proxy_without_dconf(self):
        report = rpp.ProxyPolicyReport(
            gnome_dconf_dbus=False,
            raw_session_args=(),
            proxy_pids=(55,),
            active_policy_args=("--filter",),
            dconf_policy_args=(),
            warnings=(),
        )
        self.assertIs(rpp.validate_proxy_policy(report), report)

    def test_validate_rejects_profile_dconf(self):
        report = rpp.ProxyPolicyReport(
            gnome_dconf_dbus=True,
            raw_session_args=(),
            proxy_pids=(55,),
            active_policy_args=("--filter", "--talk=ca.desrt.dconf"),
            dconf_policy_args=("--talk=ca.desrt.dconf",),
            warnings=(),
        )
        with self.assertRaisesRegex(RuntimeError, "dconf_dbus=true"):
            rpp.validate_proxy_policy(report)

    def test_validate_rejects_effective_dconf_grant_even_when_profile_is_off(self):
        report = rpp.ProxyPolicyReport(
            gnome_dconf_dbus=False,
            raw_session_args=(),
            proxy_pids=(55,),
            active_policy_args=("--filter", "--call=ca.desrt.dconf=org.example.Read@/x"),
            dconf_policy_args=("--call=ca.desrt.dconf=org.example.Read@/x",),
            warnings=(),
        )
        with self.assertRaisesRegex(RuntimeError, "grant dconf effettivo"):
            rpp.validate_proxy_policy(report)

    def test_validate_rejects_missing_filter_or_ambiguous_proxy(self):
        report = rpp.ProxyPolicyReport(
            gnome_dconf_dbus=False,
            raw_session_args=(),
            proxy_pids=(55, 56),
            active_policy_args=(),
            dconf_policy_args=(),
            warnings=("proxy sessione Bubblejail ambiguo: 2 processi",),
        )
        with self.assertRaisesRegex(RuntimeError, "attesi=1"):
            rpp.validate_proxy_policy(report)

    def test_formatter_keeps_profile_and_effective_policy_separate(self):
        report = rpp.ProxyPolicyReport(
            gnome_dconf_dbus=False,
            raw_session_args=(),
            proxy_pids=(55,),
            active_policy_args=("--filter", "--call=ca.desrt.dconf=org.example.Read@/x"),
            dconf_policy_args=("--call=ca.desrt.dconf=org.example.Read@/x",),
            warnings=(),
        )
        text = rpp.format_proxy_policy(report)
        self.assertIn("gnome_toolkit.dconf_dbus=false", text)
        self.assertIn("[HOST-PROXY-DCONF] 1", text)
        self.assertIn("--call=ca.desrt.dconf=org.example.Read@/x", text)


if __name__ == "__main__":
    unittest.main()
