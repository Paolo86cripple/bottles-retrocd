# Review 0.4.0-rc2

## Status

The architecture and runtime paths are suitable for this release candidate. The rc2 optical-device validation, UDisks2 RO mount, Bubblejail integration and GTK4/Wayland clipboard have all been exercised successfully on the target machine.

## Real-machine validation completed before rc1

- CDEmu temporary device create/load/unload/remove: PASS.
- CDEmu advanced D-Bus options: PASS.
- UDisks2 read-only mount and denied filesystem write: PASS.
- Bubblejail dynamic-whitelist sandbox: PASS (17/17).
- CD → Bubblejail integration: PASS.
- Temporary network ON followed by OFF: PASS.
- Bottles runner persistence in the private Bubblejail HOME: PASS
  (`soda-11.0-8`).

## Review fixes included in rc1

- Direct CDEmu D-Bus backend rather than localized CLI-output parsing.
- Persistent `[network]` rejected; network is transient per launch.
- Bubblejail instance reuse blocked when transient permissions would change.
- RO/RW whitelist canonicalization, overlap/broad-path checks, backup and atomic
  `services.toml` replacement.
- Dynamic CD mount uses `ro-bind` only.
- Raw `/dev/srX` is opt-in and accepted only when it is the CDEmu-mapped Linux SCSI optical block device; the block-layer `ro` bit is diagnostic, not a media-writability guarantee.
- `/dev/sgX` remains optional and disabled by default.
- UDisks2 mount state is verified rather than inferred from command success.
- Worker operations no longer read GTK widget state unsafely from background
  threads.
- Bubblejail runtime-argument capability is checked before use.
- Bottles launch stdout/stderr is retained in the XDG cache directory.
- The Test tab is a cumulative application log for diagnostics and normal operations, and can be copied from the GUI.
- Unit tests cover whitelist update, backup/restore and unsafe path rejection.

## GPU selector feature review

- GPU identity is persisted by PCI address rather than unstable `cardX` numbering.
- The integrated GPU is preferred only as a default-selection heuristic; access-control decisions use the explicitly selected GPU object.
- Mesa selection is applied per launch; the Bubblejail profile is not rewritten for GPU changes.
- Because Bubblejail 0.10.x `direct_rendering` exposes all of `/dev/dri`, runtime bwrap arguments mask `/dev/dri` with a tmpfs and re-bind only the selected GPU's DRM card/render nodes.
- The Vulkan test fails closed if selected DRM nodes are missing, non-selected GPU nodes remain visible, more than one Vulkan GPU is exposed, or vendor/device IDs do not match.
- Real-machine validation passed for both the Ryzen 7 9800X3D integrated GPU and the Radeon RX 9070 XT, and Bottles launches successfully with either selection.
- Deliberately not hardened further: GPU-related sysfs remains visible. Restricting sysfs was rejected for now to avoid unnecessary Mesa/udev compatibility risk.

## Static review

- Python syntax/AST: PASS.
- Unit tests: PASS (19/19, including GPU/settings, bridge, explicit disc sets and multidisc detection).
- `bash -n run-local.sh`: PASS.
- No hardcoded `/home/paolo` paths.
- No `os.system`, `shell=True`, `eval` or dynamic `exec` in the application path.

## Remaining architectural limitations

1. The GTK controller is host-side and has the normal permissions of the logged-in user.
2. libMirage parses optical images host-side, outside the Bottles jail.
3. Runtime network/CD injection depends on Bubblejail `--debug-bwrap-args`; rc2
   checks for support, but this remains an upstream compatibility surface.
4. The whitelist backup is one-generation rather than versioned history.
5. Concurrent external CDEmu management during temporary-device diagnostics can
   race with device-count based cleanup; avoid manipulating CDEmu from another
   client while a diagnostic is running.

## rc2 correction

The rc1 assumption that `/sys/class/block/srX/ro == 1` must hold for CDEmu was rejected by real hardware-path testing: VHBA/CDEmu can expose an optical `sr` block device with block-layer `ro=0` while the loaded image is mounted read-only by UDisks2. rc2 therefore validates device identity (CDEmu mapping + block device + SCSI type 5), keeps the filesystem mount fail-closed RO, and makes raw exposure opt-in.

## Multidisc final review candidate

- Archive fidelity: persistent sets contain only absolute references to original files below `retropc`; no CUE/BIN/image file is copied, renamed, rewritten, touched, or symlinked inside the archive tree. Tests compare file content and mtime before/after metadata save.
- Explicit policy: creating a set starts from the exact selected descriptor (so Disc 1 can always be the anchor). Automatic name grouping is advisory only; live runtime requires an explicit saved set.
- Runtime isolation: cache filesystems are UDisks2-mounted RO on host and individually `ro-bind` mounted into Bubblejail; the broad `/run/media` tree is never exposed. Only the active CDEmu `/dev/srX` is dev-bound for live swap; cache `/dev/srX` nodes and `/dev/sgX` are not exposed.
- Swap safety: bridge neutralizes `/mnt/cdemu` to a real empty directory, active CDEmu media is unload/load swapped on the same validated `/dev/srX`, then the selector moves to the pre-registered RO cache mount. Mapping changes fail closed and trigger rollback.
- Cache cleanup: every cached device mapping is revalidated before unmount/unload; `RemoveDevice` proceeds only while count, suffix ordering, last index, and `/dev/srX` mapping still match GUI-owned devices. Concurrent CDEmu changes abort removal.
- Lifecycle: the selected CDEmu drive is locked during a live session, set metadata editing is frozen, the GUI polls for Bottles exit and cleans cache automatically in a worker thread, and window close is refused while live Bottles still depends on the cache. Cleanup start and completion/failure are written to the cumulative log.
- Config privacy: application config directory is `0700`; `config.toml` and `disc-sets.toml` are `0600`.
- Static checks: Python compile PASS for all application backends, shell syntax PASS, 19/19 unit tests PASS, and no `shell=True`, `os.system`, `eval`, or dynamic `exec` usage found.
- Residual risk: an abnormal GUI crash/kill during live multidisc can leave temporary host-side CDEmu cache drives mounted until manual cleanup or the next recovery mechanism; normal close/exit paths are covered. No further sysfs/device hardening is attempted because it would add compatibility risk without helping multidisc correctness.

