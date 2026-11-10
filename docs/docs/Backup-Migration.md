# Backup & Migration

## Backup / Restore

**Panel > Settings > Backup:**

- **Download backup (DB)**: downloads a consistent SQLite copy of `panel.db`.
- **Restore**: upload a `.db` file — the current DB is backed up first, then replaced (panel + Xray restart).
- **Manual backup to bot**: sends the DB file to the admin via Telegram.
- **Auto-backup**: every 24 hours (configurable) the panel sends a DB backup to the bot if the bot token + admin ID are set. Files are kept in `/opt/sirgsm-panel/backups/` (last 7).

## User migration (export / import)

**Users tab > Export / Import:**

- **Export (Sirgsm)**: JSON with `email, inbound, uuid, password, traffic_limit (bytes), expiry (timestamp), ip_limit, enable, note, up, down` — preserves duration & volume.
- **Export (Marzban)**: Marzban-compatible JSON (`username, proxies, expire, data_limit, status, note`) — import it into Marzban directly.
- **Import**: upload JSON (Sirgsm or Marzban format) — creates users with their expiry & volume. Existing emails are skipped.

Example (Sirgsm format):

```json
[{"email":"ali","inbound":"vless","uuid":"...","traffic_limit":10737418240,"expiry":1799999999,"ip_limit":2,"enable":true}]
```

`traffic_limit` is in bytes (10 GB = 10737418240), `expiry` is a Unix timestamp (0 = unlimited).
