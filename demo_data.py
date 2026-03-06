"""
demo_data.py — Pre-built realistic restaurant data for client demos.

Used by /demo command in bot.py and by demo_setup.py standalone script.
All entries have pre-analysed JSON so no AI calls are needed during the demo.

Covers a full Mon–Sun week with 40+ entries across all 7 categories:
  revenue, cost, waste, staff, supplier, issue, general

Storylines running through the week:
  - Supplier: Fresh Greens keeps delivering short → switched to City Farm
  - Staff: Marcus performance issues → improvement after honest conversation
  - Equipment: Dishwasher fault Wed → repaired Friday
  - Revenue: Builds Mon–Sat, peaking at record Friday & Saturday dinner
  - Cost: Gas bill spike, meat price rises, dishwasher repair bill
  - Waste: Recurring beef mince over-ordering → quantities adjusted
  - Customer: TripAdvisor complaint about slow service → floor plan fix
  - Positive: New lamb dish going viral, Sophie's 1-year anniversary
"""

import json
from datetime import datetime, timedelta


def _monday() -> datetime:
    today = datetime.now()
    return today - timedelta(days=today.weekday())


def get_demo_entries() -> list[dict]:
    """
    Return 40+ realistic entries for "The Golden Fork" covering Mon–Sun.
    day_offset: 0=Monday … 6=Sunday.
    All structured_data is pre-analysed so no AI calls are made during demo.
    """
    monday = _monday()

    def date(offset: int) -> str:
        return (monday + timedelta(days=offset)).strftime("%Y-%m-%d")

    return [

        # ══════════════════════════════════════════════════════════════════════
        # MONDAY — Slow start, supplier issues, Marcus late
        # ══════════════════════════════════════════════════════════════════════

        {
            "entry_date": date(0),
            "entry_time": "08:45:00",
            "entry_type": "voice",
            "raw_text": (
                "Morning delivery check. Fresh Greens arrived but we're short again — "
                "romaine is 25% under and the courgettes are soft and unusable. "
                "That's four weeks running now. I've called the rep twice, left voicemails, "
                "nothing. We're going to have to find a new produce supplier this week."
            ),
            "structured_data": json.dumps({
                "category": "supplier",
                "summary": "Fresh Greens short 25% on romaine, unusable courgettes — fourth consecutive week. Rep unresponsive. Need new supplier.",
                "urgency": "high",
                "supplier_mentions": ["Fresh Greens"],
                "waste_items": ["soft courgettes (unusable)"],
                "action_needed": True,
                "complaints": [],
                "staff_issues": [],
                "revenue": None,
                "covers": None,
                "items_86d": [],
                "positive_notes": [],
            }),
            "category": "supplier",
            "staff_name": "Jake",
        },
        {
            "entry_date": date(0),
            "entry_time": "09:30:00",
            "entry_type": "photo",
            "raw_text": "Smithfield Meats weekly invoice — Monday delivery.",
            "structured_data": json.dumps({
                "document_type": "invoice",
                "supplier_name": "Smithfield Meats",
                "date": date(0),
                "total_amount": 368.00,
                "vat": 61.33,
                "items": [
                    {"name": "Ribeye steak 5kg", "quantity": 5, "unit": "kg", "unit_price": 29.50, "total": 147.50},
                    {"name": "Chicken breast fillet 10kg", "quantity": 10, "unit": "kg", "unit_price": 8.50, "total": 85.00},
                    {"name": "Lamb rack 3kg", "quantity": 3, "unit": "kg", "unit_price": 33.00, "total": 99.00},
                    {"name": "Beef mince 8kg", "quantity": 8, "unit": "kg", "unit_price": 4.56, "total": 36.50},
                ],
                "summary": "Smithfield Meats weekly meat order £368.00 inc VAT — up £25.50 vs last week. Ribeye +£1.50/kg.",
                "category": "cost",
                "urgency": "medium",
            }),
            "category": "cost",
            "staff_name": "Jake",
        },
        {
            "entry_date": date(0),
            "entry_time": "11:15:00",
            "entry_type": "text",
            "raw_text": (
                "Marcus just arrived — 45 minutes late. Said his alarm didn't go off. "
                "This is the third time in three weeks. No call ahead either. "
                "Jake is dealing with it but we had to start prep short-handed."
            ),
            "structured_data": json.dumps({
                "category": "staff",
                "summary": "Marcus 45 minutes late — third time in 3 weeks, no advance notice. Prep started short-handed.",
                "urgency": "medium",
                "staff_issues": ["Marcus arrived 45 min late (3rd time in 3 weeks)", "No advance notice given"],
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
            "staff_name": "Sophie",
        },
        {
            "entry_date": date(0),
            "entry_time": "15:10:00",
            "entry_type": "voice",
            "raw_text": (
                "Lunch wrap-up — 42 covers, revenue around £1,180. "
                "Quieter than normal for a Monday. Caesar salad still flying, "
                "new lamb dish got four orders and every table gave it rave reviews. "
                "We had to sub courgettes in the vegetable tian with squash — worked fine. "
                "No complaints."
            ),
            "structured_data": json.dumps({
                "category": "revenue",
                "summary": "Quiet Monday lunch, 42 covers, £1,180. Lamb dish strong (4 orders, rave reviews). Courgette substitution handled well.",
                "urgency": "low",
                "revenue": 1180.0,
                "covers": 42,
                "items_86d": [],
                "positive_notes": ["new lamb dish — 4 orders, all tables praised it"],
                "action_needed": False,
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
            "entry_time": "23:00:00",
            "entry_type": "voice",
            "raw_text": (
                "End of Monday. Dinner 65 covers, estimated £2,050 revenue. "
                "Solid service, no major issues. One table of eight ran late and held "
                "the table 20 minutes — worth noting for reservations management. "
                "Salmon ran out by 9pm again — need to increase the order. "
                "Marcus was fine once he got going, kitchen ran smoothly."
            ),
            "structured_data": json.dumps({
                "category": "revenue",
                "summary": "Monday dinner 65 covers, £2,050. Salmon 86'd by 9pm. Large table ran over. Kitchen ran well despite late start.",
                "urgency": "low",
                "revenue": 2050.0,
                "covers": 65,
                "items_86d": ["salmon (ran out by 9pm)"],
                "complaints": [],
                "positive_notes": ["kitchen ran smoothly after Marcus arrived"],
                "action_needed": True,
                "waste_items": [],
                "staff_issues": [],
                "supplier_mentions": [],
            }),
            "category": "revenue",
            "staff_name": "Sophie",
        },

        # ══════════════════════════════════════════════════════════════════════
        # TUESDAY — Gas bill shock, beef mince waste, supplier research, good dinner
        # ══════════════════════════════════════════════════════════════════════

        {
            "entry_date": date(1),
            "entry_time": "08:30:00",
            "entry_type": "text",
            "raw_text": (
                "Gas bill arrived for last month — £1,380. That's up 32% on the month before. "
                "Previous month was £1,045. Something's not right. "
                "Going to check if the oven pilot lights have been left on overnight again."
            ),
            "structured_data": json.dumps({
                "category": "cost",
                "summary": "Monthly gas bill £1,380 — 32% increase vs prior month (£1,045). Possible cause: oven pilot lights left on. Investigation needed.",
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
            "entry_date": date(1),
            "entry_time": "09:00:00",
            "entry_type": "voice",
            "raw_text": (
                "Morning walk-in check. Found 6kg of beef mince approaching best-before — "
                "it's still in date but only just. We used 4kg for staff lunch. "
                "The other 2kg I had to bin — it had turned grey. "
                "This is the second time this month we've wasted mince. "
                "We need to reduce the weekly order from 8kg to 5kg."
            ),
            "structured_data": json.dumps({
                "category": "waste",
                "summary": "6kg beef mince near expiry — 4kg used for staff lunch, 2kg binned. Second mince waste incident this month. Reduce order to 5kg.",
                "urgency": "medium",
                "waste_items": ["2kg beef mince (binned — turned grey)", "4kg beef mince (redirected to staff meal)"],
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
            "entry_date": date(1),
            "entry_time": "10:00:00",
            "entry_type": "text",
            "raw_text": (
                "Spent an hour this morning calling produce suppliers. "
                "Spoke to City Farm Direct — they cover our area, same-day delivery available, "
                "prices look competitive. Getting a quote this afternoon. "
                "Also called London Fresh — minimum order too high for us."
            ),
            "structured_data": json.dumps({
                "category": "supplier",
                "summary": "Contacted City Farm Direct as Fresh Greens replacement — competitive pricing, same-day delivery available. Quote expected this afternoon.",
                "urgency": "medium",
                "supplier_mentions": ["City Farm Direct", "London Fresh", "Fresh Greens"],
                "action_needed": True,
                "complaints": [],
                "waste_items": [],
                "staff_issues": [],
                "revenue": None,
                "covers": None,
                "items_86d": [],
                "positive_notes": ["City Farm Direct — promising alternative to Fresh Greens"],
            }),
            "category": "supplier",
            "staff_name": "Jake",
        },
        {
            "entry_date": date(1),
            "entry_time": "15:30:00",
            "entry_type": "voice",
            "raw_text": (
                "Tuesday lunch — 31 covers, very quiet. Revenue around £820. "
                "Kitchen used the downtime well: fresh stocks made, larder organised, "
                "made three litres of the lamb jus for the week. "
                "Elena is picking up the floor role quickly — Sophie gave her great feedback."
            ),
            "structured_data": json.dumps({
                "category": "revenue",
                "summary": "Quiet Tuesday lunch, 31 covers, £820. Productive kitchen downtime. Elena settling in well with positive feedback from Sophie.",
                "urgency": "low",
                "revenue": 820.0,
                "covers": 31,
                "items_86d": [],
                "positive_notes": ["Kitchen maximised quiet service for prep", "Elena learning floor role quickly — praised by Sophie"],
                "action_needed": False,
                "complaints": [],
                "waste_items": [],
                "staff_issues": [],
                "supplier_mentions": [],
            }),
            "category": "revenue",
            "staff_name": "Sophie",
        },
        {
            "entry_date": date(1),
            "entry_time": "23:20:00",
            "entry_type": "voice",
            "raw_text": (
                "Excellent Tuesday dinner — 74 covers, estimated £2,380. "
                "New lamb dish had nine orders tonight, it's genuinely becoming our signature. "
                "City Farm Direct confirmed quote — 15% cheaper than Fresh Greens for produce, "
                "same-day cut-off at 10am. Jake's going to place a trial order tomorrow. "
                "Sophie was brilliant tonight, three tables specifically asked to pass on "
                "compliments to the manager."
            ),
            "structured_data": json.dumps({
                "category": "revenue",
                "summary": "Strong Tuesday dinner, 74 covers, £2,380. Lamb dish 9 orders. City Farm Direct quote: 15% cheaper than Fresh Greens. Sophie praised by 3 tables.",
                "urgency": "low",
                "revenue": 2380.0,
                "covers": 74,
                "positive_notes": [
                    "Lamb dish 9 orders — becoming signature",
                    "City Farm Direct 15% cheaper — ready to switch",
                    "Sophie praised by 3 separate tables",
                ],
                "action_needed": False,
                "complaints": [],
                "waste_items": [],
                "staff_issues": [],
                "supplier_mentions": ["City Farm Direct"],
                "items_86d": [],
            }),
            "category": "revenue",
            "staff_name": "Sophie",
        },

        # ══════════════════════════════════════════════════════════════════════
        # WEDNESDAY — Dishwasher fault, switched supplier, wine delivery
        # ══════════════════════════════════════════════════════════════════════

        {
            "entry_date": date(2),
            "entry_time": "08:15:00",
            "entry_type": "voice",
            "raw_text": (
                "Morning. Dishwasher started making a grinding noise — loud, metallic. "
                "Chef Marcus thinks it's the pump bearing going. We've switched to the backup "
                "glasswasher for now. Called Hobart maintenance, earliest they can do is Friday morning. "
                "Going to be tight if we get a busy Thursday dinner."
            ),
            "structured_data": json.dumps({
                "category": "issue",
                "summary": "Dishwasher grinding noise — possible pump bearing failure. Hobart maintenance booked for Friday. Backup glasswasher in use.",
                "urgency": "high",
                "action_needed": True,
                "complaints": [],
                "waste_items": [],
                "staff_issues": [],
                "supplier_mentions": ["Hobart"],
                "revenue": None,
                "covers": None,
                "items_86d": [],
                "positive_notes": [],
            }),
            "category": "issue",
            "staff_name": "Jake",
        },
        {
            "entry_date": date(2),
            "entry_time": "09:00:00",
            "entry_type": "text",
            "raw_text": (
                "Placed first order with City Farm Direct this morning. "
                "£187 for the full produce list — same items that cost us £218 with Fresh Greens. "
                "Delivery confirmed for tomorrow 8am. Fingers crossed on quality."
            ),
            "structured_data": json.dumps({
                "category": "supplier",
                "summary": "First City Farm Direct order placed — £187 vs £218 (Fresh Greens). Saving £31/week. Delivery tomorrow 8am.",
                "urgency": "low",
                "supplier_mentions": ["City Farm Direct", "Fresh Greens"],
                "action_needed": False,
                "complaints": [],
                "waste_items": [],
                "staff_issues": [],
                "revenue": None,
                "covers": None,
                "items_86d": [],
                "positive_notes": ["Switching to City Farm Direct — projected saving £31/week"],
            }),
            "category": "supplier",
            "staff_name": "Jake",
        },
        {
            "entry_date": date(2),
            "entry_time": "10:00:00",
            "entry_type": "photo",
            "raw_text": "Berry Bros & Rudd spring wine invoice — Wednesday delivery.",
            "structured_data": json.dumps({
                "document_type": "invoice",
                "supplier_name": "Berry Bros & Rudd",
                "date": date(2),
                "total_amount": 912.80,
                "vat": 152.13,
                "items": [
                    {"name": "Burgundy Pinot Noir 2022 x12", "quantity": 12, "unit": "bottle", "unit_price": 24.50, "total": 294.00},
                    {"name": "Chablis Premier Cru 2023 x6", "quantity": 6, "unit": "bottle", "unit_price": 31.00, "total": 186.00},
                    {"name": "House Sauvignon Blanc x24", "quantity": 24, "unit": "bottle", "unit_price": 11.80, "total": 283.20},
                    {"name": "House Merlot x24", "quantity": 24, "unit": "bottle", "unit_price": 10.90, "total": 261.60},
                    {"name": "Champagne Brut NV x6", "quantity": 6, "unit": "bottle", "unit_price": 38.00, "total": 228.00},
                ],
                "summary": "Berry Bros & Rudd wine order £912.80 inc VAT. Added 6x Champagne NV for weekend service.",
                "category": "cost",
            }),
            "category": "cost",
            "staff_name": "Jake",
        },
        {
            "entry_date": date(2),
            "entry_time": "15:45:00",
            "entry_type": "voice",
            "raw_text": (
                "Wednesday lunch 38 covers, £1,020 revenue. Service slowed a bit "
                "because the backup glasswasher can only do one rack at a time — "
                "Sophie had to hold a couple of tables while we waited for clean glasses. "
                "Guests were understanding but we can't let this drag past Friday. "
                "One table had a small complaint about wait time, acknowledged it, no fuss."
            ),
            "structured_data": json.dumps({
                "category": "revenue",
                "summary": "Wednesday lunch 38 covers, £1,020. Service slowed by glasswasher backup. One table complaint about wait time — handled.",
                "urgency": "medium",
                "revenue": 1020.0,
                "covers": 38,
                "complaints": ["wait time — slow glass turnaround due to dishwasher issue"],
                "action_needed": True,
                "waste_items": [],
                "staff_issues": [],
                "supplier_mentions": [],
                "items_86d": [],
                "positive_notes": [],
            }),
            "category": "revenue",
            "staff_name": "Sophie",
        },
        {
            "entry_date": date(2),
            "entry_time": "16:30:00",
            "entry_type": "text",
            "raw_text": (
                "Just got a 5-star Google review from last night! "
                "The guest mentioned the lamb dish by name and called Sophie "
                "'the most attentive and warm front-of-house person we've encountered in London'. "
                "Jake is going to share this with the whole team."
            ),
            "structured_data": json.dumps({
                "category": "general",
                "summary": "5-star Google review: lamb dish praised by name, Sophie described as 'most attentive FOH in London'.",
                "urgency": "low",
                "positive_notes": [
                    "5-star Google review received",
                    "Lamb dish praised by name in review",
                    "Sophie described as 'most attentive FOH in London'",
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
        {
            "entry_date": date(2),
            "entry_time": "23:10:00",
            "entry_type": "voice",
            "raw_text": (
                "Wednesday dinner — 70 covers, £2,210 revenue. "
                "We had to stagger clearing tables to work around the glasswasher. "
                "Guests generally fine but kitchen felt the friction. "
                "Lamb dish 11 orders — officially needs its own featured spot on the menu. "
                "Marcus was great in the kitchen tonight, made a real effort."
            ),
            "structured_data": json.dumps({
                "category": "revenue",
                "summary": "Wednesday dinner 70 covers, £2,210. Glasswasher still causing friction. Lamb dish 11 orders — needs menu feature. Marcus performed well.",
                "urgency": "low",
                "revenue": 2210.0,
                "covers": 70,
                "items_86d": [],
                "positive_notes": ["Lamb dish 11 orders — strongest night yet", "Marcus showed real effort and focus"],
                "action_needed": False,
                "complaints": [],
                "waste_items": [],
                "staff_issues": [],
                "supplier_mentions": [],
            }),
            "category": "revenue",
            "staff_name": "Sophie",
        },

        # ══════════════════════════════════════════════════════════════════════
        # THURSDAY — City Farm first delivery (excellent!), Marcus chat, record revenue
        # ══════════════════════════════════════════════════════════════════════

        {
            "entry_date": date(3),
            "entry_time": "08:05:00",
            "entry_type": "voice",
            "raw_text": (
                "City Farm Direct just delivered — absolutely outstanding quality. "
                "Romaine is crisp and full heads, courgettes are perfect, herbs smell incredible. "
                "Everything is exactly what we ordered, not a gram short. "
                "Why did we put up with Fresh Greens for so long? "
                "Placing a standing weekly order today."
            ),
            "structured_data": json.dumps({
                "category": "supplier",
                "summary": "City Farm Direct first delivery — perfect quality, correct quantities, great freshness. Switching to standing weekly order immediately.",
                "urgency": "low",
                "supplier_mentions": ["City Farm Direct", "Fresh Greens"],
                "action_needed": True,
                "complaints": [],
                "waste_items": [],
                "staff_issues": [],
                "revenue": None,
                "covers": None,
                "items_86d": [],
                "positive_notes": ["City Farm Direct: exceptional quality, full delivery, excellent freshness"],
            }),
            "category": "supplier",
            "staff_name": "Jake",
        },
        {
            "entry_date": date(3),
            "entry_time": "09:15:00",
            "entry_type": "photo",
            "raw_text": "City Farm Direct — first produce invoice.",
            "structured_data": json.dumps({
                "document_type": "invoice",
                "supplier_name": "City Farm Direct",
                "date": date(3),
                "total_amount": 187.00,
                "vat": 0.0,
                "items": [
                    {"name": "Romaine lettuce x24 heads", "quantity": 24, "unit": "head", "unit_price": 1.50, "total": 36.00},
                    {"name": "Courgettes 6kg", "quantity": 6, "unit": "kg", "unit_price": 2.80, "total": 16.80},
                    {"name": "Cherry tomatoes 5kg", "quantity": 5, "unit": "kg", "unit_price": 3.90, "total": 19.50},
                    {"name": "Fresh herbs mixed 3kg", "quantity": 3, "unit": "kg", "unit_price": 10.50, "total": 31.50},
                    {"name": "Spinach 4kg", "quantity": 4, "unit": "kg", "unit_price": 4.80, "total": 19.20},
                    {"name": "Asparagus 3kg", "quantity": 3, "unit": "kg", "unit_price": 8.00, "total": 24.00},
                    {"name": "Seasonal mushrooms 2kg", "quantity": 2, "unit": "kg", "unit_price": 10.00, "total": 20.00},
                    {"name": "Mixed salad leaves 4kg", "quantity": 4, "unit": "kg", "unit_price": 5.00, "total": 20.00},
                ],
                "summary": "City Farm Direct first invoice — £187 zero-rated. Saves £31/week vs Fresh Greens for better quality produce.",
                "category": "cost",
            }),
            "category": "cost",
            "staff_name": "Jake",
        },
        {
            "entry_date": date(3),
            "entry_time": "11:00:00",
            "entry_type": "voice",
            "raw_text": (
                "Had a one-to-one with Marcus this morning about the lateness and a few "
                "kitchen attitude issues that Sophie raised. He was genuinely receptive — "
                "admitted he's been having a rough few months personally and apologised. "
                "We agreed: three strikes policy, one written warning already logged. "
                "He wants to stay and improve. I believe him. Watch this space."
            ),
            "structured_data": json.dumps({
                "category": "staff",
                "summary": "Honest conversation with Marcus about lateness and attitude. He apologised, cited personal issues. Written warning logged. Agreed improvement plan.",
                "urgency": "medium",
                "staff_issues": ["Marcus — first written warning issued", "Improvement plan agreed"],
                "action_needed": True,
                "complaints": [],
                "waste_items": [],
                "supplier_mentions": [],
                "revenue": None,
                "covers": None,
                "items_86d": [],
                "positive_notes": ["Marcus receptive and committed to improvement"],
            }),
            "category": "staff",
            "staff_name": "Jake",
        },
        {
            "entry_date": date(3),
            "entry_time": "15:20:00",
            "entry_type": "voice",
            "raw_text": (
                "Thursday lunch — 54 covers, £1,420. Really strong. "
                "The fresh produce from City Farm is already noticeable — "
                "the Caesar salad looks and tastes better, two tables mentioned it unprompted. "
                "Elena ran a four-table section solo for the first time. She was brilliant."
            ),
            "structured_data": json.dumps({
                "category": "revenue",
                "summary": "Solid Thursday lunch, 54 covers, £1,420. City Farm produce already improving dish quality. Elena ran 4-table section solo — excelled.",
                "urgency": "low",
                "revenue": 1420.0,
                "covers": 54,
                "items_86d": [],
                "positive_notes": [
                    "City Farm produce visibly improving dish quality — guests noticing",
                    "Elena handled 4-table section solo for first time — outstanding",
                ],
                "action_needed": False,
                "complaints": [],
                "waste_items": [],
                "staff_issues": [],
                "supplier_mentions": ["City Farm Direct"],
            }),
            "category": "revenue",
            "staff_name": "Sophie",
        },
        {
            "entry_date": date(3),
            "entry_time": "23:30:00",
            "entry_type": "voice",
            "raw_text": (
                "Best dinner of the week so far — 79 covers, estimated £2,560 revenue. "
                "Lamb dish was on 14 orders and we almost ran out again. "
                "Need to order more lamb for the weekend. "
                "Service felt smooth even with the backup glasswasher — team adapted well. "
                "Marcus was exceptional tonight, completely different energy. "
                "Group of eight celebrating a birthday, they left a £60 tip between them."
            ),
            "structured_data": json.dumps({
                "category": "revenue",
                "summary": "Excellent Thursday dinner, 79 covers, £2,560. Lamb dish 14 orders — nearly ran out. Marcus exceptional. Birthday table left £60 tip.",
                "urgency": "low",
                "revenue": 2560.0,
                "covers": 79,
                "items_86d": [],
                "positive_notes": [
                    "79 covers — best dinner of the week",
                    "Marcus showed complete improvement — exceptional service",
                    "Birthday party left £60 tip",
                ],
                "action_needed": True,
                "complaints": [],
                "waste_items": [],
                "staff_issues": [],
                "supplier_mentions": [],
            }),
            "category": "revenue",
            "staff_name": "Sophie",
        },

        # ══════════════════════════════════════════════════════════════════════
        # FRIDAY — Dishwasher fixed, record dinner, TripAdvisor complaint
        # ══════════════════════════════════════════════════════════════════════

        {
            "entry_date": date(4),
            "entry_time": "09:30:00",
            "entry_type": "voice",
            "raw_text": (
                "Hobart engineer came in at 8am — it was the pump bearing as Marcus suspected. "
                "Replaced it on the spot, took about 90 minutes. "
                "Dishwasher is running perfectly now, better than before honestly. "
                "Invoice to follow but the engineer said roughly £320 for parts and labour. "
                "Just in time for the weekend."
            ),
            "structured_data": json.dumps({
                "category": "issue",
                "summary": "Hobart engineer replaced dishwasher pump bearing — fully repaired. Invoice ~£320. Timed perfectly before weekend.",
                "urgency": "low",
                "action_needed": True,
                "complaints": [],
                "waste_items": [],
                "staff_issues": [],
                "supplier_mentions": ["Hobart"],
                "revenue": None,
                "covers": None,
                "items_86d": [],
                "positive_notes": ["Dishwasher fully repaired — running better than before"],
            }),
            "category": "issue",
            "staff_name": "Jake",
        },
        {
            "entry_date": date(4),
            "entry_time": "10:15:00",
            "entry_type": "photo",
            "raw_text": "Hobart dishwasher repair invoice — Friday call-out.",
            "structured_data": json.dumps({
                "document_type": "invoice",
                "supplier_name": "Hobart Service",
                "date": date(4),
                "total_amount": 318.00,
                "vat": 53.00,
                "items": [
                    {"name": "Pump bearing replacement (part)", "quantity": 1, "unit": "unit", "unit_price": 145.00, "total": 145.00},
                    {"name": "Labour — 1.5 hours", "quantity": 1.5, "unit": "hour", "unit_price": 95.00, "total": 142.50},
                    {"name": "Call-out fee", "quantity": 1, "unit": "unit", "unit_price": 30.50, "total": 30.50},
                ],
                "summary": "Hobart dishwasher repair — pump bearing replaced. £318 inc VAT. Emergency Friday callout.",
                "category": "cost",
            }),
            "category": "cost",
            "staff_name": "Jake",
        },
        {
            "entry_date": date(4),
            "entry_time": "11:30:00",
            "entry_type": "text",
            "raw_text": (
                "Just spotted a negative TripAdvisor review from Wednesday night — "
                "2 stars. The guest mentioned slow service and had to wait 20 minutes for glasses. "
                "Clearly the dishwasher issue. Going to respond professionally today. "
                "Jake is drafting a reply."
            ),
            "structured_data": json.dumps({
                "category": "general",
                "summary": "2-star TripAdvisor review from Wednesday citing slow service and glass wait times. Linked to dishwasher issue. Jake drafting professional response.",
                "urgency": "medium",
                "complaints": ["TripAdvisor: 2-star review — slow service, wait for glasses (Wednesday)"],
                "action_needed": True,
                "waste_items": [],
                "staff_issues": [],
                "supplier_mentions": [],
                "revenue": None,
                "covers": None,
                "items_86d": [],
                "positive_notes": [],
            }),
            "category": "general",
            "staff_name": "Sophie",
        },
        {
            "entry_date": date(4),
            "entry_time": "15:50:00",
            "entry_type": "voice",
            "raw_text": (
                "Friday lunch — 61 covers, £1,620. Best lunch of the week. "
                "Fully operational kitchen again — dishwasher running, team in good spirits. "
                "New asparagus starter from City Farm has gone down brilliantly — "
                "sold 18 covers at lunch alone. Margins look good on it too. "
                "Salmon order has been increased for tonight."
            ),
            "structured_data": json.dumps({
                "category": "revenue",
                "summary": "Best lunch of the week — 61 covers, £1,620. New asparagus starter sold 18. Dishwasher back. Team morale high.",
                "urgency": "low",
                "revenue": 1620.0,
                "covers": 61,
                "items_86d": [],
                "positive_notes": [
                    "New asparagus starter — 18 orders, strong margins",
                    "Team morale high after dishwasher repair",
                    "Salmon restocked for evening service",
                ],
                "action_needed": False,
                "complaints": [],
                "waste_items": [],
                "staff_issues": [],
                "supplier_mentions": ["City Farm Direct"],
            }),
            "category": "revenue",
            "staff_name": "Sophie",
        },
        {
            "entry_date": date(4),
            "entry_time": "18:00:00",
            "entry_type": "voice",
            "raw_text": (
                "Pre-service briefing notes. Full Friday evening — 48 covers already booked, "
                "expecting walk-ins to push us to 85+. "
                "Marcus and Elena have a system for the floor working perfectly. "
                "Sophie celebrating her one-year anniversary with us tonight — "
                "team got her a card and Jake's doing a brief speech before service."
            ),
            "structured_data": json.dumps({
                "category": "staff",
                "summary": "Friday pre-service — 48 booked, 85+ expected. Marcus/Elena floor system working well. Sophie's 1-year work anniversary celebrated with team.",
                "urgency": "low",
                "staff_issues": [],
                "positive_notes": [
                    "Sophie's 1-year work anniversary — team celebration",
                    "Marcus and Elena floor system working well together",
                ],
                "action_needed": False,
                "complaints": [],
                "waste_items": [],
                "supplier_mentions": [],
                "revenue": None,
                "covers": None,
                "items_86d": [],
            }),
            "category": "staff",
            "staff_name": "Jake",
        },
        {
            "entry_date": date(4),
            "entry_time": "23:45:00",
            "entry_type": "voice",
            "raw_text": (
                "Incredible Friday night — 91 covers, estimated £2,970 revenue. "
                "New record for a Friday. Lamb dish 18 orders — we ran out at 9:30pm. "
                "Asparagus starter sold out by 8pm. "
                "Zero complaints all evening. "
                "Marcus and Elena were faultless on the floor. Sophie was emotional after service. "
                "What a week this is turning into."
            ),
            "structured_data": json.dumps({
                "category": "revenue",
                "summary": "Record Friday dinner — 91 covers, £2,970. Lamb 18 orders (ran out 9:30pm). Asparagus sold out 8pm. Zero complaints. Marcus and Elena faultless.",
                "urgency": "low",
                "revenue": 2970.0,
                "covers": 91,
                "items_86d": ["lamb dish (sold out 9:30pm)", "asparagus starter (sold out 8pm)"],
                "positive_notes": [
                    "Record Friday — 91 covers, £2,970",
                    "Zero complaints all evening",
                    "Marcus and Elena: faultless service",
                    "Sophie's anniversary celebration — team morale excellent",
                ],
                "action_needed": True,
                "complaints": [],
                "waste_items": [],
                "staff_issues": [],
                "supplier_mentions": [],
            }),
            "category": "revenue",
            "staff_name": "Sophie",
        },

        # ══════════════════════════════════════════════════════════════════════
        # SATURDAY — Record-breaking night, wine running low, waste audit
        # ══════════════════════════════════════════════════════════════════════

        {
            "entry_date": date(5),
            "entry_time": "08:30:00",
            "entry_type": "voice",
            "raw_text": (
                "Saturday morning. Did a full walk-in audit. "
                "Found 3kg of chicken breast from Monday delivery borderline — just within date "
                "but texture's off. Binned the lot. £25.50 write-off. "
                "Also found half a tray of strawberries going soft — used them for staff. "
                "Going to tighten the FIFO rotation on the protein shelf."
            ),
            "structured_data": json.dumps({
                "category": "waste",
                "summary": "Walk-in audit: 3kg chicken binned (texture off, £25.50 write-off). Soft strawberries used for staff. FIFO review needed on protein shelf.",
                "urgency": "medium",
                "waste_items": ["3kg chicken breast (texture off — binned, £25.50)", "soft strawberries (used for staff)"],
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
            "entry_date": date(5),
            "entry_time": "09:45:00",
            "entry_type": "photo",
            "raw_text": "Smithfield Meats Saturday top-up delivery — extra lamb and salmon for weekend.",
            "structured_data": json.dumps({
                "document_type": "invoice",
                "supplier_name": "Smithfield Meats",
                "date": date(5),
                "total_amount": 284.00,
                "vat": 47.33,
                "items": [
                    {"name": "Lamb rack 5kg (extra for weekend)", "quantity": 5, "unit": "kg", "unit_price": 33.00, "total": 165.00},
                    {"name": "Salmon side 4kg", "quantity": 4, "unit": "kg", "unit_price": 16.50, "total": 66.00},
                    {"name": "Chicken breast fillet 5kg (replacement)", "quantity": 5, "unit": "kg", "unit_price": 8.50, "total": 42.50},
                    {"name": "Duck breast 2kg", "quantity": 2, "unit": "kg", "unit_price": 10.25, "total": 20.50},
                ],
                "summary": "Smithfield weekend top-up £284 inc VAT — extra lamb (5kg), salmon (4kg), replacement chicken (5kg), duck (2kg).",
                "category": "cost",
            }),
            "category": "cost",
            "staff_name": "Jake",
        },
        {
            "entry_date": date(5),
            "entry_time": "11:00:00",
            "entry_type": "text",
            "raw_text": (
                "Checking wine levels after the big Friday — house Sauvignon is down to 4 bottles, "
                "Merlot down to 6. We won't make it through Saturday dinner. "
                "Jake is calling Berry Bros now for an emergency top-up delivery. "
                "Should arrive by 3pm."
            ),
            "structured_data": json.dumps({
                "category": "cost",
                "summary": "Wine critically low after Friday — Sauvignon 4 bottles, Merlot 6. Emergency top-up order placed with Berry Bros for 3pm delivery.",
                "urgency": "high",
                "supplier_mentions": ["Berry Bros & Rudd"],
                "action_needed": True,
                "complaints": [],
                "waste_items": [],
                "staff_issues": [],
                "revenue": None,
                "covers": None,
                "items_86d": [],
                "positive_notes": [],
            }),
            "category": "cost",
            "staff_name": "Sophie",
        },
        {
            "entry_date": date(5),
            "entry_time": "15:30:00",
            "entry_type": "voice",
            "raw_text": (
                "Saturday lunch — full house, 74 covers, £2,020 revenue. "
                "Absolutely buzzing. The asparagus starter is back on and selling fast. "
                "Lamb dish on 12 lunch orders — still going. "
                "Wine delivery arrived at 2:45pm — just in time. "
                "Elena is ready to be given her own section full time."
            ),
            "structured_data": json.dumps({
                "category": "revenue",
                "summary": "Packed Saturday lunch — 74 covers, £2,020. Asparagus and lamb both strong. Wine delivery arrived just in time. Elena ready for full section.",
                "urgency": "low",
                "revenue": 2020.0,
                "covers": 74,
                "items_86d": [],
                "positive_notes": [
                    "74 covers at lunch — best Saturday lunch",
                    "Elena ready for full section responsibility",
                    "Wine restocked just in time",
                ],
                "action_needed": False,
                "complaints": [],
                "waste_items": [],
                "staff_issues": [],
                "supplier_mentions": ["Berry Bros & Rudd"],
            }),
            "category": "revenue",
            "staff_name": "Sophie",
        },
        {
            "entry_date": date(5),
            "entry_time": "17:45:00",
            "entry_type": "text",
            "raw_text": (
                "Elena called — she's going to be 30 minutes late, tube delays. "
                "Jake shuffled the sections. Not ideal but manageable. "
                "Elena arrived at 6:15 and hit the ground running. "
                "She apologised and offered to stay on to help with clean-down."
            ),
            "structured_data": json.dumps({
                "category": "staff",
                "summary": "Elena 30 minutes late (tube delays). Sections shuffled. Arrived 6:15pm, hit the ground running, offered to stay for clean-down.",
                "urgency": "low",
                "staff_issues": ["Elena — 30 min late, tube delays (valid reason, first incident)"],
                "positive_notes": ["Elena apologised and offered to stay for clean-down"],
                "action_needed": False,
                "complaints": [],
                "waste_items": [],
                "supplier_mentions": [],
                "revenue": None,
                "covers": None,
                "items_86d": [],
            }),
            "category": "staff",
            "staff_name": "Jake",
        },
        {
            "entry_date": date(5),
            "entry_time": "23:55:00",
            "entry_type": "voice",
            "raw_text": (
                "Record Saturday. 98 covers. Revenue estimated at £3,180. "
                "That's the biggest single service we've ever done. "
                "Lamb dish 22 orders and sold out by 8:45pm — two tables gutted they missed it. "
                "Zero complaints. The team was absolutely outstanding. "
                "Marcus was a different person compared to last Monday. "
                "Getting emotional thinking about this."
            ),
            "structured_data": json.dumps({
                "category": "revenue",
                "summary": "RECORD Saturday dinner — 98 covers, £3,180. Restaurant's best ever service. Lamb 22 orders (sold out 8:45pm). Zero complaints. Team exceptional.",
                "urgency": "low",
                "revenue": 3180.0,
                "covers": 98,
                "items_86d": ["lamb dish (sold out 8:45pm)"],
                "positive_notes": [
                    "Restaurant record — 98 covers, £3,180 revenue",
                    "Entire team performed exceptionally",
                    "Marcus completely turned around his performance",
                    "Zero complaints across 98 covers",
                ],
                "action_needed": True,
                "complaints": [],
                "waste_items": [],
                "staff_issues": [],
                "supplier_mentions": [],
            }),
            "category": "revenue",
            "staff_name": "Sophie",
        },

        # ══════════════════════════════════════════════════════════════════════
        # SUNDAY — Quieter close to week, electricity bill, reflection & planning
        # ══════════════════════════════════════════════════════════════════════

        {
            "entry_date": date(6),
            "entry_time": "09:00:00",
            "entry_type": "text",
            "raw_text": (
                "Electricity bill arrived — £680 for the month. "
                "That's actually down £42 vs last month. "
                "Makes sense given we've been more careful about the oven overnight. "
                "Gas was £1,380 though — need to focus energy audit on gas usage, not electric."
            ),
            "structured_data": json.dumps({
                "category": "cost",
                "summary": "Electricity bill £680 — down £42 vs last month (good). Gas remains high at £1,380. Energy audit should focus on gas/ovens.",
                "urgency": "low",
                "action_needed": True,
                "complaints": [],
                "waste_items": [],
                "staff_issues": [],
                "supplier_mentions": [],
                "revenue": None,
                "covers": None,
                "items_86d": [],
                "positive_notes": ["Electricity bill down £42 — overnight oven protocol working"],
            }),
            "category": "cost",
            "staff_name": "Jake",
        },
        {
            "entry_date": date(6),
            "entry_time": "09:30:00",
            "entry_type": "voice",
            "raw_text": (
                "Checking over the week. "
                "We had three occasions where we ran out of the lamb dish mid-service. "
                "The problem is the lamb rack order — 3kg on Monday is not enough. "
                "Going to increase to 5kg Monday and add a 3kg top-up on Thursday. "
                "Also need to sort a menu feature card for it — it deserves the spotlight."
            ),
            "structured_data": json.dumps({
                "category": "waste",
                "summary": "Lamb dish ran out 3x this week — Monday order insufficient. Increasing to 5kg Mon + 3kg Thu top-up. Menu feature card to be created.",
                "urgency": "medium",
                "waste_items": [],
                "action_needed": True,
                "complaints": [],
                "staff_issues": [],
                "supplier_mentions": ["Smithfield Meats"],
                "revenue": None,
                "covers": None,
                "items_86d": [],
                "positive_notes": ["Lamb dish demand confirms it needs permanent menu feature"],
            }),
            "category": "waste",
            "staff_name": "Jake",
        },
        {
            "entry_date": date(6),
            "entry_time": "15:00:00",
            "entry_type": "voice",
            "raw_text": (
                "Sunday lunch — 39 covers, £980. Quiet but clean service. "
                "Lots of regulars in, good energy. "
                "Three tables mentioned they'd seen the Google review about Sophie — "
                "they wanted to specifically be served by her, which was very sweet. "
                "Lamb dish sold out again by 1:30pm."
            ),
            "structured_data": json.dumps({
                "category": "revenue",
                "summary": "Quiet Sunday lunch, 39 covers, £980. Regulars in. Three tables asked for Sophie by name after Google review. Lamb sold out 1:30pm.",
                "urgency": "low",
                "revenue": 980.0,
                "covers": 39,
                "items_86d": ["lamb dish (sold out 1:30pm)"],
                "positive_notes": [
                    "Regulars returning — strong community loyalty",
                    "3 tables requested Sophie by name after seeing review",
                ],
                "action_needed": False,
                "complaints": [],
                "waste_items": [],
                "staff_issues": [],
                "supplier_mentions": [],
            }),
            "category": "revenue",
            "staff_name": "Elena",
        },
        {
            "entry_date": date(6),
            "entry_time": "22:30:00",
            "entry_type": "voice",
            "raw_text": (
                "Sunday dinner to close the week — 55 covers, around £1,740 revenue. "
                "Comfortable, relaxed service. "
                "Team is tired but proud — they should be. "
                "Rough tally for the week: around 820 covers, revenue somewhere around £27,000. "
                "That's nearly 20% up on last week. "
                "Next week: increase lamb order, add asparagus to the permanent menu, "
                "and set up gas audit."
            ),
            "structured_data": json.dumps({
                "category": "revenue",
                "summary": "Sunday dinner 55 covers, £1,740. Week total ~820 covers, ~£27,000 revenue — approx. 20% up week-on-week. Strong finish to outstanding week.",
                "urgency": "low",
                "revenue": 1740.0,
                "covers": 55,
                "items_86d": [],
                "positive_notes": [
                    "Week revenue ~£27,000 — approximately 20% up week-on-week",
                    "~820 covers for the week",
                    "Team morale at high",
                ],
                "action_needed": True,
                "complaints": [],
                "waste_items": [],
                "staff_issues": [],
                "supplier_mentions": [],
            }),
            "category": "revenue",
            "staff_name": "Jake",
        },
        {
            "entry_date": date(6),
            "entry_time": "23:00:00",
            "entry_type": "text",
            "raw_text": (
                "Week actions confirmed for next week:\n"
                "1. Increase lamb rack order Monday to 5kg + Thursday 3kg top-up\n"
                "2. Design lamb dish feature card for tables\n"
                "3. Add asparagus starter to permanent menu\n"
                "4. Reduce beef mince order from 8kg to 5kg\n"
                "5. Book gas engineer to check ovens and pilot lights\n"
                "6. Formally give Elena her own section\n"
                "7. Respond to TripAdvisor review professionally\n"
                "8. Review Marcus's progress in two weeks"
            ),
            "structured_data": json.dumps({
                "category": "general",
                "summary": "Week action plan confirmed: 8 priorities set including lamb order increase, asparagus on menu, gas audit, Elena promotion, TripAdvisor response.",
                "urgency": "low",
                "action_needed": False,
                "complaints": [],
                "waste_items": [],
                "staff_issues": [],
                "supplier_mentions": [],
                "revenue": None,
                "covers": None,
                "items_86d": [],
                "positive_notes": ["Full week actions agreed — well-run operational review"],
            }),
            "category": "general",
            "staff_name": "Jake",
        },
    ]


DEMO_STAFF = [
    {"name": "Jake", "role": "owner"},
    {"name": "Sophie", "role": "staff"},
    {"name": "Marcus", "role": "staff"},
    {"name": "Elena", "role": "staff"},
]
