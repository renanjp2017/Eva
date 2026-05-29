# =========================================
# EVA DISCORD BOT (FIXED)
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
# TOKENS
# =========================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

GROK_API_KEY = os.getenv("GROK_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

CANAL_PENSAMENTOS = int(os.getenv("CANAL_PENSAMENTOS", "0"))

LAVALINK_HOST = os.getenv("LAVALINK_HOST", "lavalink.railway.internal")
LAVALINK_PORT = int(os.getenv("LAVALINK_PORT", "2333"))
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD", "evabotsenha")

# =========================================
# IA
# =========================================

grok = OpenAI(
    api_key=GROK_API_KEY,
    base_url="https://api.x.ai/v1"
)

groq_client = Groq(api_key=GROQ_API_KEY)

# =========================================
# DISCORD
# =========================================

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="eva/", intents=intents)

# =========================================
# SQLITE SAFE MODE
# =========================================

conn = sqlite3.connect("eva.db", check_same_thread=False)
conn.execute("PRAGMA journal_mode=WAL;")
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
# PERSONALIDADE (mantida)
# =========================================

PERSONALIDADE = """Eva..."""

# =========================================
# SAFE STATE GUARD
# =========================================

_eva_ready = False

# =========================================
# HELPERS
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
            "obsession": "darkwave",
            "arc": "fase neutra",
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
# ON READY FIX
# =========================================

@bot.event
async def on_ready():
    global _eva_ready

    if _eva_ready:
        return

    _eva_ready = True

    print(f"[EVA] online como {bot.user}")

    try:
        node = wavelink.Node(
            uri=f"http://{LAVALINK_HOST}:{LAVALINK_PORT}",
            password=LAVALINK_PASSWORD
        )

        await wavelink.Pool.connect(nodes=[node], client=bot)
        print("[LAVALINK] conectado")

    except Exception as e:
        print("[LAVALINK ERROR]", repr(e))

    bot.loop.create_task(vida_da_eva())
    bot.loop.create_task(pensamentos_aleatorios())

# =========================================
# ON MESSAGE FIX (CRÍTICO)
# =========================================

@bot.event
async def on_message(message):

    try:
        if message.author.bot:
            return

        print("[MSG]", message.content)

        texto = message.content.strip()

        # comandos primeiro
        await bot.process_commands(message)

        if not texto:
            return

        if texto.startswith("eva/"):
            texto_limpo = texto.replace("eva/", "").strip()
        elif bot.user in message.mentions:
            texto_limpo = texto.replace(f"<@{bot.user.id}>", "").strip()
        else:
            return

        if not texto_limpo:
            texto_limpo = "oi"

        async with message.channel.typing():
            await asyncio.sleep(random.uniform(0.5, 1.5))

            resposta = await gerar_texto(message.author.id, texto_limpo)

        await message.reply(resposta)

    except Exception as e:
        print("[ON_MESSAGE ERROR]", repr(e))

# =========================================
# RUN
# =========================================

bot.run(DISCORD_TOKEN)