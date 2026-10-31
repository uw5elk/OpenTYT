# -*- coding: utf-8 -*-
"""R30 (Z1-Z6): файл теми `.gtm` (theme_edit + панель «Теми екрана») і область custom-data у бекапі, відновленні та файлі налаштувань
(custom_region.py, cps_link.backup_codeplug, cps_ui/p_backup.py, cps_ui/p_allsettings.py).
Логіка -- у будь-якому python3; GUI -- лише з tkinter + DISPLAY (`xvfb-run -a python3.12 tools/test_r30.py`; інакше частину з Tk пропущено й сказано про це).
Рації нема: SPI-флеш підроблено (FakeRadioX з test_cps_restore розуміє 'R' і 'X 1/2/3'), тож РЕАЛЬНІ алгоритми custom_data.write_block / cps_restore
відпрацьовують на підробленому флеші."""
import io
import json
import os
import random
import re
import struct
import sys
import tempfile
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import aes_key_store as aks              # noqa: E402
import cps_link as cl                    # noqa: E402
import cps_restore as crs                # noqa: E402
import custom_data as cd                 # noqa: E402
import custom_region as cr               # noqa: E402
import theme_edit as th                  # noqa: E402
import test_cps_link as base             # noqa: E402
import test_cps_restore as tcr           # noqa: E402

FAILS = []
tcr.FakeRadioX.close = lambda self: None       # панелі закривають порт після роботи (справжній serial.Serial.close)
APP = os.path.join(HERE, "..", "application")
TESTDATA = os.path.join(HERE, "testdata")


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def quiet(*_a, **_k):
    pass


def read_text(*parts):
    with open(os.path.join(APP, *parts), encoding="utf-8", errors="replace") as f:
        return f.read()


def no_sleep():
    """aes_key_store чекає 0.15-0.5 с після кожної команди (реальна рація); на підробці це марно."""
    old = time.sleep
    time.sleep = lambda _s: None
    return old


# ----------------------------------------------------------------------------------------------------------------------
#  Побудова області
# ----------------------------------------------------------------------------------------------------------------------

# (тип, довжина): довжини взято з коду (див. claude/codeplug-map.md); MSG_CONFIG -- 493 Б полів struct (виведено), SMS-сховище 1352 Б
SIZES = {4: 64, 5: 64, 6: 584, 7: 1352, 8: 493, 9: 8, 10: 76, 11: 6, 12: 1, 13: 72, 14: 16}


def make_payloads(seed, types=None):
    out = {}
    for t in (types or sorted(SIZES)):
        n = SIZES[t]
        out[t] = bytes(((seed * 37 + t * 11 + i * 7) % 250) + 1 for i in range(n))    # без 0x00 і 0xFF
    if 6 in out:
        p = bytearray(out[6])
        p[0:4] = b"AESK"
        for i in range(16):
            p[8 + i * 36] = 0          # жодного слота з ключем: блок БЕЗ ключового матеріалу
        out[6] = bytes(p)
    return out


def put_region(spi, payloads, order=None, magic=True):
    """Записати область custom-data в образ SPI: заголовок + блоки в заданому порядку."""
    pos = cd.FLASH_BASE
    spi[pos:pos + cr.REGION_LEN] = b"\xff" * cr.REGION_LEN
    if not magic:
        return spi
    spi[pos:pos + 12] = b"OpenGD77" + b"\x00" * 4
    pos += 12
    for t in (order or sorted(payloads)):
        data = payloads[t]
        spi[pos:pos + 8] = struct.pack("<ii", t, len(data))
        spi[pos + 8:pos + 8 + len(data)] = data
        pos += 8 + len(data)
    return spi


def region_of(spi):
    return bytes(spi[cd.FLASH_BASE:cd.FLASH_BASE + cr.REGION_LEN])


def payloads_of(region_bytes):
    return {b.type: b.payload for b in cr.parse_region(region_bytes).blocks}


def new_spi_with(seed, magic=True, types=None, order=None):
    spi = tcr.spi_a()
    put_region(spi, make_payloads(seed, types), order, magic)
    return spi


# ----------------------------------------------------------------------------------------------------------------------
#  Z0: межі й таблиця типів звірені з кодом прошивки
# ----------------------------------------------------------------------------------------------------------------------

def test_constants_match_firmware():
    check(cr.REGION_RAW_START == cd.FLASH_BASE == cl.FLASH_ADDRESS_OFFSET == 0x20000, "Z0: початок області == FLASH_BASE == FLASH_ADDRESS_OFFSET")
    check(cr.REGION_LEN == cd.MAX_BLOCK_ADDRESS == 0x10000, "Z0: довжина області == MAX_BLOCK_ADDRESS")
    check(cr.REGION_HDR == cd.HDR_LEN + 4 or cr.REGION_HDR == 12, "Z0: заголовок області 12 Б")
    check(cr.CAL_END <= cr.REGION_RAW_START and cr.CAL_START == crs.CAL_START and cr.CAL_END == crs.CAL_END, "Z0: калібрування поза областю й збігається з cps_restore")
    codeplug_c = read_text("source", "functions", "codeplug.c")
    check("const uint32_t MAX_BLOCK_ADDRESS = 0x10000;" in codeplug_c, "Z0: MAX_BLOCK_ADDRESS у codeplug.c == 0x10000")
    codeplug_h = read_text("include", "functions", "codeplug.h")
    m = re.search(r"typedef enum\s*\{([^}]*CODEPLUG_CUSTOM_DATA_TYPE_EMPTY[^}]*)\}\s*CodeplugCustomDataType_t", codeplug_h, re.S)
    check(m is not None, "Z0: enum CodeplugCustomDataType_t знайдено")
    names = re.findall(r"CODEPLUG_CUSTOM_DATA_TYPE_([A-Z_0-9]+)", re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)) if m else []
    names = [n for n in names if n != "EMPTY"]
    check([n for n in names] == [cr.BLOCK_TYPES[t][0] for t in sorted(cr.BLOCK_TYPES)], "Z0: таблиця типів custom_region == enum у codeplug.h (%r)" % names)
    check(sorted(cr.BLOCK_TYPES) == list(range(1, 1 + len(names))), "Z0: номери типів 1..%d підряд" % len(names))
    # розміри блоків, які задає код: прошивка (#define) == Python-інструменти
    mode = read_text("include", "functions", "aprs_mode_cfg.h")
    check(re.search(r"#define APRSM_BLOCK_LEN\s+72\b", mode) and re.search(r"#define APRSB_BLOCK_LEN\s+16\b", mode), "Z0: APRS режим 72 Б, бікон 16 Б у прошивці")
    import aprs_beacon_cfg as abc
    import rctl_config as rc
    import callreplay_config as crc
    check(abc.MODE_LEN == SIZES[13] and abc.BEACON_LEN == SIZES[14] and rc.PAYLOAD_LEN == SIZES[9] and crc.PAYLOAD_LEN == SIZES[11] and th.BLOCK_LEN == SIZES[4]
          and aks.AESK_BLOCK_LEN == SIZES[6], "Z0: розміри блоків у Python-інструментах == розміри в тесті")
    check(cr.TYPE_RCTL_STATE == 10 and cr.BLOCK_TYPES[10][0] == "RCTL_STATE" and cr.BLOCK_TYPES[10][4] == "state", "Z0: RCTL_STATE -- стан")


# ----------------------------------------------------------------------------------------------------------------------
#  Z2: файл .gtm
# ----------------------------------------------------------------------------------------------------------------------

def test_gtm():
    day = th.load_gtm(os.path.join(TESTDATA, "theme_day.gtm"))
    night = th.load_gtm(os.path.join(TESTDATA, "theme_night.gtm"))
    check(len(day) == 32 and len(night) == 32, "Z2: обидва файли читаються (по 32 кольори)")
    check(th.to_hex(night[th.INDEX["FG_RSSI_BAR"]]) == "#00FF00", "Z2: нічна FG_RSSI_BAR == #00FF00")
    check(th.to_hex(night[th.INDEX["FG_TX_FREQ"]]) == "#FF0000", "Z2: нічна FG_TX_FREQ == #FF0000")
    check(th.to_hex(day[th.INDEX["BG"]]) == "#FFFFFF", "Z2: денна BG == #FFFFFF")
    # BG_HEADER_TEXT == 0xC638; у брифі #C5C6C5 -- те саме значення RGB565 (масштаб 255/31), програма показує #C6C7C6 (добудова молодших бітів повторенням)
    check(day[th.INDEX["BG_HEADER_TEXT"]] == th.from_hex("#C5C6C5") == 0xC638, "Z2: денна BG_HEADER_TEXT == RGB565 0xC638 (#C5C6C5 у брифі)")
    for f, cols in (("theme_day.gtm", day), ("theme_night.gtm", night)):
        raw = open(os.path.join(TESTDATA, f), "rb").read()
        check(len(raw) == 64 and raw == th.encode_block(cols), "Z2: %s == рівно 64 байти блока" % f)
        out = os.path.join(tempfile.mkdtemp(prefix="r30_"), "x.gtm")
        th.save_gtm(out, th.load_gtm(os.path.join(TESTDATA, f)))
        check(open(out, "rb").read() == raw, "Z2: %s: завантажити -> зберегти == ті самі 64 байти" % f)
    # збіги зі стоковими таблицями ОБЧИСЛЕНО (числа з claude/theme-format.md: нічна 0/1, денна 15/17)
    check(th.match_counts(night, "night") == {"ua": 0, "classic": 1}, "Z2: нічна: збіг з UA 0 з 32, з класичною 1 з 32 (%r)" % th.match_counts(night, "night"))
    check(th.match_counts(day, "day") == {"ua": 15, "classic": 17}, "Z2: денна: збіг з UA 15 з 32, з класичною 17 з 32 (%r)" % th.match_counts(day, "day"))
    check(th.match_counts(th.stock_colors("night", "ua"), "night") == {"ua": 32, "classic": th.match_counts(th.stock_colors("night", "ua"), "night")["classic"]},
          "Z2: стокова UA збігається сама з собою на 32")
    # відмови: інша довжина
    d = tempfile.mkdtemp(prefix="r30_")
    for n in (0, 63, 65, 128):
        p = os.path.join(d, "bad%d.gtm" % n)
        open(p, "wb").write(b"\x12" * n)
        try:
            th.load_gtm(p)
            check(False, "Z2: файл %d Б мав бути відхилений" % n)
        except th.GtmError as e:
            check("64" in str(e) and str(n) in str(e), "Z2: відмова для %d Б пояснена словами: %s" % (n, e))
    check(th.gtm_name_hint("/x/d.gtm") == "day" and th.gtm_name_hint("N.GTM") == "night" and th.gtm_name_hint("theme.gtm") is None, "Z2: підказка за іменем d/n")
    # текстовий формат (R28) лишився
    cols = th.READY_SETS["night_red"][4]
    p = os.path.join(d, "t.txt")
    th.save_file(p, "night", cols)
    check(th.load_file(p) == ("night", cols), "Z2: текстовий формат OpenTYT-theme-1 читається, як у R28")
    # V5: хибного твердження «офіційного формату нема» більше немає в коді інструментів
    stale = []
    for root, _dirs, files in os.walk(HERE):
        if "__pycache__" in root:
            continue
        for fn in files:
            if fn.endswith((".py", ".md")) and fn != "test_r30.py":
                t = open(os.path.join(root, fn), encoding="utf-8", errors="replace").read()
                if "знайти не вдалося" in t and "формату файлів тем" in t:
                    stale.append(fn)
    check(not stale, "V5: у tools/ нема застарілого «офіційного формату файлів тем знайти не вдалося»: %r" % stale)


# ----------------------------------------------------------------------------------------------------------------------
#  Розбір області, маніфест, секрети
# ----------------------------------------------------------------------------------------------------------------------

def test_parse_manifest():
    spi = new_spi_with(1)
    reg = cr.parse_region(region_of(spi))
    check(reg.magic_ok and [b.type for b in reg.blocks] == sorted(SIZES) and all(b.length == SIZES[b.type] for b in reg.blocks), "парсер: усі 11 блоків з довжинами")
    check(not reg.problems, "парсер: проблем нема")
    part = cr.manifest_part(region_of(spi))
    check(part["start"] == 0x20000 and part["length"] == 0x10000 and part["sha256"] == cr.sha256(region_of(spi)), "маніфест: діапазон і SHA-256")
    check([(b["type"], b["length"]) for b in part["blocks"]] == [(t, SIZES[t]) for t in sorted(SIZES)], "маніфест: список блоків з типами й довжинами")
    check(part["restorable"] is False, "маніфест: cps_restore область не відновлює (restorable=false)")
    # порожня область і область без магії
    check(not cr.parse_region(b"\xff" * cr.REGION_LEN).magic_ok and cr.parse_region(b"\xff" * cr.REGION_LEN).erased, "парсер: стерта область розпізнана")
    r = cr.parse_region(b"\x00" * cr.REGION_LEN)
    check(not r.magic_ok and not r.erased and r.problems, "парсер: сміття -- не стерта й не OpenGD77")
    # блок, що вилазить за область
    bad = bytearray(b"\xff" * cr.REGION_LEN)
    bad[:12] = b"OpenGD77" + b"\x00" * 4
    bad[12:20] = struct.pack("<ii", 7, 0x20000)
    check(cr.parse_region(bytes(bad)).problems and not cr.parse_region(bytes(bad)).blocks, "парсер: довжина за межі області -- проблема, не виняток")
    # AES із ключовим матеріалом
    aes = bytearray(make_payloads(2)[6])
    aes[8] = 1
    aes[8 + 1] = 3
    aes[8 + 4:8 + 36] = bytes(range(1, 33))
    check(cr.has_secret(6, bytes(aes)) and not cr.has_secret(6, make_payloads(2)[6]) and not cr.has_secret(4, bytes(aes)), "секрет: слот valid=1 з ключем виявлено")
    b_state = cr.Block(10, 0, b"x" * 76)
    b_aes = cr.Block(6, 0, bytes(aes))
    check(not cr.default_selected(b_state) and cr.default_selected(b_state, include_state=True) and not cr.default_selected(b_aes), "типово: стан RCTL і AES із ключем не застосовуються")


# ----------------------------------------------------------------------------------------------------------------------
#  Z3, Z4, Z6: бекап -> відновлення на підробленому флеші
# ----------------------------------------------------------------------------------------------------------------------

def mk_zip(spi, **kw):
    radio = tcr.FakeRadioX(bytearray(spi))
    data, manifest = cl.backup_codeplug(cl.CpsLink(radio), rng=random.Random(5), log=quiet, **kw)
    d = tempfile.mkdtemp(prefix="r30z_")
    path = os.path.join(d, "backup.zip")
    open(path, "wb").write(data)
    return path, data, manifest


def test_backup_contains_region():
    spi_a = new_spi_with(1)
    path, data, manifest = mk_zip(spi_a)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        check(sorted(z.namelist()) == ["aeskeys.bin", "customdata.bin", "eeprom.bin", "flash.bin", "manifest.json"], "W2: у .zip є окремий файл області (і, з R31, ключів)")
        raw = z.read("customdata.bin")
    check(raw == region_of(spi_a), "W2/Z3: customdata.bin == область з рації байт-в-байт")
    p = manifest["parts"]["customData"]
    check(p["start"] == 0x20000 and p["length"] == 0x10000 and p["sha256"] == cr.sha256(raw), "W2: маніфест: діапазон 0x20000+0x10000 і SHA-256")
    check([b["type"] for b in p["blocks"]] == sorted(SIZES) and "customData" in manifest["includes"] and manifest["restorable"] == ["eeprom", "flash"],
          "W2: маніфест перелічує реально налаштовані блоки; restorable лишається [eeprom, flash]")
    m, ee, fl = cl.read_backup_zip(data)
    check(cr.read_backup_region(data) == raw and cr.read_backup_region(path) == raw, "W2: read_backup_region читає з байтів і зі шляху")
    # пошкоджена область
    bad = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as zi, zipfile.ZipFile(bad, "w") as zo:
        for n in zi.namelist():
            b = zi.read(n)
            if n == "customdata.bin":
                b = b[:100] + bytes([b[100] ^ 0xFF]) + b[101:]
            zo.writestr(n, b)
    try:
        cl.read_backup_zip(bad.getvalue())
        check(False, "W2: пошкоджена область мала бути відхилена")
    except cl.CpsError as e:
        check("SHA-256" in str(e), "W2: пошкоджена область: SHA-256 не збігається (%s)" % str(e)[:60])
    # secret у блоці AES -> маніфест позначає
    pl = make_payloads(1)
    a = bytearray(pl[6])
    a[8] = 1
    a[12:44] = bytes(range(1, 33))
    pl[6] = bytes(a)
    spi = tcr.spi_a()
    put_region(spi, pl)
    _p, _d, mm = mk_zip(spi)
    check(any(b.get("secret") for b in mm["parts"]["customData"]["blocks"]) and "секрет" in mm["note"], "W2: ключовий матеріал в AES-блоці позначено в маніфесті й примітці")
    # без області: старий формат
    _p2, d2, m2 = mk_zip(spi_a, custom_data=False, aes_keys=False)
    check("customData" not in m2["parts"] and m2["includes"] == ["eeprom", "flash"], "Z4: custom_data=False, aes_keys=False дає архів у старому форматі")


def run_restore(radio, path, **kw):
    """Відновлення через стандартні функції (без Tk). confirm записує текст, який бачив би користувач."""
    asked = []

    def confirm(text, plan=None):
        asked.append(text)
        return True
    out = cr.restore_codeplug_and_region(cl.CpsLink(radio), path, confirm, log=quiet, now=None, **kw)
    return out, asked


def test_restore_roundtrip():
    old_sleep = no_sleep()
    try:
        spi_a = new_spi_with(1)
        spi_b0 = new_spi_with(2)
        spi_b0 = tcr.spi_b(spi_b0) if hasattr(tcr, "spi_b") else spi_b0
        cal_b = bytes(spi_b0[0x10000:0x10010])
        path, data, _m = mk_zip(spi_a)

        # --- CF5/Z3: прапорець вимкнено -> область не чіпаємо ---
        rb = tcr.FakeRadioX(bytearray(spi_b0))
        before = region_of(rb.spi)
        out, asked = run_restore(rb, path)
        check(out["region"] is None and region_of(rb.spi) == before, "W3.1/CF5: прапорець вимкнено -- область рації не змінена")
        check(bytes(rb.spi[0x10000:0x10010]) == cal_b, "Z6: калібрування після відновлення кодплага не змінилось")

        # --- Z3: прапорець увімкнено (з RCTL_STATE) -> область байт-в-байт з бекапу ---
        rb = tcr.FakeRadioX(bytearray(spi_b0))
        out, asked = run_restore(rb, path, with_region=True, include_state=True)
        reg = out["region"]
        check(reg and not reg.get("absent") and reg["result"]["failed"] is None, "Z3: відновлення області завершилось без помилок: %r" % (reg and reg.get("text")))
        check(region_of(rb.spi) == region_of(spi_a), "Z3: область після відновлення байт-в-байт == область з бекапу")
        check(reg["regionMatchesExpected"] is True, "Z3: підсумкова звірка очікуваної області пройшла")
        check(any("область custom-data" in t.lower() or "custom-data" in t for t in asked) and any("Тема екрана: денна" in t for t in asked),
              "W3.1: перед записом показано список блоків, які буде перезаписано")
        check(os.path.exists(reg["safetyCopy"]) and open(reg["safetyCopy"], "rb").read() == region_of(spi_b0), "W3: страхова копія області == область рації ДО запису")
        check(rb.reset_requested and not rb.cal_touched and bytes(rb.spi[0x10000:0x10010]) == cal_b, "Z6: калібрування не чіпали; рацію перезавантажено один раз")

        # --- типово RCTL_STATE НЕ застосовується ---
        rb = tcr.FakeRadioX(bytearray(spi_b0))
        out, _a = run_restore(rb, path, with_region=True)
        pa, pb0, pb = payloads_of(region_of(spi_a)), payloads_of(region_of(spi_b0)), payloads_of(region_of(rb.spi))
        check(pb[10] == pb0[10] and pb[10] != pa[10], "W4.2/W3.1: RCTL_STATE (стан) типово лишився рації, не застосовано з бекапу")
        check(all(pb[t] == pa[t] for t in pa if t != 10), "W3: усі інші блоки == з бекапу")

        # --- лише область (без кодплага): коміти тільки в секторах області ---
        rb = tcr.FakeRadioX(bytearray(spi_b0))
        eeprom_before = bytes(rb.spi[:0x20000])
        res = cr.restore_region(cl.CpsLink(rb), path, lambda t, p=None: True, include_state=True, log=quiet)
        sectors = set(rb.commits)
        lo, hi = cr.REGION_RAW_START // 4096, cr.REGION_RAW_END // 4096
        check(sectors and all(lo <= s < hi for s in sectors), "Z6: усі записані сектори в межах області 0x20000..0x2FFFF: %r" % sorted(sectors))
        check(not rb.cal_touched and bytes(rb.spi[:0x20000]) == eeprom_before, "Z6: EEPROM (з калібруванням 0x10000) після відновлення області побайтово той самий")
        check(region_of(rb.spi) == region_of(spi_a), "Z3: лише область: байт-в-байт з бекапу")

        # --- блоки в іншому порядку / частини немає: створення у вільних слотах ---
        spi_c = new_spi_with(3, types=[4, 9], order=[9, 4])
        rb = tcr.FakeRadioX(bytearray(spi_c))
        res = cr.restore_region(cl.CpsLink(rb), path, lambda t, p=None: True, include_state=True, log=quiet)
        got = payloads_of(region_of(rb.spi))
        check(res["result"]["failed"] is None and got == pa, "Z3: блоків у рації не було/інший порядок -- усі створено, вміст == бекап")
        check(res["regionMatchesExpected"] is True, "Z3: очікувана область (симуляція) == фактична")

        # --- блок наявний, але іншої довжини: відмова з поясненням, решта пишеться ---
        pl = make_payloads(4)
        pl[9] = b"\x01" * 9           # RCTL_CONFIG має бути 8 Б
        spi_d = tcr.spi_a()
        put_region(spi_d, pl)
        rb = tcr.FakeRadioX(bytearray(spi_d))
        res = cr.restore_region(cl.CpsLink(rb), path, lambda t, p=None: True, log=quiet)
        got = payloads_of(region_of(rb.spi))
        check(res["result"]["failed"] is None and got[9] == pl[9] and got[4] == pa[4] and "Не можна було записати" in res["text"] and "іншу довжину" in res["text"],
              "W3.2: блок іншої довжини не змінено й пояснено, решта записана: %s" % res["text"].replace("\n", " | "))

        # --- скасування у підтвердженні -> нічого не пишемо ---
        rb = tcr.FakeRadioX(bytearray(spi_b0))
        snap = bytes(rb.spi)
        res = cr.restore_region(cl.CpsLink(rb), path, lambda t, p=None: False, log=quiet)
        check(res["cancelled"] and bytes(rb.spi) == snap, "W3: «Скасувати» -- флеш рації не змінено")

        # --- без області (стерта) у рації: заголовок + блоки ---
        rb = tcr.FakeRadioX(bytearray(tcr.spi_a()))
        res = cr.restore_region(cl.CpsLink(rb), path, lambda t, p=None: True, include_state=True, log=quiet)
        check(res["result"]["headerWritten"] and region_of(rb.spi) == region_of(spi_a), "W3: стерта область -- записано заголовок OpenGD77 і блоки, == бекап")
        # чужий вміст на місці області -- відмова
        spi_junk = tcr.spi_a()
        spi_junk[cd.FLASH_BASE:cd.FLASH_BASE + 64] = b"\x55" * 64
        rb = tcr.FakeRadioX(bytearray(spi_junk))
        snap = bytes(rb.spi)
        try:
            cr.restore_region(cl.CpsLink(rb), path, lambda t, p=None: True, log=quiet)
            check(False, "W3: область-сміття мала дати відмову")
        except cr.RegionError as e:
            check(bytes(rb.spi) == snap and "нічого не записано" in str(e), "W3: область не OpenGD77 і не стерта -- відмова, флеш не змінено")

        # --- Z4: старий архів без області ---
        old_path, old_data, _m = mk_zip(spi_a, custom_data=False)
        check(cr.read_backup_region(old_data) is None, "Z4: старий .zip без області читається (None)")
        m, ee, fl = cl.read_backup_zip(old_data)
        check(len(ee) == cl.EEPROM_BACKUP_LEN, "Z4: старий .zip читається cps_link.read_backup_zip як раніше")
        rb = tcr.FakeRadioX(bytearray(spi_b0))
        before = region_of(rb.spi)
        out, _a = run_restore(rb, old_path, with_region=True, include_state=True)
        check(out["region"]["absent"] and "нема" in out["region"]["text"] and region_of(rb.spi) == before, "Z4: старий архів: сказано, що області нема; область рації не чіпано")
        # кодплаг зі старого архіву відновлюється як раніше (область не потрібна)
        check(bytes(rb.spi[0x6000:0x6010]) == bytes(spi_a[0x6000:0x6010]), "Z4: кодплаг зі старого архіву відновлено як раніше")
    finally:
        time.sleep = old_sleep


# ----------------------------------------------------------------------------------------------------------------------
#  Z5: збій посеред запису блоків
# ----------------------------------------------------------------------------------------------------------------------

def test_partial_failure():
    old_sleep = no_sleep()
    real_wb = aks.flash_write_block
    real_write_block = cd.write_block
    try:
        spi_a = new_spi_with(1)
        spi_b = new_spi_with(2)
        path, _d, _m = mk_zip(spi_a)
        pa, pb0 = payloads_of(region_of(spi_a)), payloads_of(region_of(spi_b))
        rb = tcr.FakeRadioX(bytearray(spi_b))
        state = {"n": 0, "cur": 0}

        def counting_write_block(ser, t, payload):
            state["n"] += 1
            state["cur"] = state["n"]
            return real_write_block(ser, t, payload)

        def failing_flash_write(ser, addr, data):
            if state["cur"] == 3:
                raise RuntimeError("прошивка відмовила (імітація збою на 3-му блоці)")
            return real_wb(ser, addr, data)
        cd.write_block = counting_write_block
        aks.flash_write_block = failing_flash_write
        res = cr.restore_region(cl.CpsLink(rb), path, lambda t, p=None: True, selected={4, 5, 7, 8, 9}, log=quiet)
        got = payloads_of(region_of(rb.spi))
        r = res["result"]
        check(r["failed"] is not None and r["failed"]["block"].type == 7 and len(r["written"]) == 2, "Z5: збій на 3-му блоці (типу 7), записано 2: %r" % [b.type for b in r["written"]])
        check(got[4] == pa[4] and got[5] == pa[5], "Z5: перші два блоки (4, 5) записані й лишились записаними")
        check(got[7] == pb0[7] and got[8] == pb0[8] and got[9] == pb0[9], "Z5: третій і наступні блоки (7, 8, 9) лишились як були")
        check(all(got[t] == pb0[t] for t in (6, 10, 11, 12, 13, 14)), "Z5: необрані блоки не чіпано")
        txt = res["text"]
        check("ПОМИЛКА" in txt and "Записано й звірено" in txt and "Не торкався" in txt and "залишаються записаними" in txt,
              "Z5: звіт словами: що записано, де помилка, що не чіпали: %s" % txt.replace("\n", " | "))
        check([b.type for b in r["untouched"]] == [8, 9], "Z5: список «не торкався» == [8, 9]")
    finally:
        cd.write_block = real_write_block
        aks.flash_write_block = real_wb
        time.sleep = old_sleep


# ----------------------------------------------------------------------------------------------------------------------
#  Z6: жоден запис поза областю / по калібруванню; межа
# ----------------------------------------------------------------------------------------------------------------------

def test_no_write_outside_region():
    writes = []
    real_wb = aks.flash_write_block
    aks.flash_write_block = lambda ser, addr, data: writes.append((addr, len(data)))
    try:
        for addr, n, ok in ((0x20000, 12, True), (0x2FFF0, 16, True), (0x2FFF1, 16, False), (0x30000, 1, False), (0x1FFFF, 2, False),
                            (0x10000, 4096, False), (0x10FFC, 8, False), (0x0, 1, False), (0x2FFFF, 1, True)):
            writes.clear()
            try:
                cd.flash_write_span(None, addr, b"\x01" * n)
                good = True
            except ValueError:
                good = False
            check(good == ok, "Z6: запис 0x%X +%d: %s (очікувано %s)" % (addr, n, "дозволено" if good else "відхилено", "дозволено" if ok else "відхилено"))
            if not ok:
                check(writes == [], "Z6: відхилений запис 0x%X не дійшов до флеша" % addr)
        # запис через довільний шлях: усі адреси aks.flash_write_block лежать у [0x20000, 0x30000), калібрування 0x10000..0x10FFF не зачеплено
        writes.clear()
    finally:
        aks.flash_write_block = real_wb
    # повний прогін відновлення з записом усіх викликів flash_write_block
    old_sleep = no_sleep()
    try:
        spi_a, spi_b = new_spi_with(1), new_spi_with(2, types=[4, 9], order=[9, 4])
        path, _d, _m = mk_zip(spi_a)
        calls = []
        orig = aks.flash_write_block

        def rec(ser, addr, data):
            calls.append((addr, len(data)))
            return orig(ser, addr, data)
        aks.flash_write_block = rec
        try:
            rb = tcr.FakeRadioX(bytearray(spi_b))
            cr.restore_region(cl.CpsLink(rb), path, lambda t, p=None: True, include_state=True, log=quiet)
        finally:
            aks.flash_write_block = orig
        check(calls and all(cr.REGION_RAW_START <= a and a + n <= cr.REGION_RAW_END for a, n in calls), "Z6: усі %d записів відновлення в межах області" % len(calls))
        check(not any(a < cr.CAL_END and a + n > cr.CAL_START for a, n in calls), "Z6: жоден запис не перетинає сектор калібрування 0x10000..0x10FFF")
    finally:
        time.sleep = old_sleep


# ----------------------------------------------------------------------------------------------------------------------
#  W4: файл налаштувань
# ----------------------------------------------------------------------------------------------------------------------

def test_settings_file():
    old_sleep = no_sleep()
    try:
        spi_a, spi_b = new_spi_with(1), new_spi_with(2)
        ra = tcr.FakeRadioX(bytearray(spi_a))
        blocks, _reg = cr.read_settings_from_radio(cl.CpsLink(ra))
        check([b.type for b in blocks] == sorted(SIZES), "W4: прочитано всі блоки області")
        text = cr.settings_to_text(blocks, {"radioType": 6})
        again, doc = cr.settings_from_text(text)
        check([(b.type, b.payload) for b in again] == [(b.type, b.payload) for b in blocks], "W4: файл налаштувань: збереження -> читання == ті самі блоки")
        check(doc["format"] == cr.SETTINGS_FORMAT and not doc["containsSecrets"], "W4: формат і прапорець секретів")
        # пошкоджений файл
        for mut, label in ((lambda d: d["blocks"][0].update(hex="00" * 64), "інший вміст блока"), (lambda d: d.update(format="x"), "інший формат"),
                           (lambda d: d["blocks"].append(dict(d["blocks"][0])), "дубль типу")):
            dd = json.loads(text)
            mut(dd)
            try:
                cr.settings_from_text(json.dumps(dd))
                check(False, "W4: %s -- мало бути відхилено" % label)
            except cr.SettingsFileError:
                pass
        try:
            cr.settings_from_text("це не JSON")
            check(False, "W4: не JSON мав бути відхилений")
        except cr.SettingsFileError as e:
            check("не JSON" in str(e), "W4: не JSON -- пояснення словами")
        # застосування на іншу рацію: типово без RCTL_STATE
        rb = tcr.FakeRadioX(bytearray(spi_b))
        pb0 = payloads_of(region_of(rb.spi))
        sel = {b.type for b in blocks if cr.default_selected(b)}
        check(10 not in sel and 6 in sel, "W4.2: типовий вибір без RCTL_STATE (6 -- AES без ключів -- так)")
        res = cr.apply_settings(cl.CpsLink(rb), blocks, sel, log=quiet)
        got = payloads_of(region_of(rb.spi))
        pa = payloads_of(region_of(spi_a))
        check(res["result"]["failed"] is None and all(got[t] == pa[t] for t in sel) and got[10] == pb0[10], "W4: застосовано обране; RCTL_STATE рації не чіпано")
        check(res["regionMatchesExpected"] is True, "W4: підсумкова звірка області пройшла")
        check(rb.reset_requested and not rb.cal_touched, "W4: після запису рацію перезавантажено (C 6 1), калібрування не чіпали")
        rb2 = tcr.FakeRadioX(bytearray(spi_a))
        cr.apply_settings(cl.CpsLink(rb2), blocks, sel, log=quiet)
        check(not rb2.reset_requested, "W4: нічого не записано (вже таке саме) -- без перезавантаження")
        # обрано лише частину
        rb = tcr.FakeRadioX(bytearray(spi_b))
        res = cr.apply_settings(cl.CpsLink(rb), blocks, {4}, log=quiet)
        got = payloads_of(region_of(rb.spi))
        check(got[4] == pa[4] and all(got[t] == pb0[t] for t in pb0 if t != 4), "W4: обрано лише блок 4 -- інші не чіпано")
        # явний вибір RCTL_STATE працює
        rb = tcr.FakeRadioX(bytearray(spi_b))
        cr.apply_settings(cl.CpsLink(rb), blocks, {10}, log=quiet)
        check(payloads_of(region_of(rb.spi))[10] == pa[10], "W4.2: RCTL_STATE застосовується, коли обрано явно")
        # підтвердження
        rb = tcr.FakeRadioX(bytearray(spi_b))
        snap = bytes(rb.spi)
        res = cr.apply_settings(cl.CpsLink(rb), blocks, sel, confirm=lambda t, p=None: False, log=quiet)
        check(res["cancelled"] and bytes(rb.spi) == snap, "W4: скасування -- нічого не змінено")
        # AES із ключем у файлі: помічено, типово пропускається
        pl = make_payloads(1)
        a = bytearray(pl[6])
        a[8] = 1
        a[12:44] = bytes(range(1, 33))
        pl[6] = bytes(a)
        sb = [cr.Block(t, 0, p) for t, p in pl.items()]
        txt = cr.settings_to_text(sb)
        check(json.loads(txt)["containsSecrets"] and "секрет" in json.loads(txt)["note"], "W4: файл з ключовим матеріалом AES помічено секретним")
        check(6 not in {b.type for b in sb if cr.default_selected(b)}, "W4: блок AES із ключем типово не застосовується")
    finally:
        time.sleep = old_sleep


# ----------------------------------------------------------------------------------------------------------------------
#  Z1: панелі (xvfb)
# ----------------------------------------------------------------------------------------------------------------------

def _spin(app, n=3):
    for _ in range(n):
        app.update()


def _wait_idle(app, limit=15.0):
    t0 = time.time()
    while time.time() - t0 < limit:
        app.update()
        if not app.busy and app.queue.empty():
            return
        time.sleep(0.02)


def test_gui():
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("ПРОПУЩЕНО (GUI): нема tkinter")
        return
    if not os.environ.get("DISPLAY"):
        print("ПРОПУЩЕНО (GUI): нема DISPLAY")
        return
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb
    import gui_dialogs as gd
    import test_cps_csv as tc
    from cps_ui.app import CpsApp, SECTIONS
    from cps_ui.settings import Settings

    old_sleep = no_sleep()
    tmp = tempfile.mkdtemp(prefix="r30g_")
    spath = os.path.join(tmp, "ui.json")
    os.environ["TYT_CPS_SETTINGS"] = spath
    os.environ["HOME"] = tmp
    app = CpsApp(settings=Settings(spath), autoprobe=False)
    errors, infos = [], []
    mb.showinfo = lambda *a, **k: infos.append(a)
    mb.showerror = lambda *a, **k: errors.append(a)
    confirms = []
    gd.confirm_dialog = lambda *a, **k: (confirms.append(a), True)[1]
    orig_open_radio = cl.open_radio
    try:
        app.geometry("1300x900")
        app.update()
        keys = [c.key for _g, _t, cls in SECTIONS for c in cls]
        check("allsettings" in keys and "themes" in keys, "Z1: панелі «Теми екрана» і «Усі налаштування» є в SECTIONS")

        # ---------- теми: .gtm ----------
        app.show("themes")
        _spin(app)
        p = app.get_panel("themes")
        check("українська" in p.match_label.cget("text") and "класична" in p.match_label.cget("text"), "V6: у панелі показано збіг з UA і класичною: %s" % p.match_label.cget("text"))
        check("32 з 32" in p.match_label.cget("text"), "V6: початкова нічна (стокова UA) -- 32 з 32 для української")
        night_p = os.path.join(TESTDATA, "theme_night.gtm")
        day_p = os.path.join(TESTDATA, "theme_day.gtm")
        # V3: .gtm застосовується до відкритої теми; ім'я theme_*.gtm підказки не дає
        p.daytime.set("night")
        p._on_daytime()
        fd.askopenfilename = lambda **k: night_p
        n_conf = len(confirms)
        p._on_load_file()
        want = th.load_gtm(night_p)
        check(p.colors["night"] == want and p.dt == "night" and len(confirms) == n_conf, "V1/V3: theme_night.gtm завантажено у відкриту (нічну) тему без зайвих питань")
        check("0 з 32" in p.match_label.cget("text") and "1 з 32" in p.match_label.cget("text"), "V6: збіг нічної: UA 0, класична 1 (%s)" % p.match_label.cget("text"))
        check(th.to_hex(p.colors["night"][th.INDEX["FG_RSSI_BAR"]]) == "#00FF00", "V4: у панелі нічна FG_RSSI_BAR == #00FF00")
        # завантаження денного файла у відкриту нічну: вона перепише нічну (файл не вирішує)
        p.daytime.set("day")
        p._on_daytime()
        fd.askopenfilename = lambda **k: day_p
        p._on_load_file()
        check(p.dt == "day" and p.colors["day"] == th.load_gtm(day_p), "V3: .gtm у відкриту денну")
        check("15 з 32" in p.match_label.cget("text") and "17 з 32" in p.match_label.cget("text"), "V6: збіг денної: UA 15, класична 17")
        # підказка за іменем: файл n.gtm при відкритій денній
        named = os.path.join(tmp, "n.gtm")
        open(named, "wb").write(open(night_p, "rb").read())
        fd.askopenfilename = lambda **k: named
        confirms.clear()
        before = list(p.colors["day"])
        p._on_load_file()
        check(len(confirms) == 1 and "нічну" in confirms[0][2] and p.colors["day"] == th.load_gtm(named), "V3: ім'я n.gtm при відкритій денній -- підказка в діалозі; підтвердження -> у ВІДКРИТУ денну")
        gd.confirm_dialog = lambda *a, **k: (confirms.append(a), False)[1]
        p.colors["day"] = list(before)
        p._on_load_file()
        check(p.colors["day"] == before, "V3: «Скасувати» у підказці -- кольори не змінено")
        gd.confirm_dialog = lambda *a, **k: (confirms.append(a), True)[1]
        # поганий розмір
        bad = os.path.join(tmp, "x.gtm")
        open(bad, "wb").write(b"\x00" * 65)
        fd.askopenfilename = lambda **k: bad
        n_err = len(errors)
        p._on_load_file()
        check(len(errors) == n_err + 1 and "65" in errors[-1][1] and p.colors["day"] == before, "V1: 65 байтів -- відмова словами, кольори в панелі не змінено")
        errors.clear()
        # збереження: типово .gtm = 64 байти блока
        saved = {}

        def fake_save(**k):
            saved.update(k)
            return os.path.join(tmp, "out.gtm")
        fd.asksaveasfilename = fake_save
        p.daytime.set("night")
        p._on_daytime()
        p._on_save_file()
        out = open(os.path.join(tmp, "out.gtm"), "rb").read()
        check(saved.get("defaultextension") == ".gtm" and saved.get("initialfile") == "n.gtm" and saved["filetypes"][0][1] == "*.gtm", "V1: діалог збереження типово .gtm (n.gtm для нічної)")
        check(out == th.encode_block(p.colors["night"]) and len(out) == 64, "V1: .gtm == ті самі 64 байти, що пішли б у блок рації")
        # другий варіант: текстовий формат у тому самому діалозі
        check(any(ft[1] == "*.txt" for ft in saved["filetypes"]), "V2: текстовий формат лишився другим варіантом у діалозі")
        fd.asksaveasfilename = lambda **k: os.path.join(tmp, "t.txt")
        p._on_save_file()
        check(open(os.path.join(tmp, "t.txt"), encoding="utf-8").read().startswith("# OpenTYT"), "V2: *.txt -- текстовий формат OpenTYT-theme-1")
        # V7: два явні скидання
        p._on_reset()
        ua = list(p.colors["night"])
        p._on_reset_classic()
        cl_ = list(p.colors["night"])
        check(ua == th.stock_colors("night", "ua") and cl_ == th.stock_colors("night", "classic") and ua != cl_, "V7: «українська» і «класична» дають різні таблиці прошивки")
        check(p.reset_btn.cget("text") == "українська" and p.reset_classic_btn.cget("text") == "класична", "V7: на кнопках явно «українська»/«класична»")

        # ---------- «Усі налаштування» без документа, з порожнім кодплагом і повним ----------
        for label, spi in (("без документа", None), ("порожній", tc.base.make_spi()), ("повний", tc.make_fixture_spi())):
            if spi is not None:
                _cp, data = tc.codeplug_of(spi)
                src = os.path.join(tmp, "%s.zip" % label.replace(" ", "_"))
                open(src, "wb").write(data)
                check(app.doc_open_file(src), "Z1: відкрито %s кодплаг" % label)
            app.show("allsettings")
            _spin(app)
            ap = app.get_panel("allsettings")
            check(type(ap).__name__ == "AllSettingsPanel", "Z1 (%s): панель «Усі налаштування» відкривається" % label)
            check(str(ap.save_btn.cget("state")) == "disabled" and str(ap.apply_btn.cget("state")) == "disabled", "Z1 (%s): без рації збереження/запис вимкнені" % label)
            check(str(ap.load_btn.cget("state")) != "disabled", "Z1 (%s): читання файла працює без рації" % label)
            app.show("backup")
            _spin(app)
            bp = app.get_panel("backup")
            check(not hasattr(bp, "region_var") and not hasattr(bp, "region_only_button"), "W3.1/Z1 (%s): R50 -- окремих прапорців і кнопки «лише область» на панелі нема (усе у вікні «Відновити…»)" % label)
            check(str(bp.restore_button.cget("state")) == "disabled", "Z1 (%s): без рації «Відновити…» вимкнено" % label)

        # ---------- файл налаштувань і запис через панель на підробленій рації ----------
        spi_a, spi_b = new_spi_with(1), new_spi_with(2)
        radio_a = tcr.FakeRadioX(bytearray(spi_a))
        cl.open_radio = lambda *a, **k: radio_a
        ap = app.get_panel("allsettings")
        sfile = os.path.join(tmp, "all.json")
        fd.asksaveasfilename = lambda **k: sfile
        mb.showinfo = lambda *a, **k: infos.append(a)
        ap._on_save()
        _wait_idle(app)
        check(os.path.exists(sfile) and len(cr.load_settings_file(sfile)[0]) == len(SIZES), "W4/Z1: «Зберегти всі налаштування» записало файл з усіма блоками")
        fd.askopenfilename = lambda **k: sfile
        ap._on_load()
        check(set(ap.sel_vars) == set(SIZES) and ap.sel_vars[10].get() is False and ap.sel_vars[4].get() is True, "W4.2/Z1: список блоків: RCTL_STATE типово не позначено, теми позначено")
        radio_b = tcr.FakeRadioX(bytearray(spi_b))
        cl.open_radio = lambda *a, **k: radio_b
        pb0 = payloads_of(region_of(radio_b.spi))
        ap.sel_vars[8].set(False)
        ap._on_apply()
        _wait_idle(app)
        got = payloads_of(region_of(radio_b.spi))
        pa = payloads_of(region_of(spi_a))
        check(got[4] == pa[4] and got[8] == pb0[8] and got[10] == pb0[10], "W4/Z1: панель записала позначені блоки; знятий (8) і стан (10) не чіпано")
        check(not errors, "Z1: без вікон помилок: %r" % errors)

        # ---------- панель бекапу: відновлення з прапорцем ----------
        bp = app.get_panel("backup")
        bpath, _d, _m = mk_zip(spi_a)
        fd.askopenfilename = lambda **k: bpath
        radio_c = tcr.FakeRadioX(bytearray(spi_b))
        cl.open_radio = lambda *a, **k: radio_c
        bp.start_restore({"path": bpath, "kind": "zip", "codeplug": True, "region": True, "state": False, "keys": False})
        _wait_idle(app, 40.0)
        check(payloads_of(region_of(radio_c.spi))[4] == pa[4] and payloads_of(region_of(radio_c.spi))[10] == pb0[10], "W3/Z1: «Відновити кодплаг» з прапорцем області -- область відновлено (стан RCTL лишився)")
        check(not errors, "Z1: відновлення з прапорцем -- без помилок: %r" % errors)
        radio_d = tcr.FakeRadioX(bytearray(spi_b))
        cl.open_radio = lambda *a, **k: radio_d
        bp.start_restore({"path": bpath, "kind": "zip", "codeplug": True, "region": False, "state": False, "keys": False})
        _wait_idle(app, 40.0)
        check(region_of(radio_d.spi) == region_of(spi_b), "CF5/Z1: без прапорця область лишилась як була")
    finally:
        cl.open_radio = orig_open_radio
        time.sleep = old_sleep
        app.destroy()


def main():
    import faulthandler
    faulthandler.dump_traceback_later(280, exit=True)
    for t in (test_constants_match_firmware, test_gtm, test_parse_manifest, test_backup_contains_region, test_restore_roundtrip, test_partial_failure,
              test_no_write_outside_region, test_settings_file, test_gui):
        try:
            t()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILS.append("%s: виняток %r" % (t.__name__, e))
    if FAILS:
        print("test_r30: ПРОВАЛЕНО перевірок: %d" % len(FAILS))
        return 1
    print("test_r30: усе гаразд (.gtm, область custom-data у бекапі/відновленні/файлі налаштувань, збій посеред запису, межі запису, панелі).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
