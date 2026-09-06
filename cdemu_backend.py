#!/usr/bin/env python3
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import gi

gi.require_version("GLib", "2.0")
gi.require_version("Gio", "2.0")
gi.require_version("GObject", "2.0")
from gi.repository import Gio, GLib, GObject


@dataclass(slots=True)
class DeviceState:
    index: int
    loaded: bool
    filenames: tuple[str, ...]
    sr_path: str
    sg_path: str
    dpm_emulation: bool
    tr_emulation: bool
    bad_sector_emulation: bool
    dvd_report_css: bool

    @property
    def title(self) -> str:
        media = Path(self.filenames[0]).name if self.loaded and self.filenames else "vuoto"
        sg = f" · {self.sg_path}" if self.sg_path else ""
        return f"Device #{self.index} · {self.sr_path or 'mapping…'}{sg} · {media}"


class CDEmuBackend:
    """Small D-Bus client for CDEmu daemon.

    The D-Bus object/interface names, signal handling model and method signatures
    are adapted from upstream gCDEmu 3.3.1 (GPL-2.0-or-later).
    """

    BUS_NAME = "net.sf.cdemu.CDEmuDaemon"
    OBJECT_PATH = "/Daemon"
    INTERFACE = "net.sf.cdemu.CDEmuDaemon"
    REQUIRED_INTERFACE_MAJOR = 7

    def __init__(self, use_system_bus: bool = False, autostart: bool = True):
        self.use_system_bus = use_system_bus
        self.autostart = autostart
        self.bus = None
        self.proxy = None
        self.signal_handler_id = None
        self.callbacks: list[Callable[[str, int | None], None]] = []
        self.connect()

    def connect(self) -> None:
        bus_type = Gio.BusType.SYSTEM if self.use_system_bus else Gio.BusType.SESSION
        self.bus = Gio.bus_get_sync(bus_type, None)
        self.proxy = Gio.DBusProxy.new_sync(
            self.bus,
            Gio.DBusProxyFlags.NONE,
            None,
            self.BUS_NAME,
            self.OBJECT_PATH,
            self.INTERFACE,
            None,
        )
        self.signal_handler_id = self.proxy.connect("g-signal", self._on_signal)
        if self.autostart:
            self.bus.call_sync(
                self.BUS_NAME,
                self.OBJECT_PATH,
                "org.freedesktop.DBus.Peer",
                "Ping",
                None,
                None,
                Gio.DBusCallFlags.NONE,
                5000,
                None,
            )
        version = self.interface_version()
        if version[0] != self.REQUIRED_INTERFACE_MAJOR:
            raise RuntimeError(
                f"Interfaccia CDEmu incompatibile: {version[0]}.{version[1]} "
                f"(attesa major {self.REQUIRED_INTERFACE_MAJOR})."
            )

    def close(self) -> None:
        if self.proxy is not None and self.signal_handler_id is not None:
            try:
                self.proxy.disconnect(self.signal_handler_id)
            except Exception:
                pass
        self.signal_handler_id = None
        self.proxy = None
        self.bus = None

    def subscribe(self, callback: Callable[[str, int | None], None]) -> None:
        self.callbacks.append(callback)

    def _on_signal(self, proxy, sender_name, signal_name, params):
        device: int | None = None
        try:
            if signal_name in {"DeviceStatusChanged", "DeviceMappingReady", "DeviceOptionChanged"}:
                device = int(params[0])
        except Exception:
            device = None
        if signal_name in {
            "DeviceStatusChanged",
            "DeviceMappingReady",
            "DeviceOptionChanged",
            "DeviceAdded",
            "DeviceRemoved",
        }:
            for callback in tuple(self.callbacks):
                try:
                    callback(signal_name, device)
                except Exception:
                    pass

    def daemon_version(self) -> str:
        return str(self.proxy.GetDaemonVersion())

    def library_version(self) -> str:
        return str(self.proxy.GetLibraryVersion())

    def interface_version(self) -> tuple[int, int]:
        value = self.proxy.GetDaemonInterfaceVersion2()
        return int(value[0]), int(value[1])

    def number_of_devices(self) -> int:
        return int(self.proxy.GetNumberOfDevices())

    def mapping(self, index: int) -> tuple[str, str]:
        sr, sg = self.proxy.DeviceGetMapping("(i)", index)
        return str(sr), str(sg)

    def status(self, index: int) -> tuple[bool, tuple[str, ...]]:
        loaded, filenames = self.proxy.DeviceGetStatus("(i)", index)
        return bool(loaded), tuple(str(x) for x in filenames)

    def get_option(self, index: int, name: str):
        return self.proxy.DeviceGetOption("(is)", index, name)

    def set_bool_option(self, index: int, name: str, enabled: bool) -> None:
        self.proxy.DeviceSetOption("(isv)", index, name, GLib.Variant("b", bool(enabled)))

    def device_state(self, index: int) -> DeviceState:
        loaded, filenames = self.status(index)
        sr, sg = self.mapping(index)
        return DeviceState(
            index=index,
            loaded=loaded,
            filenames=filenames,
            sr_path=sr,
            sg_path=sg,
            dpm_emulation=bool(self.get_option(index, "dpm-emulation")),
            tr_emulation=bool(self.get_option(index, "tr-emulation")),
            bad_sector_emulation=bool(self.get_option(index, "bad-sector-emulation")),
            dvd_report_css=bool(self.get_option(index, "dvd-report-css")),
        )

    def devices(self) -> list[DeviceState]:
        return [self.device_state(i) for i in range(self.number_of_devices())]

    def load(self, index: int, image: Path, parameters: dict | None = None) -> None:
        params = parameters or {}
        self.proxy.DeviceLoad("(iasa{sv})", index, [str(image)], params)

    def unload(self, index: int) -> None:
        self.proxy.DeviceUnload("(i)", index)

    def add_device(self) -> int:
        before = self.number_of_devices()
        self.proxy.AddDevice()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            current = self.number_of_devices()
            if current > before:
                return current - 1
            time.sleep(0.1)
        raise RuntimeError("CDEmu non ha creato il drive temporaneo entro 5 secondi.")

    def remove_last_device(self) -> None:
        self.proxy.RemoveDevice()

    def wait_mapping(self, index: int, timeout: float = 8.0) -> tuple[str, str]:
        deadline = time.monotonic() + timeout
        last = ("", "")
        while time.monotonic() < deadline:
            last = self.mapping(index)
            sr, sg = last
            if sr and Path(sr).exists():
                return sr, sg
            time.sleep(0.1)
        raise RuntimeError(f"Mapping CDEmu non pronto per device #{index}: {last}")

    def wait_loaded(self, index: int, expected: bool, timeout: float = 8.0) -> tuple[bool, tuple[str, ...]]:
        deadline = time.monotonic() + timeout
        last = self.status(index)
        while time.monotonic() < deadline:
            last = self.status(index)
            if last[0] is expected:
                return last
            time.sleep(0.1)
        raise RuntimeError(
            f"Stato CDEmu non aggiornato per device #{index}: loaded={last[0]}, atteso={expected}."
        )
