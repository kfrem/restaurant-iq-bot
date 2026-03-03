"""
ai_client.py — Unified AI backend for Restaurant-IQ.

Auto-selects the best available backend:
  1. Anthropic Claude API  — if ANTHROPIC_API_KEY is set in .env
     └─ claude-haiku-4-5   for fast text analysis & daily summaries  (~$0.002/restaurant/month)
     └─ claude-sonnet-4-6  for invoice vision & weekly reports       (~$0.05/restaurant/month)
  2. Local Ollama          — fallback for self-hosted deployments
     └─ OLLAMA_TEXT_MODEL  for text analysis (default: gemma3:4b)
     └─ OLLAMA_MODEL       for vision + reports (default: qwen3-vl:30b)

At SaaS scale (100 restaurants):
  Claude total AI cost ≈ $5–7/month vs $200-400/month for a GPU server running Ollama.
  Margin at £149/month starter tier per restaurant: 99.9%.
"""

import base64
import json
from config import (
    ANTHROPIC_API_KEY,
    OLLAMA_MODEL,
    OLLAMA_TEXT_MODEL,
)

# ─── Backend selection ────────────────────────────────────────────────────────
_USE_CLAUDE = bool(ANTHROPIC_API_KEY)

if _USE_CLAUDE:
    import anthropic as _anthropic_lib
    _client = _anthropic_lib.Anthropic(api_key=ANTHROPIC_API_KEY)
    _FAST_MODEL  = "claude-haiku-4-5-20251001"
    _SMART_MODEL = "claude-sonnet-4-6"
else:
    import ollama as _ollama_lib
    _FAST_MODEL  = OLLAMA_TEXT_MODEL
    _SMART_MODEL = OLLAMA_MODEL


def _extract_json(text: str) -> dict:
    """Pull the first valid JSON object out of any model response."""
    try:
        start = text.index("{")
        end   = text.rindex("}") + 1
        return json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return {}


def _chat_fast(prompt: str, max_tokens: int = 600) -> str:
    """Run a prompt on the fast/cheap model. Returns raw text."""
    if _USE_CLAUDE:
        msg = _client.messages.create(
            model=_FAST_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text
    else:
        resp = _ollama_lib.chat(
            model=_FAST_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1, "num_predict": max_tokens},
        )
        return resp.message.content


def _chat_smart(prompt: str, image_b64: str = None, max_tokens: int = 1500) -> str:
    """Run a prompt on the smart model, optionally with an image."""
    if _USE_CLAUDE:
        content = []
        if image_b64:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": image_b64,
                },
            })
        content.append({"type": "text", "text": prompt})
        msg = _client.messages.create(
            model=_SMART_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": content}],
        )
        return msg.content[0].text
    else:
        messages = [{"role": "user", "content": prompt}]
        if image_b64:
            messages[0]["images"] = [image_b64]
        resp = _ollama_lib.chat(
            model=_SMART_MODEL,
            messages=messages,
            options={"temperature": 0.3, "num_predict": max_tokens},
        )
        return resp.message.content


def is_healthy() -> bool:
    """Return True if the AI backend is reachable."""
    try:
        if _USE_CLAUDE:
            # Cheapest possible ping — 1 token in, 1 token out
            _client.messages.create(
                model=_FAST_MODEL,
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
        else:
            _ollama_lib.list()
        return True
    except Exception:
        return False


def backend_name() -> str:
    return f"Claude API ({_FAST_MODEL} / {_SMART_MODEL})" if _USE_CLAUDE else f"Ollama ({_FAST_MODEL} / {_SMART_MODEL})"


# ─── Analysis functions ───────────────────────────────────────────────────────

def analyze_text_entry(text: str, restaurant_name: str = "") -> dict:
    """
    Extract structured data from a staff text or voice entry.
    Uses the fast model — typically runs in under 3 seconds with Claude Haiku.
    """
    prompt = f"""You are a data analyst for "{restaurant_name}", a UK restaurant.
A staff member sent this update. Extract key operational and financial data.

MESSAGE: "{text}"

Return ONLY valid JSON with no markdown fences, no explanation:
{{
  "category": "revenue|cost|waste|staff|issue|supplier|general",
  "summary": "one concise sentence",
  "revenue": null,
  "covers": null,
  "average_spend": null,
  "waste_items": [],
  "waste_cost": null,
  "items_86d": [],
  "staff_issues": [],
  "supplier_mentions": [],
  "complaints": [],
  "positive_notes": [],
  "action_needed": false,
  "urgency": "low|medium|high"
}}"""

    try:
        result = _extract_json(_chat_fast(prompt))
        if result:
            return result
        raise ValueError("Empty JSON")
    except Exception as e:
        print(f"[ai_client] text analysis error: {e}")
        return {
            "category": "general",
            "summary": text[:120],
            "action_needed": False,
            "urgency": "low",
        }


def analyze_invoice_photo(image_path: str, restaurant_name: str = "") -> dict:
    """
    Read an invoice/receipt using the smart vision model.
    Returns structured invoice data with line-item prices.
    """
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    prompt = f"""You are an invoice analyst for "{restaurant_name}", a UK restaurant.
Read this invoice or receipt image carefully and extract all financial data.

Return ONLY valid JSON — no markdown, no explanation:
{{
  "category": "cost",
  "document_type": "invoice|receipt|delivery_note|other",
  "supplier_name": "",
  "date": "",
  "total_amount": null,
  "vat": null,
  "currency": "GBP",
  "items": [
    {{"name": "", "quantity": null, "unit": "", "unit_price": null, "total": null}}
  ],
  "summary": "one line summary"
}}"""

    try:
        result = _extract_json(_chat_smart(prompt, image_b64=image_b64, max_tokens=800))
        if result:
            return result
        raise ValueError("Empty JSON")
    except Exception as e:
        print(f"[ai_client] invoice analysis error: {e}")
        return {
            "category": "cost",
            "document_type": "other",
            "summary": "Invoice captured — could not fully parse. Please review manually.",
        }


def generate_weekly_report(entries_data: list, restaurant_name: str = "",
                           kpi_context: str = "", supplier_alert_context: str = "") -> str:
    """
    Generate a weekly intelligence briefing from all entries.
    Uses the smart model for best narrative quality.
    kpi_context: pre-formatted KPI comparison string (week vs week)
    supplier_alert_context: pre-formatted supplier price changes string
    """
    entries_summary = []
    for e in entries_data:
        item = {
            "date": e.get("date"),
            "time": e.get("time"),
            "type": e.get("type"),
            "text": e.get("raw_text", "")[:300],
        }
        if e.get("analysis"):
            a = e["analysis"]
            item["category"] = a.get("category")
            item["summary"]  = a.get("summary")
            for field in ("revenue", "covers", "waste_cost", "waste_items",
                          "complaints", "items_86d", "action_needed"):
                if a.get(field):
                    item[field] = a[field]
        entries_summary.append(item)

    kpi_section = f"\nKPI CONTEXT:\n{kpi_context}\n" if kpi_context else ""
    supplier_section = f"\nSUPPLIER PRICE CHANGES THIS WEEK:\n{supplier_alert_context}\n" if supplier_alert_context else ""

    prompt = f"""You are Restaurant-IQ, an AI intelligence service for "{restaurant_name}", a UK food business.
You combine chartered accountancy discipline with deep restaurant operations expertise.
{kpi_section}{supplier_section}
STAFF DATA CAPTURED THIS WEEK:
{json.dumps(entries_summary, indent=2)}

Write a WEEKLY INTELLIGENCE BRIEFING. Be direct, specific, and actionable — these are busy owners.

## WEEK AT A GLANCE
Revenue, covers, and headline performance vs last week (use KPI context above if provided).

## COST ALERTS
Supplier price increases, invoice anomalies, food cost concerns. Reference specific suppliers and £ amounts.

## OPERATIONAL INSIGHTS
Waste patterns and £ value, 86'd items, complaint themes, staff issues.

## TOP ACTIONS FOR NEXT WEEK
Numbered list of 3-5 specific actions ranked by financial impact.
Lead each with the estimated £ impact. Be concrete — name the supplier, dish, or staff issue.

## POSITIVE HIGHLIGHTS
What went well. Be specific.

---
Rules:
- Use £ for all currency. Round to nearest pound.
- Where data is thin, say so clearly and suggest what to capture next week.
- No filler sentences. Every line must deliver value.
- If you see supplier price increases, quantify the annual cost impact."""

    try:
        return _chat_smart(prompt, max_tokens=1800).strip()
    except Exception as e:
        print(f"[ai_client] report generation error: {e}")
        return (
            f"## Weekly Briefing — {restaurant_name}\n\n"
            f"Unable to generate AI report (error: {e}).\n\n"
            f"Entries captured this week: {len(entries_data)}.\n"
            "Please check your AI backend (Ollama or Anthropic API key)."
        )


def generate_today_summary(entries_data: list, restaurant_name: str = "") -> str:
    """Quick end-of-day summary using the fast model. No PDF."""
    entries_summary = []
    for e in entries_data:
        item = {"time": e.get("time"), "type": e.get("type"),
                "text": e.get("raw_text", "")[:200]}
        if e.get("analysis"):
            a = e["analysis"]
            for f in ("category", "summary", "urgency", "revenue", "covers", "waste_cost"):
                if a.get(f):
                    item[f] = a[f]
        entries_summary.append(item)

    prompt = f"""You are Restaurant-IQ for "{restaurant_name}", a UK restaurant.

TODAY'S STAFF UPDATES:
{json.dumps(entries_summary, indent=2)}

Write a brief end-of-day summary (max 300 words) covering:
• Revenue and covers if reported (with £ totals)
• Any high-urgency issues flagged
• Notable waste or supplier issues
• Top 2 actions for tomorrow

Be concise. Use bullet points. Use £ for currency. No intro fluff."""

    try:
        return _chat_fast(prompt, max_tokens=500).strip()
    except Exception as e:
        print(f"[ai_client] today summary error: {e}")
        return f"Could not generate summary ({e}). {len(entries_data)} entries captured today."


def generate_comparison_report(current_data: list, prev_data: list,
                               current_kpis: dict, prev_kpis: dict,
                               restaurant_name: str = "") -> str:
    """
    Week-on-week comparison report using the smart model.
    Highlights what changed, what improved, what worsened.
    """
    def kpi_str(k):
        parts = []
        if k.get("revenue"):    parts.append(f"Revenue: £{k['revenue']:,.0f}")
        if k.get("covers"):     parts.append(f"Covers: {k['covers']:,}")
        if k.get("food_cost_pct"): parts.append(f"Food cost: {k['food_cost_pct']}%")
        return ", ".join(parts) if parts else "No financial data"

    prompt = f"""You are Restaurant-IQ for "{restaurant_name}".

CURRENT WEEK KPIs:  {kpi_str(current_kpis)}
PREVIOUS WEEK KPIs: {kpi_str(prev_kpis)}

CURRENT WEEK ENTRIES ({len(current_data)}):
{json.dumps([{"cat": e.get("analysis",{}).get("category"), "summary": e.get("analysis",{}).get("summary"), "urgency": e.get("analysis",{}).get("urgency")} for e in current_data[:30]], indent=2)}

PREVIOUS WEEK ENTRIES ({len(prev_data)}):
{json.dumps([{"cat": e.get("analysis",{}).get("category"), "summary": e.get("analysis",{}).get("summary")} for e in prev_data[:20]], indent=2)}

Write a WEEK-ON-WEEK COMPARISON covering:
1. Performance summary (up/down/flat on key metrics — use % changes)
2. What got better and why
3. What got worse and the likely cause
4. Key actions to address the downsides
5. One thing to watch this coming week

Be direct, specific, use £ and %, max 400 words."""

    try:
        return _chat_smart(prompt, max_tokens=600).strip()
    except Exception as e:
        print(f"[ai_client] comparison error: {e}")
        return f"Could not generate comparison ({e}). Try again or check your AI backend."


def generate_supplier_intelligence(price_changes: list, restaurant_name: str = "") -> str:
    """
    Generate a supplier intelligence summary from detected price changes.
    Uses the fast model since the data is already structured.
    """
    if not price_changes:
        return "No significant supplier price changes detected this week."

    changes_str = "\n".join(
        f"  {c['supplier']} — {c['item']}: £{c['old_price']:.2f} → £{c['new_price']:.2f}/unit "
        f"({'+' if c['change_pct'] > 0 else ''}{c['change_pct']}%)"
        for c in price_changes
    )

    prompt = f"""You are a food procurement analyst for "{restaurant_name}".

PRICE CHANGES DETECTED:
{changes_str}

Write a brief supplier intelligence note (max 200 words):
• Summarise the most significant changes and their likely annual £ impact
• Suggest 1-2 actions (renegotiate, find alternative, adjust menu pricing)
• Note any positive changes (price reductions)
Be direct and specific."""

    try:
        return _chat_fast(prompt, max_tokens=300).strip()
    except Exception as e:
        return f"Price changes detected but could not generate analysis ({e})."
