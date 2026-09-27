---
title: Taking a backup
nav_order: 3
---

# Taking a backup

## Step by step

1. Choose **Plugins → Z-Wave Controller Backup → Back Up Controller Now...**. The window shows the folder the backup will go to. Click **Start**.
2. In the Indigo client choose **Interfaces → Z-Wave → Disable**. Either order works. If Z-Wave is still on, the Event Log asks you to switch it off, and the Z-Wave Controller device shows **Waiting: switch Z-Wave off**.
3. Within a couple of seconds of Z-Wave going off, the plugin opens the stick and says in the Event Log what it has found — the model, its generation, the Home ID, its software version, how many devices it holds and how much memory it has.
4. It reads the whole memory twice. On a 500 series stick that takes about a minute (73 seconds on my Aeotec Gen5), and on a 700 or 800 series stick about twenty seconds.
5. The Event Log says **Backup complete**, with the file name, and then **Switch Z-Wave back on now**. Choose **Interfaces → Z-Wave → Enable**. The log says **Z-Wave is back on** and the device shows the new backup as current.

The plugin waits up to ten minutes for you to switch Z-Wave off, with a reminder after three minutes and again after six. If Z-Wave is still on after that, it cancels and says so, and you can run it again when you are ready. You can change the ten minutes in the [Settings](settings.md).

## What is checked before anything is saved

- **The two reads match** byte for byte.
- **The copy is the size the stick says its memory is.**
- **The copy is not almost entirely blank.**
- **The stick's Home ID appears in the copy.**

If any of these fail, nothing is saved, and the Event Log says which check failed.

The plugin also compares the stick's Home ID with the networks Indigo's own Z-Wave settings remember. If the stick's is not among them, the log gives a warning naming both, and the backup carries on, because the copy is still a true copy of that stick.

## What is saved

Each backup is two files in the backup folder:

| File | What it holds |
|---|---|
| **The `.bin` file** | The copy of the stick's memory. A 500 series Aeotec Gen5 gives 256 KB, and a 700 or 800 series stick about 40 to 48 KB. |
| **The `.json` file** | Which stick the copy came from — its model, Home ID, software version and devices — and when it was taken. |

The name says which stick and when, for example `Aeotec-Z-Stick-Gen5_1A2B3C4D_2026-09-13_1207.bin`, where the eight characters in the middle are your network's Home ID.

**Keep each pair together.** The plugin only offers a copy for restoring when its `.json` file sits beside it, because that is how it knows which stick the copy fits.

The files are small, so keep them all rather than tidying old ones away. The folder lives on the Mac, so make sure your usual backup, such as Time Machine, copies it somewhere else as well. The plugin also puts a short `README.md` in the folder saying what the files are.

## When to take one

Take a backup whenever you add a device to the network or remove one, because that is when the stick's list of devices changes. The plugin reminds you: adding or removing a Z-Wave device in Indigo puts a warning in the Event Log and shows **Network changed since backup** on the device.

## 700 and 800 series sticks

These sticks keep their memory in a different way, and the plugin handles them a little differently:

- It switches the stick's radio off while it reads, so nothing on the network can change the memory halfway through.
- It resets the stick at the end of every visit, which is how these sticks are meant to be left after their memory has been read. Indigo reconnects to the stick as normal when you switch Z-Wave back on.
- If the stick does not come back after that reset, the Event Log says so. If Indigo then cannot reconnect, unplug the stick and plug it back in.

## Verifying a backup

**Plugins → Z-Wave Controller Backup → Verify Last Backup** reads the stick once and compares it with the newest backup in the folder. It has no window. It starts straight away, and you switch Z-Wave off and on the same way as for a backup.

| The Event Log says | What it means |
|---|---|
| **Verified: the controller's memory matches the last backup byte for byte** | The stick and the backup are identical. |
| **Verified**, with a note that some bytes have been added in free space | A 700 or 800 series stick, which adds its own records to spare memory as it works. Nothing the backup holds has changed and the list of devices is the same, so the backup is still good. |
| **The controller's memory differs from the last backup** | Something has changed since. Routes between devices change on their own over time, and a change to the list of devices means the network changed. Either way, take a fresh backup. The device shows **Network changed since backup** until you do. |
