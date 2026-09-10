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
set PKG (find . -maxdepth 1 -type f -name 'bottles-retrocd-0.4.0-1-*.pkg.tar.*' | head -n 1)
test -n "$PKG"; or begin; echo "Pacchetto non trovato"; exit 1; end

pacman -Qlp "$PKG"
pacman -Qip "$PKG"
```

Do not tag 0.4.0 until the package-installed acceptance and uninstall-preservation
tests have passed.
