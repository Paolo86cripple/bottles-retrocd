# Bottles RetroCD roadmap

This roadmap records the current agreed order of work. Security-sensitive steps are not considered complete until branch CI and the relevant target-machine tests pass.

1. **Persistent configuration/profiles** — complete.
2. **GPU selector and strict DRM/Vulkan isolation** — complete and target-machine validated.
3. **Multidisc and live disc swapping** — complete and target-machine validated.
4. **Redump/TOSEC verifier and protection scanner** — complete and target-machine validated, including source immutability and IBM-PC-only TOSEC materialization.
5. **Retro Optical / CDEmu + libMirage hardening and lifecycle** — in progress.
   - formal host/jail trust boundary;
   - fail-closed post-launch proof for VHBA, CDEmu D-Bus, optical nodes and RO mount;
   - component/version diagnostics;
   - safe Arch/CachyOS package lifecycle and explicit update flow.
6. **Arch/CachyOS packaging** — install/remove RetroCD cleanly and integrate required host components without duplicating privileged infrastructure.
7. **dgVoodoo2 manager** — dedicated legacy-graphics compatibility point before release.
   - per-game/bottle installation rather than global DLL replacement;
   - controlled DirectX/Glide wrapper selection;
   - backup/restore of replaced files;
   - version/configuration visibility;
   - no weakening of the Bubblejail boundary.
8. **Release hardening and polish** — final regression review, documentation, packaging/release artifacts and target-machine acceptance pass.

## Scope reminder

The project remains focused on Windows retro PC games. Modern-game support is deliberately narrow: official single-player offline titles may use the same generic Bottles/Bubblejail sandbox, without expanding the architecture around launchers, online services, anti-cheat or unofficial repacks.
