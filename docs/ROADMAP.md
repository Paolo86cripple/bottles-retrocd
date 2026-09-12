# Bottles RetroCD roadmap

## Released baseline: 0.4.0

Bottles RetroCD **0.4.0** is the current published baseline, tagged from reviewed `main` merge commit `15b1e0acc61d61978051d49d97bd17cb97efb348`.

Its validated foundation includes:

- explicit archive-root persistence and dump immutability;
- strict selected-GPU DRM/Vulkan isolation;
- Wayland/XWayland compatibility with private-HOME preference persistence;
- Retro Optical CDEmu/UDisks2 handling;
- explicit multidisc/live swapping;
- Redump/TOSEC verification and protection scanning;
- exact-node standard gamepad isolation/hotplug;
- native Arch/CachyOS packaging and uninstall-preservation.

## 0.4.1 compatibility-preserving hardening

0.4.1 is the active maintenance release line. It deliberately avoids adding a new game-compatibility stack and instead hardens the already validated architecture.

Completed/target-validated work:

1. **Verifier/scanner isolation** — dedicated non-networked bubblewrap worker; archive/app/catalog RO, hash cache only RW, private HOME/tmp, minimal dev, no host proc/sys/runtime, positive attestation and fail-closed path/layout checks.
2. **Official DAT updater isolation** — separate networked bubblewrap worker; archive invisible, data/cache only RW, exact DNS/TLS inputs, official HTTPS allow-list, staged rebuild/integrity/rollback.
3. **CDEmu ownership/recovery** — inter-process flock, private ownership journal, exact appended-suffix model, write-ahead cleanup and fail-closed stale recovery; normal multidisc and SIGKILL recovery validated.
4. **Runtime surface / D-Bus hardening** — host dconf removed from the validated profile, keyfile preference persistence proven, effective proxy audit added, normal/live runtime surfaces measured, process FD/environment-name hygiene checked.
5. **Pre-launch dconf guard** — launch now refuses a profile that re-enables `gnome_toolkit.dconf_dbus` or raw session D-Bus grants that include `ca.desrt.dconf`; active-proxy inspection remains the independent runtime proof.
6. **Gamepad hotplug race hardening** — exact unplug/replug topology races are retried narrowly without weakening identity checks; unrelated helper failures remain hard failures.
7. **Consolidated target regression** — Sandbox self-test, Discworld Noir non-live/live paths, verifier/update flow and Xbox One S hotplug have passed on the target CachyOS machine.
8. **Arch/CachyOS release packaging** — metadata is 0.4.1-1. The exact final pinned artifact must pass clean build/install/integrity/uninstall-preservation before merge/release; any source-pin change invalidates evidence from an earlier candidate artifact.

## Next compatibility priorities after 0.4.1

1. **Native legacy optical DRM compatibility/emulation.** Investigate SafeDisc, SecuROM, LaserLock, StarForce and other Windows 9x/XP optical protections. Reproduce original-media verification behavior through Wine/CDEmu/libMirage or dedicated license-compatible components where feasible. A No-CD/cracked executable must not become the normal solution. Backends stay optional/fail-closed and must not broaden sandbox/optical permissions merely to work.
2. **Legacy DirectX compatibility manager.** Evaluate/integrate DxWrapper/dgVoodoo2-style support for DirectX 5–9 titles, optional and OFF by default. This comes after optical DRM work and before shaders.
3. **libRashader + Slang shaders.** Optional, per game/bottle and OFF by default after the compatibility foundation is stable.

## Maintenance backlog

- consolidate release identity constants into one shared module only after focused regression review;
- retire/remove the old direct `mutate_instance()` helper path if it remains unused;
- consider deduplicating restrictive real-sentinel staging between lifecycle/final-wrapper layers;
- keep package/release evidence tied to exact immutable source pins and tags.

These items must not weaken the validated Bubblejail boundary or become mandatory without a concrete reviewed reason.

## Scope reminder

Bottles RetroCD remains focused on Windows retro PC games. DOS uses DOSBox-Staging; ScummVM, console emulation and Steam management remain outside this architecture.
