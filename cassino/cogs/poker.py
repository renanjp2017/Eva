"""
poker.py — Texas Hold'em com mesa gótica renderizada.
Mesa única editada a cada jogada. 2-6 jogadores.
"""
import discord
from discord import app_commands
from discord.ext import commands
import random, asyncio
from dataclasses import dataclass, field
from typing import Optional
from .base import (get_fichas, set_fichas, checar_canal,
                   registrar_atividade, cancelar_timeout, FakeUser,
                   FICHAS_INICIAIS, registrar_resultado)
from .renderer import render_poker

mesas_poker: dict[int, "MesaPoker"] = {}

# ── Baralho ───────────────────────────────────────────────────────────────────
NAIPES = ["♠","♥","♦","♣"]
NUMS   = ["A","2","3","4","5","6","7","8","9","10","J","Q","K"]

def gerar_baralho():
    b=[f"{n}{s}" for n in NUMS for s in NAIPES]; random.shuffle(b); return b

def _parse(c): return (c[:-1],c[-1]) if c and c[-1] in "♠♥♦♣" else (c,"")

# ── Avaliação de mão ──────────────────────────────────────────────────────────
_RANK = {"2":2,"3":3,"4":4,"5":5,"6":6,"7":7,"8":8,"9":9,"10":10,"J":11,"Q":12,"K":13,"A":14}

def _ranks(cartas): return sorted([_RANK.get(_parse(c)[0],0) for c in cartas], reverse=True)

def _is_flush(cartas):
    suits=[_parse(c)[1] for c in cartas]
    return len(set(suits))==1

def _is_straight(rs):
    rs=sorted(set(rs),reverse=True)
    if len(rs)<5: return False
    for i in range(len(rs)-4):
        w=rs[i:i+5]
        if w[0]-w[4]==4 and len(set(w))==5: return True
    if set(rs)>={14,2,3,4,5}: return True
    return False

def avaliar_mao(cartas):
    """Retorna (categoria, kickers) para ordenação."""
    rs=_ranks(cartas)
    fl=_is_flush(cartas); st=_is_straight(rs)
    from collections import Counter
    cnt=Counter(rs)
    grps=sorted(cnt.items(),key=lambda x:(-x[1],-x[0]))
    freq=[g[1] for g in grps]; vals=[g[0] for g in grps]
    if fl and st: cat=8
    elif freq[0]==4: cat=7
    elif freq[:2]==[3,2]: cat=6
    elif fl: cat=5
    elif st: cat=4
    elif freq[0]==3: cat=3
    elif freq[:2]==[2,2]: cat=2
    elif freq[0]==2: cat=1
    else: cat=0
    return (cat,vals)

def melhor_mao_5(cartas7):
    from itertools import combinations
    return max(combinations(cartas7,5), key=lambda h: avaliar_mao(h))

def nome_mao(cat):
    return ["High Card","Par","Dois Pares","Trinca","Straight","Flush",
            "Full House","Quadra","Straight Flush"][cat]

# ── Dataclasses ───────────────────────────────────────────────────────────────
@dataclass
class JogadorPoker:
    user: object
    mao: list = field(default_factory=list)
    chips: int = 1000
    aposta_atual: int = 0
    total_apostado: int = 0
    fold: bool = False
    all_in: bool = False
    parou: bool = False

@dataclass
class MesaPoker:
    canal_id: int
    jogadores: list = field(default_factory=list)
    baralho: list = field(default_factory=list)
    community: list = field(default_factory=list)
    pot: int = 0
    aposta_max: int = 0
    stage: str = "aguardando"
    vez_idx: int = 0
    dealer_idx: int = 0
    small_blind: int = 10
    msg_id: int = 0
    iniciador_id: int = 0

    def get_jog(self, uid):
        return next((j for j in self.jogadores if j.user.id==uid), None)

    def ativos(self):
        return [j for j in self.jogadores if not j.fold]

    def proximo_ativo(self, start=None):
        idx = self.vez_idx if start is None else start
        n = len(self.jogadores)
        for _ in range(n):
            idx = (idx+1)%n
            j = self.jogadores[idx]
            if not j.fold and not j.all_in: return idx, j
        return None, None

# ── Render helper ─────────────────────────────────────────────────────────────
async def _render(canal, mesa: MesaPoker, msg="", revelar=False):
    registrar_atividade(mesa.canal_id, _timeout_cb)
    pl = []
    for j in mesa.jogadores:
        cartas = j.mao if revelar or not j.fold else []
        st = "fold" if j.fold else ("all-in" if j.all_in else "")
        ativo = mesa.jogadores[mesa.vez_idx].user.id == j.user.id if not revelar else False
        pl.append({"name":j.user.display_name,"cards":cartas,
                   "chips":j.chips,"bet":j.aposta_atual,
                   "status":st,"active":ativo,"folded":j.fold})
    buf = render_poker(mesa.community, pl, mesa.pot, mesa.stage, msg)
    file = discord.File(buf, filename="poker.png")
    if mesa.msg_id:
        try:
            m = await canal.fetch_message(mesa.msg_id); await m.delete()
        except: pass
    m = await canal.send(file=file)
    mesa.msg_id = m.id

# ── Views ─────────────────────────────────────────────────────────────────────
class EntrarPokerView(discord.ui.View):
    def __init__(self, mesa):
        super().__init__(timeout=120); self.mesa = mesa

    @discord.ui.button(label="🃏 Entrar", style=discord.ButtonStyle.success)
    async def entrar(self, i: discord.Interaction, b):
        mesa = self.mesa
        if mesa.get_jog(i.user.id):
            await i.response.send_message("Já está!", ephemeral=True); return
        if len(mesa.jogadores) >= 6:
            await i.response.send_message("Mesa cheia!", ephemeral=True); return
        chips = get_fichas(i.user.id)
        if chips < 100:
            await i.response.send_message("Precisa de pelo menos 100🪙.", ephemeral=True); return
        mesa.jogadores.append(JogadorPoker(user=i.user, chips=chips))
        await i.response.send_message(f"✅ **{i.user.display_name}** entrou com {chips}🪙! ({len(mesa.jogadores)}/6)")

    @discord.ui.button(label="▶️ Iniciar", style=discord.ButtonStyle.primary)
    async def iniciar(self, i: discord.Interaction, b):
        if i.user.id != self.mesa.iniciador_id:
            await i.response.send_message("Só quem criou.", ephemeral=True); return
        if len(self.mesa.jogadores) < 2:
            await i.response.send_message("Mínimo 2 jogadores.", ephemeral=True); return
        self.stop(); await i.response.defer()
        await iniciar_mao(i.channel, self.mesa)

    @discord.ui.button(label="❌ Cancelar", style=discord.ButtonStyle.danger)
    async def cancelar(self, i: discord.Interaction, b):
        mesas_poker.pop(self.mesa.canal_id, None); self.stop()
        await i.response.send_message("❌ Mesa cancelada.")


class AcaoPokerView(discord.ui.View):
    def __init__(self, mesa, jog):
        super().__init__(timeout=60)
        self.mesa = mesa; self.jog = jog
        pode_check = mesa.aposta_max == jog.aposta_atual
        self.children[0].label = "✔ Check" if pode_check else f"📞 Call ({mesa.aposta_max - jog.aposta_atual}🪙)"
        self.children[0].style = discord.ButtonStyle.secondary if pode_check else discord.ButtonStyle.primary

    @discord.ui.button(label="Call", style=discord.ButtonStyle.primary)
    async def call_check(self, i: discord.Interaction, b):
        if i.user.id != self.jog.user.id:
            await i.response.send_message("Não é sua vez!", ephemeral=True); return
        await i.response.defer(); self.stop()
        mesa = self.mesa; jog = self.jog
        diff = mesa.aposta_max - jog.aposta_atual
        if diff == 0:
            jog.parou = True
            await _render(i.channel, mesa, f"✔ {jog.user.display_name} deu check.")
        else:
            pagar = min(diff, jog.chips)
            jog.chips -= pagar; jog.aposta_atual += pagar; mesa.pot += pagar
            if jog.chips == 0: jog.all_in = True
            await _render(i.channel, mesa, f"📞 {jog.user.display_name} pagou {pagar}🪙.")
        await avancar_turno(i.channel, mesa)

    @discord.ui.button(label="⬆️ Raise", style=discord.ButtonStyle.secondary)
    async def raise_btn(self, i: discord.Interaction, b):
        if i.user.id != self.jog.user.id:
            await i.response.send_message("Não é sua vez!", ephemeral=True); return
        await i.response.send_modal(RaiseModal(self.mesa, self.jog)); self.stop()

    @discord.ui.button(label="❌ Fold", style=discord.ButtonStyle.danger)
    async def fold_btn(self, i: discord.Interaction, b):
        if i.user.id != self.jog.user.id:
            await i.response.send_message("Não é sua vez!", ephemeral=True); return
        await i.response.defer(); self.stop()
        self.jog.fold = True
        await _render(i.channel, self.mesa, f"❌ {self.jog.user.display_name} foldou.")
        if len(self.mesa.ativos()) == 1:
            await finalizar_mao(i.channel, self.mesa)
        else:
            await avancar_turno(i.channel, self.mesa)

    @discord.ui.button(label="🚀 All-in", style=discord.ButtonStyle.danger)
    async def allin(self, i: discord.Interaction, b):
        if i.user.id != self.jog.user.id:
            await i.response.send_message("Não é sua vez!", ephemeral=True); return
        await i.response.defer(); self.stop()
        jog=self.jog; mesa=self.mesa
        val=jog.chips; mesa.pot+=val; jog.aposta_atual+=val; jog.chips=0
        if jog.aposta_atual>mesa.aposta_max: mesa.aposta_max=jog.aposta_atual
        jog.all_in=True
        await _render(i.channel, mesa, f"🚀 {jog.user.display_name} ALL-IN {val}🪙!")
        await avancar_turno(i.channel, mesa)


class RaiseModal(discord.ui.Modal, title="Raise"):
    valor = discord.ui.TextInput(label="Valor total da sua aposta", min_length=1, max_length=6)
    def __init__(self, mesa, jog):
        super().__init__(); self.mesa=mesa; self.jog=jog
    async def on_submit(self, i: discord.Interaction):
        try: v=int(self.valor.value)
        except:
            await i.response.send_message("Inválido.", ephemeral=True); return
        jog=self.jog; mesa=self.mesa
        if v <= mesa.aposta_max:
            await i.response.send_message(f"Precisa ser maior que {mesa.aposta_max}.", ephemeral=True); return
        if v > jog.chips + jog.aposta_atual:
            await i.response.send_message("Sem chips.", ephimeral=True); return
        diff = v - jog.aposta_atual
        jog.chips -= diff; jog.aposta_atual = v; mesa.pot += diff; mesa.aposta_max = v
        for j in mesa.jogadores:
            if j != jog and not j.fold: j.parou = False
        await i.response.send_message(f"⬆️ {jog.user.display_name} raise para {v}🪙!")
        await _render(i.channel, mesa, f"⬆️ {jog.user.display_name} raise {v}🪙!")
        await avancar_turno(i.channel, mesa)

class NovaMAoView(discord.ui.View):
    def __init__(self, mesa):
        super().__init__(timeout=60); self.mesa=mesa
    @discord.ui.button(label="🔄 Nova mão",style=discord.ButtonStyle.success)
    async def nova(self,i:discord.Interaction,b):
        if not self.mesa.get_jog(i.user.id):
            await i.response.send_message("Você não está.",ephemeral=True); return
        self.stop(); await i.response.defer()
        self.mesa.jogadores=[j for j in self.mesa.jogadores if j.chips>0]
        if len(self.mesa.jogadores)<2:
            mesas_poker.pop(self.mesa.canal_id,None)
            await i.channel.send("❌ Jogadores insuficientes. Mesa encerrada.")
            return
        for j in self.mesa.jogadores:
            j.mao=[]; j.aposta_atual=0; j.total_apostado=0
            j.fold=False; j.all_in=False; j.parou=False
        self.mesa.community=[]; self.mesa.pot=0; self.mesa.aposta_max=0; self.mesa.msg_id=0
        await iniciar_mao(i.channel,self.mesa)
    @discord.ui.button(label="❌ Encerrar",style=discord.ButtonStyle.danger)
    async def enc(self,i:discord.Interaction,b):
        mesas_poker.pop(self.mesa.canal_id,None); self.stop()
        await i.response.send_message("❌ Mesa encerrada.")

# ── Lógica ────────────────────────────────────────────────────────────────────
async def iniciar_mao(canal, mesa: MesaPoker):
    mesa.baralho=gerar_baralho(); mesa.stage="pre-flop"
    mesa.community=[]; mesa.pot=0; mesa.aposta_max=mesa.small_blind*2
    n=len(mesa.jogadores)
    sb_idx=(mesa.dealer_idx+1)%n; bb_idx=(mesa.dealer_idx+2)%n
    for j in mesa.jogadores: j.mao=[_parse_deal(mesa) for _ in range(2)]; j.aposta_atual=0; j.parou=False
    # Blinds
    sb=mesa.jogadores[sb_idx]; bb=mesa.jogadores[bb_idx]
    _pagar(sb,mesa,mesa.small_blind)
    _pagar(bb,mesa,mesa.small_blind*2)
    mesa.vez_idx=(bb_idx+1)%n
    for j in mesa.jogadores:
        try: await j.user.send("🃏 **Suas cartas:** " + "  ".join(f"`{c}`" for c in j.mao))
        except: pass
    await _render(canal, mesa, f"Pre-flop | SB: {sb.user.display_name} | BB: {bb.user.display_name}")
    await pedir_acao(canal, mesa)

def _parse_deal(mesa: MesaPoker):
    return mesa.baralho.pop()

def _pagar(jog: JogadorPoker, mesa: MesaPoker, val: int):
    v=min(val,jog.chips); jog.chips-=v; jog.aposta_atual+=v; mesa.pot+=v
    if jog.chips==0: jog.all_in=True

async def pedir_acao(canal, mesa: MesaPoker):
    while True:
        idx=mesa.vez_idx; jog=mesa.jogadores[idx]
        if not jog.fold and not jog.all_in: break
        mesa.vez_idx=(mesa.vez_idx+1)%len(mesa.jogadores)
        # se voltou ao início sem encontrar ninguém
        if _rodada_encerrada(mesa):
            await proxima_fase(canal,mesa); return

    await _render(canal, mesa, f"Vez de {jog.user.display_name} | Pot: {mesa.pot}🪙")
    view = AcaoPokerView(mesa, jog)
    await canal.send(f"{jog.user.mention} — sua vez! Pot: **{mesa.pot}🪙**",
                     view=view, delete_after=65)

def _rodada_encerrada(mesa: MesaPoker):
    ativos = [j for j in mesa.jogadores if not j.fold and not j.all_in]
    if not ativos: return True
    return all(j.parou and j.aposta_atual==mesa.aposta_max for j in ativos)

async def avancar_turno(canal, mesa: MesaPoker):
    if len(mesa.ativos())==1:
        await finalizar_mao(canal,mesa); return
    mesa.vez_idx=(mesa.vez_idx+1)%len(mesa.jogadores)
    if _rodada_encerrada(mesa):
        await proxima_fase(canal,mesa)
    else:
        await pedir_acao(canal,mesa)

async def proxima_fase(canal, mesa: MesaPoker):
    for j in mesa.jogadores:
        j.aposta_atual=0; j.parou=False
    mesa.aposta_max=0
    if mesa.stage=="pre-flop":
        mesa.stage="flop"; mesa.community=[mesa.baralho.pop() for _ in range(3)]
    elif mesa.stage=="flop":
        mesa.stage="turn"; mesa.community.append(mesa.baralho.pop())
    elif mesa.stage=="turn":
        mesa.stage="river"; mesa.community.append(mesa.baralho.pop())
    elif mesa.stage=="river":
        await showdown(canal,mesa); return
    mesa.vez_idx=(mesa.dealer_idx+1)%len(mesa.jogadores)
    await _render(canal,mesa,f"{mesa.stage.title()} — {len(mesa.community)} cartas comunitárias")
    await pedir_acao(canal,mesa)

async def showdown(canal, mesa: MesaPoker):
    mesa.stage="showdown"
    vencedores=[]; melhor=None
    for j in mesa.ativos():
        todas=j.mao+mesa.community
        mao5=melhor_mao_5(todas)
        val=avaliar_mao(mao5)
        if melhor is None or val>melhor:
            melhor=val; vencedores=[j]
        elif val==melhor:
            vencedores.append(j)
    premio=mesa.pot//len(vencedores)
    for v in vencedores:
        v.chips+=premio
        set_fichas(v.user.id,v.chips)
    cat=melhor[0] if melhor else 0
    nomes=", ".join(v.user.display_name for v in vencedores)
    msg=f"🏆 {nomes} venceu! {nome_mao(cat)} — {premio}🪙 cada"
    await _render(canal,mesa,msg,revelar=True)
    cancelar_timeout(mesa.canal_id)
    mesa.dealer_idx=(mesa.dealer_idx+1)%len(mesa.jogadores)
    await canal.send("Nova mão?",view=NovaMAoView(mesa))

async def finalizar_mao(canal,mesa:MesaPoker):
    venc=mesa.ativos()[0]; venc.chips+=mesa.pot
    set_fichas(venc.user.id,venc.chips)
    await _render(canal,mesa,f"🏆 {venc.user.display_name} venceu o pot de {mesa.pot}🪙!")
    cancelar_timeout(mesa.canal_id)
    mesa.dealer_idx=(mesa.dealer_idx+1)%len(mesa.jogadores)
    await canal.send("Nova mão?",view=NovaMAoView(mesa))

async def _timeout_cb(canal_id,_):
    mesas_poker.pop(canal_id,None)
    try:
        for g in _bot_p.guilds:
            c=g.get_channel(canal_id)
            if c: await c.send("⏰ Poker encerrado por inatividade."); break
    except: pass
_bot_p=None

# ── Cog ───────────────────────────────────────────────────────────────────────
class PokerCog(commands.Cog):
    def __init__(self,bot):
        self.bot=bot; global _bot_p; _bot_p=bot

    @app_commands.command(name="poker",description="Texas Hold'em (2-6 jogadores)")
    async def cmd_poker(self,interaction:discord.Interaction):
        cid=interaction.channel_id
        if not checar_canal(cid):
            await interaction.response.send_message("🎰 Use o canal do cassino!",ephemeral=True); return
        if cid in mesas_poker:
            await interaction.response.send_message("Já tem mesa aqui!",ephemeral=True); return
        mesa=MesaPoker(canal_id=cid,iniciador_id=interaction.user.id)
        chips=get_fichas(interaction.user.id)
        mesa.jogadores.append(JogadorPoker(user=interaction.user,chips=chips))
        mesas_poker[cid]=mesa
        embed=discord.Embed(title="♠️ Texas Hold'em",
                            description=f"**{interaction.user.display_name}** abriu mesa!\n"
                                        f"Clique **Entrar** (2-6 jogadores) e depois **Iniciar**.",
                            color=0x0a1a0a)
        await interaction.response.send_message(embed=embed,view=EntrarPokerView(mesa))

    @app_commands.command(name="minhas_cartas",description="Veja suas cartas (privado)")
    async def cmd_cartas(self,interaction:discord.Interaction):
        mesa=mesas_poker.get(interaction.channel_id)
        if not mesa:
            await interaction.response.send_message("Sem mesa aqui.",ephemeral=True); return
        jog=mesa.get_jog(interaction.user.id)
        if not jog or not jog.mao:
            await interaction.response.send_message("Sem cartas.",ephemeral=True); return
        await interaction.response.send_message(
            "🃏 " + "  ".join(f"`{c}`" for c in jog.mao),ephemeral=True)

    @app_commands.command(name="poker_encerrar",description="Encerra mesa de poker")
    async def cmd_encerrar(self,interaction:discord.Interaction):
        mesa=mesas_poker.pop(interaction.channel_id,None)
        if not mesa:
            await interaction.response.send_message("Sem mesa aqui.",ephemeral=True); return
        await interaction.response.send_message("❌ Mesa encerrada.")

async def setup(bot):
    await bot.add_cog(PokerCog(bot))
