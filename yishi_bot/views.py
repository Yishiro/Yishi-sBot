from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from yishi_bot.ticketing import TICKET_TYPES

if TYPE_CHECKING:
    from yishi_bot.core import YishiBot

class TicketPanelSelect(discord.ui.Select):
    def __init__(self, bot: "YishiBot") -> None:
        options = [
            discord.SelectOption(
                label=data["label"],
                value=key,
                description=data["description"],
                emoji=data["emoji"],
            )
            for key, data in TICKET_TYPES.items()
        ]
        super().__init__(
            placeholder="Sélectionnez la raison de votre ticket...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="ticket_panel_select",
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.message is not None:
            await interaction.message.edit(view=TicketPanelView(self.bot))
        await self.bot.create_ticket(interaction, self.values[0])

class TicketPanelView(discord.ui.View):
    def __init__(self, bot: "YishiBot") -> None:
        super().__init__(timeout=None)
        self.add_item(TicketPanelSelect(bot))

class TicketCloseButton(discord.ui.Button):
    def __init__(self, bot: "YishiBot") -> None:
        super().__init__(
            label="Fermer",
            style=discord.ButtonStyle.danger,
            emoji="🔒",
            custom_id="ticket_close_button",
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.bot.archive_ticket(interaction)

class TicketCloseView(discord.ui.View):
    def __init__(self, bot: "YishiBot") -> None:
        super().__init__(timeout=None)
        self.add_item(TicketCloseButton(bot))

class TicketReopenButton(discord.ui.Button):
    def __init__(self, bot: "YishiBot") -> None:
        super().__init__(
            label="Réouvrir",
            style=discord.ButtonStyle.success,
            emoji="🔓",
            custom_id="ticket_reopen_button",
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.bot.reopen_ticket(interaction)

class TicketArchiveView(discord.ui.View):
    def __init__(self, bot: "YishiBot") -> None:
        super().__init__(timeout=None)
        self.add_item(TicketReopenButton(bot))

class GiveawayJoinButton(discord.ui.Button):
    def __init__(self, bot: "YishiBot") -> None:
        super().__init__(
            label="Participer",
            style=discord.ButtonStyle.success,
            emoji="🎉",
            custom_id="giveaway_join_button",
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.bot.join_giveaway(interaction)

class GiveawayParticipantsButton(discord.ui.Button):
    def __init__(self, bot: "YishiBot") -> None:
        super().__init__(
            label="Participants",
            style=discord.ButtonStyle.secondary,
            emoji="👥",
            custom_id="giveaway_participants_button",
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.bot.show_giveaway_participants(interaction)

class GiveawayChanceButton(discord.ui.Button):
    def __init__(self, bot: "YishiBot") -> None:
        super().__init__(
            label="Mes chances",
            style=discord.ButtonStyle.secondary,
            emoji="🍀",
            custom_id="giveaway_chance_button",
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.bot.show_giveaway_chances(interaction)

class GiveawayRemainingTimeButton(discord.ui.Button):
    def __init__(self, bot: "YishiBot") -> None:
        super().__init__(
            label="Temps restant",
            style=discord.ButtonStyle.secondary,
            emoji="⏳",
            custom_id="giveaway_remaining_button",
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.bot.show_giveaway_remaining_time(interaction)

class GiveawayView(discord.ui.View):
    def __init__(self, bot: "YishiBot") -> None:
        super().__init__(timeout=None)
        self.add_item(GiveawayJoinButton(bot))
        self.add_item(GiveawayParticipantsButton(bot))
        self.add_item(GiveawayChanceButton(bot))
        self.add_item(GiveawayRemainingTimeButton(bot))

class SaleBuyButton(discord.ui.Button):
    def __init__(self, bot: "YishiBot") -> None:
        super().__init__(
            label="Acheter",
            style=discord.ButtonStyle.success,
            emoji="🛒",
            custom_id="sale_buy_button",
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.bot.buy_sale(interaction)

class SaleListingView(discord.ui.View):
    def __init__(self, bot: "YishiBot") -> None:
        super().__init__(timeout=None)
        self.add_item(SaleBuyButton(bot))

class SaleApproveButton(discord.ui.Button):
    def __init__(self, bot: "YishiBot") -> None:
        super().__init__(
            label="Accepter",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id="sale_approve_button",
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.bot.approve_sale_listing(interaction)

class SaleRejectButton(discord.ui.Button):
    def __init__(self, bot: "YishiBot") -> None:
        super().__init__(
            label="Refuser",
            style=discord.ButtonStyle.danger,
            emoji="❌",
            custom_id="sale_reject_button",
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.bot.reject_sale_listing(interaction)

class SaleApprovalView(discord.ui.View):
    def __init__(self, bot: "YishiBot") -> None:
        super().__init__(timeout=None)
        self.add_item(SaleApproveButton(bot))
        self.add_item(SaleRejectButton(bot))

class SaleCreateModal(discord.ui.Modal, title="Création vente"):
    categorie = discord.ui.TextInput(
        label="Catégorie",
        max_length=100,
        required=True,
        placeholder="Exemple : Compte, Skin, Fruit, Service...",
    )
    produits = discord.ui.TextInput(
        label="Produits",
        max_length=120,
        required=True,
        placeholder="Nom du produit ou de l'objet vendu",
    )
    prix = discord.ui.TextInput(
        label="Prix",
        max_length=60,
        required=True,
        placeholder="Exemple : 5€ / 1200 Robux / 10€ négociable",
    )
    description = discord.ui.TextInput(
        label="Description",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=True,
        placeholder="Décris clairement ce que tu vends, les infos utiles, l'état, etc.",
    )

    def __init__(self, bot: "YishiBot") -> None:
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.bot.create_sale_listing(
            interaction,
            self.categorie.value,
            self.produits.value,
            self.prix.value,
            self.description.value,
        )

class AnnouncementModal(discord.ui.Modal, title="Création annonce"):
    titre = discord.ui.TextInput(label="Titre", max_length=120, required=True, placeholder="Titre de l'annonce")
    contenu = discord.ui.TextInput(
        label="Message",
        style=discord.TextStyle.paragraph,
        max_length=2000,
        required=True,
        placeholder="Contenu principal de l'annonce...",
    )
    footer = discord.ui.TextInput(
        label="Note en bas",
        max_length=150,
        required=False,
        placeholder="Exemple : Merci de lire attentivement",
    )

    def __init__(self, bot: "YishiBot", salon: discord.TextChannel) -> None:
        super().__init__()
        self.bot = bot
        self.salon = salon

    async def on_submit(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title=self.titre.value,
            description=self.contenu.value,
            color=discord.Color.orange(),
        )
        embed.add_field(
            name="Information",
            value="⚠️ Merci de lire cette annonce attentivement avant toute action.",
            inline=False,
        )
        embed.set_author(name="Création annonce")
        footer_text = self.footer.value.strip() if self.footer.value else f"Annonce par {interaction.user}"
        embed.set_footer(text=footer_text)
        await self.salon.send(embed=embed)
        await interaction.response.send_message(
            f"Annonce envoyée dans {self.salon.mention}.",
            ephemeral=True,
        )
