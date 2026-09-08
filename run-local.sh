#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

fail=0
for cmd in python3 cdemu bubblejail findmnt ip; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        printf 'Manca il comando richiesto: %s\n' "$cmd" >&2
        fail=1
    fi
done

if ! python3 - <<'PY' >/dev/null 2>&1
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gio', '2.0')
from gi.repository import Gtk, Gio
PY
then
    printf 'PyGObject/GTK4 non disponibile per questo Python.\n' >&2
    fail=1
fi

if [ "$fail" -ne 0 ]; then
    printf '\nPreflight fallito. Non è stato installato o modificato nulla.\n' >&2
    exit 1
fi

if ! command -v udisksctl >/dev/null 2>&1; then
    printf 'Nota: udisksctl non trovato; i test UDisks2 dovranno essere disattivati.\n' >&2
fi

exec python3 "$HERE/bottles-retro-cd-gui-final.py" "$@"
