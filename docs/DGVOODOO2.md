# dgVoodoo2 manager architecture

## Scope

Point 7 adds dgVoodoo2 as an optional compatibility layer for selected Windows games inside Bottles. It is not a new sandbox layer and it must not weaken the Bubblejail policy validated in Points 1–6.

dgVoodoo2 is upstream software by Dénes "Dege" Soltész. RetroCD does **not** vendor or redistribute its runtime binaries. The manager downloads the normal runtime ZIP on explicit user request from the official `dege-diosg/dgVoodoo2` GitHub release and verifies the SHA-256 digest published in GitHub release metadata before any file can be installed.

Upstream explicitly states that Wine/Proton are not supported targets. RetroCD therefore treats dgVoodoo2 as an optional, per-title compatibility experiment: failure must be reversible and must never become a prerequisite for launching a game normally.

## Security and ownership model

The host-side RetroCD controller may:

- read official GitHub release metadata;
- download the normal runtime ZIP into RetroCD's private XDG cache;
- validate archive structure and selected payloads;
- copy selected wrapper DLLs into one game directory inside one private Bottles `drive_c`;
- keep private manifests/backups under RetroCD's XDG data directory;
- restore the exact pre-installation state when every managed file still matches the content RetroCD installed.

It must never:

- install dgVoodoo2 DLLs globally into Wine, Bottles, `/usr`, or the Windows system directory by default;
- copy every wrapper DLL "just in case";
- modify files outside the selected bottle's `drive_c`;
- follow destination symlinks;
- overwrite an existing per-game `dgVoodoo.conf` by default;
- silently replace a managed file that the user or another tool changed after installation;
- enable network inside the game jail to fetch dgVoodoo2;
- weaken GPU, HOME, filesystem, CDEmu/VHBA, network or D-Bus isolation.

## Phase 7A: payload and transaction backend

The first implementation phase is deliberately GUI-independent.

The backend:

1. discovers normal Bottles under the Bubblejail private HOME;
2. accepts only bottle roots with `bottle.yml` and a normal `drive_c` directory;
3. validates that the selected executable resolves inside that `drive_c`;
4. parses the executable PE header and chooses dgVoodoo2 `x86` or `x64` payloads from the **game architecture**, never from the host architecture;
5. validates the official release metadata and required SHA-256 digest;
6. validates ZIP paths, rejects traversal/symlinks/duplicates and enforces size limits;
7. installs only the explicitly selected wrappers;
8. preserves an existing `dgVoodoo.conf` by default;
9. backs up replaced files outside the bottle and writes a private manifest;
10. refuses uninstall if a managed file has changed since RetroCD installed it;
11. otherwise removes files created by RetroCD and restores backed-up originals.

Supported selectable wrapper payloads:

- DirectDraw: `DDraw.dll`;
- legacy Direct3D: `D3DImm.dll`, `D3DIM700.dll`;
- Direct3D 8: `D3D8.dll`;
- Direct3D 9: `D3D9.dll`;
- Glide: `Glide.dll`, `Glide2x.dll`, `Glide3x.dll`;
- Glide3 Napalm: the alternate `Glide3x.dll` from the Napalm directory.

Regular Glide3 and Napalm Glide3 are mutually exclusive because both produce `Glide3x.dll` in the game directory.

## Phase 7B: Bottles/Wine integration

Copying a wrapper beside a game executable is only half of a Wine integration. The next phase must validate the effective Wine DLL load policy on the target system.

Preferred design, if confirmed by target tests:

- use Wine **per-application** DLL overrides rather than bottle-global overrides;
- set only the exact DLL names selected for that executable to `native,builtin`;
- snapshot any pre-existing per-application override values and restore them on uninstall;
- never edit `bottle.yml` directly when Bottles exposes a supported CLI/registry path;
- verify the loaded wrapper with runtime evidence before calling the integration active.

If per-application override semantics cannot be proven reliable with the installed Bottles/Wine runner, RetroCD will not fall back silently to broad bottle-global overrides. The safe fallback is to require a dedicated bottle for that title or to leave the override step manual until a narrower mechanism is available.

## Phase 7C: GUI and configuration

The GUI will expose a dedicated dgVoodoo2 tab with:

- official installed/cached/latest version;
- bottle selector;
- game executable selector constrained to the selected bottle's `drive_c`;
- detected PE architecture;
- individual DirectX/Glide wrapper switches;
- explicit Napalm selection;
- current managed/unmanaged/conflict state;
- install/update/uninstall/restore actions;
- exact Wine override preview;
- launch of `dgVoodooCpl.exe` only for the selected game/bottle;
- clear warning that upstream does not support Wine/Proton.

No wrapper is enabled automatically by game age or filename. Automatic API detection may be added later only as a suggestion; the final install set remains explicit.

## Acceptance gate

Before Point 7 can merge to `main`:

1. CI must cover metadata parsing, PE architecture, ZIP validation, transaction rollback and modified-file refusal;
2. target test must install into a disposable retro bottle and prove that unrelated bottle/game files are unchanged;
3. target test must prove uninstall restores an intentionally pre-existing DLL byte-for-byte;
4. target test must prove an intentionally edited managed DLL blocks automatic restore;
5. x86 must be tested first; x64 support remains available but is not considered target-validated until a suitable title is tested;
6. at least one DirectDraw/legacy-D3D title and one Glide title should be tested if available;
7. GPU isolation must remain PASS on the selected GPU;
8. game network remains OFF;
9. no dgVoodoo2 binaries are committed to the RetroCD repository or bundled into the RetroCD package.
