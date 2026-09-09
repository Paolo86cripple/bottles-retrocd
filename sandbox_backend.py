#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path

from settings_backend import config_dir, load_settings, normalize_archive_root


def configured_archive_root() -> Path:
    explicit = normalize_archive_root(os.environ.get("BOTTLES_RETRO_CD_ARCHIVE_ROOT", ""))
    if explicit:
        return Path(explicit)
    configured = normalize_archive_root(load_settings().get("archive_root", ""))
    if configured:
        return Path(configured)
    # Deliberately nonexistent placeholder: a new installation must select an
    # archive explicitly instead of inheriting a machine-specific storage path.
    return config_dir() / ".archive-not-configured"


RETROPC_ROOT = configured_archive_root()
# Kept as compatibility aliases for the reviewed controller. They now point to
# the explicit archive boundary rather than a machine-specific removable disk.
DATA_ROOT = RETROPC_ROOT
EGLLIBRARY_ROOT = RETROPC_ROOT
INSTANCE = os.environ.get("BOTTLES_RETRO_CD_INSTANCE", "Bottles")


def xdg_data_home() -> Path:
    value = os.environ.get("XDG_DATA_HOME")
    return Path(value).expanduser() if value else Path.home() / ".local" / "share"


def run_cmd(args: list[str], *, input_text: str | None = None, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
            env={**os.environ, "LC_ALL": "C"},
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"Comando non trovato: {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Timeout eseguendo: {' '.join(args)}") from exc


@dataclass(slots=True)
class AuditResult:
    rw: tuple[str, ...]
    ro: tuple[str, ...]
    home: tuple[str, ...]
    dangerous: tuple[str, ...]
    network_persistent: bool

    @property
    def safe(self) -> bool:
        return not self.dangerous and not self.network_persistent


class SandboxBackend:
    def __init__(self, instance: str = INSTANCE):
        self.instance = instance

    @property
    def instance_dir(self) -> Path:
        return xdg_data_home() / "bubblejail" / "instances" / self.instance

    @property
    def services_path(self) -> Path:
        return self.instance_dir / "services.toml"

    @property
    def private_home(self) -> Path:
        return self.instance_dir / "home"

    @property
    def backup_path(self) -> Path:
        return self.instance_dir / "services.toml.bottles-retro-cd.bak"

    def config(self) -> dict:
        try:
            with self.services_path.open("rb") as fh:
                return tomllib.load(fh)
        except OSError as exc:
            raise RuntimeError(f"Impossibile leggere {self.services_path}: {exc}") from exc
        except tomllib.TOMLDecodeError as exc:
            raise RuntimeError(f"services.toml non valido: {exc}") from exc

    @staticmethod
    def _norm(value: str, *, strict: bool = False) -> Path:
        p = Path(os.path.abspath(os.path.expanduser(value)))
        try:
            return p.resolve(strict=strict)
        except OSError:
            return p.resolve(strict=False)

    @staticmethod
    def _is_same_or_parent(parent: Path, child: Path) -> bool:
        return parent == child or parent in child.parents

    def _danger_for_path(self, p: Path, mode: str) -> str | None:
        p = p.resolve(strict=False)
        home = Path.home().resolve(strict=False)
        archive = RETROPC_ROOT.resolve(strict=False)

        # Never allow a persistent share broad enough to expose the real HOME
        # or the whole RetroCD archive. Optical media is granted dynamically.
        if p == Path("/") or self._is_same_or_parent(p, home):
            return f"{mode}:{p} espone HOME o un suo genitore"
        if self._is_same_or_parent(p, archive):
            return f"{mode}:{p} è troppo ampio (include l'archivio RetroCD)"

        # Device/system trees should be granted dynamically by the CD launcher,
        # never as a persistent root_share.
        blocked = (Path("/dev"), Path("/proc"), Path("/sys"), Path("/run"))
        if any(p == b for b in blocked):
            return f"{mode}:{p} è un albero di sistema troppo ampio"
        return None

    def _validate_whitelist(self, rw: list[str], ro: list[str]) -> tuple[list[str], list[str]]:
        def canon_many(items: list[str], mode: str) -> list[str]:
            out: list[str] = []
            seen: set[Path] = set()
            for raw in items:
                p = self._norm(raw, strict=True)
                if not p.is_dir():
                    raise RuntimeError(f"{mode}: non è una directory: {p}")
                danger = self._danger_for_path(p, mode)
                if danger:
                    raise RuntimeError(danger)
                if p in seen:
                    continue
                seen.add(p)
                out.append(str(p))
            return out

        rw_c = canon_many(rw, "RW")
        ro_c = canon_many(ro, "RO")
        rw_set = {Path(x) for x in rw_c}
        ro_set = {Path(x) for x in ro_c}
        both = rw_set & ro_set
        if both:
            raise RuntimeError("Percorso presente sia RW sia RO: " + ", ".join(map(str, sorted(both))))

        all_items = [(Path(x), "RW") for x in rw_c] + [(Path(x), "RO") for x in ro_c]
        for i, (a, amode) in enumerate(all_items):
            for b, bmode in all_items[i + 1:]:
                if a in b.parents or b in a.parents:
                    raise RuntimeError(
                        f"Bind annidati non ammessi: {amode}:{a} ↔ {bmode}:{b}. "
                        "Usa directory sorelle/non sovrapposte."
                    )
        return rw_c, ro_c

    def set_whitelist(self, rw: list[str], ro: list[str]) -> Path:
        if self.running():
            raise RuntimeError("Chiudi Bottles/Bubblejail prima di modificare la whitelist.")
        rw_c, ro_c = self._validate_whitelist(rw, ro)

        try:
            text = self.services_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"Impossibile leggere {self.services_path}: {exc}") from exc

        # Remove the existing [root_share] section while preserving all other
        # Bubblejail settings/comments verbatim.
        pattern = re.compile(r"(?ms)^\[root_share\]\s*\n.*?(?=^\[[^\n]+\]\s*$|\Z)")
        base = re.sub(pattern, "", text).rstrip() + "\n"

        if rw_c or ro_c:
            def toml_array(values: list[str]) -> str:
                if not values:
                    return "[]"
                body = ",\n".join(f"    {json.dumps(v, ensure_ascii=False)}" for v in values)
                return "[\n" + body + ",\n]"

            section = (
                "\n[root_share]\n"
                f"paths = {toml_array(rw_c)}\n"
                f"read_only_paths = {toml_array(ro_c)}\n"
            )
            updated = base + section
        else:
            updated = base

        try:
            tomllib.loads(updated)
        except tomllib.TOMLDecodeError as exc:
            raise RuntimeError(f"La modifica produrrebbe TOML non valido: {exc}") from exc

        shutil.copy2(self.services_path, self.backup_path)
        tmp = self.services_path.with_suffix(".toml.tmp")
        tmp.write_text(updated, encoding="utf-8")
        os.chmod(tmp, self.services_path.stat().st_mode & 0o777)
        os.replace(tmp, self.services_path)
        return self.backup_path

    def restore_backup(self) -> None:
        if self.running():
            raise RuntimeError("Chiudi Bottles/Bubblejail prima di ripristinare il profilo.")
        if not self.backup_path.exists():
            raise RuntimeError("Nessun backup whitelist disponibile.")
        shutil.copy2(self.backup_path, self.services_path)
        self.config()  # verify after restore

    def audit(self) -> AuditResult:
        cfg = self.config()
        root = cfg.get("root_share", {}) or {}
        rw = tuple(str(self._norm(x)) for x in root.get("paths", []))
        ro = tuple(str(self._norm(x)) for x in root.get("read_only_paths", []))
        home = tuple(str(x) for x in (cfg.get("home_share", {}) or {}).get("home_paths", []))
        dangerous: list[str] = []

        rw_paths = [Path(x) for x in rw]
        ro_paths = [Path(x) for x in ro]
        for p in rw_paths:
            if not p.is_dir():
                dangerous.append(f"RW:{p} inesistente")
            elif msg := self._danger_for_path(p, "RW"):
                dangerous.append(msg)
        for p in ro_paths:
            if not p.is_dir():
                dangerous.append(f"RO:{p} inesistente")
            elif msg := self._danger_for_path(p, "RO"):
                dangerous.append(msg)
        for raw in home:
            dangerous.append(f"HOME:{raw} (home_share non ammesso)")

        all_items = [(p, "RW") for p in rw_paths] + [(p, "RO") for p in ro_paths]
        for i, (a, amode) in enumerate(all_items):
            for b, bmode in all_items[i + 1:]:
                if a == b:
                    dangerous.append(f"duplicato {amode}/{bmode}:{a}")
                elif a in b.parents or b in a.parents:
                    dangerous.append(f"bind annidati {amode}:{a} ↔ {bmode}:{b}")

        return AuditResult(
            rw=rw,
            ro=ro,
            home=home,
            dangerous=tuple(dict.fromkeys(dangerous)),
            network_persistent="network" in cfg,
        )

    def running(self) -> bool:
        result = run_cmd(["bubblejail", "run", "--dry-run", self.instance], timeout=20)
        return "Found helper socket" in result.stdout

    def ensure_runtime_args_supported(self) -> None:
        """Fail closed if this Bubblejail build lacks runtime bwrap arguments."""
        result = run_cmd(["bubblejail", "run", "--help"], timeout=10)
        if result.returncode != 0 or "--debug-bwrap-args" not in result.stdout:
            raise RuntimeError(
                "Questa versione di Bubblejail non espone --debug-bwrap-args; "
                "rete temporanea e bind/device CD dinamici non sono supportati in sicurezza."
            )

    def test(self) -> list[tuple[str, str, str]]:
        if shutil.which("bubblejail") is None:
            return [("FAIL", "bubblejail", "comando non trovato")]
        if not self.services_path.exists():
            return [("FAIL", "istanza", f"{self.services_path} non esiste")]
        if self.running():
            return [("FAIL", "istanza", "Bottles/Bubblejail è già in esecuzione; chiudilo prima del test")]

        audit = self.audit()
        results: list[tuple[str, str, str]] = []
        if audit.dangerous:
            results.append(("FAIL", "whitelist profilo", ", ".join(audit.dangerous)))
        else:
            results.append(("PASS", "whitelist profilo", f"RW={audit.rw or ('nessuna',)} RO={audit.ro or ('nessuna',)}"))
        results.append((
            "FAIL" if audit.network_persistent else "PASS",
            "rete persistente",
            "[network] presente" if audit.network_persistent else "[network] assente",
        ))
        if audit.dangerous or audit.network_persistent:
            results.append(("FAIL", "test runtime bloccato", "correggere prima whitelist/rete persistente"))
            return results

        marker = f".bottles-retro-test-{uuid.uuid4().hex}"
        host_only = f".bottles-retro-host-only-{uuid.uuid4().hex}"
        host_only_path = Path.home() / host_only
        host_only_path.write_text("host-only\n", encoding="utf-8")

        archive_parent = RETROPC_ROOT.parent
        try:
            unshared_path = Path(tempfile.mkdtemp(prefix=".bottles-retro-unshared-", dir=archive_parent))
        except OSError as exc:
            host_only_path.unlink(missing_ok=True)
            results.append(("FAIL", "sentinel host non condivisa", f"impossibile crearla accanto all'archivio: {exc}"))
            return results
        unshared_name = unshared_path.name

        q = shlex.quote
        script_lines = [
            "set +e",
            f"marker={q(marker)}",
            f"host_only={q(host_only)}",
            f"unshared={q(str(unshared_path))}",
            "printf 'T_HOME=%s\\n' \"$HOME\"",
            "touch \"$HOME/$marker\" 2>/dev/null; printf 'T_HOME_TOUCH=%s\\n' \"$?\"",
            "[ -e \"$HOME/$host_only\" ]; printf 'T_HOST_HOME_VISIBLE=%s\\n' \"$?\"",
            "[ -e \"$unshared\" ]; printf 'T_UNSHARED_HOST_VISIBLE=%s\\n' \"$?\"",
            "[ -e \"$HOME/.ssh\" ]; printf 'T_SSH_VISIBLE=%s\\n' \"$?\"",
        ]

        for idx, p in enumerate(audit.rw):
            qp = q(p)
            script_lines += [
                f"[ -d {qp} ]; printf 'T_RW_{idx}_VISIBLE=%s\\n' \"$?\"",
                f"touch {qp}/\"$marker\" 2>/dev/null; printf 'T_RW_{idx}_WRITE=%s\\n' \"$?\"; rm -f {qp}/\"$marker\" 2>/dev/null",
            ]
        for idx, p in enumerate(audit.ro):
            qp = q(p)
            script_lines += [
                f"[ -d {qp} ]; printf 'T_RO_{idx}_VISIBLE=%s\\n' \"$?\"",
                f"touch {qp}/\"$marker\" 2>/dev/null; printf 'T_RO_{idx}_WRITE=%s\\n' \"$?\"; rm -f {qp}/\"$marker\" 2>/dev/null",
            ]

        script_lines += [
            "interfaces=\"$(ip -o link show 2>/dev/null | awk -F': ' '{print $2}' | sed 's/@.*//' | tr '\\n' ',' | sed 's/,$//')\"",
            "printf 'T_IFACES=%s\\n' \"$interfaces\"",
            "[ -n \"$WAYLAND_DISPLAY\" ] && [ -S \"$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY\" ]; printf 'T_WAYLAND=%s\\n' \"$?\"",
            "[ -n \"$DISPLAY\" ] && [ -d /tmp/.X11-unix ]; printf 'T_X11=%s\\n' \"$?\"",
            "([ -S \"$XDG_RUNTIME_DIR/pulse/native\" ] || [ -S \"$XDG_RUNTIME_DIR/pipewire-0\" ]); printf 'T_AUDIO=%s\\n' \"$?\"",
            "ls /dev/dri/renderD* >/dev/null 2>&1; printf 'T_GPU_NODES=%s\\n' \"$?\"",
            "if command -v vulkaninfo >/dev/null 2>&1; then vulkaninfo --summary >/tmp/bj-vulkan-test 2>&1; printf 'T_VULKAN=%s\\n' \"$?\"; rm -f /tmp/bj-vulkan-test; else printf 'T_VULKAN=127\\n'; fi",
            "if command -v gdbus >/dev/null 2>&1; then gdbus introspect --session --dest ca.desrt.dconf --object-path /ca/desrt/dconf/Writer/user >/dev/null 2>&1; printf 'T_DCONF=%s\\n' \"$?\"; else printf 'T_DCONF=127\\n'; fi",
            "exit",
        ]
        script = "\n".join(script_lines) + "\n"

        proc = run_cmd(["bubblejail", "run", "--debug-shell", self.instance], input_text=script, timeout=60)
        values: dict[str, str] = {}
        for line in proc.stdout.splitlines():
            if line.startswith("T_") and "=" in line:
                key, value = line.split("=", 1)
                values[key] = value.strip()

        host_marker = Path.home() / marker
        jail_marker = self.private_home / marker
        home_touch = values.get("T_HOME_TOUCH") == "0"
        isolated = home_touch and not host_marker.exists() and jail_marker.exists()
        results.append(("PASS" if isolated else "FAIL", "HOME privato", f"HOME={values.get('T_HOME','?')} host_visible={host_marker.exists()} jail_copy={jail_marker.exists()}"))
        host_hidden = values.get("T_HOST_HOME_VISIBLE") not in (None, "0")
        results.append(("PASS" if host_hidden else "FAIL", "HOME reale non visibile", f"marker host-only rc={values.get('T_HOST_HOME_VISIBLE','?')}"))
        unshared_hidden = values.get("T_UNSHARED_HOST_VISIBLE") not in (None, "0")
        results.append(("PASS" if unshared_hidden else "FAIL", "percorso host non-whitelist nascosto", f"sentinel={unshared_name} rc={values.get('T_UNSHARED_HOST_VISIBLE','?')}"))

        try:
            jail_marker.unlink(missing_ok=True)
            host_marker.unlink(missing_ok=True)
            host_only_path.unlink(missing_ok=True)
            unshared_path.rmdir()
        except Exception:
            pass

        def rc_result(key: str, label: str, expect_zero: bool = True, warn_missing: bool = False):
            raw = values.get(key)
            if raw is None:
                results.append(("FAIL", label, "risultato assente"))
                return
            if warn_missing and raw == "127":
                results.append(("WARN", label, "strumento di test non disponibile"))
                return
            ok = (raw == "0") if expect_zero else (raw != "0")
            results.append(("PASS" if ok else "FAIL", label, f"rc={raw}"))

        for idx, p in enumerate(audit.rw):
            rc_result(f"T_RW_{idx}_VISIBLE", f"RW visibile: {p}")
            rc_result(f"T_RW_{idx}_WRITE", f"RW scrivibile: {p}")
        for idx, p in enumerate(audit.ro):
            rc_result(f"T_RO_{idx}_VISIBLE", f"RO visibile: {p}")
            rc_result(f"T_RO_{idx}_WRITE", f"RO non scrivibile: {p}", expect_zero=False)

        rc_result("T_SSH_VISIBLE", "HOME privata non contiene .ssh host", expect_zero=False)
        ifaces = [x for x in values.get("T_IFACES", "").split(",") if x]
        net_ok = bool(ifaces) and all(x == "lo" for x in ifaces)
        results.append(("PASS" if net_ok else "FAIL", "rete base isolata", f"interfacce={ifaces or ['?']}"))
        rc_result("T_WAYLAND", "Wayland")
        rc_result("T_X11", "XWayland/X11")
        rc_result("T_AUDIO", "audio")
        rc_result("T_GPU_NODES", "GPU render nodes")
        rc_result("T_VULKAN", "Vulkan", warn_missing=True)
        rc_result("T_DCONF", "dconf D-Bus", warn_missing=True)

        if proc.returncode not in (0, None):
            results.append(("WARN", "debug shell", f"bubblejail rc={proc.returncode}"))
        return results

    def test_runtime_network(self) -> list[tuple[str, str, str]]:
        try:
            self.ensure_runtime_args_supported()
        except RuntimeError as exc:
            return [("FAIL", "rete temporanea", str(exc))]
        if self.running():
            return [("FAIL", "rete temporanea", "istanza già attiva")]
        if self.audit().network_persistent:
            return [("FAIL", "rete temporanea", "[network] è già persistente nel profilo")]
        args = ["bubblejail", "run", "--debug-bwrap-args", "share-net"]
        resolv = Path("/etc/resolv.conf")
        try:
            actual = resolv.resolve(strict=True)
        except OSError:
            actual = resolv
        if actual != resolv:
            args += ["--debug-bwrap-args", "ro-bind", str(actual), str(actual)]
        args += ["--debug-shell", self.instance]
        script = """
set +e
interfaces="$(ip -o link show 2>/dev/null | awk -F': ' '{print $2}' | sed 's/@.*//' | tr '\n' ',' | sed 's/,$//')"
printf 'N_IFACES=%s\n' "$interfaces"
if command -v curl >/dev/null 2>&1; then curl -I --max-time 5 https://example.com >/dev/null 2>&1; printf 'N_HTTP=%s\n' "$?"; else getent hosts example.com >/dev/null 2>&1; printf 'N_HTTP=%s\n' "$?"; fi
exit
"""
        proc = run_cmd(args, input_text=script, timeout=30)
        values = {}
        for line in proc.stdout.splitlines():
            if line.startswith("N_") and "=" in line:
                k, v = line.split("=", 1)
                values[k] = v.strip()
        ifaces = [x for x in values.get("N_IFACES", "").split(",") if x]
        iface_ok = any(x != "lo" for x in ifaces)
        http_ok = values.get("N_HTTP") == "0"
        return [
            ("PASS" if iface_ok else "FAIL", "share-net runtime", f"interfacce={ifaces or ['?']}"),
            ("PASS" if http_ok else "FAIL", "DNS/HTTP runtime", f"rc={values.get('N_HTTP','?')}"),
        ]
