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


class ModerationCog(commands.Cog):
    def __init__(self, bot: YishiBot) -> None:
        self.bot = bot

    @app_commands.command(name="clear", description="Supprime un certain nombre de messages")
    @app_commands.describe(nombre="Nombre de messages à supprimer")
    @app_commands.default_permissions(manage_messages=True)
    async def clear(
        self,
        interaction: discord.Interaction,
        nombre: app_commands.Range[int, 1, 100],
    ) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=nombre)
        await self.bot.log_event(
            interaction.guild,
            "🧹 Messages supprimés",
            f"{interaction.user.mention} a supprimé des messages dans {interaction.channel.mention}.",
            discord.Color.orange(),
            thumbnail_url=interaction.user.display_avatar.url,
            fields=[("Nombre", str(len(deleted)), True)],
        )
        await interaction.followup.send(
            f"{len(deleted)} message(s) supprimé(s).",
            ephemeral=True,
        )

    @app_commands.command(name="kick", description="Expulse un membre du serveur")
    @app_commands.describe(membre="Le membre à expulser", raison="La raison du kick")
    @app_commands.default_permissions(kick_members=True)
    async def kick(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        raison: str = "Aucune raison fournie",
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return
        bot_member = self.bot.get_bot_member(interaction.guild)
        if bot_member is None:
            await interaction.response.send_message(
                "Impossible de vérifier mes permissions.",
                ephemeral=True,
            )
            return
        error = can_moderate(interaction.user, membre, bot_member)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await membre.kick(reason=raison)
        await self.bot.log_event(
            interaction.guild,
            "👢 Membre expulsé",
            f"{membre.mention} a été expulsé par {interaction.user.mention}.",
            discord.Color.red(),
            thumbnail_url=membre.display_avatar.url,
            fields=[("Raison", raison, False)],
        )
        await interaction.response.send_message(
            f"{membre} a été expulsé. Raison : {raison}"
        )

    @app_commands.command(name="ban", description="Bannit un membre du serveur")
    @app_commands.describe(membre="Le membre à bannir", raison="La raison du ban")
    @app_commands.default_permissions(ban_members=True)
    async def ban(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        raison: str = "Aucune raison fournie",
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return
        bot_member = self.bot.get_bot_member(interaction.guild)
        if bot_member is None:
            await interaction.response.send_message(
                "Impossible de vérifier mes permissions.",
                ephemeral=True,
            )
            return
        error = can_moderate(interaction.user, membre, bot_member)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await membre.ban(reason=raison)
        await self.bot.log_event(
            interaction.guild,
            "⛔ Membre banni",
            f"{membre.mention} a été banni par {interaction.user.mention}.",
            discord.Color.red(),
            thumbnail_url=membre.display_avatar.url,
            fields=[("Raison", raison, False)],
        )
        await interaction.response.send_message(
            f"{membre} a été banni. Raison : {raison}"
        )

    @app_commands.command(name="mute", description="Timeout un membre pendant un certain temps")
    @app_commands.describe(
        membre="Le membre à mute",
        minutes="Durée du timeout en minutes",
        raison="La raison du mute",
    )
    @app_commands.default_permissions(moderate_members=True)
    async def mute(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        minutes: app_commands.Range[int, 1, 40320],
        raison: str = "Aucune raison fournie",
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return
        bot_member = self.bot.get_bot_member(interaction.guild)
        if bot_member is None:
            await interaction.response.send_message(
                "Impossible de vérifier mes permissions.",
                ephemeral=True,
            )
            return
        error = can_moderate(interaction.user, membre, bot_member)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await membre.timeout(discord.utils.utcnow() + timedelta(minutes=minutes), reason=raison)
        await self.bot.log_event(
            interaction.guild,
            "🔇 Membre mute",
            f"{membre.mention} a été mute par {interaction.user.mention}.",
            discord.Color.orange(),
            thumbnail_url=membre.display_avatar.url,
            fields=[("Durée", f"{minutes} minute(s)", True), ("Raison", raison, False)],
        )
        await interaction.response.send_message(
            f"{membre} a été mute pendant {minutes} minute(s). Raison : {raison}"
        )

    @app_commands.command(name="unmute", description="Retire le timeout d'un membre")
    @app_commands.describe(membre="Le membre à unmute", raison="La raison du unmute")
    @app_commands.default_permissions(moderate_members=True)
    async def unmute(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        raison: str = "Aucune raison fournie",
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return
        bot_member = self.bot.get_bot_member(interaction.guild)
        if bot_member is None:
            await interaction.response.send_message(
                "Impossible de vérifier mes permissions.",
                ephemeral=True,
            )
            return
        error = can_moderate(interaction.user, membre, bot_member)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await membre.timeout(None, reason=raison)
        await self.bot.log_event(
            interaction.guild,
            "🔊 Membre unmute",
            f"{membre.mention} n'est plus mute grâce à {interaction.user.mention}.",
            discord.Color.green(),
            thumbnail_url=membre.display_avatar.url,
            fields=[("Raison", raison, False)],
        )
        await interaction.response.send_message(
            f"{membre} n'est plus mute. Raison : {raison}"
        )

    @app_commands.command(name="unban", description="Débannit un membre du serveur")
    @app_commands.describe(user_id="ID du membre à débannir", raison="La raison du débannissement")
    @app_commands.default_permissions(ban_members=True)
    async def unban(
        self,
        interaction: discord.Interaction,
        user_id: str,
        raison: str = "Aucune raison fournie",
    ) -> None:
        if interaction.guild is None or not user_id.isdigit():
            await interaction.response.send_message("ID invalide.", ephemeral=True)
            return
        user = await self.bot.fetch_user(int(user_id))
        await interaction.guild.unban(user, reason=raison)
        await self.bot.log_event(
            interaction.guild,
            "✅ Membre débanni",
            f"{user} a été débanni par {interaction.user.mention}.",
            discord.Color.green(),
            fields=[("Raison", raison, False)],
        )
        await interaction.response.send_message(f"{user} a été débanni. Raison : {raison}")

    @app_commands.command(name="warn", description="Avertit un membre avec une raison")
    @app_commands.describe(membre="Le membre à avertir", raison="La raison de l'avertissement")
    @app_commands.default_permissions(moderate_members=True)
    async def warn(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        raison: str,
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return
        bot_member = self.bot.get_bot_member(interaction.guild)
        if bot_member is None:
            await interaction.response.send_message(
                "Impossible de vérifier mes permissions.",
                ephemeral=True,
            )
            return
        error = can_moderate(interaction.user, membre, bot_member)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return

        store = self.bot.get_warning_store(interaction.guild.id)
        key = str(membre.id)
        store.setdefault(key, []).append(
            {
                "reason": raison,
                "moderator_id": interaction.user.id,
                "moderator_name": str(interaction.user),
                "created_at": discord.utils.utcnow().strftime("%d/%m/%Y %H:%M"),
            }
        )
        self.bot.save_warnings()
        await self.bot.log_event(
            interaction.guild,
            "⚠️ Avertissement ajouté",
            f"{membre.mention} a reçu un avertissement de {interaction.user.mention}.",
            discord.Color.orange(),
            thumbnail_url=membre.display_avatar.url,
            fields=[("Raison", raison, False)],
        )
        await interaction.response.send_message(
            f"{membre.mention} a reçu un avertissement. Raison : {raison}"
        )

    @app_commands.command(name="list_warn", description="Affiche les avertissements d'un membre")
    @app_commands.describe(membre="Le membre dont tu veux voir les avertissements")
    @app_commands.default_permissions(moderate_members=True)
    async def list_warn(self, interaction: discord.Interaction, membre: discord.Member) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return
        warnings = self.bot.get_warning_store(interaction.guild.id).get(str(membre.id), [])
        if not warnings:
            await interaction.response.send_message(
                f"{membre.mention} n'a aucun avertissement.",
                ephemeral=True,
            )
            return
        embed = discord.Embed(
            title=f"Avertissements de {membre}",
            color=discord.Color.orange(),
        )
        for index, warning in enumerate(warnings, start=1):
            embed.add_field(
                name=f"Warn #{index}",
                value=(
                    f"Raison : {warning['reason']}\n"
                    f"Staff : {warning['moderator_name']}\n"
                    f"Date : {warning['created_at']}"
                ),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)
