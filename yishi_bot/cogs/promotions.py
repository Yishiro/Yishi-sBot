from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from yishi_bot.core import YishiBot


class PromotionsCog(commands.Cog):
    def __init__(self, bot: "YishiBot") -> None:
        self.bot = bot

    @app_commands.command(name="promo_add", description="Ajoute une promotion à la rotation hebdomadaire")
    @app_commands.describe(
        titre="Titre affiché dans la promo",
        texte="Texte principal de la promo",
        priorite="Priorité de 1 à 5 (5 = la plus forte)",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def promo_add(
        self,
        interaction: discord.Interaction,
        titre: str,
        texte: str,
        priorite: app_commands.Range[int, 1, 5],
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return

        store = self.bot.get_promo_store(interaction.guild.id)
        promo_id = int(store["next_id"])
        queue_position = max(
            (int(promo.get("queue_position", promo["id"])) for promo in store["promotions"]),
            default=0,
        ) + 1
        promo = {
            "id": promo_id,
            "title": titre,
            "content": texte,
            "priority": int(priorite),
            "active": True,
            "created_at": self.bot.iso_now(),
            "last_posted_at": None,
            "queue_position": queue_position,
        }
        store["promotions"].append(promo)
        store["next_id"] = promo_id + 1
        self.bot.save_promos()

        await interaction.response.send_message(
            f"Promotion **#{promo_id}** ajoutée avec priorité **{priorite}**.",
            ephemeral=True,
        )

    @app_commands.command(name="promo_list", description="Affiche la liste des promotions enregistrées")
    @app_commands.default_permissions(manage_guild=True)
    async def promo_list(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return

        store = self.bot.get_promo_store(interaction.guild.id)
        promotions = store["promotions"]
        if not promotions:
            await interaction.response.send_message("Aucune promotion enregistrée.", ephemeral=True)
            return

        lines = []
        ordered = sorted(
            promotions,
            key=lambda promo: (
                -int(promo.get("priority", 1)),
                int(promo.get("queue_position", promo["id"])),
            ),
        )
        for promo in ordered:
            status = "active" if promo.get("active", True) else "off"
            last_posted = promo.get("last_posted_at") or "jamais"
            lines.append(
                f"**#{promo['id']}** • P{promo.get('priority', 1)} • {status} • "
                f"{promo['title']} • last: {last_posted}"
            )

        embed = discord.Embed(
            title="Bibliothèque des promotions",
            description="\n".join(lines[:25]),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="promo_remove", description="Supprime une promotion de la rotation")
    @app_commands.describe(promo_id="Identifiant de la promotion")
    @app_commands.default_permissions(manage_guild=True)
    async def promo_remove(self, interaction: discord.Interaction, promo_id: int) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return

        store = self.bot.get_promo_store(interaction.guild.id)
        for index, promo in enumerate(store["promotions"]):
            if int(promo["id"]) == promo_id:
                removed = store["promotions"].pop(index)
                self.bot.save_promos()
                await interaction.response.send_message(
                    f"Promotion **#{promo_id}** supprimée : **{removed['title']}**.",
                    ephemeral=True,
                )
                return

        await interaction.response.send_message("Promotion introuvable.", ephemeral=True)

    @app_commands.command(name="promo_toggle", description="Active ou désactive une promotion")
    @app_commands.describe(promo_id="Identifiant de la promotion", active="Active ou désactive la promo")
    @app_commands.default_permissions(manage_guild=True)
    async def promo_toggle(self, interaction: discord.Interaction, promo_id: int, active: bool) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return

        store = self.bot.get_promo_store(interaction.guild.id)
        for promo in store["promotions"]:
            if int(promo["id"]) == promo_id:
                promo["active"] = active
                self.bot.save_promos()
                await interaction.response.send_message(
                    f"Promotion **#{promo_id}** {'activée' if active else 'désactivée'}.",
                    ephemeral=True,
                )
                return

        await interaction.response.send_message("Promotion introuvable.", ephemeral=True)

    @app_commands.command(name="promo_post", description="Publie manuellement une promotion")
    @app_commands.describe(promo_id="Laisse vide pour publier la prochaine promo prioritaire")
    @app_commands.default_permissions(manage_guild=True)
    async def promo_post(self, interaction: discord.Interaction, promo_id: int | None = None) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return

        store = self.bot.get_promo_store(interaction.guild.id)
        promo = None
        if promo_id is None:
            promo = self.bot.select_next_promo(interaction.guild.id)
        else:
            promo = next((item for item in store["promotions"] if int(item["id"]) == promo_id), None)

        if promo is None:
            await interaction.response.send_message("Aucune promotion trouvée à publier.", ephemeral=True)
            return

        message = await self.bot.post_promo(interaction.guild, promo, automatic=False)
        if message is None:
            await interaction.response.send_message(
                "Le salon de promotions n'est pas configuré ou introuvable.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Promotion publiée dans {message.channel.mention}.",
            ephemeral=True,
        )
