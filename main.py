import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio, json, os, re, time
from datetime import datetime, timedelta, timezone
from datetime import time as dtime
import feedparser
import random

from keep_alive import keep_alive


# =========================================================
# ✅ 基本設定
# =========================================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)
JST = timezone(timedelta(hours=9))


# =========================================================
# ✅ データファイル定義
# =========================================================
DATA_FILE = "cl_data.json"
FEEDS_FILE = "feeds.json"
TEMPLATE_FILE = "auto_templates.json"
REACTION_FILE = "reaction_roles.json"
GOLD_FILE = "gold_data.json"


# =========================================================
# ✅ グローバル変数
# =========================================================
cl_data = {"users": {}, "enabled": False}
voice_sessions = {}
tracking_feeds = {}
auto_templates = {}
last_template_messages = {}
reaction_role_data = {}
gold_data = {}
reminders = {}


# =========================================================
# ✅ ファイル読み書き（統一関数）
# =========================================================
def load_json(path, default):
    """JSON を安全にロードする共通関数"""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ {path} 読み込み失敗: {e}")
    return default

def save_json(path, data):
    """JSON を安全に保存する共通関数"""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"⚠️ {path} 保存失敗: {e}")


# =========================================================
# ✅ データロード関数（初期化時に使用）
# =========================================================
def load_all_data():
    global cl_data, tracking_feeds, auto_templates, reaction_role_data, gold_data
    cl_data = load_json(DATA_FILE, {"users": {}, "enabled": False})
    tracking_feeds = load_json(FEEDS_FILE, {})
    auto_templates = load_json(TEMPLATE_FILE, {})
    reaction_role_data = load_json(REACTION_FILE, {})
    gold_data = load_json(GOLD_FILE, {})

# 保存ショートカット
def save_cl_data(): save_json(DATA_FILE, cl_data)
def save_feeds(): save_json(FEEDS_FILE, tracking_feeds)
def save_templates(): save_json(TEMPLATE_FILE, auto_templates)
def save_reaction_roles(): save_json(REACTION_FILE, reaction_role_data)
def save_gold(): save_json(GOLD_FILE, gold_data)


# =========================================================
# ✅ 絵文字判定（カスタム絵文字／Unicode 絵文字）
# =========================================================
def is_emoji(s: str) -> bool:
    # カスタム絵文字形式 <a:name:id>
    if re.fullmatch(r"<a?:\w+:\d+>", s):
        return True

    # Unicode 絵文字
    emoji_pattern = re.compile(
        r"(<a?:\w+:\d+>|[\U00010000-\U0010FFFF])",
        flags=re.UNICODE
    )
    return bool(emoji_pattern.fullmatch(s))


# =========================================================
# ✅ 既存ユーザーに10000G（初回のみ）
# =========================================================
async def distribute_initial_gold():
    """
    Bot初回起動時のみ、既存ユーザー全員に10000Gを付与する
    """
    FLAG_FILE = "initial_gold_flag.json"
    if os.path.exists(FLAG_FILE):
        return  # 既に付与済み

    count = 0
    for guild in bot.guilds:
        for member in guild.members:
            if not member.bot:
                add_gold(member.id, 10000)
                count += 1

    save_json(FLAG_FILE, {"distributed": True, "count": count})
    print(f"初回ボーナス : {count} ユーザーに 10000G 配布完了")


# =========================================================
# ✅ 新規参加ユーザーに10000G（1度のみ）
# =========================================================
@bot.event
async def on_member_join(member: discord.Member):
    if member.bot:
        return

    uid = str(member.id)
    if uid not in gold_data:
        add_gold(member.id, 10000)
        print(f"JOIN BONUS : {member.display_name} に 10000G 付与")


# =========================================================
# ✅ GOLDシステム共通関数
# =========================================================
def get_balance(user_id: int) -> int:
    """ユーザーの所持GOLDを返す"""
    return gold_data.get(str(user_id), 0)

def add_gold(user_id: int, amount: int):
    """ユーザーにGOLDを加算する"""
    uid = str(user_id)
    gold_data[uid] = gold_data.get(uid, 0) + amount
    save_gold()


# =========================================================
# ✅ 毎日00:00に全ユーザーへ1000G
# =========================================================
@tasks.loop(time=dtime(hour=0, minute=0, tzinfo=JST))
async def daily_gold_distribution():
    count = 0
    for guild in bot.guilds:
        for member in guild.members:
            if not member.bot:
                add_gold(member.id, 1000)
                count += 1

    print(f"[{datetime.now(JST).strftime('%m/%d %H:%M')}] 毎日配布 : {count} ユーザーに1000G")


# =========================================================
# ✅ チャット文字数2文字＝10G
# =========================================================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # --- GOLD付与（2文字 = 10G） ---
    try:
        gain = (len(message.content) // 2) * 10
        if gain > 0:
            add_gold(message.author.id, gain)
    except Exception as e:
        print(f"チャット報酬エラー : {e}")

    # --- Communication Level 記録 ---
    if cl_data.get("enabled"):
        uid = str(message.author.id)
        cl_data["users"].setdefault(uid, {"text": 0, "vc": 0})
        cl_data["users"][uid]["text"] += len(message.content)
        save_cl_data()
        await check_and_assign_roles(message.author)

    await bot.process_commands(message)


# =========================================================
# ✅ VC滞在1分＝10G
# =========================================================
@bot.event
async def on_voice_state_update(member, before, after):
    uid = str(member.id)

    # --- VC入室 ---
    if before.channel is None and after.channel is not None:
        voice_sessions[uid] = time.time()

    # --- VC退出 or 移動 ---
    elif before.channel is not None and after.channel != before.channel:
        if uid in voice_sessions:
            duration = int((time.time() - voice_sessions[uid]) / 60)
            del voice_sessions[uid]

            if duration > 0:
                # GOLD付与（1分 = 10G）
                add_gold(member.id, duration * 10)

            # CL機能がONならVC記録
            if cl_data.get("enabled"):
                cl_data["users"].setdefault(uid, {"text": 0, "vc": 0})
                cl_data["users"][uid]["vc"] += duration
                save_cl_data()
                await check_and_assign_roles(member)


# =========================================================
# ✅ リアクション1回＝100G
# =========================================================
reaction_cooldown = {}

@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return

    uid = str(user.id)
    now = time.time()

    # クールダウン中
    if uid in reaction_cooldown and now < reaction_cooldown[uid]:
        return

    reaction_cooldown[uid] = now + 60  # 60秒クールダウン
    add_gold(user.id, 100)  # 100G付与


# =========================================================
# ✅ Communication Level
# =========================================================
CL_LEVELS = [
    {"name": "Communication Level 1", "text": 10, "vc": 30, "color": 0x999999},
    {"name": "Communication Level 2", "text": 50, "vc": 180, "color": 0x55ff55},
    {"name": "Communication Level 3", "text": 100, "vc": 720, "color": 0x3333ff},
    {"name": "Communication Level 4", "text": 333, "vc": 1440, "color": 0x8800ff},
    {"name": "Communication Level 5", "text": 666, "vc": 7200, "color": 0xffff00},
    {"name": "Communication Level 6", "text": 1000, "vc": 14400, "color": 0xff5555},
]

async def check_and_assign_roles(member: discord.Member):
    guild = member.guild
    uid = str(member.id)
    data = cl_data["users"].get(uid, {"text": 0, "vc": 0})

    achieved, color = None, None
    for level in CL_LEVELS:
        if data["text"] >= level["text"] and data["vc"] >= level["vc"]:
            achieved = level["name"]
            color = level["color"]
        else:
            break

    if not achieved:
        return

    # ロール付与
    role = discord.utils.get(guild.roles, name=achieved)
    if not role:
        role = await guild.create_role(name=achieved, color=discord.Color(color))

    if role not in member.roles:
        await member.add_roles(role)

    # 下位ロール削除
    for lvl in CL_LEVELS:
        if lvl["name"] != achieved:
            r = discord.utils.get(guild.roles, name=lvl["name"])
            if r in member.roles:
                await member.remove_roles(r)


# =========================================================
# ✅ /z1_cl_on（CL機能 ON）
# =========================================================
@bot.tree.command(name="z1_cl_on", description="Communication Level機能をONにします【管理者のみ】")
@app_commands.default_permissions(administrator=True)
async def z1_cl_on(interaction: discord.Interaction):
    cl_data["enabled"] = True
    save_cl_data()
    await interaction.response.send_message(
        "Communication Level機能をONにしました。",
        ephemeral=True
    )


# =========================================================
# ✅ /z2_cl_off（CL機能 OFF）
# =========================================================
@bot.tree.command(name="z2_cl_off", description="Communication Level機能をOFFにします【管理者のみ】")
@app_commands.default_permissions(administrator=True)
async def z2_cl_off(interaction: discord.Interaction):
    cl_data["enabled"] = False
    save_cl_data()
    await interaction.response.send_message(
        "Communication Level機能をOFFにしました。",
        ephemeral=True
    )


# =========================================================
# ✅ おみくじ（盛り上げコメント5パターン × ランダム表示）
# =========================================================
@bot.tree.command(name="a1_おみくじ", description="おみくじを引きます")
async def omikuji(interaction: discord.Interaction):

    # -----------------------------------------------------
    # 抽選確率設定
    # -----------------------------------------------------
    fixed = {
        "大大大吉": 0.01,
        "大大吉": 0.03,
        "鬼がかり 3000 BONUS": 0.01
    }
    others = ["大吉", "吉", "中吉", "小吉", "末吉", "凶", "大凶"]
    rest = 1.0 - sum(fixed.values())
    each = rest / len(others)
    weights = {**fixed, **{o: each for o in others}}

    result = random.choices(
        list(weights.keys()),
        weights=list(weights.values()),
        k=1
    )[0]

    # -----------------------------------------------------
    # 運勢ごとの盛り上げコメント（5パターン）
    # -----------------------------------------------------
    comments = {
        "大大大吉": [
            "🌟✨ 今日はあなたが主役！運命が味方する最高の一日！",
            "🔥 一生に一度レベルの奇跡が起きる予感！",
            "🌈 幸運の大波が押し寄せています！行動あるのみ！",
            "💫 すべての挑戦が成功しそうな勢い！",
            "🌟 宇宙規模の祝福が降り注いでいます！"
        ],
        "大大吉": [
            "🔥 最高に輝く一日！迷わず突き進め！",
            "✨ やること全てが流れに乗る最高運気！",
            "🌈 気持ちのままに進めば成功確定！",
            "💥 勢いMAX！運気が爆上がり！",
            "🎉 幸運ボーナス期間突入！"
        ],
        "大吉": [
            "🎉 とても良い流れです！自信を持って！",
            "✨ 調子上々！このまま加速！",
            "🙂 良い運気が吹いてきています！",
            "🌈 明るい未来が見えています！",
            "👍 良い一日が始まりそうです！"
        ],
        "吉": [
            "😊 ほんのり良い運気があなたの味方です。",
            "✨ 安定した良い日になりそう！",
            "😌 穏やかに物事が進みます！",
            "🍀 小さな幸せに気づけそう！",
            "🙂 心地よい一日になりそうです！"
        ],
        "中吉": [
            "✨ いい感じの運気です！やる気も高まる！",
            "🌤️ じわじわ運が上がってきています！",
            "📈 成長の兆しが見えます！",
            "👍 思わぬ良いことが起きるかも！",
            "🙂 期待できる一日です！"
        ],
        "小吉": [
            "🍀 小さな幸運が積み重なります！",
            "🙂 不安よりも楽しさが勝る日です！",
            "🌼 ほどよく良いことが続きます！",
            "✨ あなたのペースで進みましょう！",
            "😌 平和で心地よい時間が流れます！"
        ],
        "末吉": [
            "🌤️ 少しずつ良い方向に変わっていきます！",
            "🙂 焦らず構えれば大丈夫！",
            "🍀 小さな成長を感じられそう！",
            "😌 ゆっくりペースで運が回復します！",
            "🌱 これから上向きになります！"
        ],
        "凶": [
            "😣 無理は禁物、慎重にいけば問題なし！",
            "⚠️ 落ち着いて行動すれば回避できます！",
            "😌 深呼吸して冷静になれば大丈夫！",
            "🌧️ 小さなトラブルがあるかも、慎重に。",
            "🙂 悪い流れを断ち切るチャンスです！"
        ],
        "大凶": [
            "⚡ 逆にレア！ここから運が爆上がりします！",
            "🌑 一度下がれば次は上がるだけ！",
            "😤 開き直れば最強運気が訪れます！",
            "🔥 厄落としとしては完璧！ここから反転！",
            "💣 低いほど跳ね上がる、それが運勢です！"
        ]
    }

    # -----------------------------------------------------
    # embed生成
    # -----------------------------------------------------
    embed = discord.Embed(
        title="おみくじの結果",
        color=discord.Color.gold()
    )

    if result == "鬼がかり 3000 BONUS":
        add_gold(interaction.user.id, 3000)
        embed.description = (
            "# 💥 ﾎﾟｷｭｰｰﾝ!!\n"
            "## ✨ **鬼がかり 3000 BONUS** ✨\n"
            "### **3000GOLD GET!!!!!**"
        )

    # 最高演出（大大大吉）
    elif result == "大大大吉":
        embed.description = (
            "# 🌟✨ **大大大吉** ✨🌟\n"
            f"## {random.choice(comments[result])}\n"
            "### 今日は伝説が起きる予感！"
        )

    # 豪華演出（大大吉）
    elif result == "大大吉":
        embed.description = (
            "# 🔥 **大大吉** 🔥\n"
            f"## {random.choice(comments[result])}\n"
            "### 幸運ゲージが振り切れています！"
        )

    # 通常運勢
    else:
        chosen = random.choice(comments[result])
        embed.description = f"# {result}\n## {chosen}"

    embed.set_footer(text=f"{interaction.user.display_name} さんの運勢")

    await interaction.response.send_message(embed=embed, ephemeral=True)


# =========================================================
# ✅ リマインド機能（コマンド・永続化・復元）
# =========================================================

REMINDERS_FILE = "reminders.json"
reminders = {}


# ---------------------------------------------------------
# ✅ /リマインドコマンド（入口）
# ---------------------------------------------------------
@bot.tree.command(
    name="a2_リマインド",
    description="指定した時間または日付＋時間にリマインドを送ります（日本時間）"
)
@app_commands.describe(
    時間または分後="例：15（分後） / 21:30 / 11/01 21:30"
)
async def remind_command(interaction: discord.Interaction, 時間または分後: str):

    await interaction.response.defer(ephemeral=True)
    now = datetime.now(JST)

    # -----------------------------------------------------
    # 入力された時間形式を解析（分後 / 時刻 / 日付+時刻）
    # -----------------------------------------------------
    # ● 「15」→ 分後
    if re.fullmatch(r"\d+", 時間または分後):
        minutes = int(時間または分後)
        remind_time = now + timedelta(minutes=minutes)
        wait_seconds = minutes * 60

    # ● 「21:30」
    elif re.fullmatch(r"\d{1,2}:\d{2}", 時間または分後):
        target = datetime.strptime(時間または分後, "%H:%M").replace(
            year=now.year, month=now.month, day=now.day, tzinfo=JST
        )
        if target < now:
            target += timedelta(days=1)
        remind_time = target
        wait_seconds = (remind_time - now).total_seconds()

    # ● 「11/01 21:30」
    elif re.fullmatch(r"\d{1,2}/\d{1,2} \d{1,2}:\d{2}", 時間または分後):
        target = datetime.strptime(時間または分後, "%m/%d %H:%M").replace(
            year=now.year, tzinfo=JST
        )
        if target < now:
            target = target.replace(year=now.year + 1)
        remind_time = target
        wait_seconds = (remind_time - now).total_seconds()

    # ● 無効形式
    else:
        await interaction.followup.send("時間形式が無効です。", ephemeral=True)
        return

    # 一意のID
    remind_id = f"{interaction.user.id}-{remind_time.strftime('%Y%m%d%H%M%S')}"

    # -----------------------------------------------------
    # リマインド内容入力モーダル
    # -----------------------------------------------------
    class ReminderMessageModal(discord.ui.Modal, title="リマインド内容入力"):

        message_input = discord.ui.TextInput(
            label="リマインド内容（改行可：Shift+Enter）",
            style=discord.TextStyle.paragraph,
            required=True
        )

        async def on_submit(self, modal_interaction: discord.Interaction):

            message_text = self.message_input.value.strip()

            # ---------------------------------------------
            # リマインドタスク（指定時間後にWebhook送信）
            # ---------------------------------------------
            async def remind_task():
                try:
                    await asyncio.sleep(wait_seconds)

                    webhook = await modal_interaction.channel.create_webhook(
                        name=interaction.user.display_name
                    )

                    await webhook.send(
                        message_text,
                        username=interaction.user.display_name,
                        avatar_url=(
                            interaction.user.display_avatar.url
                            if interaction.user.display_avatar
                            else None
                        )
                    )
                    await asyncio.sleep(1)
                    await webhook.delete()

                except Exception as e:
                    print(f"リマインド送信エラー: {e}")

                finally:
                    reminders.pop(remind_id, None)
                    save_reminders()

            # タスク開始
            task = asyncio.create_task(remind_task())

            # 永続化データ保存
            reminders[remind_id] = {
                "task": task,
                "time": remind_time.isoformat(),
                "message": message_text,
                "user_id": modal_interaction.user.id,
                "channel_id": modal_interaction.channel.id
            }
            save_reminders()

            # ---------------------------------------------
            # 削除ボタンビュー
            # ---------------------------------------------
            class CancelButton(discord.ui.View):
                def __init__(self, user_id, remind_id):
                    super().__init__(timeout=None)
                    self.user_id = user_id
                    self.remind_id = remind_id

                @discord.ui.button(
                    label="リマインドを削除",
                    style=discord.ButtonStyle.danger
                )
                async def delete(self, interaction2: discord.Interaction, button):

                    if interaction2.user.id != self.user_id:
                        await interaction2.response.send_message(
                            "削除権限がありません。",
                            ephemeral=True
                        )
                        return

                    if self.remind_id in reminders:
                        reminders[self.remind_id]["task"].cancel()
                        del reminders[self.remind_id]
                        save_reminders()

                        await interaction2.response.edit_message(
                            content="リマインドを削除しました。",
                            view=None
                        )
                    else:
                        await interaction2.response.send_message(
                            "このリマインドは既に削除されています。",
                            ephemeral=True
                        )

            view = CancelButton(interaction.user.id, remind_id)

            await modal_interaction.response.send_message(
                f"リマインドを設定しました：{remind_time.strftime('%m/%d %H:%M')}\n"
                f"> {message_text}",
                view=view,
                ephemeral=True
            )

    await interaction.followup.send_modal(ReminderMessageModal())


# ---------------------------------------------------------
# ✅ 永続化：読み込み
# ---------------------------------------------------------
def load_reminders():
    if os.path.exists(REMINDERS_FILE):
        try:
            with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"リマインド読み込み失敗: {e}")
    return {}


# ---------------------------------------------------------
# ✅ 永続化：保存
# ---------------------------------------------------------
def save_reminders():
    try:
        with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
            json.dump(reminders, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"リマインド保存失敗: {e}")


# ---------------------------------------------------------
# ✅ Bot起動時：未完了リマインド復元
# ---------------------------------------------------------
async def restore_reminders():

    global reminders
    reminders = load_reminders()
    now = datetime.now(JST)
    restored = 0

    for rid, data in list(reminders.items()):

        remind_time = datetime.fromisoformat(data["time"])
        wait_seconds = (remind_time - now).total_seconds()

        # 過ぎていれば削除
        if wait_seconds <= 0:
            del reminders[rid]
            continue

        # -----------------------------
        # 復元用タスクを再生成
        # -----------------------------
        async def remind_task(remind_id=rid, data=data):
            try:
                await asyncio.sleep(wait_seconds)

                channel = bot.get_channel(data["channel_id"])
                user = bot.get_user(data["user_id"])

                if channel and user:
                    webhook = await channel.create_webhook(name=user.display_name)
                    await webhook.send(
                        data["message"],
                        username=user.display_name,
                        avatar_url=(
                            user.display_avatar.url
                            if user.display_avatar
                            else None
                        )
                    )
                    await asyncio.sleep(1)
                    await webhook.delete()

            except Exception as e:
                print(f"復元リマインド送信エラー: {e}")

            finally:
                reminders.pop(remind_id, None)
                save_reminders()

        asyncio.create_task(remind_task())
        restored += 1

    if restored > 0:
        print(f"復元したリマインド数: {restored}")

    save_reminders()


# =========================================================
# ✅ RSS自動チェック（feedparser）
# =========================================================
@tasks.loop(minutes=10)  # ← 10分間隔でチェック（変更可）
async def check_feeds():

    for channel_id, info in tracking_feeds.items():

        url = info.get("url")
        latest = info.get("latest")  # 最後に投稿した記事のID

        if not url:
            continue

        # RSS取得
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"RSS取得エラー: {e}")
            continue

        if not feed.entries:
            continue

        # 最新記事
        entry = feed.entries[0]

        # 記事IDの決定（RSS差異対策）
        entry_id = (
            entry.get("id")
            or entry.get("guid")
            or entry.get("link")
            or entry.get("title")
        )

        # 既に投稿済みならスキップ
        if entry_id == latest:
            continue

        # チャンネル取得
        channel = bot.get_channel(int(channel_id))
        if not channel:
            continue

        # 投稿
        embed = discord.Embed(
            title=entry.get("title", "無題"),
            description=entry.get("summary", "")[:2000],
            url=entry.get("link", ""),
            timestamp=datetime.now(JST),
            color=discord.Color.blue()
        )

        await channel.send(embed=embed)

        # 最新記事ID更新
        tracking_feeds[channel_id]["latest"] = entry_id
        save_feeds()

        print(f"RSS更新検知 → {channel_id} に投稿: {entry.get('title')}")


# =========================================================
# ✅ GOLD グループコマンド
# =========================================================
class GoldGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="a1_gold", description="GOLD関連コマンド")

    # ---------------------------------------------
    # 残高確認
    # ---------------------------------------------
    @app_commands.command(name="残高確認", description="あなたの所持GOLDを確認します")
    async def balance(self, interaction: discord.Interaction):
        uid = interaction.user.id
        amount = get_balance(uid)

        await interaction.response.send_message(
            f"あなたの所持GOLDは {amount} GOLD です。",
            ephemeral=True
        )

    # ---------------------------------------------
    # 送金
    # ---------------------------------------------
    @app_commands.command(name="送金", description="任意のユーザーにGOLDを送金します")
    @app_commands.describe(
        ユーザー="送金相手",
        GOLD="送金するGOLDの量"
    )
    async def send(
        self,
        interaction: discord.Interaction,
        ユーザー: discord.Member,
        GOLD: int
    ):

        # 不正チェック
        if GOLD <= 0:
            await interaction.response.send_message(
                "0以下の金額は送金できません。",
                ephemeral=True
            )
            return

        if get_balance(interaction.user.id) < GOLD:
            await interaction.response.send_message(
                "所持GOLDが不足しています。",
                ephemeral=True
            )
            return

        # 送金処理
        add_gold(interaction.user.id, -GOLD)
        add_gold(ユーザー.id, GOLD)

        await interaction.response.send_message(
            f"{ユーザー.display_name} に {GOLD} GOLD を送金しました。",
            ephemeral=True
        )


# Bot にグループを登録
bot.tree.add_command(GoldGroup())


# =========================================================
# ✅ リアクションロール設定コマンド
# =========================================================
@bot.tree.command(
    name="x1_リアクションロール設定",
    description="リアクションでロールを付与するメッセージを作成します【管理者のみ】"
)
@app_commands.describe(
    絵文字とロール="『絵文字:ロール名』をカンマ区切りで指定（例：1️⃣:猫,2️⃣:犬）",
    複数選択="True=複数選択可、False=一人一つ"
)
@app_commands.default_permissions(manage_roles=True)
async def reaction_role_setup(
    interaction: discord.Interaction,
    絵文字とロール: str,
    複数選択: bool = True
):
    # ---------------------------------------------------------
    # 入力解析
    # ---------------------------------------------------------
    pairs = [x.strip() for x in re.split("[,、]", 絵文字とロール) if x.strip()]
    emoji_role_pairs = []

    for p in pairs:
        if ":" not in p:
            await interaction.response.send_message(f"形式が不正です: {p}", ephemeral=True)
            return

        emoji, role_name = p.split(":", 1)
        role_name = role_name.strip()

        role = discord.utils.get(interaction.guild.roles, name=role_name)
        if not role:
            role = await interaction.guild.create_role(name=role_name)

        emoji_role_pairs.append((emoji.strip(), role))

    # ---------------------------------------------------------
    # モーダル定義
    # ---------------------------------------------------------
    class ReactionMessageModal(discord.ui.Modal, title="リアクションロールメッセージ入力"):
        message_input = discord.ui.TextInput(
            label="メッセージ本文",
            style=discord.TextStyle.paragraph,
            required=True
        )

        async def on_submit(self, modal_interaction: discord.Interaction):
            content = self.message_input.value.strip()
            msg = await modal_interaction.channel.send(content)

            # 反応追加
            for emoji, _ in emoji_role_pairs:
                try:
                    await msg.add_reaction(emoji)
                except:
                    pass

            # 保存
            reaction_role_data[str(msg.id)] = {
                "roles": {emoji: role.id for emoji, role in emoji_role_pairs},
                "exclusive": not 複数選択,
                "guild_id": interaction.guild.id,
            }
            save_reaction_roles()

            await modal_interaction.response.send_message(
                f"設定完了（ID: {msg.id}）",
                ephemeral=True
            )

    # モーダル送信
    await interaction.response.send_modal(ReactionMessageModal())


# =========================================================
# ✅ リアクション追加イベント
# =========================================================
@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return

    msg_id = str(payload.message_id)
    if msg_id not in reaction_role_data:
        return

    guild = bot.get_guild(payload.guild_id)
    member = guild.get_member(payload.user_id)
    data = reaction_role_data[msg_id]
    emoji = str(payload.emoji)

    if emoji not in data["roles"]:
        return

    role = guild.get_role(data["roles"][emoji])
    if not role:
        return

    # 排他設定
    if data.get("exclusive"):
        for e, r_id in data["roles"].items():
            r = guild.get_role(r_id)
            if r and r in member.roles:
                await member.remove_roles(r)

    await member.add_roles(role)


# =========================================================
# ✅ リアクション削除イベント
# =========================================================
@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    msg_id = str(payload.message_id)
    if msg_id not in reaction_role_data:
        return

    guild = bot.get_guild(payload.guild_id)
    member = guild.get_member(payload.user_id)
    data = reaction_role_data[msg_id]
    emoji = str(payload.emoji)

    if emoji not in data["roles"]:
        return

    role = guild.get_role(data["roles"][emoji])
    if not role:
        return

    await member.remove_roles(role)


# =========================================================
# ✅ リアクションロール本文編集
# =========================================================
@bot.tree.command(
    name="y1_リアクションロール本文編集",
    description="リアクションロールメッセージの本文を編集します【管理者のみ】"
)
@app_commands.describe(
    メッセージID="編集するメッセージID",
    新しい本文="差し替える本文"
)
@app_commands.default_permissions(manage_roles=True)
async def reaction_role_edit_message(interaction: discord.Interaction, メッセージID: str, 新しい本文: str):

    if メッセージID not in reaction_role_data:
        await interaction.response.send_message("指定IDは登録されていません。", ephemeral=True)
        return

    try:
        msg = await interaction.channel.fetch_message(int(メッセージID))
    except:
        await interaction.response.send_message("このチャンネルではメッセージが見つかりません。", ephemeral=True)
        return

    await msg.edit(content=新しい本文)
    await interaction.response.send_message("本文を更新しました。", ephemeral=True)


# =========================================================
# ✅ リアクションロール追加
# =========================================================
@bot.tree.command(
    name="y2_リアクションロール追加",
    description="既存リアクションロールに絵文字:ロール を追加します【管理者のみ】"
)
@app_commands.describe(
    メッセージID="対象メッセージID",
    絵文字="追加する絵文字",
    ロール名="紐づけたいロール名（なければ自動作成）"
)
@app_commands.default_permissions(manage_roles=True)
async def reaction_role_add(interaction: discord.Interaction, メッセージID: str, 絵文字: str, ロール名: str):

    if メッセージID not in reaction_role_data:
        await interaction.response.send_message("登録されていません。", ephemeral=True)
        return

    guild = interaction.guild

    try:
        msg = await interaction.channel.fetch_message(int(メッセージID))
    except:
        await interaction.response.send_message("メッセージが見つかりません。", ephemeral=True)
        return

    role = discord.utils.get(guild.roles, name=ロール名)
    if not role:
        role = await guild.create_role(name=ロール名)

    reaction_role_data[メッセージID]["roles"][絵文字] = role.id
    save_reaction_roles()

    try:
        await msg.add_reaction(絵文字)
    except:
        pass

    await interaction.response.send_message("追加しました。", ephemeral=True)


# =========================================================
# ✅ リアクションロール削除
# =========================================================
@bot.tree.command(
    name="y3_リアクションロール削除",
    description="指定した絵文字のリアクションロール設定を削除します【管理者のみ】"
)
@app_commands.describe(
    メッセージID="対象メッセージID",
    絵文字="削除する絵文字"
)
@app_commands.default_permissions(manage_roles=True)
async def reaction_role_delete(interaction: discord.Interaction, メッセージID: str, 絵文字: str):

    if メッセージID not in reaction_role_data:
        await interaction.response.send_message("登録されていません。", ephemeral=True)
        return

    if 絵文字 not in reaction_role_data[メッセージID]["roles"]:
        await interaction.response.send_message("その絵文字は設定されていません。", ephemeral=True)
        return

    del reaction_role_data[メッセージID]["roles"][絵文字]
    save_reaction_roles()

    await interaction.response.send_message("削除しました。", ephemeral=True)


# =========================================================
# ✅ 問い合わせチャンネル・削除機能
# =========================================================

# ---------------------------------------------------------
# 問い合わせボタン設置コマンド
# ---------------------------------------------------------
@bot.tree.command(
    name="x2_問い合わせ設定",
    description="問い合わせボタンを設置します【管理者のみ】"
)
@app_commands.describe(
    対応ロール="問い合わせ対応ロール",
    ボタン名="ボタン名（例：質問,要望,申請）"
)
@app_commands.default_permissions(administrator=True)
async def inquiry_setup(
    interaction: discord.Interaction,
    対応ロール: discord.Role,
    ボタン名: str
):
    labels = [x.strip() for x in re.split("[,、]", ボタン名) if x.strip()]
    if not labels:
        await interaction.response.send_message("ボタン名が指定されていません。", ephemeral=True)
        return

    # -----------------------------------------------------
    # 問い合わせ本文入力モーダル
    # -----------------------------------------------------
    class InquiryMessageModal(discord.ui.Modal, title="問い合わせメッセージ入力"):
        message_input = discord.ui.TextInput(
            label="メッセージ本文",
            style=discord.TextStyle.paragraph,
            required=True
        )

        async def on_submit(self, modal_interaction: discord.Interaction):
            view = InquiryButtonView(対応ロール, labels, self.message_input.value)
            await modal_interaction.channel.send(self.message_input.value, view=view)
            await modal_interaction.response.send_message(
                "問い合わせボタンを設置しました。",
                ephemeral=True
            )

    await interaction.response.send_modal(InquiryMessageModal())


# ---------------------------------------------------------
# ボタンビュー（複数ボタン用）
# ---------------------------------------------------------
class InquiryButtonView(discord.ui.View):
    def __init__(self, role, labels, message):
        super().__init__(timeout=None)
        self.role = role
        self.message = message

        for label in labels:
            self.add_item(
                InquiryButton(label=label, role=role, message=message)
            )


# ---------------------------------------------------------
# 個別問い合わせボタン
# ---------------------------------------------------------
class InquiryButton(discord.ui.Button):
    def __init__(self, label, role, message):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.role = role
        self.message = message

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user
        category = interaction.channel.category
        channel_name = f"{user.display_name}-{self.label}"

        # チャンネル権限
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            self.role: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }

        # チャンネル作成
        new_channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites
        )

        # 削除ボタン
        view = DeleteChannelButton()

        await new_channel.send(
            f"{user.mention} さんの『{self.label}』チャンネルが作成されました。\n"
            "問い合わせをやめる場合は「チャンネルを削除する」を押してください。",
            view=view
        )


# ---------------------------------------------------------
# チャンネル削除ボタン
# ---------------------------------------------------------
class DeleteChannelButton(discord.ui.View):
    @discord.ui.button(label="チャンネルを削除する", style=discord.ButtonStyle.danger)
    async def delete_channel(self, interaction: discord.Interaction, button: discord.ui.Button):

        await interaction.response.send_message(
            "数秒後にチャンネルを削除します。",
            ephemeral=True
        )

        await asyncio.sleep(5)

        await interaction.channel.delete(reason="問い合わせ完了により削除")


# =========================================================
# ✅ ピン留め（テンプレート自動表示）
# =========================================================

# ---------------------------------------------------------
# ピン留め設定：テンプレート登録
# ---------------------------------------------------------
@bot.tree.command(
    name="x3_ピン留め設定",
    description="このチャンネルにピン留めを設定します【管理者のみ】"
)
@app_commands.default_permissions(administrator=True)
async def pin_set(interaction: discord.Interaction):

    # -----------------------------------------------------
    # モーダル：ピン留め内容の入力
    # -----------------------------------------------------
    class PinMessageModal(discord.ui.Modal, title="ピン留め内容入力"):
        pin_input = discord.ui.TextInput(
            label="ピン留め内容",
            style=discord.TextStyle.paragraph,
            required=True,
            placeholder="このチャンネルに常に表示したいテンプレートメッセージを入力"
        )

        async def on_submit(self, modal_interaction: discord.Interaction):
            channel_id = str(modal_interaction.channel.id)

            auto_templates[channel_id] = self.pin_input.value.strip()
            save_templates()

            await modal_interaction.response.send_message(
                "ピン留めを設定しました。",
                ephemeral=True
            )

    await interaction.response.send_modal(PinMessageModal())


# ---------------------------------------------------------
# ピン留め停止：テンプレート削除
# ---------------------------------------------------------
@bot.tree.command(
    name="x4_ピン留め停止",
    description="ピン留めを停止します【管理者のみ】"
)
@app_commands.default_permissions(administrator=True)
async def pin_stop(interaction: discord.Interaction):
    channel_id = str(interaction.channel.id)

    if channel_id in auto_templates:
        del auto_templates[channel_id]
        save_templates()

        await interaction.response.send_message(
            "ピン留めを停止しました。",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "このチャンネルには設定されていません。",
            ephemeral=True
        )


# =========================================================
# ✅ Bot起動イベント（Render最適化）
# =========================================================
@bot.event
async def on_ready():

    # -----------------------------------------------------
    # データロード
    # -----------------------------------------------------
    load_all_data()

    # リアクションロール設定ロード（破損対策つき）
    global reaction_role_data
    if os.path.exists(REACTION_FILE):
        try:
            with open(REACTION_FILE, "r", encoding="utf-8") as f:
                reaction_role_data = json.load(f)
        except Exception:
            reaction_role_data = {}

    # -----------------------------------------------------
    # コマンド同期
    # -----------------------------------------------------
    await bot.tree.sync()
    print(f"✅ ログイン完了: {bot.user}")

    # -----------------------------------------------------
    # 定期タスク起動（多重起動防止）
    # -----------------------------------------------------
    if not check_feeds.is_running():
        check_feeds.start()

    if not daily_gold_distribution.is_running():
        daily_gold_distribution.start()

    # -----------------------------------------------------
    # 初回ボーナス配布（1回のみ）
    # -----------------------------------------------------
    await distribute_initial_gold()

    # -----------------------------------------------------
    # リマインド復元
    # -----------------------------------------------------
    await restore_reminders()
    print("✅ リマインド復元完了")


# =========================================================
# ✅ Render常時稼働 keep_alive + bot.run
# =========================================================
keep_alive()  # ← Render で24時間稼働させるために必要
bot.run(os.getenv("DISCORD_TOKEN"))
