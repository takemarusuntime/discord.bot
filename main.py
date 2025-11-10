import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
import json
import os
import re
import time
import random
import feedparser

from datetime import datetime, timedelta, timezone
from datetime import time as dtime

from keep_alive import keep_alive


# =========================================================
# 基本設定
# =========================================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)
JST = timezone(timedelta(hours=9))


# =========================================================
# データファイル
# =========================================================
DATA_FILE = "cl_data.json"
FEEDS_FILE = "feeds.json"
TEMPLATE_FILE = "auto_templates.json"
REACTION_FILE = "reaction_roles.json"
GOLD_FILE = "gold_data.json"
REMINDERS_FILE = "reminders.json"
FLAG_FILE = "initial_gold_flag.json"


# =========================================================
# グローバル変数
# =========================================================
cl_data = {"users": {}, "enabled": False}
voice_sessions = {}
tracking_feeds = {}
auto_templates = {}
reaction_role_data = {}
gold_data = {}
reminders = {}


# =========================================================
# JSON 読み書き
# =========================================================
def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"JSON Load Error ({path}): {e}")
    return default


def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"JSON Save Error ({path}): {e}")


# =========================================================
# データロード
# =========================================================
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
def save_reminders(): save_json(REMINDERS_FILE, reminders)


# =========================================================
# GOLD 基本関数
# =========================================================
def get_balance(user_id: int) -> int:
    return gold_data.get(str(user_id), 0)


def add_gold(user_id: int, amount: int):
    uid = str(user_id)
    gold_data[uid] = gold_data.get(uid, 0) + amount
    save_gold()

# =========================================================
# 初回 10000G（1回のみ）
# =========================================================
async def distribute_initial_gold():
    if os.path.exists(FLAG_FILE):
        return

    count = 0
    for guild in bot.guilds:
        for member in guild.members:
            if not member.bot:
                add_gold(member.id, 10000)
                count += 1

    save_json(FLAG_FILE, {"distributed": True, "count": count})
    print(f"Initial GOLD distributed to {count} users")


# =========================================================
# 新規参加ユーザーに 10000G
# =========================================================
@bot.event
async def on_member_join(member: discord.Member):
    if member.bot:
        return

    uid = str(member.id)
    if uid not in gold_data:
        add_gold(member.id, 10000)
        print(f"Join Bonus: {member.display_name} received 10000G")


# =========================================================
# 毎日 00:00 に全員へ 1000G
# =========================================================
@tasks.loop(time=dtime(hour=0, minute=0, tzinfo=JST))
async def daily_gold_distribution():
    count = 0
    for guild in bot.guilds:
        for member in guild.members:
            if not member.bot:
                add_gold(member.id, 1000)
                count += 1

    print(f"Daily GOLD: {count} users received 1000G")


# =========================================================
# チャット文字数 2文字 = 10G
# =========================================================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    try:
        gain = (len(message.content) // 2) * 10
        if gain > 0:
            add_gold(message.author.id, gain)
    except Exception as e:
        print(f"Chat Reward Error: {e}")

    # CL（Communication Level）記録
    if cl_data.get("enabled"):
        uid = str(message.author.id)
        cl_data["users"].setdefault(uid, {"text": 0, "vc": 0})
        cl_data["users"][uid]["text"] += len(message.content)
        save_cl_data()
        await check_and_assign_roles(message.author)

    await bot.process_commands(message)


# =========================================================
# VC 滞在1分 = 10G
# =========================================================
@bot.event
async def on_voice_state_update(member, before, after):
    uid = str(member.id)

    # 入室
    if before.channel is None and after.channel is not None:
        voice_sessions[uid] = time.time()

    # 退出 or 移動
    elif before.channel is not None and after.channel != before.channel:
        if uid in voice_sessions:
            duration = int((time.time() - voice_sessions[uid]) / 60)
            del voice_sessions[uid]

            if duration > 0:
                add_gold(member.id, duration * 10)

            # CL 記録
            if cl_data.get("enabled"):
                cl_data["users"].setdefault(uid, {"text": 0, "vc": 0})
                cl_data["users"][uid]["vc"] += duration
                save_cl_data()
                await check_and_assign_roles(member)


# =========================================================
# リアクション1回 = 100G（1分クールダウン）
# =========================================================
reaction_cooldown = {}

@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return

    uid = str(user.id)
    now = time.time()

    if uid in reaction_cooldown and now < reaction_cooldown[uid]:
        return

    reaction_cooldown[uid] = now + 60
    add_gold(user.id, 100)

# ---------------------------------------------------------
# ✅ /リマインドコマンド（入口）  ← 入口の引数名を英字に変更
# ---------------------------------------------------------
@bot.tree.command(
    name="a2_remind",
    description="指定した時間または日付＋時間にリマインドを送ります（日本時間）",
)
@app_commands.describe(
    time_or_minutes="例：15（分後） / 21:30 / 11/01 21:30"
)
async def remind_command(interaction: discord.Interaction, time_or_minutes: str):

    await interaction.response.defer(ephemeral=True)
    now = datetime.now(JST)

    # ---- 入力形式解析（分後 / 時刻 / 日付+時刻）----
    if re.fullmatch(r"\d+", time_or_minutes):  # 「15」→ 分後
        minutes = int(time_or_minutes)
        remind_time = now + timedelta(minutes=minutes)
        wait_seconds = minutes * 60

    elif re.fullmatch(r"\d{1,2}:\d{2}", time_or_minutes):  # 「21:30」
        target = datetime.strptime(time_or_minutes, "%H:%M").replace(
            year=now.year, month=now.month, day=now.day, tzinfo=JST
        )
        if target < now:
            target += timedelta(days=1)
        remind_time = target
        wait_seconds = (remind_time - now).total_seconds()

    elif re.fullmatch(r"\d{1,2}/\d{1,2} \d{1,2}:\d{2}", time_or_minutes):  # 「11/01 21:30」
        target = datetime.strptime(time_or_minutes, "%m/%d %H:%M").replace(
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

    class ReminderMessageModal(discord.ui.Modal, title="リマインド内容入力"):
        message_input = discord.ui.TextInput(
            label="リマインド内容（改行可：Shift+Enter）",
            style=discord.TextStyle.paragraph,
            required=True
        )

        async def on_submit(self, modal_interaction: discord.Interaction):
            message_text = self.message_input.value.strip()

            async def remind_task():
                try:
                    await asyncio.sleep(wait_seconds)
                    webhook = await modal_interaction.channel.create_webhook(
                        name=interaction.user.display_name
                    )
                    await webhook.send(
                        message_text,
                        username=interaction.user.display_name,
                        avatar_url=(interaction.user.display_avatar.url
                                    if interaction.user.display_avatar else None)
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
                "message": message_text,
                "user_id": modal_interaction.user.id,
                "channel_id": modal_interaction.channel.id
            }
            save_reminders()

            class CancelButton(discord.ui.View):
                def __init__(self, user_id, rid):
                    super().__init__(timeout=None)
                    self.user_id = user_id
                    self.rid = rid

                @discord.ui.button(label="リマインドを削除", style=discord.ButtonStyle.danger)
                async def delete(self, interaction2: discord.Interaction, _button):
                    if interaction2.user.id != self.user_id:
                        await interaction2.response.send_message("削除権限がありません。", ephemeral=True)
                        return
                    if self.rid in reminders:
                        reminders[self.rid]["task"].cancel()
                        del reminders[self.rid]
                        save_reminders()
                        await interaction2.response.edit_message(content="リマインドを削除しました。", view=None)
                    else:
                        await interaction2.response.send_message("このリマインドは既に削除されています。", ephemeral=True)

            await modal_interaction.response.send_message(
                f"リマインドを設定しました：{remind_time.strftime('%m/%d %H:%M')}\n> {message_text}",
                view=CancelButton(interaction.user.id, remind_id),
                ephemeral=True
            )

    await interaction.followup.send_modal(ReminderMessageModal())

# =========================================================
# ✅ GOLD グループコマンド（/a1_gold balance /a1_gold send）
#    ※ 表示名を日本語にしたい場合は description を日本語に
# =========================================================
class GoldGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="a1_gold", description="GOLD関連コマンド")

    @app_commands.command(
        name="balance",
        description="あなたの所持GOLDを確認します"
    )
    async def balance(self, interaction: discord.Interaction):
        amount = get_balance(interaction.user.id)
        await interaction.response.send_message(
            f"あなたの所持GOLDは {amount} GOLD です。",
            ephemeral=True
        )

    @app_commands.command(
        name="send",
        description="任意のユーザーにGOLDを送金します"
    )
    @app_commands.describe(
        member="送金相手",
        amount="送金するGOLDの量"
    )
    async def send(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if amount <= 0:
            await interaction.response.send_message("0以下の金額は送金できません。", ephemeral=True)
            return
        if get_balance(interaction.user.id) < amount:
            await interaction.response.send_message("所持GOLDが不足しています。", ephemeral=True)
            return

        add_gold(interaction.user.id, -amount)
        add_gold(member.id, amount)
        await interaction.response.send_message(
            f"{member.display_name} に {amount} GOLD を送金しました。",
            ephemeral=True
        )

# 既存登録の直下にそのまま残してOK
bot.tree.add_command(GoldGroup())

@bot.tree.command(
    name="x1_reaction_role_setup",
    description="リアクションでロールを付与するメッセージを作成します【管理者のみ】"
)
@app_commands.describe(
    pairs="『絵文字:ロール名』をカンマ区切りで指定（例：1️⃣:猫,2️⃣:犬）",
    multi_select="True=複数選択可、False=一人一つ"
)
@app_commands.default_permissions(manage_roles=True)
async def reaction_role_setup(
    interaction: discord.Interaction,
    pairs: str,
    multi_select: bool = True
):
    parsed = [x.strip() for x in re.split("[,、]", pairs) if x.strip()]
    emoji_role_pairs = []
    for p in parsed:
        if ":" not in p:
            await interaction.response.send_message(f"形式が不正です: {p}", ephemeral=True)
            return
        emoji, role_name = p.split(":", 1)
        role = discord.utils.get(interaction.guild.roles, name=role_name.strip())
        if not role:
            role = await interaction.guild.create_role(name=role_name.strip())
        emoji_role_pairs.append((emoji.strip(), role))

    class ReactionMessageModal(discord.ui.Modal, title="リアクションロールメッセージ入力"):
        message_input = discord.ui.TextInput(label="メッセージ本文", style=discord.TextStyle.paragraph, required=True)

        async def on_submit(self, modal_interaction: discord.Interaction):
            content = self.message_input.value.strip()
            msg = await modal_interaction.channel.send(content)

            for emoji, _ in emoji_role_pairs:
                try:
                    await msg.add_reaction(emoji)
                except:
                    pass

            reaction_role_data[str(msg.id)] = {
                "roles": {emoji: role.id for emoji, role in emoji_role_pairs},
                "exclusive": not multi_select,
                "guild_id": interaction.guild.id,
            }
            save_reaction_roles()
            await modal_interaction.response.send_message(f"設定完了（ID: {msg.id}）", ephemeral=True)

    await interaction.response.send_modal(ReactionMessageModal())


@bot.tree.command(
    name="y1_edit_reaction_message",
    description="リアクションロールメッセージの本文を編集します【管理者のみ】"
)
@app_commands.describe(
    message_id="編集するメッセージID",
    new_text="差し替える本文"
)
@app_commands.default_permissions(manage_roles=True)
async def reaction_role_edit_message(interaction: discord.Interaction, message_id: str, new_text: str):
    if message_id not in reaction_role_data:
        await interaction.response.send_message("指定IDは登録されていません。", ephemeral=True)
        return
    try:
        msg = await interaction.channel.fetch_message(int(message_id))
    except:
        await interaction.response.send_message("このチャンネルではメッセージが見つかりません。", ephemeral=True)
        return
    await msg.edit(content=new_text)
    await interaction.response.send_message("本文を更新しました。", ephemeral=True)


@bot.tree.command(
    name="y2_add_reaction_role",
    description="既存リアクションロールに絵文字:ロール を追加します【管理者のみ】"
)
@app_commands.describe(
    message_id="対象メッセージID",
    emoji="追加する絵文字",
    role_name="紐づけたいロール名（なければ自動作成）"
)
@app_commands.default_permissions(manage_roles=True)
async def reaction_role_add(interaction: discord.Interaction, message_id: str, emoji: str, role_name: str):
    if message_id not in reaction_role_data:
        await interaction.response.send_message("登録されていません。", ephemeral=True)
        return
    guild = interaction.guild
    try:
        msg = await interaction.channel.fetch_message(int(message_id))
    except:
        await interaction.response.send_message("メッセージが見つかりません。", ephemeral=True)
        return
    role = discord.utils.get(guild.roles, name=role_name)
    if not role:
        role = await guild.create_role(name=role_name)
    reaction_role_data[message_id]["roles"][emoji] = role.id
    save_reaction_roles()
    try:
        await msg.add_reaction(emoji)
    except:
        pass
    await interaction.response.send_message("追加しました。", ephemeral=True)


@bot.tree.command(
    name="y3_delete_reaction_role",
    description="指定した絵文字のリアクションロール設定を削除します【管理者のみ】"
)
@app_commands.describe(
    message_id="対象メッセージID",
    emoji="削除する絵文字"
)
@app_commands.default_permissions(manage_roles=True)
async def reaction_role_delete(interaction: discord.Interaction, message_id: str, emoji: str):
    if message_id not in reaction_role_data:
        await interaction.response.send_message("登録されていません。", ephemeral=True)
        return
    if emoji not in reaction_role_data[message_id]["roles"]:
        await interaction.response.send_message("その絵文字は設定されていません。", ephemeral=True)
        return
    del reaction_role_data[message_id]["roles"][emoji]
    save_reaction_roles()
    await interaction.response.send_message("削除しました。", ephemeral=True)

@bot.tree.command(
    name="x2_inquiry_setup",
    description="問い合わせボタンを設置します【管理者のみ】"
)
@app_commands.describe(
    role="問い合わせ対応ロール",
    button_names="ボタン名をカンマ区切りで（例：質問,要望,申請）"
)
@app_commands.default_permissions(administrator=True)
async def inquiry_setup(
    interaction: discord.Interaction,
    role: discord.Role,
    button_names: str
):
    labels = [x.strip() for x in re.split("[,、]", button_names) if x.strip()]
    if not labels:
        await interaction.response.send_message("ボタン名が指定されていません。", ephemeral=True)
        return

    class InquiryMessageModal(discord.ui.Modal, title="問い合わせメッセージ入力"):
        message_input = discord.ui.TextInput(label="メッセージ本文", style=discord.TextStyle.paragraph, required=True)

        async def on_submit(self, modal_interaction: discord.Interaction):
            view = InquiryButtonView(role, labels, self.message_input.value)
            await modal_interaction.channel.send(self.message_input.value, view=view)
            await modal_interaction.response.send_message("問い合わせボタンを設置しました。", ephemeral=True)

    await interaction.response.send_modal(InquiryMessageModal())

# =========================================================
# ✅ ピン留め設定
# =========================================================
@bot.tree.command(
    name="x3_pin_set",
    description="このチャンネルにピン留めを設定します【管理者のみ】"
)
@app_commands.default_permissions(administrator=True)
async def pin_set(interaction: discord.Interaction):

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

# =========================================================
# ✅ ピン留め停止
# =========================================================
@bot.tree.command(
    name="x4_pin_stop",
    description="ピン留めを停止します【管理者のみ】"
)
@app_commands.default_permissions(administrator=True)
async def pin_stop(interaction: discord.Interaction):

    channel_id = str(interaction.channel.id)

    if channel_id in auto_templates:
        del auto_templates[channel_id]
        save_templates()
        await interaction.response.send_message("ピン留めを停止しました。", ephemeral=True)
    else:
        await interaction.response.send_message("このチャンネルには設定されていません。", ephemeral=True)

# =========================================================
# ✅ Bot起動イベント（Render最適化）
# =========================================================
@bot.event
async def on_ready():

    # データロード
    load_all_data()

    # リアクションロール設定ロード（破損対策）
    global reaction_role_data
    if os.path.exists(REACTION_FILE):
        try:
            with open(REACTION_FILE, "r", encoding="utf-8") as f:
                reaction_role_data = json.load(f)
        except Exception:
            reaction_role_data = {}

    # コマンド同期（グローバル同期）
    await bot.tree.sync()
    print(f"ログイン完了: {bot.user}")

    # --- 定期タスク起動（多重起動防止）---
    if not check_feeds.is_running():
        check_feeds.start()

    if not daily_gold_distribution.is_running():
        daily_gold_distribution.start()

    # --- 初回ボーナス配布（1回だけ実行） ---
    await distribute_initial_gold()

    # --- リマインド復元 ---
    await restore_reminders()
    print("リマインド復元完了")

# =========================================================
# ✅ Render常時稼働 keep_alive + bot.run
# =========================================================
keep_alive()  # Render で24時間動かすために必須
bot.run(os.getenv("DISCORD_TOKEN"))
