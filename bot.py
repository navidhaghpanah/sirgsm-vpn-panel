#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sirgsm VPN Panel — Telegram Bot
Sirgsm.ir

Bot for managing VPN users via the Sirgsm panel HTTP API.
Uses raw Telegram Bot API (stdlib only, no extra deps).

Env:
  BOT_TOKEN     Telegram bot token from @BotFather (required)
  BOT_ADMIN_ID  Your Telegram numeric ID (from @userinfobot) — only this user can use the bot.
                If empty, bot allows everyone (NOT recommended).
  PANEL_URL     Panel base URL, e.g. http://127.0.0.1:2053/nhv-xxxx (default http://127.0.0.1:2053)
  PANEL_PATH    Secret path (default from env or nhv-a9639a605ed1)
  PANEL_USER    Panel username (default admin)
  PANEL_PASS    Panel password (required)

Commands (admin only):
  /start            منوی اصلی
  /add <email> <protocol> <days> <gb> [ip_limit]
                    ساخت کاربر — protocol: vless|trojan|ss|vmess
                    مثال: /add ali vless 30 50
  /list             لیست کاربران
  /links <email>    لینک + QR + ساب کاربر
  /status           وضعیت سرور
  /del <email>      حذف کاربر
  /reset <email>    ریست مصرف
  /enable <email>   فعال
  /disable <email>  غیرفعال
  /l2tp             لیست کاربران L2TP
  /version          نسخه پنل
  /help             راهنما
"""

import os
import sys
import time
import json
import urllib.request
import urllib.parse
import http.cookiejar
import io

def _db_setting(key, default=''):
    try:
        import sqlite3
        con = sqlite3.connect('/opt/sirgsm-panel/panel.db')
        row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        con.close()
        return row[0] if row and row[0] else default
    except Exception:
        return default

BOT_TOKEN = (os.environ.get('BOT_TOKEN', '').strip()
             or _db_setting('bot_token', '')
             or os.environ.get('SIRGSM_BOT_TOKEN', '').strip())
BOT_ADMIN_ID = (os.environ.get('BOT_ADMIN_ID', '').strip()
                or _db_setting('bot_admin_id', '')
                or os.environ.get('SIRGSM_BOT_ADMIN_ID', '').strip())
# Re-read token periodically (panel settings may change it)
def refresh_creds():
    global BOT_TOKEN, BOT_ADMIN_ID, TG
    nt = _db_setting('bot_token', '') or BOT_TOKEN
    na = _db_setting('bot_admin_id', '') or BOT_ADMIN_ID
    if nt != BOT_TOKEN:
        BOT_TOKEN = nt
        TG = f"https://api.telegram.org/bot{BOT_TOKEN}"
    if na:
        BOT_ADMIN_ID = na
PANEL_URL = os.environ.get('PANEL_URL', 'http://127.0.0.1:2053').rstrip('/')
PANEL_PATH = os.environ.get('PANEL_PATH', os.environ.get('SIRGSM_SECRET_PATH', 'nhv-a9639a605ed1')).strip('/')
PANEL_USER = os.environ.get('PANEL_USER', 'admin')
PANEL_PASS = os.environ.get('PANEL_PASS', os.environ.get('SIRGSM_ADMIN_PASS', ''))

BASE = f"{PANEL_URL}/{PANEL_PATH}"

# ---------- Panel HTTP client (with cookie session) ----------
_cj = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cj))
_logged_in = False

def panel_login():
    global _logged_in
    if _logged_in:
        return True
    if not PANEL_PASS:
        print("PANEL_PASS not set", flush=True)
        return False
    data = urllib.parse.urlencode({'username': PANEL_USER, 'password': PANEL_PASS}).encode()
    try:
        r = _opener.open(f"{BASE}/login", data=data, timeout=15)
        _logged_in = (r.status == 200)
        return _logged_in
    except Exception as e:
        print(f"panel login failed: {e}", flush=True)
        return False

def panel_api(path, method='GET', body=None):
    global _logged_in
    if not panel_login():
        return None, "ورود به پنل ناموفق بود"
    url = BASE + path
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        r = _opener.open(req, timeout=20)
        txt = r.read().decode(errors='ignore')
        try:
            return json.loads(txt), None
        except Exception:
            return txt, None
    except urllib.error.HTTPError as e:
        txt = e.read().decode(errors='ignore')
        try:
            j = json.loads(txt)
            return None, j.get('error', txt[:200])
        except Exception:
            return None, txt[:200]
    except Exception as e:
        _logged_in = False
        return None, str(e)

def panel_get_bytes(path):
    """Download binary (e.g. QR PNG) from panel."""
    if not panel_login():
        return None
    try:
        r = _opener.open(BASE + path, timeout=20)
        return r.read()
    except Exception as e:
        print(f"panel get bytes failed: {e}", flush=True)
        return None

# ---------- Telegram API ----------
TG = f"https://api.telegram.org/bot{BOT_TOKEN}"

def tg(method, **kwargs):
    url = TG + "/" + method
    data = urllib.parse.urlencode(kwargs).encode()
    # Long polling (getUpdates timeout=50) needs urlopen timeout > 50
    to = 65 if method == 'getUpdates' else 30
    try:
        r = urllib.request.urlopen(url, data=data, timeout=to)
        return json.loads(r.read().decode(errors='ignore'))
    except Exception as e:
        print(f"tg {method} failed: {e}", flush=True)
        return None

def tg_send_photo(chat_id, photo_bytes, caption=''):
    url = TG + "/sendPhoto"
    boundary = "----SirgsmBoundary"
    body = io.BytesIO()
    body.write(f"--{boundary}\r\n".encode())
    body.write(b'Content-Disposition: form-data; name="chat_id"\r\n\r\n')
    body.write(str(chat_id).encode() + b"\r\n")
    if caption:
        body.write(f"--{boundary}\r\n".encode())
        body.write(b'Content-Disposition: form-data; name="caption"\r\n\r\n')
        body.write(caption.encode('utf-8') + b"\r\n")
    body.write(f"--{boundary}\r\n".encode())
    body.write(b'Content-Disposition: form-data; name="photo"; filename="qr.png"\r\n')
    body.write(b"Content-Type: image/png\r\n\r\n")
    body.write(photo_bytes + b"\r\n")
    body.write(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(url, data=body.getvalue(),
                                 headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return json.loads(r.read().decode(errors='ignore'))
    except Exception as e:
        print(f"sendPhoto failed: {e}", flush=True)
        return None

def send(chat_id, text, keyboard=None):
    kw = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML', 'disable_web_page_preview': 'true'}
    if keyboard:
        kw['reply_markup'] = json.dumps(keyboard)
    return tg('sendMessage', **kw)

def fmt_bytes(n):
    n = float(n or 0)
    for u in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"

def fmt_date(ts):
    if not ts:
        return 'نامحدود'
    return time.strftime('%Y-%m-%d', time.localtime(ts))

MENU = {
    'inline_keyboard': [
        [{'text': '➕ افزودن کاربر', 'callback_data': 'menu_add'},
         {'text': '📋 لیست کاربران', 'callback_data': 'menu_list'}],
        [{'text': '📊 وضعیت سرور', 'callback_data': 'menu_status'},
         {'text': '❓ راهنما', 'callback_data': 'menu_help'}],
    ]
}

HELP = """<b>راهنمای ربات Sirgsm VPN</b>

➕ <code>/add &lt;email&gt; &lt;protocol&gt; &lt;days&gt; &lt;gb&gt; [ip]</code>
ساخت کاربر — protocol: <code>vless</code> | <code>trojan</code> | <code>ss</code> | <code>vmess</code> | <code>http</code> (چندتایی: <code>vless,trojan</code>)
مثال: <code>/add ali vless,trojan 30 50</code>

📋 <code>/list</code> — لیست کاربران
🔗 <code>/links &lt;email&gt;</code> — لینک + QR + ساب
📊 <code>/status</code> — وضعیت سرور
🗑 <code>/del &lt;email&gt;</code> — حذف
🔄 <code>/reset &lt;email&gt;</code> — ریست مصرف
✅ <code>/enable &lt;email&gt;</code> / ❌ <code>/disable &lt;email&gt;</code>

Sirgsm.ir"""

def is_admin(user_id):
    if not BOT_ADMIN_ID:
        return True  # open mode (not recommended)
    return str(user_id) == str(BOT_ADMIN_ID)

def handle_add(chat_id, args):
    if len(args) < 4:
        send(chat_id, "❌ فرمت اشتباه.\nمثال: <code>/add ali vless 30 50</code>\nپروتکل: vless | trojan | ss | vmess")
        return
    email = args[0]
    protos = [x.strip() for x in args[1].split(',') if x.strip()]
    try:
        days = int(args[2]); gb = float(args[3])
        ip = int(args[4]) if len(args) > 4 else 0
    except Exception:
        send(chat_id, "❌ days و gb باید عدد باشن.")
        return
    valid = ('vless', 'trojan', 'ss', 'vmess', 'http')
    if not protos or any(x not in valid for x in protos):
        send(chat_id, "❌ پروتکل نامعتبر. vless | trojan | ss | vmess | http (چندتایی با کاما: vless,trojan)")
        return
    send(chat_id, "⏳ در حال ساخت...")
    data, err = panel_api('/api/clients', method='POST', body={
        'email': email, 'inbounds': protos, 'traffic_gb': gb,
        'expiry_days': days, 'ip_limit': ip, 'note': 'via bot'})
    if err or not data:
        send(chat_id, f"❌ خطا: {err or 'نامشخص'}")
        return
    links = data.get('links', [])
    txt = f"✅ کاربر <b>{email}</b> ({','.join(protos)}) ساخته شد.\n"
    txt += f"⏳ {days} روز | 📦 {gb} گیگ | 🌐 IP: {ip or 'نامحدود'}\n\n"
    for i, l in enumerate(links):
        txt += f"<code>{l}</code>\n\n"
    txt += f"🔗 ساب: <code>{data.get('sub','')}</code>"
    send(chat_id, txt)
    # QR
    png = panel_get_bytes(f"/qr/{data['id']}")
    if png:
        tg_send_photo(chat_id, png, caption=f"QR {email}")

def handle_list(chat_id):
    data, err = panel_api('/api/clients')
    if err or data is None:
        send(chat_id, f"❌ خطا: {err}")
        return
    if not data:
        send(chat_id, "کاربری نیست.")
        return
    lines = ["📋 <b>کاربران</b>\n"]
    for c in data:
        total = c.get('total', 0)
        lim = c.get('traffic_limit', 0)
        st = {'active': '✅', 'disabled': '❌', 'expired': '⏳', 'overlimit': '📦'}.get(c.get('status'), '')
        lines.append(f"{st} <b>{c['email']}</b> ({c['inbound']}) — {fmt_bytes(total)}/{fmt_bytes(lim) if lim else '∞'} — تا {fmt_date(c.get('expiry'))} — 🟢{c.get('online',0)}")
    send(chat_id, "\n".join(lines))

def handle_links(chat_id, args):
    if not args:
        send(chat_id, "❌ ایمیل رو بفرست: <code>/links ali</code>")
        return
    email = args[0]
    data, err = panel_api('/api/clients')
    if err or data is None:
        send(chat_id, f"❌ خطا: {err}")
        return
    c = next((x for x in data if x['email'] == email), None)
    if not c:
        send(chat_id, "❌ کاربر یافت نشد.")
        return
    txt = f"🔗 <b>{email}</b>\n\n"
    for l in c.get('links', []):
        txt += f"<code>{l}</code>\n\n"
    txt += f"🔗 ساب: <code>{c.get('sub','')}</code>"
    send(chat_id, txt)
    png = panel_get_bytes(f"/qr/{c['id']}")
    if png:
        tg_send_photo(chat_id, png, caption=f"QR {email}")
    png2 = panel_get_bytes(f"/qr-sub/{c['id']}")
    if png2:
        tg_send_photo(chat_id, png2, caption=f"QR Sub {email}")

def handle_status(chat_id):
    data, err = panel_api('/api/dashboard')
    if err or data is None:
        send(chat_id, f"❌ خطا: {err}")
        return
    s = data.get('server', {})
    txt = f"""📊 <b>وضعیت سرور</b>

🖥 CPU Load: <code>{s.get('load','-')}</code>
💾 RAM: {fmt_bytes(s.get('mem_used'))} / {fmt_bytes(s.get('mem_total'))} ({s.get('mem_pct')}%)
💿 Disk: {fmt_bytes(s.get('disk_used'))} / {fmt_bytes(s.get('disk_total'))} ({s.get('disk_pct')}%)
⏱ آپ‌تایم: {s.get('uptime',0)//86400} روز
🌐 شبکه ↓ {fmt_bytes(s.get('net_rx'))} ({fmt_bytes(s.get('net_rx_rate'))}/s) | ↑ {fmt_bytes(s.get('net_tx'))} ({fmt_bytes(s.get('net_tx_rate'))}/s)
🔌 Xray: {'✅' if data.get('xray_active') else '❌'} | Warp: {'✅' if s.get('warp_enabled') else '❌'}
👥 کاربران: {data.get('enabled_users')}/{data.get('total_users')} (آنلاین: {data.get('online_users',0)})
📦 ترافیک VPN: {fmt_bytes(data.get('total_traffic'))}
☎ Asterisk: {s.get('svc_asterisk','?')}"""
    send(chat_id, txt)

def find_by_email(email):
    data, err = panel_api('/api/clients')
    if err or data is None:
        return None, err
    return next((x for x in data if x['email'] == email), None), None

def handle_l2tp(chat_id):
    data, err = panel_api('/api/l2tp')
    if err or data is None:
        send(chat_id, f"❌ خطا: {err}")
        return
    users = data.get('users', [])
    txt = f"📡 <b>L2TP</b> — سرور: <code>{data.get('server','')}</code> — فعال: {'✅' if data.get('enabled') else '❌'}\n"
    txt += f"strongswan: {data.get('status',{}).get('strongswan','?')} | xl2tpd: {data.get('status',{}).get('xl2tpd','?')}\n\n"
    if not users:
        txt += "کاربر L2TP نیست (از پنل اضافه کن)."
    else:
        for u in users:
            txt += f"{'✅' if u['enable'] else '❌'} <b>{u['username']}</b>\n"
    send(chat_id, txt)

def handle_version(chat_id):
    data, err = panel_api('/api/settings')
    if err or data is None:
        send(chat_id, f"❌ خطا: {err}")
        return
    send(chat_id, f"🔖 نسخه پنل: <b>{data.get('panel_version','?')}</b>\n🌐 دامنه: <code>{data.get('domain','')}</code>\n🔒 SSL: {'✅' if data.get('ssl_available') else '❌'}")

def handle_simple(chat_id, args, action):
    if not args:
        send(chat_id, f"❌ ایمیل رو بفرست.")
        return
    email = args[0]
    c, err = find_by_email(email)
    if err:
        send(chat_id, f"❌ خطا: {err}")
        return
    if not c:
        send(chat_id, "❌ کاربر یافت نشد.")
        return
    cid = c['id']
    if action == 'del':
        _, err = panel_api(f'/api/clients/{cid}', method='DELETE')
        send(chat_id, "🗑 حذف شد." if not err else f"❌ {err}")
    elif action == 'reset':
        _, err = panel_api(f'/api/clients/{cid}/reset', method='POST')
        send(chat_id, "🔄 ریست شد." if not err else f"❌ {err}")
    elif action == 'enable':
        _, err = panel_api(f'/api/clients/{cid}', method='PUT', body={'enable': True})
        send(chat_id, "✅ فعال شد." if not err else f"❌ {err}")
    elif action == 'disable':
        _, err = panel_api(f'/api/clients/{cid}', method='PUT', body={'enable': False})
        send(chat_id, "❌ غیرفعال شد." if not err else f"❌ {err}")

def handle_message(msg):
    chat = msg.get('chat', {})
    chat_id = chat.get('id')
    user = msg.get('from', {})
    user_id = user.get('id')
    text = (msg.get('text') or '').strip()
    if not text:
        return
    if not is_admin(user_id):
        send(chat_id, "⛔ دسترسی ندارید.")
        return
    parts = text.split()
    cmd = parts[0].split('@')[0].lower()
    args = parts[1:]
    if cmd in ('/start', '/menu'):
        send(chat_id, "👋 سلام! ربات مدیریت <b>Sirgsm VPN</b>\nاز منو استفاده کن یا دستور بفرست.", MENU)
    elif cmd == '/add':
        handle_add(chat_id, args)
    elif cmd == '/list':
        handle_list(chat_id)
    elif cmd == '/links':
        handle_links(chat_id, args)
    elif cmd == '/status':
        handle_status(chat_id)
    elif cmd == '/del':
        handle_simple(chat_id, args, 'del')
    elif cmd == '/reset':
        handle_simple(chat_id, args, 'reset')
    elif cmd == '/enable':
        handle_simple(chat_id, args, 'enable')
    elif cmd == '/disable':
        handle_simple(chat_id, args, 'disable')
    elif cmd == '/l2tp':
        handle_l2tp(chat_id)
    elif cmd == '/version':
        handle_version(chat_id)
    elif cmd == '/help':
        send(chat_id, HELP)
    else:
        send(chat_id, "❓ دستور نامعتبر. /help")

def handle_callback(cb):
    data = cb.get('data', '')
    msg = cb.get('message', {})
    chat_id = msg.get('chat', {}).get('id')
    user_id = cb.get('from', {}).get('id')
    tg('answerCallbackQuery', callback_query_id=cb.get('id'))
    if not is_admin(user_id):
        return
    if data == 'menu_add':
        send(chat_id, "➕ <code>/add &lt;email&gt; &lt;protocol&gt; &lt;days&gt; &lt;gb&gt;</code>\nمثال: <code>/add ali vless 30 50</code>")
    elif data == 'menu_list':
        handle_list(chat_id)
    elif data == 'menu_status':
        handle_status(chat_id)
    elif data == 'menu_help':
        send(chat_id, HELP)

def main():
    if not BOT_TOKEN:
        print("BOT_TOKEN not set. Get one from @BotFather.", flush=True)
        sys.exit(1)
    print("Sirgsm VPN Bot starting...", flush=True)
    tg('setMyCommands', commands=json.dumps([
        {'command': 'start', 'description': 'منوی اصلی'},
        {'command': 'add', 'description': 'افزودن کاربر'},
        {'command': 'list', 'description': 'لیست کاربران'},
        {'command': 'links', 'description': 'لینک کاربر'},
        {'command': 'status', 'description': 'وضعیت سرور'},
        {'command': 'help', 'description': 'راهنما'},
    ]))
    offset = 0
    _last_refresh = 0
    while True:
        try:
            if time.time() - _last_refresh > 60:
                refresh_creds()
                _last_refresh = time.time()
            r = tg('getUpdates', offset=offset, timeout=50, allowed_updates=json.dumps(['message', 'callback_query']))
            if not r or not r.get('ok'):
                time.sleep(3)
                continue
            for upd in r.get('result', []):
                offset = upd['update_id'] + 1
                if 'message' in upd:
                    handle_message(upd['message'])
                elif 'callback_query' in upd:
                    handle_callback(upd['callback_query'])
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"loop error: {e}", flush=True)
            time.sleep(3)

if __name__ == '__main__':
    main()
