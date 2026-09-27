---
title: How it works
nav_order: 6
---

# How it works

You do not need to know any of this to use the plugin. It is here for anyone who likes to know what is going on.

## What is in the stick's memory

A Z-Wave stick keeps its network in its own memory: the Home ID, the list of devices it has included, and the routes it has worked out for reaching each one. The stick holds the only copy of all this. The plugin copies that memory exactly as it is, byte for byte, into a file on the Mac.

A 500 series stick holds its memory as one plain block, which the plugin reads from start to finish. A 700 or 800 series stick holds it as a small filing system, reached through a different set of commands, and the plugin works out which kind it has from what the stick reports about itself.

## Why Z-Wave has to be off

Only one program can talk to the stick at a time, and while Z-Wave is running that program is Indigo. There is no command a plugin can use to make Indigo let go, so you do it by hand with **Interfaces → Z-Wave → Disable**.

The plugin checks every two seconds whether Z-Wave has been switched off. Once it has, the plugin waits until nothing else has the stick open, pauses two seconds so the stick can finish anything it was still saying to Indigo, and then opens it for itself alone. When the job is finished it closes the stick, asks you to switch Z-Wave back on, and checks every two seconds until you have. The one exception is a restore that wrote to the stick and did not hold: then the plugin says to leave Z-Wave off and run the restore again, and does not wait.

## Finding the stick

The plugin reads which port the stick is on from Indigo's own Z-Wave settings, and only ever reads those settings, never changes them. If Indigo reaches its Z-Wave interface over the network rather than through a stick on the Mac, the plugin stops and says so. The **Serial port** setting overrides all of this, for the rare case where the plugin cannot find the stick itself.

## Reading twice

A backup reads the whole memory twice and compares the two reads byte for byte. A copy is only worth having if it is right, and two reads that agree show nothing moved while it was being taken. On a 700 or 800 series stick, the plugin also switches the radio off for the whole visit, so the network cannot change the memory while it is being read, and resets the stick at the end, which switches the radio back on.

## Checking a restore

After writing a backup into the stick, the plugin reads the stick again and compares it with the backup, and checks the Home ID. On a 500 series stick the two must match byte for byte. A 700 or 800 series stick adds records of its own to spare memory whenever it restarts, so there the plugin checks that everything the backup holds is in the stick and that the list of devices is the same, and allows for those new records.

## Why it is so strict about the model and software

A backup is a raw copy of the memory, and the way that memory is laid out changed between software versions. An original Aeotec Gen5 and a Gen5+ run different versions and are not interchangeable, and 700 and 800 series sticks differ between releases of their Z-Wave software too. So before it writes anything, the plugin reads the stick and refuses unless the model and software version match the backup's, and the Home ID matches as well, unless you have said it is a replacement stick.

## The reminder when the network changes

The plugin watches Indigo's device list. When a Z-Wave device is added or removed, the stick's contents have very probably changed too, so the plugin gives one warning in the Event Log and shows **Network changed since backup** on the device. It errs towards warning, because a needless warning costs a glance at the log, while a missed one leaves you with an out-of-date backup. Taking a new backup clears it.

## One job at a time

The plugin runs one backup, verify or restore at a time. A job counts as finished once Z-Wave is back on, or at once after a restore that did not hold, so if you try to start another before then, the plugin says one is already running. If Z-Wave stays off for half an hour after a job, the plugin gives a warning that nothing is controlling your devices, and stops waiting.

## What goes in the log

The plugin writes each step to the Indigo Event Log in plain words, including the stick's model, Home ID and software version, the size of its memory, what was checked, and what it wants you to do next. If a job stops, the log names the step it stopped at. Those lines are the useful part to post if you ask for help.
