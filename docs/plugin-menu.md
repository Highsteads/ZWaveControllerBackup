---
title: The plugin menu
nav_order: 8
---

# The plugin menu

These are under **Plugins → Z-Wave Controller Backup**.

| Menu item | What it does |
|---|---|
| **Back Up Controller Now...** | Opens a short window showing the steps and the folder the backup will go to. Click **Start**, then switch Z-Wave off. The [Taking a backup](backing-up.md) page has the details. |
| **Restore Controller...** | Opens a window where you choose a backup, tick **Replacement stick** if it is going onto a different stick, and tick **Confirm**. Click **Restore**, then switch Z-Wave off. Read the [Restoring a backup](restoring.md) page first. |
| **Verify Last Backup** | Starts straight away, with no window. Switch Z-Wave off, and the plugin reads the stick and compares it with the newest backup. |
| **Show Plugin Info** | Writes the plugin's version, details of your Mac and Indigo, the backup folder, the stick's port, and what the newest backup says about the stick — its model, Home ID, software version, how many devices it holds, when it was taken, the file name, and whether the network has changed since — to the Event Log. It does not need Z-Wave switched off. It is the thing to include if you ask for help on the Indigo forum. |

Indigo adds its own items to the same menu, such as **Reload**, which restarts the plugin.

Only one backup, verify or restore runs at a time. If you start another before the first has finished, which means before Z-Wave is back on, the plugin says one is already running. A restore that did not hold finishes straight away, so you can run it again at once.
