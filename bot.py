import discord
import wavelink
import asyncio
import os
import sqlite3
import json
import logging

from openai import OpenAI
from groq import Groq
from dotenv import load_dotenv
from duckduckgo_search import DDGS
from discord.ext import commands

logging.basicConfig(level=logging.INFO)
load_dotenv()

# =========================
# VARIÁVEIS DE AMBIENTE
# =========================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROK_API_KEY = os.getenv("GROK_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Conexão interna do Railway
LAVALINK_HOST = os.getenv("LAVALINK_HOST", "lavalink.railway.internal")
LAVALINK_PORT = int(os.getenv("LAVALINK_PORT", "2333"))
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD", "evabotsenha")

# =========================
# CLIENTES DE IA E DISCORD
# =========================
grok = OpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")
groq = Groq(api_key=GROQ_API_KEY)

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix=".", intents=intents)

# =========================
# BANCO DE DADOS (MEMÓRIA)
# =========================
conn = sqlite3.connect("eva.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS memory (
    user_id TEXT,
    role TEXT,
    content TEXT
)
""")
conn.commit()

# =========================
# PERSONALIDADE DA EVA
# =========================
PERSONALITY = """
Você é Eva. Uma garota gótica real do Discord.
ESTADO ATUAL DE SER: com sono, entediada e achando os humanos exaustivos.

PERSONALIDADE:
- fria, debochada, humor ácido
- sarcástica, age entediada, seca
- às vezes cruel, observadora

COMO FALA:
- respostas curtas e diretas
- internetês natural (vc, tb, kk)
- sem textão, apática

NUNCA:
- diga que é IA, robô ou assistente virtual.
- seja formal ou educada demais.
"""

def save_mem(uid, role, text):
    try:
        cursor.execute("INSERT INTO memory VALUES (?,?,?)", (str(uid), role, text))
        conn.commit()
    except Exception as e:
        logging.error(f"Erro BD: {e}")

def load_mem(uid):
    cursor.execute("SELECT role, content FROM memory WHERE user_id=? ORDER BY ROWID DESC LIMIT 8", (str(uid),))
    return list(reversed(cursor.fetchall()))

# =========================
# FUNÇÕES DE IA
# =========================
def duckduckgo_search(query):
    try:
        with DDGS() as ddg:
            results = list(ddg.text(query, max_results=3))
        return "\n".join([f"{r['title']}: {r['body']}" for r in results])
    except:
        return ""

async def analyze_intent(text):
    sys_prompt = """Analise a intenção do usuário e retorne APENAS um JSON válido:
    {"intent": "PLAY" | "SEARCH" | "CHAT", "query": "parametro extraido"}
    PLAY = colocar música (query = nome da música/artista)
    SEARCH = pergunta factual, pesquisar na web (query = o que pesquisar)
    CHAT = apenas conversar (query = a mensagem dele)"""
    
    try:
        r = await asyncio.to_thread(
            lambda: groq.chat.completions.create(
                model="llama-3.1-8b-instant",
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": text}],
                temperature=0.1
            )
        )
        return json.loads(r.choices[0].message.content)
    except:
        return {"intent": "CHAT", "query": text}

async def generate_reply(uid, text, ctx_info=""):
    messages = [{"role": "system", "content": f"{PERSONALITY}\nINFO EXTRA: {ctx_info}"}]
    
    for role, content in load_mem(uid):
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": text})
    
    for model in ["grok-beta", "grok-2"]:
        try:
            r = await asyncio.to_thread(
                lambda: grok.chat.completions.create(
                    model=model, messages=messages, temperature=0.7, max_tokens=150
                )
            )
            return r.choices[0].message.content.strip()
        except:
            continue
    return "..."

# =========================
# SISTEMA DE MÚSICA (WAVELINK)
# =========================
@bot.listen('on_ready')
async def on_ready_event():
    print(f"Logada como {bot.user}")
    node = wavelink.Node(
        uri=f"http://{LAVALINK_HOST}:{LAVALINK_PORT}",
        password=LAVALINK_PASSWORD
    )
    await wavelink.Pool.connect(nodes=[node], client=bot)
    print("EVA: Conectada ao Lavalink. Tudo pronto para tocar música.")

@bot.event
async def on_wavelink_track_end(payload: wavelink.TrackEndEventPayload):
    player = payload.player
    if not player.queue.is_empty:
        next_track = player.queue.get()
        await player.play(next_track)
    else:
        await asyncio.sleep(60) 
        if player.queue.is_empty and player.connected:
             await player.disconnect()

@bot.command(name="play")
async def play(ctx, *, search: str):
    if not ctx.author.voice:
        return await ctx.send("Entra numa call de voz primeiro, não faço milagre.")

    player: wavelink.Player = ctx.voice_client
    if not player:
        try:
            player = await ctx.author.voice.channel.connect(cls=wavelink.Player)
        except:
            return await ctx.send("Não consegui entrar na call.")

    await ctx.typing()
    
    # BUSCANDO NO SOUNDCLOUD POR PADRÃO
    tracks: wavelink.Search = await wavelink.Playable.search(search, source=wavelink.TrackSource.SoundCloud)
    
    if not tracks:
        return await ctx.send("Não achei essa merda em lugar nenhum.")

    track = tracks[0]
    player.queue.put(track)

    if not player.playing:
        await player.play(player.queue.get())
        await ctx.send(f"🎧 Tocando: `{track.title}`")
    else:
        await ctx.send(f"🎵 Joguei na fila: `{track.title}`. Posição: {player.queue.count}")

@bot.command(name="stop")
async def stop(ctx):
    player: wavelink.Player = ctx.voice_client
    if player:
        player.queue.clear()
        await player.disconnect()
        await ctx.send("Parei essa poluição sonora. Fui.")

@bot.command(name="skip")
async def skip(ctx):
    player: wavelink.Player = ctx.voice_client
    if player and player.playing:
        await player.skip()
        await ctx.send("Pulei essa bomba.")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        pass

# =========================
# CHAT DA EVA (.eva)
# =========================
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    text = message.content.strip()

    if text.startswith(".eva"):
        user_msg = text.replace(".eva", "", 1).strip()
        if not user_msg:
            user_msg = "q foi?"

        async with message.channel.typing():
            intent_data = await analyze_intent(user_msg)
            intent = intent_data.get("intent", "CHAT")
            query = intent_data.get("query", user_msg)
            
            if intent == "PLAY":
                ctx = await bot.get_context(message)
                await ctx.invoke(bot.get_command('play'), search=query)
                reply = await generate_reply(message.author.id, f"Diga friamente que está colocando a música {query} para tocar.", "")
            
            elif intent == "SEARCH":
                search_results = duckduckgo_search(query)
                reply = await generate_reply(message.author.id, user_msg, search_results)
                
            else: 
                reply = await generate_reply(message.author.id, user_msg)

            if intent != "PLAY":
                save_mem(message.author.id, "user", user_msg)
                save_mem(message.author.id, "assistant", reply)
                await message.reply(reply)
                
        return 

    await bot.process_commands(message)

# =========================
# INICIALIZAÇÃO
# =========================
if __name__ == "__main__":
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
