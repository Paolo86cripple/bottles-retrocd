# Bottles RetroCD roadmap

This roadmap records the current agreed order of work. Security-sensitive steps are not considered complete until branch CI and the relevant target-machine tests pass.

1. **Persistent configuration/profiles** — complete.
2. **GPU selector and strict DRM/Vulkan isolation** — complete and target-machine validated; marker parsing received an additional regression hardening during the Point-5 review.
3. **Multidisc and live disc swapping** — complete and target-machine validated.
4. **Redump/TOSEC verifier and protection scanner** — complete and target-machine validated, including source immutability and IBM-PC-only TOSEC materialization.
5. **Retro Optical / CDEmu + libMirage hardening and lifecycle** — implementation complete; final review acceptance in progress.
   - formal host/jail trust boundary;
   - exact-policy fail-closed **pre-launch** proof plus independent **post-launch** proof for VHBA, CDEmu D-Bus, optical nodes and RO mount;
   - safe single-disc and multidisc eject/cleanup flows, including an explicit **Espelli tutto** action limited to RetroCD-managed media;
   - component/version diagnostics with effective VHBA-provider detection, including kernel-bundled `linux-cachyos` VHBA;
   - safe Arch/CachyOS full-system update flow with explicit preview, terminal confirmation and post-update health check.
6. **Point 5 review gate** — mandatory security/regression review before moving on; active.
   - complete diff review against `main` and full CI/static checks;
   - repeat the target-machine matrix after review hardening: no CD, RO mount only, exact `/dev/srX`, advanced `/dev/sgX` if retained, live multidisc and cleanup;
   - verify `Espelli` and `Espelli tutto`, including stale-cache/error paths and preservation of non-RetroCD CDEmu media;
   - verify that VHBA control and CDEmu D-Bus remain host-only and that no stale mounts/devices/services remain after cleanup;
   - regression-check GTK/main-thread safety, GPU isolation, network OFF, whitelist, persistent settings and verifier/source-immutability invariants.
7. **dgVoodoo2 manager** — dedicated legacy-graphics compatibility point before packaging.
   - per-game/bottle installation rather than global DLL replacement;
   - controlled DirectX/Glide wrapper selection;
   - backup/restore of replaced files;
   - version/configuration visibility;
   - no weakening of the Bubblejail boundary.
8. **Arch/CachyOS packaging** — install/remove RetroCD cleanly and integrate required host components without duplicating privileged infrastructure.
9. **Release hardening and polish** — final regression review, documentation, packaging/release artifacts and target-machine acceptance pass.

## Scope reminder

The project remains focused on Windows retro PC games. Modern-game support is deliberately narrow: official single-player offline titles may use the same generic Bottles/Bubblejail sandbox, without expanding the architecture around launchers, online services, anti-cheat or unofficial repacks.
