import discord
from discord.ext import commands
from discord import app_commands

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)


# -------------------------------------
#  新規参加時：Guest ロール付与（無ければ作成）
# -------------------------------------
@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild

    guest_role = discord.utils.get(guild.roles, name="Guest")

    # Guestロールが無ければ自動生成
    if guest_role is None:
        guest_role = await guild.create_role(
            name="Guest",
            color=discord.Color.light_grey(),
            reason="Guestロール自動生成"
        )

    # 新規参加者へ付与
    await member.add_roles(guest_role, reason="新規参加によりGuest付与")


# -------------------------------------
#  ボタン UI
# -------------------------------------
class AgreeButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="同意する",
        style=discord.ButtonStyle.success
    )
    async def agree(self, interaction: discord.Interaction, button: discord.ui.Button):

        guild = interaction.guild
        member = interaction.user

        # Member ロール探す（無ければ作成）
        member_role = discord.utils.get(guild.roles, name="Member")
        if member_role is None:
            member_role = await guild.create_role(
                name="Member",
                color=discord.Color.blue(),
                reason="Memberロール自動生成"
            )

        # Guest ロール探す
        guest_role = discord.utils.get(guild.roles, name="Guest")

        # Member付与
        await member.add_roles(member_role, reason="同意ボタン押下によりMember付与")

        # Guest外す
        if guest_role in member.roles:
            await member.remove_roles(guest_role, reason="同意完了のためGuest外し")

        # ★ 完全サイレント
        await interaction.response.defer(ephemeral=True)


# -------------------------------------
#  /z0_同意ボタン
# -------------------------------------
@bot.tree.command(
    name="z0_同意ボタン",
    description="同意ボタンを設置します"
)
async def z0_auth_button(interaction: discord.Interaction):

    view = AgreeButton()

    await interaction.response.send_message(
        "ボタンを押すと **上記の内容に同意した** ものとします。",
        view=view
    )


# -------------------------------------
# 起動時処理
# -------------------------------------
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"ログイン完了: {bot.user}")


# =========================
# TOKEN で起動
# =========================
bot.run("DISCORD_TOKEN")
