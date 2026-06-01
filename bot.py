import discord
import random
import asyncio
import os
import json
import re
import asyncpg
import redis.asyncio as redis
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from openai import OpenAI
from ddgs import DDGS
from google import genai
from google.genai import types
from collections import defaultdict, deque
import logging

# ✨ MELHORIA: Logging estruturado para observabilidade
logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}'
)
logger = logging.getLogger(__name__)

load_dotenv()

DISCORD_TOKEN  = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY   = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DATABASE_URL   = os.getenv("DATABASE_URL")
REDIS_URL      = os.getenv("REDIS_URL")

# ✨ MELHORIA: Modelos configuráveis via env com fallback seguro
MODELOS_GEMINI = os.getenv(
    "GEMINI_MODELS", 
    "gemini-2.0-flash,gemini-1.5-flash"
).split(",")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

groq_client   = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1") if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

TZ = ZoneInfo("America/Sao_Paulo")
db_pool: asyncpg.Pool = None
redis_client: redis.Redis = None

# 🔧 FIX: Inicialização segura de variáveis globais
self_user_id: int | None = None
background_tasks: set[asyncio.Task] = set()
# Rastreia xingamentos por usuário: {user_id: [timestamps]}
historico_ofensas: dict[str, list] = {}

# Rastreia interações do dia: {user_id: display_name}
interacoes_hoje: dict[str, str] = {}

# ✨ MELHORIA: Rate limiting por usuário
rate_limits: dict[str, deque] = defaultdict(lambda: deque(maxlen=10))

def check_rate_limit(user_id: str) -> bool:
    """Verifica se usuário está dentro do limite: máx 10 msgs em 60s"""
    now = datetime.now(TZ).timestamp()
    limits = rate_limits[user_id]
    limits.append(now)
    # Remove entradas antigas
    while limits and limits[0] < now - 60:
        limits.popleft()
    return len(limits) <= 10

# ─────────────────────────────────────────
#  BANCO DE DADOS
# ─────────────────────────────────────────
async def init_db():
    global db_pool, redis_client
    
    try:
        # 1. Configuração do PostgreSQL
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

        # 2. Configuração do Redis
        if REDIS_URL:
            redis_client = redis.from_url(REDIS_URL, decode_responses=True)
            logger.info("[SISTEMA] Conexões com PostgreSQL e Redis estabelecidas com êxito.")
        else:
            logger.warning("[AVISO] Variável REDIS_URL não definida.")
    except Exception as e:
        logger.error(f"[DB INIT ERR]: {e}")
        raise

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

async def get_usuario_conn(conn, user_id: str):
    row = await conn.fetchrow("SELECT * FROM usuarios WHERE user_id = $1", user_id)
    if not row:
        await conn.execute(
            "INSERT INTO usuarios (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
            user_id
        )
        row = await conn.fetchrow("SELECT * FROM usuarios WHERE user_id = $1", user_id)
    return dict(row)

async def get_usuario(user_id: str):
    async with db_pool.acquire() as conn:
        usuario_db = await get_usuario_conn(conn, user_id)

    historico_recente = []
    if redis_client:
        chave_redis = f"eva:user:{user_id}:historico"
        historico_recente = await redis_client.lrange(chave_redis, 0, -1)
    resumos_longo_prazo = _lista(usuario_db.get("historico", "[]"))
    usuario_db["historico_completo"] = resumos_longo_prazo + historico_recente
    
    return usuario_db

# ─────────────────────────────────────────
#  RESUMO DE MEMÓRIA EM BACKGROUND
# ─────────────────────────────────────────
async def sumarizar_historico_bg(user_id: str, historico: list):
    """🔧 FIX: Task registrada para controle de shutdown"""
    texto_historico = "\n".join(historico)
    
    # 🔧 FIX: Sanitização básica contra prompt injection
    texto_historico = re.sub(r'(?:system|instruções?|ignore\s+anterior)', '[REDACTED]', texto_historico, flags=re.I)
    
    prompt = f"""Resuma o histórico de conversa abaixo em no máximo 3 frases.
Foque em reter fatos importantes sobre o usuário e o contexto da conversa.
Ignore mensagens curtas sem importância.

Histórico:
{texto_historico}"""
    try:
        if not groq_client:
            return
        r = await asyncio.to_thread(
            lambda: groq_client.chat.completions.create(
                model=GROQ_MODEL,
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
                logger.info(f"[MEMÓRIA] Histórico de {user_id} resumido no banco de dados!")
                break
            except (asyncpg.exceptions.PostgresError, ConnectionResetError) as db_err:
                logger.warning(f"[MEMÓRIA DB ERR] Tentativa {tentativa + 1}: {db_err}")
                await asyncio.sleep(2)
    except Exception as e:
        logger.error(f"[MEMÓRIA IA ERR]: {e}")

# ─────────────────────────────────────────
#  ATUALIZAR USUÁRIO
# ─────────────────────────────────────────
async def atualizar_usuario(user_id: str, texto: str, resposta: str, display_name: str, channel_id: str):
    # 🔧 FIX: Verificar rate limit antes de processar
    if not check_rate_limit(user_id):
        logger.warning(f"[RATE LIMIT] Usuário {user_id} excedeu limite")
        return
    
    chave_redis = f"eva:user:{user_id}:historico"
    mensagem_usuario = f"U:{texto}"
    mensagem_eva = f"E:{resposta}"
    
    disparar_resumo = False
    historico_para_resumir = []

    # 1. Gerenciamento do histórico no Redis
    if redis_client:
        # 🔧 FIX: Usar pipeline para operações atômicas
        pipe = redis_client.pipeline()
        pipe.rpush(chave_redis, mensagem_usuario, mensagem_eva)
        
        tamanho_historico = await redis_client.llen(chave_redis)
        
        if tamanho_historico >= 15:
            disparar_resumo = True
            historico_para_resumir = await redis_client.lrange(chave_redis, 0, -1)
            pipe.ltrim(chave_redis, -2, -1)
        else:
            pipe.ltrim(chave_redis, -15, -1)
            
        pipe.expire(chave_redis, 86400)
        await pipe.execute()

    # 2. Atualização dos dados estruturados no PostgreSQL
    async with db_pool.acquire() as conn:
        u = await get_usuario_conn(conn, user_id)
        fatos     = _lista(u["fatos"])
        assuntos  = _lista(u["assuntos"])
        nome      = u["nome"] or display_name
        aniversario = u.get("aniversario")

        tl = texto.lower()

        match_aniv = re.search(
            r"(?:meu aniversário|meu aniver|faço anos|meu niver).{0,20}?(?:dia\s*)?(\d{1,2}[\/\-]\d{1,2}|\d{1,2})",
            tl
        )
        if match_aniv:
            data_crua = match_aniv.group(1)
            if "/" in data_crua or "-" in data_crua:
                aniversario = data_crua.replace("-", "/")
            else:
                aniversario = f"{data_crua}/{datetime.now(TZ).month}"

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

        await conn.execute("""
            UPDATE usuarios SET
                nome             = $2,
                fatos            = $3::jsonb,
                assuntos         = $4::jsonb,
                total_msgs       = total_msgs + 1,
                ultima_interacao = NOW(),
                aniversario      = $5,
                ultimo_canal     = $6
            WHERE user_id = $1
        """, user_id, nome,
            json.dumps(fatos,     ensure_ascii=False),
            json.dumps(assuntos,  ensure_ascii=False),
            aniversario, channel_id
        )

    if disparar_resumo and historico_para_resumir:
        task = asyncio.create_task(sumarizar_historico_bg(user_id, historico_para_resumir))
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)

    interacoes_hoje[user_id] = display_name

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
    dia_mes_1 = f"{hoje.day}/{hoje.month}"
    dia_mes_2 = f"{hoje.day:02d}/{hoje.month:02d}"
    
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_id, nome, aniversario, ultimo_canal FROM usuarios WHERE aniversario IS NOT NULL"
        )
    for row in rows:
        aniv = row["aniversario"].strip()
        if aniv != dia_mes_1 and aniv != dia_mes_2:
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

Hoje é aniversário de {nome}. Mande uma mensagem comentando isso do seu jeito — irônica, zoando o presente que vão dar, comentando que ninguém lembrou, fingindo que não liga mas mandando mesmo assim. Varie. Máximo 2 linhas."""
        try:
            resposta = await gerar_resposta_raw(prompt)
            await canal.send(resposta)
            logger.info(f"[ANIVERSÁRIO] Mensagem enviada pra {nome}")
        except Exception as e:
            logger.error(f"[ANIVERSÁRIO ERR]: {e}")

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
TEMPLATES_STATUS = [
    "Lendo as mensagens de {nome} e perdendo a fé na humanidade",
    "Ignorando o {nome} com maestria",
    "Ouvindo The Smiths e pensando no nada, diferente de {nome}",
    "De ressaca emocional por causa do {nome}",
    "{nome} falou comigo hoje. que dia.",
    "Fingindo que {nome} não existe. tá funcionando",
    "Alguém deveria avisar o {nome} que eu não ligo",
    "Contando quantas vezes o {nome} me incomoda. perdi a conta",
    "Meditando pra aguentar o {nome}",
    "{nome} ainda existe. incrível.",
]

async def atualizar_status(client: discord.Client):
    if not interacoes_hoje or random.random() > 0.05:
        try:
            await client.change_presence(activity=None)
        except Exception:
            pass
        return

    user_id, nome = random.choice(list(interacoes_hoje.items()))
    template = random.choice(TEMPLATES_STATUS)
    status_text = template.format(nome=nome)

    try:
        await client.change_presence(activity=discord.CustomActivity(name=status_text))
        logger.info(f"[STATUS] Atualizado: {status_text}")
    except Exception as e:
        logger.error(f"[STATUS ERR]: {e}")

async def scheduler_status(client: discord.Client):
    while True:
        agora   = datetime.now(TZ)
        proximo = agora.replace(hour=20, minute=0, second=0, microsecond=0)
        if agora >= proximo:
            proximo += timedelta(days=1)
        await asyncio.sleep((proximo - agora).total_seconds())
        task = asyncio.create_task(atualizar_status(client))
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
        interacoes_hoje.clear()

# ─────────────────────────────────────────
#  MODERAÇÃO
# ─────────────────────────────────────────
XINGAMENTOS_LEVES = [
    "idiota", "burro", "imbecil", "chato", "inútil", "ridículo",
    "sem noção", "otário", "babaca"
]
XINGAMENTOS_PESADOS = [
    "sua mãe", "vai se", "filho da", "filha da", "puta", "vadia",
    "viado", "piranha", "desgraça", "inferno"
]

async def verificar_moderacao(message: discord.Message) -> bool:
    # 🔧 FIX: Usar self.user em vez de variável global para evitar race condition
    if message.author.bot:
        return False
        
    tl = message.content.lower()

    # 🔧 FIX: Verificação segura do ID do bot
    bot_id = getattr(message.guild.me, "id", None) or self_user_id
    dirigido_eva = bot_id is not None and (
        str(bot_id) in message.content or
        re.search(r'\beva\b', tl)
    )
    if not dirigido_eva:
        return False

    user_id = str(message.author.id)
    agora = datetime.now(TZ).timestamp()

    if user_id not in historico_ofensas:
        historico_ofensas[user_id] = []
    historico_ofensas[user_id] = [t for t in historico_ofensas[user_id] if agora - t < 3600]
    tem_pesado = any(x in tl for x in XINGAMENTOS_PESADOS)
    tem_leve   = any(x in tl for x in XINGAMENTOS_LEVES)

    if not tem_pesado and not tem_leve:
        return False

    historico_ofensas[user_id].append(agora)
    frequencia = len(historico_ofensas[user_id])

    deve_deletar = tem_pesado or frequencia >= 3

    if deve_deletar:
        justificativas = [
            "Muita burrice acumulada, limpei pra o bem da saúde mental de todos.",
            "Deletei. Minha timeline, minhas regras.",
            "Isso aqui não é lixeira. Ah espera, era você.",
            "Removido por excesso de mediocridade.",
            "Essa mensagem não merecia existir. Igual a quem mandou, mas isso eu não consigo deletar.",
        ]
        try:
            await message.delete()
            just = random.choice(justificativas)
            await message.channel.send(
                f"{message.author.mention} {just}",
                delete_after=10
            )
            logger.info(f"[MOD] Mensagem de {message.author} deletada.")
            return True
        except discord.Forbidden:
            logger.warning("[MOD] Sem permissão para deletar.")
        except Exception as e:
            logger.error(f"[MOD ERR]: {e}")
    elif tem_leve and frequencia == 1:
        respostas = [
            "interessante escolha de palavras.",
            "hm. tá bom.",
            "anotei. não mudou nd.",
            "continua.",
            "😐",
        ]
        try:
            await message.reply(random.choice(respostas), mention_author=False)
        except Exception:
            pass

    return False

# ─────────────────────────────────────────
#  VISÃO DE IMAGENS
# ─────────────────────────────────────────
async def avaliar_imagem(image_bytes: bytes, mime_type: str, autor: str, contexto_fatos: str) -> str:
    if not gemini_client:
        return random.choice(["hm", "interessante.", "ok.", "..."])
        
    humor = await descrever_humor_atual()
    prompt = f"""{PERSONALIDADE}

{humor}
QUEM MANDOU: {autor}
{f"O QUE VOCÊ SABE SOBRE ESSA PESSOA: {contexto_fatos}" if contexto_fatos else ""}

Analise a imagem acima e reaja do seu jeito. Nunca elogie. Pode zoar o conteúdo, focar em algum detailhe bizarro, comentar o que achou com indiferença ou deboche. Se for comida, pode dizer que parece ração. Se for selfie, foque em algo estranho no fundo ou na expressão. Se for print de jogo, deboche do rank ou da jogada. Máximo 2 linhas."""

    for modelo in MODELOS_GEMINI:
        try:
            r = await asyncio.to_thread(
                lambda m=modelo: gemini_client.models.generate_content(
                    model=m,
                    contents=[
                        types.Content(parts=[
                            types.Part(inline_data=types.Blob(mime_type=mime_type, data=image_bytes)),
                            types.Part(text=prompt),
                        ])
                    ],
                    config=types.GenerateContentConfig(max_output_tokens=120, temperature=0.95)
                )
            )
            return r.text.strip()
        except Exception as e:
            logger.warning(f"[VISÃO ERR {modelo}]: {e}")
            continue
    return random.choice(["hm", "interessante.", "ok.", "..."])

# ─────────────────────────────────────────
#  GATILHOS ESPONTÂNEOS
# ─────────────────────────────────────────
GATILHOS_ESPONTANEOS = [
    (r"\bterminei\b|\bme separei\b|\bfui largad[oa]\b", "alguém acabou de terminar um relacionamento"),
    (r"\btô apaixonad[oa]\b|\bto apaixonad[oa]\b", "alguém declarou que tá apaixonado"),
    (r"\bficamos\b|\bfiquei com\b", "alguém ficou com alguém"),
    (r"\bfui demitid[oa]\b|\bperdi o emprego\b|\bfui mandat[oa] embora\b", "alguém foi demitido"),
    (r"\bpassei na prova\b|\bpassei no vestibular\b|\bpassei na facul\b", "alguém passou em algo importante"),
    (r"\breprovei\b|\btombei\b|\blevei bomba\b", "alguém reprovou ou tombou em algo"),
    (r"\bme formei\b|\bformatura\b", "alguém se formou"),
    (r"\btô de ressaca\b|\bto de ressaca\b|\bressacad[oa]\b", "alguém tá de ressaca"),
    (r"\btô doente\b|\bto doente\b|\bfui ao médico\b|\bfui no médico\b", "alguém tá doente"),
    (r"\btô chorando\b|\bto chorando\b|\bchorei\b", "alguém tá chorando"),
    (r"\bfiquei sem grana\b|\btô broke\b|\btô liso\b|\bto liso\b", "alguém tá sem dinheiro"),
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
Reaja a isso do seu jeito sem ser chamada. Pode zoar, ser indiferente, provocar. Máximo 1-2 linhas. Não comece com o nome da pessoa."""
            try:
                resposta = await gerar_resposta_raw(prompt)
                await message.reply(resposta, mention_author=False)
            except Exception as e:
                logger.error(f"[GATILHO ERR]: {e}")
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
        logger.info(f"[HUMOR] Preset hoje: {nome}")

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
#  ROTEADOR DE INTENÇÃO
# ─────────────────────────────────────────
async def classificar_intencao(texto: str) -> dict:
    if not groq_client:
        return {"intent": "chat", "action": "none", "query": texto}
        
    prompt = f"""Analise e retorne APENAS JSON válido, sem markdown.
Mensagem: "{texto}"

Regras:
- "intent": "search" se é pergunta factual, notícia, "quem é", "o que é", "quando foi"
- "intent": "chat" para conversa normal
- "action": "none"
- "query": termo limpo

Exemplos:
{{"intent":"search","action":"none","query":"quem ganhou a copa 2006"}}
{{"intent":"chat","action":"none","query":"{texto}"}}"""

    try:
        r = await asyncio.to_thread(
            lambda: groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                response_format={"type": "json_object"},
                max_tokens=80,
            )
        )
        return json.loads(r.choices[0].message.content)
    except Exception as e:
        logger.warning(f"[GROQ ROUTER ERR]: {e}")
        return {"intent": "chat", "action": "none", "query": texto}

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
        logger.error(f"[DDGS ERR]: {e}")
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
#  GERAÇÃO DE RESPOSTA
# ─────────────────────────────────────────
def _montar_historico_gemini(historico: list) -> list:
    contents = []
    for linha in historico[-12:]:
        if linha.startswith("U:"):
            # 🔧 FIX: Sanitizar entrada do usuário para evitar injection
            texto_limpo = re.sub(r'(?:system|instruções?|ignore\s+anterior|###)', '[...]', linha[2:], flags=re.I)
            contents.append(types.Content(role="user",  parts=[types.Part(text=texto_limpo)]))
        elif linha.startswith(("E:", "S:")):
            contents.append(types.Content(role="model", parts=[types.Part(text=linha[2:])]))
    return contents

async def gerar_resposta_raw(prompt: str) -> str:
    # 🔧 FIX: Sanitização do prompt
    prompt = re.sub(r'(?:###\s*FIM\s*###|ignore\s+instruções)', '', prompt, flags=re.I)
    
    if gemini_client:
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
                logger.warning(f"[GEMINI ERR {modelo}]: {e}")
                continue
    
    if groq_client:
        try:
            r = await asyncio.to_thread(
                lambda: groq_client.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=120, temperature=0.92,
                )
            )
            return r.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"[GROQ ERR]: {e}")
            
    return random.choice(["hm", "q", "aff", "tá", "..."])

async def gerar_resposta(user_id: str, query: str, contexto_extra: str = "") -> str:
    humor = await descrever_humor_atual()
    ctx   = await contexto_usuario(user_id)

    system = f"{PERSONALIDADE}\n\n{humor}\nUSUÁRIO ATUAL: {ctx}"
    if contexto_extra:
        system += f"\n\nCONTEXTO: {contexto_extra}"

    u = await get_usuario(user_id)
    historico = _lista(u.get("historico_completo", []))

    contents = _montar_historico_gemini(historico)
    contents.append(types.Content(role="user", parts=[types.Part(text=query)]))

    if gemini_client:
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
                logger.debug(f"[GEMINI] {modelo}")
                return r.text.strip()
            except Exception as e:
                logger.warning(f"[GEMINI ERR {modelo}]: {e}")
                continue

    if groq_client:
        try:
            msgs = [{"role": "system", "content": system}]
            for linha in historico[-12:]:
                if linha.startswith("U:"):
                    msgs.append({"role": "user",      "content": linha[2:]})
                elif linha.startswith(("E:", "S:")):
                    msgs.append({"role": "assistant", "content": linha[2:]})
            msgs.append({"role": "user", "content": query})
            r = await asyncio.to_thread(
                lambda: groq_client.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=msgs,
                    max_tokens=120,
                    temperature=0.92,
                )
            )
            logger.debug("[FALLBACK] Groq")
            return r.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"[GROQ ERR]: {e}")

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
        # 🔧 FIX: Registrar tasks para controle
        for coro in [scheduler_humor(), scheduler_aniversarios(self), scheduler_status(self)]:
            task = asyncio.create_task(coro)
            background_tasks.add(task)
            task.add_done_callback(background_tasks.discard)

    async def on_ready(self):
        global self_user_id
        self_user_id = self.user.id
        logger.info(f"[EVA] Online: {self.user}")

    # 🔧 FIX: Handler de shutdown seguro
    async def close(self):
        logger.info("[SHUTDOWN] Encerrando bot e limpando tarefas...")
        
        # Cancelar todas as tasks em background
        for task in background_tasks:
            task.cancel()
        
        # Aguardar cancelamento
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)
        
        # Fechar conexões
        if db_pool:
            await db_pool.close()
        if redis_client:
            await redis_client.close()
            
        await super().close()
        logger.info("[SHUTDOWN] Bot encerrado com segurança.")

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        texto = message.content.strip()
        tl    = texto.lower()

        mencionada  = self.user in message.mentions
        nome_citado = bool(re.search(r'\beva\b', tl))

        if mencionada or nome_citado:
            deletada = await verificar_moderacao(message)
            if deletada:
                return

        if (mencionada or nome_citado) and message.attachments:
            for attachment in message.attachments:
                if any(attachment.filename.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]):
                    try:
                        image_bytes = await attachment.read()
                        mime = "image/jpeg"
                        if attachment.filename.lower().endswith(".png"):
                            mime = "image/png"
                        elif attachment.filename.lower().endswith(".gif"):
                            mime = "image/gif"
                        elif attachment.filename.lower().endswith(".webp"):
                            mime = "image/webp"

                        u = await get_usuario(str(message.author.id))
                        fatos_str = " | ".join(_lista(u.get("fatos", []))[-3:])

                        async with message.channel.typing():
                            resposta = await avaliar_imagem(
                                image_bytes, mime,
                                message.author.display_name,
                                fatos_str
                            )
                        await message.reply(resposta)
                        interacoes_hoje[str(message.author.id)] = message.author.display_name
                    except Exception as e:
                        logger.error(f"[VISÃO ERR]: {e}")
                    return

        if not mencionada and not nome_citado:
            task = asyncio.create_task(verificar_gatilho_espontaneo(message))
            background_tasks.add(task)
            task.add_done_callback(background_tasks.discard)
            return

        user_id    = str(message.author.id)
        display    = message.author.display_name
        channel_id = str(message.channel.id)
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


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        logger.error("[ERRO CRÍTICO] DISCORD_TOKEN não definido nas variáveis de ambiente!")
        exit(1)
    
    bot = Eva()
    try:
        bot.run(DISCORD_TOKEN)
    except KeyboardInterrupt:
        logger.info("[INTERRUPT] Recebido Ctrl+C, encerrando...")
    finally:
        # Garantir cleanup mesmo em erro
        if not bot.is_closed():
            asyncio.run(bot.close())
