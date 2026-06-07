import discord
from discord import app_commands
from discord.ext import commands
import random
import asyncio
from dataclasses import dataclass, field
from typing import Optional
from .base import get_fichas, set_fichas, checar_canal, atualizar_msg, FakeUser, FICHAS_INICIAIS, APOSTA_MINIMA, APOSTA_MAXIMA, registrar_resultado, registrar_atividade, cancelar_timeout


jogos: dict = {}  # canal_id -> JogoTruco

# ─────────────────────────────────────────
#  BARALHO - TRUCO PAULISTA
#  Ordem de força: 4♣ > 7♥ > A♠ > 7♦ > 3 > 2 > A > K > J > Q > 7 > 6 > 5 > 4
# ─────────────────────────────────────────
MANILHAS_PAULISTA = ["4♣", "7♥", "A♠", "7♦"]  # zap, copas, espadão, ouros

VALORES = {
    "4♣": 14, "7♥": 13, "A♠": 12, "7♦": 11,
    "3": 10, "2": 9, "A": 8, "K": 7, "J": 6, "Q": 5,
    "7": 4, "6": 3, "5": 2, "4": 1,
}

NAIPES = ["♠", "♥", "♦", "♣"]
NUMEROS = ["4", "5", "6", "7", "Q", "J", "K", "A", "2", "3"]

EMOJIS_NAIPE = {"♠": "♠️", "♥": "♥️", "♦": "♦️", "♣": "♣️"}

def gerar_baralho():
    baralho = []
    for num in NUMEROS:
        for naipe in NAIPES:
            carta = f"{num}{naipe}"
            # Manilhas fixas no paulista
            if carta in MANILHAS_PAULISTA:
                baralho.append(carta)
            elif num == "4" and naipe != "♣":
                baralho.append(carta)  # 4 normais (valor 1)
            else:
                baralho.append(carta)
    return baralho

def valor_carta(carta: str) -> int:
    if carta in VALORES:
        return VALORES[carta]
    num = carta[:-1]
    return VALORES.get(num, 0)

def formatar_carta(carta: str) -> str:
    return f"`{carta}`"

# ─────────────────────────────────────────
#  ESTADOS DO JOGO
# ─────────────────────────────────────────
class EstadoTruco(Enum):
    AGUARDANDO   = "aguardando"
    JOGANDO      = "jogando"
    TRUCO_PEDIDO = "truco_pedido"
    FIM          = "fim"

@dataclass
class Equipe:
    nome: str
    jogadores: list = field(default_factory=list)
    pontos: int = 0
    maos_ganhas: int = 0  # na rodada atual

@dataclass
class JogoTruco:
    canal_id: int
    modo: str  # "1v1" ou "2v2"
    equipe1: Equipe = field(default_factory=lambda: Equipe("Time 1"))
    equipe2: Equipe = field(default_factory=lambda: Equipe("Time 2"))
    maos: dict = field(default_factory=dict)          # user_id -> [cartas]
    mesa: list = field(default_factory=list)           # [(user_id, carta)] na rodada
    rodada: int = 1                                    # 1, 2 ou 3
    vez: int = 0                                       # índice na lista de ordem
    ordem_jogadores: list = field(default_factory=list)
    estado: EstadoTruco = EstadoTruco.AGUARDANDO
    valor_rodada: int = 1                              # 1, 3, 6, 9, 12
    truco_por: Optional[int] = None                   # quem pediu truco
    vitorias_rodada: list = field(default_factory=list)  # equipe vencedora de cada mão
    primeiro_a_jogar: int = 0
    msg_id: int = 0  # ID da mensagem principal para editar

# Armazena jogos ativos por canal
jogos: dict[int, JogoTruco] = {}

# ─────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────
def get_equipe(jogo: JogoTruco, user_id: int) -> Optional[Equipe]:
    if user_id in [p.id for p in jogo.equipe1.jogadores]:
        return jogo.equipe1
    if user_id in [p.id for p in jogo.equipe2.jogadores]:
        return jogo.equipe2
    return None

def get_adversario(jogo: JogoTruco, user_id: int) -> Optional[Equipe]:
    eq = get_equipe(jogo, user_id)
    if eq == jogo.equipe1:
        return jogo.equipe2
    return jogo.equipe1

def jogador_atual(jogo: JogoTruco):
    return jogo.ordem_jogadores[jogo.vez % len(jogo.ordem_jogadores)]

def distribuir_cartas(jogo: JogoTruco):
    baralho = gerar_baralho()
    random.shuffle(baralho)
    jogo.maos = {}
    for i, jogador in enumerate(jogo.ordem_jogadores):
        jogo.maos[jogador.id] = baralho[i*3:(i+1)*3]
    jogo.mesa = []
    jogo.vitorias_rodada = []
    jogo.rodada = 1
    jogo.valor_rodada = 1
    jogo.truco_por = None
    jogo.estado = EstadoTruco.JOGANDO
    jogo.vez = jogo.primeiro_a_jogar

def embed_mesa(jogo: JogoTruco, canal) -> discord.Embed:
    atual = jogador_atual(jogo)
    e = discord.Embed(
        title="🃏 Truco Paulista",
        color=0x2B5219
    )
    e.add_field(
        name=f"📊 Placar",
        value=f"**{jogo.equipe1.nome}**: {jogo.equipe1.pontos} pts\n**{jogo.equipe2.nome}**: {jogo.equipe2.pontos} pts",
        inline=True
    )
    e.add_field(
        name="💰 Rodada vale",
        value=f"**{jogo.valor_rodada} ponto(s)**",
        inline=True
    )
    mao_txt = ""
    for i, v in enumerate(jogo.vitorias_rodada):
        mao_txt += f"Mão {i+1}: {v}\n"
    if mao_txt:
        e.add_field(name="🏆 Mãos", value=mao_txt, inline=False)

    mesa_txt = ""
    for uid, carta in jogo.mesa:
        jogador = discord.utils.get(jogo.ordem_jogadores, id=uid)
        nome = jogador.display_name if jogador else str(uid)
        mesa_txt += f"{nome}: {formatar_carta(carta)}\n"
    if mesa_txt:
        e.add_field(name="🎴 Mesa", value=mesa_txt, inline=False)

    e.set_footer(text=f"Vez de: {atual.display_name}")
    return e

async def anunciar(canal, jogo: JogoTruco, msg: str = None):
    embed = embed_mesa(jogo, canal)
    if msg:
        await canal.send(msg, embed=embed)
    else:
        await canal.send(embed=embed)

async def enviar_maos(jogo: JogoTruco):
    for jogador in jogo.ordem_jogadores:
        cartas = jogo.maos.get(jogador.id, [])
        txt = "🃏 **Suas cartas:**\n" + "  ".join(formatar_carta(c) for c in cartas)
        txt += "\n\nUse `/jogar <carta>` para jogar. Ex: `/jogar 3♠`"
        try:
            await jogador.send(txt)
        except Exception:
            pass  # DM fechada

def checar_fim_mao(jogo: JogoTruco) -> Optional[Equipe]:
    """Verifica se alguém ganhou a mão (rodada de 3 cartas)"""
    jogadores = jogo.ordem_jogadores
    n = len(jogadores)
    if len(jogo.mesa) < n:
        return None  # nem todos jogaram ainda

    # Determina vencedor da mão
    melhor_uid = None
    melhor_val = -1
    empate = False

    for uid, carta in jogo.mesa:
        v = valor_carta(carta)
        if v > melhor_val:
            melhor_val = v
            melhor_uid = uid
            empate = False
        elif v == melhor_val:
            empate = True

    if empate:
        return None  # empate = mão nula

    return get_equipe(jogo, melhor_uid)

def checar_vencedor_rodada(jogo: JogoTruco) -> Optional[Equipe]:
    """Determina vencedor da rodada (melhor de 3 mãos)"""
    v = jogo.vitorias_rodada
    eq1_wins = v.count(jogo.equipe1.nome)
    eq2_wins = v.count(jogo.equipe2.nome)

    if eq1_wins >= 2:
        return jogo.equipe1
    if eq2_wins >= 2:
        return jogo.equipe2
    if len(v) == 3:
        # Regras de empate paulista
        if eq1_wins > eq2_wins:
            return jogo.equipe1
        if eq2_wins > eq1_wins:
            return jogo.equipe2
        # Empate total: quem ganhou a primeira mão
        if v[0] != "Empate":
            for eq in [jogo.equipe1, jogo.equipe2]:
                if eq.nome == v[0]:
                    return eq
        return jogo.equipe1  # empate total: primeiro a jogar ganha
    return None

# ─────────────────────────────────────────
#  VIEWS (BOTÕES)
# ─────────────────────────────────────────
class EntrarView(discord.ui.View):
    def __init__(self, jogo: JogoTruco):
        super().__init__(timeout=120)
        self.jogo = jogo

    @discord.ui.button(label="Entrar no jogo", style=discord.ButtonStyle.success, emoji="🃏")
    async def entrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        jogo = self.jogo
        user = interaction.user
        todos = jogo.equipe1.jogadores + jogo.equipe2.jogadores
        if user in todos:
            await interaction.response.send_message("Você já está no jogo!", ephemeral=True)
            return

        max_j = 2 if jogo.modo == "1v1" else 4
        if len(todos) >= max_j:
            await interaction.response.send_message("Jogo cheio!", ephemeral=True)
            return

        if len(jogo.equipe1.jogadores) <= len(jogo.equipe2.jogadores):
            jogo.equipe1.jogadores.append(user)
            equipe = jogo.equipe1.nome
        else:
            jogo.equipe2.jogadores.append(user)
            equipe = jogo.equipe2.nome

        todos = jogo.equipe1.jogadores + jogo.equipe2.jogadores
        await interaction.response.send_message(
            f"✅ **{user.display_name}** entrou no **{equipe}**!\n"
            f"Jogadores: {len(todos)}/{max_j}"
        )

        if len(todos) == max_j:
            self.stop()
            await iniciar_jogo(interaction.channel, jogo)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        jogo = self.jogo
        criador = jogo.ordem_jogadores[0] if jogo.ordem_jogadores else None
        if criador and interaction.user.id != criador.id:
            await interaction.response.send_message("Só quem criou pode cancelar.", ephemeral=True)
            return
        jogos.pop(jogo.canal_id, None)
        self.stop()
        await interaction.response.send_message("❌ Jogo cancelado.")


class TrucoView(discord.ui.View):
    def __init__(self, jogo: JogoTruco, pedidor_id: int):
        super().__init__(timeout=30)
        self.jogo = jogo
        self.pedidor_id = pedidor_id

    @discord.ui.button(label="Aceitar", style=discord.ButtonStyle.success, emoji="✅")
    async def aceitar(self, interaction: discord.Interaction, button: discord.ui.Button):
        jogo = self.jogo
        adversario = get_adversario(jogo, self.pedidor_id)
        if interaction.user not in adversario.jogadores:
            await interaction.response.send_message("Não é você que decide!", ephemeral=True)
            return
        # Sobe o valor
        escala = [1, 3, 6, 9, 12]
        idx = escala.index(jogo.valor_rodada) if jogo.valor_rodada in escala else 0
        jogo.valor_rodada = escala[min(idx + 1, len(escala) - 1)]
        jogo.estado = EstadoTruco.JOGANDO
        self.stop()
        await interaction.response.send_message(
            f"✅ Truco aceito! Rodada agora vale **{jogo.valor_rodada} pontos**."
        )
        canal = interaction.channel
        await anunciar(canal, jogo)

    @discord.ui.button(label="Correr", style=discord.ButtonStyle.danger, emoji="🏃")
    async def correr(self, interaction: discord.Interaction, button: discord.ui.Button):
        jogo = self.jogo
        adversario = get_adversario(jogo, self.pedidor_id)
        if interaction.user not in adversario.jogadores:
            await interaction.response.send_message("Não é você que decide!", ephemeral=True)
            return
        # Quem correu perde o valor atual
        pedidor_eq = get_equipe(jogo, self.pedidor_id)
        adversario.pontos  # quem correu perde
        pts = jogo.valor_rodada
        pedidor_eq.pontos += pts
        jogo.estado = EstadoTruco.JOGANDO
        self.stop()
        await interaction.response.send_message(
            f"🏃 {interaction.user.display_name} correu! **{pedidor_eq.nome}** ganha **{pts} ponto(s)**."
        )
        await nova_rodada(interaction.channel, jogo)

    @discord.ui.button(label="Aumentar", style=discord.ButtonStyle.primary, emoji="⬆️")
    async def aumentar(self, interaction: discord.Interaction, button: discord.ui.Button):
        jogo = self.jogo
        adversario = get_adversario(jogo, self.pedidor_id)
        if interaction.user not in adversario.jogadores:
            await interaction.response.send_message("Não é você que decide!", ephemeral=True)
            return
        escala = [1, 3, 6, 9, 12]
        idx = escala.index(jogo.valor_rodada) if jogo.valor_rodada in escala else 0
        if idx >= len(escala) - 2:
            await interaction.response.send_message("Não dá pra aumentar mais!", ephemeral=True)
            return
        prox = escala[idx + 2]
        self.stop()
        # Agora quem pediu truco precisa aceitar/correr
        jogo.truco_por = interaction.user.id
        jogo.estado = EstadoTruco.TRUCO_PEDIDO
        canal = interaction.channel
        nome_prox = {3: "Truco", 6: "Seis", 9: "Nove", 12: "Doze"}.get(prox, str(prox))
        view = TrucoView(jogo, interaction.user.id)
        await interaction.response.send_message(
            f"⬆️ **{interaction.user.display_name}** quer **{nome_prox}**! "
            f"**{get_equipe(jogo, self.pedidor_id).nome}**, aceita?",
            view=view
        )


class JogarCartaView(discord.ui.View):
    def __init__(self, jogo: JogoTruco, user_id: int):
        super().__init__(timeout=60)
        self.jogo = jogo
        self.user_id = user_id
        cartas = jogo.maos.get(user_id, [])
        for carta in cartas:
            self.add_item(CartaButton(carta, jogo, user_id))


class CartaButton(discord.ui.Button):
    def __init__(self, carta: str, jogo: JogoTruco, user_id: int):
        super().__init__(label=carta, style=discord.ButtonStyle.secondary)
        self.carta = carta
        self.jogo = jogo
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Não é sua vez!", ephemeral=True)
            return
        await interaction.response.defer()
        self.view.stop()
        await processar_jogada(interaction.channel, self.jogo, self.user_id, self.carta)


# ─────────────────────────────────────────
#  LÓGICA DO JOGO
# ─────────────────────────────────────────
async def iniciar_jogo(canal, jogo: JogoTruco):
    jogo.ordem_jogadores = []
    if jogo.modo == "1v1":
        jogo.ordem_jogadores = [jogo.equipe1.jogadores[0], jogo.equipe2.jogadores[0]]
    else:
        # 2v2: intercala os times
        jogo.ordem_jogadores = [
            jogo.equipe1.jogadores[0], jogo.equipe2.jogadores[0],
            jogo.equipe1.jogadores[1], jogo.equipe2.jogadores[1],
        ]
    jogo.equipe1.nome = f"Time de {jogo.equipe1.jogadores[0].display_name}"
    jogo.equipe2.nome = f"Time de {jogo.equipe2.jogadores[0].display_name}"
    jogo.primeiro_a_jogar = 0

    distribuir_cartas(jogo)
    await enviar_maos(jogo)

    await canal.send(
        f"🃏 **Jogo começou!**\n"
        f"**{jogo.equipe1.nome}** vs **{jogo.equipe2.nome}**\n"
        f"Cartas enviadas por DM! Primeiro a jogar: **{jogo.ordem_jogadores[0].display_name}**"
    )
    await pedir_jogada(canal, jogo)


async def pedir_jogada(canal, jogo: JogoTruco):
    registrar_atividade(jogo.canal_id, _encerrar_truco_timeout)
    atual = jogador_atual(jogo)
    cartas = jogo.maos.get(atual.id, [])
    if not cartas:
        await canal.send(f"{atual.mention} não tem mais cartas!")
        return

    embed = embed_mesa(jogo, canal)
    view = JogarCartaView(jogo, atual.id)
    jogo.msg_id = await _atualizar_msg(
        canal, jogo.msg_id,
        content_txt=f"{atual.mention} é sua vez! Escolha uma carta:",
        embed=embed, view=view
    )


async def processar_jogada(canal, jogo: JogoTruco, user_id: int, carta: str):
    cartas = jogo.maos.get(user_id, [])
    if carta not in cartas:
        await canal.send("Carta inválida!", ephemeral=True)
        return

    cartas.remove(carta)
    jogo.mesa.append((user_id, carta))
    jogador = discord.utils.get(jogo.ordem_jogadores, id=user_id)
    await canal.send(f"🃏 **{jogador.display_name}** jogou {formatar_carta(carta)}")

    n = len(jogo.ordem_jogadores)

    if len(jogo.mesa) < n:
        # Próximo jogador
        jogo.vez += 1
        await pedir_jogada(canal, jogo)
        return

    # Todos jogaram — resolve mão
    vencedor_eq = checar_fim_mao(jogo)
    if vencedor_eq is None:
        jogo.vitorias_rodada.append("Empate")
        await canal.send("🤝 **Empate na mão!**")
    else:
        jogo.vitorias_rodada.append(vencedor_eq.nome)
        await canal.send(f"🏆 **{vencedor_eq.nome}** venceu a mão!")

    jogo.mesa = []

    # Verifica vencedor da rodada
    vencedor_rodada = checar_vencedor_rodada(jogo)
    if vencedor_rodada:
        vencedor_rodada.pontos += jogo.valor_rodada
        await canal.send(
            f"🎉 **{vencedor_rodada.nome}** venceu a rodada e ganhou **{jogo.valor_rodada} ponto(s)**!\n"
            f"Placar: **{jogo.equipe1.nome}** {jogo.equipe1.pontos} x {jogo.equipe2.pontos} **{jogo.equipe2.nome}**"
        )
        # Verifica fim de jogo (11 pontos)
        if jogo.equipe1.pontos >= 11 or jogo.equipe2.pontos >= 11:
            venc = jogo.equipe1 if jogo.equipe1.pontos >= 11 else jogo.equipe2
            await canal.send(
                f"🏆🏆🏆 **{venc.nome} GANHOU O JOGO!** 🏆🏆🏆\n"
                f"Placar final: {jogo.equipe1.pontos} x {jogo.equipe2.pontos}"
            )
            jogos.pop(jogo.canal_id, None)
            return
        await nova_rodada(canal, jogo)
    else:
        # Próxima mão
        jogo.rodada += 1
        # Quem ganhou a mão começa a próxima
        if vencedor_eq:
            idx = jogo.equipe1.jogadores[0] if vencedor_eq == jogo.equipe1 else jogo.equipe2.jogadores[0]
            jogo.vez = jogo.ordem_jogadores.index(idx)
        else:
            jogo.vez += 1
        await pedir_jogada(canal, jogo)


async def nova_rodada(canal, jogo: JogoTruco):
    await asyncio.sleep(2)
    jogo.primeiro_a_jogar = (jogo.primeiro_a_jogar + 1) % len(jogo.ordem_jogadores)
    distribuir_cartas(jogo)
    await enviar_maos(jogo)
    proximo = jogo.ordem_jogadores[jogo.primeiro_a_jogar]
    await canal.send(
        f"🔄 **Nova rodada!** Cartas distribuídas.\n"
        f"Primeiro a jogar: **{proximo.display_name}**"
    )
    await pedir_jogada(canal, jogo)


# ─────────────────────────────────────────
#  COMANDOS SLASH
# ─────────────────────────────────────────

async def _encerrar_truco_timeout(canal_id: int, motivo: str):
    jogos.pop(canal_id, None)
    try:
        canal = None
        for guild in _bot_ref_truco.guilds:
            canal = guild.get_channel(canal_id)
            if canal:
                break
        if canal:
            await canal.send("⏰ Jogo de **Truco** encerrado por inatividade (10 min).")
    except Exception as e:
        print(f"[TIMEOUT TRUCO] {e}")

_bot_ref_truco = None


class TrucoCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        global _bot_ref_truco
        _bot_ref_truco = bot


    @app_commands.command(name="truco", description="Cria uma partida de Truco Paulista")
    @app_commands.describe(modo="Modo de jogo: 1v1 ou 2v2")
    @app_commands.choices(modo=[
        app_commands.Choice(name="1v1 (dois jogadores)", value="1v1"),
        app_commands.Choice(name="2v2 (quatro jogadores)", value="2v2"),
    ])
    async def cmd_truco(interaction: discord.Interaction, modo: str = "1v1"):
        canal_id = interaction.channel_id
        if not checar_canal(canal_id):
            await interaction.response.send_message("🎰 Os jogos só funcionam no canal do cassino!", ephemeral=True)
            return
        if canal_id in jogos:
            await interaction.response.send_message("Já tem um jogo nesse canal! Use `/encerrar` para cancelar.", ephemeral=True)
            return

        jogo = JogoTruco(canal_id=canal_id, modo=modo)
        jogo.equipe1.jogadores.append(interaction.user)
        jogos[canal_id] = jogo

        max_j = 2 if modo == "1v1" else 4
        view = EntrarView(jogo)
        embed = discord.Embed(
            title="🃏 Truco Paulista",
            description=(
                f"**{interaction.user.display_name}** criou um jogo de truco!\n"
                f"Modo: **{modo}** ({max_j} jogadores)\n\n"
                f"Clique em **Entrar no jogo** para participar!\n"
                f"Jogadores: 1/{max_j}"
            ),
            color=0x2B5219
        )
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="truco_pedir", description="Pede truco ou aumenta o valor da rodada")
    async def cmd_pedir_truco(interaction: discord.Interaction):
        canal_id = interaction.channel_id
        jogo = jogos.get(canal_id)
        if not jogo or jogo.estado != EstadoTruco.JOGANDO:
            await interaction.response.send_message("Não tem jogo em andamento aqui.", ephemeral=True)
            return

        user = interaction.user
        minha_eq = get_equipe(jogo, user.id)
        if not minha_eq:
            await interaction.response.send_message("Você não está nesse jogo.", ephemeral=True)
            return

        escala = [1, 3, 6, 9, 12]
        idx = escala.index(jogo.valor_rodada) if jogo.valor_rodada in escala else 0
        if idx >= len(escala) - 1:
            await interaction.response.send_message("Rodada já está no valor máximo (12)!", ephemeral=True)
            return

        nomes = {3: "Truco!", 6: "Seis!", 9: "Nove!", 12: "Doze!"}
        prox = escala[idx + 1]
        grito = nomes.get(prox, f"{prox}!")

        jogo.truco_por = user.id
        jogo.estado = EstadoTruco.TRUCO_PEDIDO
        adv = get_adversario(jogo, user.id)
        view = TrucoView(jogo, user.id)
        await interaction.response.send_message(
            f"😤 **{user.display_name}** gritou **{grito}**\n"
            f"**{adv.nome}**, aceita, corre ou aumenta?",
            view=view
        )

    @app_commands.command(name="minha_mao", description="Veja suas cartas (envia por DM)")
    async def cmd_minha_mao(interaction: discord.Interaction):
        canal_id = interaction.channel_id
        jogo = jogos.get(canal_id)
        if not jogo:
            await interaction.response.send_message("Não tem jogo aqui.", ephemeral=True)
            return
        cartas = jogo.maos.get(interaction.user.id)
        if not cartas:
            await interaction.response.send_message("Você não tem cartas.", ephemeral=True)
            return
        txt = "🃏 **Suas cartas:** " + "  ".join(formatar_carta(c) for c in cartas)
        await interaction.response.send_message(txt, ephemeral=True)

    @app_commands.command(name="placar", description="Mostra o placar atual")
    async def cmd_placar(interaction: discord.Interaction):
        canal_id = interaction.channel_id
        jogo = jogos.get(canal_id)
        if not jogo:
            await interaction.response.send_message("Não tem jogo aqui.", ephemeral=True)
            return
        embed = embed_mesa(jogo, interaction.channel)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="encerrar", description="Encerra o jogo atual")
    async def cmd_encerrar(interaction: discord.Interaction):
        canal_id = interaction.channel_id
        jogo = jogos.get(canal_id)
        if not jogo:
            await interaction.response.send_message("Não tem jogo aqui.", ephemeral=True)
            return
        todos = jogo.equipe1.jogadores + jogo.equipe2.jogadores
        if interaction.user not in todos:
            await interaction.response.send_message("Você não está nesse jogo.", ephemeral=True)
            return
        jogos.pop(canal_id, None)
        await interaction.response.send_message("❌ Jogo encerrado.")




async def setup(bot: commands.Bot):
    await bot.add_cog(TrucoCog(bot))
