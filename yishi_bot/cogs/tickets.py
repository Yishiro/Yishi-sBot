from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import discord
from discord import app_commands
from discord.ext import commands

from yishi_bot.ticketing import build_custom_ticket_panel_embed, build_ticket_panel_embed
from yishi_bot.views import TicketPanelView

if TYPE_CHECKING:
    from yishi_bot.core import YishiBot


class TicketTransferModal(discord.ui.Modal, title="Transférer le ticket"):
    raison = discord.ui.TextInput(
        label="Raison du transfert",
        max_length=120,
        required=True,
        placeholder="Exemple : le client veut passer commande / problème technique",
    )
    a_faire = discord.ui.TextInput(
        label="Ce qu'il y a à faire",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=True,
        placeholder="Explique ce qui a déjà été dit et ce que le staff doit faire ensuite.",
    )

    def __init__(self, bot: "YishiBot", destination: str) -> None:
        super().__init__()
        self.bot = bot
        self.destination = destination

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return

        store = self.bot.get_ticket_store(interaction.guild.id)["channels"]
        ticket = store.get(str(interaction.channel.id))
        if ticket is None:
            await interaction.response.send_message("Cette commande doit être utilisée dans un ticket.", ephemeral=True)
            return

        category = self.bot.get_ticket_destination_category(interaction.guild, self.destination)
        if category is None:
            await interaction.response.send_message("La catégorie de destination est introuvable.", ephemeral=True)
            return

        ticket["destination"] = self.destination
        ticket["transferred_by"] = interaction.user.id
        ticket["transfer_reason"] = self.raison.value
        ticket["transfer_summary"] = self.a_faire.value
        self.bot.add_staff_points(interaction.guild.id, interaction.user.id, 2)
        self.bot.save_tickets()

        await interaction.channel.edit(category=category, reason=f"Transfert ticket vers {self.destination} par {interaction.user}")

        embed = discord.Embed(
            title="Ticket transféré",
            description=f"Le ticket a été transféré vers **{self.destination}** par {interaction.user.mention}.",
            color=discord.Color.orange(),
        )
        embed.add_field(name="Raison", value=self.raison.value, inline=False)
        embed.add_field(name="À faire", value=self.a_faire.value, inline=False)
        await interaction.channel.send(embed=embed)
        await interaction.response.send_message("Le ticket a bien été transféré.", ephemeral=True)


class TicketsCog(commands.Cog):
    def __init__(self, bot: YishiBot) -> None:
        self.bot = bot

    def get_ticket(self, interaction: discord.Interaction) -> dict | None:
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
            return None
        return self.bot.get_ticket_store(interaction.guild.id)["channels"].get(str(interaction.channel.id))

    @app_commands.command(name="ticket_add", description="Ajoute un membre au ticket actuel")
    @app_commands.describe(membre="Le membre à ajouter au ticket")
    async def ticket_add(self, interaction: discord.Interaction, membre: discord.Member) -> None:
        ticket = self.get_ticket(interaction)
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel) or ticket is None:
            await interaction.response.send_message("Cette commande doit être utilisée dans un ticket.", ephemeral=True)
            return
        if not self.bot.is_helper_member(interaction.user):  # type: ignore[arg-type]
            await interaction.response.send_message("Commande réservée au staff.", ephemeral=True)
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
        await interaction.response.send_message(f"{membre.mention} a été ajouté au ticket.", ephemeral=True)
        await interaction.channel.send(f"{membre.mention} a été ajouté au ticket par {interaction.user.mention}.")

    @app_commands.command(name="ticket_remove", description="Retire un membre du ticket actuel")
    @app_commands.describe(membre="Le membre à retirer du ticket")
    async def ticket_remove(self, interaction: discord.Interaction, membre: discord.Member) -> None:
        ticket = self.get_ticket(interaction)
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel) or ticket is None:
            await interaction.response.send_message("Cette commande doit être utilisée dans un ticket.", ephemeral=True)
            return
        if not self.bot.is_helper_member(interaction.user):  # type: ignore[arg-type]
            await interaction.response.send_message("Commande réservée au staff.", ephemeral=True)
            return

        await interaction.channel.set_permissions(membre, overwrite=None)
        await interaction.response.send_message(f"{membre.mention} a été retiré du ticket.", ephemeral=True)
        await interaction.channel.send(f"{membre.mention} a été retiré du ticket par {interaction.user.mention}.")

    @app_commands.command(name="ticket_claim", description="Claim le ticket actuel")
    async def ticket_claim(self, interaction: discord.Interaction) -> None:
        ticket = self.get_ticket(interaction)
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel) or ticket is None:
            await interaction.response.send_message("Cette commande doit être utilisée dans un ticket.", ephemeral=True)
            return
        if not self.bot.is_helper_member(interaction.user):  # type: ignore[arg-type]
            await interaction.response.send_message("Commande réservée au staff.", ephemeral=True)
            return
        if ticket.get("assigned_helper_id") and ticket.get("assigned_helper_id") != interaction.user.id:
            await interaction.response.send_message("Ce ticket est déjà claim par un autre membre du staff.", ephemeral=True)
            return

        owner = interaction.guild.get_member(ticket["owner_id"])
        ticket["assigned_helper_id"] = interaction.user.id
        ticket["claimed_at"] = self.bot.iso_now()
        self.bot.add_staff_points(interaction.guild.id, interaction.user.id, 1)
        self.bot.save_tickets()
        await self.bot.apply_claimed_ticket_permissions(interaction.guild, interaction.channel, owner, interaction.user)  # type: ignore[arg-type]
        await interaction.response.send_message("Ticket claim avec succès.", ephemeral=True)
        await interaction.channel.send(f"{interaction.user.mention} a claim ce ticket.")

    @app_commands.command(name="ticket_transfer", description="Transfère le ticket vers les achats ou le staff")
    @app_commands.describe(destination="Destination du ticket")
    async def ticket_transfer(self, interaction: discord.Interaction, destination: Literal["achat", "staff"]) -> None:
        ticket = self.get_ticket(interaction)
        if ticket is None:
            await interaction.response.send_message("Cette commande doit être utilisée dans un ticket.", ephemeral=True)
            return
        if not self.bot.is_helper_member(interaction.user):  # type: ignore[arg-type]
            await interaction.response.send_message("Commande réservée au staff.", ephemeral=True)
            return
        await interaction.response.send_modal(TicketTransferModal(self.bot, destination))

    @app_commands.command(name="ticket_close", description="Ferme le ticket actuel")
    async def ticket_close(self, interaction: discord.Interaction) -> None:
        await self.bot.archive_ticket(interaction)

    @app_commands.command(name="vouch", description="Envoie le rappel vers le salon vouches dans le ticket")
    async def vouch(self, interaction: discord.Interaction) -> None:
        ticket = self.get_ticket(interaction)
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel) or ticket is None:
            await interaction.response.send_message("Cette commande doit être utilisée dans un ticket.", ephemeral=True)
            return
        if not self.bot.is_helper_member(interaction.user):  # type: ignore[arg-type]
            await interaction.response.send_message("Commande réservée au staff.", ephemeral=True)
            return

        await interaction.response.send_message("Message vouch envoyé.", ephemeral=True)
        await interaction.channel.send(
            "Merci pour ta confiance. Si tout est bon, n'oublie pas de laisser un avis dans <#1490432216952733847>."
        )

    @app_commands.command(name="ticket_points", description="Affiche les points tickets d'un membre du staff")
    @app_commands.describe(membre="Le membre du staff")
    async def ticket_points(self, interaction: discord.Interaction, membre: discord.Member | None = None) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        if not self.bot.is_helper_member(interaction.user):  # type: ignore[arg-type]
            await interaction.response.send_message("Commande réservée au staff.", ephemeral=True)
            return
        target = membre or interaction.user
        points = self.bot.get_staff_point_total(interaction.guild.id, target.id)
        await interaction.response.send_message(f"{target.mention} a **{points}** point(s) tickets.", ephemeral=True)

    @app_commands.command(name="ticket_leaderboard", description="Affiche le classement tickets du staff")
    async def ticket_leaderboard(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        if not self.bot.is_helper_member(interaction.user):  # type: ignore[arg-type]
            await interaction.response.send_message("Commande réservée au staff.", ephemeral=True)
            return

        points_store = self.bot.get_ticket_store(interaction.guild.id)["staff_points"]
        ranking = sorted(
            ((int(member_id), int(points)) for member_id, points in points_store.items()),
            key=lambda item: item[1],
            reverse=True,
        )[:10]
        if not ranking:
            await interaction.response.send_message("Aucun point staff pour le moment.", ephemeral=True)
            return

        lines = []
        for index, (member_id, points) in enumerate(ranking, start=1):
            member = interaction.guild.get_member(member_id)
            label = member.mention if member else f"`{member_id}`"
            lines.append(f"**#{index}** {label} • {points} pts")
        embed = discord.Embed(title="Classement tickets staff", description="\n".join(lines), color=discord.Color.gold())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="envoyer_panel_tickets", description="Envoie le panneau interactif de tickets")
    @app_commands.describe(salon="Salon du panneau tickets")
    @app_commands.default_permissions(manage_guild=True)
    async def envoyer_panel_tickets(self, interaction: discord.Interaction, salon: discord.TextChannel) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        await salon.send(embed=build_ticket_panel_embed(), view=TicketPanelView(self.bot))
        await interaction.response.send_message(f"Panneau de tickets envoyé dans {salon.mention}.", ephemeral=True)

    @app_commands.command(name="envoyer_panel_tickets_custom", description="Envoie un panneau de tickets personnalisable")
    @app_commands.describe(
        salon="Salon du panneau tickets",
        titre="Titre du panel",
        texte="Texte affiché",
        image_url="Lien de l'image affichée",
        image="Image affichée sous le texte",
    )
    @app_commands.default_permissions(manage_guild=True)
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
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return

        final_image_url = image_url
        file: discord.File | None = None
        if image is not None:
            file = await image.to_file()
            final_image_url = f"attachment://{file.filename}"

        embed = build_custom_ticket_panel_embed(
            title=titre or "Yishi's Shop Support Center",
            intro_text=texte,
            image_url=final_image_url,
        )
        await salon.send(embed=embed, view=TicketPanelView(self.bot), file=file)
        await interaction.response.send_message(f"Panneau de tickets envoyé dans {salon.mention}.", ephemeral=True)
