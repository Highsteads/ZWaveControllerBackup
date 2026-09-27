---
title: Your device
nav_order: 5
---

# Your device

The plugin has one device, **Z-Wave Controller**, which stands for your Z-Wave stick. It is optional — backups and restores work without it — but it shows at a glance whether your last backup is still up to date, and triggers and control pages can use it.

It never switches anything, and it has no settings. One is all you need. A second one shows an error in the device list, and the Event Log says to delete it.

## What it shows

The device list shows **Backup status**. The rest are there for triggers, control pages and the device's details.

| Shown as | What it means |
|---|---|
| **Backup status** | A short summary, such as **Never backed up**, **Backed up 13 Sep 12:07, current**, **Backed up 13 Sep 12:07, verified**, **Restored 13 Sep 12:07, verified**, **Network changed since backup**, or what the plugin is waiting for — **Waiting: switch Z-Wave off**, **Action required: switch Z-Wave back on** or **Action required: unplug and replug the stick**. |
| **Action required** | True while the plugin is waiting for you to switch Z-Wave off or on, or to unplug and replug the stick. |
| **Network changed since backup** | True when a Z-Wave device has been added or removed in Indigo since the last backup, when Indigo has a Z-Wave device the backup does not hold, or when a verify found the stick had changed. It goes back to false when you take a new backup. |
| **Last backup OK** | True when the newest backup is good. False when there is none yet, or the last backup failed its checks. |
| **Last backup at** | The date and time of the newest backup, such as `2026-09-13 12:07`. |
| **Last backup file** | Where the newest backup is saved. |
| **Last result** | How the last job ended, such as **backup ok**, **verify ok: matches the last backup**, **restore ok: read-back matches the image**, or the reason a job failed, was cancelled or was refused. |
| **Home ID** | Your network's Home ID. |
| **Controller model** | The stick's model, such as **Aeotec Z-Stick Gen5**. A stick the plugin has no name for shows its maker's code numbers instead. |
| **Controller software** | The Z-Wave software version the stick reports. |
| **Nodes on the controller** | How many devices the stick knows, not counting itself. |
| **Node ids** | The numbers of those devices, the stick's own included. |
| **Is primary** | Whether the stick is the one in charge of the network. |
| **Is SUC** | Whether the stick is the network's update controller, which keeps any other controllers' copies of the network up to date. |

Everything the device shows about the stick comes from the newest backup, because the stick can only be read while Z-Wave is off. After a backup or a restore, it shows what the plugin found on the stick.

## Using it in triggers

Every item in the table is a device state, so an Indigo trigger can watch it. Create a new trigger, set its type to **Device State Changed**, choose the Z-Wave Controller device, and pick the state. Two that are useful:

- **Network changed since the last backup** — to send yourself a reminder to take a backup.
- **Action required (switch Z-Wave off or on)** — to tell you, wherever you are in the house, that the plugin is waiting for you.

## Using it on a control page

Any of the states can go on a control page. **Backup status** on its own is usually enough.
