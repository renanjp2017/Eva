import discord, re, random, asyncio, logging
from discord.ext import commands

logger = logging.getLogger(__name__)

GATILHOS = [
    (re.compile(r"\bterminei\b|\bme separei\b|\bfui largad[oa]\b"),          "alguém acabou de terminar um relacionamento"),
    (re.compile(r"\btransei\b|\btrepei\b|\bdei uma trepada\b"),               "alguém admitiu que transou"),
    (re.compile(r"\bestou com tesão\b|\btô com tesão\b|\bto com tesão\b"),    "alguém tá com tesão"),
    (re.compile(r"\btô bêbad[oa]\b|\bto bebado\b|\bto bebada\b"),             "alguém tá bêbado"),
    (re.compile(r"\bmandei nudes\b|\breceb[ie] nudes\b"),                     "alguém mandou ou recebeu nudes"),
    (re.compile(r"\bficamos\b|\bfiquei com\b"),                               "alguém ficou com alguém"),
    (re.compile(r"\btô sozinho\b|\bto sozinha\b|\bto sozinho\b"),             "alguém tá sozinho e carente"),
    (re.compile(r"\bme arrependi\b|\bfiz uma besteira\b"),                    "alguém se arrependeu de algo"),
    (re.compile(r"\btô de ressaca\b|\bressacad[oa]\b"),                       "alguém tá de ressaca"),
    (re.compile(r"\bque tédio\b|\bque saudade\b|\bque raiva\b"),              "alguém expressou emoção forte"),
]

REACOES = ["😈","👀","💦","🔥","😏","💅","👅","💋","🫠","😶"]


class Conversa(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot: return
        tl         = message.content.lower()
        mencionada = self.bot.user in message.mentions
        nome_citado = bool(re.search(r'\bcamy\b', tl))

        if mencionada or nome_citado:
            await self._responder(message)
            return

        task = asyncio.create_task(self._gatilho(message))
        self.bot.background_tasks.add(task)
        task.add_done_callback(self.bot.background_tasks.discard)

    async def _responder(self, message: discord.Message):
        uid     = str(message.author.id)
        cid     = str(message.channel.id)
        display = message.author.display_name
        texto   = re.sub(r'<@!?\d+>', '', message.content).strip()

        p = self.bot.get_cog("Personalidade")
        m = self.bot.get_cog("Memoria")
        if not p: return

        async with message.channel.typing():
            await asyncio.sleep(random.uniform(0.3, 0.9))
            try:
                resp = await p.gerar(uid, texto)
                await message.reply(resp, mention_author=False)
                if m: await m.atualizar(uid, texto, resp, display, cid)
            except Exception as e:
                logger.error(f"[CONVERSA ERR]: {e}")
                try:
                    await message.reply(random.choice(["hm 😏","ai bb","...😈"]), mention_author=False)
                except Exception: pass

    async def _gatilho(self, message: discord.Message):
        tl = message.content.lower()
        for padrao, contexto in GATILHOS:
            if not padrao.search(tl): continue

            if self.bot.redis:
                try:
                    ok = await self.bot.redis.set(f"camy:gatilho:{message.id}", 1, nx=True, ex=30)
                    if not ok: return
                except Exception: pass

            if random.random() > 0.30: return  # 70% ignora

            if random.random() < 0.35:
                try: await message.add_reaction(random.choice(REACOES))
                except Exception: pass
                return

            p = self.bot.get_cog("Personalidade")
            if not p: return
            prompt = (
                f"Você é Camy, mega safada e sem filtro.\n"
                f"Contexto: {contexto}. Quem disse isso foi {message.author.display_name}.\n"
                "Reaja sem ser chamada. Pode dar em cima, provocar, zoar ou fazer comentário safado. "
                "1-2 linhas. Não comece com o nome da pessoa."
            )
            try:
                resp = await p.gerar_raw(prompt)
                await message.reply(resp, mention_author=False)
            except Exception as e:
                logger.warning(f"[GATILHO ERR]: {e}")
            return


async def setup(bot):
    await bot.add_cog(Conversa(bot))
