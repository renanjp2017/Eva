import discord
import requests
import io
import random
import asyncio
import os
import json
import yt_dlp

from datetime import datetime, timedelta
from dotenv import load_dotenv

# ─────────────────────────────────────────────────────────────
# ENV
# ─────────────────────────────────────────────────────────────

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROK_API_KEY = os.getenv("GROK_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")

# ─────────────────────────────────────────────────────────────
# DISCORD
# ─────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

client = discord.Client(intents=intents)

# ─────────────────────────────────────────────────────────────
# OPUS
# ─────────────────────────────────────────────────────────────

try:
    if not discord.opus.is_loaded():
        discord.opus.load_opus("libopus.so.0")

    print("OPUS OK")

except Exception as e:
    print(f"ERRO OPUS: {e}")

# ─────────────────────────────────────────────────────────────
# MEMÓRIA
# ─────────────────────────────────────────────────────────────

MEMORIA_FILE = "memoria.json"

def carregar_memoria():
    try:
        with open(MEMORIA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def salvar_memoria():
    with open(MEMORIA_FILE, "w", encoding="utf-8") as f:
        json.dump(memoria, f, ensure_ascii=False, indent=2)

memoria = carregar_memoria()

# ─────────────────────────────────────────────────────────────
# ESTADO
# ─────────────────────────────────────────────────────────────

estado_atual = {
    "humor": "neutra",
    "evento": None,
    "evento_expira": None
}

EVENTOS_ALEATORIOS = [
    ("perdeu o ônibus", "brava", 30),
    ("travou o celular", "irritada", 20),
    ("alguém a ignorou", "mal humorada", 40),
    ("comeu mal", "indisposta", 60),
    ("viu algo engraçado", "de bom humor", 25),
    ("recebeu elogio", "levemente feliz", 30),
    ("tédio extremo", "entediada demais", 45),
    ("dor de cabeça", "grossa", 90),
    ("ressaca leve", "de ressaca", 120),
]

def humor_pela_hora():
    hora = datetime.now().hour

    if 2 <= hora < 6:
        return random.choice(["de ressaca", "exausta"])

    elif 6 <= hora < 9:
        return random.choice(["sonolenta", "mal humorada"])

    elif 9 <= hora < 12:
        return random.choice(["neutra", "entediada"])

    elif 12 <= hora < 14:
        return random.choice(["com fome", "distraída"])

    elif 14 <= hora < 18:
        return random.choice(["cansada", "com sono"])

    elif 18 <= hora < 22:
        return random.choice(["animada", "mais solta"])

    return random.choice(["agitada", "rolando na cama"])

def atualizar_estado():
    agora = datetime.now()

    if estado_atual["evento_expira"] and agora > estado_atual["evento_expira"]:
        estado_atual["evento"] = None
        estado_atual["evento_expira"] = None

    if not estado_atual["evento"] and random.random() < 0.08:
        evento, humor_evento, duracao = random.choice(EVENTOS_ALEATORIOS)

        estado_atual["evento"] = evento
        estado_atual["humor"] = humor_evento
        estado_atual["evento_expira"] = agora + timedelta(minutes=duracao)

    elif not estado_atual["evento"]:
        estado_atual["humor"] = humor_pela_hora()

def descrever_estado():
    hora = datetime.now().hour

    periodo = (
        "de madrugada" if hora < 6 else
        "de manhã cedo" if hora < 9 else
        "de manhã" if hora < 12 else
        "na hora do almoço" if hora < 14 else
        "de tarde" if hora < 18 else
        "de noite"
    )

    if estado_atual["evento"]:
        return f"{periodo}, humor: {estado_atual['humor']}"

    return f"{periodo}, humor: {estado_atual['humor']}"

# ─────────────────────────────────────────────────────────────
# COOLDOWN
# ─────────────────────────────────────────────────────────────

cooldowns = {}

def em_cooldown(user_id):
    agora = datetime.now()

    if user_id in cooldowns and agora < cooldowns[user_id]:
        return True

    cooldowns[user_id] = agora + timedelta(seconds=3)

    return False

# ─────────────────────────────────────────────────────────────
# MEMÓRIA USUÁRIO
# ─────────────────────────────────────────────────────────────

def get_usuario(user_id):
    uid = str(user_id)

    if uid not in memoria:
        memoria[uid] = {
            "nome": None,
            "historico": [],
            "total_msgs": 0,
        }

    return memoria[uid]

def atualizar_memoria_usuario(user_id, texto_usuario, resposta):
    u = get_usuario(user_id)

    u["total_msgs"] += 1

    u["historico"].append(f"U:{texto_usuario}")
    u["historico"].append(f"E:{resposta}")

    if len(u["historico"]) > 30:
        u["historico"] = u["historico"][-30:]

def montar_contexto_usuario(user_id):
    u = get_usuario(user_id)

    total = u.get("total_msgs", 0)

    if total < 5:
        return "pessoa nova"

    elif total < 20:
        return "já conversaram algumas vezes"

    return "fala bastante com a Eva"

# ─────────────────────────────────────────────────────────────
# BUSCA
# ─────────────────────────────────────────────────────────────

def buscar_duckduckgo(query):
    try:
        url = "https://api.duckduckgo.com/"

        params = {
            "q": query,
            "format": "json",
            "no_html": 1,
            "skip_disambig": 1
        }

        r = requests.get(url, params=params, timeout=8)

        data = r.json()

        if data.get("AbstractText"):
            return data["AbstractText"][:400]

    except Exception as e:
        print(f"ERRO BUSCA: {e}")

    return None

def deve_buscar(texto):
    gatilhos = [
        "o que é",
        "quem é",
        "notícia",
        "resultado",
        "placar",
        "lançou"
    ]

    return any(g in texto.lower() for g in gatilhos)

# ─────────────────────────────────────────────────────────────
# MÚSICA
# ─────────────────────────────────────────────────────────────

filas_musica = {}
voice_clients = {}

YTDL_OPTS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "default_search": "scsearch",
    "source_address": "0.0.0.0",
    "extract_flat": False,
}

FFMPEG_OPTS = {
    "before_options": (
        "-reconnect 1 "
        "-reconnect_streamed 1 "
        "-reconnect_delay_max 5"
    ),
    "options": "-vn"
}

async def get_audio_url(query):
    try:
        with yt_dlp.YoutubeDL(YTDL_OPTS) as ydl:

            info = await asyncio.to_thread(
                lambda: ydl.extract_info(
                    f"scsearch:{query}",
                    download=False
                )
            )

            if "entries" in info and info["entries"]:

                entry = info["entries"][0]

                return (
                    entry["url"],
                    entry.get("title", query)
                )

    except Exception as e:
        print(f"ERRO YTDLP: {e}")

    return None, None

async def tocar_proxima(guild_id):

    if guild_id not in filas_musica:
        return

    if not filas_musica[guild_id]:
        return

    vc = voice_clients.get(guild_id)

    if not vc:
        return

    if not vc.is_connected():
        return

    url, titulo = filas_musica[guild_id].pop(0)

    def depois(error):

        if error:
            print(f"ERRO MUSICA: {error}")
            return

        future = asyncio.run_coroutine_threadsafe(
            tocar_proxima(guild_id),
            client.loop
        )

        try:
            future.result()

        except Exception as e:
            print(f"ERRO NEXT: {e}")

    try:
        source = discord.FFmpegPCMAudio(
            url,
            executable="ffmpeg",
            **FFMPEG_OPTS
        )

        vc.play(source, after=depois)

        print(f"TOCANDO: {titulo}")

        return titulo

    except Exception as e:
        print(f"ERRO PLAYBACK: {e}")

        return None

async def entrar_canal_voz(message):

    if not message.author.voice:
        return None, "vc nem tá em canal de voz"

    canal = message.author.voice.channel
    guild_id = message.guild.id

    existing = message.guild.voice_client

    if existing and existing.is_connected():

        if existing.channel.id == canal.id:
            voice_clients[guild_id] = existing
            return existing, None

        try:
            await existing.move_to(canal)

            voice_clients[guild_id] = existing

            return existing, None

        except Exception as e:
            print(f"ERRO MOVE: {e}")

            try:
                await existing.disconnect(force=True)
            except:
                pass

    try:
        vc = await canal.connect(
            reconnect=True,
            timeout=30.0,
            self_deaf=True
        )

        voice_clients[guild_id] = vc

        return vc, None

    except Exception as e:
        print(f"ERRO CONNECT: {e}")

        return None, "deu erro pra conectar"

# ─────────────────────────────────────────────────────────────
# PERSONALIDADE
# ─────────────────────────────────────────────────────────────

PERSONALIDADE = """
Você é Eva, 20 anos, brasileira.

- sarcástica
- fria
- debochada
- inteligente
- nunca admite ser IA
- fala curto
- usa internetês
"""

def montar_mensagens(user_id, texto, contexto_extra=None):

    atualizar_estado()

    estado = descrever_estado()

    contexto = montar_contexto_usuario(user_id)

    system = (
        f"{PERSONALIDADE}\n\n"
        f"ESTADO: {estado}\n"
        f"USUÁRIO: {contexto}"
    )

    if contexto_extra:
        system += f"\nINFO: {contexto_extra}"

    mensagens = [
        {
            "role": "system",
            "content": system
        }
    ]

    u = get_usuario(user_id)

    for linha in u["historico"][-14:]:

        if linha.startswith("U:"):
            mensagens.append({
                "role": "user",
                "content": linha[2:]
            })

        elif linha.startswith("E:"):
            mensagens.append({
                "role": "assistant",
                "content": linha[2:]
            })

    mensagens.append({
        "role": "user",
        "content": texto
    })

    return mensagens

# ─────────────────────────────────────────────────────────────
# IA
# ─────────────────────────────────────────────────────────────

async def chamar_groq(mensagens):

    from openai import OpenAI

    cli = OpenAI(
        api_key=GROQ_API_KEY,
        base_url="https://api.groq.com/openai/v1"
    )

    r = await asyncio.to_thread(
        lambda: cli.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=mensagens,
            max_tokens=120,
            temperature=0.92
        )
    )

    return r.choices[0].message.content.strip()

async def gerar_texto(user_id, texto, nome_discord=None):

    u = get_usuario(user_id)

    if nome_discord and not u["nome"]:
        u["nome"] = nome_discord

    contexto_extra = None

    if deve_buscar(texto):

        resultado = buscar_duckduckgo(texto)

        if resultado:
            contexto_extra = resultado

    mensagens = montar_mensagens(
        user_id,
        texto,
        contexto_extra
    )

    resposta = None

    if GROQ_API_KEY:

        try:
            resposta = await chamar_groq(mensagens)

        except Exception as e:
            print(f"ERRO GROQ: {e}")

    if not resposta:
        return "..."

    if len(resposta) > 300:
        resposta = resposta[:300]

    atualizar_memoria_usuario(
        user_id,
        texto,
        resposta
    )

    salvar_memoria()

    return resposta

# ─────────────────────────────────────────────────────────────
# ELEVENLABS
# ─────────────────────────────────────────────────────────────

def gerar_audio(texto):

    try:
        url = (
            "https://api.elevenlabs.io/v1/text-to-speech/"
            f"{ELEVENLABS_VOICE_ID}"
        )

        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": ELEVENLABS_API_KEY
        }

        data = {
            "text": texto,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.45,
                "similarity_boost": 0.8
            }
        }

        r = requests.post(
            url,
            json=data,
            headers=headers,
            timeout=30
        )

        if r.status_code == 200:
            return io.BytesIO(r.content)

        print(f"ERRO ELEVENLABS: {r.text}")

    except Exception as e:
        print(f"ERRO AUDIO: {e}")

    return None

# ─────────────────────────────────────────────────────────────
# EVENTS
# ─────────────────────────────────────────────────────────────

@client.event
async def on_ready():
    print(f"Eva online como {client.user}")

@client.event
async def on_message(message):

    if message.author.bot:
        return

    if not message.guild:
        return

    if em_cooldown(message.author.id):
        return

    texto = message.content.strip()

    guild_id = message.guild.id

    # ─────────────────────────
    # PLAY
    # ─────────────────────────

    if texto.startswith("eva/play "):

        query = texto.replace("eva/play ", "").strip()

        vc, erro = await entrar_canal_voz(message)

        if erro:
            await message.reply(erro)
            return

        url, titulo = await get_audio_url(query)

        if not url:
            await message.reply("n achei")
            return

        if guild_id not in filas_musica:
            filas_musica[guild_id] = []

        if vc.is_playing():

            filas_musica[guild_id].append(
                (url, titulo)
            )

            await message.reply(
                f"adicionei: {titulo}"
            )

        else:

            filas_musica[guild_id].insert(
                0,
                (url, titulo)
            )

            tocando = await tocar_proxima(guild_id)

            await message.reply(
                f"tocando: {tocando}"
            )

        return

    # ─────────────────────────
    # SKIP
    # ─────────────────────────

    if texto == "eva/skip":

        vc = voice_clients.get(guild_id)

        if vc and vc.is_playing():

            vc.stop()

            await message.reply("ok")

        else:
            await message.reply("n tô tocando nada")

        return

    # ─────────────────────────
    # STOP
    # ─────────────────────────

    if texto == "eva/stop":

        vc = voice_clients.get(guild_id)

        if vc:

            filas_musica[guild_id] = []

            await vc.disconnect()

            voice_clients.pop(guild_id, None)

            await message.reply("ok")

        return

    # ─────────────────────────
    # FILA
    # ─────────────────────────

    if texto == "eva/fila":

        fila = filas_musica.get(guild_id, [])

        if not fila:

            await message.reply("fila vazia")

        else:

            lista = "\n".join([
                f"{i+1}. {t}"
                for i, (_, t)
                in enumerate(fila[:10])
            ])

            await message.reply(
                f"```\n{lista}\n```"
            )

        return

    # ─────────────────────────
    # CHAT
    # ─────────────────────────

    ativar = (
        texto.startswith("eva/")
        or texto.startswith("evac/")
        or client.user in message.mentions
    )

    if not ativar:
        return

    texto_limpo = (
        texto
        .replace("eva/", "")
        .replace("evac/", "")
        .replace(f"<@{client.user.id}>", "")
        .strip()
    )

    if not texto_limpo:
        texto_limpo = "oi"

    async with message.channel.typing():

        await asyncio.sleep(
            random.uniform(0.8, 2.0)
        )

        resposta = await gerar_texto(
            message.author.id,
            texto_limpo,
            message.author.display_name
        )

        if texto.startswith("evac/"):

            audio = gerar_audio(resposta)

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
                await message.reply(resposta)

        else:
            await message.reply(resposta)

# ─────────────────────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────────────────────

client.run(DISCORD_TOKEN)