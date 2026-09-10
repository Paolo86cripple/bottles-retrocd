# Bottles RetroCD 0.4.0 — final pre-packaging review

## Verdict

**PASS — no release-blocking code or security issue found.**

The 0.4.0 feature set is frozen. PR #3 has passed the automated regression gate, the complete target-machine gate and a final diff/security review. No runtime change is recommended before packaging unless a new regression appears.

## Automated gate

- **151/151 unit tests PASS**;
- Python compilation covers every application module, including the final display/gamepad wrapper, `gamepad_hotplug.py`, `gamepad_ns_entry.py` and `gamepad_ns_helper.py`;
- `ResourceWarning`-as-error PASS;
- `run-local.sh` shell syntax PASS;
- unsafe execution scan rejecting `os.system`, `shell=True`, `eval` and dynamic `exec` PASS;
- code-changing head `2d0373d2e6ae08eb6dfd6616ad013d1c77058bac` passed CI #320; later changes are release documentation/contract alignment and must remain green before merge.

## Target-machine acceptance — complete

The final CachyOS gate is closed:

- schema-2 `archive_root` correct; config directory/file modes `0700`/`0600`;
- archive re-selection persists after full RetroCD restart;
- pre/post archive metadata signatures are identical;
- resize + vertical scrolling works across all notebook pages;
- **Test Bubblejail: PASS=17 FAIL=0 WARN=0** with real temporary non-whitelist sentinel hidden, private HOME, real HOME/`.ssh` hidden, correct RW/RO whitelist semantics and loopback-only base networking;
- **Test CD → Bubblejail: PASS** with temporary `/dev/sr1` validated as SCSI optical type 5, verified RO host mount, two real sentinels hidden, `/mnt/cdemu` visible/non-writable and cleanup complete;
- final Discworld Noir XWayland launch: GPU pre/post PASS, Retro Optical pre/post PASS with `/mnt/cdemu=RO`, network OFF, game starts correctly with the previously validated fullscreen/audio behavior;
- final gamepad initial surface: Xbox One S `event9 + js0`, writable, `sysfs=exact`, `udev=initial-static`, `hidraw=hidden`;
- previously completed physical gamepad disconnect/reconnect, both AMD GPU paths, live multidisc, verifier/source immutability, Wayland, preference persistence and lifecycle negative-path testing remain valid.

The CDEmu/VHBA block-layer `ro` flag may report RW. It is diagnostic only; the independently verified UDisks2 filesystem mount is the authoritative RO security decision.

## Archive-root / filesystem review

- Release no longer hardcodes a target-machine removable-storage root.
- Legacy migration stores a path only when the historical archive directory exists; it does not move, rename or rewrite dump data.
- New installations must select an archive explicitly.
- Archive root/subdirectories may be explicitly shared RO.
- RW access anywhere within the archive and ancestor shares in either mode are rejected, including canonicalized aliases.
- Selecting an archive does not automatically broaden the Bubblejail whitelist.
- Sandbox and CD integration tests now use real temporary host sentinels, preventing false PASS from nonexistent paths.

## GPU / display review

- Stable PCI identity is authoritative; there is no implicit Mesa-default launch path.
- Selected DRM nodes must be live character devices; broad `/dev/dri` is masked and only selected nodes are rebound.
- Pre-launch proof requires `DRI_PRIME`, selected-node presence, known non-selected-node absence, one Vulkan GPU and matching vendor/device identity.
- Post-launch proof runs against the already-active Bubblejail instance; missing proof fails closed and terminates the exact launch process group.
- Auto/native Wayland/XWayland are persistent choices. XWayland does not broaden filesystem/network/GPU/optical permissions.
- Bottles global preferences persist through `GSETTINGS_BACKEND=keyfile` inside the private Bubblejail HOME.

## Retro Optical / multidisc review

- CDEmu control uses D-Bus; `cdemu-client` is optional.
- Raw `/dev/srX` remains opt-in and must match the CDEmu mapping plus SCSI optical type 5.
- `/dev/sgX` remains explicit and OFF by default.
- CDEmu D-Bus and `/dev/vhba_ctl` remain hidden from Bottles/Wine.
- UDisks2 mount state is verified; dynamic optical/cache filesystems are exposed RO.
- Live multidisc requires an explicit saved set, cache drives remain host-side, and ownership/mapping is revalidated before cleanup.

## Gamepad review

- Standard gamepad support uses Bubblejail `[joystick]`; no broad `/dev/input` share is added.
- `/dev/hidraw*` stays hidden for the 0.4.0 standard-controller path.
- Current host `jsX` plus matching `eventX` nodes are the only accepted surface; numbering is not hardcoded.
- Initial activation is non-destructive and intentionally does not synthesize a udev event.
- Real disconnect/reconnect rebuilds only the exact current nodes and matching minimal sysfs, sends matching libudev events and re-probes exact isolation.
- `gamepad_ns_entry.py` discovers the owning user namespace with `NS_GET_USERNS`, stages detached exact mounts, revalidates pinned identity and enters the required target namespaces fail-closed.
- No sudo/root/new group/host udev permission change is required.

## Verifier / scanner review

- Archive material is treated as untrusted host-side data but is never mounted or executed by the verifier.
- Descriptor traversal/absolute paths are rejected.
- CRC32/MD5/SHA1 hashing is streamed with before/after identity checks.
- DAT XML is indexed incrementally; exact verification requires one complete unique record and equivalent complete records remain `AMBIGUOUS`.
- Updater networking is HTTPS-only to approved hosts with redirect revalidation, bounded extraction, staging and rollback.
- Protection scanning is bounded/evidence-only and cannot override cryptographic DAT matching.
- Real source immutability has passed target validation.

## Final review findings / deferred cleanup

Two non-blocking cleanup items were found and deliberately left for post-release work because changing them now would reopen validated security-sensitive paths without a concrete benefit:

1. `gamepad_ns_helper.py` still contains the earlier direct CLI/`mutate_instance()` entry path. The application does not route through it: runtime hotplug uses `gamepad_ns_entry.py`. The older path failed closed on the target and is not a permissive fallback.
2. Real-sentinel staging for the CD integration test exists in both the lifecycle layer and the final wrapper, so the final call path stages redundant temporary sentinels. Both layers are restrictive and the target integration test passed; consolidation is maintenance cleanup only.

Neither issue broadens device/filesystem access, weakens fail-closed behavior or blocks 0.4.0 packaging.

## Residual risks / deliberate non-goals

- Controller/gamepad helpers, verifier and CDEmu/libMirage are host-side processes with the logged-in user's permissions.
- XML/ZIP/image/native parsing remains a host-side untrusted-data surface, although resource use and paths are bounded where practical.
- Bubblejail helper/runtime behavior is an upstream compatibility dependency; incompatibility intentionally fails closed.
- Whitelist backup is one-generation.
- Concurrent external CDEmu management should be avoided during ownership-sensitive operations.
- Abnormal process termination may leave temporary live-multidisc cache devices until recovery/manual cleanup; dedicated recovery is post-release work.
- Some games enumerate controllers only at startup; RetroCD cannot force application-level re-enumeration.
- Switch/gyro hidraw support remains out of scope for 0.4.0.

## Packaging readiness

The technical pre-packaging gate is **complete**. After the final documentation-only CI is green and the repository owner explicitly chooses to merge PR #3, merged `main` is the packaging source baseline.

Packaging must preserve:

- app ID `io.github.Paolo86cripple.BottlesRetroCD`, version `0.4.0`;
- user config, private Bottles HOME/prefixes, archive/DAT data and Bubblejail instance data on normal removal;
- host CDEmu/libMirage integration without duplicating an existing VHBA provider;
- UDisks2 for verified RO optical mounts/live multidisc;
- no hard dependency on `cdemu-client`;
- no extra broad gamepad permission/package layer;
- the exact fail-closed GPU, optical, filesystem, network and gamepad boundaries validated above.

## Merge criterion

All technical criteria are satisfied. Do **not** merge automatically: wait for the repository owner's explicit merge instruction after the final documentation-only CI reports success.
