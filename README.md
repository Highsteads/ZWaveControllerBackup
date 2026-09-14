# Z-Wave Controller Backup

**Version:** 1.1.0 | **Author:** CliveS & Claude | **Platform:** Indigo 2025.2 or later, macOS

Takes a complete copy of your Z-Wave USB controller's memory, checks it, keeps it, and can put
it back. Two clicks and about two minutes, from inside Indigo, on the Mac it already runs on.

## Why

The stick that runs your Z-Wave network keeps the only copy of what that network is: the
Home ID, the list of devices, the routes between them. A stick can lose that list. When it
does, every device is still on the network and still bound to the same Home ID, but the stick
no longer knows any of them, and Indigo's only documented remedy is to exclude and include
every device again. mat on the Indigo forum had that happen to 106 of them.

With a copy of the stick's memory on disk the remedy is a two-minute restore. This plugin
makes that copy from inside Indigo, needing nothing but the stick you already have.

## What it does

- **Back Up Controller Now...** reads the whole of the controller's memory twice, checks the
  two reads match and that the image is sane, and saves it with a small file beside it that
  records which controller it came from and when.
- **Restore Controller...** writes an image back, then reads the controller again to prove the
  image took, before telling you to switch Z-Wave back on. It refuses an image from a
  different model, or from a stick running a different software version, because the memory
  layout differs between versions. An image going onto a replacement stick of the same model
  needs a tick to say so.
- **Verify Last Backup** reads the controller and compares it with the last image.
- **One device**, "Z-Wave Controller", shows what the controller is, when it was last backed
  up, and whether the network has changed since. Triggers and control pages can use it.
- **Show Plugin Info** puts the same summary in the Event Log without needing the device: the
  controller, its Home ID and software, how many nodes the last image holds, when it was taken,
  and whether the network has changed since.
- **A nudge when the network changes.** Adding or removing a Z-Wave device flags the last
  backup as stale in the Event Log and on the device, so you know to take a fresh one.

## What it needs from you

Indigo holds the stick open, so it has to let go while the stick is read. The plugin cannot do
that for you: there is no command for it. Each backup goes like this.

1. Plugins > Z-Wave Controller Backup > Back Up Controller Now..., press Start.
2. In the Indigo client choose Interfaces > Z-Wave > Disable. The plugin notices within a
   couple of seconds and starts. Either order works.
3. Watch the Event Log. When it says the backup is complete, choose Interfaces > Z-Wave >
   Enable. Z-Wave is off for about two minutes in all.

Because of that, backups are not automatic. Take one after any change to the network, which
is when the stick's contents change. The plugin reminds you.

## Which controllers

Any 500, 700 or 800 series Z-Wave stick plugged into the Indigo Mac. 500 series: the Aeotec
Z-Stick Gen5 and Gen5+, the Z-Wave.me UZB, the HomeSeer SmartStick+, the Zooz ZST10 500 and
similar. 700 and 800 series: the Zooz ZST10 700 and ZST39, the Aeotec Z-Stick 7 and Z-Stick
10 Pro, the Silicon Labs UZB-7 and similar. The plugin finds the port from Indigo's own Z-Wave
settings, so there is nothing to configure, and works out which generation it is talking to.

The 700 and 800 series keep their memory as a small filesystem rather than a flat block, and
are read and written through a different Serial API command. Two things follow, both explained
in the Event Log when they happen: the stick is reset at the end of every visit (that is the
documented way to leave its memory tidy, and Indigo reconnects to it as normal), and a restore
does not need the unplug-and-replug a 500-series stick needs. A backup takes about twenty
seconds.

Sticks connected over the network rather than USB are out.

## The one rule about restoring

An image only goes back onto the same stick, or another stick of the same model running the
same software version. It is a raw copy, and the layout of the memory changed between
Aeotec's software versions (an original Gen5 on 1.01 and a Gen5+ on 1.02 are not
interchangeable), and between the Silicon Labs SDK versions a 700 or 800 series stick runs.
The plugin checks this and refuses otherwise.

Moving a network onto a different generation of stick (500 to 700, 700 to 800) is a
conversion, not a raw restore, and is a job for zwave-js: its `nvmedit convert` tool, or the
non-raw Restore NVM in Z-Wave JS UI, takes exactly the `.bin` this plugin writes. On a 500
series stick that route needs the newer Gen5 software first; mat's forum write-up (topic
29135) covers it. Two sticks holding the same Home ID must never be plugged in at the same
time, with or without software driving them.

## Tested

Live on the author's own system on 13 September 2026: an Aeotec Z-Stick Gen5 on firmware 1.01
running a network of thirty nodes under Indigo 2025.2 on macOS. Backup took 73 seconds for its
two full reads. Verify matched byte for byte. A restore of that image back onto the stick, with
the unplug and replug, read back byte for byte with the Home ID and all thirty nodes intact,
Z-Wave came back and the devices answered.

One thing seen on the way, and now explained in the Event Log when it happens: the Gen5 will not
accept a write to the last 16 bytes of its memory. Those bytes are blank in every image of it,
so the plugin reads them back instead of forcing the write, confirms they already match, and
carries on. It is expected, not a fault.

700 and 800 series, live on 14 September 2026 on a second system: a Zooz ZST39 LR (800 series,
Z-Wave 7.24, ten nodes), an Aeotec Z-Stick 10 Pro (800 series, Z-Wave 7.23, its Z-Wave side;
the Zigbee side is a separate port the plugin ignores) and a Silicon Labs 700 series stick
(Z-Wave 7.17, 108 node ids) running Indigo 2025.2's network. Backups matched a Z-Wave JS UI
backup of the same stick byte for byte, on both of the Serial API commands the plugin uses. A
restore of an older image onto the ZST39 brought back its older node table, and a restore of
the current image put it back; the Z-Stick 10 Pro went through backup, verify, restore and
verify the same way; each restore verified by read-back.

Two things learnt there, and now built in: a 700/800 stick answers the very last write of a
restore with "end of file" and does not perform it (zwave-js sees the same; those bytes hold
nothing any of its files refer to), and it must not be asked to write those bytes in smaller
pieces, because a one-byte write there hung the ZST39 outright until it was replugged. The
plugin leaves that tail alone and says so. And after any reset the stick may append a few
bytes of its own housekeeping into free space, so a 700/800 read-back is compared everywhere
the image holds data rather than byte for byte, and the node table and Home ID are checked
too.

## Installation

1. Download the plugin:
   https://github.com/Highsteads/ZWaveControllerBackup/releases/latest/download/Z-Wave.Controller.Backup.indigoPlugin.zip
2. Unzip the downloaded file. You will get `Z-Wave Controller Backup.indigoPlugin`.
3. Double-click `Z-Wave Controller Backup.indigoPlugin`. Indigo will install it automatically.
4. Optionally create one "Z-Wave Controller" device (Devices, New, Type: Z-Wave Controller
   Backup). It needs no settings.

Images go to `Z-Wave Controller Backups` next to the Indigo folder unless you choose another
folder in the plugin's Configure dialog. They are 256 KB each for a 500 series stick and about
40 to 48 KB for a 700 or 800 series one, so keep them all, and let your normal backup carry the
folder off the Mac.

## If something goes wrong

Please report it in the Indigo forum thread rather than opening a GitHub issue:
https://forums.indigodomo.com/viewtopic.php?t=29135

The Event Log lines from the plugin are the useful part — they name the controller, the sizes
and exactly which step stopped. GitHub issues are turned off on this repository on purpose, so
the thread is the one place to look.

## Credits

The 700 and 800 series support was contributed by **Autolog**, tested on a ZST39, a Z-Stick 10 Pro
and the 700 series stick running a second Indigo system, with Claude Opus 5 at the keyboard.

mat's forum write-up of recovering a Gen5 that had lost its node table is what started this,
and his zwave-js scripts remain the fallback route for anyone without the plugin. The Serial
API details were checked against the zwave-js project's source (MIT). Nothing from either is
bundled here; the plugin is plain Python with no dependencies.

## What's new

**1.1.0** (14-Sep-2026) — 700 and 800 series sticks (Zooz ZST10 700 and ZST39, Aeotec Z-Stick 7
and Z-Stick 10 Pro, UZB-7 and similar): backup, restore and verify through the NVM3 commands
those sticks use, tested live on a ZST39 LR and a 700 series stick against Z-Wave JS UI. No
unplug needed on this generation; the closing reset does the job. Node ids are read correctly
from a stick that zwave-js has left in 16-bit mode. Show Plugin Info and the device report the
full SDK version. Two small fixes found on the way: a backup folder pasted with quotes around it
is cleaned up rather than landing the images inside the plugin bundle, and the Home ID check
looks at every network Indigo's settings remember instead of the first one it finds.

**1.0.2** (13-Sep-2026) — Show Plugin Info now reports the controller itself: model, Home ID,
software version, how many nodes the last image holds, which file it is, and whether the network
has changed since. It previously showed only the folder, port and backup time.

**1.0.1** (13-Sep-2026) — The Event Log now explains, in plain words, a controller refusing to write the
end of its memory during a restore, and why that is not a fault. README records the live test.

**1.0.0** (13-Sep-2026) — First release. Backup with double read and checks, guarded restore
with read-back verification, verify, one controller device, and the stale-backup nudge.
500-series sticks on the Indigo Mac.

## Authors & licence

Vibed into existence by **CliveS**, who knew what he wanted, argued until he got it, and tested it on a real house. Typed at inhuman speed by **Claude** (Anthropic), who mostly did as it was told. 700 and 800 series by **Autolog** and Claude, on a second real house.

© 2026 CliveS · [MIT licence](LICENSE) — copy it, fork it, bend it, break it, fix it, ship it. If it breaks, you get to keep both pieces.
