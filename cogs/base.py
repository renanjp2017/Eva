"""
base.py — Estado compartilhado entre todos os cogs.
Fichas, canal cassino, helper de mensagem e /ajuda.
"""
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import os

# ─────────────────────────────────────────
#  FICHAS
# ─────────────────────────────────────────
FICHAS_INICIAIS = 500
APOSTA_MINIMA   = 10
APOSTA_MAXIMA   = 500

fichas: dict[int, int] = {}
db_pool = None

def get_fichas(user_id: int) -> int:
    return fichas.get(user_id, FICHAS_INICIAIS)

def set_fichas(user_id: int, valor: int):
    fichas[user_id] = max(0, valor)
    asyncio.create_task(_salvar_fichas(user_id, max(0, valor)))

async def _salvar_fichas(user_id: int, valor: int):
    if not db_pool:
        return
    try:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO cassino_fichas (user_id, fichas)
                VALUES ($1, $2)
                ON CONFLICT (user_id) DO UPDATE SET fichas = $2
            """, str(user_id), valor)
    except Exception as e:
        print(f"[DB] Erro ao salvar fichas: {e}")

async def carregar_fichas():
    if not db_pool:
        return
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT user_id, fichas FROM cassino_fichas")
            for row in rows:
                fichas[int(row["user_id"])] = row["fichas"]
        print(f"[DB] {len(fichas)} saldos carregados.")
    except Exception as e:
        print(f"[DB] Erro ao carregar fichas: {e}")

# ─────────────────────────────────────────
#  CANAL CASSINO
# ─────────────────────────────────────────
canais_cassino: set[int] = set()

def checar_canal(canal_id: int) -> bool:
    return len(canais_cassino) == 0 or canal_id in canais_cassino

# ─────────────────────────────────────────
#  FAKE USER (bots IA)
# ─────────────────────────────────────────
class FakeUser:
    def __init__(self, name: str, uid: int):
        self.id           = uid
        self.display_name = name
        self.mention      = name

    async def send(self, *a, **kw):
        pass

# ─────────────────────────────────────────
#  HELPER: editar ou mandar mensagem
# ─────────────────────────────────────────
async def atualizar_msg(canal, msg_id: int, content_txt: str = None, embed=None, view=None) -> int:
    if msg_id:
        try:
            msg = await canal.fetch_message(msg_id)
            kwargs = {}
            if content_txt is not None: kwargs['content'] = content_txt
            if embed is not None:       kwargs['embed']   = embed
            if view is not None:        kwargs['view']    = view
            await msg.edit(**kwargs)
            return msg_id
        except Exception:
            pass
    kwargs = {}
    if content_txt is not None: kwargs['content'] = content_txt
    if embed is not None:       kwargs['embed']   = embed
    if view is not None:        kwargs['view']    = view
    msg = await canal.send(**kwargs)
    return msg.id


# ─────────────────────────────────────────
#  COG BASE
# ─────────────────────────────────────────
class BaseCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="cassino_set", description="Define este canal como o canal do cassino (Admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def cassino_set(self, interaction: discord.Interaction):
        canais_cassino.add(interaction.channel_id)
        await interaction.response.send_message("🎰 Este canal agora é o **Cassino**!")

    @app_commands.command(name="cassino_remover", description="Remove este canal do cassino (Admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def cassino_remover(self, interaction: discord.Interaction):
        canais_cassino.discard(interaction.channel_id)
        await interaction.response.send_message("✅ Canal removido do cassino.")

    @app_commands.command(name="cassino_info", description="Mostra onde o cassino está ativo")
    async def cassino_info(self, interaction: discord.Interaction):
        if not canais_cassino:
            await interaction.response.send_message("🎰 Cassino ativo em **todos os canais**.", ephemeral=True)
        else:
            ids = ", ".join(f"<#{c}>" for c in canais_cassino)
            await interaction.response.send_message(f"🎰 Cassino ativo em: {ids}", ephemeral=True)

    @app_commands.command(name="fichas", description="Veja seu saldo de fichas")
    async def fichas_cmd(self, interaction: discord.Interaction):
        saldo = get_fichas(interaction.user.id)
        await interaction.response.send_message(
            f"🪙 **{interaction.user.display_name}** tem **{saldo} fichas**.", ephemeral=True
        )

    @app_commands.command(name="ajuda", description="Mostra todos os comandos do cassino")
    async def ajuda(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎰 Cassino — Comandos",
            description="Bem-vindo ao cassino! Aqui estão todos os jogos disponíveis.",
            color=0xFFD700
        )
        embed.add_field(name="💰 Fichas", value=(
            "`/fichas` — veja seu saldo\n"
            "Fichas iniciais: **500 🪙** | Salvas permanentemente"
        ), inline=False)
        embed.add_field(name="🃏 Truco Paulista", value=(
            "`/truco 1v1` `/truco 2v2` — multiplayer\n"
            "`/truco_solo` — contra o bot\n"
            "`/truco_pedir` — truco/seis/nove/doze\n"
            "`/minha_mao` · `/placar` · `/encerrar`"
        ), inline=False)
        embed.add_field(name="🎴 Blackjack (21)", value=(
            "`/21` — abre mesa (solo ou até 6 jogadores)\n"
            "`/21_encerrar` — encerra a mesa"
        ), inline=False)
        embed.add_field(name="♠️ Poker Texas Hold'em", value=(
            "`/poker` — multiplayer (2–9 jogadores)\n"
            "`/poker_solo` — contra o bot (IA difícil)\n"
            "`/minhas_cartas` · `/poker_encerrar`"
        ), inline=False)
        embed.add_field(name="🎰 Roleta", value=(
            "`/roleta` — número(35x), cor(2x), par/ímpar(2x), metade(2x), dezena(3x)"
        ), inline=False)
        embed.add_field(name="🦁 Jogo do Bicho", value=(
            "`/bicho` — 25 bichos, acertar paga **18x**"
        ), inline=False)
        embed.add_field(name="🃏 UNO", value=(
            "`/uno` — 2–8 jogadores · `/uno_encerrar`"
        ), inline=False)
        embed.add_field(name="🁣 Dominó", value=(
            "`/domino` — multiplayer · `/domino_solo` · `/domino_encerrar`"
        ), inline=False)
        embed.add_field(name="♟️ Xadrez", value=(
            "`/xadrez` — 1v1 · `/xadrez_solo` — vs IA\n"
            "`/xadrez_entrar` · `/xadrez_encerrar`"
        ), inline=False)
        embed.set_footer(text="Boa sorte! 🍀 | Fichas não têm valor real.")
        await interaction.response.send_message(embed=embed)

    @cassino_set.error
    @cassino_remover.error
    async def admin_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Você precisa ser Admin.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(BaseCog(bot))
