import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio, json, os, re, time
from datetime import datetime, timedelta, timezone
from datetime import time as dtime
from keep_alive import keep_alive
import feedparser

# ===== 基本設定 =====
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)
JST = timezone(timedelta(hours=9))

# ===== データファイル =====
DATA_FILE = "cl_data.json"
FEEDS_FILE = "feeds.json"
TEMPLATE_FILE = "auto_templates.json"  # ピン留め用

cl_data = {"users": {}, "enabled": False}
reminders = {}
voice_sessions = {}
tracking_feeds = {}

# ピン留め：チャンネルごとのテンプレテキスト/直近テンプレメッセID
def load_templates():
    if os.path.exists(TEMPLATE_FILE):
        with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}
def save_templates(data):
    with open(TEMPLATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
auto_templates = load_templates()
last_template_messages = {}  # {channel_id: message_id}

# ===== データ管理 =====
def load_data():
    global cl_data
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                cl_data = json.load(f)
        except:
            print("Communication Level データ読み込み失敗。新規作成します。")
            cl_data = {"users": {}, "enabled": False}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(cl_data, f, ensure_ascii=False, indent=4)

def load_feeds():
    global tracking_feeds
    if os.path.exists(FEEDS_FILE):
        try:
            with open(FEEDS_FILE, "r", encoding="utf-8") as f:
                tracking_feeds = json.load(f)
        except:
            print("RSSデータ読み込み失敗。新規作成します。")
            tracking_feeds = {}

def save_feeds():
    with open(FEEDS_FILE, "w", encoding="utf-8") as f:
        json.dump(tracking_feeds, f, ensure_ascii=False, indent=4)



#------------------------------------------------------------------------------------------------------------



# ===== Communication Level 設定 =====
CL_LEVELS = [
    {"name": "Communication Level 1", "text": 10, "vc": 30, "color": 0x999999},
    {"name": "Communication Level 2", "text": 50, "vc": 180, "color": 0x55ff55},
    {"name": "Communication Level 3", "text": 100, "vc": 720, "color": 0x3333ff},
    {"name": "Communication Level 4", "text": 333, "vc": 1440, "color": 0x8800ff},
    {"name": "Communication Level 5", "text": 666, "vc": 7200, "color": 0xffff00},
    {"name": "Communication Level 6", "text": 1000, "vc": 14400, "color": 0xff5555},
]

# ===== on_voice_state_update =====
@bot.event
async def on_voice_state_update(member, before, after):
    if not cl_data.get("enabled"):
        return
    user_id = str(member.id)

    # 入室時刻を記録
    if before.channel is None and after.channel is not None:
        voice_sessions[user_id] = time.time()

    # 退出時に滞在時間を加算
    elif before.channel is not None and after.channel is None:
        if user_id in voice_sessions:
            duration = int((time.time() - voice_sessions[user_id]) / 60)
            del voice_sessions[user_id]

            # Communication Levelデータ更新
            if user_id not in cl_data["users"]:
                cl_data["users"][user_id] = {"text": 0, "vc": 0}
            cl_data["users"][user_id]["vc"] += duration
            save_data()

            # 🔸 VC滞在報酬：1分につき5GOLD
            if duration > 0:
                try:
                    add_gold(member.id, duration * 5)
                except Exception as e:
                    print(f"VC報酬付与エラー: {e}")

            await check_and_assign_roles(member)

# ===== ロール付与処理 =====
async def check_and_assign_roles(member: discord.Member):
    guild = member.guild
    user_id = str(member.id)
    data = cl_data["users"].get(user_id, {"text": 0, "vc": 0})
    text = data["text"]
    vc = data["vc"]

    achieved = None
    color = None
    for level in CL_LEVELS:
        if text >= level["text"] and vc >= level["vc"]:
            achieved = level["name"]
            color = level["color"]
        else:
            break

    if not achieved:
        return

    role = discord.utils.get(guild.roles, name=achieved)
    if not role:
        role = await guild.create_role(name=achieved, color=discord.Color(color))

    if role not in member.roles:
        await member.add_roles(role)
        print(f"{member.display_name} に {achieved} を付与しました")

    for level in CL_LEVELS:
        if level["name"] != achieved:
            r = discord.utils.get(guild.roles, name=level["name"])
            if r in member.roles:
                await member.remove_roles(r)
                print(f"{member.display_name} から {level['name']} を削除しました")

# ===== ON/OFFコマンド =====
@bot.tree.command(name="z1_cl_on", description="Communication Level機能をONにします（管理者のみ）")
@app_commands.default_permissions(administrator=True)
async def z1_cl_on(interaction: discord.Interaction):
    cl_data["enabled"] = True
    save_data()
    await interaction.response.send_message("Communication Level機能をONにしました。", ephemeral=True)

@bot.tree.command(name="z2_cl_off", description="Communication Level機能をOFFにします（管理者のみ）")
@app_commands.default_permissions(administrator=True)
async def z2_cl_off(interaction: discord.Interaction):
    cl_data["enabled"] = False
    save_data()
    await interaction.response.send_message("Communication Level機能をOFFにしました。", ephemeral=True)


#------------------------------------------------------------------------------------------------------------


# ===== ロール付与メッセージ機能 =====
@bot.tree.command(
    name="x1_ロール付与メッセージ",
    description="ボタンでロールを付与するメッセージを作成します（管理者のみ）"
)
@app_commands.describe(
    メッセージ内容="表示するメッセージ",
    ボタンとロール="『ボタン名:ロール名』をカンマまたは読点区切りで入力"
)
@app_commands.default_permissions(manage_roles=True)
async def role_message(interaction: discord.Interaction, メッセージ内容: str, ボタンとロール: str):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("権限がありません。", ephemeral=True)
        return

    try:
        pairs = [x.strip() for x in re.split("[,、]", ボタンとロール) if x.strip()]
        button_role_pairs = []
        for p in pairs:
            if ":" not in p:
                await interaction.response.send_message("入力形式が正しくありません。『ボタン名:ロール名』の形式で指定してください。", ephemeral=True)
                return
            label, role_name = p.split(":", 1)
            role = discord.utils.get(interaction.guild.roles, name=role_name.strip())
            if not role:
                await interaction.response.send_message(f"ロール「{role_name.strip()}」が見つかりません。", ephemeral=True)
                return
            button_role_pairs.append((label.strip(), role))
    except Exception as e:
        await interaction.response.send_message(f"入力解析に失敗しました: {e}", ephemeral=True)
        return

    view = RoleSelectView(button_role_pairs)
    await interaction.response.defer()
    await interaction.channel.send(メッセージ内容, view=view)

class RoleSelectView(discord.ui.View):
    def __init__(self, button_role_pairs):
        super().__init__(timeout=None)
        for label, role in button_role_pairs:
            self.add_item(RoleButton(label=label, role=role))

class RoleButton(discord.ui.Button):
    def __init__(self, label, role):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.role = role

    async def callback(self, interaction: discord.Interaction):
        member = interaction.user
        role = self.role
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(f"{role.name} ロールを操作できません（Botの権限階層が下です）。", ephemeral=True)
            return
        try:
            if role in member.roles:
                await member.remove_roles(role)
            else:
                await member.add_roles(role)
        except discord.Forbidden:
            await interaction.response.send_message(f"{role.name} の付与／削除に失敗しました（Botの権限不足）。", ephemeral=True)
            return
        except Exception as e:
            await interaction.response.send_message(f"予期せぬエラー: {e}", ephemeral=True)
            return
        await interaction.response.defer()


#------------------------------------------------------------------------------------------------------------


# ===== 問い合わせ設定 =====
@bot.tree.command(name="x2_問い合わせ設定", description="問い合わせボタンを設置します（管理者のみ）")
@app_commands.describe(
    対象ロール="問い合わせに対応するロールを指定してください（例：@スタッフ）",
    メッセージ内容="上部に表示する説明メッセージ",
    ボタンと説明="例：『バグ報告:不具合報告はこちら』『質問:質問はこちら』（カンマ区切り）"
)
@app_commands.default_permissions(administrator=True)
async def a6_inquiry_setup(
    interaction: discord.Interaction,
    対象ロール: discord.Role,
    メッセージ内容: str,
    ボタンと説明: str
):
    # 入力解析
    try:
        pairs = [x.strip() for x in re.split("[,、]", ボタンと説明) if x.strip()]
        button_data = []
        for p in pairs:
            if ":" not in p:
                await interaction.response.send_message("入力形式が間違っています。『ボタン名:説明』の形式で指定してください。", ephemeral=True)
                return
            label, desc = p.split(":", 1)
            button_data.append((label.strip(), desc.strip()))
    except Exception as e:
        await interaction.response.send_message(f"入力エラー: {e}", ephemeral=True)
        return

    # ボタン生成
    view = InquiryButtonView(対象ロール, button_data)
    await interaction.response.send_message("問い合わせボタンを設置しました。", ephemeral=True)
    await interaction.channel.send(メッセージ内容, view=view)

class InquiryButtonView(discord.ui.View):
    def __init__(self, role, button_data):
        super().__init__(timeout=None)
        self.role = role
        for label, desc in button_data:
            self.add_item(InquiryButton(label=label, desc=desc, role=role))

class InquiryButton(discord.ui.Button):
    def __init__(self, label, desc, role):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.desc = desc
        self.role = role

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user
        category = interaction.channel.category

        channel_name = f"{user.display_name}-{self.label}"
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            self.role: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }

        new_channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites
        )

        view = DeleteChannelButton()
        await new_channel.send(
            f"{user.mention} さんの『{self.label}』用チャンネルが作成されました。\n{self.desc}",
            view=view
        )
        await interaction.response.send_message(f"チャンネルを作成しました → {new_channel.mention}", ephemeral=True)

class DeleteChannelButton(discord.ui.View):
    @discord.ui.button(label="チャンネルを削除する", style=discord.ButtonStyle.danger)
    async def delete_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("このチャンネルは5秒後に削除されます。", ephemeral=True)
        await asyncio.sleep(5)
        await interaction.channel.delete(reason="問い合わせ完了により削除")


#------------------------------------------------------------------------------------------------------------


# ===== ピン留め =====
@bot.tree.command(name="x3_ピン留め設定", description="このチャンネルにピン留めを設定します（管理者のみ）")
@app_commands.describe(メッセージ="ピン留め内容")
@app_commands.default_permissions(administrator=True)
async def a2_pin(interaction: discord.Interaction, メッセージ: str):
    channel_id = str(interaction.channel.id)
    auto_templates[channel_id] = メッセージ
    save_templates(auto_templates)
    await interaction.response.send_message("このチャンネルにピン留めを設定しました。", ephemeral=True)

@bot.tree.command(name="x4_ピン留め停止", description="このチャンネルのピン留めを停止します（管理者のみ）")
@app_commands.default_permissions(administrator=True)
async def a3_pin_stop(interaction: discord.Interaction):
    channel_id = str(interaction.channel.id)
    if channel_id in auto_templates:
        del auto_templates[channel_id]
        save_templates(auto_templates)
        await interaction.response.send_message("このチャンネルのピン留めを停止しました。", ephemeral=True)
    else:
        await interaction.response.send_message("このチャンネルにはピン留めが設定されていません。", ephemeral=True)

# ===== 統合 on_message（CLカウント + ピン留め維持 + チャット報酬） =====
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    channel_id = str(message.channel.id)

    # 🔸 チャット報酬：2文字につき1GOLD
    try:
        gain = len(message.content) // 2
        if gain > 0:
            add_gold(message.author.id, gain)
    except Exception as e:
        print(f"チャット報酬付与エラー: {e}")

    # ピン留めテンプレ維持
    if channel_id in auto_templates:
        template_text = auto_templates[channel_id]
        if channel_id in last_template_messages:
            try:
                old_msg = await message.channel.fetch_message(last_template_messages[channel_id])
                await old_msg.delete()
            except discord.NotFound:
                pass
            except discord.Forbidden:
                print(f"Botに削除権限がありません（チャンネルID: {channel_id}）")
            except Exception as e:
                print(f"ピン留め削除エラー: {e}")
        try:
            new_msg = await message.channel.send(template_text)
            last_template_messages[channel_id] = new_msg.id
        except discord.Forbidden:
            print(f"Botに送信権限がありません（チャンネルID: {channel_id}）")
        except Exception as e:
            print(f"ピン留め投稿エラー: {e}")

    # Communication Level 記録
    if cl_data.get("enabled"):
        user_id = str(message.author.id)
        if user_id not in cl_data["users"]:
            cl_data["users"][user_id] = {"text": 0, "vc": 0}
        cl_data["users"][user_id]["text"] += len(message.content)
        save_data()
        await check_and_assign_roles(message.author)

    # 他コマンド処理
    await bot.process_commands(message)


#------------------------------------------------------------------------------------------------------------


# ===== Xポスト引用 (RSS) =====
@tasks.loop(minutes=5)
async def check_feeds():
    for channel_id, info in tracking_feeds.items():
        channel = bot.get_channel(int(channel_id))
        if channel is None:
            continue
        feed = feedparser.parse(info["rss"])
        if not feed.entries:
            continue
        latest_entry = feed.entries[0]
        latest_link = latest_entry.link
        desc = latest_entry.get("description", "").lower()
        if latest_link != info.get("latest") and not any(x in desc for x in ["rt @", "retweeted", "mention"]):
            info["latest"] = latest_link
            save_feeds()
            await channel.send(latest_link)

@bot.tree.command(name="x5_xポスト引用", description="指定アカウントの新規ポスト・引用を自動で貼ります（管理者のみ）")
@app_commands.describe(アカウント名="例：elonmusk")
@app_commands.default_permissions(administrator=True)
async def a4_xpost(interaction: discord.Interaction, アカウント名: str):
    rss_url = f"https://nitter.net/{アカウント名}/rss"
    tracking_feeds[str(interaction.channel.id)] = {"rss": rss_url, "latest": None}
    save_feeds()
    if not check_feeds.is_running():
        check_feeds.start()
    await interaction.response.send_message(f"@{アカウント名} の投稿監視を開始しました。", ephemeral=True)

@bot.tree.command(name="x6_xポスト停止", description="このチャンネルでのXポスト監視を停止します（管理者のみ）")
@app_commands.default_permissions(administrator=True)
async def a5_xpost_stop(interaction: discord.Interaction):
    channel_id = str(interaction.channel.id)
    if channel_id in tracking_feeds:
        del tracking_feeds[channel_id]
        save_feeds()
        await interaction.response.send_message("このチャンネルでのXポスト監視を停止しました。", ephemeral=True)
    else:
        await interaction.response.send_message("このチャンネルでは現在Xポスト監視が有効ではありません。", ephemeral=True)



#------------------------------------------------------------------------------------------------------------



# ===== Goldシステム（通貨 + ショップ） =====

GOLD_FILE = "gold_data.json"
SHOP_CATEGORIES = ["装飾", "称号", "ロール"]

# --- Goldデータ読み込み／保存 ---
def load_gold():
    if os.path.exists(GOLD_FILE):
        with open(GOLD_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}
def save_gold(data):
    with open(GOLD_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

gold_data = load_gold()

# --- 残高取得 ---
def get_balance(user_id: int) -> int:
    return gold_data.get(str(user_id), 0)

# --- 残高追加／減少 ---
def add_gold(user_id: int, amount: int):
    uid = str(user_id)
    gold_data[uid] = gold_data.get(uid, 0) + amount
    save_gold(gold_data)

@tasks.loop(time=dtime(hour=0, minute=0, tzinfo=JST))
async def daily_gold_distribution():
    count = 0
    for guild in bot.guilds:
        for member in guild.members:
            if member.bot:
                continue
            add_gold(member.id, 100)
            count += 1
    print(f"[{datetime.now(JST).strftime('%m/%d %H:%M')}] 🎁 毎日配布完了: {count}ユーザーに100 GOLD付与")



# ===== 新規参加者へ自動10000GOLD付与 =====
@bot.event
async def on_member_join(member: discord.Member):
    if member.bot:
        return
    try:
        add_gold(member.id, 10000)
        print(f"[JOIN] {member.display_name} に10000 GOLDを付与しました。")
    except Exception as e:
        print(f"新規メンバー初期GOLD付与エラー: {e}")


# ===== 既存メンバーへ一括10000GOLD付与（初回起動時のみ） =====
async def distribute_initial_gold():
    FLAG_FILE = "initial_gold_flag.json"
    if os.path.exists(FLAG_FILE):
        return  # すでに配布済みならスキップ

    count = 0
    for guild in bot.guilds:
        for member in guild.members:
            if member.bot:
                continue
            add_gold(member.id, 10000)
            count += 1

    with open(FLAG_FILE, "w", encoding="utf-8") as f:
        json.dump({"distributed": True, "count": count}, f, ensure_ascii=False, indent=4)

    print(f"💰 初回ボーナス: 既存メンバー {count} 名に10000 GOLDを配布しました。")



# ===== /a1_残高確認 =====
@bot.tree.command(name="a1_残高確認", description="所持GOLDを確認できます")
async def check_gold(interaction: discord.Interaction):
    balance = get_balance(interaction.user.id)
    await interaction.response.send_message(
        f"あなたの所持GOLDは **{balance} GOLD** です💰",
        ephemeral=True
    )



# ===== /a2_送金 =====
@bot.tree.command(name="a2_送金", description="他のユーザーにGOLDを送金します")
@app_commands.describe(
    相手="送金先ユーザー",
    金額="送金するGOLDの額"
)
async def send_gold(interaction: discord.Interaction, 相手: discord.Member, 金額: int):
    sender_id = str(interaction.user.id)
    receiver_id = str(相手.id)
    sender_balance = get_balance(interaction.user.id)

    if 金額 <= 0:
        await interaction.response.send_message("送金額は1以上で指定してください。", ephemeral=True)
        return
    if sender_balance < 金額:
        await interaction.response.send_message("所持GOLDが足りません。", ephemeral=True)
        return
    if sender_id == receiver_id:
        await interaction.response.send_message("自分自身には送金できません。", ephemeral=True)
        return

    # 処理
    add_gold(interaction.user.id, -金額)
    add_gold(相手.id, 金額)

    await interaction.response.send_message(
        f"{相手.display_name} に **{金額} GOLD** を送金しました💸",
        ephemeral=True
    )



# ===== /a3_ショップ =====
@bot.tree.command(name="a3_ショップ", description="GOLDで商品を購入できます")
@app_commands.describe(カテゴリ="ショップカテゴリを選択")
@app_commands.choices(カテゴリ=[
    app_commands.Choice(name="装飾", value="装飾"),
    app_commands.Choice(name="称号", value="称号"),
    app_commands.Choice(name="ロール", value="ロール"),
])
async def shop(interaction: discord.Interaction, カテゴリ: app_commands.Choice[str]):
    balance = get_balance(interaction.user.id)
    cat = カテゴリ.value

    if cat == "装飾":
        msg = (
            f"🎀 **装飾ショップへようこそ！**\n"
            "好きな絵文字で名前を装飾できます！\n"
            "例：🔥あなたの名前🔥\n\n"
            "価格：**1000 GOLD**\n"
            "購入方法：`/購入 絵文字`\n"
            f"（あなたの所持GOLD：**{balance} GOLD**）"
        )

    elif cat == "称号":
        msg = (
            f"🏷️ **称号ショップへようこそ！**\n"
            "オリジナル称号を名前に付与できます！\n"
            "例：`冒険者 あなたの名前`\n\n"
            "価格：**3000 GOLD**\n"
            "購入方法：`/購入 称号名`\n"
            f"（あなたの所持GOLD：**{balance} GOLD**）"
        )

    elif cat == "ロール":
        msg = (
            f"⚔️ **ロールショップへようこそ！**\n"
            "GOLDで好きな属性ロールを購入できます！\n\n"
            "1 🔥火属性🔥　500 GOLD\n"
            "2 💧水属性💧　500 GOLD\n"
            "3 🌪️風属性🌪️　500 GOLD\n"
            "4 🌱土属性🌱　500 GOLD\n\n"
            "購入方法：`/購入 番号`\n"
            f"（あなたの所持GOLD：**{balance} GOLD**）"
        )

    else:
        msg = "存在しないカテゴリです。"

    await interaction.response.send_message(msg, ephemeral=True)


# ===== /購入 =====
@bot.tree.command(name="購入", description="ショップの商品を購入します")
@app_commands.describe(内容="購入内容（例：🔥 または 冒険者 または 1〜4）")
async def buy(interaction: discord.Interaction, 内容: str):
    uid = str(interaction.user.id)
    balance = get_balance(interaction.user.id)

    # --- 装飾 ---
    if 内容.startswith(("🔥", "💧", "🌸", "🌟", "🖤", "💀", "✨", "<:", "<a:")):
        cost = 1000
        if balance < cost:
            await interaction.response.send_message("GOLDが足りません。", ephemeral=True)
            return
        add_gold(interaction.user.id, -cost)
        new_name = f"{内容}{interaction.user.display_name}{内容}"
        await interaction.user.edit(nick=new_name)
        await interaction.response.send_message(f"🔥 名前を装飾しました！ → {new_name}", ephemeral=True)
        return

    # --- 称号 ---
    elif 内容.isalpha() or 内容.isascii() or 内容:
        cost = 3000
        if 内容.isdigit():  # ロール選択に流す
            pass
        else:
            if balance < cost:
                await interaction.response.send_message("GOLDが足りません。", ephemeral=True)
                return
            add_gold(interaction.user.id, -cost)
            new_name = f"{内容} {interaction.user.display_name}"
            await interaction.user.edit(nick=new_name)
            await interaction.response.send_message(f"🏷️ 称号を付与しました！ → {new_name}", ephemeral=True)
            return

    # --- ロール ---
    if 内容.isdigit():
        num = int(内容)
        if num not in [1, 2, 3, 4]:
            await interaction.response.send_message("存在しない番号です。", ephemeral=True)
            return
        cost = 500
        if balance < cost:
            await interaction.response.send_message("GOLDが足りません。", ephemeral=True)
            return
        add_gold(interaction.user.id, -cost)
        roles = {
            1: "🔥火属性🔥",
            2: "💧水属性💧",
            3: "🌪️風属性🌪️",
            4: "🌱土属性🌱"
        }
        role_name = roles[num]
        role = discord.utils.get(interaction.guild.roles, name=role_name)
        if not role:
            role = await interaction.guild.create_role(name=role_name)
        await interaction.user.add_roles(role)
        await interaction.response.send_message(f"✅ {role_name} ロールを購入しました！", ephemeral=True)
        return

    await interaction.response.send_message("購入内容を正しく指定してください。", ephemeral=True)



#------------------------------------------------------------------------------------------------------------



# ===== リマインド =====
@bot.tree.command(name="c1_リマインド", description="指定した時間または日付＋時間にリマインドを送ります（日本時間）")
@app_commands.describe(時間または分後="「21:30」「11/03 21:30」または「15」など", メッセージ="リマインド内容")
async def remind(interaction: discord.Interaction, 時間または分後: str, メッセージ: str):
    await interaction.response.defer(ephemeral=True)
    now = datetime.now(JST)
    remind_time = None
    wait_seconds = None

    if re.fullmatch(r"\d+", 時間または分後):
        minutes = int(時間または分後)
        remind_time = now + timedelta(minutes=minutes)
        wait_seconds = minutes * 60
    elif re.fullmatch(r"\d{1,2}:\d{2}", 時間または分後):
        target = datetime.strptime(時間または分後, "%H:%M").replace(year=now.year, month=now.month, day=now.day, tzinfo=JST)
        if target < now:
            target += timedelta(days=1)
        remind_time = target
        wait_seconds = (remind_time - now).total_seconds()
    elif re.fullmatch(r"\d{1,2}/\d{1,2} \d{1,2}:\d{2}", 時間または分後):
        target = datetime.strptime(時間または分後, "%m/%d %H:%M").replace(year=now.year, tzinfo=JST)
        if target < now:
            target = target.replace(year=now.year + 1)
        remind_time = target
        wait_seconds = (remind_time - now).total_seconds()
    else:
        await interaction.followup.send("時間形式が無効です。", ephemeral=True)
        return

    remind_id = f"{interaction.user.id}-{remind_time.strftime('%Y%m%d%H%M%S')}"
    async def remind_task():
        try:
            await asyncio.sleep(wait_seconds)
            webhook = await interaction.channel.create_webhook(name=interaction.user.display_name)
            await webhook.send(
                メッセージ,
                username=interaction.user.display_name,
                avatar_url=interaction.user.display_avatar.url
            )
            await asyncio.sleep(1)
            await webhook.delete()
        except Exception as e:
            print(f"リマインド送信エラー: {e}")
        finally:
            reminders.pop(remind_id, None)

    task = asyncio.create_task(remind_task())
    reminders[remind_id] = {"task": task, "time": remind_time, "message": メッセージ}
    view = None

    class CancelButton(discord.ui.View):
        def __init__(self, user_id: int, remind_id: str):
            super().__init__(timeout=None)
            self.user_id = user_id
            self.remind_id = remind_id
        @discord.ui.button(label="リマインドを削除", style=discord.ButtonStyle.danger)
        async def cancel_button(self, interaction2: discord.Interaction, button: discord.ui.Button):
            if interaction2.user.id != self.user_id:
                await interaction2.response.send_message("削除権限がありません。", ephemeral=True)
                return
            if self.remind_id in reminders:
                reminders[self.remind_id]["task"].cancel()
                del reminders[self.remind_id]
                await interaction2.response.edit_message(content="リマインドを削除しました。", view=None)
            else:
                await interaction2.response.send_message("このリマインドはすでに削除されています。", ephemeral=True)

    view = CancelButton(interaction.user.id, remind_id)
    await interaction.followup.send(f"リマインドを設定しました：{remind_time.strftime('%m/%d %H:%M')}\n> {メッセージ}", view=view, ephemeral=True)


#------------------------------------------------------------------------------------------------------------


# ===== 起動 =====
@bot.event
async def on_ready():
    load_data()
    load_feeds()
    await bot.tree.sync()
    print(f"ログイン完了: {bot.user}")
    print(f"Communication Level: {'ON' if cl_data['enabled'] else 'OFF'}")
    if not check_feeds.is_running():
        check_feeds.start()
    if not daily_gold_distribution.is_running():
        daily_gold_distribution.start()
    await distribute_initial_gold()


keep_alive()
bot.run(os.getenv("DISCORD_TOKEN"))