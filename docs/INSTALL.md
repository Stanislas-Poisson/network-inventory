# Installation on a Raspberry Pi

For Debian (Raspberry Pi OS Lite is enough). No Docker. The application runs as a normal
user and never as root.

## 1. Packages

```bash
sudo apt install python3 python3-venv arp-scan git
```

Python 3.11 or newer is required.

## 2. The program

```bash
git clone https://github.com/Stanislas-Poisson/network-inventory.git ~/network-inventory
cd ~/network-inventory
make install
```

`make install` creates `.venv` and installs the dependencies (Flask and segno).

## 3. The right to scan

`arp-scan` needs the `cap_net_raw` capability. Give it to the binary, so that the
application does not need root:

```bash
sudo setcap cap_net_raw+ep "$(command -v arp-scan)"
```

Check it with `.venv/bin/python -m network_inventory scan`. An update of the `arp-scan`
package removes the capability: run the command again.

## 4. The password

```bash
.venv/bin/python -m network_inventory set-password
```

The user name is `admin`, the password has at least 12 characters. Only its hash is stored,
next to the database. Without a password the interface refuses to listen on a network
address.

## 5. The service

```bash
mkdir -p ~/.config/network-inventory ~/.config/systemd/user ~/.local/share/network-inventory
cat > ~/.config/network-inventory/env <<ENV
# The LAN address of the Pi: never 0.0.0.0 unless you know why.
NETWORK_INVENTORY_HOST=192.168.1.20
NETWORK_INVENTORY_DB=$HOME/.local/share/network-inventory/inventory.db
ENV
cp deploy/network-inventory.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now network-inventory
loginctl enable-linger "$USER"
```

Replace the address with the one of your Pi. The shell writes the real path of your home
directory in the `env` file, because systemd does not expand `$HOME` there. The interface is
then on `http://<address>:8080`.

## Good to know

- The login uses HTTP Basic: the password travels in clear on the local network. Do not
  expose the port outside of it.
- The web server is the one that comes with Flask: fine for one person at home, not for
  the internet.
- Back up the database file, or use the Export page (the JSON backup holds the Wi-Fi keys in
  clear: store it encrypted).
- Scanning from WSL2 needs `networkingMode=mirrored` in `.wslconfig`, otherwise only the
  virtual network is visible.
