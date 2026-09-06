from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gpu_backend import bubblewrap_gpu_args, detect_gpus, gpu_by_pci, mesa_env, parse_vulkan_summary, preferred_gpu


class GpuBackendTests(unittest.TestCase):
    def _gpu(self, root: Path, card: str, pci: str, *, vram: int, boot: bool, render: str):
        drm = root / "sys" / "class" / "drm"
        dev = root / "sys" / "devices" / "pci0000:00" / pci
        dev.mkdir(parents=True)
        (dev / "class").write_text("0x030000\n")
        (dev / "vendor").write_text("0x1002\n")
        (dev / "device").write_text("0x0001\n")
        (dev / "boot_vga").write_text("1\n" if boot else "0\n")
        (dev / "mem_info_vram_total").write_text(str(vram) + "\n")
        (dev / "drm" / render).mkdir(parents=True)
        card_path = drm / card
        card_path.mkdir(parents=True, exist_ok=True)
        (card_path / "device").symlink_to(dev, target_is_directory=True)

    @mock.patch("gpu_backend._pci_name")
    def test_detect_and_prefer_integrated(self, pci_name):
        pci_name.side_effect = lambda pci: "AMD Ryzen Processor Graphics" if "0a:00" in pci else "AMD Radeon RX 9070 XT"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._gpu(root, "card1", "0000:03:00.0", vram=16 * 1024**3, boot=True, render="renderD128")
            self._gpu(root, "card2", "0000:0a:00.0", vram=512 * 1024**2, boot=False, render="renderD129")
            gpus = detect_gpus(root / "sys/class/drm", root / "dev/dri")
            self.assertEqual(2, len(gpus))
            self.assertEqual("0000:0a:00.0", preferred_gpu(gpus).pci_address)
            self.assertEqual("0000:03:00.0", gpu_by_pci(gpus, "0000:03:00.0").pci_address)

    def test_parse_vulkan_summary(self):
        devices = parse_vulkan_summary("""GPU0:\n\tvendorID = 0x1002\n\tdeviceID = 0x7550\n\tdeviceName = AMD Radeon RX\n""")
        self.assertEqual([{"vendorID": "0x1002", "deviceID": "0x7550", "deviceName": "AMD Radeon RX"}], devices)

    def test_mesa_env_uses_stable_pci_selector(self):
        from gpu_backend import GPUInfo
        gpu = GPUInfo("0000:03:00.0", "/dev/dri/card1", "/dev/dri/renderD128", "1002", "7550", "amdgpu", "AMD Radeon", False, True, 16 * 1024**3)
        env = mesa_env(gpu)
        self.assertEqual("pci-0000_03_00_0", env["DRI_PRIME"])
        self.assertEqual("1", env["MESA_VK_DEVICE_SELECT_FORCE_DEFAULT_DEVICE"])
        args = bubblewrap_gpu_args(gpu)
        self.assertIn("setenv", args)
        self.assertIn("tmpfs", args)
        self.assertIn("/dev/dri", args)
        self.assertIn("/dev/dri/card1", args)
        self.assertIn("/dev/dri/renderD128", args)
        self.assertEqual(2, args.count("dev-bind"))


if __name__ == "__main__":
    unittest.main()
