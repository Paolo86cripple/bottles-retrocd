# Bottles Retro CD GUI

GTK4 controller for running native Bottles inside a dedicated Bubblejail instance,
with CDEmu/UDisks2 integration for retro optical media.

Current version: **0.4.0-rc2**.

## Goals

- keep Bottles/Wine inside the existing Bubblejail instance `Bottles`;
- private HOME for Bottles, runners, DXVK, runtimes and prefixes;
- explicit persistent filesystem whitelist with separate RW and RO paths;
- network OFF by default, optionally enabled for one launch only;
- per-launch GPU selector with integrated-GPU preference, persistent PCI-address selection and strict `/dev/dri` node isolation;
- CDEmu control over D-Bus using the same daemon API model as gCDEmu;
- UDisks2 mount verification in read-only mode;
- optional raw optical-device exposure for Wine, accepted only when it matches the CDEmu D-Bus mapping and is validated as a Linux SCSI optical block device;
- diagnostics before normal use;
- explicit Redump/TOSEC-friendly multidisc sets that reference original descriptors without modifying archive files;
- live multidisc swap with RO cache mounts, stable `/mnt/cdemu` and automatic post-Bottles cleanup.

## UI

The interface is split into five tabs:

1. **CDEmu** — drive selection, image load/eject and UDisks2 RO status.
2. **Sandbox** — per-launch GPU, network and optical-device permissions, GPU Vulkan test, plus Bottles launch.
3. **Whitelist** — persistent Bubblejail `root_share` RO/RW management.
4. **Advanced** — DPM, transfer-rate, bad-sector and DVD CSS emulation.
5. **Test** — cumulative application log plus CDEmu/UDisks2, Bubblejail, bridge/cache and end-to-end CD → Bubblejail tests, with copy-log.

## Current validation

On CachyOS with Bubblejail 0.10.4, CDEmu daemon 3.3.1 and Bottles 67.1 the
following have been validated on real hardware:

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
- Vulkan identity test and successful Bottles launches on both available AMD GPUs;
- Wayland, XWayland, audio, Vulkan/GPU and dconf;
- dynamic `/dev/srX` plus `/mnt/cdemu` integration;
- runner downloaded with temporary network ON persists inside Bubblejail's
  private HOME and remains available after reopening with network OFF;
- static bridge A→B follows the selected mount without restarting Bubblejail;
- Discworld Noir three-disc Redump set caches Disc 1/2/3 on distinct UDisks2 RO mounts and swaps correctly while Bottles remains open.

The rc2 validates raw `/dev/srX` by CDEmu mapping, Linux block-device identity and SCSI optical type 5. The block-layer `ro` bit is diagnostic only; UDisks2 filesystem mounts remain fail-closed read-only. This path has been validated on the target CachyOS system.

## Run locally

Nothing is installed by this tree:

```sh
./run-local.sh
```

The existing Bubblejail instance is expected at:

```text
~/.local/share/bubblejail/instances/Bottles/
```

## Important security boundary

The GTK controller and CDEmu/libMirage run on the host as the logged-in user.
The whitelist protects **Bottles/Wine inside Bubblejail**; it is not a sandbox
for the controller itself or for libMirage image parsing.

Persistent `[network]` in `services.toml` is rejected. The GUI only enables
network transiently for the selected launch.

## License and upstream attribution

This project is GPL-3.0-or-later. The CDEmu D-Bus backend uses interface names,
method signatures, signal names and client design patterns adapted from gCDEmu
3.3.1 (GPL-2.0-or-later). See `NOTICE`.
