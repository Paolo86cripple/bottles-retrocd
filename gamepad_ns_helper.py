#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import errno
import json
import os
import re
import socket
import stat
import struct
import time
from pathlib import Path

CLONE_NEWNS = 0x00020000
CLONE_NEWUSER = 0x10000000
CLONE_NEWNET = 0x40000000

AT_FDCWD = -100
AT_EMPTY_PATH = 0x1000
OPEN_TREE_CLONE = 0x00000001
OPEN_TREE_CLOEXEC = os.O_CLOEXEC
MOVE_MOUNT_F_EMPTY_PATH = 0x00000004

MNT_DETACH = 2
SYS_OPEN_TREE = 428
SYS_MOVE_MOUNT = 429

NETLINK_KOBJECT_UEVENT = getattr(socket, "NETLINK_KOBJECT_UEVENT", 15)
UDEV_MONITOR_GROUP = 2
UDEV_MONITOR_MAGIC = 0xFEEDCAFE

_NODE_RE = re.compile(r"^(?:js|event)[0-9]+$")
_HOST_UID = os.getuid()

_libc = ctypes.CDLL(None, use_errno=True)
_libc.umount2.argtypes = [ctypes.c_char_p, ctypes.c_int]
_libc.umount2.restype = ctypes.c_int

_open_tree_fn = getattr(_libc, "open_tree", None)
if _open_tree_fn is not None:
    _open_tree_fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    _open_tree_fn.restype = ctypes.c_int

_move_mount_fn = getattr(_libc, "move_mount", None)
if _move_mount_fn is not None:
    _move_mount_fn.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    _move_mount_fn.restype = ctypes.c_int


def _runtime_helper_socket(instance: str) -> Path:
    if (
        not instance
        or instance.startswith("/")
        or instance.startswith("-")
        or "/" in instance
    ):
        raise RuntimeError(f"Nome istanza Bubblejail non valido: {instance!r}")
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{_HOST_UID}"))
    return runtime / "bubblejail" / instance / "helper" / "helper.socket"


def _socket_inode(path: Path) -> str:
    wanted = str(path)
    try:
        lines = Path("/proc/net/unix").read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
    except OSError as exc:
        raise RuntimeError(f"Impossibile leggere /proc/net/unix: {exc}") from exc

    matches: list[str] = []
    for line in lines[1:]:
        fields = line.split()
        if len(fields) >= 8 and fields[-1] == wanted:
            matches.append(fields[6])
    if len(matches) != 1:
        raise RuntimeError(
            "Socket helper Bubblejail non identificabile in modo univoco "
            f"({len(matches)} match): {path}"
        )
    return matches[0]


def _socket_owner_pids(sock_inode: str) -> tuple[int, ...]:
    needle = f"socket:[{sock_inode}]"
    owners: list[int] = []
    uid = _HOST_UID
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
        raise RuntimeError(
            f"Namespace {name} non leggibile per PID {pid}: {exc}"
        ) from exc


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
    sandbox_owners: list[int] = []
    for pid in owners:
        try:
            if _namespace_link(pid, "mnt") != host_mnt:
                sandbox_owners.append(pid)
        except RuntimeError:
            continue

    if len(sandbox_owners) == 1:
        return sandbox_owners[0]

    helper_named = [
        pid
        for pid in sandbox_owners
        if "bubblejail-helper" in _cmdline(pid)
        or "bubblejail_helper" in _cmdline(pid)
    ]
    if len(helper_named) == 1:
        return helper_named[0]

    host_user = _namespace_link(os.getpid(), "user")
    child_user: list[int] = []
    for pid in sandbox_owners:
        try:
            if _namespace_link(pid, "user") != host_user:
                child_user.append(pid)
        except RuntimeError:
            continue
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

    if not stat.S_ISSOCK(st.st_mode) or st.st_uid != _HOST_UID:
        raise RuntimeError(
            "Il socket runtime Bubblejail non è un socket dell'utente corrente."
        )

    pid = _socket_owner_pid(_socket_inode(socket_path))
    # PID namespace membership is deliberately not required. The helper uses
    # fd-based detached mounts, so it never resolves host sources through the
    # sandbox's /proc and does not need CLONE_NEWPID.
    for ns_name in ("user", "mnt", "net"):
        ns_path = Path(f"/proc/{pid}/ns/{ns_name}")
        if not ns_path.exists():
            raise RuntimeError(f"Namespace {ns_name} non disponibile per PID {pid}.")
    return pid


def _validate_node_name(name: str) -> str:
    if _NODE_RE.fullmatch(name) is None:
        raise RuntimeError(f"Nome nodo input rifiutato: {name!r}")
    return name


def _validate_sysfs_root(path: Path) -> Path:
    path = Path(path)
    try:
        path.relative_to("/sys/devices")
    except ValueError as exc:
        raise RuntimeError(f"Radice sysfs gamepad rifiutata: {path}") from exc
    if path == Path("/sys/devices"):
        raise RuntimeError("Radice sysfs gamepad troppo ampia: /sys/devices")
    return path


def _host_sysfs_binding(name: str) -> tuple[str, Path]:
    name = _validate_node_name(name)
    class_entry = Path("/sys/class/input") / name
    try:
        link_target = os.readlink(class_entry)
        resolved = class_entry.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError(f"Sysfs host non disponibile per {name}: {exc}") from exc

    _validate_sysfs_root(resolved)
    try:
        root = resolved.parents[2]
    except IndexError as exc:
        raise RuntimeError(
            f"Gerarchia sysfs gamepad inattesa per {name}: {resolved}"
        ) from exc
    root = _validate_sysfs_root(root)
    if os.path.isabs(link_target):
        raise RuntimeError(
            f"Symlink sysfs assoluto inatteso per {name}: {link_target}"
        )
    return link_target, root


def _validate_host_node(raw: str) -> tuple[str, Path, str, Path]:
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

    link_target, sysfs_root = _host_sysfs_binding(name)
    return name, path, link_target, sysfs_root


def _umount_once(path: Path) -> bool:
    if _libc.umount2(os.fsencode(path), MNT_DETACH) == 0:
        return True
    err = ctypes.get_errno()
    if err in (errno.EINVAL, errno.ENOENT):
        return False
    raise OSError(err, os.strerror(err), str(path))


def _umount_all(path: Path, *, limit: int = 12) -> None:
    for _ in range(limit):
        if not _umount_once(path):
            return
    raise RuntimeError(f"Troppi mount sovrapposti su {path}; rimozione rifiutata.")


def _open_tree_clone(source_fd: int) -> int:
    flags = AT_EMPTY_PATH | OPEN_TREE_CLONE | OPEN_TREE_CLOEXEC
    if _open_tree_fn is not None:
        result = _open_tree_fn(source_fd, b"", flags)
    else:
        result = _libc.syscall(
            SYS_OPEN_TREE,
            source_fd,
            ctypes.c_char_p(b""),
            flags,
        )
    if result < 0:
        err = ctypes.get_errno()
        raise OSError(
            err,
            os.strerror(err),
            f"open_tree(fd={source_fd}, AT_EMPTY_PATH|OPEN_TREE_CLONE)",
        )
    return int(result)


def _move_mount_fd(mount_fd: int, target: Path) -> None:
    target_bytes = os.fsencode(target)
    if _move_mount_fn is not None:
        result = _move_mount_fn(
            mount_fd,
            b"",
            AT_FDCWD,
            target_bytes,
            MOVE_MOUNT_F_EMPTY_PATH,
        )
    else:
        result = _libc.syscall(
            SYS_MOVE_MOUNT,
            mount_fd,
            ctypes.c_char_p(b""),
            AT_FDCWD,
            ctypes.c_char_p(target_bytes),
            MOVE_MOUNT_F_EMPTY_PATH,
        )
    if result != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), f"move_mount(fd={mount_fd}) -> {target}")


def _prepare_file_target(target: Path) -> None:
    target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    if target.exists():
        return
    fd = os.open(target, os.O_CREAT | os.O_WRONLY | os.O_CLOEXEC, 0o600)
    os.close(fd)


def _attach_device_mount(name: str, mount_fd: int) -> None:
    name = _validate_node_name(name)
    target = Path("/dev/input") / name
    _prepare_file_target(target)
    _move_mount_fd(mount_fd, target)
    print(f"BOUND={name}", flush=True)


def _attach_sysfs_mount(target: Path, mount_fd: int) -> None:
    target = _validate_sysfs_root(target)
    # Bubblejail builds /sys as a synthetic private tree and binds only the
    # required subtrees. Creating this exact target inside that private tree
    # does not expose additional host sysfs content.
    target.mkdir(mode=0o755, parents=True, exist_ok=True)
    _move_mount_fd(mount_fd, target)
    print(f"SYSFS_BOUND={target}", flush=True)


def _install_sysfs_link(name: str, link_target: str) -> None:
    name = _validate_node_name(name)
    if not link_target or os.path.isabs(link_target):
        raise RuntimeError(
            f"Target symlink sysfs rifiutato per {name}: {link_target!r}"
        )

    class_dir = Path("/sys/class/input")
    target = class_dir / name
    try:
        current = os.readlink(target)
    except FileNotFoundError:
        current = None
    except OSError as exc:
        raise RuntimeError(
            f"Target sysfs {target} non è un symlink gestibile: {exc}"
        ) from exc

    if current == link_target:
        return

    class_dir.mkdir(mode=0o755, parents=True, exist_ok=True)
    if current is not None:
        target.unlink()
    target.symlink_to(link_target)
    print(f"SYSFS_LINK={name}", flush=True)


def _remove_target(name: str) -> None:
    name = _validate_node_name(name)
    target = Path("/dev/input") / name
    _umount_all(target)
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    except IsADirectoryError as exc:
        raise RuntimeError(f"Target input inatteso (directory): {target}") from exc
    print(f"REMOVED={name}", flush=True)


def _remove_sysfs_link(name: str) -> None:
    name = _validate_node_name(name)
    target = Path("/sys/class/input") / name
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    except IsADirectoryError as exc:
        raise RuntimeError(f"Target sysfs inatteso (directory): {target}") from exc
    print(f"SYSFS_UNLINK={name}", flush=True)


def _state_dir() -> Path:
    return Path("/run/user") / str(_HOST_UID) / "bottles-retro-cd-gamepad-hotplug"


def _state_file(name: str) -> Path:
    return _state_dir() / f"{_validate_node_name(name)}.json"


def _event_properties_from_live_node(name: str) -> dict[str, str]:
    name = _validate_node_name(name)
    dev = Path("/dev/input") / name
    class_entry = Path("/sys/class/input") / name
    try:
        st = dev.stat()
        resolved = class_entry.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError(f"Metadati udev non leggibili per {name}: {exc}") from exc

    if not stat.S_ISCHR(st.st_mode):
        raise RuntimeError(f"Metadati udev rifiutati: {dev} non è un character device.")
    _validate_sysfs_root(resolved)

    try:
        devpath = "/" + str(resolved.relative_to("/sys"))
    except ValueError as exc:
        raise RuntimeError(f"Syspath udev fuori da /sys per {name}: {resolved}") from exc

    props = {
        "DEVPATH": devpath,
        "DEVNAME": str(dev),
        "SUBSYSTEM": "input",
        "MAJOR": str(os.major(st.st_rdev)),
        "MINOR": str(os.minor(st.st_rdev)),
        "ID_INPUT": "1",
        "ID_INPUT_JOYSTICK": "1",
    }

    uevent = resolved / "uevent"
    try:
        for line in uevent.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            key, sep, value = line.partition("=")
            if sep and key and "\0" not in key and "\0" not in value:
                props.setdefault(key, value)
    except OSError:
        pass

    props["DEVPATH"] = devpath
    props["DEVNAME"] = str(dev)
    props["SUBSYSTEM"] = "input"
    props["MAJOR"] = str(os.major(st.st_rdev))
    props["MINOR"] = str(os.minor(st.st_rdev))
    return props


def _save_state(name: str, sysfs_root: Path, link_target: str) -> dict[str, str]:
    name = _validate_node_name(name)
    sysfs_root = _validate_sysfs_root(sysfs_root)
    props = _event_properties_from_live_node(name)

    state_dir = _state_dir()
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(state_dir, 0o700)

    payload = {
        "name": name,
        "sysfs_root": str(sysfs_root),
        "link_target": link_target,
        "properties": props,
    }
    path = _state_file(name)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return props


def _load_state(name: str) -> tuple[Path, str, dict[str, str]]:
    name = _validate_node_name(name)
    path = _state_file(name)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Stato hotplug precedente mancante/non valido per {name}: {exc}"
        ) from exc

    if not isinstance(raw, dict) or raw.get("name") != name:
        raise RuntimeError(f"Stato hotplug precedente incoerente per {name}.")

    root = _validate_sysfs_root(Path(str(raw.get("sysfs_root", ""))))
    link_target = raw.get("link_target")
    props = raw.get("properties")
    if (
        not isinstance(link_target, str)
        or not link_target
        or os.path.isabs(link_target)
    ):
        raise RuntimeError(f"Stato hotplug: symlink sysfs non valido per {name}.")
    if not isinstance(props, dict):
        raise RuntimeError(f"Stato hotplug: proprietà udev non valide per {name}.")

    clean_props: dict[str, str] = {}
    for key, value in props.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise RuntimeError(
                f"Stato hotplug: proprietà udev non stringa per {name}."
            )
        if not key or "\0" in key or "\0" in value:
            raise RuntimeError(f"Stato hotplug: proprietà udev rifiutata per {name}.")
        clean_props[key] = value

    for required in ("DEVPATH", "DEVNAME", "SUBSYSTEM", "MAJOR", "MINOR"):
        if required not in clean_props:
            raise RuntimeError(
                f"Stato hotplug: proprietà udev {required} mancante per {name}."
            )
    return root, link_target, clean_props


def _drop_state(name: str) -> None:
    try:
        _state_file(name).unlink()
    except FileNotFoundError:
        pass


def _murmur2(data: bytes, seed: int = 0) -> int:
    m = 0x5BD1E995
    h = (seed ^ len(data)) & 0xFFFFFFFF
    index = 0
    remaining = len(data)

    while remaining >= 4:
        k = int.from_bytes(data[index : index + 4], "little")
        k = (k * m) & 0xFFFFFFFF
        k ^= k >> 24
        k = (k * m) & 0xFFFFFFFF
        h = (h * m) & 0xFFFFFFFF
        h ^= k
        index += 4
        remaining -= 4

    if remaining == 3:
        h ^= data[index + 2] << 16
    if remaining >= 2:
        h ^= data[index + 1] << 8
    if remaining >= 1:
        h ^= data[index]
        h = (h * m) & 0xFFFFFFFF

    h ^= h >> 13
    h = (h * m) & 0xFFFFFFFF
    h ^= h >> 15
    return h & 0xFFFFFFFF


def _udev_packet(properties: dict[str, str], action: str) -> bytes:
    if action not in {"add", "remove"}:
        raise RuntimeError(f"Azione udev rifiutata: {action}")

    props = dict(properties)
    props["ACTION"] = action
    props["SEQNUM"] = str(time.monotonic_ns())
    ordered = ["ACTION", "SEQNUM"] + sorted(
        key for key in props if key not in {"ACTION", "SEQNUM"}
    )

    chunks: list[bytes] = []
    for key in ordered:
        value = props[key]
        if not key or "\0" in key or "\0" in value:
            raise RuntimeError("Proprietà udev contenente NUL rifiutata.")
        chunks.append(
            f"{key}={value}".encode("utf-8", errors="strict") + b"\0"
        )
    payload = b"".join(chunks)

    header_format = "=8s8I"
    header_size = struct.calcsize(header_format)
    subsystem_hash = socket.htonl(_murmur2(b"input"))
    header = struct.pack(
        header_format,
        b"libudev\0",
        socket.htonl(UDEV_MONITOR_MAGIC),
        header_size,
        header_size,
        len(payload),
        subsystem_hash,
        0,
        0xFFFFFFFF,
        0xFFFFFFFF,
    )
    return header + payload


def _send_udev_event(properties: dict[str, str], action: str) -> None:
    packet = _udev_packet(properties, action)
    with socket.socket(
        socket.AF_NETLINK,
        socket.SOCK_DGRAM,
        NETLINK_KOBJECT_UEVENT,
    ) as sock:
        sock.bind((0, 0))
        sent = sock.sendto(packet, (0, UDEV_MONITOR_GROUP))

    if sent != len(packet):
        raise RuntimeError(
            f"Notifica udev {action} incompleta: {sent}/{len(packet)} byte."
        )

    name = Path(properties.get("DEVNAME", "?")).name
    print(f"UDEV_{action.upper()}={name}", flush=True)


def _mutate_inside_namespace(
    device_mounts: dict[str, int],
    sysfs_mounts: dict[Path, int],
    sysfs_links: dict[str, tuple[str, Path]],
    remove_names: list[str],
    namespace_pid: int,
    notify: bool,
) -> None:
    Path("/dev/input").mkdir(mode=0o755, parents=True, exist_ok=True)

    removed: dict[str, tuple[Path, str, dict[str, str]]] = {}
    for name in sorted(set(remove_names)):
        removed[name] = _load_state(name)

    if notify:
        for name in sorted(removed):
            _send_udev_event(removed[name][2], "remove")

    removed_roots = {metadata[0] for metadata in removed.values()}
    for name in sorted(removed):
        _remove_target(name)
        _remove_sysfs_link(name)
        _drop_state(name)
    for root in sorted(
        removed_roots,
        key=lambda p: (len(p.parts), str(p)),
        reverse=True,
    ):
        _umount_all(root)
        print(f"SYSFS_UNBOUND={root}", flush=True)

    for root in sorted(sysfs_mounts, key=str):
        _attach_sysfs_mount(root, sysfs_mounts[root])

    for name in sorted(sysfs_links):
        link_target, _ = sysfs_links[name]
        _install_sysfs_link(name, link_target)

    for name in sorted(device_mounts):
        _attach_device_mount(name, device_mounts[name])

    added_props: dict[str, dict[str, str]] = {}
    for name in sorted(device_mounts):
        link_target, root = sysfs_links[name]
        added_props[name] = _save_state(name, root, link_target)

    if notify:
        for name in sorted(added_props):
            _send_udev_event(added_props[name], "add")

    print(f"NAMESPACE_PID={namespace_pid}", flush=True)
    print("MOUNT_API=open_tree+move_mount", flush=True)


def mutate_instance(
    instance: str,
    bind_paths: list[str],
    remove_names: list[str],
    *,
    notify: bool = False,
) -> None:
    if not hasattr(os, "setns"):
        raise RuntimeError("Python non espone os.setns(); hotplug namespace non disponibile.")

    namespace_pid = find_instance_namespace_pid(instance)
    validated = [_validate_host_node(raw) for raw in bind_paths]
    if len({name for name, _, _, _ in validated}) != len(validated):
        raise RuntimeError("Nodi gamepad duplicati nella richiesta hotplug.")
    remove_names = [_validate_node_name(name) for name in remove_names]

    device_source_fds: dict[str, int] = {}
    sysfs_source_fds: dict[Path, int] = {}
    device_mounts: dict[str, int] = {}
    sysfs_mounts: dict[Path, int] = {}
    sysfs_links: dict[str, tuple[str, Path]] = {}

    user_fd = mnt_fd = net_fd = -1
    try:
        # Exact host resources are opened before entering Bubblejail. No host
        # directory is ever shared.
        for name, path, link_target, sysfs_root in validated:
            device_source_fds[name] = os.open(path, os.O_PATH | os.O_CLOEXEC)
            sysfs_links[name] = (link_target, sysfs_root)
            if sysfs_root not in sysfs_source_fds:
                sysfs_source_fds[sysfs_root] = os.open(
                    sysfs_root, os.O_PATH | os.O_CLOEXEC
                )

        # Namespace descriptors are also captured while /proc still refers to
        # the host PID namespace.
        user_fd = os.open(
            f"/proc/{namespace_pid}/ns/user", os.O_RDONLY | os.O_CLOEXEC
        )
        mnt_fd = os.open(
            f"/proc/{namespace_pid}/ns/mnt", os.O_RDONLY | os.O_CLOEXEC
        )
        net_fd = os.open(
            f"/proc/{namespace_pid}/ns/net", os.O_RDONLY | os.O_CLOEXEC
        )

        need_user = os.readlink("/proc/self/ns/user") != os.readlink(
            f"/proc/{namespace_pid}/ns/user"
        )
        need_net = os.readlink("/proc/self/ns/net") != os.readlink(
            f"/proc/{namespace_pid}/ns/net"
        )

        if need_user:
            os.setns(user_fd, CLONE_NEWUSER)

        # Enter only the mount namespace. PID namespace entry is intentionally
        # unnecessary and is denied on the target CachyOS setup. The exact host
        # FDs opened above remain valid across setns().
        os.setns(mnt_fd, CLONE_NEWNS)

        # Create detached bind mounts directly from the already-authorised FDs.
        # This avoids /proc/self/fd entirely, so the caller's PID namespace is
        # irrelevant.
        for name, source_fd in device_source_fds.items():
            device_mounts[name] = _open_tree_clone(source_fd)
        for root, source_fd in sysfs_source_fds.items():
            sysfs_mounts[root] = _open_tree_clone(source_fd)

        if need_net:
            os.setns(net_fd, CLONE_NEWNET)

        _mutate_inside_namespace(
            device_mounts,
            sysfs_mounts,
            sysfs_links,
            remove_names,
            namespace_pid,
            notify,
        )
    finally:
        for mapping in (
            device_mounts,
            sysfs_mounts,
            device_source_fds,
            sysfs_source_fds,
        ):
            for fd in mapping.values():
                try:
                    os.close(fd)
                except OSError:
                    pass

        for fd in (user_fd, mnt_fd, net_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="RetroCD exact-node gamepad hotplug helper"
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
