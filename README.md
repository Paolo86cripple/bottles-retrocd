# Bottles Retro CD GUI

GTK4 controller for running native Bottles inside a dedicated Bubblejail instance,
with CDEmu/UDisks2 integration for retro optical media and a read-only Redump/TOSEC verifier.

Current version: **0.4.0-rc2 + unreleased verifier/multidisc work**.

## Goals

- keep Bottles/Wine inside the existing Bubblejail instance `Bottles`;
- private HOME for Bottles, runners, DXVK, runtimes and prefixes;
- explicit persistent filesystem whitelist with separate RW and RO paths;
- network OFF by default, optionally enabled for one launch only;
- per-launch GPU selector with integrated-GPU preference, persistent PCI-address selection and strict `/dev/dri` node isolation;
- fail closed if GPU identity/nodes cannot be proven or if the effective running Bubblejail instance does not expose exactly the selected GPU;
- CDEmu control over D-Bus using the same daemon API model as gCDEmu;
- UDisks2 mount verification in read-only mode;
- optional raw optical-device exposure for Wine, accepted only when it matches the CDEmu D-Bus mapping and is validated as a Linux SCSI optical block device;
- diagnostics before normal use;
- explicit Redump/TOSEC-friendly multidisc sets that reference original descriptors without modifying archive files;
- live multidisc swap with RO cache mounts, stable `/mnt/cdemu` and automatic post-Bottles cleanup;
- Redump/TOSEC verification without modifying, mounting or executing archive dumps;
- official DAT updates with HTTPS host allow-list, bounded ZIP extraction, staged indexing and rollback;
- optional read-only protection-signature scanning of ISO9660/Joliet and common raw-sector images.

## UI

The interface is split into six tabs:

1. **CDEmu** — drive selection, image load/eject and UDisks2 RO status.
2. **Sandbox** — per-launch GPU, network and optical-device permissions, GPU Vulkan/isolation test, plus Bottles launch.
3. **Whitelist** — persistent Bubblejail `root_share` RO/RW management.
4. **Advanced** — DPM, transfer-rate, bad-sector and DVD CSS emulation.
5. **Test** — cumulative application log plus CDEmu/UDisks2, Bubblejail, bridge/cache and end-to-end CD → Bubblejail tests. The log can be copied or explicitly cleared with **Pulisci log**.
6. **Verifica** — Redump PC/TOSEC DAT update/import, exact 1:1 image/set verification, protection scan and explicit DAT↔scanner comparison.

## GPU/Bubblejail launch policy

GPU selection is a security decision, not just a performance preference.

- GPU identity is persisted by stable PCI address, never by `cardX` numbering.
- Bottles launch is refused if no valid GPU can be selected; there is no implicit `Mesa default` fallback.
- PCI/vendor/device/driver metadata and both selected DRM nodes are validated before launch.
- The selected `cardN` and `renderD*` paths must be live character devices.
- Bubblejail's broad `/dev/dri` view is masked and only those two selected nodes are rebound.
- Before Bottles starts, a temporary Bubblejail probe must positively confirm `DRI_PRIME`, both selected nodes, absence of known nodes belonging to other GPUs, exactly one Vulkan device, and matching vendor/device IDs.
- After Bottles starts, the GUI attaches the same probe to the already-running Bubblejail instance. If effective isolation cannot be confirmed, the launch process group is terminated and the GUI reports failure.
- **Test Vulkan** uses the same positive-proof validator.

The automatic post-launch guard is new in this candidate and must receive a final real-machine pass on the target Bubblejail 0.10.4 installation after integration.

## Verifier architecture

The verifier is host-side, but deliberately read-only with respect to archive material:

- CUE/TOC descriptors are parsed without rewriting them;
- descriptor references are canonicalized and rejected if they escape the authorised archive root;
- CloneCD/MDS companion payloads are resolved without altering names or paths;
- CRC32, MD5 and SHA-1 are calculated in one streaming pass;
- the persistent hash cache keys validity on device/inode/size/mtime/ctime and is invalidated when a file changes;
- Logiqx XML is parsed incrementally into SQLite;
- a `MATCH 1:1` means every payload belongs to one and only one complete DAT game record;
- equivalent complete matches in multiple DAT records are reported as `AMBIGUOUS`, never silently chosen;
- DAT serial/version/protection metadata are retained when present.

Verifier data is stored under the user's XDG data/cache directories, not in the dump tree. The updater downloads only over HTTPS from allow-listed official Redump/TOSEC hosts, validates redirects, bounds compressed/unpacked inputs, rejects ZIP traversal/symlinks, builds a complete staged SQLite index and replaces the live generation only after validation. A failed update restores the previous catalog/DAT generation.

The protection scanner never mounts or executes the image. It reads ISO9660/Joliet structures directly, supports common 2048/2336/2352-sector layouts, bounds directory depth/count/extent size and file samples, performs a streaming raw-signature pass, and reports evidence separately from DAT metadata.

## Current validation

On CachyOS with Bubblejail 0.10.4, CDEmu daemon 3.3.1 and Bottles 67.1 the
following have been validated on real hardware in the existing rc2/multidisc work:

- CDEmu temporary-device create/load/unload/remove;
- CDEmu advanced options through D-Bus;
- UDisks2 read-only mount and denied filesystem write;
- Bubblejail private HOME;
- host HOME hidden;
- dynamic RW/RO whitelist enforcement;
- non-whitelisted Data paths hidden;
- network isolation with only loopback;
- persistent GPU selection by PCI address;
- strict `/dev/dri` isolation exposing only the selected GPU nodes;
- Vulkan identity test and successful Bottles launches on both available AMD GPUs for the previous selector path;
- Wayland, XWayland, audio, Vulkan/GPU and dconf;
- dynamic `/dev/srX` plus `/mnt/cdemu` integration;
- runner downloaded with temporary network ON persists inside Bubblejail's private HOME and remains available after reopening with network OFF;
- static bridge A→B follows the selected mount without restarting Bubblejail;
- Discworld Noir three-disc Redump set caches Disc 1/2/3 on distinct UDisks2 RO mounts and swaps correctly while Bottles remains open.

The current branch CI passes **73 unit tests**: 19 original sandbox/settings/multidisc/bridge tests, 8 additional GPU fail-closed regression tests, 35 verifier/catalog/update tests and 12 protection-scanner tests. CI also compiles every Python module, treats `ResourceWarning` as an error and scans for unsafe dynamic execution patterns.

The rc2 validates raw `/dev/srX` by CDEmu mapping, Linux block-device identity and SCSI optical type 5. The block-layer `ro` bit is diagnostic only; UDisks2 filesystem mounts remain fail-closed read-only.

## Post-release roadmap

1. **DxWrapper / Legacy DirectX compatibility layer** — evaluate and integrate DxWrapper as an optional, **OFF-by-default** compatibility backend for legacy Windows games, especially DirectDraw/Direct3D 1–7 through `Dd7to9` and D3D8→D3D9. It should be selectable per profile, work with either DXVK or WineD3D where appropriate, and must not weaken the existing Bubblejail sandbox or device/filesystem isolation.
2. **libRashader + Slang shaders** — optional, **OFF-by-default** shader integration for Windows/Bottles games, after the legacy DirectX compatibility layer is stable.

## Run locally

Nothing is installed by this tree:

```sh
./run-local.sh
```

The existing Bubblejail instance is expected at:

```text
~/.local/share/bubblejail/instances/Bottles/
```

The verifier also has a CLI for diagnostics and scripted checks:

```sh
python verifier_cli.py stats
python verifier_cli.py verify /path/to/disc.cue --root /path/to/retropc
python verifier_cli.py verify-set /path/to/disc1.cue /path/to/disc2.cue --root /path/to/retropc
python verifier_cli.py scan /path/to/disc.iso --root /path/to/retropc
python verifier_cli.py verify-scan /path/to/disc.iso --root /path/to/retropc
python verifier_cli.py update redump
python verifier_cli.py update tosec
```

## Important security boundary

The GTK controller, verifier, CDEmu daemon and libMirage run on the host as the logged-in user. Bubblejail protects **Bottles/Wine**, not these host-side components. Consequently all host-side parsing paths are written fail-closed and archive inputs are treated as untrusted data.

Persistent `[network]` in `services.toml` is rejected. The GUI only enables network transiently for the selected launch. The verifier updater has its own much narrower network policy: HTTPS only to explicit official Redump/TOSEC hosts.

## License and upstream attribution

This project is GPL-3.0-or-later. The CDEmu D-Bus backend uses interface names,
method signatures, signal names and client design patterns adapted from gCDEmu
3.3.1 (GPL-2.0-or-later). See `NOTICE`.
