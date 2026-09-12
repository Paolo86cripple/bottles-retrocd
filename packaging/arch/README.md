# Arch / CachyOS packaging

This directory builds the Bottles RetroCD **0.4.1-1** Arch/CachyOS package.

The package payload is pinned to an exact reviewed source commit rather than to a moving branch. For the final 0.4.1 candidate the payload source is:

```text
3c842c0c5f740a041c4f2de4edcdb899691ccbd2
```

That payload contains the validated 0.4.1 runtime hardening, the final pre-launch dconf/D-Bus guard and the aligned documentation installed under `/usr/share/doc/bottles-retrocd/`.

`PKGBUILD`, `.SRCINFO` and CI must always name the same payload commit. Changing that pin invalidates package-acceptance evidence from an earlier artifact and requires rebuilding/rechecking the exact new package before merge/release.

The package installs only application-owned files under `/usr`. It does not create, rewrite or remove the user's Bubblejail `Bottles` instance, private HOME, RetroCD configuration, archive, DAT catalog/cache or game prefixes.

## Dependency policy

Direct runtime dependencies are declared in `PKGBUILD`. `bottles` and `bubblejail` are AUR packages on stock Arch. CDEmu/libMirage are taken from the host distribution. RetroCD deliberately does not depend directly on a specific VHBA kernel-module package: `cdemu-daemon` and the distribution/kernel must provide a compatible effective VHBA provider, avoiding duplicate CachyOS kernel/DKMS infrastructure.

`cdemu-client` is not required. `sudo` is optional and is used only by the interactive Componenti update action. `lspci`/`pciutils` is diagnostic enrichment only.

The package intentionally declares:

```text
conflicts = bottles-retro-cd-gui
replaces  = bottles-retro-cd-gui
```

so the obsolete historical local package name does not coexist with the stable launcher.

## Build on the target system

Commands shown here are fish-compatible:

```fish
git fetch origin
git switch hardening/0.4.1-runtime-audit
git pull --ff-only
cd packaging/arch

makepkg --cleanbuild --syncdeps
```

If `bottles` or `bubblejail` are not already installed, install those AUR dependencies with the chosen AUR helper before running `makepkg`.

After a successful build, inspect the package before installation:

```fish
set PKG (find . -maxdepth 1 -type f -name 'bottles-retrocd-0.4.1-1-*.pkg.tar.*' | head -n 1)
test -n "$PKG"; or begin; echo "Pacchetto non trovato"; exit 1; end

pacman -Qlp "$PKG"
pacman -Qip "$PKG"
```

`.SRCINFO` is tracked alongside `PKGBUILD` and must be regenerated whenever package metadata or the source pin changes:

```fish
makepkg --printsrcinfo > .SRCINFO
```

## Final 0.4.1 artifact gate

The exact artifact built from payload commit `3c842c0c5f740a041c4f2de4edcdb899691ccbd2` is the remaining package acceptance target.

Required acceptance:

- clean `makepkg --cleanbuild --syncdeps` succeeds with the complete test suite;
- package metadata/file list are inspected and package-owned paths remain under the intended `/usr` locations;
- install/upgrade or reinstall of the exact `0.4.1-1` artifact succeeds;
- `pacman -Qkk bottles-retrocd` reports zero altered files;
- one installed-package normal launch still passes the static dconf guard plus existing GPU/Retro Optical proofs;
- removal deletes package-owned `/usr` payload only;
- RetroCD configuration, Bubblejail instance/private HOME, prefixes, archive and verifier state remain unchanged across uninstall/reinstall.

An earlier 0.4.1-1 candidate passed the preservation/integrity path with **65 package files / 0 altered files**, but the later pre-launch dconf guard and documentation alignment changed the payload source. That earlier artifact is useful regression evidence but is not the final merge/release artifact.

## Historical 0.4.0 baseline

The published 0.4.0 package remains `bottles-retrocd 0.4.0-3`. Its target acceptance passed with 151/151 tests, 53 files / 0 altered files, stable application identity, GPU/Retro Optical/Discworld/gamepad validation and uninstall preservation. The published 0.4.0 tag/package history is immutable and must not be rewritten while preparing 0.4.1.
