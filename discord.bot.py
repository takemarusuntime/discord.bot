import discord, json, os, time, asyncio, random
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
from keep_alive import keep_alive

# === Bot設定 ===
intents = discord.Intents.default()
intents.message_content = intents.members = intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)

balances, voice_times, last_message_time = {}, {}, {}
BALANCES_FILE = "balances.json"
INTEREST_RATE = (1.5 ** (1/365)) - 1  # 年利50%を日利換算

# === データ管理 ===
def save_data():
    tmp=BALANCES_FILE+".tmp"
    with open(tmp,"w",encoding="utf-8") as f: json.dump(balances,f,ensure_ascii=False,indent=4)
    os.replace(tmp,BALANCES_FILE)
def load_data():
    global balances
    if os.path.exists(BALANCES_FILE):
        try: balances.update(json.load(open(BALANCES_FILE,"r",encoding="utf-8")))
        except: balances.clear(); print("⚠️balances.json破損→再生成")
def ensure_account(uid):
    if uid not in balances:
        balances[uid]={"wallet":0,"bank":10000,"coin":0,"last_interest":str(datetime.utcnow().date()),
                       "items":{"large":0,"medium":0,"small":0}}

# === 報酬・利息 ===
@bot.event
async def on_message(m):
    if m.author.bot:return
    uid=str(m.author.id); ensure_account(uid)
    if uid in last_message_time and time.time()-last_message_time[uid]<5:return await bot.process_commands(m)
    last_message_time[uid]=time.time()
    if len(m.content.strip())>=3: balances[uid]["bank"]+=len(m.content)//3; save_data()
    await bot.process_commands(m)
@bot.event
async def on_voice_state_update(mem,b,a):
    uid=str(mem.id); ensure_account(uid)
    if b.channel is None and a.channel: voice_times[uid]=datetime.utcnow()
    elif b.channel and not a.channel and uid in voice_times:
        mins=int((datetime.utcnow()-voice_times.pop(uid)).total_seconds()//60)
        if mins>0: balances[uid]["bank"]+=mins; save_data()
@tasks.loop(hours=24)
async def apply_interest():
    jst=timezone(timedelta(hours=9));today=datetime.now(jst).date()
    for uid,d in balances.items():
        ensure_account(uid);last=datetime.strptime(d.get("last_interest",str(today)),"%Y-%m-%d").date()
        for _ in range((today-last).days): d["bank"]=round(d["bank"]*(1+INTEREST_RATE),2)
        d["last_interest"]=str(today)
    save_data();print(f"💰{today}利息反映（日利{INTEREST_RATE*100:.4f}%）")

# === おみくじ ===
@bot.tree.command(name="おみくじ",description="今日の運勢を占います！")
async def omikuji(i):
    uid=str(i.user.id); ensure_account(uid)
    res_w=[("大大大吉",1),("大大吉",3),("大吉",9),("吉",10),("中吉",20),("小吉",15),("末吉",20),("凶",10),("大凶",6),("大大凶",3),("大大大凶",1),
           ("ﾎﾟｷｭｰｰﾝ!! 鬼がかりBONUS3000",0.5),("ﾍﾟｶｯ!!BIGBONUS",1.5)]
    res=random.choices([r[0] for r in res_w],weights=[r[1] for r in res_w])[0]
    bonus=3000 if "鬼がかり" in res else 300 if "BIG" in res else 0
    if bonus: balances[uid]["wallet"]+=bonus; save_data()
    await i.response.send_message(f"🎴**{i.user.display_name}の運勢！**\n✨{res}✨"+(f"\n💥{bonus}G獲得！" if bonus else ""),ephemeral=True)

# === bankグループ ===
bank=discord.app_commands.Group(name="bank",description="銀行関連")

# --- 残高確認 ---
@bank.command(name="残高確認", description="残高を確認します")
async def bal(i):
    uid = str(i.user.id)
    ensure_account(uid)
    w, b = balances[uid]["wallet"], balances[uid]["bank"]
    await i.response.send_message(f"👛{i.user.display_name}の残高\n所持:{w}G 預金:{b}G", ephemeral=True)

# --- 送金 ---
@bank.command(name="送金",description="他人に送金")
async def pay(i,user:discord.User,amt:int):
    s,r=str(i.user.id),str(user.id);ensure_account(s);ensure_account(r)
    if amt<=0:return await i.response.send_message("⚠️1以上指定",ephemeral=True)
    if s==r:return await i.response.send_message("🤔自分送金不可",ephemeral=True)
    if balances[s]["wallet"]<amt:return await i.response.send_message("💸不足",ephemeral=True)
    balances[s]["wallet"]-=amt;balances[r]["wallet"]+=amt;save_data()
    await i.response.send_message(f"{i.user.mention}➡{user.mention}に{amt}G送金",ephemeral=True)

# --- 預け入れ ---
@bank.command(name="預け入れ",description="銀行に預けます")
async def dep(i,amt:int):
    uid=str(i.user.id);ensure_account(uid)
    if amt<=0 or balances[uid]["wallet"]<amt:return await i.response.send_message("⚠️残高不足",ephemeral=True)
    balances[uid]["wallet"]-=amt;balances[uid]["bank"]+=amt;save_data()
    await i.response.send_message(f"🏦{amt}G預入\n👛{balances[uid]['wallet']}G/💰{balances[uid]['bank']}G",ephemeral=True)

# --- 引き出し ---
@bank.command(name="引き出し",description="銀行から引き出します")
async def wd(i,amt:int):
    uid=str(i.user.id);ensure_account(uid)
    if amt<=0 or balances[uid]["bank"]<amt:return await i.response.send_message("⚠️残高不足",ephemeral=True)
    balances[uid]["bank"]-=amt;balances[uid]["wallet"]+=amt;save_data()
    await i.response.send_message(f"💵{amt}G引出\n👛{balances[uid]['wallet']}G/💰{balances[uid]['bank']}G",ephemeral=True)
bot.tree.add_command(bank)

# === casinoグループ ===
casino=discord.app_commands.Group(name="casino",description="カジノ")

# --- Coin貸し出し ---
@casino.command(name="coin貸し出し",description="20Gで1Coinを購入")
async def loan(i,coin数:int):
    uid=str(i.user.id);ensure_account(uid)
    cost=coin数*20
    if coin数<=0 or balances[uid]["wallet"]<cost:return await i.response.send_message("💸G不足",ephemeral=True)
    balances[uid]["wallet"]-=cost;balances[uid]["coin"]+=coin数;save_data()
    await i.response.send_message(f"🎟️{coin数}Coin貸出(-{cost}G)",ephemeral=True)

# --- カウンター ---
@casino.command(name="カウンター",description="Coinを景品に交換（💴275/💵55/💶11）")
async def counter(i,coin数:int):
    uid=str(i.user.id);ensure_account(uid);u=balances[uid]
    if coin数<11:return await i.response.send_message("⚠️11Coin以上から",ephemeral=True)
    if u["coin"]<coin数:return await i.response.send_message("🪙Coin不足",ephemeral=True)
    L,rem=coin数//275,coin数%275;M,rem=rem//55,rem%55;S,rem=rem//11,rem%11
    used=L*275+M*55+S*11;u["coin"]-=used
    u["items"]["large"]+=L;u["items"]["medium"]+=M;u["items"]["small"]+=S
    txt=[]
    if L:txt.append(f"💴大景品×{L}")
    if M:txt.append(f"💵中景品×{M}")
    if S:txt.append(f"💶小景品×{S}")
    if not txt:return await i.response.send_message("⚠️交換不可",ephemeral=True)
    refund=f"\n🔁余りCoin({rem})返却しました" if rem>0 else ""
    if rem>0:u["coin"]+=rem
    save_data()
    await i.response.send_message(f"🎁**{i.user.display_name}のカウンター交換結果**\n"+"\n".join(txt)+
    f"\n🪙使用:{used}枚 残:{u['coin']}枚{refund}",ephemeral=True)

# --- 景品交換所 ---
@casino.command(name="景品交換所",description="所持している景品をGに交換します（💴5000/💵1000/💶200）")
async def exchange_items(i):
    uid=str(i.user.id);ensure_account(uid);u=balances[uid];items=u["items"]
    L,M,S=items["large"],items["medium"],items["small"]
    if L+M+S==0:return await i.response.send_message("🎁交換できる景品を持っていません。",ephemeral=True)
    L_t,M_t,S_t=L*5000,M*1000,S*200;total=L_t+M_t+S_t
    u["wallet"]+=total;u["items"]={"large":0,"medium":0,"small":0};save_data()
    det=[]
    if L:det.append(f"💴大景品×{L} → {L_t}G")
    if M:det.append(f"💵中景品×{M} → {M_t}G")
    if S:det.append(f"💶小景品×{S} → {S_t}G")
    await i.response.send_message(f"💱**{i.user.display_name}の景品交換結果**\n"+"\n".join(det)+
    f"\n💰合計{total}Gをウォレットに加算！\n👛現在:{u['wallet']}G",ephemeral=True)

# --- スロット ---
@casino.command(name="スロット",description="3Coinで1回転！縦リール演出！")
async def slot(i):
    uid=str(i.user.id);ensure_account(uid);u=balances[uid]
    b=u.get("bonus_spins",0);f=u.get("free_spin",False)
    if f:u["free_spin"]=False
    elif u["coin"]<3:return await i.response.send_message("🪙不足(3Coin必要)",ephemeral=True)
    else:u["coin"]-=3
    m=await i.response.send_message("🎰スロット始動…",ephemeral=True);await asyncio.sleep(0.1)
    s=["🔔","🫒","🔵","🍒","🤡","🔶","💷"];roll=random.randint(1,1000)
    F=[[""]*3 for _ in range(3)];pay=0;text=""
    if b>0:F=[["🔔"]*3 for _ in range(3)];pay,text=15,"+15枚";u["bonus_spins"]-=1
    else:
        if roll<=1:F=[["🤡"]*3 for _ in range(3)];pay,text=10,"+10枚"
        elif roll<=5:F=[["🔶"]*3 for _ in range(3)];pay,u["bonus_spins"],text=3,30,"+3枚(BIG)"
        elif roll<=9:F=[["🔶","🔶","💷"] for _ in range(3)];pay,u["bonus_spins"],text=3,15,"+3枚(REG)"
        elif roll<=50:F=[["🔔"]*3 for _ in range(3)];pay,text=15,"+15枚"
        elif roll<=217:F=[["🫒"]*3 for _ in range(3)];pay,text=8,"+8枚"
        elif roll<=360:F=[["🔵"]*3 for _ in range(3)];u["free_spin"],text=True,"FREE SPIN!"
        else:F=[[random.choice(s) for _ in range(3)] for _ in range(3)]
    u["coin"]+=pay;save_data()
    for _ in range(6):
        frame="\n".join(" ".join(random.choice(s) for _ in range(3)) for _ in range(3))
        await m.edit(content=f"🎰リール回転中…\n{frame}");await asyncio.sleep(0.05)
    D=[[random.choice(s) for _ in range(3)] for _ in range(3)]
    for c in range(3):
        for r in range(3):D[r][c]=F[r][c]
        await m.edit(content=f"🎰リール回転中…\n"+"\n".join(" ".join(x) for x in D))
        await asyncio.sleep(0.25+c*0.15)
    disp="\n".join(" ".join(r) for r in F)
    v=discord.ui.View();v.add_item(discord.ui.Button(label="もう1回回す",style=discord.ButtonStyle.primary,custom_id="slot_retry"))
    await m.edit(content=f"🎰**{i.user.display_name}のスロット結果！**\n{disp}\n{text}\n🪙{u['coin']}枚",view=v)
@bot.event
async def on_interaction(i):
    if i.type==discord.InteractionType.component and i.data.get("custom_id")=="slot_retry":await slot(i)
bot.tree.add_command(casino)

# === 起動 ===
@bot.event
async def on_disconnect():save_data()
load_data()
@bot.event
async def on_ready():await bot.tree.sync();apply_interest.start();print(f"✅ログイン:{bot.user}")
keep_alive();bot.run(os.environ["DISCORD_TOKEN"])
