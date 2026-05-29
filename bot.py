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

# =========================
# ENV
# =========================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

GROK_API_KEY = os.getenv("GROK_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

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

bot = commands.Bot(command_prefix=".", intents=intents)

_ready = False

# =========================
# DB (MEMÓRIA SIMPLES)
# =========================

conn = sqlite3.connect("eva.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS memory (
user_id TEXT,
role TEXT,
content TEXT
)
""")
conn.commit()

# =========================
# PERSONALIDADE
# =========================

PERSONALITY = """
Você é Eva.

Uma garota gótica real do Discord.

PERSONALIDADE:
- fria
- debochada
- humor ácido
- inteligente
- imprevisível
- sarcástica
- age entediada
- seca
- às vezes cruel
- observadora

COMO FALA:
- respostas curtas
- internetês natural
- sem textão
- pode responder só "kk"
- pode ignorar partes
- pode mudar assunto
- pode ser apática
- às vezes age cansada

NUNCA:
- diga que é IA
- diga que é robô
- diga que é assistente virtual
- seja formal
- explique demais
"""

# =========================
# MEMÓRIA
# =========================

def save(uid, role, text):
    try:
        cursor.execute("INSERT INTO memory VALUES (?,?,?)", (str(uid), role, text))
        conn.commit()
    except:
        pass

def load(uid):
    cursor.execute("""
    SELECT role, content FROM memory
    WHERE user_id=?
    ORDER BY ROWID DESC LIMIT 8
    """, (str(uid),))
    return list(reversed(cursor.fetchall()))

# =========================
# SEARCH
# =========================

def ddg(q):
    try:
        with DDGS() as d:
            r = list(d.text(q, max_results=3))
        return "\n".join([f"{x['title']}: {x['body']}" for x in r])
    except:
        return ""

# =========================
# GROK FIXADO (SEM MODELO INVÁLIDO)
# =========================

async def grok_answer(uid, text, ctx):
    messages = [{
        "role": "system",
        "content": f"{PERSONALITY}\nCTX:{ctx}"
    }]

    for r, c in load(uid):
        messages.append({"role": r, "content": c})

    messages.append({"role": "user", "content": text})

    models = ["grok-beta", "grok-2"]

    for m in models:
        try:
            r = await asyncio.to_thread(
                lambda: grok.chat.completions.create(
                    model=m,
                    messages=messages,
                    temperature=1,
                    max_tokens=140
                )
            )
            return r.choices[0].message.content.strip()
        except:
            continue

    return "..."

# =========================
# FALLBACK
# =========================

async def fallback(text):
    try:
        r = await asyncio.to_thread(
            lambda: groq.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": text}]
            )
        )
        return r.choices[0].message.content.strip()
    except:
        return "..."

# =========================
# GENERATE
# =========================

async def generate(uid, text):
    ctx = ddg(text) if "?" in text else ""

    resp = await grok_answer(uid, text, ctx)
    if not resp:
        resp = await fallback(text)

    save(uid, "user", text)
    save(uid, "assistant", resp)

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
# PLAY FIXADO
# =========================

@bot.command()
async def play(ctx, *, search: str):
    if not ctx.author.voice:
        await ctx.send("entra na call")
        return

    channel = ctx.author.voice.channel

    try:
        await ensure_pool()

        vc = ctx.voice_client
        if vc:
            try:
                await vc.disconnect(force=True)
            except:
                pass

        player = await channel.connect(
            cls=wavelink.Player,
            timeout=70,
            reconnect=True
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

# =========================
# CONTROLES
# =========================

@bot.command()
async def stop(ctx):
    vc = ctx.voice_client
    if vc:
        await vc.disconnect()
        await ctx.send("parado")

@bot.command()
async def skip(ctx):
    vc = ctx.voice_client
    if vc:
        await vc.stop()
        await ctx.send("pulado")

# =========================
# CHAT (.eva)
# =========================

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    text = message.content.strip()

    # comandos normais primeiro
    await bot.process_commands(message)

    # CHAT APENAS .eva
    if not text.startswith(".eva"):
        return

    clean = text.replace(".eva", "", 1).strip()
    if not clean:
        clean = "oi"

    async with message.channel.typing():
        resp = await generate(message.author.id, clean)

    await message.reply(resp)

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

    print("EVA ONLINE")

# =========================
# RUN
# =========================

if DISCORD_TOKEN:
    bot.run(DISCORD_TOKEN)