# Testing 0.4.0-rc2 + verifier candidate

This tree is intended to be run locally before packaging. Nothing here installs files under `/usr`.

Start the GTK application with:

```sh
./run-local.sh
```

The existing Bubblejail instance `Bottles` is reused; no second persistent instance is created.

## Automated regression suite

Run:

```sh
PYTHONWARNINGS='error::ResourceWarning' python -m unittest discover -s tests -v
bash -n run-local.sh
```

The current branch suite contains **73 tests**:

- 19 original sandbox/settings/multidisc/bridge tests;
- 8 additional GPU fail-closed validation tests;
- 35 Redump/TOSEC verifier, Logiqx index, hash-cache and updater tests;
- 12 read-only protection-scanner tests.

The GPU tests cover rejection of an implicit default GPU, malformed stable identity, positive proof of the selected nodes, rejection of visible non-selected DRM nodes, Vulkan vendor/device mismatch, multiple Vulkan devices, missing proof markers, and the distinction between pre-launch environment proof and post-launch effective-sandbox proof.

The verifier tests include path-escape rejection, Windows absolute CUE rejection, streaming hash/cache invalidation, exact/partial/ambiguous DAT matches, ZIP traversal and ZIP symlink rejection, official-host HTTPS policy, local DAT immutability, corrupt-update rollback and injected `os.replace()` failure rollback.

The scanner tests include cooked/raw/Joliet parsing, signature detection, DAT↔scanner comparison and fail-closed rejection of an oversized ISO directory extent.

## Mandatory GPU/Bubblejail real-machine validation

The final launch guard is security-sensitive and must be tested on the target CachyOS machine after pulling the candidate.

With Bottles fully closed:

1. Select the **Ryzen 7 9800X3D integrated GPU**.
2. Press **Test Vulkan** and require a PASS.
3. Launch Bottles. The cumulative log must contain both a `GPU pre-avvio` PASS and a `GPU post-avvio` PASS before the launch is considered successful.
4. Close Bottles completely.
5. Repeat with the **Radeon RX 9070 XT**.

Expected policy:

- no GPU / invalid GPU metadata / missing DRM character device -> launch refused;
- missing `--debug-bwrap-args` support -> launch refused;
- selected DRM node missing in the jail -> launch refused;
- any known DRM node from the non-selected GPU visible -> launch refused;
- `DRI_PRIME` not positively confirmed by the **pre-launch** probe -> launch refused;
- the **post-launch** attached-shell probe does not depend on its shell `DRI_PRIME` value, but must still positively prove selected-node presence, non-selected-node absence, exactly one Vulkan GPU and matching vendor/device identity;
- zero or more than one Vulkan GPU -> launch refused;
- vendor/device mismatch -> launch refused;
- post-launch debug-shell attachment or effective-isolation proof failure -> the exact Bubblejail launch process group is terminated and the GUI reports failure.

## Existing runtime validation

Run the tests in the **Test** tab with Bottles fully closed:

1. **CDEmu + UDisks2** — temporary device creation, D-Bus load/unload, advanced CDEmu options, optical-device identity, UDisks2 RO mount and denied write, followed by cleanup.
2. **Bubblejail** — private HOME, dynamic RO/RW whitelist, hidden unshared Data, network isolation, Wayland/XWayland, audio, GPU/Vulkan and dconf.
3. **CD → Bubblejail** — temporary CDEmu device plus `/mnt/cdemu` RO inside the jail, raw `/dev/srX` as an explicit compatibility path, while unrelated Data paths stay hidden.
4. **Bridge/cache multidisc** — static bridge target switching and cached RO mount lifecycle.

The Test tab is a cumulative application log. It records normal operations such as load/eject, Bottles launch, GPU pre/post probes, disc swaps and cache cleanup. **Copia log** copies it; **Pulisci log** clears only the visible in-memory log and deliberately does not append a new log line after clearing.

## Verifier validation

The **Verifica** tab provides:

- **Aggiorna Redump PC**;
- **Aggiorna TOSEC**;
- **Importa DAT locali…** under a separate `manual` source namespace;
- **Verifica immagine**;
- **Verifica set multidisco**;
- **Scansiona protezioni**;
- **Verifica + confronta scanner**.

Before testing a real archive, update/import DATs and confirm the catalog counter is non-zero. A successful exact result must say `MATCH 1:1`. An ambiguous duplicate must remain `AMBIGUOUS`; do not treat it as a verified unique match.

The verifier must not change the dump tree. For a real test sample, record content hash and `mtime_ns` of descriptor/payload files before and after verification and confirm they are unchanged. Verification must work without mounting the image.

The protection scanner is evidence-only: it reads ISO9660/Joliet/common raw-sector layouts directly and performs a raw streaming signature pass. Use **Verifica + confronta scanner** to see an explicit DAT↔scanner statement. Scanner absence of a signature does not override a cryptographic DAT match, and scanner evidence does not by itself turn a DAT mismatch into a match.

## Updater failure tests

The updater is deliberately transactional. It must satisfy all of the following:

- reject non-HTTPS URLs;
- reject redirects to hosts outside the Redump/TOSEC allow-list;
- reject path traversal and symlink members in ZIP archives;
- bound download/member/unpacked sizes;
- parse/index all staged DATs before replacing live data;
- keep the previous DAT directory and SQLite catalog byte-identical if staging/parse fails;
- restore the previous generation if a filesystem replace fails after the old generation has already been moved to rollback paths.

These cases are part of `tests/test_verifier_backend.py`.

## Operational Bottles test

The GUI may launch Bottles with no CD loaded, but a valid explicitly selected GPU is always required.

1. Enable network for one launch only.
2. Start Bottles and install a runner.
3. Close Bottles completely.
4. Confirm the runner was written under the Bubblejail private HOME, normally `~/.local/share/bubblejail/instances/Bottles/home/.local/share/bottles/runners/`.
5. Reopen with network OFF and confirm the runner is still available.

This test previously passed with `soda-11.0-8` on the target CachyOS system.

## Whitelist

The **Whitelist** tab edits the real `root_share` section of:

`~/.local/share/bubblejail/instances/Bottles/services.toml`

RO and RW entries are separate. Before writing, the GUI validates and canonicalizes paths, refuses broad/overlapping shares, and creates a backup at:

`services.toml.bottles-retro-cd.bak`

The CDEmu mount is never added to the persistent whitelist; it is injected RO for the individual launch/test only.

## Security boundary

The whitelist constrains Bottles/Wine inside Bubblejail. The GTK controller, verifier, CDEmu daemon and libMirage remain host-side and run with the logged-in user's normal permissions. All optical/DAT parsing paths therefore treat their inputs as untrusted data.

## Final multidisc validation before release

A saved explicit set is required for live multidisc. Existing sets are reused unchanged. To create a new set from Disc 1, select its original descriptor and press **Crea set da questo disco**, then add Disc 2/3 with **Aggiungi disco…**. Autodetection is only a hint and is not persisted automatically.

The end-to-end hardware test remains: load Disc 1 on the active CDEmu drive, enable UDisks2 RO + `/mnt/cdemu` + live multidisc, launch Bottles, confirm both GPU probe PASS lines, swap 1→2→3→2 without closing Bottles, then close Bottles and verify the log first reports cache cleanup start and then successful cleanup. Cleanup runs on a worker so the GTK UI stays responsive.
