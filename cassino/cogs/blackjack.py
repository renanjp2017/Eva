"""
blackjack.py — Blackjack 21 com mesa gótica renderizada.
Mesa única que se edita a cada jogada via message.edit().
Suporta até 4 jogadores + dealer (bot).
"""
import discord
from discord import app_commands
from discord.ext import commands
import random, asyncio, io
from dataclasses import dataclass, field
from typing import Optional
from .base import (get_fichas, set_fichas, checar_canal,
                   FICHAS_INICIAIS, registrar_resultado,
                   registrar_atividade, cancelar_timeout)
from .renderer import render_blackjack

mesas_bj: dict[int, "MesaBJ"] = {}

# ── Baralho ───────────────────────────────────────────────────────────────────
NAIPES = ["♠","♥","♦","♣"]
NUMS   = ["A","2","3","4","5","6","7","8","9","10","J","Q","K"]

def gerar_baralho():
    b = [f"{n}{s}" for n in NUMS for s in NAIPES]
    random.shuffle(b)
    return b

def _parse(carta):
    return (carta[:-1], carta[-1]) if carta[-1] in "♠♥♦♣" else (carta,"")

def valor_carta(carta):
    n = _parse(carta)[0]
    if n in ("J","Q","K"): return 10
    if n == "A":           return 11
    return int(n)

def calcular_mao(cartas):
    total = sum(valor_carta(c) for c in cartas)
    ases  = sum(1 for c in cartas if _parse(c)[0]=="A")
    while total > 21 and ases:
        total -= 10; ases -= 1
    return total

# ── Dataclasses ───────────────────────────────────────────────────────────────
@dataclass
class JogadorBJ:
    user: discord.Member
    mao:  list = field(default_factory=list)
    aposta: int = 0
    parou:  bool = False
    estourou: bool = False
    blackjack: bool = False
    doubled:   bool = False

@dataclass
class MesaBJ:
    canal_id:    int
    estado:      str = "aguardando"
    jogadores:   list = field(default_factory=list)
    dealer_mao:  list = field(default_factory=list)
    baralho:     list = field(default_factory=list)
    iniciador_id: int = 0
    msg_id:      int = 0        # mensagem da mesa (editada a cada jogada)

    def get_jogador(self, uid):
        return next((j for j in self.jogadores if j.user.id==uid), None)

    def todos_terminaram(self):
        return all(j.parou or j.estourou or j.blackjack for j in self.jogadores)

    def proximo_jogador(self):
        return next((j for j in self.jogadores
                     if not j.parou and not j.estourou and not j.blackjack), None)

# ── Renderer helper ───────────────────────────────────────────────────────────
def _pl_data(mesa: MesaBJ, revelar_dealer=False):
    return [{"name":  j.user.display_name,
             "cards": j.mao,
             "value": calcular_mao(j.mao),
             "bet":   j.aposta,
             "status":"bj" if j.blackjack else "bust" if j.estourou else "stand" if j.parou else "",
             "active": False}
            for j in mesa.jogadores]

async def _render_send(canal, mesa: MesaBJ, hide=True, msg="", active_uid=None):
    """Renderiza a mesa e edita/cria a mensagem principal."""
    pl = _pl_data(mesa)
    if active_uid:
        for p,j in zip(pl, mesa.jogadores):
            p["active"] = (j.user.id == active_uid)
    dv = calcular_mao(mesa.dealer_mao) if not hide else 0
    buf = render_blackjack(mesa.dealer_mao, dv, pl,
                           hide_dealer_second=hide, message=msg)
    file = discord.File(buf, filename="mesa.png")
    if mesa.msg_id:
        try:
            m = await canal.fetch_message(mesa.msg_id)
            await m.delete()
        except Exception:
            pass
    m = await canal.send(file=file)
    mesa.msg_id = m.id
    return m

# ── Views ─────────────────────────────────────────────────────────────────────
class ApostaModal(discord.ui.Modal, title="Sua aposta"):
    aposta = discord.ui.TextInput(label="Fichas (mín 10)", min_length=1, max_length=5)
    def __init__(self, mesa):
        super().__init__()
        self.mesa = mesa
    async def on_submit(self, interaction: discord.Interaction):
        mesa = self.mesa
        jog  = mesa.get_jogador(interaction.user.id)
        if not jog:
            await interaction.response.send_message("Você não está nessa mesa.", ephemeral=True); return
        if jog.aposta > 0:
            await interaction.response.send_message("Já apostou!", ephemeral=True); return
        try:
            valor = int(self.aposta.value)
        except:
            await interaction.response.send_message("Valor inválido.", ephemeral=True); return
        if valor < 10:
            await interaction.response.send_message("Mínimo 10 fichas.", ephemeral=True); return
        saldo = get_fichas(interaction.user.id)
        if valor > saldo:
            await interaction.response.send_message(f"Sem fichas suficientes ({saldo}🪙).", ephemeral=True); return
        jog.aposta = valor
        todos = all(j.aposta>0 for j in mesa.jogadores)
        await interaction.response.send_message(
            f"✅ **{interaction.user.display_name}** apostou **{valor}🪙**"
            + (" — iniciando!" if todos else ""))
        if todos:
            await iniciar_rodada(interaction.channel, mesa)

class ApostarView(discord.ui.View):
    def __init__(self, mesa):
        super().__init__(timeout=90)
        self.mesa = mesa
    @discord.ui.button(label="💰 Apostar", style=discord.ButtonStyle.primary)
    async def apostar(self, interaction: discord.Interaction, btn: discord.ui.Button):
        jog = self.mesa.get_jogador(interaction.user.id)
        if not jog:
            await interaction.response.send_message("Você não está nessa mesa.", ephemeral=True); return
        if jog.aposta > 0:
            await interaction.response.send_message("Já apostou!", ephemeral=True); return
        await interaction.response.send_modal(ApostaModal(self.mesa))

class BJView(discord.ui.View):
    def __init__(self, mesa, jogador):
        super().__init__(timeout=60)
        self.mesa    = mesa
        self.jogador = jogador
        # Double só se tiver 2 cartas e fichas
        saldo = get_fichas(jogador.user.id)
        self.children[2].disabled = (len(jogador.mao)!=2 or saldo < jogador.aposta)

    @discord.ui.button(label="🤚 Hit / Pedir",    style=discord.ButtonStyle.secondary)
    async def hit(self, i: discord.Interaction, b):
        if i.user.id != self.jogador.user.id:
            await i.response.send_message("Não é sua vez!", ephemeral=True); return
        await i.response.defer(); self.stop()
        carta = self.mesa.baralho.pop()
        self.jogador.mao.append(carta)
        val = calcular_mao(self.jogador.mao)
        if val > 21:
            self.jogador.estourou = True
            await _render_send(i.channel, self.mesa, msg=f"💥 {self.jogador.user.display_name} estourou com {val}!")
            await avancar_turno(i.channel, self.mesa)
        elif val == 21:
            self.jogador.parou = True
            await _render_send(i.channel, self.mesa, active_uid=self.jogador.user.id,
                               msg=f"🌟 {self.jogador.user.display_name} atingiu 21!")
            await avancar_turno(i.channel, self.mesa)
        else:
            await pedir_turno(i.channel, self.mesa, self.jogador)

    @discord.ui.button(label="✋ Stand / Manter", style=discord.ButtonStyle.secondary)
    async def stand(self, i: discord.Interaction, b):
        if i.user.id != self.jogador.user.id:
            await i.response.send_message("Não é sua vez!", ephemeral=True); return
        await i.response.defer(); self.stop()
        self.jogador.parou = True
        val = calcular_mao(self.jogador.mao)
        await _render_send(i.channel, self.mesa, active_uid=self.jogador.user.id,
                           msg=f"✋ {self.jogador.user.display_name} parou com {val}.")
        await avancar_turno(i.channel, self.mesa)

    @discord.ui.button(label="2× Double / Dobrar", style=discord.ButtonStyle.secondary)
    async def double(self, i: discord.Interaction, b):
        if i.user.id != self.jogador.user.id:
            await i.response.send_message("Não é sua vez!", ephemeral=True); return
        saldo = get_fichas(self.jogador.user.id)
        if saldo < self.jogador.aposta:
            await i.response.send_message("Fichas insuficientes para dobrar.", ephemeral=True); return
        await i.response.defer(); self.stop()
        set_fichas(self.jogador.user.id, saldo - self.jogador.aposta)
        self.jogador.aposta *= 2
        self.jogador.doubled = True
        carta = self.mesa.baralho.pop()
        self.jogador.mao.append(carta)
        val = calcular_mao(self.jogador.mao)
        self.jogador.parou = True
        if val > 21: self.jogador.estourou = True
        await _render_send(i.channel, self.mesa, active_uid=self.jogador.user.id,
                           msg=f"2× {self.jogador.user.display_name} dobrou → {val} pts")
        await avancar_turno(i.channel, self.mesa)

    @discord.ui.button(label="🏳️ Surrender / Desistir", style=discord.ButtonStyle.danger)
    async def surrender(self, i: discord.Interaction, b):
        if i.user.id != self.jogador.user.id:
            await i.response.send_message("Não é sua vez!", ephemeral=True); return
        await i.response.defer(); self.stop()
        devolver = self.jogador.aposta // 2
        set_fichas(self.jogador.user.id, get_fichas(self.jogador.user.id) + devolver)
        self.jogador.parou    = True
        self.jogador.estourou = True
        self.jogador.aposta   = 0
        await _render_send(i.channel, self.mesa,
                           msg=f"🏳️ {self.jogador.user.display_name} desistiu. Recuperou {devolver}🪙.")
        await avancar_turno(i.channel, self.mesa)

class EntrarBJView(discord.ui.View):
    def __init__(self, mesa):
        super().__init__(timeout=90)
        self.mesa = mesa
    @discord.ui.button(label="🃏 Entrar", style=discord.ButtonStyle.success)
    async def entrar(self, i: discord.Interaction, b):
        mesa = self.mesa
        if mesa.get_jogador(i.user.id):
            await i.response.send_message("Já está na mesa!", ephemeral=True); return
        if len(mesa.jogadores) >= 4:
            await i.response.send_message("Mesa cheia! (máx 4)", ephemeral=True); return
        mesa.jogadores.append(JogadorBJ(user=i.user))
        await i.response.send_message(f"✅ **{i.user.display_name}** entrou! ({len(mesa.jogadores)} jogadores)")
    @discord.ui.button(label="▶️ Iniciar", style=discord.ButtonStyle.primary)
    async def iniciar(self, i: discord.Interaction, b):
        mesa = self.mesa
        if i.user.id != mesa.iniciador_id:
            await i.response.send_message("Só quem criou pode iniciar.", ephemeral=True); return
        if not mesa.jogadores:
            await i.response.send_message("Precisa de pelo menos 1 jogador.", ephemeral=True); return
        mesa.estado = "apostando"; self.stop()
        view = ApostarView(mesa)
        nomes = ", ".join(j.user.display_name for j in mesa.jogadores)
        await i.response.send_message(f"🃏 Mesa iniciada! Jogadores: **{nomes}**\nFaça suas apostas:", view=view)

class NovaRodadaBJView(discord.ui.View):
    def __init__(self, mesa):
        super().__init__(timeout=60)
        self.mesa = mesa
    @discord.ui.button(label="🔄 Nova rodada", style=discord.ButtonStyle.success)
    async def nova(self, i: discord.Interaction, b):
        mesa = self.mesa
        if not mesa.get_jogador(i.user.id):
            await i.response.send_message("Você não estava nessa mesa.", ephemeral=True); return
        self.stop()
        for j in mesa.jogadores:
            j.mao=[]; j.aposta=0; j.parou=False; j.estourou=False; j.blackjack=False; j.doubled=False
        mesa.dealer_mao=[]; mesa.msg_id=0
        await i.response.send_message("🃏 Nova rodada! Faça suas apostas:", view=ApostarView(mesa))
    @discord.ui.button(label="❌ Encerrar mesa", style=discord.ButtonStyle.danger)
    async def encerrar(self, i: discord.Interaction, b):
        mesas_bj.pop(self.mesa.canal_id, None); self.stop()
        await i.response.send_message("❌ Mesa encerrada.")

# ── Lógica ────────────────────────────────────────────────────────────────────
async def iniciar_rodada(canal, mesa: MesaBJ):
    mesa.baralho    = gerar_baralho()
    mesa.dealer_mao = []
    mesa.estado     = "jogando"
    for _ in range(2):
        for j in mesa.jogadores: j.mao.append(mesa.baralho.pop())
        mesa.dealer_mao.append(mesa.baralho.pop())
    for j in mesa.jogadores:
        set_fichas(j.user.id, get_fichas(j.user.id) - j.aposta)
        if calcular_mao(j.mao)==21: j.blackjack=True

    proximo = mesa.proximo_jogador()
    msg_txt = f"Vez de {proximo.user.display_name}!" if proximo else "Verificando blackjacks..."
    await _render_send(canal, mesa, hide=True,
                       active_uid=proximo.user.id if proximo else None,
                       msg=msg_txt)
    if proximo:
        await pedir_turno(canal, mesa, proximo)
    else:
        await vez_dealer(canal, mesa)

async def pedir_turno(canal, mesa: MesaBJ, jogador: JogadorBJ):
    registrar_atividade(mesa.canal_id, _timeout_cb)
    val  = calcular_mao(jogador.mao)
    view = BJView(mesa, jogador)
    await _render_send(canal, mesa, hide=True,
                       active_uid=jogador.user.id,
                       msg=f"Vez de {jogador.user.display_name} — {val} pts | Aposta: {jogador.aposta}🪙")
    await canal.send(f"{jogador.user.mention} escolha sua ação:", view=view, delete_after=65)

async def avancar_turno(canal, mesa: MesaBJ):
    proximo = mesa.proximo_jogador()
    if proximo:
        await pedir_turno(canal, mesa, proximo)
    else:
        await vez_dealer(canal, mesa)

async def vez_dealer(canal, mesa: MesaBJ):
    await _render_send(canal, mesa, hide=False, msg="🃏 Vez do Dealer...")
    await asyncio.sleep(1)
    while calcular_mao(mesa.dealer_mao) < 17:
        carta = mesa.baralho.pop()
        mesa.dealer_mao.append(carta)
        val = calcular_mao(mesa.dealer_mao)
        await _render_send(canal, mesa, hide=False, msg=f"Dealer puxou → {val}")
        await asyncio.sleep(1.2)

    dv = calcular_mao(mesa.dealer_mao)
    dest = dv>21
    linhas = []
    for j in mesa.jogadores:
        val  = calcular_mao(j.mao)
        nome = j.user.display_name
        if j.aposta == 0:
            linhas.append(f"🏳️ {nome} — desistiu")
        elif j.estourou:
            linhas.append(f"💥 {nome} — estourou. −{j.aposta}🪙")
        elif j.blackjack and dv!=21:
            g = int(j.aposta*2.5)
            set_fichas(j.user.id, get_fichas(j.user.id)+g)
            linhas.append(f"🌟 {nome} — Blackjack! +{g}🪙")
        elif dest or val>dv:
            g = j.aposta*2
            set_fichas(j.user.id, get_fichas(j.user.id)+g)
            linhas.append(f"🎉 {nome} — ganhou! +{g}🪙")
        elif val==dv:
            set_fichas(j.user.id, get_fichas(j.user.id)+j.aposta)
            linhas.append(f"🤝 {nome} — empate. Devolvido {j.aposta}🪙")
        else:
            linhas.append(f"😔 {nome} — perdeu. −{j.aposta}🪙")

    resultado = " · ".join(linhas)
    await _render_send(canal, mesa, hide=False, msg=resultado)
    cancelar_timeout(mesa.canal_id)

    for j in mesa.jogadores:
        val   = calcular_mao(j.mao)
        ganhou = not j.estourou and (dest or val>dv or j.blackjack)
        asyncio.create_task(registrar_resultado(
            j.user.id, j.user.display_name, "Blackjack 21", ganhou, j.aposta))

    await canal.send("Jogar de novo?", view=NovaRodadaBJView(mesa))

async def _timeout_cb(canal_id, _):
    mesas_bj.pop(canal_id, None)
    try:
        for g in _bot_bj.guilds:
            c = g.get_channel(canal_id)
            if c:
                await c.send("⏰ Mesa de **Blackjack** encerrada por inatividade.")
                break
    except: pass

_bot_bj = None

# ── Cog ───────────────────────────────────────────────────────────────────────
class BlackjackCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        global _bot_bj; _bot_bj = bot

    @app_commands.command(name="21", description="Abre uma mesa de Blackjack (até 4 jogadores)")
    async def cmd_21(self, interaction: discord.Interaction):
        cid = interaction.channel_id
        if not checar_canal(cid):
            await interaction.response.send_message("🎰 Use o canal do cassino!", ephemeral=True); return
        if cid in mesas_bj:
            await interaction.response.send_message("Já tem mesa aqui!", ephemeral=True); return
        mesa = MesaBJ(canal_id=cid, iniciador_id=interaction.user.id)
        mesa.jogadores.append(JogadorBJ(user=interaction.user))
        mesas_bj[cid] = mesa
        view = EntrarBJView(mesa)
        embed = discord.Embed(
            title="🃏 Blackjack — 21",
            description=(f"**{interaction.user.display_name}** abriu uma mesa!\n"
                         f"Clique em **Entrar** (até 4 jogadores) e depois **Iniciar**."),
            color=0x1a0a2e)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="21_encerrar", description="Encerra a mesa de Blackjack")
    async def cmd_encerrar(self, interaction: discord.Interaction):
        mesa = mesas_bj.pop(interaction.channel_id, None)
        if not mesa:
            await interaction.response.send_message("Sem mesa aqui.", ephemeral=True); return
        await interaction.response.send_message("❌ Mesa encerrada.")

async def setup(bot):
    await bot.add_cog(BlackjackCog(bot))
