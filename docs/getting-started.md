---
title: Getting started
nav_order: 2
---

# Getting started

Installing takes a minute, and the first backup a few more.

## What you need

- Indigo 2025.2 or later.
- A 500, 700 or 800 series Z-Wave stick plugged into the Indigo Mac by USB and already working in Indigo.
- A few minutes when your Z-Wave devices can do without Indigo, because Z-Wave is switched off while the stick is read.

Nothing needs a password, an account or a key.

## 1. Install the plugin

1. Go to the [Releases page](https://github.com/Highsteads/ZWaveControllerBackup/releases/latest) and download `Z-Wave.Controller.Backup.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `Z-Wave Controller Backup.indigoPlugin`
3. Double-click `Z-Wave Controller Backup.indigoPlugin` — Indigo will install it automatically

Indigo asks whether to enable the plugin. Say yes.

## 2. Check the settings

Indigo opens the plugin's Configure window the first time. You can leave every box as it is. Backups then go to a folder called **Z-Wave Controller Backups** in `/Library/Application Support/Perceptive Automation/`, beside the Indigo folder, and the plugin finds the stick from Indigo's own Z-Wave settings.

Click **Save**. Save it before you use the plugin's menu, because the menu does not open while that window is still waiting. Every setting is explained on the [Settings](settings.md) page.

## 3. Add the device

The device is optional, but it shows at a glance when you last took a backup and whether it is still up to date.

1. In Indigo, choose **New Device**.
2. Set **Type** to **Z-Wave Controller Backup** and the model to **Z-Wave Controller**.
3. Click **Save**. It has no settings to fill in.

One of these is all you need. A second one shows an error and does nothing, and the Event Log says to delete it.

## 4. Take your first backup

1. Choose **Plugins → Z-Wave Controller Backup → Back Up Controller Now...** and click **Start**.
2. In the Indigo client choose **Interfaces → Z-Wave → Disable**. You can do this before or after clicking Start.
3. Watch the Event Log. When it says the backup is complete and asks you to switch Z-Wave back on, choose **Interfaces → Z-Wave → Enable**.

The [Taking a backup](backing-up.md) page goes through each step in more detail.

## 5. Check it worked

The Event Log has a line starting **Backup complete**, with the name of the file it saved, followed by **Z-Wave is back on**. The Z-Wave Controller device shows something like **Backed up 13 Sep 12:07, current**, along with the stick's model and the number of devices it holds.

If you want to be sure the copy matches the stick, choose **Plugins → Z-Wave Controller Backup → Verify Last Backup**, and switch Z-Wave off and on again the same way.

If something does not go to plan, the [When something goes wrong](troubleshooting.md) page goes through the usual causes.
