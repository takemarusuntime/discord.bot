import discord
from discord import app_commands
from discord.ext import commands
import asyncio, json, os, re, time
from datetime import datetime, timedelta, timezone
from keep_alive import keep_alive

# ===== 基本設定 =====
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)
JST = timezone(timedelta(hours=9))

# ===== データファイル =====
DATA_FILE = "cl_data.json"
cl_data = {"users": {}, "enabled": False}
reminders = {}
voice_sessions = {}

# ===== データ管理 =====
def load_data():
    global cl_data
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                cl_data = json.load(f)
        except:
            print("⚠️ データ読み込み失敗。新規作成します。")
            cl_data = {"users": {}, "enabled": False}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(cl_data, f, ensure_ascii=False, indent=4)



# ===== Communication Level 設定 =====------------------------------------------------------------------------
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
    if not cl_data.get("enabled"):
        return

    user_id = str(message.author.id)
    if user_id not in cl_data["users"]:
        cl_data["users"][user_id] = {"text": 0, "vc": 0}

    cl_data["users"][user_id]["text"] += len(message.content)
    save_data()
    await check_and_assign_roles(message.author)
    await bot.process_commands(message)

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
    for level in CL_LEVELS:
        if text >= level["text"] and vc >= level["vc"]:
            achieved = level["name"]
        else:
            break

    if not achieved:
        return

    role = discord.utils.get(guild.roles, name=achieved)
    if not role:
        role = await guild.create_role(name=achieved)

    if role not in member.roles:
        await member.add_roles(role)
        print(f"✅ {member.display_name} に {achieved} を付与しました")

    for level in CL_LEVELS:
        if level["name"] != achieved:
            r = discord.utils.get(guild.roles, name=level["name"])
            if r in member.roles:
                await member.remove_roles(r)
                print(f"❌ {member.display_name} から {level['name']} を削除しました")

# ===== ON/OFFコマンド =====
@bot.tree.command(name="Z1_CL_ON", description="Communication Level機能をONにします（管理者のみ）")
@app_commands.default_permissions(administrator=True)
async def a1_cl(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("❌ 権限がありません。", ephemeral=True)
        return
    cl_data["enabled"] = True
    save_data()
    await interaction.response.send_message("✅ Communication Level機能を **ON** にしました。", ephemeral=True)

@bot.tree.command(name="Z2_CL_OFF", description="Communication Level機能をOFFにします（管理者のみ）")
@app_commands.default_permissions(administrator=True)
async def a2_cl(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("❌ 権限がありません。", ephemeral=True)
        return
    cl_data["enabled"] = False
    save_data()
    await interaction.response.send_message("✅ Communication Level機能を **OFF** にしました。", ephemeral=True)



# ===== ロール付与メッセージ機能 =====--------------------------------------------------------------------------
@bot.tree.command(name="A1_ロール付与メッセージ", description="ボタンでロールを付与するメッセージを作成します（管理者のみ）")
@app_commands.describe(
    メッセージ内容="表示するメッセージの本文",
    ボタンとロール="例：『赤ボタン:Fire』『青ボタン:Water』『緑ボタン:Earth』のように入力（カンマ区切り）"
)
@app_commands.default_permissions(manage_roles=True)
async def role_message(interaction: discord.Interaction, メッセージ内容: str, ボタンとロール: str):
    # --- 権限チェック ---
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("❌ このコマンドを実行する権限がありません。", ephemeral=True)
        return

    # --- 入力解析 ---
    try:
        pairs = [x.strip() for x in ボタンとロール.split("、") if x.strip()]
        button_role_pairs = []
        for p in pairs:
            if ":" not in p:
                await interaction.response.send_message("⚠️ 入力形式が正しくありません。『ボタン名:ロール名』の形式で指定してください。", ephemeral=True)
                return
            label, role_name = p.split(":", 1)
            button_role_pairs.append((label.strip(), role_name.strip()))
    except Exception as e:
        await interaction.response.send_message(f"⚠️ 入力解析に失敗しました: {e}", ephemeral=True)
        return

    # --- ボタン作成 ---
    view = RoleSelectView(interaction.guild, button_role_pairs)
    await interaction.response.send_message("✅ ロール付与メッセージを作成しました。", ephemeral=True)
    await interaction.channel.send(メッセージ内容, view=view)


# ===== ボタンビュー定義 =====
class RoleSelectView(discord.ui.View):
    def __init__(self, guild, button_role_pairs):
        super().__init__(timeout=None)
        self.guild = guild
        for label, role_name in button_role_pairs:
            self.add_item(RoleButton(label=label, role_name=role_name))

# ===== 各ボタン定義 =====
class RoleButton(discord.ui.Button):
    def __init__(self, label, role_name):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.role_name = role_name

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        member = interaction.user
        role = discord.utils.get(guild.roles, name=self.role_name)

        # --- ロールが存在しなければ作成 ---
        if role is None:
            try:
                role = await guild.create_role(name=self.role_name)
                await interaction.channel.send(f"🆕 ロール `{self.role_name}` を自動作成しました。", delete_after=5)
            except discord.Forbidden:
                await interaction.response.send_message("⚠️ ロールを作成できません（権限不足）。", ephemeral=True)
                return

        # --- 付与/削除のトグル ---
        if role in member.roles:
            await member.remove_roles(role)
            await interaction.response.send_message(f"❎ ロール `{self.role_name}` を削除しました。", ephemeral=True)
        else:
            await member.add_roles(role)
            await interaction.response.send_message(f"✅ ロール `{self.role_name}` を付与しました。", ephemeral=True)



# ===== リマインド機能 =====-----------------------------------------------------------------------------------
@bot.tree.command(name="リマインド", description="指定した時間または○分後にリマインドを送ります（日本時間）")
@app_commands.describe(
    時間または分後="「21:30」または「15」など（分後指定もOK）",
    メッセージ="リマインド内容",
    表示モード="bot または user（ユーザー風）"
)
@app_commands.choices(表示モード=[
    app_commands.Choice(name="botの見た目で送信", value="bot"),
    app_commands.Choice(name="ユーザーの見た目で送信", value="user")
])
async def remind(
    interaction: discord.Interaction,
    時間または分後: str,
    メッセージ: str,
    表示モード: app_commands.Choice[str]
):
    await interaction.response.defer(ephemeral=True)
    now = datetime.now(JST)
    remind_time = None
    wait_seconds = None

    # --- 「○分後」指定 ---
    if re.fullmatch(r"\d+", 時間または分後):
        minutes = int(時間または分後)
        if minutes <= 0:
            await interaction.followup.send("分後の指定は1以上で入力してください。", ephemeral=True)
            return
        remind_time = now + timedelta(minutes=minutes)
        wait_seconds = minutes * 60
        time_text = f"{minutes}分後（{remind_time.strftime('%H:%M')}ごろ）"

    # --- 「HH:MM」形式 ---
    elif re.fullmatch(r"\d{1,2}:\d{2}", 時間または分後):
        target = datetime.strptime(時間または分後, "%H:%M").replace(
            year=now.year, month=now.month, day=now.day, tzinfo=JST
        )
        if target < now:
            target += timedelta(days=1)
        remind_time = target
        wait_seconds = (remind_time - now).total_seconds()
        time_text = remind_time.strftime("%H:%M")
    else:
        await interaction.followup.send("時間は「HH:MM」または「○分後」で指定してください。", ephemeral=True)
        return

    remind_id = f"{interaction.user.id}-{remind_time.strftime('%Y%m%d%H%M%S')}"
    mode = 表示モード.value

    # --- リマインド処理 ---
    async def remind_task():
        await asyncio.sleep(wait_seconds)
        try:
            if mode == "user":
                webhook = await interaction.channel.create_webhook(name=interaction.user.display_name)
                await webhook.send(
                    メッセージ,
                    username=interaction.user.display_name,
                    avatar_url=interaction.user.display_avatar.url
                )
                await webhook.delete()
            else:
                await interaction.channel.send(f"{interaction.user.mention} {メッセージ}")
        except Exception as e:
            print(f"リマインド送信エラー: {e}")
        reminders.pop(remind_id, None)

    task = asyncio.create_task(remind_task())
    reminders[remind_id] = {"task": task, "time": remind_time, "message": メッセージ, "mode": mode}

    view = CancelButton(interaction.user.id, remind_id)
    await interaction.followup.send(
        f"✅ リマインドを設定しました！\n**{time_text}** に以下の内容を送信します：\n> {メッセージ}\n\n表示モード：**{ 'ユーザー風' if mode=='user' else 'Bot' }**",
        view=view,
        ephemeral=True
    )

# --- リマインド削除ボタン ---
class CancelButton(discord.ui.View):
    def __init__(self, user_id: int, remind_id: str):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.remind_id = remind_id

    @discord.ui.button(label="🗑️ リマインドを削除", style=discord.ButtonStyle.danger)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("このリマインドを削除できるのは設定者のみです。", ephemeral=True)
            return
        if self.remind_id in reminders:
            reminders[self.remind_id]["task"].cancel()
            del reminders[self.remind_id]
            await interaction.response.edit_message(content="✅ リマインドを削除しました。", view=None)
        else:
            await interaction.response.send_message("このリマインドはすでに削除されています。", ephemeral=True)



# ===== 起動 =====--------------------------------------------------------------------------------------------
@bot.event
async def on_ready():
    load_data()
    await bot.tree.sync()
    print(f"✅ ログイン完了: {bot.user}")
    print(f"📊 Communication Level: {'ON' if cl_data['enabled'] else 'OFF'}")

keep_alive()
bot.run(os.getenv("DISCORD_TOKEN"))
