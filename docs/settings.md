---
title: Settings
nav_order: 7
---

# Settings

## The plugin's settings

Open these with **Plugins → Z-Wave Controller Backup → Configure**. Most people can leave them all as they are.

| Setting | What it does |
|---|---|
| **Backup folder** | Where backups are saved. Leave it blank to use **Z-Wave Controller Backups** in `/Library/Application Support/Perceptive Automation/`, beside the Indigo folder. To use another folder, type or paste its full path, starting with `/` or `~`. Quotes around a pasted path are removed for you. The folder is created if it does not exist, and a path that does not start with `/` or `~` is refused. |
| **Serial port** | The port the stick is on. Leave it blank and the plugin uses the one Indigo's Z-Wave interface uses, which is right for almost everyone. Only fill it in if the plugin says it cannot find the port in Indigo's settings. |
| **Wait for Z-Wave to be switched off (minutes)** | How long a backup, verify or restore waits for you to switch Z-Wave off before it gives up, 10 minutes to start with. Any whole number from 1 to 60. |
| **Debug logging** | Adds extra lines to the Event Log, including progress through each read and write. Only useful when chasing a problem. |

The plugin needs no password, account or key, so there is nothing to put in `IndigoSecrets.py` for it.

## The device's settings

The Z-Wave Controller device has no settings. The [Your device](device.md) page explains what it shows.
