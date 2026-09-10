# Testing

Before packaging/release, close Bottles completely and run the relevant runtime tests in the **Test** tab plus one normal secured Bottles launch. User-facing terminal examples use fish syntax.

## 1. Archive root

Expected:

- `~/.config/bottles-retro-cd/config.toml` uses schema 2 and persists `archive_root`;
- a legacy target path is migrated only when it actually exists;
- migration/selection changes configuration only and does not move or modify dump files;
- a newly selected archive persists after closing and reopening RetroCD;
- the archive root may be explicitly shared RO, but RW access within it and ancestor shares are rejected.

Final 0.4.0 target result: **PASS**. Config directory/file permissions are `0700`/`0600`; GUI re-selection persisted; pre/post archive metadata signatures were identical.

## 2. CDEmu + UDisks2

Expected:

- temporary drive created and mapped;
- image loaded via D-Bus;
- `/dev/srX` validated as the CDEmu-mapped SCSI optical block device;
- DPM, transfer-rate, bad-sector and CSS options get/set/get successfully;
- UDisks2 creates a verified RO mount;
- write attempt on the mount is denied;
- temporary device is removed during cleanup.

`cdemu-client` is optional and must not be required merely to start RetroCD.

## 3. Bubblejail

Expected:

- whitelist audit PASS;
- persistent `[network]` absent;
- private HOME writable while a real host-HOME marker remains invisible;
- each configured RW path is writable;
- each configured RO path rejects writes;
- a real temporary non-whitelisted host sentinel remains invisible;
- only loopback is present with base network OFF;
- Wayland, XWayland/X11, audio and GPU/Vulkan surfaces are available according to the profile.

Final 0.4.0 target result: **PASS=17 FAIL=0 WARN=0**.

## 4. GPU fail-closed launch

For each GPU path under acceptance testing:

1. select the GPU;
2. run **Test Vulkan** and require PASS;
3. launch Bottles;
4. require both `GPU pre-avvio` and `GPU post-avvio` PASS lines;
5. confirm selected DRM nodes are present and known non-selected nodes absent;
6. confirm exactly one Vulkan device with matching vendor/device identity;
7. close Bottles completely before changing GPU/backend.

Any missing/invalid GPU identity, missing DRM character device, unsupported Bubblejail runtime argument, missing positive proof marker, visible non-selected DRM node, multiple Vulkan GPUs, vendor/device mismatch or failed post-launch attachment must fail closed. A post-launch proof failure must terminate the launched process group.

Both target AMD GPU paths passed. The final Discworld Noir XWayland session again produced GPU pre/post PASS with the non-selected GPUs hidden.

## 5. Display and preference persistence

Expected:

- Auto does not force a Wine display backend;
- native Wayland works when selected;
- XWayland keeps Bottles/GTK usable on Wayland while Wine/Proton takes the X11/XWayland path;
- forcing XWayland does not add filesystem, network, GPU or optical permissions;
- Bottles global preferences persist through the isolated GSettings `keyfile` backend after a full close/reopen.

Final Discworld Noir acceptance with `proton-cachyos-native` + D7VK and XWayland: **PASS**, including the known-good fullscreen/audio behavior.

## 6. CD → Bubblejail

Expected:

- temporary CDEmu drive and RO host mount;
- raw `/dev/srX` is the validated CDEmu optical device when explicitly requested;
- `/mnt/cdemu` is visible and not writable when requested;
- real temporary host sentinel directories stay hidden;
- cleanup removes temporary resources.

Final target result: **PASS**. `/dev/sr1` validated as SCSI optical type 5, host mount RO, two real sentinels hidden, `/mnt/cdemu` visible/read-only and cleanup complete.

The block-layer `ro` flag may report RW for CDEmu/VHBA and is diagnostic only; the verified UDisks2 filesystem mount is the authoritative RO decision.

## 7. Gamepad exact-node/hotplug

Expected:

- static `[joystick]` path exposes only current `jsX` plus matching `eventX` nodes;
- `/dev/hidraw*` remains hidden;
- initial running-Bottles activation reports `sysfs=exact`, `udev=initial-static`, `hidraw=hidden`;
- physical disconnect/reconnect while Bottles remains open reports `udev=notified` and continues to expose exactly the current controller surface.

Final target result: **PASS**, including physical Xbox One S disconnect/reconnect and a final XWayland launch with `event9 + js0` exact and writable.

## 8. Redump/TOSEC verifier

Expected:

- official/local DAT index reports non-zero catalog/game/ROM counts;
- a known exact dump reports `MATCH 1:1`;
- partial/incorrect data reports `MISMATCH`;
- duplicate complete DAT records remain `AMBIGUOUS`;
- verification never mounts or executes the image;
- descriptor/payload content and `mtime_ns` remain unchanged before/after verification;
- protection scanning is reported separately from cryptographic DAT matching;
- oversized malformed ISO directory extents are rejected fail-closed.

## 9. Multidisc

Use an explicit saved set. Verify live swapping without closing Bottles, then close Bottles and require automatic cache cleanup. The selected active `/dev/srX` must remain stable and cached drives must not be exposed to Wine. Discworld Noir three-disc live swapping has already passed the 0.4.0 target gate.

## Automated gate

```fish
env PYTHONWARNINGS='error::ResourceWarning' python -m unittest discover -s tests -v
bash -n run-local.sh
```

Expected current count: **151 tests PASS**. CI also compiles every application module, including the final display/gamepad wrappers and namespace helpers, and rejects `os.system`, `shell=True`, `eval` and dynamic `exec` patterns.

## Pre-packaging acceptance status

The `review/pre-packaging-cleanup` real-machine gate is **complete/PASS**:

1. archive root schema/persistence/immutability — PASS;
2. resize + scroll on all notebook pages — PASS;
3. Test Bubblejail with real sentinel — PASS;
4. Test CD → Bubblejail with real sentinels and RO policy — PASS;
5. final GPU + Retro Optical pre/post secured launch — PASS;
6. final Discworld Noir XWayland launch — PASS;
7. standard gamepad initial exact-node proof during the final launch — PASS.

The branch may be merged only after the final documentation-only CI remains green and the repository owner explicitly chooses to merge. Packaging should use the merged `main` baseline.
