from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import verifier_sandbox as vs
import verifier_worker as vw


class VerifierSandboxPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.archive = self.root / "archive"
        self.archive.mkdir()
        self.image = self.archive / "disc.bin"
        self.image.write_bytes(b"disc")

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _has_mount(args: tuple[str, ...], flag: str, source: Path, dest: Path) -> bool:
        wanted = (flag, str(source), str(dest))
        return any(tuple(args[i:i + 3]) == wanted for i in range(max(0, len(args) - 2)))

    def _layout(self):
        app = self.root / "app"
        app.mkdir()
        (app / "verifier_worker.py").write_text("# worker\n", encoding="utf-8")
        data = self.root / "data" / "bottles-retro-cd" / "verifier"
        data.mkdir(parents=True)
        cache = self.root / "cache" / "bottles-retro-cd" / "verifier"
        cache.mkdir(parents=True)
        return app, data, cache

    def test_command_unshares_network_and_other_namespaces(self):
        app, data, cache = self._layout()
        args = vs._sandbox_command(
            self.archive.resolve(),
            bwrap="/usr/bin/bwrap",
            app_dir=app.resolve(),
            data_dir=data.resolve(),
            cache_dir=cache.resolve(),
        )
        self.assertIn("--unshare-all", args)
        self.assertIn("--die-with-parent", args)
        self.assertIn("--new-session", args)
        self.assertIn("--clearenv", args)
        self.assertNotIn("--share-net", args)
        self.assertNotIn("--proc", args)
        self.assertNotIn("/sys", args)
        self.assertNotIn("/run", args)

    def test_command_exposes_only_exact_archive_and_state_modes(self):
        app, data, cache = self._layout()
        archive = self.archive.resolve()
        app = app.resolve(); data = data.resolve(); cache = cache.resolve()
        args = vs._sandbox_command(
            archive,
            bwrap="/usr/bin/bwrap",
            app_dir=app,
            data_dir=data,
            cache_dir=cache,
        )
        self.assertTrue(self._has_mount(args, "--ro-bind", Path("/usr"), Path("/usr")))
        self.assertTrue(self._has_mount(args, "--ro-bind", archive, archive))
        self.assertTrue(self._has_mount(args, "--ro-bind", app, app))
        self.assertTrue(self._has_mount(args, "--ro-bind", data, data))
        self.assertTrue(self._has_mount(args, "--bind", cache, cache))
        self.assertNotIn("--bind-try", args)

    def test_command_has_private_home_and_tmp(self):
        app, data, cache = self._layout()
        args = vs._sandbox_command(
            self.archive.resolve(),
            bwrap="/usr/bin/bwrap",
            app_dir=app.resolve(),
            data_dir=data.resolve(),
            cache_dir=cache.resolve(),
        )
        self.assertIn("--tmpfs", args)
        self.assertIn("/tmp", args)
        joined = "\n".join(args)
        self.assertIn("HOME\n/tmp/retrocd-home", joined)
        self.assertIn("RETROCD_VERIFIER_SANDBOX\n1", joined)

    def test_absent_catalog_is_not_promoted_to_writable_state(self):
        app, _data, cache = self._layout()
        missing = self.root / "missing-data" / "bottles-retro-cd" / "verifier"
        args = vs._sandbox_command(
            self.archive.resolve(),
            bwrap="/usr/bin/bwrap",
            app_dir=app.resolve(),
            data_dir=missing,
            cache_dir=cache.resolve(),
        )
        self.assertFalse(self._has_mount(args, "--bind", missing, missing))
        self.assertFalse(self._has_mount(args, "--ro-bind", missing, missing))

    def test_rw_cache_may_not_overlap_archive(self):
        app, data, _cache = self._layout()
        with self.assertRaisesRegex(vs.VerifierSandboxError, "cache RW sovrapposta"):
            vs._validate_mount_layout(
                archive=self.archive.resolve(),
                app_dir=app.resolve(),
                data_dir=data.resolve(),
                cache_dir=self.archive.resolve() / "cache",
            )

    def test_archive_may_not_overlap_application_code(self):
        _app, data, cache = self._layout()
        with self.assertRaisesRegex(vs.VerifierSandboxError, "archivio e codice"):
            vs._validate_mount_layout(
                archive=self.archive.resolve(),
                app_dir=self.archive.resolve() / "code",
                data_dir=data.resolve(),
                cache_dir=cache.resolve(),
            )

    def test_private_cache_is_forced_to_0700(self):
        cache = self.root / "new-cache"
        result = vs._private_dir(cache)
        self.assertEqual(stat.S_IMODE(result.stat().st_mode), 0o700)
        self.assertEqual(result.stat().st_uid, os.getuid())

    def test_input_outside_archive_is_rejected_before_bwrap(self):
        outside = self.root / "outside.bin"
        outside.write_bytes(b"x")
        with self.assertRaises(vs.VerifierSandboxError):
            vs._canonical_inputs((outside,), self.archive.resolve())

    def test_missing_bwrap_fails_closed(self):
        client = vs.VerifierSandbox()
        with mock.patch.object(vs.shutil, "which", return_value=None):
            with self.assertRaisesRegex(vs.VerifierSandboxError, "manca 'bwrap'"):
                client._bwrap()

    def test_group_writable_bwrap_is_rejected(self):
        fake = self.root / "bwrap"
        fake.write_text("#!/bin/sh\n", encoding="ascii")
        fake.chmod(0o775)
        with self.assertRaisesRegex(vs.VerifierSandboxError, "non trusted"):
            vs._trusted_bwrap(str(fake))

    def test_unknown_operation_is_rejected_without_spawning(self):
        client = vs.VerifierSandbox(bwrap_path="/usr/bin/bwrap")
        with mock.patch.object(vs.subprocess, "run") as run:
            with self.assertRaises(vs.VerifierSandboxError):
                client.run("update", (self.image,), self.archive)
        run.assert_not_called()

    def test_successful_worker_response_is_schema_checked(self):
        client = vs.VerifierSandbox(bwrap_path="/usr/bin/bwrap")
        data = self.root / "state" / "bottles-retro-cd" / "verifier"
        data.mkdir(parents=True)
        cache = self.root / "cache-state" / "bottles-retro-cd" / "verifier"
        response = {"ok": True, "text": "[MATCH] disc.bin", "status": "MATCH", "matched": True}
        completed = subprocess.CompletedProcess(("fake",), 0, json.dumps(response), "")
        with (
            mock.patch.object(vs, "verifier_data_dir", return_value=data),
            mock.patch.object(vs, "verifier_cache_dir", return_value=cache),
            mock.patch.object(vs, "_sandbox_command", return_value=("fake-bwrap",)),
            mock.patch.object(client, "_bwrap", return_value="/usr/bin/bwrap"),
            mock.patch.object(vs.subprocess, "run", return_value=completed) as run,
        ):
            result = client.verify(self.image, self.archive)
        self.assertEqual(result.status, "MATCH")
        self.assertTrue(result.matched)
        request = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(request["operation"], "verify")
        self.assertEqual(request["root"], str(self.archive.resolve()))
        self.assertEqual(request["paths"], [str(self.image.resolve())])
        self.assertTrue(run.call_args.kwargs["close_fds"])

    def test_worker_error_response_fails_closed(self):
        client = vs.VerifierSandbox(bwrap_path="/usr/bin/bwrap")
        data = self.root / "state2" / "bottles-retro-cd" / "verifier"
        data.mkdir(parents=True)
        cache = self.root / "cache-state2" / "bottles-retro-cd" / "verifier"
        completed = subprocess.CompletedProcess(
            ("fake",), 2, json.dumps({"ok": False, "error": "denied"}), ""
        )
        with (
            mock.patch.object(vs, "verifier_data_dir", return_value=data),
            mock.patch.object(vs, "verifier_cache_dir", return_value=cache),
            mock.patch.object(vs, "_sandbox_command", return_value=("fake-bwrap",)),
            mock.patch.object(client, "_bwrap", return_value="/usr/bin/bwrap"),
            mock.patch.object(vs.subprocess, "run", return_value=completed),
        ):
            with self.assertRaisesRegex(vs.VerifierSandboxError, "denied"):
                client.verify(self.image, self.archive)

    def test_worker_rejects_path_escape_independently(self):
        outside = self.root / "outside-worker.bin"
        outside.write_bytes(b"x")
        with self.assertRaises(RuntimeError):
            vw._canonical_paths([str(outside)], self.archive.resolve())

    def test_worker_rejects_updater_operation(self):
        with self.assertRaisesRegex(RuntimeError, "non consentita"):
            vw.handle_request(
                {
                    "operation": "update",
                    "root": str(self.archive),
                    "paths": [str(self.image)],
                }
            )


if __name__ == "__main__":
    unittest.main()
