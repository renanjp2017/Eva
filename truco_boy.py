import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional

# ─────────────────────────────────────────
#  CONFIGURAÇÃO
# ─────────────────────────────────────────
TOKEN = "SEU_TOKEN_AQUI"

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

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
    atual = jogador_atual(jogo)
    cartas = jogo.maos.get(atual.id, [])
    if not cartas:
        await canal.send(f"{atual.mention} não tem mais cartas!")
        return

    embed = embed_mesa(jogo, canal)
    view = JogarCartaView(jogo, atual.id)
    await canal.send(
        f"{atual.mention} é sua vez! Escolha uma carta:",
        embed=embed,
        view=view
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
@bot.tree.command(name="truco", description="Cria uma partida de Truco Paulista")
@app_commands.describe(modo="Modo de jogo: 1v1 ou 2v2")
@app_commands.choices(modo=[
    app_commands.Choice(name="1v1 (dois jogadores)", value="1v1"),
    app_commands.Choice(name="2v2 (quatro jogadores)", value="2v2"),
])
async def cmd_truco(interaction: discord.Interaction, modo: str = "1v1"):
    canal_id = interaction.channel_id
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


@bot.tree.command(name="truco_pedir", description="Pede truco ou aumenta o valor da rodada")
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


@bot.tree.command(name="minha_mao", description="Veja suas cartas (envia por DM)")
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


@bot.tree.command(name="placar", description="Mostra o placar atual")
async def cmd_placar(interaction: discord.Interaction):
    canal_id = interaction.channel_id
    jogo = jogos.get(canal_id)
    if not jogo:
        await interaction.response.send_message("Não tem jogo aqui.", ephemeral=True)
        return
    embed = embed_mesa(jogo, interaction.channel)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="encerrar", description="Encerra o jogo atual")
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


# ─────────────────────────────────────────
#  BLACKJACK - 21
# ─────────────────────────────────────────
FICHAS_INICIAIS   = 500
APOSTA_MINIMA     = 10
APOSTA_MAXIMA     = 500

NAIPES_BJ  = ["♠", "♥", "♦", "♣"]
NUMEROS_BJ = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]

fichas: dict[int, int] = {}   # user_id -> fichas
mesas_bj: dict[int, "MesaBJ"] = {}  # canal_id -> mesa

def get_fichas(user_id: int) -> int:
    return fichas.get(user_id, FICHAS_INICIAIS)

def set_fichas(user_id: int, valor: int):
    fichas[user_id] = max(0, valor)

def gerar_baralho_bj():
    b = [f"{n}{s}" for n in NUMEROS_BJ for s in NAIPES_BJ]
    random.shuffle(b)
    return b

def valor_carta_bj(carta: str) -> int:
    n = carta[:-1]
    if n in ["J", "Q", "K"]:
        return 10
    if n == "A":
        return 11
    return int(n)

def calcular_mao(cartas: list[str]) -> int:
    total = sum(valor_carta_bj(c) for c in cartas)
    ases  = sum(1 for c in cartas if c[:-1] == "A")
    while total > 21 and ases:
        total -= 10
        ases  -= 1
    return total

def formatar_mao(cartas: list[str], esconder_segunda: bool = False) -> str:
    if esconder_segunda and len(cartas) >= 2:
        return f"`{cartas[0]}` `??`"
    return "  ".join(f"`{c}`" for c in cartas)

@dataclass
class JogadorBJ:
    user: discord.Member
    mao: list = field(default_factory=list)
    aposta: int = 0
    parou: bool = False
    estourou: bool = False
    blackjack: bool = False

@dataclass
class MesaBJ:
    canal_id: int
    estado: str = "aguardando"   # aguardando | apostando | jogando | fim
    jogadores: list = field(default_factory=list)  # [JogadorBJ]
    dealer_mao: list = field(default_factory=list)
    baralho: list = field(default_factory=list)
    iniciador_id: int = 0

    def get_jogador(self, user_id: int) -> Optional[JogadorBJ]:
        for j in self.jogadores:
            if j.user.id == user_id:
                return j
        return None

    def todos_terminaram(self) -> bool:
        return all(j.parou or j.estourou or j.blackjack for j in self.jogadores)

    def proximo_jogador(self) -> Optional[JogadorBJ]:
        for j in self.jogadores:
            if not j.parou and not j.estourou and not j.blackjack:
                return j
        return None


def embed_mesa_bj(mesa: MesaBJ, revelar_dealer: bool = False) -> discord.Embed:
    e = discord.Embed(title="🃏 Blackjack — 21", color=0x1a1a2e)

    dealer_val = calcular_mao(mesa.dealer_mao)
    if revelar_dealer:
        e.add_field(
            name=f"🏦 Dealer — {dealer_val} pontos",
            value=formatar_mao(mesa.dealer_mao),
            inline=False
        )
    else:
        e.add_field(
            name="🏦 Dealer",
            value=formatar_mao(mesa.dealer_mao, esconder_segunda=True),
            inline=False
        )

    for j in mesa.jogadores:
        val  = calcular_mao(j.mao)
        nome = j.user.display_name
        status = ""
        if j.blackjack:
            status = " 🌟 BLACKJACK!"
        elif j.estourou:
            status = " 💥 ESTOUROU"
        elif j.parou:
            status = " ✋ Parou"
        e.add_field(
            name=f"{nome} — {val} pts{status} (aposta: {j.aposta} 🪙)",
            value=formatar_mao(j.mao),
            inline=False
        )
    return e


class ApostaModal(discord.ui.Modal, title="Sua aposta"):
    aposta = discord.ui.TextInput(
        label="Quantas fichas?",
        placeholder=f"Mínimo {APOSTA_MINIMA}, máximo {APOSTA_MAXIMA}",
        min_length=1,
        max_length=4
    )

    def __init__(self, mesa: MesaBJ):
        super().__init__()
        self.mesa = mesa

    async def on_submit(self, interaction: discord.Interaction):
        mesa = self.mesa
        user = interaction.user
        jog  = mesa.get_jogador(user.id)

        if not jog:
            await interaction.response.send_message("Você não está nessa mesa.", ephemeral=True)
            return
        if jog.aposta > 0:
            await interaction.response.send_message("Você já apostou!", ephemeral=True)
            return

        try:
            valor = int(self.aposta.value)
        except ValueError:
            await interaction.response.send_message("Valor inválido.", ephemeral=True)
            return

        saldo = get_fichas(user.id)
        valor = max(APOSTA_MINIMA, min(valor, APOSTA_MAXIMA, saldo))
        jog.aposta = valor

        todos_apostaram = all(j.aposta > 0 for j in mesa.jogadores)
        await interaction.response.send_message(
            f"✅ **{user.display_name}** apostou **{valor} 🪙**"
            + (" — todos apostaram, iniciando!" if todos_apostaram else ""),
        )

        if todos_apostaram:
            await iniciar_rodada_bj(interaction.channel, mesa)


class ApostarView(discord.ui.View):
    def __init__(self, mesa: MesaBJ):
        super().__init__(timeout=60)
        self.mesa = mesa

    @discord.ui.button(label="Apostar", style=discord.ButtonStyle.primary, emoji="🪙")
    async def apostar(self, interaction: discord.Interaction, button: discord.ui.Button):
        mesa = self.mesa
        jog  = mesa.get_jogador(interaction.user.id)
        if not jog:
            await interaction.response.send_message("Você não está nessa mesa.", ephemeral=True)
            return
        if jog.aposta > 0:
            await interaction.response.send_message("Você já apostou!", ephemeral=True)
            return
        await interaction.response.send_modal(ApostaModal(mesa))


class JogarBJView(discord.ui.View):
    def __init__(self, mesa: MesaBJ, jogador: JogadorBJ):
        super().__init__(timeout=60)
        self.mesa    = mesa
        self.jogador = jogador

    @discord.ui.button(label="Pedir carta", style=discord.ButtonStyle.success, emoji="🃏")
    async def pedir(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.jogador.user.id:
            await interaction.response.send_message("Não é sua vez!", ephemeral=True)
            return
        await interaction.response.defer()
        self.stop()
        mesa = self.mesa
        jog  = self.jogador
        carta = mesa.baralho.pop()
        jog.mao.append(carta)
        val = calcular_mao(jog.mao)

        if val > 21:
            jog.estourou = True
            await interaction.channel.send(
                f"💥 **{jog.user.display_name}** pegou `{carta}` e estourou com **{val}**!",
                embed=embed_mesa_bj(mesa)
            )
            await avancar_turno_bj(interaction.channel, mesa)
        elif val == 21:
            jog.parou = True
            await interaction.channel.send(
                f"🌟 **{jog.user.display_name}** atingiu **21**!",
                embed=embed_mesa_bj(mesa)
            )
            await avancar_turno_bj(interaction.channel, mesa)
        else:
            await interaction.channel.send(
                f"🃏 **{jog.user.display_name}** pegou `{carta}` — total: **{val}**",
                embed=embed_mesa_bj(mesa)
            )
            await pedir_turno_bj(interaction.channel, mesa, jog)

    @discord.ui.button(label="Parar", style=discord.ButtonStyle.danger, emoji="✋")
    async def parar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.jogador.user.id:
            await interaction.response.send_message("Não é sua vez!", ephemeral=True)
            return
        await interaction.response.defer()
        self.stop()
        self.jogador.parou = True
        val = calcular_mao(self.jogador.mao)
        await interaction.channel.send(
            f"✋ **{self.jogador.user.display_name}** parou com **{val}**."
        )
        await avancar_turno_bj(interaction.channel, self.mesa)


async def iniciar_rodada_bj(canal, mesa: MesaBJ):
    mesa.baralho    = gerar_baralho_bj()
    mesa.dealer_mao = []
    mesa.estado     = "jogando"

    # Distribui 2 cartas pra cada jogador e dealer
    for _ in range(2):
        for j in mesa.jogadores:
            j.mao.append(mesa.baralho.pop())
        mesa.dealer_mao.append(mesa.baralho.pop())

    # Desconta apostas
    for j in mesa.jogadores:
        set_fichas(j.user.id, get_fichas(j.user.id) - j.aposta)

    # Verifica blackjacks naturais
    for j in mesa.jogadores:
        if calcular_mao(j.mao) == 21:
            j.blackjack = True

    await canal.send("🃏 **Cartas distribuídas!**", embed=embed_mesa_bj(mesa))

    # Primeiro jogador que não tem blackjack
    proximo = mesa.proximo_jogador()
    if proximo:
        await pedir_turno_bj(canal, mesa, proximo)
    else:
        await vez_dealer_bj(canal, mesa)


async def pedir_turno_bj(canal, mesa: MesaBJ, jogador: JogadorBJ):
    view = JogarBJView(mesa, jogador)
    val  = calcular_mao(jogador.mao)
    await canal.send(
        f"🎯 **{jogador.user.mention}** é sua vez! Você tem **{val}** pontos.\n"
        f"Aposta: **{jogador.aposta} 🪙**",
        view=view
    )


async def avancar_turno_bj(canal, mesa: MesaBJ):
    proximo = mesa.proximo_jogador()
    if proximo:
        await pedir_turno_bj(canal, mesa, proximo)
    else:
        await vez_dealer_bj(canal, mesa)


async def vez_dealer_bj(canal, mesa: MesaBJ):
    await canal.send("🏦 **Vez do dealer!**")
    await asyncio.sleep(1)

    # Dealer puxa até 17+
    while calcular_mao(mesa.dealer_mao) < 17:
        carta = mesa.baralho.pop()
        mesa.dealer_mao.append(carta)
        val   = calcular_mao(mesa.dealer_mao)
        await canal.send(f"🏦 Dealer pegou `{carta}` — total: **{val}**")
        await asyncio.sleep(1)

    dealer_val = calcular_mao(mesa.dealer_mao)
    dealer_estourou = dealer_val > 21

    resultado_txt = "**Resultado final:**\n"
    for j in mesa.jogadores:
        val   = calcular_mao(j.mao)
        nome  = j.user.display_name
        ganho = 0

        if j.estourou:
            resultado_txt += f"💥 {nome} — estourou. Perdeu **{j.aposta} 🪙**\n"
        elif j.blackjack and calcular_mao(mesa.dealer_mao) != 21:
            ganho = int(j.aposta * 2.5)
            set_fichas(j.user.id, get_fichas(j.user.id) + ganho)
            resultado_txt += f"🌟 {nome} — Blackjack! Ganhou **{ganho} 🪙**\n"
        elif dealer_estourou:
            ganho = j.aposta * 2
            set_fichas(j.user.id, get_fichas(j.user.id) + ganho)
            resultado_txt += f"🎉 {nome} — dealer estourou! Ganhou **{ganho} 🪙**\n"
        elif val > dealer_val:
            ganho = j.aposta * 2
            set_fichas(j.user.id, get_fichas(j.user.id) + ganho)
            resultado_txt += f"🎉 {nome} — {val} vs {dealer_val}. Ganhou **{ganho} 🪙**\n"
        elif val == dealer_val:
            set_fichas(j.user.id, get_fichas(j.user.id) + j.aposta)
            resultado_txt += f"🤝 {nome} — empate! Devolveu **{j.aposta} 🪙**\n"
        else:
            resultado_txt += f"😔 {nome} — {val} vs {dealer_val}. Perdeu **{j.aposta} 🪙**\n"

        saldo = get_fichas(j.user.id)
        resultado_txt += f"   Saldo: **{saldo} 🪙**\n"

    embed = embed_mesa_bj(mesa, revelar_dealer=True)
    await canal.send(resultado_txt, embed=embed)
    mesas_bj.pop(mesa.canal_id, None)


# ─── COMANDOS BLACKJACK ───────────────────

class EntrarBJView(discord.ui.View):
    def __init__(self, mesa: MesaBJ):
        super().__init__(timeout=60)
        self.mesa = mesa

    @discord.ui.button(label="Entrar", style=discord.ButtonStyle.success, emoji="🃏")
    async def entrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        mesa = self.mesa
        user = interaction.user
        if mesa.get_jogador(user.id):
            await interaction.response.send_message("Você já está na mesa!", ephemeral=True)
            return
        if len(mesa.jogadores) >= 6:
            await interaction.response.send_message("Mesa cheia! (máx 6)", ephemeral=True)
            return
        mesa.jogadores.append(JogadorBJ(user=user))
        await interaction.response.send_message(f"✅ **{user.display_name}** entrou na mesa! ({len(mesa.jogadores)} jogadores)")

    @discord.ui.button(label="Iniciar", style=discord.ButtonStyle.primary, emoji="▶️")
    async def iniciar(self, interaction: discord.Interaction, button: discord.ui.Button):
        mesa = self.mesa
        if interaction.user.id != mesa.iniciador_id:
            await interaction.response.send_message("Só quem criou pode iniciar.", ephemeral=True)
            return
        if len(mesa.jogadores) < 1:
            await interaction.response.send_message("Precisa de pelo menos 1 jogador.", ephemeral=True)
            return
        mesa.estado = "apostando"
        self.stop()
        view = ApostarView(mesa)
        nomes = ", ".join(j.user.display_name for j in mesa.jogadores)
        saldos = "\n".join(f"**{j.user.display_name}**: {get_fichas(j.user.id)} 🪙" for j in mesa.jogadores)
        await interaction.response.send_message(
            f"🃏 **Mesa iniciada!** Jogadores: {nomes}\n\n{saldos}\n\nFaça suas apostas!",
            view=view
        )


@bot.tree.command(name="21", description="Inicia uma mesa de Blackjack (21)")
async def cmd_21(interaction: discord.Interaction):
    canal_id = interaction.channel_id
    if canal_id in mesas_bj:
        await interaction.response.send_message("Já tem uma mesa aqui! Use `/21_encerrar` para cancelar.", ephemeral=True)
        return

    mesa = MesaBJ(canal_id=canal_id, iniciador_id=interaction.user.id)
    mesa.jogadores.append(JogadorBJ(user=interaction.user))
    mesas_bj[canal_id] = mesa

    view = EntrarBJView(mesa)
    embed = discord.Embed(
        title="🃏 Blackjack — 21",
        description=(
            f"**{interaction.user.display_name}** abriu uma mesa de 21!\n\n"
            f"Clique em **Entrar** para participar (até 6 jogadores).\n"
            f"Quando todos estiverem prontos, clique em **Iniciar**.\n\n"
            f"Fichas iniciais: **{FICHAS_INICIAIS} 🪙**"
        ),
        color=0x1a1a2e
    )
    await interaction.response.send_message(embed=embed, view=view)


@bot.tree.command(name="fichas", description="Veja seu saldo de fichas")
async def cmd_fichas(interaction: discord.Interaction):
    saldo = get_fichas(interaction.user.id)
    await interaction.response.send_message(
        f"🪙 **{interaction.user.display_name}** tem **{saldo} fichas**.",
        ephemeral=True
    )


@bot.tree.command(name="21_encerrar", description="Encerra a mesa de blackjack atual")
async def cmd_21_encerrar(interaction: discord.Interaction):
    canal_id = interaction.channel_id
    mesa = mesas_bj.get(canal_id)
    if not mesa:
        await interaction.response.send_message("Não tem mesa aqui.", ephemeral=True)
        return
    if interaction.user.id != mesa.iniciador_id:
        await interaction.response.send_message("Só quem criou pode encerrar.", ephemeral=True)
        return
    mesas_bj.pop(canal_id, None)
    await interaction.response.send_message("❌ Mesa encerrada.")


# ─────────────────────────────────────────
#  EVENTOS
# ─────────────────────────────────────────
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ {bot.user} online! Comandos sincronizados.")


bot.run(TOKEN)
