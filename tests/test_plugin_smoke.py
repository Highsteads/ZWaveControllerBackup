#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_plugin_smoke.py
# Description: Loads plugin.py against a stubbed Indigo and drives the three
#              operations end to end with the scripted stick standing in for the
#              port: backup writes an image and sidecar, restore refuses a wrong
#              image and writes a right one, verify compares, the stale nudge
#              fires once, menus refuse when busy, and the plugin never touches
#              a port while Z-Wave is on.
# Author:      CliveS & Claude Fable 5.1
# Date:        13-09-2026 12:40
# Version:     1.0.0

import importlib.util
import json
import logging
import os
import sys
import threading
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fake_stick import GEN5, SERVER_PLUGIN, FakeStick  # noqa: E402


# ── the smallest Indigo that will hold still ─────────────────────────

class FakeDevice:
    def __init__(self, dev_id, name, device_type="zwaveController", plugin_id="com.clives.indigoplugin.zwave-controller-backup",
                 protocol="zwave", address=""):
        self.id, self.name = dev_id, name
        self.deviceTypeId = device_type
        self.pluginId = plugin_id
        self.protocol = protocol
        self.address = address
        self.states = {}
        self.errorState = ""

    def updateStatesOnServer(self, items):
        for item in items:
            self.states[item["key"]] = item["value"]

    def setErrorStateOnServer(self, text):
        self.errorState = text


class FakeCollection(dict):
    subscribed = 0

    def add(self, dev):
        self[dev.id] = dev

    def __iter__(self):
        return iter(list(self.values()))

    def subscribeToChanges(self):
        FakeCollection.subscribed += 1


def build_indigo(install_folder, zwave_enabled):
    ind = types.ModuleType("indigo")
    ind.Dict = dict
    ind.devices = FakeCollection()
    ind.kProtocol = types.SimpleNamespace(ZWave="zwave", Plugin="plugin")
    ind.server = types.SimpleNamespace(getInstallFolderPath=lambda: install_folder, version="2025.2.0",
                                       log=lambda *a, **k: None)
    ind.zwave = types.SimpleNamespace(isEnabled=lambda: zwave_enabled["on"])

    class PluginBase:
        StopThread = type("StopThread", (Exception,), {})

        def __init__(self, pid, name, version, prefs):
            self.pluginId, self.pluginDisplayName = pid, name
            self.pluginVersion, self.pluginPrefs = version, dict(prefs)
            self.logger = logging.getLogger(f"zwcb.test.{id(self)}")
            self.logger.addHandler(logging.NullHandler())
            self.logger.setLevel(logging.DEBUG)
            self.stopThread = False

        def deviceCreated(self, dev):
            pass

        def deviceDeleted(self, dev):
            pass

        def deviceUpdated(self, a, b):
            pass

        def stopConcurrentThread(self):
            self.stopThread = True

    ind.PluginBase = PluginBase
    return ind


def load_plugin(tmp_path, zwave_enabled, folder=None):
    install = os.path.join(str(tmp_path), "Indigo 2025.2")
    prefs_dir = os.path.join(install, "Preferences", "Plugins")
    os.makedirs(prefs_dir, exist_ok=True)
    with open(os.path.join(prefs_dir, "com.perceptiveautomation.indigoplugin.zwave.indiPref"), "w") as fh:
        fh.write('<?xml version="1.0"?><Prefs type="dict">'
                 '<HomeE0BB7FA8_Node005 type="bool">true</HomeE0BB7FA8_Node005>'
                 '<interfacePort_serialConnType type="string">local</interfacePort_serialConnType>'
                 '<interfacePort_serialPortLocal type="string">/dev/cu.fake</interfacePort_serialPortLocal></Prefs>')
    ind = build_indigo(install, zwave_enabled)
    sys.modules["indigo"] = ind
    for name in ("plugin", "controller_image", "plugin_utils"):
        sys.modules.pop(name, None)
    cwd = os.getcwd()
    os.chdir(SERVER_PLUGIN)          # the plugin resolves its siblings via os.getcwd(), as Indigo sets it
    try:
        sys.path.insert(0, SERVER_PLUGIN)
        spec = importlib.util.spec_from_file_location("plugin", os.path.join(SERVER_PLUGIN, "plugin.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        os.chdir(cwd)
    prefs = {"backupFolder": folder or "", "portOverride": "", "waitMinutes": "1", "debugLogging": "false"}
    plugin = mod.Plugin("com.clives.indigoplugin.zwave-controller-backup", "Z-Wave Controller Backup", "1.0.0", prefs)
    return mod, plugin, ind


class LogSpy(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append((record.levelno, record.getMessage()))

    def messages(self, level=None):
        return [m for lv, m in self.records if level is None or lv == level]


def wire_stick(mod, plugin, stick):
    """Route the plugin's port opening at the scripted stick and make waits instant."""
    mod.ci.open_port = lambda path, tries=15, pause=1.5: stick
    mod.ci.port_holders = lambda port: []
    plugin._sleep = lambda s: None
    plugin._sleep_short = lambda s: None
    plugin._wait_for_replug = lambda port_path: None
    # In the stub nobody clicks Enable, so the half-hour wait for it is cut to nothing; a test
    # that wants the re-enabled state flips the stub on and calls _cue_reenable() itself.
    mod.REENABLE_WAIT_SECONDS = 0


def run_and_join(plugin, start_fn, *args):
    err = start_fn(*args)
    assert err in (None, (True, args[0] if args else None)) or err[0] is True, err
    plugin._worker.join(30)
    assert not plugin._worker.is_alive()
    return err


# ── tests ─────────────────────────────────────────────────────────────

def test_plugin_imports_starts_and_writes_the_folder_readme(tmp_path):
    zw = {"on": True}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    plugin.startup()
    assert os.path.isfile(os.path.join(plugin.backup_folder, "README.md"))
    assert plugin.backup_folder.endswith("Z-Wave Controller Backups")
    assert FakeCollection.subscribed >= 1
    assert plugin.wait_minutes == 1


def test_backup_end_to_end_writes_image_and_sidecar_and_states(tmp_path):
    zw = {"on": False}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    spy = LogSpy()
    plugin.logger.addHandler(spy)
    plugin.startup()
    dev = FakeDevice(101, "Z-Wave Controller")
    ind.devices.add(dev)
    plugin.deviceStartComm(dev)
    assert dev.states["backupStatus"] == "Never backed up"
    stick = FakeStick()
    wire_stick(mod, plugin, stick)
    run_and_join(plugin, plugin.menuBackup, {})
    images = mod.ci.list_images(plugin.backup_folder)
    assert len(images) == 1
    path, side = images[0]
    assert open(path, "rb").read() == bytes(stick.nvm)
    assert side["identity"]["homeId"] == "E0BB7FA8" and side["checks"]["readsIdentical"] is True
    assert side["pluginVersion"] == "1.0.0" and side["indigoVersion"] == "2025.2.0"
    assert dev.states["lastBackupOk"] is True
    assert dev.states["homeId"] == "E0BB7FA8"
    assert dev.states["controllerModel"] == "Aeotec Z-Stick Gen5"
    assert dev.states["softwareVersion"] == "Z-Wave 4.54 (SDK 6.51.10)"
    assert dev.states["nodeCount"] == len(GEN5["nodes"]) - 1
    # Z-Wave is still off in the stub, so the plugin must be asking for it back on.
    assert any("Switch Z-Wave back on" in m for m in spy.messages(logging.INFO))
    assert dev.states["actionRequired"] is True
    assert dev.states["backupStatus"] == "Action required: switch Z-Wave back on"
    assert plugin._busy is None
    # ... and once the user has clicked Enable, the device settles on the result.
    zw["on"] = True
    plugin._cue_reenable()
    assert dev.states["actionRequired"] is False
    assert dev.states["backupStatus"].startswith("Backed up") and dev.states["backupStatus"].endswith("current")
    # No read was attempted while Z-Wave was on: every request went to the stick only after the wait.
    assert stick.requests[0][0] in (mod.ci.F_GET_VERSION,)


def test_backup_waits_and_gives_up_if_zwave_stays_on(tmp_path, monkeypatch):
    zw = {"on": True}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    spy = LogSpy()
    plugin.logger.addHandler(spy)
    plugin.startup()
    stick = FakeStick()
    wire_stick(mod, plugin, stick)
    monkeypatch.setattr(mod, "REMINDER_SECONDS", (0,))
    clock = {"t": 0.0}
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock.__setitem__("t", clock["t"] + 30) or clock["t"])
    run_and_join(plugin, plugin.menuBackup, {})
    assert stick.requests == []                        # never touched the port
    assert any("cancelled" in m for m in spy.messages(logging.WARNING))
    assert mod.ci.list_images(plugin.backup_folder) == []


def test_menus_refuse_while_busy(tmp_path):
    zw = {"on": True}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    plugin.startup()
    release = threading.Event()
    plugin._run_backup = lambda: release.wait(5)
    assert plugin.menuBackup({})[0] is True
    ok, values, errors = plugin.menuBackup({})
    assert ok is False and "already running" in errors["showAlertText"]
    ok, values, errors = plugin.menuRestore({"imageFile": "", "confirmOverwrite": "true"})
    assert ok is False and "imageFile" in errors
    release.set()
    plugin._worker.join(5)
    assert plugin._busy is None


def test_restore_dialog_validation(tmp_path):
    zw = {"on": True}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    plugin.startup()
    img = os.path.join(plugin.backup_folder, "x.bin")
    open(img, "wb").write(b"\x00")
    ok, values, errors = plugin.menuRestore({"imageFile": img, "confirmOverwrite": "false"})
    assert ok is False and "confirmOverwrite" in errors and "imageFile" not in errors
    ok, values, errors = plugin.menuRestore({"imageFile": "", "confirmOverwrite": "true"})
    assert ok is False and "imageFile" in errors


def test_restore_refuses_wrong_software_and_writes_right_image(tmp_path):
    zw = {"on": False}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    spy = LogSpy()
    plugin.logger.addHandler(spy)
    plugin.startup()
    stick = FakeStick()
    wire_stick(mod, plugin, stick)
    run_and_join(plugin, plugin.menuBackup, {})
    path, side = mod.ci.list_images(plugin.backup_folder)[0]
    # 1) an image whose sidecar claims another software version is refused, and nothing is written
    wrong = os.path.join(plugin.backup_folder, "wrong.bin")
    open(wrong, "wb").write(open(path, "rb").read())
    bad = json.loads(open(mod.ci.sidecar_path_for(path)).read())
    bad["identity"]["libraryVersionString"] = "Z-Wave 6.07"
    bad["takenAt"] = "2020-01-01T00:00:00"
    json.dump(bad, open(mod.ci.sidecar_path_for(wrong), "w"))
    writes_before = stick.write_count
    run_and_join(plugin, plugin.menuRestore, {"imageFile": wrong, "confirmOverwrite": "true"})
    assert stick.write_count == writes_before
    assert any("Restore refused" in m and "memory layout" in m for m in spy.messages(logging.ERROR))
    # 2) the genuine image, after the stick's memory has been scribbled on, goes back and verifies
    stick.nvm[100:200] = b"\x00" * 100
    run_and_join(plugin, plugin.menuRestore, {"imageFile": path, "confirmOverwrite": "true"})
    assert stick.write_count > writes_before
    assert bytes(stick.nvm) == open(path, "rb").read()
    assert any("Restore verified" in m for m in spy.messages(logging.INFO))
    assert stick.requests[-1][0] != mod.ci.F_EXT_NVM_WRITE      # the read-back came after the writes
    assert any(f == mod.ci.F_SOFT_RESET for f, _ in stick.requests)


def test_restore_reports_a_read_back_that_differs(tmp_path):
    zw = {"on": False}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    spy = LogSpy()
    plugin.logger.addHandler(spy)
    plugin.startup()
    stick = FakeStick()
    wire_stick(mod, plugin, stick)
    run_and_join(plugin, plugin.menuBackup, {})
    path, side = mod.ci.list_images(plugin.backup_folder)[0]

    class Forgetful(FakeStick):
        """Accepts every write and keeps none of it."""
        def _respond(self, func, payload):
            if func == mod.ci.F_EXT_NVM_WRITE:
                return bytes([1])
            return super()._respond(func, payload)
    forget = Forgetful()
    forget.nvm[100:200] = b"\x00" * 100
    wire_stick(mod, plugin, forget)
    run_and_join(plugin, plugin.menuRestore, {"imageFile": path, "confirmOverwrite": "true"})
    assert any("did NOT hold" in m for m in spy.messages(logging.ERROR))


def test_verify_matches_then_notices_a_change(tmp_path):
    zw = {"on": False}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    spy = LogSpy()
    plugin.logger.addHandler(spy)
    plugin.startup()
    stick = FakeStick()
    wire_stick(mod, plugin, stick)
    run_and_join(plugin, plugin.menuBackup, {})
    plugin.menuVerify()
    plugin._worker.join(30)
    assert any("Verified" in m for m in spy.messages(logging.INFO))
    stick.nvm[5000] ^= 0xFF
    plugin.menuVerify()
    plugin._worker.join(30)
    assert any("differs from the last backup in 1 bytes" in m for m in spy.messages(logging.WARNING))


def test_stale_nudge_fires_once_for_a_new_zwave_device_and_clears_on_backup(tmp_path):
    zw = {"on": False}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    spy = LogSpy()
    plugin.logger.addHandler(spy)
    plugin.startup()
    dev = FakeDevice(101, "Z-Wave Controller")
    ind.devices.add(dev)
    plugin.deviceStartComm(dev)
    stick = FakeStick()
    wire_stick(mod, plugin, stick)
    # before any backup: nothing to be stale
    plugin.deviceCreated(FakeDevice(5, "New lamp", device_type="dimmer", plugin_id="", address="240"))
    assert not spy.messages(logging.WARNING)
    run_and_join(plugin, plugin.menuBackup, {})
    assert dev.states["networkChangedSinceBackup"] is False
    # a Z-Wave device on a node the image already holds is not a change
    plugin.deviceCreated(FakeDevice(6, "Re-synced switch", device_type="relay", plugin_id="", address="88"))
    assert dev.states["networkChangedSinceBackup"] is False
    # a genuinely new node is, once
    plugin.deviceCreated(FakeDevice(7, "New sensor", device_type="sensor", plugin_id="", address="240"))
    plugin.deviceCreated(FakeDevice(8, "Another", device_type="sensor", plugin_id="", address="241"))
    assert dev.states["networkChangedSinceBackup"] is True
    assert dev.states["backupStatus"] == "Network changed since backup"
    assert len([m for m in spy.messages(logging.WARNING) if "changed since the last backup" in m]) == 1
    # our own device and non-Z-Wave devices never count
    plugin.deviceDeleted(FakeDevice(9, "Own", plugin_id=plugin.pluginId))
    plugin.deviceDeleted(FakeDevice(10, "Zigbee thing", protocol="plugin", plugin_id="x", address="1"))
    assert len([m for m in spy.messages(logging.WARNING) if "changed since the last backup" in m]) == 1
    # a fresh backup clears it
    run_and_join(plugin, plugin.menuBackup, {})
    assert dev.states["networkChangedSinceBackup"] is False


def test_second_controller_device_is_refused(tmp_path):
    zw = {"on": True}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    a, b = FakeDevice(1, "A"), FakeDevice(2, "B")
    ind.devices.add(a)
    ind.devices.add(b)
    plugin.deviceStartComm(a)
    plugin.deviceStartComm(b)
    assert plugin._dev_id == 1 and b.errorState == "duplicate"


def test_prefs_validation_and_menu_prefill(tmp_path):
    zw = {"on": True}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    ok, values, errors = plugin.validatePrefsConfigUi({"waitMinutes": "0", "backupFolder": ""})
    assert ok is False and "waitMinutes" in errors
    ok, values = plugin.validatePrefsConfigUi({"waitMinutes": "5", "backupFolder": os.path.join(str(tmp_path), "elsewhere")})[:2]
    assert ok is True and os.path.isdir(os.path.join(str(tmp_path), "elsewhere"))
    assert plugin.get_menu_action_config_ui_values("menuBackup")["folderShown"] == plugin.backup_folder
    assert plugin.imageList()[0][1].startswith("No images")
    assert "imageFile" not in plugin.get_menu_action_config_ui_values("menuRestore")


def test_restore_dialog_preselects_the_newest_image(tmp_path):
    zw = {"on": False}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    plugin.startup()
    stick = FakeStick()
    wire_stick(mod, plugin, stick)
    run_and_join(plugin, plugin.menuBackup, {})
    older = os.path.join(plugin.backup_folder, "older.bin")
    open(older, "wb").write(b"\x00" * 8)
    json.dump({"takenAt": "2020-01-01T00:00:00", "identity": {}}, open(mod.ci.sidecar_path_for(older), "w"))
    newest = mod.ci.list_images(plugin.backup_folder)[0][0]
    assert newest != older
    assert plugin.get_menu_action_config_ui_values("menuRestore")["imageFile"] == newest


def test_700_series_is_refused_before_any_read(tmp_path):
    zw = {"on": False}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    spy = LogSpy()
    plugin.logger.addHandler(spy)
    plugin.startup()
    stick = FakeStick(profile=dict(GEN5, library=b"Z-Wave 7.19\x00" + bytes([1])))
    wire_stick(mod, plugin, stick)
    run_and_join(plugin, plugin.menuBackup, {})
    assert any("700 or 800 series" in m for m in spy.messages(logging.ERROR))
    assert not any(f == mod.ci.F_EXT_NVM_READ for f, _ in stick.requests)
    assert mod.ci.list_images(plugin.backup_folder) == []


@pytest.mark.parametrize("conn", ["netSocket", "netRfc2217"])
def test_network_attached_interface_is_refused(tmp_path, conn):
    zw = {"on": False}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    spy = LogSpy()
    plugin.logger.addHandler(spy)
    pref = os.path.join(plugin._zwave_prefs_path())
    open(pref, "w").write(f'<Prefs type="dict"><interfacePort_serialConnType type="string">{conn}</interfacePort_serialConnType>'
                          f'<interfacePort_serialPortLocal type="string">/dev/cu.fake</interfacePort_serialPortLocal></Prefs>')
    plugin.startup()
    stick = FakeStick()
    wire_stick(mod, plugin, stick)
    run_and_join(plugin, plugin.menuBackup, {})
    assert any("over the network" in m for m in spy.messages(logging.ERROR))
    assert stick.requests == []
