from __future__ import annotations

import asyncio
import io
import random
from datetime import timedelta
from typing import Any, Literal

import discord
from discord import app_commands
from discord.ext import commands

from storage import (
    CONFIG_FILE,
    GACHA_FILE,
    GIVEAWAYS_FILE,
    INVITES_FILE,
    TICKETS_FILE,
    WARNINGS_FILE,
    load_json,
    save_json,
)
from tickets import TICKET_TYPES, build_custom_ticket_panel_embed, build_ticket_panel_embed, slugify_name
from yishi_bot.cogs.configuration import ConfigurationCog
from yishi_bot.cogs.events import EventsCog
from yishi_bot.cogs.gacha import GachaCog
from yishi_bot.cogs.general import GeneralCog
from yishi_bot.cogs.giveaways import GiveawaysCog
from yishi_bot.cogs.moderation import ModerationCog
from yishi_bot.cogs.tickets import TicketsCog
from yishi_bot.constants import *
from yishi_bot.helpers import (
    can_moderate,
    default_config,
    default_gacha_store,
    get_member_giveaway_weight,
    merge_missing_defaults,
    parse_duration,
    split_long_message,
)
from yishi_bot.views import GiveawayView, TicketArchiveView, TicketCloseView, TicketPanelView

class YishiBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

        self.config_data = load_json(CONFIG_FILE, {})
        self.ticket_data = load_json(TICKETS_FILE, {})
        self.warning_data = load_json(WARNINGS_FILE, {})
        self.invite_data = load_json(INVITES_FILE, {})
        self.giveaway_data = load_json(GIVEAWAYS_FILE, {})
        self.gacha_data = load_json(GACHA_FILE, default_gacha_store())
        if self._migrate_invite_data():
            self.save_invites()
        if merge_missing_defaults(self.gacha_data, default_gacha_store()):
            self.save_gacha()

        self.invite_cache: dict[int, dict[str, int]] = {}
        self.giveaway_tasks: dict[str, asyncio.Task] = {}
        self.pending_ticket_creations: set[tuple[int, int]] = set()
        self.pending_gacha_spins: set[tuple[int, int]] = set()
        self.sync_done = False
        self.synced_guild_ids: set[int] = set()

    async def setup_hook(self) -> None:
        self.add_view(TicketPanelView(self))
        self.add_view(TicketCloseView(self))
        self.add_view(TicketArchiveView(self))
        self.add_view(GiveawayView(self))

        await self.add_cog(EventsCog(self))
        await self.add_cog(GeneralCog(self))
        await self.add_cog(GachaCog(self))
        await self.add_cog(ModerationCog(self))
        await self.add_cog(TicketsCog(self))
        await self.add_cog(GiveawaysCog(self))
        await self.add_cog(ConfigurationCog(self))

    def get_guild_config(self, guild_id: int) -> dict[str, Any]:
        key = str(guild_id)
        changed = False
        if key not in self.config_data:
            self.config_data[key] = default_config()
            changed = True
        else:
            changed = merge_missing_defaults(self.config_data[key], default_config())
        if changed:
            self.save_config()
        return self.config_data[key]

    def get_ticket_store(self, guild_id: int) -> dict[str, Any]:
        key = str(guild_id)
        if key not in self.ticket_data:
            self.ticket_data[key] = {"channels": {}}
            self.save_tickets()
        return self.ticket_data[key]

    def get_warning_store(self, guild_id: int) -> dict[str, Any]:
        key = str(guild_id)
        if key not in self.warning_data:
            self.warning_data[key] = {}
            self.save_warnings()
        return self.warning_data[key]

    def default_invite_store(self) -> dict[str, Any]:
        return {
            "counts": {},
            "invite_snapshot": {},
            "member_inviter_ids": {},
        }

    def _migrate_invite_data(self) -> bool:
        changed = False
        for guild_id, value in list(self.invite_data.items()):
            if not isinstance(value, dict):
                self.invite_data[guild_id] = self.default_invite_store()
                changed = True
                continue

            if "counts" not in value:
                legacy_counts = {
                    str(user_id): int(count)
                    for user_id, count in value.items()
                    if isinstance(count, (int, float, str)) and str(count).lstrip("-").isdigit()
                }
                self.invite_data[guild_id] = {
                    "counts": legacy_counts,
                    "invite_snapshot": {},
                    "member_inviter_ids": {},
                }
                changed = True
                continue

            defaults = self.default_invite_store()
            for key, default_value in defaults.items():
                if key not in value or not isinstance(value[key], dict):
                    value[key] = default_value.copy()
                    changed = True

            normalized_counts: dict[str, int] = {}
            for user_id, count in value["counts"].items():
                try:
                    normalized_counts[str(user_id)] = int(count)
                except (TypeError, ValueError):
                    changed = True
            if normalized_counts != value["counts"]:
                value["counts"] = normalized_counts
                changed = True

            normalized_snapshot: dict[str, int] = {}
            for code, uses in value["invite_snapshot"].items():
                try:
                    normalized_snapshot[str(code)] = int(uses)
                except (TypeError, ValueError):
                    changed = True
            if normalized_snapshot != value["invite_snapshot"]:
                value["invite_snapshot"] = normalized_snapshot
                changed = True

            normalized_member_inviter_ids: dict[str, int] = {}
            for member_id, inviter_id in value["member_inviter_ids"].items():
                try:
                    normalized_member_inviter_ids[str(member_id)] = int(inviter_id)
                except (TypeError, ValueError):
                    changed = True
            if normalized_member_inviter_ids != value["member_inviter_ids"]:
                value["member_inviter_ids"] = normalized_member_inviter_ids
                changed = True

        return changed

    def get_invite_store(self, guild_id: int) -> dict[str, Any]:
        key = str(guild_id)
        if key not in self.invite_data:
            self.invite_data[key] = self.default_invite_store()
            self.save_invites()
        elif not isinstance(self.invite_data[key], dict) or "counts" not in self.invite_data[key]:
            self._migrate_invite_data()
            self.save_invites()
        return self.invite_data[key]

    def get_giveaway_store(self, guild_id: int) -> dict[str, Any]:
        key = str(guild_id)
        if key not in self.giveaway_data:
            self.giveaway_data[key] = {}
            self.save_giveaways()
        return self.giveaway_data[key]

    def save_config(self) -> None:
        save_json(CONFIG_FILE, self.config_data)

    def save_tickets(self) -> None:
        save_json(TICKETS_FILE, self.ticket_data)

    def save_warnings(self) -> None:
        save_json(WARNINGS_FILE, self.warning_data)

    def save_invites(self) -> None:
        save_json(INVITES_FILE, self.invite_data)

    def save_giveaways(self) -> None:
        save_json(GIVEAWAYS_FILE, self.giveaway_data)

    def save_gacha(self) -> None:
        save_json(GACHA_FILE, self.gacha_data)

    def get_invite_count(self, guild_id: int, user_id: int) -> int:
        counts = self.get_invite_store(guild_id)["counts"]
        return int(counts.get(str(user_id), 0))

    def get_member_inviter_id(self, guild_id: int, member_id: int) -> int | None:
        inviter_id = self.get_invite_store(guild_id)["member_inviter_ids"].get(str(member_id))
        return int(inviter_id) if inviter_id is not None else None

    def get_gacha_inventory(self, user_id: int) -> dict[str, int]:
        key = str(user_id)
        inventories = self.gacha_data.setdefault("inventories", {})
        if key not in inventories:
            inventories[key] = {"basic": 0, "advanced": 0, "deluxe": 0}
            self.save_gacha()
        return inventories[key]

    def get_member_notes(self, user_id: int) -> list[dict[str, Any]]:
        key = str(user_id)
        notes = self.gacha_data.setdefault("member_notes", {})
        if key not in notes:
            notes[key] = []
            self.save_gacha()
        return notes[key]

    def add_member_note(self, user_id: int, author_id: int, author_name: str, content: str) -> dict[str, Any]:
        note = {
            "author_id": author_id,
            "author_name": author_name,
            "content": content,
            "timestamp": discord.utils.utcnow().isoformat(),
        }
        self.get_member_notes(user_id).append(note)
        self.save_gacha()
        return note

    def remove_member_note(self, user_id: int, index: int) -> dict[str, Any] | None:
        notes = self.get_member_notes(user_id)
        if index < 0 or index >= len(notes):
            return None
        removed = notes.pop(index)
        self.save_gacha()
        return removed

    def record_spin_adjustment(
        self,
        target_id: int,
        target_name: str,
        actor_id: int,
        actor_name: str,
        spin_type: str,
        quantity: int,
        action: str,
        reason: str | None,
        total_after: int,
    ) -> None:
        self.gacha_data.setdefault("grant_history", []).append(
            {
                "target_id": target_id,
                "target_name": target_name,
                "actor_id": actor_id,
                "actor_name": actor_name,
                "spin_type": spin_type,
                "quantity": quantity,
                "action": action,
                "reason": reason or "",
                "total_after": total_after,
                "timestamp": discord.utils.utcnow().isoformat(),
            }
        )
        self.save_gacha()

    def get_member_grant_history(self, user_id: int) -> list[dict[str, Any]]:
        return [
            entry
            for entry in self.gacha_data.get("grant_history", [])
            if int(entry.get("target_id", 0)) == user_id
        ]

    def get_open_tickets_for_user(self, guild_id: int, user_id: int) -> list[dict[str, Any]]:
        return [
            ticket
            for ticket in self.get_ticket_store(guild_id)["channels"].values()
            if ticket["owner_id"] == user_id and ticket["status"] == "open"
        ]

    def get_next_ticket_number(self, guild_id: int) -> int:
        tickets = self.get_ticket_store(guild_id)["channels"].values()
        used_numbers = sorted(
            ticket["number"]
            for ticket in tickets
            if ticket["status"] == "open"
        )

        expected = 1
        for number in used_numbers:
            if number == expected:
                expected += 1
            elif number > expected:
                break
        return expected

    def get_bot_member(self, guild: discord.Guild) -> discord.Member | None:
        if self.user is None:
            return None
        return guild.get_member(self.user.id)

    def get_logs_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        config = self.get_guild_config(guild.id)
        channel = guild.get_channel(config["logs_channel_id"]) if config["logs_channel_id"] else None
        return channel if isinstance(channel, discord.TextChannel) else None

    def get_transcript_logs_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        config = self.get_guild_config(guild.id)
        channel = (
            guild.get_channel(config["transcript_logs_channel_id"])
            if config["transcript_logs_channel_id"]
            else None
        )
        return channel if isinstance(channel, discord.TextChannel) else None

    def get_gacha_spin_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        config = self.get_guild_config(guild.id)
        channel = guild.get_channel(config["gacha_spin_channel_id"]) if config["gacha_spin_channel_id"] else None
        return channel if isinstance(channel, discord.TextChannel) else None

    def get_gacha_winner_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        config = self.get_guild_config(guild.id)
        channel = guild.get_channel(config["gacha_winner_channel_id"]) if config["gacha_winner_channel_id"] else None
        return channel if isinstance(channel, discord.TextChannel) else None

    def get_gacha_logs_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        config = self.get_guild_config(guild.id)
        channel = guild.get_channel(config["gacha_logs_channel_id"]) if config["gacha_logs_channel_id"] else None
        return channel if isinstance(channel, discord.TextChannel) else None

    async def log_event(
        self,
        guild: discord.Guild,
        title: str,
        description: str,
        color: discord.Color,
        *,
        thumbnail_url: str | None = None,
        fields: list[tuple[str, str, bool]] | None = None,
    ) -> None:
        channel = self.get_logs_channel(guild)
        if channel is None:
            return

        embed = discord.Embed(title=title, description=description, color=color)
        if thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url)
        if fields:
            for name, value, inline in fields:
                embed.add_field(name=name, value=value[:1024] or "Aucune donnée", inline=inline)
        embed.set_footer(text=f"ID serveur : {guild.id} • {discord.utils.utcnow().strftime('%d/%m/%Y %H:%M')}")
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    def is_staff_member(self, member: discord.Member) -> bool:
        config = self.get_guild_config(member.guild.id)
        staff_role = member.guild.get_role(config["staff_role_id"]) if config["staff_role_id"] else None
        archive_role = member.guild.get_role(config["archive_role_id"]) if config["archive_role_id"] else None
        return (
            member.id == member.guild.owner_id
            or member.guild_permissions.manage_guild
            or (staff_role is not None and staff_role in member.roles)
            or (archive_role is not None and archive_role in member.roles)
        )

    async def configure_logs_channel_permissions(self, guild: discord.Guild, channel: discord.TextChannel) -> None:
        config = self.get_guild_config(guild.id)
        staff_role = guild.get_role(config["staff_role_id"]) if config["staff_role_id"] else None
        archive_role = guild.get_role(config["archive_role_id"]) if config["archive_role_id"] else None
        await channel.set_permissions(guild.default_role, view_channel=False)
        if staff_role is not None:
            await channel.set_permissions(
                staff_role,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )
        if archive_role is not None:
            await channel.set_permissions(
                archive_role,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )
        if guild.owner is not None:
            await channel.set_permissions(
                guild.owner,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
            )

    async def configure_staff_only_channel(self, guild: discord.Guild, channel: discord.TextChannel) -> None:
        await self.configure_logs_channel_permissions(guild, channel)

    def format_remaining_duration(self, end_at: int) -> str:
        remaining = end_at - int(discord.utils.utcnow().timestamp())
        if remaining <= 0:
            return "Terminé"
        days, rem = divmod(remaining, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, seconds = divmod(rem, 60)
        parts: list[str] = []
        if days:
            parts.append(f"{days}j")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if seconds or not parts:
            parts.append(f"{seconds}s")
        return " ".join(parts)

    async def build_ticket_transcript(self, channel: discord.TextChannel) -> str:
        lines: list[str] = []
        async for message in channel.history(limit=None, oldest_first=True):
            created = message.created_at.strftime("%d/%m/%Y %H:%M")
            content = message.content or ""
            if message.embeds and not content:
                content = "[embed]"
            if message.attachments:
                attachments = ", ".join(attachment.url for attachment in message.attachments)
                content = f"{content}\nPièces jointes : {attachments}".strip()
            lines.append(f"[{created}] {message.author} : {content}".strip())
        return "\n".join(lines) or "Aucun message dans ce ticket."

    async def send_ticket_transcript(self, channel: discord.TextChannel) -> None:
        transcript = await self.build_ticket_transcript(channel)
        transcript_bytes = transcript.encode("utf-8")
        recipients = [
            member
            for member in channel.members
            if not member.bot and channel.permissions_for(member).view_channel
        ]
        for member in recipients:
            try:
                file = discord.File(
                    io.BytesIO(transcript_bytes),
                    filename=f"transcript-{channel.name}.txt",
                )
                await member.send(
                    content=f"Transcript du ticket **{channel.name}**",
                    file=file,
                )
            except discord.Forbidden:
                continue

        transcript_channel = self.get_transcript_logs_channel(channel.guild)
        if transcript_channel is not None:
            try:
                file = discord.File(
                    io.BytesIO(transcript_bytes),
                    filename=f"transcript-{channel.name}.txt",
                )
                await transcript_channel.send(
                    content=f"Transcript du ticket **{channel.name}**",
                    file=file,
                )
            except discord.HTTPException:
                pass

    def add_gacha_spins(self, user_id: int, spin_type: str, quantity: int) -> int:
        inventory = self.get_gacha_inventory(user_id)
        inventory[spin_type] = int(inventory.get(spin_type, 0)) + quantity
        self.save_gacha()
        return inventory[spin_type]

    def remove_gacha_spins(self, user_id: int, spin_type: str, quantity: int) -> int:
        inventory = self.get_gacha_inventory(user_id)
        current = int(inventory.get(spin_type, 0))
        new_total = max(0, current - quantity)
        inventory[spin_type] = new_total
        self.save_gacha()
        return new_total

    def next_claim_number(self) -> int:
        number = int(self.gacha_data.get("next_claim_number", 1))
        self.gacha_data["next_claim_number"] = number + 1
        self.save_gacha()
        return number

    def roll_gacha_rarity(self, spin_type: str) -> str:
        roll = random.uniform(0, 100)
        running = 0.0
        for rarity, rewards in GACHA_REWARDS[spin_type].items():
            running += sum(float(reward["chance"]) for reward in rewards)
            if roll <= running:
                return rarity
        return list(GACHA_REWARDS[spin_type].keys())[-1]

    def roll_gacha_reward(self, spin_type: str, rarity: str) -> dict[str, Any]:
        rewards = GACHA_REWARDS[spin_type][rarity]
        total = sum(float(reward["chance"]) for reward in rewards)
        local_roll = random.uniform(0, total)
        running = 0.0
        for reward in rewards:
            running += float(reward["chance"])
            if local_roll <= running:
                return reward
        return rewards[-1]

    def build_gacha_result_embed(
        self,
        member: discord.Member,
        spin_type: str,
        rarity: str,
        reward: dict[str, Any],
        claim_number: int,
    ) -> discord.Embed:
        color = GACHA_RARITY_COLORS.get(rarity, discord.Color.blurple())
        embed = discord.Embed(
            title=f"{GACHA_RARITY_EMOJIS.get(rarity, '🎰')} Spin Result",
            description=f"Congratulations **{member.display_name}**!",
            color=color,
        )
        embed.add_field(name="Spin Type", value=spin_type.title(), inline=True)
        embed.add_field(name="Reward", value=reward["name"], inline=True)
        embed.add_field(name="Rarity", value=rarity, inline=True)
        embed.add_field(name="Type", value=reward["reward_type"], inline=True)
        embed.add_field(name="Claim Number", value=f"`{claim_number}`", inline=True)
        embed.add_field(
            name="Claim",
            value="Open a ticket and send this claim number to receive your reward.",
            inline=False,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        return embed

    def build_gacha_log_embed(
        self,
        member: discord.Member,
        spin_type: str,
        rarity: str,
        reward: dict[str, Any],
        claim_number: int,
    ) -> discord.Embed:
        embed = discord.Embed(
            title="📒 Gacha Log",
            color=GACHA_RARITY_COLORS.get(rarity, discord.Color.blurple()),
        )
        embed.add_field(name="Player", value=f"{member.mention}\n`{member.id}`", inline=True)
        embed.add_field(name="Spin", value=spin_type.title(), inline=True)
        embed.add_field(name="Reward", value=reward["name"], inline=True)
        embed.add_field(name="Rarity", value=rarity, inline=True)
        embed.add_field(name="Type", value=reward["reward_type"], inline=True)
        embed.add_field(name="Claim Number", value=f"`{claim_number}`", inline=True)
        embed.set_footer(text=discord.utils.utcnow().strftime("%d/%m/%Y %H:%M"))
        return embed

    async def log_gacha_spin(
        self,
        guild: discord.Guild,
        member: discord.Member,
        spin_type: str,
        rarity: str,
        reward: dict[str, Any],
        claim_number: int,
    ) -> None:
        channel = self.get_gacha_logs_channel(guild)
        if channel is None:
            return
        try:
            await channel.send(embed=self.build_gacha_log_embed(member, spin_type, rarity, reward, claim_number))
        except discord.HTTPException:
            pass

    async def animate_gacha_rarity(
        self,
        message: discord.Message,
        spin_type: str,
        final_rarity: str,
    ) -> None:
        rarity_order = list(GACHA_REWARDS[spin_type].keys())
        sequence: list[str] = []
        for _ in range(8):
            sequence.append(random.choice(rarity_order))
        sequence.extend([random.choice(rarity_order), final_rarity, final_rarity])
        delays = [0.25, 0.25, 0.30, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.65, 0.80]
        for rarity, delay in zip(sequence, delays):
            embed = discord.Embed(
                title=f"{GACHA_RARITY_EMOJIS.get(rarity, '🎰')} {rarity}",
                description=f"{spin_type.title()} Spin in progress...",
                color=GACHA_RARITY_COLORS.get(rarity, discord.Color.blurple()),
            )
            await message.edit(embed=embed)
            await asyncio.sleep(delay)

    async def execute_gacha_spin(
        self,
        interaction: discord.Interaction,
        spin_type: Literal["basic", "advanced", "deluxe"],
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        gacha_channel = self.get_gacha_spin_channel(interaction.guild)
        if gacha_channel is None or interaction.channel_id != gacha_channel.id:
            mention = gacha_channel.mention if gacha_channel is not None else AUTO_GACHA_SPIN_CHANNEL_NAME
            await interaction.response.send_message(
                f"Utilise cette commande dans {mention}.",
                ephemeral=True,
            )
            return

        lock_key = (interaction.guild.id, interaction.user.id)
        if lock_key in self.pending_gacha_spins:
            await interaction.response.send_message("Tu as déjà un spin en cours.", ephemeral=True)
            return

        inventory = self.get_gacha_inventory(interaction.user.id)
        if int(inventory.get(spin_type, 0)) <= 0:
            await interaction.response.send_message(
                f"Tu n'as aucun {spin_type.title()} Spin disponible.",
                ephemeral=True,
            )
            return

        self.pending_gacha_spins.add(lock_key)
        try:
            inventory[spin_type] = int(inventory.get(spin_type, 0)) - 1
            self.save_gacha()

            rarity = self.roll_gacha_rarity(spin_type)
            reward = self.roll_gacha_reward(spin_type, rarity)
            claim_number = self.next_claim_number()

            await interaction.response.defer()
            animation_embed = discord.Embed(
                title="🎰 Spin Starting",
                description=f"{interaction.user.display_name} is rolling a {spin_type.title()} Spin...",
                color=discord.Color.blurple(),
            )
            animation_message = await interaction.followup.send(embed=animation_embed, wait=True)
            await self.animate_gacha_rarity(animation_message, spin_type, rarity)

            winner_channel = self.get_gacha_winner_channel(interaction.guild)
            if winner_channel is None:
                winner_channel = gacha_channel

            result_embed = self.build_gacha_result_embed(
                interaction.user,
                spin_type,
                rarity,
                reward,
                claim_number,
            )
            await winner_channel.send(embed=result_embed)

            if rarity in {"Legendary", "Mythical", "Secret"}:
                await winner_channel.send(
                    f"🌟 Big Win! {interaction.user.display_name} just won **{reward['name']}** from a **{spin_type.title()} Spin**!"
                )

            self.gacha_data.setdefault("history", []).append(
                {
                    "user_id": interaction.user.id,
                    "display_name": interaction.user.display_name,
                    "spin_type": spin_type,
                    "reward": reward["name"],
                    "rarity": rarity,
                    "reward_type": reward["reward_type"],
                    "claim_number": claim_number,
                    "timestamp": discord.utils.utcnow().isoformat(),
                }
            )
            self.save_gacha()
            await self.log_gacha_spin(
                interaction.guild,
                interaction.user,
                spin_type,
                rarity,
                reward,
                claim_number,
            )
        finally:
            self.pending_gacha_spins.discard(lock_key)

    def build_gacha_rates_embed(self, spin_type: str) -> discord.Embed:
        rarity_order = ("Common", "Rare", "Epic", "Legendary", "Mythical", "Secret")
        spin_data = GACHA_REWARDS[spin_type]
        color_map = {
            "basic": discord.Color.green(),
            "advanced": discord.Color.blue(),
            "deluxe": discord.Color.purple(),
        }
        icon_map = {
            "basic": "🟢",
            "advanced": "🔵",
            "deluxe": "🟣",
        }
        embed = discord.Embed(
            title=f"{icon_map.get(spin_type, '🎰')} {spin_type.title()} Spin",
            description="Taux de drop et récompenses possibles.",
            color=color_map.get(spin_type, discord.Color.blurple()),
        )

        rarity_lines: list[str] = []
        reward_lines: list[str] = []
        for rarity in rarity_order:
            rewards = spin_data.get(rarity)
            if not rewards:
                continue
            total = sum(float(reward["chance"]) for reward in rewards)
            total_display = f"{int(total)}%" if total.is_integer() else f"{total:.2f}%"
            rarity_lines.append(f"• {rarity}: **{total_display}**")
            reward_lines.append(f"• {rarity}: {', '.join(reward['name'] for reward in rewards)}")

        embed.add_field(name="Raretés", value="\n".join(rarity_lines), inline=False)
        embed.add_field(name="Possible Rewards", value="\n".join(reward_lines), inline=False)
        embed.set_footer(text="Les taux affichés correspondent aux chances réelles du spin.")
        return embed

    async def ensure_ticket_config(self, guild: discord.Guild) -> None:
        config = self.get_guild_config(guild.id)

        staff_role = guild.get_role(config["staff_role_id"]) if config["staff_role_id"] else None
        if staff_role is None:
            staff_role = discord.utils.get(guild.roles, name=AUTO_STAFF_ROLE_NAME)
            if staff_role is None:
                staff_role = await guild.create_role(
                    name=AUTO_STAFF_ROLE_NAME,
                    reason="Auto configuration tickets",
                )
            config["staff_role_id"] = staff_role.id

        archive_role = guild.get_role(config["archive_role_id"]) if config["archive_role_id"] else None
        if archive_role is None:
            archive_role = discord.utils.get(guild.roles, name=AUTO_ARCHIVE_ROLE_NAME)
            if archive_role is None:
                archive_role = await guild.create_role(
                    name=AUTO_ARCHIVE_ROLE_NAME,
                    reason="Auto configuration tickets",
                )
            config["archive_role_id"] = archive_role.id

        ticket_category = guild.get_channel(config["ticket_category_id"]) if config["ticket_category_id"] else None
        if not isinstance(ticket_category, discord.CategoryChannel):
            ticket_category = discord.utils.get(guild.categories, name=AUTO_TICKET_CATEGORY_NAME)
            if ticket_category is None:
                ticket_category = await guild.create_category(
                    AUTO_TICKET_CATEGORY_NAME,
                    reason="Auto configuration tickets",
                )
            config["ticket_category_id"] = ticket_category.id

        archive_category = guild.get_channel(config["archive_category_id"]) if config["archive_category_id"] else None
        if not isinstance(archive_category, discord.CategoryChannel):
            archive_category = discord.utils.get(guild.categories, name=AUTO_ARCHIVE_CATEGORY_NAME)
            if archive_category is None:
                archive_category = await guild.create_category(
                    AUTO_ARCHIVE_CATEGORY_NAME,
                    reason="Auto configuration tickets",
                )
            config["archive_category_id"] = archive_category.id

        logs_channel = guild.get_channel(config["logs_channel_id"]) if config["logs_channel_id"] else None
        if not isinstance(logs_channel, discord.TextChannel):
            logs_channel = discord.utils.get(guild.text_channels, name=AUTO_LOGS_CHANNEL_NAME)
            if logs_channel is None:
                logs_channel = await guild.create_text_channel(
                    AUTO_LOGS_CHANNEL_NAME,
                    reason="Auto configuration logs",
                )
            config["logs_channel_id"] = logs_channel.id
        await self.configure_logs_channel_permissions(guild, logs_channel)

        transcript_logs_channel = (
            guild.get_channel(config["transcript_logs_channel_id"])
            if config["transcript_logs_channel_id"]
            else None
        )
        if not isinstance(transcript_logs_channel, discord.TextChannel):
            transcript_logs_channel = discord.utils.get(
                guild.text_channels,
                name=AUTO_TRANSCRIPT_CHANNEL_NAME,
            )
            if transcript_logs_channel is None:
                transcript_logs_channel = await guild.create_text_channel(
                    AUTO_TRANSCRIPT_CHANNEL_NAME,
                    reason="Auto configuration transcript logs",
                )
            config["transcript_logs_channel_id"] = transcript_logs_channel.id
        await self.configure_staff_only_channel(guild, transcript_logs_channel)

        gacha_spin_channel = guild.get_channel(config["gacha_spin_channel_id"]) if config["gacha_spin_channel_id"] else None
        if not isinstance(gacha_spin_channel, discord.TextChannel):
            gacha_spin_channel = discord.utils.get(guild.text_channels, name=AUTO_GACHA_SPIN_CHANNEL_NAME)
            if gacha_spin_channel is None:
                gacha_spin_channel = await guild.create_text_channel(
                    AUTO_GACHA_SPIN_CHANNEL_NAME,
                    reason="Auto configuration gacha spin",
                )
            config["gacha_spin_channel_id"] = gacha_spin_channel.id

        gacha_winner_channel = guild.get_channel(config["gacha_winner_channel_id"]) if config["gacha_winner_channel_id"] else None
        if not isinstance(gacha_winner_channel, discord.TextChannel):
            gacha_winner_channel = discord.utils.get(guild.text_channels, name=AUTO_GACHA_WINNER_CHANNEL_NAME)
            if gacha_winner_channel is None:
                gacha_winner_channel = await guild.create_text_channel(
                    AUTO_GACHA_WINNER_CHANNEL_NAME,
                    reason="Auto configuration gacha winners",
                )
            config["gacha_winner_channel_id"] = gacha_winner_channel.id

        gacha_logs_channel = guild.get_channel(config["gacha_logs_channel_id"]) if config["gacha_logs_channel_id"] else None
        if not isinstance(gacha_logs_channel, discord.TextChannel):
            gacha_logs_channel = discord.utils.get(guild.text_channels, name=AUTO_GACHA_LOGS_CHANNEL_NAME)
            if gacha_logs_channel is None:
                gacha_logs_channel = await guild.create_text_channel(
                    AUTO_GACHA_LOGS_CHANNEL_NAME,
                    reason="Auto configuration gacha logs",
                )
            config["gacha_logs_channel_id"] = gacha_logs_channel.id
        await self.configure_staff_only_channel(guild, gacha_logs_channel)

        self.save_config()

    async def cache_invites(self, guild: discord.Guild) -> None:
        store = self.get_invite_store(guild.id)
        saved_snapshot = {
            str(code): int(uses)
            for code, uses in store.get("invite_snapshot", {}).items()
        }
        try:
            invites = await guild.invites()
        except discord.Forbidden:
            self.invite_cache[guild.id] = saved_snapshot
            return

        current_snapshot = {invite.code: invite.uses or 0 for invite in invites}
        self.invite_cache[guild.id] = current_snapshot
        if current_snapshot != saved_snapshot:
            store["invite_snapshot"] = current_snapshot
            self.save_invites()

    async def track_member_invite(self, member: discord.Member) -> discord.Member | None:
        store = self.get_invite_store(member.guild.id)
        before = self.invite_cache.get(
            member.guild.id,
            {
                str(code): int(uses)
                for code, uses in store.get("invite_snapshot", {}).items()
            },
        )
        try:
            invites = await member.guild.invites()
        except discord.Forbidden:
            return None

        inviter: discord.abc.User | None = None
        after = {invite.code: invite.uses or 0 for invite in invites}
        for invite in invites:
            previous_uses = before.get(invite.code, 0)
            current_uses = invite.uses or 0
            if current_uses > previous_uses and invite.inviter is not None:
                inviter = invite.inviter
                break

        self.invite_cache[member.guild.id] = after
        store["invite_snapshot"] = after
        if inviter is None:
            self.save_invites()
            return None

        key = str(inviter.id)
        counts = store["counts"]
        counts[key] = int(counts.get(key, 0)) + 1
        store["member_inviter_ids"][str(member.id)] = inviter.id
        self.save_invites()
        return member.guild.get_member(inviter.id)

    async def schedule_existing_giveaways(self) -> None:
        for guild_id, giveaways in self.giveaway_data.items():
            for message_id, giveaway in giveaways.items():
                if giveaway.get("status") == "active":
                    self.schedule_giveaway_end(
                        int(guild_id),
                        int(message_id),
                        int(giveaway["end_at"]),
                    )

    def schedule_giveaway_end(self, guild_id: int, message_id: int, end_at: int) -> None:
        task_key = f"{guild_id}:{message_id}"
        existing = self.giveaway_tasks.get(task_key)
        if existing is not None:
            existing.cancel()
        self.giveaway_tasks[task_key] = asyncio.create_task(
            self._giveaway_end_task(guild_id, message_id, end_at)
        )

    async def _giveaway_end_task(self, guild_id: int, message_id: int, end_at: int) -> None:
        await asyncio.sleep(max(0, end_at - int(discord.utils.utcnow().timestamp())))
        await self.finish_giveaway(guild_id, message_id)

    def cancel_giveaway_task(self, guild_id: int, message_id: int) -> None:
        task_key = f"{guild_id}:{message_id}"
        existing = self.giveaway_tasks.pop(task_key, None)
        if existing is not None:
            existing.cancel()

    async def send_rules_text(self, channel: discord.TextChannel) -> None:
        for part in split_long_message(RULES_TEXT):
            await channel.send(part)

    async def create_ticket(self, interaction: discord.Interaction, ticket_type: str) -> None:
        guild = interaction.guild
        user = interaction.user
        if guild is None or not isinstance(user, discord.Member):
            await interaction.response.send_message(
                "Impossible de créer un ticket ici.",
                ephemeral=True,
            )
            return

        lock_key = (guild.id, user.id)
        if lock_key in self.pending_ticket_creations:
            await interaction.response.send_message(
                "Ton ticket est déjà en cours de création, attends une seconde.",
                ephemeral=True,
            )
            return

        config = self.get_guild_config(guild.id)
        staff_role = guild.get_role(config["staff_role_id"]) if config["staff_role_id"] else None
        archive_role = guild.get_role(config["archive_role_id"]) if config["archive_role_id"] else None
        ticket_category = guild.get_channel(config["ticket_category_id"]) if config["ticket_category_id"] else None
        archive_category = guild.get_channel(config["archive_category_id"]) if config["archive_category_id"] else None

        if (
            staff_role is None
            or archive_role is None
            or not isinstance(ticket_category, discord.CategoryChannel)
            or not isinstance(archive_category, discord.CategoryChannel)
        ):
            await interaction.response.send_message(
                "Le système de tickets n'est pas encore configuré correctement.",
                ephemeral=True,
            )
            return

        if len(self.get_open_tickets_for_user(guild.id, user.id)) >= 3:
            await interaction.response.send_message(
                "Tu as déjà 3 tickets ouverts. Ferme-en un avant d'en créer un autre.",
                ephemeral=True,
            )
            return

        self.pending_ticket_creations.add(lock_key)
        try:
            number = self.get_next_ticket_number(guild.id)
            channel_name = f"{number}-{slugify_name(user.display_name)}"
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                user: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                    embed_links=True,
                ),
                staff_role: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_messages=True,
                ),
                archive_role: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_messages=True,
                ),
            }
            channel = await guild.create_text_channel(
                name=channel_name,
                category=ticket_category,
                overwrites=overwrites,
                reason=f"Création du ticket {ticket_type} par {user}",
            )

            store = self.get_ticket_store(guild.id)
            store["channels"][str(channel.id)] = {
                "channel_id": channel.id,
                "owner_id": user.id,
                "status": "open",
                "type": ticket_type,
                "number": number,
            }
            self.save_tickets()

            embed = discord.Embed(
                title=f"Ticket {TICKET_TYPES[ticket_type]['label']}",
                description=(
                    f"{user.mention}, ton ticket a été créé avec succès.\n"
                    "Explique ta demande avec le plus de détails possible."
                ),
                color=discord.Color.green(),
            )
            embed.add_field(name="Catégorie", value=TICKET_TYPES[ticket_type]["label"], inline=True)
            embed.add_field(name="Numéro", value=str(number), inline=True)
            await channel.send(
                content=f"{user.mention} {staff_role.mention}",
                embed=embed,
                view=TicketCloseView(self),
            )
            await self.log_event(
                guild,
                "🎫 Ticket ouvert",
                f"{user.mention} a ouvert un ticket **{TICKET_TYPES[ticket_type]['label']}**.",
                discord.Color.green(),
                thumbnail_url=user.display_avatar.url,
                fields=[
                    ("Salon", channel.mention, True),
                    ("Numéro", str(number), True),
                ],
            )
            await interaction.response.defer(ephemeral=True, thinking=False)
        finally:
            self.pending_ticket_creations.discard(lock_key)

    async def archive_ticket(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        channel = interaction.channel
        user = interaction.user
        if guild is None or channel is None or not isinstance(user, discord.Member):
            await interaction.response.send_message(
                "Impossible de fermer ce ticket.",
                ephemeral=True,
            )
            return

        store = self.get_ticket_store(guild.id)
        ticket = store["channels"].get(str(channel.id))
        if ticket is None:
            await interaction.response.send_message(
                "Ce salon n'est pas un ticket géré par le bot.",
                ephemeral=True,
            )
            return
        if ticket["status"] != "open":
            await interaction.response.send_message(
                "Ce ticket est déjà archivé.",
                ephemeral=True,
            )
            return

        config = self.get_guild_config(guild.id)
        staff_role = guild.get_role(config["staff_role_id"]) if config["staff_role_id"] else None
        archive_role = guild.get_role(config["archive_role_id"]) if config["archive_role_id"] else None
        archive_category = guild.get_channel(config["archive_category_id"]) if config["archive_category_id"] else None
        owner = guild.get_member(ticket["owner_id"])

        if archive_role is None or not isinstance(archive_category, discord.CategoryChannel):
            await interaction.response.send_message(
                "La configuration des archives est invalide.",
                ephemeral=True,
            )
            return

        is_staff = staff_role is not None and staff_role in user.roles
        is_archive_staff = archive_role in user.roles
        if not (user.id == guild.owner_id or is_staff or is_archive_staff):
            await interaction.response.send_message(
                "Seul le staff peut fermer ce ticket.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        await channel.edit(category=archive_category, reason=f"Archivage du ticket par {user}")
        await self.send_ticket_transcript(channel)

        if owner is not None:
            await channel.set_permissions(
                owner,
                overwrite=discord.PermissionOverwrite(view_channel=False),
            )
        if staff_role is not None:
            await channel.set_permissions(
                staff_role,
                overwrite=discord.PermissionOverwrite(view_channel=False),
            )
        await channel.set_permissions(
            archive_role,
            overwrite=discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
            ),
        )
        if guild.owner is not None:
            await channel.set_permissions(
                guild.owner,
                overwrite=discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_messages=True,
                ),
            )
        await channel.set_permissions(
            guild.default_role,
            overwrite=discord.PermissionOverwrite(view_channel=False),
        )

        ticket["status"] = "archived"
        ticket["closed_by"] = user.id
        self.save_tickets()

        embed = discord.Embed(
            title="Ticket archivé",
            description=(
                f"Ce ticket a été archivé par {user.mention}.\n"
                "Seul le staff supérieur peut maintenant consulter cette archive."
            ),
            color=discord.Color.orange(),
        )
        await channel.send(embed=embed, view=TicketArchiveView(self))
        await self.log_event(
            guild,
            "📁 Ticket fermé",
            f"Le ticket **{channel.name}** a été archivé par {user.mention}.",
            discord.Color.orange(),
            thumbnail_url=user.display_avatar.url,
            fields=[("Salon", channel.name, True)],
        )
        await interaction.followup.send("Le ticket a été archivé.", ephemeral=True)

    async def reopen_ticket(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        channel = interaction.channel
        user = interaction.user
        if guild is None or channel is None or not isinstance(user, discord.Member):
            await interaction.response.send_message(
                "Impossible de réouvrir ce ticket.",
                ephemeral=True,
            )
            return

        store = self.get_ticket_store(guild.id)
        ticket = store["channels"].get(str(channel.id))
        if ticket is None:
            await interaction.response.send_message(
                "Ce salon n'est pas un ticket géré par le bot.",
                ephemeral=True,
            )
            return
        if ticket["status"] != "archived":
            await interaction.response.send_message(
                "Ce ticket n'est pas archivé.",
                ephemeral=True,
            )
            return

        config = self.get_guild_config(guild.id)
        staff_role = guild.get_role(config["staff_role_id"]) if config["staff_role_id"] else None
        archive_role = guild.get_role(config["archive_role_id"]) if config["archive_role_id"] else None
        ticket_category = guild.get_channel(config["ticket_category_id"]) if config["ticket_category_id"] else None
        owner = guild.get_member(ticket["owner_id"])

        if (
            staff_role is None
            or archive_role is None
            or not isinstance(ticket_category, discord.CategoryChannel)
        ):
            await interaction.response.send_message(
                "La configuration des tickets est invalide.",
                ephemeral=True,
            )
            return
        if not (user.id == guild.owner_id or archive_role in user.roles):
            await interaction.response.send_message(
                "Seul le staff supérieur peut réouvrir ce ticket.",
                ephemeral=True,
            )
            return
        if owner is None:
            await interaction.response.send_message(
                "Le créateur du ticket n'est plus sur le serveur.",
                ephemeral=True,
            )
            return
        if len(self.get_open_tickets_for_user(guild.id, owner.id)) >= 3:
            await interaction.response.send_message(
                "Impossible de réouvrir ce ticket car l'utilisateur a déjà 3 tickets ouverts.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        await channel.edit(category=ticket_category, reason=f"Réouverture du ticket par {user}")
        await channel.set_permissions(
            owner,
            overwrite=discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            ),
        )
        await channel.set_permissions(
            staff_role,
            overwrite=discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
            ),
        )
        await channel.set_permissions(
            archive_role,
            overwrite=discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
            ),
        )
        if guild.owner is not None:
            await channel.set_permissions(
                guild.owner,
                overwrite=discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_messages=True,
                ),
            )
        await channel.set_permissions(
            guild.default_role,
            overwrite=discord.PermissionOverwrite(view_channel=False),
        )

        ticket["status"] = "open"
        ticket["reopened_by"] = user.id
        self.save_tickets()

        embed = discord.Embed(
            title="Ticket réouvert",
            description=f"Ce ticket a été réouvert par {user.mention}.",
            color=discord.Color.green(),
        )
        await channel.send(embed=embed, view=TicketCloseView(self))
        await self.log_event(
            guild,
            "📂 Ticket réouvert",
            f"Le ticket **{channel.name}** a été réouvert par {user.mention}.",
            discord.Color.green(),
            thumbnail_url=user.display_avatar.url,
        )
        await interaction.followup.send("Le ticket a été réouvert.", ephemeral=True)

    async def join_giveaway(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.message is None:
            await interaction.response.send_message(
                "Impossible de participer ici.",
                ephemeral=True,
            )
            return

        store = self.get_giveaway_store(interaction.guild.id)
        giveaway = store.get(str(interaction.message.id))
        if giveaway is None or giveaway.get("status") != "active":
            await interaction.response.send_message(
                "Ce giveaway n'est plus actif.",
                ephemeral=True,
            )
            return

        user_id = interaction.user.id
        participants = giveaway.setdefault("participants", [])
        if user_id in participants:
            await interaction.response.send_message(
                "Tu participes déjà à ce giveaway.",
                ephemeral=True,
            )
            return

        participants.append(user_id)
        self.save_giveaways()
        await interaction.response.send_message(
            "Participation enregistrée.",
            ephemeral=True,
        )
        try:
            await interaction.user.send(f"Tu participes au giveaway : {giveaway['prize']}")
        except discord.Forbidden:
            pass

    async def show_giveaway_chances(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Impossible d'afficher tes chances ici.", ephemeral=True)
            return
        weight = get_member_giveaway_weight(interaction.user)
        bonus_roles = [role.name for role in interaction.user.roles if role.name in INVITE_ROLE_WEIGHTS]
        best_role = max(bonus_roles, key=lambda role_name: INVITE_ROLE_WEIGHTS[role_name]) if bonus_roles else None
        parts = [f"Chance totale : **x{weight:g}**"]
        if best_role is not None:
            parts.append(f"Rôle invitations pris en compte : **{best_role}**")
        if interaction.user.premium_since is not None or discord.utils.get(interaction.user.roles, name="Server Booster"):
            parts.append("Bonus Server Booster : **+1**")
        await interaction.response.send_message("\n".join(parts), ephemeral=True)

    async def show_giveaway_remaining_time(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.message is None:
            await interaction.response.send_message("Impossible d'afficher le temps restant ici.", ephemeral=True)
            return
        giveaway = self.get_giveaway_store(interaction.guild.id).get(str(interaction.message.id))
        if giveaway is None:
            await interaction.response.send_message("Aucun giveaway trouvé pour ce message.", ephemeral=True)
            return
        remaining = self.format_remaining_duration(int(giveaway["end_at"]))
        await interaction.response.send_message(
            f"Temps restant pour **{giveaway['prize']}** : **{remaining}**",
            ephemeral=True,
        )

    async def show_giveaway_participants(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.message is None:
            await interaction.response.send_message(
                "Impossible d'afficher les participants ici.",
                ephemeral=True,
            )
            return

        giveaway = self.get_giveaway_store(interaction.guild.id).get(str(interaction.message.id))
        if giveaway is None:
            await interaction.response.send_message(
                "Aucun giveaway trouvé pour ce message.",
                ephemeral=True,
            )
            return

        participant_ids = list(dict.fromkeys(giveaway.get("participants", [])))
        if not participant_ids:
            await interaction.response.send_message(
                f"Aucun participant pour **{giveaway['prize']}** pour le moment.",
                ephemeral=True,
            )
            return

        lines: list[str] = []
        for user_id in participant_ids:
            member = interaction.guild.get_member(user_id)
            if member is None:
                try:
                    member = await interaction.guild.fetch_member(user_id)
                except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                    member = None

            if member is not None:
                lines.append(f"• {member.display_name}")
            else:
                lines.append(f"• {user_id}")

        chunks: list[str] = []
        current = ""
        for line in lines:
            candidate = line if not current else f"{current}\n{line}"
            if len(candidate) <= 3500:
                current = candidate
            else:
                chunks.append(current)
                current = line
        if current:
            chunks.append(current)

        embed = discord.Embed(
            title=f"Participants • {giveaway['prize']}",
            description=f"Participants : **{len(participant_ids)}**",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Liste", value=chunks[0], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        for extra_chunk in chunks[1:]:
            extra_embed = discord.Embed(
                title=f"Participants • {giveaway['prize']} (suite)",
                color=discord.Color.gold(),
            )
            extra_embed.add_field(name="Liste", value=extra_chunk, inline=False)
            await interaction.followup.send(embed=extra_embed, ephemeral=True)

    async def _pick_weighted_winners(
        self,
        guild: discord.Guild,
        participant_ids: list[int],
        winners_count: int,
        excluded: set[int] | None = None,
    ) -> list[int]:
        pool: list[tuple[int, float]] = []
        excluded = excluded or set()

        for user_id in participant_ids:
            if user_id in excluded:
                continue
            member = guild.get_member(user_id)
            if member is None:
                try:
                    member = await guild.fetch_member(user_id)
                except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                    member = None
            if member is None:
                continue
            pool.append((user_id, get_member_giveaway_weight(member)))

        winners: list[int] = []
        for _ in range(min(winners_count, len(pool))):
            total_weight = sum(weight for _, weight in pool)
            if total_weight <= 0:
                break
            pick = random.uniform(0, total_weight)
            running = 0.0
            chosen_index = 0
            for index, (_, weight) in enumerate(pool):
                running += weight
                if pick <= running:
                    chosen_index = index
                    break
            winner_id, _ = pool.pop(chosen_index)
            winners.append(winner_id)
        return winners

    async def finish_giveaway(self, guild_id: int, message_id: int) -> None:
        store = self.get_giveaway_store(guild_id)
        giveaway = store.get(str(message_id))
        if giveaway is None or giveaway.get("status") != "active":
            return

        guild = self.get_guild(guild_id)
        if guild is None:
            return
        channel = guild.get_channel(giveaway["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            return

        participant_ids = list(dict.fromkeys(giveaway.get("participants", [])))
        winners = await self._pick_weighted_winners(
            guild,
            participant_ids,
            int(giveaway["winners_count"]),
        )

        giveaway["status"] = "ended"
        giveaway["winners"] = winners
        self.save_giveaways()
        self.cancel_giveaway_task(guild_id, message_id)

        if winners:
            winner_names: list[str] = []
            for winner_id in winners:
                member = guild.get_member(winner_id)
                winner_names.append(member.display_name if member is not None else str(winner_id))
            names_text = ", ".join(winner_names)
            await channel.send(
                f"🎉 Giveaway terminé ! Gagnant(s) pour **{giveaway['prize']}** : {names_text}"
            )
        else:
            await channel.send(
                f"🎉 Giveaway terminé pour **{giveaway['prize']}**, "
                "mais aucun participant valide n'a été trouvé."
            )

    async def reroll_giveaway(self, guild_id: int, message_id: int) -> list[int]:
        store = self.get_giveaway_store(guild_id)
        giveaway = store.get(str(message_id))
        if giveaway is None:
            return []

        guild = self.get_guild(guild_id)
        if guild is None:
            return []

        participant_ids = list(dict.fromkeys(giveaway.get("participants", [])))
        previous_winners = set(giveaway.get("winners", []))
        winners = await self._pick_weighted_winners(
            guild,
            participant_ids,
            int(giveaway["winners_count"]),
            excluded=previous_winners,
        )
        giveaway["winners"] = winners
        self.save_giveaways()
        return winners

    async def sync_guild_commands(self, guild: discord.Guild) -> None:
        await self.ensure_ticket_config(guild)
        await self.cache_invites(guild)
        self.tree.clear_commands(guild=guild)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        print(f"{len(synced)} commande(s) slash synchronisées sur {guild.name}.")
        self.synced_guild_ids.add(guild.id)

    async def sync_commands_once(self, force: bool = False) -> None:
        if force:
            self.synced_guild_ids.clear()
            self.sync_done = False

        pending_guilds = [guild for guild in self.guilds if guild.id not in self.synced_guild_ids]
        for guild in pending_guilds:
            await self.sync_guild_commands(guild)

        if not self.sync_done:
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            await self.schedule_existing_giveaways()
            self.sync_done = True


def create_bot() -> YishiBot:
    return YishiBot()
