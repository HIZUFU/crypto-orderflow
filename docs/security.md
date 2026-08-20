# Security and API keys

## Current version

The collector uses Bybit public WebSocket streams. This requires no API key and no account access. The web service is intended for localhost only and has no login yet. Do not expose it to the Internet.

## Future account key

When account data is needed, create a dedicated application key at the exchange, separate from the main account credentials. Required permissions should be added in stages:

1. Read-only account/balance/positions/order history for reconciliation.
2. Trading permission only when live execution has been explicitly enabled and tested.

Disable withdrawals, transfers, asset management, and account settings. Enable an IP allowlist where the exchange supports it. Never provide a seed phrase, password, 2FA code, or withdrawal permission.

For Bybit, the API uses an API key plus secret for HMAC authentication, or a self-generated RSA key pair. The private RSA key must remain on the machine. Store secrets in a local secret manager or a locked `.env` file outside Git. Never put them in frontend JavaScript, Telegram messages, logs, Docker images, or GitHub Actions output.

## Operational controls

- Keep the dashboard bound to localhost.
- Use a firewall and VPN before any remote access.
- Back up only encrypted configuration and database data.
- Mask keys in logs and UI.
- Add authentication and an audit log before remote access.
- Keep live execution in a separate module with an explicit two-step confirmation and emergency stop.

## Incident response

If a key may have leaked, revoke it at the exchange immediately, create a replacement, inspect account activity, and rotate local secrets. Do not attempt to hide a leaked secret by deleting a later commit; revoke it because Git history may retain it.
