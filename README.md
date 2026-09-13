# Z-Wave Controller Backup

**Version:** 1.0.1 | **Author:** CliveS & Claude | **Platform:** Indigo 2025.2 or later, macOS

Takes a complete copy of your Z-Wave USB controller's memory, checks it, keeps it, and can put
it back. Two clicks and about two minutes, from inside Indigo, on the Mac it already runs on.

## Why

The stick that runs your Z-Wave network keeps the only copy of what that network is: the
Home ID, the list of devices, the routes between them. A 500-series stick can lose that list.
When it does, every device is still on the network and still bound to the same Home ID, but
the stick no longer knows any of them, and Indigo's only documented remedy is to exclude and
include every device again. mat on the Indigo forum had that happen to 106 of them.

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

Any 500-series Z-Wave stick plugged into the Indigo Mac: the Aeotec Z-Stick Gen5 and Gen5+,
the Z-Wave.me UZB, the HomeSeer SmartStick+, the Zooz ZST10 500 and similar. The plugin finds
the port from Indigo's own Z-Wave settings, so there is nothing to configure.

Not yet: 700 and 800 series sticks (Z-Stick 7, Z-Stick 10 Pro, ZST39, ZWA-2). Their memory is
read a different way and the author has none to test against. The plugin recognises one and
says so rather than guessing. Sticks connected over the network rather than USB are also out.

## The one rule about restoring

An image only goes back onto the same stick, or another stick of the same model running the
same software version. It is a raw copy, and the layout of the memory changed between
Aeotec's software versions (an original Gen5 on 1.01 and a Gen5+ on 1.02 are not
interchangeable). The plugin checks this and refuses otherwise. Converting an image for a
different generation of stick is a job for zwave-js, and needs the newer Gen5 software
first; mat's forum write-up (topic 29135) covers that route.

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

## Installation

1. Go to the Releases page and download `Z-Wave.Controller.Backup.indigoPlugin.zip`.
2. Unzip the downloaded file. You will get `Z-Wave Controller Backup.indigoPlugin`.
3. Double-click `Z-Wave Controller Backup.indigoPlugin`. Indigo will install it automatically.
4. Optionally create one "Z-Wave Controller" device (Devices, New, Type: Z-Wave Controller
   Backup). It needs no settings.

Images go to `Z-Wave Controller Backups` next to the Indigo folder unless you choose another
folder in the plugin's Configure dialog. They are about 256 KB each, so keep them all, and
let your normal backup carry the folder off the Mac.

## Credits

mat's forum write-up of recovering a Gen5 that had lost its node table is what started this,
and his zwave-js scripts remain the fallback route for anyone without the plugin. The Serial
API details were checked against the zwave-js project's source (MIT). Nothing from either is
bundled here; the plugin is plain Python with no dependencies.

## What's new

**1.0.1** (13-Sep-2026) — The Event Log now explains, in plain words, a controller refusing to write the
end of its memory during a restore, and why that is not a fault. README records the live test.

**1.0.0** (13-Sep-2026) — First release. Backup with double read and checks, guarded restore
with read-back verification, verify, one controller device, and the stale-backup nudge.
500-series sticks on the Indigo Mac.

## Authors & licence

Vibed into existence by **CliveS**, who knew what he wanted, argued until he got it, and tested it on a real house. Typed at inhuman speed by **Claude** (Anthropic), who mostly did as it was told.

© 2026 CliveS · [MIT licence](LICENSE) — copy it, fork it, bend it, break it, fix it, ship it. If it breaks, you get to keep both pieces.
