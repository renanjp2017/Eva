"""
truco_bot.py — Entry point do bot Cassino (Wonderland/Mad Hatter).
Carrega todos os cogs e conecta ao Postgres (Railway).
"""
import asyncio
import os
import traceback
import discord
from discord.ext import commands

try:
    import asyncpg
    HAS_PG = True
except ImportError:
    HAS_PG = False

TOKEN = os.environ.get("DISCORD_TOKEN", "")

# Railway usa "postgres://" mas asyncpg exige "postgresql://"
_raw_db_url = os.environ.get("DATABASE_URL", "")
DATABASE_URL = _raw_db_url.replace("postgres://", "postgresql://", 1) if _raw_db_url else ""

# ID do seu servidor Discord (para sync instantâneo de slash commands)
# Coloque o ID do servidor na variável de ambiente GUILD_ID no Railway
# Para pegar o ID: Discord > Configurações > Modo Desenvolvedor ligado > clique direito no servidor > Copiar ID
_guild_id = os.environ.get("GUILD_ID", "")
TEST_GUILD = discord.Object(id=int(_guild_id)) if _guild_id else None

COGS = [
    "cogs.base",
    "cogs.truco",
    "cogs.blackjack",
    "cogs.poker",
    "cogs.cassino",
    "cogs.uno",
    "cogs.domino",
    "cogs.xadrez",
]

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"[boot] {bot.user} online!")

    if TEST_GUILD:
        # Sync instantâneo no servidor específico (uso durante desenvolvimento)
        bot.tree.copy_global_to(guild=TEST_GUILD)
        synced = await bot.tree.sync(guild=TEST_GUILD)
        print(f"✅ {len(synced)} slash commands sincronizados no servidor (instantâneo).")
    else:
        # Sync global — leva até 1h para propagar (use em produção final)
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} slash commands sincronizados globalmente.")


async def main():
    async with bot:
        # 1. Banco de dados
        if HAS_PG and DATABASE_URL:
            import cogs.base as base
            try:
                base.db_pool = await asyncpg.create_pool(
                    DATABASE_URL,
                    min_size=1,
                    max_size=5,
                    command_timeout=30,
                )
                await base.init_db()
                await base.carregar_fichas()
                print("[DB] Postgres conectado e fichas carregadas.")
            except Exception as e:
                print(f"[DB] Falha na conexão: {e}")
                traceback.print_exc()
        else:
            if not DATABASE_URL:
                print("[DB] ⚠️  DATABASE_URL não definida — fichas só em RAM (sem persistência).")

        # 2. Cogs
        print("[boot] Carregando cogs...")
        for cog in COGS:
            try:
                await bot.load_extension(cog)
                print(f"✅ Cog carregado: {cog}")
            except Exception as e:
                print(f"❌ Erro ao carregar {cog}: {e}")
                traceback.print_exc()

        # 3. Start
        await bot.start(TOKEN)


if __name__ == "__main__":
    if not TOKEN:
        print("[ERRO CRÍTICO] DISCORD_TOKEN não definido!")
        exit(1)
    asyncio.run(main())
