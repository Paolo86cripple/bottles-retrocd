# Bottles RetroCD roadmap

The 0.4.0 feature set is frozen except for release blockers.

1. Persistent configuration/profiles — complete.
2. GPU selector and strict DRM/Vulkan isolation — complete and target validated.
3. Multidisc and live disc swapping — complete and target validated.
4. Redump/TOSEC verifier and protection scanner — complete and target validated.
5. Retro Optical / CDEmu + libMirage lifecycle — complete and target validated.
6. Display and preference persistence — complete and target validated: Auto, native Wayland, XWayland, GSettings keyfile persistence.
7. 0.4.0 pre-packaging review — automated gate complete at 130 tests PASS; final target archive-root/sentinel acceptance pending.
8. Arch/CachyOS packaging — immediate next step after review merge. Install only package-owned files, provide desktop integration and correct dependencies, and preserve all user config/archive/Bubblejail data on normal removal.
9. 0.4.0 release — installed-package acceptance, final regression, tag and GitHub release.
10. Legacy DirectX compatibility managers such as dgVoodoo2/DxWrapper — post-0.4.0, optional and OFF by default.
11. Optional libRashader + Slang shader integration — post-release, per game/bottle, OFF by default and without weakening Bubblejail.

## Scope reminder

Bottles RetroCD remains focused on Windows retro PC games. DOS uses DOSBox-Staging; ScummVM, console emulation and Steam management remain outside this architecture.
