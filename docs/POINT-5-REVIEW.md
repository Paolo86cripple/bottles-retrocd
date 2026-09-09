# Point 5 review record

Status: **PASS**

Review date: 2026-09-08

Branch reviewed: `hardening/retro-optical-boundary-v2`

Base branch: `main` at `216ab5978f23ecf4b403b521c321cf778b81c343`

> Historical review record. Later 0.4.0 pre-packaging work added portable archive-root configuration, Wayland/XWayland selection and isolated Bottles preference persistence without changing the Point-5 optical trust boundary. See `REVIEW.md` and `docs/ROADMAP.md` for current release status.

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
- updater negative paths: rejects loaded media, prepares the expected full-system package transaction, opens an interactive terminal helper, and allows cancellation without changing packages;
- GTK frontend remained open and stable after main-loop marshalling fix.

## Regression review of Points 1–4

- Persistent settings backend remained compatible with private permissions and corrupt-config fallback.
- GPU policy remained fail-closed; both target GPUs passed final pre/post probes.
- Multidisc core/bridge remained intact; live switching and cleanup passed again on target.
- Redump/TOSEC verifier and protection scanner remained green and retained source-immutability guarantees.

## Merge gate at the time

The Point-5 branch was eligible for merge only after its branch CI and target-machine acceptance passed. That gate is complete.

Current work has moved to the 0.4.0 pre-packaging review and Arch/CachyOS packaging; legacy DirectX compatibility managers are post-0.4.0 work.
