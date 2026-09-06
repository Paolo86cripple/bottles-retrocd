# Security / code review — 0.4.0-rc2

## Result

The architecture is suitable for an RC after successful real-machine testing.
No known issue currently defeats the intended Bottles/Wine filesystem or
network boundary.

## Reviewed and hardened

- Bubblejail instance reuse is blocked when changing transient permissions.
- Persistent `[network]` is rejected.
- Whitelist paths are canonicalized and validated before writing.
- Real HOME, Data root/ancestors, overlapping mounts and broad system roots are rejected.
- `services.toml` is syntax-checked, backed up and atomically replaced.
- Image enumeration does not follow directory symlinks outside `retropc`.
- Subprocess commands use argv lists; no user path is interpolated into a shell
  except test snippets where paths are shell-quoted.
- CDEmu uses D-Bus instead of localized CLI-output parsing.
- UDisks2 mount state is verified rather than trusted from command success alone.
- Dynamic mount is always `ro-bind`.
- Raw `/dev/srX` exposure is opt-in and validated against the CDEmu D-Bus mapping, Linux block-device type and SCSI optical type 5. The block-layer `ro` bit is diagnostic only.
- `/dev/sgX` remains optional and OFF by default because it grants a broader SCSI interface.
- GTK widget state used by worker operations is marshalled back to the GTK main thread.
- Bubblejail runtime-argument support is checked before using `--debug-bwrap-args`.
- Bottles launch output is retained under the XDG cache directory instead of discarded.

## Real-machine validation completed for rc2

- CDEmu/UDisks2 test: PASS.
- Bubblejail sandbox test: PASS (17/17 on the dynamic-whitelist build).
- CD → Bubblejail test: PASS.
- Bottles runner persistence with temporary network ON then OFF: PASS.

## Remaining architectural limitations

1. The controller is host-side and has the normal permissions of the logged-in user.
2. libMirage parses images host-side; a libMirage vulnerability is outside the Bottles jail.
3. Runtime network/CD injection currently relies on Bubblejail's
   `--debug-bwrap-args`; rc2 detects absence, but this remains an upstream compatibility surface.
4. Whitelist backup is one-generation, not a history.
5. `RemoveDevice` follows CDEmu/gCDEmu's last-device model; cleanup avoids removal
   if another client has changed the device count, but concurrent external CDEmu
   management remains a race to avoid during diagnostics.
