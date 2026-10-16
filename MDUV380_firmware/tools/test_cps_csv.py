#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Хост-тести R26 V1: tools/cps_csv.py (CSV-обмін кодплуга у форматі OpenGD77 CPS). Без рації, без pyserial.

T1  кругова оборотність: експорт -> імпорт без правок повертає кодплуг БАЙТ-У-БАЙТ (зі сміттям у неописаних полях);
T2  кирилиця в обидва боки (GBK з CPS і cp1251 з рації), правки сумісної й читабельної колонок;
T3  кома й крапка (читаємо обидві, пишемо за заданим знаком);
T4  табуляція перед частотами;
T5  зона з неіснуючим каналом / TG-список з неіснуючим контактом -> відмова ДО запису (жодного X у підставній рації);
T6  ліміт назви 16 байтів (GBK/cp1251) з поясненням;
плюс: вибір кодування V1.9, нове/змінене/видалене, імпорт у рацію через шлях відновлення (страхова копія, діалог зі списком змін).
"""
import csv
import os
import random
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cps_link as cl            # noqa: E402
import cps_csv as cc             # noqa: E402
import codeplug_view as cv       # noqa: E402
import test_cps_link as base     # noqa: E402
import test_cps_restore as tr    # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def bcd4(v):
    return bytes.fromhex("%08d" % v)


def chan(name_raw, rx, tx, digital, **kw):
    """Канал із ВІДОМИМИ значеннями полів + СМІТТЯМ у неописаних байтах (37, 42, 52..54, невикористані біти прапорців)."""
    rg = random.Random(sum(name_raw) + rx)
    r = bytearray(rg.getrandbits(8) for _ in range(56))      # сміття всюди, далі перекриваємо відомі поля
    r[0:16] = name_raw.ljust(16, b"\xff")
    r[16:20] = bytes.fromhex("%08d" % rx)[::-1]
    r[20:24] = bytes.fromhex("%08d" % tx)[::-1]
    r[24] = 1 if digital else 0
    r[25] = kw.get("power", 0)
    r[27] = kw.get("tot", 0)
    r[32:34] = struct.pack("<H", kw.get("rxtone", 0xFFFF))
    r[34:36] = struct.pack("<H", kw.get("txtone", 0xFFFF))
    r[38] = (0x80 if kw.get("dmrid") else 0) | (r[38] & 0x17)              # 0x17: сміттєві біти, не описані в CSV
    if kw.get("dmrid"):
        r[39:42] = bytes([(kw["dmrid"] >> 16) & 255, (kw["dmrid"] >> 8) & 255, kw["dmrid"] & 255])
    r[43] = kw.get("group", 0)
    r[44] = kw.get("cc", 1)
    r[45] = kw.get("aprs", 0)
    struct.pack_into("<H", r, 46, kw.get("contact", 0))
    r[48] = (r[48] & 0xF0) | kw.get("ta", 0)
    r[49] = (r[49] & 0xBF) | (0x40 if kw.get("ts2") else 0)
    r[51] = (r[51] & 0x88) | kw.get("f4", 0)
    r[55] = kw.get("sql", 0)
    return bytes(r)


GBK_PAPUGA = "Папуга".encode("gbk")
CP_IZHAK = "Їжак".encode("cp1251")


def make_fixture_spi():
    spi = base.make_spi()
    cp_ee = bytearray(spi[:cl.EEPROM_BACKUP_LEN])
    rng = cl.flash_backup_range()
    fl = bytearray(spi[rng["raw_start"]:rng["raw_start"] + rng["length"]])
    img = cc.Image(cp_ee, fl, rng["codeplug_start"])
    # --- контакти (слоти 0,1,2,10 уже є з make_spi; додаємо зі сміттям у ringStyle/rxTone) ---
    for slot in (0, 1, 2, 10):
        rec = bytearray(img.fl(cl.CP_ADDR_CONTACTS + slot * 24, 24))
        rec[21], rec[22] = 3, (0x01 if slot != 1 else 0x02)
        img.set_contact(slot, bytes(rec))
    # --- канали: 1 цифровий Папуга, 2 аналоговий, 3 цифровий кирилиця cp1251, 130 (банк 1, флеш) ---
    img.set_channel_rec(1, chan(GBK_PAPUGA, 44600625, 44600625, True, cc=3, contact=1, group=1, ts2=True, ta=1, dmrid=2504012, power=9,
                                f4=0x20))
    img.set_channel_rec(2, chan(b"PMR 1", 44600625, 44600625, False, rxtone=0x0885, txtone=0x8000 | 0x4000 | 0x23, power=5, tot=4, sql=8,
                                f4=0x02 | 0x40))
    img.set_channel_rec(3, chan("ЇЖАК ҐЄІіїєґ".encode("cp1251"), 43050000, 43850000, True, contact=2, group=5, aprs=1, ta=2, f4=0x04 | 0x10))
    img.set_channel_rec(130, chan(b"Flash ch", 14480000, 14480000, False, power=1))
    for n in (1, 2, 3, 130):
        img.set_channel_in_use(n, True)
    # --- TG-списки: слот 0 (Ukraine: контакти 1,2,3), слот 4 (Група: контакт 2) ---
    g0 = bytearray(img.fl(cl.CP_ADDR_RX_GROUP, 80))
    g0[16:80] = struct.pack("<3H", 1, 2, 3).ljust(64, b"\x00")
    img.set_group(0, bytes(g0), 3)
    g4 = bytearray(img.fl(cl.CP_ADDR_RX_GROUP + 4 * 80, 80))
    g4[16:80] = struct.pack("<H", 2).ljust(64, b"\x00")
    img.set_group(4, bytes(g4), 1)
    # --- зони: стандартні з make_spi + склад ---
    st = img.zone_stride()
    for bit, members in ((0, (1, 3)), (1, (2,)), (5, (1, 2, 3, 130))):
        rec = bytearray(img.ee(cl.CP_ADDR_EX_ZONE_LIST + bit * st, st))
        rec[16:st] = b"".join(struct.pack("<H", v) for v in members).ljust(st - 16, b"\x00")
        img.set_zone(bit, bytes(rec))
    # --- APRS ---
    a = bytearray(b"\x00" * 64)
    a[0:8] = b"APRS\xff\xff\xff\xff"
    a[8] = 7
    a[9:12] = bytes([0x7C, 0x00, 0x30])          # 48,0098: ціла 48 -> (48<<15)|98
    v = (48 << 15) | 98
    a[9:12] = bytes([v & 255, (v >> 8) & 255, v >> 16])
    v = (33 << 15) | 4845
    a[12:15] = bytes([v & 255, (v >> 8) & 255, v >> 16])
    a[15:21] = b"WIDE1\x00"
    a[21] = 1
    a[22:28] = b"WIDE2\x00"
    a[28] = 1
    a[29], a[30] = 0, 58
    a[31:55] = b"TYT MD-UV390".ljust(24, b"\x00")
    struct.pack_into("<I", a, 55, 14480000)
    a[61] = 0x02 | 0x04
    struct.pack_into("<H", a, 62, cc.APRS_MAGIC)
    img.set_aprs(0, bytes(a))
    # --- DTMF ---
    d = b"Test DTMF".ljust(16, b"\xff") + bytes([1, 2, 3, 10, 11, 12, 13, 14]) + b"\xff" * 8
    img.set_dtmf(0, d)
    spi[:cl.EEPROM_BACKUP_LEN] = img.eeprom
    spi[rng["raw_start"]:rng["raw_start"] + rng["length"]] = img.flash
    return spi


def codeplug_of(spi):
    radio = base.FakeRadio(spi)
    data, _m = cl.backup_codeplug(cl.CpsLink(radio), rng=random.Random(5), log=lambda *_: None)
    cp, _man = cv.codeplug_from_backup(data)
    return cp, data


def export_dir(cp, d, dp=","):
    cc.export_files(cp, d, dp, log=lambda *_: None)
    return d


def read_csv_rows(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.reader(f, delimiter=";"))


def write_csv_rows(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f, delimiter=";", lineterminator="\r\n").writerows(rows)


def import_dir(cp, d, **kw):
    return cc.import_csv(cp, cc.read_dir(d), **kw)


def images_equal(res, cp):
    return bytes(res.image.eeprom) == bytes(cp.eeprom) and bytes(res.image.flash) == bytes(cp.flash)


def edit_cell(path, row_pred, col, value):
    rows = read_csv_rows(path)
    hdr = rows[0]
    ci = hdr.index(col)
    n = 0
    for r in rows[1:]:
        if row_pred(r):
            r[ci] = value
            n += 1
    check(n >= 1, "edit_cell: рядок знайдено у %s" % os.path.basename(path))
    write_csv_rows(path, rows)


# ----------------------------------------------------------------------------------------

def test_format_and_roundtrip():
    spi = make_fixture_spi()
    cp, _data = codeplug_of(spi)
    for dp in (",", "."):
        with tempfile.TemporaryDirectory() as d:
            export_dir(cp, d, dp)
            # --- формат файлів ---
            check(sorted(os.listdir(d)) == sorted(cc.FILE_NAMES.values()), "створено шість файлів: %r" % sorted(os.listdir(d)))
            raw = open(os.path.join(d, "Channels.csv"), "rb").read()
            check(not raw.startswith(b"\xef\xbb\xbf"), "без BOM")
            check(b"\r\n" in raw and raw.count(b"\n") == raw.count(b"\r\n"), "кінці рядків CRLF")
            hdr = raw.split(b"\r\n")[0].decode("utf-8").split(";")
            check(hdr[:len(cc.CHANNEL_HDR)] == cc.CHANNEL_HDR and hdr[-1] == cc.READABLE, "заголовок Channels.csv: CPS-колонки + «Name (readable)»")
            check([c["name"] for c in cc.CH_COLUMNS] == cc.CHANNEL_HDR[2:], "колонки CH_COLUMNS == заголовок CPS (без №, назви)")
            rows = read_csv_rows(os.path.join(d, "Channels.csv"))
            by_num = {r[0]: r for r in rows[1:]}
            check(rows[0].index("Rx Frequency") == 3 and by_num["1"][3] == "\t446" + dp + "00625", "частота з табуляцією попереду: %r" % by_num["1"][3])
            check(by_num["2"][13] == "88" + dp + "5" and by_num["2"][14].startswith("D023I"), "тони: %r / %r" % (by_num["2"][13], by_num["2"][14]))
            check(by_num["2"][6] == "" and by_num["2"][7] == "", "поля цифри для аналогового каналу порожні")
            check(by_num["1"][5] == "" and by_num["1"][13] == "", "поля аналога для цифрового каналу порожні")
            # --- T1: байт-у-байт ---
            res = import_dir(cp, d, dp=dp)
            check(images_equal(res, cp), "T1 (%r): експорт -> імпорт без правок == вихідний кодплуг БАЙТ-У-БАЙТ" % dp)
            check(not res.any_change() and not res.warnings, "T1: жодної зміни й жодного попередження: %s %r" % (res.summary(), res.warnings))


def test_cyrillic():
    spi = make_fixture_spi()
    cp, _data = codeplug_of(spi)
    with tempfile.TemporaryDirectory() as d:
        export_dir(cp, d)
        ch = read_csv_rows(os.path.join(d, "Channels.csv"))
        names = {r[0]: (r[1], r[-1]) for r in ch[1:]}
        check(names["1"][0] == "§±§Ñ§á§å§Ô§Ñ", "T2: «Папуга» у сумісній колонці як у CPS: %r" % names["1"][0])
        check(names["1"][0].encode("latin-1") == GBK_PAPUGA, "T2: сумісна колонка -> latin-1 -> сирі байти GBK")
        check(names["1"][1] == "Папуга", "T2: читабельна колонка: %r" % names["1"][1])
        check(names["3"][0].encode("latin-1") == "ЇЖАК ҐЄІіїєґ".encode("cp1251") and names["3"][1] == "ЇЖАК ҐЄІіїєґ", "T2: cp1251-назва з рації")
        co = read_csv_rows(os.path.join(d, "Contacts.csv"))
        check(any(r[0] == "§±§Ñ§á§å§Ô§Ñ" and r[-1] == "Папуга" for r in co[1:]), "T2: Contacts.csv має ту саму пару")

        # --- читання «CPS-подібного» файла (без читабельної колонки): сумісна колонка -> сирі байти ---
        with tempfile.TemporaryDirectory() as d2:
            export_dir(cp, d2)
            for fn in cc.FILE_NAMES.values():
                rows = read_csv_rows(os.path.join(d2, fn))
                write_csv_rows(os.path.join(d2, fn), [r[:-1] for r in rows])
            res = import_dir(cp, d2)
            check(images_equal(res, cp), "T2: файл БЕЗ читабельної колонки (як від CPS) -> теж байт-у-байт")

        # --- правка ЧИТАБЕЛЬНОЇ колонки (сумісну не чіпали) -> нова назва кодується за V1.9 ---
        for newname, want_enc, raw_check in (("Дракон", "GBK", "Дракон".encode("gb2312")), ("Ґанок", "cp1251", "Ґанок".encode("cp1251")),
                                             ("Київ-1", "cp1251", "Київ-1".encode("cp1251")), ("Mixed Дом", "GBK", "Mixed Дом".encode("gb2312"))):
            with tempfile.TemporaryDirectory() as d3:
                export_dir(cp, d3)
                p = os.path.join(d3, "Channels.csv")
                for fn in ("Zones.csv", "TG_Lists.csv"):          # зони посилаються на канали ЗА НАЗВОЮ -- їх лишати не можна
                    os.unlink(os.path.join(d3, fn))
                edit_cell(p, lambda r: r[0] == "2", cc.READABLE, newname)
                sess = cc.Session()
                res = import_dir(cp, d3, session=sess)
                rec = res.image.channel_rec(2)
                check(rec[:16].rstrip(b"\xff") == raw_check, "T2: %r записано як %s: %r" % (newname, want_enc, rec[:16]))
                check(cv.decode_name_ex(rec[:16]) == (newname, want_enc if want_enc != "GBK" or any(ord(c) > 127 for c in newname) else "ASCII"),
                      "T2: %r читається назад однаково: %r" % (newname, cv.decode_name_ex(rec[:16])))
                warned = any("cp1251" in w for w in res.warnings)
                check(warned == (want_enc == "cp1251"), "V1.9: попередження про cp1251 для %r: %r" % (newname, res.warnings))
                if warned:
                    res2 = import_dir(cp, d3, session=sess)
                    check(not any("cp1251" in w for w in res2.warnings), "V1.9: у межах сеансу попередження лише ОДИН раз")
                check(len(res.changed) == 1 and "Канали" == res.changed[0][0], "T2: змінено лише цей канал: %r" % res.changed)
        # --- правка СУМІСНОЇ колонки (як у CPS) -> сирі байти з latin-1 ---
        with tempfile.TemporaryDirectory() as d4:
            export_dir(cp, d4)
            os.unlink(os.path.join(d4, "Zones.csv"))
            edit_cell(os.path.join(d4, "Channels.csv"), lambda r: r[0] == "2", "Channel Name", "§±§Ñ§á")
            res = import_dir(cp, d4)
            check(res.image.channel_rec(2)[:16] == "Пап".encode("gbk").ljust(16, b"\xff"), "T2: правка сумісної колонки -> байти GBK")
        # --- ASCII-латиниця у сумісній ---
        with tempfile.TemporaryDirectory() as d5:
            export_dir(cp, d5)
            os.unlink(os.path.join(d5, "Zones.csv"))
            edit_cell(os.path.join(d5, "Channels.csv"), lambda r: r[0] == "2", "Channel Name", "PMR 2")
            edit_cell(os.path.join(d5, "Channels.csv"), lambda r: r[0] == "2", cc.READABLE, "PMR 1")        # читабельну не міняли
            res = import_dir(cp, d5)
            check(res.image.channel_rec(2)[:16] == b"PMR 2".ljust(16, b"\xff"), "T2: сумісна колонка -- джерело істини, коли її змінено")


def test_decimal_and_tab():
    spi = make_fixture_spi()
    cp, _data = codeplug_of(spi)
    outs = {}
    for dp in (",", "."):
        with tempfile.TemporaryDirectory() as d:
            export_dir(cp, d, dp)
            outs[dp] = open(os.path.join(d, "Channels.csv"), "rb").read().decode("utf-8")
    check(outs[","] != outs["."] and outs[","].replace(",", ".") == outs["."].replace(",", "."), "T3: два експорти відрізняються лише десятковим знаком")
    check("446,00625" in outs[","] and "446.00625" in outs["."], "T3: кома / крапка в частотах")
    # --- читання: у файл з комами руками вписано крапку в одній клітинці й кому -- в іншій; з табуляцією й без ---
    for rx_text, tx_text in (("\t433,5", "433.6"), ("433.5", "\t433,6"), (" 433,500 ", "433,60000\t")):
        with tempfile.TemporaryDirectory() as d:
            export_dir(cp, d, ",")
            p = os.path.join(d, "Channels.csv")
            edit_cell(p, lambda r: r[0] == "2", "Rx Frequency", rx_text)
            edit_cell(p, lambda r: r[0] == "2", "Tx Frequency", tx_text)
            res = import_dir(cp, d)
            rec = res.image.channel_rec(2)
            check(cv.freq_bcd_le(rec[16:20]) == 43350000 and cv.freq_bcd_le(rec[20:24]) == 43360000,
                  "T3/T4: %r / %r прочитано як 433,5 / 433,6: %r" % (rx_text, tx_text, (cv.freq_bcd_le(rec[16:20]), cv.freq_bcd_le(rec[20:24]))))
            check(len(res.changed) == 1 and "Rx Frequency" in res.changed[0][1], "T3: у звіті змінена колонка частоти: %r" % res.changed)
    # --- тон: 88,5 vs 88.5 ---
    for t in ("123.0", "123,0"):
        with tempfile.TemporaryDirectory() as d:
            export_dir(cp, d, ",")
            edit_cell(os.path.join(d, "Channels.csv"), lambda r: r[0] == "2", "RX Tone", t)
            res = import_dir(cp, d)
            check(struct.unpack_from("<H", res.image.channel_rec(2), 32)[0] == 0x1230, "T3: CTCSS %r -> 0x1230" % t)
    # --- системна локаль не змінюється побічно ---
    import locale
    before = locale.setlocale(locale.LC_NUMERIC)
    cc.system_decimal_point()
    check(locale.setlocale(locale.LC_NUMERIC) == before, "V1.4: визначення десяткового знака не міняє глобальну локаль")
    # --- табуляція у вихідному файлі: ПЕРЕД частотою, в усіх частотних клітинках ---
    rows = outs[","].split("\r\n")[1:]
    check(all(r.split(";")[3].startswith("\t") and r.split(";")[4].startswith("\t") for r in rows if r and "0xFFFFFFFF" not in r), "T4: усі частоти в експорті з табуляцією")
    # --- сміття у частотному полі не губиться: 0x-форма ---
    spi2 = bytearray(spi)
    cp2, _ = codeplug_of(spi2)
    img = cc.Image.from_codeplug(cp2)
    rec = bytearray(img.channel_rec(2))
    rec[16:20] = bytes([0xAB, 0xCD, 0xEF, 0x12])
    img.set_channel_rec(2, bytes(rec))
    with tempfile.TemporaryDirectory() as d:
        cc.export_files(img, d, ",", log=lambda *_: None)
        res = import_dir(img, d)
        check(images_equal(res, img) is False or bytes(res.image.eeprom) == bytes(img.eeprom), "не-BCD частота: імпорт без правок її не псує")


def test_refusals():
    spi = make_fixture_spi()
    cp, _data = codeplug_of(spi)
    # --- зона -> неіснуючий канал ---
    with tempfile.TemporaryDirectory() as d:
        export_dir(cp, d)
        z = os.path.join(d, "Zones.csv")
        rows = read_csv_rows(z)
        rows[1][2] = "Нема такого каналу"
        rows[2][1] = "Теж нема"
        write_csv_rows(z, rows)
        try:
            import_dir(cp, d)
            check(False, "T5: імпорт зони з неіснуючим каналом мав бути відхилений")
        except cc.CsvImportRefused as e:
            txt = str(e)
            check("Нема такого каналу" in txt and "Теж нема" in txt, "T5: у відмові названо ВСІ відсутні канали: %s" % txt)
            check(len(e.problems) == 2, "T5: проблем рівно 2: %r" % e.problems)
    # --- TG-список -> неіснуючий контакт, окремо від нормального ---
    with tempfile.TemporaryDirectory() as d:
        export_dir(cp, d)
        t = os.path.join(d, "TG_Lists.csv")
        rows = read_csv_rows(t)
        rows[1][1] = "Привид"
        write_csv_rows(t, rows)
        try:
            import_dir(cp, d)
            check(False, "T5: TG-список з неіснуючим контактом мав бути відхилений")
        except cc.CsvImportRefused as e:
            check("Привид" in str(e), "T5: названо відсутній контакт")
    # --- канал -> неіснуючий контакт / TG-список ---
    with tempfile.TemporaryDirectory() as d:
        export_dir(cp, d)
        p = os.path.join(d, "Channels.csv")
        edit_cell(p, lambda r: r[0] == "1", "Contact", "Немає контакту")
        edit_cell(p, lambda r: r[0] == "1", "TG List", "Немає списку")
        try:
            import_dir(cp, d)
            check(False, "канал з неіснуючими посиланнями мав бути відхилений")
        except cc.CsvImportRefused as e:
            check("Немає контакту" in str(e) and "Немає списку" in str(e), "обидва відсутні посилання названо: %s" % e)
    # --- видалення контакту, на який посилається канал (завантажено лише Contacts.csv) ---
    with tempfile.TemporaryDirectory() as d:
        export_dir(cp, d)
        for fn in list(cc.FILE_NAMES.values()):
            if fn != "Contacts.csv":
                os.unlink(os.path.join(d, fn))
        rows = read_csv_rows(os.path.join(d, "Contacts.csv"))
        keep = [rows[0]] + [r for r in rows[1:] if r[-1] != "LOCAL"]
        write_csv_rows(os.path.join(d, "Contacts.csv"), keep)
        try:
            import_dir(cp, d)
            check(False, "видалення контакту LOCAL, що в TG-списку / каналі, мало бути відхилене")
        except cc.CsvImportRefused as e:
            check("LOCAL" in str(e) or "контакт №3" in str(e), "названо видалений контакт: %s" % e)
    # --- дублікат Channel Number, число поза межами, нечисло ---
    with tempfile.TemporaryDirectory() as d:
        export_dir(cp, d)
        p = os.path.join(d, "Channels.csv")
        rows = read_csv_rows(p)
        rows[2][0] = rows[1][0]
        write_csv_rows(p, rows)
        try:
            import_dir(cp, d)
            check(False, "дублікат Channel Number")
        except cc.CsvImportRefused as e:
            check("вже є" in str(e), "дублікат номера названо")
    # --- заборонені значення в «жорстких» колонках ---
    with tempfile.TemporaryDirectory() as d:
        export_dir(cp, d)
        p = os.path.join(d, "Channels.csv")
        edit_cell(p, lambda r: r[0] == "2", "Rx Frequency", "abc")
        edit_cell(p, lambda r: r[0] == "2", "Colour Code", "x")
        edit_cell(p, lambda r: r[0] == "1", "Colour Code", "99")
        try:
            import_dir(cp, d)
            check(False, "погані значення")
        except cc.CsvImportRefused as e:
            check(len(e.problems) == 2 and "Rx Frequency" in str(e) and "Colour Code" in str(e), "кілька проблем одним списком: %r" % e.problems)
    # --- «м'яка» колонка з незрозумілим значенням: попередження, поле не міняється ---
    with tempfile.TemporaryDirectory() as d:
        export_dir(cp, d)
        edit_cell(os.path.join(d, "Channels.csv"), lambda r: r[0] == "2", "Power", "Ультра")
        res = import_dir(cp, d)
        check(images_equal(res, cp) and len(res.warnings) == 1, "м'яка колонка: поле не змінено, є попередження: %r" % res.warnings)


def test_name_limit():
    spi = make_fixture_spi()
    cp, _data = codeplug_of(spi)
    # 8 кирилічних літер у GBK = 16 байтів (влазить), 9 -- ні
    for text, ok in (("АБВГДЕЁЖ", True), ("АБВГДЕЁЖЗ", False), ("ТестТестТестТест", False), ("Тест Тес", True),
                     ("Їжачок-Ґринджол", True), ("Їжачок-Ґринджол!!", False)):
        with tempfile.TemporaryDirectory() as d:
            export_dir(cp, d)
            for fn in ("Channels.csv", "TG_Lists.csv", "Zones.csv", "APRS.csv", "DTMF.csv"):
                os.unlink(os.path.join(d, fn))
            edit_cell(os.path.join(d, "Contacts.csv"), lambda r: r[-1] == "LOCAL", cc.READABLE, text)
            try:
                res = import_dir(cp, d)
                raw = [r for s_, r in res.image.contacts() if s_ == 2][0][:16]
                check(ok and cv.decode_name_ex(raw)[0] == text, "T6: «%s» влізло" % text)
            except cc.CsvImportRefused as e:
                check(not ok, "T6: «%s» не мало бути відхилене: %s" % (text, e))
                n = len(cc.encode_new_name(text)[0])
                check("%d байтів" % n in str(e) and "дозволено 16" in str(e) and "зайве: %d" % (n - 16) in str(e),
                      "T6: пояснення з кількістю байтів: %s" % e)
    with tempfile.TemporaryDirectory() as d:
        export_dir(cp, d)
        for fn in ("Channels.csv", "TG_Lists.csv", "Zones.csv", "APRS.csv", "DTMF.csv"):
            os.unlink(os.path.join(d, fn))
        edit_cell(os.path.join(d, "Contacts.csv"), lambda r: r[-1] == "LOCAL", cc.READABLE, "ТестТестТестТест")
        try:
            import_dir(cp, d)
        except cc.CsvImportRefused as e:
            check("cp1251 влізло б (16 байтів)" in str(e), "підказка про cp1251, коли GBK не влізає: %s" % e)
    # символ, якого немає ні в GB2312, ні в cp1251
    with tempfile.TemporaryDirectory() as d:
        export_dir(cp, d)
        for fn in ("Channels.csv", "TG_Lists.csv", "Zones.csv", "APRS.csv", "DTMF.csv"):
            os.unlink(os.path.join(d, fn))
        edit_cell(os.path.join(d, "Contacts.csv"), lambda r: r[-1] == "LOCAL", cc.READABLE, "Test ★ ✓")
        try:
            import_dir(cp, d)
            check(False, "символ поза кодуваннями мав бути відхилений")
        except cc.CsvImportRefused as e:
            check("★" in str(e) and "не кодуються" in str(e), "названо символ, якого немає в кодуваннях: %s" % e)


def test_add_change_delete():
    spi = make_fixture_spi()
    cp, _data = codeplug_of(spi)
    with tempfile.TemporaryDirectory() as d:
        export_dir(cp, d)
        # --- новий контакт українською: лише читабельна колонка ---
        p = os.path.join(d, "Contacts.csv")
        rows = read_csv_rows(p)
        rows.append(["", "2550", "Group", "Disabled", "Одеса"])
        write_csv_rows(p, rows)
        # --- новий канал без номера, цифровий, з посиланням на новий контакт ---
        pc = os.path.join(d, "Channels.csv")
        rows = read_csv_rows(pc)
        new = [""] * len(rows[0])
        h = {c: i for i, c in enumerate(rows[0])}
        new[h["Channel Name"]] = ""
        new[h[cc.READABLE]] = "Одеса ТГ"
        new[h["Channel Type"]] = "Digital"
        new[h["Rx Frequency"]] = "\t438,5"
        new[h["Tx Frequency"]] = "\t431,5"
        new[h["Colour Code"]] = "1"
        new[h["Timeslot"]] = "2"
        new[h["Contact"]] = "Одеса"
        new[h["TG List"]] = "Ukraine"
        new[h["Power"]] = "5W"
        rows.append(new)
        # --- видалення каналу 130 (з єдиної зони, де він є) ---
        rows = [r for r in rows if r[0] != "130"]
        write_csv_rows(pc, rows)
        zr = read_csv_rows(os.path.join(d, "Zones.csv"))
        zr[3][4] = ""
        write_csv_rows(os.path.join(d, "Zones.csv"), zr)
        # --- зміна: потужність каналу 2 ---
        edit_cell(pc, lambda r: r[0] == "2", "Power", "2W")
        res = import_dir(cp, d)
        check(len(res.added) == 2 and {a[0] for a in res.added} == {"Контакти", "Канали"}, "додано контакт і канал: %r" % res.added)
        check(len(res.removed) == 1 and res.removed[0][0] == "Канали" and "130" in res.removed[0][1], "видалено канал 130: %r" % res.removed)
        check(len(res.changed) == 2 and any("Power" in c[1] for c in res.changed) and any(c[0] == "Зони" for c in res.changed),
              "змінено Power у каналі 2 і склад зони: %r" % res.changed)
        lines = "\n".join(res.report_lines())
        check(lines.index("ВИДАЛЯЄТЬСЯ") < lines.index("Нові"), "видалення -- на видноті першими")
        img = res.image
        check(not img.channel_in_use(130) and img.channel_in_use(4), "канал 130 вимкнено, новий отримав найменший вільний номер 4 (або інший вільний)")
        r4 = img.channel_rec(4)
        check(r4[24] == 1 and cv.freq_bcd_le(r4[16:20]) == 43850000 and cv.freq_bcd_le(r4[20:24]) == 43150000, "новий канал: тип і частоти")
        check(r4[25] == 8 and (r4[49] & 0x40), "новий канал: потужність 5W, TS2")
        contact_no = r4[46] | (r4[47] << 8)
        crec = [rec for s_, rec in img.contacts() if s_ + 1 == contact_no][0]
        check(cv.decode_name_ex(crec[:16]) == ("Одеса", "GBK") and cv.bcd_to_int(crec[16:20]) == 2550, "новий канал посилається на новий контакт")
        check(r4[43] == 1, "посилання на TG-список «Ukraine» -> №1")
        # решта кодплуга не змінилась
        diff_ee = [i for i in range(len(cp.eeprom)) if cp.eeprom[i] != img.eeprom[i]]
        check(all(0x3780 <= i < 0x3780 + 16 + 128 * 56 or 0x8030 <= i < 0x8030 + 68 * 176 for i in diff_ee),
              "EEPROM змінено лише в банку каналів 0 і списку зон (%d байтів)" % len(diff_ee))
    # --- перейменування контакту «на місці» через читабельну колонку, TG-список — лишається посилатись ---
    with tempfile.TemporaryDirectory() as d:
        export_dir(cp, d)
        for fn in ("Channels.csv", "TG_Lists.csv", "Zones.csv", "APRS.csv", "DTMF.csv"):
            os.unlink(os.path.join(d, fn))
        edit_cell(os.path.join(d, "Contacts.csv"), lambda r: r[-1] == "LOCAL", cc.READABLE, "Місцевий")
        res = import_dir(cp, d)
        check(len(res.changed) == 1 and not res.removed and not res.added, "перейменування на місці: %s" % res.summary())
    # --- видалення зони, TG-списку, DTMF, APRS ---
    with tempfile.TemporaryDirectory() as d:
        export_dir(cp, d)
        for fn, keepfirst in (("Zones.csv", 1), ("TG_Lists.csv", 1), ("DTMF.csv", 0), ("APRS.csv", 0)):
            p = os.path.join(d, fn)
            rows = read_csv_rows(p)
            write_csv_rows(p, rows[:1 + keepfirst])
        # канали посилаються на TG-список 5 («Група») і APRS — тому потрібна відмова
        try:
            import_dir(cp, d)
            check(False, "видалення TG-списку/APRS, на які посилаються канали, мало бути відхилене")
        except cc.CsvImportRefused as e:
            check("Група" in str(e) or "APRS" in str(e), "відмова називає видалені цілі: %s" % e)
    # --- DTMF і APRS: правка, нові ---
    with tempfile.TemporaryDirectory() as d:
        export_dir(cp, d)
        rows = read_csv_rows(os.path.join(d, "DTMF.csv"))
        check(rows[1][1] == "123ABCD*", "DTMF-код у гіпотетичному алфавіті: %r" % rows[1])
        edit_cell(os.path.join(d, "DTMF.csv"), lambda r: r[0] == "Test DTMF", "Code", "9#*")
        edit_cell(os.path.join(d, "APRS.csv"), lambda r: r[0] == "APRS", "Comment text", "New comment")
        res = import_dir(cp, d)
        dt = dict(res.image.dtmf())[0]
        check(dt[16:32] == bytes([9, 15, 14]) + b"\xff" * 13, "DTMF: код записано: %r" % dt[16:32])
        ap = dict(res.image.aprs())[0]
        check(ap[31:55] == b"New comment".ljust(24, b"\x00") and ap[:8] == dict(cp.__dict__ and cc.Image.from_codeplug(cp).aprs())[0][:8],
              "APRS: коментар змінено, решта запису та сама")


def test_no_x_on_refusal_and_cli():
    """T5 доказ: імпорт у рацію з поганим CSV не посилає жодної X-команди й не робить страхової копії."""
    spi = make_fixture_spi()
    cp, _data = codeplug_of(spi)
    with tempfile.TemporaryDirectory() as d:
        export_dir(cp, d)
        z = os.path.join(d, "Zones.csv")
        rows = read_csv_rows(z)
        rows[1][1] = "Нема такого каналу"
        write_csv_rows(z, rows)
        radio = tr.FakeRadioX(bytearray(spi))
        with tr.Unlocked():
            try:
                cc.import_to_radio(cl.CpsLink(radio, retries=0), d, lambda t, p: True, log=lambda *_: None)
                check(False, "T5: імпорт мав бути відхилений")
            except cc.CsvImportRefused:
                pass
        check(radio.x_total == 0 and not radio.commits and not radio.c_calls, "T5: жодної X/C-команди при відмові: x=%d c=%r" % (radio.x_total, radio.c_calls))
        check(not [f for f in os.listdir(d) if "pre-restore" in f or "csv-import" in f], "T5: ні страхової копії, ні файла образу при відмові")


def test_import_to_radio():
    spi = make_fixture_spi()
    cp, _data = codeplug_of(spi)
    with tempfile.TemporaryDirectory() as d:
        export_dir(cp, d)
        edit_cell(os.path.join(d, "Channels.csv"), lambda r: r[0] == "2", "Power", "2W")
        rows = read_csv_rows(os.path.join(d, "Contacts.csv"))
        rows.append(["", "2550", "Group", "Disabled", "Одеса"])
        write_csv_rows(os.path.join(d, "Contacts.csv"), rows)
        radio = tr.FakeRadioX(bytearray(spi))
        texts = []
        prog = []

        def confirm(text, plan):
            texts.append(text)
            return True
        with tr.Unlocked():
            res = cc.import_to_radio(cl.CpsLink(radio, retries=0), d, confirm, progress=lambda p, t: prog.append(p), log=lambda *_: None,
                                     session=cc.Session())
        check(res["cancelled"] is False and res["sectorsWritten"] > 0, "імпорт записав сектори: %r" % res.get("sectorsWritten"))
        check(radio.c_calls[:1] == [bytes([0])] and radio.c_calls[-1] == bytes([6, 1]), "C 0 ... C 6 1: %r" % radio.c_calls)
        check(not any(c[0] == 4 for c in radio.x_calls), "X 4 не використовується")
        t = texts[0]
        for frag in ("ІМПОРТ CSV", "Одеса", "Power", "pre-restore", "Нові (1)", "Змінені (1)"):
            check(frag in t, "діалог містить «%s»" % frag)
        sf = [f for f in os.listdir(d) if f.startswith("codeplug_pre-restore")]
        check(len(sf) == 1, "страхова копія створена: %r" % sf)
        check(any(f.startswith("codeplug_csv-import") for f in os.listdir(d)), "файл образу «що записали» збережено")
        check(prog == sorted(prog) and prog[-1] == 100, "прогрес монотонний до 100")
        # рація тепер == образ: повторний імпорт нічого не змінює
        cp2, _ = cv.codeplug_from_radio(cl.CpsLink(tr.FakeRadioX(radio.spi), retries=0))
        res2 = import_dir(cp2, d)
        check(not res2.any_change(), "після запису повторний імпорт без змін: %s" % res2.summary())
        # рація не має змін, окрім потрібних
        check(bytes(radio.spi[0x10000:0x11000]) == bytes(spi[0x10000:0x11000]), "калібрування не торкались")
        # імпорт без змін: нічого не пишемо
        radio2 = tr.FakeRadioX(bytearray(spi))
        d2 = tempfile.mkdtemp()
        export_dir(cp, d2)
        with tr.Unlocked():
            r = cc.import_to_radio(cl.CpsLink(radio2, retries=0), d2, lambda t, p: (_ for _ in ()).throw(AssertionError("діалог не потрібен")),
                                   log=lambda *_: None)
        check(r["nothingToDo"] and radio2.x_total == 0, "CSV без змін: нічого не пишемо й не питаємо")
        # заблоковано -> відмова навіть після успішного розбору
        radio3 = tr.FakeRadioX(bytearray(spi))
        with tr.Locked():
            try:
                cc.import_to_radio(cl.CpsLink(radio3, retries=0), d, lambda t, p: True, log=lambda *_: None)
                check(False, "заблоковано: імпорт мав відмовитись")
            except Exception as e:  # noqa: BLE001
                check("заблоковано" in str(e), "блокування відновлення блокує й імпорт: %s" % e)
        check(radio3.x_total == 0, "при блокуванні жодної X-команди")


def main():
    for t in (test_format_and_roundtrip, test_cyrillic, test_decimal_and_tab, test_refusals, test_name_limit, test_add_change_delete,
              test_no_x_on_refusal_and_cli, test_import_to_radio):
        try:
            t()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILS.append("%s: виняток %r" % (t.__name__, e))
    if FAILS:
        print("test_cps_csv: ПРОВАЛЕНО перевірок: %d" % len(FAILS))
        return 1
    print("test_cps_csv: усі перевірки пройшли (T1 кругова оборотність, T2 кирилиця, T3/T4 кома-крапка-табуляція, T5 відмови, T6 ліміт назви, імпорт у рацію).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
