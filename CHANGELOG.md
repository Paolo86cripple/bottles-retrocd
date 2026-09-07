# Changelog

## Unreleased — Redump/TOSEC verifier final review candidate

- restored the previously reviewed Redump/TOSEC verifier work and integrated it into the current multidisc/GPU `main` lineage;
- added read-only CUE/TOC/CCD/MDS payload resolution with canonical root containment and explicit rejection of descriptor path escape/Windows absolute references;
- added one-pass streaming CRC32/MD5/SHA1 hashing and a persistent SQLite hash cache invalidated by device/inode/size/mtime/ctime changes;
- added incremental Logiqx XML parsing into a persistent SQLite catalog, retaining source, DAT, description, serial, version and protection metadata;
- exact verification now requires a complete 1:1 payload multiset against one DAT game; duplicate complete records remain `AMBIGUOUS` rather than being silently selected;
- added exact multidisc-set verification without modifying archive files;
- added official Redump PC and TOSEC updater paths restricted to HTTPS and an explicit official-host allow-list;
- DAT updates are bounded, staged, parsed and indexed before installation; ZIP traversal/symlinks are rejected and post-swap failures restore the previous generation;
- local DAT import copies metadata only into the verifier data area and leaves original DAT files untouched;
- added a read-only protection scanner for ISO9660/Joliet and common raw-sector layouts plus streaming raw-signature detection;
- added explicit DAT↔scanner comparison while keeping scanner evidence independent from cryptographic DAT matching;
- added `verifier_cli.py` for stats, verify, verify-set, scan, verify-scan and update/import diagnostics;
- added a dedicated **Verifica** GTK tab;
- restored the reviewed **Pulisci log** action using `_clear_log`; it clears the current `Gtk.TextBuffer` only and is disabled while the controller is busy;
- preserved the already validated rc2/multidisc GUI controller byte-for-byte in `bottles-retro-cd-gui-base.py`, with the verifier entrypoint layered as a subclass to minimise regression risk in CDEmu/Bubblejail/GPU paths;
- hardened CI to compile all Python modules, treat `ResourceWarning` as an error, run the full suite and reject `os.system`, `shell=True`, `eval` and dynamic `exec` patterns;
- regression suite restored to **65 tests**: 19 existing + 35 verifier/updater + 11 scanner tests.

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
