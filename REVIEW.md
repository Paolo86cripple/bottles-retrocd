# Review 0.4.0-rc2 + verifier candidate

## Status

The existing rc2/GPU/multidisc runtime architecture remains the baseline. The recovered Redump/TOSEC verifier is layered onto that baseline without rewriting the validated CDEmu/Bubblejail/GPU controller: the former `bottles-retro-cd-gui.py` is preserved byte-for-byte as `bottles-retro-cd-gui-base.py`, while the public entrypoint subclasses it to add verifier UI and the reviewed log-clear action.

This review treats optical images and downloaded/imported DATs as untrusted host-side input. The verifier never mounts or executes images and never writes inside the dump tree.

## Real-machine validation completed before verifier recovery

- CDEmu temporary device create/load/unload/remove: PASS.
- CDEmu advanced D-Bus options: PASS.
- UDisks2 read-only mount and denied filesystem write: PASS.
- Bubblejail dynamic-whitelist sandbox: PASS.
- CD → Bubblejail integration: PASS.
- Temporary network ON followed by OFF: PASS.
- Bottles runner persistence in the private Bubblejail HOME: PASS (`soda-11.0-8`).
- GPU isolation/Vulkan identity: PASS on Ryzen 7 9800X3D iGPU and Radeon RX 9070 XT.
- Discworld Noir three-disc live cache/swap lifecycle: PASS in the multidisc candidate.

## Existing rc2 / GPU / multidisc security conclusions

- CDEmu is controlled through D-Bus rather than localized CLI parsing.
- Persistent `[network]` is rejected; network is transient per Bottles launch.
- Bubblejail instance reuse is blocked when transient permissions would change.
- RO/RW whitelist paths are canonicalized, broad/overlapping paths are rejected, and `services.toml` replacement is backed up and atomic.
- Dynamic CD filesystems use `ro-bind` only.
- Raw `/dev/srX` is opt-in and must be the exact CDEmu-mapped Linux SCSI optical block device; block-layer `ro` is diagnostic only.
- `/dev/sgX` remains optional and disabled by default.
- UDisks2 mount state is verified rather than inferred from command success.
- Worker operations do not read GTK widget state directly from worker threads.
- GPU identity persists by PCI address and only the selected GPU DRM nodes are re-exposed after `/dev/dri` masking.
- Live multidisc requires an explicit saved set; cache devices remain host-side and only the active optical device is exposed to Wine.
- Cache cleanup revalidates device ownership/count/order/mapping before removal and aborts on concurrent external CDEmu changes.

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
- Directory traversal is bounded by depth and entry-count limits.
- File-content sampling is bounded; a separate raw scan streams the whole image with overlap sufficient for cross-chunk signatures.
- Evidence is reported with confidence and source labels; it is not silently promoted into cryptographic DAT verification.
- DAT protection metadata is compared explicitly with scanner observations. Scanner absence does not invalidate a cryptographic DAT match; scanner presence does not turn a DAT mismatch into a match.

## GUI review

- The dedicated **Verifica** tab provides official Redump/TOSEC update, local DAT import, single-image verification, multidisc verification, scanner-only and DAT↔scanner actions.
- The reviewed **Pulisci log** callback is `_clear_log`.
- `_clear_log` uses `Gtk.TextBuffer.set_text("")` and deliberately updates the status label directly rather than calling `set_message()`, which would immediately append a new line to the cleared log.
- `Pulisci log`, `Copia log` and verifier actions are disabled while the controller is busy and re-enabled through the existing `set_busy()` lifecycle, including exception paths handled by `finish_background()`.
- The base security-sensitive GUI remains byte-identical to the pre-verifier `main` version; verifier integration is isolated in the entrypoint subclass.

## Static/regression review

- Regression suite composition: **65 tests total** = 19 existing + 35 verifier/updater + 11 scanner.
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
6. GPU-related sysfs remains visible to avoid unnecessary Mesa/udev compatibility risk.

## Merge criterion

Do not advance this candidate to `main` unless the branch CI passes the full 65-test suite, Python/static checks and shell check. After merge, repeat the real-machine verifier test against the previously validated Discworld Noir Redump set and confirm descriptor/payload content and `mtime_ns` remain unchanged before/after verification.
