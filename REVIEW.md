# Review 0.4.0-rc2 + verifier candidate

## Status

The existing rc2/GPU/multidisc runtime architecture remains the baseline. The recovered Redump/TOSEC verifier is layered onto that baseline without rewriting the validated CDEmu/multidisc controller: the former `bottles-retro-cd-gui.py` is preserved as `bottles-retro-cd-gui-base.py`, while the public entrypoint subclasses it to add verifier UI, the reviewed log-clear action and the final fail-closed GPU/Bubblejail launch guard.

This review treats optical images and downloaded/imported DATs as untrusted host-side input. The verifier never mounts or executes images and never writes inside the dump tree.

## Real-machine validation completed before verifier recovery

- CDEmu temporary device create/load/unload/remove: PASS.
- CDEmu advanced D-Bus options: PASS.
- UDisks2 read-only mount and denied filesystem write: PASS.
- Bubblejail dynamic-whitelist sandbox: PASS.
- CD → Bubblejail integration: PASS.
- Temporary network ON followed by OFF: PASS.
- Bottles runner persistence in the private Bubblejail HOME: PASS (`soda-11.0-8`).
- GPU isolation/Vulkan identity: PASS on Ryzen 7 9800X3D iGPU and Radeon RX 9070 XT for the pre-hardening selector path.
- Discworld Noir three-disc live cache/swap lifecycle: PASS in the multidisc candidate.

The automatic GPU pre/post-launch guard is CI-reviewed and unit-tested. The first target-machine post-launch attempt exposed an integration bug in the probe transport: Bubblejail 0.10.4 ignores `--debug-shell` once the instance is already running and instead routes positional commands through its helper RPC. That false-negative path is now corrected; one final real-machine pass is still required.

## Existing rc2 / multidisc security conclusions

- CDEmu is controlled through D-Bus rather than localized CLI parsing.
- Persistent `[network]` is rejected; network is transient per Bottles launch.
- Bubblejail instance reuse is blocked when transient permissions would change.
- RO/RW whitelist paths are canonicalized, broad/overlapping paths are rejected, and `services.toml` replacement is backed up and atomic.
- Dynamic CD filesystems use `ro-bind` only.
- Raw `/dev/srX` is opt-in and must be the exact CDEmu-mapped Linux SCSI optical block device; block-layer `ro` is diagnostic only.
- `/dev/sgX` remains optional and disabled by default.
- UDisks2 mount state is verified rather than inferred from command success.
- Worker operations do not read GTK widget state directly from worker threads.
- Live multidisc requires an explicit saved set; cache devices remain host-side and only the active optical device is exposed to Wine.
- Cache cleanup revalidates device ownership/count/order/mapping before removal and aborts on concurrent external CDEmu changes.

## Final GPU / Bubblejail fail-closed review

The later sandbox review found that the original selector was strict once a GPU was selected, but the launch path could still fall back to `Mesa default` when no usable GPU was detected and the strict Vulkan/DRM verification was only a separate manual button. Those are now release-blocking failures rather than permissive fallbacks.

- GPU identity still persists by stable PCI address; `cardX` ordering is never used as persistent identity.
- The selected GPU must have a syntactically valid PCI address, 4-digit vendor/device IDs, a kernel driver, a DRM `cardN` node and a `renderD*` node.
- Immediately before launch, both selected DRM paths must resolve to live character devices on the host.
- `bubblewrap_gpu_args(None)` is rejected: there is no implicit Mesa-default launch path.
- Bubblejail runtime-argument support is checked before any GPU policy is attempted.
- `/dev/dri` is masked with a tmpfs and only the selected GPU card/render nodes are rebound.
- A mandatory **pre-launch** debug-shell probe verifies `DRI_PRIME`, both selected DRM nodes, absence of all known non-selected GPU nodes, exactly one Vulkan device and matching vendor/device IDs.
- The pre-launch probe must terminate cleanly; if it leaves a Bubblejail instance active, Bottles is not launched.
- After the real Bottles Bubblejail process starts, the controller injects the second probe through Bubblejail 0.10.4's supported running-instance path: `bubblejail run --wait <instance> /bin/sh -c <probe>`. The CLI detects the existing helper socket, sends the positional command through `send_run_rpc()`, and the helper executes it inside the existing sandbox with stdout/stderr captured.
- The earlier `bubblejail run --debug-shell <instance>` post-launch implementation was incorrect for an already-running instance: `run_bjail()` returns through `run_running_instance()` before the `debug_shell` path is used. The resulting missing markers were therefore a probe-transport false negative, not proof that the selected DRM nodes were actually absent from Bottles.
- The post-launch helper command may receive a fresh process environment, so this phase does not require its `DRI_PRIME` marker. It still requires both selected DRM nodes, absence of every known non-selected GPU node, exactly one Vulkan device and matching vendor/device IDs. This proves the effective device/Vulkan isolation of the running jail.
- Absence of any required proof marker is failure: missing success markers are treated the same as explicit failure markers.
- If helper injection, output collection or post-launch proof fails, the exact Bubblejail process group captured for that launch is terminated; live multidisc state is cleaned when it is safe to do so; the GUI reports an explicit launch failure.
- The manual **Test Vulkan** action uses the strict pre-launch validator, including `DRI_PRIME`.
- GPU-related sysfs remains visible. This is deliberate to avoid unnecessary Mesa/udev compatibility risk; access control is enforced at the DRM device-node boundary.

## Recovered Redump/TOSEC verifier review

### Archive fidelity

- Verification opens descriptors/payloads read-only and does not rename, rewrite, move, copy or touch archive files.
- CUE and TOC references are resolved relative to the descriptor and canonicalized below the authorised root.
- `..` escape, absolute POSIX paths, Windows drive-letter paths and UNC-style paths are rejected.
- CCD/MDS companion payload resolution preserves original files and paths.
- Exact saved multidisc paths continue to take priority over name heuristics; the existing Discworld Noir regression for `Disc` inside the title remains covered.

### Hashing and cache

- CRC32, MD5 and SHA-1 are calculated in a single streaming read.
- The file is stat-ed before and after hashing; device, inode, size, mtime and ctime must remain unchanged.
- A changed file is not cached as a valid hash result.
- Persistent cache identity includes device/inode/size/mtime/ctime, so replacement or mutation invalidates a prior result.
- SQLite connections are explicitly closed; CI elevates `ResourceWarning` to errors.

### Logiqx DAT index

- DAT/XML input is parsed incrementally with `xml.etree.ElementTree.iterparse` rather than loaded as one DOM.
- The SQLite schema stores source/catalog/game/ROM records plus description, serial, version and protection metadata.
- ROM records without size or any usable digest are ignored as non-verification material.
- Catalog rebuild happens in a temporary SQLite file, runs `PRAGMA integrity_check`, rejects an empty ROM index and only then replaces the live database.
- `MATCH 1:1` requires the complete local payload multiset to match exactly one complete DAT game.
- Partial file matches remain `MISMATCH`.
- Multiple complete equivalent DAT game records remain `AMBIGUOUS`; the application does not arbitrarily choose Redump over TOSEC or vice versa.

### Official DAT updater

- Network policy is independent from Bottles networking and permits HTTPS only.
- Initial URL and every redirect target must resolve to the explicit Redump/TOSEC host allow-list.
- Credentials embedded in updater URLs are rejected.
- Download size is bounded both by declared `Content-Length` and actual streamed bytes.
- ZIP member count, per-member size and total unpacked size are bounded.
- ZIP traversal and Unix symlink entries are rejected.
- Only DAT/XML members are materialised; colliding basenames are deterministically disambiguated.
- Raw XML responses must look like Logiqx `<datafile>` material.
- A source update is prepared under a private staging directory and a complete combined catalog is built before any live generation is moved.
- The narrow failure window after moving the old DAT/catalog to rollback names but before installing staging is explicitly handled: rollback paths are restored even when `os.replace()` itself is fault-injected to fail at that point.
- Corrupt XML and injected replace failure are regression-tested to keep the previous live DAT and catalog byte-identical.
- Local DAT import copies only the DAT metadata into verifier storage and leaves source files/content/mtime untouched.

### Protection scanner

- The scanner never mounts or executes images.
- It recognizes ISO9660/Joliet volume descriptors from cooked 2048-byte sectors and common raw 2352/2336-byte sector layouts.
- Directory traversal is bounded by depth, entry count and a hard 64 MiB per-directory extent limit; an oversized/malformed directory extent fails closed rather than causing an unbounded allocation.
- File-content sampling is bounded; a separate raw scan streams the whole image with overlap sufficient for cross-chunk signatures.
- Evidence is reported with confidence and source labels; it is not silently promoted into cryptographic DAT verification.
- DAT protection metadata is compared explicitly with scanner observations. Scanner absence does not invalidate a cryptographic DAT match; scanner presence does not turn a DAT mismatch into a match.

## GUI review

- The dedicated **Verifica** tab provides official Redump/TOSEC update, local DAT import, single-image verification, multidisc verification, scanner-only and DAT↔scanner actions.
- The reviewed **Pulisci log** callback is `_clear_log`.
- `_clear_log` uses `Gtk.TextBuffer.set_text("")` and deliberately updates the status label directly rather than calling `set_message()`, which would immediately append a new line to the cleared log.
- `Pulisci log`, `Copia log` and verifier actions are disabled while the controller is busy and re-enabled through the existing `set_busy()` lifecycle, including exception paths handled by `finish_background()`.
- The preserved base controller remains unchanged; verifier and final GPU launch hardening are isolated in the public entrypoint subclass.

## Static/regression review

- Final branch CI target: **73 tests PASS**.
- Composition: 19 original sandbox/settings/multidisc/bridge tests, 8 additional GPU fail-closed regression tests, 35 verifier/updater tests and 12 scanner tests.
- The existing GPU invocation regression now explicitly asserts that a running-instance probe uses `--wait` + positional `/bin/sh -c` rather than `--debug-shell`.
- Python syntax compilation includes all application, verifier, scanner and preserved-base modules.
- Unit tests run with `PYTHONWARNINGS=error::ResourceWarning`.
- Shell syntax remains checked with `bash -n run-local.sh`.
- CI rejects `os.system`, `shell=True`, `eval` and dynamic `exec` usage in Python application paths.
- No DAT or hash cache is stored inside the repository or archive dump tree; XDG data/cache locations are used.

## Residual risks / deliberate non-goals

1. The GTK controller, verifier, CDEmu and libMirage are host-side processes with the logged-in user's normal permissions. Bubblejail isolates Bottles/Wine, not these parsers.
2. XML/ZIP/image parsing is hardened and bounded but still processes attacker-controlled bytes in Python standard-library parsers on the host.
3. The protection scanner is heuristic evidence, not a copy-protection oracle; unknown or obfuscated protections can be missed.
4. DAT authenticity currently relies on HTTPS transport plus official-host allow-list and structural/index validation. There is no detached cryptographic signature verification because the selected upstream distribution paths do not provide a uniform signed-manifest mechanism in this implementation.
5. Abnormal GUI/process kill during a live multidisc session can still leave temporary host-side CDEmu cache drives until manual/next-session recovery, as documented in the multidisc review.
6. The automatic post-launch GPU proof depends on Bubblejail 0.10.4's running-instance helper RPC and its `--wait` response path. Any upstream incompatibility or timeout remains fail-closed and terminates/refuses the launch rather than silently skipping proof.
7. GPU-related sysfs remains visible to avoid unnecessary Mesa/udev compatibility risk.

## Merge criterion

Do not advance this candidate to `main` unless branch CI passes all **73 tests**, Python/static checks and shell check. After integration, repeat on the target CachyOS machine:

1. launch with the Ryzen 7 9800X3D iGPU and confirm both pre/post GPU probe log lines;
2. launch with the Radeon RX 9070 XT and confirm the same effective DRM/Vulkan isolation proof;
3. verify the previously validated Discworld Noir Redump set and confirm descriptor/payload content and `mtime_ns` remain unchanged before/after verification;
4. exercise one live multidisc session and confirm normal cache cleanup.
