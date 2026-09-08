#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import struct
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Iterable

APP_DIRNAME = "bottles-retro-cd"
SCHEMA_VERSION = 1
OFFICIAL_REPOSITORY = "dege-diosg/dgVoodoo2"
LATEST_RELEASE_API = f"https://api.github.com/repos/{OFFICIAL_REPOSITORY}/releases/latest"
RELEASE_ASSET_RE = re.compile(r"^dgVoodoo2_[0-9_]+\.zip$", re.IGNORECASE)
SHA256_RE = re.compile(r"^sha256:([0-9a-fA-F]{64})$")
USER_AGENT = "Bottles-RetroCD-dgVoodoo2/0.1"
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_MEMBER_BYTES = 32 * 1024 * 1024
MAX_SELECTED_BYTES = 96 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 512

API_HOSTS = frozenset({"api.github.com"})
DOWNLOAD_HOSTS = frozenset({
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
})


class DgVoodooError(RuntimeError):
    pass


class TargetArch(str, Enum):
    X86 = "x86"
    X64 = "x64"


class Wrapper(str, Enum):
    DDRAW = "ddraw"
    D3DIMM = "d3dimm"
    D3DIM700 = "d3dim700"
    D3D8 = "d3d8"
    D3D9 = "d3d9"
    GLIDE = "glide"
    GLIDE2X = "glide2x"
    GLIDE3X = "glide3x"
    GLIDE3X_NAPALM = "glide3x_napalm"


@dataclass(frozen=True, slots=True)
class ReleaseInfo:
    tag: str
    version: str
    asset_name: str
    download_url: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class BottleInfo:
    name: str
    root: Path
    drive_c: Path


@dataclass(frozen=True, slots=True)
class InstallReport:
    version: str
    target_exe: Path
    arch: TargetArch
    wrappers: tuple[Wrapper, ...]
    installed_files: tuple[Path, ...]
    preserved_files: tuple[Path, ...]
    manifest_path: Path


def _xdg_data_home() -> Path:
    value = os.environ.get("XDG_DATA_HOME")
    return Path(value).expanduser() if value else Path.home() / ".local" / "share"


def _xdg_cache_home() -> Path:
    value = os.environ.get("XDG_CACHE_HOME")
    return Path(value).expanduser() if value else Path.home() / ".cache"


def manager_data_dir() -> Path:
    return _xdg_data_home() / APP_DIRNAME / "dgvoodoo2"


def manager_cache_dir() -> Path:
    return _xdg_cache_home() / APP_DIRNAME / "dgvoodoo2"


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _validate_https(url: str, allowed_hosts: frozenset[str]) -> str:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme.lower() != "https":
        raise DgVoodooError(f"URL dgVoodoo2 non HTTPS rifiutato: {url}")
    if host not in allowed_hosts:
        raise DgVoodooError(f"Host dgVoodoo2 non autorizzato: {host or '<vuoto>'}")
    if parsed.username or parsed.password:
        raise DgVoodooError("Credenziali nell'URL dgVoodoo2 non ammesse.")
    return url


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts: frozenset[str]):
        super().__init__()
        self.allowed_hosts = allowed_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        _validate_https(newurl, self.allowed_hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def parse_release_metadata(payload: bytes) -> ReleaseInfo:
    if len(payload) > MAX_METADATA_BYTES:
        raise DgVoodooError("Metadata release dgVoodoo2 troppo grandi.")
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DgVoodooError(f"Metadata release dgVoodoo2 non validi: {exc}") from exc
    if not isinstance(raw, dict):
        raise DgVoodooError("Metadata release dgVoodoo2 inattesi.")

    tag = raw.get("tag_name")
    if not isinstance(tag, str) or not re.fullmatch(r"v2\.[0-9]+(?:\.[0-9]+)*", tag):
        raise DgVoodooError(f"Tag dgVoodoo2 inatteso: {tag!r}")
    if raw.get("draft") or raw.get("prerelease"):
        raise DgVoodooError("La release dgVoodoo2 latest non è una release stabile pubblicata.")

    candidates: list[ReleaseInfo] = []
    for asset in raw.get("assets", []):
        if not isinstance(asset, dict):
            continue
        name = asset.get("name")
        if not isinstance(name, str) or not RELEASE_ASSET_RE.fullmatch(name):
            continue
        if name.casefold().endswith("_dbg.zip") or name.casefold().endswith("_dev64.zip"):
            continue
        digest = asset.get("digest")
        match = SHA256_RE.fullmatch(digest) if isinstance(digest, str) else None
        url = asset.get("browser_download_url")
        size = asset.get("size")
        if not match or not isinstance(url, str) or not isinstance(size, int):
            continue
        _validate_https(url, DOWNLOAD_HOSTS)
        if size <= 0 or size > MAX_ARCHIVE_BYTES:
            raise DgVoodooError(f"Dimensione asset dgVoodoo2 non ammessa: {size}")
        candidates.append(
            ReleaseInfo(
                tag=tag,
                version=tag.removeprefix("v"),
                asset_name=name,
                download_url=url,
                sha256=match.group(1).lower(),
                size=size,
            )
        )
    if len(candidates) != 1:
        raise DgVoodooError(
            f"Release dgVoodoo2: atteso un solo ZIP runtime ufficiale, trovati {len(candidates)}."
        )
    return candidates[0]


def fetch_latest_release(timeout: float = 12.0) -> ReleaseInfo:
    _validate_https(LATEST_RELEASE_API, API_HOSTS)
    opener = urllib.request.build_opener(_SafeRedirect(API_HOSTS))
    req = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    try:
        response = opener.open(req, timeout=timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DgVoodooError(f"Impossibile leggere la release ufficiale dgVoodoo2: {exc}") from exc
    with response:
        final = response.geturl()
        _validate_https(final, API_HOSTS)
        data = response.read(MAX_METADATA_BYTES + 1)
    return parse_release_metadata(data)


def download_release(
    release: ReleaseInfo,
    *,
    cache_root: Path | None = None,
    timeout: float = 45.0,
) -> Path:
    _validate_https(release.download_url, DOWNLOAD_HOSTS)
    cache_root = cache_root or manager_cache_dir()
    target_dir = cache_root / "releases" / release.tag
    _ensure_private_dir(target_dir)
    target = target_dir / release.asset_name
    if target.is_file():
        if target.stat().st_size == release.size and sha256_file(target) == release.sha256:
            return target
        target.unlink()
    elif target.exists():
        raise DgVoodooError(f"Cache dgVoodoo2 non è un file regolare: {target}")

    opener = urllib.request.build_opener(_SafeRedirect(DOWNLOAD_HOSTS))
    req = urllib.request.Request(release.download_url, headers={"User-Agent": USER_AGENT})
    part = target.with_suffix(target.suffix + ".part")
    try:
        response = opener.open(req, timeout=timeout)
        digest = hashlib.sha256()
        written = 0
        with response, part.open("wb") as out:
            _validate_https(response.geturl(), DOWNLOAD_HOSTS)
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_ARCHIVE_BYTES:
                    raise DgVoodooError("Download dgVoodoo2 supera il limite previsto.")
                digest.update(chunk)
                out.write(chunk)
        if written != release.size:
            raise DgVoodooError(
                f"Dimensione dgVoodoo2 diversa dai metadata: {written} != {release.size}."
            )
        actual = digest.hexdigest()
        if actual != release.sha256:
            raise DgVoodooError(
                f"SHA-256 dgVoodoo2 non corrisponde: atteso {release.sha256}, ottenuto {actual}."
            )
        os.chmod(part, 0o600)
        os.replace(part, target)
        return target
    except Exception:
        try:
            part.unlink()
        except FileNotFoundError:
            pass
        raise


def bottles_root(private_home: Path) -> Path:
    return private_home / ".local" / "share" / "bottles" / "bottles"


def discover_bottles(private_home: Path) -> tuple[BottleInfo, ...]:
    root = bottles_root(private_home)
    if not root.is_dir():
        return ()
    out: list[BottleInfo] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.casefold()):
        if child.is_symlink() or not child.is_dir():
            continue
        config = child / "bottle.yml"
        drive = child / "drive_c"
        if config.is_file() and not config.is_symlink() and drive.is_dir() and not drive.is_symlink():
            out.append(BottleInfo(child.name, child.resolve(), drive.resolve()))
    return tuple(out)


def detect_pe_arch(executable: Path) -> TargetArch:
    executable = executable.resolve(strict=True)
    if not executable.is_file() or executable.is_symlink():
        raise DgVoodooError(f"Executable non regolare: {executable}")
    try:
        with executable.open("rb") as fh:
            header = fh.read(64)
            if len(header) < 64 or header[:2] != b"MZ":
                raise DgVoodooError(f"File non PE/MZ: {executable}")
            pe_offset = struct.unpack_from("<I", header, 0x3C)[0]
            if pe_offset < 64 or pe_offset > 16 * 1024 * 1024:
                raise DgVoodooError(f"Offset PE inatteso: {pe_offset}")
            fh.seek(pe_offset)
            signature = fh.read(4)
            machine_raw = fh.read(2)
    except OSError as exc:
        raise DgVoodooError(f"Impossibile leggere {executable}: {exc}") from exc
    if signature != b"PE\x00\x00" or len(machine_raw) != 2:
        raise DgVoodooError(f"Firma PE non valida: {executable}")
    machine = struct.unpack("<H", machine_raw)[0]
    if machine == 0x014C:
        return TargetArch.X86
    if machine == 0x8664:
        return TargetArch.X64
    raise DgVoodooError(f"Architettura PE non supportata da questo manager: 0x{machine:04x}")


def validate_game_target(executable: Path, bottle: BottleInfo) -> tuple[Path, TargetArch]:
    exe = executable.resolve(strict=True)
    drive = bottle.drive_c.resolve(strict=True)
    if not exe.is_relative_to(drive):
        raise DgVoodooError(f"Executable fuori da drive_c della bottle {bottle.name}: {exe}")
    if exe.parent.is_symlink():
        raise DgVoodooError(f"Directory gioco symlink non ammessa: {exe.parent}")
    return exe, detect_pe_arch(exe)


def _source_path(wrapper: Wrapper, arch: TargetArch) -> str:
    base = arch.value
    paths = {
        Wrapper.DDRAW: f"MS/{base}/DDraw.dll",
        Wrapper.D3DIMM: f"MS/{base}/D3DImm.dll",
        Wrapper.D3DIM700: f"MS/{base}/D3DIM700.dll",
        Wrapper.D3D8: f"MS/{base}/D3D8.dll",
        Wrapper.D3D9: f"MS/{base}/D3D9.dll",
        Wrapper.GLIDE: f"3Dfx/{base}/Glide.dll",
        Wrapper.GLIDE2X: f"3Dfx/{base}/Glide2x.dll",
        Wrapper.GLIDE3X: f"3Dfx/{base}/Glide3x.dll",
        Wrapper.GLIDE3X_NAPALM: f"3Dfx/{base}/Napalm/Glide3x.dll",
    }
    return paths[wrapper]


def wrapper_destination(wrapper: Wrapper) -> str:
    return {
        Wrapper.DDRAW: "DDraw.dll",
        Wrapper.D3DIMM: "D3DImm.dll",
        Wrapper.D3DIM700: "D3DIM700.dll",
        Wrapper.D3D8: "D3D8.dll",
        Wrapper.D3D9: "D3D9.dll",
        Wrapper.GLIDE: "Glide.dll",
        Wrapper.GLIDE2X: "Glide2x.dll",
        Wrapper.GLIDE3X: "Glide3x.dll",
        Wrapper.GLIDE3X_NAPALM: "Glide3x.dll",
    }[wrapper]


def wine_override_names(wrappers: Iterable[Wrapper]) -> tuple[str, ...]:
    mapping = {
        Wrapper.DDRAW: "ddraw",
        Wrapper.D3DIMM: "d3dimm",
        Wrapper.D3DIM700: "d3dim700",
        Wrapper.D3D8: "d3d8",
        Wrapper.D3D9: "d3d9",
        Wrapper.GLIDE: "glide",
        Wrapper.GLIDE2X: "glide2x",
        Wrapper.GLIDE3X: "glide3x",
        Wrapper.GLIDE3X_NAPALM: "glide3x",
    }
    return tuple(dict.fromkeys(mapping[item] for item in wrappers))


def wine_overrides_value(wrappers: Iterable[Wrapper]) -> str:
    names = wine_override_names(wrappers)
    return ";".join(f"{name}=n,b" for name in names)


def _zip_index(zf: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = zf.infolist()
    if len(infos) > MAX_ARCHIVE_MEMBERS:
        raise DgVoodooError(f"Archivio dgVoodoo2 con troppi membri: {len(infos)}")
    index: dict[str, zipfile.ZipInfo] = {}
    for info in infos:
        raw = info.filename.replace("\\", "/")
        pure = PurePosixPath(raw)
        if not raw or raw.startswith("/") or ".." in pure.parts:
            raise DgVoodooError(f"Path ZIP dgVoodoo2 non sicuro: {info.filename!r}")
        mode = (info.external_attr >> 16) & 0o170000
        if mode == stat.S_IFLNK:
            raise DgVoodooError(f"Symlink ZIP dgVoodoo2 rifiutato: {info.filename!r}")
        if info.file_size > MAX_MEMBER_BYTES:
            raise DgVoodooError(f"Membro dgVoodoo2 troppo grande: {info.filename}")
        if info.is_dir():
            continue
        key = str(pure).casefold()
        if key in index:
            raise DgVoodooError(f"Membro dgVoodoo2 duplicato per case-fold: {info.filename}")
        index[key] = info
    return index


def _read_member(
    zf: zipfile.ZipFile,
    index: dict[str, zipfile.ZipInfo],
    path: str,
) -> bytes:
    info = index.get(path.casefold())
    if info is None:
        raise DgVoodooError(f"File atteso assente dall'archivio dgVoodoo2: {path}")
    data = zf.read(info)
    if len(data) != info.file_size:
        raise DgVoodooError(f"Lettura incompleta del membro dgVoodoo2: {path}")
    return data


def _installation_key(bottle: BottleInfo, executable: Path) -> str:
    material = f"{bottle.root.resolve()}\0{executable.resolve()}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:32]


def _installation_dir(data_root: Path, bottle: BottleInfo, executable: Path) -> Path:
    return data_root / "installations" / _installation_key(bottle, executable)


def _atomic_write(path: Path, data: bytes, mode: int = 0o644) -> None:
    if path.exists() and path.is_symlink():
        raise DgVoodooError(f"Destinazione symlink rifiutata: {path}")
    tmp = path.with_name(f".{path.name}.retrocd-dgvoodoo.tmp")
    try:
        with tmp.open("wb") as fh:
            fh.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def install_wrappers(
    archive: Path,
    release: ReleaseInfo,
    bottle: BottleInfo,
    executable: Path,
    wrappers: Iterable[Wrapper],
    *,
    data_root: Path | None = None,
    include_control_panel: bool = True,
    preserve_existing_config: bool = True,
) -> InstallReport:
    archive = archive.resolve(strict=True)
    if not archive.is_file() or archive.is_symlink():
        raise DgVoodooError(f"Archivio dgVoodoo2 non regolare: {archive}")
    if archive.stat().st_size != release.size or sha256_file(archive) != release.sha256:
        raise DgVoodooError("Archivio dgVoodoo2 non corrisponde ai metadata ufficiali verificati.")

    exe, arch = validate_game_target(executable, bottle)
    target_dir = exe.parent.resolve(strict=True)
    selected = tuple(dict.fromkeys(wrappers))
    if not selected:
        raise DgVoodooError("Seleziona almeno un wrapper dgVoodoo2.")
    destinations = [wrapper_destination(item) for item in selected]
    if len(destinations) != len({name.casefold() for name in destinations}):
        raise DgVoodooError(
            "Selezione dgVoodoo2 ambigua: due wrapper produrrebbero lo stesso nome file."
        )

    data_root = (data_root or manager_data_dir()).resolve(strict=False)
    installs_root = data_root / "installations"
    _ensure_private_dir(data_root)
    _ensure_private_dir(installs_root)
    final_dir = _installation_dir(data_root, bottle, exe)
    if final_dir.exists():
        raise DgVoodooError(
            "dgVoodoo2 risulta già gestito da RetroCD per questo executable; disinstalla/ripristina prima."
        )

    try:
        zf = zipfile.ZipFile(archive)
    except (OSError, zipfile.BadZipFile) as exc:
        raise DgVoodooError(f"Archivio dgVoodoo2 non valido: {exc}") from exc

    with zf:
        index = _zip_index(zf)
        payloads: list[tuple[str, bytes, str]] = []
        total = 0
        for wrapper in selected:
            source = _source_path(wrapper, arch)
            data = _read_member(zf, index, source)
            total += len(data)
            payloads.append((wrapper_destination(wrapper), data, source))
        config_data = _read_member(zf, index, "dgVoodoo.conf")
        total += len(config_data)
        cpl_data = b""
        if include_control_panel:
            cpl_data = _read_member(zf, index, "dgVoodooCpl.exe")
            total += len(cpl_data)
        if total > MAX_SELECTED_BYTES:
            raise DgVoodooError("Payload dgVoodoo2 selezionato troppo grande.")

    staging = Path(tempfile.mkdtemp(prefix=".install-", dir=installs_root))
    os.chmod(staging, 0o700)
    backup_dir = staging / "backup"
    _ensure_private_dir(backup_dir)
    managed: list[dict[str, object]] = []
    preserved: list[str] = []
    applied: list[tuple[Path, Path | None]] = []

    def apply_payload(name: str, data: bytes, source: str, *, preserve: bool = False) -> None:
        dest = target_dir / name
        if dest.exists() and dest.is_symlink():
            raise DgVoodooError(f"Destinazione dgVoodoo2 symlink rifiutata: {dest}")
        if preserve and dest.exists():
            preserved.append(name)
            return
        backup: Path | None = None
        original_sha = ""
        if dest.exists():
            if not dest.is_file():
                raise DgVoodooError(f"Destinazione dgVoodoo2 non regolare: {dest}")
            backup = backup_dir / f"{len(managed):03d}-{name}.orig"
            shutil.copy2(dest, backup)
            os.chmod(backup, 0o600)
            original_sha = sha256_file(backup)
        _atomic_write(dest, data)
        installed_sha = _sha256_bytes(data)
        managed.append({
            "name": name,
            "source": source,
            "installed_sha256": installed_sha,
            "backup": str(backup.relative_to(staging)) if backup else "",
            "original_sha256": original_sha,
        })
        applied.append((dest, backup))

    try:
        for name, data, source in payloads:
            apply_payload(name, data, source)
        apply_payload(
            "dgVoodoo.conf",
            config_data,
            "dgVoodoo.conf",
            preserve=preserve_existing_config,
        )
        if include_control_panel:
            apply_payload("dgVoodooCpl.exe", cpl_data, "dgVoodooCpl.exe")

        manifest = {
            "schema_version": SCHEMA_VERSION,
            "release": {
                "tag": release.tag,
                "version": release.version,
                "asset_name": release.asset_name,
                "sha256": release.sha256,
            },
            "bottle": {
                "name": bottle.name,
                "root": str(bottle.root.resolve()),
                "drive_c": str(bottle.drive_c.resolve()),
            },
            "target_exe": str(exe),
            "target_dir": str(target_dir),
            "arch": arch.value,
            "wrappers": [item.value for item in selected],
            "wine_overrides": wine_overrides_value(selected),
            "managed_files": managed,
            "preserved_files": preserved,
        }
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(manifest_path, 0o600)
        os.replace(staging, final_dir)
    except Exception:
        for dest, backup in reversed(applied):
            try:
                if backup is not None and backup.is_file():
                    shutil.copy2(backup, dest)
                else:
                    dest.unlink()
            except OSError:
                pass
        shutil.rmtree(staging, ignore_errors=True)
        raise

    installed_paths = tuple(target_dir / str(item["name"]) for item in managed)
    preserved_paths = tuple(target_dir / name for name in preserved)
    return InstallReport(
        version=release.version,
        target_exe=exe,
        arch=arch,
        wrappers=selected,
        installed_files=installed_paths,
        preserved_files=preserved_paths,
        manifest_path=final_dir / "manifest.json",
    )


def _load_manifest(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DgVoodooError(f"Manifest dgVoodoo2 non leggibile: {path}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
        raise DgVoodooError(f"Manifest dgVoodoo2 con schema non supportato: {path}")
    return raw


def uninstall_wrappers(
    bottle: BottleInfo,
    executable: Path,
    *,
    data_root: Path | None = None,
) -> tuple[Path, ...]:
    exe, _arch = validate_game_target(executable, bottle)
    data_root = (data_root or manager_data_dir()).resolve(strict=False)
    install_dir = _installation_dir(data_root, bottle, exe)
    manifest_path = install_dir / "manifest.json"
    manifest = _load_manifest(manifest_path)
    if Path(str(manifest.get("target_exe", ""))).resolve(strict=False) != exe:
        raise DgVoodooError("Manifest dgVoodoo2 non appartiene all'executable richiesto.")
    target_dir = Path(str(manifest.get("target_dir", ""))).resolve(strict=True)
    if target_dir != exe.parent.resolve(strict=True):
        raise DgVoodooError("Directory target dgVoodoo2 diversa dal manifest.")

    managed = manifest.get("managed_files")
    if not isinstance(managed, list) or not managed:
        raise DgVoodooError("Manifest dgVoodoo2 senza file gestiti.")

    prepared: list[tuple[Path, Path | None]] = []
    for entry in managed:
        if not isinstance(entry, dict):
            raise DgVoodooError("Voce manifest dgVoodoo2 non valida.")
        name = entry.get("name")
        expected = entry.get("installed_sha256")
        if not isinstance(name, str) or Path(name).name != name:
            raise DgVoodooError(f"Nome file manifest dgVoodoo2 non valido: {name!r}")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise DgVoodooError(f"Hash manifest dgVoodoo2 non valido per {name}")
        dest = target_dir / name
        if dest.is_symlink() or not dest.is_file():
            raise DgVoodooError(f"File gestito dgVoodoo2 mancante/non regolare: {dest}")
        actual = sha256_file(dest)
        if actual != expected:
            raise DgVoodooError(
                f"File gestito modificato dopo l'installazione: {dest}. Ripristino automatico rifiutato."
            )
        backup_raw = entry.get("backup", "")
        backup: Path | None = None
        if backup_raw:
            if not isinstance(backup_raw, str):
                raise DgVoodooError("Percorso backup dgVoodoo2 non valido.")
            backup = (install_dir / backup_raw).resolve(strict=True)
            if not backup.is_relative_to(install_dir.resolve(strict=True)) or not backup.is_file():
                raise DgVoodooError(f"Backup dgVoodoo2 non valido: {backup}")
            original_sha = entry.get("original_sha256", "")
            if not isinstance(original_sha, str) or sha256_file(backup) != original_sha:
                raise DgVoodooError(f"Backup dgVoodoo2 corrotto: {backup}")
        prepared.append((dest, backup))

    rollback_dir = Path(tempfile.mkdtemp(prefix=".uninstall-", dir=install_dir))
    os.chmod(rollback_dir, 0o700)
    rollback: list[tuple[Path, Path]] = []
    restored: list[Path] = []
    try:
        for index, (dest, _backup) in enumerate(prepared):
            copy = rollback_dir / f"{index:03d}-{dest.name}.installed"
            shutil.copy2(dest, copy)
            rollback.append((dest, copy))
        for dest, backup in prepared:
            if backup is None:
                dest.unlink()
            else:
                tmp_data = backup.read_bytes()
                _atomic_write(dest, tmp_data)
            restored.append(dest)
    except Exception:
        for dest, copy in rollback:
            try:
                shutil.copy2(copy, dest)
            except OSError:
                pass
        raise
    finally:
        shutil.rmtree(rollback_dir, ignore_errors=True)

    shutil.rmtree(install_dir)
    return tuple(restored)
