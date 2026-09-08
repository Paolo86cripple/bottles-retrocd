# Bottles RetroCD roadmap

This roadmap records the current agreed order of work. Security-sensitive steps are not considered complete until branch CI and the relevant target-machine tests pass.

1. **Persistent configuration/profiles** — complete and regression-reviewed.
2. **GPU selector and strict DRM/Vulkan isolation** — complete and target-machine validated on both the Ryzen 7 9800X3D iGPU and Radeon RX 9070 XT dGPU; marker parsing received additional regression hardening during the Point-5 review.
3. **Multidisc and live disc swapping** — complete and target-machine validated, including Discworld Noir live swapping and cache cleanup.
4. **Redump/TOSEC verifier and protection scanner** — complete and target-machine validated, including source immutability and IBM-PC-only TOSEC materialization.
5. **Retro Optical / CDEmu + libMirage hardening and lifecycle** — complete and target-machine validated.
   - formal host/jail trust boundary;
   - exact-policy fail-closed **pre-launch** proof plus independent **post-launch** proof for VHBA, CDEmu D-Bus, optical nodes and RO mount;
   - verified no-CD, RO mount, exact `/dev/srX`, explicit advanced `/dev/sgX`, live multidisc and cleanup flows;
   - safe single-disc and multidisc eject/cleanup, including **Espelli tutto** limited to RetroCD-managed media;
   - component/version diagnostics with effective VHBA-provider detection, including kernel-bundled `linux-cachyos` VHBA;
   - safe Arch/CachyOS full-system update flow with explicit preview, terminal confirmation and post-update health check.
6. **Point 5 review gate** — complete, PASS.
   - complete diff review against `main` and full CI/static checks passed;
   - target-machine acceptance passed for no-CD, exact raw optical policy, live multidisc, cleanup and both integrated/discrete GPU paths;
   - RO-only path was independently target-validated before the final preflight hardening and remains covered by the exact-policy probe/unit suite;
   - explicit `/dev/sgX` advanced path target-tested successfully;
   - lifecycle manager, updater negative paths and `Espelli tutto` target-tested successfully;
   - GTK/main-thread safety, GPU isolation, network-OFF, whitelist, persistent settings and verifier/source-immutability invariants regression-reviewed.
7. **dgVoodoo2 manager** — next active point, before packaging.
   - per-game/bottle installation rather than global DLL replacement;
   - controlled DirectX/Glide wrapper selection;
   - backup/restore of replaced files;
   - version/configuration visibility;
   - no weakening of the Bubblejail boundary.
8. **Arch/CachyOS packaging** — install/remove RetroCD cleanly and integrate required host components without duplicating privileged infrastructure.
9. **Release hardening and polish** — final regression review, documentation, packaging/release artifacts and target-machine acceptance pass.

## Scope reminder

The project remains focused on Windows retro PC games. Modern-game support is deliberately narrow: official single-player offline titles may use the same generic Bottles/Bubblejail sandbox, without expanding the architecture around launchers, online services, anti-cheat or unofficial repacks.
