# Changelog

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
