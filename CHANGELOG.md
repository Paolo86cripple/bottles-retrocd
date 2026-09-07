# Changelog

## Unreleased — multidisc review candidate

- explicit Redump/TOSEC disc sets now start from exactly the selected descriptor (including Disc 1); autodetection remains advisory and is never persisted implicitly;
- live multidisc now fails closed unless the active disc belongs to an explicit saved multidisc set;
- added automatic post-Bottles cleanup polling, asynchronous cache cleanup and blocks GUI close while a live multidisc session is active;
- the Test tab is now a cumulative application log for tests and normal operations; closing Bottles logs cleanup start immediately before the worker removes cache devices;
- CDEmu cache cleanup revalidates device mappings/count/order before touching or removing appended devices;
- `/mnt/cdemu` now points to a real empty private directory while media is being changed;
- app config directory is hardened to mode `0700`; metadata files remain `0600`;
- saved-set resolution uses exact path membership before naming-based autodetection in GUI, cache tests and live Bottles launch;
- regression suite: 19 tests, including Disc 1 explicit-set creation, Redump path/mtime immutability, Alt/Rerelease membership and bridge neutral target.

## Unreleased — GPU selector

- added dynamic GPU detection with stable PCI-address selection instead of `cardX` ordering;
- prefer the integrated GPU on first use and persist the selected PCI address in `~/.config/bottles-retro-cd/config.toml` with mode `0600`;
- apply the selected GPU per Bottles launch using Mesa `DRI_PRIME`;
- added a Vulkan verification action that checks vendor/device identity inside Bubblejail;
- strict GPU isolation masks Bubblejail's broad `/dev/dri` view and re-exposes only the selected GPU's `cardX` and `renderD*` nodes;
- verified on the target dual-AMD system with both the Ryzen 7 9800X3D iGPU and Radeon RX 9070 XT, including successful Bottles launch.

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
