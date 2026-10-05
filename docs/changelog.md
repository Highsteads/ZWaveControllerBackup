---
title: Version history
nav_order: 10
---

# Version history

The newest version is at the top.

## 1.2.1 — 5 October 2026

- A restore now checks the backup file is exactly the one that was saved before it writes anything. Every backup records a checksum of its image in its `.json` file, and until now the restore never looked at it, so a file damaged on a disk but still the right size would have been written into the stick, and the check afterwards would have said it held, because it compared the stick with the same damaged file. Now a file that does not match is refused, and so is one whose `.json` file has no checksum at all.
- A restore also runs the checks a fresh backup has to pass, and refuses an image that is almost blank or that does not hold its own Home ID.
- **Restore verified** now says the backup's checksum was confirmed before anything was written, so it claims no more than the plugin has checked.
- If something went wrong just as the plugin opened the stick, it could keep hold of the port, and Indigo could not get the stick back until the plugin was reloaded. It now lets go.

## 1.2.0 — 27 September 2026

- When a restore does not hold, the Event Log tells you to leave Z-Wave off, and that is now the last word. Before, the very next line asked you to switch Z-Wave back on, which was the wrong advice.
- The device shows **Action required: run Restore again** in that case, rather than asking for Z-Wave back on.
- You can run the restore again straight away. Before, the plugin sat waiting for Z-Wave for up to half an hour and turned the second try away, so the only way round it was to reload the plugin.
- The **Debug logging** setting now says what it really shows, which is how far each read and write has got, every tenth of the way. It used to promise every single piece.

## 1.1.0 — 14 September 2026

- **700 and 800 series sticks** can be backed up, restored and verified, including the Zooz ZST10 700 and ZST39, the Aeotec Z-Stick 7 and Z-Stick 10 Pro, the Silicon Labs UZB-7 and similar. Autolog wrote this and tested it on a Zooz ZST39 LR, an Aeotec Z-Stick 10 Pro and a Silicon Labs 700 series stick, with the backups matching those made by Z-Wave JS UI byte for byte.
- These sticks need no unplugging during a restore, because the plugin resets them at the end instead.
- The list of devices is read correctly from a stick that has been switched to the longer device numbers some other software uses.
- **Show Plugin Info** and the device show the stick's full software version.
- A backup folder pasted with quotes around it is cleaned up, where before the backups could end up inside the plugin itself.
- The warning about a stick's Home ID checks every network Indigo's settings remember, not only the first one it finds.

## 1.0.2 — 13 September 2026

**Show Plugin Info** describes the stick itself: its model, Home ID, software version, how many devices the last backup holds, which file that is, and whether the network has changed since. Before, it showed only the folder, the port and the time of the last backup.

## 1.0.1 — 13 September 2026

When a stick refuses to write the very end of its memory during a restore, the Event Log explains in plain words what happened and why it is not a fault.

## 1.0.0 — 13 September 2026

The first release, for 500 series sticks plugged into the Indigo Mac: a backup with two reads and checks, a guarded restore that reads the stick back to prove the copy took, a verify, one Z-Wave Controller device, and a reminder when the network changes after a backup.
