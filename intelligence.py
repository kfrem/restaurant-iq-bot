"""
intelligence.py — Financial KPI engine for Restaurant-IQ.

Converts raw DB entry data into actionable financial metrics:
  - Food cost % (cost of goods / revenue)
  - Gross profit margin
  - Cover counts and revenue totals
  - Week-on-week trend deltas
  - Supplier price change detection
  - Industry benchmark comparisons

London restaurant industry benchmarks (source: UKHospitality, CGA, ALMR data):
  Casual dining:  food cost ~28–32%, GP ~70%, avg spend ~£28, ~400 covers/week
  Fine dining:    food cost ~32–38%, GP ~68%, avg spend ~£75, ~200 covers/week
  QSR / fast:     food cost ~28–32%, GP ~70%, avg spend ~£12, ~800 covers/week
  Café / brunch:  food cost ~25–30%, GP ~73%, avg spend ~£15, ~500 covers/week
  Pub/gastropub:  food cost ~28–34%, GP ~70%, avg spend ~£22, ~550 covers/week
"""

from collections import defaultdict
from typing import Optional

# ─── Industry benchmarks ──────────────────────────────────────────────────────

BENCHMARKS = {
    "casual":  {"food_cost_pct": 30, "gp_pct": 70, "avg_spend": 28,  "covers_week": 400},
    "fine":    {"food_cost_pct": 35, "gp_pct": 65, "avg_spend": 75,  "covers_week": 200},
    "qsr":     {"food_cost_pct": 30, "gp_pct": 70, "avg_spend": 12,  "covers_week": 800},
    "cafe":    {"food_cost_pct": 27, "gp_pct": 73, "avg_spend": 15,  "covers_week": 500},
    "gastropub": {"food_cost_pct": 31, "gp_pct": 69, "avg_spend": 22, "covers_week": 550},
}
DEFAULT_BENCHMARK = BENCHMARKS["casual"]


# ─── KPI calculation helpers ─────────────────────────────────────────────────

def _to_float(value) -> float:
    """Safely coerce a value to float, stripping £ and commas."""
    try:
        return float(str(value).replace("£", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


def calculate_revenue(entries: list) -> float:
    return sum(_to_float(e.get("analysis", {}).get("revenue")) for e in entries)


def calculate_covers(entries: list) -> int:
    total = 0
    for e in entries:
        covers = e.get("analysis", {}).get("covers")
        if covers:
            try:
                total += int(covers)
            except (ValueError, TypeError):
                pass
    return total


def calculate_food_cost(entries: list) -> float:
    """Sum all cost-category entries with a total_amount (invoices/receipts)."""
    total = 0.0
    for e in entries:
        a = e.get("analysis", {})
        if a.get("category") == "cost" and a.get("total_amount"):
            total += _to_float(a["total_amount"])
    return total


def calculate_waste_cost(entries: list) -> float:
    total = 0.0
    for e in entries:
        wc = e.get("analysis", {}).get("waste_cost")
        if wc:
            total += _to_float(wc)
    return total


def calculate_food_cost_pct(entries: list) -> Optional[float]:
    """Food cost % = total cost invoices / total reported revenue × 100."""
    revenue = calculate_revenue(entries)
    cost    = calculate_food_cost(entries)
    if revenue > 0 and cost > 0:
        return round((cost / revenue) * 100, 1)
    return None


def build_kpis(entries: list) -> dict:
    """Build a KPI dict from a list of entry dicts (as returned by _build_entries_data)."""
    revenue         = calculate_revenue(entries)
    covers          = calculate_covers(entries)
    food_cost       = calculate_food_cost(entries)
    food_cost_pct   = calculate_food_cost_pct(entries)
    waste_cost      = calculate_waste_cost(entries)
    gp_pct          = round((1 - food_cost / revenue) * 100, 1) if revenue > 0 and food_cost > 0 else None

    categories: dict = {}
    high_urgency = 0
    for e in entries:
        a = e.get("analysis", {})
        cat = a.get("category", "general")
        categories[cat] = categories.get(cat, 0) + 1
        if a.get("urgency") == "high":
            high_urgency += 1

    return {
        "revenue":         revenue,
        "covers":          covers,
        "food_cost":       food_cost,
        "food_cost_pct":   food_cost_pct,
        "gp_pct":          gp_pct,
        "waste_cost":      waste_cost,
        "high_urgency":    high_urgency,
        "entry_count":     len(entries),
        "categories":      categories,
    }


def kpi_delta(current: dict, previous: dict, key: str) -> Optional[float]:
    """Return numeric delta between current and previous KPI values, or None."""
    c = current.get(key)
    p = previous.get(key)
    if c is not None and p is not None and p != 0:
        return round(c - p, 1)
    return None


# ─── Supplier price intelligence ─────────────────────────────────────────────

def extract_supplier_prices(entries: list) -> dict:
    """
    Extract supplier → item → price mappings from invoice/receipt entries.
    Returns: {supplier_name: {item_name: {"unit_price": float, "unit": str}}}
    """
    prices: dict = defaultdict(dict)
    for e in entries:
        a = e.get("analysis", {})
        if a.get("category") != "cost":
            continue
        supplier = (a.get("supplier_name") or "").strip()
        if not supplier:
            continue
        for item in a.get("items", []):
            name       = (item.get("name") or "").strip()
            unit_price = item.get("unit_price")
            unit       = (item.get("unit") or "").strip()
            if name and unit_price:
                prices[supplier][name] = {
                    "unit_price": _to_float(unit_price),
                    "unit": unit,
                }
    return dict(prices)


def detect_price_changes(current: dict, historic: dict, threshold_pct: float = 5.0) -> list:
    """
    Compare current supplier prices against historical prices.
    Only flags changes >= threshold_pct (default 5%) to reduce noise.
    Returns list of change dicts sorted by absolute % change (largest first).
    """
    changes = []
    for supplier, items in current.items():
        for item_name, data in items.items():
            new_price = data["unit_price"]
            old_data  = historic.get(supplier, {}).get(item_name)
            if not old_data:
                continue
            old_price = old_data["unit_price"]
            if old_price and old_price > 0:
                pct = ((new_price - old_price) / old_price) * 100
                if abs(pct) >= threshold_pct:
                    annual_impact = (new_price - old_price) * 52  # rough weekly annualisation
                    changes.append({
                        "supplier":       supplier,
                        "item":           item_name,
                        "old_price":      old_price,
                        "new_price":      new_price,
                        "change_pct":     round(pct, 1),
                        "unit":           data.get("unit", ""),
                        "annual_impact":  round(annual_impact, 0),
                    })
    return sorted(changes, key=lambda x: abs(x["change_pct"]), reverse=True)


def format_price_changes(changes: list) -> str:
    """Format price changes as a compact Telegram-friendly string."""
    if not changes:
        return "No significant supplier price changes this week."
    lines = []
    for c in changes:
        icon = "⬆️" if c["change_pct"] > 0 else "⬇️"
        impact_str = f"  (~£{abs(c['annual_impact']):,.0f}/yr impact)" if c["annual_impact"] else ""
        lines.append(
            f"{icon} {c['supplier']} — {c['item']}: "
            f"£{c['old_price']:.2f} → £{c['new_price']:.2f}/{c['unit'] or 'unit'} "
            f"({'+' if c['change_pct'] > 0 else ''}{c['change_pct']}%){impact_str}"
        )
    return "\n".join(lines)


# ─── KPI display formatting ──────────────────────────────────────────────────

def format_kpi_dashboard(current_kpis: dict, prev_kpis: dict = None,
                          restaurant_name: str = "",
                          target_food_cost_pct: float = 30.0,
                          restaurant_type: str = "casual") -> str:
    """
    Format a KPI dashboard as a Telegram message.
    Includes week-on-week deltas and benchmark comparison when data is available.
    """
    benchmark = BENCHMARKS.get(restaurant_type, DEFAULT_BENCHMARK)
    lines = [f"KPI DASHBOARD — {restaurant_name}", "─" * 36, ""]

    def delta_str(val, prev_val, suffix="", higher_is_better=True, is_pct_point=False):
        if val is None or prev_val is None:
            return ""
        delta = val - prev_val
        if is_pct_point:
            sign = "+" if delta > 0 else ""
            arrow = "▲" if delta > 0 else "▼"
            color = "✅" if (delta < 0) == higher_is_better else "⚠️"
            return f"  {color} {arrow}{sign}{delta:.1f}pp vs last wk"
        sign = "+" if delta > 0 else ""
        arrow = "▲" if delta > 0 else "▼"
        return f"  {arrow}{sign}{suffix}{delta:,.0f} vs last wk"

    # Revenue
    rev = current_kpis.get("revenue")
    if rev:
        prev_rev = prev_kpis.get("revenue") if prev_kpis else None
        d = delta_str(rev, prev_rev, "£", higher_is_better=True)
        lines.append(f"Revenue:   £{rev:>10,.0f}{d}")

    # Covers
    covers = current_kpis.get("covers")
    if covers:
        prev_cov = prev_kpis.get("covers") if prev_kpis else None
        d = delta_str(covers, prev_cov, "", higher_is_better=True)
        bm = benchmark.get("covers_week", 0)
        bm_str = f"  (benchmark: {bm:,})" if bm else ""
        lines.append(f"Covers:    {covers:>10,}{d}{bm_str}")

    # Food cost %
    fc_pct = current_kpis.get("food_cost_pct")
    if fc_pct is not None:
        prev_fc = prev_kpis.get("food_cost_pct") if prev_kpis else None
        d = delta_str(fc_pct, prev_fc, higher_is_better=False, is_pct_point=True)
        status = "✅" if fc_pct <= target_food_cost_pct else "⚠️"
        bm = benchmark.get("food_cost_pct", 0)
        bm_str = f"  (target: {target_food_cost_pct}%  |  benchmark: {bm}%)"
        lines.append(f"Food cost: {status} {fc_pct:>7.1f}%{d}{bm_str}")

    # GP %
    gp_pct = current_kpis.get("gp_pct")
    if gp_pct is not None:
        prev_gp = prev_kpis.get("gp_pct") if prev_kpis else None
        d = delta_str(gp_pct, prev_gp, higher_is_better=True, is_pct_point=True)
        bm = benchmark.get("gp_pct", 0)
        bm_str = f"  (benchmark: {bm}%)" if bm else ""
        lines.append(f"GP margin: {gp_pct:>8.1f}%{d}{bm_str}")

    # Waste
    waste = current_kpis.get("waste_cost")
    if waste:
        lines.append(f"Waste:     £{waste:>9,.0f}  ⚠️ review waste log")

    # Urgency flags
    urgent = current_kpis.get("high_urgency", 0)
    if urgent:
        lines.append(f"\n🔴 High-urgency issues this week: {urgent}")

    if not any([rev, covers, fc_pct, gp_pct]):
        lines.append("No financial data captured this week yet.")
        lines.append("")
        lines.append("To see KPIs here, ask staff to include in voice notes:")
        lines.append('  "Revenue today was £3,200, 85 covers"')
        lines.append('  Or send invoice/receipt photos for food cost tracking.')

    return "\n".join(lines)


def format_benchmark_comparison(current_kpis: dict, restaurant_name: str = "",
                                 restaurant_type: str = "casual") -> str:
    """
    Compare the restaurant's KPIs against London industry benchmarks.
    Used by the /benchmark command (Pro tier).
    """
    benchmark = BENCHMARKS.get(restaurant_type, DEFAULT_BENCHMARK)
    type_label = restaurant_type.replace("_", " ").title()

    lines = [
        f"BENCHMARK — {restaurant_name} vs London {type_label}",
        "─" * 40, "",
    ]

    def compare_row(label, actual, bm_val, suffix="%", lower_is_better=False):
        if actual is None:
            return f"{label:<18} {'No data':>12}   vs  {bm_val}{suffix} (benchmark)"
        diff = actual - bm_val
        if lower_is_better:
            icon = "✅" if diff <= 0 else "⚠️"
        else:
            icon = "✅" if diff >= 0 else "⚠️"
        sign = "+" if diff >= 0 else ""
        return (
            f"{label:<18} {actual:>8.1f}{suffix}   vs  {bm_val}{suffix} benchmark  "
            f"{icon} {sign}{diff:.1f}{suffix}"
        )

    lines.append(compare_row("Food cost",     current_kpis.get("food_cost_pct"), benchmark["food_cost_pct"], "%", lower_is_better=True))
    lines.append(compare_row("GP margin",     current_kpis.get("gp_pct"),        benchmark["gp_pct"],       "%"))
    lines.append(compare_row("Covers/week",   current_kpis.get("covers"),        benchmark["covers_week"],  "", lower_is_better=False))
    lines.append("")
    lines.append(f"Industry data: London {type_label} (UKHospitality / CGA benchmarks).")
    lines.append(f"To change your restaurant type, use /targets type casual|fine|qsr|cafe|gastropub")

    return "\n".join(lines)
