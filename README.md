# Bottles RetroCD

GTK4 controller for running native Bottles inside the existing Bubblejail instance `Bottles`, with CDEmu/UDisks2 integration for retro optical media, strict device/filesystem isolation, exact-node gamepad support and sandboxed Redump/TOSEC verification.

This source tree is the **0.4.1** compatibility-preserving hardening line.

## Arch / CachyOS package

0.4.1 uses the native package identity:

```text
bottles-retrocd 0.4.1-1
```

A built package is installed with pacman, for example:

```fish
sudo pacman -U ./bottles-retrocd-0.4.1-1-x86_64.pkg.tar.zst
```

The package installs only application-owned files under `/usr`. Normal removal intentionally preserves RetroCD configuration, the Bubblejail `Bottles` instance/private HOME, Wine prefixes, archive data and verifier state. It conflicts with/replaces the obsolete historical local package name `bottles-retro-cd-gui`.

## Security and compatibility goals

- keep Bottles/Wine inside the existing Bubblejail instance `Bottles`;
- keep a private HOME for Bottles, runners, DXVK, runtimes and prefixes;
- use an explicit persistent filesystem whitelist with separate RW and RO paths;
- keep network OFF by default and enable it only transiently for a selected launch;
- select one GPU by stable PCI identity and expose only its exact DRM card/render nodes;
- support native Wayland plus an explicit XWayland compatibility fallback without broadening other permissions;
- persist Bottles preferences via `GSETTINGS_BACKEND=keyfile` inside the private jail HOME while host dconf remains blocked;
- refuse launch when the Bubblejail profile enables `gnome_toolkit.dconf_dbus` or raw session D-Bus grants that include `ca.desrt.dconf`;
- configure one explicit archive root and never modify original dump files as part of normal verification/launch policy;
- support standard controllers through Bubblejail `[joystick]` with exact `jsX` + matching `eventX` exposure and hidden `/dev/hidraw*`;
- keep CDEmu control host-side while CDEmu D-Bus, `/dev/vhba_ctl` and `/dev/sgX` stay hidden from Bottles unless an exact advanced path is explicitly required;
- verify optical mounts through UDisks2 as read-only;
- allow optional raw `/dev/srX` exposure only for the exact CDEmu-mapped SCSI optical block device;
- support explicit multidisc sets and live swapping without exposing cached CDEmu drives to Wine;
- run archive verification/protection parsing in a dedicated bubblewrap worker;
- run official Redump/TOSEC updates in a separate networked bubblewrap worker with the game archive invisible.

## UI

The interface is split into seven tabs:

1. **CDEmu** — drive selection, image load/eject, multidisc and UDisks2 RO status.
2. **Sandbox** — archive root, GPU, network/optical permissions, display backend, gamepad status/test, Vulkan/isolation test and Bottles launch.
3. **Whitelist** — persistent Bubblejail `root_share` RO/RW management.
4. **Avanzate** — DPM, transfer-rate, bad-sector and DVD CSS emulation.
5. **Test** — cumulative log plus CDEmu/UDisks2, Bubblejail, bridge/cache and runtime-surface tests.
6. **Verifica** — sandbox attestation, Redump/TOSEC update/import, exact verification, protection scan and DAT↔scanner comparison.
7. **Componenti** — host-side CDEmu/libMirage/VHBA health and explicit Arch/CachyOS update flow.

## Archive root

`config.toml` schema 2 stores `archive_root`, the selected GPU PCI address and display backend.

An existing installation may migrate the historical target path only when that directory actually exists. Migration changes the path setting only; RetroCD does not copy, move, rename or rewrite archive files.

The configured archive root and its subdirectories may be explicitly whitelisted read-only. RW access anywhere within the archive is forbidden, and archive ancestors are refused in both modes. Selecting an archive does not share it automatically.

## Display and settings isolation

The Sandbox tab stores one of:

- **Auto** — no Wine display override;
- **Wayland nativo** — use the native Wayland path where supported;
- **XWayland** — present X11/XWayland to Wine while the Bottles GTK UI may remain on Wayland.

Forced XWayland requires the already configured Bubblejail `x11` + `wayland` services. RetroCD does not silently add broader permissions.

Bottles preferences use:

```text
GSETTINGS_BACKEND=keyfile
```

inside Bubblejail's private HOME. In the validated 0.4.1 profile:

```toml
[gnome_toolkit]
dconf_dbus = false
```

Host `ca.desrt.dconf` is therefore not required. The 0.4.1 entrypoint performs a static fail-closed profile check before launch, and the runtime audit independently inspects the effective `xdg-dbus-proxy` policy after launch.

## GPU isolation

GPU selection is a security decision, not just a performance preference.

- GPU identity is persisted by PCI address, never by `cardX` numbering.
- Selected DRM nodes must be live character devices.
- Broad `/dev/dri` is masked and only the selected card/render nodes are rebound.
- Pre-launch proof requires matching PCI/vendor/device identity, exact selected-node visibility, non-selected-node absence, `DRI_PRIME` and exactly one Vulkan GPU.
- Post-launch proof repeats the effective check against the already-running Bubblejail instance.
- Missing or contradictory proof fails closed; a post-launch isolation failure terminates the exact launch process group.

## Retro Optical / CDEmu

CDEmu is controlled over its host D-Bus API; `cdemu-client` is optional. UDisks2 mount state is verified rather than inferred from command success.

Raw `/dev/srX` exposure is OFF by default. When enabled, RetroCD requires the exact CDEmu mapping and Linux SCSI optical type 5. `/dev/sgX` is a separate advanced option and remains OFF by default. CDEmu D-Bus and `/dev/vhba_ctl` remain hidden from Bottles/Wine.

0.4.1 adds durable CDEmu ownership evidence for live multidisc:

- an inter-process flock serializes mutating RetroCD CDEmu work;
- a private journal records boot/daemon identity, owner process identity, baseline count, exact mappings/media/mounts and write-ahead cleanup state;
- recovery removes only the exact proven contiguous appended suffix in LIFO order;
- ambiguous ownership, mapping/count drift or external activity fails closed instead of guessing.

## Gamepad isolation and hotplug

Standard controller support uses Bubblejail `[joystick]`; RetroCD does not add a broad `/dev/input` share and does not expose `/dev/hidraw*` on this path.

The accepted surface is always the currently detected `jsX` node plus its matching evdev `eventX` node(s). Physical disconnect/reconnect rebuilds only that exact surface and matching minimal sysfs, then emits matching libudev notifications for Wine/winebus. Device numbers are not assumed stable.

0.4.1 also handles the real unplug/replug race where sysfs can briefly reference an input node already gone from `/dev/input`: only exact disappearing/changed-source topology failures are retried; unrelated helper failures remain hard failures.

## Verifier / scanner sandbox

Archive verification and protection scanning no longer run directly in the GTK/CLI host process. They execute in a dedicated bubblewrap worker with:

- application code RO;
- authorized archive RO;
- existing verifier catalog RO;
- only the dedicated hash cache RW;
- private HOME and `/tmp`;
- an unshared network namespace with at most loopback;
- no host `/proc`, `/sys` or runtime state;
- minimal `/dev`;
- `--clearenv` and closed inherited file descriptors.

The worker canonicalizes all requested inputs below the authorized archive and fails closed on path escape, unsafe mount layout, missing/untrusted `bwrap` or failed boundary attestation.

Verification retains the existing semantics: streamed CRC32/MD5/SHA1, `MATCH 1:1` only for one complete unique DAT game, `AMBIGUOUS` for equivalent complete records, and scanner evidence kept separate from cryptographic matching. The scanner never mounts or executes the image.

## Official DAT updater sandbox

Official Redump/TOSEC updates run in a second bubblewrap worker, separate from both the game sandbox and the verifier worker. It receives host networking but not the configured game archive. Only verifier data/catalog and verifier cache are writable.

The updater keeps HTTPS official-host allow-lists, redirect revalidation, bounded downloads/ZIP contents, traversal/symlink rejection, staged indexing, SQLite integrity checks and rollback. Exact trusted DNS/TLS host files are mounted RO rather than exposing broad `/etc`.

Manual local DAT import remains a separate host-side metadata operation.

## Runtime audit

The **Analizza runtime sandbox** diagnostic attaches read-only probes to an already-running `Bottles` instance and reports:

- session/system D-Bus names;
- effective host `xdg-dbus-proxy` policy;
- UNIX/runtime sockets;
- network interfaces/routes;
- sensitive visible device nodes.

The validated network-OFF baseline exposes only `org.freedesktop.DBus` on session/system buses, the expected Pulse/Wayland/X11 sockets and the selected GPU nodes. Live multidisc adds only the exact active `/dev/srX`; cached drives and `/dev/sgX` remain hidden.

## 0.4.1 target evidence

The 0.4.1 hardening line has been exercised on CachyOS with:

- Sandbox self-test `PASS=17 FAIL=0 WARN=0`;
- Discworld Noir non-live launch on the dedicated RX 9070 XT, XWayland, network OFF, raw sr OFF, sg hidden and `/mnt/cdemu=RO`, with GPU/Retro Optical pre/post PASS;
- live Discworld Noir multidisc with stable exact active `/dev/srX`, hidden cache devices and automatic cleanup;
- verifier sandbox attestation plus Redump verify/scan before and after an official DAT update;
- Xbox One S initial/disconnect/reconnect exact-node hotplug with `sysfs=exact`, `udev=notified` on physical changes and `hidraw=hidden`;
- process FD scan `FD_SOSPETTI=0` and environment-name scan `VAR_SENSIBILI=0`;
- package removal/reinstallation preserving RetroCD config, Bubblejail profile and verifier catalog in the candidate acceptance run.

Release-critical package evidence for the exact pinned final artifact is tracked in PR #5 and must refer to the same source pin that is ultimately merged/released.

## Run locally from source

Nothing is installed by the source tree:

```fish
./run-local.sh
```

Required runtime commands include `python3`, `bubblejail`, `bwrap`, `findmnt`, `ip` and `vulkaninfo`. `udisksctl` is required for verified RO optical mounts/live multidisc. `cdemu-client` is not required.

The existing Bubblejail instance is expected at:

```text
~/.local/share/bubblejail/instances/Bottles/
```

## Security boundary

Bubblejail is the security boundary for Bottles/Wine. The GTK controller, CDEmu/libMirage control path and gamepad hotplug helpers are host-side user processes. Archive verification/scanning and official DAT updates have their own dedicated bubblewrap boundaries in 0.4.1.

Persistent `[network]` in `services.toml` is rejected. Game networking is transient per launch. The DAT updater's networking is separate and limited by its own sandbox plus official HTTPS allow-list.

## Roadmap after 0.4.1

1. **Native legacy optical DRM compatibility/emulation** — SafeDisc, SecuROM, LaserLock, StarForce and related Windows 9x/XP protections through original-media-compatible mechanisms; No-CD/cracked executables are not the normal solution.
2. **Legacy DirectX compatibility manager** — optional/OFF-by-default DxWrapper/dgVoodoo2-style DirectX 5–9 support.
3. **libRashader + Slang shaders** — optional/OFF by default after the compatibility foundation is stable.

None of these may weaken the validated Bubblejail boundary merely for convenience.

## License and upstream attribution

This project is GPL-3.0-or-later. The CDEmu D-Bus backend uses interface names, method signatures, signal names and client design patterns adapted from gCDEmu 3.3.1 (GPL-2.0-or-later). See `NOTICE`.
