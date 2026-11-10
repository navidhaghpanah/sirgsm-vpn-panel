# نصب

## نصب تک‌خطی

```bash
curl -fsSL https://raw.githubusercontent.com/navidhaghpanah/sirgsm-vpn-panel/main/install.sh | bash
```

یا از روی کلون محلی:

```bash
git clone https://github.com/navidhaghpanah/sirgsm-vpn-panel.git && cd sirgsm-vpn-panel
sudo bash install.sh
```

## نصب‌کننده چه کار می‌کند؟

1. **همه نیازمندی‌ها** را خودکار نصب می‌کند: Python 3، Flask، qrcode/Pillow، nginx، certbot، strongswan (+starter)، xl2tpd، wireguard-tools، ufw.
2. `app.py` و `bot.py` را به `/opt/sirgsm-panel/` کپی می‌کند.
3. `/root/sirgsm-panel.env` (مسیر مخفی + رمز ادمین + پورت) و `/root/sirgsm-panel.txt` (مشخصات) را می‌سازد.
4. سرویس‌های systemd می‌سازد: `sirgsm-panel` و `sirgsm-bot`.
5. فایروال را باز می‌کند: پورت پنل، L2TP/IPsec (UDP 500/4500/1701)، پورت 80 (برای SSL).
6. اگر `SSL_EMAIL` و `DOMAIN` ست باشند، **SSL Let's Encrypt** برای دامنه پنل می‌گیرد (یا بعداً از پنل > تنظیمات > SSL).
7. پنل را استارت می‌کند.

## متغیرهای محیطی

```bash
DOMAIN=example.com PANEL_PORT=2053 SSL_EMAIL=you@example.com bash install.sh
```

## بعد از نصب

- پنل: `http://YOUR_DOMAIN:2053/YOUR_SECRET_PATH/` — ورود `admin` / رمز از `/root/sirgsm-panel.txt`.
- ربات: توکن را در **پنل > تنظیمات > ربات تلگرام** (از [@BotFather](https://t.me/BotFather)) و آیدی را از [@userinfobot](https://t.me/userinfobot) بگذار، بعد `systemctl restart sirgsm-bot`.
- Warp: فایل‌های `account.toml` + `profile.conf` + `warp.json` را در `/opt/sirgsm-panel/warp/` بگذار (README را ببین).
- Xray: Xray-core را جدا نصب کن (مستندات [XTLS/Xray-core](https://github.com/XTLS/Xray-core))، بعد پنل را ری‌استارت کن (کانفیگ را خودش می‌سازد).

## آپدیت

پنل > تنظیمات > آپدیت: ریپو (`navidhaghpanah/sirgsm-vpn-panel`) را ست کن، بررسی کن، یک‌کلیک آپدیت کن.
