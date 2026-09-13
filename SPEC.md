# Z-Wave Controller Backup — SPEC (v1.0.0)

Agreed 13-Sep-2026 between CliveS and Claude Fable 5.1. Signed-off spec precedes any code.

## Purpose and success

A plugin any Indigo user on a Mac can install that takes a complete, verified image of their
500-series Z-Wave controller's memory (Home ID, node table, routing) and can write it back.

**Success criterion:** an image taken by the plugin, written back by the plugin onto the same
stick, leaves Indigo controlling every device exactly as before, with no re-pairing. Proven on
CliveS's Gen5 by writing the 12-Sep image back (identical bytes, so a working restore changes
nothing).

**Why it exists:** a 500-series stick can lose its node table (mat, forum t=29135, 106 devices).
Indigo's only documented remedy is exclude/include everything. With an image on disk the remedy
is a two-minute restore.

## Scope

**In v1.0.0**
- Backup: raw image over the Serial API, double read, verified, saved with a JSON sidecar.
- Restore: raw write of an image, guarded (below), then a full re-read to prove it held.
- One `Z-Wave Controller` device carrying identity + backup status states.
- Stale nudge: flags the last backup as stale when Indigo's Z-Wave devices change.
- Guides the user through the two clicks Indigo needs (Interfaces -> Z-Wave -> Disable / Enable)
  and waits for them, with every step in the event log.
- Any 500-series stick Indigo connects to locally: Aeotec Gen5/Gen5+, Z-Wave.me UZB, HomeSeer
  SmartStick+, Zooz ZST10 500, Sigma/SiLabs UZB-based sticks.

**Out of v1.0.0**
- 700/800-series sticks (different memory protocol, no hardware here to test). The plugin
  detects one and refuses with a clear message.
- Conversion between firmware versions or stick generations (zwave-js territory; needs SDK
  6.61+ and a Windows-only Aeotec update on older Gen5s). Documented in the README, not done.
- Network-attached sticks (RFC2217 / socket connection types). Refused with a message.
- Scheduling / unattended backups. Not possible: Z-Wave must be disabled by hand.
- Any write to the network itself (no inclusion, exclusion, SUC changes, node edits).

## External contract (verified live 12-Sep-2026 against a Gen5, firmware 1.01, SDK 6.51.10)

Transport: the stick's serial port, exclusive open, 115200 8N1, Serial API framing (SOF/LEN/
TYPE/FUNC/payload/checksum, ACK/NAK/CAN). Function ids verified against @zwave-js/serial:

| Use | Function | Notes |
|---|---|---|
| library string ("Z-Wave 4.54") + type | 0x15 GetVersion | protocol string -> SDK via the INS13954 table |
| Home ID + own node id | 0x20 MemoryGetId | |
| controller flags (primary/SUC/SIS) | 0x05 GetControllerCapabilities | |
| SUC node id | 0x56 GetSUCNodeId | |
| manufacturer/product ids, serial API version | 0x07 GetSerialApiCapabilities | |
| node bitmask, chip type | 0x02 GetSerialApiInitData | 29-byte mask |
| NVM size code | 0x29 GetNVMId | payload[3]: 18 = 256 KB |
| read NVM | 0x2A ExtNVMReadLongBuffer | offset 3 bytes BE + length 2 bytes BE, adaptive chunk (48 for Aeotec 0x86/0x01/0x5A, 168 otherwise), empty reply -> 48 |
| write NVM | 0x2B ExtNVMWriteLongBuffer | chunk = (first read length - 5), mirrors zwave-js restoreNVMRaw500 |
| soft reset | 0x08 SoftReset | after a write, then the user power-cycles the stick |

Port discovery: read Indigo's own Z-Wave prefs
(`Preferences/Plugins/com.perceptiveautomation.indigoplugin.zwave.indiPref`,
`interfacePort_serialPortLocal`, `interfacePort_serialConnType` must be `local`). Override field
in PluginConfig for the odd case. No sample-payload gap: the reader is already proven on this
stick, and the FakePort self-test pins the framing.

The port is free only while Indigo's Z-Wave interface is disabled. `indigo.zwave.isEnabled()`
tells the plugin when the user has done that; `lsof` is the belt-and-braces check before opening.

## Device model

One custom device, `zwaveController`, created by the user (one per controller; a second is
refused). Display state `backupStatus`.

| State | Type | Meaning |
|---|---|---|
| backupStatus | string | display: "Never backed up" / "Backed up 12 Sep 17:24, current" / "Network changed since backup" / "Backup in progress" / "Action required: switch Z-Wave back on" / "Backup failed" |
| actionRequired | bool | true while the plugin is waiting for the user's Disable or Enable click |
| lastBackupAt | string | ISO time of the last successful image |
| lastBackupFile | string | path of the last image |
| lastBackupOk | bool | |
| networkChangedSinceBackup | bool | the stale nudge |
| homeId | string | 8 hex chars |
| controllerModel | string | e.g. "Aeotec Z-Stick Gen5 (0086:0001:005A)" |
| softwareVersion | string | library string, e.g. "Z-Wave 4.54 (SDK 6.51.10)" |
| nodeCount | int | node ids the controller lists, excluding itself |
| nodeIds | string | comma list, for the notes and for the stale check |
| isPrimary / isSUC | bool | |

States are written only by the plugin's own worker; no other store holds them (state ownership).

## Menu items (plugin menu)

1. **Back Up Controller Now...** — dialog shows the backup folder, the two instructions
   ("1. Interfaces -> Z-Wave -> Disable. 2. Click Start.") and Start. Start returns at once and
   spawns the worker. The worker: waits up to `waitMinutes` (default 10) for Z-Wave to go off
   (INFO at start, a reminder at 3 and 6 minutes, WARNING and stop at the limit), opens the port,
   reads identity, refuses a 700-series stick, warns if the Home ID differs from Indigo's prefs, reads the
   NVM twice, compares, checks size / not blank / Home ID present, writes `.bin` + `.json`,
   updates the device, closes the port, then logs the cue: **"Backup complete. Switch Z-Wave back
   on: Interfaces -> Z-Wave -> Enable."** and sets `actionRequired` until `isEnabled()` is true
   again (polled for up to 30 minutes, then the state stays set and a WARNING says so).
2. **Restore Controller...** — dialog lists the images in the backup folder (newest first, with
   date, model and Home ID from the sidecar), a checkbox "This image goes onto a REPLACEMENT
   stick" (required when the Home ID differs), and a confirmation checkbox "I understand this
   overwrites the controller's memory". Worker: same wait, identity read, **guards** (below),
   write in chunks, soft reset, then instructs "unplug the stick, wait three seconds, plug it
   back in" and waits for the port to disappear and return (up to 5 minutes), re-reads the whole
   NVM and compares with the image, logs the verdict, then the same re-enable cue.
3. **Verify Last Backup** — re-reads the stick and compares with the last image (same wait
   dance). Cheap proof for the nervous.
4. Standard **Show Plugin Info** (banner) last, after a separator.

Only one operation at a time (a lock); a second menu action is refused with a log line.

**Restore guards (all hard refusals unless stated):** image size equals the stick's NVM size;
manufacturer/product ids equal; library version string equal (the same-firmware rule: SDK 6.51
and 6.81 layouts differ); Home ID equal unless the replacement-stick box is ticked; sidecar
present and parseable; the plugin's own read-back after the write must equal the image, else
ERROR naming the mismatch count and "do not re-enable Z-Wave yet, run Restore again".

## Stale nudge

The plugin subscribes to device changes (loop guard on its own pluginId). When a device with
`protocol == indigo.kProtocol.ZWave` is created or deleted, or when Indigo's set of Z-Wave node
ids differs from the last image's `nodeIds`, it sets `networkChangedSinceBackup`, sets
`backupStatus` to "Network changed since backup" and logs one WARNING (once per change, not per
tick). A successful backup clears it. Users trigger their own reminder on the state.

## The six architecture questions

1. **State ownership** — the device states are the only store; the worker writes them, nothing
   else does. The last image's identity lives in its `.json` sidecar, read on demand.
2. **Failure isolation** — the worker's whole body is one try/except: any exception logs an
   ERROR, closes the port, clears `actionRequired` if Z-Wave is already on, sets `backupStatus`
   to "Backup failed", and never leaves the port open. `deviceUpdated` is wrapped the same way.
3. **Config-blank safety** — folder blank -> default under the Perceptive Automation root
   (`Z-Wave Controller Backups/`), created on demand; wait minutes coerced with try/except and
   clamped 1..60; port override blank -> Indigo's prefs.
4. **Idempotency + loops** — device-change subscription guarded on pluginId; the nudge sets a
   flag rather than re-logging; the wait loop polls `isEnabled()` every 2 s and cannot spin.
5. **Termination** — every wait has a limit (Z-Wave off: 10 min default; re-enable: 30 min;
   replug: 5 min); the serial layer has per-command attempts (3) and timeouts; `StopThread` is
   honoured by checking `self.stopThread` in the wait loops (they are worker threads, not
   `runConcurrentThread`, so they check the flag themselves and exit within 2 s of shutdown).
6. **Test seam** — the serial layer takes any object with `read()`/`write()`; `FakePort` is a
   scripted stick. The backup/restore/verify logic is a pure class (`ControllerImage`) that
   never touches `indigo`; the plugin class only wires menus, device states and logging.

**Threading model:** menu callbacks return immediately and start a `threading.Thread`
(daemon) per operation; no `runConcurrentThread` at all. Progress and cues go to
`self.logger.info`, faults to `warning`/`error`. Why a thread: UI callbacks time out at ~30 s
and a backup takes 70 s plus however long the user takes to click.

## Files written

`<folder>/<Model>_<HomeID>_<YYYY-MM-DD_HHMM>.bin` (exact NVM size) and `.json` (identity,
NVM ids, checks, sha256, tool version, Indigo version). `<folder>/README.md` written once:
what these files are, the same-firmware rule, how to restore from the plugin and, as a
fallback, with mat's zwave-js script. Keep all images (256 KB each); no retention logic.

## Config (PluginConfig.xml)

- Backup folder (blank = default).
- Serial port override (blank = Indigo's own setting).
- Wait for Z-Wave to be switched off: minutes (default 10).
- Debug logging checkbox.
- No credentials of any kind: no IndigoSecrets keys.

## Logging

Indigo's start line only at boot. INFO for every step that changes something or needs the user
(waiting, port opened, read done, verified, file written, "switch Z-Wave back on", restore
written, restore verified). DEBUG for chunk progress. WARNING for timeouts and the stale nudge.
ERROR for guard refusals and faults, always naming the reason. Banner on demand only.

## Tests

`tests/` at the repo root, pytest, stub `indigo`:
- framing: build/checksum vectors (01 03 00 20 DC), parser with ACK / unsolicited frame /
  corrupt frame -> NAK / CAN retry; empty-chunk fallback to 48; write chunking mirrors the read.
- identity parsing from recorded payloads of the Gen5 (captured 12-Sep).
- backup happy path against FakePort; checks (size, blank, Home ID); sidecar content.
- every restore guard refuses on its own condition and passes when all hold; replacement-stick
  path; read-back mismatch is an ERROR.
- stale nudge: created/deleted Z-Wave device sets the flag once; a backup clears it; a
  non-Z-Wave device does nothing; own-plugin updates are ignored.
- wait loop: times out, honours stopThread, proceeds when isEnabled flips.
- the canonical `test_version_consistency.py`, `ruff.toml`, CI workflow running pytest.
Mutation sweep before release on the guards (each guard removed must go red).

**Live verification (the part tests cannot do):** backup on CliveS's Gen5 -> restore that image
onto the same stick -> read-back equal -> Indigo re-enabled -> a device commanded and answered.

## Repo and release

- `~/GitHub/ZWaveControllerBackup`, Highsteads org, public, MIT, standard Authors & licence
  footer, house `.gitignore`, `**Version:**` README header + `## What's new`, topics
  `indigo, indigo-domotics, home-automation, indigo-plugin, zwave`, Issues on.
- Bundle `Z-Wave Controller Backup.indigoPlugin`, id `com.clives.indigoplugin.zwave-controller-backup`,
  PluginVersion 1.0.0, ServerApiVersion 3.0, CFBundleVersion 1.0.0, CFBundleURLTypes -> the repo,
  GithubInfo {GithubRepo, GithubUser}, `Contents/Resources/icon.png` for the store.
- v1.0.0 GitHub release with the `.indigoPlugin.zip` once the live verification has passed.
- Credit mat's write-up and zwave-js (MIT) in the README. Nothing vendored from either.

## Pre-fills assumed (shout if wrong)

Header block, `self.logger` + millisecond filter, on-demand banner, `showPluginInfo`,
Python 3.13 stdlib only (termios/fcntl/json/hashlib), no requirements.txt, versioning from
1.0.0, UK English throughout, plain-English event-log lines.
