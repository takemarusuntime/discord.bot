import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio, json, os, re, time
from datetime import datetime, timedelta, timezone
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
cl_data = {"users": {}, "enabled": False}
reminders = {}
voice_sessions = {}
tracking_feeds = {}

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



# ===== Communication Level 設定 =====
CL_LEVELS = [
    {"name": "Communication Level 1", "text": 10, "vc": 30, "color": 0x999999},
    {"name": "Communication Level 2", "text": 50, "vc": 180, "color": 0x55ff55},
    {"name": "Communication Level 3", "text": 100, "vc": 720, "color": 0x3333ff},
    {"name": "Communication Level 4", "text": 333, "vc": 1440, "color": 0x8800ff},
    {"name": "Communication Level 5", "text": 666, "vc": 7200, "color": 0xffff00},
    {"name": "Communication Level 6", "text": 1000, "vc": 14400, "color": 0xff5555},
]

# ===== Communication Level 記録 =====
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    await bot.process_commands(message)

    if not cl_data.get("enabled"):
        return

    user_id = str(message.author.id)
    if user_id not in cl_data["users"]:
        cl_data["users"][user_id] = {"text": 0, "vc": 0}

    cl_data["users"][user_id]["text"] += len(message.content)
    save_data()
    await check_and_assign_roles(message.author)

@bot.event
async def on_voice_state_update(member, before, after):
    if not cl_data.get("enabled"):
        return
    user_id = str(member.id)
    if before.channel is None and after.channel is not None:
        voice_sessions[user_id] = time.time()
    elif before.channel is not None and after.channel is None:
        if user_id in voice_sessions:
            duration = int((time.time() - voice_sessions[user_id]) / 60)
            del voice_sessions[user_id]
            if user_id not in cl_data["users"]:
                cl_data["users"][user_id] = {"text": 0, "vc": 0}
            cl_data["users"][user_id]["vc"] += duration
            save_data()
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
async def a1_cl(interaction: discord.Interaction):
    cl_data["enabled"] = True
    save_data()
    await interaction.response.send_message("Communication Level機能をONにしました。", ephemeral=True)

@bot.tree.command(name="z2_cl_off", description="Communication Level機能をOFFにします（管理者のみ）")
@app_commands.default_permissions(administrator=True)
async def a2_cl(interaction: discord.Interaction):
    cl_data["enabled"] = False
    save_data()
    await interaction.response.send_message("Communication Level機能をOFFにしました。", ephemeral=True)



# ===== ロール付与メッセージ機能 =====
@bot.tree.command(
    name="a1_ロール付与メッセージ",
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



# ===== ピン留め =====
TEMPLATE_FILE = "auto_templates.json"

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


# --- 設定コマンド ---
@bot.tree.command(name="a2ピン留め設定", description="このチャンネルにピン留めを設定します（管理者のみ）")
@app_commands.describe(メッセージ="ピン留め内容")
@app_commands.default_permissions(administrator=True)
async def set_template(interaction: discord.Interaction, メッセージ: str):
    channel_id = str(interaction.channel.id)
    auto_templates[channel_id] = メッセージ
    save_templates(auto_templates)
    await interaction.response.send_message(f"このチャンネルにピン留めを設定しました。", ephemeral=True)


# --- 停止コマンド ---
@bot.tree.command(name="a3ピン留め停止", description="このチャンネルのピン留めを停止します（管理者のみ）")
@app_commands.default_permissions(administrator=True)
async def stop_template(interaction: discord.Interaction):
    channel_id = str(interaction.channel.id)
    if channel_id in auto_templates:
        del auto_templates[channel_id]
        save_templates(auto_templates)
        await interaction.response.send_message("このチャンネルのピン留めを停止しました。", ephemeral=True)
    else:
        await interaction.response.send_message("このチャンネルにはピン留めが設定されていません。", ephemeral=True)


# --- メッセージ監視 ---
@bot.event
async def on_message(message: discord.Message):
    # Bot自身には反応しない
    if message.author.bot:
        return

    channel_id = str(message.channel.id)

    # 対象チャンネルにピン留めが設定されている場合のみ動作
    if channel_id in auto_templates:
        template_text = auto_templates[channel_id]

        # 古いピン留めを削除（存在すれば）
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

        # 新しいピン留めを投稿
        try:
            new_msg = await message.channel.send(template_text)
            last_template_messages[channel_id] = new_msg.id
        except discord.Forbidden:
            print(f"Botに送信権限がありません（チャンネルID: {channel_id}）")
        except Exception as e:
            print(f"ピン留め投稿エラー: {e}")

    # 他の機能のon_messageを継続
    await bot.process_commands(message)



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

@bot.tree.command(name="a4_Xポスト引用", description="指定アカウントの新規ポスト・引用を自動で貼ります（管理者のみ）")
@app_commands.describe(アカウント名="例：elonmusk")
@app_commands.default_permissions(administrator=True)
async def x_post(interaction: discord.Interaction, アカウント名: str):
    rss_url = f"https://nitter.net/{アカウント名}/rss"
    tracking_feeds[str(interaction.channel.id)] = {"rss": rss_url, "latest": None}
    save_feeds()
    if not check_feeds.is_running():
        check_feeds.start()
    await interaction.response.send_message(f"@{アカウント名} の投稿監視を開始しました。", ephemeral=True)

# ===== Xポスト停止コマンド =====
@bot.tree.command(name="a5_Xポスト停止", description="このチャンネルでのXポスト監視を停止します（管理者のみ）")
@app_commands.default_permissions(administrator=True)
async def x_post_stop(interaction: discord.Interaction):
    channel_id = str(interaction.channel.id)
    if channel_id in tracking_feeds:
        del tracking_feeds[channel_id]
        save_feeds()
        await interaction.response.send_message("このチャンネルでのXポスト監視を停止しました。", ephemeral=True)
    else:
        await interaction.response.send_message("このチャンネルでは現在Xポスト監視が有効ではありません。", ephemeral=True)





# ===== リマインド =====
@bot.tree.command(name="1_リマインド", description="指定した時間または日付＋時間にリマインドを送ります（日本時間）")
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
    view = CancelButton(interaction.user.id, remind_id)
    await interaction.followup.send(f"リマインドを設定しました：{remind_time.strftime('%m/%d %H:%M')}\n> {メッセージ}", view=view, ephemeral=True)

class CancelButton(discord.ui.View):
    def __init__(self, user_id: int, remind_id: str):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.remind_id = remind_id

    @discord.ui.button(label="リマインドを削除", style=discord.ButtonStyle.danger)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("削除権限がありません。", ephemeral=True)
            return
        if self.remind_id in reminders:
            reminders[self.remind_id]["task"].cancel()
            del reminders[self.remind_id]
            await interaction.response.edit_message(content="リマインドを削除しました。", view=None)
        else:
            await interaction.response.send_message("このリマインドはすでに削除されています。", ephemeral=True)

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

keep_alive()
bot.run(os.getenv("DISCORD_TOKEN"))
