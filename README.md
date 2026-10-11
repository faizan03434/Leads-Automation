# Bytora Mail Studio

Double-click **start.bat**, or run `python server.py` and open http://127.0.0.1:8765. Python 3.10+ is required; no extra packages are needed.

1. Gmail SMTP is prefilled: `smtp.gmail.com`, SSL/TLS, port `465`, username and From address `bytora.officials@gmail.com`, and sender name `Muhammad Faizan | Bytora`. Enter your Gmail app password and click **Test & connect mailbox**.
2. Drop a UTF-8 CSV with `name,email` columns. Your supplied CSV matches this format. Empty names and invalid emails are skipped; email addresses are deduplicated across all imports.
3. Edit and save your subject/body. `{{name}}` is replaced for each lead. Preview the first lead.
4. Review recipients, check the confirmation box, and click **Send product emails**. Each run sends only pending leads, up to the chosen limit. Start another run for the remaining leads.
5. Review statuses or export them. Retry failures deliberately. Check your Sent folder before retrying uncertain delivery to avoid duplicates.

The database stores leads, statuses, and the template on this computer. SMTP credentials stay only in memory. Keep the server running during sending. Stop allows the active email to finish. A restarted server marks interrupted delivery as uncertain. Sent means SMTP acceptance, not inbox delivery. There is no automatic retry or bounce/unsubscribe ingestion; process unsubscribe replies and remove suppressed contacts from future source lists. This is a local, single-user application; do not expose its port to the internet.

## Inbox setup

No software can guarantee emails avoid spam. Authenticate your domain with SPF and DKIM using your provider's exact DNS records, then configure DMARC. Use a verified sender aligned with your domain, relevant messages, permission-based lists and your provider's sending limits. Begin with a small run. Avoid purchased lists and misleading subjects. Honor opt-out replies before sending more mail. The default 30-second interval and 25-email run cap control volume; they do not guarantee deliverability.

SMTP authentication is tested; DNS authentication and inbox placement are not checked by this app. Live sending requires your mailbox credentials. No emails are sent merely by uploading a CSV.
