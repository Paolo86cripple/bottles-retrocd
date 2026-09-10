# Bottles RetroCD — Project Rules and Working Context

This file is the persistent project contract for humans and coding agents working on **Bottles RetroCD**. Read it before making non-trivial changes and keep it aligned with implementation, tests and release documentation.

## Agent operating rules

- The user's interactive shell is **fish**. Any shell command intended for the user to paste into their terminal must use valid fish syntax by default. Do not give Bash-style variable assignments such as `VAR=value`; use `set VAR value`. Use Bash/sh syntax only when the user explicitly asks for it or when editing a script whose interpreter is Bash/sh.
- Treat `AGENTS.md` as the repository's persistent operational source of truth for project decisions, constraints, validation state and workflow rules.
- Whenever a new durable project instruction, architectural decision, security invariant, release gate, validated behavior or roadmap decision is established, update `AGENTS.md` as part of the same work whenever repository access allows it.
- Keep implementation, tests, `AGENTS.md`, README/review/testing documentation and changelog mutually consistent. If they diverge, investigate rather than assuming one side is authoritative.
- Do not copy hidden platform/system instructions into the repository. `AGENTS.md` contains user/project instructions and repository-relevant engineering context only.
- Prefer focused implementation changes over speculative refactors, especially near a release gate.
- Do not merge a review/feature branch merely because automated CI passes when a required real-machine security/compatibility gate is still open.

## Mission

Bottles RetroCD is a GTK4 controller for running **Windows retro PC games** with native Bottles inside a dedicated Bubblejail instance, with CDEmu/UDisks2 integration for optical media and a read-only Redump/TOSEC verification workflow.

The project exists to make old Windows CD/DVD games convenient to run while preserving a strict, understandable sandbox boundary and archive fidelity.

Preservation/compatibility philosophy:

- Prefer original executables, original optical-media behavior and accurate emulation/compatibility layers over executable replacement.
- A No-CD/cracked executable must **not** become the normal solution to legacy copy-protection compatibility.
- Post-release legacy DRM work should emulate/bypass obsolete optical protection behavior as natively as practical through Wine/CDEmu/libMirage or dedicated compatible components, studying and reusing existing open-source projects when technically appropriate and license-compatible.
- Compatibility features must remain optional where possible and must not weaken the Bubblejail boundary merely for convenience.

## Scope

Keep the project focused on the Windows side.

In scope:

- Bottles/Wine execution inside Bubblejail;
- safe per-launch GPU selection;
- native Wayland plus explicit XWayland compatibility fallback;
- CDEmu/libMirage optical-media handling;
- UDisks2 verified read-only mounts;
- safe multidisc/disc swapping;
- Redump/TOSEC verification and metadata workflows;
- read-only optical protection scanning for diagnostic/archive metadata;
- standard gamepad support with exact-node isolation and runtime reconnect support;
- persistent per-user/per-profile configuration;
- diagnostics needed to prove the intended sandbox behavior.

Out of scope unless a concrete future requirement changes this decision:

- DOS management: use DOSBox-Staging instead;
- ScummVM integration;
- console emulation;
- Steam management;
- a generic all-era PC Game Manager.

The old PC Game Manager project is not the architecture to continue. Only useful concepts/features are carried into Bottles RetroCD: **GPU selector, multidisc support, Redump/TOSEC verification, and persistent configuration**.

## Release identity

- Stable application ID: `io.github.Paolo86cripple.BottlesRetroCD`.
- Current release candidate/version: `0.4.0`.
- 0.4.0 feature scope is frozen except for release blockers, documentation alignment and packaging/release hardening.

## Architectural baseline

- Reuse the existing Bubblejail instance named `Bottles`.
- Bottles, Wine, runners, DXVK, runtimes and prefixes live in Bubblejail's private HOME.
- The GTK controller runs on the host as the logged-in user.
- CDEmu/libMirage image parsing happens on the host.
- Redump/TOSEC DAT parsing, hashing and protection scanning happen on the host.
- The gamepad hotplug monitor/helper runs host-side as the logged-in user but may target only the namespaces of the active `Bottles` instance and validated controller device/sysfs references.
- Bubblejail is the security boundary for Bottles/Wine, not for the controller, verifier, gamepad broker or libMirage.
- CDEmu is controlled through its D-Bus API model rather than localized CLI-output parsing. `cdemu-client` is optional.
- UDisks2 mount state must be verified, not inferred from command success.
- The archive root is an explicit persistent setting; no user-specific storage location is hardcoded into the release.

Do not replace this design with another sandbox stack unless there is a demonstrated security or compatibility reason.

## Security invariants

Security regressions are release blockers.

### Filesystem

- Host HOME must remain hidden from Bottles/Wine except for explicitly approved shares.
- Host filesystem exposure is deny-by-default.
- Persistent shares use an explicit Bubblejail whitelist with separate RO and RW paths.
- Canonicalize and validate whitelist paths before writing configuration.
- Allow explicitly whitelisted RO access to the configured RetroCD archive root and its subdirectories. Reject RW access to any part of the archive, its ancestors in either mode, real HOME, broad system roots, unsafe overlap, and equivalent over-broad paths.
- Dynamic optical/cache mounts into the jail must use `ro-bind`.
- Never expose broad `/run/media`, `/mnt` or storage-root trees merely to make optical media work. Archive RO sharing requires an explicit whitelist entry; selecting an archive does not share it automatically.
- Isolation tests must create a real temporary host sentinel and prove that it is invisible inside Bubblejail; do not infer isolation from a path that may not exist.

### Network

- Bottles network is OFF by default.
- Persistent `[network]` in Bubblejail `services.toml` is forbidden and must be rejected.
- Bottles network may be enabled only transiently for the selected launch.
- Do not weaken this rule to simplify runner downloads or setup. Download with a temporary network-enabled launch, then verify persistence with network OFF.
- Verifier DAT updates use a separate, narrower network policy: HTTPS only, explicit official Redump/TOSEC host allow-list, and redirect revalidation.

### Display

- `Auto` is the neutral/default display policy.
- Native Wayland may be selected persistently when supported by the runner.
- XWayland is an explicit compatibility fallback; it must not require broader filesystem, network, GPU or optical permissions.
- XWayland keeps Bottles/GTK free to use Wayland while Wine/Proton is directed to the X11/XWayland path.
- Forced XWayland requires the existing Bubblejail `x11` and `wayland` services; RetroCD must fail closed rather than silently add display permissions.
- Bottles global GSettings use the isolated `keyfile` backend so preferences persist in Bubblejail's private HOME instead of writing host dconf.

### GPU

- Detect GPUs dynamically.
- Persist GPU identity by stable PCI address, never by unstable `cardX` numbering.
- Prefer the integrated GPU only as the initial/default-selection heuristic.
- The explicitly selected GPU is authoritative for access control.
- A Bottles launch **must not** fall back to an implicit Mesa/default GPU when no valid selection can be proven.
- Before launch, validate the selected GPU PCI address, 4-digit vendor/device IDs, kernel driver, DRM `cardN` and `renderD*` names, and require both DRM paths to be live character devices.
- Apply Mesa GPU selection per launch; do not rewrite the persistent Bubblejail profile merely to change GPU.
- Bubblejail 0.10.x `direct_rendering` is too broad for strict multi-GPU isolation: mask `/dev/dri` at runtime and bind back only the selected GPU's DRM card/render nodes.
- Every normal Bottles launch must run a fail-closed **pre-launch** GPU probe that positively proves `DRI_PRIME`, selected DRM-node presence, known non-selected DRM-node absence, exactly one Vulkan device, and matching vendor/device identity.
- Every normal Bottles launch must then run a fail-closed **post-launch proof against the already-running Bubblejail instance**. On Bubblejail 0.10.4 this uses `bubblejail run --wait <instance> /bin/sh -c <probe>`, not `--debug-shell`.
- Absence of a required success/proof marker is failure; do not infer success from lack of an explicit failure marker.
- If helper injection or post-launch proof fails, terminate the exact launch process group and report launch failure.
- The manual Vulkan/GPU test must use the same strict validator as the normal launch path.
- Do not further hide GPU-related sysfs unless a concrete threat or requirement justifies the Mesa/udev compatibility risk.

### Optical devices

- Raw `/dev/srX` exposure is optional and OFF by default.
- When enabled, accept only the exact device mapped by CDEmu and validate that it is a Linux SCSI optical block device (SCSI type 5).
- `/sys/class/block/srX/ro` is diagnostic only. VHBA/CDEmu may legitimately report `ro=0` even when the image filesystem is safely mounted read-only.
- The security decision for mounted media is the verified UDisks2 read-only filesystem state.
- `/dev/sgX` is broader SCSI access and must remain optional and OFF by default.
- The CDEmu D-Bus service and `/dev/vhba_ctl` must not be exposed to Bottles/Wine.

### Gamepad / input devices

- Standard gamepad support uses Bubblejail's `[joystick]` service.
- Never expose all of `/dev/input` merely to make a controller work.
- Never expose keyboard or mouse event devices as part of gamepad support.
- `/dev/hidraw*` remains hidden for the standard 0.4.0 gamepad path. Switch/gyro/hidraw-dependent controller support is out of scope for 0.4.0 rather than a reason to weaken isolation.
- Host detection accepts supported `jsX` nodes and their matching evdev `eventX` sibling(s); acceptance is based on the current host-detected identity, not hardcoded node numbers.
- The pre-launch **Test gamepad** must prove exact host/jail node agreement, readability, absence of unrelated input nodes and absence of hidraw.
- Gamepad node numbers may change after disconnect/reconnect; this must not break reconciliation.
- The runtime monitor fingerprints device identity including path/inode/rdev so disappearance/path reuse is detected.
- Initial monitor activation is non-destructive because Wine already starts with the static Bubblejail joystick surface. It must report `udev=initial-static` and must not synthesize an unnecessary add event.
- Physical disconnect/reconnect must reconcile only the exact current gamepad `jsX/eventX` nodes plus the matching minimal sysfs subtree and emit corresponding synthetic libudev notifications for Wine/winebus. Successful real changes report `udev=notified`.
- Runtime reconciliation must keep `sysfs=exact` and `hidraw=hidden` after every transition.
- Namespace/sysfs/udev/isolation failures are failures. Do not add a permissive fallback.
- Do not require sudo, root, additional host groups, persistent udev permission changes or host capabilities for the normal hotplug path.
- The 0.4.0 broker discovers the user namespace that owns Bubblejail's mount namespace using `NS_GET_USERNS`, creates a private staging mount namespace under that owner, pins/revalidates device/sysfs object identity, prepares exact detached mounts, then enters the target mount/network namespaces and mutates the jail fail-closed.
- Some legacy games enumerate controllers only at startup. RetroCD can prove the Wine-visible device/sysfs/udev transition; it cannot force a game to implement runtime re-enumeration.

## Multidisc rules

Archive fidelity is mandatory.

- Persistent disc sets store references to the user's original descriptors under the configured archive root.
- Never copy, rename, rewrite, modify, touch, or symlink original CUE/BIN/image files merely to create a set.
- Creating an explicit set starts from the exact selected descriptor; Disc 1 must always be usable as the anchor.
- Automatic filename grouping is advisory only and must never silently become persisted truth.
- Live multidisc requires an explicit saved set.
- Cache filesystems are mounted read-only with UDisks2 and individually `ro-bind` mounted into Bubblejail.
- Only the active CDEmu `/dev/srX` may be exposed for live swapping; cached drives and `/dev/sgX` must not be leaked into the jail.
- During swap, neutralize `/mnt/cdemu` to a real empty directory before changing media.
- Swap on the same validated active `/dev/srX`; mapping changes must fail closed and trigger rollback.
- Revalidate cache device count, ordering and mappings before cleanup/removal.
- Do not remove devices if external CDEmu activity has made ownership ambiguous.
- While a live multidisc session is active, lock the selected CDEmu drive and freeze set editing.
- Poll Bottles exit and clean caches automatically.
- Refuse normal GUI close while live Bottles still depends on the multidisc cache.
- Log cleanup start, completion and failure in the cumulative application log.

Known residual risk: an abnormal GUI crash/kill during a live multidisc session can leave temporary host-side CDEmu cache drives mounted. Normal lifecycle paths must clean up safely; future recovery work should address abnormal termination without weakening ownership validation.

## Redump/TOSEC verifier rules

The verifier is implemented and is part of the project baseline. Do not treat it as a future placeholder.

### Archive integrity

- Verification must never mount, execute, rename, rewrite, move, copy or touch dump files.
- CUE/TOC references must be canonicalized and remain below the authorised archive root.
- Reject traversal, absolute POSIX paths, Windows drive-letter paths and UNC-style references in descriptors.
- Preserve original Redump/TOSEC filenames and directory structure.
- A verification or local-DAT import test must be able to prove source content and `mtime_ns` remain unchanged.

### Hashing and cache

- Calculate CRC32, MD5 and SHA-1 in one streaming pass.
- Stat before and after hashing and fail if the file changes during the operation.
- Hash-cache validity must depend on stable file identity/state, currently device/inode/size/mtime/ctime.
- Keep the hash cache outside the archive tree under XDG cache storage.
- Explicitly close SQLite connections; `ResourceWarning` is a CI failure.

### DAT catalog

- Parse Logiqx XML incrementally; do not require loading large DATs into memory as one DOM.
- Preserve source/DAT/game/description/serial/version/protection metadata when present.
- Ignore ROM entries that have neither a valid size nor any usable digest.
- Build catalog replacements in staging, run SQLite `integrity_check`, and reject empty/unverifiable indexes.
- `MATCH 1:1` requires every local payload to match one complete DAT game record and no second complete equivalent record.
- Partial per-file matches are `MISMATCH`.
- Multiple complete equivalent records are `AMBIGUOUS`; never silently prefer Redump or TOSEC.

### DAT updater

- Allow HTTPS only.
- Revalidate redirect targets against the explicit official Redump/TOSEC host allow-list.
- Reject credentials embedded in updater URLs.
- Bound download bytes, ZIP member count, individual unpacked member size and total unpacked size.
- Reject ZIP traversal and symlink entries.
- Materialize only DAT/XML metadata files.
- Stage and fully index the combined catalog before moving any live generation.
- If any failure occurs after a live DAT/catalog was moved to a rollback name, restore the previous generation even if the failure itself is an `os.replace()` failure.
- Keep local manual DAT imports in a separate source namespace so official updates cannot overwrite them.

### Protection scanner

- Scanner is read-only and must never mount or execute image contents.
- Bound ISO/Joliet directory depth, entry count, directory extent size and file-content samples.
- The current hard limit for one directory extent is 64 MiB; malformed larger extents must fail closed rather than allocate unbounded memory.
- Raw signature scanning must be streaming and handle cross-chunk signatures.
- Scanner evidence is heuristic metadata only; it does not override cryptographic DAT matching.
- Compare DAT protection metadata and scanner evidence explicitly instead of conflating them.

## Persistent configuration

- Use `~/.config/bottles-retro-cd/` for application configuration.
- Configuration directory mode: `0700`.
- Sensitive metadata/config files such as `config.toml` and `disc-sets.toml`: `0600`.
- Config schema 2 persists `gpu_pci`, `display_backend` and `archive_root`.
- Existing pre-schema-2 target installs may migrate the old `/run/media/<user>/Data/Downloads/retropc` archive location only when it actually exists; migration stores the path and never moves or modifies archive data.
- New installations must choose an archive root explicitly; no machine-specific removable-storage default is allowed.
- Verifier catalog data belongs under XDG data storage; hash/cache data belongs under XDG cache storage.
- Persist stable identifiers and user intent, not volatile kernel numbering.
- Preserve compatibility with existing settings whenever possible; migrations must be explicit and safe.

## Coding practices

- Prefer Python standard-library solutions when practical.
- Subprocess calls must use argv lists.
- Do not use `os.system`, `shell=True`, `eval`, or dynamic `exec` in application paths.
- Never interpolate user-controlled filesystem paths into an unquoted shell command.
- If a shell snippet is unavoidable for a test, quote paths correctly and keep the snippet narrowly scoped.
- GTK widget access from background work must be marshalled to the GTK main thread.
- Configuration writes must be syntax-checked where applicable, backed up when modifying Bubblejail configuration, and replaced atomically.
- Detect Bubblejail runtime-argument capabilities before depending on `--debug-bwrap-args`.
- Keep launch stdout/stderr available in the XDG cache/log path for diagnostics instead of discarding it.
- Do not hardcode a specific user's home directory or storage path.
- Favor fail-closed behavior when security-sensitive identity/mapping checks are ambiguous.
- Avoid additional hardening that creates substantial compatibility risk without a concrete security benefit.
- Preserve reviewed security-sensitive controller code when possible; isolate new host-side features into focused modules rather than expanding a monolith.
- Near release, do not refactor already validated core code solely for aesthetic cleanup. Defer low-value consolidation until after release unless dead/duplicate behavior creates an actual risk.

## User-facing command examples

- Commands shown for manual terminal execution must be valid for **fish**.
- Prefer fish-native variable assignment, for example:

  ```fish
  set ARCHIVE "/path/to/archive"
  ```

  not:

  ```bash
  ARCHIVE="/path/to/archive"
  ```

- `VAR=value command` environment-prefix syntax should be replaced with fish-compatible `env VAR=value command` or `set -lx VAR value` as appropriate.
- Multi-line pipelines and continuations should be written so they paste cleanly into fish.
- Script files keep the syntax of their declared shebang; this rule concerns commands given interactively to the user.

## Testing gate

Before treating a feature as release-ready, close Bottles completely and validate the relevant paths on the target CachyOS system.

Baseline release tests:

1. **CDEmu + UDisks2**
   - temporary drive creation/mapping;
   - D-Bus image load;
   - optical-device identity validation;
   - advanced options get/set/get;
   - verified RO mount;
   - denied write attempt;
   - safe cleanup.

2. **Bubblejail**
   - whitelist audit PASS;
   - no persistent `[network]`;
   - private HOME writable and real host HOME marker invisible;
   - configured RW paths writable;
   - configured RO paths reject writes;
   - a real temporary non-whitelisted host sentinel is invisible;
   - only loopback with base network OFF;
   - Wayland, XWayland, audio and GPU/Vulkan checks pass.

3. **GPU fail-closed launch**
   - run **Test Vulkan** for each selectable GPU;
   - launch each GPU and require both pre- and post-launch GPU proof lines;
   - verify selected DRM nodes are present and all known non-selected GPU nodes absent;
   - verify exactly one Vulkan device with matching vendor/device IDs;
   - verify `DRI_PRIME` during the pre-launch probe;
   - verify failure to prove the running sandbox terminates the launch.

4. **CD → Bubblejail**
   - temporary CDEmu drive and RO host mount;
   - optional raw `/dev/srX` is the validated CDEmu optical device;
   - `/mnt/cdemu` visible but not writable;
   - real temporary host sentinels remain hidden;
   - cleanup removes temporary resources.

5. **Runner/preferences persistence**
   - launch once with temporary network ON and install/download a runner;
   - close Bottles fully and confirm the runner persists in Bubblejail private HOME;
   - relaunch with network OFF and confirm it remains usable;
   - change Bottles global preferences such as dark mode/temp cleanup and verify persistence through the isolated GSettings keyfile backend.

6. **Display fallback**
   - validate native Wayland;
   - validate XWayland with the same runner and sandbox permissions;
   - verify XWayland does not require extra network/filesystem/GPU/optical permissions.

7. **Gamepad exact-node isolation/hotplug**
   - with Bottles closed and controller connected, **Test gamepad** must expose only current `jsX` + matching `eventX`, readable, with no unrelated input and no hidraw;
   - launch with gamepad ON and require initial PASS with `sysfs=exact`, `udev=initial-static`, `hidraw=hidden`;
   - physically disconnect while Bottles stays running and require PASS with `nodi=nessuno`, `sysfs=exact`, `udev=notified`, `hidraw=hidden`;
   - reconnect without restarting Bottles and require exactly the current/new `jsX/eventX` pair with `sysfs=exact`, `udev=notified`, `hidraw=hidden`;
   - where the application itself supports runtime controller re-enumeration, confirm practical controller usability after reconnect.

8. **Feature-specific tests**
   - Multidisc: verify explicit-set membership, original-file content/mtime immutability, live swaps, rollback and automatic cleanup.
   - Redump/TOSEC verifier: run the full verifier/updater/scanner regression suite, verify a known real Redump set, and prove descriptor/payload content and `mtime_ns` are unchanged.

Static checks before merge must include Python compilation of every module, shell syntax, unit tests with `ResourceWarning` promoted to errors, and a scan ensuring forbidden execution patterns have not appeared.

## Current validated baseline

The **0.4.0 pre-packaging candidate** has been validated on CachyOS with the existing Bubblejail/CDEmu/Bottles stack.

Validated target-machine paths include:

- both available AMD GPUs, including the Ryzen 7 9800X3D integrated GPU and Radeon RX 9070 XT, with automatic pre/post launch proof;
- CDEmu/UDisks2 RO optical flow, optional raw `/dev/srX`, explicit `/dev/sgX`, multidisc cache/swap and cleanup;
- Discworld Noir three-disc Redump set;
- Bottles global preference persistence using `GSETTINGS_BACKEND=keyfile` inside the private HOME;
- `proton-cachyos-native` + D7VK with Discworld Noir;
- native Wayland working, with XWayland validated as the compatibility fallback and providing immediate fullscreen with audio for Discworld Noir;
- network OFF baseline and temporary network ON runner persistence;
- Xbox One S static Bubblejail path with only the exact current `jsX` + matching `eventX`, no unrelated input and no hidraw;
- Xbox One S physical hotplug while Bottles remained running: initial `event9 + js0` PASS with `sysfs=exact`, `udev=initial-static`, `hidraw=hidden`; disconnect PASS with no controller nodes and `udev=notified`; reconnect PASS with exact `event9 + js0`, `sysfs=exact`, `udev=notified`, `hidraw=hidden`;
- schema-2 `archive_root` persistence with `0700` config directory and `0600` config file, plus identical pre/post archive metadata signatures after GUI re-selection;
- resize + vertical scrolling across all notebook pages after the all-pages scroller fix;
- final Bubblejail isolation test on target: **PASS=17 FAIL=0 WARN=0**, with real non-whitelist sentinel hidden, private HOME, host HOME/.ssh hidden, configured RW/RO behavior correct, base network limited to `lo`, Wayland/X11/audio/GPU/Vulkan/dconf all available as intended;
- final CD → Bubblejail integration test with Discworld Noir Disc 1: temporary `/dev/sr1` validated as SCSI optical type 5, host mount verified RO, both freshly-created real non-whitelist sentinels hidden, `/mnt/cdemu` visible and non-writable, temporary drive cleanup PASS. VHBA block-layer `ro=RW` remains diagnostic only and does not override the verified RO filesystem policy;
- verifier/source immutability and lifecycle/update negative paths.

Automated regression baseline: **151 unit tests PASS**, Python compilation for all application modules including `gamepad_ns_entry.py`, `ResourceWarning`-as-error PASS, `bash -n run-local.sh` PASS, and forbidden dynamic-execution scan PASS. CI #320 on commit `2d0373d2e6ae08eb6dfd6616ad013d1c77058bac` is SUCCESS after the real-sentinel CD integration-test hardening.

The gamepad implementation is frozen for 0.4.0 unless a new real release blocker is discovered.

## Final pre-packaging gate status

PR #3 / `review/pre-packaging-cleanup` remains open until the final real-machine gate is complete.

Already closed:

- gamepad static exact-node isolation;
- gamepad initial broker activation;
- physical controller disconnect/reconnect without restarting Bottles;
- GPU pre/post isolation on target hardware;
- core Retro Optical pre/post isolation;
- Discworld Noir XWayland fullscreen/audio compatibility;
- existing multidisc/verifier/lifecycle target validation;
- schema-2 archive root, GUI persistence and archive immutability check;
- resize + vertical scroll on all notebook pages;
- final Test Bubblejail with real temporary host sentinel: 17 PASS, 0 FAIL, 0 WARN;
- final Test CD → Bubblejail with real temporary integration sentinels, verified RO `/mnt/cdemu` and cleanup PASS.

Remaining final-machine checks before merge/packaging:

1. perform one final normal Bottles launch and require GPU pre/post + Retro Optical pre/post PASS;
2. repeat the known-good XWayland Discworld Noir launch as the last compatibility regression. These may be satisfied by the same final Discworld Noir/XWayland session if that session produces all four isolation proof lines and the game itself still reaches the known-good fullscreen/audio state.

Do not merge PR #3 until these are complete.

## Packaging requirements

When packaging begins:

- package the stable app ID `io.github.Paolo86cripple.BottlesRetroCD` at version `0.4.0`;
- preserve the existing Bubblejail `Bottles` instance and user-owned private HOME/config/data;
- install/remove only package-owned application files;
- normal package removal must not delete user configuration, private Bottles HOME/prefixes, archive data, DAT/user cache policy data or Bubblejail instance data;
- do not add `cdemu-client` as a hard runtime requirement; RetroCD uses the CDEmu D-Bus API;
- UDisks2/`udisksctl` remains required for verified RO optical mounts/live multidisc paths;
- use host CDEmu/libMirage and the effective VHBA provider without duplicating kernel infrastructure already supplied by CachyOS;
- do not add a separate broad gamepad package/permission layer beyond the reviewed Bubblejail joystick path;
- after package creation, perform package-installed acceptance tests before tagging the release.

## Git workflow

- `main` is the integration branch and should remain in a tested, usable state.
- Develop non-trivial features on focused branches such as `feature/<name>` or `review/<name>`.
- Keep commits focused and descriptive.
- Run static/unit checks before committing and real-machine integration checks before declaring a security-sensitive feature finished.
- Compare the feature branch against `main` before merge and confirm only intended files changed.
- Prefer a clean reviewed merge; never force-update `main` merely to simplify history.
- After integration, verify remote `main`, then remove obsolete feature branches only when they are no longer useful.
- Do not commit generated caches, local machine state, private Bottles prefixes, mounted media, DAT downloads or user-specific absolute paths.

## Near-term roadmap

The feature baseline for 0.4.0 is frozen except for release blockers. Immediate work is:

1. finish the final pre-packaging real-machine gate;
2. create Arch/CachyOS packaging, desktop integration and clean install/remove behavior;
3. run package-installed acceptance tests and release hardening;
4. merge/tag/publish the stable 0.4.0 release when all gates remain green.

Post-release work, in priority order:

1. **Legacy optical DRM compatibility/emulation** — investigate SafeDisc, SecuROM, LaserLock, StarForce and other relevant Windows 9x/XP-era CD/DVD protection schemes; reproduce original media/protection behavior as natively as practical through Wine/CDEmu/libMirage or dedicated compatible components; study and reuse existing open-source projects when technically appropriate and license-compatible; do not make No-CD/cracked executables the normal compatibility solution; keep any protection backend optional/fail-closed and do not broaden Bubblejail/optical permissions merely to make it work.
2. **Legacy DirectX compatibility layer/manager** — integrate optional DxWrapper/dgVoodoo2-style compatibility support for DirectX 5–9-era games, OFF by default and managed per game/profile.
3. **libRashader + Slang shaders** — optional, OFF by default, after the compatibility foundation is stable.
4. **Abnormal-termination recovery for live multidisc cache devices** — recover safely without weakening device ownership validation.

None of the post-release features may weaken the existing Bubblejail boundary or become mandatory for ordinary launch paths without a concrete, reviewed reason.

## Documentation references

See these files for detailed evidence and caveats:

- `README.md`
- `README-TESTING.md`
- `REVIEW.md`
- `docs/SECURITY-REVIEW.md`
- `docs/TESTING.md`
- `CHANGELOG.md`

When documentation and implementation diverge, investigate and update both; do not silently assume either side is current.
