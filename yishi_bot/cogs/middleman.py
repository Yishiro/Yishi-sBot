from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from yishi_bot.core import YishiBot


class MiddlemanCog(commands.Cog):
    def __init__(self, bot: "YishiBot") -> None:
        self.bot = bot

    @app_commands.command(name="mm", description="Ouvre un échange sécurisé avec un Middleman recommandé")
    @app_commands.describe(
        membre="L'autre membre de l'échange",
        produit="Objet, compte ou service échangé",
        prix="Prix ou valeur convenue",
        details="Détails utiles pour le Middleman",
    )
    async def middleman(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        produit: str,
        prix: str,
        details: str,
    ) -> None:
        await self.bot.create_middleman(interaction, membre, produit, prix, details)

    @app_commands.command(name="mm_close", description="Clôture un échange Middleman terminé")
    async def middleman_close(self, interaction: discord.Interaction) -> None:
        await self.bot.close_middleman(interaction)

    @app_commands.command(name="mm_setup", description="Configure le rôle et la catégorie Middleman")
    @app_commands.default_permissions(manage_guild=True)
    async def middleman_setup(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        role, category = await self.bot.ensure_middleman_config(interaction.guild)
        await interaction.response.send_message(
            f"Système Middleman configuré : rôle {role.mention} et catégorie **{category.name}**.",
            ephemeral=True,
        )
