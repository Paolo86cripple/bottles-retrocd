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

The same bottle launched with `DISPLAY` removed from the child environment opened `winecfg` correctly through `winewayland.drv`.

This is not dgVoodoo2-specific. Bubblejail issue #230 (`Bottles: X Window System error`) reports the same MIT-SHM family of failure with Bottles on CachyOS:

- https://github.com/igo95862/bubblejail/issues/230

Bubblejail intentionally starts bubblewrap with `--unshare-all`, while its X11 service exposes the X socket/Xauthority. RetroCD MUST NOT work around MIT-SHM by sharing the host IPC namespace.

## Security policy

- Do not add host IPC sharing to the Bottles instance.
- Do not weaken Bubblejail namespace isolation to make XShm work.
- Do not change network, filesystem, GPU, optical or CDEmu permissions as part of display selection.
- Native Wayland is selected narrowly by removing `DISPLAY` from the Wine/Bottles child process; the Wayland socket already exposed by the existing Bubblejail profile remains the transport.
- XWayland remains an explicit compatibility fallback until release acceptance proves where it is still required.

## Current Point-7 behavior

`dgVoodooCpl.exe` is launched through Wine native Wayland because the target already proved the XWayland MIT-SHM path broken and the native Wayland `winecfg` path functional.

The normal RetroCD/Bottles game-launch path is intentionally unchanged while the display matrix is active.

## Non-game display matrix

Before changing the general default, test the same bottle with the public Bottles Wine utilities in both display modes:

1. `winecfg`
2. `regedit`
3. `taskmgr`
4. `control`
5. `explorer`

Use `display_probe_cli.py`; no games, downloads, registry mutations or Bubblejail profile changes are required by the probe itself.

Example:

```text
python ./display_probe_cli.py --bottle retrocd-vodoo-test --backend xwayland --tool winecfg
python ./display_probe_cli.py --bottle retrocd-vodoo-test --backend wayland  --tool winecfg
```

The CLI detects the known MIT-SHM failure pattern but cannot determine whether a graphical window was visible; visual appearance must still be confirmed on the target.

## Promotion gate for native Wayland default

Native Wayland may become RetroCD's default only after:

- the non-game Win32/GDI matrix is target-PASS;
- a synthetic non-game DirectDraw/Direct3D/Vulkan surface probe is target-PASS;
- strict iGPU and dGPU selection remains correct;
- fullscreen, scaling, pointer confinement and keyboard behavior are reviewed;
- XWayland remains available as a per-title fallback without host IPC sharing;
- release/RC real-title acceptance (Point 9) covers titles that need XWayland-specific behavior.

Wine 11.x continues to improve the native Wayland driver, including exclusive fullscreen and legacy DDraw-related improvements, but upstream still has open monitor/scaling edge cases. RetroCD therefore treats display backend selection as a compatibility policy, not a universal assumption.
