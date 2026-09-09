#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import errno
import os
import re
import stat
from pathlib import Path

CLONE_NEWNS = 0x00020000
CLONE_NEWUSER = 0x10000000
MS_BIND = 4096
MNT_DETACH = 2
_NODE_RE = re.compile(r"^(?:js|event)[0-9]+$")

_libc = ctypes.CDLL(None, use_errno=True)
_libc.mount.argtypes = [
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_ulong,
    ctypes.c_void_p,
]
_libc.mount.restype = ctypes.c_int
_libc.umount2.argtypes = [ctypes.c_char_p, ctypes.c_int]
_libc.umount2.restype = ctypes.c_int


def _runtime_helper_socket(instance: str) -> Path:
    if not instance or instance.startswith("/") or instance.startswith("-") or "/" in instance:
        raise RuntimeError(f"Nome istanza Bubblejail non valido: {instance!r}")
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    return runtime / "bubblejail" / instance / "helper" / "helper.socket"


def _socket_inode(path: Path) -> str:
    wanted = str(path)
    try:
        lines = Path("/proc/net/unix").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise RuntimeError(f"Impossibile leggere /proc/net/unix: {exc}") from exc
    matches: list[str] = []
    for line in lines[1:]:
        fields = line.split()
        if len(fields) >= 8 and fields[-1] == wanted:
            matches.append(fields[6])
    if len(matches) != 1:
        raise RuntimeError(
            f"Socket helper Bubblejail non identificabile in modo univoco ({len(matches)} match): {path}"
        )
    return matches[0]


def _socket_owner_pids(sock_inode: str) -> tuple[int, ...]:
    needle = f"socket:[{sock_inode}]"
    owners: list[int] = []
    uid = os.getuid()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdecimal():
            continue
        try:
            if proc.stat().st_uid != uid:
                continue
            for fd in (proc / "fd").iterdir():
                try:
                    if os.readlink(fd) == needle:
                        owners.append(int(proc.name))
                        break
                except OSError:
                    continue
        except OSError:
            continue
    return tuple(sorted(set(owners)))


def _namespace_link(pid: int, name: str) -> str:
    try:
        return os.readlink(f"/proc/{pid}/ns/{name}")
    except OSError as exc:
        raise RuntimeError(f"Namespace {name} non leggibile per PID {pid}: {exc}") from exc


def _cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\0", b" ").decode("utf-8", errors="replace")


def _socket_owner_pid(sock_inode: str) -> int:
    owners = _socket_owner_pids(sock_inode)
    if not owners:
        raise RuntimeError("Nessun processo possiede il socket helper Bubblejail.")

    host_mnt = _namespace_link(os.getpid(), "mnt")
    sandbox_owners = [
        pid for pid in owners
        if _namespace_link(pid, "mnt") != host_mnt
    ]
    if len(sandbox_owners) == 1:
        return sandbox_owners[0]

    helper_named = [
        pid for pid in sandbox_owners
        if "bubblejail-helper" in _cmdline(pid) or "bubblejail_helper" in _cmdline(pid)
    ]
    if len(helper_named) == 1:
        return helper_named[0]

    host_user = _namespace_link(os.getpid(), "user")
    child_user = [
        pid for pid in sandbox_owners
        if _namespace_link(pid, "user") != host_user
    ]
    if len(child_user) == 1:
        return child_user[0]

    raise RuntimeError(
        "Processo helper nel namespace sandbox non identificabile in modo univoco: "
        f"owners={owners}, sandbox={sandbox_owners}, helper={helper_named}."
    )


def find_instance_namespace_pid(instance: str) -> int:
    socket_path = _runtime_helper_socket(instance)
    try:
        st = socket_path.stat()
    except OSError as exc:
        raise RuntimeError(f"Istanza Bubblejail non attiva: {socket_path}: {exc}") from exc
    if not stat.S_ISSOCK(st.st_mode) or st.st_uid != os.getuid():
        raise RuntimeError("Il socket runtime Bubblejail non è un socket dell'utente corrente.")
    pid = _socket_owner_pid(_socket_inode(socket_path))
    for ns_name in ("user", "mnt"):
        ns_path = Path(f"/proc/{pid}/ns/{ns_name}")
        if not ns_path.exists():
            raise RuntimeError(f"Namespace {ns_name} non disponibile per PID {pid}.")
    return pid


def _validate_node_name(name: str) -> str:
    if _NODE_RE.fullmatch(name) is None:
        raise RuntimeError(f"Nome nodo input rifiutato: {name!r}")
    return name


def _validate_host_node(raw: str) -> tuple[str, Path]:
    path = Path(raw)
    if path.parent != Path("/dev/input"):
        raise RuntimeError(f"Nodo gamepad fuori da /dev/input: {path}")
    name = _validate_node_name(path.name)
    try:
        st = path.stat()
    except OSError as exc:
        raise RuntimeError(f"Nodo gamepad host non disponibile: {path}: {exc}") from exc
    if not stat.S_ISCHR(st.st_mode):
        raise RuntimeError(f"Nodo gamepad host non è un character device: {path}")
    if not os.access(path, os.R_OK):
        raise RuntimeError(f"Nodo gamepad host non leggibile dall'utente: {path}")
    return name, path


def _umount_once(path: Path) -> bool:
    if _libc.umount2(os.fsencode(path), MNT_DETACH) == 0:
        return True
    err = ctypes.get_errno()
    if err in (errno.EINVAL, errno.ENOENT):
        return False
    raise OSError(err, os.strerror(err), str(path))


def _remove_target(name: str) -> None:
    name = _validate_node_name(name)
    target = Path("/dev/input") / name
    for _ in range(8):
        if not _umount_once(target):
            break
    else:
        raise RuntimeError(f"Troppi mount sovrapposti su {target}; rimozione rifiutata.")
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    except IsADirectoryError as exc:
        raise RuntimeError(f"Target input inatteso (directory): {target}") from exc
    print(f"REMOVED={name}")


def _bind_fd(name: str, source_fd: int) -> None:
    name = _validate_node_name(name)
    input_dir = Path("/dev/input")
    input_dir.mkdir(mode=0o755, parents=True, exist_ok=True)
    target = input_dir / name

    # A safe initial activation may deliberately overlay Bubblejail's static
    # bind. Do not unlink a mounted target: mount(2) can stack the new exact
    # source on top, proving dynamic bind capability without first removing the
    # known-working static controller path.
    if not target.exists():
        fd = os.open(target, os.O_CREAT | os.O_WRONLY | os.O_CLOEXEC, 0o600)
        os.close(fd)

    source = f"/proc/self/fd/{source_fd}"
    if _libc.mount(os.fsencode(source), os.fsencode(target), None, MS_BIND, None) != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), f"{source} -> {target}")
    print(f"BOUND={name}")


def mutate_instance(instance: str, bind_paths: list[str], remove_names: list[str]) -> None:
    if not hasattr(os, "setns"):
        raise RuntimeError("Python non espone os.setns(); hotplug namespace non disponibile.")

    namespace_pid = find_instance_namespace_pid(instance)
    validated = [_validate_host_node(raw) for raw in bind_paths]
    if len({name for name, _ in validated}) != len(validated):
        raise RuntimeError("Nodi gamepad duplicati nella richiesta hotplug.")
    remove_names = [_validate_node_name(name) for name in remove_names]

    source_fds: dict[str, int] = {}
    user_fd = mnt_fd = -1
    try:
        # All host device FDs are opened before entering the sandbox namespace.
        # After setns(), /proc/self/fd/N remains an exact reference to those
        # already-authorised character devices; no host directory is exposed.
        for name, path in validated:
            source_fds[name] = os.open(path, os.O_PATH | os.O_CLOEXEC)
        user_fd = os.open(f"/proc/{namespace_pid}/ns/user", os.O_RDONLY | os.O_CLOEXEC)
        mnt_fd = os.open(f"/proc/{namespace_pid}/ns/mnt", os.O_RDONLY | os.O_CLOEXEC)

        current_user_ns = os.readlink("/proc/self/ns/user")
        target_user_ns = os.readlink(f"/proc/{namespace_pid}/ns/user")
        if current_user_ns != target_user_ns:
            os.setns(user_fd, CLONE_NEWUSER)
        os.setns(mnt_fd, CLONE_NEWNS)

        Path("/dev/input").mkdir(mode=0o755, parents=True, exist_ok=True)
        for name in sorted(set(remove_names)):
            _remove_target(name)
        for name in sorted(source_fds):
            _bind_fd(name, source_fds[name])
        print(f"NAMESPACE_PID={namespace_pid}")
    finally:
        for fd in source_fds.values():
            try:
                os.close(fd)
            except OSError:
                pass
        for fd in (user_fd, mnt_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="RetroCD exact-node gamepad mount-namespace helper"
    )
    parser.add_argument("--instance", required=True)
    parser.add_argument("--bind", action="append", default=[])
    parser.add_argument("--remove", action="append", default=[])
    args = parser.parse_args()
    mutate_instance(args.instance, args.bind, args.remove)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
