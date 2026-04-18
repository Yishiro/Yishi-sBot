import re

import discord


TICKET_TYPES = {
    "achat": {
        "label": "Achat",
        "emoji": "🛒",
        "description": "Ouvrir un ticket pour un achat.",
    },
    "renseignement": {
        "label": "Renseignement",
        "emoji": "❓",
        "description": "Poser une question au staff.",
    },
    "report": {
        "label": "Report",
        "emoji": "🚨",
        "description": "Signaler un probleme.",
    },
    "autre": {
        "label": "Autre",
        "emoji": "📩",
        "description": "Toute autre demande.",
    },
}


def slugify_name(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9-]", "-", name.lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "utilisateur"


def build_ticket_panel_embed() -> discord.Embed:
    return discord.Embed(
        title="Yishi's Shop Tickets",
        description=(
            "Bienvenue sur Yishi's Shop.\n\n"
            "Selectionnez la categorie qui correspond le mieux a votre demande "
            "afin que le staff puisse vous repondre rapidement.\n"
            "Merci de rester clair, poli et patient pour faciliter le traitement de votre ticket.\n\n"
            "*Notre staff vous repondra des que possible.*"
        ),
        color=discord.Color.blurple(),
    )
