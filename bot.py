# =========================================
# EVA DISCORD BOT - STABLE BUILD
# =========================================

import discord
import wavelink
import random
import asyncio
import os
import sqlite3
import requests

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

CANAL_PENSAMENTOS = int(os.getenv("CANAL_PENSAMENTOS", "0"))

LAVALINK_HOST = os.getenv("LAVALINK_HOST", "lavalink.railway.internal")
LAVALINK_PORT = int(os.getenv("LAVALINK_PORT", "2333"))
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD", "evabotsenha")

# =========================================
# IA CLIENTS
# =========================================

grok = OpenAI(
    api_key=GROK_API_KEY,
    base_url="https://api.x.ai/v1"
)

groq_client = Groq(api_key=GROQ_API_KEY)

# =========================================
# DISCORD SETUP
# =========================================

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="eva/", intents=intents)

# =========================================
# STATE FLAGS
# =========================================

_ready_once = False

# =========================================
# DATABASE SAFE
# =========================================

conn = sqlite3.connect("eva.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS eva_state (
    id INTEGER PRIMARY KEY,
    mood TEXT,
    energy INTEGER,
    social_battery INTEGER,
    stress INTEGER,
    obsession TEXT,
    current_arc TEXT,
    last_event TEXT
)
""")

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
Fria, debochada, sarcástica, curta nas respostas.
Nunca diga que é IA.
Nunca explique demais.
"""

# =========================================
# STATE
# =========================================

def pegar_estado():
    cursor.execute("SELECT * FROM eva_state WHERE id = 1")
    estado = cursor.fetchone()

    if not estado:
        return {
            "mood": "entediada",
            "energy": 50,
            "social_battery": 50,
            "stress": 20,
            "obsession": "dark",
            "arc": "neutra",
            "event": "acordou"
        }

    return {
        "mood": estado[1],
        "energy": estado[2],
        "social_battery": estado[3],
        "stress": estado[4],
        "obsession": estado[5],
        "arc": estado[6],
        "event": estado[7]
    }

# =========================================
# MEMORY
# =========================================

def salvar_memoria(user_id, role, content):
    cursor.execute(
        "INSERT INTO user_memory VALUES (?, ?, ?)",
        (str(user_id), role, content)
    )
    conn.commit()

def carregar_memoria(user_id):
    cursor.execute(
        "SELECT role, content FROM user_memory WHERE user_id=? ORDER BY ROWID DESC LIMIT 10",
        (str(user_id),)
    )
    data = cursor.fetchall()
    data.reverse()
    return data

# =========================================
# DUCK SEARCH
# =========================================

def search(text):
    try:
        with DDGS() as ddgs:
            res = list(ddgs.text(text, max_results=3))

        out = ""
        for r in res:
            out += f"{r['title']}: {r['body']}\n\n"

        return out
    except:
        return ""

# =========================================
# IA
# =========================================

async def gerar_resposta(user_id, texto):

    estado = pegar_estado()

    pesquisa = ""
    gatilhos = ["quem", "o que", "onde", "quando", "noticia", "pesquisa"]

    if any(g in texto.lower() for g in gatilhos):
        pesquisa = search(texto)

    mensagens = [{
        "role": "system",
        "content": f"{PERSONALIDADE}\nESTADO:{estado}\n{pesquisa}"
    }]

    for r, c in carregar_memoria(user_id):
        mensagens.append({"role": r, "content": c})

    mensagens.append({"role": "user", "content": texto})

    try:
        resp = await asyncio.to_thread(
            lambda: grok.chat.completions.create(
                model="grok-2-latest",
                messages=mensagens,
                temperature=1,
                max_tokens=120
            )
        )

        return resp.choices[0].message.content.strip()

    except Exception as e:
        print("[IA ERROR]", e)
        return "..."

# =========================================
# MUSIC READY
# =========================================

@bot.command()
async def play(ctx, *, search: str):

    if not ctx.author.voice:
        await ctx.send("entra na call")
        return

    channel = ctx.author.voice.channel
    player = ctx.voice_client

    if not player:
        player = await channel.connect(cls=wavelink.Player)

    try:
        tracks = await wavelink.Playable.search(search)

        if not tracks:
            await ctx.send("n achei")
            return

        await player.play(tracks[0])
        await ctx.send(f"tocando: {tracks[0].title}")

    except Exception as e:
        print("[PLAY ERROR]", e)
        await ctx.send("erro música")

@bot.command()
async def stop(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()

@bot.command()
async def skip(ctx):
    if ctx.voice_client:
        await ctx.voice_client.stop()

# =========================================
# ON READY SAFE
# =========================================

@bot.event
async def on_ready():

    global _ready_once

    if _ready_once:
        return

    _ready_once = True

    print(f"EVA ONLINE {bot.user}")

    try:
        node = wavelink.Node(
            uri=f"http://{LAVALINK_HOST}:{LAVALINK_PORT}",
            password=LAVALINK_PASSWORD
        )

        await wavelink.Pool.connect(nodes=[node], client=bot)
        print("Lavalink OK")

    except Exception as e:
        print("[LAVALINK ERROR]", e)

    asyncio.create_task(loop_eva())

# =========================================
# BACKGROUND LOOP
# =========================================

async def loop_eva():

    await bot.wait_until_ready()

    while not bot.is_closed():
        await asyncio.sleep(random.randint(1800, 3600))
        print("EVA LOOP OK")

# =========================================
# MESSAGE HANDLER (FIXED)
# =========================================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    print("[MSG]", message.content)

    await bot.process_commands(message)

    texto = message.content.lower().strip()

    if not (texto.startswith("eva/") or bot.user in message.mentions):
        return

    clean = texto.replace("eva/", "").replace(f"<@{bot.user.id}>", "").strip()

    if not clean:
        clean = "oi"

    async with message.channel.typing():
        await asyncio.sleep(1)
        resp = await gerar_resposta(message.author.id, clean)

    await message.reply(resp)

# =========================================
# RUN
# =========================================

bot.run(DISCORD_TOKEN)