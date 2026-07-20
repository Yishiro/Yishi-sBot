from __future__ import annotations

import asyncio
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
    LINK_PATTERN,
    RULES_ACCEPT_TEXT,
    RULES_TEXT,
    WELCOME_ADVANTAGES,
    WELCOME_CHECKLIST,
)
from yishi_bot.helpers import can_moderate, parse_duration, split_long_message
from yishi_bot.views import AnnouncementModal, TicketPanelView

if TYPE_CHECKING:
    from yishi_bot.core import YishiBot


class EventsCog(commands.Cog):
    def __init__(self, bot: YishiBot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        await self.bot.sync_commands_once()
        print(f"Bot connecté en tant que {self.bot.user}")

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        try:
            await self.bot.sync_guild_commands(guild)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite) -> None:
        if invite.guild is not None:
            await self.bot.cache_invites(invite.guild)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite) -> None:
        if invite.guild is not None:
            await self.bot.cache_invites(invite.guild)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        config = self.bot.get_guild_config(member.guild.id)
        welcome_channel = (
            member.guild.get_channel(config["welcome_channel_id"])
            if config["welcome_channel_id"]
            else member.guild.system_channel
        )
        inviter = await self.bot.track_member_invite(member)
        if not isinstance(welcome_channel, discord.TextChannel):
            return

        embed = discord.Embed(
            title="Nouveau membre !",
            description=(
                f"## Bienvenue, {member.mention} 👋\n"
                f"Tu es le **{member.guild.member_count}ème membre** à rejoindre **Yishi's Shop**."
            ),
            color=discord.Color.gold(),
        )
        embed.add_field(name="Avant de commencer", value=WELCOME_CHECKLIST, inline=False)
        embed.add_field(name="Pourquoi nous choisir", value=WELCOME_ADVANTAGES, inline=False)
        embed.add_field(
            name="Invitation",
            value=f"Invité par {inviter.mention}" if inviter is not None else "Inviteur non détecté",
            inline=False,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        if member.guild.banner:
            embed.set_image(url=member.guild.banner.url)
        embed.set_author(
            name=member.guild.name,
            icon_url=member.guild.icon.url if member.guild.icon else None,
        )
        embed.set_footer(
            text=f"Bienvenue parmi nous • {discord.utils.utcnow().strftime('%H:%M')}",
            icon_url=member.guild.icon.url if member.guild.icon else None,
        )
        await welcome_channel.send(embed=embed)
        await self.bot.log_event(
            member.guild,
            "👋 Membre rejoint",
            f"{member.mention} a rejoint le serveur.",
            discord.Color.green(),
            thumbnail_url=member.display_avatar.url,
            fields=[
                ("Membres totaux", str(member.guild.member_count), True),
                ("Compte créé", member.created_at.strftime("%d/%m/%Y %H:%M"), True),
            ],
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        await self.bot.log_event(
            member.guild,
            "📤 Membre parti",
            f"{member} a quitté le serveur.",
            discord.Color.red(),
            thumbnail_url=member.display_avatar.url,
            fields=[("Membres restants", str(member.guild.member_count), True)],
        )

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        before_roles = {role.id: role.name for role in before.roles if role != before.guild.default_role}
        after_roles = {role.id: role.name for role in after.roles if role != after.guild.default_role}
        added = [name for role_id, name in after_roles.items() if role_id not in before_roles]
        removed = [name for role_id, name in before_roles.items() if role_id not in after_roles]
        if added or removed:
            fields: list[tuple[str, str, bool]] = []
            if added:
                fields.append(("Ajoutés", "\n".join(f"• {role}" for role in added), False))
            if removed:
                fields.append(("Retirés", "\n".join(f"• {role}" for role in removed), False))
            await self.bot.log_event(
                after.guild,
                "🎭 Rôles modifiés",
                f"Les rôles de {after.mention} ont été modifiés.",
                discord.Color.blurple(),
                thumbnail_url=after.display_avatar.url,
                fields=fields,
            )

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        await self.bot.log_event(
            message.guild,
            "🗑️ Message supprimé",
            f"Un message de {message.author.mention} a été supprimé dans {message.channel.mention}.",
            discord.Color.red(),
            thumbnail_url=message.author.display_avatar.url,
            fields=[("Contenu", message.content or "[vide ou embed]", False)],
        )

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.guild is None or before.author.bot or before.content == after.content:
            return
        await self.bot.log_event(
            before.guild,
            "✏️ Message modifié",
            f"Un message de {before.author.mention} a été modifié dans {before.channel.mention}.",
            discord.Color.orange(),
            thumbnail_url=before.author.display_avatar.url,
            fields=[
                ("Avant", before.content or "[vide]", False),
                ("Après", after.content or "[vide]", False),
            ],
        )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if before.channel == after.channel:
            return
        if after.channel is not None:
            await self.bot.log_event(
                member.guild,
                "🔊 Connexion vocale",
                f"{member.mention} a rejoint un salon vocal.",
                discord.Color.green(),
                thumbnail_url=member.display_avatar.url,
                fields=[("Salon", after.channel.name, True)],
            )
        elif before.channel is not None:
            await self.bot.log_event(
                member.guild,
                "🔇 Déconnexion vocale",
                f"{member.mention} a quitté un salon vocal.",
                discord.Color.orange(),
                thumbnail_url=member.display_avatar.url,
                fields=[("Salon", before.channel.name, True)],
            )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot or not isinstance(message.author, discord.Member):
            return
        if self.bot.is_staff_member(message.author):
            return
        if LINK_PATTERN.search(message.content):
            try:
                await message.delete()
            except discord.HTTPException:
                return
            await self.bot.log_event(
                message.guild,
                "🔗 Lien bloqué",
                f"Un lien envoyé par {message.author.mention} a été supprimé dans {message.channel.mention}.",
                discord.Color.red(),
                thumbnail_url=message.author.display_avatar.url,
                fields=[("Contenu", message.content, False)],
            )
            warning = await message.channel.send(
                f"{message.author.mention}, les liens ne sont pas autorisés ici."
            )
            await asyncio.sleep(8)
            try:
                await warning.delete()
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None or str(payload.emoji) != "✅":
            return
        if self.bot.user is not None and payload.user_id == self.bot.user.id:
            return

        config = self.bot.get_guild_config(payload.guild_id)
        if payload.message_id != config["rules_message_id"]:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        role = guild.get_role(config["rules_role_id"]) if config["rules_role_id"] else None
        try:
            member = guild.get_member(payload.user_id) or await guild.fetch_member(payload.user_id)
        except (discord.Forbidden, discord.NotFound):
            return
        if role is None or member.bot or role in member.roles:
            return
        await member.add_roles(role, reason="Validation du règlement par réaction")
