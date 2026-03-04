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
    "marketing":  "MARKETING",
    "finance":    "FINANCE",
    "operations": "OPERATIONS",
    "admin":      "ADMIN",
}

# UK benchmark: overhead as % of revenue (excl. food & labour)
# Energy 3-5%, Occupancy 8-12%, Marketing 2-4%, Finance 1-2%, Operations 2-3%, Admin 1%
_OVERHEAD_BENCHMARKS = {
    "energy":     (3.0, 5.0),
    "occupancy":  (8.0, 12.0),
    "marketing":  (2.0, 4.0),
    "finance":    (1.0, 2.5),
    "operations": (1.5, 3.0),
    "admin":      (0.5, 1.5),
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
    category_order = ["energy", "occupancy", "marketing", "finance", "operations", "admin"]
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
