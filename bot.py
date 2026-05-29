# =========================================
# EVA DISCORD BOT
# =========================================

import discord
import yt_dlp
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
intents.guilds = True
intents.members = True

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

EVENTOS = [
    "sumiu por horas",
    "brigou em call",
    "tá cansada das pessoas",
    "virou a noite ouvindo música",
    "dormiu mal",
    "tá paranoica",
    "tá estranhamente sociável",
    "passou raiva hoje",
    "quer ficar sozinha"
]

ARCS = [
    "fase cruel",
    "fase antisocial",
    "fase depressiva",
    "fase sedutora",
    "fase apática",
    "fase niilista"
]

PENSAMENTOS = [
    "odeio acordar",
    "silêncio estranho hj",
    "acho q vou sumir",
    "vcs falam mt merda",
    "to ouvindo música faz horas",
    "queria dormir 15h seguidas",
    "madrugada deixa td pior"
]

# =========================================
# ESTADO EVA
# =========================================

def criar_estado():

    cursor.execute(
        "SELECT * FROM eva_state WHERE id = 1"
    )

    estado = cursor.fetchone()

    if not estado:

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
    LIMIT 12
    """, (str(user_id),))

    dados = cursor.fetchall()

    dados.reverse()

    return dados

# =========================================
# GEO
# =========================================

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

        return "desconhecido"

# =========================================
# INTERNET
# =========================================

def pesquisar_duckduckgo(texto):

    try:

        with DDGS() as ddgs:

            resultados = list(
                ddgs.text(
                    texto,
                    max_results=3
                )
            )

        resposta = ""

        for r in resultados:

            resposta += (
                f"Título: {r['title']}\n"
                f"Resumo: {r['body']}\n\n"
            )

        return resposta

    except Exception as e:

        print(e)

        return ""

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
            "entediada",
            "apática",
            "irritada",
            "cansada",
            "debochada",
            "carente"
        ])

        novo_evento = random.choice(
            EVENTOS
        )

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

            novo_arc = random.choice(
                ARCS
            )

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

                try:

                    await canal.send(
                        random.choice(PENSAMENTOS)
                    )

                except:
                    pass

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
Humor: {estado["mood"]}
Energia: {estado["energy"]}
Social: {estado["social_battery"]}
Stress: {estado["stress"]}
Obsessão: {estado["obsession"]}
Arco: {estado["arc"]}
Evento: {estado["event"]}

Localização:
{geo_ip()}

Pesquisa:
{pesquisa}
"""
    }]

    historico = carregar_memoria(
        user_id
    )

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

async def gerar_texto(user_id, texto):

    estado = pegar_estado()

    if estado["social_battery"] < 10:

        if random.random() < 0.45:

            return random.choice([
                "...",
                "kk",
                "hm",
                "preguiça"
            ])

    pesquisa = ""

    gatilhos = [
        "quem",
        "o que",
        "oque",
        "onde",
        "quando",
        "pesquisa",
        "procura",
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

        resposta = "..."

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
# YOUTUBE + PIPED
# =========================================

YDL_OPTIONS = {
    "format": "bestaudio/best",
    "quiet": True,
    "nocheckcertificate": True,
    "ignoreerrors": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0"
}

FFMPEG_OPTIONS = {
    "before_options": (
        "-reconnect 1 "
        "-reconnect_streamed 1 "
        "-reconnect_delay_max 5"
    ),
    "options": "-vn"
}

PIPED_INSTANCES = [
    "https://piped.video",
    "https://piped.adminforge.de",
    "https://piped.projectsegfau.lt"
]

def buscar_piped(query):

    for instancia in PIPED_INSTANCES:

        try:

            url = (
                f"{instancia}/api/search?"
                f"q={query}&filter=videos"
            )

            r = requests.get(
                url,
                timeout=10
            ).json()

            items = r.get("items", [])

            if items:

                video = items[0]

                video_url = video.get(
                    "url",
                    ""
                )

                if "watch?v=" in video_url:

                    return (
                        "https://youtube.com"
                        f"{video_url}"
                    )

        except Exception as e:

            print(e)

    return None

# =========================================
# MUSIC
# =========================================

@bot.command(name="play")
async def play(ctx, *, search):

    if not ctx.author.voice:

        await ctx.send(
            "entra em call primeiro"
        )

        return

    canal = ctx.author.voice.channel

    if ctx.voice_client is None:

        vc = await canal.connect()

    else:

        vc = ctx.voice_client

    await ctx.send(
        "procurando música..."
    )

    try:

        url = search

        if "http" not in search:

            piped_url = buscar_piped(
                search
            )

            if piped_url:

                url = piped_url

        loop = asyncio.get_event_loop()

        data = await loop.run_in_executor(
            None,
            lambda: yt_dlp.YoutubeDL(
                YDL_OPTIONS
            ).extract_info(
                url,
                download=False
            )
        )

        if not data:

            await ctx.send(
                "youtube morreu dnv"
            )

            return

        if "entries" in data:

            data = data["entries"][0]

        if not data:

            await ctx.send(
                "n achei isso"
            )

            return

        audio_url = data.get("url")

        titulo = data.get(
            "title",
            "música"
        )

        if not audio_url:

            await ctx.send(
                "falhou pegando áudio"
            )

            return

        source = discord.FFmpegPCMAudio(
            audio_url,
            **FFMPEG_OPTIONS
        )

        if vc.is_playing():

            vc.stop()

        vc.play(source)

        await ctx.send(
            f"tocando: {titulo}"
        )

    except Exception as e:

        print(e)

        await ctx.send(
            "youtube surtou"
        )

@bot.command(name="stop")
async def stop(ctx):

    if ctx.voice_client:

        await ctx.voice_client.disconnect()

        await ctx.send(
            "silêncio finalmente"
        )

@bot.command(name="skip")
async def skip(ctx):

    if ctx.voice_client:

        ctx.voice_client.stop()

        await ctx.send(
            "pulada"
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
# CHAT
# =========================================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    texto = message.content.strip()

    ativar = (
        texto.startswith("eva/")
        or bot.user in message.mentions
    )

    if ativar:

        texto_limpo = (
            texto
            .replace("eva/", "")
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

            try:

                await message.reply(
                    resposta
                )

            except:
                pass

    await bot.process_commands(
        message
    )

# =========================================
# RUN
# =========================================

bot.run(DISCORD_TOKEN)