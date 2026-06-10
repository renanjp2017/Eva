"""
base.py — Estado compartilhado entre todos os cogs.
Fichas, canal cassino, helper de mensagem, /ajuda, bônus diário, ranking, histórico.
"""
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import json
from datetime import datetime, timezone, timedelta
import os

# ─────────────────────────────────────────
#  CONSTANTES
# ─────────────────────────────────────────
FICHAS_INICIAIS  = 500
APOSTA_MINIMA    = 10
APOSTA_MAXIMA    = 500
BONUS_DIARIO     = 200
TIMEOUT_PARTIDA  = 600  # 10 minutos sem ação

# ─────────────────────────────────────────
#  BANCO DE DADOS
# ─────────────────────────────────────────
db_pool = None

async def init_db():
    if not db_pool:
        return
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS cassino_fichas (
                user_id     TEXT PRIMARY KEY,
                fichas      INTEGER NOT NULL DEFAULT 500,
                ultimo_bonus TIMESTAMP,
                vitorias    INTEGER DEFAULT 0,
                derrotas    INTEGER DEFAULT 0,
                maior_ganho INTEGER DEFAULT 0,
                total_apostado BIGINT DEFAULT 0,
                nome        TEXT DEFAULT ''
            )
        """)
        # Histórico de partidas
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS cassino_historico (
                id          SERIAL PRIMARY KEY,
                user_id     TEXT NOT NULL,
                jogo        TEXT NOT NULL,
                resultado   TEXT NOT NULL,
                valor       INTEGER NOT NULL,
                ts          TIMESTAMP DEFAULT NOW()
            )
        """)
        # Estado das partidas salvo
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS cassino_estado (
                canal_id    TEXT PRIMARY KEY,
                cog         TEXT NOT NULL,
                estado_json TEXT NOT NULL,
                ts          TIMESTAMP DEFAULT NOW()
            )
        """)

# ─────────────────────────────────────────
#  FICHAS
# ─────────────────────────────────────────
fichas: dict[int, int] = {}

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

async def registrar_resultado(user_id: int, nome: str, jogo: str, ganhou: bool, valor: int):
    """Registra resultado de partida e atualiza estatísticas."""
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                resultado = "vitoria" if ganhou else "derrota"
                await conn.execute("""
                    INSERT INTO cassino_historico (user_id, jogo, resultado, valor)
                    VALUES ($1, $2, $3, $4)
                """, str(user_id), jogo, resultado, valor)
                if ganhou:
                    await conn.execute("""
                        INSERT INTO cassino_fichas (user_id, fichas, nome, vitorias, maior_ganho)
                        VALUES ($1, $2, $3, 1, $4)
                        ON CONFLICT (user_id) DO UPDATE SET
                            vitorias    = cassino_fichas.vitorias + 1,
                            maior_ganho = GREATEST(cassino_fichas.maior_ganho, $4),
                            nome        = $3,
                            total_apostado = cassino_fichas.total_apostado + $4
                    """, str(user_id), get_fichas(user_id), nome, valor)
                else:
                    await conn.execute("""
                        INSERT INTO cassino_fichas (user_id, fichas, nome, derrotas)
                        VALUES ($1, $2, $3, 1)
                        ON CONFLICT (user_id) DO UPDATE SET
                            derrotas = cassino_fichas.derrotas + 1,
                            nome     = $3,
                            total_apostado = cassino_fichas.total_apostado + $4
                    """, str(user_id), get_fichas(user_id), nome, valor)
        except Exception as e:
            print(f"[DB] Erro ao registrar resultado: {e}")

# ─────────────────────────────────────────
#  TIMEOUT DE PARTIDAS
# ─────────────────────────────────────────
_timeouts: dict[int, asyncio.Task] = {}  # canal_id -> task

def registrar_atividade(canal_id: int, encerrar_cb):
    """Reinicia o timeout de inatividade para uma partida."""
    cancelar_timeout(canal_id)
    task = asyncio.create_task(_timeout_worker(canal_id, encerrar_cb))
    _timeouts[canal_id] = task

def cancelar_timeout(canal_id: int):
    task = _timeouts.pop(canal_id, None)
    if task:
        task.cancel()

async def _timeout_worker(canal_id: int, encerrar_cb):
    await asyncio.sleep(TIMEOUT_PARTIDA)
    try:
        await encerrar_cb(canal_id, "timeout")
    except Exception as e:
        print(f"[TIMEOUT] Erro ao encerrar {canal_id}: {e}")

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

    # ── Admin ──
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

    # ── Fichas ──
    @app_commands.command(name="fichas", description="Veja seu saldo de fichas")
    async def fichas_cmd(self, interaction: discord.Interaction):
        saldo = get_fichas(interaction.user.id)
        await interaction.response.send_message(
            f"🪙 **{interaction.user.display_name}** tem **{saldo} fichas**.", ephemeral=True
        )

    # ── Bônus diário ──
    @app_commands.command(name="diario", description="Resgate seu bônus diário de fichas")
    async def diario(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        agora   = datetime.now(timezone.utc)

        if db_pool:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT ultimo_bonus FROM cassino_fichas WHERE user_id = $1", str(user_id)
                )
                if row and row["ultimo_bonus"]:
                    ultimo = row["ultimo_bonus"].replace(tzinfo=timezone.utc)
                    proximo = ultimo + timedelta(hours=24)
                    if agora < proximo:
                        restante = proximo - agora
                        horas    = int(restante.total_seconds() // 3600)
                        minutos  = int((restante.total_seconds() % 3600) // 60)
                        await interaction.response.send_message(
                            f"⏳ Você já pegou o bônus hoje! Volte em **{horas}h {minutos}m**.", ephemeral=True
                        )
                        return
                # Dá o bônus
                novo_saldo = get_fichas(user_id) + BONUS_DIARIO
                set_fichas(user_id, novo_saldo)
                await conn.execute("""
                    INSERT INTO cassino_fichas (user_id, fichas, ultimo_bonus, nome)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (user_id) DO UPDATE SET
                        fichas = $2, ultimo_bonus = $3, nome = $4
                """, str(user_id), novo_saldo, agora, interaction.user.display_name)
        else:
            # Sem DB: usa memória com cooldown simples
            novo_saldo = get_fichas(user_id) + BONUS_DIARIO
            set_fichas(user_id, novo_saldo)

        await interaction.response.send_message(
            f"🎁 **{interaction.user.display_name}** resgatou **{BONUS_DIARIO} 🪙** de bônus diário!\n"
            f"Saldo atual: **{get_fichas(user_id)} 🪙**"
        )

    # ── Ranking ──
    @app_commands.command(name="ranking", description="Top 10 jogadores do cassino")
    async def ranking(self, interaction: discord.Interaction):
        if not db_pool:
            # Fallback: ranking por memória
            top = sorted(fichas.items(), key=lambda x: x[1], reverse=True)[:10]
            embed = discord.Embed(title="🏆 Ranking do Cassino", color=0xFFD700)
            for i, (uid, saldo) in enumerate(top, 1):
                medal = ["🥇","🥈","🥉"].get(i-1, f"{i}.")  if i <= 3 else f"{i}."
                embed.add_field(name=f"{medal} <@{uid}>", value=f"**{saldo} 🪙**", inline=False)
            await interaction.response.send_message(embed=embed)
            return

        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT nome, fichas, vitorias, derrotas, maior_ganho
                FROM cassino_fichas
                ORDER BY fichas DESC
                LIMIT 10
            """)

        embed = discord.Embed(
            title="🏆 Ranking do Cassino",
            description="Os 10 jogadores mais ricos do servidor",
            color=0xFFD700
        )
        medals = ["🥇","🥈","🥉"]
        for i, row in enumerate(rows, 1):
            medal = medals[i-1] if i <= 3 else f"**{i}.**"
            nome  = row["nome"] or f"Jogador {i}"
            taxa  = f"{row['vitorias']}V/{row['derrotas']}D" if (row['vitorias'] + row['derrotas']) > 0 else "—"
            embed.add_field(
                name=f"{medal} {nome}",
                value=f"**{row['fichas']} 🪙** | {taxa} | maior ganho: {row['maior_ganho']} 🪙",
                inline=False
            )
        embed.set_footer(text="Atualizado em tempo real")
        await interaction.response.send_message(embed=embed)

    # ── Perfil / Histórico ──
    @app_commands.command(name="perfil", description="Veja seu histórico e estatísticas")
    async def perfil(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        saldo   = get_fichas(user_id)

        embed = discord.Embed(
            title=f"🎰 Perfil de {interaction.user.display_name}",
            color=0x2B5219
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name="💰 Saldo", value=f"**{saldo} 🪙**", inline=True)

        if db_pool:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT vitorias, derrotas, maior_ganho, total_apostado
                    FROM cassino_fichas WHERE user_id = $1
                """, str(user_id))
                historico = await conn.fetch("""
                    SELECT jogo, resultado, valor, ts
                    FROM cassino_historico
                    WHERE user_id = $1
                    ORDER BY ts DESC LIMIT 5
                """, str(user_id))

            if row:
                total = (row["vitorias"] or 0) + (row["derrotas"] or 0)
                taxa  = f"{round(row['vitorias']/total*100)}%" if total > 0 else "—"
                embed.add_field(name="🏆 Vitórias", value=str(row["vitorias"] or 0), inline=True)
                embed.add_field(name="💔 Derrotas", value=str(row["derrotas"] or 0), inline=True)
                embed.add_field(name="📈 Taxa de vitória", value=taxa, inline=True)
                embed.add_field(name="🚀 Maior ganho", value=f"{row['maior_ganho'] or 0} 🪙", inline=True)
                embed.add_field(name="💸 Total apostado", value=f"{row['total_apostado'] or 0} 🪙", inline=True)

            if historico:
                hist_txt = ""
                for h in historico:
                    emoji   = "✅" if h["resultado"] == "vitoria" else "❌"
                    data    = h["ts"].strftime("%d/%m %H:%M")
                    hist_txt += f"{emoji} **{h['jogo']}** — {h['valor']} 🪙 ({data})\n"
                embed.add_field(name="📋 Últimas 5 partidas", value=hist_txt, inline=False)
        else:
            embed.add_field(name="⚠️", value="Conecte o Postgres para ver estatísticas completas.", inline=False)

        await interaction.response.send_message(embed=embed)

    # ── Ajuda ──
    @app_commands.command(name="ajuda", description="Mostra todos os comandos do cassino")
    async def ajuda(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎰 Cassino — Comandos",
            description="Bem-vindo ao cassino! Aqui estão todos os jogos disponíveis.",
            color=0xFFD700
        )
        embed.add_field(name="💰 Fichas & Perfil", value=(
            "`/fichas` — saldo atual\n"
            "`/diario` — bônus diário de **200 🪙**\n"
            "`/ranking` — top 10 do servidor\n"
            "`/perfil` — suas estatísticas e histórico"
        ), inline=False)
        embed.add_field(name="🃏 Truco Paulista", value=(
            "`/truco 1v1` `/truco 2v2` — multiplayer\n"
            "`/truco_solo` — contra o bot\n"
            "`/truco_pedir` · `/minha_mao` · `/placar` · `/encerrar`"
        ), inline=False)
        embed.add_field(name="🎴 Blackjack (21)", value=(
            "`/21` — solo ou até 6 jogadores\n"
            "`/21_encerrar`"
        ), inline=False)
        embed.add_field(name="♠️ Poker Texas Hold'em", value=(
            "`/poker` — 2–9 jogadores · `/poker_solo` — vs IA\n"
            "`/minhas_cartas` · `/poker_encerrar`"
        ), inline=False)
        embed.add_field(name="🎰 Roleta", value=(
            "`/roleta` — número(35x) · cor(2x) · par/ímpar(2x) · metade(2x) · dezena(3x)"
        ), inline=False)
        embed.add_field(name="🦁 Jogo do Bicho", value=(
            "`/bicho` — 25 bichos, acertar paga **18x**"
        ), inline=False)
        embed.add_field(name="🃏 UNO", value="`/uno` — 2–8 jogadores · `/uno_encerrar`", inline=False)
        embed.add_field(name="🁣 Dominó", value=(
            "`/domino` · `/domino_solo` · `/domino_encerrar`"
        ), inline=False)
        embed.add_field(name="♟️ Xadrez", value=(
            "`/xadrez` · `/xadrez_solo` · `/xadrez_entrar` · `/xadrez_encerrar`"
        ), inline=False)
        embed.set_footer(text="⏰ Partidas encerram automaticamente após 10 min de inatividade")
        await interaction.response.send_message(embed=embed)

    @cassino_set.error
    @cassino_remover.error
    async def admin_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Você precisa ser Admin.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(BaseCog(bot))
