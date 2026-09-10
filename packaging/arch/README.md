# Arch / CachyOS packaging

This directory builds the Bottles RetroCD 0.4.0 package from a pinned release
candidate commit. The 0.4.0 runtime passed the pre-packaging target-machine and
CI gates; final release review then found and fixed an identity-only mismatch in
the final wrapper (`org.local.BottlesRetroCD` / `0.4.0-rc2` versus the stable
packaging identity).

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

The final 0.4.0 Arch/CachyOS candidate is `pkgrel=3`. It conflicts with and
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
set PKG (find . -maxdepth 1 -type f -name 'bottles-retrocd-0.4.0-3-*.pkg.tar.*' | head -n 1)
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

The full target-machine package acceptance completed successfully for
`0.4.0-2` on CachyOS on 2026-09-10:

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

Final release review then found that the final GUI wrapper inherited legacy
base constants `APP_ID=org.local.BottlesRetroCD`, `APP_NAME=Bottles Retro CD`
and `VERSION=0.4.0-rc2`. The final wrapper now overrides only those three
release-identity values to `io.github.Paolo86cripple.BottlesRetroCD`,
`Bottles RetroCD` and `0.4.0`; sandbox/device/runtime policy is unchanged.
Because package content changed, `pkgrel` was correctly incremented to 3 and
the package source pin moved to the identity-fix commit.

Before merge, rebuild/install `0.4.0-3` and perform the narrow reopened gate:
151/151 package tests, `pacman -Qkk` integrity, GUI title/version and effective
GTK application ID. The earlier security/Discworld/uninstall-preservation gates
do not need to be repeated unless this narrow check exposes an unrelated
regression.
