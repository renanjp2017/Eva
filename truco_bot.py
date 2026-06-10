"""
truco_bot.py — Entry point do bot.
Carrega todos os cogs e conecta ao Postgres.
"""
import discord
from discord.ext import commands
import asyncio
import os

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
    # Conecta ao Postgres e carrega fichas
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
            print(f"[DB] Falha: {e}")

    await bot.tree.sync()
    print(f"✅ {bot.user} online! Comandos sincronizados.")


async def main():
    async with bot:
        for cog in COGS:
            try:
                await bot.load_extension(cog)
                print(f"✅ Cog carregado: {cog}")
            except Exception as e:
                print(f"❌ Erro ao carregar {cog}: {e}")
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
