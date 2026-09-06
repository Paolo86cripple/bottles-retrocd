# Bottles Retro CD GUI

GTK4 controller for running native Bottles inside a dedicated Bubblejail instance,
with CDEmu/UDisks2 integration for retro optical media.

Current version: **0.4.0-rc1**.

## Goals

- keep Bottles/Wine inside the existing Bubblejail instance `Bottles`;
- private HOME for Bottles, runners, DXVK, runtimes and prefixes;
- explicit persistent filesystem whitelist with separate RW and RO paths;
- network OFF by default, optionally enabled for one launch only;
- CDEmu control over D-Bus using the same daemon API model as gCDEmu;
- UDisks2 mount verification in read-only mode;
- optional raw optical-device exposure for Wine, accepted only when the kernel
  reports `/dev/srX` as read-only;
- diagnostics before normal use.

## UI

The interface is split into five tabs:

1. **CDEmu** — drive selection, image load/eject and UDisks2 RO status.
2. **Sandbox** — per-launch network and optical-device permissions, plus Bottles launch.
3. **Whitelist** — persistent Bubblejail `root_share` RO/RW management.
4. **Advanced** — DPM, transfer-rate, bad-sector and DVD CSS emulation.
5. **Test** — CDEmu/UDisks2, Bubblejail and end-to-end CD → Bubblejail tests, with copy-log.

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
- Wayland, XWayland, audio, Vulkan/GPU and dconf;
- dynamic `/dev/srX` plus `/mnt/cdemu` integration;
- runner downloaded with temporary network ON persists inside Bubblejail's
  private HOME and remains available after reopening with network OFF.

The rc1 adds an additional fail-closed check that the raw `/dev/srX` device is
reported read-only by the kernel before it may be passed to Wine. Re-run the
CDEmu and integration tests once after updating to rc1.

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
