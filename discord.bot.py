import discord
from discord.ext import commands
import json
import os

# --- Bot設定 ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- グローバル変数 ---
balances = {}  # 各ユーザーの所持金と預金残高を管理

# --- JSONファイル ---
BALANCES_FILE = "balances.json"

# --- データ読み込み ---
def load_data():
    global balances
    if os.path.exists(BALANCES_FILE):
        with open(BALANCES_FILE, "r", encoding="utf-8") as f:
            balances.update(json.load(f))

# --- データ保存 ---
def save_data():
    with open(BALANCES_FILE, "w", encoding="utf-8") as f:
        json.dump(balances, f, ensure_ascii=False, indent=4)

# --- ユーザーデータ初期化 ---
def ensure_account(user_id):
    if user_id not in balances:
        balances[user_id] = {"wallet": 10000, "bank": 0}  # 初期所持金10,000G


# --- 残高確認コマンド ---
@bot.tree.command(name="balance", description="現在の所持金と預け入れ残高を確認します")
async def balance(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    ensure_account(user_id)

    wallet = balances[user_id]["wallet"]
    bank = balances[user_id]["bank"]

    await interaction.response.send_message(
        f"💳 **{interaction.user.display_name} さんの残高**\n"
        f"👛 所持金（ウォレット）: **{wallet}G**\n"
        f"🏦 預け入れ残高（バンク）: **{bank}G**",
        ephemeral=True
    )


# --- 預け入れコマンド ---
@bot.tree.command(name="deposit", description="指定した金額を銀行に預け入れます")
async def deposit(interaction: discord.Interaction, amount: int):
    user_id = str(interaction.user.id)
    ensure_account(user_id)

    if amount <= 0:
        await interaction.response.send_message("⚠️ 金額は1以上を指定してください。", ephemeral=True)
        return

    if balances[user_id]["wallet"] < amount:
        await interaction.response.send_message("💸 所持金が不足しています。", ephemeral=True)
        return

    balances[user_id]["wallet"] -= amount
    balances[user_id]["bank"] += amount
    save_data()

    await interaction.response.send_message(
        f"💰 {interaction.user.mention} さんが **{amount}G** を銀行に預け入れました！\n"
        f"👛 現在の所持金: **{balances[user_id]['wallet']}G**\n"
        f"🏦 預け入れ残高: **{balances[user_id]['bank']}G**",
        ephemeral=True
    )


# --- 引き出しコマンド ---
@bot.tree.command(name="withdraw", description="銀行から指定した金額を引き出します")
async def withdraw(interaction: discord.Interaction, amount: int):
    user_id = str(interaction.user.id)
    ensure_account(user_id)

    if amount <= 0:
        await interaction.response.send_message("⚠️ 金額は1以上を指定してください。", ephemeral=True)
        return

    if balances[user_id]["bank"] < amount:
        await interaction.response.send_message("💸 銀行の残高が不足しています。", ephemeral=True)
        return

    balances[user_id]["bank"] -= amount
    balances[user_id]["wallet"] += amount
    save_data()

    await interaction.response.send_message(
        f"🏧 {interaction.user.mention} さんが **{amount}G** を銀行から引き出しました。\n"
        f"👛 現在の所持金: **{balances[user_id]['wallet']}G**\n"
        f"🏦 預け入れ残高: **{balances[user_id]['bank']}G**",
        ephemeral=True
    )


# --- 送金コマンド ---
@bot.tree.command(name="pay", description="他のユーザーに通貨を送ります（所持金から減額）")
async def pay(interaction: discord.Interaction, user: discord.User, amount: int):
    sender_id = str(interaction.user.id)
    receiver_id = str(user.id)
    ensure_account(sender_id)
    ensure_account(receiver_id)

    if amount <= 0:
        await interaction.response.send_message("⚠️ 金額は1以上を指定してください。", ephemeral=True)
        return
    if sender_id == receiver_id:
        await interaction.response.send_message("🤔 自分自身には送金できません。", ephemeral=True)
        return

    if balances[sender_id]["wallet"] < amount:
        await interaction.response.send_message("💸 所持金が不足しています。", ephemeral=True)
        return

    balances[sender_id]["wallet"] -= amount
    balances[receiver_id]["wallet"] += amount
    save_data()

    await interaction.response.send_message(
        f"✅ {interaction.user.mention} から {user.mention} に **{amount}G** を送金しました！\n"
        f"👛 あなたの現在の所持金: **{balances[sender_id]['wallet']}G**",
        ephemeral=True
    )


# --- データ読み込み ---
load_data()

# --- 起動時ログ ---
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ ログインしました: {bot.user}")


from keep_alive import keep_alive
keep_alive()

# --- Bot起動 ---
bot.run(os.environ["DISCORD_TOKEN"])
