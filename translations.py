"""
translations.py
===============
All user-facing strings for the registration flow and key commands.

Usage:
    from translations import t

    text = t("reg.country.prompt", lang="fr")
    text = t("reg.features.universal.1", lang="en")

Rules:
  - Add new strings HERE, never inline in handlers.
  - Every key must exist in both "en" and "fr".
  - Use {placeholders} for runtime values.
  - Keep keys namespaced: reg.* for registration, cmd.* for commands, err.* for errors.
"""

from __future__ import annotations

# ── String table ──────────────────────────────────────────────────────────────

_T: dict[str, dict[str, str]] = {

    # ── Registration: preamble ─────────────────────────────────────────────────
    "reg.welcome": {
        "en": (
            "*Welcome to TradeFlow!*\n\n"
            "Let's get you set up in a few quick steps.\n"
            "Your answers shape exactly which features and laws apply to your business.\n\n"
            "_Bienvenue sur TradeFlow ! Répondez en français à tout moment._"
        ),
        "fr": (
            "*Bienvenue sur TradeFlow !*\n\n"
            "Configurons votre compte en quelques étapes rapides.\n"
            "Vos réponses déterminent exactement quelles fonctionnalités et lois s'appliquent."
        ),
    },

    # ── Step 1: Country ────────────────────────────────────────────────────────
    "reg.country.prompt": {
        "en": (
            "STEP 1 — SELECT YOUR COUNTRY\n"
            "══════════════════════════════\n\n"
            "Your country sets your currency, compliance laws, and inspection rules automatically.\n\n"
            "Tap your country below, or type its name."
        ),
        "fr": (
            "ÉTAPE 1 — SÉLECTIONNEZ VOTRE PAYS\n"
            "══════════════════════════════════\n\n"
            "Votre pays définit automatiquement votre devise, les lois applicables et les règles d'inspection.\n\n"
            "Appuyez sur votre pays ci-dessous, ou tapez son nom."
        ),
    },
    "reg.country.not_found": {
        "en": "Country not recognised. Please tap a button or type the country name.",
        "fr": "Pays non reconnu. Veuillez appuyer sur un bouton ou taper le nom du pays.",
    },
    "reg.country.confirmed": {
        "en": "✅ Country: *{country}*\nCurrency automatically set to: *{currency}*",
        "fr": "✅ Pays : *{country}*\nDevise automatiquement définie sur : *{currency}*",
    },

    # ── Step 2: Sub-region ─────────────────────────────────────────────────────
    "reg.region.prompt": {
        "en": (
            "STEP 2 — YOUR REGION / STATE\n"
            "═══════════════════════════════\n\n"
            "Select your region or state below.\n"
            "This helps apply the right local rules (e.g. inspections, sub-regional compliance).\n\n"
            "Or type your region/city if not listed."
        ),
        "fr": (
            "ÉTAPE 2 — VOTRE RÉGION / ÉTAT\n"
            "════════════════════════════════\n\n"
            "Sélectionnez votre région ou état ci-dessous.\n"
            "Cela aide à appliquer les règles locales appropriées.\n\n"
            "Ou tapez votre région/ville si elle n'est pas listée."
        ),
    },
    "reg.region.skip_hint": {
        "en": "Type your region name, or tap *Skip* to continue.",
        "fr": "Tapez le nom de votre région, ou appuyez sur *Ignorer* pour continuer.",
    },
    "reg.region.confirmed": {
        "en": "✅ Region: *{region}*",
        "fr": "✅ Région : *{region}*",
    },

    # ── Step 3: Language ───────────────────────────────────────────────────────
    "reg.language.prompt": {
        "en": (
            "STEP 3 — YOUR LANGUAGE\n"
            "═══════════════════════\n\n"
            "All reports and messages will be delivered in your chosen language.\n"
            "You can change this later with /setlanguage.\n\n"
            "ÉTAPE 3 — VOTRE LANGUE\n"
            "Tous les rapports seront livrés dans la langue choisie."
        ),
        "fr": (
            "ÉTAPE 3 — VOTRE LANGUE\n"
            "════════════════════════\n\n"
            "Tous les rapports et messages seront livrés dans votre langue choisie.\n"
            "Vous pourrez changer cela plus tard avec /setlanguage.\n\n"
            "STEP 3 — YOUR LANGUAGE\n"
            "All reports will be delivered in your chosen language."
        ),
    },
    "reg.language.confirmed": {
        "en": "✅ Language: *English*\nAll messages will now be in English.",
        "fr": "✅ Langue : *Français*\nTous les messages seront désormais en français.",
    },

    # ── Step 4: Sector ─────────────────────────────────────────────────────────
    "reg.sector.prompt": {
        "en": (
            "STEP 4 — YOUR BUSINESS SECTOR\n"
            "══════════════════════════════\n\n"
            "Select the sector that best describes your business.\n"
            "This determines which features, reports, and compliance tools are relevant."
        ),
        "fr": (
            "ÉTAPE 4 — VOTRE SECTEUR D'ACTIVITÉ\n"
            "═══════════════════════════════════\n\n"
            "Sélectionnez le secteur qui décrit le mieux votre entreprise.\n"
            "Cela détermine quelles fonctionnalités et outils de conformité sont pertinents."
        ),
    },
    "reg.sector.not_found": {
        "en": "Please tap a sector from the list above.",
        "fr": "Veuillez appuyer sur un secteur dans la liste ci-dessus.",
    },

    # ── Step 5: Sub-sector ─────────────────────────────────────────────────────
    "reg.subsector.prompt": {
        "en": (
            "STEP 5 — YOUR BUSINESS TYPE\n"
            "═══════════════════════════\n\n"
            "Select the type that best matches your operation."
        ),
        "fr": (
            "ÉTAPE 5 — TYPE D'ÉTABLISSEMENT\n"
            "════════════════════════════════\n\n"
            "Sélectionnez le type qui correspond le mieux à votre activité."
        ),
    },

    # ── Step 6: Business name ─────────────────────────────────────────────────
    "reg.name.prompt": {
        "en": (
            "STEP 6 — BUSINESS NAME\n"
            "════════════════════════\n\n"
            "*What is your business trading name?*\n\n"
            "This name appears on all reports and records."
        ),
        "fr": (
            "ÉTAPE 6 — NOM DE L'ENTREPRISE\n"
            "═══════════════════════════════\n\n"
            "*Quel est le nom commercial de votre entreprise ?*\n\n"
            "Ce nom apparaîtra sur tous les rapports et enregistrements."
        ),
    },
    "reg.name.registered": {
        "en": "✅ *{name}* is now registered!\n\nLet's add a few optional details to your profile.",
        "fr": "✅ *{name}* est maintenant enregistré !\n\nAjoutons quelques détails optionnels à votre profil.",
    },

    # ── Step 7: Location ──────────────────────────────────────────────────────
    "reg.location.prompt": {
        "en": (
            "STEP 7 — LOCATION  _(optional)_\n"
            "══════════════════════════════\n\n"
            "What is your business address?\n"
            "Include street, city and postcode/zip."
        ),
        "fr": (
            "ÉTAPE 7 — LOCALISATION  _(facultatif)_\n"
            "═══════════════════════════════════════\n\n"
            "Quelle est l'adresse de votre entreprise ?\n"
            "Incluez la rue, la ville et le code postal."
        ),
    },

    # ── Step 8: Contact ───────────────────────────────────────────────────────
    "reg.contact.prompt": {
        "en": (
            "STEP 8 — CONTACT DETAILS  _(optional)_\n"
            "════════════════════════════════════\n\n"
            "Phone number and/or email address?\n"
            "_(e.g. +44 20 7123 4567 | hello@yourbusiness.com)_"
        ),
        "fr": (
            "ÉTAPE 8 — COORDONNÉES  _(facultatif)_\n"
            "══════════════════════════════════════\n\n"
            "Numéro de téléphone et/ou adresse e-mail ?\n"
            "_(ex. +33 1 23 45 67 89 | bonjour@votreentreprise.fr)_"
        ),
    },

    # ── Step 9: Legal / Tax ───────────────────────────────────────────────────
    "reg.legal.prompt": {
        "en": (
            "STEP 9 — LEGAL & TAX  _(optional)_\n"
            "═══════════════════════════════════\n\n"
            "Company registration number and/or {vat_label} number?\n"
            "Entering your {vat_label} number lets TradeFlow auto-confirm your country.\n\n"
            "_(e.g. {company_id_example} | {vat_example})_"
        ),
        "fr": (
            "ÉTAPE 9 — JURIDIQUE & FISCAL  _(facultatif)_\n"
            "══════════════════════════════════════════\n\n"
            "Numéro d'immatriculation et/ou numéro de {vat_label} ?\n"
            "Entrer votre numéro de {vat_label} permet à TradeFlow de confirmer votre pays.\n\n"
            "_(ex. {company_id_example} | {vat_example})_"
        ),
    },

    # ── Step 10: Features ─────────────────────────────────────────────────────
    "reg.features.prompt": {
        "en": (
            "STEP 10 — YOUR FEATURES\n"
            "═══════════════════════\n\n"
            "Here are the features for *{name}* ({sub_industry}).\n"
            "Everything is ON by default — tap to turn off anything you don't need.\n"
            "You can change these later with /setfeatures."
        ),
        "fr": (
            "ÉTAPE 10 — VOS FONCTIONNALITÉS\n"
            "════════════════════════════════\n\n"
            "Voici les fonctionnalités pour *{name}* ({sub_industry}).\n"
            "Tout est ACTIVÉ par défaut — appuyez pour désactiver ce dont vous n'avez pas besoin.\n"
            "Vous pouvez les modifier plus tard avec /setfeatures."
        ),
    },
    "reg.features.confirm_btn": {
        "en": "✅ Confirm — Activate All",
        "fr": "✅ Confirmer — Tout activer",
    },
    "reg.features.customise_btn": {
        "en": "⚙️ Customise Features",
        "fr": "⚙️ Personnaliser les fonctionnalités",
    },
    "reg.features.save_btn": {
        "en": "💾 Save & Continue",
        "fr": "💾 Enregistrer & Continuer",
    },

    # ── Registration complete ─────────────────────────────────────────────────
    "reg.complete": {
        "en": (
            "*All set! {name} is fully registered.*\n\n"
            "🌍 Country: {country}\n"
            "💰 Currency: {currency}\n"
            "🏢 Industry: {sub_industry}\n"
            "⚖️  Compliance: {compliance_summary}\n\n"
            "*Profile saved:*\n{profile_summary}\n\n"
            "You can update these any time with /profile, /setcountry, /setindustry, /setlanguage, /setfeatures\n\n"
            "*Ready to go:*\n"
            "  • Send a voice note about today\n"
            "  • Send a photo of an invoice\n"
            "  • Type /features to see everything TradeFlow can do"
        ),
        "fr": (
            "*C'est tout ! {name} est entièrement enregistré.*\n\n"
            "🌍 Pays : {country}\n"
            "💰 Devise : {currency}\n"
            "🏢 Secteur : {sub_industry}\n"
            "⚖️  Conformité : {compliance_summary}\n\n"
            "*Profil enregistré :*\n{profile_summary}\n\n"
            "Vous pouvez mettre à jour ces informations avec /profile, /setcountry, /setindustry, /setlanguage, /setfeatures\n\n"
            "*Prêt à démarrer :*\n"
            "  • Envoyez un message vocal sur votre journée\n"
            "  • Envoyez une photo d'une facture\n"
            "  • Tapez /features pour voir tout ce que TradeFlow peut faire"
        ),
    },

    # ── Already registered ─────────────────────────────────────────────────────
    "reg.already_registered": {
        "en": (
            "*{name}* is already registered.\n\n"
            "Use /rename to change the name.\n"
            "Use /profile to update your company details.\n"
            "Use /setcountry, /setlanguage, /setindustry or /setfeatures to change your setup."
        ),
        "fr": (
            "*{name}* est déjà enregistré.\n\n"
            "Utilisez /rename pour changer le nom.\n"
            "Utilisez /profile pour mettre à jour vos coordonnées.\n"
            "Utilisez /setcountry, /setlanguage, /setindustry ou /setfeatures pour modifier votre configuration."
        ),
    },

    # ── Skip / cancel hints ───────────────────────────────────────────────────
    "reg.skip_hint": {
        "en": "Reply with the details, or type *skip* to move on.",
        "fr": "Répondez avec les détails, ou tapez *ignorer* pour passer à l'étape suivante.",
    },
    "reg.skip_btn": {
        "en": "Skip →",
        "fr": "Ignorer →",
    },
    "reg.cancel": {
        "en": "Registration cancelled. Run /register to start again.",
        "fr": "Inscription annulée. Lancez /register pour recommencer.",
    },

    # ── Compliance auto-applied notice ────────────────────────────────────────
    "reg.compliance.applied": {
        "en": (
            "✅ *Compliance automatically configured for {country}:*\n"
            "{compliance_list}"
        ),
        "fr": (
            "✅ *Conformité automatiquement configurée pour {country} :*\n"
            "{compliance_list}"
        ),
    },

    # ── /setlanguage command ───────────────────────────────────────────────────
    "cmd.setlanguage.prompt": {
        "en": (
            "Language — {name}\n"
            "{'─' * 30}\n"
            "Current: *English*\n\n"
            "Tap to change:"
        ),
        "fr": (
            "Langue — {name}\n"
            "{'─' * 30}\n"
            "Actuelle : *Français*\n\n"
            "Appuyez pour changer :"
        ),
    },
    "cmd.setlanguage.updated": {
        "en": "Language updated to *English*. All messages will now be in English.",
        "fr": "Langue mise à jour : *Français*. Tous les messages seront désormais en français.",
    },

    # ── /setfeatures command ───────────────────────────────────────────────────
    "cmd.setfeatures.prompt": {
        "en": (
            "Features — {name}\n"
            "Tap to toggle ON/OFF. Changes save automatically."
        ),
        "fr": (
            "Fonctionnalités — {name}\n"
            "Appuyez pour activer/désactiver. Les modifications s'enregistrent automatiquement."
        ),
    },
    "cmd.setfeatures.saved": {
        "en": "✅ Features updated.",
        "fr": "✅ Fonctionnalités mises à jour.",
    },

    # ── Feature names ─────────────────────────────────────────────────────────
    "feature.weekly_report": {
        "en": "Weekly Intelligence Report",
        "fr": "Rapport d'intelligence hebdomadaire",
    },
    "feature.financials": {
        "en": "Financial P&L Tracking",
        "fr": "Suivi financier P&L",
    },
    "feature.invoices": {
        "en": "Invoice & Payment Management",
        "fr": "Gestion des factures et paiements",
    },
    "feature.rota": {
        "en": "Staff Rota / Scheduling",
        "fr": "Planning du personnel",
    },
    "feature.stock": {
        "en": "Stock & Inventory Tracking",
        "fr": "Suivi des stocks et inventaires",
    },
    "feature.labour": {
        "en": "Labour Cost Tracking",
        "fr": "Suivi des coûts de main-d'œuvre",
    },
    "feature.tips": {
        "en": "Tips Tracking & Compliance",
        "fr": "Suivi des pourboires et conformité",
    },
    "feature.export": {
        "en": "Data Export (Xero / Sage / CSV)",
        "fr": "Export des données (Xero / Sage / CSV)",
    },
    "feature.dashboard": {
        "en": "Live Web Dashboard",
        "fr": "Tableau de bord web en direct",
    },
    "feature.allergens": {
        "en": "Allergen Traceability",
        "fr": "Traçabilité des allergènes",
    },
    "feature.eightysix": {
        "en": "Stock-Out / 86'd Item Tracking",
        "fr": "Suivi des ruptures de stock",
    },
    "feature.inspection": {
        "en": "Inspection Readiness Reports",
        "fr": "Rapports de préparation aux inspections",
    },
    "feature.import_history": {
        "en": "Historical Data Import",
        "fr": "Import de données historiques",
    },

    # ── Sector names ──────────────────────────────────────────────────────────
    "sector.food_beverage": {
        "en": "Food & Beverage",
        "fr": "Alimentation & Boissons",
    },
    "sector.retail": {
        "en": "Retail & Shop",
        "fr": "Commerce de détail",
    },
    "sector.health_beauty": {
        "en": "Health & Beauty",
        "fr": "Santé & Beauté",
    },
    "sector.professional_services": {
        "en": "Professional Services",
        "fr": "Services professionnels",
    },
    "sector.hospitality": {
        "en": "Hospitality & Accommodation",
        "fr": "Hôtellerie & Hébergement",
    },
    "sector.other": {
        "en": "Other / General Business",
        "fr": "Autre / Entreprise générale",
    },

    # ── Sub-sector names ──────────────────────────────────────────────────────
    "subsector.restaurant": {"en": "Restaurant / Dining", "fr": "Restaurant / Restauration"},
    "subsector.cafe": {"en": "Café / Coffee Shop", "fr": "Café / Salon de thé"},
    "subsector.bar": {"en": "Bar", "fr": "Bar"},
    "subsector.pub": {"en": "Pub / Tavern", "fr": "Pub / Taverne"},
    "subsector.bakery": {"en": "Bakery / Patisserie", "fr": "Boulangerie / Pâtisserie"},
    "subsector.food_truck": {"en": "Food Truck / Street Food", "fr": "Food Truck / Restauration de rue"},
    "subsector.takeaway": {"en": "Takeaway / Fast Food", "fr": "Vente à emporter / Restauration rapide"},
    "subsector.catering": {"en": "Catering / Events Food", "fr": "Traiteur / Restauration événementielle"},
    "subsector.retail": {"en": "General Retail", "fr": "Commerce de détail général"},
    "subsector.supermarket": {"en": "Supermarket / Grocery", "fr": "Supermarché / Épicerie"},
    "subsector.pharmacy": {"en": "Pharmacy / Chemist", "fr": "Pharmacie"},
    "subsector.clothing": {"en": "Clothing & Fashion", "fr": "Vêtements & Mode"},
    "subsector.electronics": {"en": "Electronics", "fr": "Électronique"},
    "subsector.hardware": {"en": "Hardware / DIY", "fr": "Quincaillerie / Bricolage"},
    "subsector.salon": {"en": "Hair Salon", "fr": "Salon de coiffure"},
    "subsector.barbershop": {"en": "Barbershop", "fr": "Barbier"},
    "subsector.spa": {"en": "Spa / Wellness", "fr": "Spa / Bien-être"},
    "subsector.gym": {"en": "Gym / Fitness Studio", "fr": "Salle de sport / Fitness"},
    "subsector.clinic": {"en": "Clinic / Medical Practice", "fr": "Clinique / Cabinet médical"},
    "subsector.laundry": {"en": "Laundry / Dry Cleaning", "fr": "Blanchisserie / Pressing"},
    "subsector.cleaning": {"en": "Cleaning Services", "fr": "Services de nettoyage"},
    "subsector.logistics": {"en": "Delivery / Logistics", "fr": "Livraison / Logistique"},
    "subsector.trades": {"en": "Trades (Plumbing / Electrical)", "fr": "Artisanat (Plomberie / Électricité)"},
    "subsector.general_services": {"en": "General Services", "fr": "Services généraux"},
    "subsector.hotel": {"en": "Hotel", "fr": "Hôtel"},
    "subsector.guesthouse": {"en": "Guesthouse / B&B", "fr": "Maison d'hôtes / B&B"},
    "subsector.events_venue": {"en": "Events Venue / Function Room", "fr": "Salle de réception / Événementiel"},
    "subsector.general": {"en": "General Business", "fr": "Entreprise générale"},

    # ── Errors ────────────────────────────────────────────────────────────────
    "err.not_registered": {
        "en": "This group is not registered yet. Use /register to get started.",
        "fr": "Ce groupe n'est pas encore enregistré. Utilisez /register pour commencer.",
    },
}

# ── Public API ────────────────────────────────────────────────────────────────

def t(key: str, lang: str = "en", **kwargs) -> str:
    """
    Return the translated string for key in the given language.
    Falls back to English if the key isn't translated in the requested language.
    Falls back to [key] if not found at all.
    Applies {placeholder} substitution via kwargs.
    """
    lang = lang if lang in ("en", "fr") else "en"
    entry = _T.get(key)
    if entry is None:
        return f"[{key}]"
    text = entry.get(lang) or entry.get("en") or f"[{key}]"
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return text


def get_lang(restaurant: dict | None) -> str:
    """Return the language code ('en' or 'fr') for this restaurant."""
    if not restaurant:
        return "en"
    return (restaurant.get("language") or "en").lower()[:2]


def infer_lang_from_telegram(language_code: str | None) -> str:
    """
    Guess language from Telegram user's language_code (e.g. 'fr-FR', 'fr', 'en-US').
    Returns 'fr' if French, 'en' otherwise.
    """
    if language_code and language_code.lower().startswith("fr"):
        return "fr"
    return "en"
