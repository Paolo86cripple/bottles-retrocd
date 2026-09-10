# Bottles RetroCD roadmap

## Released baseline: 0.4.0

Bottles RetroCD **0.4.0** is released and tagged from the reviewed `main` merge commit `15b1e0acc61d61978051d49d97bd17cb97efb348`.

Completed and target-validated in 0.4.0:

1. Persistent configuration/profiles — complete and target validated, including schema-2 `archive_root` persistence and dump immutability.
2. GPU selector and strict DRM/Vulkan isolation — complete and target validated on both AMD GPU paths.
3. Multidisc and live disc swapping — complete and target validated.
4. Redump/TOSEC verifier and protection scanner — complete and target validated with source immutability.
5. Retro Optical / CDEmu + libMirage lifecycle — complete and target validated.
6. Display and preference persistence — complete and target validated: Auto, native Wayland, XWayland and isolated GSettings keyfile persistence.
7. Standard gamepad exact-node isolation and physical hotplug — complete and target validated with `sysfs=exact`, correct initial/change udev semantics and `hidraw=hidden`.
8. Pre-release review — **PASS**: 151 tests, CI green, real archive/sentinel/RO checks PASS, resize/scroll PASS, final XWayland Discworld Noir launch PASS with GPU + Retro Optical pre/post proof.
9. Arch/CachyOS packaging — **COMPLETE**. Final package is `bottles-retrocd 0.4.0-3`, with tracked `.SRCINFO`, package migration metadata, clean install/upgrade, 53 files / 0 altered files, and uninstall-preservation PASS.
10. 0.4.0 release — **COMPLETE**. PR #4 merged, post-merge `main` CI PASS, annotated tag `0.4.0` published and verified against merge commit `15b1e0acc61d61978051d49d97bd17cb97efb348`.

The released 0.4.0 baseline is now frozen except for narrowly scoped maintenance/security fixes. New compatibility features belong to post-release branches and must preserve the validated Bubblejail boundary.

## Post-release priorities

1. **Native legacy optical DRM compatibility/emulation — ACTIVE NEXT OBJECTIVE.** Investigate SafeDisc, SecuROM, LaserLock, StarForce and other Windows 9x/XP-era optical protections; reproduce original media/protection behavior as natively as practical through Wine/CDEmu/libMirage or dedicated compatible components; study and reuse existing open-source projects when technically appropriate and license-compatible. A No-CD/cracked executable must not become the normal solution. Backends remain optional/fail-closed and must not broaden Bubblejail or optical permissions merely to work.
2. **Legacy DirectX compatibility manager.** Evaluate/integrate DxWrapper/dgVoodoo2-style support for DirectX 5–9-era titles, optional and OFF by default. This comes after the optical-DRM objective and before shaders.
3. **libRashader + Slang shaders.** Optional, per game/bottle and OFF by default, after the compatibility foundation is stable.
4. **Abnormal-termination recovery for live multidisc cache devices.** Recover temporary cache devices safely after abnormal GUI/process termination without weakening ownership or mapping validation.

## Post-release maintenance backlog

- Consolidate release identity constants into one shared module instead of final-wrapper overrides, only after a focused regression review.
- Retire or remove the old direct `mutate_instance()` helper path in `gamepad_ns_helper.py` if no longer required.
- Consider deduplicating restrictive real-sentinel staging between lifecycle and final wrapper layers.

These are maintenance items, not reasons to destabilize the released security-sensitive paths.

## Scope reminder

Bottles RetroCD remains focused on Windows retro PC games. DOS uses DOSBox-Staging; ScummVM, console emulation and Steam management remain outside this architecture.
