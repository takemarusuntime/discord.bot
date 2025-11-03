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
TEMPLATE_FILE = "auto_templates.json"

cl_data = {"users": {}, "enabled": False}
reminders = {}
voice_sessions = {}
tracking_feeds = {}

# ===== 絵文字判定関数 =====
def is_emoji(s: str) -> bool:
    """Unicode絵文字またはDiscordカスタム絵文字かどうかを判定"""
    # カスタム絵文字 (<:name:id> or <a:name:id>)
    if re.fullmatch(r"<a?:\w+:\d+>", s):
        return True
    # 標準絵文字（広範囲対応）
    emoji_pattern = re.compile(r"(<a?:\w+:\d+>|[\U00010000-\U0010FFFF])", flags=re.UNICODE)
    return bool(emoji_pattern.fullmatch(s))

# ===== ピン留めテンプレート管理 =====
def load_templates():
    if os.path.exists(TEMPLATE_FILE):
        with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_templates(data):
    with open(TEMPLATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

auto_templates = load_templates()
last_template_messages = {}

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


# ------------------------------------------------------------------------------------------------------------
# ===== Communication Level 機能 =====

CL_LEVELS = [
    {"name": "Communication Level 1", "text": 10, "vc": 30, "color": 0x999999},
    {"name": "Communication Level 2", "text": 50, "vc": 180, "color": 0x55ff55},
    {"name": "Communication Level 3", "text": 100, "vc": 720, "color": 0x3333ff},
    {"name": "Communication Level 4", "text": 333, "vc": 1440, "color": 0x8800ff},
    {"name": "Communication Level 5", "text": 666, "vc": 7200, "color": 0xffff00},
    {"name": "Communication Level 6", "text": 1000, "vc": 14400, "color": 0xff5555},
]

@bot.event
async def on_voice_state_update(member, before, after):
    if not cl_data.get("enabled"):
        return
    user_id = str(member.id)

    # 入室
    if before.channel is None and after.channel is not None:
        voice_sessions[user_id] = time.time()

    # 退出時
    elif before.channel is not None and after.channel is None:
        if user_id in voice_sessions:
            duration = int((time.time() - voice_sessions[user_id]) / 60)
            del voice_sessions[user_id]

            if user_id not in cl_data["users"]:
                cl_data["users"][user_id] = {"text": 0, "vc": 0}
            cl_data["users"][user_id]["vc"] += duration
            save_data()

            # VC滞在報酬
            if duration > 0:
                try:
                    add_gold(member.id, duration * 5)
                except Exception as e:
                    print(f"VC報酬付与エラー: {e}")

            await check_and_assign_roles(member)

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

# ===== ON/OFF =====
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

# ------------------------------------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------------------------------------
# ===== 問い合わせチャンネル =====
@bot.tree.command(name="x2_問い合わせ設定", description="問い合わせボタンを設置します（管理者のみ）")
@app_commands.describe(
    対象ロール="問い合わせ対応ロールを指定（例：@スタッフ）",
    メッセージ内容="上部に表示する説明メッセージ",
    ボタンと説明="例：『バグ報告:不具合報告はこちら』『質問:質問はこちら』（カンマ区切り）"
)
@app_commands.default_permissions(administrator=True)
async def inquiry_setup(
    interaction: discord.Interaction,
    対象ロール: discord.Role,
    メッセージ内容: str,
    ボタンと説明: str
):
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


# ------------------------------------------------------------------------------------------------------------
# ===== ピン留め機能 =====
@bot.tree.command(name="x3_ピン留め設定", description="このチャンネルにピン留めを設定します（管理者のみ）")
@app_commands.describe(メッセージ="ピン留め内容")
@app_commands.default_permissions(administrator=True)
async def pin_set(interaction: discord.Interaction, メッセージ: str):
    channel_id = str(interaction.channel.id)
    auto_templates[channel_id] = メッセージ
    save_templates(auto_templates)
    await interaction.response.send_message("このチャンネルにピン留めを設定しました。", ephemeral=True)

@bot.tree.command(name="x4_ピン留め停止", description="このチャンネルのピン留めを停止します（管理者のみ）")
@app_commands.default_permissions(administrator=True)
async def pin_stop(interaction: discord.Interaction):
    channel_id = str(interaction.channel.id)
    if channel_id in auto_templates:
        del auto_templates[channel_id]
        save_templates(auto_templates)
        await interaction.response.send_message("このチャンネルのピン留めを停止しました。", ephemeral=True)
    else:
        await interaction.response.send_message("このチャンネルにはピン留めが設定されていません。", ephemeral=True)

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    channel_id = str(message.channel.id)

    # チャット報酬（2文字で1G）
    try:
        gain = len(message.content) // 2
        if gain > 0:
            add_gold(message.author.id, gain)
    except Exception as e:
        print(f"チャット報酬付与エラー: {e}")

    # ピン留め維持
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
        try:
            new_msg = await message.channel.send(template_text)
            last_template_messages[channel_id] = new_msg.id
        except discord.Forbidden:
            print(f"Botに送信権限がありません（チャンネルID: {channel_id}）")

    # Communication Level 記録
    if cl_data.get("enabled"):
        user_id = str(message.author.id)
        if user_id not in cl_data["users"]:
            cl_data["users"][user_id] = {"text": 0, "vc": 0}
        cl_data["users"][user_id]["text"] += len(message.content)
        save_data()
        await check_and_assign_roles(message.author)

    await bot.process_commands(message)


# ------------------------------------------------------------------------------------------------------------
# ===== Xポスト引用（RSS） =====
@tasks.loop(minutes=5)
async def check_feeds():
    for channel_id, info in tracking_feeds.items():
        channel = bot.get_channel(int(channel_id))
        if not channel:
            continue
        feed = feedparser.parse(info["rss"])
        if not feed.entries:
            continue
        latest = feed.entries[0]
        link = latest.link
        desc = latest.get("description", "").lower()
        if link != info.get("latest") and not any(x in desc for x in ["rt @", "retweeted", "mention"]):
            info["latest"] = link
            save_feeds()
            await channel.send(link)

@bot.tree.command(name="x5_xポスト引用", description="指定アカウントの新規ポスト・引用を自動で貼ります（管理者のみ）")
@app_commands.describe(アカウント名="例：elonmusk")
@app_commands.default_permissions(administrator=True)
async def x_post(interaction: discord.Interaction, アカウント名: str):
    rss_url = f"https://nitter.net/{アカウント名}/rss"
    tracking_feeds[str(interaction.channel.id)] = {"rss": rss_url, "latest": None}
    save_feeds()
    if not check_feeds.is_running():
        check_feeds.start()
    await interaction.response.send_message(f"@{アカウント名} の投稿監視を開始しました。", ephemeral=True)

@bot.tree.command(name="x6_xポスト停止", description="このチャンネルでのXポスト監視を停止します（管理者のみ）")
@app_commands.default_permissions(administrator=True)
async def x_post_stop(interaction: discord.Interaction):
    cid = str(interaction.channel.id)
    if cid in tracking_feeds:
        del tracking_feeds[cid]
        save_feeds()
        await interaction.response.send_message("このチャンネルでのXポスト監視を停止しました。", ephemeral=True)
    else:
        await interaction.response.send_message("このチャンネルでは監視が有効ではありません。", ephemeral=True)

# ------------------------------------------------------------------------------------------------------------
# ===== Gold システム（通貨） =====

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

# --- 残高操作 ---
def get_balance(user_id: int) -> int:
    return gold_data.get(str(user_id), 0)

def add_gold(user_id: int, amount: int):
    uid = str(user_id)
    gold_data[uid] = gold_data.get(uid, 0) + amount
    save_gold(gold_data)

# ===== 毎日配布（JST 00:00 に全ユーザーへ 100 GOLD）=====
@tasks.loop(time=dtime(hour=0, minute=0, tzinfo=JST))
async def daily_gold_distribution():
    count = 0
    for guild in bot.guilds:
        for member in guild.members:
            if member.bot:
                continue
            add_gold(member.id, 100)
            count += 1
    print(f"[{datetime.now(JST).strftime('%m/%d %H:%M')}] 毎日配布完了: {count}ユーザーに100 GOLD付与")

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
        return  # すでに配布済み

    count = 0
    for guild in bot.guilds:
        for member in guild.members:
            if member.bot:
                continue
            add_gold(member.id, 10000)
            count += 1

    with open(FLAG_FILE, "w", encoding="utf-8") as f:
        json.dump({"distributed": True, "count": count}, f, ensure_ascii=False, indent=4)

    print(f"初回ボーナス: 既存メンバー {count} 名に10000 GOLDを配布しました。")


# ------------------------------------------------------------------------------------------------------------
# ===== /a1_残高確認 =====
@bot.tree.command(name="a1_残高確認", description="所持GOLDを確認できます")
async def a1_check_gold(interaction: discord.Interaction):
    balance = get_balance(interaction.user.id)
    await interaction.response.send_message(
        f"あなたの所持GOLDは **{balance} GOLD** です",
        ephemeral=True
    )


# ------------------------------------------------------------------------------------------------------------
# ===== /a2_送金 =====
@bot.tree.command(name="a2_送金", description="他のユーザーにGOLDを送金します")
@app_commands.describe(
    相手="送金先ユーザー",
    金額="送金するGOLDの額"
)
async def a2_send_gold(interaction: discord.Interaction, 相手: discord.Member, 金額: int):
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

    add_gold(interaction.user.id, -金額)
    add_gold(相手.id, 金額)

    await interaction.response.send_message(
        f"{相手.display_name} に **{金額} GOLD** を送金しました",
        ephemeral=True
    )


# ------------------------------------------------------------------------------------------------------------
# ===== /a3_ショップ =====
@bot.tree.command(name="a3_ショップ", description="GOLDで商品を購入できます")
@app_commands.describe(カテゴリ="ショップカテゴリを選択")
@app_commands.choices(カテゴリ=[
    app_commands.Choice(name="装飾", value="装飾"),
    app_commands.Choice(name="称号", value="称号"),
    app_commands.Choice(name="ロール", value="ロール")
])
async def a3_shop(interaction: discord.Interaction, カテゴリ: app_commands.Choice[str]):
    balance = get_balance(interaction.user.id)
    cat = カテゴリ.value

    # ==========================
    # 装飾ショップ
    # ==========================
    if cat == "装飾":
        class DecoModal(discord.ui.Modal, title="装飾購入"):
            emoji_input = discord.ui.TextInput(
                label="好きな絵文字を入力（例：🔥、💎、カスタム絵文字も可能）",
                style=discord.TextStyle.short,
                required=True
            )

            async def on_submit(self, modal_interaction: discord.Interaction):
                uid = modal_interaction.user.id
                内容 = self.emoji_input.value.strip()
                balance = get_balance(uid)

                if not is_emoji(内容):
                    await modal_interaction.response.send_message("無効な絵文字です。", ephemeral=True)
                    return
                if balance < 1000:
                    await modal_interaction.response.send_message("GOLDが足りません。", ephemeral=True)
                    return

                old_name = modal_interaction.user.display_name
                clean = re.sub(r"^(<a?:\w+:\d+>|[\U0001F000-\U0010FFFF])+ ?", "", old_name)
                clean = re.sub(r"( ?<a?:\w+:\d+>| ?[\U0001F000-\U0010FFFF])+?$", "", clean)
                clean = re.sub(r"^\[.*?\]\s*", "", clean).strip()

                title_match = re.search(r"\[(.*?)\]", old_name)
                current_title = title_match.group(1) if title_match else None

                new_name = f"{内容} "
                if current_title:
                    new_name += f"[{current_title}] "
                new_name += f"{clean} {内容}"

                add_gold(uid, -1000)
                await modal_interaction.user.edit(nick=new_name.strip())
                await modal_interaction.response.send_message(f"装飾を変更しました！ → {new_name}", ephemeral=True)

        class DecoButton(discord.ui.Button):
            def __init__(self):
                super().__init__(label="装飾購入", style=discord.ButtonStyle.primary)

            async def callback(self, button_interaction: discord.Interaction):
                modal = DecoModal()
                await button_interaction.response.send_modal(modal)
                self.disabled = True
                await button_interaction.message.edit(view=self.view)

        view = discord.ui.View()
        view.add_item(DecoButton())

        msg = (
            f"**ようこそ！装飾ショップへ！**\n"
            "「🔥名前🔥」のようにあなたの名前を絵文字で装飾できます。\n\n"
            "**価格：1000 GOLD**\n"
            f"（あなたの所持：{balance} GOLD）"
        )
        await interaction.response.send_message(msg, view=view, ephemeral=True)

    # ==========================
    # 称号ショップ
    # ==========================
    elif cat == "称号":
        class TitleModal(discord.ui.Modal, title="称号購入"):
            title_input = discord.ui.TextInput(
                label="付けたい称号を入力（例：勇者、伝説の竜騎士 など）",
                style=discord.TextStyle.short,
                required=True
            )

            async def on_submit(self, modal_interaction: discord.Interaction):
                uid = modal_interaction.user.id
                内容 = self.title_input.value.strip()
                balance = get_balance(uid)

                if balance < 3000:
                    await modal_interaction.response.send_message("GOLDが足りません。", ephemeral=True)
                    return

                old_name = modal_interaction.user.display_name
                clean = re.sub(r"^(<a?:\w+:\d+>|[\U0001F000-\U0010FFFF])+ ?", "", old_name)
                clean = re.sub(r"( ?<a?:\w+:\d+>| ?[\U0001F000-\U0010FFFF])+?$", "", clean)
                clean = re.sub(r"^\[.*?\]\s*", "", clean).strip()

                deco_match = re.match(r"(<a?:\w+:\d+>|[\U0001F000-\U0010FFFF])", old_name)
                current_deco = deco_match.group(1) if deco_match else None

                new_name = ""
                if current_deco:
                    new_name += f"{current_deco} "
                new_name += f"[{内容}] {clean}"
                if current_deco:
                    new_name += f" {current_deco}"

                add_gold(uid, -3000)
                await modal_interaction.user.edit(nick=new_name.strip())
                await modal_interaction.response.send_message(f"称号を変更しました！ → {new_name}", ephemeral=True)

        class TitleButton(discord.ui.Button):
            def __init__(self):
                super().__init__(label="称号購入", style=discord.ButtonStyle.success)

            async def callback(self, button_interaction: discord.Interaction):
                modal = TitleModal()
                await button_interaction.response.send_modal(modal)
                self.disabled = True
                await button_interaction.message.edit(view=self.view)

        view = discord.ui.View()
        view.add_item(TitleButton())

        msg = (
            f"**ようこそ！称号ショップへ！**\n"
            "「[称号] 名前」のように称号を付けられます。\n\n"
            "**価格：3000 GOLD**\n"
            f"（あなたの所持：{balance} GOLD）"
        )
        await interaction.response.send_message(msg, view=view, ephemeral=True)

    # ==========================
    # ロールショップ
    # ==========================
    elif cat == "ロール":
        class RoleModal(discord.ui.Modal, title="ロール購入"):
            num_input = discord.ui.TextInput(
                label="購入したいロール番号を入力（1〜4）",
                style=discord.TextStyle.short,
                required=True
            )

            async def on_submit(self, modal_interaction: discord.Interaction):
                uid = modal_interaction.user.id
                balance = get_balance(uid)

                try:
                    num = int(self.num_input.value.strip())
                except ValueError:
                    await modal_interaction.response.send_message("数字を入力してください。", ephemeral=True)
                    return

                roles = {
                    1: ("🔥火属性🔥", 500),
                    2: ("💧水属性💧", 500),
                    3: ("🌪️風属性🌪️", 500),
                    4: ("🌱土属性🌱", 500)
                }

                if num not in roles:
                    await modal_interaction.response.send_message("1〜4の番号を入力してください。", ephemeral=True)
                    return

                role_name, cost = roles[num]
                if balance < cost:
                    await modal_interaction.response.send_message("GOLDが足りません。", ephemeral=True)
                    return

                add_gold(uid, -cost)
                role = discord.utils.get(modal_interaction.guild.roles, name=role_name)
                if not role:
                    role = await modal_interaction.guild.create_role(name=role_name)
                await modal_interaction.user.add_roles(role)
                await modal_interaction.response.send_message(f"{role_name} を購入しました！", ephemeral=True)

        class RoleButton(discord.ui.Button):
            def __init__(self):
                super().__init__(label="ロール購入", style=discord.ButtonStyle.primary)

            async def callback(self, button_interaction: discord.Interaction):
                modal = RoleModal()
                await button_interaction.response.send_modal(modal)
                self.disabled = True
                await button_interaction.message.edit(view=self.view)

        view = discord.ui.View()
        view.add_item(RoleButton())

        msg = (
            f"**ようこそ！ロールショップへ！**\n"
            "\n"
            "1 🔥火属性🔥　500 GOLD\n"
            "2 💧水属性💧　500 GOLD\n"
            "3 🌪️風属性🌪️　500 GOLD\n"
            "4 🌱土属性🌱　500 GOLD\n\n"
            "\n"
            f"（あなたの所持：{balance} GOLD）"
        )
        await interaction.response.send_message(msg, view=view, ephemeral=True)



# ------------------------------------------------------------------------------------------------------------
# ===== /a4_リセット（装飾 / 称号 / ロール） =====
@bot.tree.command(name="a4_リセット", description="購入した装飾・称号・ロールを削除します")
@app_commands.describe(種類="リセットする項目を選択")
@app_commands.choices(種類=[
    app_commands.Choice(name="装飾リセット", value="装飾"),
    app_commands.Choice(name="称号リセット", value="称号"),
    app_commands.Choice(name="ロールリセット", value="ロール"),
])
async def a4_reset_items(interaction: discord.Interaction, 種類: app_commands.Choice[str]):
    choice = 種類.value
    user = interaction.user
    old_name = user.display_name
    new_name = old_name

    # 装飾リセット
    if choice == "装飾":
        new_name = re.sub(r"^(<a?:\w+:\d+>|[\U0001F000-\U0010FFFF])+ ?", "", new_name)
        new_name = re.sub(r"( ?<a?:\w+:\d+>| ?[\U0001F000-\U0010FFFF])+?$", "", new_name)
        new_name = new_name.strip()
        try:
            await user.edit(nick=new_name)
            await interaction.response.send_message(f"装飾をリセットしました → `{new_name}`", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("ニックネームを変更する権限がありません。", ephemeral=True)
        return

    # 称号リセット
    if choice == "称号":
        new_name = re.sub(r"^\[.*?\]\s*", "", new_name).strip()
        try:
            await user.edit(nick=new_name)
            await interaction.response.send_message(f"称号をリセットしました → `{new_name}`", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("ニックネームを変更する権限がありません。", ephemeral=True)
        return

    # ロールリセット
    if choice == "ロール":
        removed_roles = []
        role_names = ["🔥火属性🔥", "💧水属性💧", "🌪️風属性🌪️", "🌱土属性🌱"]
        for name in role_names:
            role = discord.utils.get(interaction.guild.roles, name=name)
            if role and role in user.roles:
                try:
                    await user.remove_roles(role)
                    removed_roles.append(name)
                except discord.Forbidden:
                    pass

        if removed_roles:
            await interaction.response.send_message(f"ロールをリセットしました：{', '.join(removed_roles)}", ephemeral=True)
        else:
            await interaction.response.send_message("リセット対象のロールが見つかりませんでした。", ephemeral=True)
        return


# ------------------------------------------------------------------------------------------------------------
# ===== リマインド =====
@bot.tree.command(name="c1_リマインド", description="指定した時間または日付＋時間にリマインドを送ります（日本時間）")
@app_commands.describe(時間または分後="「21:30」「11/03 21:30」または「15」など", メッセージ="リマインド内容")
async def c1_remind(interaction: discord.Interaction, 時間または分後: str, メッセージ: str):
    await interaction.response.defer(ephemeral=True)
    now = datetime.now(JST)

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
    await interaction.followup.send(
        f"リマインドを設定しました：{remind_time.strftime('%m/%d %H:%M')}\n> {メッセージ}",
        view=view,
        ephemeral=True
    )


# ------------------------------------------------------------------------------------------------------------
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
