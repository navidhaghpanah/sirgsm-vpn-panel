# Installation

## One-line install

```bash
curl -fsSL https://raw.githubusercontent.com/navidhaghpanah/sirgsm-vpn-panel/main/install.sh | bash
```

Or from a local clone:

```bash
git clone https://github.com/navidhaghpanah/sirgsm-vpn-panel.git && cd sirgsm-vpn-panel
sudo bash install.sh
```

## What the installer does

1. Installs **all requirements** automatically: Python 3, Flask, qrcode/Pillow, nginx, certbot, strongswan (+starter), xl2tpd, wireguard-tools, ufw.
2. Copies `app.py` + `bot.py` to `/opt/sirgsm-panel/`.
3. Creates `/root/sirgsm-panel.env` (secret path + admin password + port) and `/root/sirgsm-panel.txt` (creds).
4. Creates systemd services: `sirgsm-panel`, `sirgsm-bot`.
5. Opens firewall: panel port, L2TP/IPsec (UDP 500/4500/1701), port 80 (for SSL).
6. Gets **Let's Encrypt SSL** for the panel domain if `SSL_EMAIL` + `DOMAIN` are set (or later from Panel > Settings > SSL).
7. Starts the panel.

## Env overrides

```bash
DOMAIN=example.com PANEL_PORT=2053 SSL_EMAIL=you@example.com bash install.sh
```

## After install

- Panel: `http://YOUR_DOMAIN:2053/YOUR_SECRET_PATH/` — login `admin` / password from `/root/sirgsm-panel.txt`.
- Bot: set token in **Panel > Settings > Telegram Bot** (from [@BotFather](https://t.me/BotFather)), admin ID from [@userinfobot](https://t.me/userinfobot), then `systemctl restart sirgsm-bot`.
- Warp: place `account.toml` + `profile.conf` + `warp.json` in `/opt/sirgsm-panel/warp/` (see README).
- Xray: install Xray-core separately (see [XTLS/Xray-core](https://github.com/XTLS/Xray-core)), then restart the panel (it builds the config).

## Update

Panel > Settings > Update: set repo (`navidhaghpanah/sirgsm-vpn-panel`), check, update in one click.
