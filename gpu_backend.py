#!/usr/bin/env python3
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

PCI_RE = re.compile(r"^[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]$")


@dataclass(frozen=True, slots=True)
class GPUInfo:
    pci_address: str
    card_node: str
    render_node: str
    vendor_id: str
    device_id: str
    driver: str
    name: str
    integrated: bool | None
    boot_vga: bool
    vram_bytes: int | None

    @property
    def mesa_dri_prime(self) -> str:
        return "pci-" + self.pci_address.replace(":", "_").replace(".", "_")

    @property
    def kind_label(self) -> str:
        if self.integrated is True:
            return "Integrata"
        if self.integrated is False:
            return "Dedicata"
        return "GPU"

    @property
    def label(self) -> str:
        suffix = Path(self.render_node).name if self.render_node else "senza render node"
        return f"{self.kind_label} · {self.name} · {self.pci_address} · {suffix}"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="ascii", errors="replace").strip()
    except OSError:
        return ""


def _read_int(path: Path) -> int | None:
    value = _read_text(path)
    if not value:
        return None
    try:
        return int(value, 0)
    except ValueError:
        return None


def _pci_name(pci_address: str) -> str:
    if shutil.which("lspci") is None:
        return f"PCI {pci_address}"
    try:
        result = subprocess.run(
            ["lspci", "-D", "-s", pci_address],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
            env={"LC_ALL": "C", "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return f"PCI {pci_address}"
    line = result.stdout.strip()
    if not line:
        return f"PCI {pci_address}"
    if ": " in line:
        return line.split(": ", 1)[1].strip()
    return line


def _integrated_hint(name: str, vram_bytes: int | None) -> bool | None:
    low = name.casefold()
    integrated_tokens = (
        "integrated", "apu", "processor graphics", "radeon graphics",
        "raphael", "mendocino", "rembrandt", "phoenix", "strix",
    )
    discrete_tokens = (
        "radeon rx", "geforce", "arc a", "arc b", "quadro", "tesla",
    )
    if any(token in low for token in discrete_tokens):
        return False
    if any(token in low for token in integrated_tokens):
        return True
    if vram_bytes is not None:
        if vram_bytes <= 2 * 1024**3:
            return True
        if vram_bytes >= 4 * 1024**3:
            return False
    return None


def detect_gpus(sys_class_drm: Path = Path("/sys/class/drm"), dev_dri: Path = Path("/dev/dri")) -> list[GPUInfo]:
    gpus: list[GPUInfo] = []
    seen_pci: set[str] = set()
    if not sys_class_drm.is_dir():
        return gpus
    for card in sorted(sys_class_drm.glob("card[0-9]*")):
        try:
            device = (card / "device").resolve(strict=True)
        except OSError:
            continue
        pci_address = device.name
        if not PCI_RE.match(pci_address) or pci_address in seen_pci:
            continue
        class_code = _read_text(device / "class").lower()
        if class_code and not class_code.startswith("0x03"):
            continue
        render_name = ""
        drm_dir = device / "drm"
        if drm_dir.is_dir():
            renders = sorted(p.name for p in drm_dir.glob("renderD[0-9]*"))
            if renders:
                render_name = renders[0]
        render_node = str(dev_dri / render_name) if render_name else ""
        vendor = _read_text(device / "vendor").removeprefix("0x").lower()
        devid = _read_text(device / "device").removeprefix("0x").lower()
        boot_vga = _read_text(device / "boot_vga") == "1"
        vram = _read_int(device / "mem_info_vram_total")
        try:
            driver = (device / "driver").resolve(strict=True).name
        except OSError:
            driver = ""
        name = _pci_name(pci_address)
        integrated = _integrated_hint(name, vram)
        gpus.append(GPUInfo(
            pci_address=pci_address.lower(), card_node=str(dev_dri / card.name), render_node=render_node,
            vendor_id=vendor, device_id=devid, driver=driver, name=name, integrated=integrated,
            boot_vga=boot_vga, vram_bytes=vram,
        ))
        seen_pci.add(pci_address)
    return gpus


def preferred_gpu(gpus: list[GPUInfo]) -> GPUInfo | None:
    if not gpus:
        return None
    integrated = [gpu for gpu in gpus if gpu.integrated is True]
    if integrated:
        return sorted(integrated, key=lambda g: (not bool(g.render_node), not g.boot_vga, g.pci_address))[0]
    known_vram = [gpu for gpu in gpus if gpu.vram_bytes is not None]
    if len(known_vram) >= 2:
        return min(known_vram, key=lambda g: (g.vram_bytes or 0, not bool(g.render_node), g.pci_address))
    boot = [gpu for gpu in gpus if gpu.boot_vga]
    if boot:
        return sorted(boot, key=lambda g: g.pci_address)[0]
    return sorted(gpus, key=lambda g: g.pci_address)[0]


def gpu_by_pci(gpus: list[GPUInfo], pci_address: str | None) -> GPUInfo | None:
    if not pci_address:
        return None
    wanted = pci_address.casefold()
    return next((gpu for gpu in gpus if gpu.pci_address.casefold() == wanted), None)


def mesa_env(gpu: GPUInfo | None) -> dict[str, str]:
    if gpu is None:
        return {}
    return {"DRI_PRIME": gpu.mesa_dri_prime, "MESA_VK_DEVICE_SELECT_FORCE_DEFAULT_DEVICE": "1"}


def bubblewrap_gpu_args(gpu: GPUInfo | None) -> list[str]:
    args: list[str] = []
    for key, value in mesa_env(gpu).items():
        args += ["--debug-bwrap-args", "setenv", key, value]

    if gpu is None:
        return args
    if not gpu.render_node:
        raise RuntimeError(f"GPU {gpu.pci_address}: render node non disponibile")

    # Bubblejail direct_rendering currently exposes the whole /dev/dri.
    # Extra bwrap arguments are appended afterwards, so mask that view and
    # re-open only the nodes belonging to the selected GPU.
    args += ["--debug-bwrap-args", "tmpfs", "/dev/dri"]
    if gpu.card_node:
        args += ["--debug-bwrap-args", "dev-bind", gpu.card_node, gpu.card_node]
    args += ["--debug-bwrap-args", "dev-bind", gpu.render_node, gpu.render_node]
    return args


def parse_vulkan_summary(text: str) -> list[dict[str, str]]:
    devices: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("GPU") and line.endswith(":"):
            if current:
                devices.append(current)
            current = {}
            continue
        if current is None or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if key in {"vendorID", "deviceID", "deviceName", "deviceType"}:
            current[key] = value
    if current:
        devices.append(current)
    return devices
