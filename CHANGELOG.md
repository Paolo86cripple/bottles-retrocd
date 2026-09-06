# Changelog

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
