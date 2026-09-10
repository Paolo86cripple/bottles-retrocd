# Bottles RetroCD — Project Rules and Working Context

This file is the persistent operational contract for humans and coding agents working on **Bottles RetroCD**. Read it before non-trivial work and keep it aligned with implementation, tests, packaging, release documentation and validated target behavior.

## Agent operating rules

- The user's interactive shell is **fish**. Any terminal command intended for the user to paste must use valid fish syntax by default. Use `set VAR value`, not Bash-style `VAR=value`. Use Bash/sh syntax only when explicitly requested or when editing/testing a script whose declared interpreter is Bash/sh.
- Treat `AGENTS.md` as the repository's persistent source of truth for durable project decisions, constraints, validation state, workflow, packaging and roadmap.
- Update `AGENTS.md` whenever a durable project instruction, architecture/security decision, release gate, validated behavior, packaging decision or roadmap decision changes.
- Keep implementation, tests, `AGENTS.md`, README/review/testing docs, packaging metadata and changelog mutually consistent. Investigate divergence rather than assuming one side is current.
- Do not copy hidden platform/system instructions into the repository.
- Prefer focused changes over speculative refactors, especially around security-sensitive paths and stable releases.
- Once a security-sensitive runtime path is CI-green and target-validated, do not refactor it for aesthetics without a concrete reason and relevant regression testing.
- Never force-update `main` merely to simplify history.
- Packaging/release work still requires real-machine gates where specified; CI alone is not sufficient.
- No automatic merge. Owner approval is required before merging non-trivial packaging/release/security-sensitive work.

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
- Arch/CachyOS packaging and release distribution.

Out of scope unless a future concrete requirement changes the decision: DOS management (use DOSBox-Staging), ScummVM integration, console emulation, Steam management, or revival of a generic all-era PC Game Manager.

## Preservation / compatibility philosophy

- Prefer original executables, original optical-media behavior and accurate compatibility/emulation over executable replacement.
- A No-CD/cracked executable must **not** become the normal solution to legacy copy-protection compatibility.
- Future legacy DRM work should reproduce obsolete optical-protection behavior as natively as practical through Wine/CDEmu/libMirage or dedicated compatible components.
- Study/reuse existing open-source projects where technically appropriate and license-compatible instead of reinventing solved components.
- Compatibility layers remain optional where possible and must not weaken Bubblejail merely for convenience.

## Released baseline: 0.4.0

- Stable app ID: `io.github.Paolo86cripple.BottlesRetroCD`.
- Stable release name/version: `Bottles RetroCD 0.4.0`.
- Runtime security/compatibility baseline merged by PR #3: `8c75163168164fef896041c6b1a62ddac19b3faf`.
- Final packaging/release PR #4 merged to `main` as `15b1e0acc61d61978051d49d97bd17cb97efb348`.
- Post-merge `main` CI: PASS.
- Annotated tag **`0.4.0`** was published on 2026-09-10 and verified to dereference exactly to merge commit `15b1e0acc61d61978051d49d97bd17cb97efb348`.
- Treat the published `0.4.0` tag as immutable. Do not move or retag it; fixes require a new version/tag.
- Final Arch/CachyOS package is **`bottles-retrocd 0.4.0-3`**.
- Package source is pinned to identity-fix commit `122460692d0c19650d663a77288b1c489851cd44`; its only runtime-code delta from the fully validated baseline is the final wrapper's stable app ID/name/version override.
- `.SRCINFO` is tracked and synchronized with `PKGBUILD`.
- Full pre-release security/compatibility gates plus package acceptance and uninstall-preservation are PASS.
- Narrow 0.4.0-3 identity/package gate is PASS: clean package build with 151/151 tests, upgrade from 0.4.0-2, `pacman -Qkk` 53 files/0 altered, stable GUI identity and GTK/D-Bus application ID verified.
- 0.4.0 is now a frozen release baseline except for narrowly scoped maintenance/security fixes.
- Distribution target for the GitHub Release: attach `bottles-retrocd-0.4.0-3-x86_64.pkg.tar.zst` plus a SHA256 checksum. The package is the intended Arch/CachyOS binary artifact for this release.

## Architectural baseline

- Reuse the existing Bubblejail instance named `Bottles`; do not create a second persistent instance.
- Bottles/Wine/runners/DXVK/runtimes/prefixes live in Bubblejail's private HOME.
- GTK controller, CDEmu/libMirage control, DAT updater controller and gamepad hotplug helpers are host-side as the logged-in user.
- Archive verification/protection parsing runs in a dedicated bubblewrap worker; official DAT updates run in a separate networked bubblewrap worker.
- Gamepad helpers may target only the active `Bottles` instance and validated controller device/sysfs references.
- Bubblejail remains the security boundary for Bottles/Wine. Dedicated bubblewrap workers provide additional least-privilege boundaries for verifier/scanner and official DAT updates.
- CDEmu is controlled through its D-Bus API model; `cdemu-client` is optional.
- UDisks2 mount state must be verified, not inferred from command success.
- Archive root is explicit persistent configuration; no release-time user-specific storage path may be hardcoded.
- Local-tree entrypoint remains `run-local.sh`; installed entrypoint is `/usr/bin/bottles-retrocd`, delegating to `/usr/lib/bottles-retrocd/run-local.sh`.
- The final gamepad wrapper is the authoritative released 0.4.0 application identity layer and publishes `io.github.Paolo86cripple.BottlesRetroCD`, `Bottles RetroCD`, `0.4.0`.

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
- Never expose broad `/run/media`, `/mnt` or storage roots merely to make optical media work.
- Isolation tests must create real temporary host objects and prove them invisible; nonexistent paths are not proof.

### Persistent configuration

- Config path: `~/.config/bottles-retro-cd/` mode `0700`.
- Sensitive files such as `config.toml`/`disc-sets.toml`: `0600`.
- Schema 2 persists `gpu_pci`, `display_backend`, `archive_root`.
- Historical archive-path migration stores only the path when it exists and never moves/copies/renames/rewrites/touches archive data.
- New installs choose archive explicitly.
- Persist stable identifiers, not volatile kernel numbering.

### Network

- Bottles network OFF by default.
- Persistent `[network]` in Bubblejail config is forbidden and must fail validation.
- Network may be enabled only transiently for a selected launch.
- Do not make network persistent merely to download runners.
- Runner workflow: temporary network ON for download/install, fully close Bottles, reopen OFF and confirm persistence in private HOME.
- Verifier/scanner worker has an unshared network namespace and may see at most loopback.
- Official DAT updater networking is isolated in its own bubblewrap worker and remains HTTPS-only to explicit official Redump/TOSEC hosts with redirect revalidation.

### Display / preferences

- Persistent display choices: Auto, native Wayland, XWayland.
- Auto is neutral; native Wayland only where supported by runner.
- XWayland is a compatibility fallback and must not broaden filesystem/network/GPU/optical access.
- Forced XWayland requires existing Bubblejail `x11` + `wayland`; fail closed rather than adding permissions silently.
- Bottles global settings use `GSETTINGS_BACKEND=keyfile` inside private HOME, not host dconf.

### GPU

- Detect dynamically; persist stable PCI address, never `cardX` numbering.
- No implicit Mesa/default fallback when selected GPU cannot be proven.
- Validate PCI/vendor/device/driver plus DRM `cardN` and `renderD*`; selected paths must be live character devices.
- Apply Mesa GPU selection per launch; do not rewrite persistent Bubblejail policy merely to switch GPU.
- Mask broad `/dev/dri` and bind back only selected card/render nodes.
- Pre-launch proof requires selected nodes, absence of known non-selected nodes, exactly one Vulkan device and matching vendor/device identity.
- Post-launch proof attaches to the already-running Bubblejail and re-proves effective isolation.
- Missing proof markers are failure; post-launch proof failure terminates the exact launch process group.
- Manual Test Vulkan uses the same strict validator.

### Retro Optical / CDEmu

- Raw `/dev/srX` is optional/OFF by default; if exposed it must exactly match CDEmu mapping and Linux SCSI optical type 5.
- `/sys/class/block/srX/ro`/block-layer RO is diagnostic only; verified UDisks2 filesystem RO state is authoritative.
- `/dev/sgX` is broader SCSI access, explicit and OFF by default.
- CDEmu D-Bus and `/dev/vhba_ctl` stay hidden from Bottles/Wine.
- No broad storage-tree exposure for optical compatibility.
- Lifecycle detects the effective VHBA provider, including CachyOS kernel-provided VHBA, and must not duplicate privileged/kernel infrastructure.
- During a live Bottles session, broad “eject all” operations are intentionally refused; use the validated active-device eject path.

### Standard gamepad / input

- Standard controller path uses Bubblejail `[joystick]`.
- Never expose all `/dev/input`, keyboard/mouse event nodes, or `/dev/hidraw*` for the standard path.
- Switch/gyro/hidraw-dependent support is out of scope rather than a reason to weaken isolation.
- Host detection accepts supported `jsX` plus matching evdev `eventX`; node numbers may change across reconnect.
- Test gamepad proves exact host/jail agreement, readability, no unrelated input, no hidraw.
- Runtime fingerprint includes path/inode/rdev.
- Initial monitor activation preserves known-good static surface and reports `udev=initial-static` without unnecessary synthetic add.
- Physical disconnect/reconnect reconciles exact current `jsX/eventX` plus minimal sysfs and sends synthetic libudev remove/add, reporting `udev=notified`.
- Every transition re-probes `sysfs=exact` and `hidraw=hidden`; ambiguity/failure is fail-closed with no permissive fallback.
- No sudo/root/additional groups/persistent udev permission changes/host capabilities for normal hotplug.
- Runtime hotplug routes through `gamepad_ns_entry.py`: `NS_GET_USERNS` discovers the mount-namespace owner; exact host objects are pinned; a private staging mount namespace is created; `(st_dev, st_ino, type, st_rdev)` is revalidated; detached exact mounts use `open_tree`; target mount/network namespaces are entered only after preparation. No PID namespace dependency.

## Multidisc rules

- Archive fidelity is mandatory: never copy/rename/rewrite/modify/touch/symlink original CUE/BIN/images to create a set.
- Persistent sets reference original descriptors under configured archive; Disc 1 remains a valid explicit anchor.
- Filename grouping/autodetection is advisory only and never silently persisted as truth.
- Live multidisc requires an explicit saved set.
- Cache filesystems are UDisks2 RO and individually `ro-bind` exposed.
- Only active CDEmu `/dev/srX` may be exposed; cached drives and `/dev/sgX` must not leak.
- During swap neutralize `/mnt/cdemu` to a real empty private directory, keep the same validated active `/dev/srX`, fail closed/rollback on mapping change.
- Revalidate cache device count/order/mapping before cleanup; refuse ambiguous removal during external CDEmu activity.
- Lock active drive/freeze set editing during live multidisc; poll Bottles exit and clean caches automatically; refuse normal GUI close while live Bottles depends on cache.
- Known residual: abnormal GUI/process kill may leave temporary cache drives; safe recovery is post-release work and must not weaken ownership validation.

## Redump / TOSEC verifier rules

- Archive verification and protection scanning execute in a dedicated bubblewrap worker, never directly in the GTK/CLI host process.
- Verifier/scanner worker mounts application code, authorized archive and existing catalog read-only; only the dedicated verifier hash-cache is writable.
- Verifier/scanner worker uses a private HOME and `/tmp`, an unshared network namespace, minimal `/dev`, and no host `/proc`, `/sys` or runtime state. Synthetic parent directories required for exact binds do not count as host-runtime exposure.
- The verifier sandbox must fail closed if `bwrap` is missing/untrusted, path layout overlaps protected trees, inputs escape the authorized archive, or positive attestation fails.
- Canonicalize CUE/TOC references below authorized archive and reject traversal/absolute/Windows/UNC escapes.
- Hash CRC32/MD5/SHA1 in one streaming pass; stat before/after; cache identity includes device/inode/size/mtime/ctime under XDG cache.
- Parse Logiqx incrementally; retain source/DAT/game/description/serial/version/protection metadata.
- Build catalog in staging, run SQLite integrity checks, reject empty/unverifiable indexes.
- `MATCH 1:1` requires one complete unique game; partial is `MISMATCH`; equivalent complete records remain `AMBIGUOUS`.
- Official DAT updates execute in a second, separate bubblewrap worker. It receives network access plus RW only to verifier data/catalog and verifier cache; the configured game archive must not be mounted or visible.
- Updater data/cache paths must not overlap the configured archive or application code. The worker must fail closed if the configured archive is visible before any download begins.
- The updater's filesystem is otherwise minimal: `/usr` RO, private HOME and `/tmp`, minimal `/dev`, and only exact RO host files needed for DNS/TLS resolution rather than broad `/etc` exposure.
- Official updater remains HTTPS-only with explicit host allow-list, redirect revalidation, bounded download/ZIP sizes/counts, traversal/symlink rejection, staged indexing, integrity checks and rollback.
- Manual DAT imports remain in a separate source namespace and are not routed through the networked official updater worker.
- Protection scanner is read-only, bounded, keeps the 64 MiB per-directory-extent limit, streams raw signatures with overlap, and never overrides cryptographic matching.

## Coding practices

- Prefer Python stdlib where practical.
- Application subprocesses use argv lists; no `os.system`, `shell=True`, `eval` or dynamic `exec` in app paths.
- Never interpolate user-controlled paths into unquoted shell commands.
- GTK widget access from workers is marshalled to the GTK main thread.
- Bubblejail config writes are syntax-checked/backed up/atomic where applicable.
- Detect Bubblejail runtime capabilities before depending on them.
- Keep launch stdout/stderr in XDG cache/logs.
- Do not hardcode user HOME/storage paths.
- Favor fail-closed identity/mapping decisions.

## 0.4.0 validation record

Automated/runtime baseline:

- 151 unit tests PASS;
- all application modules compile;
- `ResourceWarning`-as-error PASS;
- shell syntax PASS;
- forbidden dynamic-execution scan PASS;
- PR #3 and PR #4 CI green;
- post-merge `main` CI green;
- final target security/compatibility gate PASS.

Target validation included:

- both AMD GPU paths with pre/post DRM/Vulkan proof;
- CDEmu/UDisks2 RO flow, optional exact raw `/dev/srX`, explicit `/dev/sgX`, multidisc cache/swap/cleanup;
- Discworld Noir three-disc set, verifier/source immutability, native Wayland/XWayland, `proton-cachyos-native` + D7VK;
- network OFF baseline + temporary-network runner persistence;
- Xbox One S exact static path and physical hotplug/reconnect;
- schema-2 archive persistence + config permissions + identical pre/post archive metadata signatures;
- Test Bubblejail `PASS=17 FAIL=0 WARN=0`;
- installed-package functional launch PASS with RX 9070 XT selected, two other GPUs hidden, Retro Optical pre/post PASS, `/mnt/cdemu=RO`, raw sr hidden by default and exact gamepad isolation;
- live-session broad eject correctly refused; active-device eject succeeded;
- uninstall-preservation PASS.

## 0.4.1 hardening validation in progress

Focused branch: `hardening/0.4.1-verifier-sandbox`.

Completed gates:

- dedicated verifier/scanner bubblewrap boundary implemented without changing the released Bottles/Wine Bubblejail runtime policy;
- target attestation PASS on CachyOS: archive=RO, app=RO, catalog=RO, cache=RW, host HOME sentinel hidden, network=loopback only, `/proc` hidden, `/sys` hidden, host `/run` runtime state hidden;
- real Discworld Noir Disc 1 CUE/BIN verification through the worker PASS with Redump `MATCH 1:1` and protection scanner completing direct raw/ISO reads without mount/execution;
- GUI `Test verifica sandbox` PASS and GUI `Verifica + confronta scanner` PASS on the same image;
- official Redump updater moved to a separate networked bubblewrap worker; successful target update rebuilt the live catalog to 1 catalog / 61096 games / 199394 ROM records;
- immediate post-update Discworld Noir verification remained `MATCH 1:1`, proving download → staged catalog rebuild → atomic install → isolated verifier read path without archive regression;
- CI at updater-boundary HEAD: 180/180 unit tests PASS plus Python syntax, shell syntax, Arch packaging syntax, release identity/metadata and unsafe dynamic-execution scan PASS.

Still required before merge/release consideration:

- exercise the official updater through the GUI path on the target system;
- review/validate remaining 0.4.1 hardening items before deciding branch split/merge scope;
- no automatic merge; owner approval remains required.

## Arch / CachyOS packaging contract

Packaging layout:

- `packaging/arch/PKGBUILD`;
- `packaging/arch/.SRCINFO`;
- `/usr/lib/bottles-retrocd/` application payload;
- `/usr/bin/bottles-retrocd` launcher;
- desktop/AppStream metadata under `/usr/share`;
- docs/licenses under app-owned `/usr/share` locations.

Packaging policy:

- final 0.4.0 package metadata is `pkgver=0.4.0`, `pkgrel=3`;
- `conflicts=('bottles-retro-cd-gui')` and `replaces=('bottles-retro-cd-gui')` intentionally migrate the obsolete local package name;
- no package-owned files under `/home`, `/run`, `/mnt`, `/media`, `/dev`, `/sys`, or user data/config locations;
- install/remove scripts never create/reset/delete Bubblejail instances, private HOME, prefixes, RetroCD config, archive or verifier data;
- uninstall removes only package-owned `/usr` files and preserves user state;
- direct dependencies: `python`, `python-gobject`, `gtk4`, `bottles`, `bubblejail`, `cdemu-daemon`, `libmirage`, `udisks2`, `vulkan-tools`, `iproute2`, `util-linux`;
- do not hard-depend on `vhba-module`, `vhba-module-dkms` or `cdemu-client`;
- `sudo` remains optional for the Componenti update action;
- `lspci`/`pciutils` remains optional diagnostic enrichment;
- regenerate `.SRCINFO` after packaging metadata changes and rerun CI.

## Git / release workflow

- `main` remains the tested integration branch.
- Non-trivial work belongs on focused branches.
- Keep commits focused; compare branch with `main` before merge; no force-updates.
- Do not commit generated `src/`, `pkg/`, built package archives, caches, private instance state, mounted media, DAT downloads or user-specific paths.
- Published tags are immutable. `0.4.0` points to `15b1e0acc61d61978051d49d97bd17cb97efb348` and must never be moved.
- GitHub Release 0.4.0 uses tag `0.4.0` and distributes the validated `bottles-retrocd-0.4.0-3-x86_64.pkg.tar.zst` asset plus SHA256.
- Future fixes/releases use new branches, version/package revisions and tags as appropriate; never rewrite the 0.4.0 release history.

## Post-release roadmap, agreed order

0. **0.4.1 compatibility-preserving hardening — ACTIVE.** Harden host-side verifier/scanner/updater and lifecycle ownership/recovery without tightening the already validated game runtime in ways that could reduce compatibility.
1. **Native legacy optical DRM compatibility/emulation.** Investigate SafeDisc, SecuROM, LaserLock, StarForce and other Windows 9x/XP optical protections; reproduce original verification behavior via Wine/CDEmu/libMirage or compatible components; reuse license-compatible open source; No-CD/cracks are not the normal solution; keep optional/fail-closed without broader sandbox permissions.
2. **Legacy DirectX compatibility layer/manager.** DxWrapper/dgVoodoo2-style DirectX 5–9 support, optional/OFF by default, after DRM work and before shaders.
3. **libRashader + Slang shaders.** Optional/OFF by default per game/bottle after the compatibility foundation is stable.
4. **Abnormal-termination recovery for live multidisc cache devices.** Recover safely without weakening device-ownership validation; this may be pulled into the active 0.4.1 hardening cycle if implemented conservatively.

Post-release maintenance backlog:

- consolidate release identity constants into one shared module after focused regression review;
- retire/remove the old direct `mutate_instance()` helper path if still unused;
- consider deduplicating restrictive real-sentinel staging between lifecycle/final-wrapper layers.

None of these may weaken the validated Bubblejail boundary or become mandatory without a concrete reviewed reason.

## Documentation references

Keep aligned: `README.md`, `README-TESTING.md`, `REVIEW.md`, `docs/SECURITY-REVIEW.md`, `docs/TESTING.md`, `docs/ROADMAP.md`, `CHANGELOG.md`, and `packaging/arch/README.md`.
