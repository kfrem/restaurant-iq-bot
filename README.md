# Restaurant-IQ Bot

A Telegram bot that captures operational data from restaurant staff —
voice notes, invoice photos, and text updates — and turns it into a
weekly AI-generated intelligence briefing with a branded PDF report.

---

## Your AI Upgrade Path (Fully Automatic)

The bot switches AI providers by itself as you grow.
**You never touch any code.** You just add the three API keys to Railway
and the system handles the rest.

| Restaurants registered | AI Provider | Cost | Quality |
|------------------------|------------|------|---------|
| 0 – 49 | Google Gemini | **FREE** | Good |
| 50 – 99 | Groq / Llama | **FREE** | Better |
| 100+ | Claude (Anthropic) | ~£5/month | Best |

To see which AI tier is currently active, send `/status` in any registered group.

---

## SETUP GUIDE (Read this — it's all you need to do)

---

### STEP 1 — Get your three API keys

You need three keys total. You only need the first two **right now**.
Get all three in advance so the system switches automatically.

---

#### Key 1: Telegram Bot Token (needed NOW)

1. Open Telegram on your phone or computer
2. Search for **@BotFather** and open that chat
3. Send this message: `/newbot`
4. It will ask for a name — type something like: `Restaurant IQ`
5. It will ask for a username — type something like: `MyRestaurantIQBot`
   *(must end in the word `bot`)*
6. BotFather will send you a token that looks like this:
   `123456789:ABCdefGHIjklmNOPqrstUVwxyz`
7. Copy that token — you'll need it in Step 2

---

#### Key 2: Google Gemini API Key (needed NOW — completely FREE)

1. Go to this website: **https://aistudio.google.com/app/apikey**
   *(Sign in with your Google account if asked)*
2. Click the blue **"Create API key"** button
3. A key will appear — it starts with `AIzaSy...`
4. Click the copy icon next to it
5. Keep it safe — you'll paste it in Step 2

---

#### Key 3: Groq API Key (FREE — add this before you hit 50 restaurants)

1. Go to: **https://console.groq.com/keys**
   *(Create a free account with your email — no credit card)*
2. Click **"Create API Key"**
3. Give it any name, like `restaurant-iq`
4. The key starts with `gsk_...`
5. Copy it and keep it safe

---

#### Key 4: Anthropic (Claude) API Key (paid — add before you hit 100 restaurants)

1. Go to: **https://console.anthropic.com/**
   *(Create a free account)*
2. Click **Settings → API Keys → Create Key**
3. The key starts with `sk-ant-...`
4. Go to **Billing** and add a card — put £10 credit on it
   *(Each weekly report costs about £0.05 — very cheap)*
5. Copy the key and keep it safe

---

### STEP 2 — Add your keys to Railway

This is where all three keys get saved so the bot can use them.

1. Go to **https://railway.app** and log in
2. Click on your **restaurant-iq-bot** service
3. Click the **"Variables"** tab at the top
4. For each row in the table below:
   - Click **"+ New Variable"**
   - Type the **Variable Name** exactly as shown (left column)
   - Paste your key in the **Value** field (right column)
   - Press Enter or click the tick to save

| Variable Name | What to paste here | Add when? |
|--------------|-------------------|-----------|
| `TELEGRAM_BOT_TOKEN` | Your token from Key 1 | NOW |
| `GEMINI_API_KEY` | Your key from Key 2 | NOW |
| `GROQ_API_KEY` | Your key from Key 3 | Before 50 restaurants |
| `ANTHROPIC_API_KEY` | Your key from Key 4 | Before 100 restaurants |

5. Railway will redeploy automatically. Wait 30 seconds.

---

### STEP 3 — Set up your Telegram group

Do this once for each restaurant you want to manage.

1. **Create a Telegram group** for the restaurant team
   *(or use an existing one)*
2. **Add your bot to the group** — tap the group name → Add Members → search for your bot's username
3. **Make the bot an admin:**
   - Tap the group name at the top
   - Tap "Edit" (pencil icon)
   - Tap "Administrators"
   - Tap "Add Administrator"
   - Select your bot
   - Save
4. In the group chat, type and send:
   `/register Your Restaurant Name`
   Example: `/register Joe's Bistro`
5. Tell your team to start sending voice notes, photos, and text messages

---

### STEP 4 — That's it. The system does the rest.

Every message sent in the group is automatically captured and analysed:

| What staff send | What the bot does |
|----------------|-------------------|
| Voice note | Transcribes it, extracts category, urgency, revenue figures |
| Photo of an invoice or receipt | Reads supplier name, total amount, all line items |
| Text message | Categorises and summarises it |

At the end of each week, send `/weeklyreport` to get:
- A full intelligence briefing in the Telegram group
- A branded PDF report attached to the same message

---

## Bot Commands

| Command | Who uses it | What it does |
|---------|------------|--------------|
| `/start` | Anyone | Shows the welcome message |
| `/register Your Name` | Owner | Registers this Telegram group as a restaurant |
| `/status` | Owner or manager | Shows this week's entries + which AI tier is active |
| `/weeklyreport` | Owner | Generates and sends the weekly briefing + PDF |

---

## How the Automatic AI Switching Works

Every time the bot analyses something, it does this automatically:

```
1. Count restaurants in the database
2. Is the count 0-49?   → Use Google Gemini (free)
   Is the count 50-99?  → Use Groq / Llama (free)
   Is the count 100+?   → Use Claude / Anthropic (paid, best)
3. Check that the required API key is saved in Railway
4. If the key is missing, fall back to the previous tier
   and log a warning (you'll see it in Railway Logs)
5. Call the AI and return the result
```

**You never need to change any code.** Just make sure the keys are in Railway before you hit each threshold.

---

## File Structure

```
restaurant-iq-bot/
├── bot.py              Telegram bot — commands and message handlers
├── model_router.py     AI auto-switching brain — all three providers live here
├── analyzer.py         Thin wrapper that calls model_router
├── transcriber.py      Voice → text (Whisper, runs on the server)
├── database.py         SQLite database layer
├── report_generator.py PDF generation (ReportLab)
├── config.py           Loads environment variables from Railway
├── requirements.txt    Python package dependencies
└── .env.example        Template showing all available variables
```

---

## Security — Keeping Your Keys Safe

**Never share your API keys with anyone.**
Never paste them into code files, emails, or chats.
Always store them only in Railway Variables.

If you accidentally shared a key, regenerate it immediately:
- **Gemini key**: Go to https://aistudio.google.com/app/apikey → delete the old key → create a new one → update Railway
- **Groq key**: Go to https://console.groq.com/keys → delete → create new → update Railway
- **Telegram token**: Message @BotFather → `/revoke` → it gives you a new token → update Railway
- **Anthropic key**: Go to https://console.anthropic.com/settings/keys → delete → create new → update Railway

---

## Troubleshooting

**The bot doesn't respond to messages in the group**
- Make sure you made the bot an **admin** in the group
- Make sure you sent `/register` first
- Check Railway Logs for any error messages

**"GEMINI_API_KEY is not set" error on startup**
- Go to Railway → your service → Variables → add `GEMINI_API_KEY`
- Get a free key at https://aistudio.google.com/app/apikey

**The bot is still using Gemini even though I have 50+ restaurants**
- Add `GROQ_API_KEY` in Railway Variables (see Step 1, Key 3)
- Without that key, the system falls back to Gemini automatically

**Voice notes are not being transcribed**
- The very first voice note downloads the Whisper model (~150 MB) — just wait a minute
- If accuracy is low, add `WHISPER_MODEL_SIZE` = `small` in Railway Variables

**The weekly report takes a long time**
- With Gemini/Groq: 20–60 seconds
- With Claude: 10–30 seconds
- This is normal — the AI is reading all your week's data

**I want to upgrade to the next tier early (before hitting the restaurant count)**
- Just add the API key in Railway — the system will use it once you hit the threshold
- To force an immediate switch, contact your developer (one small config change needed)
