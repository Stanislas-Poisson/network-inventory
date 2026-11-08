# Security Policy

## Reporting vulnerabilities

| Channel | Description | Contact / Link |
| :--- | :--- | :--- |
| **Private report** | Preferred channel for sensitive reports. | [Report a vulnerability][advisories] |
| **Issues** | Non-sensitive problems. | [Open an issue][issues] |
| **Email** | Alternative contact. | `security@the-white-rabbits.fr` |

Please **do not disclose a vulnerability publicly** until it has been reviewed and fixed.

---

## Supported versions

| Version | Supported |
| :--- | :--- |
| `main` | Yes |

There are no releases: only the latest commit of `main` receives fixes.

---

## Scope

- The project scans a local network and will serve a web interface on it. Report any way to reach that interface from outside the local network, to read or change the inventory without authentication, or to run a command through a scanned value (device name, MAC, host name).
- No device list and no router setting is stored in this repository. If you find something that looks like one, report it privately: it is a mistake.
- A missing feature or a wrong device type is not a vulnerability: open an issue.

[advisories]: https://github.com/Stanislas-Poisson/network-inventory/security/advisories/new
[issues]: https://github.com/Stanislas-Poisson/network-inventory/issues
