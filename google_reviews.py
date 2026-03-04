"""
google_reviews.py — Google Places review monitoring for Restaurant-IQ.

Checks each restaurant's Google listing for new negative reviews and
sends an instant Telegram alert so owners can respond quickly.

Setup for a client:
  1. The restaurant owner types: /setplace <Google Place ID>
  2. The bot stores the Place ID and starts monitoring every hour

How to find a Google Place ID:
  • Go to Google Maps → search for the restaurant
  • Click Share → the URL contains the Place ID after "place/"
  • Or use: https://developers.google.com/maps/documentation/places/web-service/place-id

API used: Google Places Details (same GOOGLE_API_KEY as vision analysis)
Note: The Places API returns the 5 most recent reviews. We track the
      timestamp of the newest seen review to detect new ones.
"""

import logging

import requests

from config import GOOGLE_API_KEY

logger = logging.getLogger(__name__)

_PLACES_URL = "https://maps.googleapis.com/maps/api/place/details/json"


def get_recent_reviews(place_id: str) -> list:
    """
    Fetch up to 5 recent reviews for a Google Place.
    Returns a list of review dicts, or [] on any error.
    Each dict has: rating (int), text (str), author_name (str), time (int unix timestamp)
    """
    if not GOOGLE_API_KEY or not place_id:
        return []

    try:
        resp = requests.get(
            _PLACES_URL,
            params={
                "place_id":     place_id,
                "fields":       "reviews,name,rating",
                "key":          GOOGLE_API_KEY,
                "reviews_sort": "newest",
                "language":     "en",
            },
            timeout=10,
        )
        data = resp.json()

        if data.get("status") != "OK":
            logger.warning(
                f"Google Places API status: {data.get('status')} — "
                f"{data.get('error_message', 'no message')}"
            )
            return []

        return data.get("result", {}).get("reviews", [])

    except Exception as e:
        logger.error(f"Google Places review fetch failed for place {place_id}: {e}")
        return []


def get_new_reviews(place_id: str, since_timestamp: int) -> list:
    """
    Return reviews posted after `since_timestamp` (Unix timestamp).
    Only returns reviews with rating <= 3 (negative/mixed) as those need urgent action.
    """
    reviews = get_recent_reviews(place_id)
    new_negative = [
        r for r in reviews
        if r.get("time", 0) > since_timestamp and r.get("rating", 5) <= 3
    ]
    return sorted(new_negative, key=lambda r: r.get("time", 0))


def get_all_new_reviews(place_id: str, since_timestamp: int) -> list:
    """Return ALL new reviews (any rating) since the timestamp."""
    reviews = get_recent_reviews(place_id)
    return sorted(
        [r for r in reviews if r.get("time", 0) > since_timestamp],
        key=lambda r: r.get("time", 0),
    )


def format_review_alert(review: dict, restaurant_name: str) -> str:
    """Format a review as a Telegram alert message."""
    rating     = int(review.get("rating", 0))
    stars      = "⭐" * rating + "☆" * (5 - rating)
    author     = review.get("author_name", "Anonymous")
    text       = (review.get("text") or "No review text").strip()[:400]
    urgency    = "🔴" if rating <= 2 else "🟡"

    draft_hint = (
        "\n\n💡 Suggested response: Acknowledge the experience, "
        "apologise sincerely, invite them to contact you directly to resolve it."
        if rating <= 3 else ""
    )

    return (
        f"{urgency} NEW GOOGLE REVIEW — {restaurant_name}\n"
        f"{'─' * 34}\n"
        f"Rating: {stars} ({rating}/5)\n"
        f"From: {author}\n\n"
        f'"{text}"'
        f"{draft_hint}\n\n"
        f"Respond on Google Maps to show other customers you care."
    )


def places_api_enabled() -> bool:
    """Return True if Google API key is configured (same key used for vision)."""
    return bool(GOOGLE_API_KEY)
