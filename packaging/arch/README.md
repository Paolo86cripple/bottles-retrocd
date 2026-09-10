# Arch / CachyOS packaging

This directory builds the Bottles RetroCD 0.4.0 package from the exact runtime
commit that passed the pre-packaging target-machine and CI gates.

The package installs only application-owned files under `/usr`. It does not
create, rewrite or remove the user's Bubblejail `Bottles` instance, private
HOME, RetroCD configuration, archive, DAT catalog/cache or game prefixes.

## Dependency policy

Direct runtime dependencies are declared in `PKGBUILD`. `bottles` and
`bubblejail` are AUR packages on stock Arch. CDEmu/libMirage are taken from the
host distribution. RetroCD deliberately does not depend directly on a specific
VHBA kernel-module package: `cdemu-daemon` and the distribution/kernel must
provide a compatible effective `VHBA-MODULE`, which avoids duplicating CachyOS'
kernel-provided VHBA infrastructure.

`cdemu-client` is not required. `sudo` is optional and is used only by the
interactive Componenti update action.

The final 0.4.0 Arch/CachyOS package is `pkgrel=2`. It conflicts with and
replaces the historical local package name `bottles-retro-cd-gui`, so an
upgrade does not leave two launchers installed.

## Build on the target system

Commands shown here are fish-compatible:

```fish
git switch packaging/arch-cachyos-0.4.0
git pull --ff-only
cd packaging/arch

makepkg --cleanbuild --syncdeps
```

If `bottles` or `bubblejail` are not already installed, install those AUR
dependencies with your chosen AUR helper before running `makepkg`.

After a successful build, inspect the package before installation:

```fish
set PKG (find . -maxdepth 1 -type f -name 'bottles-retrocd-0.4.0-2-*.pkg.tar.*' | head -n 1)
test -n "$PKG"; or begin; echo "Pacchetto non trovato"; exit 1; end

pacman -Qlp "$PKG"
pacman -Qip "$PKG"
```

`.SRCINFO` is tracked alongside `PKGBUILD` and must be regenerated whenever
package metadata changes:

```fish
makepkg --printsrcinfo > .SRCINFO
```

## 0.4.0 package acceptance

Target-machine package acceptance completed successfully on CachyOS on
2026-09-10:

- clean `makepkg` build completed with 151/151 tests passing;
- package metadata and file list were inspected before installation;
- package payload was limited to the expected `/usr` locations;
- installed package integrity reported 53 files and 0 altered files;
- Bubblejail test passed 17/17 with no failures or warnings;
- installed launch passed GPU pre/post isolation, Retro Optical pre/post,
  XWayland, network OFF and exact Xbox One S gamepad isolation;
- Discworld Noir launched through the installed package using the validated
  Retro Optical path;
- uninstall-preservation comparison showed configuration, Bubblejail state,
  prefixes and archive content unchanged;
- package was reinstalled afterward as `bottles-retrocd 0.4.0-2`.

With these gates complete, the packaging branch is eligible for final review,
merge approval and the 0.4.0 tag/release workflow.
