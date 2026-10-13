# Контраст WCAG після квантування в RGB565 (так їх покаже дисплей)
def q(c):
    r,g,b=(c>>16)&255,(c>>8)&255,c&255
    r5,g6,b5=r>>3,g>>2,b>>3
    return ((r5<<3)|(r5>>2),(g6<<2)|(g6>>4),(b5<<3)|(b5>>2))
def lum(c):
    def f(v):
        v/=255; return v/12.92 if v<=0.03928 else ((v+0.055)/1.055)**2.4
    r,g,b=q(c); return 0.2126*f(r)+0.7152*f(g)+0.0722*f(b)
def cr(a,b):
    la,lb=lum(a),lum(b); 
    if la<lb: la,lb=lb,la
    return (la+0.05)/(lb+0.05)
DAY=dict(BG=0xFFFFFF,FG=0x000000,DEC=0x1C1C1C,SPL=0x0A2F44,NOTIF=0x0A3550,WARN=0x804000,ERR=0xC80000,MNAME_FG=0xFFFFFF,MNAME_BG=0x0A4A6E,SEL=0x0A4A6E,OPT=0x0A4A6E,HDR_BG=0xD2DCE3,HDR_FG=0x000000,RSSI=0x006400,S9P=0xC80000,CHN=0x0A4A6E,CON=0x8C0A00,ZONE=0x3F4F5A,TX=0xC80000,POLAR=0x404040,SAT=0x006400,GPS=0x000078)
NIGHT=dict(BG=0x05080C,FG=0xE8EEF2,DEC=0x6F8493,SPL=0x9FD3F0,NOTIF=0x9FD3F0,WARN=0xFFCC55,ERR=0xFF7676,MNAME_FG=0xFFFFFF,MNAME_BG=0x1B4F72,SEL=0xD8A93F,OPT=0xE3B454,HDR_BG=0x05080C,HDR_FG=0xA9D6F0,RSSI=0x33FF33,S9P=0xFF6A2A,CHN=0x7FD8B5,CON=0xFFCC55,ZONE=0xC5CED5,TX=0xFF7676,POLAR=0x86B9D6,SAT=0x7FD8B5,GPS=0x93B4FF)
for n,P in (('DAY',DAY),('NIGHT',NIGHT)):
    pairs=[('текст/тло',P['FG'],P['BG']),('декорація/тло',P['DEC'],P['BG']),('заставка',P['SPL'],P['BG']),('сповіщення',P['NOTIF'],P['BG']),('попередження',P['WARN'],P['BG']),('помилка',P['ERR'],P['BG']),
    ('заголовок меню',P['MNAME_FG'],P['MNAME_BG']),('виділений пункт (текст=BG)',P['BG'],P['SEL']),('пункт меню/тло',P['FG'] if n=='DAY' else 0xA9D6F0,P['BG']),('значення налашт.',P['OPT'],P['BG']),('шапка',P['HDR_FG'],P['HDR_BG']),
    ('RSSI/шапка',P['RSSI'],P['HDR_BG']),('S9+/тло',P['S9P'],P['BG']),('назва каналу',P['CHN'],P['BG']),('контакт',P['CON'],P['BG']),('зона',P['ZONE'],P['BG']),('TX',P['TX'],P['BG']),('полярна',P['POLAR'],P['BG']),('супутник',P['SAT'],P['BG']),('GPS',P['GPS'],P['BG'])]
    print(n)
    for name,a,b in pairs: print('  %-28s %5.2f %s'%(name,cr(a,b),'' if cr(a,b)>=4.5 else ('<-- <4.5' if cr(a,b)>=3 else '<-- <3!')))
