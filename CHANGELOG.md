# Changelog

## 0.0.1

First test release. It has one media player and the options to name things as you like.

- Config flow: add a receiver by host, or confirm one found by SSDP. Change the address later with Reconfigure.
- Main zone media player: power, volume (shown as a percentage, with the dB value as an attribute), mute, source and listening mode.
- Source list: the receiver's own input names, one entry each, with no alias chains.
- Listening mode list: one clean name per mode, limited to the modes the current signal allows.
- Options: rename and hide inputs and listening modes, order the inputs, set a maximum volume, and put the volume back after power on.
- Diagnostics with the address and identifiers hidden.

Not in this release: zones 2 and 3, tone and level controls, Dirac Live, sensors and the remote card.
