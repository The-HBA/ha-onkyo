# Changelog

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
