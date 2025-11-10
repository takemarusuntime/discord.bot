import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio, json, os, re, random, time
from datetime import datetime, timedelta, timezone
from datetime import time as dtime
from keep_alive import keep_alive

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

# ============================== メモリ ==============================
cl_data = {"enabled": True, "users": {}}
gold_data = {}
reaction_role_data = {}
pin_data = {}             # {channel_id: {"message_id": int, "body": str}}
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

# ============================== GOLD ==============================
def get_gold(uid):
    return gold_data.get(str(uid), 0)

def add_gold(uid, amount):
    uid = str(uid)
    gold_data[uid] = gold_data.get(uid, 0) + amount
    save(DATA_GOLD, gold_data)

@tasks.loop(time=dtime(hour=0, minute=0, tzinfo=JST))
async def daily_gold():
    cnt = 0
    for guild in bot.guilds:
        for m in guild.members:
            if not m.bot:
                add_gold(m.id, 1000)
                cnt += 1
    print(f"[Daily] {cnt}人に1000 GOLD")

@bot.event
async def on_member_join(member):
    if not member.bot:
        add_gold(member.id, 10000)
        print(f"[JOIN] {member.display_name} に10000 GOLD")

async def initial_bonus():
    if os.path.exists(INIT_FLAG):
        return
    cnt = 0
    for guild in bot.guilds:
        for m in guild.members:
            if not m.bot:
                add_gold(m.id, 10000)
                cnt += 1
    save(INIT_FLAG, {"done": True})
    print(f"[初回配布] {cnt}人へ10000 GOLD")

# ============================== チャット / VC 報酬 ==============================
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # --- チャット報酬 ---
    gain = (len(message.content) // 2) * 10
    if gain > 0:
        add_gold(message.author.id, gain)

    # --- Communication Level ---
    if cl_data["enabled"]:
        uid = str(message.author.id)
        cl_data["users"].setdefault(uid, {"text": 0, "vc": 0})
        cl_data["users"][uid]["text"] += len(message.content)
        save(DATA_CL, cl_data)
        await check_cl_role(message.author)

    # ============================== Bot独自ピン（最下部固定） ==============================
    cid = str(message.channel.id)
    if cid in pin_data and message.author.id != bot.user.id:

        data = pin_data[cid]

        # 古い固定メッセージ削除
        try:
            old_msg = await message.channel.fetch_message(int(data["message_id"]))
            await old_msg.delete()
        except:
            pass

        # 最下部へ再投稿
        new_msg = await message.channel.send(data["body"])
        pin_data[cid]["message_id"] = new_msg.id
        save(DATA_PIN, pin_data)

    # --- コマンド処理 ---
    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    uid = str(member.id)

    # VC 入室
    if before.channel is None and after.channel is not None:
        voice_sessions[uid] = time.time()

    # VC 退出
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

# ============================== Communication Level ==============================
CL_LEVELS = [
    {"name": "Communication Level 1", "text": 10,   "vc": 30,    "color": 0x999999},
    {"name": "Communication Level 2", "text": 50,   "vc": 180,   "color": 0x55FF55},
    {"name": "Communication Level 3", "text": 100,  "vc": 720,   "color": 0x3333FF},
    {"name": "Communication Level 4", "text": 333,  "vc": 1440,  "color": 0x8800FF},
    {"name": "Communication Level 5", "text": 666,  "vc": 7200,  "color": 0xFFFF00},
    {"name": "Communication Level 6", "text": 1000, "vc": 14400, "color": 0xFF5555},
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

# ============================== /b1_おみくじ ==============================
@bot.tree.command(
    name="b1_おみくじ",
    description="おみくじを引きます"
)
async def b1_omikuji(interaction: discord.Interaction):

    fixed = {
        "大大大吉": 0.01,
        "大大吉":   0.03,
        "鬼がかり 3000 BONUS": 0.01
    }
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

    embed.set_footer(
        text=f"{interaction.user.display_name} の運勢",
        icon_url=interaction.user.display_avatar.url
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ============================== リマインド 共通関数 ==============================
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


# ============================== /b2_リマインド設定 ==============================
@bot.tree.command(
    name="b2_リマインド設定",
    description="指定した時間にリマインドします"
)
@app_commands.describe(when="例: 15 / 21:30 / 11/01 21:30")
async def b2_remind(interaction: discord.Interaction, when: str):

    await interaction.response.defer(ephemeral=True)
    now = datetime.now(JST)

    # ---- 分後 ----
    if re.fullmatch(r"\d+", when):
        remind_time = now + timedelta(minutes=int(when))

    # ---- 今日の時刻 ----
    elif re.fullmatch(r"\d{1,2}:\d{2}", when):
        t = datetime.strptime(when, "%H:%M")
        remind_time = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        if remind_time < now:
            remind_time += timedelta(days=1)

    # ---- 月日 + 時刻 ----
    elif re.fullmatch(r"\d{1,2}/\d{1,2} \d{1,2}:\d{2}", when):
        t = datetime.strptime(when, "%m/%d %H:%M")
        remind_time = now.replace(
            month=t.month,
            day=t.day,
            hour=t.hour,
            minute=t.minute,
            second=0,
            microsecond=0
        )
        if remind_time < now:
            remind_time = remind_time.replace(year=now.year + 1)

    else:
        await interaction.followup.send("時間形式が無効です。", ephemeral=True)
        return

    remind_id = f"{interaction.user.id}-{int(remind_time.timestamp())}"

    # ---- モーダル ----
    class MsgModal(discord.ui.Modal, title="リマインド内容入力"):

        text = discord.ui.TextInput(
            label="内容",
            style=discord.TextStyle.paragraph,
            required=True
        )

        async def on_submit(self, mi: discord.Interaction):

            msg = self.text.value.strip()
            wait = (remind_time - datetime.now(JST)).total_seconds()

            asyncio.create_task(remind_task(
                remind_id,
                {
                    "message": msg,
                    "time": remind_time.isoformat(),
                    "user_id": mi.user.id,
                    "channel_id": mi.channel.id
                },
                wait
            ))

            reminders[remind_id] = {
                "message": msg,
                "time": remind_time.isoformat(),
                "user_id": mi.user.id,
                "channel_id": mi.channel.id
            }
            save_reminders()

            # ---- 削除ボタン ----
            class Cancel(discord.ui.View):
                def __init__(self):
                    super().__init__(timeout=None)

                @discord.ui.button(label="リマインド削除", style=discord.ButtonStyle.danger)
                async def del_btn(self, itx: discord.Interaction, _):
                    if remind_id in reminders:
                        reminders.pop(remind_id)
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

# ============================== リアクションロール：共通関数 ==============================
def load_reaction_roles():
    return load(DATA_REACT, {})

def save_reaction_roles():
    save(DATA_REACT, reaction_role_data)


# ============================== x1_リアクションロール設定 ==============================
@bot.tree.command(
    name="x1_リアクションロール設定",
    description="リアクションロールを新規作成します"
)
@app_commands.describe(
    pairs="絵文字:ロール名 をカンマ区切り（例：🔴:赤,🔵:青）",
    multi_select="True=複数選択可 / False=一つのみ"
)
@app_commands.default_permissions(manage_roles=True)
async def x1_rr_setup(interaction: discord.Interaction, pairs: str, multi_select: bool = True):

    # ==== 絵文字:ロール解析 ====
    pair_list = [x.strip() for x in re.split("[,、]", pairs) if x.strip()]
    emoji_role_pairs = []

    for p in pair_list:
        if ":" not in p:
            await interaction.response.send_message(f"形式エラー: {p}", ephemeral=True)
            return

        emoji, role_name = p.split(":", 1)
        role_name = role_name.strip()

        role = discord.utils.get(interaction.guild.roles, name=role_name)
        if not role:
            try:
                role = await interaction.guild.create_role(name=role_name)
            except:
                await interaction.response.send_message(f"ロール作成不可: {role_name}", ephemeral=True)
                return

        emoji_role_pairs.append((emoji.strip(), role))

    # ==== 本文をモーダルで入力 ====
    class RRMessageModal(discord.ui.Modal, title="リアクションロール本文"):
        body = discord.ui.TextInput(
            label="本文（改行可）",
            style=discord.TextStyle.paragraph,
            required=True
        )

        async def on_submit(self, mi: discord.Interaction):

            msg = await mi.channel.send(self.body.value)

            # リアクション付与
            for emoji, _role in emoji_role_pairs:
                try:
                    await msg.add_reaction(emoji)
                except:
                    pass

            # 保存
            reaction_role_data[str(msg.id)] = {
                "guild_id": interaction.guild.id,
                "channel_id": mi.channel.id,
                "exclusive": (not multi_select),
                "roles": {e: r.id for e, r in emoji_role_pairs},
                "message": self.body.value
            }
            save_reaction_roles()

            await mi.response.send_message(
                f"✅ 作成完了\nメッセージID: {msg.id}\n排他: {'ON' if not multi_select else 'OFF'}",
                ephemeral=True
            )

    await interaction.response.send_modal(RRMessageModal())


# ============================== y1_リアクションロール追加 ==============================
@bot.tree.command(
    name="y1_リアクションロール追加",
    description="既存リアクションロールへ追加"
)
@app_commands.describe(
    message_id="対象メッセージのID",
    pairs="絵文字:ロール名 をカンマ区切り"
)
@app_commands.default_permissions(manage_roles=True)
async def y1_rr_add(interaction: discord.Interaction, message_id: str, pairs: str):

    data = reaction_role_data.get(message_id)
    if not data:
        await interaction.response.send_message("対象が存在しません。", ephemeral=True)
        return

    channel = bot.get_channel(int(data["channel_id"]))
    try:
        msg = await channel.fetch_message(int(message_id))
    except:
        await interaction.response.send_message("メッセージ取得失敗。", ephemeral=True)
        return

    pair_list = [x.strip() for x in re.split("[,、]", pairs) if x.strip()]
    added = []

    for p in pair_list:
        if ":" not in p:
            continue

        emoji, role_name = p.split(":", 1)
        role_name = role_name.strip()

        role = discord.utils.get(interaction.guild.roles, name=role_name)
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
    await interaction.response.send_message(
        f"追加：{', '.join(added) if added else '無し'}",
        ephemeral=True
    )


# ============================== y2_リアクションロール削除 ==============================
@bot.tree.command(
    name="y2_リアクションロール削除",
    description="既存リアクションロールから削除"
)
@app_commands.describe(
    message_id="メッセージID",
    emojis="削除する絵文字をカンマ区切り"
)
@app_commands.default_permissions(manage_roles=True)
async def y2_rr_remove(interaction: discord.Interaction, message_id: str, emojis: str):

    data = reaction_role_data.get(message_id)
    if not data:
        await interaction.response.send_message("対象が存在しません。", ephemeral=True)
        return

    channel = bot.get_channel(int(data["channel_id"]))
    try:
        msg = await channel.fetch_message(int(message_id))
    except:
        await interaction.response.send_message("メッセージ取得失敗", ephemeral=True)
        return

    targets = [x.strip() for x in re.split("[,、]", emojis) if x.strip()]
    removed = []

    for e in targets:
        if e in data["roles"]:
            data["roles"].pop(e, None)
            removed.append(e)

            # リアクション削除
            try:
                for r in msg.reactions:
                    if str(r.emoji) == e:
                        await msg.clear_reaction(r.emoji)
                        break
            except:
                pass

    save_reaction_roles()
    await interaction.response.send_message(
        f"削除：{', '.join(removed) if removed else '無し'}",
        ephemeral=True
    )


# ============================== y3_リアクションロール本文編集 ==============================
@bot.tree.command(
    name="y3_リアクションロール本文編集",
    description="リアクションロール本文を編集"
)
@app_commands.describe(message_id="編集対象のメッセージID")
@app_commands.default_permissions(manage_messages=True)
async def y3_rr_edit_body(interaction: discord.Interaction, message_id: str):

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

    class EditBodyModal(discord.ui.Modal, title="本文編集"):
        body = discord.ui.TextInput(
            label="本文（改行可）",
            style=discord.TextStyle.paragraph,
            required=True,
            default=data.get("message", "")
        )

        async def on_submit(self, mi: discord.Interaction):
            try:
                await msg.edit(content=self.body.value)
            except:
                await mi.response.send_message("編集失敗", ephemeral=True)
                return

            data["message"] = self.body.value
            save_reaction_roles()

            await mi.response.send_message("✅ 更新しました", ephemeral=True)

    await interaction.response.send_modal(EditBodyModal())


# ============================== リアクション付与/削除の処理 ==============================
@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
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
        # 排他 → 他のロールを外す
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
    member = guild.get_member(payload.user_id)
    role = guild.get_role(role_id)

    if not member or not role:
        return

    try:
        await member.remove_roles(role)
    except:
        pass

# ============================== 問い合わせ：設定コマンド ==============================
@bot.tree.command(
    name="x2_問い合わせ設定",
    description="問い合わせボタンを設置します"
)
@app_commands.describe(
    support_role="対応するロール",
    button_labels="カンマ区切り（例：質問,要望,申請）"
)
@app_commands.default_permissions(administrator=True)
async def x2_ticket_setup(interaction: discord.Interaction, support_role: discord.Role, button_labels: str):

    labels = [x.strip() for x in re.split("[,、]", button_labels) if x.strip()]
    if not labels:
        await interaction.response.send_message("ボタン名が空です。", ephemeral=True)
        return

    class TicketBodyModal(discord.ui.Modal, title="案内メッセージ入力"):
        body = discord.ui.TextInput(
            label="本文（改行可）",
            style=discord.TextStyle.paragraph,
            required=True
        )

        async def on_submit(self, mi: discord.Interaction):
            view = InquiryButtonView(support_role, labels, self.body.value)
            await mi.channel.send(self.body.value, view=view)
            await mi.response.send_message("✅ 問い合わせボタンを設置しました。", ephemeral=True)

    await interaction.response.send_modal(TicketBodyModal())


# ============================== 問い合わせ：ボタンビュー ==============================
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
        name = f"{user.display_name}-{self.label}"

        # 権限設定
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            self.role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }

        # チャンネル作成
        ch = await guild.create_text_channel(
            name=name, category=category, overwrites=overwrites
        )

        await ch.send(self.message, view=DeleteChannelButton())
        await interaction.response.send_message("✅ チャンネルを作成しました。", ephemeral=True)


class DeleteChannelButton(discord.ui.View):
    @discord.ui.button(label="チャンネルを削除する", style=discord.ButtonStyle.danger)
    async def delete_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("削除します…", ephemeral=True)
        await asyncio.sleep(3)
        try:
            await interaction.channel.delete(reason="Ticket closed")
        except:
            pass

# ============================== ピン留め（保存・読み込み） ==============================
def load_pin():
    return load(DATA_PIN, {})

def save_pin():
    save(DATA_PIN, pin_data)


# ============================== x3_ピン留め設定 ==============================
@bot.tree.command(
    name="x3_ピン留め設定",
    description="このチャンネルの固定メッセージを設定します（Bot独自）"
)
@app_commands.default_permissions(administrator=True)
async def x3_pin(interaction: discord.Interaction):

    class PinBodyModal(discord.ui.Modal, title="ピン留め本文入力"):
        body = discord.ui.TextInput(
            label="本文（改行可）",
            style=discord.TextStyle.paragraph,
            required=True
        )

        async def on_submit(self, mi: discord.Interaction):
            cid = str(mi.channel.id)

            # 旧メッセージ削除
            old = pin_data.get(cid)
            if old:
                try:
                    msg_old = await mi.channel.fetch_message(int(old["message_id"]))
                    await msg_old.delete()
                except:
                    pass

            # 新しい固定メッセージ投稿
            new_msg = await mi.channel.send(self.body.value)

            # 保存
            pin_data[cid] = {"message_id": new_msg.id, "body": self.body.value}
            save_pin()

            await mi.response.send_message("✅ 自動固定メッセージを設定しました。", ephemeral=True)

    await interaction.response.send_modal(PinBodyModal())


# ============================== x4_ピン留め削除 ==============================
@bot.tree.command(
    name="x4_ピン留め削除",
    description="このチャンネルの固定メッセージを削除します（Bot独自）"
)
@app_commands.default_permissions(administrator=True)
async def x4_unpin(interaction: discord.Interaction):
    cid = str(interaction.channel.id)

    if cid not in pin_data:
        await interaction.response.send_message("設定された固定メッセージはありません。", ephemeral=True)
        return

    try:
        msg = await interaction.channel.fetch_message(int(pin_data[cid]["message_id"]))
        await msg.delete()
    except:
        pass

    pin_data.pop(cid, None)
    save_pin()

    await interaction.response.send_message("✅ 固定メッセージを削除しました。", ephemeral=True)

# ============================== on_ready ==============================
@bot.event
async def on_ready():
    global cl_data, gold_data, reaction_role_data, pin_data

    cl_data = load(DATA_CL, {"enabled": True, "users": {}})
    gold_data = load(DATA_GOLD, {})
    reaction_role_data = load_reaction_roles()
    pin_data = load_pin()

    # スラッシュコマンド同期
    await bot.tree.sync()

    print(f"✅ ログイン完了: {bot.user}")
    print(f"✅ Communication Level: {'ON' if cl_data.get('enabled') else 'OFF'}")

    # 毎日GOLD配布開始
    if not daily_gold.is_running():
        daily_gold.start()

    # 初回ボーナス
    await initial_bonus()

    # リマインド復元
    await restore_reminders()

    print("✅ 起動処理完了")

# ============================== 24時間稼働 ==============================
keep_alive()
bot.run(os.getenv("DISCORD_TOKEN"))
