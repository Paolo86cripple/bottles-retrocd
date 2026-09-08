# Retro Optical trust boundary

## Purpose

Retro Optical is the optical-media compatibility layer used by Bottles RetroCD for Windows CD/DVD games. Its security goal is narrower than "sandbox CDEmu": CDEmu and libMirage are trusted host-side infrastructure, while the untrusted Windows game remains inside Bubblejail and receives only the minimum optical surface required for compatibility.

The existing CDEmu/multidisc controller remains the runtime baseline. This document formalizes the boundary that the launcher must prove after every Bottles start.

## Upstream model

Bottles RetroCD's `cdemu_backend.py` intentionally implements only a small D-Bus subset of upstream gCDEmu. Upstream gCDEmu 3.3.1 uses the same bus name, object path, interface major 7 and the same `DeviceLoad`, `DeviceUnload`, mapping, option and device-lifecycle methods.

Upstream CDEmu also exposes broader methods that RetroCD does not need, including blank-media creation. Omitting such methods from RetroCD's Python client is not an access-control boundary: if an untrusted process could reach the host CDEmu D-Bus service directly, it could invoke methods independently of our GUI.

Normal `DeviceLoad` media is initialized upstream as non-recordable/non-rewritable read-only optical media. Recording support exists through the separate blank-media/writer path. Raw SCSI access is therefore still a broader compatibility interface than a read-only filesystem mount even though a normal archive image is not made recordable.

## Host-side trusted plane

These components remain outside Bubblejail:

- the VHBA kernel module;
- `/dev/vhba_ctl`;
- `cdemu-daemon`;
- libMirage and image parsing;
- Bottles RetroCD's CDEmu D-Bus controller;
- UDisks2 optical mounting;
- the original archive images under the authorised retro tree;
- optional diagnostic clients such as gCDEmu or `cdemu-client`.

The CDEmu daemon requires the VHBA control interface to exchange SCSI requests with the kernel module. Moving the daemon into the game jail would therefore require exposing a privileged host-control surface to the untrusted game and would weaken, not strengthen, the design.

## Bubblejail game plane

The game must never receive:

- `/dev/vhba_ctl`;
- access to `net.sf.cdemu.CDEmuDaemon` on the session D-Bus;
- the CDEmu daemon process as a jail service;
- libMirage parsing of the source image inside the game jail;
- generic `/dev`, `/run/media`, or cached multidisc optical devices.

The game may receive only:

1. `/mnt/cdemu`, using a verified read-only UDisks2 mount and Bubblewrap `ro-bind`; and/or
2. the exact CDEmu `/dev/srN` mapped for the selected active drive when raw optical compatibility is required; and/or
3. the exact paired `/dev/sgN` only after explicit advanced opt-in.

Live multidisc keeps cache drives host-side. Only the single active `/dev/srN` remains visible to Wine; `/mnt/cdemu` switches through the already-validated static RO mount bank and private selector.

## Mandatory post-launch proof

Every normal Bottles launch is fail-closed. After the existing GPU post-launch proof succeeds, RetroCD injects a second read-only probe through Bubblejail's running-instance helper RPC.

The proof must confirm all of the following:

- `/dev/vhba_ctl` is absent;
- `org.freedesktop.DBus.Peer.Ping` to `net.sf.cdemu.CDEmuDaemon` is blocked;
- the set of visible `/dev/srN` nodes is exactly the set authorised for that launch (zero or one);
- the set of visible `/dev/sgN` nodes is exactly the set authorised for that launch (normally zero);
- `/mnt/cdemu` is absent when not authorised;
- when `/mnt/cdemu` is authorised, it resolves to a directory and `findmnt` reports `ro` rather than `rw`.

The probe performs no write attempt against the optical media. Failure or absence of any required proof marker terminates the exact Bubblejail process group already captured by the GPU fail-closed launcher and triggers safe multidisc cleanup when possible.

## Component lifecycle on Arch/CachyOS

RetroCD should prefer distribution-managed CDEmu components rather than privately bundling a second daemon/kernel stack.

Reasons:

- VHBA is a kernel component and must match the running kernel;
- the daemon installs a D-Bus-activatable systemd user service, udev integration and module-loading integration;
- libMirage is a shared host parser used by the daemon;
- duplicating those pieces inside RetroCD would increase privileged update and compatibility risk.

The component manager planned for the remainder of Point 5 should therefore:

- detect installed/running versions without parsing localized GUI output;
- query daemon/libMirage versions through the existing D-Bus API when possible;
- detect the loaded VHBA module and package state;
- prefer official Arch/CachyOS packages and, on custom kernels, the appropriate DKMS VHBA package;
- make package installation/update an explicit user action, never a silent background privilege escalation;
- show the transaction that will be performed before invoking the system package manager;
- never remove packages merely because RetroCD did not install them;
- treat `cdemu-client` and gCDEmu as optional diagnostics, because RetroCD itself talks to the daemon directly over D-Bus.

A source-build fallback is not part of the default architecture. If one is ever added, RetroCD must record exactly which build-only dependencies it installed and remove only those dependencies after the build; pre-existing packages must never be removed automatically.

## Acceptance tests

Before merging this hardening into `main`, validate on the target CachyOS system with Bottles fully closed before each launch:

1. launch Bottles without optical media and require `sr=hidden`, `sg=hidden`, `/mnt/cdemu=hidden`, VHBA hidden and CDEmu D-Bus blocked;
2. launch with only the RO mount exposed and require `/mnt/cdemu=RO`, no raw optical nodes, VHBA hidden and D-Bus blocked;
3. launch with the exact raw `/dev/srN` enabled and require exactly that node, no `sgN`, plus the expected RO mount policy;
4. optionally test explicit `/dev/sgN` exposure and require exactly the mapped `srN` + `sgN` pair;
5. run the existing Discworld Noir live multidisc flow and require one active `srN`, no cached optical nodes, no `sgN`, `/mnt/cdemu=RO`, VHBA hidden and D-Bus blocked;
6. confirm normal cache cleanup after Bottles exits;
7. rerun the full unit/static CI gate.

Do not weaken a failed proof to a warning for compatibility. A game that needs a broader optical surface must receive a narrowly reviewed policy change rather than an implicit fallback.
