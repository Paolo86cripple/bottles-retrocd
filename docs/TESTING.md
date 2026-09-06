# Testing

Before a release, close Bottles completely and run the three tests in the **Test** tab.

## 1. CDEmu + UDisks2

Expected:

- temporary drive created and mapped;
- image loaded via D-Bus;
- raw `/dev/srX` reported read-only by the kernel;
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

## 3. CD → Bubblejail

Expected:

- temporary CDEmu drive and RO host mount;
- raw `/dev/srX` is read-only and visible in the jail;
- `/mnt/cdemu` is visible and not writable;
- unrelated Data paths stay hidden;
- cleanup removes the temporary device.

## Operational runner test

1. Enable network for one launch.
2. Start Bottles and install a runner.
3. Close Bottles completely.
4. Confirm the runner exists under the private instance HOME, normally:
   `~/.local/share/bubblejail/instances/Bottles/home/.local/share/bottles/runners/`.
5. Reopen with network OFF and confirm the runner remains available.
