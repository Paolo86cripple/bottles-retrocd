# Changelog

## 0.4.0

First stable Bottles RetroCD release candidate.

### Sandbox / launch hardening

- reuse the dedicated Bubblejail `Bottles` instance with private HOME and deny-by-default host exposure;
- network remains OFF by default and may be enabled only for the selected launch; persistent `[network]` is rejected;
- GPU selection persists by stable PCI address and never silently falls back to Mesa default;
- selected DRM card/render nodes are validated as live character devices, broad `/dev/dri` is masked, and only the selected GPU nodes are rebound;
- mandatory pre-launch and already-running post-launch GPU/Vulkan proofs fail closed and terminate the exact launch process group on proof failure;
- manual **Test Vulkan** uses the same validator;
- added persistent display policy: Auto / native Wayland / XWayland;
- XWayland keeps the Bottles GTK UI free to use Wayland while Wine/Proton uses the X11/XWayland path, without adding filesystem/network/GPU/optical permissions;
- forced display backends validate the existing Bubblejail display services instead of silently modifying the profile;
- Bottles global GSettings use the isolated `keyfile` backend so dark mode, temp/cache preferences and similar settings persist inside the private Bubblejail HOME;
- the Sandbox page is vertically scrollable so all release controls remain reachable on smaller windows;
- added a stable application ID: `io.github.Paolo86cripple.BottlesRetroCD`.

### Gamepad

- standard gamepad access uses Bubblejail's built-in `[joystick]` service rather than a broad `/dev/input` share;
- pre-launch **Test gamepad** compares the exact host/jail `jsX` + matching `eventX` surface, requires readability and rejects unrelated input nodes or `/dev/hidraw*` exposure;
- added a Sandbox gamepad status/toggle and dedicated hotplug status reporting;
- after Bottles launch, RetroCD monitors only supported controller-node identity and keeps the already-running jail synchronized on physical add/remove/reconnect;
- dynamic reconciliation passes only validated gamepad device FDs, recreates the matching minimal sysfs subtree and re-probes the jail after each change;
- initial activation is non-destructive and reports `udev=initial-static` because Wine starts with the existing static Bubblejail joystick surface;
- actual disconnect/reconnect emits matching libudev remove/add notifications inside Bubblejail's network namespace for Wine/winebus and reports `udev=notified`;
- the namespace broker discovers the user namespace that owns Bubblejail's mount namespace with Linux `NS_GET_USERNS`, stages detached exact-node mounts in a private mount namespace, revalidates pinned device/sysfs identity, then enters the active mount/network namespaces;
- node numbering is not assumed stable across reconnect; the accepted surface is always compared with the current host-detected controller nodes;
- any namespace/sysfs/udev/isolation failure reports `[FAIL] Gamepad hotplug`; there is no permissive fallback;
- `/dev/hidraw*` remains excluded and Switch/gyro hidraw support is deliberately out of scope for 0.4.0.

### Portable archive root

- configuration schema bumped to 2 with persistent `archive_root` alongside `gpu_pci` and `display_backend`;
- removed the release-time dependency on a hardcoded `/run/media/<user>/Data` storage layout;
- existing target installations migrate the historical `/run/media/<user>/Data/Downloads/retropc` path only when it actually exists; migration stores the path but never moves/modifies dump data;
- new installations must choose the archive root explicitly;
- explicit RO shares of the archive root/subdirectories are allowed; RW access anywhere within the archive and ancestor shares in either mode are refused;
- Bubblejail/integration tests now use real temporary host sentinels, avoiding false PASS results from non-existent machine-specific paths.

### Retro Optical / CDEmu

- CDEmu is controlled through its D-Bus API model; `cdemu-client` is optional and no longer required by `run-local.sh`;
- fixed false failure on CDEmu `/dev/srX` when the block-layer `ro` flag is 0;
- raw exposure validates the exact CDEmu-mapped Linux SCSI optical block device (type 5);
- block-layer `ro` is diagnostic only; UDisks2 filesystem mounts remain fail-closed read-only;
- raw `/dev/srX` exposure is OFF by default and opt-in for compatibility-sensitive titles;
- `/dev/sgX` remains explicit, advanced and OFF by default;
- CDEmu/libMirage/VHBA lifecycle diagnostics detect the effective provider, including kernel-bundled CachyOS VHBA;
- component update flow requires explicit preview, terminal confirmation and post-update recheck.

### Multidisc

- explicit Redump/TOSEC disc sets start from exactly the selected descriptor; autodetection is advisory and never persisted implicitly;
- live multidisc fails closed unless the active disc belongs to an explicit saved set;
- added automatic post-Bottles cleanup polling and asynchronous cache cleanup;
- cache cleanup revalidates device mappings/count/order before touching appended devices;
- `/mnt/cdemu` points to a real empty private directory during media change;
- saved-set resolution uses exact path membership before naming heuristics;
- original Redump/TOSEC files, names and mtimes remain untouched.

### Redump / TOSEC verifier

- read-only CUE/TOC/CCD/MDS payload resolution with canonical root containment and rejection of descriptor path escape/absolute Windows references;
- one-pass streaming CRC32/MD5/SHA1 hashing with a persistent SQLite cache invalidated by device/inode/size/mtime/ctime changes;
- incremental Logiqx XML indexing into SQLite with source, description, serial, version and protection metadata;
- exact verification requires a complete 1:1 payload multiset against one DAT game; duplicate complete records remain `AMBIGUOUS`;
- exact multidisc-set verification without modifying archive files;
- official Redump PC and TOSEC updater paths restricted to HTTPS and explicit official-host allow-lists;
- bounded, staged DAT updates with ZIP traversal/symlink rejection, validation before install and rollback on failure;
- local DAT import copies metadata only into verifier storage and leaves source DATs untouched;
- read-only protection scanner for ISO9660/Joliet/common raw-sector layouts with bounded directory/file sampling and streaming raw signatures;
- explicit DAT↔scanner comparison while keeping scanner evidence independent from cryptographic verification;
- `verifier_cli.py` provides stats, verify, verify-set, scan, verify-scan and update/import diagnostics.

### UI / diagnostics

- seven tabs: CDEmu, Sandbox, Whitelist, Avanzate, Test, Verifica and Componenti;
- Sandbox includes archive root, GPU, transient permissions, persistent display backend, gamepad controls and a vertical scroller;
- cumulative application log records normal operations, security probes and gamepad hotplug transitions; **Pulisci log** clears only the visible in-memory buffer;
- CI explicitly compiles the display/gamepad wrapper, hotplug monitor, namespace entry helper and namespace mount/udev helper together with all other Python modules.

### Validation

- target-machine validation completed for both AMD GPUs, CDEmu/UDisks2, raw optical, explicit `/dev/sgX`, multidisc, verifier/source immutability, lifecycle/update negative paths, preference persistence, Wayland and XWayland;
- Discworld Noir validated with `proton-cachyos-native` + D7VK; XWayland enters fullscreen directly while preserving audio and the existing sandbox/optical policy;
- Xbox One S static Bubblejail controller path validated with only the current `jsX` + matching `eventX`, readable/writable, no unrelated input or hidraw exposure, and responding inputs;
- exact-node gamepad hotplug physically validated on CachyOS: initial `event9 + js0` with `udev=initial-static`, physical disconnect to an empty exact surface with `udev=notified`, and reconnect without restarting Bottles restoring `event9 + js0` with `udev=notified`; every stage reported `sysfs=exact` and `hidraw=hidden`;
- final pre-packaging regression suite: **151 tests PASS** on the hotplug implementation, plus Python compilation, `ResourceWarning`-as-error, shell syntax and unsafe dynamic execution scan.

## 0.4.0-rc2

- fixed false failure on CDEmu `/dev/srX` when the block-layer `ro` flag is 0;
- validate raw exposure as the exact CDEmu-mapped Linux SCSI optical block device (type 5);
- treat the block-layer RO flag as diagnostic only; UDisks2 filesystem mount remains fail-closed RO;
- raw `/dev/srX` exposure is now OFF by default and opt-in for compatibility-sensitive titles.

## 0.4.0-rc1

- validated CDEmu/UDisks2 and Bubblejail end-to-end on CachyOS;
- validated Bottles runner persistence across temporary network ON/OFF;
- added configurable RO/RW whitelist management;
- added copy-log action;
- split GUI into tabs;
- switched CDEmu control to direct D-Bus API model inspired by gCDEmu;
- added fail-closed raw `/dev/srX` read-only verification;
- fixed GTK worker-thread widget access;
- added Bubblejail runtime-argument compatibility check;
- retain Bottles/Bubblejail launch log in XDG cache;
- refreshed documentation and added standard-library unit tests for whitelist writes.
