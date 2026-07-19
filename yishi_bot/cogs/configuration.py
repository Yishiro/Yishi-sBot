from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any, Literal

import discord
from discord import app_commands
from discord.ext import commands

from tickets import build_custom_ticket_panel_embed, build_ticket_panel_embed
from yishi_bot.constants import (
    AUTO_ARCHIVE_CATEGORY_NAME,
    AUTO_ARCHIVE_ROLE_NAME,
    AUTO_GACHA_LOGS_CHANNEL_NAME,
    AUTO_GACHA_SPIN_CHANNEL_NAME,
    AUTO_GACHA_WINNER_CHANNEL_NAME,
    AUTO_LOGS_CHANNEL_NAME,
    AUTO_STAFF_ROLE_NAME,
    AUTO_TICKET_CATEGORY_NAME,
    AUTO_TRANSCRIPT_CHANNEL_NAME,
    GACHA_REWARDS,
    GACHA_SPIN_TYPES,
    RULES_ACCEPT_TEXT,
    RULES_TEXT,
    WELCOME_ADVANTAGES,
    WELCOME_CHECKLIST,
)
from yishi_bot.helpers import can_moderate, parse_duration, split_long_message
from yishi_bot.views import AnnouncementModal, TicketPanelView

if TYPE_CHECKING:
    from yishi_bot.core import YishiBot


class ConfigurationCog(commands.Cog):
    def __init__(self, bot: YishiBot) -> None:
            self.bot = bot

    async def config_role_staff(self, interaction: discord.Interaction, role: discord.Role) -> None:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "Commande indisponible ici.",
                    ephemeral=True,
                )
                return
            config = self.bot.get_guild_config(interaction.guild.id)
            config["staff_role_id"] = role.id
            self.bot.save_config()
            await interaction.response.send_message(
                f"Le rôle staff des tickets ouverts est maintenant {role.mention}.",
                ephemeral=True,
            )

    async def config_role_archive(self, interaction: discord.Interaction, role: discord.Role) -> None:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "Commande indisponible ici.",
                    ephemeral=True,
                )
                return
            config = self.bot.get_guild_config(interaction.guild.id)
            config["archive_role_id"] = role.id
            self.bot.save_config()
            await interaction.response.send_message(
                f"Le rôle des archives est maintenant {role.mention}.",
                ephemeral=True,
            )

    async def config_categorie_tickets(
            self,
            interaction: discord.Interaction,
            categorie: discord.CategoryChannel,
        ) -> None:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "Commande indisponible ici.",
                    ephemeral=True,
                )
                return
            config = self.bot.get_guild_config(interaction.guild.id)
            config["ticket_category_id"] = categorie.id
            self.bot.save_config()
            await interaction.response.send_message(
                f"La catégorie des tickets ouverts est maintenant {categorie.name}.",
                ephemeral=True,
            )

    async def config_categorie_archives(
            self,
            interaction: discord.Interaction,
            categorie: discord.CategoryChannel,
        ) -> None:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "Commande indisponible ici.",
                    ephemeral=True,
                )
                return
            config = self.bot.get_guild_config(interaction.guild.id)
            config["archive_category_id"] = categorie.id
            self.bot.save_config()
            await interaction.response.send_message(
                f"La catégorie des tickets archivés est maintenant {categorie.name}.",
                ephemeral=True,
            )

    async def config_salon_bienvenue(
            self,
            interaction: discord.Interaction,
            salon: discord.TextChannel,
        ) -> None:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "Commande indisponible ici.",
                    ephemeral=True,
                )
                return
            config = self.bot.get_guild_config(interaction.guild.id)
            config["welcome_channel_id"] = salon.id
            self.bot.save_config()
            await interaction.response.send_message(
                f"Le salon de bienvenue est maintenant {salon.mention}.",
                ephemeral=True,
            )

    async def config_salon_logs(
            self,
            interaction: discord.Interaction,
            salon: discord.TextChannel,
        ) -> None:
            if interaction.guild is None:
                await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
                return
            config = self.bot.get_guild_config(interaction.guild.id)
            config["logs_channel_id"] = salon.id
            self.bot.save_config()
            await self.bot.configure_logs_channel_permissions(interaction.guild, salon)
            await interaction.response.send_message(
                f"Le salon de logs est maintenant {salon.mention}.",
                ephemeral=True,
            )

    async def config_role_regles(self, interaction: discord.Interaction, role: discord.Role) -> None:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "Commande indisponible ici.",
                    ephemeral=True,
                )
                return
            config = self.bot.get_guild_config(interaction.guild.id)
            config["rules_role_id"] = role.id
            self.bot.save_config()
            await interaction.response.send_message(
                f"Le rôle des règles est maintenant {role.mention}.",
                ephemeral=True,
            )

    async def envoyer_reglement(
            self,
            interaction: discord.Interaction,
            salon: discord.TextChannel,
        ) -> None:
            await self.bot.send_rules_text(salon)
            await interaction.response.send_message(
                f"Le règlement a été envoyé dans {salon.mention}.",
                ephemeral=True,
            )

    async def envoyer_message_regles(
            self,
            interaction: discord.Interaction,
            salon: discord.TextChannel,
        ) -> None:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "Commande indisponible ici.",
                    ephemeral=True,
                )
                return
            config = self.bot.get_guild_config(interaction.guild.id)
            if config["rules_role_id"] is None:
                await interaction.response.send_message(
                    "Configure d'abord le rôle avec /config_role_regles.",
                    ephemeral=True,
                )
                return

            message = await salon.send(RULES_ACCEPT_TEXT)
            await message.add_reaction("✅")
            config["rules_message_id"] = message.id
            config["rules_channel_id"] = salon.id
            self.bot.save_config()
            await interaction.response.send_message(
                f"Le message de validation a été envoyé dans {salon.mention}.",
                ephemeral=True,
            )
