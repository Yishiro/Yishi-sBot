from __future__ import annotations

import re

import discord

AUTO_STAFF_ROLE_NAME = "👑・𝐒taff"
AUTO_ARCHIVE_ROLE_NAME = "👑・𝐅ondateur"
AUTO_TICKET_CATEGORY_NAME = "Tickets"
AUTO_ARCHIVE_CATEGORY_NAME = "Ticket-Close"
AUTO_LOGS_CHANNEL_NAME = "📂・𝐋ogs-staff"
AUTO_TRANSCRIPT_CHANNEL_NAME = "logs-transcript"
AUTO_GACHA_SPIN_CHANNEL_NAME = "🎰・𝐆acha-spin"
AUTO_GACHA_WINNER_CHANNEL_NAME = "🏆・𝐆acha-winner"
AUTO_GACHA_LOGS_CHANNEL_NAME = "gacha-logs"
AUTO_SALES_CHANNEL_NAME = "💸・𝐄nchères"
AUTO_SALES_CATEGORY_NAME = "Ventes-en-cours"
AUTO_SALES_REVIEW_CHANNEL_NAME = "ventes-validation"

DEFAULT_PROMO_CHANNEL_ID = 1517777716210831460
TICKET_RECALL_HOURS = 24
SALES_RECALL_HOURS = 24

INVITE_ROLE_WEIGHTS = {
    "🥉 Inviteur Bronze • 5": 1.5,
    "🥈 Inviteur Silver • 10": 2.0,
    "🥇 Inviteur Gold • 15": 2.5,
    "💎 Inviteur Diamond • 20": 3.0,
}

INVITE_ROLE_REQUIREMENTS = {
    "🥉 Inviteur Bronze • 5": 5,
    "🥈 Inviteur Silver • 10": 10,
    "🥇 Inviteur Gold • 15": 15,
    "💎 Inviteur Diamond • 20": 20,
}

WELCOME_CHECKLIST = (
    "• Lire les salons importants\n"
    "• Consulter la boutique disponible\n"
    "• Ouvrir un ticket si tu as une question ou si tu veux passer commande"
)

WELCOME_ADVANTAGES = (
    "• Shop fiable, rapide et professionnel\n"
    "• Service sérieux, sécurisé et de qualité\n"
    "• Staff disponible pour t'aider"
)

RULES_TEXT = """📜 𝐑èglement Officiel
Bienvenue sur Yishi's Shop.
Afin de garantir une expérience sérieuse, fluide et agréable à l'ensemble des membres, chaque utilisateur est tenu de respecter le règlement ci-dessous.

✧ 1. Respect & comportement
Le respect envers tous les membres du serveur est obligatoire.
Tout comportement toxique, irrespectueux, provocateur, agressif, insultant ou humiliant est strictement interdit.

✧ 2. Spam & flood interdits
Les messages répétitifs, le flood, le spam, les abus de majuscules, les mentions abusives ainsi que l'utilisation excessive d'emojis sont interdits.

✧ 3. Contenus inappropriés
Tout contenu choquant, violent, haineux, discriminatoire, sexuel, offensant ou inadapté au serveur est formellement interdit.

✧ 4. Publicité non autorisée
La publicité, sous quelque forme que ce soit, est interdite sans autorisation préalable du staff.
Cela inclut les serveurs Discord, shops, réseaux sociaux, sites, services ou messages privés à but promotionnel.

✧ 5. Utilisation correcte des salons
Chaque salon possède une utilité précise.
Merci de respecter leur fonction et d'éviter le hors-sujet afin de préserver une organisation claire et professionnelle.

✧ 6. Commandes sérieuses uniquement
Les commandes, demandes ou réservations doivent être sérieuses.
Toute perte de temps volontaire, troll, faux intérêt ou abus envers le staff pourra être sanctionné.

✧ 7. Tolérance zéro envers les arnaques
Toute tentative d'arnaque, fraude, faux paiement, fausse preuve, chargeback, manipulation ou tromperie entraînera une sanction immédiate pouvant aller jusqu'au bannissement définitif.

✧ 8. Paiements & preuves
Les consignes données par le staff concernant les paiements, preuves, validations et tickets doivent être respectées.
Toute tentative de contourner le système ou de fournir de fausses informations est interdite.

✧ 9. Respect du staff
Le staff est présent pour assurer le bon fonctionnement du serveur.
Le manque de respect, la provocation, l'abus ou le refus délibéré de coopération avec l'équipe de modération ne seront pas tolérés.

✧ 10. Tickets & support
Les tickets doivent être ouverts uniquement pour une raison valable : commande, question importante, assistance ou problème réel.
Tout abus de ticket pourra entraîner une restriction d'accès au support.

✧ 11. Sécurité personnelle
Ne partagez jamais vos informations sensibles : mots de passe, codes, adresses e-mail, moyens de paiement ou données privées.
Vous êtes responsable de la sécurité de votre compte et de vos échanges.

✧ 12. Transactions & services
Les échanges et services proposés au sein du shop doivent rester clairs, honnêtes et conformes à ce qui est annoncé.
Toute tentative de nuisance, de faux deal ou de perturbation volontaire sera sanctionnée.

✧ 13. Sanctions
Le non-respect du règlement peut entraîner, selon la gravité des faits :

avertissement
mute
exclusion temporaire
bannissement définitif

Le staff se réserve le droit d'adapter les sanctions selon la situation.

✧ 14. Acceptation du règlement
En restant sur Yishi's Shop, vous acceptez automatiquement l'ensemble des règles mentionnées ci-dessus et vous engagez à les respecter pleinement.

Merci de votre confiance et bon shopping sur Yishi's Shop"""

RULES_ACCEPT_TEXT = (
    "En réagissant avec ✅ à ce message, tu acceptes le règlement du serveur "
    "et tu obtiens l'accès complet au serveur."
)
LINK_PATTERN = re.compile(r"(https?://\S+|www\.\S+|discord\.gg/\S+|discord\.com/invite/\S+)", re.IGNORECASE)
GACHA_SPIN_TYPES = ("basic", "advanced", "deluxe")
GACHA_RARITY_COLORS = {
    "Common": discord.Color.light_grey(),
    "Rare": discord.Color.blue(),
    "Epic": discord.Color.purple(),
    "Legendary": discord.Color.gold(),
    "Mythical": discord.Color.red(),
    "Secret": discord.Color.from_rgb(255, 105, 180),
}
GACHA_RARITY_EMOJIS = {
    "Common": "?",
    "Rare": "??",
    "Epic": "??",
    "Legendary": "??",
    "Mythical": "??",
    "Secret": "??",
}
GACHA_REWARDS = {
    "basic": {
        "Common": [
            {"name": "Rocket", "reward_type": "Physical Fruit", "chance": 4.0},
            {"name": "Spin", "reward_type": "Physical Fruit", "chance": 3.8},
            {"name": "Blade", "reward_type": "Physical Fruit", "chance": 3.6},
            {"name": "Spring", "reward_type": "Physical Fruit", "chance": 3.2},
            {"name": "Bomb", "reward_type": "Physical Fruit", "chance": 3.1},
            {"name": "Smoke", "reward_type": "Physical Fruit", "chance": 3.0},
            {"name": "Spike", "reward_type": "Physical Fruit", "chance": 2.9},
            {"name": "Flame", "reward_type": "Physical Fruit", "chance": 2.8},
            {"name": "Ice", "reward_type": "Physical Fruit", "chance": 2.7},
            {"name": "Sand", "reward_type": "Physical Fruit", "chance": 2.5},
            {"name": "Dark", "reward_type": "Physical Fruit", "chance": 2.3},
            {"name": "Eagle", "reward_type": "Physical Fruit", "chance": 2.0},
            {"name": "Diamond", "reward_type": "Physical Fruit", "chance": 1.1},
        ],
        "Rare": [
            {"name": "Light", "reward_type": "Physical Fruit", "chance": 3.1},
            {"name": "Rubber", "reward_type": "Physical Fruit", "chance": 2.7},
            {"name": "Ghost", "reward_type": "Physical Fruit", "chance": 2.5},
            {"name": "Magma", "reward_type": "Physical Fruit", "chance": 2.3},
            {"name": "Quake", "reward_type": "Physical Fruit", "chance": 2.1},
            {"name": "Love", "reward_type": "Physical Fruit", "chance": 2.0},
            {"name": "Creation", "reward_type": "Physical Fruit", "chance": 1.9},
            {"name": "Spider", "reward_type": "Physical Fruit", "chance": 1.8},
            {"name": "Sound", "reward_type": "Physical Fruit", "chance": 1.5},
            {"name": "Phoenix", "reward_type": "Physical Fruit", "chance": 1.4},
            {"name": "Pain", "reward_type": "Physical Fruit", "chance": 1.4},
            {"name": "Blizzard", "reward_type": "Physical Fruit", "chance": 1.3},
        ],
        "Epic": [
            {"name": "Buddha", "reward_type": "Physical Fruit", "chance": 3.0},
            {"name": "Portal", "reward_type": "Physical Fruit", "chance": 2.7},
            {"name": "Gravity", "reward_type": "Physical Fruit", "chance": 2.2},
            {"name": "Mammoth", "reward_type": "Physical Fruit", "chance": 2.0},
            {"name": "T-Rex", "reward_type": "Physical Fruit", "chance": 1.9},
            {"name": "Shadow", "reward_type": "Physical Fruit", "chance": 1.8},
            {"name": "Venom", "reward_type": "Physical Fruit", "chance": 1.8},
            {"name": "Spirit", "reward_type": "Physical Fruit", "chance": 1.6},
            {"name": "Lightning", "reward_type": "Physical Fruit", "chance": 1.0},
        ],
        "Legendary": [
            {"name": "Dough", "reward_type": "Physical Fruit", "chance": 4.0},
            {"name": "Gas", "reward_type": "Physical Fruit", "chance": 3.5},
            {"name": "Tiger", "reward_type": "Physical Fruit", "chance": 3.5},
            {"name": "Yeti", "reward_type": "Physical Fruit", "chance": 3.0},
            {"name": "Control", "reward_type": "Physical Fruit", "chance": 3.0},
        ],
        "Mythical": [
            {"name": "Kitsune", "reward_type": "Physical Fruit", "chance": 6.0},
        ],
    },
    "advanced": {
        "Common": [
            {"name": "Rocket", "reward_type": "Physical Fruit", "chance": 4.0},
            {"name": "Spin", "reward_type": "Physical Fruit", "chance": 3.8},
            {"name": "Blade", "reward_type": "Physical Fruit", "chance": 3.6},
            {"name": "Spring", "reward_type": "Physical Fruit", "chance": 3.2},
            {"name": "Bomb", "reward_type": "Physical Fruit", "chance": 3.1},
            {"name": "Smoke", "reward_type": "Physical Fruit", "chance": 3.0},
            {"name": "Spike", "reward_type": "Physical Fruit", "chance": 2.9},
            {"name": "Flame", "reward_type": "Physical Fruit", "chance": 2.8},
            {"name": "Ice", "reward_type": "Physical Fruit", "chance": 2.7},
            {"name": "Sand", "reward_type": "Physical Fruit", "chance": 2.5},
            {"name": "Dark", "reward_type": "Physical Fruit", "chance": 2.3},
            {"name": "Eagle", "reward_type": "Physical Fruit", "chance": 2.0},
            {"name": "Diamond", "reward_type": "Physical Fruit", "chance": 1.1},
        ],
        "Rare": [
            {"name": "Light", "reward_type": "Physical Fruit", "chance": 3.1},
            {"name": "Rubber", "reward_type": "Physical Fruit", "chance": 2.7},
            {"name": "Ghost", "reward_type": "Physical Fruit", "chance": 2.5},
            {"name": "Magma", "reward_type": "Physical Fruit", "chance": 2.3},
            {"name": "Quake", "reward_type": "Physical Fruit", "chance": 2.1},
            {"name": "Love", "reward_type": "Physical Fruit", "chance": 2.0},
            {"name": "Creation", "reward_type": "Physical Fruit", "chance": 1.9},
            {"name": "Spider", "reward_type": "Physical Fruit", "chance": 1.8},
            {"name": "Sound", "reward_type": "Physical Fruit", "chance": 1.5},
            {"name": "Phoenix", "reward_type": "Physical Fruit", "chance": 1.4},
            {"name": "Pain", "reward_type": "Physical Fruit", "chance": 1.4},
            {"name": "Blizzard", "reward_type": "Physical Fruit", "chance": 1.3},
        ],
        "Epic": [
            {"name": "Buddha", "reward_type": "Physical Fruit", "chance": 2.8},
            {"name": "Portal", "reward_type": "Physical Fruit", "chance": 2.5},
            {"name": "Gravity", "reward_type": "Physical Fruit", "chance": 2.0},
            {"name": "Mammoth", "reward_type": "Physical Fruit", "chance": 1.8},
            {"name": "T-Rex", "reward_type": "Physical Fruit", "chance": 1.7},
            {"name": "Shadow", "reward_type": "Physical Fruit", "chance": 1.6},
            {"name": "Venom", "reward_type": "Physical Fruit", "chance": 1.6},
            {"name": "Spirit", "reward_type": "Physical Fruit", "chance": 1.5},
            {"name": "2x Boss Drops Chance", "reward_type": "Gamepass", "chance": 1.5},
            {"name": "Lightning", "reward_type": "Physical Fruit", "chance": 1.0},
        ],
        "Legendary": [
            {"name": "Kitsune", "reward_type": "Physical Fruit", "chance": 1.0},
            {"name": "Fast Boats", "reward_type": "Gamepass", "chance": 1.8},
            {"name": "2x Money", "reward_type": "Gamepass", "chance": 2.2},
            {"name": "2x Mastery", "reward_type": "Gamepass", "chance": 2.4},
            {"name": "Control", "reward_type": "Physical Fruit", "chance": 2.8},
            {"name": "Yeti", "reward_type": "Physical Fruit", "chance": 2.5},
            {"name": "Tiger", "reward_type": "Physical Fruit", "chance": 2.3},
            {"name": "Gas", "reward_type": "Physical Fruit", "chance": 1.1},
            {"name": "Dough", "reward_type": "Physical Fruit", "chance": 0.9},
        ],
        "Mythical": [
            {"name": "Dark Blade", "reward_type": "Gamepass", "chance": 6.0},
        ],
    },
    "deluxe": {
        "Rare": [
            {"name": "Light", "reward_type": "Physical Fruit", "chance": 5.0},
            {"name": "Rubber", "reward_type": "Physical Fruit", "chance": 4.5},
            {"name": "Ghost", "reward_type": "Physical Fruit", "chance": 4.0},
            {"name": "Magma", "reward_type": "Physical Fruit", "chance": 3.6},
            {"name": "Quake", "reward_type": "Physical Fruit", "chance": 3.4},
            {"name": "Love", "reward_type": "Physical Fruit", "chance": 3.2},
            {"name": "Creation", "reward_type": "Physical Fruit", "chance": 3.0},
            {"name": "Spider", "reward_type": "Physical Fruit", "chance": 2.9},
            {"name": "Sound", "reward_type": "Physical Fruit", "chance": 2.4},
            {"name": "Phoenix", "reward_type": "Physical Fruit", "chance": 2.3},
            {"name": "Pain", "reward_type": "Physical Fruit", "chance": 2.2},
            {"name": "Blizzard", "reward_type": "Physical Fruit", "chance": 2.1},
            {"name": "Eagle Glacier", "reward_type": "Fruit Skin", "chance": 2.1},
            {"name": "Torment Pain", "reward_type": "Fruit Skin", "chance": 1.3},
        ],
        "Epic": [
            {"name": "Buddha", "reward_type": "Physical Fruit", "chance": 4.0},
            {"name": "Portal", "reward_type": "Physical Fruit", "chance": 3.4},
            {"name": "Gravity", "reward_type": "Physical Fruit", "chance": 2.8},
            {"name": "Mammoth", "reward_type": "Physical Fruit", "chance": 2.7},
            {"name": "T-Rex", "reward_type": "Physical Fruit", "chance": 2.5},
            {"name": "Shadow", "reward_type": "Physical Fruit", "chance": 2.1},
            {"name": "Venom", "reward_type": "Physical Fruit", "chance": 2.1},
            {"name": "Spirit", "reward_type": "Physical Fruit", "chance": 2.0},
            {"name": "2x Boss Drops Chance", "reward_type": "Gamepass", "chance": 2.0},
            {"name": "Celestial Pain", "reward_type": "Fruit Skin", "chance": 1.8},
            {"name": "Eagle Matrix", "reward_type": "Fruit Skin", "chance": 1.6},
            {"name": "Fiend Yeti", "reward_type": "Fruit Skin", "chance": 1.5},
            {"name": "Ruby Diamond", "reward_type": "Fruit Skin", "chance": 1.3},
            {"name": "Lightning", "reward_type": "Physical Fruit", "chance": 0.8},
            {"name": "Kitsune", "reward_type": "Physical Fruit", "chance": 1.0},
            {"name": "Fast Boats", "reward_type": "Gamepass", "chance": 1.4},
            {"name": "2x Money", "reward_type": "Gamepass", "chance": 1.5},
            {"name": "2x Mastery", "reward_type": "Gamepass", "chance": 1.5},
        ],
        "Legendary": [
            {"name": "Dark Blade", "reward_type": "Gamepass", "chance": 0.30},
            {"name": "Portal Divin", "reward_type": "Fruit Skin", "chance": 1.25},
            {"name": "Werewolf", "reward_type": "Fruit Skin", "chance": 1.20},
            {"name": "Requiem Eagle", "reward_type": "Fruit Skin", "chance": 1.20},
            {"name": "Rose Quartz Diamond", "reward_type": "Fruit Skin", "chance": 1.20},
            {"name": "Yellow Lightning", "reward_type": "Fruit Skin", "chance": 1.20},
            {"name": "Emerald Diamond", "reward_type": "Fruit Skin", "chance": 1.20},
            {"name": "Topaz Diamond", "reward_type": "Fruit Skin", "chance": 1.15},
            {"name": "Frustration Pain", "reward_type": "Fruit Skin", "chance": 1.10},
            {"name": "Sadness Pain", "reward_type": "Fruit Skin", "chance": 1.00},
            {"name": "Dough", "reward_type": "Physical Fruit", "chance": 1.20},
            {"name": "Gas", "reward_type": "Physical Fruit", "chance": 1.15},
            {"name": "Tiger", "reward_type": "Physical Fruit", "chance": 1.15},
            {"name": "Yeti", "reward_type": "Physical Fruit", "chance": 1.15},
            {"name": "Control", "reward_type": "Physical Fruit", "chance": 1.10},
        ],
        "Mythical": [
            {"name": "Purple Lightning", "reward_type": "Fruit Skin", "chance": 1.20},
            {"name": "Parrot Eagle", "reward_type": "Fruit Skin", "chance": 1.00},
            {"name": "Ember Dragon", "reward_type": "Fruit Skin", "chance": 0.80},
        ],
        "Secret": [
            {"name": "Kitsune Galaxy", "reward_type": "Fruit Skin", "chance": 1.0},
        ],
    },
}
