from __future__ import annotations

import re

import discord


TICKET_TYPES = {
    "achat": {
        "label": "Buy",
        "emoji": "💳",
        "description": "Create a buy ticket",
    },
    "exchange": {
        "label": "Exchange",
        "emoji": "♻️",
        "description": "Create a exchange ticket",
    },
    "help": {
        "label": "Need Help?",
        "emoji": "🚨",
        "description": "Create a need help? ticket",
    },
    "partnership": {
        "label": "Partnerships",
        "emoji": "🤝",
        "description": "Create a partnerships ticket",
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
            "Sélectionnez la catégorie qui correspond le mieux à votre demande "
            "afin que le staff puisse vous répondre rapidement.\n"
            "Merci de rester clair, poli et patient pour faciliter le traitement de votre ticket.\n\n"
            "*Notre staff vous répondra dès que possible.*"
        ),
        color=discord.Color.blurple(),
    )


def build_custom_ticket_panel_embed(
    title: str = "Supra's Shop Support Center",
    intro_text: str | None = None,
    image_url: str | None = None,
) -> discord.Embed:
    intro = (
        intro_text.strip()
        if intro_text
        else (
            "## Supra's Shop Support Center\n"
            "Welcome to our official support system.\n\n"
            "## How It Works\n"
            "» Select the appropriate category from the dropdown menu below\n"
            "» Our team will respond as soon as possible\n"
            "» Please read #📌・Tos before buying"
        )
    )

    embed = discord.Embed(
        title=title,
        description=intro,
        color=discord.Color.dark_embed(),
    )
    if image_url:
        embed.set_image(url=image_url)
    embed.set_footer(text="Supra's Shop • Support Center")
    return embed
