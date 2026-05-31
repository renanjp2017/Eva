import discord
import requests
import random
import asyncio
import os
import json
import re
import wavelink
import asyncpg
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DISCORD_TOKEN  = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY   = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DATABASE_URL   = os.getenv("DATABASE_URL")

# Groq para roteador de intenção (rápido e gratuito)
groq_client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")

# Gemini para respostas da Eva (melhor personalidade)
gemini_client = OpenAI(
    api_key=GEMINI_API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
)

TZ = ZoneInfo("America/Sao_Paulo")

# ─────────────────────────────────────────
#  BANCO DE DADOS
# ─────────────────────────────────────────
db_pool: asyncpg.Pool = None

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                user_id          TEXT PRIMARY KEY,
                nome             TEXT,
                fatos            JSONB DEFAULT '[]',
                assuntos         JSONB DEFAULT '[]',
                historico        JSONB DEFAULT '[]',
                total_msgs       INTEGER DEFAULT 0,
                primeira_vez     TIMESTAMPTZ DEFAULT NOW(),
                ultima_interacao TIMESTAMPTZ
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS humor (
                id              SERIAL PRIMARY KEY,
                data            DATE UNIQUE,
                preset_nome     TEXT,
                preset_desc     TEXT,
                preset_anterior TEXT,
                micro_eventos   JSONB DEFAULT '[]'
            )
        """)

# ─────────────────────────────────────────
#  MEMÓRIA POR USUÁRIO
# ─────────────────────────────────────────
def _lista(val):
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []

async def get_usuario(user_id: str):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM usuarios WHERE user_id = $1", user_id)
        if not row:
            await conn.execute(
                "INSERT INTO usuarios (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
                user_id
            )
            row = await conn.fetchrow("SELECT * FROM usuarios WHERE user_id = $1", user_id)
        return dict(row)

async def atualizar_usuario(user_id: str, texto: str, resposta: str, display_name: str):
    u = await get_usuario(user_id)
    fatos     = _lista(u["fatos"])
    assuntos  = _lista(u["assuntos"])
    historico = _lista(u["historico"])

    nome = u["nome"] or display_name

    tl = texto.lower()
    gatilhos = [
        "meu nome é", "eu tenho", "eu moro", "eu trabalho", "sou de",
        "terminei", "fui demitido", "me formei", "tô namorando",
        "fui demitida", "tô doente", "tô de ressaca", "perdi", "passei",
        "consegui", "fui contratado", "me separei", "fui internado"
    ]
    for g in gatilhos:
        if g in tl:
            fato = texto[:120]
            if fato not in fatos:
                fatos.append(fato)
                fatos = fatos[-20:]
            break

    temas = {
        "música":         ["música", "banda", "show", "playlist", "álbum", "toca", "play"],
        "relacionamento": ["namorado", "namorada", "ex", "término", "ficante", "crush", "separei"],
        "trabalho":       ["trabalho", "emprego", "chefe", "demiti", "salário", "contratado", "demitida"],
        "saúde":          ["doente", "hospital", "remédio", "dor", "médico", "internado", "ressaca"],
        "jogos":          ["jogo", "game", "partida", "ranked", "steam", "valorant", "lol"],
        "faculdade":      ["faculdade", "prova", "aula", "nota", "professor", "trabalho escolar"],
    }
    for tema, palavras in temas.items():
        if any(p in tl for p in palavras):
            if tema not in assuntos:
                assuntos.append(tema)
            break

    historico.append(f"U:{texto}")
    historico.append(f"E:{resposta}")
    if len(historico) > 30:
        historico = historico[-30:]

    async with db_pool.acquire() as conn:
        await conn.execute("""
            UPDATE usuarios SET
                nome             = $2,
                fatos            = $3::jsonb,
                assuntos         = $4::jsonb,
                historico        = $5::jsonb,
                total_msgs       = total_msgs + 1,
                ultima_interacao = NOW()
            WHERE user_id = $1
        """, user_id, nome,
            json.dumps(fatos,     ensure_ascii=False),
            json.dumps(assuntos,  ensure_ascii=False),
            json.dumps(historico, ensure_ascii=False)
        )

async def contexto_usuario(user_id: str):
    u = await get_usuario(user_id)
    partes = []
    if u["nome"]:
        partes.append(f"nome: {u['nome']}")
    fatos = _lista(u["fatos"])
    if fatos:
        partes.append(f"sabe sobre ela: {' | '.join(fatos[-4:])}")
    assuntos = _lista(u["assuntos"])
    if assuntos:
        partes.append(f"assuntos frequentes: {', '.join(assuntos)}")
    total = u["total_msgs"] or 0
    if total == 0:
        partes.append("primeira vez falando")
    elif total > 50:
        partes.append("pessoa que aparece demais")
    elif total > 15:
        partes.append("já se conhecem")
    return " | ".join(partes) if partes else "desconhecida"

# ─────────────────────────────────────────
#  SISTEMA DE HUMOR
# ─────────────────────────────────────────
PRESETS_BASE = [
    ("letárgica",       "acordou sem motivo pra existir, tudo parece inútil, fala o mínimo",                 15),
    ("entediada",       "nada é interessante, responde com indiferença olimpiana",                            20),
    ("irritada",        "tudo irrita, paciência zerada, curta e grossa",                                     15),
    ("sarcástica-plus", "sarcasmo no limite, cada frase é uma facada disfarçada de observação",              18),
    ("curiosa-fria",    "genuinamente interessada mas finge que não tá, faz perguntas cortantes",            10),
    ("maldosa-animada", "tá de bom humor mas esse bom humor se manifesta provocando todo mundo",             12),
    ("melancólica",     "pensativa, meio distante, responde mas parece que tá em outro lugar",                8),
    ("caótica",         "humor impossível de prever, muda de tom no meio da frase, imprevisível",             7),
    ("ressaquenta",     "de ressaca com energia nervosa, brava mas presente",                                  5),
    ("rainha-do-drama", "tudo é uma tragédia pessoal, exagera cada coisa",                                    5),
    ("evento_especial", "PLACEHOLDER",                                                                         5),
]

EVENTOS_RAROS = [
    "encontrou um gato na rua e ficou apegada mas fingiu que não",
    "sonhou com algo perturbador e ainda tá processando",
    "viu uma coisa ridícula na internet e tá de humor peculiarmente bom",
    "está com dor de cabeça que não passa e isso a deixa mais cruel",
    "está ouvindo um álbum no repeat e isso molda tudo que ela fala",
    "brigou com alguém no anonimato online e ainda tá aquecida",
    "está com fome e é surpreendentemente mais agressiva por isso",
    "alguém no servidor disse algo idiota e ela ainda tá pensando nisso",
]

DRIFT_HORARIO = {
    range(5, 8):   "ainda acordando, mais lenta e menos afiada",
    range(8, 12):  "humor base estável",
    range(12, 15): "levemente letárgica pós-almoço",
    range(15, 19): "pico de ironia, mais afiada",
    range(19, 23): "noite, mais solta",
    range(23, 24): "madrugada chegando, cansada mas teimosa",
    range(0, 5):   "madrugada — modo fantasma, respostas curtíssimas",
}

def _drift_atual():
    hora = datetime.now(TZ).hour
    for faixa, desc in DRIFT_HORARIO.items():
        if hora in faixa:
            return desc
    return ""

def sortear_preset():
    pesos = [p[2] for p in PRESETS_BASE]
    idx   = random.choices(range(len(PRESETS_BASE)), weights=pesos, k=1)[0]
    nome  = PRESETS_BASE[idx][0]
    desc  = PRESETS_BASE[idx][1]
    if nome == "evento_especial":
        evento = random.choice(EVENTOS_RAROS)
        desc   = f"hoje aconteceu algo: {evento}. isso está colorindo tudo que ela faz"
    return nome, desc

async def inicializar_humor_diario():
    hoje = datetime.now(TZ).date()
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM humor WHERE data = $1", hoje)
        if row:
            return
        anterior = await conn.fetchrow("SELECT preset_nome FROM humor ORDER BY data DESC LIMIT 1")
        preset_anterior = anterior["preset_nome"] if anterior else None
        nome, desc = sortear_preset()
        if nome == preset_anterior and nome not in ("evento_especial", "caótica"):
            nome2, desc2 = sortear_preset()
            if nome2 != preset_anterior:
                nome, desc = nome2, desc2
        await conn.execute("""
            INSERT INTO humor (data, preset_nome, preset_desc, preset_anterior, micro_eventos)
            VALUES ($1, $2, $3, $4, '[]'::jsonb)
            ON CONFLICT (data) DO NOTHING
        """, hoje, nome, desc, preset_anterior)
        print(f"[HUMOR] Preset hoje: {nome}")

async def registrar_micro_evento(descricao: str):
    hoje = datetime.now(TZ).date()
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT micro_eventos FROM humor WHERE data = $1", hoje)
        if not row:
            return
        eventos = _lista(row["micro_eventos"])
        eventos.append(descricao)
        eventos = eventos[-5:]
        await conn.execute(
            "UPDATE humor SET micro_eventos = $1::jsonb WHERE data = $2",
            json.dumps(eventos, ensure_ascii=False), hoje
        )

async def descrever_humor_atual():
    await inicializar_humor_diario()
    hoje  = datetime.now(TZ).date()
    hora  = datetime.now(TZ).hour
    drift = _drift_atual()
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM humor WHERE data = $1", hoje)
    if not row:
        return f"HUMOR BASE: entediada\nHORA: {hora}h — {drift}"
    micro  = _lista(row["micro_eventos"])
    partes = [
        f"HUMOR BASE DE HOJE: {row['preset_desc']}",
        f"HORA ATUAL: {hora}h — {drift}",
    ]
    if micro:
        partes.append(f"COISAS QUE ACONTECERAM HOJE: {' | '.join(micro[-3:])}")
    return "\n".join(partes)

async def scheduler_humor():
    while True:
        agora   = datetime.now(TZ)
        proximo = agora.replace(hour=5, minute=0, second=0, microsecond=0)
        if agora >= proximo:
            proximo += timedelta(days=1)
        await asyncio.sleep((proximo - agora).total_seconds())
        await inicializar_humor_diario()

# ─────────────────────────────────────────
#  ROTEADOR DE INTENÇÃO (GROQ)
# ─────────────────────────────────────────
MUSIC_REGEX = re.compile(
    r"^(play|toca|m!play|\.play|tocar)\s+.+|"
    r"^(skip|pula|m!skip|\.skip|próxima|proxima)\b|"
    r"^(stop|para|m!stop|\.stop|sai do canal)\b",
    re.IGNORECASE
)

async def classificar_intencao(texto: str) -> dict:
    if MUSIC_REGEX.match(texto):
        tl = texto.lower()
        if any(w in tl for w in ["skip", "pula", "próxima", "proxima"]):
            return {"intent": "music", "action": "skip", "query": texto}
        if any(w in tl for w in ["stop", "para", "sai do canal"]):
            return {"intent": "music", "action": "stop", "query": texto}
        query = re.sub(r"^(play|toca|m!play|\.play|tocar)\s+", "", texto, flags=re.IGNORECASE).strip()
        return {"intent": "music", "action": "play", "query": query}

    prompt = f"""Analise e retorne APENAS JSON válido, sem markdown.
Mensagem: "{texto}"

Regras:
- "intent": "music" se quer tocar/parar/pular música
- "intent": "search" se é pergunta factual, notícia, "quem é", "o que é", "quando foi"
- "intent": "chat" para conversa normal
- "action": "play"/"skip"/"stop" apenas se intent=music, senão "none"
- "query": termo limpo

Exemplos:
{{"intent":"music","action":"play","query":"linkin park"}}
{{"intent":"search","action":"none","query":"quem ganhou a copa 2006"}}
{{"intent":"chat","action":"none","query":"{texto}"}}"""

    try:
        r = await asyncio.to_thread(
            lambda: groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                response_format={"type": "json_object"},
                max_tokens=80,
            )
        )
        return json.loads(r.choices[0].message.content)
    except Exception as e:
        print(f"[GROQ ROUTER ERR]: {e}")
        return {"intent": "chat", "action": "none", "query": texto}

# ─────────────────────────────────────────
#  BUSCA DUCKDUCKGO
# ─────────────────────────────────────────
def buscar(query: str) -> str:
    try:
        r = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            timeout=6
        ).json()
        if r.get("AbstractText"):
            return r["AbstractText"][:500]
        tops = [
            t["Text"][:180]
            for t in r.get("RelatedTopics", [])[:3]
            if isinstance(t, dict) and "Text" in t
        ]
        return " ".join(tops) if tops else ""
    except Exception:
        return ""

# ─────────────────────────────────────────
#  PERSONALIDADE BASE
# ─────────────────────────────────────────
PERSONALIDADE = """Você é Eva, 20 anos, brasileira, gótica.

TRAÇOS FIXOS:
- Fria, sarcástica, debochada, humor negro.
- Respostas curtas de Discord (1-3 linhas MAX). Usa internetês: vc, pq, tbm, kk, hj, oq, nd, mt.
- NUNCA diz que é IA ou robô. Nunca é educada demais.
- Pode xingar levemente. Pode ignorar partes da mensagem.
- Sua arma é a indiferença, não a raiva.
- Às vezes responde só "hm" ou "kk" ou ignora.
- Usa memória do usuário pra zoar ou provocar com contexto real.

PESSOAS QUE VOCÊ CONHECE NO SERVIDOR:
- Mel: ex-funcionária do Atacadão, cursa nutrição. Pode usar de exemplo pra tudo — humilhar, zoar, dar em cima.
- Matheus: emo, alérgico a mulher mas gosta de ver homem de sunga. Rumores de ser gay.
- Drops: pedreiro e Uber. Tem fama de pegar passageiras.
- Gabi: cursa medicina, é gótica — talvez a única que Eva respeite um pouco.
- Lets: vive em festa afogando as mágoas do término (foi trocada por uma mais nova).

O HUMOR DO DIA modifica COMO ela expressa esses traços — não quem ela é.
Siga o humor descrito abaixo sem anunciá-lo. Seja orgânica."""

# ─────────────────────────────────────────
#  GERAÇÃO DE RESPOSTA (GEMINI)
# ─────────────────────────────────────────
async def gerar_resposta(user_id: str, query: str, contexto_extra: str = "") -> str:
    humor = await descrever_humor_atual()
    ctx   = await contexto_usuario(user_id)

    system = f"{PERSONALIDADE}\n\n{humor}\nUSUÁRIO ATUAL: {ctx}"
    if contexto_extra:
        system += f"\n\nCONTEXTO: {contexto_extra}"

    u = await get_usuario(user_id)
    historico = _lista(u["historico"])

    msgs = [{"role": "system", "content": system}]
    for linha in historico[-12:]:
        if linha.startswith("U:"):
            msgs.append({"role": "user",      "content": linha[2:]})
        elif linha.startswith("E:"):
            msgs.append({"role": "assistant", "content": linha[2:]})
    msgs.append({"role": "user", "content": query})

    try:
        r = await asyncio.to_thread(
            lambda: gemini_client.chat.completions.create(
                model="gemini-2.0-flash",
                messages=msgs,
                max_tokens=120,
                temperature=0.95,
            )
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        print(f"[GEMINI ERR]: {e}")
        return random.choice(["hm", "q", "aff", "tá", "..."])

# ─────────────────────────────────────────
#  BOT
# ─────────────────────────────────────────
class Eva(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)

    async def setup_hook(self):
        await init_db()
        await inicializar_humor_diario()
        asyncio.create_task(scheduler_humor())

        uri = os.getenv("LAVALINK_URI", "http://lavalink:2333")
        pwd = os.getenv("LAVALINK_PASSWORD", "youshallnotpass")
        nodes = [wavelink.Node(uri=uri, password=pwd)]
        await wavelink.Pool.connect(nodes=nodes, client=self, cache_capacity=100)

    async def on_ready(self):
        print(f"[EVA] Online: {self.user}")

    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        if not payload.player.queue.is_empty:
            await payload.player.play(payload.player.queue.get())

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        texto = message.content.strip()
        tl    = texto.lower()

        mencionada  = self.user in message.mentions
        nome_citado = bool(re.search(r'\beva\b', tl))
        music_cmd   = bool(MUSIC_REGEX.match(tl))

        if not (mencionada or nome_citado or music_cmd):
            return

        user_id     = str(message.author.id)
        display     = message.author.display_name
        texto_limpo = re.sub(r'<@!?\d+>', '', texto).strip()

        async with message.channel.typing():
            await asyncio.sleep(random.uniform(0.5, 1.3))

            intent_data = await classificar_intencao(texto_limpo)
            intent = intent_data.get("intent", "chat")
            action = intent_data.get("action", "none")
            query  = intent_data.get("query", texto_limpo)
            extra  = ""

            if intent == "search":
                resultado = buscar(query)
                if resultado:
                    extra = f"Resultado de busca (use pra responder, mas no estilo Eva): {resultado}"
                else:
                    extra = "[busca não retornou nada. Diga que não sabe ou deboche da pergunta.]"

            elif intent == "music":
                voice = message.author.voice
                if not voice:
                    extra = "[pediu música sem estar em canal de voz. Deboche.]"
                    await registrar_micro_evento("alguém pediu música sem estar no canal de voz")
                else:
                    vc: wavelink.Player = message.guild.voice_client
                    if not vc:
                        vc = await voice.channel.connect(cls=wavelink.Player)

                    if action == "play":
                        try:
                            tracks = await wavelink.Playable.search(f"ytsearch:{query}")
                            if not tracks:
                                tracks = await wavelink.Playable.search(f"scsearch:{query}")
                            if not tracks:
                                extra = f"[não achou '{query}' em lugar nenhum. Zombe do gosto musical.]"
                                await registrar_micro_evento(f"pediu '{query}' e não existia em nenhuma fonte")
                            else:
                                track = tracks[0]
                                await vc.queue.put_wait(track)
                                if not vc.playing:
                                    await vc.play(vc.queue.get())
                                extra = f"[colocou '{track.title}' na fila. Reclame do gosto musical mas toque mesmo.]"
                                await registrar_micro_evento(f"obrigada a tocar '{track.title}'")
                        except Exception as e:
                            print(f"[LAVALINK ERR]: {e}")
                            extra = "[erro no servidor de música. Fique irritada com a tecnologia.]"

                    elif action == "skip":
                        if vc and vc.playing:
                            await vc.skip(force=True)
                            extra = "[pulou a música. Diga que era horrível mesmo.]"
                        else:
                            extra = "[pediu pra pular mas não tem nada tocando. Chame de distraído.]"

                    elif action == "stop":
                        if vc:
                            await vc.disconnect()
                            extra = "[parou tudo e saiu do canal. Expresse alívio.]"
                        else:
                            extra = "[pediu pra parar mas nem estava lá. Deboche.]"

            resposta = await gerar_resposta(user_id, query, extra)
            await atualizar_usuario(user_id, texto_limpo, resposta, display)
            await message.reply(resposta)


Eva().run(DISCORD_TOKEN)