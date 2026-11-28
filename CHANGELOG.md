# Changelog

## 0.1.2-beta

The sidebar page gets the receiver's advanced settings, the ones the removed Web Setup page held.

- New "Advanced settings" section: input assign (audio source, HDMI, digital and analog jacks, input skip), input names and start volume, per-input audio and HDMI, TV out and HDMI (CEC, ARC), speaker levels, distances and crossovers, equalizer, power and volume limits, zones, and smaller options.
- Speaker levels, distances and crossovers are part of the Dirac calibration: the first change to a record saves its old values, and Restore puts them back (Keep forgets them).
- Speaker layout and network are shown and never changed. Video assign is shown read only, because the TX-RZ50 ignores changes to it.
- Changes need an administrator. A model that does not answer these settings shows no section.
- New websocket commands `onkyo_eiscp/ci_info`, `ci_read`, `ci_set` and `ci_restore`.

## 0.1.1-beta

Fixes from the first check on a real Home Assistant.

- Configure now holds only the volume settings. Rename, hide and order inputs and modes in the sheet (Edit on the card, or Names on the sidebar page); the one-by-one steps are gone. Names you set before stay.
- The sidebar page puts Names and Receiver under the card on wide screens, so the two columns end at about the same height.
- The sidebar page shows a message with a Reload button when a file fails to load, instead of a blank page.
- The TX-RZ50 no longer shows the Audio and Video keys on the Remote tab; they do nothing on that model.

## 0.1.0-beta

The first version with the full feature set. It has been checked against a simulated TX-RZ50 and in a fake Home Assistant page, not yet on a live Home Assistant.

- Entities for the main zone: selects (late night and others), numbers (tone, levels, sleep timer, A/V sync), switches (Music Optimizer), Dirac Live slot, audio and video sensors, and a `remote` entity for the on-screen menu keys.
- Zone 2 and zone 3 media players, with source lists that include "follow the main zone".
- Actions `send_raw` and `survey`, and a repair when the core Onkyo integration uses the same receiver.
- Remote card with Main, Modes, Remote, Playing and Zones tabs, and the sidebar page "Onkyo" with receiver settings and rename tools.
- Remote keys come from what the receiver reports, so a model without a Home key does not show one.
- The settings link on the Playing tab shows to administrators only.

## 0.0.2

- Renamed to Onkyo Remote and switched to the Onkyo logo. The integration ID `onkyo_eiscp` is unchanged, so nothing needs to be set up again.

## 0.0.1

First test release. It has one media player and the options to name things as you like.

- Config flow: add a receiver by host, or confirm one found by SSDP. Change the address later with Reconfigure.
- Main zone media player: power, volume (shown as a percentage, with the dB value as an attribute), mute, source and listening mode.
- Source list: the receiver's own input names, one entry each, with no alias chains.
- Listening mode list: one clean name per mode, limited to the modes the current signal allows.
- Options: rename and hide inputs and listening modes, order the inputs, set a maximum volume, and put the volume back after power on.
- Diagnostics with the address and identifiers hidden.

Not in this release: zones 2 and 3, tone and level controls, Dirac Live, sensors and the remote card.
