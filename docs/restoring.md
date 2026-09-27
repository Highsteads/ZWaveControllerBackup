---
title: Restoring a backup
nav_order: 4
---

# Restoring a backup

A restore writes a backup back into the stick, over whatever the stick holds now. Read this page through before you start.

## Before you start

- **Only restore when you need to** — the stick has lost its network, or you are moving the network onto a replacement stick of the same model.
- **A backup only goes back onto the same model running the same software version** as the stick it came from. The layout of the memory changes between software versions, so a copy taken under one version does not fit another. The plugin checks this and refuses otherwise.
- **Switch Z-Wave back on only when the Event Log asks you to.** Once the plugin has written to the stick, it asks only after the restore is verified. If the restore does not hold, it says **Do not switch Z-Wave back on yet** and does not ask. Follow [If the restore does not hold](#if-the-restore-does-not-hold) below.
- **Never plug in two sticks holding the same Home ID at the same time**, with or without Indigo running. After you restore onto a replacement stick, the old stick and the new one hold the same network.
- **A 500 series stick needs unplugging and plugging back in** partway through, when the Event Log asks. Stay near the Mac.

## Step by step

1. Choose **Plugins → Z-Wave Controller Backup → Restore Controller...**.
2. In **Image**, choose the backup to write. The newest is already chosen, and each one shows the date, the stick's model and its Home ID. Only backups with their `.json` file beside them appear.
3. Tick **Replacement stick** only if this backup is going onto a different stick from the one it came from. The new stick will have a different Home ID from the backup, and without the tick the plugin refuses.
4. Tick **Confirm** — "I understand this overwrites the controller's memory". The plugin will not start without it.
5. Click **Restore**.
6. In the Indigo client choose **Interfaces → Z-Wave → Disable**. The plugin waits for this exactly as it does for a backup.
7. The plugin reads the stick and checks the backup fits it. If anything does not fit, the Event Log gives each reason on a line starting **Restore refused**, and nothing is written. When it then asks you to switch Z-Wave back on, it is safe to do so.
8. The plugin writes the backup into the stick. The Event Log says **Do not unplug anything** while it does. On my Aeotec Gen5 the writing took just under a minute.

What happens next depends on the generation of the stick.

### A 500 series stick

1. The plugin resets the stick, except for the few models that do not come back from a reset, such as the Z-Wave.me UZB, where the unplug does the same job.
2. The Event Log says **Now unplug the stick, wait three seconds, and plug it back in**, and the device shows **Action required: unplug and replug the stick**. Do exactly that, into the same USB socket.
3. The plugin notices the stick come back, reads its whole memory, and compares it with the backup byte for byte. It also checks the stick's Home ID is the one in the backup.
4. The Event Log says **Restore verified**, with the Home ID and the number of devices.

The plugin waits up to five minutes for you to unplug the stick. If you do not, it checks the stick anyway and says a power cycle is still recommended. Once you have unplugged it, it waits up to five minutes for the stick to come back, and if it does not, the restore fails.

On an Aeotec Gen5, the Event Log may say the stick would not accept a write to the last 16 bytes of its memory. Those bytes are blank in every copy of that stick, so the plugin reads them back instead, confirms they already match, and carries on. That is expected, not a fault.

### A 700 or 800 series stick

1. There is no unplugging. The plugin resets the stick and reads it straight back.
2. It checks that everything the backup holds is in the stick, and that the stick's Home ID and list of devices match the backup.
3. The Event Log says **Restore verified**, with the Home ID and the number of devices.

Two things the Event Log explains when they happen, and neither is a fault. The stick answers the very last piece of the write with "end of file" and does not write it, because those bytes hold nothing the stick uses, and the plugin leaves them alone. The stick also adds a few records of its own to spare memory when it restarts, so the check allows for those.

### Then, for every stick

1. The Event Log says **Switch Z-Wave back on now**. Choose **Interfaces → Z-Wave → Enable**.
2. Check that a device or two answers in Indigo.

If you restored onto a replacement stick, put the old one away and keep it unplugged.

## If the restore does not hold

If the Event Log says **Restore did NOT hold**, or the restore failed after the plugin had started writing, the stick's memory may be partly written. The log then says **Do not switch Z-Wave back on yet**, and the device shows **Action required: run Restore again**. **Leave Z-Wave off.** The plugin does not ask you to switch it back on, and it is ready for the next restore straight away.

To try again:

1. Check the stick is plugged in.
2. Run **Restore Controller...** again with the same backup, or choose your previous backup. Z-Wave is already off, so the plugin starts as soon as you click Restore.

If a restore failed before the plugin wrote anything, for example because it could not open the stick, the stick is as it was. The Event Log then asks you to switch Z-Wave back on as usual, and it is safe to do so.

Only switch Z-Wave back on once the Event Log says **Restore verified**. If a restore will not hold after a second try, post the Event Log lines in the [forum thread](https://forums.indigodomo.com/viewtopic.php?t=29135) before you do anything else.

## Why a restore is refused

| The Event Log says | What it means |
|---|---|
| **the image has no sidecar file** | The backup's `.json` file is missing, so the plugin cannot tell which stick it came from. |
| **the image is ... bytes but this controller's memory is ... bytes** | The backup is from a stick with a different amount of memory. |
| **the image came from ... and this controller is ...** | A different model. |
| **the image came from software ... and this controller runs ...** | The same model, running a different software version. |
| **the image came from SDK ... and this controller runs SDK ...** | A 700 or 800 series stick of the same model, running a different release of its Z-Wave software. |
| **the image is for Home ID ... and this controller is ...** | A different stick. Tick **Replacement stick** if that is what you meant. |

Nothing is written when a restore is refused.

## Moving to a different generation of stick

Moving a network from a 500 series stick to a 700, or from a 700 to an 800, is a conversion, not a restore, and this plugin does not do it. The zwave-js project has tools for that, and mat's write-up in the [forum thread](https://forums.indigodomo.com/viewtopic.php?t=29135) covers the route.
