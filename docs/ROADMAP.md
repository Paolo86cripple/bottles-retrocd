# Bottles RetroCD roadmap

This roadmap records the current agreed order of work. Security-sensitive steps are not considered complete until branch CI and the relevant target-machine tests pass.

1. **Persistent configuration/profiles** — complete.
2. **GPU selector and strict DRM/Vulkan isolation** — complete and target-machine validated.
3. **Multidisc and live disc swapping** — complete and target-machine validated.
4. **Redump/TOSEC verifier and protection scanner** — complete and target-machine validated, including source immutability and IBM-PC-only TOSEC materialization.
5. **Retro Optical / CDEmu + libMirage hardening and lifecycle** — in progress.
   - formal host/jail trust boundary;
   - fail-closed post-launch proof for VHBA, CDEmu D-Bus, optical nodes and RO mount;
   - safe single-disc and multidisc eject/cleanup flows, including an explicit **Espelli tutto** action limited to RetroCD-managed media;
   - component/version diagnostics;
   - safe Arch/CachyOS package lifecycle and explicit update flow.
6. **Point 5 review gate** — mandatory security/regression review before packaging.
   - review the complete point-5 diff against `main` and re-run full CI/static checks;
   - repeat the target-machine matrix: no CD, RO mount only, exact `/dev/srX`, advanced `/dev/sgX` if retained, live multidisc and cleanup;
   - verify `Espelli` and `Espelli tutto`, including stale-cache/error paths and preservation of non-RetroCD CDEmu media;
   - verify that VHBA control and CDEmu D-Bus remain host-only and that no stale mounts/devices/services remain after cleanup;
   - regression-check GTK/main-thread safety, GPU isolation, network OFF, whitelist and source immutability invariants.
7. **Arch/CachyOS packaging** — install/remove RetroCD cleanly and integrate required host components without duplicating privileged infrastructure.
8. **dgVoodoo2 manager** — dedicated legacy-graphics compatibility point before release.
   - per-game/bottle installation rather than global DLL replacement;
   - controlled DirectX/Glide wrapper selection;
   - backup/restore of replaced files;
   - version/configuration visibility;
   - no weakening of the Bubblejail boundary.
9. **Release hardening and polish** — final regression review, documentation, packaging/release artifacts and target-machine acceptance pass.

## Scope reminder

The project remains focused on Windows retro PC games. Modern-game support is deliberately narrow: official single-player offline titles may use the same generic Bottles/Bubblejail sandbox, without expanding the architecture around launchers, online services, anti-cheat or unofficial repacks.
