import discord
import aiohttp
import io
import random
import asyncio
import os
import json
import yt_dlp
import logging

from datetime import datetime, timedelta
from dotenv import load_dotenv

# ─────────────────────────────────────────────────────────────
# LOAD ENV
# ─────────────────────────────────────────────────────────────

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")

# ─────────────────────────────────────────────────────────────
# LOGS
# ─────────────────────────────────────────────────────────────

logging.getLogger("discord.voice_state").setLevel(logging.ERROR)

# ─────────────────────────────────────────────────────────────
# DISCORD
# ─────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

client = discord.Client(intents=intents)

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

async def salvar_memoria_async():
    # Roda a função síncrona de I/O em uma thread separada para não bloquear
    def _salvar():
        with open(MEMORIA_FILE, "w", encoding="utf-8") as f:
            json.dump(memoria, f, ensure_ascii=False, indent=2)
    await asyncio.to_thread(_salvar)

memoria = carregar_memoria()

# ─────────────────────────────────────────────────────────────
# ESTADO EMOCIONAL
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
    ("TPM", "irritadíssima", 480),
]

def humor_pela_hora():
    hora = datetime.now().hour
    if 2 <= hora < 6: return random.choice(["de ressaca", "exausta"])
    elif 6 <= hora < 9: return random.choice(["sonolenta", "mal humorada"])
    elif 9 <= hora < 12: return random.choice(["neutra", "entediada"])
    elif 12 <= hora < 14: return random.choice(["com fome", "distraída"])
    elif 14 <= hora < 18: return random.choice(["cansada", "com sono"])
    elif 18 <= hora < 22: return random.choice(["animada", "mais solta"])
    return random.choice(["agitada", "rolando na cama"])

def atualizar_estado():
    agora = datetime.now()
    if estado_atual["evento_expira"] and agora > estado_atual["evento_expira"]:
        estado_atual["evento"] = None
        estado_atual["evento_expira"] = None

    if not estado_atual["evento"] and random.random() < 0.08:
        evento, humor, duracao = random.choice(EVENTOS_ALEATORIOS)
        estado_atual["evento"] = evento
        estado_atual["humor"] = humor
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
        "de noite" if hora < 22 else
        "de madrugada"
    )
    if estado_atual["evento"]:
        return f"{periodo}, humor: {estado_atual['humor']} (motivo: {estado_atual['evento']})"
    return f"{periodo}, humor: {estado_atual['humor']}"

# ─────────────────────────────────────────────────────────────
# COOLDOWN
# ─────────────────────────────────────────────────────────────

cooldowns = {}

def em_cooldown(user_id):
    agora = datetime.now()
    if user_id in cooldowns:
        if agora < cooldowns[user_id]:
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
            "assuntos": [],
            "fatos": [],
            "historico": [],
            "total_msgs": 0,
        }
    return memoria[uid]

def atualizar_memoria_usuario(user_id, texto, resposta):
    u = get_usuario(user_id)
    u["total_msgs"] += 1
    u["historico"].append(f"U:{texto}")
    u["historico"].append(f"E:{resposta}")
    if len(u["historico"]) > 30:
        u["historico"] = u["historico"][-30:]

def montar_contexto_usuario(user_id):
    u = get_usuario(user_id)
    partes = []
    if u["nome"]: partes.append(f"nome: {u['nome']}")
    total = u["total_msgs"]
    if total == 0: partes.append("primeira conversa")
    elif total < 10: partes.append("já conversaram")
    else: partes.append("fala bastante com a Eva")
    return " | ".join(partes)

# ─────────────────────────────────────────────────────────────
# PESQUISA (Agora Assíncrona com aiohttp)
# ─────────────────────────────────────────────────────────────

def deve_buscar(texto):
    gatilhos = ["o que é", "quem é", "como funciona", "me fala sobre", "notícia", "resultado", "placar"]
    return any(g in texto.lower() for g in gatilhos)

async def buscar_duckduckgo(query):
    try:
        url = "https://api.duckduckgo.com/"
        params = {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=8) as r:
                data = await r.json()
                if data.get("AbstractText"):
                    return data["AbstractText"][:400]
        return None
    except Exception as e:
        print(f"ERRO BUSCA: {e}")
        return None

# ─────────────────────────────────────────────────────────────
# YTDLP
# ─────────────────────────────────────────────────────────────

filas_musica = {}
voice_clients = {}

YTDL_OPTS = {
    "format": "bestaudio[ext=m4a]/bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "extract_flat": False,
    "nocheckcertificate": True,
    "ignoreerrors": True,
    "cookiefile": "cookies.txt",  # Aqui ele vai ler o arquivo que você exportou
    "extractor_args": {
        "youtube": {
            "player_client": ["tv", "web"] # 'tv' tem menos chance de ser bloqueado
        }
    }
}


FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn"
}

async def get_audio_url(query):
    try:
        with yt_dlp.YoutubeDL(YTDL_OPTS) as ydl:
            info = await asyncio.to_thread(lambda: ydl.extract_info(f"ytsearch1:{query}", download=False))
            if not info: return None, None
            entry = info["entries"][0] if "entries" in info else info
            if not entry: return None, None
            return entry.get("url"), entry.get("title", query)
    except Exception as e:
        print(f"ERRO YTDLP: {e}")
        return None, None

async def tocar_proxima(guild_id):
    if guild_id not in filas_musica: return
    if not filas_musica[guild_id]:
        vc = voice_clients.get(guild_id)
        if vc and vc.is_connected(): await vc.disconnect()
        voice_clients.pop(guild_id, None)
        return

    vc = voice_clients.get(guild_id)
    if not vc or not vc.is_connected(): return

    url, titulo = filas_musica[guild_id].pop(0)

    def depois(error):
        if error: print(f"ERRO MUSICA: {error}")
        asyncio.run_coroutine_threadsafe(tocar_proxima(guild_id), client.loop)

    try:
        source = discord.FFmpegPCMAudio(url, executable="ffmpeg", **FFMPEG_OPTS)
        vc.play(source, after=depois)
        print(f"TOCANDO: {titulo}")
        return titulo
    except Exception as e:
        print(f"ERRO PLAYBACK: {e}")
        return None

async def entrar_canal_voz(message):
    if not message.author.voice: return None, "vc nem tá em canal"
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
            try: await existing.disconnect(force=True)
            except: pass

    try:
        vc = await canal.connect(reconnect=True, timeout=30.0, self_deaf=True)
        voice_clients[guild_id] = vc
        return vc, None
    except Exception as e:
        print(f"ERRO CONNECT: {e}")
        return None, "erro pra conectar"

# ─────────────────────────────────────────────────────────────
# PERSONALIDADE
# ─────────────────────────────────────────────────────────────

PERSONALIDADE = """
Você é Eva, 20 anos, brasileira.

- sarcástica
- fria
- debochada
- inteligente
- fala curto
- usa internetês
- nunca admite ser IA
"""

# ─────────────────────────────────────────────────────────────
# PROMPT
# ─────────────────────────────────────────────────────────────

def montar_mensagens(user_id, texto, contexto_extra=None):
    atualizar_estado()
    estado = descrever_estado()
    contexto = montar_contexto_usuario(user_id)
    system = f"{PERSONALIDADE}\n\nESTADO: {estado}\nUSUÁRIO: {contexto}"
    if contexto_extra: system += f"\n\nINFO EXTRA: {contexto_extra}"
    
    mensagens = [{"role": "system", "content": system}]
    u = get_usuario(user_id)
    for linha in u["historico"][-14:]:
        if linha.startswith("U:"): mensagens.append({"role": "user", "content": linha[2:]})
        elif linha.startswith("E:"): mensagens.append({"role": "assistant", "content": linha[2:]})
    mensagens.append({"role": "user", "content": texto})
    return mensagens

# ─────────────────────────────────────────────────────────────
# IA
# ─────────────────────────────────────────────────────────────

async def chamar_groq(mensagens):
    from openai import OpenAI
    cli = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
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
    if nome_discord and not u["nome"]: u["nome"] = nome_discord
    contexto_extra = None

    if deve_buscar(texto):
        resultado = await buscar_duckduckgo(texto)
        if resultado: contexto_extra = resultado

    mensagens = montar_mensagens(user_id, texto, contexto_extra)

    try:
        resposta = await chamar_groq(mensagens)
    except Exception as e:
        print(f"ERRO IA: {e}")
        return "..."

    atualizar_memoria_usuario(user_id, texto, resposta)
    await salvar_memoria_async()
    return resposta[:300]

# ─────────────────────────────────────────────────────────────
# ELEVENLABS (Agora Assíncrono com aiohttp)
# ─────────────────────────────────────────────────────────────

async def gerar_audio(texto):
    try:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
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
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data, headers=headers, timeout=30) as r:
                if r.status == 200:
                    audio_data = await r.read()
                    return io.BytesIO(audio_data)
                print(f"ERRO ELEVENLABS: {await r.text()}")
                return None
    except Exception as e:
        print(f"ERRO AUDIO: {e}")
        return None

# ─────────────────────────────────────────────────────────────
# DISCORD EVENTS
# ─────────────────────────────────────────────────────────────

@client.event
async def on_ready():
    print(f"Eva online como {client.user}")

@client.event
async def on_message(message):
    if message.author.bot or not message.guild: return
    if em_cooldown(message.author.id): return

    texto = message.content.strip()
    guild_id = message.guild.id

    # PLAY
    if texto.startswith("eva/play "):
        query = texto.replace("eva/play ", "").strip()
        vc, erro = await entrar_canal_voz(message)
        if erro:
            await message.reply(erro)
            return
        
        url, titulo = await get_audio_url(query)
        if not url:
            await message.reply("youtube bloqueou essa música, tenta de novo ou com outro nome")
            return

        if guild_id not in filas_musica: filas_musica[guild_id] = []

        if vc.is_playing():
            filas_musica[guild_id].append((url, titulo))
            await message.reply(f"adicionei: {titulo}")
        else:
            filas_musica[guild_id].insert(0, (url, titulo))
            tocando = await tocar_proxima(guild_id)
            await message.reply(f"tocando: {tocando}")
        return

    # SKIP
    if texto == "eva/skip":
        vc = voice_clients.get(guild_id)
        if vc and vc.is_playing():
            vc.stop()
            await message.reply("skipado")
        else: await message.reply("n tem nada tocando")
        return

    # STOP
    if texto == "eva/stop":
        vc = voice_clients.get(guild_id)
        if vc:
            filas_musica[guild_id] = []
            await vc.disconnect()
            voice_clients.pop(guild_id, None)
            await message.reply("parei")
        return

    # FILA
    if texto == "eva/fila":
        fila = filas_musica.get(guild_id, [])
        if not fila:
            await message.reply("fila vazia")
            return
        lista = "\n".join([f"{i+1}. {t}" for i, (_, t) in enumerate(fila[:10])])
        await message.reply(f"```\n{lista}\n```")
        return

    # CHAT
    ativar = texto.startswith("eva/") or texto.startswith("evac/") or client.user in message.mentions
    if not ativar: return

    texto_limpo = texto.replace("eva/", "").replace("evac/", "").replace(f"<@{client.user.id}>", "").strip()
    if not texto_limpo: texto_limpo = "oi"

    async with message.channel.typing():
        await asyncio.sleep(random.uniform(0.8, 2.0))
        resposta = await gerar_texto(message.author.id, texto_limpo, message.author.display_name)

        if texto.startswith("evac/"):
            audio = await gerar_audio(resposta)  # Agora usando await
            if audio:
                arquivo = discord.File(fp=audio, filename="eva.mp3")
                await message.reply(content=resposta, file=arquivo)
            else: await message.reply(resposta)
        else:
            await message.reply(resposta)

# ─────────────────────────────────────────────────────────────
# OPUS
# ─────────────────────────────────────────────────────────────

try:
    discord.opus.load_opus("libopus.so.0")
except: pass

# ─────────────────────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────────────────────

client.run(DISCORD_TOKEN)
