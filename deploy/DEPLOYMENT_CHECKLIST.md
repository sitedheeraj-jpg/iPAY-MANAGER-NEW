# Deployment Checklist

Use this checklist before and after deploying the bot. Do not put real tokens or
database passwords in this file or commit them to Git.

## 1. Before deployment

- [ ] Rotate the MongoDB password that was shared in the original project brief.
- [ ] Create or confirm the MongoDB Atlas database user.
- [ ] Allow the deployment platform's outbound access in MongoDB Atlas Network Access.
      For a quick first deployment, `0.0.0.0/0` can be used with a strong
      password; restrict it later if your hosting setup provides fixed egress IPs.
- [ ] Create a Telegram bot with BotFather.
- [ ] Copy the bot token into the hosting platform's secret/environment settings.
- [ ] Find the numeric Telegram ID for every owner.
- [ ] Confirm `OWNER_IDS` is comma-separated, for example `123456789,987654321`.
- [ ] Confirm the MongoDB URI has its username/password URL-encoded if either
      contains special characters.
- [ ] From the project root, run `python -m deploy.verify_env` and confirm both
      checks pass.

Required variables:

| Variable | Example | Secret |
| --- | --- | --- |
| `BOT_TOKEN` | `123456:AA...` | Yes |
| `MONGODB_URI` | `mongodb+srv://user:password@cluster/...` | Yes |
| `MONGODB_DB` | `agent_member_bot` | No |
| `OWNER_IDS` | `123456789,987654321` | No |
| `LOG_LEVEL` | `INFO` | No |

## 2. Render

- [ ] Create a Blueprint from `render.yaml`, or create a Background Worker.
- [ ] Confirm the service type is **Background Worker**, not a web service.
- [ ] Set `BOT_TOKEN` as a secret environment variable.
- [ ] Set `MONGODB_URI` as a secret environment variable.
- [ ] Set `MONGODB_DB` to `agent_member_bot`.
- [ ] Set `OWNER_IDS`.
- [ ] Keep the build command: `pip install -r requirements.txt`.
- [ ] Keep the start command: `python -m app`.
- [ ] Deploy the worker.
- [ ] Open the deployment logs and confirm `Connected to MongoDB`.
- [ ] Open the bot in Telegram and send `/start`.

Render uses a `starter` Background Worker because Telegram long polling does
not require a public HTTP port.

## 3. Railway

- [ ] Create a new Railway project from this source.
- [ ] Confirm Railway detects the included `Dockerfile`.
- [ ] Add `BOT_TOKEN`.
- [ ] Add `MONGODB_URI`.
- [ ] Add `MONGODB_DB=agent_member_bot`.
- [ ] Add `OWNER_IDS`.
- [ ] Add `LOG_LEVEL=INFO`.
- [ ] Deploy the service.
- [ ] Confirm the service is running and has not entered a restart loop.
- [ ] Open the deploy logs and confirm `Connected to MongoDB`.
- [ ] Open the bot in Telegram and send `/start`.

This bot is a worker process. Railway does not need a public HTTP port for it.

## 4. Linux VPS

- [ ] Copy the project to `/opt/agent-member-bot`.
- [ ] Confirm the server has Python 3.11 or newer.
- [ ] Run:

```bash
cd /opt/agent-member-bot
sudo bash deploy/vps/install.sh
```

- [ ] Edit the environment file:

```bash
sudo nano /opt/agent-member-bot/.env
```

- [ ] Set `BOT_TOKEN`, `MONGODB_URI`, `MONGODB_DB`, `OWNER_IDS`, and `LOG_LEVEL`.
- [ ] Start the service:

```bash
sudo systemctl start agent-member-bot
sudo systemctl enable agent-member-bot
```

- [ ] Check service status:

```bash
sudo systemctl status agent-member-bot --no-pager
```

- [ ] Check live logs:

```bash
sudo journalctl -u agent-member-bot -f
```

- [ ] Confirm the logs show `Connected to MongoDB`.
- [ ] Open the bot in Telegram and send `/start`.

## 5. Functional verification

- [ ] `/start` asks a new Telegram user for a custom UID.
- [ ] A duplicate UID is rejected.
- [ ] The admin receives a registration notification.
- [ ] Admin approval unlocks the user's dashboard.
- [ ] Admin rejection locks the user and sends a notification.
- [ ] Balance opens correctly.
- [ ] Admin credit creates a credit transaction.
- [ ] Admin debit cannot reduce the balance below zero.
- [ ] History shows the latest transactions.
- [ ] Agent users can submit team additions.
- [ ] Team additions appear in the admin queue.
- [ ] Approved team additions create the member account.
- [ ] Withdrawals appear in the admin queue.
- [ ] Approved withdrawals create a debit transaction.
- [ ] A withdrawal larger than the current balance stays pending.
- [ ] `/admin` is blocked for non-admin users.
- [ ] Owners can add/remove database-backed admins from `/admins`.
- [ ] Approving/rejecting a request edits all owner/admin copies and removes
      their action buttons.
- [ ] `/start` shows iPAY copy and a green-styled registration link; a valid
      UID submission deletes the user's UID message and edits the welcome
      message to the submitted state.
- [ ] Rejected users receive iPAY registration and UID-resubmission buttons.
- [ ] Telegram message effects appear for welcome, registration rejection /
      approval, task submission, and task reward approval (on supported clients).
- [ ] If Telegram rejects any effect ID, the same message is retried without an
      effect and still reaches the user.
- [ ] `/cancel` clears active forms.
- [ ] `/help`, `/profile`, `/balance`, `/history`, `/withdraw`, `/id`, and
      `/menu` appear in Telegram's command menu.
- [ ] Agents can use `/team` to view approved members.
- [ ] A QR image can be submitted as withdrawal payment details and is delivered
      to the admin for review.
- [ ] `/submit_task` accepts a task description and one or more screenshots.
- [ ] Submitted task proof images reach the admin with Approve/Reject buttons.
- [ ] Approving a task asks the admin for a reward amount.
- [ ] The reward creates a credit transaction and updates the user's balance.
- [ ] The user receives a task approval/reward notification with the new balance.
- [ ] Rejecting a task notifies the user and does not change their balance.

## 6. MongoDB verification

After the first successful start, the application creates these collections and
indexes automatically:

- `users`
- `transactions`
- `withdrawals`
- `team_additions`

Confirm in MongoDB Atlas that the unique indexes exist for:

- `users.telegram_id`
- `users.custom_uid`
- `transactions.transaction_id`
- `withdrawals.withdrawal_id`
- `team_additions.addition_id`

## 7. Operations and rollback

- [ ] Keep the bot token and MongoDB URI only in platform secrets.
- [ ] Do not upload `.env` to a public repository.
- [ ] Export or back up MongoDB before major code changes.
- [ ] Keep the previous deployment version available.
- [ ] If a release fails, redeploy the previous version and inspect logs.
- [ ] If credentials may have leaked, rotate the Telegram token and MongoDB password.

Useful VPS commands:

```bash
sudo systemctl restart agent-member-bot
sudo systemctl stop agent-member-bot
sudo journalctl -u agent-member-bot --since "30 minutes ago" --no-pager
```