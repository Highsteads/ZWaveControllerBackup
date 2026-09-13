#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin.py
# Description: Z-Wave Controller Backup. Takes a complete, verified image of a
#              500-series Z-Wave USB controller's memory (Home ID, node table,
#              routes) and can write it back. Indigo has to let go of the stick
#              while that happens, so the plugin waits for the user to switch
#              Z-Wave off, does the job, and says when to switch it back on.
# Author:      CliveS & Claude Fable 5.1
# Date:        13-09-2026 17:45
# Version:     1.0.2

try:
    import indigo
except ImportError:
    pass

import json
import logging
import os as _os
import sys as _sys
import threading
import time

_sys.path.insert(0, _os.getcwd())   # plugin_utils.py + controller_image.py are bundled here
try:
    from plugin_utils import as_bool, install_timestamp_filter, log_startup_banner
except ImportError:
    log_startup_banner = None
    install_timestamp_filter = None

    def as_bool(value, default=False):
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "yes", "on") if value is not None else default

import controller_image as ci

# ============================================================
# Constants
# ============================================================

PLUGIN_ID = "com.clives.indigoplugin.zwave-controller-backup"
PLUGIN_VERSION = "1.0.2"
DEVICE_TYPE = "zwaveController"
DEFAULT_FOLDER_NAME = "Z-Wave Controller Backups"
POLL_SECONDS = 2
REENABLE_WAIT_SECONDS = 30 * 60
REPLUG_WAIT_SECONDS = 5 * 60
PORT_FREE_WAIT_SECONDS = 30
SETTLE_SECONDS = 2
REMINDER_SECONDS = (180, 360)

FOLDER_README = """# Z-Wave Controller Backups

Each `.bin` here is a complete copy of a Z-Wave USB controller's memory: its Home ID, the
list of devices it knows, and the routes it uses to reach them. The `.json` beside it says
which controller it came from and when.

Restore from Indigo: Plugins > Z-Wave Controller Backup > Restore Controller... and follow
the Event Log. An image only goes back onto the same model running the same software
version; the plugin refuses anything else, because the memory layout differs between
versions.

Fallback without the plugin: the zwave-js library's `controller.restoreNVMRaw()` writes the
same bytes back (never `restoreNVM()`, which tries to convert). See mat's write-up on the
Indigo forum, topic 29135, for a ready-made script.

Take a fresh copy whenever a device is added to or removed from the network.
"""


# ============================================================
# Plugin
# ============================================================

class Plugin(indigo.PluginBase):

    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        super().__init__(pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
        if install_timestamp_filter:
            install_timestamp_filter(self, True)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._busy = None
        self._worker = None
        self._dev_id = None
        self._last = None            # newest sidecar dict, or None
        self._last_path = None       # its image path
        self._network_flag = False
        self._final_status = None
        self._shadow = {}            # last states written, for when no device exists yet
        self._read_prefs(pluginPrefs)

    # --------------------------------------------------------
    # Preferences
    # --------------------------------------------------------

    def _read_prefs(self, prefs):
        folder = (prefs.get("backupFolder") or "").strip()
        self.backup_folder = folder or self._default_folder()
        self.port_override = (prefs.get("portOverride") or "").strip()
        try:
            minutes = int(str(prefs.get("waitMinutes", 10)).strip() or 10)
        except (ValueError, TypeError):
            minutes = 10
        self.wait_minutes = max(1, min(60, minutes))
        self.debug = as_bool(prefs.get("debugLogging", False))
        handler = getattr(self, "indigo_log_handler", None)
        if handler is not None:
            handler.setLevel(logging.DEBUG if self.debug else logging.INFO)

    @staticmethod
    def _default_folder():
        try:
            base = _os.path.dirname(indigo.server.getInstallFolderPath())
        except Exception:
            base = _os.path.expanduser("~")
        return _os.path.join(base, DEFAULT_FOLDER_NAME)

    @staticmethod
    def _zwave_prefs_path():
        try:
            return _os.path.join(indigo.server.getInstallFolderPath(), "Preferences", "Plugins", ci.ZWAVE_PREFS_FILE)
        except Exception:
            return ""

    def validatePrefsConfigUi(self, valuesDict):
        errors = self._dict()
        try:
            minutes = int(str(valuesDict.get("waitMinutes", "10")).strip() or 10)
            if not 1 <= minutes <= 60:
                raise ValueError
        except (ValueError, TypeError):
            errors["waitMinutes"] = "Whole minutes between 1 and 60."
        folder = (valuesDict.get("backupFolder") or "").strip()
        if folder:
            try:
                _os.makedirs(folder, exist_ok=True)
            except OSError as e:
                errors["backupFolder"] = f"Cannot create that folder: {e}"
        if len(errors):
            return (False, valuesDict, errors)
        return (True, valuesDict)

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            self._read_prefs(valuesDict)
            self._ensure_folder()

    # --------------------------------------------------------
    # Lifecycle
    # --------------------------------------------------------

    def startup(self):
        try:
            indigo.devices.subscribeToChanges()
        except Exception as e:
            self.logger.warning(f"Could not subscribe to device changes, so the stale-backup nudge is off: {e}")
        self._ensure_folder()
        self._load_newest()
        last = self._last["takenAt"][:16].replace("T", " ") if self._last else "never"
        self.logger.info(f"Ready. Images go to {self.backup_folder}; last backup {last}.")

    def shutdown(self):
        self._stop.set()
        worker = self._worker
        if worker and worker.is_alive():
            worker.join(2.0)

    def stopConcurrentThread(self):
        super().stopConcurrentThread()
        self._stop.set()

    # --------------------------------------------------------
    # Device lifecycle
    # --------------------------------------------------------

    def deviceStartComm(self, dev):
        if dev.deviceTypeId != DEVICE_TYPE:
            return
        if self._dev_id and self._dev_id != dev.id:
            self.logger.error(f"'{dev.name}': only one Z-Wave Controller device is needed and one already exists. Delete this one.")
            try:
                dev.setErrorStateOnServer("duplicate")
            except Exception:
                pass
            return
        self._dev_id = dev.id
        self._refresh_device_states()

    def deviceStopComm(self, dev):
        if dev.id == self._dev_id:
            self._dev_id = None

    def deviceCreated(self, dev):
        super().deviceCreated(dev)
        self._maybe_network_change(dev, "added")

    def deviceDeleted(self, dev):
        super().deviceDeleted(dev)
        self._maybe_network_change(dev, "removed")

    def deviceUpdated(self, orig_dev, new_dev):
        super().deviceUpdated(orig_dev, new_dev)

    def _maybe_network_change(self, dev, what):
        """The stale nudge. A Z-Wave device appearing or vanishing in Indigo means the
        controller very probably changed too. Approximate on purpose: over-warning costs a
        glance at the log, under-warning costs a stale image."""
        try:
            if getattr(dev, "pluginId", "") == self.pluginId:
                return
            if getattr(dev, "protocol", None) != indigo.kProtocol.ZWave:
                return
            node = self._node_of(dev)
            if what == "added" and self._last and node in set(self._last["identity"].get("nodeIds", [])):
                return      # a device re-defined onto a node the image already holds
            if not self._last:
                self.logger.debug(f"Z-Wave device '{dev.name}' {what}; no backup exists yet to be stale.")
                return
            if self._network_flag:
                return
            self._network_flag = True
            when = self._last["takenAt"][:16].replace("T", " ")
            self.logger.warning(
                f"Z-Wave device '{dev.name}' was {what}, so the controller has changed since the last backup ({when}). "
                f"Back it up again when convenient: Plugins > {self.pluginDisplayName} > Back Up Controller Now.")
            self._set(networkChangedSinceBackup=True, backupStatus="Network changed since backup")
        except Exception as e:
            self.logger.debug(f"stale-nudge check skipped: {e}")

    @staticmethod
    def _node_of(dev):
        try:
            return int(str(dev.address).strip())
        except (ValueError, TypeError, AttributeError):
            return None

    def _zwave_nodes_in_indigo(self):
        nodes = set()
        try:
            for dev in indigo.devices:
                if getattr(dev, "protocol", None) == indigo.kProtocol.ZWave:
                    node = self._node_of(dev)
                    if node:
                        nodes.add(node)
        except Exception as e:
            self.logger.debug(f"could not list Z-Wave devices: {e}")
        return nodes

    # --------------------------------------------------------
    # Device states
    # --------------------------------------------------------

    def _dict(self):
        try:
            return indigo.Dict()
        except Exception:
            return {}

    def _set(self, **states):
        self._shadow.update(states)
        if not self._dev_id:
            return
        try:
            dev = indigo.devices[self._dev_id]
            dev.updateStatesOnServer([{"key": k, "value": v} for k, v in states.items()])
        except Exception as e:
            self.logger.debug(f"could not update device states: {e}")

    @staticmethod
    def _identity_states(ident):
        """The device states that describe the controller itself."""
        known = set(ident.get("nodeIds", []))
        return dict(
            homeId=ident.get("homeId", ""), controllerModel=ident.get("modelName", ""),
            softwareVersion=ci.software_description(ident),
            nodeCount=max(0, len(known) - (1 if ident.get("ownNodeId") in known else 0)),
            nodeIds=",".join(str(n) for n in sorted(known)),
            isPrimary=bool(ident.get("initIsPrimary", False)), isSUC=bool(ident.get("isSUC", False)),
        )

    def _network_has_changed(self):
        """True when Indigo holds a Z-Wave node the newest image does not, or the nudge has fired.
        Read-only: the latch itself is set by _maybe_network_change and _refresh_device_states."""
        if not self._last:
            return False
        known = set(self._last.get("identity", {}).get("nodeIds", []))
        return bool(self._zwave_nodes_in_indigo() - known) or self._network_flag

    def _controller_extras(self):
        """What Show Plugin Info says about the controller itself. Taken from the newest image,
        because the stick can only be read with Z-Wave off and this menu item runs with it on."""
        if not self._last:
            return [("Controller:", "unknown until the first backup"), ("Last backup:", "never")]
        st = self._identity_states(self._last.get("identity", {}))
        return [
            ("Controller:", f"{st['controllerModel'] or 'unknown model'}, Home ID {st['homeId'] or '?'}"),
            ("Software:", st["softwareVersion"] or "?"),
            ("Nodes in image:", str(st["nodeCount"])),
            ("Last backup:", self._last["takenAt"][:16].replace("T", " ")),
            ("Image file:", _os.path.basename(self._last_path) if self._last_path else "?"),
            ("Network changed:", "yes, a Z-Wave device was added or removed" if self._network_has_changed()
             else "no, the last backup is current"),
        ]

    def _refresh_device_states(self):
        """Everything the device shows, derived from the newest sidecar on disk."""
        if not self._last:
            self._set(backupStatus="Never backed up", actionRequired=False, networkChangedSinceBackup=False,
                      lastBackupOk=False, lastBackupAt="", lastBackupFile="", lastResult="no backup yet")
            return
        ident = self._last.get("identity", {})
        changed = self._network_has_changed()
        self._network_flag = changed
        when = self._last["takenAt"][:16].replace("T", " ")
        status = "Network changed since backup" if changed else f"Backed up {self._pretty(self._last['takenAt'])}, current"
        self._set(
            backupStatus=status, actionRequired=False, networkChangedSinceBackup=changed,
            lastBackupOk=True, lastBackupAt=when, lastBackupFile=self._last_path or "",
            lastResult=self._shadow.get("lastResult", "backup on file"),
            **self._identity_states(ident),
        )

    @staticmethod
    def _pretty(iso):
        try:
            import datetime as _dt
            t = _dt.datetime.fromisoformat(iso)
            return f"{t.day} {t.strftime('%b %H:%M')}"
        except Exception:
            return iso

    # --------------------------------------------------------
    # Folder + sidecars
    # --------------------------------------------------------

    def _ensure_folder(self):
        try:
            _os.makedirs(self.backup_folder, exist_ok=True)
            readme = _os.path.join(self.backup_folder, "README.md")
            if not _os.path.exists(readme):
                with open(readme, "w", encoding="utf-8") as fh:
                    fh.write(FOLDER_README)
        except OSError as e:
            self.logger.error(f"Cannot use the backup folder {self.backup_folder}: {e}")

    def _load_newest(self):
        images = ci.list_images(self.backup_folder)
        if images:
            self._last_path, self._last = images[0]
        else:
            self._last_path, self._last = None, None

    def imageList(self, filter="", valuesDict=None, typeId="", targetId=0):
        out = []
        for path, side in ci.list_images(self.backup_folder):
            ident = side.get("identity", {})
            label = f"{self._pretty(side.get('takenAt', ''))}  {ident.get('modelName', '?')}  Home ID {ident.get('homeId', '?')}"
            out.append((path, label))
        if not out:
            out.append(("", "No images in the backup folder yet"))
        return out

    def get_menu_action_config_ui_values(self, menu_id):
        values = self._dict()
        if menu_id == "menuBackup":
            values["folderShown"] = self.backup_folder
        elif menu_id == "menuRestore":
            images = ci.list_images(self.backup_folder)
            if images:
                values["imageFile"] = images[0][0]      # newest first: the usual restore
        return values

    # --------------------------------------------------------
    # Menu callbacks
    # --------------------------------------------------------

    def _alert(self, message):
        errors = self._dict()
        errors["showAlertText"] = message
        return errors

    def menuBackup(self, valuesDict=None, typeId=""):
        err = self._start("backup", self._run_backup)
        if err:
            return (False, valuesDict, self._alert(err))
        return (True, valuesDict)

    def menuRestore(self, valuesDict=None, typeId=""):
        valuesDict = valuesDict if valuesDict is not None else {}
        errors = self._dict()
        path = (valuesDict.get("imageFile") or "").strip()
        if not path or not _os.path.isfile(path):
            errors["imageFile"] = "Choose an image."
        if not as_bool(valuesDict.get("confirmOverwrite", False)):
            errors["confirmOverwrite"] = "Tick to confirm the controller's memory may be overwritten."
        if len(errors):
            return (False, valuesDict, errors)
        replacement = as_bool(valuesDict.get("replacementStick", False))
        err = self._start("restore", self._run_restore, path, replacement)
        if err:
            return (False, valuesDict, self._alert(err))
        return (True, valuesDict)

    def menuVerify(self, valuesDict=None, typeId=""):
        err = self._start("verify", self._run_verify)
        if err:
            self.logger.warning(err)

    def showPluginInfo(self, valuesDict=None, typeId=None):
        port, conn, _home = ci.zwave_port_from_prefs(self._zwave_prefs_path())
        extras = [
            ("Backup folder:", self.backup_folder),
            ("Serial port:", self.port_override or port or "not found in Indigo's Z-Wave settings"),
            ("Connection:", conn or "?"),
        ]
        extras.extend(self._controller_extras())
        extras.append(("Busy with:", self._busy or "nothing"))
        if log_startup_banner:
            log_startup_banner(self.pluginId, self.pluginDisplayName, self.pluginVersion, extras=extras)
        else:
            indigo.server.log(f"{self.pluginDisplayName} v{self.pluginVersion}")

    # --------------------------------------------------------
    # Worker plumbing
    # --------------------------------------------------------

    def _start(self, name, fn, *args):
        """Start `fn` on a worker thread. Returns an error message if something else is running."""
        with self._lock:
            if self._busy:
                return f"A {self._busy} is already running. Wait for the Event Log to say it has finished."
            self._busy = name
            self._stop.clear()
            self._worker = threading.Thread(target=self._guarded, args=(name, fn, args), name=f"zwcb-{name}", daemon=True)
            self._worker.start()
        return None

    def _guarded(self, name, fn, args):
        try:
            fn(*args)
        except Exception as e:
            self.logger.error(f"{name.capitalize()} failed: {e}")
            self.logger.debug("traceback", exc_info=True)
            self._final_status = f"{name.capitalize()} failed"
            self._set(lastResult=f"{name} failed: {e}")
        finally:
            try:
                self._cue_reenable()
            finally:
                with self._lock:
                    self._busy = None

    def _zwave_on(self):
        try:
            return bool(indigo.zwave.isEnabled())
        except Exception:
            return True

    def _sleep(self, seconds):
        self._stop.wait(seconds)

    def _wait_for_zwave_off(self, name):
        """True once Indigo has let go of the stick, False on timeout or shutdown."""
        limit = self.wait_minutes * 60
        t0 = time.monotonic()
        sent = set()
        if self._zwave_on():
            self.logger.info(
                f"{name.capitalize()}: waiting for Z-Wave to be switched off. In the Indigo client choose "
                f"Interfaces > Z-Wave > Disable. It starts the moment Z-Wave is off (waiting up to {self.wait_minutes} minutes).")
            self._set(actionRequired=True, backupStatus="Waiting: switch Z-Wave off")
        while self._zwave_on():
            if self._stop.is_set():
                return False
            elapsed = time.monotonic() - t0
            if elapsed >= limit:
                self.logger.warning(
                    f"{name.capitalize()} cancelled: Z-Wave was still on after {self.wait_minutes} minutes. Run it again when you are ready.")
                self._final_status = f"{name.capitalize()} cancelled"
                self._set(actionRequired=False, lastResult=f"{name} cancelled: Z-Wave stayed on")
                return False
            for mark in REMINDER_SECONDS:
                if elapsed >= mark and mark not in sent:
                    sent.add(mark)
                    self.logger.info("Still waiting for Z-Wave to be switched off (Interfaces > Z-Wave > Disable).")
            self._sleep(POLL_SECONDS)
        return True

    def _resolve_port(self):
        if self.port_override:
            return self.port_override, None
        path = self._zwave_prefs_path()
        port, conn, _home = ci.zwave_port_from_prefs(path)
        if not port:
            return None, "Could not find the Z-Wave serial port in Indigo's settings. Set it in the plugin's Configure dialog."
        if conn and conn != "local":
            return None, f"Indigo's Z-Wave interface is connected over the network ({conn}), which this plugin cannot image. Only a stick plugged into this Mac."
        return port, None

    def _open(self, port_path):
        t0 = time.monotonic()
        while ci.port_holders(port_path) and time.monotonic() - t0 < PORT_FREE_WAIT_SECONDS:
            if self._stop.is_set():
                raise RuntimeError("stopped")
            self._sleep(POLL_SECONDS)
        holders = ci.port_holders(port_path)
        if holders:
            raise RuntimeError(f"the port is still held by process {', '.join(holders)} although Z-Wave reports off")
        self._sleep(SETTLE_SECONDS)          # let the stick finish whatever it was saying to Indigo
        port = ci.open_port(port_path)
        api = ci.SerialApi(port, sleep=self._sleep_short)
        api.reset_parser()
        return port, api

    @staticmethod
    def _sleep_short(seconds):
        time.sleep(seconds)

    def _with_stick(self, name, body):
        """Wait for Z-Wave off, open the port, read identity, run body(port, api, identity, nvm)."""
        if not self._wait_for_zwave_off(name):
            return False
        port_path, err = self._resolve_port()
        if err:
            self.logger.error(err)
            self._final_status = f"{name.capitalize()} failed"
            return False
        self.logger.info(f"Z-Wave is off. Opening {port_path}.")
        self._set(actionRequired=False, backupStatus=f"{name.capitalize()} in progress")
        port, api = self._open(port_path)
        try:
            identity = ci.read_identity(api)
            if not ci.is_500_series(identity):
                self.logger.error(
                    f"This controller reports '{identity.get('libraryVersionString')}', which is a 700 or 800 series stick. "
                    f"Version {PLUGIN_VERSION} images 500-series controllers only.")
                self._final_status = f"{name.capitalize()} failed"
                return False
            nvm = ci.read_nvm_id(api)
            return body(port_path, port, api, identity, nvm)
        finally:
            try:
                port.close()
            except Exception:
                pass

    def _progress(self, label):
        def cb(done, total):
            self.logger.debug(f"{label}: {done * 100 // total}% ({done}/{total} bytes)")
        return cb

    def _cue_reenable(self):
        """After any operation: if Z-Wave is still off, say so, and clear the flag once it is on."""
        if self._zwave_on():
            self._set(actionRequired=False, backupStatus=self._final_status or self._shadow.get("backupStatus", ""))
            if self._final_status and self._last and not self._network_flag and "failed" not in self._final_status.lower():
                self._refresh_device_states()
            self._final_status = None
            return
        self.logger.info("Switch Z-Wave back on now: Interfaces > Z-Wave > Enable in the Indigo client.")
        self._set(actionRequired=True, backupStatus="Action required: switch Z-Wave back on")
        t0 = time.monotonic()
        while not self._zwave_on():
            if self._stop.is_set():
                return
            if time.monotonic() - t0 > REENABLE_WAIT_SECONDS:
                self.logger.warning("Z-Wave has been off for half an hour. Nothing is controlling your devices until you choose Interfaces > Z-Wave > Enable.")
                return
            self._sleep(POLL_SECONDS)
        self.logger.info("Z-Wave is back on.")
        self._set(actionRequired=False)
        if self._last and "failed" not in (self._final_status or "").lower():
            self._refresh_device_states()
        else:
            self._set(backupStatus=self._final_status or self._shadow.get("backupStatus", ""))
        self._final_status = None

    # --------------------------------------------------------
    # The three operations
    # --------------------------------------------------------

    def _run_backup(self):
        self._with_stick("backup", self._backup_body)

    def _backup_body(self, port_path, port, api, identity, nvm):
        size = nvm["sizeBytes"]
        _p, _c, prefs_home = ci.zwave_port_from_prefs(self._zwave_prefs_path())
        if prefs_home and prefs_home != identity["homeId"]:
            self.logger.warning(f"The stick's Home ID is {identity['homeId']} but Indigo's Z-Wave settings name {prefs_home}. Imaging the stick as it is.")
        nodes = [n for n in identity["nodeIds"] if n != identity["ownNodeId"]]
        self.logger.info(
            f"Reading {identity['modelName']}, Home ID {identity['homeId']}, {ci.software_description(identity)}, "
            f"{len(nodes)} nodes, {size // 1024} KB of memory. Two full reads, about a minute.")
        chunk = ci.initial_chunk_for(identity)
        t0 = time.monotonic()
        img1 = ci.dump_nvm(api, size, chunk, progress=self._progress("read 1"), should_stop=self._stop.is_set)
        img2 = ci.dump_nvm(api, size, chunk, progress=self._progress("read 2"), should_stop=self._stop.is_set)
        diff = ci.compare_images(img1, img2)
        checks, problems = ci.image_checks(img1, size, identity["homeId"])
        if diff["differingBytes"]:
            problems.append(f"the two reads differ in {diff['differingBytes']} bytes (first at offset {diff['firstDifference']})")
        if problems:
            for p in problems:
                self.logger.error(f"Backup not saved: {p}.")
            self._final_status = "Backup failed"
            self._set(lastResult="backup failed: " + "; ".join(problems), lastBackupOk=False)
            return False
        taken = ci.now()
        self._ensure_folder()
        base = ci.image_filename(identity, taken)
        image_path = _os.path.join(self.backup_folder, base + ".bin")
        with open(image_path, "wb") as fh:
            fh.write(img1)
        side = ci.sidecar_for(identity, nvm, checks, image_path, port_path, taken, PLUGIN_VERSION,
                              self._indigo_version(), reads_identical=True)
        with open(ci.sidecar_path_for(image_path), "w", encoding="utf-8") as fh:
            json.dump(side, fh, indent=2)
        self._last, self._last_path = side, image_path
        self._network_flag = False
        self.logger.info(
            f"Backup complete in {time.monotonic() - t0:.0f} s: {image_path} ({size} bytes, both reads identical, "
            f"sha256 {checks['sha256'][:12]}).")
        self._final_status = f"Backed up {self._pretty(side['takenAt'])}, current"
        self._set(lastResult="backup ok", lastBackupOk=True, networkChangedSinceBackup=False,
                  lastBackupAt=side["takenAt"][:16].replace("T", " "), lastBackupFile=image_path,
                  **self._identity_states(identity))
        return True

    def _run_verify(self):
        self._with_stick("verify", self._verify_body)

    def _verify_body(self, port_path, port, api, identity, nvm):
        if not self._last_path or not _os.path.isfile(self._last_path):
            self.logger.error("There is no backup image to verify against. Take one first.")
            self._final_status = "Verify failed"
            return False
        with open(self._last_path, "rb") as fh:
            image = fh.read()
        self.logger.info(f"Reading the controller to compare with {_os.path.basename(self._last_path)}.")
        current = ci.dump_nvm(api, nvm["sizeBytes"], ci.initial_chunk_for(identity),
                              progress=self._progress("verify read"), should_stop=self._stop.is_set)
        diff = ci.compare_images(image, current)
        if diff["differingBytes"] == 0:
            self.logger.info("Verified: the controller's memory matches the last backup byte for byte.")
            self._final_status = f"Backed up {self._pretty(self._last['takenAt'])}, verified"
            self._set(lastResult="verify ok: matches the last backup")
            return True
        self.logger.warning(
            f"The controller's memory differs from the last backup in {diff['differingBytes']} bytes "
            f"(first at offset {diff['firstDifference']}). Routes change on their own; a node table change means the network changed. Back it up again.")
        self._final_status = "Network changed since backup"
        self._network_flag = True
        self._set(lastResult=f"verify: {diff['differingBytes']} bytes differ from the last backup", networkChangedSinceBackup=True)
        return True

    def _run_restore(self, path, replacement_ok):
        self._with_stick("restore", lambda pp, port, api, ident, nvm: self._restore_body(pp, port, api, ident, nvm, path, replacement_ok))

    def _restore_body(self, port_path, port, api, identity, nvm, path, replacement_ok):
        with open(path, "rb") as fh:
            image = fh.read()
        try:
            side = ci.load_sidecar(path)
        except (OSError, ValueError):
            side = None
        reasons = ci.restore_refusals(image, side, identity, nvm, replacement_ok)
        if reasons:
            for r in reasons:
                self.logger.error(f"Restore refused: {r}.")
            self._final_status = "Restore refused"
            self._set(lastResult="restore refused: " + "; ".join(reasons))
            return False
        self.logger.info(
            f"Writing {_os.path.basename(path)} ({len(image)} bytes) into {identity['modelName']}, Home ID {identity['homeId']}. "
            f"Do not unplug anything yet.")
        chunk = ci.initial_chunk_for(identity)
        written, skipped = ci.write_nvm(api, image, chunk, progress=self._progress("write"), should_stop=self._stop.is_set)
        for off, n in skipped:
            at_end = off + n == len(image)
            blank = all(b == 0xFF for b in image[off:off + n])
            where = f"the last {n} bytes of its memory" if at_end else f"{n} bytes of its memory at offset {off}"
            note = ""
            if at_end and blank:
                note = (" Those bytes are blank in the image, which is what the end of a stick's memory normally holds; "
                        "the Aeotec Gen5 is known to refuse writes there and this is expected, not a fault.")
            self.logger.info(
                f"The controller would not accept a write to {where}, and the plugin did not force it. It read those bytes back "
                f"instead and they already hold exactly what the image holds, so the restore is complete and nothing is missing.{note}")
        if ci.soft_reset_allowed(identity):
            self.logger.info(f"Written {written} bytes. Resetting the controller.")
            if not ci.soft_reset(api):
                self.logger.warning("The controller did not acknowledge the reset; the unplug will do the same job.")
        else:
            self.logger.info(f"Written {written} bytes. This model is not soft-reset (it does not come back); the unplug does the job.")
        port.close()
        self.logger.info("Now unplug the stick, wait three seconds, and plug it back in. I will then read it back to check the image took.")
        self._set(actionRequired=True, backupStatus="Action required: unplug and replug the stick")
        self._wait_for_replug(port_path)
        port2, api2 = self._open(port_path)
        try:
            ident2 = ci.read_identity(api2)
            current = ci.dump_nvm(api2, nvm["sizeBytes"], chunk, progress=self._progress("read-back"), should_stop=self._stop.is_set)
        finally:
            port2.close()
        diff = ci.compare_images(image, current)
        if diff["differingBytes"] == 0 and ident2.get("homeId") == side["identity"].get("homeId"):
            self.logger.info(
                f"Restore verified: the controller's memory matches the image byte for byte, Home ID {ident2['homeId']}, "
                f"{len([n for n in ident2['nodeIds'] if n != ident2['ownNodeId']])} nodes.")
            self._final_status = f"Restored {self._pretty(side.get('takenAt', ''))}, verified"
            self._set(lastResult="restore ok: read-back matches the image", **self._identity_states(ident2))
            return True
        self.logger.error(
            f"Restore did NOT hold: the read-back differs from the image in {diff['differingBytes']} bytes "
            f"(Home ID now {ident2.get('homeId')}). Do not switch Z-Wave back on yet. Run Restore again, or restore your previous image.")
        self._final_status = "Restore failed"
        self._set(lastResult=f"restore failed: read-back differs in {diff['differingBytes']} bytes")
        return False

    def _wait_for_replug(self, port_path):
        """Wait for the port node to vanish (unplug) and return (replug). Carry on either way."""
        t0 = time.monotonic()
        gone = False
        while time.monotonic() - t0 < REPLUG_WAIT_SECONDS:
            if self._stop.is_set():
                raise RuntimeError("stopped")
            if not _os.path.exists(port_path):
                gone = True
                break
            self._sleep(1)
        if not gone:
            self.logger.warning("The stick was not unplugged within five minutes. Checking the image anyway; a power-cycle is still recommended.")
            return
        self.logger.debug("Stick unplugged; waiting for it to come back.")
        t1 = time.monotonic()
        while time.monotonic() - t1 < REPLUG_WAIT_SECONDS:
            if self._stop.is_set():
                raise RuntimeError("stopped")
            if _os.path.exists(port_path):
                self._sleep(3)
                return
            self._sleep(1)
        raise RuntimeError("the stick did not come back within five minutes of being unplugged")

    @staticmethod
    def _indigo_version():
        try:
            return str(indigo.server.version)
        except Exception:
            return "unknown"
