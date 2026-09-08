#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from dgvoodoo_backend import BottleInfo, DgVoodooError, manager_data_dir, validate_game_target
from sandbox_backend import INSTANCE

OVERRIDE_SCHEMA_VERSION = 1
REG_BASE = r"HKCU\Software\Wine\AppDefaults"
ABSENT_MARKERS = (
    "reg: Unable to find the specified registry key",
    "reg: Unable to find the specified registry value",
    "ERROR: The system was unable to find the specified registry key or value",
)
_OVERRIDE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_SAFE_VALUE_RE = re.compile(r"^[A-Za-z0-9_, .-]{0,128}$")

Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True, slots=True)
class ActivationStatus:
    state: str
    executable: Path
    app_name: str
    overrides: tuple[str, ...]


def _run(args: list[str], timeout: int = 90) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
            env={**os.environ, "LC_ALL": "C"},
        )
    except FileNotFoundError as exc:
        raise DgVoodooError(f"Comando richiesto non trovato: {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise DgVoodooError(f"Timeout eseguendo {args[0]}.") from exc


def _bottles_cli(bottle: BottleInfo, args: list[str], *, runner: Runner = _run) -> str:
    command = ["bubblejail", "run", "--wait", INSTANCE, "bottles-cli", *args]
    result = runner(command)
    return result.stdout or ""


def _app_name(executable: Path) -> str:
    name = executable.name
    if (
        not name
        or not name.casefold().endswith(".exe")
        or len(name) > 160
        or any(ch in name for ch in ('\\', '/', '"', "'", '\x00', '\n', '\r'))
    ):
        raise DgVoodooError(f"Nome executable non adatto ad AppDefaults Wine: {name!r}")
    return name


def _override_name(name: str) -> str:
    value = name.strip().casefold().removesuffix(".dll")
    if not _OVERRIDE_NAME_RE.fullmatch(value):
        raise DgVoodooError(f"Nome DLL override non valido: {name!r}")
    return value


def _registry_key(app_name: str) -> str:
    return rf"{REG_BASE}\{app_name}\DllOverrides"


def _query_command(app_name: str, override: str) -> str:
    return f'reg query "{_registry_key(app_name)}" /v {override}'


def parse_reg_query(output: str, override: str) -> str | None:
    override = _override_name(override)
    matches: list[str] = []
    pattern = re.compile(
        rf"(?mi)^\s*{re.escape(override)}\s+REG_SZ\s+(.*?)\s*$"
    )
    for match in pattern.finditer(output):
        matches.append(match.group(1))
    if len(matches) == 1:
        value = matches[0]
        if not _SAFE_VALUE_RE.fullmatch(value):
            raise DgVoodooError(f"Valore registro inatteso per {override}: {value!r}")
        return value
    if len(matches) > 1:
        raise DgVoodooError(f"Query registro ambigua per {override}: più valori trovati.")
    if any(marker in output for marker in ABSENT_MARKERS):
        return None
    tail = "\n".join(output.strip().splitlines()[-8:])
    raise DgVoodooError(
        f"Impossibile interpretare la query registro per {override}; output inatteso:\n{tail}"
    )


def query_app_override(
    bottle: BottleInfo,
    executable: Path,
    override: str,
    *,
    runner: Runner = _run,
) -> str | None:
    exe, _arch = validate_game_target(executable, bottle)
    app_name = _app_name(exe)
    name = _override_name(override)
    output = _bottles_cli(
        bottle,
        ["shell", "-b", bottle.name, "-i", _query_command(app_name, name)],
        runner=runner,
    )
    return parse_reg_query(output, name)


def _set_app_override(
    bottle: BottleInfo,
    executable: Path,
    override: str,
    value: str,
    *,
    runner: Runner = _run,
) -> None:
    exe, _arch = validate_game_target(executable, bottle)
    app_name = _app_name(exe)
    name = _override_name(override)
    if not _SAFE_VALUE_RE.fullmatch(value) or not value:
        raise DgVoodooError(f"Valore override non valido per {name}: {value!r}")
    _bottles_cli(
        bottle,
        [
            "reg", "add", "-b", bottle.name,
            "-k", _registry_key(app_name),
            "-v", name,
            "-d", value,
            "-t", "REG_SZ",
        ],
        runner=runner,
    )
    observed = query_app_override(bottle, exe, name, runner=runner)
    if observed != value:
        raise DgVoodooError(
            f"Verifica post-scrittura fallita per {name}: atteso {value!r}, ottenuto {observed!r}."
        )


def _delete_app_override(
    bottle: BottleInfo,
    executable: Path,
    override: str,
    *,
    runner: Runner = _run,
) -> None:
    exe, _arch = validate_game_target(executable, bottle)
    app_name = _app_name(exe)
    name = _override_name(override)
    _bottles_cli(
        bottle,
        [
            "reg", "del", "-b", bottle.name,
            "-k", _registry_key(app_name),
            "-v", name,
        ],
        runner=runner,
    )
    observed = query_app_override(bottle, exe, name, runner=runner)
    if observed is not None:
        raise DgVoodooError(
            f"Verifica post-rimozione fallita per {name}: valore ancora presente {observed!r}."
        )


def _decode_json_list(output: str) -> list[dict]:
    decoder = json.JSONDecoder()
    candidates: list[list] = []
    for index, char in enumerate(output):
        if char != '[':
            continue
        try:
            value, _end = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            candidates.append(value)
    if len(candidates) != 1:
        raise DgVoodooError(
            f"Output JSON di 'bottles-cli programs' ambiguo: attesa una lista, trovate {len(candidates)}."
        )
    return candidates[0]


def _override_lhs_names(spec: str) -> set[str]:
    out: set[str] = set()
    for entry in spec.split(';'):
        lhs, sep, _rhs = entry.partition('=')
        if not sep:
            continue
        for token in re.split(r"[,\s]+", lhs.strip()):
            if not token:
                continue
            try:
                out.add(_override_name(token))
            except DgVoodooError:
                continue
    return out


def check_program_environment_conflicts(
    bottle: BottleInfo,
    executable: Path,
    overrides: Iterable[str],
    *,
    runner: Runner = _run,
) -> None:
    exe, _arch = validate_game_target(executable, bottle)
    app_name = _app_name(exe).casefold()
    wanted = {_override_name(name) for name in overrides}
    output = _bottles_cli(bottle, ["-j", "programs", "-b", bottle.name], runner=runner)
    programs = _decode_json_list(output)
    for program in programs:
        path = program.get("path")
        if not isinstance(path, str):
            continue
        basename = path.replace('\\', '/').rsplit('/', 1)[-1].casefold()
        if basename != app_name:
            continue
        environment = program.get("environment")
        if not isinstance(environment, dict):
            continue
        spec = environment.get("WINEDLLOVERRIDES")
        if not isinstance(spec, str) or not spec.strip():
            continue
        collision = sorted(wanted & _override_lhs_names(spec))
        if collision:
            raise DgVoodooError(
                "Il programma Bottles ha già WINEDLLOVERRIDES con precedenza su AppDefaults "
                f"per: {', '.join(collision)}. Attivazione dgVoodoo2 rifiutata."
            )


def _activation_id(bottle: BottleInfo, executable: Path) -> str:
    material = f"{bottle.root.resolve()}\0{executable.resolve()}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:32]


def _state_dir(data_root: Path, bottle: BottleInfo, executable: Path) -> Path:
    return data_root / "activations" / _activation_id(bottle, executable)


def _state_path(data_root: Path, bottle: BottleInfo, executable: Path) -> Path:
    return _state_dir(data_root, bottle, executable) / "state.json"


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, tmp_name = tempfile.mkstemp(prefix=".state-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def _load_state(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise DgVoodooError(f"Stato override dgVoodoo2 assente/non regolare: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DgVoodooError(f"Stato override dgVoodoo2 non leggibile: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != OVERRIDE_SCHEMA_VERSION:
        raise DgVoodooError("Stato override dgVoodoo2 con schema non supportato.")
    return raw


def activation_status(
    bottle: BottleInfo,
    executable: Path,
    *,
    data_root: Path | None = None,
) -> ActivationStatus:
    exe, _arch = validate_game_target(executable, bottle)
    root = (data_root or manager_data_dir()).resolve(strict=False)
    path = _state_path(root, bottle, exe)
    if not path.exists():
        return ActivationStatus("inactive", exe, _app_name(exe), ())
    state = _load_state(path)
    if state.get("bottle_root") != str(bottle.root.resolve()) or state.get("target_exe") != str(exe):
        raise DgVoodooError("Stato override dgVoodoo2 non appartiene al target richiesto.")
    names = state.get("overrides")
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        raise DgVoodooError("Stato override dgVoodoo2 senza lista valida di override.")
    status = state.get("status")
    if status not in {"pending", "active"}:
        raise DgVoodooError(f"Stato override dgVoodoo2 inatteso: {status!r}")
    return ActivationStatus(status, exe, _app_name(exe), tuple(names))


def activate_app_overrides(
    bottle: BottleInfo,
    executable: Path,
    overrides: Iterable[str],
    *,
    data_root: Path | None = None,
    runner: Runner = _run,
) -> ActivationStatus:
    exe, _arch = validate_game_target(executable, bottle)
    names = tuple(dict.fromkeys(_override_name(name) for name in overrides))
    if not names:
        raise DgVoodooError("Nessun override Wine da attivare.")
    root = (data_root or manager_data_dir()).resolve(strict=False)
    path = _state_path(root, bottle, exe)
    if path.exists() or path.is_symlink():
        raise DgVoodooError("Esiste già uno stato override dgVoodoo2 per questo executable.")

    check_program_environment_conflicts(bottle, exe, names, runner=runner)
    previous = {name: query_app_override(bottle, exe, name, runner=runner) for name in names}
    expected = {name: "n,b" for name in names}
    state = {
        "schema_version": OVERRIDE_SCHEMA_VERSION,
        "status": "pending",
        "bottle_name": bottle.name,
        "bottle_root": str(bottle.root.resolve()),
        "target_exe": str(exe),
        "app_name": _app_name(exe),
        "overrides": list(names),
        "previous": previous,
        "expected": expected,
    }
    _atomic_json(path, state)
    applied: list[str] = []
    try:
        for name in names:
            _set_app_override(bottle, exe, name, expected[name], runner=runner)
            applied.append(name)
        state["status"] = "active"
        _atomic_json(path, state)
    except Exception:
        for name in reversed(applied):
            try:
                old = previous[name]
                if old is None:
                    _delete_app_override(bottle, exe, name, runner=runner)
                else:
                    _set_app_override(bottle, exe, name, old, runner=runner)
            except Exception:
                pass
        raise
    return ActivationStatus("active", exe, _app_name(exe), names)


def deactivate_app_overrides(
    bottle: BottleInfo,
    executable: Path,
    *,
    data_root: Path | None = None,
    runner: Runner = _run,
) -> ActivationStatus:
    exe, _arch = validate_game_target(executable, bottle)
    root = (data_root or manager_data_dir()).resolve(strict=False)
    path = _state_path(root, bottle, exe)
    state = _load_state(path)
    if state.get("bottle_root") != str(bottle.root.resolve()) or state.get("target_exe") != str(exe):
        raise DgVoodooError("Stato override dgVoodoo2 non appartiene al target richiesto.")
    names = state.get("overrides")
    previous = state.get("previous")
    expected = state.get("expected")
    status = state.get("status")
    if (
        status not in {"pending", "active"}
        or not isinstance(names, list)
        or not isinstance(previous, dict)
        or not isinstance(expected, dict)
    ):
        raise DgVoodooError("Stato override dgVoodoo2 incompleto/non valido.")

    observed: dict[str, str | None] = {}
    for raw_name in names:
        name = _override_name(raw_name)
        value = query_app_override(bottle, exe, name, runner=runner)
        observed[name] = value
        if status == "active" and value != expected.get(name):
            raise DgVoodooError(
                f"Override Wine {name} modificato dopo l'attivazione: atteso {expected.get(name)!r}, "
                f"ottenuto {value!r}. Ripristino automatico rifiutato."
            )
        if status == "pending" and value not in {expected.get(name), previous.get(name)}:
            raise DgVoodooError(
                f"Override Wine {name} in stato pending ma con valore estraneo {value!r}; restore rifiutato."
            )

    restored: list[str] = []
    try:
        for raw_name in names:
            name = _override_name(raw_name)
            old = previous.get(name)
            if old is None:
                _delete_app_override(bottle, exe, name, runner=runner)
            else:
                if not isinstance(old, str):
                    raise DgVoodooError(f"Snapshot precedente non valido per {name}.")
                _set_app_override(bottle, exe, name, old, runner=runner)
            restored.append(name)
    except Exception:
        for name in restored:
            try:
                current = observed[name]
                if current is None:
                    _delete_app_override(bottle, exe, name, runner=runner)
                else:
                    _set_app_override(bottle, exe, name, current, runner=runner)
            except Exception:
                pass
        raise

    path.unlink()
    try:
        path.parent.rmdir()
    except OSError:
        pass
    return ActivationStatus("inactive", exe, _app_name(exe), tuple(_override_name(n) for n in names))


def tamper_refusal_test(
    bottle: BottleInfo,
    executable: Path,
    override: str,
    *,
    data_root: Path | None = None,
    runner: Runner = _run,
) -> str:
    exe, _arch = validate_game_target(executable, bottle)
    name = _override_name(override)
    status = activation_status(bottle, exe, data_root=data_root)
    if status.state != "active" or name not in status.overrides:
        raise DgVoodooError(f"Override {name} non attivo nella transazione corrente.")
    _set_app_override(bottle, exe, name, "b", runner=runner)
    try:
        try:
            deactivate_app_overrides(bottle, exe, data_root=data_root, runner=runner)
        except DgVoodooError as exc:
            message = str(exc)
            if "modificato dopo" not in message:
                raise DgVoodooError(
                    f"Tamper test override fallito per motivo inatteso: {message}"
                ) from exc
        else:
            raise DgVoodooError("ERRORE: restore ha accettato un override Wine modificato.")
    finally:
        _set_app_override(bottle, exe, name, "n,b", runner=runner)
    return message
