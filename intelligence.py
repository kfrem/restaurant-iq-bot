"""
intelligence.py — Financial KPI engine for Restaurant-IQ.

Converts raw DB entry data into actionable financial metrics:
  - Food cost % (cost of goods / revenue)
  - Gross profit margin
  - Cover counts and revenue totals
  - Week-on-week trend deltas
  - Supplier price change detection
  - UK-wide industry benchmark comparisons

UK restaurant industry benchmarks (source: UKHospitality, CGA, ALMR, Lumina data):
  Casual dining:  food cost ~28–32%, GP ~70%, avg spend ~£28, ~400 covers/week
  Fine dining:    food cost ~32–38%, GP ~68%, avg spend ~£75, ~200 covers/week
  QSR / fast:     food cost ~28–32%, GP ~70%, avg spend ~£12, ~800 covers/week
  Café / brunch:  food cost ~25–30%, GP ~73%, avg spend ~£15, ~500 covers/week
  Pub/gastropub:  food cost ~28–34%, GP ~70%, avg spend ~£22, ~550 covers/week

Note: UK national averages used. London operators typically run 5-8% higher
cost bases but achieve 10-20% higher average spend. Regional operators
outside London often achieve better GP margins due to lower fixed costs.
"""

from collections import defaultdict
from typing import Optional

# ─── UK Industry benchmarks ───────────────────────────────────────────────────

BENCHMARKS = {
    "casual":    {"food_cost_pct": 30, "gp_pct": 70, "avg_spend": 28,  "covers_week": 400},
    "fine":      {"food_cost_pct": 35, "gp_pct": 65, "avg_spend": 75,  "covers_week": 200},
    "qsr":       {"food_cost_pct": 30, "gp_pct": 70, "avg_spend": 12,  "covers_week": 800},
    "cafe":      {"food_cost_pct": 27, "gp_pct": 73, "avg_spend": 15,  "covers_week": 500},
    "gastropub": {"food_cost_pct": 31, "gp_pct": 69, "avg_spend": 22,  "covers_week": 550},
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


def calculate_labour_cost(entries: list) -> float:
    """Sum all labour-category entries (wages/payroll logged via voice or text)."""
    total = 0.0
    for e in entries:
        a = e.get("analysis", {})
        if a.get("category") == "labour" and a.get("labour_cost"):
            total += _to_float(a["labour_cost"])
    return total


def calculate_labour_pct(entries: list) -> Optional[float]:
    """Labour cost % = total labour / total revenue × 100."""
    revenue = calculate_revenue(entries)
    labour  = calculate_labour_cost(entries)
    if revenue > 0 and labour > 0:
        return round((labour / revenue) * 100, 1)
    return None


def calculate_avg_spend(entries: list) -> Optional[float]:
    """Average spend per head = total revenue / total covers."""
    revenue = calculate_revenue(entries)
    covers  = calculate_covers(entries)
    if revenue > 0 and covers > 0:
        return round(revenue / covers, 2)
    return None


def calculate_cash_variance(entries: list) -> float:
    """Sum of all till variances (expected - actual) logged this period."""
    total = 0.0
    for e in entries:
        a = e.get("analysis", {})
        if a.get("category") == "cash":
            expected = _to_float(a.get("cash_expected") or 0)
            actual   = _to_float(a.get("cash_actual") or 0)
            if expected and actual:
                total += expected - actual
    return round(total, 2)


def build_kpis(entries: list) -> dict:
    """Build a KPI dict from a list of entry dicts (as returned by _build_entries_data)."""
    revenue         = calculate_revenue(entries)
    covers          = calculate_covers(entries)
    food_cost       = calculate_food_cost(entries)
    food_cost_pct   = calculate_food_cost_pct(entries)
    waste_cost      = calculate_waste_cost(entries)
    labour_cost     = calculate_labour_cost(entries)
    labour_pct      = calculate_labour_pct(entries)
    avg_spend       = calculate_avg_spend(entries)
    cash_variance   = calculate_cash_variance(entries)
    gp_pct          = round((1 - food_cost / revenue) * 100, 1) if revenue > 0 and food_cost > 0 else None

    categories: dict = {}
    high_urgency = 0
    allergen_count = 0
    delivery_issues = 0
    for e in entries:
        a = e.get("analysis", {})
        cat = a.get("category", "general")
        categories[cat] = categories.get(cat, 0) + 1
        if a.get("urgency") == "high":
            high_urgency += 1
        if cat == "allergen":
            allergen_count += 1
        if cat == "delivery_issue":
            delivery_issues += 1

    return {
        "revenue":          revenue,
        "covers":           covers,
        "avg_spend":        avg_spend,
        "food_cost":        food_cost,
        "food_cost_pct":    food_cost_pct,
        "gp_pct":           gp_pct,
        "waste_cost":       waste_cost,
        "labour_cost":      labour_cost,
        "labour_pct":       labour_pct,
        "cash_variance":    cash_variance,
        "allergen_count":   allergen_count,
        "delivery_issues":  delivery_issues,
        "high_urgency":     high_urgency,
        "entry_count":      len(entries),
        "categories":       categories,
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


# ─── Labour dashboard ─────────────────────────────────────────────────────────

def format_labour_dashboard(current_kpis: dict, prev_kpis: dict = None,
                             restaurant_name: str = "",
                             target_labour_pct: float = 30.0) -> str:
    lines = [f"LABOUR DASHBOARD — {restaurant_name}", "─" * 36, ""]

    labour = current_kpis.get("labour_cost", 0)
    revenue = current_kpis.get("revenue", 0)
    labour_pct = current_kpis.get("labour_pct")

    if labour:
        prev_labour = prev_kpis.get("labour_cost", 0) if prev_kpis else None
        delta = f"  (▲£{labour - prev_labour:,.0f} vs last wk)" if prev_labour else ""
        lines.append(f"Wage bill this week:  £{labour:>8,.0f}{delta}")
        annual = labour * 52
        lines.append(f"Annualised estimate:  £{annual:>8,.0f}")
    else:
        lines.append("No wage data logged this week.")
        lines.append("")
        lines.append("To track wages, send a voice note or text like:")
        lines.append('  "Wage bill this week was £3,200"')
        lines.append('  "Paid out payroll today, total £6,400"')
        return "\n".join(lines)

    if labour_pct is not None:
        status = "✅" if labour_pct <= target_labour_pct else "⚠️"
        prev_lp = prev_kpis.get("labour_pct") if prev_kpis else None
        delta_str = ""
        if prev_lp:
            d = labour_pct - prev_lp
            delta_str = f"  ({'▲' if d > 0 else '▼'}{abs(d):.1f}pp vs last wk)"
        lines.append(f"Labour %:             {status} {labour_pct:.1f}%{delta_str}  (target: <{target_labour_pct}%)")
    elif revenue:
        lines.append("Labour %:             Log revenue entries to calculate %")

    return "\n".join(lines)


# ─── Waste report ─────────────────────────────────────────────────────────────

def format_waste_report(entries: list, restaurant_name: str = "") -> str:
    waste_entries = [
        e for e in entries
        if e.get("analysis", {}).get("category") == "waste"
        and e.get("analysis", {}).get("waste_cost")
    ]

    lines = [f"WASTE LOG — {restaurant_name}", "─" * 36, ""]

    if not waste_entries:
        lines.append("No waste logged this week.")
        lines.append("")
        lines.append("To track waste, send a voice note like:")
        lines.append('  "Threw out a tray of salmon, about £40 worth"')
        lines.append('  "Binned 2kg of over-ripe veg, maybe £15"')
        return "\n".join(lines)

    total = 0.0
    by_day: dict = {}
    for e in waste_entries:
        a    = e.get("analysis", {})
        date = e.get("date", "unknown")
        cost = _to_float(a.get("waste_cost", 0))
        total += cost
        by_day.setdefault(date, []).append((a.get("summary", "waste logged"), cost))

    for date, items in sorted(by_day.items()):
        day_total = sum(c for _, c in items)
        lines.append(f"{date}  (£{day_total:.0f})")
        for summary, cost in items:
            lines.append(f"  • {summary}  £{cost:.0f}")

    lines.append("")
    lines.append(f"TOTAL this week:  £{total:,.0f}")
    lines.append(f"Annualised:       £{total * 52:,.0f}/year")

    return "\n".join(lines)


# ─── Cash reconciliation ──────────────────────────────────────────────────────

def format_cash_reconciliation(entries: list, restaurant_name: str = "") -> str:
    cash_entries = [
        e for e in entries
        if e.get("analysis", {}).get("category") == "cash"
        and (e.get("analysis", {}).get("cash_expected") or e.get("analysis", {}).get("cash_actual"))
    ]

    lines = [f"CASH RECONCILIATION — {restaurant_name}", "─" * 36, ""]

    if not cash_entries:
        lines.append("No till counts logged this week.")
        lines.append("")
        lines.append("To track cash, send a voice note at end of each day like:")
        lines.append('  "Till count tonight, expected £842, actual £838"')
        lines.append('  "Cash up done, £920 in the till"')
        return "\n".join(lines)

    total_variance = 0.0
    for e in cash_entries:
        a        = e.get("analysis", {})
        date     = e.get("date", "unknown")
        expected = _to_float(a.get("cash_expected") or 0)
        actual   = _to_float(a.get("cash_actual") or 0)
        summary  = a.get("summary", "cash logged")

        if expected and actual:
            variance = actual - expected
            total_variance += variance
            status = "✅" if abs(variance) <= 5 else ("⚠️" if abs(variance) <= 20 else "🔴")
            lines.append(
                f"{date}  Expected £{expected:,.0f}  Actual £{actual:,.0f}  "
                f"Variance {'+' if variance >= 0 else ''}£{variance:.0f}  {status}"
            )
        else:
            lines.append(f"{date}  {summary}")

    lines.append("")
    tv_status = "✅" if abs(total_variance) <= 20 else "⚠️"
    lines.append(f"Week total variance:  {'+' if total_variance >= 0 else ''}£{total_variance:.0f}  {tv_status}")
    if total_variance < -50:
        lines.append("⚠️ Significant shortfall — investigate cash handling procedures.")

    return "\n".join(lines)


# ─── Allergen log ─────────────────────────────────────────────────────────────

def format_allergen_log(entries: list, restaurant_name: str = "") -> str:
    allergen_entries = [
        e for e in entries
        if e.get("analysis", {}).get("category") == "allergen"
    ]

    lines = [f"ALLERGEN LOG — {restaurant_name}", "─" * 36, ""]

    if not allergen_entries:
        lines.append("No allergen incidents logged this week. ✅")
        lines.append("")
        lines.append("To log allergen incidents (required by law), send a voice note like:")
        lines.append('  "Customer asked about nuts in the Caesar salad — confirmed nut free"')
        lines.append('  "Guest reported gluten reaction after fish and chips — investigating"')
        return "\n".join(lines)

    for e in allergen_entries:
        a        = e.get("analysis", {})
        date     = e.get("date", "unknown")
        urgency  = a.get("urgency", "low")
        icon     = "🔴" if urgency == "high" else ("🟡" if urgency == "medium" else "🟢")
        allergen = a.get("allergen_name", "unspecified allergen")
        dish     = a.get("allergen_dish", "")
        summary  = a.get("summary", "allergen incident logged")
        action   = a.get("action_needed")

        dish_str   = f" — {dish}" if dish else ""
        action_str = f"\n   Action: {action}" if action else ""
        lines.append(f"{icon} {date}  {allergen.upper()}{dish_str}")
        lines.append(f"   {summary}{action_str}")
        lines.append("")

    lines.append("⚠️ Keep all allergen logs for at least 3 years (Natasha's Law requirement).")

    return "\n".join(lines)


# ─── Supplier reliability ─────────────────────────────────────────────────────

def format_supplier_reliability(entries: list, restaurant_name: str = "") -> str:
    issue_entries = [
        e for e in entries
        if e.get("analysis", {}).get("category") == "delivery_issue"
    ]

    lines = [f"SUPPLIER RELIABILITY — {restaurant_name}", "─" * 36, ""]

    if not issue_entries:
        lines.append("No delivery issues logged this period. ✅")
        lines.append("")
        lines.append("To log delivery issues, send a voice note like:")
        lines.append('  "Brakes didn\'t deliver the chicken again, short by 10kg"')
        lines.append('  "Turner Foods delivered late, 3 hours after the window"')
        return "\n".join(lines)

    by_supplier: dict = {}
    for e in issue_entries:
        a        = e.get("analysis", {})
        supplier = a.get("supplier_name") or "Unknown supplier"
        issue    = a.get("delivery_issue") or a.get("summary", "issue logged")
        date     = e.get("date", "unknown")
        urgency  = a.get("urgency", "low")
        by_supplier.setdefault(supplier, []).append((date, issue, urgency))

    for supplier, issues in sorted(by_supplier.items(), key=lambda x: -len(x[1])):
        count  = len(issues)
        icon   = "🔴" if count >= 3 else ("🟡" if count >= 2 else "🟢")
        lines.append(f"{icon} {supplier} — {count} issue{'s' if count > 1 else ''}")
        for date, issue, _ in issues:
            lines.append(f"   • {date}: {issue}")
        lines.append("")

    if len(issue_entries) >= 3:
        lines.append("💡 Consider raising these issues at your next supplier review,")
        lines.append("   or request a credit note for failed/short deliveries.")

    return "\n".join(lines)


# ─── Menu profitability (4-box matrix) ───────────────────────────────────────

def format_menu_profitability(menu_items: list, restaurant_name: str = "") -> str:
    """
    Classic 4-box menu engineering matrix:
      Stars       — high margin + high popularity (assume all logged dishes are 'popular' for now)
      Ploughhorses — low margin + (implicitly popular)
      Opportunities — high margin (to be promoted)
      Dogs         — low margin (review or remove)

    Since we don't track per-dish order counts here, we split on margin % alone:
      High margin = food cost % < 33%  (GP > 67%)
      Low margin  = food cost % >= 33%
    """
    if not menu_items:
        return (
            f"MENU PROFITABILITY — {restaurant_name}\n"
            "─" * 36 + "\n\n"
            "No dishes added yet.\n\n"
            "Add your dishes with:\n"
            "  /menu add Fish and Chips 4.20 14.50\n"
            "  (dish name, food cost £, selling price £)"
        )

    lines = [f"MENU PROFITABILITY — {restaurant_name}", "─" * 36, ""]

    stars, ploughhorses, opportunities, dogs = [], [], [], []

    for item in menu_items:
        name  = item["dish_name"]
        cost  = item["food_cost"] or 0
        price = item["selling_price"] or 0
        if price <= 0:
            continue
        fc_pct = (cost / price) * 100
        gp_pct = 100 - fc_pct
        margin_label = f"FC {fc_pct:.0f}%  GP {gp_pct:.0f}%"

        if fc_pct < 33:
            stars.append((name, margin_label, price))
        else:
            dogs.append((name, margin_label, price))

    def _rows(items):
        return "\n".join(f"  {n:<28} {m}  @ £{p:.2f}" for n, m, p in items)

    if stars:
        lines.append("⭐ HIGH MARGIN (food cost < 33%) — protect and promote these")
        lines.append(_rows(stars))
        lines.append("")

    if dogs:
        lines.append("⚠️ REVIEW NEEDED (food cost ≥ 33%) — reprice or reduce portion")
        lines.append(_rows(dogs))
        lines.append("")

    avg_fc = sum(
        (item["food_cost"] / item["selling_price"]) * 100
        for item in menu_items
        if item["food_cost"] and item["selling_price"]
    ) / max(len([i for i in menu_items if i["food_cost"] and i["selling_price"]]), 1)

    lines.append(f"Average menu food cost: {avg_fc:.1f}%")
    lines.append("Update dishes: /menu add DishName FoodCost SellingPrice")
    lines.append("Remove a dish: /menu remove DishName")

    return "\n".join(lines)


# ─── VAT summary ──────────────────────────────────────────────────────────────

def format_vat_summary(entries: list, restaurant_name: str = "",
                        period_label: str = "this quarter") -> str:
    """
    Estimate VAT position from captured revenue and cost data.
    All UK restaurant sales are standard-rated (20%) unless VAT-registered with
    a turnover threshold. This is a rough estimate — not a substitute for an accountant.
    """
    revenue   = calculate_revenue(entries)
    costs     = calculate_food_cost(entries)
    labour    = calculate_labour_cost(entries)

    lines = [f"VAT SUMMARY — {restaurant_name}", f"Period: {period_label}", "─" * 36, ""]

    if not revenue:
        lines.append("No revenue data captured for this period.")
        lines.append("Log daily revenue via voice note to see your VAT estimate.")
        return "\n".join(lines)

    output_vat   = round(revenue * 20 / 120, 2)   # VAT included in revenue (1/6 rule)
    input_vat    = round(costs  * 20 / 120, 2)     # Reclaimable VAT on purchases
    net_vat      = round(output_vat - input_vat, 2)

    lines.append(f"Revenue captured:       £{revenue:>10,.2f}")
    lines.append(f"Output VAT (est.):      £{output_vat:>10,.2f}  ← VAT you owe HMRC")
    lines.append("")
    lines.append(f"Supplier costs logged:  £{costs:>10,.2f}")
    lines.append(f"Input VAT (est.):       £{input_vat:>10,.2f}  ← VAT you can reclaim")
    if labour:
        lines.append(f"Wages (VAT exempt):     £{labour:>10,.2f}")
    lines.append("")
    lines.append(f"Estimated net VAT due:  £{net_vat:>10,.2f}")
    lines.append("")
    lines.append("⚠️ These are rough estimates based on logged entries only.")
    lines.append("   Share this summary with your accountant — not a substitute for")
    lines.append("   a properly filed VAT return.")

    return "\n".join(lines)


# ─── Cash flow forecast ───────────────────────────────────────────────────────

def format_cashflow_forecast(current_balance: float, weekly_revenue: float,
                              weekly_food_cost: float, weekly_labour: float,
                              weekly_overheads: float = 0.0,
                              restaurant_name: str = "") -> str:
    """
    4-week rolling cash flow forecast including all overhead costs.
    weekly_overheads should include energy, rent, rates, etc. (excl. food/labour).
    """
    lines = [f"CASH FLOW FORECAST — {restaurant_name}", "─" * 36, ""]

    if not current_balance:
        lines.append("Set your current bank balance to see a forecast:")
        lines.append("  /cashflow 8400")
        lines.append("")
        lines.append("Tip: also log your fixed costs for an accurate forecast:")
        lines.append("  /overhead rent 3200")
        lines.append("  /overhead electricity 450")
        return "\n".join(lines)

    weekly_costs = weekly_food_cost + weekly_labour + weekly_overheads
    weekly_net   = weekly_revenue - weekly_costs

    lines.append(f"Current balance:      £{current_balance:>10,.0f}")
    lines.append("")
    lines.append(f"Weekly revenue (avg): £{weekly_revenue:>10,.0f}")
    lines.append(f"Weekly costs (avg):   £{weekly_costs:>10,.0f}")
    lines.append(f"  Food/drinks:        £{weekly_food_cost:>10,.0f}")
    lines.append(f"  Labour:             £{weekly_labour:>10,.0f}")
    if weekly_overheads > 0:
        lines.append(f"  Overheads:          £{weekly_overheads:>10,.0f}")
    else:
        lines.append(f"  Overheads:             not logged")
        lines.append(f"  ⚠️ Add /overhead entries for accuracy")
    lines.append(f"Weekly net:           £{weekly_net:>10,.0f}")
    lines.append("")
    lines.append("PROJECTED BALANCE:")

    balance = current_balance
    for week in range(1, 5):
        balance += weekly_net
        status = "✅" if balance > 2000 else ("⚠️" if balance > 0 else "🔴 DANGER")
        lines.append(f"  Week {week}: £{balance:>8,.0f}  {status}")

    if balance < 0:
        lines.append("")
        lines.append("🔴 Warning: Current trajectory leads to negative balance.")
        lines.append("   Review costs or ensure revenue entries are logged regularly.")
    elif balance < 2000:
        lines.append("")
        lines.append("⚠️ Balance will be tight. Monitor closely.")

    lines.append("")
    lines.append("Update balance: /cashflow <amount>  e.g. /cashflow 9500")
    lines.append("Based on this week's logged data — log more entries for accuracy.")

    return "\n".join(lines)


# ─── Overhead / operating expenses dashboard ──────────────────────────────────

# Category display order and labels
_OVERHEAD_CATEGORY_LABELS = {
    "energy":     "ENERGY",
    "occupancy":  "OCCUPANCY",
    "staffing":   "STAFFING ON-COSTS",
    "compliance": "COMPLIANCE & LEGAL",
    "marketing":  "MARKETING",
    "finance":    "FINANCE",
    "operations": "OPERATIONS",
    "admin":      "ADMIN",
    "custom":     "CUSTOM / UNCATEGORISED",
}

# UK benchmark: overhead as % of revenue (excl. food & labour)
_OVERHEAD_BENCHMARKS = {
    "energy":     (3.0,  5.0),
    "occupancy":  (8.0,  12.0),
    "staffing":   (2.0,  4.0),   # NI, pension, staff meals on top of wages
    "compliance": (0.5,  1.5),
    "marketing":  (2.0,  4.0),
    "finance":    (1.0,  2.5),
    "operations": (1.5,  3.0),
    "admin":      (0.5,  1.5),
}


def format_overhead_dashboard(summary: dict, revenue: float = 0.0,
                               food_cost: float = 0.0, labour_cost: float = 0.0,
                               restaurant_name: str = "", period_days: int = 30) -> str:
    """
    Format a full overhead expense breakdown with benchmarks and prime cost calculation.
    summary: output of database.get_overhead_summary()
    """
    lines = [f"OVERHEAD EXPENSES ({period_days} days) — {restaurant_name}", "─" * 44, ""]

    if not summary:
        lines.append("No overhead expenses logged yet.")
        lines.append("")
        lines.append("Log your fixed and variable costs:")
        lines.append("  /overhead electricity 450")
        lines.append("  /overhead gas 380")
        lines.append("  /overhead rent 3200")
        lines.append("  /overhead rates 850")
        lines.append("  /overhead insurance 290")
        lines.append("  /overhead deliveroo 480")
        lines.append("  /overhead card_fees 180")
        lines.append("  /overhead water 95")
        lines.append("  /overhead cleaning 65")
        lines.append("  /overhead packaging 210")
        lines.append("")
        lines.append("Type /overhead for full list of categories.")
        return "\n".join(lines)

    grand_total = sum(
        v["total"]
        for cat in summary.values()
        for v in cat.values()
    )

    if revenue > 0:
        overhead_pct = (grand_total / revenue) * 100
        pct_str = f"  ({overhead_pct:.1f}% of revenue)"
        status = "✅" if overhead_pct <= 22 else ("⚠️" if overhead_pct <= 28 else "🔴")
    else:
        pct_str = ""
        status = ""

    lines.append(f"Total overheads:    £{grand_total:>9,.0f}{pct_str} {status}")
    if revenue > 0:
        lines.append(f"Revenue this period: £{revenue:>8,.0f}")
    lines.append("")

    # Per-category breakdown
    category_order = ["energy", "occupancy", "staffing", "compliance",
                      "marketing", "finance", "operations", "admin", "custom"]
    for cat in category_order:
        if cat not in summary:
            continue
        cat_total = sum(v["total"] for v in summary[cat].values())
        label = _OVERHEAD_CATEGORY_LABELS.get(cat, cat.upper())
        cat_pct = f"  {(cat_total/revenue*100):.1f}%" if revenue > 0 else ""

        # Benchmark flag
        bench = _OVERHEAD_BENCHMARKS.get(cat)
        bench_flag = ""
        if bench and revenue > 0:
            pct = cat_total / revenue * 100
            if pct > bench[1]:
                bench_flag = " ⚠️ above target"
            elif pct <= bench[0]:
                bench_flag = " ✅"

        lines.append(f"  {label:<14} £{cat_total:>8,.0f}{cat_pct}{bench_flag}")
        for sub, data in sorted(summary[cat].items()):
            lines.append(f"    {sub:<20} £{data['total']:>7,.0f}")
        lines.append("")

    # Prime cost section
    if food_cost > 0 or labour_cost > 0:
        energy_total = sum(v["total"] for v in summary.get("energy", {}).values())
        prime = food_cost + labour_cost + energy_total
        lines.append("─" * 44)
        lines.append("PRIME COST (food + labour + energy):")
        lines.append(f"  Food cost:    £{food_cost:>8,.0f}" +
                     (f"  ({food_cost/revenue*100:.1f}%)" if revenue > 0 else ""))
        lines.append(f"  Labour:       £{labour_cost:>8,.0f}" +
                     (f"  ({labour_cost/revenue*100:.1f}%)" if revenue > 0 else ""))
        lines.append(f"  Energy:       £{energy_total:>8,.0f}" +
                     (f"  ({energy_total/revenue*100:.1f}%)" if revenue > 0 else ""))
        lines.append(f"  ─────────────────────────")
        prime_pct = prime / revenue * 100 if revenue > 0 else 0
        prime_status = "✅" if prime_pct < 60 else ("⚠️" if prime_pct < 65 else "🔴")
        lines.append(f"  PRIME TOTAL:  £{prime:>8,.0f}" +
                     (f"  ({prime_pct:.1f}%) {prime_status}" if revenue > 0 else ""))
        if revenue > 0:
            lines.append(f"  UK target: prime cost < 60% of revenue")
        lines.append("")

    lines.append("Log expenses: /overhead <type> <£amount>")
    lines.append("Examples:")
    lines.append("  /overhead electricity 450")
    lines.append("  /overhead rent 3200")
    lines.append("  /overhead deliveroo 480")

    return "\n".join(lines)


# ─── Energy monitoring and advisor ───────────────────────────────────────────

ENERGY_SAVING_TIPS = """
ENERGY SAVING TIPS FOR RESTAURANTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔴 HIGH IMPACT — save £100–500/month:

• FRYERS: Turn off between lunch and dinner
  service. Each fryer costs ~£4/day to idle.
  Turning off for 2 hours saves ~£50/month.

• OVENS: Pre-heat 20 mins before service —
  NOT 2 hours. Turn off 30 mins before close.
  A commercial oven left on unnecessarily
  wastes £80–120/month.

• EXTRACTION FANS: Don't run at full speed
  during quiet periods. Variable-speed fans
  pay back their cost in under 12 months.

• FRIDGE/FREEZER SEALS: A broken door seal
  wastes 20–30% of fridge energy. Test it:
  close the door on a piece of paper — if
  the paper slides out easily, replace the
  seal (costs ~£20, saves ~£30/month).

🟡 MEDIUM IMPACT — save £30–100/month:

• DISHWASHER: Only run full loads. Turn off
  overnight. Leaving on standby costs £25/month.

• HOT WATER: Set to exactly 60°C — hotter
  wastes gas, colder risks legionella.

• LIGHTING: Switch to LED bulbs throughout.
  10 bulbs = ~£15/month saving. Add motion
  sensors in storage rooms and toilets.

• GRILL & HOT PLATE: Don't leave on between
  service periods. 20 mins to heat up is enough.

🟢 QUICK WINS — save £10–30/month:

• Only boil what you need in the kettle.
• Turn off TVs, screens and tablets overnight.
• Defrost freezers regularly — ice build-up
  forces the motor to work harder.
• Use lids on pots — boils faster, uses less gas.
• Check oven door seals every month.

⏰ CLOSING CHECKLIST (save £150–300/month):

Turn OFF every night:
  ☐ Fryers
  ☐ Ovens and grills
  ☐ Hot holding / bain marie
  ☐ Heat lamps
  ☐ Dishwasher
  ☐ Extraction fans
  ☐ Non-essential fridges (if empty)
  ☐ TVs and monitors
  ☐ Coffee machine boiler (if not used mornings)
  ☐ Non-essential lighting

Always leave ON:
  ✅ Main fridges and freezers
  ✅ Alarm and CCTV
  ✅ Emergency lighting

📊 UK ENERGY BENCHMARK:
  Energy should be 3–5% of weekly revenue.
  Above 6%? You're likely wasting £200–500/month.

  Typical costs (per month):
    Small café / takeaway:    £400–900
    Casual restaurant (50):   £800–1,800
    Busy restaurant (100+):   £1,500–3,500
""".strip()


def format_energy_dashboard(energy_logs: list, revenue: float = 0.0,
                             restaurant_name: str = "") -> str:
    """Show energy cost history and benchmark against revenue."""
    lines = [f"ENERGY TRACKER — {restaurant_name}", "─" * 36, ""]

    if not energy_logs:
        lines.append("No energy bills logged yet.")
        lines.append("")
        lines.append("Log your bills like this:")
        lines.append("  /energy electricity 450")
        lines.append("  /energy electricity 450 2800")
        lines.append("  (£450 bill, 2800 kWh used)")
        lines.append("")
        lines.append("  /energy gas 380")
        lines.append("  /energy gas 380 1200")
        lines.append("  (£380 bill, 1200 m³ used)")
        lines.append("")
        lines.append("  /energy tips  — get energy saving advice")
        return "\n".join(lines)

    # Group by subcategory (Electricity, Gas, etc.)
    totals: dict = {}
    for row in energy_logs:
        sub = row["subcategory"]
        totals.setdefault(sub, {"amount": 0.0, "units": 0.0, "count": 0})
        totals[sub]["amount"] += row["amount"]
        if row["units"]:
            totals[sub]["units"] += row["units"]
        totals[sub]["count"] += 1

    grand_total = sum(v["amount"] for v in totals.values())

    if revenue > 0:
        pct = grand_total / revenue * 100
        bench = "✅ on target" if pct <= 5 else ("⚠️ above target — see /energy tips" if pct <= 7 else "🔴 HIGH — act now, see /energy tips")
        lines.append(f"Total energy cost:  £{grand_total:,.0f}  ({pct:.1f}% of revenue)")
        lines.append(f"UK benchmark (3–5%): {bench}")
    else:
        lines.append(f"Total energy cost:  £{grand_total:,.0f}")
        lines.append("Log revenue entries so we can show your energy %.")
    lines.append("")

    for sub, data in sorted(totals.items()):
        lines.append(f"  {sub:<16} £{data['amount']:>7,.0f}  ({data['count']} bills)")
        if data["units"] > 0:
            unit_label = "kWh" if "Electr" in sub else "m³"
            cost_per = data["amount"] / data["units"]
            lines.append(f"  {'':16} {data['units']:,.0f} {unit_label}  "
                         f"({cost_per:.1f}p per {unit_label.rstrip('h')})")
    lines.append("")

    # Recent bills
    lines.append("RECENT BILLS:")
    for row in energy_logs[:6]:
        note = f" — {row['note']}" if row["note"] else ""
        units = f"  {row['units']:.0f} {'kWh' if 'Electr' in row['subcategory'] else 'm³'}" if row["units"] else ""
        lines.append(f"  {row['bill_date']}  {row['subcategory']:<16} £{row['amount']:>7,.0f}{units}{note}")

    lines.append("")
    lines.append("For energy saving advice: /energy tips")
    lines.append("Log a bill: /energy electricity 450 2800")

    return "\n".join(lines)


# ─── Revenue growth advisor ───────────────────────────────────────────────────

# Revenue growth levers per restaurant type
# Each entry: (title, detail, weekly_£_potential)
_GROWTH_PLAYS = {
    "casual": [
        ("Upsell starters and desserts",
         "Train staff to offer starters to every table and desserts to every diner who "
         "finishes their main. Even 25% conversion on starters at £7 and desserts at £6 "
         "adds £3.25/head on a 400-cover week.",
         "£520–800/week"),
        ("Launch a weekday lunch offer",
         "Many casual restaurants make 70% of revenue at dinner. A 2-course £18 weekday "
         "lunch set menu can fill 30–60 extra covers Mon–Fri with pre-prepared food, low "
         "waste, and predictable staffing.",
         "£540–1,080/week"),
        ("Cocktail / pre-dinner drinks moment",
         "A focused aperitif offer (3–4 options, £9–11 each) offered as guests sit down "
         "converts at 25–40%. At 400 covers at 30% take-up and £10 average = £1,200/week "
         "at 70%+ GP — your most profitable sell.",
         "£400–1,200/week"),
        ("Private dining and events",
         "A set-menu private dining event at £45/head minimum spend is pre-sold, low-waste, "
         "and efficient. Even 2 events/month of 20 guests each = £1,800/month in predictable "
         "additional revenue with higher GP than a la carte.",
         "£400–900/week average"),
        ("Capture emails and drive return visits",
         "Most restaurants lose 70% of customers after one visit. A simple email capture "
         "(via reservation system or QR code) and monthly re-engagement email with an offer "
         "('Book your table, mention this email, get a complimentary dessert') costs pennies "
         "and drives measurable repeat bookings.",
         "£200–600/week (repeat trade)"),
    ],
    "fine": [
        ("Introduce sommelier-curated wine pairings",
         "Wine pairing at £45–70/head on a tasting menu converts at 20–40% when actively "
         "offered by the sommelier or server. On 200 covers at 30% take-up and £55 pairing "
         "= £3,300/week at 70%+ GP. The single highest-impact revenue lever for fine dining.",
         "£1,500–4,000/week"),
        ("Pre-dinner champagne and cocktail service",
         "Dedicated bar/lounge seating before dinner. Even a 30-min arrival drink at £15–25 "
         "per person converted on 60% of covers = £1,800–5,000/week in bar revenue at "
         "65–70% GP.",
         "£1,200–3,000/week"),
        ("Chef's table or counter dining premium",
         "A 6–8 seat chef's table or kitchen counter experience at a 15–25% premium over "
         "standard covers (or as a separate experience at £120–200/head inclusive). "
         "Full pre-payment eliminates no-shows on these seats.",
         "£720–1,600/week"),
        ("Weekday tasting menu lunch at accessible price",
         "A 4-course lunch at £55–70 (vs £95–130 dinner) opens a completely different "
         "market: corporate lunches, special occasions, food writers. Lunch service typically "
         "has lower labour cost (prep done for dinner service anyway).",
         "£1,100–2,800/week"),
        ("Pre-sold seasonal events (Valentine's, NYE, Christmas)",
         "Ticket-only events with 100% pre-payment at premium pricing. Valentine's at £120/head "
         "for 60 covers = £7,200 in one evening. Christmas set menu Nov–Dec can represent "
         "15–25% of annual revenue. Book out 3–6 months in advance.",
         "Seasonal windfall — £5,000–20,000 per event"),
    ],
    "qsr": [
        ("Meal deal bundling — add sides and drinks automatically",
         "QSR research shows bundling increases average spend 20–35% vs individual items. "
         "'Make it a meal for £2.50 more' at the point of order converts at 40–60%. "
         "On 800 covers at £12 average and 40% take-up at £2.50 extra = £800/week.",
         "£400–1,200/week"),
        ("Digital ordering (kiosk or app)",
         "Self-service kiosks and app ordering consistently increase average spend by 15–20% "
         "vs counter ordering — customers add items they would feel embarrassed to request "
         "from a person. For 800 covers/week at £12, a 15% uplift = £1,440/week.",
         "£700–2,000/week"),
        ("Virtual brand on delivery platforms",
         "Run a second brand from your existing kitchen with a different menu on Uber Eats "
         "or Deliveroo. Uses spare kitchen capacity during quiet periods. A focused "
         "virtual brand (e.g., a wings concept or loaded fries concept) can add "
         "£500–2,000/week with minimal incremental cost.",
         "£500–2,000/week"),
        ("Loyalty app — drive return frequency",
         "QSR loyalty schemes increase visit frequency by 25–40%. A simple stamp-based "
         "app (every 8th meal free) costs ~£80/month to operate. If you have 200 regular "
         "customers and loyalty increases their frequency from 2x/month to 2.5x/month, "
         "that's 100 extra covers/month at £12 = £1,200/month.",
         "£200–600/week"),
        ("Breakfast / coffee daypart",
         "If not already trading at breakfast, a simple breakfast menu (£4–8, coffee + item) "
         "captures a second daily revenue occasion. Regular breakfast customers spend "
         "£1,500–3,000/year at one location. 20 regular breakfast covers = £80–160/day "
         "in additional revenue.",
         "£400–1,000/week"),
    ],
    "cafe": [
        ("Premium coffee upsell and retail coffee sales",
         "Train staff to describe coffee origin and flavour profile — premium option "
         "take-up increases 20–40%. Sell retail bags (250g at £9–14) at the counter. "
         "On 500 coffee covers, moving 15% to a £1 premium option = £75/day. "
         "Retail: 20 bags/week at £11 average = £220/week at 60%+ GP.",
         "£250–700/week"),
        ("Bottomless brunch (Saturday and Sunday)",
         "Bottomless brunch at £28–38/head for 90 minutes. Pre-booked, pre-paid. "
         "Food-led cafes/brunch spots with table licence can fill weekend mornings at "
         "guaranteed revenue. 30 covers at £32 = £960 per session, 2 sessions/weekend "
         "= £1,920/weekend.",
         "£800–2,000/week (weekends only)"),
        ("Evening trading — wine, cheese and charcuterie",
         "Most cafes close at 5pm, missing the 5–8pm early-evening opportunity. "
         "A simple evening offer (wine by glass £6–9, sharing boards £14–18) with "
         "minimal extra staff can generate £300–800/evening Thu–Sat.",
         "£300–800/week"),
        ("Subscription coffee model",
         "'Coffee Club — £35/month unlimited filter coffee.' Creates guaranteed recurring "
         "revenue, drives daily return visits, and builds community. At 50 subscribers "
         "= £1,750/month recurring, mostly margin since filter coffee cost is minimal.",
         "£400–700/week from subscribers"),
        ("Remote worker trade (weekday)",
         "Free WiFi, power sockets, and a quiet environment. Market to local co-working "
         "communities and businesses. Remote workers stay longer, spend more per hour "
         "(£8–15 vs £5–8 for a quick visit). A café of 40 seats with 15 regular remote "
         "workers on weekdays can add £300–600/week.",
         "£200–500/week"),
    ],
    "gastropub": [
        ("Develop the beer/drinks offer and wet sales %",
         "Gastropubs should be 45–55% wet sales. If your wet sales are below 35%, you are "
         "leaving significant GP on the table. Introduce a craft beer rotation, a focused "
         "cocktail menu (6 options is enough), and a premium wine by the glass range. "
         "Each 5% increase in wet sales % on £8,000 revenue = £400/week at higher GP.",
         "£400–1,000/week"),
        ("Sunday roast — pre-book, pre-sell, maximise",
         "Sunday is the highest-revenue day for gastropubs. Offer a pre-booked Sunday roast "
         "with deposits (reduces no-shows). Add a bottomless roast option at £38/head "
         "(food + unlimited roast potatoes, Yorkshire puddings, gravy, soft drinks). "
         "A fully booked Sunday at 60 covers = £1,500–2,200.",
         "£400–800/week uplift"),
        ("Quiz nights and weekly events",
         "A quiz night, pub games evening, or music night on a typically quiet Wednesday "
         "or Thursday can add 30–60 covers at £22+ average spend. Recurring events build "
         "habit — once a customer comes every Wednesday, they are worth £1,000+/year. "
         "Cost to host a quiz: £50–150 for a host.",
         "£600–1,200/week on the event night"),
        ("Activate outdoor space with heat lamps",
         "Each additional outdoor cover activated with heat lamps and weather protection "
         "adds £15–25 per service. 10 extra covers × 2 services/day × 5 months "
         "= approximately £15,000–25,000 in seasonal additional revenue. "
         "Heat lamp rental: £50–150/month.",
         "£300–600/week seasonal"),
        ("Private hire for functions and events",
         "Birthday parties, team events, wakes. A room hire fee of £200–500 + minimum F&B "
         "spend per head. Even 2 private hire bookings per month at £800 average total "
         "spend = £400/month in highly predictable, high-margin revenue.",
         "£200–600/week average"),
    ],
}

# Cost reduction quick wins per scenario
_COST_REDUCTION_TIPS = [
    ("Turn off delivery platforms during your quietest hours",
     "If 80% of your delivery orders come between 6–10pm, pause your Deliveroo/Uber Eats "
     "listing at lunchtime. This forces lunch delivery directly through your own website "
     "(0% commission vs 30%) and doesn't meaningfully reduce volume.\n"
     "   Saving: £50–200/week depending on volume."),
    ("Introduce a card-guarantee policy for peak bookings",
     "No-shows at 10% of bookings cost a 400-cover restaurant £58,000/year in lost revenue. "
     "A card-guarantee (charge £10/head if no-show with < 24 hours notice) reduces no-shows "
     "by 50–70%. Reservation systems like Resy and OpenTable support this natively.\n"
     "   Revenue recovered: £100–600/week."),
    ("Do a weekly stock-take, not monthly",
     "A monthly stock-take lets waste, over-portioning and theft run undetected for 4 weeks. "
     "Switching to weekly catches variances while they are small. 1–2 hours per week for "
     "a manager at £14/hour = £14–28/week cost vs potentially catching £100–400/week in "
     "controllable waste earlier.\n"
     "   Saving: £50–300/week."),
    ("Negotiate your energy contract via a broker",
     "When your business energy contract comes up for renewal, use an energy broker "
     "(Make It Cheaper, Utility Bidder, Bionic) to tender to multiple suppliers. "
     "Switching supplier at renewal can save 10–25% vs auto-renewing with the incumbent. "
     "On a £1,500/month energy bill, that is £150–375/month = £1,800–4,500/year.\n"
     "   Saving: £150–375/month."),
    ("Train staff to reduce over-portioning with a portion scale",
     "Over-portioning is invisible theft from your margin. A portion of chicken breast "
     "supposed to be 180g consistently plated at 220g = 22% food cost inflation on that "
     "dish. Introduce a portion scale and a one-week weighing exercise on your top 5 "
     "protein dishes. Typically saves 2–5% on those dishes' food cost.\n"
     "   Saving: £100–400/week depending on volume."),
    ("Hire an apprentice instead of a junior on full NMW",
     "Government apprenticeship co-investment means you pay 5% of the training cost, "
     "government pays 95%. Apprentice wages start at £6.40/hour vs adult NMW of £11.44+. "
     "A first-year apprentice commis chef doing 40 hours/week saves £200/week in wages "
     "vs an adult hire, PLUS free training, PLUS a £1,000 government incentive payment.\n"
     "   Saving: £150–250/week vs hiring adult staff."),
    ("Simplify your menu — cut your lowest-selling dishes",
     "Every menu item you remove reduces: ingredients to stock, prep sheets to run, "
     "training needed, and waste risk. A menu of 18–22 dishes has 20–30% lower "
     "food waste as a % of food cost than a 40+ dish menu. Identify the bottom 20% "
     "of dishes by sales count (log /menu sales weekly) and remove them in the next menu cycle.\n"
     "   Saving: £50–200/week in reduced waste."),
    ("Move repeat delivery customers to your own ordering channel",
     "Every customer who orders directly through your own website/phone costs you 0% "
     "commission vs 30% on Deliveroo. Add a 'Save 10% when ordering direct' flyer in "
     "every Deliveroo bag. Even converting 20% of delivery customers to direct saves "
     "significant commission.\n"
     "   Saving: £100–400/week depending on delivery volume."),
]


def format_revenue_growth_advisor(kpis: dict, restaurant_type: str,
                                   overhead_summary: dict = None,
                                   restaurant_name: str = "") -> str:
    """
    Personalised revenue growth and cost reduction advisor.
    Based on current KPIs vs UK benchmarks, gives specific, quantified actions.
    """
    rtype = restaurant_type if restaurant_type in BENCHMARKS else "casual"
    bench = BENCHMARKS[rtype]
    type_label = rtype.replace("qsr", "QSR / Fast Food").replace("cafe", "Café").title()

    lines = [f"GROWTH ADVISOR — {restaurant_name}", f"({type_label})", "═" * 40, ""]

    # ── Current snapshot ──────────────────────────────────────────────────────
    revenue   = kpis.get("revenue", 0)
    covers    = kpis.get("covers", 0)
    avg_spend = kpis.get("avg_spend_per_head", 0)
    food_pct  = kpis.get("food_cost_pct", 0)
    gp_pct    = kpis.get("gp_pct", 0)

    lines.append("YOUR CURRENT WEEK:")

    if revenue > 0:
        lines.append(f"  Revenue:      £{revenue:>8,.0f}")
    else:
        lines.append("  Revenue:      not logged yet")

    if covers > 0:
        cover_status = "✅" if covers >= bench["covers_week"] else "⚠️ below benchmark"
        lines.append(f"  Covers:       {covers:>8}  {cover_status}")
        lines.append(f"  Benchmark:    {bench['covers_week']:>8}  covers/week ({type_label})")
    else:
        lines.append("  Covers:       not logged yet")

    if avg_spend > 0:
        spend_status = "✅" if avg_spend >= bench["avg_spend"] * 0.95 else "⚠️"
        lines.append(f"  Avg spend:    £{avg_spend:>7,.2f}  {spend_status} (benchmark: £{bench['avg_spend']})")

    if food_pct > 0:
        fc_status = "✅" if food_pct <= bench["food_cost_pct"] else "⚠️ above target"
        lines.append(f"  Food cost:    {food_pct:>7.1f}%  {fc_status} (target: {bench['food_cost_pct']}%)")

    if gp_pct > 0:
        gp_status = "✅" if gp_pct >= bench["gp_pct"] else "⚠️"
        lines.append(f"  GP margin:    {gp_pct:>7.1f}%  {gp_status} (target: {bench['gp_pct']}%)")

    # ── Revenue gap ───────────────────────────────────────────────────────────
    lines.append("")
    lines.append("─" * 40)
    if revenue > 0 and covers > 0 and covers < bench["covers_week"]:
        cover_gap  = bench["covers_week"] - covers
        revenue_gap = cover_gap * (avg_spend if avg_spend > 0 else bench["avg_spend"])
        lines.append(f"REVENUE GAP: You are {cover_gap} covers/week below the {type_label}")
        lines.append(f"benchmark. At your current spend, that represents")
        lines.append(f"£{revenue_gap:,.0f}/week (£{revenue_gap*52:,.0f}/year) in potential revenue.")
    elif revenue == 0:
        lines.append("Log revenue entries daily to unlock your personalised gap analysis.")
    else:
        lines.append("Your cover count is at or above the benchmark — focus on")
        lines.append("increasing average spend and return visit rate.")

    # ── Top revenue opportunities ─────────────────────────────────────────────
    plays = _GROWTH_PLAYS.get(rtype, _GROWTH_PLAYS["casual"])
    lines.append("")
    lines.append("TOP 5 REVENUE OPPORTUNITIES:")
    lines.append("─" * 40)
    for i, (title, detail, potential) in enumerate(plays, 1):
        lines.append(f"{i}. {title.upper()}")
        lines.append(f"   Potential: {potential}")
        # Wrap detail at ~55 chars
        words = detail.split()
        current_line = "   "
        for word in words:
            if len(current_line) + len(word) + 1 > 57:
                lines.append(current_line)
                current_line = "   " + word
            else:
                current_line = current_line + (" " if current_line != "   " else "") + word
        if current_line.strip():
            lines.append(current_line)
        lines.append("")

    # ── Cost reduction quick wins ─────────────────────────────────────────────
    lines.append("TOP COST REDUCTION ACTIONS:")
    lines.append("─" * 40)

    # Prioritise tips based on what they have logged
    has_delivery = overhead_summary and any(
        "Commission" in sub or "Platform" in sub
        for cat in overhead_summary.values()
        for sub in cat.keys()
    )
    tips_to_show = _COST_REDUCTION_TIPS[:5]

    for i, (title, detail) in enumerate(tips_to_show, 1):
        lines.append(f"{i}. {title.upper()}")
        for detail_line in detail.split("\n"):
            words = detail_line.split()
            current_line = "   "
            for word in words:
                if len(current_line) + len(word) + 1 > 57:
                    lines.append(current_line)
                    current_line = "   " + word
                else:
                    current_line = current_line + (" " if current_line != "   " else "") + word
            if current_line.strip():
                lines.append(current_line)
        lines.append("")

    lines.append("═" * 40)
    lines.append("Update restaurant type: /targets type casual|fine|qsr|cafe|gastropub")
    lines.append("Log overheads:          /overhead")
    lines.append("Track no-shows:         /noshow 3")
    lines.append("Energy savings:         /energy tips")

    return "\n".join(lines)


# ─── No-show / cancellation analysis ─────────────────────────────────────────

def format_noshow_analysis(noshow_logs: list, summary: dict,
                            avg_spend: float = 0.0,
                            restaurant_name: str = "") -> str:
    """
    Show no-show rate, weekly revenue cost, annual projection, and solutions.
    """
    lines = [f"NO-SHOW TRACKER — {restaurant_name}", "─" * 36, ""]

    if not noshow_logs or not summary:
        lines.append("No no-shows logged yet.")
        lines.append("")
        lines.append("Log no-shows to see the revenue impact:")
        lines.append("  /noshow 3         (3 no-shows today)")
        lines.append("  /noshow 3 25      (3 no-shows from 25 booked)")
        lines.append("")
        lines.append("UK average: 5–15% of booked covers don't show.")
        lines.append("A 10% no-show rate on 400 covers/week =")
        lines.append("£58,000/year in lost revenue at £28 avg spend.")
        return "\n".join(lines)

    total_ns  = summary.get("total_noshows", 0)
    total_bk  = summary.get("total_booked", 0)
    ns_rate   = summary.get("noshow_rate_pct", 0)
    avg_daily = summary.get("avg_daily_noshows", 0)
    log_days  = summary.get("log_days", 1)

    lines.append(f"Logging period:    {log_days} days logged")
    lines.append(f"Total no-shows:    {total_ns:.0f} covers")
    if total_bk > 0:
        ns_flag = "✅ good" if ns_rate < 5 else ("⚠️ above target" if ns_rate < 10 else "🔴 act now")
        lines.append(f"Total booked:      {total_bk:.0f} covers")
        lines.append(f"No-show rate:      {ns_rate:.1f}%  {ns_flag}")
        lines.append(f"UK benchmark:      5–10% (uncharged bookings)")

    # Revenue impact
    if avg_spend > 0:
        weekly_ns     = avg_daily * 7
        weekly_lost   = weekly_ns * avg_spend
        annual_lost   = weekly_lost * 52
        lines.append("")
        lines.append("REVENUE IMPACT:")
        lines.append(f"  Avg spend/head:  £{avg_spend:.2f}")
        lines.append(f"  Est. weekly loss: £{weekly_lost:,.0f}")
        lines.append(f"  Est. annual loss: £{annual_lost:,.0f}")

        if annual_lost > 5000:
            lines.append("")
            lines.append("🔴 This is significant. Action recommended:")

    # Recommendations
    lines.append("")
    lines.append("HOW TO FIX THIS:")
    lines.append("")
    lines.append("1. CARD GUARANTEE (most effective)")
    lines.append("   Take card details at booking. Charge £10–15/head")
    lines.append("   for no-shows with < 24 hours notice. Reduces")
    lines.append("   no-shows by 50–70%. Use OpenTable, Resy or")
    lines.append("   ResDiary — all support this natively.")
    lines.append("")
    lines.append("2. SMS/EMAIL REMINDER (free, easy)")
    lines.append("   Automated reminder 48 hours before booking with")
    lines.append("   a cancellation link. Reduces no-shows by 30–50%")
    lines.append("   at near-zero cost. Most reservation systems")
    lines.append("   include this — make sure it's turned on.")
    lines.append("")
    lines.append("3. WAITLIST (fills freed tables)")
    lines.append("   A digital waitlist converts 40–60% of cancellations")
    lines.append("   into new bookings. Resy and SevenRooms do this well.")
    lines.append("")
    lines.append("4. DEPOSIT FOR PEAK DATES")
    lines.append("   For Christmas, Valentine's, NYE: take 100% pre-")
    lines.append("   payment. No-shows become zero. The guest has already")
    lines.append("   paid — it's just a question of whether they show up.")
    lines.append("")

    # Recent log
    lines.append("RECENT LOG:")
    for row in noshow_logs[:8]:
        bk_str = f"  (from {row['covers_booked']} booked)" if row["covers_booked"] else ""
        note   = f"  — {row['note']}" if row["note"] else ""
        lines.append(f"  {row['log_date']}  {row['covers_noshow']} no-shows{bk_str}{note}")

    lines.append("")
    lines.append("Log: /noshow 3        (3 no-shows today)")
    lines.append("Log: /noshow 3 25     (3 from 25 booked covers)")

    return "\n".join(lines)
