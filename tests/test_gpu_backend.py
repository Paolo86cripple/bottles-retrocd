from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gpu_backend import (
    GPUInfo,
    bubblejail_gpu_probe_invocation,
    bubblewrap_gpu_args,
    detect_gpus,
    gpu_by_pci,
    mesa_env,
    parse_vulkan_summary,
    preferred_gpu,
    validate_gpu_info,
    validate_gpu_probe_output,
)


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

    @staticmethod
    def _info() -> GPUInfo:
        return GPUInfo(
            "0000:03:00.0", "/dev/dri/card1", "/dev/dri/renderD128",
            "1002", "7550", "amdgpu", "AMD Radeon", False, True, 16 * 1024**3,
        )

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
        gpu = self._info()
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

        script = "printf 'probe\\n'"
        attached_args, attached_input = bubblejail_gpu_probe_invocation(
            gpu, "Bottles", script, attached=True
        )
        self.assertEqual(
            ["bubblejail", "run", "--wait", "Bottles", "/bin/sh", "-c"],
            attached_args[:-1],
        )
        self.assertTrue(attached_args[-1].startswith("PATH=/usr/bin:/bin\nexport PATH\nLC_ALL=C\nexport LC_ALL\n"))
        self.assertTrue(attached_args[-1].endswith(script))
        self.assertIsNone(attached_input)
        self.assertNotIn("--debug-shell", attached_args)

        pre_args, pre_input = bubblejail_gpu_probe_invocation(
            gpu, "Bottles", script, attached=False
        )
        self.assertIn("--debug-shell", pre_args)
        self.assertNotIn("--wait", pre_args)
        self.assertTrue(pre_input.startswith("PATH=/usr/bin:/bin\nexport PATH\nLC_ALL=C\nexport LC_ALL\n"))
        self.assertTrue(pre_input.endswith(script))

    def test_bubblewrap_rejects_implicit_default_gpu(self):
        with self.assertRaises(RuntimeError):
            bubblewrap_gpu_args(None)

    def test_validate_gpu_info_rejects_invalid_identity(self):
        good = self._info()
        invalid = (
            GPUInfo("bad", good.card_node, good.render_node, good.vendor_id, good.device_id, good.driver, good.name, False, True, None),
            GPUInfo(good.pci_address, good.card_node, good.render_node, "xyz", good.device_id, good.driver, good.name, False, True, None),
            GPUInfo(good.pci_address, good.card_node, good.render_node, good.vendor_id, "", good.driver, good.name, False, True, None),
            GPUInfo(good.pci_address, "/dev/dri/renderD1", good.render_node, good.vendor_id, good.device_id, good.driver, good.name, False, True, None),
            GPUInfo(good.pci_address, good.card_node, "/dev/dri/card9", good.vendor_id, good.device_id, good.driver, good.name, False, True, None),
            GPUInfo(good.pci_address, good.card_node, good.render_node, good.vendor_id, good.device_id, "", good.name, False, True, None),
        )
        for gpu in invalid:
            with self.subTest(gpu=gpu):
                with self.assertRaises(RuntimeError):
                    validate_gpu_info(gpu)

    def _probe_text(self, *, hidden_visible: bool = False, device: str = "7550", extra_gpu: bool = False) -> str:
        hidden = "GPU_HIDDEN_NODE_VISIBLE=/dev/dri/card2" if hidden_visible else "GPU_HIDDEN_NODE_OK=/dev/dri/card2"
        text = f"""GPU_DRI_PRIME=pci-0000_03_00_0
GPU_SELECTED_NODE_OK=/dev/dri/card1
GPU_SELECTED_NODE_OK=/dev/dri/renderD128
{hidden}
GPU0:
    vendorID = 0x1002
    deviceID = 0x{device}
    deviceName = AMD Radeon RX
"""
        if extra_gpu:
            text += """GPU1:
    vendorID = 0x1002
    deviceID = 0x164e
    deviceName = AMD Radeon Graphics
"""
        return text

    def test_probe_validation_accepts_exact_single_gpu(self):
        actual = validate_gpu_probe_output(
            self._info(), self._probe_text(), hidden_nodes=["/dev/dri/card2"]
        )
        self.assertEqual("AMD Radeon RX", actual["deviceName"])

        # A command inserted into the already-running instance through the
        # Bubblejail helper may have a fresh process environment. The post-launch
        # proof therefore ignores DRI_PRIME but still requires effective device
        # node and Vulkan isolation.
        post_text = self._probe_text().replace(
            "GPU_DRI_PRIME=pci-0000_03_00_0",
            "GPU_DRI_PRIME=",
        )
        post = validate_gpu_probe_output(
            self._info(),
            post_text,
            hidden_nodes=["/dev/dri/card2"],
            require_dri_prime=False,
        )
        self.assertEqual("AMD Radeon RX", post["deviceName"])

    def test_probe_validation_rejects_visible_nonselected_node(self):
        with self.assertRaises(RuntimeError):
            validate_gpu_probe_output(
                self._info(), self._probe_text(hidden_visible=True), hidden_nodes=["/dev/dri/card2"]
            )

    def test_probe_validation_rejects_wrong_vulkan_identity(self):
        with self.assertRaises(RuntimeError):
            validate_gpu_probe_output(
                self._info(), self._probe_text(device="164e"), hidden_nodes=["/dev/dri/card2"]
            )

    def test_probe_validation_rejects_multiple_vulkan_gpus(self):
        with self.assertRaises(RuntimeError):
            validate_gpu_probe_output(
                self._info(), self._probe_text(extra_gpu=True), hidden_nodes=["/dev/dri/card2"]
            )

    def test_probe_validation_requires_positive_proof_markers(self):
        text = self._probe_text().replace("GPU_SELECTED_NODE_OK=/dev/dri/renderD128\n", "")
        with self.assertRaises(RuntimeError):
            validate_gpu_probe_output(self._info(), text, hidden_nodes=["/dev/dri/card2"])


if __name__ == "__main__":
    unittest.main()
