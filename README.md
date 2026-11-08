# network-inventory

A home network inventory that is the source of truth: a list of devices by type, category, IP and name, compared with what is really on the network, and exported to configure a router again without searching everything.

> **Status: design.** Nothing is coded yet. The architecture below is a proposal.

## The idea

- **The inventory is the reference.** The router only applies it. When the router changes, its settings are redone from the inventory.
- **Compare with reality.** A LAN scan is matched with the inventory to spot a misclassified device (a new network card means a new MAC and a new IP) or an unknown one.
- **The real inventory stays private.** This repository holds the code only, never your list of devices.

## Planned parts

| Part | Role |
| :--- | :--- |
| Inventory | One `inventory.yaml` file. A device has a name, a type, a category and a list of interfaces (MAC, expected IP). |
| Scanner | Python script (`arp-scan` or `nmap -sn`), history of the observations in SQLite. |
| Comparator | Classifies each device: matching, different IP, unknown MAC, missing. |
| Web interface | Light application: views by type, category, IP and name, and a page of the differences. Local network only. |
| Export | A table (MAC, IP, name, category) to enter in the router, then an optional automatic push. |

It is meant to run on a Raspberry Pi 3, with no database server.

## Requirements

- The scan needs to see the local network. On WSL2 this means `networkingMode=mirrored` in `.wslconfig`: in the default NAT mode, only the virtual network is visible.
- `arp-scan` and `nmap`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). To report a vulnerability, see [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
