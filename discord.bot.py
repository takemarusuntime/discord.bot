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
balances = {}  # ユーザー残高

# --- JSONファイル ---
BALANCES_FILE = "balances.json"

# --- データ読み込み ---
def load_data():
    global balances
    if os.path.exists(BALANCES_FILE):
        with open(BALANCES_FILE, "r") as f:
            balances.update(json.load(f))

# --- データ保存 ---
def save_data():
    with open(BALANCES_FILE, "w") as f:
        json.dump(balances, f)


# --- 送金コマンド(エフェメラル、スラッシュコマンド) ---
@bot.tree.command(name="pay", description="他のユーザーに通貨を送ります")
async def pay(interaction: discord.Interaction, user: discord.User, amount: int):
    sender_id = str(interaction.user.id)
    receiver_id = str(user.id)

    if amount <= 0:
        await interaction.response.send_message("⚠️ 金額は1以上を指定してください。", ephemeral=True)
        return
    if sender_id == receiver_id:
        await interaction.response.send_message("🤔 自分自身には送金できません。", ephemeral=True)
        return

    sender_balance = balances.get(sender_id, 0)
    if sender_balance < amount:
        await interaction.response.send_message("💸 残高が不足しています。", ephemeral=True)
        return

    # 送金処理
    balances[sender_id] -= amount
    balances[receiver_id] = balances.get(receiver_id, 0) + amount
    save_data()  # ← 修正済み ✅

    # 送金者の新しい残高を取得
    sender_new_balance = balances[sender_id]

    # 結果を送信（送金者にのみ表示）
    await interaction.response.send_message(
        f"✅ {interaction.user.mention} から {user.mention} に **{amount}G** を送金しました！\n\n"
        f"💰 あなたの残高: **{sender_new_balance}G**",
        ephemeral=True
    )


# 起動時にデータ読み込み
load_data()

# --- 起動時ログ ---
@bot.event
async def on_ready():
    await bot.tree.sync()  # ← スラッシュコマンドを同期するために追加
    print(f"✅ ログインしました: {bot.user}")


from keep_alive import keep_alive
keep_alive()

# --- Botを起動する ---
bot.run(os.environ["DISCORD_TOKEN"])
