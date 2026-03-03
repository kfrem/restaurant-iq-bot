"""
analyzer.py — Public API for all AI analysis in Restaurant-IQ.

This module is a thin wrapper that delegates to ai_client.py, which
auto-selects between Claude API and Ollama based on ANTHROPIC_API_KEY.
Import from here — never import ai_client directly from bot.py.
"""

from ai_client import (
    analyze_text_entry,
    analyze_invoice_photo,
    generate_weekly_report,
    generate_today_summary,
    generate_comparison_report,
    generate_supplier_intelligence,
    is_healthy,
    backend_name,
)

# Re-export everything so existing callers don't break
__all__ = [
    "analyze_text_entry",
    "analyze_invoice_photo",
    "generate_weekly_report",
    "generate_today_summary",
    "generate_comparison_report",
    "generate_supplier_intelligence",
    "is_healthy",
    "backend_name",
]


def is_ollama_healthy() -> bool:
    """Legacy name kept for backwards compatibility."""
    return is_healthy()
