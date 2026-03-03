"""
subscription.py — Three-tier subscription model for Restaurant-IQ.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TIER 1 — Solo (£149/month)
  Fully automated Telegram bot intelligence.
  Best for: price-conscious owners comfortable with technology.
  Human involvement: none.
  1 location · All core bot commands · Weekly AI briefing + PDF

TIER 2 — Managed (£499/month)
  Bot + Flivio dashboard + a real human advisor.
  Best for: growing independents who want a sounding board.
  Human involvement: 2 hours/week analyst review.
  3 locations · Named advisor · Advisor-annotated weekly reports
  · Flivio dashboard access · Monthly 30-min check-in call

TIER 3 — Enterprise (£999/month)
  Full-service intelligence with dedicated advisory support.
  Best for: serious operators, groups, chef-owners scaling up.
  Human involvement: 4 hours/week + fortnightly scheduled call.
  10 locations · Dedicated analyst · Analyst attends to your data
  · Flivio full access · Supplier database · Custom integrations
  · Competitor benchmarking · Priority 24hr support
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

IMPORTANT DESIGN PRINCIPLE:
  Even Solo clients feel the human touch through personalised onboarding,
  a named founder message on first report, and upgrade paths that feel like
  gaining a real advisor — not just unlocking software features.
"""

from datetime import datetime, timedelta
from config import UPGRADE_URL

TRIAL_DAYS = 14

TIERS = {
    "solo": {
        "name":               "Solo",
        "price_gbp":          149,
        "locations":          1,
        "human_hours_week":   0,
        "flivio_access":      False,
        "supplier_db":        False,
        "calls_per_month":    0,
        "support_hours":      "5 business days",
        "features": {
            "compare":   True,
            "suppliers": True,
            "targets":   True,
            "benchmark": False,
            "findsupplier": False,
            "flivio":    False,
        },
        "pitch": (
            "Fully automated AI intelligence from your team's voice notes and invoices.\n"
            "Your bot works 24/7 — no staff training, no dashboards to log into.\n"
            "Weekly briefing + PDF every Monday at 08:00."
        ),
    },
    "managed": {
        "name":               "Managed",
        "price_gbp":          499,
        "locations":          3,
        "human_hours_week":   2,
        "flivio_access":      True,
        "supplier_db":        False,
        "calls_per_month":    1,
        "support_hours":      "48 hours",
        "features": {
            "compare":   True,
            "suppliers": True,
            "targets":   True,
            "benchmark": True,
            "findsupplier": False,
            "flivio":    True,
        },
        "pitch": (
            "Everything in Solo, plus a named restaurant advisor who reviews your data\n"
            "every week and adds their own commentary to your weekly report.\n"
            "A human who knows your business — not just a bot.\n"
            "Includes Flivio dashboard, 3 locations, and a monthly 30-min call."
        ),
    },
    "enterprise": {
        "name":               "Enterprise",
        "price_gbp":          999,
        "locations":          10,
        "human_hours_week":   4,
        "flivio_access":      True,
        "supplier_db":        True,
        "calls_per_month":    2,
        "support_hours":      "24 hours",
        "features": {
            "compare":   True,
            "suppliers": True,
            "targets":   True,
            "benchmark": True,
            "findsupplier": True,
            "flivio":    True,
        },
        "pitch": (
            "Your dedicated analyst works with you and your data every week.\n"
            "They access your POS, accounting and operational data directly —\n"
            "intelligence the bot alone cannot deliver.\n"
            "10 locations · fortnightly calls · supplier database ·\n"
            "custom integrations · priority 24hr support."
        ),
    },
}


def trial_days_remaining(restaurant) -> int:
    status = restaurant.get("subscription_status", "trial")
    if status not in (None, "trial"):
        return 0
    try:
        created = datetime.fromisoformat(
            str(restaurant.get("created_at", "")).replace(" ", "T")
        )
        trial_end = created + timedelta(days=TRIAL_DAYS)
        return max(0, (trial_end - datetime.now()).days)
    except (ValueError, AttributeError):
        return TRIAL_DAYS


def is_active(restaurant) -> bool:
    status = restaurant.get("subscription_status", "trial")
    if status == "active":
        return True
    if status in (None, "trial"):
        return trial_days_remaining(restaurant) > 0
    return False


def get_tier(restaurant) -> str:
    status = restaurant.get("subscription_status", "trial")
    if status in (None, "trial"):
        return "trial"
    return restaurant.get("subscription_tier") or "solo"


def get_tier_info(restaurant) -> dict:
    tier = get_tier(restaurant)
    if tier == "trial":
        # Trial gets Managed-level features to give full taste of the product
        return TIERS["managed"]
    return TIERS.get(tier, TIERS["solo"])


def has_feature(restaurant, feature: str) -> bool:
    if not is_active(restaurant):
        return False
    tier = get_tier(restaurant)
    if tier == "trial":
        return TIERS["managed"]["features"].get(feature, False)
    return TIERS.get(tier, TIERS["solo"])["features"].get(feature, False)


def has_human_advisor(restaurant) -> bool:
    """Return True if this tier includes a human advisor."""
    tier = get_tier(restaurant)
    if tier == "trial":
        return False  # Trial is bot-only to preserve analyst capacity
    return TIERS.get(tier, {}).get("human_hours_week", 0) > 0


def max_locations(restaurant) -> int:
    tier = get_tier(restaurant)
    if tier == "trial":
        return 1
    return TIERS.get(tier, TIERS["solo"])["locations"]


def trial_banner(restaurant) -> str:
    status = restaurant.get("subscription_status", "trial")
    if status == "active":
        return ""
    days = trial_days_remaining(restaurant)
    if days > 3:
        return f"\n\n─\n🔔 Free trial: {days} days remaining. {UPGRADE_URL}"
    if days > 0:
        return (
            f"\n\n─\n⚠️ Trial ends in {days} day{'s' if days != 1 else ''}! "
            f"Subscribe to keep your data: {UPGRADE_URL}"
        )
    return ""


def upgrade_prompt(restaurant) -> str:
    days = trial_days_remaining(restaurant)
    status = restaurant.get("subscription_status", "trial")
    tier = get_tier(restaurant)

    if status == "active":
        info = TIERS.get(tier, TIERS["solo"])
        return (
            f"You're on the {info['name']} plan (£{info['price_gbp']}/month).\n\n"
            + _tier_comparison_text()
            + f"\n\nUpgrade or manage your subscription: {UPGRADE_URL}"
        )

    header = (
        f"⚠️ Free trial ends in {days} day{'s' if days != 1 else ''}."
        if days > 0
        else "🔒 Your free trial has ended."
    )

    return (
        f"{header}\n\n"
        "Choose the right plan for your restaurant:\n\n"
        + _tier_comparison_text()
        + f"\n\nAll plans include 30-day money-back guarantee.\n{UPGRADE_URL}"
    )


def _tier_comparison_text() -> str:
    lines = []
    for info in TIERS.values():
        human_str = (
            f"{info['human_hours_week']}hrs/wk advisor"
            if info["human_hours_week"] > 0
            else "automated"
        )
        lines.append(
            f"  {info['name']} — £{info['price_gbp']}/month\n"
            f"  {info['locations']} location{'s' if info['locations'] > 1 else ''} · "
            f"{human_str} · {info['support_hours']} support\n"
            f"  {info['pitch'].split(chr(10))[0]}"
        )
    return "\n\n".join(lines)


def status_summary(restaurant) -> str:
    status = restaurant.get("subscription_status", "trial")
    if status == "active":
        tier = get_tier(restaurant)
        info = TIERS.get(tier, TIERS["solo"])
        human = f" · {info['human_hours_week']}hrs/wk advisor" if info["human_hours_week"] > 0 else ""
        return f"✅ {info['name']} plan — £{info['price_gbp']}/month{human}"
    days = trial_days_remaining(restaurant)
    if days > 0:
        return f"🔔 Free trial — {days} day{'s' if days != 1 else ''} remaining"
    return "🔒 Trial expired — subscription required"
