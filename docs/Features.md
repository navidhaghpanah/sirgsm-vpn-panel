# Features

## Protocols & transports

| Inbound | Port | Transports |
|---|---|---|
| VLESS | 443 | Reality+TCP, Reality+gRPC, TLS+WS, TLS+gRPC, TLS+TCP, TCP, WS |
| Trojan | 8443 | Reality+TCP, TLS+WS, TLS+gRPC, TLS+TCP, TCP |
| Shadowsocks 2022 | 8388 | TCP/UDP |
| VMess | 2096 | Reality+TCP, TLS+WS, TLS+gRPC, TCP, WS |

Switch transports in **Panel > Settings > Transports** (TLS needs the Let's Encrypt cert first).

## Users

- Expiry (days), traffic limit (GB), concurrent IP limit, online count, status (active/disabled/expired/over-limit), bulk actions.
- QR code (link + subscription), subscription link with **landing page** (browser shows account details; VPN clients get plain text; `/raw` forces plain).

## Server & network

CPU load, RAM, disk, uptime, network RX/TX totals + rates, per-interface stats, VPN traffic totals, Xray/Warp/Asterisk status.

## Warp & routing

Cloudflare WARP (WireGuard) outbound for YouTube/Google/OpenAI/Telegram + custom routing rules with presets.

## L2TP / IKEv2

IPsec (strongswan) + L2TP (xl2tpd), PSK from Settings, per-user PPP accounts, ports UDP 500/4500/1701.

## Bot, backup, migration, update

- Telegram bot: `/add /list /links /status /l2tp /version /del /reset /enable /disable` (token in Settings).
- Backup: DB download, restore, auto-backup every 24h to the bot.
- Migration: JSON export/import (Sirgsm + Marzban formats) preserving duration & volume.
- Update: check GitHub releases, one-click update.
