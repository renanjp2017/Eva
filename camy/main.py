"""
main.py — Camy Bot +18
Variáveis: DISCORD_TOKEN, GEMINI_API_KEY, GROQ_API_KEY, DATABASE_URL, REDIS_URL
"""
import asyncio, os, logging, signal, random
import discord
from discord.ext import commands
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}')
logger = logging.getLogger(__name__)
load_dotenv()

COGS = [
    "cogs.db",
    "cogs.memoria",
    "cogs.personalidade",
    "cogs.eunca",
    "cogs.vod",
    "cogs.mestre",
    "cogs.conversa",
]

background_tasks: set[asyncio.Task] = set()


class Camy(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.background_tasks = background_tasks

    async def setup_hook(self):
        for cog in COGS:
            try:
                await self.load_extension(cog)
                logger.info(f"[COG] ✓ {cog}")
            except Exception as e:
                logger.error(f"[COG] ✗ {cog}: {e}")
        await self.tree.sync()
        logger.info("[CAMY] Slash commands sincronizados.")
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.close()))
            except NotImplementedError:
                pass

    async def on_ready(self):
        logger.info(f"[CAMY] Online: {self.user} (id={self.user.id})")
        await self.change_presence(
            activity=discord.CustomActivity(name="te deixando sem graça desde 2024 😈")
        )

    async def close(self):
        for task in list(background_tasks):
            task.cancel()
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)
        await super().close()


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.error("DISCORD_TOKEN não definido!")
        exit(1)
    Camy().run(token, log_handler=None)
