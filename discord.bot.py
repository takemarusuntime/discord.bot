import discord
from discord.ext import commands
import json
import os
from datetime import datetime

# --- Bot設定 ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True  # VC監視に必要
bot = commands.Bot(command_prefix="!", intents=intents)

# --- グローバル変数 ---
balances = {}  # 各ユーザーの所持金と預金残高を管理
voice_times = {}  # VC報酬管理用 {user_id: 入室時刻(datetime)}

# --- JSONファイル ---
BALANCES_FILE = "balances.json"


# --- データ保存（安全版） ---
def save_data():
    """balances.json の安全保存（破損防止）"""
    temp_file = BALANCES_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(balances, f, ensure_ascii=False, indent=4)
    os.replace(temp_file, BALANCES_FILE)


# --- データ読み込み（例外処理付き） ---
def load_data():
    """balances.json の読み込み（破損時は初期化）"""
    global balances
    if os.path.exists(BALANCES_FILE):
        try:
            with open(BALANCES_FILE, "r", encoding="utf-8") as f:
                balances.update(json.load(f))
        except json.JSONDecodeError:
            print("⚠️ balances.json が壊れています。新しく作り直します。")
            balances.clear()


# --- ユーザーデータ初期化 ---
def ensure_account(user_id):
    if user_id not in balances:
        balances[user_id] = {"wallet": 1000, "bank": 0}  # 初期所持金1,000G


# ==============================
# グループ外コマンド
# ==============================

# --- 残高確認 ---
@bot.tree.command(name="残高確認", description="あなたの現在の所持金と口座残高を確認します")
async def balance(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    ensure_account(user_id)

    wallet = balances[user_id]["wallet"]
    bank = balances[user_id]["bank"]

    await interaction.response.send_message(
        f"**{interaction.user.display_name} さんの残高**\n"
        f"現在の所持金： **{wallet}G**\n"
        f"預け入れ残高： **{bank}G**",
        ephemeral=True
    )


# --- 送金 ---
@bot.tree.command(name="送金", description="他のユーザーに通貨を送ります（所持金から減額）")
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
        f"{interaction.user.mention} から {user.mention} に **{amount}G** を送金しました！\n"
        f"あなたの現在の所持金： **{balances[sender_id]['wallet']}G**",
        ephemeral=True
    )


# ==============================
# 銀行グループコマンド
# ==============================

bank_group = discord.app_commands.Group(name="銀行", description="銀行関連のコマンド")


# --- 預け入れ ---
@bank_group.command(name="預け入れ", description="指定した金額を銀行に預け入れます")
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
        f"{interaction.user.mention} さんが **{amount}G** を銀行に預け入れました！\n"
        f"現在の所持金： **{balances[user_id]['wallet']}G**\n"
        f"預け入れ残高： **{balances[user_id]['bank']}G**",
        ephemeral=True
    )


# --- 引き出し ---
@bank_group.command(name="引き出し", description="指定した金額を銀行から引き出します")
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
        f"{interaction.user.mention} さんが **{amount}G** を銀行から引き出しました。\n"
        f"現在の所持金： **{balances[user_id]['wallet']}G**\n"
        f"預け入れ残高： **{balances[user_id]['bank']}G**",
        ephemeral=True
    )


# --- グループ登録 ---
bot.tree.add_command(bank_group)


# ==============================
# チャット文字数報酬機能（1文字1G）
# ==============================

@bot.event
async def on_message(message: discord.Message):
    # Bot自身の発言は無視
    if message.author.bot:
        return

    user_id = str(message.author.id)
    ensure_account(user_id)

    char_count = len(message.content.strip())  # メッセージの文字数
    if char_count > 0:
        balances[user_id]["bank"] += char_count  # 1文字ごとに1G
        save_data()

    # 他のコマンドも動作するように必要
    await bot.process_commands(message)


# ==============================
# ボイスチャット報酬機能（1分1G）
# ==============================

@bot.event
async def on_voice_state_update(member, before, after):
    user_id = str(member.id)
    ensure_account(user_id)

    # ✅ 入室
    if before.channel is None and after.channel is not None:
        voice_times[user_id] = datetime.utcnow()

    # ✅ 退出
    elif before.channel is not None and after.channel is None:
        if user_id in voice_times:
            join_time = voice_times.pop(user_id)
            duration = datetime.utcnow() - join_time
            minutes = int(duration.total_seconds() // 60)

            if minutes > 0:
                reward = minutes * 1  # 1分ごとに1G
                balances[user_id]["bank"] += reward
                save_data()


# ==============================
# 共通処理・起動
# ==============================

@bot.event
async def on_disconnect():
    save_data()

load_data()

@bot.event
async def on_ready():
    await bot.tree.sync()
    print("✅ コマンドを再同期しました！")
    print(f"✅ ログインしました: {bot.user}")

from keep_alive import keep_alive
keep_alive()

bot.run(os.environ["DISCORD_TOKEN"])
