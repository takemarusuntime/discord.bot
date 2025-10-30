import discord, json, os, time, asyncio, random
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
from datetime import time as dtime  # JST 0:00 実行用
from keep_alive import keep_alive



# --- Bot設定 ---
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



# --- データ管理 ---
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
            "high_mode": False}



# --- チャット報酬(3文字1G) ---
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



# --- VC滞在報酬(1分1G) ---
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



# --- 利子(00:00日利配布) ---
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



# --- おみくじ ---
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
        ephemeral=True)



# --- 銀行 ---
bank = discord.app_commands.Group(name="1-銀行", description="銀行関連のコマンドです")



# --- 残高確認 ---
@bank.command(name="1_残高確認")
async def bank_bal(i):
    uid = str(i.user.id)
    ensure_account(uid)
    w, b = balances[uid]["wallet"], balances[uid]["bank"]
    await i.response.send_message(f"💰 {i.user.display_name}\n所持:{w}G 預金:{b}G", ephemeral=True)



# --- 送金 ---
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



# --- 預け入れ ---
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



# --- 引き出し ---
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



# --- CASINO ---
casino = discord.app_commands.Group(name="2-casino", description="カジノ関連のコマンドです")



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
async def casino_loan(i: discord.Interaction, coin数: int):
    uid = str(i.user.id)
    ensure_account(uid)
    cost = coin数 * 20
    if coin数 <= 0 or balances[uid]["wallet"] < cost:
        return await i.response.send_message("💰 G不足", ephemeral=True)
    balances[uid]["wallet"] -= cost
    balances[uid]["coin"] += coin数
    save_data()
    await i.response.send_message(f"🪙 {coin数}Coin 貸出 (-{cost}G)", ephemeral=True)



# --- カウンター ---
@casino.command(name="3_カウンター", description="Coinを景品に交換（💴275Coin/💵55Coin/💶11Coin）")
async def casino_counter(i: discord.Interaction, coin数: int):
    uid = str(i.user.id)
    ensure_account(uid)
    u = balances[uid]

    # 入力チェック
    if coin数 < 11:
        return await i.response.send_message("⚠️ 11Coin以上から交換可能です", ephemeral=True)
    if u["coin"] < coin数:
        return await i.response.send_message("🪙 Coin不足", ephemeral=True)

    # 交換処理
    L, rem = coin数 // 275, coin数 % 275
    M, rem = rem // 55, rem % 55
    S, rem = rem // 11, rem % 11
    used = L * 275 + M * 55 + S * 11

    u["coin"] -= used
    u["items"]["large"] += L
    u["items"]["medium"] += M
    u["items"]["small"] += S
    if rem > 0:
        u["coin"] += rem

    save_data()

    txt = [f"💴×{L}" if L else "", f"💵×{M}" if M else "", f"💶×{S}" if S else ""]
    txt = " ".join(t for t in txt if t)
    await i.response.send_message(f"🎁 交換結果：{txt}\n🪙 使用:{used} 残:{u['coin']}枚", ephemeral=True)



# --- 景品交換所 ---
@casino.command(name="4_景品交換所", description="景品をGで買い取ります（💴5000G/💵1000G/💶200G）")
async def casino_exchange(i: discord.Interaction):
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
    if L:
        det.append(f"💴×{L} → {L_t}G")
    if M:
        det.append(f"💵×{M} → {M_t}G")
    if S:
        det.append(f"💶×{S} → {S_t}G")

    await i.response.send_message(
        f"💱 交換結果：\n" + "\n".join(det) +
        f"\n💰 合計 {total}G 加算！\n👛 現在:{u['wallet']}G",
        ephemeral=True)



# --- スロット ---
@casino.command(name="11_🎰スロット", description="設定1")
async def casino_slot(i: discord.Interaction):
    await i.response.defer(ephemeral=True)
    msg = await i.followup.send("🎰 スロットを起動中…", ephemeral=True)
    await run_slot(i, msg)

# --- 確認ビュー ---
class SlotView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id

    @discord.ui.button(label="もう1回転", style=discord.ButtonStyle.primary)
    async def retry(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 他人による押下を防止
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("これは他のユーザーのスロットです！", ephemeral=True)

        # ✅ すぐに defer（タイムアウト防止）
        await interaction.response.defer(ephemeral=True)

        # followup で新たにメッセージを返す（元メッセージは放置OK）
        msg = await interaction.followup.send("🎰 リール回転中…", ephemeral=True)
        await run_slot(interaction, msg)

# --- スロット本体処理（共通関数化） ---
async def run_slot(i: discord.Interaction, msg: discord.Message):
    uid = str(i.user.id)
    ensure_account(uid)
    u = balances[uid]
    b = u.get("bonus_spins", 0)
    f = u.get("free_spin", False)
    high_mode = u.get("high_mode", False)

    # --- コイン消費 ---
    if f:
        u["free_spin"] = False
    elif u["coin"] < 3:
        return await msg.edit(content="🪙 Coin不足（3Coin必要）", view=None)
    else:
        u["coin"] -= 3

    # --- 抽選（確率リセット版） ---
    symbols = ["🔔", "🍇", "🔵", "🍒", "🤡", "💖", "💷"]
    roll = random.randint(1, 1000)
    board = [[random.choice(symbols) for _ in range(3)] for _ in range(3)]
    pay, text = 0, ""

    # --- 成立ラインをランダム選択（上・中・下・斜め） ---
    line_type = random.choice([0, 1, 2, 3, 4])
    def set_line(arr):
        if line_type == 0:      # 上段
            for c in range(3): board[0][c] = arr[c]
        elif line_type == 1:    # 中段
            for c in range(3): board[1][c] = arr[c]
        elif line_type == 2:    # 下段
            for c in range(3): board[2][c] = arr[c]
        elif line_type == 3:    # 斜め ↘
            for n in range(3): board[n][n] = arr[n]
        elif line_type == 4:    # 斜め ↙
            for n in range(3): board[n][2 - n] = arr[n]

    # --- 抽選テーブル ---
    if b > 0:
        # BONUS中確定ベル（払い出し枚数はここで変更可）
        set_line(["🍒","🍒","🍒"])
        pay, text = 30, "+30枚"
        u["bonus_spins"] -= 1

    else:
        if roll <= 1:  # 🤡 1/1000
            set_line(["🤡","🤡","🤡"])
            pay, text = 10, "+10枚 🎯 BONUS高確率ゾーン突入！"
            u["high_mode"] = True

        elif high_mode and roll <= 5:  # BONUS合算1/240 → 約4/1000をBONUS抽選
            if random.choice([True, False]):
                # BIG BONUS
                set_line(["💖","💖","💖"])
                pay, u["bonus_spins"], text = 3, 10, "BIG BONUS!!"
            else:
                # REGULAR BONUS
                set_line(["💖","💖","💷"])
                pay, u["bonus_spins"], text = 3, 5, "REGULAR BONUS!!"
            u["high_mode"] = False

        elif roll <= 50:  # 🔔 1/20
            set_line(["🔔","🔔","🔔"])
            pay, text = 15, "+15枚"

        elif roll <= 150:  # 🍇 1/10
            set_line(["🍇","🍇","🍇"])
            pay, text = 8, "+8枚"

        elif roll <= 293:  # 🔵 1/7
            set_line(["🔵","🔵","🔵"])
            u["free_spin"], text = True, "FREE SPIN!"

        else:
            # ハズレ
            pass

    u["coin"] += pay
    save_data()

    # --- 疑似回転アニメ ---
    for _ in range(2):
        frame = "\n".join(" ".join(random.choice(symbols) for _ in range(3)) for _ in range(3))
        await msg.edit(content=f"🎰 リール回転中…\n{frame}")
        await asyncio.sleep(0.03)

    disp = [[random.choice(symbols) for _ in range(3)] for _ in range(3)]
    for c in range(3):
        for r in range(3):
            disp[r][c] = board[r][c]
        await msg.edit(content=f"🎰 リール回転中…\n" + "\n".join(" ".join(x) for x in disp))
        await asyncio.sleep(0.25 + c * 0.15)

    # --- 結果表示 ---
    final_txt = "\n".join(" ".join(r) for r in board)
    view = SlotView(i.user.id)
    mode_status = "（🎯BONUS高確率ゾーン中）" if u.get("high_mode", False) else ""
    await msg.edit(
        content=(f"🎰 **{i.user.display_name} のスロット結果！**{mode_status}\n"
                 f"{final_txt}\n{text}\n🪙 現在：{u['coin']}枚"),
        view=view)



# --- 12_100面ダイス ---
@casino.command(name="12_🎲100面ダイス", description="0～100の数字を当てろ！")
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
        multiplier = 500
        text += f"💥 **当たり＆ゾロ目！500倍の大当たり！！** 💥"
    elif dice == number:
        multiplier = 100
        text += f"🎯 **的中！100倍のCoinを獲得！**"
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



# --- チンチロ ---
@casino.command(name="13_チンチロ", description="加藤一二三と加藤一一一")
async def casino_chinchiro(i: discord.Interaction, bet: int = 10, opponent: discord.User = None):
    uid = str(i.user.id)
    ensure_account(uid)
    u = balances[uid]

    # --- ベットチェック ---
    if bet <= 0:
        return await i.response.send_message("🪙 ベット額は1以上を指定してください。", ephemeral=True)
    if u["coin"] < bet:
        return await i.response.send_message(f"🪙 コインが足りません（{bet}Coin必要）", ephemeral=True)

    # --- 対戦相手を決定 ---
    is_bot = False
    if opponent is None or opponent.bot:
        opponent_name = "ディーラーBot"
        is_bot = True
    else:
        opponent_name = opponent.display_name
        oid = str(opponent.id)
        ensure_account(oid)
        o = balances[oid]
        if o["coin"] < bet:
            return await i.response.send_message(f"{opponent.mention} のコインが不足しています。", ephemeral=True)
        u["coin"] -= bet
        o["coin"] -= bet
        save_data()

    # --- サイコロ処理関数 ---
    def roll_dice():
        return [random.randint(1, 6) for _ in range(3)]

    def get_yaku(rolls):
        rolls.sort()
        a, b, c = rolls
        # 特殊役
        if a == b == c:
            if a == 1:
                return (7, "💎 ピンゾロ（1・1・1）"), 7  # 最強
            return (6 + a, f"🎯 {a}{a}{a}のゾロ目！"), 6
        if rolls == [1, 2, 3]:
            return (-2, "💀 ヒフミ（1・2・3）"), 0
        if rolls == [4, 5, 6]:
            return (6, "🌟 シゴロ（4・5・6）"), 5
        # 通常役
        if a == b:
            return (c, f"🎲 目:{c}（{a}{a}{c}）"), 1
        if b == c:
            return (a, f"🎲 目:{a}（{b}{b}{a}）"), 1
        return (0, "💤 目なし（ハズレ）"), 0

    def compare(player, dealer):
        p_val, p_txt = player[0]
        d_val, d_txt = dealer[0]
        p_rank = player[1]
        d_rank = dealer[1]

        if p_rank > d_rank or (p_rank == d_rank and p_val > d_val):
            return "win", f"🎉 あなたの勝ち！ {p_txt} > {d_txt}"
        elif p_rank < d_rank or (p_rank == d_rank and p_val < d_val):
            return "lose", f"💥 あなたの負け… {p_txt} < {d_txt}"
        else:
            return "draw", f"🤝 引き分け ({p_txt} = {d_txt})"

    # --- ダイスロール ---
    player_rolls = roll_dice()
    dealer_rolls = roll_dice()
    player = get_yaku(player_rolls)
    dealer = get_yaku(dealer_rolls)

    result, text = compare(player, dealer)

    # --- 配当倍率 ---
    def get_multiplier(yaku_rank, val):
        # yaku_rank=7 → ピンゾロ, 6 → ゾロ目, 5 → シゴロ
        if yaku_rank == 7:
            return 10
        elif yaku_rank == 6:
            return 5
        elif yaku_rank == 5:
            return 3
        return 2  # 通常勝利

    # --- 結果処理 ---
    reward = 0
    if result == "win":
        mult = get_multiplier(player[1], player[0][0])
        reward = bet * mult
        u["coin"] += reward
        if not is_bot:
            pass  # 対人の場合、相手はすでにベットを消費済み
        outcome = f"🎯 勝利！ ×{mult}倍配当！ +{reward}Coin"
    elif result == "lose":
        outcome = f"💥 敗北！ -{bet}Coin"
        if not is_bot:
            mult = get_multiplier(dealer[1], dealer[0][0])
            balances[oid]["coin"] += bet * mult
    else:
        # 引き分け
        u["coin"] += bet
        if not is_bot:
            balances[oid]["coin"] += bet
        outcome = f"🤝 引き分け（ベット返却）"

    save_data()

    # --- 結果表示 ---
    msg = (
        f"🎲 **{i.user.display_name} のチンチロ勝負！**\n\n"
        f"対戦相手：**{opponent_name}**\n\n"
        f"あなたの出目：{player_rolls} → {player[0][1]}\n"
        f"{opponent_name}の出目：{dealer_rolls} → {dealer[0][1]}\n\n"
        f"{text}\n"
        f"{outcome}\n"
        f"🪙 現在の残高：{u['coin']}Coin")

    await i.response.send_message(msg, ephemeral=True)



# --- ブラックジャック ---
@casino.command(name="14_🃏ブラックジャック", description="カードの数字が21に近いほうが勝ち！")
async def casino_blackjack_advanced(i: discord.Interaction, bet: int = 10):
    uid = str(i.user.id)
    ensure_account(uid)
    u = balances[uid]

    if bet <= 0:
        return await i.response.send_message("🪙 ベット額は1以上を指定してください。", ephemeral=True)
    if u["coin"] < bet:
        return await i.response.send_message(f"🪙 コインが足りません（{bet}Coin必要）", ephemeral=True)

    # --- コインを消費 ---
    u["coin"] -= bet
    save_data()

    deck = [f"{r}{s}" for s in ["♠", "♥", "♦", "♣"] for r in ["A","K","Q","J","10","9","8","7","6","5","4","3","2"]]
    random.shuffle(deck)

    player_hand = [deck.pop(), deck.pop()]
    dealer_hand = [deck.pop(), deck.pop()]
    split_hand = None
    is_doubled = False

    def hand_value(hand):
        value, aces = 0, 0
        for c in hand:
            rank = c[:-1]
            if rank in ["K","Q","J","10"]:
                value += 10
            elif rank == "A":
                aces += 1
                value += 11
            else:
                value += int(rank)
        while value > 21 and aces:
            value -= 10
            aces -= 1
        return value

    def can_split(hand):
        return len(hand) == 2 and hand[0][:-1] == hand[1][:-1]

    def show_status(hidden=True, extra=""):
        p_val = hand_value(player_hand)
        dealer_val = hand_value([dealer_hand[0]]) if hidden else hand_value(dealer_hand)
        dealer_txt = dealer_hand[0] + " ??" if hidden else " ".join(dealer_hand)
        split_txt = f"\n✂️ 分割手: {' '.join(split_hand)} = {hand_value(split_hand)}" if split_hand else ""
        return (
            f"🃏 **{i.user.display_name} のブラックジャック！**\n"
            f"ベット額: {bet}Coin\n\n"
            f"あなたの手札: {' '.join(player_hand)} = {p_val}\n"
            f"ディーラー: {dealer_txt} {'(伏せ札あり)' if hidden else f'= {dealer_val}'}\n"
            f"{split_txt}\n{extra}")

    # --- メインゲームビュー ---
    class BlackjackAdvancedView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=120)

        # --- ヒット ---
        @discord.ui.button(label="ヒット", style=discord.ButtonStyle.primary)
        async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != i.user.id:
                return await interaction.response.send_message("あなたのゲームではありません！", ephemeral=True)
            player_hand.append(deck.pop())
            if hand_value(player_hand) > 21:
                self.disable_all_items()
                await interaction.response.edit_message(
                    content=f"{show_status(False)}\n💥 バースト！ あなたの負けです… (-{bet}枚)", view=self)
                save_data()
                return
            await interaction.response.edit_message(content=show_status(True), view=self)

        # --- スタンド ---
        @discord.ui.button(label="スタンド", style=discord.ButtonStyle.success)
        async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != i.user.id:
                return await interaction.response.send_message("あなたのゲームではありません！", ephemeral=True)

            # --- ディーラーのターン ---
            dealer_v = hand_value(dealer_hand)
            while dealer_v < 17:
                dealer_hand.append(deck.pop())
                dealer_v = hand_value(dealer_hand)

            p_val = hand_value(player_hand)
            result = ""
            if dealer_v > 21 or p_val > dealer_v:
                win = bet * (3 if is_doubled else 2)
                u["coin"] += win
                result = f"🎉 勝利！ +{win}Coin"
            elif p_val == dealer_v:
                u["coin"] += bet
                result = "🤝 引き分け！ ベット返却"
            else:
                result = f"💥 敗北！ -{bet}Coin"

            save_data()
            self.disable_all_items()
            await interaction.response.edit_message(
                content=f"{show_status(False)}\n{result}\n🪙 現在の残高: {u['coin']}Coin",
                view=self)

        # --- ダブルダウン（賭け金倍・1回引いて終了） ---
        @discord.ui.button(label="ダブルダウン", style=discord.ButtonStyle.danger)
        async def double_down(self, interaction: discord.Interaction, button: discord.ui.Button):
            nonlocal is_doubled
            if interaction.user.id != i.user.id:
                return await interaction.response.send_message("あなたのゲームではありません！", ephemeral=True)
            if u["coin"] < bet:
                return await interaction.response.send_message("🪙 コイン不足でダブルできません。", ephemeral=True)

            u["coin"] -= bet
            save_data()
            is_doubled = True
            player_hand.append(deck.pop())
            p_val = hand_value(player_hand)
            if p_val > 21:
                self.disable_all_items()
                return await interaction.response.edit_message(
                    content=f"{show_status(False)}\n💥 バースト！ ダブル失敗… (-{bet*2}枚)", view=self)

            # --- ディーラーターン ---
            dealer_v = hand_value(dealer_hand)
            while dealer_v < 17:
                dealer_hand.append(deck.pop())
                dealer_v = hand_value(dealer_hand)

            result = ""
            if dealer_v > 21 or p_val > dealer_v:
                win = bet * 4  # ダブル勝利は4倍払い
                u["coin"] += win
                result = f"🔥 ダブル成功！ +{win}Coin"
            elif p_val == dealer_v:
                u["coin"] += bet * 2
                result = "🤝 引き分け（ダブル） ベット返却"
            else:
                result = f"💥 敗北！ -{bet*2}Coin"

            save_data()
            self.disable_all_items()
            await interaction.response.edit_message(
                content=f"{show_status(False)}\n{result}\n🪙 現在の残高: {u['coin']}Coin",
                view=self)

        # --- スプリット（同ランク2枚時のみ） ---
        @discord.ui.button(label="スプリット", style=discord.ButtonStyle.secondary)
        async def split(self, interaction: discord.Interaction, button: discord.ui.Button):
            nonlocal split_hand
            if interaction.user.id != i.user.id:
                return await interaction.response.send_message("あなたのゲームではありません！", ephemeral=True)
            if not can_split(player_hand):
                return await interaction.response.send_message("✂️ スプリットできません（同じカードが必要）", ephemeral=True)
            if u["coin"] < bet:
                return await interaction.response.send_message("🪙 コイン不足でスプリットできません。", ephemeral=True)

            u["coin"] -= bet
            save_data()
            split_hand = [player_hand.pop(), deck.pop()]
            player_hand.append(deck.pop())
            await interaction.response.edit_message(content=show_status(True, "✂️ スプリットしました！"), view=self)

    await i.response.defer(ephemeral=True)
    await i.followup.send(show_status(True), ephemeral=True, view=BlackjackAdvancedView())



# --- ハイ＆ロー ---
@casino.command(name="15_🃏ハイアンドロー", description="次のカードが高いか低いかを当てよう！")
async def casino_highlow(i: discord.Interaction, bet: int = 10):
    uid = str(i.user.id)
    ensure_account(uid)
    u = balances[uid]

    # --- ベット額チェック ---
    if bet <= 0:
        return await i.response.send_message("🪙 ベット額は1以上を指定してください。", ephemeral=True)
    if u["coin"] < bet:
        return await i.response.send_message(f"🪙 コインが足りません（{bet}Coin必要）", ephemeral=True)

    # --- コイン消費 ---
    u["coin"] -= bet
    save_data()

    # --- 山札生成 ---
    deck = [f"{r}{s}" for s in ["♠", "♥", "♦", "♣"] for r in ["A","K","Q","J","10","9","8","7","6","5","4","3","2"]]
    random.shuffle(deck)

    rank_order = {"A":14, "K":13, "Q":12, "J":11, "10":10, "9":9, "8":8, "7":7, "6":6, "5":5, "4":4, "3":3, "2":2}
    current_card = deck.pop()
    streak = 0  # 連勝数

    def card_value(card):
        return rank_order[card[:-1]]

    def show_status(extra=""):
        return (
            f"🎴 **{i.user.display_name} のハイ＆ロー！**\n\n"
            f"🪙 ベット額: {bet}Coin\n"
            f"現在のカード: **{current_card}**\n"
            f"連勝数: {streak}\n"
            f"{extra}\n"
            f"🪙 残高: {u['coin']}Coin")

    # --- メインゲームビュー ---
    class HighLowView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=120)

        @discord.ui.button(label="HIGH 🔺", style=discord.ButtonStyle.primary)
        async def high(self, interaction: discord.Interaction, button: discord.ui.Button):
            await self.judge(interaction, "HIGH")

        @discord.ui.button(label="LOW 🔻", style=discord.ButtonStyle.danger)
        async def low(self, interaction: discord.Interaction, button: discord.ui.Button):
            await self.judge(interaction, "LOW")

        async def judge(self, interaction: discord.Interaction, choice: str):
            nonlocal current_card, streak
            if interaction.user.id != i.user.id:
                return await interaction.response.send_message("あなたのゲームではありません！", ephemeral=True)

            if not deck:
                return await interaction.response.send_message("カードが尽きました！再スタートしてください。", ephemeral=True)

            new_card = deck.pop()
            current_val = card_value(current_card)
            new_val = card_value(new_card)

            win = False
            if new_val == current_val:
                result = f"😐 同値 ({current_card} → {new_card}) 引き分け（ノーカウント）"
            elif (new_val > current_val and choice == "HIGH") or (new_val < current_val and choice == "LOW"):
                win = True
                streak += 1
                result = f"✅ 正解！ ({current_card} → {new_card})"
            else:
                result = f"💥 ハズレ！ ({current_card} → {new_card})"

            current_card = new_card

            if not win:
                self.disable_all_items()
                await interaction.response.edit_message(
                    content=f"{show_status(result)}\n❌ ゲーム終了！ 連勝記録：{streak}\n(-{bet}枚)",
                    view=self)
                save_data()
                return

            # 勝利時：報酬倍率は連勝ごとに上昇
            reward = int(bet * (2 ** streak))
            await interaction.response.edit_message(
                content=f"{show_status(result)}\n🎯 現在の倍率：x{2 ** streak}（次に勝てば +{reward}Coin）\n続けますか？",
                view=self)

        @discord.ui.button(label="降りる 🏁", style=discord.ButtonStyle.success)
        async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
            nonlocal streak
            if interaction.user.id != i.user.id:
                return await interaction.response.send_message("あなたのゲームではありません！", ephemeral=True)

            if streak == 0:
                msg = f"😔 降りました。勝利なし (-{bet}Coin)"
            else:
                reward = int(bet * (2 ** streak))
                u["coin"] += reward
                msg = f"🪙 降りました！ +{reward}Coin 獲得！ 🎉（{streak}連勝）"
                save_data()

            self.disable_all_items()
            await interaction.response.edit_message(content=f"{show_status(msg)}", view=self)

    await i.response.defer(ephemeral=True)
    await i.followup.send(show_status(), ephemeral=True, view=HighLowView())



bot.tree.add_command(casino)



# --- ルーレット ---
@casino.command(name="16_🎯ルーレット", description="赤・黒・数字・範囲に賭けるルーレット！対戦相手をBotまたはユーザーから選択可能。")
async def casino_roulette(i: discord.Interaction, bet: int, opponent: discord.User = None):
    uid = str(i.user.id)
    ensure_account(uid)
    u = balances[uid]

    if bet <= 0:
        return await i.response.send_message("💰 ベット額は1以上にしてください。", ephemeral=True)
    if u["coin"] < bet:
        return await i.response.send_message("🪙 コインが不足しています。", ephemeral=True)

    # --- 対戦相手 ---
    is_bot = False
    if opponent is None or opponent.bot:
        opponent_name = "🎰 ディーラーBot"
        is_bot = True
    else:
        oid = str(opponent.id)
        ensure_account(oid)
        o = balances[oid]
        if o["coin"] < bet:
            return await i.response.send_message(f"{opponent.mention} のコインが不足しています。", ephemeral=True)
        opponent_name = opponent.display_name

    view = RouletteMainView(i.user.id, bet, opponent, is_bot)
    await i.response.send_message(
        f"🎡 **ルーレット開始！**\nベット額：{bet}Coin\n対戦相手：{opponent_name}\n\nどのタイプに賭けますか？",
        view=view,
        ephemeral=True)


# === メインボタンビュー（3行構成） ===
class RouletteMainView(discord.ui.View):
    def __init__(self, user_id: int, bet: int, opponent, is_bot: bool):
        super().__init__(timeout=90)
        self.user_id = user_id
        self.bet = bet
        self.opponent = opponent
        self.is_bot = is_bot

        # 1行目：色と数字指定
        self.add_item(ColorButton(self, "red", "🟥", discord.ButtonStyle.danger, row=0))
        self.add_item(ColorButton(self, "black", "⬛", discord.ButtonStyle.secondary, row=0))
        self.add_item(ColorButton(self, "0", "🟩", discord.ButtonStyle.success, row=0))
        self.add_item(NumberSelectButton(self, row=0))

        # 2行目：2倍・3倍の範囲
        for label in ["0-18", "19-36", "0-12", "13-24", "25-36"]:
            self.add_item(RangeButton(self, label, row=1))

        # 3行目：6倍の範囲
        for label in ["0-6", "7-12", "13-18", "19-24", "25-30", "31-36"]:
            self.add_item(RangeButton(self, label, row=2))

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("これは他のユーザーのルーレットです！", ephemeral=True)
            return False
        return True


# === ボタン定義 ===
class NumberSelectButton(discord.ui.Button):
    def __init__(self, view_parent, row=0):
        super().__init__(label="数字指定", style=discord.ButtonStyle.primary, row=row)
        self.view_parent = view_parent

    async def callback(self, i: discord.Interaction):
        await i.response.send_message("🎯 数字（0〜36）を入力してください：", ephemeral=True)

        def check(msg):
            return msg.author.id == self.view_parent.user_id and msg.content.isdigit()

        try:
            msg = await i.client.wait_for("message", check=check, timeout=20)
            number = msg.content
            await msg.delete()
            await spin_roulette(i, number, self.view_parent.bet, self.view_parent.opponent, self.view_parent.is_bot)
        except asyncio.TimeoutError:
            await i.followup.send("⌛ 入力がなかったためキャンセルしました。", ephemeral=True)


class ColorButton(discord.ui.Button):
    def __init__(self, view_parent, value, emoji, style, row=0):
        super().__init__(label=emoji, style=style, row=row)
        self.value = value
        self.view_parent = view_parent

    async def callback(self, i: discord.Interaction):
        await i.response.defer(ephemeral=True)
        await spin_roulette(i, self.value, self.view_parent.bet, self.view_parent.opponent, self.view_parent.is_bot)


class RangeButton(discord.ui.Button):
    def __init__(self, view_parent, label, row=1):
        super().__init__(label=label, style=discord.ButtonStyle.primary, row=row)
        self.label_text = label
        self.view_parent = view_parent

    async def callback(self, i: discord.Interaction):
        await i.response.defer(ephemeral=True)
        await spin_roulette(i, self.label_text, self.view_parent.bet, self.view_parent.opponent, self.view_parent.is_bot)


# === スピン処理 ===
async def spin_roulette(i: discord.Interaction, choice, bet, opponent, is_bot):
    uid = str(i.user.id)
    ensure_account(uid)
    u = balances[uid]

    # --- アニメーション ---
    msg = await i.followup.send("🎡 ルーレットが回転中…", ephemeral=True)
    emojis = ["🟥", "⬛", "🟩"]
    for _ in range(15):
        await msg.edit(content=f"🎡 ルーレットが回転中… {random.choice(emojis)}")
        await asyncio.sleep(0.12)

    # --- 結果 ---
    result = random.randint(0, 36)
    if result == 0:
        color, emoji = "green", "🟩"
    elif result % 2 == 0:
        color, emoji = "black", "⬛"
    else:
        color, emoji = "red", "🟥"

    # --- 判定 ---
    win = False
    multiplier = 0

    # 色
    if choice in ["red", "black"] and choice == color:
        multiplier = 2; win = True
    # 数字
    elif choice.isdigit() and int(choice) == result:
        num = int(choice)
        multiplier = 100 if num == 0 else 36
        win = True
    # 範囲
    elif "-" in choice:
        low, high = map(int, choice.split("-"))
        if low <= result <= high:
            diff = high - low + 1
            if diff == 18: multiplier = 2
            elif diff == 12: multiplier = 3
            elif diff == 7: multiplier = 6  # e.g. 0-6
            elif diff == 6: multiplier = 6  # 7-12 等
            win = True

    # --- 配当処理 ---
    if win:
        payout = bet * multiplier
        u["coin"] += payout
        result_text = f"🎉 当たり！ ×{multiplier}倍！ (+{payout}Coin)"
    else:
        u["coin"] -= bet
        result_text = f"💀 はずれ… (-{bet}Coin)"

    save_data()
    await msg.edit(content=f"🎯 結果：{emoji} **{result} ({color})**\n{result_text}\n🪙 あなたの残高：{u['coin']}Coin")



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
