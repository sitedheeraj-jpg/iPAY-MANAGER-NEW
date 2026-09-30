# Agent / Member Management Telegram Bot

Production-oriented Telegram bot built with:

- Python 3.11+
- aiogram 3.x (async Telegram framework)
- MongoDB via Motor (async MongoDB driver)
- aiogram FSM for multi-step forms

The bot supports member registration and approval, agent team additions, balances,
transaction history, withdrawals, admin pagination, admin fund management,
multiple owners, and owner-managed admins.

## Security first

The MongoDB URI from the original brief is **not embedded in this project**.
Put it in `.env` or your deployment platform's secret/environment settings.
Because a database password was shared in the original brief, rotate that
credential in MongoDB before deploying this bot.

Never commit `.env`, bot tokens, or database credentials.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with BOT_TOKEN, MONGODB_URI, and OWNER_IDS
python -m app
```

`OWNER_IDS` is a comma-separated list of Telegram numeric user IDs. Every owner
can use `/admin` and manage database-backed admins from the **Manage Admins**
button or `/admins`. Existing deployments can keep using `ADMIN_IDS`; when
`OWNER_IDS` is empty, its values are treated as owners for backwards compatibility.
Admins added by an owner are persisted in MongoDB and survive restarts.
Both `OWNER_IDS=100,200` and JSON-array values such as `OWNER_IDS=[100,200]`
are accepted by the settings parser.

## Deployment

The included `Dockerfile` runs the bot as a long-running polling process:

```bash
docker build -t agent-member-bot .
docker run --env-file .env --restart unless-stopped agent-member-bot
```

### Render

The included `render.yaml` defines the bot as a background worker, which is the
correct Render service type for Telegram long polling. In Render:

1. Create a new Blueprint from this repository, or create a Background Worker.
2. Set `BOT_TOKEN`, `MONGODB_URI`, and `OWNER_IDS` as secret environment variables.
3. Keep the generated `MONGODB_DB` and `LOG_LEVEL` values, or change them.

The build and start commands are already defined:

```text
pip install -r requirements.txt
python -m app
```

### Railway

Railway can deploy the included `Dockerfile` directly. `railway.json` and
`railway.toml` provide the same Docker/start/restart configuration:

1. Create a new Railway project from the source repository.
2. Add the variables from `.env.example`.
3. Deploy the service.

No public HTTP port is required because the bot uses Telegram long polling.

### VPS with systemd

For Ubuntu/Debian or another Linux VPS with Python 3.11+:

```bash
sudo mkdir -p /opt/agent-member-bot
sudo cp -R agent_member_bot/. /opt/agent-member-bot/
cd /opt/agent-member-bot
sudo bash deploy/vps/install.sh
sudo nano /opt/agent-member-bot/.env
sudo systemctl start agent-member-bot
sudo journalctl -u agent-member-bot -f
```

The installer creates a restricted `agentbot` system user, a virtual
environment, and an automatically restarting systemd service.

For the full prefilled launch and verification checklist, see
`deploy/DEPLOYMENT_CHECKLIST.md`.

After setting the environment variables, verify the configuration and MongoDB
connection with:

```bash
python -m deploy.verify_env
```

### Manual PaaS commands

For a PaaS without native configuration support, use:

- Build command: `pip install -r requirements.txt`
- Start command: `python -m app`
- Runtime: Python 3.11+

Set `BOT_TOKEN`, `MONGODB_URI`, `MONGODB_DB`, and `OWNER_IDS` as secrets or
environment variables in the platform.

## MongoDB

On startup the bot creates these collections and indexes:

- `users`: unique Telegram ID and custom UID
- `transactions`: indexed user/timestamp and unique transaction ID
- `withdrawals`: indexed status/user/timestamp and unique withdrawal ID
- `team_additions`: indexed status/agent/timestamp and unique addition ID
- `tasks`: indexed status/user/timestamp and unique task ID
- `admins`: unique Telegram ID with Owner/Admin role
- `admin_notifications`: tracks each admin/owner copy so decisions sync everywhere
- `broadcasts`: audit log of every broadcast (audience, totals, delivered/blocked/failed)

The `team_additions` collection is required to keep team requests separate from
approved users until an administrator reviews them.

## User flow

1. A user sends `/start` and submits a unique custom UID.
2. An admin receives Approve / Reject buttons.
3. Approved users receive the dashboard. A rejected effect ID is retried without
   animation, so it cannot prevent the message from being delivered.
4. Agents can submit team additions; those also require admin approval.
5. Users can request withdrawals with an amount and UPI ID or QR text.
6. An admin approves or rejects withdrawals. Approval atomically deducts funds
   and creates a debit transaction.
7. Users submit completed task descriptions with one or more screenshot proofs.
8. Admins approve/reject task proofs; approval asks for a reward amount, credits
   the user's wallet, records a credit transaction, and notifies the user.

## Admin commands

- `/admin` — open the admin dashboard
- `/users` — browse and manage all registered users
- `/admins` — manage admins (owners only)
- `/broadcast` — send a message or photo to members
- `/cancel` — cancel the current FSM form

## User commands

- `/start` — register or open the dashboard
- `/menu` — open the dashboard
- `/profile` — view profile and UID binding
- `/balance` — view wallet balance
- `/history` — view the latest 10 balance transactions
- `/withdraw` — submit a UPI ID or QR-image withdrawal request
- `/submit_task` — submit a completed task with screenshot proof
- `/my_tasks` — view task statuses and rewards
- `/add_team` — submit a team member for approval (agents)
- `/team` — view approved team members (agents)
- `/id` — show Telegram ID
- `/help` — show commands and usage
- `/cancel` — cancel the active form

Commands are registered automatically with Telegram when the bot starts.

The admin panel includes pending users, pending team additions, pending
withdrawals, pending task proofs, user search, add/deduct balance controls,
and owner-only admin management. When any admin or owner approves/rejects a
request, all stored copies of that request are edited with the decision and
their action buttons are removed. This includes task proof photos and
withdrawal QR messages.

The registration flow is branded for iPAY, links users to the official
registration URL, edits the original welcome prompt after a UID is submitted,
and provides a resubmission action when registration is rejected. Telegram
message effects are used for welcome, rejection, registration approval, task
submission, and task reward approval. Effects are shown by Telegram clients
that support message effects.

## Broadcasts

Admins and owners can send an announcement from **Admin Panel → 📢 Broadcast**
or with `/broadcast`:

1. Pick an audience: approved users, agents only, regular users only, or
   everyone who has started the bot. Live recipient counts are shown.
2. Send the announcement as a text message or a single photo with an optional
   caption. Bold/italic/links are preserved because the message is copied
   as-is.
3. The bot shows a preview of exactly what members will receive. Tap
   **Send** to start or **Cancel** to abort.
4. Delivery runs in the background at ~25 messages/second (under Telegram's
   limit), automatically waits and retries on flood-control responses, and
   counts users who blocked the bot separately from other failures. A live
   progress message has a **Stop broadcast** button.

Only one broadcast can run at a time. Each broadcast is recorded in the
`broadcasts` collection.

## Telegram button colors

The code uses the modern Bot API `style` values `primary`, `success`, and
`danger` on inline buttons. Telegram clients that do not yet render button
styles will still show the buttons and their text normally.