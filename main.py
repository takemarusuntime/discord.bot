import os
import json
import discord
from discord import app_commands
from discord.ext import commands
from keep_alive import keep_alive


# ============================================================
#  BOT 基本設定（INTENTS）
# ============================================================
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

DATA_FILE = "reaction_roles.json"



# ============================================================
#  JSON 読み書き
# ============================================================
def load_json():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False)

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data):
    temp = DATA_FILE + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    os.replace(temp, DATA_FILE)


rr_data = load_json()



# ============================================================
#  ユーティリティ
# ============================================================
def is_admin(inter):
    return inter.user.guild_permissions.administrator


def parse_pairs(text):
    """絵文字:ロール のペアを分解"""
    results = []
    for chunk in text.split(","):
        chunk = chunk.strip()
        if ":" not in chunk:
            raise ValueError(f"形式エラー: {chunk}（絵文字:ロール）形式で指定してください")
        emoji, role = chunk.split(":", 1)
        results.append((emoji.strip(), role.strip()))
    return results


async def resolve_role(guild, value):
    """ロール（名前 / ID / メンション）を Role に変換"""
    value = value.strip()

    # メンション <@&ID>
    if value.startswith("<@&") and value.endswith(">"):
        rid = int(value[3:-1])
        return guild.get_role(rid)

    # ID
    if value.isdigit():
        return guild.get_role(int(value))

    # 名前
    return discord.utils.get(guild.roles, name=value)


async def fetch_message(interaction, ref):
    """メッセージID or メッセージリンク → Message"""
    ref = ref.strip()

    if "discord.com/channels" in ref:
        _, _, _, guild_id, channel_id, msg_id = ref.split("/")
        if int(guild_id) != interaction.guild.id:
            raise ValueError("このサーバーのメッセージではありません。")
        channel = interaction.guild.get_channel(int(channel_id))
        return await channel.fetch_message(int(msg_id))

    # ID の場合
    return await interaction.channel.fetch_message(int(ref))



# ============================================================
#  モーダル（本文入力）
# ============================================================
class BodyModal(discord.ui.Modal, title="本文を入力"):
    body = discord.ui.TextInput(label="本文", style=discord.TextStyle.paragraph)

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    async def on_submit(self, interaction):
        await self.callback(interaction, str(self.body))



# ============================================================
#  X1 新規リアクションロール
# ============================================================
@app_commands.default_permissions(administrator=True)
@app_commands.command(
    name="x1_リアクションロール設定",
    description="リアクションロールを新規作成（管理者のみ）"
)
@app_commands.describe(
    絵文字ロール一覧="例: 😀:@メンバー, 🔥:VIP",
    複数選択="true なら複数ロール付与を許可"
)
async def x1(inter, 絵文字ロール一覧: str, 複数選択: bool):

    if not is_admin(inter):
        return await inter.response.send_message("管理者のみ実行できます。", ephemeral=True)

    try:
        pairs = parse_pairs(絵文字ロール一覧)
    except Exception as e:
        return await inter.response.send_message(str(e), ephemeral=True)

    # --- 本文入力モーダル ---
    async def submit(inter2, body_text):
        embed = discord.Embed(description=body_text, color=discord.Color.gold())
        msg = await inter2.channel.send(embed=embed)

        items = []
        for emoji, role_txt in pairs:
            role = await resolve_role(inter2.guild, role_txt)
            if role is None:
                return await inter2.followup.send(f"ロールが見つかりません: {role_txt}", ephemeral=True)

            await msg.add_reaction(emoji)
            items.append({"emoji": emoji, "role_id": role.id})

        rr_data[str(msg.id)] = {
            "channel_id": inter2.channel.id,
            "multiple": 複数選択,
            "body": body_text,
            "items": items
        }
        save_json(rr_data)

        await inter2.followup.send("設定しました。", ephemeral=True)

    await inter.response.send_modal(BodyModal(submit))



# ============================================================
#  Y1 追加
# ============================================================
@app_commands.default_permissions(administrator=True)
@app_commands.command(
    name="y1_リアクションロール追加",
    description="既存メッセージに絵文字:ロールを追加（管理者のみ）"
)
async def y1(inter, メッセージ: str, 追加一覧: str):

    if not is_admin(inter):
        return await inter.response.send_message("管理者のみ実行できます。", ephemeral=True)

    try:
        msg = await fetch_message(inter, メッセージ)
    except Exception as e:
        return await inter.response.send_message(f"取得失敗: {e}", ephemeral=True)

    key = str(msg.id)
    if key not in rr_data:
        return await inter.response.send_message("未登録メッセージです。", ephemeral=True)

    try:
        pairs = parse_pairs(追加一覧)
    except Exception as e:
        return await inter.response.send_message(str(e), ephemeral=True)

    added = []
    for emoji, role_txt in pairs:
        role = await resolve_role(inter.guild, role_txt)
        if role is None:
            continue

        await msg.add_reaction(emoji)
        rr_data[key]["items"].append({"emoji": emoji, "role_id": role.id})
        added.append(f"{emoji}:{role.name}")

    save_json(rr_data)

    if added:
        await inter.response.send_message("追加: " + ", ".join(added), ephemeral=True)
    else:
        await inter.response.send_message("追加できませんでした。", ephemeral=True)



# ============================================================
#  Y2 削除
# ============================================================
@app_commands.default_permissions(administrator=True)
@app_commands.command(
    name="y2_リアクションロール削除",
    description="絵文字 または 絵文字:ロール を削除（管理者のみ）"
)
async def y2(inter, メッセージ: str, 削除一覧: str):

    if not is_admin(inter):
        return await inter.response.send_message("管理者のみ実行できます。", ephemeral=True)

    try:
        msg = await fetch_message(inter, メッセージ)
    except Exception as e:
        return await inter.response.send_message(f"取得失敗: {e}", ephemeral=True)

    key = str(msg.id)
    if key not in rr_data:
        return await inter.response.send_message("未登録メッセージです。", ephemeral=True)

    targets = [x.strip() for x in 削除一覧.split(",")]

    before = len(rr_data[key]["items"])
    new_items = []

    for item in rr_data[key]["items"]:
        emoji = item["emoji"]
        rid = item["role_id"]

        remove = False
        for t in targets:
            if ":" in t:
                e, rtxt = t.split(":", 1)
                r = await resolve_role(inter.guild, rtxt)
                if e == emoji and r and r.id == rid:
                    remove = True
            else:
                if t == emoji:
                    remove = True

        if not remove:
            new_items.append(item)

    rr_data[key]["items"] = new_items
    save_json(rr_data)

    removed = before - len(new_items)
    await inter.response.send_message(f"{removed} 件削除しました。", ephemeral=True)



# ============================================================
#  Y3 本文編集
# ============================================================
@app_commands.default_permissions(administrator=True)
@app_commands.command(
    name="y3_リアクションロール本文編集",
    description="リアクションロール本文を変更（管理者のみ）"
)
async def y3(inter, メッセージ: str):

    if not is_admin(inter):
        return await inter.response.send_message("管理者のみ実行できます。", ephemeral=True)

    try:
        msg = await fetch_message(inter, メッセージ)
    except Exception as e:
        return await inter.response.send_message(f"取得失敗: {e}", ephemeral=True)

    key = str(msg.id)
    if key not in rr_data:
        return await inter.response.send_message("未登録メッセージです。", ephemeral=True)

    async def submit(inter2, text):
        embed = discord.Embed(description=text, color=discord.Color.gold())
        await msg.edit(embed=embed)

        rr_data[key]["body"] = text
        save_json(rr_data)

        await inter2.followup.send("本文を更新しました。", ephemeral=True)

    await inter.response.send_modal(BodyModal(submit))



# ============================================================
#  リアクション → ロール付与 / 剥奪
# ============================================================
@bot.event
async def on_raw_reaction_add(payload):
    entry = rr_data.get(str(payload.message_id))
    if not entry:
        return

    guild = bot.get_guild(payload.guild_id)
    member = guild.get_member(payload.user_id)
    if member.bot:
        return

    emoji = str(payload.emoji)
    matched = [i for i in entry["items"] if i["emoji"] == emoji]

    if not matched:
        return

    # 単一選択 → 他ロール削除
    if not entry["multiple"]:
        others = [i["role_id"] for i in entry["items"] if i["emoji"] != emoji]
        for rid in others:
            r = guild.get_role(rid)
            if r in member.roles:
                await member.remove_roles(r)

    # ロール付与
    for item in matched:
        role = guild.get_role(item["role_id"])
        if role and role not in member.roles:
            await member.add_roles(role)



@bot.event
async def on_raw_reaction_remove(payload):
    entry = rr_data.get(str(payload.message_id))
    if not entry:
        return

    guild = bot.get_guild(payload.guild_id)
    member = guild.get_member(payload.user_id)

    if member.bot:
        return

    emoji = str(payload.emoji)
    matched = [i for i in entry["items"] if i["emoji"] == emoji]

    for item in matched:
        role = guild.get_role(item["role_id"])
        if role in member.roles:
            await member.remove_roles(role)



# ============================================================
#  起動
# ============================================================
@bot.event
async def on_ready():
    await bot.tree.sync()
    print("コマンド同期完了")
    print(f"ログイン: {bot.user}")


keep_alive()

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("環境変数 DISCORD_TOKEN が設定されていません")

bot.run(TOKEN)
