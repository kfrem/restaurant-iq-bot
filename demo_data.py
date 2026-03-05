"""
demo_data.py — Pre-built realistic restaurant data for client demos.

Used by /demo command in bot.py and by demo_setup.py standalone script.
All entries have pre-analysed JSON so no AI calls are needed during the demo.
"""

import json
from datetime import datetime, timedelta


def _monday() -> datetime:
    today = datetime.now()
    return today - timedelta(days=today.weekday())


def get_demo_entries() -> list[dict]:
    """
    Return a list of realistic entries for "The Golden Fork" covering Mon–Wed.
    Each dict has: day_offset, time, entry_type, raw_text, structured_data, category
    day_offset 0 = Monday, 1 = Tuesday, 2 = Wednesday
    """
    monday = _monday()

    def date(offset: int) -> str:
        return (monday + timedelta(days=offset)).strftime("%Y-%m-%d")

    return [
        # ── MONDAY ──────────────────────────────────────────────────────────
        {
            "entry_date": date(0),
            "entry_time": "09:15:00",
            "entry_type": "voice",
            "raw_text": (
                "Morning check-in from Jake. Delivery from Fresh Greens arrived "
                "but we're 20% short on romaine again — this is the third week running. "
                "Also the parsley looks wilted, not sure we can use it tonight. "
                "Called the rep, left a voicemail."
            ),
            "structured_data": json.dumps({
                "category": "supplier",
                "summary": "Fresh Greens delivered short on romaine (20%) and poor-quality parsley — third week running.",
                "urgency": "high",
                "supplier_mentions": ["Fresh Greens"],
                "waste_items": ["wilted parsley"],
                "action_needed": True,
                "complaints": [],
                "staff_issues": [],
                "revenue": None,
                "covers": None,
            }),
            "category": "supplier",
            "staff_name": "Jake",
        },
        {
            "entry_date": date(0),
            "entry_time": "10:30:00",
            "entry_type": "photo",
            "raw_text": "Invoice from Smithfield Meats — weekly meat delivery.",
            "structured_data": json.dumps({
                "document_type": "invoice",
                "supplier_name": "Smithfield Meats",
                "date": date(0),
                "total_amount": 342.50,
                "vat": 57.08,
                "items": [
                    {"description": "Ribeye steak 5kg", "quantity": 5, "unit": "kg", "unit_price": 28.00},
                    {"description": "Chicken breast fillet 10kg", "quantity": 10, "unit": "kg", "unit_price": 8.25},
                    {"description": "Lamb rack 3kg", "quantity": 3, "unit": "kg", "unit_price": 32.00},
                    {"description": "Beef mince 8kg", "quantity": 8, "unit": "kg", "unit_price": 6.50},
                ],
                "summary": "Weekly meat order from Smithfield — £342.50 inc VAT, up £28 vs last week.",
                "category": "cost",
            }),
            "category": "cost",
            "staff_name": "Jake",
        },
        {
            "entry_date": date(0),
            "entry_time": "15:20:00",
            "entry_type": "voice",
            "raw_text": (
                "Lunch wrap-up — 47 covers. Caesar salad flying out, ran out of croutons by 2pm "
                "and had to tell three tables we couldn't do it. Revenue around £1,240 for lunch. "
                "Table 7 asked for the chef to come out — really positive, they loved the new lamb dish."
            ),
            "structured_data": json.dumps({
                "category": "revenue",
                "summary": "Lunch 47 covers, £1,240 revenue. Ran out of croutons. Strong feedback on new lamb dish.",
                "urgency": "low",
                "revenue": 1240.0,
                "covers": 47,
                "items_86d": ["caesar salad (croutons ran out)"],
                "positive_notes": ["new lamb dish getting excellent guest feedback"],
                "action_needed": True,
                "complaints": [],
                "waste_items": [],
                "staff_issues": [],
                "supplier_mentions": [],
            }),
            "category": "revenue",
            "staff_name": "Sophie",
        },
        {
            "entry_date": date(0),
            "entry_time": "23:05:00",
            "entry_type": "voice",
            "raw_text": (
                "End of day Monday. Dinner service 68 covers, estimated £2,180 revenue. "
                "Had to 86 salmon by 8pm — caught us off guard. Table 12 complained their steak "
                "was overcooked, comped dessert, they were fine when they left. "
                "Marcus left early again, said he had a headache."
            ),
            "structured_data": json.dumps({
                "category": "revenue",
                "summary": "Dinner 68 covers, £2,180 revenue. Salmon 86'd at 8pm. One steak complaint comped. Marcus left early.",
                "urgency": "medium",
                "revenue": 2180.0,
                "covers": 68,
                "items_86d": ["salmon"],
                "complaints": ["overcooked steak — comped dessert"],
                "staff_issues": ["Marcus left shift early"],
                "action_needed": True,
                "positive_notes": [],
                "waste_items": [],
                "supplier_mentions": [],
            }),
            "category": "revenue",
            "staff_name": "Sophie",
        },

        # ── TUESDAY ─────────────────────────────────────────────────────────
        {
            "entry_date": date(1),
            "entry_time": "09:45:00",
            "entry_type": "text",
            "raw_text": "Wine delivery arrived from Berry Bros & Rudd — spring Burgundy selection and house whites. Invoice is £856.40.",
            "structured_data": json.dumps({
                "category": "cost",
                "summary": "Berry Bros & Rudd wine delivery — £856.40 for spring Burgundy selection and house whites.",
                "urgency": "low",
                "supplier_mentions": ["Berry Bros & Rudd"],
                "revenue": None,
                "covers": None,
                "action_needed": False,
                "complaints": [],
                "waste_items": [],
                "staff_issues": [],
                "items_86d": [],
                "positive_notes": [],
            }),
            "category": "cost",
            "staff_name": "Jake",
        },
        {
            "entry_date": date(1),
            "entry_time": "10:00:00",
            "entry_type": "photo",
            "raw_text": "Invoice from Berry Bros & Rudd — spring wine order.",
            "structured_data": json.dumps({
                "document_type": "invoice",
                "supplier_name": "Berry Bros & Rudd",
                "date": date(1),
                "total_amount": 856.40,
                "vat": 142.73,
                "items": [
                    {"description": "Burgundy Pinot Noir 2022 x12", "quantity": 12, "unit": "bottle", "unit_price": 24.50},
                    {"description": "Chablis Premier Cru 2023 x6", "quantity": 6, "unit": "bottle", "unit_price": 31.00},
                    {"description": "House Sauvignon Blanc x24", "quantity": 24, "unit": "bottle", "unit_price": 11.80},
                    {"description": "House Merlot x24", "quantity": 24, "unit": "bottle", "unit_price": 10.90},
                ],
                "summary": "Spring wine order — £856.40 inc VAT. New Burgundy selection + house wines restocked.",
                "category": "cost",
            }),
            "category": "cost",
            "staff_name": "Jake",
        },
        {
            "entry_date": date(1),
            "entry_time": "11:30:00",
            "entry_type": "voice",
            "raw_text": (
                "Marcus called in sick again — that's the third time this month. "
                "Had to pull Sophie from the kitchen to cover the floor for the full lunch service. "
                "Kitchen was short-handed as a result."
            ),
            "structured_data": json.dumps({
                "category": "staff",
                "summary": "Marcus called in sick (3rd time this month). Sophie pulled from kitchen to cover floor.",
                "urgency": "high",
                "staff_issues": ["Marcus — 3rd sick day this month", "Sophie had to leave kitchen to cover floor"],
                "action_needed": True,
                "complaints": [],
                "waste_items": [],
                "supplier_mentions": [],
                "revenue": None,
                "covers": None,
                "items_86d": [],
                "positive_notes": [],
            }),
            "category": "staff",
            "staff_name": "Jake",
        },
        {
            "entry_date": date(1),
            "entry_time": "15:45:00",
            "entry_type": "text",
            "raw_text": "Lunch was quiet — only 28 covers. Good opportunity for prep. Kitchen team got ahead on stocks and sauces for dinner.",
            "structured_data": json.dumps({
                "category": "revenue",
                "summary": "Quiet lunch, 28 covers. Kitchen used time for prep — stocks and sauces ready for dinner.",
                "urgency": "low",
                "covers": 28,
                "revenue": None,
                "action_needed": False,
                "complaints": [],
                "waste_items": [],
                "staff_issues": [],
                "supplier_mentions": [],
                "items_86d": [],
                "positive_notes": ["good prep opportunity — kitchen got ahead"],
            }),
            "category": "revenue",
            "staff_name": "Sophie",
        },
        {
            "entry_date": date(1),
            "entry_time": "23:15:00",
            "entry_type": "voice",
            "raw_text": (
                "Best dinner service this week — 72 covers, estimated £2,350 revenue. "
                "The new chicken supreme dish is getting incredible feedback, at least five tables "
                "specifically mentioned it to waiting staff. "
                "Sophie had a great night on the floor, multiple compliments from guests."
            ),
            "structured_data": json.dumps({
                "category": "revenue",
                "summary": "Excellent dinner — 72 covers, £2,350. New chicken supreme a standout hit. Sophie praised by multiple guests.",
                "urgency": "low",
                "revenue": 2350.0,
                "covers": 72,
                "positive_notes": [
                    "new chicken supreme dish — 5+ tables mentioned it",
                    "Sophie received multiple guest compliments",
                ],
                "action_needed": False,
                "complaints": [],
                "waste_items": [],
                "staff_issues": [],
                "supplier_mentions": [],
                "items_86d": [],
            }),
            "category": "revenue",
            "staff_name": "Sophie",
        },

        # ── WEDNESDAY ───────────────────────────────────────────────────────
        {
            "entry_date": date(2),
            "entry_time": "08:30:00",
            "entry_type": "text",
            "raw_text": "Gas bill arrived for last month — £1,240. That's up roughly 30% on the previous month. Worth reviewing the kitchen equipment usage.",
            "structured_data": json.dumps({
                "category": "cost",
                "summary": "Monthly gas bill £1,240 — 30% increase vs prior month. Kitchen equipment usage should be reviewed.",
                "urgency": "high",
                "action_needed": True,
                "complaints": [],
                "waste_items": [],
                "staff_issues": [],
                "supplier_mentions": [],
                "revenue": None,
                "covers": None,
                "items_86d": [],
                "positive_notes": [],
            }),
            "category": "cost",
            "staff_name": "Jake",
        },
        {
            "entry_date": date(2),
            "entry_time": "09:00:00",
            "entry_type": "voice",
            "raw_text": (
                "Morning walk-in check. Found 5kg of beef mince on the verge of going off — "
                "best before was today and it smells borderline. Used the whole lot for staff meal "
                "rather than risk it tonight. Need to review ordering quantities for mince, "
                "this is the second time in three weeks we've had to do this."
            ),
            "structured_data": json.dumps({
                "category": "waste",
                "summary": "5kg beef mince near expiry — used for staff meal. Second waste incident in 3 weeks. Review ordering quantities.",
                "urgency": "medium",
                "waste_items": ["5kg beef mince (near expiry)"],
                "action_needed": True,
                "complaints": [],
                "staff_issues": [],
                "supplier_mentions": [],
                "revenue": None,
                "covers": None,
                "items_86d": [],
                "positive_notes": [],
            }),
            "category": "waste",
            "staff_name": "Jake",
        },
        {
            "entry_date": date(2),
            "entry_time": "10:15:00",
            "entry_type": "photo",
            "raw_text": "Produce invoice from Fresh Greens — mid-week top-up delivery.",
            "structured_data": json.dumps({
                "document_type": "invoice",
                "supplier_name": "Fresh Greens Produce",
                "date": date(2),
                "total_amount": 234.80,
                "vat": 0.0,
                "items": [
                    {"description": "Romaine lettuce x20 heads", "quantity": 20, "unit": "head", "unit_price": 1.80},
                    {"description": "Cherry tomatoes 5kg", "quantity": 5, "unit": "kg", "unit_price": 4.20},
                    {"description": "Fresh herbs mixed 3kg", "quantity": 3, "unit": "kg", "unit_price": 12.00},
                    {"description": "Spinach 4kg", "quantity": 4, "unit": "kg", "unit_price": 5.60},
                    {"description": "Courgettes 6kg", "quantity": 6, "unit": "kg", "unit_price": 3.40},
                ],
                "summary": "Fresh Greens mid-week top-up — £234.80 (zero-rated). Full romaine delivery as replacement for Monday shortfall.",
                "category": "cost",
            }),
            "category": "cost",
            "staff_name": "Jake",
        },
        {
            "entry_date": date(2),
            "entry_time": "11:00:00",
            "entry_type": "voice",
            "raw_text": (
                "Dishwasher is making a loud grinding noise — started this morning. "
                "Chef thinks it might be the pump. Called maintenance, they can only come Friday. "
                "We're using the back-up glasswasher for now but it's slower and we'll struggle "
                "on a busy evening service."
            ),
            "structured_data": json.dumps({
                "category": "issue",
                "summary": "Dishwasher grinding noise — possible pump fault. Maintenance booked Friday. Back-up glasswasher in use.",
                "urgency": "high",
                "action_needed": True,
                "complaints": [],
                "waste_items": [],
                "staff_issues": [],
                "supplier_mentions": [],
                "revenue": None,
                "covers": None,
                "items_86d": [],
                "positive_notes": [],
            }),
            "category": "issue",
            "staff_name": "Sophie",
        },
        {
            "entry_date": date(2),
            "entry_time": "14:30:00",
            "entry_type": "text",
            "raw_text": "Just saw we got a new 5-star Google review from last night! Guest specifically mentioned the chicken supreme and called Sophie 'the best waitress we've had anywhere in London'. Brilliant.",
            "structured_data": json.dumps({
                "category": "general",
                "summary": "5-star Google review praising chicken supreme dish and Sophie by name — excellent guest experience.",
                "urgency": "low",
                "positive_notes": [
                    "5-star Google review received",
                    "Chicken supreme praised specifically",
                    "Sophie described as 'best waitress in London'",
                ],
                "action_needed": False,
                "complaints": [],
                "waste_items": [],
                "staff_issues": [],
                "supplier_mentions": [],
                "revenue": None,
                "covers": None,
                "items_86d": [],
            }),
            "category": "general",
            "staff_name": "Jake",
        },
    ]


DEMO_STAFF = [
    {"name": "Jake", "role": "owner"},
    {"name": "Sophie", "role": "staff"},
    {"name": "Marcus", "role": "staff"},
]
