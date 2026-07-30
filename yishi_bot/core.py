from __future__ import annotations

import asyncio
import contextlib
import io
import random
import tempfile
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from yishi_bot.storage import (
    CONFIG_FILE,
    GACHA_FILE,
    GIVEAWAYS_FILE,
    INVITES_FILE,
    LEVELS_FILE,
    PROMOS_FILE,
    SALES_FILE,
    TICKETS_FILE,
    WARNINGS_FILE,
    load_json,
    save_json,
)
from yishi_bot.ticketing import TICKET_TYPES, build_custom_ticket_panel_embed, build_ticket_panel_embed, slugify_name
from yishi_bot.cogs.configuration import ConfigurationCog
from yishi_bot.cogs.events import EventsCog
from yishi_bot.cogs.gacha import GachaCog
from yishi_bot.cogs.general import GeneralCog
from yishi_bot.cogs.giveaways import GiveawaysCog
from yishi_bot.cogs.moderation import ModerationCog
from yishi_bot.cogs.promotions import PromotionsCog
from yishi_bot.cogs.progression import ProgressionCog
from yishi_bot.cogs.sales import SalesCog
from yishi_bot.cogs.tickets import TicketsCog
from yishi_bot.constants import *
from yishi_bot.helpers import (
    can_moderate,
    default_config,
    default_gacha_store,
    default_level_store,
    default_promo_store,
    get_best_invite_role_name,
    get_member_giveaway_weight,
    merge_missing_defaults,
    parse_duration,
    split_long_message,
)
from yishi_bot.views import GiveawayView, SaleApprovalView, SaleListingView, TicketArchiveView, TicketCloseView, TicketPanelView

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
        self.sale_data = load_json(SALES_FILE, {})
        self.promo_data = load_json(PROMOS_FILE, {})
        self.level_data = load_json(LEVELS_FILE, default_level_store())
        if self._migrate_invite_data():
            self.save_invites()
        if merge_missing_defaults(self.gacha_data, default_gacha_store()):
            self.save_gacha()
        if merge_missing_defaults(self.level_data, default_level_store()):
            self.save_levels()

        self.invite_cache: dict[int, dict[str, int]] = {}
        self.giveaway_tasks: dict[str, asyncio.Task] = {}
        self.pending_ticket_creations: set[tuple[int, int]] = set()
        self.pending_gacha_spins: set[tuple[int, int]] = set()
        self.message_xp_cooldowns: dict[tuple[int, int], datetime] = {}
        self.background_task: asyncio.Task | None = None
        self.paris_tz = ZoneInfo("Europe/Paris")
        self.sync_done = False
        self.synced_guild_ids: set[int] = set()
        self.tree.on_error = self.on_app_command_error

    async def setup_hook(self) -> None:
        self.add_view(TicketPanelView(self))
        self.add_view(TicketCloseView(self))
        self.add_view(TicketArchiveView(self))
        self.add_view(GiveawayView(self))
        self.add_view(SaleListingView(self))
        self.add_view(SaleApprovalView(self))

        await self.add_cog(EventsCog(self))
        await self.add_cog(GeneralCog(self))
        await self.add_cog(GachaCog(self))
        await self.add_cog(ModerationCog(self))
        await self.add_cog(PromotionsCog(self))
        await self.add_cog(ProgressionCog(self))
        await self.add_cog(SalesCog(self))
        await self.add_cog(TicketsCog(self))
        await self.add_cog(GiveawaysCog(self))
        await self.add_cog(ConfigurationCog(self))
        if self.background_task is None:
            self.background_task = asyncio.create_task(self.run_background_jobs())

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        original_error = getattr(error, "original", error)
        command_name = interaction.command.qualified_name if interaction.command is not None else "inconnue"

        if isinstance(error, app_commands.CommandNotFound):
            message = (
                "Cette commande n'existe plus ou n'est pas encore synchronisée. "
                "Réessaie dans quelques instants."
            )
        else:
            message = (
                "La commande a rencontré une erreur interne. "
                "Le problème a été journalisé."
            )

        if interaction.guild is not None:
            details = "".join(
                traceback.format_exception(
                    type(original_error),
                    original_error,
                    original_error.__traceback__,
                )
            )[:3500]
            await self.log_event(
                interaction.guild,
                "Erreur slash command",
                f"Une erreur est survenue sur `/{command_name}`.",
                discord.Color.red(),
                thumbnail_url=interaction.user.display_avatar.url if interaction.user else None,
                fields=[
                    ("Utilisateur", getattr(interaction.user, "mention", "Inconnu"), True),
                    ("Salon", getattr(interaction.channel, "mention", "Inconnu"), True),
                    ("Détail", f"```py\n{details}\n```", False),
                ],
            )

        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass

    async def close(self) -> None:
        if self.background_task is not None:
            self.background_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.background_task
            self.background_task = None
        await super().close()

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
            self.ticket_data[key] = {
                "channels": {},
                "staff_points": {},
                "panel_message_id": None,
            }
            self.save_tickets()
        else:
            store = self.ticket_data[key]
            changed = False
            if "channels" not in store or not isinstance(store["channels"], dict):
                store["channels"] = {}
                changed = True
            if "staff_points" not in store or not isinstance(store["staff_points"], dict):
                store["staff_points"] = {}
                changed = True
            if "panel_message_id" not in store:
                store["panel_message_id"] = None
                changed = True
            for ticket in store["channels"].values():
                if "assigned_helper_id" not in ticket:
                    ticket["assigned_helper_id"] = None
                    changed = True
                if "claimed_at" not in ticket:
                    ticket["claimed_at"] = None
                    changed = True
                if "destination" not in ticket:
                    ticket["destination"] = "helper"
                    changed = True
                if "transferred_by" not in ticket:
                    ticket["transferred_by"] = None
                    changed = True
                if "transfer_reason" not in ticket:
                    ticket["transfer_reason"] = None
                    changed = True
                if "transfer_summary" not in ticket:
                    ticket["transfer_summary"] = None
                    changed = True
                if "claimed_messages" not in ticket:
                    ticket["claimed_messages"] = 0
                    changed = True
            if changed:
                self.save_tickets()
        return self.ticket_data[key]

    def get_level_store(self, guild_id: int) -> dict[str, Any]:
        key = str(guild_id)
        if key not in self.level_data:
            self.level_data[key] = {
                "members": {},
                "voice_sessions": {},
                "temp_channels": {},
            }
            self.save_levels()
        elif merge_missing_defaults(self.level_data[key], default_level_store()):
            self.save_levels()
        return self.level_data[key]

    def get_warning_store(self, guild_id: int) -> dict[str, Any]:
        key = str(guild_id)
        if key not in self.warning_data:
            self.warning_data[key] = {}
            self.save_warnings()
        return self.warning_data[key]

    def default_invite_store(self) -> dict[str, Any]:
        return {
            "counts": {},
            "weekly_counts": {},
            "invite_snapshot": {},
            "member_inviter_ids": {},
            "role_baseline_counts": {},
            "role_baseline_initialized_at": None,
            "last_weekly_reset_key": None,
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
                    "weekly_counts": {},
                    "invite_snapshot": {},
                    "member_inviter_ids": {},
                }
                changed = True
                continue

            defaults = self.default_invite_store()
            for key, default_value in defaults.items():
                if key not in value or not isinstance(value[key], dict):
                    value[key] = default_value.copy() if isinstance(default_value, dict) else default_value
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

            normalized_role_baselines: dict[str, int] = {}
            for user_id, count in value.get("role_baseline_counts", {}).items():
                try:
                    normalized_role_baselines[str(user_id)] = int(count)
                except (TypeError, ValueError):
                    changed = True
            if normalized_role_baselines != value.get("role_baseline_counts", {}):
                value["role_baseline_counts"] = normalized_role_baselines
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
            self.giveaway_data[key] = {"giveaways": {}, "blacklist": {}}
            self.save_giveaways()
        store = self.giveaway_data[key]
        if "giveaways" not in store or not isinstance(store["giveaways"], dict):
            legacy_giveaways = {
                k: v
                for k, v in list(store.items())
                if isinstance(v, dict) and str(v.get("message_id", "")).isdigit()
            }
            store.clear()
            store["giveaways"] = legacy_giveaways
            store["blacklist"] = {}
            self.save_giveaways()
        if "blacklist" not in store or not isinstance(store["blacklist"], dict):
            store["blacklist"] = {}
            self.save_giveaways()
        return store

    def get_giveaway_entries(self, guild_id: int) -> dict[str, Any]:
        return self.get_giveaway_store(guild_id)["giveaways"]

    def get_giveaway_blacklist(self, guild_id: int) -> dict[str, Any]:
        return self.get_giveaway_store(guild_id)["blacklist"]

    def get_sale_store(self, guild_id: int) -> dict[str, Any]:
        key = str(guild_id)
        if key not in self.sale_data:
            self.sale_data[key] = {"messages": {}, "channels": {}, "reviews": {}}
            self.save_sales()
        else:
            store = self.sale_data[key]
            changed = False
            for field in ("messages", "channels", "reviews"):
                if field not in store or not isinstance(store[field], dict):
                    store[field] = {}
                    changed = True
            for channel_id, value in list(store["channels"].items()):
                if isinstance(value, str):
                    store["channels"][channel_id] = {
                        "message_id": value,
                        "last_activity_at": None,
                        "recall_sent_at": None,
                    }
                    changed = True
            if changed:
                self.save_sales()
        return self.sale_data[key]

    def get_promo_store(self, guild_id: int) -> dict[str, Any]:
        key = str(guild_id)
        if key not in self.promo_data:
            self.promo_data[key] = default_promo_store()
            self.save_promos()
        else:
            store = self.promo_data[key]
            if merge_missing_defaults(store, default_promo_store()):
                self.save_promos()
        return self.promo_data[key]

    def save_config(self) -> None:
        save_json(CONFIG_FILE, self.config_data)

    def save_tickets(self) -> None:
        save_json(TICKETS_FILE, self.ticket_data)

    def save_levels(self) -> None:
        save_json(LEVELS_FILE, self.level_data)

    def save_warnings(self) -> None:
        save_json(WARNINGS_FILE, self.warning_data)

    def save_invites(self) -> None:
        save_json(INVITES_FILE, self.invite_data)

    def save_giveaways(self) -> None:
        save_json(GIVEAWAYS_FILE, self.giveaway_data)

    def save_gacha(self) -> None:
        save_json(GACHA_FILE, self.gacha_data)

    def save_sales(self) -> None:
        save_json(SALES_FILE, self.sale_data)

    def save_promos(self) -> None:
        save_json(PROMOS_FILE, self.promo_data)

    def get_invite_count(self, guild_id: int, user_id: int) -> int:
        counts = self.get_invite_store(guild_id)["counts"]
        return int(counts.get(str(user_id), 0))

    def get_weekly_invite_count(self, guild_id: int, user_id: int) -> int:
        counts = self.get_invite_store(guild_id)["weekly_counts"]
        return int(counts.get(str(user_id), 0))

    def get_invite_role_count_from_now(self, guild_id: int, user_id: int) -> int:
        store = self.get_invite_store(guild_id)
        key = str(user_id)
        total_count = int(store["counts"].get(key, 0))
        baseline_count = int(store.get("role_baseline_counts", {}).get(key, 0))
        return max(0, total_count - baseline_count)

    def initialize_invite_role_baseline(self, guild_id: int) -> bool:
        store = self.get_invite_store(guild_id)
        if store.get("role_baseline_initialized_at"):
            return False

        counts = store.setdefault("counts", {})
        baselines = store.setdefault("role_baseline_counts", {})
        for user_id, count in counts.items():
            baselines[str(user_id)] = int(count)
        store["role_baseline_initialized_at"] = self.iso_now()
        self.save_invites()
        return True

    def get_member_inviter_id(self, guild_id: int, member_id: int) -> int | None:
        inviter_id = self.get_invite_store(guild_id)["member_inviter_ids"].get(str(member_id))
        return int(inviter_id) if inviter_id is not None else None

    def is_helper_member(self, member: discord.Member) -> bool:
        helper_names = {
            HELPER_ROLE_NAME,
            TRIAL_MOD_ROLE_NAME,
            MODERATOR_ROLE_NAME,
            RESPONSABLE_ROLE_NAME,
            ADMIN_ROLE_NAME,
            FOUNDER_ROLE_NAME,
            AUTO_STAFF_ROLE_NAME,
            AUTO_ARCHIVE_ROLE_NAME,
        }
        return any(role.name in helper_names for role in member.roles) or member.guild.owner_id == member.id

    def can_close_tickets(self, member: discord.Member) -> bool:
        close_role_names = {
            MODERATOR_ROLE_NAME,
            RESPONSABLE_ROLE_NAME,
            ADMIN_ROLE_NAME,
            FOUNDER_ROLE_NAME,
            AUTO_STAFF_ROLE_NAME,
            AUTO_ARCHIVE_ROLE_NAME,
        }
        return any(role.name in close_role_names for role in member.roles) or member.guild.owner_id == member.id

    def get_staff_point_total(self, guild_id: int, user_id: int) -> int:
        store = self.get_ticket_store(guild_id)["staff_points"]
        return int(store.get(str(user_id), 0))

    def add_staff_points(self, guild_id: int, user_id: int, amount: int) -> int:
        store = self.get_ticket_store(guild_id)["staff_points"]
        key = str(user_id)
        store[key] = int(store.get(key, 0)) + amount
        self.save_tickets()
        return int(store[key])

    def get_member_level_entry(self, guild_id: int, user_id: int) -> dict[str, Any]:
        members = self.get_level_store(guild_id)["members"]
        key = str(user_id)
        if key not in members:
            members[key] = {
                "xp": 0,
                "message_count": 0,
                "voice_seconds": 0,
                "last_message_xp_at": None,
            }
            self.save_levels()
        return members[key]

    def xp_for_level(self, level: int) -> int:
        if level <= 0:
            return 0
        return 100 * level * level

    def get_level_from_xp(self, xp: int) -> int:
        level = 0
        while xp >= self.xp_for_level(level + 1):
            level += 1
        return level

    def get_member_grade(self, level: int) -> str:
        grade = "Novice"
        for name, required_level in XP_GRADE_LEVELS.items():
            if level >= required_level:
                grade = name
        return grade

    def get_member_level_stats(self, guild_id: int, user_id: int) -> dict[str, Any]:
        entry = self.get_member_level_entry(guild_id, user_id)
        total_xp = int(entry.get("xp", 0))
        level = self.get_level_from_xp(total_xp)
        current_level_floor = self.xp_for_level(level)
        next_level_total = self.xp_for_level(level + 1)
        current_xp = total_xp - current_level_floor
        needed_xp = max(1, next_level_total - current_level_floor)
        return {
            "xp": total_xp,
            "level": level,
            "grade": self.get_member_grade(level),
            "current_xp": current_xp,
            "needed_xp": needed_xp,
            "message_count": int(entry.get("message_count", 0)),
            "voice_seconds": int(entry.get("voice_seconds", 0)),
        }

    async def sync_member_xp_role(self, member: discord.Member) -> None:
        stats = self.get_member_level_stats(member.guild.id, member.id)
        grade = stats["grade"]
        role_name = XP_ROLE_BY_GRADE[grade]
        role_to_add = discord.utils.get(member.guild.roles, name=role_name)
        if role_to_add is None:
            return
        xp_roles = [role for role in member.guild.roles if role.name in XP_ROLE_NAMES]
        roles_to_remove = [role for role in member.roles if role in xp_roles and role != role_to_add]
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason="Mise à jour du grade XP")
        if role_to_add not in member.roles:
            await member.add_roles(role_to_add, reason="Mise à jour du grade XP")

    async def sync_all_xp_roles(self, guild: discord.Guild) -> None:
        for member in guild.members:
            if member.bot:
                continue
            await self.sync_member_xp_role(member)

    async def add_member_xp(self, member: discord.Member, amount: int, *, count_message: bool = False, voice_seconds: int = 0) -> None:
        entry = self.get_member_level_entry(member.guild.id, member.id)
        before_level = self.get_level_from_xp(int(entry.get("xp", 0)))
        entry["xp"] = int(entry.get("xp", 0)) + amount
        if count_message:
            entry["message_count"] = int(entry.get("message_count", 0)) + 1
        if voice_seconds:
            entry["voice_seconds"] = int(entry.get("voice_seconds", 0)) + voice_seconds
        self.save_levels()
        after_level = self.get_level_from_xp(int(entry.get("xp", 0)))
        await self.sync_member_xp_role(member)
        if after_level > before_level:
            await self.log_event(
                member.guild,
                "Niveau gagné",
                f"{member.mention} est passé niveau **{after_level}**.",
                discord.Color.blurple(),
                thumbnail_url=member.display_avatar.url,
            )

    async def set_member_level(self, member: discord.Member, level: int) -> dict[str, Any]:
        target_level = max(0, int(level))
        entry = self.get_member_level_entry(member.guild.id, member.id)
        before_stats = self.get_member_level_stats(member.guild.id, member.id)
        entry["xp"] = self.xp_for_level(target_level)
        self.save_levels()
        await self.sync_member_xp_role(member)
        after_stats = self.get_member_level_stats(member.guild.id, member.id)
        return {
            "before_level": before_stats["level"],
            "after_level": after_stats["level"],
            "before_grade": before_stats["grade"],
            "after_grade": after_stats["grade"],
            "xp": after_stats["xp"],
        }

    async def award_message_xp(self, message: discord.Message) -> None:
        if message.guild is None or not isinstance(message.author, discord.Member):
            return
        if len(message.content.strip()) < 4:
            return
        key = (message.guild.id, message.author.id)
        now = self.utcnow()
        last_award = self.message_xp_cooldowns.get(key)
        if last_award is not None and now - last_award < timedelta(seconds=60):
            return
        self.message_xp_cooldowns[key] = now
        await self.add_member_xp(message.author, 20, count_message=True)

    def get_level_ranking(self, guild_id: int) -> list[tuple[int, int]]:
        members = self.get_level_store(guild_id)["members"]
        ranking = []
        for member_id, entry in members.items():
            ranking.append((int(member_id), int(entry.get("xp", 0))))
        ranking.sort(key=lambda item: item[1], reverse=True)
        return ranking

    def get_member_rank_position(self, guild_id: int, user_id: int) -> int:
        ranking = self.get_level_ranking(guild_id)
        for index, (member_id, _) in enumerate(ranking, start=1):
            if member_id == user_id:
                return index
        return max(1, len(ranking))

    def get_temp_voice_store(self, guild_id: int) -> dict[str, Any]:
        return self.get_level_store(guild_id)["temp_channels"]

    def get_temp_voice_entry(self, guild_id: int, channel_id: int) -> dict[str, Any] | None:
        return self.get_temp_voice_store(guild_id).get(str(channel_id))

    def can_manage_voice_feature(self, member: discord.Member, feature: str) -> bool:
        level = self.get_member_level_stats(member.guild.id, member.id)["level"]
        requirements = {
            "lock": XP_GRADE_LEVELS["Actif"],
            "unlock": XP_GRADE_LEVELS["Actif"],
            "limit": XP_GRADE_LEVELS["Actif"],
            "invite": XP_GRADE_LEVELS["Confirme"],
            "kick": XP_GRADE_LEVELS["Confirme"],
            "rename": XP_GRADE_LEVELS["Elite"],
            "transfer": XP_GRADE_LEVELS["Legende"],
            "stream": XP_GRADE_LEVELS["Actif"],
            "camera": XP_GRADE_LEVELS["Confirme"],
        }
        return level >= requirements.get(feature, 999)

    async def handle_voice_state_change(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        config = self.get_guild_config(member.guild.id)
        creator_channel_id = config.get("voice_creator_channel_id")

        if before.channel is not None:
            entry = self.get_temp_voice_entry(member.guild.id, before.channel.id)
            if entry is not None:
                entry.get("join_order", {}).pop(str(member.id), None)
                if len(before.channel.members) == 0:
                    self.get_temp_voice_store(member.guild.id).pop(str(before.channel.id), None)
                    self.save_levels()
                    with contextlib.suppress(discord.HTTPException):
                        await before.channel.delete(reason="Salon vocal temporaire vide")
                else:
                    current_owner_id = int(entry.get("owner_id", 0))
                    if current_owner_id == member.id:
                        new_owner = min(
                            before.channel.members,
                            key=lambda m: self.parse_iso_datetime(entry.get("join_order", {}).get(str(m.id))) or self.utcnow(),
                        )
                        entry["owner_id"] = new_owner.id
                        self.save_levels()
                        await self.update_temp_voice_owner_permissions(before.channel, new_owner)

        if after.channel is not None and creator_channel_id and after.channel.id == creator_channel_id:
            category = after.channel.category
            new_channel = await member.guild.create_voice_channel(
                name=f"🔊・Vocal de {member.display_name}",
                category=category,
                reason=f"Salon vocal temporaire pour {member}",
            )
            await member.move_to(new_channel)
            self.get_temp_voice_store(member.guild.id)[str(new_channel.id)] = {
                "owner_id": member.id,
                "join_order": {str(member.id): self.iso_now()},
                "locked": False,
            }
            self.save_levels()
            await self.update_temp_voice_owner_permissions(new_channel, member)
            with contextlib.suppress(discord.HTTPException):
                await new_channel.send(embed=self.build_temp_voice_commands_embed(member))
            return

        if after.channel is not None:
            entry = self.get_temp_voice_entry(member.guild.id, after.channel.id)
            if entry is not None:
                entry.setdefault("join_order", {})[str(member.id)] = self.iso_now()
                self.save_levels()

    async def update_temp_voice_owner_permissions(self, channel: discord.VoiceChannel, owner: discord.Member) -> None:
        allow_stream = self.can_manage_voice_feature(owner, "stream")
        await channel.set_permissions(
            owner,
            view_channel=True,
            connect=True,
            speak=True,
            stream=allow_stream,
            use_voice_activation=True,
            priority_speaker=False,
        )

    async def process_voice_xp(self) -> None:
        for guild in self.guilds:
            for channel in guild.voice_channels:
                eligible_members = [
                    member
                    for member in channel.members
                    if not member.bot and not (member.voice.self_deaf or member.voice.self_mute)
                ]
                if len(eligible_members) < 2:
                    continue
                for member in eligible_members:
                    await self.add_member_xp(member, 5, voice_seconds=60)

    def get_owned_temp_voice_channel(self, member: discord.Member) -> discord.VoiceChannel | None:
        voice = member.voice
        if voice is None or not isinstance(voice.channel, discord.VoiceChannel):
            return None
        entry = self.get_temp_voice_entry(member.guild.id, voice.channel.id)
        if entry is None or int(entry.get("owner_id", 0)) != member.id:
            return None
        return voice.channel

    async def lock_temp_voice(self, member: discord.Member) -> str:
        channel = self.get_owned_temp_voice_channel(member)
        if channel is None:
            return "Tu dois être propriétaire d'un vocal temporaire pour faire ça."
        await channel.set_permissions(member.guild.default_role, connect=False, view_channel=True)
        entry = self.get_temp_voice_entry(member.guild.id, channel.id)
        if entry is not None:
            entry["locked"] = True
            self.save_levels()
        return "Vocal verrouillé."

    async def unlock_temp_voice(self, member: discord.Member) -> str:
        channel = self.get_owned_temp_voice_channel(member)
        if channel is None:
            return "Tu dois être propriétaire d'un vocal temporaire pour faire ça."
        await channel.set_permissions(member.guild.default_role, connect=True, view_channel=True)
        entry = self.get_temp_voice_entry(member.guild.id, channel.id)
        if entry is not None:
            entry["locked"] = False
            self.save_levels()
        return "Vocal déverrouillé."

    async def set_temp_voice_limit(self, member: discord.Member, limit: int) -> str:
        channel = self.get_owned_temp_voice_channel(member)
        if channel is None:
            return "Tu dois être propriétaire d'un vocal temporaire pour faire ça."
        await channel.edit(user_limit=limit)
        return f"Limite du vocal définie à {limit}."

    async def rename_temp_voice(self, member: discord.Member, name: str) -> str:
        channel = self.get_owned_temp_voice_channel(member)
        if channel is None:
            return "Tu dois être propriétaire d'un vocal temporaire pour faire ça."
        await channel.edit(name=name[:100])
        return "Nom du vocal mis à jour."

    async def invite_to_temp_voice(self, member: discord.Member, target: discord.Member) -> str:
        channel = self.get_owned_temp_voice_channel(member)
        if channel is None:
            return "Tu dois être propriétaire d'un vocal temporaire pour faire ça."
        await channel.set_permissions(target, connect=True, view_channel=True)
        return f"{target.mention} peut rejoindre ton vocal."

    async def kick_from_temp_voice(self, member: discord.Member, target: discord.Member) -> str:
        channel = self.get_owned_temp_voice_channel(member)
        if channel is None:
            return "Tu dois être propriétaire d'un vocal temporaire pour faire ça."
        if target.voice is None or target.voice.channel != channel:
            return "Ce membre n'est pas dans ton vocal."
        await target.move_to(None)
        await channel.set_permissions(target, connect=False)
        return f"{target.mention} a été expulsé du vocal."

    async def transfer_temp_voice(self, member: discord.Member, target: discord.Member) -> str:
        channel = self.get_owned_temp_voice_channel(member)
        if channel is None:
            return "Tu dois être propriétaire d'un vocal temporaire pour faire ça."
        if target.voice is None or target.voice.channel != channel:
            return "Ce membre doit être dans ton vocal."
        entry = self.get_temp_voice_entry(member.guild.id, channel.id)
        if entry is None:
            return "Ce vocal n'est pas géré par le bot."
        entry["owner_id"] = target.id
        self.save_levels()
        await self.update_temp_voice_owner_permissions(channel, target)
        return f"{target.mention} est maintenant propriétaire du vocal."

    def format_voice_duration(self, seconds: int) -> str:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours} h {minutes:02d} min"

    def get_level_theme(self, grade: str) -> dict[str, tuple[int, int, int] | str]:
        themes = {
            "Novice": {"accent": (220, 220, 220), "bg": (18, 24, 35)},
            "Actif": {"accent": (52, 152, 255), "bg": (12, 25, 48)},
            "Confirme": {"accent": (63, 217, 157), "bg": (8, 36, 30)},
            "Elite": {"accent": (174, 82, 255), "bg": (24, 12, 44)},
            "Legende": {"accent": (255, 198, 64), "bg": (28, 18, 45)},
        }
        return themes.get(grade, themes["Novice"])

    def build_temp_voice_commands_embed(self, member: discord.Member) -> discord.Embed:
        stats = self.get_member_level_stats(member.guild.id, member.id)

        def command_line(command: str, required_level: int, unlocked: bool) -> str:
            status = "✅" if unlocked else "🔒"
            suffix = "" if unlocked else f" • niveau {required_level}+"
            return f"{status} `{command}`{suffix}"

        embed = discord.Embed(
            title="🔊 Commandes du vocal temporaire",
            description=(
                f"Bienvenue {member.mention}, ton vocal privé vient d'être créé.\n"
                f"Tu es actuellement **niveau {stats['level']}** • **{stats['grade']}**."
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Gestion du vocal",
            value="\n".join(
                [
                    command_line("/voc_lock", XP_GRADE_LEVELS["Actif"], self.can_manage_voice_feature(member, "lock")),
                    command_line("/voc_unlock", XP_GRADE_LEVELS["Actif"], self.can_manage_voice_feature(member, "unlock")),
                    command_line("/voc_limit", XP_GRADE_LEVELS["Actif"], self.can_manage_voice_feature(member, "limit")),
                    command_line("/voc_rename", XP_GRADE_LEVELS["Elite"], self.can_manage_voice_feature(member, "rename")),
                ]
            ),
            inline=False,
        )
        embed.add_field(
            name="Gestion des membres",
            value="\n".join(
                [
                    command_line("/voc_invite", XP_GRADE_LEVELS["Confirme"], self.can_manage_voice_feature(member, "invite")),
                    command_line("/voc_kick", XP_GRADE_LEVELS["Confirme"], self.can_manage_voice_feature(member, "kick")),
                    command_line("/voc_transfer", XP_GRADE_LEVELS["Legende"], self.can_manage_voice_feature(member, "transfer")),
                ]
            ),
            inline=False,
        )
        embed.set_footer(text="Les commandes verrouillées se débloquent avec le système de niveau du serveur.")
        return embed

    def render_level_card(self, member: discord.Member) -> str:
        from PIL import Image, ImageChops, ImageDraw, ImageFont

        stats = self.get_member_level_stats(member.guild.id, member.id)
        rank = self.get_member_rank_position(member.guild.id, member.id)
        theme = self.get_level_theme(stats["grade"])
        accent = theme["accent"]
        bg = theme["bg"]

        width, height = 1100, 430
        img = Image.new("RGB", (width, height), tuple(bg))
        draw = ImageDraw.Draw(img)

        try:
            title_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 56)
            grade_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 25)
            value_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 25)
            body_font = ImageFont.truetype("DejaVuSans.ttf", 18)
            small_font = ImageFont.truetype("DejaVuSans.ttf", 15)
            tiny_font = ImageFont.truetype("DejaVuSans.ttf", 14)
        except OSError:
            title_font = ImageFont.load_default()
            grade_font = ImageFont.load_default()
            value_font = ImageFont.load_default()
            body_font = ImageFont.load_default()
            small_font = ImageFont.load_default()
            tiny_font = ImageFont.load_default()

        panel_fill = (13, 19, 37)
        inner_fill = (19, 28, 50)
        white = (245, 247, 252)
        soft = (214, 221, 232)
        muted = (149, 160, 184)
        bar_bg = (35, 49, 77)
        border = tuple(accent)
        glow = tuple(min(255, value + 45) for value in accent)

        ratio = max(0.0, min(1.0, stats["current_xp"] / max(1, stats["needed_xp"])))
        initials = "".join(part[0] for part in member.display_name.split()[:2]).upper() or member.display_name[:1].upper()
        xp_text = f"{stats['xp']:,}".replace(",", " ")
        badge_sheet_path = Path(__file__).with_name("level_badges_sheet.png")
        badge_index_by_grade = {
            "Novice": 0,
            "Actif": 1,
            "Confirme": 2,
            "Elite": 3,
            "Legende": 4,
        }

        draw.rounded_rectangle((14, 14, width - 14, height - 14), radius=36, fill=panel_fill, outline=border, width=3)

        avatar_center_x = 185
        avatar_center_y = 214
        outer_radius = 146
        draw.ellipse(
            (avatar_center_x - outer_radius, avatar_center_y - outer_radius, avatar_center_x + outer_radius, avatar_center_y + outer_radius),
            fill=tuple(accent),
        )

        badge_pasted = False
        if badge_sheet_path.exists():
            try:
                badge_sheet = Image.open(badge_sheet_path).convert("RGBA")
                section_width = badge_sheet.width // 5
                badge_index = badge_index_by_grade.get(stats["grade"], 0)
                left = max(0, badge_index * section_width)
                right = badge_sheet.width if badge_index == 4 else min(badge_sheet.width, (badge_index + 1) * section_width)
                section = badge_sheet.crop((left, 0, right, badge_sheet.height))
                square_side = min(section.width, section.height)
                offset_x = max(0, (section.width - square_side) // 2)
                offset_y = max(0, (section.height - square_side) // 2)
                badge = section.crop((offset_x, offset_y, offset_x + square_side, offset_y + square_side))

                # Remove the plain light/dark background from the generated badge sheet.
                cleaned_pixels: list[tuple[int, int, int, int]] = []
                for red, green, blue, alpha in badge.getdata():
                    max_channel = max(red, green, blue)
                    min_channel = min(red, green, blue)
                    is_dark_bg = red <= 30 and green <= 30 and blue <= 30
                    is_light_bg = red >= 210 and green >= 210 and blue >= 210
                    is_low_saturation = (max_channel - min_channel) <= 18
                    if is_dark_bg or (is_light_bg and is_low_saturation):
                        cleaned_pixels.append((red, green, blue, 0))
                    else:
                        cleaned_pixels.append((red, green, blue, alpha))
                badge.putdata(cleaned_pixels)

                bbox = badge.getbbox()
                if bbox is not None:
                    badge = badge.crop(bbox)

                resampling = getattr(Image, "Resampling", None)
                resample_filter = (
                    resampling.LANCZOS
                    if resampling is not None
                    else getattr(Image, "LANCZOS", Image.BICUBIC)
                )

                badge = badge.resize((228, 228), resample_filter)

                # Clip the badge to a perfect circle so nothing spills outside the avatar zone.
                circle_mask = Image.new("L", badge.size, 0)
                circle_draw = ImageDraw.Draw(circle_mask)
                circle_draw.ellipse((0, 0, badge.width - 1, badge.height - 1), fill=255)

                badge_alpha = badge.getchannel("A")
                clipped_alpha = ImageChops.multiply(badge_alpha, circle_mask)
                badge.putalpha(clipped_alpha)

                badge_x = avatar_center_x - badge.width // 2
                badge_y = avatar_center_y - badge.height // 2
                img.paste(badge, (badge_x, badge_y), badge)
                badge_pasted = True
            except Exception:
                badge_pasted = False

        if not badge_pasted:
            draw.text((avatar_center_x, avatar_center_y), initials, font=title_font, anchor="mm", fill=white)

        right_x = 390
        draw.text((right_x, 86), member.display_name, font=title_font, fill=white)
        draw.text((right_x, 142), f"{stats['grade'].upper()}  •  NIVEAU {stats['level']}", font=grade_font, fill=tuple(accent))

        bar_x1, bar_y1, bar_x2, bar_y2 = right_x, 190, 978, 224
        draw.rounded_rectangle((bar_x1, bar_y1, bar_x2, bar_y2), radius=18, fill=bar_bg)
        if ratio > 0:
            fill_x = int(bar_x1 + (bar_x2 - bar_x1) * ratio)
            draw.rounded_rectangle((bar_x1, bar_y1, max(bar_x1 + 18, fill_x), bar_y2), radius=18, fill=tuple(accent))
        draw.text((right_x, 244), f"{stats['current_xp']} / {stats['needed_xp']} XP vers le prochain niveau", font=body_font, fill=soft)

        stat_boxes = [
            ((right_x, 286, right_x + 170, 354), "XP TOTAL", xp_text),
            ((right_x + 230, 286, right_x + 400, 354), "MESSAGES", str(stats["message_count"])),
            ((right_x + 460, 286, right_x + 690, 354), "TEMPS VOCAL", self.format_voice_duration(stats["voice_seconds"])),
        ]
        for box, label, value in stat_boxes:
            draw.text((box[0], box[1]), label, font=small_font, fill=muted)
            draw.text((box[0], box[1] + 28), value, font=value_font, fill=white)

        draw.text((right_x, 372), "CLASSEMENT", font=body_font, fill=muted)
        draw.text((right_x, 396), f"#{rank}", font=value_font, fill=white)

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        tmp.close()
        img.save(tmp.name)
        return tmp.name

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

    def utcnow(self) -> datetime:
        return discord.utils.utcnow()

    def iso_now(self) -> str:
        return self.utcnow().isoformat()

    def parse_iso_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def mark_ticket_activity(self, guild_id: int, channel_id: int) -> None:
        ticket = self.get_ticket_store(guild_id)["channels"].get(str(channel_id))
        if ticket is None:
            return
        ticket["last_activity_at"] = self.iso_now()
        ticket["recall_sent_at"] = None
        self.save_tickets()

    def mark_sale_activity(self, guild_id: int, channel_id: int) -> None:
        store = self.get_sale_store(guild_id)
        channel_state = store["channels"].get(str(channel_id))
        if not isinstance(channel_state, dict):
            return
        channel_state["last_activity_at"] = self.iso_now()
        channel_state["recall_sent_at"] = None
        self.save_sales()

    def track_managed_channel_activity(self, message: discord.Message) -> None:
        if message.guild is None:
            return
        channel_id = message.channel.id
        guild_id = message.guild.id
        if str(channel_id) in self.get_ticket_store(guild_id)["channels"]:
            self.mark_ticket_activity(guild_id, channel_id)
            return
        if str(channel_id) in self.get_sale_store(guild_id)["channels"]:
            self.mark_sale_activity(guild_id, channel_id)

    def get_promo_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        config = self.get_guild_config(guild.id)
        channel = guild.get_channel(config["promo_channel_id"]) if config["promo_channel_id"] else None
        return channel if isinstance(channel, discord.TextChannel) else None

    def build_promo_embed(self, promo: dict[str, Any]) -> discord.Embed:
        priority = int(promo.get("priority", 1))
        palette = {
            1: discord.Color.from_rgb(94, 129, 172),
            2: discord.Color.from_rgb(46, 204, 113),
            3: discord.Color.from_rgb(241, 196, 15),
            4: discord.Color.from_rgb(230, 126, 34),
            5: discord.Color.from_rgb(231, 76, 60),
        }
        color = palette.get(max(1, min(priority, 5)), discord.Color.blurple())
        embed = discord.Embed(
            title=f"Offer Of The Week #{promo['id']}",
            description=promo["content"],
            color=color,
        )
        embed.add_field(name="Promotion", value=promo["title"], inline=False)
        embed.add_field(name="Priority", value=str(priority), inline=True)
        embed.add_field(name="Status", value="Active" if promo.get("active", True) else "Disabled", inline=True)
        embed.set_author(name="Yishi's Shop Weekly Promotion")
        embed.set_footer(text="Limited weekly offer")
        return embed

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

    def get_sales_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        config = self.get_guild_config(guild.id)
        channel = guild.get_channel(config["sales_channel_id"]) if config["sales_channel_id"] else None
        return channel if isinstance(channel, discord.TextChannel) else None

    def get_sales_review_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        config = self.get_guild_config(guild.id)
        channel = guild.get_channel(config["sales_review_channel_id"]) if config["sales_review_channel_id"] else None
        return channel if isinstance(channel, discord.TextChannel) else None

    def get_sales_category(self, guild: discord.Guild) -> discord.CategoryChannel | None:
        config = self.get_guild_config(guild.id)
        channel = guild.get_channel(config["sales_category_id"]) if config["sales_category_id"] else None
        return channel if isinstance(channel, discord.CategoryChannel) else None

    def build_sales_rules_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="\U0001f4b8 Règlement des ventes membres",
            description=(
                "Respecte ces règles pour vendre et acheter en toute sécurité dans ce salon."
            ),
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="Créer une vente",
            value=(
                "Utilise la commande `/vente` pour envoyer ton annonce au staff.\n"
                "Une fois validée, elle sera publiée ici."
            ),
            inline=False,
        )
        embed.add_field(
            name="Acheter une vente",
            value=(
                "Clique sur le bouton **Acheter** sous une annonce.\n"
                "Le bot créera automatiquement un salon privé entre vendeur et acheteur."
            ),
            inline=False,
        )
        embed.add_field(
            name="Interdiction des MP",
            value=(
                "Toute demande de passage en message privé pour finaliser une vente est interdite.\n"
                "La transaction doit obligatoirement se faire dans le salon créé par le bot."
            ),
            inline=False,
        )
        embed.add_field(
            name="Middleman",
            value=(
                "Des MM sont disponibles si besoin pour sécuriser la transaction.\n"
                "Le service de MM est gratuit : **0% de frais**."
            ),
            inline=False,
        )
        embed.add_field(
            name="Sécurité",
            value=(
                "Si quelqu'un te demande de sortir du ticket de vente, refuse et préviens le staff.\n"
                "Ne finalise jamais une vente hors du salon privé de transaction."
            ),
            inline=False,
        )
        embed.set_footer(text="Yishi's Shop • Ventes sécurisées")
        return embed

    async def fetch_managed_message(
        self,
        channel: discord.TextChannel,
        message_id: int | None,
    ) -> discord.Message | None:
        if not message_id:
            return None
        try:
            return await channel.fetch_message(int(message_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
            return None

    async def cleanup_duplicate_managed_messages(
        self,
        channel: discord.TextChannel,
        keep_message_id: int,
        *,
        title: str | None = None,
    ) -> None:
        if self.user is None:
            return
        with contextlib.suppress(discord.HTTPException):
            async for message in channel.history(limit=25):
                if message.id == keep_message_id or message.author.id != self.user.id:
                    continue
                if title is not None:
                    if not message.embeds or message.embeds[0].title != title:
                        continue
                await message.delete()

    async def ensure_managed_embed_message(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        config_key: str,
        embed: discord.Embed,
        *,
        view: discord.ui.View | None = None,
    ) -> discord.Message | None:
        config = self.get_guild_config(guild.id)
        existing_message = await self.fetch_managed_message(channel, config.get(config_key))

        try:
            if existing_message is not None:
                await existing_message.edit(content=None, embed=embed, view=view)
                await self.cleanup_duplicate_managed_messages(channel, existing_message.id, title=embed.title)
                return existing_message

            managed_message = await channel.send(embed=embed, view=view)
            config[config_key] = managed_message.id
            self.save_config()
            await self.cleanup_duplicate_managed_messages(channel, managed_message.id, title=embed.title)
            return managed_message
        except discord.HTTPException:
            return None

    async def ensure_managed_text_message(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        config_key: str,
        content: str,
    ) -> discord.Message | None:
        config = self.get_guild_config(guild.id)
        existing_message = await self.fetch_managed_message(channel, config.get(config_key))

        try:
            if existing_message is not None:
                await existing_message.edit(content=content, embed=None, attachments=[])
                return existing_message

            managed_message = await channel.send(content)
            config[config_key] = managed_message.id
            self.save_config()
            return managed_message
        except discord.HTTPException:
            return None

    async def ensure_sales_rules_message(self, guild: discord.Guild, sales_channel: discord.TextChannel) -> discord.Message | None:
        embed = self.build_sales_rules_embed()
        return await self.ensure_managed_embed_message(
            guild,
            sales_channel,
            "sales_info_message_id",
            embed,
        )

    async def ensure_sales_review_channel(self, guild: discord.Guild) -> discord.TextChannel:
        config = self.get_guild_config(guild.id)
        review_channel = self.get_sales_review_channel(guild)
        if review_channel is None:
            review_channel = discord.utils.get(guild.text_channels, name=AUTO_SALES_REVIEW_CHANNEL_NAME)
            if review_channel is None:
                review_channel = await guild.create_text_channel(
                    AUTO_SALES_REVIEW_CHANNEL_NAME,
                    reason="Auto configuration validation ventes",
                )
            config["sales_review_channel_id"] = review_channel.id
        elif review_channel.name != AUTO_SALES_REVIEW_CHANNEL_NAME:
            await review_channel.edit(
                name=AUTO_SALES_REVIEW_CHANNEL_NAME,
                reason="Mise à jour configuration validation ventes",
            )

        await self.configure_staff_only_channel(guild, review_channel)
        self.save_config()
        return review_channel

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

    async def ensure_role(self, guild: discord.Guild, name: str, *, mentionable: bool = False) -> discord.Role:
        role = discord.utils.get(guild.roles, name=name)
        if role is None:
            role = await guild.create_role(name=name, mentionable=mentionable, reason="Configuration automatique du serveur")
        return role

    async def ensure_role_order(self, guild: discord.Guild, ordered_roles: list[discord.Role]) -> None:
        positions: dict[discord.Role, int] = {}
        next_position = 1
        for role in ordered_roles:
            if role.is_default():
                continue
            positions[role] = next_position
            next_position += 1
        if positions:
            await guild.edit_role_positions(positions=positions)

    async def ensure_category(
        self,
        guild: discord.Guild,
        categories: dict[str, discord.CategoryChannel],
        name: str,
    ) -> discord.CategoryChannel:
        category = categories.get(name) or discord.utils.get(guild.categories, name=name)
        if category is None:
            category = await guild.create_category(name, reason="Configuration automatique du serveur")
        categories[name] = category
        return category

    async def ensure_text_channel(
        self,
        guild: discord.Guild,
        categories: dict[str, discord.CategoryChannel],
        name: str,
        *,
        category_name: str,
        protected_id: int | None = None,
    ) -> discord.TextChannel:
        channel = guild.get_channel(protected_id) if protected_id else None
        if not isinstance(channel, discord.TextChannel):
            channel = discord.utils.get(guild.text_channels, name=name)
        if channel is None:
            channel = await guild.create_text_channel(name, reason="Configuration automatique du serveur")
        category = await self.ensure_category(guild, categories, category_name)
        await channel.edit(name=name, category=category, reason="Organisation automatique du serveur")
        return channel

    async def ensure_voice_channel(
        self,
        guild: discord.Guild,
        categories: dict[str, discord.CategoryChannel],
        name: str,
        *,
        category_name: str,
    ) -> discord.VoiceChannel:
        channel = discord.utils.get(guild.voice_channels, name=name)
        if channel is None:
            channel = await guild.create_voice_channel(name, reason="Configuration automatique du serveur")
        category = await self.ensure_category(guild, categories, category_name)
        await channel.edit(name=name, category=category, reason="Organisation automatique du serveur")
        return channel

    def build_shop_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="Yishi's Shop",
            description=(
                "Bienvenue sur le shop.\n\n"
                "Tu peux retrouver ici nos différents services, preuves et avis clients.\n"
                "Pour les prix, disponibilités ou demandes spéciales, ouvre un ticket ou viens en message privé."
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Services",
            value="Blox Fruits, services variés, gacha, ventes entre membres et offres ponctuelles.",
            inline=False,
        )
        embed.set_footer(text="Prix et demandes spéciales uniquement en ticket ou en DM")
        return embed

    def build_free_access_embed(self, service_name: str) -> discord.Embed:
        embed = discord.Embed(
            title=f"{service_name} Free",
            description=(
                "Ce salon est réservé aux membres ayant atteint l'accès hebdomadaire.\n"
                f"Il faut au moins **{FREE_INVITE_REQUIREMENT} invitations cette semaine** pour y accéder.\n"
                "Les accès sont réinitialisés chaque semaine."
            ),
            color=discord.Color.dark_teal(),
        )
        embed.set_footer(text="Lecture seule • Le staff et le bot publient les comptes")
        return embed

    async def rebuild_server(self, guild: discord.Guild) -> dict[str, int]:
        config = self.get_guild_config(guild.id)
        categories: dict[str, discord.CategoryChannel] = {}
        kept_channel_ids = set(PROTECTED_CHANNEL_IDS)

        staff_role = await self.ensure_role(guild, AUTO_STAFF_ROLE_NAME)
        helper_role = await self.ensure_role(guild, HELPER_ROLE_NAME)
        trial_mod_role = await self.ensure_role(guild, TRIAL_MOD_ROLE_NAME)
        moderator_role = await self.ensure_role(guild, MODERATOR_ROLE_NAME)
        responsable_role = await self.ensure_role(guild, RESPONSABLE_ROLE_NAME)
        admin_role = await self.ensure_role(guild, ADMIN_ROLE_NAME)
        founder_role = await self.ensure_role(guild, FOUNDER_ROLE_NAME)
        archive_role = await self.ensure_role(guild, AUTO_ARCHIVE_ROLE_NAME)
        free_role = await self.ensure_role(guild, FREE_ACCESS_ROLE_NAME)
        for role_name in XP_ROLE_NAMES:
            await self.ensure_role(guild, role_name)
        await self.ensure_role_order(
            guild,
            [
                free_role,
                helper_role,
                trial_mod_role,
                moderator_role,
                responsable_role,
                admin_role,
                staff_role,
                founder_role,
                archive_role,
            ],
        )

        config["staff_role_id"] = staff_role.id
        config["helper_role_id"] = helper_role.id
        config["trial_mod_role_id"] = trial_mod_role.id
        config["moderator_role_id"] = moderator_role.id
        config["responsable_role_id"] = responsable_role.id
        config["admin_role_id"] = admin_role.id
        config["founder_role_id"] = founder_role.id
        config["archive_role_id"] = archive_role.id
        config["free_access_role_id"] = free_role.id

        welcome_channel = await self.ensure_text_channel(guild, categories, WELCOME_CHANNEL_NAME, category_name="✦ ACCUEIL", protected_id=1493595067338723338)
        rules_channel = await self.ensure_text_channel(guild, categories, RULES_CHANNEL_NAME, category_name="✦ ACCUEIL")
        announcements_channel = await self.ensure_text_channel(guild, categories, ANNOUNCEMENTS_CHANNEL_NAME, category_name="✦ ACCUEIL")
        shop_channel = await self.ensure_text_channel(guild, categories, SHOP_CHANNEL_NAME, category_name="✦ BOUTIQUE")
        proofs_channel = await self.ensure_text_channel(guild, categories, PROOFS_CHANNEL_NAME, category_name="✦ BOUTIQUE", protected_id=1490431484593574039)
        vouches_channel = await self.ensure_text_channel(guild, categories, VOUCHES_CHANNEL_NAME, category_name="✦ BOUTIQUE", protected_id=1490432216952733847)
        reviews_channel = await self.ensure_text_channel(guild, categories, REVIEWS_CHANNEL_NAME, category_name="✦ BOUTIQUE", protected_id=1490431507859247134)
        uber_eat_channel = await self.ensure_text_channel(guild, categories, UBER_EAT_CHANNEL_NAME, category_name="✦ BOUTIQUE", protected_id=1501249716980285530)
        gacha_spin_channel = await self.ensure_text_channel(guild, categories, AUTO_GACHA_SPIN_CHANNEL_NAME, category_name="✦ BOUTIQUE")
        gacha_winner_channel = await self.ensure_text_channel(guild, categories, AUTO_GACHA_WINNER_CHANNEL_NAME, category_name="✦ BOUTIQUE", protected_id=1502264206794297395)
        sales_channel = await self.ensure_text_channel(guild, categories, AUTO_SALES_CHANNEL_NAME, category_name="✦ BOUTIQUE")
        netflix_channel = await self.ensure_text_channel(guild, categories, FREE_NETFLIX_CHANNEL_NAME, category_name=FREE_CATEGORY_NAME)
        crunchyroll_channel = await self.ensure_text_channel(guild, categories, FREE_CRUNCHYROLL_CHANNEL_NAME, category_name=FREE_CATEGORY_NAME)
        general_channel = await self.ensure_text_channel(guild, categories, GENERAL_CHANNEL_NAME, category_name="✦ COMMUNAUTÉ", protected_id=1493004543137681498)
        media_channel = await self.ensure_text_channel(guild, categories, MEDIA_CHANNEL_NAME, category_name="✦ COMMUNAUTÉ", protected_id=1490431816224473208)
        giveaways_channel = await self.ensure_text_channel(guild, categories, GIVEAWAYS_CHANNEL_NAME, category_name="✦ COMMUNAUTÉ")
        ticket_panel_channel = await self.ensure_text_channel(guild, categories, TICKET_PANEL_CHANNEL_NAME, category_name="✦ SUPPORT")
        ticket_info_channel = await self.ensure_text_channel(guild, categories, TICKET_INFO_CHANNEL_NAME, category_name="✦ SUPPORT")
        logs_channel = await self.ensure_text_channel(guild, categories, AUTO_LOGS_CHANNEL_NAME, category_name="✦ STAFF")
        transcript_channel = await self.ensure_text_channel(guild, categories, "📄・logs-transcript", category_name="✦ STAFF")
        sales_review_channel = await self.ensure_text_channel(guild, categories, "✅・ventes-validation", category_name="✦ STAFF")
        gacha_logs_channel = await self.ensure_text_channel(guild, categories, "📝・gacha-logs", category_name="✦ STAFF")
        staff_prices_channel = await self.ensure_text_channel(guild, categories, STAFF_PRICE_CHANNEL_NAME, category_name="✦ STAFF")
        voice_creator_channel = await self.ensure_voice_channel(guild, categories, VOICE_CREATOR_CHANNEL_NAME, category_name="✦ VOCAUX")
        helper_ticket_category = await self.ensure_category(guild, categories, HELPER_TICKET_CATEGORY_NAME)
        purchase_ticket_category = await self.ensure_category(guild, categories, PURCHASE_TICKET_CATEGORY_NAME)
        staff_ticket_category = await self.ensure_category(guild, categories, STAFF_TICKET_CATEGORY_NAME)
        archive_ticket_category = await self.ensure_category(guild, categories, ARCHIVED_TICKET_CATEGORY_NAME)
        sales_private_category = await self.ensure_category(guild, categories, AUTO_SALES_CATEGORY_NAME)

        config["welcome_channel_id"] = welcome_channel.id
        config["rules_channel_id"] = rules_channel.id
        config["announcements_channel_id"] = announcements_channel.id
        config["shop_channel_id"] = shop_channel.id
        config["gacha_spin_channel_id"] = gacha_spin_channel.id
        config["gacha_winner_channel_id"] = gacha_winner_channel.id
        config["gacha_logs_channel_id"] = gacha_logs_channel.id
        config["sales_channel_id"] = sales_channel.id
        config["sales_review_channel_id"] = sales_review_channel.id
        config["sales_category_id"] = sales_private_category.id
        config["logs_channel_id"] = logs_channel.id
        config["transcript_logs_channel_id"] = transcript_channel.id
        config["giveaways_channel_id"] = giveaways_channel.id
        config["free_category_id"] = categories[FREE_CATEGORY_NAME].id
        config["free_netflix_channel_id"] = netflix_channel.id
        config["free_crunchyroll_channel_id"] = crunchyroll_channel.id
        config["ticket_category_id"] = helper_ticket_category.id
        config["ticket_helper_category_id"] = helper_ticket_category.id
        config["ticket_purchase_category_id"] = purchase_ticket_category.id
        config["ticket_staff_category_id"] = staff_ticket_category.id
        config["archive_category_id"] = archive_ticket_category.id
        config["voice_category_id"] = categories["✦ VOCAUX"].id
        config["voice_creator_channel_id"] = voice_creator_channel.id
        config["staff_prices_channel_id"] = staff_prices_channel.id
        if guild.get_channel(DEFAULT_PROMO_CHANNEL_ID):
            config["promo_channel_id"] = DEFAULT_PROMO_CHANNEL_ID

        keep_channel_ids = {
            welcome_channel.id,
            rules_channel.id,
            announcements_channel.id,
            shop_channel.id,
            proofs_channel.id,
            vouches_channel.id,
            reviews_channel.id,
            uber_eat_channel.id,
            gacha_spin_channel.id,
            gacha_winner_channel.id,
            sales_channel.id,
            netflix_channel.id,
            crunchyroll_channel.id,
            general_channel.id,
            media_channel.id,
            giveaways_channel.id,
            ticket_panel_channel.id,
            ticket_info_channel.id,
            logs_channel.id,
            transcript_channel.id,
            sales_review_channel.id,
            gacha_logs_channel.id,
            staff_prices_channel.id,
            voice_creator_channel.id,
        } | kept_channel_ids

        keep_category_ids = {
            category.id
            for category in (
                helper_ticket_category,
                purchase_ticket_category,
                staff_ticket_category,
                archive_ticket_category,
                sales_private_category,
                *categories.values(),
            )
        }

        for channel in list(guild.channels):
            if channel.id in keep_channel_ids or channel.id in keep_category_ids:
                continue
            with contextlib.suppress(discord.HTTPException):
                await channel.delete(reason="Reconstruction automatique du serveur")

        for category in list(guild.categories):
            if category.id in keep_category_ids:
                continue
            if category.channels:
                continue
            with contextlib.suppress(discord.HTTPException):
                await category.delete(reason="Reconstruction automatique du serveur")

        await self.configure_logs_channel_permissions(guild, logs_channel)
        await self.configure_staff_only_channel(guild, transcript_channel)
        await self.configure_staff_only_channel(guild, sales_review_channel)
        await self.configure_staff_only_channel(guild, gacha_logs_channel)
        await self.configure_staff_only_channel(guild, staff_prices_channel)

        for free_channel in (netflix_channel, crunchyroll_channel):
            await free_channel.set_permissions(guild.default_role, view_channel=False, send_messages=False, add_reactions=False)
            await free_channel.set_permissions(free_role, view_channel=True, send_messages=False, read_message_history=True, add_reactions=False)
            for role in (helper_role, trial_mod_role, moderator_role, responsable_role, admin_role, founder_role, staff_role, archive_role):
                await free_channel.set_permissions(role, view_channel=True, send_messages=True, read_message_history=True)

        await sales_channel.set_permissions(guild.default_role, view_channel=True, send_messages=False)

        with contextlib.suppress(discord.HTTPException):
            await self.ensure_managed_embed_message(guild, shop_channel, "shop_message_id", self.build_shop_embed())
        with contextlib.suppress(discord.HTTPException):
            await self.ensure_managed_embed_message(
                guild,
                netflix_channel,
                "free_netflix_message_id",
                self.build_free_access_embed("Netflix"),
            )
        with contextlib.suppress(discord.HTTPException):
            await self.ensure_managed_embed_message(
                guild,
                crunchyroll_channel,
                "free_crunchyroll_message_id",
                self.build_free_access_embed("Crunchyroll"),
            )
        with contextlib.suppress(discord.HTTPException):
            await self.send_rules_text(guild, rules_channel)
        with contextlib.suppress(discord.HTTPException):
            panel_message = await self.ensure_managed_embed_message(
                guild,
                ticket_panel_channel,
                "ticket_panel_message_id",
                build_ticket_panel_embed(),
                view=TicketPanelView(self),
            )
            if panel_message is not None:
                self.get_ticket_store(guild.id)["panel_message_id"] = panel_message.id

        await self.ensure_sales_rules_message(guild, sales_channel)
        self.save_config()
        self.save_tickets()
        await self.sync_all_free_access_roles(guild)
        return {
            "roles": 9 + len(XP_ROLE_NAMES),
            "channels": len(keep_channel_ids),
            "categories": len(keep_category_ids),
        }

    def build_sale_embed(self, sale: dict[str, Any], *, reserved: bool = False) -> discord.Embed:
        status = "reserved" if reserved else sale.get("status", "available")
        status_map = {
            "pending": ("En attente de validation", discord.Color.orange()),
            "available": ("Disponible", discord.Color.blurple()),
            "reserved": ("Réservée", discord.Color.orange()),
            "rejected": ("Refusée", discord.Color.red()),
            "closed": ("Clôturée", discord.Color.dark_grey()),
        }
        status_text, color = status_map.get(status, ("Disponible", discord.Color.blurple()))
        embed = discord.Embed(
            title="💸 Vente en cours",
            description="Clique sur **Acheter** si tu veux ouvrir un salon privé avec le vendeur.",
            color=color,
        )
        embed.add_field(name="Catégorie", value=sale["category"], inline=True)
        embed.add_field(name="Produits", value=sale["product"], inline=True)
        embed.add_field(name="Prix", value=sale["price"], inline=True)
        embed.add_field(name="Description", value=sale["description"], inline=False)
        embed.add_field(name="Statut", value=status_text, inline=True)
        embed.add_field(name="Vendeur", value=f"<@{sale['seller_id']}>", inline=True)
        if sale.get("buyer_id"):
            embed.add_field(name="Acheteur", value=f"<@{sale['buyer_id']}>", inline=True)
        embed.set_footer(text="Yishi's Shop • Vente membre")
        return embed

    def build_sale_review_embed(self, sale: dict[str, Any]) -> discord.Embed:
        embed = discord.Embed(
            title="Validation vente",
            description="Le staff doit accepter ou refuser cette vente avant publication.",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Vendeur", value=f"<@{sale['seller_id']}>", inline=True)
        embed.add_field(name="Catégorie", value=sale["category"], inline=True)
        embed.add_field(name="Prix", value=sale["price"], inline=True)
        embed.add_field(name="Produits", value=sale["product"], inline=False)
        embed.add_field(name="Description", value=sale["description"], inline=False)
        embed.add_field(name="Statut", value="En attente", inline=True)
        embed.set_footer(text="Validation staff requise")
        return embed

    async def ensure_sales_config(self, guild: discord.Guild) -> tuple[discord.TextChannel, discord.CategoryChannel, discord.TextChannel]:
        config = self.get_guild_config(guild.id)
        sales_channel = self.get_sales_channel(guild)
        if sales_channel is None:
            sales_channel = discord.utils.get(guild.text_channels, name=AUTO_SALES_CHANNEL_NAME)
            if sales_channel is None:
                sales_channel = await guild.create_text_channel(
                    AUTO_SALES_CHANNEL_NAME,
                    reason="Auto configuration ventes",
                )
            config["sales_channel_id"] = sales_channel.id
        elif sales_channel.name != AUTO_SALES_CHANNEL_NAME:
            await sales_channel.edit(name=AUTO_SALES_CHANNEL_NAME, reason="Mise ? jour configuration ventes")

        sales_category = self.get_sales_category(guild)
        if sales_category is None:
            sales_category = discord.utils.get(guild.categories, name=AUTO_SALES_CATEGORY_NAME)
            if sales_category is None:
                sales_category = await guild.create_category(
                    AUTO_SALES_CATEGORY_NAME,
                    reason="Auto configuration ventes",
                )
            config["sales_category_id"] = sales_category.id

        review_channel = await self.ensure_sales_review_channel(guild)
        self.save_config()
        return sales_channel, sales_category, review_channel

    async def create_sale_listing(
        self,
        interaction: discord.Interaction,
        category: str,
        product: str,
        price: str,
        description: str,
    ) -> None:
        guild = interaction.guild
        seller = interaction.user
        if guild is None or not isinstance(seller, discord.Member):
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return

        _, _, review_channel = await self.ensure_sales_config(guild)
        await interaction.response.defer(ephemeral=True)

        sale = {
            "seller_id": seller.id,
            "category": category,
            "product": product,
            "price": price,
            "description": description,
            "status": "pending",
            "buyer_id": None,
            "sale_channel_id": None,
            "review_message_id": None,
            "public_message_id": None,
            "created_at": discord.utils.utcnow().isoformat(),
        }

        review_message = await review_channel.send(
            embed=self.build_sale_review_embed(sale),
            view=SaleApprovalView(self),
        )
        sale["review_message_id"] = review_message.id
        store = self.get_sale_store(guild.id)
        store["reviews"][str(review_message.id)] = sale
        self.save_sales()

        await self.log_event(
            guild,
            "Nouvelle demande de vente",
            f"{seller.mention} a soumis une vente pour validation : **{product}**.",
            discord.Color.gold(),
            thumbnail_url=seller.display_avatar.url,
            fields=[
                ("Salon staff", review_channel.mention, True),
                ("Prix", price, True),
                ("Catégorie", category, True),
            ],
        )
        await interaction.followup.send(
            f"Ta vente a été envoyée au staff pour validation dans {review_channel.mention}.",
            ephemeral=True,
        )

    async def approve_sale_listing(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        review_message = interaction.message
        member = interaction.user
        if guild is None or review_message is None or not isinstance(member, discord.Member):
            await interaction.response.send_message("Impossible de valider cette vente.", ephemeral=True)
            return
        if not self.is_staff_member(member):
            await interaction.response.send_message("Seul le staff peut valider une vente.", ephemeral=True)
            return

        store = self.get_sale_store(guild.id)
        sale = store["reviews"].get(str(review_message.id))
        if sale is None:
            await interaction.response.send_message("Cette demande de vente n'existe plus.", ephemeral=True)
            return
        if sale.get("status") != "pending":
            await interaction.response.send_message("Cette vente a déjà été traitée.", ephemeral=True)
            return

        sales_channel, _, _ = await self.ensure_sales_config(guild)
        await interaction.response.defer(ephemeral=True)

        sale["status"] = "available"
        public_message = await sales_channel.send(embed=self.build_sale_embed(sale), view=SaleListingView(self))
        sale["public_message_id"] = public_message.id
        store["messages"][str(public_message.id)] = sale
        store["reviews"].pop(str(review_message.id), None)
        self.save_sales()

        approved_embed = self.build_sale_review_embed(sale)
        approved_embed.color = discord.Color.green()
        approved_embed.set_field_at(5, name="Statut", value=f"Acceptée par {member.mention}", inline=True)
        await review_message.edit(embed=approved_embed, view=None)

        seller = guild.get_member(int(sale["seller_id"]))
        if seller is not None:
            try:
                await seller.send(f"Ta vente **{sale['product']}** a été acceptée et publiée dans {sales_channel.mention}.")
            except discord.Forbidden:
                pass

        await self.log_event(
            guild,
            "Vente validée",
            f"{member.mention} a validé la vente **{sale['product']}**.",
            discord.Color.green(),
            thumbnail_url=member.display_avatar.url,
            fields=[("Salon public", sales_channel.mention, True)],
        )
        await interaction.followup.send("Vente acceptée et publiée.", ephemeral=True)

    async def reject_sale_listing(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        review_message = interaction.message
        member = interaction.user
        if guild is None or review_message is None or not isinstance(member, discord.Member):
            await interaction.response.send_message("Impossible de refuser cette vente.", ephemeral=True)
            return
        if not self.is_staff_member(member):
            await interaction.response.send_message("Seul le staff peut refuser une vente.", ephemeral=True)
            return

        store = self.get_sale_store(guild.id)
        sale = store["reviews"].get(str(review_message.id))
        if sale is None:
            await interaction.response.send_message("Cette demande de vente n'existe plus.", ephemeral=True)
            return
        if sale.get("status") != "pending":
            await interaction.response.send_message("Cette vente a déjà été traitée.", ephemeral=True)
            return

        sale["status"] = "rejected"
        sale["rejected_by"] = member.id
        sale["rejected_at"] = discord.utils.utcnow().isoformat()
        store["reviews"].pop(str(review_message.id), None)
        self.save_sales()

        rejected_embed = self.build_sale_review_embed(sale)
        rejected_embed.color = discord.Color.red()
        rejected_embed.set_field_at(5, name="Statut", value=f"Refusée par {member.mention}", inline=True)
        await review_message.edit(embed=rejected_embed, view=None)

        seller = guild.get_member(int(sale["seller_id"]))
        if seller is not None:
            try:
                await seller.send(f"Ta vente **{sale['product']}** a été refusée par le staff.")
            except discord.Forbidden:
                pass

        await self.log_event(
            guild,
            "Vente refusée",
            f"{member.mention} a refusé la vente **{sale['product']}**.",
            discord.Color.red(),
            thumbnail_url=member.display_avatar.url,
        )
        await interaction.response.send_message("Vente refusée.", ephemeral=True)

    async def buy_sale(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        message = interaction.message
        buyer = interaction.user
        if guild is None or message is None or not isinstance(buyer, discord.Member):
            await interaction.response.send_message("Impossible d'acheter cette vente ici.", ephemeral=True)
            return

        store = self.get_sale_store(guild.id)
        sale = store["messages"].get(str(message.id))
        if sale is None:
            await interaction.response.send_message("Cette vente n'existe plus.", ephemeral=True)
            return
        if sale.get("status") != "available":
            await interaction.response.send_message("Cette vente est déjà prise.", ephemeral=True)
            return
        if sale["seller_id"] == buyer.id:
            await interaction.response.send_message("Tu ne peux pas acheter ta propre vente.", ephemeral=True)
            return

        config = self.get_guild_config(guild.id)
        staff_role = guild.get_role(config["staff_role_id"]) if config["staff_role_id"] else None
        sales_category = self.get_sales_category(guild)
        seller = guild.get_member(int(sale["seller_id"]))
        if seller is None:
            await interaction.response.send_message("Le vendeur n'est plus disponible sur le serveur.", ephemeral=True)
            return
        if sales_category is None:
            _, sales_category, _ = await self.ensure_sales_config(guild)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            buyer: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            ),
            seller: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            ),
        }
        if staff_role is not None:
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                manage_messages=True,
            )
        if guild.owner is not None:
            overwrites[guild.owner] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                manage_messages=True,
            )

        await interaction.response.defer(ephemeral=True)
        channel_name = slugify_name(f"vente-{sale['product']}-{buyer.display_name}")[:90]
        sale_channel = await guild.create_text_channel(
            channel_name,
            category=sales_category,
            overwrites=overwrites,
            reason=f"Vente ouverte par {buyer}",
        )

        sale["status"] = "reserved"
        sale["buyer_id"] = buyer.id
        sale["sale_channel_id"] = sale_channel.id
        store["channels"][str(sale_channel.id)] = {
            "message_id": str(message.id),
            "last_activity_at": self.iso_now(),
            "recall_sent_at": None,
        }
        self.save_sales()

        reserved_embed = self.build_sale_embed(sale, reserved=True)
        await message.edit(embed=reserved_embed, view=None)

        ticket_embed = discord.Embed(
            title="🧾 Vente ouverte",
            description=(
                "Ce salon privé a été créé pour finaliser la transaction.\n"
                "Le staff pourra clôturer la vente une fois terminée."
            ),
            color=discord.Color.green(),
        )
        ticket_embed.add_field(name="Vendeur", value=seller.mention, inline=True)
        ticket_embed.add_field(name="Acheteur", value=buyer.mention, inline=True)
        ticket_embed.add_field(name="Prix", value=sale["price"], inline=True)
        ticket_embed.add_field(name="Produit", value=sale["product"], inline=False)
        ticket_embed.add_field(name="Description", value=sale["description"], inline=False)
        await sale_channel.send(embed=ticket_embed)

        await self.log_event(
            guild,
            "Vente réservée",
            f"{buyer.mention} a réservé la vente **{sale['product']}**.",
            discord.Color.orange(),
            thumbnail_url=buyer.display_avatar.url,
            fields=[
                ("Salon privé", sale_channel.mention, True),
                ("Vendeur", seller.mention, True),
            ],
        )
        await interaction.followup.send(
            f"Vente réservée, le salon privé a été créé : {sale_channel.mention}",
            ephemeral=True,
        )

    async def close_sale_channel(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        channel = interaction.channel
        member = interaction.user
        if guild is None or channel is None or not isinstance(member, discord.Member):
            await interaction.response.send_message("Impossible de fermer cette vente.", ephemeral=True)
            return
        if not self.is_staff_member(member):
            await interaction.response.send_message("Seul le staff peut fermer une vente.", ephemeral=True)
            return

        store = self.get_sale_store(guild.id)
        channel_state = store["channels"].get(str(channel.id))
        if channel_state is None:
            await interaction.response.send_message("Ce salon n\'est pas une vente gérée par le bot.", ephemeral=True)
            return
        message_id = channel_state.get("message_id") if isinstance(channel_state, dict) else channel_state

        sale = store["messages"].get(str(message_id))
        if sale is None:
            store["channels"].pop(str(channel.id), None)
            self.save_sales()
            await interaction.response.send_message("Cette vente n'existe plus dans les données.", ephemeral=True)
            return

        sales_channel = self.get_sales_channel(guild)
        if sales_channel is not None:
            try:
                listing_message = await sales_channel.fetch_message(int(message_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                listing_message = None
            if listing_message is not None:
                try:
                    await listing_message.delete()
                except discord.HTTPException:
                    pass

        sale["status"] = "closed"
        sale["closed_by"] = member.id
        sale["closed_at"] = discord.utils.utcnow().isoformat()
        store["channels"].pop(str(channel.id), None)
        self.save_sales()

        await interaction.response.send_message("Vente clôturée, suppression du salon en cours...", ephemeral=True)
        await self.log_event(
            guild,
            "Vente clôturée",
            f"{member.mention} a clôturé la vente **{sale['product']}**.",
            discord.Color.red(),
            thumbnail_url=member.display_avatar.url,
            fields=[
                ("Acheteur", f"<@{sale['buyer_id']}>" if sale.get("buyer_id") else "Aucun", True),
                ("Vendeur", f"<@{sale['seller_id']}>", True),
            ],
        )
        await asyncio.sleep(2)
        await channel.delete(reason=f"Vente clôturée par {member}")

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

    def select_next_promo(self, guild_id: int) -> dict[str, Any] | None:
        store = self.get_promo_store(guild_id)
        active_promos = [promo for promo in store["promotions"] if promo.get("active", True)]
        if not active_promos:
            return None
        return min(
            active_promos,
            key=lambda promo: (
                -int(promo.get("priority", 1)),
                int(promo.get("queue_position", promo["id"])),
                promo.get("last_posted_at") or "",
            ),
        )

    async def post_promo(self, guild: discord.Guild, promo: dict[str, Any], *, automatic: bool) -> discord.Message | None:
        channel = self.get_promo_channel(guild)
        if channel is None:
            return None

        embed = self.build_promo_embed(promo)
        content = "-# Interested? Open a ticket to claim this weekly offer."
        message = await channel.send(content=content, embed=embed)

        promo["last_posted_at"] = self.iso_now()
        max_queue = max(
            (int(existing.get("queue_position", existing["id"])) for existing in self.get_promo_store(guild.id)["promotions"]),
            default=0,
        )
        promo["queue_position"] = max_queue + 1
        if automatic:
            now_paris = self.utcnow().astimezone(self.paris_tz)
            self.get_promo_store(guild.id)["last_auto_post_week"] = now_paris.strftime("%G-W%V")
        self.save_promos()

        await self.log_event(
            guild,
            "Promotion publiée",
            f"La promotion **{promo['title']}** a été publiée.",
            discord.Color.gold(),
            fields=[
                ("Salon", channel.mention, True),
                ("Priorité", str(promo.get("priority", 1)), True),
                ("Mode", "Automatique" if automatic else "Manuel", True),
            ],
        )
        return message

    async def process_weekly_promotions(self) -> None:
        now_paris = self.utcnow().astimezone(self.paris_tz)
        if now_paris.weekday() != 4 or now_paris.hour != 20:
            return

        current_week_key = now_paris.strftime("%G-W%V")
        for guild in self.guilds:
            store = self.get_promo_store(guild.id)
            if store.get("last_auto_post_week") == current_week_key:
                continue
            promo = self.select_next_promo(guild.id)
            if promo is None:
                continue
            try:
                await self.post_promo(guild, promo, automatic=True)
            except discord.HTTPException:
                continue

    async def process_ticket_recalls(self) -> None:
        now = self.utcnow()
        for guild in self.guilds:
            config = self.get_guild_config(guild.id)
            staff_role = guild.get_role(config["staff_role_id"]) if config["staff_role_id"] else None
            if staff_role is None:
                continue

            changed = False
            store = self.get_ticket_store(guild.id)
            for ticket in store["channels"].values():
                if ticket.get("status") != "open":
                    continue
                channel = guild.get_channel(int(ticket["channel_id"]))
                if not isinstance(channel, discord.TextChannel):
                    continue
                last_activity = self.parse_iso_datetime(ticket.get("last_activity_at")) or channel.created_at
                recall_sent_at = self.parse_iso_datetime(ticket.get("recall_sent_at"))
                if now - last_activity < timedelta(hours=TICKET_RECALL_HOURS):
                    continue
                if recall_sent_at is not None and recall_sent_at >= last_activity:
                    continue
                try:
                    await channel.send(
                        f"{staff_role.mention} rappel automatique : ce ticket est inactif depuis plus de {TICKET_RECALL_HOURS}h."
                    )
                except discord.HTTPException:
                    continue
                ticket["recall_sent_at"] = self.iso_now()
                changed = True
            if changed:
                self.save_tickets()

    async def process_sale_recalls(self) -> None:
        now = self.utcnow()
        for guild in self.guilds:
            store = self.get_sale_store(guild.id)
            changed = False
            for channel_id, channel_state in store["channels"].items():
                if not isinstance(channel_state, dict):
                    continue
                sale = store["messages"].get(str(channel_state.get("message_id")))
                if sale is None or sale.get("status") != "reserved":
                    continue
                channel = guild.get_channel(int(channel_id))
                if not isinstance(channel, discord.TextChannel):
                    continue
                last_activity = self.parse_iso_datetime(channel_state.get("last_activity_at")) or channel.created_at
                recall_sent_at = self.parse_iso_datetime(channel_state.get("recall_sent_at"))
                if now - last_activity < timedelta(hours=SALES_RECALL_HOURS):
                    continue
                if recall_sent_at is not None and recall_sent_at >= last_activity:
                    continue
                mentions = [f"<@{sale['seller_id']}>"]
                if sale.get("buyer_id"):
                    mentions.append(f"<@{sale['buyer_id']}>")
                try:
                    await channel.send(
                        f"{' '.join(mentions)} rappel automatique : cette vente est inactive depuis plus de {SALES_RECALL_HOURS}h."
                    )
                except discord.HTTPException:
                    continue
                channel_state["recall_sent_at"] = self.iso_now()
                changed = True
            if changed:
                self.save_sales()

    async def process_weekly_free_access_reset(self) -> None:
        now_paris = self.utcnow().astimezone(self.paris_tz)
        if now_paris.weekday() != FREE_RESET_WEEKDAY or now_paris.hour != FREE_RESET_HOUR or now_paris.minute < FREE_RESET_MINUTE:
            return

        current_week_key = now_paris.strftime("%G-W%V")
        for guild in self.guilds:
            store = self.get_invite_store(guild.id)
            if store.get("last_weekly_reset_key") == current_week_key:
                continue
            store["weekly_counts"] = {}
            store["last_weekly_reset_key"] = current_week_key
            self.save_invites()
            await self.sync_all_free_access_roles(guild)

    async def run_background_jobs(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                await self.process_ticket_recalls()
                await self.process_sale_recalls()
                await self.process_weekly_promotions()
                await self.process_weekly_free_access_reset()
                await self.process_voice_xp()
            except Exception:
                traceback.print_exc()
            await asyncio.sleep(60)

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

        sales_channel = guild.get_channel(config["sales_channel_id"]) if config["sales_channel_id"] else None
        if not isinstance(sales_channel, discord.TextChannel):
            sales_channel = discord.utils.get(guild.text_channels, name=AUTO_SALES_CHANNEL_NAME)
            if sales_channel is None:
                sales_channel = await guild.create_text_channel(
                    AUTO_SALES_CHANNEL_NAME,
                    reason="Auto configuration ventes",
                )
            config["sales_channel_id"] = sales_channel.id

        sales_category = guild.get_channel(config["sales_category_id"]) if config["sales_category_id"] else None
        if not isinstance(sales_category, discord.CategoryChannel):
            sales_category = discord.utils.get(guild.categories, name=AUTO_SALES_CATEGORY_NAME)
            if sales_category is None:
                sales_category = await guild.create_category(
                    AUTO_SALES_CATEGORY_NAME,
                    reason="Auto configuration ventes",
                )
            config["sales_category_id"] = sales_category.id

        promo_channel = guild.get_channel(config["promo_channel_id"]) if config["promo_channel_id"] else None
        if not isinstance(promo_channel, discord.TextChannel):
            fixed_channel = guild.get_channel(DEFAULT_PROMO_CHANNEL_ID)
            if isinstance(fixed_channel, discord.TextChannel):
                promo_channel = fixed_channel
                config["promo_channel_id"] = fixed_channel.id

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

    async def sync_member_invite_roles(self, member: discord.Member) -> None:
        invite_count = self.get_invite_role_count_from_now(member.guild.id, member.id)
        best_role_name = get_best_invite_role_name(invite_count)

        invite_roles = {
            role_name: discord.utils.get(member.guild.roles, name=role_name)
            for role_name in INVITE_ROLE_REQUIREMENTS
        }
        roles_to_remove = [
            role
            for role_name, role in invite_roles.items()
            if role is not None and role in member.roles and role_name != best_role_name
        ]
        role_to_add = invite_roles.get(best_role_name) if best_role_name else None

        if roles_to_remove:
            try:
                await member.remove_roles(*roles_to_remove, reason="Mise à jour auto des rôles invitations")
            except discord.HTTPException:
                pass

        if role_to_add is not None and role_to_add not in member.roles:
            try:
                await member.add_roles(role_to_add, reason="Attribution auto du rôle invitations")
            except discord.HTTPException:
                pass

    async def sync_all_invite_roles(self, guild: discord.Guild) -> None:
        for member in guild.members:
            if member.bot:
                continue
            await self.sync_member_invite_roles(member)

    async def sync_member_free_access(self, member: discord.Member) -> None:
        config = self.get_guild_config(member.guild.id)
        role = member.guild.get_role(config["free_access_role_id"]) if config["free_access_role_id"] else None
        if role is None:
            role = discord.utils.get(member.guild.roles, name=FREE_ACCESS_ROLE_NAME)
            if role is None:
                return
            config["free_access_role_id"] = role.id
            self.save_config()

        weekly_count = self.get_weekly_invite_count(member.guild.id, member.id)
        has_role = role in member.roles
        should_have_role = weekly_count >= FREE_INVITE_REQUIREMENT
        if should_have_role and not has_role:
            await member.add_roles(role, reason="Accès free hebdomadaire débloqué")
        elif has_role and not should_have_role:
            await member.remove_roles(role, reason="Réinitialisation hebdomadaire des accès free")

    async def sync_all_free_access_roles(self, guild: discord.Guild) -> None:
        for member in guild.members:
            if member.bot:
                continue
            await self.sync_member_free_access(member)

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
        weekly_counts = store["weekly_counts"]
        weekly_counts[key] = int(weekly_counts.get(key, 0)) + 1
        store["member_inviter_ids"][str(member.id)] = inviter.id
        self.save_invites()
        inviter_member = member.guild.get_member(inviter.id)
        if inviter_member is not None:
            await self.sync_member_invite_roles(inviter_member)
            await self.sync_member_free_access(inviter_member)
        return inviter_member

    async def schedule_existing_giveaways(self) -> None:
        for guild_id, guild_store in self.giveaway_data.items():
            giveaways = guild_store.get("giveaways", guild_store) if isinstance(guild_store, dict) else {}
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

    async def send_rules_text(self, guild: discord.Guild, channel: discord.TextChannel) -> None:
        content = "\n\n".join(split_long_message(RULES_TEXT))
        await self.ensure_managed_text_message(guild, channel, "rules_text_message_id", content)

    def get_ticket_destination_category(self, guild: discord.Guild, destination: str) -> discord.CategoryChannel | None:
        config = self.get_guild_config(guild.id)
        key_map = {
            "helper": "ticket_helper_category_id",
            "achat": "ticket_purchase_category_id",
            "staff": "ticket_staff_category_id",
        }
        key = key_map.get(destination, "ticket_helper_category_id")
        category = guild.get_channel(config.get(key)) if config.get(key) else None
        return category if isinstance(category, discord.CategoryChannel) else None

    async def apply_open_ticket_permissions(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        owner: discord.Member,
    ) -> None:
        config = self.get_guild_config(guild.id)
        helper_role = guild.get_role(config["helper_role_id"]) if config["helper_role_id"] else None
        trial_role = guild.get_role(config["trial_mod_role_id"]) if config["trial_mod_role_id"] else None
        moderator_role = guild.get_role(config["moderator_role_id"]) if config["moderator_role_id"] else None
        responsable_role = guild.get_role(config["responsable_role_id"]) if config["responsable_role_id"] else None
        admin_role = guild.get_role(config["admin_role_id"]) if config["admin_role_id"] else None
        founder_role = guild.get_role(config["founder_role_id"]) if config["founder_role_id"] else None
        archive_role = guild.get_role(config["archive_role_id"]) if config["archive_role_id"] else None
        staff_role = guild.get_role(config["staff_role_id"]) if config["staff_role_id"] else None

        await channel.set_permissions(guild.default_role, view_channel=False)
        await channel.set_permissions(
            owner,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True,
        )
        for role in (helper_role, trial_role, moderator_role, responsable_role, admin_role, founder_role, archive_role, staff_role):
            if role is None:
                continue
            await channel.set_permissions(
                role,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=role.name
                in {MODERATOR_ROLE_NAME, RESPONSABLE_ROLE_NAME, ADMIN_ROLE_NAME, FOUNDER_ROLE_NAME, AUTO_STAFF_ROLE_NAME, AUTO_ARCHIVE_ROLE_NAME},
            )

    async def apply_claimed_ticket_permissions(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        owner: discord.Member | None,
        claimer: discord.Member,
    ) -> None:
        config = self.get_guild_config(guild.id)
        helper_role = guild.get_role(config["helper_role_id"]) if config["helper_role_id"] else None
        trial_role = guild.get_role(config["trial_mod_role_id"]) if config["trial_mod_role_id"] else None
        moderator_role = guild.get_role(config["moderator_role_id"]) if config["moderator_role_id"] else None
        responsable_role = guild.get_role(config["responsable_role_id"]) if config["responsable_role_id"] else None
        admin_role = guild.get_role(config["admin_role_id"]) if config["admin_role_id"] else None
        founder_role = guild.get_role(config["founder_role_id"]) if config["founder_role_id"] else None
        archive_role = guild.get_role(config["archive_role_id"]) if config["archive_role_id"] else None
        staff_role = guild.get_role(config["staff_role_id"]) if config["staff_role_id"] else None

        await channel.set_permissions(guild.default_role, view_channel=False)
        if owner is not None:
            await channel.set_permissions(
                owner,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            )
        await channel.set_permissions(
            claimer,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_messages=True,
        )
        for role in (helper_role, trial_role):
            if role is not None:
                await channel.set_permissions(role, view_channel=False, send_messages=False, read_message_history=False)
        for role in (moderator_role, responsable_role, admin_role, founder_role, archive_role, staff_role):
            if role is None:
                continue
            await channel.set_permissions(
                role,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
            )

    async def create_ticket(self, interaction: discord.Interaction, ticket_type: str) -> None:
        guild = interaction.guild
        user = interaction.user
        if guild is None or not isinstance(user, discord.Member):
            await interaction.response.send_message("Impossible de cr?er un ticket ici.", ephemeral=True)
            return

        lock_key = (guild.id, user.id)
        if lock_key in self.pending_ticket_creations:
            await interaction.response.send_message(
                "Ton ticket est d?j? en cours de cr?ation, attends une seconde.",
                ephemeral=True,
            )
            return

        helper_category = self.get_ticket_destination_category(guild, "helper")
        archive_category = guild.get_channel(self.get_guild_config(guild.id)["archive_category_id"])
        if not isinstance(helper_category, discord.CategoryChannel) or not isinstance(archive_category, discord.CategoryChannel):
            await interaction.response.send_message(
                "Le syst?me de tickets n'est pas encore configur? correctement.",
                ephemeral=True,
            )
            return

        if len(self.get_open_tickets_for_user(guild.id, user.id)) >= 1:
            await interaction.response.send_message(
                "Tu as d?j? un ticket ouvert. Ferme-le avant d'en cr?er un autre.",
                ephemeral=True,
            )
            return

        config = self.get_guild_config(guild.id)
        helper_role = guild.get_role(config["helper_role_id"]) if config["helper_role_id"] else None
        trial_role = guild.get_role(config["trial_mod_role_id"]) if config["trial_mod_role_id"] else None

        self.pending_ticket_creations.add(lock_key)
        try:
            number = self.get_next_ticket_number(guild.id)
            channel = await guild.create_text_channel(
                name=f"{number}-{slugify_name(user.display_name)}",
                category=helper_category,
                reason=f"Cr?ation du ticket {ticket_type} par {user}",
            )
            await self.apply_open_ticket_permissions(guild, channel, user)

            store = self.get_ticket_store(guild.id)
            store["channels"][str(channel.id)] = {
                "channel_id": channel.id,
                "owner_id": user.id,
                "status": "open",
                "type": ticket_type,
                "number": number,
                "destination": "helper",
                "assigned_helper_id": None,
                "claimed_at": None,
                "transferred_by": None,
                "transfer_reason": None,
                "transfer_summary": None,
                "claimed_messages": 0,
                "last_activity_at": self.iso_now(),
                "recall_sent_at": None,
            }
            self.save_tickets()

            embed = discord.Embed(
                title="Ticket Renseignement",
                description=(
                    f"{user.mention}, ton ticket a ?t? cr?? avec succ?s.\n"
                    "Explique ta demande avec le plus de d?tails possible.\n"
                    "Un helper te r?pondra puis transf?rera le ticket si besoin."
                ),
                color=discord.Color.green(),
            )
            embed.add_field(name="Cat?gorie", value=TICKET_TYPES[ticket_type]["label"], inline=True)
            embed.add_field(name="Num?ro", value=str(number), inline=True)
            await channel.send(
                content=" ".join(
                    mention
                    for mention in (
                        user.mention,
                        helper_role.mention if helper_role else None,
                        trial_role.mention if trial_role else None,
                    )
                    if mention
                ),
                embed=embed,
                view=TicketCloseView(self),
            )
            await self.log_event(
                guild,
                "?? Ticket ouvert",
                f"{user.mention} a ouvert un ticket **{TICKET_TYPES[ticket_type]['label']}**.",
                discord.Color.green(),
                thumbnail_url=user.display_avatar.url,
                fields=[
                    ("Salon", channel.mention, True),
                    ("Num?ro", str(number), True),
                    ("Destination", "Helpers", True),
                ],
            )
            await interaction.response.send_message(f"Ton ticket a ?t? cr?? : {channel.mention}", ephemeral=True)
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

        if not self.can_close_tickets(user):
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
        if ticket.get("assigned_helper_id"):
            self.add_staff_points(guild.id, int(ticket["assigned_helper_id"]), 2)
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
        ticket["last_activity_at"] = self.iso_now()
        ticket["recall_sent_at"] = None
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

        store = self.get_giveaway_entries(interaction.guild.id)
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
        giveaway = self.get_giveaway_entries(interaction.guild.id).get(str(interaction.message.id))
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

        giveaway = self.get_giveaway_entries(interaction.guild.id).get(str(interaction.message.id))
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
        store = self.get_giveaway_entries(guild_id)
        giveaway = store.get(str(message_id))
        if giveaway is None or giveaway.get("status") != "active":
            return

        guild = self.get_guild(guild_id)
        if guild is None:
            return
        channel = guild.get_channel(giveaway["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            return

        blacklist = set(int(user_id) for user_id in self.get_giveaway_blacklist(guild_id).keys())
        eligible_participant_ids = [
            user_id
            for user_id in list(dict.fromkeys(giveaway.get("participants", [])))
            if user_id not in blacklist
        ]
        winners: list[int] = []
        forced_winner_id = giveaway.get("forced_winner_id")
        if forced_winner_id is not None:
            forced_member = guild.get_member(int(forced_winner_id))
            if forced_member is None:
                try:
                    forced_member = await guild.fetch_member(int(forced_winner_id))
                except (discord.Forbidden, discord.NotFound, discord.HTTPException, ValueError):
                    forced_member = None
            if forced_member is not None:
                winners.append(int(forced_winner_id))

        remaining_slots = max(0, int(giveaway["winners_count"]) - len(winners))
        extra_winners = await self._pick_weighted_winners(
            guild,
            eligible_participant_ids,
            remaining_slots,
            excluded=set(winners),
        )
        winners.extend(extra_winners)

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
        store = self.get_giveaway_entries(guild_id)
        giveaway = store.get(str(message_id))
        if giveaway is None:
            return []

        guild = self.get_guild(guild_id)
        if guild is None:
            return []

        blacklist = set(int(user_id) for user_id in self.get_giveaway_blacklist(guild_id).keys())
        participant_ids = [
            user_id
            for user_id in list(dict.fromkeys(giveaway.get("participants", [])))
            if user_id not in blacklist
        ]
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
        self.initialize_invite_role_baseline(guild.id)
        await self.sync_all_invite_roles(guild)
        await self.sync_all_free_access_roles(guild)
        await self.sync_all_xp_roles(guild)
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
