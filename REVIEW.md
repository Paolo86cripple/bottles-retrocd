# Bottles RetroCD 0.4.1 — final pre-release review

## Verdict

**PASS for the code/security/compatibility review. One narrow release gate remains: rebuild and recheck the exact final 0.4.1-1 package artifact pinned to payload commit `3c842c0c5f740a041c4f2de4edcdb899691ccbd2`.**

The validated 0.4.0 game-compatibility boundary is intentionally preserved. 0.4.1 hardens verifier/updater isolation, CDEmu ownership/recovery, runtime D-Bus exposure and exact-node gamepad hotplug without broadening Bubblejail permissions.

No automatic merge. Final explicit owner approval is required after the exact pinned artifact gate and final CI are green.

## Consolidated automated review

The 0.4.1 branch CI covers:

- Python compilation for the complete application/runtime hardening modules;
- full unit tests with `ResourceWarning` promoted to error;
- shell syntax;
- Arch packaging syntax;
- release identity and Arch metadata consistency;
- exact package source-pin consistency;
- unsafe dynamic-execution scan rejecting `os.system`, `shell=True`, `eval` and dynamic `exec` in application Python paths.

The runtime guard source (`ca3a6aeb22bad6d932121a24e17927fc11bf9eaf`) passed CI before final documentation/package-pin alignment. The current branch must also remain green after the final metadata synchronization.

## Target-machine regression — complete for runtime behavior

The consolidated CachyOS regression passed:

- **Sandbox self-test:** `PASS=17 FAIL=0 WARN=0`;
- Bottles preference persistence via `GSETTINGS_BACKEND=keyfile` with host dconf blocked;
- Discworld Noir non-live path on the dedicated RX 9070 XT with XWayland, network OFF, raw `/dev/srX` OFF, `/dev/sgX` hidden and `/mnt/cdemu=RO`;
- GPU pre/post DRM/Vulkan proof PASS;
- Retro Optical pre/post proof PASS;
- live three-disc multidisc path with one exact active `/dev/srX`, cached drives hidden, `/dev/sgX` hidden and automatic cleanup;
- CDEmu SIGKILL/stale-session recovery with exact owned-suffix LIFO cleanup after Bottles closed;
- Xbox One S static exact-node exposure and physical disconnect/reconnect with `sysfs=exact`, `udev=notified` on real transitions and `hidraw=hidden`;
- verifier/scanner sandbox attestation plus Redump `MATCH 1:1` and protection scan;
- official Redump updater sandbox followed by successful known-disc re-verification;
- runtime session/system buses limited to `org.freedesktop.DBus` in the validated network-OFF baseline;
- effective `xdg-dbus-proxy` filtering with zero dconf grants;
- process hygiene scans `FD_SOSPETTI=0` and `VAR_SENSIBILI=0` for the reviewed classes.

## Final adversarial D-Bus finding — fixed

The final review found a narrow gap: the active runtime proxy was audited and host dconf was blocked on the validated profile, but launch did not yet refuse a future static profile regression before Bubblejail started.

0.4.1 now adds a fail-closed pre-launch guard that rejects:

- `[gnome_toolkit] dconf_dbus=true`;
- raw session D-Bus `--talk`, `--own` or `--call` grants whose exact or `.*` name policy includes `ca.desrt.dconf`.

The independent post-launch effective-proxy audit remains mandatory. The guard does not alter CDEmu ownership, GPU, optical, filesystem, network or gamepad permissions.

## Filesystem / network / archive

- Host HOME remains hidden except explicit approved shares.
- Persistent `[network]` remains forbidden; game networking is transient and OFF by default.
- Whitelist paths are canonicalized and deny-by-default.
- Archive root/subdirectories may be explicitly shared RO; RW inside the archive and ancestor shares remain rejected.
- Verification/scanning never modifies, mounts or executes original dump material.

## GPU / display

- GPU identity persists by PCI address, never `cardX` numbering.
- Broad `/dev/dri` is masked; only exact selected DRM nodes are rebound.
- Pre/post proof must establish exact DRM/Vulkan identity and isolation.
- Native Wayland/XWayland choices do not broaden other permissions.

## Retro Optical / multidisc

- CDEmu/libMirage/UDisks2 remain trusted host-side infrastructure.
- CDEmu D-Bus and `/dev/vhba_ctl` remain hidden from Bottles/Wine.
- Raw `/dev/srX` and `/dev/sgX` remain explicit/OFF by default.
- UDisks2 verified filesystem RO state is authoritative.
- 0.4.1 adds inter-process CDEmu locking plus a private ownership journal with boot/daemon/process/device/mapping/media/mount evidence and write-ahead cleanup state.
- Stale cleanup removes only the exact proven contiguous owned suffix and refuses ambiguity/external activity.

## Verifier / updater hardening

Verification/protection scanning now run in a dedicated bubblewrap worker with archive/app/catalog RO, hash cache only RW, private HOME/tmp, minimal `/dev`, loopback-only networking and no host proc/sys/runtime state.

Official DAT updates run in a separate networked bubblewrap worker with the game archive invisible, verifier state only RW, exact DNS/TLS inputs, HTTPS allow-lists, bounded extraction, staged rebuild, integrity checks and rollback.

## Gamepad

- Standard controllers use Bubblejail `[joystick]` with exact current `jsX` + matching evdev `eventX` nodes.
- Broad `/dev/input` and `/dev/hidraw*` remain hidden.
- Physical hotplug reconciles exact nodes/sysfs and sends matching libudev notifications.
- The real unplug/replug sysfs↔`/dev/input` race is retried only for exact disappearing/changed-source topology conditions; unrelated helper failures remain hard failures.

## Package artifact status

A previous 0.4.1-1 candidate passed package removal/reinstall preservation with **65 package files / 0 altered files**, preserving RetroCD configuration, Bubblejail profile/private state and verifier catalog.

That artifact predates the final pre-launch dconf guard and final installed-document alignment, so it cannot be the merge/release artifact.

The final package metadata is:

```text
pkgver = 0.4.1
pkgrel = 1
payload source = 3c842c0c5f740a041c4f2de4edcdb899691ccbd2
```

`PKGBUILD`, `.SRCINFO` and CI must all name that same payload source.

Required final narrow gate:

1. clean build of the exact pinned artifact;
2. inspect package metadata/file list;
3. install/reinstall or upgrade successfully;
4. `pacman -Qkk bottles-retrocd` reports zero altered files;
5. one installed normal launch still passes static dconf guard plus GPU/Retro Optical proofs;
6. uninstall removes package-owned `/usr` files only and preserves config/Bubblejail/prefix/archive/verifier state.

This is a package-acceptance recheck, not a request to repeat the already completed full runtime regression matrix unless the exact artifact exposes a regression.

## Residual risks / deliberate limits

- GTK controller, CDEmu/libMirage control and gamepad helpers remain host-side user processes.
- Manual local DAT import remains host-side; official network updating does not.
- Bubblejail/xdg-dbus-proxy semantics are upstream dependencies; unexpected/missing proof fails closed.
- Concurrent uncooperative external CDEmu activity can create ownership ambiguity; RetroCD refuses destructive cleanup rather than guessing.
- Some games enumerate controllers only at startup; RetroCD cannot force application-level re-enumeration.
- Switch/gyro hidraw support remains outside the standard-controller path.

## Merge criterion

Merge only when all of the following are true:

- current branch CI is green;
- `PKGBUILD`, `.SRCINFO` and CI agree on payload `3c842c0c5f740a041c4f2de4edcdb899691ccbd2`;
- the exact 0.4.1-1 artifact passes the narrow final package gate above;
- final branch-vs-`main` review shows no unexpected divergence;
- repository owner gives explicit final approval.

Do **not** merge automatically.
