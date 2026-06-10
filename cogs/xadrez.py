"""
xadrez.py — Xadrez com mesa gótica renderizada.
Mesa única editada a cada jogada.
Modos: 1v1, vs IA. Pedra-papel-tesoura determina quem começa e cor.
"""
import discord
from discord import app_commands
from discord.ext import commands
import random, asyncio
from dataclasses import dataclass, field
from typing import Optional
from .base import checar_canal, registrar_atividade, cancelar_timeout
from .renderer import render_xadrez

partidas: dict[int, "PartidaXadrez"] = {}

# ── Tabuleiro ─────────────────────────────────────────────────────────────────
EMOJIS = {
    ('b','K'):'♔',('b','Q'):'♕',('b','R'):'♖',
    ('b','B'):'♗',('b','N'):'♘',('b','P'):'♙',
    ('p','K'):'♚',('p','Q'):'♛',('p','R'):'♜',
    ('p','B'):'♝',('p','N'):'♞',('p','P'):'♟',
}

def tabuleiro_inicial():
    t={}
    ordem=['R','N','B','Q','K','B','N','R']
    for c,l in [('p',7),('b',0)]:
        for col,tipo in enumerate(ordem): t[(col,l)]=(c,tipo)
        pl=6 if c=='p' else 1
        for col in range(8): t[(col,pl)]=(c,'P')
    return t

def movimentos_peca(tab,pos,cor,ep=None):
    if pos not in tab: return []
    cor2,tipo=tab[pos]
    if cor2!=cor: return []
    col,lin=pos; movs=[]
    def add(p):
        if 0<=p[0]<=7 and 0<=p[1]<=7:
            if p not in tab or tab[p][0]!=cor: movs.append(p)
    def slide(dirs):
        for dc,dl in dirs:
            c2,l2=col+dc,lin+dl
            while 0<=c2<=7 and 0<=l2<=7:
                p=(c2,l2)
                if p in tab:
                    if tab[p][0]!=cor: movs.append(p)
                    break
                movs.append(p); c2+=dc; l2+=dl
    if tipo=='P':
        d=1 if cor=='b' else -1
        f=(col,lin+d)
        if f not in tab and 0<=f[1]<=7:
            movs.append(f)
            ini=1 if cor=='b' else 6
            f2=(col,lin+2*d)
            if lin==ini and f2 not in tab: movs.append(f2)
        for dc in(-1,1):
            a=(col+dc,lin+d)
            if 0<=a[0]<=7 and 0<=a[1]<=7:
                if (a in tab and tab[a][0]!=cor) or (ep and a==ep): movs.append(a)
    elif tipo=='N':
        for dc,dl in[(-2,-1),(-2,1),(-1,-2),(-1,2),(1,-2),(1,2),(2,-1),(2,1)]: add((col+dc,lin+dl))
    elif tipo=='B': slide([(1,1),(1,-1),(-1,1),(-1,-1)])
    elif tipo=='R': slide([(1,0),(-1,0),(0,1),(0,-1)])
    elif tipo=='Q': slide([(1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)])
    elif tipo=='K':
        for dc in(-1,0,1):
            for dl in(-1,0,1):
                if dc==0 and dl==0: continue
                add((col+dc,lin+dl))
    return movs

def rei_em_xeque(tab,cor):
    rp=next((p for p,v in tab.items() if v==(cor,'K')),None)
    if not rp: return False
    op='p' if cor=='b' else 'b'
    return any(rp in movimentos_peca(tab,p,op) for p in tab if tab[p][0]==op)

def ia_jogar(tab,cor,ep=None):
    VALOR={'P':1,'N':3,'B':3,'R':5,'Q':9,'K':100}
    pecas=[(p,tab[p]) for p in tab if tab[p][0]==cor]
    random.shuffle(pecas)
    melhor=None; mv=-999
    for pos,(c,t) in pecas:
        for dest in movimentos_peca(tab,pos,cor,ep):
            t2=dict(tab); t2[dest]=t2.pop(pos)
            if rei_em_xeque(t2,cor): continue
            g=VALOR.get(tab.get(dest,('x','P'))[1],0) if dest in tab else 0
            op='p' if cor=='b' else 'b'
            if rei_em_xeque(t2,op): g+=0.5
            r=random.uniform(0,0.3)
            if g+r>mv: mv=g+r; melhor=(pos,dest)
    return melhor

# ── Dataclass ─────────────────────────────────────────────────────────────────
@dataclass
class PartidaXadrez:
    canal_id:    int
    branco_id:   int
    preto_id:    int
    branco_nome: str
    preto_nome:  str
    tabuleiro:   dict = field(default_factory=tabuleiro_inicial)
    vez:         str  = 'b'
    sel:         object = None
    movs:        list = field(default_factory=list)
    en_passant:  object = None
    estado:      str  = "jogando"
    vs_ia:       bool = False
    msg_id:      int  = 0
    col_sel:     int  = -1

    def id_atual(self):
        return self.branco_id if self.vez=='b' else self.preto_id
    def nome_atual(self):
        return self.branco_nome if self.vez=='b' else self.preto_nome

# ── Render helper ─────────────────────────────────────────────────────────────
async def _render(canal, partida: PartidaXadrez, msg=""):
    registrar_atividade(partida.canal_id, _timeout_cb)
    xeque = rei_em_xeque(partida.tabuleiro, partida.vez)
    buf = render_xadrez(
        partida.tabuleiro, partida.branco_nome, partida.preto_nome,
        partida.vez, partida.sel, partida.movs, msg, xeque)
    file = discord.File(buf, filename="xadrez.png")
    if partida.msg_id:
        try:
            m = await canal.fetch_message(partida.msg_id)
            await m.delete()
        except: pass
    m = await canal.send(file=file, view=XadrezView(partida))
    partida.msg_id = m.id

# ── View com botões ────────────────────────────────────────────────────────────
class XadrezView(discord.ui.View):
    def __init__(self, partida):
        super().__init__(timeout=300)
        self.partida = partida
        self._build()

    def _build(self):
        for i,c in enumerate("ABCDEFGH"):
            btn = discord.ui.Button(label=c, style=discord.ButtonStyle.secondary,
                                    custom_id=f"col_{i}", row=0)
            btn.callback = self._col_cb(i)
            self.add_item(btn)
        for l in range(8):
            btn = discord.ui.Button(label=str(l+1), style=discord.ButtonStyle.secondary,
                                    custom_id=f"lin_{l}", row=1)
            btn.callback = self._lin_cb(l)
            self.add_item(btn)
        ab = discord.ui.Button(label="🏳️ Abandonar", style=discord.ButtonStyle.danger,
                               custom_id="abandon", row=2)
        ab.callback = self._abandon
        self.add_item(ab)
        lb = discord.ui.Button(label="✖ Limpar seleção", style=discord.ButtonStyle.secondary,
                               custom_id="limpar", row=2)
        lb.callback = self._limpar
        self.add_item(lb)

    def _col_cb(self, col):
        async def cb(i: discord.Interaction):
            if i.user.id != self.partida.id_atual():
                await i.response.send_message("Não é sua vez!", ephemeral=True); return
            await i.response.defer()
            self.partida.col_sel = col
            await _render(i.channel, self.partida,
                          f"Coluna **{'ABCDEFGH'[col]}** selecionada — clique na linha (1-8)")
        return cb

    def _lin_cb(self, lin):
        async def cb(i: discord.Interaction):
            p = self.partida
            if i.user.id != p.id_atual():
                await i.response.send_message("Não é sua vez!", ephemeral=True); return
            if p.col_sel == -1:
                await i.response.send_message("Selecione a coluna primeiro!", ephemeral=True); return
            await i.response.defer()
            pos = (p.col_sel, lin)
            tab = p.tabuleiro
            if p.sel is None:
                if pos not in tab or tab[pos][0] != p.vez:
                    p.col_sel=-1
                    await _render(i.channel, p, "❌ Não há sua peça nessa casa."); return
                movs = movimentos_peca(tab, pos, p.vez, p.en_passant)
                if not movs:
                    p.col_sel=-1
                    await _render(i.channel, p, "❌ Essa peça não tem movimentos."); return
                p.sel=pos; p.movs=movs; p.col_sel=-1
                await _render(i.channel, p, f"Peça selecionada — {len(movs)} movimento(s)")
            else:
                if pos not in p.movs:
                    if pos in tab and tab[pos][0]==p.vez:
                        movs=movimentos_peca(tab,pos,p.vez,p.en_passant)
                        p.sel=pos; p.movs=movs; p.col_sel=-1
                        await _render(i.channel, p); return
                    p.col_sel=-1
                    await _render(i.channel, p, "❌ Movimento inválido."); return
                orig=p.sel; p.sel=None; p.movs=[]; p.col_sel=-1
                await executar_mov(i.channel, p, orig, pos)
        return cb

    async def _abandon(self, i: discord.Interaction):
        p = self.partida
        if i.user.id not in (p.branco_id, p.preto_id):
            await i.response.send_message("Você não está nessa partida.", ephemeral=True); return
        venc = p.preto_nome if i.user.id==p.branco_id else p.branco_nome
        partidas.pop(p.canal_id, None); self.stop()
        await i.response.send_message(f"🏳️ **{i.user.display_name}** abandonou. **{venc}** vence!")

    async def _limpar(self, i: discord.Interaction):
        if i.user.id != self.partida.id_atual():
            await i.response.send_message("Não é sua vez!", ephemeral=True); return
        await i.response.defer()
        self.partida.sel=None; self.partida.movs=[]; self.partida.col_sel=-1
        await _render(i.channel, self.partida, "Seleção limpa.")

async def executar_mov(canal, p: PartidaXadrez, orig, dest):
    tab=p.tabuleiro; cor=p.vez
    peca=tab[orig]; tipo=peca[1]
    cap=tab.get(dest)
    p.en_passant=None

    if tipo=='P' and abs(orig[1]-dest[1])==2:
        d=1 if cor=='b' else -1
        p.en_passant=(orig[0],orig[1]+d)

    tab[dest]=tab.pop(orig)
    if tipo=='P' and (dest[1]==7 or dest[1]==0):
        tab[dest]=(cor,'Q')

    if rei_em_xeque(tab,cor):
        tab[orig]=tab.pop(dest)
        if cap: tab[dest]=cap
        await canal.send("❌ Movimento inválido: deixa seu rei em xeque!", delete_after=4)
        await _render(canal, p); return

    op='p' if cor=='b' else 'b'
    p.vez=op

    movs_op=[]
    for pos in list(tab.keys()):
        if tab[pos][0]==op:
            movs_op.extend(movimentos_peca(tab,pos,op,p.en_passant))

    col_l="abcdefgh"
    orig_s=col_l[orig[0]]+str(orig[1]+1)
    dest_s=col_l[dest[0]]+str(dest[1]+1)
    emoji_p=EMOJIS.get(peca,"?")
    msg_mov=f"{emoji_p} {p.branco_nome if cor=='b' else p.preto_nome}: {orig_s}→{dest_s}"

    if not movs_op:
        xeque=rei_em_xeque(tab,op)
        venc=p.branco_nome if cor=='b' else p.preto_nome
        fim_msg = f"♟️ XEQUE-MATE! 🏆 **{venc}** venceu!" if xeque else "♟️ Afogamento! Empate!"
        buf=render_xadrez(tab,p.branco_nome,p.preto_nome,p.vez,msg=fim_msg)
        file=discord.File(buf,filename="xadrez.png")
        if p.msg_id:
            try:
                m=await canal.fetch_message(p.msg_id); await m.delete()
            except: pass
        await canal.send(file=file)
        p.estado="fim"; partidas.pop(p.canal_id,None)
        return

    await _render(canal, p, msg_mov)

    if p.vs_ia and p.preto_id==999999996 and p.vez=='p':
        await asyncio.sleep(1.2)
        mov=ia_jogar(tab,'p',p.en_passant)
        if mov:
            await executar_mov(canal,p,mov[0],mov[1])
        else:
            p.estado="fim"; partidas.pop(p.canal_id,None)
            await canal.send("🤖 IA sem movimento. Empate!")

# ── PPT (pedra papel tesoura para cores) ─────────────────────────────────────
class PPTView(discord.ui.View):
    def __init__(self, p1, p2, canal_id):
        super().__init__(timeout=60)
        self.p1=p1; self.p2=p2; self.canal_id=canal_id
        self.escolhas={}
    async def _escolher(self, i, escolha):
        if i.user.id not in (self.p1.id,self.p2.id):
            await i.response.send_message("Você não está nessa partida.", ephemeral=True); return
        if i.user.id in self.escolhas:
            await i.response.send_message("Já escolheu!", ephemeral=True); return
        self.escolhas[i.user.id]=escolha
        await i.response.send_message(f"✅ Você escolheu **{escolha}**!", ephemeral=True)
        if len(self.escolhas)==2:
            self.stop()
            await self._resolver(i.channel)
    @discord.ui.button(label="🪨 Pedra",  style=discord.ButtonStyle.secondary, row=0)
    async def pedra(self,i,b): await self._escolher(i,"Pedra")
    @discord.ui.button(label="📄 Papel",  style=discord.ButtonStyle.secondary, row=0)
    async def papel(self,i,b): await self._escolher(i,"Papel")
    @discord.ui.button(label="✂️ Tesoura",style=discord.ButtonStyle.secondary, row=0)
    async def tesoura(self,i,b): await self._escolher(i,"Tesoura")

    async def _resolver(self, canal):
        e1=self.escolhas.get(self.p1.id,"?")
        e2=self.escolhas.get(self.p2.id,"?")
        ganha_de={"Pedra":"Tesoura","Papel":"Pedra","Tesoura":"Papel"}
        if e1==e2:
            venc=random.choice([self.p1,self.p2])
            await canal.send(f"🤝 Empate ({e1} vs {e2})! **{venc.display_name}** escolhe a cor por sorteio.")
        elif ganha_de[e1]==e2:
            venc=self.p1
            await canal.send(f"🎉 **{self.p1.display_name}** venceu! ({e1} bate {e2})")
        else:
            venc=self.p2
            await canal.send(f"🎉 **{self.p2.display_name}** venceu! ({e2} bate {e1})")

        # Vencedor escolhe cor
        await canal.send(f"**{venc.display_name}**, escolha sua cor:", view=EscolherCorView(self.p1,self.p2,venc,self.canal_id))

class EscolherCorView(discord.ui.View):
    def __init__(self,p1,p2,venc,canal_id):
        super().__init__(timeout=60)
        self.p1=p1; self.p2=p2; self.venc=venc; self.canal_id=canal_id
    @discord.ui.button(label="♔ Brancas (começa)",style=discord.ButtonStyle.secondary)
    async def brancas(self,i,b):
        if i.user.id!=self.venc.id:
            await i.response.send_message("Não é você que escolhe!", ephemeral=True); return
        self.stop()
        branco=self.venc; preto=self.p1 if self.venc==self.p2 else self.p2
        await self._iniciar(i.channel,branco,preto)
    @discord.ui.button(label="♚ Pretas",style=discord.ButtonStyle.secondary)
    async def pretas(self,i,b):
        if i.user.id!=self.venc.id:
            await i.response.send_message("Não é você que escolhe!", ephemeral=True); return
        self.stop()
        preto=self.venc; branco=self.p1 if self.venc==self.p2 else self.p2
        await self._iniciar(i.channel,branco,preto)
    async def _iniciar(self,canal,branco,preto):
        p=PartidaXadrez(canal_id=self.canal_id,
                        branco_id=branco.id,preto_id=preto.id,
                        branco_nome=branco.display_name,preto_nome=preto.display_name)
        partidas[self.canal_id]=p
        await canal.send(f"♔ **{branco.display_name}** (Brancas) vs ♚ **{preto.display_name}** (Pretas)\nBrancas começam!")
        await _render(canal,p,"Vez das brancas — selecione coluna depois linha")

# ── Timeout ───────────────────────────────────────────────────────────────────
async def _timeout_cb(canal_id,_):
    partidas.pop(canal_id,None)
    try:
        for g in _bot_x.guilds:
            c=g.get_channel(canal_id)
            if c: await c.send("⏰ Xadrez encerrado por inatividade."); break
    except: pass
_bot_x=None

# ── Cog ───────────────────────────────────────────────────────────────────────
class XadrezCog(commands.Cog):
    def __init__(self,bot):
        self.bot=bot
        global _bot_x; _bot_x=bot

    @app_commands.command(name="xadrez",description="Xadrez 1v1 — PPT determina quem começa")
    async def cmd_xadrez(self,interaction: discord.Interaction):
        if not checar_canal(interaction.channel_id):
            await interaction.response.send_message("🎰 Use o canal do cassino!", ephemeral=True); return
        cid=interaction.channel_id
        if cid in partidas:
            await interaction.response.send_message("Já tem xadrez aqui!", ephemeral=True); return
        # Aguarda segundo jogador
        partidas[cid]=PartidaXadrez(canal_id=cid,branco_id=interaction.user.id,preto_id=0,
                                    branco_nome=interaction.user.display_name,preto_nome="?",estado="aguardando")
        await interaction.response.send_message(
            f"♟️ **{interaction.user.display_name}** quer jogar xadrez!\nUse `/xadrez_entrar` para aceitar o desafio.")

    @app_commands.command(name="xadrez_entrar",description="Entra no desafio de xadrez")
    async def cmd_entrar(self,interaction: discord.Interaction):
        cid=interaction.channel_id
        p=partidas.get(cid)
        if not p or p.estado!="aguardando":
            await interaction.response.send_message("Sem xadrez aguardando aqui.", ephemeral=True); return
        if interaction.user.id==p.branco_id:
            await interaction.response.send_message("Você criou o desafio!", ephemeral=True); return
        # PPT
        p1 = interaction.guild.get_member(p.branco_id) or interaction.user
        p2 = interaction.user
        partidas.pop(cid,None)   # remove o "aguardando", PPT vai recriar
        await interaction.response.send_message(
            f"⚔️ **{p1.display_name}** vs **{p2.display_name}**!\n"
            f"🪨📄✂️ Joguem pedra-papel-tesoura para definir quem escolhe a cor:",
            view=PPTView(p1,p2,cid))

    @app_commands.command(name="xadrez_solo",description="Xadrez contra a IA")
    async def cmd_solo(self,interaction: discord.Interaction):
        if not checar_canal(interaction.channel_id):
            await interaction.response.send_message("🎰 Use o canal do cassino!", ephemeral=True); return
        cid=interaction.channel_id
        if cid in partidas:
            await interaction.response.send_message("Já tem xadrez aqui!", ephemeral=True); return
        p=PartidaXadrez(canal_id=cid,branco_id=interaction.user.id,preto_id=999999996,
                        branco_nome=interaction.user.display_name,preto_nome="🤖 IA",vs_ia=True)
        partidas[cid]=p
        await interaction.response.send_message(
            f"♟️ **{interaction.user.display_name}** (♔) vs **🤖 IA** (♚)\nVocê começa!")
        await _render(interaction.channel,p,"Selecione coluna depois linha para mover")

    @app_commands.command(name="xadrez_encerrar",description="Encerra a partida de xadrez")
    async def cmd_encerrar(self,interaction: discord.Interaction):
        p=partidas.pop(interaction.channel_id,None)
        if not p:
            await interaction.response.send_message("Sem xadrez aqui.", ephemeral=True); return
        await interaction.response.send_message("❌ Xadrez encerrado.")

async def setup(bot):
    await bot.add_cog(XadrezCog(bot))
