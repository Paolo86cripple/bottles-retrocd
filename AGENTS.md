# Bottles RetroCD — Project Rules and Working Context

This file is the persistent project contract for humans and coding agents working on **Bottles RetroCD**. Read it before non-trivial work and keep it aligned with implementation, tests, packaging, release documentation and validated target behavior.

## Agent operating rules

- The user's interactive shell is **fish**. Any terminal command intended for the user to paste must use valid fish syntax by default. Use `set VAR value`, not Bash-style `VAR=value`. Use Bash/sh syntax only when explicitly requested or when editing/testing a script whose declared interpreter is Bash/sh.
- Treat `AGENTS.md` as the repository's persistent operational source of truth for durable project decisions, constraints, validation state, workflow, packaging and roadmap.
- Whenever a durable project instruction, architecture/security decision, release gate, validated behavior, packaging decision or roadmap decision is established, update `AGENTS.md` as part of the same repository work when access allows it.
- Keep implementation, tests, `AGENTS.md`, README/review/testing docs, packaging metadata and changelog mutually consistent. Investigate divergence rather than assuming one side is current.
- Do not copy hidden platform/system instructions into the repository. Record only user/project instructions and repository-relevant engineering context.
- Prefer focused changes over speculative refactors, especially near packaging/release.
- Once a security-sensitive runtime path is CI-green and target-validated, do not refactor it for aesthetics immediately before release. Defer low-value cleanup unless it fixes a concrete risk/regression.
- Never force-update `main` merely to simplify history.
- Do not merge packaging/release work merely because CI passes if required real-machine gates are still open.
- No automatic merge. Owner approval is required before merging packaging/release work.

## Mission and scope

Bottles RetroCD is a GTK4 controller for running **Windows retro PC games** with native Bottles inside the existing Bubblejail `Bottles` instance, with CDEmu/libMirage/UDisks2 integration for legacy optical media and a read-only Redump/TOSEC verification workflow.

In scope:

- Bottles/Wine execution inside Bubblejail;
- safe per-launch GPU selection and strict DRM/Vulkan node isolation;
- native Wayland plus explicit XWayland fallback;
- CDEmu/libMirage optical-media handling and verified UDisks2 RO mounts;
- safe multidisc/disc swapping;
- Redump/TOSEC verification and read-only protection scanning;
- standard gamepad support with exact-node isolation and runtime disconnect/reconnect;
- persistent configuration and diagnostics that positively prove sandbox behavior;
- Arch/CachyOS packaging of the validated application.

Out of scope unless a future concrete requirement changes the decision: DOS management (use DOSBox-Staging), ScummVM integration, console emulation, Steam management, or revival of a generic all-era PC Game Manager. Useful concepts carried from the retired manager are GPU selection, multidisc, Redump/TOSEC verification and persistent configuration.

## Preservation / compatibility philosophy

- Prefer original executables, original optical-media behavior and accurate compatibility/emulation over executable replacement.
- A No-CD/cracked executable must **not** become the normal solution to legacy copy-protection compatibility.
- Future legacy DRM work should reproduce obsolete optical-protection behavior as natively as practical through Wine/CDEmu/libMirage or dedicated compatible components.
- Study/reuse existing open-source projects where technically appropriate and license-compatible instead of reinventing solved components.
- Compatibility layers remain optional where possible and must not weaken Bubblejail merely for convenience.

## Release identity and current phase

- Stable app ID: `io.github.Paolo86cripple.BottlesRetroCD`.
- Stable release name/version: `Bottles RetroCD 0.4.0`.
- Runtime security/compatibility baseline merged by PR #3: `8c75163168164fef896041c6b1a62ddac19b3faf`; post-merge CI #339 SUCCESS.
- Final real-machine pre-packaging gate: PASS.
- Final PR #3 diff/security review: PASS; no runtime/security blocker found.
- Current work branch: `packaging/arch-cachyos-0.4.0`, created from the reviewed runtime merge commit.
- 0.4.0 runtime feature scope is frozen. Do not add runtime features before release.
- Full Arch/CachyOS package acceptance for `bottles-retrocd 0.4.0-2`: PASS.
- Final release review found one identity-only issue: the final wrapper inherited legacy base values `APP_ID=org.local.BottlesRetroCD`, `APP_NAME=Bottles Retro CD`, `VERSION=0.4.0-rc2` while package/Desktop/AppStream already used the stable identity.
- Identity-only fix commit: `122460692d0c19650d663a77288b1c489851cd44`. It changes only the final wrapper's published app ID/name/version; Bubblejail, GPU, optical, network, gamepad, verifier, archive and process-isolation logic are unchanged.
- Because installed payload changed after `0.4.0-2`, final package candidate is **`bottles-retrocd 0.4.0-3`**.
- Package source is pinned to the identity-fix commit above; `.SRCINFO` is tracked and synchronized with `PKGBUILD`.
- Narrow 0.4.0-3 target gate is OPEN: clean package build with 151/151 tests, install/upgrade, `pacman -Qkk`, visible stable GUI identity, and effective GTK application ID must pass before merge.
- The owner has authorized merge after this final review is clean and the narrow reopened target gate passes.

## Architectural baseline

- Reuse the existing Bubblejail instance named `Bottles`; do not create a second persistent instance.
- Bottles/Wine/runners/DXVK/runtimes/prefixes live in Bubblejail's private HOME.
- GTK controller, CDEmu/libMirage control/parsing, verifier and gamepad hotplug helpers are host-side as the logged-in user.
- Gamepad helpers may target only the active `Bottles` instance and validated controller device/sysfs references.
- Bubblejail is the security boundary for Bottles/Wine, not for host-side controller/verifier/CDEmu/libMirage/gamepad helpers.
- CDEmu is controlled through its D-Bus API model; `cdemu-client` is optional.
- UDisks2 mount state must be verified, not inferred from command success.
- Archive root is explicit persistent configuration; no release-time user-specific storage path may be hardcoded.
- Local-tree entrypoint remains `run-local.sh`; installed entrypoint is `/usr/bin/bottles-retrocd`, which delegates to `/usr/lib/bottles-retrocd/run-local.sh`.
- The final gamepad wrapper is the authoritative application entrypoint and publishes `io.github.Paolo86cripple.BottlesRetroCD`, `Bottles RetroCD`, `0.4.0`; legacy base constants are implementation details and must not leak into the released application identity.

## Security invariants

Security regressions are release blockers.

### Filesystem and archive

- Host HOME is hidden from Bottles/Wine except explicit approved shares.
- Host filesystem exposure is deny-by-default.
- Persistent shares use Bubblejail `root_share` with separate RO/RW paths; canonicalize and validate before writing.
- Explicit RO access to configured archive root/subdirectories is allowed; RW anywhere inside the archive is forbidden; archive ancestors are forbidden in both modes.
- Reject real HOME, `/`, broad system roots, unsafe overlaps, nested conflicting binds and canonicalized aliases violating the same policy.
- Selecting an archive never shares it automatically.
- Dynamic optical/cache filesystem mounts use `ro-bind`.
- Never expose broad `/run/media`, `/mnt` or storage roots just to make optical media work.
- Isolation tests must create real temporary host objects and prove them invisible; nonexistent paths are not proof.

### Persistent configuration

- Config path: `~/.config/bottles-retro-cd/` mode `0700`.
- Sensitive files such as `config.toml`/`disc-sets.toml`: `0600`.
- Schema 2 persists `gpu_pci`, `display_backend`, `archive_root`.
- Existing target installs may migrate historical archive path only if it exists; migration stores only the path and never moves/copies/renames/rewrites/touches archive data.
- New installs choose archive explicitly.
- Config writes remain syntax-safe/atomic where applicable; persist stable identifiers, not volatile kernel numbering.

### Network

- Bottles network OFF by default.
- Persistent `[network]` in Bubblejail config is forbidden and must fail validation.
- Network may be enabled only transiently for a selected launch.
- Do not make network persistent merely to download runners.
- Runner workflow: temporary network ON for download/install, fully close Bottles, reopen OFF and confirm persistence in private HOME.
- Verifier update networking is independent: HTTPS only to explicit official Redump/TOSEC hosts with redirect revalidation.

### Display / preferences

- Persistent display choices: Auto, native Wayland, XWayland.
- Auto is neutral; native Wayland only where supported by runner.
- XWayland is compatibility fallback and must not broaden filesystem/network/GPU/optical access.
- Forced XWayland requires existing Bubblejail `x11` + `wayland`; fail closed rather than adding permissions silently.
- Bottles global settings use `GSETTINGS_BACKEND=keyfile` inside private HOME, not host dconf.

### GPU

- Detect dynamically; persist stable PCI address, never `cardX` numbering.
- No implicit Mesa/default fallback when selected GPU cannot be proven.
- Validate PCI/vendor/device/driver plus DRM `cardN` and `renderD*`; selected paths must be live character devices.
- Apply Mesa GPU selection per launch; do not rewrite persistent Bubblejail policy merely to switch GPU.
- Mask broad `/dev/dri` and bind back only selected card/render nodes.
- Pre-launch proof: `DRI_PRIME`, selected nodes present, known non-selected nodes absent, exactly one Vulkan device, matching vendor/device identity.
- Post-launch proof attaches to already-running Bubblejail via supported `bubblejail run --wait <instance> ...` path and re-proves effective selected-node/Vulkan isolation.
- Missing proof markers are failure. Post-launch proof failure terminates the exact launch process group.
- Manual Test Vulkan uses the same strict validator.
- Do not hide additional GPU sysfs without concrete security value; avoid Mesa/udev compatibility regressions.

### Retro Optical / CDEmu

- Raw `/dev/srX` is optional/OFF by default; if exposed it must exactly match CDEmu mapping and Linux SCSI optical type 5.
- `/sys/class/block/srX/ro`/block-layer RO is diagnostic only; verified UDisks2 filesystem RO state is authoritative.
- `/dev/sgX` is broader SCSI access, explicit and OFF by default.
- CDEmu D-Bus and `/dev/vhba_ctl` stay hidden from Bottles/Wine.
- No broad storage-tree exposure for optical compatibility.
- Lifecycle detects effective VHBA provider, including CachyOS kernel-provided VHBA, and must not duplicate privileged/kernel infrastructure.
- During a live Bottles session, broad “eject all” operations are intentionally refused; use the validated active-device eject path.

### Standard gamepad / input

- Standard controller path uses Bubblejail `[joystick]`.
- Never expose all `/dev/input`, keyboard/mouse event nodes, or `/dev/hidraw*` for the 0.4.0 standard path.
- Switch/gyro/hidraw-dependent support is out of scope for 0.4.0 rather than a reason to weaken isolation.
- Host detection accepts supported `jsX` plus matching evdev `eventX`; node numbers may change across reconnect.
- Test gamepad proves exact host/jail agreement, readability, no unrelated input, no hidraw.
- Runtime fingerprint includes path/inode/rdev.
- Initial monitor activation preserves known-good static surface, reports `udev=initial-static`, and sends no unnecessary initial add event.
- Physical disconnect/reconnect reconciles exact current `jsX/eventX` plus minimal sysfs and sends synthetic libudev remove/add, reporting `udev=notified`.
- Every transition re-probes `sysfs=exact` and `hidraw=hidden`; ambiguity/failure is fail-closed with no permissive fallback.
- No sudo/root/additional groups/persistent udev permission changes/host capabilities for normal hotplug.
- Runtime hotplug routes through `gamepad_ns_entry.py`: `NS_GET_USERNS` finds mount-namespace owner; exact host objects are pinned; a private staging mount namespace is created; `(st_dev, st_ino, type, st_rdev)` is revalidated; detached exact mounts use `open_tree`; target mount/network namespaces are entered only after preparation. No PID namespace dependency.
- Some legacy games enumerate controllers only at startup; RetroCD proves Wine-visible transition but cannot force game-level runtime enumeration.

## Multidisc rules

- Archive fidelity is mandatory: never copy/rename/rewrite/modify/touch/symlink original CUE/BIN/images to create a set.
- Persistent sets reference original descriptors under configured archive; Disc 1 remains a valid explicit anchor.
- Filename grouping/autodetection is advisory only and never silently persisted as truth.
- Live multidisc requires an explicit saved set.
- Cache filesystems are UDisks2 RO and individually `ro-bind` exposed.
- Only active CDEmu `/dev/srX` may be exposed; cached drives and `/dev/sgX` must not leak.
- During swap neutralize `/mnt/cdemu` to a real empty private directory, keep same validated active `/dev/srX`, fail closed/rollback on mapping change.
- Revalidate cache device count/order/mapping before cleanup; refuse ambiguous removal during external CDEmu activity.
- Lock active drive/freeze set editing during live multidisc; poll Bottles exit and clean caches automatically; refuse normal GUI close while live Bottles depends on cache.
- Log cleanup start/completion/failure for live multidisc ownership and recovery diagnostics.
- Known residual: abnormal GUI/process kill may leave temporary cache drives; recovery is post-release and must not weaken ownership validation.

## Redump / TOSEC verifier rules

- Verifier is implemented and baseline; never mount/execute/rename/rewrite/move/copy/touch dump files.
- Resolve/canonicalize CUE/TOC below authorized archive; reject traversal, absolute POSIX, Windows drive-letter and UNC references; preserve filenames/structure.
- Hash CRC32/MD5/SHA1 in one streaming pass; stat before/after; cache identity includes device/inode/size/mtime/ctime under XDG cache; close SQLite explicitly.
- Parse Logiqx incrementally; preserve source/DAT/game/description/serial/version/protection metadata; ignore unusable ROM records.
- Build catalog in staging, run SQLite integrity checks, reject empty/unverifiable indexes.
- `MATCH 1:1` requires one complete unique game; partial is `MISMATCH`; equivalent complete records remain `AMBIGUOUS`.
- Official updater is HTTPS-only with explicit host allow-list, redirect revalidation, no embedded credentials; bound download/ZIP sizes/counts; reject traversal/symlinks; materialize only DAT/XML; stage/index before swap and rollback on any replacement failure.
- Manual DAT imports remain in a separate source namespace from official catalog updates.
- Protection scanner is read-only, bounded, keeps 64 MiB per-directory-extent limit, streams raw signatures with overlap, and remains heuristic evidence that never overrides cryptographic matching.

## Coding practices

- Prefer Python stdlib where practical.
- Application subprocesses use argv lists; no `os.system`, `shell=True`, `eval` or dynamic `exec` in app paths.
- Never interpolate user-controlled paths into unquoted shell commands.
- If a shell snippet is unavoidable for a test, quote paths correctly and keep it narrowly scoped.
- GTK widget access from workers is marshalled to GTK main thread.
- Bubblejail config writes are syntax-checked/backed up/atomic where applicable.
- Detect Bubblejail runtime capabilities before depending on them.
- Keep launch stdout/stderr in XDG cache/logs.
- Do not hardcode user HOME/storage paths.
- Favor fail-closed identity/mapping decisions; avoid hardening that creates substantial compatibility risk without concrete benefit.

## User-facing command examples

All interactive examples must paste cleanly into fish, e.g.:

```fish
set ARCHIVE "/path/to/archive"
find "$ARCHIVE" -type f
```

For environment overrides use fish-compatible forms such as:

```fish
env PYTHONWARNINGS='error::ResourceWarning' python -m unittest discover -s tests -v
```

Scripts keep their declared interpreter; Bash syntax is valid inside a Bash `PKGBUILD`, but user terminal instructions remain fish.

## 0.4.0 validation baseline

Automated/runtime baseline before packaging:

- 151 unit tests PASS;
- all application modules compile, including final GUI/gamepad namespace helpers;
- `ResourceWarning`-as-error PASS;
- shell syntax PASS;
- forbidden dynamic-execution scan PASS;
- PR #3 branch CI and post-merge `main` CI #339 green;
- final target security/compatibility gate PASS.

Target behavior validated before packaging included:

- both AMD GPUs with pre/post DRM/Vulkan proof;
- CDEmu/UDisks2 RO flow, optional exact raw `/dev/srX`, explicit `/dev/sgX`, multidisc cache/swap/cleanup;
- Discworld Noir three-disc set, verifier/source immutability, preference persistence, native Wayland/XWayland, `proton-cachyos-native` + D7VK;
- network OFF baseline + temporary-network runner persistence;
- Xbox One S exact static path and physical hotplug/reconnect;
- schema-2 archive persistence + `0700`/`0600` config permissions + identical pre/post archive metadata signatures;
- Test Bubblejail `PASS=17 FAIL=0 WARN=0` with real hidden sentinel;
- Test CD → Bubblejail PASS with SCSI optical type 5, verified RO mount, hidden real sentinels and cleanup.

## Full Arch/CachyOS package acceptance for 0.4.0-2 — PASS

Completed on target CachyOS on 2026-09-10.

- All declared package dependencies present.
- `makepkg --cleanbuild --syncdeps` completed successfully.
- Local packaging source hashes passed.
- `check()` executed **151/151 tests PASS**.
- `package()` and packaging issue checks completed successfully.
- Package metadata/file-list inspection PASS; payload only under expected `/usr` paths.
- Install script contains informational messages only and does not alter user state.
- Installed package integrity: **53 total files, 0 altered files**.
- Installed launcher resolved to `/usr/bin/bottles-retrocd` and successfully ran installed code under `/usr/lib/bottles-retrocd/`.
- Test Bubblejail from installed package: **PASS=17 FAIL=0 WARN=0**.
- Historical local package `bottles-retro-cd-gui 0.3.0-1` was removed cleanly with no package-file overlap beyond common system directories and no orphans; final metadata declares `conflicts`/`replaces`.
- Installed-package functional launch PASS using Discworld Noir Disc 1 with XWayland, network OFF, dedicated RX 9070 XT selected, two other GPUs hidden, GPU pre/post PASS, Retro Optical pre/post PASS, `/mnt/cdemu=RO`, CDEmu D-Bus/vhba/sg hidden, raw sr hidden by default, Xbox One S `event9 + js0`, `sysfs=exact`, `udev=initial-static`, `hidraw=hidden`.
- Live-session broad eject was correctly refused fail-closed; active device eject succeeded.
- Uninstall-preservation gate PASS: before/after comparison showed RetroCD config, Bubblejail instance/private HOME/prefix state and archive content unchanged after removing the package.
- `0.4.0-2` was reinstalled after the preservation test.

## Narrow final package gate for 0.4.0-3 — OPEN

The identity-only fix changes installed Python payload but no sandbox/device/security behavior, so only relevant validation is reopened:

- final branch CI must be green, including identity and `.SRCINFO` checks;
- target `makepkg --cleanbuild --syncdeps` must complete with **151/151 tests PASS**;
- install/upgrade the resulting `bottles-retrocd 0.4.0-3` package;
- `pacman -Qkk bottles-retrocd` must report no altered files;
- GUI/application must publish `Bottles RetroCD 0.4.0` and GTK application ID `io.github.Paolo86cripple.BottlesRetroCD`;
- if this narrow gate exposes an unrelated runtime/security regression, reopen the relevant broader gate; otherwise do not repeat the already-passed GPU/Retro Optical/Discworld/gamepad/uninstall-preservation suite.

## Deferred non-blocking cleanup

Do not touch these before 0.4.0 release unless a concrete regression appears:

1. `gamepad_ns_helper.py` still contains older direct CLI/`mutate_instance()` code; runtime hotplug uses `gamepad_ns_entry.py`. Old path failed closed and is not a permissive fallback.
2. CD-integration real-sentinel staging exists in both lifecycle and final wrapper layers; redundant but restrictive and target-tested.
3. After release, consider consolidating release identity constants into one shared module instead of overriding legacy base constants in the final wrapper. Do not refactor this immediately before 0.4.0 after the identity-only fix has passed its narrow gate.

## Arch / CachyOS packaging contract

Packaging layout:

- `packaging/arch/PKGBUILD` — package recipe;
- `packaging/arch/.SRCINFO` — generated package metadata, tracked and kept synchronized with `PKGBUILD`;
- `/usr/lib/bottles-retrocd/` — installed application Python modules and internal `run-local.sh`;
- `/usr/bin/bottles-retrocd` — tiny launcher only;
- `/usr/share/applications/io.github.Paolo86cripple.BottlesRetroCD.desktop` — desktop entry;
- `/usr/share/metainfo/io.github.Paolo86cripple.BottlesRetroCD.metainfo.xml` — AppStream metadata;
- `/usr/share/doc/bottles-retrocd/` and `/usr/share/licenses/bottles-retrocd/` — app-owned docs/license.

Packaging source policy:

- 0.4.0 security/compatibility baseline remains `8c75163168164fef896041c6b1a62ddac19b3faf`.
- Final packaged source is pinned to `122460692d0c19650d663a77288b1c489851cd44`, whose only runtime-code delta from the validated baseline is the final-wrapper application ID/name/version override described above; other intervening branch commits are packaging/CI/docs only.
- Do not move the source pin again without a concrete reviewed reason and corresponding relevant validation.
- Final candidate metadata is `pkgver=0.4.0`, `pkgrel=3`.
- `conflicts=('bottles-retro-cd-gui')` and `replaces=('bottles-retro-cd-gui')` are intentional migration metadata for the obsolete historical local package name.
- No files may be installed under `/home`, `/run`, `/mnt`, `/media`, `/dev`, `/sys`, or user config/data locations.
- Package install/remove scripts must never create/reset/delete Bubblejail instances, private HOME, prefixes, RetroCD config, archive, DAT catalog/cache or other user-owned content.
- Uninstall removes only package-owned files under `/usr`; user state is intentionally preserved.

Verified dependency policy:

- direct dependencies: `python`, `python-gobject`, `gtk4`, `bottles`, `bubblejail`, `cdemu-daemon`, `libmirage`, `udisks2`, `vulkan-tools`, `iproute2`, `util-linux`;
- on stock Arch, `bottles` and `bubblejail` are AUR packages;
- `lspci`/`pciutils` is optional diagnostic enrichment because GPU detection falls back safely to stable PCI identity when it is absent; it is not a hard runtime dependency;
- do **not** add direct dependency on `vhba-module` or `vhba-module-dkms`; CDEmu/distribution/kernel must satisfy effective `VHBA-MODULE`;
- do **not** add `cdemu-client` as hard dependency; RetroCD uses D-Bus directly;
- `sudo` is optional and only enables interactive Componenti full-system update;
- no separate/broad gamepad dependency or permissions layer beyond Bubblejail `[joystick]`.

Packaging validation requirements:

- CI validates runtime compile/tests plus `PKGBUILD`, `.install`, launcher syntax, desktop/metainfo, local hashes, final release identity and `.SRCINFO` metadata;
- full target package build/file-list/installed/security/compatibility/uninstall-preservation acceptance is PASS for 0.4.0-2;
- identity-only payload change to 0.4.0-3 reopened only the narrow gate documented above;
- after any package-metadata change, regenerate `.SRCINFO` with `makepkg --printsrcinfo > .SRCINFO` and rerun CI;
- merge packaging branch only after final review, narrow 0.4.0-3 target gate PASS and owner approval;
- after merge, verify `main` CI before creating the 0.4.0 tag/release.

## Git / release workflow

- `main` remains tested integration branch.
- Non-trivial work belongs on focused branches such as `packaging/arch-cachyos-0.4.0`.
- Keep commits focused; compare branch with `main` before merge; no force-updates.
- Do not commit generated `src/`, `pkg/`, built package archives, caches, private instance state, mounted media, DAT downloads or user-specific paths.
- The packaging branch remains based on runtime merge commit `8c751631...`; the only allowed runtime-code delta before release is the reviewed identity-only fix at `122460692...`.
- Current release flow: final CI → narrow 0.4.0-3 target gate → authorized merge → `main` CI → tag/release 0.4.0.

## Post-release roadmap, agreed order

1. **Native legacy optical DRM compatibility/emulation** — investigate SafeDisc, SecuROM, LaserLock, StarForce and other Windows 9x/XP optical protections; reproduce original verification behavior via Wine/CDEmu/libMirage or compatible components; reuse license-compatible open source; No-CD/cracks are not the normal solution; keep optional/fail-closed without broader sandbox permissions.
2. **Legacy DirectX compatibility layer/manager** — DxWrapper/dgVoodoo2-style DirectX 5–9 support, optional/OFF by default, after DRM work and before shaders.
3. **libRashader + Slang shaders** — optional/OFF by default per game/bottle after compatibility foundation is stable.
4. **Abnormal-termination recovery for live multidisc cache devices** — safe recovery without weakening ownership validation.

None of these may weaken the validated Bubblejail boundary or become mandatory without a concrete reviewed reason.

## Documentation references

Keep aligned: `README.md`, `README-TESTING.md`, `REVIEW.md`, `docs/SECURITY-REVIEW.md`, `docs/TESTING.md`, `docs/ROADMAP.md`, `CHANGELOG.md`, and `packaging/arch/README.md`.
