# Retro Optical trust boundary

## Purpose

Retro Optical is the optical-media compatibility layer used by Bottles RetroCD for Windows CD/DVD games. Its security goal is narrower than "sandbox CDEmu": CDEmu and libMirage are trusted host-side infrastructure, while the untrusted Windows game remains inside Bubblejail and receives only the minimum optical surface required for compatibility.

The existing CDEmu/multidisc controller remains the runtime baseline. The final launcher adds fail-closed proof around that controller without moving the trusted CDEmu plane into the game jail.

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

## Mandatory pre-launch proof

Every normal Bottles launch is fail-closed before the application starts. After the base controller has computed the final runtime Bubblejail command, RetroCD takes those exact Bubblewrap arguments and creates a temporary `--debug-shell` jail by replacing only the final application tail `-- INSTANCE`.

This exact-policy preflight therefore verifies the same GPU, network, mount-bank and raw optical arguments that would be used by the real Bottles launch. Unexpected or ambiguous command layouts are rejected rather than guessed.

The read-only probe must confirm all of the following before Bottles may start:

- `/dev/vhba_ctl` is absent;
- `org.freedesktop.DBus.Peer.Ping` to `net.sf.cdemu.CDEmuDaemon` is blocked;
- the set of visible `/dev/srN` nodes is exactly the set authorised for that launch (normally zero or one);
- the set of visible `/dev/sgN` nodes is exactly the set authorised for that launch (normally zero);
- `/mnt/cdemu` is absent when not authorised;
- when `/mnt/cdemu` is authorised, it resolves to a directory and `findmnt` reports `ro` rather than `rw`;
- the temporary probe jail exits completely before the real application is started.

The probe performs no write attempt against the optical media. Missing proof markers, unexpected nodes or a jail that remains active block the launch.

## Mandatory post-launch proof

After Bottles starts, RetroCD retains a second independent proof against the already-running jail. The GPU postflight verifies the selected DRM nodes and absence of known non-selected GPU nodes; the Retro Optical attached probe rechecks VHBA, CDEmu D-Bus, the exact `srN`/`sgN` set and `/mnt/cdemu` read-only status.

Bubblejail 0.10.x may echo the command sent to a running instance. Probe validators therefore accept only complete marker lines emitted by the probe; literal marker strings embedded in Bubblejail diagnostic text are never treated as evidence.

If any post-launch proof fails, RetroCD terminates the exact Bubblejail process group captured for that launch and performs safe multidisc cleanup when possible. The final runtime path avoids globally monkeypatching Python's `subprocess.Popen`; process capture is scoped to the controller module used for the launch.

## Component lifecycle on Arch/CachyOS

RetroCD uses distribution-managed CDEmu components rather than privately bundling a second daemon/kernel stack.

The implemented lifecycle manager:

- reads installed package versions through pacman;
- queries daemon and libMirage runtime versions and CDEmu interface version over the host session D-Bus;
- verifies that `modinfo` resolves VHBA for the running kernel;
- verifies that `/dev/vhba_ctl` is a host character device and that the `vhba` module is loaded;
- determines the effective VHBA provider from the resolved module file and `pacman -Qo`;
- accepts a kernel-bundled provider such as `kernel:linux-cachyos` without installing a duplicate standalone/DKMS VHBA package;
- requires running-kernel headers only when the effective provider is actually DKMS;
- treats `cdemu-client` as optional diagnostics;
- reports pending component updates without performing them automatically.

The explicit updater performs a full Arch/CachyOS `pacman -Syu`, never a partial upgrade. Before it can run it requires Bottles/Bubblejail closed and every CDEmu media device empty. The GUI shows the exact transaction first; the terminal helper requires the literal confirmation `AGGIORNA`, then pacman retains its own interactive confirmation. The helper stops the CDEmu user service before the transaction when necessary, restarts it afterwards and runs a new health check. It never uses `--noconfirm`, never removes pre-existing packages automatically and never installs a second VHBA provider when the kernel already supplies one.

A source-build fallback is not part of the default architecture.

## Eject and cleanup policy

Single-device eject can neutralise the active live bridge before unloading the selected media. `Espelli tutto` is intentionally conservative: it requires Bottles closed, cleans an inactive RetroCD-owned multidisc cache, and unloads only media whose reported source files remain under the authorised RetroCD archive root. It does not remove generic CDEmu devices and leaves media loaded by unrelated clients outside that root untouched.

Multidisc cache device removal is ownership-sensitive. RetroCD removes appended cache devices only while the device count and mappings still prove that the suffix belongs to the current controller session; otherwise it unloads what it can and leaves ambiguous devices present rather than risking another client's drive.

## Acceptance tests

Before merging this hardening into `main`, validate on the target CachyOS system with Bottles fully closed before each launch:

1. launch Bottles without optical media and require both pre- and post-launch proof of `sr=hidden`, `sg=hidden`, `/mnt/cdemu=hidden`, VHBA hidden and CDEmu D-Bus blocked;
2. launch with only the RO mount exposed and require both proofs of `/mnt/cdemu=RO`, no raw optical nodes, VHBA hidden and D-Bus blocked;
3. launch with the exact raw `/dev/srN` enabled and require both proofs of exactly that node, no `sgN`, plus the expected RO mount policy;
4. test explicit `/dev/sgN` exposure if that advanced feature is retained and require both proofs of exactly the mapped `srN` + `sgN` pair;
5. run the Discworld Noir live multidisc flow and require both proofs of one active `srN`, no cached optical nodes, no `sgN`, `/mnt/cdemu=RO`, VHBA hidden and D-Bus blocked;
6. confirm normal cache cleanup after Bottles exits;
7. verify `Espelli tutto`, including preservation of media outside the authorised RetroCD root;
8. verify the lifecycle health check and updater negative paths (Bottles running, media loaded, user cancellation);
9. rerun the full unit/static CI gate and the regression checks for settings, GPU, multidisc, verifier/scanner, whitelist and network-OFF defaults.

Do not weaken a failed proof to a warning for compatibility. A game that needs a broader optical surface must receive a narrowly reviewed policy change rather than an implicit fallback.
