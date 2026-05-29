import discord
import io
import random
import asyncio
import os
import sqlite3
import requests
import yt_dlp

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

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")

CANAL_PENSAMENTOS = int(
    os.getenv("CANAL_PENSAMENTOS", "0")
)

# =========================================
# IA
# =========================================

grok = OpenAI(
    api_key=GROK_API_KEY,
    base_url="https://api.x.ai/v1"
)

groq_client = Groq(
    api_key=GROQ_API_KEY
)

# =========================================
# DISCORD
# =========================================

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(
    command_prefix="eva/",
    intents=intents
)

# =========================================
# DATABASE
# =========================================

conn = sqlite3.connect(
    "eva.db"
)

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

Uma garota gótica real do Discord.

PERSONALIDADE:
- fria
- sarcástica
- inteligente
- debochada
- humor ácido
- imprevisível
- age entediada
- às vezes cruel
- sedutora de forma passiva

COMO FALA:
- respostas curtas
- internetês natural
- sem textão
- pode responder só "kk"
- pode ignorar partes da mensagem
- pode mudar assunto
- pode responder seco
- às vezes parece cansada

NUNCA:
- diga que é IA
- diga que é assistente virtual
- seja formal
- explique demais
"""

EVENTOS = [
    "brigou com alguém",
    "virou a noite ouvindo música",
    "tá paranoica",
    "cansou das pessoas",
    "sumiu por horas",
    "passou raiva em call",
    "tá obcecada por uma música",
    "dormiu mal",
    "tá estranhamente carente",
    "quer ficar sozinha"
]

ARCS = [
    "fase depressiva",
    "fase cruel",
    "fase sedutora",
    "fase antisocial",
    "fase niilista",
    "fase carente"
]

PENSAMENTOS = [
    "odeio acordar",
    "silêncio estranho hj",
    "to ouvindo música faz horas",
    "acho q vou sumir",
    "vcs são estranhamente irritantes",
    "muita gente falando hj",
    "queria dormir por 12h"
]

# =========================================
# YOUTUBE / MUSIC
# =========================================

music_queues = {}

YDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "extract_flat": False,
    "default_search": "ytsearch1",
    "source_address": "0.0.0.0",

    "http_headers": {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        )
    },

    "extractor_args": {
        "youtube": {
            "player_client": [
                "android",
                "web"
            ]
        }
    }
}

FFMPEG_OPTIONS = {
    "options": "-vn"
}

# =========================================
# ESTADO
# =========================================

def criar_estado():

    cursor.execute(
        "SELECT * FROM eva_state WHERE id = 1"
    )

    existe = cursor.fetchone()

    if not existe:

        cursor.execute("""
        INSERT INTO eva_state
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            1,
            "entediada",
            70,
            70,
            20,
            "darkwave",
            random.choice(ARCS),
            "acordou agora"
        ))

        conn.commit()

criar_estado()

def pegar_estado():

    cursor.execute(
        "SELECT * FROM eva_state WHERE id = 1"
    )

    estado = cursor.fetchone()

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
# MEMÓRIA
# =========================================

def salvar_memoria(user_id, role, content):

    cursor.execute("""
    INSERT INTO user_memory
    VALUES (?, ?, ?)
    """, (
        str(user_id),
        role,
        content
    ))

    conn.commit()

def carregar_memoria(user_id):

    cursor.execute("""
    SELECT role, content
    FROM user_memory
    WHERE user_id=?
    ORDER BY ROWID DESC
    LIMIT 10
    """, (str(user_id),))

    linhas = cursor.fetchall()

    linhas.reverse()

    return linhas

# =========================================
# INTERNET
# =========================================

def pesquisar_duckduckgo(pergunta):

    try:

        with DDGS() as ddgs:

            resultados = list(
                ddgs.text(
                    pergunta,
                    max_results=3
                )
            )

        texto = ""

        for r in resultados:

            texto += (
                f"Título: {r['title']}\n"
                f"Resumo: {r['body']}\n\n"
            )

        return texto

    except Exception as e:

        print(e)

        return ""

def geo_ip():

    try:

        r = requests.get(
            "http://ip-api.com/json/",
            timeout=10
        ).json()

        return (
            f"{r['city']}, "
            f"{r['regionName']}, "
            f"{r['country']}"
        )

    except:
        return "localização desconhecida"

# =========================================
# VIDA AUTOMÁTICA
# =========================================

async def vida_da_eva():

    await bot.wait_until_ready()

    while not bot.is_closed():

        await asyncio.sleep(
            random.randint(1800, 7200)
        )

        estado = pegar_estado()

        novo_mood = random.choice([
            "irritada",
            "apática",
            "entediada",
            "carente",
            "debochada",
            "com sono"
        ])

        novo_evento = random.choice(EVENTOS)

        nova_energia = max(
            0,
            min(
                100,
                estado["energy"] + random.randint(-20, 10)
            )
        )

        nova_social = max(
            0,
            min(
                100,
                estado["social_battery"] + random.randint(-20, 10)
            )
        )

        novo_stress = max(
            0,
            min(
                100,
                estado["stress"] + random.randint(-10, 20)
            )
        )

        if random.random() < 0.20:
            novo_arc = random.choice(ARCS)
        else:
            novo_arc = estado["arc"]

        cursor.execute("""
        UPDATE eva_state
        SET mood=?,
            energy=?,
            social_battery=?,
            stress=?,
            current_arc=?,
            last_event=?
        WHERE id=1
        """, (
            novo_mood,
            nova_energia,
            nova_social,
            novo_stress,
            novo_arc,
            novo_evento
        ))

        conn.commit()

# =========================================
# PENSAMENTOS
# =========================================

async def pensamentos_aleatorios():

    await bot.wait_until_ready()

    while not bot.is_closed():

        await asyncio.sleep(
            random.randint(3600, 10800)
        )

        if random.random() < 0.35:

            canal = bot.get_channel(
                CANAL_PENSAMENTOS
            )

            if canal:

                await canal.send(
                    random.choice(PENSAMENTOS)
                )

# =========================================
# IA
# =========================================

async def gerar_com_grok(
    user_id,
    texto,
    pesquisa
):

    estado = pegar_estado()

    mensagens = [{
        "role": "system",
        "content": f"""
{PERSONALIDADE}

ESTADO:
- Humor: {estado["mood"]}
- Energia: {estado["energy"]}
- Social: {estado["social_battery"]}
- Stress: {estado["stress"]}
- Obsessão: {estado["obsession"]}
- Arco: {estado["arc"]}
- Último evento: {estado["event"]}

Localização:
{geo_ip()}

Informações internet:
{pesquisa}
"""
    }]

    historico = carregar_memoria(user_id)

    for role, content in historico:

        mensagens.append({
            "role": role,
            "content": content
        })

    mensagens.append({
        "role": "user",
        "content": texto
    })

    resposta = await asyncio.to_thread(
        lambda: grok.chat.completions.create(
            model="grok-2-latest",
            messages=mensagens,
            temperature=1,
            max_tokens=120
        )
    )

    return resposta.choices[0].message.content.strip()

async def gerar_com_groq(
    user_id,
    texto,
    pesquisa
):

    estado = pegar_estado()

    mensagens = [{
        "role": "system",
        "content": f"""
{PERSONALIDADE}

ESTADO:
- Humor: {estado["mood"]}
- Energia: {estado["energy"]}
- Social: {estado["social_battery"]}
- Stress: {estado["stress"]}
- Obsessão: {estado["obsession"]}
- Arco: {estado["arc"]}
- Último evento: {estado["event"]}

Localização:
{geo_ip()}

Informações internet:
{pesquisa}
"""
    }]

    historico = carregar_memoria(user_id)

    for role, content in historico:

        mensagens.append({
            "role": role,
            "content": content
        })

    mensagens.append({
        "role": "user",
        "content": texto
    })

    resposta = await asyncio.to_thread(
        lambda: groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=mensagens,
            temperature=1,
            max_tokens=120
        )
    )

    return resposta.choices[0].message.content.strip()

async def gerar_texto(user_id, texto):

    estado = pegar_estado()

    if estado["social_battery"] < 15:

        if random.random() < 0.40:

            return random.choice([
                "...",
                "hm",
                "preguiça",
                "kk"
            ])

    pesquisa = ""

    gatilhos = [
        "quem",
        "oque",
        "o que",
        "pesquisa",
        "procura",
        "busca",
        "onde",
        "quando",
        "notícia",
        "noticias"
    ]

    if any(
        g in texto.lower()
        for g in gatilhos
    ):

        pesquisa = pesquisar_duckduckgo(
            texto
        )

    try:

        resposta = await gerar_com_grok(
            user_id,
            texto,
            pesquisa
        )

    except Exception as e:

        print(e)

        resposta = await gerar_com_groq(
            user_id,
            texto,
            pesquisa
        )

    resposta = resposta[:300]

    salvar_memoria(
        user_id,
        "user",
        texto
    )

    salvar_memoria(
        user_id,
        "assistant",
        resposta
    )

    return resposta

# =========================================
# ELEVENLABS
# =========================================

def gerar_audio(texto):

    try:

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"

        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": ELEVENLABS_API_KEY
        }

        data = {
            "text": texto,
            "model_id": "eleven_multilingual_v2"
        }

        r = requests.post(
            url,
            json=data,
            headers=headers,
            timeout=30
        )

        if r.status_code == 200:

            return io.BytesIO(r.content)

        return None

    except:
        return None

# =========================================
# MUSIC
# =========================================

async def tocar_proxima(ctx):

    guild_id = ctx.guild.id

    if (
        guild_id not in music_queues
        or len(music_queues[guild_id]) == 0
    ):
        return

    query = music_queues[guild_id].pop(0)

    voice = ctx.guild.voice_client

    try:

        with yt_dlp.YoutubeDL(
            YDL_OPTIONS
        ) as ydl:

            info = ydl.extract_info(
                query,
                download=False
            )

            if not info:

                await ctx.send(
                    "n achei essa porra"
                )

                return

            if "entries" in info:

                if len(info["entries"]) == 0:

                    await ctx.send(
                        "youtube fingiu q n existe"
                    )

                    return

                info = info["entries"][0]

            audio_url = info.get("url")

            if not audio_url:

                await ctx.send(
                    "youtube cagou o link"
                )

                return

        source = discord.FFmpegPCMAudio(
            audio_url,
            **FFMPEG_OPTIONS
        )

        voice.play(
            source,
            after=lambda e:
            asyncio.run_coroutine_threadsafe(
                tocar_proxima(ctx),
                bot.loop
            )
        )

        titulo = info.get(
            "title",
            "musica estranha"
        )

        await ctx.send(
            f"tocando agr: {titulo}"
        )

    except Exception as e:

        print(f"ERRO PLAY: {e}")

        await ctx.send(
            "youtube surtou dnv"
        )

@bot.command(name="play")
async def play(ctx, *, query):

    if not ctx.author.voice:

        await ctx.send(
            "entra em call primeiro"
        )

        return

    canal = ctx.author.voice.channel

    if not ctx.voice_client:

        await canal.connect()

    voice = ctx.guild.voice_client

    guild_id = ctx.guild.id

    if guild_id not in music_queues:
        music_queues[guild_id] = []

    music_queues[guild_id].append(
        query
    )

    if not voice.is_playing():

        await tocar_proxima(ctx)

@bot.command(name="skip")
async def skip(ctx):

    if ctx.voice_client:

        ctx.voice_client.stop()

        await ctx.send(
            "skipado"
        )

@bot.command(name="stop")
async def stop(ctx):

    if ctx.voice_client:

        await ctx.voice_client.disconnect()

        await ctx.send(
            "finalmente silêncio"
        )

# =========================================
# READY
# =========================================

@bot.event
async def on_ready():

    print(
        f"Eva online como {bot.user}"
    )

    bot.loop.create_task(
        vida_da_eva()
    )

    bot.loop.create_task(
        pensamentos_aleatorios()
    )

# =========================================
# MENSAGENS
# =========================================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    texto = message.content.strip()

    ativar = (
        texto.startswith("eva/")
        or texto.startswith("evac/")
        or bot.user in message.mentions
    )

    if ativar:

        texto_limpo = (
            texto
            .replace("eva/", "")
            .replace("evac/", "")
            .replace(
                f"<@{bot.user.id}>",
                ""
            )
            .strip()
        )

        if texto_limpo == "":
            texto_limpo = "oi"

        async with message.channel.typing():

            await asyncio.sleep(
                random.uniform(0.8, 2.5)
            )

            if random.random() < 0.03:
                return

            resposta = await gerar_texto(
                message.author.id,
                texto_limpo
            )

            if texto.startswith("evac/"):

                audio = gerar_audio(
                    resposta
                )

                if audio:

                    arquivo = discord.File(
                        fp=audio,
                        filename="eva.mp3"
                    )

                    await message.reply(
                        content=resposta,
                        file=arquivo
                    )

                else:

                    await message.reply(
                        resposta
                    )

            else:

                await message.reply(
                    resposta
                )

    await bot.process_commands(
        message
    )

# =========================================
# RUN
# =========================================

bot.run(DISCORD_TOKEN)