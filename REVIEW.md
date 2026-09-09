# Bottles RetroCD 0.4.0 — final pre-packaging review

## Status

The 0.4.0 feature set is frozen except for release blockers. The reviewed runtime architecture remains Bottles/Wine inside the existing Bubblejail instance, with host-side RetroCD controller/gamepad hotplug helper, CDEmu/libMirage and verifier components.

The pre-packaging review originally found three portability/documentation issues, all addressed on `review/pre-packaging-cleanup`:

1. the archive root was still derived from a target-machine-specific `/run/media/<user>/Data` path;
2. `run-local.sh` still required the optional `cdemu` CLI despite the D-Bus backend;
3. one integration test inferred isolation from machine-specific paths that might not exist.

Before packaging, the branch also received two user-facing release-hardening changes: the Sandbox page is vertically scrollable, and standard gamepad support is consolidated around Bubblejail `[joystick]` with exact-node disconnect/reconnect handling. The gamepad implementation deliberately preserves the existing security boundary: no broad `/dev/input` share and no `/dev/hidraw*` exposure for the 0.4.0 standard-controller path.

The branch aligns runtime version/Application ID, CI module list and release documentation.

## Automated gate

Current regression suite: **146 tests PASS** on the exact-node sysfs/udev hotplug implementation.

Additional gates:

- Python syntax/bytecode compilation for every application module, explicitly including display/gamepad wrappers, `gamepad_hotplug.py` and `gamepad_ns_helper.py`: PASS on the implementation head;
- unit tests with `PYTHONWARNINGS=error::ResourceWarning`: PASS;
- `bash -n run-local.sh`: PASS;
- unsafe execution scan for `os.system`, `shell=True`, `eval` and dynamic `exec`: PASS.

The final docs/reporting commits must keep branch CI green before merge.

## Archive-root portability review

Configuration schema is now 2 and persists:

- `gpu_pci`;
- `display_backend`;
- `archive_root`.

The release no longer hardcodes a specific removable-media/storage location. On a legacy target installation, the historical `/run/media/<user>/Data/Downloads/retropc` directory is used only when it actually exists, and the migration writes that location into `config.toml`. No archive file or directory is copied, renamed, moved or rewritten by migration.

New installations have no implicit machine-specific archive location and must select the archive root explicitly from the Sandbox tab.

The configured archive root and its subdirectories may be explicitly shared RO. RW access anywhere within the archive and ancestor shares in either mode are rejected, including canonicalized symlink aliases. The same policy applies when saving a whitelist and auditing an existing profile. Selecting the archive does not automatically share it. Optical mounts/devices retain the existing dynamic Retro Optical policy.

The Bubblejail test creates a real temporary non-whitelisted host sentinel adjacent to the archive and requires it to be invisible inside the jail. The CD→Bubblejail integration path likewise uses temporary real sentinel directories rather than assuming machine-specific paths exist.

## Gamepad / hotplug review

The standard controller path uses Bubblejail's built-in `[joystick]` service. The target Xbox One S controller has already passed the static isolation test with only `js0` + matching `event24` visible, both readable/writable, no unrelated input nodes, no `/dev/hidraw*`, and responding inputs.

RetroCD's hotplug extension keeps that surface narrow:

- host detection accepts supported `jsX` devices and their matching evdev `eventX` siblings;
- the pre-launch test compares the exact host/jail node sets and fails on unrelated input or hidraw exposure;
- after Bottles launch, the monitor watches only the fingerprint of those detected controller nodes;
- initial activation is non-destructive, records/overlays the known-good static surface and reports `udev=initial-static` because no synthetic event is needed at jail startup;
- a physical add/remove/reconnect rebuilds only the exact current device nodes and matching minimal sysfs subtree;
- actual changes emit matching libudev remove/add notifications inside Bubblejail's network namespace for Wine/winebus and report `udev=notified`;
- each reconciliation is re-probed from inside the already-running jail and must still show no unrelated input and no hidraw;
- namespace/sysfs/udev failures are reported as `[FAIL] Gamepad hotplug`; there is no permissive fallback.

Node numbers may change after reconnect, so acceptance compares against the current host-detected pair rather than assuming `event24` forever.

Switch/gyro controllers requiring hidraw remain a deliberate non-goal for 0.4.0.

**Remaining target-machine gamepad gate:** prove physical disconnect and reconnect while Bottles/Wine remains running, then confirm the controller becomes usable again in Wine/a game that supports runtime re-enumeration.

## Display / Bottles preference review

The persistent display choices are:

- Auto;
- native Wayland;
- XWayland.

XWayland removes the Proton native-Wayland opt-ins and reports an X11 session to Bottles/Wine while deliberately keeping the Wayland environment available to the Bottles GTK UI. It requires the existing Bubblejail `x11` + `wayland` services and does not add them automatically.

Bottles global preferences use `GSETTINGS_BACKEND=keyfile`, placing persistent settings under the jail's private HOME instead of exposing/writing the host dconf database.

Target-machine validation already completed:

- Bottles preferences such as dark mode and temporary/cache policy persist after complete close/reopen: PASS;
- XWayland launches Bottles: PASS;
- Discworld Noir via `proton-cachyos-native` + D7VK on XWayland goes directly fullscreen with working audio: PASS;
- native Wayland remains functional: PASS.

## GPU / Bubblejail fail-closed review

- stable PCI identity is authoritative;
- no implicit Mesa-default launch is allowed;
- selected `cardN` + `renderD*` must be live character devices;
- broad `/dev/dri` is masked and only selected nodes are rebound;
- pre-launch proof requires `DRI_PRIME`, selected-node presence, non-selected-node absence, exactly one Vulkan device and matching vendor/device IDs;
- post-launch proof is injected into the already-running Bubblejail helper path and re-proves effective DRM/Vulkan isolation;
- missing proof markers are failures;
- post-launch proof failure terminates the exact launch process group;
- manual Test Vulkan uses the same strict validator.

Target-machine validation has passed on both the Ryzen 7 9800X3D iGPU and Radeon RX 9070 XT.

## Retro Optical / CDEmu review

- CDEmu control is direct D-Bus API; `cdemu-client` is optional;
- raw `/dev/srX` is OFF by default and must match the exact CDEmu mapping plus SCSI optical type 5;
- block-layer `ro` remains diagnostic only;
- UDisks2 filesystem mount state is the read-only security decision;
- `/dev/sgX` remains explicit and OFF by default;
- CDEmu D-Bus and `/dev/vhba_ctl` remain absent from the Bottles sandbox;
- pre/post optical probes validate the exact launch policy;
- lifecycle detects kernel-bundled or package-provided VHBA without duplicating kernel infrastructure.

Previously completed target validation includes no-CD, RO mount, raw optical, explicit `/dev/sgX`, live multidisc and cleanup paths.

## Multidisc review

- saved sets preserve original descriptor/image paths;
- auto grouping is advisory only;
- live multidisc requires an explicit saved set;
- cache drives remain host-side and mounted RO;
- only the active optical device is available to Wine;
- `/mnt/cdemu` is neutralized during swap;
- mapping changes fail closed with rollback;
- cache cleanup revalidates device count/order/mapping before removal;
- normal Bottles exit triggers asynchronous cleanup.

Discworld Noir three-disc Redump live swapping has passed on the target system.

## Verifier / scanner review

Archive material is treated as untrusted host-side data but is never mounted or executed by the verifier.

- CUE/TOC references are canonicalized below the authorised root;
- absolute/traversal references are rejected;
- CCD/MDS companions are resolved without modifying originals;
- CRC32/MD5/SHA1 are streamed in one pass;
- cache validity depends on device/inode/size/mtime/ctime;
- Logiqx XML is indexed incrementally into SQLite;
- exact matches require one complete unique DAT record;
- equivalent complete records remain `AMBIGUOUS`;
- updater networking is HTTPS + official-host allow-list with redirect validation;
- downloads/ZIP extraction are bounded and staged;
- ZIP traversal/symlinks are rejected;
- replacement failures restore the previous live generation;
- ISO/Joliet/raw protection scanning is bounded and evidence-only.

Real-source/dump immutability validation has passed.

## Packaging readiness

After the remaining target-machine gate below, the branch is ready to merge into `main` and become the source baseline for Arch/CachyOS packaging.

Packaging must preserve these requirements:

- stable application ID `io.github.Paolo86cripple.BottlesRetroCD`;
- version `0.4.0`;
- no dependency on `cdemu-client`;
- no extra gamepad runtime dependency beyond Bubblejail's built-in standard joystick support;
- runtime dependency on Python/GTK4/PyGObject, Bubblejail and Vulkan diagnostic tooling;
- UDisks2 available for RO optical mounts/live multidisc;
- CDEmu daemon + libMirage host integration without duplicating a VHBA provider already supplied by the kernel;
- install/remove only application-owned files; never delete user config, private Bottles HOME, archive data or Bubblejail instance data during normal package removal.

## Residual risks / deliberate non-goals

1. GTK controller/gamepad hotplug helper, verifier, CDEmu and libMirage remain host-side processes with the user's permissions.
2. XML/ZIP/image parsing is bounded but still parses untrusted bytes using standard-library/native components.
3. Protection scanning is heuristic evidence, not a complete copy-protection oracle.
4. DAT authenticity relies on HTTPS + official-host allow-list and structural/index validation; there is no uniform detached signature mechanism in this implementation.
5. Abnormal GUI/process termination during live multidisc may leave temporary CDEmu cache drives until recovery/manual cleanup.
6. Upstream Bubblejail helper/namespace behavior changes can make launch or hotplug proofs fail; this remains intentionally fail-closed.
7. XWayland is a compatibility fallback, not a reason to broaden sandbox permissions.
8. Some legacy Windows games enumerate controllers only at startup; RetroCD can prove the Wine-visible device/udev transition but cannot force an individual game to implement runtime re-enumeration.
9. Switch/gyro hidraw support is out of scope for 0.4.0 rather than weakening the device boundary.

## Merge criterion

Merge `review/pre-packaging-cleanup` only after:

1. branch CI remains fully green;
2. target config shows the correct migrated/current archive root without any dump modification;
3. changing/reselecting the archive root from the GUI persists correctly;
4. Sandbox vertical scrolling keeps every release control reachable;
5. **Test gamepad** still proves only the exact standard controller nodes, readable, no unrelated `/dev/input` and no hidraw;
6. first Bottles launch with gamepad ON reports hotplug PASS with `sysfs=exact`, `udev=initial-static`, `hidraw=hidden`;
7. physical controller disconnect while Bottles remains running reports PASS with no gamepad nodes left and `udev=notified`;
8. reconnect without restarting Bottles reports PASS with exactly the new/current `jsX/eventX` nodes, `udev=notified`, no hidraw, and the controller is usable again where Wine/game runtime enumeration permits;
9. **Test Bubblejail** proves the real temporary non-whitelist sentinel is hidden;
10. **Test CD → Bubblejail** passes using the real sentinel path;
11. one normal Bottles launch still produces GPU pre/post + Retro Optical pre/post PASS lines;
12. XWayland still starts Bottles and Discworld Noir remains directly fullscreen with audio.
