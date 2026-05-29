import discord
import wavelink
import random
import asyncio
import os
import sqlite3
import json

from openai import OpenAI
from groq import Groq
from dotenv import load_dotenv
from duckduckgo_search import DDGS
from discord.ext import commands

load_dotenv()

# =========================
# ENV
# =========================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

GROK_API_KEY = os.getenv("GROK_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

GROK_MODEL = os.getenv("GROK_MODEL", "grok-2-latest")

LAVALINK_HOST = os.getenv("LAVALINK_HOST", "lavalink.railway.internal")
LAVALINK_PORT = int(os.getenv("LAVALINK_PORT", "2333"))
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD", "evabotsenha")

# =========================
# CLIENTS
# =========================

grok = OpenAI(
    api_key=GROK_API_KEY,
    base_url="https://api.x.ai/v1"
)

groq = Groq(api_key=GROQ_API_KEY)

# =========================
# DISCORD
# =========================

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="eva/", intents=intents)

_ready = False

# =========================
# DB
# =========================

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

# =========================
# PERSONALITY
# =========================

PERSONALITY = """
Você é Eva.
Respostas curtas, frias, sarcásticas, Discord vibe.
Nunca seja assistente.
"""

# =========================
# STATE
# =========================

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

# =========================
# MEMORY
# =========================

def save_memory(uid, role, text):
    try:
        cursor.execute("INSERT INTO user_memory VALUES (?,?,?)",
                       (str(uid), role, text))
        conn.commit()
    except:
        pass

def load_memory(uid):
    try:
        cursor.execute("""
        SELECT role, content FROM user_memory
        WHERE user_id=?
        ORDER BY ROWID DESC LIMIT 10
        """, (str(uid),))
        return list(reversed(cursor.fetchall()))
    except:
        return []

# =========================
# SEARCH
# =========================

def ddg(query):
    try:
        with DDGS() as d:
            res = list(d.text(query, max_results=3))
        return "\n".join([f"{r['title']}: {r['body']}" for r in res])
    except:
        return ""

# =========================
# GROK (FIXED FALLBACK)
# =========================

async def grok_answer(uid, text, context):
    state = get_state()
    memory = load_memory(uid)

    messages = [{
        "role": "system",
        "content": f"{PERSONALITY}\nSTATE:{state}\nCTX:{context}"
    }]

    for r, c in memory:
        messages.append({"role": r, "content": c})

    messages.append({"role": "user", "content": text})

    models = [GROK_MODEL, "grok-beta", "grok-2"]

    for model in models:
        try:
            r = await asyncio.to_thread(
                lambda: grok.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=1,
                    max_tokens=140
                )
            )
            return r.choices[0].message.content.strip()
        except:
            continue

    return None

# =========================
# FALLBACK
# =========================

async def fallback(text):
    try:
        r = await asyncio.to_thread(
            lambda: groq.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role":"user","content":text}]
            )
        )
        return r.choices[0].message.content.strip()
    except:
        return "..."

# =========================
# GENERATE PIPELINE
# =========================

async def generate(uid, text):
    context = ""

    if "buscar" in text or "?" in text:
        context = ddg(text)

    resp = await grok_answer(uid, text, context)

    if not resp:
        resp = await fallback(text)

    save_memory(uid, "user", text)
    save_memory(uid, "assistant", resp)

    return resp

# =========================
# LAVALINK
# =========================

async def ensure_pool():
    try:
        if not wavelink.Pool.nodes:
            node = wavelink.Node(
                uri=f"http://{LAVALINK_HOST}:{LAVALINK_PORT}",
                password=LAVALINK_PASSWORD
            )
            await wavelink.Pool.connect(nodes=[node], client=bot)
    except:
        pass

# =========================
# MUSIC FIXED
# =========================

@bot.command()
async def play(ctx, *, search: str):
    if not ctx.author.voice:
        await ctx.send("entra na call")
        return

    channel = ctx.author.voice.channel
    player = ctx.voice_client

    try:
        await ensure_pool()

        if player and player.is_connected():
            try:
                await player.disconnect(force=True)
            except:
                pass

        player = await channel.connect(
            cls=wavelink.Player,
            timeout=60,
            reconnect=True,
            self_deaf=True
        )

        await ctx.send("buscando...")

        tracks = await wavelink.Playable.search(search)

        if not tracks:
            await ctx.send("n achei")
            return

        await player.play(tracks[0])
        await ctx.send(f"tocando: {tracks[0].title}")

    except Exception:
        await ctx.send("erro música")

@bot.command()
async def stop(ctx):
    vc = ctx.voice_client
    if vc:
        await vc.disconnect()

@bot.command()
async def skip(ctx):
    vc = ctx.voice_client
    if vc:
        await vc.stop()

# =========================
# READY
# =========================

@bot.event
async def on_ready():
    global _ready
    if _ready:
        return
    _ready = True

    try:
        node = wavelink.Node(
            uri=f"http://{LAVALINK_HOST}:{LAVALINK_PORT}",
            password=LAVALINK_PASSWORD
        )
        await wavelink.Pool.connect(nodes=[node], client=bot)
    except:
        pass

# =========================
# MESSAGE HANDLER
# =========================

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    await bot.process_commands(message)

    text = message.content

    if not (text.startswith("eva/") or bot.user in message.mentions):
        return

    clean = text.replace("eva/", "").replace(f"<@{bot.user.id}>", "").strip()

    async with message.channel.typing():
        resp = await generate(message.author.id, clean)

    await message.reply(resp)

# =========================
# RUN
# =========================

if DISCORD_TOKEN:
    bot.run(DISCORD_TOKEN)