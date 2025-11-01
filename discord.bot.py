import discord
from discord import app_commands
from discord.ext import commands
import asyncio
from datetime import datetime, timedelta, timezone
from keep_alive import keep_alive
import re

# ===== Bot設定 =====
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
JST = timezone(timedelta(hours=9))
reminders = {}


# -------------------- リマインド --------------------
@bot.tree.command(name="リマインド", description="指定した時間または○分後にリマインドを送ります（日本時間）")
@app_commands.describe(
    時間または分後="「21:30」または「15」など（分後指定もOK）",
    メッセージ="リマインド内容"
)
async def remind(interaction: discord.Interaction, 時間または分後: str, メッセージ: str):
    now = datetime.now(JST)
    remind_time = None
    wait_seconds = None

    # --- 「○分後」指定を判定 ---
    if re.fullmatch(r"\d+", 時間または分後):
        minutes = int(時間または分後)
        if minutes <= 0:
            await interaction.response.send_message("分後の指定は1以上で入力してください。", ephemeral=True)
            return
        remind_time = now + timedelta(minutes=minutes)
        wait_seconds = minutes * 60
        time_text = f"{minutes}分後（{remind_time.strftime('%H:%M')}ごろ）"

    # --- 「HH:MM」形式を判定 ---
    elif re.fullmatch(r"\d{1,2}:\d{2}", 時間または分後):
        try:
            target = datetime.strptime(時間または分後, "%H:%M").replace(
                year=now.year, month=now.month, day=now.day, tzinfo=JST
            )
            if target < now:
                target += timedelta(days=1)
            remind_time = target
            wait_seconds = (remind_time - now).total_seconds()
            time_text = remind_time.strftime("%H:%M")
        except ValueError:
            await interaction.response.send_message("時間は 00:00～23:59 の形式で入力してください。", ephemeral=True)
            return
    else:
        await interaction.response.send_message("時間は「HH:MM」または「○分後」で指定してください。", ephemeral=True)
        return

    # --- リマインドID作成 ---
    remind_id = f"{interaction.user.id}-{remind_time.strftime('%Y%m%d%H%M%S')}"

    # --- 実際のリマインド処理 ---
    async def remind_task():
        await asyncio.sleep(wait_seconds)
        embed = discord.Embed(
            title="⏰ リマインド",
            description=メッセージ,
            color=discord.Color.blurple(),
            timestamp=datetime.now(JST)
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        await interaction.channel.send(embed=embed)
        reminders.pop(remind_id, None)

    task = asyncio.create_task(remind_task())
    reminders[remind_id] = {"task": task, "time": remind_time, "message": メッセージ}

    view = CancelButton(interaction.user.id, remind_id)
    await interaction.response.send_message(
        f"✅ リマインドを設定しました！\n**{time_text}** に以下の内容をお知らせします：\n> {メッセージ}",
        view=view,
        ephemeral=True
    )

# --- 削除ボタン ---
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



# -------------------- 起動時処理 --------------------
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ ログイン完了: {bot.user}")

keep_alive()
bot.run("DISCORD_TOKEN")