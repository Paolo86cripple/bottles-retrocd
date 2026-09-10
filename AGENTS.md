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
- Do not merge packaging/release work merely because CI passes if required real-machine package acceptance is still open.

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
- Future legacy DRM work should reproduce/bypass obsolete optical-protection behavior as natively as practical through Wine/CDEmu/libMirage or dedicated compatible components.
- Study/reuse existing open-source projects where technically appropriate and license-compatible instead of reinventing solved components.
- Compatibility layers remain optional where possible and must not weaken Bubblejail merely for convenience.

## Release identity and current phase

- Stable app ID: `io.github.Paolo86cripple.BottlesRetroCD`.
- Version: `0.4.0`.
- PR #3 pre-packaging review was merged into `main` as `8c75163168164fef896041c6b1a62ddac19b3faf`.
- Post-merge CI #339: SUCCESS.
- Final real-machine pre-packaging gate: PASS.
- Final PR #3 diff/security review: PASS; no runtime/security blocker found.
- Current work branch: `packaging/arch-cachyos-0.4.0`, created from the reviewed merge commit.
- Current packaging skeleton commit: `a888d7e59a6eca0fab67841045675d81ed1fea63`; packaging-metadata CI hardening follows on the same branch.
- 0.4.0 runtime feature scope is frozen. Do not add new runtime features before package acceptance/release.

## Architectural baseline

- Reuse the existing Bubblejail instance named `Bottles`; do not create a second persistent instance.
- Bottles/Wine/runners/DXVK/runtimes/prefixes live in Bubblejail's private HOME.
- GTK controller, CDEmu/libMirage control/parsing, verifier and gamepad hotplug helpers are host-side as the logged-in user.
- Gamepad helpers may target only the active `Bottles` instance and validated controller device/sysfs references.
- Bubblejail is the security boundary for Bottles/Wine, not for host-side controller/verifier/CDEmu/libMirage/gamepad helpers.
- CDEmu is controlled through its D-Bus API model; `cdemu-client` is optional.
- UDisks2 mount state must be verified, not inferred from command success.
- Archive root is explicit persistent configuration; no release-time user-specific storage path may be hardcoded.
- Local-tree entrypoint is `run-local.sh`, which launches `bottles-retro-cd-gui-gamepad.py`.

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
- Existing target installs may migrate historical `/run/media/<user>/Data/Downloads/retropc` only if it exists; migration stores only the path and never moves/copies/renames/rewrites/touches archive data.
- New installs choose archive explicitly.
- Config writes remain syntax-safe/atomic where applicable; persist stable identifiers, not volatile kernel numbering.

### Network

- Bottles network OFF by default.
- Persistent `[network]` in Bubblejail config is forbidden.
- Network may be enabled only transiently for a selected launch.
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
- Known residual: abnormal GUI/process kill may leave temporary cache drives; recovery is post-release and must not weaken ownership validation.

## Redump / TOSEC verifier rules

- Verifier is implemented and baseline; never mount/execute/rename/rewrite/move/copy/touch dump files.
- Resolve/canonicalize CUE/TOC below authorized archive; reject traversal, absolute POSIX, Windows drive-letter and UNC references; preserve filenames/structure.
- Hash CRC32/MD5/SHA1 in one streaming pass; stat before/after; cache identity includes device/inode/size/mtime/ctime under XDG cache; close SQLite explicitly.
- Parse Logiqx incrementally; preserve source/DAT/game/description/serial/version/protection metadata; ignore unusable ROM records.
- Build catalog in staging, run SQLite integrity checks, reject empty/unverifiable indexes.
- `MATCH 1:1` requires one complete unique game; partial is `MISMATCH`; equivalent complete records remain `AMBIGUOUS`.
- Official updater is HTTPS-only with explicit host allow-list, redirect revalidation, no embedded credentials; bound download/ZIP sizes/counts; reject traversal/symlinks; materialize only DAT/XML; stage/index before swap and rollback on any replacement failure.
- Protection scanner is read-only, bounded, keeps 64 MiB per-directory-extent limit, streams raw signatures with overlap, and remains heuristic evidence that never overrides cryptographic matching.

## Coding practices

- Prefer Python stdlib where practical.
- Application subprocesses use argv lists; no `os.system`, `shell=True`, `eval` or dynamic `exec` in app paths.
- Never interpolate user-controlled paths into unquoted shell commands.
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

Automated baseline before packaging:

- 151 unit tests PASS;
- all application modules compile, including final GUI/gamepad namespace helpers;
- `ResourceWarning`-as-error PASS;
- shell syntax PASS;
- forbidden dynamic-execution scan PASS;
- PR #3 branch CI and post-merge `main` CI #339 green.

Target baseline completed 2026-09-10:

- both AMD GPUs with pre/post DRM/Vulkan proof;
- CDEmu/UDisks2 RO flow, optional exact raw `/dev/srX`, explicit `/dev/sgX`, multidisc cache/swap/cleanup;
- Discworld Noir three-disc set, verifier/source immutability, preference persistence, native Wayland/XWayland, `proton-cachyos-native` + D7VK;
- network OFF baseline + temporary-network runner persistence;
- Xbox One S exact static path and physical hotplug/reconnect;
- schema-2 archive persistence + `0700`/`0600` config permissions + identical pre/post archive metadata signatures;
- resize/vertical scroll all pages;
- Test Bubblejail `PASS=17 FAIL=0 WARN=0` with real hidden sentinel;
- Test CD → Bubblejail PASS with SCSI optical type 5, verified RO mount, two hidden real sentinels and cleanup;
- final Discworld Noir XWayland launch PASS with GPU pre/post, Retro Optical pre/post `/mnt/cdemu=RO`, network OFF, game start/fullscreen/audio;
- final gamepad initial proof `event9 + js0`, writable, `sysfs=exact`, `udev=initial-static`, `hidraw=hidden`.

## Deferred non-blocking cleanup

Do not touch these before 0.4.0 package acceptance unless a concrete regression appears:

1. `gamepad_ns_helper.py` still contains older direct CLI/`mutate_instance()` code; runtime hotplug uses `gamepad_ns_entry.py`. Old path failed closed and is not a permissive fallback.
2. CD-integration real-sentinel staging exists in both lifecycle and final wrapper layers; redundant but restrictive and target-tested.

## Arch / CachyOS packaging contract

Current packaging branch: `packaging/arch-cachyos-0.4.0`.

Packaging layout:

- `packaging/arch/PKGBUILD` — package recipe;
- `/usr/lib/bottles-retrocd/` — installed application Python modules and internal `run-local.sh`;
- `/usr/bin/bottles-retrocd` — tiny launcher only;
- `/usr/share/applications/io.github.Paolo86cripple.BottlesRetroCD.desktop` — desktop entry;
- `/usr/share/metainfo/io.github.Paolo86cripple.BottlesRetroCD.metainfo.xml` — AppStream metadata;
- `/usr/share/doc/bottles-retrocd/` and `/usr/share/licenses/bottles-retrocd/` — app-owned docs/license.

Packaging source policy:

- For the first 0.4.0 package, pin the installed runtime source to exact reviewed merge commit `8c75163168164fef896041c6b1a62ddac19b3faf`, not a moving branch.
- Packaging-only commits may change recipe/metadata/docs/CI but must not silently change the runtime payload away from the reviewed commit.
- No files may be installed under `/home`, `/run`, `/mnt`, `/media`, `/dev`, `/sys`, or user config/data locations.
- Package install/remove scripts must never create/reset/delete Bubblejail instances, private HOME, prefixes, RetroCD config, archive, DAT catalog/cache or other user-owned content.
- Uninstall removes only package-owned files under `/usr`; user state is intentionally preserved.

Verified current dependency policy (2026-09-10):

- direct package dependencies: `python`, `python-gobject`, `gtk4`, `bottles`, `bubblejail`, `cdemu-daemon`, `libmirage`, `udisks2`, `vulkan-tools`, `iproute2`, `util-linux`;
- on stock Arch, `bottles` and `bubblejail` are AUR packages; do not pretend they are official-repo packages;
- `cdemu-daemon`, `libmirage`, `udisks2`, `vulkan-tools`, `python-gobject`, `gtk4`, `util-linux` are available in Arch repositories at packaging time;
- do **not** add a direct dependency on `vhba-module` or `vhba-module-dkms`; CDEmu/distribution/kernel must satisfy the effective `VHBA-MODULE`, preserving CachyOS kernel-provided VHBA where applicable;
- do **not** add `cdemu-client` as a hard dependency; RetroCD uses D-Bus directly;
- `sudo` is optional and only enables the interactive Componenti full-system update action;
- no separate/broad gamepad dependency or permissions layer beyond Bubblejail `[joystick]`.

Packaging validation:

- packaging CI must validate `PKGBUILD`, `.install`, launcher shell syntax, desktop/metainfo structure and local-source hashes without weakening the existing runtime CI;
- build with `makepkg` on target CachyOS after syncing the packaging branch;
- inspect package file list/metadata before install;
- install package and launch via `/usr/bin/bottles-retrocd` and desktop entry;
- rerun a focused installed-package acceptance: GUI startup/config persistence, Bubblejail sentinel test, GPU/Retro Optical secured launch, Discworld Noir XWayland, gamepad initial exact-node proof;
- explicitly test uninstall and prove config, Bubblejail instance/private HOME/prefixes and archive remain untouched; reinstall afterward if continuing release work;
- do not tag/release 0.4.0 until package-installed acceptance and uninstall-preservation pass.

## Git / release workflow

- `main` remains tested integration branch.
- Non-trivial work belongs on focused branches such as `packaging/arch-cachyos-0.4.0`.
- Keep commits focused; compare branch with `main` before merge; no force-updates.
- Do not commit generated `src/`, `pkg/`, built package archives, caches, private instance state, mounted media, DAT downloads or user-specific paths.
- Merge packaging branch only after packaging CI + target package build/installed acceptance/uninstall preservation are green and owner approves.
- After packaging merge, verify `main` CI, then tag/release 0.4.0.

## Post-release roadmap, agreed order

1. **Native legacy optical DRM compatibility/emulation** — investigate SafeDisc, SecuROM, LaserLock, StarForce and other Windows 9x/XP optical protections; reproduce original verification behavior via Wine/CDEmu/libMirage or compatible components; reuse license-compatible open source; No-CD/cracks are not the normal solution; keep optional/fail-closed without broader sandbox permissions.
2. **Legacy DirectX compatibility layer/manager** — DxWrapper/dgVoodoo2-style DirectX 5–9 support, optional/OFF by default, after DRM work and before shaders.
3. **libRashader + Slang shaders** — optional/OFF by default per game/bottle after compatibility foundation is stable.
4. **Abnormal-termination recovery for live multidisc cache devices** — safe recovery without weakening ownership validation.

None of these may weaken the validated Bubblejail boundary or become mandatory without a concrete reviewed reason.

## Documentation references

Keep aligned: `README.md`, `README-TESTING.md`, `REVIEW.md`, `docs/SECURITY-REVIEW.md`, `docs/TESTING.md`, `docs/ROADMAP.md`, `CHANGELOG.md`, and `packaging/arch/README.md`.
