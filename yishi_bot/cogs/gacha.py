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


class GachaCog(commands.Cog):
    def __init__(self, bot: YishiBot) -> None:
            self.bot = bot

    async def spin_stock(
            self,
            interaction: discord.Interaction,
            membre: discord.Member | None = None,
        ) -> None:
            if membre is not None:
                inventory = self.bot.get_gacha_inventory(membre.id)
                embed = discord.Embed(
                    title=f"Stock de {membre.display_name}",
                    color=discord.Color.gold(),
                )
                embed.add_field(name="Basic", value=str(inventory.get("basic", 0)), inline=True)
                embed.add_field(name="Advanced", value=str(inventory.get("advanced", 0)), inline=True)
                embed.add_field(name="Deluxe", value=str(inventory.get("deluxe", 0)), inline=True)
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            inventories = self.bot.gacha_data.get("inventories", {})
            if not inventories:
                await interaction.response.send_message("Aucun stock de spin enregistré.", ephemeral=True)
                return

            lines: list[str] = []
            for user_id, inventory in inventories.items():
                total = int(inventory.get("basic", 0)) + int(inventory.get("advanced", 0)) + int(inventory.get("deluxe", 0))
                if total <= 0:
                    continue
                member_obj = interaction.guild.get_member(int(user_id)) if interaction.guild is not None else None
                name = member_obj.display_name if member_obj is not None else user_id
                lines.append(
                    f"• {name} — Basic: {inventory.get('basic', 0)} | Advanced: {inventory.get('advanced', 0)} | Deluxe: {inventory.get('deluxe', 0)}"
                )
            if not lines:
                await interaction.response.send_message("Aucun stock de spin actif.", ephemeral=True)
                return
            embed = discord.Embed(title="Stock global des spins", description="\n".join(lines[:30]), color=discord.Color.gold())
            await interaction.response.send_message(embed=embed, ephemeral=True)

    async def gacha_taux(self, interaction: discord.Interaction) -> None:
            embeds = [
                self.bot.build_gacha_rates_embed("basic"),
                self.bot.build_gacha_rates_embed("advanced"),
                self.bot.build_gacha_rates_embed("deluxe"),
            ]
            await interaction.response.send_message(embeds=embeds)

    async def basic(self, interaction: discord.Interaction) -> None:
            await self.bot.execute_gacha_spin(interaction, "basic")

    async def advanced(self, interaction: discord.Interaction) -> None:
            await self.bot.execute_gacha_spin(interaction, "advanced")

    async def deluxe(self, interaction: discord.Interaction) -> None:
            await self.bot.execute_gacha_spin(interaction, "deluxe")

    async def basic_add(
            self,
            interaction: discord.Interaction,
            membre: discord.Member,
            quantite: app_commands.Range[int, 1, 100],
            raison: str | None = None,
        ) -> None:
            total = self.bot.add_gacha_spins(membre.id, "basic", int(quantite))
            self.bot.record_spin_adjustment(
                membre.id,
                membre.display_name,
                interaction.user.id,
                interaction.user.display_name,
                "basic",
                int(quantite),
                "add",
                raison,
                total,
            )
            if interaction.guild is not None:
                await self.bot.log_gacha_spin(
                    interaction.guild,
                    membre,
                    "basic",
                    "Stock Update",
                    {"name": f"+{quantite} Basic Spin(s)", "reward_type": f"Total: {total} | {raison or 'Aucune raison'}"},
                    0,
                )
            await interaction.response.send_message(
                f"{quantite} Basic Spin(s) ajoutés à {membre.mention}. Nouveau total : {total}.",
                ephemeral=True,
            )

    async def advanced_add(
            self,
            interaction: discord.Interaction,
            membre: discord.Member,
            quantite: app_commands.Range[int, 1, 100],
            raison: str | None = None,
        ) -> None:
            total = self.bot.add_gacha_spins(membre.id, "advanced", int(quantite))
            self.bot.record_spin_adjustment(
                membre.id,
                membre.display_name,
                interaction.user.id,
                interaction.user.display_name,
                "advanced",
                int(quantite),
                "add",
                raison,
                total,
            )
            if interaction.guild is not None:
                await self.bot.log_gacha_spin(
                    interaction.guild,
                    membre,
                    "advanced",
                    "Stock Update",
                    {"name": f"+{quantite} Advanced Spin(s)", "reward_type": f"Total: {total} | {raison or 'Aucune raison'}"},
                    0,
                )
            await interaction.response.send_message(
                f"{quantite} Advanced Spin(s) ajoutés à {membre.mention}. Nouveau total : {total}.",
                ephemeral=True,
            )

    async def deluxe_add(
            self,
            interaction: discord.Interaction,
            membre: discord.Member,
            quantite: app_commands.Range[int, 1, 100],
            raison: str | None = None,
        ) -> None:
            total = self.bot.add_gacha_spins(membre.id, "deluxe", int(quantite))
            self.bot.record_spin_adjustment(
                membre.id,
                membre.display_name,
                interaction.user.id,
                interaction.user.display_name,
                "deluxe",
                int(quantite),
                "add",
                raison,
                total,
            )
            if interaction.guild is not None:
                await self.bot.log_gacha_spin(
                    interaction.guild,
                    membre,
                    "deluxe",
                    "Stock Update",
                    {"name": f"+{quantite} Deluxe Spin(s)", "reward_type": f"Total: {total} | {raison or 'Aucune raison'}"},
                    0,
                )
            await interaction.response.send_message(
                f"{quantite} Deluxe Spin(s) ajoutés à {membre.mention}. Nouveau total : {total}.",
                ephemeral=True,
            )

    async def spin_remove(
            self,
            interaction: discord.Interaction,
            membre: discord.Member,
            type: app_commands.Choice[str],
            quantite: app_commands.Range[int, 1, 100],
            raison: str | None = None,
        ) -> None:
            total = self.bot.remove_gacha_spins(membre.id, type.value, int(quantite))
            self.bot.record_spin_adjustment(
                membre.id,
                membre.display_name,
                interaction.user.id,
                interaction.user.display_name,
                type.value,
                int(quantite),
                "remove",
                raison,
                total,
            )
            if interaction.guild is not None:
                await self.bot.log_gacha_spin(
                    interaction.guild,
                    membre,
                    type.value,
                    "Stock Update",
                    {"name": f"-{quantite} {type.name} Spin(s)", "reward_type": f"Total: {total} | {raison or 'Aucune raison'}"},
                    0,
                )
            await interaction.response.send_message(
                f"{quantite} {type.name} Spin(s) retirés à {membre.mention}. Nouveau total : {total}.",
                ephemeral=True,
            )

    async def note_add(
            self,
            interaction: discord.Interaction,
            membre: discord.Member,
            note: str,
        ) -> None:
            self.bot.add_member_note(
                membre.id,
                interaction.user.id,
                interaction.user.display_name,
                note,
            )
            await interaction.response.send_message(
                f"Note ajoutée pour {membre.mention}.",
                ephemeral=True,
            )

    async def note_remove(
            self,
            interaction: discord.Interaction,
            membre: discord.Member,
            index: app_commands.Range[int, 1, 100],
        ) -> None:
            removed = self.bot.remove_member_note(membre.id, int(index) - 1)
            if removed is None:
                await interaction.response.send_message("Cette note n'existe pas.", ephemeral=True)
                return
            await interaction.response.send_message(
                f"Note supprimée pour {membre.mention} : {removed.get('content', '')}",
                ephemeral=True,
            )

    async def spin_log(
            self,
            interaction: discord.Interaction,
            membre: discord.Member | None = None,
        ) -> None:
            history = self.bot.gacha_data.get("history", [])
            if membre is not None:
                history = [entry for entry in history if int(entry["user_id"]) == membre.id]
            if not history:
                await interaction.response.send_message("Aucun spin enregistré.", ephemeral=True)
                return

            latest = list(reversed(history[-20:]))
            lines = []
            for entry in latest:
                lines.append(
                    f"• #{entry['claim_number']} — {entry['display_name']} — {entry['spin_type'].title()} — {entry['reward']} ({entry['rarity']})"
                )
            embed = discord.Embed(
                title="Historique des spins" if membre is None else f"Historique de {membre.display_name}",
                description="\n".join(lines),
                color=discord.Color.blurple(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
