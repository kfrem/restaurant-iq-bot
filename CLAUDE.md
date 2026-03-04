# CLAUDE.md — Assistant Instructions for This Project

## About the User
- **Skill level: Complete beginner / novice**
- Uses **Windows** (Notepad, not a Linux text editor)
- Is building the Restaurant-IQ Telegram bot as a non-developer
- Gets confused when instructions skip steps or assume prior knowledge

## How to Give Instructions
Always be specific about:
1. **WHERE** to do something (which app, which window, which folder)
2. **HOW** to open it (click what, type what, press what)
3. **WHAT** it looks like when it worked

Never say things like "run the command" without saying WHERE to run it.

### Instruction Template to Follow
Instead of:
> "Run `python bot.py`"

Always say:
> 1. Press the **Windows key**, type **cmd**, press **Enter** — this opens the black Command Prompt window
> 2. Type exactly: `cd C:\path\to\restaurant-iq-bot` and press **Enter**
> 3. Type: `python bot.py` and press **Enter**
> 4. You will see text scrolling — that means the bot is running. Leave this window open.

---

## Project: Restaurant-IQ Bot

A Telegram bot that helps restaurant owners track finances, costs, and operations via voice notes, photos, and text.

### Key Files
| File | Purpose |
|------|---------|
| `bot.py` | Main bot — this is what you run to start the bot |
| `config.py` | Reads settings from `.env` |
| `.env` | Your secret keys and settings (never share this file) |
| `database.py` | Stores restaurant data locally |
| `requirements.txt` | List of Python packages needed |

### The .env File (Settings File)
Located at: `C:\[wherever you installed it]\restaurant-iq-bot\.env`
Open with: **Notepad**

Key settings to fill in:
| Setting | What it is | Where to get it |
|---------|-----------|-----------------|
| `TELEGRAM_BOT_TOKEN` | Password for your bot | @BotFather → /mybots → API Token |
| `ADMIN_TELEGRAM_ID` | Your personal Telegram number | Send `/myid` to your bot |
| `GROQ_API_KEY` | Free AI key (for text analysis) | console.groq.com/keys |
| `GOOGLE_API_KEY` | Free AI key (for images/vision) | aistudio.google.com/apikey |

### How to Start the Bot (Windows)
1. Press **Windows key**
2. Type **cmd** and press **Enter** — a black window opens
3. Type this and press **Enter** (adjust path to match where your files are):
   ```
   cd C:\Users\YourName\restaurant-iq-bot
   ```
4. Type this and press **Enter**:
   ```
   python bot.py
   ```
5. Leave that black window open — closing it stops the bot

### How to Get Your Telegram User ID
1. Make sure the bot is running (step above)
2. Open Telegram
3. Go to your **Restaurant-IQ Bot** chat
4. Type `/myid` and press Send
5. The bot will reply with a number — that is your ID
6. Copy it into `.env` next to `ADMIN_TELEGRAM_ID=`

### How to See Everything You Need to Configure
- Send `/setup` to your bot — it shows a ✅/❌ checklist of every setting

### Installed Bot Commands
| Command | What it does |
|---------|-------------|
| `/start` | Welcome message |
| `/register RestaurantName` | Register your restaurant |
| `/myid` | Shows your Telegram User ID |
| `/setup` | Full configuration checklist |
| `/status` | Check your restaurant status |
| `/metrics` | KPI dashboard |
| `/today` | Today's summary |
| `/weeklyreport` | Weekly financial report |

---

## User's Telegram Bot Info
- Bot name: **Restaurant-IQ Bot**
- Bot username: **@RestaurantIQ_bot**
- Token: stored in `.env` as `TELEGRAM_BOT_TOKEN`

## Reminders for Claude
- Always say WHICH window or app to use
- Always say WHERE a file is located
- Avoid technical jargon — use plain English
- When showing terminal commands, always first explain how to open the terminal
- Confirm what "success looks like" after each step
