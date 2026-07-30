from __future__ import annotations

import asyncio
import os
from datetime import datetime
from functools import wraps
from threading import Thread
from typing import Any
from zoneinfo import ZoneInfo

from flask import Flask, flash, redirect, render_template, request, session, url_for


app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("PANEL_SECRET_KEY") or os.environ.get("DISCORD_TOKEN") or "yishi-panel-dev-secret"

_bot = None
_paris_tz = ZoneInfo("Europe/Paris")
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


def iso_to_local(value: str | None) -> str:
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.strftime("%d/%m/%Y %H:%M")
        return dt.astimezone(_paris_tz).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return value


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
        }

    ticket_store = bot.get_ticket_store(guild.id)
    sale_store = bot.get_sale_store(guild.id)
    giveaway_store = bot.get_giveaway_store(guild.id)
    promo_store = bot.get_promo_store(guild.id)
    level_store = bot.level_data.get("members", {})

    return {
        "tickets_open": len(ticket_store.get("channels", {})),
        "sales_active": len(sale_store.get("messages", {})),
        "sales_pending": len(sale_store.get("reviews", {})),
        "giveaways_active": len(giveaway_store.get("giveaways", {})),
        "promotions_total": len(promo_store.get("promotions", [])),
        "tracked_members": len(level_store),
    }


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


@app.route("/dashboard")
@login_required
def dashboard():
    guild = selected_guild()
    stats = get_dashboard_stats(guild)
    bot = get_bot()
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
        **panel_context("dashboard"),
    )


@app.route("/config", methods=["GET", "POST"])
@login_required
def config_page():
    bot = get_bot()
    guild = selected_guild()
    if bot is None or guild is None:
        flash("Bot ou serveur indisponible.", "error")
        return render_template("config.html", config_fields=CONFIG_FIELDS, config={}, **panel_context("config"))

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
        config_fields=CONFIG_FIELDS,
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
        elif action == "send_level_now":
            async def _send_level_now() -> None:
                channel = guild.get_channel(bot.get_daily_level_channel_id(guild.id))
                if channel is None:
                    raise RuntimeError("Salon progression introuvable.")
                await channel.send(bot.build_daily_level_message(guild.id))

            ok, message = run_bot_coroutine(_send_level_now())
            flash("Message progression envoye." if ok else f"Echec: {message}", "success" if ok else "error")
        elif action == "send_sales_now":
            async def _send_sales_now() -> None:
                channel = guild.get_channel(bot.get_daily_sales_rules_channel_id(guild.id))
                if channel is None:
                    raise RuntimeError("Salon ventes introuvable.")
                await channel.send(embed=bot.build_sales_rules_embed())

            ok, message = run_bot_coroutine(_send_sales_now())
            flash("Reglement ventes envoye." if ok else f"Echec: {message}", "success" if ok else "error")
        elif action == "sync_commands":
            ok, message = run_bot_coroutine(bot.sync_commands_once(force=True), timeout=60)
            flash("Commandes resynchronisees." if ok else f"Echec: {message}", "success" if ok else "error")

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
        }
        if ticket.get("status") == "archived":
            archived_tickets.append(row)
        else:
            open_tickets.append(row)

    open_tickets.sort(key=lambda item: item["channel_name"].lower())
    archived_tickets.sort(key=lambda item: item["channel_name"].lower())
    return render_template(
        "tickets_panel.html",
        open_tickets=open_tickets,
        archived_tickets=archived_tickets,
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
        **panel_context("sales"),
    )


def run_web_server() -> None:
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, use_reloader=False)


def keep_alive(bot: Any | None = None) -> None:
    if bot is not None:
        attach_bot(bot)
    thread = Thread(target=run_web_server, daemon=True)
    thread.start()
