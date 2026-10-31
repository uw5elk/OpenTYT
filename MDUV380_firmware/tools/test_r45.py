#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R45: самоперевірка -- цілісність кодплага (V1, cp_integrity.py) і різниця після операції (V2, cp_diff.py), сценарії S6.1/S6.2/S6.3 майстра.

Рації нема: кодплаг -- образ із фікстури test_cps_csv (+ налаштування, LUCZ і VFO, яких у фікстурі нема), рація -- підроблена (FakeRadioX з test_cps_restore).

Z0  адреси й розкладки в модулях збігаються з іншими модулями й з codeplug.h (а не вгадані);
Z1  кожна перевірка V1: справний кодплаг -- проходить; підкладена вада -- провалюється й НАЗИВАЄ місце (зона, позиція, канал, контакт); мутанти перевірок ловляться;
Z2  між двома знімками змінено один канал -- у різниці рівно він і нічого більше; видалення каналу/контакту/зони -- наслідки відокремлено від несподіваного; файл стану;
Z3  підкладена зміна калібрування (і хеша ключів/теми) -- голосно: і в різниці, і в сценарії (FAIL + ctx.shout);
Z4  великий кодплаг (сотні каналів, усі зони, усі контакти): V1 і порівняння вкладаються в розумний час, час друкується (і йде у звіт сценарію);
Z5  сценарії S6.1-S6.3 на підробленій рації (лише читання, звіт, підказки), кнопки панелі під xvfb (без DISPLAY розділ пропущено).
Запуск: `xvfb-run -a python3.12 tools/test_r45.py`."""
import copy
import datetime
import os
import re
import struct
import sys
import tempfile
import time
import types
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cp_diff as cdf                    # noqa: E402
import cp_integrity as cint              # noqa: E402
import cps_csv as cc                     # noqa: E402
import cps_link as cl                    # noqa: E402
import selfcheck as sc                   # noqa: E402
import test_cps_csv as tc                # noqa: E402
import test_cps_restore as tcr           # noqa: E402
import test_r38 as t38                   # noqa: E402
import vfo_edit as ve                    # noqa: E402

FAILS = []
CODEPLUG_H = os.path.join(HERE, "..", "application", "include", "functions", "codeplug.h")
TIMES = {}


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


# ----------------------------------------------------------------------------------------------------------------------
#  Образи
# ----------------------------------------------------------------------------------------------------------------------

def add_runtime(img):
    """До фікстури додає те, чого в ній нема, а в живої рації є: налаштування (магія, поточна зона), LUCZ і обидва VFO (копії записів каналів 1 і 2)."""
    ee = img.eeprom
    ee[cint.SETTINGS_EE_ADDR:cint.SETTINGS_EE_ADDR + 4] = struct.pack("<I", cint.SETTINGS_MAGIC)
    struct.pack_into("<h", ee, cint.SETTINGS_EE_ADDR + cint.SETTINGS_OFF_CURRENT_ZONE, 0)
    ee[cint.LUCZ_ADDR:cint.LUCZ_ADDR + 4] = b"LUCZ"
    ee[cint.LUCZ_ADDR + 4:cint.LUCZ_ADDR + 4 + cint.LUCZ_BYTES] = bytes(70)
    struct.pack_into("<h", ee, cint.LUCZ_ADDR + 4 + cint.LUCZ_ALL_SLOT, 0)
    img.set_ee(cint.ADDR_VFO[0], img.channel_rec(1))
    img.set_ee(cint.ADDR_VFO[1], img.channel_rec(2))
    return img


def base_image():
    spi = t38.make_spi()
    cp, _ = tc.codeplug_of(spi)
    return add_runtime(cc.Image.from_codeplug(cp))


_BASE = None


def fresh():
    """Новий незалежний образ справного кодплага."""
    global _BASE
    if _BASE is None:
        _BASE = base_image()
    return cc.Image(bytearray(_BASE.eeprom), bytearray(_BASE.flash), _BASE.base)


def edit_chan(img, n, fn):
    rec = bytearray(img.channel_rec(n))
    fn(rec)
    img.set_channel_rec(n, bytes(rec))


def zone_rec(img, bit):
    return dict(img.zones())[bit]


def set_zone_vals(img, bit, vals):
    rec = bytearray(zone_rec(img, bit))
    fmt = img.zone_format()
    rec[16:] = struct.pack("<%dH" % fmt, *(list(vals) + [0] * (fmt - len(vals))))
    img.set_zone(bit, bytes(rec))


def set_current_zone(img, v):
    struct.pack_into("<h", img.eeprom, cint.SETTINGS_EE_ADDR + cint.SETTINGS_OFF_CURRENT_ZONE, v)


def erase_contact(img, number):
    img.set_contact(number - 1, b"\xff" * cl.CP_CONTACT_SIZE)


def ref16(rec, off, v):
    rec[off] = v & 255
    rec[off + 1] = v >> 8


def failed(checks):
    return {c.cid: c for c in checks if not c.ok}


# ----------------------------------------------------------------------------------------------------------------------
#  Вади, що підкладаються: (назва, підклад, мають_провалитись -- рівно ці перевірки, {перевірка: [підрядки у місці]})
# ----------------------------------------------------------------------------------------------------------------------

def p_dangling_zone(img):
    set_zone_vals(img, 0, [1, 3, 777])


def p_hole(img):
    set_zone_vals(img, 5, [1, 2, 0, 130])


def p_contact_erased(img):
    erase_contact(img, 2)


def p_group_dangling(img):
    edit_chan(img, 1, lambda r: r.__setitem__(cc.O_GROUP, 9))


def p_group_member(img):
    erase_contact(img, 3)                                   # контакт №3 лежить у списку прийому №1, на нього не вказує жоден канал


def p_aprs(img):
    edit_chan(img, 1, lambda r: r.__setitem__(cc.O_APRS, 5))


def p_vfo(img):
    rec = bytearray(img.ee(cint.ADDR_VFO[0], cl.CP_CHANNEL_SIZE))
    ref16(rec, cc.O_CONTACT, 1000)                          # контакту №1000 нема
    img.set_ee(cint.ADDR_VFO[0], bytes(rec))


def p_vfo_group(img):
    rec = bytearray(img.ee(cint.ADDR_VFO[1], cl.CP_CHANNEL_SIZE))
    rec[cc.O_MODE] = 1
    rec[cc.O_GROUP] = 33
    img.set_ee(cint.ADDR_VFO[1], bytes(rec))


def p_mask_no_record(img):
    img.set_channel_in_use(500, True)                       # у масці, а запис 0xFF (фантомний канал)
    img.set_channel_rec(500, b"\xff" * cl.CP_CHANNEL_SIZE)


def p_zone_mentions_unmasked(img):
    set_zone_vals(img, 1, [2, 140])


def p_zone_no_name(img):
    rec = bytearray(zone_rec(img, 1))
    rec[:16] = b"\xff" * 16
    img.set_zone(1, bytes(rec))


def p_current_zone(img):
    set_current_zone(img, 9)


def p_lucz_zone(img):
    img.eeprom[cint.LUCZ_ADDR + 4 + 0] = 7                  # зона з бітом 0 має 2 канали, а збережена позиція 8


def p_lucz_all_current(img):
    set_current_zone(img, 3)                                # «Всі канали» (зон 3) -- поточна
    struct.pack_into("<h", img.eeprom, cint.LUCZ_ADDR + 4 + cint.LUCZ_ALL_SLOT, 699)   # «останній канал» 700 у кодплазі нема


def p_lucz_all_not_current(img):
    struct.pack_into("<h", img.eeprom, cint.LUCZ_ADDR + 4 + cint.LUCZ_ALL_SLOT, 699)   # зона не поточна -- лише примітка


DEFECTS = [
    ("V1.1 зона вказує на канал, якого нема", p_dangling_zone, {"V1.1", "V1.7"}, {"V1.1": ["«Київ»", "позиція 3", "№777"], "V1.7": ["№777"]}),
    ("V1.2 діра у списку зони", p_hole, {"V1.2"}, {"V1.2": ["«Папуга»", "позиції 3", "№130"]}),
    ("V1.3 канал вказує на стертий контакт", p_contact_erased, {"V1.3", "V1.4"}, {"V1.3": ["№3", "контакт №2"], "V1.4": ["контакт №2"]}),
    ("V1.4 канал вказує на неіснуючий список прийому", p_group_dangling, {"V1.4"}, {"V1.4": ["№1", "список прийому №9"]}),
    ("V1.4 стертий контакт усередині списку прийому", p_group_member, {"V1.4"}, {"V1.4": ["список прийому №1", "позиція 3", "контакт №3"]}),
    ("V1.5 канал вказує на слот APRS за межами", p_aprs, {"V1.5"}, {"V1.5": ["№1", "слот APRS №5", "лише 1"]}),
    ("V1.6 VFO A вказує на стертий контакт", p_vfo, {"V1.6"}, {"V1.6": ["VFO A", "контакт №1000"]}),
    ("V1.6 VFO B вказує на порожній список прийому", p_vfo_group, {"V1.6"}, {"V1.6": ["VFO B", "список прийому №33"]}),
    ("V1.7 канал у масці без запису", p_mask_no_record, {"V1.7", "V1.3", "V1.4", "V1.5"} - {"V1.3", "V1.4", "V1.5"}, {"V1.7": ["канал №500", "у масці"]}),
    ("V1.7 зона згадує канал поза маскою", p_zone_mentions_unmasked, {"V1.1", "V1.7"}, {"V1.7": ["№140", "«Local»", "позиція 2"], "V1.1": ["№140"]}),
    ("V1.8 зона без назви", p_zone_no_name, {"V1.8"}, {"V1.8": ["немає назви"]}),
    ("V1.8 поточна зона поза списком", p_current_zone, {"V1.8"}, {"V1.8": ["поточна зона №9", "зон у масці 3"]}),
    ("V1.8 LUCZ: позиція за межами списку зони", p_lucz_zone, {"V1.8"}, {"V1.8": ["«Київ»", "збережена позиція 8", "каналів у зоні 2"]}),
    ("V1.8 LUCZ «Всі канали» на неіснуючий канал, і це поточна зона", p_lucz_all_current, {"V1.8", "V1.7"}, {"V1.8": ["«Всі канали»", "№700", "ПОТОЧНА"], "V1.7": ["№700", "LUCZ"]}),
]


def defect_suite(mod):
    """Прогін усіх підкладених вад на модулі перевірок `mod` -> перелік розбіжностей (порожній -- модуль справний)."""
    bad = []
    clean = mod.run_checks(fresh())
    if failed(clean):
        bad.append("справний кодплаг провалює: %s" % sorted(failed(clean)))
    if len(clean) != 8 or [c.cid for c in clean] != ["V1.%d" % i for i in range(1, 9)]:
        bad.append("перевірки V1.1..V1.8 не всі на місці")
    for name, plant, must, places in DEFECTS:
        img = fresh()
        plant(img)
        f = failed(mod.run_checks(img))
        if set(f) != must:
            bad.append("%s: провалились %s, очікувалось %s" % (name, sorted(f), sorted(must)))
        for cid, subs in places.items():
            text = f[cid].places(50) if cid in f else ""
            for s in subs:
                if s not in text:
                    bad.append("%s: у місці проблеми %s нема «%s» (є: %s)" % (name, cid, s, text[:200]))
    # аналоговий канал із «висячими» полями контакт/TG-список/APRS-слот у прошивці не читається -- не проблема
    img = fresh()
    edit_chan(img, 2, lambda r: (ref16(r, cc.O_CONTACT, 999), r.__setitem__(cc.O_GROUP, 40)))
    f = failed(mod.run_checks(img))
    if f:
        bad.append("аналоговий канал з висячим контактом/списком -- не проблема, а провалились %s" % sorted(f))
    # «Всі канали» не поточна -- лише примітка, не провал
    img = fresh()
    p_lucz_all_not_current(img)
    f = failed(mod.run_checks(img))
    if f:
        bad.append("LUCZ «Всі канали» не поточна зона: мала бути примітка, а не провал (%s)" % sorted(f))
    else:
        notes = " ".join(" ".join(c.notes) for c in mod.run_checks(img))
        if "зона не поточна" not in notes:
            bad.append("LUCZ «Всі канали» не поточна зона: нема примітки")
    return bad


# ----------------------------------------------------------------------------------------------------------------------
#  Z0: адреси
# ----------------------------------------------------------------------------------------------------------------------

def test_z0_addresses():
    check(cint.ADDR_VFO == (ve.vfo_addr(0), ve.vfo_addr(1)) == (0x7590, 0x75C8), "Z0: адреси VFO збігаються з vfo_edit")
    check((cint.LUCZ_ADDR, cint.LUCZ_BYTES, cint.LUCZ_ALL_SLOT, cint.SETTINGS_EE_ADDR) == (sc.LUCZ_ADDR, sc.LUCZ_BYTES, sc.LUCZ_ALL_SLOT, sc.SETTINGS_EE_ADDR),
          "Z0: LUCZ і налаштування збігаються з selfcheck")
    check(cint.CHANNELS_MAX == 1024, "Z0: каналів 1024")
    check(cdf.CALIB == (0x10000, 0x11000), "Z0: калібрування 0x10000..0x10FFF")
    check(cdf.CHAN_FIELDS[-1][2] == cc.CH_SIZE == cl.CP_CHANNEL_SIZE == 56, "Z0: запис каналу 56 Б, таблиця полів його покриває")
    cover = set()
    for _n, lo, hi in cdf.CHAN_FIELDS:
        cover.update(range(lo, hi))
    for off, label in ((cc.O_GROUP, "TG-список"), (cc.O_APRS, "APRS"), (cc.O_CONTACT, "контакт"), (cc.O_CONTACT + 1, "контакт (2-й байт)"), (cc.O_MODE, "режим")):
        check(off in cover, "Z0: поле «%s» (зсув %d) є в таблиці різниці" % (label, off))
    try:
        with open(CODEPLUG_H, encoding="utf-8", errors="replace") as f:
            h = f.read()
        m = re.search(r"#define\s+CODEPLUG_ADDR_LUCZ\s+(0x[0-9A-Fa-f]+)", h)
        check(m is not None and int(m.group(1), 16) == cint.LUCZ_ADDR, "Z0: LUCZ збігається з codeplug.h (%s)" % (m.group(1) if m else "не знайдено"))
    except OSError as e:
        print("test_r45: codeplug.h не прочитано (%s) -- звірку LUCZ пропущено" % e)
    check(fresh().zone_format() == 80, "Z0: фікстура має зони по 80 каналів")


# ----------------------------------------------------------------------------------------------------------------------
#  Z1: перевірки V1
# ----------------------------------------------------------------------------------------------------------------------

def test_z1_checks():
    bad = defect_suite(cint)
    for b in bad:
        check(False, "Z1: " + b)
    # кожна перевірка рапортує лічильник
    for c in cint.run_checks(fresh()):
        check(c.checked >= 0 and ("перевірено %d" % c.checked) in c.summary() and "проблем: 0" in c.summary(), "Z1: підсумок %s: %s" % (c.cid, c.summary()))
    ch = {c.cid: c for c in cint.run_checks(fresh())}
    check(ch["V1.1"].checked == 7 and ch["V1.2"].checked == 3 and ch["V1.3"].checked == 2 and ch["V1.6"].checked == 2 and ch["V1.7"].checked == 4,
          "Z1: лічильники на справній фікстурі: %s" % {k: v.checked for k, v in ch.items()})
    # проблем багато -- місця обмежені, решта лічильником
    img = fresh()
    set_zone_vals(img, 5, list(range(600, 640)))
    f = failed(cint.run_checks(img))
    check("V1.1" in f and len(f["V1.1"].problems) == 40 and "і ще 32" in f["V1.1"].places(), "Z1: 40 висячих посилань -- 8 місць і «і ще 32»")
    # V3.1: підказка є для кожної перевірки, що провалилась, і тільки для них; автовиправлення нема
    img = fresh()
    p_hole(img)
    p_vfo(img)
    hints = cint.hint(cint.run_checks(img))
    check(len(hints) == 2 and hints[0].startswith("V1.2") and hints[1].startswith("V1.6") and any("CPS" in h for h in hints), "Z1: V3.1 підказки: %r" % hints)
    check(cint.hint(cint.run_checks(fresh())) == [], "Z1: справному кодплагу підказки не потрібні")
    for cid, text in cint.HINTS.items():
        check(("CPS" in text or "рації" in text) and len(text) > 40, "Z1: підказка %s змістовна" % cid)
    # лише читання: образ не змінився
    img = fresh()
    snap = (bytes(img.eeprom), bytes(img.flash))
    p_hole(img)
    snap = (bytes(img.eeprom), bytes(img.flash))
    cint.run_checks(img)
    check((bytes(img.eeprom), bytes(img.flash)) == snap, "Z1: перевірки образу не змінюють")
    # кодплаг без налаштувань/LUCZ/VFO (як стоковий, свіжий): це примітки, а не провали
    spi = t38.make_spi()
    cp, _ = tc.codeplug_of(spi)
    bare = cc.Image.from_codeplug(cp)
    chk = cint.run_checks(bare)
    check(not failed(chk), "Z1: кодплаг без налаштувань/LUCZ/VFO -- без провалів: %s" % sorted(failed(chk)))
    check(any("не записані" in n for c in chk for n in c.notes) and any("LUCZ" in n for c in chk for n in c.notes), "Z1: відсутність налаштувань/LUCZ названо в примітках")
    # порожній кодплаг (усе 0xFF)
    empty = cc.Image(bytearray(b"\xff" * len(bare.eeprom)), bytearray(b"\xff" * len(bare.flash)), bare.base)
    try:
        chk = cint.run_checks(empty)
        check(len(chk) == 8, "Z1: порожній образ: усі 8 перевірок відпрацювали")
    except Exception as e:  # noqa: BLE001
        check(False, "Z1: порожній образ валить перевірки: %r" % e)


def mutate(src, old, new):
    check(src.count(old) == 1, "Z1: мутант: шаблон «%s» має зустрічатися рівно раз (зустрівся %d)" % (old[:50], src.count(old)))
    mod = types.ModuleType("cp_integrity_mut")
    mod.__file__ = cint.__file__
    exec(compile(src.replace(old, new), "cp_integrity_mut", "exec"), mod.__dict__)
    return mod


MUTANTS = [
    ("V1.1 не бачить висячого посилання", "elif n not in m.chan:\n                c.problems.append(\"%s, позиція %d: канал №%d поза маскою", "elif False:\n                c.problems.append(\"%s, позиція %d: канал №%d поза маскою"),
    ("V1.1 вважає все висячим", "elif n not in m.chan:\n                c.problems.append(\"%s, позиція %d: канал №%d поза маскою", "elif True:\n                c.problems.append(\"%s, позиція %d: канал №%d поза маскою"),
    ("V1.2 діри не бачить", "if z[\"tail\"]:", "if False:"),
    ("V1.3 стертий контакт проходить", "elif k not in m.contacts:\n            c.problems.append(\"%s: контакт №%d стертий", "elif False:\n            c.problems.append(\"%s: контакт №%d стертий"),
    ("V1.3 перевіряє й аналогові", "if not m.digital(rec):\n            analog_refs += 1 if k else 0\n            continue", "if False:\n            continue"),
    ("V1.4 неіснуючий список проходить", "elif g not in m.groups:", "elif False:"),
    ("V1.4 учасників списків не перевіряє", "if v > cl.CP_CONTACTS_MAX or v not in m.contacts:", "if False:"),
    ("V1.5 слот APRS за межами проходить", "if a > cc.APRS_MAX or a > m.aprs_count:", "if False:"),
    ("V1.6 VFO з контактом проходить", "if ct and (ct > cl.CP_CONTACTS_MAX or ct not in m.contacts):", "if False:"),
    ("V1.6 VFO зі списком проходить", "if g and (g > cl.CP_RXGROUPS_MAX or g not in m.groups):", "if False:"),
    ("V1.7 запис без змісту проходить", "why = _meaningful(m.chan[n])\n        if why:", "why = []\n        if why:"),
    ("V1.7 згадок поза маскою не бачить", "if n and 1 <= n <= CHANNELS_MAX and n not in m.chan:", "if False:"),
    ("V1.7 LUCZ «Всі канали» не бачить", "if 1 <= n <= CHANNELS_MAX and n not in m.chan:\n            mentions", "if False:\n            mentions"),
    ("V1.8 зона без назви проходить", "if z[\"raw0\"] in (0x00, 0xFF):", "if False:"),
    ("V1.8 поточна зона не перевіряється", "if not (0 <= cz <= len(m.zones)):", "if False:"),
    ("V1.8 позиція LUCZ не перевіряється", "if cnt and idx >= cnt:", "if False:"),
    ("V1.8 «Всі канали» не поточна теж провал", "if cz is not None and cz == len(m.zones):\n                c.problems.append(msg + \" (і це ПОТОЧНА зона)\")\n            else:\n                c.notes.append(msg + \" (зона не поточна)\")",
     "c.problems.append(msg + \" (і це ПОТОЧНА зона)\")"),
]


def test_z1_mutants():
    with open(cint.__file__, encoding="utf-8") as f:
        src = f.read()
    caught = 0
    for name, old, new in MUTANTS:
        try:
            bad = defect_suite(mutate(src, old, new))
        except Exception as e:  # noqa: BLE001 -- мутант, що валиться, теж «спійманий»
            bad = ["мутант впав: %r" % e]
        if bad:
            caught += 1
        else:
            check(False, "Z1: мутант НЕ спійманий: %s" % name)
    print("test_r45: мутантів V1 спіймано %d з %d" % (caught, len(MUTANTS)))


# ----------------------------------------------------------------------------------------------------------------------
#  Z2/Z3: різниця
# ----------------------------------------------------------------------------------------------------------------------

GUARDS = {"калібрування": "a" * 64, "таблиця ключів AES": "b" * 64, "тема (день)": "c" * 64, "тема (ніч)": "d" * 64}
NOW = datetime.datetime(2026, 10, 30, 12, 34)


def st(img, guards=None):
    return cdf.capture(img, guards if guards is not None else GUARDS, NOW)


def diff(before_img, after_img, expected=None, g_before=None, g_after=None):
    return cdf.compare(st(before_img, g_before), st(after_img, g_after), expected)


def test_z2_diff():
    a = fresh()
    # нічого не змінилось
    d = diff(a, fresh())
    check(not d.any_change and d.items() == set() and "не змінився" in d.lines()[0] and not d.protected_changed, "Z2: однакові знімки -- «не змінився»: %r" % d.lines())
    check(d.bytes_ee == 0 and d.bytes_fl == 0 and not d.sectors_ee and not d.sectors_fl, "Z2: однакові знімки -- 0 байтів і секторів")
    # один канал в EEPROM (№3) -- рівно він
    b = fresh()
    edit_chan(b, 3, lambda r: r.__setitem__(slice(cc.O_RX, cc.O_RX + 4), bytes([0x25, 0x00, 0x00, 0x47])))
    d = diff(a, b)
    check(d.items() == {("канал змінено", 3)}, "Z2: змінено канал №3 (EEPROM) -- у різниці рівно він: %r" % d.items())
    check(d.channels_changed and d.channels_changed[0][0] == 3 and d.channels_changed[0][2] == ["частота прийому"], "Z2: названо поле «частота прийому»: %r" % d.channels_changed)
    check(d.sectors_ee and not d.sectors_fl and 0 < d.bytes_ee <= 4 and d.bytes_fl == 0, "Z2: змінено лише EEPROM, байтів ≤4: %d/%d" % (d.bytes_ee, d.bytes_fl))
    check(not d.protected_changed and not d.unexplained and not d.consequences and not d.hidden, "Z2: охоронюване, неопоясненого, наслідків нема")
    check(any("№3" in x for x in d.lines()), "Z2: у тексті названо канал №3")
    # один канал у флеші (№130) -- рівно він; змінено сектор флеша, не EEPROM
    b = fresh()
    edit_chan(b, 130, lambda r: r.__setitem__(cc.O_POWER, (r[cc.O_POWER] + 1) & 255))
    d = diff(a, b)
    check(d.items() == {("канал змінено", 130)} and d.sectors_fl and not d.sectors_ee and d.bytes_ee == 0, "Z2: канал №130 (флеш): %r" % d.items())
    # Expected: названий канал -- не несподіваний; інший -- несподіваний
    b = fresh()
    edit_chan(b, 3, lambda r: r.__setitem__(cc.O_POWER, (r[cc.O_POWER] + 1) & 255))
    edit_chan(b, 1, lambda r: r.__setitem__(cc.O_SQL, (r[cc.O_SQL] + 1) & 255))
    d = diff(a, b, cdf.Expected(channels=[3]))
    check(d.items() == {("канал змінено", 1), ("канал змінено", 3)} and len(d.unexpected) == 1 and "№1" in d.unexpected[0], "Z2: Expected=[3]: несподіваний лише №1: %r" % d.unexpected)
    d = diff(a, b, cdf.Expected(channels=[1, 3]))
    check(not d.unexpected and d.expected_given, "Z2: Expected=[1,3]: несподіваного нема")
    d = diff(a, b)
    check(not d.expected_given and not d.unexpected, "Z2: без Expected несподіване не оцінюється")
    # Expected.parse
    check(cdf.Expected.parse("", "", "") is None and cdf.Expected.parse("5, 7", "", "").channels == {5, 7}, "Z2: Expected.parse")
    ex = cdf.Expected.parse("1 2;3", "Київ; Local", "4")
    check(ex.channels == {1, 2, 3} and ex.zones == {"київ", "local"} and ex.contacts == {4}, "Z2: Expected.parse: роздільники %r" % ((ex.channels, ex.zones, ex.contacts),))
    try:
        cdf.Expected.parse("abc", "", "")
        check(False, "Z2: Expected.parse(abc) має відмовити")
    except ValueError:
        pass

    # видалено канал №130 разом із зоною, що його містила («Папуга»: [1,2,3,130])
    b = fresh()
    b.set_channel_in_use(130, False)
    b.set_channel_rec(130, b"\xff" * cl.CP_CHANNEL_SIZE)
    set_zone_vals(b, 5, [1, 2, 3])
    d = diff(a, b, cdf.Expected(channels=[130], zones=["Папуга"]))
    check(d.items() == {("канал видалено", 130), ("зона змінена", 5)}, "Z2: видалення каналу: %r" % d.items())
    check(not d.unexpected and not d.hidden, "Z2: видалення каналу, що очікувалось: несподіваного нема, запис 0xFF не «прихована зміна»: %r %r" % (d.unexpected, d.hidden))
    # канал видалено, але зона його ще містить (висяче посилання) -- у зоні «змінено» нема, діра лишилась тим, що ловить V1
    b2 = fresh()
    b2.set_channel_in_use(130, False)
    d = diff(a, b2)
    check(d.items() == {("канал видалено", 130)}, "Z2: канал видалено без чистки зони: %r" % d.items())
    # зона з цим каналом після видалення каналу й чистки: наслідок видалення відокремлено
    b3 = fresh()
    b3.set_channel_in_use(130, False)
    set_zone_vals(b3, 5, [1, 2, 3])
    d = diff(a, b3)
    check(d.consequences and any("зона «Папуга»" in c and "№130" in c for c in d.consequences), "Z2: чистка зони після видалення каналу -- наслідок: %r" % d.consequences)
    # видалено контакт №2 (на нього вказує канал №3) з каскадом R44: канал 3 -> «Немає»
    b = fresh()
    erase_contact(b, 2)
    edit_chan(b, 3, lambda r: ref16(r, cc.O_CONTACT, 0))
    d = diff(a, b, cdf.Expected(contacts=[2]))
    check(d.items() == {("контакт видалено", 2)} and not d.unexpected, "Z2: видалення контакту з каскадом: %r / %r" % (d.items(), d.unexpected))
    check(any("канал №3" in c and "контакт №2" in c and "Немає" in c for c in d.consequences), "Z2: каскад у каналі №3 названо наслідком: %r" % d.consequences)
    check(any("Наслідки" in x for x in d.lines()) and ("канал змінено", 3) not in d.items(), "Z2: наслідок не рахується окремою правкою каналу")
    # а якщо канал змінився СВОЄЮ правкою разом з контактом -- це вже правка
    b = fresh()
    erase_contact(b, 2)
    edit_chan(b, 3, lambda r: (ref16(r, cc.O_CONTACT, 0), r.__setitem__(cc.O_POWER, (r[cc.O_POWER] + 1) & 255)))
    d = diff(a, b, cdf.Expected(contacts=[2]))
    check(("канал змінено", 3) in d.items() and any("№3" in u for u in d.unexpected), "Z2: канал №3 змінено ще й власною правкою -- несподіване: %r" % d.unexpected)
    # видалено зону
    b = fresh()
    b.clear_zone(1)
    d = diff(a, b, cdf.Expected(zones=["Local"]))
    check(d.items() == {("зона видалена", 1)} and not d.unexpected, "Z2: видалення зони: %r" % d.items())
    d = diff(a, b, cdf.Expected(zones=["Інша"]))
    check(len(d.unexpected) == 1 and "«Local»" in d.unexpected[0], "Z2: зона видалена, а очікувалась інша: %r" % d.unexpected)
    # зона: додано/вийнято канал; перейменовано
    b = fresh()
    set_zone_vals(b, 1, [2, 1])
    d = diff(a, b)
    check(d.items() == {("зона змінена", 1)} and "додано канали №1" in d.zones_changed[0][2][0], "Z2: у зону додано канал: %r" % d.zones_changed)
    b = fresh()
    rec = bytearray(zone_rec(b, 1))
    rec[:5] = b"NewZ_"
    b.set_zone(1, bytes(rec))
    d = diff(a, b)
    check(d.items() == {("зона змінена", 1)} and "назву змінено" in d.zones_changed[0][2][0], "Z2: зону перейменовано: %r" % d.zones_changed)
    # новий контакт, змінений контакт
    b = fresh()
    rec = bytearray(b.contacts()[0][1])
    rec[16] ^= 1
    b.set_contact(0, bytes(rec))
    d = diff(a, b)
    check(d.items() == {("контакт змінено", 1)} and d.contacts_changed[0][2] == ["номер"], "Z2: контакт №1 змінено (номер): %r" % d.contacts_changed)
    b = fresh()
    b.set_contact(20, b.contacts()[0][1])
    d = diff(a, b)
    check(d.items() == {("контакт додано", 21)}, "Z2: контакт додано: %r" % d.items())
    # списки прийому, APRS: окремо від каналів/зон/контактів -- завжди несподівані, якщо вказано Expected
    b = fresh()
    b.clear_group_len(0)
    d = diff(a, b, cdf.Expected(channels=[1]))
    check(d.items() == {("TG-список", 1)} and d.unexpected, "Z2: зник TG-список №1: %r %r" % (d.items(), d.unexpected))
    # VFO і службові ділянки не мішають: змінений VFO -- окремо, не «змінений канал»
    b = fresh()
    b.eeprom[cint.ADDR_VFO[0] + 16] ^= 1
    d = diff(a, b, cdf.Expected(channels=[1]))
    check(d.vfo_changed == ["VFO A"] and d.items() == set() and not d.unexpected, "Z2: VFO змінилось -- окремо: %r %r" % (d.vfo_changed, d.items()))
    b = fresh()
    b.eeprom[cint.SETTINGS_EE_ADDR + 100] ^= 1
    d = diff(a, b, cdf.Expected(channels=[1]))
    check(d.items() == set() and d.service and not d.unexpected, "Z2: налаштування рації -- службова ділянка, не несподіване: %r" % d.service)
    # байти, яких ніхто не пояснив (невідома ділянка EEPROM)
    b = fresh()
    b.eeprom[0x5800] ^= 0xFF
    d = diff(a, b)
    check(d.unexplained and d.unexplained[0][0] == 0x5800 and d.any_change, "Z2: неопоясненого байта названо: %r" % d.unexplained)
    # запис каналу поза маскою
    b = fresh()
    b.set_channel_rec(600, b"\x01" * cl.CP_CHANNEL_SIZE)
    d = diff(a, b)
    check(d.hidden == ["канал №600"] and d.items() == set(), "Z2: запис поза маскою -- «прихована» зміна, не канал: %r" % d.hidden)

    # файл стану: коло, пошкодження
    tmp = tempfile.mkdtemp(prefix="r45_")
    p = os.path.join(tmp, "s.zip")
    s1 = st(a)
    cdf.save_state(s1, p)
    back = cdf.load_state(p)
    check(back.eeprom == s1.eeprom and back.flash == s1.flash and back.guards == s1.guards and back.created == s1.created and back.base == s1.base, "Z2: файл стану: коло збігається")
    check(not diff(a, back.image()).any_change, "Z2: образ зі стану збігається з вихідним")
    try:
        cdf.save_state(s1, p)
        check(False, "Z2: існуючий файл стану не перезаписується")
    except FileExistsError:
        pass
    bad = os.path.join(tmp, "bad.zip")
    with zipfile.ZipFile(p) as zi, zipfile.ZipFile(bad, "w") as zo:
        for n in zi.namelist():
            data = zi.read(n)
            if n == "eeprom.bin":
                data = bytes([data[0] ^ 1]) + data[1:]
            zo.writestr(n, data)
    for label, path in (("пошкоджений", bad), ("не zip", __file__), ("нема файла", os.path.join(tmp, "нема.zip"))):
        try:
            cdf.load_state(path)
            check(False, "Z2: %s файл стану має відхилятись" % label)
        except cdf.StateError as e:
            check(str(e), "Z2: %s: порожнє повідомлення" % label)
    # у файлі стану нема секретів: у guards лише хеші, і нічого, схожого на ключ
    with zipfile.ZipFile(p) as z:
        man = z.read("manifest.json").decode("utf-8")
    check(all(re.fullmatch(r"[0-9a-f]{64}", v) for v in s1.guards.values()), "Z2: у охоронюваному лише SHA-256")


def test_z3_protected():
    a = fresh()
    # калібрування: один байт -- голосно
    b = fresh()
    b.eeprom[0x10000] ^= 1
    d = diff(a, b)
    prot = {n: ch for n, ch, _t in d.protected}
    cal = [p for p in d.protected if p[0].startswith("калібрування")][0]
    check(cal[1] is True and "1" in cal[2], "Z3: зміна байта калібрування названа: %r" % (cal,))
    check(d.calibration_bytes == 1 and d.protected_changed and prot, "Z3: calibration_bytes=1, protected_changed не порожній")
    check(d.items() == set() and not d.unexplained, "Z3: решта кодплага не зачеплена")
    # калібрування в кінці сектора
    b = fresh()
    b.eeprom[0x10FFF] ^= 1
    check(diff(a, b).protected_changed, "Z3: останній байт калібрування")
    # байт ПІСЛЯ сектора калібрування -- не калібрування
    b = fresh()
    b.eeprom[0x11000] ^= 1
    d = diff(a, b)
    check(not d.protected_changed and d.calibration_bytes == 0, "Z3: 0x11000 не калібрування")
    # хеші ключів AES / теми / база: змінилися -- голосно; однакові -- гаразд; не прочитано -- не порівнюємо
    g2 = dict(GUARDS)
    g2["таблиця ключів AES"] = "e" * 64
    d = diff(a, a, g_after=g2)
    ch = [p for p in d.protected if p[0] == "таблиця ключів AES"][0]
    check(ch[1] is True and "ЗМІНИВСЯ" in ch[2] and len(d.protected_changed) == 1, "Z3: змінився хеш таблиці ключів: %r" % (ch,))
    check(not d.any_change, "Z3: кодплаг при цьому не змінився (хеш -- про інше)")
    g3 = dict(GUARDS)
    g3["тема (день)"] = "не прочитано: збій"
    d = diff(a, a, g_after=g3)
    th = [p for p in d.protected if p[0] == "тема (день)"][0]
    check(th[1] is None and not d.protected_changed, "Z3: «не прочитано» -- не порівнюємо й не вважаємо зміною: %r" % (th,))
    g4 = {k: v for k, v in GUARDS.items() if k != "тема (ніч)"}
    d = diff(a, a, g_after=g4)
    check([p for p in d.protected if p[0] == "тема (ніч)"][0][1] is None, "Z3: охоронюваного нема в одному зі знімків -- не порівняно")
    d = diff(a, a)
    check(all(p[1] is False for p in d.protected) and len(d.protected) == 1 + len(GUARDS), "Z3: нічого не змінилось -- усе охоронюване «однакове»")
    # образ EEPROM коротший за 0x11000 -- не падає
    short = cc.Image(bytearray(a.eeprom[:0x10800]), bytearray(a.flash), a.base)
    try:
        d = cdf.compare(st(short), st(short))
        check([p for p in d.protected if p[0].startswith("калібрування")][0][1] is None, "Z3: короткий образ: калібрування «не порівняно»")
    except Exception as e:  # noqa: BLE001
        check(False, "Z3: короткий образ валить порівняння: %r" % e)


# ----------------------------------------------------------------------------------------------------------------------
#  Z4: великий кодплаг
# ----------------------------------------------------------------------------------------------------------------------

def big_image(channels=900, per_zone=80):
    img = fresh()
    tpl_dmr, tpl_fm = bytearray(img.channel_rec(3)), bytearray(img.channel_rec(2))
    for n in range(1, channels + 1):
        rec = bytearray(tpl_dmr if n % 2 else tpl_fm)
        name = ("Ch%d" % n).encode("ascii")
        rec[:16] = name + b"\xff" * (16 - len(name))
        if n % 2:
            ref16(rec, cc.O_CONTACT, 1 + n % 5)
            rec[cc.O_GROUP] = 1 if n % 3 else 5
            rec[cc.O_APRS] = 0
        else:
            ref16(rec, cc.O_CONTACT, 0)
            rec[cc.O_GROUP] = 0
        img.set_channel_in_use(n, True)
        img.set_channel_rec(n, bytes(rec))
    for slot in range(1024):
        if img.fl(cl.CP_ADDR_CONTACTS + slot * cl.CP_CONTACT_SIZE, 1)[0] != 0xFF:
            continue
        rec = bytearray(cc_contact_tpl(img))
        nm = ("TG%d" % (slot + 1)).encode("ascii")
        rec[:16] = nm + b"\xff" * (16 - len(nm))
        img.set_contact(slot, bytes(rec))
    for bit in range(cl.CP_ZONES_MAX):
        nm = ("Zone%d" % bit).encode("ascii")
        rec = bytearray(16 + 2 * img.zone_format())
        rec[:16] = nm + b"\xff" * (16 - len(nm))
        vals = [1 + (bit * 7 + k) % channels for k in range(per_zone)]
        rec[16:] = struct.pack("<%dH" % img.zone_format(), *vals)
        img.set_zone(bit, bytes(rec))
    return img


def cc_contact_tpl(img):
    return img.contacts()[1][1]


def test_z4_large():
    img = big_image()
    n_ch, n_z, n_k = len(img.channels()), len(img.zones()), len(img.contacts())
    check(n_ch == 900 and n_z == cl.CP_ZONES_MAX and n_k >= 1000, "Z4: великий кодплаг зібрано: %d каналів, %d зон, %d контактів" % (n_ch, n_z, n_k))
    t0 = time.time()
    checks = cint.run_checks(img)
    dt = time.time() - t0
    TIMES["V1 на великому кодплазі"] = dt
    f = failed(checks)
    # у зразкових зонах канали зі списку лежать у межах 1..900 -- усе в масці; контакти 1..5 існують
    check(not f, "Z4: великий справний кодплаг -- без провалів: %s" % {k: v.places(3) for k, v in f.items()})
    check(checks[0].checked == cl.CP_ZONES_MAX * 80 and checks[6].checked == 900, "Z4: лічильники: %s" % [c.checked for c in checks])
    check(dt < 20, "Z4: V1 на 900 каналах і 68 зонах за %.2f с (поріг 20 с)" % dt)
    # вада у великому кодплазі називається серед сотень
    bad = cc.Image(bytearray(img.eeprom), bytearray(img.flash), img.base)
    set_zone_vals(bad, 40, [10, 20, 1000, 30])
    f = failed(cint.run_checks(bad))
    check("V1.1" in f and "«Zone40»" in f["V1.1"].places() and "позиція 3" in f["V1.1"].places() and "№1000" in f["V1.1"].places(),
          "Z4: вада у великому кодплазі названа: %s" % (f["V1.1"].places() if "V1.1" in f else f.keys()))
    # порівняння двох великих знімків
    other = cc.Image(bytearray(img.eeprom), bytearray(img.flash), img.base)
    edit_chan(other, 700, lambda r: r.__setitem__(cc.O_POWER, (r[cc.O_POWER] + 1) & 255))
    s1, s2 = st(img), st(other)
    t0 = time.time()
    d = cdf.compare(s1, s2)
    dt2 = time.time() - t0
    TIMES["порівняння знімків (900 каналів)"] = dt2
    check(d.items() == {("канал змінено", 700)}, "Z4: у великому кодплазі змінено один канал -- у різниці рівно він: %r" % d.items())
    check(dt2 < 20, "Z4: порівняння за %.2f с (поріг 20 с)" % dt2)
    tmp = tempfile.mkdtemp(prefix="r45_big_")
    t0 = time.time()
    p = cdf.save_state(s1, os.path.join(tmp, "big.zip"))
    cdf.load_state(p)
    TIMES["запис і читання файла стану"] = time.time() - t0
    TIMES["розмір файла стану, КіБ"] = os.path.getsize(p) / 1024.0
    print("test_r45: Z4 час: " + "; ".join("%s -- %.2f" % (k, v) for k, v in TIMES.items()))


# ----------------------------------------------------------------------------------------------------------------------
#  Z5: сценарії майстра на підробленій рації
# ----------------------------------------------------------------------------------------------------------------------

def spi_edit(spi, fn):
    """Змінює кодплаг у образі SPI підробленої рації: прочитати -> Image -> fn -> записати назад (так само, як t38.make_spi)."""
    cp, _ = tc.codeplug_of(bytes(spi))
    img = cc.Image.from_codeplug(cp)
    fn(img)
    spi[:cl.EEPROM_BACKUP_LEN] = bytes(img.eeprom)
    rng = cl.flash_backup_range()
    spi[rng["raw_start"]:rng["raw_start"] + rng["length"]] = bytes(img.flash)


def rich_spi():
    spi = bytearray(t38.make_spi())
    spi_edit(spi, add_runtime)
    return spi


def ctx_for(link, state_path=None, expected=None):
    ctx = t38.make_ctx(link)
    ctx.state_path = state_path
    ctx.expected = expected
    return ctx


def run_ids(ctx, ids):
    with tcr.Unlocked():
        return sc.run(ctx, ids)


def res_of(rep, sid):
    return next(r for r in rep.results if r.scenario.sid == sid)


def step_names(res):
    return [s.name for s in res.steps]


def test_z5_scenarios():
    # --- реєстр ---
    s61, s62, s63 = sc.SCENARIO_BY_ID["S6.1"], sc.SCENARIO_BY_ID["S6.2"], sc.SCENARIO_BY_ID["S6.3"]
    check(all(s.risk == sc.RISK_READ for s in (s61, s62, s63)), "Z5: S6.* лише читання")
    check(s61 in sc.SCENARIOS and s61.default_on and not s61.writes, "Z5: S6.1 -- звичайний читальний сценарій із галочкою")
    check(s62 not in sc.SCENARIOS and s63 not in sc.SCENARIOS and s62 in sc.ACTIONS and s63 in sc.ACTIONS and not s62.default_on and not s63.default_on,
          "Z5: S6.2/S6.3 -- дії-кнопки, без галочок")
    ordered = sc.order(["S4.1", "S6.3", "S6.2", "S6.1"])
    check([s.sid for s in ordered][-1] == "S4.1" and [s.sid for s in ordered][:3] == ["S6.1", "S6.2", "S6.3"], "Z5: порядок: читальні (S6.1, S6.2, S6.3) перед писальним: %r" % [s.sid for s in ordered])

    # --- S6.1 на справній рації ---
    spi = rich_spi()
    radio, link = t38.make_radio(spi)
    ctx = ctx_for(link)
    rep = run_ids(ctx, ["S6.1"])
    r = res_of(rep, "S6.1")
    names = step_names(r)
    check(r.status == sc.PASS, "Z5: S6.1 на справній рації: %r" % t38.failed_names(r))
    for i in range(1, 9):
        check(any(n.startswith("V1.%d " % i) and "перевірено" in n and "проблем: 0" in n for n in names), "Z5: S6.1 крок V1.%d з лічильниками" % i)
    check(not radio.writes_seen and all(rq[0] in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10) for rq in radio.requests), "Z5: S6.1 лише читає (жодної команди запису)")
    check(not r.notes or not any("Як виправити" in n for n in r.notes), "Z5: справній рації підказок нема")

    # --- S6.1 з вадами: називає місце, дає підказку, не виправляє ---
    spi = rich_spi()
    before = bytes(spi)
    spi_edit(spi, lambda img: (set_zone_vals(img, 0, [1, 3, 777]), erase_contact(img, 2)))
    mid = bytes(spi)
    radio, link = t38.make_radio(spi)
    rep = run_ids(ctx_for(link), ["S6.1"])
    r = res_of(rep, "S6.1")
    bad_names = t38.failed_names(r)
    check(r.status == sc.FAIL and any(n.startswith("V1.1") for n in bad_names) and any(n.startswith("V1.3") for n in bad_names), "Z5: S6.1 з вадами провалена: %r" % bad_names)
    got = " | ".join(str(s.got) for s in r.failed_steps())
    check("«Київ»" in got and "позиція 3" in got and "№777" in got and "канал №3" in got and "контакт №2" in got, "Z5: у кроках названо зону, позицію, канал, контакт: %s" % got[:300])
    check(any(n.startswith("Як виправити. V1.1") and "CPS" in n for n in r.notes) and any("нічого не виправляє" in n for n in r.notes), "Z5: підказка «як виправити» через CPS є: %r" % r.notes[:3])
    check(bytes(radio.spi) == mid and not radio.writes_seen, "Z5: S6.1 нічого не виправила й не записала")
    check(before != mid, "Z5: (контроль) вади справді підкладено")
    md = sc.render_markdown(rep)
    check("Що не пройшло" in md and "V1.1" in md and "№777" in md and "Як виправити" in md, "Z5: у звіті є «Що не пройшло» з місцем і підказкою")

    # --- S6.2 / S6.3 ---
    spi = rich_spi()
    radio, link = t38.make_radio(spi)
    ctx = ctx_for(link)
    # без стану
    rep = run_ids(ctx, ["S6.3"])
    r = res_of(rep, "S6.3")
    check(r.status == sc.SKIPPED and "Запам'ятати стан" in (r.skip_reason or ""), "Z5: S6.3 без стану пропущено з поясненням: %r" % (r.skip_reason,))
    # запам'ятати
    rep = run_ids(ctx, ["S6.2"])
    r = res_of(rep, "S6.2")
    check(r.status == sc.PASS and ctx.state_path and os.path.isfile(ctx.state_path), "Z5: S6.2 створив файл стану: %r" % t38.failed_names(r))
    check(os.path.dirname(ctx.state_path) == ctx.out_dir and os.path.basename(ctx.state_path).startswith("selfcheck_state_") and ctx.state_path.endswith(".zip"),
          "Z5: файл стану лежить поруч зі звітом: %s" % ctx.state_path)
    st0 = cdf.load_state(ctx.state_path)
    check(st0.eeprom == bytes(radio.spi[:cl.EEPROM_BACKUP_LEN]), "Z5: файл стану містить поточний EEPROM")
    for name in ("калібрування", "таблиця ключів AES", "тема (ден", "тема (ніч"):
        check(any(k.startswith(name) for k in st0.guards), "Z5: у стані є хеш «%s»: %s" % (name, sorted(st0.guards)))
    from test_cps_restore import QK_START  # noqa: F401  (швидкі клавіші -- не ключі)
    import aes_keys_backup as akb
    keys = bytes(radio.spi[akb.KEYS_START:akb.KEYS_START + akb.KEYS_LEN])
    secret = [keys[i:i + 16] for i in range(0, len(keys), 16) if len(set(keys[i:i + 16])) > 2][:3]
    with open(ctx.state_path, "rb") as f:
        raw = f.read()
    with zipfile.ZipFile(ctx.state_path) as z:
        blob = b"".join(z.read(n) for n in z.namelist())
    check(secret and not any(s in blob for s in secret) or not secret, "Z5: у файлі стану нема шматків таблиці ключів AES")
    check(not radio.writes_seen, "Z5: S6.2 лише читає")
    sp = ctx.state_path
    # порівняти: нічого не змінилось
    rep = run_ids(ctx, ["S6.3"])
    r = res_of(rep, "S6.3")
    check(r.status == sc.PASS and any("не змінився" in n for n in r.notes), "Z5: S6.3 без змін: %r %r" % (t38.failed_names(r), r.notes[:2]))
    check(any(s.name.startswith("V2.3 калібрування") for s in r.steps), "Z5: S6.3 має крок про калібрування")
    check(not ctx.loud, "Z5: без змін -- без голосних попереджень")
    # змінили канал №3 -- у різниці рівно він
    spi_edit(radio.spi, lambda img: edit_chan(img, 3, lambda rec: rec.__setitem__(cc.O_POWER, (rec[cc.O_POWER] + 1) & 255)))
    rep = run_ids(ctx, ["S6.3"])
    r = res_of(rep, "S6.3")
    notes = "\n".join(r.notes)
    check(r.status == sc.PASS and "Канали, що змінились" in notes and "№3" in notes and "потужність" in notes, "Z5: S6.3 після правки каналу №3: %r" % r.notes[:6])
    check("№1 " not in notes.split("Канали, що змінились")[1].split("Змінено байтів")[0], "Z5: інших каналів у різниці нема")
    check(any("V2.3 інші канали" in s.name for s in r.steps if s.ok is None), "Z5: без Expected -- довідка «не вказано, що саме робилось»")
    # Expected: правили №3 -- гаразд; не очікували нічого про №3 -- несподіване
    ctx.expected = cdf.Expected(channels=[3])
    r = res_of(run_ids(ctx, ["S6.3"]), "S6.3")
    check(r.status == sc.PASS and any(s.name.startswith("V2.3 інші канали") and s.ok for s in r.steps), "Z5: Expected=[3] -- гаразд: %r" % t38.failed_names(r))
    ctx.expected = cdf.Expected(channels=[7])
    r = res_of(run_ids(ctx, ["S6.3"]), "S6.3")
    check(r.status == sc.FAIL and any(s.name.startswith("V2.3 інші канали") and not s.ok and "№3" in str(s.got) for s in r.steps), "Z5: Expected=[7] -- №3 несподіваний: %r" % t38.failed_names(r))
    ctx.expected = None
    # калібрування змінилось -- голосно
    radio.spi[0x10000] ^= 0xFF
    ctx.loud = []
    r = res_of(run_ids(ctx, ["S6.3"]), "S6.3")
    check(r.status == sc.FAIL and any(s.name.startswith("V2.3 калібрування") and not s.ok for s in r.steps), "Z5: калібрування змінилось -- FAIL: %r" % t38.failed_names(r))
    check(ctx.loud and "калібрування" in ctx.loud[0] and "ЗМІНИЛОСЬ" in ctx.loud[0], "Z5: калібрування змінилось -- ctx.shout: %r" % ctx.loud)
    rep_md = sc.render_markdown(run_ids(ctx, ["S6.3"]))
    check("калібрування" in rep_md and "НЕ ЗБІГЛОСЬ" in rep_md, "Z5: у звіті зміна калібрування видна")
    # ключ AES змінився -- хеш в охоронюваному
    radio.spi[0x10000] ^= 0xFF
    t0 = bytes(radio.spi[akb.KEYS_START:akb.KEYS_START + 4])
    radio.spi[akb.KEYS_START] ^= 0xFF
    ctx.loud = []
    r = res_of(run_ids(ctx, ["S6.3"]), "S6.3")
    aes_step = [s for s in r.steps if "ключ" in s.name.lower() or "AES" in s.name]
    check(aes_step and any(not s.ok for s in aes_step) and ctx.loud, "Z5: змінився вміст таблиці ключів AES -- голосно: %r" % [s.name for s in r.steps])
    radio.spi[akb.KEYS_START:akb.KEYS_START + 4] = t0
    check(not radio.writes_seen, "Z5: S6.3 лише читає")
    # перемкнули файл стану на пошкоджений
    bad = os.path.join(ctx.out_dir, "bad_state.zip")
    with open(bad, "wb") as f:
        f.write(b"no zip")
    ctx.state_path = bad
    r = res_of(run_ids(ctx, ["S6.3"]), "S6.3")
    check(r.status == sc.FAIL and any(s.name == "файл стану" for s in r.steps), "Z5: пошкоджений файл стану -- провал із поясненням")
    ctx.state_path = sp


def test_z5_report_timing():
    """Z4 (сценарій): час перевірки V1 іде у звіт."""
    spi = rich_spi()
    spi_edit(spi, lambda img: None)
    radio, link = t38.make_radio(spi)
    rep = run_ids(ctx_for(link), ["S6.1"])
    md = sc.render_markdown(rep)
    check("час самої перевірки" in md, "Z4: час перевірки V1 є у звіті сценарію")


# ----------------------------------------------------------------------------------------------------------------------
#  Z5: панель
# ----------------------------------------------------------------------------------------------------------------------

def test_z5_panel():
    try:
        import tkinter as tk
        r = tk.Tk()
        r.destroy()
    except Exception as e:  # noqa: BLE001
        print("test_r45: розділ UI пропущено (нема Tk/DISPLAY: %s)" % e)
        return
    import test_r36 as t36
    import layout_probe as lp
    import cps_ui.p_selfcheck as psc
    spath = os.path.join(tempfile.mkdtemp(prefix="r45_ui_"), "ui.json")
    app = t36.make_app(spath)
    old_sleep = t38.no_sleep()
    out = tempfile.mkdtemp(prefix="r45_out_")
    orig_open, orig_out = t38.cps_open_radio(), psc.output_dir
    try:
        app.show("selfcheck")
        t36.spin(app, 0.5)
        p = app.get_panel("selfcheck")
        check(isinstance(p, psc.SelfcheckPanel), "UI: панель потрібного класу")
        check("S6.1" in p.vars and "S6.2" not in p.vars and "S6.3" not in p.vars, "UI: S6.1 має галочку, S6.2/S6.3 -- кнопки, не галочки")
        check(p.vars["S6.1"].get() is True and "S6.1" in p.selected(), "UI: S6.1 типово вибрано (читальний)")
        texts = (p.remember_btn.cget("text"), p.compare_btn.cget("text"), p.pick_btn.cget("text"))
        check(texts == ("Запам'ятати стан", "Порівняти", "Вибрати файл стану..."), "UI: кнопки: %r" % (texts,))
        check("ще не запам'ятовано" in p.state_label.cget("text"), "UI: підпис без стану: %s" % p.state_label.cget("text"))
        # «Порівняти» без стану: пояснення, нічого не запускається
        p._on_compare()
        check("Спершу «Запам'ятати стан»" in p.result_label.cget("text") and not p.shell.busy, "UI: «Порівняти» без стану пояснює, що робити: %s" % p.result_label.cget("text"))
        # поля «Очікувано»
        p.exp_vars["channels"].set("5, 7")
        p.exp_vars["zones"].set("Київ; Local")
        p.exp_vars["contacts"].set("")
        ex = p._expected()
        check(ex.channels == {5, 7} and ex.zones == {"київ", "local"} and not ex.contacts, "UI: поля очікуваного читаються")
        p.exp_vars["channels"].set("п'ять")
        try:
            p._expected()
            check(False, "UI: помилка в номері має давати ValueError")
        except ValueError as e:
            check("номери" in str(e), "UI: помилка в номері пояснена: %s" % e)
        p.state_path = __file__
        p._on_compare()
        check("номери" in p.result_label.cget("text"), "UI: «Порівняти» з помилкою в полі не запускається, а пояснює")
        p.state_path = None
        p.exp_vars["channels"].set("")
        p.exp_vars["zones"].set("")
        # розкладка
        app.geometry("1024x768")
        t36.spin(app, 0.4)
        iss = lp.probe_panel(app, "selfcheck")
        if iss:
            t36.spin(app, 0.7)
            iss = lp.probe_panel(app, "selfcheck")
        check(not iss, "UI: розділ з блоком «Що змінила остання операція» не обрізаний на 1024x768: %r" % (iss[:3],))
        # робочі потоки на підробленій рації: запам'ятати -> змінити -> порівняти
        spi = rich_spi()
        radio, link = t38.make_radio(spi)
        import cps_link as cps
        cps.open_radio = lambda *a, **k: radio
        psc.output_dir = lambda: out
        p._exp = None
        with tcr.Unlocked():
            rep = p.run_worker(["S6.2"])
        p._remember_done(rep)
        check(p.state_path and os.path.isfile(p.state_path) and p.state_path.startswith(out) and "Стан запам'ятано" in p.state_label.cget("text"),
              "UI: після «Запам'ятати стан» файл є, підпис оновлено: %s" % p.state_label.cget("text"))
        spi_edit(radio.spi, lambda img: edit_chan(img, 1, lambda rec: rec.__setitem__(cc.O_POWER, (rec[cc.O_POWER] + 1) & 255)))
        p.exp_vars["channels"].set("1")
        p._exp = p._expected()
        with tcr.Unlocked():
            rep = p.run_worker(["S6.3"])
        r = res_of(rep, "S6.3")
        check(r.status == sc.PASS and any("№1" in n for n in r.notes) and any(s.name.startswith("V2.3 інші канали") and s.ok for s in r.steps),
              "UI: порівняння з панелі бачить правку каналу №1 і передає поле «Очікувано»: %r" % t38.failed_names(r))
        p._run_done(rep)
        check(rep.path and os.path.isfile(rep.path), "UI: звіт порівняння збережено")
    finally:
        t38.cps_set_open_radio(orig_open)
        psc.output_dir = orig_out
        time.sleep = old_sleep
        app.destroy()


def main():
    test_z0_addresses()
    test_z1_checks()
    test_z1_mutants()
    test_z2_diff()
    test_z3_protected()
    test_z4_large()
    test_z5_scenarios()
    test_z5_report_timing()
    test_z5_panel()
    if FAILS:
        print("\nПРОВАЛІВ: %d" % len(FAILS))
        sys.exit(1)
    print("test_r45: усе гаразд")


if __name__ == "__main__":
    main()
