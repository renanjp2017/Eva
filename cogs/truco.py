"""
truco.py — Truco Paulista com mesa gótica renderizada.
Mesa única editada a cada jogada. Modos: 1v1, 2v2, vs IA.
"""
import discord
from discord import app_commands
from discord.ext import commands
import random, asyncio
from dataclasses import dataclass, field
from typing import Optional
from .base import (get_fichas, set_fichas, checar_canal,
                   registrar_atividade, cancelar_timeout, FakeUser)
from .renderer import render_truco

jogos: dict[int, "JogoTruco"] = {}

# ── Baralho ───────────────────────────────────────────────────────────────────
NAIPES  = ["♠","♥","♦","♣"]
NUMEROS = ["4","5","6","7","Q","J","K","A","2","3"]
MANILHAS_PAULISTA = ["4♣","7♥","A♠","7♦"]
VALORES = {
    "4♣":14,"7♥":13,"A♠":12,"7♦":11,
    "3":10,"2":9,"A":8,"K":7,"J":6,"Q":5,
    "7":4,"6":3,"5":2,"4":1,
}

def gerar_baralho():
    return [f"{n}{s}" for n in NUMEROS for s in NAIPES]

def valor_carta(carta):
    if carta in VALORES: return VALORES[carta]
    return VALORES.get(carta[:-1], 0)

def fmt_carta(c): return f"`{c}`"

# ── Dataclasses ───────────────────────────────────────────────────────────────
@dataclass
class Equipe:
    nome: str
    jogadores: list = field(default_factory=list)
    pontos: int = 0

@dataclass
class JogoTruco:
    canal_id: int
    modo: str
    equipe1: Equipe = field(default_factory=lambda: Equipe("Time 1"))
    equipe2: Equipe = field(default_factory=lambda: Equipe("Time 2"))
    maos:    dict  = field(default_factory=dict)
    mesa:    list  = field(default_factory=list)    # [(nome, carta)]
    rodada:  int   = 1
    vez:     int   = 0
    ordem:   list  = field(default_factory=list)
    estado:  str   = "aguardando"
    valor_rodada: int = 1
    truco_por: Optional[int] = None
    vitorias_rodada: list = field(default_factory=list)
    primeiro: int  = 0
    msg_id:  int   = 0

    def jogador_atual(self):
        return self.ordem[self.vez % len(self.ordem)]

    def equipe_de(self, uid):
        if uid in [p.id for p in self.equipe1.jogadores]: return self.equipe1
        if uid in [p.id for p in self.equipe2.jogadores]: return self.equipe2
        return None

    def adversaria(self, uid):
        eq = self.equipe_de(uid)
        return self.equipe2 if eq == self.equipe1 else self.equipe1

# ── Render helper ─────────────────────────────────────────────────────────────
async def _render(canal, jogo: JogoTruco, msg="", view=None):
    registrar_atividade(jogo.canal_id, _timeout_cb)
    atual = jogo.jogador_atual()
    buf = render_truco(
        jogo.equipe1.nome, jogo.equipe1.pontos,
        jogo.equipe2.nome, jogo.equipe2.pontos,
        jogo.valor_rodada, jogo.vitorias_rodada,
        [(nome, carta) for nome, carta in jogo.mesa],
        atual.display_name, jogo.rodada, msg)
    file = discord.File(buf, filename="truco.png")
    if jogo.msg_id:
        try:
            m = await canal.fetch_message(jogo.msg_id)
            await m.delete()
        except: pass
    kwargs = {"file": file}
    if view: kwargs["view"] = view
    m = await canal.send(**kwargs)
    jogo.msg_id = m.id

# ── Distribuição ──────────────────────────────────────────────────────────────
def _distribuir(jogo: JogoTruco):
    baralho = gerar_baralho(); random.shuffle(baralho)
    jogo.maos = {}
    for i, j in enumerate(jogo.ordem):
        jogo.maos[j.id] = baralho[i*3:(i+1)*3]
    jogo.mesa = []; jogo.vitorias_rodada = []
    jogo.rodada = 1; jogo.valor_rodada = 1
    jogo.truco_por = None; jogo.estado = "jogando"
    jogo.vez = jogo.primeiro

async def _enviar_maos(jogo: JogoTruco):
    for j in jogo.ordem:
        cartas = jogo.maos.get(j.id, [])
        try:
            await j.send("🃏 **Suas cartas:** " + "  ".join(fmt_carta(c) for c in cartas)
                         + "\n\nJogue pelo canal usando os botões.")
        except: pass

# ── Views ─────────────────────────────────────────────────────────────────────
class EntrarView(discord.ui.View):
    def __init__(self, jogo):
        super().__init__(timeout=120); self.jogo = jogo

    @discord.ui.button(label="🃏 Entrar", style=discord.ButtonStyle.success)
    async def entrar(self, i: discord.Interaction, b):
        jogo = self.jogo
        todos = jogo.equipe1.jogadores + jogo.equipe2.jogadores
        if i.user in todos:
            await i.response.send_message("Já está no jogo!", ephemeral=True); return
        max_j = 2 if jogo.modo == "1v1" else 4
        if len(todos) >= max_j:
            await i.response.send_message("Jogo cheio!", ephemeral=True); return
        if len(jogo.equipe1.jogadores) <= len(jogo.equipe2.jogadores):
            jogo.equipe1.jogadores.append(i.user); eq = jogo.equipe1.nome
        else:
            jogo.equipe2.jogadores.append(i.user); eq = jogo.equipe2.nome
        todos = jogo.equipe1.jogadores + jogo.equipe2.jogadores
        await i.response.send_message(
            f"✅ **{i.user.display_name}** entrou no **{eq}**! ({len(todos)}/{max_j})")
        if len(todos) == max_j:
            self.stop(); await _iniciar(i.channel, jogo)

    @discord.ui.button(label="❌ Cancelar", style=discord.ButtonStyle.danger)
    async def cancelar(self, i: discord.Interaction, b):
        jogos.pop(self.jogo.canal_id, None); self.stop()
        await i.response.send_message("❌ Jogo cancelado.")


class CartaButton(discord.ui.Button):
    def __init__(self, carta, jogo, uid):
        red = carta[-1] in ("♥","♦")
        super().__init__(label=carta,
                         style=discord.ButtonStyle.danger if red else discord.ButtonStyle.secondary,
                         custom_id=f"tc_{uid}_{carta}")
        self.carta = carta; self.jogo = jogo; self.uid = uid

    async def callback(self, i: discord.Interaction):
        if i.user.id != self.uid:
            await i.response.send_message("Não é sua vez!", ephemeral=True); return
        await i.response.defer(); self.view.stop()
        await processar_jogada(i.channel, self.jogo, self.uid, self.carta)


class JogarView(discord.ui.View):
    def __init__(self, jogo, uid):
        super().__init__(timeout=60)
        self.jogo = jogo; self.uid = uid
        for carta in jogo.maos.get(uid, []):
            self.add_item(CartaButton(carta, jogo, uid))

    @discord.ui.button(label="😤 Truco!", style=discord.ButtonStyle.primary, row=1)
    async def truco(self, i: discord.Interaction, b):
        jogo = self.jogo
        if i.user.id != self.uid:
            await i.response.send_message("Não é sua vez!", ephemeral=True); return
        escala = [1,3,6,9,12]
        idx = escala.index(jogo.valor_rodada) if jogo.valor_rodada in escala else 0
        if idx >= len(escala)-1:
            await i.response.send_message("Já no máximo!", ephemeral=True); return
        prox  = escala[idx+1]
        grito = {3:"Truco!",6:"Seis!",9:"Nove!",12:"Doze!"}.get(prox, f"{prox}!")
        jogo.truco_por = i.user.id; jogo.estado = "truco_pedido"
        adv = jogo.adversaria(i.user.id)
        self.stop()
        await i.response.send_message(
            f"😤 **{i.user.display_name}** gritou **{grito}**\n"
            f"**{adv.nome}**, aceita, corre ou aumenta?",
            view=TrucoRespostaView(jogo, i.user.id))


class TrucoRespostaView(discord.ui.View):
    def __init__(self, jogo, pedidor_id):
        super().__init__(timeout=30)
        self.jogo = jogo; self.pedidor_id = pedidor_id

    async def _pode(self, i):
        adv = self.jogo.adversaria(self.pedidor_id)
        if i.user not in adv.jogadores:
            await i.response.send_message("Não é você que decide!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ Aceitar", style=discord.ButtonStyle.success)
    async def aceitar(self, i: discord.Interaction, b):
        if not await self._pode(i): return
        escala=[1,3,6,9,12]; idx=escala.index(self.jogo.valor_rodada) if self.jogo.valor_rodada in escala else 0
        self.jogo.valor_rodada=escala[min(idx+1,4)]
        self.jogo.estado="jogando"; self.stop()
        await i.response.send_message(f"✅ Aceito! Vale **{self.jogo.valor_rodada}pts**")
        await _render(i.channel, self.jogo)
        await pedir_jogada(i.channel, self.jogo)

    @discord.ui.button(label="🏃 Correr", style=discord.ButtonStyle.danger)
    async def correr(self, i: discord.Interaction, b):
        if not await self._pode(i): return
        eq_ped = self.jogo.equipe_de(self.pedidor_id)
        pts = self.jogo.valor_rodada; eq_ped.pontos += pts
        self.jogo.estado="jogando"; self.stop()
        await i.response.send_message(f"🏃 Correu! **{eq_ped.nome}** +{pts}pts")
        await nova_rodada(i.channel, self.jogo)

    @discord.ui.button(label="⬆️ Aumentar", style=discord.ButtonStyle.primary)
    async def aumentar(self, i: discord.Interaction, b):
        if not await self._pode(i): return
        escala=[1,3,6,9,12]; idx=escala.index(self.jogo.valor_rodada) if self.jogo.valor_rodada in escala else 0
        if idx >= 3:
            await i.response.send_message("Não dá mais!", ephemeral=True); return
        prox=escala[idx+2]; self.stop()
        grito={6:"Seis!",9:"Nove!",12:"Doze!"}.get(prox,f"{prox}!")
        self.jogo.truco_por=i.user.id
        eq_orig=self.jogo.equipe_de(self.pedidor_id)
        await i.response.send_message(
            f"⬆️ **{i.user.display_name}** quer **{grito}**\n"
            f"**{eq_orig.nome}**, aceita ou corre?",
            view=TrucoRespostaView(self.jogo, i.user.id))


class NovaRodadaView(discord.ui.View):
    def __init__(self, jogo):
        super().__init__(timeout=60); self.jogo = jogo

    @discord.ui.button(label="🔄 Continuar", style=discord.ButtonStyle.success)
    async def continuar(self, i: discord.Interaction, b):
        todos = self.jogo.equipe1.jogadores + self.jogo.equipe2.jogadores
        if i.user not in todos:
            await i.response.send_message("Você não está no jogo.", ephemeral=True); return
        self.stop(); await i.response.defer()
        await nova_rodada(i.channel, self.jogo)

    @discord.ui.button(label="❌ Encerrar", style=discord.ButtonStyle.danger)
    async def encerrar(self, i: discord.Interaction, b):
        jogos.pop(self.jogo.canal_id, None); self.stop()
        await i.response.send_message("❌ Jogo encerrado.")

# ── Lógica ────────────────────────────────────────────────────────────────────
async def _iniciar(canal, jogo: JogoTruco):
    all_j = jogo.equipe1.jogadores + jogo.equipe2.jogadores
    if jogo.modo == "1v1":
        jogo.ordem = [jogo.equipe1.jogadores[0], jogo.equipe2.jogadores[0]]
    else:
        jogo.ordem = [jogo.equipe1.jogadores[0], jogo.equipe2.jogadores[0],
                      jogo.equipe1.jogadores[1], jogo.equipe2.jogadores[1]]
    jogo.equipe1.nome = f"Time {jogo.equipe1.jogadores[0].display_name}"
    jogo.equipe2.nome = f"Time {jogo.equipe2.jogadores[0].display_name}"
    jogo.primeiro = 0
    _distribuir(jogo)
    await _enviar_maos(jogo)
    await canal.send(f"🃏 Jogo começou! Cartas enviadas por DM.\n"
                     f"**{jogo.equipe1.nome}** vs **{jogo.equipe2.nome}**")
    await _render(canal, jogo, f"Vez de {jogo.jogador_atual().display_name}")
    await pedir_jogada(canal, jogo)

async def pedir_jogada(canal, jogo: JogoTruco):
    if jogo.estado != "jogando": return
    atual = jogo.jogador_atual()
    cartas = jogo.maos.get(atual.id, [])
    if not cartas: return
    view = JogarView(jogo, atual.id)
    await canal.send(f"{atual.mention} — escolha sua carta ou **Truco!**",
                     view=view, delete_after=65)

async def processar_jogada(canal, jogo: JogoTruco, uid, carta):
    cartas = jogo.maos.get(uid, [])
    if carta not in cartas: return
    cartas.remove(carta)
    jogador = discord.utils.get(jogo.ordem, id=uid)
    jogo.mesa.append((jogador.display_name, carta))

    n = len(jogo.ordem)
    if len(jogo.mesa) < n:
        jogo.vez += 1
        await _render(canal, jogo, f"{jogador.display_name} jogou {carta}")
        await pedir_jogada(canal, jogo)
        return

    # Resolve mão
    melhor_uid, melhor_val, empate = None, -1, False
    for uid2, c2 in jogo.mesa:
        j2 = discord.utils.get(jogo.ordem, display_name=uid2)
        v2 = valor_carta(c2)
        if v2 > melhor_val: melhor_val, melhor_uid, empate = v2, j2.id if j2 else uid2, False
        elif v2 == melhor_val: empate = True

    if empate:
        jogo.vitorias_rodada.append("Empate")
        await _render(canal, jogo, "🤝 Empate na mão!")
    else:
        eq_venc = jogo.equipe_de(melhor_uid)
        jogo.vitorias_rodada.append(eq_venc.nome if eq_venc else "?")
        await _render(canal, jogo, f"🏆 {eq_venc.nome if eq_venc else '?'} venceu a mão!")

    jogo.mesa = []
    # Checa vencedor da rodada
    v = jogo.vitorias_rodada
    e1c, e2c = v.count(jogo.equipe1.nome), v.count(jogo.equipe2.nome)
    venc_rodada = None
    if e1c >= 2: venc_rodada = jogo.equipe1
    elif e2c >= 2: venc_rodada = jogo.equipe2
    elif len(v) == 3:
        if e1c > e2c: venc_rodada = jogo.equipe1
        elif e2c > e1c: venc_rodada = jogo.equipe2
        elif v[0] != "Empate":
            nome0 = v[0]
            venc_rodada = jogo.equipe1 if jogo.equipe1.nome==nome0 else jogo.equipe2
        else: venc_rodada = jogo.equipe1

    if venc_rodada:
        venc_rodada.pontos += jogo.valor_rodada
        await _render(canal, jogo,
                      f"🎉 {venc_rodada.nome} venceu a rodada! +{jogo.valor_rodada}pts | "
                      f"Placar: {jogo.equipe1.pontos} x {jogo.equipe2.pontos}")
        if jogo.equipe1.pontos >= 12 or jogo.equipe2.pontos >= 12:
            venc_final = jogo.equipe1 if jogo.equipe1.pontos >= 12 else jogo.equipe2
            await canal.send(f"🏆🏆🏆 **{venc_final.nome} GANHOU O JOGO!** 🏆🏆🏆\n"
                             f"Placar: {jogo.equipe1.pontos} x {jogo.equipe2.pontos}",
                             view=NovaRodadaView(jogo))
            jogos.pop(jogo.canal_id, None)
        else:
            await canal.send("Continuar?", view=NovaRodadaView(jogo))
    else:
        jogo.rodada += 1; jogo.vez += 1
        await pedir_jogada(canal, jogo)

async def nova_rodada(canal, jogo: JogoTruco):
    await asyncio.sleep(1)
    jogo.primeiro = (jogo.primeiro + 1) % len(jogo.ordem)
    _distribuir(jogo)
    await _enviar_maos(jogo)
    await _render(canal, jogo, f"🔄 Nova rodada! Vez de {jogo.jogador_atual().display_name}")
    await pedir_jogada(canal, jogo)

async def _timeout_cb(canal_id, _):
    jogos.pop(canal_id, None)
    try:
        for g in _bot_t.guilds:
            c = g.get_channel(canal_id)
            if c: await c.send("⏰ Truco encerrado por inatividade."); break
    except: pass
_bot_t = None

# ── Cog ───────────────────────────────────────────────────────────────────────
class TrucoCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot; global _bot_t; _bot_t = bot

    @app_commands.command(name="truco", description="Truco Paulista (1v1 ou 2v2)")
    @app_commands.describe(modo="Modo de jogo")
    @app_commands.choices(modo=[
        app_commands.Choice(name="1v1", value="1v1"),
        app_commands.Choice(name="2v2", value="2v2"),
    ])
    async def cmd_truco(self, interaction: discord.Interaction, modo: str = "1v1"):
        cid = interaction.channel_id
        if not checar_canal(cid):
            await interaction.response.send_message("🎰 Use o canal do cassino!", ephemeral=True); return
        if cid in jogos:
            await interaction.response.send_message("Já tem jogo aqui! Use `/encerrar`.", ephemeral=True); return
        jogo = JogoTruco(canal_id=cid, modo=modo)
        jogo.equipe1.jogadores.append(interaction.user)
        jogos[cid] = jogo
        max_j = 2 if modo=="1v1" else 4
        embed = discord.Embed(title="🃏 Truco Paulista",
                              description=f"**{interaction.user.display_name}** criou um jogo **{modo}**!\n"
                                          f"Jogadores: 1/{max_j}\nClique em **Entrar** para participar.",
                              color=0x2B0a0a)
        await interaction.response.send_message(embed=embed, view=EntrarView(jogo))

    @app_commands.command(name="truco_solo", description="Truco solo contra a IA")
    async def cmd_solo(self, interaction: discord.Interaction):
        cid = interaction.channel_id
        if not checar_canal(cid):
            await interaction.response.send_message("🎰 Use o canal do cassino!", ephemeral=True); return
        if cid in jogos:
            await interaction.response.send_message("Já tem jogo aqui!", ephemeral=True); return
        jogo = JogoTruco(canal_id=cid, modo="1v1")
        jogo.equipe1.jogadores.append(interaction.user)
        ia = FakeUser("🤖 IA Truco", 999999997)
        jogo.equipe2.jogadores.append(ia)
        jogos[cid] = jogo
        await interaction.response.send_message("🤖 **Truco Solo** — você vs IA. Iniciando...")
        await _iniciar(interaction.channel, jogo)

    @app_commands.command(name="minha_mao", description="Veja suas cartas (privado)")
    async def cmd_mao(self, interaction: discord.Interaction):
        jogo = jogos.get(interaction.channel_id)
        if not jogo:
            await interaction.response.send_message("Sem jogo aqui.", ephemeral=True); return
        cartas = jogo.maos.get(interaction.user.id)
        if not cartas:
            await interaction.response.send_message("Sem cartas.", ephemeral=True); return
        await interaction.response.send_message(
            "🃏 " + "  ".join(fmt_carta(c) for c in cartas), ephemeral=True)

    @app_commands.command(name="encerrar", description="Encerra o jogo atual")
    async def cmd_encerrar(self, interaction: discord.Interaction):
        jogo = jogos.pop(interaction.channel_id, None)
        if not jogo:
            await interaction.response.send_message("Sem jogo aqui.", ephemeral=True); return
        await interaction.response.send_message("❌ Jogo encerrado.")

async def setup(bot):
    await bot.add_cog(TrucoCog(bot))
