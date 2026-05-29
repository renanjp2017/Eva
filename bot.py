import discord
import io
import random
import asyncio
import os
import sqlite3
import yt_dlp
import logging
import aiohttp

from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN    = os.getenv("DISCORD_TOKEN")
GROK_API_KEY     = os.getenv("GROK_API_KEY")
GROQ_API_KEY     = os.getenv("GROQ_API_KEY")
ELEVENLABS_API_KEY  = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")

logging.getLogger("discord").setLevel(logging.ERROR)

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
client = discord.Client(intents=intents)

# ─── SQLITE ────────────────────────────────────────────────────

def init_db():
    con = sqlite3.connect("eva.db")
    cur = con.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS usuarios (
            user_id TEXT PRIMARY KEY,
            nome TEXT,
            apelido TEXT,
            opiniao TEXT,
            total_msgs INTEGER DEFAULT 0,
            primeira_vez TEXT
        );
        CREATE TABLE IF NOT EXISTS fatos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            fato TEXT
        );
        CREATE TABLE IF NOT EXISTS assuntos (
            user_id TEXT,
            assunto TEXT,
            UNIQUE(user_id, assunto)
        );
        CREATE TABLE IF NOT EXISTS historico (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            role TEXT,
            conteudo TEXT,
            ts TEXT DEFAULT (datetime('now'))
        );
    """)
    con.commit()
    con.close()

init_db()

def get_db():
    con = sqlite3.connect("eva.db")
    con.row_factory = sqlite3.Row
    return con

def get_ou_criar_usuario(user_id, nome=None):
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM usuarios WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if not row:
        cur.execute(
            "INSERT INTO usuarios (user_id,nome,primeira_vez) VALUES (?,?,?)",
            (user_id, nome, datetime.now().isoformat())
        )
        con.commit()
    elif nome and not row["nome"]:
        cur.execute("UPDATE usuarios SET nome=? WHERE user_id=?", (nome, user_id))
        con.commit()
    con.close()

def salvar_mensagem(user_id, role, conteudo):
    con = get_db()
    con.execute(
        "INSERT INTO historico (user_id,role,conteudo) VALUES (?,?,?)",
        (user_id, role, conteudo)
    )
    # mantém só as últimas 30 por usuário
    con.execute("""
        DELETE FROM historico WHERE id IN (
            SELECT id FROM historico WHERE user_id=?
            ORDER BY id DESC LIMIT -1 OFFSET 30
        )
    """, (user_id,))
    con.execute(
        "UPDATE usuarios SET total_msgs=total_msgs+1 WHERE user_id=?",
        (user_id,)
    )
    con.commit()
    con.close()

def get_historico(user_id, n=14):
    con = get_db()
    rows = con.execute(
        "SELECT role,conteudo FROM historico WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, n)
    ).fetchall()
    con.close()
    return list(reversed(rows))

def get_usuario_info(user_id):
    con = get_db()
    u = con.execute("SELECT * FROM usuarios WHERE user_id=?", (user_id,)).fetchone()
    fatos = con.execute("SELECT fato FROM fatos WHERE user_id=? LIMIT 4", (user_id,)).fetchall()
    assuntos = con.execute("SELECT assunto FROM assuntos WHERE user_id=?", (user_id,)).fetchall()
    con.close()
    return u, [f["fato"] for f in fatos], [a["assunto"] for a in assuntos]

def salvar_fato(user_id, texto):
    gatilhos = ["meu nome é", "eu moro", "eu trabalho", "eu estudo", "sou de",
                "to namorando", "terminei", "fui demitido", "passei em", "reprovei",
                "tenho namorad", "moro em", "trabalho em"]
    for g in gatilhos:
        if g in texto.lower():
            con = get_db()
            fatos = [r["fato"] for r in con.execute(
                "SELECT fato FROM fatos WHERE user_id=?", (user_id,)).fetchall()]
            if texto[:80] not in fatos:
                con.execute("INSERT INTO fatos (user_id,fato) VALUES (?,?)", (user_id, texto[:80]))
                con.commit()
            con.close()
            break

def salvar_assunto(user_id, texto):
    temas = {
        "música":       ["música", "banda", "show", "playlist", "ouvindo"],
        "relacionamento": ["namorado", "namorada", "crush", "ex", "término", "ficante"],
        "trabalho":     ["trabalho", "emprego", "chefe", "salário", "demiti"],
        "faculdade":    ["faculdade", "prova", "professor", "aula", "semestre"],
        "jogo":         ["jogo", "game", "ranked", "partida", "personagem"],
        "série/filme":  ["série", "filme", "netflix", "assistindo", "episódio"],
    }
    texto_l = texto.lower()
    for tema, palavras in temas.items():
        if any(p in texto_l for p in palavras):
            con = get_db()
            con.execute(
                "INSERT OR IGNORE INTO assuntos (user_id,assunto) VALUES (?,?)",
                (user_id, tema)
            )
            con.commit()
            con.close()
            break

def limpar_usuario(user_id):
    con = get_db()
    for t in ["fatos", "assuntos", "historico"]:
        con.execute(f"DELETE FROM {t} WHERE user_id=?", (user_id,))
    con.execute(
        "UPDATE usuarios SET apelido=NULL,opiniao=NULL,total_msgs=0 WHERE user_id=?",
        (user_id,)
    )
    con.commit()
    con.close()

def montar_contexto(user_id):
    u, fatos, assuntos = get_usuario_info(user_id)
    partes = []
    if u:
        if u["nome"]:    partes.append(f"nome: {u['nome']}")
        if u["apelido"]: partes.append(f"apelido: {u['apelido']}")
        if u["opiniao"]: partes.append(f"Eva acha: {u['opiniao']}")
        total = u["total_msgs"] or 0
        if total == 0:   partes.append("primeira conversa")
        elif total < 10: partes.append("já conversaram algumas vezes")
        else:            partes.append("fala bastante com a Eva")
    if fatos:    partes.append(f"revelou: {' | '.join(fatos)}")
    if assuntos: partes.append(f"assuntos: {', '.join(assuntos)}")
    return " | ".join(partes) if partes else "pessoa nova"

# ─── ESTADO EMOCIONAL ──────────────────────────────────────────

estado = {"humor": "neutra", "evento": None, "expira": None}

EVENTOS = [
    ("perdeu o ônibus",   "brava",         30),
    ("travou o celular",  "irritada",       20),
    ("alguém a ignorou",  "mal humorada",   40),
    ("comeu mal",         "indisposta",     60),
    ("viu algo engraçado","de bom humor",   25),
    ("recebeu elogio",    "levemente feliz",30),
    ("tédio extremo",     "entediada demais",45),
    ("dor de cabeça",     "grossa",         90),
    ("ressaca leve",      "de ressaca",    120),
    ("TPM",               "irritadíssima", 480),
    ("tomou café",        "um pouco melhor",30),
    ("fome",              "impaciente",     40),
    ("cansaço extremo",   "exausta",        60),
    ("ouvindo música boa","mais relaxada",  35),
]

def humor_base():
    h = datetime.now().hour
    if 2  <= h < 6:  return random.choice(["exausta","acordada à toa"])
    if 6  <= h < 9:  return random.choice(["sonolenta","mal humorada"])
    if 9  <= h < 12: return random.choice(["neutra","entediada"])
    if 12 <= h < 14: return random.choice(["com fome","distraída"])
    if 14 <= h < 18: return random.choice(["cansada","com sono"])
    if 18 <= h < 22: return random.choice(["animada","mais solta"])
    return random.choice(["agitada","rolando na cama"])

def atualizar_estado():
    agora = datetime.now()
    if estado["expira"] and agora > estado["expira"]:
        estado["evento"] = None
        estado["expira"] = None
    if not estado["evento"] and random.random() < 0.08:
        ev, hm, dur = random.choice(EVENTOS)
        estado["evento"] = ev
        estado["humor"]  = hm
        estado["expira"] = agora + timedelta(minutes=dur)
    elif not estado["evento"]:
        estado["humor"] = humor_base()

def desc_estado():
    h = datetime.now().hour
    p = ("de madrugada" if h<6 else "de manhã cedo" if h<9 else "de manhã" if h<12
         else "na hora do almoço" if h<14 else "de tarde" if h<18
         else "de noite" if h<22 else "de madrugada")
    if estado["evento"]:
        return f"{p}, humor: {estado['humor']} (motivo: {estado['evento']})"
    return f"{p}, humor: {estado['humor']}"

# ─── COOLDOWN ──────────────────────────────────────────────────

cooldowns = {}
def em_cooldown(uid):
    agora = datetime.now()
    if uid in cooldowns and agora < cooldowns[uid]:
        return True
    cooldowns[uid] = agora + timedelta(seconds=3)
    return False

# ─── BUSCA DUCKDUCKGO ──────────────────────────────────────────

GATILHOS_BUSCA = ["o que é","quem é","como funciona","me fala sobre",
                  "notícia","resultado","placar","quando é","o que aconteceu",
                  "qual é","sabe oq","sabe o que"]

async def buscar(query):
    try:
        params = {"q": query, "format": "json", "no_html": 1, "skip_disambig": 1}
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.duckduckgo.com/", params=params,
                             timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status == 200:
                    d = await r.json(content_type=None)
                    if d.get("AbstractText"):
                        return d["AbstractText"][:400]
    except Exception as e:
        print(f"BUSCA ERR: {e}")
    return None

def deve_buscar(txt):
    return any(g in txt.lower() for g in GATILHOS_BUSCA)

# ─── MÚSICA ────────────────────────────────────────────────────

filas   = {}   # guild_id -> [(url, titulo)]
vcs     = {}   # guild_id -> VoiceClient
tocando = {}   # guild_id -> titulo

YTDL_OPTS = {
    "format": "bestaudio/best[ext=webm]/bestaudio/best",
    "ignoreerrors": True,
    "quiet": True,
    "no_warnings": True,
    "nocheckcertificate": True,
    "extractor_args": {"youtube": {"player_client": ["ios", "mweb", "web"]}},
}

FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn -bufsize 64k",
}

async def resolver_url(query):
    try:
        eh_link = "youtube.com/" in query or "youtu.be/" in query
        busca   = query if eh_link else f"ytsearch1:{query}"
        with yt_dlp.YoutubeDL(YTDL_OPTS) as ydl:
            info = await asyncio.to_thread(lambda: ydl.extract_info(busca, download=False))
        if not info:
            return None, None
        entry = info["entries"][0] if "entries" in info else info
        return entry.get("url"), entry.get("title", query)
    except Exception as e:
        print(f"YTDLP ERR: {e}")
        return None, None

async def play_proximo(guild_id):
    if not filas.get(guild_id):
        tocando.pop(guild_id, None)
        vc = vcs.get(guild_id)
        if vc and vc.is_connected():
            await asyncio.sleep(2)
            if not filas.get(guild_id):
                await vc.disconnect()
                vcs.pop(guild_id, None)
        return

    vc = vcs.get(guild_id)
    if not vc or not vc.is_connected():
        return

    url, titulo = filas[guild_id].pop(0)
    tocando[guild_id] = titulo

    def depois(err):
        if err: print(f"PLAY ERR: {err}")
        asyncio.run_coroutine_threadsafe(play_proximo(guild_id), client.loop)

    try:
        src = discord.FFmpegPCMAudio(url, executable="ffmpeg", **FFMPEG_OPTS)
        vc.play(discord.PCMVolumeTransformer(src, volume=0.8), after=depois)
    except Exception as e:
        print(f"FFMPEG ERR: {e}")

async def entrar_voz(message):
    if not message.author.voice:
        return None, "vc nem tá em canal"
    canal    = message.author.voice.channel
    guild_id = message.guild.id
    existing = message.guild.voice_client
    if existing and existing.is_connected():
        if existing.channel.id != canal.id:
            await existing.move_to(canal)
        vcs[guild_id] = existing
        return existing, None
    try:
        vc = await canal.connect(timeout=20, reconnect=True, self_deaf=True)
        vcs[guild_id] = vc
        return vc, None
    except Exception as e:
        return None, f"erro ao conectar: {e}"

# ─── PERSONALIDADE ─────────────────────────────────────────────

SISTEMA = """Você é Eva, 20 anos, brasileira.

HISTÓRIA:
Cresceu numa família comum, saiu de casa cedo. Divide apartamento com uma amiga.
Trabalha meio período num café e faz faculdade de design à noite.
Gosta de música alternativa, filmes de terror, tatuagens e ficar no celular até tarde.
Já teve relacionamentos complicados, hoje prefere não se prender.
Online é mais ela mesma do que na vida real.

PERSONALIDADE:
- fria por padrão, não por maldade — é defesa
- sarcástica, debochada, humor negro
- inteligente, observadora, não é boba
- quando gosta de alguém fica levemente menos grossa (só levemente)
- quando tá mal é curta e grossa
- NUNCA admite que é IA ou robô — reage com deboche
- NUNCA é educada demais
- NUNCA escreve textão

COMO FALA:
- internetês: vc, pq, kk, nao, tbm, msm, hj, td, aq
- respostas curtas, 1-2 linhas no máximo
- às vezes só "kk" ou "..." ou ignora parte da mensagem
- não explica, não justifica, não pede desculpa

EXEMPLOS:
oi → hm
tudo bem? → tanto faz
vc é robô? → q delírio
me ajuda → depende do entretenimento envolvido
vc é estranha → e vc continua falando comigo"""

def montar_msgs(user_id, texto, extra=None):
    atualizar_estado()
    sys = f"{SISTEMA}\n\nESTADO: {desc_estado()}\nUSUÁRIO: {montar_contexto(user_id)}"
    if extra:
        sys += f"\n\nINFO (use naturalmente, não copie): {extra}"
    msgs = [{"role": "system", "content": sys}]
    for row in get_historico(user_id):
        msgs.append({"role": row["role"], "content": row["conteudo"]})
    msgs.append({"role": "user", "content": texto})
    return msgs

# ─── IA ────────────────────────────────────────────────────────

async def chamar_groq(msgs):
    from openai import AsyncOpenAI
    cli = AsyncOpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
    r = await cli.chat.completions.create(
        model="llama-3.3-70b-versatile", messages=msgs,
        max_tokens=120, temperature=0.92
    )
    return r.choices[0].message.content.strip()

async def chamar_grok(msgs):
    from openai import AsyncOpenAI
    cli = AsyncOpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")
    r = await cli.chat.completions.create(
        model="grok-2-latest", messages=msgs,
        max_tokens=120, temperature=0.92
    )
    return r.choices[0].message.content.strip()

async def gerar(user_id, texto, nome=None):
    get_ou_criar_usuario(user_id, nome)
    salvar_fato(user_id, texto)
    salvar_assunto(user_id, texto)

    extra = None
    if deve_buscar(texto):
        extra = await buscar(texto)

    msgs = montar_msgs(user_id, texto, extra)
    resp = None

    if GROQ_API_KEY:
        try:    resp = await chamar_groq(msgs)
        except Exception as e: print(f"GROQ ERR: {e}")

    if not resp and GROK_API_KEY:
        try:    resp = await chamar_grok(msgs)
        except Exception as e: print(f"GROK ERR: {e}")

    if not resp:
        return "..."

    resp = resp[:300]
    salvar_mensagem(user_id, "user",      texto)
    salvar_mensagem(user_id, "assistant", resp)
    return resp

# ─── ELEVENLABS ────────────────────────────────────────────────

async def gerar_audio(texto):
    if not ELEVENLABS_API_KEY or not ELEVENLABS_VOICE_ID:
        return None
    try:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
        hdrs = {"Accept":"audio/mpeg","Content-Type":"application/json",
                "xi-api-key": ELEVENLABS_API_KEY}
        data = {"text": texto, "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability":0.45,"similarity_boost":0.8}}
        async with aiohttp.ClientSession() as s:
            async with s.post(url, json=data, headers=hdrs,
                              timeout=aiohttp.ClientTimeout(total=30)) as r:
                if r.status == 200:
                    return io.BytesIO(await r.read())
                print(f"ELEVEN ERR {r.status}: {await r.text()}")
    except Exception as e:
        print(f"AUDIO ERR: {e}")
    return None

# ─── DISCORD ───────────────────────────────────────────────────

@client.event
async def on_ready():
    print(f"Eva online — {client.user}")

@client.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return
    if em_cooldown(message.author.id):
        return

    txt      = message.content.strip()
    uid      = str(message.author.id)
    guild_id = message.guild.id

    # ── eva/esquece ──
    if txt == "eva/esquece":
        limpar_usuario(uid)
        await message.reply("ok")
        return

    # ── eva/play ──
    if txt.lower().startswith("eva/play "):
        query = txt[9:].strip()
        vc, err = await entrar_voz(message)
        if err:
            await message.reply(err)
            return

        async with message.channel.typing():
            url, titulo = await resolver_url(query)

        if not url:
            await message.reply("n achei isso não")
            return

        filas.setdefault(guild_id, [])
        if vc.is_playing() or vc.is_paused():
            filas[guild_id].append((url, titulo))
            pos = len(filas[guild_id])
            await message.reply(f"fila #{pos}: {titulo}")
        else:
            filas[guild_id].insert(0, (url, titulo))
            await play_proximo(guild_id)
            await message.reply(f"tocando: {titulo}")
        return

    # ── eva/skip ──
    if txt == "eva/skip":
        vc = vcs.get(guild_id)
        if vc and vc.is_playing():
            vc.stop()
            await message.reply("ok")
        else:
            await message.reply("n tem nada tocando")
        return

    # ── eva/stop ──
    if txt == "eva/stop":
        filas[guild_id] = []
        vc = vcs.get(guild_id)
        if vc:
            await vc.disconnect()
            vcs.pop(guild_id, None)
        await message.reply("parei")
        return

    # ── eva/fila ──
    if txt == "eva/fila":
        fila = filas.get(guild_id, [])
        atual = tocando.get(guild_id)
        if not fila and not atual:
            await message.reply("fila vazia")
            return
        linhas = []
        if atual: linhas.append(f"▶ {atual}")
        linhas += [f"{i+1}. {t}" for i, (_, t) in enumerate(fila[:10])]
        await message.reply("```\n" + "\n".join(linhas) + "\n```")
        return

    # ── resposta normal ──
    ativar = (
        txt.startswith("eva/")
        or txt.startswith("evac/")
        or client.user in message.mentions
    )
    if not ativar:
        return

    texto_limpo = (
        txt
        .replace("eva/",  "")
        .replace("evac/", "")
        .replace(f"<@{client.user.id}>", "")
        .strip()
    ) or "oi"

    async with message.channel.typing():
        await asyncio.sleep(random.uniform(0.8, 2.0))
        resp = await gerar(uid, texto_limpo, message.author.display_name)

    if txt.startswith("evac/"):
        audio = await gerar_audio(resp)
        if audio:
            tmp = f"/tmp/eva_{uid}.mp3"
            try:
                with open(tmp, "wb") as f:
                    f.write(audio.getbuffer())
                await message.reply(content=resp, file=discord.File(tmp, "eva.mp3"))
            except:
                await message.reply(resp)
            finally:
                if os.path.exists(tmp): os.remove(tmp)
        else:
            await message.reply(resp)
    else:
        await message.reply(resp)

try:
    discord.opus.load_opus("libopus.so.0")
except:
    pass

client.run(DISCORD_TOKEN)
