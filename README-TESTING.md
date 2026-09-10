# Testing Bottles RetroCD 0.4.0

This tree is the pre-packaging 0.4.0 candidate. Running it locally does not install files under `/usr`. User-facing terminal examples use fish syntax.

Start with:

```fish
./run-local.sh
```

The existing Bubblejail instance `Bottles` is reused; no second persistent instance is created.

## Automated regression suite

```fish
env PYTHONWARNINGS='error::ResourceWarning' python -m unittest discover -s tests -v
bash -n run-local.sh
```

Current expected count: **151 tests PASS**.

CI also compiles every application module including the final display/gamepad wrapper and namespace helpers, promotes `ResourceWarning` to an error, checks `run-local.sh`, and rejects `os.system`, `shell=True`, `eval` and dynamic `exec` in Python application paths.

## Final pre-packaging target-machine gate — PASS

The complete 0.4.0 real-machine gate passed on 2026-09-10:

1. schema-2 archive root and private config permissions — PASS;
2. GUI archive re-selection and restart persistence — PASS;
3. archive metadata signature before/after selection identical — PASS;
4. resize + vertical scrolling across all notebook pages — PASS;
5. Test Bubblejail with a real temporary non-whitelist sentinel — **PASS=17 FAIL=0 WARN=0**;
6. Test CD → Bubblejail with real temporary sentinels and verified RO optical mount — PASS;
7. final secured Bottles launch with GPU pre/post + Retro Optical pre/post proof — PASS;
8. final Discworld Noir XWayland regression — PASS; game starts correctly with the previously validated fullscreen/audio behavior;
9. standard Xbox One S initial exact-node proof during the final launch — PASS (`event9 + js0`, `sysfs=exact`, `udev=initial-static`, `hidraw=hidden`).

## Gamepad / hotplug behavior

Gamepad support is managed through Bubblejail's existing `[joystick]` service. RetroCD does **not** bind all of `/dev/input` and 0.4.0 does not expose `/dev/hidraw*` for the standard-controller path.

The pre-launch **Test gamepad** is fail-closed: the jail must show exactly the host-detected joystick node plus its matching evdev node(s). Node numbers are not contractual and may change after disconnect/reconnect.

Initial monitor activation uses the already-present static joystick surface and reports:

```text
sysfs=exact · udev=initial-static · hidraw=hidden
```

A real add/remove/reconnect rebuilds only the exact gamepad nodes and matching minimal sysfs subtree, emits matching libudev notifications for Wine/winebus, and reports:

```text
sysfs=exact · udev=notified · hidraw=hidden
```

The namespace entry path discovers the user namespace that owns Bubblejail's mount namespace with Linux `NS_GET_USERNS`, prepares detached exact-node mounts in a private staging mount namespace, revalidates pinned device/sysfs identity, then enters the active Bubblejail mount/network namespaces. No privilege elevation or broad input fallback is used.

Physical Xbox One S validation passed for initial activation, disconnect to an empty exact surface, and reconnect without restarting Bottles.

Switch/gyro controllers that require hidraw are out of scope for 0.4.0.

## Archive root behavior

Configuration schema 2 persists `gpu_pci`, `display_backend` and `archive_root`.

On an existing target installation, the historical `/run/media/<user>/Data/Downloads/retropc` directory is migrated only when it exists. Migration stores the path; it does not move data. New installations must select an archive explicitly.

Explicit RO sharing of the configured archive root and its subdirectories is allowed. RW access to any part of the archive is forbidden, and ancestors remain forbidden in both modes. Selecting an archive does not automatically share it.

Final target validation confirmed `0700` on the config directory, `0600` on `config.toml`, persistence after restart and identical pre/post archive metadata signatures.

## CDEmu + UDisks2

From the **Test** tab, **Test CDEmu + UDisks2** should prove temporary drive creation/mapping, D-Bus load/unload, exact SCSI optical identity, advanced-option get/set/get, verified UDisks2 RO mount, denied write and safe cleanup.

`cdemu-client` is optional. RetroCD controls CDEmu through D-Bus. `udisksctl` is required for UDisks2 RO mounts and live multidisc behavior.

The CDEmu/VHBA block-layer `ro` flag may report RW and is diagnostic only. The independently verified UDisks2 filesystem mount is authoritative for the RO policy.

## Bubblejail

**Test Bubblejail** proves whitelist audit, no persistent `[network]`, private HOME, hidden real HOME/`.ssh`, configured RW/RO semantics, a real hidden non-whitelist sentinel, loopback-only base networking, and the intended Wayland/X11/audio/GPU/Vulkan surfaces.

Final target result: **17 PASS, 0 FAIL, 0 WARN**.

## GPU fail-closed launch

The automatic launch guard has passed target-machine tests on both AMD GPU paths. Any final acceptance launch must prove stable PCI identity, live selected DRM nodes, known non-selected DRM nodes absent, exactly one Vulkan GPU with matching vendor/device IDs, pre-launch `DRI_PRIME`, and post-launch effective isolation inside the already-running Bubblejail instance.

Missing proof is failure and must terminate/refuse the launch rather than silently continue.

## Display and Bottles preferences

Persistent choices are **Auto**, **Wayland nativo** and **XWayland**. XWayland is a compatibility fallback and does not add filesystem, network, GPU or optical permissions.

Bottles global preferences use `GSETTINGS_BACKEND=keyfile` inside the private Bubblejail HOME. Preference persistence has already passed target testing.

Discworld Noir with `proton-cachyos-native` + D7VK passed the final XWayland regression on 2026-09-10.

## CD → Bubblejail

The integrated test creates a temporary CDEmu drive and real temporary host sentinel directories, then proves the exact optical device policy, `/mnt/cdemu` RO and sentinel invisibility, followed by cleanup.

Final target result: `/dev/sr1` validated as SCSI optical type 5, host mount verified RO, both real sentinels hidden, `/mnt/cdemu` visible/non-writable and temporary-drive cleanup PASS.

## Multidisc

A saved explicit set is required for live multidisc. Autodetection is advisory only and never persisted as policy. Discworld Noir three-disc 1→2→3→2 live swapping and automatic cleanup have already passed target validation.

## Verifier

The **Verifica** tab provides official Redump PC/TOSEC updates, local DAT import, single/set verification, protection scan and DAT↔scanner comparison.

Required invariants remain: unique exact data reports `MATCH 1:1`, equivalent duplicate complete records remain `AMBIGUOUS`, incorrect/partial data remains `MISMATCH`, verification never mounts/executes the dump, source content/mtime remain unchanged, and scanner evidence never overrides cryptographic DAT matching.

The updater remains HTTPS-only to approved official hosts, bounded, staged and rollback-safe.

## Operational runner test

Runner persistence has already passed on the target system. If repeated, enable network for one launch, install/download the runner, close Bottles fully, reopen with network OFF, and confirm the runner remains usable from Bubblejail's private HOME.

## Security boundary

Bubblejail protects Bottles/Wine. The GTK controller, gamepad hotplug helpers, verifier, CDEmu daemon and libMirage are host-side and run with the logged-in user's permissions, so host-side archive/DAT parsing treats inputs as untrusted data. The hotplug helpers are limited to the active `Bottles` instance and validated gamepad device/sysfs references; they do not add a persistent broad device share or require privilege elevation.

## Merge status

The technical pre-packaging gate is complete. PR #3 may be merged after the final documentation-only CI remains green and the repository owner explicitly chooses to merge. Packaging then starts from merged `main`.
