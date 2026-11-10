#!/usr/bin/env bash
# Sirgsm VPN Panel — one-line installer (Ubuntu/Debian)
# Sirgsm.ir
#
# Install (one line):
#   curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/main/install.sh | bash
# Or from a local clone:
#   bash install.sh
#
# What it does automatically:
#   - Installs all requirements (Python, Flask, qrcode, nginx, certbot, strongswan, xl2tpd, wireguard-tools)
#   - Copies panel + bot to /opt/sirgsm-panel
#   - Creates env + systemd services (panel, bot)
#   - Opens firewall ports (panel, L2TP/IPsec)
#   - Gets Let's Encrypt SSL for the panel domain (if DOMAIN is set)
#   - Enables + starts services
set -euo pipefail

echo "=== Sirgsm VPN Panel installer ==="

# --- Config (override via env) ---
DOMAIN="${DOMAIN:-nhv.3tayesh.ir}"
PANEL_PORT="${PANEL_PORT:-2053}"
SSL_EMAIL="${SSL_EMAIL:-}"
ADMIN_PASS="${ADMIN_PASS:-}"
SECRET_PATH="${SECRET_PATH:-}"

# --- 1) System deps (all requirements, automatic) ---
echo "[1/7] Installing system packages..."
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3 python3-pip python3-flask \
  nginx certbot python3-certbot-nginx \
  strongswan strongswan-starter xl2tpd \
  wireguard-tools curl openssl ufw ca-certificates

echo "[2/7] Installing Python deps..."
pip3 install --break-system-packages 'qrcode[pil]' Pillow Flask || true

# --- 3) Copy files ---
echo "[3/7] Copying panel files..."
mkdir -p /opt/sirgsm-panel
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
if [ -f "$SCRIPT_DIR/app.py" ]; then
  cp "$SCRIPT_DIR/app.py" "$SCRIPT_DIR/bot.py" /opt/sirgsm-panel/
  [ -d "$SCRIPT_DIR/warp" ] && cp -r "$SCRIPT_DIR/warp" /opt/sirgsm-panel/ || true
else
  echo "app.py not found next to install.sh — download the repo zip and run from there."
  exit 1
fi

# --- 4) Env (panel creds) ---
echo "[4/7] Configuring panel..."
if [ -z "$SECRET_PATH" ]; then
  SECRET_PATH="nhv-$(openssl rand -hex 8)"
fi
if [ -z "$ADMIN_PASS" ]; then
  ADMIN_PASS="$(openssl rand -base64 12 | tr -d '\n')"
fi
cat > /root/sirgsm-panel.env <<EOF
SIRGSM_SECRET_PATH=$SECRET_PATH
SIRGSM_ADMIN_PASS=$ADMIN_PASS
SIRGSM_PANEL_PORT=$PANEL_PORT
EOF
chmod 600 /root/sirgsm-panel.env
cat > /root/sirgsm-panel.txt <<EOF
PANEL_USER=admin
PANEL_PASS=$ADMIN_PASS
PANEL_PATH=$SECRET_PATH
PANEL_PORT=$PANEL_PORT
PANEL_URL=http://$DOMAIN:$PANEL_PORT/$SECRET_PATH/
EOF
chmod 600 /root/sirgsm-panel.txt
echo "Panel: http://$DOMAIN:$PANEL_PORT/$SECRET_PATH/ (admin / $ADMIN_PASS)"

# --- 5) Services ---
echo "[5/7] Creating services..."
cat > /etc/systemd/system/sirgsm-panel.service <<'EOF'
[Unit]
Description=Sirgsm VPN Panel (Custom)
After=network.target xray.service

[Service]
Type=simple
User=root
EnvironmentFile=/root/sirgsm-panel.env
ExecStart=/usr/bin/python3 /opt/sirgsm-panel/app.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/sirgsm-bot.service <<'EOF'
[Unit]
Description=Sirgsm VPN Telegram Bot
After=network.target sirgsm-panel.service

[Service]
Type=simple
User=root
EnvironmentFile=/root/sirgsm-bot.env
ExecStart=/usr/bin/python3 /opt/sirgsm-panel/bot.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Bot env (token comes from panel settings; env is fallback)
if [ ! -f /root/sirgsm-bot.env ]; then
  cat > /root/sirgsm-bot.env <<EOF
BOT_TOKEN=
BOT_ADMIN_ID=
PANEL_URL=http://127.0.0.1:$PANEL_PORT
PANEL_PATH=$SECRET_PATH
PANEL_USER=admin
PANEL_PASS=$ADMIN_PASS
EOF
  chmod 600 /root/sirgsm-bot.env
fi

systemctl daemon-reload
systemctl enable sirgsm-panel sirgsm-bot || true

# --- 6) Firewall ---
echo "[6/7] Firewall..."
ufw allow "$PANEL_PORT/tcp" comment 'Sirgsm Panel' || true
ufw allow 500/udp comment 'IPsec IKE' || true
ufw allow 4500/udp comment 'IPsec NAT-T' || true
ufw allow 1701/udp comment 'L2TP' || true
ufw allow 80/tcp comment 'HTTP (SSL)' || true
ufw --force enable || true

# --- 7) SSL (automatic) ---
echo "[7/7] SSL..."
if [ -n "$SSL_EMAIL" ] && [ -n "$DOMAIN" ]; then
  echo "Requesting Let's Encrypt cert for $DOMAIN..."
  certbot certonly --standalone --non-interactive --agree-tos -m "$SSL_EMAIL" -d "$DOMAIN" || \
  certbot certonly --nginx --non-interactive --agree-tos -m "$SSL_EMAIL" -d "$DOMAIN" || \
  echo "SSL failed (check DNS for $DOMAIN points to this server, port 80 free)."
else
  echo "SSL skipped (set SSL_EMAIL + DOMAIN to enable). You can also get it later from Panel > Settings > SSL."
fi

systemctl restart sirgsm-panel
sleep 2
systemctl status sirgsm-panel --no-pager | head -8
echo ""
echo "=== Done! ==="
echo "Panel: http://$DOMAIN:$PANEL_PORT/$SECRET_PATH/"
echo "Bot: set token in Panel > Settings > Telegram, then: systemctl restart sirgsm-bot"
echo "Sirgsm.ir"
