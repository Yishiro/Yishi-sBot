from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from functools import wraps
from threading import Thread
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from flask import Flask, Response, flash, redirect, render_template, request, session, url_for

from yishi_bot.constants import FREE_INVITE_REQUIREMENT, XP_GRADE_LEVELS
from yishi_bot.helpers import parse_duration
from yishi_bot.storage import DATABASE_URL
from yishi_bot.views import GiveawayView


app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("PANEL_SECRET_KEY") or os.environ.get("DISCORD_TOKEN") or "yishi-panel-dev-secret"

_bot = None
try:
    _paris_tz = ZoneInfo("Europe/Paris")
except ZoneInfoNotFoundError:
    _paris_tz = timezone.utc
_panel_started_at = datetime.now(tz=_paris_tz)

CONFIG_FIELDS = (
    ("staff_role_id", "Role staff"),
    ("archive_role_id", "Role archive"),
    ("helper_role_id", "Role helper"),
    ("trial_mod_role_id", "Role modo test"),
    ("moderator_role_id", "Role modo"),
    ("responsable_role_id", "Role responsable"),
    ("admin_role_id", "Role admin"),
    ("founder_role_id", "Role fondateur"),
    ("free_access_role_id", "Role acces free"),
    ("welcome_channel_id", "Salon bienvenue"),
    ("announcements_channel_id", "Salon annonces"),
    ("shop_channel_id", "Salon shop"),
    ("logs_channel_id", "Salon logs staff"),
    ("transcript_logs_channel_id", "Salon logs transcript"),
    ("gacha_spin_channel_id", "Salon gacha spin"),
    ("gacha_winner_channel_id", "Salon gacha winner"),
    ("gacha_logs_channel_id", "Salon gacha logs"),
    ("giveaways_channel_id", "Salon giveaways"),
    ("sales_channel_id", "Salon ventes"),
    ("sales_review_channel_id", "Salon validation ventes"),
    ("promo_channel_id", "Salon promotions"),
    ("staff_prices_channel_id", "Salon tarifs staff"),
    ("free_netflix_channel_id", "Salon netflix free"),
    ("free_crunchyroll_channel_id", "Salon crunchyroll free"),
    ("daily_level_channel_id", "Salon message progression"),
    ("daily_sales_rules_channel_id", "Salon reglement ventes auto"),
)

CONFIG_GROUPS = (
    (
        "Roles",
        (
            "staff_role_id",
            "archive_role_id",
            "helper_role_id",
            "trial_mod_role_id",
            "moderator_role_id",
            "responsable_role_id",
            "admin_role_id",
            "founder_role_id",
            "free_access_role_id",
        ),
    ),
    (
        "Salons publics",
        (
            "welcome_channel_id",
            "announcements_channel_id",
            "shop_channel_id",
            "gacha_spin_channel_id",
            "gacha_winner_channel_id",
            "giveaways_channel_id",
            "sales_channel_id",
            "promo_channel_id",
            "free_netflix_channel_id",
            "free_crunchyroll_channel_id",
            "daily_level_channel_id",
            "daily_sales_rules_channel_id",
        ),
    ),
    (
        "Salons staff",
        (
            "logs_channel_id",
            "transcript_logs_channel_id",
            "gacha_logs_channel_id",
            "sales_review_channel_id",
            "staff_prices_channel_id",
        ),
    ),
)

LEVEL_FEATURE_RULES = (
    ("Aucun bonus vocal", 0),
    ("Lock / unlock vocal", XP_GRADE_LEVELS["Actif"]),
    ("Limiter les places", XP_GRADE_LEVELS["Actif"]),
    ("Stream autorise", XP_GRADE_LEVELS["Actif"]),
    ("Inviter des membres", XP_GRADE_LEVELS["Confirme"]),
    ("Kick depuis le vocal", XP_GRADE_LEVELS["Confirme"]),
    ("Camera autorisee", XP_GRADE_LEVELS["Confirme"]),
    ("Renommer le vocal", XP_GRADE_LEVELS["Elite"]),
    ("Transferer le vocal", XP_GRADE_LEVELS["Legende"]),
)

QUICK_ACTIONS = (
    ("sync_commands", "Resync slash commands"),
    ("sync_xp_roles", "Sync roles XP"),
    ("sync_invite_roles", "Sync roles invitations"),
    ("sync_free_roles", "Sync acces free"),
    ("send_level_now", "Envoyer message progression"),
    ("send_sales_now", "Envoyer reglement ventes"),
)


def attach_bot(bot: Any) -> None:
    global _bot
    _bot = bot


def get_bot() -> Any:
    return _bot


def panel_username() -> str:
    return os.environ.get("PANEL_USERNAME", "owner")


def panel_password() -> str:
    return os.environ.get("PANEL_PASSWORD", "")


def panel_enabled() -> bool:
    return bool(panel_password().strip())


def is_authenticated() -> bool:
    return session.get("panel_authenticated") is True


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_authenticated():
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def parse_int_or_none(value: str) -> int | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def parse_any_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=_paris_tz)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return dt.replace(tzinfo=_paris_tz)
            return dt.astimezone(_paris_tz)
        except ValueError:
            return None
    return None


def iso_to_local(value: str | None) -> str:
    dt = parse_any_datetime(value)
    if dt is None:
        return "-"
    return dt.strftime("%d/%m/%Y %H:%M")


def role_name_for(guild: Any | None, role_id: Any) -> str:
    if guild is None or not role_id:
        return "-"
    role = guild.get_role(int(role_id))
    return role.name if role is not None else f"Role introuvable ({role_id})"


def channel_name_for(guild: Any | None, channel_id: Any) -> str:
    if guild is None or not channel_id:
        return "-"
    channel = guild.get_channel(int(channel_id))
    return f"#{channel.name}" if channel is not None else f"Salon introuvable ({channel_id})"


def resolve_config_value(guild: Any | None, key: str, value: Any) -> str:
    if key.endswith("_role_id"):
        return role_name_for(guild, value)
    if key.endswith("_channel_id"):
        return channel_name_for(guild, value)
    return str(value) if value not in (None, "") else "-"


def config_sections_for(guild: Any | None, config: dict[str, Any]) -> list[dict[str, Any]]:
    labels = dict(CONFIG_FIELDS)
    sections: list[dict[str, Any]] = []
    for title, keys in CONFIG_GROUPS:
        fields = []
        for key in keys:
            fields.append(
                {
                    "key": key,
                    "label": labels.get(key, key),
                    "value": config.get(key, "") or "",
                    "current": resolve_config_value(guild, key, config.get(key)),
                }
            )
        sections.append({"title": title, "fields": fields})
    return sections


def build_quick_action_items() -> list[dict[str, str]]:
    return [{"key": key, "label": label} for key, label in QUICK_ACTIONS]


def json_download(data: dict[str, Any], filename: str) -> Response:
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    return Response(
        payload,
        mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def available_guilds() -> list[Any]:
    bot = get_bot()
    if bot is None:
        return []
    return sorted(bot.guilds, key=lambda guild: guild.name.lower())


def selected_guild() -> Any | None:
    guilds = available_guilds()
    if not guilds:
        return None

    requested = request.values.get("guild_id", "").strip()
    if requested.isdigit():
        guild = get_bot().get_guild(int(requested))
        if guild is not None:
            return guild
    return guilds[0]


def get_dashboard_stats(guild: Any | None) -> dict[str, Any]:
    bot = get_bot()
    if bot is None or guild is None:
        return {
            "tickets_open": 0,
            "sales_active": 0,
            "sales_pending": 0,
            "giveaways_active": 0,
            "promotions_total": 0,
            "tracked_members": 0,
            "free_members": 0,
            "staff_points_total": 0,
        }

    ticket_store = bot.get_ticket_store(guild.id)
    sale_store = bot.get_sale_store(guild.id)
    giveaway_store = bot.get_giveaway_store(guild.id)
    promo_store = bot.get_promo_store(guild.id)
    level_store = bot.get_level_store(guild.id)
    invite_store = bot.get_invite_store(guild.id)
    config = bot.get_guild_config(guild.id)
    free_role = guild.get_role(config.get("free_access_role_id")) if config.get("free_access_role_id") else None
    free_members = 0
    if free_role is not None:
        free_members = sum(1 for member in guild.members if free_role in member.roles)
    staff_points_total = sum(int(value) for value in ticket_store.get("staff_points", {}).values())

    return {
        "tickets_open": len(ticket_store.get("channels", {})),
        "sales_active": len(sale_store.get("messages", {})),
        "sales_pending": len(sale_store.get("reviews", {})),
        "giveaways_active": len(giveaway_store.get("giveaways", {})),
        "promotions_total": len(promo_store.get("promotions", [])),
        "tracked_members": len(level_store.get("members", {})),
        "free_members": free_members or sum(1 for count in invite_store.get("weekly_counts", {}).values() if int(count) >= FREE_INVITE_REQUIREMENT),
        "staff_points_total": staff_points_total,
    }


def get_guild_overview(guild: Any | None) -> dict[str, Any]:
    bot = get_bot()
    if bot is None or guild is None:
        return {
            "members": 0,
            "humans": 0,
            "bots": 0,
            "text_channels": 0,
            "voice_channels": 0,
            "roles": 0,
        }
    humans = sum(1 for member in guild.members if not member.bot)
    bots = sum(1 for member in guild.members if member.bot)
    return {
        "members": guild.member_count or len(guild.members),
        "humans": humans,
        "bots": bots,
        "text_channels": len(guild.text_channels),
        "voice_channels": len(guild.voice_channels),
        "roles": len(guild.roles),
    }


def level_rows_for(guild: Any | None) -> list[dict[str, Any]]:
    bot = get_bot()
    if bot is None or guild is None:
        return []
    rows: list[dict[str, Any]] = []
    for member_id, _xp in bot.get_level_ranking(guild.id):
        member = guild.get_member(member_id)
        if member is None or member.bot:
            continue
        stats = bot.get_member_level_stats(guild.id, member_id)
        rows.append(
            {
                "member_id": member_id,
                "member_name": member.display_name,
                "level": stats["level"],
                "grade": stats["grade"],
                "xp": stats["xp"],
                "messages": stats["message_count"],
                "voice": bot.format_voice_duration(stats["voice_seconds"]),
                "rank": bot.get_member_rank_position(guild.id, member_id),
            }
        )
    return rows


def level_detail_for(guild: Any | None, member_id: int | None) -> dict[str, Any] | None:
    bot = get_bot()
    if bot is None or guild is None or member_id is None:
        return None
    member = guild.get_member(member_id)
    if member is None:
        return None
    stats = bot.get_member_level_stats(guild.id, member_id)
    rank = bot.get_member_rank_position(guild.id, member_id)
    unlocked = [label for label, required in LEVEL_FEATURE_RULES if stats["level"] >= required]
    locked = [f"{label} (niveau {required}+)" for label, required in LEVEL_FEATURE_RULES if stats["level"] < required]
    return {
        "member": member,
        "stats": stats,
        "rank": rank,
        "unlocked": unlocked,
        "locked": locked,
        "xp_role_name": bot.get_member_grade(stats["level"]),
        "voice_text": bot.format_voice_duration(stats["voice_seconds"]),
    }


def invite_rows_for(guild: Any | None) -> list[dict[str, Any]]:
    bot = get_bot()
    if bot is None or guild is None:
        return []
    store = bot.get_invite_store(guild.id)
    config = bot.get_guild_config(guild.id)
    free_role = guild.get_role(config.get("free_access_role_id")) if config.get("free_access_role_id") else None
    all_user_ids = set(store.get("counts", {}).keys()) | set(store.get("weekly_counts", {}).keys())
    rows: list[dict[str, Any]] = []
    for user_id in all_user_ids:
        member = guild.get_member(int(user_id))
        total = int(store.get("counts", {}).get(user_id, 0))
        weekly = int(store.get("weekly_counts", {}).get(user_id, 0))
        if total <= 0 and weekly <= 0:
            continue
        rows.append(
            {
                "member_id": int(user_id),
                "member_name": member.display_name if member else user_id,
                "total": total,
                "weekly": weekly,
                "from_now": bot.get_invite_role_count_from_now(guild.id, int(user_id)),
                "free_access": (
                    "Oui"
                    if member is not None and free_role is not None and free_role in member.roles
                    else ("Oui" if weekly >= FREE_INVITE_REQUIREMENT else "Non")
                ),
            }
        )
    rows.sort(key=lambda item: (item["weekly"], item["total"]), reverse=True)
    return rows


def promotion_stats_for(guild: Any | None) -> dict[str, int]:
    bot = get_bot()
    if bot is None or guild is None:
        return {"total": 0, "active": 0, "inactive": 0}
    promos = bot.get_promo_store(guild.id).get("promotions", [])
    active = sum(1 for promo in promos if promo.get("active", True))
    return {"total": len(promos), "active": active, "inactive": len(promos) - active}


def giveaway_stats_for(guild: Any | None) -> dict[str, int]:
    bot = get_bot()
    if bot is None or guild is None:
        return {"active": 0, "ended": 0, "blacklist": 0, "forced": 0}
    entries = bot.get_giveaway_entries(guild.id)
    active = sum(1 for item in entries.values() if item.get("status") == "active")
    ended = sum(1 for item in entries.values() if item.get("status") != "active")
    forced = sum(1 for item in entries.values() if item.get("forced_winner_id"))
    blacklist = len(bot.get_giveaway_blacklist(guild.id))
    return {"active": active, "ended": ended, "blacklist": blacklist, "forced": forced}


def gacha_stats_for(guild: Any | None) -> dict[str, int]:
    bot = get_bot()
    if bot is None:
        return {"members": 0, "basic": 0, "advanced": 0, "deluxe": 0, "history": 0, "notes": 0}
    inventories = bot.gacha_data.get("inventories", {})
    note_count = sum(len(value) for value in bot.gacha_data.get("member_notes", {}).values())
    return {
        "members": sum(1 for inv in inventories.values() if sum(int(inv.get(name, 0)) for name in ("basic", "advanced", "deluxe")) > 0),
        "basic": sum(int(inv.get("basic", 0)) for inv in inventories.values()),
        "advanced": sum(int(inv.get("advanced", 0)) for inv in inventories.values()),
        "deluxe": sum(int(inv.get("deluxe", 0)) for inv in inventories.values()),
        "history": len(bot.gacha_data.get("grant_history", [])),
        "notes": note_count,
    }


def ticket_stats_for(guild: Any | None) -> dict[str, int]:
    bot = get_bot()
    if bot is None or guild is None:
        return {"open": 0, "archived": 0, "helpers": 0, "staff_points": 0}
    channels = bot.get_ticket_store(guild.id).get("channels", {})
    open_count = sum(1 for ticket in channels.values() if ticket.get("status") != "archived")
    archived_count = sum(1 for ticket in channels.values() if ticket.get("status") == "archived")
    helper_count = sum(1 for ticket in channels.values() if ticket.get("assigned_helper_id"))
    staff_points = sum(int(value) for value in bot.get_ticket_store(guild.id).get("staff_points", {}).values())
    return {"open": open_count, "archived": archived_count, "helpers": helper_count, "staff_points": staff_points}


def sales_stats_for(guild: Any | None) -> dict[str, int]:
    bot = get_bot()
    if bot is None or guild is None:
        return {"pending": 0, "active": 0, "reserved": 0, "channels": 0}
    store = bot.get_sale_store(guild.id)
    messages = store.get("messages", {})
    return {
        "pending": len(store.get("reviews", {})),
        "active": sum(1 for sale in messages.values() if sale.get("status") != "reserved"),
        "reserved": sum(1 for sale in messages.values() if sale.get("status") == "reserved"),
        "channels": len(store.get("channels", {})),
    }


def invite_stats_for(guild: Any | None) -> dict[str, int]:
    bot = get_bot()
    if bot is None or guild is None:
        return {"tracked": 0, "weekly_ready": 0, "from_now_total": 0}
    rows = invite_rows_for(guild)
    return {
        "tracked": len(rows),
        "weekly_ready": sum(1 for row in rows if row["weekly"] >= FREE_INVITE_REQUIREMENT),
        "from_now_total": sum(int(row["from_now"]) for row in rows),
    }


def logs_types_for(guild: Any | None) -> list[str]:
    entries = activity_feed_for(guild, limit=200)
    return sorted({entry["type"] for entry in entries})


def member_hub_data(guild: Any | None, member_id: int | None) -> dict[str, Any] | None:
    bot = get_bot()
    if bot is None or guild is None or member_id is None:
        return None
    member = guild.get_member(member_id)
    if member is None:
        return None

    level_stats = bot.get_member_level_stats(guild.id, member.id)
    invite_store = bot.get_invite_store(guild.id)
    total_invites = int(invite_store.get("counts", {}).get(str(member.id), 0))
    weekly_invites = int(invite_store.get("weekly_counts", {}).get(str(member.id), 0))
    from_now_invites = bot.get_invite_role_count_from_now(guild.id, member.id)
    inventory = bot.get_gacha_inventory(member.id)
    notes = bot.get_member_notes(member.id)
    history = bot.get_member_grant_history(member.id)
    open_tickets = bot.get_open_tickets_for_user(guild.id, member.id)
    archived_tickets = [
        ticket
        for ticket in bot.get_ticket_store(guild.id)["channels"].values()
        if ticket.get("owner_id") == member.id and ticket.get("status") == "archived"
    ]
    blacklist = bot.get_giveaway_blacklist(guild.id).get(str(member.id))
    sale_store = bot.get_sale_store(guild.id)
    selling = [sale for sale in sale_store.get("messages", {}).values() if int(sale.get("seller_id", 0)) == member.id]
    buying = [sale for sale in sale_store.get("messages", {}).values() if int(sale.get("buyer_id", 0)) == member.id]
    giveaway_entries = bot.get_giveaway_entries(guild.id)
    giveaway_participations = []
    giveaway_wins = []
    for giveaway in giveaway_entries.values():
        participants = [int(item) for item in giveaway.get("participants", [])]
        winners = [int(item) for item in giveaway.get("winners", [])]
        if member.id in participants:
            giveaway_participations.append(giveaway)
        if member.id in winners:
            giveaway_wins.append(giveaway)
    free_role = None
    config = bot.get_guild_config(guild.id)
    if config.get("free_access_role_id"):
        free_role = guild.get_role(config["free_access_role_id"])
    recent_member_logs = [
        entry
        for entry in activity_feed_for(guild, limit=150)
        if str(member.id) in entry["detail"] or member.display_name.lower() in entry["detail"].lower()
    ][:12]

    return {
        "member": member,
        "roles": [role.name for role in member.roles if not role.is_default()],
        "joined_at": iso_to_local(member.joined_at.isoformat()) if member.joined_at else "-",
        "created_at": iso_to_local(member.created_at.isoformat()) if member.created_at else "-",
        "level": level_stats,
        "level_rank": bot.get_member_rank_position(guild.id, member.id),
        "voice_text": bot.format_voice_duration(level_stats["voice_seconds"]),
        "invites": {
            "total": total_invites,
            "weekly": weekly_invites,
            "from_now": from_now_invites,
            "free_access": bool(free_role is not None and free_role in member.roles) or weekly_invites >= FREE_INVITE_REQUIREMENT,
        },
        "gacha": {
            "inventory": inventory,
            "notes": list(reversed(notes[-10:])),
            "history": list(reversed(history[-10:])),
        },
        "tickets": open_tickets,
        "tickets_archived": list(reversed(archived_tickets[-10:])),
        "sales": {
            "selling": selling,
            "buying": buying,
        },
        "giveaways": {
            "participations": giveaway_participations,
            "wins": giveaway_wins,
        },
        "giveaway_blacklist": blacklist,
        "staff_points": bot.get_staff_point_total(guild.id, member.id),
        "recent_logs": recent_member_logs,
    }


def activity_feed_for(guild: Any | None, *, limit: int = 40) -> list[dict[str, Any]]:
    bot = get_bot()
    if bot is None or guild is None:
        return []

    entries: list[dict[str, Any]] = []

    ticket_store = bot.get_ticket_store(guild.id)
    for channel_id, ticket in ticket_store.get("channels", {}).items():
        entries.append(
            {
                "type": "Ticket",
                "title": f"{ticket.get('type', 'ticket').title()} • {ticket.get('status', 'open')}",
                "detail": f"Salon #{channel_id} • Owner {ticket.get('owner_id', '-')}",
                "when": parse_any_datetime(ticket.get("claimed_at")) or parse_any_datetime(ticket.get("created_at")),
            }
        )

    sale_store = bot.get_sale_store(guild.id)
    for review_message_id, sale in sale_store.get("reviews", {}).items():
        entries.append(
            {
                "type": "Vente",
                "title": f"Validation en attente • {sale.get('product', '-')}",
                "detail": f"Review {review_message_id} • vendeur {sale.get('seller_id', '-')}",
                "when": parse_any_datetime(sale.get("created_at")),
            }
        )
    for message_id, sale in sale_store.get("messages", {}).items():
        entries.append(
            {
                "type": "Vente",
                "title": f"{sale.get('status', 'active').title()} • {sale.get('product', '-')}",
                "detail": f"Annonce {message_id} • vendeur {sale.get('seller_id', '-')}",
                "when": parse_any_datetime(sale.get("created_at")),
            }
        )

    for item in bot.gacha_data.get("grant_history", []):
        entries.append(
            {
                "type": "Gacha",
                "title": f"{item.get('action', 'add').title()} {item.get('spin_type', '-')} x{item.get('quantity', 0)}",
                "detail": f"{item.get('target_name', item.get('target_id', '-'))} • {item.get('actor_name', '-')}",
                "when": parse_any_datetime(item.get("timestamp")),
            }
        )

    for item in bot.get_promo_store(guild.id).get("promotions", []):
        entries.append(
            {
                "type": "Promo",
                "title": item.get("title", "Promotion"),
                "detail": f"Priorite {item.get('priority', 1)} • {'Active' if item.get('active', True) else 'Off'}",
                "when": parse_any_datetime(item.get("last_posted_at")),
            }
        )

    giveaway_entries = bot.get_giveaway_entries(guild.id)
    for giveaway in giveaway_entries.values():
        entries.append(
            {
                "type": "Giveaway",
                "title": f"{giveaway.get('status', 'active').title()} • {giveaway.get('prize', '-')}",
                "detail": f"Message {giveaway.get('message_id', '-')} • {len(giveaway.get('participants', []))} participants",
                "when": parse_any_datetime(giveaway.get("end_at")),
            }
        )

    for member_id, data in bot.get_giveaway_blacklist(guild.id).items():
        entries.append(
            {
                "type": "Blacklist",
                "title": f"Membre {member_id} blacklist giveaway",
                "detail": data.get("reason", "Aucune raison"),
                "when": parse_any_datetime(data.get("added_at")),
            }
        )

    entries = [entry for entry in entries if entry["when"] is not None]
    entries.sort(key=lambda item: item["when"], reverse=True)
    return [
        {
            **entry,
            "when_text": iso_to_local(entry["when"].isoformat()),
        }
        for entry in entries[:limit]
    ]


def filtered_activity_feed_for(guild: Any | None, *, limit: int = 120, entry_type: str = "", query: str = "") -> list[dict[str, Any]]:
    entries = activity_feed_for(guild, limit=limit)
    if entry_type:
        entries = [entry for entry in entries if entry["type"] == entry_type]
    if query:
        lowered = query.lower()
        entries = [
            entry
            for entry in entries
            if lowered in entry["title"].lower() or lowered in entry["detail"].lower()
        ]
    return entries


def staff_rows_for(guild: Any | None) -> list[dict[str, Any]]:
    bot = get_bot()
    if bot is None or guild is None:
        return []
    store = bot.get_ticket_store(guild.id)
    channels = store.get("channels", {})
    points_store = store.get("staff_points", {})
    active_claims: dict[int, int] = {}
    archived_claims: dict[int, int] = {}
    transferred: dict[int, int] = {}

    for ticket in channels.values():
        helper_id = ticket.get("assigned_helper_id")
        if helper_id:
            if ticket.get("status") == "archived":
                archived_claims[int(helper_id)] = archived_claims.get(int(helper_id), 0) + 1
            else:
                active_claims[int(helper_id)] = active_claims.get(int(helper_id), 0) + 1
        transfer_by = ticket.get("transferred_by")
        if transfer_by:
            transferred[int(transfer_by)] = transferred.get(int(transfer_by), 0) + 1

    tracked_ids = set(int(user_id) for user_id in points_store.keys()) | set(active_claims.keys()) | set(archived_claims.keys()) | set(transferred.keys())
    rows: list[dict[str, Any]] = []
    for user_id in tracked_ids:
        member = guild.get_member(user_id)
        rows.append(
            {
                "member_id": user_id,
                "member_name": member.display_name if member else str(user_id),
                "points": int(points_store.get(str(user_id), 0)),
                "active_claims": active_claims.get(user_id, 0),
                "resolved_tickets": archived_claims.get(user_id, 0),
                "transfers": transferred.get(user_id, 0),
            }
        )
    rows.sort(key=lambda item: (item["points"], item["resolved_tickets"], item["active_claims"]), reverse=True)
    return rows


def run_quick_action(bot: Any, guild: Any, action: str) -> tuple[str, str]:
    if action == "sync_commands":
        ok, message = run_bot_coroutine(bot.sync_commands_once(force=True), timeout=90)
        return ("success" if ok else "error", "Commandes resynchronisees." if ok else f"Echec: {message}")
    if action == "sync_xp_roles":
        ok, message = run_bot_coroutine(bot.sync_all_xp_roles(guild), timeout=180)
        return ("success" if ok else "error", "Roles XP synchronises." if ok else f"Echec: {message}")
    if action == "sync_invite_roles":
        ok, message = run_bot_coroutine(bot.sync_all_invite_roles(guild), timeout=180)
        return ("success" if ok else "error", "Roles invitations synchronises." if ok else f"Echec: {message}")
    if action == "sync_free_roles":
        ok, message = run_bot_coroutine(bot.sync_all_free_access_roles(guild), timeout=180)
        return ("success" if ok else "error", "Acces free synchronises." if ok else f"Echec: {message}")
    if action == "send_level_now":
        async def _send_level_now() -> None:
            channel = guild.get_channel(bot.get_daily_level_channel_id(guild.id))
            if channel is None:
                raise RuntimeError("Salon progression introuvable.")
            await channel.send(bot.build_daily_level_message(guild.id))

        ok, message = run_bot_coroutine(_send_level_now(), timeout=60)
        return ("success" if ok else "error", "Message progression envoye." if ok else f"Echec: {message}")
    if action == "send_sales_now":
        async def _send_sales_now() -> None:
            channel = guild.get_channel(bot.get_daily_sales_rules_channel_id(guild.id))
            if channel is None:
                raise RuntimeError("Salon ventes introuvable.")
            await channel.send(embed=bot.build_sales_rules_embed())

        ok, message = run_bot_coroutine(_send_sales_now(), timeout=60)
        return ("success" if ok else "error", "Reglement ventes envoye." if ok else f"Echec: {message}")
    return ("error", "Action inconnue.")


def panel_context(active_page: str) -> dict[str, Any]:
    guild = selected_guild()
    bot = get_bot()
    now_paris = datetime.now(tz=_paris_tz)
    return {
        "active_page": active_page,
        "guilds": available_guilds(),
        "selected_guild": guild,
        "bot_online": bool(bot and not bot.is_closed()),
        "panel_enabled": panel_enabled(),
        "panel_started_at": _panel_started_at,
        "now_paris": now_paris,
    }


def run_bot_coroutine(coro: Any, *, timeout: int = 20) -> tuple[bool, str]:
    bot = get_bot()
    if bot is None or getattr(bot, "loop", None) is None:
        return False, "Bot indisponible."
    future = asyncio.run_coroutine_threadsafe(coro, bot.loop)
    try:
        future.result(timeout=timeout)
    except Exception as exc:
        return False, str(exc)
    return True, "Action executee."


@app.route("/health")
def health() -> str:
    return "ok"


@app.route("/")
def home():
    if is_authenticated():
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if not panel_enabled():
            flash("Configure d'abord PANEL_PASSWORD sur le VPS.", "error")
        else:
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if username == panel_username() and password == panel_password():
                session["panel_authenticated"] = True
                return redirect(url_for("dashboard"))
            flash("Identifiants invalides.", "error")

    return render_template("login.html", **panel_context("login"))


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    guild = selected_guild()
    bot = get_bot()
    if request.method == "POST":
        if bot is None or guild is None:
            flash("Bot ou serveur indisponible.", "error")
        else:
            category, message = run_quick_action(bot, guild, request.form.get("action", ""))
            flash(message, category)
        return redirect(url_for("dashboard", guild_id=guild.id if guild else None))
    stats = get_dashboard_stats(guild)
    recent_promos = []
    if bot is not None and guild is not None:
        recent_promos = sorted(
            bot.get_promo_store(guild.id).get("promotions", []),
            key=lambda promo: int(promo.get("queue_position", promo["id"])),
        )[:5]
    return render_template(
        "dashboard.html",
        stats=stats,
        recent_promos=recent_promos,
        overview=get_guild_overview(guild),
        quick_actions=build_quick_action_items(),
        recent_activity=activity_feed_for(guild, limit=8),
        ticket_stats=ticket_stats_for(guild),
        sales_stats=sales_stats_for(guild),
        giveaway_stats=giveaway_stats_for(guild),
        gacha_stats=gacha_stats_for(guild),
        invite_stats=invite_stats_for(guild),
        promo_stats=promotion_stats_for(guild),
        **panel_context("dashboard"),
    )


@app.route("/config", methods=["GET", "POST"])
@login_required
def config_page():
    bot = get_bot()
    guild = selected_guild()
    if bot is None or guild is None:
        flash("Bot ou serveur indisponible.", "error")
        return render_template("config.html", config_sections=[], config={}, **panel_context("config"))

    config = bot.get_guild_config(guild.id)
    if request.method == "POST":
        for key, _label in CONFIG_FIELDS:
            value = parse_int_or_none(request.form.get(key, ""))
            config[key] = value
        bot.save_config()
        flash("Configuration enregistree.", "success")
        return redirect(url_for("config_page", guild_id=guild.id))

    return render_template(
        "config.html",
        config_sections=config_sections_for(guild, config),
        config=config,
        **panel_context("config"),
    )


@app.route("/auto-messages", methods=["GET", "POST"])
@login_required
def auto_messages():
    bot = get_bot()
    guild = selected_guild()
    if bot is None or guild is None:
        flash("Bot ou serveur indisponible.", "error")
        return render_template("auto_messages.html", auto_config={}, sales_preview=None, **panel_context("auto_messages"))

    config = bot.get_guild_config(guild.id)
    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "save":
            config["auto_level_message_enabled"] = request.form.get("auto_level_message_enabled") == "on"
            config["auto_sales_rules_enabled"] = request.form.get("auto_sales_rules_enabled") == "on"
            config["daily_level_channel_id"] = parse_int_or_none(request.form.get("daily_level_channel_id", "")) or config.get("daily_level_channel_id")
            config["daily_sales_rules_channel_id"] = parse_int_or_none(request.form.get("daily_sales_rules_channel_id", "")) or config.get("daily_sales_rules_channel_id")
            config["daily_level_message"] = request.form.get("daily_level_message", "").strip()
            bot.save_config()
            flash("Messages automatiques mis a jour.", "success")
        elif action in {item[0] for item in QUICK_ACTIONS}:
            category, message = run_quick_action(bot, guild, action)
            flash(message, category)

        return redirect(url_for("auto_messages", guild_id=guild.id))

    auto_config = {
        "auto_level_message_enabled": config.get("auto_level_message_enabled", True),
        "auto_sales_rules_enabled": config.get("auto_sales_rules_enabled", True),
        "daily_level_channel_id": bot.get_daily_level_channel_id(guild.id),
        "daily_sales_rules_channel_id": bot.get_daily_sales_rules_channel_id(guild.id),
        "daily_level_message": bot.get_daily_level_message_text(guild.id),
    }
    return render_template(
        "auto_messages.html",
        auto_config=auto_config,
        sales_preview=bot.build_sales_rules_embed(),
        **panel_context("auto_messages"),
    )


@app.route("/promotions", methods=["GET", "POST"])
@login_required
def promotions():
    bot = get_bot()
    guild = selected_guild()
    if bot is None or guild is None:
        flash("Bot ou serveur indisponible.", "error")
        return render_template("promotions.html", promotions=[], **panel_context("promotions"))

    store = bot.get_promo_store(guild.id)
    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "add":
            title = request.form.get("title", "").strip()
            content = request.form.get("content", "").strip()
            try:
                priority = max(1, min(5, int(request.form.get("priority", "1"))))
            except ValueError:
                priority = 1
            if not title or not content:
                flash("Titre et texte obligatoires.", "error")
            else:
                promo_id = int(store["next_id"])
                max_queue = max(
                    (int(promo.get("queue_position", promo["id"])) for promo in store["promotions"]),
                    default=0,
                )
                store["promotions"].append(
                    {
                        "id": promo_id,
                        "title": title,
                        "content": content,
                        "priority": priority,
                        "active": True,
                        "queue_position": max_queue + 1,
                        "last_posted_at": None,
                    }
                )
                store["next_id"] = promo_id + 1
                bot.save_promos()
                flash("Promotion ajoutee.", "success")
        elif action == "toggle":
            promo_id = request.form.get("promo_id", "").strip()
            for promo in store["promotions"]:
                if str(promo["id"]) == promo_id:
                    promo["active"] = not promo.get("active", True)
                    bot.save_promos()
                    flash("Statut de la promotion mis a jour.", "success")
                    break
        elif action == "delete":
            promo_id = request.form.get("promo_id", "").strip()
            store["promotions"] = [promo for promo in store["promotions"] if str(promo["id"]) != promo_id]
            bot.save_promos()
            flash("Promotion supprimee.", "success")
        elif action == "post_next":
            async def _post_next() -> None:
                promo = bot.select_next_promo(guild.id)
                if promo is None:
                    raise RuntimeError("Aucune promotion active a publier.")
                message = await bot.post_promo(guild, promo, automatic=False)
                if message is None:
                    raise RuntimeError("Salon promotions introuvable.")

            ok, message = run_bot_coroutine(_post_next(), timeout=60)
            flash("Promotion publiee." if ok else f"Echec: {message}", "success" if ok else "error")

        return redirect(url_for("promotions", guild_id=guild.id))

    promotions_list = sorted(
        store.get("promotions", []),
        key=lambda promo: (
            -int(promo.get("priority", 1)),
            int(promo.get("queue_position", promo["id"])),
        ),
    )
    return render_template(
        "promotions.html",
        promotions=promotions_list,
        promo_stats=promotion_stats_for(guild),
        **panel_context("promotions"),
    )


@app.route("/tickets", methods=["GET", "POST"])
@login_required
def tickets_page():
    bot = get_bot()
    guild = selected_guild()
    if bot is None or guild is None:
        flash("Bot ou serveur indisponible.", "error")
        return render_template("tickets_panel.html", open_tickets=[], archived_tickets=[], **panel_context("tickets"))

    if request.method == "POST":
        action = request.form.get("action", "")
        channel_id = parse_int_or_none(request.form.get("channel_id", ""))
        if action == "reset":
            ok, message = run_bot_coroutine(bot.owner_reset_tickets(guild.id), timeout=120)
            flash("Tous les tickets ont ete supprimes et le compteur repart de zero." if ok else f"Echec: {message}", "success" if ok else "error")
            return redirect(url_for("tickets_page", guild_id=guild.id))
        if channel_id is None:
            flash("ID de ticket invalide.", "error")
        elif action == "archive":
            ok, message = run_bot_coroutine(bot.owner_archive_ticket(guild.id, channel_id), timeout=60)
            flash("Ticket archive." if ok else f"Echec: {message}", "success" if ok else "error")
        elif action == "reopen":
            ok, message = run_bot_coroutine(bot.owner_reopen_ticket(guild.id, channel_id), timeout=60)
            flash("Ticket reouvert." if ok else f"Echec: {message}", "success" if ok else "error")
        return redirect(url_for("tickets_page", guild_id=guild.id))

    store = bot.get_ticket_store(guild.id).get("channels", {})
    ticket_filter = request.args.get("filter", "").strip().lower()
    search_query = request.args.get("q", "").strip().lower()
    open_tickets: list[dict[str, Any]] = []
    archived_tickets: list[dict[str, Any]] = []
    for channel_id, ticket in store.items():
        channel = guild.get_channel(int(channel_id))
        owner = guild.get_member(int(ticket.get("owner_id", 0))) if ticket.get("owner_id") else None
        helper = guild.get_member(int(ticket.get("assigned_helper_id", 0))) if ticket.get("assigned_helper_id") else None
        row = {
            "channel_id": int(channel_id),
            "channel_name": channel.name if channel else f"#{channel_id}",
            "owner_name": owner.display_name if owner else str(ticket.get("owner_id", "-")),
            "helper_name": helper.display_name if helper else "-",
            "ticket_type": ticket.get("type", "-"),
            "status": ticket.get("status", "-"),
            "destination": ticket.get("destination", "-"),
            "opened_at": iso_to_local(ticket.get("created_at")),
            "claimed_at": iso_to_local(ticket.get("claimed_at")),
            "last_activity_at": iso_to_local(ticket.get("last_activity_at")),
            "transfer_reason": ticket.get("transfer_reason") or "-",
            "transfer_summary": ticket.get("transfer_summary") or "-",
            "claimed_messages": int(ticket.get("claimed_messages", 0)),
        }
        haystack = " ".join(
            [
                row["channel_name"],
                row["owner_name"],
                row["helper_name"],
                row["ticket_type"],
                row["destination"],
            ]
        ).lower()
        if ticket_filter and row["ticket_type"].lower() != ticket_filter and row["destination"].lower() != ticket_filter:
            continue
        if search_query and search_query not in haystack:
            continue
        if ticket.get("status") == "archived":
            archived_tickets.append(row)
        else:
            open_tickets.append(row)

    open_tickets.sort(key=lambda item: item["channel_name"].lower())
    archived_tickets.sort(key=lambda item: item["channel_name"].lower())
    staff_points = []
    for user_id, points in bot.get_ticket_store(guild.id).get("staff_points", {}).items():
        member = guild.get_member(int(user_id))
        staff_points.append(
            {
                "member_name": member.display_name if member else user_id,
                "points": int(points),
            }
        )
    staff_points.sort(key=lambda item: item["points"], reverse=True)
    return render_template(
        "tickets_panel.html",
        open_tickets=open_tickets,
        archived_tickets=archived_tickets,
        staff_points=staff_points[:15],
        ticket_stats=ticket_stats_for(guild),
        ticket_filter=ticket_filter,
        search_query=search_query,
        **panel_context("tickets"),
    )


@app.route("/sales", methods=["GET", "POST"])
@login_required
def sales_page():
    bot = get_bot()
    guild = selected_guild()
    if bot is None or guild is None:
        flash("Bot ou serveur indisponible.", "error")
        return render_template("sales_panel.html", pending_sales=[], active_sales=[], reserved_sales=[], **panel_context("sales"))

    if request.method == "POST":
        action = request.form.get("action", "")
        target_id = parse_int_or_none(request.form.get("target_id", ""))
        if target_id is None:
            flash("ID de vente invalide.", "error")
        elif action == "approve":
            ok, message = run_bot_coroutine(bot.owner_approve_sale(guild.id, target_id), timeout=60)
            flash("Vente acceptee." if ok else f"Echec: {message}", "success" if ok else "error")
        elif action == "reject":
            ok, message = run_bot_coroutine(bot.owner_reject_sale(guild.id, target_id), timeout=60)
            flash("Vente refusee." if ok else f"Echec: {message}", "success" if ok else "error")
        elif action == "close":
            ok, message = run_bot_coroutine(bot.owner_close_sale_channel(guild.id, target_id), timeout=60)
            flash("Vente cloturee." if ok else f"Echec: {message}", "success" if ok else "error")
        return redirect(url_for("sales_page", guild_id=guild.id))

    store = bot.get_sale_store(guild.id)
    pending_sales: list[dict[str, Any]] = []
    active_sales: list[dict[str, Any]] = []
    reserved_sales: list[dict[str, Any]] = []

    for review_message_id, sale in store.get("reviews", {}).items():
        seller = guild.get_member(int(sale.get("seller_id", 0))) if sale.get("seller_id") else None
        pending_sales.append(
            {
                "target_id": int(review_message_id),
                "product": sale.get("product", "-"),
                "category": sale.get("category", "-"),
                "price": sale.get("price", "-"),
                "seller_name": seller.display_name if seller else str(sale.get("seller_id", "-")),
                "created_at": iso_to_local(sale.get("created_at")),
            }
        )

    for message_id, sale in store.get("messages", {}).items():
        seller = guild.get_member(int(sale.get("seller_id", 0))) if sale.get("seller_id") else None
        buyer = guild.get_member(int(sale.get("buyer_id", 0))) if sale.get("buyer_id") else None
        row = {
            "message_id": int(message_id),
            "product": sale.get("product", "-"),
            "category": sale.get("category", "-"),
            "price": sale.get("price", "-"),
            "status": sale.get("status", "-"),
            "seller_name": seller.display_name if seller else str(sale.get("seller_id", "-")),
            "buyer_name": buyer.display_name if buyer else "-",
            "created_at": iso_to_local(sale.get("created_at")),
            "sale_channel_id": int(sale["sale_channel_id"]) if sale.get("sale_channel_id") else None,
        }
        if sale.get("status") == "reserved" and row["sale_channel_id"]:
            reserved_sales.append(row)
        else:
            active_sales.append(row)

    return render_template(
        "sales_panel.html",
        pending_sales=pending_sales,
        active_sales=active_sales,
        reserved_sales=reserved_sales,
        sales_stats=sales_stats_for(guild),
        **panel_context("sales"),
    )


@app.route("/giveaways", methods=["GET", "POST"])
@login_required
def giveaways_page():
    bot = get_bot()
    guild = selected_guild()
    if bot is None or guild is None:
        flash("Bot ou serveur indisponible.", "error")
        return render_template("giveaways_panel.html", active_giveaways=[], ended_giveaways=[], blacklist_entries=[], **panel_context("giveaways"))

    entries = bot.get_giveaway_entries(guild.id)
    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "create":
            channel_id = parse_int_or_none(request.form.get("channel_id", ""))
            prize = request.form.get("prize", "").strip()
            duration = request.form.get("duration", "").strip()
            winners_count = parse_int_or_none(request.form.get("winners_count", "")) or 0
            seconds = parse_duration(duration) if duration else None

            if channel_id is None or not prize or seconds is None or winners_count <= 0:
                flash("Parametres giveaway invalides.", "error")
            else:
                async def _create_giveaway() -> None:
                    channel = guild.get_channel(channel_id)
                    if not isinstance(channel, discord.TextChannel):
                        raise RuntimeError("Salon giveaway introuvable.")

                    end_at = int(discord.utils.utcnow().timestamp()) + seconds
                    embed = discord.Embed(
                        title="🎉 Giveaway",
                        description=(
                            f"Prix : **{prize}**\n"
                            f"Gagnant(s) : **{winners_count}**\n"
                            f"Fin : <t:{end_at}:R>\n"
                            "Chances bonus : **rôles invitations + Server Booster**\n\n"
                            "Clique sur Participer pour rejoindre le giveaway."
                        ),
                        color=discord.Color.gold(),
                    )
                    message = await channel.send(embed=embed, view=GiveawayView(bot))

                    store = bot.get_giveaway_entries(guild.id)
                    store[str(message.id)] = {
                        "message_id": message.id,
                        "channel_id": channel.id,
                        "prize": prize,
                        "winners_count": int(winners_count),
                        "participants": [],
                        "winners": [],
                        "forced_winner_id": None,
                        "end_at": end_at,
                        "status": "active",
                        "created_by": guild.owner_id,
                    }
                    bot.save_giveaways()
                    bot.schedule_giveaway_end(guild.id, message.id, end_at)

                ok, message = run_bot_coroutine(_create_giveaway(), timeout=90)
                flash("Giveaway cree." if ok else f"Echec: {message}", "success" if ok else "error")
        elif action in {"end", "reroll"}:
            message_id = parse_int_or_none(request.form.get("message_id", ""))
            if message_id is None:
                flash("ID giveaway invalide.", "error")
            elif action == "end":
                ok, message = run_bot_coroutine(bot.finish_giveaway(guild.id, message_id), timeout=90)
                flash("Giveaway termine." if ok else f"Echec: {message}", "success" if ok else "error")
            elif action == "reroll":
                ok, message = run_bot_coroutine(bot.reroll_giveaway(guild.id, message_id), timeout=90)
                flash("Giveaway reroll." if ok else f"Echec: {message}", "success" if ok else "error")
        elif action == "blacklist_add":
            member_id = parse_int_or_none(request.form.get("member_id", ""))
            reason = request.form.get("reason", "").strip() or "Aucune raison"
            if member_id is None:
                flash("ID membre invalide.", "error")
            else:
                store = bot.get_giveaway_blacklist(guild.id)
                store[str(member_id)] = {
                    "reason": reason,
                    "added_by": guild.owner_id,
                    "added_at": datetime.now(tz=_paris_tz).isoformat(),
                }
                bot.save_giveaways()
                flash("Membre blacklist giveaways ajoute.", "success")
        elif action == "blacklist_remove":
            member_id = parse_int_or_none(request.form.get("member_id", ""))
            if member_id is None:
                flash("ID membre invalide.", "error")
            else:
                bot.get_giveaway_blacklist(guild.id).pop(str(member_id), None)
                bot.save_giveaways()
                flash("Membre retire de la blacklist giveaways.", "success")
        elif action == "force_winner":
            message_id = parse_int_or_none(request.form.get("message_id", ""))
            member_id = parse_int_or_none(request.form.get("member_id", ""))
            giveaway = entries.get(str(message_id)) if message_id is not None else None
            if giveaway is None or member_id is None:
                flash("Giveaway ou membre invalide.", "error")
            else:
                giveaway["forced_winner_id"] = member_id
                bot.save_giveaways()
                flash("Forced winner enregistre.", "success")
        elif action == "clear_forced":
            message_id = parse_int_or_none(request.form.get("message_id", ""))
            giveaway = entries.get(str(message_id)) if message_id is not None else None
            if giveaway is None:
                flash("Giveaway introuvable.", "error")
            else:
                giveaway["forced_winner_id"] = None
                bot.save_giveaways()
                flash("Forced winner retire.", "success")
        return redirect(url_for("giveaways_page", guild_id=guild.id))

    active_giveaways: list[dict[str, Any]] = []
    ended_giveaways: list[dict[str, Any]] = []
    for giveaway in entries.values():
        participants = giveaway.get("participants", [])
        winners = giveaway.get("winners", [])
        row = {
            "message_id": int(giveaway.get("message_id", 0)),
            "prize": giveaway.get("prize", "-"),
            "status": giveaway.get("status", "-"),
            "participants_count": len(participants),
            "winners_count": int(giveaway.get("winners_count", 0)),
            "forced_winner_id": giveaway.get("forced_winner_id"),
            "end_at": giveaway.get("end_at", 0),
            "winners": winners,
            "participants_preview": ", ".join(str(item) for item in participants[:8]) if participants else "-",
        }
        if giveaway.get("status") == "active":
            active_giveaways.append(row)
        else:
            ended_giveaways.append(row)

    active_giveaways.sort(key=lambda item: item["end_at"], reverse=True)
    ended_giveaways.sort(key=lambda item: item["end_at"], reverse=True)

    blacklist_entries = []
    for member_id, data in bot.get_giveaway_blacklist(guild.id).items():
        member = guild.get_member(int(member_id))
        blacklist_entries.append(
            {
                "member_id": int(member_id),
                "member_name": member.display_name if member else member_id,
                "reason": data.get("reason", "Aucune raison"),
                "added_at": iso_to_local(data.get("added_at")),
            }
        )

    return render_template(
        "giveaways_panel.html",
        active_giveaways=active_giveaways,
        ended_giveaways=ended_giveaways,
        blacklist_entries=blacklist_entries,
        giveaway_stats=giveaway_stats_for(guild),
        **panel_context("giveaways"),
    )


@app.route("/gacha", methods=["GET", "POST"])
@login_required
def gacha_page():
    bot = get_bot()
    guild = selected_guild()
    if bot is None or guild is None:
        flash("Bot ou serveur indisponible.", "error")
        return render_template("gacha_panel.html", stocks=[], selected_member=None, selected_inventory=None, selected_notes=[], selected_history=[], **panel_context("gacha"))

    if request.method == "POST":
        action = request.form.get("action", "")
        member_id = parse_int_or_none(request.form.get("member_id", ""))
        spin_type = request.form.get("spin_type", "basic").strip().lower()
        quantity = parse_int_or_none(request.form.get("quantity", "")) or 0
        reason = request.form.get("reason", "").strip() or None

        if action in {"add_spin", "remove_spin", "note_add"} and member_id is None:
            flash("ID membre invalide.", "error")
            return redirect(url_for("gacha_page", guild_id=guild.id))

        member = guild.get_member(member_id) if member_id is not None else None
        member_name = member.display_name if member is not None else str(member_id)

        if action == "add_spin":
            if spin_type not in {"basic", "advanced", "deluxe"} or quantity <= 0:
                flash("Spin ou quantite invalide.", "error")
            else:
                total = bot.add_gacha_spins(member_id, spin_type, quantity)
                bot.record_spin_adjustment(member_id, member_name, guild.owner_id, "Owner Panel", spin_type, quantity, "add", reason, total)
                flash(f"{quantity} spin(s) ajoutes. Nouveau total: {total}.", "success")
        elif action == "remove_spin":
            if spin_type not in {"basic", "advanced", "deluxe"} or quantity <= 0:
                flash("Spin ou quantite invalide.", "error")
            else:
                total = bot.remove_gacha_spins(member_id, spin_type, quantity)
                bot.record_spin_adjustment(member_id, member_name, guild.owner_id, "Owner Panel", spin_type, quantity, "remove", reason, total)
                flash(f"{quantity} spin(s) retires. Nouveau total: {total}.", "success")
        elif action == "note_add":
            note = request.form.get("note", "").strip()
            if not note:
                flash("Note vide.", "error")
            else:
                bot.add_member_note(member_id, guild.owner_id, "Owner Panel", note)
                flash("Note ajoutee.", "success")
        elif action == "note_remove":
            note_index = parse_int_or_none(request.form.get("note_index", ""))
            if note_index is None:
                flash("Index note invalide.", "error")
            elif bot.remove_member_note(member_id, note_index) is None:
                flash("Note introuvable.", "error")
            else:
                flash("Note retiree.", "success")

        target = member_id if member_id is not None else request.form.get("target_member_id", "")
        return redirect(url_for("gacha_page", guild_id=guild.id, member_id=target))

    stocks = []
    for user_id, inventory in bot.gacha_data.get("inventories", {}).items():
        total = int(inventory.get("basic", 0)) + int(inventory.get("advanced", 0)) + int(inventory.get("deluxe", 0))
        if total <= 0:
            continue
        member = guild.get_member(int(user_id))
        stocks.append(
            {
                "member_id": int(user_id),
                "member_name": member.display_name if member else user_id,
                "basic": int(inventory.get("basic", 0)),
                "advanced": int(inventory.get("advanced", 0)),
                "deluxe": int(inventory.get("deluxe", 0)),
                "total": total,
            }
        )
    stocks.sort(key=lambda item: item["total"], reverse=True)

    selected_member_id = parse_int_or_none(request.args.get("member_id", ""))
    selected_member = guild.get_member(selected_member_id) if selected_member_id is not None else None
    selected_inventory = bot.get_gacha_inventory(selected_member_id) if selected_member_id is not None else None
    selected_notes = bot.get_member_notes(selected_member_id) if selected_member_id is not None else []
    selected_history = bot.get_member_grant_history(selected_member_id) if selected_member_id is not None else []
    selected_history = list(reversed(selected_history[-20:])) if selected_history else []

    return render_template(
        "gacha_panel.html",
        stocks=stocks,
        selected_member=selected_member,
        selected_member_id=selected_member_id,
        selected_inventory=selected_inventory,
        selected_notes=selected_notes,
        selected_history=selected_history,
        gacha_stats=gacha_stats_for(guild),
        **panel_context("gacha"),
    )


@app.route("/invites", methods=["GET", "POST"])
@login_required
def invites_page():
    bot = get_bot()
    guild = selected_guild()
    if bot is None or guild is None:
        flash("Bot ou serveur indisponible.", "error")
        return render_template(
            "invites_panel.html",
            invite_rows=[],
            free_role_name="-",
            weekly_requirement=2,
            weekly_reset_label="-",
            **panel_context("invites"),
        )

    store = bot.get_invite_store(guild.id)
    config = bot.get_guild_config(guild.id)

    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "refresh_free":
            ok, message = run_bot_coroutine(bot.sync_all_free_access_roles(guild), timeout=120)
            flash("Acces free mis a jour." if ok else f"Echec: {message}", "success" if ok else "error")
        elif action == "sync_invite_roles":
            ok, message = run_bot_coroutine(bot.sync_all_invite_roles(guild), timeout=180)
            flash("Roles invitations synchronises." if ok else f"Echec: {message}", "success" if ok else "error")
        elif action == "reset_weekly":
            store["weekly_counts"] = {}
            store["last_weekly_reset_key"] = datetime.now(tz=_paris_tz).strftime("%G-W%V")
            bot.save_invites()
            ok, message = run_bot_coroutine(bot.sync_all_free_access_roles(guild), timeout=120)
            flash("Compteur weekly reset." if ok else f"Reset fait mais sync en echec: {message}", "success" if ok else "error")
        elif action == "post_free":
            service = request.form.get("service", "").strip().lower()
            content = request.form.get("content", "").strip()
            key = "free_netflix_channel_id" if service == "netflix" else "free_crunchyroll_channel_id"
            channel = guild.get_channel(config.get(key))
            if not isinstance(channel, discord.TextChannel):
                flash("Salon free introuvable.", "error")
            elif not content:
                flash("Contenu vide.", "error")
            else:
                color = discord.Color.red() if service == "netflix" else discord.Color.orange()
                async def _post_free() -> None:
                    embed = discord.Embed(
                        title=f"{service.title()} Free",
                        description=content,
                        color=color,
                    )
                    embed.set_footer(text="Publie via owner panel")
                    await channel.send(embed=embed)
                ok, message = run_bot_coroutine(_post_free(), timeout=60)
                flash("Publication envoyee." if ok else f"Echec: {message}", "success" if ok else "error")

        return redirect(url_for("invites_page", guild_id=guild.id))

    rows = invite_rows_for(guild)
    free_role = guild.get_role(config["free_access_role_id"]) if config.get("free_access_role_id") else None
    weekly_reset_label = store.get("last_weekly_reset_key") or "Jamais"

    return render_template(
        "invites_panel.html",
        invite_rows=rows,
        free_role_name=free_role.name if free_role is not None else "-",
        weekly_requirement=FREE_INVITE_REQUIREMENT,
        weekly_reset_label=weekly_reset_label,
        invite_stats=invite_stats_for(guild),
        **panel_context("invites"),
    )


@app.route("/levels", methods=["GET", "POST"])
@login_required
def levels_page():
    bot = get_bot()
    guild = selected_guild()
    if bot is None or guild is None:
        flash("Bot ou serveur indisponible.", "error")
        return render_template(
            "levels_panel.html",
            leaderboard=[],
            selected_profile=None,
            grade_rules=LEVEL_FEATURE_RULES,
            **panel_context("levels"),
        )

    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "sync_xp_roles":
            category, message = run_quick_action(bot, guild, action)
            flash(message, category)
            return redirect(url_for("levels_page", guild_id=guild.id))
        if action == "set_level":
            member_id = parse_int_or_none(request.form.get("member_id", ""))
            target_level = parse_int_or_none(request.form.get("target_level", ""))
            member = guild.get_member(member_id) if member_id is not None else None
            if member is None or target_level is None:
                flash("Membre ou niveau invalide.", "error")
            else:
                async def _set_level() -> dict[str, Any]:
                    return await bot.set_member_level(member, target_level)

                future = asyncio.run_coroutine_threadsafe(_set_level(), bot.loop)
                try:
                    result = future.result(timeout=60)
                    flash(
                        f"Niveau mis a jour: {member.display_name} passe de {result['before_level']} a {result['after_level']}.",
                        "success",
                    )
                except Exception as exc:
                    flash(f"Echec: {exc}", "error")
            return redirect(url_for("levels_page", guild_id=guild.id, member_id=member_id or ""))

    leaderboard = level_rows_for(guild)
    selected_member_id = parse_int_or_none(request.args.get("member_id", ""))
    selected_profile = level_detail_for(guild, selected_member_id)
    return render_template(
        "levels_panel.html",
        leaderboard=leaderboard[:30],
        selected_profile=selected_profile,
        grade_rules=LEVEL_FEATURE_RULES,
        level_stats={
            "tracked": len(leaderboard),
            "top_level": leaderboard[0]["level"] if leaderboard else 0,
            "top_xp": leaderboard[0]["xp"] if leaderboard else 0,
        },
        **panel_context("levels"),
    )


@app.route("/logs")
@login_required
def logs_page():
    guild = selected_guild()
    selected_type = request.args.get("type", "").strip()
    query = request.args.get("q", "").strip()
    entries = filtered_activity_feed_for(guild, limit=160, entry_type=selected_type, query=query)
    return render_template(
        "logs_panel.html",
        entries=entries,
        log_types=logs_types_for(guild),
        selected_type=selected_type,
        query=query,
        **panel_context("logs"),
    )


@app.route("/security", methods=["GET", "POST"])
@login_required
def security_page():
    bot = get_bot()
    guild = selected_guild()
    if bot is None or guild is None:
        flash("Bot ou serveur indisponible.", "error")
        return render_template("security.html", security={}, quick_actions=[], **panel_context("security"))

    if request.method == "POST":
        category, message = run_quick_action(bot, guild, request.form.get("action", ""))
        flash(message, category)
        return redirect(url_for("security_page", guild_id=guild.id))

    security = {
        "panel_enabled": panel_enabled(),
        "database_enabled": bool(DATABASE_URL),
        "secret_key_set": bool(os.environ.get("PANEL_SECRET_KEY")),
        "username": panel_username(),
        "session_active": is_authenticated(),
        "bot_online": bool(bot and not bot.is_closed()),
        "guild_synced": guild.id in getattr(bot, "synced_guild_ids", set()),
        "guild_owner_id": guild.owner_id,
        "guild_count": len(bot.guilds),
        "latency_ms": round(bot.latency * 1000) if getattr(bot, "latency", None) is not None else 0,
    }
    return render_template(
        "security.html",
        security=security,
        quick_actions=build_quick_action_items(),
        **panel_context("security"),
    )


@app.route("/members", methods=["GET", "POST"])
@login_required
def members_page():
    bot = get_bot()
    guild = selected_guild()
    if bot is None or guild is None:
        flash("Bot ou serveur indisponible.", "error")
        return render_template("members_panel.html", selected_profile=None, **panel_context("members"))

    selected_member_id = parse_int_or_none(request.values.get("member_id", ""))
    if request.method == "POST":
        action = request.form.get("action", "")
        selected_member_id = parse_int_or_none(request.form.get("member_id", "")) or selected_member_id
        member = guild.get_member(selected_member_id) if selected_member_id is not None else None
        if action == "sync_member_invites":
            if member is None:
                flash("Membre introuvable.", "error")
            else:
                ok, message = run_bot_coroutine(bot.sync_member_invite_roles(member), timeout=60)
                flash("Roles invitations du membre synchronises." if ok else f"Echec: {message}", "success" if ok else "error")
        elif action == "blacklist_add":
            reason = request.form.get("reason", "").strip() or "Aucune raison"
            if selected_member_id is None:
                flash("ID membre invalide.", "error")
            else:
                store = bot.get_giveaway_blacklist(guild.id)
                store[str(selected_member_id)] = {
                    "reason": reason,
                    "added_by": guild.owner_id,
                    "added_at": datetime.now(tz=_paris_tz).isoformat(),
                }
                bot.save_giveaways()
                flash("Membre ajoute a la blacklist giveaways.", "success")
        elif action == "blacklist_remove":
            if selected_member_id is None:
                flash("ID membre invalide.", "error")
            else:
                bot.get_giveaway_blacklist(guild.id).pop(str(selected_member_id), None)
                bot.save_giveaways()
                flash("Membre retire de la blacklist giveaways.", "success")
        elif action == "free_sync":
            ok, message = run_bot_coroutine(bot.sync_all_free_access_roles(guild), timeout=120)
            flash("Acces free resynchronises." if ok else f"Echec: {message}", "success" if ok else "error")
        return redirect(url_for("members_page", guild_id=guild.id, member_id=selected_member_id or ""))

    selected_profile = member_hub_data(guild, selected_member_id)
    top_members = level_rows_for(guild)[:12]
    return render_template(
        "members_panel.html",
        selected_profile=selected_profile,
        top_members=top_members,
        **panel_context("members"),
    )


@app.route("/staff")
@login_required
def staff_page():
    guild = selected_guild()
    rows = staff_rows_for(guild)
    return render_template(
        "staff_panel.html",
        staff_rows=rows,
        **panel_context("staff"),
    )


@app.route("/export/<dataset>")
@login_required
def export_dataset(dataset: str):
    bot = get_bot()
    guild = selected_guild()
    if bot is None or guild is None:
        return Response("Bot ou serveur indisponible.", status=503)

    exports = {
        "config": bot.get_guild_config(guild.id),
        "tickets": bot.get_ticket_store(guild.id),
        "sales": bot.get_sale_store(guild.id),
        "giveaways": {
            "entries": bot.get_giveaway_entries(guild.id),
            "blacklist": bot.get_giveaway_blacklist(guild.id),
        },
        "promotions": bot.get_promo_store(guild.id),
        "invites": bot.get_invite_store(guild.id),
        "levels": bot.get_level_store(guild.id),
        "gacha": bot.gacha_data,
    }
    if dataset not in exports:
        return Response("Dataset inconnu.", status=404)
    return json_download(exports[dataset], f"{guild.id}-{dataset}.json")


def run_web_server() -> None:
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, use_reloader=False)


def keep_alive(bot: Any | None = None) -> None:
    if bot is not None:
        attach_bot(bot)
    thread = Thread(target=run_web_server, daemon=True)
    thread.start()
