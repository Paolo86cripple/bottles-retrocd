# Bottles RetroCD — Project Rules and Working Context

This file is the persistent project contract for humans and coding agents working on **Bottles RetroCD**.

## Mission

Bottles RetroCD is a GTK4 controller for running **Windows retro PC games** with native Bottles inside a dedicated Bubblejail instance, with CDEmu/UDisks2 integration for optical media.

The project exists to make old Windows CD/DVD games convenient to run while preserving a strict, understandable sandbox boundary.

## Scope

Keep the project focused on the Windows side.

In scope:

- Bottles/Wine execution inside Bubblejail;
- safe per-launch GPU selection;
- CDEmu/libMirage optical-media handling;
- UDisks2 verified read-only mounts;
- safe multidisc/disc swapping;
- Redump/TOSEC verification and metadata workflows;
- persistent per-user/per-profile configuration;
- diagnostics needed to prove the intended sandbox behavior.

Out of scope unless a concrete future requirement changes this decision:

- DOS management: use DOSBox-Staging instead;
- ScummVM integration;
- console emulation;
- Steam management;
- a generic all-era PC Game Manager.

The old PC Game Manager project is not the architecture to continue. Only useful concepts/features are carried into Bottles RetroCD: **GPU selector, multidisc support, Redump/TOSEC verification, and persistent configuration**.

## Architectural baseline

- Reuse the existing Bubblejail instance named `Bottles`.
- Bottles, Wine, runners, DXVK, runtimes and prefixes live in Bubblejail's private HOME.
- The GTK controller runs on the host as the logged-in user.
- CDEmu/libMirage image parsing happens on the host.
- Bubblejail is the security boundary for Bottles/Wine, not for the controller or libMirage.
- CDEmu is controlled through its D-Bus API model rather than localized CLI-output parsing.
- UDisks2 mount state must be verified, not inferred from command success.

Do not replace this design with another sandbox stack unless there is a demonstrated security or compatibility reason.

## Security invariants

Security regressions are release blockers.

### Filesystem

- Host HOME must remain hidden from Bottles/Wine except for explicitly approved shares.
- Host filesystem exposure is deny-by-default.
- Persistent shares use an explicit Bubblejail whitelist with separate RO and RW paths.
- Canonicalize and validate whitelist paths before writing configuration.
- Reject real HOME, broad system roots, the Data root/ancestors, unsafe overlap, and equivalent over-broad paths.
- Dynamic optical/cache mounts into the jail must use `ro-bind`.
- Never expose the broad `/run/media` tree merely to make optical media work.
- Unrelated paths below the user's Data storage must remain invisible.

### Network

- Network is OFF by default.
- Persistent `[network]` in Bubblejail `services.toml` is forbidden and must be rejected.
- Network may be enabled only transiently for the selected Bottles launch.
- Do not weaken this rule to simplify runner downloads or setup. Download with a temporary network-enabled launch, then verify persistence with network OFF.

### GPU

- Detect GPUs dynamically.
- Persist GPU identity by stable PCI address, never by unstable `cardX` numbering.
- Prefer the integrated GPU only as the initial/default-selection heuristic.
- The explicitly selected GPU is authoritative for access control.
- Apply Mesa GPU selection per launch; do not rewrite the persistent Bubblejail profile merely to change GPU.
- Bubblejail 0.10.x `direct_rendering` is too broad for strict multi-GPU isolation: mask `/dev/dri` at runtime and bind back only the selected GPU's DRM card/render nodes.
- GPU/Vulkan verification must fail closed if selected DRM nodes are missing, non-selected nodes remain visible, more than one Vulkan GPU is exposed, or vendor/device identity does not match the selection.
- Do not further hide GPU-related sysfs unless a concrete threat or requirement justifies the Mesa/udev compatibility risk.

### Optical devices

- Raw `/dev/srX` exposure is optional and OFF by default.
- When enabled, accept only the exact device mapped by CDEmu and validate that it is a Linux SCSI optical block device (SCSI type 5).
- `/sys/class/block/srX/ro` is diagnostic only. VHBA/CDEmu may legitimately report `ro=0` even when the image filesystem is safely mounted read-only.
- The security decision for mounted media is the verified UDisks2 read-only filesystem state.
- `/dev/sgX` is broader SCSI access and must remain optional and OFF by default.

## Multidisc rules

Archive fidelity is mandatory.

- Persistent disc sets store references to the user's original descriptors under the retro archive tree.
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

## Persistent configuration

- Use `~/.config/bottles-retro-cd/` for application configuration.
- Configuration directory mode: `0700`.
- Sensitive metadata/config files such as `config.toml` and `disc-sets.toml`: `0600`.
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
   - unrelated Data path invisible;
   - only loopback with base network OFF;
   - Wayland, XWayland, audio, GPU/Vulkan and dconf checks pass.

3. **CD → Bubblejail**
   - temporary CDEmu drive and RO host mount;
   - optional raw `/dev/srX` is the validated CDEmu optical device;
   - `/mnt/cdemu` visible but not writable;
   - unrelated Data paths remain hidden;
   - cleanup removes temporary resources.

4. **Runner persistence**
   - launch once with temporary network ON;
   - install/download runner;
   - close Bottles fully;
   - confirm runner persists in Bubblejail private HOME;
   - relaunch with network OFF and confirm it remains usable.

5. **Feature-specific tests**
   - GPU selector: verify every selectable GPU, strict DRM-node isolation, Vulkan vendor/device identity and real Bottles launch.
   - Multidisc: verify explicit-set membership, original-file content/mtime immutability, live swaps, rollback and automatic cleanup.
   - Redump/TOSEC verifier: add deterministic fixture/unit tests before merging; verification must never modify source media/archive files.

Static checks before merge should include Python compile/AST checks, shell syntax for shell launchers, unit tests, and a scan ensuring forbidden execution patterns have not appeared.

## Current validated baseline

The repository's current rc2/multidisc baseline has been validated on CachyOS with Bubblejail 0.10.4, CDEmu daemon 3.3.1 and Bottles 67.1.

Validated hardware paths include both available AMD GPUs, including the Ryzen 7 9800X3D integrated GPU and Radeon RX 9070 XT, and a three-disc Discworld Noir Redump set for live multidisc behavior.

See these files for detailed current evidence and caveats:

- `README.md`
- `REVIEW.md`
- `docs/SECURITY-REVIEW.md`
- `docs/TESTING.md`
- `CHANGELOG.md`

When documentation and implementation diverge, investigate and update both; do not silently assume either side is current.

## Git workflow

- `main` is the integration branch and should remain in a tested, usable state.
- Develop non-trivial features on focused branches such as `feature/<name>`.
- Keep commits focused and descriptive.
- Run static/unit checks before committing and real-machine integration checks before declaring a security-sensitive feature finished.
- Compare the feature branch against `main` before merge and confirm only intended files changed.
- Prefer fast-forward/rebase or a clean reviewed merge according to the branch history; never force-update `main` merely to simplify history.
- After integration, verify remote `main`, then remove obsolete feature branches only when they are no longer useful.
- Do not commit generated caches, local machine state, private Bottles prefixes, mounted media, or user-specific absolute paths.

## Near-term roadmap

The next carried-over PC Game Manager capability to implement is the **Redump/TOSEC verifier**, followed by any remaining persistent-configuration work needed to make those verification choices/profile settings durable. Preserve all security invariants above while doing so.
