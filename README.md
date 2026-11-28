# Onkyo Remote (ha-onkyo)

A Home Assistant integration for Onkyo network receivers (and Pioneer and Integra models that use the same eISCP protocol). It is local only: it talks to the receiver on your network, with no cloud and no accounts.

Status: 0.1.0-beta. Built and checked on an Onkyo TX-RZ50. Other models are meant to work (the integration reads what the receiver supports) and are not tested yet.

Parts of this project were written with AI-assisted tooling.

## What works in 0.1.0-beta

| Area | What you get |
|---|---|
| Media players | Main zone, zone 2 and zone 3: power, volume (percent, dB as an attribute), mute, source, listening mode |
| Sources and modes | The receiver's own names, one entry each, only what the signal allows |
| Sound | Bass, treble, subwoofer and centre level, dialog and vocal enhancement, late night, A/V sync, Music Optimizer, sleep timer |
| Dirac Live | Choose a filled slot, or off |
| Sensors | Audio and video input information |
| Remote | On-screen menu keys through the `remote` entity |
| Actions | `send_raw` for any eISCP command, `survey` to record what your model answers |
| Repairs | A notice when the core Onkyo integration uses the same receiver |
| Options | Rename and hide inputs and modes, order the inputs, maximum volume, restore volume after power on |
| Remote card | One card with Main, Modes, Remote, Playing and Zones tabs, and a sidebar page "Onkyo" for the receiver settings |
| Diagnostics | Capabilities and values, with address and identifiers hidden |

The tabs a model cannot use are hidden. Controls the model does not support are hidden too.

## The card

Edit a dashboard, add a card, and pick Onkyo Remote. Choose the receiver in the card editor. The sidebar page opens the same card full screen with the rename tools for administrators.

## Install

1. In HACS, open the menu, choose Custom repositories, and add `https://github.com/The-HBA/ha-onkyo` as an Integration.
2. Install Onkyo Remote and restart Home Assistant.
3. Go to Settings, Devices and services, Add integration, and pick Onkyo Remote. Enter the receiver's address.

Home Assistant 2026.9 or newer is needed. Network control must be on in the receiver's menu.

## One connection per computer

The receiver closes its older connection when the same computer opens a new one. The core Onkyo integration and this one would push each other off, so remove the core Onkyo entry for the same receiver before you add this one.

## Names

Open the integration, choose Configure, and pick what to change.

| Step | Effect |
|---|---|
| Rename or hide inputs | Pick an input, give it a name, or hide it from the source list |
| Order of inputs | Pick the inputs in the order you want them listed |
| Rename or hide listening modes | Same for modes. Names must be unique |
| Volume | The maximum volume is 100 percent on the slider. Optionally put the volume back after power on |

An empty name goes back to the receiver's own name. Hidden items stay available to the `send_raw` action.

## Develop

```bash
uv venv --python 3.14 && uv pip install -r requirements_test_ha.txt
.venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/mypy
# The library and tool tests need real local sockets, so run them without the Home Assistant plugin.
.venv/bin/pytest -q -p no:homeassistant tests/lib tests/tools tests/test_boundary.py
.venv/bin/pytest -q tests/ha
```

## License

MIT. See [LICENSE](LICENSE).
