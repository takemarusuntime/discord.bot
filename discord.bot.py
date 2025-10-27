import discord, json, os, time, asyncio, random
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
from keep_alive import keep_alive

# === Bot設定 ===
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)

balances, voice_times, last_message_time = {}, {}, {}
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
            "wallet": 0,
            "bank": 10000,
            "coin": 0,
            "last_interest": str(datetime.utcnow().date()),
            "items": {"large": 0, "medium": 0, "small": 0},
            "high_mode": False  # ← 追加済み
        }

# === 利息 ===
@tasks.loop(hours=24)
async def apply_interest():
    jst = timezone(timedelta(hours=9))
    today = datetime.now(jst).date()
    for uid, data in balances.items():
        ensure_account(uid)
        last = datetime.strptime(data.get("last_interest", str(today)), "%Y-%m-%d").date()
        days = (today - last).days
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
@casino.command(name="2_Coin貸し出し", description="1Coin＝20Gで貸し出します。")
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

# --- スロット（💖系1/240・高確率モード対応） ---
@casino.command(name="11_スロット", description="3Coinで1回転！（🤡後はBIG/REG確率UP）")
async def casino_slot(i: discord.Interaction):
    uid = str(i.user.id)
    ensure_account(uid)
    u = balances[uid]
    b = u.get("bonus_spins", 0)
    f = u.get("free_spin", False)
    high_mode = u.get("high_mode", False)

    if f:
        u["free_spin"] = False
    elif u["coin"] < 3:
        return await i.response.send_message("🪙 Coin不足（3Coin必要）", ephemeral=True)
    else:
        u["coin"] -= 3

    await i.response.send_message("🎰 スロットを起動中…", ephemeral=True)
    m = await i.followup.send("🎰 リール回転中…", ephemeral=True)
    await asyncio.sleep(0.1)

    symbols = ["🔔", "🍇", "🔵", "🍒", "🤡", "💖", "💷"]
    roll = random.randint(1, 1000)
    F = [[""] * 3 for _ in range(3)]
    pay = 0
    text = ""

    if b > 0:
        F = [["🔔"] * 3 for _ in range(3)]
        pay, text = 15, "+15枚"
        u["bonus_spins"] -= 1
    else:
        if roll <= 1:
            F = [["🤡"] * 3 for _ in range(3)]
            pay, text = 10, "+10枚 🎯 BONUS高確率ゾーン突入！"
            u["high_mode"] = True
        elif high_mode and roll <= 17:
            F = [["💖"] * 3 for _ in range(3)]
            pay, u["bonus_spins"], text = 3, 30, "BIG BONUS!!"
            u["high_mode"] = False
        elif high_mode and roll <= 34:
            F = [["💖", "💖", "💷"] for _ in range(3)]
            pay, u["bonus_spins"], text = 3, 15, "REGULAR BONUS!!"
            u["high_mode"] = False
        elif roll <= 5:
            F = [["💖"] * 3 for _ in range(3)]
            pay, u["bonus_spins"], text = 3, 30, "BIG BONUS!!"
        elif roll <= 9:
            F = [["💖", "💖", "💷"] for _ in range(3)]
            pay, u["bonus_spins"], text = 3, 15, "REGULAR BONUS!!"
        elif roll <= 50:
            F = [["🔔"] * 3 for _ in range(3)]
            pay, text = 15, "+15枚"
        elif roll <= 217:
            F = [["🍇"] * 3 for _ in range(3)]
            pay, text = 8, "+8枚"
        elif roll <= 360:
            F = [["🔵"] * 3 for _ in range(3)]
            u["free_spin"], text = True, "FREE SPIN!"
        else:
            F = [[random.choice(symbols) for _ in range(3)] for _ in range(3)]

    u["coin"] += pay
    save_data()

    for _ in range(6):
        frame = "\n".join(" ".join(random.choice(symbols) for _ in range(3)) for _ in range(3))
        await m.edit(content=f"🎰 リール回転中…\n{frame}")
        await asyncio.sleep(0.05)

    D = [[random.choice(symbols) for _ in range(3)] for _ in range(3)]
    for c in range(3):
        for r in range(3):
            D[r][c] = F[r][c]
        await m.edit(content=f"🎰 リール回転中…\n" + "\n".join(" ".join(x) for x in D))
        await asyncio.sleep(0.25 + c * 0.15)

    disp = "\n".join(" ".join(r) for r in F)
    v = discord.ui.View()
    v.add_item(discord.ui.Button(label="もう1回回す", style=discord.ButtonStyle.primary, custom_id="slot_retry"))
    mode_status = "（🎯BONUS高確率ゾーン中）" if u.get("high_mode", False) else ""
    await m.edit(
        content=f"🎰 **{i.user.display_name} のスロット結果！**{mode_status}\n{disp}\n{text}\n🪙 現在：{u['coin']}枚",
        view=v
    )

@bot.event
async def on_interaction(i):
    if i.type == discord.InteractionType.component and i.data.get("custom_id") == "slot_retry":
        await casino_slot(i)

bot.tree.add_command(casino)

# === 起動 ===
@bot.event
async def on_disconnect():
    save_data()

load_data()

@bot.event
async def on_ready():
    await bot.tree.sync()
    if not apply_interest.is_running():
        apply_interest.start()
    print("✅ コマンドを再同期しました！")
    print(f"✅ ログインしました: {bot.user}")

keep_alive()
bot.run(os.environ["DISCORD_TOKEN"])
