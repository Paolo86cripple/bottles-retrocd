from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cdemu_lifecycle import CommandResult, inspect_lifecycle, update_command


KERNEL = "7.2.3-1-cachyos"


class FakeRunner:
    def __init__(self):
        self.packages = {
            "cdemu-daemon": "3.3.1-1",
            "libmirage": "3.3.2-1",
            "cdemu-client": "3.3.1-1",
            "vhba-module-dkms": "20260313-1",
        }
        self.updates = ""
        self.interface = "(uint32 7, uint32 0)\n"
        self.service_active = True
        self.dbus_reachable = True
        self.module_path = f"/usr/lib/modules/{KERNEL}/updates/dkms/vhba.ko.zst"
        self.module_owner = ""
        self.module_owner_version = ""

    def __call__(self, args, timeout):
        args = tuple(args)
        if args[:2] == ("pacman", "-Qu"):
            return CommandResult(0 if self.updates else 1, self.updates)
        if args[:2] == ("pacman", "-Q") and len(args) == 3:
            name = args[2]
            version = self.packages.get(name)
            if version is None:
                return CommandResult(1, f"error: package '{name}' was not found\n")
            return CommandResult(0, f"{name} {version}\n")
        if args[:2] == ("pacman", "-Qo") and len(args) == 3:
            if self.module_owner and args[2] == self.module_path:
                version = self.module_owner_version or "1-1"
                return CommandResult(0, f"{self.module_path} is owned by {self.module_owner} {version}\n")
            return CommandResult(1, f"error: No package owns {args[2]}\n")
        if args == ("modinfo", "-n", "vhba"):
            return CommandResult(0, self.module_path + "\n")
        if args == ("systemctl", "--user", "is-active", "cdemu-daemon.service"):
            return CommandResult(0 if self.service_active else 3, "active\n" if self.service_active else "inactive\n")
        if args and args[0] == "gdbus":
            method = args[-1]
            if not self.dbus_reachable:
                return CommandResult(1, "D-Bus unavailable\n")
            if method == "org.freedesktop.DBus.Peer.Ping":
                return CommandResult(0, "()\n")
            if method.endswith("GetDaemonVersion"):
                return CommandResult(0, "('3.3.1',)\n")
            if method.endswith("GetLibraryVersion"):
                return CommandResult(0, "('3.3.2',)\n")
            if method.endswith("GetDaemonInterfaceVersion2"):
                return CommandResult(0, self.interface)
            if method.endswith("GetNumberOfDevices"):
                return CommandResult(0, "(uint32 1,)\n")
        return CommandResult(127, "unexpected command: " + " ".join(args))


class LifecycleTests(unittest.TestCase):
    def make_roots(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        sys_root = root / "sys"
        dev_root = root / "dev"
        modules_root = root / "modules"
        (sys_root / "module" / "vhba").mkdir(parents=True)
        dev_root.mkdir(parents=True)
        (dev_root / "vhba_ctl").symlink_to("/dev/null")
        (modules_root / KERNEL / "build").mkdir(parents=True)
        return tmp, sys_root, dev_root, modules_root

    def inspect(self, runner: FakeRunner):
        tmp, sys_root, dev_root, modules_root = self.make_roots()
        self.addCleanup(tmp.cleanup)
        return inspect_lifecycle(
            runner=runner,
            kernel=KERNEL,
            sys_root=sys_root,
            dev_root=dev_root,
            modules_root=modules_root,
        )

    def test_healthy_cachyos_dkms_stack_passes(self):
        report = self.inspect(FakeRunner())
        self.assertTrue(report.ok, report.failures)
        self.assertEqual(report.vhba_provider, "vhba-module-dkms")
        self.assertEqual(report.daemon_version, "3.3.1")
        self.assertEqual(report.libmirage_runtime_version, "3.3.2")
        self.assertEqual(report.interface_version, "7.0")
        self.assertEqual(report.device_count, 1)
        self.assertTrue(report.vhba_control_char)

    def test_kernel_bundled_vhba_passes_without_standalone_package(self):
        runner = FakeRunner()
        runner.packages.pop("vhba-module-dkms")
        runner.module_path = f"/lib/modules/{KERNEL}/kernel/drivers/scsi/vhba/vhba.ko.zst"
        runner.module_owner = "linux-cachyos"
        runner.module_owner_version = "7.2.3-1"
        report = self.inspect(runner)
        self.assertTrue(report.ok, report.failures)
        self.assertEqual(report.vhba_provider, "kernel:linux-cachyos")
        command = update_command(report)
        self.assertNotIn("vhba-module-dkms", command)
        self.assertNotIn("vhba-module", command)

    def test_kernel_bundled_vhba_does_not_require_headers_for_runtime(self):
        runner = FakeRunner()
        runner.packages.pop("vhba-module-dkms")
        runner.module_path = f"/lib/modules/{KERNEL}/kernel/drivers/scsi/vhba/vhba.ko.zst"
        runner.module_owner = "linux-cachyos"
        runner.module_owner_version = "7.2.3-1"
        tmp, sys_root, dev_root, modules_root = self.make_roots()
        self.addCleanup(tmp.cleanup)
        (modules_root / KERNEL / "build").rmdir()
        report = inspect_lifecycle(
            runner=runner,
            kernel=KERNEL,
            sys_root=sys_root,
            dev_root=dev_root,
            modules_root=modules_root,
        )
        self.assertTrue(report.ok, report.failures)
        self.assertEqual(report.vhba_provider, "kernel:linux-cachyos")
        self.assertFalse(report.kernel_headers_present)

    def test_cdemu_client_is_optional(self):
        runner = FakeRunner()
        runner.packages.pop("cdemu-client")
        report = self.inspect(runner)
        self.assertTrue(report.ok, report.failures)
        self.assertNotIn("cdemu-client", update_command(report))

    def test_wrong_kernel_module_path_fails(self):
        runner = FakeRunner()
        runner.packages.pop("vhba-module-dkms")
        runner.packages["vhba-module"] = "20260313-43"
        runner.module_path = "/usr/lib/modules/7.2.3-arch1-1/extramodules/vhba.ko.zst"
        runner.module_owner = "vhba-module"
        runner.module_owner_version = "20260313-43"
        report = self.inspect(runner)
        self.assertFalse(report.ok)
        self.assertTrue(any("fuori dalla directory del kernel corrente" in item for item in report.failures))

    def test_missing_headers_fail_for_dkms(self):
        runner = FakeRunner()
        tmp, sys_root, dev_root, modules_root = self.make_roots()
        self.addCleanup(tmp.cleanup)
        (modules_root / KERNEL / "build").rmdir()
        report = inspect_lifecycle(
            runner=runner,
            kernel=KERNEL,
            sys_root=sys_root,
            dev_root=dev_root,
            modules_root=modules_root,
        )
        self.assertFalse(report.ok)
        self.assertTrue(any("headers del kernel corrente assenti per DKMS" in item for item in report.failures))

    def test_typed_interface_version_does_not_parse_uint32_as_version(self):
        runner = FakeRunner()
        runner.interface = "(uint32 7, uint32 4)\n"
        report = self.inspect(runner)
        self.assertEqual(report.interface_version, "7.4")
        self.assertTrue(report.ok, report.failures)

    def test_incompatible_interface_major_fails(self):
        runner = FakeRunner()
        runner.interface = "(uint32 8, uint32 0)\n"
        report = self.inspect(runner)
        self.assertFalse(report.ok)
        self.assertTrue(any("interfaccia CDEmu incompatibile" in item for item in report.failures))

    def test_pending_component_update_is_reported_without_execution(self):
        runner = FakeRunner()
        runner.updates = "libmirage 3.3.2-1 -> 3.3.3-1\n"
        report = self.inspect(runner)
        lib = next(item for item in report.packages if item.name == "libmirage")
        self.assertEqual(lib.pending_version, "3.3.3-1")
        self.assertTrue(any("aggiornamento disponibile: libmirage" in item for item in report.warnings))
        command = update_command(report)
        self.assertEqual(command[:5], ("sudo", "pacman", "-Syu", "--needed", "cdemu-daemon"))
        self.assertIn("vhba-module-dkms", command)

    def test_unreachable_daemon_fails_closed(self):
        runner = FakeRunner()
        runner.dbus_reachable = False
        report = self.inspect(runner)
        self.assertFalse(report.ok)
        self.assertTrue(any("daemon CDEmu non raggiungibile" in item for item in report.failures))


if __name__ == "__main__":
    unittest.main()
