"""
supplier_db.py — UK Restaurant Supplier Directory for Restaurant-IQ.

This module powers the /findsupplier command and the automated supplier
alternative suggestions when price spikes are detected.

HOW IT WORKS:
  1. The directory is seeded with verified UK suppliers (below)
  2. Analysts can add new suppliers via /analyst supplier add
  3. When the bot detects a supplier price increase >10%, it queries
     this database for alternatives in the same category and region
  4. Enterprise clients get full directory access; others see top 3 results

BUILDING THE DATABASE OVER TIME:
  - Start with the seed data below (curated, manually verified)
  - Add suppliers as clients mention them in voice notes (analyst-verified)
  - Negotiate group buying rates for platform users at scale
  - This becomes a genuine competitive moat — a curated, trusted UK
    supplier network nobody else has access to

REGIONS USED:
  london | south-east | midlands | north-west | north-east |
  yorkshire | south-west | scotland | wales | uk-wide
"""

from database import _db


# ─── Seed data ────────────────────────────────────────────────────────────────
# Manually curated UK food suppliers. Add more over time.
# All entries are factual based on publicly available information.

SEED_SUPPLIERS = [
    # MEAT & POULTRY
    {
        "name": "Turner & George",
        "categories": ["meat", "poultry", "charcuterie"],
        "regions": ["london", "south-east"],
        "description": "Independent London butcher supplying restaurants since 2013. "
                       "Dry-aged beef, heritage pork, whole carcass butchery.",
        "website": "turnerandgeorge.co.uk",
        "min_order_gbp": 150,
        "delivery_days": "Mon-Fri",
        "verified": 1,
    },
    {
        "name": "Farmison & Co",
        "categories": ["meat", "poultry", "lamb"],
        "regions": ["yorkshire", "uk-wide"],
        "description": "Yorkshire-based premium butcher. Rare breed, pasture-fed. "
                       "Next-day delivery UK-wide.",
        "website": "farmison.com",
        "min_order_gbp": 75,
        "delivery_days": "Mon-Sat",
        "verified": 1,
    },
    {
        "name": "Aubrey Allen",
        "categories": ["meat", "poultry", "game"],
        "regions": ["midlands", "uk-wide"],
        "description": "Royal Warrant holders. Midlands-based, supplying fine dining "
                       "and quality casual restaurants across the UK since 1933.",
        "website": "aubreyallen.co.uk",
        "min_order_gbp": 200,
        "delivery_days": "Mon-Fri",
        "verified": 1,
    },

    # FISH & SEAFOOD
    {
        "name": "The Fish Society",
        "categories": ["fish", "seafood"],
        "regions": ["uk-wide"],
        "description": "Online fishmonger delivering restaurant-grade fish nationwide. "
                       "Overnight delivery, sustainable sourcing.",
        "website": "thefishsociety.co.uk",
        "min_order_gbp": 50,
        "delivery_days": "Mon-Sat",
        "verified": 1,
    },
    {
        "name": "Sealord UK",
        "categories": ["fish", "seafood"],
        "regions": ["uk-wide"],
        "description": "Large-scale sustainable seafood supplier. MSC certified. "
                       "Good for QSR and casual dining volume buyers.",
        "website": "sealord.co.uk",
        "min_order_gbp": 300,
        "delivery_days": "Mon-Fri",
        "verified": 1,
    },
    {
        "name": "Cornwall Fishmongers",
        "categories": ["fish", "seafood"],
        "regions": ["south-west", "london"],
        "description": "Day-boat fish direct from Cornish ports. "
                       "Overnight to London and South-West. Seasonal, traceable.",
        "website": "cornwallfishmongers.co.uk",
        "min_order_gbp": 100,
        "delivery_days": "Tue-Sat",
        "verified": 1,
    },

    # FRESH PRODUCE
    {
        "name": "New Covent Garden Market",
        "categories": ["produce", "fruit", "vegetables", "herbs"],
        "regions": ["london", "south-east"],
        "description": "London's wholesale market. Multiple traders. "
                       "Best for London operators wanting market-fresh produce at trade prices.",
        "website": "cgma.gov.uk",
        "min_order_gbp": 0,
        "delivery_days": "Mon-Sat (market open 2am-11am)",
        "verified": 1,
    },
    {
        "name": "Natoora",
        "categories": ["produce", "fruit", "vegetables", "herbs"],
        "regions": ["london", "south-east"],
        "description": "Premium seasonal produce, strong on Italian and European specialities. "
                       "Used by top London restaurants. Higher cost, exceptional quality.",
        "website": "natoora.co.uk",
        "min_order_gbp": 150,
        "delivery_days": "Mon-Sat",
        "verified": 1,
    },
    {
        "name": "Riverford Organic",
        "categories": ["produce", "fruit", "vegetables"],
        "regions": ["uk-wide"],
        "description": "Farm-to-chef organic produce. Nationwide delivery. "
                       "Fixed weekly boxes or flexible ordering. Strong sustainability story.",
        "website": "riverford.co.uk",
        "min_order_gbp": 50,
        "delivery_days": "Mon-Sat",
        "verified": 1,
    },

    # DAIRY
    {
        "name": "Ivy House Farm",
        "categories": ["dairy", "milk", "cream", "butter"],
        "regions": ["south-west", "uk-wide"],
        "description": "Somerset organic dairy. Pasteurised and unhomogenised milk, "
                       "cream, butter. Supplied to restaurants and delis nationwide.",
        "website": "ivyhousefarm.co.uk",
        "min_order_gbp": 80,
        "delivery_days": "Mon, Wed, Fri",
        "verified": 1,
    },
    {
        "name": "The Fine Cheese Co.",
        "categories": ["dairy", "cheese"],
        "regions": ["south-west", "london", "uk-wide"],
        "description": "Bath-based cheese specialist. UK and continental cheeses "
                       "for restaurant boards and menus. Excellent cheesemonger support.",
        "website": "finecheese.co.uk",
        "min_order_gbp": 100,
        "delivery_days": "Mon-Fri",
        "verified": 1,
    },

    # DRY GOODS & WHOLESALE
    {
        "name": "Brakes",
        "categories": ["dry goods", "frozen", "chilled", "packaging", "cleaning"],
        "regions": ["uk-wide"],
        "description": "UK's largest foodservice wholesaler. Full range from "
                       "ingredients to packaging. Competitive on volume. "
                       "Good for operators wanting one-supplier simplicity.",
        "website": "brake.co.uk",
        "min_order_gbp": 250,
        "delivery_days": "Mon-Sat",
        "verified": 1,
    },
    {
        "name": "Booker Wholesale",
        "categories": ["dry goods", "beverages", "frozen", "chilled"],
        "regions": ["uk-wide"],
        "description": "National cash & carry and delivered wholesale. "
                       "Competitive pricing for dry goods, beverages, and ambient products. "
                       "Good value for independent restaurants.",
        "website": "booker.co.uk",
        "min_order_gbp": 0,
        "delivery_days": "Mon-Sat",
        "verified": 1,
    },
    {
        "name": "Sous Chef",
        "categories": ["dry goods", "speciality", "spices", "condiments"],
        "regions": ["uk-wide"],
        "description": "Specialist ingredients for professional chefs. "
                       "Hard-to-source items: fermented, cured, speciality grains. "
                       "Used widely across fine dining and modern casual.",
        "website": "souschef.co.uk",
        "min_order_gbp": 40,
        "delivery_days": "Mon-Fri",
        "verified": 1,
    },

    # BEVERAGES
    {
        "name": "Enotria & Coe",
        "categories": ["beverages", "wine", "spirits"],
        "regions": ["london", "south-east", "uk-wide"],
        "description": "Independent wine merchant supplying London restaurants since 1972. "
                       "Strong on European wines, knowledgeable sales team.",
        "website": "enotria.co.uk",
        "min_order_gbp": 200,
        "delivery_days": "Mon-Fri",
        "verified": 1,
    },
    {
        "name": "Matthew Clark",
        "categories": ["beverages", "wine", "beer", "spirits", "soft drinks"],
        "regions": ["uk-wide"],
        "description": "Bibendum Wine owner. Full drinks range for the on-trade. "
                       "National coverage, competitive volume pricing.",
        "website": "matthewclark.co.uk",
        "min_order_gbp": 250,
        "delivery_days": "Mon-Fri",
        "verified": 1,
    },
    {
        "name": "Speciality Drinks",
        "categories": ["beverages", "spirits", "cocktail"],
        "regions": ["london", "uk-wide"],
        "description": "Premium and artisan spirits for cocktail bars and fine dining. "
                       "Wide range of niche labels not available through mainstream wholesalers.",
        "website": "specialitydrinks.com",
        "min_order_gbp": 150,
        "delivery_days": "Mon-Fri",
        "verified": 1,
    },

    # PACKAGING & DISPOSABLES
    {
        "name": "Vegware",
        "categories": ["packaging", "disposables"],
        "regions": ["uk-wide"],
        "description": "Plant-based compostable packaging. Used by restaurants wanting "
                       "to reduce single-use plastic. Full range from cups to takeaway containers.",
        "website": "vegware.com",
        "min_order_gbp": 50,
        "delivery_days": "Mon-Fri",
        "verified": 1,
    },
]


# ─── DB helpers ───────────────────────────────────────────────────────────────

def seed_suppliers():
    """Insert seed suppliers if the table is empty."""
    with _db() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) as n FROM supplier_directory")
        if c.fetchone()["n"] > 0:
            return  # Already seeded

        for s in SEED_SUPPLIERS:
            conn.execute(
                """INSERT INTO supplier_directory
                   (name, categories, regions, description, website,
                    min_order_gbp, delivery_days, verified)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    s["name"],
                    ",".join(s["categories"]),
                    ",".join(s["regions"]),
                    s["description"],
                    s.get("website", ""),
                    s.get("min_order_gbp", 0),
                    s.get("delivery_days", ""),
                    s.get("verified", 0),
                ),
            )
        conn.commit()
    print(f"Supplier directory seeded with {len(SEED_SUPPLIERS)} suppliers.")


def search_suppliers(query: str, region: str = None, limit: int = 5) -> list:
    """
    Search the supplier directory by category keyword and optional region.
    query: e.g. "chicken", "fish", "dairy", "wine"
    region: e.g. "london", "north-west" (optional filter)
    Returns list of supplier rows.
    """
    query_lower = query.lower().strip()
    with _db() as conn:
        c = conn.cursor()
        if region:
            region_lower = region.lower().strip()
            c.execute(
                """SELECT * FROM supplier_directory
                   WHERE (LOWER(categories) LIKE ? OR LOWER(name) LIKE ? OR LOWER(description) LIKE ?)
                   AND (LOWER(regions) LIKE ? OR LOWER(regions) LIKE '%uk-wide%')
                   ORDER BY verified DESC, name ASC
                   LIMIT ?""",
                (f"%{query_lower}%", f"%{query_lower}%", f"%{query_lower}%",
                 f"%{region_lower}%", limit),
            )
        else:
            c.execute(
                """SELECT * FROM supplier_directory
                   WHERE LOWER(categories) LIKE ?
                      OR LOWER(name) LIKE ?
                      OR LOWER(description) LIKE ?
                   ORDER BY verified DESC, name ASC
                   LIMIT ?""",
                (f"%{query_lower}%", f"%{query_lower}%", f"%{query_lower}%", limit),
            )
        return c.fetchall()


def get_alternatives_for_supplier(supplier_name: str, category: str,
                                   region: str = None, limit: int = 3) -> list:
    """
    Find alternative suppliers for a given category, excluding the current supplier.
    Used when price increases are detected.
    """
    results = search_suppliers(category, region=region, limit=limit + 2)
    return [r for r in results if r["name"].lower() != supplier_name.lower()][:limit]


def add_supplier(name: str, categories: list, regions: list,
                  description: str, website: str = "",
                  min_order_gbp: float = 0, delivery_days: str = "",
                  verified: int = 0) -> int:
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """INSERT INTO supplier_directory
               (name, categories, regions, description, website,
                min_order_gbp, delivery_days, verified)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, ",".join(categories), ",".join(regions),
             description, website, min_order_gbp, delivery_days, verified),
        )
        conn.commit()
        return c.lastrowid


def format_supplier_results(suppliers: list, max_show: int = 3,
                              is_enterprise: bool = False) -> str:
    """Format supplier search results for a Telegram message."""
    if not suppliers:
        return "No suppliers found matching your search."

    display = suppliers[:max_show] if not is_enterprise else suppliers
    lines = []
    for s in display:
        verified_badge = " ✅ Verified" if s["verified"] else ""
        min_order = f"Min order: £{s['min_order_gbp']:.0f}" if s["min_order_gbp"] else ""
        lines.append(
            f"  {s['name']}{verified_badge}\n"
            f"  {s['description'][:120]}…\n"
            f"  {s['website']}  ·  {min_order}  ·  {s['delivery_days']}\n"
        )

    result = "\n".join(lines)
    if not is_enterprise and len(suppliers) > max_show:
        result += f"\n+{len(suppliers) - max_show} more results — upgrade to Enterprise for full access."
    return result


def format_price_alert_with_alternatives(supplier_name: str, item_name: str,
                                          change_pct: float, region: str,
                                          category: str) -> str:
    """
    Format a price alert message with suggested alternatives.
    Called when a price increase >=10% is detected on an invoice.
    """
    alternatives = get_alternatives_for_supplier(supplier_name, category, region, limit=2)
    alt_text = ""
    if alternatives:
        names = " / ".join(a["name"] for a in alternatives)
        alt_text = f"\n  💡 Alternatives to consider: {names}"
    return (
        f"⚠️ Price alert: {supplier_name} — {item_name} up {change_pct:+.1f}%{alt_text}"
    )
