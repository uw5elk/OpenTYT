#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R53: порядок каналів, зон, контактів і списків прийому в CPS (tools/reorder.py). Хост-тести, без рації й без Tk.

L1  синтетичний кодплаг (канали в EEPROM і флеші, дірки в слотах, контакти, списки, зони, VFO, LUCZ, налаштування, квіккеї) сам цілісний;
L2  випадкові перестановки КОЖНОГО виду (формат зон 80 і 16): після кожної -- усі посилання вказують на ТІ САМІ за вмістом записи
    (назви / ID / частоти), порядок = заданий, цілісність кодплага (усі номери вказують на наявні записи, маски не змінились),
    змінено лише дозволені ділянки (нічого зайвого не зачеплено);
L3  крок «вгору / вниз» і перенесення: межі без збою, сусідні міняються місцями, порожні слоти й дірки лишаються на місцях;
L4  крайні випадки: нульовий контакт «Немає», висяче посилання, нема LUCZ / налаштувань, активна зона = «Всі канали», квіккеї (попередження);
L5  некоректний порядок відхиляється ДО змін; обернена перестановка повертає вихідні байти;
L6  МУТАНТИ: кожен пропущений перерахунок посилань валить відповідну перевірку;
L7  образ після перестановки проходить шлях CSV (експорт -> імпорт без змін == той самий образ) -- структура придатна для читання.
Запуск: python3 tools/test_r53.py"""
import os
import random
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cps_link as cl            # noqa: E402
import cps_csv as cc            # noqa: E402
import codeplug_view as cv       # noqa: E402
import reorder as ro             # noqa: E402
import table_edit as te          # noqa: E402
import vfo_edit as ve            # noqa: E402
import test_cps_link as base     # noqa: E402
import test_cps_csv as tcsv      # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


# ---------------------------------------------------------------------------------------------------------------------------------
#  Синтетичний кодплаг
# ---------------------------------------------------------------------------------------------------------------------------------

def blank_image(zone80=True):
    spi = base.make_spi()
    rng = cl.flash_backup_range()
    img = cc.Image(bytearray(spi[:cl.EEPROM_BACKUP_LEN]), bytearray(spi[rng["raw_start"]:rng["raw_start"] + rng["length"]]), rng["codeplug_start"])
    for s, _r in img.contacts():
        img.set_contact(s, b"\xff" * 24)
    for s, _r, _l in img.groups():
        img.clear_group_len(s)
    for b, _r in img.zones():
        img.clear_zone(b)
    img.set_ee(cl.CP_ADDR_EX_ZONE_INUSE, bytes(32))
    for n, _r in img.channels():
        img.set_channel_in_use(n, False)
    img.set_ee(cv.CP_ADDR_ZONE_FORMAT_BYTE, b"\x00" if zone80 else b"\xff")
    return img


def contact_rec(name, ident, ctype=0):
    return name.encode("cp1251").ljust(16, b"\xff") + bytes.fromhex("%08d" % ident) + bytes([ctype]) + b"\x00\x00\x00"


def world(seed, zone80=True, lucz=True, settings=True, quick=True):
    """Випадковий кодплаг: контакти (12) у розкиданих слотах, списки (6), канали (22 у трьох банках, EEPROM + флеш), зони (6), VFO A/B."""
    rg = random.Random(seed)
    img = blank_image(zone80)
    cslots = sorted(rg.sample(range(0, 70), 12))
    for s in cslots:
        img.set_contact(s, contact_rec("Ct%d" % s, 1000 + s, s % 3))
    cnums = [s + 1 for s in cslots]
    gslots = sorted(rg.sample(range(0, 20), 6))
    gnums = [s + 1 for s in gslots]
    for s in gslots:
        mem = rg.sample(cnums, rg.randint(1, 6))
        rec = ("Gr%d" % s).encode("cp1251").ljust(16, b"\xff") + b"".join(struct.pack("<H", v) for v in mem).ljust(64, b"\x00")
        img.set_group(s, rec, len(mem))
    chn = sorted(rg.sample(list(range(1, 40)) + list(range(125, 135)) + list(range(250, 262)), 22))
    for n in chn:
        digital = rg.random() < 0.6
        kw = {"contact": rg.choice(cnums + [0]), "group": rg.choice(gnums + [0])}
        if n == chn[3]:
            kw["contact"] = 900                          # висяче посилання (слота 899 нема): має лишитись як є
        img.set_channel_rec(n, tcsv.chan(("Ch%d" % n).encode("cp1251"), 14400000 + 25 * n, 14400000 + 25 * n, digital, **kw))
        img.set_channel_in_use(n, True)
    st = img.zone_stride()
    zbits = sorted(rg.sample(range(0, 30), 6))
    for b in zbits:
        mem = rg.sample(chn, rg.randint(1, 10))
        rec = ("Zn%d" % b).encode("cp1251").ljust(16, b"\xff") + b"".join(struct.pack("<H", v) for v in mem).ljust(st - 16, b"\x00")
        img.set_zone(b, rec)
    for n in (0, 1):
        img.set_ee(ve.vfo_addr(n), tcsv.chan(b"VFO%d" % n, 43000000 + 1000 * n, 43000000 + 1000 * n, True, contact=rg.choice(cnums), group=rg.choice(gnums)))
    if lucz:
        img.set_ee(ro.LUCZ_ADDR, ro.LUCZ_TAG + bytes(70))
        for b in zbits:
            ln = len([v for v in te.zones(img) if v[0] == b][0][2])
            img.set_ee(ro.LUCZ_DATA + b, bytes([rg.randrange(ln)]))
        img.set_ee(ro.LUCZ_DATA + ro.LUCZ_ALL_OFFSET, struct.pack("<h", rg.choice(chn) - 1))
    if settings:
        img.set_ee(ro.SETTINGS_ADDR, struct.pack("<I", ro.SETTINGS_MAGIC))
        img.set_ee(ro.SETTINGS_ADDR + ro.CURRENT_ZONE_OFFSET, struct.pack("<h", rg.randint(0, len(zbits))))
    if quick:
        keys = [0x8000] * 10
        keys[1] = rg.choice(cnums)
        keys[4] = 0x8000 | (3 << 10) | 2
        img.set_ee(ro.QUICKKEYS_ADDR, struct.pack("<10H", *keys))
    return img


# ---------------------------------------------------------------------------------------------------------------------------------
#  Розв'язання посилань за ВМІСТОМ та інваріанти
# ---------------------------------------------------------------------------------------------------------------------------------

def resolve(img):
    """Усе, що має лишитись незмінним при будь-якій перестановці: посилання, перераховані в ІМЕНА (контакт / список / канал / зона)."""
    cn = {s: cc.readable_text(r[:16]) for s, r in img.contacts()}
    gn = {s: cc.readable_text(r[:16]) for s, r, _l in img.groups()}
    chn = {n: cc.readable_text(r[:16]) for n, r in img.channels()}

    def cname(v):
        return None if v == 0 else cn.get(v - 1, ("висяче", v))

    def gname(v):
        return None if v == 0 else gn.get(v - 1, ("висяче", v))

    def zeroed(rec):
        r = bytearray(rec)
        r[cc.O_CONTACT:cc.O_CONTACT + 2] = b"\x00\x00"
        r[cc.O_GROUP] = 0
        return bytes(r)

    out = {"contacts": {cc.readable_text(r[:16]): bytes(r) for _s, r in img.contacts()}}
    out["groups"] = {}
    for _s, r, ln in img.groups():
        mem = te._members(r, ln)
        out["groups"][cc.readable_text(r[:16])] = (ln, [cname(v) for v in mem], bytes(r[16 + 2 * len(mem):]))
    out["channels"] = {}
    for n, r in img.channels():
        out["channels"][chn[n]] = (zeroed(r), cname(r[cc.O_CONTACT] | (r[cc.O_CONTACT + 1] << 8)), gname(r[cc.O_GROUP]))
    n80 = img.zone_format()
    out["zones"] = {}
    for b, r in img.zones():
        mem = te._members(r, n80)
        out["zones"][cc.readable_text(r[:16])] = ([chn.get(v, ("висяче", v)) for v in mem], bytes(r[16 + 2 * len(mem):]))
    out["vfo"] = []
    for n in (0, 1):
        r = ve.vfo_rec(img, n)
        out["vfo"].append((zeroed(r), cname(r[cc.O_CONTACT] | (r[cc.O_CONTACT + 1] << 8)), gname(r[cc.O_GROUP])))
    zbits = [b for b, _r in img.zones()]
    zname = {b: cc.readable_text(r[:16]) for b, r in img.zones()}
    if ro.lucz_present(img):
        out["lucz_zone"] = {zname[b]: ro.lucz_zone(img, b) for b in zbits}
        a = ro.lucz_all_channels(img)
        out["lucz_all"] = chn.get(a, ("висяче", a))
    cur = ro.current_zone(img)
    out["current_zone"] = None if cur is None else ("ALL" if cur >= len(zbits) else zname[zbits[cur]])
    out["quick"] = bytes(img.ee(ro.QUICKKEYS_ADDR, 20))
    return out


def integrity(img):
    """Інваріанти цілісності (як у знятої самоперевірки R45, але прямо в тесті). Повертає список порушень."""
    bad = []
    chn = {n for n, _r in img.channels()}
    cn = {s + 1 for s, _r in img.contacts()}
    gn = {s + 1 for s, _r, _l in img.groups()}
    n80 = img.zone_format()
    for b, r in img.zones():
        for v in te._members(r, n80):
            if v not in chn:
                bad.append("зона біт %d: канал №%d не існує" % (b, v))
    for s, r, ln in img.groups():
        for v in te._members(r, ln):
            if v not in cn:
                bad.append("список слот %d: контакт №%d не існує" % (s, v))
    for n, r in img.channels():
        c, g = r[cc.O_CONTACT] | (r[cc.O_CONTACT + 1] << 8), r[cc.O_GROUP]
        if r[cc.O_MODE] != 0:
            if c and c not in cn and c != 900:
                bad.append("цифровий канал №%d: контакт №%d не існує" % (n, c))
            if g and g not in gn:
                bad.append("цифровий канал №%d: список №%d не існує" % (n, g))
    names = [cc.readable_text(r[:16]) for _n, r in img.channels()]
    if len(set(names)) != len(names):
        bad.append("назви каналів повторюються")
    if ro.lucz_present(img):
        zl = dict((b, len(te._members(r, n80))) for b, r in img.zones())
        for b, ln in zl.items():
            if ro.lucz_zone(img, b) >= ln:
                bad.append("LUCZ зони біт %d виходить за список (%d >= %d)" % (b, ro.lucz_zone(img, b), ln))
        a = ro.lucz_all_channels(img)
        if a not in chn:
            bad.append("LUCZ «Всіх каналів» вказує на неіснуючий канал №%d" % a)
    cur = ro.current_zone(img)
    if cur is not None and cur > len(list(img.zones())):
        bad.append("currentZone %d поза межами" % cur)
    return bad


def occupied(img):
    """Множина зайнятих слотів усіх видів + маска зон: перестановка їх змінювати не вправі."""
    return (ro.idents(img, "channel"), ro.idents(img, "contact"), ro.idents(img, "tg"), ro.idents(img, "zone"),
            bytes(img.ee(cl.CP_ADDR_EX_ZONE_INUSE, 32)),
            [r for r in (img.channel_in_use(n) for n in range(1, 1025))])


def allowed_ranges(img, kind):
    """Абсолютні адреси кодплага ("ee"|"fl", початок, кінець), куди перестановка kind ВПРАВІ писати."""
    rng = []
    ch = []
    for n in range(1, cl.CP_CHANNELS_BANKS * cl.CP_CHANNELS_PER_BANK + 1):
        bank, slot = divmod(n - 1, cl.CP_CHANNELS_PER_BANK)
        where, h = img._bank_header_addr(bank)
        ch.append((where, h + 16 + slot * cc.CH_SIZE, h + 16 + (slot + 1) * cc.CH_SIZE))
    vfo = [("ee", ve.ADDR_VFO_A, ve.ADDR_VFO_A + 2 * ve.VFO_SIZE)]
    zones = [("ee", cl.CP_ADDR_EX_ZONE_LIST, cl.CP_ADDR_EX_ZONE_LIST + cl.CP_ZONES_MAX * img.zone_stride())]
    contacts = [("fl", cl.CP_ADDR_CONTACTS, cl.CP_ADDR_CONTACTS + cl.CP_CONTACTS_MAX * cl.CP_CONTACT_SIZE)]
    groups = [("fl", cl.CP_ADDR_RX_GROUP, cl.CP_ADDR_RX_GROUP + cl.CP_RXGROUPS_MAX * cl.CP_RXGROUP_SIZE),
              ("fl", cl.CP_ADDR_RX_GROUP_LEN, cl.CP_ADDR_RX_GROUP_LEN + cl.CP_RXGROUPS_MAX)]
    if kind == "channel":
        rng = ch + zones + [("ee", ro.LUCZ_DATA + ro.LUCZ_ALL_OFFSET, ro.LUCZ_DATA + ro.LUCZ_ALL_OFFSET + 2)]
    elif kind == "contact":
        rng = contacts + groups[:1] + ch + vfo
    elif kind == "tg":
        rng = groups + ch + vfo
    else:
        rng = zones + [("ee", ro.LUCZ_DATA, ro.LUCZ_DATA + 70),
                       ("ee", ro.SETTINGS_ADDR + ro.CURRENT_ZONE_OFFSET, ro.SETTINGS_ADDR + ro.CURRENT_ZONE_OFFSET + 2)]
    return rng


def stray_changes(before, after, kind):
    """Адреси змінених байтів поза дозволеними ділянками."""
    rng = allowed_ranges(before, kind)
    stray = []
    for where, a, b in (("ee", before.eeprom, after.eeprom), ("fl", before.flash, after.flash)):
        base_addr = 0 if where == "ee" else before.base
        for i in range(len(a)):
            if a[i] != b[i]:
                addr = base_addr + i
                if not any(w == where and lo <= addr < hi for w, lo, hi in rng):
                    stray.append((where, addr))
                    if len(stray) > 5:
                        return stray
    return stray


def order_names(img, kind):
    return [dict(te.entity_names(img, kind))[i] for i in ro.idents(img, kind)]


# ---------------------------------------------------------------------------------------------------------------------------------
#  Прогін однієї перестановки з усіма перевірками
# ---------------------------------------------------------------------------------------------------------------------------------

def run_permutation(img, kind, rg, tag, report=True):
    """Випадкова перестановка; повертає (новий образ, список проблем)."""
    before = resolve(img)
    ids = ro.idents(img, kind)
    names = dict(te.entity_names(img, kind))
    new_order = list(ids)
    rg.shuffle(new_order)
    res = ro.permute(img, kind, new_order)
    out = res.image
    problems = []
    if resolve(out) != before:
        diff = [k for k in before if resolve(out).get(k) != before[k]]
        problems.append("%s: посилання після перестановки вказують на інші записи (розділи: %s)" % (tag, ", ".join(diff)))
    if order_names(out, kind) != [names[i] for i in new_order]:
        problems.append("%s: порядок після перестановки не збігається із заданим" % tag)
    if integrity(out):
        problems.append("%s: порушено цілісність: %s" % (tag, integrity(out)[:3]))
    if occupied(out) != occupied(img):
        problems.append("%s: змінилась множина зайнятих слотів / маски" % tag)
    st = stray_changes(img, out, kind)
    if st:
        problems.append("%s: змінено байти поза дозволеними ділянками: %r" % (tag, st[:3]))
    if report:
        for p in problems:
            check(False, p)
    return out, problems


def test_l1_world():
    for z80 in (True, False):
        for seed in range(4):
            img = world(seed, z80)
            check(not integrity(img), "L1: синтетичний кодплаг цілісний (seed %d, зони %s): %r" % (seed, "80" if z80 else "16", integrity(img)[:3]))
            check(len(ro.idents(img, "channel")) == 22 and len(ro.idents(img, "contact")) == 12 and len(ro.idents(img, "tg")) == 6
                  and len(ro.idents(img, "zone")) == 6, "L1: кількості записів")
            check(img.zone_format() == (80 if z80 else 16), "L1: формат зон")
            check(any(n > 128 for n in ro.idents(img, "channel")) and any(n <= 128 for n in ro.idents(img, "channel")), "L1: є канали і в EEPROM, і у флеші")
            gaps = [s for s in ro.idents(img, "contact")]
            check(gaps != list(range(len(gaps))), "L1: у контактах є дірки між слотами")
    # самі перевірки чутливі: зіпсований образ ловиться
    img = world(1)
    bad = cc.Image(img.eeprom, img.flash, img.base)
    n = ro.idents(bad, "channel")[0]
    rec = bytearray(bad.channel_rec(n))
    rec[cc.O_MODE] = 1
    struct.pack_into("<H", rec, cc.O_CONTACT, 777)
    bad.set_channel_rec(n, bytes(rec))
    check(integrity(bad), "L1: перевірка цілісності бачить посилання на неіснуючий контакт")
    check(resolve(bad) != resolve(img), "L1: розв'язання за вмістом бачить зміну посилання")


def test_l2_random():
    total = 0
    for kind in ro.KINDS:
        for z80 in (True, False):
            for seed in range(6):
                img = world(seed * 7 + 1, z80)
                rg = random.Random(seed + 100)
                for it in range(8):
                    img, _p = run_permutation(img, kind, rg, "L2 %s/зони %s/seed %d/крок %d" % (kind, "80" if z80 else "16", seed, it))
                    total += 1
    check(total == 4 * 2 * 6 * 8, "L2: виконано %d перестановок" % total)
    # змішані: по черзі різні види на одному образі
    img = world(5)
    rg = random.Random(55)
    for it in range(40):
        img, _p = run_permutation(img, rg.choice(ro.KINDS), rg, "L2-змішані/крок %d" % it)


def test_l3_steps():
    img = world(3)
    for kind in ro.KINDS:
        ids = ro.idents(img, kind)
        # межі: «вгору» для першого і «вниз» для останнього -- без змін і без збою
        for ident, step in ((ids[0], -1), (ids[-1], 1)):
            res = ro.move(img, kind, ident, step)
            check(bytes(res.image.eeprom) == bytes(img.eeprom) and bytes(res.image.flash) == bytes(img.flash) and not res.changed,
                  "L3 %s: на межі нічого не змінюється" % kind)
        # сусіди міняються місцями
        names = order_names(img, kind)
        for pos in (1, len(ids) // 2, len(ids) - 1):
            res = ro.move(img, kind, ids[pos], -1)
            exp = list(names)
            exp[pos - 1], exp[pos] = exp[pos], exp[pos - 1]
            check(order_names(res.image, kind) == exp, "L3 %s: «вгору» з позиції %d міняє місцями із сусідом" % (kind, pos))
            check(resolve(res.image) == resolve(img), "L3 %s: посилання на місці після кроку" % kind)
            check(ro.ident_after_move(img, kind, ids[pos], step=-1) == ids[pos - 1], "L3 %s: слот після кроку" % kind)
        for pos in (0, len(ids) // 2):
            res = ro.move(img, kind, ids[pos], 1)
            exp = list(names)
            exp[pos + 1], exp[pos] = exp[pos], exp[pos + 1]
            check(order_names(res.image, kind) == exp, "L3 %s: «вниз» з позиції %d" % (kind, pos))
        # перенесення на довільне місце
        res = ro.move_to(img, kind, ids[0], ids[-1])
        exp = list(names)
        exp.append(exp.pop(0))
        check(order_names(res.image, kind) == exp, "L3 %s: перенесення першого на місце останнього" % kind)
        check(resolve(res.image) == resolve(img), "L3 %s: посилання на місці після перенесення" % kind)
        res = ro.move_to(img, kind, ids[-1], ids[0])
        check(order_names(res.image, kind)[0] == names[-1], "L3 %s: перенесення останнього нагору" % kind)
        # дірки лишаються на місцях
        check(ro.idents(res.image, kind) == ids, "L3 %s: множина зайнятих слотів (дірки) та сама" % kind)
    # журнал: короткий для кроку, один рядок для великої перестановки
    res = ro.move(img, "channel", ro.idents(img, "channel")[5], -1)
    check(2 <= len(res.changed) <= 6 and any("Канали" == s for s, _t in res.changed), "L3: журнал кроку: %r" % res.changed)
    big = ro.permute(img, "channel", list(reversed(ro.idents(img, "channel"))))
    check(sum(1 for s, _t in big.changed if s == "Канали") == 1, "L3: велика перестановка -- один рядок у журналі")


def test_l4_edges():
    # --- «Немає» (0) лишається 0, висяче посилання лишається висячим ---
    img = world(2)
    ids = ro.idents(img, "contact")
    res = ro.permute(img, "contact", list(reversed(ids)))
    out = res.image
    zero = [n for n, r in img.channels() if r[cc.O_CONTACT] == 0 and r[cc.O_MODE] != 0]
    check(all(out.channel_rec(n)[cc.O_CONTACT:cc.O_CONTACT + 2] == b"\x00\x00" for n in zero), "L4: контакт «Немає» (0) лишається 0")
    dang = [n for n, r in img.channels() if (r[cc.O_CONTACT] | (r[cc.O_CONTACT + 1] << 8)) == 900]
    check(dang and all((out.channel_rec(n)[cc.O_CONTACT] | (out.channel_rec(n)[cc.O_CONTACT + 1] << 8)) == 900 for n in dang),
          "L4: висяче посилання на порожній слот лишається тим самим числом (не потрапляє на живий запис)")
    # --- нема LUCZ і/або налаштувань ---
    for kw in ({"lucz": False}, {"settings": False}, {"lucz": False, "settings": False, "quick": False}):
        img = world(4, **kw)
        for kind in ro.KINDS:
            _o, p = run_permutation(img, kind, random.Random(9), "L4 %r/%s" % (kw, kind), report=False)
            check(not p, "L4 %r/%s: %r" % (kw, kind, p))
    img = world(4, lucz=False, settings=False, quick=False)
    out = ro.permute(img, "zone", list(reversed(ro.idents(img, "zone")))).image
    check(bytes(out.ee(0x6000, 0x90)) == bytes(img.ee(0x6000, 0x90)), "L4: без тегу LUCZ / магічного числа ділянка 0x6000..0x608F не чіпається")
    # --- активна зона = «Всі канали» лишається «Всіма каналами»; інакше -- та сама зона ---
    img = world(6)
    nz = len(ro.idents(img, "zone"))
    for cur in range(nz + 1):
        im = cc.Image(img.eeprom, img.flash, img.base)
        im.set_ee(ro.SETTINGS_ADDR + ro.CURRENT_ZONE_OFFSET, struct.pack("<h", cur))
        res = ro.permute(im, "zone", list(reversed(ro.idents(im, "zone"))))
        check(resolve(res.image)["current_zone"] == resolve(im)["current_zone"], "L4: активна зона #%d лишається тією самою" % cur)
        if cur == nz:
            check(ro.current_zone(res.image) == nz, "L4: «Всі канали» лишаються активними")
    # --- один запис / порожній вид: нічого не ламається ---
    one = blank_image()
    one.set_contact(3, contact_rec("Єдиний", 5))
    r1 = ro.permute(one, "contact", [3])
    check(bytes(r1.image.fl(cl.CP_ADDR_CONTACTS, 24 * 10)) == bytes(one.fl(cl.CP_ADDR_CONTACTS, 24 * 10)) and not r1.changed, "L4: один контакт -- без змін")
    for kind in ro.KINDS:
        r0 = ro.permute(blank_image(), kind, [])
        check(not r0.changed and bytes(r0.image.eeprom) == bytes(blank_image().eeprom), "L4 %s: порожній вид -- без змін" % kind)
    # --- квіккеї: образ не чіпається, є попередження ---
    img = world(7)
    qk = dict(ro.quickkeys(img))
    check(len(qk) == 2 and qk[4] & 0x8000, "L4: квіккеї прочитано: %r" % (qk,))
    cnum = qk[1]
    ids = ro.idents(img, "contact")
    order = [i for i in ids if i != cnum - 1] + [cnum - 1]
    res = ro.permute(img, "contact", order)
    check(res.image.ee(ro.QUICKKEYS_ADDR, 20) == img.ee(ro.QUICKKEYS_ADDR, 20), "L4: квіккеї в образі не змінено")
    check(any("Квіккей «1»" in w for w in res.warnings), "L4: попередження про квіккей контакту: %r" % res.warnings)
    res = ro.permute(img, "zone", list(reversed(ro.idents(img, "zone"))))
    check(any("квіккеї меню" in w and "4" in w for w in res.warnings), "L4: попередження про квіккей меню при перестановці зон: %r" % res.warnings)
    res = ro.permute(img, "channel", list(reversed(ro.idents(img, "channel"))))
    check(not res.warnings, "L4: канали -- квіккеї не залежать, попереджень нема: %r" % res.warnings)


def test_l5_errors_and_inverse():
    img = world(8)
    snap = (bytes(img.eeprom), bytes(img.flash))
    ids = ro.idents(img, "channel")
    for label, order in (("повтор", ids[:-1] + [ids[0]]), ("бракує", ids[:-1]), ("зайвий", ids + [999]), ("чужий", ids[:-1] + [998])):
        try:
            ro.permute(img, "channel", order)
            check(False, "L5: %s -- перестановку мало бути відхилено" % label)
        except ro.ReorderError as e:
            check(e.problems, "L5: %s -- є пояснення" % label)
        check((bytes(img.eeprom), bytes(img.flash)) == snap, "L5: %s -- образ-аргумент не змінено" % label)
    try:
        ro.permute(img, "dtmf", [])
        check(False, "L5: невідомий вид відхилено")
    except ro.ReorderError:
        pass
    try:
        ro.move(img, "channel", 999, -1)
        check(False, "L5: крок для неіснуючого запису відхилено")
    except ro.ReorderError:
        pass
    check(isinstance(ro.ReorderError([]), te.TableEditError), "L5: ReorderError показується панеллю як TableEditError")
    # обернена перестановка повертає вихідні байти
    for kind in ro.KINDS:
        rg = random.Random(31)
        order = list(ro.idents(img, kind))
        rg.shuffle(order)
        step1 = ro.permute(img, kind, order).image
        # тепер у слоті ids[k] лежить запис, що був order[k]; щоб повернути, потрібно в слот order[k] поставити запис зі слота ids[k] -> inv
        ids_k = ro.idents(img, kind)
        pos = {ident: k for k, ident in enumerate(order)}                       # запис order[k] тепер у слоті ids_k[k]
        back = [ids_k[pos[i]] for i in ids_k]
        step2 = ro.permute(step1, kind, back).image
        check(bytes(step2.eeprom) == bytes(img.eeprom) and bytes(step2.flash) == bytes(img.flash), "L5 %s: обернена перестановка повертає вихідні БАЙТИ" % kind)
    # ідентична перестановка -- без змін
    for kind in ro.KINDS:
        r = ro.permute(img, kind, ro.idents(img, kind))
        check(not r.changed and not r.warnings and bytes(r.image.eeprom) == bytes(img.eeprom) and bytes(r.image.flash) == bytes(img.flash),
              "L5 %s: ідентична перестановка -- без змін і без попереджень" % kind)


# ---------------------------------------------------------------------------------------------------------------------------------
#  Мутанти
# ---------------------------------------------------------------------------------------------------------------------------------

def suite_failures(kinds, seeds=3, steps=4):
    """Скільки випадкових перестановок має проблеми (для мутантів: у справжнього коду -- 0)."""
    bad = 0
    for kind in kinds:
        for z80 in (True, False):
            for seed in range(seeds):
                img = world(seed * 5 + 2, z80)
                rg = random.Random(seed + 7)
                for it in range(steps):
                    try:
                        img, p = run_permutation(img, kind, rg, "mut", report=False)
                    except Exception:  # noqa: BLE001 -- мутант міг зламати інше: це теж «виявлено»
                        bad += 1
                        break
                    bad += 1 if p else 0
    return bad


def test_l6_mutants():
    check(suite_failures(ro.KINDS) == 0, "L6: справжній код проходить усі перевірки (база для мутантів)")
    cases = (
        ("пропущено перенумерацію каналів у зонах", "_remap_zone_members", lambda img, nm: 0, ("channel",)),
        ("пропущено LUCZ «Всіх каналів»", "_fix_lucz_all", lambda out, mapping, res: None, ("channel",)),
        ("пропущено контакти у списках прийому", "_remap_group_members", lambda img, nm: 0, ("contact",)),
        ("пропущено O_CONTACT у каналах", "_remap_channels_field", lambda img, off, two, nm: 0, ("contact",)),
        ("пропущено O_GROUP у каналах", "_remap_channels_field", lambda img, off, two, nm: 0, ("tg",)),
        ("пропущено VFO (контакт)", "_remap_vfo_field", lambda img, off, two, nm: 0, ("contact",)),
        ("пропущено VFO (список)", "_remap_vfo_field", lambda img, off, two, nm: 0, ("tg",)),
        ("пропущено LUCZ зон", "_fix_lucz_zones", lambda src, out, moved: None, ("zone",)),
        ("пропущено currentZone", "_fix_current_zone", lambda src, out, mapping, old, res: None, ("zone",)),
    )
    for label, attr, fake, kinds in cases:
        real = getattr(ro, attr)
        setattr(ro, attr, fake)
        try:
            n = suite_failures(kinds)
        finally:
            setattr(ro, attr, real)
        check(n > 0, "L6 мутант «%s»: тести ПОВИННІ падати, але нічого не помічено" % label)
    # мутант «перенумеровано лише цифрові канали»: O_CONTACT аналогових лишається на старому слоті
    real = ro._remap_channels_field

    def only_digital(img, off, two, nm):
        n = 0
        for num, rec in img.channels():
            if rec[cc.O_MODE] == 0:
                continue
            n += real(_OneChan(img, num), off, two, nm)
        return n
    class _OneChan:  # мінімальна обгортка: лише потрібний канал
        def __init__(self, img, num):
            self.img, self.num = img, num

        def channels(self):
            return [(self.num, self.img.channel_rec(self.num))]

        def set_channel_rec(self, n, rec):
            self.img.set_channel_rec(n, rec)
    ro._remap_channels_field = only_digital
    try:
        n = suite_failures(("contact", "tg"))
    finally:
        ro._remap_channels_field = real
    check(n > 0, "L6 мутант «перенумеровано лише цифрові канали»: має падати")
    # мутант «записи не переносяться, лише посилання міняються»
    real = cc.Image.set_contact
    cc.Image.set_contact = lambda self, slot, rec: None
    try:
        n = suite_failures(("contact",))
    finally:
        cc.Image.set_contact = real
    check(n > 0, "L6 мутант «записи контактів не переносяться»: має падати")
    # після мутантів код відновлено
    check(suite_failures(ro.KINDS, seeds=1, steps=2) == 0, "L6: після мутантів код у вихідному стані")


def test_l7_csv_path():
    for kind in ro.KINDS:
        img = world(9)
        rg = random.Random(3)
        order = list(ro.idents(img, kind))
        rg.shuffle(order)
        out = ro.permute(img, kind, order).image
        with tempfile.TemporaryDirectory() as d:
            cc.export_files(out, d, ",", log=lambda *_: None)
            res = cc.import_csv(out, cc.read_dir(d), dp=",")
            same = bytes(res.image.eeprom) == bytes(out.eeprom) and bytes(res.image.flash) == bytes(out.flash)
            check(same and not res.any_change(), "L7 %s: після перестановки експорт CSV -> імпорт без правок == той самий образ (змін: %s)" % (kind, res.summary()))
            rows = tcsv.read_csv_rows(os.path.join(d, "Channels.csv"))
            nums = [int(r[0]) for r in rows[1:]]
            check(nums == sorted(nums), "L7 %s: Channels.csv іде за зростанням номера" % kind)


def main():
    tests = [test_l1_world, test_l2_random, test_l3_steps, test_l4_edges, test_l5_errors_and_inverse, test_l6_mutants, test_l7_csv_path]
    for t in tests:
        print("--", t.__name__)
        t()
    print("ПРОВАЛІВ: %d" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
