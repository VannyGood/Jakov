# Jakov

A Telegram bot for your own channels and groups:

- **Publisher**: write and schedule posts with generated text and animated custom emoji.
- **Guard**: rule-based moderation of groups and channel comments (links, ads, spam).
- **Scanner**: checks links and files for malware and phishing.

> Status: **Phase 1 of 6**: skeleton, config, database and migrations, admin access, main
> menu, channel linking, timezone and the custom emoji test. The other modules arrive in
> later phases.

## Quick start (local, long polling)

```bash
cp .env.example .env      # then fill BOT_TOKEN and ADMIN_IDS
./scripts/run.sh          # creates .venv, applies migrations, starts the bot
```

Requires Python 3.12+ (developed on 3.14). Then open your bot in Telegram and send `/start`.

### Getting the values

| Variable | Where it comes from |
|---|---|
| `BOT_TOKEN` | @BotFather → `/newbot` (or `/token` for an existing bot). Never commit it. |
| `ADMIN_IDS` | Your numeric user ID from @userinfobot. Comma-separate several admins. |
| `TIMEZONE` | Default IANA zone. Each admin can set their own in **/settings → Timezone** by sharing their location (looked up offline, coordinates are not stored). |

Anyone who is not in `ADMIN_IDS` gets **no response** in private chat.

## Linking a channel or group

1. Add the bot as an **admin**. For channels give it **Post messages** and **Edit messages**
   (editing is also what lets bots pin in channels).
2. If you add it yourself, Jakov links the chat automatically and DMs you.
   Otherwise use **/channels → ➕ Add** and forward any post from the chat, or send its
   `@username`, `t.me/...` link or numeric ID.
3. Jakov checks that it is an admin with posting rights and that **you** are an admin there.

Jakov tracks being added, removed, demoted or losing rights and messages you each time.
If a group is upgraded to a supergroup, its new ID is picked up automatically.

## Custom (animated) emoji

Since **Bot API 9.4 (Feb 2026)**, bots may send custom emoji when the **bot owner has
Telegram Premium**. This works in private chats, groups and supergroups. Before that, bots
needed an extra username bought on Fragment. **Channels are not explicitly covered** by the
rule, so Jakov never assumes. It tests:

- **In your DM** on the first `/start` (and again from **/settings → 🧪 Custom emoji test**).
- **Per chat** from **/channels → (chat) → 🧪 Test custom emoji**. This posts one silent
  message and deletes it right away.

The bot sends a real `<tg-emoji>` message and checks whether Telegram kept the
`custom_emoji` entity. If not, Jakov falls back to normal emoji automatically and says so.

If custom emoji are unavailable, the realistic alternatives are:
- keep the bot owner's Premium subscription active (the current official route);
- post animated **stickers** or GIFs next to the text instead of inline emoji;
- send posts from a user account (userbot). This is against the spirit of the Bot API and not
  supported by Jakov.

## Development

```bash
.venv/bin/pytest            # unit + integration tests (Telegram is faked, no network)
.venv/bin/ruff check .
.venv/bin/mypy              # strict
.venv/bin/alembic revision --autogenerate -m "describe change"
```

Layout: `handlers/` (thin aiogram routers) → `services/` (Telegram and database work) →
`engine/` (pure logic) and `db/` (models, repositories, migrations). Every table has an
`owner_id` so Jakov can become multi-user later. Today all rows belong to the first admin
in `ADMIN_IDS`.

Wizard progress (FSM) is stored in the database, so a restart doesn't lose half-finished
steps. Logs go to `var/logs/jakov.log` (JSON, rotated 5 × 5 MB). Bot tokens and API keys
are redacted from every log line.

### Webhook mode (optional)

Set `RUN_MODE=webhook`, `WEBHOOK_BASE_URL=https://your.domain`, `WEBHOOK_SECRET=...`.
The bot then listens on `WEBHOOK_HOST:WEBHOOK_PORT` at `WEBHOOK_PATH`.
