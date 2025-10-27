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
# チャット3文字ごとの端数を保持（ユーザーごと）
char_progress = {}

BALANCES_FILE = "balances.json"
INTEREST_RATE = (1.5 ** (1 / 365)) - 1  # 年利50%を日利換算

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
            "high_mode": False  # スロットの高確率モード
        }

# === チャット報酬（3文字ごとに1G。空白は除外） ===
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    uid = str(message.author.id)
    ensure_account(uid)

    # 全種類の空白を除去して文字数をカウント
    non_ws_len = len("".join(message.content.split()))
    if non_ws_len > 0:
        acc = char_progress.get(uid, 0) + non_ws_len
        gained = acc // 3           # 3文字ごとに1G
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
                continue  # AFKチャンネルは対象外
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
# discord.ext.tasks.loop の time= を使い、JSTの0時に起動する
JST = timezone(timedelta(hours=9))

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
@bot.tree.command(name="おみくじ", description="今日の運勢を占います！")
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

# === 銀行グループ ===
bank = discord.app_commands.Group(name="銀行", description="銀行関連のコマンドです")

@bank.command(name="1_残高確認", description="自分のG残高を確認します。")
async def bank_bal(i):
    uid = str(i.user.id)
    ensure_account(uid)
    w, b = balances[uid]["wallet"], balances[uid]["bank"]
    await i.response.send_message(f"👛 {i.user.display_name}の残高\n所持:{w}G 預金:{b}G", ephemeral=True)

@bank.command(name="2_送金", description="他のユーザーにGを送金します。")
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

@bank.command(name="3_預け入れ", description="所持Gを銀行に預けます。")
async def bank_dep(i, amt: int):
    uid = str(i.user.id)
    ensure_account(uid)
    if amt <= 0 or balances[uid]["wallet"] < amt:
        return await i.response.send_message("⚠️ 残高不足", ephemeral=True)
    balances[uid]["wallet"] -= amt
    balances[uid]["bank"] += amt
    save_data()
    await i.response.send_message(f"💰 {amt}G 預け入れました。\n👛 {balances[uid]['wallet']}G / 🏦 {balances[uid]['bank']}G", ephemeral=True)

@bank.command(name="4_引き出し", description="銀行からGを引き出します。")
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

# === カジノグループ ===
casino = discord.app_commands.Group(name="casino", description="カジノ関連のコマンドです")

# --- 所持Coin＆景品数確認 ---
@casino.command(name="1_所持coin_景品数確認", description="現在の所持Coinと景品数を確認します")
async def check_coin_items(i: discord.Interaction):
    uid = str(i.user.id)
    ensure_account(uid)
    u = balances[uid]
    items = u["items"]
    msg = (
        f"🎰 **{i.user.display_name} の所持状況**\n"
        f"🪙 Coin：{u['coin']}枚\n\n"
        f"🎁 景品：💴{items['large']} 💵{items['medium']} 💶{items['small']}"
    )
    await i.response.send_message(msg, ephemeral=True)

# --- Coin貸し出し ---
@casino.command(name="2_coin貸し出し", description="1Coin＝20Gで貸し出します。")
async def casino_loan(i, coin数: int):
    uid = str(i.user.id)
    ensure_account(uid)
    cost = coin数 * 20
    if coin数 <= 0 or balances[uid]["wallet"] < cost:
        return await i.response.send_message("👛 G不足", ephemeral=True)
    balances[uid]["wallet"] -= cost
    balances[uid]["coin"] += coin数
    save_data()
    await i.response.send_message(f"🪙 {coin数}Coin 貸出 (-{cost}G)", ephemeral=True)

# --- カウンター ---
@casino.command(name="3_カウンター", description="Coinを景品に交換（💴275Coin/💵55Coin/💶11Coin）")
async def casino_counter(i, coin数: int):
    uid = str(i.user.id)
    ensure_account(uid)
    u = balances[uid]
    if coin数 < 11:
        return await i.response.send_message("⚠️ 11Coin以上から交換可能です", ephemeral=True)
    if u["coin"] < coin数:
        return await i.response.send_message("🪙 Coin不足", ephemeral=True)
    L, rem = coin数 // 275, coin数 % 275
    M, rem = rem // 55, rem % 55
    S, rem = rem // 11, rem % 11
    used = L * 275 + M * 55 + S * 11
    u["coin"] -= used
    u["items"]["large"] += L
    u["items"]["medium"] += M
    u["items"]["small"] += S
    if rem > 0: u["coin"] += rem
    save_data()
    txt = [f"💴×{L}" if L else "", f"💵×{M}" if M else "", f"💶×{S}" if S else ""]
    txt = " ".join(t for t in txt if t)
    await i.response.send_message(f"🎁 交換結果：{txt}\n🪙 使用:{used} 残:{u['coin']}枚", ephemeral=True)

# --- 景品交換所 ---
@casino.command(name="4_景品交換所", description="景品をGで買い取り！（💴5000G/💵1000G/💶200G）")
async def casino_exchange(i):
    uid = str(i.user.id)
    ensure_account(uid)
    u = balances[uid]
    L, M, S = u["items"]["large"], u["items"]["medium"], u["items"]["small"]
    if L + M + S == 0:
        return await i.response.send_message("🎁 景品がありません。", ephemeral=True)
    L_t, M_t, S_t = L * 5000, M * 1000, S * 200
    total = L_t + M_t + S_t
    u["wallet"] += total
    u["items"] = {"large": 0, "medium": 0, "small": 0}
    save_data()
    det = []
    if L: det.append(f"💴×{L} → {L_t}G")
    if M: det.append(f"💵×{M} → {M_t}G")
    if S: det.append(f"💶×{S} → {S_t}G")
    await i.response.send_message(f"💱 交換結果：\n" + "\n".join(det) +
                                  f"\n💰 合計 {total}G 加算！\n👛 現在:{u['wallet']}G", ephemeral=True)

# --- スロット（💖系1/240・高確率モード＋斜めライン対応） ---
@casino.command(name="11_スロット", description="3Coinで1回転！")
async def casino_slot(i: discord.Interaction, from_button: bool = False):
    uid = str(i.user.id)
    ensure_account(uid)
    u = balances[uid]
    b = u.get("bonus_spins", 0)
    f = u.get("free_spin", False)
    high_mode = u.get("high_mode", False)

    # 1) 応答の確定
    if from_button:
        await i.response.defer(ephemeral=True)
        msg = await i.followup.send("🎰 リール回転中…", ephemeral=True)
    else:
        await i.response.send_message("🎰 スロットを起動中…", ephemeral=True)
        msg = await i.followup.send("🎰 リール回転中…", ephemeral=True)

    # 2) コイン消費
    if f:
        u["free_spin"] = False
    elif u["coin"] < 3:
        return await i.followup.send("🪙 Coin不足（3Coin必要）", ephemeral=True)
    else:
        u["coin"] -= 3

    # 3) 抽選（横/斜めの当たりラインをランダム）
    symbols = ["🔔", "🍇", "🔵", "🍒", "🤡", "💖", "💷"]
    roll = random.randint(1, 1000)
    board = [[random.choice(symbols) for _ in range(3)] for _ in range(3)]
    pay, text = 0, ""

    line_type = random.choice([0, 1, 2])   # 0:中央横, 1:↘斜め, 2:↙斜め
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
        elif roll <= 5:   # 1/240
            set_line(["💖","💖","💖"]); pay, u["bonus_spins"], text = 3, 30, "BIG BONUS!!"
        elif roll <= 9:   # 1/240
            set_line(["💖","💖","💷"]); pay, u["bonus_spins"], text = 3, 15, "REGULAR BONUS!!"
        elif roll <= 50:
            set_line(["🔔","🔔","🔔"]); pay, text = 15, "+15枚"
        elif roll <= 217:
            set_line(["🍇","🍇","🍇"]); pay, text = 8, "+8枚"
        elif roll <= 360:
            set_line(["🔵","🔵","🔵"]); u["free_spin"], text = True, "FREE SPIN!"
        # else: はずれ

    u["coin"] += pay
    save_data()

    # 4) 疑似回転と停止演出
    for _ in range(6):
        frame = "\n".join(" ".join(random.choice(symbols) for _ in range(3)) for _ in range(3))
        await msg.edit(content=f"🎰 リール回転中…\n{frame}")
        await asyncio.sleep(0.05)

    disp = [[random.choice(symbols) for _ in range(3)] for _ in range(3)]
    for c in range(3):
        for r in range(3): disp[r][c] = board[r][c]
        await msg.edit(content=f"🎰 リール回転中…\n" + "\n".join(" ".join(x) for x in disp))
        await asyncio.sleep(0.25 + c*0.15)

    # 5) 結果表示
    final_txt = "\n".join(" ".join(r) for r in board)
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="もう1回回す", style=discord.ButtonStyle.primary, custom_id="slot_retry"))
    mode_status = "（🎯BONUS高確率ゾーン中）" if u.get("high_mode", False) else ""
    await msg.edit(content=f"🎰 **{i.user.display_name} のスロット結果！**{mode_status}\n{final_txt}\n{text}\n🪙 現在：{u['coin']}枚", view=view)

# --- スロット再スピンボタン用（※重複定義なし） ---
@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.component and interaction.data.get("custom_id") == "slot_retry":
        # deferしてからボタン経由のスピンを実行
        await casino_slot(interaction, from_button=True)

# --- 12_100面ダイス ---
@casino.command(name="12_100面ダイス", description="0～100の数字を指定して賭け！最高200倍のCoinを獲得！")
async def casino_dice(i: discord.Interaction, number: int, bet: int):
    uid = str(i.user.id)
    ensure_account(uid)
    u = balances[uid]

    # 入力チェック
    if not (0 <= number <= 100):
        return await i.response.send_message("⚠️ 0～100の数字を指定してください。", ephemeral=True)
    if bet <= 0:
        return await i.response.send_message("⚠️ 1以上のCoinを指定してください。", ephemeral=True)
    if u["coin"] < bet:
        return await i.response.send_message("🪙 Coinが不足しています。", ephemeral=True)

    # コイン消費
    u["coin"] -= bet

    # ダイス
    dice = random.randint(0, 100)
    text = f"🎲 ダイスの出目は **{dice}**！\n🎯 {i.user.display_name}の予想: {number}\n"
    multiplier = 0

    def same_decade(num1, num2):
        def group(n): return ((n - 1) // 10) if n > 0 else 0
        return group(num1) == group(num2)

    is_double = (dice % 11 == 0 and dice != 0)
    same_tens = same_decade(dice, number)

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
        text += f"💫 ニアピン！同じ10の位！2倍のCoinを獲得！"
    else:
        text += f"😢 ハズレ…また挑戦しよう！"

    win = bet * multiplier
    u["coin"] += win
    save_data()

    text += f"\n\n🪙 賭け: {bet}枚\n🎁 獲得: {win}枚\n🪙 現在の所持Coin: {u['coin']}枚"
    await i.response.send_message(text, ephemeral=True)

bot.tree.add_command(casino)

# === 起動／終了時 ===
@bot.event
async def on_disconnect():
    save_data()

load_data()

@bot.event
async def on_ready():
    await bot.tree.sync()
    if not apply_interest.is_running():
        apply_interest.start()  # JST 0:00 に走る設定
    if not reward_voice_minutes.is_running():
        reward_voice_minutes.start()
    print("✅ コマンドを再同期しました！")
    print(f"✅ ログインしました: {bot.user}")

keep_alive()
bot.run(os.environ["DISCORD_TOKEN"])
