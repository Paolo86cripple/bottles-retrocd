# Bottles RetroCD

GTK4 controller for running native Bottles inside a dedicated Bubblejail instance, with CDEmu/UDisks2 integration for retro optical media and a read-only Redump/TOSEC verifier.

Current release candidate: **0.4.0**.

## Goals

- keep Bottles/Wine inside the existing Bubblejail instance `Bottles`;
- private HOME for Bottles, runners, DXVK, runtimes and prefixes;
- explicit persistent filesystem whitelist with separate RW and RO paths;
- network OFF by default, optionally enabled for one launch only;
- per-launch GPU selector with persistent PCI-address selection and strict `/dev/dri` node isolation;
- fail closed if GPU identity/nodes cannot be proven or if the running Bubblejail instance exposes more than the selected GPU;
- native Wayland with an explicit XWayland compatibility fallback;
- persistent Bottles global preferences inside the private jail HOME through the GLib keyfile backend;
- configurable persistent RetroCD archive root with migration from the previous target-machine path, without moving or modifying dump files;
- CDEmu control over D-Bus using the same daemon API model as gCDEmu;
- UDisks2 mount verification in read-only mode;
- optional raw optical-device exposure for Wine, accepted only when it matches the CDEmu D-Bus mapping and is validated as a Linux SCSI optical block device;
- explicit Redump/TOSEC-friendly multidisc sets that reference original descriptors without modifying archive files;
- live multidisc swap with RO cache mounts, stable `/mnt/cdemu` and automatic post-Bottles cleanup;
- Redump/TOSEC verification without modifying, mounting or executing archive dumps;
- official DAT updates with HTTPS host allow-list, bounded ZIP extraction, staged indexing and rollback;
- optional read-only protection-signature scanning of ISO9660/Joliet and common raw-sector images.

## UI

The interface is split into seven tabs:

1. **CDEmu** — drive selection, image load/eject, multidisc and UDisks2 RO status.
2. **Sandbox** — archive root, per-launch GPU, network/optical permissions, display backend, GPU Vulkan/isolation test and Bottles launch.
3. **Whitelist** — persistent Bubblejail `root_share` RO/RW management.
4. **Avanzate** — DPM, transfer-rate, bad-sector and DVD CSS emulation.
5. **Test** — cumulative application log plus CDEmu/UDisks2, Bubblejail, bridge/cache and end-to-end CD → Bubblejail tests.
6. **Verifica** — Redump PC/TOSEC DAT update/import, exact 1:1 image/set verification, protection scan and explicit DAT↔scanner comparison.
7. **Componenti** — host-side CDEmu/libMirage/VHBA health and explicit Arch/CachyOS update flow.

## Archive root

`config.toml` schema 2 stores the archive root explicitly together with the selected GPU PCI address and display backend.

On an existing target installation that still uses the historical:

```text
/run/media/<user>/Data/Downloads/retropc
```

RetroCD migrates only the **path setting** when that directory actually exists. It never copies, moves, renames or rewrites the archive. New installations must choose the archive root explicitly.

The archive root and its subdirectories may be explicitly whitelisted read-only. RW access to any part of the archive is forbidden, and its parents are refused in both modes. Selecting an archive does not share it automatically. Optical mounts/devices are injected separately according to the selected Retro Optical policy.

## Display backends

The Sandbox tab stores one of:

- **Auto** — no display override;
- **Wayland nativo** — enables the Proton/CachyOS native-Wayland controls;
- **XWayland** — removes the native-Proton Wayland opt-ins and presents an X11 session to Wine/Bottles while keeping the Bottles GTK UI free to use Wayland.

Forced XWayland requires the existing Bubblejail `x11` and `wayland` services. RetroCD does not add new display permissions automatically.

Bottles global preferences use:

```text
GSETTINGS_BACKEND=keyfile
```

so settings such as dark mode and temporary/cache preferences persist in Bubblejail's private HOME without exposing the host dconf database.

## GPU/Bubblejail launch policy

GPU selection is a security decision, not just a performance preference.

- GPU identity is persisted by stable PCI address, never by `cardX` numbering.
- Bottles launch is refused if no valid GPU can be selected; there is no implicit Mesa-default fallback.
- PCI/vendor/device/driver metadata and both selected DRM nodes are validated before launch.
- The selected `cardN` and `renderD*` paths must be live character devices.
- Bubblejail's broad `/dev/dri` view is masked and only those two selected nodes are rebound.
- Before Bottles starts, a temporary Bubblejail probe must positively confirm `DRI_PRIME`, both selected nodes, absence of known nodes belonging to other GPUs, exactly one Vulkan device, and matching vendor/device IDs.
- After Bottles starts, the GUI attaches the same effective-device proof to the already-running Bubblejail instance.
- If post-launch proof fails, the exact launch process group is terminated and the GUI reports failure.
- **Test Vulkan** uses the same positive-proof validator.

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

Verifier data is stored under XDG data/cache directories, not in the dump tree. The updater downloads only over HTTPS from allow-listed official Redump/TOSEC hosts, validates redirects, bounds compressed/unpacked inputs, rejects ZIP traversal/symlinks, builds a complete staged SQLite index and replaces the live generation only after validation. A failed update restores the previous catalog/DAT generation.

The protection scanner never mounts or executes the image. It reads ISO9660/Joliet structures directly, supports common 2048/2336/2352-sector layouts, bounds directory depth/count/extent size and file samples, performs a streaming raw-signature pass, and reports evidence separately from DAT metadata.

## Current validation

The 0.4.0 candidate has been validated on the target CachyOS system for:

- CDEmu temporary-device create/load/unload/remove and advanced D-Bus options;
- UDisks2 read-only mounts and denied filesystem writes;
- Bubblejail private HOME, whitelist enforcement, hidden real HOME and network isolation;
- real temporary host sentinels used for non-whitelist isolation checks;
- persistent GPU selection and strict DRM/Vulkan isolation on both available AMD GPUs;
- mandatory pre/post launch GPU proof;
- Wayland and XWayland;
- audio;
- persistent Bottles GSettings/keyfile preferences;
- dynamic `/dev/srX` plus `/mnt/cdemu` integration;
- runner persistence after temporary network ON followed by network OFF;
- static bridge and live multidisc swaps;
- Discworld Noir three-disc Redump set;
- Discworld Noir with `proton-cachyos-native` + D7VK: native Wayland works, while XWayland enters fullscreen directly;
- verifier/source immutability and lifecycle/update negative paths.

Current CI: **130 unit tests PASS**. CI also compiles every Python module including `display_backend.py`, treats `ResourceWarning` as an error, checks shell syntax and scans for unsafe dynamic execution patterns.

## Run locally

Nothing is installed by this tree:

```sh
./run-local.sh
```

Required runtime commands include `python3`, `bubblejail`, `findmnt`, `ip` and `vulkaninfo`. `cdemu-client` is not required; RetroCD controls CDEmu through D-Bus. `udisksctl` is required for UDisks2 RO mounts and live multidisc operation.

The existing Bubblejail instance is expected at:

```text
~/.local/share/bubblejail/instances/Bottles/
```

The verifier also has a CLI:

```sh
python verifier_cli.py stats
python verifier_cli.py verify /path/to/disc.cue --root /path/to/archive
python verifier_cli.py verify-set /path/to/disc1.cue /path/to/disc2.cue --root /path/to/archive
python verifier_cli.py scan /path/to/disc.iso --root /path/to/archive
python verifier_cli.py verify-scan /path/to/disc.iso --root /path/to/archive
python verifier_cli.py update redump
python verifier_cli.py update tosec
```

## Important security boundary

The GTK controller, verifier, CDEmu daemon and libMirage run on the host as the logged-in user. Bubblejail protects **Bottles/Wine**, not these host-side components. Consequently all host-side parsing paths are written fail-closed and archive inputs are treated as untrusted data.

Persistent `[network]` in `services.toml` is rejected. The GUI only enables Bottles networking transiently for the selected launch. The verifier updater has its own narrower HTTPS/official-host policy.

## Post-0.4.0 roadmap

- **Legacy DirectX compatibility managers** such as dgVoodoo2/DxWrapper, optional and OFF by default.
- **libRashader + Slang shaders**, optional and OFF by default, after the base release is packaged and stable.
- abnormal-termination recovery for live multidisc cache devices.

None of these should weaken the existing Bubblejail boundary or become mandatory for ordinary launch paths.

## License and upstream attribution

This project is GPL-3.0-or-later. The CDEmu D-Bus backend uses interface names, method signatures, signal names and client design patterns adapted from gCDEmu 3.3.1 (GPL-2.0-or-later). See `NOTICE`.
