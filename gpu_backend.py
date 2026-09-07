#!/usr/bin/env python3
from __future__ import annotations

import re
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

PCI_RE = re.compile(r"^[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]$")
HEX4_RE = re.compile(r"^[0-9a-fA-F]{4}$")
CARD_NODE_RE = re.compile(r"^card[0-9]+$")
RENDER_NODE_RE = re.compile(r"^renderD[0-9]+$")
GPU_PROBE_PATH = "/usr/bin:/bin"


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


def validate_gpu_info(gpu: GPUInfo) -> None:
    """Validate the stable GPU identity before it can affect sandbox policy."""
    if not PCI_RE.fullmatch(gpu.pci_address):
        raise RuntimeError(f"GPU con indirizzo PCI non valido: {gpu.pci_address!r}")
    if not HEX4_RE.fullmatch(gpu.vendor_id):
        raise RuntimeError(f"GPU {gpu.pci_address}: vendor ID non valido: {gpu.vendor_id!r}")
    if not HEX4_RE.fullmatch(gpu.device_id):
        raise RuntimeError(f"GPU {gpu.pci_address}: device ID non valido: {gpu.device_id!r}")
    if not gpu.card_node or not CARD_NODE_RE.fullmatch(Path(gpu.card_node).name):
        raise RuntimeError(f"GPU {gpu.pci_address}: DRM card node non valido: {gpu.card_node!r}")
    if not gpu.render_node or not RENDER_NODE_RE.fullmatch(Path(gpu.render_node).name):
        raise RuntimeError(f"GPU {gpu.pci_address}: DRM render node non valido: {gpu.render_node!r}")
    if not gpu.driver:
        raise RuntimeError(f"GPU {gpu.pci_address}: driver kernel non determinabile")


def validate_gpu_runtime(gpu: GPUInfo) -> None:
    """Fail closed unless both selected DRM nodes are live character devices."""
    validate_gpu_info(gpu)
    for label, raw in (("card", gpu.card_node), ("render", gpu.render_node)):
        path = Path(raw)
        try:
            mode = path.stat().st_mode
        except OSError as exc:
            raise RuntimeError(f"GPU {gpu.pci_address}: nodo DRM {label} non accessibile: {path}: {exc}") from exc
        if not stat.S_ISCHR(mode):
            raise RuntimeError(f"GPU {gpu.pci_address}: nodo DRM {label} non è un character device: {path}")


def mesa_env(gpu: GPUInfo | None) -> dict[str, str]:
    if gpu is None:
        return {}
    validate_gpu_info(gpu)
    return {"DRI_PRIME": gpu.mesa_dri_prime, "MESA_VK_DEVICE_SELECT_FORCE_DEFAULT_DEVICE": "1"}


def bubblewrap_gpu_args(gpu: GPUInfo | None) -> list[str]:
    if gpu is None:
        raise RuntimeError("GPU obbligatoria: rifiutato avvio con selezione Mesa implicita.")
    validate_gpu_info(gpu)
    args: list[str] = []
    for key, value in mesa_env(gpu).items():
        args += ["--debug-bwrap-args", "setenv", key, value]

    # Bubblejail direct_rendering currently exposes the whole /dev/dri.
    # Extra bwrap arguments are appended afterwards, so mask that view and
    # re-open only the nodes belonging to the selected GPU.
    args += ["--debug-bwrap-args", "tmpfs", "/dev/dri"]
    args += ["--debug-bwrap-args", "dev-bind", gpu.card_node, gpu.card_node]
    args += ["--debug-bwrap-args", "dev-bind", gpu.render_node, gpu.render_node]
    return args


def bubblejail_gpu_probe_invocation(
    gpu: GPUInfo,
    instance: str,
    script: str,
    *,
    attached: bool,
) -> tuple[list[str], str | None]:
    """Build the Bubblejail invocation used by the strict GPU probe.

    Bubblejail 0.10.4 does not attach ``--debug-shell`` to an already-running
    instance: the CLI switches to its helper RPC path and forwards only the
    positional command. Therefore a running-instance probe must use ``--wait``
    plus an explicit shell command, which executes inside the existing sandbox
    and returns combined stdout/stderr through the helper.

    Probe commands run with a fixed system PATH and C locale. This avoids both
    helper-RPC environment differences and user-controlled PATH entries from
    changing which ``vulkaninfo`` binary supplies the security proof.
    """
    validate_gpu_info(gpu)
    if not instance or instance.startswith("-"):
        raise RuntimeError(f"Nome istanza Bubblejail non valido: {instance!r}")
    probe_script = (
        f"PATH={GPU_PROBE_PATH}\n"
        "export PATH\n"
        "LC_ALL=C\n"
        "export LC_ALL\n"
        + script
    )
    if attached:
        return ["bubblejail", "run", "--wait", instance, "/bin/sh", "-c", probe_script], None
    return ["bubblejail", "run", *bubblewrap_gpu_args(gpu), "--debug-shell", instance], probe_script


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


def validate_gpu_probe_output(
    gpu: GPUInfo,
    text: str,
    *,
    hidden_nodes: list[str] | tuple[str, ...] = (),
    require_dri_prime: bool = True,
) -> dict[str, str]:
    """Validate a Bubblejail GPU probe; absence of required proof is failure.

    The pre-launch probe requires DRI_PRIME because it starts with the exact
    runtime bwrap environment. A command injected through Bubblejail's helper
    into an already-running instance may receive a fresh process environment,
    so the post-launch proof intentionally ignores that environment marker while
    still requiring the effective DRM-node and Vulkan identity isolation.
    """
    validate_gpu_info(gpu)
    if "GPU_VULKANINFO_MISSING=1" in text:
        raise RuntimeError("vulkaninfo non è disponibile dentro Bubblejail.")

    if require_dri_prime:
        dri_prime = ""
        for line in text.splitlines():
            if line.startswith("GPU_DRI_PRIME="):
                dri_prime = line.split("=", 1)[1].strip()
                break
        if dri_prime != gpu.mesa_dri_prime:
            raise RuntimeError(
                f"DRI_PRIME non confermato nella jail: atteso {gpu.mesa_dri_prime!r}, ottenuto {dri_prime!r}."
            )

    for node in (gpu.card_node, gpu.render_node):
        if f"GPU_SELECTED_NODE_OK={node}" not in text:
            raise RuntimeError(f"Nodo DRM selezionato non confermato nella jail: {node}")
        if f"GPU_SELECTED_NODE_MISSING={node}" in text:
            raise RuntimeError(f"Nodo DRM selezionato mancante nella jail: {node}")

    for node in hidden_nodes:
        if f"GPU_HIDDEN_NODE_VISIBLE={node}" in text:
            raise RuntimeError(f"Isolamento GPU fallito; nodo non selezionato visibile: {node}")
        if f"GPU_HIDDEN_NODE_OK={node}" not in text:
            raise RuntimeError(f"Assenza del nodo non selezionato non confermata: {node}")

    devices = parse_vulkan_summary(text)
    if len(devices) != 1:
        raise RuntimeError(f"La jail deve esporre una sola GPU Vulkan; rilevate {len(devices)}.")
    actual = devices[0]
    vendor = actual.get("vendorID", "").lower().removeprefix("0x").zfill(4)
    device = actual.get("deviceID", "").lower().removeprefix("0x").zfill(4)
    if vendor != gpu.vendor_id.lower() or device != gpu.device_id.lower():
        raise RuntimeError(
            f"GPU Vulkan diversa da quella richiesta: attesa {gpu.vendor_id}:{gpu.device_id}, "
            f"ottenuta {vendor}:{device} ({actual.get('deviceName', 'nome sconosciuto')})."
        )
    return actual
