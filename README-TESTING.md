# Testing Bottles RetroCD 0.4.0

This tree is the pre-packaging 0.4.0 candidate. Running it locally does not install files under `/usr`.

Start with:

```sh
./run-local.sh
```

The existing Bubblejail instance `Bottles` is reused; no second persistent instance is created.

## Automated regression suite

```sh
PYTHONWARNINGS='error::ResourceWarning' python -m unittest discover -s tests -v
bash -n run-local.sh
```

Current expected count: **151 tests PASS**.

CI also:

- compiles every application module, including the final display/gamepad GUI wrapper, `gamepad_hotplug.py`, `gamepad_ns_entry.py` and `gamepad_ns_helper.py`;
- promotes `ResourceWarning` to an error;
- checks `run-local.sh` syntax;
- rejects `os.system`, `shell=True`, `eval` and dynamic `exec` in Python paths.

## Final pre-packaging target-machine gate

The GPU/optical/display paths, static Xbox controller isolation and exact-node physical hotplug broker have passed target-machine validation. The remaining release gate covers archive-root portability, Sandbox scroll, real-sentinel isolation and one final launch regression.

With Bottles fully closed:

1. pull and run `review/pre-packaging-cleanup`;
2. confirm **Archivio RetroCD** shows the existing archive automatically on the legacy target installation;
3. inspect `~/.config/bottles-retro-cd/config.toml` and require `schema_version = 2` plus the correct `archive_root`;
4. reselect the same archive through **Scegli cartella…**, close RetroCD completely, reopen it and confirm the choice persists;
5. confirm the **Sandbox** tab scrolls vertically and all controls, including Gamepad and **Avvia Bottles**, remain reachable;
6. run **Test Bubblejail** and require PASS for the real temporary non-whitelisted host sentinel;
7. run **Test CD → Bubblejail** with a known disc and require both temporary host sentinels hidden, `/mnt/cdemu` RO when enabled, and the exact raw optical node only when requested;
8. launch Bottles once and require GPU pre/post plus Retro Optical pre/post PASS lines;
9. select XWayland and confirm Bottles still opens; for Discworld Noir confirm direct fullscreen and working audio.

Changing or migrating the archive root must not alter dump contents, names, paths or mtimes.

## Gamepad / hotplug behavior

Gamepad support is managed through Bubblejail's existing `[joystick]` service. RetroCD does **not** bind all of `/dev/input` and 0.4.0 does not expose `/dev/hidraw*` for the standard controller path.

The pre-launch **Test gamepad** is fail-closed: the jail must show exactly the host-detected joystick node plus its matching evdev node(s). Node numbers are not contractual and may change after disconnect/reconnect.

After Bottles launch, the RetroCD hotplug monitor polls only supported controller identity. On initial activation it overlays/records the already-present Bubblejail joystick surface without sending a synthetic udev event, so the expected marker is:

```text
udev=initial-static
```

On a real add/remove/reconnect event, the helper rebuilds only the exact gamepad nodes and matching minimal sysfs subtree, and emits matching libudev notifications for Wine/winebus. The namespace entry path discovers the user namespace that owns Bubblejail's mount namespace with Linux `NS_GET_USERNS`, prepares detached exact-node mounts in a private staging mount namespace, revalidates pinned device/sysfs identity, then enters the active Bubblejail mount/network namespaces. The expected change marker is:

```text
udev=notified
```

Every successful result must also report `sysfs=exact` and `hidraw=hidden`. Any namespace, sysfs, notification or post-change isolation failure must produce `[FAIL] Gamepad hotplug`; do not work around it by broadening `/dev/input`, adding hidraw access or elevating privileges.

Target validation on 2026-09-10 passed the complete physical cycle with an Xbox One S controller:

- initial running-Bottles surface: `event9, js0`, writable, `sysfs=exact`, `udev=initial-static`, `hidraw=hidden`;
- physical disconnect: `nodi=nessuno`, `sysfs=exact`, `udev=notified`, `hidraw=hidden`;
- reconnect without restarting Bottles: `event9, js0`, writable, `sysfs=exact`, `udev=notified`, `hidraw=hidden`.

Switch/gyro controllers that require hidraw are out of scope for 0.4.0.

## Archive root behavior

Configuration schema 2 persists:

- `gpu_pci`;
- `display_backend`;
- `archive_root`.

On the existing target machine, the previous `/run/media/<user>/Data/Downloads/retropc` directory is migrated only if it exists. Migration stores the path; it does not move data.

A new installation has no machine-specific archive default and must select one explicitly.

Explicit RO sharing of the configured archive root and its subdirectories is allowed; RW access to any part of the archive is forbidden. Ancestors remain forbidden in both modes. Verify that an archive RO whitelist entry passes audit, is readable inside Bubblejail and rejects writes, while the adjacent host sentinel stays hidden. Optical mounts/devices retain the reviewed dynamic Retro Optical policy.

## CDEmu + UDisks2

From the **Test** tab, **Test CDEmu + UDisks2** should prove:

- temporary drive creation and mapping;
- D-Bus image load/unload;
- exact CDEmu optical block-device identity;
- DPM, transfer-rate, bad-sector and CSS options get/set/get;
- UDisks2 read-only mount;
- denied write attempt;
- safe temporary-device cleanup.

`cdemu-client` is optional. RetroCD controls CDEmu through D-Bus. `udisksctl` is required for UDisks2 RO mounts and live multidisc behavior.

## Bubblejail

**Test Bubblejail** should prove:

- whitelist audit PASS;
- persistent `[network]` absent;
- private HOME writable while a real host-HOME marker remains invisible;
- configured RW paths writable;
- configured RO paths visible but not writable;
- a real temporary non-whitelisted host path remains invisible;
- only loopback with network OFF;
- Wayland and XWayland/X11 surfaces available according to the profile;
- audio and GPU/Vulkan surfaces available as intended.

The real sentinel is created for the test and removed afterward. Isolation is never inferred from a machine-specific path that might simply not exist.

## GPU fail-closed launch

The automatic launch guard has already passed target-machine tests on the Ryzen 7 9800X3D iGPU and Radeon RX 9070 XT.

For any final acceptance launch require:

- valid stable PCI identity;
- selected DRM nodes present and live;
- known non-selected DRM nodes absent;
- exactly one Vulkan GPU with matching vendor/device IDs;
- `DRI_PRIME` positively proven during pre-launch;
- post-launch effective isolation proven through the already-running Bubblejail helper path.

Any missing proof must fail closed and terminate/refuse the launch rather than silently continue.

## Display and Bottles preferences

The persistent display choices are:

- **Auto**;
- **Wayland nativo**;
- **XWayland**.

XWayland is a compatibility fallback. It does not add network, filesystem, GPU or optical permissions. Bottles/GTK remains free to use Wayland while Wine/Proton takes the X11/XWayland path.

Bottles global preferences use `GSETTINGS_BACKEND=keyfile` inside the private Bubblejail HOME. Dark mode and the temporary/cache preference have already been confirmed persistent after a complete Bottles close/reopen.

## CD → Bubblejail

The integrated test creates a temporary CDEmu drive and real host sentinel directories, then verifies:

- the exact `/dev/srX` is visible when explicitly requested;
- `/mnt/cdemu` is visible and read-only when a filesystem mount is enabled;
- unrelated real host sentinels are not visible;
- cleanup unloads/unmounts and removes temporary resources safely.

## Multidisc

A saved explicit set is required for live multidisc. Autodetection is only advisory and is never persisted as policy.

The target end-to-end acceptance remains:

1. load Disc 1;
2. enable UDisks2 RO + `/mnt/cdemu` + live multidisc;
3. launch Bottles;
4. require launch security probes PASS;
5. swap 1→2→3→2 without closing Bottles;
6. close Bottles;
7. require automatic cache cleanup.

Discworld Noir three-disc live swapping has already passed this validation.

## Verifier

The **Verifica** tab provides official Redump PC/TOSEC updates, local DAT import, single/set verification, protection scan and DAT↔scanner comparison.

Required invariants:

- exact known data reports `MATCH 1:1`;
- duplicate complete records remain `AMBIGUOUS`;
- incorrect/partial data remains `MISMATCH`;
- verification never mounts or executes the dump;
- descriptor/payload content and `mtime_ns` remain unchanged;
- scanner evidence never overrides cryptographic DAT matching.

The updater must remain HTTPS-only to approved official hosts, bounded, staged and rollback-safe.

## Operational runner test

Runner persistence has already passed on the target system. To repeat:

1. enable network for one launch;
2. install/download a runner in Bottles;
3. close Bottles fully;
4. reopen with network OFF;
5. confirm the runner remains under Bubblejail's private HOME and is still usable.

## Security boundary

Bubblejail protects Bottles/Wine. The GTK controller, gamepad hotplug helpers, verifier, CDEmu daemon and libMirage are host-side and run with the logged-in user's permissions, so all host-side archive/DAT parsing treats inputs as untrusted data. The hotplug helpers are limited to the namespaces of the active `Bottles` instance and validated gamepad device/sysfs references; they do not add a persistent broad device share or require privilege elevation.
