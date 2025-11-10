import os
import json
import discord
from discord import app_commands
from discord.ext import commands
from keep_alive import keep_alive


# ============================================================
#  BOT 基本設定
# ============================================================
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

DATA_FILE = "reaction_roles.json"


# ============================================================
#  JSON 読み書き
# ============================================================
def load_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False)
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    os.replace(tmp, DATA_FILE)


rr_data = load_data()


# ============================================================
#  ユーティリティ
# ============================================================
def parse_pairs(text):
    """
    "😀:@メンバー, 🔥:VIP" → [("😀", "@メンバー"), ("🔥", "VIP")]
    """
    pairs = []
    for chunk in text.split(","):
        chunk = chunk.strip()
        if ":" not in chunk:
            raise ValueError(f"形式エラー: {chunk}  ← 絵文字:ロール の形式で指定してください")
        emoji, role = chunk.split(":", 1)
        pairs.append((emoji.strip(), role.strip()))
    return pairs


async def resolve_role(guild, role_text):
    """ロール名 / メンション / ID のいずれかに対応"""
    role_text = role_text.strip()

    # メンション <@&123>
    if role_text.startswith("<@&") and role_text.endswith(">"):
        rid = int(role_text[3:-1])
        return guild.get_role(rid)

    # ID
    if role_text.isdigit():
        return guild.get_role(int(role_text))

    # 名前完全一致
    role = discord.utils.get(guild.roles, name=role_text)
    if role:
        return role

    return None


async def fetch_msg(interaction, id_or_link):
    """メッセージリンク または メッセージID から Message を取得"""
    text = id_or_link.strip()

    # リンク
    if "discord.com/channels" in text:
        guild_id, channel_id, msg_id = text.split("/")[-3:]
        if int(guild_id) != interaction.guild.id:
            raise ValueError("他サーバーのメッセージは指定できません。")
        channel = interaction.guild.get_channel(int(channel_id))
        return await channel.fetch_message(int(msg_id))

    # ID
    return await interaction.channel.fetch_message(int(text))


def is_admin(interaction):
    return interaction.user.guild_permissions.administrator


# ============================================================
#  モーダル（本文入力）
# ============================================================
class BodyModal(discord.ui.Modal, title="本文を入力"):
    body = discord.ui.TextInput(label="本文", style=discord.TextStyle.paragraph)

    def __init__(self, callback):
        super().__init__()
        self.callback_func = callback

    async def on_submit(self, interaction):
        await self.callback_func(interaction, str(self.body))


# ============================================================
#  X1 新規リアクションロール設定
# ============================================================
@app_commands.default_permissions(administrator=True)
@app_commands.command(
    name="x1_リアクションロール設定",
    description="リアクションロールを新規作成します（管理者のみ）"
)
@app_commands.describe(
    絵文字ロール一覧="例: 😀:@メンバー, 🔥:VIP",
    複数選択="true なら複数ロール許可"
)
async def x1(interaction, 絵文字ロール一覧: str, 複数選択: bool):

    if not is_admin(interaction):
        return await interaction.response.send_message("管理者のみ実行できます。", ephemeral=True)

    try:
        pairs_raw = parse_pairs(絵文字ロール一覧)
    except Exception as e:
        return await interaction.response.send_message(str(e), ephemeral=True)

    async def submit(inter, body_text):
        embed = discord.Embed(description=body_text, color=discord.Color.gold())
        msg = await inter.channel.send(embed=embed)

        items = []
        for emoji, role_txt in pairs_raw:
            role = await resolve_role(inter.guild, role_txt)
            if role is None:
                return await inter.followup.send(f"ロールが見つかりません: {role_txt}", ephemeral=True)

            await msg.add_reaction(emoji)
            items.append({"emoji": emoji, "role_id": role.id})

        rr_data[str(msg.id)] = {
            "channel_id": inter.channel.id,
            "multiple": bool(複数選択),
            "body": body_text,
            "items": items
        }
        save_data(rr_data)

        await inter.followup.send("設定しました。", ephemeral=True)

    await interaction.response.send_modal(BodyModal(submit))


# ============================================================
#  Y1 追加
# ============================================================
@app_commands.default_permissions(administrator=True)
@app_commands.command(
    name="y1_リアクションロール追加",
    description="既存メッセージに絵文字:ロールを追加（管理者のみ）"
)
@app_commands.describe(
    メッセージ="メッセージID または メッセージリンク",
    追加一覧="例: 😀:@メンバー, 🔥:VIP"
)
async def y1(interaction, メッセージ: str, 追加一覧: str):

    if not is_admin(interaction):
        return await interaction.response.send_message("管理者のみ実行できます。", ephemeral=True)

    try:
        msg = await fetch_msg(interaction, メッセージ)
    except Exception as e:
        return await interaction.response.send_message(f"メッセージ取得失敗: {e}", ephemeral=True)

    key = str(msg.id)
    if key not in rr_data:
        return await interaction.response.send_message("このメッセージはリアクションロール未登録です。", ephemeral=True)

    try:
        pairs_raw = parse_pairs(追加一覧)
    except Exception as e:
        return await interaction.response.send_message(str(e), ephemeral=True)

    added = []
    for emoji, role_txt in pairs_raw:
        role = await resolve_role(interaction.guild, role_txt)
        if role is None:
            continue

        await msg.add_reaction(emoji)
        rr_data[key]["items"].append({"emoji": emoji, "role_id": role.id})
        added.append(f"{emoji}:{role.name}")

    save_data(rr_data)

    if added:
        await interaction.response.send_message("追加: " + ", ".join(added), ephemeral=True)
    else:
        await interaction.response.send_message("追加できませんでした。", ephemeral=True)


# ============================================================
#  Y2 削除
# ============================================================
@app_commands.default_permissions(administrator=True)
@app_commands.command(
    name="y2_リアクションロール削除",
    description="既存メッセージから絵文字 or 絵文字:ロール を削除（管理者のみ）"
)
@app_commands.describe(
    メッセージ="メッセージID または リンク",
    削除一覧="例: 😀, 🔥:VIP"
)
async def y2(interaction, メッセージ: str, 削除一覧: str):

    if not is_admin(interaction):
        return await interaction.response.send_message("管理者のみ実行できます。", ephemeral=True)

    try:
        msg = await fetch_msg(interaction, メッセージ)
    except Exception as e:
        return await interaction.response.send_message(f"メッセージ取得失敗: {e}", ephemeral=True)

    key = str(msg.id)
    if key not in rr_data:
        return await interaction.response.send_message("未登録メッセージです。", ephemeral=True)

    targets = []
    for item in 削除一覧.split(","):
        targets.append(item.strip())

    before = len(rr_data[key]["items"])
    new_items = []

    for entry in rr_data[key]["items"]:
        emoji = entry["emoji"]
        role_id = entry["role_id"]

        remove_flag = False
        for t in targets:
            if ":" in t:
                e, r = t.split(":", 1)
                r_obj = await resolve_role(interaction.guild, r)
                if e == emoji and r_obj and r_obj.id == role_id:
                    remove_flag = True
            else:
                if t == emoji:
                    remove_flag = True

        if not remove_flag:
            new_items.append(entry)

    rr_data[key]["items"] = new_items
    save_data(rr_data)

    removed = before - len(new_items)
    await interaction.response.send_message(f"{removed} 件削除しました。", ephemeral=True)


# ============================================================
#  Y3本文編集
# ============================================================
@app_commands.default_permissions(administrator=True)
@app_commands.command(
    name="y3_リアクションロール本文編集",
    description="リアクションロールの本文を編集（管理者のみ）"
)
@app_commands.describe(
    メッセージ="メッセージID または リンク"
)
async def y3(interaction, メッセージ: str):

    if not is_admin(interaction):
        return await interaction.response.send_message("管理者のみ実行できます。", ephemeral=True)

    try:
        msg = await fetch_msg(interaction, メッセージ)
    except Exception as e:
        return await interaction.response.send_message(f"メッセージ取得失敗: {e}", ephemeral=True)

    key = str(msg.id)
    if key not in rr_data:
        return await interaction.response.send_message("未登録メッセージです。", ephemeral=True)

    async def submit(inter, body_text):
        embed = discord.Embed(description=body_text, color=discord.Color.gold())
        await msg.edit(embed=embed)
        rr_data[key]["body"] = body_text
        save_data(rr_data)
        await inter.followup.send("本文を更新しました。", ephemeral=True)

    await interaction.response.send_modal(BodyModal(submit))


# ============================================================
#  リアクション付与 → ロール付与 / 削除
# ============================================================
@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    entry = rr_data.get(str(payload.message_id))
    if not entry:
        return

    guild = bot.get_guild(payload.guild_id)
    member = guild.get_member(payload.user_id)
    if member.bot:
        return

    emoji = str(payload.emoji)
    target = [i for i in entry["items"] if i["emoji"] == emoji]
    if not target:
        return

    roles_to_add = [guild.get_role(i["role_id"]) for i in target]

    # 単一選択時は他ロールを外す
    if not entry["multiple"]:
        others = [i["role_id"] for i in entry["items"] if i["emoji"] != emoji]
        for rid in others:
            r = guild.get_role(rid)
            if r in member.roles:
                await member.remove_roles(r)

    for r in roles_to_add:
        if r and r not in member.roles:
            await member.add_roles(r)


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    entry = rr_data.get(str(payload.message_id))
    if not entry:
        return

    guild = bot.get_guild(payload.guild_id)
    member = guild.get_member(payload.user_id)
    if member.bot:
        return

    emoji = str(payload.emoji)
    target = [i for i in entry["items"] if i["emoji"] == emoji]

    for i in target:
        role = guild.get_role(i["role_id"])
        if role in member.roles:
            await member.remove_roles(role)


# ============================================================
#  起動
# ============================================================
@bot.event
async def on_ready():
    await bot.tree.sync()
    print("スラッシュコマンド同期完了")
    print(f"ログイン: {bot.user}")

keep_alive()
bot.run(os.getenv("TOKEN"))
