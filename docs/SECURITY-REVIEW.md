# Security / code review — Bottles RetroCD 0.4.0

## Result

The 0.4.0 pre-packaging candidate preserves the intended fail-closed Bottles/Wine filesystem, network, optical and GPU boundaries. Previously required target GPU/optical/display validation has been completed; the remaining pre-merge machine check is the portable archive-root migration/selector and real-sentinel integration test.

## Bubblejail / filesystem / network

- Bottles/Wine runs in the dedicated Bubblejail instance with private HOME.
- Persistent `[network]` is rejected; network is transient and OFF by default.
- Whitelist paths are canonicalized and validated before writing.
- Real HOME, archive root/ancestors, overlapping mounts and broad system roots are rejected.
- `services.toml` is syntax-checked, backed up and atomically replaced.
- Dynamic optical/cache mounts use `ro-bind`.
- Isolation tests create real temporary host sentinels and prove they are hidden rather than assuming a named host path exists.
- Runtime Bubblejail argument support is checked before launch policy depends on it.
- Bottles launch output remains available under XDG cache storage.

## Display / settings isolation

- Auto, native Wayland and XWayland are persistent display choices.
- XWayland removes native Proton Wayland opt-ins and reports an X11 session to Wine/Bottles while keeping Wayland available to the Bottles GTK UI.
- Forced XWayland requires existing Bubblejail `x11` + `wayland` services and never adds broader permissions automatically.
- Bottles global preferences use `GSETTINGS_BACKEND=keyfile`, persisting inside the private Bubblejail HOME instead of writing the host dconf database.
- Target validation confirms native Wayland and XWayland both launch; Discworld Noir enters fullscreen directly through XWayland with working audio.

## GPU fail-closed path

- GPU identity is stable PCI identity, not `cardX` numbering.
- Bottles launch is refused when no valid GPU is available; implicit Mesa default is not accepted.
- PCI address, vendor/device IDs, kernel driver and DRM node names are validated.
- Selected `cardN` and `renderD*` nodes must be live character devices before launch.
- Broad `/dev/dri` is masked; only selected GPU DRM nodes are rebound.
- Pre-launch proof verifies `DRI_PRIME`, selected-node presence, non-selected-node absence, exactly one Vulkan GPU and vendor/device identity.
- Post-launch proof is injected into the already-running Bubblejail helper path and proves effective DRM/Vulkan isolation.
- Missing proof markers fail closed.
- If post-launch helper injection/output/proof fails, the exact captured Bubblejail process group is terminated.
- Test Vulkan uses the same strict pre-launch validator.
- Target validation passed on both available AMD GPUs.

## Optical / multidisc

- CDEmu uses D-Bus; `cdemu-client` is optional.
- UDisks2 mount state is verified rather than inferred from command success.
- Raw `/dev/srX` is opt-in and must match the CDEmu mapping plus Linux SCSI optical type 5.
- Block-layer `ro` is diagnostic only; the mounted filesystem's verified RO state is authoritative.
- `/dev/sgX` remains optional and OFF by default.
- CDEmu D-Bus and `/dev/vhba_ctl` are not exposed to Bottles/Wine.
- Live multidisc requires an explicit saved set and keeps cache devices host-side.
- Cache cleanup revalidates ownership/count/order/mapping before removal.
- Target validation includes RO mounts, raw optical, explicit `/dev/sgX`, live multidisc and cleanup.

## Redump/TOSEC verifier and scanner

- Dump files are opened read-only and never mounted or executed by the verifier/scanner.
- CUE/TOC traversal and absolute references are rejected.
- Hashing streams CRC32/MD5/SHA1 with before/after file identity checks and persistent cache invalidation.
- Logiqx DATs are indexed incrementally into SQLite; `MATCH 1:1` requires one complete unique game record.
- Official updater URLs are HTTPS-only with explicit host allow-list and redirect revalidation.
- DAT updates use bounded download/ZIP handling, staging, integrity checks and rollback.
- ZIP traversal and symlinks are rejected.
- ISO/Joliet scanning bounds depth, entries, samples and directory extents.
- Scanner evidence remains heuristic and cannot override cryptographic DAT verification.

## Automated evidence

Current pre-packaging branch CI passes:

- compilation of every Python module, including `display_backend.py`;
- **130/130 unit tests** with `ResourceWarning` promoted to errors;
- `bash -n run-local.sh`;
- source scan rejecting `os.system`, `shell=True`, `eval` and dynamic `exec` patterns.

## Remaining pre-merge target check

1. confirm legacy/current archive root is stored correctly in schema-2 config without modifying dump files;
2. reselect the archive in the GUI and prove persistence after restart;
3. run Test Bubblejail and require the real temporary host sentinel hidden;
4. run Test CD → Bubblejail and require the integration sentinels hidden plus RO policy PASS;
5. confirm one normal Bottles launch retains GPU and Retro Optical pre/post PASS;
6. repeat the working XWayland Discworld Noir launch.

## Remaining architectural limitations

1. The controller, verifier and CDEmu/libMirage are host-side and have the normal permissions of the logged-in user.
2. Native/XML/ZIP/image parsers still process untrusted bytes host-side, although inputs and resource use are bounded where practical.
3. Runtime policy injection depends on supported Bubblejail runtime arguments and helper behavior; incompatibility intentionally fails closed.
4. Whitelist backup is one-generation, not a history.
5. Concurrent external CDEmu management should be avoided during ownership-sensitive diagnostics/live cache operations.
6. Abnormal GUI/process termination can leave temporary live-multidisc CDEmu cache devices until recovery/manual cleanup.
7. XWayland is a compatibility fallback and must never justify broader sandbox access.
