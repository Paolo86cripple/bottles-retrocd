from __future__ import annotations

import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest import mock

import cdemu_update_cli as updater


class FakeSandbox:
    running_value = False

    def __init__(self, instance):
        self.instance = instance

    def running(self):
        return self.running_value


class UpdateCliTests(unittest.TestCase):
    @staticmethod
    def healthy_report():
        return SimpleNamespace(
            ok=True,
            daemon_service_active=True,
            daemon_reachable=True,
            vhba_provider="kernel:linux-cachyos",
            failures=(),
        )

    def run_main(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = updater.main()
        return rc, output.getvalue()

    @mock.patch.object(updater, "SandboxBackend", FakeSandbox)
    def test_refuses_when_bottles_is_running(self):
        FakeSandbox.running_value = True
        try:
            rc, output = self.run_main()
        finally:
            FakeSandbox.running_value = False
        self.assertEqual(2, rc)
        self.assertIn("Bottles/Bubblejail è attivo", output)

    @mock.patch.object(updater, "SandboxBackend", FakeSandbox)
    @mock.patch.object(updater, "_media_preflight", return_value=(False, "media loaded"))
    def test_refuses_when_media_are_loaded(self, _media):
        rc, output = self.run_main()
        self.assertEqual(2, rc)
        self.assertIn("media loaded", output)

    @mock.patch.object(updater, "SandboxBackend", FakeSandbox)
    @mock.patch.object(updater, "_media_preflight", return_value=(True, ""))
    @mock.patch.object(updater, "inspect_lifecycle")
    @mock.patch.object(updater, "format_report", return_value="REPORT")
    @mock.patch.object(updater, "update_command", return_value=("sudo", "pacman", "-Syu", "--needed", "cdemu-daemon"))
    @mock.patch.object(updater.shutil, "which", return_value="/usr/bin/sudo")
    @mock.patch("builtins.input", return_value="NO")
    @mock.patch.object(updater.subprocess, "run")
    def test_decline_changes_nothing(
        self,
        run,
        _input,
        _which,
        _command,
        _format,
        inspect,
        _media,
    ):
        inspect.return_value = self.healthy_report()
        rc, output = self.run_main()
        self.assertEqual(0, rc)
        self.assertIn("Operazione annullata", output)
        run.assert_not_called()

    @mock.patch.object(updater, "SandboxBackend", FakeSandbox)
    @mock.patch.object(updater, "_media_preflight", return_value=(True, ""))
    @mock.patch.object(updater, "inspect_lifecycle")
    @mock.patch.object(updater, "format_report", return_value="REPORT")
    @mock.patch.object(
        updater,
        "update_command",
        return_value=("sudo", "pacman", "-Syu", "--needed", "cdemu-daemon", "libmirage"),
    )
    @mock.patch.object(updater.shutil, "which", return_value="/usr/bin/sudo")
    @mock.patch("builtins.input", return_value="AGGIORNA")
    @mock.patch.object(updater.subprocess, "run")
    def test_confirmed_update_stops_daemon_runs_pacman_and_restarts(
        self,
        run,
        _input,
        _which,
        command,
        _format,
        inspect,
        _media,
    ):
        before = self.healthy_report()
        after = self.healthy_report()
        inspect.side_effect = [before, after]
        run.return_value = SimpleNamespace(returncode=0)

        rc, output = self.run_main()

        self.assertEqual(0, rc)
        self.assertIn("Componenti Retro Optical aggiornati", output)
        expected = list(command.return_value)
        self.assertEqual(
            [
                mock.call(["systemctl", "--user", "stop", updater.SERVICE], check=False),
                mock.call(expected, check=False),
                mock.call(["systemctl", "--user", "start", updater.SERVICE], check=False),
            ],
            run.call_args_list,
        )


if __name__ == "__main__":
    unittest.main()
