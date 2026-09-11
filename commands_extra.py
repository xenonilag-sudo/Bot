# =========================================================
# commands_extra.py
# Economy / Shop / Inventory / Item
# =========================================================

import discord
from discord.ext import commands

import messages


# =========================================================
# SHOP CONFIG
# =========================================================

MUTE_PRICE = 100

# Thời gian mute
MUTE_DURATION_MINUTES = 20


# =========================================================
# ECONOMY COG
# =========================================================

class EconomyCommands(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    # =====================================================
    # MONEY
    # =====================================================

    @commands.command(
        name="money",
        aliases=[
            "coin",
            "coins",
            "xu"
        ]
    )
    async def money(self, ctx):

        balance = self.bot.get_balance(
            ctx.author.id
        )

        await ctx.send(
            messages.BALANCE.format(
                user=ctx.author.mention,
                balance=balance
            )
        )

    # =====================================================
    # SHOP
    # =====================================================

    @commands.command(
        name="shop"
    )
    async def shop(self, ctx):

        embed = discord.Embed(
            title=messages.SHOP_TITLE,
            color=discord.Color.gold()
        )

        embed.add_field(
            name="🔇 Mute",
            value=messages.SHOP_MUTE.format(
                price=MUTE_PRICE,
                minutes=MUTE_DURATION_MINUTES
            ),
            inline=False
        )

        embed.set_footer(
            text=messages.SHOP_FOOTER.format(
                prefix=self.bot.prefix
            )
        )

        await ctx.send(
            embed=embed
        )

    # =====================================================
    # BUY
    # =====================================================

    @commands.command(
        name="buy",
        aliases=["mua"]
    )
    async def buy(
        self,
        ctx,
        item=None
    ):

        if not item:

            await ctx.send(
                messages.BUY_USAGE.format(
                    prefix=self.bot.prefix
                )
            )

            return

        item = item.lower().strip()

        if item not in (
            "mute",
            "🔇"
        ):

            await ctx.send(
                messages.ITEM_NOT_FOUND.format(
                    item=item
                )
            )

            return

        success = self.bot.remove_money(
            ctx.author.id,
            MUTE_PRICE
        )

        if not success:

            balance = self.bot.get_balance(
                ctx.author.id
            )

            await ctx.send(
                messages.NOT_ENOUGH_MONEY.format(
                    price=MUTE_PRICE,
                    balance=balance
                )
            )

            return

        self.bot.add_item(
            ctx.author.id,
            "mute",
            1
        )

        balance = self.bot.get_balance(
            ctx.author.id
        )

        await ctx.send(
            messages.PURCHASE_SUCCESS.format(
                item="🔇 Mute",
                price=MUTE_PRICE,
                balance=balance
            )
        )

    # =====================================================
    # INVENTORY
    # =====================================================

    @commands.command(
        name="inventory",
        aliases=[
            "inv",
            "tui",
            "bag"
        ]
    )
    async def inventory(self, ctx):

        mute_count = self.bot.get_item_count(
            ctx.author.id,
            "mute"
        )

        if mute_count <= 0:

            await ctx.send(
                messages.INVENTORY_EMPTY
            )

            return

        embed = discord.Embed(
            title=messages.INVENTORY_TITLE,
            color=discord.Color.blurple()
        )

        embed.add_field(
            name="🔇 Mute",
            value=messages.INVENTORY_MUTE.format(
                quantity=mute_count
            ),
            inline=False
        )

        await ctx.send(
            embed=embed
        )

    # =====================================================
    # USE ITEM
    # =====================================================

    @commands.command(
        name="use",
        aliases=["dung"]
    )
    async def use_item(
        self,
        ctx,
        item=None,
        member: discord.Member = None
    ):

        if not item:

            await ctx.send(
                messages.MUTE_USAGE.format(
                    prefix=self.bot.prefix
                )
            )

            return

        item = item.lower().strip()

        if item != "mute":

            await ctx.send(
                messages.ITEM_NOT_FOUND.format(
                    item=item
                )
            )

            return

        if member is None:

            await ctx.send(
                messages.MUTE_USAGE.format(
                    prefix=self.bot.prefix
                )
            )

            return

        if member.id == ctx.author.id:

            await ctx.send(
                messages.MUTE_SELF
            )

            return

        if member.bot:

            await ctx.send(
                messages.MUTE_BOT
            )

            return

        # =============================================
        # Check inventory
        # =============================================

        item_count = self.bot.get_item_count(
            ctx.author.id,
            "mute"
        )

        if item_count <= 0:

            await ctx.send(
                messages.NO_MUTE_ITEM.format(
                    prefix=self.bot.prefix
                )
            )

            return

        # =============================================
        # Remove item
        # =============================================

        removed = self.bot.remove_item(
            ctx.author.id,
            "mute",
            1
        )

        if not removed:

            await ctx.send(
                messages.NO_MUTE_ITEM.format(
                    prefix=self.bot.prefix
                )
            )

            return

        # =============================================
        # Apply mute
        # =============================================

        self.bot.mute_user(
            ctx.channel.id,
            member.id,
            MUTE_DURATION_MINUTES
        )

        await ctx.send(
            messages.MUTE_SUCCESS.format(
                user=member.mention,
                minutes=MUTE_DURATION_MINUTES
            )
        )


# =========================================================
# SETUP
# =========================================================

async def setup(bot):

    await bot.add_cog(
        EconomyCommands(bot)
    )
