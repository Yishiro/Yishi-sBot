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


class TicketsCog(commands.Cog):
    def __init__(self, bot: YishiBot) -> None:
            self.bot = bot

    async def add_membre_ticket(
            self,
            interaction: discord.Interaction,
            membre: discord.Member,
        ) -> None:
            if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
                await interaction.response.send_message(
                    "Commande indisponible ici.",
                    ephemeral=True,
                )
                return
            ticket = self.bot.get_ticket_store(interaction.guild.id)["channels"].get(str(interaction.channel.id))
            if ticket is None:
                await interaction.response.send_message(
                    "Cette commande doit être utilisée dans un ticket.",
                    ephemeral=True,
                )
                return

            await interaction.channel.set_permissions(
                membre,
                overwrite=discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                    embed_links=True,
                ),
            )
            await interaction.response.send_message(
                f"{membre.mention} a été ajouté au ticket.",
                ephemeral=True,
            )
            await interaction.channel.send(
                f"{membre.mention} a été ajouté au ticket par {interaction.user.mention}."
            )

    async def remove_membre_ticket(
            self,
            interaction: discord.Interaction,
            membre: discord.Member,
        ) -> None:
            if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
                await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
                return
            ticket = self.bot.get_ticket_store(interaction.guild.id)["channels"].get(str(interaction.channel.id))
            if ticket is None:
                await interaction.response.send_message("Cette commande doit être utilisée dans un ticket.", ephemeral=True)
                return
            await interaction.channel.set_permissions(membre, overwrite=None)
            await interaction.response.send_message(f"{membre.mention} a été retiré du ticket.", ephemeral=True)
            await interaction.channel.send(f"{membre.mention} a été retiré du ticket par {interaction.user.mention}.")

    async def envoyer_panel_tickets(
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
            if not all(
                [
                    config["staff_role_id"],
                    config["archive_role_id"],
                    config["ticket_category_id"],
                    config["archive_category_id"],
                ]
            ):
                await interaction.response.send_message(
                    "Configure d'abord les rôles et catégories des tickets.",
                    ephemeral=True,
                )
                return

            await salon.send(embed=build_ticket_panel_embed(), view=TicketPanelView(self.bot))
            await interaction.response.send_message(
                f"Panneau de tickets envoyé dans {salon.mention}.",
                ephemeral=True,
            )

    async def envoyer_panel_tickets_custom(
            self,
            interaction: discord.Interaction,
            salon: discord.TextChannel,
            titre: str | None = None,
            texte: str | None = None,
            image_url: str | None = None,
            image: discord.Attachment | None = None,
        ) -> None:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "Commande indisponible ici.",
                    ephemeral=True,
                )
                return
            config = self.bot.get_guild_config(interaction.guild.id)
            if not all(
                [
                    config["staff_role_id"],
                    config["archive_role_id"],
                    config["ticket_category_id"],
                    config["archive_category_id"],
                ]
            ):
                await interaction.response.send_message(
                    "Configure d'abord les rôles et catégories des tickets.",
                    ephemeral=True,
                )
                return

            final_image_url = image_url
            file: discord.File | None = None
            if image is not None:
                file = await image.to_file()
                final_image_url = f"attachment://{file.filename}"

            embed = build_custom_ticket_panel_embed(
                title=titre or "Supra's Shop Support Center",
                intro_text=texte,
                image_url=final_image_url,
            )
            await salon.send(
                embed=embed,
                view=TicketPanelView(self.bot),
                file=file,
            )
            await interaction.response.send_message(
                f"Panneau de tickets envoyé dans {salon.mention}.",
                ephemeral=True,
            )
