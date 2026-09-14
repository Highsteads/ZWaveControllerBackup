#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_plugin_smoke.py
# Description: Loads plugin.py against a stubbed Indigo and drives the three
#              operations end to end with the scripted stick standing in for the
#              port: backup writes an image and sidecar, restore refuses a wrong
#              image and writes a right one, verify compares, the stale nudge
#              fires once, menus refuse when busy, and the plugin never touches
#              a port while Z-Wave is on, and Show Plugin Info describes the
#              controller from the newest image.
# Author:      CliveS & Claude Fable 5.1
# Date:        14-09-2026 16:30
# Version:     1.2.0

import importlib.util
import json
import logging
import os
import sys
import threading
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fake_stick import GEN5, SERVER_PLUGIN, STICK700, ZST39, FakeStick, FakeStick700  # noqa: E402


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
                                       apiVersion="3.8", log=lambda *a, **k: None)
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
    plugin = mod.Plugin("com.clives.indigoplugin.zwave-controller-backup", "Z-Wave Controller Backup", mod.PLUGIN_VERSION, prefs)
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


def test_backup_warns_only_when_the_home_id_is_unknown_to_indigo(tmp_path):
    zw = {"on": False}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    spy = LogSpy()
    plugin.logger.addHandler(spy)
    plugin.startup()
    wire_stick(mod, plugin, FakeStick())                       # Home ID E0BB7FA8, which the stub prefs know
    run_and_join(plugin, plugin.menuBackup, {})
    assert not any("Home ID" in m for m in spy.messages(logging.WARNING))
    wire_stick(mod, plugin, FakeStick700())                    # E2DAD17B, which they do not
    run_and_join(plugin, plugin.menuBackup, {})
    assert any("only know E0BB7FA8" in m for m in spy.messages(logging.WARNING))


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
    assert side["pluginVersion"] == mod.PLUGIN_VERSION and side["indigoVersion"] == "2025.2.0"
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
    # quotes around a pasted path are dropped, and a relative path is refused rather than landing in the bundle
    quoted = "'" + os.path.join(str(tmp_path), "quoted") + "'"
    ok, values = plugin.validatePrefsConfigUi({"waitMinutes": "5", "backupFolder": quoted})[:2]
    assert ok is True and values["backupFolder"] == os.path.join(str(tmp_path), "quoted") and os.path.isdir(values["backupFolder"])
    ok, values, errors = plugin.validatePrefsConfigUi({"waitMinutes": "5", "backupFolder": "relative/folder"})
    assert ok is False and "backupFolder" in errors and not os.path.exists("relative/folder")
    plugin._read_prefs({"backupFolder": "'relative'", "waitMinutes": "5"})
    assert plugin.backup_folder == plugin._default_folder()
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


def test_unrecognised_generation_is_refused_before_any_read(tmp_path):
    zw = {"on": False}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    spy = LogSpy()
    plugin.logger.addHandler(spy)
    plugin.startup()
    stick = FakeStick(profile=dict(GEN5, library=b"Z-Wave\x00" + bytes([1])))     # no version at all
    wire_stick(mod, plugin, stick)
    run_and_join(plugin, plugin.menuBackup, {})
    assert any("does not recognise" in m for m in spy.messages(logging.ERROR))
    assert not any(f in (mod.ci.F_EXT_NVM_READ, mod.ci.F_NVM_OPERATIONS, mod.ci.F_EXT_NVM_OPERATIONS) for f, _ in stick.requests)
    assert mod.ci.list_images(plugin.backup_folder) == []


@pytest.mark.parametrize("profile,func,size", [(ZST39, 0x3D, 40960), (STICK700, 0x2E, 49152)])
def test_700_series_backup_end_to_end(tmp_path, profile, func, size):
    zw = {"on": False}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    spy = LogSpy()
    plugin.logger.addHandler(spy)
    plugin.startup()
    stick = FakeStick700(profile=profile)
    wire_stick(mod, plugin, stick)
    before = bytes(stick.nvm)
    run_and_join(plugin, plugin.menuBackup, {})
    path, side = mod.ci.list_images(plugin.backup_folder)[0]
    assert open(path, "rb").read() == before
    assert side["nvm"]["sizeBytes"] == size and side["nvm"]["function"] == f"0x{func:02X}"
    assert side["identity"]["homeId"] == profile["homeId"].hex().upper()
    # radio off and watchdog stopped before the first NVM op, reset on the way out, radio back on
    funcs = [f for f, _ in stick.requests]
    assert funcs.index(mod.ci.F_SET_RF_RECEIVE_MODE) < funcs.index(func)
    assert funcs.index(mod.ci.F_STOP_WATCHDOG) < funcs.index(func)
    assert funcs[-1] == mod.ci.F_SOFT_RESET and stick.resets == 1 and stick.radio_on
    assert not any(f in (mod.ci.F_NVM_GET_ID, mod.ci.F_EXT_NVM_READ) for f in funcs)      # no 500-series calls
    assert any("Backup complete" in m for m in spy.messages(logging.INFO))
    assert any(f"({700 if func == 0x2E else 800} series)" in m for m in spy.messages(logging.INFO))
    st = plugin._shadow
    assert st["softwareVersion"].startswith("Z-Wave 7.") and st["homeId"] == side["identity"]["homeId"]


def test_700_series_restore_end_to_end_without_a_replug(tmp_path):
    zw = {"on": False}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    spy = LogSpy()
    plugin.logger.addHandler(spy)
    plugin.startup()
    stick = FakeStick700()
    wire_stick(mod, plugin, stick)
    replug_calls = []
    plugin._wait_for_replug = lambda port_path: replug_calls.append(port_path)
    run_and_join(plugin, plugin.menuBackup, {})
    path, side = mod.ci.list_images(plugin.backup_folder)[0]
    image = open(path, "rb").read()
    # scribble on the stick so the restore has work to do
    stick.nvm[100:2000] = b"\x00" * 1900
    writes_before = stick.write_count
    run_and_join(plugin, plugin.menuRestore, {"imageFile": path, "confirmOverwrite": "true"})
    assert stick.write_count > writes_before
    assert replug_calls == []                                          # the reset is the step, not an unplug
    assert bytes(stick.nvm[100:2000]) == image[100:2000]               # the scribble is gone
    d = mod.ci.compare_images_700(image, bytes(stick.nvm), 64)         # only housekeeping + tail may differ
    assert d["unexplainedBytes"] == 0
    assert any("Restore verified" in m for m in spy.messages(logging.INFO))
    assert any("end of file" in m and "did not write them" in m for m in spy.messages(logging.INFO))
    assert stick.resets == 3 and not stick.hung and stick.radio_on   # backup 1, restore 2: after the write and on the way out
    assert plugin._shadow["lastResult"].startswith("restore ok")


def test_700_series_restore_notices_a_write_that_did_not_take(tmp_path):
    zw = {"on": False}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    spy = LogSpy()
    plugin.logger.addHandler(spy)
    plugin.startup()
    stick = FakeStick700()
    wire_stick(mod, plugin, stick)
    run_and_join(plugin, plugin.menuBackup, {})
    path, side = mod.ci.list_images(plugin.backup_folder)[0]

    class Forgetful(FakeStick700):
        """Says OK to every write and keeps none of it."""
        def _nvm_op(self, func, payload):
            if payload[0] == mod.ci.NVM_OP_WRITE and self.nvm_open:
                w = 4 if func == mod.ci.F_EXT_NVM_OPERATIONS else 2
                return bytes([0, 0]) + payload[2:2 + w]
            return super()._nvm_op(func, payload)
    forget = Forgetful()
    forget.nvm[100:2000] = b"\x00" * 1900
    wire_stick(mod, plugin, forget)
    run_and_join(plugin, plugin.menuRestore, {"imageFile": path, "confirmOverwrite": "true"})
    assert any("did NOT hold" in m and "not housekeeping" in m for m in spy.messages(logging.ERROR))
    assert plugin._shadow["lastResult"].startswith("restore failed")


def test_700_series_restore_notices_a_node_table_that_differs(tmp_path):
    zw = {"on": False}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    spy = LogSpy()
    plugin.logger.addHandler(spy)
    plugin.startup()
    stick = FakeStick700()
    wire_stick(mod, plugin, stick)
    run_and_join(plugin, plugin.menuBackup, {})
    path, side = mod.ci.list_images(plugin.backup_folder)[0]
    stick.profile["nodes"] = ZST39["nodes"] + [40]      # the stick keeps reporting a node the image lacks
    run_and_join(plugin, plugin.menuRestore, {"imageFile": path, "confirmOverwrite": "true"})
    assert any("did NOT hold" in m and "lists 11 nodes where the image has 10" in m for m in spy.messages(logging.ERROR))


def test_700_series_verify_tolerates_housekeeping_and_reports_real_change(tmp_path):
    zw = {"on": False}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    spy = LogSpy()
    plugin.logger.addHandler(spy)
    plugin.startup()
    stick = FakeStick700()
    wire_stick(mod, plugin, stick)
    run_and_join(plugin, plugin.menuBackup, {})
    # the reset at the end of the backup already appended housekeeping into erased space
    run_and_join(plugin, plugin.menuVerify)
    assert any("Verified" in m and "added in free space" in m for m in spy.messages(logging.INFO))
    stick.profile["nodes"] = ZST39["nodes"] + [40]      # a node appeared, though every byte of it landed in free space
    run_and_join(plugin, plugin.menuVerify)
    assert any("lists 11 nodes where the last backup has 10" in m for m in spy.messages(logging.WARNING))
    assert plugin._shadow["networkChangedSinceBackup"] is True
    stick.profile["nodes"] = ZST39["nodes"]
    plugin._network_flag = False
    stick.nvm[200:210] = b"\x00" * 10                   # a real change to a node file
    run_and_join(plugin, plugin.menuVerify)
    assert any("differs from the last backup" in m for m in spy.messages(logging.WARNING))


def test_700_series_session_is_closed_with_a_reset_even_when_the_read_fails(tmp_path):
    zw = {"on": False}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    spy = LogSpy()
    plugin.logger.addHandler(spy)
    plugin.startup()

    class Broken(FakeStick700):
        def _nvm_op(self, func, payload):
            if payload[0] == mod.ci.NVM_OP_READ and self.nvm_open:
                return bytes([0x03, 0])                  # operation interference, every time
            return super()._nvm_op(func, payload)
    stick = Broken()
    wire_stick(mod, plugin, stick)
    run_and_join(plugin, plugin.menuBackup, {})
    assert any("Backup failed" in m and "interference" in m for m in spy.messages(logging.ERROR))
    assert stick.resets == 1 and stick.radio_on             # never left with the radio off
    assert mod.ci.list_images(plugin.backup_folder) == []


def test_16_bit_node_id_mode_does_not_confuse_the_backup(tmp_path):
    zw = {"on": False}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    plugin.startup()
    stick = FakeStick700(node_id_bits=16)
    wire_stick(mod, plugin, stick)
    run_and_join(plugin, plugin.menuBackup, {})
    path, side = mod.ci.list_images(plugin.backup_folder)[0]
    assert side["identity"]["ownNodeId"] == 1 and side["identity"]["sucNodeId"] == 1
    assert plugin._shadow["nodeCount"] == len(ZST39["nodes"]) - 1


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


def test_restore_explains_a_refused_tail_in_plain_words(tmp_path):
    zw = {"on": False}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    spy = LogSpy()
    plugin.logger.addHandler(spy)
    plugin.startup()
    stick = FakeStick(refuse_tail=16)
    wire_stick(mod, plugin, stick)
    run_and_join(plugin, plugin.menuBackup, {})
    path, side = mod.ci.list_images(plugin.backup_folder)[0]
    run_and_join(plugin, plugin.menuRestore, {"imageFile": path, "confirmOverwrite": "true"})
    lines = [m for m in spy.messages(logging.INFO) if "would not accept a write" in m]
    assert len(lines) == 1
    assert "the last 16 bytes of its memory" in lines[0]
    assert "exactly what the image holds" in lines[0]
    assert "expected, not a fault" in lines[0]
    assert not any("refused" in m for m in spy.messages(logging.ERROR))
    assert any("Restore verified" in m for m in spy.messages(logging.INFO))


def banner_lines(ind):
    """Collect what the banner actually writes to the event log."""
    lines = []
    ind.server.log = lambda *a, **k: lines.append(str(a[0]) if a else "")
    return lines


def test_show_plugin_info_describes_the_controller_after_a_backup(tmp_path):
    zw = {"on": False}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    plugin.startup()
    stick = FakeStick()
    wire_stick(mod, plugin, stick)
    run_and_join(plugin, plugin.menuBackup, {})
    rows = dict(plugin._controller_extras())
    assert rows["Controller:"] == "Aeotec Z-Stick Gen5, Home ID E0BB7FA8"
    assert rows["Software:"] == "Z-Wave 4.54 (SDK 6.51.10)"
    assert rows["Nodes in image:"] == str(len(GEN5["nodes"]) - 1)
    assert rows["Image file:"].endswith(".bin") and os.sep not in rows["Image file:"]
    assert rows["Network changed:"].startswith("no,")
    # the banner's label column is 20 wide and its lines are ASCII only
    assert all(len(label) <= 20 for label, _ in plugin._controller_extras())
    assert all(str(v).isascii() for v in rows.values())
    # ... and all of it reaches the event log when the menu item is pressed
    lines = banner_lines(ind)
    plugin.showPluginInfo()
    blob = "\n".join(lines)
    for wanted in ("Aeotec Z-Stick Gen5", "E0BB7FA8", "Nodes in image:", "Network changed:", "Busy with:"):
        assert wanted in blob, wanted


def test_show_plugin_info_admits_it_knows_nothing_before_the_first_backup(tmp_path):
    zw = {"on": True}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    plugin.startup()
    rows = dict(plugin._controller_extras())
    assert rows["Controller:"] == "unknown until the first backup"
    assert rows["Last backup:"] == "never"
    assert "Software:" not in rows          # nothing invented from an image that does not exist
    lines = banner_lines(ind)
    plugin.showPluginInfo()
    assert any("unknown until the first backup" in ln for ln in lines)


def test_show_plugin_info_reports_a_network_that_has_moved_since_the_backup(tmp_path):
    zw = {"on": False}
    mod, plugin, ind = load_plugin(tmp_path, zw)
    plugin.startup()
    stick = FakeStick()
    wire_stick(mod, plugin, stick)
    run_and_join(plugin, plugin.menuBackup, {})
    assert dict(plugin._controller_extras())["Network changed:"].startswith("no,")
    plugin.deviceCreated(FakeDevice(7, "New sensor", device_type="sensor", plugin_id="", address="240"))
    assert dict(plugin._controller_extras())["Network changed:"].startswith("yes,")
