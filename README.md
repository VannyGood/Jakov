# Jakov

A Telegram bot for your own channels and groups:

- **Publisher**: write and schedule posts with generated text and animated custom emoji.
- **Guard**: rule-based moderation of groups and channel comments (links, ads, spam).
- **Scanner**: checks links and files for malware and phishing.

> Status: **Phase 2 of 6**: channel linking, the post wizard with template and emoji engine,
> animated menus, Send now, and editing or deleting published posts. Scheduling, Guard and
> Scanner arrive in later phases.

## Quick start (local, long polling)

```bash
cp .env.example .env      # then fill BOT_TOKEN and ADMIN_IDS
./scripts/run.sh          # creates .venv, applies migrations, starts the bot
./scripts/stop.sh         # graceful stop
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

## Writing posts (✍️ New post or /newpost)

1. Pick a type: 🎮 Game invite, 🛒 Sell something, 💘 Romantic, 📣 Announcement,
   🎁 Giveaway or ✏️ Custom.
2. Answer a few short questions. Optional ones have **⏭ Skip**. Dates accept
   `friday 20:00`, `25.12 18:00`, `tomorrow 9am`, `in 3 days`, … in your timezone.
3. Pick a tone (🔥 Hype, 😎 Chill, 😂 Funny, 💼 Serious), then optionally attach one photo or
   video, and link buttons (`Label - https://link`, one per line).
4. Jakov sends **3 real previews**. Under each one: **✅ Use this** or **✏️ Edit**. Below
   them: **🔁 Rotate all 3**, **🔄 Regenerate**, **🎭 Change emojis**, and **🎨 Style**
   (Mixed, or one pack such as Dogs or Snoop Dogg).
5. On the ready card, toggle 📌 pin, 🔕 silent and 🔗 link preview, then **📨 Send now**.
   Scheduling arrives in Phase 3.

Every published post is stored (chat and message ID). **📰 Published** (/posts) lets you
open, edit the text of, or delete any of them.

### Templates (no AI needed)

Templates live in `data/templates/<type>.yaml`. Each tone has lists of `hooks`, `bodies` and
`ctas`, and a post combines one of each. Inside a line:

| Syntax | Meaning |
|---|---|
| `{Hello\|Hi\|Hey}` | spintax: one option is picked; groups can nest |
| `{product}`, `{price}`, … | answers from the wizard (HTML-escaped automatically) |
| `{date}`, `{weekday}`, `{time}`, `{countdown}`, `{deadline}`, `{channel}` | filled at send time in your timezone |
| `{tip}`, `{quote}`, `{fact}` | rotate through `data/pools/*.yaml` without repeats |
| `{emoji:fire}`, `{emoji}` | an emoji for that mood, or a generic one matching type and tone |
| `[[ … ]]` | optional block: removed when a value inside it is empty |

Moods are defined in `data/emoji_moods.yaml`. Jakov validates every template at startup,
and the tests render all of them.

## Emoji library (😀 Emoji library or /emoji)

On the first start, Jakov imports the starter packs from `data/starter_packs.yaml`
(RestrictedEmoji, DogsEmoji, two Snoop Dogg packs, DuckEmoji, PepeEmoji, GameIcons, …):
about 1,800 animated emoji. Static emoji are skipped.

- `/emojipack https://t.me/addemoji/Name` imports a pack.
- `/addemoji fire`, then send a message with your own custom emoji, tags them with a mood.
- Browse by **pack** or by **mood**. Tap an emoji to tag, untag or delete it. Packs can be
  disabled or removed.

Emoji are tagged with moods automatically from their base character (🔥 → fire, 💰 → money,
…), so any pack works with every template right away.

### Animated menus

Every message and button the bot sends to an admin uses the animated version of its emoji
(Bot API 9.4 custom emoji and button icons). Turn it off, or pick the pack used for menus,
in **⚙️ Settings**. Previews and real posts are never rewritten, so a preview always shows
exactly what will be published.

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
