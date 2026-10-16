# -*- coding: utf-8 -*-
import sys, re
from seed_lib import *
import gen_aprs_icons24 as G
import icons_prim1 as P
import icons_alt as A

def dg(fn):
    return lambda: fn()

# --- первинна таблиця '/'
PRIM = {
 '!': G.police, '#': G.digi, '$': G.phone, '%': P.dxcluster, '&': G.gateway, "'": P.smallplane, '(': P.satellite, ')': P.wheelchair,
 '*': P.snowmobile, '+': P.redcross, ',': P.scout, '-': G.house, '.': P.xmark, '/': P.reddot,
 ':': P.fire, ';': A.camp, '<': G.moto, '=': P.locomotive, '>': G.car, '?': P.server, '@': P.storm,
 'A': P.aid, 'B': P.bbs, 'C': P.canoe, 'E': P.eyeball, 'F': P.tractor, 'G': P.gridsq, 'H': P.hotel, 'I': G.tcpip,
 'K': P.school, 'L': P.pcuser, 'M': P.mac, 'N': P.nts, 'O': G.balloon, 'P': A.policecar, 'R': P.rv, 'S': P.shuttle,
 'T': P.sstv, 'U': G.bus, 'V': P.atv, 'W': P.wxsvc, 'X': P.helicopter, 'Y': G.sail, 'Z': P.winaprs,
 '[': G.human, '\\': P.dfstation, ']': P.mail, '^': G.plane, '_': G.wx, '`': P.dish,
 'a': P.ambulance, 'b': G.bike, 'c': P.icp, 'd': P.firedept, 'e': P.horse, 'f': P.firetruck, 'g': P.glider, 'h': P.hospital,
 'i': P.iota, 'j': G.jeep, 'k': G.truck, 'l': P.laptop, 'm': P.mice, 'n': P.node, 'o': P.eoc, 'p': P.dog, 'q': P.gridsq2,
 'r': G.antenna, 's': P.powerboat, 't': P.truckstop, 'u': P.semi, 'v': G.van, 'w': P.water, 'x': P.xaprs, 'y': P.yagi,
 'z': P.shelter, '|': P.tncsw1, '~': P.tncsw2,
}
for d in "0123456789":
    PRIM[d] = P.digitring(d)

# --- додаткова таблиця '\'
ALT = {
 '!': G.emerg, '#': G.digi_alt, '$': A.bank, '%': A.powerplant, '&': G.gateway, "'": A.crash, '(': A.cloud_only, ')': A.meo,
 '*': A.snowflake, '+': A.church, ',': P.trefoil, '-': G.house, '.': A.question, '/': P.waypoint, '0': A.ring0,
 '8': A.wifi, '9': A.pump, ':': A.hail, ';': A.park, '<': A.advisory, '=': A.keypad, '>': G.car, '?': P.kiosk, '@': A.hurricane,
 'A': A.boxsq, 'B': A.blowsnow, 'C': A.anchor, 'D': A.drizzle, 'E': A.smoke, 'F': A.freezing, 'G': A.snowshower, 'H': A.haze,
 'I': A.rainshower, 'J': A.lightning, 'K': A.kenwood, 'L': A.lighthouse, 'M': A.mars, 'N': A.buoy, 'O': A.rocket, 'P': A.parking,
 'Q': A.quake, 'R': A.restaurant, 'S': P.satellite, 'T': A.thunderstorm, 'U': A.sunny, 'V': A.vortac, 'W': P.wxsvc, 'X': A.pharmacy,
 'Y': A.radio, '[': A.wallcloud, '\\': A.gpspin, '^': G.plane, '_': G.wx, '`': A.umbrella,
 'a': A.arrl, 'b': A.dust, 'c': A.civildef, 'd': A.dxspot, 'e': A.sleet, 'f': A.funnel, 'g': A.gale, 'h': A.store, 'i': A.star,
 'j': A.excavator, 'k': G.jeep, 'l': A.areas, 'm': A.signpost, 'n': G.tri, 'o': A.smallring, 'p': A.partly, 'r': A.restrooms,
 's': A.ship, 't': A.tornado, 'u': G.truck, 'v': G.van, 'w': A.flood, 'x': A.barrier, 'y': A.binoculars, 'z': P.shelter,
 '{': A.fog, '|': P.tncsw1, '~': P.tncsw2,
}

def despeckle(cv):
    """прибрати поодинокі пікселі (без жодного сусіда): на цьому екрані вони розмиваються"""
    p = cv.p
    rm = []
    for y in range(24):
        for x in range(24):
            if p[y][x]:
                nb = sum(1 for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dx or dy) and 0 <= x + dx < 24 and 0 <= y + dy < 24 and p[y + dy][x + dx])
                if nb == 0:
                    rm.append((x, y))
    for x, y in rm:
        p[y][x] = 0

def all_icons():
    out = []
    for t, tab in (('/', PRIM), ('\\', ALT)):
        for code in sorted(tab, key=lambda c: ord(c)):
            cv = tab[code]()
            despeckle(cv)
            out.append((t, code, cv))
    return out

def write_txt(path):
    """записати ASCII-джерело (стартова точка; далі ДЖЕРЕЛО ПРАВДИ -- tools/aprs_icons.txt, його правлять руками)"""
    import os
    from names import NEW_P, NEW_A
    hdr = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'application', 'include', 'user_interface', 'languages', 'aprsmode_ua.h')
    txt = open(hdr, 'rb').read().decode('cp1251')
    ex = {'P': {}, 'A': {}}
    for m in re.finditer(r'#define\s+APRSM_SYM_([PA])_([0-9A-F]{2})\s+"([^"]*)"', txt):
        ex[m.group(1)][chr(int(m.group(2), 16))] = m.group(3)
    base = {'>': 'авто', '[': 'людина', '-': 'дім', 'b': 'велосипед', '<': 'мотоцикл', 'k': 'вантажівка', 'v': 'фургон', '#': 'діджі', 'r': 'ретранслятор', 'Y': 'яхта'}
    out = []
    for t, c, cv in all_icons():
        n = (NEW_P if t == '/' else NEW_A).get(c) or (base.get(c) if t == '/' else None) or ex['P' if t == '/' else 'A'].get(c) or '?'
        out.append("@ %s %s %s" % (t, c, n))
        out.extend(''.join('#' if v else '.' for v in row) for row in cv.p)
        out.append('')
    open(path, 'w', encoding='utf-8').write('\n'.join(out))


if __name__ == '__main__':
    if len(sys.argv) > 2 and sys.argv[1] == 'txt':
        write_txt(sys.argv[2])
        sys.exit(0)
    ic = all_icons()
    print(len(ic), 'піктограм', len(PRIM), len(ALT))
    which = sys.argv[1] if len(sys.argv) > 1 else None
    if which:
        items = [("%s%s" % (t, c), cv) for t, c, cv in ic if (which == 'all' or t == which)]
        sheet_png(items, 'sheet_%s.png' % ('all' if which == 'all' else ('p' if which == '/' else 'a')), cols=12, scale=4)
