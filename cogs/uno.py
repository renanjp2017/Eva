import discord
from discord import app_commands
from discord.ext import commands
import random
import asyncio
from dataclasses import dataclass, field
from typing import Optional
from .base import get_fichas, set_fichas, checar_canal, atualizar_msg, FakeUser, FICHAS_INICIAIS, APOSTA_MINIMA, APOSTA_MAXIMA, registrar_resultado, registrar_atividade, cancelar_timeout


mesas_uno: dict = {}  # canal_id -> MesaUno

# ═════════════════════════════════════════
#  UNO
# ═════════════════════════════════════════
UNO_CORES   = ["🔴", "🔵", "🟡", "🟢"]
UNO_VALORES = ["0","1","2","3","4","5","6","7","8","9","+2","🚫","↩️"]
UNO_ESPECIAIS = ["🃏+4", "🃏cor"]  # wild cards

mesas_uno: dict[int, "MesaUno"] = {}

def gerar_baralho_uno():
    deck = []
    for cor in UNO_CORES:
        for val in UNO_VALORES:
            deck.append(f"{cor}{val}")
            if val != "0":
                deck.append(f"{cor}{val}")  # duas cópias exceto 0
    for _ in range(4):
        deck.append("🃏+4")
        deck.append("🃏cor")
    random.shuffle(deck)
    return deck

def carta_uno_jogavel(carta: str, topo: str, cor_curinga: str) -> bool:
    if carta.startswith("🃏"):
        return True
    topo_cor = topo[:2] if topo.startswith("🃏") else topo[0] if topo[0] in "🔴🔵🟡🟢" else topo[:2]
    carta_cor = carta[:2] if carta[:2] in UNO_CORES else carta[0]
    topo_cor  = cor_curinga if topo.startswith("🃏") else topo_cor
    if carta_cor == topo_cor:
        return True
    topo_val  = topo[2:] if topo[:2] in UNO_CORES else topo[1:]
    carta_val = carta[2:] if carta[:2] in UNO_CORES else carta[1:]
    return carta_val == topo_val

@dataclass
class MesaUno:
    canal_id: int
    iniciador_id: int
    jogadores: list = field(default_factory=list)
    maos: dict = field(default_factory=dict)      # user_id -> [cartas]
    baralho: list = field(default_factory=list)
    descarte: list = field(default_factory=list)
    vez_idx: int = 0
    direcao: int = 1  # 1 = horário, -1 = anti-horário
    estado: str = "aguardando"
    cor_curinga: str = ""
    pendurado: int = 0  # +2 ou +4 acumulado
    msg_id: int = 0  # ID da mensagem principal para editar

    def topo(self): return self.descarte[-1] if self.descarte else ""
    def jogador_atual(self): return self.jogadores[self.vez_idx % len(self.jogadores)]
    def avancar(self, n=1):
        self.vez_idx = (self.vez_idx + self.direcao * n) % len(self.jogadores)
    def get_mao(self, uid): return self.maos.get(uid, [])


async def iniciar_uno(canal, mesa: MesaUno):
    mesa.estado  = "jogando"
    mesa.baralho = gerar_baralho_uno()
    mesa.descarte = []
    mesa.vez_idx  = 0
    mesa.direcao  = 1
    mesa.pendurado = 0

    for j in mesa.jogadores:
        mesa.maos[j.id] = [mesa.baralho.pop() for _ in range(7)]

    # Primeira carta (não pode ser especial)
    while True:
        carta = mesa.baralho.pop()
        if not carta.startswith("🃏") and "+" not in carta and "🚫" not in carta and "↩️" not in carta:
            break
        mesa.baralho.insert(0, carta)
    mesa.descarte.append(carta)

    await canal.send(
        f"🃏 **UNO iniciado!** Jogadores: {', '.join(j.display_name for j in mesa.jogadores)}\n"
        f"Carta inicial: **{carta}**\n\nCartas enviadas por DM!"
    )
    for j in mesa.jogadores:
        await enviar_mao_uno(j, mesa)
    await pedir_turno_uno(canal, mesa)


async def enviar_mao_uno(jogador, mesa: MesaUno):
    cartas = mesa.get_mao(jogador.id)
    txt = "🃏 **Sua mão no UNO:**\n" + "  ".join(f"`{c}`" for c in cartas)
    txt += f"\n\nCarta no topo: `{mesa.topo()}`"
    try:
        await jogador.send(txt)
    except Exception:
        pass


async def pedir_turno_uno(canal, mesa: MesaUno):
    registrar_atividade(mesa.canal_id, _encerrar_uno_timeout)
    atual = mesa.jogador_atual()
    cartas = mesa.get_mao(atual.id)
    jogaveis = [c for c in cartas if carta_uno_jogavel(c, mesa.topo(), mesa.cor_curinga)]
    embed = discord.Embed(title="🃏 UNO", color=0xff4444)
    embed.add_field(name="Topo", value=f"`{mesa.topo()}`", inline=True)
    embed.add_field(name="Vez de", value=atual.display_name, inline=True)
    embed.add_field(name="Cartas na mão", value=" ".join(f"`{c}`" for c in cartas) or "nenhuma", inline=False)
    if mesa.pendurado > 0:
        embed.add_field(name="⚠️ Pendurado", value=f"+{mesa.pendurado} cartas!", inline=False)

    if not jogaveis:
        # Compra carta automaticamente
        if mesa.baralho:
            nova = mesa.baralho.pop()
            cartas.append(nova)
            await canal.send(f"🃏 **{atual.display_name}** não tem carta jogável e comprou `{nova}`.", embed=embed)
            if carta_uno_jogavel(nova, mesa.topo(), mesa.cor_curinga):
                await pedir_turno_uno(canal, mesa)
            else:
                mesa.avancar()
                await pedir_turno_uno(canal, mesa)
        return

    view = UnoJogarView(mesa, atual)
    mesa.msg_id = await _atualizar_msg(
        canal, mesa.msg_id,
        content_txt=f"🃏 **{atual.mention}** é sua vez!",
        embed=embed, view=view
    )


class EscolherCorView(discord.ui.View):
    def __init__(self, mesa: MesaUno, carta: str):
        super().__init__(timeout=30)
        self.mesa  = mesa
        self.carta = carta
        for cor in UNO_CORES:
            self.add_item(CorButton(cor, mesa, carta))

class CorButton(discord.ui.Button):
    def __init__(self, cor: str, mesa: MesaUno, carta: str):
        super().__init__(label=cor, style=discord.ButtonStyle.primary)
        self.cor   = cor
        self.mesa  = mesa
        self.carta = carta

    async def callback(self, interaction: discord.Interaction):
        mesa = self.mesa
        if interaction.user.id != mesa.jogador_atual().id:
            await interaction.response.send_message("Não é sua vez!", ephemeral=True)
            return
        await interaction.response.defer()
        self.view.stop()
        mesa.cor_curinga = self.cor
        canal = interaction.channel
        await canal.send(f"🃏 Cor escolhida: **{self.cor}**")
        mesa.avancar()
        await pedir_turno_uno(canal, mesa)


class UnoJogarView(discord.ui.View):
    def __init__(self, mesa: MesaUno, jogador):
        super().__init__(timeout=60)
        self.mesa    = mesa
        self.jogador = jogador
        cartas = mesa.get_mao(jogador.id)
        jogaveis = [c for c in cartas if carta_uno_jogavel(c, mesa.topo(), mesa.cor_curinga)]
        for carta in jogaveis[:20]:  # max 20 botões
            self.add_item(UnoCartaButton(carta, mesa, jogador))

    @discord.ui.button(label="Comprar carta", style=discord.ButtonStyle.danger, emoji="📥", row=4)
    async def comprar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.jogador.id:
            await interaction.response.send_message("Não é sua vez!", ephemeral=True)
            return
        await interaction.response.defer()
        self.stop()
        mesa = self.mesa
        if mesa.baralho:
            nova = mesa.baralho.pop()
            mesa.get_mao(self.jogador.id).append(nova)
            await interaction.channel.send(f"📥 **{self.jogador.display_name}** comprou uma carta.")
        mesa.avancar()
        await pedir_turno_uno(interaction.channel, mesa)


class UnoCartaButton(discord.ui.Button):
    def __init__(self, carta: str, mesa: MesaUno, jogador):
        super().__init__(label=carta, style=discord.ButtonStyle.success)
        self.carta   = carta
        self.mesa    = mesa
        self.jogador = jogador

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.jogador.id:
            await interaction.response.send_message("Não é sua vez!", ephemeral=True)
            return
        await interaction.response.defer()
        self.view.stop()
        mesa  = self.mesa
        carta = self.carta
        mao   = mesa.get_mao(self.jogador.id)
        if carta not in mao:
            return
        mao.remove(carta)
        mesa.descarte.append(carta)
        canal = interaction.channel

        # Verifica UNO e vitória
        if len(mao) == 0:
            await canal.send(f"🎉 **{self.jogador.display_name} ganhou o UNO!**")
            view = NovaRodadaUnoView(mesa)
            await canal.send("Jogar de novo?", view=view)
            return
        if len(mao) == 1:
            await canal.send(f"⚠️ **{self.jogador.display_name}**: UNO!")

        # Efeitos especiais
        val = carta[2:] if carta[:2] in UNO_CORES else carta
        if carta.startswith("🃏"):
            # Curinga — pede cor
            if "+4" in carta:
                mesa.pendurado += 4
            mesa.avancar()
            view = EscolherCorView(mesa, carta)
            await canal.send(f"🃏 **{self.jogador.display_name}** jogou `{carta}`! Escolha a cor:", view=view)
            return
        elif "+2" in val:
            mesa.pendurado += 2
            mesa.avancar()
            # Próximo compra
            prox = mesa.jogador_atual()
            if mesa.pendurado > 0:
                for _ in range(mesa.pendurado):
                    if mesa.baralho:
                        mesa.get_mao(prox.id).append(mesa.baralho.pop())
                await canal.send(f"😬 **{prox.display_name}** comprou **{mesa.pendurado}** cartas!")
                mesa.pendurado = 0
                mesa.avancar()
        elif "🚫" in val:
            mesa.avancar()
            prox = mesa.jogador_atual()
            await canal.send(f"🚫 **{prox.display_name}** foi bloqueado!")
            mesa.avancar()
        elif "↩️" in val:
            mesa.direcao *= -1
            await canal.send(f"↩️ Direção invertida!")
            mesa.avancar()
        else:
            mesa.avancar()

        await pedir_turno_uno(canal, mesa)


class EntrarUnoView(discord.ui.View):
    def __init__(self, mesa: MesaUno):
        super().__init__(timeout=120)
        self.mesa = mesa

    @discord.ui.button(label="Entrar", style=discord.ButtonStyle.success, emoji="🃏")
    async def entrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        mesa = self.mesa
        if interaction.user in mesa.jogadores:
            await interaction.response.send_message("Você já está na mesa!", ephemeral=True)
            return
        if len(mesa.jogadores) >= 8:
            await interaction.response.send_message("Mesa cheia! (máx 8)", ephemeral=True)
            return
        mesa.jogadores.append(interaction.user)
        await interaction.response.send_message(
            f"✅ **{interaction.user.display_name}** entrou! ({len(mesa.jogadores)}/8)"
        )

    @discord.ui.button(label="Iniciar", style=discord.ButtonStyle.primary, emoji="▶️")
    async def iniciar(self, interaction: discord.Interaction, button: discord.ui.Button):
        mesa = self.mesa
        if interaction.user.id != mesa.iniciador_id:
            await interaction.response.send_message("Só quem criou pode iniciar.", ephemeral=True)
            return
        if len(mesa.jogadores) < 2:
            await interaction.response.send_message("Precisa de pelo menos 2 jogadores.", ephemeral=True)
            return
        self.stop()
        await interaction.response.send_message("▶️ Iniciando UNO!")
        await iniciar_uno(interaction.channel, mesa)



async def _encerrar_uno_timeout(canal_id: int, motivo: str):
    mesas_uno.pop(canal_id, None)
    try:
        canal = None
        for guild in _bot_ref_uno.guilds:
            canal = guild.get_channel(canal_id)
            if canal:
                break
        if canal:
            await canal.send("⏰ Jogo de **UNO** encerrado por inatividade (10 min).")
    except Exception as e:
        print(f"[TIMEOUT UNO] {e}")

_bot_ref_uno = None


class UnoCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        global _bot_ref_uno
        _bot_ref_uno = bot


    @app_commands.command(name="uno", description="Inicia uma partida de UNO (2-8 jogadores)")
    async def cmd_uno(interaction: discord.Interaction):
        if not checar_canal(interaction.channel_id):
            await interaction.response.send_message("🎰 Os jogos só funcionam no canal do cassino!", ephemeral=True)
            return
        canal_id = interaction.channel_id
        if canal_id in mesas_uno:
            await interaction.response.send_message("Já tem UNO aqui! Use `/uno_encerrar`.", ephemeral=True)
            return
        mesa = MesaUno(canal_id=canal_id, iniciador_id=interaction.user.id)
        mesa.jogadores.append(interaction.user)
        mesas_uno[canal_id] = mesa
        embed = discord.Embed(title="🃏 UNO", color=0xff4444,
            description=f"**{interaction.user.display_name}** criou UNO!\nEntre e aguarde o início.\n2–8 jogadores.")
        await interaction.response.send_message(embed=embed, view=EntrarUnoView(mesa))

    @app_commands.command(name="uno_encerrar", description="Encerra o UNO atual")
    async def cmd_uno_encerrar(interaction: discord.Interaction):
        mesa = mesas_uno.pop(interaction.channel_id, None)
        if not mesa:
            await interaction.response.send_message("Não tem UNO aqui.", ephemeral=True)
            return
        await interaction.response.send_message("❌ UNO encerrado.")




async def setup(bot: commands.Bot):
    await bot.add_cog(UnoCog(bot))
