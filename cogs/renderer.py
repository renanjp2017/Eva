"""
renderer.py — Mesa gótica usando os fundos reais (Alice no País das Maravilhas).
Landscape 1536x1024 → redimensionado para 1024x682 (Discord-safe).
Portrait  1024x1536 → usado para xadrez (tabuleiro precisa de mais altura).

Zonas no landscape (em proporção da imagem):
  Plaquinha título : x 510-1026, y 42-118   (px originais 1536x1024)
  Feltro seguro    : x 280-1260, y 148-870

Zonas no portrait (1024x1536):
  Plaquinha título : x 340-684, y 55-145
  Feltro seguro    : x 120-900, y 150-1280
"""
import io, math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ── Dimensões de saída ────────────────────────────────────────────────────────
OUT_W, OUT_H   = 1024, 682   # landscape → Discord OK em qualquer tela
OUT_WP, OUT_HP = 682, 1024   # portrait  → xadrez

# Fundo original: 1536x1024 landscape, 1024x1536 portrait
_ASSETS = Path(__file__).parent.parent / "assets"
_BG_L   = _ASSETS / "mesa_landscape.jpg"
_BG_P   = _ASSETS / "mesa_portrait.jpg"

# ── Zonas no OUTPUT (proporcional) ────────────────────────────────────────────
# Landscape output 1024x682
# Plaquinha: originalmente x[510-1026]/1536 * 1024, y[42-118]/1024 * 682
PLAQUE_L = (340, 28, 684, 78)    # (x1,y1,x2,y2) na imagem output
FELT_L   = (186, 98, 840, 580)   # área segura do feltro landscape

# Portrait output 682x1024
PLAQUE_P = (171, 36, 456, 97)
FELT_P   = (80,  100, 600, 854)

# ── Paleta de texto ───────────────────────────────────────────────────────────
GOLD     = (210, 170,  80)
GOLD_LT  = (240, 210, 120)
CREAM    = (240, 225, 200)
DARK     = ( 15,   8,  20)
RED_BRT  = (180,  20,  20)
WHITE_O  = (245, 238, 220)
SHADOW   = (  0,   0,   0)

# ── Cartas ────────────────────────────────────────────────────────────────────
_CARDS_DIR   = Path(__file__).parent.parent / "cards" / "genereted"
_SUIT_NAMES  = {"♠":"espadas","♥":"copas","♦":"ouros","♣":"paus"}
_VALUE_NAMES = {"A":"as","J":"valete","Q":"dama","K":"rei",
                **{str(i):str(i) for i in range(2,11)}}

def _parse(carta: str) -> tuple[str,str]:
    return (carta[:-1], carta[-1]) if carta and carta[-1] in "♠♥♦♣" else (carta,"")

def _card_img(value: str, suit: str, w=80, h=112) -> Image.Image:
    v = _VALUE_NAMES.get(value, value.lower())
    s = _SUIT_NAMES.get(suit, suit.lower())
    p = _CARDS_DIR / f"{v}_{s}.png"
    if p.exists():
        return Image.open(p).convert("RGBA").resize((w,h), Image.LANCZOS)
    return _card_back(w, h)

def _card_back(w=80, h=112) -> Image.Image:
    img  = Image.new("RGBA", (w,h), (0,0,0,0))
    draw = ImageDraw.Draw(img,"RGBA")
    draw.rounded_rectangle([0,0,w-1,h-1], radius=6,
                            fill=(15,8,25,255), outline=(*GOLD,200), width=2)
    cx,cy,d = w//2,h//2,10
    draw.polygon([(cx,cy-d),(cx+d,cy),(cx,cy+d),(cx-d,cy)], fill=(100,0,0,200))
    draw.polygon([(cx,cy-5),(cx+5,cy),(cx,cy+5),(cx-5,cy)], fill=(*GOLD,200))
    return img

# ── Fontes ────────────────────────────────────────────────────────────────────
_FD = Path("/usr/share/fonts/truetype")
def _font(size, bold=True):
    try:
        p = _FD/"dejavu/DejaVuSerif-Bold.ttf" if bold else _FD/"dejavu/DejaVuSerif.ttf"
        return ImageFont.truetype(str(p), size)
    except:
        return ImageFont.load_default(size=size)

def _sans(size):
    try:
        return ImageFont.truetype(str(_FD/"liberation/LiberationSans-Bold.ttf"), size)
    except:
        return ImageFont.load_default(size=size)

# ── Base da mesa ──────────────────────────────────────────────────────────────
def _base(portrait=False) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    src = _BG_P if portrait else _BG_L
    ow, oh = (OUT_WP, OUT_HP) if portrait else (OUT_W, OUT_H)
    if src.exists():
        bg = Image.open(src).convert("RGB").resize((ow,oh), Image.LANCZOS)
    else:
        bg = Image.new("RGB", (ow,oh), (30,8,10))
    draw = ImageDraw.Draw(bg, "RGBA")
    return bg, draw

def _write_title(draw, title: str, portrait=False):
    px1,py1,px2,py2 = PLAQUE_P if portrait else PLAQUE_L
    cx = (px1+px2)//2; cy = (py1+py2)//2
    # Fundo semitransparente na plaquinha
    draw.rounded_rectangle([px1+4,py1+4,px2-4,py2-4], radius=6,
                            fill=(8,4,12,200))
    f = _font(int((py2-py1)*0.55))
    # Sombra
    draw.text((cx+2,cy+2), title.upper(), font=f, fill=(*SHADOW,180), anchor="mm")
    draw.text((cx, cy),    title.upper(), font=f, fill=GOLD_LT,        anchor="mm")

def _tc(draw, text, cx, cy, f, color=CREAM, shadow=True):
    if shadow:
        draw.text((cx+1,cy+1), text, font=f, fill=(*SHADOW,160), anchor="mm")
    draw.text((cx,cy), text, font=f, fill=color, anchor="mm")

def _badge(draw, text: str, cx, cy, bw=110, bh=30, color=GOLD, bg=(10,5,15,210)):
    draw.rounded_rectangle([cx-bw//2,cy-bh//2,cx+bw//2,cy+bh//2],
                            radius=6, fill=bg, outline=(*color,180), width=1)
    _tc(draw, text, cx, cy, _sans(13), color)

def _label(draw, text, cx, cy, size=13, color=CREAM):
    _tc(draw, text, cx, cy, _font(size, bold=False), color, shadow=False)

def _section(draw, text, cx, cy):
    f = _font(14)
    tw = int(draw.textlength(text, font=f))
    pad = 14
    draw.rounded_rectangle([cx-tw//2-pad,cy-12,cx+tw//2+pad,cy+13],
                            radius=5, fill=(8,4,12,200), outline=(*GOLD,150), width=1)
    _tc(draw, text, cx, cy, f, GOLD_LT)

def _wave(draw, y, cx, width=220, color=GOLD):
    x1,x2 = cx-width//2, cx+width//2
    draw.line([(x1,y),(x1+40,y)], fill=(*color,110), width=1)
    draw.line([(x2-40,y),(x2,y)], fill=(*color,110), width=1)
    pts = [(x1+40+i, y+int(math.sin(i/7*math.pi)*3)) for i in range(x2-x1-80)]
    if len(pts)>1: draw.line(pts, fill=(*color,140), width=1)
    d=4
    draw.polygon([(cx,y-d),(cx+d,y),(cx,y+d),(cx-d,y)], fill=(*color,200))

def _to_bytes(img):
    buf = io.BytesIO()
    img.save(buf,"PNG")
    buf.seek(0)
    return buf

def _paste_card(base, card_img, x, y):
    if card_img.mode == "RGBA":
        base.paste(card_img, (x,y), card_img)
    else:
        base.paste(card_img, (x,y))

# ════════════════════════════════════════════════════════════════════════════
#  BLACKJACK  — landscape 1024x682
#  Dealer no topo, jogadores embaixo, placar lateral
# ════════════════════════════════════════════════════════════════════════════
def render_blackjack(dealer_cards, dealer_value, players,
                     hide_dealer_second=True, message=""):
    img, draw = _base()
    W, H = OUT_W, OUT_H
    cx   = W//2

    _write_title(draw, "Blackjack · 21")

    CW, CH = 82, 114

    # ── Regras no feltro ──────────────────────────────────────────────────
    for i,txt in enumerate(["Blackjack pays 3 to 2",
                             "Dealer must hit soft 17",
                             "Insurance pays 2 to 1"]):
        draw.text((cx, H//2-14+i*18), txt, font=_font(10,False),
                  fill=(*GOLD,55), anchor="mm")

    # ── DEALER ────────────────────────────────────────────────────────────
    dy = 100
    _section(draw, "DEALER", cx, dy-28)
    _wave(draw, dy-10, cx, 220)

    n = len(dealer_cards)
    tw = n*CW+(n-1)*6
    sx = cx-tw//2
    for i,carta in enumerate(dealer_cards):
        xi = sx+i*(CW+6)
        if hide_dealer_second and i==0:
            ci = _card_back(CW,CH)
        else:
            v,s = _parse(carta)
            ci  = _card_img(v,s,CW,CH)
        _paste_card(img, ci, xi, dy)

    shown = "?" if hide_dealer_second else str(dealer_value)
    _badge(draw, shown, cx, dy+CH+20, bw=60, bh=28, color=CREAM)

    # ── JOGADORES ─────────────────────────────────────────────────────────
    n_pl = len(players)
    py_base = H-CH-90
    _wave(draw, py_base-18, cx, 280)
    _section(draw, "PLAYER" + ("S" if n_pl>1 else ""), cx, py_base-38)

    slot = min(190, (W-80)//max(n_pl,1))
    sx_pl = cx - (n_pl*slot)//2 + slot//2

    for i,pl in enumerate(players):
        pcx = sx_pl + i*slot
        pcy = py_base

        is_active = pl.get("active",False)
        status    = pl.get("status","")
        folded    = status in ("bust","fold")

        pl_cards = pl.get("cards",[])
        nc = len(pl_cards)
        cw2 = min(CW, max(40, (slot-20)//max(nc,1)-2))
        ch2 = int(cw2*1.4)
        tw2 = nc*cw2+(nc-1)*4
        sx2 = pcx-tw2//2

        for j,carta in enumerate(pl_cards):
            v,s = _parse(carta)
            ci  = _card_img(v,s,cw2,ch2)
            if folded:
                gray = ci.convert("LA").convert("RGBA")
                _paste_card(img, gray, sx2+j*(cw2+4), pcy)
            else:
                _paste_card(img, ci, sx2+j*(cw2+4), pcy)

        val = pl.get("value",0)
        vc  = RED_BRT if val>21 else (GOLD_LT if val==21 else CREAM)
        _badge(draw, str(val), pcx, pcy+ch2+16, bw=50,bh=26, color=vc)

        st_txt = {"bust":"💥","bj":"🌟","stand":"✋"}.get(status,"")
        bg_c   = (50,15,8,220) if is_active else (8,4,12,210)
        bd_c   = RED_BRT if is_active else GOLD
        _badge(draw, pl["name"][:12]+st_txt, pcx, pcy+ch2+40,
               bw=120,bh=26, color=CREAM, bg=(*bg_c[:3],220))
        # Redraws border only
        draw.rounded_rectangle([pcx-60,pcy+ch2+27,pcx+60,pcy+ch2+53],
                                radius=6, fill=None, outline=(*bd_c,200), width=2)

        bet = pl.get("bet",0)
        if bet:
            _label(draw, f"🪙 {bet}", pcx, pcy+ch2+60, size=12)

    # ── Mensagem ──────────────────────────────────────────────────────────
    if message:
        _msg_bar(draw, message, W, H)

    return _to_bytes(img)


# ════════════════════════════════════════════════════════════════════════════
#  TRUCO  — landscape 1024x682
# ════════════════════════════════════════════════════════════════════════════
def render_truco(equipe1_nome, equipe1_pts, equipe2_nome, equipe2_pts,
                 rodada_vale, maos_ganhas, mesa_cartas, jogador_vez,
                 rodada=1, message=""):
    img, draw = _base()
    W,H = OUT_W, OUT_H
    cx  = W//2

    _write_title(draw, "Truco Paulista")

    # ── Placar topo ───────────────────────────────────────────────────────
    _badge(draw, f"{equipe1_nome[:12]}  {equipe1_pts}pts",
           175, 100, bw=160, bh=34, color=GOLD)
    _badge(draw, f"{equipe2_nome[:12]}  {equipe2_pts}pts",
           W-175, 100, bw=160, bh=34, color=GOLD)
    _section(draw, f"Rodada {rodada} · Vale {rodada_vale}pt(s)", cx, 100)

    # ── Mãos ganhas ───────────────────────────────────────────────────────
    _wave(draw, 132, cx, 300)
    for i,v in enumerate(maos_ganhas):
        col_v = GOLD_LT if v not in ("Empate","") else CREAM
        _label(draw, f"Mão {i+1}: {v}", cx-80+i*80, 148, 12, col_v)

    # ── Cartas na mesa ────────────────────────────────────────────────────
    CW,CH = 74, 104
    mesa_y = H//2 - CH//2 + 10
    nm = len(mesa_cartas)
    if nm:
        tw = nm*(CW+8)-8
        sx = cx-tw//2
        for i,(nome,carta) in enumerate(mesa_cartas):
            xi = sx+i*(CW+8)
            v,s = _parse(carta)
            ci  = _card_img(v,s,CW,CH)
            _paste_card(img,ci,xi,mesa_y)
            _label(draw, nome[:10], xi+CW//2, mesa_y+CH+14, 11, CREAM)
    else:
        draw.ellipse([cx-30,H//2-30,cx+30,H//2+30],
                     fill=None, outline=(*GOLD,50), width=1)
        _label(draw,"Aguardando...",cx,H//2,13,(*GOLD,120))

    # ── Vez ───────────────────────────────────────────────────────────────
    _wave(draw, H-118, cx, 280)
    _section(draw, f"Vez de  {jogador_vez}", cx, H-96)

    if message:
        _msg_bar(draw, message, W, H)

    return _to_bytes(img)


# ════════════════════════════════════════════════════════════════════════════
#  XADREZ  — portrait 682x1024  (mais alto = tabuleiro cabe melhor)
# ════════════════════════════════════════════════════════════════════════════
XADREZ_EMOJIS = {
    ('b','K'):'♔',('b','Q'):'♕',('b','R'):'♖',
    ('b','B'):'♗',('b','N'):'♘',('b','P'):'♙',
    ('p','K'):'♚',('p','Q'):'♛',('p','R'):'♜',
    ('p','B'):'♝',('p','N'):'♞',('p','P'):'♟',
}

def render_xadrez(tabuleiro, branco_nome, preto_nome, vez,
                  sel=None, movs=None, message="", xeque=False):
    img, draw = _base(portrait=True)
    W,H = OUT_WP, OUT_HP
    cx  = W//2

    _write_title(draw, "Xadrez", portrait=True)

    # ── Tabuleiro ─────────────────────────────────────────────────────────
    CELL  = 72
    BOARD = CELL*8
    bx    = cx - BOARD//2
    by    = H//2 - BOARD//2 + 20

    movs_set = set(movs) if movs else set()

    # Borda do tabuleiro
    draw.rectangle([bx-5,by-5,bx+BOARD+5,by+BOARD+5],
                   fill=(8,4,12,200), outline=(*GOLD,220), width=3)

    fp = _font(34)
    fl = _font(12,False)

    for lin in range(8):
        for col in range(8):
            x   = bx + col*CELL
            y   = by + (7-lin)*CELL
            pos = (col,lin)
            claro = (col+lin)%2==0

            if sel and pos==sel:
                cc = (180,100,15)
            elif pos in movs_set:
                cc = (160,140,15)
            elif claro:
                cc = (200,178,140)
            else:
                cc = (72, 48, 25)

            draw.rectangle([x,y,x+CELL-1,y+CELL-1], fill=cc)

            if pos in tabuleiro:
                cor,tipo = tabuleiro[pos]
                emoji    = XADREZ_EMOJIS.get((cor,tipo),"?")
                pc  = WHITE_O if cor=='b' else DARK
                sh  = DARK    if cor=='b' else WHITE_O
                draw.text((x+CELL//2+2,y+CELL//2+2), emoji, font=fp,
                          fill=(*sh,140), anchor="mm")
                draw.text((x+CELL//2,  y+CELL//2),   emoji, font=fp,
                          fill=pc, anchor="mm")

            if pos in movs_set and pos not in tabuleiro:
                r=9; ox=x+CELL//2; oy=y+CELL//2
                draw.ellipse([ox-r,oy-r,ox+r,oy+r], fill=(*GOLD,180))

        # Número lateral
        draw.text((bx-12, by+(7-lin)*CELL+CELL//2), str(lin+1),
                  font=fl, fill=(*GOLD,180), anchor="mm")

    # Letras abaixo
    for col in range(8):
        draw.text((bx+col*CELL+CELL//2, by+BOARD+14), "ABCDEFGH"[col],
                  font=fl, fill=(*GOLD,180), anchor="mm")

    # ── Nomes ─────────────────────────────────────────────────────────────
    _badge(draw, f"♚ {preto_nome[:14]}", cx, by-26,
           bw=160,bh=28, color=GOLD if vez=='p' else CREAM)
    _badge(draw, f"♔ {branco_nome[:14]}", cx, by+BOARD+42,
           bw=160,bh=28, color=GOLD if vez=='b' else CREAM)

    if xeque:
        _msg_bar(draw, "⚠️  XEQUE!", W, H, color=RED_BRT)
    elif message:
        _msg_bar(draw, message, W, H)

    return _to_bytes(img)


# ════════════════════════════════════════════════════════════════════════════
#  POKER  — landscape 1024x682
# ════════════════════════════════════════════════════════════════════════════
def render_poker(community_cards, players, pot, stage, message=""):
    img, draw = _base()
    W,H = OUT_W, OUT_H
    cx  = W//2

    _write_title(draw, f"Poker · {stage.title()}")

    CW,CH   = 70,98
    CWP,CHP = 52,73

    # ── Pote ──────────────────────────────────────────────────────────────
    _badge(draw, f"🪙 {pot}", cx, H//2-8, bw=120,bh=34, color=GOLD)
    _label(draw, "POT", cx, H//2-28, 12, GOLD)

    # ── Cartas comunitárias ───────────────────────────────────────────────
    comm_y = H//2-CH-46
    nc = len(community_cards)
    if nc:
        tw = nc*(CW+6)-6
        sx = cx-tw//2
        for i,carta in enumerate(community_cards):
            v,s = _parse(carta)
            ci  = _card_img(v,s,CW,CH)
            _paste_card(img,ci,sx+i*(CW+6),comm_y)
    else:
        for i in range(5):
            sx = cx-(5*(CW+6)-6)//2+i*(CW+6)
            ci = _card_back(CW,CH)
            fade = ci.copy()
            for py2 in range(CH):
                for px2 in range(CW):
                    r,g,b,a = fade.getpixel((px2,py2))
                    fade.putpixel((px2,py2),(r,g,b,a//4))
            _paste_card(img,fade,sx,comm_y)

    _wave(draw, comm_y-14, cx, 380)
    _wave(draw, H//2+32,   cx, 260)

    # ── Jogadores ao redor ────────────────────────────────────────────────
    n = len(players)
    positions = _oval(n, cx, H//2+10, rx=int(W*0.38), ry=int(H*0.29))

    for i,pl in enumerate(players):
        px,py = positions[i]
        folded = pl.get("folded",False)
        active = pl.get("active",False)
        status = pl.get("status","")
        pl_cards = pl.get("cards",[])
        nc2 = len(pl_cards)
        tw2 = nc2*CWP+(nc2-1)*4
        sx2 = px-tw2//2

        for j,carta in enumerate(pl_cards):
            v,s = _parse(carta)
            ci  = _card_img(v,s,CWP,CHP) if carta else _card_back(CWP,CHP)
            xj  = sx2+j*(CWP+4)
            yj  = py-CHP//2
            if folded:
                gray = ci.convert("LA").convert("RGBA")
                _paste_card(img,gray,xj,yj)
            else:
                _paste_card(img,ci,xj,yj)

        st_txt = {"fold":"FOLD","all-in":"ALL-IN","check":"✔","call":"CALL"}.get(status,"")
        bg_a = (50,15,8,220) if active else (8,4,12,210)
        _badge(draw, f"{pl['name'][:10]}{' '+st_txt if st_txt else ''}",
               px, py+CHP//2+18, bw=130,bh=26,
               color=GOLD if active else CREAM, bg=bg_a)
        chips = pl.get("chips",0)
        bet   = pl.get("bet",0)
        _label(draw, f"🪙{chips}", px, py+CHP//2+38,12)
        if bet:
            _label(draw, f"+{bet}", px, py+CHP//2+52,11,GOLD_LT)

    if message:
        _msg_bar(draw, message, W, H)

    return _to_bytes(img)

def _oval(n, cx, cy, rx, ry):
    pos=[]
    for i in range(n):
        a = math.pi/2 + 2*math.pi/n*i
        pos.append((int(cx+rx*math.cos(a)), int(cy+ry*math.sin(a))))
    return pos

# ── Barra de mensagem rodapé ──────────────────────────────────────────────────
def _msg_bar(draw, text, W, H, color=GOLD_LT):
    y=H-24
    draw.rounded_rectangle([80,y-14,W-80,y+14], radius=7,
                            fill=(8,4,12,220), outline=(*GOLD,140), width=1)
    _tc(draw, text[:80], W//2, y, _sans(13), color)
