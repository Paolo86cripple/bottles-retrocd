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
- Diagnostic log can be copied from the GUI.
- Unit tests cover whitelist update, backup/restore and unsafe path rejection.

## Static review

- Python syntax/AST: PASS.
- Unit tests: PASS.
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
