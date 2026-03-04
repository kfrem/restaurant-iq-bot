"""
stripe_payments.py — Stripe Checkout session creation for Restaurant-IQ.

Called by bot.py when a client types /upgrade and wants to pay.
Creates a hosted Stripe Checkout page and returns the URL.
"""

import logging

import stripe

from config import (
    STRIPE_SECRET_KEY,
    STRIPE_SOLO_PRICE_ID,
    STRIPE_MANAGED_PRICE_ID,
    STRIPE_ENTERPRISE_PRICE_ID,
    UPGRADE_URL,
)

logger = logging.getLogger(__name__)

# Map tier names to Stripe Price IDs (set in .env)
_PRICE_IDS = {
    "solo":       STRIPE_SOLO_PRICE_ID,
    "managed":    STRIPE_MANAGED_PRICE_ID,
    "enterprise": STRIPE_ENTERPRISE_PRICE_ID,
}


def stripe_enabled() -> bool:
    """Return True if Stripe is configured and all three price IDs are set."""
    return bool(
        STRIPE_SECRET_KEY
        and STRIPE_SOLO_PRICE_ID
        and STRIPE_MANAGED_PRICE_ID
        and STRIPE_ENTERPRISE_PRICE_ID
    )


def create_checkout_url(tier: str, restaurant_id: int, owner_telegram_id: str) -> str:
    """
    Create a Stripe Checkout session for the given tier and return the payment URL.

    Parameters
    ----------
    tier               : "solo", "managed", or "enterprise"
    restaurant_id      : the restaurant's database ID (stored in Stripe metadata)
    owner_telegram_id  : the owner's Telegram user ID (so we know who to notify)

    Returns
    -------
    The Stripe-hosted payment page URL (valid for 24 hours).
    """
    if not STRIPE_SECRET_KEY:
        raise RuntimeError("STRIPE_SECRET_KEY is not set in .env")

    price_id = _PRICE_IDS.get(tier)
    if not price_id:
        raise ValueError(
            f"No Stripe Price ID configured for tier '{tier}'. "
            f"Set STRIPE_{tier.upper()}_PRICE_ID in your .env file."
        )

    stripe.api_key = STRIPE_SECRET_KEY

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        # After payment: bot will notify via webhook; these are fallback URLs
        success_url=UPGRADE_URL + "?success=1",
        cancel_url=UPGRADE_URL + "?cancel=1",
        metadata={
            "restaurant_id":     str(restaurant_id),
            "owner_telegram_id": str(owner_telegram_id),
            "tier":              tier,
        },
        # Pre-fill subscription metadata so the webhook can identify the restaurant
        subscription_data={
            "metadata": {
                "restaurant_id":     str(restaurant_id),
                "owner_telegram_id": str(owner_telegram_id),
                "tier":              tier,
            }
        },
    )

    logger.info(
        f"Created Stripe checkout session {session.id} "
        f"for restaurant {restaurant_id} tier={tier}"
    )
    return session.url
