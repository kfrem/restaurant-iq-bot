"""
stripe_webhook.py — Flask HTTP server that receives Stripe payment events.

Stripe calls this server automatically when:
  - A client successfully pays       → activate their subscription
  - A subscription is cancelled      → mark as expired
  - A payment fails (card declined)  → notify the restaurant owner

This server runs in a background thread alongside the Telegram bot.
It listens on port 8080 (or WEBHOOK_PORT in your .env).

To expose it to the internet for Stripe to reach it, you need either:
  • Railway / Render hosting  (recommended — covered in setup guide)
  • ngrok for local testing   (ngrok http 8080)
"""

import logging
import threading

import requests
import stripe
from flask import Flask, request, jsonify

from config import (
    STRIPE_SECRET_KEY,
    STRIPE_WEBHOOK_SECRET,
    TELEGRAM_BOT_TOKEN,
    WEBHOOK_PORT,
)
from database import get_all_restaurants, update_subscription

logger = logging.getLogger(__name__)

flask_app = Flask(__name__)


# ── Stripe event handler ───────────────────────────────────────────────────────

@flask_app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    """Receive and verify a Stripe webhook event, then process it."""
    payload   = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")

    # Verify the request actually came from Stripe (not someone faking it)
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except stripe.error.SignatureVerificationError:
        logger.warning("Stripe webhook: invalid signature — request rejected")
        return jsonify({"error": "Invalid signature"}), 400
    except Exception as e:
        logger.error(f"Stripe webhook: error parsing event — {e}")
        return jsonify({"error": "Bad request"}), 400

    _handle_event(event)
    return jsonify({"status": "ok"}), 200


@flask_app.route("/health", methods=["GET"])
def health():
    """Simple health check so you can confirm the server is running."""
    return jsonify({"status": "ok", "service": "restaurant-iq-webhook"}), 200


# ── Event processing ───────────────────────────────────────────────────────────

def _handle_event(event: dict):
    """Route each Stripe event type to the correct handler."""
    event_type = event["type"]
    data       = event["data"]["object"]

    logger.info(f"Stripe event received: {event_type}")

    if event_type == "checkout.session.completed":
        _on_checkout_completed(data)

    elif event_type in ("customer.subscription.deleted", "customer.subscription.paused"):
        _on_subscription_cancelled(data)

    elif event_type == "invoice.payment_failed":
        _on_payment_failed(data)

    else:
        logger.debug(f"Stripe event ignored (not handled): {event_type}")


def _on_checkout_completed(session: dict):
    """Client successfully paid — activate their subscription."""
    metadata      = session.get("metadata") or {}
    restaurant_id = metadata.get("restaurant_id")
    tier          = metadata.get("tier", "solo")
    owner_tg_id   = metadata.get("owner_telegram_id")
    stripe_cust   = session.get("customer")

    if not restaurant_id:
        logger.error("checkout.session.completed: no restaurant_id in metadata")
        return

    update_subscription(
        int(restaurant_id),
        status="active",
        tier=tier,
        stripe_customer_id=stripe_cust,
    )
    logger.info(f"Activated '{tier}' subscription for restaurant ID {restaurant_id}")

    # Notify the restaurant owner in Telegram
    if owner_tg_id:
        from subscription import TIERS
        info = TIERS.get(tier, TIERS["solo"])
        _send_telegram_message(
            owner_tg_id,
            f"Payment received — thank you!\n\n"
            f"Your *{info['name']} plan* is now active.\n"
            f"£{info['price_gbp']}/month · {info['locations']} location(s)\n\n"
            f"Everything is set up. Just keep sending voice notes, photos, "
            f"and texts as normal — your weekly briefing will arrive every Monday at 08:00.",
        )


def _on_subscription_cancelled(subscription: dict):
    """Subscription was cancelled or paused — mark restaurant as expired."""
    stripe_cust = subscription.get("customer")
    if not stripe_cust:
        return

    restaurants = get_all_restaurants()
    for r in restaurants:
        if r["stripe_customer_id"] == stripe_cust:
            update_subscription(r["id"], status="expired")
            logger.info(f"Deactivated subscription for restaurant ID {r['id']}")

            # Notify owner
            owner_tg_id = r.get("owner_telegram_id")
            if owner_tg_id:
                _send_telegram_message(
                    owner_tg_id,
                    "Your Restaurant-IQ subscription has been cancelled.\n\n"
                    "Your data is safe. To reactivate, type /upgrade in the bot.",
                )
            break


def _on_payment_failed(invoice: dict):
    """Card payment failed — warn the owner so they can update their card."""
    stripe_cust = invoice.get("customer")
    if not stripe_cust:
        return

    restaurants = get_all_restaurants()
    for r in restaurants:
        if r["stripe_customer_id"] == stripe_cust:
            owner_tg_id = r.get("owner_telegram_id")
            if owner_tg_id:
                _send_telegram_message(
                    owner_tg_id,
                    "Payment failed — your Restaurant-IQ subscription could not be renewed.\n\n"
                    "Please update your payment card to avoid losing access.\n"
                    "Type /upgrade to see your options.",
                )
            break


# ── Telegram notification helper ──────────────────────────────────────────────

def _send_telegram_message(telegram_user_id: str, text: str):
    """Send a Telegram message directly via the Bot API (no asyncio needed)."""
    if not TELEGRAM_BOT_TOKEN:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id":    telegram_user_id,
                "text":       text,
                "parse_mode": "Markdown",
            },
            timeout=10,
        )
    except Exception as e:
        logger.error(f"Failed to send Telegram notification to {telegram_user_id}: {e}")


# ── Server startup ─────────────────────────────────────────────────────────────

def start_webhook_server():
    """
    Start the Flask webhook server in a background thread.
    Called from bot.py main() when STRIPE_SECRET_KEY is configured.
    """
    stripe.api_key = STRIPE_SECRET_KEY

    def _run():
        # Silence Flask's default logger to keep the console clean
        import logging as _logging
        _logging.getLogger("werkzeug").setLevel(_logging.WARNING)
        flask_app.run(host="0.0.0.0", port=WEBHOOK_PORT, debug=False, use_reloader=False)

    thread = threading.Thread(target=_run, daemon=True, name="stripe-webhook")
    thread.start()
    logger.info(f"Stripe webhook server started on port {WEBHOOK_PORT} — POST /stripe/webhook")
    return thread
