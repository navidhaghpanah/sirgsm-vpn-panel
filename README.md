# Sirgsm VPN Panel

Custom VPN management panel built from scratch (Flask + SQLite + Xray-core).

**Sponsor: [Sirgsm.ir](https://sirgsm.ir) — Navid Haghbayan**

## Features

- **4 protocols**: VLESS, Trojan, Shadowsocks 2022, VMess
- **Transports per inbound** (most-used types, switchable in Settings):
  - VLESS: Reality+TCP, Reality+gRPC, TLS+WebSocket, TLS+gRPC, TLS+TCP, TCP, WebSocket
  - Trojan: Reality+TCP, TLS+WebSocket, TLS+gRPC, TLS+TCP, TCP
  - VMess: Reality+TCP, TLS+WebSocket, TLS+gRPC, TCP, WebSocket
  - Shadowsocks: TCP/UDP (2022-blake3-aes-128-gcm)
- **User management**: expiry (days) + traffic limit (GB) + concurrent IP limit, online users, bulk actions
- **QR code** for links & subscription
- **Subscription landing page**: opening the sub link in a browser shows account details (usage, expiry, links, QR); proxy clients get plain-text links automatically (`/sub/<token>/raw` forces raw)
- **Server status**: CPU load, RAM, disk, uptime, network RX/TX totals + rates, per-interface stats, VPN traffic totals
- **Warp outbound** (Cloudflare WARP via WireGuard) for YouTube / Google / OpenAI / Telegram + routing rules with presets
- **L2TP / IKEv2 (IPsec)**: PSK + per-user PPP accounts, managed from Settings
- **SSL**: one-click Let's Encrypt for the panel domain (Settings > SSL)
- **Telegram bot** (`bot.py`): `/add /list /links /status /l2tp /version /del /reset /enable /disable` — token & admin ID are set in Panel Settings
- **Settings in panel**: domain, port, password, bot, SSL, transports, landing page, L2TP, update repo
- **Update**: check GitHub for new releases and update in one click (Settings > Update)
- **Persian RTL UI**, secret URL path, SIP Gateway (Asterisk) monitoring only (never touched)

## Install (one line)

```bash
curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/main/install.sh | bash
```

Or from a local clone:

```bash
git clone https://github.com/<owner>/<repo>.git && cd <repo>
sudo bash install.sh
```

The installer automatically installs **all requirements** (Python, Flask, qrcode, nginx, certbot, strongswan, xl2tpd, wireguard-tools), copies files, creates services, opens firewall ports, and gets **SSL** for the panel domain (set `SSL_EMAIL` + `DOMAIN` env vars, or get it later from Panel > Settings > SSL).

Panel: `http://YOUR_DOMAIN:2053/YOUR_SECRET_PATH/` — login `admin` / generated password (saved to `/root/sirgsm-panel.txt`).

## Warp setup

Register a free Cloudflare WARP account (e.g. via `wgcf`), then place:

- `/opt/sirgsm-panel/warp/account.toml`
- `/opt/sirgsm-panel/warp/profile.conf`
- `/opt/sirgsm-panel/warp/warp.json` — `{"reserved": [..]}` from the API `client_id`

The panel auto-loads Warp outbound and seeds routing rules for YouTube/Google/OpenAI/Telegram.

## Telegram bot

Set the token in **Panel > Settings > Telegram Bot** (from [@BotFather](https://t.me/BotFather)) and your numeric ID (from [@userinfobot](https://t.me/userinfobot)), then `systemctl restart sirgsm-bot`. Only the admin ID can use the bot.

## Landing page (template)

The sub landing page is a customizable template. In **Panel > Settings > Landing Page** you can change title, subtitle, footer, or paste a full custom HTML template. Placeholders: `{title} {subtitle} {footer} {email} {protocol} {used} {limit} {pct} {expiry} {ip_limit} {online} {status_fa} {status_cls} {links_html} {sub} {qr_link} {qr_sub}`.

## L2TP / IKEv2

In **Panel > Settings > L2TP**: enable, set PSK (secret), add users. Clients connect with L2TP/IPsec (PSK), server = panel domain, ports UDP 500/4500/1701.

## Update

In **Panel > Settings > Update**: set the GitHub repo (`owner/repo`), check for new releases, update in one click. The updater downloads the release zip and restarts panel + bot.

## Security notes

- Change `SIRGSM_SECRET_PATH` and `SIRGSM_ADMIN_PASS` before going live.
- Never commit real secrets (`.env`, `*.db`, `warp/`, `vpn-secrets*`) — see `.gitignore`.
- The panel never manages Asterisk/SIP — it only displays its status.

## License

MIT — see `LICENSE`.

---
Sponsor: **Sirgsm.ir — Navid Haghbayan**
