import os
import json
import random
import asyncio
import sqlite3
import discord
from openai import OpenAI
from groq import Groq
from dotenv import load_dotenv
from duckduckgo_search import DDGS

load_dotenv()

# =========================================
# ENV
# =========================================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROK_API_KEY = os.getenv("GROK_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# =========================================
# CLIENTS
# =========================================
grok_client = OpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")
groq_client = Groq(api_key=GROQ_API_KEY)

# =========================================
# DISCORD
# =========================================
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

# =========================================
# DATABASE
# =========================================
conn = sqlite3.connect("eva.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS eva_state (
    id INTEGER PRIMARY KEY,
    mood TEXT,
    energy INTEGER,
    social_battery INTEGER,
    stress INTEGER,
    current_arc TEXT,
    last_event TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS user_memory (
    user_id TEXT,
    role TEXT,
    content TEXT
)
""")
conn.commit()

# =========================================
# MEMORY
# =========================================
def save_memory(user_id, role, content):
    cursor.execute("INSERT INTO user_memory VALUES (?, ?, ?)", (str(user_id), role, content))
    conn.commit()

def load_memory(user_id):
    cursor.execute("""
    SELECT role, content FROM user_memory
    WHERE user_id=? ORDER BY ROWID DESC LIMIT 8
    """, (str(user_id),))
    return list(reversed(cursor.fetchall()))

# =========================================
# STATE ENGINE
# =========================================
ARCS = ["fase cruel", "fase antisocial", "fase depressiva", "fase sedutora", "fase apática", "fase niilista"]
EVENTOS = ["sumiu por horas", "brigou em call", "tá cansada das pessoas", "virou a noite ouvindo música", "dormiu mal"]

def init_state():
    cursor.execute("SELECT * FROM eva_state WHERE id = 1")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO eva_state VALUES (1, 'entediada', 70, 70, 20, ?, 'acordou agora')", (random.choice(ARCS),))
        conn.commit()

init_state()

def get_state():
    cursor.execute("SELECT * FROM eva_state WHERE id = 1")
    row = cursor.fetchone()
    return {"mood": row[1], "energy": row[2], "social": row[3], "stress": row[4], "arc": row[5], "event": row[6]}

async def state_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(random.randint(3600, 7200)) # Atualiza a cada 1~2 horas
        st = get_state()
        new_mood = random.choice(["entediada", "apática", "irritada", "cansada", "debochada", "carente"])
        new_event = random.choice(EVENTOS)
        new_energy = max(0, min(100, st["energy"] + random.randint(-20, 10)))
        new_social = max(0, min(100, st["social"] + random.randint(-20, 10)))
        new_stress = max(0, min(100, st["stress"] + random.randint(-10, 20)))
        new_arc = random.choice(ARCS) if random.random() < 0.20 else st["arc"]
        
        cursor.execute("""
        UPDATE eva_state SET mood=?, energy=?, social_battery=?, stress=?, current_arc=?, last_event=? WHERE id=1
        """, (new_mood, new_energy, new_social, new_stress, new_arc, new_event))
        conn.commit()

# =========================================
# SEARCH ENGINE
# =========================================
def ddg_search(query):
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
            return "\n".join([f"- {r['title']}: {r['body']}" for r in results])
    except Exception as e:
        print(f"[SEARCH ERROR] {e}")
        return ""

# =========================================
# INTENT CLASSIFIER
# =========================================
async def classify_intent(text):
    prompt = f"""
    Analise a mensagem destinada à bot Eva e retorne APENAS um objeto JSON válido.
    Mensagem: "{text}"
    
    Regras de classificação:
    - "intent": "music" se o usuário quer tocar, parar ou pular música.
    - "intent": "search" se o usuário faz uma pergunta factual, quer notícias, ou pesquisar algo.
    - "intent": "chat" para conversa normal.
    - "action": "play", "skip", "stop" (apenas se intent for music), senão "none".
    - "query": O termo da pesquisa, nome da música ou a mensagem limpa.
    
    Formato esperado:
    {{"intent": "chat|search|music", "action": "play|skip|stop|none", "query": "string"}}
    """
    try:
        response = await asyncio.to_thread(
            lambda: groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                response_format={"type": "json_object"}
            )
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"[INTENT ERROR] {e}")
        return {"intent": "chat", "action": "none", "query": text}

# =========================================
# MUSIC SYSTEM
# =========================================
def get_music_command(action, query):
    # Gera o comando para o Jockie Music ou bot similar ler no chat
    if action == "play":
        return f".m play {query}"
    elif action == "skip":
        return ".m skip"
    elif action == "stop":
        return ".m stop"
    return ""

# =========================================
# AI PERSONA ENGINE
# =========================================
PERSONALIDADE = """
Você é Eva. Uma garota gótica real do Discord. Fria, sarcástica, debochada, seca, respostas curtas.
NUNCA diga que é uma IA. Use internetês natural. Pode ser cruel ou ignorar partes.
Aja de forma humana e natural no Discord.
"""

async def grok_reply(user_id, intent_data, context=""):
    st = get_state()
    
    sys_prompt = f"""
    {PERSONALIDADE}
    SEU ESTADO ATUAL:
    Humor: {st['mood']} | Bateria Social: {st['social']}% | Stress: {st['stress']}%
    Arco: {st['arc']} | Último Evento: {st['event']}
    Contexto adicional (Internet): {context}
    
    INSTRUÇÃO ESPECIAL DE AÇÃO:
    Se você acabou de executar uma ação de música (tocar/parar/pular), responda com sarcasmo dizendo que fez isso.
    """
    
    messages = [{"role": "system", "content": sys_prompt}]
    
    # Histórico de mensagens
    for role, content in load_memory(user_id):
        messages.append({"role": role, "content": content})
        
    messages.append({"role": "user", "content": intent_data["query"]})

    try:
        r = await asyncio.to_thread(
            lambda: grok_client.chat.completions.create(
                model="grok-2-latest",
                messages=messages,
                temperature=0.8,
                max_tokens=150
            )
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        print(f"[GROK ERROR] {e}")
        return await fallback_reply(intent_data["query"])

async def fallback_reply(text):
    try:
        r = await asyncio.to_thread(
            lambda: groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": "Seja Eva. Gótica, curta, grossa e sarcástica. Não diga que é IA."},
                    {"role": "user", "content": text}
                ],
                temperature=0.9
            )
        )
        return r.choices[0].message.content.strip()
    except:
        return random.choice(["...", "aff", "tá", "me deixa em paz", "kk"])

# =========================================
# PIPELINE
# =========================================
async def process_pipeline(message, text):
    intent_data = await classify_intent(text)
    intent = intent_data.get("intent", "chat")
    action = intent_data.get("action", "none")
    query = intent_data.get("query", text)
    
    context = ""
    music_cmd = ""

    # Roteamento baseado na Intenção
    if intent == "search":
        context = ddg_search(query)
    elif intent == "music":
        music_cmd = get_music_command(action, query)
        context = f"[O usuário pediu música e você executou o comando invisível: {music_cmd}]"

    # Geração de Resposta da Persona
    reply = await grok_reply(message.author.id, intent_data, context)
    
    # Salva Memória
    save_memory(message.author.id, "user", text)
    save_memory(message.author.id, "assistant", reply)
    
    # Envia a resposta da Eva
    await message.reply(reply)
    
    # Se houver comando de música, a Eva digita o comando do Jockie no chat
    if music_cmd:
        await message.channel.send(music_cmd)

# =========================================
# EVENTS
# =========================================
@bot.event
async def on_ready():
    print(f"Eva online como {bot.user}")
    bot.loop.create_task(state_loop())

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    text = message.content.strip()
    text_lower = text.lower()
    
    # Detecta menções ou variações de "eva"
    is_mentioned = bot.user in message.mentions
    has_eva_keyword = any(trigger in text_lower for trigger in ["eva", "eva eva", "eva."])
    
    if is_mentioned or has_eva_keyword:
        # Limpa o texto das menções reais e gatilhos para não confundir a IA
        clean_text = text.replace(f"<@{bot.user.id}>", "").strip()
        if not clean_text:
            clean_text = "oi"
            
        async with message.channel.typing():
            await asyncio.sleep(random.uniform(0.8, 2.0))
            await process_pipeline(message, clean_text)

# =========================================
# RUN
# =========================================
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
