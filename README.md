# Z-Wave Controller Backup

**Back up the memory of your Z-Wave USB stick from inside Indigo, and put it back if the stick ever loses your network.**

**Version:** 1.2.1 | **Author:** CliveS, Autolog & Claude | **Needs:** Indigo 2025.2 or later, and a Z-Wave USB stick plugged into the Indigo Mac

**[Read the full guide](https://highsteads.github.io/ZWaveControllerBackup/)** — setting up, backing up, restoring, what everything means, and what to do when something goes wrong.

---

## What it does

The Z-Wave stick keeps the only copy of your network: its Home ID, which every device on the network shares, the list of devices it knows, and the routes it uses to reach them. A stick can lose that list, and the usual remedy is then to exclude and include every device again. mat on the Indigo forum had that happen to 106 of them. This plugin keeps a copy of the stick's memory on the Mac, so the remedy is a restore that takes a few minutes instead.

- **Backs up the stick** by reading its whole memory twice, checking the two reads match, and saving the copy with a small file beside it that records which stick it came from and when.
- **Restores a backup** and then reads the stick again to prove the copy took, before it tells you to switch Z-Wave back on. It refuses a copy from a different model, or from a stick running a different software version.
- **Verifies the last backup** by reading the stick and comparing it with the copy.
- **Gives you one device**, Z-Wave Controller, which shows what the stick is, when it was last backed up, and whether the network has changed since.
- **Reminds you** when you add or remove a Z-Wave device in Indigo, because the last backup is then out of date.

Indigo has to let go of the stick while it is read, and a plugin has no way to make it, so each backup needs two clicks from you: switch Z-Wave off, and switch it back on when the Event Log says so. For a 500 series stick, Z-Wave is off for about two minutes in all.

## Which sticks it works with

Any 500, 700 or 800 series Z-Wave stick plugged into the Indigo Mac by USB — for example the Aeotec Z-Stick Gen5, Gen5+, Z-Stick 7 and Z-Stick 10 Pro, the Zooz ZST10 and ZST39, the Z-Wave.me UZB, the HomeSeer SmartStick+ and the Silicon Labs UZB-7. The plugin finds the stick from Indigo's own Z-Wave settings and works out which generation it is.

I have run it on my own Aeotec Gen5 with thirty devices, and Autolog on a Zooz ZST39 LR, an Aeotec Z-Stick 10 Pro and a Silicon Labs 700 series stick. A Z-Wave interface reached over the network, rather than a stick on the Mac, is not supported.

## Installing

1. Go to the [Releases page](https://github.com/Highsteads/ZWaveControllerBackup/releases/latest) and download `Z-Wave.Controller.Backup.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `Z-Wave Controller Backup.indigoPlugin`
3. Double-click `Z-Wave Controller Backup.indigoPlugin` — Indigo will install it automatically

## Setting it up

1. When Indigo opens **Configure**, leave everything as it is and click **Save**. Backups go to a folder called **Z-Wave Controller Backups** beside the Indigo folder.
2. If you want the device, create a **New Device**, choose **Z-Wave Controller Backup** and the model **Z-Wave Controller**, and click **Save**. It has no settings.
3. Choose **Plugins → Z-Wave Controller Backup → Back Up Controller Now...** and click **Start**, then choose **Interfaces → Z-Wave → Disable**. When the Event Log says the backup is complete, choose **Interfaces → Z-Wave → Enable**.

Take a fresh backup whenever you add or remove a device. Before you ever restore, read the [restoring page](https://highsteads.github.io/ZWaveControllerBackup/restoring.html) of the guide all the way through.

## What's new

**v1.2.1** — A restore now refuses a backup file that no longer matches the checksum recorded when it was saved, so a damaged file can never reach the stick, and **Restore verified** says that checksum was confirmed. If something went wrong as the plugin opened the stick, it now lets go of the port instead of keeping it from Indigo.

**v1.2.0** — When a restore does not hold, the plugin now tells you to leave Z-Wave off and stops there, instead of also asking you to switch it back on. The device shows **Action required: run Restore again**, and you can run the restore again straight away.

**v1.1.0** — 700 and 800 series sticks, written by **Autolog**: backup, restore and verify, tested on a Zooz ZST39 LR, an Aeotec Z-Stick 10 Pro and a Silicon Labs 700 series stick. These sticks need no unplugging during a restore. Show Plugin Info and the device show the stick's full software version, and a backup folder pasted with quotes around it is cleaned up.

Every version is listed in the [version history](https://highsteads.github.io/ZWaveControllerBackup/changelog.html).

## Reporting a problem

Please post in [this thread](https://forums.indigodomo.com/viewtopic.php?t=29135) on the Indigo forum rather than on GitHub, where issues are turned off. The Event Log lines from the plugin are the useful part, because they name the stick and the step that stopped.

## Credits

The 700 and 800 series support was written by **Autolog** and Claude, and tested by Autolog on a second real house. mat's forum write-up of recovering an Aeotec Gen5 that had lost its list of devices is what started this plugin, and his zwave-js scripts remain a route for anyone without it. The way the plugin talks to the stick was checked against the zwave-js project's source, and nothing from either is bundled here.

## Authors & licence

Vibed into existence by **CliveS**, who knew what he wanted, argued until he got it, and tested it on a real house. Typed at inhuman speed by **Claude** (Anthropic), who mostly did as it was told.

© 2026 CliveS · [MIT licence](LICENSE) — copy it, fork it, bend it, break it, fix it, ship it. If it breaks, you get to keep both pieces.
