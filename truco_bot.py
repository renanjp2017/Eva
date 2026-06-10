"""
truco_bot.py — Entry point do bot.
Carrega todos os cogs e conecta ao Postgres.
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

TOKEN        = os.environ.get("DISCORD_TOKEN", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

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
    # Sincronização dos comandos de barra (Slash Commands)
    await bot.tree.sync()
    print(f"✅ {bot.user} online! Comandos sincronizados.")


async def main():
    async with bot:
        # 1. Inicialização segura do banco de dados antes de carregar os cogs
        if HAS_PG and DATABASE_URL:
            import cogs.base as base
            try:
                base.db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
                async with base.db_pool.acquire() as conn:
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS cassino_fichas (
                            user_id TEXT PRIMARY KEY,
                            fichas  INTEGER NOT NULL DEFAULT 500
                        )
                    """)
                await base.carregar_fichas()
                print("[DB] Postgres conectado e fichas carregadas.")
            except Exception as e:
                print(f"[DB] Falha na conexão com o banco de dados: {e}")
                traceback.print_exc()

        # 2. Carregamento das extensões (Cogs)
        print("[boot] Carregando cogs...")
        for cog in COGS:
            try:
                await bot.load_extension(cog)
                print(f"✅ Cog carregado: {cog}")
            except Exception as e:
                print(f"❌ Erro ao carregar {cog}: {e}")
                traceback.print_exc()

        # 3. Inicialização do bot
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
