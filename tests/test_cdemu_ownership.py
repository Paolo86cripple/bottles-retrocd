from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cdemu_ownership as co


class FakeCDEmu:
    def __init__(self, base_count: int, resources: list[co.OwnedDevice], *, daemon="session:guid:owner"):
        self.base_count = base_count
        self.resources = list(resources)
        self.daemon = daemon
        self.loaded = {item.index: True for item in resources}
        self.remove_calls = 0
        self.unload_calls: list[int] = []

    def daemon_identity(self) -> str:
        return self.daemon

    def number_of_devices(self) -> int:
        return self.base_count + len(self.resources)

    def _resource(self, index: int) -> co.OwnedDevice:
        for item in self.resources:
            if item.index == index:
                return item
        raise RuntimeError(f"missing device {index}")

    def mapping(self, index: int) -> tuple[str, str]:
        item = self._resource(index)
        return item.sr, item.sg

    def status(self, index: int) -> tuple[bool, tuple[str, ...]]:
        item = self._resource(index)
        loaded = self.loaded.get(index, False)
        return loaded, (item.image,) if loaded else ()

    def unload(self, index: int) -> None:
        self._resource(index)
        self.loaded[index] = False
        self.unload_calls.append(index)

    def wait_loaded(self, index: int, expected: bool, timeout: float = 8.0):
        state = self.status(index)
        if state[0] is not expected:
            raise RuntimeError("unexpected loaded state")
        return state

    def remove_last_device(self) -> None:
        if not self.resources:
            raise RuntimeError("no device")
        item = self.resources.pop()
        self.loaded.pop(item.index, None)
        self.remove_calls += 1


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "state"
        self.images = []
        for n in range(3):
            path = Path(self.tmp.name) / f"disc-{n}.cue"
            path.write_text("FILE disc.bin BINARY\n", encoding="ascii")
            self.images.append(str(path.resolve()))

    def tearDown(self):
        self.tmp.cleanup()

    def store(self) -> co.CDEmuOwnershipStore:
        return co.CDEmuOwnershipStore(self.root)

    def resource(self, index: int, image: str, sr_num: int) -> co.OwnedDevice:
        return co.OwnedDevice(index, image, f"/dev/sr{sr_num}", f"/dev/sg{sr_num}", f"/run/media/test/DISC{sr_num}", 1000 + sr_num)

    def begin(self, store: co.CDEmuOwnershipStore, base: int = 2):
        store.acquire_session_lock(timeout=0)
        return store.begin(daemon_identity="session:guid:owner", base_count=base, expected_images=tuple(self.images))

    def test_journal_roundtrip_and_permissions(self):
        store = self.store()
        self.begin(store)
        store.set_pending(index=2, image=self.images[0])
        item = self.resource(2, self.images[0], 2)
        store.commit_pending(item)
        loaded = store.load()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.resources, (item,))
        self.assertEqual(stat.S_IMODE(store.root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(store.journal_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(store.lock_path.stat().st_mode), 0o600)
        store.clear()
        store.close()

    def test_slots_pending_update_does_not_depend_on_dict(self):
        store = self.store()
        session = self.begin(store)
        self.assertFalse(hasattr(session, "__dict__"))
        updated = store.set_pending(index=2, image=self.images[0])
        self.assertEqual(updated.pending.index, 2)
        store.clear()
        store.close()

    def test_second_store_is_excluded_by_live_flock(self):
        first, second = self.store(), self.store()
        first.acquire_session_lock(timeout=0)
        with self.assertRaises(co.CDEmuOwnershipBusy):
            second.acquire_session_lock(timeout=0)
        first.release_session_lock()
        second.acquire_session_lock(timeout=0)
        second.release_session_lock()

    def test_relative_state_root_is_rejected(self):
        with self.assertRaises(co.CDEmuOwnershipError):
            co.CDEmuOwnershipStore(Path("relative/state"))

    def test_state_root_symlink_is_rejected(self):
        target = Path(self.tmp.name) / "target"
        target.mkdir()
        self.root.parent.mkdir(parents=True, exist_ok=True)
        self.root.symlink_to(target, target_is_directory=True)
        store = self.store()
        with self.assertRaisesRegex(co.CDEmuOwnershipError, "symlink"):
            store.acquire_session_lock(timeout=0)

    def test_malformed_or_permissive_journal_is_rejected(self):
        store = self.store()
        store.acquire_session_lock(timeout=0)
        store.root.mkdir(parents=True, exist_ok=True)
        store.journal_path.write_text("{}", encoding="utf-8")
        os.chmod(store.journal_path, 0o644)
        with self.assertRaises(co.CDEmuOwnershipError):
            store.load()
        store.journal_path.chmod(0o600)
        with self.assertRaises(co.CDEmuOwnershipError):
            store.load()
        store.journal_path.unlink()
        store.close()

    def test_pending_must_be_next_suffix_index(self):
        store = self.store()
        self.begin(store, base=4)
        with self.assertRaises(co.CDEmuOwnershipError):
            store.set_pending(index=5, image=self.images[0])
        store.clear()
        store.close()

    def test_commit_requires_exact_pending(self):
        store = self.store()
        self.begin(store)
        store.set_pending(index=2, image=self.images[0])
        with self.assertRaises(co.CDEmuOwnershipError):
            store.commit_pending(self.resource(2, self.images[1], 2))
        store.clear()
        store.close()

    def test_activate_requires_complete_expected_set(self):
        store = self.store()
        self.begin(store)
        store.set_pending(index=2, image=self.images[0])
        store.commit_pending(self.resource(2, self.images[0], 2))
        with self.assertRaises(co.CDEmuOwnershipError):
            store.activate()
        store.clear()
        store.close()

    def test_removal_journal_is_lifo(self):
        store = self.store()
        self.begin(store)
        for offset in range(3):
            index = 2 + offset
            store.set_pending(index=index, image=self.images[offset])
            store.commit_pending(self.resource(index, self.images[offset], index))
        store.activate()
        with self.assertRaises(co.CDEmuOwnershipError):
            store.set_removing(3)
        store.set_removing(4)
        store.commit_removed(4)
        self.assertEqual([x.index for x in store.load().resources], [2, 3])
        store.clear()
        store.close()

    def test_current_process_start_ticks_are_stable(self):
        ticks = co.process_start_ticks(os.getpid())
        self.assertIsInstance(ticks, int)
        self.assertGreater(ticks, 0)

    def _prepare_full_session(self):
        store = self.store()
        self.begin(store, base=2)
        resources = []
        for offset in range(3):
            index = 2 + offset
            item = self.resource(index, self.images[offset], index)
            store.set_pending(index=index, image=self.images[offset])
            store.commit_pending(item)
            resources.append(item)
        store.activate()
        return store, resources

    def test_full_cleanup_revalidates_and_removes_reverse_suffix(self):
        store, resources = self._prepare_full_session()
        fake = FakeCDEmu(2, resources)
        mounts = {item.sr: item.mount for item in resources}

        def mount_info(sr):
            target = mounts.get(sr)
            return target, bool(target)

        def unmount(sr):
            mounts[sr] = None

        rdevs = {item.sr: item.rdev for item in resources}
        with mock.patch.object(co, "block_rdev", side_effect=lambda sr: rdevs[sr]):
            result = co.cleanup_owned_session(
                store, fake, mount_info=mount_info, unmount=unmount,
                validate_optical=lambda sr: sr, stale_recovery=False, sandbox_running=False,
            )
        self.assertTrue(result.completed)
        self.assertEqual(fake.remove_calls, 3)
        self.assertEqual(fake.unload_calls, [4, 3, 2])
        self.assertIsNone(store.load())
        store.release_session_lock()

    def test_mapping_drift_refuses_any_remove_and_keeps_journal(self):
        store, resources = self._prepare_full_session()
        fake = FakeCDEmu(2, resources)
        original_mapping = fake.mapping
        fake.mapping = lambda index: ("/dev/sr99", "") if index == 3 else original_mapping(index)
        rdevs = {item.sr: item.rdev for item in resources}
        with mock.patch.object(co, "block_rdev", side_effect=lambda sr: rdevs[sr]):
            with self.assertRaises(co.CDEmuOwnershipError):
                co.cleanup_owned_session(
                    store, fake, mount_info=lambda sr: (None, False), unmount=lambda sr: None,
                    validate_optical=lambda sr: sr, stale_recovery=False, sandbox_running=False,
                )
        self.assertEqual(fake.remove_calls, 0)
        self.assertIsNotNone(store.load())
        store.clear()
        store.close()

    def test_pending_extra_device_is_never_guessed_or_removed(self):
        store = self.store()
        self.begin(store, base=2)
        store.set_pending(index=2, image=self.images[0])
        item = self.resource(2, self.images[0], 2)
        fake = FakeCDEmu(2, [item])
        with mock.patch.object(co, "session_owner_alive", return_value=False):
            with self.assertRaisesRegex(co.CDEmuOwnershipError, "pending"):
                co.cleanup_owned_session(
                    store, fake, mount_info=lambda sr: (None, False), unmount=lambda sr: None,
                    validate_optical=lambda sr: sr, stale_recovery=True, sandbox_running=False,
                )
        self.assertEqual(fake.remove_calls, 0)
        self.assertIsNotNone(store.load())
        store.clear()
        store.close()

    def test_pending_without_extra_device_is_reconciled_without_mutation(self):
        store = self.store()
        self.begin(store, base=2)
        store.set_pending(index=2, image=self.images[0])
        fake = FakeCDEmu(2, [])
        with mock.patch.object(co, "session_owner_alive", return_value=False):
            result = co.cleanup_owned_session(
                store, fake, mount_info=lambda sr: (None, False), unmount=lambda sr: None,
                validate_optical=lambda sr: sr, stale_recovery=True, sandbox_running=False,
            )
        self.assertTrue(result.completed)
        self.assertEqual(fake.remove_calls, 0)
        self.assertIsNone(store.load())
        store.release_session_lock()

    def test_write_ahead_remove_recovers_if_device_already_gone(self):
        store, resources = self._prepare_full_session()
        store.set_removing(resources[-1].index)
        # Model crash after upstream RemoveDevice but before commit_removed.
        fake = FakeCDEmu(2, resources[:-1])
        mounts = {item.sr: None for item in resources}
        rdevs = {item.sr: item.rdev for item in resources}
        with mock.patch.object(co, "session_owner_alive", return_value=False), \
             mock.patch.object(co, "block_rdev", side_effect=lambda sr: rdevs[sr]):
            result = co.cleanup_owned_session(
                store, fake, mount_info=lambda sr: (mounts.get(sr), False), unmount=lambda sr: None,
                validate_optical=lambda sr: sr, stale_recovery=True, sandbox_running=False,
            )
        self.assertTrue(result.completed)
        self.assertEqual(fake.remove_calls, 2)
        self.assertIsNone(store.load())
        store.release_session_lock()

    def test_daemon_change_clears_only_obsolete_journal(self):
        store, resources = self._prepare_full_session()
        fake = FakeCDEmu(2, resources, daemon="session:new-guid:new-owner")
        result = co.cleanup_owned_session(
            store, fake, mount_info=lambda sr: (None, False), unmount=lambda sr: None,
            validate_optical=lambda sr: sr, stale_recovery=True, sandbox_running=False,
        )
        self.assertTrue(result.completed)
        self.assertTrue(result.obsolete_journal_cleared)
        self.assertEqual(fake.remove_calls, 0)
        self.assertIsNone(store.load())
        store.release_session_lock()

    def test_running_sandbox_blocks_cleanup_before_mutation(self):
        store, resources = self._prepare_full_session()
        fake = FakeCDEmu(2, resources)
        with self.assertRaises(co.CDEmuOwnershipError):
            co.cleanup_owned_session(
                store, fake, mount_info=lambda sr: (None, False), unmount=lambda sr: None,
                validate_optical=lambda sr: sr, stale_recovery=False, sandbox_running=True,
            )
        self.assertEqual(fake.remove_calls, 0)
        store.clear()
        store.close()


if __name__ == "__main__":
    unittest.main()
