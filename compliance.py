"""
compliance.py
=============
Single source of truth for ALL jurisdiction-specific and industry-specific rules.

No law names, regulatory body names, fee/penalty references, or jurisdiction-specific
requirements should be hardcoded anywhere else in the codebase.

Usage:
    from compliance import get_compliance, tips_enabled, allergen_enabled, inspection_enabled

    comp = get_compliance(restaurant)
    law  = comp["allergen_law"]
    body = comp["inspection_body"]

The restaurant dict must contain at least:
    - country_code  (ISO 3166-1 alpha-2, e.g. "GB", "US", "AU")  — or inferred from currency_code
    - currency_code (e.g. "GBP", "USD")
    - industry      (e.g. "restaurant", "salon")
"""

# ── Industry classification ───────────────────────────────────────────────────

FOOD_INDUSTRIES = {
    "restaurant", "cafe", "café", "bar", "pub", "bakery",
    "food truck", "takeaway", "hotel", "supermarket",
}


def is_food_business(restaurant: dict) -> bool:
    """True if this business handles food — used to gate food-specific commands."""
    industry = (restaurant.get("industry") or "restaurant").lower()
    return industry in FOOD_INDUSTRIES


# ── Country inference from currency ──────────────────────────────────────────

CURRENCY_TO_COUNTRY: dict[str, str] = {
    "GBP": "GB",
    "USD": "US",
    "EUR": "EU",    # Ambiguous — any EU member; full country list below
    "AUD": "AU",
    "NGN": "NG",
    "KES": "KE",
    "ZAR": "ZA",
    "GHS": "GH",
    "UGX": "UG",
    "TZS": "TZ",
    "XOF": "XOF",  # West African CFA Franc — several countries
}


def infer_country(restaurant: dict) -> str:
    """
    Return the best country code for this restaurant.
    Uses the stored country_code if set; otherwise infers from currency_code.
    Falls back to "GB" so existing single-country installations are unaffected.
    """
    stored = (restaurant.get("country_code") or "").strip().upper()
    if stored:
        return stored
    currency = (restaurant.get("currency_code") or "GBP").upper()
    return CURRENCY_TO_COUNTRY.get(currency, "GB")


# ── Country compliance configurations ────────────────────────────────────────
#
# Keys used throughout the codebase — add new keys here, never in the callers.
#
#   TIPS
#   tips_enabled          bool     Whether tips recording is a legal obligation
#   tips_law              str|None Name of the tips allocation law (None = no law)
#   tips_summary          str      One-sentence obligation description shown to users
#   tips_retention_years  int      Mandatory record retention (0 = no requirement)
#
#   ALLERGENS  (applies to food businesses only)
#   allergen_law          str      Name of the allergen traceability/labelling law
#   allergen_summary      str      One-sentence description shown to users
#   allergen_applies      bool     Whether any allergen law applies here
#
#   FOOD INSPECTION  (applies to food businesses only)
#   inspection_body       str      Name of the food safety authority
#   inspection_officers   str      What inspectors are called
#   hygiene_scheme        str      Name of the hygiene rating scheme
#   inspection_summary    str      One-sentence description shown to users
#
#   DATA PROTECTION
#   data_law              str      Name of the data protection law
#   data_summary          str      One-sentence description shown to users
#
#   ADMIN / FORMATTING
#   vat_label             str      "VAT", "GST", "Sales Tax", etc.
#   vat_rate_label        str      e.g. "20% standard rate"
#   company_id_label      str      "Company Number", "ABN", "EIN", etc.
#   date_format           str      "DD/MM/YYYY" or "MM/DD/YYYY"
#   accounting_formats    list     Supported /export formats

COUNTRY_COMPLIANCE: dict[str, dict] = {

    # ── United Kingdom ────────────────────────────────────────────────────────
    "GB": {
        "tips_enabled": True,
        "tips_law": "Employment (Allocation of Tips) Act 2023",
        "tips_summary": (
            "100% of tips must be passed to workers with no deductions. "
            "Records must be kept for 3 years and provided to any worker on request."
        ),
        "tips_retention_years": 3,

        "allergen_law": "Natasha's Law (Food Information (Amendment) (England) Regulations 2019)",
        "allergen_summary": (
            "Allergen declarations must be updated whenever ingredients or suppliers change. "
            "Unlimited fines for failures."
        ),
        "allergen_applies": True,

        "inspection_body": "Food Standards Agency (FSA)",
        "inspection_officers": "Environmental Health Officers (EHOs)",
        "hygiene_scheme": "Food Hygiene Rating Scheme (FHRS) — rated 0 to 5",
        "inspection_summary": (
            "FSA hygiene rating from 0–5. EHOs inspect supplier records, temperature logs, "
            "allergen declarations, and staff training. A 5-star rating requires evidence "
            "of consistent record-keeping."
        ),

        "data_law": "UK GDPR",
        "data_summary": "Personal data must not be kept longer than necessary (UK GDPR Article 5(1)(e)).",

        "vat_label": "VAT",
        "vat_rate_label": "20% standard rate / 0% zero-rated",
        "company_id_label": "Company Number",
        "date_format": "DD/MM/YYYY",
        "accounting_formats": ["Xero Bills", "Sage 50", "Payroll CSV", "General CSV"],
    },

    # ── United States ─────────────────────────────────────────────────────────
    "US": {
        "tips_enabled": False,
        "tips_law": None,
        "tips_summary": (
            "No federal tips allocation law. Tip pooling rules vary by state. "
            "TradeFlow records all tip events for your own records."
        ),
        "tips_retention_years": 0,

        "allergen_law": "FALCPA (Food Allergen Labeling and Consumer Protection Act 2004) / FASTER Act 2021",
        "allergen_summary": (
            "9 major allergens must be declared. Written traceability records are best practice "
            "for food safety and liability."
        ),
        "allergen_applies": True,

        "inspection_body": "FDA / local health departments",
        "inspection_officers": "health inspectors",
        "hygiene_scheme": "local health department letter grade (A/B/C)",
        "inspection_summary": (
            "Health department inspections vary by county and city. Focus areas: "
            "temperature control, allergen labelling, sanitation, and employee hygiene."
        ),

        "data_law": "CCPA (California) / state privacy laws",
        "data_summary": "No single federal data law. Best practice: don't retain personal data longer than needed.",

        "vat_label": "Sales Tax",
        "vat_rate_label": "varies by state",
        "company_id_label": "EIN",
        "date_format": "MM/DD/YYYY",
        "accounting_formats": ["QuickBooks CSV", "Xero Bills", "Payroll CSV", "General CSV"],
    },

    # ── Australia ─────────────────────────────────────────────────────────────
    "AU": {
        "tips_enabled": False,
        "tips_law": None,
        "tips_summary": "No mandatory tips allocation law in Australia. Distribution is at employer discretion.",
        "tips_retention_years": 0,

        "allergen_law": "FSANZ Standard 1.2.3 (Food Standards Australia New Zealand)",
        "allergen_summary": (
            "Mandatory allergen labelling for pre-packaged food. "
            "Traceability records are best practice for food service operations."
        ),
        "allergen_applies": True,

        "inspection_body": "FSANZ / state food safety authorities",
        "inspection_officers": "environmental health officers",
        "hygiene_scheme": "state-based food safety programs",
        "inspection_summary": (
            "State food authority inspections cover food safety plans, temperature control, "
            "allergens, and staff certification requirements."
        ),

        "data_law": "Privacy Act 1988 (Australian Privacy Principles)",
        "data_summary": "Personal data must be handled under the Australian Privacy Principles and deleted when no longer needed.",

        "vat_label": "GST",
        "vat_rate_label": "10% standard rate",
        "company_id_label": "ABN",
        "date_format": "DD/MM/YYYY",
        "accounting_formats": ["MYOB CSV", "Xero Bills", "Payroll CSV", "General CSV"],
    },

    # ── European Union (generic — covers DE, FR, ES, IT, NL, BE, etc.) ───────
    "EU": {
        "tips_enabled": False,
        "tips_law": None,
        "tips_summary": (
            "No EU-wide tips allocation law. Rules vary by member state. "
            "Some sectors have collective bargaining agreements covering tips."
        ),
        "tips_retention_years": 0,

        "allergen_law": "EU Food Information Regulation (FIR) No. 1169/2011",
        "allergen_summary": (
            "14 major allergens must be declared for both pre-packaged and unpackaged food. "
            "Written records required."
        ),
        "allergen_applies": True,

        "inspection_body": "national food safety authority (varies by member state)",
        "inspection_officers": "food safety inspectors",
        "hygiene_scheme": "EU Regulation (EC) No 852/2004 HACCP standards",
        "inspection_summary": (
            "National food authority inspections under EU Regulation 852/2004 cover HACCP plans, "
            "temperature control, allergen declarations, and supplier traceability."
        ),

        "data_law": "GDPR (EU General Data Protection Regulation)",
        "data_summary": "Personal data must not be kept longer than necessary (GDPR Article 5(1)(e) storage limitation).",

        "vat_label": "VAT",
        "vat_rate_label": "varies by country",
        "company_id_label": "company registration number",
        "date_format": "DD/MM/YYYY",
        "accounting_formats": ["Xero Bills", "Payroll CSV", "General CSV"],
    },

    # ── Nigeria ───────────────────────────────────────────────────────────────
    "NG": {
        "tips_enabled": False,
        "tips_law": None,
        "tips_summary": "No mandatory tips allocation law in Nigeria. Tips are at employer discretion.",
        "tips_retention_years": 0,

        "allergen_law": "NAFDAC Food Safety Regulations",
        "allergen_summary": "NAFDAC requires labelling of common allergens on food products.",
        "allergen_applies": True,

        "inspection_body": "NAFDAC (National Agency for Food and Drug Administration and Control)",
        "inspection_officers": "NAFDAC inspectors",
        "hygiene_scheme": "NAFDAC Good Manufacturing Practice (GMP) standards",
        "inspection_summary": (
            "NAFDAC and State Ministries of Health inspect food safety, hygiene standards, "
            "and product labelling compliance."
        ),

        "data_law": "Nigeria Data Protection Act 2023",
        "data_summary": "Personal data must be processed lawfully and not retained longer than necessary.",

        "vat_label": "VAT",
        "vat_rate_label": "7.5%",
        "company_id_label": "CAC Registration Number",
        "date_format": "DD/MM/YYYY",
        "accounting_formats": ["General CSV", "Payroll CSV"],
    },

    # ── Kenya ─────────────────────────────────────────────────────────────────
    "KE": {
        "tips_enabled": False,
        "tips_law": None,
        "tips_summary": "No mandatory tips allocation law in Kenya.",
        "tips_retention_years": 0,

        "allergen_law": "Kenya Food, Drugs and Chemical Substances Act / KEBS standards",
        "allergen_summary": "KEBS requires allergen labelling on pre-packaged foods.",
        "allergen_applies": True,

        "inspection_body": "KEBS / county health departments",
        "inspection_officers": "public health officers",
        "hygiene_scheme": "county health department inspection standards",
        "inspection_summary": (
            "County public health officers inspect food safety, sanitation, "
            "and hygiene practices."
        ),

        "data_law": "Kenya Data Protection Act 2019",
        "data_summary": "Personal data must be collected and retained lawfully; delete when no longer needed.",

        "vat_label": "VAT",
        "vat_rate_label": "16%",
        "company_id_label": "Business Registration Number",
        "date_format": "DD/MM/YYYY",
        "accounting_formats": ["General CSV", "Payroll CSV"],
    },

    # ── South Africa ──────────────────────────────────────────────────────────
    "ZA": {
        "tips_enabled": False,
        "tips_law": None,
        "tips_summary": "No mandatory tips allocation law in South Africa.",
        "tips_retention_years": 0,

        "allergen_law": "Foodstuffs, Cosmetics and Disinfectants Act (R146 labelling regulations)",
        "allergen_summary": "Mandatory allergen labelling under R146 regulations.",
        "allergen_applies": True,

        "inspection_body": "Department of Health / municipalities",
        "inspection_officers": "environmental health officers",
        "hygiene_scheme": "Certificate of Acceptability (CoA) scheme",
        "inspection_summary": (
            "Municipal environmental health officers issue Certificates of Acceptability. "
            "Inspections cover premises, food handling, and hygiene standards."
        ),

        "data_law": "POPIA (Protection of Personal Information Act 2013)",
        "data_summary": "Personal data must be processed lawfully under POPIA; delete when purpose is fulfilled.",

        "vat_label": "VAT",
        "vat_rate_label": "15%",
        "company_id_label": "Company Registration Number (CIPC)",
        "date_format": "DD/MM/YYYY",
        "accounting_formats": ["Xero Bills", "General CSV", "Payroll CSV"],
    },

    # ── Ghana ─────────────────────────────────────────────────────────────────
    "GH": {
        "tips_enabled": False,
        "tips_law": None,
        "tips_summary": "No mandatory tips allocation law in Ghana.",
        "tips_retention_years": 0,

        "allergen_law": "Food and Drugs Authority (FDA Ghana) labelling regulations",
        "allergen_summary": "FDA Ghana requires allergen information on food product labels.",
        "allergen_applies": True,

        "inspection_body": "Food and Drugs Authority (FDA Ghana)",
        "inspection_officers": "FDA inspectors",
        "hygiene_scheme": "FDA Ghana food business licensing standards",
        "inspection_summary": (
            "FDA Ghana inspects food premises for hygiene, labelling compliance, "
            "and food safety standards."
        ),

        "data_law": "Data Protection Act 2012 (Ghana)",
        "data_summary": "Personal data must be processed lawfully and not kept longer than necessary.",

        "vat_label": "VAT",
        "vat_rate_label": "15%",
        "company_id_label": "Ghana Registration Number",
        "date_format": "DD/MM/YYYY",
        "accounting_formats": ["General CSV", "Payroll CSV"],
    },

    # ── Uganda ────────────────────────────────────────────────────────────────
    "UG": {
        "tips_enabled": False,
        "tips_law": None,
        "tips_summary": "No mandatory tips allocation law in Uganda.",
        "tips_retention_years": 0,

        "allergen_law": "National Drug Authority / Uganda National Bureau of Standards food regulations",
        "allergen_summary": "UNBS food labelling standards require allergen declarations on food products.",
        "allergen_applies": True,

        "inspection_body": "Ministry of Health / Uganda National Bureau of Standards (UNBS)",
        "inspection_officers": "health inspectors",
        "hygiene_scheme": "UNBS food safety standards",
        "inspection_summary": (
            "Ministry of Health and UNBS inspect food businesses for hygiene, "
            "safety standards, and labelling compliance."
        ),

        "data_law": "National Information Technology Authority (NITA) data guidelines",
        "data_summary": "Data should be handled responsibly; Uganda is developing formal data protection law.",

        "vat_label": "VAT",
        "vat_rate_label": "18%",
        "company_id_label": "Uganda Revenue Authority TIN",
        "date_format": "DD/MM/YYYY",
        "accounting_formats": ["General CSV", "Payroll CSV"],
    },

    # ── Tanzania ──────────────────────────────────────────────────────────────
    "TZ": {
        "tips_enabled": False,
        "tips_law": None,
        "tips_summary": "No mandatory tips allocation law in Tanzania.",
        "tips_retention_years": 0,

        "allergen_law": "Tanzania Food, Drugs and Cosmetics Authority (TFDA) regulations",
        "allergen_summary": "TFDA requires allergen labelling on food products.",
        "allergen_applies": True,

        "inspection_body": "Tanzania Food, Drugs and Cosmetics Authority (TFDA)",
        "inspection_officers": "TFDA inspectors",
        "hygiene_scheme": "TFDA food safety and hygiene standards",
        "inspection_summary": (
            "TFDA inspects food businesses for hygiene, safety, and labelling compliance."
        ),

        "data_law": "Tanzania Personal Data Protection Act 2022",
        "data_summary": "Personal data must be handled lawfully under the 2022 Act.",

        "vat_label": "VAT",
        "vat_rate_label": "18%",
        "company_id_label": "Tanzania Business Registration Number",
        "date_format": "DD/MM/YYYY",
        "accounting_formats": ["General CSV", "Payroll CSV"],
    },
}

# ── Default fallback (country not in table) ───────────────────────────────────

_DEFAULT_COMPLIANCE: dict = {
    "tips_enabled": False,
    "tips_law": None,
    "tips_summary": "Check your local employment law for any tips allocation obligations.",
    "tips_retention_years": 0,

    "allergen_law": "local allergen labelling regulations",
    "allergen_summary": "Check local food safety regulations for allergen declaration requirements.",
    "allergen_applies": True,

    "inspection_body": "local food safety authority",
    "inspection_officers": "food safety inspectors",
    "hygiene_scheme": "local food hygiene inspection scheme",
    "inspection_summary": (
        "Local food safety authority inspections typically cover hygiene, allergens, "
        "temperature control, and supplier records."
    ),

    "data_law": "local data protection law",
    "data_summary": "Personal data should not be kept longer than necessary.",

    "vat_label": "Tax",
    "vat_rate_label": "standard rate",
    "company_id_label": "company registration number",
    "date_format": "DD/MM/YYYY",
    "accounting_formats": ["General CSV", "Payroll CSV"],
}

# ── Country display names ─────────────────────────────────────────────────────

COUNTRY_NAMES: dict[str, str] = {
    "GB":  "United Kingdom",
    "US":  "United States",
    "AU":  "Australia",
    "EU":  "European Union",
    "NG":  "Nigeria",
    "KE":  "Kenya",
    "ZA":  "South Africa",
    "GH":  "Ghana",
    "UG":  "Uganda",
    "TZ":  "Tanzania",
    "XOF": "West Africa (CFA zone)",
}

# Supported country codes for /setcountry
SUPPORTED_COUNTRIES: dict[str, str] = {
    "GB": "United Kingdom",
    "US": "United States",
    "AU": "Australia",
    "EU": "European Union (generic)",
    "NG": "Nigeria",
    "KE": "Kenya",
    "ZA": "South Africa",
    "GH": "Ghana",
    "UG": "Uganda",
    "TZ": "Tanzania",
}

# ── VAT prefix → country inference (used during registration) ────────────────

_VAT_PREFIX_TO_COUNTRY: dict[str, str] = {
    "GB": "GB",
    "US": "US",
    "AU": "AU",
    # EU member states
    "AT": "EU", "BE": "EU", "BG": "EU", "CY": "EU",
    "CZ": "EU", "DE": "EU", "DK": "EU", "EE": "EU",
    "ES": "EU", "FI": "EU", "FR": "EU", "GR": "EU",
    "HR": "EU", "HU": "EU", "IE": "EU", "IT": "EU",
    "LT": "EU", "LU": "EU", "LV": "EU", "MT": "EU",
    "NL": "EU", "PL": "EU", "PT": "EU", "RO": "EU",
    "SE": "EU", "SI": "EU", "SK": "EU",
}


def country_from_vat_number(vat_number: str) -> str | None:
    """
    Attempt to infer country code from a VAT number prefix.
    Returns a country code string (e.g. "GB", "EU") or None if unrecognised.
    """
    if not vat_number:
        return None
    prefix = vat_number.strip().upper()[:2]
    return _VAT_PREFIX_TO_COUNTRY.get(prefix)


# ── Public API ────────────────────────────────────────────────────────────────

def get_compliance(restaurant: dict) -> dict:
    """
    Return the full compliance configuration for this restaurant.
    Never returns None — always falls back to _DEFAULT_COMPLIANCE for unknown countries.
    """
    country = infer_country(restaurant)
    return COUNTRY_COMPLIANCE.get(country, _DEFAULT_COMPLIANCE)


def get_country_display(restaurant: dict) -> str:
    """Human-readable country name for this restaurant."""
    code = infer_country(restaurant)
    return COUNTRY_NAMES.get(code, code)


def tips_enabled(restaurant: dict) -> bool:
    """True if tips recording is a legal obligation for this business's country."""
    return get_compliance(restaurant)["tips_enabled"]


def allergen_enabled(restaurant: dict) -> bool:
    """
    True if allergen traceability applies.
    Requires: food business in any country that has allergen regulations (currently all).
    """
    comp = get_compliance(restaurant)
    return is_food_business(restaurant) and comp.get("allergen_applies", False)


def inspection_enabled(restaurant: dict) -> bool:
    """True if food inspection readiness reporting is relevant for this business."""
    return is_food_business(restaurant)
