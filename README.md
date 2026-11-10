Sirgsm VPN Panel
Custom VPN management panel built from scratch (Flask + SQLite + Xray-core).

Sponsor: Sirgsm.ir — Navid Haghbayan

Features
4 protocols: VLESS Reality (443), Trojan Reality (8443), Shadowsocks 2022 (8388), VMess Reality (2096)
User management: create users with expiry (days) + traffic limit (GB) + concurrent IP limit
Online users & IP limit enforcement (via Xray API)
QR code for links & subscription
Subscription link (/sub/<token>)
Server status: CPU load, RAM, disk, uptime, network RX/TX totals + rates, per-interface stats
Total inbound/outbound traffic (VPN users + server network)
Warp outbound (Cloudflare WARP via WireGuard) for YouTube / Google / OpenAI / Telegram
Routing rules with presets (block ads, direct IR, Warp presets)
Telegram bot (
bot.py
): add/list/links/status/del/reset/enable/disable via chat
Persian RTL UI, secret URL path, SIP Gateway (Asterisk) monitoring only (never touched)
Requirements
Ubuntu/Debian VPS, Python 3.10+, Xray-core v26.x
python3-flask, qrcode[pil] (Pillow)
Install (quick)
Bash

# 1) Install Xray-core (see https://github.com/XTLS/Xray-core)
# 2) Copy files
sudo mkdir -p /opt/sirgsm-panel
sudo cp app.py bot.py /opt/sirgsm-panel/
sudo cp -r warp /opt/sirgsm-panel/   # Warp account (see below)

# 3) Env
sudo tee /root/sirgsm-panel.env <<'EOF'
SIRGSM_SECRET_PATH=change-me-random
SIRGSM_ADMIN_PASS=change-me-strong
SIRGSM_PANEL_PORT=2053
EOF
sudo chmod 600 /root/sirgsm-panel.env

# 4) Service
sudo tee /etc/systemd/system/sirgsm-panel.service <<'EOF'
[Unit]
Description=Sirgsm VPN Panel (Custom)
After=network.target xray.service

[Service]
Type=simple
User=root
EnvironmentFile=/root/sirgsm-panel.env
ExecStart=/usr/bin/python3 /opt/sirgsm-panel/app.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now sirgsm-panel
Panel: http://YOUR_DOMAIN:2053/YOUR_SECRET_PATH/ — login admin / your password.

Warp setup
Register a free Cloudflare WARP account (e.g. via wgcf), then place:

/opt/sirgsm-panel/warp/account.toml (wgcf account)
/opt/sirgsm-panel/warp/profile.conf (wgcf profile)
/opt/sirgsm-panel/warp/warp.json — {"reserved": [..]} from the API client_id
The panel auto-loads Warp outbound and seeds routing rules for YouTube/Google/OpenAI/Telegram.

Telegram bot
Create a bot via @BotFather → copy token.
Get your numeric ID via @userinfobot.
Configure /root/sirgsm-bot.env:
text

BOT_TOKEN=...
BOT_ADMIN_ID=...
PANEL_URL=http://127.0.0.1:2053
PANEL_PATH=your-secret-path
PANEL_USER=admin
PANEL_PASS=your-panel-password
sudo systemctl enable --now sirgsm-bot
Commands: /add <email> <vless|trojan|ss|vmess> <days> <gb> [ip], /list, /links <email>, /status, /del, /reset, /enable, /disable.

Security notes
Change SIRGSM_SECRET_PATH and SIRGSM_ADMIN_PASS before going live.
Never commit real secrets (.env, *.db, warp/, vpn-secrets*) — see 
.gitignore
.
The panel never manages Asterisk/SIP — it only displays its status.
License
MIT — see 
LICENSE
.

Sponsor: Sirgsm.ir

