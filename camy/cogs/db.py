import asyncio, json, os, logging
import asyncpg
import redis.asyncio as redis
from discord.ext import commands

logger = logging.getLogger(__name__)

_raw = os.getenv("DATABASE_URL", "")
DATABASE_URL = _raw.replace("postgres://", "postgresql://", 1) if _raw else ""
REDIS_URL    = os.getenv("REDIS_URL", "")


class DB(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.db    = None
        bot.redis = None
        bot._ram  = {}
        asyncio.create_task(self._init())

    async def _init(self):
        try:
            self.bot.db = await asyncpg.create_pool(
                DATABASE_URL, min_size=1, max_size=10,
                command_timeout=30, max_inactive_connection_lifetime=300,
            )
            async with self.bot.db.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS usuarios (
                        user_id          TEXT PRIMARY KEY,
                        nome             TEXT,
                        fatos            JSONB DEFAULT '[]',
                        resumos          JSONB DEFAULT '[]',
                        total_msgs       INTEGER DEFAULT 0,
                        ultima_interacao TIMESTAMPTZ,
                        ultimo_canal     TEXT
                    )
                """)
            logger.info("[DB] PostgreSQL conectado.")
        except Exception as e:
            logger.error(f"[DB ERR]: {e}")

        if REDIS_URL:
            try:
                self.bot.redis = redis.from_url(
                    REDIS_URL, decode_responses=True,
                    socket_connect_timeout=2, socket_timeout=2,
                    retry_on_timeout=True, health_check_interval=30,
                )
                await self.bot.redis.ping()
                logger.info("[DB] Redis conectado.")
            except Exception as e:
                logger.warning(f"[REDIS ERR]: {e}")


async def setup(bot):
    await bot.add_cog(DB(bot))
