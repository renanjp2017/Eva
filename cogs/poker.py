import discord
from discord import app_commands
from discord.ext import commands
import random
import asyncio
from dataclasses import dataclass, field
from typing import Optional
from .base import get_fichas, set_fichas, checar_canal, atualizar_msg, FakeUser, FICHAS_INICIAIS, APOSTA_MINIMA, APOSTA_MAXIMA, registrar_resultado, registrar_atividade, cancelar_timeout
from itertools import combinations


mesas_poker: dict = {}  # canal_id -> MesaPoker
POKER_BIG_BLIND = 20
POKER_SMALL_BLIND = 10
POKER_MAX_JOGADORES = 9

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

    # Registra resultados
    for j in mesa.jogadores:
        if j.user.id not in {999999998}:
            ganhou = j in vencedores if 'vencedores' in dir() else False
            asyncio.create_task(registrar_resultado(
                j.user.id, j.user.display_name, "Poker",
                ganhou, parte if ganhou else j.aposta_rodada
            ))

    cancelar_timeout(mesa.canal_id)
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

async def _encerrar_poker_timeout(canal_id: int, motivo: str):
    from . import poker as _self
    mesa = mesas_poker.pop(canal_id, None)
    if not mesa:
        return
    try:
        canal = None
        for guild in _self._bot_ref.guilds:
            canal = guild.get_channel(canal_id)
            if canal:
                break
        if canal:
            atual = mesa.jogador_atual()
            mencao = atual.user.mention if atual and hasattr(atual.user, 'mention') else ""
            await canal.send(f"⏰ {mencao} Partida de poker encerrada por **inatividade** (10 min sem ação).")
    except Exception as e:
        print(f"[TIMEOUT POKER] {e}")

_bot_ref = None


class PokerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        global _bot_ref
        _bot_ref = bot


    @app_commands.command(name="poker", description="Abre uma mesa de Texas Hold'em")
    async def cmd_poker(interaction: discord.Interaction):
        canal_id = interaction.channel_id
        if not checar_canal(canal_id):
            await interaction.response.send_message("🎰 Os jogos só funcionam no canal do cassino!", ephemeral=True)
            return
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

    @app_commands.command(name="poker_encerrar", description="Encerra a mesa de poker atual")
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

    @app_commands.command(name="minhas_cartas", description="Veja suas cartas de poker (privado)")
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

        return len(canais_cassino) == 0 or canal_id in canais_cassino
    @app_commands.command(name="cassino_set", description="Define este canal como o canal do cassino (Admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def cmd_cassino_set(interaction: discord.Interaction):
        canais_cassino.add(interaction.channel_id)
        await interaction.response.send_message(
            f"🎰 Este canal agora é o **Cassino**! Só aqui os jogos funcionam."
        )
    @app_commands.command(name="cassino_remover", description="Remove este canal do cassino (Admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def cmd_cassino_remover(interaction: discord.Interaction):
        canais_cassino.discard(interaction.channel_id)
        msg = "✅ Canal removido do cassino." if canais_cassino or True else "✅ Cassino desativado — jogos liberados em todos os canais."
        await interaction.response.send_message(msg)
    @app_commands.command(name="truco_solo", description="Joga Truco contra o bot")
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
    @app_commands.command(name="poker_solo", description="Joga Texas Hold'em contra o bot (IA difícil)")
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
        registrar_atividade(mesa.canal_id, _encerrar_poker_timeout)
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




async def setup(bot: commands.Bot):
    await bot.add_cog(PokerCog(bot))
