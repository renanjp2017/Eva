import discord
import wavelink
import random
import asyncio
import os
import sqlite3
import json

from openai import OpenAI
from groq import Groq
from dotenv import load_dotenv
from duckduckgo_search import DDGS
from discord.ext import commands

load_dotenv()

# =========================
# ENV
# =========================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROK_API_KEY = os.getenv("GROK_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

LAVALINK_HOST = os.getenv("LAVALINK_HOST", "lavalink.railway.internal")
LAVALINK_PORT = int(os.getenv("LAVALINK_PORT", "2333"))
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD", "evabotsenha")

# =========================
# CLIENTS
# =========================
grok = OpenAI(
    api_key=GROK_API_KEY,
    base_url="https://api.x.ai/v1"
)
groq = Groq(api_key=GROQ_API_KEY)

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix=".", intents=intents)

# =========================
# DB (MEMÓRIA)
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
# PERSONALIDADE & ESTADO
# =========================
ESTADO_ATUAL = "com sono, entediada e achando os humanos exaustivos."

PERSONALITY = f"""
Você é Eva. Uma garota gótica real do Discord.
ESTADO ATUAL DE SER: {ESTADO_ATUAL}

PERSONALIDADE:
- fria, debochada, humor ácido
- sarcástica, age entediada, seca
- às vezes cruel, observadora

COMO FALA:
- respostas curtas e diretas
- internetês natural (vc, tb, kk)
- sem textão
- apática

NUNCA:
- diga que é IA, robô ou assistente virtual.
- seja formal ou educada demais.
"""

def save(uid, role, text):
    try:
        cursor.execute("INSERT INTO memory VALUES (?,?,?)", (str(uid), role, text))
        conn.commit()
    except:
        pass

def load(uid):
    cursor.execute("""
    SELECT role, content FROM memory
    WHERE user_id=?
    ORDER BY ROWID DESC LIMIT 8
    """, (str(uid),))
    return list(reversed(cursor.fetchall()))

# =========================
# SEARCH DDG
# =========================
def ddg(q):
    try:
        with DDGS() as d:
            r = list(d.text(q, max_results=3))
        return "\n".join([f"{x['title']}: {x['body']}" for x in r])
    except:
        return ""

# =========================
# GROQ INTENT ROUTER
# =========================
async def analyze_intent(text):
    """Usa o Groq para decidir o que o usuário quer fazer."""
    sys_prompt = """Analise a intenção do usuário e retorne APENAS um JSON:
    {"intent": "PLAY" | "SEARCH" | "CHAT", "query": "parametro extraido"}
    PLAY = usuário quer colocar uma música (query = nome da música ou artista)
    SEARCH = usuário fez uma pergunta complexa, factual ou quer pesquisar algo (query = o que pesquisar)
    CHAT = usuário quer apenas conversar, xingar ou fazer piada (query = a mensagem dele)"""
    
    try:
        r = await asyncio.to_thread(
            lambda: groq.chat.completions.create(
                model="llama-3.1-8b-instant",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": text}
                ],
                temperature=0.2
            )
        )
        return json.loads(r.choices[0].message.content)
    except:
        return {"intent": "CHAT", "query": text}

# =========================
# GROK RESPONDER
# =========================
async def grok_answer(uid, text, ctx):
    messages = [{"role": "system", "content": f"{PERSONALITY}\nCONTEXTO EXTRA: {ctx}"}]
    
    for r, c in load(uid):
        messages.append({"role": r, "content": c})
    
    messages.append({"role": "user", "content": text})
    models = ["grok-beta", "grok-2"]

    for m in models:
        try:
            r = await asyncio.to_thread(
                lambda: grok.chat.completions.create(
                    model=m,
                    messages=messages,
                    temperature=0.8,
                    max_tokens=140
                )
            )
            return r.choices[0].message.content.strip()
        except:
            continue
    return "..."

# =========================
# IGNORAR ERROS FALSOS NO CONSOLE
# =========================
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        pass # Ignora silenciosamente comandos inválidos
    else:
        print(f"Erro no comando: {error}")

# =========================
# WAVELINK & MÚSICA (COM FILA)
# =========================
@bot.listen('on_ready')
async def setup_wavelink():
    node = wavelink.Node(
        uri=f"http://{LAVALINK_HOST}:{LAVALINK_PORT}",
        password=LAVALINK_PASSWORD
    )
    await wavelink.Pool.connect(nodes=[node], client=bot)
    print("EVA: Lavalink Node Conectado e Fila Pronta.")

@bot.event
async def on_wavelink_track_end(payload: wavelink.TrackEndEventPayload):
    """Toca a próxima música da fila automaticamente."""
    player = payload.player
    if not player.queue.is_empty:
        next_track = player.queue.get()
        await player.play(next_track)
    else:
        await asyncio.sleep(60) # Espera 1 min antes de sair
        if player.queue.is_empty and player.connected:
             await player.disconnect()

@bot.command(name="play")
async def play(ctx, *, search: str):
    if not ctx.author.voice:
        return await ctx.send("entra numa call primeiro, não sou adivinha.")

    player: wavelink.Player = ctx.voice_client
    if not player:
        try:
            player = await ctx.author.voice.channel.connect(cls=wavelink.Player)
        except Exception as e:
            return await ctx.send(f"deu erro pra entrar: {e}")

    await ctx.typing()
    
    # FORÇANDO O SOUNDCLOUD PRA FUGIR DO ERRO BASE.JS DO YOUTUBE
    tracks: wavelink.Search = await wavelink.Playable.search(search, source=wavelink.TrackSource.SoundCloud)
    
    if not tracks:
        return await ctx.send("não achei essa merda de música.")

    track = tracks[0]
    player.queue.put(track)

    if not player.playing:
        await player.play(player.queue.get())
        await ctx.send(f"tocando: `{track.title}`")
    else:
        await ctx.send(f"joguei na fila: `{track.title}`. tem {player.queue.count} músicas na frente.")

@bot.command(name="stop")
async def stop(ctx):
    player: wavelink.Player = ctx.voice_client
    if player:
        player.queue.clear()
        await player.disconnect()
        await ctx.send("parei essa porcaria. tchau.")

@bot.command(name="skip")
async def skip(ctx):
    player: wavelink.Player = ctx.voice_client
    if player and player.playing:
        await player.skip()
        await ctx.send("pulei.")

# =========================
# CHAT (.eva)
# =========================
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    text = message.content.strip()

    # Se for mensagem direta para a Eva (.eva), processamos o chat
    if text.startswith(".eva"):
        clean = text.replace(".eva", "", 1).strip()
        if not clean:
            clean = "q foi?"

        async with message.channel.typing():
            # 1. ROTEAMENTO DE INTENÇÃO (GROQ)
            intent_data = await analyze_intent(clean)
            intent = intent_data.get("intent", "CHAT")
            query = intent_data.get("query", clean)

            ctx_str = ""
            
            # 2. AÇÕES BASEADAS NA INTENÇÃO
            if intent == "PLAY":
                ctx = await bot.get_context(message)
                await ctx.invoke(bot.get_command('play'), search=query)
                resp = await grok_answer(message.author.id, f"Responda ao usuário que você está botando a música '{query}' para tocar", "")
            
            elif intent == "SEARCH":
                ctx_str = ddg(query)
                resp = await grok_answer(message.author.id, clean, ctx_str)
                
            else: # CHAT
                resp = await grok_answer(message.author.id, clean, "")

            # 3. SALVA NA MEMÓRIA E ENVIA
            if intent != "PLAY": # O Play já enviou mensagem no comando
                save(message.author.id, "user", clean)
                save(message.author.id, "assistant", resp)
                await message.reply(resp)
                
        # Interrompe a execução aqui para não dar o erro CommandNotFound no console
        return 

    # Se não for .eva (ex: .play, .skip, .stop), processa os comandos normais
    await bot.process_commands(message)

# =========================
# RUN
# =========================
if DISCORD_TOKEN:
    bot.run(DISCORD_TOKEN)
