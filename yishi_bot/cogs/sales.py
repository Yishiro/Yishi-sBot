from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from yishi_bot.views import SaleCreateModal

if TYPE_CHECKING:
    from yishi_bot.core import YishiBot


class SalesCog(commands.Cog):
    def __init__(self, bot: "YishiBot") -> None:
        self.bot = bot

    @app_commands.command(name="vente", description="Ouvre une fenêtre pour créer une annonce de vente")
    async def vente(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(SaleCreateModal(self.bot))

    @app_commands.command(name="vente_close", description="Ferme un salon de vente et retire l'annonce")
    async def vente_close(self, interaction: discord.Interaction) -> None:
        await self.bot.close_sale_channel(interaction)

    @app_commands.command(name="vente_setup", description="Configure automatiquement les salons du système de vente")
    @app_commands.default_permissions(manage_guild=True)
    async def vente_setup(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return

        sales_channel, sales_category = await self.bot.ensure_sales_config(interaction.guild)
        await interaction.response.send_message(
            (
                "Système de vente configuré.\n"
                f"Salon des annonces : {sales_channel.mention}\n"
                f"Catégorie des ventes privées : **{sales_category.name}**"
            ),
            ephemeral=True,
        )
