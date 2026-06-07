import discord
from discord import app_commands
from discord.ext import commands
import random
import asyncio
from dataclasses import dataclass, field
from typing import Optional
from .base import get_fichas, set_fichas, checar_canal, atualizar_msg, FakeUser, FICHAS_INICIAIS, APOSTA_MINIMA, APOSTA_MAXIMA
from itertools import product as iproduct


mesas_domino: dict = {}  # canal_id -> MesaDomino

# ═════════════════════════════════════════
#  DOMINÓ
# ═════════════════════════════════════════
from itertools import product as iproduct

def gerar_pedras_domino():
    pedras = []
    for i in range(7):
        for j in range(i, 7):
            pedras.append((i, j))
    random.shuffle(pedras)
    return pedras

def pedra_str(p):
    return f"[{p[0]}|{p[1]}]"

def pedra_jogavel(pedra, esq, dir_):
    return pedra[0] in (esq, dir_) or pedra[1] in (esq, dir_)

def girar_pedra(pedra, lado):
    """Retorna pedra orientada para encaixar no lado."""
    if pedra[0] == lado:
        return pedra
    return (pedra[1], pedra[0])

@dataclass
class MesaDomino:
    canal_id: int
    modo: str       # "paulista" ou "bloqueio"
    equipes: str    # "1v1" ou "2v2"
    iniciador_id: int
    jogadores: list = field(default_factory=list)
    maos: dict = field(default_factory=dict)
    mesa_pedras: list = field(default_factory=list)  # pedras na mesa em ordem
    extremo_esq: int = -1
    extremo_dir: int = -1
    vez_idx: int = 0
    estado: str = "aguardando"
    equipe1: list = field(default_factory=list)  # indices dos jogadores
    equipe2: list = field(default_factory=list)
    passes_consecutivos: int = 0
    pontos_eq1: int = 0
    pontos_eq2: int = 0

    def jogador_atual(self):
        return self.jogadores[self.vez_idx % len(self.jogadores)]

    def avancar(self):
        self.vez_idx = (self.vez_idx + 1) % len(self.jogadores)

    def mao(self, uid):
        return self.maos.get(uid, [])

    def eq_do_jogador(self, uid):
        idx = next((i for i, j in enumerate(self.jogadores) if j.id == uid), -1)
        return 1 if idx in self.equipe1 else 2


mesas_domino: dict[int, MesaDomino] = {}


def ia_jogar_domino(mesa: MesaDomino, uid: int):
    """IA escolhe melhor pedra ou passa."""
    mao = mesa.mao(uid)
    if mesa.extremo_esq == -1:
        return mao[0] if mao else None, "esq"
    jogaveis = [(p, lado) for p in mao
                for lado in ("esq", "dir")
                if (lado == "esq" and (p[0] == mesa.extremo_esq or p[1] == mesa.extremo_esq))
                or (lado == "dir" and (p[0] == mesa.extremo_dir or p[1] == mesa.extremo_dir))]
    if not jogaveis:
        return None, None
    # Prefere pedras maiores
    jogaveis.sort(key=lambda x: x[0][0] + x[0][1], reverse=True)
    return jogaveis[0]


async def iniciar_domino(canal, mesa: MesaDomino):
    mesa.estado = "jogando"
    pedras = gerar_pedras_domino()
    n = len(mesa.jogadores)
    por_jogador = 7 if n <= 4 else 5
    for i, j in enumerate(mesa.jogadores):
        mesa.maos[j.id] = pedras[i*por_jogador:(i+1)*por_jogador]

    if mesa.equipes == "2v2":
        mesa.equipe1 = [0, 2]
        mesa.equipe2 = [1, 3]
    else:
        mesa.equipe1 = [0]
        mesa.equipe2 = [1]

    # Quem tem [6|6] começa
    for i, j in enumerate(mesa.jogadores):
        if (6, 6) in mesa.maos[j.id]:
            mesa.vez_idx = i
            break

    for j in mesa.jogadores:
        mao_txt = "  ".join(pedra_str(p) for p in mesa.mao(j.id))
        try:
            await j.send(f"🁣 **Suas pedras no Dominó:**\n{mao_txt}")
        except Exception:
            pass

    await canal.send(
        f"🁣 **Dominó iniciado!** Modo: **{mesa.modo}** | **{mesa.equipes}**\n"
        f"Pedras enviadas por DM! Primeiro: **{mesa.jogador_atual().display_name}**"
    )
    await pedir_turno_domino(canal, mesa)


def embed_domino(mesa: MesaDomino) -> discord.Embed:
    e = discord.Embed(title="🁣 Dominó", color=0x1a1a1a)
    if mesa.mesa_pedras:
        linha = "  ".join(pedra_str(p) for p in mesa.mesa_pedras[-8:])
        e.add_field(name=f"Mesa ({len(mesa.mesa_pedras)} pedras)", value=f"`{linha}`", inline=False)
        e.add_field(name="Extremos", value=f"◀ **{mesa.extremo_esq}** ... **{mesa.extremo_dir}** ▶", inline=False)
    for j in mesa.jogadores:
        n_pedras = len(mesa.mao(j.id))
        e.add_field(name=j.display_name, value=f"{n_pedras} pedras", inline=True)
    if mesa.equipes == "2v2":
        eq1 = " & ".join(mesa.jogadores[i].display_name for i in mesa.equipe1 if i < len(mesa.jogadores))
        eq2 = " & ".join(mesa.jogadores[i].display_name for i in mesa.equipe2 if i < len(mesa.jogadores))
        e.add_field(name="Pontos", value=f"{eq1}: {mesa.pontos_eq1} | {eq2}: {mesa.pontos_eq2}", inline=False)
    e.set_footer(text=f"Vez de: {mesa.jogador_atual().display_name} | Modo: {mesa.modo}")
    return e


async def pedir_turno_domino(canal, mesa: MesaDomino):
    atual = mesa.jogador_atual()
    IDS_BOT_DOM = {999999997}

    if atual.id in IDS_BOT_DOM:
        await asyncio.sleep(1.2)
        pedra, lado = ia_jogar_domino(mesa, atual.id)
        if pedra:
            await jogar_pedra_domino(canal, mesa, atual.id, pedra, lado)
        else:
            await passar_domino(canal, mesa, atual.id)
        return

    mao = mesa.mao(atual.id)
    jogaveis_esq = [p for p in mao if mesa.extremo_esq == -1 or p[0] == mesa.extremo_esq or p[1] == mesa.extremo_esq]
    jogaveis_dir = [p for p in mao if mesa.extremo_dir == -1 or p[0] == mesa.extremo_dir or p[1] == mesa.extremo_dir]
    tem_jogada   = bool(jogaveis_esq or jogaveis_dir) if mesa.extremo_esq != -1 else bool(mao)

    embed = embed_domino(mesa)
    if not tem_jogada:
        await canal.send(f"🚫 **{atual.display_name}** não tem pedra jogável e passa!", embed=embed)
        await passar_domino(canal, mesa, atual.id)
        return

    view = DominoJogarView(mesa, atual)
    await canal.send(f"🁣 **{atual.mention}** é sua vez!", embed=embed, view=view)


async def jogar_pedra_domino(canal, mesa: MesaDomino, uid: int, pedra, lado: str):
    mao = mesa.mao(uid)
    if pedra not in mao:
        return
    mao.remove(pedra)
    mesa.passes_consecutivos = 0

    if mesa.extremo_esq == -1:
        # Primeira pedra
        mesa.mesa_pedras.append(pedra)
        mesa.extremo_esq = pedra[0]
        mesa.extremo_dir = pedra[1]
    elif lado == "esq":
        p = girar_pedra(pedra, mesa.extremo_esq)
        mesa.mesa_pedras.insert(0, p)
        mesa.extremo_esq = p[1] if p[0] == mesa.extremo_esq else p[0]
        # fix: extremo esq é o lado que aponta pra fora
        mesa.extremo_esq = p[0] if p[1] == mesa.extremo_esq else p[0]
        # simpler: just update correctly
        if pedra[0] == mesa.extremo_esq:
            mesa.extremo_esq = pedra[1]
        else:
            mesa.extremo_esq = pedra[0]
        mesa.mesa_pedras.insert(0, pedra)
        mesa.mesa_pedras.pop(1)
    else:
        if pedra[0] == mesa.extremo_dir:
            mesa.extremo_dir = pedra[1]
        else:
            mesa.extremo_dir = pedra[0]
        mesa.mesa_pedras.append(pedra)

    jogador = next((j for j in mesa.jogadores if j.id == uid), None)
    nome = jogador.display_name if jogador else str(uid)
    await canal.send(f"🁣 **{nome}** jogou `{pedra_str(pedra)}` na **{lado}**")

    # Verifica vitória
    if len(mao) == 0:
        await fim_domino(canal, mesa, uid, "bateu")
        return

    # Modo paulista: pode bater com a mesma pedra
    if mesa.modo == "paulista" and len(mesa.mesa_pedras) > 1:
        if mesa.extremo_esq == mesa.extremo_dir == pedra[0] == pedra[1]:
            await fim_domino(canal, mesa, uid, "carroça")
            return

    mesa.avancar()
    await pedir_turno_domino(canal, mesa)


async def passar_domino(canal, mesa: MesaDomino, uid: int):
    mesa.passes_consecutivos += 1
    mesa.avancar()
    n = len(mesa.jogadores)
    if mesa.passes_consecutivos >= n:
        await fim_domino(canal, mesa, None, "bloqueio")
        return
    await pedir_turno_domino(canal, mesa)


async def fim_domino(canal, mesa: MesaDomino, uid_vencedor, motivo: str):
    if uid_vencedor:
        jogador = next((j for j in mesa.jogadores if j.id == uid_vencedor), None)
        nome = jogador.display_name if jogador else "?"
        eq   = mesa.eq_do_jogador(uid_vencedor)
        if eq == 1:
            mesa.pontos_eq1 += 1
        else:
            mesa.pontos_eq2 += 1
        txt = f"🏆 **{nome}** {'bateu' if motivo == 'bateu' else 'fez carroça'}! "
        if mesa.equipes == "2v2":
            eq1 = " & ".join(mesa.jogadores[i].display_name for i in mesa.equipe1 if i < len(mesa.jogadores))
            eq2 = " & ".join(mesa.jogadores[i].display_name for i in mesa.equipe2 if i < len(mesa.jogadores))
            txt += f"\nPlacar: {eq1} **{mesa.pontos_eq1}** x **{mesa.pontos_eq2}** {eq2}"
    else:
        # Bloqueio: menor soma de pontos vence
        somas = {}
        for j in mesa.jogadores:
            somas[j.id] = sum(p[0] + p[1] for p in mesa.mao(j.id))
        min_soma = min(somas.values())
        vencedores = [j for j in mesa.jogadores if somas[j.id] == min_soma]
        nomes = ", ".join(j.display_name for j in vencedores)
        txt = f"🔒 Jogo bloqueado! **{nomes}** vence com menor soma ({min_soma} pontos)."

    await canal.send(txt, embed=embed_domino(mesa))
    view = NovaRodadaDominoView(mesa)
    await canal.send("Jogar de novo?", view=view)


class NovaRodadaDominoView(discord.ui.View):
    def __init__(self, mesa: MesaDomino):
        super().__init__(timeout=60)
        self.mesa = mesa

    @discord.ui.button(label="Nova rodada", style=discord.ButtonStyle.success, emoji="🔄")
    async def nova(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not mesa_domino_tem_jogador(self.mesa, interaction.user.id):
            await interaction.response.send_message("Você não está nessa mesa.", ephemeral=True)
            return
        self.stop()
        await interaction.response.send_message("🔄 Nova rodada!")
        await iniciar_domino(interaction.channel, self.mesa)

    @discord.ui.button(label="Encerrar", style=discord.ButtonStyle.danger, emoji="❌")
    async def encerrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        mesas_domino.pop(self.mesa.canal_id, None)
        self.stop()
        await interaction.response.send_message("❌ Jogo encerrado.")

def mesa_domino_tem_jogador(mesa, uid):
    return any(j.id == uid for j in mesa.jogadores)


class DominoJogarView(discord.ui.View):
    def __init__(self, mesa: MesaDomino, jogador):
        super().__init__(timeout=60)
        self.mesa    = mesa
        self.jogador = jogador
        mao = mesa.mao(jogador.id)
        adicionadas = set()
        for p in mao:
            key = str(p)
            if key in adicionadas:
                continue
            adicionadas.add(key)
            jogavel_esq = (mesa.extremo_esq == -1 or p[0] == mesa.extremo_esq or p[1] == mesa.extremo_esq)
            jogavel_dir = (mesa.extremo_dir == -1 or p[0] == mesa.extremo_dir or p[1] == mesa.extremo_dir)
            if jogavel_esq:
                self.add_item(DominoPedraBtn(p, "esq", mesa, jogador))
            if jogavel_dir and mesa.extremo_esq != -1 and mesa.extremo_esq != mesa.extremo_dir:
                self.add_item(DominoPedraBtn(p, "dir", mesa, jogador))


class DominoPedraBtn(discord.ui.Button):
    def __init__(self, pedra, lado, mesa, jogador):
        label = f"{pedra_str(pedra)} {'◀' if lado == 'esq' else '▶'}"
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.pedra   = pedra
        self.lado    = lado
        self.mesa    = mesa
        self.jogador = jogador

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.jogador.id:
            await interaction.response.send_message("Não é sua vez!", ephemeral=True)
            return
        await interaction.response.defer()
        self.view.stop()
        await jogar_pedra_domino(interaction.channel, self.mesa, self.jogador.id, self.pedra, self.lado)


class EntrarDominoView(discord.ui.View):
    def __init__(self, mesa: MesaDomino):
        super().__init__(timeout=120)
        self.mesa = mesa

    @discord.ui.button(label="Entrar", style=discord.ButtonStyle.success, emoji="🁣")
    async def entrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        mesa = self.mesa
        if mesa_domino_tem_jogador(mesa, interaction.user.id):
            await interaction.response.send_message("Você já está!", ephemeral=True)
            return
        max_j = 4 if mesa.equipes == "2v2" else 2
        if len(mesa.jogadores) >= max_j:
            await interaction.response.send_message("Mesa cheia!", ephemeral=True)
            return
        mesa.jogadores.append(interaction.user)
        await interaction.response.send_message(f"✅ **{interaction.user.display_name}** entrou! ({len(mesa.jogadores)}/{max_j})")
        if len(mesa.jogadores) == max_j:
            self.stop()
            await iniciar_domino(interaction.channel, mesa)

    @discord.ui.button(label="Iniciar", style=discord.ButtonStyle.primary, emoji="▶️")
    async def iniciar(self, interaction: discord.Interaction, button: discord.ui.Button):
        mesa = self.mesa
        if interaction.user.id != mesa.iniciador_id:
            await interaction.response.send_message("Só quem criou pode iniciar.", ephemeral=True)
            return
        min_j = 2
        if len(mesa.jogadores) < min_j:
            await interaction.response.send_message(f"Precisa de pelo menos {min_j} jogadores.", ephemeral=True)
            return
        self.stop()
        await interaction.response.send_message("▶️ Iniciando Dominó!")
        await iniciar_domino(interaction.channel, mesa)



class DominoCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot


    @app_commands.command(name="domino", description="Inicia uma partida de Dominó")
    @app_commands.describe(modo="paulista ou bloqueio", equipes="1v1 ou 2v2")
    @app_commands.choices(
        modo=[app_commands.Choice(name="Paulista", value="paulista"),
              app_commands.Choice(name="Bloqueio", value="bloqueio")],
        equipes=[app_commands.Choice(name="1v1", value="1v1"),
                 app_commands.Choice(name="2v2", value="2v2")]
    )
    async def cmd_domino(interaction: discord.Interaction, modo: str = "paulista", equipes: str = "1v1"):
        if not checar_canal(interaction.channel_id):
            await interaction.response.send_message("🎰 Os jogos só funcionam no canal do cassino!", ephemeral=True)
            return
        canal_id = interaction.channel_id
        if canal_id in mesas_domino:
            await interaction.response.send_message("Já tem dominó aqui!", ephemeral=True)
            return
        mesa = MesaDomino(canal_id=canal_id, modo=modo, equipes=equipes, iniciador_id=interaction.user.id)
        mesa.jogadores.append(interaction.user)
        mesas_domino[canal_id] = mesa
        max_j = 4 if equipes == "2v2" else 2
        embed = discord.Embed(title="🁣 Dominó", color=0x1a1a1a,
            description=f"**{interaction.user.display_name}** criou Dominó!\nModo: **{modo}** | **{equipes}** ({max_j} jogadores)")
        await interaction.response.send_message(embed=embed, view=EntrarDominoView(mesa))

    @app_commands.command(name="domino_solo", description="Joga Dominó contra o bot")
    @app_commands.choices(
        modo=[app_commands.Choice(name="Paulista", value="paulista"),
              app_commands.Choice(name="Bloqueio", value="bloqueio")]
    )
    async def cmd_domino_solo(interaction: discord.Interaction, modo: str = "paulista"):
        if not checar_canal(interaction.channel_id):
            await interaction.response.send_message("🎰 Os jogos só funcionam no canal do cassino!", ephemeral=True)
            return
        canal_id = interaction.channel_id
        if canal_id in mesas_domino:
            await interaction.response.send_message("Já tem dominó aqui!", ephemeral=True)
            return
        bot_user = FakeUser("🤖 DominoBot", 999999997)
        mesa = MesaDomino(canal_id=canal_id, modo=modo, equipes="1v1", iniciador_id=interaction.user.id)
        mesa.jogadores = [interaction.user, bot_user]
        mesas_domino[canal_id] = mesa
        await interaction.response.send_message(f"🁣 Iniciando Dominó **{modo}** contra o bot!")
        await iniciar_domino(interaction.channel, mesa)

    @app_commands.command(name="domino_encerrar", description="Encerra o dominó atual")
    async def cmd_domino_encerrar(interaction: discord.Interaction):
        mesa = mesas_domino.pop(interaction.channel_id, None)
        if not mesa:
            await interaction.response.send_message("Não tem dominó aqui.", ephemeral=True)
            return
        await interaction.response.send_message("❌ Dominó encerrado.")




async def setup(bot: commands.Bot):
    await bot.add_cog(DominoCog(bot))
