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
    title: str = "Supra's Shop Support",
    intro_text: str | None = None,
) -> discord.Embed:
    intro = (
        intro_text.strip()
        if intro_text
        else (
            "Welcome to Supra's Shop.\n"
            "Choose the ticket category that matches your request so the staff can help you quickly."
        )
    )

    lines: list[str] = [intro, ""]
    for data in TICKET_TYPES.values():
        lines.append(f"{data['emoji']} **{data['label']}**")
        lines.append(data["description"])
        lines.append("")

    embed = discord.Embed(
        title=title,
        description="\n".join(lines).strip(),
        color=discord.Color.dark_embed(),
    )
    embed.set_footer(text="Supra's Shop • Support Center")
    return embed
