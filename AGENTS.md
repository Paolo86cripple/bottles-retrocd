# Bottles RetroCD — Project Rules and Working Context

This file is the persistent project contract for humans and coding agents working on **Bottles RetroCD**. Read it before non-trivial work and keep it aligned with implementation, tests, release documentation and validated target behavior.

## Agent operating rules

- The user's interactive shell is **fish**. Any terminal command intended for the user to paste must use valid fish syntax by default. Do not give Bash-style assignments such as `VAR=value`; use `set VAR value`. Use Bash/sh syntax only when explicitly requested or when editing/explaining a script whose interpreter is Bash/sh.
- Treat `AGENTS.md` as the repository's persistent operational source of truth for durable project decisions, constraints, validation state, workflow and roadmap.
- Whenever a durable project instruction, architectural decision, security invariant, release gate, validated behavior or roadmap decision is established, update `AGENTS.md` as part of the same repository work when access allows it.
- Keep implementation, tests, `AGENTS.md`, README/review/testing documentation and changelog mutually consistent. Investigate divergence rather than assuming one side is current.
- Do not copy hidden platform/system instructions into the repository. Record only user/project instructions and repository-relevant engineering context.
- Prefer focused changes over speculative refactors, especially near packaging/release.
- Do not merge merely because CI passes if a required real-machine gate is open.
- Conversely, once a security-sensitive runtime path is CI-green and target-validated, do not refactor it for aesthetics immediately before release. Defer low-value cleanup unless it fixes a concrete risk or regression.
- Never force-update `main` merely to simplify history.

## Mission and scope

Bottles RetroCD is a GTK4 controller for running **Windows retro PC games** with native Bottles inside the existing Bubblejail `Bottles` instance, with CDEmu/libMirage/UDisks2 integration for legacy optical media and a read-only Redump/TOSEC verification workflow.

The project is intentionally focused on Windows retro PC games.

In scope:

- Bottles/Wine execution inside Bubblejail;
- safe per-launch GPU selection and strict DRM/Vulkan node isolation;
- native Wayland plus explicit XWayland compatibility fallback;
- CDEmu/libMirage optical-media handling;
- verified UDisks2 read-only mounts;
- safe multidisc/disc swapping;
- Redump/TOSEC verification and read-only protection scanning;
- standard gamepad support with exact-node isolation and runtime disconnect/reconnect;
- persistent configuration;
- diagnostics that positively prove sandbox behavior.

Out of scope for the current architecture unless a future concrete requirement changes the decision:

- DOS management: use DOSBox-Staging;
- ScummVM integration;
- console emulation;
- Steam management;
- a generic all-era PC Game Manager.

The retired PC Game Manager architecture is not to be revived. Useful concepts carried into Bottles RetroCD are GPU selection, multidisc management, Redump/TOSEC verification and persistent configuration.

## Preservation / compatibility philosophy

- Prefer original executables, original optical-media behavior and accurate compatibility/emulation over executable replacement.
- A No-CD/cracked executable must **not** become the normal solution to legacy copy-protection compatibility.
- Future legacy DRM work should reproduce or bypass obsolete optical-protection behavior as natively as practical through Wine/CDEmu/libMirage or dedicated compatible components.
- Study and reuse existing open-source projects where technically appropriate and license-compatible instead of reinventing solved components.
- Compatibility layers remain optional where possible and must not weaken Bubblejail merely for convenience.

## Release identity and current phase

- Stable application ID: `io.github.Paolo86cripple.BottlesRetroCD`.
- Release candidate/version: `0.4.0`.
- PR #3: `Prepare Bottles RetroCD 0.4.0 for packaging`.
- Review branch: `review/pre-packaging-cleanup`.
- 0.4.0 feature scope is frozen.
- **Final real-machine pre-packaging gate: PASS.**
- **Final PR diff/security review: PASS; no runtime/security blocker found.**
- Immediate next step after owner-approved PR merge: **Arch/CachyOS packaging**.
- Do not add new features before packaging.

## Architectural baseline

- Reuse the existing Bubblejail instance named `Bottles`; do not create a second persistent instance.
- Bottles, Wine, runners, DXVK, runtimes and prefixes live in Bubblejail's private HOME.
- The GTK controller runs host-side as the logged-in user.
- CDEmu/libMirage image parsing and control are host-side.
- Redump/TOSEC DAT parsing, hashing and protection scanning are host-side.
- Gamepad hotplug monitor/helpers are host-side as the logged-in user but may target only the active `Bottles` instance and validated controller device/sysfs references.
- Bubblejail is the security boundary for Bottles/Wine, not for the controller/verifier/CDEmu/libMirage/gamepad helpers.
- CDEmu is controlled through its D-Bus API model; `cdemu-client` is optional.
- UDisks2 mount state must be verified, not inferred from command success.
- The archive root is explicit persistent configuration; no release-time user-specific storage path may be hardcoded.
- `run-local.sh` launches the final `bottles-retro-cd-gui-gamepad.py` wrapper.

## Security invariants

Security regressions are release blockers.

### Filesystem and archive

- Host HOME must remain hidden from Bottles/Wine except for explicit approved shares.
- Host filesystem exposure is deny-by-default.
- Persistent shares use Bubblejail `root_share` with separate RO and RW paths.
- Canonicalize and validate whitelist paths before writing.
- Explicit RO access to the configured archive root and its subdirectories is allowed.
- RW access to the archive root or anything below it is forbidden.
- Ancestors of the archive are forbidden in both RO and RW modes.
- Reject real HOME, `/`, broad system roots, unsafe overlaps, nested conflicting binds and canonicalized aliases that violate the same policy.
- Selecting an archive does not automatically expose it to the jail.
- Dynamic optical/cache filesystem mounts into the jail use `ro-bind`.
- Never expose broad `/run/media`, `/mnt` or storage-root trees just to make optical media work.
- Isolation tests must create real temporary host objects and prove they are invisible. A path that merely does not exist is not isolation evidence.

### Persistent configuration

- Application config: `~/.config/bottles-retro-cd/`.
- Config directory mode: `0700`.
- Sensitive files such as `config.toml` and `disc-sets.toml`: `0600`.
- Schema 2 persists `gpu_pci`, `display_backend` and `archive_root`.
- Existing target installs may migrate the historical `/run/media/<user>/Data/Downloads/retropc` archive only when it exists.
- Migration stores only the path; never move, copy, rename, rewrite or touch archive data.
- New installations must choose an archive explicitly.
- Config writes must be syntax-safe/atomic where applicable.
- Persist stable identifiers and user intent, not volatile kernel numbering.

### Network

- Bottles networking is OFF by default.
- Persistent `[network]` in Bubblejail `services.toml` is forbidden and must fail validation.
- Network may be enabled only transiently for the selected launch.
- Do not make network persistent merely to download runners.
- Runner workflow: temporary network ON for download/install, fully close Bottles, reopen network OFF and confirm the runner persists in private HOME.
- Verifier DAT networking is independent and narrower: HTTPS only to explicit official Redump/TOSEC hosts with redirect revalidation.

### Display / preferences

- Persistent display choices: `Auto`, native Wayland, XWayland.
- Auto is neutral and does not force a Wine display backend.
- Native Wayland is used only where supported by the selected runner.
- XWayland is a compatibility fallback and must not require broader filesystem/network/GPU/optical permissions.
- Forced XWayland requires the existing Bubblejail `x11` and `wayland` services; fail closed rather than silently adding permissions.
- Bottles global preferences use `GSETTINGS_BACKEND=keyfile` so settings persist inside Bubblejail's private HOME rather than writing host dconf.

### GPU

- Detect GPUs dynamically.
- Persist GPU identity by stable PCI address, never `cardX` numbering.
- The explicitly selected GPU is authoritative for access control.
- No implicit Mesa/default-GPU fallback is allowed if a valid selected GPU cannot be proven.
- Validate selected PCI address, 4-digit vendor/device IDs, kernel driver, DRM `cardN` and `renderD*` names.
- Require selected DRM paths to be live character devices.
- Apply Mesa GPU selection per launch; do not rewrite persistent Bubblejail policy just to switch GPU.
- Bubblejail's broad `/dev/dri` view is too permissive for strict multi-GPU isolation: mask `/dev/dri` and bind back only the selected card/render nodes.
- Every normal launch requires a fail-closed pre-launch GPU proof: `DRI_PRIME`, selected nodes present, known non-selected nodes absent, exactly one Vulkan device, matching vendor/device identity.
- Every normal launch also requires a post-launch proof against the already-running Bubblejail instance using the supported helper path (`bubblejail run --wait <instance> ...`).
- Post-launch proof revalidates effective selected-node/non-selected-node/Vulkan identity. It need not require a fresh helper process to inherit `DRI_PRIME`.
- Missing success markers are failure; absence of explicit failure is not enough.
- If post-launch helper injection/output/proof fails, terminate the exact launch process group and report launch failure.
- Manual Test Vulkan uses the same strict pre-launch validator.
- Do not hide additional GPU sysfs merely for aesthetics; avoid Mesa/udev compatibility risk unless there is a concrete threat.

### Retro Optical / CDEmu

- Raw `/dev/srX` exposure is optional and OFF by default.
- If exposed, it must be the exact CDEmu mapping and a real Linux SCSI optical block device, peripheral type 5.
- `/sys/class/block/srX/ro` / block-layer RO is diagnostic only. VHBA/CDEmu may report RW even while the filesystem is safely mounted RO.
- The verified UDisks2 filesystem mount is authoritative for read-only policy.
- `/dev/sgX` is broader SCSI access, explicit and OFF by default.
- CDEmu D-Bus and `/dev/vhba_ctl` must remain hidden from Bottles/Wine.
- No broad storage-tree exposure to support optical media.
- Lifecycle logic must detect the effective VHBA provider, including a provider bundled by the CachyOS kernel, and must not duplicate privileged/kernel infrastructure unnecessarily.

### Standard gamepad / input

- Standard gamepad support uses Bubblejail `[joystick]`.
- Never expose all `/dev/input` merely to make a controller work.
- Never expose keyboard or mouse event nodes as part of gamepad support.
- `/dev/hidraw*` remains hidden for the 0.4.0 standard-controller path.
- Switch/gyro/hidraw-dependent support is out of scope for 0.4.0 rather than a reason to weaken isolation.
- Host detection accepts supported `jsX` plus matching evdev `eventX` sibling(s).
- Node numbers are not contractual and may change across reconnect.
- Test gamepad must prove exact host/jail node agreement, readability, no unrelated input nodes and no hidraw.
- Runtime fingerprinting includes path/inode/rdev so disappearance/path reuse is detected.
- Initial monitor activation must preserve the already-known-good static Bubblejail joystick surface and report `udev=initial-static`; do not synthesize an unnecessary initial add notification.
- Physical disconnect/reconnect must reconcile only the exact current `jsX/eventX` nodes plus matching minimal sysfs and emit matching synthetic libudev remove/add notifications, reporting `udev=notified`.
- Every successful transition must re-probe `sysfs=exact` and `hidraw=hidden`.
- Namespace/sysfs/udev/isolation ambiguity is failure. Do not add a permissive fallback.
- No sudo/root/additional groups/persistent host udev permission changes/capabilities are allowed for the normal hotplug path.
- Runtime hotplug routes through `gamepad_ns_entry.py`.
- `gamepad_ns_entry.py` uses `NS_GET_USERNS` to discover the user namespace owning the Bubblejail mount namespace, pins exact host objects, enters that owner user namespace, creates a private staging mount namespace, reopens/revalidates identity `(st_dev, st_ino, file type, st_rdev)`, creates detached exact mounts with `open_tree`, then enters the target mount/network namespaces and applies the mutation fail-closed.
- No PID namespace dependency.
- Some legacy games enumerate controllers only at startup; RetroCD can prove the Wine-visible device/sysfs/udev transition but cannot force application-level runtime enumeration.

## Multidisc rules

Archive fidelity is mandatory.

- Persistent disc sets reference original descriptors under the configured archive root.
- Never copy, rename, rewrite, modify, touch or symlink original CUE/BIN/image files to create a set.
- Creating an explicit set starts from the exact selected descriptor; Disc 1 must remain a valid anchor.
- Filename grouping/autodetection is advisory only and must not silently become persisted truth.
- Live multidisc requires an explicit saved set.
- Cache filesystems are mounted RO with UDisks2 and individually exposed with `ro-bind`.
- Only the active CDEmu `/dev/srX` may be exposed for live swapping; cached drives and `/dev/sgX` must not leak into the jail.
- During swap, neutralize `/mnt/cdemu` to a real empty private directory before changing media.
- Swap on the same validated active `/dev/srX`; mapping changes fail closed and trigger rollback.
- Revalidate cache device count/order/mapping before cleanup/removal.
- Do not remove drives if external CDEmu activity makes ownership ambiguous.
- While live multidisc is active, lock the selected CDEmu drive and freeze set editing.
- Poll Bottles exit and clean caches automatically.
- Refuse normal GUI close while live Bottles still depends on multidisc cache.
- Log cleanup start/completion/failure.
- Known residual: abnormal GUI/process kill may leave temporary cache drives. Recovery is post-release work; do not weaken ownership validation to solve it.

## Redump / TOSEC verifier rules

The verifier is implemented and part of the baseline.

### Archive integrity

- Verification must never mount, execute, rename, rewrite, move, copy or touch dump files.
- CUE/TOC references are resolved/canonicalized below the authorised archive root.
- Reject traversal, absolute POSIX paths, Windows drive-letter paths and UNC references.
- Preserve Redump/TOSEC filenames and directory structure.
- Verification/local DAT import tests must be able to prove source content and `mtime_ns` unchanged.

### Hashing/cache

- Calculate CRC32, MD5 and SHA-1 in one streaming pass.
- Stat before and after hashing and fail if the file changed.
- Cache identity/state includes device/inode/size/mtime/ctime.
- Keep hash cache outside the archive under XDG cache storage.
- Explicitly close SQLite connections; `ResourceWarning` is a CI failure.

### DAT catalog/updater

- Parse Logiqx XML incrementally; do not load large DATs as one DOM.
- Preserve source/DAT/game/description/serial/version/protection metadata where present.
- Ignore ROM entries that have neither usable size nor digest material.
- Build catalog replacements in staging, run SQLite integrity checks and reject empty/unverifiable indexes.
- `MATCH 1:1` requires all local payloads to match exactly one complete DAT game record.
- Partial matches are `MISMATCH`.
- Multiple complete equivalent records are `AMBIGUOUS`; never silently prefer Redump or TOSEC.
- Official updater: HTTPS only, explicit official host allow-list, redirect revalidation, no embedded credentials.
- Bound streamed download size, ZIP member count, per-member size and total unpacked size.
- Reject ZIP traversal and symlinks.
- Materialize only DAT/XML metadata.
- Fully stage/index before moving live data.
- Roll back the previous generation if any live replacement step fails, including injected `os.replace()` failure.
- Keep manual DAT imports in a separate source namespace.

### Protection scanner

- Scanner is read-only and never mounts/executes images.
- Bound ISO/Joliet depth, entries, directory extent size and file samples.
- Keep the existing 64 MiB per-directory-extent hard limit; malformed larger extents fail closed.
- Raw signature scanning is streaming and handles cross-chunk matches.
- Scanner evidence is heuristic metadata only and never overrides cryptographic DAT matching.

## Coding practices

- Prefer Python standard-library solutions when practical.
- Subprocess application paths use argv lists.
- Do not use `os.system`, `shell=True`, `eval` or dynamic `exec` in application paths.
- Never interpolate user-controlled filesystem paths into an unquoted shell command.
- If a shell snippet is unavoidable for a test, quote paths correctly and keep it narrowly scoped.
- GTK widget access from background work must be marshalled to the GTK main thread.
- Configuration writes must be syntax-checked where applicable, backed up when modifying Bubblejail config and replaced atomically.
- Detect Bubblejail runtime-argument capabilities before depending on them.
- Keep launch stdout/stderr in XDG cache/log storage for diagnostics.
- Do not hardcode a specific user's HOME/storage path.
- Favor fail-closed behavior when security-sensitive identity/mapping checks are ambiguous.
- Avoid hardening that creates substantial compatibility risk without concrete security benefit.
- Preserve reviewed security-sensitive code near release; add focused modules/wrappers rather than expanding monoliths where practical.

## User-facing command examples

All interactive examples must paste cleanly into fish. Example:

```fish
set ARCHIVE "/path/to/archive"
find "$ARCHIVE" -type f
```

For one-command environment overrides use fish-compatible forms such as:

```fish
env PYTHONWARNINGS='error::ResourceWarning' python -m unittest discover -s tests -v
```

Do not give Bash-only `VAR=value command` or standalone `VAR=value` examples as user terminal instructions.

Scripts keep their declared interpreter. A command such as `bash -n run-local.sh` is valid to invoke from fish when explicitly testing a Bash script.

## 0.4.0 validation baseline

Automated baseline:

- **151 unit tests PASS**;
- Python compilation for all application modules including final GUI wrapper, hotplug monitor, namespace entry and mount/udev helper;
- `ResourceWarning`-as-error PASS;
- `run-local.sh` shell syntax PASS;
- forbidden unsafe dynamic-execution scan PASS;
- CI remained green through the code-changing candidate; final documentation-only commits must also remain green before merge.

Target-machine baseline includes:

- both AMD GPU paths with pre/post DRM/Vulkan proof;
- CDEmu/UDisks2 RO optical flow, optional exact raw `/dev/srX`, explicit `/dev/sgX`, multidisc cache/swap/cleanup;
- Discworld Noir three-disc Redump set;
- verifier/source immutability;
- Bottles preference persistence with GSettings keyfile;
- native Wayland and XWayland;
- `proton-cachyos-native` + D7VK Discworld Noir;
- network OFF baseline and temporary-network runner persistence;
- Xbox One S static exact-node path and physical hotplug/reconnect;
- schema-2 archive root persistence and private config permissions;
- resize + vertical scrolling on all notebook pages;
- real non-whitelist sentinel isolation.

### Final target gate completed 2026-09-10

- Archive config: schema 2, expected archive root, config modes `0700`/`0600` — PASS.
- GUI archive re-selection persisted after full restart — PASS.
- Pre/post archive metadata signatures identical — PASS.
- Resize + scroll across all notebook pages — PASS.
- Test Bubblejail — **PASS=17 FAIL=0 WARN=0**; private HOME, host HOME/`.ssh` hidden, real adjacent sentinel hidden, RW/RO semantics correct, only `lo` with network OFF, display/audio/GPU/Vulkan/dconf surfaces as intended.
- Test CD → Bubblejail — PASS; temporary `/dev/sr1` SCSI optical type 5, host mount RO, two real integration sentinels hidden, `/mnt/cdemu` visible/read-only, cleanup PASS.
- Final Discworld Noir XWayland launch — PASS; GPU pre/post PASS, Retro Optical pre/post PASS with `/mnt/cdemu=RO`, network OFF, game launched correctly with known-good fullscreen/audio behavior.
- Final gamepad initial proof during that launch — PASS; Xbox One S `event9 + js0`, writable, `sysfs=exact`, `udev=initial-static`, `hidraw=hidden`.

The final real-machine pre-packaging gate is therefore **CLOSED/PASS**.

## Final PR #3 review conclusion

Final diff/security review found **no release-blocking runtime issue**.

Two non-blocking maintenance items are explicitly deferred until after 0.4.0:

1. `gamepad_ns_helper.py` still contains the older direct CLI/`mutate_instance()` path. Runtime hotplug does not use it; `gamepad_hotplug.py` routes through `gamepad_ns_entry.py`. The old path failed closed on target and is not a permissive fallback. Do not refactor it before packaging merely for cleanup.
2. CD integration real-sentinel staging is present in both lifecycle and final wrapper layers, causing redundant temporary staging. Both are restrictive and the real test passes. Consolidate post-release if desired; do not touch the validated runtime for aesthetics now.

The gamepad implementation is frozen for 0.4.0 unless a new concrete regression is discovered.

## Packaging requirements

When packaging begins:

- Package stable app ID `io.github.Paolo86cripple.BottlesRetroCD` version `0.4.0`.
- Install/remove only application-owned files.
- Normal uninstall must preserve user config, Bubblejail instance/private HOME/prefixes, archive data, DAT/catalog/cache policy data and other user-owned content.
- Do not add `cdemu-client` as a hard runtime dependency; RetroCD uses CDEmu D-Bus.
- UDisks2/`udisksctl` is required for verified RO mounts/live multidisc.
- Use host CDEmu/libMirage and the effective VHBA provider; do not duplicate kernel infrastructure already supplied by CachyOS.
- Do not add a broad separate gamepad package/permission layer beyond the reviewed `[joystick]` path.
- Runtime dependency set must be verified against current Arch/CachyOS package names at packaging time rather than guessed from stale knowledge.
- Provide desktop integration appropriate to Arch/CachyOS packaging.
- After package creation, perform installed-package acceptance tests before tag/release.
- Package removal must not erase configuration or game/archive data.

## Git / release workflow

- `main` is the integration branch and should remain tested/usable.
- Non-trivial work belongs on focused feature/review branches.
- Keep commits focused/descriptive.
- Run static/unit checks before committing and target integration checks before declaring security-sensitive work complete.
- Compare branch against `main` before merge and confirm only intended files changed.
- Prefer a clean reviewed merge; never force-update `main` for convenience.
- Do not commit generated caches, local machine state, private Bottles prefixes, mounted media, DAT downloads or user-specific absolute paths.
- PR #3 technical gate is satisfied; **do not merge automatically**. Merge only after final docs-only CI is green and the repository owner explicitly instructs/approves the merge.
- After merge, verify remote `main`, then begin packaging.
- Tag/release only after package-installed acceptance and release hardening.

## Post-release roadmap, agreed order

After packaging, installed-package acceptance and release hardening:

1. **Native legacy optical DRM compatibility/emulation** — first post-release compatibility objective. Investigate SafeDisc, SecuROM, LaserLock, StarForce and other relevant Windows 9x/XP optical protections. Reproduce original disc-verification behavior as natively as practical through Wine/CDEmu/libMirage or dedicated compatible components. Study/reuse existing open-source projects where technically appropriate and license-compatible. No-CD/cracked executables are not the normal solution. Keep backends optional/fail-closed and do not broaden Bubblejail/optical permissions merely to make them work.
2. **Legacy DirectX compatibility layer/manager** — DxWrapper/dgVoodoo2-style support for DirectX 5–9-era games, optional and OFF by default, after the DRM objective above and before shader work.
3. **libRashader + Slang shaders** — optional, OFF by default, per game/bottle, after the compatibility foundation is stable.
4. **Abnormal-termination recovery for live multidisc cache devices** — safe recovery without weakening device ownership validation.

None of these post-release features may weaken the validated Bubblejail boundary or become mandatory for ordinary launch paths without a concrete reviewed reason.

## Documentation references

Keep these aligned with this contract:

- `README.md`
- `README-TESTING.md`
- `REVIEW.md`
- `docs/SECURITY-REVIEW.md`
- `docs/TESTING.md`
- `docs/ROADMAP.md`
- `CHANGELOG.md`

When documentation and implementation diverge, investigate and update both; do not silently assume either is current.
