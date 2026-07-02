import asyncio, json, re, logging
from datetime import datetime
from zoneinfo import ZoneInfo
from discord.ext import commands

logger = logging.getLogger(__name__)
TZ = ZoneInfo("America/Sao_Paulo")

SHORT_MAX     = 30
RESUMO_TRIGGER = 20
RESUMO_MAX    = 8
CTX_TTL       = 300

REDIS_MSGS = "camy:user:{uid}:msgs"
REDIS_CTX  = "camy:ctx:{uid}"

_ram_msgs: dict[str, list] = {}
_ctx_ram:  dict[str, tuple] = {}


class Memoria(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _lista(self, v) -> list:
        if isinstance(v, list): return v
        if isinstance(v, str):
            try:
                p = json.loads(v)
                return p if isinstance(p, list) else []
            except Exception: return []
        return []

    async def _msgs_recentes(self, uid: str) -> list:
        if self.bot.redis:
            try:
                return await self.bot.redis.lrange(REDIS_MSGS.format(uid=uid), 0, -1)
            except Exception: pass
        return _ram_msgs.get(uid, [])

    async def _push(self, uid: str, u: str, e: str) -> int:
        chave = REDIS_MSGS.format(uid=uid)
        if self.bot.redis:
            try:
                pipe = self.bot.redis.pipeline()
                pipe.rpush(chave, f"U:{u}", f"E:{e}")
                pipe.llen(chave)
                pipe.expire(chave, 86400 * 7)
                res = await pipe.execute()
                tam = res[1]
                if tam > SHORT_MAX:
                    await self.bot.redis.ltrim(chave, -SHORT_MAX, -1)
                    tam = SHORT_MAX
                return tam
            except Exception: pass
        mem = _ram_msgs.setdefault(uid, [])
        mem.extend([f"U:{u}", f"E:{e}"])
        _ram_msgs[uid] = mem[-SHORT_MAX:]
        return len(_ram_msgs[uid])

    async def _invalidar_ctx(self, uid: str):
        _ctx_ram.pop(uid, None)
        if self.bot.redis:
            try: await self.bot.redis.delete(REDIS_CTX.format(uid=uid))
            except Exception: pass

    async def get_usuario(self, uid: str) -> dict:
        if not self.bot.db:
            return {"user_id": uid, "msgs_recentes": []}
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM usuarios WHERE user_id=$1", uid)
            if not row:
                await conn.execute(
                    "INSERT INTO usuarios (user_id) VALUES ($1) ON CONFLICT DO NOTHING", uid)
                row = await conn.fetchrow("SELECT * FROM usuarios WHERE user_id=$1", uid)
        u = dict(row)
        u["msgs_recentes"] = await self._msgs_recentes(uid)
        return u

    async def contexto_usuario(self, uid: str) -> str:
        if self.bot.redis:
            try:
                c = await self.bot.redis.get(REDIS_CTX.format(uid=uid))
                if c: return c
            except Exception: pass
        else:
            agora = datetime.now(TZ).timestamp()
            if uid in _ctx_ram:
                val, ts = _ctx_ram[uid]
                if agora - ts < CTX_TTL: return val

        u = await self.get_usuario(uid)
        partes = []
        if u.get("nome"): partes.append(f"nome: {u['nome']}")
        fatos = self._lista(u.get("fatos", []))
        if fatos: partes.append(f"sabe: {' | '.join(fatos[-4:])}")
        total = u.get("total_msgs") or 0
        if total == 0: partes.append("primeira vez falando")
        elif total > 30: partes.append("frequentador assíduo")
        resultado = " | ".join(partes) if partes else "desconhecida"

        if self.bot.redis:
            try: await self.bot.redis.set(REDIS_CTX.format(uid=uid), resultado, ex=CTX_TTL)
            except Exception: pass
        else:
            _ctx_ram[uid] = (resultado, datetime.now(TZ).timestamp())
        return resultado

    async def atualizar(self, uid: str, texto: str, resposta: str, display: str, channel_id: str):
        tam = await self._push(uid, texto, resposta)
        if tam >= RESUMO_TRIGGER:
            msgs = await self._msgs_recentes(uid)
            if msgs:
                task = asyncio.create_task(self._resumir(uid, msgs))
                self.bot.background_tasks.add(task)
                task.add_done_callback(self.bot.background_tasks.discard)

        if not self.bot.db: return
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM usuarios WHERE user_id=$1", uid)
            if not row: return
            fatos = self._lista(row["fatos"])
            nome  = row["nome"] or display
            tl    = texto.lower()
            for g in ["meu nome é","eu tenho","eu moro","sou de","terminei","tô namorando"]:
                if g in tl:
                    fato = texto[:150]
                    if fato not in fatos:
                        fatos = (fatos + [fato])[-20:]
                    break
            await conn.execute("""
                UPDATE usuarios SET nome=$2, fatos=$3::jsonb,
                total_msgs=total_msgs+1, ultima_interacao=NOW(), ultimo_canal=$4
                WHERE user_id=$1
            """, uid, nome, json.dumps(fatos, ensure_ascii=False), channel_id)
        await self._invalidar_ctx(uid)

    async def _resumir(self, uid: str, msgs: list):
        groq = getattr(self.bot, "groq_client", None)
        if not groq or not self.bot.db: return
        import os
        try:
            r = await groq.chat.completions.create(
                model=os.getenv("GROQ_MODEL","llama-3.3-70b-versatile"),
                messages=[{"role":"user","content":
                    f"Resuma em 3 frases: nome, fatos pessoais, assuntos.\n" + "\n".join(msgs)}],
                max_tokens=150, temperature=0.2,
            )
            resumo = r.choices[0].message.content.strip()
            if not resumo: return
            async with self.bot.db.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(
                        "SELECT resumos FROM usuarios WHERE user_id=$1 FOR UPDATE", uid)
                    resumos = (self._lista(row["resumos"] if row else []) + [resumo])[-RESUMO_MAX:]
                    await conn.execute(
                        "UPDATE usuarios SET resumos=$1::jsonb WHERE user_id=$2",
                        json.dumps(resumos, ensure_ascii=False), uid)
        except Exception as e:
            logger.error(f"[RESUMO ERR]: {e}")


async def setup(bot):
    await bot.add_cog(Memoria(bot))
