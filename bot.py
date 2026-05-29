import discord
import io
import re
import random
import asyncio
import os
import sqlite3
import yt_dlp
import google.generativeai as genai
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")
GROK_API_KEY = os.getenv("GROK_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)
gemini = genai.GenerativeModel(model_name="gemini-1.5-flash")

grok = OpenAI(
    api_key=GROK_API_KEY,
    base_url="https://api.x.ai/v1"
)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

memoria = {}

PERSONALIDADE = """
Você é Eva, uma garota gótica real do Discord.

QUEM VOCÊ É:
- fria, sarcástica, debochada
- humor negro e ácido
- inteligente mas preguiçosa
- sedutora de forma passiva — nunca forçada
- imprevisível: às vezes responde com um "kkk" seco, às vezes ignora partes da mensagem
- age entediada mas observa tudo
- NUNCA diz que é IA, robô ou assistente
- NUNCA é educada demais
- NUNCA escreve textão

COMO FALA:
- respostas curtas, máximo 2 linhas
- internetês natural (vc, pq, kk, nao, tbm, etc)
- pode responder só com "kk" ou "..." ou ignorar
- sem emoji excessivo, no máximo um ocasional
- sem explicações desnecessárias

EXEMPLOS:
usuário: oi
Eva: hm

usuário: vc é má
Eva: perceptivo da sua parte

usuário: me ajuda
Eva: depende do entretenimento envolvido

usuário: você é estranha
Eva: e vc continua falando comigo
"""

def mood_atual():
    return random.choice([
        "entediada",
        "irritada",
        "com sono",
        "debochada",
        "mexendo no celular",
        "ignorando todo mundo",
        "com dor de cabeça"
    ])

async def gerar_com_grok(historico, texto):
    mensagens = [{"role": "system", "content": PERSONALIDADE + f"\n\nEstado atual: {mood_atual()}"}]

    for linha in historico[-8:]:
        if linha.startswith("Usuário:"):
            mensagens.append({"role": "user", "content": linha.replace("Usuário: ", "")})
        elif linha.startswith("Eva:"):
            mensagens.append({"role": "assistant", "content": linha.replace("Eva: ", "")})

    mensagens.append({"role": "user", "content": texto})

    resposta = await asyncio.to_thread(
        lambda: grok.chat.completions.create(
            model="grok-2-latest",
            messages=mensagens,
            max_tokens=150,
            temperature=0.9
        )
    )

    return resposta.choices[0].message.content.strip()

async def gerar_com_gemini(historico, texto):
    contexto = "\n".join(historico[-6:])
    prompt = f"""{PERSONALIDADE}

Estado atual: {mood_atual()}

Histórico:
{contexto}

Usuário: {texto}
Eva:"""

    resposta = await asyncio.to_thread(
        lambda: gemini.generate_content(prompt)
    )
    return resposta.text.strip()

async def gerar_texto(user_id, texto):
    if user_id not in memoria:
        memoria[user_id] = []

    historico = memoria[user_id]

    # Grok gera a resposta principal
    # Gemini refina se a resposta for longa ou sair do personagem
    try:
        resposta_grok = await gerar_com_grok(historico, texto)

        # se sair do personagem ou for longa demais, Gemini corrige
        if len(resposta_grok) > 250 or "como posso ajudar" in resposta_grok.lower():
            resposta_final = await gerar_com_gemini(historico, texto)
        else:
            resposta_final = resposta_grok

    except Exception as e:
        print(f"ERRO GROK: {e}")
        try:
            resposta_final = await gerar_com_gemini(historico, texto)
        except Exception as e2:
            print(f"ERRO GEMINI: {e2}")
            return "..."

    if len(resposta_final) > 300:
        resposta_final = resposta_final[:300]

    memoria[user_id].append(f"Usuário: {texto}")
    memoria[user_id].append(f"Eva: {resposta_final}")

    # mantém só as últimas 20 linhas
    if len(memoria[user_id]) > 20:
        memoria[user_id] = memoria[user_id][-20:]

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
            "voice_settings": {
                "stability": 0.45,
                "similarity_boost": 0.8
            }
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

    texto = message.content.strip()

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

    if texto_limpo == "":
        texto_limpo = "oi"

    async with message.channel.typing():
        await asyncio.sleep(random.uniform(0.8, 2))

        resposta = await gerar_texto(message.author.id, texto_limpo)

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