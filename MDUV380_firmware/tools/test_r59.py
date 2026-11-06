#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R59/R60 (CPS, без Tk): «Роумінг» -- 10 СПИСКІВ у байті 37 запису каналу, колонка CSV «RoamList» (+ читання старої «Roam»), блок налаштувань (custom-data №15),
попередження, безпечний запис.

Q1  константи Python == прошивка (номер типу блока, байт/мітка/кількість списків, магія, версія, межі стрибків, розкладка 8 байтів, правила придатності каналу);
    розбір/запис байта списку Python == справжній roam_cfg.c (скомпільований, усі 256 значень);
Q2  блок: build/parse -- кругова оборотність, обмеження стрибків як у прошивці (поза 1..5 -> 2), недійсні блоки (коротший, інша магія, інша версія) -> None;
Q3  CSV: колонка «RoamList» після стокових і перед «Name (readable)»; експорт -> імпорт БАЙТ-У-БАЙТ; CSV без колонки (стоковий) і порожні комірки список не чіпають;
    значення 0..10 ставлять РІВНО байт 37 (+ знімають старий прапорець); сміття в інших байтах не зачеплено; нісенітниця / 11 / -1 -- попередження, список як був;
    старий CSV R59 зі стовпцем «Roam»: Yes -> список 1 (у звіті і в попередженні), No / порожнє нічого не змінює;
Q4  table_edit: roam_numbers(lst) / channels_set_roam (один байт, ідемпотентність, ПЕРЕНОС між списками, відсутній канал/список 11 -- відмова без змін), channel_edit
    ({"RoamList": ...}) дає ті самі байти; roam_migrate_legacy (старий прапорець -> список 1, інші не чіпає);
Q5  R53: «Вище / Нижче» і довільна перестановка каналів -- номер списку їде разом із каналом (за вмістом, не за номером);
Q6  попередження: жодного списку з 2+ каналів при увімкненому; список з одним каналом; аналог / DMO / симплекс / лише прийом; дублі частот + колір-коду У ТОМУ САМОМУ списку
    (в різних -- не дубль); старий прапорець без списку; списки без блока в рації; чисто -- порожньо;
Q7  безпечний запис: страхова копія → запис → звірка; незбіг звірки, недоступна тека, відмова запису; погані значення нічого не пишуть; читання відсутнього блока;
Q8  область custom-data: тип 15 у таблиці блоків (налаштування), розбирається, потрапляє в файл налаштувань і назад, у типове застосування;
Q9  МУТАНТИ: кожна ручна підміна логіки (байт, мітка, межі, магія, порядок колонки, зайвий запис...) валить хоч одну перевірку.
Запуск: python3 tools/test_r59.py"""
import copy
import os
import re
import shutil
import struct
import subprocess
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


def img_to_codeplug(img, cp):
    """Кодплаг-обгортка для імпорту/експорту з образу img (образ уже містить усі зміни; cp -- вихідний кодплаг фікстури)."""
    out = copy.copy(cp)
    out.eeprom = bytes(img.eeprom)
    out.flash = bytes(img.flash)
    return out


def fixture_image():
    spi = tcsv.make_fixture_spi()
    cp, _d = tcsv.codeplug_of(spi)
    return cc.Image.from_codeplug(cp), cp


def img_copy(img):
    return cc.Image(bytearray(img.eeprom), bytearray(img.flash), img.base)


def set_list(img, num, lst):
    """Образ із каналом num у списку lst (0 -- без списку): байт 37 з міткою, як це пише прошивка (roamListToByte)."""
    r = bytearray(dict(img.channels())[num])
    r[37] = (0xC0 | lst) if lst else 0
    out = img_copy(img)
    out.set_channel_rec(num, bytes(r))
    return out


def set_flag(img, num, on):
    """Лише СТАРИЙ прапорець R59 (біт 0 байта 38)."""
    r = bytearray(dict(img.channels())[num])
    r[38] = (r[38] | 0x01) if on else (r[38] & 0xFE)
    out = img_copy(img)
    out.set_channel_rec(num, bytes(r))
    return out


def rec_of(img, num):
    return bytes(dict(img.channels())[num])


def roam_world(on=(), lst=1):
    """Образ з чотирма цифровими (різні пари частот) і одним аналоговим каналом; канали з on стоять у списку lst (байт 37 = 0xC0|lst), решта -- без списку; старий прапорець знято."""
    img = t53.blank_image()
    spec = [(1, 14400000, 14500000, True), (2, 14410000, 14510000, True), (3, 43000000, 43000000, True), (4, 14420000, 14520000, False),
            (5, 14430000, 14530000, True)]
    for n, rx, tx, dig in spec:
        r = bytearray(tcsv.chan(("RM%d" % n).encode("cp1251"), rx, tx, dig, cc=n))
        r[38] &= 0xFE
        r[37] = 0
        r[51] &= ~0x04 & 0xFF              # без «лише прийом»
        r[38] = (r[38] & ~0x04) & 0xFF      # без «примусово DMO»
        img.set_channel_rec(n, bytes(r))
        img.set_channel_in_use(n, True)
    for n in on:
        img = set_list(img, n, lst)
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
            "Q1: маска СТАРОГО прапорця роумінгу 0x01 у LibreDMR_flag1 (codeplug.h) == FL_ROAM у cps_csv.py і roam_cfg.py")
    rh = read_text("include", "functions", "roam_cfg.h")
    num = lambda name: int(re.search(r"#define\s+%s\s+(0x[0-9A-Fa-f]+|\d+)U?\b" % name, rh).group(1), 0)      # noqa: E731
    R.check(num("ROAM_LISTS_COUNT") == rc.LISTS_COUNT == cc.ROAM_LISTS == 10, "Q1: кількість списків 10 у roam_cfg.h == roam_cfg.py == cps_csv.py")
    R.check(num("ROAM_LIST_BYTE_OFFSET") == rc.LIST_BYTE_OFFSET == cc.O_ROAMLIST == 37, "Q1: байт списку -- 37 запису каналу (прошивка == Python)")
    R.check(num("ROAM_LIST_TAG") == rc.LIST_TAG == cc.ROAM_TAG == 0xC0 and num("ROAM_LIST_TAG_MASK") == rc.LIST_TAG_MASK == cc.ROAM_TAG_MASK == 0xF0 and
            num("ROAM_LIST_VALUE_MASK") == rc.LIST_VALUE_MASK == 0x0F, "Q1: мітка 0xC0, маска мітки 0xF0, маска номера 0x0F (прошивка == Python)")
    R.check(re.search(r"_UNUSED_1", h) is not None, "Q1: байт 37 у codeplug.h -- _UNUSED_1 (його прошивка більше ніде не використовує)")
    R.check(re.search(r"CODEPLUG_CHANNEL_LIBREDMR_FLAG1_FORCE_DMO\s+0x04\b", h) is not None and rc.FL_FORCE_DMO == 0x04, "Q1: маска «примусово DMO» 0x04")
    R.check(cc.O_FLAG1L == 38, "Q1: LibreDMR_flag1 -- байт 38 запису каналу")
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


def suite_list_byte(R):
    """Q1: розбір/запис байта списку на Python == справжній roam_cfg.c (збирається gcc, 256 значень байта й числа 0..20 для запису)."""
    cc_bin = shutil.which("gcc") or shutil.which("cc")
    exp = {b: rc.list_from_byte(b) for b in range(256)}
    R.check(all(exp[0xC0 | n] == n for n in range(1, 11)) and all(exp[b] == 0 for b in range(256) if not (0xC1 <= b <= 0xCA)),
            "Q1: list_from_byte: лише 0xC1..0xCA дають 1..10, решта 256-10 значень -- 0")
    R.check(all(rc.list_to_byte(n) == (0xC0 | n if 1 <= n <= 10 else 0) for n in range(0, 21)) and rc.list_to_byte(True) == 0 and rc.list_to_byte(-1) == 0,
            "Q1: list_to_byte: N -> 0xC0|N, поза 1..10 -> 0")
    if cc_bin is None:
        R.check(True, "Q1: gcc нема -- звірку з roam_cfg.c пропущено")
        return
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "t.c")
        with open(src, "w") as f:
            f.write('#include <stdio.h>\n#include <stdint.h>\n#include "functions/roam_cfg.h"\nint main(void){for(int b=0;b<256;b++)printf("F %d %u\\n",b,roamListFromByte((uint8_t)b));'
                    'for(int n=0;n<21;n++)printf("T %d %u\\n",n,roamListToByte((uint8_t)n));return 0;}\n')
        exe = os.path.join(td, "t")
        r = subprocess.run([cc_bin, "-DENABLE_ROAM_RETRY", "-DROAM_CFG_HOST_TEST", "-I" + os.path.join(APP, "include"), src,
                            os.path.join(APP, "source", "functions", "roam_cfg.c"), "-o", exe], capture_output=True, text=True)
        if r.returncode != 0:
            R.check(False, "Q1: roam_cfg.c не збирається для звірки: %s" % r.stderr[-300:])
            return
        out = subprocess.run([exe], capture_output=True, text=True).stdout.split("\n")
        got_f = {int(l.split()[1]): int(l.split()[2]) for l in out if l.startswith("F ")}
        got_t = {int(l.split()[1]): int(l.split()[2]) for l in out if l.startswith("T ")}
        R.check(got_f == exp, "Q1: roamListFromByte (C) == list_from_byte (Python) на всіх 256 значеннях")
        R.check(got_t == {n: rc.list_to_byte(n) for n in range(21)}, "Q1: roamListToByte (C) == list_to_byte (Python) на 0..20")


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
    # у фікстурі кілька каналів дістають список, щоб перевірка не була порожньою
    img = set_list(set_list(img, 3, 2), 130, 10)
    cp = img_to_codeplug(img, cp)
    with tempfile.TemporaryDirectory() as d:
        cc.export_files(cp, d, DP, log=lambda *_: None)
        rows = tcsv.read_csv_rows(os.path.join(d, "Channels.csv"))
        hdr = rows[0]
        R.check(hdr[:len(cc.CHANNEL_HDR)] == cc.CHANNEL_HDR, "Q3: стокові колонки йдуть першими і без змін")
        R.check(hdr[len(cc.CHANNEL_HDR)] == "RoamList" and hdr[-1] == cc.READABLE and len(hdr) == len(cc.CHANNEL_HDR) + 2 and "Roam" not in hdr,
                "Q3: «RoamList» -- після стокових, перед «Name (readable)», старої «Roam» в експорті нема: %r" % hdr[-3:])
        ri = hdr.index("RoamList")
        by = {r[0]: r for r in rows[1:]}
        want = {n: str(rc.list_of(rec_of(img, n))) for n in (1, 2, 3, 130)}
        R.check({n: by[str(n)][ri] for n in want} == want, "Q3: у CSV номер списку каналу: %r vs %r" % ({n: by[str(n)][ri] for n in want}, want))
        R.check(want[3] == "2" and want[130] == "10" and want[1] == "0", "Q3: у фікстурі є канали зі списками 2, 10 і без списку (перевірка не порожня)")
        res = tcsv.import_dir(cp, d, dp=DP)
        R.check(tcsv.images_equal(res, cp), "Q3: експорт -> імпорт без правок == вихідний кодплаг БАЙТ-У-БАЙТ (з колонкою RoamList)")
        R.check(not res.any_change() and not res.warnings, "Q3: жодної зміни й попередження: %s %r" % (res.summary(), res.warnings))
        # стоковий CSV (без колонки) -- списки не чіпає
        stock = [[c for j, c in enumerate(r) if j != ri] for r in rows]
        tcsv.write_csv_rows(os.path.join(d, "Channels.csv"), stock)
        res = tcsv.import_dir(cp, d, dp=DP)
        R.check(tcsv.images_equal(res, cp), "Q3: CSV без колонки RoamList не змінює жодного байта (списки лишились як були)")
        # порожня комірка -- не чіпає
        rows2 = [list(r) for r in rows]
        for r in rows2[1:]:
            r[ri] = ""
        tcsv.write_csv_rows(os.path.join(d, "Channels.csv"), rows2)
        res = tcsv.import_dir(cp, d, dp=DP)
        R.check(tcsv.images_equal(res, cp), "Q3: порожні комірки RoamList не чіпають список")
        # 0..10: пише рівно байт 37 з міткою; решта запису незмінна
        for ch, val, byte in ((1, "7", 0xC7), (3, "0", 0x00), (3, "10", 0xCA), (130, "1", 0xC1)):
            tcsv.write_csv_rows(os.path.join(d, "Channels.csv"), rows)
            tcsv.edit_cell(os.path.join(d, "Channels.csv"), lambda r, c=ch: r[0] == str(c), "RoamList", val)
            res = tcsv.import_dir(cp, d, dp=DP)
            new = rec_of(res.image, ch)
            old = rec_of(img, ch)
            R.check(new[37] == byte, "Q3: канал %d, RoamList=%s -> байт 37 = 0x%02X (є 0x%02X)" % (ch, val, byte, new[37]))
            diff = [i for i in range(56) if new[i] != old[i]]
            R.check(diff in ([37], [37, 38]) and (new[38] ^ old[38]) in (0, old[38] & 1), "Q3: канал %d: змінився байт 37 і, щонайбільше, старий прапорець (біт 0 байта 38): байти %r" % (ch, diff))
            others = [n for n, r in img.channels() if n != ch and bytes(r) != rec_of(res.image, n)]
            R.check(others == [], "Q3: інші канали не зачеплено: %r" % others)
        # старий прапорець R59 у записі знімається, коли список ставить CSV (як і прошивка)
        flagged = set_flag(img, 1, True)
        cpf = img_to_codeplug(flagged, cp)
        cc.export_files(cpf, d, DP, log=lambda *_: None)
        tcsv.edit_cell(os.path.join(d, "Channels.csv"), lambda r: r[0] == "1", "RoamList", "4")
        res = tcsv.import_dir(cpf, d, dp=DP)
        R.check(rec_of(res.image, 1)[37] == 0xC4 and rec_of(res.image, 1)[38] & 1 == 0, "Q3: запис списку знімає старий прапорець (байт 38 біт 0)")
        # нісенітниця -- попередження, список як був
        for bad in ("можливо", "11", "-1", "1,5"):
            tcsv.write_csv_rows(os.path.join(d, "Channels.csv"), rows)
            tcsv.edit_cell(os.path.join(d, "Channels.csv"), lambda r: r[0] == "3", "RoamList", bad)
            res = tcsv.import_dir(cp, d, dp=DP)
            R.check(rec_of(res.image, 3) == rec_of(img, 3), "Q3: RoamList=%r лишає канал як був" % bad)
            R.check(any("RoamList" in w for w in res.warnings), "Q3: і про %r є попередження: %r" % (bad, res.warnings))
        # сміття в байті 37 (чужий CPS): не чіпаємо, поки CSV каже «0» (читається як 0)
        junk = bytearray(rec_of(img, 1))
        junk[37] = 0x5A
        imgj = img_copy(img)
        imgj.set_channel_rec(1, bytes(junk))
        cpj = img_to_codeplug(imgj, cp)
        cc.export_files(cpj, d, DP, log=lambda *_: None)
        res = tcsv.import_dir(cpj, d, dp=DP)
        R.check(tcsv.images_equal(res, cpj), "Q3: сміття 0x5A у байті 37 (це «без списку») експорт -> імпорт не зіпсував")
        # СТАРИЙ CSV R59: стовпець «Roam» (Yes/No) без «RoamList»
        cc.export_files(cp, d, DP, log=lambda *_: None)
        legacy = [list(r) for r in tcsv.read_csv_rows(os.path.join(d, "Channels.csv"))]
        lri = legacy[0].index("RoamList")
        legacy[0][lri] = "Roam"
        for r in legacy[1:]:
            r[lri] = "Yes" if r[0] in ("1", "2") else "No"
        tcsv.write_csv_rows(os.path.join(d, "Channels.csv"), legacy)
        res = tcsv.import_dir(cp, d, dp=DP)
        R.check(rec_of(res.image, 1)[37] == 0xC1 and rec_of(res.image, 2)[37] == 0xC1, "Q3: старий CSV: Roam=Yes -> список 1: %02X %02X" % (rec_of(res.image, 1)[37], rec_of(res.image, 2)[37]))
        R.check(rec_of(res.image, 3) == rec_of(img, 3) and rec_of(res.image, 130) == rec_of(img, 130),
                "Q3: старий CSV: Roam=No НЕ скидає списки каналів 3 (2) і 130 (10)")
        R.check(any("Roam" in w and "СПИСОК 1" in w for w in res.warnings) and any("Roam" in x[1] and "список 1" in x[1] for x in res.changed),
                "Q3: старий CSV: перенос у список 1 видно і в попередженнях, і у списку змін (діалог підтвердження): %r / %r" % (res.warnings, res.changed[:2]))
        # у старому CSV канал, що вже має список, лишається у своєму
        legacy2 = [list(r) for r in legacy]
        for r in legacy2[1:]:
            if r[0] == "3":
                r[lri] = "Yes"
        tcsv.write_csv_rows(os.path.join(d, "Channels.csv"), legacy2)
        res = tcsv.import_dir(cp, d, dp=DP)
        R.check(rec_of(res.image, 3)[37] == 0xC2, "Q3: старий CSV: Yes на каналі, що вже в списку 2, його НЕ переносить")
        # і нісенітниця в старому стовпці
        tcsv.edit_cell(os.path.join(d, "Channels.csv"), lambda r: r[0] == "1", "Roam", "можливо")
        res = tcsv.import_dir(cp, d, dp=DP)
        R.check(rec_of(res.image, 1) == rec_of(img, 1) and any("Roam" in w for w in res.warnings), "Q3: старий CSV: нісенітниця в «Roam» -- попередження, канал як був")


def suite_edit(R):
    w = roam_world(on=(1,))
    R.check(te.roam_numbers(w) == [1] and te.roam_numbers(w, 1) == [1] and te.roam_numbers(w, 2) == [], "Q4: roam_numbers: %r" % te.roam_numbers(w))
    res = te.channels_set_roam(w, [2, 5], 1)
    R.check(te.roam_numbers(res.image) == [1, 2, 5] and len(res.changed) == 2, "Q4: додано 2 і 5 до списку 1: %r / %r" % (te.roam_numbers(res.image), res.changed))
    for n in (1, 2, 3, 4, 5):
        a, b = rec_of(w, n), rec_of(res.image, n)
        d = [i for i in range(56) if a[i] != b[i]]
        R.check(d == ([37] if n in (2, 5) else []), "Q4: канал %d: змінені байти %r" % (n, d))
    R.check(rec_of(res.image, 2)[37] == 0xC1, "Q4: байт 37 каналу 2 = 0xC1")
    again = te.channels_set_roam(res.image, [2, 5], 1)
    R.check(not again.changed and bytes(again.image.eeprom) == bytes(res.image.eeprom) and bytes(again.image.flash) == bytes(res.image.flash),
            "Q4: повторне додавання нічого не змінює (ідемпотентно)")
    # перенос між списками: канал в одному списку
    mv = te.channels_set_roam(res.image, [2], 2)
    R.check(te.roam_numbers(mv.image, 1) == [1, 5] and te.roam_numbers(mv.image, 2) == [2] and len(mv.changed) == 1 and "перенесено зі списку 1 до списку 2" in mv.changed[0][1],
            "Q4: перенос каналу 2 зі списку 1 у 2: %r / %r" % (te.roam_numbers(mv.image, 1), mv.changed))
    off = te.channels_set_roam(mv.image, [1, 2, 5], 0)
    R.check(te.roam_numbers(off.image) == [] and len(off.changed) == 3, "Q4: прибрано всі: %r" % te.roam_numbers(off.image))
    R.check(all(rec_of(off.image, n)[37] == 0 for n in (1, 2, 5)), "Q4: байт 37 обнулено")
    try:
        te.channels_set_roam(w, [2, 999], 1)
        R.check(False, "Q4: відсутній канал -- відмова")
    except te.TableEditError as e:
        R.check("999" in str(e), "Q4: відмова називає канал")
    R.check(te.roam_numbers(w) == [1], "Q4: після відмови образ не змінено")
    for bad in (11, -1, 255, True, "1", None):
        try:
            te.channels_set_roam(w, [2], bad)
            R.check(False, "Q4: список %r відхилено" % (bad,))
        except te.TableEditError:
            R.check(True, "")
    # той самий результат через CSV-шлях редактора
    via = te.channel_edit(w, 2, {"RoamList": "1"}, DP)
    R.check(rec_of(via.image, 2) == rec_of(res.image, 2), "Q4: channel_edit({'RoamList': '1'}) дає ті самі байти, що channels_set_roam")
    via2 = te.channel_edit(res.image, 2, {"RoamList": "0"}, DP)
    R.check(rec_of(via2.image, 2)[37] == 0, "Q4: channel_edit({'RoamList': '0'}) знімає")
    # значення форми
    R.check(te.channel_values(w, 1, DP)["RoamList"] == "1" and te.channel_values(w, 2, DP)["RoamList"] == "0", "Q4: channel_values віддає RoamList")
    # новий канал на основі наявного успадковує список (дублікат -- той самий запис, крім назви й номера)
    dup = te.duplicate_entity(w, "channel", 1, DP)
    newn = [n for n in te.roam_numbers(dup.image) if n != 1]
    R.check(len(newn) == 1, "Q4: дублікат каналу зі списку теж зі списку (копія запису): %r" % te.roam_numbers(dup.image))
    # одноразове перенесення старого прапорця
    old = set_flag(set_flag(set_flag(w, 2, True), 3, True), 4, True)       # 1 -- у списку 1; 2, 3, 4 -- лише старий прапорець
    old = set_list(old, 3, 2)                                               # 3 має і список 2, і прапорець: список важливіший
    R.check(rc.legacy_channels(old) == [2, 4], "Q4: legacy_channels: канали з прапорцем без списку %r" % rc.legacy_channels(old))
    mig = te.roam_migrate_legacy(old)
    R.check(te.roam_numbers(mig.image, 1) == [1, 2, 4] and te.roam_numbers(mig.image, 2) == [3] and len(mig.changed) == 2,
            "Q4: roam_migrate_legacy: 2 і 4 -> список 1, 3 лишився в 2: %r / %r" % (te.roam_numbers(mig.image, 1), te.roam_numbers(mig.image, 2)))
    R.check(rec_of(mig.image, 2)[38] & 1 == 0 and rec_of(mig.image, 4)[38] & 1 == 0, "Q4: після перенесення старий прапорець знято")
    R.check(rec_of(mig.image, 3) == rec_of(old, 3), "Q4: канал із власним списком перенесення не чіпає (навіть прапорець)")
    R.check(not te.roam_migrate_legacy(mig.image).changed, "Q4: повторне перенесення нічого не робить")


def suite_r53(R):
    import random
    for seed in range(6):
        img = t53.world(seed)
        img, _n = rc.clear_lists(img)               # у фікстурі байт 37 / біт 0 -- сміття: починаємо з чистого стану
        names = {n: cc.readable_text(r[:16]) for n, r in img.channels()}
        rg = random.Random(seed)
        marked = {n: rg.randint(1, 10) for n in rg.sample(sorted(names), 7)}
        for n, k in marked.items():
            img = set_list(img, n, k)
        want = {names[n]: k for n, k in marked.items()}
        want_off = {names[n] for n in names if n not in marked}
        order = ro.idents(img, "channel")
        for _ in range(4):
            new = list(order)
            rg.shuffle(new)
            res = ro.permute(img, "channel", new)
            got = {cc.readable_text(r[:16]): rc.list_of(r) for n, r in res.image.channels() if rc.list_of(r)}
            got_off = {cc.readable_text(r[:16]) for n, r in res.image.channels() if not rc.list_of(r)}
            R.check(got == want and got_off == want_off, "Q5 [seed %d]: після перестановки номер списку лишився на тих самих каналах (за назвою)" % seed)
        n0 = order[3]
        res = ro.move(img, "channel", n0, -1)
        nm = names[n0]
        list_before = rc.list_of(dict(img.channels())[n0])
        found = [r for n, r in res.image.channels() if cc.readable_text(r[:16]) == nm]
        R.check(len(found) == 1 and rc.list_of(found[0]) == list_before, "Q5 [seed %d]: «Вище» несе номер списку з каналом" % seed)


def suite_warnings(R):
    ok = roam_world(on=(1, 2, 5))
    R.check(rc.check_list(ok, enabled=True) == [], "Q6: чистий список -- без попереджень: %r" % rc.check_list(ok, enabled=True))
    R.check(rc.check_list(ok, enabled=False) == [], "Q6: вимкнено -- теж чисто")
    one = roam_world(on=(1,))
    w = rc.check_list(one, enabled=True)
    R.check(len(w) == 1 and "жоден список" in w[0], "Q6: увімкнено, а у списку 1 канал: %r" % w)
    R.check(rc.check_list(one, enabled=False) == [], "Q6: вимкнено -- про «менше 2» не нагадуємо")
    none = roam_world()
    w = rc.check_list(none, enabled=True)
    R.check(len(w) == 1 and "жоден список" in w[0], "Q6: увімкнено, списки порожні: %r" % w)
    # один список з 2+, інший з одним каналом
    mixed = set_list(roam_world(on=(1, 2)), 5, 3)
    w = rc.check_list(mixed, enabled=True)
    R.check(len(w) == 1 and "У списку 3 лише один канал (№5)" in w[0], "Q6: список 3 з одним каналом при списку 1 з двома: %r" % w)
    R.check(rc.check_list(mixed, enabled=False) == [], "Q6: вимкнено -- про самотній канал не нагадуємо")
    # аналоговий
    w = rc.check_list(roam_world(on=(1, 4)), enabled=False)
    R.check(len(w) == 1 and "№4" in w[0] and "аналог" in w[0] and "списку 1" in w[0], "Q6: аналоговий у списку: %r" % w)
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
    R.check(len(w) == 1 and "№1" in w[0] and "№2" in w[0] and "однакові" in w[0] and "списку 1" in w[0], "Q6: дублі частот+колір-код в одному списку: %r" % w)
    # ті самі частоти й колір-код, але в РІЗНИХ списках -- не дубль
    dd = set_list(d, 2, 2)
    R.check(rc.check_list(dd, enabled=False) == [], "Q6: однакові пари в різних списках -- не дубль: %r" % rc.check_list(dd, enabled=False))
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
    # старий прапорець без списку
    lg = set_flag(roam_world(on=(1, 2)), 5, True)
    w = rc.check_list(lg, enabled=False)
    R.check(len(w) == 1 and "СТАРИМ" in w[0] and "1" in w[0], "Q6: старий прапорець без списку: %r" % w)
    # прапорці без блока в рації
    w = rc.check_list(ok, enabled=False, block_absent=True)
    R.check(len(w) == 1 and "блока налаштувань" in w[0] and "3" in w[0], "Q6: списки є, блока в рації нема: %r" % w)
    R.check(rc.check_list(none, enabled=False, block_absent=True) == [], "Q6: блока нема, але й каналів у списках нема -- мовчимо")
    # очищення всіх списків
    out, n = rc.clear_lists(ok)
    R.check(n == 3 and te.roam_numbers(out) == [], "Q6: clear_lists знімає всі: %d" % n)
    R.check(all(rec_of(out, k)[:37] == rec_of(ok, k)[:37] and rec_of(out, k)[39:] == rec_of(ok, k)[39:] for k in (1, 2, 3, 4, 5)), "Q6: clear_lists не чіпає інші байти (крім 37 і 38)")


def suite_roundtrip(R):
    """Радіо ↔ CPS: ті самі дані. «Радіо» тут -- справжня семантика прошивки (roamListFromByte/ToByte, перевірена у Q1 проти roam_cfg.c): запис списку з меню рації
    = ОДИН запис каналу з байтом 0xC0|N і знятим старим прапорцем; CPS має прочитати його так само й навпаки."""
    img = roam_world(on=(1, 2, 5))
    # «рація» додає канал 3 до списку 1, а канал 2 переносить у список 2
    radio = img_copy(img)
    for n, k in ((3, 1), (2, 2)):
        r = bytearray(rec_of(radio, n))
        r[37] = 0xC0 | k
        r[38] &= 0xFE
        radio.set_channel_rec(n, bytes(r))
    R.check(te.roam_numbers(radio, 1) == [1, 3, 5] and te.roam_numbers(radio, 2) == [2], "Q10: CPS читає списки, записані «рацією»: %r %r" % (te.roam_numbers(radio, 1), te.roam_numbers(radio, 2)))
    # CPS робить ті самі зміни -- байти записів ідентичні рація == CPS
    cps = te.channels_set_roam(te.channels_set_roam(img, [3], 1).image, [2], 2).image
    R.check(all(rec_of(cps, n) == rec_of(radio, n) for n in range(1, 6)), "Q10: ті самі зміни в CPS і в «рації» дають ТОЙ САМИЙ байт-у-байт запис каналів")
    # CSV того, що зробила «рація», повертається без втрат
    _img0, cp = fixture_image()
    cpr = img_to_codeplug(radio, cp)
    with tempfile.TemporaryDirectory() as d:
        cc.export_files(cpr, d, DP, log=lambda *_: None)
        res = tcsv.import_dir(cpr, d, dp=DP)
        R.check(tcsv.images_equal(res, cpr) and not res.warnings, "Q10: кодплаг із «радійними» списками -> CSV -> імпорт == він сам")
        rows = tcsv.read_csv_rows(os.path.join(d, "Channels.csv"))
        ri = rows[0].index("RoamList")
        by = {r[0]: r[ri] for r in rows[1:]}
        R.check([by.get(str(n)) for n in (1, 2, 3, 5)] == ["1", "2", "1", "1"], "Q10: у CSV ті самі номери списків: %r" % [by.get(str(n)) for n in (1, 2, 3, 5)])
    # зміни, які CPS пише у кодплаг, «рація» бачить за правилом прошивки
    for n, r in cps.channels():
        fw = (r[37] & 0x0F) if ((r[37] & 0xF0) == 0xC0 and 1 <= (r[37] & 0x0F) <= 10) else 0
        R.check(fw == rc.list_of(r), "Q10: канал %d -- правило прошивки і CPS однакові (%d)" % (n, fw))
    # кожен із 10 списків проходить CPS -> байт -> «рація» -> CPS без втрат
    for k in range(1, 11):
        x = te.channels_set_roam(img, [4], k).image
        R.check(rec_of(x, 4)[37] == 0xC0 | k and rc.list_of(rec_of(x, 4)) == k, "Q10: список %d: байт 0x%02X і назад" % (k, rec_of(x, 4)[37]))


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


SUITES = (suite_constants, suite_list_byte, suite_payload, csv_roundtrip, suite_edit, suite_r53, suite_warnings, suite_roundtrip, suite_write, suite_region)


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
            col = cc.CH_COLUMN_BY_NAME["RoamList"]
            old = col[key]
            col[key] = val
            return lambda: col.__setitem__(key, old)
        return apply

    def patch_cols(**kv):
        def apply():
            col = cc.CH_COLUMN_BY_NAME["RoamList"]
            old = {k: col[k] for k in kv}
            col.update(kv)
            return lambda: col.update(old)
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
    # --- байт списку (Python-бік; C-бік перевіряє test_roam_cfg + звірка Q1) ---
    out.append(("list_from_byte: без перевірки мітки", patch(rc, "list_from_byte", lambda b: (b & 0x0F) if 1 <= (b & 0x0F) <= 10 else 0)))
    out.append(("list_from_byte: мітка лише старший біт", patch(rc, "list_from_byte", lambda b: (b & 0x0F) if (b & 0x80) and 1 <= (b & 0x0F) <= 10 else 0)))
    out.append(("list_from_byte: 11 теж список", patch(rc, "list_from_byte", lambda b: (b & 0x0F) if (b & 0xF0) == 0xC0 and 1 <= (b & 0x0F) <= 11 else 0)))
    out.append(("list_to_byte: без мітки", patch(rc, "list_to_byte", lambda n: n if 1 <= n <= 10 else 0)))
    out.append(("list_to_byte: пише 11", patch(rc, "list_to_byte", lambda n: (0xC0 | n) if 1 <= n <= 11 else 0)))
    out.append(("list_to_byte: 0 -> 0xC0", patch(rc, "list_to_byte", lambda n: (0xC0 | n) if 0 <= n <= 10 else 0)))
    out.append(("LIST_BYTE_OFFSET 36", patch(rc, "LIST_BYTE_OFFSET", 36)))
    out.append(("cps_csv: інший байт списку", patch(cc, "O_ROAMLIST", 39)))
    out.append(("cps_csv: інша мітка", patch(cc, "ROAM_TAG", 0xB0)))
    # --- CSV ---
    out.append(("«RoamList» не потрапляє в заголовок CSV", patch(cc, "CHANNEL_EXT_HDR", [])))
    out.append(("колонка RoamList не м'яка (порожня комірка змінює)", patch_col("soft", False)))
    out.append(("колонка RoamList лише для цифрових", patch_col("app", "D")))
    out.append(("RoamList: dec віддає сирий байт", patch_col("dec", lambda r, c: str(r[37]))))
    out.append(("RoamList: dec без перевірки мітки", patch_col("dec", lambda r, c: str(r[37] & 0x0F))))
    real_enc = cc.CH_COLUMN_BY_NAME["RoamList"]["enc"]

    def enc_no_range(r, t, c):
        n = int((t or "0").strip() or 0)
        r[37] = (0xC0 | n) if n else 0
        r[38] &= 0xFE
    out.append(("RoamList: enc без перевірки меж (11 пишеться)", patch_col("enc", enc_no_range)))

    def enc_keep_flag(r, t, c):
        f = r[38]
        real_enc(r, t, c)
        r[38] = f
    out.append(("RoamList: enc не знімає старий прапорець", patch_col("enc", enc_keep_flag)))

    def enc_plain(r, t, c):
        real_enc(r, t, c)
        if r[37]:
            r[37] &= 0x0F
    out.append(("RoamList: enc пише номер без мітки", patch_col("enc", enc_plain)))
    out.append(("legacy: стовпець «Roam» не читається", patch(cc, "LEGACY_ROAM_COL", "НеіснуючийСтовпець")))
    real_set_list = cc.roam_list_set
    out.append(("legacy: Roam=Yes -> список 2", patch(cc, "roam_list_set", lambda r, n: real_set_list(r, 2 if n == 1 else n))))
    # --- table_edit ---
    real_set = te.channels_set_roam

    def set_wrong_byte(img, numbers, lst):
        out_img = cc.Image(img.eeprom, img.flash, img.base)
        res = cc.ImportResult()
        res.image = out_img
        for n in sorted(set(numbers)):
            r = bytearray(dict(img.channels())[n])
            r[39] = (0xC0 | lst) if lst else 0
            out_img.set_channel_rec(n, bytes(r))
            res.changed.append(("Канали", "№%d" % n))
        return res
    out.append(("channels_set_roam пише не той байт", patch(te, "channels_set_roam", set_wrong_byte)))

    def set_no_missing_check(img, numbers, lst):
        return real_set(img, [n for n in numbers if n in dict(img.channels())], lst)
    out.append(("channels_set_roam ковтає відсутній канал", patch(te, "channels_set_roam", set_no_missing_check)))

    def set_always_changed(img, numbers, lst):
        res = real_set(img, numbers, lst)
        if not res.changed:
            res.changed.append(("Канали", "фіктивна зміна"))
        return res
    out.append(("channels_set_roam рапортує зміну, якої нема", patch(te, "channels_set_roam", set_always_changed)))
    out.append(("channels_set_roam без перевірки списку", patch(te, "channels_set_roam", lambda img, numbers, lst: real_set(img, numbers, min(max(lst, 0), 10)) if not isinstance(lst, int) or lst in range(0, 11) else real_set(img, numbers, 0))))
    out.append(("roam_numbers ігнорує список", patch(te, "roam_numbers", lambda img, lst=None: [n for n, r in img.channels() if rc.list_of(r)])))
    out.append(("roam_numbers бере всі канали", patch(te, "roam_numbers", lambda img, lst=None: [n for n, _r in img.channels()])))
    out.append(("with_list не знімає старий прапорець", patch(rc, "with_list", lambda rec, lst: bytes(rec[:37]) + bytes([rc.list_to_byte(lst)]) + bytes(rec[38:]))))
    out.append(("with_list чіпає ще й байт 39", patch(rc, "with_list", lambda rec, lst: bytes(rec[:37]) + bytes([rc.list_to_byte(lst), rec[38] & 0xFE, 0]) + bytes(rec[40:]))))
    out.append(("legacy_channels бере й канали зі списком", patch(rc, "legacy_channels", lambda img: [n for n, r in img.channels() if rc.legacy_flag(r)])))
    out.append(("legacy_channels не бачить прапорця", patch(rc, "legacy_channels", lambda img: [])))
    out.append(("міграція кладе в список 2", patch(te, "roam_migrate_legacy", lambda img: real_set(img, rc.legacy_channels(img), 2))))
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
    out.append(("pair_key враховує ще й назву", patch(rc, "pair_key", lambda r: (rc._freq(r, 16), rc._freq(r, 20), r[44], r[2]))))
    real_check = rc.check_list
    out.append(("check_list без попередження «жоден список»", patch(rc, "check_list", lambda img, enabled=False, block_absent=False: [w for w in real_check(img, enabled, block_absent) if "жоден список" not in w])))
    out.append(("check_list без попередження про самотній канал", patch(rc, "check_list", lambda img, enabled=False, block_absent=False: [w for w in real_check(img, enabled, block_absent) if "лише один канал" not in w])))
    out.append(("check_list без попередження про старий прапорець", patch(rc, "check_list", lambda img, enabled=False, block_absent=False: [w for w in real_check(img, enabled, block_absent) if "СТАРИМ" not in w])))
    out.append(("check_list без попередження «блока нема»", patch(rc, "check_list", lambda img, enabled=False, block_absent=False: real_check(img, enabled, False))))
    out.append(("check_list завжди як «увімкнено»", patch(rc, "check_list", lambda img, enabled=False, block_absent=False: real_check(img, True, block_absent))))
    out.append(("clear_lists знімає не все", patch(rc, "clear_lists", lambda img: (img, 0))))
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
