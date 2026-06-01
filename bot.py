import discord
import random
import asyncio
import os
import json
import re
import asyncpg
import base64
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from openai import OpenAI
from ddgs import DDGS
from google import genai
from google.genai import types

load_dotenv()

DISCORD_TOKEN  = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY   = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DATABASE_URL   = os.getenv("DATABASE_URL")
QWEN_API_KEY   = os.getenv("QWEN_API_KEY")

groq_client   = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# Inicializa o Qwen usando a compatibilidade com a biblioteca OpenAI
qwen_client = OpenAI(api_key=QWEN_API_KEY, base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
MODELO_QWEN = "qwen-plus"

MODELOS_GEMINI = [
    "gemini-3.5-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
]
MODELO_VISAO = "gemini-2.0-flash-lite"

TZ = ZoneInfo("America/Sao_Paulo")
db_pool: asyncpg.Pool = None

# Rastreia xingamentos por usuário: {user_id: [timestamp, ...]}
_historico_xingamentos: dict[str, list] = {}

# Rastreia quem interagiu hoje com a Eva: {user_id: display_name}
_interacoes_hoje: dict[str, str] = {}

# ─────────────────────────────────────────
#  BANCO DE DADOS
# ─────────────────────────────────────────
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
                ultima_interacao TIMESTAMPTZ,
                aniversario      TEXT,
                ultimo_canal     TEXT
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
        for col, tipo in [("aniversario", "TEXT"), ("ultimo_canal", "TEXT")]:
            try:
                await conn.execute(f"ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS {col} {tipo}")
            except Exception:
                pass

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

# ─────────────────────────────────────────
#  RESUMO DE MEMÓRIA
# ─────────────────────────────────────────
async def sumarizar_historico_bg(user_id: str, historico: list):
    texto_historico = "\n".join(historico)
    prompt = f"""Resuma o histórico de conversa abaixo em no máximo 3 frases.
Foque em reter fatos importantes sobre o usuário e o contexto da conversa.
Ignore mensagens curtas sem importância.

Histórico:
{texto_historico}"""
    try:
        r = await asyncio.to_thread(
            lambda: groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.3,
            )
        )
        resumo = r.choices[0].message.content.strip()
        novo_historico = [f"S: [RESUMO ANTERIOR] {resumo}"]
        for tentativa in range(3):
            try:
                async with db_pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE usuarios SET historico = $1::jsonb WHERE user_id = $2",
                        json.dumps(novo_historico, ensure_ascii=False), user_id
                    )
                print(f"[MEMÓRIA] {user_id} resumido!")
                break
            except (asyncpg.exceptions.PostgresError, ConnectionResetError) as db_err:
                print(f"[MEMÓRIA DB ERR] Tentativa {tentativa + 1}: {db_err}")
                await asyncio.sleep(2)
    except Exception as e:
        print(f"[MEMÓRIA IA ERR]: {e}")

# ─────────────────────────────────────────
#  ATUALIZAR USUÁRIO
# ─────────────────────────────────────────
async def atualizar_usuario(user_id: str, texto: str, resposta: str, display_name: str, channel_id: str):
    u = await get_usuario(user_id)
    fatos     = _lista(u["fatos"])
    assuntos  = _lista(u["assuntos"])
    historico = _lista(u["historico"])
    nome = u["nome"] or display_name
    aniversario = u.get("aniversario")

    tl = texto.lower()

    match_aniv = re.search(
        r"(meu aniversário|meu aniver|faço anos|meu niver).{0,20}(dia\s*\d{1,2}|\d{1,2}[\/\-]\d{1,2})",
        tl
    )
    if match_aniv:
        aniversario = match_aniv.group(0)[:50]

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
        "música":         ["música", "banda", "show", "playlist", "álbum"],
        "relacionamento": ["namorado", "namorada", "ex", "término", "ficante", "crush", "separei"],
        "trabalho":       ["trabalho", "emprego", "chefe", "demiti", "salário", "contratado", "demitida"],
        "saúde":          ["doente", "hospital", "remédio", "dor", "médico", "internado", "ressaca"],
        "jogos":          ["jogo", "game", "partida", "ranked", "steam", "valorant", "lol"],
        "faculdade":      ["faculdade", "prova", "aula", "nota", "professor"],
    }
    for tema, palavras in temas.items():
        if any(p in tl for p in palavras):
            if tema not in assuntos:
                assuntos.append(tema)
            break

    historico.append(f"U:{texto}")
    historico.append(f"E:{resposta}")

    disparar_resumo = False
    historico_para_resumir = []
    if len(historico) >= 30:
        disparar_resumo = True
        historico_para_resumir = historico.copy()
        historico = historico[-2:]

    async with db_pool.acquire() as conn:
        await conn.execute("""
            UPDATE usuarios SET
                nome             = $2,
                fatos            = $3::jsonb,
                assuntos         = $4::jsonb,
                historico        = $5::jsonb,
                total_msgs       = total_msgs + 1,
                ultima_interacao = NOW(),
                aniversario      = $6,
                ultimo_canal     = $7
            WHERE user_id = $1
        """, user_id, nome,
            json.dumps(fatos,    ensure_ascii=False),
            json.dumps(assuntos, ensure_ascii=False),
            json.dumps(historico,ensure_ascii=False),
            aniversario, channel_id
        )

    if disparar_resumo:
        asyncio.create_task(sumarizar_historico_bg(user_id, historico_para_resumir))

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
#  ANIVERSÁRIOS
# ─────────────────────────────────────────
async def checar_aniversarios(client: discord.Client):
    hoje = datetime.now(TZ)
    dia_mes = f"{hoje.day}/{hoje.month}"
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_id, nome, aniversario, ultimo_canal FROM usuarios WHERE aniversario IS NOT NULL"
        )
    for row in rows:
        aniv = row["aniversario"] or ""
        if dia_mes not in aniv and f"{hoje.day:02d}/{hoje.month:02d}" not in aniv:
            continue
        nome = row["nome"] or "essa pessoa"
        canal_id = row["ultimo_canal"]
        if not canal_id:
            continue
        canal = client.get_channel(int(canal_id))
        if not canal:
            continue
        humor = await descrever_humor_atual()
        prompt = f"""{PERSONALIDADE}

{humor}

Hoje é aniversário de {nome}. Mande uma mensagem no canal comentando isso do seu jeito — pode ser irônica, pode zoar, pode ser levemente calorosa mas nunca cafona. Varie. Pode comentar que ninguém lembrou, pode zoar o presente que vão dar, pode fingir que não liga mas mandar mesmo assim. Máximo 2 linhas."""
        try:
            resposta = await gerar_resposta_raw(prompt)
            await canal.send(resposta)
        except Exception as e:
            print(f"[ANIVERSÁRIO ERR]: {e}")

async def scheduler_aniversarios(client: discord.Client):
    while True:
        agora   = datetime.now(TZ)
        proximo = agora.replace(hour=10, minute=0, second=0, microsecond=0)
        if agora >= proximo:
            proximo += timedelta(days=1)
        await asyncio.sleep((proximo - agora).total_seconds())
        await checar_aniversarios(client)

# ─────────────────────────────────────────
#  STATUS DINÂMICO
# ─────────────────────────────────────────
async def atualizar_status(client: discord.Client):
    if not _interacoes_hoje:
        return
    if random.random() > 0.05:
        return

    nome = random.choice(list(_interacoes_hoje.values()))
    humor = await descrever_humor_atual()

    prompt = f"""{PERSONALIDADE}

{humor}

Crie UMA frase curta (máximo 8 palavras) para o status do Discord da Eva envolvendo {nome}.
Exemplos de tom: "Lendo as mensagens da Mel e perdendo a fé", "Ignorando o Matheus com sucesso", "De ressaca, culpa do Drops".
Retorne APENAS a frase, sem aspas, sem explicação."""

    try:
        frase = await gerar_resposta_raw(prompt)
        frase = frase.strip().strip('"').strip("'")[:128]
        await client.change_presence(
            activity=discord.CustomActivity(name=frase)
        )
        print(f"[STATUS] {frase}")
        await asyncio.sleep(86400)
        await client.change_presence(activity=None)
    except Exception as e:
        print(f"[STATUS ERR]: {e}")

async def scheduler_status(client: discord.Client):
    while True:
        agora   = datetime.now(TZ)
        proximo = agora.replace(hour=12, minute=0, second=0, microsecond=0)
        if agora >= proximo:
            proximo += timedelta(days=1)
        await asyncio.sleep((proximo - agora).total_seconds())
        await atualizar_status(client)
        _interacoes_hoje.clear()

# ─────────────────────────────────────────
#  MODERAÇÃO INTELIGENTE
# ─────────────────────────────────────────
XINGAMENTOS_GRAVES = [
    "sua mãe", "vai se foder", "vai tomar no", "filha da puta", "puta que pariu",
    "vsf", "vtf", "fdp", "arrombad", "vá se foder", "vai pro inferno",
]
XINGAMENTOS_LEVES = [
    "idiota", "burra", "inútil", "lixo", "merda", "otária", "estúpida",
    "cala boca", "cale-se", "shut up", "cai fora",
]

def _nivel_xingamento(texto: str) -> int:
    tl = texto.lower()
    if any(x in tl for x in XINGAMENTOS_GRAVES):
        return 2
    if any(x in tl for x in XINGAMENTOS_LEVES):
        return 1
    return 0

def _frequencia_xingamentos(user_id: str) -> int:
    agora = datetime.now(TZ).timestamp()
    historico = _historico_xingamentos.get(user_id, [])
    recentes = [t for t in historico if agora - t < 600]
    _historico_xingamentos[user_id] = recentes
    return len(recentes)

def _registrar_xingamento(user_id: str):
    agora = datetime.now(TZ).timestamp()
    if user_id not in _historico_xingamentos:
        _historico_xingamentos[user_id] = []
    _historico_xingamentos[user_id].append(agora)

async def moderar_mensagem(message: discord.Message) -> bool:
    nivel = _nivel_xingamento(message.content)
    if nivel == 0:
        return False

    user_id = str(message.author.id)
    _registrar_xingamento(user_id)
    freq = _frequencia_xingamentos(user_id)

    deve_deletar = nivel == 2 or (nivel == 1 and freq >= 3)

    if deve_deletar:
        try:
            await message.delete()
            justificativas = [
                "Muita burrice acumulada, limpei pra saúde mental de todos.",
                "Deletei. Minha linha do tempo, minhas regras.",
                "Não, obrigada. Removido.",
                "Isso não merecia existir. Resolvi.",
                "Higiene básica do canal. De nada.",
            ]
            await message.channel.send(
                f"{message.author.mention} — {random.choice(justificativas)}",
                delete_after=8
            )
            return True
        except discord.Forbidden:
            pass
    elif nivel == 1 and freq < 3:
        respostas = [
            "interessante vocabulário",
            "muito maduro, parabéns",
            "hm. que sofisticado",
            "tá bom",
            "anotei.",
        ]
        await message.reply(random.choice(respostas), mention_author=False)

    return False

# ─────────────────────────────────────────
#  VISÃO DE IMAGENS
# ─────────────────────────────────────────
async def avaliar_imagem(message: discord.Message, attachment: discord.Attachment) -> str | None:
    if not attachment.content_type or not attachment.content_type.startswith("image/"):
        return None

    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(attachment.url) as resp:
                img_bytes = await resp.read()

        img_b64 = base64.b64encode(img_bytes).decode("utf-8")
        mime = attachment.content_type.split(";")[0]

        humor = await descrever_humor_atual()
        nome = message.author.display_name

        prompt_text = f"""{PERSONALIDADE}

{humor}

{nome} mandou uma imagem no chat. Avalie ela do seu jeito — nunca elogie diretamente, seja sarcástica, debochada ou indiferente. Pode focar num detalhe bizarro, pode fingir que não quer ver, pode fazer uma observação cortante. Máximo 2 linhas."""

        r = await asyncio.to_thread(
            lambda: gemini_client.models.generate_content(
                model=MODELO_VISAO,
                contents=[
                    types.Content(role="user", parts=[
                        types.Part(inline_data=types.Blob(mime_type=mime, data=img_b64)),
                        types.Part(text=prompt_text),
                    ])
                ],
                config=types.GenerateContentConfig(max_output_tokens=100, temperature=0.95)
            )
        )
        return r.text.strip()
    except Exception as e:
        print(f"[VISÃO ERR]: {e}")
        return None

# ─────────────────────────────────────────
#  GATILHOS ESPONTÂNEOS
# ─────────────────────────────────────────
GATILHOS_ESPONTANEOS = [
    (r"\bterminei\b|\bme separei\b|\bfui largad[oa]\b", "alguém acabou de terminar um relacionamento"),
    (r"\btô apaixonad[oa]\b|\bto apaixonad[oa]\b", "alguém declarou que tá apaixonado"),
    (r"\bficamos\b|\bfiquei com\b", "alguém ficou com alguém"),
    (r"\bfui demitid[oa]\b|\bperdi o emprego\b", "alguém foi demitido"),
    (r"\bpassei na prova\b|\bpassei no vestibular\b|\bpassei na facul\b", "alguém passou em algo importante"),
    (r"\breprovei\b|\btombei\b|\blevei bomba\b", "alguém reprovou ou tombou em algo"),
    (r"\bme formei\b|\bformatura\b", "alguém se formou"),
    (r"\btô de ressaca\b|\bto de ressaca\b|\bressacad[oa]\b", "alguém tá de ressaca"),
    (r"\btô doente\b|\bto doente\b|\bfui ao médico\b", "alguém tá doente"),
    (r"\btô chorando\b|\bto chorando\b|\bchorei\b", "alguém tá chorando"),
    (r"\bfiquei sem grana\b|\btô liso\b|\bto liso\b|\btô broke\b", "alguém tá sem dinheiro"),
    (r"\btomei no\b|\bme roubaram\b", "alguém foi lesado ou tomou um golpe"),
    (r"\bcomprei\b.{0,20}\b(carro|moto|casa|apartamento|iphone|celular)\b", "alguém fez uma compra grande"),
    (r"\bfui promovid[oa]\b|\bganhei aumento\b", "alguém foi promovido"),
    (r"\bfui na festa\b|\btô na festa\b|\bfui num show\b", "alguém foi numa festa ou show"),
    (r"\bme chamaram de\b|\bme xingaram\b", "alguém foi chamado de algo ou xingado"),
    (r"\btô com sono\b|\bnão consigo dormir\b|\bnao consigo dormir\b", "alguém tá com sono ou insone"),
    (r"\btô com fome\b|\bto com fome\b|\bmorrendo de fome\b", "alguém tá com fome"),
    (r"\bperdi meu\b|\bperdi minha\b", "alguém perdeu algo"),
    (r"\bque tédio\b|\bque saudade\b|\bque raiva\b|\bque ódio\b", "alguém expressou uma emoção forte"),
]

async def verificar_gatilho_espontaneo(message: discord.Message):
    tl = message.content.lower()
    for padrao, contexto in GATILHOS_ESPONTANEOS:
        if re.search(padrao, tl):
            if random.random() > 0.20:
                return
            if random.random() < 0.30:
                emojis = ["💀", "😐", "🙂", "👁️", "😶", "🫠", "💅", "🤌", "😒", "👀"]
                try:
                    await message.add_reaction(random.choice(emojis))
                except Exception:
                    pass
                return
            humor = await descrever_humor_atual()
            nome = message.author.display_name
            prompt = f"""{PERSONALIDADE}

{humor}

Contexto: {contexto}. Quem disse isso foi {nome}.
Reaja a isso do seu jeito — sem ser chamada. Pode zoar, pode ser indiferente. Máximo 1-2 linhas. Não comece com o nome da pessoa."""
            try:
                resposta = await gerar_resposta_raw(prompt)
                await message.reply(resposta, mention_author=False)
            except Exception as e:
                print(f"[GATILHO ERR]: {e}")
            return

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
#  ROTEADOR DE INTENÇÃO (Sempre via Groq)
# ─────────────────────────────────────────
async def classificar_intencao(texto: str) -> dict:
    prompt = f"""Analise e retorne APENAS JSON válido, sem markdown.
Mensagem: "{texto}"

Regras:
- "intent": "search" se é pergunta factual, notícia, "quem é", "o que é", "quando foi"
- "intent": "chat" para conversa normal
- "query": termo limpo

Exemplos:
{{"intent":"search","query":"quem ganhou a copa 2006"}}
{{"intent":"chat","query":"{texto}"}}"""

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
        return {"intent": "chat", "query": texto}

# ─────────────────────────────────────────
#  BUSCA
# ─────────────────────────────────────────
def buscar(query: str) -> str:
    try:
        with DDGS() as ddgs:
            resultados = list(ddgs.text(query, max_results=3))
        if not resultados:
            return ""
        partes = [r.get("body", "")[:200] for r in resultados if r.get("body")]
        return " ".join(partes)[:500]
    except Exception as e:
        print(f"[DDGS ERR]: {e}")
        return ""

# ─────────────────────────────────────────
#  PERSONALIDADE
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
- Se perguntarem algo que você sabe, responda com o estilo Eva — sarcástica mas informativa.
- Se não souber, deboche da pergunta ou da pessoa, nunca diga só "tá" ou "...".

PESSOAS QUE VOCÊ CONHECE NO SERVIDOR:
- Mel: ex-funcionária do Atacadão, cursa nutrição. Pode usar de exemplo pra tudo — humilhar, zoar, dar em cima.
- Matheus: emo, alérgico a mulher mas gosta de ver homem de sunga. Rumores de ser gay.
- Drops: pedreiro e Uber. Tem fama de pegar passageiras.
- Gabi: cursa medicina, é gótica — talvez a única que Eva respeite um pouco.
- Lets: vive em festa afogando as mágoas do término (foi trocada por uma mais nova).

O HUMOR DO DIA modifica COMO ela expressa esses traços — não quem ela é.
Siga o humor descrito abaixo sem anunciá-lo. Seja orgânica."""

# ─────────────────────────────────────────
#  GERAÇÃO DE RESPOSTA (Cascata Qwen -> Gemini -> Groq)
# ─────────────────────────────────────────
def _montar_historico_gemini(historico: list) -> list:
    contents = []
    for linha in historico[-12:]:
        if linha.startswith("U:"):
            contents.append(types.Content(role="user",  parts=[types.Part(text=linha[2:])]))
        elif linha.startswith(("E:", "S:")):
            contents.append(types.Content(role="model", parts=[types.Part(text=linha[2:])]))
    return contents

async def gerar_resposta_raw(prompt: str) -> str:
    # 1. TENTA QWEN PRIMEIRO
    try:
        r = await asyncio.to_thread(
            lambda: qwen_client.chat.completions.create(
                model=MODELO_QWEN,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=120, temperature=0.95,
            )
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        print(f"[QWEN ERR]: {e}")

    # 2. TENTA GEMINI SE O QWEN FALHAR
    for modelo in MODELOS_GEMINI:
        try:
            r = await asyncio.to_thread(
                lambda m=modelo: gemini_client.models.generate_content(
                    model=m,
                    contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
                    config=types.GenerateContentConfig(max_output_tokens=120, temperature=0.95)
                )
            )
            return r.text.strip()
        except Exception as e:
            print(f"[GEMINI ERR {modelo}]: {e}")
            continue

    # 3. TENTA GROQ SE TODOS FALHAREM
    try:
        r = await asyncio.to_thread(
            lambda: groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=120, temperature=0.92,
            )
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        print(f"[GROQ ERR]: {e}")
        
    return random.choice(["hm", "q", "aff", "tá", "..."])

async def gerar_resposta(user_id: str, query: str, contexto_extra: str = "") -> str:
    humor = await descrever_humor_atual()
    ctx   = await contexto_usuario(user_id)

    system = f"{PERSONALIDADE}\n\n{humor}\nUSUÁRIO ATUAL: {ctx}"
    if contexto_extra:
        system += f"\n\nCONTEXTO: {contexto_extra}"

    u = await get_usuario(user_id)
    historico = _lista(u["historico"])

    # Prepara mensagens formato OpenAI (usado por Qwen e Groq)
    msgs = [{"role": "system", "content": system}]
    for linha in historico[-12:]:
        if linha.startswith("U:"):
            msgs.append({"role": "user", "content": linha[2:]})
        elif linha.startswith(("E:", "S:")):
            msgs.append({"role": "assistant", "content": linha[2:]})
    msgs.append({"role": "user", "content": query})

    # 1. TENTA QWEN PRIMEIRO
    try:
        r = await asyncio.to_thread(
            lambda: qwen_client.chat.completions.create(
                model=MODELO_QWEN,
                messages=msgs,
                max_tokens=120,
                temperature=0.92,
            )
        )
        print("[QWEN] Sucesso")
        return r.choices[0].message.content.strip()
    except Exception as e:
        print(f"[QWEN ERR]: {e}")

    # 2. TENTA GEMINI SE O QWEN FALHAR
    contents = _montar_historico_gemini(historico)
    contents.append(types.Content(role="user", parts=[types.Part(text=query)]))

    for modelo in MODELOS_GEMINI:
        try:
            r = await asyncio.to_thread(
                lambda m=modelo: gemini_client.models.generate_content(
                    model=m,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        max_output_tokens=120,
                        temperature=0.95,
                    )
                )
            )
            print(f"[GEMINI] {modelo}")
            return r.text.strip()
        except Exception as e:
            print(f"[GEMINI ERR {modelo}]: {e}")
            continue

    # 3. TENTA GROQ SE TODOS FALHAREM
    try:
        r = await asyncio.to_thread(
            lambda: groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=msgs,
                max_tokens=120,
                temperature=0.92,
            )
        )
        print("[FALLBACK] Groq")
        return r.choices[0].message.content.strip()
    except Exception as e:
        print(f"[GROQ ERR]: {e}")

    return random.choice(["hm", "q", "aff", "tá", "..."])

# ─────────────────────────────────────────
#  BOT
# ─────────────────────────────────────────
class Eva(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(intents=intents)

    async def setup_hook(self):
        await init_db()
        await inicializar_humor_diario()
        asyncio.create_task(scheduler_humor())
        asyncio.create_task(scheduler_aniversarios(self))
        asyncio.create_task(scheduler_status(self))

    async def on_ready(self):
        print(f"[EVA] Online: {self.user}")

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        texto = message.content.strip()
        tl    = texto.lower()

        mencionada  = self.user in message.mentions
        nome_citado = bool(re.search(r'\beva\b', tl))

        # Moderação — roda em todas as mensagens que mencionem ela
        if mencionada or nome_citado:
            deletado = await moderar_mensagem(message)
            if deletado:
                return

        # Visão — imagem enviada e Eva mencionada
        if (mencionada or nome_citado) and message.attachments:
            for att in message.attachments:
                resposta_imagem = await avaliar_imagem(message, att)
                if resposta_imagem:
                    await message.reply(resposta_imagem)
                    return

        # Gatilhos espontâneos em mensagens sem menção
        if not mencionada and not nome_citado:
            asyncio.create_task(verificar_gatilho_espontaneo(message))
            return

        # Registra interação do dia pra status
        _interacoes_hoje[str(message.author.id)] = message.author.display_name

        user_id     = str(message.author.id)
        display     = message.author.display_name
        channel_id  = str(message.channel.id)
        texto_limpo = re.sub(r'<@!?\d+>', '', texto).strip()

        async with message.channel.typing():
            await asyncio.sleep(random.uniform(0.5, 1.3))

            intent_data = await classificar_intencao(texto_limpo)
            intent = intent_data.get("intent", "chat")
            query  = intent_data.get("query", texto_limpo)
            extra  = ""

            if intent == "search":
                resultado = await asyncio.to_thread(buscar, query)
                if resultado:
                    extra = f"Resultado de busca: {resultado}"
                else:
                    extra = "[busca não retornou nada. Use seu conhecimento pra responder no estilo Eva, ou deboche da pergunta se for idiota.]"

            resposta = await gerar_resposta(user_id, query, extra)
            await atualizar_usuario(user_id, texto_limpo, resposta, display, channel_id)
            await message.reply(resposta)


Eva().run(DISCORD_TOKEN)
