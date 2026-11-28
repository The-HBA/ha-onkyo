# Troubleshooting

## Known limits

- One connection per computer: the receiver closes its older connection when the same computer opens a new one. Do not run the core Onkyo integration, or another eISCP tool, from the same Home Assistant at the same time.
- Dirac Live: you can choose a slot (or none). Measurement and filters are not available.
- Some advanced settings are shown but not changed: speaker layout, network, and (on the TX-RZ50) video assign, which the receiver ignores.
- Calibration restore values last until Home Assistant restarts or the integration reloads.
- Other models than the TX-RZ50 are untested. Local only: no cloud, accounts, firmware updates or music streaming.

## Cannot connect

- Check the address, and that Network Control is on in the receiver's menu.
- Check that the receiver is on the same network, or that port 60128 is open between the networks.
- In standby some receivers close the network. Turn on the network standby option in the receiver menu if it has one.

## Repair: core Onkyo uses the same receiver

Remove the core Onkyo entry for this receiver (Settings, Devices and services), then reload Onkyo Remote.

## Entities are unavailable

The connection dropped. The integration reconnects by itself. Check the log for "connection to ... lost" and "is back".

## Advanced settings say the receiver did not answer

Switch the receiver on and press Try again. A model that never answers these settings has no such section.

## Collect information for an issue

1. Turn on debug logging for `custom_components.onkyo_eiscp` (Settings, Devices and services, Onkyo Remote, Enable debug logging).
2. Download the diagnostics from the device page.
3. For a model that is missing something, run the `survey` action in Developer tools, Actions, and attach the result. Addresses and the MAC are removed from it.
