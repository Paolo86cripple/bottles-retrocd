# Testing Bottles RetroCD 0.4.1

This tree is the 0.4.1 compatibility-preserving hardening line. Running it locally does not install files under `/usr`. User-facing terminal examples use fish syntax.

Start with:

```fish
./run-local.sh
```

The existing Bubblejail instance `Bottles` is reused; no second persistent instance is created.

## Automated regression suite

```fish
env PYTHONWARNINGS='error::ResourceWarning' python -m unittest discover -s tests -v
bash -n run-local.sh
```

The exact test count may grow during focused hardening; the gate is that the complete suite passes with `ResourceWarning` promoted to an error. CI also compiles every application module, validates shell/Arch packaging syntax, release identity/package metadata and rejects unsafe dynamic-execution patterns.

## 1. Bubblejail base sandbox

With Bottles fully closed, **Test Bubblejail** must prove:

- persistent `[network]` absent;
- private HOME writable while the real host HOME remains hidden;
- host `.ssh` hidden;
- configured RW paths writable and configured RO paths non-writable;
- a real non-whitelist host sentinel hidden;
- loopback-only base networking;
- Wayland/XWayland, audio, selected GPU and Vulkan surfaces available as configured;
- host dconf blocked.

For 0.4.1, dconf is secure only when all of the following agree:

- `[gnome_toolkit] dconf_dbus=false` in the Bubblejail profile;
- Bottles preferences persist via `GSETTINGS_BACKEND=keyfile`;
- host `ca.desrt.dconf` is not reachable;
- effective `xdg-dbus-proxy` policy contains `--filter` and no dconf talk/call/own grant.

Validated target baseline: **PASS=17 FAIL=0 WARN=0**.

## 2. Pre-launch D-Bus profile guard

The 0.4.1 entrypoint must refuse launch before Bubblejail starts if the static profile can expose host dconf.

The guard rejects:

- `gnome_toolkit.dconf_dbus=true`;
- raw session D-Bus `--talk`, `--own` or `--call` grants whose exact or `.*` name policy includes `ca.desrt.dconf`.

Unrelated raw D-Bus grants are not automatically rejected by this specific dconf guard. The already-running proxy remains subject to the independent effective-policy audit.

## 3. GPU fail-closed launch

For an acceptance launch:

1. select the intended GPU;
2. run **Test Vulkan** and require PASS;
3. launch Bottles;
4. require both `GPU pre-avvio` and `GPU post-avvio` PASS;
5. confirm only the selected DRM card/render nodes are visible;
6. confirm exactly one Vulkan GPU with matching vendor/device identity.

Any missing/contradictory proof must fail closed. A post-launch proof failure must terminate the exact captured launch process group.

## 4. Display / preferences

Expected:

- Auto does not force a Wine display backend;
- native Wayland works when selected;
- XWayland keeps the Bottles GTK UI usable while Wine/Proton takes the X11/XWayland path;
- forcing XWayland does not add filesystem/network/GPU/optical permissions;
- Bottles preferences persist through the isolated keyfile backend after full close/reopen.

Discworld Noir has passed the 0.4.1 consolidated XWayland path with the dedicated RX 9070 XT and network OFF.

## 5. Retro Optical / non-live game path

With raw `/dev/srX` OFF and `/dev/sgX` OFF unless the test explicitly requires them:

- CDEmu/vhba control surfaces remain hidden from the jail;
- `/mnt/cdemu` is RO when a disc is mounted;
- raw sr remains hidden by default;
- GPU and Retro Optical pre/post proofs PASS;
- the game launches normally.

Validated Discworld Noir non-live baseline: dedicated RX 9070 XT, XWayland, network OFF, gamepad OFF, raw sr OFF, sg hidden, `/mnt/cdemu=RO`.

## 6. CDEmu ownership / live multidisc

Use an explicit saved multidisc set. 0.4.1 adds an inter-process operation lock and private ownership journal.

Required invariants:

- cache creation records exact base count, mapping, rdev, media and RO mount evidence;
- cached drives stay host-side;
- the jail sees only the exact active optical device when raw exposure is required;
- swap keeps the validated active mapping stable;
- cleanup is LIFO over the exact owned suffix;
- count/mapping/media/daemon ambiguity fails closed;
- a stale journal is recovered only after Bottles is no longer running;
- SIGKILL recovery never guesses ownership.

Discworld Noir three-disc cache/swap/cleanup and abnormal-termination recovery have passed the target gate.

## 7. Runtime-surface audit

With Bottles already running, **Analizza runtime sandbox** is read-only and must not modify policy.

For the network-OFF/gamepad-OFF baseline, expected evidence is:

- session D-Bus: only `org.freedesktop.DBus`;
- system D-Bus: only `org.freedesktop.DBus`;
- expected PulseAudio/Wayland/X11 sockets only;
- loopback interface and no routes;
- selected DRM nodes only;
- one exact filtered `xdg-dbus-proxy` process;
- zero dconf grants.

Live multidisc may add only the exact active `/dev/srX`; cached optical devices and `/dev/sgX` must remain hidden.

Real process-hygiene evidence recorded for 0.4.1: `FD_SOSPETTI=0` and `VAR_SENSIBILI=0` for the reviewed path/name classes.

## 8. Gamepad exact-node / hotplug

Standard gamepad support is through Bubblejail `[joystick]`; there is no broad `/dev/input` share and `/dev/hidraw*` remains hidden.

Required sequence:

1. static test exposes only current `jsX` + matching `eventX` nodes;
2. launch Bottles with gamepad ON;
3. initial monitor state reports exact nodes, `sysfs=exact`, `udev=initial-static`, `hidraw=hidden`;
4. physically disconnect: surface becomes empty and reports `udev=notified`;
5. reconnect: only the newly detected exact nodes return with `sysfs=exact`, `udev=notified`, `hidraw=hidden`.

0.4.1 contains a narrow retry for the real unplug/replug race where sysfs and `/dev/input` can be briefly out of phase. Only exact disappearing/changed-source topology errors are retryable; unrelated helper failures remain hard failures.

Xbox One S initial/disconnect/reconnect has passed this gate on the target machine.

## 9. Verifier/scanner sandbox

Run **Test verifica sandbox** before release acceptance. Expected attestation:

```text
archive=RO · app=RO · catalog=RO · cache=RW · host-home-sentinel=hidden · net=lo · proc=hidden · sys=hidden · run-host=hidden
```

Then verify/scan a known archive image. Required invariants:

- verifier/scanner executes in the dedicated bubblewrap worker;
- input remains under the authorized archive root;
- verification does not mount/execute/rename/rewrite dump files;
- exact known data reports `MATCH 1:1`;
- scanner evidence stays separate from DAT matching;
- only the hash cache is writable.

Discworld Noir Disc 1 has passed this path against Redump before and after an official DAT update.

## 10. Official DAT updater sandbox

The official updater must run in its own networked bubblewrap worker:

- game archive invisible;
- application code RO;
- verifier data/catalog and cache only RW;
- private HOME/tmp;
- no host proc/sys/runtime state;
- exact trusted DNS/TLS host inputs;
- HTTPS official-host allow-list with redirect revalidation;
- staged catalog rebuild, integrity check and rollback.

After an update, immediately re-run the known-disc verify/scan regression.

## 11. Package artifact gate

The merge/release artifact must be built from the exact commit pinned by `packaging/arch/PKGBUILD` and `.SRCINFO`.

Required target sequence:

- clean `makepkg --cleanbuild --syncdeps`;
- inspect package metadata/file list;
- install/reinstall the exact artifact;
- `pacman -Qkk bottles-retrocd` reports zero altered files;
- package-owned `/usr` payload disappears on removal;
- RetroCD config, Bubblejail `Bottles` instance/profile and verifier state remain byte-for-byte unchanged across uninstall/reinstall;
- one installed-package normal Bottles launch still passes the static dconf guard, GPU and Retro Optical proofs.

A previous 0.4.1-1 candidate already passed removal/reinstall preservation with 65 package files and 0 altered files, but any later source-pin change requires the final artifact to be rebuilt and rechecked before merge.

## Security boundary

Bubblejail protects Bottles/Wine. The GTK controller, CDEmu/libMirage control and gamepad hotplug helpers are host-side user processes. 0.4.1 moves archive verification/scanning into a dedicated non-networked bubblewrap worker and official DAT updates into a separate networked worker with the archive invisible.

No release gate may be bypassed by widening filesystem, D-Bus, input, GPU or optical permissions merely for convenience.
