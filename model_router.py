"""
model_router.py — Automatic AI provider switching based on restaurant count.

HOW IT WORKS
============
Every time the bot needs AI (text analysis, photo reading, weekly report),
this module checks how many restaurants are registered and picks the right
AI provider automatically. You never need to change any code — just make
sure all three API keys are saved in Railway.

UPGRADE PATH
============
  0  – 49  restaurants  →  Google Gemini   (free, 1,500 req/day)
  50 – 99  restaurants  →  Groq            (free, fast inference)
  100+     restaurants  →  Claude / Anthropic (professional, best quality)

If a tier's API key is missing, the system falls back to the previous tier
and logs a warning so you know which key to add.
"""

import json
import base64
import logging
import time

logger = logging.getLogger(__name__)


def _with_retry(fn, *args, retries=3, wait=25):
    """
    Call fn(*args). If a 429 rate-limit error is returned by the API,
    wait `wait` seconds and retry up to `retries` times before giving up.
    All other exceptions are raised immediately.
    """
    for attempt in range(retries):
        try:
            return fn(*args)
        except Exception as e:
            err = str(e)
            if "429" in err or "quota" in err.lower() or "rate_limit" in err.lower():
                if attempt < retries - 1:
                    logger.warning(
                        "Rate limit hit (attempt %d/%d). Waiting %ds...",
                        attempt + 1, retries, wait,
                    )
                    time.sleep(wait)
                    continue
            raise
    raise RuntimeError("Max retries exceeded after rate limit")

# ============================================================
# TIER DEFINITIONS
# Change the thresholds here if you want to upgrade earlier.
# (max_count, provider, label, text_model, vision_model)
# ============================================================
_TIERS = [
    (49,   "gemini", "Starter — Google Gemini (Free)",       "gemini-2.0-flash",            "gemini-2.0-flash"),
    (99,   "groq",   "Growth — Groq / Llama (Free)",         "llama-3.3-70b-versatile",     "llama-3.2-11b-vision-preview"),
    (None, "claude", "Scale — Claude / Anthropic (Pro)",     "claude-haiku-4-5-20251001",   "claude-haiku-4-5-20251001"),
]


# ============================================================
# Shared prompt templates (same JSON output regardless of provider)
# ============================================================

def _text_prompt(text: str, restaurant_name: str,
                 business_type: str = "restaurant",
                 currency_symbol: str = "£") -> str:
    cs = currency_symbol
    return f"""You are a {business_type} data analyst for "{restaurant_name}".
A staff member has sent this update. Extract key information.

MESSAGE: "{text}"

Return ONLY valid JSON — no markdown, no explanation, just the JSON object:
{{
  "category": "revenue|cost|waste|staff|issue|supplier|general",
  "summary": "one concise sentence",
  "revenue": null,
  "covers": null,
  "waste_items": [],
  "items_86d": [],
  "staff_issues": [],
  "supplier_mentions": [],
  "complaints": [],
  "positive_notes": [],
  "action_needed": false,
  "urgency": "low|medium|high",
  "tips_detected": false,
  "tip_amount": null,
  "tip_type": null,
  "allergen_risk": false,
  "allergen_detail": null
}}

Tips detection: set tips_detected=true if the message mentions tips, gratuities, service charge, or tronc.
  Extract tip_amount (number, {cs}) and tip_type ("card", "cash", or "both") if mentioned.
Allergen risk: set allergen_risk=true if a supplier change, ingredient substitution, or new product is mentioned
  that could affect product/food allergen declarations. Describe the concern in allergen_detail.
Labour cost: set category="labour" if the message mentions wages, payroll, staff costs, agency fees, or labour costs.
  Extract the {cs} amount into the revenue field (we reuse it for labour amounts on the labour category)."""


def _image_prompt(restaurant_name: str,
                  business_type: str = "restaurant",
                  currency_symbol: str = "£") -> str:
    cs = currency_symbol
    return f"""You are an invoice analyst for "{restaurant_name}" ({business_type}).
Read this invoice or receipt image carefully and extract all data.

Return ONLY valid JSON — no markdown, no explanation:
{{
  "category": "cost",
  "document_type": "invoice|receipt|delivery_note|other",
  "supplier_name": "",
  "date": "",
  "due_date": null,
  "payment_terms": null,
  "total_amount": null,
  "vat": null,
  "items": [
    {{"name": "", "quantity": null, "unit": "", "unit_price": null, "total": null}}
  ],
  "summary": "one line summary",
  "allergen_risk": false,
  "allergen_detail": null,
  "tips_detected": false,
  "tip_amount": null,
  "tip_type": null
}}

For due_date: if payment terms are shown (e.g. "Net 30", "30 days"), calculate the due date from the invoice date and return as YYYY-MM-DD.
If no terms shown, return null for both due_date and payment_terms.
Allergen risk: set allergen_risk=true if this invoice shows a new supplier, a substituted product, or a product
  whose ingredients could affect allergen declarations (e.g. different butter brand, new flour supplier).
  Describe the concern in allergen_detail.
Tips: set tips_detected=true only if the document is a tips/tronc distribution sheet."""


def _report_prompt(entries_summary: list, restaurant_name: str,
                   financials: dict | None = None,
                   currency_symbol: str = "£") -> str:
    cs = currency_symbol
    fin_block = ""
    if financials and financials.get("revenue_total", 0) > 0:
        labour_line = ""
        if financials.get("labour_total", 0) > 0:
            labour_line = f"  Labour costs captured: {cs}{financials['labour_total']:,.2f}\n"
        fin_block = f"""
Pre-calculated financial totals for this period:
  Revenue captured: {cs}{financials['revenue_total']:,.2f}
  Invoiced costs captured: {cs}{financials['cost_total']:,.2f}
{labour_line}  Net profit (revenue minus food costs and labour): {cs}{financials['gross_profit']:,.2f}
  Food GP margin (before labour): {financials.get('food_margin_pct', 0)}%
  Net margin (after labour): {financials.get('net_margin_pct', 0)}%
  Note: costs = invoices photographed this week. Labour = entries via /labour command.
"""

    return f"""You are TradeFlow, an AI intelligence service for "{restaurant_name}".
You combine chartered accountancy discipline and business economics expertise with AI analysis.
Use {cs} for all monetary values in your response.

Here is all data captured this week from staff voice notes, photos and messages:

{json.dumps(entries_summary, indent=2)}
{fin_block}
Write a WEEKLY INTELLIGENCE BRIEFING with these sections:

## WEEK AT A GLANCE
- Total revenue, total covers, gross profit (if data available), key highlights

## FINANCIAL SUMMARY
- Revenue vs invoiced costs breakdown
- Gross margin analysis
- Cost items captured this week (supplier, amount)
- Flag any cost items that look unusually high or that represent price increases

## COST ALERTS
- Supplier price changes, invoice anomalies, food cost concerns, energy bills

## OPERATIONAL INSIGHTS
- Waste and 86'd item patterns, staff issues, complaint themes, supplier performance

## TOP ACTIONS FOR NEXT WEEK
Numbered list of 3-5 specific, actionable priorities ranked by financial impact.
Include an estimated {cs} impact where data supports it.

## POSITIVE HIGHLIGHTS
What went well this week — customer feedback, staff performance, menu wins.

---
Guidelines:
- Language: clear, direct, professional — these are busy owners
- Use {cs} for all currency
- Where data is thin, say so and suggest what to capture next week
- Be specific with numbers when data supports it
- Keep each section concise — no filler sentences"""


# ============================================================
# JSON extraction helper
# ============================================================

def _extract_json(text: str) -> dict:
    """Pull the first valid JSON object out of a model response."""
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        return json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return {}


# ============================================================
# TIER SELECTION
# ============================================================

def _select_tier() -> dict:
    """
    Check restaurant count, find the right tier, validate the API key is set,
    and fall back to the previous tier if a key is missing.
    """
    from database import get_restaurant_count
    from config import GEMINI_API_KEY, GROQ_API_KEY, ANTHROPIC_API_KEY

    count = get_restaurant_count()

    _key_map = {
        "gemini": GEMINI_API_KEY,
        "groq":   GROQ_API_KEY,
        "claude": ANTHROPIC_API_KEY,
    }

    # Find which tier the count falls into, then walk backwards if key is missing
    target_index = 0
    for i, (max_count, provider, *_) in enumerate(_TIERS):
        if max_count is None or count <= max_count:
            target_index = i
            break
        target_index = i  # keep updating so we land on the last tier

    # Walk backwards until we find a tier with a valid key
    for i in range(target_index, -1, -1):
        max_count, provider, label, text_model, vision_model = _TIERS[i]
        key = _key_map.get(provider)
        if key and key not in ("your_gemini_api_key_here", "your_groq_api_key_here", "your_anthropic_api_key_here"):
            # Calculate next tier info
            next_tier = None
            next_at = None
            if i < len(_TIERS) - 1:
                next_max, next_provider, next_label, *_ = _TIERS[i + 1]
                # The "next tier starts at" is previous tier max + 1
                prev_max = _TIERS[i][0]
                next_at = (prev_max + 1) if prev_max is not None else None
                next_tier = next_label

            if i < target_index:
                logger.warning(
                    "API key for '%s' tier is not set. "
                    "Falling back to '%s'. "
                    "Add the key in Railway Variables to unlock the next tier.",
                    _TIERS[target_index][1], provider
                )

            return {
                "provider":    provider,
                "label":       label,
                "text_model":  text_model,
                "vision_model": vision_model,
                "count":       count,
                "next_tier":   next_tier,
                "next_at":     next_at,
                "tier_index":  i,
            }

    # Should never reach here, but return gemini as ultimate fallback
    return {
        "provider":    "gemini",
        "label":       _TIERS[0][2],
        "text_model":  _TIERS[0][3],
        "vision_model": _TIERS[0][4],
        "count":       0,
        "next_tier":   _TIERS[1][2],
        "next_at":     50,
        "tier_index":  0,
    }


def get_tier_status() -> dict:
    """Public helper for displaying tier info in /status command."""
    return _select_tier()


# ============================================================
# PROVIDER IMPLEMENTATIONS — Google Gemini
# ============================================================

def _gemini_text(prompt: str) -> str:
    import google.generativeai as genai
    from config import GEMINI_API_KEY, GEMINI_MODEL
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL)

    def _call():
        return model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(temperature=0.1, max_output_tokens=400),
        ).text

    return _with_retry(_call)


def _gemini_vision(prompt: str, image_path: str) -> str:
    import google.generativeai as genai
    from PIL import Image
    from config import GEMINI_API_KEY, GEMINI_MODEL
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL)
    image = Image.open(image_path)

    def _call():
        return model.generate_content(
            [prompt, image],
            generation_config=genai.types.GenerationConfig(temperature=0.1, max_output_tokens=600),
        ).text

    return _with_retry(_call)


def _gemini_report(prompt: str) -> str:
    import google.generativeai as genai
    from config import GEMINI_API_KEY, GEMINI_MODEL
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL)

    def _call():
        return model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(temperature=0.3, max_output_tokens=2500),
        ).text

    return _with_retry(_call)


# ============================================================
# PROVIDER IMPLEMENTATIONS — Groq (free tier, fast)
# ============================================================

def _groq_text(prompt: str, model: str) -> str:
    from groq import Groq
    from config import GROQ_API_KEY
    client = Groq(api_key=GROQ_API_KEY)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=400,
    )
    return response.choices[0].message.content


def _groq_vision(prompt: str, image_path: str, model: str) -> str:
    from groq import Groq
    from config import GROQ_API_KEY
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    client = Groq(api_key=GROQ_API_KEY)
    response = client.chat.completions.create(
        model=model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ],
        }],
        max_tokens=600,
    )
    return response.choices[0].message.content


def _groq_report(prompt: str, model: str) -> str:
    from groq import Groq
    from config import GROQ_API_KEY
    client = Groq(api_key=GROQ_API_KEY)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=2500,
    )
    return response.choices[0].message.content


# ============================================================
# PROVIDER IMPLEMENTATIONS — Claude / Anthropic (professional)
# ============================================================

def _claude_text(prompt: str, model: str) -> str:
    import anthropic
    from config import ANTHROPIC_API_KEY
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=model,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def _claude_vision(prompt: str, image_path: str, model: str) -> str:
    import anthropic
    from config import ANTHROPIC_API_KEY
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=model,
        max_tokens=600,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
                },
                {"type": "text", "text": prompt},
            ],
        }],
    )
    return response.content[0].text


def _claude_report(prompt: str, model: str) -> str:
    import anthropic
    from config import ANTHROPIC_API_KEY
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=model,
        max_tokens=2500,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


# ============================================================
# DISPATCH TABLE — maps provider name to functions
# ============================================================

_TEXT_FN   = {"gemini": _gemini_text,   "groq": _groq_text,   "claude": _claude_text}
_VISION_FN = {"gemini": _gemini_vision, "groq": _groq_vision, "claude": _claude_vision}
_REPORT_FN = {"gemini": _gemini_report, "groq": _groq_report, "claude": _claude_report}


# ============================================================
# PUBLIC INTERFACE — called by analyzer.py
# ============================================================

def analyze_text(text: str, restaurant_name: str,
                 currency_symbol: str = "£", business_type: str = "restaurant") -> dict:
    tier = _select_tier()
    prompt = _text_prompt(text, restaurant_name, business_type, currency_symbol)
    provider = tier["provider"]
    try:
        if provider == "groq":
            raw = _TEXT_FN[provider](prompt, tier["text_model"])
        elif provider == "claude":
            raw = _TEXT_FN[provider](prompt, tier["text_model"])
        else:
            raw = _TEXT_FN[provider](prompt)

        result = _extract_json(raw)
        if result:
            return result
        raise ValueError("Empty or invalid JSON from model")
    except Exception as e:
        logger.error("analyze_text error (%s): %s", provider, e)
        return {
            "category": "general",
            "summary": text[:120],
            "action_needed": False,
            "urgency": "low",
        }


def analyze_image(image_path: str, restaurant_name: str,
                  currency_symbol: str = "£", business_type: str = "restaurant") -> dict:
    tier = _select_tier()
    prompt = _image_prompt(restaurant_name, business_type, currency_symbol)
    provider = tier["provider"]
    try:
        if provider in ("groq", "claude"):
            raw = _VISION_FN[provider](prompt, image_path, tier["vision_model"])
        else:
            raw = _VISION_FN[provider](prompt, image_path)

        result = _extract_json(raw)
        if result:
            return result
        raise ValueError("Empty or invalid JSON from model")
    except Exception as e:
        logger.error("analyze_image error (%s): %s", provider, e)
        return {
            "category": "cost",
            "document_type": "other",
            "summary": "Invoice captured — could not fully parse. Review manually.",
        }


def generate_report(entries_data: list, restaurant_name: str,
                    financials: dict | None = None,
                    currency_symbol: str = "£") -> str:
    tier = _select_tier()
    provider = tier["provider"]

    # Build the entries summary (same logic regardless of provider)
    summary = []
    for e in entries_data:
        item = {
            "date": e.get("date"),
            "time": e.get("time"),
            "type": e.get("type"),
            "text": e.get("raw_text", "")[:300],
        }
        if e.get("analysis"):
            a = e["analysis"]
            for key in ("category", "summary", "revenue", "covers", "urgency"):
                if a.get(key):
                    item[key] = a[key]
            for key in ("waste_items", "complaints", "items_86d", "staff_issues", "supplier_mentions", "positive_notes"):
                if a.get(key):
                    item[key] = a[key]
            if a.get("action_needed"):
                item["action_needed"] = True
        summary.append(item)

    prompt = _report_prompt(summary, restaurant_name, financials, currency_symbol)

    try:
        if provider == "groq":
            return _REPORT_FN[provider](prompt, tier["text_model"]).strip()
        elif provider == "claude":
            return _REPORT_FN[provider](prompt, tier["text_model"]).strip()
        else:
            return _REPORT_FN[provider](prompt).strip()
    except Exception as e:
        logger.error("generate_report error (%s): %s", provider, e)
        err = str(e)
        if "429" in err or "quota" in err.lower() or "rate_limit" in err.lower():
            user_msg = (
                "The AI is temporarily busy (rate limit reached). "
                "Please wait 30 seconds and try /report again."
            )
        else:
            user_msg = (
                "Could not generate the AI report. "
                "Check your API key is valid, then try /report again."
            )
        return (
            f"## Weekly Briefing — {restaurant_name}\n\n"
            f"{user_msg}\n\n"
            f"Entries captured this week: {len(entries_data)}.\n"
            f"Current AI tier: {tier['label']}."
        )


def analyze_correction(original_text: str, correction: str, restaurant_name: str,
                       currency_symbol: str = "£", business_type: str = "restaurant") -> dict:
    """
    Re-analyse an entry applying a specific correction.
    Uses a dedicated prompt so the AI applies the fix rather than
    treating the correction text as new data to extract.
    """
    tier = _select_tier()
    provider = tier["provider"]

    prompt = f"""You are a {business_type} data analyst for "{restaurant_name}".

A staff member logged this entry:
ORIGINAL: "{original_text}"

They want to correct one specific detail:
CORRECTION: "{correction}"

Apply ONLY the stated correction. Fix just that detail — do not re-interpret the rest of the original entry.
The summary must reflect the corrected information in plain English. Do NOT include the words "correction" or "CORRECTION" in the summary.

Return ONLY valid JSON — no markdown, no explanation:
{{
  "category": "revenue|cost|waste|staff|issue|supplier|general",
  "summary": "corrected one-sentence summary (no mention of the word correction)",
  "revenue": null,
  "covers": null,
  "waste_items": [],
  "items_86d": [],
  "staff_issues": [],
  "supplier_mentions": [],
  "complaints": [],
  "positive_notes": [],
  "action_needed": false,
  "urgency": "low|medium|high",
  "tips_detected": false,
  "tip_amount": null,
  "tip_type": null,
  "allergen_risk": false,
  "allergen_detail": null
}}"""

    try:
        if provider == "groq":
            raw = _TEXT_FN[provider](prompt, tier["text_model"])
        elif provider == "claude":
            raw = _TEXT_FN[provider](prompt, tier["text_model"])
        else:
            raw = _TEXT_FN[provider](prompt)

        result = _extract_json(raw)
        if result:
            return result
        raise ValueError("Empty or invalid JSON from model")
    except Exception as e:
        logger.error("analyze_correction error (%s): %s", provider, e)
        return {
            "category": "general",
            "summary": f"{original_text[:100]} [correction applied: {correction[:60]}]",
            "action_needed": False,
            "urgency": "low",
        }


def analyze_history_import(description: str, start_date: str, end_date: str,
                           restaurant_name: str,
                           currency_symbol: str = "£", business_type: str = "restaurant") -> list:
    """
    Parse a plain-language description of any historical period and return
    a list of daily entry dicts ready to be saved to the database.
    Scales the number of entries based on the length of the period:
      1 day       → 1-3 entries
      2-7 days    → 3-7 entries
      8-14 days   → 5-10 entries (fortnight)
      15-31 days  → 7-14 entries (month)
      32-92 days  → 10-20 entries (quarter)
      93+ days    → 15-30 entries (multi-month)
    Used by /import for backfilling historical data of any length.
    """
    from datetime import date as _date
    try:
        d1 = _date.fromisoformat(start_date)
        d2 = _date.fromisoformat(end_date)
        num_days = max(1, (d2 - d1).days + 1)
    except ValueError:
        num_days = 7

    if num_days == 1:
        min_e, max_e = 1, 3
    elif num_days <= 7:
        min_e, max_e = 3, 7
    elif num_days <= 14:
        min_e, max_e = 5, 10
    elif num_days <= 31:
        min_e, max_e = 7, 14
    elif num_days <= 92:
        min_e, max_e = 10, 20
    else:
        min_e, max_e = 15, 30

    cs = currency_symbol
    tier = _select_tier()
    provider = tier["provider"]

    prompt = f"""You are a {business_type} data analyst for "{restaurant_name}".

A {business_type} owner is importing historical data covering {num_days} day(s): {start_date} to {end_date}.
They have described this period as follows:

"{description}"

Extract the key facts and create between {min_e} and {max_e} representative daily log entries.
Spread entries proportionally across the period — do not cluster them all on one date.
Each entry should represent one real operational event (a shift report, a supplier delivery,
a staff issue, a cost, a revenue figure, an equipment problem, etc).

Return ONLY valid JSON — a JSON array of entry objects, no markdown, no explanation:
[
  {{
    "date": "YYYY-MM-DD",
    "time": "HH:MM:SS",
    "type": "voice",
    "category": "revenue|cost|waste|staff|issue|supplier|general",
    "raw_text": "plain English log entry for this event as if written by a staff member",
    "summary": "one sentence",
    "revenue": null,
    "covers": null,
    "urgency": "low|medium|high"
  }}
]

Rules:
- All dates must be between {start_date} and {end_date} inclusive
- Spread entries across the whole period, not bunched at the start or end
- If revenue is mentioned across multiple days/weeks, split it proportionally
- If a specific event has a date (e.g. "fridge broke on the 14th"), use that date
- raw_text should sound like a real staff voice note or text message, not a formal report
- For month-long or multi-month imports, include a mix of revenue summaries, cost events,
  staff notes, and supplier entries across different weeks"""

    try:
        if provider == "groq":
            raw = _TEXT_FN[provider](prompt, tier["text_model"])
        elif provider == "claude":
            raw = _TEXT_FN[provider](prompt, tier["text_model"])
        else:
            raw = _TEXT_FN[provider](prompt)

        try:
            start = raw.index("[")
            end = raw.rindex("]") + 1
            entries = json.loads(raw[start:end])
            if isinstance(entries, list):
                return entries
        except (ValueError, json.JSONDecodeError):
            pass
        raise ValueError("Could not parse entries array from model")
    except Exception as e:
        logger.error("analyze_history_import error (%s): %s", provider, e)
        return []


def answer_help_question(question: str, restaurant_name: str,
                         currency_symbol: str = "£", business_type: str = "restaurant") -> str:
    """
    Answer a business owner's question about how to use the bot.
    Returns a plain-English helpful response.
    """
    cs = currency_symbol
    tier = _select_tier()
    provider = tier["provider"]

    prompt = f"""You are TradeFlow, a Telegram bot assistant for "{restaurant_name}" ({business_type}).
The owner is asking a question about how to use you.

QUESTION: "{question}"

You know everything about the bot's capabilities. Here is a full reference:

DAILY USE: Send voice notes, photos of invoices, or text messages to the group.
  Voice notes are transcribed and analysed automatically.
  Invoice photos are read and added to the payment tracker.

COMMANDS:
  /status        — how many entries captured this week
  /today         — what was logged today
  /history       — browse past weekly reports (/history [date] for specific week)
  /recall [date] — recall any day or week (e.g. /recall yesterday, /recall 5 May, /recall March)
  /weeklyreport  — full AI briefing + PDF for the current week (also auto-sent every Monday 08:00)
  /financials    — revenue, costs, labour and net margin for any period
  /labour {cs}X [description] — record wages or labour costs
  /outstanding   — unpaid invoices
  /markpaid [id] — mark an invoice as paid
  /teamstats     — who's contributing entries and how much (staff engagement)
  /eightysix     — which items run out most frequently
  /export        — download entries as CSV for Excel or accountants
  /correct [fix] — fix a detail in your last entry (e.g. /correct the amount was {cs}450 not {cs}540)
  /deletelast    — delete your last entry and re-send
  /import [dates]: [description] — import any historical period (day/fortnight/month/quarter)
  /rename [name] — rename your business
  /setindustry [type] — set your business type (e.g. restaurant, cafe, retail, salon)
  /currency [code] — set your currency (e.g. GBP, USD, EUR, NGN)
  /deletedata 90 — delete entries older than 90 days (GDPR compliance)
  /cleardata     — delete all entries (keeps registration)
  /tips          — tip events log
  /tipsreport    — generate formal tip allocation record
  /allergens     — allergen/product traceability log
  /inspection    — compliance readiness report
  /ask [question]— ask me anything about the bot
  /support [msg] — report a problem to the app support team

TIPS FOR BEST RESULTS:
  - End-of-shift voice notes are the most valuable thing your team can do
  - Photograph invoices the day they arrive for accurate due date tracking
  - The /correct command only fixes one detail — state exactly what changed
  - Use /import to backfill any historical period (day, fortnight, month, quarter) before you joined

Answer the question concisely and helpfully. Be specific — reference actual commands.
If the question is about a problem, explain what likely went wrong and how to fix it.
Use plain English, no jargon. Keep your answer under 200 words."""

    try:
        if provider == "groq":
            return _TEXT_FN[provider](prompt, tier["text_model"]).strip()
        elif provider == "claude":
            return _TEXT_FN[provider](prompt, tier["text_model"]).strip()
        else:
            return _TEXT_FN[provider](prompt).strip()
    except Exception as e:
        logger.error("answer_help_question error (%s): %s", provider, e)
        return (
            "I couldn't generate a full answer right now. "
            "Try /features for a complete guide, or /support to contact the support team directly."
        )


def generate_tips_report(tips_events: list, summary: dict,
                         restaurant_name: str, period_label: str,
                         currency_symbol: str = "£") -> str:
    """
    Generate a Tips Act compliant monthly allocation record.
    Employment (Allocation of Tips) Act 2023 — in force October 2024.
    """
    tier = _select_tier()
    provider = tier["provider"]

    cs = currency_symbol
    events_block = ""
    if tips_events:
        lines = []
        for t in tips_events:
            lines.append(
                f"  {t.get('event_date')}  {t.get('shift', 'unspecified shift')}  "
                f"{t.get('tip_type', 'unknown').upper()}  "
                f"{cs}{t.get('gross_amount') or 0:.2f}  "
                f"Notes: {t.get('staff_notes', '') or 'none'}"
            )
        events_block = "\n".join(lines)
    else:
        events_block = "  No individual tip events recorded for this period."

    prompt = f"""You are TradeFlow, generating a tips compliance record for "{restaurant_name}".
Use {cs} for all monetary values in your response.

UK LAW CONTEXT (Employment (Allocation of Tips) Act 2023, in force October 2024):
- Employers must pass 100% of customer tips to workers, with no deductions.
- A written tips policy is required.
- Records must be kept for 3 years and provided to any worker who requests them.
- Workers can request their tip allocation records at any time.

PERIOD: {period_label}

RECORDED TIP EVENTS:
{events_block}

PERIOD TOTALS:
  Card tips:    {cs}{summary.get('card', 0):.2f}
  Cash tips:    {cs}{summary.get('cash', 0):.2f}
  Type unknown: {cs}{summary.get('unknown', 0):.2f}
  TOTAL:        {cs}{summary.get('total', 0):.2f}
  Events logged: {summary.get('events', 0)}

Write a formal compliance record with these sections:

## TIPS ALLOCATION RECORD — {restaurant_name.upper()}
## Period: {period_label}

### Summary
Total tips received, split by type, and number of recorded events.

### Allocation Events
List each event from the data above in a clear table format.

### Compliance Statement
A short statement confirming tips policy compliance under the Employment (Allocation of Tips) Act 2023.
Include: tips passed to staff in full, method of allocation, record retention commitment.

### Action Items
Any gaps in records or steps needed to ensure full compliance.

Note: Be specific about the legal requirements. This document may be requested by any staff member.
Use £ for all currency. Plain text format, no filler."""

    try:
        if provider == "groq":
            return _TEXT_FN[provider](prompt, tier["text_model"]).strip()
        elif provider == "claude":
            return _TEXT_FN[provider](prompt, tier["text_model"]).strip()
        else:
            return _TEXT_FN[provider](prompt).strip()
    except Exception as e:
        logger.error("generate_tips_report error (%s): %s", provider, e)
        return (
            f"## TIPS ALLOCATION RECORD — {restaurant_name.upper()}\n"
            f"Period: {period_label}\n\n"
            f"Total tips recorded: {cs}{summary.get('total', 0):.2f} across {summary.get('events', 0)} events.\n"
            f"Card: {cs}{summary.get('card', 0):.2f}  |  Cash: {cs}{summary.get('cash', 0):.2f}\n\n"
            f"Raw events:\n{events_block}\n\n"
            f"Note: AI report generation failed — raw data shown above for manual record-keeping."
        )


def generate_inspection_report(entries_data: list, restaurant_name: str,
                               business_type: str = "restaurant") -> str:
    """
    Generate a compliance/inspection preparation report.
    Groups all compliance-relevant entries: supplier changes, equipment faults,
    temperature incidents, cleaning issues, staff incidents, allergen alerts.
    """
    tier = _select_tier()
    provider = tier["provider"]

    lines = []
    for e in entries_data:
        line = f"[{e.get('date')} {e.get('time', '')}]"
        if e.get("analysis") and e["analysis"].get("summary"):
            line += f" {e['analysis']['summary']}"
        else:
            line += f" {(e.get('raw_text') or '')[:200]}"
        category = (e.get("analysis") or {}).get("category", e.get("category", "general"))
        line += f"  [cat:{category}]"
        lines.append(line)

    entries_block = "\n".join(lines) if lines else "No entries found."

    prompt = f"""You are TradeFlow, preparing a compliance readiness report for "{restaurant_name}" ({business_type}).

These are all operational entries recorded in the last 90 days:

{entries_block}

Write a COMPLIANCE & INSPECTION READINESS REPORT:

## INSPECTION READINESS — {restaurant_name.upper()}
## Generated: today

### Overall Readiness Assessment
A brief verdict: Ready / Needs Attention / Action Required. 1-2 sentences.

### Supplier Traceability Log
List all supplier changes, new suppliers, and delivery issues from the entries.
Regulators ask for evidence of approved supplier lists and traceability records.

### Equipment & Maintenance Log
List all equipment faults, repairs, and safety-related issues with dates.
Include temperature control equipment, pest control, and cleaning records where mentioned.

### Staff & Training Notes
Any staff incidents, training mentions, or compliance observations from entries.

### Product/Food Safety Incidents
Any temperature concerns, cold chain issues, or product safety incidents.

### Allergen & Product Traceability
Any supplier changes or product substitutions that could affect allergen or ingredient declarations.

### Gaps in Documentation
What a regulator would likely flag as missing based on these records.
Be direct — gaps in records cost compliance rating points.

### Pre-Inspection Action List
Numbered list of specific steps to take before the next inspection or audit.

Use plain text, be direct, and be relevant to the {business_type} industry."""

    try:
        if provider == "groq":
            return _TEXT_FN[provider](prompt, tier["text_model"]).strip()
        elif provider == "claude":
            return _TEXT_FN[provider](prompt, tier["text_model"]).strip()
        else:
            return _TEXT_FN[provider](prompt).strip()
    except Exception as e:
        logger.error("generate_inspection_report error (%s): %s", provider, e)
        return (
            f"## INSPECTION READINESS — {restaurant_name.upper()}\n\n"
            f"AI report generation failed. Raw entries for manual review:\n\n"
            f"{entries_block}"
        )


def generate_recall_summary(entries_data: list, query_text: str,
                             restaurant_name: str,
                             currency_symbol: str = "£", business_type: str = "restaurant") -> str:
    """
    Summarise a set of entries for a date-based recall query.
    Used by the /recall command.
    """
    cs = currency_symbol
    tier = _select_tier()
    provider = tier["provider"]

    lines = []
    for e in entries_data:
        line = f"[{e.get('date')} {e.get('time', '')}] ({e.get('type', 'text').upper()})"
        if e.get("analysis") and e["analysis"].get("summary"):
            line += f" {e['analysis']['summary']}"
        elif e.get("raw_text"):
            line += f" {e['raw_text'][:150]}"
        lines.append(line)

    entries_block = "\n".join(lines) if lines else "No entries found for this period."

    prompt = f"""You are TradeFlow, the operational memory for "{restaurant_name}" ({business_type}).
Use {cs} for all monetary values.

The owner has asked: "{query_text}"

Here are all entries recorded for the requested period:

{entries_block}

Write a concise, conversational summary (3-10 bullet points) of what happened.
Group by theme — revenue, costs, staffing, issues, positives.
Be specific with numbers and names where available.
End with any unresolved actions from this period.
Use plain text, no markdown headers."""

    try:
        if provider == "groq":
            return _TEXT_FN[provider](prompt, tier["text_model"]).strip()
        elif provider == "claude":
            return _TEXT_FN[provider](prompt, tier["text_model"]).strip()
        else:
            return _TEXT_FN[provider](prompt).strip()
    except Exception as e:
        logger.error("generate_recall_summary error (%s): %s", provider, e)
        return entries_block  # Fall back to raw list
