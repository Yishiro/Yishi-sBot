from __future__ import annotations

import re

import discord


TICKET_TYPES = {
    "renseignement": {
        "label": "Renseignement",
        "emoji": "🎫",
        "description": "Ouvre un ticket de renseignement",
    },
}


def slugify_name(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9-]", "-", name.lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "utilisateur"


def build_ticket_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Yishi's Shop Support Center",
        description=(
            "Bienvenue sur le support de Yishi's Shop.\n\n"
            "Ouvre un ticket de renseignement si tu veux connaître un prix, poser une question "
            "ou être redirigé vers un ticket achat par le staff.\n\n"
            "Les helpers traitent d'abord les demandes, puis transfèrent au bon pôle si nécessaire."
        ),
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="Comment ça marche",
        value=(
            "• Ouvre un ticket de renseignement\n"
            "• Explique clairement ta demande\n"
            "• Un helper te répondra\n"
            "• Si besoin, ton ticket sera transféré vers le staff ou les achats"
        ),
        inline=False,
    )
    embed.set_footer(text="Un seul type de ticket à l'ouverture • Le staff oriente ensuite")
    return embed


def build_custom_ticket_panel_embed(
    title: str = "Supra's Shop Support Center",
    intro_text: str | None = None,
    image_url: str | None = None,
) -> discord.Embed:
    intro = (
        intro_text.strip()
        if intro_text
        else (
            "Welcome to our official support system.\n\n"
            "Open a ticket to ask for prices, product information or support.\n"
            "Our helpers will answer first and transfer your ticket if needed."
        )
    )

    embed = discord.Embed(
        title=title,
        description=intro,
        color=discord.Color.dark_embed(),
    )
    if image_url:
        embed.set_image(url=image_url)
    embed.set_footer(text="Support Center • Ticket routing handled by staff")
    return embed
