# Retro Optical trust boundary

## Purpose

Retro Optical is the optical-media compatibility layer used by Bottles RetroCD for Windows CD/DVD games. Its security goal is narrower than “sandbox CDEmu”: CDEmu/libMirage and UDisks2 remain trusted host-side infrastructure, while the untrusted Windows game remains inside Bubblejail and receives only the minimum optical surface required for compatibility.

0.4.1 keeps the validated 0.4.0 game boundary and hardens CDEmu ownership/recovery around it.

## Upstream model

`cdemu_backend.py` implements only the subset of the CDEmu D-Bus API required by RetroCD. Omitting broader daemon methods from the Python client is not an access-control boundary: the game must not be able to reach the host CDEmu D-Bus service at all.

Normal loaded image media is treated as read-only optical content. Raw SCSI interfaces remain broader than a filesystem RO mount and are therefore separate, explicit compatibility options.

## Host-side trusted plane

These components remain outside Bubblejail:

- the VHBA kernel provider and `/dev/vhba_ctl`;
- `cdemu-daemon`;
- libMirage image parsing;
- RetroCD's CDEmu D-Bus controller;
- UDisks2 optical mounting;
- original archive images under the authorized archive root;
- optional diagnostic clients such as gCDEmu or `cdemu-client`.

The CDEmu daemon requires the VHBA control interface. Moving that control plane into the untrusted game jail would require exposing a privileged host-control surface and would weaken the design.

## Bubblejail game plane

The game must never receive:

- `/dev/vhba_ctl`;
- access to `net.sf.cdemu.CDEmuDaemon` on D-Bus;
- the CDEmu daemon as a jail service;
- libMirage parsing of source images inside the game jail;
- generic `/dev`, broad removable-media trees or cached multidisc optical devices.

The game may receive only:

1. `/mnt/cdemu`, from a verified RO UDisks2 mount via restrictive bind policy; and/or
2. the exact CDEmu `/dev/srN` mapped to the active drive when raw optical compatibility is required; and/or
3. the exact paired `/dev/sgN` only after explicit advanced opt-in.

Raw `/dev/srX` and `/dev/sgX` are OFF by default.

## Mandatory pre-launch optical proof

Every normal Bottles launch is fail-closed before game code starts. RetroCD validates the exact runtime policy that would be used for the real launch.

The probe must confirm:

- `/dev/vhba_ctl` absent;
- CDEmu D-Bus blocked;
- visible `/dev/srN` set exactly equal to the authorized set (normally zero or one);
- visible `/dev/sgN` set exactly equal to the authorized set (normally zero);
- `/mnt/cdemu` absent when not authorized;
- when authorized, `/mnt/cdemu` is a directory and `findmnt` reports it RO.

Missing/ambiguous proof blocks launch. The probe does not perform a write attempt against optical media.

## Mandatory post-launch optical proof

After Bottles starts, RetroCD attaches an independent proof to the already-running jail and rechecks:

- VHBA hidden;
- CDEmu D-Bus blocked;
- exact `srN`/`sgN` visibility;
- `/mnt/cdemu` RO state.

Bubblejail output is parsed using complete expected marker lines only; echoed command text is never accepted as proof. If a post-launch proof fails, RetroCD terminates the exact launch process group and performs safe cleanup when possible.

## Live multidisc

Live multidisc requires an explicit saved set. Cache drives remain host-side. The jail receives only the single active optical device when raw exposure is required, while `/mnt/cdemu` follows the selected disc through the validated RO mount bank/bridge path.

Target validation proved Discworld Noir live swapping with one exact active `/dev/sr0`, cached drives hidden, `/dev/sgX` hidden, `/mnt/cdemu=RO` and unchanged D-Bus/socket/network/GPU surface across a Disc 1 → Disc 2 swap.

## 0.4.1 durable ownership and crash recovery

CDEmu device creation/removal is ownership-sensitive because upstream device lifecycle is append/remove-last oriented. 0.4.1 therefore adds durable evidence instead of relying only on in-memory cache bookkeeping.

### Inter-process lock

Mutating RetroCD CDEmu work is serialized through an `flock`-based operation/session lock stored under private XDG state. The lock file is user-owned, mode 0600 and opened CLOEXEC. A second cooperating RetroCD process cannot mutate the CDEmu suffix while a live ownership lease exists.

### Ownership journal

A private mode-0600 journal records:

- schema/session ID;
- host boot ID;
- CDEmu daemon identity (bus GUID + unique name owner);
- owner PID + process start ticks;
- baseline device count;
- exact expected images;
- each owned device index, image, `/dev/srX`, `/dev/sgX`, mount and block rdev;
- pending AddDevice intent;
- write-ahead removing index and cleanup phase.

The journal accepts only an exact contiguous suffix beginning at the recorded baseline.

### Recovery rules

Recovery never guesses ownership. Before any destructive action RetroCD revalidates:

- same host boot and daemon identity;
- exact expected device count and contiguous indexes;
- exact sr/sg mapping;
- exact rdev;
- loaded media identity/state;
- compatible verified RO mount evidence.

A changed boot/daemon makes the old journal obsolete; the journal may be cleared without touching current devices. Mapping/count/media ambiguity or unjournaled mount state causes fail-closed refusal.

Cleanup is LIFO. Before `RemoveDevice`, the intent is written to the journal. A crash after upstream removal but before journal commit can therefore be reconciled by exact device-count evidence on restart.

Stale recovery is refused while Bottles/Bubblejail is still active. Once Bottles closes, only the exact proven owned suffix is removed.

### Validated recovery evidence

- normal three-disc cache/swap/cleanup: PASS;
- SIGKILL of RetroCD while the live cache existed: recovery deferred while Bottles remained open, then exact LIFO owned-suffix cleanup after close: PASS;
- crash after mapping / after load but before mount: unit-covered recoverable stages;
- unknown/unattributed mount or pending extra device ambiguity: fail closed.

## Non-live launch serialization

0.4.1 also fixes the non-live self-contention path: stale recovery is resolved first, then a temporary CDEmu session lock protects the launch preparation without recursively reacquiring the same flock. This path has been target-validated with Discworld Noir.

## Component lifecycle on Arch/CachyOS

RetroCD uses distribution-managed CDEmu components rather than privately bundling a second daemon/kernel stack.

The lifecycle manager:

- reads installed package versions through pacman;
- queries daemon/libMirage runtime versions and CDEmu interface version over host D-Bus;
- verifies the effective VHBA provider for the running kernel;
- verifies `/dev/vhba_ctl` as the expected host character device;
- accepts a kernel-bundled provider such as `kernel:linux-cachyos` without installing duplicate DKMS infrastructure;
- treats `cdemu-client` as optional diagnostics;
- reports pending component updates without applying them automatically.

The explicit updater performs a full Arch/CachyOS `pacman -Syu`, never a partial upgrade. It requires Bottles closed and no unresolved RetroCD CDEmu ownership journal/lease. The CDEmu ownership lock remains held across the preflight and transaction path, with a second media/running-instance check immediately before touching the daemon.

The GUI shows the intended transaction first; the terminal helper requires explicit confirmation and pacman retains its own confirmation. No `--noconfirm` path is used.

## Eject and cleanup policy

Single-device eject may neutralize the active live bridge before unloading selected media.

`Espelli tutto` is intentionally conservative:

- Bottles must be closed;
- a RetroCD-owned live cache is cleaned through the ownership journal rules above;
- generic CDEmu devices are not blindly removed;
- media outside the authorized RetroCD archive root remains outside RetroCD's destructive policy.

If ownership cannot be proven, RetroCD leaves ambiguous devices in place rather than risking another client's drive.

## Acceptance tests

Before merge/release, validate on the target CachyOS system:

1. no optical media: pre/post proof `vhba=hidden`, CDEmu D-Bus blocked, sr hidden, sg hidden, `/mnt/cdemu=hidden`;
2. RO filesystem-only exposure: `/mnt/cdemu=RO`, raw nodes hidden;
3. exact raw `/dev/srN` when explicitly enabled;
4. exact `/dev/sgN` only when the advanced path is explicitly enabled;
5. Discworld Noir live multidisc with one active sr, hidden cached drives/sg and RO mount;
6. normal cache cleanup after Bottles exit;
7. abnormal-process recovery with exact journal/lock evidence;
8. updater negative paths while Bottles/ownership/media state is unsafe;
9. full static/unit gate and regressions for GPU, filesystem, network, verifier and gamepad boundaries.

Do not weaken a failed proof to a warning for compatibility. A title that needs a broader optical surface requires a narrow reviewed policy change rather than an implicit fallback.
