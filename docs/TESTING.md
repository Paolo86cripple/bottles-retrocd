# Testing

Before packaging/release, close Bottles completely and run the relevant runtime tests in the **Test** and **Verifica** tabs plus one normal secured Bottles launch. User-facing terminal examples use fish syntax.

## 1. Base Bubblejail sandbox

Expected:

- whitelist audit PASS;
- persistent `[network]` absent;
- private HOME writable while real host HOME and `.ssh` stay hidden;
- configured RW/RO semantics exact;
- real non-whitelist sentinel hidden;
- loopback-only base networking;
- Wayland/XWayland, audio, selected GPU and Vulkan surfaces available according to policy;
- host dconf blocked while Bottles settings persist via keyfile.

0.4.1 target baseline: **PASS=17 FAIL=0 WARN=0**.

## 2. D-Bus / dconf policy

The validated Bubblejail profile has:

```toml
[gnome_toolkit]
dconf_dbus = false
```

Pre-launch, RetroCD must reject `dconf_dbus=true` and raw session D-Bus talk/own/call grants that include `ca.desrt.dconf` by exact name or `.*` wildcard policy.

Post-launch, the runtime audit must prove:

- exactly one session `xdg-dbus-proxy` for the `Bottles` instance;
- `--filter` present;
- zero effective dconf grants;
- `ca.desrt.dconf` unreachable;
- session/system buses limited to the expected names.

The target baseline exposed only `org.freedesktop.DBus` on both buses.

## 3. GPU fail-closed launch

For each GPU path under acceptance testing:

1. select the GPU;
2. run **Test Vulkan** and require PASS;
3. launch Bottles;
4. require both `GPU pre-avvio` and `GPU post-avvio` PASS;
5. confirm selected DRM nodes present and known non-selected nodes absent;
6. confirm exactly one Vulkan device with matching vendor/device identity.

Any missing/contradictory evidence must fail closed.

0.4.1 consolidated Discworld Noir path passed on the dedicated RX 9070 XT with two other GPUs hidden.

## 4. Display / preferences

Expected:

- Auto does not force Wine display policy;
- native Wayland works when selected;
- XWayland does not broaden filesystem/network/GPU/optical policy;
- Bottles preferences persist through `GSETTINGS_BACKEND=keyfile` after full close/reopen.

Discworld Noir passed the consolidated XWayland path with working audio and established fullscreen behavior.

## 5. Retro Optical / non-live launch

Expected default security posture:

- CDEmu D-Bus hidden from the jail;
- `/dev/vhba_ctl` hidden;
- raw `/dev/srX` hidden unless explicitly required;
- `/dev/sgX` hidden unless explicitly enabled;
- `/mnt/cdemu` RO when an optical mount is requested;
- GPU and Retro Optical pre/post proofs PASS.

0.4.1 Discworld Noir non-live target result: **PASS** with network OFF, gamepad OFF, raw sr OFF, sg hidden and `/mnt/cdemu=RO`.

## 6. CDEmu ownership / crash recovery

For live multidisc:

- acquire the RetroCD inter-process operation/session lock;
- record exact ownership journal evidence before destructive lifecycle steps;
- require an exact contiguous appended suffix;
- revalidate boot/daemon identity, device count/index, mapping/rdev, media and RO mount state before cleanup;
- remove only in LIFO order;
- refuse cleanup while Bottles is active;
- refuse ambiguity rather than guessing ownership.

Target evidence includes normal three-disc cache/swap/cleanup and SIGKILL recovery after Bottles closure.

## 7. Live multidisc runtime delta

With Discworld Noir three-disc live mode:

- cache all requested discs RO host-side;
- expose only the exact active optical `/dev/srX` to Wine when required;
- keep cached drives and `/dev/sgX` hidden;
- keep D-Bus/socket/network/DRM surface unchanged across swaps;
- keep the active device identity stable across Disc 1 → Disc 2;
- clean the owned cache automatically after Bottles exits.

This path has passed on target.

## 8. Gamepad exact-node/hotplug

Expected:

- static `[joystick]` path exposes only current `jsX` plus matching `eventX` nodes;
- `/dev/hidraw*` hidden;
- initial activation `sysfs=exact`, `udev=initial-static`;
- physical disconnect removes the exact surface and reports `udev=notified`;
- reconnect restores only the newly detected exact surface and reports `udev=notified`.

A transient sysfs↔`/dev/input` unplug/replug race is retryable only when the exact source node disappeared or changed before namespace mutation. Other helper failures remain hard failures.

Xbox One S initial/disconnect/reconnect passed after this fix.

## 9. Verifier/scanner sandbox

Expected attestation:

```text
archive=RO · app=RO · catalog=RO · cache=RW · host-home-sentinel=hidden · net=lo · proc=hidden · sys=hidden · run-host=hidden
```

Required semantics:

- `bwrap` is trusted/root-owned and not group/other writable;
- archive inputs canonicalize below the authorized root;
- archive/app/catalog are RO;
- only verifier hash cache is RW;
- HOME/tmp private;
- host network/proc/sys/runtime absent;
- verification/scanning never mounts or executes the dump.

Discworld Noir Disc 1 passed Redump `MATCH 1:1` plus direct ISO/raw scan.

## 10. Official DAT updater sandbox

Expected:

- separate networked bwrap worker;
- game archive invisible;
- app code RO;
- verifier data/catalog + cache only RW;
- private HOME/tmp;
- no host proc/sys/runtime;
- exact trusted DNS/TLS inputs;
- HTTPS official-host allow-list and redirect revalidation;
- staged catalog integrity/rollback.

After update, repeat known-disc verify/scan. The target Redump update and immediate Discworld revalidation passed.

## 11. Process hygiene

Runtime evidence includes scanning visible process FDs and environment variable names. The reviewed target run reported:

```text
FD_SOSPETTI= 0
VAR_SENSIBILI= 0
```

for removable-media, sg/vhba, SSH/GPG and common secret-bearing variable-name classes.

## 12. Automated gate

```fish
env PYTHONWARNINGS='error::ResourceWarning' python -m unittest discover -s tests -v
bash -n run-local.sh
```

CI also checks Python syntax, Arch packaging syntax, release identity/package metadata consistency and unsafe dynamic execution patterns.

## 13. Final Arch/CachyOS artifact gate

The artifact must be built from the exact commit pinned by `packaging/arch/PKGBUILD` and `.SRCINFO`.

Required final acceptance:

1. clean `makepkg --cleanbuild --syncdeps`;
2. install/reinstall the exact artifact;
3. `pacman -Qkk bottles-retrocd` reports zero altered files;
4. removal deletes package-owned `/usr` payload;
5. RetroCD config, Bubblejail instance/profile and verifier state remain byte-identical across uninstall/reinstall;
6. one installed-package normal launch passes the static D-Bus profile guard and the existing GPU/Retro Optical proofs.

A previous 0.4.1-1 candidate passed this preservation/integrity path with 65 total files and 0 altered files. If the package source pin changes afterward, that earlier artifact is no longer the merge/release artifact and the final artifact gate must be repeated.

## Merge rule

No automatic merge. Merge only after CI is green on the final branch, the exact pinned package artifact passes the final target gate and the owner has approved the merge.
