from pathlib import Path
from xml.sax.saxutils import escape
import base64
import json
import math
import shutil

from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent
OUT = ROOT
ASSETS = OUT / 'dressme-poster-assets'
OUT.mkdir(parents=True, exist_ok=True)
ASSETS.mkdir(exist_ok=True)
GENERATED = ASSETS / 'wardrobe-photography.png'
ATLAS = ASSETS / 'wardrobe-photography.png'
if GENERATED.resolve() != ATLAS.resolve():
    shutil.copy2(GENERATED, ATLAS)

FONTS = Path(r'C:\Windows\Fonts')
for name, file in [('Sans', 'calibri.ttf'), ('Bold', 'calibrib.ttf'),
                   ('Light', 'calibril.ttf'), ('Serif', 'BOD_R.TTF'),
                   ('Italic', 'GARAIT.TTF')]:
    pdfmetrics.registerFont(TTFont(name, str(FONTS / file)))

W, H = 594 / 25.4 * 72, 841 / 25.4 * 72
BG = '#F7F2EA'
PAPER = '#FCFAF6'
INK = '#292425'
MUTED = '#6E6360'
BURG = '#713E4C'
BLUSH = '#EAD6D5'
LINE = '#D8C9BF'
SAGE = '#4F695C'
AMBER = '#946B3E'
PDF = OUT / 'DressMe_A1_Academic_Poster.pdf'
SVG = OUT / 'DressMe_A1_Editable_Poster.svg'


class Art:
    def __init__(self):
        self.c = canvas.Canvas(str(PDF), pagesize=(W, H), pageCompression=1)
        self.c.setTitle('DressMe - Your Personal AI Fashion Assistant | A1 Academic Poster')
        self.c.setAuthor('DressMe | Advanced Data Science Project')
        self.c.setSubject('Academic concept poster. Interface examples are illustrative; Virtual Try-On is an optional future extension.')
        self.s = []
        self.defs = []
        self.clips = 0
        self.text_log = []
        data = base64.b64encode(ATLAS.read_bytes()).decode()
        self.defs.append(f'<image id="wardrobe-atlas" width="1024" height="1536" href="data:image/png;base64,{data}"/>')

    def color(self, fill, stroke, sw=1):
        if fill:
            self.c.setFillColor(HexColor(fill))
        if stroke:
            self.c.setStrokeColor(HexColor(stroke))
        self.c.setLineWidth(sw)

    def rect(self, x, y, w, h, fill=None, stroke=None, r=0, sw=1):
        self.color(fill, stroke, sw)
        self.c.roundRect(x, H-y-h, w, h, r, fill=int(bool(fill)), stroke=int(bool(stroke)))
        self.s.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill or "none"}" stroke="{stroke or "none"}" stroke-width="{sw}"/>')

    def ellipse(self, x, y, w, h, fill=None, stroke=None, sw=1):
        self.color(fill, stroke, sw)
        self.c.ellipse(x, H-y-h, x+w, H-y, fill=int(bool(fill)), stroke=int(bool(stroke)))
        self.s.append(f'<ellipse cx="{x+w/2}" cy="{y+h/2}" rx="{w/2}" ry="{h/2}" fill="{fill or "none"}" stroke="{stroke or "none"}" stroke-width="{sw}"/>')

    def line(self, x1, y1, x2, y2, color=LINE, sw=1, dash=None):
        self.color(None, color, sw)
        self.c.setLineCap(1)
        self.c.setDash(dash or [])
        self.c.line(x1, H-y1, x2, H-y2)
        self.c.setDash([])
        ds = f' stroke-dasharray="{",".join(map(str,dash))}"' if dash else ''
        self.s.append(f'<path d="M {x1} {y1} L {x2} {y2}" fill="none" stroke="{color}" stroke-width="{sw}" stroke-linecap="round"{ds}/>')

    def path(self, commands, fill=None, stroke=BURG, sw=1.4):
        self.color(fill, stroke, sw)
        self.c.setLineCap(1)
        self.c.setLineJoin(1)
        p = self.c.beginPath()
        for cmd in commands:
            if cmd[0] == 'M': p.moveTo(cmd[1], H-cmd[2])
            elif cmd[0] == 'L': p.lineTo(cmd[1], H-cmd[2])
            elif cmd[0] == 'C': p.curveTo(cmd[1], H-cmd[2], cmd[3], H-cmd[4], cmd[5], H-cmd[6])
            elif cmd[0] == 'Z': p.close()
        self.c.drawPath(p, fill=int(bool(fill)), stroke=int(bool(stroke)))
        d = ' '.join(' '.join(map(str, cmd)) for cmd in commands)
        self.s.append(f'<path d="{d}" fill="{fill or "none"}" stroke="{stroke or "none"}" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"/>')

    def text(self, text, x, y, size=22, font='Sans', color=INK, align='left', tracking=0):
        width = pdfmetrics.stringWidth(text, font, size) + max(0, len(text)-1)*tracking
        start = x if align == 'left' else x-width/2 if align == 'center' else x-width
        assert start >= 35 and start+width <= W-35, (text, start, width)
        assert 35 <= y <= H-35, (text, y)
        self.text_log.append({'text':text, 'x':round(start,2), 'y':y, 'width':round(width,2), 'font_size':size})
        self.c.setFillColor(HexColor(color))
        t = self.c.beginText(start, H-y-size*.8)
        t.setFont(font, size)
        t.setCharSpace(tracking)
        t.textOut(text)
        self.c.drawText(t)
        family = {'Sans':'Calibri', 'Bold':'Calibri', 'Light':'Calibri Light', 'Serif':'Bodoni MT', 'Italic':'Garamond'}[font]
        extra = ' font-weight="700"' if font == 'Bold' else ' font-style="italic"' if font == 'Italic' else ''
        self.s.append(f'<text x="{start}" y="{y+size*.8}" font-family="{family}" font-size="{size}" fill="{color}" letter-spacing="{tracking}"{extra}>{escape(text)}</text>')
        return width

    def wrap(self, text, x, y, width, size=22, leading=None, font='Sans', color=INK, max_lines=None):
        leading = leading or size*1.24
        words = text.split()
        lines = []
        line = ''
        for word in words:
            test = f'{line} {word}'.strip()
            if pdfmetrics.stringWidth(test, font, size) <= width:
                line = test
            else:
                lines.append(line)
                line = word
        if line: lines.append(line)
        if max_lines: assert len(lines) <= max_lines, (text, len(lines), max_lines)
        for i, line in enumerate(lines): self.text(line, x, y+i*leading, size, font, color)
        return len(lines)*leading

    def tile(self, index, x, y, w, h=None, r=0):
        h = h or w
        self.rect(x,y,w,h,'#FBF5EC',None,r)
        # Contain the full garment in the card, preserving its square photo cell.
        d=min(w,h)
        cx=x+(w-d)/2
        cy=y+(h-d)/2
        self.clips += 1
        cid = f'crop-{self.clips}'
        # Clip to an atlas cell; images remain original, embedded photo assets.
        p = self.c.beginPath()
        p.roundRect(cx, H-cy-d, d, d, min(r,d/8))
        self.c.saveState()
        self.c.clipPath(p, stroke=0, fill=0)
        s = d/512
        ix = cx-(index%2)*512*s
        iy = cy-(index//2)*512*s
        self.c.drawImage(str(ATLAS), ix, H-iy-1536*s, width=1024*s, height=1536*s, mask='auto')
        self.c.restoreState()
        self.defs.append(f'<clipPath id="{cid}"><rect x="{cx}" y="{cy}" width="{d}" height="{d}" rx="{min(r,d/8)}"/></clipPath>')
        self.s.append(f'<g clip-path="url(#{cid})"><use href="#wardrobe-atlas" transform="translate({ix} {iy}) scale({s})"/></g>')

    def save(self):
        self.c.showPage()
        self.c.save()
        SVG.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="594mm" height="841mm" viewBox="0 0 {W} {H}"><title>DressMe A1 Academic Poster</title><desc>Editable vector design with live text. Uses Calibri, Bodoni MT and Garamond fonts. All mockup data is illustrative.</desc><defs>{"".join(self.defs)}</defs>{"".join(self.s)}</svg>', encoding='utf-8')
        (OUT/'dressme-poster-assets'/'text-layout.json').write_text(json.dumps(self.text_log, indent=2), encoding='utf-8')


a = Art()


def icon(kind, x, y, size=28, color=BURG, sw=1.6):
    k = size/24
    def path(cmds, fill=None):
        a.path([tuple([c[0]] + [v*k+(x if j%2 == 0 else y) for j,v in enumerate(c[1:])]) for c in cmds], fill, color, sw)
    def line(x1,y1,x2,y2): a.line(x+x1*k,y+y1*k,x+x2*k,y+y2*k,color,sw)
    def circle(cx,cy,r): a.ellipse(x+(cx-r)*k,y+(cy-r)*k,2*r*k,2*r*k,None,color,sw)
    if kind in ['hanger', 'wardrobe']:
        path([('M',9,6),('C',9,1,16,1,16,6),('C',16,8,12,8,12,11),('L',2,18),('L',22,18),('L',12,11)])
    elif kind in ['scan','camera']:
        for xx,yy,dx,dy in [(2,2,6,6),(22,2,-6,6),(2,22,6,-6),(22,22,-6,-6)]:
            path([('M',xx,yy+dy),('L',xx,yy),('L',xx+dx,yy)])
        if kind=='scan':
            path([('M',8,9),('L',10,7),('L',14,7),('L',17,10),('L',15,12),('L',15,17),('L',9,17),('L',9,12),('L',6,12),('Z',)])
        else: a.rect(x+6*k,y+7*k,12*k,10*k,None,color,2*k,sw); circle(12,12,2.5)
    elif kind in ['user','style']:
        circle(12,6.5,4)
        path([('M',3,22),('C',3,11,21,11,21,22)])
        if kind=='style': line(19,3,23,3); line(21,1,21,5)
    elif kind=='outfit':
        path([('M',8,3),('C',10,6,14,6,16,3),('L',23,8),('L',19,13),('L',16,11),('L',16,22),('L',8,22),('L',8,11),('L',5,13),('L',1,8),('Z',)])
    elif kind in ['bag','wallet']:
        a.rect(x+3*k,y+7*k,18*k,15*k,None,color,2*k,sw)
        if kind=='bag': path([('M',8,8),('L',8,5),('C',8,0,16,0,16,5),('L',16,8)])
        else: line(15,12,23,12); line(23,12,23,17); line(23,17,15,17); line(15,17,15,12); circle(18,14.5,.4)
    elif kind in ['grid','optimize']:
        for xx,yy in [(2,2),(14,2),(2,14),(14,14)]: a.rect(x+xx*k,y+yy*k,8*k,8*k,None,color,1.3*k,sw)
    elif kind in ['chat','explain']:
        path([('M',3,3),('L',21,3),('L',21,17),('L',10,17),('L',4,22),('L',4,17),('L',3,17),('Z',)])
        line(7,8,17,8); line(7,12,14,12)
    elif kind in ['network','ai']:
        for p,q in [((4,5),(12,11)),((4,19),(12,11)),((12,11),(20,4)),((12,11),(20,20)),((12,11),(20,12))]: line(*p,*q)
        for cx,cy in [(4,5),(4,19),(12,11),(20,4),(20,12),(20,20)]:
            a.ellipse(x+(cx-2)*k,y+(cy-2)*k,4*k,4*k,PAPER,color,sw)
    elif kind in ['spark','generative']:
        path([('M',12,1),('L',15,9),('L',23,12),('L',15,15),('L',12,23),('L',9,15),('L',1,12),('L',9,9),('Z',)])
    elif kind=='layers':
        for off in [0,5,10]: path([('M',2,7+off),('L',12,2+off),('L',22,7+off),('L',12,12+off),('Z',)])
    elif kind=='sliders':
        for yy,cx in [(4,8),(12,17),(20,6)]: line(2,yy,22,yy); a.ellipse(x+(cx-2)*k,y+(yy-2)*k,4*k,4*k,PAPER,color,sw)
    elif kind=='leaf':
        path([('M',4,21),('C',1,5,13,1,22,2),('C',21,18,14,23,4,21),('M',4,21),('L',17,7)])
    elif kind=='repeat':
        path([('M',3,8),('C',6,1,18,1,21,8),('L',21,3),('M',21,8),('L',16,8),('M',21,16),('C',18,23,6,23,3,16),('L',3,21),('M',3,16),('L',8,16)])
    elif kind=='sun':
        circle(12,12,4)
        for angle in range(0,360,45):
            c,s=math.cos(math.radians(angle)),math.sin(math.radians(angle));line(12+c*7,12+s*7,12+c*10,12+s*10)
    elif kind=='heart':
        path([('M',12,21),('C',-7,10,3,-1,12,7),('C',21,-1,31,10,12,21),('Z',)])
    elif kind=='check': path([('M',4,12),('L',10,18),('L',21,5)])
    elif kind=='warning':
        path([('M',12,2),('L',23,22),('L',1,22),('Z',)]);line(12,8,12,14);circle(12,18,.5)
    elif kind=='cross': line(5,5,19,19);line(19,5,5,19)


def label(text, x, y, color=BURG): a.text(text, x, y, 15.5, 'Bold', color, tracking=1.7)


def feature(n, title, body, kind, x, y):
    a.rect(x,y,494,151,PAPER,LINE,13,.8)
    a.text(f'{n:02}',x+22,y+20,18,'Bold',BURG)
    icon(kind,x+61,y+18,26)
    a.text(title,x+102,y+21,22.5,'Bold')
    a.wrap(body,x+23,y+63,448,21.5,26,color=MUTED,max_lines=3)


def phone(x,y,w,h,shopping=False):
    a.rect(x+9,y+10,w,h,'#D5C3BB',None,35)
    a.rect(x,y,w,h,INK,'#171515',35,1.6)
    a.rect(x+7,y+7,w-14,h-14,PAPER,None,29)
    a.rect(x+w/2-36,y+11,72,12,INK,None,6)
    a.text('9:41',x+22,y+16,10,'Bold')
    for i in range(3): a.rect(x+w-42+i*4,y+19-i*2,2.5,4+i*2,INK,None,.4)
    a.rect(x+w-25,y+17,12,7,None,INK,1,.7)
    if shopping:
        a.text('DRESSME',x+21,y+44,15,'Serif',tracking=1.4)
        a.text('Should I buy this?',x+21,y+70,18,'Bold')
        a.tile(3,x+16,y+98,w-32,100,11)
        a.rect(x+18,y+204,w-36,51,'#EAF0EB',None,7)
        a.text('87%',x+w/2,y+207,28,'Bold',SAGE,'center')
        a.text('wardrobe compatibility',x+w/2,y+242,10.4,'Sans',SAGE,'center')
        a.rect(x+26,y+h-15,w-52,3,INK,None,1.5)
    else:
        a.text('DRESSME',x+20,y+49,23,'Serif',tracking=1.2)
        a.text('Your digital wardrobe',x+20,y+81,20.5,'Bold')
        chips=[('All',43),('Tops',52),('Bottoms',69),('More',48)]
        xx=x+19
        for i,(t,cw) in enumerate(chips):
            a.rect(xx,y+116,cw,24,BURG if i==0 else '#EEE7DF',None,12)
            a.text(t,xx+cw/2,y+122,12.5,'Bold' if i==0 else 'Sans',PAPER if i==0 else MUTED,'center')
            xx+=cw+6
        items=[('Outerwear','Taupe blazer'),('Knitwear','Ivory sweater'),('Bottoms','Burgundy trousers'),('Tops','Linen shirt'),('Shoes','Everyday sneakers'),('Accessories','Leather bag')]
        tw=(w-49)/2
        for i,(cat,item) in enumerate(items):
            xx=x+18+(i%2)*(tw+13); yy=y+155+(i//2)*108
            a.tile(i,xx,yy,tw,80,8)
            a.text(cat,xx,yy+84,10.8,'Bold',BURG)
            a.text(item,xx,yy+96,10.3,'Sans',MUTED)
        a.line(x+18,y+h-40,x+w-18,y+h-40,LINE,.7)
        icon('hanger',x+39,y+h-31,16)
        icon('spark',x+w/2-8,y+h-31,16,MUTED)
        icon('user',x+w-54,y+h-31,16,MUTED)
        a.rect(x+w/2-38,y+h-10,76,3,INK,None,1.5)


# PAGE: a restrained ivory field, magazine-style masthead and fine rules.
a.rect(0,0,W,H,BG)
a.rect(0,0,17,H,BURG)
label('ADVANCED DATA SCIENCE  /  ACADEMIC PROJECT',74,60)
a.text('FASHION  +  INTELLIGENCE',W-74,60,15.5,'Bold',MUTED,'right',1.7)
a.line(74,91,W-74,91,LINE,.8)
a.text('DRESSME',70,111,166,'Serif',INK,tracking=5)
a.text('Your Personal AI Fashion Assistant',78,279,39,'Light')
a.wrap('An intelligent fashion ecosystem that transforms your wardrobe into a personalized digital experience using Artificial Intelligence, Computer Vision, and Recommendation Systems.',79,339,1460,24,30,color=MUTED,max_lines=2)
a.text('Your Wardrobe. Your Style. Your Intelligence.',79,410,26,'Italic',BURG)

label('01  /  PROJECT VISION',77,461)
a.text('Digitize your wardrobe. Understand your style. Discover outfits. Make smarter purchases.',77,488,23.5,'Sans')

# Six feature cards frame the main wardrobe interface.
feature(1,'Smart Digital Wardrobe','Upload clothing images and automatically organize your personal digital wardrobe.','hanger',76,538)
feature(2,'AI Clothing Recognition','Identify clothing categories, colors, styles and visual characteristics with Computer Vision.','scan',76,704)
feature(3,'Personal Style Profiling','Learn individual preferences from clothing characteristics and user interactions.','style',76,870)
feature(4,'Intelligent Outfit Recommendation','Generate personalized outfit combinations using pieces already in your wardrobe.','outfit',1113,538)
feature(5,'Smart Shopping Assistant','Evaluate potential purchases against your style and the clothes you already own.','bag',1113,704)
feature(6,'Wardrobe Optimization','Find missing pieces, detect redundant items and improve wardrobe diversity.','grid',1113,870)

# Central smartphone with a subtle halo and feature connections.
a.ellipse(612,548,452,455,'#EDE0DA')
a.ellipse(631,570,413,413,None,'#DBC3C0',1)
a.ellipse(659,596,360,360,None,'#DBC3C0',.65)
for yy in [614,779,945]:
    a.line(581,yy,679,yy,'#C8A9AB',1,[3,5])
    a.line(996,yy,1101,yy,'#C8A9AB',1,[3,5])
    for xx in [582,1098]: a.ellipse(xx-3,yy-3,6,6,BURG)
phone(691,521,300,519)
a.text('ILLUSTRATIVE WARDROBE INTERFACE',841,1056,12.5,'Bold',MUTED,'center',.8)

a.rect(76,1090,1531,91,'#EAD9D7',None,13)
a.text('07',98,1112,20,'Bold',BURG)
icon('explain',145,1110,32)
a.text('Explainable Fashion AI',199,1108,25,'Bold')
a.text('Clear explanations and compatibility scores reveal why each recommendation fits your wardrobe.',199,1144,21.5,'Sans',MUTED)

# Horizontal machine learning pipeline.
label('02  /  HOW DOES DRESSME WORK?',77,1222)
steps=[('USER INPUT','Clothing images +\nuser interactions','camera'),('COMPUTER VISION','Clothing recognition +\nfeature extraction','scan'),('PERSONALIZATION','Style profiling +\npreference modeling','user'),('RECOMMENDATION ENGINE','Outfit generation, matching +\nwardrobe optimization','network'),('INTELLIGENT FASHION ADVICE','Personalized outfits +\nshopping decisions','spark')]
stepw=285
for i,(title,body,kind) in enumerate(steps):
    xx=76+i*311.5
    a.rect(xx,1261,stepw,157,PAPER,LINE,11,.8)
    icon(kind,xx+18,1278,29)
    a.text(f'{i+1:02}',xx+stepw-20,1280,16,'Bold',BURG,'right')
    a.text(title,xx+18,1323,16.7 if len(title)>22 else 18,'Bold')
    for j,line in enumerate(body.split('\n')): a.text(line,xx+18,1356+j*23,18.8,'Sans',MUTED)
    if i<4:
        a.line(xx+stepw+4,1341,xx+stepw+20,1341,BURG,1.6)
        a.path([('M',xx+stepw+15,1336),('L',xx+stepw+21,1341),('L',xx+stepw+15,1346)],None,BURG,1.6)

# Shopping highlight, with three clearly differentiated possible outcomes.
a.rect(76,1461,1008,425,'#EEE1DC',None,16)
label('03  /  AN INNOVATIVE FEATURE',101,1485)
a.text('Should I buy this?',102,1514,34,'Serif')
phone(104,1570,180,282,True)

outcomes=[('check',SAGE,'RECOMMENDED PURCHASE','This item matches your style and combines with several pieces in your wardrobe.'),('warning',AMBER,'THINK TWICE','You already own similar items. This purchase adds limited value to your wardrobe.'),('cross',BURG,'NOT RECOMMENDED','This item has low compatibility with your current wardrobe.')]
for i,(kind,col,title,body) in enumerate(outcomes):
    yy=1578+i*89
    a.ellipse(321,yy-3,31,31,'#F9F5EF')
    icon(kind,326,yy+2,21,col,1.8)
    a.text(title,367,yy,20.5,'Bold',col)
    a.wrap(body,367,yy+30,675,20.8,24.5,color=MUTED,max_lines=2)
    if i<2:a.line(366,yy+77,1055,yy+77,'#D5C1B9',.7)
a.text('Illustrative UI example. The score is not a measured project result.',313,1850,16.2,'Italic',MUTED)

# Concise technology matrix.
label('AI METHODS',1120,1485)
a.text('Powered by Data Science',1118,1518,27,'Serif')
a.text('& Artificial Intelligence',1118,1551,27,'Serif')
tech=[('Computer Vision','scan'),('Convolutional Neural\nNetworks (CNN)','layers'),('Deep Learning','network'),('Recommendation\nSystems','outfit'),('Collaborative\nFiltering','user'),('Preference\nModeling','sliders'),('Multimodal AI','layers'),('Explainable AI','chat'),('Generative AI','spark')]
for i,(title,kind) in enumerate(tech):
    row,col=divmod(i,2)
    xx=1120+col*249; yy=1611+row*51
    icon(kind,xx,yy+2,23)
    for j,line in enumerate(title.split('\n')):a.text(line,xx+36,yy+j*20,18.8,'Sans',INK)

# Impact and an explicitly optional future perspective.
label('04  /  INNOVATION & IMPACT',77,1933)
a.text('Beyond Fashion:',76,1968,34,'Serif')
a.text('Smarter & More Sustainable Choices',77,2006,30,'Light')
impact=[('Personalized fashion experiences','style'),('Fewer unnecessary purchases','bag'),('Better wardrobe utilization','hanger'),('Budget-conscious shopping','wallet'),('More sustainable consumption habits','leaf'),('Tunisian fashion preferences & seasons','sun')]
for i,(title,kind) in enumerate(impact):
    row,col=divmod(i,2)
    xx=79+col*520; yy=2072+row*45
    icon(kind,xx,yy-1,25)
    a.text(title,xx+39,yy+1,21,'Sans',INK)

a.rect(1150,1933,457,284,PAPER,LINE,15,.8)
label('OPTIONAL EXTENSION',1173,1954)
a.text('Virtual Try-On',1173,1986,29,'Serif')
# A small fitting interface: a user silhouette with outfit overlay and scan corners.
a.rect(1175,2032,115,146,'#EEE4DF',None,12)
a.ellipse(1218,2046,25,25,'#C3ACA3')
a.path([('M',1210,2077),('L',1252,2077),('L',1262,2128),('L',1245,2131),('L',1241,2172),('L',1229,2172),('L',1226,2131),('L',1213,2172),('L',1201,2172),('L',1210,2127),('L',1199,2125),('Z',)],'#AF8D8D',None)
a.path([('M',1214,2077),('L',1205,2118),('L',1256,2118),('L',1248,2077)],None,BURG,1.2)
for xx,yy,dx,dy in [(1185,2042,9,9),(1280,2042,-9,9),(1185,2168,9,-9),(1280,2168,-9,-9)]:
    a.path([('M',xx,yy+dy),('L',xx,yy),('L',xx+dx,yy)],None,BURG,1)
a.wrap('Visualize an outfit through a virtual fitting interface.',1310,2040,268,21,26,color=MUTED,max_lines=4)
a.text('Future perspective',1310,2148,18,'Bold',BURG)
a.text('Not implemented',1310,2174,17.5,'Sans',MUTED)

# Academic footer, with intentional writable space for institution and team.
a.line(76,2253,1607,2253,LINE,1)
a.text('ADVANCED DATA SCIENCE PROJECT',77,2276,18,'Bold',BURG,tracking=1.2)
a.text('Academic project - Data Science & Artificial Intelligence',77,2308,18,'Sans',MUTED)
a.text('DressMe | Your Personal AI Fashion Assistant',77,2337,18,'Serif',INK)
a.rect(837,2273,184,84,None,LINE,5,.8)
a.text('UNIVERSITY LOGO',929,2310,13.2,'Sans',MUTED,'center',.8)
label('TEAM MEMBERS',1061,2276,MUTED)
a.line(1061,2314,1607,2314,LINE,.8)
label('ACADEMIC SUPERVISORS',1061,2327,MUTED)
a.line(1061,2350,1607,2350,LINE,.8)

a.save()
reader=PdfReader(str(PDF))
assert len(reader.pages)==1
page=reader.pages[0]
assert abs(float(page.mediabox.width)-W)<.01
assert abs(float(page.mediabox.height)-H)<.01
text=page.extract_text()
required=['DRESSME','Smart Digital Wardrobe','AI Clothing Recognition','Personal Style Profiling','Intelligent Outfit Recommendation','Smart Shopping Assistant','Wardrobe Optimization','Explainable Fashion AI','87%','not a measured project result','Not implemented','Tunisian','Generative AI','Convolutional Neural','TEAM MEMBERS','ACADEMIC SUPERVISORS']
for item in required: assert item.lower() in text.lower(),item
(ASSETS/'poster-text.txt').write_text(text,encoding='utf-8')
print(json.dumps({'pdf':str(PDF),'svg':str(SVG),'page_mm':[594,841],'pages':1,'text_objects':len(a.text_log),'pdf_bytes':PDF.stat().st_size},indent=2))
