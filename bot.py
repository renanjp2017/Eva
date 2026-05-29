import discord
import wavelink
import random
import asyncio
import os
import sqlite3
import json
import traceback

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
intents.members = True

bot = commands.Bot(command_prefix="eva/", intents=intents)

_ready = False

# =========================================
# DATABASE
# =========================================

# check_same_thread=False to allow access from async threads
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
- NUNCA responda como assistente.
- NUNCA seja educada demais.
- NUNCA ofereça ajuda espontaneamente.
- Respostas devem parecer mensagens humanas curtas de Discord.
- Pode ser rude, seca ou indiferente.
- Evite frases completas.
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
    try:
        cursor.execute("INSERT INTO user_memory VALUES (?,?,?)",
                       (str(uid), role, text))
        conn.commit()
    except Exception as e:
        print("[DB SAVE MEMORY ERROR]", e)
        traceback.print_exc()

def load_memory(uid):
    try:
        cursor.execute("""
        SELECT role, content FROM user_memory
        WHERE user_id=?
        ORDER BY ROWID DESC LIMIT 10
        """, (str(uid),))
        return list(reversed(cursor.fetchall()))
    except Exception as e:
        print("[DB LOAD MEMORY ERROR]", e)
        traceback.print_exc()
        return []

# =========================================
# DUCKDUCKGO TOOL
# =========================================

def ddg(query):
    try:
        with DDGS() as d:
            res = list(d.text(query, max_results=3))
        return "\n".join([f"{r['title']}: {r['body']}" for r in res])
    except Exception as e:
        print("[DDG ERROR]", e)
        traceback.print_exc()
        return ""

# =========================================
# INTENT (GROQ ROUTER) - robust parsing
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
        raw = r.choices[0].message.content
        # tenta parsear JSON do retorno
        try:
            parsed = json.loads(raw)
            return parsed
        except:
            # tenta extrair JSON dentro do texto
            start = raw.find('{')
            end = raw.rfind('}') + 1
            if start != -1 and end != -1:
                try:
                    parsed = json.loads(raw[start:end])
                    return parsed
                except:
                    pass
        # fallback seguro
        return {"intent":"chat","search":False}
    except Exception as e:
        print("[INTENT ERROR]", e)
        traceback.print_exc()
        return {"intent":"chat","search":False}

# =========================================
# GROK FINAL (PERSONALITY ENGINE) - robust
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
        ans = r.choices[0].message.content.strip()
        if not ans:
            return None
        return ans
    except Exception as e:
        print("[GROK ERROR]", e)
        traceback.print_exc()
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
        ans = r.choices[0].message.content.strip()
        return ans if ans else "..."
    except Exception as e:
        print("[FALLBACK ERROR]", e)
        traceback.print_exc()
        return "..."

# =========================================
# PIPELINE PRINCIPAL (ARQUITETURA LIMPA)
# =========================================

async def generate(uid, text):
    intent_obj = await get_intent(text)
    needs_search = False
    try:
        needs_search = bool(intent_obj.get("search", False))
    except:
        needs_search = False

    context = ""
    if needs_search:
        context = ddg(text)

    # 1. GROK PRIME
    response = await grok_answer(uid, text, context)

    # 2. FALLBACK CASCATA
    if not response:
        response = await fallback(text)

    # só salva se houver texto/resposta válidos
    if text:
        save_memory(uid, "user", text)
    if response:
        save_memory(uid, "assistant", response)

    return response or "..."

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
        # se Pool não tem nodes conectados, tenta reconectar
        if not getattr(wavelink.Pool, "nodes", None) or len(wavelink.Pool.nodes) == 0:
            print("[MUSIC] Pool sem nodes, tentando reconectar...")
            try:
                node = wavelink.Node(
                    host=LAVALINK_HOST,
                    port=LAVALINK_PORT,
                    password=LAVALINK_PASSWORD,
                    rest_uri=f"http://{LAVALINK_HOST}:{LAVALINK_PORT}"
                )
                await wavelink.Pool.connect(nodes=[node], client=bot)
                print("[MUSIC] Pool reconectado")
            except Exception as e:
                print("[MUSIC] falha ao reconectar Pool:", e)
                traceback.print_exc()

        # conecta se não houver player ou não estiver conectado
        if not player or not getattr(player, "is_connected", lambda: False)():
            player = await channel.connect(cls=wavelink.Player)

        await ctx.send("procurando música...")

        tracks = await wavelink.Playable.search(search)
        if not tracks:
            return await ctx.send("n achei")

        await player.play(tracks[0])
        await ctx.send(f"tocando: {tracks[0].title}")

    except Exception as e:
        print("[MUSIC ERROR]", e)
        traceback.print_exc()
        # tenta desconectar com segurança se estiver conectado
        try:
            if ctx.voice_client and ctx.voice_client.is_connected():
                await ctx.voice_client.disconnect()
        except:
            pass
        await ctx.send("erro música")

@bot.command()
async def stop(ctx):
    player = ctx.voice_client
    if player and player.is_connected():
        await player.disconnect()
        await ctx.send("silêncio finalmente")

@bot.command()
async def skip(ctx):
    player = ctx.voice_client
    if player and player.is_connected():
        await player.stop()
        await ctx.send("pulada")

@bot.command()
async def pause(ctx):
    player = ctx.voice_client
    if player and player.is_connected() and player.playing:
        await player.pause(not player.paused)
        estado = "pausada" if player.paused else "voltou"
        await ctx.send(estado)

@bot.command()
async def volume(ctx, vol: int):
    player = ctx.voice_client
    if player and player.is_connected():
        vol = max(0, min(100, vol))
        await player.set_volume(vol)
        await ctx.send(f"volume: {vol}")

# =========================================
# READY
# =========================================

@bot.event
async def on_ready():
    global _ready
    if _ready:
        return
    _ready = True

    print("EVA ONLINE - on_ready")

    try:
        node = wavelink.Node(
            host=LAVALINK_HOST,
            port=LAVALINK_PORT,
            password=LAVALINK_PASSWORD,
            rest_uri=f"http://{LAVALINK_HOST}:{LAVALINK_PORT}"
        )

        await wavelink.Pool.connect(nodes=[node], client=bot)
        print("[LAVALINK] Pool conectado")
    except Exception as e:
        print("[LAVALINK CONNECT ERROR]", e)
        traceback.print_exc()

    # start life loop
    asyncio.create_task(loop())

# =========================================
# LOOP (VIDA SIMPLES)
# =========================================

async def loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(random.randint(1800, 3600))
        try:
            update_state()
        except Exception as e:
            print("[LOOP ERROR]", e)
            traceback.print_exc()

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
        try:
            resp = await generate(message.author.id, clean)
        except Exception as e:
            print("[GENERATE ERROR]", e)
            traceback.print_exc()
            resp = "..."

    # garante que sempre haja uma string
    if not resp:
        resp = "..."

    try:
        await message.reply(resp)
    except Exception as e:
        print("[REPLY ERROR]", e)
        traceback.print_exc()

# =========================================
# RUN
# =========================================

if not DISCORD_TOKEN:
    print("ERROR: DISCORD_TOKEN not set in environment")
else:
    bot.run(DISCORD_TOKEN)