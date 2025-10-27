import discord, json, os, time, asyncio
from discord.ext import commands, tasks
from datetime import datetime
from keep_alive import keep_alive

# --- Bot設定 ---
intents = discord.Intents.default()
intents.message_content, intents.members, intents.voice_states = True, True, True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- グローバル変数 ---
balances, voice_times, last_message_time = {}, {}, {}
BALANCES_FILE = "balances.json"
INTEREST_RATE = 0.001  # 1日0.1%

# --- データ保存・読み込み ---
def save_data():
    temp = BALANCES_FILE + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(balances, f, ensure_ascii=False, indent=4)
    os.replace(temp, BALANCES_FILE)

def load_data():
    global balances
    if os.path.exists(BALANCES_FILE):
        try:
            with open(BALANCES_FILE, "r", encoding="utf-8") as f:
                balances.update(json.load(f))
        except json.JSONDecodeError:
            print("⚠️ balances.json が壊れています。新しく作り直します。")
            balances.clear()

def ensure_account(user_id):
    if user_id not in balances:
        balances[user_id] = {"wallet": 0, "bank": 10000, "last_interest": str(datetime.utcnow().date())}


# ==============================
# グループ外コマンド
# ==============================

#残高確認
@bot.tree.command(name="残高確認", description="あなたの現在の所持金と口座残高を確認します")
async def balance(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    ensure_account(uid)
    w, b = balances[uid]["wallet"], balances[uid]["bank"]
    await interaction.response.send_message(
        f"**{interaction.user.display_name} さんの残高**\n"
        f"現在の所持金： **{w}G**\n"
        f"預け入れ残高： **{b}G**",
        ephemeral=True
    )

#送金
@bot.tree.command(name="送金", description="他のユーザーに通貨を送ります（所持金から減額）")
async def pay(interaction: discord.Interaction, user: discord.User, amount: int):
    sid, rid = str(interaction.user.id), str(user.id)
    ensure_account(sid); ensure_account(rid)
    if amount <= 0:
        return await interaction.response.send_message("⚠️ 金額は1以上を指定してください。", ephemeral=True)
    if sid == rid:
        return await interaction.response.send_message("🤔 自分自身には送金できません。", ephemeral=True)
    if balances[sid]["wallet"] < amount:
        return await interaction.response.send_message("💸 所持金が不足しています。", ephemeral=True)
    balances[sid]["wallet"] -= amount
    balances[rid]["wallet"] += amount
    save_data()
    await interaction.response.send_message(
        f"{interaction.user.mention} から {user.mention} に **{amount}G** を送金しました！\n"
        f"あなたの現在の所持金： **{balances[sid]['wallet']}G**",
        ephemeral=True
    )


# ==============================
# 銀行グループコマンド
# ==============================

bank_group = discord.app_commands.Group(name="銀行", description="銀行関連のコマンド")

#預け入れ
@bank_group.command(name="預け入れ", description="指定した金額を銀行に預け入れます")
async def deposit(interaction: discord.Interaction, amount: int):
    uid = str(interaction.user.id)
    ensure_account(uid)
    if amount <= 0:
        return await interaction.response.send_message("⚠️ 金額は1以上を指定してください。", ephemeral=True)
    if balances[uid]["wallet"] < amount:
        return await interaction.response.send_message("💸 所持金が不足しています。", ephemeral=True)
    balances[uid]["wallet"] -= amount
    balances[uid]["bank"] += amount
    save_data()
    await interaction.response.send_message(
        f"{interaction.user.mention} さんが **{amount}G** を銀行に預け入れました！\n"
        f"現在の所持金： **{balances[uid]['wallet']}G**\n"
        f"預け入れ残高： **{balances[uid]['bank']}G**",
        ephemeral=True
    )

#引き出し
@bank_group.command(name="引き出し", description="指定した金額を銀行から引き出します")
async def withdraw(interaction: discord.Interaction, amount: int):
    uid = str(interaction.user.id)
    ensure_account(uid)
    if amount <= 0:
        return await interaction.response.send_message("⚠️ 金額は1以上を指定してください。", ephemeral=True)
    if balances[uid]["bank"] < amount:
        return await interaction.response.send_message("💸 銀行の残高が不足しています。", ephemeral=True)
    balances[uid]["bank"] -= amount
    balances[uid]["wallet"] += amount
    save_data()
    await interaction.response.send_message(
        f"ご利用ありがとうございます！ **{amount}G** を銀行から引き出しました。\n"
        f"現在の所持金： **{balances[uid]['wallet']}G**\n"
        f"預け入れ残高： **{balances[uid]['bank']}G**",
        ephemeral=True
    )

bot.tree.add_command(bank_group)


# ==============================
# チャット報酬（3文字で1G、5秒間隔）
# ==============================

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot: return
    uid = str(message.author.id)
    ensure_account(uid)
    now = time.time()
    if uid in last_message_time and (now - last_message_time[uid]) < 5:
        return await bot.process_commands(message)
    last_message_time[uid] = now
    c = len(message.content.strip())
    if c >= 3:
        r = c // 3
        balances[uid]["bank"] += r
        save_data()
    await bot.process_commands(message)


# ==============================
# ボイスチャット報酬（1分1G）
# ==============================

@bot.event
async def on_voice_state_update(member, before, after):
    uid = str(member.id)
    ensure_account(uid)
    if before.channel is None and after.channel is not None:
        voice_times[uid] = datetime.utcnow()
    elif before.channel is not None and after.channel is None and uid in voice_times:
        duration = datetime.utcnow() - voice_times.pop(uid)
        mins = int(duration.total_seconds() // 60)
        if mins > 0:
            balances[uid]["bank"] += mins
            save_data()


# ==============================
# 利息付与機能（1日ごとに0.1%複利）
# ==============================

@tasks.loop(hours=24)
async def apply_interest():
    today = datetime.utcnow().date()
    print("💰 利息計算中…")
    for uid, data in balances.items():
        ensure_account(uid)
        last_interest = datetime.strptime(data.get("last_interest", str(today)), "%Y-%m-%d").date()
        days = (today - last_interest).days
        if days > 0:
            for _ in range(days):
                data["bank"] = round(data["bank"] * (1 + INTEREST_RATE), 2)
            data["last_interest"] = str(today)
    save_data()
    print("✅ 利息付与完了。")


import random

# ==============================
# おみくじコマンド（特別報酬付き）
# ==============================

@bot.tree.command(name="おみくじ", description="今日の運勢を占います！")
async def omikuji(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    ensure_account(user_id)

    # 結果と確率設定（合計100%）
    results = [
        ("大大大吉", 1.0),
        ("大大吉", 3.0),
        ("大吉", 9.0),
        ("吉", 10.0),
        ("中吉", 20.0),
        ("小吉", 15.0),
        ("末吉", 20.0),
        ("凶", 10.0),
        ("大凶", 6.0),
        ("大大凶", 3.0),
        ("大大大凶", 1.0),
        ("ﾎﾟｷｭｰｰﾝ!! 鬼がかりBONUS 3000", 0.5),
        ("ﾍﾟｶｯ!! BIG BONUS", 1.5)
    ]

    names, weights = zip(*results)
    result = random.choices(names, weights=weights, k=1)[0]

    bonus_text = ""
    bonus_amount = 0

    # 特別報酬処理
    if result == "ﾎﾟｷｭｰｰﾝ!! 鬼がかりBONUS 3000":
        bonus_amount = 3000
        balances[user_id]["wallet"] += bonus_amount
        bonus_text = f"\n💥 **{bonus_amount}G** 獲得！"

    elif result == "ﾍﾟｶｯ!! BIG BONUS":
        bonus_amount = 300
        balances[user_id]["wallet"] += bonus_amount
        bonus_text = f"\n💥 **{bonus_amount}G** 獲得！"

    # 保存
    if bonus_amount > 0:
        save_data()

    await interaction.response.send_message(
        f"🎴 **{interaction.user.display_name} さんのおみくじ結果！**\n"
        f"✨ 今日の運勢は…… **{result}！！** ✨{bonus_text}",
        ephemeral=True
    )


# ==============================
# 共通処理・起動
# ==============================

@bot.event
async def on_disconnect(): save_data()

load_data()

@bot.event
async def on_ready():
    await bot.tree.sync()
    apply_interest.start()  # 利息タスク起動
    print("✅ コマンドを再同期しました！")
    print(f"✅ ログインしました: {bot.user}")

keep_alive()
bot.run(os.environ["DISCORD_TOKEN"])
