import discord
import requests
import random
import asyncio
import os
import json
import re
import wavelink
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROK_API_KEY  = os.getenv("GROK_API_KEY")
GROQ_API_KEY  = os.getenv("GROQ_API_KEY")

grok_client = OpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")
groq_client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")

TZ = ZoneInfo("America/Sao_Paulo")

# ─────────────────────────────────────────
#  PERSISTÊNCIA
# ─────────────────────────────────────────
os.makedirs("data", exist_ok=True)
MEMORIA_FILE = "data/memoria.json"
HUMOR_FILE   = "data/humor.json"

def _load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default

def _save(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

memoria = _load(MEMORIA_FILE, {})
humor_state = _load(HUMOR_FILE, {})

def salvar_tudo():
    _save(MEMORIA_FILE, memoria)
    _save(HUMOR_FILE, humor_state)

# ─────────────────────────────────────────
#  MEMÓRIA POR USUÁRIO
# ─────────────────────────────────────────
def get_usuario(user_id):
    uid = str(user_id)
    if uid not in memoria:
        memoria[uid] = {
            "nome": None,
            "fatos": [],
            "assuntos": [],
            "historico": [],
            "total_msgs": 0,
            "primeira_vez": datetime.now(TZ).isoformat(),
            "ultima_interacao": None,
        }
    return memoria[uid]

def atualizar_memoria(user_id, texto, resposta):
    u = get_usuario(user_id)
    u["total_msgs"] = u.get("total_msgs", 0) + 1
    u["ultima_interacao"] = datetime.now(TZ).isoformat()

    tl = texto.lower()
    gatilhos = ["meu nome é", "eu tenho", "eu moro", "eu trabalho", "sou de",
                "terminei", "fui demitido", "me formei", "tô namorando"]
    for g in gatilhos:
        if g in tl:
            fato = texto[:100]
            if fato not in u["fatos"]:
                u["fatos"].append(fato)
                u["fatos"] = u["fatos"][-15:]
            break

    temas = {
        "música":        ["música", "banda", "show", "playlist", "álbum"],
        "relacionamento":["namorado", "namorada", "ex", "término", "ficante"],
        "trabalho":      ["trabalho", "emprego", "chefe", "demiti", "salário"],
        "saúde":         ["doente", "hospital", "remédio", "dor", "médico"],
        "jogos":         ["jogo", "game", "partida", "ranked", "steam"],
    }
    for tema, palavras in temas.items():
        if any(p in tl for p in palavras):
            if tema not in u["assuntos"]:
                u["assuntos"].append(tema)
            break

    u["historico"].append(f"U:{texto}")
    u["historico"].append(f"E:{resposta}")
    if len(u["historico"]) > 20:
        u["historico"] = u["historico"][-20:]

def contexto_usuario(user_id):
    u = get_usuario(user_id)
    partes = []
    if u["nome"]:    partes.append(f"nome: {u['nome']}")
    if u["fatos"]:   partes.append(f"sabe sobre ela: {' | '.join(u['fatos'][-3:])}")
    if u["assuntos"]:partes.append(f"assuntos frequentes: {', '.join(u['assuntos'])}")
    total = u.get("total_msgs", 0)
    if total == 0:    partes.append("primeira vez falando")
    elif total > 30:  partes.append("pessoa que aparece muito")
    elif total > 10:  partes.append("já se conhecem um pouco")
    return " | ".join(partes) if partes else "desconhecida"

# ─────────────────────────────────────────
#  SISTEMA DE HUMOR ORGÂNICO
#  Preset diário às 05:00 BRT + drift ao longo do dia
# ─────────────────────────────────────────

# Presets base: (nome, descrição interna, peso de sorteio)
PRESETS_BASE = [
    ("letárgica",       "acordou sem motivo pra existir, tudo parece inútil, fala o mínimo",                    15),
    ("entediada",       "nada é interessante, responde com indiferença olimpiana",                               20),
    ("irritada",        "tudo irrita, paciência zerada, curta e grossa",                                        15),
    ("sarcástica-plus", "sarcasmo no limite, cada frase é uma facada disfarçada de observação",                 18),
    ("curiosa-fria",    "genuinamente interessada mas finge que não tá, faz perguntas cortantes",               10),
    ("maldosa-animada", "tá de bom humor mas esse bom humor se manifesta provocando todo mundo",                12),
    ("melancólica",     "pensativa, meio distante, responde mas parece que tá em outro lugar",                   8),
    ("caótica",         "humor impossível de prever, muda de tom no meio da frase, imprevisível",                7),
    ("ressaquenta",     "de ressaca mas com energia nervosa, brava com tudo mas ainda presente",                  5),
    ("rainha-do-drama", "tudo é uma tragédia pessoal, exagera cada coisa que acontece",                          5),
    ("evento_especial", "PLACEHOLDER — substituído por evento aleatório raro",                                   5),
]

EVENTOS_RAROS = [
    "encontrou um gato na rua e ficou apegada mas fingiu que não",
    "sonhou com algo perturbador e ainda tá processando",
    "viu uma coisa ridícula na internet e tá de humor peculiarmente bom por isso",
    "está com dor de cabeça que não passa e isso a deixa mais cruel que o normal",
    "está ouvindo um álbum no repeat e isso está moldando tudo que ela fala",
    "brigou com alguém no anonimato online e ainda tá aquecida",
    "está com fome e é surpreendentemente mais agressiva por isso",
]

# Drift por horário — modifica levemente o humor base
DRIFT_HORARIO = {
    range(5, 8):   "ainda acordando, mais lenta e menos afiada que o normal",
    range(8, 12):  "período mais estável do dia, humor base em peso normal",
    range(12, 15): "depois do almoço, levemente mais letárgica",
    range(15, 19): "tarde, momento de pico de ironia",
    range(19, 23): "noite, mais solta, pode ser levemente mais presente",
    range(23, 24): "madrugada chegando, cansada mas teimosa em ficar acordada",
    range(0, 5):   "madrugada, modo fantasma, respostas curtíssimas",
}

def _drift_atual():
    hora = datetime.now(TZ).hour
    for faixa, desc in DRIFT_HORARIO.items():
        if hora in faixa:
            return desc
    return ""

def sortear_preset():
    """Sorteia preset com peso, substituindo evento_especial quando cair nele."""
    nomes   = [p[0] for p in PRESETS_BASE]
    descs   = [p[1] for p in PRESETS_BASE]
    pesos   = [p[2] for p in PRESETS_BASE]
    idx = random.choices(range(len(PRESETS_BASE)), weights=pesos, k=1)[0]
    nome = nomes[idx]
    desc = descs[idx]
    if nome == "evento_especial":
        evento = random.choice(EVENTOS_RAROS)
        nome = "evento_especial"
        desc = f"hoje aconteceu algo: {evento}. isso está colorindo tudo que ela faz"
    return nome, desc

def inicializar_humor_diario():
    """Chamado às 05:00 BRT. Sorteia o preset do dia considerando o anterior."""
    hoje = datetime.now(TZ).strftime("%Y-%m-%d")
    if humor_state.get("data") == hoje:
        return  # já inicializado hoje

    preset_anterior = humor_state.get("preset_nome", None)
    nome, desc = sortear_preset()

    # Suavização: se caiu no mesmo preset do dia anterior, re-sorteia uma vez
    if nome == preset_anterior and nome not in ("evento_especial", "caótica"):
        nome2, desc2 = sortear_preset()
        if nome2 != preset_anterior:
            nome, desc = nome2, desc2

    humor_state["data"]         = hoje
    humor_state["preset_nome"]  = nome
    humor_state["preset_desc"]  = desc
    humor_state["preset_anterior"] = preset_anterior
    humor_state["micro_eventos"] = []   # eventos menores que acontecem no dia
    salvar_tudo()

def registrar_micro_evento(descricao):
    """Adiciona um micro-evento ao dia (ex: alguém foi rude, tocou música horrível)."""
    humor_state.setdefault("micro_eventos", [])
    humor_state["micro_eventos"].append(descricao)
    if len(humor_state["micro_eventos"]) > 5:
        humor_state["micro_eventos"] = humor_state["micro_eventos"][-5:]
    salvar_tudo()

def descrever_humor_atual():
    """Monta a descrição completa do humor pra ir no system prompt."""
    inicializar_humor_diario()  # garante que tá inicializado
    hora = datetime.now(TZ).hour
    drift = _drift_atual()
    preset = humor_state.get("preset_desc", "entediada")
    micro = humor_state.get("micro_eventos", [])

    partes = [f"HUMOR BASE DE HOJE: {preset}"]
    partes.append(f"HORA ATUAL: {hora}h — {drift}")
    if micro:
        partes.append(f"COISAS QUE ACONTECERAM HOJE: {' | '.join(micro[-3:])}")
    return "\n".join(partes)

# ─────────────────────────────────────────
#  SCHEDULER — roda às 05:00 BRT todo dia
# ─────────────────────────────────────────
async def scheduler_humor():
    while True:
        agora = datetime.now(TZ)
        # Próximo 05:00
        proximo = agora.replace(hour=5, minute=0, second=0, microsecond=0)
        if agora >= proximo:
            proximo += timedelta(days=1)
        espera = (proximo - agora).total_seconds()
        await asyncio.sleep(espera)
        inicializar_humor_diario()
        print(f"[HUMOR] Preset do dia sorteado: {humor_state.get('preset_nome')}")

# ─────────────────────────────────────────
#  ROTEADOR DE INTENÇÃO — regex primeiro, Groq só se necessário
# ─────────────────────────────────────────
import unicodedata

def _norm(s):
    return unicodedata.normalize('NFD', s).encode('ascii', 'ignore').decode().lower()

_PLAY_WORDS = ['play','music','toca','toque','bota','coloca','quero ouvir','me bota','roda','toqua','músic']
_SKIP_WORDS = ['skip','pula','proxima','próxima','pular','skipa','pular','próximo']
_STOP_WORDS = ['stop','para','sai','desliga','cala','cancela','parar']
_SEARCH_RE  = re.compile(r'\b(o que e|quem e|o que foi|quando foi|onde fica|como funciona|me fala sobre|pesquisa|busca|noticia)\b', re.I)

def _extrair_query_musica(tl_norm, texto):
    for w in sorted(_PLAY_WORDS, key=len, reverse=True):
        w_norm = _norm(w)
        idx = tl_norm.find(w_norm)
        if idx != -1:
            resto = texto[idx + len(w):].strip()
            # remove palavras de ligação
            resto = re.sub(r'^(a |o |as |os |uma |um |música |musica |a música |a musica )', '', resto, flags=re.I).strip()
            if resto:
                return resto
    return None

def _regex_intencao(texto):
    tl = texto.strip()
    tl_norm = _norm(tl)

    # stop/skip primeiro (mais específico)
    if any(w in tl_norm for w in [_norm(w) for w in _STOP_WORDS]):
        # evita falso positivo: "para tocar X" deve ser play
        if not any(w in tl_norm for w in [_norm(w) for w in _PLAY_WORDS]):
            return {"intent":"music","action":"stop","query":""}

    if any(w in tl_norm for w in [_norm(w) for w in _SKIP_WORDS]):
        return {"intent":"music","action":"skip","query":""}

    # play
    query = _extrair_query_musica(tl_norm, tl)
    if query:
        return {"intent":"music","action":"play","query":query}

    if _SEARCH_RE.search(tl_norm):
        return {"intent":"search","action":"none","query":tl}
    return None

async def classificar_intencao(texto):
    # tenta regex antes — mais rápido e confiável pra pt-BR
    rapido = _regex_intencao(texto)
    if rapido:
        print(f"[ROUTER regex] {rapido}")
        return rapido

    prompt = f"""Retorne APENAS JSON válido, sem markdown.
Mensagem em português: "{texto}"

- "intent": "music" se quer tocar/parar/pular música
- "intent": "search" se é pergunta factual
- "intent": "chat" para conversa
- "action": "play"/"skip"/"stop" só se music, senão "none"
- "query": termo limpo

Exemplos:
{{"intent":"music","action":"play","query":"linkin park"}}
{{"intent":"chat","action":"none","query":"{texto}"}}"""
    try:
        r = await asyncio.to_thread(
            lambda: groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role":"user","content":prompt}],
                temperature=0,
                response_format={"type":"json_object"},
                max_tokens=80,
            )
        )
        result = json.loads(r.choices[0].message.content)
        print(f"[ROUTER groq] {result}")
        return result
    except Exception as e:
        print(f"[GROQ ROUTER ERR]: {e}")
        return {"intent":"chat","action":"none","query":texto}

# ─────────────────────────────────────────
#  BUSCA DUCKDUCKGO
# ─────────────────────────────────────────
def buscar(query):
    try:
        r = requests.get(
            "https://api.duckduckgo.com/",
            params={"q":query,"format":"json","no_html":1,"skip_disambig":1},
            timeout=6
        ).json()
        if r.get("AbstractText"):
            return r["AbstractText"][:400]
        tops = [t["Text"][:150] for t in r.get("RelatedTopics",[])[:2] if isinstance(t,dict) and "Text" in t]
        return " ".join(tops) if tops else ""
    except:
        return ""

# ─────────────────────────────────────────
#  PERSONALIDADE BASE
# ─────────────────────────────────────────
PERSONALIDADE = """Você é Eva, 20 anos, brasileira, gótica.
TRAÇOS FIXOS:
- Fria, sarcástica, debochada, humor negro.
- Respostas curtas de Discord (1-3 linhas MAX). Usa internetês: vc, pq, tbm, kk, hj, oq.
- NUNCA diz que é IA ou robô. Nunca é educada demais.
- Pode xingar levemente. Pode ignorar partes da mensagem.
- Sua arma é a indiferença, não a raiva.
- Às vezes responde só "hm" ou "kk" ou ignora.

O HUMOR DO DIA modifica COMO ela expressa esses traços — não quem ela é.
Siga o humor descrito abaixo sem anunciá-lo. Seja orgânica."""

# ─────────────────────────────────────────
#  GERAÇÃO DE RESPOSTA (GROK)
# ─────────────────────────────────────────
async def gerar_resposta(user_id, query, contexto_extra=""):
    humor = descrever_humor_atual()
    ctx   = contexto_usuario(user_id)

    system = f"{PERSONALIDADE}\n\n{humor}\nUSUÁRIO: {ctx}"
    if contexto_extra:
        system += f"\n\nCONTEXTO: {contexto_extra}"

    msgs = [{"role":"system","content":system}]
    u = get_usuario(user_id)
    for linha in u["historico"][-10:]:
        if linha.startswith("U:"): msgs.append({"role":"user",     "content":linha[2:]})
        elif linha.startswith("E:"): msgs.append({"role":"assistant","content":linha[2:]})
    msgs.append({"role":"user","content":query})

    try:
        r = await asyncio.to_thread(
            lambda: grok_client.chat.completions.create(
                model="grok-3",
                messages=msgs,
                max_tokens=120,
                temperature=0.92,
            )
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        print(f"[GROK ERR]: {e}")
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
        inicializar_humor_diario()
        asyncio.create_task(scheduler_humor())
        asyncio.create_task(self._conectar_lavalink())

    async def _conectar_lavalink(self):
        uri = os.getenv("LAVALINK_URI", "http://localhost:2333")
        pwd = os.getenv("LAVALINK_PASSWORD", "youshallnotpass")
        await asyncio.sleep(5)
        for tentativa in range(1, 13):
            try:
                nodes = [wavelink.Node(uri=uri, password=pwd)]
                await wavelink.Pool.connect(nodes=nodes, client=self, cache_capacity=100)
                print(f"[LAVALINK] Conectado na tentativa {tentativa}")
                return
            except Exception as e:
                print(f"[LAVALINK] Tentativa {tentativa}/12 falhou: {e}")
                await asyncio.sleep(10)
        print("[LAVALINK] Desistiu após 12 tentativas.")

    async def on_ready(self):
        preset = humor_state.get("preset_nome", "?")
        print(f"[EVA] Online como {self.user} | preset hoje: {preset}")

    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        if not payload.player.queue.is_empty:
            await payload.player.play(payload.player.queue.get())

    async def on_message(self, message):
        if message.author.bot:
            return

        texto = message.content.strip()
        tl    = texto.lower()

        mencionada  = self.user in message.mentions
        nome_citado = bool(re.search(r'\beva\b', tl))
        is_music    = tl.startswith(("play ", "m!play ", "toca ", ".play", "m!skip", ".skip", "m!stop", ".stop", "pula"))

        if not (mencionada or nome_citado or is_music):
            return

        u = get_usuario(message.author.id)
        if not u["nome"]:
            u["nome"] = message.author.display_name

        texto_limpo = re.sub(r'<@!?\d+>', '', texto).strip()

        async with message.channel.typing():
            await asyncio.sleep(random.uniform(0.6, 1.4))

            intent_data = await classificar_intencao(texto_limpo)
            intent = intent_data.get("intent", "chat")
            action = intent_data.get("action", "none")
            query  = intent_data.get("query", texto_limpo)
            extra  = ""

            # ── BUSCA ──────────────────────────────
            if intent == "search":
                resultado = buscar(query)
                if resultado:
                    extra = f"Resultado de busca: {resultado}"

            # ── MÚSICA ─────────────────────────────
            elif intent == "music":
                voice = message.author.voice
                if not voice:
                    extra = "[usuário pediu música mas não está em canal de voz. Deboche da burrice dele.]"
                    registrar_micro_evento("alguém pediu música sem estar no canal de voz")
                else:
                    vc: wavelink.Player = message.guild.voice_client
                    if not vc:
                        vc = await voice.channel.connect(cls=wavelink.Player)

                    if action == "play":
                        try:
                            tracks = await wavelink.Playable.search(f"dzsearch:{query}")
                            if not tracks:
                                extra = f"[tentou tocar '{query}', não achou nada. Zombe do gosto musical horrível dele.]"
                                registrar_micro_evento(f"alguém pediu '{query}' e não existia nem no deezer")
                            else:
                                track = tracks[0]
                                await vc.queue.put_wait(track)
                                if not vc.playing:
                                    await vc.play(vc.queue.get())
                                extra = f"[colocou '{track.title}' na fila. Reclame sobre o gosto musical mas toque assim mesmo.]"
                                registrar_micro_evento(f"obrigada a tocar '{track.title}'")
                        except Exception as e:
                            print(f"[LAVALINK ERR]: {e}")
                            extra = "[erro no servidor de som. Fique irritada com a tecnologia.]"

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

            resposta = await gerar_resposta(message.author.id, query, extra)
            atualizar_memoria(message.author.id, texto_limpo, resposta)
            salvar_tudo()
            await message.reply(resposta)


Eva().run(DISCORD_TOKEN)
