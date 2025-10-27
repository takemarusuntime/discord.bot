import discord, json, os, time, asyncio, random
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
from keep_alive import keep_alive

# --- Bot設定 ---
intents = discord.Intents.default()
intents.message_content, intents.members, intents.voice_states = True, True, True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- グローバル変数 ---
balances, voice_times, last_message_time = {}, {}, {}
BALANCES_FILE = "balances.json"
# 年利50%を日利に換算
INTEREST_RATE = (1.5 ** (1/365)) - 1  # 約0.1118%

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

def ensure_account(uid):
    if uid not in balances:
        balances[uid] = {"wallet": 0, "bank": 10000, "coin": 0, "last_interest": str(datetime.utcnow().date())}


# ==============================
# 🪙 チャット報酬・VC報酬・利息
# ==============================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    uid = str(message.author.id)
    ensure_account(uid)
    now = time.time()
    if uid in last_message_time and (now - last_message_time[uid]) < 5:
        return await bot.process_commands(message)
    last_message_time[uid] = now
    c = len(message.content.strip())
    if c >= 3:
        balances[uid]["bank"] += c // 3
        save_data()
    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member, before, after):
    uid = str(member.id)
    ensure_account(uid)
    if before.channel is None and after.channel is not None:
        voice_times[uid] = datetime.utcnow()
    elif before.channel is not None and after.channel is None and uid in voice_times:
        mins = int((datetime.utcnow() - voice_times.pop(uid)).total_seconds() // 60)
        if mins > 0:
            balances[uid]["bank"] += mins
            save_data()

@tasks.loop(hours=24)
async def apply_interest():
    jst = timezone(timedelta(hours=9))
    today = datetime.now(jst).date()
    for uid, data in balances.items():
        ensure_account(uid)
        last = datetime.strptime(data.get("last_interest", str(today)), "%Y-%m-%d").date()
        days = (today - last).days
        if days > 0:
            for _ in range(days):
                data["bank"] = round(data["bank"] * (1 + INTEREST_RATE), 2)
            data["last_interest"] = str(today)
    save_data()
    print(f"💰 {today} 利息を反映しました（年利50%・日利{INTEREST_RATE*100:.4f}%）")


# ==============================
# 🎴 おみくじ（独立）
# ==============================
@bot.tree.command(name="おみくじ", description="今日の運勢を占います！")
async def omikuji(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    ensure_account(uid)
    results = [
        ("大大大吉", 1.0), ("大大吉", 3.0), ("大吉", 9.0), ("吉", 10.0),
        ("中吉", 20.0), ("小吉", 15.0), ("末吉", 20.0), ("凶", 10.0),
        ("大凶", 6.0), ("大大凶", 3.0), ("大大大凶", 1.0),
        ("ﾎﾟｷｭｰｰﾝ!! 鬼がかりBONUS 3000", 0.5), ("ﾍﾟｶｯ!! BIG BONUS", 1.5)
    ]
    res = random.choices([r[0] for r in results], weights=[r[1] for r in results], k=1)[0]
    bonus = 3000 if res == "ﾎﾟｷｭｰｰﾝ!! 鬼がかりBONUS 3000" else 300 if res == "ﾍﾟｶｯ!! BIG BONUS" else 0
    if bonus:
        balances[uid]["wallet"] += bonus
        save_data()
    await interaction.response.send_message(
        f"🎴 **{interaction.user.display_name} さんのおみくじ結果！**\n✨ 今日の運勢は…… **{res}！！** ✨"
        + (f"\n💥 **{bonus}G** 獲得！" if bonus else ""), ephemeral=True)


# ==============================
# 🏦 bankグループ
# ==============================
bank_group = discord.app_commands.Group(name="bank", description="銀行関連のコマンド")

@bank_group.command(name="残高確認", description="あなたの現在の所持金と口座残高を確認します")
async def balance(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    ensure_account(uid)
    w, b = balances[uid]["wallet"], balances[uid]["bank"]
    await interaction.response.send_message(
        f"**{interaction.user.display_name} さんの残高**\n現在の所持金： **{w}G**\n預け入れ残高： **{b}G**", ephemeral=True)

@bank_group.command(name="送金", description="他のユーザーに通貨を送ります（所持金から減額）")
async def pay(interaction: discord.Interaction, user: discord.User, amount: int):
    sid, rid = str(interaction.user.id), str(user.id)
    ensure_account(sid)
    ensure_account(rid)
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
        f"あなたの現在の所持金： **{balances[sid]['wallet']}G**", ephemeral=True)

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
        f"現在の所持金： **{balances[uid]['wallet']}G**\n預け入れ残高： **{balances[uid]['bank']}G**", ephemeral=True)

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
        f"現在の所持金： **{balances[uid]['wallet']}G**\n預け入れ残高： **{balances[uid]['bank']}G**", ephemeral=True)

bot.tree.add_command(bank_group)


# ==============================
# 🎰 casinoグループ
# ==============================
casino_group = discord.app_commands.Group(name="casino", description="カジノゲーム関連のコマンド")

@casino_group.command(name="coin貸し出し", description="20Gで1Coinを購入（交換）します")
async def coin_loan(interaction: discord.Interaction, coin数: int):
    uid = str(interaction.user.id)
    ensure_account(uid)
    if coin数 <= 0:
        return await interaction.response.send_message("⚠️ 1以上のCoin数を指定してください。", ephemeral=True)
    cost = coin数 * 20
    if balances[uid]["wallet"] < cost:
        return await interaction.response.send_message("💸 所持金が不足しています。", ephemeral=True)
    balances[uid]["wallet"] -= cost
    balances[uid]["coin"] += coin数
    save_data()
    await interaction.response.send_message(
        f"🎟️ {interaction.user.display_name} さんに **{coin数} Coin** を貸し出しました！\n"
        f"💰 消費G：{cost}G\n👛 残高：{balances[uid]['wallet']}G\n🪙 保有Coin：{balances[uid]['coin']}枚", ephemeral=True)

@casino_group.command(name="景品交換所", description="10Coinごとに180Gを獲得します")
async def exchange_prizes(interaction: discord.Interaction, coin数: int):
    uid = str(interaction.user.id)
    ensure_account(uid)
    if coin数 <= 0 or coin数 % 10 != 0:
        return await interaction.response.send_message("⚠️ 交換は10Coin単位で指定してください。", ephemeral=True)
    if balances[uid]["coin"] < coin数:
        return await interaction.response.send_message("🪙 Coinが不足しています。", ephemeral=True)
    gain = (coin数 // 10) * 180
    balances[uid]["coin"] -= coin数
    balances[uid]["wallet"] += gain
    save_data()
    await interaction.response.send_message(
        f"🏆 {interaction.user.display_name} さんが **{coin数} Coin** を景品交換しました！\n"
        f"💵 獲得：{gain}G\n👛 所持金：{balances[uid]['wallet']}G\n🪙 残りCoin：{balances[uid]['coin']}枚", ephemeral=True)

@casino_group.command(name="ダイス", description="1〜100の数字を選んでCoinを賭け、ダイス勝負！")
async def dice(interaction: discord.Interaction, number: int, bet: int):
    uid = str(interaction.user.id)
    ensure_account(uid)
    if not (1 <= number <= 100):
        return await interaction.response.send_message("🎯 数字は1〜100で指定してください。", ephemeral=True)
    if bet <= 0:
        return await interaction.response.send_message("💰 賭けCoinは1枚以上にしてください。", ephemeral=True)
    if balances[uid]["coin"] < bet:
        return await interaction.response.send_message("🪙 Coinが不足しています。", ephemeral=True)

    balances[uid]["coin"] -= bet
    dice = random.randint(1, 100)
    w = 0

    if dice == number:
        w = bet * 30
        balances[uid]["coin"] += w
        msg = f"🎯 **的中！** 出目{dice}！💎 賭けCoinの30倍 **{w} Coin** 獲得！"
    elif dice % 11 == 0:
        w = bet * 2
        balances[uid]["coin"] += w
        msg = f"🎰 **ゾロ目ボーナス！** 出目{dice}！ 賭けCoinの2倍 **{w} Coin** 獲得！"
    else:
        msg = f"🎲 出目{dice}！😢 残念、賭けCoin {bet} 枚は失われました。"

    save_data()
    await interaction.response.send_message(
        f"🎲 **{interaction.user.display_name} のダイスチャレンジ！**\n選んだ数字：{number}\n{msg}\n🪙 現在の保有Coin：{balances[uid]['coin']}枚",
        ephemeral=True)

bot.tree.add_command(casino_group)


# ==============================
# ⚙️ 起動処理
# ==============================
@bot.event
async def on_disconnect():
    save_data()

load_data()

@bot.event
async def on_ready():
    await bot.tree.sync()
    apply_interest.start()
    print("✅ コマンドを再同期しました！")
    print(f"✅ ログインしました: {bot.user}")

keep_alive()
bot.run(os.environ["DISCORD_TOKEN"])
