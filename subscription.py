"""
subscription.py — Subscription and trial management for Restaurant-IQ SaaS.

Pricing tiers (all GBP, billed monthly):
  Trial    — 14 days free, full access, no card required
  Starter  — £149/month  · 1 location
  Growth   — £399/month  · 3 locations  · premium features
  Pro      — £999/month  · 10 locations · full suite

Feature gating:
  All tiers get: /status /today /weeklyreport /history /export /deletedata
  Growth+:       /compare /suppliers /targets (week-on-week & supplier intelligence)
  Pro:           /benchmark (cross-network anonymised benchmarks)

Stripe handles billing; this module handles feature gating and trial tracking.
Set STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET in .env to enable live billing.
"""

from datetime import datetime, timedelta
from config import UPGRADE_URL

TRIAL_DAYS = 14

TIERS = {
    "starter": {
        "name":        "Starter",
        "price_gbp":   149,
        "locations":   1,
        "features":    {"compare": False, "suppliers": False, "targets": False, "benchmark": False},
        "description": "1 location · All core features · 90-day history",
    },
    "growth": {
        "name":        "Growth",
        "price_gbp":   399,
        "locations":   3,
        "features":    {"compare": True, "suppliers": True, "targets": True, "benchmark": False},
        "description": "3 locations · Week-on-week analysis · Supplier intelligence",
    },
    "pro": {
        "name":        "Pro",
        "price_gbp":   999,
        "locations":   10,
        "features":    {"compare": True, "suppliers": True, "targets": True, "benchmark": True},
        "description": "10 locations · Benchmarking · Priority support",
    },
}

# Trial and all paid tiers have access to base features
_BASE_FEATURES = {"compare": True, "suppliers": True, "targets": True, "benchmark": False}


def trial_days_remaining(restaurant) -> int:
    """Days remaining in free trial (0 if trial expired or not in trial)."""
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
        return TRIAL_DAYS  # Assume full trial if we can't parse


def is_active(restaurant) -> bool:
    """
    Return True if this restaurant has active access (trial or paid subscription).
    All features are locked once trial expires and no subscription exists.
    """
    status = restaurant.get("subscription_status", "trial")
    if status == "active":
        return True
    if status in (None, "trial"):
        return trial_days_remaining(restaurant) > 0
    return False


def get_tier(restaurant) -> str:
    """Return the current tier label: trial / starter / growth / pro."""
    status = restaurant.get("subscription_status", "trial")
    if status in (None, "trial"):
        return "trial"
    return restaurant.get("subscription_tier") or "starter"


def has_feature(restaurant, feature: str) -> bool:
    """
    Return True if this restaurant's tier includes the given feature.
    During trial, all features including Growth-level are available.
    """
    if not is_active(restaurant):
        return False
    tier = get_tier(restaurant)
    if tier == "trial":
        # Full access during trial — let them experience everything
        return _BASE_FEATURES.get(feature, False)
    return TIERS.get(tier, {}).get("features", {}).get(feature, False)


def max_locations(restaurant) -> int:
    """Maximum registered locations for this tier."""
    tier = get_tier(restaurant)
    if tier == "trial":
        return 1
    return TIERS.get(tier, {"locations": 1})["locations"]


def trial_banner(restaurant) -> str:
    """
    Short banner appended to command responses during trial.
    Returns empty string if paid subscription.
    """
    status = restaurant.get("subscription_status", "trial")
    if status == "active":
        return ""
    days_left = trial_days_remaining(restaurant)
    if days_left > 3:
        return f"\n\n─\n🔔 Free trial: {days_left} days remaining. {UPGRADE_URL}"
    if days_left > 0:
        return (
            f"\n\n─\n⚠️ Trial ends in {days_left} day{'s' if days_left != 1 else ''}! "
            f"Subscribe to keep your data and reports: {UPGRADE_URL}"
        )
    return ""


def upgrade_prompt(restaurant) -> str:
    """
    Full upgrade message shown when trial has expired or a feature is gated.
    """
    days_left = trial_days_remaining(restaurant)
    status = restaurant.get("subscription_status", "trial")

    if status == "active":
        tier = get_tier(restaurant)
        tier_info = TIERS.get(tier, {})
        return (
            f"You're on the {tier_info.get('name', tier.title())} plan "
            f"(£{tier_info.get('price_gbp', '?')}/month).\n"
            f"To upgrade, visit: {UPGRADE_URL}"
        )

    if days_left > 0:
        header = f"⚠️ Your free trial ends in {days_left} day{'s' if days_left != 1 else ''}."
    else:
        header = "🔒 Your free trial has ended."

    plans = "\n".join(
        f"  {info['name']} — £{info['price_gbp']}/month\n  {info['description']}"
        for info in TIERS.values()
    )

    return (
        f"{header}\n\n"
        "Choose a Restaurant-IQ plan to continue:\n\n"
        f"{plans}\n\n"
        f"Subscribe at: {UPGRADE_URL}\n"
        "All plans include a 30-day money-back guarantee."
    )


def status_summary(restaurant) -> str:
    """
    One-line subscription status for display in /status or /upgrade commands.
    """
    status = restaurant.get("subscription_status", "trial")
    if status == "active":
        tier = get_tier(restaurant)
        info = TIERS.get(tier, {})
        return f"✅ {info.get('name', tier.title())} plan — £{info.get('price_gbp', '?')}/month"
    days_left = trial_days_remaining(restaurant)
    if days_left > 0:
        return f"🔔 Free trial — {days_left} day{'s' if days_left != 1 else ''} remaining"
    return "🔒 Trial expired — subscription required"
