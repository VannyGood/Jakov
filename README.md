# Jakov

A Telegram bot for your own channels and groups:

- **Publisher**: write and schedule posts with generated text and animated custom emoji.
- **Guard**: rule-based moderation of groups and channel comments (links, ads, spam).
- **Scanner**: checks links and files for malware and phishing.

> Status: **Phase 3 of 6**: channel linking, the post wizard with the writing engine,
> animated menus, Send now, scheduling with approvals, and editing or deleting published
> posts. Guard and Scanner arrive in later phases.

## Quick start (local, long polling)

```bash
cp .env.example .env      # then fill BOT_TOKEN and ADMIN_IDS
./scripts/run.sh          # creates .venv, applies migrations, starts the bot
./scripts/stop.sh         # graceful stop
```

Requires Python 3.12+ (developed on 3.14). Then open your bot in Telegram and send `/start`.
That's the only command: everything else is behind buttons.

### AI writer (optional, recommended)

Posts are written by a small **local** model through [Ollama](https://ollama.com), free and
private:

```bash
brew install ollama && brew services start ollama   # macOS; see ollama.com for Linux
ollama pull gemma3:1b                                 # ~800 MB
```

Settings: `LLM_ENABLED`, `OLLAMA_URL`, `OLLAMA_MODEL`, `LLM_TIMEOUT_S` (see `.env.example`).
If Ollama isn't running, Jakov automatically uses its built-in writer instead, so posting
and schedules never fail. ⚙️ Settings shows which writer is active.

How it stays accurate: the model writes only the prose (headline, intro, body, closing,
call to action), returned as structured JSON. **Facts never pass through the model.** Product,
price, offer, dates and links are inserted by code from your answers. Every section the
model returns is checked: invented numbers, links, hashtags, markdown, promises of links that
don't exist and over-long text are rejected, and the built-in writer fills the gap. Plain
emoji the model writes become animated ones from your library. AI-written scheduled posts are
**rewritten fresh on every send**.

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

## Writing posts (✍️ Create a post)

1. Pick a type: 🎮 Game invite, 🛒 Sell something, 💘 Romantic, 📣 Announcement,
   🎁 Giveaway or ✏️ Custom.
2. Answer a few short questions. Optional ones have **⏭ Skip**. Dates accept
   `friday 20:00`, `25.12 18:00`, `tomorrow 9am`, `in 3 days`, … in your timezone.
3. Pick a tone (🔥 Hype, 😎 Chill, 😂 Funny, 💼 Serious). On the **Almost done** screen, send a
   photo or video to attach it, or send `Label - https://link` lines to add buttons. Both are
   optional. Then tap **✨ Create my post**.
4. Jakov sends **3 real previews**. Under each one: **✅ Use this** or **✏️ Edit**. Below
   them: **🔁 Rotate all 3**, **🔄 Regenerate**, **🎭 Change emojis**, and **🎨 Style**
   (Mixed, or one pack such as Dogs or Snoop Dogg).
5. On the ready card, toggle 📌 pin, 🔕 silent and 🔗 link preview, then **📨 Send now** or
   **⏰ Schedule**.

Every published post is stored (chat and message ID). **📰 Published** (/posts) lets you
open, edit the text of, or delete any of them.

### Built-in writer (backup when the AI is off)

Posts are composed from **layouts** (`data/layouts.yaml`) filled with **sections** written per
post type and tone (`data/templates/<type>.yaml`):

| Layout | Shape |
|---|---|
| classic | headline → intro + body → call to action |
| spotlight | headline → intro → bullet facts → call to action |
| story | narrative → `<blockquote>` highlight → call to action |
| punchy | headline + call to action |
| signature | headline → body → bullet facts → italic closing → call to action → P.S. |

Sections: `headline`, `intro`, `body`, `points` (bullet facts), `closing`, `cta`, `action`
(a call to action without facts, for layouts that list them already) and `ps`. Three
variations always try three different layouts, and every variation mentions your key
answers (product, game, prize…). A final tidy pass fixes punctuation (`now!.` → `now!`),
spacing and lowercase line starts. Text you write yourself keeps your own casing. Inside a line:

| Syntax | Meaning |
|---|---|
| `{Hello\|Hi\|Hey}` | spintax: one option is picked; groups can nest |
| `{product}`, `{price}`, … | answers from the wizard (HTML-escaped automatically) |
| `{product.upper}`, `.title`, `.lower`, `.a` | filters; `.a` adds "a" or "an" (`an Air Max`) |
| `{date}`, `{weekday}`, `{time}`, `{countdown}`, `{deadline}`, `{channel}` | filled at send time in your timezone |
| `{tip}`, `{quote}`, `{fact}` | rotate through `data/pools/*.yaml` without repeats |
| `{emoji:fire}`, `{emoji}` | an emoji for that mood, or a generic one matching type and tone |
| `[[ … ]]` | optional block: removed when a value inside it is empty |

Moods are defined in `data/emoji_moods.yaml`. Jakov validates every template at startup,
and the tests render all of them.

## Scheduling (⏰ Schedule, /schedules)

From a ready post: **⏰ Schedule** → chat → **once**, **every day at HH:MM** or **every N
minutes/hours** → stop **never**, after **N posts** or **on a date** → options:

- **🔁 Rotate variations**: cycle through the variations; every send re-spins the text and
  picks new emoji, so repeated posts never look identical.
- **🛂 Ask my approval**: the bot DMs you the exact post with ✅ Approve / ⏭ Skip / ✏️ Edit.
  Nothing is posted without Approve. If you don't answer within `APPROVAL_TIMEOUT_MINUTES`
  (default 30), the run is skipped and logged.

`/schedules` lists everything with its next run in your timezone: pause, resume, send now,
edit timing, edit post, history (last 10 runs with reasons) and delete.

**Reliability**
- Times are stored in UTC and shown in your timezone. Daily times follow DST: a time that
  doesn't exist that day (spring forward) runs at the shifted time; an ambiguous one (fall
  back) runs once, at the first occurrence. "Every N hours" counts real time.
- **Catch-up**: a run that is less than `CATCHUP_GRACE_MINUTES` late (default 15) is sent;
  older ones are skipped and logged as one summary. A long outage never causes a burst.
- **No duplicates**: each run is reserved (unique run key) before sending. If the bot is
  killed in the middle of a send, that run is marked *uncertain* on restart and you are told.
  It is never re-sent automatically.
- **One outgoing queue** for all posts: ~30 messages/s overall, 1/s per private chat, ≤20/min
  per group or channel. Telegram's `RetryAfter` is honoured exactly; network errors back off
  1 s → 2 s → 4 s.
- If the bot is removed or loses posting rights, that chat's schedules **pause** and you get
  a ▶️ Resume button. Resuming continues from now on, without replaying missed runs.

## Emoji library (😀 Emoji library or /emoji)

Jakov imports the starter packs from `data/starter_packs.yaml`: Google's
**NotoEmojiAnimated**, **PremiumIcons**, DogsEmoji, two Snoop Dogg packs,
TenYearsOfTelegram, DuckEmoji, PepeEmoji, GameIcons, … and RestrictedEmoji. That's about
2,200 animated emoji (static ones are skipped). Packs added to that file later are imported
on the next start; packs you deleted are not brought back. Posts prefer the expressive packs.
RestrictedEmoji (animated standard emoji) is only a fallback.

- `/emojipack https://t.me/addemoji/Name` imports a pack.
- `/addemoji fire`, then send a message with your own custom emoji, tags them with a mood.
- Browse by **pack** or by **mood**. Tap an emoji to tag, untag or delete it. Packs can be
  disabled or removed.

Emoji are tagged with moods automatically from their base character (🔥 → fire, 💰 → money,
…), so any pack works with every template right away.

### Only emoji that really move

Some "animated" packs contain emoji whose animation never changes. They look frozen (all
of GameIcons and MovieIcons, most of PremiumIcons). Jakov downloads every emoji once,
measures how much its animation moves, and **never uses frozen ones**, neither in menus nor
in posts. AdaptivePremium, TopicIcons and AdaptiveLines are removed and blocked
(`retired` in `data/starter_packs.yaml`).

### Animated menus

Every message and button the bot sends to an admin uses the animated version of its emoji
(Bot API 9.4 custom emoji, button icons and **colored buttons**: blue for the main action,
green to confirm or send, red to cancel or delete). Menu icons come from
`data/ui_icons.yaml`, generated from the measured motion: Google's animated Noto emoji first,
then moving PremiumIcons, then Telegram's animated set. In **⚙️ Settings** you can turn animated
menus off or use any pack as the menu style. Previews and real posts are never rewritten, so a preview always shows
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
