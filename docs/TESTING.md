# Testing

Before a release, close Bottles completely and run the runtime tests in the **Test** tab, the GPU launch checks below, and the verifier checks in the **Verifica** tab.

## 1. CDEmu + UDisks2

Expected:

- temporary drive created and mapped;
- image loaded via D-Bus;
- `/dev/srX` validated as the CDEmu-mapped SCSI optical block device;
- DPM, transfer-rate, bad-sector and CSS options get/set/get successfully;
- UDisks2 creates a RO mount;
- write attempt on the mount is denied;
- temporary device is removed during cleanup.

## 2. Bubblejail

Expected:

- whitelist audit PASS;
- persistent `[network]` absent;
- private HOME writable while a host-only marker remains invisible;
- each configured RW path is writable;
- each configured RO path rejects writes;
- an unshared marker under Data stays invisible;
- only loopback is present with base network OFF;
- Wayland, XWayland, audio, GPU/Vulkan and dconf checks pass.

## 3. GPU fail-closed launch

Run once with the Ryzen 7 9800X3D iGPU and once with the Radeon RX 9070 XT.

For each GPU:

1. select the GPU;
2. run **Test Vulkan** and require PASS;
3. launch Bottles;
4. require both `GPU pre-avvio` and `GPU post-avvio` PASS lines in the cumulative log;
5. confirm the non-selected GPU DRM nodes are reported hidden;
6. close Bottles completely before switching GPU.

Any missing/invalid GPU identity, missing DRM character device, unsupported Bubblejail runtime argument, missing positive proof marker, visible non-selected DRM node, multiple Vulkan GPU, vendor/device mismatch, or failed post-launch attachment must make launch fail. A post-launch proof failure must terminate the launched Bubblejail process group.

## 4. CD → Bubblejail

Expected:

- temporary CDEmu drive and RO host mount;
- raw `/dev/srX` is the validated CDEmu optical device and is visible in the jail when explicitly enabled;
- `/mnt/cdemu` is visible and not writable;
- unrelated Data paths stay hidden;
- cleanup removes the temporary device.

## 5. Redump/TOSEC verifier

Expected:

- official or local DAT index reports non-zero catalog/game/ROM counts;
- a known exact dump reports `MATCH 1:1`;
- partial/incorrect data reports `MISMATCH`;
- duplicate complete DAT records remain `AMBIGUOUS`;
- verification never mounts or executes the image;
- descriptor/payload content and `mtime_ns` are byte-for-byte/time-for-time unchanged before and after verification;
- protection scanning is reported separately from cryptographic DAT matching;
- oversized malformed ISO directory extents are rejected by the bounded parser path.

## 6. Multidisc

Use an explicit saved set. Verify a live 1→2→3→2 swap without closing Bottles, then close Bottles and require automatic cache cleanup. The selected active `/dev/srX` must remain stable and cached drives must not be exposed to Wine.

## Automated gate

Current candidate CI must pass:

```sh
PYTHONWARNINGS='error::ResourceWarning' python -m unittest discover -s tests -v
bash -n run-local.sh
```

Expected current count: **73 tests**. CI also compiles all Python modules and rejects `os.system`, `shell=True`, `eval` and dynamic `exec` patterns.

## Operational runner test

1. Enable network for one launch.
2. Start Bottles and install a runner.
3. Close Bottles completely.
4. Confirm the runner exists under the private instance HOME, normally:
   `~/.local/share/bubblejail/instances/Bottles/home/.local/share/bottles/runners/`.
5. Reopen with network OFF and confirm the runner remains available.

### Note on `/sys/class/block/srX/ro`

For CDEmu/VHBA this flag may be `0` even for a normally loaded optical image. It is logged for diagnostics but is not used as the security decision. The mounted filesystem must still be verified read-only, and raw device exposure is optional.
