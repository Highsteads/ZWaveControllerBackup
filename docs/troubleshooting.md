---
title: When something goes wrong
nav_order: 9
---

# When something goes wrong

Each section starts with what you see, then what it means and what to do.

## The Event Log says "Restore did NOT hold" or "Restore failed"

If the log goes on to say **Do not switch Z-Wave back on yet**, the stick's memory may be partly written. **Leave Z-Wave off** and run the restore again. The [Restoring a backup](restoring.md#if-the-restore-does-not-hold) page says exactly what to do. If the log asks you to switch Z-Wave back on instead, nothing was written, and it is safe to do so.

## The Event Log says "Restore refused"

The backup does not fit this stick, or the backup file has changed since it was saved, and nothing was written. Each line gives the reason, and the [Restoring a backup](restoring.md#why-a-restore-is-refused) page explains each one. It is safe to switch Z-Wave back on.

## The Event Log says the job was cancelled because Z-Wave was still on

The plugin waited the number of minutes set in its [Settings](settings.md), 10 to start with, and Z-Wave was not switched off. Nothing was read or written. Run it again, and choose **Interfaces → Z-Wave → Disable** in the Indigo client.

## The plugin says a backup, verify or restore "is already running"

A job counts as finished once Z-Wave is back on. Choose **Interfaces → Z-Wave → Enable**, wait for the log to say **Z-Wave is back on**, and try again. A restore that did not hold finishes straight away without asking for Z-Wave, so you can run it again at once.

## The Event Log says "Could not find the Z-Wave serial port in Indigo's settings"

The plugin could not read which port the stick is on. Open **Plugins → Z-Wave Controller Backup → Configure** and fill in **Serial port** with the stick's port, which Indigo shows in its own Z-Wave interface settings.

## The Event Log says the Z-Wave interface "is connected over the network"

Indigo reaches its Z-Wave interface over the network rather than through a stick plugged into the Mac. The plugin only works with a stick plugged into the Indigo Mac.

## The Event Log says "the port is still held by process ..."

Z-Wave is off in Indigo, but another program still has the stick open. Close whatever else uses the stick, and run the job again.

## The Event Log says "Backup not saved"

One of the checks failed, and the line says which. If it says the two reads differ, run the backup again. If the same thing happens twice, post the Event Log lines in the forum thread below.

## The Event Log warns that the stick's Home ID is not one Indigo's settings know

The stick plugged in is not on a network Indigo's Z-Wave settings remember. The backup still goes ahead. Check it is the stick you meant to back up.

## The Event Log says the controller would not accept a write to the last 16 bytes of its memory

This happens on an Aeotec Gen5 during a restore. Those bytes are blank in every copy of that stick, and the plugin has confirmed they already match. It is expected, not a fault.

## The Event Log says the controller answered "end of file" to the final bytes

This happens on 700 and 800 series sticks during a restore. Those bytes hold nothing the stick uses, and the plugin leaves them alone. It is expected, not a fault.

## The Event Log says the controller did not announce itself after the reset

A 700 or 800 series stick did not confirm it had restarted. Switch Z-Wave back on as usual, and if Indigo cannot reconnect to the stick, unplug it and plug it back in.

## The Event Log says the controller "differs from the last backup"

The stick has changed since the last backup. Routes between devices change on their own over time, and a change to the list of devices means the network changed. Take a fresh backup.

## The Event Log says Z-Wave has been off for half an hour

Nothing is controlling your Z-Wave devices. Choose **Interfaces → Z-Wave → Enable**.

## The Event Log says the plugin does not recognise the controller

The stick did not report itself as a 500, 700 or 800 series stick, so the plugin will not touch it. Post the Event Log lines in the forum thread below.

## The Restore window says "No images in the backup folder yet"

There are no backups in the folder the plugin is using, or their `.json` files are missing. Check the **Backup folder** setting points where your backups are, and that each `.bin` file still has its `.json` file beside it.

## The Z-Wave Controller device shows an error

You have more than one Z-Wave Controller device. Delete the extra one.

## Still stuck?

Choose **Plugins → Z-Wave Controller Backup → Show Plugin Info**, copy the lines it writes to the Event Log along with the lines from the job that went wrong, and post them in [this thread](https://forums.indigodomo.com/viewtopic.php?t=29135) on the Indigo forum. Please report problems there rather than on GitHub, where issues are turned off.
