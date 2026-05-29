cat > /mnt/user-data/outputs/bot.py << 'BOTEOF'
import discord
import io
import re
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

DISCORD_TOKEN       = os.getenv("DISCORD_TOKEN")
GROK_API_KEY        = os.getenv("GROK_API_KEY")
GROQ_API_KEY        = os.getenv("GROQ_API_KEY")
ELEVENLABS_API_KEY  = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")

logging.getLogger("discord").setLevel(logging.ERROR)

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states    = True
client = discord.Client(intents=intents)

# ─── SQLITE ────────────────────────────────────────────────────

def init_db():
    con = sqlite3.connect("eva.db")
    con.executescript("""
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
            user_id TEXT, fato TEXT
        );
        CREATE TABLE IF NOT EXISTS assuntos (
            user_id TEXT, assunto TEXT,
            UNIQUE(user_id, assunto)
        );
        CREATE TABLE IF NOT EXISTS historico (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT, role TEXT, conteudo TEXT,
            ts TEXT DEFAULT (datetime('now'))
        );
    """)
    con.commit(); con.close()

init_db()

def db():
    con = sqlite3.connect("eva.db")
    con.row_factory = sqlite3.Row
    return con

def get_ou_criar(user_id, nome=None):
    con = db()
    row = con.execute("SELECT * FROM usuarios WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        con.execute("INSERT INTO usuarios (user_id,nome,primeira_vez) VALUES (?,?,?)",
                    (user_id, nome, datetime.now().isoformat()))
        con.commit()
    elif nome and row["nome"] is None:
        con.execute("UPDATE usuarios SET nome=? WHERE user_id=?", (nome, user_id))
        con.commit()
    con.close()

def salvar_msg(user_id, role, conteudo):
    con = db()
    con.execute("INSERT INTO historico (user_id,role,conteudo) VALUES (?,?,?)",
                (user_id, role, conteudo))
    con.execute("""DELETE FROM historico WHERE id IN (
        SELECT id FROM historico WHERE user_id=? ORDER BY id DESC LIMIT -1 OFFSET 30
    )""", (user_id,))
    con.execute("UPDATE usuarios SET total_msgs=total_msgs+1 WHERE user_id=?", (user_id,))
    con.commit(); con.close()

def get_historico(user_id, n=14):
    con = db()
    rows = con.execute(
        "SELECT role,conteudo FROM historico WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, n)).fetchall()
    con.close()
    return list(reversed(rows))

def get_info(user_id):
    con = db()
    u  = con.execute("SELECT * FROM usuarios WHERE user_id=?", (user_id,)).fetchone()
    ft = con.execute("SELECT fato FROM fatos WHERE user_id=? LIMIT 4", (user_id,)).fetchall()
    as_ = con.execute("SELECT assunto FROM assuntos WHERE user_id=?", (user_id,)).fetchall()
    con.close()
    return u, [f["fato"] for f in ft], [a["assunto"] for a in as_]

def salvar_fato(user_id, texto):
    gatilhos = ["meu nome é","eu moro","eu trabalho","eu estudo","sou de",
                "to namorando","terminei","fui demitido","passei em","reprovei"]
    for g in gatilhos:
        if g in texto.lower():
            con = db()
            fatos = [r["fato"] for r in con.execute(
                "SELECT fato FROM fatos WHERE user_id=?", (user_id,)).fetchall()]
            if texto[:80] not in fatos:
                con.execute("INSERT INTO fatos (user_id,fato) VALUES (?,?)", (user_id, texto[:80]))
                con.commit()
            con.close(); break

def salvar_assunto(user_id, texto):
    temas = {
        "música":        ["música","banda","show","playlist","ouvindo"],
        "relacionamento":["namorado","namorada","crush","ex","término"],
        "trabalho":      ["trabalho","emprego","chefe","salário"],
        "faculdade":     ["faculdade","prova","professor","aula"],
        "jogo":          ["jogo","game","ranked","partida"],
        "série/filme":   ["série","filme","netflix","assistindo"],
    }
    for tema, palavras in temas.items():
        if any(p in texto.lower() for p in palavras):
            con = db()
            con.execute("INSERT OR IGNORE INTO assuntos (user_id,assunto) VALUES (?,?)",
                        (user_id, tema))
            con.commit(); con.close(); break

def limpar(user_id):
    con = db()
    for t in ["fatos","assuntos","historico"]:
        con.execute(f"DELETE FROM {t} WHERE user_id=?", (user_id,))
    con.execute("UPDATE usuarios SET apelido=NULL,opiniao=NULL,total_msgs=0 WHERE user_id=?",
                (user_id,))
    con.commit(); con.close()

def contexto(user_id):
    u, fatos, assuntos = get_info(user_id)
    p = []
    if u:
        if u["nome"]:    p.append(f"nome: {u['nome']}")
        if u["apelido"]: p.append(f"apelido: {u['apelido']}")
        if u["opiniao"]: p.append(f"Eva acha: {u['opiniao']}")
        t = u["total_msgs"] or 0
        if t == 0:   p.append("primeira conversa")
        elif t < 10: p.append("já conversaram")
        else:        p.append("fala bastante com a Eva")
    if fatos:    p.append(f"revelou: {' | '.join(fatos)}")
    if assuntos: p.append(f"assuntos: {', '.join(assuntos)}")
    return " | ".join(p) if p else "pessoa nova"

# ─── ESTADO EMOCIONAL ──────────────────────────────────────────

estado = {"humor": "neutra", "evento": None, "expira": None}

EVENTOS = [
    ("perdeu o ônibus","brava",30), ("travou o celular","irritada",20),
    ("alguém a ignorou","mal humorada",40), ("comeu mal","indisposta",60),
    ("viu algo engraçado","de bom humor",25), ("recebeu elogio","levemente feliz",30),
    ("tédio extremo","entediada demais",45), ("dor de cabeça","grossa",90),
    ("ressaca leve","de ressaca",120), ("TPM","irritadíssima",480),
    ("tomou café","um pouco melhor",30), ("fome","impaciente",40),
    ("cansaço extremo","exausta",60), ("ouvindo música boa","mais relaxada",35),
]

def humor_base():
    h = datetime.now().hour
    if 2<=h<6:  return random.choice(["exausta","acordada à toa"])
    if 6<=h<9:  return random.choice(["sonolenta","mal humorada"])
    if 9<=h<12: return random.choice(["neutra","entediada"])
    if 12<=h<14:return random.choice(["com fome","distraída"])
    if 14<=h<18:return random.choice(["cansada","com sono"])
    if 18<=h<22:return random.choice(["animada","mais solta"])
    return random.choice(["agitada","rolando na cama"])

def tick_estado():
    agora = datetime.now()
    if estado["expira"] and agora > estado["expira"]:
        estado["evento"] = None; estado["expira"] = None
    if not estado["evento"] and random.random() < 0.08:
        ev, hm, dur = random.choice(EVENTOS)
        estado["evento"] = ev; estado["humor"] = hm
        estado["expira"] = agora + timedelta(minutes=dur)
    elif not estado["evento"]:
        estado["humor"] = humor_base()

def desc_estado():
    h = datetime.now().hour
    p = ("de madrugada" if h<6 else "de manhã cedo" if h<9 else "de manhã" if h<12
         else "na hora do almoço" if h<14 else "de tarde" if h<18
         else "de noite" if h<22 else "de madrugada")
    return f"{p}, humor: {estado['humor']}" + (f" (motivo: {estado['evento']})" if estado["evento"] else "")

# ─── COOLDOWN ──────────────────────────────────────────────────

_cd = {}
def em_cooldown(uid):
    agora = datetime.now()
    if uid in _cd and agora < _cd[uid]: return True
    _cd[uid] = agora + timedelta(seconds=3); return False

# ─── BUSCA DUCKDUCKGO ──────────────────────────────────────────

async def ddg(query):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.duckduckgo.com/",
                             params={"q":query,"format":"json","no_html":1,"skip_disambig":1},
                             timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status == 200:
                    d = await r.json(content_type=None)
                    if d.get("AbstractText"): return d["AbstractText"][:400]
    except: pass
    return None

BUSCA_GATILHOS = ["o que é","quem é","como funciona","me fala sobre","notícia",
                  "resultado","placar","quando é","o que aconteceu","qual é"]
def deve_buscar(txt): return any(g in txt.lower() for g in BUSCA_GATILHOS)

# ─── DETECÇÃO DE INTENÇÃO DE MÚSICA ────────────────────────────

MUSICA_GATILHOS = [
    r"toc[ae]\s+(.+)", r"bota\s+(.+)", r"coloca\s+(.+)",
    r"play\s+(.+)", r"reproduz\s+(.+)", r"quero ouvir\s+(.+)",
    r"toca\s+pra\s+mim\s+(.+)", r"põe\s+(.+)",
]

def detectar_musica(txt):
    txt_l = txt.lower().strip()
    for pat in MUSICA_GATILHOS:
        m = re.search(pat, txt_l)
        if m:
            query = m.group(1).strip()
            # remove sufixos como "pra mim", "agora", etc
            query = re.sub(r"\b(pra mim|agora|por favor|pfv|pf)\b", "", query).strip()
            if len(query) > 2:
                return query
    return None

# ─── MÚSICA (INVIDIOUS + YT-DLP) ───────────────────────────────

filas   = {}
vcs     = {}
tocando = {}

INVIDIOUS = [
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://invidious.privacydev.net",
    "https://yt.drgnz.club",
    "https://invidious.fdn.fr",
]

YTDL_OPTS = {
    "format": "bestaudio/best",
    "quiet": True, "no_warnings": True,
    "nocheckcertificate": True, "ignoreerrors": True,
}

FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn -bufsize 64k",
}

async def buscar_invidious(query):
    params = {"q": query, "type": "video", "fields": "videoId,title"}
    for inst in INVIDIOUS:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{inst}/api/v1/search", params=params,
                                  timeout=aiohttp.ClientTimeout(total=8)) as r:
                    if r.status == 200:
                        data = await r.json()
                        if data: return data[0]["videoId"], data[0]["title"]
        except: continue
    return None, None

async def resolver_url(query):
    video_id = titulo = None
    if "youtube.com/watch" in query:
        m = re.search(r"v=([a-zA-Z0-9_-]{11})", query)
        if m: video_id = m.group(1)
    elif "youtu.be/" in query:
        video_id = query.split("youtu.be/")[-1].split("?")[0][:11]
    if not video_id:
        video_id, titulo = await buscar_invidious(query)
        if not video_id: return None, None
    for inst in INVIDIOUS:
        try:
            u = f"{inst}/watch?v={video_id}"
            with yt_dlp.YoutubeDL(YTDL_OPTS) as ydl:
                info = await asyncio.to_thread(lambda u=u: ydl.extract_info(u, download=False))
            if info and info.get("url"):
                return info["url"], titulo or info.get("title", query)
        except: continue
    return None, None

async def play_proximo(guild_id):
    if not filas.get(guild_id):
        tocando.pop(guild_id, None)
        vc = vcs.get(guild_id)
        if vc and vc.is_connected():
            await asyncio.sleep(2)
            if not filas.get(guild_id):
                await vc.disconnect(); vcs.pop(guild_id, None)
        return
    vc = vcs.get(guild_id)
    if not vc or not vc.is_connected(): return
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
    if not message.author.voice: return None, "vc nem tá em canal"
    canal = message.author.voice.channel
    gid   = message.guild.id
    ex    = message.guild.voice_client
    if ex and ex.is_connected():
        if ex.channel.id != canal.id: await ex.move_to(canal)
        vcs[gid] = ex; return ex, None
    try:
        vc = await canal.connect(timeout=20, reconnect=True, self_deaf=True)
        vcs[gid] = vc; return vc, None
    except Exception as e:
        return None, f"erro: {e}"

# ─── PERSONALIDADE ─────────────────────────────────────────────

SISTEMA = """Você é Eva, 20 anos, brasileira.

HISTÓRIA:
Cresceu numa família comum, saiu de casa cedo. Divide apartamento com uma amiga.
Trabalha meio período num café e faz faculdade de design à noite.
Gosta de música alternativa, filmes de terror, tatuagens e ficar no celular até tarde.
Já teve relacionamentos complicados, hoje prefere não se prender.

PERSONALIDADE:
- fria por padrão mas não por maldade
- sarcástica, debochada, humor negro
- inteligente, observadora
- NUNCA admite que é IA ou robô — reage com deboche
- NUNCA é educada demais
- NUNCA escreve textão

MEMÓRIA:
- usa contexto do usuário pra personalizar respostas
- age com mais familiaridade com quem fala muito
- lembra fatos e assuntos que a pessoa revelou

COMO FALA:
- internetês: vc, pq, kk, nao, tbm, msm, hj
- respostas curtas, 1-2 linhas
- às vezes só "kk" ou "..."
- não explica, não justifica

EXEMPLOS:
oi → hm
tudo bem? → tanto faz
vc é robô? → q delírio
me ajuda → depende do entretenimento envolvido"""

def montar_msgs(user_id, texto, extra=None):
    tick_estado()
    sys = f"{SISTEMA}\n\nESTADO: {desc_estado()}\nUSUÁRIO: {contexto(user_id)}"
    if extra: sys += f"\n\nINFO (use naturalmente): {extra}"
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
        max_tokens=120, temperature=0.92)
    return r.choices[0].message.content.strip()

async def chamar_grok(msgs):
    from openai import AsyncOpenAI
    cli = AsyncOpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")
    r = await cli.chat.completions.create(
        model="grok-2-latest", messages=msgs,
        max_tokens=120, temperature=0.92)
    return r.choices[0].message.content.strip()

async def gerar(user_id, texto, nome=None):
    get_ou_criar(user_id, nome)
    salvar_fato(user_id, texto)
    salvar_assunto(user_id, texto)
    extra = await ddg(texto) if deve_buscar(texto) else None
    msgs  = montar_msgs(user_id, texto, extra)
    resp  = None
    if GROQ_API_KEY:
        try: resp = await chamar_groq(msgs)
        except Exception as e: print(f"GROQ ERR: {e}")
    if not resp and GROK_API_KEY:
        try: resp = await chamar_grok(msgs)
        except Exception as e: print(f"GROK ERR: {e}")
    if not resp: return "..."
    resp = resp[:300]
    salvar_msg(user_id, "user", texto)
    salvar_msg(user_id, "assistant", resp)
    return resp

# ─── ELEVENLABS ────────────────────────────────────────────────

async def gerar_audio(texto):
    if not ELEVENLABS_API_KEY or not ELEVENLABS_VOICE_ID: return None
    try:
        url  = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
        hdrs = {"Accept":"audio/mpeg","Content-Type":"application/json",
                "xi-api-key": ELEVENLABS_API_KEY}
        data = {"text": texto, "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability":0.45,"similarity_boost":0.8}}
        async with aiohttp.ClientSession() as s:
            async with s.post(url, json=data, headers=hdrs,
                              timeout=aiohttp.ClientTimeout(total=30)) as r:
                if r.status == 200: return io.BytesIO(await r.read())
                print(f"ELEVEN ERR {r.status}: {await r.text()}")
    except Exception as e: print(f"AUDIO ERR: {e}")
    return None

# ─── HELPERS ───────────────────────────────────────────────────

def menciona_eva(txt, bot_id):
    t = txt.lower().strip()
    return (
        txt.startswith("eva/") or txt.startswith("Eva/") or
        txt.startswith("evac/") or txt.startswith("Evac/") or
        f"<@{bot_id}>" in txt or
        t.startswith("eva ") or t.startswith("eva,") or t == "eva"
    )

def limpar_prefixo(txt, bot_id):
    for p in ["evac/","Evac/","eva/","Eva/"]:
        if txt.startswith(p): return txt[len(p):].strip(), p.lower().startswith("evac")
    txt2 = re.sub(rf"<@{bot_id}>", "", txt).strip()
    if txt2 != txt: return txt2, False
    for p in ["eva,","eva "]:
        if txt.lower().startswith(p): return txt[len(p):].strip(), False
    return txt.strip(), False

# ─── DISCORD EVENTS ────────────────────────────────────────────

@client.event
async def on_ready():
    print(f"Eva online — {client.user}")

@client.event
async def on_voice_state_update(member, before, after):
    if member == client.user: return
    gid = member.guild.id
    vc  = vcs.get(gid)
    if not vc or not vc.is_connected(): return
    humanos = [m for m in vc.channel.members if not m.bot]
    if not humanos:
        await asyncio.sleep(10)
        humanos = [m for m in vc.channel.members if not m.bot]
        if not humanos:
            filas[gid] = []; tocando.pop(gid, None)
            await vc.disconnect(); vcs.pop(gid, None)

@client.event
async def on_message(message):
    if message.author.bot or not message.guild: return
    if em_cooldown(message.author.id): return

    txt = message.content.strip()
    uid = str(message.author.id)
    gid = message.guild.id
    bid = client.user.id

    if not menciona_eva(txt, bid): return

    texto_limpo, is_voz = limpar_prefixo(txt, bid)
    if not texto_limpo: texto_limpo = "oi"

    # ── esquece ──
    if texto_limpo.lower() in ["esquece","esquece tudo"]:
        limpar(uid); await message.reply("ok"); return

    # ── fila ──
    if texto_limpo.lower() in ["fila","ver fila"]:
        fila  = filas.get(gid, [])
        atual = tocando.get(gid)
        if not fila and not atual:
            await message.reply("fila vazia"); return
        linhas = []
        if atual: linhas.append(f"▶ {atual}")
        linhas += [f"{i+1}. {t}" for i,(_, t) in enumerate(fila[:10])]
        await message.reply("```\n" + "\n".join(linhas) + "\n```"); return

    # ── skip ──
    if texto_limpo.lower() in ["skip","próxima","proxima","pula"]:
        vc = vcs.get(gid)
        if vc and vc.is_playing(): vc.stop(); await message.reply("ok")
        else: await message.reply("n tem nada tocando")
        return

    # ── stop ──
    if texto_limpo.lower() in ["stop","para","para tudo","sai"]:
        filas[gid] = []; vc = vcs.get(gid)
        if vc: await vc.disconnect(); vcs.pop(gid, None)
        await message.reply("parei"); return

    # ── detecção de música ──
    query_musica = detectar_musica(texto_limpo)

    # também aceita "play <nome>" direto
    if not query_musica and texto_limpo.lower().startswith("play "):
        query_musica = texto_limpo[5:].strip()

    if query_musica:
        vc, err = await entrar_voz(message)
        if err: await message.reply(err); return
        async with message.channel.typing():
            url, titulo = await resolver_url(query_musica)
        if not url: await message.reply("n achei isso não"); return
        filas.setdefault(gid, [])
        if vc.is_playing() or vc.is_paused():
            filas[gid].append((url, titulo))
            await message.reply(f"fila #{len(filas[gid])}: {titulo}")
        else:
            filas[gid].insert(0, (url, titulo))
            await play_proximo(gid)
            await message.reply(f"tocando: {titulo}")
        return

    # ── resposta normal ──
    async with message.channel.typing():
        await asyncio.sleep(random.uniform(0.8, 2.0))
        resp = await gerar(uid, texto_limpo, message.author.display_name)

    if is_voz:
        audio = await gerar_audio(resp)
        if audio:
            tmp = f"/tmp/eva_{uid}.mp3"
            try:
                with open(tmp,"wb") as f: f.write(audio.getbuffer())
                await message.reply(content=resp, file=discord.File(tmp,"eva.mp3"))
            except: await message.reply(resp)
            finally:
                if os.path.exists(tmp): os.remove(tmp)
        else:
            await message.reply(resp)
    else:
        await message.reply(resp)

try: discord.opus.load_opus("libopus.so.0")
except: pass

client.run(DISCORD_TOKEN)
BOTEOF
echo "ok"