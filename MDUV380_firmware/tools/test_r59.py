#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R59 (CPS, без Tk): «Роумінг» -- прапорець каналу, колонка CSV «Roam», блок налаштувань (custom-data №15), попередження, безпечний запис.

Q1  константи Python == прошивка (номер типу блока, маска прапорця, магія, версія, межі стрибків, розкладка 8 байтів, правила придатності каналу);
Q2  блок: build/parse -- кругова оборотність, обмеження стрибків як у прошивці (поза 1..5 -> 2), недійсні блоки (коротший, інша магія, інша версія) -> None;
Q3  CSV: колонка «Roam» після стокових і перед «Name (readable)»; експорт -> імпорт БАЙТ-У-БАЙТ; CSV без колонки (стоковий) і порожні комірки прапорець не чіпають;
    Yes/No ставлять і знімають РІВНО один біт; сміття в інших бітах і байтах не зачеплено; нісенітниця в «Roam» -- попередження, прапорець як був;
Q4  table_edit: roam_numbers / channels_set_roam (один біт, ідемпотентність, відсутній канал -- відмова без змін), channel_edit({"Roam": ...}) дає ті самі байти;
Q5  R53: «Вище / Нижче» і довільна перестановка каналів -- прапорець їде разом із каналом (за вмістом, не за номером);
Q6  попередження: <2 каналів при увімкненому; аналог / DMO / симплекс / лише прийом; дублі частот + колір-коду; прапорці без блока в рації; чисто -- порожньо;
Q7  безпечний запис: страхова копія → запис → звірка; незбіг звірки, недоступна тека, відмова запису; погані значення нічого не пишуть; читання відсутнього блока;
Q8  область custom-data: тип 15 у таблиці блоків (налаштування), розбирається, потрапляє в файл налаштувань і назад, у типове застосування;
Q9  МУТАНТИ: кожна ручна підміна логіки (бит, межі, магія, порядок колонки, зайвий запис...) валить хоч одну перевірку.
Запуск: python3 tools/test_r59.py"""
import copy
import os
import re
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cps_csv as cc            # noqa: E402
import custom_data as cd         # noqa: E402
import custom_region as cr       # noqa: E402
import reorder as ro             # noqa: E402
import roam_cfg as rc            # noqa: E402
import table_edit as te          # noqa: E402
import test_cps_csv as tcsv      # noqa: E402
import test_r53 as t53           # noqa: E402

APP = os.path.join(HERE, "..", "application")
DP = ","


def read_text(*parts):
    with open(os.path.join(APP, *parts), encoding="utf-8", errors="replace") as f:
        return f.read()


class Run:
    """Збирає перевірки одного прогону; мутант проганяється тими самими перевірками, лише з підміною."""

    def __init__(self):
        self.fails = []
        self.n = 0

    def check(self, cond, msg):
        self.n += 1
        if not cond:
            self.fails.append(msg)


def fixture_image():
    spi = tcsv.make_fixture_spi()
    cp, _d = tcsv.codeplug_of(spi)
    return cc.Image.from_codeplug(cp), cp


def img_copy(img):
    return cc.Image(bytearray(img.eeprom), bytearray(img.flash), img.base)


def set_flag(img, num, on):
    r = bytearray(dict(img.channels())[num])
    r[38] = (r[38] | 0x01) if on else (r[38] & 0xFE)
    out = img_copy(img)
    out.set_channel_rec(num, bytes(r))
    return out


def rec_of(img, num):
    return bytes(dict(img.channels())[num])


def roam_world(on=()):
    """Образ з трьома каналами цифрових (різні пари частот) і одним аналоговим; прапорець роумінгу (біт 0 байта 38) виставлено на каналах із on, на решті знято."""
    img = t53.blank_image()
    spec = [(1, 14400000, 14500000, True), (2, 14410000, 14510000, True), (3, 43000000, 43000000, True), (4, 14420000, 14520000, False),
            (5, 14430000, 14530000, True)]
    for n, rx, tx, dig in spec:
        r = bytearray(tcsv.chan(("RM%d" % n).encode("cp1251"), rx, tx, dig, cc=n))
        r[38] &= 0xFE
        r[51] &= ~0x04 & 0xFF              # без «лише прийом»
        r[38] = (r[38] & ~0x04) & 0xFF      # без «примусово DMO»
        img.set_channel_rec(n, bytes(r))
        img.set_channel_in_use(n, True)
    for n in on:
        img = set_flag(img, n, True)
    return img


# ---------------------------------------------------------------------------------------------------------------------------------
#  Підроблена рація для custom-data (без USB)
# ---------------------------------------------------------------------------------------------------------------------------------

class FakeBlocks:
    """Підміна cd.read_block / cd.write_block: словник {тип: байти}; режими відмов для сценаріїв."""

    def __init__(self, store=None, fail_write=False, corrupt_write=False):
        self.store = dict(store or {})
        self.fail_write = fail_write
        self.corrupt_write = corrupt_write
        self.writes = []
        self._old = None

    def __enter__(self):
        self._old = (cd.read_block, cd.write_block)
        cd.read_block = lambda ser, t, max_len: (self.store[t][:max_len] if t in self.store else None)

        def wr(ser, t, payload):
            if self.fail_write:
                return False, "немає місця (тест)"
            self.writes.append((t, bytes(payload)))
            self.store[t] = bytes(payload[:-1] + bytes([payload[-1] ^ 1])) if self.corrupt_write else bytes(payload)
            return True, "тест"
        cd.write_block = wr
        return self

    def __exit__(self, *a):
        cd.read_block, cd.write_block = self._old


# ---------------------------------------------------------------------------------------------------------------------------------
#  Набір перевірок (приймає Run, щоб мутанти проганялись тим самим кодом)
# ---------------------------------------------------------------------------------------------------------------------------------

def suite_constants(R):
    h = read_text("include", "functions", "codeplug.h")
    R.check(re.search(r"CODEPLUG_CUSTOM_DATA_TYPE_ROAM_CFG\s*=\s*15\b", h) is not None and rc.TYPE_ROAM_CFG == 15, "Q1: тип блока 15 у codeplug.h і в roam_cfg.py")
    R.check(re.search(r"CODEPLUG_CHANNEL_LIBREDMR_FLAG1_ROAMING\s+0x01\b", h) is not None and cc.FL_ROAM == 0x01 and rc.FL_ROAM == 0x01,
            "Q1: маска прапорця роумінгу 0x01 у LibreDMR_flag1 (codeplug.h) == FL_ROAM у cps_csv.py і roam_cfg.py")
    R.check(re.search(r"CODEPLUG_CHANNEL_LIBREDMR_FLAG1_FORCE_DMO\s+0x04\b", h) is not None and rc.FL_FORCE_DMO == 0x04, "Q1: маска «примусово DMO» 0x04")
    R.check(cc.O_FLAG1L == 38, "Q1: LibreDMR_flag1 -- байт 38 запису каналу")
    R.check(re.search(r"CHANNEL_FLAG_ROAMING", h) is not None, "Q1: CHANNEL_FLAG_ROAMING у codeplug.h")
    c = read_text("include", "functions", "roam_cfg.h")
    R.check(re.search(r"ROAM_HOPS_MIN\s+%dU" % rc.HOPS_MIN, c) and re.search(r"ROAM_HOPS_MAX\s+%dU" % rc.HOPS_MAX, c) and
            re.search(r"ROAM_HOPS_DEFAULT\s+%dU" % rc.HOPS_DEFAULT, c), "Q1: межі стрибків 1/5/2 у roam_cfg.h == Python")
    R.check(re.search(r'ROAM_CFG_MAGIC\s+"%s"' % rc.MAGIC.decode(), c) is not None and re.search(r"ROAM_CFG_VERSION\s+%dU" % rc.VERSION, c), "Q1: магія і версія")
    body = re.search(r"typedef struct\s*\{(.*?)\}\s*roamOnFlashCfg_t", c, re.S).group(1)
    size = 0
    for line in body.splitlines():
        m = re.match(r"\s*(char|uint8_t)\s+(\w+)(?:\[(\d+)\])?\s*;", line)
        if m:
            size += int(m.group(3) or 1)
    R.check(size == rc.PAYLOAD_LEN == 8, "Q1: розкладка roamOnFlashCfg_t = %d байтів == PAYLOAD_LEN" % size)
    R.check([re.match(r"\s*\w+\s+(\w+)", l).group(1) for l in body.splitlines() if re.match(r"\s*(char|uint8_t)\s", l)] ==
            ["magic[4]".split("[")[0], "version", "enabled", "maxHops", "reserved"], "Q1: порядок полів блока magic/version/enabled/maxHops/reserved")
    u = read_text("source", "functions", "wake_hop_sel.c")
    m = re.search(r"bool wakeHopChannelUsable.*?\n\}", u, re.S)
    R.check(m is not None and all(k in m.group(0) for k in ("digital", "forceDmo", "rxOnly", "rxFreq != c->txFreq")),
            "Q1: правила придатності каналу в прошивці (цифровий, не DMO, не лише прийом, RX != TX) -- ті, що дзеркалить problem_of()")


def suite_payload(R):
    p = rc.build_payload(True, 3)
    R.check(p == b"ROAM\x01\x01\x03\x00" and len(p) == 8, "Q2: build(True,3) = ROAM 01 01 03 00: %r" % p)
    R.check(rc.build_payload(False, 2) == b"ROAM\x01\x00\x02\x00", "Q2: build(False,2)")
    for en in (False, True):
        for h in range(1, 6):
            R.check(rc.parse_payload(rc.build_payload(en, h)) == {"version": 1, "enabled": en, "max_hops": h}, "Q2: кругова оборотність enabled=%s hops=%d" % (en, h))
    for bad in (0, 6, 7, 255, -1, 2.5, "3", None, True):
        try:
            rc.build_payload(True, bad)
            R.check(False, "Q2: build відхиляє макс. стрибків %r" % (bad,))
        except rc.RoamCfgError:
            R.check(True, "")
    for raw, want in ((0, 2), (6, 2), (255, 2), (1, 1), (5, 5), (3, 3)):
        R.check(rc.parse_payload(b"ROAM\x01\x01" + bytes([raw]) + b"\x00")["max_hops"] == want, "Q2: байт стрибків %d читається як %d (як roamCfgClampHops)" % (raw, want))
    R.check(rc.clamp_hops(0) == 2 and rc.clamp_hops(6) == 2 and rc.clamp_hops(4) == 4, "Q2: clamp_hops")
    for raw in (b"", b"ROAM\x01\x01\x03", b"XOAM\x01\x01\x03\x00", b"ROAM\x02\x01\x03\x00", b"ROAM\x00\x01\x03\x00", None):
        R.check(rc.parse_payload(raw) is None, "Q2: недійсний блок %r -> None" % (raw,))
    R.check(rc.parse_payload(b"ROAM\x01\x07\x03\x00")["enabled"] is True, "Q2: enabled != 0 -- увімкнено (як у прошивці)")
    R.check(rc.parse_payload(b"ROAM\x01\x01\x03\x00\xAA\xBB")["max_hops"] == 3, "Q2: довший блок читається за першими 8 байтами")
    R.check(rc.default_state() == {"version": 1, "enabled": False, "max_hops": 2}, "Q2: типовий стан -- вимкнено, 2")


def csv_roundtrip(R):
    img, cp = fixture_image()
    with tempfile.TemporaryDirectory() as d:
        cc.export_files(cp, d, DP, log=lambda *_: None)
        rows = tcsv.read_csv_rows(os.path.join(d, "Channels.csv"))
        hdr = rows[0]
        R.check(hdr[:len(cc.CHANNEL_HDR)] == cc.CHANNEL_HDR, "Q3: стокові колонки йдуть першими і без змін")
        R.check(hdr[len(cc.CHANNEL_HDR)] == "Roam" and hdr[-1] == cc.READABLE and len(hdr) == len(cc.CHANNEL_HDR) + 2, "Q3: «Roam» -- після стокових, перед «Name (readable)»: %r" % hdr[-3:])
        ri = hdr.index("Roam")
        by = {r[0]: r for r in rows[1:]}
        want = {n: ("Yes" if rec_of(img, n)[38] & 1 else "No") for n in (1, 2, 3, 130)}
        R.check({n: by[str(n)][ri] for n in want} == want, "Q3: у CSV прапорець каналу: %r vs %r" % ({n: by[str(n)][ri] for n in want}, want))
        R.check(want[3] == "Yes" and want[1] == "No", "Q3: у фікстурі є канали з прапорцем і без нього (перевірка не порожня)")
        res = tcsv.import_dir(cp, d, dp=DP)
        R.check(tcsv.images_equal(res, cp), "Q3: експорт -> імпорт без правок == вихідний кодплаг БАЙТ-У-БАЙТ (з колонкою Roam)")
        R.check(not res.any_change() and not res.warnings, "Q3: жодної зміни й попередження: %s %r" % (res.summary(), res.warnings))
        # стоковий CSV (без колонки Roam) -- прапорці не чіпає
        stock = [[c for j, c in enumerate(r) if j != ri] for r in rows]
        tcsv.write_csv_rows(os.path.join(d, "Channels.csv"), stock)
        res = tcsv.import_dir(cp, d, dp=DP)
        R.check(tcsv.images_equal(res, cp), "Q3: CSV без колонки Roam не змінює жодного байта (прапорці лишились як були)")
        # порожня комірка -- не чіпає
        rows2 = [list(r) for r in rows]
        for r in rows2[1:]:
            r[ri] = ""
        tcsv.write_csv_rows(os.path.join(d, "Channels.csv"), rows2)
        res = tcsv.import_dir(cp, d, dp=DP)
        R.check(tcsv.images_equal(res, cp), "Q3: порожні комірки Roam не чіпають прапорець")
        # Yes/No: ставить і знімає рівно один біт, решта запису незмінна
        for ch, val, bit in ((1, "Yes", 1), (3, "No", 0)):
            tcsv.write_csv_rows(os.path.join(d, "Channels.csv"), rows)
            tcsv.edit_cell(os.path.join(d, "Channels.csv"), lambda r, c=ch: r[0] == str(c), "Roam", val)
            res = tcsv.import_dir(cp, d, dp=DP)
            new = rec_of(res.image, ch)
            old = rec_of(img, ch)
            R.check(new[38] & 1 == bit, "Q3: канал %d, Roam=%s -> біт %d" % (ch, val, bit))
            diff = [i for i in range(56) if new[i] != old[i]]
            R.check(diff == [38] and (new[38] ^ old[38]) == 1, "Q3: канал %d: змінився лише біт 0 байта 38 (змінені байти %r)" % (ch, diff))
            others = [n for n, r in img.channels() if n != ch and bytes(r) != rec_of(res.image, n)]
            R.check(others == [], "Q3: інші канали не зачеплено: %r" % others)
        # нісенітниця -- попередження, прапорець як був
        tcsv.write_csv_rows(os.path.join(d, "Channels.csv"), rows)
        tcsv.edit_cell(os.path.join(d, "Channels.csv"), lambda r: r[0] == "3", "Roam", "можливо")
        res = tcsv.import_dir(cp, d, dp=DP)
        R.check(rec_of(res.image, 3) == rec_of(img, 3), "Q3: нерозбірливе значення Roam лишає канал як був")
        R.check(any("Roam" in w for w in res.warnings), "Q3: і про це є попередження: %r" % res.warnings)


def suite_edit(R):
    w = roam_world(on=(1,))
    R.check(te.roam_numbers(w) == [1], "Q4: roam_numbers: %r" % te.roam_numbers(w))
    res = te.channels_set_roam(w, [2, 5], True)
    R.check(te.roam_numbers(res.image) == [1, 2, 5] and len(res.changed) == 2, "Q4: додано 2 і 5: %r / %r" % (te.roam_numbers(res.image), res.changed))
    for n in (1, 2, 3, 4, 5):
        a, b = rec_of(w, n), rec_of(res.image, n)
        d = [i for i in range(56) if a[i] != b[i]]
        R.check(d == ([38] if n in (2, 5) else []), "Q4: канал %d: змінені байти %r" % (n, d))
    again = te.channels_set_roam(res.image, [2, 5], True)
    R.check(not again.changed and bytes(again.image.eeprom) == bytes(res.image.eeprom) and bytes(again.image.flash) == bytes(res.image.flash),
            "Q4: повторне додавання нічого не змінює (ідемпотентно)")
    off = te.channels_set_roam(res.image, [1, 2, 5], False)
    R.check(te.roam_numbers(off.image) == [] and len(off.changed) == 3, "Q4: прибрано всі: %r" % te.roam_numbers(off.image))
    R.check(all(rec_of(off.image, n)[38] & 1 == 0 for n in (1, 2, 5)), "Q4: біт знято")
    try:
        te.channels_set_roam(w, [2, 999], True)
        R.check(False, "Q4: відсутній канал -- відмова")
    except te.TableEditError as e:
        R.check("999" in str(e), "Q4: відмова називає канал")
    R.check(te.roam_numbers(w) == [1], "Q4: після відмови образ не змінено")
    # той самий результат через CSV-шлях редактора
    via = te.channel_edit(w, 2, {"Roam": "Yes"}, DP)
    R.check(rec_of(via.image, 2) == rec_of(res.image, 2), "Q4: channel_edit({'Roam': 'Yes'}) дає ті самі байти, що channels_set_roam")
    via2 = te.channel_edit(res.image, 2, {"Roam": "No"}, DP)
    R.check(rec_of(via2.image, 2)[38] & 1 == 0, "Q4: channel_edit({'Roam': 'No'}) знімає")
    # значення форми
    R.check(te.channel_values(w, 1, DP)["Roam"] == "Yes" and te.channel_values(w, 2, DP)["Roam"] == "No", "Q4: channel_values віддає Roam")
    # новий канал на основі наявного успадковує прапорець (дублікат -- той самий запис, крім назви й номера)
    dup = te.duplicate_entity(w, "channel", 1, DP)
    newn = [n for n in te.roam_numbers(dup.image) if n != 1]
    R.check(len(newn) == 1, "Q4: дублікат каналу зі списку теж зі списку (копія запису): %r" % te.roam_numbers(dup.image))


def suite_r53(R):
    import random
    for seed in range(6):
        img = t53.world(seed)
        img = te.channels_set_roam(img, [n for n, _r in img.channels()], False).image      # у фікстурі біт 0 -- сміття: починаємо з чистого списку
        names = {n: cc.readable_text(r[:16]) for n, r in img.channels()}
        rg = random.Random(seed)
        marked = set(rg.sample(sorted(names), 7))
        for n in marked:
            img = set_flag(img, n, True)
        want = {names[n] for n in marked}
        want_off = {names[n] for n in names if n not in marked}
        order = ro.idents(img, "channel")
        for _ in range(4):
            new = list(order)
            rg.shuffle(new)
            res = ro.permute(img, "channel", new)
            got = {cc.readable_text(r[:16]) for n, r in res.image.channels() if r[38] & 1}
            got_off = {cc.readable_text(r[:16]) for n, r in res.image.channels() if not r[38] & 1}
            R.check(got == want and got_off == want_off, "Q5 [seed %d]: після перестановки прапорець лишився на тих самих каналах (за назвою)" % seed)
        n0 = order[3]
        res = ro.move(img, "channel", n0, -1)
        nm = names[n0]
        flag_before = bool(dict(img.channels())[n0][38] & 1)
        found = [r for n, r in res.image.channels() if cc.readable_text(r[:16]) == nm]
        R.check(len(found) == 1 and bool(found[0][38] & 1) == flag_before, "Q5 [seed %d]: «Вище» несе прапорець з каналом" % seed)


def suite_warnings(R):
    ok = roam_world(on=(1, 2, 5))
    R.check(rc.check_list(ok, enabled=True) == [], "Q6: чистий список -- без попереджень: %r" % rc.check_list(ok, enabled=True))
    R.check(rc.check_list(ok, enabled=False) == [], "Q6: вимкнено -- теж чисто")
    one = roam_world(on=(1,))
    w = rc.check_list(one, enabled=True)
    R.check(len(w) == 1 and "щонайменше 2" in w[0], "Q6: увімкнено, а в списку 1 канал: %r" % w)
    R.check(rc.check_list(one, enabled=False) == [], "Q6: вимкнено -- про «менше 2» не нагадуємо")
    none = roam_world()
    w = rc.check_list(none, enabled=True)
    R.check(len(w) == 1 and "0 каналів" in w[0], "Q6: увімкнено, список порожній: %r" % w)
    # аналоговий
    w = rc.check_list(roam_world(on=(1, 4)), enabled=False)
    R.check(len(w) == 1 and "№4" in w[0] and "аналог" in w[0], "Q6: аналоговий у списку: %r" % w)
    # симплекс
    w = rc.check_list(roam_world(on=(1, 3)), enabled=False)
    R.check(len(w) == 1 and "№3" in w[0] and "симплекс" in w[0], "Q6: симплекс у списку: %r" % w)
    # DMO
    d = roam_world(on=(1, 2))
    r = bytearray(rec_of(d, 2))
    r[38] |= 0x04
    d.set_channel_rec(2, bytes(r))
    w = rc.check_list(d, enabled=False)
    R.check(len(w) == 1 and "№2" in w[0] and "DMO" in w[0], "Q6: DMO у списку: %r" % w)
    # лише прийом
    d = roam_world(on=(1, 2))
    r = bytearray(rec_of(d, 2))
    r[51] |= 0x04
    d.set_channel_rec(2, bytes(r))
    w = rc.check_list(d, enabled=False)
    R.check(len(w) == 1 and "№2" in w[0] and "лише прийом" in w[0], "Q6: лише прийом у списку: %r" % w)
    # проблемний канал НЕ у списку -- мовчимо
    R.check(rc.check_list(roam_world(on=(1, 2)), enabled=True) == [], "Q6: аналоговий/симплекс поза списком не згадується")
    # дублі пар
    d = roam_world(on=(1, 2, 5))
    r = bytearray(rec_of(d, 2))
    r[16:24] = rec_of(d, 1)[16:24]
    r[44] = rec_of(d, 1)[44]
    d.set_channel_rec(2, bytes(r))
    w = rc.check_list(d, enabled=False)
    R.check(len(w) == 1 and "№1" in w[0] and "№2" in w[0] and "однакові" in w[0], "Q6: дублі частот+колір-код: %r" % w)
    # той самий пара частот, інший колір-код -- не дубль
    r2 = bytearray(r)
    r2[44] = (r[44] % 15) + 1
    d.set_channel_rec(2, bytes(r2))
    R.check(rc.check_list(d, enabled=False) == [], "Q6: однакові частоти, але інший колір-код -- не дубль")
    r3 = bytearray(r)                                  # той самий RX і колір-код, інший TX -- теж не дубль
    r3[20:24] = rec_of(d, 5)[20:24]
    d.set_channel_rec(2, bytes(r3))
    R.check(rc.check_list(d, enabled=False) == [], "Q6: однаковий RX і колір-код, але інший TX -- не дубль")
    r4 = bytearray(r)                                  # той самий TX і колір-код, інший RX -- теж не дубль
    r4[16:20] = rec_of(d, 5)[16:20]
    d.set_channel_rec(2, bytes(r4))
    R.check(rc.check_list(d, enabled=False) == [], "Q6: однаковий TX і колір-код, але інший RX -- не дубль")
    # прапорці без блока в рації
    w = rc.check_list(ok, enabled=False, block_absent=True)
    R.check(len(w) == 1 and "блока налаштувань" in w[0] and "3" in w[0], "Q6: прапорці є, блока в рації нема: %r" % w)
    R.check(rc.check_list(none, enabled=False, block_absent=True) == [], "Q6: блока нема, але й прапорців нема -- мовчимо")
    # зняття всіх позначок
    out, n = rc.clear_flags(ok)
    R.check(n == 3 and te.roam_numbers(out) == [], "Q6: clear_flags знімає всі: %d" % n)
    R.check(all(rec_of(out, k)[:38] == rec_of(ok, k)[:38] and rec_of(out, k)[39:] == rec_of(ok, k)[39:] for k in (1, 2, 3, 4, 5)), "Q6: clear_flags не чіпає інші байти")


def suite_write(R):
    with tempfile.TemporaryDirectory() as td:
        # блока ще нема: створюється, страхової копії нема
        with FakeBlocks() as fb:
            st, raw = rc.read_state(None)
            R.check(st is None and raw is None, "Q7: блока нема -> (None, None)")
            text, safety = rc.write_state(None, True, 3, safety_dir=td, log=lambda *_: None)
            R.check(safety is None and fb.writes == [(15, b"ROAM\x01\x01\x03\x00")], "Q7: створення блока без страхової копії: %r" % fb.writes)
            R.check("Звірка читанням: OK" in text and "увімкнено" in text and "3" in text, "Q7: текст підсумку: %s" % text)
            R.check(os.listdir(td) == [], "Q7: файлів не створено")
            st, raw = rc.read_state(None)
            R.check(st == {"version": 1, "enabled": True, "max_hops": 3} and raw == b"ROAM\x01\x01\x03\x00", "Q7: читання після запису")
            # блок є: страхова копія з попереднім вмістом, потім запис
            text, safety = rc.write_state(None, False, 5, safety_dir=td, log=lambda *_: None)
            R.check(safety is not None and open(safety, "rb").read() == b"ROAM\x01\x01\x03\x00", "Q7: страхова копія = старий блок")
            R.check(fb.store[15] == b"ROAM\x01\x00\x05\x00" and safety in text, "Q7: записано новий блок і названо копію")
            text2, safety2 = rc.write_state(None, False, 5, safety_dir=td, log=lambda *_: None)
            R.check(safety2 != safety and os.path.exists(safety) and os.path.exists(safety2), "Q7: друга копія не затирає першу")
        # погані значення -- нічого не пишуть, не торкаються рації
        with FakeBlocks({15: b"ROAM\x01\x01\x02\x00"}) as fb:
            n_files = len(os.listdir(td))
            for bad in (0, 6, "x", None):
                try:
                    rc.write_state(None, True, bad, safety_dir=td, log=lambda *_: None)
                    R.check(False, "Q7: макс. стрибків %r відхилено до запису" % (bad,))
                except rc.RoamCfgError:
                    R.check(True, "")
            R.check(fb.writes == [] and len(os.listdir(td)) == n_files, "Q7: погані значення: ні запису, ні копії")
        # відмова запису
        with FakeBlocks({15: b"ROAM\x01\x01\x02\x00"}, fail_write=True) as fb:
            try:
                rc.write_state(None, True, 4, safety_dir=td, log=lambda *_: None)
                R.check(False, "Q7: відмова запису піднімає помилку")
            except RuntimeError as e:
                R.check("не записані" in str(e) and "тест" in str(e), "Q7: текст відмови: %s" % e)
            R.check(fb.store[15] == b"ROAM\x01\x01\x02\x00", "Q7: після відмови блок у рації як був")
        # незбіг звірки
        with FakeBlocks({15: b"ROAM\x01\x01\x02\x00"}, corrupt_write=True):
            try:
                rc.write_state(None, True, 4, safety_dir=td, log=lambda *_: None)
                R.check(False, "Q7: незбіг звірки -- помилка")
            except RuntimeError as e:
                R.check("звірка" in str(e) and "роам" not in str(e).lower() or "звірка" in str(e), "Q7: незбіг звірки названо: %s" % e)
        # недоступна тека копії -- нічого не пишемо
        with FakeBlocks({15: b"ROAM\x01\x01\x02\x00"}) as fb:
            bad_dir = os.path.join(td, "немає", "такої")
            try:
                rc.write_state(None, True, 4, safety_dir=bad_dir, log=lambda *_: None)
                R.check(False, "Q7: недоступна тека копії -- відмова")
            except RuntimeError as e:
                R.check("страхова копія" in str(e) and fb.writes == [], "Q7: відмова до запису: %s" % e)
        # недійсний блок у рації читається як «нема дійсного»
        with FakeBlocks({15: b"JUNKJUNK"}):
            st, raw = rc.read_state(None)
            R.check(st is None and raw == b"JUNKJUNK", "Q7: недійсний блок: стан None, сирі байти віддано")


def suite_region(R):
    import test_r30 as t30
    payload = rc.build_payload(True, 4)
    R.check(cr.BLOCK_TYPES.get(15, (None,))[0] == "ROAM_CFG" and cr.BLOCK_TYPES[15][4] == "setting", "Q8: тип 15 -- ROAM_CFG, налаштування")
    R.check(cr.type_name(15) == "ROAM_CFG" and "Роумінг" in cr.type_title(15), "Q8: назви типу 15")
    spi = t30.new_spi_with(1, types=[4, 9])
    pl = t30.payloads_of(t30.region_of(spi))
    pl[15] = payload
    spi2 = t30.put_region(bytearray(spi), pl, order=sorted(pl))
    region = t30.region_of(spi2)
    parsed = cr.parse_region(region)
    by = parsed.by_type()
    R.check(15 in by and by[15].payload == payload and by[15].name == "ROAM_CFG" and by[15].kind == "setting" and not parsed.problems, "Q8: блок 15 розбирається в області: %r" % (parsed.problems,))
    R.check(cr.default_selected(by[15]), "Q8: типово застосовується до рації при відновленні (налаштування, не стан і не секрет)")
    text = cr.settings_to_text(parsed.blocks)
    blocks, _doc = cr.settings_from_text(text)
    R.check(any(b.type == 15 and b.payload == payload for b in blocks), "Q8: блок 15 проходить файл налаштувань і назад")
    R.check("ROAM_CFG" in text, "Q8: у файлі налаштувань названо блок")


SUITES = (suite_constants, suite_payload, csv_roundtrip, suite_edit, suite_r53, suite_warnings, suite_write, suite_region)


def run_all():
    R = Run()
    for s in SUITES:
        try:
            s(R)
        except Exception as e:  # noqa: BLE001 -- збій сценарію теж провал (мутант міг зламати код так, що він падає)
            R.fails.append("%s: виняток %s: %s" % (s.__name__, type(e).__name__, e))
    return R


# ---------------------------------------------------------------------------------------------------------------------------------
#  Мутанти
# ---------------------------------------------------------------------------------------------------------------------------------

def mutants():
    """[(назва, застосувати() -> відновити())]. Кожен мутант міняє ОДНЕ місце логіки."""
    out = []

    def patch(obj, name, new):
        def apply():
            old = getattr(obj, name)
            setattr(obj, name, new)
            return lambda: setattr(obj, name, old)
        return apply

    def patch_col(key, val):
        def apply():
            col = cc.CH_COLUMN_BY_NAME["Roam"]
            old = col[key]
            col[key] = val
            return lambda: col.__setitem__(key, old)
        return apply

    # --- блок ---
    out.append(("clamp: 0 лишається 0", patch(rc, "clamp_hops", lambda h: h if 0 <= h <= 5 else rc.HOPS_DEFAULT)))
    out.append(("clamp: 6 лишається 6", patch(rc, "clamp_hops", lambda h: h if 1 <= h <= 6 else rc.HOPS_DEFAULT)))
    out.append(("clamp: поза межами -> 1", patch(rc, "clamp_hops", lambda h: h if 1 <= h <= 5 else 1)))
    out.append(("check_hops пропускає 0", patch(rc, "check_hops", lambda h: h if isinstance(h, int) and 0 <= h <= 5 else (_ for _ in ()).throw(rc.RoamCfgError("x")))))
    out.append(("check_hops пропускає 6", patch(rc, "check_hops", lambda h: h if isinstance(h, int) and 1 <= h <= 6 else (_ for _ in ()).throw(rc.RoamCfgError("x")))))
    out.append(("check_hops пропускає будь-що", patch(rc, "check_hops", lambda h: h)))

    def build_bad_order(enabled, max_hops):
        rc.check_hops(max_hops)
        return b"ROAM\x01" + bytes([max_hops, 1 if enabled else 0, 0])
    out.append(("build: enabled і hops переставлено", patch(rc, "build_payload", build_bad_order)))
    out.append(("build: інша версія", patch(rc, "build_payload", lambda e, h: (rc.check_hops(h), b"ROAM\x02" + bytes([1 if e else 0, h, 0]))[1])))
    out.append(("build: enabled завжди 1", patch(rc, "build_payload", lambda e, h: (rc.check_hops(h), b"ROAM\x01\x01" + bytes([h, 0]))[1])))
    out.append(("build: довжина 7", patch(rc, "build_payload", lambda e, h: (rc.check_hops(h), b"ROAM\x01" + bytes([1 if e else 0, h]))[1])))
    out.append(("build: резерв не нуль", patch(rc, "build_payload", lambda e, h: (rc.check_hops(h), b"ROAM\x01" + bytes([1 if e else 0, h, 0xAA]))[1])))
    out.append(("parse: не перевіряє магію", patch(rc, "parse_payload", lambda p: {"version": 1, "enabled": p[5] != 0, "max_hops": rc.clamp_hops(p[6])} if p and len(p) >= 8 and p[4] == 1 else None)))
    out.append(("parse: не перевіряє версію", patch(rc, "parse_payload", lambda p: {"version": p[4], "enabled": p[5] != 0, "max_hops": rc.clamp_hops(p[6])} if p and len(p) >= 8 and bytes(p[:4]) == b"ROAM" else None)))
    out.append(("parse: не перевіряє довжину", patch(rc, "parse_payload", lambda p: {"version": 1, "enabled": bool(p[5]), "max_hops": rc.clamp_hops(p[6])} if p and len(p) >= 7 and bytes(p[:4]) == b"ROAM" and p[4] == 1 else None)))
    out.append(("parse: enabled лише ==1", patch(rc, "parse_payload", lambda p: {"version": 1, "enabled": p[5] == 1, "max_hops": rc.clamp_hops(p[6])} if p and len(p) >= 8 and bytes(p[:4]) == b"ROAM" and p[4] == 1 else None)))
    out.append(("parse: не обмежує стрибки", patch(rc, "parse_payload", lambda p: {"version": 1, "enabled": p[5] != 0, "max_hops": p[6]} if p and len(p) >= 8 and bytes(p[:4]) == b"ROAM" and p[4] == 1 else None)))
    # --- CSV ---
    old_dec = cc.CH_COLUMN_BY_NAME["Roam"]["dec"]
    old_enc = cc.CH_COLUMN_BY_NAME["Roam"]["enc"]
    d2, e2 = cc._flag(cc.O_FLAG1L, 0x02)
    out.append(("колонка Roam на бiті 0x02", lambda: (lambda o: (cc.CH_COLUMN_BY_NAME["Roam"].update(dec=d2, enc=e2), lambda: cc.CH_COLUMN_BY_NAME["Roam"].update(dec=old_dec, enc=old_enc))[1])(None)))
    d3, e3 = cc._flag(cc.O_FLAG1L, 0x01, invert=True)
    out.append(("колонка Roam інвертована", lambda: (lambda o: (cc.CH_COLUMN_BY_NAME["Roam"].update(dec=d3, enc=e3), lambda: cc.CH_COLUMN_BY_NAME["Roam"].update(dec=old_dec, enc=old_enc))[1])(None)))
    out.append(("колонка Roam не м'яка (порожня комірка змінює)", patch_col("soft", False)))
    out.append(("колонка Roam лише для цифрових", patch_col("app", "D")))
    out.append(("«Roam» не потрапляє в заголовок CSV", patch(cc, "CHANNEL_EXT_HDR", [])))
    # --- table_edit ---
    real_set = te.channels_set_roam

    def set_wrong_byte(img, numbers, on):
        out_img = cc.Image(img.eeprom, img.flash, img.base)
        res = cc.ImportResult()
        res.image = out_img
        for n in sorted(set(numbers)):
            r = bytearray(dict(img.channels())[n])
            r[39] = (r[39] | 1) if on else (r[39] & 0xFE)
            out_img.set_channel_rec(n, bytes(r))
            res.changed.append(("Канали", "№%d" % n))
        return res
    out.append(("channels_set_roam пише не той байт", patch(te, "channels_set_roam", set_wrong_byte)))

    def set_no_missing_check(img, numbers, on):
        return real_set(img, [n for n in numbers if n in dict(img.channels())], on)
    out.append(("channels_set_roam ковтає відсутній канал", patch(te, "channels_set_roam", set_no_missing_check)))

    def set_always_changed(img, numbers, on):
        res = real_set(img, numbers, on)
        if not res.changed:
            res.changed.append(("Канали", "фіктивна зміна"))
        return res
    out.append(("channels_set_roam рапортує зміну, якої нема", patch(te, "channels_set_roam", set_always_changed)))
    out.append(("roam_numbers бере всі канали", patch(te, "roam_numbers", lambda img: [n for n, _r in img.channels()])))
    # --- попередження ---
    real_problem = rc.problem_of
    out.append(("problem_of: аналог не помічено", patch(rc, "problem_of", lambda r: None if r[24] == 0 else real_problem(r))))
    out.append(("problem_of: симплекс не помічено", patch(rc, "problem_of", lambda r: None if rc._freq(r, 16) == rc._freq(r, 20) else real_problem(r))))
    out.append(("problem_of: DMO не помічено", patch(rc, "problem_of", lambda r: None if r[38] & 4 else real_problem(r))))
    out.append(("problem_of: лише прийом не помічено", patch(rc, "problem_of", lambda r: None if (r[51] & 4 and r[24] and not r[38] & 4 and rc._freq(r, 16) != rc._freq(r, 20)) else real_problem(r))))
    out.append(("problem_of: усе проблема", patch(rc, "problem_of", lambda r: "test")))
    out.append(("pair_key без колір-коду", patch(rc, "pair_key", lambda r: (rc._freq(r, 16), rc._freq(r, 20)))))
    out.append(("pair_key без RX", patch(rc, "pair_key", lambda r: (rc._freq(r, 20), r[44]))))
    out.append(("pair_key без TX", patch(rc, "pair_key", lambda r: (rc._freq(r, 16), r[44]))))
    real_check = rc.check_list
    out.append(("check_list без попередження «менше 2»", patch(rc, "check_list", lambda img, enabled=False, block_absent=False: [w for w in real_check(img, enabled, block_absent) if "щонайменше" not in w])))
    out.append(("check_list без попередження «блока нема»", patch(rc, "check_list", lambda img, enabled=False, block_absent=False: real_check(img, enabled, False))))
    out.append(("check_list завжди «менше 2»", patch(rc, "check_list", lambda img, enabled=False, block_absent=False: real_check(img, True, block_absent))))
    out.append(("clear_flags знімає не все", patch(rc, "clear_flags", lambda img: (img, 0))))
    # --- запис ---
    real_write = rc.write_state

    def no_verify_write(ser, enabled, max_hops, safety_dir=None, now=None, log=print):
        payload = rc.build_payload(enabled, max_hops)
        ok, msg = cd.write_block(ser, rc.TYPE_ROAM_CFG, payload)
        if not ok:
            raise RuntimeError("налаштування «Роумінгу» не записані: " + msg)
        return "ok", None
    out.append(("запис без страхової копії і звірки", patch(rc, "write_state", no_verify_write)))

    return out


def run_mutants():
    bad = []
    for name, apply in mutants():
        restore = apply()
        try:
            R = run_all()
        finally:
            restore()
        if not R.fails:
            bad.append(name)
    return bad


def main():
    R = run_all()
    for f in R.fails:
        print("ПРОВАЛ:", f)
    if R.fails:
        print("test_r59: %d провалів з %d перевірок" % (len(R.fails), R.n))
        return 1
    muts = mutants()
    surv = run_mutants()
    for s in surv:
        print("ПРОВАЛ: мутант вижив (тест його не бачить):", s)
    if surv:
        return 1
    print("test_r59: усе гаразд (%d перевірок; мутантів %d, усі вбито: константи з прошивки, блок, CSV-колонка, редагування, R53, попередження, безпечний запис, область)." % (R.n, len(muts)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
