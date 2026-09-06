# Changelog

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
