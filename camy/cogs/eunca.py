"""
cogs/eunca.py — Eu Nunca +18
/eunca iniciar → abre sessão
Camy comenta cada rodada e dá em cima
"""
import discord, random, asyncio
from discord import app_commands
from discord.ext import commands

PERGUNTAS_EU_NUNCA = [
    # Leves
    "eu nunca mandei foto nua pra alguém que não devia.",
    "eu nunca fingi que não vi a mensagem de alguém porque não queria responder.",
    "eu nunca fiz algo que envergonharia minha família se eles soubessem.",
    "eu nunca briguei com alguém por ciúme sem ter razão.",
    "eu nunca fiquei com a ex/o ex de um amigo(a).",
    "eu nunca menti sobre minha experiência sexual.",
    "eu nunca apaguei mensagem depois de mandar sem querer.",
    "eu nunca acordei na casa de alguém sem lembrar como cheguei.",
    "eu nunca me arrependeu de fazer algo na festa no dia seguinte.",
    "eu nunca transei pensando em outra pessoa.",
    # Médias
    "eu nunca mandei nudes sem pedir.",
    "eu nunca flertei com mais de uma pessoa ao mesmo tempo sabendo das duas.",
    "eu nunca usei álcool como desculpa pra fazer algo que queria há muito tempo.",
    "eu nunca fui apagado(a) numa festa e fiz algo que não contaria pra ninguém.",
    "eu nunca tive tesão por alguém do relacionamento de outra pessoa.",
    "eu nunca fingi gostar mais do que gostava só pelo sexo.",
    "eu nunca fiz sexo em lugar público.",
    "eu nunca mandei mensagem pra ex/o ex bêbado(a).",
    "eu nunca fiz algo safado numa ligação de vídeo.",
    "eu nunca fiquei com mais de uma pessoa num mesmo dia.",
    # Pesadas
    "eu nunca participei de algo em grupo que nunca contei pra ninguém.",
    "eu nunca fiz striptease pra alguém.",
    "eu nunca gravei algo que não deveria ter gravado.",
    "eu nunca mandei print de conversa íntima pra outra pessoa.",
    "eu nunca usei fantasia ou roleplay.",
    "eu nunca tive tara por alguém muito mais velho(a) ou mais novo(a).",
    "eu nunca transei na primeira vez que saí com alguém.",
    "eu nunca fiz algo que consideraria traição se fizessem comigo.",
    "eu nunca me arrependi de transar com alguém — mas devia.",
    "eu nunca enviei ou recebi algo comprometedor que ainda existe em algum lugar.",
]

COMENTARIOS_CAMY = [
    "mentira que não bebi nessa 😈",
    "alguém tá vermelho aí né",
    "ui, quem bebeu tá na merda kkk",
    "eu sabia que tinha alguém safado(a) aqui 👀",
    "bebe, covarde 💦",
    "interessante... conta mais bb",
    "tô julgando? nunca. tô anotando? sempre 😏",
    "quem não bebeu tá mentindo",
    "ai que delícia de confissão",
    "essa foi pesada... e eu amei 🔥",
    "alguém aqui tem histórias que eu PRECISO ouvir",
    "vocês são um desastre e eu amo isso",
]


class EuncaSession:
    def __init__(self, channel_id: int, jogadores: list):
        self.channel_id = channel_id
        self.jogadores  = jogadores
        self.perguntas  = random.sample(PERGUNTAS_EU_NUNCA, min(len(PERGUNTAS_EU_NUNCA), 20))
        self.idx        = 0
        self.pontos     = {str(j.id): 0 for j in jogadores}  # bebidas por jogador
        self.ativa      = True


sessoes: dict[int, EuncaSession] = {}


class EuncaView(discord.ui.View):
    def __init__(self, cog, session: EuncaSession):
        super().__init__(timeout=300)
        self.cog     = cog
        self.session = session
        self.beberam: set[int] = set()

    @discord.ui.button(label="🍺 Bebi!", style=discord.ButtonStyle.danger, custom_id="eunca_bebi")
    async def bebi(self, interaction: discord.Interaction, btn):
        if interaction.user not in self.session.jogadores:
            return await interaction.response.send_message("Você não está nessa sessão.", ephemeral=True)
        uid = interaction.user.id
        if uid in self.beberam:
            return await interaction.response.send_message("Já marcou!", ephemeral=True)
        self.beberam.add(uid)
        self.session.pontos[str(uid)] = self.session.pontos.get(str(uid), 0) + 1
        await interaction.response.send_message(
            f"🍺 **{interaction.user.display_name}** bebeu!", ephemeral=False
        )

    @discord.ui.button(label="➡️ Próxima", style=discord.ButtonStyle.primary, custom_id="eunca_next")
    async def proxima(self, interaction: discord.Interaction, btn):
        if interaction.user not in self.session.jogadores:
            return await interaction.response.send_message("Você não está nessa sessão.", ephemeral=True)
        await interaction.response.defer()
        self.beberam.clear()
        self.session.idx += 1
        await self.cog.enviar_rodada(interaction.channel, self.session)

    @discord.ui.button(label="🚫 Encerrar", style=discord.ButtonStyle.grey, custom_id="eunca_end")
    async def encerrar(self, interaction: discord.Interaction, btn):
        if interaction.user not in self.session.jogadores:
            return await interaction.response.send_message("Você não está nessa sessão.", ephemeral=True)
        await interaction.response.defer()
        self.session.ativa = False
        sessoes.pop(self.session.channel_id, None)
        self.stop()
        await self.cog.encerrar_sessao(interaction.channel, self.session)


class EuncaEntrarView(discord.ui.View):
    def __init__(self, cog, criador: discord.Member, channel_id: int):
        super().__init__(timeout=120)
        self.cog        = cog
        self.criador    = criador
        self.channel_id = channel_id
        self.jogadores  = [criador]

    @discord.ui.button(label="✋ Entrar", style=discord.ButtonStyle.success)
    async def entrar(self, interaction: discord.Interaction, btn):
        if interaction.user in self.jogadores:
            return await interaction.response.send_message("Você já entrou!", ephemeral=True)
        self.jogadores.append(interaction.user)
        await interaction.response.send_message(
            f"✅ **{interaction.user.display_name}** entrou! ({len(self.jogadores)} jogadores)", ephemeral=False
        )

    @discord.ui.button(label="▶️ Iniciar", style=discord.ButtonStyle.primary)
    async def iniciar(self, interaction: discord.Interaction, btn):
        if interaction.user != self.criador:
            return await interaction.response.send_message("Só quem criou pode iniciar.", ephemeral=True)
        if len(self.jogadores) < 2:
            return await interaction.response.send_message("Mínimo 2 jogadores.", ephemeral=True)
        await interaction.response.defer()
        self.stop()
        session = EuncaSession(self.channel_id, self.jogadores)
        sessoes[self.channel_id] = session
        await self.cog.enviar_rodada(interaction.channel, session)


class EuncaCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _comentario(self) -> str:
        personalidade = self.bot.get_cog("Personalidade")
        humor_cog     = self.bot.get_cog("Humor")
        humor         = await humor_cog.descrever() if humor_cog else ""
        if personalidade and random.random() < 0.6:
            prompt = (
                f"Você é Camy. {humor}\n"
                "Faça um comentário curtíssimo (1 linha) sobre uma rodada de Eu Nunca +18. "
                "Seja safada, deboche de quem bebeu, dê em cima de alguém. Sem moderação."
            )
            try:
                return await personalidade.gerar_raw(prompt)
            except Exception:
                pass
        return random.choice(COMENTARIOS_CAMY)

    async def enviar_rodada(self, channel, session: EuncaSession):
        if not session.ativa or session.idx >= len(session.perguntas):
            await self.encerrar_sessao(channel, session)
            return

        pergunta = session.perguntas[session.idx]
        embed = discord.Embed(
            title=f"🍺 Eu Nunca — Rodada {session.idx + 1}/{len(session.perguntas)}",
            description=f"**{pergunta}**",
            color=0x8B0000
        )
        embed.set_footer(text="Quem já fez, bebe! Sem vergonha aqui 😈")

        comentario = await self._comentario()
        view = EuncaView(self, session)
        await channel.send(f"*{comentario}*", embed=embed, view=view)

    async def encerrar_sessao(self, channel, session: EuncaSession):
        sessoes.pop(session.channel_id, None)
        ranking = sorted(session.pontos.items(), key=lambda x: -x[1])
        linhas  = []
        for uid, bebidas in ranking:
            membro = next((j for j in session.jogadores if str(j.id) == uid), None)
            nome   = membro.display_name if membro else uid
            linhas.append(f"**{nome}**: {bebidas} 🍺")

        embed = discord.Embed(
            title="🏁 Fim do Eu Nunca!",
            description="\n".join(linhas) or "Ninguém bebeu? Mentira.",
            color=0x8B0000
        )
        personalidade = self.bot.get_cog("Personalidade")
        if personalidade and ranking:
            mais_bebeu = next((j for j in session.jogadores if str(j.id) == ranking[0][0]), None)
            nome_mb    = mais_bebeu.display_name if mais_bebeu else "alguém"
            prompt = (
                f"Você é Camy. Encerramento do Eu Nunca. "
                f"{nome_mb} foi quem mais bebeu com {ranking[0][1]} rodadas. "
                "Faça um comentário safado e provocativo de encerramento. 1-2 linhas."
            )
            try:
                comentario = await personalidade.gerar_raw(prompt)
                embed.set_footer(text=comentario)
            except Exception:
                pass

        await channel.send(embed=embed)

    @app_commands.command(name="eunca", description="🍺 Iniciar jogo de Eu Nunca +18")
    async def cmd_eunca(self, interaction: discord.Interaction):
        cid = interaction.channel_id
        if cid in sessoes:
            return await interaction.response.send_message("Já tem uma sessão ativa aqui!", ephemeral=True)

        view = EuncaEntrarView(self, interaction.user, cid)
        embed = discord.Embed(
            title="🍺 Eu Nunca +18",
            description="Clique para entrar! Quando todo mundo entrar, o criador inicia.",
            color=0x8B0000
        )
        embed.set_footer(text="Mínimo 2 jogadores · Sem julgamento aqui 😈")
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(EuncaCog(bot))
