import discord
from discord import app_commands
from discord.ext import commands
import random
import asyncio
from dataclasses import dataclass, field
from typing import Optional
from .base import get_fichas, set_fichas, checar_canal, atualizar_msg, FakeUser, FICHAS_INICIAIS, APOSTA_MINIMA, APOSTA_MAXIMA


# ═════════════════════════════════════════
#  ROLETA
# ═════════════════════════════════════════
ROLETA_NUMEROS = list(range(0, 37))  # 0-36
ROLETA_VERMELHOS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
ROLETA_PRETOS   = {2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35}

def roleta_cor(n: int) -> str:
    if n == 0: return "verde"
    return "vermelho" if n in ROLETA_VERMELHOS else "preto"

def roleta_pagar(aposta_tipo: str, aposta_val: str, resultado: int) -> float:
    """Retorna multiplicador do pagamento (0 = perdeu)."""
    r = resultado
    t = aposta_tipo
    if t == "numero":
        return 35.0 if str(r) == aposta_val else 0
    if t == "cor":
        cor = roleta_cor(r)
        return 2.0 if cor == aposta_val and r != 0 else 0
    if t == "paridade":
        if r == 0: return 0
        par = "par" if r % 2 == 0 else "impar"
        return 2.0 if par == aposta_val else 0
    if t == "metade":
        if r == 0: return 0
        metade = "baixo" if r <= 18 else "alto"
        return 2.0 if metade == aposta_val else 0
    if t == "dezena":
        dezenas = {"1": range(1,13), "2": range(13,25), "3": range(25,37)}
        return 3.0 if r in dezenas.get(aposta_val, []) else 0
    return 0


class RoletaApostaModal(discord.ui.Modal, title="Apostar na Roleta"):
    tipo = discord.ui.TextInput(
        label="Tipo: numero/cor/paridade/metade/dezena",
        placeholder="ex: cor"
    )
    valor = discord.ui.TextInput(
        label="Valor da aposta",
        placeholder="ex: vermelho / 17 / par / baixo / 1"
    )
    fichas_apostar = discord.ui.TextInput(
        label="Fichas",
        placeholder="ex: 50"
    )

    def __init__(self, canal_id: int):
        super().__init__()
        self.canal_id = canal_id

    async def on_submit(self, interaction: discord.Interaction):
        user    = interaction.user
        tipo    = self.tipo.value.strip().lower()
        val     = self.valor.value.strip().lower()
        saldo   = get_fichas(user.id)

        tipos_validos = ["numero", "cor", "paridade", "metade", "dezena"]
        if tipo not in tipos_validos:
            await interaction.response.send_message(
                f"Tipo inválido! Use: {', '.join(tipos_validos)}", ephemeral=True)
            return

        try:
            valor = int(self.fichas_apostar.value)
        except ValueError:
            await interaction.response.send_message("Fichas inválidas.", ephemeral=True)
            return

        if saldo < aposta:
            await interaction.response.send_message(f"Saldo insuficiente! Você tem {saldo} 🪙", ephemeral=True)
            return

        resultado = random.randint(0, 36)
        cor       = roleta_cor(resultado)
        multi     = roleta_pagar(tipo, val, resultado)

        emoji_cor = {"verde": "🟢", "vermelho": "🔴", "preto": "⚫"}.get(cor, "")
        set_fichas(user.id, saldo - aposta)

        if multi > 0:
            ganho = int(aposta * multi)
            set_fichas(user.id, get_fichas(user.id) + ganho)
            txt = (f"🎰 **Roleta!** Resultado: **{resultado}** {emoji_cor} {cor}\n\n"
                   f"✅ Sua aposta ({tipo}: **{val}**) GANHOU! Recebeu: **{ganho} 🪙** (x{multi:.0f})\n"
                   f"Saldo: **{get_fichas(user.id)} 🪙**")
        else:
            txt = (f"🎰 **Roleta!** Resultado: **{resultado}** {emoji_cor} {cor}\n\n"
                   f"❌ Sua aposta ({tipo}: **{val}**) perdeu. Perdeu: **{aposta} 🪙**\n"
                   f"Saldo: **{get_fichas(user.id)} 🪙**")

        await interaction.response.send_message(txt)


class RoletaView(discord.ui.View):
    def __init__(self, canal_id: int):
        super().__init__(timeout=60)
        self.canal_id = canal_id

    @discord.ui.button(label="Fazer aposta", style=discord.ButtonStyle.primary, emoji="🎰")
    async def apostar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RoletaApostaModal(self.canal_id))

    @discord.ui.button(label="Girar sem aposta", style=discord.ButtonStyle.secondary, emoji="🎡")
    async def girar(self, interaction: discord.Interaction, button: discord.ui.Button):
        resultado = random.randint(0, 36)
        cor  = roleta_cor(resultado)
        emoji_cor = {"verde": "🟢", "vermelho": "🔴", "preto": "⚫"}.get(cor, "")
        await interaction.response.send_message(
            f"🎡 Roleta girou: **{resultado}** {emoji_cor} {cor} (sem aposta)"
        )



class CassinoCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot


    @app_commands.command(name="roleta", description="Jogue na roleta do cassino")
    async def cmd_roleta(interaction: discord.Interaction):
        if not checar_canal(interaction.channel_id):
            await interaction.response.send_message("🎰 Os jogos só funcionam no canal do cassino!", ephemeral=True)
            return
        saldo = get_fichas(interaction.user.id)
        embed = discord.Embed(title="🎰 Roleta", color=0x8B0000)
        embed.add_field(name="Como apostar", value=(
            "**numero** — aposte num número (0-36) → paga 35x\n"
            "**cor** — vermelho/preto/verde → paga 2x\n"
            "**paridade** — par/impar → paga 2x\n"
            "**metade** — baixo(1-18)/alto(19-36) → paga 2x\n"
            "**dezena** — 1(1-12)/2(13-24)/3(25-36) → paga 3x"
        ), inline=False)
        embed.set_footer(text=f"Seu saldo: {saldo} 🪙")
        await interaction.response.send_message(embed=embed, view=RoletaView(interaction.channel_id))


    # ═════════════════════════════════════════
    #  JOGO DO BICHO
    # ═════════════════════════════════════════
    BICHOS = [
        ("Avestruz", [1,2,3,4]), ("Águia", [5,6,7,8]), ("Burro", [9,10,11,12]),
        ("Borboleta", [13,14,15,16]), ("Cachorro", [17,18,19,20]),
        ("Cabra", [21,22,23,24]), ("Carneiro", [25,26,27,28]),
        ("Camelo", [29,30,31,32]), ("Cobra", [33,34,35,36]),
        ("Coelho", [37,38,39,40]), ("Cavalo", [41,42,43,44]),
        ("Elefante", [45,46,47,48]), ("Galo", [49,50,51,52]),
        ("Gato", [53,54,55,56]), ("Jacaré", [57,58,59,60]),
        ("Leão", [61,62,63,64]), ("Macaco", [65,66,67,68]),
        ("Porco", [69,70,71,72]), ("Pavão", [73,74,75,76]),
        ("Peru", [77,78,79,80]), ("Touro", [81,82,83,84]),
        ("Tigre", [85,86,87,88]), ("Urso", [89,90,91,92]),
        ("Veado", [93,94,95,96]), ("Vaca", [97,98,99,0]),
    ]
    BICHOS_NOMES = [b[0] for b in BICHOS]

    def sorteio_bicho():
        numero = random.randint(0, 99)
        for nome, nums in BICHOS:
            if numero in nums or (numero == 0 and 0 in nums):
                return nome, numero
        return BICHOS[-1][0], numero

    def nome_para_bicho(nome: str):
        for b_nome, nums in BICHOS:
            if b_nome.lower() == nome.lower():
                return b_nome, nums
        return None, None


    class BichoModal(discord.ui.Modal, title="Jogo do Bicho"):
        bicho = discord.ui.TextInput(
            label="Qual bicho? (ex: Gato, Leão, Tigre...)",
            placeholder="Digite o nome do bicho"
        )
        aposta = discord.ui.TextInput(
            label="Fichas",
            placeholder="ex: 100"
        )

        async def on_submit(self, interaction: discord.Interaction):
            user  = interaction.user
            saldo = get_fichas(user.id)
            nome_b, _ = nome_para_bicho(self.bicho.value)

            if not nome_b:
                lista = ", ".join(BICHOS_NOMES[:10]) + "..."
                await interaction.response.send_message(
                    f"Bicho inválido! Exemplos: {lista}", ephemeral=True)
                return

            try:
                valor = max(APOSTA_MINIMA, min(int(self.aposta.value), APOSTA_MAXIMA, saldo))
            except ValueError:
                await interaction.response.send_message("Valor inválido.", ephemeral=True)
                return

            if saldo < valor:
                await interaction.response.send_message(f"Saldo insuficiente! Você tem {saldo} 🪙", ephemeral=True)
                return

            resultado, numero = sorteio_bicho()
            set_fichas(user.id, saldo - valor)

            if resultado.lower() == nome_b.lower():
                ganho = valor * 18
                set_fichas(user.id, get_fichas(user.id) + ganho)
                txt = (f"🦁 **Jogo do Bicho!**\n"
                       f"Número sorteado: **{numero:02d}** → **{resultado}**\n\n"
                       f"🎉 GANHOU! Você apostou em **{nome_b}** e acertou!\n"
                       f"Recebeu: **{ganho} 🪙** (x18)\n"
                       f"Saldo: **{get_fichas(user.id)} 🪙**")
            else:
                txt = (f"🦁 **Jogo do Bicho!**\n"
                       f"Número sorteado: **{numero:02d}** → **{resultado}**\n\n"
                       f"❌ Você apostou em **{nome_b}** e perdeu.\n"
                       f"Perdeu: **{valor} 🪙**\n"
                       f"Saldo: **{get_fichas(user.id)} 🪙**")

            await interaction.response.send_message(txt)


    class BichoView(discord.ui.View):
        @discord.ui.button(label="Apostar", style=discord.ButtonStyle.primary, emoji="🦁")
        async def apostar(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.send_modal(BichoModal())

        @discord.ui.button(label="Ver bichos", style=discord.ButtonStyle.secondary, emoji="📋")
        async def ver_bichos(self, interaction: discord.Interaction, button: discord.ui.Button):
            lista = "\n".join(f"**{b[0]}**: {b[1][0]:02d}-{b[1][-1]:02d}" for b in BICHOS)
            await interaction.response.send_message(f"🦁 **Bichos:**\n{lista}", ephemeral=True)

    @app_commands.command(name="bicho", description="Aposte no Jogo do Bicho")
    async def cmd_bicho(interaction: discord.Interaction):
        if not checar_canal(interaction.channel_id):
            await interaction.response.send_message("🎰 Os jogos só funcionam no canal do cassino!", ephemeral=True)
            return
        saldo = get_fichas(interaction.user.id)
        embed = discord.Embed(title="🦁 Jogo do Bicho", color=0x228B22)
        embed.description = (
            "Aposte num bicho e torça pro número sair!\n"
            "São **25 bichos**, cada um com 4 números (00-99).\n"
            "Acertar paga **18x** a aposta!\n\n"
            "Clique em **Ver bichos** para ver a lista completa."
        )
        embed.set_footer(text=f"Seu saldo: {saldo} 🪙")
        await interaction.response.send_message(embed=embed, view=BichoView())




async def setup(bot: commands.Bot):
    await bot.add_cog(CassinoCog(bot))
