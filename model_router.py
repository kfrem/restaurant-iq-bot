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

def _text_prompt(text: str, restaurant_name: str) -> str:
    return f"""You are a restaurant data analyst for "{restaurant_name}".
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
  "urgency": "low|medium|high"
}}"""


def _image_prompt(restaurant_name: str) -> str:
    return f"""You are an invoice analyst for "{restaurant_name}".
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
  "summary": "one line summary"
}}

For due_date: if payment terms are shown (e.g. "Net 30", "30 days"), calculate the due date from the invoice date and return as YYYY-MM-DD.
If no terms shown, return null for both due_date and payment_terms."""


def _report_prompt(entries_summary: list, restaurant_name: str,
                   financials: dict | None = None) -> str:
    fin_block = ""
    if financials and financials.get("revenue_total", 0) > 0:
        fin_block = f"""
Pre-calculated financial totals for this period:
  Revenue captured: £{financials['revenue_total']:,.2f}
  Invoiced costs captured: £{financials['cost_total']:,.2f}
  Gross profit (revenue minus invoiced costs): £{financials['gross_profit']:,.2f}
  Gross margin: {financials['gross_margin_pct']}%
  Note: costs figure includes only invoices photographed this week. Labour and other costs not captured here.
"""

    return f"""You are Restaurant-IQ, an AI intelligence service for "{restaurant_name}", a London food business.
You combine chartered accountancy discipline and food economics expertise with AI analysis.

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
Include an estimated £ impact where data supports it.

## POSITIVE HIGHLIGHTS
What went well this week — customer feedback, staff performance, menu wins.

---
Guidelines:
- Language: clear, direct, professional — these are busy owners
- Use £ for all currency
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

def analyze_text(text: str, restaurant_name: str) -> dict:
    tier = _select_tier()
    prompt = _text_prompt(text, restaurant_name)
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


def analyze_image(image_path: str, restaurant_name: str) -> dict:
    tier = _select_tier()
    prompt = _image_prompt(restaurant_name)
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
                    financials: dict | None = None) -> str:
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

    prompt = _report_prompt(summary, restaurant_name, financials)

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


def generate_recall_summary(entries_data: list, query_text: str,
                             restaurant_name: str) -> str:
    """
    Summarise a set of entries for a date-based recall query.
    Used by the /recall command.
    """
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

    prompt = f"""You are Restaurant-IQ, the operational memory for "{restaurant_name}".

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
