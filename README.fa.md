# Sirgsm VPN Panel

پنل مدیریت VPN اختصاصی، ساخته‌شده از صفر (Flask + SQLite + Xray-core).

**اسپانسر: [Sirgsm.ir](https://sirgsm.ir) — Navid Haghbayan**

[English](README.md) | **فارسی**

## قابلیت‌ها

- **۴ پروتکل**: VLESS، Trojan، Shadowsocks 2022، VMess
- **ترنسپورت برای هر اینباند** (قابل تغییر در تنظیمات):
  - VLESS: Reality+TCP، Reality+gRPC، TLS+WebSocket، TLS+gRPC، TLS+TCP، TCP، WebSocket
  - Trojan: Reality+TCP، TLS+WebSocket، TLS+gRPC، TLS+TCP، TCP
  - VMess: Reality+TCP، TLS+WebSocket، TLS+gRPC، TCP، WebSocket
  - Shadowsocks: TCP/UDP (2022-blake3-aes-128-gcm)
- **مدیریت کاربر**: انقضا (روز) + سقف حجم (گیگ) + سقف IP همزمان، کاربران آنلاین، عملیات گروهی
- **QR کد** برای لینک و اشتراک
- **لندینگ‌پیج اشتراک**: باز کردن لینک ساب در مرورگر → جزئیات اکانت (مصرف/انقضا/لینک/QR)؛ کلاینت‌های VPN خودکار متن خام می‌گیرن (`/sub/<token>/raw` برای خام)
- **وضعیت سرور**: CPU، RAM، دیسک، آپ‌تایم، ورودی/خروجی شبکه + سرعت، ترافیک VPN
- **Warp** (Cloudflare WARP) برای یوتیوب/گوگل/اوپن‌ای‌آی/تلگرام + قوانین routing
- **L2TP / IKEv2 (IPsec)**: PSK + کاربرهای PPP، از تنظیمات
- **SSL**: دریافت یک‌کلیکی Let's Encrypt برای دامنه پنل
- **ربات تلگرام** (`bot.py`): `/add /list /links /status /l2tp /version /del /reset /enable /disable` — توکن و آیدی در تنظیمات پنل
- **بکاپ/ریستور**: دانلود دیتابیس، ریستور، بکاپ خودکار هر ۲۴ ساعت به ربات تلگرام
- **مهاجرت کاربر**: خروجی/ورودی JSON (فرمت Sirgsm + سازگار با Marzban) با حفظ مدت و حجم
- **تنظیمات در پنل**: دامنه، پورت، رمز، ربات، SSL، ترنسپورت‌ها، لندینگ، L2TP، ریپوی آپدیت
- **آپدیت**: بررسی ریلیزهای گیت‌هاب و آپدیت یک‌کلیکی
- **رابط فارسی RTL**، مسیر مخفی، مانیتورینگ SIP (Asterisk) فقط نمایشی

## نصب (تک‌خطی)

```bash
curl -fsSL https://raw.githubusercontent.com/navidhaghpanah/sirgsm-vpn-panel/main/install.sh | bash
```

یا از روی کلون محلی:

```bash
git clone https://github.com/navidhaghpanah/sirgsm-vpn-panel.git && cd sirgsm-vpn-panel
sudo bash install.sh
```

نصب‌کننده همه نیازمندی‌ها (Python، Flask، qrcode، nginx، certbot، strongswan، xl2tpd، wireguard-tools) را خودکار نصب می‌کند، فایل‌ها را کپی می‌کند، سرویس‌ها را می‌سازد، فایروال را باز می‌کند و SSL می‌گیرد (متغیرهای `SSL_EMAIL` و `DOMAIN` را ست کن، یا بعداً از پنل بگیر).

پنل: `http://YOUR_DOMAIN:2053/YOUR_SECRET_PATH/` — ورود `admin` / رمز ساخته‌شده (در `/root/sirgsm-panel.txt`).

## Warp

یک اکانت رایگان Cloudflare WARP بساز (مثلاً با `wgcf`) و این فایل‌ها را بگذار:

- `/opt/sirgsm-panel/warp/account.toml`
- `/opt/sirgsm-panel/warp/profile.conf`
- `/opt/sirgsm-panel/warp/warp.json` — `{"reserved": [..]}` از `client_id` در API

پنل خروجی Warp را خودکار لود می‌کند و قوانین یوتیوب/گوگل/اوپن‌ای‌آی/تلگرام را می‌سازد.

## ربات تلگرام

توکن را در **پنل > تنظیمات > ربات تلگرام** (از [@BotFather](https://t.me/BotFather)) و آیدی عددی خودت را (از [@userinfobot](https://t.me/userinfobot)) وارد کن، بعد `systemctl restart sirgsm-bot`. فقط آیدی ادمین می‌تواند از ربات استفاده کند.

## لندینگ‌پیج (قالب)

لندینگ اشتراک یک قالب قابل شخصی‌سازی است. در **پنل > تنظیمات > لندینگ‌پیج** عنوان، زیرعنوان، فوتر یا یک قالب HTML کامل سفارشی می‌توانی بگذاری. متغیرها: `{title} {subtitle} {footer} {email} {protocol} {used} {limit} {pct} {expiry} {ip_limit} {online} {status_fa} {status_cls} {links_html} {sub} {qr_link} {qr_sub}`.

## L2TP / IKEv2

در **پنل > تنظیمات > L2TP**: فعال کن، PSK (secret) بگذار، کاربر اضافه کن. کلاینت‌ها با L2TP/IPsec (PSK) وصل می‌شوند، سرور = دامنه پنل، پورت‌های UDP 500/4500/1701.

## بکاپ و مهاجرت

- **بکاپ**: دانلود دیتابیس، ریستور (قبلش خودکار بکاپ گرفته می‌شود)، بکاپ خودکار هر ۲۴ ساعت به ربات.
- **مهاجرت**: خروجی JSON در دو فرمت Sirgsm و Marzban (با مدت و حجم)، ورودی JSON برای ساخت کاربرها.

## آپدیت

در **پنل > تنظیمات > آپدیت**: ریپو (`owner/repo`) را ست کن، نسخه جدید را بررسی کن، یک‌کلیک آپدیت کن. آپدیتر فایل zip ریلیز را دانلود و پنل + ربات را ری‌استارت می‌کند.

## نکات امنیتی

- قبل از انتشار، `SIRGSM_SECRET_PATH` و `SIRGSM_ADMIN_PASS` را عوض کن.
- هیچ secret واقعی را کامیت نکن (`.env`، `*.db`، `warp/`، `vpn-secrets*`) — به `.gitignore` نگاه کن.
- پنل Asterisk/SIP را مدیریت نمی‌کند — فقط وضعیتش را نمایش می‌دهد.

## لایسنس

MIT — فایل `LICENSE` را ببین.

---
اسپانسر: **Sirgsm.ir — Navid Haghbayan**
