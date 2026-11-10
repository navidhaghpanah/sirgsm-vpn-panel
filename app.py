#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sirgsm VPN Panel - Custom unique VPN management panel (built from scratch)
VLESS Reality + Trojan Reality + Shadowsocks 2022 + VMess Reality | Users (traffic/expiry/IP-limit) | Routing + Warp | QR + Sub | Stats via Xray API
Persian RTL UI, dark unique design. No third-party panel code.
Sponsor: Sirgsm.ir — Navid Haghbayan
"""
import os
import io
import json
import sqlite3
import subprocess
import uuid
import base64
import time
import datetime
import secrets
import threading
import shutil
import urllib.request
import urllib.error
from functools import wraps

from flask import Flask, request, session, jsonify, redirect, abort, render_template_string, send_file
from werkzeug.security import generate_password_hash, check_password_hash

try:
    import qrcode
    from PIL import Image
    HAS_QR = True
except Exception:
    HAS_QR = False

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 7 * 24 * 3600

# ---------------- Config ----------------
PANEL_PORT = int(os.environ.get('SIRGSM_PANEL_PORT', os.environ.get('NHV_PANEL_PORT', '2053')))
SECRET_PATH = os.environ.get('SIRGSM_SECRET_PATH', os.environ.get('NHV_SECRET_PATH', 'sirgsm-panel'))
XRAY_CONFIG = '/usr/local/etc/xray/config.json'
XRAY_BIN = '/usr/local/bin/xray'
API_ADDR = '127.0.0.1:10000'
DB_PATH = '/opt/sirgsm-panel/panel.db'
WARP_DIR = '/opt/sirgsm-panel/warp'
DOMAIN = 'nhv.3tayesh.ir'
SERVER_IP = '185.204.169.123'
PANEL_NAME = 'Sirgsm VPN Panel'
SPONSOR = 'Sirgsm.ir — Navid Haghbayan'
PANEL_VERSION = '3.1.0'
GITHUB_REPO = 'sirgsm/sirgsm-vpn-panel'  # default, overridable in settings (update_repo)

# Load base secrets (VLESS existing + Trojan keys)
def load_kv(path):
    d = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    d[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return d

S1 = load_kv('/root/vpn-secrets.txt')   # UUID, PRIV, PUB, SHORTID, HYPASS(old)
S2 = load_kv('/root/vpn-secrets2.txt')  # TPRIV, TPUB, TPASS, TSHORT, SSP

VLESS_UUID = S1.get('UUID', 'cfd128ff-52b8-4246-acbf-e377e4b28e02')
VLESS_PRIV = S1.get('PRIV', 'kPHU-2k0HOBMDDxBKrsK33AGxt5da-64C7Tdhmn2Wl0')
VLESS_PUB = S1.get('PUB', 'M_ulMyWARRuYEOMsykxQ43-3MjX2-VUteYi9c4C5_28')
VLESS_SHORT = S1.get('SHORTID', '4aeb6052647dd786')

TROJAN_PRIV = S2.get('TPRIV', '')
TROJAN_PUB = S2.get('TPUB', '')
TROJAN_SHORT = S2.get('TSHORT', '')
SS_SERVER_KEY = S2.get('SS_SERVER_KEY', '')
VMESS_PRIV = S2.get('VMESS_PRIV', '')
VMESS_PUB = S2.get('VMESS_PUB', '')
VMESS_SHORT = S2.get('VMESS_SHORT', '')

def load_warp():
    """Load Warp WireGuard outbound from profile.conf + reserved. Returns dict or None."""
    try:
        priv = addr4 = addr6 = pub = endpoint = None
        with open(os.path.join(WARP_DIR, 'profile.conf')) as f:
            for line in f:
                line = line.strip()
                if line.startswith('PrivateKey'):
                    priv = line.split('=', 1)[1].strip()
                elif line.startswith('Address'):
                    parts = [p.strip() for p in line.split('=', 1)[1].split(',')]
                    for p in parts:
                        if p.startswith('172.'):
                            addr4 = p
                        elif ':' in p:
                            addr6 = p
                elif line.startswith('PublicKey'):
                    pub = line.split('=', 1)[1].strip()
                elif line.startswith('Endpoint'):
                    endpoint = line.split('=', 1)[1].strip()
        # Reserved from client_id (stored in warp.json if present, else decode default)
        reserved = [217, 243, 198]
        try:
            with open(os.path.join(WARP_DIR, 'warp.json')) as f:
                wj = json.load(f)
                reserved = wj.get('reserved', reserved)
        except Exception:
            pass
        if not (priv and pub and endpoint and addr4):
            return None
        addrs = [addr4] + ([addr6] if addr6 else [])
        return {
            "tag": "warp",
            "protocol": "wireguard",
            "settings": {
                "secretKey": priv,
                "address": addrs,
                "peers": [{"publicKey": pub, "endpoint": endpoint, "allowedIPs": ["0.0.0.0/0", "::/0"]}],
                "reserved": reserved,
                "mtu": 1280,
            },
        }
    except Exception:
        return None

INBOUNDS_META = {
    'vless': {'port': 443, 'protocol': 'vless', 'remark': 'VLESS', 'fa': 'وی‌لس'},
    'trojan': {'port': 8443, 'protocol': 'trojan', 'remark': 'Trojan', 'fa': 'تروجان'},
    'ss': {'port': 8388, 'protocol': 'shadowsocks', 'remark': 'Shadowsocks 2022', 'fa': 'شدوساکس ۲۰۲۲'},
    'vmess': {'port': 2096, 'protocol': 'vmess', 'remark': 'VMess', 'fa': 'وی‌مس'},
}

# Transport choices per inbound (most-used types). id -> (label, network, security)
INBOUND_TRANSPORTS = {
    'vless': {
        'reality-tcp': ('Reality + TCP', 'tcp', 'reality'),
        'reality-grpc': ('Reality + gRPC', 'grpc', 'reality'),
        'tls-ws': ('TLS + WebSocket', 'ws', 'tls'),
        'tls-grpc': ('TLS + gRPC', 'grpc', 'tls'),
        'tls-tcp': ('TLS + TCP', 'tcp', 'tls'),
        'tcp': ('TCP (بدون رمزنگاری)', 'tcp', 'none'),
        'ws': ('WebSocket (بدون رمزنگاری)', 'ws', 'none'),
    },
    'trojan': {
        'reality-tcp': ('Reality + TCP', 'tcp', 'reality'),
        'tls-ws': ('TLS + WebSocket', 'ws', 'tls'),
        'tls-grpc': ('TLS + gRPC', 'grpc', 'tls'),
        'tls-tcp': ('TLS + TCP', 'tcp', 'tls'),
        'tcp': ('TCP (بدون رمزنگاری)', 'tcp', 'none'),
    },
    'vmess': {
        'reality-tcp': ('Reality + TCP', 'tcp', 'reality'),
        'tls-ws': ('TLS + WebSocket', 'ws', 'tls'),
        'tls-grpc': ('TLS + gRPC', 'grpc', 'tls'),
        'tcp': ('TCP (بدون رمزنگاری)', 'tcp', 'none'),
        'ws': ('WebSocket (بدون رمزنگاری)', 'ws', 'none'),
    },
    'ss': {
        'tcp': ('TCP/UDP', 'tcp', 'none'),
    },
}
WS_PATHS = {'vless': '/sirgsm-vless', 'trojan': '/sirgsm-trojan', 'vmess': '/sirgsm-vmess'}
GRPC_SERVICES = {'vless': 'SirgsmVless', 'trojan': 'SirgsmTrojan', 'vmess': 'SirgsmVmess'}
REALITY_DEST = {'vless': ('www.microsoft.com', 'www.microsoft.com:443'),
                'trojan': ('dl.google.com', 'dl.google.com:443'),
                'vmess': ('www.amazon.com', 'www.amazon.com:443')}
REALITY_KEYS = {'vless': ('VLESS_PRIV', 'VLESS_PUB', 'VLESS_SHORT'),
                'trojan': ('TROJAN_PRIV', 'TROJAN_PUB', 'TROJAN_SHORT'),
                'vmess': ('VMESS_PRIV', 'VMESS_PUB', 'VMESS_SHORT')}

# ---------------- DB ----------------
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

# ---------------- Settings helpers ----------------
SETTINGS_DEFAULTS = {
    'panel_domain': DOMAIN,
    'panel_port': str(PANEL_PORT),
    'panel_version': PANEL_VERSION,
    'bot_token': '',
    'bot_admin_id': '',
    'bot_enabled': '0',
    'l2tp_enabled': '0',
    'l2tp_secret': '',
    'landing_title': 'Sirgsm VPN',
    'landing_subtitle': 'اشتراک VPN شما',
    'landing_footer': 'Sponsor: Sirgsm.ir — Navid Haghbayan',
    'landing_template': '',
    'transport_vless': 'reality-tcp',
    'transport_trojan': 'reality-tcp',
    'transport_vmess': 'reality-tcp',
    'transport_ss': 'tcp',
    'update_repo': GITHUB_REPO,
    'ssl_email': '',
    'ssl_enabled': '0',
    'backup_enabled': '1',
    'backup_interval_hours': '24',
    'backup_last': '0',
}

def get_setting(key, default=None):
    try:
        con = db()
        row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        con.close()
        if row and row['value'] not in (None, ''):
            return row['value']
    except Exception:
        pass
    if default is not None:
        return default
    return SETTINGS_DEFAULTS.get(key, '')

def set_setting(key, value):
    con = db()
    con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, str(value)))
    con.commit()
    con.close()

def get_domain():
    return get_setting('panel_domain', DOMAIN) or DOMAIN

def get_panel_port():
    try:
        return int(get_setting('panel_port', str(PANEL_PORT)) or PANEL_PORT)
    except Exception:
        return PANEL_PORT

def get_transport(inbound):
    tid = get_setting(f'transport_{inbound}', 'reality-tcp')
    choices = INBOUND_TRANSPORTS.get(inbound, {})
    if tid not in choices:
        tid = 'reality-tcp' if inbound != 'ss' else 'tcp'
    return tid

def ssl_cert_paths(domain=None):
    d = domain or get_domain()
    return (f'/etc/letsencrypt/live/{d}/fullchain.pem',
            f'/etc/letsencrypt/live/{d}/privkey.pem')

def ssl_available(domain=None):
    c, k = ssl_cert_paths(domain)
    return os.path.exists(c) and os.path.exists(k)

def panel_scheme():
    # Panel itself serves HTTP (secret path + password protect it).
    # The Let's Encrypt cert is used for Xray TLS transports, not panel HTTPS.
    # (For panel HTTPS, put nginx in front — see README.)
    return 'http'

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        inbound TEXT NOT NULL,
        uuid TEXT,
        password TEXT,
        traffic_limit INTEGER DEFAULT 0,
        expiry INTEGER DEFAULT 0,
        ip_limit INTEGER DEFAULT 0,
        enable INTEGER DEFAULT 1,
        up INTEGER DEFAULT 0,
        down INTEGER DEFAULT 0,
        last_up INTEGER DEFAULT 0,
        last_down INTEGER DEFAULT 0,
        last_online INTEGER DEFAULT 0,
        created INTEGER DEFAULT 0,
        note TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS routing (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rtype TEXT NOT NULL,
        value TEXT NOT NULL,
        outbound TEXT NOT NULL,
        enable INTEGER DEFAULT 1,
        remark TEXT DEFAULT '',
        sort INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS l2tp_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        enable INTEGER DEFAULT 1,
        created INTEGER DEFAULT 0
    );
    """)
    # Migrations for existing DBs
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(clients)").fetchall()]
        if 'ip_limit' not in cols:
            con.execute("ALTER TABLE clients ADD COLUMN ip_limit INTEGER DEFAULT 0")
        if 'last_online' not in cols:
            con.execute("ALTER TABLE clients ADD COLUMN last_online INTEGER DEFAULT 0")
        con.commit()
    except Exception:
        pass
    # Seed admin user if not exists
    row = con.execute("SELECT value FROM settings WHERE key='admin_pass'").fetchone()
    if not row:
        # Default password will be replaced on first run via env or generated
        default_pass = os.environ.get('SIRGSM_ADMIN_PASS', os.environ.get('NHV_ADMIN_PASS', 'Sirgsm@2026Panel!'))
        con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('admin_user','admin')")
        con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('admin_pass',?)",
                    (generate_password_hash(default_pass),))
        con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('secret_path',?)", (SECRET_PATH,))
        con.commit()
    # Seed settings defaults (only if missing)
    for k, v in SETTINGS_DEFAULTS.items():
        r = con.execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()
        if not r:
            con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (k, v))
    con.commit()
    # Seed routing defaults if empty
    cnt = con.execute("SELECT COUNT(*) c FROM routing").fetchone()['c']
    if cnt == 0:
        defaults = [
            ('ip', 'geoip:private', 'block', 1, 'بلاک IP خصوصی', 1),
            ('domain', 'geosite:category-ads-all', 'block', 1, 'بلاک تبلیغات', 2),
            ('domain', 'geosite:ir', 'direct', 0, 'مستقیم ایران (اختیاری)', 3),
            ('ip', 'geoip:ir', 'direct', 0, 'مستقیم IP ایران (اختیاری)', 4),
            ('domain', 'domain:youtube.com', 'warp', 1, 'Warp: یوتیوب', 5),
            ('domain', 'domain:youtu.be', 'warp', 1, 'Warp: یوتیوب کوتاه', 6),
            ('domain', 'domain:googlevideo.com', 'warp', 1, 'Warp: ویدیو گوگل', 7),
            ('domain', 'domain:google.com', 'warp', 1, 'Warp: گوگل', 8),
            ('domain', 'domain:gstatic.com', 'warp', 1, 'Warp: جی‌استیتیک', 9),
            ('domain', 'domain:openai.com', 'warp', 1, 'Warp: اوپن‌ای‌آی', 10),
            ('domain', 'domain:chat.openai.com', 'warp', 1, 'Warp: چت اوپن‌ای‌آی', 11),
            ('domain', 'domain:telegram.org', 'warp', 1, 'Warp: تلگرام', 12),
            ('domain', 'domain:telegram.me', 'warp', 1, 'Warp: تلگرام می', 13),
        ]
        con.executemany("INSERT INTO routing(rtype,value,outbound,enable,remark,sort) VALUES(?,?,?,?,?,?)", defaults)
    # Seed admin clients (one per inbound, unlimited) if not exists
    for inbound, email in [('vless', 'admin-vless'), ('trojan', 'admin-trojan'), ('ss', 'admin-ss'), ('vmess', 'admin-vmess')]:
        exists = con.execute("SELECT id FROM clients WHERE email=?", (email,)).fetchone()
        if not exists:
            now = int(time.time())
            if inbound == 'vless':
                con.execute("INSERT INTO clients(email,inbound,uuid,password,traffic_limit,expiry,enable,created,note) VALUES(?,?,?,?,0,0,1,?,?)",
                            (email, inbound, VLESS_UUID, '', now, 'کاربر اصلی VLESS'))
            elif inbound == 'trojan':
                tp = S2.get('TPASS', secrets.token_urlsafe(10)[:16])
                con.execute("INSERT INTO clients(email,inbound,uuid,password,traffic_limit,expiry,enable,created,note) VALUES(?,?,?,?,0,0,1,?,?)",
                            (email, inbound, '', tp, now, 'کاربر اصلی Trojan'))
            elif inbound == 'vmess':
                con.execute("INSERT INTO clients(email,inbound,uuid,password,traffic_limit,expiry,enable,created,note) VALUES(?,?,?,?,0,0,1,?,?)",
                            (email, inbound, str(uuid.uuid4()), '', now, 'کاربر اصلی VMess'))
            else:
                sp = S2.get('SSP', base64.b64encode(os.urandom(16)).decode())
                con.execute("INSERT INTO clients(email,inbound,uuid,password,traffic_limit,expiry,enable,created,note) VALUES(?,?,?,?,0,0,1,?,?)",
                            (email, inbound, '', sp, now, 'کاربر اصلی Shadowsocks'))
    con.commit()
    con.close()

# ---------------- Xray config ----------------
def build_stream(inbound):
    """Build streamSettings for inbound based on its transport setting."""
    tid = get_transport(inbound)
    label, network, security = INBOUND_TRANSPORTS[inbound][tid]
    domain = get_domain()
    ss = {"network": network}
    if security == 'reality':
        sni, dest = REALITY_DEST[inbound]
        priv = {'vless': VLESS_PRIV, 'trojan': TROJAN_PRIV, 'vmess': VMESS_PRIV}[inbound]
        short = {'vless': VLESS_SHORT, 'trojan': TROJAN_SHORT, 'vmess': VMESS_SHORT}[inbound]
        ss["security"] = "reality"
        ss["realitySettings"] = {
            "show": False, "dest": dest, "xver": 0,
            "serverNames": [sni], "privateKey": priv, "shortIds": [short],
        }
    elif security == 'tls':
        cert, key = ssl_cert_paths(domain)
        ss["security"] = "tls"
        ss["tlsSettings"] = {
            "certificates": [{"certificateFile": cert, "keyFile": key}],
            "alpn": ["h2", "http/1.1"],
        }
    if network == 'ws':
        ss["wsSettings"] = {"path": WS_PATHS.get(inbound, '/sirgsm')}
    elif network == 'grpc':
        ss["grpcSettings"] = {"serviceName": GRPC_SERVICES.get(inbound, 'SirgsmService')}
    return ss

def build_xray_config():
    con = db()
    clients = con.execute("SELECT * FROM clients WHERE enable=1").fetchall()
    routes = con.execute("SELECT * FROM routing WHERE enable=1 ORDER BY sort, id").fetchall()
    con.close()

    by_inbound = {'vless': [], 'trojan': [], 'ss': [], 'vmess': []}
    for c in clients:
        if c['inbound'] in by_inbound:
            by_inbound[c['inbound']].append(c)

    # VLESS flow only for reality-tcp (xtls-rprx-vision)
    vless_flow = "xtls-rprx-vision" if get_transport('vless') == 'reality-tcp' else None
    vless_clients = []
    for c in by_inbound['vless']:
        if not c['uuid']:
            continue
        e = {"id": c['uuid'], "email": c['email']}
        if vless_flow:
            e["flow"] = vless_flow
        vless_clients.append(e)
    trojan_clients = [{"password": c['password'], "email": c['email']}
                      for c in by_inbound['trojan'] if c['password']]
    ss_clients = [{"password": c['password'], "email": c['email']}
                  for c in by_inbound['ss'] if c['password']]
    vmess_clients = [{"id": c['uuid'], "alterId": 0, "email": c['email']}
                     for c in by_inbound['vmess'] if c['uuid']]

    inbounds = [
        {
            "tag": "api",
            "port": 10000,
            "listen": "127.0.0.1",
            "protocol": "dokodemo-door",
            "settings": {"address": "127.0.0.1"},
        },
        {
            "port": 443,
            "protocol": "vless",
            "settings": {"clients": vless_clients, "decryption": "none"},
            "streamSettings": build_stream('vless'),
            "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]},
            "tag": "vless-in",
        },
        {
            "port": 8443,
            "protocol": "trojan",
            "settings": {"clients": trojan_clients},
            "streamSettings": build_stream('trojan'),
            "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]},
            "tag": "trojan-in",
        },
        {
            "port": 8388,
            "protocol": "shadowsocks",
            "settings": {
                "method": "2022-blake3-aes-128-gcm",
                "password": SS_SERVER_KEY,
                "network": "tcp,udp",
                "clients": ss_clients,
            },
            "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]},
            "tag": "ss-in",
        },
        {
            "port": 2096,
            "protocol": "vmess",
            "settings": {"clients": vmess_clients},
            "streamSettings": build_stream('vmess'),
            "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]},
            "tag": "vmess-in",
        },
    ]

    # Routing rules
    rules = [{"inboundTag": ["api"], "outboundTag": "api", "type": "field"}]
    for r in routes:
        rule = {"type": "field", "outboundTag": r['outbound']}
        if r['rtype'] == 'domain':
            rule['domain'] = [r['value']]
        elif r['rtype'] == 'ip':
            rule['ip'] = [r['value']]
        elif r['rtype'] == 'port':
            rule['port'] = r['value']
        elif r['rtype'] == 'protocol':
            rule['protocol'] = [r['value']]
        else:
            rule['domain'] = [r['value']]
        rules.append(rule)

    outbounds = [
        {"protocol": "freedom", "tag": "direct"},
        {"protocol": "blackhole", "tag": "block"},
    ]
    warp_out = load_warp()
    if warp_out:
        outbounds.append(warp_out)
    config = {
        "log": {"loglevel": "warning"},
        "api": {"tag": "api", "services": ["StatsService", "HandlerService", "RoutingService", "LoggerService"]},
        "stats": {},
        "policy": {"levels": {"0": {"statsUserUplink": True, "statsUserDownlink": True, "statsUserOnline": True}}},
        "inbounds": inbounds,
        "outbounds": outbounds,
        "routing": {"domainStrategy": "IPIfNonMatch", "rules": rules},
    }
    with open(XRAY_CONFIG, 'w') as f:
        json.dump(config, f, indent=2)
    return config

def restart_xray():
    subprocess.run(['systemctl', 'restart', 'xray'], timeout=30)
    time.sleep(2)

def xray_active():
    try:
        r = subprocess.run(['systemctl', 'is-active', 'xray'], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() == 'active'
    except Exception:
        return False

# ---------------- Stats ----------------
def query_stats():
    """Query Xray stats via CLI. Returns dict email -> (up, down)."""
    result = {}
    try:
        r = subprocess.run([XRAY_BIN, 'api', 'statsquery', f'--server={API_ADDR}', '-pattern', 'user>>>'],
                           capture_output=True, text=True, timeout=10)
        out = (r.stdout or '') + (r.stderr or '')
        # Try JSON parse first
        try:
            data = json.loads(out)
            stats = data.get('stat', data.get('stats', [])) if isinstance(data, dict) else data
            if isinstance(stats, list):
                for s in stats:
                    name = s.get('name', '')
                    val = s.get('value', 0)
                    # name format: user>>>EMAIL>>>traffic>>>uplink
                    parts = name.split('>>>')
                    if len(parts) >= 4 and parts[0] == 'user':
                        email = parts[1]
                        kind = parts[3]
                        up, down = result.get(email, (0, 0))
                        if kind == 'uplink':
                            up = int(val)
                        elif kind == 'downlink':
                            down = int(val)
                        result[email] = (up, down)
                return result
        except Exception:
            pass
        # Fallback: parse text lines like "user>>>x>>>traffic>>>uplink: 123"
        for line in out.splitlines():
            line = line.strip()
            if '>>>' not in line:
                continue
            # split on last colon
            if ':' in line:
                name, val = line.rsplit(':', 1)
                name = name.strip()
                val = val.strip()
                try:
                    v = int(val)
                except Exception:
                    continue
                parts = name.split('>>>')
                if len(parts) >= 4 and parts[0] == 'user':
                    email = parts[1]
                    kind = parts[3]
                    up, down = result.get(email, (0, 0))
                    if kind == 'uplink':
                        up = v
                    elif kind == 'downlink':
                        down = v
                    result[email] = (up, down)
    except Exception as e:
        print(f'stats query failed: {e}', flush=True)
    return result

def sync_stats_and_enforce():
    """Update traffic counters (delta-based, survives Xray restarts), disable expired/over-limit users."""
    stats = query_stats()
    if not stats:
        return
    con = db()
    changed = False
    now = int(time.time())
    rows = con.execute("SELECT * FROM clients").fetchall()
    for c in rows:
        email = c['email']
        if email in stats:
            up, down = stats[email]
            last_up = c['last_up'] or 0
            last_down = c['last_down'] or 0
            # Delta since last poll; if Xray restarted, counter < last -> delta is current value
            d_up = (up - last_up) if up >= last_up else up
            d_down = (down - last_down) if down >= last_down else down
            new_up = (c['up'] or 0) + d_up
            new_down = (c['down'] or 0) + d_down
            con.execute("UPDATE clients SET up=?, down=?, last_up=?, last_down=? WHERE id=?",
                        (new_up, new_down, up, down, c['id']))
        # Enforce limits
        total = (c['up'] or 0) + (c['down'] or 0)
        over = False
        if c['traffic_limit'] and c['traffic_limit'] > 0 and total >= c['traffic_limit']:
            over = True
        if c['expiry'] and c['expiry'] > 0 and now >= c['expiry']:
            over = True
        if over and c['enable'] == 1:
            con.execute("UPDATE clients SET enable=0 WHERE id=?", (c['id'],))
            changed = True
    con.commit()
    con.close()
    if changed:
        try:
            build_xray_config()
            restart_xray()
        except Exception as e:
            print(f'enforce restart failed: {e}', flush=True)

def query_online_users():
    """Returns dict email -> online count via statsgetallonlineusers."""
    result = {}
    try:
        r = subprocess.run([XRAY_BIN, 'api', 'statsgetallonlineusers', f'--server={API_ADDR}'],
                           capture_output=True, text=True, timeout=10)
        out = (r.stdout or '').strip()
        if not out:
            return result
        try:
            data = json.loads(out)
            # Format may be list of emails or dict; handle both
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, str):
                        result[item] = result.get(item, 0) + 1
                    elif isinstance(item, dict):
                        em = item.get('email') or item.get('user') or ''
                        if em:
                            result[em] = result.get(em, 0) + 1
            elif isinstance(data, dict):
                for k, v in data.items():
                    try:
                        result[k] = int(v)
                    except Exception:
                        result[k] = 1
        except Exception:
            # Text fallback: one email per line
            for line in out.splitlines():
                line = line.strip()
                if line and '>>>' not in line and '{' not in line:
                    result[line] = result.get(line, 0) + 1
    except Exception as e:
        print(f'online query failed: {e}', flush=True)
    return result

def query_online_ips(email):
    """Returns list of (ip, timestamp) for a user via statsonlineiplist."""
    ips = []
    try:
        r = subprocess.run([XRAY_BIN, 'api', 'statsonlineiplist', f'--server={API_ADDR}', '-email', email],
                           capture_output=True, text=True, timeout=10)
        out = (r.stdout or '').strip()
        if not out or out == '{}':
            return ips
        try:
            data = json.loads(out)
            # Possible formats: {"email": [{"ip": "...", "timestamp": ...}]} or list
            if isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, list):
                        for item in v:
                            if isinstance(item, dict):
                                ips.append((item.get('ip', ''), item.get('timestamp', 0)))
                            elif isinstance(item, str):
                                ips.append((item, 0))
                    elif isinstance(v, str):
                        ips.append((v, 0))
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        ips.append((item.get('ip', ''), item.get('timestamp', 0)))
                    elif isinstance(item, str):
                        ips.append((item, 0))
        except Exception:
            for line in out.splitlines():
                line = line.strip()
                if line and ('.' in line or ':' in line):
                    ips.append((line.split()[0], 0))
    except Exception:
        pass
    return [(ip, ts) for ip, ts in ips if ip]

INBOUND_TAGS = {'vless': 'vless-in', 'trojan': 'trojan-in', 'ss': 'ss-in', 'vmess': 'vmess-in'}

def enforce_ip_limits():
    """Block excess IPs for users over ip_limit via Xray sib API."""
    try:
        con = db()
        rows = con.execute("SELECT * FROM clients WHERE enable=1 AND ip_limit>0").fetchall()
        con.close()
        for c in rows:
            try:
                ips = query_online_ips(c['email'])
                limit = c['ip_limit'] or 0
                if limit and len(ips) > limit:
                    # Block newest excess (sort by timestamp desc, block beyond limit)
                    ips_sorted = sorted(ips, key=lambda x: x[1] or 0, reverse=True)
                    excess = ips_sorted[limit:]
                    tag = INBOUND_TAGS.get(c['inbound'], 'vless-in')
                    for ip, _ in excess:
                        try:
                            subprocess.run([XRAY_BIN, 'api', 'sib', f'--server={API_ADDR}',
                                            '-outbound=blocked', f'-inbound={tag}', ip],
                                           capture_output=True, text=True, timeout=10)
                        except Exception:
                            pass
            except Exception:
                pass
    except Exception as e:
        print(f'ip limit enforce failed: {e}', flush=True)

def stats_loop():
    while True:
        try:
            sync_stats_and_enforce()
            enforce_ip_limits()
        except Exception as e:
            print(f'stats loop error: {e}', flush=True)
        time.sleep(60)

# ---------------- Helpers ----------------
def fmt_bytes(n):
    n = int(n or 0)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != 'B' else f"{n} B"
        n /= 1024
    return f"{n:.1f} PB"

def fmt_date(ts):
    if not ts:
        return 'نامحدود'
    try:
        return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
    except Exception:
        return 'نامحدود'

def gen_links(c):
    email = c['email']
    inbound = c['inbound']
    domain = get_domain()
    links = []
    if inbound == 'ss':
        method = '2022-blake3-aes-128-gcm'
        raw = f"{method}:{SS_SERVER_KEY}:{c['password']}"
        b64 = base64.b64encode(raw.encode()).decode()
        links.append(f"ss://{b64}@{SERVER_IP}:8388#{email}")
        links.append(f"ss://{b64}@{domain}:8388#{email}")
        return links
    tid = get_transport(inbound)
    label, network, security = INBOUND_TRANSPORTS[inbound][tid]
    port = INBOUNDS_META[inbound]['port']
    # Reality params
    sni_r, _dest = REALITY_DEST.get(inbound, ('www.microsoft.com', ''))
    pub = {'vless': VLESS_PUB, 'trojan': TROJAN_PUB, 'vmess': VMESS_PUB}.get(inbound, '')
    short = {'vless': VLESS_SHORT, 'trojan': TROJAN_SHORT, 'vmess': VMESS_SHORT}.get(inbound, '')
    ws_path = WS_PATHS.get(inbound, '/sirgsm')
    grpc_svc = GRPC_SERVICES.get(inbound, 'SirgsmService')
    for host in (SERVER_IP, domain):
        if inbound == 'vless':
            q = ['encryption=none']
            if security == 'reality':
                q += ['security=reality', f'sni={sni_r}', 'fp=chrome', f'pbk={pub}', f'sid={short}']
            elif security == 'tls':
                q += ['security=tls', f'sni={domain}']
            q.append(f'type={network}')
            if network == 'ws':
                q.append(f'path={ws_path}')
            elif network == 'grpc':
                q.append(f'serviceName={grpc_svc}')
            if tid == 'reality-tcp':
                q.append('flow=xtls-rprx-vision')
            links.append(f"vless://{c['uuid']}@{host}:{port}?" + '&'.join(q) + f"#{email}")
        elif inbound == 'trojan':
            q = []
            if security == 'reality':
                q += ['security=reality', f'sni={sni_r}', 'fp=chrome', f'pbk={pub}', f'sid={short}']
            elif security == 'tls':
                q += ['security=tls', f'sni={domain}']
            q.append(f'type={network}')
            if network == 'ws':
                q.append(f'path={ws_path}')
            elif network == 'grpc':
                q.append(f'serviceName={grpc_svc}')
            links.append(f"trojan://{c['password']}@{host}:{port}?" + '&'.join(q) + f"#{email}")
        elif inbound == 'vmess':
            cfg = {
                "v": "2", "ps": email, "add": host, "port": str(port),
                "id": c['uuid'], "aid": "0", "scy": "auto",
                "net": network, "type": "none",
                "host": domain if security == 'tls' else "",
                "path": ws_path if network == 'ws' else (grpc_svc if network == 'grpc' else ""),
                "tls": security if security in ('reality', 'tls') else "",
                "sni": sni_r if security == 'reality' else (domain if security == 'tls' else ""),
                "alpn": "", "fp": "chrome" if security == 'reality' else "",
                "pbk": pub if security == 'reality' else "",
                "sid": short if security == 'reality' else "",
                "headerType": "none",
            }
            b64 = base64.b64encode(json.dumps(cfg).encode()).decode()
            links.append(f"vmess://{b64}")
    return links

def sub_url(c):
    token = c['uuid'] or c['password'] or ''
    return f"{panel_scheme()}://{get_domain()}:{get_panel_port()}/sub/{token}"

def server_stats():
    out = {}
    try:
        with open('/proc/uptime') as f:
            up = float(f.read().split()[0])
            out['uptime'] = int(up)
    except Exception:
        out['uptime'] = 0
    try:
        mem = {}
        with open('/proc/meminfo') as f:
            for line in f:
                if ':' in line:
                    k, v = line.split(':', 1)
                    mem[k.strip()] = int(v.strip().split()[0])  # kB
        total = mem.get('MemTotal', 1)
        avail = mem.get('MemAvailable', 0)
        out['mem_total'] = total * 1024
        out['mem_used'] = (total - avail) * 1024
        out['mem_pct'] = round((total - avail) / total * 100, 1) if total else 0
    except Exception:
        out['mem_total'] = out['mem_used'] = 0
        out['mem_pct'] = 0
    try:
        # CPU: load avg
        with open('/proc/loadavg') as f:
            parts = f.read().split()
            out['load'] = f"{parts[0]} {parts[1]} {parts[2]}"
    except Exception:
        out['load'] = ''
    try:
        du = shutil.disk_usage('/')
        out['disk_total'] = du.total
        out['disk_used'] = du.used
        out['disk_pct'] = round(du.used / du.total * 100, 1) if du.total else 0
    except Exception:
        out['disk_total'] = out['disk_used'] = 0
        out['disk_pct'] = 0
    for svc in ['xray', 'asterisk', 'sirgsm-panel', 'nhv-panel']:
        try:
            r = subprocess.run(['systemctl', 'is-active', svc], capture_output=True, text=True, timeout=5)
            out[f'svc_{svc}'] = r.stdout.strip()
        except Exception:
            out[f'svc_{svc}'] = 'unknown'
    # Network totals (all non-lo interfaces) + per-interface
    try:
        def read_net():
            rx = tx = 0
            per = {}
            with open('/proc/net/dev') as f:
                for line in f:
                    if ':' not in line:
                        continue
                    iface, rest = line.split(':', 1)
                    iface = iface.strip()
                    if iface == 'lo':
                        continue
                    parts = rest.split()
                    if len(parts) >= 16:
                        r = int(parts[0]); t = int(parts[8])
                        rx += r; tx += t
                        per[iface] = {'rx': r, 'tx': t}
            return rx, tx, per
        rx1, tx1, per1 = read_net()
        time.sleep(1)
        rx2, tx2, per2 = read_net()
        out['net_rx'] = rx2
        out['net_tx'] = tx2
        out['net_rx_rate'] = max(0, rx2 - rx1)
        out['net_tx_rate'] = max(0, tx2 - tx1)
        out['net_per'] = per2
    except Exception:
        out['net_rx'] = out['net_tx'] = 0
        out['net_rx_rate'] = out['net_tx_rate'] = 0
        out['net_per'] = {}
    out['warp_enabled'] = bool(load_warp())
    return out

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(f'/{SECRET_PATH}/login')
        return f(*args, **kwargs)
    return decorated

def check_secret():
    # SECRET_PATH is part of URL; Flask routes already include it. This is just a guard.
    pass

# ---------------- Routes ----------------
@app.route(f'/{SECRET_PATH}/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = request.form.get('username', '')
        pw = request.form.get('password', '')
        con = db()
        u = con.execute("SELECT value FROM settings WHERE key='admin_user'").fetchone()
        p = con.execute("SELECT value FROM settings WHERE key='admin_pass'").fetchone()
        con.close()
        if u and p and user == u['value'] and check_password_hash(p['value'], pw):
            session['logged_in'] = True
            session.permanent = True
            return redirect(f'/{SECRET_PATH}/')
        return render_template_string(LOGIN_HTML, error='نام کاربری یا رمز اشتباه است', secret=SECRET_PATH), 401
    if session.get('logged_in'):
        return redirect(f'/{SECRET_PATH}/')
    return render_template_string(LOGIN_HTML, error='', secret=SECRET_PATH)

@app.route(f'/{SECRET_PATH}/logout')
def logout():
    session.clear()
    return redirect(f'/{SECRET_PATH}/login')

@app.route(f'/{SECRET_PATH}/')
@login_required
def index():
    return render_template_string(INDEX_HTML, secret=SECRET_PATH)

@app.route(f'/{SECRET_PATH}/api/dashboard')
@login_required
def api_dashboard():
    sync_stats_and_enforce()
    con = db()
    clients = con.execute("SELECT * FROM clients ORDER BY id").fetchall()
    con.close()
    total_up = sum(c['up'] or 0 for c in clients)
    total_down = sum(c['down'] or 0 for c in clients)
    by_inbound = {}
    for k, meta in INBOUNDS_META.items():
        lst = [c for c in clients if c['inbound'] == k]
        by_inbound[k] = {
            'meta': meta,
            'count': len(lst),
            'enabled': sum(1 for c in lst if c['enable']),
            'traffic': sum((c['up'] or 0) + (c['down'] or 0) for c in lst),
        }
    online = query_online_users()
    return jsonify({
        'server': server_stats(),
        'xray_active': xray_active(),
        'total_users': len(clients),
        'enabled_users': sum(1 for c in clients if c['enable']),
        'online_users': sum(online.values()) if online else 0,
        'total_up': total_up,
        'total_down': total_down,
        'total_traffic': total_up + total_down,
        'by_inbound': by_inbound,
        'domain': DOMAIN,
        'ip': SERVER_IP,
        'panel_name': PANEL_NAME,
        'sponsor': SPONSOR,
    })

@app.route(f'/{SECRET_PATH}/api/clients', methods=['GET', 'POST'])
@login_required
def api_clients():
    con = db()
    if request.method == 'GET':
        inbound_filter = request.args.get('inbound', '')
        if inbound_filter in INBOUNDS_META:
            rows = con.execute("SELECT * FROM clients WHERE inbound=? ORDER BY id", (inbound_filter,)).fetchall()
        else:
            rows = con.execute("SELECT * FROM clients ORDER BY id").fetchall()
        online = query_online_users()
        out = []
        for c in rows:
            d = dict(c)
            d['total'] = (d['up'] or 0) + (d['down'] or 0)
            d['links'] = gen_links(c)
            d['sub'] = sub_url(c)
            d['online'] = online.get(c['email'], 0)
            # Status: enabled/disabled/expired/over-limit
            now = int(time.time())
            total = d['total']
            if not d['enable']:
                d['status'] = 'disabled'
            elif d['expiry'] and now >= d['expiry']:
                d['status'] = 'expired'
            elif d['traffic_limit'] and total >= d['traffic_limit']:
                d['status'] = 'overlimit'
            else:
                d['status'] = 'active'
            out.append(d)
        con.close()
        return jsonify(out)
    # POST create
    data = request.get_json(force=True)
    email = (data.get('email') or '').strip()
    inbound = data.get('inbound', 'vless')
    if not email or inbound not in INBOUNDS_META:
        con.close()
        return jsonify({'error': 'ایمیل و پروتکل معتبر نیست'}), 400
    if con.execute("SELECT id FROM clients WHERE email=?", (email,)).fetchone():
        con.close()
        return jsonify({'error': 'این ایمیل قبلاً وجود دارد'}), 400
    traffic_gb = float(data.get('traffic_gb') or 0)
    traffic_limit = int(traffic_gb * 1024 * 1024 * 1024) if traffic_gb > 0 else 0
    expiry_days = int(data.get('expiry_days') or 0)
    expiry = int(time.time() + expiry_days * 86400) if expiry_days > 0 else 0
    note = (data.get('note') or '').strip()
    now = int(time.time())
    if inbound == 'vless':
        uid = str(uuid.uuid4())
        pw = ''
    elif inbound == 'trojan':
        uid = ''
        pw = secrets.token_urlsafe(12)[:16]
    elif inbound == 'vmess':
        uid = str(uuid.uuid4())
        pw = ''
    else:
        uid = ''
        pw = base64.b64encode(os.urandom(16)).decode()
    ip_limit = int(data.get('ip_limit') or 0)
    cur = con.execute("INSERT INTO clients(email,inbound,uuid,password,traffic_limit,expiry,ip_limit,enable,created,note) VALUES(?,?,?,?,?,?,?,1,?,?)",
                      (email, inbound, uid, pw, traffic_limit, expiry, ip_limit, now, note))
    cid = cur.lastrowid
    con.commit()
    row = con.execute("SELECT * FROM clients WHERE id=?", (cid,)).fetchone()
    con.close()
    try:
        build_xray_config()
        restart_xray()
    except Exception as e:
        return jsonify({'error': f'کاربر ساخته شد ولی Xray restart نشد: {e}'}), 500
    d = dict(row)
    d['total'] = (d['up'] or 0) + (d['down'] or 0)
    d['links'] = gen_links(row)
    return jsonify(d), 201

@app.route(f'/{SECRET_PATH}/api/clients/<int:cid>', methods=['PUT', 'DELETE'])
@login_required
def api_client_one(cid):
    con = db()
    row = con.execute("SELECT * FROM clients WHERE id=?", (cid,)).fetchone()
    if not row:
        con.close()
        return jsonify({'error': 'یافت نشد'}), 404
    if request.method == 'DELETE':
        con.execute("DELETE FROM clients WHERE id=?", (cid,))
        con.commit()
        con.close()
        try:
            build_xray_config()
            restart_xray()
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        return jsonify({'ok': True})
    # PUT update
    data = request.get_json(force=True)
    traffic_gb = data.get('traffic_gb', None)
    expiry_days = data.get('expiry_days', None)
    ip_limit = data.get('ip_limit', None)
    note = data.get('note', None)
    enable = data.get('enable', None)
    email = data.get('email', None)
    sets = []
    params = []
    if email is not None:
        email = str(email).strip()
        if email and email != row['email']:
            if con.execute("SELECT id FROM clients WHERE email=?", (email,)).fetchone():
                con.close()
                return jsonify({'error': 'این ایمیل قبلاً وجود دارد'}), 400
            sets.append('email=?')
            params.append(email)
    if traffic_gb is not None:
        traffic_gb = float(traffic_gb or 0)
        sets.append('traffic_limit=?')
        params.append(int(traffic_gb * 1024 * 1024 * 1024) if traffic_gb > 0 else 0)
    if expiry_days is not None:
        expiry_days = int(expiry_days or 0)
        sets.append('expiry=?')
        params.append(int(time.time() + expiry_days * 86400) if expiry_days > 0 else 0)
    if ip_limit is not None:
        sets.append('ip_limit=?')
        params.append(int(ip_limit or 0))
    if note is not None:
        sets.append('note=?')
        params.append(str(note).strip())
    if enable is not None:
        sets.append('enable=?')
        params.append(1 if enable else 0)
    if sets:
        params.append(cid)
        con.execute(f"UPDATE clients SET {', '.join(sets)} WHERE id=?", params)
        con.commit()
    newrow = con.execute("SELECT * FROM clients WHERE id=?", (cid,)).fetchone()
    con.close()
    try:
        build_xray_config()
        restart_xray()
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    d = dict(newrow)
    d['total'] = (d['up'] or 0) + (d['down'] or 0)
    d['links'] = gen_links(newrow)
    return jsonify(d)

@app.route(f'/{SECRET_PATH}/api/clients/<int:cid>/reset', methods=['POST'])
@login_required
def api_client_reset(cid):
    con = db()
    row = con.execute("SELECT * FROM clients WHERE id=?", (cid,)).fetchone()
    if not row:
        con.close()
        return jsonify({'error': 'یافت نشد'}), 404
    con.execute("UPDATE clients SET up=0, down=0, last_up=0, last_down=0 WHERE id=?", (cid,))
    con.commit()
    con.close()
    # Restart Xray to zero counters for clean reset; delta logic handles the rest.
    try:
        build_xray_config()
        restart_xray()
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({'ok': True})

@app.route(f'/{SECRET_PATH}/api/routing', methods=['GET', 'POST'])
@login_required
def api_routing():
    con = db()
    if request.method == 'GET':
        rows = con.execute("SELECT * FROM routing ORDER BY sort, id").fetchall()
        con.close()
        return jsonify([dict(r) for r in rows])
    data = request.get_json(force=True)
    rtype = data.get('rtype', 'domain')
    value = (data.get('value') or '').strip()
    outbound = data.get('outbound', 'direct')
    remark = (data.get('remark') or '').strip()
    if not value or rtype not in ('domain', 'ip', 'port', 'protocol') or outbound not in ('direct', 'block', 'warp'):
        con.close()
        return jsonify({'error': 'مقادیر معتبر نیست'}), 400
    mx = con.execute("SELECT COALESCE(MAX(sort),0) m FROM routing").fetchone()['m']
    cur = con.execute("INSERT INTO routing(rtype,value,outbound,enable,remark,sort) VALUES(?,?,?,?,1,?)",
                      (rtype, value, outbound, remark, mx + 1))
    rid = cur.lastrowid
    con.commit()
    row = con.execute("SELECT * FROM routing WHERE id=?", (rid,)).fetchone()
    con.close()
    try:
        build_xray_config()
        restart_xray()
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify(dict(row)), 201

@app.route(f'/{SECRET_PATH}/api/routing/<int:rid>', methods=['PUT', 'DELETE'])
@login_required
def api_routing_one(rid):
    con = db()
    row = con.execute("SELECT * FROM routing WHERE id=?", (rid,)).fetchone()
    if not row:
        con.close()
        return jsonify({'error': 'یافت نشد'}), 404
    if request.method == 'DELETE':
        con.execute("DELETE FROM routing WHERE id=?", (rid,))
        con.commit()
        con.close()
        try:
            build_xray_config()
            restart_xray()
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        return jsonify({'ok': True})
    data = request.get_json(force=True)
    sets, params = [], []
    for k in ('rtype', 'value', 'outbound', 'remark'):
        if k in data:
            sets.append(f'{k}=?')
            params.append(str(data[k]).strip())
    if 'enable' in data:
        sets.append('enable=?')
        params.append(1 if data['enable'] else 0)
    if sets:
        params.append(rid)
        con.execute(f"UPDATE routing SET {', '.join(sets)} WHERE id=?", params)
        con.commit()
    newrow = con.execute("SELECT * FROM routing WHERE id=?", (rid,)).fetchone()
    con.close()
    try:
        build_xray_config()
        restart_xray()
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify(dict(newrow))

@app.route(f'/{SECRET_PATH}/api/logs')
@login_required
def api_logs():
    try:
        r = subprocess.run(['journalctl', '-u', 'xray', '--no-pager', '-n', '120'],
                           capture_output=True, text=True, timeout=10)
        return jsonify({'logs': (r.stdout or '')[-12000:]})
    except Exception as e:
        return jsonify({'logs': f'خطا: {e}'}), 500

@app.route(f'/{SECRET_PATH}/api/restart-xray', methods=['POST'])
@login_required
def api_restart():
    try:
        build_xray_config()
        restart_xray()
        return jsonify({'ok': True, 'active': xray_active()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route(f'/{SECRET_PATH}/api/change-pass', methods=['POST'])
@login_required
def api_change_pass():
    data = request.get_json(force=True)
    new = (data.get('password') or '').strip()
    if len(new) < 8:
        return jsonify({'error': 'رمز حداقل ۸ کاراکتر باشد'}), 400
    con = db()
    con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('admin_pass',?)",
                (generate_password_hash(new),))
    con.commit()
    con.close()
    return jsonify({'ok': True})

@app.route(f'/{SECRET_PATH}/api/settings', methods=['GET', 'PUT'])
@login_required
def api_settings():
    if request.method == 'GET':
        out = {}
        for k in SETTINGS_DEFAULTS:
            if k == 'bot_token':
                v = get_setting(k, '')
                out[k] = ('••••••' + v[-4:]) if v else ''
                out['bot_token_set'] = bool(v)
            else:
                out[k] = get_setting(k, SETTINGS_DEFAULTS[k])
        out['panel_version'] = PANEL_VERSION
        out['domain'] = get_domain()
        out['ssl_available'] = ssl_available()
        out['transports'] = {ib: {tid: v[0] for tid, v in ch.items()} for ib, ch in INBOUND_TRANSPORTS.items()}
        return jsonify(out)
    data = request.get_json(force=True)
    allowed = set(SETTINGS_DEFAULTS.keys())
    changed = []
    for k, v in data.items():
        if k not in allowed:
            continue
        if k == 'bot_token' and v in ('', '••••••', None):
            continue
        set_setting(k, v)
        changed.append(k)
    # Side effects
    need_xray = any(k.startswith('transport_') or k == 'panel_domain' for k in changed)
    need_bot = any(k in ('bot_token', 'bot_admin_id', 'bot_enabled') for k in changed)
    need_l2tp = any(k in ('l2tp_enabled', 'l2tp_secret') for k in changed)
    msg = []
    if need_xray:
        try:
            build_xray_config()
            restart_xray()
            msg.append('xray rebuilt')
        except Exception as e:
            return jsonify({'error': f'Xray rebuild failed: {e}'}), 500
    if need_bot:
        try:
            subprocess.run(['systemctl', 'restart', 'sirgsm-bot'], timeout=15)
            msg.append('bot restarted')
        except Exception as e:
            msg.append(f'bot restart: {e}')
    if need_l2tp:
        try:
            apply_l2tp()
            msg.append('l2tp applied')
        except Exception as e:
            return jsonify({'error': f'L2TP apply failed: {e}'}), 500
    return jsonify({'ok': True, 'changed': changed, 'msg': msg})

@app.route(f'/{SECRET_PATH}/api/restart-panel', methods=['POST'])
@login_required
def api_restart_panel():
    try:
        subprocess.run(['systemctl', 'restart', 'sirgsm-panel'], timeout=10)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route(f'/{SECRET_PATH}/api/restart-bot', methods=['POST'])
@login_required
def api_restart_bot():
    try:
        subprocess.run(['systemctl', 'restart', 'sirgsm-bot'], timeout=15)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route(f'/{SECRET_PATH}/api/ssl/issue', methods=['POST'])
@login_required
def api_ssl_issue():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or get_setting('ssl_email', '')).strip()
    domain = get_domain()
    if not email or '@' not in email:
        return jsonify({'error': 'ایمیل معتبر برای Let\'s Encrypt وارد کن'}), 400
    set_setting('ssl_email', email)
    # Install certbot if needed
    try:
        r = subprocess.run(['which', 'certbot'], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            subprocess.run(['apt-get', 'update', '-y'], timeout=120)
            subprocess.run(['apt-get', 'install', '-y', 'certbot', 'python3-certbot-nginx'], timeout=300)
        # Stop nginx if running (standalone needs port 80 free; nginx plugin handles it, but standalone is simpler)
        # Use webroot via nginx if available, else standalone
        r = subprocess.run(['certbot', 'certonly', '--standalone', '--non-interactive',
                            '--agree-tos', '-m', email, '-d', domain],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            # Try nginx plugin
            r = subprocess.run(['certbot', 'certonly', '--nginx', '--non-interactive',
                                '--agree-tos', '-m', email, '-d', domain],
                               capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return jsonify({'error': f'certbot failed: {(r.stderr or r.stdout)[-800:]}'}), 500
        set_setting('ssl_enabled', '1')
        # Restart panel to pick up HTTPS (if configured) + xray for TLS transports
        try:
            build_xray_config()
            restart_xray()
        except Exception:
            pass
        return jsonify({'ok': True, 'domain': domain})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route(f'/{SECRET_PATH}/api/update/check')
@login_required
def api_update_check():
    repo = get_setting('update_repo', GITHUB_REPO)
    try:
        req = urllib.request.Request(
            f'https://api.github.com/repos/{repo}/releases/latest',
            headers={'User-Agent': 'SirgsmPanel', 'Accept': 'application/vnd.github+json'})
        with urllib.request.urlopen(req, timeout=15) as r:
            j = json.loads(r.read().decode())
        latest = (j.get('tag_name') or '').lstrip('v')
        assets = j.get('assets', [])
        zip_url = ''
        for a in assets:
            if a.get('name', '').endswith('.zip'):
                zip_url = a.get('browser_download_url', '')
                break
        return jsonify({'current': PANEL_VERSION, 'latest': latest,
                        'update_available': bool(latest and latest != PANEL_VERSION),
                        'zip_url': zip_url, 'repo': repo,
                        'html_url': j.get('html_url', '')})
    except Exception as e:
        return jsonify({'error': f'بررسی آپدیت ناموفق بود: {e}', 'current': PANEL_VERSION})

@app.route(f'/{SECRET_PATH}/api/update/apply', methods=['POST'])
@login_required
def api_update_apply():
    data = request.get_json(silent=True) or {}
    zip_url = data.get('zip_url', '')
    if not zip_url or not zip_url.startswith('https://'):
        return jsonify({'error': 'zip_url نامعتبر'}), 400
    try:
        import zipfile
        tmp = '/tmp/sirgsm-update.zip'
        urllib.request.urlretrieve(zip_url, tmp)
        with zipfile.ZipFile(tmp) as z:
            names = z.namelist()
            # Find app.py/bot.py inside (handle top-level folder)
            for n in names:
                if n.endswith('app.py'):
                    z.extract(n, '/tmp/sirgsm-update')
                elif n.endswith('bot.py'):
                    z.extract(n, '/tmp/sirgsm-update')
        # Copy to /opt/sirgsm-panel/
        for root, dirs, files in os.walk('/tmp/sirgsm-update'):
            for f in files:
                if f in ('app.py', 'bot.py'):
                    shutil.copy(os.path.join(root, f), f'/opt/sirgsm-panel/{f}')
        subprocess.run(['systemctl', 'restart', 'sirgsm-panel'], timeout=10)
        subprocess.run(['systemctl', 'restart', 'sirgsm-bot'], timeout=15)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ---------------- L2TP / IKEv2 ----------------
def l2tp_status():
    out = {}
    for svc in ('strongswan-starter', 'xl2tpd'):
        try:
            r = subprocess.run(['systemctl', 'is-active', svc], capture_output=True, text=True, timeout=5)
            out[svc] = r.stdout.strip()
        except Exception:
            out[svc] = 'unknown'
    return out

def apply_l2tp():
    enabled = get_setting('l2tp_enabled', '0') == '1'
    secret = get_setting('l2tp_secret', '')
    if not enabled:
        for svc in ('xl2tpd', 'strongswan-starter'):
            subprocess.run(['systemctl', 'stop', svc], timeout=15)
        return {'enabled': False}
    if not secret:
        raise Exception('L2TP secret (PSK) is empty')
    # Check packages
    for binp in ('/usr/sbin/ipsec', '/usr/sbin/xl2tpd'):
        if not os.path.exists(binp):
            raise Exception(f'{binp} not found — install strongswan + xl2tpd (install.sh does it)')
    domain = get_domain()
    # /etc/ipsec.conf
    with open('/etc/ipsec.conf', 'w') as f:
        f.write(f"""config setup
    charondebug="ike 1, knl 1, cfg 0"
    uniqueids=no

conn %default
    ikelifetime=60m
    keylife=20m
    rekeymargin=3m
    keyingtries=1
    authby=secret
    left=%defaultroute
    leftid={domain}
    right=%any
    rightauth=psk
    ike=aes256-sha1-modp1024,aes256-sha256-modp2048!
    esp=aes256-sha1,aes256-sha256!
    dpdaction=clear
    dpdtimeout=120s
    dpdinterval=30s

conn L2TP-PSK
    keyexchange=ikev1
    leftprotoport=17/1701
    rightprotoport=17/%any
    forceencaps=yes
    type=transport
    auto=add
""")
    with open('/etc/ipsec.secrets', 'w') as f:
        f.write('%any : PSK "' + secret + '"\n')
    os.chmod('/etc/ipsec.secrets', 0o600)
    # /etc/xl2tpd/xl2tpd.conf
    os.makedirs('/etc/xl2tpd', exist_ok=True)
    with open('/etc/xl2tpd/xl2tpd.conf', 'w') as f:
        f.write("""[global]
port = 1701

[lns default]
ip range = 192.168.42.10-192.168.42.250
pppoptfile = /etc/ppp/options.xl2tpd
length bit = yes
""")
    os.makedirs('/etc/ppp', exist_ok=True)
    with open('/etc/ppp/options.xl2tpd', 'w') as f:
        f.write("""ms-dns 8.8.8.8
ms-dns 1.1.1.1
require-chap
refuse-pap
require-mschap-v2
nocrypt
connect-delay 5000
proxyarp
defaultroute
usepeerdns
override-addr
lock
hide-password
mtu 1280
mru 1280
""")
    # chap-secrets from DB
    con = db()
    users = con.execute("SELECT username,password FROM l2tp_users WHERE enable=1").fetchall()
    con.close()
    with open('/etc/ppp/chap-secrets', 'w') as f:
        f.write('# Sirgsm VPN Panel — L2TP users\n')
        for u in users:
            f.write(f'"{u["username"]}" * "{u["password"]}" *\n')
    os.chmod('/etc/ppp/chap-secrets', 0o600)
    # Enable IP forwarding
    with open('/etc/sysctl.d/99-sirgsm-l2tp.conf', 'w') as f:
        f.write('net.ipv4.ip_forward=1\nnet.ipv4.conf.all.accept_redirects=0\nnet.ipv4.conf.all.send_redirects=0\n')
    subprocess.run(['sysctl', '-p', '/etc/sysctl.d/99-sirgsm-l2tp.conf'], timeout=10)
    # Firewall
    for rule in (['ufw', 'allow', '500/udp'], ['ufw', 'allow', '4500/udp'], ['ufw', 'allow', '1701/udp']):
        subprocess.run(rule, timeout=15)
    # Restart services (starter provides /usr/sbin/ipsec + strongswan-starter unit)
    subprocess.run(['systemctl', 'disable', 'strongswan-swanctl'], timeout=15)
    subprocess.run(['systemctl', 'enable', 'strongswan-starter'], timeout=15)
    subprocess.run(['systemctl', 'enable', 'xl2tpd'], timeout=15)
    subprocess.run(['systemctl', 'restart', 'strongswan-starter'], timeout=30)
    subprocess.run(['systemctl', 'restart', 'xl2tpd'], timeout=30)
    return {'enabled': True, 'users': len(users)}

@app.route(f'/{SECRET_PATH}/api/l2tp', methods=['GET', 'POST'])
@login_required
def api_l2tp():
    con = db()
    if request.method == 'GET':
        rows = con.execute("SELECT * FROM l2tp_users ORDER BY id").fetchall()
        con.close()
        return jsonify({'users': [dict(r) for r in rows],
                        'enabled': get_setting('l2tp_enabled', '0') == '1',
                        'secret_set': bool(get_setting('l2tp_secret', '')),
                        'status': l2tp_status(),
                        'server': get_domain()})
    data = request.get_json(force=True)
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    if not username or not password:
        con.close()
        return jsonify({'error': 'نام کاربری و رمز الزامیه'}), 400
    if con.execute("SELECT id FROM l2tp_users WHERE username=?", (username,)).fetchone():
        con.close()
        return jsonify({'error': 'این نام کاربری وجود دارد'}), 400
    cur = con.execute("INSERT INTO l2tp_users(username,password,enable,created) VALUES(?,?,1,?)",
                      (username, password, int(time.time())))
    uid = cur.lastrowid
    con.commit()
    row = con.execute("SELECT * FROM l2tp_users WHERE id=?", (uid,)).fetchone()
    con.close()
    try:
        apply_l2tp()
    except Exception as e:
        return jsonify({'error': f'کاربر ساخته شد ولی L2TP اعمال نشد: {e}'}), 500
    return jsonify(dict(row)), 201

@app.route(f'/{SECRET_PATH}/api/l2tp/<int:uid>', methods=['PUT', 'DELETE'])
@login_required
def api_l2tp_one(uid):
    con = db()
    row = con.execute("SELECT * FROM l2tp_users WHERE id=?", (uid,)).fetchone()
    if not row:
        con.close()
        return jsonify({'error': 'یافت نشد'}), 404
    if request.method == 'DELETE':
        con.execute("DELETE FROM l2tp_users WHERE id=?", (uid,))
        con.commit()
        con.close()
        try:
            apply_l2tp()
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        return jsonify({'ok': True})
    data = request.get_json(force=True)
    sets, params = [], []
    if 'enable' in data:
        sets.append('enable=?')
        params.append(1 if data['enable'] else 0)
    if 'password' in data and str(data['password']).strip():
        sets.append('password=?')
        params.append(str(data['password']).strip())
    if sets:
        params.append(uid)
        con.execute(f"UPDATE l2tp_users SET {', '.join(sets)} WHERE id=?", params)
        con.commit()
    newrow = con.execute("SELECT * FROM l2tp_users WHERE id=?", (uid,)).fetchone()
    con.close()
    try:
        apply_l2tp()
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify(dict(newrow))

BACKUP_DIR = '/opt/sirgsm-panel/backups'

def make_backup():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = time.strftime('%Y%m%d-%H%M%S')
    dest = os.path.join(BACKUP_DIR, f'panel-{ts}.db')
    con = db()
    # Use sqlite backup API for consistency
    src = con
    dst = sqlite3.connect(dest)
    src.backup(dst)
    dst.close()
    con.close()
    # Keep last 7
    try:
        files = sorted(os.listdir(BACKUP_DIR))
        for f in files[:-7]:
            os.remove(os.path.join(BACKUP_DIR, f))
    except Exception:
        pass
    return dest

def tg_send_document(token, chat_id, filepath, caption=''):
    url = f'https://api.telegram.org/bot{token}/sendDocument'
    boundary = '----SirgsmBackupBoundary'
    with open(filepath, 'rb') as fh:
        data = fh.read()
    body = io.BytesIO()
    body.write(f'--{boundary}\r\n'.encode())
    body.write(f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'.encode())
    if caption:
        body.write(f'--{boundary}\r\n'.encode())
        body.write(b'Content-Disposition: form-data; name="caption"\r\n\r\n')
        body.write(caption.encode('utf-8') + b'\r\n')
    body.write(f'--{boundary}\r\n'.encode())
    body.write(f'Content-Disposition: form-data; name="document"; filename="{os.path.basename(filepath)}"\r\n'.encode())
    body.write(b'Content-Type: application/octet-stream\r\n\r\n')
    body.write(data + b'\r\n')
    body.write(f'--{boundary}--\r\n'.encode())
    req = urllib.request.Request(url, data=body.getvalue(),
                                 headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
    try:
        r = urllib.request.urlopen(req, timeout=60)
        return json.loads(r.read().decode(errors='ignore')).get('ok', False)
    except Exception as e:
        print(f'backup send failed: {e}', flush=True)
        return False

def backup_loop():
    while True:
        try:
            time.sleep(3600)
            if get_setting('backup_enabled', '1') != '1':
                continue
            try:
                interval = int(get_setting('backup_interval_hours', '24') or 24) * 3600
            except Exception:
                interval = 24 * 3600
            try:
                last = int(get_setting('backup_last', '0') or 0)
            except Exception:
                last = 0
            if time.time() - last < interval:
                continue
            token = get_setting('bot_token', '')
            admin = get_setting('bot_admin_id', '')
            if not token or not admin:
                continue
            dest = make_backup()
            ok = tg_send_document(token, admin, dest,
                                  caption=f'Sirgsm VPN Panel — Auto backup {time.strftime("%Y-%m-%d %H:%M")}')
            if ok:
                set_setting('backup_last', str(int(time.time())))
                print(f'Auto backup sent: {dest}', flush=True)
        except Exception as e:
            print(f'backup loop error: {e}', flush=True)

@app.route(f'/{SECRET_PATH}/api/backup', methods=['GET', 'POST'])
@login_required
def api_backup():
    if request.method == 'GET':
        # Download current DB
        dest = make_backup()
        return send_file(dest, as_attachment=True, download_name=os.path.basename(dest),
                         mimetype='application/octet-stream')
    # POST: manual backup + send to bot
    token = get_setting('bot_token', '')
    admin = get_setting('bot_admin_id', '')
    if not token or not admin:
        return jsonify({'error': 'توکن ربات یا آیدی ادمین ست نشده'}), 400
    dest = make_backup()
    ok = tg_send_document(token, admin, dest,
                          caption=f'Sirgsm VPN Panel — Manual backup {time.strftime("%Y-%m-%d %H:%M")}')
    if ok:
        set_setting('backup_last', str(int(time.time())))
        return jsonify({'ok': True, 'file': os.path.basename(dest)})
    return jsonify({'error': 'ارسال به تلگرام ناموفق بود'}), 500

@app.route(f'/{SECRET_PATH}/api/backup/restore', methods=['POST'])
@login_required
def api_backup_restore():
    f = request.files.get('file')
    if not f:
        return jsonify({'error': 'فایل آپلود نشد'}), 400
    tmp = '/tmp/sirgsm-restore.db'
    f.save(tmp)
    # Validate: sqlite header + clients table
    try:
        with open(tmp, 'rb') as fh:
            header = fh.read(16)
        if not header.startswith(b'SQLite format 3'):
            return jsonify({'error': 'فایل دیتابیس معتبر نیست'}), 400
        con = sqlite3.connect(tmp)
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        con.close()
        if 'clients' not in tables or 'settings' not in tables:
            return jsonify({'error': 'فایل دیتابیس پنل نیست (جدول clients/settings ندارد)'}), 400
    except Exception as e:
        return jsonify({'error': f'اعتبارسنجی ناموفق بود: {e}'}), 400
    # Backup current before restore
    make_backup()
    shutil.copy(tmp, DB_PATH)
    try:
        build_xray_config()
        restart_xray()
    except Exception:
        pass
    # Restart panel to reload (new DB)
    try:
        subprocess.run(['systemctl', 'restart', 'sirgsm-panel'], timeout=10)
    except Exception:
        pass
    return jsonify({'ok': True})

@app.route(f'/{SECRET_PATH}/api/users/export')
@login_required
def api_users_export():
    fmt = request.args.get('format', 'sirgsm')
    con = db()
    rows = con.execute("SELECT * FROM clients ORDER BY id").fetchall()
    con.close()
    if fmt == 'marzban':
        out = []
        for c in rows:
            proxies = {}
            if c['inbound'] == 'vless':
                proxies['vless'] = {'id': c['uuid']}
            elif c['inbound'] == 'trojan':
                proxies['trojan'] = {'password': c['password']}
            elif c['inbound'] == 'vmess':
                proxies['vmess'] = {'id': c['uuid']}
            elif c['inbound'] == 'ss':
                proxies['shadowsocks'] = {'password': c['password']}
            out.append({
                'username': c['email'],
                'proxies': proxies,
                'expire': c['expiry'] or 0,
                'data_limit': c['traffic_limit'] or 0,
                'data_limit_reset_day': 0,
                'status': 'active' if c['enable'] else 'disabled',
                'on_hold_timeout': 0,
                'on_hold_expire_day': 0,
                'note': c['note'] or '',
            })
        return jsonify(out)
    out = []
    for c in rows:
        out.append({
            'email': c['email'], 'inbound': c['inbound'],
            'uuid': c['uuid'], 'password': c['password'],
            'traffic_limit': c['traffic_limit'] or 0,
            'expiry': c['expiry'] or 0,
            'ip_limit': c['ip_limit'] or 0,
            'enable': bool(c['enable']), 'note': c['note'] or '',
            'up': c['up'] or 0, 'down': c['down'] or 0,
        })
    return jsonify(out)

@app.route(f'/{SECRET_PATH}/api/users/import', methods=['POST'])
@login_required
def api_users_import():
    data = request.get_json(force=True)
    if not isinstance(data, list):
        return jsonify({'error': 'فایل باید لیست JSON باشه'}), 400
    con = db()
    created, skipped = 0, 0
    for item in data:
        # Support sirgsm format + marzban format
        email = item.get('email') or item.get('username') or ''
        inbound = item.get('inbound', '')
        uuid_v = item.get('uuid', '')
        password = item.get('password', '')
        traffic_limit = item.get('traffic_limit', item.get('data_limit', 0)) or 0
        expiry = item.get('expiry', item.get('expire', 0)) or 0
        ip_limit = item.get('ip_limit', 0) or 0
        enable = item.get('enable', True)
        if isinstance(enable, str):
            enable = enable.lower() in ('1', 'true', 'active')
        note = item.get('note', '') or ''
        proxies = item.get('proxies', {})
        if not inbound and proxies:
            if 'vless' in proxies:
                inbound = 'vless'
                uuid_v = proxies['vless'].get('id', '')
            elif 'trojan' in proxies:
                inbound = 'trojan'
                password = proxies['trojan'].get('password', '')
            elif 'vmess' in proxies:
                inbound = 'vmess'
                uuid_v = proxies['vmess'].get('id', '')
            elif 'shadowsocks' in proxies:
                inbound = 'ss'
                password = proxies['shadowsocks'].get('password', '')
        if not email or inbound not in INBOUNDS_META:
            skipped += 1
            continue
        if con.execute("SELECT id FROM clients WHERE email=?", (email,)).fetchone():
            skipped += 1
            continue
        # Generate missing creds
        if inbound in ('vless', 'vmess') and not uuid_v:
            uuid_v = str(uuid.uuid4())
        if inbound == 'trojan' and not password:
            password = secrets.token_urlsafe(12)[:16]
        if inbound == 'ss' and not password:
            password = base64.b64encode(os.urandom(16)).decode()
        con.execute("INSERT INTO clients(email,inbound,uuid,password,traffic_limit,expiry,ip_limit,enable,created,note) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (email, inbound, uuid_v, password, int(traffic_limit), int(expiry),
                     int(ip_limit), 1 if enable else 0, int(time.time()), note))
        created += 1
    con.commit()
    con.close()
    try:
        build_xray_config()
        restart_xray()
    except Exception as e:
        return jsonify({'error': f'ایمپورت شد ولی Xray restart نشد: {e}', 'created': created, 'skipped': skipped}), 500
    return jsonify({'ok': True, 'created': created, 'skipped': skipped})

@app.route(f'/{SECRET_PATH}/api/clients/bulk', methods=['POST'])
@login_required
def api_clients_bulk():
    data = request.get_json(force=True)
    ids = data.get('ids') or []
    action = data.get('action', '')
    if not ids or action not in ('delete', 'reset', 'enable', 'disable'):
        return jsonify({'error': 'درخواست نامعتبر'}), 400
    con = db()
    placeholders = ','.join('?' for _ in ids)
    if action == 'delete':
        con.execute(f"DELETE FROM clients WHERE id IN ({placeholders})", ids)
    elif action == 'reset':
        con.execute(f"UPDATE clients SET up=0, down=0, last_up=0, last_down=0 WHERE id IN ({placeholders})", ids)
    elif action == 'enable':
        con.execute(f"UPDATE clients SET enable=1 WHERE id IN ({placeholders})", ids)
    elif action == 'disable':
        con.execute(f"UPDATE clients SET enable=0 WHERE id IN ({placeholders})", ids)
    con.commit()
    con.close()
    try:
        build_xray_config()
        restart_xray()
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({'ok': True, 'count': len(ids)})

@app.route(f'/{SECRET_PATH}/qr/<int:cid>')
@login_required
def qr_client(cid):
    if not HAS_QR:
        return 'QR unavailable', 500
    con = db()
    row = con.execute("SELECT * FROM clients WHERE id=?", (cid,)).fetchone()
    con.close()
    if not row:
        return 'Not found', 404
    links = gen_links(row)
    text = links[1] if len(links) > 1 else (links[0] if links else '')
    img = qrcode.make(text)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

@app.route(f'/{SECRET_PATH}/qr-sub/<int:cid>')
@login_required
def qr_sub(cid):
    if not HAS_QR:
        return 'QR unavailable', 500
    con = db()
    row = con.execute("SELECT * FROM clients WHERE id=?", (cid,)).fetchone()
    con.close()
    if not row:
        return 'Not found', 404
    img = qrcode.make(sub_url(row))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

@app.route(f'/{SECRET_PATH}/api/warp')
@login_required
def api_warp():
    w = load_warp()
    return jsonify({'enabled': bool(w), 'outbound': w})

LANDING_DEFAULT = r"""<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} — اشتراک</title>
<style>
*{box-sizing:border-box}body{margin:0;font-family:Tahoma,sans-serif;background:#0b1220;color:#e6edf7;min-height:100vh;padding:20px}
.wrap{max-width:640px;margin:0 auto}
.head{text-align:center;margin:24px 0}
.badge{width:64px;height:64px;border-radius:18px;background:linear-gradient(135deg,#10b981,#0ea5e9);display:inline-flex;align-items:center;justify-content:center;font-weight:900;font-size:28px;color:#04121a}
h1{margin:12px 0 4px;font-size:24px} .sub{color:#8ea0bd}
.card{background:linear-gradient(160deg,#111c33,#0d1526);border:1px solid #1e2d4d;border-radius:16px;padding:18px;margin:14px 0}
.row{display:flex;gap:10px;flex-wrap:wrap;justify-content:space-between}
.kv{font-size:14px;margin:6px 0}.kv b{color:#7dd3fc}
.bar{height:10px;background:#1e2d4d;border-radius:6px;overflow:hidden;margin:8px 0}
.bar i{display:block;height:100%;background:linear-gradient(90deg,#10b981,#0ea5e9)}
textarea{width:100%;background:#0a1120;color:#cfe3ff;border:1px solid #22355c;border-radius:10px;padding:10px;font-size:12px;direction:ltr;text-align:left}
.btn{background:linear-gradient(135deg,#10b981,#0ea5e9);color:#04121a;border:0;border-radius:10px;padding:10px 18px;font-weight:700;cursor:pointer;font-family:inherit}
.btn2{background:#1e2d4d;color:#e6edf7;border:1px solid #2b4066;border-radius:10px;padding:10px 18px;cursor:pointer;font-family:inherit}
.qrs{display:flex;gap:16px;justify-content:center;flex-wrap:wrap;text-align:center}
.qrs img{width:150px;height:150px;background:#fff;border-radius:12px;padding:6px}
.pill{display:inline-block;padding:3px 10px;border-radius:20px;background:#065f46;color:#a7f3d0;font-size:12px}
.pill.off{background:#7f1d1d;color:#fecaca}
.foot{text-align:center;color:#8ea0bd;font-size:12px;margin:24px 0}
</style></head><body><div class="wrap">
<div class="head"><div class="badge">S</div><h1>{title}</h1><div class="sub">{subtitle}</div></div>
<div class="card">
<div class="row"><div class="kv">👤 کاربر: <b>{email}</b></div><div class="kv">🔌 پروتکل: <b>{protocol}</b></div></div>
<div class="kv">📊 مصرف: <b>{used} / {limit}</b></div><div class="bar"><i style="width:{pct}%"></i></div>
<div class="row"><div class="kv">⏳ انقضا: <b>{expiry}</b></div><div class="kv">🌐 سقف IP: <b>{ip_limit}</b></div><div class="kv">🟢 آنلاین: <b>{online}</b></div></div>
<div class="kv">وضعیت: <span class="pill {status_cls}">{status_fa}</span></div>
</div>
<div class="card"><h3 style="margin-top:0">🔗 لینک‌ها</h3>
{links_html}
<label>لینک اشتراک (Sub)</label><textarea rows="2" readonly>{sub}</textarea>
<div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
<button class="btn" onclick="navigator.clipboard.writeText('{sub}');this.textContent='کپی شد ✓'">کپی ساب</button>
<a class="btn2" href="{sub}/raw" style="text-decoration:none">نسخه خام (برای کلاینت)</a></div></div>
<div class="card"><h3 style="margin-top:0">📷 QR</h3><div class="qrs">
<div><img src="data:image/png;base64,{qr_link}"><br><small>QR لینک</small></div>
<div><img src="data:image/png;base64,{qr_sub}"><br><small>QR اشتراک</small></div></div></div>
<div class="foot">{footer}</div>
</div></body></html>"""

def qr_b64(text):
    if not HAS_QR:
        return ''
    img = qrcode.make(text)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode()

def is_browser_ua(ua):
    ua = (ua or '').lower()
    clients = ('v2ray', 'clash', 'sing-box', 'singbox', 'nekoray', 'streisand', 'foxray',
               'v2rayn', 'v2rayng', 'hiddify', 'shadowrocket', 'outline', 'curl', 'wget', 'python')
    if any(c in ua for c in clients):
        return False
    return True

@app.route('/sub/<uid>')
@app.route('/sub/<uid>/raw')
def subscription(uid):
    con = db()
    row = con.execute("SELECT * FROM clients WHERE uuid=? OR password=?", (uid, uid)).fetchone()
    con.close()
    if not row:
        return 'Not found', 404
    links = gen_links(row)
    raw = request.path.endswith('/raw') or request.args.get('raw') == '1'
    if raw or not is_browser_ua(request.headers.get('User-Agent', '')):
        return '\n'.join(links), 200, {'Content-Type': 'text/plain; charset=utf-8'}
    # Landing page (browser)
    online = query_online_users().get(row['email'], 0)
    total = (row['up'] or 0) + (row['down'] or 0)
    lim = row['traffic_limit'] or 0
    pct = min(100, round(total / lim * 100)) if lim else 0
    now = int(time.time())
    if not row['enable']:
        status_fa, status_cls = 'غیرفعال', 'off'
    elif row['expiry'] and now >= row['expiry']:
        status_fa, status_cls = 'منقضی', 'off'
    elif lim and total >= lim:
        status_fa, status_cls = 'پر شده', 'off'
    else:
        status_fa, status_cls = 'فعال', ''
    proto_fa = {'vless': 'VLESS', 'trojan': 'Trojan', 'ss': 'Shadowsocks', 'vmess': 'VMess'}.get(row['inbound'], row['inbound'])
    links_html = ''.join(
        f'<label>لینک {i+1}</label><textarea rows="3" readonly>{l}</textarea>'
        for i, l in enumerate(links))
    tpl = get_setting('landing_template', '') or LANDING_DEFAULT
    vals = {
        'title': get_setting('landing_title', 'Sirgsm VPN'),
        'subtitle': get_setting('landing_subtitle', 'اشتراک VPN شما'),
        'footer': get_setting('landing_footer', SPONSOR),
        'email': row['email'], 'protocol': proto_fa,
        'used': fmt_bytes(total), 'limit': fmt_bytes(lim) if lim else 'نامحدود',
        'pct': str(pct), 'expiry': fmt_date(row['expiry']),
        'ip_limit': str(row['ip_limit']) if row['ip_limit'] else 'نامحدود',
        'online': str(online), 'status_fa': status_fa, 'status_cls': status_cls,
        'links_html': links_html, 'sub': sub_url(row),
        'qr_link': qr_b64(links[1] if len(links) > 1 else (links[0] if links else '')),
        'qr_sub': qr_b64(sub_url(row)),
    }
    html = tpl
    for k, v in vals.items():
        html = html.replace('{' + k + '}', str(v))
    return html, 200, {'Content-Type': 'text/html; charset=utf-8'}

@app.route('/')
def root():
    return redirect(f'/{SECRET_PATH}/login')

# ---------------- HTML ----------------
LOGIN_HTML = r"""<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Sirgsm VPN Panel — ورود</title>
<style>
*{box-sizing:border-box}body{margin:0;font-family:Tahoma,sans-serif;background:#0b1220;color:#e6edf7;display:flex;min-height:100vh;align-items:center;justify-content:center;padding:20px}
.card{width:100%;max-width:380px;background:linear-gradient(160deg,#111c33,#0d1526);border:1px solid #1e2d4d;border-radius:20px;padding:28px;box-shadow:0 20px 60px rgba(0,0,0,.5)}
.logo{display:flex;align-items:center;gap:12px;margin-bottom:18px}
.badge{width:46px;height:46px;border-radius:14px;background:linear-gradient(135deg,#10b981,#0ea5e9);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:18px;color:#04121a}
h1{font-size:20px;margin:0}p{color:#8ea0bd;font-size:13px;margin:4px 0 0}
label{display:block;font-size:13px;color:#aebdd6;margin:14px 0 6px}
input{width:100%;padding:12px;border-radius:12px;border:1px solid #24365c;background:#0a1120;color:#fff;font-size:14px}
button{width:100%;margin-top:18px;padding:12px;border:0;border-radius:12px;background:linear-gradient(135deg,#10b981,#0ea5e9);color:#04121a;font-weight:800;font-size:15px;cursor:pointer}
.err{background:#3b1420;border:1px solid #7f1d2d;color:#fda4af;padding:10px;border-radius:10px;font-size:13px;margin-top:12px}
</style></head><body><div class="card">
<div class="logo"><div class="badge">S</div><div><h1>Sirgsm VPN Panel</h1><p>پنل اختصاصی VPN — ورود مدیر</p></div></div>
{% if error %}<div class="err">{{ error }}</div>{% endif %}
<form method="post"><label>نام کاربری</label><input name="username" required autocomplete="username">
<label>رمز عبور</label><input name="password" type="password" required autocomplete="current-password">
<button type="submit">ورود</button></form>
<p style="text-align:center;margin-top:14px">nhv.3tayesh.ir<br><small style="color:#8ea0bd">Sponsor: Sirgsm.ir — Navid Haghbayan</small></p></div></body></html>"""

INDEX_HTML = r"""<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Sirgsm VPN Panel</title>
<style>
*{box-sizing:border-box}body{margin:0;font-family:Tahoma,sans-serif;background:#0b1220;color:#e6edf7}
a{color:#38bdf8;text-decoration:none}
.top{position:sticky;top:0;z-index:10;background:rgba(11,18,32,.92);backdrop-filter:blur(10px);border-bottom:1px solid #1e2d4d;padding:12px 16px;display:flex;align-items:center;gap:12px}
.badge{width:38px;height:38px;border-radius:12px;background:linear-gradient(135deg,#10b981,#0ea5e9);display:flex;align-items:center;justify-content:center;font-weight:900;color:#04121a}
.top h1{font-size:17px;margin:0}.top small{color:#8ea0bd}
.top .sp{flex:1}
.btn{border:1px solid #24365c;background:#111c33;color:#e6edf7;padding:9px 14px;border-radius:11px;cursor:pointer;font-family:inherit;font-size:13px}
.btn.primary{background:linear-gradient(135deg,#10b981,#0ea5e9);color:#04121a;border:0;font-weight:800}
.btn.danger{background:#3b1420;border-color:#7f1d2d;color:#fda4af}
.btn.sm{padding:6px 10px;font-size:12px;border-radius:9px}
.wrap{max-width:1180px;margin:0 auto;padding:16px}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0 14px}
.tab{padding:9px 16px;border-radius:999px;border:1px solid #24365c;background:#111c33;cursor:pointer;font-size:13px}
.tab.on{background:linear-gradient(135deg,#10b981,#0ea5e9);color:#04121a;font-weight:800;border:0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.card{background:linear-gradient(160deg,#111c33,#0d1526);border:1px solid #1e2d4d;border-radius:16px;padding:16px}
.card h3{margin:0 0 6px;font-size:13px;color:#8ea0bd;font-weight:400}
.big{font-size:22px;font-weight:900}
.pill{display:inline-block;padding:3px 10px;border-radius:999px;font-size:12px;background:#0f2a1f;color:#6ee7b7;border:1px solid #14532d}
.pill.off{background:#3b1420;color:#fda4af;border-color:#7f1d2d}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:10px 8px;border-bottom:1px solid #1e2d4d;text-align:right;vertical-align:top}
th{color:#8ea0bd;font-weight:400}
.bar{height:8px;background:#0a1120;border-radius:99px;overflow:hidden;margin-top:6px}
.bar i{display:block;height:100%;background:linear-gradient(90deg,#10b981,#0ea5e9)}
.mono{font-family:Consolas,monospace;direction:ltr;text-align:left;word-break:break-all}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.6);display:none;align-items:center;justify-content:center;padding:16px;z-index:20}
.modal.open{display:flex}
.box{width:100%;max-width:520px;background:#0d1526;border:1px solid #24365c;border-radius:18px;padding:20px;max-height:90vh;overflow:auto}
.box h2{margin:0 0 12px;font-size:16px}
label{display:block;font-size:13px;color:#aebdd6;margin:12px 0 6px}
input,select,textarea{width:100%;padding:11px;border-radius:11px;border:1px solid #24365c;background:#0a1120;color:#fff;font-family:inherit;font-size:13px}
.row{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
.toast{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);background:#0f2a1f;border:1px solid #14532d;color:#a7f3d0;padding:11px 18px;border-radius:12px;display:none;z-index:30;font-size:13px}
pre{background:#070d18;border:1px solid #1e2d4d;border-radius:12px;padding:12px;overflow:auto;font-size:12px;direction:ltr;text-align:left;max-height:420px}
.hint{color:#8ea0bd;font-size:12px;line-height:1.9}
@media(max-width:640px){table{font-size:12px}th,td{padding:8px 5px}}
</style></head><body>
<div class="top"><div class="badge">S</div><div><h1>Sirgsm VPN Panel</h1><small>nhv.3tayesh.ir — VLESS • Trojan • Shadowsocks • VMess</small></div>
<div class="sp"></div><button class="btn sm" onclick="refreshAll()">↻ تازه‌سازی</button>
<a class="btn sm" href="/{{ secret }}/logout">خروج</a></div>
<div class="wrap">
<div class="tabs">
<button class="tab on" data-t="dash" onclick="showTab('dash')">داشبورد</button>
<button class="tab" data-t="users" onclick="showTab('users')">کاربران</button>
<button class="tab" data-t="routing" onclick="showTab('routing')">مسیریابی</button>
<button class="tab" data-t="logs" onclick="showTab('logs')">لاگ Xray</button>
<button class="tab" data-t="settings" onclick="showTab('settings')">تنظیمات</button>
</div>

<section id="tab-dash">
<div class="grid" id="dashCards"></div>
<h3 style="margin:18px 0 10px">اینباندها</h3>
<div class="grid" id="inboundCards"></div>
</section>

<section id="tab-users" style="display:none">
<div class="row" style="margin:0 0 12px">
<select id="fInbound" onchange="loadClients()" style="max-width:220px">
<option value="">همه پروتکل‌ها</option><option value="vless">VLESS Reality (443)</option>
<option value="trojan">Trojan Reality (8443)</option><option value="ss">Shadowsocks 2022 (8388)</option><option value="vmess">VMess Reality (2096)</option></select>
<input id="fSearch" placeholder="جستجو ایمیل..." oninput="loadClients()" style="max-width:260px">
<div style="flex:1"></div>
<button class="btn" onclick="exportUsers('sirgsm')">⬇ خروجی (Sirgsm)</button>
<button class="btn" onclick="exportUsers('marzban')">⬇ خروجی (Marzban)</button>
<label class="btn" style="cursor:pointer">⬆ ایمپورت<input type="file" id="importFile" accept=".json" style="display:none" onchange="importUsers()"></label>
<button class="btn primary" onclick="openAdd()">+ کاربر جدید</button></div>
<div class="row" id="bulkBar" style="display:none;margin:0 0 10px">
<span id="bulkCount"></span>
<button class="btn sm" onclick="bulkAction('enable')">فعال</button>
<button class="btn sm" onclick="bulkAction('disable')">غیرفعال</button>
<button class="btn sm" onclick="bulkAction('reset')">ریست مصرف</button>
<button class="btn sm danger" onclick="bulkAction('delete')">حذف</button></div>
<div class="card" style="overflow:auto"><table><thead><tr>
<th><input type="checkbox" id="selAll" onchange="toggleAll(this.checked)"></th><th>ایمیل</th><th>پروتکل</th><th>مصرف / سقف</th><th>انقضا</th><th>آنلاین</th><th>وضعیت</th><th>عملیات</th>
</tr></thead><tbody id="clientsBody"></tbody></table></div>
<p class="hint">سقف حجم: ۰ = نامحدود | مدت: ۰ = بدون انقضا. بعد از ساخت/ویرایش، Xray خودکار restart می‌شه.</p>
</section>

<section id="tab-routing" style="display:none">
<div class="card"><h3 style="margin-top:0">افزودن قانون</h3>
<div class="row" style="margin:0">
<select id="rType" style="max-width:160px"><option value="domain">دامنه</option><option value="ip">IP</option><option value="port">پورت</option><option value="protocol">پروتکل</option></select>
<input id="rValue" placeholder="مثال: geosite:ir یا geoip:private" style="flex:1;min-width:200px">
<select id="rOut" style="max-width:150px"><option value="direct">مستقیم (direct)</option><option value="block">بلاک (block)</option><option value="warp">Warp (warp)</option></select>
<input id="rRemark" placeholder="توضیح (اختیاری)" style="max-width:220px">
<button class="btn primary" onclick="addRouting()">افزودن</button></div>
<div class="row">
<button class="btn sm" onclick="preset('domain','geosite:category-ads-all','block','بلاک تبلیغات')">+ بلاک تبلیغات</button>
<button class="btn sm" onclick="preset('ip','geoip:private','block','بلاک IP خصوصی')">+ بلاک خصوصی</button>
<button class="btn sm" onclick="preset('domain','geosite:ir','direct','مستقیم ایران')">+ مستقیم ایران</button>
<button class="btn sm" onclick="preset('ip','geoip:ir','direct','مستقیم IP ایران')">+ مستقیم IP ایران</button>
<button class="btn sm" onclick="preset('domain','domain:youtube.com','warp','Warp: یوتیوب')">+ Warp یوتیوب</button>
<button class="btn sm" onclick="preset('domain','domain:google.com','warp','Warp: گوگل')">+ Warp گوگل</button>
<button class="btn sm" onclick="preset('domain','domain:openai.com','warp','Warp: اوپن‌ای‌آی')">+ Warp اوپن‌ای‌آی</button>
<button class="btn sm" onclick="preset('domain','domain:telegram.org','warp','Warp: تلگرام')">+ Warp تلگرام</button>
</div></div>
<div class="card" style="margin-top:12px;overflow:auto"><table><thead><tr><th>نوع</th><th>مقدار</th><th>خروجی</th><th>توضیح</th><th>فعال</th><th></th></tr></thead>
<tbody id="routingBody"></tbody></table></div>
<p class="hint">قوانین از بالا به پایین چک می‌شن. خروجی direct یعنی بدون VPN، block یعنی قطع.</p>
</section>

<section id="tab-logs" style="display:none"><div class="card"><pre id="logsPre">در حال بارگذاری...</pre></div></section>

<section id="tab-settings" style="display:none">
<div class="grid">
<div class="card"><h3 style="margin-top:0">دامنه و پورت پنل</h3>
<label>دامنه (برای لینک‌ها و SSL)</label><input id="sDomain" dir="ltr">
<label>پورت پنل (بعد از ذخیره ری‌استارت می‌شه)</label><input id="sPort" type="number" dir="ltr">
<div class="row"><button class="btn primary" onclick="saveDomain()">ذخیره</button></div>
<p class="hint">تغییر دامنه لینک‌ها و Xray رو بازسازی می‌کنه.</p></div>
<div class="card"><h3 style="margin-top:0">تغییر رمز پنل</h3>
<label>رمز جدید (حداقل ۸ کاراکتر)</label><input id="newPass" type="password">
<div class="row"><button class="btn primary" onclick="changePass()">ذخیره</button></div></div>
<div class="card"><h3 style="margin-top:0">سرویس‌ها</h3>
<p class="hint" id="xrayState">...</p>
<div class="row">
<button class="btn" onclick="restartXray()">Restart Xray</button>
<button class="btn" onclick="restartPanel()">Restart Panel</button>
<button class="btn" onclick="restartBot()">Restart Bot</button></div></div>
<div class="card"><h3 style="margin-top:0">🤖 ربات تلگرام</h3>
<label>توکن ربات (از @BotFather)</label><input id="sBotToken" dir="ltr" placeholder="••••">
<label>آیدی عددی ادمین (از @userinfobot)</label><input id="sBotAdmin" dir="ltr">
<label><input type="checkbox" id="sBotEnabled"> ربات فعال</label>
<div class="row"><button class="btn primary" onclick="saveBot()">ذخیره و ری‌استارت ربات</button></div>
<p class="hint">بعد از ذخیره، سرویس sirgsm-bot ری‌استارت می‌شه.</p></div>
<div class="card"><h3 style="margin-top:0">🔒 SSL (Let's Encrypt)</h3>
<label>ایمیل (برای certbot)</label><input id="sSslEmail" dir="ltr">
<p class="hint" id="sslState">...</p>
<div class="row"><button class="btn primary" onclick="issueSsl()">دریافت گواهی SSL</button></div>
<p class="hint">دامنه باید به این سرور اشاره کنه (DNS). پورت ۸۰ باید آزاد باشه.</p></div>
<div class="card"><h3 style="margin-top:0">🔌 ترنسپورت اینباندها</h3>
<label>VLESS</label><select id="sTrVless"></select>
<label>Trojan</label><select id="sTrTrojan"></select>
<label>VMess</label><select id="sTrVmess"></select>
<label>Shadowsocks</label><select id="sTrSs"></select>
<div class="row"><button class="btn primary" onclick="saveTransports()">ذخیره (بازسازی Xray)</button></div>
<p class="hint">برای TLS باید اول SSL گرفته باشی. Reality نیازی به گواهی نداره.</p></div>
<div class="card"><h3 style="margin-top:0">🖼 لندینگ‌پیج اشتراک</h3>
<label>عنوان</label><input id="sLandTitle">
<label>زیرعنوان</label><input id="sLandSub">
<label>فوتر</label><input id="sLandFoot">
<label>قالب HTML سفارشی (خالی = پیش‌فرض) — متغیرها: {title} {email} {used} {limit} {expiry} {links_html} {sub} {qr_link} {qr_sub}</label>
<textarea id="sLandTpl" rows="6" dir="ltr" style="font-size:11px"></textarea>
<div class="row"><button class="btn primary" onclick="saveLanding()">ذخیره</button></div></div>
<div class="card"><h3 style="margin-top:0">📡 L2TP / IKEv2</h3>
<label><input type="checkbox" id="sL2tpEnabled"> L2TP فعال</label>
<label>PSK / Secret (IPsec)</label><input id="sL2tpSecret" dir="ltr">
<div class="row"><button class="btn primary" onclick="saveL2tp()">ذخیره و اعمال</button></div>
<p class="hint" id="l2tpState">...</p>
<h4>کاربران L2TP</h4>
<div class="row"><input id="l2tpUser" placeholder="نام کاربری" style="max-width:150px"><input id="l2tpPass" placeholder="رمز" style="max-width:150px">
<button class="btn sm primary" onclick="addL2tp()">+ افزودن</button></div>
<div id="l2tpList" style="margin-top:10px"></div>
<p class="hint">سرور: <span class="mono" id="l2tpServer"></span> | نوع: L2TP/IPsec (PSK) | پورت‌ها: UDP 500/4500/1701</p></div>
<div class="card"><h3 style="margin-top:0">💾 بکاپ و ریستور</h3>
<label><input type="checkbox" id="sBackupEnabled" onchange="saveBackupSettings()"> بکاپ خودکار (هر ۲۴ ساعت به ربات تلگرام)</label>
<label>بازه (ساعت)</label><input id="sBackupHours" type="number" min="1" dir="ltr" onchange="saveBackupSettings()">
<p class="hint" id="backupState">...</p>
<div class="row">
<button class="btn" onclick="downloadBackup()">⬇ دانلود بکاپ (DB)</button>
<button class="btn" onclick="sendBackup()">📤 بکاپ دستی به ربات</button>
<label class="btn" style="cursor:pointer">⬆ ریستور<input type="file" id="restoreFile" accept=".db" style="display:none" onchange="restoreBackup()"></label></div>
<p class="hint">ریستور دیتابیس فعلی رو جایگزین می‌کنه (قبلش خودکار بکاپ گرفته می‌شه).</p></div>
<div class="card"><h3 style="margin-top:0">⬆ آپدیت پنل</h3>
<p class="hint">نسخه فعلی: <b id="curVer">...</b> | ریپو: <span class="mono" id="updRepo"></span></p>
<label>ریپوی گیت‌هاب (owner/repo)</label><input id="sUpdRepo" dir="ltr">
<div class="row"><button class="btn" onclick="saveUpdRepo()">ذخیره ریپو</button>
<button class="btn" onclick="checkUpdate()">بررسی آپدیت</button></div>
<p class="hint" id="updState">...</p>
<div class="row"><button class="btn primary" onclick="applyUpdate()" id="updBtn" style="display:none">آپدیت به نسخه جدید</button></div></div>
<div class="card"><h3 style="margin-top:0">درباره</h3>
<p class="hint">Sirgsm VPN Panel v<span id="aboutVer"></span> — ساخته‌شده از صفر (بدون ریپوی آماده).<br>
Sponsor: Sirgsm.ir — Navid Haghbayan<br>
SIP Gateway (Asterisk) فقط نمایش داده می‌شه و مدیریت نمی‌شه.<br>
آدرس پنل: <span class="mono" id="panelAddr"></span></p></div>
</div></section>
</div>

<p style="text-align:center;color:#8ea0bd;font-size:12px;margin:24px 0 8px">Sirgsm VPN Panel — Sponsor: <a href="https://sirgsm.ir" target="_blank">Sirgsm.ir</a> — Navid Haghbayan</p>
<div class="modal" id="modal"><div class="box" id="modalBox"></div></div>
<div class="toast" id="toast"></div>

<script>
const S = "{{ secret }}";
const base = "/" + S;
function toast(m){const t=document.getElementById('toast');t.textContent=m;t.style.display='block';setTimeout(()=>t.style.display='none',2600);}
function showTab(t){document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('on',b.dataset.t===t));
['dash','users','routing','logs','settings'].forEach(x=>document.getElementById('tab-'+x).style.display=x===t?'block':'none');
if(t==='dash')loadDash();if(t==='users')loadClients();if(t==='routing')loadRouting();if(t==='logs')loadLogs();if(t==='settings')loadSettings();}
function refreshAll(){loadDash();toast('تازه‌سازی شد');}
function fmtB(n){n=+n||0;const u=['B','KB','MB','GB','TB'];let i=0;while(n>=1024&&i<4){n/=1024;i++;}return n.toFixed(i?1:0)+' '+u[i];}
function fmtD(ts){if(!ts)return 'نامحدود';const d=new Date(ts*1000);return d.toLocaleDateString('fa-IR');}
async function api(path,opt){const r=await fetch(base+path,opt);const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.error||'خطا');return j;}
async function loadDash(){
 const d=await api('/api/dashboard');const s=d.server;
 const perNet = s.net_per ? Object.entries(s.net_per).map(([k,v])=>`${k}: ↓${fmtB(v.rx)} ↑${fmtB(v.tx)}`).join('<br>') : '';
 document.getElementById('dashCards').innerHTML=`
 <div class="card"><h3>CPU (Load)</h3><div class="big">${s.load||'-'}</div></div>
 <div class="card"><h3>RAM</h3><div class="big">${fmtB(s.mem_used)} / ${fmtB(s.mem_total)}</div><div class="bar"><i style="width:${s.mem_pct}%"></i></div><small>${s.mem_pct}%</small></div>
 <div class="card"><h3>دیسک</h3><div class="big">${fmtB(s.disk_used)} / ${fmtB(s.disk_total)}</div><div class="bar"><i style="width:${s.disk_pct}%"></i></div><small>${s.disk_pct}%</small></div>
 <div class="card"><h3>آپ‌تایم</h3><div class="big">${Math.floor(s.uptime/86400)} روز</div><small>${Math.floor(s.uptime%86400/3600)} ساعت</small></div>
 <div class="card"><h3>شبکه — ورودی کل</h3><div class="big">↓ ${fmtB(s.net_rx)}</div><small>سرعت: ${fmtB(s.net_rx_rate)}/s</small></div>
 <div class="card"><h3>شبکه — خروجی کل</h3><div class="big">↑ ${fmtB(s.net_tx)}</div><small>سرعت: ${fmtB(s.net_tx_rate)}/s</small></div>
 <div class="card"><h3>جزئیات شبکه</h3><small>${perNet||'-'}</small></div>
 <div class="card"><h3>Xray</h3><div class="big">${d.xray_active?'✅ فعال':'❌ خاموش'}</div><small>Warp: ${s.warp_enabled?'✅ فعال':'❌ خاموش'}</small></div>
 <div class="card"><h3>Asterisk (SIP)</h3><div class="big">${s.svc_asterisk==='active'?'✅ فعال':'❌'}</div><small>فقط نمایش — دست نخورده</small></div>
 <div class="card"><h3>کاربران</h3><div class="big">${d.enabled_users} / ${d.total_users}</div><small>آنلاین: ${d.online_users||0}</small></div>
 <div class="card"><h3>ترافیک VPN</h3><div class="big">${fmtB(d.total_traffic)}</div><small>↑ ${fmtB(d.total_up)} ↓ ${fmtB(d.total_down)}</small></div>`;
 document.getElementById('inboundCards').innerHTML=Object.entries(d.by_inbound).map(([k,v])=>`
 <div class="card"><h3>${v.meta.fa} — پورت ${v.meta.port}</h3><div class="big">${v.count} کاربر</div>
 <small>${v.enabled} فعال • مصرف ${fmtB(v.traffic)}</small></div>`).join('');
}
async function loadClients(){
 const f=document.getElementById('fInbound').value;const q=(document.getElementById('fSearch').value||'').trim();
 const rows=await api('/api/clients'+(f?`?inbound=${f}`:''));
 const list=rows.filter(c=>!q||c.email.includes(q));
 document.getElementById('clientsBody').innerHTML=list.map(c=>{
  const pct=c.traffic_limit?Math.min(100,Math.round(c.total/c.traffic_limit*100)):0;
  const exp=c.expiry?fmtD(c.expiry):'نامحدود';
  const lim=c.traffic_limit?fmtB(c.traffic_limit):'نامحدود';
  const stMap={active:['فعال',''],disabled:['غیرفعال','off'],expired:['منقضی','off'],overlimit:['پر شده','off']};
  const st=stMap[c.status]||stMap.active;
  const protoMap={vless:'VLESS',trojan:'Trojan',ss:'SS',vmess:'VMess'};
  return `<tr><td><input type="checkbox" class="selRow" value="${c.id}" onchange="updateBulk()"></td><td><b>${c.email}</b><br><small style="color:#8ea0bd">${c.note||''}</small></td>
  <td>${protoMap[c.inbound]||c.inbound}</td>
  <td style="min-width:150px">${fmtB(c.total)} / ${lim}<div class="bar"><i style="width:${pct}%"></i></div><small>↑${fmtB(c.up)} ↓${fmtB(c.down)}</small></td>
  <td>${exp}<br><small style="color:#8ea0bd">IP: ${c.ip_limit||'∞'}</small></td>
  <td>${c.online?('🟢 '+c.online):'⚪ 0'}</td>
  <td><span class="pill ${st[1]}">${st[0]}</span></td>
  <td style="white-space:nowrap">
  <button class="btn sm" onclick="copyLink(${c.id})">لینک/QR</button>
  <button class="btn sm" onclick="openEdit(${c.id})">ویرایش</button>
  <button class="btn sm" onclick="toggleClient(${c.id},${c.enable?0:1})">${c.enable?'غیرفعال':'فعال'}</button>
  <button class="btn sm" onclick="resetClient(${c.id})">ریست</button>
  <button class="btn sm danger" onclick="delClient(${c.id})">حذف</button></td></tr>`;}).join('')||'<tr><td colspan="8">کاربری نیست</td></tr>';
 updateBulk();
 window._clients=rows;
}
function openModal(html){document.getElementById('modalBox').innerHTML=html;document.getElementById('modal').classList.add('open');}
function closeModal(){document.getElementById('modal').classList.remove('open');}
document.getElementById('modal').addEventListener('click',e=>{if(e.target.id==='modal')closeModal();});
function openAdd(){openModal(`<h2>کاربر جدید</h2>
<label>ایمیل (نام کاربر)</label><input id="mEmail" placeholder="مثلاً: ali">
<label>پروتکل</label><select id="mInbound"><option value="vless">VLESS Reality (443)</option><option value="trojan">Trojan Reality (8443)</option><option value="ss">Shadowsocks 2022 (8388)</option><option value="vmess">VMess Reality (2096)</option></select>
<label>سقف حجم (گیگابایت) — ۰ نامحدود</label><input id="mTraffic" type="number" min="0" step="0.5" value="0">
<label>مدت (روز) — ۰ بدون انقضا</label><input id="mExpiry" type="number" min="0" value="0">
<label>سقف IP همزمان — ۰ نامحدود</label><input id="mIp" type="number" min="0" value="0">
<label>یادداشت</label><input id="mNote">
<div class="row"><button class="btn primary" onclick="saveAdd()">ساخت</button><button class="btn" onclick="closeModal()">انصراف</button></div>`);}
async function saveAdd(){const b={email:document.getElementById('mEmail').value.trim(),inbound:document.getElementById('mInbound').value,
traffic_gb:+document.getElementById('mTraffic').value||0,expiry_days:+document.getElementById('mExpiry').value||0,ip_limit:+document.getElementById('mIp').value||0,note:document.getElementById('mNote').value.trim()};
try{const c=await api('/api/clients',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
closeModal();toast('کاربر ساخته شد');loadClients();showLinks(c);}catch(e){toast(e.message);}}
function openEdit(id){const c=(window._clients||[]).find(x=>x.id===id);if(!c)return;
openModal(`<h2>ویرایش ${c.email}</h2>
<label>ایمیل</label><input id="eEmail" value="${c.email}">
<label>سقف حجم (گیگابایت) — ۰ نامحدود</label><input id="eTraffic" type="number" min="0" step="0.5" value="${c.traffic_limit?+(c.traffic_limit/1073741824).toFixed(2):0}">
<label>مدت از الان (روز) — ۰ بدون انقضا</label><input id="eExpiry" type="number" min="0" value="0">
<label>سقف IP همزمان — ۰ نامحدود</label><input id="eIp" type="number" min="0" value="${c.ip_limit||0}">
<label>یادداشت</label><input id="eNote" value="${(c.note||'').replace(/"/g,'&quot;')}">
<div class="row"><button class="btn primary" onclick="saveEdit(${id})">ذخیره</button><button class="btn" onclick="closeModal()">انصراف</button></div>
<p class="hint">برای تمدید، مدت جدید از الان حساب می‌شه. برای بدون انقضا ۰ بذار.</p>`);}
async function saveEdit(id){const b={email:document.getElementById('eEmail').value.trim(),traffic_gb:+document.getElementById('eTraffic').value||0,
expiry_days:+document.getElementById('eExpiry').value||0,ip_limit:+document.getElementById('eIp').value||0,note:document.getElementById('eNote').value.trim()};
try{await api('/api/clients/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
closeModal();toast('ذخیره شد');loadClients();}catch(e){toast(e.message);}}
async function toggleClient(id,en){try{await api('/api/clients/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({enable:en})});toast('انجام شد');loadClients();}catch(e){toast(e.message);}}
async function resetClient(id){if(!confirm('مصرف این کاربر صفر بشه؟'))return;try{await api('/api/clients/'+id+'/reset',{method:'POST'});toast('ریست شد');loadClients();}catch(e){toast(e.message);}}
async function delClient(id){if(!confirm('حذف بشه؟'))return;try{await api('/api/clients/'+id,{method:'DELETE'});toast('حذف شد');loadClients();}catch(e){toast(e.message);}}
function showLinks(c){openModal(`<h2>لینک‌های ${c.email}</h2>
${(c.links||[]).map((l,i)=>`<label>لینک ${i+1}</label><textarea rows="3" readonly class="mono">${l}</textarea>`).join('')}
<label>لینک اشتراک (Sub)</label><textarea rows="2" readonly class="mono">${c.sub||''}</textarea>
<div class="row" style="align-items:flex-start">
<div style="text-align:center"><img src="${base}/qr/${c.id}" width="150" height="150" style="border-radius:12px;background:#fff;padding:6px"><br><small>QR لینک</small></div>
<div style="text-align:center"><img src="${base}/qr-sub/${c.id}" width="150" height="150" style="border-radius:12px;background:#fff;padding:6px"><br><small>QR اشتراک</small></div></div>
<div class="row"><button class="btn primary" onclick="navigator.clipboard.writeText('${(c.links||[])[0]||''}');toast('کپی شد')">کپی لینک اول</button>
<button class="btn" onclick="navigator.clipboard.writeText('${c.sub||''}');toast('ساب کپی شد')">کپی ساب</button><button class="btn" onclick="closeModal()">بستن</button></div>`);}
async function copyLink(id){const c=(window._clients||[]).find(x=>x.id===id);if(!c)return;showLinks(c);}
function toggleAll(on){document.querySelectorAll('.selRow').forEach(x=>x.checked=on);updateBulk();}
function updateBulk(){const n=document.querySelectorAll('.selRow:checked').length;const b=document.getElementById('bulkBar');
if(b){b.style.display=n?'flex':'none';document.getElementById('bulkCount').textContent=n+' انتخاب شده';}}
async function bulkAction(a){const ids=[...document.querySelectorAll('.selRow:checked')].map(x=>+x.value);
if(!ids.length)return;if(a==='delete'&&!confirm(ids.length+' کاربر حذف بشه؟'))return;
try{await api('/api/clients/bulk',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids,action:a})});toast('انجام شد');loadClients();}catch(e){toast(e.message);}}
async function loadRouting(){const rows=await api('/api/routing');
document.getElementById('routingBody').innerHTML=rows.map(r=>`<tr><td>${r.rtype}</td><td class="mono">${r.value}</td><td>${r.outbound}</td><td>${r.remark||''}</td>
<td><span class="pill ${r.enable?'':'off'}">${r.enable?'فعال':'خاموش'}</span></td>
<td style="white-space:nowrap"><button class="btn sm" onclick="toggleRouting(${r.id},${r.enable?0:1})">${r.enable?'خاموش':'روشن'}</button>
<button class="btn sm danger" onclick="delRouting(${r.id})">حذف</button></td></tr>`).join('')||'<tr><td colspan="6">قانونی نیست</td></tr>';}
async function addRouting(){const b={rtype:document.getElementById('rType').value,value:document.getElementById('rValue').value.trim(),
outbound:document.getElementById('rOut').value,remark:document.getElementById('rRemark').value.trim()};
try{await api('/api/routing',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});toast('اضافه شد');loadRouting();}catch(e){toast(e.message);}}
async function preset(t,v,o,rm){try{await api('/api/routing',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rtype:t,value:v,outbound:o,remark:rm})});toast('اضافه شد');loadRouting();}catch(e){toast(e.message);}}
async function toggleRouting(id,en){try{await api('/api/routing/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({enable:en})});loadRouting();}catch(e){toast(e.message);}}
async function delRouting(id){if(!confirm('حذف بشه؟'))return;try{await api('/api/routing/'+id,{method:'DELETE'});loadRouting();}catch(e){toast(e.message);}}
async function loadLogs(){const d=await api('/api/logs');document.getElementById('logsPre').textContent=d.logs||'(خالی)';}
let _settings=null,_updZip='';
async function loadSettings(){const d=await api('/api/dashboard');document.getElementById('xrayState').textContent=d.xray_active?'Xray فعاله':'Xray خاموشه';
document.getElementById('panelAddr').textContent=location.origin+'/'+S+'/';
const s=await api('/api/settings');_settings=s;
document.getElementById('sDomain').value=s.panel_domain||'';
document.getElementById('sPort').value=s.panel_port||2053;
document.getElementById('sBotToken').placeholder=s.bot_token||'توکن جدید...';
document.getElementById('sBotAdmin').value=s.bot_admin_id||'';
document.getElementById('sBotEnabled').checked=s.bot_enabled==='1';
document.getElementById('sSslEmail').value=s.ssl_email||'';
document.getElementById('sslState').textContent=s.ssl_available?'✅ گواهی SSL موجوده':'❌ گواهی SSL نیست';
document.getElementById('sLandTitle').value=s.landing_title||'';
document.getElementById('sLandSub').value=s.landing_subtitle||'';
document.getElementById('sLandFoot').value=s.landing_footer||'';
document.getElementById('sLandTpl').value=s.landing_template||'';
document.getElementById('sL2tpEnabled').checked=s.l2tp_enabled==='1';
document.getElementById('sL2tpSecret').value=s.l2tp_secret||'';
document.getElementById('sUpdRepo').value=s.update_repo||'';
document.getElementById('sBackupEnabled').checked=s.backup_enabled==='1';
document.getElementById('sBackupHours').value=s.backup_interval_hours||24;
document.getElementById('backupState').textContent=s.backup_last&&s.backup_last!=='0'?('آخرین بکاپ: '+new Date(+s.backup_last*1000).toLocaleString('fa-IR')):'هنوز بکاپی گرفته نشده';
document.getElementById('curVer').textContent=s.panel_version||'';
document.getElementById('aboutVer').textContent=s.panel_version||'';
document.getElementById('updRepo').textContent=s.update_repo||'';
const fill=(id,ib,cur)=>{const el=document.getElementById(id);const ch=(s.transports||{})[ib]||{};
el.innerHTML=Object.entries(ch).map(([k,v])=>`<option value="${k}" ${k===cur?'selected':''}>${v}</option>`).join('');};
fill('sTrVless','vless',s.transport_vless);fill('sTrTrojan','trojan',s.transport_trojan);
fill('sTrVmess','vmess',s.transport_vmess);fill('sTrSs','ss',s.transport_ss);
loadL2tp();}
async function saveSettingsPatch(b){return api('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});}
async function saveDomain(){try{await saveSettingsPatch({panel_domain:document.getElementById('sDomain').value.trim(),panel_port:document.getElementById('sPort').value});toast('ذخیره شد — لینک‌ها آپدیت شدن');}catch(e){toast(e.message);}}
async function saveBot(){try{const b={bot_admin_id:document.getElementById('sBotAdmin').value.trim(),bot_enabled:document.getElementById('sBotEnabled').checked?'1':'0'};
const tok=document.getElementById('sBotToken').value.trim();if(tok)b.bot_token=tok;
await saveSettingsPatch(b);toast('ذخیره و ربات ری‌استارت شد');}catch(e){toast(e.message);}}
async function issueSsl(){if(!confirm('گواهی SSL گرفته بشه؟ دامنه باید به سرور اشاره کنه.'))return;
try{toast('در حال دریافت SSL...');await api('/api/ssl/issue',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:document.getElementById('sSslEmail').value.trim()})});toast('SSL گرفته شد ✅');loadSettings();}catch(e){toast(e.message);}}
async function saveTransports(){try{await saveSettingsPatch({transport_vless:document.getElementById('sTrVless').value,transport_trojan:document.getElementById('sTrTrojan').value,transport_vmess:document.getElementById('sTrVmess').value,transport_ss:document.getElementById('sTrSs').value});toast('ترنسپورت ذخیره و Xray بازسازی شد');}catch(e){toast(e.message);}}
async function saveLanding(){try{await saveSettingsPatch({landing_title:document.getElementById('sLandTitle').value,landing_subtitle:document.getElementById('sLandSub').value,landing_footer:document.getElementById('sLandFoot').value,landing_template:document.getElementById('sLandTpl').value});toast('لندینگ ذخیره شد');}catch(e){toast(e.message);}}
async function saveL2tp(){try{await saveSettingsPatch({l2tp_enabled:document.getElementById('sL2tpEnabled').checked?'1':'0',l2tp_secret:document.getElementById('sL2tpSecret').value.trim()});toast('L2TP اعمال شد');loadL2tp();}catch(e){toast(e.message);}}
async function loadL2tp(){try{const d=await api('/api/l2tp');
document.getElementById('l2tpServer').textContent=d.server||'';
document.getElementById('l2tpState').textContent=`strongswan: ${d.status.strongswan||'?'} | xl2tpd: ${d.status.xl2tpd||'?'}`;
document.getElementById('l2tpList').innerHTML=(d.users||[]).map(u=>`<div class="row" style="justify-content:space-between;border:1px solid #22355c;border-radius:10px;padding:8px;margin:6px 0">
<span><b>${u.username}</b> — ${u.enable?'✅':'❌'}</span>
<span><button class="btn sm" onclick="toggleL2tp(${u.id},${u.enable?0:1})">${u.enable?'غیرفعال':'فعال'}</button>
<button class="btn sm danger" onclick="delL2tp(${u.id})">حذف</button></span></div>`).join('')||'<p class="hint">کاربر L2TP نیست</p>';}catch(e){}}
async function addL2tp(){const u=document.getElementById('l2tpUser').value.trim(),p=document.getElementById('l2tpPass').value.trim();
if(!u||!p)return toast('نام و رمز رو وارد کن');
try{await api('/api/l2tp',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})});toast('اضافه شد');loadL2tp();}catch(e){toast(e.message);}}
async function toggleL2tp(id,en){try{await api('/api/l2tp/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({enable:en})});loadL2tp();}catch(e){toast(e.message);}}
async function delL2tp(id){if(!confirm('حذف بشه؟'))return;try{await api('/api/l2tp/'+id,{method:'DELETE'});loadL2tp();}catch(e){toast(e.message);}}
async function saveUpdRepo(){try{await saveSettingsPatch({update_repo:document.getElementById('sUpdRepo').value.trim()});toast('ریپو ذخیره شد');loadSettings();}catch(e){toast(e.message);}}
async function saveBackupSettings(){try{await saveSettingsPatch({backup_enabled:document.getElementById('sBackupEnabled').checked?'1':'0',backup_interval_hours:document.getElementById('sBackupHours').value});toast('تنظیمات بکاپ ذخیره شد');}catch(e){toast(e.message);}}
function downloadBackup(){window.open(base+'/api/backup','_blank');}
async function sendBackup(){try{toast('در حال ارسال بکاپ به ربات...');await api('/api/backup',{method:'POST'});toast('بکاپ به ربات ارسال شد ✅');loadSettings();}catch(e){toast(e.message);}}
async function restoreBackup(){const f=document.getElementById('restoreFile').files[0];if(!f)return;
if(!confirm('دیتابیس فعلی با این فایل جایگزین بشه؟ (قبلش بکاپ گرفته می‌شه)'))return;
const fd=new FormData();fd.append('file',f);
try{const r=await fetch(base+'/api/backup/restore',{method:'POST',body:fd,credentials:'same-origin'});
const d=await r.json();if(!r.ok)throw new Error(d.error||'خطا');toast('ریستور انجام شد ✅');setTimeout(()=>location.reload(),1500);}catch(e){toast(e.message);}}
function exportUsers(fmt){window.open(base+'/api/users/export?format='+fmt,'_blank');}
async function importUsers(){const f=document.getElementById('importFile').files[0];if(!f)return;
try{const txt=await f.text();const data=JSON.parse(txt);
const d=await api('/api/users/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
toast(`ایمپورت شد: ${d.created} ساخته، ${d.skipped} رد شد`);loadClients();}catch(e){toast(e.message);}}
async function checkUpdate(){document.getElementById('updState').textContent='در حال بررسی...';
try{const d=await api('/api/update/check');
if(d.error){document.getElementById('updState').textContent='❌ '+d.error;return;}
document.getElementById('updState').textContent=d.update_available?`✅ نسخه جدید: ${d.latest} (فعلی: ${d.current})`:`✅ به‌روز هستی (${d.current})`;
if(d.update_available){_updZip=d.zip_url;document.getElementById('updBtn').style.display='';}}catch(e){document.getElementById('updState').textContent='❌ '+e.message;}}
async function applyUpdate(){if(!_updZip||!confirm('آپدیت اعمال بشه؟ پنل و ربات ری‌استارت می‌شن.'))return;
try{toast('در حال آپدیت...');await api('/api/update/apply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({zip_url:_updZip})});toast('آپدیت انجام شد ✅');}catch(e){toast(e.message);}}
async function restartPanel(){if(!confirm('پنل restart بشه؟'))return;try{await api('/api/restart-panel',{method:'POST'});toast('پنل restart شد');}catch(e){toast(e.message);}}
async function restartBot(){try{await api('/api/restart-bot',{method:'POST'});toast('ربات restart شد');}catch(e){toast(e.message);}}
async function changePass(){const p=document.getElementById('newPass').value.trim();
try{await api('/api/change-pass',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:p})});toast('رمز عوض شد');document.getElementById('newPass').value='';}catch(e){toast(e.message);}}
async function restartXray(){if(!confirm('Xray restart بشه؟ چند ثانیه قطع می‌شه.'))return;
try{await api('/api/restart-xray',{method:'POST'});toast('Xray restart شد');}catch(e){toast(e.message);}}
loadDash();
</script></body></html>"""

if __name__ == '__main__':
    init_db()
    # Build initial config (with API/stats + 3 inbounds) and restart Xray once
    try:
        build_xray_config()
        print('Initial Xray config built', flush=True)
    except Exception as e:
        print(f'Initial config failed: {e}', flush=True)
    t = threading.Thread(target=stats_loop, daemon=True)
    t.start()
    bt = threading.Thread(target=backup_loop, daemon=True)
    bt.start()
    print(f'Sirgsm VPN Panel starting on port {PANEL_PORT}, secret path /{SECRET_PATH}/', flush=True)
    app.run(host='0.0.0.0', port=PANEL_PORT, threaded=True)
