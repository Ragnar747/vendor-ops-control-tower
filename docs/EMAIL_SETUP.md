# Connecting a real mailbox (optional)

The project works fully offline with the demo mailbox in `data/inbox/`.
This guide is only for showing it working with a **real Gmail inbox**.

⚠️ Use a **separate test Gmail account**, never your personal one, and only send it
**fake vendor emails** (you can forward the demo `.eml` files to it).

## 1. Create a Gmail app password
1. In the test Gmail account, turn on **2-Step Verification** (Google Account → Security).
2. Then Google Account → Security → **App passwords** → create one named
   `vendor-control-tower`.
3. Google shows a 16-character password. Copy it. **Never put it in code or GitHub.**

## 2. Set it for this terminal session only (PowerShell)
```
$env:VENDOR_MAILBOX = "imap"
$env:VENDOR_IMAP_USER = "your-test-account@gmail.com"
$env:VENDOR_IMAP_PASSWORD = "the 16-character app password"
```
These disappear when you close the terminal, which is safer than saving them.

The intake reads only emails from `@vendors.example.com` senders by default.
For a real test, change `VENDOR_EMAIL_DOMAIN` in `src/config.py` and the addresses in
`data/clean/vendor_contacts.csv` to match whoever sends the test emails.

The mailbox is opened **read-only**: nothing is deleted or marked as read.

## 3. Sending emails (optional)
By default every email is only saved to `data/outbox/`. To really send them:
```
$env:VENDOR_SEND_EMAILS = "true"
```
⚠️ Only do this when every recipient address is one you control.

## 4. Run it every morning (Windows Task Scheduler)
1. Open **Task Scheduler** → **Create Basic Task** → name it "Vendor Control Tower".
2. Trigger: **Daily**, e.g. 7:00 am.
3. Action: **Start a program**
   - Program: `C:\path\to\project\.venv\Scripts\python.exe`
   - Arguments: `run_all.py`
   - Start in: `C:\path\to\project`
4. Each run writes a log to `data/logs/`.
