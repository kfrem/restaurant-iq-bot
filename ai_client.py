"""
ai_client.py — Multi-backend AI with automatic cost-optimised fallback
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Backend priority (cheapest → premium):
  1. Groq         — FREE tier (console.groq.com)        — text only, very fast
  2. Google Gemini — FREE tier (aistudio.google.com)     — text + vision
  3. Ollama        — local / self-hosted                  — text + vision
  4. Anthropic     — paid, Enterprise tier only           — text + vision

Subscription-tier model routing:
  Solo / Trial  →  Groq (text) + Gemini Flash (vision) — costs nothing
  Managed       →  Gemini 1.5 Pro (reports) + Gemini Flash (analysis)
  Enterprise    →  Claude Sonnet (reports) + Claude Haiku (analysis)

Any backends whose keys are missing are silently skipped.
At least one of GROQ_API_KEY or GOOGLE_API_KEY should be set for free usage.
"""

import base64
import json
import logging
import re

logger = logging.getLogger(__name__)

from config import (
    ANTHROPIC_API_KEY, CLAUDE_FAST_MODEL, CLAUDE_SMART_MODEL,
    GOOGLE_API_KEY, GEMINI_FAST_MODEL, GEMINI_SMART_MODEL,
    GROQ_API_KEY, GROQ_MODEL,
    OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_TEXT_MODEL,
)

# ── Lazy singletons (initialised on first use) ────────────────────────────────

_groq_client      = None
_anthropic_client = None
_gemini_ready     = False


def _groq():
    global _groq_client
    if _groq_client is None and GROQ_API_KEY:
        try:
            from groq import Groq
            _groq_client = Groq(api_key=GROQ_API_KEY)
        except ImportError:
            logger.warning("groq package missing — run: pip install groq")
    return _groq_client


def _gemini_init() -> bool:
    global _gemini_ready
    if not _gemini_ready and GOOGLE_API_KEY:
        try:
            import google.generativeai as genai
            genai.configure(api_key=GOOGLE_API_KEY)
            _gemini_ready = True
        except ImportError:
            logger.warning("google-generativeai missing — run: pip install google-generativeai")
    return _gemini_ready


def _anthropic():
    global _anthropic_client
    if _anthropic_client is None and ANTHROPIC_API_KEY:
        try:
            import anthropic
            _anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        except ImportError:
            logger.warning("anthropic package missing — run: pip install anthropic")
    return _anthropic_client


def _ollama_available() -> bool:
    try:
        import urllib.request
        urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=2)
        return True
    except Exception:
        return False


# ── Low-level callers ─────────────────────────────────────────────────────────

def _call_groq(prompt: str, system: str = "", json_mode: bool = False) -> str:
    client = _groq()
    if not client:
        raise RuntimeError("Groq not configured")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    kwargs: dict = {"model": GROQ_MODEL, "messages": messages, "max_tokens": 2048}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content.strip()


def _call_gemini(prompt: str, system: str = "", model: str = None,
                 image_path: str = None) -> str:
    if not _gemini_init():
        raise RuntimeError("Gemini not configured")
    import google.generativeai as genai
    m = genai.GenerativeModel(
        model_name=model or GEMINI_FAST_MODEL,
        system_instruction=system or None,
    )
    if image_path:
        import PIL.Image
        img = PIL.Image.open(image_path)
        response = m.generate_content([prompt, img])
    else:
        response = m.generate_content(prompt)
    if not response.text:
        raise RuntimeError("Gemini returned empty response (safety filter?)")
    return response.text.strip()


def _call_anthropic(prompt: str, system: str = "", model: str = None,
                    image_path: str = None) -> str:
    client = _anthropic()
    if not client:
        raise RuntimeError("Anthropic not configured")
    content: list = []
    if image_path:
        with open(image_path, "rb") as f:
            img_b64 = base64.standard_b64encode(f.read()).decode()
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64},
        })
    content.append({"type": "text", "text": prompt})
    resp = client.messages.create(
        model=model or CLAUDE_FAST_MODEL,
        max_tokens=2048,
        system=system or "You are a restaurant business analyst.",
        messages=[{"role": "user", "content": content}],
    )
    return resp.content[0].text.strip()


def _call_ollama(prompt: str, system: str = "", model: str = None,
                 image_path: str = None) -> str:
    import ollama
    m = model or (OLLAMA_MODEL if image_path else OLLAMA_TEXT_MODEL)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    msg: dict = {"role": "user", "content": prompt}
    if image_path:
        with open(image_path, "rb") as f:
            msg["images"] = [f.read()]
    messages.append(msg)
    resp = ollama.chat(model=m, messages=messages)
    return resp["message"]["content"].strip()


# ── Tier-aware dispatch ───────────────────────────────────────────────────────

def _fast_text(prompt: str, system: str = "", json_mode: bool = False) -> str:
    """
    Cheapest available backend for quick text tasks (entry analysis, today summary).
    Priority: Groq (free) → Gemini Flash (free) → Ollama → Claude Haiku
    """
    errors = []

    if GROQ_API_KEY:
        try:
            return _call_groq(prompt, system, json_mode=json_mode)
        except Exception as e:
            errors.append(f"Groq: {e}")
            logger.debug(f"Groq failed, trying next: {e}")

    if GOOGLE_API_KEY:
        try:
            return _call_gemini(prompt, system, model=GEMINI_FAST_MODEL)
        except Exception as e:
            errors.append(f"Gemini Flash: {e}")
            logger.debug(f"Gemini failed, trying next: {e}")

    try:
        return _call_ollama(prompt, system)
    except Exception as e:
        errors.append(f"Ollama: {e}")

    if ANTHROPIC_API_KEY:
        try:
            return _call_anthropic(prompt, system, model=CLAUDE_FAST_MODEL)
        except Exception as e:
            errors.append(f"Claude Haiku: {e}")

    raise RuntimeError(
        "All AI backends failed. Check your .env keys.\n"
        "Free options: GROQ_API_KEY (groq.com) or GOOGLE_API_KEY (aistudio.google.com)\n"
        + "\n".join(errors)
    )


def _smart_report(prompt: str, system: str = "", tier: str = "solo") -> str:
    """
    Tier-aware backend for report/comparison generation.
      enterprise → Claude Sonnet (best quality, paid)
      managed    → Gemini 1.5 Pro (good quality, cheap)
      solo/trial → Gemini Flash (free) or Groq
    Always has a fallback chain so a report is always produced.
    """
    errors = []

    # Enterprise: Claude Sonnet
    if tier == "enterprise" and ANTHROPIC_API_KEY:
        try:
            return _call_anthropic(prompt, system, model=CLAUDE_SMART_MODEL)
        except Exception as e:
            errors.append(f"Claude Sonnet: {e}")
            logger.warning(f"Claude Sonnet failed, falling back: {e}")

    # Managed/Enterprise: Gemini 1.5 Pro
    if tier in ("managed", "enterprise") and GOOGLE_API_KEY:
        try:
            return _call_gemini(prompt, system, model=GEMINI_SMART_MODEL)
        except Exception as e:
            errors.append(f"Gemini Pro: {e}")
            logger.warning(f"Gemini Pro failed, falling back: {e}")

    # Solo/Trial: Gemini Flash (free)
    if GOOGLE_API_KEY:
        try:
            return _call_gemini(prompt, system, model=GEMINI_FAST_MODEL)
        except Exception as e:
            errors.append(f"Gemini Flash: {e}")
            logger.warning(f"Gemini Flash failed, falling back: {e}")

    # Groq (good for shorter reports)
    if GROQ_API_KEY:
        try:
            return _call_groq(prompt, system)
        except Exception as e:
            errors.append(f"Groq: {e}")

    # Ollama local
    try:
        return _call_ollama(prompt, system)
    except Exception as e:
        errors.append(f"Ollama: {e}")

    # Claude last resort (any tier)
    if ANTHROPIC_API_KEY:
        try:
            return _call_anthropic(prompt, system)
        except Exception as e:
            errors.append(f"Claude: {e}")

    raise RuntimeError(
        "No AI backend available. Set GROQ_API_KEY or GOOGLE_API_KEY in .env for free use.\n"
        + "\n".join(errors)
    )


def _vision_call(prompt: str, image_path: str, system: str = "") -> str:
    """
    Vision call for invoice/receipt reading.
    Priority: Gemini Flash (free vision) → Ollama vision → Claude Haiku
    Groq is text-only and is skipped here.
    """
    errors = []

    if GOOGLE_API_KEY:
        try:
            return _call_gemini(prompt, system, model=GEMINI_FAST_MODEL,
                                image_path=image_path)
        except Exception as e:
            errors.append(f"Gemini: {e}")
            logger.debug(f"Gemini vision failed: {e}")

    try:
        return _call_ollama(prompt, system, image_path=image_path)
    except Exception as e:
        errors.append(f"Ollama: {e}")

    if ANTHROPIC_API_KEY:
        try:
            return _call_anthropic(prompt, system, model=CLAUDE_FAST_MODEL,
                                   image_path=image_path)
        except Exception as e:
            errors.append(f"Claude Haiku: {e}")

    raise RuntimeError(
        "No vision backend available.\n"
        "Set GOOGLE_API_KEY (aistudio.google.com — free) to read invoice photos.\n"
        + "\n".join(errors)
    )


# ── JSON extraction helper ────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """Pull JSON from model output even if wrapped in markdown or prose."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {"summary": text[:200], "category": "general", "urgency": "low"}


# ── System prompts ────────────────────────────────────────────────────────────

_JSON_SYSTEM = (
    "You are a restaurant operations analyst. "
    "Return only valid JSON, no extra text, no markdown fences."
)
_REPORT_SYSTEM = (
    "You are a senior restaurant business analyst writing for independent UK restaurant owners. "
    "Be direct, specific, and actionable. Use British English and £ for currency."
)


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_text_entry(text: str, restaurant_name: str) -> dict:
    prompt = f"""Analyse this restaurant update from {restaurant_name}.

Update: "{text}"

Return exactly this JSON:
{{
  "category": "revenue|cost|staff|waste|maintenance|customer|general",
  "summary": "one sentence summary",
  "urgency": "high|medium|low",
  "revenue": <number or null>,
  "covers": <integer or null>,
  "waste_cost": <number or null>,
  "action_needed": "specific action or null"
}}"""
    try:
        raw = _fast_text(prompt, _JSON_SYSTEM, json_mode=True)
        return _extract_json(raw)
    except Exception as e:
        logger.error(f"analyze_text_entry failed: {e}")
        return {"category": "general", "summary": text[:100], "urgency": "low"}


def analyze_invoice_photo(image_path: str, restaurant_name: str) -> dict:
    prompt = f"""This is an invoice or receipt for {restaurant_name}.
Extract all information and return JSON:

{{
  "supplier_name": "supplier name",
  "invoice_date": "YYYY-MM-DD or null",
  "total_amount": <number or null>,
  "category": "food_cost|beverage|packaging|equipment|utilities|general",
  "summary": "brief description",
  "urgency": "high|medium|low",
  "items": [
    {{"name": "item name", "quantity": <number>, "unit": "kg/case/each/litre", "unit_price": <number>}}
  ]
}}"""
    try:
        raw = _vision_call(prompt, image_path, _JSON_SYSTEM)
        return _extract_json(raw)
    except Exception as e:
        logger.error(f"analyze_invoice_photo failed: {e}")
        return {
            "summary": "Invoice captured — set GOOGLE_API_KEY for free vision analysis",
            "category": "cost", "urgency": "low", "items": [],
        }


def generate_today_summary(entries: list, restaurant_name: str) -> str:
    if not entries:
        return "No entries recorded today."
    lines = "\n".join(
        f"- [{e.get('type', 'text')}] {e.get('raw_text', '')[:150]}"
        for e in entries[:20]
    )
    prompt = f"""Today's entries for {restaurant_name}:
{lines}

Write a concise end-of-day flash report (150 words max):
- Revenue / covers if mentioned
- Key issues or wins
- One priority for tomorrow"""
    try:
        return _fast_text(prompt, _REPORT_SYSTEM)
    except Exception as e:
        logger.error(f"generate_today_summary failed: {e}")
        return f"Summary unavailable — {e}"


def generate_weekly_report(entries: list, restaurant_name: str,
                           kpi_context: str = "", supplier_alert_context: str = "",
                           tier: str = "solo") -> str:
    lines = "\n".join(
        f"- [{e.get('date', '')} {e.get('type', '')}] {e.get('raw_text', '')[:200]}"
        for e in entries[:60]
    )
    sections = [f"RESTAURANT: {restaurant_name}\nENTRIES THIS WEEK:\n{lines}"]
    if kpi_context:
        sections.append(f"KPI SUMMARY:\n{kpi_context}")
    if supplier_alert_context:
        sections.append(f"SUPPLIER ALERTS:\n{supplier_alert_context}")

    prompt = "\n\n".join(sections) + """

Write a comprehensive weekly briefing with these sections:
## Executive Summary
## Financial Performance
## Operational Highlights
## Staff & Service
## Supplier & Cost Intelligence
## Priorities for Next Week

Be specific, use numbers from the data, flag risks clearly."""
    try:
        return _smart_report(prompt, _REPORT_SYSTEM, tier=tier)
    except Exception as e:
        logger.error(f"generate_weekly_report failed: {e}")
        return f"Weekly report generation failed: {e}"


def generate_comparison_report(current_entries: list, prev_entries: list,
                               current_kpis: dict, prev_kpis: dict,
                               restaurant_name: str, tier: str = "solo") -> str:
    def _fmt(kpis: dict) -> str:
        return (
            f"Revenue £{kpis.get('total_revenue', 0):.0f} | "
            f"Covers {kpis.get('total_covers', 0)} | "
            f"Food cost {kpis.get('food_cost_pct', 0):.1f}%"
        )

    prompt = f"""Week-on-week comparison for {restaurant_name}:

THIS WEEK:  {_fmt(current_kpis)}  ({len(current_entries)} entries)
LAST WEEK:  {_fmt(prev_kpis)}  ({len(prev_entries)} entries)

Provide a focused comparison:
- What improved and by how much?
- What declined and why (based on the data)?
- One key action to carry forward"""
    try:
        return _smart_report(prompt, _REPORT_SYSTEM, tier=tier)
    except Exception as e:
        logger.error(f"generate_comparison_report failed: {e}")
        return f"Comparison unavailable — {e}"


def generate_supplier_intelligence(price_changes: list, restaurant_name: str) -> str:
    if not price_changes:
        return "No significant price changes detected this week."
    items = "\n".join(
        f"- {c.get('supplier')}: {c.get('item')} "
        f"{c.get('old_price', '?')} → {c.get('new_price', '?')} "
        f"({c.get('pct_change', 0):+.1f}%)"
        for c in price_changes[:10]
    )
    prompt = f"""Supplier price changes for {restaurant_name}:
{items}

Brief intelligence:
- Which changes are most significant for GP margin?
- Impact on food cost %
- Recommended actions (challenge supplier, find alternative, adjust menu pricing)"""
    try:
        return _fast_text(prompt, _REPORT_SYSTEM)
    except Exception as e:
        logger.error(f"generate_supplier_intelligence failed: {e}")
        return "Supplier intelligence unavailable."


# ── Health & status ───────────────────────────────────────────────────────────

def is_healthy() -> bool:
    """Returns True if at least one backend is configured and reachable."""
    if GROQ_API_KEY or GOOGLE_API_KEY or ANTHROPIC_API_KEY:
        return True   # Cloud key present → assume available (no quota wasted on ping)
    return _ollama_available()  # Local only → needs actual network check


def backend_name() -> str:
    parts = []
    if GROQ_API_KEY:
        parts.append(f"Groq/{GROQ_MODEL} (free)")
    if GOOGLE_API_KEY:
        parts.append(f"Gemini Flash+Pro (free/cheap)")
    if ANTHROPIC_API_KEY:
        parts.append("Claude (Enterprise)")
    if not (GROQ_API_KEY or GOOGLE_API_KEY or ANTHROPIC_API_KEY):
        parts.append(f"Ollama local ({OLLAMA_TEXT_MODEL})")
    return " + ".join(parts) if parts else "No backend configured — set GROQ_API_KEY or GOOGLE_API_KEY"


# Legacy alias used by analyzer.py
def is_ollama_healthy() -> bool:
    return is_healthy()
