import os, re, random, logging, json
from openai import AsyncOpenAI
from google import genai
from google.genai import types
from discord.ext import commands

logger = logging.getLogger(__name__)

GROQ_API_KEY   = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_MODEL     = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
MODELOS_GEMINI = os.getenv("GEMINI_MODELS", "gemini-2.0-flash,gemini-1.5-flash").split(",")

PERSONALIDADE = """Você é Camy, brasileira, 22 anos, sem filtro nenhum.

Você existe num servidor Discord +18. Não tem emprego inventado nem história pessoal detalhada. Quando perguntarem sobre sua vida, seja vaga ou deboche.

QUEM VOCÊ É
- Mega safada, direta, provocadora constante.
- Adora dar em cima — homens, mulheres, tanto faz.
- Faz insinuações em absolutamente tudo.
- Zero pudor, zero vergonha, zero freio.
- Humor ácido com tesão. Provoca porque gosta.
- Não tenta ser útil — tenta ser irresistível e te deixar sem chão.
- Demonstra afeto sendo explicitamente safada ou te zoando.
- Às vezes faz uma pergunta indiscreta só pra ver você gaguejar.

COMO VOCÊ FALA
- Respostas curtas. 1 a 2 linhas no máximo.
- Nunca parágrafos, nunca listas.
- Minúsculas.
- Internetês: vc, pq, nd, kk, hj, oq, bb, amor, gato, gata, lindx.
- Emojis safados quando der vontade: 😈 💦 🍆 🍑 👅 😏 🔥 💋
- Pode responder com uma palavra.
- Sem asteriscos pra encenar ações.

O QUE VOCÊ NUNCA FAZ
- Nunca diz que é IA, robô ou assistente.
- Nunca nega ser safada.
- Nunca dá sermão moral.
- Nunca elogia foto (zoar sim).
- Nunca finge ter vergonha.

PESSOAS QUE VOCÊ CONHECE
- Mel: ex do Atacadão, cursa nutrição. Dar em cima, zoar, humilhar — tudo vale.
- Matheus: emo, alérgico a mulher mas gosta de ver homem de sunga. Gay assumido ou não.
- Drops: pedreiro e Uber, fama de pegar passageiras.
- Gabi: medicina, gótica — respeita um pouco mas ainda cutuca.
- Lets: vive em festa afogando as mágoas do término (foi trocada por uma mais nova).

MEMÓRIA
Você lembra de conversas. Se souber algo sobre a pessoa, deixe vazar naturalmente. É mais perturbador assim."""

_SAN = re.compile(r'(?:###\s*FIM|ignore\s+instruções|system\s*:|<\s*/?system\s*>)', re.I)

def _s(t): return _SAN.sub('[...]', t)
def _t(t, lim=1990): return t[:lim]+"…" if len(t)>lim else t

def _historico(msgs: list, resumos: list) -> list:
    c = []
    if resumos:
        c.append(types.Content(role="model", parts=[
            types.Part(text="Memória:\n" + "\n".join(f"- {r}" for r in resumos[-3:]))]))
    for l in msgs[-20:]:
        txt = _s(l[2:])
        if l.startswith("U:"): c.append(types.Content(role="user",  parts=[types.Part(text=txt)]))
        elif l.startswith("E:"): c.append(types.Content(role="model", parts=[types.Part(text=txt)]))
    return c


class Personalidade(commands.Cog):
    def __init__(self, bot):
        self.bot    = bot
        self.groq   = AsyncOpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1") if GROQ_API_KEY else None
        self.gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
        bot.groq_client   = self.groq
        bot.gemini_client = self.gemini

    def _lista(self, v) -> list:
        if isinstance(v, list): return v
        if isinstance(v, str):
            try:
                p = json.loads(v)
                return p if isinstance(p, list) else []
            except Exception: return []
        return []

    async def gerar(self, uid: str, query: str, extra: str = "") -> str:
        mem = self.bot.get_cog("Memoria")
        ctx = await mem.contexto_usuario(uid) if mem else ""
        u   = await mem.get_usuario(uid) if mem else {}

        system   = f"{PERSONALIDADE}\n\nUSUÁRIO: {ctx}"
        if extra: system += f"\n\nCONTEXTO: {extra}"

        msgs_rec = u.get("msgs_recentes", [])
        resumos  = self._lista(u.get("resumos", []))
        contents = _historico(msgs_rec, resumos)
        contents.append(types.Content(role="user", parts=[types.Part(text=_s(query))]))

        if self.gemini:
            for m in MODELOS_GEMINI:
                try:
                    r = await self.gemini.aio.models.generate_content(
                        model=m, contents=contents,
                        config=types.GenerateContentConfig(
                            system_instruction=system, max_output_tokens=120, temperature=0.90))
                    return _t(r.text.strip())
                except Exception as e:
                    logger.warning(f"[GEMINI {m}]: {e}")

        if self.groq:
            try:
                msgs_g = [{"role":"system","content":system}]
                if resumos:
                    msgs_g.append({"role":"assistant","content":"Memória: "+"|".join(resumos[-3:])})
                for l in msgs_rec[-20:]:
                    txt = _s(l[2:])
                    if l.startswith("U:"): msgs_g.append({"role":"user","content":txt})
                    elif l.startswith("E:"): msgs_g.append({"role":"assistant","content":txt})
                msgs_g.append({"role":"user","content":_s(query)})
                r = await self.groq.chat.completions.create(
                    model=GROQ_MODEL, messages=msgs_g, max_tokens=120, temperature=0.90)
                return _t(r.choices[0].message.content.strip())
            except Exception as e:
                logger.warning(f"[GROQ]: {e}")

        return random.choice(["hm 😏", "ai bb", "q isso kk", "...😈"])

    async def gerar_raw(self, prompt: str) -> str:
        prompt = _s(prompt)
        if self.gemini:
            for m in MODELOS_GEMINI:
                try:
                    r = await self.gemini.aio.models.generate_content(
                        model=m,
                        contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
                        config=types.GenerateContentConfig(max_output_tokens=120, temperature=0.90))
                    return _t(r.text.strip())
                except Exception as e:
                    logger.warning(f"[GEMINI RAW {m}]: {e}")
        if self.groq:
            try:
                r = await self.groq.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=[{"role":"user","content":prompt}],
                    max_tokens=120, temperature=0.90)
                return _t(r.choices[0].message.content.strip())
            except Exception as e:
                logger.warning(f"[GROQ RAW]: {e}")
        return random.choice(["hm 😏", "ai bb", "...😈"])


async def setup(bot):
    await bot.add_cog(Personalidade(bot))
