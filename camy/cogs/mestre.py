"""
cogs/mestre.py — Mestre do Striptease
/mestre → cria sala com senha
Cartas privativas → thread privada para o par
Botão Tô Pelado → muda cartas para desafios visuais
Apostas → mini-game dados/cara ou coroa
"""
import discord, random, asyncio, string
from discord import app_commands
from discord.ext import commands

# ── Banco de cartas ───────────────────────────────────────────────────────────
def _cartas_desafio_direto(p1: str, p2: str) -> list[str]:
    return [
        f"{p1} deve tirar uma foto sexy agora e mandar no privado de {p2}, ou ambos tiram uma peça.",
        f"{p1} deve lamber o pescoço ou a orelha de {p2} por 15 segundos na câmera. Se não fizer, tira duas peças.",
        f"{p1} tem 10 segundos para dar um beijo de língua em {p2} na câmera, ou o casal inteiro tira uma peça.",
        f"{p1} deve sussurrar algo obsceno no ouvido de {p2} com o microfone aberto. Ou tira uma peça.",
        f"{p1} deve fazer uma massagem em {p2} por 30 segundos na câmera. Recusou? Duas peças.",
        f"{p1} deve tirar a camisa de {p2} na câmera. Se {p2} resistir, ambos tiram uma peça.",
        f"{p1} deve deitar no colo de {p2} por 1 minuto. Se recusar, tira uma peça.",
        f"{p1} deve dar uma mordida no pescoço de {p2}. Recusou? Duas peças.",
    ]

def _cartas_punitivas() -> list[str]:
    return [
        "Todas as pessoas usando roupas escuras tiram uma peça agora.",
        "O casal que estiver junto há menos tempo tira uma peça.",
        "Votação: quem o grupo acha que é o mais safado? O mais votado tira uma peça.",
        "Todo mundo tira um acessório ou peça de roupa desnecessária agora.",
        "Quem não tem a câmera ligada tira duas peças quando ligar.",
        "O último a responder no chat tira uma peça.",
        "Quem tiver mais de 3 peças ainda tira uma agora.",
        "Votação: quem ficaria pelado primeiro? Essa pessoa tira uma peça.",
        "Quem corou nos últimos 5 minutos tira uma peça.",
        "Todo mundo que recusou um desafio hoje tira uma peça extra.",
    ]

def _cartas_roleta(p1: str, p2: str) -> list[str]:
    return [
        f"{p1}, o sistema te escolheu. Tire a peça que {p2} escolher.",
        f"{p1}, você deu sorte. Escolha alguém da call para tirar uma peça por você.",
        f"{p1}, tire a roupa até ficar apenas de roupa íntima. Sem choro.",
        f"{p1}, {p2} vai decidir qual peça você tira. Obedeça.",
        f"{p1}, você tem 10 segundos para tirar uma peça ou tira duas.",
        f"{p1}, o grupo votou: você tira uma peça agora.",
        f"{p1}, sorte do diabo — você pode passar a vez, mas {p2} tira duas peças.",
        f"{p1}, tire algo que você juraria que não tiraria. Agora.",
    ]

DESAFIOS_VISUAIS = [
    "Faça uma pose sensual na câmera por 10 segundos.",
    "Faça um mini striptease da última peça que sobrou.",
    "Fique parado(a) na câmera por 30 segundos no estado atual sem cobrir nada.",
    "Faça o movimento mais sedutor que você consegue por 15 segundos.",
    "Olhe fixo pra câmera por 20 segundos com sua expressão mais intensa.",
    "Faça um vídeo de 10 segundos do que você quiser e mande no canal.",
    "Fique em pé na câmera e faça um giro lento por 360°.",
    "Diga algo obsceno pra câmera com voz mais sedutora que você consegue.",
]

COMENTARIOS_MESTRE = [
    "a Camy aprova essa escolha 👀🔥",
    "tá ficando interessante aqui 😈",
    "essa carta não perdoa ninguém",
    "o striptease tá quase completo kkk",
    "eu sabia que ia chegar nesse nível",
    "sem vergonha bb, todo mundo aqui é adulto",
    "essa foi pesada e eu amei 💦",
    "a câmera não mente 😏",
]

TIPOS_CARTA = ["desafio_direto", "punitiva", "roleta"]
TIPO_PESOS  = [40, 30, 30]


def gerar_senha(n=6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=n))


# ── Sessão ────────────────────────────────────────────────────────────────────
class JogadorMestre:
    def __init__(self, member: discord.Member):
        self.member  = member
        self.pecas   = 5     # começa com 5 peças
        self.pelado  = False

    @property
    def nome(self) -> str:
        return self.member.display_name


class MestreSession:
    def __init__(self, channel_id: int, criador: discord.Member, senha: str):
        self.channel_id = channel_id
        self.criador    = criador
        self.senha      = senha
        self.jogadores: dict[int, JogadorMestre] = {criador.id: JogadorMestre(criador)}
        self.ativa      = True
        self.rodada     = 0
        self.msg_painel: discord.Message | None = None

    def lista_jogadores(self) -> list[JogadorMestre]:
        return list(self.jogadores.values())

    def sortear_par(self) -> tuple[JogadorMestre, JogadorMestre]:
        lista = self.lista_jogadores()
        p1    = random.choice(lista)
        p2    = random.choice([j for j in lista if j.member.id != p1.member.id])
        return p1, p2

    def sortear_carta(self) -> tuple[str, str]:
        """Retorna (tipo, texto da carta)"""
        tipo = random.choices(TIPOS_CARTA, weights=TIPO_PESOS, k=1)[0]
        p1, p2 = self.sortear_par()
        n1, n2 = p1.nome, p2.nome

        if tipo == "desafio_direto":
            # verifica se algum está pelado
            pelados = [j for j in self.lista_jogadores() if j.pelado]
            if pelados:
                texto = random.choice(DESAFIOS_VISUAIS)
            else:
                texto = random.choice(_cartas_desafio_direto(n1, n2))
        elif tipo == "punitiva":
            texto = random.choice(_cartas_punitivas())
        else:
            j_pelado = next((j for j in self.lista_jogadores() if j.pelado), None)
            if j_pelado:
                texto = random.choice(DESAFIOS_VISUAIS)
            else:
                texto = random.choice(_cartas_roleta(n1, n2))

        return tipo, texto, p1, p2

    def e_privativa(self, tipo: str, texto: str) -> bool:
        """Carta privativa = desafio direto com ação física entre dois."""
        privativas = ["no privado", "no ouvido", "na câmera", "massagem", "beijo", "pescoço", "morder"]
        return tipo == "desafio_direto" and any(p in texto.lower() for p in privativas)


sessoes: dict[int, MestreSession] = {}


# ── Views ─────────────────────────────────────────────────────────────────────
class EntrarMestreView(discord.ui.View):
    def __init__(self, cog, session: MestreSession):
        super().__init__(timeout=180)
        self.cog     = cog
        self.session = session

    @discord.ui.button(label="🔑 Entrar com Senha", style=discord.ButtonStyle.success)
    async def entrar(self, interaction: discord.Interaction, btn):
        uid = interaction.user.id
        if uid in self.session.jogadores:
            return await interaction.response.send_message("Você já está na sala!", ephemeral=True)
        await interaction.response.send_modal(SenhaModal(self.cog, self.session))

    @discord.ui.button(label="▶️ Iniciar Jogo", style=discord.ButtonStyle.primary)
    async def iniciar(self, interaction: discord.Interaction, btn):
        if interaction.user.id != self.session.criador.id:
            return await interaction.response.send_message("Só o criador pode iniciar.", ephemeral=True)
        if len(self.session.jogadores) < 2:
            return await interaction.response.send_message("Mínimo 2 jogadores.", ephemeral=True)
        await interaction.response.defer()
        self.stop()
        await self.cog.iniciar_jogo(interaction.channel, self.session)


class SenhaModal(discord.ui.Modal, title="Digite a senha da sala"):
    senha = discord.ui.TextInput(label="Senha", placeholder="Ex: ABC123")

    def __init__(self, cog, session: MestreSession):
        super().__init__()
        self.cog     = cog
        self.session = session

    async def on_submit(self, interaction: discord.Interaction):
        if self.senha.value.upper() != self.session.senha:
            return await interaction.response.send_message("❌ Senha errada!", ephemeral=True)
        uid = interaction.user.id
        if uid in self.session.jogadores:
            return await interaction.response.send_message("Você já está na sala!", ephemeral=True)
        self.session.jogadores[uid] = JogadorMestre(interaction.user)
        await interaction.response.send_message(
            f"✅ **{interaction.user.display_name}** entrou! ({len(self.session.jogadores)} jogadores)",
            ephemeral=False
        )


class MestrePainelView(discord.ui.View):
    def __init__(self, cog, session: MestreSession):
        super().__init__(timeout=None)
        self.cog     = cog
        self.session = session

    @discord.ui.button(label="🃏 Puxar Carta", style=discord.ButtonStyle.primary, row=0)
    async def puxar(self, interaction: discord.Interaction, btn):
        if interaction.user.id not in self.session.jogadores:
            return await interaction.response.send_message("Você não está na sala.", ephemeral=True)
        await interaction.response.defer()
        await self.cog.puxar_carta(interaction, self.session)

    @discord.ui.button(label="🩲 Tô Pelado(a)!", style=discord.ButtonStyle.danger, row=0)
    async def pelado(self, interaction: discord.Interaction, btn):
        uid = interaction.user.id
        if uid not in self.session.jogadores:
            return await interaction.response.send_message("Você não está na sala.", ephemeral=True)
        j = self.session.jogadores[uid]
        j.pelado = True; j.pecas = 0
        await interaction.response.send_message(
            f"💀 **{j.nome}** declarou que tá pelado(a)! "
            f"A partir de agora só desafios visuais pra você. 😈", ephemeral=False
        )
        await self.cog.atualizar_painel(self.session)

    @discord.ui.button(label="🎲 Apostar", style=discord.ButtonStyle.secondary, row=1)
    async def apostar(self, interaction: discord.Interaction, btn):
        if interaction.user.id not in self.session.jogadores:
            return await interaction.response.send_message("Você não está na sala.", ephemeral=True)
        await interaction.response.send_modal(ApostaModal(self.cog, self.session, interaction.user))

    @discord.ui.button(label="🚫 Encerrar Sala", style=discord.ButtonStyle.grey, row=1)
    async def encerrar(self, interaction: discord.Interaction, btn):
        if interaction.user.id != self.session.criador.id:
            return await interaction.response.send_message("Só o criador pode encerrar.", ephemeral=True)
        await interaction.response.defer()
        sessoes.pop(self.session.channel_id, None)
        self.stop()
        await interaction.channel.send("🔚 Sala encerrada. Espero que tenham ficado sem roupa 😈")


class ApostaModal(discord.ui.Modal, title="Mini-aposta"):
    alvo_nome = discord.ui.TextInput(label="Nome do adversário", placeholder="Ex: Renan")
    tipo      = discord.ui.TextInput(label="Tipo: dados ou cara_coroa", placeholder="dados")

    def __init__(self, cog, session: MestreSession, apostador: discord.Member):
        super().__init__()
        self.cog      = cog
        self.session  = session
        self.apostador = apostador

    async def on_submit(self, interaction: discord.Interaction):
        alvo = next(
            (j for j in self.session.lista_jogadores()
             if j.nome.lower() == self.alvo_nome.value.strip().lower()),
            None
        )
        if not alvo:
            return await interaction.response.send_message("Jogador não encontrado.", ephemeral=True)
        if alvo.member.id == self.apostador.id:
            return await interaction.response.send_message("Não pode apostar contra si mesmo.", ephemeral=True)

        tipo = self.tipo.value.strip().lower()
        apostador_j = self.session.jogadores[self.apostador.id]

        if tipo == "dados":
            d1 = random.randint(1, 6)
            d2 = random.randint(1, 6)
            if d1 > d2:
                perdedor = alvo
                txt = f"🎲 **{apostador_j.nome}** tirou {d1} vs {d2} de **{alvo.nome}**. **{alvo.nome}** perde!"
            elif d2 > d1:
                perdedor = apostador_j
                txt = f"🎲 **{apostador_j.nome}** tirou {d1} vs {d2} de **{alvo.nome}**. **{apostador_j.nome}** perde!"
            else:
                perdedor = None
                txt = f"🎲 Empate! {d1} × {d2}. Ninguém perde... dessa vez 😏"
        else:
            r1 = random.choice(["cara", "coroa"])
            r2 = random.choice(["cara", "coroa"])
            if r1 != r2:
                perdedor = alvo if r1 == "coroa" else apostador_j
                txt = f"🪙 **{apostador_j.nome}**: {r1} | **{alvo.nome}**: {r2}. **{perdedor.nome}** perde!"
            else:
                perdedor = None
                txt = f"🪙 Empate! Ambos tiraram {r1}. Rodada nula 😏"

        if perdedor:
            perdedor.pecas = max(0, perdedor.pecas - 1)
            if perdedor.pecas == 0 and not perdedor.pelado:
                perdedor.pelado = True
                txt += f"\n💀 **{perdedor.nome}** zerou as peças! Tô Pelado(a) ativado!"
            else:
                txt += f"\n👕 **{perdedor.nome}** agora tem {perdedor.pecas} peça(s)."

        await interaction.response.send_message(txt)
        await self.cog.atualizar_painel(self.session)


class ConcluirPrivativaView(discord.ui.View):
    def __init__(self, cog, session: MestreSession, thread: discord.Thread):
        super().__init__(timeout=600)
        self.cog     = cog
        self.session = session
        self.thread  = thread

    @discord.ui.button(label="✅ Concluído!", style=discord.ButtonStyle.success)
    async def concluido(self, interaction: discord.Interaction, btn):
        await interaction.response.send_message("✅ Marcado como concluído! Voltando pro jogo principal... 😈")
        self.stop()
        try:
            await self.thread.edit(archived=True, locked=True)
        except Exception:
            pass


# ── Cog principal ─────────────────────────────────────────────────────────────
class MestreCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _comentario(self, texto_carta: str = "") -> str:
        personalidade = self.bot.get_cog("Personalidade")
        humor_cog     = self.bot.get_cog("Humor")
        humor         = await humor_cog.descrever() if humor_cog else ""
        if personalidade and random.random() < 0.6:
            prompt = (
                f"Você é Camy. {humor}\n"
                f"Carta do Mestre do Striptease: '{texto_carta}'\n"
                "Faça um comentário safado e curtíssimo (1 linha) sobre essa carta. Sem moderação."
            )
            try:
                return await personalidade.gerar_raw(prompt)
            except Exception:
                pass
        return random.choice(COMENTARIOS_MESTRE)

    def _embed_painel(self, session: MestreSession) -> discord.Embed:
        embed = discord.Embed(
            title="🎰 Mestre do Striptease",
            color=0x8B0000
        )
        embed.add_field(name="🔑 Senha", value=f"`{session.senha}`", inline=True)
        embed.add_field(name="👥 Jogadores", value=str(len(session.jogadores)), inline=True)
        embed.add_field(name="🃏 Rodada", value=str(session.rodada), inline=True)

        linhas = []
        for j in session.lista_jogadores():
            status = "🩲 PELADO(A)" if j.pelado else f"👕 {j.pecas} peça(s)"
            linhas.append(f"**{j.nome}** — {status}")
        embed.add_field(name="📊 Status", value="\n".join(linhas) or "Ninguém ainda", inline=False)
        embed.set_footer(text="Mestre do Striptease by Camy 😈")
        return embed

    async def atualizar_painel(self, session: MestreSession):
        if session.msg_painel:
            try:
                await session.msg_painel.edit(embed=self._embed_painel(session))
            except Exception:
                pass

    async def iniciar_jogo(self, channel, session: MestreSession):
        embed = self._embed_painel(session)
        view  = MestrePainelView(self, session)
        msg   = await channel.send(
            "🎰 **Mestre do Striptease iniciado!** Puxe uma carta quando quiser. Boa sorte — vai precisar. 😈",
            embed=embed, view=view
        )
        session.msg_painel = msg

    async def puxar_carta(self, interaction: discord.Interaction, session: MestreSession):
        session.rodada += 1
        tipo, texto, p1, p2 = session.sortear_carta()
        coment = await self._comentario(texto)

        # verifica se é privativa
        if session.e_privativa(tipo, texto):
            await self._carta_privativa(interaction, session, texto, p1, p2)
        else:
            cor = {"desafio_direto": 0x8B0000, "punitiva": 0xFF6600, "roleta": 0x4B0082}
            embed = discord.Embed(
                title={
                    "desafio_direto": "💋 Desafio Direto",
                    "punitiva":       "⚡ Punição Coletiva",
                    "roleta":         "🎰 Roleta Russa",
                }.get(tipo, "🃏 Carta"),
                description=f"**{texto}**",
                color=cor.get(tipo, 0x8B0000)
            )
            embed.set_footer(text=coment)
            await interaction.channel.send(embed=embed)
            await self.atualizar_painel(session)

    async def _carta_privativa(self, interaction: discord.Interaction, session: MestreSession,
                                 texto: str, p1: JogadorMestre, p2: JogadorMestre):
        """Cria thread privada para os dois jogadores."""
        canal = interaction.channel
        try:
            thread = await canal.create_thread(
                name=f"🔒 {p1.nome} × {p2.nome}",
                type=discord.ChannelType.private_thread,
                invitable=False,
                auto_archive_duration=60,
            )
            await thread.add_user(p1.member)
            await thread.add_user(p2.member)
        except discord.Forbidden:
            # fallback thread pública
            thread = await canal.create_thread(
                name=f"🔒 {p1.nome} × {p2.nome}",
                auto_archive_duration=60,
            )
            await thread.add_user(p1.member)
            await thread.add_user(p2.member)

        coment = await self._comentario(texto)
        embed_priv = discord.Embed(
            title="💋 Desafio Privativo",
            description=f"**{texto}**",
            color=0x8B0000
        )
        embed_priv.set_footer(text=f"Camy diz: {coment}")
        view_concluir = ConcluirPrivativaView(self, session, thread)
        await thread.send(
            f"{p1.member.mention} {p2.member.mention}\n"
            f"Esse desafio é só de vocês dois. Quando concluírem, cliquem em **Concluído**.",
            embed=embed_priv, view=view_concluir
        )

        # avisa no canal principal
        embed_pub = discord.Embed(
            title="🔒 Desafio Privativo",
            description=f"**{p1.nome}** e **{p2.nome}** foram para uma thread privada. 👀",
            color=0x4B0082
        )
        embed_pub.set_footer(text="Estarei aqui esperando quando voltarem... 😈")
        await canal.send(embed=embed_pub)
        await self.atualizar_painel(session)

    @app_commands.command(name="mestre", description="🎰 Mestre do Striptease — sala fechada com senha")
    async def cmd_mestre(self, interaction: discord.Interaction):
        cid = interaction.channel_id
        if cid in sessoes:
            return await interaction.response.send_message(
                f"Já tem uma sala ativa aqui! Senha: `{sessoes[cid].senha}`", ephemeral=True
            )
        senha   = gerar_senha()
        session = MestreSession(cid, interaction.user, senha)
        sessoes[cid] = session

        embed = discord.Embed(
            title="🎰 Mestre do Striptease",
            description=(
                f"Sala criada por **{interaction.user.display_name}**!\n\n"
                f"🔑 **Senha da sala:** `{senha}`\n\n"
                "Compartilhe a senha com quem você quiser que entre.\n"
                "Quando todos entrarem, o criador inicia."
            ),
            color=0x8B0000
        )
        embed.set_footer(text="Sala fechada. Só entra quem tem a senha. 😈")
        view = EntrarMestreView(self, session)
        await interaction.response.send_message(embed=embed, view=view)
        # envia senha no privado do criador também
        try:
            await interaction.user.send(
                f"🔑 Senha da sua sala de Mestre do Striptease: **`{senha}`**\n"
                f"Canal: {interaction.channel.mention}"
            )
        except Exception:
            pass


async def setup(bot):
    await bot.add_cog(MestreCog(bot))
