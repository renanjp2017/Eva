"""
cogs/vod.py — Verdade ou Desafio +18
/vod → abre sessão em grupo
Camy comenta cada rodada, dá em cima, provoca
"""
import discord, random, asyncio
from discord import app_commands
from discord.ext import commands

VERDADES = [
    # Leves
    "Qual foi a coisa mais safada que você já fez e nunca contou pra ninguém?",
    "Qual foi seu pior beijo da vida? Descreve.",
    "Você já teve tesão por alguém dessa call? Quem?",
    "Qual é a sua maior fantasia sexual que você nunca realizou?",
    "Você já mandou nudes? Pra quem?",
    "Qual foi a situação mais constrangedora que você passou na cama?",
    "Você já fingiu orgasmo? Com quem?",
    "Qual é a coisa que você mais tem vergonha de admitir que gosta?",
    "Você já ficou com alguém só por pena?",
    "Qual é seu fetiche mais bizarro?",
    # Médias
    "Descreve o melhor sexo que você já teve. Sem poupar detalhes.",
    "Você já traiu ou foi traído(a)? Conta a história.",
    "Qual é a pessoa mais inapropriada com quem você já ficou?",
    "Você já fez sexo em lugar público? Onde?",
    "Qual é a fantasia que você tem mas nunca falaria pra sua família?",
    "Você já usou alguém emocionalmente só pelo sexo?",
    "Qual é a coisa mais ousada que você já fez numa ligação de vídeo?",
    "Você já flertou com mais de uma pessoa ao mesmo tempo sabendo das duas?",
    "Qual foi a pior decisão que você tomou por causa de atração física?",
    "Você já gravou algo que não deveria ter gravado?",
    # Pesadas
    "Qual é a fantasia que você tem vergonha de admitir até pra si mesmo(a)?",
    "Se tivesse que escolher alguém dessa call pra uma noite, quem seria?",
    "Qual é a coisa mais safada que você já fez com mais de uma pessoa?",
    "Você já mandou mensagem pra pessoa errada com conteúdo que não era pra ela ver?",
    "Qual é o lugar mais absurdo onde você já transou ou quis transar?",
    "Se você pudesse fazer qualquer coisa com alguém dessa call sem consequências, o que seria?",
    "Qual é a maior mentira que você já contou pra conseguir ficar com alguém?",
    "Você já fez roleplay ou fantasia? Conta.",
    "Qual foi a situação mais intensa que você já viveu e nunca contaria pra família?",
    "Se tivesse que mandar uma foto agora como prova de algo, o que seria?",
]

DESAFIOS = [
    # Leves
    "Imita o som que você faz quando tá com prazer. Vai.",
    "Manda uma mensagem pra alguém da sua lista de contatos dizendo que tá com saudade. Agora.",
    "Conta uma fantasia sua em 30 segundos sem parar.",
    "Faz uma pose sensual na câmera por 5 segundos.",
    "Manda um áudio com sua voz mais sedutora dizendo o nome de alguém dessa call.",
    "Descreve o que você faria se ficasse sozinho(a) com alguém dessa call.",
    "Manda um emoji que representa seu estado de espírito sexual agora.",
    "Conta o último sonho erótico que você teve.",
    "Diz o nome de alguém que você já fantasiou aqui no servidor.",
    "Faz uma careta de prazer na câmera por 3 segundos.",
    # Médias
    "Liga pro número mais recente da sua lista e diz 'tava pensando em você'. Agora.",
    "Manda uma mensagem ousada pra alguém que você escolher dessa call.",
    "Faz um mini striptease de 10 segundos na câmera — pelo menos tira a camiseta.",
    "Diz em voz alta a coisa mais safada que você já pensou sobre alguém dessa call.",
    "Manda um print do seu histórico de busca de hoje. Ou inventa um motivo pra não mostrar.",
    "Faz uma pose de revista na câmera. 10 segundos. Vale qualquer coisa.",
    "Manda um áudio gemendo dramaticamente por 3 segundos.",
    "Descreve em detalhes o que você faria numa noite com alguém que você escolher aqui.",
    "Tira uma foto mostrando mais do que deveria e manda no privado de quem a Camy escolher.",
    "Passa 30 segundos fazendo seu melhor olhar sedutor na câmera sem rir.",
    # Pesadas
    "Tira uma peça de roupa agora na câmera. Sem desculpa.",
    "Manda uma foto atrevida no privado de alguém que a Camy vai sortear.",
    "Fica de roupa íntima na câmera por 1 minuto.",
    "Faz um striptease completo de pelo menos 2 peças na câmera.",
    "Manda a foto mais ousada que você tem no celular agora pra alguém dessa call.",
    "Descreve em voz alta o que você faria com alguém aqui se a câmera sumisse agora.",
    "Fica 2 minutos falando ao vivo o que você faria numa noite com a pessoa da sua direita na tela.",
    "Tira uma foto de algo que vc normalmente não mostraria e manda pra Camy escolher quem recebe.",
    "Faz um vídeo de 15 segundos do seu melhor movimento sensual e manda no canal.",
    "Escolhe alguém dessa call e passa 1 minuto descrevendo o que você faria com ela(e) em detalhes.",
]

COMENTARIOS_VERDADE = [
    "essa pergunta vai separar os corajosos dos mentirosos 😈",
    "responde sem enrolar bb",
    "eu preciso de detalhes. DETALHES.",
    "tô curiosa e não tô com vergonha de admitir 👀",
    "alguém vai mentir aqui. eu sei.",
    "essa é boa... e vai deixar alguém vermelho 🔥",
]

COMENTARIOS_DESAFIO = [
    "faz ou tira uma roupa. simples assim 💅",
    "sem desculpa. vai.",
    "eu tô assistindo e julgando. pode começar.",
    "esse desafio foi feito pra deixar vc sem saída 😏",
    "vai ser engraçado ou vai ser quente. de qualquer forma eu ganho.",
    "coragem, bb. ou a roupa sai 🔥",
]


class VoDSession:
    def __init__(self, channel_id: int, jogadores: list):
        self.channel_id = channel_id
        self.jogadores  = list(jogadores)
        self.idx_jogador = 0
        self.ativa      = True
        self.rodada     = 0

    def jogador_atual(self) -> discord.Member:
        return self.jogadores[self.idx_jogador % len(self.jogadores)]

    def avancar(self):
        self.idx_jogador = (self.idx_jogador + 1) % len(self.jogadores)
        self.rodada += 1


sessoes: dict[int, VoDSession] = {}


class EscolhaView(discord.ui.View):
    def __init__(self, cog, session: VoDSession):
        super().__init__(timeout=60)
        self.cog     = cog
        self.session = session

    @discord.ui.button(label="🗣️ Verdade", style=discord.ButtonStyle.primary)
    async def verdade(self, interaction: discord.Interaction, btn):
        j = self.session.jogador_atual()
        if interaction.user.id != j.id:
            return await interaction.response.send_message("Não é sua vez!", ephemeral=True)
        await interaction.response.defer()
        self.stop()
        await self.cog.fazer_verdade(interaction.channel, self.session)

    @discord.ui.button(label="💪 Desafio", style=discord.ButtonStyle.danger)
    async def desafio(self, interaction: discord.Interaction, btn):
        j = self.session.jogador_atual()
        if interaction.user.id != j.id:
            return await interaction.response.send_message("Não é sua vez!", ephemeral=True)
        await interaction.response.defer()
        self.stop()
        await self.cog.fazer_desafio(interaction.channel, self.session)

    @discord.ui.button(label="🚫 Encerrar", style=discord.ButtonStyle.grey)
    async def encerrar(self, interaction: discord.Interaction, btn):
        if interaction.user not in self.session.jogadores:
            return await interaction.response.send_message("Você não está nessa sessão.", ephemeral=True)
        await interaction.response.defer()
        self.stop()
        sessoes.pop(self.session.channel_id, None)
        await interaction.channel.send("🔚 Sessão encerrada. Espero ter deixado vocês constrangidos 😈")


class ProximaView(discord.ui.View):
    def __init__(self, cog, session: VoDSession):
        super().__init__(timeout=120)
        self.cog     = cog
        self.session = session

    @discord.ui.button(label="➡️ Próximo", style=discord.ButtonStyle.success)
    async def proxima(self, interaction: discord.Interaction, btn):
        if interaction.user not in self.session.jogadores:
            return await interaction.response.send_message("Você não está nessa sessão.", ephemeral=True)
        await interaction.response.defer()
        self.stop()
        self.session.avancar()
        await self.cog.nova_rodada(interaction.channel, self.session)

    @discord.ui.button(label="🚫 Encerrar", style=discord.ButtonStyle.grey)
    async def encerrar(self, interaction: discord.Interaction, btn):
        if interaction.user not in self.session.jogadores:
            return await interaction.response.send_message("Você não está nessa sessão.", ephemeral=True)
        await interaction.response.defer()
        self.stop()
        sessoes.pop(self.session.channel_id, None)
        await interaction.channel.send("🔚 Encerrado. Valeu por existirem 😈")


class EntrarVoDView(discord.ui.View):
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
            f"✅ **{interaction.user.display_name}** entrou! ({len(self.jogadores)} jogadores)"
        )

    @discord.ui.button(label="▶️ Iniciar", style=discord.ButtonStyle.primary)
    async def iniciar(self, interaction: discord.Interaction, btn):
        if interaction.user != self.criador:
            return await interaction.response.send_message("Só quem criou pode iniciar.", ephemeral=True)
        if len(self.jogadores) < 2:
            return await interaction.response.send_message("Mínimo 2 jogadores.", ephemeral=True)
        await interaction.response.defer()
        self.stop()
        session = VoDSession(self.channel_id, self.jogadores)
        sessoes[self.channel_id] = session
        await self.cog.nova_rodada(interaction.channel, session)


class VoDCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _comentario_vod(self, tipo: str) -> str:
        personalidade = self.bot.get_cog("Personalidade")
        humor_cog     = self.bot.get_cog("Humor")
        humor         = await humor_cog.descrever() if humor_cog else ""
        pool = COMENTARIOS_VERDADE if tipo == "verdade" else COMENTARIOS_DESAFIO
        if personalidade and random.random() < 0.5:
            prompt = (
                f"Você é Camy. {humor}\n"
                f"Faça um comentário curtíssimo (1 linha) antes de uma {'verdade' if tipo=='verdade' else 'desafio'} +18. "
                "Seja safada e provocativa."
            )
            try:
                return await personalidade.gerar_raw(prompt)
            except Exception:
                pass
        return random.choice(pool)

    async def nova_rodada(self, channel, session: VoDSession):
        if not session.ativa:
            return
        j = session.jogador_atual()
        embed = discord.Embed(
            title=f"🎲 Verdade ou Desafio — Rodada {session.rodada + 1}",
            description=f"**{j.mention}** — Verdade ou Desafio?",
            color=0x8B0000
        )
        view = EscolhaView(self, session)
        await channel.send(embed=embed, view=view)

    async def fazer_verdade(self, channel, session: VoDSession):
        j        = session.jogador_atual()
        pergunta = random.choice(VERDADES)
        coment   = await self._comentario_vod("verdade")
        embed = discord.Embed(
            title=f"🗣️ Verdade para {j.display_name}",
            description=f"**{pergunta}**",
            color=0x4169E1
        )
        embed.set_footer(text=coment)
        view = ProximaView(self, session)
        await channel.send(embed=embed, view=view)

    async def fazer_desafio(self, channel, session: VoDSession):
        j        = session.jogador_atual()
        desafio  = random.choice(DESAFIOS)
        coment   = await self._comentario_vod("desafio")
        embed = discord.Embed(
            title=f"💪 Desafio para {j.display_name}",
            description=f"**{desafio}**",
            color=0x8B0000
        )
        embed.set_footer(text=coment)
        view = ProximaView(self, session)
        await channel.send(embed=embed, view=view)

    @app_commands.command(name="vod", description="🎲 Iniciar Verdade ou Desafio +18")
    async def cmd_vod(self, interaction: discord.Interaction):
        cid = interaction.channel_id
        if cid in sessoes:
            return await interaction.response.send_message("Já tem uma sessão ativa aqui!", ephemeral=True)
        view = EntrarVoDView(self, interaction.user, cid)
        embed = discord.Embed(
            title="🎲 Verdade ou Desafio +18",
            description="Clique para entrar! Quando todo mundo entrar, o criador inicia.\n\nSem censura aqui. 😈",
            color=0x8B0000
        )
        embed.set_footer(text="Mínimo 2 jogadores · Vai ser inesquecível")
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(VoDCog(bot))
