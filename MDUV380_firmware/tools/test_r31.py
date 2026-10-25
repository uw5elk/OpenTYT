# -*- coding: utf-8 -*-
"""R31 (Z1-Z6): ключі AES у бекапі й відновленні (aes_keys_backup.py, restore_extras.py, cps_link.backup_codeplug) і база позивних DMR ID (dmr_db.py,
flash_guard.py, cps_ui/p_backup.py, cps_ui/p_dmrdb.py).
Логіка -- у будь-якому python3; GUI -- лише з tkinter + DISPLAY (`xvfb-run -a python3.12 tools/test_r31.py`).
Рації нема: SPI-флеш підроблено (FakeRadioX з test_cps_restore розуміє 'R' і 'X 1/2/3'), тож РЕАЛЬНІ алгоритми запису відпрацьовують на підробленому флеші.
Формат бази перевіряється проти РЕАЛЬНОГО коду прошивки: функція dmrDbTextDecode і таблиця DECOMPRESS_LUT витягуються з uiUtilities.c і компілюються gcc."""
import datetime
import io
import json
import os
import random
import re
import struct
import subprocess
import sys
import tempfile
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import aes_keys_backup as akb            # noqa: E402
import cps_link as cl                    # noqa: E402
import dmr_db as db                      # noqa: E402
import flash_guard as fg                 # noqa: E402
import restore_extras as rx              # noqa: E402
import test_cps_link as base             # noqa: E402
import test_cps_restore as tcr           # noqa: E402

FAILS = []
tcr.FakeRadioX.close = lambda self: None
APP = os.path.join(HERE, "..", "application")


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
    old = time.sleep
    time.sleep = lambda _s: None
    return old


# ----------------------------------------------------------------------------------------------------------------------
#  Підроблена таблиця ключів
# ----------------------------------------------------------------------------------------------------------------------

def make_table(seed, occupied, blank_empty=True):
    """1600 Б: слоти з `occupied` -- тип 4/7, назва, «загорнутий» ключ (псевдовипадковий); решта -- як лишає стокова рація (тип 4 + обгортка BLANK) або 0xFF."""
    t = bytearray(akb.KEYS_LEN)
    for s in range(akb.ENTRIES):
        e = bytearray(akb.ENTRY_LEN)
        if s in occupied:
            e[0] = 4 if s % 2 else 7
            e[4:36] = ("K%d_%d" % (seed, s)).encode("utf-16-le").ljust(32, b"\x00")
            e[36:68] = bytes(((seed * 31 + s * 17 + i * 5) % 251) + 1 for i in range(32))
        elif s == 0:
            e[:] = b"\x00" * akb.ENTRY_LEN
        elif blank_empty:
            e[0] = 4
            e[4:36] = str(s).encode("utf-16-le").ljust(32, b"\x00")
            e[36:68] = akb.WRAPPED_BLANK
        else:
            e[:] = b"\xff" * akb.ENTRY_LEN
        t[s * akb.ENTRY_LEN:(s + 1) * akb.ENTRY_LEN] = e
    return bytes(t)


def put_table(spi, table):
    spi[akb.KEYS_START:akb.KEYS_START + akb.KEYS_LEN] = table
    return spi


def table_of(spi):
    return bytes(spi[akb.KEYS_START:akb.KEYS_START + akb.KEYS_LEN])


def mk_zip(spi, **kw):
    radio = tcr.FakeRadioX(bytearray(spi))
    data, manifest = cl.backup_codeplug(cl.CpsLink(radio), rng=random.Random(5), log=quiet, **kw)
    d = tempfile.mkdtemp(prefix="r31z_")
    path = os.path.join(d, "backup.zip")
    open(path, "wb").write(data)
    return path, data, manifest, radio


def confirm_recorder(answer=True):
    asked = []

    def confirm(text, plan=None):
        asked.append(text)
        return answer
    return confirm, asked


# ----------------------------------------------------------------------------------------------------------------------
#  Z0: константи == код прошивки
# ----------------------------------------------------------------------------------------------------------------------

def test_constants_match_firmware():
    hook = read_text("source", "crypto", "dmr_aes_hook.c")
    check("#define STOCK_KEY_TABLE_BASE   0xD9F9Cu" in hook and "#define STOCK_KEY_ENTRY_LEN    0x64" in hook, "Z0: адреса таблиці й довжина запису в dmr_aes_hook.c")
    check(re.search(r"STOCK_KEY_MIN_ID\s+1\b", hook) and re.search(r"STOCK_KEY_MAX_ID\s+15\b", hook), "Z0: keyId 1..15 у прошивці")
    check("stockKeyEntryAddr(id)  (STOCK_KEY_TABLE_BASE + STOCK_KEY_ENTRY_LEN * (uint32_t)(id))" in hook, "Z0: адреса запису = база + 100*keyId")
    check(akb.KEYS_START == 0xD9F9C and akb.ENTRY_LEN == 100 and akb.ENTRIES == 16 and akb.KEYS_LEN == 0x640, "Z0: константи aes_keys_backup")
    check(akb.slot_addr(1) == 0xDA000 and akb.slot_addr(15) + akb.ENTRY_LEN == 0xDA5DC, "Z0: слоти 1..15 лежать у 0xDA000..0xDA5DB (один сектор)")
    check(akb.slot_addr(1) // 4096 == akb.slot_addr(15) // 4096 == (akb.slot_addr(15) + 99) // 4096, "Z0: усі слоти в одному 4-КіБ секторі")
    check(akb.TYPES_AES256 == (0x04, 0x07) and re.search(r"STOCK_KEY_TYPE_AES256\s+0x04", hook) and re.search(r"STOCK_KEY_TYPE_AES256B\s+0x07", hook), "Z0: типи запису 0x04/0x07")
    try:
        import stock_key_table as skt
        check(akb.WRAPPED_ZERO == skt.wrap_key(bytes(32)) and akb.WRAPPED_BLANK == skt.wrap_key(skt.BLANK_KEY), "Z0: «порожні» обгортки == stock_key_table.wrap_key")
        check(skt.STOCK_KEY_TABLE_BASE == akb.KEYS_START and skt.STOCK_KEY_ENTRY_LEN == akb.ENTRY_LEN, "Z0: геометрія == stock_key_table")
        # зайнятість: наш висновок без криптографії == висновок прошивки (розгорнути й перевірити)
        ok = True
        for key in (bytes(32), skt.BLANK_KEY, bytes(range(1, 33)), bytes(31) + b"\x02"):
            e = bytearray(100)
            e[0] = 4
            e[36:68] = skt.wrap_key(key)
            ok &= akb.slot_occupied(bytes(e)) == skt.is_key_present(key)
        check(ok, "Z0: slot_occupied == stockKeyIsPresent(розгорнутого ключа)")
    except ImportError:
        print("ПРОПУЩЕНО (Z0): нема cryptography")
    ui = read_text("source", "user_interface", "uiUtilities.c")
    check("const uint32_t DMRID_MEMORY_LOCATION_1 = 0x30000 + FLASH_ADDRESS_OFFSET;" in ui and "const uint32_t DMRID_MEMORY_LOCATION_2 = 0xB8000 + FLASH_ADDRESS_OFFSET;" in ui,
          "Z0: адреси баз у uiUtilities.c")
    check("const uint32_t DMRID_HEADER_LENGTH = 0x0C;" in ui and "(0x40000 - DMRID_HEADER_LENGTH)" in ui and "- 0x4a" in ui, "Z0: заголовок 12 Б, область 0x40000, зсув довжини 0x4a")
    check(db.AREA1_START == 0x50000 and db.AREA2_START == 0xD8000 and db.AREA1_LEN == 0x40000 and db.HEADER_LEN == 12 and db.LEN_BIAS == 0x4A, "Z0: константи dmr_db")
    codeplug_h = read_text("include", "functions", "codeplug.h")
    check("#define FLASH_ADDRESS_OFFSET  (128 * 1024)" in codeplug_h and cl.FLASH_ADDRESS_OFFSET == 0x20000, "Z0: FLASH_ADDRESS_OFFSET == 128 КіБ")
    g = read_text("include", "user_interface", "uiGlobals.h")
    check(re.search(r"MAX_DMR_ID_CONTACT_TEXT_LENGTH\s+51\b", g) and re.search(r"MIN_ENTRIES_BEFORE_USING_SLICES\s+40\b", g), "Z0: text[51], 40 записів до зрізів")
    check(db.MAX_REC_LEN == 4 + 51 and db.MIN_ENTRIES_BEFORE_USING_SLICES == 40, "Z0: dmr_db: sizeof(dmrIdDataStruct_t) = 55, поріг 40")
    lut = re.search(r"DECOMPRESS_LUT\[64\] = \{(.*?)\};", ui, re.S).group(1)
    chars = "".join(re.findall(r"'(.)'", lut))
    check(chars == db.LUT and len(db.LUT) == 64, "Z0: таблиця DECOMPRESS_LUT == dmr_db.LUT")
    check(fg.check_windows() == [], "Z0/Z6: жодне вікно запису не перетинає захищені зони: %r" % fg.check_windows())
    check(db.AREA2_START < akb.KEYS_START < db.AREA2_START + 0x4000, "Z0: таблиця ключів лежить ВСЕРЕДИНІ області №2 (ось чому її не пишемо)")
    check(fg.WINDOWS["dmrdb"] == (0x50000, 0x90000) and fg.WINDOWS["keys"] == (0xDA000, 0xDA5DC), "Z0: вікна запису")


# ----------------------------------------------------------------------------------------------------------------------
#  Z2: ключі в бекапі й відновленні
# ----------------------------------------------------------------------------------------------------------------------

OCC = {2, 5, 9}


def spi_with_keys(occupied=OCC, seed=1, base_fn=None):
    spi = (base_fn or tcr.spi_a)()
    return put_table(spi, make_table(seed, occupied))


def test_backup_keys():
    spi_a = spi_with_keys()
    table_a = table_of(spi_a)
    path, data, manifest, radio = mk_zip(spi_a)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        check("aeskeys.bin" in z.namelist() and z.read("aeskeys.bin") == table_a, "K2.1/Z2: у .zip є aeskeys.bin == таблиця з рації байт-в-байт")
        mtext = z.read("manifest.json").decode("utf-8")
    p = manifest["parts"]["aesKeys"]
    check(p["start"] == 0xD9F9C and p["length"] == 0x640 and p["sha256"] == cl.sha256(table_a), "K2.1: маніфест: діапазон і SHA-256")
    check(p["occupiedSlots"] == [2, 5, 9], "K2.1: маніфест перелічує зайняті слоти: %r" % p["occupiedSlots"])
    check(p["containsSecrets"] is True and manifest["containsSecrets"] is True, "K2.2: частина й архів позначені як секретні")
    check("aesKeys" in manifest["includes"] and manifest["restorable"] == ["eeprom", "flash"], "K2.1: includes має aesKeys; restorable лишається [eeprom, flash]")
    leaked = [s for s in OCC if akb.entry_of(table_a, s)[36:68].hex() in mtext or akb.entry_of(table_a, s)[36:68].hex().upper() in mtext]
    check(not leaked, "K2.1: у маніфесті НЕМАЄ ключового матеріалу (слоти %r)" % leaked)
    wrapped_b64 = [akb.entry_of(table_a, s)[36:68] for s in OCC]
    check(all(w.hex() not in mtext for w in wrapped_b64) and "ключі шифрування" in manifest["note"], "K2.2: у примітці маніфесту сказано про ключі шифрування")
    check(akb.read_backup_keys(data) == table_a and akb.read_backup_keys(path) == table_a, "K2: read_backup_keys читає з байтів і зі шляху")
    m, ee, fl = cl.read_backup_zip(data)
    check(m["parts"]["aesKeys"]["sha256"] == cl.sha256(table_a), "K2: cps_link.read_backup_zip перевіряє частину")
    # лише читання; кожен читач таблиці дійсно торкається лише 0xD9F9C..
    check(radio.x_total == 0 and not radio.c_calls, "K2: бекап не пише в рацію")
    # пошкоджена таблиця в архіві
    bad = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as zi, zipfile.ZipFile(bad, "w") as zo:
        for n in zi.namelist():
            b = zi.read(n)
            if n == "aeskeys.bin":
                b = b[:50] + bytes([b[50] ^ 0xFF]) + b[51:]
            zo.writestr(n, b)
    try:
        cl.read_backup_zip(bad.getvalue())
        check(False, "K2: пошкоджена таблиця мала бути відхилена")
    except cl.CpsError as e:
        check("SHA-256" in str(e), "K2: пошкоджена таблиця -- SHA-256 не збігається")
    # K2.3: без ключів
    path2, data2, m2, radio2 = mk_zip(spi_a, aes_keys=False)
    with zipfile.ZipFile(io.BytesIO(data2)) as z:
        check("aeskeys.bin" not in z.namelist(), "K2.3/Z2: з aes_keys=False файла ключів у .zip нема")
    check("aesKeys" not in m2["parts"] and "aesKeys" not in m2["includes"] and not m2["containsSecrets"], "K2.3: у маніфесті ключів нема, архів не секретний")
    touched = [q for q in radio2.requests if q[0] == cl.CPS_ACCESS_FLASH and q[1] < akb.KEYS_START + akb.KEYS_LEN and q[1] + q[2] > akb.KEYS_START]
    check(not touched, "K2.3/Z2: без ключів рація НЕ читалась у діапазоні 0xD9F9C..0xDA5DB: %r" % touched)
    check(akb.read_backup_keys(data2) is None, "K2.3: read_backup_keys -> None для архіву без ключів")
    # повний знімок з ключами й без них
    _p3, d3, m3, _r3 = mk_zip(spi_a, full_snapshot=True)
    check(m3["includes"].count("aesKeys") == 1 and m3["parts"]["aesKeys"]["occupiedSlots"] == [2, 5, 9] and "dmrIdDb" in m3["parts"] and "voicePrompts" in m3["parts"],
          "K2/D5: повний знімок має ключі зі слотами, голосові підказки й базу позивних")
    with zipfile.ZipFile(io.BytesIO(d3)) as z:
        check(sorted(z.namelist()) == ["aeskeys.bin", "customdata.bin", "dmriddb.bin", "eeprom.bin", "flash.bin", "manifest.json", "voiceprompts.bin"] and
              len(z.read("dmriddb.bin")) == 0x40000, "D5.1: повний знімок: dmriddb.bin = область №1 (256 КіБ)")
    _p4, d4, m4, _r4 = mk_zip(spi_a, full_snapshot=True, aes_keys=False)
    check("aesKeys" not in m4["parts"] and "voicePrompts" in m4["parts"] and "ключів" not in m4["note"].replace("ключів AES відновлює", ""), "K2.3: повний знімок без ключів -- ключів нема, підказки є")
    # порожня таблиця (ні одного слота): архів усе одно коректний
    _p5, d5, m5, _r5 = mk_zip(tcr.spi_a())
    check(m5["parts"]["aesKeys"]["occupiedSlots"] == [] if "aesKeys" in m5["parts"] else False, "K2.1: порожня таблиця -- occupiedSlots порожній")


def spi_b_with(table_b):
    s = tcr.spi_b(tcr.spi_a())
    return put_table(s, table_b)


def test_restore_keys_roundtrip():
    old_sleep = no_sleep()
    try:
        table_a = make_table(1, OCC)
        spi_a = put_table(tcr.spi_a(), table_a)
        path, data, _m, _r = mk_zip(spi_a)
        # рація B: ключі 2 і 5 стерті (BLANK), в 9 -- інший ключ, у 3 -- свій ключ, якого в архіві нема
        tb = bytearray(table_a)
        for s in (2, 5):
            tb[s * 100:(s + 1) * 100] = make_table(0, set())[s * 100:(s + 1) * 100]
        tb[9 * 100:10 * 100] = make_table(7, {9})[900:1000]
        tb[3 * 100:4 * 100] = make_table(7, {3})[300:400]
        spi_b = put_table(tcr.spi_b(tcr.spi_a()), bytes(tb))
        before = bytes(spi_b)
        radio = tcr.FakeRadioX(bytearray(spi_b))
        confirm, asked = confirm_recorder(True)
        d = os.path.dirname(path)
        res = akb.restore_keys(cl.CpsLink(radio), path, confirm, log=quiet)
        t_after = table_of(radio.spi)
        for s in (2, 5, 9):
            check(akb.entry_of(t_after, s) == akb.entry_of(table_a, s), "K3/Z2: слот %d == бекап байт-в-байт" % s)
        check(akb.entry_of(t_after, 3) == akb.entry_of(bytes(tb), 3) and akb.slot_occupied(akb.entry_of(t_after, 3)), "K3: слот 3 (є в рації, нема в архіві) не чіпано")
        keep = [s for s in range(16) if s not in (2, 5, 9)]
        check(all(akb.entry_of(t_after, s) == akb.entry_of(bytes(tb), s) for s in keep), "K3: решта слотів і запис 0 не змінились")
        outside = bytes(radio.spi[:0xDA000]) + bytes(radio.spi[0xDB000:])
        check(outside == before[:0xDA000] + before[0xDB000:], "K3.4/Z6: поза сектором 0xDA000 флеш не змінено ні на байт (калібрування, кодплаг, база, підказки)")
        check(bytes(radio.spi[0xDA5DC:0xDB000]) == before[0xDA5DC:0xDB000], "K3.4: хвіст сектора 0xDA000 після слота 15 не змінено")
        check(radio.commits == [0xDA] * 3 and not radio.cal_touched, "K3.2: три слоти -- три записи сектора 0xDA, калібрування недоторкане: %r" % radio.commits)
        check(res["result"]["written"] == [2, 5, 9] and res["tableMatchesExpected"] is True and not res["result"]["failed"], "K3.2: записано й звірено слоти 2, 5, 9")
        txt = asked[0]
        check("Слоти до запису: 2, 5, 9." in txt and "зараз зайняті (ключі буде ЗАМІНЕНО): 9." in txt, "K3.1: підтвердження: слоти й які зайняті: %s" % txt.split("\n")[3:5])
        check(not any(akb.entry_of(table_a, s)[36:68].hex() in txt for s in OCC), "K3.1: у тексті підтвердження ключів нема")
        sc = res["safetyCopy"]
        check(os.path.dirname(sc) == d and open(sc, "rb").read() == bytes(tb) and "aeskeys_pre-restore" in os.path.basename(sc), "K3.3: страхова копія таблиці поряд з бекапом == стан ДО")
        check(radio.reset_requested, "K3: після запису рація перезавантажується")
        # повторно: уже все записано
        r2 = akb.restore_keys(cl.CpsLink(radio), path, confirm, log=quiet)
        check(r2["nothingToDo"] and "вже містить" in r2["text"], "K3: повторне відновлення -- нічого писати")
        # відмова у підтвердженні
        radio_c = tcr.FakeRadioX(bytearray(spi_b))
        r3 = akb.restore_keys(cl.CpsLink(radio_c), path, lambda *_: False, log=quiet)
        check(r3["cancelled"] and radio_c.x_total == 0 and bytes(radio_c.spi) == before, "K3: «Скасувати» -- у рацію нічого не записано")

        # --- через повний цикл: кодплаг + ключі (прапорець УВІМКНЕНО) ---
        radio_d = tcr.FakeRadioX(bytearray(spi_b))
        confirm2, asked2 = confirm_recorder(True)
        out = rx.restore_codeplug_and_extras(cl.CpsLink(radio_d), path, confirm2, log=quiet, with_keys=True)
        check(out["keys"]["result"]["written"] == [2, 5, 9] and all(akb.entry_of(table_of(radio_d.spi), s) == akb.entry_of(table_a, s) for s in (2, 5, 9)),
              "Z2: повний цикл з прапорцем: ключі відновлено")
        check(sum(1 for c in radio_d.c_calls if c[:2] == bytes([6, 1])) == 1, "Z2: рівно один C 6 1")
        # --- прапорець ВИМКНЕНО: ключі в рації не чіпаються, про це сказано ---
        radio_e = tcr.FakeRadioX(bytearray(spi_b))
        out2 = rx.restore_codeplug_and_extras(cl.CpsLink(radio_e), path, confirm_recorder(True)[0], log=quiet, with_keys=False)
        check(out2["keys"] is None and table_of(radio_e.spi) == bytes(tb), "Z2/CG4: прапорець вимкнено -- таблиця ключів у рації не змінилась")
        check("НЕ відновлювались" in out2["keysNote"] and "2, 5, 9" in out2["keysNote"], "K4.2: вимкнений прапорець -- сказано, що в архіві є ключі й їх не відновлювали: %s" % out2["keysNote"])
        check(all(s != 0xDA for k, s in radio_e.x_calls if k == 1), "Z2: прапорець вимкнено -- жодного X для сектора 0xDA")
    finally:
        time.sleep = old_sleep


def test_slot0_ignored():
    """Запис 0 таблиці прошивка не читає й не пише (keyId 0 -- «вимкнено»); він лежить в іншому секторі (0xD9000) і не відновлюється."""
    old_sleep = no_sleep()
    try:
        t = bytearray(make_table(1, {2}))
        t[0:100] = bytes([4]) + b"\x00\x00\x00" + bytes(range(1, 97))          # «зайнятий» вигляд запису 0
        spi_a = put_table(tcr.spi_a(), bytes(t))
        path, _d, m, _r = mk_zip(spi_a)
        check(m["parts"]["aesKeys"]["occupiedSlots"] == [2], "K1.2: запис 0 не потрапляє до зайнятих слотів")
        tb = bytearray(make_table(5, {7}))
        tb[0:100] = b"\x5a" * 100
        spi_b = put_table(tcr.spi_b(tcr.spi_a()), bytes(tb))
        radio = tcr.FakeRadioX(bytearray(spi_b))
        res = akb.restore_keys(cl.CpsLink(radio), path, confirm_recorder()[0], log=quiet)
        check(table_of(radio.spi)[:100] == b"\x5a" * 100 and res["result"]["written"] == [2], "K3.4: запис 0 у рації не змінено")
        check(all(0xD9000 // 4096 != s_ for k, s_ in radio.x_calls if k == 1), "K3.4: сектор 0xD9000 (запис 0 і область №2 бази) не готувався до запису")
    finally:
        time.sleep = old_sleep


def test_old_zip_without_keys():
    old_sleep = no_sleep()
    try:
        table_b = make_table(3, {1, 4})
        spi_b = put_table(tcr.spi_b(tcr.spi_a()), table_b)
        path, data, m, _r = mk_zip(tcr.spi_a(), aes_keys=False, custom_data=False)       # архів у форматі до R30/R31
        check("aesKeys" not in m["parts"] and m["includes"] == ["eeprom", "flash"], "Z3: старий формат архіву без ключів і області")
        radio = tcr.FakeRadioX(bytearray(spi_b))
        res = akb.restore_keys(cl.CpsLink(radio), path, confirm_recorder()[0], log=quiet)
        check(res["absent"] and "нема" in res["text"] and radio.x_total == 0 and table_of(radio.spi) == table_b, "Z3/K4.2: restore_keys: ключів нема -- сказано словами, рація не чіпана")
        radio2 = tcr.FakeRadioX(bytearray(spi_b))
        out = rx.restore_codeplug_and_extras(cl.CpsLink(radio2), path, confirm_recorder()[0], log=quiet, with_keys=True)
        check(out["keys"]["absent"] and "нема" in out["keysNote"] and table_of(radio2.spi) == table_b, "Z3: повний цикл зі старим архівом і прапорцем: ключі лишились, про відсутність сказано")
        radio3 = tcr.FakeRadioX(bytearray(spi_b))
        out3 = rx.restore_codeplug_and_extras(cl.CpsLink(radio3), path, confirm_recorder()[0], log=quiet, with_keys=False)
        check("нема" in out3["keysNote"] and table_of(radio3.spi) == table_b, "Z3/K4.2: прапорець вимкнено -- про відсутність ключів в архіві все одно сказано")
        # архів зі зламаним діапазоном ключів: відмова, нічого не записано
        bad = io.BytesIO()
        path_k, data_k, _mk, _rk = mk_zip(put_table(tcr.spi_a(), make_table(1, {2})))
        with zipfile.ZipFile(io.BytesIO(data_k)) as zi, zipfile.ZipFile(bad, "w") as zo:
            for n in zi.namelist():
                b = zi.read(n)
                if n == "manifest.json":
                    mm = json.loads(b.decode("utf-8"))
                    mm["parts"]["aesKeys"]["start"] = 0xDA800
                    b = json.dumps(mm).encode("utf-8")
                zo.writestr(n, b)
        pbad = os.path.join(tempfile.mkdtemp(prefix="r31b_"), "bad.zip")
        open(pbad, "wb").write(bad.getvalue())
        radio4 = tcr.FakeRadioX(bytearray(spi_b))
        try:
            akb.restore_keys(cl.CpsLink(radio4), pbad, confirm_recorder()[0], log=quiet)
            check(False, "K3.4: інший початок таблиці в маніфесті мав бути відхилений")
        except cl.CpsError as e:
            check("інший діапазон" in str(e) and radio4.x_total == 0, "K3.4: маніфест з іншим початком таблиці -- відмова до запису (%s)" % str(e)[:50])
    finally:
        time.sleep = old_sleep


def test_failure_on_third_slot():
    old_sleep = no_sleep()
    try:
        occ = {1, 4, 7, 12}
        table_a = make_table(2, occ)
        path, _d, _m, _r = mk_zip(put_table(tcr.spi_a(), table_a))
        table_b = make_table(9, {3})                      # у рації інші слоти; слоти 1, 4, 7, 12 порожні
        spi_b = put_table(tcr.spi_b(tcr.spi_a()), table_b)
        # кожен слот = X 1, X 2, X 3: після 6 X-команд рація «замовкає» -- третій слот (7) не запишеться
        radio = tcr.FakeRadioX(bytearray(spi_b), die_after_x=6)
        res = akb.restore_keys(cl.CpsLink(radio), path, confirm_recorder()[0], log=quiet, post_reset=False)
        r = res["result"]
        check(r["written"] == [1, 4] and r["failed"]["slot"] == 7 and r["untouched"] == [12], "Z4/K3.2: записані слоти 1, 4; збій на 7; слот 12 не торкались: %r" % r)
        t = table_of(radio.spi)
        check(akb.entry_of(t, 1) == akb.entry_of(table_a, 1) and akb.entry_of(t, 4) == akb.entry_of(table_a, 4), "Z4: перші два слоти записані")
        check(akb.entry_of(t, 7) == akb.entry_of(table_b, 7) and akb.entry_of(t, 12) == akb.entry_of(table_b, 12), "Z4: слоти 7 і 12 як були")
        check(akb.entry_of(t, 3) == akb.entry_of(table_b, 3), "Z4: слот 3 (чужий) не чіпано")
        txt = res["text"]
        check("Записано й звірено слоти: 1, 4." in txt and "ПОМИЛКА на слоті 7" in txt and "ЗАПИСАНІ й залишаються записаними" in txt and "Не торкався" in txt and "12" in txt,
              "Z4: звіт словами: %s" % txt.replace("\n", " | "))
        check(res["safetyCopy"] and open(res["safetyCopy"], "rb").read() == table_b, "Z4/K3.3: страхова копія є і дорівнює стану ДО")
        check(not radio.reset_requested, "Z4: post_reset=False -- без перезавантаження")
    finally:
        time.sleep = old_sleep


# ----------------------------------------------------------------------------------------------------------------------
#  Z6: межі запису
# ----------------------------------------------------------------------------------------------------------------------

def test_guard_bounds():
    radio = tcr.FakeRadioX(bytearray(tcr.spi_a()))
    ser = radio
    bad = [("keys", 0x10000, 4, "калібрування"), ("keys", 0x20000, 4, "custom-data"), ("keys", 0x50000, 4, "база позивних"), ("keys", 0xAF400, 4, "голосові підказки"),
           ("keys", 0x9B000, 4, "кодплаг"), ("keys", 0xD9F9C, 100, "запис 0 таблиці (його не відновлюємо)"), ("keys", 0xDA5DC - 10, 20, "за кінець слота 15"),
           ("keys", 0xDA000 - 1, 10, "перед слотом 1"), ("keys", 0xDB000, 4, "за сектором ключів"),
           ("dmrdb", 0x10000, 4, "калібрування"), ("dmrdb", 0x4F000, 4, "перед базою"), ("dmrdb", 0x20000, 4, "custom-data"), ("dmrdb", 0x90000, 4, "за областю №1"),
           ("dmrdb", 0x8FFF0, 0x20, "через кінець області №1"), ("dmrdb", 0xD8000, 4, "область №2"), ("dmrdb", 0xDA000, 100, "ключі AES"), ("dmrdb", 0xAF400, 4, "голосові підказки"),
           ("dmrdb", 0x9B000, 4, "кодплаг"), ("nonexistent", 0x50000, 4, "невідоме вікно")]
    for w, a, n, what in bad:
        try:
            fg.write_span(ser, a, b"\xab" * n, w)
            check(False, "Z6: запис у вікно %s на 0x%X (%s) мав бути відхилений" % (w, a, what))
        except fg.GuardError:
            pass
    check(radio.x_total == 0 and not radio.cal_touched and bytes(radio.spi) == bytes(tcr.spi_a()), "Z6: жодної X-команди, флеш не змінено після %d відхилень" % len(bad))
    # самоперевірка таблиць ловить зламане вікно
    worse = dict(fg.WINDOWS)
    worse["dmrdb"] = (0x50000, 0xDA100)
    check(fg.check_windows(worse) != [], "Z6: розширене вікно бази, що наїхало б на ключі/підказки, виявляється самоперевіркою")
    worse2 = dict(fg.WINDOWS)
    worse2["keys"] = (0xD9000, 0xDA5DC)       # наїжджає на початок області №2 бази (до таблиці ключів)
    check(fg.check_windows(worse2) != [], "Z6: розширене вікно ключів виявляється самоперевіркою")
    worse3 = dict(fg.WINDOWS)
    worse3["dmrdb"] = (0x20000, 0x90000)
    check(fg.check_windows(worse3) != [], "Z6: вікно бази, що захопило custom-data, виявляється самоперевіркою")


def spi_marked():
    """Образ із відмінними візерунками в усіх зонах, які не можна чіпати."""
    spi = tcr.spi_a()
    spi[0x20000:0x30000] = bytes((i * 7 + 1) % 251 for i in range(0x10000))
    spi[0x9B000:0xAF000] = bytes((i * 13 + 5) % 251 for i in range(0x14000))
    spi[0xAF400:0xD8000] = bytes((i * 3 + 9) % 251 for i in range(0xD8000 - 0xAF400))
    spi[0xD8000:0xD9F9C] = bytes((i * 11 + 2) % 251 for i in range(0xD9F9C - 0xD8000))
    spi[0xDB000:0xDC000] = bytes((i * 17 + 4) % 251 for i in range(0x1000))
    return spi


def untouched_outside(before, after, lo, hi):
    return bytes(before[:lo]) == bytes(after[:lo]) and bytes(before[hi:]) == bytes(after[hi:])


# ----------------------------------------------------------------------------------------------------------------------
#  Z5: база позивних
# ----------------------------------------------------------------------------------------------------------------------

def indep_encode(text, nbytes):
    """Незалежна від dmr_db реалізація стиснення: бітовий рядок з 6-бітних індексів."""
    lut = " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz."
    n = nbytes * 8 // 6
    t = (text + " " * n)[:n]
    bits = "".join(format(lut.index(c), "06b") for c in t)
    return int(bits, 2).to_bytes(nbytes, "big")


def c_decoder():
    """Скомпілювати dmrDbTextDecode із РЕАЛЬНОГО uiUtilities.c. Повертає шлях до бінарника або None."""
    src = read_text("source", "user_interface", "uiUtilities.c")
    m = re.search(r"static const uint8_t DECOMPRESS_LUT\[64\] = \{.*?\};", src, re.S)
    md = re.search(r"static void dmrDbTextDecode\([^)]*\)\s*\{", src)         # визначення, а не попереднє оголошення
    i = md.start()
    j = md.end() - 1
    depth, k = 0, j
    while True:
        depth += src[k] == "{"
        depth -= src[k] == "}"
        if depth == 0:
            break
        k += 1
    func = src[i:k + 1]
    prog = ("#include <stdint.h>\n#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n" + m.group(0) + "\n" + func + "\n"
            "int main(int c, char **v) { uint8_t in[64]; int n = (int)strlen(v[1]) / 2; for (int i = 0; i < n; i++) { unsigned x; sscanf(v[1] + 2 * i, \"%2x\", &x); in[i] = (uint8_t)x; }\n"
            "  uint8_t out[128]; memset(out, 0, sizeof out); dmrDbTextDecode(out, in, n); printf(\"%s\", out); return 0; }\n")
    d = tempfile.mkdtemp(prefix="r31c_")
    cpath, exe = os.path.join(d, "dec.c"), os.path.join(d, "dec")
    open(cpath, "w").write(prog)
    try:
        r = subprocess.run(["gcc", "-O1", "-o", exe, cpath], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return exe if r.returncode == 0 else None


def test_text_format():
    for text in ("UR5XXX Ivan", "", "A", "N0CALL John Smith", "a.b.c 0123456789"):
        for nb in (12, 15, 18):
            check(db.compress_text(text, nb) == indep_encode(db.sanitize(text), nb), "Z5: стиснення %r (%d Б) == незалежна реалізація" % (text, nb))
    check(db.decompress_text(db.compress_text("UR5XXX Ivan", 12)) == "UR5XXX Ivan", "Z5: кругом: стиснути -> розгорнути")
    check(db.decompress_text(db.compress_text("x" * 40, 12)) == "x" * 16, "Z5: довгий текст обрізається до 16 символів")
    check(db.sanitize("Богдан Ґалан-Їжак") == "Bohdan Galan Yizhak" and db.sanitize("Café Zoë") == "Cafe Zoe" and db.sanitize("a_b-c/d") == "a b c d",
          "Z5: транслітерація й чистка символів поза таблицею")
    exe = c_decoder()
    if exe is None:
        print("ПРОПУЩЕНО (Z5): нема gcc -- порівняння з C-функцією dmrDbTextDecode не виконано")
        return
    rnd = random.Random(7)
    samples = [db.compress_text(t, nb) for t in ("UR5XXX Ivan", "Test", "", "0123456789.abcdefZ") for nb in (12, 15, 18)]
    samples += [bytes(rnd.randrange(256) for _ in range(nb)) for nb in (12, 15, 18, 12, 12, 15) for _ in range(40)]
    bad = 0
    for s in samples:
        c = subprocess.run([exe, s.hex()], capture_output=True, timeout=20).stdout.decode("latin-1")
        if c != db.decompress_text(s):
            bad += 1
            print("   розбіжність:", s.hex(), repr(c), repr(db.decompress_text(s)))
    check(bad == 0, "Z5: dmr_db.decompress_text == СПРАВЖНЯ dmrDbTextDecode із прошивки на %d зразках (розбіжностей %d)" % (len(samples), bad))


def fw_lookup(image, target):
    """Двійковий пошук як у dmrIDLookup для формату 'N' (3 байти, без зрізів): повертає текст або None."""
    img = db.parse_image(image, want_records=False)
    lo, hi = 0, img.count - 1
    while lo <= hi:
        mid = (lo + hi) >> 1
        off = db.HEADER_LEN + mid * img.rec_len
        rid = int.from_bytes(image[off:off + 3], "little")
        if rid < target:
            lo = mid + 1
        elif rid > target:
            hi = mid - 1
        else:
            return db.decompress_text(image[off + 3:off + img.rec_len])
    return None


def test_build_image():
    recs = [(2550002, "UR2ABC Olena"), (255, "Z"), (2550001, "UR1ABC Ivan"), (3100001, "K1ABC Bob")]
    img = db.build_image(recs)
    exp = bytearray(b"IdN" + bytes([15 + 0x4A]) + bytes(4) + struct.pack("<I", 4))
    for rid, t in sorted(recs):
        exp += rid.to_bytes(3, "little") + indep_encode(t, 12)
    check(img == bytes(exp), "Z5: образ == очікувані байти за форматом (заголовок IdN, довжина 0x59, 4 записи по 15 Б, відсортовані)")
    check(len(img) == 12 + 4 * 15 and img[3] == 0x59, "Z5: розмір і байт довжини")
    p = db.parse_image(img)
    check(p.valid and p.count == 4 and p.rec_len == 15 and p.mode == "N" and [r[0] for r in p.records] == sorted(r[0] for r in recs), "Z5: розбір образа")
    check(all(fw_lookup(img, rid) == db.decompress_text(db.compress_text(t, 12)) for rid, t in recs) and fw_lookup(img, 4) is None, "Z5: двійковий пошук як у прошивці знаходить усі записи")
    # інші довжини запису
    for chars, rl in ((16, 15), (20, 18), (24, 21)):
        i2 = db.build_image([(1, "ABCDEFGHIJKLMNOPQRSTUVWX")], chars)
        check(i2[3] == rl + 0x4A and len(i2) == 12 + rl and db.parse_image(i2).records == [(1, "ABCDEFGHIJKLMNOPQRSTUVWX"[:chars])], "Z5: текст %d символів -- запис %d Б" % (chars, rl))
    # порожня база
    e = db.build_image([])
    pe = db.parse_image(e)
    check(e == b"IdN" + bytes([0x59]) + bytes(4) + bytes(4) and pe.valid and pe.count == 0 and pe.records == [] and not db.validate_for_write(pe), "Z5: порожня база -- лише заголовок, валідна")
    # один запис: попередження про ≤40 не показується (один запис -- min==max)
    one = db.parse_image(db.build_image([(7, "Solo")]))
    check(one.valid and one.records == [(7, "Solo")] and not one.warnings, "Z5: один запис")
    few = db.parse_image(db.build_image([(i, "x") for i in range(1, 11)]))
    check(few.warnings and "НАЙБІЛЬШОГО" in few.warnings[0], "Z5: 2..40 записів -- попередження про особливість dmrIDLookup (з коду)")
    big = db.parse_image(db.build_image([(i, "x") for i in range(1, 100)]))
    check(not big.warnings, "Z5: понад 40 записів -- без попереджень")
    # переповнення
    cap = db.capacity(15)
    check(cap == (0x40000 - 12) // 15 == 17475, "Z5: місткість області №1 для запису 15 Б -- %d" % cap)
    full = db.build_image([(i, "UR") for i in range(1, cap + 1)])
    check(len(full) <= db.AREA1_LEN and len(full) == 12 + cap * 15 and db.parse_image(full).valid and not db.validate_for_write(db.parse_image(full)), "Z5: рівно повна область -- вміщається, валідна")
    try:
        db.build_image([(i, "UR") for i in range(1, cap + 2)])
        check(False, "Z5: переповнення мало бути відхилене")
    except db.DbError as e:
        check("17475" in str(e), "Z5: переповнення на 1 запис -- відмова з місткістю: %s" % e)
    try:
        db.build_image([(0x1000000, "x")])
        check(False, "Z5: ID з 4 байтів у форматі 'N' має бути відхилений")
    except db.DbError:
        pass
    check(db.capacity(18) == (0x40000 - 12) // 18 and db.capacity(21) == (0x40000 - 12) // 21, "Z5: місткість для 18 і 21 Б")
    # розбір чужих/зламаних образів
    unsorted = bytearray(img)
    unsorted[12:15], unsorted[27:30] = unsorted[27:30], unsorted[12:15]
    pu = db.parse_image(bytes(unsorted))
    check(not pu.valid and db.validate_for_write(pu) and "не відсортовані" in pu.problems[0], "Z5: невідсортований образ відхиляється: %s" % pu.problems)
    check(not db.parse_image(b"\xff" * 32).valid and "Id" in db.parse_image(b"\xff" * 32).problems[0], "Z5: стерта область -- «це не база»")
    n_img = bytearray(img)
    n_img[2:3] = b"n"
    check(db.validate_for_write(db.parse_image(bytes(n_img))), "Z5: формат 'n' (область №2 на голосових підказках) цей інструмент не пише")
    trunc = db.parse_image(img[:12 + 15 * 2])
    check(not trunc.valid and "обрізано" in trunc.problems[0], "Z5: обрізаний файл -- проблема")
    over = bytearray(img)
    over[8:12] = struct.pack("<I", cap + 1)
    po = db.parse_image(bytes(over))
    check(db.validate_for_write(po) and any("№2" in w for w in po.warnings), "Z5: заголовок із count > місткості -- не записується, застерігає про область №2")
    # 4-байтний формат (читання)
    plain = bytearray(b"Id" + b"X" + bytes([24 + 0x4A]) + bytes(4) + struct.pack("<I", 2))
    for rid, t in ((2550001, b"UR1ABC Ivan"), (2550002, b"UR2ABC")):
        plain += struct.pack("<I", int(str(rid), 16)) + t.ljust(20, b"\x00")
    pp = db.parse_image(bytes(plain))
    check(pp.valid and pp.mode == "plain" and pp.id_len == 4 and pp.records == [(2550001, "UR1ABC Ivan"), (2550002, "UR2ABC")], "Z5: 4-байтний формат (BCD, ASCII) читається: %r %r" % (pp.records, pp.problems))
    check(not db.validate_for_write(pp), "Z5: такий образ (зі страхової копії) можна записати назад")


def sample_csv():
    rows = ["RADIO_ID,CALLSIGN,FIRST_NAME,LAST_NAME,CITY,STATE,COUNTRY"]
    rows += ["2550001,UR1AAA,Ivan,Petrenko,Kyiv,Kyivska,Ukraine", "2550002,UR2BBB,Олена,Коваль,Львів,Lvivska,Ukraine", "2550003,UR3CCC,Taras,Shevchenko,Kaniv,Cherkaska,Ukraine",
             "3100001,K1USA,John,Smith,Boston,MA,United States", "2600001,SP1PL,Jan,Kowalski,Warsaw,Mazowieckie,Poland", "2550001,UR1AAA,Dup,Dup,x,y,z",
             "abc,BAD,No,Id,x,y,z", "20000000,HUGE,Too,Large,x,y,z", "2559999,UR9ZZZ,,,Odesa,Odeska,Ukraine"]
    return "\n".join(rows) + "\n"


def test_sources_and_filters():
    src = db.parse_source(sample_csv().encode("utf-8"))
    check(len(src.rows) == 8 and src.skipped == 1 and not src.has_date, "D2/Z5: CSV (Radioid) розібрано: 8 рядків, 1 нерозпізнаний, дат нема")
    check(src.rows[1]["first"] == "Олена", "D2: кирилиця з UTF-8 збережена до транслітерації")
    rows, info = db.apply_filters(src.rows, ["255"], None, None, has_date=False)
    check([r["id"] for r in rows] == [2550001, 2550002, 2550003, 2559999] and info["region"] == 2 and info["dups"] == 1 and info["badId"] == 1,
          "D3.1/Z5: регіон 255: 4 записи; відкинуто іноземних 2, дублікат 1, ID завеликий 1: %r" % info)
    rows_all, info_all = db.apply_filters(src.rows, [], None, None, has_date=False)
    check(len(rows_all) == 6, "D3.1: без регіону -- усі коректні (6)")
    rows_l, info_l = db.apply_filters(src.rows, ["255"], None, 2, has_date=False)
    check([r["id"] for r in rows_l] == [2550001, 2550002] and info_l["limited"] == 2, "D3.1: ліміт 2 записи (без дат -- найменші ID)")
    rows_m, _ = db.apply_filters(src.rows, ["255", "310"], None, None, has_date=False)
    check(len(rows_m) == 5, "D3.1: кілька префіксів")
    # неактивність
    _r, i_un = db.apply_filters(src.rows, ["255"], 365, None, has_date=False)
    check(i_un["inactiveUnavailable"] and i_un["selected"] == 4 and i_un["inactive"] == 0, "D3.1: нема колонки дати -- фільтр бездіяльності НЕ застосовано й про це сказано")
    csv2 = "RADIO_ID,CALLSIGN,FIRST_NAME,LAST_HEARD\n2550001,UR1AAA,A,2026-10-01\n2550002,UR2BBB,B,2024-01-01\n2550003,UR3CCC,C,\n2550004,UR4DDD,D,2026-09-01\n"
    s2 = db.parse_source(csv2)
    check(s2.has_date and s2.rows[0]["date"] == datetime.date(2026, 10, 1), "D3.1: колонка дати розпізнана")
    today = datetime.date(2026, 10, 25)
    r2, i2 = db.apply_filters(s2.rows, [], 90, None, today=today, has_date=True)
    check([r["id"] for r in r2] == [2550001, 2550004] and i2["inactive"] == 2, "D3.1: активні за 90 днів: 2550001 і 2550004 (без дати й давні відкинуто)")
    r3, _ = db.apply_filters(s2.rows, [], None, 2, today=today, has_date=True)
    check(sorted(r["id"] for r in r3) == [2550001, 2550004], "D3.1: ліміт при наявних датах бере найсвіжіших")
    # JSON
    js = json.dumps({"users": [{"id": 2550001, "radio_id": 2550001, "callsign": "UR1AAA", "fname": "Ivan", "surname": "P", "city": "Kyiv", "country": "Ukraine"},
                               {"radio_id": 2550002, "callsign": "UR2BBB", "fname": "Olena"}, {"callsign": "noid"}]})
    sj = db.parse_source(js)
    check(len(sj.rows) == 2 and sj.skipped == 1 and sj.rows[0]["callsign"] == "UR1AAA", "D2: JSON (users[]) розібрано")
    for bad in ("", "foo,bar\n1,2\n", "{\"x\": 1}"):
        try:
            db.parse_source(bad)
            check(False, "D2: %r мав бути відхилений" % bad)
        except db.DbError:
            pass
    # cp1251 файл
    s3 = db.parse_source("RADIO_ID,CALLSIGN,FIRST_NAME\n2550001,UR1AAA,Богдан\n".encode("cp1251"))
    check(s3.rows[0]["first"] == "Богдан", "D2: файл у cp1251 розпізнано")
    # колонки й складання тексту
    check(db.compose(src.rows[0], ["callsign", "first"]) == "UR1AAA Ivan" and db.compose(src.rows[1], ["callsign", "first", "last"]) == "UR2BBB Olena Koval",
          "D3.2: колонки й порядок; кирилиця -> латиниця")
    check(db.compose(src.rows[0], ["first", "callsign"]) == "Ivan UR1AAA", "D3.2: порядок колонок змінюється")
    try:
        db.parse_columns("callsign,shoe")
        check(False, "D3.2: невідома колонка мала бути відхилена")
    except db.DbError:
        pass
    check(db.parse_prefixes("255, 310;260") == ["255", "310", "260"], "D3.1: префікси через кому/крапку з комою")
    try:
        db.parse_prefixes("25x")
        check(False, "D3.1: нецифровий префікс мав бути відхилений")
    except db.DbError:
        pass
    # лічильники до запису
    job = db.Job(src, ["255"], None, None, ["callsign", "first"], 16)
    s = job.summary()
    check(job.selected == 4 and job.fits and job.cap == 17475 and "після фільтрів 4, влізе 17475, буде записано 4" in s and "17475" in s, "D3.3: лічильники ДО запису: відібрано 4, вміщується 17475: %s" % s.replace("\n", " | "))
    check(job.preview()[0] == "2550001  UR1AAA Ivan", "D3.3: попередній перегляд показує те, що побачить рація")
    big = db.Source([{"id": i, "callsign": "UR", "first": "", "last": "", "city": "", "state": "", "country": "", "date": None} for i in range(1, 17480)], 0, False)
    jb = db.Job(big, [], None, None, ["callsign"], 16)
    check(not jb.fits and "НЕ ВМІЩУЄТЬСЯ" in jb.summary() and "ключів AES" in jb.summary(), "D3.3: не вміщується -- сказано до запису")
    try:
        jb.image()
        check(False, "D3.3: образ з переповненням мав бути відхилений")
    except db.DbError:
        pass
    jl = db.Job(big, [], None, 100, ["callsign"], 16)
    check(jl.fits and jl.selected == 100, "D3.1: ліміт записів повертає набір у межі місткості")
    # файли бази
    d = tempfile.mkdtemp(prefix="r31d_")
    image = job.image()
    pth = os.path.join(d, "db.bin")
    db.save_db_file(pth, image)
    check(db.load_db_file(pth) == image, "D5.2: зберегти -> завантажити дає той самий образ")
    pad = os.path.join(d, "padded.bin")
    open(pad, "wb").write(image + b"\xff" * 5000)
    check(db.load_db_file(pad) == image, "D5.2: файл із хвостом обрізається до заголовок+записи")
    junk = os.path.join(d, "junk.bin")
    open(junk, "wb").write(b"hello world, not a db")
    try:
        db.load_db_file(junk)
        check(False, "D5.2: сміття мало бути відхилене")
    except db.DbError:
        pass


# ----------------------------------------------------------------------------------------------------------------------
#  D4: запис бази на підробленому флеші
# ----------------------------------------------------------------------------------------------------------------------

def spi_with_db(image, marked=True):
    spi = spi_marked() if marked else tcr.spi_a()
    spi[db.AREA1_START:db.AREA1_START + db.AREA1_LEN] = b"\xff" * db.AREA1_LEN
    spi[db.AREA1_START:db.AREA1_START + len(image)] = image
    return spi


def make_records(n, seed=0):
    rnd = random.Random(seed)
    ids = sorted(rnd.sample(range(2550000, 2559999), n))
    return [(i, "UR%d %s" % (i % 1000, "Name%d" % (i % 97))) for i in ids]


def test_write_db():
    old_sleep = no_sleep()
    try:
        old_img = db.build_image(make_records(3000, 1))
        new_recs = make_records(5000, 2)
        new_img = db.build_image(new_recs)
        spi = spi_with_db(old_img)
        before = bytes(spi)
        radio = tcr.FakeRadioX(bytearray(spi))
        d = tempfile.mkdtemp(prefix="r31w_")
        confirm, asked = confirm_recorder(True)
        prog = []
        res = db.write_db(cl.CpsLink(radio), new_img, confirm, progress=lambda p, t: prog.append(p), log=quiet, safety_dir=d, rng=random.Random(3))
        after = bytes(radio.spi)
        check(res["written"] and res["verified"] is True and not res["cancelled"], "D4/Z5: база записана й звірена: %s" % res["text"].split("\n")[0])
        check(after[db.AREA1_START:db.AREA1_START + len(new_img)] == new_img, "D4: у рації образ == збудований байт-в-байт")
        span = (len(new_img) + 4095) // 4096 * 4096
        check(after[db.AREA1_START + len(new_img):db.AREA1_START + span] == before[db.AREA1_START + len(new_img):db.AREA1_START + span], "D4: хвіст останнього сектора лишився як був")
        old_span = (len(old_img) + 4095) // 4096 * 4096
        check(untouched_outside(before, after, db.AREA1_START, db.AREA1_START + span), "Z6/CG6: поза записаними секторами області №1 флеш не змінено (ключі, custom-data, кодплаг, підказки, калібрування)")
        check(bytes(after[akb.KEYS_START:akb.KEYS_START + akb.KEYS_LEN]) == bytes(before[akb.KEYS_START:akb.KEYS_START + akb.KEYS_LEN]), "CG6/Z6: таблиця ключів не змінилась")
        secs = sorted({s for k, s in radio.x_calls if k == 1})
        check(all(db.AREA1_START // 4096 <= s < (db.AREA1_START + db.AREA1_LEN) // 4096 for s in secs) and not radio.cal_touched, "Z6: усі X-сектори в області №1, калібрування недоторкане: %r" % secs[:3])
        commits = radio.commits
        check(commits[0] == db.AREA1_START // 4096 and commits[-1] == db.AREA1_START // 4096, "D4/Z5: перший і останній запис -- сектор 0 (обнулений заголовок на початку, справжній -- наприкінці)")
        check(len(commits) == len(set(commits[:-1])) + 1, "D4: кожен змінений сектор записано один раз (крім сектора заголовка)")
        sc = res["safetyCopy"]
        check(os.path.dirname(sc) == d and open(sc, "rb").read() == before[db.AREA1_START:db.AREA1_START + max(span, old_span)] and "dmrdb_pre-write" in sc, "D4.1: страхова копія області до запису")
        check(db.load_db_file(sc) == old_img, "D4.1/D5.2: страхову копію можна завантажити як базу -- це стара база")
        check(prog and prog[-1] == 100 and prog == sorted(prog), "D4.2: прогрес зростає до 100")
        check(radio.reset_requested, "D4: рація перезавантажується (інакше прошивка нову базу не побачить)")
        txt = asked[0]
        check("5000 записів по 15 Б" in txt and "3000 записів" in txt and "ключів AES" in txt and "Порядок" in txt, "D4.1: підтвердження описує нову й стару бази, порядок запису: %s" % txt.split("\n")[1:3])
        # повторний запис того самого -- нічого
        r2 = db.write_db(cl.CpsLink(radio), new_img, confirm, log=quiet, safety_dir=d)
        check(r2["nothingToDo"] and not r2["written"], "D4: така сама база -- записувати нічого")
        # скасування користувачем
        radio_c = tcr.FakeRadioX(bytearray(spi))
        n = [0]

        def cancel():
            n[0] += 1
            return n[0] > 3
        rc = db.write_db(cl.CpsLink(radio_c), new_img, confirm, log=quiet, safety_dir=d, cancel=cancel)
        hdr = db.parse_image(bytes(radio_c.spi[db.AREA1_START:db.AREA1_START + 12]), want_records=False)
        check(rc["cancelled"] and not rc["written"] and not hdr.rec_len, "D4.2: скасування -- заголовок обнулено (бази нема), а не база зі сміттям")
        check("ПЕРЕРВАНО" in rc["text"] and "обнулено" in rc["text"] and rc["safetyCopy"] in rc["text"] and radio_c.reset_requested, "D4.2: звіт про скасування словами, зі страховою копією")
        check(untouched_outside(before, bytes(radio_c.spi), db.AREA1_START, db.AREA1_START + span), "D4.2/Z6: при скасуванні поза областю №1 нічого не змінено")
        check(db.load_db_file(rc["safetyCopy"]) == old_img, "D4.2: страхова копія при скасуванні -- стара база")
        # збій рації посеред запису
        radio_f = tcr.FakeRadioX(bytearray(spi), die_after_x=12)
        rf = db.write_db(cl.CpsLink(radio_f), new_img, confirm, log=quiet, safety_dir=d)
        check(rf.get("failed") and not rf["written"] and "ПОМИЛКА" in rf["text"] and "обнулено" in rf["text"], "D4: збій рації -- звіт словами: %s" % rf["text"][:80])
        check(untouched_outside(before, bytes(radio_f.spi), db.AREA1_START, db.AREA1_START + span), "D4/Z6: при збої поза областю №1 нічого не змінено")
        # відмова в підтвердженні
        radio_n = tcr.FakeRadioX(bytearray(spi))
        rn = db.write_db(cl.CpsLink(radio_n), new_img, lambda *_: False, log=quiet, safety_dir=d)
        check(rn["cancelled"] and radio_n.x_total == 0 and bytes(radio_n.spi) == before, "D4: «Скасувати» у підтвердженні -- у рацію нічого")
        # звірка помічає псування
        # звірка читанням: справжня -- проходить, зіпсований заголовок або запис у рації -- ні
        ok_, why_ = db.verify(cl.CpsLink(radio), new_img, db.parse_image(new_img), random.Random(2))
        check(ok_ and "записів" in why_, "D4.3: звірка проходить на записаній базі (%s)" % why_)
        radio.spi[db.AREA1_START + 12 + 15 * 4999] ^= 0xFF                       # зіпсувати останній запис
        ok2, why2 = db.verify(cl.CpsLink(radio), new_img, db.parse_image(new_img), random.Random(2))
        check(not ok2 and "запис №4999" in why2, "D4.3: звірка ловить зіпсований останній запис: %s" % why2)
        radio.spi[db.AREA1_START + 12 + 15 * 4999] ^= 0xFF
        radio.spi[db.AREA1_START + 3] ^= 0xFF
        ok3, why3 = db.verify(cl.CpsLink(radio), new_img, db.parse_image(new_img), random.Random(2))
        check(not ok3 and "заголовок" in why3, "D4.3: звірка ловить зіпсований заголовок")
        radio.spi[db.AREA1_START + 3] ^= 0xFF
        # відмови до запису
        for what, bad in (("формат n", bytes(new_img[:2]) + b"n" + new_img[3:]), ("більше за область", new_img[:8] + struct.pack("<I", 99999) + new_img[12:]),
                          ("не база", b"\xff" * 64)):
            r_ = tcr.FakeRadioX(bytearray(spi))
            try:
                db.write_db(cl.CpsLink(r_), bad, confirm, log=quiet, safety_dir=d)
                check(False, "D4: %s мав бути відхилений" % what)
            except db.DbError:
                check(r_.x_total == 0 and bytes(r_.spi) == before, "D4: %s -- відмова, у рацію нічого" % what)
        # порожня рація (бази нема) і порожня база
        spi_e = spi_marked()
        spi_e[db.AREA1_START:db.AREA1_START + db.AREA1_LEN] = b"\xff" * db.AREA1_LEN
        re_ = tcr.FakeRadioX(bytearray(spi_e))
        rr = db.write_db(cl.CpsLink(re_), db.build_image([]), confirm, log=quiet, safety_dir=d)
        check(rr["written"] and re_.spi[db.AREA1_START:db.AREA1_START + 12] == db.build_image([]), "D4/Z5: порожня база в рацію без бази записується (лише заголовок)")
        re2 = tcr.FakeRadioX(bytearray(spi_e))
        r1 = db.write_db(cl.CpsLink(re2), db.build_image([(2550001, "Solo")]), confirm, log=quiet, safety_dir=d)
        check(r1["written"] and fw_lookup(bytes(re2.spi[db.AREA1_START:db.AREA1_START + 27]), 2550001) == "Solo", "D4/Z5: один запис записано, пошук знаходить")
        # максимальна база
        cap = db.capacity(15)
        fullimg = db.build_image([(i, "UR%d" % (i % 100)) for i in range(1, cap + 1)])
        rf2 = tcr.FakeRadioX(bytearray(spi))
        rfull = db.write_db(cl.CpsLink(rf2), fullimg, confirm, log=quiet, safety_dir=d)
        check(rfull["written"] and rfull["verified"] and bytes(rf2.spi[db.AREA1_START:db.AREA1_START + len(fullimg)]) == fullimg, "Z5: повна область (%d записів) записана" % cap)
        check(bytes(rf2.spi[db.AREA1_START + db.AREA1_LEN:]) == before[db.AREA1_START + db.AREA1_LEN:] and bytes(rf2.spi[:db.AREA1_START]) == before[:db.AREA1_START],
              "Z5/Z6: повна база не вийшла за область №1 (ні вперед до ключів, ні назад)")
        # стара база виходить в область №2 -- попередження, область №2 не чіпається
        big_old = bytearray(old_img)
        big_old[8:12] = struct.pack("<I", 20000)
        spi_o = spi_with_db(bytes(big_old))
        ro = tcr.FakeRadioX(bytearray(spi_o))
        c2, a2 = confirm_recorder(True)
        rro = db.write_db(cl.CpsLink(ro), new_img, c2, log=quiet, safety_dir=d)
        check(rro["written"] and "№2" in a2[0] and bytes(ro.spi[0xD8000:]) == bytes(spi_o[0xD8000:]), "D1.4/Z6: стара база більша за область №1 -- попередження; область №2 і ключі не чіпано")
    finally:
        time.sleep = old_sleep


# ----------------------------------------------------------------------------------------------------------------------
#  Z1: панелі (xvfb)
# ----------------------------------------------------------------------------------------------------------------------

def _spin(app, n=3):
    for _ in range(n):
        app.update()


def _wait_idle(app, limit=30.0):
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
    tmp = tempfile.mkdtemp(prefix="r31g_")
    spath = os.path.join(tmp, "ui.json")
    os.environ["TYT_CPS_SETTINGS"] = spath
    os.environ["HOME"] = tmp
    app = CpsApp(settings=Settings(spath), autoprobe=False)
    errors, infos, asks = [], [], []
    mb.showinfo = lambda *a, **k: infos.append(a)
    mb.showerror = lambda *a, **k: errors.append(a)
    mb.askyesno = lambda *a, **k: (asks.append(a), True)[1]
    confirms = []
    gd.confirm_dialog = lambda *a, **k: (confirms.append(a), True)[1]
    orig_open_radio = cl.open_radio
    try:
        app.geometry("1300x900")
        app.update()
        keys = [c.key for _g, _t, cls in SECTIONS for c in cls]
        check("dmrdb" in keys, "Z1: панель «База позивних» є в SECTIONS")
        for label, spi in (("без документа", None), ("порожній", tc.base.make_spi()), ("повний", tc.make_fixture_spi())):
            if spi is not None:
                _cp, data = tc.codeplug_of(spi)
                src = os.path.join(tmp, "%s.zip" % label.replace(" ", "_"))
                open(src, "wb").write(data)
                check(app.doc_open_file(src), "Z1: відкрито %s кодплаг" % label)
            app.show("dmrdb")
            _spin(app)
            dp = app.get_panel("dmrdb")
            check(type(dp).__name__ == "DmrDbPanel", "Z1 (%s): панель бази відкривається" % label)
            check(str(dp.write_btn.cget("state")) == "disabled" and str(dp.save_btn.cget("state")) == "disabled", "Z1 (%s): без рації запис і читання з рації вимкнені" % label)
            check(str(dp.open_btn.cget("state")) != "disabled" and str(dp.count_btn.cget("state")) != "disabled", "Z1 (%s): робота з файлом не потребує рації" % label)
            app.show("backup")
            _spin(app)
            bp = app.get_panel("backup")
            check(bp.keys_var.get() is True and bp.keys_restore_var.get() is False, "K2.3/K3.1/Z1 (%s): ключі в архів -- типово ТАК; відновлення ключів -- типово НІ" % label)
            check("міститиме ключі шифрування AES" in bp.keys_note.cget("text"), "K2.2: рядок про ключі в архіві: %s" % bp.keys_note.cget("text"))
            bp.keys_var.set(False)
            bp._update_keys_note()
            check("НЕ містить ключів AES і голосових підказок" in bp.keys_note.cget("text"), "K4.1/Z1: ключі вимкнено -- у вікні сказано, що архів їх не містить: %s" % bp.keys_note.cget("text"))
            bp.full_snapshot_var.set(True)
            bp._update_keys_note()
            check("НЕ міститиме ключів AES" in bp.keys_note.cget("text") and "голосові підказки" in bp.keys_note.cget("text"), "K4.1: повний знімок без ключів -- рядок відповідає")
            bp.full_snapshot_var.set(False)
            bp.keys_var.set(True)
            bp._update_keys_note()
            check(str(bp.keys_only_button.cget("state")) == "disabled", "Z1 (%s): без рації «Відновити лише ключі AES» вимкнено" % label)

        # ---------- бекап із панелі: з ключами / без ----------
        spi_a = put_table(tcr.spi_a(), make_table(1, OCC))
        radio = tcr.FakeRadioX(bytearray(spi_a))
        cl.open_radio = lambda *a, **k: radio
        bp = app.get_panel("backup")
        app.show("backup")
        bp._on_backup_clicked()
        _wait_idle(app)
        check(infos and "містить ключі шифрування AES" in infos[-1][1], "K2.2/Z1: після бекапу з ключами одним рядком сказано, що архів містить ключі: %r" % ((infos[-1] if infos else None),))
        zips = sorted(os.path.join(dp_, f) for dp_, _d, fs in os.walk(tmp) for f in fs if f.startswith("codeplug_backup") and f.endswith(".zip"))
        check(zips and akb.read_backup_keys(zips[-1]) == table_of(spi_a), "Z1: збережений архів має таблицю ключів")
        infos.clear()
        bp.keys_var.set(False)
        radio_n = tcr.FakeRadioX(bytearray(spi_a))
        cl.open_radio = lambda *a, **k: radio_n
        bp._on_backup_clicked()
        _wait_idle(app)
        check(infos and "НЕ містить ключів AES" in infos[-1][1], "K4.1/Z1: після бекапу без ключів сказано, що архів ключів не містить")
        zips2 = sorted(os.path.join(dp_, f) for dp_, _d, fs in os.walk(tmp) for f in fs if f.startswith("codeplug_backup") and f.endswith(".zip"))
        newest = [z for z in zips2 if z not in zips]
        check(newest and akb.read_backup_keys(newest[-1]) is None, "K2.3/Z1: архів без ключів: файла ключів нема")
        bp.keys_var.set(True)

        # ---------- відновлення ключів із панелі ----------
        bpath, _d, _m, _r = mk_zip(spi_a)
        tb = put_table(tcr.spi_b(tcr.spi_a()), make_table(1, {2}))
        radio_r = tcr.FakeRadioX(bytearray(tb))
        cl.open_radio = lambda *a, **k: radio_r
        fd.askopenfilename = lambda **k: bpath
        confirms.clear()
        bp._on_restore_keys_clicked()
        _wait_idle(app, 40.0)
        check(len(confirms) == 1 and "Слоти до запису: 5, 9." in confirms[0][2] or "Слоти до запису" in confirms[0][2], "K3.1/Z1: перед записом показано підтвердження зі слотами")
        check(all(akb.entry_of(table_of(radio_r.spi), s) == akb.entry_of(table_of(spi_a), s) for s in OCC), "K3/Z1: «Відновити лише ключі AES» відновила слоти")
        check(not errors, "Z1: без вікон помилок: %r" % errors)
        # «Відновити кодплаг» з прапорцем вимкненим: ключі не чіпаються й про це сказано
        radio_s = tcr.FakeRadioX(bytearray(tb))
        cl.open_radio = lambda *a, **k: radio_s
        infos.clear()
        bp.keys_restore_var.set(False)
        bp._on_restore_clicked()
        _wait_idle(app, 60.0)
        check(table_of(radio_s.spi) == table_of(tb) and any("НЕ відновлювались" in str(i) for i in infos), "K3.1/K4.2/Z1: прапорець вимкнено -- ключі не чіпано, про це сказано")
        radio_t = tcr.FakeRadioX(bytearray(tb))
        cl.open_radio = lambda *a, **k: radio_t
        bp.keys_restore_var.set(True)
        bp._on_restore_clicked()
        _wait_idle(app, 60.0)
        check(all(akb.entry_of(table_of(radio_t.spi), s) == akb.entry_of(table_of(spi_a), s) for s in OCC), "K3.1/Z1: прапорець увімкнено -- ключі відновлено разом з кодплагом")
        bp.keys_restore_var.set(False)

        # ---------- панель бази: файл -> відбір -> запис ----------
        csvp = os.path.join(tmp, "users.csv")
        open(csvp, "w", encoding="utf-8").write(sample_csv())
        app.show("dmrdb")
        dp = app.get_panel("dmrdb")
        fd.askopenfilename = lambda **k: csvp
        dp._on_open_source()
        _wait_idle(app)
        check(dp.source is not None and "рядків з ID: 8" in dp.src_label.cget("text"), "D2.2/Z1: локальний файл відкрито: %s" % dp.src_label.cget("text"))
        dp._on_count()
        while dp.table_filling:
            app.update()
        tv = [dp.tree.item(i, "values") for i in dp.tree.get_children()]
        check("після фільтрів 4" in dp.summary.cget("text") and "17475" in dp.summary.cget("text") and any("UR1AAA Ivan" in str(v[2]) for v in tv),
              "D3.3/Z1 (R33: список у таблиці): лічильники й перегляд до запису: %s" % dp.summary.cget("text").replace("\n", " | "))
        dp.limit_var.set("x")
        n_err = len(errors)
        dp._on_count()
        check(len(errors) == n_err + 1, "Z1: хибний ліміт -- відмова словами")
        dp.limit_var.set("")
        spi_db = spi_with_db(db.build_image(make_records(100, 3)))
        radio_db = tcr.FakeRadioX(bytearray(spi_db))
        cl.open_radio = lambda *a, **k: radio_db
        before = bytes(spi_db)
        confirms.clear()
        infos.clear()
        dp._on_count()
        dp._on_write()
        _wait_idle(app, 60.0)
        written = bytes(radio_db.spi[db.AREA1_START:db.AREA1_START + 12 + 4 * 15])
        check(len(confirms) == 1 and written == db.build_image([(r["id"], db.compose(r, ["callsign", "first"])) for r in dp.job.rows]), "D4/Z1: підтвердження показано; у рації записано відфільтровану базу")
        check(untouched_outside(before, bytes(radio_db.spi), db.AREA1_START, db.AREA1_START + 0x1000 * 2), "Z6/Z1: через панель поза областю №1 нічого не змінено")
        check(infos and "База записана" in infos[-1][1], "D4/Z1: підсумок записано в діалозі")
        # зберегти з рації -> завантажити з файлу
        out = os.path.join(tmp, "radio_db.bin")
        fd.asksaveasfilename = lambda **k: out
        dp._on_save_db()
        _wait_idle(app)
        check(os.path.exists(out) and db.load_db_file(out)[:12] == written[:12], "D5.2/Z1: «Зберегти базу з рації» записала образ")
        fd.askopenfilename = lambda **k: out
        dp._on_load_db()
        check(dp.image is not None and "Готовий образ" in dp.summary.cget("text"), "D5.2/Z1: «Завантажити з файлу» дає готовий образ: %s" % dp.summary.cget("text").split("\n")[0])
        dp._on_what()
        _wait_idle(app)
        check("формату N" in dp.what_label.cget("text") and "4 по 15" in dp.what_label.cget("text").replace("записів ", ""), "Z1: «Що зараз у рації»: %s" % dp.what_label.cget("text"))
        # сміття у файлі
        junk = os.path.join(tmp, "junk.bin")
        open(junk, "wb").write(b"not a database")
        fd.askopenfilename = lambda **k: junk
        n_err = len(errors)
        dp._on_load_db()
        check(len(errors) == n_err + 1 and dp.image is not None, "Z1: файл-сміття -- відмова словами, попередній образ не втрачено")
        check(not any("Traceback" in str(e) for e in errors), "Z1: без внутрішніх помилок")
    finally:
        cl.open_radio = orig_open_radio
        time.sleep = old_sleep
        app.destroy()


def main():
    import faulthandler
    faulthandler.dump_traceback_later(500, exit=True)
    for t in (test_constants_match_firmware, test_backup_keys, test_restore_keys_roundtrip, test_slot0_ignored, test_old_zip_without_keys, test_failure_on_third_slot,
              test_guard_bounds, test_text_format, test_build_image, test_sources_and_filters, test_write_db, test_gui):
        try:
            t()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILS.append("%s: виняток %r" % (t.__name__, e))
    if FAILS:
        print("test_r31: ПРОВАЛЕНО перевірок: %d" % len(FAILS))
        return 1
    print("test_r31: усе гаразд (ключі AES у бекапі й відновленні, збій на слоті, межі запису, формат і запис бази позивних, панелі).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
