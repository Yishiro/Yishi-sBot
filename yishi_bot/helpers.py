from __future__ import annotations

import re
from typing import Any

import discord

from yishi_bot.constants import INVITE_ROLE_WEIGHTS

def parse_duration(value: str) -> int | None:
    match = re.fullmatch(r"(\d+)([mhd])", value.lower().strip())
    if match is None:
        return None

    amount = int(match.group(1))
    unit = match.group(2)
    if amount <= 0:
        return None
    if unit == "m":
        return amount * 60
    if unit == "h":
        return amount * 60 * 60
    return amount * 24 * 60 * 60

def split_long_message(text: str, limit: int = 1900) -> list[str]:
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    current = ""
    for block in text.split("\n\n"):
        candidate = block if not current else f"{current}\n\n{block}"
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        current = block

    if current:
        parts.append(current)
    return parts

def default_config() -> dict[str, Any]:
    return {
        "staff_role_id": None,
        "archive_role_id": None,
        "ticket_category_id": None,
        "archive_category_id": None,
        "welcome_channel_id": None,
        "logs_channel_id": None,
        "transcript_logs_channel_id": None,
        "gacha_spin_channel_id": None,
        "gacha_winner_channel_id": None,
        "gacha_logs_channel_id": None,
        "sales_channel_id": None,
        "sales_category_id": None,
        "sales_review_channel_id": None,
        "promo_channel_id": None,
        "rules_role_id": None,
        "rules_message_id": None,
        "rules_channel_id": None,
    }

def can_moderate(
    actor: discord.Member,
    target: discord.Member,
    bot_member: discord.Member,
) -> str | None:
    if target == actor:
        return "Tu ne peux pas te modérer toi-même."
    if target == bot_member:
        return "Je ne peux pas me modérer moi-même."
    if target.top_role >= actor.top_role and actor != actor.guild.owner:
        return "Tu ne peux pas modérer ce membre car son rôle est égal ou supérieur au tien."
    if target.top_role >= bot_member.top_role:
        return "Je ne peux pas modérer ce membre car son rôle est trop élevé."
    return None

def get_member_giveaway_weight(member: discord.Member) -> float:
    weight = 1.0
    for role in member.roles:
        weight = max(weight, INVITE_ROLE_WEIGHTS.get(role.name, 1.0))

    if member.premium_since is not None or discord.utils.get(member.roles, name="Server Booster"):
        weight += 1.0
    return weight

def default_gacha_store() -> dict[str, Any]:
    return {
        "inventories": {},
        "history": [],
        "grant_history": [],
        "member_notes": {},
        "next_claim_number": 1,
    }

def default_promo_store() -> dict[str, Any]:
    return {
        "promotions": [],
        "next_id": 1,
        "last_auto_post_week": None,
    }

def merge_missing_defaults(target: dict[str, Any], defaults: dict[str, Any]) -> bool:
    changed = False
    for key, value in defaults.items():
        if key not in target:
            target[key] = value
            changed = True
    return changed
