"""
Gerador de cartas góticas usando Pillow puro.
Estética: Alice no País das Maravilhas, vitoriana, preto/branco/vermelho.
"""
import sys, math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

BG_CARD   = (245, 240, 232)
RED_DEEP  = (139, 0,   0)
RED_BRITE = (180, 20,  20)
GOLD      = (180, 148, 68)
GOLD_LT   = (220, 190, 100)
DARK_INK  = (20,  10,  30)
WHITE_OFF = (245, 240, 232)
SHADOW    = (180, 170, 155)

SUIT_COLOR  = {"♠": DARK_INK, "♣": DARK_INK, "♥": RED_BRITE, "♦": RED_BRITE}
SUIT_NAMES  = {"♠": "espadas", "♥": "copas", "♦": "ouros", "♣": "paus"}
VALUE_NAMES = {"A":"as","J":"valete","Q":"dama","K":"rei",
               **{str(i):str(i) for i in range(2,11)}}
SUITS  = ["♠","♥","♦","♣"]
VALUES = ["A","2","3","4","5","6","7","8","9","10","J","Q","K"]
W, H, S = 240, 336, 2

def font(size, bold=True):
    cands = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
    ]
    for p in cands:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)

def new_card():
    img  = Image.new("RGBA", (W*S, H*S), (0,0,0,0))
    draw = ImageDraw.Draw(img, "RGBA")
    # fundo
    draw.rounded_rectangle([0,0,W*S-1,H*S-1], radius=18*S,
                            fill=BG_CARD, outline=DARK_INK, width=3*S)
    draw.rounded_rectangle([6*S,6*S,W*S-7*S,H*S-7*S], radius=14*S,
                            fill=None, outline=(*GOLD,180), width=S)
    draw.rounded_rectangle([10*S,10*S,W*S-11*S,H*S-11*S], radius=12*S,
                            fill=None, outline=(*GOLD,70), width=S)
    return img, draw

def arabesque(draw, y):
    cx, yy = W*S//2, y*S
    m = 18*S
    draw.line([(m,yy),(cx-36*S,yy)], fill=(*GOLD,120), width=S)
    draw.line([(cx+36*S,yy),(W*S-m,yy)], fill=(*GOLD,120), width=S)
    pts=[(i, yy+int(math.sin((i-(cx-36*S))/(9*S)*math.pi)*3*S))
         for i in range(cx-36*S, cx+36*S, 2)]
    if len(pts)>=2: draw.line(pts, fill=(*GOLD,150), width=S)
    d=4*S
    draw.polygon([(cx,yy-d),(cx+d,yy),(cx,yy+d),(cx-d,yy)], fill=(*GOLD,210))

def corner_gem(draw, x, y):
    r=5*S
    for a in range(0,360,60):
        rad=math.radians(a)
        px=x+math.cos(rad)*r*0.7; py=y+math.sin(rad)*r*0.7
        draw.ellipse([px-r*0.3,py-r*0.3,px+r*0.3,py+r*0.3], fill=(*GOLD,100))
    draw.ellipse([x-r*0.35,y-r*0.35,x+r*0.35,y+r*0.35], fill=(*GOLD,200))

def corner_labels(draw, value, suit):
    c  = SUIT_COLOR[suit]
    fb = font(20*S); fs = font(14*S, bold=False)
    for (x,y,ys) in [(20*S,22*S,40*S),(( W-20)*S,(H-22)*S,(H-40)*S)]:
        draw.text((x+S,y+S), value, font=fb, fill=(*SHADOW,180), anchor="mm")
        draw.text((x,y),     value, font=fb, fill=(*c,255),       anchor="mm")
        draw.text((x,ys),    suit,  font=fs, fill=(*c,220),       anchor="mm")

def suit_txt(draw, cx, cy, suit, size, color, alpha=255):
    f=font(size)
    draw.text((cx+S,cy+S), suit, font=f, fill=(*SHADOW,alpha//2), anchor="mm")
    draw.text((cx,cy),     suit, font=f, fill=(*color,alpha),     anchor="mm")

def draw_clock(draw, cx, cy, r):
    r=r*S
    draw.ellipse([cx-r,cy-r,cx+r,cy+r], outline=(*GOLD,200), width=S)
    for h in range(12):
        a=math.radians(h*30-90)
        x1=cx+math.cos(a)*r*.76; y1=cy+math.sin(a)*r*.76
        x2=cx+math.cos(a)*r*.9;  y2=cy+math.sin(a)*r*.9
        draw.line([(x1,y1),(x2,y2)], fill=(*GOLD,170), width=S)
    draw.line([(cx,cy),(cx,cy-r*.55)], fill=(*DARK_INK,230), width=max(1,S))
    draw.line([(cx,cy),(cx+r*.38,cy+r*.28)], fill=(*DARK_INK,200), width=max(1,S))
    draw.ellipse([cx-2*S,cy-2*S,cx+2*S,cy+2*S], fill=(*GOLD,255))

def draw_rose(draw, cx, cy, sz):
    r=sz*S
    for a in range(0,360,40):
        rad=math.radians(a)
        px=cx+math.cos(rad)*r*.7; py=cy+math.sin(rad)*r*.7
        draw.ellipse([px-r*.45,py-r*.45,px+r*.45,py+r*.45], fill=(*RED_DEEP,170))
    draw.ellipse([cx-r*.5,cy-r*.5,cx+r*.5,cy+r*.5], fill=(*RED_BRITE,220))
    draw.ellipse([cx-r*.25,cy-r*.25,cx+r*.25,cy+r*.25], fill=(*GOLD,200))

def draw_mushroom(draw, cx, cy, sz):
    s=sz*S
    draw.rectangle([cx-s*.25,cy,cx+s*.25,cy+s*.7], fill=(*WHITE_OFF,200))
    draw.ellipse([cx-s,cy-s*.5,cx+s,cy+s*.5], fill=(*RED_BRITE,210))
    draw.ellipse([cx-s*.65,cy-s*.1,cx+s*.65,cy+s*.4], fill=(*RED_DEEP,150))
    for ox,oy in [(-0.4,-0.15),(0.3,-0.3),(0.0,-0.35)]:
        bx,by=cx+ox*s,cy+oy*s; br=s*.1
        draw.ellipse([bx-br,by-br,bx+br,by+br], fill=(255,255,255,230))

def draw_teacup(draw, cx, cy, sz):
    s=sz*S
    draw.ellipse([cx-s*.9,cy+s*.6,cx+s*.9,cy+s*1.0], fill=(*WHITE_OFF,170), outline=(*GOLD,130), width=S)
    draw.polygon([(cx-s*.6,cy),(cx+s*.6,cy),(cx+s*.65,cy+s*.7),(cx-s*.65,cy+s*.7)],
                 fill=(*WHITE_OFF,200), outline=(*GOLD,130))
    pts=[(cx+s*.6+math.cos(math.radians(-30+t/19*210))*s*.3,
          cy+s*.35+math.sin(math.radians(-30+t/19*210))*s*.3) for t in range(20)]
    if len(pts)>=2: draw.line(pts, fill=(*GOLD,170), width=S)

def thematic(draw, suit, cx, cy, sz=9):
    if   suit=="♥": draw_rose(draw,cx,cy,sz)
    elif suit=="♦": draw_clock(draw,cx,cy,sz*1.2)
    elif suit=="♣": draw_mushroom(draw,cx,cy,sz)
    else:           draw_teacup(draw,cx,cy,sz)

def cat_smile(draw, cx, cy, sz):
    s=sz*S
    for ox in [-0.38,0.38]:
        ex,ey=cx+ox*s,cy-s*.2
        draw.ellipse([ex-s*.18,ey-s*.22,ex+s*.18,ey+s*.22], fill=(*GOLD,230))
        draw.ellipse([ex-s*.06,ey-s*.18,ex+s*.06,ey+s*.18], fill=(*DARK_INK,255))
    pts=[(cx-s*.65+t/29*s*1.3, cy+s*.4*math.sin(t/29*math.pi)) for t in range(30)]
    if len(pts)>=2: draw.line(pts, fill=(*RED_BRITE,220), width=max(2,S*2))
    for side in [-1,1]:
        for yo in [-0.05,0.12]:
            draw.line([(cx+side*s*.6,cy+yo*s),(cx+side*s*1.1,cy+(yo-.05)*s)],
                      fill=(*WHITE_OFF,140), width=S)

NPOS={
    "2":[(0.5,0.28),(0.5,0.72)],
    "3":[(0.5,0.25),(0.5,0.5),(0.5,0.75)],
    "4":[(0.3,0.28),(0.7,0.28),(0.3,0.72),(0.7,0.72)],
    "5":[(0.3,0.25),(0.7,0.25),(0.5,0.5),(0.3,0.75),(0.7,0.75)],
    "6":[(0.3,0.24),(0.7,0.24),(0.3,0.5),(0.7,0.5),(0.3,0.76),(0.7,0.76)],
    "7":[(0.3,0.22),(0.7,0.22),(0.5,0.35),(0.3,0.48),(0.7,0.48),(0.3,0.74),(0.7,0.74)],
    "8":[(0.3,0.22),(0.7,0.22),(0.3,0.38),(0.7,0.38),(0.3,0.62),(0.7,0.62),(0.3,0.78),(0.7,0.78)],
    "9":[(0.3,0.21),(0.7,0.21),(0.3,0.36),(0.7,0.36),(0.5,0.5),(0.3,0.64),(0.7,0.64),(0.3,0.79),(0.7,0.79)],
    "10":[(0.3,0.20),(0.7,0.20),(0.3,0.34),(0.7,0.34),(0.3,0.48),(0.7,0.48),
          (0.3,0.62),(0.7,0.62),(0.3,0.76),(0.7,0.76),(0.5,0.27)],
}

def make_card(value, suit):
    img,draw = new_card()
    color = SUIT_COLOR[suit]
    cx,cy = W*S//2, H*S//2
    is_red = color == RED_BRITE

    arabesque(draw, 62); arabesque(draw, H-62)
    for gx,gy in [(22,58),(W-22,58),(22,H-58),(W-22,H-58)]:
        corner_gem(draw, gx*S, gy*S)

    if value=="A":
        r=65*S
        for rad,alpha in [(r,100),(r-10*S,60),(r-20*S,40)]:
            draw.ellipse([cx-rad,cy-rad,cx+rad,cy+rad], outline=(*GOLD,alpha), width=S)
        suit_txt(draw,cx,cy,suit,90*S,color)
        for ox,oy in [(-0.28,-0.28),(0.28,-0.28),(-0.28,0.28),(0.28,0.28)]:
            thematic(draw,suit,cx+ox*W*S,cy+oy*H*S,12)

    elif value in NPOS:
        fs=font(22*S)
        for rx,ry in NPOS[value]:
            pcx,pcy=int(rx*W*S),int(ry*H*S)
            draw.text((pcx+S,pcy+S),suit,font=fs,fill=(*SHADOW,120),anchor="mm")
            if ry>0.52:
                tmp=Image.new("RGBA",(28*S,28*S),(0,0,0,0))
                td=ImageDraw.Draw(tmp,"RGBA")
                td.text((14*S,14*S),suit,font=font(20*S),fill=(*color,230),anchor="mm")
                tmp=tmp.rotate(180)
                img.paste(tmp,(pcx-14*S,pcy-14*S),tmp)
            else:
                draw.text((pcx,pcy),suit,font=fs,fill=(*color,230),anchor="mm")
        thematic(draw,suit,cx,cy,8)

    elif value=="J":
        bc = RED_DEEP if is_red else (30,15,45)
        draw.rectangle([cx-30*S,cy-30*S,cx+30*S,cy+60*S],fill=(*bc,220),outline=(*GOLD,140),width=S)
        draw.ellipse([cx-24*S,cy-82*S,cx+24*S,cy-36*S],fill=(*WHITE_OFF,245),outline=(*DARK_INK,200),width=S)
        draw.chord([cx-26*S,cy-92*S,cx+26*S,cy-58*S],start=190,end=350,fill=(*DARK_INK,220))
        for ox in [-9,9]:
            ex,ey=cx+ox*S,cy-64*S
            draw.ellipse([ex-4*S,ey-4*S,ex+4*S,ey+4*S],fill=(*DARK_INK,255))
            draw.ellipse([ex+S,ey-S,ex+2*S,ey+S],fill=(255,255,255,200))
        draw.arc([cx-6*S,cy-55*S,cx+6*S,cy-49*S],start=0,end=180,fill=(*DARK_INK,180),width=S)
        draw.polygon([(cx-22*S,cy-42*S),(cx+22*S,cy-42*S),(cx+14*S,cy-30*S),(cx,cy-36*S),(cx-14*S,cy-30*S)],fill=(*WHITE_OFF,200))
        suit_txt(draw,cx,cy+10*S,suit,24*S,color)
        draw.polygon([(cx-18*S,cy-82*S),(cx+18*S,cy-82*S),(cx+12*S,cy-102*S),(cx-12*S,cy-102*S)],fill=(*DARK_INK,240))
        draw.rectangle([cx-22*S,cy-84*S,cx+22*S,cy-78*S],fill=(*DARK_INK,220),outline=(*GOLD,180),width=S)
        cat_smile(draw,cx,cy+80*S,18)

    elif value=="Q":
        dc = RED_DEEP if is_red else (30,10,50)
        draw.polygon([(cx-40*S,cy+80*S),(cx+40*S,cy+80*S),(cx+32*S,cy-20*S),(cx-32*S,cy-20*S)],fill=(*dc,230),outline=(*GOLD,140),width=S)
        draw.ellipse([cx-25*S,cy-88*S,cx+25*S,cy-38*S],fill=(*WHITE_OFF,248),outline=(*DARK_INK,200),width=S)
        draw.chord([cx-27*S,cy-100*S,cx+27*S,cy-64*S],start=190,end=350,fill=(*DARK_INK,230))
        draw.rectangle([cx-26*S,cy-95*S,cx-22*S,cy-62*S],fill=(*DARK_INK,220))
        draw.rectangle([cx+22*S,cy-95*S,cx+26*S,cy-62*S],fill=(*DARK_INK,220))
        for ox in [-9,9]:
            ex,ey=cx+ox*S,cy-70*S
            draw.ellipse([ex-5*S,ey-5*S,ex+5*S,ey+5*S],fill=(*DARK_INK,255))
            draw.ellipse([ex+S,ey-S,ex+2*S,ey+S],fill=(255,255,255,200))
        draw.arc([cx-8*S,cy-57*S,cx+8*S,cy-51*S],start=0,end=180,fill=(*RED_BRITE,220),width=max(1,S))
        pts_c=[(cx-25*S,cy-98*S),(cx-25*S,cy-112*S),(cx-13*S,cy-104*S),(cx,cy-118*S),(cx+13*S,cy-104*S),(cx+25*S,cy-112*S),(cx+25*S,cy-98*S)]
        draw.polygon(pts_c,fill=(*GOLD,240),outline=(*GOLD_LT,200),width=S)
        for gx,gy in [(cx-13*S,cy-104*S),(cx,cy-118*S),(cx+13*S,cy-104*S)]:
            draw.ellipse([gx-3*S,gy-3*S,gx+3*S,gy+3*S],fill=(*RED_BRITE,255))
        draw.arc([cx-20*S,cy-46*S,cx+20*S,cy-34*S],start=0,end=180,fill=(*GOLD,200),width=max(1,S*2))
        suit_txt(draw,cx,cy+30*S,suit,26*S,color if is_red else WHITE_OFF)
        draw_rose(draw,cx-28*S,cy+62*S,9); draw_rose(draw,cx+28*S,cy+62*S,9)

    elif value=="K":
        cc = RED_DEEP if is_red else (20,8,40)
        draw.polygon([(cx-44*S,cy+80*S),(cx+44*S,cy+80*S),(cx+35*S,cy-25*S),(cx-35*S,cy-25*S)],fill=(*cc,230),outline=(*GOLD,140),width=S)
        draw.ellipse([cx-24*S,cy-88*S,cx+24*S,cy-42*S],fill=(*WHITE_OFF,248),outline=(*DARK_INK,200),width=S)
        draw.chord([cx-26*S,cy-98*S,cx+26*S,cy-68*S],start=190,end=350,fill=(*DARK_INK,220))
        draw.polygon([(cx-18*S,cy-62*S),(cx+18*S,cy-62*S),(cx+14*S,cy-44*S),(cx,cy-40*S),(cx-14*S,cy-44*S)],fill=(*DARK_INK,170))
        for ox in [-9,9]:
            ex,ey=cx+ox*S,cy-74*S
            draw.ellipse([ex-5*S,ey-5*S,ex+5*S,ey+5*S],fill=(*DARK_INK,255))
            draw.ellipse([ex+S,ey-S,ex+2*S,ey+S],fill=(255,255,255,200))
        draw.line([(cx-7*S,cy-63*S),(cx+7*S,cy-63*S)],fill=(*DARK_INK,200),width=max(1,S))
        pts_c=[(cx-27*S,cy-98*S),(cx-27*S,cy-116*S),(cx-15*S,cy-106*S),(cx-6*S,cy-124*S),(cx,cy-120*S),(cx+6*S,cy-124*S),(cx+15*S,cy-106*S),(cx+27*S,cy-116*S),(cx+27*S,cy-98*S)]
        draw.polygon(pts_c,fill=(*GOLD,245),outline=(*GOLD_LT,200),width=S)
        draw.rectangle([cx-29*S,cy-100*S,cx+29*S,cy-92*S],fill=(*GOLD,220),outline=(*GOLD_LT,180),width=S)
        for gx,gy in [(cx,cy-120*S),(cx-15*S,cy-106*S),(cx+15*S,cy-106*S)]:
            draw.ellipse([gx-4*S,gy-4*S,gx+4*S,gy+4*S],fill=(*RED_BRITE,255))
        draw.line([(cx+36*S,cy-22*S),(cx+44*S,cy+70*S)],fill=(*GOLD,230),width=max(2,S*2))
        draw.ellipse([cx+32*S,cy-30*S,cx+40*S,cy-22*S],fill=(*GOLD,220))
        draw.ellipse([cx+34*S,cy-32*S,cx+38*S,cy-28*S],fill=(*RED_BRITE,255))
        draw.line([(cx-36*S,cy-22*S),(cx-42*S,cy+68*S)],fill=(*WHITE_OFF,200),width=max(2,S*2))
        draw.line([(cx-48*S,cy-8*S),(cx-28*S,cy+2*S)],fill=(*WHITE_OFF,170),width=max(1,S))
        suit_txt(draw,cx,cy+22*S,suit,24*S,color if is_red else WHITE_OFF)

    corner_labels(draw, value, suit)

    out=img.resize((W,H),Image.LANCZOS)
    final=Image.new("RGB",(W,H),BG_CARD)
    final.paste(out,mask=out.split()[3])
    return final

def card_filename(v,s): return f"{VALUE_NAMES[v]}_{SUIT_NAMES[s]}.png"
def get_card_path(v,s,d="cards/generated"): return Path(d)/card_filename(v,s)

def generate_all_cards(output_dir="cards/generated", verbose=True):
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    total=0
    for s in SUITS:
        for v in VALUES:
            fname=card_filename(v,s); path=out/fname
            try:
                make_card(v,s).save(str(path),"PNG")
                total+=1
                if verbose: print(f"  ✓ {fname}")
            except Exception as e:
                if verbose: print(f"  ✗ {v}{s}: {e}")
    if verbose: print(f"\n  {total}/52 cartas em '{output_dir}'")
    return total

if __name__=="__main__":
    out = sys.argv[1] if len(sys.argv)>1 else "cards/generated"
    print(f"\n🃏 Gerando 52 cartas → {out}\n")
    generate_all_cards(output_dir=out)
