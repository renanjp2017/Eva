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
# DB
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
conn.commit()

# =========================================
# PERSONALIDADE
# =========================================

PERSONALIDADE = """
Você é Eva.
Fria, sarcástica, curta.
Nunca diga que é IA.
"""

# =========================================
# MEMORY
# =========================================

def save_memory(uid, role, content):
    cursor.execute("INSERT INTO user_memory VALUES (?,?,?)",
                   (str(uid), role, content))
    conn.commit()

def load_memory(uid):
    cursor.execute("""
    SELECT role, content FROM user_memory
    WHERE user_id=?
    ORDER BY ROWID DESC LIMIT 8
    """, (str(uid),))
    return list(reversed(cursor.fetchall()))

# =========================================
# DUCKDUCKGO TOOL
# =========================================

def ddg_search(q):
    try:
        with DDGS() as d:
            res = list(d.text(q, max_results=3))
        return "\n\n".join([f"{r['title']}: {r['body']}" for r in res])
    except:
        return ""

# =========================================
# INTENT ROUTER (GROQ)
# =========================================

async def get_intent(text):

    prompt = f"""
Classifique a mensagem:

Mensagem: {text}

Responda JSON:
{{
"intent": "chat|search|music|status|command",
"needs_search": true/false
}}
"""

    try:
        r = await asyncio.to_thread(
            lambda: groq.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )
        )

        return r.choices[0].message.content

    except:
        return '{"intent":"chat","needs_search":false}'

# =========================================
# GROK RESPONSE (PERSONALITY)
# =========================================

async def grok_reply(uid, text, context=""):

    messages = [
        {"role": "system", "content": PERSONALIDADE},
        {"role": "user", "content": f"{context}\n\n{text}"}
    ]

    try:
        r = await asyncio.to_thread(
            lambda: grok.chat.completions.create(
                model="grok-2-latest",
                messages=messages,
                temperature=1,
                max_tokens=120
            )
        )
        return r.choices[0].message.content.strip()

    except:
        return None

# =========================================
# FALLBACK GROQ CHAT
# =========================================

async def groq_fallback(text):

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
# MAIN AI PIPELINE
# =========================================

async def generate(uid, text):

    intent_raw = await get_intent(text)

    needs_search = "true" in intent_raw.lower()

    context = ""

    if needs_search:
        context = ddg_search(text)

    # GROK PRIMARY
    resp = await grok_reply(uid, text, context)

    # FALLBACK
    if not resp:
        resp = await groq_fallback(text)

    save_memory(uid, "user", text)
    save_memory(uid, "assistant", resp)

    return resp

# =========================================
# MUSIC (SAFE CONNECT)
# =========================================

@bot.command()
async def play(ctx, *, search: str):

    if not ctx.author.voice:
        return await ctx.send("entra na call")

    channel = ctx.author.voice.channel

    player = ctx.voice_client

    try:
        if not player:
            player = await asyncio.wait_for(
                channel.connect(cls=wavelink.Player),
                timeout=10
            )

        tracks = await wavelink.Playable.search(search)

        if not tracks:
            return await ctx.send("n achei")

        await player.play(tracks[0])
        await ctx.send(f"tocando: {tracks[0].title}")

    except Exception as e:
        print("[MUSIC ERROR]", e)
        await ctx.send("erro voice/lavalink")

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

    clean = text.replace("eva/", "").replace(f"<@{bot.user.id}>", "").strip()

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