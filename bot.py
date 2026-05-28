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

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROK_API_KEY = os.getenv("GROK_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
client = discord.Client(intents=intents)

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

# ─── ESTADO EMOCIONAL ──────────────────────────────────────────────────────────

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
    ("tomou café", "um pouco melhor", 30),
    ("fome", "impaciente", 40),
    ("cansaço extremo", "exausta", 60),
    ("ouvindo música boa", "mais relaxada", 35),
    ("briga no grupo", "agitada", 25),
]

def humor_pela_hora():
    hora = datetime.now().hour
    if 2 <= hora < 6:
        return random.choice(["de ressaca", "acordada à toa", "exausta"])
    elif 6 <= hora < 9:
        return random.choice(["sonolenta", "mal humorada", "no automático"])
    elif 9 <= hora < 12:
        return random.choice(["neutra", "no trabalho", "entediada"])
    elif 12 <= hora < 14:
        return random.choice(["com fome", "um pouco melhor", "distraída"])
    elif 14 <= hora < 18:
        return random.choice(["entediada", "cansada", "com sono"])
    elif 18 <= hora < 22:
        return random.choice(["mais solta", "animada", "em casa vendo série"])
    else:
        return random.choice(["agitada", "com sono", "rolando na cama"])

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
        "de noite" if hora < 22 else
        "de madrugada"
    )
    if estado_atual["evento"]:
        return f"{periodo}, humor: {estado_atual['humor']} (motivo: {estado_atual['evento']})"
    return f"{periodo}, humor: {estado_atual['humor']}"

# ─── COOLDOWN ──────────────────────────────────────────────────────────────────

cooldowns = {}

def em_cooldown(user_id):
    agora = datetime.now()
    if user_id in cooldowns and agora < cooldowns[user_id]:
        return True
    cooldowns[user_id] = agora + timedelta(seconds=3)
    return False

# ─── MEMÓRIA RICA ──────────────────────────────────────────────────────────────

def get_usuario(user_id):
    uid = str(user_id)
    if uid not in memoria:
        memoria[uid] = {
            "nome": None,
            "apelido": None,
            "opiniao": None,
            "assuntos": [],
            "fatos": [],
            "historico": [],
            "total_msgs": 0,
            "primeira_vez": datetime.now().isoformat(),
        }
    return memoria[uid]

def atualizar_memoria_usuario(user_id, texto_usuario, resposta_eva):
    u = get_usuario(user_id)
    u["total_msgs"] = u.get("total_msgs", 0) + 1

    gatilhos_fatos = ["meu nome é", "eu tenho", "eu moro", "eu trabalho", "eu estudo",
                      "sou de", "tenho", "moro em", "trabalho em", "to namorando",
                      "terminei", "fui demitido", "passei em", "reprovei"]
    texto_lower = texto_usuario.lower()
    for g in gatilhos_fatos:
        if g in texto_lower:
            fato = texto_usuario[:80]
            if fato not in u["fatos"]:
                u["fatos"].append(fato)
                if len(u["fatos"]) > 10:
                    u["fatos"] = u["fatos"][-10:]
            break

    temas = {
        "música": ["música", "banda", "show", "playlist", "ouvindo"],
        "relacionamento": ["namorado", "namorada", "crush", "ex", "ficante", "término"],
        "trabalho": ["trabalho", "emprego", "chefe", "salário", "demiti"],
        "faculdade": ["faculdade", "prova", "professor", "aula", "semestre"],
        "jogo": ["jogo", "game", "ranked", "partida", "personagem"],
        "série/filme": ["série", "filme", "episódio", "netflix", "assistindo"],
    }
    for tema, palavras in temas.items():
        if any(p in texto_lower for p in palavras):
            if tema not in u["assuntos"]:
                u["assuntos"].append(tema)
            break

    u["historico"].append(f"U:{texto_usuario}")
    u["historico"].append(f"E:{resposta_eva}")
    if len(u["historico"]) > 30:
        u["historico"] = u["historico"][-30:]

def montar_contexto_usuario(user_id):
    u = get_usuario(user_id)
    partes = []
    if u["nome"]:
        partes.append(f"nome: {u['nome']}")
    if u["apelido"]:
        partes.append(f"Eva chama de: {u['apelido']}")
    if u["opiniao"]:
        partes.append(f"Eva acha: {u['opiniao']}")
    if u["fatos"]:
        partes.append(f"revelou: {' | '.join(u['fatos'][-4:])}")
    if u["assuntos"]:
        partes.append(f"assuntos: {', '.join(u['assuntos'])}")
    total = u.get("total_msgs", 0)
    if total == 0:
        partes.append("primeira conversa")
    elif total < 5:
        partes.append("pessoa nova")
    elif total < 20:
        partes.append("já conversaram algumas vezes")
    else:
        partes.append("fala bastante com a Eva")
    return " | ".join(partes) if partes else "pessoa nova"

# ─── BUSCA DUCKDUCKGO ──────────────────────────────────────────────────────────

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

        resultado = ""
        if data.get("AbstractText"):
            resultado = data["AbstractText"][:400]
        elif data.get("RelatedTopics"):
            for t in data["RelatedTopics"][:3]:
                if isinstance(t, dict) and t.get("Text"):
                    resultado += t["Text"][:150] + " "

        return resultado.strip() if resultado else None
    except Exception as e:
        print(f"ERRO BUSCA: {e}")
        return None

def deve_buscar(texto):
    gatilhos = [
        "o que é", "quem é", "quando foi", "quando é", "o que aconteceu",
        "qual é", "como funciona", "me fala sobre", "sabe sobre",
        "notícia", "novidade", "lançou", "saiu", "estreou",
        "resultado", "placar", "ganhou", "perdeu", "venceu"
    ]
    return any(g in texto.lower() for g in gatilhos)

# ─── MÚSICA ────────────────────────────────────────────────────────────────────

filas_musica = {}  # guild_id -> lista de urls
voice_clients = {}  # guild_id -> voice_client

YTDL_OPTS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    # Simula um iPhone para contornar restrições de DRM/Região
    "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
}

FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

async def get_audio_url(query):
    with yt_dlp.YoutubeDL(YTDL_OPTS) as ydl:
        info = await asyncio.to_thread(lambda: ydl.extract_info(f"ytsearch:{query}", download=False))
        if "entries" in info and info["entries"]:
            entry = info["entries"][0]
            return entry["url"], entry.get("title", query)
        return None, None

async def tocar_proxima(guild_id):
    if guild_id not in filas_musica or not filas_musica[guild_id]:
        return

    vc = voice_clients.get(guild_id)
    if not vc or not vc.is_connected():
        return

    url, titulo = filas_musica[guild_id].pop(0)

    def depois(error):
        if error:
            print(f"ERRO MUSICA: {error}")
        asyncio.run_coroutine_threadsafe(tocar_proxima(guild_id), client.loop)

    source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTS)
    vc.play(source, after=depois)
    return titulo

async def entrar_canal_voz(message):
    if not message.author.voice:
        return None, "vc nem tá em canal de voz"
    canal = message.author.voice.channel
    guild_id = message.guild.id

    if guild_id in voice_clients and voice_clients[guild_id].is_connected():
        return voice_clients[guild_id], None

    vc = await canal.connect()
    voice_clients[guild_id] = vc
    return vc, None

# ─── PROMPT ────────────────────────────────────────────────────────────────────

PERSONALIDADE = """Você é Eva, 20 anos, brasileira.

HISTÓRIA:
Cresceu numa família comum, saiu de casa cedo. Divide apartamento com uma amiga.
Trabalha meio período num café e faz faculdade de design à noite.
Gosta de música alternativa, filmes de terror, tatuagens e ficar no celular até tarde.
Já teve relacionamentos complicados, hoje prefere não se prender.

PERSONALIDADE:
- fria por padrão mas não por maldade
- sarcástica, debochada, humor negro
- inteligente, observadora
- NUNCA admite que é IA ou robô
- NUNCA é educada demais
- NUNCA escreve textão

MEMÓRIA:
- usa contexto do usuário pra personalizar respostas
- age com mais familiaridade com quem fala muito com ela
- lembra de assuntos e fatos que a pessoa revelou

COMO FALA:
- internetês: vc, pq, kk, nao, tbm, msm, hj
- respostas curtas, 1-2 linhas
- às vezes só "kk" ou "..."
- não explica, não justifica

EXEMPLOS:
usuário: oi / Eva: hm
usuário: tudo bem? / Eva: tanto faz
usuário: vc é robô? / Eva: q delírio"""

def montar_mensagens(user_id, texto, contexto_extra=None):
    atualizar_estado()
    estado = descrever_estado()
    contexto = montar_contexto_usuario(user_id)

    system = f"{PERSONALIDADE}\n\nESTADO ATUAL: {estado}\nUSUÁRIO: {contexto}"
    if contexto_extra:
        system += f"\n\nINFO RELEVANTE (use naturalmente, não copie): {contexto_extra}"

    mensagens = [{"role": "system", "content": system}]
    u = get_usuario(user_id)
    for linha in u["historico"][-14:]:
        if linha.startswith("U:"):
            mensagens.append({"role": "user", "content": linha[2:]})
        elif linha.startswith("E:"):
            mensagens.append({"role": "assistant", "content": linha[2:]})
    mensagens.append({"role": "user", "content": texto})
    return mensagens

# ─── IAs ───────────────────────────────────────────────────────────────────────

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

async def chamar_grok(mensagens):
    from openai import OpenAI
    cli = OpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")
    r = await asyncio.to_thread(
        lambda: cli.chat.completions.create(
            model="grok-2-latest",
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

    mensagens = montar_mensagens(user_id, texto, contexto_extra)
    resposta_final = None

    if GROQ_API_KEY:
        try:
            resposta_final = await chamar_groq(mensagens)
        except Exception as e:
            print(f"ERRO GROQ: {e}")

    if not resposta_final and GROK_API_KEY:
        try:
            resposta_final = await chamar_grok(mensagens)
        except Exception as e:
            print(f"ERRO GROK: {e}")

    if not resposta_final:
        return "..."

    if len(resposta_final) > 300:
        resposta_final = resposta_final[:300]

    atualizar_memoria_usuario(user_id, texto, resposta_final)
    salvar_memoria()
    return resposta_final

# ─── ÁUDIO ─────────────────────────────────────────────────────────────────────

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
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.45, "similarity_boost": 0.8}
        }
        r = requests.post(url, json=data, headers=headers, timeout=30)
        if r.status_code == 200:
            return io.BytesIO(r.content)
        print(f"ERRO ELEVENLABS: {r.text}")
        return None
    except Exception as e:
        print(f"ERRO AUDIO: {e}")
        return None

# ─── DISCORD ───────────────────────────────────────────────────────────────────

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

    # ── comando: esquecer ──
    if texto == "eva/esquece":
        uid = str(message.author.id)
        if uid in memoria:
            memoria[uid] = {
                "nome": None, "apelido": None, "opiniao": None,
                "assuntos": [], "fatos": [], "historico": [],
                "total_msgs": 0, "primeira_vez": datetime.now().isoformat()
            }
            salvar_memoria()
        await message.reply("ok")
        return

    # ── comandos de música ──
    if texto.startswith("eva/play "):
        query = texto.replace("eva/play ", "").strip()
        vc, erro = await entrar_canal_voz(message)
        if erro:
            await message.reply(erro)
            return

        url, titulo = await get_audio_url(query)
        if not url:
            await message.reply("n achei isso não")
            return

        if guild_id not in filas_musica:
            filas_musica[guild_id] = []

        if vc.is_playing():
            filas_musica[guild_id].append((url, titulo))
            await message.reply(f"adicionei na fila: {titulo}")
        else:
            filas_musica[guild_id].insert(0, (url, titulo))
            tocando = await tocar_proxima(guild_id)
            await message.reply(f"tocando: {tocando}")
        return

    if texto == "eva/skip":
        vc = voice_clients.get(guild_id)
        if vc and vc.is_playing():
            vc.stop()
            await message.reply("ok")
        else:
            await message.reply("n tô tocando nada")
        return

    if texto == "eva/stop":
        vc = voice_clients.get(guild_id)
        if vc:
            filas_musica[guild_id] = []
            await vc.disconnect()
            voice_clients.pop(guild_id, None)
            await message.reply("ok")
        return

    if texto == "eva/fila":
        fila = filas_musica.get(guild_id, [])
        if not fila:
            await message.reply("fila vazia")
        else:
            lista = "\n".join([f"{i+1}. {t}" for i, (_, t) in enumerate(fila[:10])])
            await message.reply(f"```\n{lista}\n```")
        return

    # ── resposta normal ──
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
        await asyncio.sleep(random.uniform(0.8, 2.0))
        resposta = await gerar_texto(message.author.id, texto_limpo, message.author.display_name)

        if texto.startswith("evac/"):
            audio = gerar_audio(resposta)
            if audio:
                arquivo = discord.File(fp=audio, filename="eva.mp3")
                await message.reply(content=resposta, file=arquivo)
            else:
                await message.reply(resposta)
        else:
            await message.reply(resposta)

client.run(DISCORD_TOKEN)