"""
truco_bot.py — Entry point do bot Cassino.
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
    await bot.tree.sync()
    print(f"✅ {bot.user} online! Comandos sincronizados.")


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
    asyncio.run(main())
