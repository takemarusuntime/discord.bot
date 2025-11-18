from keep_alive import keep_alive
keep_alive()  # Flask を起動（Render 無料でスリープ防止）

import discord
from discord.ext import commands, tasks
import asyncio, json, os, re, random, time
from datetime import datetime, timedelta, timezone
from datetime import time as dtime

JST = timezone(timedelta(hours=9))

# ============================== Bot設定 ==============================
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True
intents.reactions = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ============================== ファイル ==============================
DATA_CL     = "cl_data.json"
DATA_GOLD   = "gold_data.json"
DATA_REACT  = "reaction_roles.json"
DATA_PIN    = "pin_data.json"
DATA_REMIND = "reminders.json"
INIT_FLAG   = "init_gold_flag.json"
DATA_COIN   = "coin_data.json"

# ============================== メモリ ==============================
cl_data = {"enabled": True, "users": {}}
gold_data = {}
reaction_role_data = {}
pin_data = {}
reminders = {}
voice_sessions = {}

# ============================== 共通 I/O ==============================
def load(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return default

def save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

# ============================== ReactionRole データ ==============================
def load_reaction_roles():
    return load(DATA_REACT, {})

def save_reaction_roles():
    save(DATA_REACT, reaction_role_data)

# ============================== Pin データ ==============================
def load_pin():
    return load(DATA_PIN, {})

def save_pin():
    save(DATA_PIN, pin_data)

# ============================== GOLD 共通関数 ==============================
def get_gold(uid):
    return gold_data.get(str(uid), 0)

def add_gold(uid, amount):
    uid = str(uid)
    gold_data[uid] = gold_data.get(uid, 0) + amount
    save(DATA_GOLD, gold_data)

# ============================== COIN データ ==============================
def load_coin():
    return load(DATA_COIN, {})

def save_coin(data):
    tmp = DATA_COIN + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_COIN)

# ============================== 毎日GOLD配布 ==============================
@tasks.loop(time=dtime(hour=0, minute=0, tzinfo=JST))
async def daily_gold():
    cnt = 0
    for guild in bot.guilds:
        for m in guild.members:
            if not m.bot:
                add_gold(m.id, 1000)
                cnt += 1
    print(f"[Daily] {cnt}人に1000 GOLD 配布")

# ============================== サーバー参加時の処理（A方式） ==============================
@bot.event
async def on_member_join(member):
    """参加時に毎回 10000G を付与＋Guestロール付け"""
    if member.bot:
        return

    # 10000G付与（A方式）
    add_gold(member.id, 10000)
    print(f"[JOIN] {member.display_name} に10000 GOLD 配布")

    # Guestロール付与
    guest = discord.utils.get(member.guild.roles, name="Guest")
    if guest:
        try:
            await member.add_roles(guest, reason="自動Guest付与")
            print(f"[Guest付与] {member.display_name} に Guest 付与")
        except Exception as e:
            print(f"[Guest付与失敗] {e}")

# ============================== Member追加時にGuestを外す ==============================
@bot.event
async def on_member_update(before, after):
    member_role = discord.utils.get(after.guild.roles, name="Member")
    guest_role = discord.utils.get(after.guild.roles, name="Guest")

    added = [r for r in after.roles if r not in before.roles]

    if member_role and member_role in added:
        if guest_role and guest_role in after.roles:
            try:
                await after.remove_roles(guest_role, reason="Member認証 → Guest解除")
                print(f"[Guest解除] {after.display_name} から Guest 削除")
            except Exception as e:
                print(f"[Guest解除失敗] {e}")

# ============================== Communication Level ==============================
CL_LEVELS = [
    {"name": "Communication Level 1", "text": 10,   "vc": 60,    "color": 0x999999},
    {"name": "Communication Level 2", "text": 50,   "vc": 720,   "color": 0x55FF55},
    {"name": "Communication Level 3", "text": 100,  "vc": 1440,  "color": 0x3333FF},
    {"name": "Communication Level 4", "text": 333,  "vc": 10080, "color": 0x8800FF},
    {"name": "Communication Level 5", "text": 666,  "vc": 20160, "color": 0xFFFF00},
    {"name": "Communication Level 6", "text": 1000, "vc": 43200, "color": 0xFF5555},
]

async def check_cl_role(member):
    uid = str(member.id)
    data = cl_data["users"].get(uid, {"text": 0, "vc": 0})

    achieved = None
    for lv in CL_LEVELS:
        if data["text"] >= lv["text"] and data["vc"] >= lv["vc"]:
            achieved = lv
        else:
            break

    if not achieved:
        return

    guild = member.guild
    target = discord.utils.get(guild.roles, name=achieved["name"])
    if not target:
        target = await guild.create_role(
            name=achieved["name"],
            color=discord.Color(achieved["color"])
        )

    if target not in member.roles:
        await member.add_roles(target)

    # 他レベルを外す
    for lv in CL_LEVELS:
        if lv["name"] != achieved["name"]:
            r = discord.utils.get(guild.roles, name=lv["name"])
            if r and r in member.roles:
                await member.remove_roles(r)

# ============================== on_message ==============================
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    uid = str(message.author.id)

    # チャットGOLD
    gain = (len(message.content) // 2) * 10
    if gain > 0:
        add_gold(message.author.id, gain)

    # Communication Level
    if cl_data["enabled"]:
        cl_data["users"].setdefault(uid, {"text": 0, "vc": 0})
        cl_data["users"][uid]["text"] += len(message.content)
        save(DATA_CL, cl_data)
        await check_cl_role(message.author)

    # 最下部固定ピン処理
    cid = str(message.channel.id)
    if cid in pin_data and message.author.id != bot.user.id:
        data = pin_data[cid]

        try:
            old_msg = await message.channel.fetch_message(int(data["message_id"]))
            await old_msg.delete()
        except:
            pass

        new_msg = await message.channel.send(data["body"])
        pin_data[cid]["message_id"] = new_msg.id
        save_pin()

    await bot.process_commands(message)

# ============================== VC時間処理 ==============================
@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    uid = str(member.id)

    if before.channel is None and after.channel is not None:
        voice_sessions[uid] = time.time()

    elif before.channel is not None and after.channel is None:
        if uid in voice_sessions:
            minutes = int((time.time() - voice_sessions[uid]) / 60)
            voice_sessions.pop(uid, None)

            if minutes > 0:
                add_gold(member.id, minutes * 10)

            cl_data["users"].setdefault(uid, {"text": 0, "vc": 0})
            cl_data["users"][uid]["vc"] += minutes
            save(DATA_CL, cl_data)

            await check_cl_role(member)




# ============================================================
# GOLD メニュー（残高確認 / 送金）
# ============================================================

@bot.tree.command(
    name="a0_gold",
    description="GOLDメニュー（残高確認・送金）"
)
@app_commands.describe(
    操作="実行したい操作を選択します",
    相手="送金相手（送金の場合のみ）",
    金額="送金するGOLDの金額（1以上）"
)
@app_commands.choices(
    操作=[
        app_commands.Choice(name="GOLD残高確認", value="check"),
        app_commands.Choice(name="GOLD送金", value="send"),
    ]
)
async def a1_gold(
    interaction: discord.Interaction,
    操作: app_commands.Choice[str],
    相手: discord.Member = None,
    金額: int = None
):

    uid = str(interaction.user.id)
    balance = gold_data.get(uid, 0)

    # ============================================
    # ① GOLD残高確認
    # ============================================
    if 操作.value == "check":
        embed = discord.Embed(
            title="GOLD残高確認",
            description=(
                f"【名前】 {interaction.user.display_name}\n"
                f"【現在のGOLD】 {balance} G"
            ),
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # ============================================
    # ② GOLD送金
    # ============================================
    if 操作.value == "send":

        if 相手 is None:
            await interaction.response.send_message("送金する相手を指定してください。", ephemeral=True)
            return

        if 金額 is None or 金額 <= 0:
            await interaction.response.send_message("送金額は1以上で指定してください。", ephemeral=True)
            return

        sender_id = str(interaction.user.id)
        receiver_id = str(相手.id)

        if sender_id == receiver_id:
            await interaction.response.send_message("自分自身には送金できません。", ephemeral=True)
            return

        sender_gold = gold_data.get(sender_id, 0)
        if sender_gold < 金額:
            await interaction.response.send_message("ウォレット残高が不足しています。", ephemeral=True)
            return

        if receiver_id not in gold_data:
            gold_data[receiver_id] = 0

        gold_data[sender_id] -= 金額
        gold_data[receiver_id] += 金額
        save(DATA_GOLD, gold_data)

        embed = discord.Embed(
            title="GOLD送金 完了",
            description=(
                f"【送金者】 {interaction.user.display_name}\n"
                f"【受取者】 {相手.display_name}\n"
                f"【送金額】 {金額} G\n\n"
                f"送金が正常に完了しました。"
            ),
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        await interaction.response.send_message(embed=embed, ephemeral=True)
        return


# ============================== /b1_おみくじ ==============================
import random

# ===== ラッキーアイテム生成 =====
def generate_lucky_item():
    colors = [
        "黒い", "白い", "灰色の", "銀色の", "金色の", "茶色の", "こげ茶色の", "ベージュの",
        "赤い", "青い", "緑の", "黄色い", "オレンジ色の", "ピンク色の", "紫の", "水色の",
        "紺色の", "ネイビーの", "カーキ色の", "ライトグレーの", "ダークグレーの",
        "ライトブルーの", "深緑の", "ワインレッドの", "エメラルド色の",
        "クリーム色の", "薄黄色の", "空色の", "ターコイズの",
        "黄緑の", "マゼンタの"
    ]

    # 持ち運べる小物（略：あなたの元のリストを使用）
    items = ["ミニタオル", "折りたたみ傘", "爪切り", "USBメモリ", "ポーチ", "キーホルダー"]

    return f"{random.choice(colors)}{random.choice(items)}"

# ===== おみくじ本体 =====
@bot.tree.command(
    name="b1_おみくじ",
    description="おみくじを引きます"
)
async def b1_omikuji(interaction: discord.Interaction):

    weights = {
        "大大大吉": 0.005,
        "大大吉":   0.01,
    }

    others = ["大吉", "中吉", "吉", "小吉", "末吉", "凶", "大凶"]

    remaining = 1 - sum(weights.values())
    basic = remaining / len(others)
    weights["大吉"] = basic + 0.005

    for f in others:
        if f != "大吉":
            weights[f] = basic

    result = random.choices(list(weights.keys()), list(weights.values()))[0]

    messages = {
        "大大大吉": [
            "✨宇宙があなたを祝福！奇跡が連続する最上級の一日です！🚀🌟",
            "🔥運命が完全覚醒！望む前に幸運が押し寄せます！🌈💫",
            "🌟天が味方する瞬間！圧倒的パワーで全てが好転します！💥⚡",
            "💎選ばれし者の輝き！今日のあなたは無敵です！✨👑",
            "🌅超次元の幸福到来！運命があなた中心に回り始めます！💫🌍"
        ],
        "大大吉": [
            "🎉勢いが最高潮！行動すれば成功が雪崩のように訪れます！🌟",
            "🌈絶好調の波が到来！大きな成果が手に入りやすい一日です！💪✨",
            "🔥運気の風が背中を押します！大胆な挑戦が吉！⚡",
            "💫輝きが増す日！あなたの魅力が周囲を動かします！🌟",
            "✨大きな幸福が静かに近づいています。掴み取る準備を！🌱"
        ],
        "大吉": [
            "😊明るい流れが続く日。少しの勇気で一気に前進！🌟",
            "🌈小さな幸せが積み重なり、良い日になります！✨",
            "☀穏やかな運の追い風があなたを支えます！🍀",
            "✨行動が素直に結果へつながる一日です！📈",
            "😌心地よいバランスが続き、良い選択ができる運気です！🌿"
        ],
        "中吉": [
            "🍀自然と良い方向へ進む安定した一日です！😊",
            "✨気持ちが前向きになり、小さな成功が積み重なります！📈",
            "📘冷静な判断が良い結果を呼びます！🌿",
            "🌞期待以上の成果が得られそうな運気です！💫",
            "🪄あなたの直感が冴えています。選択に自信を！⚡"
        ],
        "吉": [
            "😄穏やかで過ごしやすい運気。安心して進めます！🌼",
            "🍀無理をしなければ順調にいく一日！✨",
            "📗タイミングが合いやすく、小さな幸運が訪れます！🌈",
            "🌿平和で気持よく過ごせる日です。焦りは禁物！",
            "🙂ほっとするような良い流れが続きます！✨"
        ],
        "小吉": [
            "🌱控えめながら良い流れが来ています！🍀",
            "😌少し嬉しい出来事が起こりそう！✨",
            "📘慎重に行動すれば確実にプラスへ！📈",
            "🌼気負わず自然体でいれば良い方向へ進みます！",
            "💭ゆったり過ごすと小さな幸せを感じられます！"
        ],
        "末吉": [
            "🍃大きな問題はなく、落ち着いた一日になりそうです！😌",
            "🌱少しずつ運気が回復していく気配があります！✨",
            "🕊焦らず進めば良い結果がついてきます！",
            "🌙静かな幸運がゆっくりと近づいてきます！",
            "📘現状維持が吉。慎重さが価値を生みます！"
        ],
        "凶": [
            "🌧少し噛み合わない日ですが、落ち着けば大丈夫です！😣",
            "🌫無理は禁物。ゆっくり進めば問題なし！🍃",
            "😓期待しすぎると空回り気味。深呼吸を！",
            "🌧慎重に動けば悪い流れを避けられます！",
            "💧今日はペースダウンが吉。明日は巻き返せます！"
        ],
        "大凶": [
            "⛈今日は静かに過ごすのが最善。無理はしないで！😢",
            "🌪うまくいかないことが続く予感…休息を優先！💤",
            "😭厳しめの運気。行動は控え目に！",
            "🌧不運が重なりやすい日。守りの姿勢が吉！",
            "🕯落ち込む必要はなし。今日は耐え、明日から好転します。✨"
        ]
    }

    fortune_text = random.choice(messages[result])

    # GOLD付与
    if result == "大大大吉":
        add_gold(interaction.user.id, 5000)
    elif result == "大大吉":
        add_gold(interaction.user.id, 3000)
    elif result == "大吉":
        add_gold(interaction.user.id, 1000)

    # 表示
    color_map = {
        "大大大吉": "#FFF000",
        "大大吉":   "#FFD65C",
        "大吉":     "#FFF5B5",
        "大凶":     discord.Color.dark_red(),
        "凶":       discord.Color.red(),
    }

    embed = discord.Embed(
        title=f"【{result}】",
        description=f"### {fortune_text}",
        color=color_map.get(result, discord.Color.light_gray())
    )

    # ラッキーアイテム
    embed.add_field(name="ラッキーアイテム", value=generate_lucky_item(), inline=False)

    embed.set_footer(
        text=f"{interaction.user.display_name} の運勢",
        icon_url=interaction.user.display_avatar.url
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ============================== リマインド機能 ==============================
def load_reminders():
    return load(DATA_REMIND, {})

def save_reminders():
    save(DATA_REMIND, reminders)

async def remind_task(rid, data, wait):
    try:
        await asyncio.sleep(max(0, wait))
        channel = bot.get_channel(data["channel_id"])
        user = bot.get_user(data["user_id"])

        if channel and user:
            webhook = await channel.create_webhook(name=user.display_name)
            await webhook.send(
                data["message"],
                username=user.display_name,
                avatar_url=user.display_avatar.url
            )
            await webhook.delete()

    except:
        pass
    finally:
        reminders.pop(rid, None)
        save_reminders()

async def restore_reminders():
    global reminders
    reminders = load_reminders()
    now = datetime.now(JST)

    for rid, data in list(reminders.items()):
        t = datetime.fromisoformat(data["time"])
        wait = (t - now).total_seconds()

        if wait <= 0:
            reminders.pop(rid, None)
            continue

        asyncio.create_task(remind_task(rid, data, wait))

    save_reminders()

# ========== /b2_リマインド設定 ==========
@bot.tree.command(
    name="b2_リマインド設定",
    description="指定した時間にリマインドします"
)
@app_commands.describe(when="例: 15 / 21:30 / 11/01 21:30")
async def b2_remind(interaction: discord.Interaction, when: str):

    await interaction.response.defer(ephemeral=True)
    now = datetime.now(JST)

    # 分後
    if re.fullmatch(r"\d+", when):
        remind_time = now + timedelta(minutes=int(when))

    # 今日の時刻
    elif re.fullmatch(r"\d{1,2}:\d{2}", when):
        t = datetime.strptime(when, "%H:%M")
        remind_time = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        if remind_time < now:
            remind_time += timedelta(days=1)

    # 日付 + 時刻
    elif re.fullmatch(r"\d{1,2}/\d{1,2} \d{1,2}:\d{2}", when):
        t = datetime.strptime(when, "%m/%d %H:%M")
        remind_time = now.replace(
            month=t.month, day=t.day,
            hour=t.hour, minute=t.minute,
            second=0, microsecond=0
        )
        if remind_time < now:
            remind_time = remind_time.replace(year=now.year + 1)

    else:
        await interaction.followup.send("時間形式が無効です。", ephemeral=True)
        return

    rid = f"{interaction.user.id}-{int(remind_time.timestamp())}"

    # モーダル
    class MsgModal(discord.ui.Modal, title="リマインド内容入力"):

        text = discord.ui.TextInput(
            label="内容",
            style=discord.TextStyle.paragraph,
            required=True
        )

        async def on_submit(self, mi):

            msg = self.text.value.strip()
            wait = (remind_time - datetime.now(JST)).total_seconds()

            asyncio.create_task(remind_task(
                rid,
                {
                    "message": msg,
                    "time": remind_time.isoformat(),
                    "user_id": mi.user.id,
                    "channel_id": mi.channel.id
                },
                wait
            ))

            reminders[rid] = {
                "message": msg,
                "time": remind_time.isoformat(),
                "user_id": mi.user.id,
                "channel_id": mi.channel.id
            }
            save_reminders()

            # 削除ボタン
            class Cancel(discord.ui.View):
                @discord.ui.button(label="リマインド削除", style=discord.ButtonStyle.danger)
                async def del_btn(self, itx, _):
                    if rid in reminders:
                        reminders.pop(rid)
                        save_reminders()
                        await itx.response.edit_message(
                            content="リマインドを削除しました。",
                            view=None
                        )
                    else:
                        await itx.response.send_message("削除できません。", ephemeral=True)

            await mi.response.send_message(
                f"設定完了：{remind_time.strftime('%m/%d %H:%M')}\n> {msg}",
                view=Cancel(),
                ephemeral=True
            )

    await interaction.followup.send_modal(MsgModal())


# ============================== Casino（Coin） ==============================
@bot.tree.command(
    name="c0_casino_coin",
    description="COINメニュー（残高確認・貸出・返却）"
)
@app_commands.describe(
    操作="COIN 貸出か返却か選んでください",
    数量="貸出、返却したい COIN の数量"
)
@app_commands.choices(
    操作=[
        app_commands.Choice(name="COIN残高確認", value="check"),
        app_commands.Choice(name="COIN貸出（GOLD → COIN）", value="lend"),
        app_commands.Choice(name="COIN返却（COIN → GOLD）", value="return")
    ]
)
async def casino_coin(interaction, 操作, 数量: int = None):

    uid = str(interaction.user.id)
    coin_data = load_coin()
    user_coin = coin_data.get(uid, 0)
    user_gold = gold_data.get(uid, 0)

    # COIN残高確認
    if 操作.value == "check":
        embed = discord.Embed(
            title="COIN残高確認",
            description=f"現在のCOIN： **{user_coin} COIN**",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # 数量必須
    if 数量 is None or 数量 <= 0:
        await interaction.response.send_message("1以上の数量を指定してください。", ephemeral=True)
        return

    # COIN貸出
    if 操作.value == "lend":
        want = 数量
        need = want * 20
        if user_gold < need:
            await interaction.response.send_message("GOLDが不足しています。", ephemeral=True)
            return

        gold_data[uid] = user_gold - need
        coin_data[uid] = user_coin + want
        save(DATA_GOLD, gold_data)
        save_coin(coin_data)

        embed = discord.Embed(
            title="COIN貸出 完了",
            description=f"{want} COIN 取得\n消費GOLD：{need} G",
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # COIN返却（10COIN単位）
    if 操作.value == "return":
        want = 数量
        if user_coin < want:
            await interaction.response.send_message("COIN残高が不足しています。", ephemeral=True)
            return

        unit = want // 10
        if unit == 0:
            await interaction.response.send_message("10COIN単位で返却できます。", ephemeral=True)
            return

        used = unit * 10
        get_gold = unit * 180

        coin_data[uid] = user_coin - used
        gold_data[uid] = user_gold + get_gold
        save_coin(coin_data)
        save(DATA_GOLD, gold_data)

        embed = discord.Embed(
            title="COIN返却 完了",
            description=f"{used} COIN を返却 → {get_gold} GOLD",
            color=discord.Color.orange()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return


# ============================== リアクションロール ==============================
# x1_新規作成
@bot.tree.command(name="x1_リアクションロール設定", description="リアクションロールを新規作成します")
@app_commands.describe(pairs="絵文字:ロール名（例：🔴:赤,🔵:青）", multi_select="True=複数可/False=排他")
@app_commands.default_permissions(manage_roles=True)
async def x1_rr(interaction, pairs: str, multi_select: bool = True):

    pair_list = [x.strip() for x in re.split("[,、]", pairs) if x.strip()]
    emoji_role_pairs = []

    for p in pair_list:
        if ":" not in p:
            await interaction.response.send_message("形式エラー", ephemeral=True)
            return

        emoji, role_name = p.split(":", 1)
        role_name = role_name.strip()

        role = discord.utils.get(interaction.guild.roles, name=role_name)
        if not role:
            try:
                role = await interaction.guild.create_role(name=role_name)
            except:
                await interaction.response.send_message("ロール作成不可", ephemeral=True)
                return

        emoji_role_pairs.append((emoji.strip(), role))

    class RRMessageModal(discord.ui.Modal, title="リアクションロール本文"):
        body = discord.ui.TextInput(label="本文", style=discord.TextStyle.paragraph, required=True)

        async def on_submit(self, mi):
            msg = await mi.channel.send(self.body.value)

            for emoji, _role in emoji_role_pairs:
                try:
                    await msg.add_reaction(emoji)
                except:
                    pass

            reaction_role_data[str(msg.id)] = {
                "guild_id": interaction.guild.id,
                "channel_id": mi.channel.id,
                "exclusive": (not multi_select),
                "roles": {e: r.id for e, r in emoji_role_pairs},
                "message": self.body.value
            }
            save_reaction_roles()

            await mi.response.send_message("作成しました", ephemeral=True)

    await interaction.response.send_modal(RRMessageModal())

# y1_追加
@bot.tree.command(name="y1_リアクションロール追加", description="既存へ追加")
@app_commands.default_permissions(manage_roles=True)
async def y1_rr_add(interaction, message_id: str, pairs: str):

    data = reaction_role_data.get(message_id)
    if not data:
        await interaction.response.send_message("対象なし", ephemeral=True)
        return

    channel = bot.get_channel(int(data["channel_id"]))
    try:
        msg = await channel.fetch_message(int(message_id))
    except:
        await interaction.response.send_message("メッセージ取得失敗", ephemeral=True)
        return

    pair_list = [x.strip() for x in re.split("[,、]", pairs) if x.strip()]
    added = []

    for p in pair_list:
        if ":" not in p:
            continue

        emoji, role_name = p.split(":", 1)
        role = discord.utils.get(interaction.guild.roles, name=role_name.strip())
        if not role:
            try:
                role = await interaction.guild.create_role(name=role_name)
            except:
                continue

        data["roles"][emoji] = role.id
        added.append(f"{emoji}:{role_name}")

        try:
            await msg.add_reaction(emoji)
        except:
            pass

    save_reaction_roles()
    await interaction.response.send_message(f"追加：{', '.join(added)}", ephemeral=True)

# y2_削除
@bot.tree.command(name="y2_リアクションロール削除", description="削除")
@app_commands.default_permissions(manage_roles=True)
async def y2_rr_del(interaction, message_id: str, emojis: str):

    data = reaction_role_data.get(message_id)
    if not data:
        await interaction.response.send_message("対象なし", ephemeral=True)
        return

    channel = bot.get_channel(int(data["channel_id"]))
    try:
        msg = await channel.fetch_message(int(message_id))
    except:
        await interaction.response.send_message("取得失敗", ephemeral=True)
        return

    targets = [x.strip() for x in re.split("[,、]", emojis) if x.strip()]
    removed = []

    for e in targets:
        if e in data["roles"]:
            data["roles"].pop(e, None)
            removed.append(e)

            try:
                for r in msg.reactions:
                    if str(r.emoji) == e:
                        await msg.clear_reaction(r.emoji)
                        break
            except:
                pass

    save_reaction_roles()
    await interaction.response.send_message(f"削除：{', '.join(removed)}", ephemeral=True)

# y3_本文編集
@bot.tree.command(name="y3_リアクションロール本文編集", description="本文編集")
@app_commands.default_permissions(manage_messages=True)
async def y3_rr_edit(interaction, message_id: str):

    data = reaction_role_data.get(message_id)
    if not data:
        await interaction.response.send_message("対象なし", ephemeral=True)
        return

    channel = bot.get_channel(int(data["channel_id"]))
    try:
        msg = await channel.fetch_message(int(message_id))
    except:
        await interaction.response.send_message("取得失敗", ephemeral=True)
        return

    class Modal(discord.ui.Modal, title="本文編集"):
        body = discord.ui.TextInput(
            label="本文",
            style=discord.TextStyle.paragraph,
            default=data["message"]
        )

        async def on_submit(self, mi):
            try:
                await msg.edit(content=self.body.value)
            except:
                await mi.response.send_message("編集失敗", ephemeral=True)
                return

            data["message"] = self.body.value
            save_reaction_roles()

            await mi.response.send_message("更新しました", ephemeral=True)

    await interaction.response.send_modal(Modal())


# ============================== Reactionイベント（ロール付与/削除） ==============================
@bot.event
async def on_raw_reaction_add(payload):
    mid = str(payload.message_id)

    if mid not in reaction_role_data:
        return
    if payload.user_id == bot.user.id:
        return

    d = reaction_role_data[mid]
    emoji = str(payload.emoji)
    role_id = d["roles"].get(emoji)
    if not role_id:
        return

    guild = bot.get_guild(int(d["guild_id"]))
    member = guild.get_member(payload.user_id)
    role = guild.get_role(role_id)
    if not member or not role:
        return

    try:
        if d.get("exclusive"):
            for rid in d["roles"].values():
                if rid != role.id:
                    r = guild.get_role(rid)
                    if r in member.roles:
                        await member.remove_roles(r)

        await member.add_roles(role)
    except:
        pass

@bot.event
async def on_raw_reaction_remove(payload):
    mid = str(payload.message_id)

    if mid not in reaction_role_data:
        return

    d = reaction_role_data[mid]
    emoji = str(payload.emoji)
    role_id = d["roles"].get(emoji)
    if not role_id:
        return

    guild = bot.get_guild(int(d["guild_id"]))
    member = guild.get_member(payload.user_id)
    role = guild.get_role(role_id)

    if not member or not role:
        return

    try:
        await member.remove_roles(role)
    except:
        pass


# ============================== 問い合わせシステム ==============================
class InquiryButtonView(discord.ui.View):
    def __init__(self, role, labels, message):
        super().__init__(timeout=None)
        self.role = role
        self.message = message
        for label in labels:
            self.add_item(InquiryButton(label=label, role=role, message=message))

class InquiryButton(discord.ui.Button):
    def __init__(self, label, role, message):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.role = role
        self.message = message

    async def callback(self, interaction):
        guild = interaction.guild
        user = interaction.user
        category = interaction.channel.category
        name = f"{user.display_name}-{self.label}"

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            self.role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }

        ch = await guild.create_text_channel(
            name=name, category=category, overwrites=overwrites
        )

        await ch.send(self.message, view=DeleteChannelButton())
        await interaction.response.send_message("チャンネルを作成しました。", ephemeral=True)

class DeleteChannelButton(discord.ui.View):
    @discord.ui.button(label="チャンネルを削除する", style=discord.ButtonStyle.danger)
    async def delete(self, interaction, _btn):
        await interaction.response.send_message("削除します…", ephemeral=True)
        await asyncio.sleep(2)
        try:
            await interaction.channel.delete(reason="Ticket closed")
        except:
            pass

@bot.tree.command(
    name="x2_問い合わせ設定",
    description="問い合わせボタンを設置します（管理者専用）"
)
@app_commands.default_permissions(administrator=True)
async def x2_ticket(interaction, support_role: discord.Role, button_labels: str):

    labels = [x.strip() for x in re.split("[,、]", button_labels) if x.strip()]
    if not labels:
        await interaction.response.send_message("ボタン名が空です。", ephemeral=True)
        return

    class Modal(discord.ui.Modal, title="案内メッセージ入力"):
        body = discord.ui.TextInput(
            label="本文",
            style=discord.TextStyle.paragraph,
            required=True
        )

        async def on_submit(self, mi):
            view = InquiryButtonView(support_role, labels, self.body.value)
            await mi.channel.send(self.body.value, view=view)
            await mi.response.send_message("問い合わせボタンを設置しました。", ephemeral=True)

    await interaction.response.send_modal(Modal())


# ============================== ピン留め ==============================
@bot.tree.command(name="x3_ピン留め設定", description="固定メッセージを設定します")
@app_commands.default_permissions(administrator=True)
async def x3_pin(interaction):

    class Modal(discord.ui.Modal, title="ピン留め内容"):
        body = discord.ui.TextInput(
            label="本文",
            style=discord.TextStyle.paragraph,
            required=True
        )

        async def on_submit(self, mi):
            cid = str(mi.channel.id)

            old = pin_data.get(cid)
            if old:
                try:
                    old_msg = await mi.channel.fetch_message(int(old["message_id"]))
                    await old_msg.delete()
                except:
                    pass

            new_msg = await mi.channel.send(self.body.value)

            pin_data[cid] = {"message_id": new_msg.id, "body": self.body.value}
            save_pin()

            await mi.response.send_message("固定メッセージを設定しました。", ephemeral=True)

    await interaction.response.send_modal(Modal())


@bot.tree.command(name="x4_ピン留め削除", description="固定メッセージ削除")
@app_commands.default_permissions(administrator=True)
async def x4_unpin(interaction):

    cid = str(interaction.channel.id)
    if cid not in pin_data:
        await interaction.response.send_message("設定なし", ephemeral=True)
        return

    try:
        msg = await interaction.channel.fetch_message(int(pin_data[cid]["message_id"]))
        await msg.delete()
    except:
        pass

    pin_data.pop(cid, None)
    save_pin()
    await interaction.response.send_message("削除しました。", ephemeral=True)


# ============================== 認証ボタン ==============================
AGREE_BUTTON_MESSAGE = (
    "### サーバールールへの同意\n"
    "以下のボタンを押すと **ルールに同意したもの** とみなされ、チャンネルが解放されます。"
)

class AgreeButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ 同意する", style=discord.ButtonStyle.success, custom_id="agree_button")
    async def agree(self, interaction, btn):

        member = interaction.user
        guild = interaction.guild
        member_role = discord.utils.get(guild.roles, name="Member")

        if not member_role:
            member_role = await guild.create_role(name="Member")

        if member_role in member.roles:
            return await interaction.response.send_message("既に認証済みです。", ephemeral=True)

        await member.add_roles(member_role)
        await interaction.response.send_message("認証が完了しました。", ephemeral=True)


@bot.tree.command(
    name="認証ボタン設置",
    description="ルールチャンネルに認証ボタンを設置します"
)
@app_commands.default_permissions(administrator=True)
async def setup_agree(interaction):

    await interaction.response.defer(ephemeral=True)

    await interaction.channel.send(
        AGREE_BUTTON_MESSAGE,
        view=AgreeButton()
    )

    await interaction.followup.send("認証ボタンを設置しました。", ephemeral=True)


# ============================== on_ready ==============================
@bot.event
async def on_ready():
    global cl_data, gold_data, reaction_role_data, pin_data

    cl_data = load(DATA_CL, {"enabled": True, "users": {}})
    gold_data = load(DATA_GOLD, {})
    reaction_role_data = load_reaction_roles()
    pin_data = load_pin()

    await bot.tree.sync()

    print(f"ログイン完了: {bot.user}")
    print("Communication Level:", "ON" if cl_data["enabled"] else "OFF")

    if not daily_gold.is_running():
        daily_gold.start()

    await restore_reminders()

    print("起動処理完了")


# ============================== BOT起動 ==============================
TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN が Render に設定されていません")

bot.run(TOKEN)