# Point 5 review record

Status: **PASS**

Review date: 2026-09-08

Branch reviewed: `hardening/retro-optical-boundary-v2`

Base branch: `main` at `216ab5978f23ecf4b403b521c321cf778b81c343`

## Scope

The review covered Point 5 (Retro Optical / CDEmu + libMirage hardening and lifecycle) plus regression checks for Points 1–4.

## Findings fixed during review

- Added an exact-policy Retro Optical **pre-launch** proof so a bad optical boundary blocks Bottles before game code starts.
- Retained the independent Retro Optical **post-launch** proof against the running jail.
- Removed the fragile global `subprocess.Popen` monkeypatch from the final launch path; process capture is scoped to the launch controller.
- Hardened GPU probe marker parsing against Bubblejail echoed-command contamination.
- Hardened lifecycle version comparison so Arch package versions such as `3.3.1-1.1` are matched to runtime `3.3.1` without accepting prefix collisions such as `3.3.10`.
- Hardened running-kernel VHBA path validation against substring-only kernel-name matches.
- Added automated tests for the safe updater control flow and made its PyGObject/CDEmu imports lazy enough for headless CI.
- Correctly detects CachyOS kernel-bundled VHBA (`kernel:linux-cachyos`) and does not suggest/install a duplicate DKMS provider.

## Target-machine acceptance

Target environment included CachyOS kernel `7.2.3-1-cachyos`, Bubblejail 0.10.4, Ryzen 7 9800X3D integrated graphics and Radeon RX 9070 XT discrete graphics.

Validated behaviours:

- no optical media: GPU pre/post PASS; Retro Optical pre/post PASS; VHBA hidden; CDEmu D-Bus blocked; `sr` hidden; `sg` hidden; `/mnt/cdemu` hidden;
- RO filesystem-only exposure: target-validated before the final preflight hardening; `/mnt/cdemu=RO`, raw nodes hidden;
- exact raw `/dev/srX`: target-validated;
- explicit advanced `/dev/sgX`: target-tested successfully;
- Discworld Noir live multidisc: one active `/dev/sr0`, RO mount bank, cache 3/3, live swaps successful, cache cleanup successful;
- integrated GPU launch: pre/post PASS;
- Radeon RX 9070 XT launch: pre/post PASS;
- `Espelli tutto`: target-tested successfully on RetroCD-managed media;
- lifecycle health check: PASS with `kernel:linux-cachyos`, CDEmu 3.3.1, libMirage 3.3.3, API 7.0;
- updater negative paths: rejects loaded media, prepares the expected `sudo pacman -Syu --needed cdemu-daemon libmirage cdemu-client` transaction, opens an interactive terminal helper, and allows cancellation without changing packages;
- GTK frontend remained open and stable after main-loop marshalling fix.

## Regression review of Points 1–4

- Persistent settings backend unchanged by Point 5; private permissions and corrupt-config fallback remain covered by unit tests.
- GPU policy unchanged apart from parser hardening; both target GPUs passed the final pre/post probes.
- Multidisc core backend and bridge were not rewritten by Point 5; live switching and cleanup passed again on target.
- Redump/TOSEC verifier and protection scanner were not rewritten by Point 5; the complete verifier/scanner test suite remained green, and prior target source-immutability validation remains applicable.

## Merge gate

The branch is eligible for merge to `main` only after the final branch CI for this review record is green. No force push is permitted.

Next roadmap item after merge: **dgVoodoo2 manager**, then **Arch/CachyOS packaging**.
