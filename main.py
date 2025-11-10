import os
import re
import json
import time
import random
import asyncio
import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
from datetime import time as dtime
from keep_alive import keep_alive

# ============================== 基本設定 ==============================
JST = timezone(timedelta(hours=9))

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ============================== パス ==============================
DATA_CL     = "cl_data.json"
DATA_GOLD   = "gold_data.json"
DATA_REACT  = "reaction_roles.json"
DATA_PIN    = "pin_data.json"
DATA_REMIND = "reminders.json"
INIT_FLAG   = "init_gold_flag.json"

# ============================== メモリ ==============================
cl_data: dict = {"enabled": True, "users": {}}
gold_data: dict = {}
reaction_role_data: dict = {}
pin_data: dict = {}            # {channel_id: {"message_id": int, "body": str}}
reminders: dict = {}
voice_sessions: dict = {}

# ============================== ユーティリティ ==============================
def load(path: str, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return default

def save(path: str, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

# ============================== GOLD ==============================
def get_gold(uid: int) -> int:
    return gold_data.get(str(uid), 0)

def add_gold(uid: int, amount: int):
    k = str(uid)
    gold_data[k] = gold_data.get(k, 0) + amount
    save(DATA_GOLD, gold_data)

@tasks.loop(time=dtime(hour=0, minute=0, tzinfo=JST))
async def daily_gold():
    count = 0
    for g in bot.guilds:
        for m in g.members:
            if not m.bot:
                add_gold(m.id, 1000)
                count += 1
    print(f"[毎日GOLD] {count}人へ1000G")

@bot.event
async def on_member_join(member: discord.Member):
    if member.bot:
        return
    add_gold(member.id, 10000)
    print(f"[JOIN] {member.display_name} に10000G付与")

async def initial_bonus():
    if os.path.exists(INIT_FLAG):
        return
    count = 0
    for g in bot.guilds:
        for m in g.members:
            if not m.bot:
                add_gold(m.id, 10000)
                count += 1
    save(INIT_FLAG, {"done": True, "count": count})
    print(f"[初回配布] 既存{count}人へ10000G")

# ============================== チャット / VC 報酬 ==============================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    gain = (len(message.content) // 2) * 10
    if gain > 0:
        add_gold(message.author.id, gain)

    if cl_data.get("enabled", True):
        uid = str(message.author.id)
        cl_data["users"].setdefault(uid, {"text": 0, "vc": 0})
        cl_data["users"][uid]["text"] += len(message.content)
        save(DATA_CL, cl_data)
        await check_cl_role(message.author)

    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member: discord.Member, before, after):
    if member.bot:
        return
    uid = str(member.id)

    if before.channel is None and after.channel is not None:
        voice_sessions[uid] = time.time()

    elif before.channel is not None and after.channel is None:
        start = voice_sessions.pop(uid, None)
        if start is None:
            return
        minutes = int((time.time() - start) / 60)
        if minutes > 0:
            add_gold(member.id, minutes * 10)
            cl_data["users"].setdefault(uid, {"text": 0, "vc": 0})
            cl_data["users"][uid]["vc"] += minutes
            save(DATA_CL, cl_data)
            await check_cl_role(member)

# ============================== Communication Level ==============================
CL_LEVELS = [
    {"name": "Communication Level 1", "text": 10,   "vc": 30,    "color": 0x999999},
    {"name": "Communication Level 2", "text": 50,   "vc": 180,   "color": 0x55FF55},
    {"name": "Communication Level 3", "text": 100,  "vc": 720,   "color": 0x3333FF},
    {"name": "Communication Level 4", "text": 333,  "vc": 1440,  "color": 0x8800FF},
    {"name": "Communication Level 5", "text": 666,  "vc": 7200,  "color": 0xFFFF00},
    {"name": "Communication Level 6", "text": 1000, "vc": 14400, "color": 0xFF5555},
]

async def check_cl_role(member: discord.Member):
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
    role = discord.utils.get(guild.roles, name=achieved["name"])
    if not role:
        role = await guild.create_role(name=achieved["name"], color=discord.Color(achieved["color"]))
    if role not in member.roles:
        await member.add_roles(role)

    for lv in CL_LEVELS:
        if lv["name"] != achieved["name"]:
            r = discord.utils.get(guild.roles, name=lv["name"])
            if r and r in member.roles:
                await member.remove_roles(r)

# ============================== /b1_omikuji ==============================
@bot.tree.command(name="b1_omikuji", description="おみくじを引きます")
async def b1_omikuji(interaction: discord.Interaction):
    fixed = {"大大大吉": 0.01, "大大吉": 0.03, "鬼がかり 3000 BONUS": 0.01}
    others = ["大吉", "吉", "中吉", "小吉", "末吉", "凶", "大凶"]
    rest = 1.0 - sum(fixed.values())
    each = rest / len(others)
    weights = {**fixed, **{o: each for o in others}}
    result = random.choices(list(weights.keys()), list(weights.values()), k=1)[0]

    embed = discord.Embed(title="おみくじ結果", color=discord.Color.gold())
    if result == "鬼がかり 3000 BONUS":
        add_gold(interaction.user.id, 3000)
        embed.description = "# ﾎﾟｷｭｰｰﾝ!!\n## 鬼がかり 3000 BONUS\n### 3000GOLD GET!!!!!"
        embed.color = discord.Color.from_str("#FFD700")
    else:
        embed.description = f"# {result}"

    embed.set_footer(text=f"{interaction.user.display_name} の運勢", icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ============================== /b2_remind_set ==============================
def load_reminders():
    return load(DATA_REMIND, {})

def save_reminders():
    save(DATA_REMIND, reminders)

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

async def remind_task(rid: str, data: dict, wait: float):
    try:
        await asyncio.sleep(max(0, wait))
        channel = bot.get_channel(data["channel_id"])
        user = bot.get_user(data["user_id"])
        if channel and user:
            wh = await channel.create_webhook(name=user.display_name)
            await wh.send(data["message"], username=user.display_name, avatar_url=user.display_avatar.url)
            await wh.delete()
    except:
        pass
    finally:
        reminders.pop(rid, None)
        save_reminders()

@bot.tree.command(name="b2_remind_set", description="指定した時間にリマインドします")
@app_commands.describe(時間または分後="例: 15 / 21:30 / 11/01 21:30")
async def b2_remind(interaction: discord.Interaction, 時間または分後: str):
    await interaction.response.defer(ephemeral=True)
    now = datetime.now(JST)

    if re.fullmatch(r"\d+", 時間または分後):
        remind_time = now + timedelta(minutes=int(時間または分後))
    elif re.fullmatch(r"\d{1,2}:\d{2}", 時間または分後):
        t = datetime.strptime(時間または分後, "%H:%M")
        remind_time = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        if remind_time < now:
            remind_time += timedelta(days=1)
    elif re.fullmatch(r"\d{1,2}/\d{1,2} \d{1,2}:\d{2}", 時間または分後):
        t = datetime.strptime(時間または分後, "%m/%d %H:%M")
        remind_time = now.replace(month=t.month, day=t.day, hour=t.hour, minute=t.minute, second=0, microsecond=0)
        if remind_time < now:
            remind_time = remind_time.replace(year=now.year + 1)
    else:
        await interaction.followup.send("時間形式が無効です。", ephemeral=True)
        return

    remind_id = f"{interaction.user.id}-{int(remind_time.timestamp())}"

    class MsgModal(discord.ui.Modal, title="リマインド内容入力"):
        text = discord.ui.TextInput(label="内容", style=discord.TextStyle.paragraph, required=True)

        async def on_submit(self, mi: discord.Interaction):
            msg = self.text.value.strip()
            wait = (remind_time - datetime.now(JST)).total_seconds()

            asyncio.create_task(remind_task(remind_id, {
                "message": msg,
                "time": remind_time.isoformat(),
                "user_id": mi.user.id,
                "channel_id": mi.channel.id
            }, wait))

            reminders[remind_id] = {
                "message": msg,
                "time": remind_time.isoformat(),
                "user_id": mi.user.id,
                "channel_id": mi.channel.id
            }
            save_reminders()

            class Cancel(discord.ui.View):
                def __init__(self):
                    super().__init__(timeout=None)

                @discord.ui.button(label="リマインド削除", style=discord.ButtonStyle.danger)
                async def del_btn(self, itx: discord.Interaction, _):
                    if remind_id in reminders:
                        reminders.pop(remind_id)
                        save_reminders()
                        await itx.response.edit_message(content="リマインドを削除しました。", view=None)
                    else:
                        await itx.response.send_message("削除できません。", ephemeral=True)

            await mi.response.send_message(
                f"リマインド設定完了：{remind_time.strftime('%m/%d %H:%M')}\n> {msg}",
                view=Cancel(),
                ephemeral=True
            )

    await interaction.followup.send_modal(MsgModal())

# ============================== Reaction Role: x1 / y1 / y2 / y3 ==============================
def load_reaction_roles():
    return load(DATA_REACT, {})

def save_reaction_roles():
    save(DATA_REACT, reaction_role_data)

@bot.tree.command(name="x1_reaction_setup", description="リアクションロールを新規作成（本文はモーダルで入力）")
@app_commands.describe(
    絵文字とロール="『絵文字:ロール名』をカンマ区切り（例：🔴:赤,🔵:青）",
    複数選択="True=複数可 / False=一つのみ"
)
@app_commands.default_permissions(manage_roles=True)
async def x1_rr_setup(interaction: discord.Interaction, 絵文字とロール: str, 複数選択: bool = True):
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
            try:
                role = await interaction.guild.create_role(name=role_name)
            except discord.Forbidden:
                await interaction.response.send_message(f"ロール作成不可: {role_name}", ephemeral=True)
                return
        emoji_role_pairs.append((emoji.strip(), role))

    class RRMessageModal(discord.ui.Modal, title="本文メッセージ入力"):
        body = discord.ui.TextInput(label="本文（改行可）", style=discord.TextStyle.paragraph, required=True)

        async def on_submit(self, mi: discord.Interaction):
            sent = await mi.channel.send(self.body.value)
            for e, _r in emoji_role_pairs:
                try:
                    await sent.add_reaction(e)
                except discord.HTTPException:
                    pass

            reaction_role_data[str(sent.id)] = {
                "guild_id": interaction.guild.id,
                "channel_id": mi.channel.id,
                "exclusive": (not 複数選択),
                "roles": {e: r.id for e, r in emoji_role_pairs},
                "message": self.body.value
            }
            save_reaction_roles()

            await mi.response.send_message(
                f"作成完了: メッセージID {sent.id} / 排他: {'ON' if not 複数選択 else 'OFF'}",
                ephemeral=True
            )

    await interaction.response.send_modal(RRMessageModal())

@bot.tree.command(name="y1_reaction_add", description="既存のリアクションロールにペアを追加")
@app_commands.describe(メッセージID="対象メッセージのID", 絵文字とロール="『絵文字:ロール名』をカンマ区切り")
@app_commands.default_permissions(manage_roles=True)
async def y1_rr_add(interaction: discord.Interaction, メッセージID: str, 絵文字とロール: str):
    data = reaction_role_data.get(メッセージID)
    if not data:
        await interaction.response.send_message("対象が見つかりません。", ephemeral=True)
        return

    channel = bot.get_channel(int(data["channel_id"]))
    if not channel:
        await interaction.response.send_message("チャンネルが見つかりません。", ephemeral=True)
        return

    try:
        msg = await channel.fetch_message(int(メッセージID))
    except:
        await interaction.response.send_message("メッセージ取得に失敗しました。", ephemeral=True)
        return

    pairs = [x.strip() for x in re.split("[,、]", 絵文字とロール) if x.strip()]
    added = []

    for p in pairs:
        if ":" not in p:
            continue
        emoji, role_name = p.split(":", 1)
        role_name = role_name.strip()

        role = discord.utils.get(interaction.guild.roles, name=role_name)
        if not role:
            try:
                role = await interaction.guild.create_role(name=role_name)
            except discord.Forbidden:
                continue

        data["roles"][emoji.strip()] = role.id
        try:
            await msg.add_reaction(emoji.strip())
        except:
            pass

        added.append(f"{emoji.strip()}:{role.name}")

    reaction_role_data[メッセージID] = data
    save_reaction_roles()

    await interaction.response.send_message(
        f"追加: {', '.join(added) if added else 'なし'}",
        ephemeral=True
    )

@bot.tree.command(name="y2_reaction_remove", description="既存のリアクションロールから絵文字を削除")
@app_commands.describe(メッセージID="対象メッセージのID", 絵文字一覧="削除する絵文字をカンマ区切り（例：🔴,🔵）")
@app_commands.default_permissions(manage_roles=True)
async def y2_rr_remove(interaction: discord.Interaction, メッセージID: str, 絵文字一覧: str):
    data = reaction_role_data.get(メッセージID)
    if not data:
        await interaction.response.send_message("対象が見つかりません。", ephemeral=True)
        return

    channel = bot.get_channel(int(data["channel_id"]))
    if not channel:
        await interaction.response.send_message("チャンネルが見つかりません。", ephemeral=True)
        return

    try:
        msg = await channel.fetch_message(int(メッセージID))
    except:
        await interaction.response.send_message("メッセージ取得に失敗しました。", ephemeral=True)
        return

    targets = [x.strip() for x in re.split("[,、]", 絵文字一覧) if x.strip()]
    removed = []

    for e in targets:
        if e in data["roles"]:
            data["roles"].pop(e, None)
            removed.append(e)
            try:
                for react in msg.reactions:
                    if str(react.emoji) == e:
                        await msg.clear_reaction(react.emoji)
                        break
            except:
                pass

    reaction_role_data[メッセージID] = data
    save_reaction_roles()

    await interaction.response.send_message(
        f"削除: {', '.join(removed) if removed else 'なし'}",
        ephemeral=True
    )

@bot.tree.command(name="y3_reaction_edit", description="対象メッセージの本文を編集")
@app_commands.describe(メッセージID="対象メッセージのID")
@app_commands.default_permissions(manage_messages=True)
async def y3_rr_edit_body(interaction: discord.Interaction, メッセージID: str):
    data = reaction_role_data.get(メッセージID)
    if not data:
        await interaction.response.send_message("対象が見つかりません。", ephemeral=True)
        return

    channel = bot.get_channel(int(data["channel_id"]))
    if not channel:
        await interaction.response.send_message("チャンネルが見つかりません。", ephemeral=True)
        return

    try:
        msg = await channel.fetch_message(int(メッセージID))
    except:
        await interaction.response.send_message("メッセージ取得に失敗しました。", ephemeral=True)
        return

    class EditBodyModal(discord.ui.Modal, title="本文編集"):
        body = discord.ui.TextInput(
            label="新しい本文（改行可）",
            style=discord.TextStyle.paragraph,
            required=True,
            default=data.get("message", "")
        )

        async def on_submit(self, mi: discord.Interaction):
            try:
                await msg.edit(content=self.body.value)
            except:
                await mi.response.send_message("編集に失敗しました。", ephemeral=True)
                return

            data["message"] = self.body.value
            reaction_role_data[メッセージID] = data
            save_reaction_roles()

            await mi.response.send_message("本文を更新しました。", ephemeral=True)

    await interaction.response.send_modal(EditBodyModal())

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    mid = str(payload.message_id)
    if mid not in reaction_role_data or payload.user_id == bot.user.id:
        return

    d = reaction_role_data[mid]
    emoji = str(payload.emoji)
    role_id = d["roles"].get(emoji)
    if not role_id:
        return

    guild = bot.get_guild(int(d["guild_id"]))
    if not guild:
        return

    member = guild.get_member(payload.user_id)
    role = guild.get_role(role_id)
    if not member or not role:
        return

    try:
        if d.get("exclusive"):
            for rid in d["roles"].values():
                if rid != role.id:
                    r = guild.get_role(rid)
                    if r and r in member.roles:
                        await member.remove_roles(r)
        await member.add_roles(role)
    except:
        pass

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    mid = str(payload.message_id)
    if mid not in reaction_role_data:
        return

    d = reaction_role_data[mid]
    emoji = str(payload.emoji)
    role_id = d["roles"].get(emoji)
    if not role_id:
        return

    guild = bot.get_guild(int(d["guild_id"]))
    if not guild:
        return

    member = guild.get_member(payload.user_id)
    role = guild.get_role(role_id)
    if not member or not role:
        return

    try:
        await member.remove_roles(role)
    except:
        pass

# ============================== 問い合わせ /x2_ticket_setup ==============================
@bot.tree.command(name="x2_ticket_setup", description="問い合わせボタンを設置（本文はモーダルで入力）")
@app_commands.describe(対応ロール="対応するロール", ボタン名="カンマ区切り（例：質問,要望,申請）")
@app_commands.default_permissions(administrator=True)
async def x2_ticket_setup(interaction: discord.Interaction, 対応ロール: discord.Role, ボタン名: str):
    labels = [x.strip() for x in re.split("[,、]", ボタン名) if x.strip()]
    if not labels:
        await interaction.response.send_message("ボタン名が空です。", ephemeral=True)
        return

    class TicketBodyModal(discord.ui.Modal, title="案内メッセージ入力"):
        body = discord.ui.TextInput(label="本文（改行可）", style=discord.TextStyle.paragraph, required=True)

        async def on_submit(self, mi: discord.Interaction):
            view = InquiryButtonView(対応ロール, labels, self.body.value)
            await mi.channel.send(self.body.value, view=view)
            await mi.response.send_message("問い合わせボタンを設置しました。", ephemeral=True)

    await interaction.response.send_modal(TicketBodyModal())

class InquiryButtonView(discord.ui.View):
    def __init__(self, role: discord.Role, labels: list[str], message: str):
        super().__init__(timeout=None)
        self.role = role
        self.message = message
        for label in labels:
            self.add_item(InquiryButton(label=label, role=role, message=message))

class InquiryButton(discord.ui.Button):
    def __init__(self, label: str, role: discord.Role, message: str):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.role = role
        self.message = message

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user
        category = interaction.channel.category
        name = f"{user.display_name}-{self.label}"

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            self.role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }

        ch = await guild.create_text_channel(name=name, category=category, overwrites=overwrites)
        await ch.send(self.message, view=DeleteChannelButton())
        await interaction.response.send_message("チャンネルを作成しました。", ephemeral=True)

class DeleteChannelButton(discord.ui.View):
    @discord.ui.button(label="チャンネルを削除する", style=discord.ButtonStyle.danger)
    async def delete_channel(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_message("数秒後に削除します。", ephemeral=True)
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason="Ticket close")
        except:
            pass

# ============================== ピン留め x3 / x4 ==============================
def load_pin():
    return load(DATA_PIN, {})

def save_pin():
    save(DATA_PIN, pin_data)

@bot.tree.command(name="x3_pin_set", description="このチャンネルに案内メッセージを固定（本文はモーダル）")
@app_commands.default_permissions(administrator=True)
async def x3_pin(interaction: discord.Interaction):
    class PinBodyModal(discord.ui.Modal, title="ピン留め本文入力"):
        body = discord.ui.TextInput(label="本文（改行可）", style=discord.TextStyle.paragraph, required=True)

        async def on_submit(self, mi: discord.Interaction):
            cid = str(mi.channel.id)

            old = pin_data.get(cid)
            if old:
                try:
                    msg_old = await mi.channel.fetch_message(int(old["message_id"]))
                    await msg_old.delete()
                except:
                    pass

            sent = await mi.channel.send(self.body.value)
            pin_data[cid] = {"message_id": sent.id, "body": self.body.value}
            save_pin()

            await mi.response.send_message("ピン留めメッセージを設定しました。", ephemeral=True)

    await interaction.response.send_modal(PinBodyModal())

@bot.tree.command(name="x4_pin_delete", description="このチャンネルのピン留めを削除")
@app_commands.default_permissions(administrator=True)
async def x4_unpin(interaction: discord.Interaction):
    cid = str(interaction.channel.id)
    if cid not in pin_data:
        await interaction.response.send_message("設定がありません。", ephemeral=True)
        return

    ok = False
    try:
        msg = await interaction.channel.fetch_message(int(pin_data[cid]["message_id"]))
        await msg.delete()
        ok = True
    except:
        pass

    pin_data.pop(cid, None)
    save_pin()

    await interaction.response.send_message(
        "削除しました。" if ok else "記録のみ削除しました。",
        ephemeral=True
    )

# ============================== 起動処理 ==============================
@bot.event
async def on_ready():
    global cl_data, gold_data, reaction_role_data, pin_data

    cl_data = load(DATA_CL, {"enabled": True, "users": {}})
    gold_data = load(DATA_GOLD, {})
    reaction_role_data = load_reaction_roles()
    pin_data = load_pin()

    await bot.tree.sync()
    print(f"ログイン完了: {bot.user} / CL: {'ON' if cl_data.get('enabled') else 'OFF'}")

    if not daily_gold.is_running():
        daily_gold.start()

    await initial_bonus()
    await restore_reminders()
    print("初期化完了")

# ============================== 24/7 ==============================
keep_alive()
bot.run(os.getenv("DISCORD_TOKEN"))
