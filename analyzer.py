"""
analyzer.py — Public interface for AI analysis.

All calls are routed through model_router.py which automatically
selects the right AI provider based on restaurant count.

  0-49  restaurants  →  Google Gemini (free)
  50-99 restaurants  →  Groq / Llama  (free)
  100+  restaurants  →  Claude / Anthropic (professional)

No code changes needed here — add the API keys in Railway
and the system upgrades itself.
"""

from model_router import analyze_text, analyze_image, generate_report


def analyze_text_entry(text: str, restaurant_name: str = "",
                       currency_symbol: str = "£", business_type: str = "restaurant") -> dict:
    return analyze_text(text, restaurant_name, currency_symbol, business_type)


def analyze_invoice_photo(image_path: str, restaurant_name: str = "",
                          currency_symbol: str = "£", business_type: str = "restaurant") -> dict:
    return analyze_image(image_path, restaurant_name, currency_symbol, business_type)


def generate_weekly_report(entries_data: list, restaurant_name: str = "",
                           financials: dict | None = None,
                           currency_symbol: str = "£") -> str:
    return generate_report(entries_data, restaurant_name, financials, currency_symbol)
