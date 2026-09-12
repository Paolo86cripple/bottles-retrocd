# Bottles RetroCD — Project Rules and Working Context

This file is the persistent operational contract for humans and coding agents working on **Bottles RetroCD**. Read it before non-trivial work and keep it aligned with implementation, tests, packaging, release documentation and validated target behavior.

## Agent operating rules

- The user's interactive shell is **fish**. Commands intended for direct paste must use fish syntax by default (`set VAR value`, not Bash assignment syntax).
- Treat `AGENTS.md` as the repository's persistent source of truth for durable project decisions, architecture/security constraints, validation state, packaging and roadmap.
- Update `AGENTS.md` whenever a durable instruction, security/compatibility decision, release gate, validated behavior, packaging decision or roadmap decision changes.
- Keep code, tests, `AGENTS.md`, README/review/testing docs, packaging metadata and changelog mutually consistent. Investigate divergence instead of assuming one side is current.
- Do not copy hidden platform/system instructions into the repository.
- Prefer focused changes over speculative refactors, especially in security-sensitive paths and released baselines.
- Once a security-sensitive runtime path is CI-green and target-validated, do not refactor it for aesthetics without a concrete reason and relevant regression tests.
- Never force-update `main` merely to simplify history.
- Packaging/release work still requires the specified real-machine gates; CI alone is not sufficient.
- No automatic merge. Explicit owner approval is required before merging non-trivial packaging/release/security-sensitive work.
- For architecture, sandbox/security, compatibility, lifecycle/device ownership and release-critical work, use maximum review effort. Before completion perform an adversarial second pass covering failure modes, rollback/cleanup, privilege/filesystem leaks, races, and consistency between code, tests, docs and target-machine evidence.

## Mission and scope

Bottles RetroCD is a GTK4 controller for running **Windows retro PC games** with native Bottles inside the existing Bubblejail instance `Bottles`, with CDEmu/libMirage/UDisks2 integration for legacy optical media and read-only Redump/TOSEC verification.

In scope:

- Bottles/Wine execution inside Bubblejail;
- safe per-launch GPU selection and strict DRM/Vulkan node isolation;
- native Wayland plus explicit XWayland fallback;
- CDEmu/libMirage optical-media handling and verified UDisks2 RO mounts;
- safe multidisc/disc swapping;
- Redump/TOSEC verification and read-only protection scanning;
- standard gamepad support with exact-node isolation and runtime disconnect/reconnect;
- persistent configuration and diagnostics that positively prove sandbox behavior;
- Arch/CachyOS packaging and release distribution;
- preservation-oriented compatibility/emulation for obsolete Windows optical copy-protection systems, provided this does not weaken the Bubblejail boundary.

Out of scope unless a future concrete requirement changes the decision: DOS management (use DOSBox-Staging), ScummVM integration, console emulation, Steam management, or revival of a generic all-era PC Game Manager.

## Preservation / compatibility philosophy

- Prefer original executables, original optical-media behavior and accurate compatibility/emulation over executable replacement.
- A No-CD/cracked executable must **not** become the normal solution to legacy copy-protection compatibility.
- Legacy DRM work should reproduce or satisfy obsolete optical verification as natively as practical through Wine, CDEmu/libMirage or dedicated license-compatible compatibility components.
- A userspace compatibility shim is acceptable when it replaces an obsolete/insecure Windows protection driver interface **while the original-disc/media authentication still remains part of the launch path**.
- Do not patch/unpack the game executable merely to remove the protection as the normal implementation path.
- Study/reuse existing open-source projects where technically appropriate and license-compatible instead of reinventing solved components.
- Compatibility layers remain optional where possible and must never weaken Bubblejail merely for convenience.

## Released baselines

### 0.4.0

- Stable app ID: `io.github.Paolo86cripple.BottlesRetroCD`.
- PR #3 runtime/security baseline: `8c75163168164fef896041c6b1a62ddac19b3faf`.
- PR #4 packaging/release merge: `15b1e0acc61d61978051d49d97bd17cb97efb348`.
- Immutable annotated tag `0.4.0` points to `15b1e0acc61d61978051d49d97bd17cb97efb348`.
- Final historical package: `bottles-retrocd 0.4.0-3`.
- Full real-machine security/compatibility and package acceptance gates passed.

### 0.4.1 — current stable release

- PR #5 `0.4.1: compatibility-preserving hardening (Phases A-E)` merged to `main` as `a1879967f40aa13457f30494639b737fbd4a0d66`.
- Post-merge `main` CI #530: PASS.
- Annotated tag `0.4.1` points exactly to merge commit `a1879967f40aa13457f30494639b737fbd4a0d66`; treat the tag as immutable.
- GitHub Release `Bottles RetroCD 0.4.1` is published.
- Final Arch/CachyOS artifact: `bottles-retrocd-0.4.1-1-x86_64.pkg.tar.zst`.
- Validated artifact SHA-256: `001b2423b1e5b60f73e82eb6a0ec9c69bd9885316de5bcf2ad2d7f85b64deb8b`.
- Final package payload source pin: `3c842c0c5f740a041c4f2de4edcdb899691ccbd2`.
- Clean build: 251/251 tests PASS.
- Package metadata/file list PASS; all package-owned paths are under `/usr`.
- Installed runtime launch PASS with GPU and Retro Optical pre/post proofs.
- Exact-artifact uninstall preservation PASS: config, Bubblejail state and verifier state unchanged.
- Exact artifact reinstall PASS; `pacman -Qkk`: 65 total files, 0 altered files.
- 0.4.1 is now a frozen stable baseline except for narrowly scoped maintenance/security fixes.

## Architectural baseline

- Reuse the existing Bubblejail instance named `Bottles`; do not create a second persistent instance.
- Bottles/Wine/runners/DXVK/runtimes/prefixes live in Bubblejail's private HOME.
- GTK controller, CDEmu/libMirage control, DAT updater controller and gamepad hotplug helpers are host-side as the logged-in user.
- Archive verification/protection parsing runs in a dedicated bubblewrap worker; official DAT updates run in a separate networked bubblewrap worker.
- Bubblejail remains the Bottles/Wine security boundary. Dedicated bubblewrap workers provide least-privilege boundaries for verifier/scanner and official DAT updates.
- CDEmu is controlled through its D-Bus API model; `cdemu-client` is optional.
- UDisks2 mount state must be verified, not inferred from command success.
- Archive root is explicit persistent configuration; no release-time user-specific storage path may be hardcoded.
- Local-tree entrypoint is `run-local.sh`; installed entrypoint is `/usr/bin/bottles-retrocd`, delegating to `/usr/lib/bottles-retrocd/run-local.sh`.

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
- Historical archive migration stores only the path and never moves/copies/renames/rewrites/touches archive data.
- Persist stable identifiers, not volatile kernel numbering.

### Network

- Bottles network OFF by default.
- Persistent `[network]` in Bubblejail config is forbidden and must fail validation.
- Network may be enabled only transiently for a selected launch.
- Verifier/scanner worker has an unshared network namespace and may see at most loopback.
- Official DAT updater uses its own networked bubblewrap worker and remains HTTPS-only to explicit official hosts with redirect revalidation.
- Legacy optical DRM support must not gain network access merely to avoid a local disc check.
- Online-activation DRM is a separate problem from optical-disc emulation. Do not fake proprietary activation servers or silently add network permissions; treat dead activation infrastructure as a separate reviewed compatibility case.

### Display / preferences

- Persistent display choices: Auto, native Wayland, XWayland.
- Auto is neutral; native Wayland only where supported by the selected runner.
- XWayland is a compatibility fallback and must not broaden filesystem/network/GPU/optical access.
- Forced XWayland requires existing Bubblejail `x11` + `wayland`; fail closed rather than adding permissions silently.
- Bottles global settings use `GSETTINGS_BACKEND=keyfile` inside private HOME, not host dconf.
- `[gnome_toolkit] dconf_dbus` must remain false; effective `xdg-dbus-proxy` policy must remain filtered with no dconf grants.
- The 0.4.1 pre-launch guard rejects dconf exposure before Bottles launch; runtime proxy audit remains the independent post-launch proof.

### GPU

- Detect dynamically; persist stable PCI address, never `cardX` numbering.
- No implicit Mesa/default fallback when selected GPU cannot be proven.
- Validate PCI/vendor/device/driver plus exact DRM card/render nodes.
- Mask broad `/dev/dri` and bind back only selected card/render nodes.
- Pre/post launch proofs must positively establish selected GPU visibility and non-selected GPU absence.
- Post-launch proof failure terminates the exact launch process group.

### Retro Optical / CDEmu

- Raw `/dev/srX` is optional/OFF by default; if exposed it must exactly match CDEmu mapping and Linux SCSI optical type 5.
- `/sys/class/block/srX/ro` is diagnostic only; verified UDisks2 filesystem RO state is authoritative.
- `/dev/sgX` is broader SCSI access, explicit and OFF by default.
- CDEmu D-Bus and `/dev/vhba_ctl` stay hidden from Bottles/Wine.
- No broad storage-tree exposure for optical compatibility.
- CDEmu mutations are serialized with the inter-process flock and private ownership journal.
- Stale-cache recovery may remove only the exact owned contiguous appended suffix after strict revalidation; ambiguity/external activity is fail-closed.
- Live multidisc must preserve the same validated active `/dev/srX`, expose only the active drive, keep cached drives/sg hidden and keep cache mounts read-only.

### Standard gamepad / input

- Standard controller path uses Bubblejail `[joystick]`.
- Never expose all `/dev/input`, keyboard/mouse event nodes or `/dev/hidraw*` for the standard path.
- Host detection accepts supported `jsX` plus matching evdev `eventX`; node numbers may change across reconnect.
- Runtime hotplug revalidates exact current nodes/minimal sysfs, emits synthetic libudev transitions and fails closed on ambiguity.
- No sudo/root/additional groups/persistent udev permission changes/host capabilities for normal hotplug.

## Multidisc rules

- Never copy/rename/rewrite/modify/touch/symlink original archive images to create a set.
- Persistent sets reference original descriptors under configured archive.
- Filename grouping/autodetection is advisory only and never silently persisted as truth.
- Live multidisc requires an explicit saved set.
- Cache filesystems are UDisks2 RO and individually `ro-bind` exposed.
- Only active CDEmu `/dev/srX` may be exposed; cached drives and `/dev/sgX` must not leak.
- Revalidate device count/order/mapping before cleanup; refuse ambiguous removal during external CDEmu activity.
- Abnormal termination is covered by ownership-journal recovery; cleanup is exact LIFO and never guesses ownership.

## Redump / TOSEC verifier rules

- Archive verification and protection scanning execute in a dedicated bubblewrap worker, never directly in the GTK/CLI host process.
- Application code, authorized archive and existing catalog are RO; only verifier hash cache is RW.
- Worker has private HOME/tmp, unshared network namespace, minimal `/dev`, no host `/proc`, `/sys` or runtime state.
- Fail closed if `bwrap` is missing/untrusted, layouts overlap protected trees, inputs escape authorized archive or positive attestation fails.
- Canonicalize CUE/TOC references below authorized archive and reject traversal/absolute/Windows/UNC escapes.
- Hash CRC32/MD5/SHA1 in one streaming pass with pre/post stat and robust cache identity.
- Build catalog in staging, run SQLite integrity checks and reject empty/unverifiable indexes.
- `MATCH 1:1` requires one complete unique game; partial is `MISMATCH`; equivalent complete records remain `AMBIGUOUS`.
- Official DAT updates run in a separate networked bubblewrap worker; archive must be invisible and only verifier data/catalog/cache may be RW.
- Protection scanner is read-only, bounded, keeps the 64 MiB per-directory-extent limit, streams raw signatures with overlap and never overrides cryptographic matching.

## Legacy optical DRM compatibility — ACTIVE post-0.4.1 work

Focused research branch: `research/legacy-optical-drm`.

### First target

- First real test title: **Freelancer, Italian retail edition**.
- Public compatibility databases identify Freelancer retail as **SafeDisc 2.7**; historical version lists commonly identify the US retail build as SafeDisc `2.70.030`.
- Do **not** assume the Italian disc is byte-for-byte the same protection revision. Confirm the actual image/disc through the existing read-only scanner, Redump metadata where available, executable/file signatures and observed runtime behavior before making a compatibility decision.
- Freelancer is a good initial test because it is a 32-bit Windows 98SE/ME/2000/XP-era title and its retail copy protection is representative of SafeDisc 2.x while the game itself is otherwise a conventional Direct3D 8 title.

### Protection families to cover

The research scope is broader than SafeDisc. At minimum investigate the optical protection families represented in Redump/period PC software and in the current scanner:

- SafeDisc 1–4;
- SecuROM classic disc-check generations, including subchannel and DPM variants;
- LaserLock;
- StarForce optical-disc variants;
- TAGES disc-check/Twin-Sector variants (online activation handled separately);
- VOB ProtectCD / ProtectDVD and ProtectDISC;
- CD-Cops / DVD-Cops;
- CopyLok / CodeLok;
- Ring PROTECH / ProRing;
- CD-Lock;
- Bitpool;
- DiscGuard / CD-Guard;
- SmartE and other Redump-listed optical families when a real title requires them.

Scanner coverage should eventually be reviewed against Redump's protection vocabulary, but detection work remains read-only and must not be confused with runtime emulation support.

### Native compatibility strategy hierarchy

Prefer solutions in this order, subject to actual protection requirements:

1. **Existing Wine + faithful optical emulation.** First determine whether the original protection already works when the correct 32-bit/XP-era Wine environment and a sufficiently faithful CDEmu image are used.
2. **CDEmu/libMirage media emulation.** Use existing support for raw main-channel/subchannel data, bad-sector emulation, DPM emulation, transfer-rate emulation and device identity where the protection checks physical-disc characteristics. Prefer adding generic accurate optical behavior upstream-style rather than game-specific hacks.
3. **Userspace protection-driver compatibility shim.** For obsolete Windows drivers such as SafeDisc `secdrv.sys`, prefer a narrowly scoped userspace replacement of the expected interface/IOCTL behavior that still requires the original media check. SafeDiscShim is a concrete GPL-3.0-or-later reference candidate and must be evaluated for Wine compatibility before any integration decision.
4. **Targeted Wine compatibility work.** If Wine is missing a generic NT/device/SCSI behavior required by several legitimate original-disc checks, consider a clean, upstreamable compatibility fix rather than embedding a title-specific bypass.
5. **Targeted CDEmu/libMirage extension.** If a required optical behavior is missing but can be represented safely in the CDEmu model, prefer a generic, format-aware implementation with tests and no broader device exposure.
6. **Reference VM/real Windows only as an oracle.** A Windows XP VM or real legacy machine may be used to observe legitimate original-disc behavior and compare traces, but it is not the desired Bottles RetroCD runtime solution.

Explicitly rejected as the normal path:

- distributing or automatically applying No-CD/cracked executables;
- executable unpacking/patching whose purpose is to remove the disc check;
- installing obsolete DRM kernel modules into the **Linux host kernel**;
- exposing broad `/dev/sg*`, broad storage trees, host D-Bus or other privileged host surfaces merely to satisfy DRM;
- disabling the validated Bubblejail boundary or running Bottles/Wine unsandboxed for compatibility.

### Media/image fidelity rules for DRM research

- Preserve archive originals byte-for-byte; research never rewrites the source image.
- Do not assume ISO is sufficient. ISO omits full raw sector/subchannel information and cannot represent several protection-relevant error/topology properties.
- CUE/BIN can preserve raw main-channel sectors but may still be insufficient for protections that depend on subchannel or DPM/topology data.
- CCD/IMG/SUB, TOC/BIN, MDS/MDF, B5T/B6T and other libMirage-supported formats may carry additional protection-relevant information. MDS/MDF and B6T are especially relevant when DPM is required.
- CDEmu currently exposes configurable DPM and bad-sector emulation; use them only when the source image actually contains or justifies the relevant information.
- Never synthesize a successful authentication result merely because a title is known to use a protection. Positive behavior must be derived from the original image/disc evidence or from a narrowly reviewed compatibility implementation of the original interface.

### SafeDisc / Freelancer initial experiment order

For Freelancer ITA, proceed diagnostically rather than jumping directly to a shim:

1. verify the exact image with Redump/TOSEC where possible and run the existing protection scanner;
2. identify exact SafeDisc generation/revision from disc/executable evidence;
3. record image format and whether it contains full raw sectors/subchannel/DPM metadata;
4. install from the CDEmu device through the normal read-only Retro Optical path;
5. attempt launch with the current preferred runner in a 32-bit/XP-compatible bottle configuration without compatibility shim;
6. capture the exact failure boundary: media not found, SafeDisc loader/API check, `secdrv` service/driver failure, SCSI/device query mismatch, API-entry heuristic, or unrelated game compatibility issue;
7. only then test a SafeDiscShim-style userspace compatibility path in an isolated feature branch, without changing host kernel drivers or relaxing Bubblejail;
8. require the original mounted image/disc to remain necessary for success; a launch that succeeds with no media is evidence that the experiment crossed into a protection-removal path and is not acceptable as the default implementation.

### Security gate for future DRM implementations

Any legacy DRM implementation must demonstrate all of the following before merge:

- no new persistent host privilege;
- no DRM-provided Linux kernel module;
- no broad raw SCSI/storage access beyond an exact, justified device surface;
- no weakening of GPU, gamepad, D-Bus, HOME, network or archive isolation;
- original archive image remains read-only and untouched;
- compatibility component is optional/fail-closed and can be disabled per launch/profile;
- precise cleanup/rollback if a transient device/shim is created;
- tests distinguish media-emulation failure from Wine/protection-driver failure;
- real-machine validation on at least one protected title plus a non-protected regression title.

## Coding practices

- Prefer Python stdlib where practical.
- Application subprocesses use argv lists; no `os.system`, `shell=True`, `eval` or dynamic `exec` in app paths.
- Never interpolate user-controlled paths into unquoted shell commands.
- GTK widget access from workers is marshalled to the GTK main thread.
- Bubblejail config writes are syntax-checked, backed up and atomic where applicable.
- Detect Bubblejail runtime capabilities before depending on them.
- Keep launch stdout/stderr in XDG cache/logs.
- Do not hardcode user HOME/storage paths.
- Favor fail-closed identity/mapping decisions.

## 0.4.1 durable validation record

- Phase A verifier/scanner isolation: PASS; Discworld Noir Disc 1 remained Redump `MATCH 1:1`.
- Phase B official DAT updater isolation: PASS; validated Redump catalog 61118 games / 199470 ROM records.
- Phase C CDEmu ownership/recovery: PASS, including 3-disc swap/cleanup and SIGKILL recovery.
- Phase D runtime D-Bus/socket/process audit: PASS; dconf blocked, keyfile persistence validated, minimal bus/device surface retained.
- Phase E consolidated target regression: `PASS=17 FAIL=0 WARN=0`; Discworld non-live path PASS; Xbox One S exact-node disconnect/reconnect PASS; verifier/update revalidation PASS.
- Final static dconf guard: PASS and CI-green.
- Final exact package artifact: build/metadata/install/runtime/uninstall-preservation/reinstall/integrity PASS.
- PR #5 merged; post-merge CI #530 PASS; tag/release 0.4.1 published.

## Arch / CachyOS packaging contract

- `packaging/arch/PKGBUILD` and tracked `packaging/arch/.SRCINFO` must remain synchronized.
- Package payload lives under `/usr/lib/bottles-retrocd`; launcher under `/usr/bin/bottles-retrocd`; metadata/docs/licenses under app-owned `/usr/share` locations.
- No package-owned files under `/home`, `/run`, `/mnt`, `/media`, `/dev`, `/sys` or user data/config locations.
- Install/remove scripts never create/reset/delete Bubblejail instances, private HOME, prefixes, RetroCD config, archive or verifier data.
- Uninstall removes only package-owned `/usr` files and preserves user state.
- 0.4.1 historical package metadata is `pkgver=0.4.1`, `pkgrel=1`, exact payload source `3c842c0c5f740a041c4f2de4edcdb899691ccbd2`.
- Direct dependencies remain `python`, `python-gobject`, `gtk4`, `bottles`, `bubblejail`, `cdemu-daemon`, `libmirage`, `udisks2`, `vulkan-tools`, `iproute2`, `util-linux` unless a future reviewed change intentionally updates them.
- Do not hard-depend on `vhba-module`, `vhba-module-dkms` or `cdemu-client`.
- `sudo` remains optional for Componenti update; `pciutils` remains optional diagnostic enrichment.
- Regenerate `.SRCINFO` after packaging metadata/source-pin changes and rerun CI.

## Git / release workflow

- `main` is the tested integration branch.
- Non-trivial work belongs on focused branches.
- Keep commits focused; compare branch with `main` before merge; never force-update `main` for convenience.
- Do not commit generated `src/`, `pkg/`, built package archives, caches, private instance state, mounted media, DAT downloads or user-specific paths.
- Published tags are immutable. `0.4.0` and `0.4.1` must never be moved.
- Future fixes/releases use new branches, version/package revisions and tags; never rewrite published release history.

## Post-0.4.1 roadmap, agreed order

0. **0.4.1 hardening/release — COMPLETE.** Stable release published and frozen baseline established.
1. **Native legacy optical DRM compatibility/emulation — ACTIVE.** First concrete test target: Freelancer Italian retail (expected SafeDisc 2.7, exact revision to verify). Explore SafeDisc, SecuROM, LaserLock, StarForce, TAGES, ProtectCD/ProtectDISC, CD-Cops, CopyLok/CodeLok, Ring PROTECH, CD-Lock, Bitpool, DiscGuard, SmartE and other real optical families. Preserve original-media authentication; no No-CD normal path; keep optional/fail-closed without broader sandbox permissions.
2. **Legacy DirectX compatibility layer/manager.** Optional/OFF-by-default DirectX 5–9 compatibility support after optical DRM work and before shaders.
3. **libRashader + Slang shaders.** Optional/OFF by default per game/bottle after the compatibility foundation is stable.

Post-release maintenance backlog:

- consolidate release identity constants into one shared module after focused regression review;
- retire/remove the old direct `mutate_instance()` helper path if still unused;
- consider deduplicating restrictive real-sentinel staging between lifecycle/final-wrapper layers.

None of these may weaken the validated Bubblejail boundary or become mandatory without a concrete reviewed reason.

## Documentation references

Keep aligned as applicable: `README.md`, `README-TESTING.md`, `REVIEW.md`, `docs/SECURITY-REVIEW.md`, `docs/TESTING.md`, `docs/ROADMAP.md`, `docs/0.4.1-PHASE-D-RUNTIME-AUDIT.md`, `CHANGELOG.md`, and `packaging/arch/README.md`.
