# Testing

Before packaging/release, close Bottles completely and run the relevant runtime tests in the **Test** tab plus one normal secured Bottles launch.

## 1. Archive root

Expected:

- `~/.config/bottles-retro-cd/config.toml` uses schema 2 and persists `archive_root`;
- a legacy target path is migrated only when it actually exists;
- migration/selection changes configuration only and does not move or modify dump files;
- a newly selected archive persists after closing and reopening RetroCD;
- the archive root and its ancestors cannot be added as persistent Bubblejail shares.

## 2. CDEmu + UDisks2

Expected:

- temporary drive created and mapped;
- image loaded via D-Bus;
- `/dev/srX` validated as the CDEmu-mapped SCSI optical block device;
- DPM, transfer-rate, bad-sector and CSS options get/set/get successfully;
- UDisks2 creates a RO mount;
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

The isolation sentinel is created before the test and removed afterward; a nonexistent machine-specific path is never accepted as isolation proof.

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

The target Ryzen 7 9800X3D iGPU and Radeon RX 9070 XT paths have already passed this validation.

## 5. Display and preference persistence

Expected:

- Auto does not force a Wine display backend;
- native Wayland works when selected;
- XWayland keeps Bottles/GTK usable on Wayland while Wine/Proton takes the X11/XWayland path;
- forcing XWayland does not add filesystem, network, GPU or optical permissions;
- Bottles global preferences persist through the isolated GSettings `keyfile` backend after a full close/reopen.

Discworld Noir has been target-validated with `proton-cachyos-native` + D7VK: XWayland enters fullscreen directly with working audio.

## 6. CD → Bubblejail

Expected:

- temporary CDEmu drive and RO host mount;
- raw `/dev/srX` is the validated CDEmu optical device and is visible only when explicitly enabled;
- `/mnt/cdemu` is visible and not writable when requested;
- real temporary host sentinel directories stay hidden;
- cleanup removes temporary resources.

## 7. Redump/TOSEC verifier

Expected:

- official/local DAT index reports non-zero catalog/game/ROM counts;
- a known exact dump reports `MATCH 1:1`;
- partial/incorrect data reports `MISMATCH`;
- duplicate complete DAT records remain `AMBIGUOUS`;
- verification never mounts or executes the image;
- descriptor/payload content and `mtime_ns` remain unchanged before/after verification;
- protection scanning is reported separately from cryptographic DAT matching;
- oversized malformed ISO directory extents are rejected fail-closed.

## 8. Multidisc

Use an explicit saved set. Verify live swapping without closing Bottles, then close Bottles and require automatic cache cleanup. The selected active `/dev/srX` must remain stable and cached drives must not be exposed to Wine.

## Automated gate

```sh
PYTHONWARNINGS='error::ResourceWarning' python -m unittest discover -s tests -v
bash -n run-local.sh
```

Expected current count: **132 tests PASS**. CI also compiles every Python module including `display_backend.py` and rejects `os.system`, `shell=True`, `eval` and dynamic `exec` patterns.

## Immediate pre-merge acceptance for `review/pre-packaging-cleanup`

1. verify the archive root was migrated/selected correctly;
2. reselect the same archive and prove persistence after restart;
3. run **Test Bubblejail** and require the temporary host sentinel hidden;
4. run **Test CD → Bubblejail** and require both integration sentinels hidden plus RO optical policy PASS;
5. launch Bottles and require GPU + Retro Optical pre/post PASS;
6. repeat the working Discworld Noir XWayland launch and confirm direct fullscreen/audio.

Only after these pass should the cleanup branch be merged and used as the packaging source baseline.

### Note on `/sys/class/block/srX/ro`

For CDEmu/VHBA this flag may be `0` even for a normally loaded optical image. It is diagnostic only. Mounted filesystems must still be verified read-only, and raw device exposure remains optional.
