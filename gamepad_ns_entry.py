#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import fcntl
import os
import stat
from pathlib import Path

import gamepad_ns_helper as core

# linux/nsfs.h: _IO(0xb7, 0x1)
NS_GET_USERNS = 0xB701

_libc = ctypes.CDLL(None, use_errno=True)
_libc.unshare.argtypes = [ctypes.c_int]
_libc.unshare.restype = ctypes.c_int


def _ns_key(fd: int) -> tuple[int, int]:
    st = os.fstat(fd)
    return int(st.st_dev), int(st.st_ino)


def _owning_userns(namespace_fd: int) -> int:
    try:
        owner_fd = fcntl.ioctl(namespace_fd, NS_GET_USERNS)
    except OSError as exc:
        raise RuntimeError(
            f"Impossibile determinare la user namespace owner: {exc}"
        ) from exc
    if not isinstance(owner_fd, int) or owner_fd < 0:
        raise RuntimeError("NS_GET_USERNS non ha restituito un file descriptor valido.")
    return owner_fd


def _unshare_mount_namespace() -> None:
    unshare = getattr(os, "unshare", None)
    if unshare is not None:
        unshare(core.CLONE_NEWNS)
        return
    if _libc.unshare(core.CLONE_NEWNS) != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), "unshare(CLONE_NEWNS)")


def _source_key(st: os.stat_result) -> tuple[int, int, int, int]:
    return (
        int(st.st_dev),
        int(st.st_ino),
        int(stat.S_IFMT(st.st_mode)),
        int(st.st_rdev),
    )


def _reopen_pinned(path: Path, pinned_fd: int) -> int:
    try:
        fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
    except OSError as exc:
        raise RuntimeError(f"Risorsa hotplug non più disponibile: {path}: {exc}") from exc
    try:
        if _source_key(os.fstat(fd)) != _source_key(os.fstat(pinned_fd)):
            raise RuntimeError(
                f"Risorsa host cambiata durante la riconciliazione hotplug: {path}"
            )
        return fd
    except BaseException:
        os.close(fd)
        raise


def mutate_instance(
    instance: str,
    bind_paths: list[str],
    remove_names: list[str],
    *,
    notify: bool = False,
) -> None:
    if not hasattr(os, "setns"):
        raise RuntimeError("Python non espone os.setns(); hotplug namespace non disponibile.")

    namespace_pid = core.find_instance_namespace_pid(instance)
    validated = [core._validate_host_node(raw) for raw in bind_paths]
    if len({name for name, _, _, _ in validated}) != len(validated):
        raise RuntimeError("Nodi gamepad duplicati nella richiesta hotplug.")
    remove_names = [core._validate_node_name(name) for name in remove_names]

    device_pins: dict[str, int] = {}
    sysfs_pins: dict[Path, int] = {}
    device_mounts: dict[str, int] = {}
    sysfs_mounts: dict[Path, int] = {}
    sysfs_links: dict[str, tuple[str, Path]] = {}

    mnt_fd = net_fd = owner_user_fd = current_user_fd = current_net_fd = -1
    try:
        # Pin each exact host object before any namespace transition. These FDs
        # are identity guards only; no host directory is shared with Bubblejail.
        for name, path, link_target, sysfs_root in validated:
            device_pins[name] = os.open(path, os.O_PATH | os.O_CLOEXEC)
            sysfs_links[name] = (link_target, sysfs_root)
            if sysfs_root not in sysfs_pins:
                sysfs_pins[sysfs_root] = os.open(
                    sysfs_root, os.O_PATH | os.O_CLOEXEC
                )

        mnt_fd = os.open(
            f"/proc/{namespace_pid}/ns/mnt", os.O_RDONLY | os.O_CLOEXEC
        )
        net_fd = os.open(
            f"/proc/{namespace_pid}/ns/net", os.O_RDONLY | os.O_CLOEXEC
        )
        current_user_fd = os.open(
            "/proc/self/ns/user", os.O_RDONLY | os.O_CLOEXEC
        )
        current_net_fd = os.open(
            "/proc/self/ns/net", os.O_RDONLY | os.O_CLOEXEC
        )

        # A non-user namespace is governed by its owning user namespace. The
        # process currently living in the target mount namespace may itself be
        # in a nested/different user namespace, so never infer ownership from
        # /proc/<pid>/ns/user.
        owner_user_fd = _owning_userns(mnt_fd)
        if _ns_key(owner_user_fd) == _ns_key(current_user_fd):
            raise RuntimeError(
                "La mount namespace Bubblejail è posseduta dalla user namespace "
                "corrente; hotplug exact-node non disponibile senza privilegi host."
            )

        # Joining a descendant user namespace grants the capabilities scoped to
        # that namespace. Create a private staging mount namespace owned by the
        # same user namespace before cloning any host source mount.
        os.setns(owner_user_fd, core.CLONE_NEWUSER)
        _unshare_mount_namespace()

        # Reopen every exact source in the staging namespace and verify it is
        # still the same object pinned above. This closes the unplug/TOCTOU gap.
        for name, _, _, _ in validated:
            source_path = Path("/dev/input") / name
            source_fd = _reopen_pinned(source_path, device_pins[name])
            try:
                device_mounts[name] = core._open_tree_clone(source_fd)
            finally:
                os.close(source_fd)

        for root in sorted(sysfs_pins, key=str):
            source_fd = _reopen_pinned(root, sysfs_pins[root])
            try:
                sysfs_mounts[root] = core._open_tree_clone(source_fd)
            finally:
                os.close(source_fd)

        # All potentially failing source preparation is complete. Enter the
        # actual Bubblejail mount namespace only now. If network namespace entry
        # is required for udev notification, do it before mutating any mount.
        os.setns(mnt_fd, core.CLONE_NEWNS)
        if _ns_key(net_fd) != _ns_key(current_net_fd):
            os.setns(net_fd, core.CLONE_NEWNET)

        core._mutate_inside_namespace(
            device_mounts,
            sysfs_mounts,
            sysfs_links,
            remove_names,
            namespace_pid,
            notify,
        )
        print("ENTRY=mount-owner-userns+staging-mnt", flush=True)
    finally:
        for mapping in (device_mounts, sysfs_mounts, device_pins, sysfs_pins):
            for fd in mapping.values():
                try:
                    os.close(fd)
                except OSError:
                    pass
        for fd in (mnt_fd, net_fd, owner_user_fd, current_user_fd, current_net_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="RetroCD exact-node gamepad namespace entry helper"
    )
    parser.add_argument("--instance", required=True)
    parser.add_argument("--bind", action="append", default=[])
    parser.add_argument("--remove", action="append", default=[])
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Invia eventi udev add/remove nella network namespace Bubblejail.",
    )
    args = parser.parse_args()
    mutate_instance(
        args.instance,
        args.bind,
        args.remove,
        notify=args.notify,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
