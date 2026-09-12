# Security / code review — Bottles RetroCD 0.4.1

## Result

**PASS for the 0.4.1 code/security design after the final pre-launch D-Bus guard fix.**

The release artifact itself remains a separate gate: it must be rebuilt from the exact final package source pin and pass the package install/integrity/uninstall-preservation checks before merge/release.

## Bubblejail / filesystem / network

- Bottles/Wine runs in the dedicated Bubblejail instance `Bottles` with private HOME.
- Persistent `[network]` is rejected; game networking is transient and OFF by default.
- Whitelist paths are canonicalized and validated before writing.
- Explicit archive-root/subdirectory RO shares are allowed; RW access within the archive, ancestor shares, real HOME, overlapping mounts and broad system roots are rejected.
- Dynamic optical/cache mounts use restrictive exact binds; broad removable-media roots are not exposed.
- Runtime Bubblejail argument support is checked before policy depends on it.

Validated target self-test: **PASS=17 FAIL=0 WARN=0**.

## dconf / D-Bus hardening

0.4.1 uses the Bubblejail 0.10.4 profile key:

```toml
[gnome_toolkit]
dconf_dbus = false
```

Bottles was positively observed using:

```text
GSETTINGS_BACKEND=keyfile
```

inside the private jail HOME, and preference changes persisted across a full close/reopen with host dconf disabled.

The hardened D-Bus invariant has two independent halves:

1. **pre-launch static profile guard** — launch is refused if `gnome_toolkit.dconf_dbus=true` or if `debug.raw_dbus_session_args` contains an exact/`.*` `--talk`, `--own` or `--call` policy that includes `ca.desrt.dconf`;
2. **post-launch effective proxy audit** — the exact active `xdg-dbus-proxy` process must be unique, filtered and contain no effective dconf grant.

Validated runtime evidence showed `ca.desrt.dconf` absent/`ServiceUnknown`, session/system buses exposing only `org.freedesktop.DBus`, and the effective proxy policy reduced to `--filter` with zero dconf grants.

The final review specifically found the absence of the pre-launch half as a release blocker; that gap is now closed without changing CDEmu lock ownership or runtime permissions.

## GPU / display

- GPU identity is stable PCI identity, not `cardX` numbering.
- Launch is refused if no valid selected GPU can be proven.
- Selected DRM card/render nodes must be live character devices.
- Broad `/dev/dri` is masked and only selected nodes are rebound.
- Pre-launch proof verifies `DRI_PRIME`, selected-node presence, known non-selected-node absence, one Vulkan GPU and matching vendor/device identity.
- Post-launch proof repeats effective DRM/Vulkan isolation inside the running jail.
- Missing proof fails closed; post-launch proof failure terminates the exact launch process group.
- Auto/native Wayland/XWayland choices do not broaden filesystem/network/GPU/optical policy.

Discworld Noir passed the consolidated 0.4.1 XWayland path with dedicated RX 9070 XT, network OFF and GPU pre/post proofs PASS.

## Retro Optical / CDEmu ownership

- CDEmu control remains host-side over D-Bus; `cdemu-client` is optional.
- UDisks2 mount state is verified and the RO filesystem mount is authoritative.
- Raw `/dev/srX` is OFF by default and requires the exact CDEmu mapping plus Linux SCSI optical type 5.
- `/dev/sgX` remains explicit/OFF by default.
- CDEmu D-Bus and `/dev/vhba_ctl` remain hidden from Bottles/Wine.

0.4.1 hardens live multidisc ownership with:

- an inter-process flock around cooperating mutating RetroCD CDEmu work;
- a private ownership journal containing boot/daemon identity, owner PID/start ticks, base count, expected images, exact device mappings/rdev/media/mount evidence and write-ahead cleanup state;
- exact contiguous appended-suffix ownership;
- LIFO cleanup only after revalidation;
- fail-closed handling for mapping/count/media/daemon ambiguity and external activity;
- stale-session recovery that refuses destructive cleanup while Bottles is active.

Normal 3-disc cache/swap/cleanup and SIGKILL recovery were physically validated on the target machine.

## Standard gamepad / hotplug

- Standard controllers use Bubblejail `[joystick]`; no broad `/dev/input` bind is added.
- `/dev/hidraw*` remains hidden on this path.
- The accepted surface is the current host `jsX` plus matching evdev `eventX` nodes; numbering is not hardcoded.
- Initial activation is non-destructive and reports `udev=initial-static`.
- Physical disconnect/reconnect rebuilds only the exact current nodes plus matching minimal sysfs and emits matching libudev notifications.
- Namespace entry and exact-node/sysfs identity are revalidated before mutation.

A real unplug/replug race was observed: sysfs could briefly reference an `eventX` node already gone from `/dev/input`. 0.4.1 now retries only narrowly classified disappearing/changed-source topology failures. Unrelated helper errors remain hard failures. Xbox One S initial/disconnect/reconnect passed after this fix with exact sysfs and hidden hidraw.

## Verifier / scanner boundary

Archive verification and protection scanning no longer execute directly in the GTK/CLI host process. A dedicated bubblewrap worker receives:

- application code RO;
- authorized archive RO;
- existing catalog RO;
- verifier hash cache only RW;
- private HOME/tmp;
- unshared network namespace with at most loopback;
- minimal `/dev`;
- no host `/proc`, `/sys` or runtime state;
- cleared environment and closed inherited file descriptors.

The launcher validates the mount layout before creating RW cache state, requires a trusted root-owned non-group/other-writable `bwrap`, canonicalizes all input paths below the authorized archive and performs a positive boundary attestation.

Discworld Noir Disc 1 remained Redump `MATCH 1:1`; scanner reads remained direct/raw and no mount or execution occurred.

## Official DAT updater boundary

Official Redump/TOSEC updates run in a second bubblewrap worker, separate from the verifier and game jail.

- The configured game archive is not mounted and its visibility is positively rejected before download.
- Application code is RO.
- Verifier data/catalog and cache are the only RW state.
- HOME/tmp are private; host proc/sys/runtime state is absent.
- Network is available only to this updater worker.
- Exact trusted DNS/TLS host inputs are mounted RO rather than broad `/etc`.
- HTTPS official-host allow-lists, redirect validation, bounded ZIP handling, traversal/symlink rejection, staged indexing, integrity checks and rollback remain enforced.

A real Redump update followed by immediate Discworld verify/scan passed on target.

## Runtime-surface evidence

Read-only runtime probes cover session/system D-Bus names, UNIX/runtime sockets, routes/interfaces and sensitive device nodes. The effective host proxy is inspected separately from in-jail method probes.

Validated network-OFF baseline:

- session D-Bus: `org.freedesktop.DBus` only;
- system D-Bus: `org.freedesktop.DBus` only;
- expected PulseAudio/Wayland/X11 sockets;
- selected DRM card/render nodes only;
- dconf blocked.

Validated live-multidisc delta adds only the exact active optical `/dev/srX`; cached CDEmu devices and `/dev/sgX` remain hidden.

Real process-hygiene scans reported:

```text
FD_SOSPETTI=0
VAR_SENSIBILI=0
```

for the reviewed path and secret-name classes.

## Automated evidence

Current CI covers:

- Python syntax for the complete 0.4.1 application modules;
- the full unit-test suite with `ResourceWarning` as error;
- shell syntax;
- Arch packaging syntax;
- application/release identity and package metadata consistency;
- rejection of unsafe dynamic execution patterns.

The narrow pre-launch D-Bus guard and its wrapper contract have dedicated tests.

## Residual risks / deliberate limits

- The GTK controller, CDEmu/libMirage control path and gamepad helpers still run as the logged-in host user.
- Manual local DAT import remains host-side; official network updates do not.
- Bubblejail/xdg-dbus-proxy runtime semantics remain an upstream compatibility dependency; unexpected/missing proof intentionally fails closed.
- Concurrent uncooperative external CDEmu management can force ownership ambiguity; RetroCD then refuses destructive cleanup rather than guessing.
- Some games enumerate controllers only at startup; RetroCD can prove the Wine-visible transition but cannot force game-level re-enumeration.
- Switch/gyro hidraw support remains out of scope for the standard-controller path.

## Merge criterion

The code/security review is complete only when the final branch remains CI-green and the exact pinned 0.4.1-1 package artifact passes the target build/install/integrity/uninstall-preservation gate. Owner approval is required before merge; approval has been granted conditionally on those gates passing.
