# Getting started

## Before you begin

- An Onkyo, Pioneer or Integra receiver with a network connection.
- Network control turned on in the receiver's menu.
- Home Assistant 2026.9 or newer, on the same network as the receiver.
- The core Onkyo integration removed for the same receiver. The receiver allows one connection per computer, so two integrations would push each other off.

## Install

1. In HACS, open the menu, choose Custom repositories, and add `https://github.com/The-HBA/ha-onkyo` as an Integration.
2. Install Onkyo Remote and restart Home Assistant.

## Set up

Go to Settings, Devices and services, Add integration, and pick Onkyo Remote. If your receiver is found on the network, it shows up as a discovered device and you only confirm it.

| Field | Meaning |
|---|---|
| Host | The receiver's address, for example `192.168.1.50`. Give the receiver a fixed address in your router. |
| Port | The eISCP port. Leave it at 60128 unless you changed it. |

The setup reads the receiver's identity first. If it cannot, it shows an error and creates nothing.

## Options

Open the integration and press Configure.

| Option | Meaning |
|---|---|
| Maximum volume | The volume that counts as 100 percent on the slider. Home Assistant never sets the receiver above it. |
| Put the volume back after power on | Some receivers jump to a loud level at power on. When on, the volume from before standby is set again. |

Inputs and listening modes are renamed, hidden and ordered in the sheet that opens from Edit on the card, or from Names on the sidebar page.

## Change the address

Open the integration, use the three-dot menu on the entry, and choose Reconfigure. The new address must belong to the same receiver.

## Remove

Open Settings, Devices and services, pick Onkyo Remote, open the three-dot menu on the entry, and choose Delete. The entities, the device and the sidebar page go with it. When the last receiver is removed, the card resource and the sidebar page go too. Cards you placed on dashboards stay as empty cards; delete them yourself. Then remove the repository in HACS if you no longer want it.
