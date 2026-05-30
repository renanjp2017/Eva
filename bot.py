import discord
import requests
import random
import asyncio
import os
import json
import re
import wavelink
from datetime import datetime, timedelta
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# =========================================
# ENV & CLIENTS
# =========================================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROK_API_KEY = os.getenv("GROK_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

grok_client = OpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")
groq_client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")

# =========================================
# MEMÓRIA RICA (JSON) PARA O RAILWAY
# =========================================
os.makedirs("data", exist_ok=True) # Cria a pasta de dados se não existir
MEMORIA_FILE = "data/memoria.json" # Salva no volume do Railway

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

def get_usuario(user_id):
    uid = str(user_id)
    if uid not in memoria:
        memoria[uid] = {
            "nome": None,
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

    gatilhos_fatos = ["meu nome é", "eu tenho", "eu moro", "eu trabalho", "sou de", "terminei", "fui demitido"]
    texto_lower = texto_usuario.lower()
    
    for g in gatilhos_fatos:
        if g in texto_lower:
            fato = texto_usuario[:80]
            if fato not in u["fatos"]:
                u["fatos"].append(fato)
                if len(u["fatos"]) > 10: u["fatos"] = u["fatos"][-10:]
            break

    temas = {
        "música": ["música", "banda", "show", "playlist"],
        "relacionamento": ["namorado", "namorada", "ex", "término"],
        "trabalho": ["trabalho", "emprego", "chefe", "demiti"],
    }
    for tema, palavras in temas.items():
        if any(p in texto_lower for p in palavras):
            if tema not in u["assuntos"]: u["assuntos"].append(tema)
            break

    u["historico"].append(f"U:{texto_usuario}")
    u["historico"].append(f"E:{resposta_eva}")
    if len(u["historico"]) > 16:
        u["historico"] = u["historico"][-16:]

def montar_contexto_usuario(user_id):
    u = get_usuario(user_id)
    partes = []
    if u["nome"]: partes.append(f"nome: {u['nome']}")
    if u["fatos"]: partes.append(f"revelou: {' | '.join(u['fatos'][-3:])}")
    if u["assuntos"]: partes.append(f"assuntos: {', '.join(u['assuntos'])}")
    
    total = u.get("total_msgs", 0)
    if total == 0: partes.append("primeira conversa")
    elif total > 15: partes.append("fala bastante com vc")
    
    return " | ".join(partes) if partes else "pessoa nova"

# =========================================
# SISTEMA TAMAGOTCHI
# =========================================
estado_atual = {"humor": "neutra", "evento": None, "evento_expira": None}

EVENTOS_ALEATORIOS = [
    ("perdeu o ônibus", "brava", 30),
    ("travou o celular", "irritada", 20),
    ("alguém a ignorou", "mal humorada", 40),
    ("tédio extremo", "entediada demais", 45),
    ("ressaca leve", "de ressaca", 120),
    ("TPM", "irritadíssima", 480),
    ("tomou café", "um pouco melhor", 30),
    ("ouvindo música boa", "relaxada", 35),
]

def humor_pela_hora():
    hora = datetime.now().hour
    if 2 <= hora < 6: return random.choice(["de ressaca", "exausta"])
    elif 6 <= hora < 9: return random.choice(["sonolenta", "mal humorada"])
    elif 9 <= hora < 12: return random.choice(["neutra", "entediada"])
    elif 12 <= hora < 18: return random.choice(["com preguiça", "cansada"])
    else: return random.choice(["mais solta", "vendo série", "rolando na cama"])

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
    if estado_atual["evento"]:
        return f"{hora}h, humor: {estado_atual['humor']} (motivo: {estado_atual['evento']})"
    return f"{hora}h, humor: {estado_atual['humor']}"

# =========================================
# INTENT ROUTER (GROQ)
# =========================================
async def classificar_intencao(texto):
    prompt = f"""
    Analise a intenção do usuário e retorne APENAS um JSON válido.
    Mensagem: "{texto}"
    
    Regras:
    - "intent": "music" se o usuário quer tocar, parar ou pular música (ex: play, music, m!play, m!skip, toca, pula).
    - "intent": "search" se o usuário faz uma pergunta factual ou busca notícia.
    - "intent": "chat" para conversa normal.
    - "action": "play", "skip", "stop" (apenas se intent for music), senão "none".
    - "query": O termo da pesquisa, nome da música ou a mensagem limpa.
    
    Exemplos de saída:
    {{"intent": "music", "action": "play", "query": "linkin park"}}
    {{"intent": "chat", "action": "none", "query": "{texto}"}}
    """
    try:
        r = await asyncio.to_thread(
            lambda: groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                response_format={"type": "json_object"}
            )
        )
        return json.loads(r.choices[0].message.content)
    except Exception as e:
        print(f"[ERRO GROQ ROUTER]: {e}")
        return {"intent": "chat", "action": "none", "query": texto}

# =========================================
# DUCKDUCKGO SEARCH
# =========================================
def buscar_duckduckgo(query):
    try:
        r = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            timeout=8
        ).json()
        
        if r.get("AbstractText"): return r["AbstractText"][:400]
        elif r.get("RelatedTopics"):
            return "".join([t["Text"][:150] + " " for t in r["RelatedTopics"][:2] if isinstance(t, dict)])
    except:
        pass
    return ""

# =========================================
# IA PRINCIPAL (GROK)
# =========================================
PERSONALIDADE = """Você é Eva, 20 anos, gótica, brasileira.
- Fria, sarcástica, debochada, humor negro.
- Respostas curtas de Discord (1-3 linhas no máximo), usa internetês (vc, pq, tbm, kk, hj).
- NUNCA diga que é IA ou robô. Não seja educada.
- Pode xingar.
- Se o usuário pediu música, aja como se VOCÊ fosse a DJ obrigada a trabalhar, julgando o gosto musical dele."""

async def gerar_resposta(user_id, intent_data, contexto_extra=""):
    atualizar_estado()
    estado = descrever_estado()
    contexto = montar_contexto_usuario(user_id)

    system_prompt = f"{PERSONALIDADE}\n\nESTADO ATUAL: {estado}\nUSUÁRIO: {contexto}"
    if contexto_extra:
        system_prompt += f"\n\nINFO RELEVANTE: {contexto_extra}"

    mensagens = [{"role": "system", "content": system_prompt}]
    
    u = get_usuario(user_id)
    for linha in u["historico"][-8:]:
        if linha.startswith("U:"): mensagens.append({"role": "user", "content": linha[2:]})
        elif linha.startswith("E:"): mensagens.append({"role": "assistant", "content": linha[2:]})
        
    mensagens.append({"role": "user", "content": intent_data["query"]})

    try:
        r = await asyncio.to_thread(
            lambda: grok_client.chat.completions.create(
                model="grok-3",
                messages=mensagens,
                max_tokens=150,
                temperature=0.9
            )
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        print(f"[ERRO GROK]: {e}")
        return random.choice(["hm", "aff", "q", "me deixa em paz", "tá"])

# =========================================
# CLIENTE DISCORD COM WAVELINK (LAVALINK)
# =========================================
class EvaBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)

    async def setup_hook(self):
        # Puxa a URL do Lavalink do Railway
        lavalink_uri = os.getenv("LAVALINK_URI", "http://localhost:2333")
        nodes = [wavelink.Node(uri=lavalink_uri, password="youshallnotpass")]
        await wavelink.Pool.connect(nodes=nodes, client=self, cache_capacity=100)

    async def on_ready(self):
        print(f"🔥 Eva online como {self.user} e conectada ao Lavalink!")

    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        if not payload.player.queue.is_empty:
            next_track = payload.player.queue.get()
            await payload.player.play(next_track)

    async def on_message(self, message):
        if message.author.bot:
            return

        texto = message.content.strip()
        texto_lower = texto.lower()
        
        is_mentioned = self.user in message.mentions
        has_name = bool(re.search(r'\beva\b', texto_lower))
        is_music = texto_lower.startswith(("play ", "music ", "m!", "toca ", "pula", ".skip", ".stop", ".play"))
        
        if not (is_mentioned or has_name or is_music):
            return

        u = get_usuario(message.author.id)
        if not u["nome"]: u["nome"] = message.author.display_name

        texto_limpo = texto.replace(f"<@{self.user.id}>", "").strip()

        async with message.channel.typing():
            await asyncio.sleep(random.uniform(0.8, 1.5))
            
            intent_data = await classificar_intencao(texto_limpo)
            intent = intent_data.get("intent", "chat")
            action = intent_data.get("action", "none")
            query = intent_data.get("query", texto_limpo)
            
            contexto_extra = ""

            if intent == "search":
                busca = buscar_duckduckgo(query)
                if busca: contexto_extra = f"Resultado do DuckDuckGo: {busca}"
                
            elif intent == "music":
                voice_state = message.author.voice
                
                if not voice_state:
                    contexto_extra = "[O usuário pediu música, mas não está num canal de voz. Ofenda a falta de inteligência dele.]"
                else:
                    vc: wavelink.Player = message.guild.voice_client
                    if not vc:
                        vc = await voice_state.channel.connect(cls=wavelink.Player)
                    
                    if action == "play":
                        try:
                            tracks = await wavelink.Playable.search(f"dzsearch:{query}")
                            if not tracks:
                                contexto_extra = f"[Você tentou tocar '{query}', mas não achou NADA no Deezer. Zombe dele por ouvir música esquisita que nem existe.]"
                            else:
                                track = tracks[0]
                                await vc.queue.put_wait(track)
                                
                                if not vc.playing:
                                    await vc.play(vc.queue.get())
                                
                                contexto_extra = f"[Você acabou de colocar a música '{track.title}' na fila. Reclame como essa música é ruim e julgue o gosto musical dele.]"
                        except Exception as e:
                            print(f"[ERRO LAVALINK]: {e}")
                            contexto_extra = "[Ocorreu um erro no servidor de som. Fique irritada com a tecnologia e xingue o bot de música.]"

                    elif action == "skip":
                        if vc and vc.playing:
                            await vc.skip(force=True)
                            contexto_extra = "[Você pulou a música atual. Reclame que estava insuportável e que ele tem um gosto terrível.]"
                        else:
                            contexto_extra = "[O usuário pediu pra pular música, mas não tem NADA tocando. Chame ele de esquizofrênico.]"

                    elif action == "stop":
                        if vc:
                            await vc.disconnect()
                            contexto_extra = "[Você parou a música, desconectou do canal de voz e disse que finalmente tem paz.]"
                        else:
                            contexto_extra = "[O usuário pediu pra parar a música, mas você nem tava lá. Deboche da cara dele.]"

            resposta = await gerar_resposta(message.author.id, intent_data, contexto_extra)
                
            atualizar_memoria_usuario(message.author.id, texto_limpo, resposta)
            salvar_memoria()
            
            await message.reply(resposta)

client = EvaBot()
client.run(DISCORD_TOKEN)
