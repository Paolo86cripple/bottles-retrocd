#!/usr/bin/env python3
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

CDEMU_DBUS_NAME = "net.sf.cdemu.CDEmuDaemon"
CDEMU_DBUS_PATH = "/Daemon"
VHBA_CONTROL_PATH = "/dev/vhba_ctl"
JAIL_CD_TARGET = "/mnt/cdemu"
OPTICAL_PROBE_PATH = "/usr/bin:/bin"

_SR_RE = re.compile(r"^/dev/sr[0-9]+$")
_SG_RE = re.compile(r"^/dev/sg[0-9]+$")


@dataclass(frozen=True, slots=True)
class OpticalExposure:
    """Exact optical surface intentionally exposed to one Bottles launch.

    CDEmu itself, libMirage and the VHBA control device are never part of this
    surface: they remain trusted host-side components. Only a verified RO
    filesystem view and, when compatibility requires it, the exact CDEmu
    sr/sg mapping may cross the Bubblejail boundary.
    """

    mount_expected: bool = False
    raw_expected: bool = False
    sr_path: str = ""
    sg_expected: bool = False
    sg_path: str = ""

    def validate(self) -> None:
        if self.raw_expected:
            if not _SR_RE.fullmatch(self.sr_path):
                raise RuntimeError(f"Retro Optical: mapping sr non valido: {self.sr_path!r}")
        elif self.sr_path:
            raise RuntimeError("Retro Optical: sr_path presente senza esposizione raw autorizzata.")

        if self.sg_expected:
            if not self.raw_expected:
                raise RuntimeError("Retro Optical: /dev/sgX non può essere esposto senza /dev/srX.")
            if not _SG_RE.fullmatch(self.sg_path):
                raise RuntimeError(f"Retro Optical: mapping sg non valido: {self.sg_path!r}")
        elif self.sg_path:
            raise RuntimeError("Retro Optical: sg_path presente senza esposizione sg autorizzata.")


def _prefixed_probe_script(script: str) -> str:
    return (
        f"PATH={OPTICAL_PROBE_PATH}\n"
        "export PATH\n"
        "LC_ALL=C\n"
        "export LC_ALL\n"
        + script
    )


def bubblejail_optical_probe_invocation(instance: str, script: str) -> list[str]:
    """Build the post-launch probe invocation for an already-running jail."""
    if not instance or instance.startswith("-"):
        raise RuntimeError(f"Nome istanza Bubblejail non valido: {instance!r}")
    return [
        "bubblejail",
        "run",
        "--wait",
        instance,
        "/bin/sh",
        "-c",
        _prefixed_probe_script(script),
    ]


def bubblejail_optical_preflight_invocation(
    runtime_args: list[str] | tuple[str, ...],
    instance: str,
    script: str,
) -> tuple[list[str], str]:
    """Replace only the application tail of an exact runtime command.

    The returned temporary jail therefore receives exactly the same Bubblewrap
    arguments as the real Bottles launch (GPU, network, RO mount bank, raw sr/sg
    devices, etc.) but executes ``--debug-shell`` instead of the application.
    Any unexpected command layout is rejected rather than guessed.
    """
    if not instance or instance.startswith("-"):
        raise RuntimeError(f"Nome istanza Bubblejail non valido: {instance!r}")
    args = list(runtime_args)
    if len(args) < 4 or Path(str(args[0])).name != "bubblejail" or args[1] != "run":
        raise RuntimeError("Retro Optical: comando runtime Bubblejail inatteso; preflight rifiutato.")
    if args.count("--") != 1 or args[-2:] != ["--", instance]:
        raise RuntimeError(
            "Retro Optical: impossibile provare che il comando runtime termini esattamente con '-- INSTANCE'."
        )
    if "--debug-shell" in args or "--wait" in args:
        raise RuntimeError("Retro Optical: comando runtime contiene opzioni di probe inattese.")
    probe_args = [*args[:-2], "--debug-shell", instance]
    return probe_args, _prefixed_probe_script(script)


def optical_probe_script() -> str:
    """Return a read-only shell probe for the effective optical boundary.

    The probe never writes to the mounted disc. Read-only status is proven
    from the mount namespace with findmnt, while device and D-Bus visibility
    are enumerated explicitly.
    """
    return f"""\
set +e

if [ -e {VHBA_CONTROL_PATH} ]; then
    printf 'OPT_VHBA_VISIBLE=1\\n'
else
    printf 'OPT_VHBA_HIDDEN=1\\n'
fi

for node in /dev/sr[0-9]*; do
    [ -e "$node" ] || continue
    printf 'OPT_SR_VISIBLE=%s\\n' "$node"
done
for node in /dev/sg[0-9]*; do
    [ -e "$node" ] || continue
    printf 'OPT_SG_VISIBLE=%s\\n' "$node"
done

if command -v gdbus >/dev/null 2>&1; then
    if gdbus call --session \
        --dest {CDEMU_DBUS_NAME} \
        --object-path {CDEMU_DBUS_PATH} \
        --method org.freedesktop.DBus.Peer.Ping >/dev/null 2>&1; then
        printf 'OPT_CDEMU_DBUS_REACHABLE=1\\n'
    else
        printf 'OPT_CDEMU_DBUS_BLOCKED=1\\n'
    fi
else
    printf 'OPT_GDBUS_MISSING=1\\n'
fi

if [ -e {JAIL_CD_TARGET} ] || [ -L {JAIL_CD_TARGET} ]; then
    printf 'OPT_MOUNT_PRESENT=1\\n'
    if [ -d {JAIL_CD_TARGET} ]; then
        printf 'OPT_MOUNT_DIRECTORY=1\\n'
    else
        printf 'OPT_MOUNT_NOT_DIRECTORY=1\\n'
    fi
    if command -v findmnt >/dev/null 2>&1; then
        options="$(findmnt -nr -T {JAIL_CD_TARGET} -o OPTIONS 2>/dev/null | head -n 1)"
        if [ -n "$options" ]; then
            printf 'OPT_MOUNT_OPTIONS=%s\\n' "$options"
        else
            printf 'OPT_MOUNT_FINDMNT_FAILED=1\\n'
        fi
    else
        printf 'OPT_FINDMNT_MISSING=1\\n'
    fi
else
    printf 'OPT_MOUNT_ABSENT=1\\n'
fi

exit 0
"""


def _probe_lines(text: str) -> tuple[str, ...]:
    """Return normalized lines for exact marker matching.

    Bubblejail 0.10.x echoes commands sent to an already-running instance. That
    diagnostic text contains the literal OPT_* strings from the shell source,
    so security decisions must match complete emitted lines, never substrings.
    """
    return tuple(line.strip() for line in text.splitlines())


def _has_marker(lines: tuple[str, ...], marker: str) -> bool:
    return marker in lines


def _values(lines: tuple[str, ...], prefix: str) -> tuple[str, ...]:
    needle = prefix + "="
    return tuple(
        line.split("=", 1)[1].strip()
        for line in lines
        if line.startswith(needle)
    )


def validate_optical_probe_output(exposure: OpticalExposure, text: str) -> dict[str, object]:
    """Fail closed unless the jail exposes exactly the authorised surface."""
    exposure.validate()
    lines = _probe_lines(text)

    if _has_marker(lines, "OPT_VHBA_VISIBLE=1") or not _has_marker(lines, "OPT_VHBA_HIDDEN=1"):
        raise RuntimeError("Retro Optical: /dev/vhba_ctl non risulta nascosto nella jail.")

    if _has_marker(lines, "OPT_GDBUS_MISSING=1"):
        raise RuntimeError("Retro Optical: gdbus assente; impossibile provare il blocco D-Bus CDEmu.")
    if _has_marker(lines, "OPT_CDEMU_DBUS_REACHABLE=1") or not _has_marker(
        lines, "OPT_CDEMU_DBUS_BLOCKED=1"
    ):
        raise RuntimeError("Retro Optical: il daemon CDEmu risulta raggiungibile dal gioco via D-Bus.")

    visible_sr = set(_values(lines, "OPT_SR_VISIBLE"))
    expected_sr = {exposure.sr_path} if exposure.raw_expected else set()
    if visible_sr != expected_sr:
        raise RuntimeError(
            "Retro Optical: nodi /dev/srX visibili diversi dalla policy: "
            f"attesi={sorted(expected_sr)}, ottenuti={sorted(visible_sr)}."
        )

    visible_sg = set(_values(lines, "OPT_SG_VISIBLE"))
    expected_sg = {exposure.sg_path} if exposure.sg_expected else set()
    if visible_sg != expected_sg:
        raise RuntimeError(
            "Retro Optical: nodi /dev/sgX visibili diversi dalla policy: "
            f"attesi={sorted(expected_sg)}, ottenuti={sorted(visible_sg)}."
        )

    mount_options = ""
    if exposure.mount_expected:
        if not _has_marker(lines, "OPT_MOUNT_PRESENT=1") or not _has_marker(
            lines, "OPT_MOUNT_DIRECTORY=1"
        ):
            raise RuntimeError(f"Retro Optical: {JAIL_CD_TARGET} non è una directory disponibile nella jail.")
        if _has_marker(lines, "OPT_FINDMNT_MISSING=1") or _has_marker(
            lines, "OPT_MOUNT_FINDMNT_FAILED=1"
        ):
            raise RuntimeError("Retro Optical: impossibile provare con findmnt che il mount sia read-only.")
        values = _values(lines, "OPT_MOUNT_OPTIONS")
        if len(values) != 1:
            raise RuntimeError("Retro Optical: opzioni mount assenti o ambigue.")
        mount_options = values[0]
        option_set = {item.strip() for item in mount_options.split(",") if item.strip()}
        if "ro" not in option_set or "rw" in option_set:
            raise RuntimeError(
                f"Retro Optical: {JAIL_CD_TARGET} non risulta read-only (opzioni={mount_options!r})."
            )
    else:
        if not _has_marker(lines, "OPT_MOUNT_ABSENT=1") or _has_marker(lines, "OPT_MOUNT_PRESENT=1"):
            raise RuntimeError(f"Retro Optical: {JAIL_CD_TARGET} è visibile senza autorizzazione.")

    return {
        "mount": exposure.mount_expected,
        "mount_options": mount_options,
        "sr": exposure.sr_path if exposure.raw_expected else "",
        "sg": exposure.sg_path if exposure.sg_expected else "",
        "vhba_hidden": True,
        "cdemu_dbus_blocked": True,
    }


def format_optical_probe_success(
    exposure: OpticalExposure,
    result: dict[str, object],
    *,
    phase: str = "post-avvio",
) -> str:
    exposure.validate()
    mount = f"{JAIL_CD_TARGET}=RO" if exposure.mount_expected else f"{JAIL_CD_TARGET}=hidden"
    sr = exposure.sr_path if exposure.raw_expected else "hidden"
    sg = exposure.sg_path if exposure.sg_expected else "hidden"
    return (
        f"[PASS] Retro Optical {phase}: "
        f"vhba=hidden · CDEmu D-Bus=blocked · sr={sr} · sg={sg} · {mount}"
    )
