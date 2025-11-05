# =========================================================
# Discord Bot 総合システム
# =========================================================
# 対応機能：
# 1. Communication Level（VC＋チャット）ロール付与
# 2. 既存ユーザーへ初回10000GOLD
# 3. 新規加入ユーザーへ10000GOLD
# 4. 毎日全ユーザーへ100GOLD
# 5. チャット・VC滞在でGOLD付与
# 6. リアクションロール
# 7. 問い合わせチャンネル自動生成
# 8. ピン留め・削除
# 9. X投稿自動引用・停止
# 10. 残高確認・送金・ショップ
# 11. リマインド
# =========================================================

import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio, json, os, re, time
from datetime import datetime, timedelta, timezone
from datetime import time as dtime
import feedparser
from keep_alive import keep_alive
import random



# ---------------------------------------------------------
# 基本設定
# ---------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.reactions = True
bot = commands.Bot(command_prefix="!", intents=intents)
JST = timezone(timedelta(hours=9))

# ---------------------------------------------------------
# データファイル定義
# ---------------------------------------------------------
DATA_FILE = "cl_data.json"
FEEDS_FILE = "feeds.json"
TEMPLATE_FILE = "auto_templates.json"
REACTION_FILE = "reaction_roles.json"
GOLD_FILE = "gold_data.json"

# ---------------------------------------------------------
# グローバル変数
# ---------------------------------------------------------
cl_data = {"users": {}, "enabled": False}
voice_sessions = {}
tracking_feeds = {}
auto_templates = {}
last_template_messages = {}
reaction_role_data = {}
gold_data = {}
reminders = {}

# ---------------------------------------------------------
# ファイル読み書き関数
# ---------------------------------------------------------
def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ {path} 読み込み失敗: {e}")
    return default

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"⚠️ {path} 保存失敗: {e}")

# ---------------------------------------------------------
# データロード関数
# ---------------------------------------------------------
def load_all_data():
    global cl_data, tracking_feeds, auto_templates, reaction_role_data, gold_data
    cl_data = load_json(DATA_FILE, {"users": {}, "enabled": False})
    tracking_feeds = load_json(FEEDS_FILE, {})
    auto_templates = load_json(TEMPLATE_FILE, {})
    reaction_role_data = load_json(REACTION_FILE, {})
    gold_data = load_json(GOLD_FILE, {})

def save_cl_data(): save_json(DATA_FILE, cl_data)
def save_feeds(): save_json(FEEDS_FILE, tracking_feeds)
def save_templates(): save_json(TEMPLATE_FILE, auto_templates)
def save_reaction_roles(): save_json(REACTION_FILE, reaction_role_data)
def save_gold(): save_json(GOLD_FILE, gold_data)

# ---------------------------------------------------------
# 絵文字判定関数
# ---------------------------------------------------------
def is_emoji(s: str) -> bool:
    """UnicodeまたはDiscordカスタム絵文字か判定"""
    if re.fullmatch(r"<a?:\w+:\d+>", s):
        return True
    emoji_pattern = re.compile(r"(<a?:\w+:\d+>|[\U00010000-\U0010FFFF])", flags=re.UNICODE)
    return bool(emoji_pattern.fullmatch(s))

# ---------------------------------------------------------
# GOLDシステム
# ---------------------------------------------------------
def get_balance(user_id: int) -> int:
    return gold_data.get(str(user_id), 0)

def add_gold(user_id: int, amount: int):
    uid = str(user_id)
    gold_data[uid] = gold_data.get(uid, 0) + amount
    save_gold()

#毎日00:00に全ユーザーへ100G配布
@tasks.loop(time=dtime(hour=0, minute=0, tzinfo=JST))
async def daily_gold_distribution():
    count = 0
    for guild in bot.guilds:
        for member in guild.members:
            if not member.bot:
                add_gold(member.id, 100)
                count += 1
    print(f"[{datetime.now(JST).strftime('%m/%d %H:%M')}] 毎日配布完了: {count}ユーザーに100G付与")

#新規メンバーに10000G付与
@bot.event
async def on_member_join(member: discord.Member):
    if member.bot:
        return
    add_gold(member.id, 10000)
    print(f"[JOIN] {member.display_name} に10000Gを付与しました。")

#初回起動時のみ既存全メンバーへ10000G付与
async def distribute_initial_gold():
    FLAG_FILE = "initial_gold_flag.json"
    if os.path.exists(FLAG_FILE):
        return
    count = 0
    for guild in bot.guilds:
        for member in guild.members:
            if not member.bot:
                add_gold(member.id, 10000)
                count += 1
    save_json(FLAG_FILE, {"distributed": True, "count": count})
    print(f"初回ボーナス: 既存メンバー {count} 名に10000Gを配布しました。")


# ---------------------------------------------------------
# Communication Level 機能
# ---------------------------------------------------------
CL_LEVELS = [
    {"name": "Communication Level 1", "text": 10, "vc": 30, "color": 0x999999},
    {"name": "Communication Level 2", "text": 50, "vc": 180, "color": 0x55ff55},
    {"name": "Communication Level 3", "text": 100, "vc": 720, "color": 0x3333ff},
    {"name": "Communication Level 4", "text": 333, "vc": 1440, "color": 0x8800ff},
    {"name": "Communication Level 5", "text": 666, "vc": 7200, "color": 0xffff00},
    {"name": "Communication Level 6", "text": 1000, "vc": 14400, "color": 0xff5555},
]

# --- チャット記録 ---
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    #Communication Level 記録
    if cl_data.get("enabled"):
        uid = str(message.author.id)
        if uid not in cl_data["users"]:
            cl_data["users"][uid] = {"text": 0, "vc": 0}
        cl_data["users"][uid]["text"] += len(message.content)
        save_cl_data()
        await check_and_assign_roles(message.author)

    await bot.process_commands(message)

# --- VC滞在時間 ---
@bot.event
async def on_voice_state_update(member, before, after):
    if not cl_data.get("enabled"):
        return
    uid = str(member.id)

    # 入室時
    if before.channel is None and after.channel is not None:
        voice_sessions[uid] = time.time()

    # 退出／移動時
    elif before.channel is not None and after.channel != before.channel:
        if uid in voice_sessions:
            duration = int((time.time() - voice_sessions[uid]) / 60)
            del voice_sessions[uid]
            cl_data["users"].setdefault(uid, {"text": 0, "vc": 0})
            cl_data["users"][uid]["vc"] += duration
            save_cl_data()

            # GOLD報酬
            if duration > 0:
                add_gold(member.id, duration * 5)

            await check_and_assign_roles(member)

# --- ロール判定 ---
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

    role = discord.utils.get(guild.roles, name=achieved)
    if not role:
        role = await guild.create_role(name=achieved, color=discord.Color(color))

    if role not in member.roles:
        await member.add_roles(role)

    for lvl in CL_LEVELS:
        if lvl["name"] != achieved:
            r = discord.utils.get(guild.roles, name=lvl["name"])
            if r in member.roles:
                await member.remove_roles(r)

# --- ON/OFF切替 ---
@bot.tree.command(name="z1_cl_on", description="Communication Level機能をONにします【管理者のみ】")
@app_commands.default_permissions(administrator=True)
async def z1_cl_on(interaction: discord.Interaction):
    cl_data["enabled"] = True
    save_cl_data()
    await interaction.response.send_message("Communication Level機能をONにしました。", ephemeral=True)

@bot.tree.command(name="z2_cl_off", description="Communication Level機能をOFFにします【管理者のみ】")
@app_commands.default_permissions(administrator=True)
async def z2_cl_off(interaction: discord.Interaction):
    cl_data["enabled"] = False
    save_cl_data()
    await interaction.response.send_message("Communication Level機能をOFFにしました。", ephemeral=True)


# ---------------------------------------------------------
# リアクションロール機能
# ---------------------------------------------------------
@bot.tree.command(
    name="x1_リアクションロール設定",
    description="リアクションでロールを付与するメッセージを作成します【管理者のみ】"
)
@app_commands.describe(
    絵文字とロール="『絵文字:ロール名』をカンマ区切りで指定（例：1️⃣:猫,2️⃣:犬,3️⃣:鳥）",
    複数選択="Trueで複数選択を許可、Falseで一人一つのみ"
)
@app_commands.default_permissions(manage_roles=True)
async def reaction_role_setup(
    interaction: discord.Interaction,
    絵文字とロール: str,
    複数選択: bool = True
):
    # ✅ deferしない（モーダル表示をブロックしてしまうため）
    pairs = [x.strip() for x in re.split("[,、]", 絵文字とロール) if x.strip()]
    emoji_role_pairs = []

    # --- 絵文字とロールの検証 ---
    for p in pairs:
        if ":" not in p:
            await interaction.response.send_message(f"形式が不正です: {p}", ephemeral=True)
            return
        emoji, role_name = p.split(":", 1)
        role_name = role_name.strip()

        # ロール確認・なければ作成
        role = discord.utils.get(interaction.guild.roles, name=role_name)
        if not role:
            try:
                role = await interaction.guild.create_role(name=role_name)
                print(f"ロール自動生成: {role_name}")
            except discord.Forbidden:
                await interaction.response.send_message(f"ロール {role_name} を作成できません（権限不足）", ephemeral=True)
                return

        emoji_role_pairs.append((emoji.strip(), role))

    # --- モーダルでメッセージ内容を入力 ---
    class ReactionMessageModal(discord.ui.Modal, title="リアクションロールメッセージ入力"):
        message_input = discord.ui.TextInput(
            label="メッセージ本文",
            style=discord.TextStyle.paragraph,
            required=True
        )

        async def on_submit(self, modal_interaction: discord.Interaction):
            content = self.message_input.value.strip()

            # メッセージ送信
            msg = await modal_interaction.channel.send(content)
            for emoji, _ in emoji_role_pairs:
                try:
                    await msg.add_reaction(emoji)
                except discord.HTTPException:
                    print(f"絵文字追加失敗: {emoji}")

            # 設定保存
            reaction_role_data[str(msg.id)] = {
                "roles": {emoji: role.id for emoji, role in emoji_role_pairs},
                "exclusive": not 複数選択,
                "guild_id": interaction.guild.id,
            }
            save_reaction_roles()

            await modal_interaction.response.send_message(
                f"リアクションロール設定が完了しました！\n"
                f"メッセージID: `{msg.id}`\n"
                f"排他モード: {'ON(一人一つのみ)' if not 複数選択 else 'OFF(複数選択可)'}",
                ephemeral=True
            )

    await interaction.response.send_modal(ReactionMessageModal())


# ---------------------------------------------------------
# 問い合わせチャンネル作成コマンド
# ---------------------------------------------------------
@bot.tree.command(name="x2_問い合わせ設定", description="問い合わせボタンを設置します【管理者のみ】")
@app_commands.describe(
    対応ロール="問い合わせ対応ロールを選択してください",
    ボタン名="ボタン名をカンマ区切りで指定（例：質問,要望,申請など）"
)
@app_commands.default_permissions(administrator=True)
async def inquiry_setup(interaction: discord.Interaction, 対応ロール: discord.Role, ボタン名: str):
    # --- ボタン名 ---
    labels = [x.strip() for x in re.split("[,、]", ボタン名) if x.strip()]
    if not labels:
        await interaction.response.send_message("ボタン名が指定されていません。", ephemeral=True)
        return

    # --- メッセージ入力モーダル ---
    class InquiryMessageModal(discord.ui.Modal, title="問い合わせメッセージ入力"):
        message_input = discord.ui.TextInput(
            label="メッセージ本文",
            style=discord.TextStyle.paragraph,
            required=True
        )

        async def on_submit(self, modal_interaction: discord.Interaction):
            view = InquiryButtonView(対応ロール, labels, self.message_input.value)
            await modal_interaction.channel.send(self.message_input.value, view=view)
            await modal_interaction.response.send_message("問い合わせボタンを設置しました。", ephemeral=True)

    await interaction.response.send_modal(InquiryMessageModal())


# ---------------------------------------------------------
# 問い合わせボタンビュー
# ---------------------------------------------------------
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

        new_channel = await guild.create_text_channel(name=channel_name, category=category, overwrites=overwrites)
        view = DeleteChannelButton()
        await new_channel.send(
            f"{user.mention} さんの『{self.label}』チャンネルが作成されました。\n"
            "問い合わせをやめる場合は「チャンネルを削除する」を押してください。",
            view=view
        )


class DeleteChannelButton(discord.ui.View):
    @discord.ui.button(label="チャンネルを削除する", style=discord.ButtonStyle.danger)
    async def delete_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("数秒後にチャンネルを自動削除します", ephemeral=True)
        await asyncio.sleep(5)
        await interaction.channel.delete(reason="問い合わせ完了により削除")


# ---------------------------------------------------------
# ピン留め機能
# ---------------------------------------------------------
@bot.tree.command(name="x3_ピン留め設定", description="このチャンネルにピン留めを設定します【管理者のみ】")
@app_commands.describe(メッセージ="ピン留め内容")
@app_commands.default_permissions(administrator=True)
async def pin_set(interaction: discord.Interaction, メッセージ: str):
    channel_id = str(interaction.channel.id)
    auto_templates[channel_id] = メッセージ
    save_templates()
    await interaction.response.send_message("このチャンネルにピン留めを設定しました。", ephemeral=True)


@bot.tree.command(name="x4_ピン留め停止", description="このチャンネルのピン留めを停止します【管理者のみ】")
@app_commands.default_permissions(administrator=True)
async def pin_stop(interaction: discord.Interaction):
    channel_id = str(interaction.channel.id)
    if channel_id in auto_templates:
        del auto_templates[channel_id]
        save_templates()
        await interaction.response.send_message("このチャンネルのピン留めを停止しました。", ephemeral=True)
    else:
        await interaction.response.send_message("このチャンネルにはピン留めが設定されていません。", ephemeral=True)


# on_message のピン留め処理
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    channel_id = str(message.channel.id)

    # チャット報酬
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
        uid = str(message.author.id)
        if uid not in cl_data["users"]:
            cl_data["users"][uid] = {"text": 0, "vc": 0}
        cl_data["users"][uid]["text"] += len(message.content)
        save_cl_data()
        await check_and_assign_roles(message.author)

    await bot.process_commands(message)


# ---------------------------------------------------------
# Xポスト引用機能
# ---------------------------------------------------------
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


@bot.tree.command(name="x5_xポスト引用", description="指定アカウントの新規ポスト・引用を自動で貼ります【管理者のみ】")
@app_commands.describe(アカウント名="例：elonmusk")
@app_commands.default_permissions(administrator=True)
async def x_post(interaction: discord.Interaction, アカウント名: str):
    rss_url = f"https://nitter.net/{アカウント名}/rss"
    tracking_feeds[str(interaction.channel.id)] = {"rss": rss_url, "latest": None}
    save_feeds()
    if not check_feeds.is_running():
        check_feeds.start()
    await interaction.response.send_message(f"@{アカウント名} の投稿監視を開始しました。", ephemeral=True)


@bot.tree.command(name="x6_xポスト停止", description="このチャンネルでのXポスト監視を停止します【管理者のみ】")
@app_commands.default_permissions(administrator=True)
async def x_post_stop(interaction: discord.Interaction):
    cid = str(interaction.channel.id)
    if cid in tracking_feeds:
        del tracking_feeds[cid]
        save_feeds()
        await interaction.response.send_message("このチャンネルでのXポスト監視を停止しました。", ephemeral=True)
    else:
        await interaction.response.send_message("このチャンネルでは監視が有効ではありません。", ephemeral=True)


# ---------------------------------------------------------
# GOLD関連コマンド
# ---------------------------------------------------------
@bot.tree.command(name="a1_残高確認", description="所持GOLDを確認できます")
async def a1_check_gold(interaction: discord.Interaction):
    balance = get_balance(interaction.user.id)
    await interaction.response.send_message(f"あなたの所持GOLDは **{balance} GOLD** です", ephemeral=True)


@bot.tree.command(name="a2_送金", description="他のユーザーにGOLDを送金します")
@app_commands.describe(相手="送金先ユーザー", 金額="送金するGOLDの額")
async def a2_send_gold(interaction: discord.Interaction, 相手: discord.Member, 金額: int):
    sender_balance = get_balance(interaction.user.id)
    if 金額 <= 0:
        await interaction.response.send_message("送金額は1以上で指定してください。", ephemeral=True)
        return
    if sender_balance < 金額:
        await interaction.response.send_message("所持GOLDが足りません。", ephemeral=True)
        return
    if interaction.user.id == 相手.id:
        await interaction.response.send_message("自分自身には送金できません。", ephemeral=True)
        return

    add_gold(interaction.user.id, -金額)
    add_gold(相手.id, 金額)
    await interaction.response.send_message(f"{相手.display_name} に **{金額} GOLD** を送金しました。", ephemeral=True)


# ---------------------------------------------------------
# ショップ機能（装飾・称号・ロール）
# ---------------------------------------------------------
@bot.tree.command(name="a3_ショップ", description="任意の装飾、称号、ロールをつけられます　※PCのみ")
@app_commands.describe(カテゴリ="ショップカテゴリを選択")
@app_commands.choices(カテゴリ=[
    app_commands.Choice(name="装飾", value="装飾"),
    app_commands.Choice(name="称号", value="称号"),
    app_commands.Choice(name="ロール", value="ロール")
])
async def a3_shop(interaction: discord.Interaction, カテゴリ: app_commands.Choice[str]):
    balance = get_balance(interaction.user.id)
    cat = カテゴリ.value

    # ======================
    # 装飾ショップ
    # ======================
    if cat == "装飾":
        class DecoModal(discord.ui.Modal, title="装飾入力"):
            emoji_input = discord.ui.TextInput(
                label="好きな絵文字を入力（例：🔥、💎、カスタム絵文字も可）",
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

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="装飾入力", style=discord.ButtonStyle.primary, custom_id="deco_button"))

        async def button_callback(interaction_button: discord.Interaction):
            modal = DecoModal()
            await interaction_button.response.send_modal(modal)

        for child in view.children:
            if isinstance(child, discord.ui.Button) and child.custom_id == "deco_button":
                child.callback = button_callback

        msg = (
            f"**ようこそ！装飾ショップへ！**\n"
            "「🔥名前🔥」のように名前を絵文字で装飾できます！\n"
            "\n"
            "**価格：1000 GOLD**\n"
            f"（あなたの所持：{balance} GOLD）"
        )
        await interaction.response.send_message(msg, view=view, ephemeral=True)

    # ======================
    # 称号ショップ
    # ======================
    elif cat == "称号":
        class TitleModal(discord.ui.Modal, title="称号入力"):
            title_input = discord.ui.TextInput(
                label="付けたい称号を入力（例：勇者、破壊神など）",
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

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="称号入力", style=discord.ButtonStyle.primary, custom_id="title_button"))

        async def button_callback(interaction_button: discord.Interaction):
            modal = TitleModal()
            await interaction_button.response.send_modal(modal)

        for child in view.children:
            if isinstance(child, discord.ui.Button) and child.custom_id == "title_button":
                child.callback = button_callback

        msg = (
            f"**ようこそ！称号ショップへ！**\n"
            "「[称号] 名前」のように称号を付けられます！\n"
            "\n"
            "**価格：3000 GOLD**\n"
            f"（あなたの所持：{balance} GOLD）"
        )
        await interaction.response.send_message(msg, view=view, ephemeral=True)

    # ======================
    # ロールショップ
    # ======================
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

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="ロール購入", style=discord.ButtonStyle.primary, custom_id="role_button"))

        async def button_callback(interaction_button: discord.Interaction):
            modal = RoleModal()
            await interaction_button.response.send_modal(modal)

        for child in view.children:
            if isinstance(child, discord.ui.Button) and child.custom_id == "role_button":
                child.callback = button_callback

        msg = (
            f"**ようこそ！ロールショップへ！**\n"
            "1 🔥火属性🔥　500 GOLD\n"
            "2 💧水属性💧　500 GOLD\n"
            "3 🌪️風属性🌪️　500 GOLD\n"
            "4 🌱土属性🌱　500 GOLD\n"
            f"\n（あなたの所持：{balance} GOLD）"
        )
        await interaction.response.send_message(msg, view=view, ephemeral=True)


# ---------------------------------------------------------
# リセット機能（装飾／称号／ロール）
# ---------------------------------------------------------
@bot.tree.command(name="a4_リセット", description="付与した装飾・称号・ロールを削除します")
@app_commands.describe(種類="リセットする項目を選択")
@app_commands.choices(種類=[
    app_commands.Choice(name="装飾リセット", value="装飾"),
    app_commands.Choice(name="称号リセット", value="称号"),
    app_commands.Choice(name="ロールリセット", value="ロール")
])
async def a4_reset(interaction: discord.Interaction, 種類: app_commands.Choice[str]):
    user = interaction.user
    old_name = user.display_name
    new_name = old_name

    # --- 装飾 ---
    if 種類.value == "装飾":
        new_name = re.sub(r"^(<a?:\w+:\d+>|[\U0001F000-\U0010FFFF])+ ?", "", new_name)
        new_name = re.sub(r"( ?<a?:\w+:\d+>| ?[\U0001F000-\U0010FFFF])+?$", "", new_name).strip()
        await user.edit(nick=new_name)
        await interaction.response.send_message(f"装飾を削除しました → `{new_name}`", ephemeral=True)
        return

    # --- 称号 ---
    if 種類.value == "称号":
        new_name = re.sub(r"^\[.*?\]\s*", "", new_name).strip()
        await user.edit(nick=new_name)
        await interaction.response.send_message(f"称号を削除しました → `{new_name}`", ephemeral=True)
        return

    # --- ロール ---
    if 種類.value == "ロール":
        role_names = ["🔥火属性🔥", "💧水属性💧", "🌪️風属性🌪️", "🌱土属性🌱"]
        removed = []
        for rname in role_names:
            role = discord.utils.get(interaction.guild.roles, name=rname)
            if role and role in user.roles:
                await user.remove_roles(role)
                removed.append(rname)
        if removed:
            await interaction.response.send_message(f"ロールを削除しました：{', '.join(removed)}", ephemeral=True)
        else:
            await interaction.response.send_message("削除対象のロールがありません。", ephemeral=True)


# ---------------------------------------------------------
# リマインドコマンド
# ---------------------------------------------------------
# ---------------------------------------------------------
# リマインド永続化設定
# ---------------------------------------------------------
REMINDERS_FILE = "reminders.json"
reminders = {}

def load_reminders():
    if os.path.exists(REMINDERS_FILE):
        try:
            with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"リマインド読み込み失敗: {e}")
    return {}

def save_reminders():
    try:
        with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
            json.dump(reminders, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"リマインド保存失敗: {e}")


async def restore_reminders():
    """Bot起動時に未完了のリマインドを復元"""
    global reminders
    reminders = load_reminders()
    now = datetime.now(JST)
    restored = 0

    for rid, data in list(reminders.items()):
        remind_time = datetime.fromisoformat(data["time"])
        wait_seconds = (remind_time - now).total_seconds()
        if wait_seconds <= 0:
            del reminders[rid]
            continue

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
                        avatar_url=user.display_avatar.url if user.display_avatar else None,
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
        print(f"🔁 復元したリマインド数: {restored}")
    save_reminders()


# ---------------------------------------------------------
# おみくじ機能
# ---------------------------------------------------------
@bot.tree.command(name="b1_おみくじ", description="おみくじを引きます")
async def omikuji(interaction: discord.Interaction):
    # 確率設定
    fixed = {
        "大大大吉": 0.01,
        "大大吉": 0.03,
        "鬼がかり 3000 BONUS": 0.01
    }
    others = ["大吉", "吉", "中吉", "小吉", "末吉", "凶", "大凶"]
    rest = 1.0 - sum(fixed.values())
    each = rest / len(others)
    weights = {**fixed, **{o: each for o in others}}

    result = random.choices(list(weights.keys()), weights=list(weights.values()), k=1)[0]

    # Embed作成（安定表示）
    embed = discord.Embed(
        title="🎴 おみくじの結果 🎴",
        color=discord.Color.gold()
    )

    # --- 特別結果：鬼がかり ---
    if result == "鬼がかり 3000 BONUS":
        add_gold(interaction.user.id, 3000)
        embed.description = (
            "# 💥 ﾎﾟｷｭｰｰﾝ!!\n"
            "## ✨ **鬼がかり 3000 BONUS** ✨\n"
            "### **3000GOLD GET!!!!!**"
        )
        embed.color = discord.Color.from_str("#FFD700")  # 金色

    # --- 通常結果 ---
    else:
        embed.description = f"# {result}"

    embed.set_footer(text=f"{interaction.user.display_name} さんの運勢", icon_url=interaction.user.display_avatar.url)

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------
# リマインドコマンド
# ---------------------------------------------------------
@bot.tree.command(name="c1_リマインド", description="指定した時間または日付＋時間にリマインドを送ります(日本時間)")
@app_commands.describe(
    時間または分後="「11/01 21:30」「21:30」または「15」(分後)など"
)
async def c1_remind(interaction: discord.Interaction, 時間または分後: str):
    await interaction.response.defer(ephemeral=True)
    now = datetime.now(JST)

    # --- 「○分後」指定 ---
    if re.fullmatch(r"\d+", 時間または分後):
        minutes = int(時間または分後)
        remind_time = now + timedelta(minutes=minutes)
        wait_seconds = minutes * 60

    # --- 「時刻指定 HH:MM」 ---
    elif re.fullmatch(r"\d{1,2}:\d{2}", 時間または分後):
        target = datetime.strptime(時間または分後, "%H:%M").replace(
            year=now.year, month=now.month, day=now.day, tzinfo=JST
        )
        if target < now:
            target += timedelta(days=1)
        remind_time = target
        wait_seconds = (remind_time - now).total_seconds()

    # --- 「月日＋時刻指定 MM/DD HH:MM」 ---
    elif re.fullmatch(r"\d{1,2}/\d{1,2} \d{1,2}:\d{2}", 時間または分後):
        target = datetime.strptime(時間または分後, "%m/%d %H:%M").replace(
            year=now.year, tzinfo=JST
        )
        if target < now:
            target = target.replace(year=now.year + 1)
        remind_time = target
        wait_seconds = (remind_time - now).total_seconds()

    else:
        await interaction.followup.send("時間形式が無効です。", ephemeral=True)
        return

    remind_id = f"{interaction.user.id}-{remind_time.strftime('%Y%m%d%H%M%S')}"

    # --- メッセージ入力モーダル ---
    class ReminderMessageModal(discord.ui.Modal, title="リマインド内容入力"):
        message_input = discord.ui.TextInput(
            label="リマインドメッセージ（改行可：Shift+Enter）",
            style=discord.TextStyle.paragraph,
            required=True
        )

        async def on_submit(self, modal_interaction: discord.Interaction):
            メッセージ = self.message_input.value.strip()

            async def remind_task():
                try:
                    await asyncio.sleep(wait_seconds)
                    webhook = await modal_interaction.channel.create_webhook(name=interaction.user.display_name)
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
                    save_reminders()

            task = asyncio.create_task(remind_task())
            reminders[remind_id] = {
                "task": task,
                "time": remind_time.isoformat(),
                "message": メッセージ,
                "user_id": modal_interaction.user.id,
                "channel_id": modal_interaction.channel.id
            }
            save_reminders()

            # --- 削除ボタン付きビュー ---
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
                        save_reminders()
                        await interaction2.response.edit_message(content="リマインドを削除しました。", view=None)
                    else:
                        await interaction2.response.send_message("このリマインドはすでに削除されています。", ephemeral=True)

            view = CancelButton(interaction.user.id, remind_id)
            await modal_interaction.response.send_message(
                f"リマインドを設定しました：{remind_time.strftime('%m/%d %H:%M')}\n> {メッセージ}",
                view=view,
                ephemeral=True
            )

    await interaction.followup.send_modal(ReminderMessageModal())


# ---------------------------------------------------------
# 起動イベント
# ---------------------------------------------------------
@bot.event
async def on_ready():
    load_all_data()

    # 🔹 リアクションロール設定ロード
    global reaction_role_data
    if os.path.exists(REACTION_FILE):
        try:
            with open(REACTION_FILE, "r", encoding="utf-8") as f:
                reaction_role_data = json.load(f)
            print(f"リアクションロール設定を {len(reaction_role_data)} 件ロードしました。")
        except Exception as e:
            print(f"リアクションロールデータの読み込み失敗: {e}")
            reaction_role_data = {}

    # 🔹 コマンド同期
    await bot.tree.sync()
    print(f"ログイン完了: {bot.user}")
    print(f"Communication Level: {'ON' if cl_data['enabled'] else 'OFF'}")

    # 🔹 定期タスク起動
    if not check_feeds.is_running():
        check_feeds.start()
    if not daily_gold_distribution.is_running():
        daily_gold_distribution.start()

    # 🔹 初回ボーナス配布
    await distribute_initial_gold()

    # 🔹 リマインド復元
    await restore_reminders()
    print("🕓 リマインド復元完了")

# ---------------------------------------------------------
# 常時稼働（Render対応）
# ---------------------------------------------------------
keep_alive()
bot.run(os.getenv("DISCORD_TOKEN"))
