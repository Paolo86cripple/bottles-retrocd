# Security / code review — final verifier + GPU candidate

## Result

The recovered verifier/multidisc candidate passes the current static and regression gate. The intended Bottles/Wine filesystem, network, optical and GPU boundaries remain fail-closed in code. The final automatic GPU post-launch guard still requires one real-machine pass on the target CachyOS/Bubblejail installation after integration.

## Reviewed and hardened

### Bubblejail / filesystem / network

- Bubblejail instance reuse is blocked when changing transient permissions.
- Persistent `[network]` is rejected.
- Whitelist paths are canonicalized and validated before writing.
- Real HOME, Data root/ancestors, overlapping mounts and broad system roots are rejected.
- `services.toml` is syntax-checked, backed up and atomically replaced.
- Image enumeration does not follow directory symlinks outside `retropc`.
- Subprocess commands use argv lists; no user path is interpolated into a shell except narrowly scoped test snippets where paths are shell-quoted.
- Bubblejail runtime-argument support is checked before using `--debug-bwrap-args`.
- Bottles launch output is retained under the XDG cache directory instead of discarded.

### GPU fail-closed path

- GPU identity is stable PCI identity, not `cardX` numbering.
- Bottles launch is refused when no valid GPU is available; implicit `Mesa default` is not accepted.
- PCI address, vendor/device IDs, kernel driver and DRM node names are validated.
- Selected `cardN` and `renderD*` nodes must be live character devices before launch.
- Bubblejail's broad `/dev/dri` exposure is masked; only selected GPU DRM nodes are rebound.
- A pre-launch probe positively verifies `DRI_PRIME`, selected DRM-node presence, non-selected DRM-node absence, one Vulkan GPU and vendor/device identity.
- Missing success markers fail closed; lack of proof is not treated as success.
- Bubblejail 0.10.4 does **not** use `--debug-shell` when the instance is already running. Its CLI detects the helper socket and forwards positional commands through `send_run_rpc()`. The post-launch probe therefore uses `bubblejail run --wait <instance> /bin/sh -c <probe>` so the helper executes it inside the already-running Bottles sandbox and returns combined stdout/stderr.
- The first real-machine post-launch attempt used `--debug-shell` and produced missing DRM proof markers. Source review showed this was a probe-transport false negative rather than evidence that Bottles had actually lost the selected DRM nodes.
- The running-instance helper probe verifies the **effective DRM/Vulkan isolation**: selected nodes present, known non-selected nodes absent, exactly one Vulkan GPU and matching vendor/device identity. It intentionally does not require the injected process to report `DRI_PRIME`, because that process may receive a fresh environment unrelated to the already-running Bottles process.
- If helper injection, output collection or effective-isolation proof fails, the exact captured Bubblejail process group is terminated and the launch is reported as failed.
- **Test Vulkan** uses the strict pre-launch validator, including `DRI_PRIME`.
- GPU sysfs remains visible deliberately for Mesa/udev compatibility; the access-control boundary is `/dev/dri`.

### Optical / multidisc

- CDEmu uses D-Bus instead of localized CLI-output parsing.
- UDisks2 mount state is verified rather than trusted from command success alone.
- Dynamic mount is always `ro-bind`.
- Raw `/dev/srX` exposure is opt-in and validated against the CDEmu D-Bus mapping, Linux block-device type and SCSI optical type 5. The block-layer `ro` bit is diagnostic only.
- `/dev/sgX` remains optional and OFF by default because it grants a broader SCSI interface.
- Live multidisc requires an explicit saved set and keeps cache drives host-side.
- Cache cleanup revalidates ownership/count/order/mapping and refuses ambiguous removal.

### Redump/TOSEC verifier and scanner

- Dump files are opened read-only and are never mounted or executed by the verifier/scanner.
- CUE/TOC path escape and absolute-path references are rejected.
- Hashing is streaming CRC32/MD5/SHA1 with before/after file identity checks and persistent cache invalidation.
- Logiqx DATs are indexed incrementally into SQLite and `MATCH 1:1` requires one complete unique DAT game record.
- Official updater URLs are HTTPS-only with explicit host allow-list and redirect revalidation.
- DAT updates use bounded download/ZIP extraction, staging, `integrity_check` and rollback.
- ZIP traversal and symlink members are rejected.
- ISO/Joliet scanner bounds depth, entries, file samples and directory extents (64 MiB maximum per directory extent).
- Scanner evidence remains heuristic and is never promoted into cryptographic verification.

## Automated evidence

Current branch CI must pass:

- Python syntax compilation for all application/verifier/scanner modules;
- **73/73 unit tests** with `ResourceWarning` promoted to errors;
- `bash -n run-local.sh`;
- source scan rejecting `os.system`, `shell=True`, `eval` and dynamic `exec` patterns.

The existing GPU regression test now also asserts the Bubblejail 0.10.4 routing rule: pre-launch uses the validated debug-shell flow, while a running-instance post-launch probe uses `--wait` plus a positional `/bin/sh -c` command and never `--debug-shell`.

## Real-machine validation already completed on the earlier runtime path

- CDEmu/UDisks2 test: PASS.
- Bubblejail sandbox test: PASS.
- CD → Bubblejail test: PASS.
- Bottles runner persistence with temporary network ON then OFF: PASS.
- Manual GPU isolation/Vulkan identity: PASS on Ryzen 7 9800X3D iGPU and Radeon RX 9070 XT.
- Discworld Noir three-disc live multidisc: PASS.

## Required final target-machine pass

After integration, repeat both GPU selections and require the cumulative log to contain both `GPU pre-avvio` and `GPU post-avvio` PASS lines. Then repeat one Discworld Noir verifier run (proving content and `mtime_ns` unchanged) and one normal live multidisc lifecycle.

## Remaining architectural limitations

1. The controller, verifier and CDEmu/libMirage are host-side and have the normal permissions of the logged-in user.
2. libMirage and Python standard-library XML/ZIP/image parsing process untrusted bytes outside the Bottles jail; inputs are bounded/hardened but this is still a host-side parser surface.
3. Runtime network/CD/GPU injection relies on Bubblejail `--debug-bwrap-args`; absence or incompatible behavior now fails closed, but this remains an upstream compatibility surface.
4. The automatic post-launch GPU proof depends on Bubblejail 0.10.4's running-instance helper RPC and `--wait` response path; incompatibility or timeout is intentionally fail-closed.
5. Whitelist backup is one-generation, not a history.
6. Concurrent external CDEmu management remains a race to avoid during diagnostics/live cache ownership checks.
7. Abnormal GUI/process kill can leave temporary live-multidisc CDEmu cache devices until manual or future recovery handling.
