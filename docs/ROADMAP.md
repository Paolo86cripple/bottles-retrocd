# Bottles RetroCD roadmap

The 0.4.0 feature set is frozen. The final real-machine pre-packaging gate and final PR security review are complete; no additional feature work belongs in 0.4.0 before packaging.

1. Persistent configuration/profiles — complete and target validated, including schema-2 `archive_root` persistence and dump immutability.
2. GPU selector and strict DRM/Vulkan isolation — complete and target validated on both AMD GPU paths.
3. Multidisc and live disc swapping — complete and target validated.
4. Redump/TOSEC verifier and protection scanner — complete and target validated with source immutability.
5. Retro Optical / CDEmu + libMirage lifecycle — complete and target validated.
6. Display and preference persistence — complete and target validated: Auto, native Wayland, XWayland and isolated GSettings keyfile persistence.
7. Standard gamepad exact-node isolation and physical hotplug — complete and target validated with `sysfs=exact`, correct initial/change udev semantics and `hidraw=hidden`.
8. 0.4.0 pre-packaging review — **PASS**: 151 tests, CI green, real archive/sentinel/RO checks PASS, resize/scroll PASS, final XWayland Discworld Noir launch PASS with GPU + Retro Optical pre/post proof.
9. Arch/CachyOS packaging — immediate next step after PR #3 merge. Install only package-owned files, provide desktop integration and correct dependencies, and preserve user config/archive/Bubblejail data on normal removal.
10. 0.4.0 release — installed-package acceptance, release hardening, final regression, tag and GitHub release.

## Post-release priorities

1. **Native legacy optical DRM compatibility/emulation** — first post-release-hardening compatibility objective. Investigate SafeDisc, SecuROM, LaserLock, StarForce and other Windows 9x/XP-era optical protections; reproduce the original media/protection behavior as natively as practical through Wine/CDEmu/libMirage or dedicated compatible components; study and reuse existing open-source projects when technically appropriate and license-compatible. A No-CD/cracked executable must not become the normal solution. Backends remain optional/fail-closed and must not broaden Bubblejail or optical permissions merely to work.
2. **Legacy DirectX compatibility managers** — evaluate/integrate DxWrapper/dgVoodoo2-style support for DirectX 5–9-era titles, optional and OFF by default, after release hardening and after the DRM compatibility objective above.
3. **libRashader + Slang shaders** — optional, per game/bottle and OFF by default, after the compatibility foundation is stable.
4. **Abnormal-termination recovery for live multidisc cache devices** — recover safely without weakening device-ownership validation.

None of the post-release features may weaken the validated Bubblejail boundary or become mandatory for ordinary launch paths without a concrete reviewed reason.

## Scope reminder

Bottles RetroCD remains focused on Windows retro PC games. DOS uses DOSBox-Staging; ScummVM, console emulation and Steam management remain outside this architecture.
