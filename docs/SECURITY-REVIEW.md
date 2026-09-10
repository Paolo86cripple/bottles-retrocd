# Security / code review — Bottles RetroCD 0.4.0

## Result

**PASS — no pre-packaging security blocker found.**

The final PR #3 review and target-machine acceptance preserve the intended fail-closed Bottles/Wine filesystem, network, optical, GPU and standard-gamepad boundaries. The real-machine pre-packaging gate is complete.

## Bubblejail / filesystem / network

- Bottles/Wine runs in the dedicated Bubblejail instance with private HOME.
- Persistent `[network]` is rejected; network is transient and OFF by default.
- Whitelist paths are canonicalized and validated before writing.
- Explicit archive-root/subdirectory RO shares are allowed. RW access anywhere within the archive, ancestors in either mode, real HOME, overlapping mounts and broad system roots are rejected. Whitelist writes and existing-profile audits enforce the same canonicalized policy.
- `services.toml` is syntax-checked, backed up and atomically replaced.
- Dynamic optical/cache mounts use `ro-bind`.
- Isolation tests create real temporary host sentinels and prove they are hidden rather than assuming a named host path does not exist.
- Runtime Bubblejail argument support is checked before launch policy depends on it.
- Bottles launch output remains available under XDG cache storage.

Final target Test Bubblejail result: **PASS=17 FAIL=0 WARN=0**. The real non-whitelist sentinel was hidden, the private HOME was writable, real HOME/`.ssh` remained hidden, configured RW/RO semantics were correct, and base networking exposed only loopback.

## Archive-root portability

- Config schema 2 persists `gpu_pci`, `display_backend` and `archive_root`.
- Existing installations migrate the historical archive path only when it actually exists; migration stores only the path and does not move/rename/rewrite dump data.
- New installations have no machine-specific removable-storage default.
- Config directory/file permissions are `0700`/`0600`.
- Target GUI re-selection persisted after restart.
- Pre/post archive metadata signatures were identical after re-selection, confirming no change to dump names/sizes/mtimes.

## Display / settings isolation

- Auto, native Wayland and XWayland are persistent display choices.
- XWayland removes native Proton Wayland opt-ins and presents an X11 session to Wine/Bottles while keeping Wayland available to the Bottles GTK UI.
- Forced XWayland requires existing Bubblejail `x11` + `wayland` services and never adds broader permissions automatically.
- Bottles global preferences use `GSETTINGS_BACKEND=keyfile`, persisting inside the private Bubblejail HOME instead of writing host dconf.
- The final Discworld Noir acceptance session used XWayland successfully with audio and the previously validated fullscreen behavior.

## GPU fail-closed path

- GPU identity is stable PCI identity, not `cardX` numbering.
- Bottles launch is refused when no valid GPU is available; implicit Mesa default is not accepted.
- PCI address, vendor/device IDs, kernel driver and DRM node names are validated.
- Selected `cardN` and `renderD*` nodes must be live character devices before launch.
- Broad `/dev/dri` is masked; only selected GPU DRM nodes are rebound.
- Pre-launch proof verifies `DRI_PRIME`, selected-node presence, non-selected-node absence, exactly one Vulkan GPU and matching vendor/device identity.
- Post-launch proof is injected into the already-running Bubblejail helper path and proves effective DRM/Vulkan isolation.
- Missing proof markers fail closed; post-launch proof failure terminates the exact captured launch process group.
- Test Vulkan uses the same strict pre-launch validator.
- Target validation passed on both available AMD GPU paths.

Final XWayland/Discworld session again produced both GPU pre- and post-launch PASS proofs with all other known GPUs hidden.

## Retro Optical / CDEmu / multidisc

- CDEmu uses D-Bus; `cdemu-client` is optional.
- UDisks2 mount state is verified rather than inferred from command success.
- Raw `/dev/srX` is opt-in and must match the CDEmu mapping plus Linux SCSI optical type 5.
- Block-layer `ro` is diagnostic only; the verified mounted filesystem RO state is authoritative.
- `/dev/sgX` remains optional and OFF by default.
- CDEmu D-Bus and `/dev/vhba_ctl` are not exposed to Bottles/Wine.
- Live multidisc requires an explicit saved set and keeps cache devices host-side.
- Cache cleanup revalidates ownership/count/order/mapping before removal.

Final CD → Bubblejail acceptance created a real temporary `/dev/sr1`, validated it as SCSI optical type 5, verified the host mount RO, proved two real non-whitelist integration sentinels hidden, proved `/mnt/cdemu` visible but non-writable, and cleaned the temporary drive. The final Discworld Noir session then produced Retro Optical pre/post PASS with `/mnt/cdemu=RO`.

## Standard gamepad / hotplug

- Standard controller access uses Bubblejail `[joystick]`; there is no broad `/dev/input` share.
- `/dev/hidraw*` stays hidden for 0.4.0.
- Host detection accepts current `jsX` plus matching evdev `eventX` siblings; node numbers are not hardcoded.
- Initial monitor activation is deliberately non-destructive and reports `udev=initial-static`.
- Physical disconnect/reconnect rebuilds only the exact current controller nodes plus matching minimal sysfs and emits matching libudev notifications, reporting `udev=notified`.
- Runtime reconciliation re-probes the jail and requires `sysfs=exact`, exact input nodes and `hidraw=hidden`.
- The namespace entry helper determines the mount namespace owner with `NS_GET_USERNS`, stages detached exact mounts in a private mount namespace, revalidates pinned device/sysfs identity, then enters the active mount/network namespaces.
- No sudo/root/new groups/persistent host udev changes are required.

The physical Xbox One S initial/disconnect/reconnect cycle and the final XWayland launch both passed. The final launch again showed `event9 + js0`, writable, `sysfs=exact`, `udev=initial-static`, `hidraw=hidden`.

## Redump/TOSEC verifier and scanner

- Dump files are opened read-only and never mounted or executed by the verifier/scanner.
- Descriptor traversal/absolute references are rejected.
- Hashing streams CRC32/MD5/SHA1 with before/after file identity checks and persistent cache invalidation.
- Logiqx DATs are indexed incrementally into SQLite; `MATCH 1:1` requires one complete unique game record.
- Official updater URLs are HTTPS-only with explicit host allow-list and redirect revalidation.
- DAT updates use bounded download/ZIP handling, staging, integrity checks and rollback.
- ZIP traversal/symlinks are rejected.
- ISO/Joliet/raw scanning is bounded and evidence-only; scanner output cannot override cryptographic DAT matching.
- Real-source immutability validation has passed.

## Automated evidence

Current release-candidate regression gate:

- **151/151 unit tests PASS**;
- Python compilation covers every application module, including the final GUI wrapper, `gamepad_hotplug.py`, `gamepad_ns_entry.py` and `gamepad_ns_helper.py`;
- `ResourceWarning`-as-error PASS;
- `run-local.sh` shell syntax PASS;
- unsafe execution scan rejecting `os.system`, `shell=True`, `eval` and dynamic `exec` PASS;
- latest CI before final documentation alignment remained green; documentation-only follow-up commits must remain green before merge.

## Final PR review findings

No release blocker was found in the runtime diff. Two low-risk cleanup items are deliberately deferred rather than reopening already target-validated code:

1. `gamepad_ns_helper.py` still contains the earlier direct CLI/`mutate_instance()` entry path. The application runtime does **not** route through it; `gamepad_hotplug.py` routes through `gamepad_ns_entry.py`. The old path failed closed on the target and does not provide a permissive fallback. Removing/consolidating it is post-release cleanup.
2. The CD integration sentinel setup exists in both the lifecycle layer and final wrapper, causing redundant temporary sentinel staging. Both paths are restrictive and the real target test passed; consolidation is post-release cleanup, not a 0.4.0 security change.

Neither item broadens device/filesystem access or bypasses a fail-closed check.

## Remaining architectural limitations

1. The controller, gamepad helpers, verifier and CDEmu/libMirage are host-side and run with the logged-in user's permissions.
2. Native/XML/ZIP/image parsers still process untrusted bytes host-side, although inputs/resource use are bounded where practical.
3. Runtime policy injection depends on supported Bubblejail runtime arguments/helper behavior; incompatibility intentionally fails closed.
4. Whitelist backup is one-generation, not a history.
5. Concurrent external CDEmu management should be avoided during ownership-sensitive diagnostics/live cache operations.
6. Abnormal GUI/process termination can leave temporary live-multidisc CDEmu cache devices until recovery/manual cleanup.
7. XWayland is a compatibility fallback and must never justify broader sandbox access.
8. Some games enumerate controllers only at startup; RetroCD can prove the Wine-visible transition but cannot force application-level re-enumeration.

## Merge criterion

The technical pre-packaging criterion is satisfied. Merge PR #3 only after its final documentation-only CI is green and after the repository owner explicitly chooses to merge. Packaging then begins from the merged `main` baseline.
