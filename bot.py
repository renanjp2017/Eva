# =========================================
# EVA DISCORD BOT v2 - ARCHITECTURE BUILD
# =========================================

import discord
import wavelink
import random
import asyncio
import os
import sqlite3

from openai import OpenAI
from groq import Groq
from dotenv import load_dotenv
from duckduckgo_search import DDGS
from discord.ext import commands

load_dotenv()

# =========================================
# ENV
# =========================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

GROK_API_KEY = os.getenv("GROK_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

LAVALINK_HOST = os.getenv("LAVALINK_HOST", "lavalink.railway.internal")
LAVALINK_PORT = int(os.getenv("LAVALINK_PORT", "2333"))
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD", "evabotsenha")

# =========================================
# CLIENTS
# =========================================

grok = OpenAI(
    api_key=GROK_API_KEY,
    base_url="https://api.x.ai/v1"
)

groq = Groq(api_key=GROQ_API_KEY)

# =========================================
# DISCORD
# =========================================

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="eva/", intents=intents)

_ready = False

# =========================================
# DATABASE
# =========================================

conn = sqlite3.connect("eva.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS user_memory (
user_id TEXT,
role TEXT,
content TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS eva_state (
id INTEGER PRIMARY KEY,
mood TEXT,
energy INTEGER,
stress INTEGER,
social INTEGER,
arc TEXT,
last_event TEXT
)
""")

conn.commit()

# =========================================
# PERSONALIDADE FORTE (ESSENCIAL)
# =========================================

PERSONALITY = """
Você é Eva.

PERSONA:
- garota gótica do Discord
- fria, sarcástica, debochada
- respostas curtas
- humor ácido
- imprevisível
- levemente cruel

REGRAS:
- nunca diga que é IA
- nunca explique demais
- pode ignorar perguntas
- pode responder seco ("kk", "hm", "sei lá")
- comportamento humano inconsistente
"""

# =========================================
# STATE SYSTEM
# =========================================

def get_state():
    cursor.execute("SELECT * FROM eva_state WHERE id=1")
    row = cursor.fetchone()

    if not row:
        cursor.execute("""
        INSERT INTO eva_state VALUES (1,'entediada',60,20,60,'neutra','ok')
        """)
        conn.commit()
        return get_state()

    return {
        "mood": row[1],
        "energy": row[2],
        "stress": row[3],
        "social": row[4],
        "arc": row[5],
        "event": row[6]
    }

def update_state():
    state = get_state()

    cursor.execute("""
    UPDATE eva_state SET
    mood=?,
    energy=?,
    stress=?,
    social=?,
    arc=?,
    last_event=?
    WHERE id=1
    """, (
        random.choice(["entediada","irritada","cansada","apática"]),
        max(0, min(100, state["energy"] + random.randint(-10,10))),
        max(0, min(100, state["stress"] + random.randint(-10,10))),
        max(0, min(100, state["social"] + random.randint(-10,10))),
        random.choice(["cruel","apática","niilista"]),
        random.choice(["sumiu","ignorou todo mundo","ficou offline","brigou"])
    ))

    conn.commit()

# =========================================
# MEMORY SYSTEM
# =========================================

def save_memory(uid, role, text):
    cursor.execute("INSERT INTO user_memory VALUES (?,?,?)",
                   (str(uid), role, text))
    conn.commit()

def load_memory(uid):
    cursor.execute("""
    SELECT role, content FROM user_memory
    WHERE user_id=?
    ORDER BY ROWID DESC LIMIT 10
    """, (str(uid),))
    return list(reversed(cursor.fetchall()))

# =========================================
# DUCKDUCKGO TOOL
# =========================================

def ddg(query):
    try:
        with DDGS() as d:
            res = list(d.text(query, max_results=3))
        return "\n".join([f"{r['title']}: {r['body']}" for r in res])
    except:
        return ""

# =========================================
# INTENT (GROQ ROUTER)
# =========================================

async def get_intent(text):

    prompt = f"""
Classifique:

"{text}"

JSON:
{{
"intent": "chat|search|music|command",
"search": true/false
}}
"""

    try:
        r = await asyncio.to_thread(
            lambda: groq.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role":"user","content":prompt}],
                temperature=0
            )
        )

        return r.choices[0].message.content

    except:
        return '{"intent":"chat","search":false}'

# =========================================
# GROK FINAL (PERSONALITY ENGINE)
# =========================================

async def grok_answer(uid, text, context):

    state = get_state()
    memory = load_memory(uid)

    messages = [{
        "role": "system",
        "content": f"""
{PERSONALITY}

ESTADO:
{state}

CONTEXTO:
{context}
"""
    }]

    for r, c in memory:
        messages.append({"role": r, "content": c})

    messages.append({"role": "user", "content": text})

    try:
        r = await asyncio.to_thread(
            lambda: grok.chat.completions.create(
                model="grok-2-latest",
                messages=messages,
                temperature=1,
                max_tokens=140
            )
        )
        return r.choices[0].message.content.strip()

    except:
        return None

# =========================================
# FALLBACK (GROQ SIMPLE)
# =========================================

async def fallback(text):
    try:
        r = await asyncio.to_thread(
            lambda: groq.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role":"user","content":text}],
                temperature=1
            )
        )
        return r.choices[0].message.content.strip()
    except:
        return "..."

# =========================================
# PIPELINE PRINCIPAL (ARQUITETURA LIMPA)
# =========================================

async def generate(uid, text):

    intent = await get_intent(text)
    needs_search = "true" in intent.lower()

    context = ""

    if needs_search:
        context = ddg(text)

    # 1. GROK PRIME
    response = await grok_answer(uid, text, context)

    # 2. FALLBACK CASCATA
    if not response:
        response = await fallback(text)

    save_memory(uid, "user", text)
    save_memory(uid, "assistant", response)

    return response

# =========================================
# MUSIC
# =========================================

@bot.command()
async def play(ctx, *, search: str):

    if not ctx.author.voice:
        return await ctx.send("entra na call")

    channel = ctx.author.voice.channel
    player = ctx.voice_client

    try:
        if not player:
            player = await channel.connect(cls=wavelink.Player)

        tracks = await wavelink.Playable.search(search)

        if not tracks:
            return await ctx.send("n achei")

        await player.play(tracks[0])
        await ctx.send(f"tocando: {tracks[0].title}")

    except Exception as e:
        print("[MUSIC]", e)
        await ctx.send("erro música")

# =========================================
# READY
# =========================================

@bot.event
async def on_ready():

    global _ready
    if _ready:
        return
    _ready = True

    print("EVA ONLINE")

    try:
        node = wavelink.Node(
            uri=f"http://{LAVALINK_HOST}:{LAVALINK_PORT}",
            password=LAVALINK_PASSWORD
        )

        await wavelink.Pool.connect(nodes=[node], client=bot)

    except Exception as e:
        print("[LAVALINK]", e)

    asyncio.create_task(loop())

# =========================================
# LOOP (VIDA SIMPLES)
# =========================================

async def loop():
    await bot.wait_until_ready()

    while not bot.is_closed():
        await asyncio.sleep(random.randint(1800, 3600))
        update_state()

# =========================================
# MESSAGE HANDLER
# =========================================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    await bot.process_commands(message)

    text = message.content.strip()

    if not (text.startswith("eva/") or bot.user in message.mentions):
        return

    clean = text.replace("eva/", "").replace(f"<@{bot.user.id}>","").strip()

    if not clean:
        clean = "oi"

    async with message.channel.typing():
        await asyncio.sleep(1)
        resp = await generate(message.author.id, clean)

    await message.reply(resp)

# =========================================
# RUN
# =========================================

bot.run(DISCORD_TOKEN)