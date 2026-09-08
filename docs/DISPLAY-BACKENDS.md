# Wine display backends inside Bubblejail

## Scope

RetroCD runs Bottles/Wine inside a Bubblejail instance whose isolation remains the security boundary. Display compatibility must not be fixed by weakening that boundary.

## Target finding — 2026-09-08

On the CachyOS target, a Bottles Wine utility launched through the inherited X11/XWayland path failed before showing a window with:

```text
X Error of failed request: BadValue
Major opcode of failed request: 130 (MIT-SHM)
Minor opcode of failed request: 3 (X_ShmPutImage)
```

The same bottle launched with `DISPLAY` removed from the child environment opened `winecfg` correctly through Wine native Wayland.

A second target test proved that nested Gamescope can create an XWayland server *inside* the Bubblejail namespace. This avoids crossing the host IPC boundary for MIT-SHM and therefore preserves Bubblejail's namespace isolation.

## Security policy

- Do not share the host IPC namespace.
- Do not add persistent Bubblejail capabilities to solve display performance.
- Do not grant `CAP_SYS_NICE` to Gamescope from RetroCD.
- Do not change network, filesystem, GPU, optical or CDEmu permissions as part of display selection.
- Native Wayland is selected narrowly by removing `DISPLAY` from the child process.
- Host XWayland remains available only as a diagnostic/legacy path because MIT-SHM is broken on the validated target.
- Internal Gamescope/XWayland is the compatibility fallback for software that requires X11.

## Why RetroCD does not grant CAP_SYS_NICE

Gamescope can use `CAP_SYS_NICE` to raise process/thread priority and optionally real-time scheduling. Bubblewrap, however, drops capabilities from sandboxed processes by default. Granting a capability through the sandbox or assigning a global file capability to the host `gamescope` binary would widen privilege beyond the narrow display-compatibility requirement. RetroCD therefore accepts normal-priority Gamescope scheduling and keeps the sandbox capability set unchanged.

## Lightweight Gamescope profile

The compatibility fallback uses stock Gamescope with the minimum runtime feature set required to host one XWayland server:

```text
env -u DISPLAY \
  gamescope \
    --backend wayland \
    --xwayland-count 1 \
    --disable-color-management \
    -w 1920 -h 1080 \
    -W 1920 -H 1080 \
    -f \
    -- \
    gamescopereaper -- <Bottles/Wine command>
```

Policy:

- default internal resolution: **1920x1080**;
- output resolution: **1920x1080**;
- 1:1 input/output dimensions, so no intentional scaling step;
- exactly one internal XWayland server;
- no FSR;
- no NIS;
- no scaler/filter override;
- no frame limiter or refresh-rate override;
- no HDR;
- no adaptive-sync request;
- no immediate-flips request;
- no MangoApp;
- no Steam integration mode;
- no `--rt`;
- no host IPC sharing;
- no additional capability.

`gamescopereaper` is used instead of shell sleeps. It becomes a subreaper and keeps Wine descendants associated with Gamescope until they terminate.

## Current default policy

Until the synthetic display matrix and release acceptance are complete:

1. Wine native Wayland is the preferred path for minimum compositor overhead.
2. Internal Gamescope/XWayland is the explicit compatibility fallback.
3. Host XWayland is retained for diagnostics but is not considered reliable on the validated target.

The normal game-launch path is not promoted to a new default until the non-game matrix, synthetic graphics probes, iGPU/dGPU isolation and release acceptance pass.
