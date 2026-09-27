---
title: Home
nav_order: 1
---

# Z-Wave Controller Backup for Indigo

This plugin takes a complete copy of the memory of the Z-Wave USB stick that runs your network, checks the copy, keeps it as a file on the Mac, and can write it back. It all happens from inside [Indigo](https://www.indigodomo.com), on the Mac Indigo already runs on, and there is nothing else to install.

## Why you might want it

The stick keeps the only copy of what your Z-Wave network is: its **Home ID**, the number the stick gives your network and every device on it shares, the list of devices it knows, and the routes it uses to reach them. A stick can lose that list. When it does, every device still belongs to the network, but the stick no longer knows any of them, and the usual remedy is to exclude and include every device again. mat on the Indigo forum had that happen to 106 of them.

With a copy of the stick's memory on disk, the remedy is a restore that takes a few minutes instead.

## What it does for you

- **Backs up the stick.** It reads the stick's whole memory twice, checks the two reads match, and saves the copy with a small file beside it that records which stick it came from and when.
- **Restores a backup.** It writes a copy back, then reads the stick again to prove the copy took before it tells you to switch Z-Wave back on. It refuses a copy from a different model, or from a stick running a different software version.
- **Verifies the last backup.** It reads the stick and compares it with the newest copy.
- **Gives you one device**, called Z-Wave Controller, which shows what the stick is, when it was last backed up, and whether the network has changed since.
- **Reminds you when a backup is out of date.** Adding or removing a Z-Wave device in Indigo marks the last backup as out of date, in the Event Log and on the device.

## The one thing you do by hand

While Z-Wave is running, Indigo holds the stick, and there is no command a plugin can use to make it let go. So for every backup, verify or restore, you switch Z-Wave off yourself with **Interfaces → Z-Wave → Disable** in the Indigo client, and switch it back on with **Interfaces → Z-Wave → Enable** when the Event Log tells you to. The plugin notices each step within a couple of seconds and tells you what to do next.

For a backup of a 500 series stick, Z-Wave is off for about two minutes in all. Because of this step, backups are not automatic.

## Which sticks it works with

Any 500, 700 or 800 series Z-Wave stick plugged into the Indigo Mac by USB. The series is the generation of Z-Wave chip inside the stick. The plugin works out which generation it is talking to, and finds the stick from Indigo's own Z-Wave settings, so there is nothing to set up.

| Series | For example |
|---|---|
| **500** | Aeotec Z-Stick Gen5 and Gen5+, Z-Wave.me UZB, HomeSeer SmartStick+, Zooz ZST10 500 |
| **700 and 800** | Zooz ZST10 700 and ZST39, Aeotec Z-Stick 7 and Z-Stick 10 Pro, Silicon Labs UZB-7 |

These have been through backup, verify and restore on real networks: my own Aeotec Z-Stick Gen5 with thirty devices, and on Autolog's system a Zooz ZST39 LR, an Aeotec Z-Stick 10 Pro and a Silicon Labs 700 series stick. The other sticks in the table have not been tried.

A Z-Wave interface that Indigo reaches over the network, rather than a stick plugged into the Mac, is not supported.

## Where to go next

| If you want to... | Read |
|---|---|
| Install the plugin and take your first backup | [Getting started](getting-started.md) |
| Know exactly what happens during a backup or a verify | [Taking a backup](backing-up.md) |
| Put a backup back onto your stick, or onto a replacement | [Restoring a backup](restoring.md) |
| Know what the Z-Wave Controller device shows, and use it in triggers | [Your device](device.md) |
| Understand what the plugin is doing behind the scenes | [How it works](how-it-works.md) |
| Know what every setting does | [Settings](settings.md) |
| Know what each item in the Plugins menu does | [The plugin menu](plugin-menu.md) |
| Sort out a problem | [When something goes wrong](troubleshooting.md) |
| See what changed in each version | [Version history](changelog.md) |

## Download

The latest version is always on the [Releases page](https://github.com/Highsteads/ZWaveControllerBackup/releases/latest).
