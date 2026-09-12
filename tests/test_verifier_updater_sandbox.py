from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import verifier_updater_sandbox as us
import verifier_updater_worker as uw
from verifier_common import UpdateReport


class VerifierUpdaterSandboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app = self.root / "app"
        self.app.mkdir()
        (self.app / "verifier_updater_worker.py").write_text("# worker\n", encoding="utf-8")
        self.data = self.root / "data" / "bottles-retro-cd" / "verifier"
        self.cache = self.root / "cache" / "bottles-retro-cd" / "verifier"
        self.data.mkdir(parents=True)
        self.cache.mkdir(parents=True)
        self.archive = self.root / "archive"
        self.archive.mkdir()
        self.resolv = self.root / "resolv.conf"
        self.resolv.write_text("nameserver 127.0.0.1\n", encoding="ascii")
        self.ca = self.root / "cert.pem"
        self.ca.write_text("certificate\n", encoding="ascii")

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _has_mount(args: tuple[str, ...], flag: str, source: Path, dest: Path) -> bool:
        wanted = (flag, str(source), str(dest))
        return any(tuple(args[i:i + 3]) == wanted for i in range(max(0, len(args) - 2)))

    def _command(self) -> tuple[str, ...]:
        return us._sandbox_command(
            bwrap="/usr/bin/bwrap",
            app_dir=self.app.resolve(),
            data_dir=self.data.resolve(),
            cache_dir=self.cache.resolve(),
            network_mounts=(
                (self.resolv.resolve(), Path("/etc/resolv.conf")),
                (self.ca.resolve(), Path("/etc/ssl/cert.pem")),
            ),
        )

    def test_command_shares_only_network_namespace(self):
        args = self._command()
        self.assertIn("--unshare-all", args)
        self.assertIn("--share-net", args)
        self.assertIn("--die-with-parent", args)
        self.assertIn("--new-session", args)
        self.assertIn("--clearenv", args)
        self.assertNotIn("--proc", args)
        self.assertNotIn("/sys", args)

    def test_command_has_exact_rw_state_and_no_archive_mount(self):
        args = self._command()
        self.assertTrue(self._has_mount(args, "--bind", self.data.resolve(), self.data.resolve()))
        self.assertTrue(self._has_mount(args, "--bind", self.cache.resolve(), self.cache.resolve()))
        self.assertTrue(self._has_mount(args, "--ro-bind", self.app.resolve(), self.app.resolve()))
        self.assertNotIn(str(self.archive.resolve()), args)
        self.assertNotIn(("--ro-bind", "/etc", "/etc"), tuple(zip(args, args[1:], args[2:])))

    def test_network_files_are_exact_read_only_binds(self):
        args = self._command()
        self.assertTrue(self._has_mount(args, "--ro-bind", self.resolv.resolve(), Path("/etc/resolv.conf")))
        self.assertTrue(self._has_mount(args, "--ro-bind", self.ca.resolve(), Path("/etc/ssl/cert.pem")))
        self.assertIn("SSL_CERT_FILE", args)
        self.assertIn("/etc/ssl/cert.pem", args)

    def test_private_home_and_environment_are_forced(self):
        args = self._command()
        joined = "\n".join(args)
        self.assertIn("HOME\n/tmp/retrocd-updater-home", joined)
        self.assertIn("RETROCD_UPDATER_SANDBOX\n1", joined)
        self.assertIn("PYTHONNOUSERSITE\n1", joined)

    def test_layout_rejects_rw_state_inside_archive(self):
        with self.assertRaisesRegex(us.VerifierUpdaterSandboxError, "archivio giochi"):
            us._validate_layout(
                app_dir=self.app.resolve(),
                data_dir=(self.archive / "data").resolve(),
                cache_dir=self.cache.resolve(),
                archive=self.archive.resolve(),
            )

    def test_layout_rejects_rw_state_over_application(self):
        with self.assertRaisesRegex(us.VerifierUpdaterSandboxError, "codice applicazione"):
            us._validate_layout(
                app_dir=self.app.resolve(),
                data_dir=(self.app / "state").resolve(),
                cache_dir=self.cache.resolve(),
                archive=self.archive.resolve(),
            )

    def test_unknown_source_is_rejected_without_spawning(self):
        updater = us.VerifierUpdaterSandbox(bwrap_path="/usr/bin/bwrap")
        with mock.patch.object(us.subprocess, "run") as run:
            with self.assertRaises(us.VerifierUpdaterSandboxError):
                updater.update("mirror", archive_root=self.archive)
        run.assert_not_called()

    def test_successful_response_is_schema_and_path_checked(self):
        updater = us.VerifierUpdaterSandbox(bwrap_path="/usr/bin/bwrap")
        report = {
            "ok": True,
            "source": "redump",
            "url": "https://redump.info/datfile/pc/",
            "dat_files": 1,
            "games": 10,
            "roms": 20,
            "catalog_path": str(self.data / "catalog.sqlite3"),
        }
        completed = subprocess.CompletedProcess(("fake",), 0, json.dumps(report), "")
        with (
            mock.patch.object(us, "verifier_data_dir", return_value=self.data),
            mock.patch.object(us, "verifier_cache_dir", return_value=self.cache),
            mock.patch.object(us, "_network_mounts", return_value=((self.resolv, Path("/etc/resolv.conf")), (self.ca, Path("/etc/ssl/cert.pem")))),
            mock.patch.object(us, "_sandbox_command", return_value=("fake-bwrap",)),
            mock.patch.object(updater, "_bwrap", return_value="/usr/bin/bwrap"),
            mock.patch.object(us.subprocess, "run", return_value=completed) as run,
        ):
            result = updater.update("redump", archive_root=self.archive)
        self.assertEqual(result.source, "redump")
        self.assertEqual(result.roms, 20)
        request = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(request["source"], "redump")
        self.assertEqual(request["forbidden_archive"], str(self.archive.resolve()))
        self.assertTrue(run.call_args.kwargs["close_fds"])

    def test_worker_refuses_visible_archive_before_update(self):
        with mock.patch.object(uw, "update_official_source") as update:
            with self.assertRaisesRegex(RuntimeError, "Archivio giochi visibile"):
                uw.handle_request({"source": "redump", "forbidden_archive": str(self.archive)})
        update.assert_not_called()

    def test_worker_accepts_only_official_source_names(self):
        with mock.patch.object(uw, "update_official_source") as update:
            with self.assertRaisesRegex(RuntimeError, "non consentita"):
                uw.handle_request({"source": "custom", "forbidden_archive": None})
        update.assert_not_called()

    def test_worker_serializes_valid_report(self):
        expected = UpdateReport(
            "redump",
            "https://redump.info/datfile/pc/",
            1,
            10,
            20,
            Path("/tmp/catalog.sqlite3"),
        )
        with mock.patch.object(uw, "update_official_source", return_value=expected):
            result = uw.handle_request({"source": "redump", "forbidden_archive": None})
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "redump")
        self.assertEqual(result["roms"], 20)


if __name__ == "__main__":
    unittest.main()
