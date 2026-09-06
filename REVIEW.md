# Review 0.4.0-rc1

## Status

The architecture and the previously tested runtime paths are suitable for a
release candidate. The project is not being called stable yet because rc1 adds
one new fail-closed check: the kernel must report the raw `/dev/srX` device as
read-only before the GUI exposes it to Wine. Re-run the CDEmu and integrated CD
tests once on the target machine before promoting rc1 to stable.

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
- Raw `/dev/srX` exposure fails closed unless the kernel reports read-only.
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
3. Runtime network/CD injection depends on Bubblejail `--debug-bwrap-args`; rc1
   checks for support, but this remains an upstream compatibility surface.
4. The whitelist backup is one-generation rather than versioned history.
5. Concurrent external CDEmu management during temporary-device diagnostics can
   race with device-count based cleanup; avoid manipulating CDEmu from another
   client while a diagnostic is running.
