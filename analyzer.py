"""
AI analysis using the Google Gemini API.

- Text entries:    gemini-1.5-flash (fast, low cost)
- Invoice photos:  gemini-1.5-flash (native vision support)
- Weekly reports:  gemini-1.5-pro   (best narrative quality)
"""

import json
import PIL.Image
import google.generativeai as genai

from config import GEMINI_API_KEY, GEMINI_MODEL, GEMINI_REPORT_MODEL

genai.configure(api_key=GEMINI_API_KEY)


def _extract_json(text: str) -> dict:
    """Pull the first valid JSON object out of a model response. Returns {} on failure."""
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        return json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return {}


def analyze_text_entry(text: str, restaurant_name: str = "") -> dict:
    """
    Extract structured data from a staff text/voice entry.
    Uses the fast text model (gemini-1.5-flash).
    """
    prompt = f"""You are a restaurant data analyst for "{restaurant_name}".
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

    try:
        model = genai.GenerativeModel(
            GEMINI_MODEL,
            generation_config={"temperature": 0.1, "max_output_tokens": 400},
        )
        response = model.generate_content(prompt)
        result = _extract_json(response.text)
        if result:
            return result
        raise ValueError("Empty JSON response from model")
    except Exception as e:
        print(f"Text analysis error: {e}")
        return {
            "category": "general",
            "summary": text[:120],
            "action_needed": False,
            "urgency": "low",
        }


def analyze_invoice_photo(image_path: str, restaurant_name: str = "") -> dict:
    """
    Read an invoice or receipt photo using Gemini's vision capability.
    Returns structured invoice data.
    """
    prompt = f"""You are an invoice analyst for "{restaurant_name}".
Read this invoice or receipt image carefully and extract all data.

Return ONLY valid JSON — no markdown, no explanation:
{{
  "category": "cost",
  "document_type": "invoice|receipt|delivery_note|other",
  "supplier_name": "",
  "date": "",
  "total_amount": null,
  "vat": null,
  "items": [
    {{"name": "", "quantity": null, "unit": "", "unit_price": null, "total": null}}
  ],
  "summary": "one line summary"
}}"""

    try:
        image = PIL.Image.open(image_path)
        model = genai.GenerativeModel(
            GEMINI_MODEL,
            generation_config={"temperature": 0.1, "max_output_tokens": 600},
        )
        response = model.generate_content([prompt, image])
        result = _extract_json(response.text)
        if result:
            return result
        raise ValueError("Empty JSON response from model")
    except Exception as e:
        print(f"Invoice analysis error: {e}")
        return {
            "category": "cost",
            "document_type": "other",
            "summary": "Invoice captured — could not fully parse. Review manually.",
        }


def generate_weekly_report(entries_data: list, restaurant_name: str = "") -> str:
    """
    Generate a plain-English weekly intelligence briefing from all week's entries.
    Uses the report model for best narrative quality.
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
            item["summary"] = a.get("summary")
            if a.get("revenue"):
                item["revenue"] = a["revenue"]
            if a.get("covers"):
                item["covers"] = a["covers"]
            if a.get("waste_items"):
                item["waste"] = a["waste_items"]
            if a.get("complaints"):
                item["complaints"] = a["complaints"]
            if a.get("items_86d"):
                item["items_86d"] = a["items_86d"]
            if a.get("action_needed"):
                item["action_needed"] = True
        entries_summary.append(item)

    prompt = f"""You are Restaurant-IQ, an AI intelligence service for "{restaurant_name}", a London food business.
You combine chartered accountancy discipline and food economics expertise with AI analysis.

Here is all data captured this week from staff voice notes, photos and messages:

{json.dumps(entries_summary, indent=2)}

Write a WEEKLY INTELLIGENCE BRIEFING with these sections:

## WEEK AT A GLANCE
- Total revenue captured (if reported), total covers, key highlights

## COST ALERTS
- Supplier price changes, invoice anomalies, food cost concerns

## OPERATIONAL INSIGHTS
- Waste and 86'd item patterns, staff issues, complaint themes

## TOP ACTIONS FOR NEXT WEEK
Numbered list of 3-5 specific, actionable priorities ranked by financial impact.
Include an estimated £ impact where data supports it.

## POSITIVE HIGHLIGHTS
What went well this week.

---
Guidelines:
- Language: clear, direct, professional — these are busy owners
- Use £ for all currency
- Where data is thin, say so and suggest what to capture next week
- Be specific with numbers when data supports it
- Keep each section concise — no filler sentences"""

    try:
        model = genai.GenerativeModel(
            GEMINI_REPORT_MODEL,
            generation_config={"temperature": 0.3, "max_output_tokens": 1200},
        )
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"Report generation error: {e}")
        return (
            f"## Weekly Briefing — {restaurant_name}\n\n"
            f"Unable to generate AI report (error: {e}).\n\n"
            f"Raw data captured this week: {len(entries_data)} entries.\n"
            "Please check that GEMINI_API_KEY is set correctly in your environment variables."
        )
