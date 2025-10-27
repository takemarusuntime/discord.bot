import discord, json, os, time, asyncio, random
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
from datetime import time as dtime  # JST 0:00 実行用
from keep_alive import keep_alive

# === Bot設定 ===
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)

balances, voice_times, last_message_time = {}, {}, {}
char_progress = {}  # チャット3文字ごとの端数管理

BALANCES_FILE = "balances.json"
INTEREST_RATE = (1.5 ** (1 / 365)) - 1  # 年利50%を日利換算
JST = timezone(timedelta(hours=9))

# === データ管理 ===
def save_data():
    tmp = BALANCES_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(balances, f, ensure_ascii=False, indent=4)
    os.replace(tmp, BALANCES_FILE)

def load_data():
    global balances
    if os.path.exists(BALANCES_FILE):
        try:
            with open(BALANCES_FILE, "r", encoding="utf-8") as f:
                balances.update(json.load(f))
        except:
            print("⚠️ balances.json 破損 → 再生成")
            balances.clear()
            save_data()

def ensure_account(uid):
    if uid not in balances:
        balances[uid] = {
            "wallet": 10000,
            "bank": 0,
            "coin": 0,
            "last_interest": str(datetime.utcnow().date()),
            "items": {"large": 0, "medium": 0, "small": 0},
            "high_mode": False
        }

# === チャット報酬（3文字ごとに1G。空白は除外） ===
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    uid = str(message.author.id)
    ensure_account(uid)
    non_ws_len = len("".join(message.content.split()))
    if non_ws_len > 0:
        acc = char_progress.get(uid, 0) + non_ws_len
        gained = acc // 3
        char_progress[uid] = acc % 3
        if gained > 0:
            balances[uid]["wallet"] += gained
            save_data()
    await bot.process_commands(message)

# === VC滞在報酬（1分ごとに在室メンバーへ1G。AFKは除外） ===
@tasks.loop(minutes=1)
async def reward_voice_minutes():
    total_awards = 0
    for guild in bot.guilds:
        afk = guild.afk_channel
        for vc in guild.voice_channels:
            if afk and vc.id == afk.id:
                continue
            for member in vc.members:
                if member.bot:
                    continue
                uid = str(member.id)
                ensure_account(uid)
                balances[uid]["wallet"] += 1
                total_awards += 1
    if total_awards:
        save_data()

# === 利息（JST 0:00に厳密実行） ===
@tasks.loop(time=dtime(hour=0, minute=0, second=0, tzinfo=JST))
async def apply_interest():
    today = datetime.now(JST).date()
    for uid, data in balances.items():
        ensure_account(uid)
        last = datetime.strptime(data.get("last_interest", str(today)), "%Y-%m-%d").date()
        days = (today - last).days
        if days > 0:
            for _ in range(days):
                data["bank"] = round(data["bank"] * (1 + INTEREST_RATE), 2)
            data["last_interest"] = str(today)
    save_data()
    print(f"💰 {today} 利息反映（日利 {INTEREST_RATE * 100:.4f}%）")

# === おみくじ ===
@bot.tree.command(name="0-おみくじ", description="今日の運勢を占います！")
async def omikuji(i):
    uid = str(i.user.id)
    ensure_account(uid)
    res_w = [
        ("大大大吉", 1), ("大大吉", 3), ("大吉", 9), ("吉", 10), ("中吉", 20),
        ("小吉", 15), ("末吉", 20), ("凶", 10), ("大凶", 6), ("大大凶", 3), ("大大大凶", 1),
        ("ﾎﾟｷｭｰｰﾝ!! 鬼がかりBONUS3000", 0.5), ("ﾍﾟｶｯ!!BIGBONUS", 1.5)
    ]
    res = random.choices([r[0] for r in res_w], weights=[r[1] for r in res_w])[0]
    bonus = 3000 if "鬼がかり" in res else 300 if "BIG" in res else 0
    if bonus:
        balances[uid]["wallet"] += bonus
        save_data()
    await i.response.send_message(
        f"🎴 **{i.user.display_name}の運勢！**\n✨{res}✨" +
        (f"\n💥 {bonus}G獲得！" if bonus else ""),
        ephemeral=True
    )

# === 銀行コマンド群 ===
bank = discord.app_commands.Group(name="1-銀行", description="銀行関連のコマンドです")

@bank.command(name="1_残高確認")
async def bank_bal(i):
    uid = str(i.user.id)
    ensure_account(uid)
    w, b = balances[uid]["wallet"], balances[uid]["bank"]
    await i.response.send_message(f"👛 {i.user.display_name}\n所持:{w}G 預金:{b}G", ephemeral=True)

@bank.command(name="2_送金")
async def bank_pay(i, user: discord.User, amt: int):
    s, r = str(i.user.id), str(user.id)
    ensure_account(s)
    ensure_account(r)
    if amt <= 0:
        return await i.response.send_message("⚠️ 1以上を指定", ephemeral=True)
    if s == r:
        return await i.response.send_message("🤔 自分に送金不可", ephemeral=True)
    if balances[s]["wallet"] < amt:
        return await i.response.send_message("👛 残高不足", ephemeral=True)
    balances[s]["wallet"] -= amt
    balances[r]["wallet"] += amt
    save_data()
    await i.response.send_message(f"{i.user.mention} ➡ {user.mention} に {amt}G 送金", ephemeral=True)

@bank.command(name="3_預け入れ")
async def bank_dep(i, amt: int):
    uid = str(i.user.id)
    ensure_account(uid)
    if amt <= 0 or balances[uid]["wallet"] < amt:
        return await i.response.send_message("⚠️ 残高不足", ephemeral=True)
    balances[uid]["wallet"] -= amt
    balances[uid]["bank"] += amt
    save_data()
    await i.response.send_message(f"💰 {amt}G 預け入れました。\n👛 {balances[uid]['wallet']}G / 🏦 {balances[uid]['bank']}G", ephemeral=True)

@bank.command(name="4_引き出し")
async def bank_wd(i, amt: int):
    uid = str(i.user.id)
    ensure_account(uid)
    if amt <= 0 or balances[uid]["bank"] < amt:
        return await i.response.send_message("⚠️ 残高不足", ephemeral=True)
    balances[uid]["bank"] -= amt
    balances[uid]["wallet"] += amt
    save_data()
    await i.response.send_message(f"💰 {amt}G 引き出し\n👛 {balances[uid]['wallet']}G / 🏦 {balances[uid]['bank']}G", ephemeral=True)

bot.tree.add_command(bank)

# === カジノ機能群 ===
casino = discord.app_commands.Group(name="2-casino", description="カジノ関連のコマンドです")

# --- スロットボタン用ビュー（安定版） ---
class SlotView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
    @discord.ui.button(label="もう1回回す", style=discord.ButtonStyle.primary, custom_id="slot_retry")
    async def retry(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.response.is_done():
            await interaction.response.defer()
        await casino_slot(interaction, from_button=True)

# --- スロット ---
@casino.command(name="11_スロット", description="3Coinで1回転！BB成立で360枚！")
async def casino_slot(i: discord.Interaction, from_button: bool = False):
    uid = str(i.user.id)
    ensure_account(uid)
    u = balances[uid]
    b = u.get("bonus_spins", 0)
    f = u.get("free_spin", False)
    high_mode = u.get("high_mode", False)

    # 応答の確定
    if from_button:
        if not i.response.is_done():
            await i.response.defer()
        msg = await i.followup.send("🎰 リール回転中…", ephemeral=True)
    else:
        await i.response.send_message("🎰 スロットを起動中…", ephemeral=True)
        msg = await i.followup.send("🎰 リール回転中…", ephemeral=True)

    # コイン消費
    if f:
        u["free_spin"] = False
    elif u["coin"] < 3:
        return await i.followup.send("🪙 Coin不足（3Coin必要）", ephemeral=True)
    else:
        u["coin"] -= 3

    # 抽選
    symbols = ["🔔", "🍇", "🔵", "🍒", "🤡", "💖", "💷"]
    roll = random.randint(1, 1000)
    board = [[random.choice(symbols) for _ in range(3)] for _ in range(3)]
    pay, text = 0, ""

    line_type = random.choice([0, 1, 2])
    def set_line(arr):
        if line_type == 0:
            for c in range(3): board[1][c] = arr[c]
        elif line_type == 1:
            for n in range(3): board[n][n] = arr[n]
        else:
            for n in range(3): board[n][2-n] = arr[n]

    if b > 0:
        set_line(["🔔","🔔","🔔"]); pay, text = 15, "+15枚"; u["bonus_spins"] -= 1
    else:
        if roll <= 1:
            set_line(["🤡","🤡","🤡"]); pay, text = 10, "+10枚 🎯 BONUS高確率ゾーン突入！"; u["high_mode"] = True
        elif high_mode and roll <= 17:
            set_line(["💖","💖","💖"]); pay, u["bonus_spins"], text = 3, 30, "BIG BONUS!!"; u["high_mode"] = False
        elif high_mode and roll <= 34:
            set_line(["💖","💖","💷"]); pay, u["bonus_spins"], text = 3, 15, "REGULAR BONUS!!"; u["high_mode"] = False
        elif roll <= 5:
            set_line(["💖","💖","💖"]); pay, u["bonus_spins"], text = 3, 30, "BIG BONUS!!"
        elif roll <= 9:
            set_line(["💖","💖","💷"]); pay, u["bonus_spins"], text = 3, 15, "REGULAR BONUS!!"
        elif roll <= 50:
            set_line(["🔔","🔔","🔔"]); pay, text = 15, "+15枚"
        elif roll <= 217:
            set_line(["🍇","🍇","🍇"]); pay, text = 8, "+8枚"
        elif roll <= 360:
            set_line(["🔵","🔵","🔵"]); u["free_spin"], text = True, "FREE SPIN!"

    u["coin"] += pay
    save_data()

    # 疑似回転
    for _ in range(6):
        frame = "\n".join(" ".join(random.choice(symbols) for _ in range(3)) for _ in range(3))
        await msg.edit(content=f"🎰 リール回転中…\n{frame}")
        await asyncio.sleep(0.05)

    disp = [[random.choice(symbols) for _ in range(3)] for _ in range(3)]
    for c in range(3):
        for r in range(3): disp[r][c] = board[r][c]
        await msg.edit(content=f"🎰 リール回転中…\n" + "\n".join(" ".join(x) for x in disp))
        await asyncio.sleep(0.25 + c*0.15)

    # 結果表示
    final_txt = "\n".join(" ".join(r) for r in board)
    view = SlotView()
    mode_status = "（🎯BONUS高確率ゾーン中）" if u.get("high_mode", False) else ""
    await msg.edit(content=f"🎰 **{i.user.display_name} のスロット結果！**{mode_status}\n{final_txt}\n{text}\n🪙 現在：{u['coin']}枚", view=view)

# --- 12_100面ダイス ---
@casino.command(name="12_100面ダイス", description="0～100の数字を指定して賭け！最高200倍のCoinを獲得！")
async def casino_dice(i: discord.Interaction, number: int, bet: int):
    uid = str(i.user.id)
    ensure_account(uid)
    u = balances[uid]

    # --- 入力チェック ---
    if not (0 <= number <= 100):
        return await i.response.send_message("⚠️ 0～100の数字を指定してください。", ephemeral=True)
    if bet <= 0:
        return await i.response.send_message("⚠️ 1以上のCoinを指定してください。", ephemeral=True)
    if u["coin"] < bet:
        return await i.response.send_message("🪙 Coinが不足しています。", ephemeral=True)

    # --- コイン消費 ---
    u["coin"] -= bet

    # --- ダイスを振る ---
    dice = random.randint(0, 100)
    text = f"🎲 ダイスの出目は **{dice}**！\n🎯 {i.user.display_name}の予想: {number}\n"
    multiplier = 0

    # --- 判定補助関数 ---
    def same_decade(num1, num2):
        """1～10, 11～20, ..., 91～100 のグループで比較"""
        def group(n): return ((n - 1) // 10) if n > 0 else 0
        return group(num1) == group(num2)

    # --- 特殊判定 ---
    is_double = (dice % 11 == 0 and dice != 0)  # ゾロ目（11,22,...,99,100）
    same_tens = same_decade(dice, number)       # 同じ10の位

    # --- 結果分岐 ---
    if dice == number and is_double:
        multiplier = 200
        text += f"💥 **当たり＆ゾロ目！200倍の大当たり！！** 💥"
    elif dice == number:
        multiplier = 40
        text += f"🎯 **的中！40倍のCoinを獲得！**"
    elif is_double:
        multiplier = 5
        text += f"✨ ゾロ目ボーナス！5倍のCoinを獲得！"
    elif same_tens:
        multiplier = 2
        text += f"💫 ニアピン！2倍のCoinを獲得！"
    else:
        text += f"😢 ハズレ…また挑戦しよう！"

    # --- 結果反映 ---
    win = bet * multiplier
    u["coin"] += win
    save_data()

    # --- 結果表示 ---
    text += f"\n\n🪙 賭け: {bet}枚\n🎁 獲得: {win}枚\n🪙 現在の所持Coin: {u['coin']}枚"
    await i.response.send_message(text, ephemeral=True)

bot.tree.add_command(casino)

# === 起動/終了処理 ===
@bot.event
async def on_disconnect():
    save_data()

load_data()

@bot.event
async def on_ready():
    await bot.tree.sync()
    if not apply_interest.is_running():
        apply_interest.start()
    if not reward_voice_minutes.is_running():
        reward_voice_minutes.start()
    print("✅ コマンド再同期完了")
    print(f"✅ ログイン: {bot.user}")

keep_alive()
bot.run(os.environ["DISCORD_TOKEN"])
