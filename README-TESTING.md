# Testing 0.4.0-rc2

This release candidate is intended to be run locally before packaging.
Nothing in this tree installs files under `/usr`.

Start it with:

```sh
./run-local.sh
```

The existing Bubblejail instance `Bottles` is reused; no second instance is
created.

## Required validation

Run the three tests in the **Test** tab with Bottles fully closed:

1. **CDEmu + UDisks2** — temporary device creation, D-Bus load/unload, advanced
   CDEmu options, CDEmu optical-device identity, UDisks2 RO mount and denied
   write, followed by cleanup.
2. **Bubblejail** — private HOME, dynamic RO/RW whitelist, hidden unshared Data,
   network isolation, Wayland/XWayland, audio, GPU/Vulkan and dconf.
3. **CD → Bubblejail** — temporary CDEmu device plus `/mnt/cdemu` RO inside the
   jail, raw `/dev/srX` as an explicit compatibility path, while unrelated
   Data paths still hidden.

The Test tab is a cumulative application log: it also records normal operations such as load/eject, Bottles launch, disc swaps and cache cleanup. Use **Copia log** to copy the complete session log.

## Operational Bottles test

The GUI may launch Bottles with no CD loaded.

1. Enable network for one launch only.
2. Start Bottles and install a runner.
3. Close Bottles completely.
4. Confirm the runner was written under the Bubblejail private HOME, normally:
   `~/.local/share/bubblejail/instances/Bottles/home/.local/share/bottles/runners/`.
5. Reopen with network OFF and confirm the runner is still available.

This test has already passed with `soda-11.0-8` on the target CachyOS system.

## Whitelist

The **Whitelist** tab edits the real `root_share` section of:

`~/.local/share/bubblejail/instances/Bottles/services.toml`

RO and RW entries are separate. Before writing, the GUI validates and
canonicalizes paths, refuses broad/overlapping shares, and creates a backup at:

`services.toml.bottles-retro-cd.bak`

The CDEmu mount is never added to the persistent whitelist; it is injected RO
for the individual launch/test only.

## Security boundary

The whitelist constrains Bottles/Wine inside Bubblejail. The GTK controller,
CDEmu daemon and libMirage remain host-side and run with the logged-in user's
normal permissions.

## Final multidisc validation before merge

A saved explicit set is required for live multidisc. Existing sets are reused unchanged. To create a new set from Disc 1, select its original descriptor and press **Crea set da questo disco**, then add Disc 2/3 with **Aggiungi disco…**. Autodetection is only a hint and is not persisted automatically.

The final end-to-end hardware test is: load Disc 1 on the active CDEmu drive, enable UDisks2 RO + `/mnt/cdemu` + live multidisc, launch Bottles, swap 1→2→3→2 without closing Bottles, then close Bottles and verify the log first reports that cache cleanup is starting and then reports successful cleanup. Cleanup runs on a worker so the GTK UI stays responsive.
