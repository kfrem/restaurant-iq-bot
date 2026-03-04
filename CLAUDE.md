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

### The Web Dashboard (Charts & Graphs)
The bot also runs a **web dashboard** — a beautiful interactive page you can open in any web browser to see all your data as charts.

**How to open it (while the bot is running):**
1. Make sure the bot is running (see above)
2. Open your web browser (Chrome, Edge, Firefox — any of them)
3. In the address bar at the top, type exactly:
   ```
   http://localhost:8080/
   ```
   and press **Enter**
4. You will see the dashboard with all your charts

**If you are on a different computer or phone on the same WiFi:**
- Replace `localhost` with the IP address of the computer running the bot
- Example: `http://192.168.1.5:8080/`
- To find your IP: press Windows key, type `cmd`, press Enter, type `ipconfig`, press Enter — look for "IPv4 Address"

**What the dashboard shows:**
| Chart / Panel | What it tells you |
|---|---|
| 6 KPI cards at the top | Revenue, covers, average spend, food cost %, GP%, labour % — all colour-coded green/red vs your benchmark |
| Revenue & Food Cost chart | Line chart of the last 8 weeks — see trends at a glance |
| Overhead donut chart | How your costs are split by category. Hover over a segment to see the breakdown |
| Food Cost % chart | Your food cost over time vs your industry benchmark |
| Monthly Overhead bar | Six months of overhead spend as a bar chart |
| Menu Profitability | Every dish with its food cost, selling price, and GP% — green = star dish, red = losing money |
| No-Show Tracker | How many bookings didn't show up and how much revenue that cost you |
| Entry Search | Type "salmon" and see every entry mentioning salmon — with dates and £ amounts |

**Change the date range:**
- Use the **7D / 30D / 90D / 1Y** buttons at the top right to switch between time periods
- Or use the date picker boxes to pick any start and end date
- All charts update instantly when you change the date

**To protect the dashboard with a password:**
1. Open your `.env` file in Notepad
2. Add a new line: `DASHBOARD_TOKEN=YourPasswordHere`
3. Save the file and restart the bot
4. Now the dashboard URL will be: `http://localhost:8080/?token=YourPasswordHere`

**What to add in `.env` for the dashboard:**
| Setting | What it is | Example |
|---|---|---|
| `DASHBOARD_TOKEN` | Password for the web dashboard (optional) | `DASHBOARD_TOKEN=MyPassword123` |
| `WEBHOOK_PORT` | Which port the server runs on (default: 8080) | `WEBHOOK_PORT=8080` |

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
| `/overhead` | Log and view all operating expenses (rent, rates, insurance, packaging, etc.) |
| `/energy` | Track electricity & gas bills + get energy-saving tips |
| `/cashflow` | 30-day cash flow forecast — now includes overheads |

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
