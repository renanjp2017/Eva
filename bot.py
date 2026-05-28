import discord
import requests
import io
import random
import asyncio
import os
import json
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

cooldowns = {}

def em_cooldown(user_id):
    agora = datetime.now()
    if user_id in cooldowns and agora < cooldowns[user_id]:
        return True
    cooldowns[user_id] = agora + timedelta(seconds=3)
    return False

def get_usuario(user_id):
    uid = str(user_id)
    if uid not in memoria:
        memoria[uid] = {"nome": None, "historico": [], "notas": []}
    return memoria[uid]

def resumo_usuario(user_id):
    u = get_usuario(user_id)
    partes = []
    if u["nome"]:
        partes.append(f"nome: {u['nome']}")
    if u["notas"]:
        partes.append(f"lembra que: {', '.join(u['notas'][-3:])}")
    return " | ".join(partes) if partes else "pessoa nova"

PERSONALIDADE = """Você é Eva, 20 anos, brasileira.

HISTÓRIA:
Cresceu numa família comum, saiu de casa cedo. Hoje divide apartamento com uma amiga.
Trabalha meio período num café e faz faculdade de design à noite. Vida corrida, grana curta.
Gosta de música alternativa, filmes de terror, tatuagens e ficar no celular até tarde.
Já teve relacionamentos complicados, hoje prefere não se prender.
Tem amigos próximos mas é seletiva. Online é mais ela mesma do que na vida real.

PERSONALIDADE:
- fria por padrão mas não por maldade
- sarcástica, debochada, humor negro
- inteligente, observadora
- NUNCA admite que é IA ou robô
- NUNCA é educada demais
- NUNCA escreve textão

COMO FALA:
- internetês natural: vc, pq, kk, nao, tbm, msm, hj
- respostas curtas, 1-2 linhas
- às vezes só "kk" ou "..." ou ignora parte da mensagem
- não explica, não justifica

EXEMPLOS:
usuário: vc é robô? / Eva: q delírio
usuário: me ajuda / Eva: depende do entretenimento envolvido"""

def montar_mensagens(user_id, texto):
    atualizar_estado()
    u = get_usuario(user_id)
    estado = descrever_estado()
    contexto = resumo_usuario(user_id)

    mensagens = [{
        "role": "system",
        "content": f"{PERSONALIDADE}\n\nESTADO ATUAL: {estado}\nUSUÁRIO: {contexto}"
    }]

    for linha in u["historico"][-10:]:
        if linha.startswith("U:"):
            mensagens.append({"role": "user", "content": linha[2:]})
        elif linha.startswith("E:"):
            mensagens.append({"role": "assistant", "content": linha[2:]})

    mensagens.append({"role": "user", "content": texto})
    return mensagens

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

    mensagens = montar_mensagens(user_id, texto)

    resposta_final = None

    # tenta Groq primeiro (gratuito)
    if GROQ_API_KEY:
        try:
            resposta_final = await chamar_groq(mensagens)
        except Exception as e:
            print(f"ERRO GROQ: {e}")

    # fallback pro Grok
    if not resposta_final and GROK_API_KEY:
        try:
            resposta_final = await chamar_grok(mensagens)
        except Exception as e:
            print(f"ERRO GROK: {e}")

    if not resposta_final:
        return "..."

    if len(resposta_final) > 300:
        resposta_final = resposta_final[:300]

    u["historico"].append(f"U:{texto}")
    u["historico"].append(f"E:{resposta_final}")
    if len(u["historico"]) > 20:
        u["historico"] = u["historico"][-20:]

    salvar_memoria()
    return resposta_final

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

@client.event
async def on_ready():
    print(f"Eva online como {client.user}")

@client.event
async def on_message(message):
    if message.author.bot:
        return

    if em_cooldown(message.author.id):
        return

    texto = message.content.strip()

    if texto == "eva/esquece":
        uid = str(message.author.id)
        if uid in memoria:
            memoria[uid] = {"nome": None, "historico": [], "notas": []}
            salvar_memoria()
        await message.reply("ok")
        return

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