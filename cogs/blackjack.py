import discord
from discord import app_commands
from discord.ext import commands
import random
import asyncio
from dataclasses import dataclass, field
from typing import Optional
from .base import get_fichas, set_fichas, checar_canal, atualizar_msg, FakeUser, FICHAS_INICIAIS, APOSTA_MINIMA, APOSTA_MAXIMA, registrar_resultado, registrar_atividade, cancelar_timeout


mesas_bj: dict = {}  # canal_id -> MesaBJ

# ─────────────────────────────────────────
#  BLACKJACK - 21
# ─────────────────────────────────────────

NAIPES_BJ  = ["♠", "♥", "♦", "♣"]
NUMEROS_BJ = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]

mesas_bj: dict[int, "MesaBJ"] = {}  # canal_id -> mesa

def get_fichas(user_id: int) -> int:
    return fichas.get(user_id, FICHAS_INICIAIS)

def set_fichas(user_id: int, valor: int):
    fichas[user_id] = max(0, valor)
    # Persiste em background sem bloquear
    asyncio.create_task(_salvar_fichas(user_id, max(0, valor)))

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
        saldo = get_fichas(j.user.id)
        e.add_field(
            name=f"{nome} — {val} pts{status} | aposta: {j.aposta} 🪙 | saldo: {saldo} 🪙",
            value=formatar_mao(j.mao),
            inline=False
        )
    return e


class ApostaModal(discord.ui.Modal, title="Sua aposta"):
    aposta = discord.ui.TextInput(
        label="Quantas fichas?",
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

    # Primeiro jogador que não tem blackjack
    proximo = mesa.proximo_jogador()
    if proximo:
        # Manda a primeira mensagem com os botões já incluídos
        view = JogarBJView(mesa, proximo)
        val  = calcular_mao(proximo.mao)
        msg  = await canal.send(
            f"🃏 **Cartas distribuídas!** | 🎯 **{proximo.user.mention}** é sua vez! **{val}** pts | Aposta: **{proximo.aposta} 🪙**",
            embed=embed_mesa_bj(mesa),
            view=view
        )
        mesa.msg_id = msg.id
    else:
        await canal.send("🃏 **Cartas distribuídas!**", embed=embed_mesa_bj(mesa))
        await vez_dealer_bj(canal, mesa)


async def pedir_turno_bj(canal, mesa: MesaBJ, jogador: JogadorBJ):
    view = JogarBJView(mesa, jogador)
    val  = calcular_mao(jogador.mao)
    embed = embed_mesa_bj(mesa)
    mesa.msg_id = await _atualizar_msg(
        canal, mesa.msg_id,
        content_txt=f"🎯 **{jogador.user.mention}** é sua vez! **{val}** pts | Aposta: **{jogador.aposta} 🪙**",
        embed=embed, view=view
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
    cancelar_timeout(mesa.canal_id)
    for j in mesa.jogadores:
        if hasattr(j.user, 'id') and j.user.id < 999999990:
            val = calcular_mao(j.mao)
            ganhou = not j.estourou and (dealer_estourou or val > dealer_val or j.blackjack)
            asyncio.create_task(registrar_resultado(
                j.user.id, j.user.display_name, "Blackjack 21", ganhou, j.aposta
            ))
    view = NovaRodadaBJView(mesa)
    await canal.send("Jogar de novo?", view=view)


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



async def _encerrar_bj_timeout(canal_id: int, motivo: str):
    mesa = mesas_bj.pop(canal_id, None)
    if not mesa:
        return
    try:
        canal = None
        for guild in _bot_ref_bj.guilds:
            canal = guild.get_channel(canal_id)
            if canal:
                break
        if canal:
            await canal.send("⏰ Mesa de **Blackjack** encerrada por inatividade (10 min).")
    except Exception as e:
        print(f"[TIMEOUT BJ] {e}")

_bot_ref_bj = None


class BlackjackCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        global _bot_ref_bj
        _bot_ref_bj = bot


    @app_commands.command(name="21", description="Inicia uma mesa de Blackjack (21)")
    async def cmd_21(interaction: discord.Interaction):
        canal_id = interaction.channel_id
        if not checar_canal(canal_id):
            await interaction.response.send_message("🎰 Os jogos só funcionam no canal do cassino!", ephemeral=True)
            return
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

    @app_commands.command(name="fichas", description="Veja seu saldo de fichas")
    async def cmd_fichas(interaction: discord.Interaction):
        saldo = get_fichas(interaction.user.id)
        await interaction.response.send_message(
            f"🪙 **{interaction.user.display_name}** tem **{saldo} fichas**.",
            ephemeral=True
        )

    @app_commands.command(name="21_encerrar", description="Encerra a mesa de blackjack atual")
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




async def setup(bot: commands.Bot):
    await bot.add_cog(BlackjackCog(bot))
