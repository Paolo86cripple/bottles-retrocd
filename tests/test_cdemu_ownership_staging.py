from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cdemu_ownership as co


class FakeCDEmu:
    def __init__(self, base_count: int, resources: list[co.OwnedDevice]):
        self.base_count = base_count
        self.resources = list(resources)
        self.loaded = {item.index: False for item in resources}
        self.remove_calls = 0
        self.unload_calls: list[int] = []

    def daemon_identity(self) -> str:
        return "session:guid:owner"

    def number_of_devices(self) -> int:
        return self.base_count + len(self.resources)

    def _resource(self, index: int) -> co.OwnedDevice:
        for item in self.resources:
            if item.index == index:
                return item
        raise RuntimeError(index)

    def mapping(self, index: int) -> tuple[str, str]:
        item = self._resource(index)
        return item.sr, item.sg

    def status(self, index: int) -> tuple[bool, tuple[str, ...]]:
        item = self._resource(index)
        loaded = self.loaded[index]
        return loaded, (item.image,) if loaded else ()

    def unload(self, index: int) -> None:
        self.loaded[index] = False
        self.unload_calls.append(index)

    def wait_loaded(self, index: int, expected: bool, timeout: float = 8.0):
        state = self.status(index)
        if state[0] is not expected:
            raise RuntimeError("unexpected state")
        return state

    def remove_last_device(self) -> None:
        item = self.resources.pop()
        self.loaded.pop(item.index, None)
        self.remove_calls += 1


class StagedOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "state"
        self.image = Path(self.tmp.name) / "disc.cue"
        self.image.write_text("FILE disc.bin BINARY\n", encoding="ascii")
        self.image = self.image.resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def prepared_store(self):
        store = co.CDEmuOwnershipStore(self.root)
        store.acquire_session_lock(timeout=0)
        store.begin(
            daemon_identity="session:guid:owner",
            base_count=1,
            expected_images=(str(self.image),),
        )
        store.set_pending(index=1, image=str(self.image))
        resource = co.OwnedDevice(1, str(self.image), "/dev/sr1", "/dev/sg1", "", 1001)
        store.commit_pending(resource)
        return store, resource

    def test_mapping_stage_roundtrips_without_mount(self):
        store, resource = self.prepared_store()
        loaded = store.load()
        self.assertEqual(loaded.resources, (resource,))
        self.assertEqual(loaded.resources[0].mount, "")
        store.clear()
        store.close()

    def test_activate_refuses_resource_without_journaled_ro_mount(self):
        store, _resource = self.prepared_store()
        with self.assertRaisesRegex(co.CDEmuOwnershipError, "mount"):
            store.activate()
        store.clear()
        store.close()

    def test_mount_stage_is_persisted_then_allows_activation(self):
        store, _resource = self.prepared_store()
        mount = Path(self.tmp.name) / "mounted-disc"
        mount.mkdir()
        updated = store.update_resource_mount(1, str(mount))
        self.assertEqual(updated.resources[0].mount, str(mount.resolve()))
        active = store.activate()
        self.assertEqual(active.phase, "active")
        store.clear()
        store.close()

    def test_crash_after_mapping_before_load_is_recoverable(self):
        store, resource = self.prepared_store()
        fake = FakeCDEmu(1, [resource])
        with mock.patch.object(co, "block_rdev", return_value=resource.rdev), \
             mock.patch.object(co, "session_owner_alive", return_value=False):
            result = co.cleanup_owned_session(
                store,
                fake,
                mount_info=lambda _sr: (None, False),
                unmount=lambda _sr: None,
                validate_optical=lambda sr: sr,
                stale_recovery=True,
                sandbox_running=False,
            )
        self.assertTrue(result.completed)
        self.assertEqual(fake.remove_calls, 1)
        self.assertEqual(fake.unload_calls, [])
        self.assertIsNone(store.load())
        store.release_session_lock()

    def test_crash_after_load_before_mount_is_recoverable(self):
        store, resource = self.prepared_store()
        fake = FakeCDEmu(1, [resource])
        fake.loaded[1] = True
        with mock.patch.object(co, "block_rdev", return_value=resource.rdev), \
             mock.patch.object(co, "session_owner_alive", return_value=False):
            result = co.cleanup_owned_session(
                store,
                fake,
                mount_info=lambda _sr: (None, False),
                unmount=lambda _sr: None,
                validate_optical=lambda sr: sr,
                stale_recovery=True,
                sandbox_running=False,
            )
        self.assertTrue(result.completed)
        self.assertEqual(fake.unload_calls, [1])
        self.assertEqual(fake.remove_calls, 1)
        self.assertIsNone(store.load())
        store.release_session_lock()

    def test_unjournaled_mount_remains_fail_closed(self):
        store, resource = self.prepared_store()
        fake = FakeCDEmu(1, [resource])
        fake.loaded[1] = True
        with mock.patch.object(co, "block_rdev", return_value=resource.rdev), \
             mock.patch.object(co, "session_owner_alive", return_value=False):
            with self.assertRaisesRegex(co.CDEmuOwnershipError, "journal"):
                co.cleanup_owned_session(
                    store,
                    fake,
                    mount_info=lambda _sr: ("/run/media/test/UNKNOWN", True),
                    unmount=lambda _sr: None,
                    validate_optical=lambda sr: sr,
                    stale_recovery=True,
                    sandbox_running=False,
                )
        self.assertEqual(fake.remove_calls, 0)
        self.assertIsNotNone(store.load())
        store.clear()
        store.close()


if __name__ == "__main__":
    unittest.main()
