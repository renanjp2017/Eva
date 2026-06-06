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
import os
TOKEN = os.environ.get("DISCORD_TOKEN", "")

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
#  POKER - TEXAS HOLD'EM
# ─────────────────────────────────────────
from itertools import combinations

POKER_BIG_BLIND   = 20
POKER_SMALL_BLIND = 10
POKER_MAX_JOGADORES = 9

mesas_poker: dict[int, "MesaPoker"] = {}

# Naipes e números compartilhados com BJ mas redefinidos pra clareza
P_NAIPES  = ["♠", "♥", "♦", "♣"]
P_NUMEROS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
P_RANK    = {n: i for i, n in enumerate(P_NUMEROS)}  # 2=0 ... A=12

def gerar_baralho_poker():
    b = [f"{n}{s}" for n in P_NUMEROS for s in P_NAIPES]
    random.shuffle(b)
    return b

def rank_carta(carta: str) -> int:
    return P_RANK[carta[:-1]]

# ── Avaliação de mãos ──────────────────────────────────────────────────────
NOMES_MAO = [
    "Carta Alta", "Par", "Dois Pares", "Trinca",
    "Sequência", "Flush", "Full House", "Quadra",
    "Straight Flush", "Royal Flush"
]

def avaliar_5(cartas: list[str]) -> tuple:
    """Retorna (categoria, [ranks desc]) para 5 cartas."""
    ranks  = sorted([rank_carta(c) for c in cartas], reverse=True)
    naipes = [c[-1] for c in cartas]
    flush  = len(set(naipes)) == 1
    seq    = (ranks[0] - ranks[4] == 4 and len(set(ranks)) == 5)
    # Sequência A-2-3-4-5
    roda   = ranks == [12, 3, 2, 1, 0]
    if roda:
        ranks = [3, 2, 1, 0, -1]
        seq   = True

    contagem = {}
    for r in ranks:
        contagem[r] = contagem.get(r, 0) + 1
    grupos = sorted(contagem.items(), key=lambda x: (x[1], x[0]), reverse=True)
    freq   = [g[1] for g in grupos]
    kickers = [g[0] for g in grupos]

    if flush and seq:
        cat = 9 if ranks[0] == 12 and not roda else 8
    elif freq[0] == 4:
        cat = 7
    elif freq[:2] == [3, 2]:
        cat = 6
    elif flush:
        cat = 5
    elif seq:
        cat = 4
    elif freq[0] == 3:
        cat = 3
    elif freq[:2] == [2, 2]:
        cat = 2
    elif freq[0] == 2:
        cat = 1
    else:
        cat = 0

    return (cat, kickers)

def melhor_mao(cartas: list[str]) -> tuple:
    """Melhor combinação de 5 entre até 7 cartas."""
    melhor = None
    for combo in combinations(cartas, 5):
        val = avaliar_5(list(combo))
        if melhor is None or val > melhor:
            melhor = val
    return melhor

def nome_mao(cartas: list[str]) -> str:
    cat, _ = melhor_mao(cartas)
    return NOMES_MAO[cat]

# ── Dataclasses ────────────────────────────────────────────────────────────
@dataclass
class JogadorPoker:
    user: discord.Member
    mao: list = field(default_factory=list)
    fichas_mesa: int = 0    # fichas na mesa atual
    aposta_rodada: int = 0  # apostado na rodada atual
    all_in: bool = False
    foldou: bool = False
    ativo: bool = True

    @property
    def pode_agir(self):
        return self.ativo and not self.foldou and not self.all_in

@dataclass
class MesaPoker:
    canal_id: int
    iniciador_id: int
    estado: str = "aguardando"  # aguardando|pre_flop|flop|turn|river|showdown
    jogadores: list = field(default_factory=list)
    baralho: list = field(default_factory=list)
    comunitarias: list = field(default_factory=list)
    pote: int = 0
    aposta_atual: int = 0
    vez_idx: int = 0
    dealer_idx: int = 0
    rodada_apostas: int = 0  # quantos já agiram nessa rodada

    def get_jogador(self, user_id: int) -> Optional[JogadorPoker]:
        for j in self.jogadores:
            if j.user.id == user_id:
                return j
        return None

    def ativos(self) -> list:
        return [j for j in self.jogadores if not j.foldou and j.ativo]

    def podem_agir(self) -> list:
        return [j for j in self.ativos() if not j.all_in]

    def jogador_atual(self) -> Optional[JogadorPoker]:
        ativos = self.ativos()
        if not ativos:
            return None
        for _ in range(len(self.jogadores)):
            j = self.jogadores[self.vez_idx % len(self.jogadores)]
            if j.pode_agir:
                return j
            self.vez_idx += 1
        return None

    def avancar_vez(self):
        self.vez_idx = (self.vez_idx + 1) % len(self.jogadores)

# ── Embed da mesa ──────────────────────────────────────────────────────────
def embed_poker(mesa: MesaPoker, revelar: bool = False) -> discord.Embed:
    e = discord.Embed(title="🃏 Texas Hold'em", color=0x0d1b2a)

    com = "  ".join(f"`{c}`" for c in mesa.comunitarias) if mesa.comunitarias else "_nenhuma ainda_"
    e.add_field(name=f"🎴 Comunitárias | Pote: {mesa.pote} 🪙", value=com, inline=False)

    fases = {"pre_flop": "Pré-Flop", "flop": "Flop", "turn": "Turn", "river": "River", "showdown": "Showdown"}
    e.add_field(name="📍 Fase", value=fases.get(mesa.estado, mesa.estado), inline=True)
    e.add_field(name="💰 Aposta atual", value=f"{mesa.aposta_atual} 🪙", inline=True)

    for j in mesa.jogadores:
        saldo = get_fichas(j.user.id)
        status = ""
        if j.foldou:       status = " 🚫 Fold"
        elif j.all_in:     status = " 💥 All-in"
        mao_txt = "  ".join(f"`{c}`" for c in j.mao) if (revelar and not j.foldou) else "`??` `??`"
        e.add_field(
            name=f"{j.user.display_name}{status} — {saldo} 🪙 (aposta: {j.aposta_rodada})",
            value=mao_txt,
            inline=False
        )
    return e

# ── Lógica do jogo ─────────────────────────────────────────────────────────
async def iniciar_partida_poker(canal, mesa: MesaPoker):
    mesa.estado  = "pre_flop"
    mesa.baralho = gerar_baralho_poker()
    mesa.comunitarias = []
    mesa.pote    = 0
    mesa.aposta_atual = POKER_BIG_BLIND

    # Zera estado dos jogadores
    for j in mesa.jogadores:
        j.mao           = []
        j.aposta_rodada = 0
        j.all_in        = False
        j.foldou        = False
        j.ativo         = True

    n = len(mesa.jogadores)
    mesa.dealer_idx = (mesa.dealer_idx + 1) % n
    sb_idx = (mesa.dealer_idx + 1) % n
    bb_idx = (mesa.dealer_idx + 2) % n

    # Distribui cartas
    for _ in range(2):
        for j in mesa.jogadores:
            j.mao.append(mesa.baralho.pop())

    # Envia cartas por DM
    for j in mesa.jogadores:
        try:
            await j.user.send(
                f"🃏 **Suas cartas no poker:**\n"
                f"`{j.mao[0]}`  `{j.mao[1]}`\n"
                f"Fichas: **{get_fichas(j.user.id)} 🪙**"
            )
        except Exception:
            pass

    # Small e big blind
    sb = mesa.jogadores[sb_idx]
    bb = mesa.jogadores[bb_idx]
    _cobrar(mesa, sb, POKER_SMALL_BLIND)
    _cobrar(mesa, bb, POKER_BIG_BLIND)

    dealer_nome = mesa.jogadores[mesa.dealer_idx].user.display_name
    await canal.send(
        f"🃏 **Nova partida de Texas Hold'em!**\n"
        f"Dealer: **{dealer_nome}** | SB: **{sb.user.display_name}** ({POKER_SMALL_BLIND}🪙) | BB: **{bb.user.display_name}** ({POKER_BIG_BLIND}🪙)\n"
        f"Cartas enviadas por DM!",
        embed=embed_poker(mesa)
    )

    # Primeiro a agir: após o BB
    mesa.vez_idx     = (bb_idx + 1) % n
    mesa.rodada_apostas = 0
    await pedir_acao_poker(canal, mesa)


def _cobrar(mesa: MesaPoker, jogador: JogadorPoker, valor: int):
    saldo = get_fichas(jogador.user.id)
    real  = min(valor, saldo)
    set_fichas(jogador.user.id, saldo - real)
    jogador.aposta_rodada += real
    mesa.pote             += real
    if get_fichas(jogador.user.id) == 0:
        jogador.all_in = True
    if real > mesa.aposta_atual:
        mesa.aposta_atual = real


async def pedir_acao_poker(canal, mesa: MesaPoker):
    # Se só um ativo, ele ganha
    if len(mesa.ativos()) == 1:
        await showdown_poker(canal, mesa)
        return

    # Se todos fizeram ação ou só all-ins sobraram, avança fase
    podem = mesa.podem_agir()
    todos_igualaram = all(j.aposta_rodada == mesa.aposta_atual for j in podem)
    if todos_igualaram and mesa.rodada_apostas >= len(podem):
        await avancar_fase_poker(canal, mesa)
        return

    jogador = mesa.jogador_atual()
    if not jogador:
        await avancar_fase_poker(canal, mesa)
        return

    diff = mesa.aposta_atual - jogador.aposta_rodada
    saldo = get_fichas(jogador.user.id)
    view  = AcaoPokerView(mesa, jogador, diff, saldo)
    await canal.send(
        f"🎯 **{jogador.user.mention}** é sua vez!\n Pote: **{mesa.pote} 🪙** | Aposta atual: **{mesa.aposta_atual} 🪙** | Suas fichas: **{saldo} 🪙**"
        + (f" | Para pagar: **{diff} 🪙**" if diff > 0 else " | Pode dar Check"),
        embed=embed_poker(mesa),
        view=view
    )


async def avancar_fase_poker(canal, mesa: MesaPoker):
    # Zera apostas da rodada
    for j in mesa.jogadores:
        j.aposta_rodada = 0
    mesa.aposta_atual   = 0
    mesa.rodada_apostas = 0
    # Primeiro a agir após dealer
    n = len(mesa.jogadores)
    mesa.vez_idx = (mesa.dealer_idx + 1) % n

    if mesa.estado == "pre_flop":
        mesa.estado = "flop"
        mesa.comunitarias += [mesa.baralho.pop() for _ in range(3)]
        await canal.send("🎴 **Flop!**", embed=embed_poker(mesa))
    elif mesa.estado == "flop":
        mesa.estado = "turn"
        mesa.comunitarias.append(mesa.baralho.pop())
        await canal.send("🎴 **Turn!**", embed=embed_poker(mesa))
    elif mesa.estado == "turn":
        mesa.estado = "river"
        mesa.comunitarias.append(mesa.baralho.pop())
        await canal.send("🎴 **River!**", embed=embed_poker(mesa))
    elif mesa.estado in ("river", "showdown"):
        await showdown_poker(canal, mesa)
        return

    await pedir_acao_poker(canal, mesa)


async def showdown_poker(canal, mesa: MesaPoker):
    mesa.estado = "showdown"
    ativos = mesa.ativos()

    if len(ativos) == 1:
        vencedor = ativos[0]
        set_fichas(vencedor.user.id, get_fichas(vencedor.user.id) + mesa.pote)
        await canal.send(
            f"🏆 **{vencedor.user.display_name}** ganhou o pote de **{mesa.pote} 🪙** (todos deram fold)!",
            embed=embed_poker(mesa, revelar=False)
        )
    else:
        resultados = []
        for j in ativos:
            todas = j.mao + mesa.comunitarias
            val   = melhor_mao(todas)
            nome  = nome_mao(todas)
            resultados.append((j, val, nome))

        resultados.sort(key=lambda x: x[1], reverse=True)
        melhor_val = resultados[0][1]
        vencedores = [r for r in resultados if r[1] == melhor_val]
        parte = mesa.pote // len(vencedores)

        txt = "🏆 **Showdown!**\n"
        for j, val, nome in resultados:
            cartas_txt = "  ".join(f"`{c}`" for c in j.mao)
            txt += f"**{j.user.display_name}**: {cartas_txt} — _{nome}_\n"

        txt += "\n"
        for j, val, nome in vencedores:
            set_fichas(j.user.id, get_fichas(j.user.id) + parte)
            txt += f"🎉 **{j.user.display_name}** ganhou **{parte} 🪙**!\n"

        await canal.send(txt, embed=embed_poker(mesa, revelar=True))

    # Pergunta se quer jogar de novo
    view = NovaPartidaView(mesa)
    await canal.send("Quer jogar de novo?", view=view)


# ── Views de ação ──────────────────────────────────────────────────────────
class ApostaPokerModal(discord.ui.Modal, title="Raise — quanto quer apostar?"):
    valor = discord.ui.TextInput(label="Valor total da aposta", placeholder="Ex: 100")

    def __init__(self, mesa: MesaPoker, jogador: JogadorPoker):
        super().__init__()
        self.mesa    = mesa
        self.jogador = jogador

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.valor.value)
        except ValueError:
            await interaction.response.send_message("Valor inválido.", ephemeral=True)
            return

        mesa    = self.mesa
        jogador = self.jogador
        saldo   = get_fichas(jogador.user.id)
        diff    = mesa.aposta_atual - jogador.aposta_rodada
        minimo  = diff + POKER_BIG_BLIND

        if val < minimo:
            await interaction.response.send_message(f"Mínimo para raise: {minimo} 🪙", ephemeral=True)
            return

        real = min(val, saldo)
        _cobrar(mesa, jogador, real)
        mesa.aposta_atual   = jogador.aposta_rodada
        mesa.rodada_apostas = 1  # reset — todos precisam agir novamente
        mesa.avancar_vez()

        await interaction.response.send_message(
            f"⬆️ **{jogador.user.display_name}** fez raise para **{jogador.aposta_rodada} 🪙**!"
        )
        await pedir_acao_poker(interaction.channel, mesa)


class AcaoPokerView(discord.ui.View):
    def __init__(self, mesa: MesaPoker, jogador: JogadorPoker, diff: int, saldo: int):
        super().__init__(timeout=60)
        self.mesa    = mesa
        self.jogador = jogador
        self.diff    = diff
        self.saldo   = saldo

        # Ajusta botões dinamicamente
        if diff == 0:
            self.pagar.label = "Check ✓"
        else:
            self.pagar.label = f"Call ({diff} 🪙)"
        if saldo == 0 or diff >= saldo:
            self.raise_btn.disabled = True

    @discord.ui.button(label="Call", style=discord.ButtonStyle.success)
    async def pagar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.jogador.user.id:
            await interaction.response.send_message("Não é sua vez!", ephemeral=True)
            return
        await interaction.response.defer()
        self.stop()
        mesa    = self.mesa
        jogador = self.jogador
        diff    = self.diff

        if diff == 0:
            await interaction.channel.send(f"✓ **{jogador.user.display_name}** deu check.")
        else:
            real = min(diff, get_fichas(jogador.user.id))
            _cobrar(mesa, jogador, real)
            await interaction.channel.send(f"📞 **{jogador.user.display_name}** pagou **{real} 🪙**.")

        mesa.rodada_apostas += 1
        mesa.avancar_vez()
        await pedir_acao_poker(interaction.channel, mesa)

    @discord.ui.button(label="Raise", style=discord.ButtonStyle.primary, emoji="⬆️")
    async def raise_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.jogador.user.id:
            await interaction.response.send_message("Não é sua vez!", ephemeral=True)
            return
        self.stop()
        await interaction.response.send_modal(ApostaPokerModal(self.mesa, self.jogador))

    @discord.ui.button(label="All-in 💥", style=discord.ButtonStyle.danger)
    async def all_in(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.jogador.user.id:
            await interaction.response.send_message("Não é sua vez!", ephemeral=True)
            return
        await interaction.response.defer()
        self.stop()
        mesa    = self.mesa
        jogador = self.jogador
        saldo   = get_fichas(jogador.user.id)
        _cobrar(mesa, jogador, saldo)
        if jogador.aposta_rodada > mesa.aposta_atual:
            mesa.aposta_atual   = jogador.aposta_rodada
            mesa.rodada_apostas = 1
        else:
            mesa.rodada_apostas += 1
        await interaction.channel.send(f"💥 **{jogador.user.display_name}** foi ALL-IN com **{saldo} 🪙**!")
        mesa.avancar_vez()
        await pedir_acao_poker(interaction.channel, mesa)

    @discord.ui.button(label="Fold 🚫", style=discord.ButtonStyle.secondary)
    async def fold(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.jogador.user.id:
            await interaction.response.send_message("Não é sua vez!", ephemeral=True)
            return
        await interaction.response.defer()
        self.stop()
        self.jogador.foldou = True
        mesa = self.mesa
        mesa.rodada_apostas += 1
        await interaction.channel.send(f"🚫 **{self.jogador.user.display_name}** deu fold.")
        mesa.avancar_vez()
        await pedir_acao_poker(interaction.channel, mesa)


class NovaPartidaView(discord.ui.View):
    def __init__(self, mesa: MesaPoker):
        super().__init__(timeout=60)
        self.mesa = mesa

    @discord.ui.button(label="Jogar de novo", style=discord.ButtonStyle.success, emoji="🔄")
    async def jogar_novo(self, interaction: discord.Interaction, button: discord.ui.Button):
        mesa = self.mesa
        if not mesa.get_jogador(interaction.user.id):
            await interaction.response.send_message("Você não está nessa mesa.", ephemeral=True)
            return
        # Verifica fichas
        sem_fichas = [j for j in mesa.jogadores if get_fichas(j.user.id) < POKER_BIG_BLIND]
        for j in sem_fichas:
            set_fichas(j.user.id, FICHAS_INICIAIS)  # recarrega fichas zeradas
        self.stop()
        await interaction.response.send_message("🔄 Iniciando nova partida...")
        await iniciar_partida_poker(interaction.channel, mesa)

    @discord.ui.button(label="Encerrar mesa", style=discord.ButtonStyle.danger, emoji="❌")
    async def encerrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        mesa = self.mesa
        if interaction.user.id != mesa.iniciador_id:
            await interaction.response.send_message("Só quem criou pode encerrar.", ephemeral=True)
            return
        mesas_poker.pop(mesa.canal_id, None)
        self.stop()
        await interaction.response.send_message("❌ Mesa encerrada.")


# ── Entrar na mesa ─────────────────────────────────────────────────────────
class EntrarPokerView(discord.ui.View):
    def __init__(self, mesa: MesaPoker):
        super().__init__(timeout=120)
        self.mesa = mesa

    @discord.ui.button(label="Entrar", style=discord.ButtonStyle.success, emoji="🃏")
    async def entrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        mesa = self.mesa
        user = interaction.user
        if mesa.get_jogador(user.id):
            await interaction.response.send_message("Você já está na mesa!", ephemeral=True)
            return
        if len(mesa.jogadores) >= POKER_MAX_JOGADORES:
            await interaction.response.send_message("Mesa cheia!", ephemeral=True)
            return
        mesa.jogadores.append(JogadorPoker(user=user))
        saldo = get_fichas(user.id)
        await interaction.response.send_message(
            f"✅ **{user.display_name}** entrou! ({len(mesa.jogadores)}/{POKER_MAX_JOGADORES}) — Fichas: **{saldo} 🪙**"
        )

    @discord.ui.button(label="Iniciar partida", style=discord.ButtonStyle.primary, emoji="▶️")
    async def iniciar(self, interaction: discord.Interaction, button: discord.ui.Button):
        mesa = self.mesa
        if interaction.user.id != mesa.iniciador_id:
            await interaction.response.send_message("Só quem criou pode iniciar.", ephemeral=True)
            return
        if len(mesa.jogadores) < 2:
            await interaction.response.send_message("Precisa de pelo menos 2 jogadores.", ephemeral=True)
            return
        self.stop()
        await interaction.response.send_message("▶️ Iniciando partida...")
        await iniciar_partida_poker(interaction.channel, mesa)


# ── Comandos slash ─────────────────────────────────────────────────────────
@bot.tree.command(name="poker", description="Abre uma mesa de Texas Hold'em")
async def cmd_poker(interaction: discord.Interaction):
    canal_id = interaction.channel_id
    if canal_id in mesas_poker:
        await interaction.response.send_message("Já tem uma mesa aqui! Use `/poker_encerrar`.", ephemeral=True)
        return

    mesa = MesaPoker(canal_id=canal_id, iniciador_id=interaction.user.id)
    mesa.jogadores.append(JogadorPoker(user=interaction.user))
    mesas_poker[canal_id] = mesa

    saldo = get_fichas(interaction.user.id)
    view  = EntrarPokerView(mesa)
    embed = discord.Embed(
        title="🃏 Texas Hold'em",
        description=(
            f"**{interaction.user.display_name}** abriu uma mesa de poker!\n\n"
            f"Clique em **Entrar** para participar (2–{POKER_MAX_JOGADORES} jogadores).\n"
            f"Quando todos estiverem prontos, clique em **Iniciar partida**.\n\n"
            f"Blinds: **{POKER_SMALL_BLIND}/{POKER_BIG_BLIND} 🪙** | Fichas iniciais: **{FICHAS_INICIAIS} 🪙**"
        ),
        color=0x0d1b2a
    )
    await interaction.response.send_message(embed=embed, view=view)


@bot.tree.command(name="poker_encerrar", description="Encerra a mesa de poker atual")
async def cmd_poker_encerrar(interaction: discord.Interaction):
    canal_id = interaction.channel_id
    mesa = mesas_poker.get(canal_id)
    if not mesa:
        await interaction.response.send_message("Não tem mesa aqui.", ephemeral=True)
        return
    if interaction.user.id != mesa.iniciador_id:
        await interaction.response.send_message("Só quem criou pode encerrar.", ephemeral=True)
        return
    mesas_poker.pop(canal_id, None)
    await interaction.response.send_message("❌ Mesa de poker encerrada.")


@bot.tree.command(name="minhas_cartas", description="Veja suas cartas de poker (privado)")
async def cmd_minhas_cartas(interaction: discord.Interaction):
    canal_id = interaction.channel_id
    mesa = mesas_poker.get(canal_id)
    if not mesa:
        await interaction.response.send_message("Não tem mesa aqui.", ephemeral=True)
        return
    jog = mesa.get_jogador(interaction.user.id)
    if not jog or not jog.mao:
        await interaction.response.send_message("Você não tem cartas.", ephemeral=True)
        return
    cartas = "  ".join(f"`{c}`" for c in jog.mao)
    todas  = jog.mao + mesa.comunitarias
    nome   = nome_mao(todas) if mesa.comunitarias else "—"
    await interaction.response.send_message(
        f"🃏 Suas cartas: {cartas}\n🏆 Melhor mão atual: **{nome}**",
        ephemeral=True
    )


# ─────────────────────────────────────────
#  CANAL CASSINO
# ─────────────────────────────────────────
canais_cassino: set[int] = set()  # vazio = qualquer canal

def checar_canal(canal_id: int) -> bool:
    return len(canais_cassino) == 0 or canal_id in canais_cassino

@bot.tree.command(name="cassino_set", description="Define este canal como o canal do cassino (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_cassino_set(interaction: discord.Interaction):
    canais_cassino.add(interaction.channel_id)
    await interaction.response.send_message(
        f"🎰 Este canal agora é o **Cassino**! Só aqui os jogos funcionam."
    )

@bot.tree.command(name="cassino_remover", description="Remove este canal do cassino (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_cassino_remover(interaction: discord.Interaction):
    canais_cassino.discard(interaction.channel_id)
    msg = "✅ Canal removido do cassino." if canais_cassino or True else "✅ Cassino desativado — jogos liberados em todos os canais."
    await interaction.response.send_message(msg)

@bot.tree.command(name="cassino_info", description="Mostra onde o cassino está ativo")
async def cmd_cassino_info(interaction: discord.Interaction):
    if not canais_cassino:
        await interaction.response.send_message("🎰 Cassino ativo em **todos os canais**.", ephemeral=True)
    else:
        ids = ", ".join(f"<#{c}>" for c in canais_cassino)
        await interaction.response.send_message(f"🎰 Cassino ativo em: {ids}", ephemeral=True)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ Você precisa ser Admin para isso.", ephemeral=True)

# ─────────────────────────────────────────
#  BOT IA - POKER (DIFÍCIL)
# ─────────────────────────────────────────
def ia_decidir_poker(jogo: "MesaPoker", jog: "JogadorPoker") -> tuple[str, int]:
    """
    Retorna (ação, valor): ação = 'fold'|'call'|'raise'|'check'|'allin'
    Estratégia difícil: usa força da mão, pot odds e blefe ocasional.
    """
    todas     = jog.mao + jogo.comunitarias
    cat, _    = melhor_mao(todas) if todas else ((0, []), None)
    if isinstance(cat, tuple):
        forca = cat[0]
    else:
        forca = cat

    saldo      = get_fichas(jog.user.id)
    diff       = jogo.aposta_atual - jog.aposta_rodada
    pote       = jogo.pote
    pot_odds   = diff / (pote + diff) if (pote + diff) > 0 else 0

    # Fase pré-flop: avalia cartas na mão
    if not jogo.comunitarias:
        r1, r2 = rank_carta(jog.mao[0]), rank_carta(jog.mao[1])
        par     = r1 == r2
        altas   = r1 >= 10 and r2 >= 10
        conect  = abs(r1 - r2) <= 2
        if par and r1 >= 10:   forca = 8  # par alto = muito forte pré-flop
        elif par:               forca = 5
        elif altas:             forca = 6
        elif conect:            forca = 3
        else:                   forca = 1

    blefe = random.random() < 0.12  # 12% de chance de blefar

    if forca >= 7 or blefe:
        # Mão forte ou blefe: raise agressivo
        valor_raise = min(saldo, max(jogo.aposta_atual * 3, POKER_BIG_BLIND * 4))
        if valor_raise >= saldo * 0.8:
            return ('allin', saldo)
        return ('raise', valor_raise)
    elif forca >= 4:
        # Mão média: call se pot odds valerem
        if diff == 0:
            return ('check', 0)
        if pot_odds < 0.35 or diff <= saldo * 0.3:
            return ('call', diff)
        return ('fold', 0)
    else:
        # Mão fraca
        if diff == 0:
            return ('check', 0)
        if pot_odds < 0.2 and diff <= POKER_BIG_BLIND * 2:
            return ('call', diff)
        return ('fold', 0)


async def executar_acao_ia_poker(canal, mesa: "MesaPoker", jog: "JogadorPoker"):
    await asyncio.sleep(random.uniform(1.2, 2.5))  # simula "pensar"
    acao, valor = ia_decidir_poker(mesa, jog)

    if acao == 'fold':
        jog.foldou = True
        mesa.rodada_apostas += 1
        await canal.send(f"🤖 **{jog.user.display_name}** deu fold.")
    elif acao == 'check':
        mesa.rodada_apostas += 1
        await canal.send(f"🤖 **{jog.user.display_name}** deu check.")
    elif acao == 'call':
        real = min(valor, get_fichas(jog.user.id))
        _cobrar(mesa, jog, real)
        mesa.rodada_apostas += 1
        await canal.send(f"🤖 **{jog.user.display_name}** pagou **{real} 🪙**.")
    elif acao == 'raise':
        diff_atual = mesa.aposta_atual - jog.aposta_rodada
        total      = diff_atual + valor
        real       = min(total, get_fichas(jog.user.id))
        _cobrar(mesa, jog, real)
        mesa.aposta_atual   = jog.aposta_rodada
        mesa.rodada_apostas = 1
        await canal.send(f"🤖 **{jog.user.display_name}** fez raise para **{jog.aposta_rodada} 🪙**!")
    elif acao == 'allin':
        saldo = get_fichas(jog.user.id)
        _cobrar(mesa, jog, saldo)
        if jog.aposta_rodada > mesa.aposta_atual:
            mesa.aposta_atual   = jog.aposta_rodada
            mesa.rodada_apostas = 1
        else:
            mesa.rodada_apostas += 1
        await canal.send(f"🤖 **{jog.user.display_name}** foi ALL-IN com **{saldo} 🪙**!")

    mesa.avancar_vez()
    await pedir_acao_poker(canal, mesa)


# ─────────────────────────────────────────
#  PATCH: checar canal em todos os comandos
# ─────────────────────────────────────────
# Monkey-patch: wrap original commands to check casino channel
_orig_truco    = cmd_truco.callback
_orig_21       = cmd_21.callback
_orig_poker    = cmd_poker.callback

async def _truco_checked(interaction: discord.Interaction, modo: str = "1v1"):
    if not checar_canal(interaction.channel_id):
        await interaction.response.send_message("🎰 Os jogos só funcionam no canal do cassino!", ephemeral=True)
        return
    await _orig_truco(interaction, modo)

async def _21_checked(interaction: discord.Interaction):
    if not checar_canal(interaction.channel_id):
        await interaction.response.send_message("🎰 Os jogos só funcionam no canal do cassino!", ephemeral=True)
        return
    await _orig_21(interaction)

async def _poker_checked(interaction: discord.Interaction):
    if not checar_canal(interaction.channel_id):
        await interaction.response.send_message("🎰 Os jogos só funcionam no canal do cassino!", ephemeral=True)
        return
    await _orig_poker(interaction)

cmd_truco.callback = _truco_checked
cmd_21.callback    = _21_checked
cmd_poker.callback = _poker_checked


# ─────────────────────────────────────────
#  SOLO - TRUCO CONTRA BOT
# ─────────────────────────────────────────
class BotTruco:
    """Jogador IA para o truco."""
    def __init__(self, user_fake):
        self.id           = user_fake.id
        self.display_name = user_fake.display_name

    async def send(self, *a, **kw):
        pass  # Bot não recebe DM


class FakeUser:
    def __init__(self, name: str, uid: int):
        self.id           = uid
        self.display_name = name
        self.mention      = name

    async def send(self, *a, **kw):
        pass


def ia_jogar_truco(jogo: JogoTruco, user_id: int) -> str:
    """Escolhe a melhor carta: joga a mais forte se o adversário já jogou mais forte, senão a mais fraca."""
    cartas = jogo.maos.get(user_id, [])
    if not cartas:
        return cartas[0] if cartas else ""

    # Verifica se adversário já jogou nessa rodada
    jogadas_adv = [c for uid, c in jogo.mesa if uid != user_id]

    if jogadas_adv:
        melhor_adv = max(valor_carta(c) for c in jogadas_adv)
        # Tenta ganhar com a carta mais fraca que ainda bata
        vencedoras = [c for c in cartas if valor_carta(c) > melhor_adv]
        if vencedoras:
            return min(vencedoras, key=valor_carta)
        else:
            return min(cartas, key=valor_carta)  # descarta a mais fraca
    else:
        # Joga primeiro: carta média (nem revela a melhor, nem desperdiça)
        ordenadas = sorted(cartas, key=valor_carta)
        return ordenadas[len(ordenadas) // 2]


@bot.tree.command(name="truco_solo", description="Joga Truco contra o bot")
async def cmd_truco_solo(interaction: discord.Interaction):
    if not checar_canal(interaction.channel_id):
        await interaction.response.send_message("🎰 Os jogos só funcionam no canal do cassino!", ephemeral=True)
        return
    canal_id = interaction.channel_id
    if canal_id in jogos:
        await interaction.response.send_message("Já tem um jogo nesse canal!", ephemeral=True)
        return

    bot_user = FakeUser("🤖 TrucoBot", 999999999)
    jogo = JogoTruco(canal_id=canal_id, modo="1v1")
    jogo.equipe1.jogadores.append(interaction.user)
    jogo.equipe2.jogadores.append(bot_user)
    jogos[canal_id] = jogo

    await interaction.response.send_message("🃏 Iniciando Truco contra o Bot...")
    await iniciar_jogo(interaction.channel, jogo)


# ─────────────────────────────────────────
#  SOLO - 21 CONTRA BOT (já funciona, só confirma)
# ─────────────────────────────────────────
# O 21 já suporta 1 jogador contra o dealer — sem mudanças necessárias.

# ─────────────────────────────────────────
#  SOLO - POKER CONTRA BOT
# ─────────────────────────────────────────
@bot.tree.command(name="poker_solo", description="Joga Texas Hold'em contra o bot (IA difícil)")
async def cmd_poker_solo(interaction: discord.Interaction):
    if not checar_canal(interaction.channel_id):
        await interaction.response.send_message("🎰 Os jogos só funcionam no canal do cassino!", ephemeral=True)
        return
    canal_id = interaction.channel_id
    if canal_id in mesas_poker:
        await interaction.response.send_message("Já tem uma mesa aqui!", ephemeral=True)
        return

    bot_user = FakeUser("🤖 PokerBot", 999999998)
    set_fichas(bot_user.id, FICHAS_INICIAIS)

    mesa = MesaPoker(canal_id=canal_id, iniciador_id=interaction.user.id)
    mesa.jogadores.append(JogadorPoker(user=interaction.user))
    mesa.jogadores.append(JogadorPoker(user=bot_user))
    mesas_poker[canal_id] = mesa

    await interaction.response.send_message(
        f"🤖 Iniciando poker contra **PokerBot** (IA Difícil)! Fichas: **{get_fichas(interaction.user.id)} 🪙**"
    )
    await iniciar_partida_poker(interaction.channel, mesa)


# ─────────────────────────────────────────
#  PATCH: pedir_acao_poker verifica se é IA
# ─────────────────────────────────────────
_orig_pedir_acao = pedir_acao_poker

async def pedir_acao_poker(canal, mesa: MesaPoker):
    if len(mesa.ativos()) == 1:
        await showdown_poker(canal, mesa)
        return

    podem = mesa.podem_agir()
    todos_igualaram = all(j.aposta_rodada == mesa.aposta_atual for j in podem)
    if todos_igualaram and mesa.rodada_apostas >= len(podem):
        await avancar_fase_poker(canal, mesa)
        return

    jogador = mesa.jogador_atual()
    if not jogador:
        await avancar_fase_poker(canal, mesa)
        return

    # Se for bot IA, age automaticamente
    IDS_BOT = {999999998, 999999999}
    if jogador.user.id in IDS_BOT:
        await executar_acao_ia_poker(canal, mesa, jogador)
        return

    diff  = mesa.aposta_atual - jogador.aposta_rodada
    saldo = get_fichas(jogador.user.id)
    view  = AcaoPokerView(mesa, jogador, diff, saldo)
    linha1 = f"🎯 **{jogador.user.mention}** é sua vez!"
    linha2 = f"Pote: **{mesa.pote} 🪙** | Aposta atual: **{mesa.aposta_atual} 🪙** | Suas fichas: **{saldo} 🪙**"
    extra  = f" | Para pagar: **{diff} 🪙**" if diff > 0 else " | Pode dar Check"
    await canal.send(
        linha1 + " " + linha2 + extra,
        embed=embed_poker(mesa),
        view=view
    )


# Substitui a referência global
import sys
_mod = sys.modules[__name__]
setattr(_mod, 'pedir_acao_poker', pedir_acao_poker)

# Atualiza referências nas funções que chamam pedir_acao_poker
avancar_fase_poker.__globals__['pedir_acao_poker']  = pedir_acao_poker
showdown_poker.__globals__['pedir_acao_poker']      = pedir_acao_poker


# ─────────────────────────────────────────
#  PATCH: processar_jogada verifica bot truco
# ─────────────────────────────────────────
_orig_processar = processar_jogada

async def processar_jogada(canal, jogo: JogoTruco, user_id: int, carta: str):
    await _orig_processar(canal, jogo, user_id, carta)
    # Após a jogada, verifica se é vez do bot
    if canal.id not in jogos:
        return
    jogo = jogos.get(canal.id)
    if not jogo or jogo.estado != EstadoTruco.JOGANDO:
        return
    atual = jogador_atual(jogo)
    if atual and atual.id == 999999999:
        await asyncio.sleep(1.2)
        carta_bot = ia_jogar_truco(jogo, atual.id)
        if carta_bot:
            await processar_jogada(canal, jogo, atual.id, carta_bot)

setattr(_mod, 'processar_jogada', processar_jogada)
pedir_jogada.__globals__['processar_jogada'] = processar_jogada


# ─────────────────────────────────────────
#  EVENTOS
# ─────────────────────────────────────────
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ {bot.user} online! Comandos sincronizados.")


bot.run(TOKEN)
