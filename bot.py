import discord
import requests
import random
import asyncio
import os
import json
import re
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

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# =========================================
# MEMÓRIA RICA (JSON)
# =========================================
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
# SISTEMA TAMAGOTCHI (ESTADO/HUMOR)
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
    - "intent": "music" se o usuário quer tocar, parar ou pular música (ex: play, music, m!play, m!skip).
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
                model="grok-4.3",
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
# EVENTOS DO DISCORD
# =========================================
@client.event
async def on_ready():
    print(f"🔥 Eva online como {client.user}")

@client.event
async def on_message(message):
    if message.author.bot:
        return

    texto = message.content.strip()
    texto_lower = texto.lower()
    
    # ── GATILHOS DE ATIVAÇÃO NATURAL ──
    is_mentioned = client.user in message.mentions
    has_name = bool(re.search(r'\beva\b', texto_lower))
    # Ajustado para pegar "m!", ".skip", etc.
    is_music = texto_lower.startswith(("play ", "music ", "m!", ".skip", ".stop", ".play"))
    
    if not (is_mentioned or has_name or is_music):
        return

    u = get_usuario(message.author.id)
    if not u["nome"]: u["nome"] = message.author.display_name

    texto_limpo = texto.replace(f"<@{client.user.id}>", "").strip()

    async with message.channel.typing():
        await asyncio.sleep(random.uniform(0.8, 1.5))
        
        # 1. Roteador
        intent_data = await classificar_intencao(texto_limpo)
        intent = intent_data.get("intent", "chat")
        action = intent_data.get("action", "none")
        query = intent_data.get("query", texto_limpo)
        
        contexto_extra = ""
        comando_jockie = ""

        # 2. Direcionamento Invisível
        if intent == "search":
            busca = buscar_duckduckgo(query)
            if busca: contexto_extra = f"Resultado do DuckDuckGo: {busca}"
            
        elif intent == "music":
            # Aqui configuramos o comando com o prefixo exato do Jockie
            if action == "play":
                comando_jockie = f"m!play {query}"
                contexto_extra = f"[O usuário pediu pra tocar '{query}'. Vc já deu o play, tire sarro do gosto dele.]"
            elif action == "skip":
                comando_jockie = "m!skip"
                contexto_extra = "[Você acabou de pular a música, diga algo sobre como estava insuportável.]"
            elif action == "stop":
                comando_jockie = "m!stop"
                contexto_extra = "[Você parou a música, diga que não aguentava mais.]"

        # 3. Geração da Mensagem da Persona
        resposta = await gerar_resposta(message.author.id, intent_data, contexto_extra)
        
        # 4. TRUQUE MÁGICO: Envia o comando e apaga em 0.5 segundos
        if comando_jockie:
            try:
                msg_comando = await message.channel.send(comando_jockie)
                await asyncio.sleep(0.5) # O tempo exato pro Jockie ler antes de sumir
                await msg_comando.delete()
            except Exception as e:
                print(f"[ERRO AO APAGAR COMANDO]: {e}")
            
        # 5. Salva memórias
        atualizar_memoria_usuario(message.author.id, texto_limpo, resposta)
        salvar_memoria()
        
        # 6. Responde ao usuário com a mensagem real
        await message.reply(resposta)

client.run(DISCORD_TOKEN)
