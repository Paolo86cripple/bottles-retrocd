#!/usr/bin/env python3
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

JAIL_BRIDGE_ROOT = "/run/bottles-retro-cd-bridge"
JAIL_CD_TARGET = "/mnt/cdemu"


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


@dataclass(slots=True)
class DiscBridge:
    """Static RO mount bank plus a dynamic selector in the jail's private HOME.

    All disc filesystems are bound read-only when Bubblewrap starts. The only
    live operation is replacing a symlink stored in the private HOME, which is
    already shared with the jail. This avoids /proc/<pid>/fd and dynamic mount
    propagation while keeping /run/media hidden.
    """

    instance: str
    private_home: Path
    neutral_dir: Path
    media_root: Path
    targets: dict[str, str] = field(default_factory=dict)
    current_host: Path | None = None
    current_target: str = ""
    prepared: bool = False

    @property
    def state_dir(self) -> Path:
        return self.private_home / ".cache" / "bottles-retro-cd" / f"bridge-{self.instance}"

    @property
    def jail_state_dir(self) -> Path:
        rel = self.state_dir.resolve(strict=False).relative_to(self.private_home.resolve(strict=False))
        return Path.home() / rel

    def _validate_target(self, target: Path) -> Path:
        resolved = target.resolve(strict=True)
        if not resolved.is_dir():
            raise RuntimeError(f"Target bridge non è una directory: {resolved}")
        neutral = self.neutral_dir.resolve(strict=True)
        media_root = self.media_root.resolve(strict=False)
        if resolved != neutral and not _is_relative_to(resolved, media_root):
            # Self-tests and future non-UDisks providers may use directories
            # below the jail private HOME. Those are already sandbox-private.
            home = self.private_home.resolve(strict=False)
            if not _is_relative_to(resolved, home):
                raise RuntimeError(f"Target bridge fuori dalle radici consentite: {resolved}")
        return resolved

    def start(self, initial_target: Path, targets: list[Path] | tuple[Path, ...] | None = None) -> None:
        self.neutral_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.state_dir, 0o700)
        # Keep /mnt/cdemu valid but empty while changing media instead of
        # temporarily pointing it at a dangling symlink.
        empty_host = self.state_dir / "empty"
        empty_host.mkdir(exist_ok=True)
        os.chmod(empty_host, 0o700)

        all_targets = list(targets or [initial_target])
        initial = self._validate_target(initial_target)
        neutral = self._validate_target(self.neutral_dir)
        if all(self._validate_target(p) != neutral for p in all_targets):
            all_targets.append(neutral)

        self.targets.clear()
        seen: set[str] = set()
        ordinal = 0
        for target in all_targets:
            resolved = self._validate_target(target)
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            if resolved == neutral:
                jail_target = str(self.jail_state_dir / "empty")
            else:
                jail_target = f"{JAIL_BRIDGE_ROOT}/disc-{ordinal}"
                ordinal += 1
            self.targets[key] = jail_target

        if str(initial) not in self.targets:
            raise RuntimeError("Target iniziale non registrato nel bridge")
        self.current_host = self.state_dir / "current"
        self.prepared = True
        self.set_target(initial)

    def _replace_selector(self, jail_target: str) -> None:
        if self.current_host is None:
            raise RuntimeError("Bridge multidisco non preparato")
        tmp = self.current_host.with_name(f".current-{os.getpid()}.tmp")
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        os.symlink(jail_target, tmp)
        os.replace(tmp, self.current_host)

    def set_target(self, target: Path) -> str:
        if not self.prepared:
            raise RuntimeError("Bridge multidisco non preparato")
        resolved = self._validate_target(target)
        key = str(resolved)
        jail_target = self.targets.get(key)
        if jail_target is None:
            raise RuntimeError(
                "Target non pre-registrato nel bridge; i mount live devono essere noti prima di avviare Bubblejail."
            )
        self._replace_selector(jail_target)
        self.current_target = key
        return key

    def neutralize(self) -> str:
        return self.set_target(self.neutral_dir)

    def status(self) -> dict:
        return {
            "ok": self.prepared,
            "target": self.current_target,
            "targets": len(self.targets),
            "selector": str(self.current_host or ""),
        }

    def alive(self) -> bool:
        return bool(self.prepared and self.current_host and self.current_host.is_symlink())

    def stop(self) -> None:
        if self.current_host is not None:
            try:
                self.current_host.unlink()
            except FileNotFoundError:
                pass
        self.targets.clear()
        self.current_target = ""
        self.prepared = False

    def bubblewrap_args(self) -> list[str]:
        if not self.prepared or self.current_host is None:
            raise RuntimeError("Bridge multidisco non preparato")
        args = ["--debug-bwrap-args", "dir", JAIL_BRIDGE_ROOT]
        neutral = self.neutral_dir.resolve(strict=True)
        for host_target, jail_target in self.targets.items():
            host = Path(host_target)
            if host == neutral:
                continue
            args += ["--debug-bwrap-args", "ro-bind", str(host), jail_target]
        args += [
            "--debug-bwrap-args", "dir", "/mnt",
            "--debug-bwrap-args", "symlink", str(self.jail_state_dir / "current"), JAIL_CD_TARGET,
        ]
        return args
