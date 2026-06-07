import discord
from discord import app_commands
from discord.ext import commands
import random
import asyncio
from dataclasses import dataclass, field
from typing import Optional
from .base import get_fichas, set_fichas, checar_canal, atualizar_msg, FakeUser, FICHAS_INICIAIS, APOSTA_MINIMA, APOSTA_MAXIMA, registrar_resultado, registrar_atividade, cancelar_timeout


partidas_xadrez: dict = {}  # canal_id -> PartidaXadrez

# ═════════════════════════════════════════
#  XADREZ
# ═════════════════════════════════════════
# Representação: dict[pos] = (cor, tipo)
# cor: 'b' branco, 'p' preto | tipo: K Q R B N P

XADREZ_EMOJIS = {
    ('b','K'): '♔', ('b','Q'): '♕', ('b','R'): '♖',
    ('b','B'): '♗', ('b','N'): '♘', ('b','P'): '♙',
    ('p','K'): '♚', ('p','Q'): '♛', ('p','R'): '♜',
    ('p','B'): '♝', ('p','N'): '♞', ('p','P'): '♟',
}

def tabuleiro_inicial():
    t = {}
    ordem = ['R','N','B','Q','K','B','N','R']
    for c, linha in [('p', 7), ('b', 0)]:
        for col, tipo in enumerate(ordem):
            t[(col, linha)] = (c, tipo)
        pawn_linha = 6 if c == 'p' else 1
        for col in range(8):
            t[(col, pawn_linha)] = (c, 'P')
    return t

def render_tabuleiro(tab: dict, sel=None, movs=None) -> str:
    linhas = []
    for linha in range(7, -1, -1):
        row = str(linha + 1)  # número da linha na direita
        for col in range(8):
            pos   = (col, linha)
            claro = (col + linha) % 2 == 0
            if movs and pos in movs:
                row += '🟡'
            elif sel and pos == sel:
                row += '🟠'
            elif pos in tab:
                row += XADREZ_EMOJIS.get(tab[pos], '❓')
            else:
                row += ('⬜' if claro else '⬛')
        linhas.append(row)
    linhas.append("   A  B  C  D  E  F  G  H")
    return '\n'.join(linhas)

def movimentos_peca(tab: dict, pos, cor_atual: str, en_passant=None) -> list:
    if pos not in tab:
        return []
    cor, tipo = tab[pos]
    if cor != cor_atual:
        return []
    col, lin = pos
    movs = []

    def add(p):
        if 0 <= p[0] <= 7 and 0 <= p[1] <= 7:
            if p not in tab or tab[p][0] != cor:
                movs.append(p)

    def deslizar(dirs):
        for dc, dl in dirs:
            c, l = col + dc, lin + dl
            while 0 <= c <= 7 and 0 <= l <= 7:
                p = (c, l)
                if p in tab:
                    if tab[p][0] != cor:
                        movs.append(p)
                    break
                movs.append(p)
                c += dc
                l += dl

    if tipo == 'P':
        dir_ = 1 if cor == 'b' else -1
        frente = (col, lin + dir_)
        if frente not in tab and 0 <= frente[1] <= 7:
            movs.append(frente)
            inicio = 1 if cor == 'b' else 6
            duas = (col, lin + 2 * dir_)
            if lin == inicio and duas not in tab:
                movs.append(duas)
        for dc in (-1, 1):
            atk = (col + dc, lin + dir_)
            if 0 <= atk[0] <= 7 and 0 <= atk[1] <= 7:
                if atk in tab and tab[atk][0] != cor:
                    movs.append(atk)
                if en_passant and atk == en_passant:
                    movs.append(atk)
    elif tipo == 'N':
        for dc, dl in [(-2,-1),(-2,1),(-1,-2),(-1,2),(1,-2),(1,2),(2,-1),(2,1)]:
            add((col+dc, lin+dl))
    elif tipo == 'B':
        deslizar([(1,1),(1,-1),(-1,1),(-1,-1)])
    elif tipo == 'R':
        deslizar([(1,0),(-1,0),(0,1),(0,-1)])
    elif tipo == 'Q':
        deslizar([(1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)])
    elif tipo == 'K':
        for dc in (-1,0,1):
            for dl in (-1,0,1):
                if dc == 0 and dl == 0: continue
                add((col+dc, lin+dl))
    return movs

def rei_em_xeque(tab, cor):
    rei_pos = next((p for p, v in tab.items() if v == (cor, 'K')), None)
    if not rei_pos:
        return False
    oponente = 'p' if cor == 'b' else 'b'
    for pos in list(tab.keys()):
        if tab[pos][0] == oponente:
            if rei_pos in movimentos_peca(tab, pos, oponente):
                return True
    return False

def ia_xadrez(tab: dict, cor: str, en_passant=None):
    """IA simples: captura se pode, senão move aleatório. Com avaliação de material."""
    VALOR = {'P':1,'N':3,'B':3,'R':5,'Q':9,'K':100}
    pecas = [(pos, tab[pos]) for pos in tab if tab[pos][0] == cor]
    random.shuffle(pecas)
    melhor = None
    melhor_val = -999

    for pos, (c, tipo) in pecas:
        for dest in movimentos_peca(tab, pos, cor, en_passant):
            tab2 = dict(tab)
            tab2[dest] = tab2.pop(pos)
            if rei_em_xeque(tab2, cor):
                continue
            ganho = VALOR.get(tab.get(dest, (None, 'P'))[1] if dest in tab else '_', 0)
            # Penaliza deixar rei em xeque do oponente (bônus)
            oponente = 'p' if cor == 'b' else 'b'
            if rei_em_xeque(tab2, oponente):
                ganho += 0.5
            ruido = random.uniform(0, 0.3)
            if ganho + ruido > melhor_val:
                melhor_val = ganho + ruido
                melhor = (pos, dest)

    return melhor

@dataclass
class PartidaXadrez:
    canal_id: int
    branco_id: int
    preto_id: int
    branco_nome: str
    preto_nome: str
    tabuleiro: dict = field(default_factory=tabuleiro_inicial)
    vez: str = 'b'       # 'b' ou 'p'
    sel: object = None   # posição selecionada
    movs: list = field(default_factory=list)
    en_passant: object = None
    estado: str = "jogando"
    vs_ia: bool = False
    msg_id: int = 0  # ID da mensagem principal para editar
    col_sel: int = -1  # coluna selecionada no clique

    def jogador_atual_id(self):
        return self.branco_id if self.vez == 'b' else self.preto_id

    def jogador_atual_nome(self):
        return self.branco_nome if self.vez == 'b' else self.preto_nome


partidas_xadrez: dict[int, PartidaXadrez] = {}

def pos_para_coords(s: str):
    """'e2' -> (4,1)"""
    cols = {'a':0,'b':1,'c':2,'d':3,'e':4,'f':5,'g':6,'h':7}
    s = s.strip().lower()
    if len(s) != 2 or s[0] not in cols or not s[1].isdigit():
        return None
    return (cols[s[0]], int(s[1]) - 1)

def coords_para_pos(c, l):
    return "abcdefgh"[c] + str(l+1)


async def renderizar_xadrez(canal, partida: PartidaXadrez, msg=""):
    registrar_atividade(partida.canal_id, _encerrar_xadrez_timeout)
    tab_str  = render_tabuleiro(partida.tabuleiro, partida.sel, set(partida.movs) if partida.movs else None)
    xeque    = " ⚠️ **XEQUE!**" if rei_em_xeque(partida.tabuleiro, partida.vez) else ""
    cor_nome = "Brancas ♔" if partida.vez == 'b' else "Pretas ♚"
    vez_nome = partida.jogador_atual_nome()
    estado   = ""
    if partida.sel:
        col_str = "abcdefgh"[partida.sel[0]]
        lin_str = str(partida.sel[1] + 1)
        peca    = partida.tabuleiro.get(partida.sel)
        peca_str = XADREZ_EMOJIS.get(peca, "?") if peca else "?"
        n_movs  = len(partida.movs)
        estado  = f"\nSelecionada: **{peca_str} {col_str}{lin_str}** ({n_movs} movimento(s) disponível) — clique no destino"
    txt = f"{tab_str}\n{msg}\nVez de **{vez_nome}** ({cor_nome}){xeque}{estado}"
    view = XadrezView(partida)
    partida.msg_id = await _atualizar_msg(canal, partida.msg_id, content_txt=txt, view=view)


async def executar_movimento_xadrez(canal, partida: PartidaXadrez, orig, dest):
    tab  = partida.tabuleiro
    cor  = partida.vez
    peca = tab[orig]
    tipo = peca[1]
    capturou = tab.get(dest)
    partida.en_passant = None
    partida.sel  = None
    partida.movs = []

    # En passant setup
    if tipo == 'P' and abs(orig[1] - dest[1]) == 2:
        dir_ = 1 if cor == 'b' else -1
        partida.en_passant = (orig[0], orig[1] + dir_)

    tab[dest] = tab.pop(orig)

    # Promoção
    if tipo == 'P' and (dest[1] == 7 or dest[1] == 0):
        tab[dest] = (cor, 'Q')

    # Xeque no próprio rei — desfaz
    if rei_em_xeque(tab, cor):
        tab[orig] = tab.pop(dest)
        if capturou:
            tab[dest] = capturou
        await canal.send("❌ Movimento inválido: deixa seu rei em xeque!", delete_after=4)
        await renderizar_xadrez(canal, partida)
        return

    oponente = 'p' if cor == 'b' else 'b'
    partida.vez = oponente

    movs_oponente = []
    for pos in list(tab.keys()):
        if tab[pos][0] == oponente:
            movs_oponente.extend(movimentos_peca(tab, pos, oponente, partida.en_passant))

    orig_str = coords_para_pos(*orig)
    dest_str = coords_para_pos(*dest)
    emoji_p  = XADREZ_EMOJIS.get(peca, "?")
    msg      = f"{emoji_p} **{partida.branco_nome if cor == 'b' else partida.preto_nome}**: `{orig_str}→{dest_str}`"

    if not movs_oponente:
        if rei_em_xeque(tab, oponente):
            vencedor = partida.branco_nome if cor == 'b' else partida.preto_nome
            tab_str  = render_tabuleiro(tab)
            partida.msg_id = await _atualizar_msg(canal, partida.msg_id,
                content_txt=f"{tab_str}\n♟️ **XEQUE-MATE!** 🏆 **{vencedor}** venceu!", view=None)
        else:
            tab_str = render_tabuleiro(tab)
            partida.msg_id = await _atualizar_msg(canal, partida.msg_id,
                content_txt=f"{tab_str}\n♟️ **Afogamento!** Empate!", view=None)
        partida.estado = "fim"
        view = NovaPartidaXadrezView(partida)
        await canal.send("Jogar de novo?", view=view)
        return

    await renderizar_xadrez(canal, partida, msg)

    # IA joga
    if partida.vs_ia and partida.preto_id == 999999996 and partida.vez == 'p':
        await asyncio.sleep(1.5)
        mov = ia_xadrez(tab, 'p', partida.en_passant)
        if mov:
            await executar_movimento_xadrez(canal, partida, mov[0], mov[1])
        else:
            partida.estado = "fim"
            view = NovaPartidaXadrezView(partida)
            await canal.send("🤖 IA sem movimento. Empate!", view=view)


class XadrezView(discord.ui.View):
    """Tabuleiro interativo com seleção por clique (coluna A-H, linha 1-8)."""
    def __init__(self, partida: PartidaXadrez):
        super().__init__(timeout=300)
        self.partida = partida
        self._build_buttons()

    def _build_buttons(self):
        partida = self.partida
        # Row 0-1: colunas A-H (selecionar coluna)
        cols = list("ABCDEFGH")
        for i, c in enumerate(cols):
            btn = discord.ui.Button(
                label=c,
                style=discord.ButtonStyle.secondary,
                custom_id=f"col_{i}",
                row=0
            )
            btn.callback = self._make_col_cb(i)
            self.add_item(btn)

        # Row 1: linhas 1-8
        for l in range(8):
            btn = discord.ui.Button(
                label=str(l + 1),
                style=discord.ButtonStyle.secondary,
                custom_id=f"lin_{l}",
                row=1
            )
            btn.callback = self._make_lin_cb(l)
            self.add_item(btn)

        # Row 2: ações
        abandonar_btn = discord.ui.Button(
            label="Abandonar 🏳️",
            style=discord.ButtonStyle.danger,
            custom_id="abandonar",
            row=2
        )
        abandonar_btn.callback = self._abandonar_cb
        self.add_item(abandonar_btn)

        limpar_btn = discord.ui.Button(
            label="Limpar seleção",
            style=discord.ButtonStyle.secondary,
            custom_id="limpar",
            row=2
        )
        limpar_btn.callback = self._limpar_cb
        self.add_item(limpar_btn)

    def _make_col_cb(self, col: int):
        async def cb(interaction: discord.Interaction):
            partida = self.partida
            if interaction.user.id != partida.jogador_atual_id():
                await interaction.response.send_message("Não é sua vez!", ephemeral=True)
                return
            await interaction.response.defer()
            partida.col_sel = col
            # Se já tem linha selecionada, forma a posição
            # Senão aguarda linha
            await renderizar_xadrez(interaction.channel, partida, f"Coluna **{'ABCDEFGH'[col]}** selecionada — agora clique na linha (1-8)")
        return cb

    def _make_lin_cb(self, lin: int):
        async def cb(interaction: discord.Interaction):
            partida = self.partida
            if interaction.user.id != partida.jogador_atual_id():
                await interaction.response.send_message("Não é sua vez!", ephemeral=True)
                return
            if partida.col_sel == -1:
                await interaction.response.send_message("Selecione a coluna primeiro (A-H)!", ephemeral=True)
                return
            await interaction.response.defer()
            pos = (partida.col_sel, lin)
            tab = partida.tabuleiro

            if partida.sel is None:
                # Selecionar peça
                if pos not in tab or tab[pos][0] != partida.vez:
                    partida.col_sel = -1
                    await renderizar_xadrez(interaction.channel, partida, "❌ Não há sua peça nessa casa.")
                    return
                movs = movimentos_peca(tab, pos, partida.vez, partida.en_passant)
                if not movs:
                    partida.col_sel = -1
                    await renderizar_xadrez(interaction.channel, partida, "❌ Essa peça não tem movimentos.")
                    return
                partida.sel  = pos
                partida.movs = movs
                partida.col_sel = -1
                await renderizar_xadrez(interaction.channel, partida)
            else:
                # Mover para destino
                if pos not in partida.movs:
                    # Nova seleção?
                    if pos in tab and tab[pos][0] == partida.vez:
                        movs = movimentos_peca(tab, pos, partida.vez, partida.en_passant)
                        partida.sel  = pos
                        partida.movs = movs
                        partida.col_sel = -1
                        await renderizar_xadrez(interaction.channel, partida)
                    else:
                        partida.col_sel = -1
                        await renderizar_xadrez(interaction.channel, partida, "❌ Movimento inválido. Selecione outra peça ou destino válido.")
                    return
                orig = partida.sel
                partida.sel  = None
                partida.movs = []
                partida.col_sel = -1
                await executar_movimento_xadrez(interaction.channel, partida, orig, pos)
        return cb

    async def _abandonar_cb(self, interaction: discord.Interaction):
        partida = self.partida
        if interaction.user.id not in (partida.branco_id, partida.preto_id):
            await interaction.response.send_message("Você não está nessa partida.", ephemeral=True)
            return
        vencedor = partida.preto_nome if interaction.user.id == partida.branco_id else partida.branco_nome
        partidas_xadrez.pop(partida.canal_id, None)
        self.stop()
        await interaction.response.send_message(f"🏳️ **{interaction.user.display_name}** abandonou. **{vencedor}** vence!")

    async def _limpar_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.partida.jogador_atual_id():
            await interaction.response.send_message("Não é sua vez!", ephemeral=True)
            return
        await interaction.response.defer()
        self.partida.sel     = None
        self.partida.movs    = []
        self.partida.col_sel = -1
        await renderizar_xadrez(interaction.channel, self.partida, "Seleção limpa.")



async def _encerrar_xadrez_timeout(canal_id: int, motivo: str):
    partidas_xadrez.pop(canal_id, None)
    try:
        canal = None
        for guild in _bot_ref_xadrez.guilds:
            canal = guild.get_channel(canal_id)
            if canal:
                break
        if canal:
            await canal.send("⏰ Jogo de **Xadrez** encerrado por inatividade (10 min).")
    except Exception as e:
        print(f"[TIMEOUT XADREZ] {e}")

_bot_ref_xadrez = None


class XadrezCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        global _bot_ref_xadrez
        _bot_ref_xadrez = bot


    @app_commands.command(name="xadrez", description="Joga xadrez 1v1 com outro jogador")
    async def cmd_xadrez(interaction: discord.Interaction):
        if not checar_canal(interaction.channel_id):
            await interaction.response.send_message("🎰 Os jogos só funcionam no canal do cassino!", ephemeral=True)
            return
        canal_id = interaction.channel_id
        if canal_id in partidas_xadrez:
            await interaction.response.send_message("Já tem xadrez aqui!", ephemeral=True)
            return
        await interaction.response.send_message(
            f"♟️ **{interaction.user.display_name}** quer jogar xadrez!\nO segundo jogador use `/xadrez_entrar`."
        )
        partidas_xadrez[canal_id] = PartidaXadrez(
            canal_id=canal_id,
            branco_id=interaction.user.id,
            preto_id=0,
            branco_nome=interaction.user.display_name,
            preto_nome="?",
            tabuleiro=tabuleiro_inicial(),
            estado="aguardando"
        )

    @app_commands.command(name="xadrez_entrar", description="Entra na partida de xadrez como preto")
    async def cmd_xadrez_entrar(interaction: discord.Interaction):
        canal_id = interaction.channel_id
        partida  = partidas_xadrez.get(canal_id)
        if not partida or partida.estado != "aguardando":
            await interaction.response.send_message("Não tem xadrez aguardando aqui.", ephemeral=True)
            return
        if interaction.user.id == partida.branco_id:
            await interaction.response.send_message("Você já é as brancas!", ephemeral=True)
            return
        partida.preto_id   = interaction.user.id
        partida.preto_nome = interaction.user.display_name
        partida.estado     = "jogando"
        await interaction.response.send_message(
            f"♟️ **{partida.branco_nome}** (♔ Brancas) vs **{partida.preto_nome}** (♚ Pretas)\n"
            f"Brancas começam! Clique na coluna (A-H) depois na linha (1-8) para mover."
        )
        await renderizar_xadrez(interaction.channel, partida)

    @app_commands.command(name="xadrez_solo", description="Joga xadrez contra a IA")
    async def cmd_xadrez_solo(interaction: discord.Interaction):
        if not checar_canal(interaction.channel_id):
            await interaction.response.send_message("🎰 Os jogos só funcionam no canal do cassino!", ephemeral=True)
            return
        canal_id = interaction.channel_id
        if canal_id in partidas_xadrez:
            await interaction.response.send_message("Já tem xadrez aqui!", ephemeral=True)
            return
        partida = PartidaXadrez(
            canal_id=canal_id,
            branco_id=interaction.user.id,
            preto_id=999999996,
            branco_nome=interaction.user.display_name,
            preto_nome="🤖 XadrezBot",
            tabuleiro=tabuleiro_inicial(),
            estado="jogando",
            vs_ia=True
        )
        partidas_xadrez[canal_id] = partida
        await interaction.response.send_message(
            f"♟️ **{interaction.user.display_name}** (♔) vs **🤖 XadrezBot** (♚)\n"
            f"Clique na coluna (A-H) depois na linha (1-8) para mover."
        )
        await renderizar_xadrez(interaction.channel, partida)

    @app_commands.command(name="xadrez_encerrar", description="Encerra a partida de xadrez")
    async def cmd_xadrez_encerrar(interaction: discord.Interaction):
        partida = partidas_xadrez.pop(interaction.channel_id, None)
        if not partida:
            await interaction.response.send_message("Não tem xadrez aqui.", ephemeral=True)
            return
        await interaction.response.send_message("❌ Xadrez encerrado.")




async def setup(bot: commands.Bot