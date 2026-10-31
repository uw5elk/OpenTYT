#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R41: видалення каналу з меню рації -- сторона інструментів (tools/) і мутації прошивкової логіки.

Z5  кодплаг з ДІРОЮ в нумерації каналів (канал видалено так, як це робить прошивка: біт маски знято, запис 0xFF, номер прибрано з усіх зон):
    переглядач, таблиці, експорт у CSV, імпорт без правок (байт-у-байт), новий канал без номера займає найменший вільний номер.
Z5b розкладка адрес у C-тесті (tests/test_codeplug_chandel.c) збігається з тим, що знають інструменти (cps_link) -- обидві сторони читають один формат;
Z6  мутації: у копії codeplug.c / codeplug_chandel.h ламається одне місце -- хост-тест прошивки (tests/test_codeplug_chandel.c) МАЄ провалитись;
Z7  (за бажанням, змінна R41_BASE=<каталог application старої версії>) типова збірка (без ENABLE_CHANNEL_DELETE) після препроцесора ідентична старій.
Запуск: `python3 tools/test_r41.py` (без рації, без ARM-тулчейну; потрібен лише gcc)."""
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.abspath(os.path.join(HERE, ".."))
APP = os.path.join(FW, "application")
sys.path.insert(0, HERE)

import cps_csv as cc                     # noqa: E402
import cps_link as cl                    # noqa: E402
import codeplug_view as cv               # noqa: E402
import test_cps_csv as tc                # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)
    else:
        print("  ok  ", msg)


# ------------------------------------------------------------------------------------------ Z5
def fw_delete(img, number):
    """Те саме, що робить codeplugChannelDelete(): з усіх зон (щільний список, хвіст зсувається), потім маска, потім запис -> 0xFF."""
    st = img.zone_stride()
    for bit in range(cl.CP_ZONES_MAX):
        mask = img.ee(cl.CP_ADDR_EX_ZONE_INUSE, 32)
        if not (mask[bit >> 3] >> (bit & 7)) & 1:
            continue
        rec = bytearray(img.ee(cl.CP_ADDR_EX_ZONE_LIST + bit * st, st))
        vals = []
        for k in range((st - 16) // 2):
            v = rec[16 + 2 * k] | (rec[17 + 2 * k] << 8)
            if v == 0:
                break
            vals.append(v)
        kept = [v for v in vals if v != number]
        if kept != vals:
            rec[16:st] = b"".join(struct.pack("<H", v) for v in kept).ljust(st - 16, b"\x00")
            img.set_zone(bit, bytes(rec))
    img.set_channel_in_use(number, False)
    img.set_channel_rec(number, b"\xff" * 56)


def spi_with_deleted(numbers):
    spi = tc.make_fixture_spi()
    rng = cl.flash_backup_range()
    cp_ee = bytearray(spi[:cl.EEPROM_BACKUP_LEN])
    fl = bytearray(spi[rng["raw_start"]:rng["raw_start"] + rng["length"]])
    img = cc.Image(cp_ee, fl, rng["codeplug_start"])
    for n in numbers:
        fw_delete(img, n)
    spi[:cl.EEPROM_BACKUP_LEN] = img.eeprom
    spi[rng["raw_start"]:rng["raw_start"] + rng["length"]] = img.flash
    return spi


def test_tools_with_hole():
    # фікстура test_cps_csv: канали 1,2,3 (EEPROM), 130 (флеш) і службові 385,386; зони: біт0 {1,3}, біт1 {2}, біт5 {1,2,3,130}.
    # Видаляємо 3 -- дірка МІЖ номерами (EEPROM-банк), жодна зона не спорожніла.
    spi = spi_with_deleted([3])
    cp, _ = tc.codeplug_of(spi)
    nums = [c[0] for c in cp.channels()]
    check(nums == [1, 2, 130, 385, 386], "переглядач: канали 1,2,130,385,386 (дірка на 3), номери не зсунулись (є %r)" % nums)
    check(cp.channel_count() == 5, "переглядач: channel_count = 5 (є %d)" % cp.channel_count())
    check(not cp.channel_in_use(3) and cp.channel_in_use(2), "маска: 3 вимкнено, 2 живий")
    zones = {z[0]: z[3] for z in cp.zones()}
    check(zones.get(1) == [1] and zones.get(2) == [2] and zones.get(6) == [1, 2, 130],
          "зони (№ = біт+1): {1}, {2}, {1,2,130} -- 3 прибрано скрізь, списки щільні (є %r)" % zones)
    _cols, zrows = cp.table_zones()
    check(not any("порожній" in r[3] for r in zrows), "таблиця зон: жодного «(порожній)» -- посилань на видалений канал нема")

    # CSV: експорт -> імпорт без правок == байт-у-байт
    with tempfile.TemporaryDirectory() as d:
        tc.export_dir(cp, d)
        rows = tc.read_csv_rows(os.path.join(d, "Channels.csv"))
        check([r[0] for r in rows[1:]] == ["1", "2", "130", "385", "386"], "Channels.csv: номери 1,2,130,385,386 (3 немає)")
        res = tc.import_dir(cp, d)
        check(tc.images_equal(res, cp), "Z5: експорт -> імпорт кодплага з дірою без правок == вихідний БАЙТ-У-БАЙТ")
        check(not res.any_change() and not res.warnings, "Z5: жодної зміни й жодного попередження: %s %r" % (res.summary(), res.warnings))

    # новий канал без номера отримує НАЙМЕНШИЙ вільний номер -- 3 (дірка), решта не рухається
    with tempfile.TemporaryDirectory() as d:
        tc.export_dir(cp, d)
        pc = os.path.join(d, "Channels.csv")
        rows = tc.read_csv_rows(pc)
        h = {c: i for i, c in enumerate(rows[0])}
        new = [""] * len(rows[0])
        new[h[cc.READABLE]] = "Новий"
        new[h["Channel Type"]] = "Analogue"
        new[h["Rx Frequency"]] = "\t145,5"
        new[h["Tx Frequency"]] = "\t145,5"
        new[h["Bandwidth (kHz)"]] = "12,5"
        rows.append(new)
        tc.write_csv_rows(pc, rows)
        res = tc.import_dir(cp, d)
        img = res.image
        check(img.channel_in_use(3), "новий канал без номера зайняв номер 3 (найменший вільний, тобто дірка)")
        check(all(img.channel_rec(n) == cp.channel_record(n) for n in (1, 2, 130, 385, 386)), "номери 1,2,130,385,386 не змінились байт-у-байт")

    # дірка на ПЕРШОМУ номері (видалили канал 1): все працює
    cp1, _ = tc.codeplug_of(spi_with_deleted([1]))
    check([c[0] for c in cp1.channels()][:3] == [2, 3, 130], "дірка на першому номері: 2,3,130,...")
    with tempfile.TemporaryDirectory() as d:
        tc.export_dir(cp1, d)
        res = tc.import_dir(cp1, d)
        check(tc.images_equal(res, cp1), "Z5: дірка на першому номері -- коло CSV байт-у-байт")

    # ЗОНА СПОРОЖНІЛА (видалили 2 -- єдиний канал зони біт1): переглядач не падає; CSV-коло не відхиляє імпорт, а чесно попереджає і прибирає порожню зону
    cp2z, _ = tc.codeplug_of(spi_with_deleted([2]))
    zz = {z[0]: z[3] for z in cp2z.zones()}
    check(zz.get(2) == [], "спорожніла зона лишається в кодплазі порожньою (біт зони не знімається, номери зон не зсуваються): %r" % zz)
    with tempfile.TemporaryDirectory() as d:
        tc.export_dir(cp2z, d)
        res = tc.import_dir(cp2z, d)
        check(any("порожня" in w for w in res.warnings), "CSV-коло: порожню зону названо в попередженні: %r" % res.warnings)
        others_same = all(res.image.channel_rec(n) == cp2z.channel_record(n) for n in (1, 3, 130))
        check(others_same, "CSV-коло: решта каналів не змінилась")

    # дірка у флеш-банку (видалили 130)
    cp3, _ = tc.codeplug_of(spi_with_deleted([130]))
    check([c[0] for c in cp3.channels()][:3] == [1, 2, 3], "після видалення 130 лишилось 1,2,3,...")


def test_layout_matches_tools():
    src = open(os.path.join(FW, "tests", "test_codeplug_chandel.c"), encoding="utf-8").read()

    def c(name):
        return int(re.search(r"#define %s\s+(0x[0-9A-Fa-f]+|\d+)" % name, src).group(1), 0)
    pairs = [("ADDR_HDR_EEP", cl.CP_ADDR_CHANNEL_HEADER_EEPROM), ("ADDR_HDR_FLASH", cl.CP_ADDR_CHANNEL_HEADER_FLASH),
             ("ADDR_ZONES", cl.CP_ADDR_EX_ZONE_LIST), ("ADDR_ZONEMASK", cl.CP_ADDR_EX_ZONE_INUSE)]
    for name, val in pairs:
        check(c(name) == val, "розкладка: %s у C-тесті = %#x = cps_link (%#x)" % (name, c(name), val))
    check(c("ADDR_CH_EEP") == cl.CP_ADDR_CHANNEL_HEADER_EEPROM + 16, "розкладка: записи каналів EEPROM = заголовок + 16")
    check(c("ADDR_CH_FLASH") == cl.CP_ADDR_CHANNEL_HEADER_FLASH + 16, "розкладка: записи каналів флешу = заголовок + 16")
    check(c("REC") == cl.CP_CHANNEL_SIZE and "#define ZONE_STRIDE (16 + 2 * 80)" in src, "розкладка: розмір запису каналу й крок зони")


# ------------------------------------------------------------------------------------------ Z6
FW_INCS = ["-I%s/tools/hoststub" % FW, "-include", "%s/tools/hoststub/host_compat.h" % FW, "-I%s" % FW, "-I%s/Core/Inc" % FW,
           "-I%s/Drivers/CMSIS/Device/ST/STM32F4xx/Include" % FW, "-I%s/Drivers/CMSIS/Include" % FW,
           "-I%s/Drivers/STM32F4xx_HAL_Driver/Inc" % FW, "-I%s/Drivers/STM32F4xx_HAL_Driver/Inc/Legacy" % FW,
           "-I%s/Middlewares/ST/STM32_USB_Device_Library/Class/CDC/Inc" % FW, "-I%s/Middlewares/ST/STM32_USB_Device_Library/Core/Inc" % FW,
           "-I%s/Middlewares/Third_Party/FreeRTOS/Source/CMSIS_RTOS_V2" % FW, "-I%s/Middlewares/Third_Party/FreeRTOS/Source/include" % FW,
           "-I%s/Middlewares/Third_Party/FreeRTOS/Source/portable/GCC/ARM_CM4F" % FW, "-I%s/USB_DEVICE/App" % FW, "-I%s/USB_DEVICE/Target" % FW]
CFLAGS = ["-O1", "-w", "-std=gnu11", "-DENABLE_AES", "-DENABLE_DMR_DATA", "-DENABLE_CALL_REPLAY", "-DUSE_HAL_DRIVER", "-DSTM32F405xx",
          "-DPLATFORM_MDUV380", "-DPLATFORM_VARIANT_UV380_PLUS_10W", "-DNDEBUG", "-DLANGUAGE_BUILD_UKRAINIAN", "-DENABLE_CHANNEL_DELETE"]

# (назва, файл, що замінити, чим) -- кожен «що» зустрічається РІВНО раз. Тест прошивки має ПРОВАЛИТИСЬ.
MUTANTS = [
    ("зони не чіпаємо (каскад вимкнено)", "codeplug.c",
     "if (codeplugZoneListCount(z.channels, num, (uint16_t)channelIndex) == 0)", "if (codeplugZoneListCount(z.channels, num, (uint16_t)channelIndex) >= 0)"),
    ("біт у кеші маски не знімається", "codeplug.c",
     "	codeplugChanMaskClear(codeplugAllChannelsCache, channelIndex);\n	codeplugAllChannelsRecount();", "	codeplugAllChannelsRecount();"),
    ("байт маски в EEPROM не пишеться", "codeplug.c",
     "EEPROM_Write(addr, &maskByte, 1)", "true"),
    ("запис каналу в EEPROM не стирається", "codeplug.c",
     "		EEPROM_Write(addr, blank, sizeof(blank));", "		(void)blank;"),
    ("запис каналу у флеші не стирається", "codeplug.c",
     "		SPI_Flash_write(FLASH_ADDRESS_OFFSET + addr, blank, sizeof(blank));", "		(void)blank;"),
    ("лічильники «Всіх каналів» не перераховуються", "codeplug.c",
     "	codeplugChanMaskClear(codeplugAllChannelsCache, channelIndex);\n	codeplugAllChannelsRecount();", "	codeplugChanMaskClear(codeplugAllChannelsCache, channelIndex);"),
    ("LUCZ «Всіх каналів» не виправляється", "codeplug.c",
     "if (codeplugGetLastUsedChannelInZone(-1) == channelIndex)", "if (0)"),
    ("єдиний канал можна видалити", "codeplug.c",
     "if (codeplugChanMaskCount(codeplugAllChannelsCache) <= 1)", "if (codeplugChanMaskCount(codeplugAllChannelsCache) <= 0)"),
    ("збій запису зони ігнорується", "codeplug.c",
     "(uint8_t *)&z, ((codeplugChannelsPerZone == 16) ? CODEPLUG_ZONE_DATA_ORIGINAL_STRUCT_SIZE : CODEPLUG_ZONE_DATA_OPENGD77_STRUCT_SIZE)))\n		{\n			return CODEPLUG_CHANNEL_DELETE_WRITE_ERROR;",
     "(uint8_t *)&z, ((codeplugChannelsPerZone == 16) ? CODEPLUG_ZONE_DATA_ORIGINAL_STRUCT_SIZE : CODEPLUG_ZONE_DATA_OPENGD77_STRUCT_SIZE)))\n		{\n			(void)0;"),
    ("зона з двома входженнями рахується двічі", "codeplug.c",
     "			n++;\n		}\n	}\n\n	return n;", "			n += codeplugZoneListCount(z.channels, z.NOT_IN_CODEPLUGDATA_numChannelsInZone, (uint16_t)channelIndex);\n		}\n	}\n\n	return n;"),
    ("крок банків флешу без 16-байтової маски", "codeplug_chandel.h",
     "(CODEPLUG_CHDEL_CHANNELS_PER_BANK * CODEPLUG_CHDEL_CHANNEL_SIZE + CODEPLUG_CHDEL_BANK_HEADER_SIZE)", "(CODEPLUG_CHDEL_CHANNELS_PER_BANK * CODEPLUG_CHDEL_CHANNEL_SIZE)"),
    ("записи флешу без проміжків-масок", "codeplug_chandel.h",
     "(CODEPLUG_CHDEL_BANK_HEADER_SIZE * (index / CODEPLUG_CHDEL_CHANNELS_PER_BANK)) + ", "0 + "),
    ("список зони не ущільнюється", "codeplug_chandel.h",
     "		if (list[r] != channel)\n		{\n			list[w++] = list[r];\n		}", "		list[w++] = (list[r] != channel) ? list[r] : 0;"),
    ("позиція в зоні не коригується", "codeplug_chandel.h",
     "	return (kept >= newCount) ? 0 : kept;", "	return oldIdx;"),
    ("після останнього в зоні -- не перший", "codeplug_chandel.h",
     "	return (kept >= newCount) ? 0 : kept;", "	return (kept >= newCount) ? (newCount - 1) : kept;"),
    ("межі номера каналу розсунуто", "codeplug_chandel.h",
     "	if ((index < CODEPLUG_CHDEL_CHANNELS_MIN) || (index > CODEPLUG_CHDEL_CHANNELS_MAX))\n	{\n		return -1;\n	}\n	index--;\n	if (index < CODEPLUG_CHDEL_CHANNELS_PER_BANK)",
     "	if ((index < CODEPLUG_CHDEL_CHANNELS_MIN) || (index > CODEPLUG_CHDEL_CHANNELS_MAX))\n	{\n		return -1;\n	}\n	index--;\n	if (index <= CODEPLUG_CHDEL_CHANNELS_PER_BANK)"),
]


def build_and_run(tmp, files):
    """files: {ім'я: текст} -- підмінені копії; решта береться з application/. Повертає (зібралось, код виходу, вивід)."""
    inc = os.path.join(tmp, "include", "functions")
    os.makedirs(inc, exist_ok=True)
    src_c = os.path.join(tmp, "codeplug.c")
    shutil.copyfile(os.path.join(APP, "source", "functions", "codeplug.c"), src_c)
    shutil.copyfile(os.path.join(APP, "include", "functions", "codeplug_chandel.h"), os.path.join(inc, "codeplug_chandel.h"))
    for name, text in files.items():
        path = src_c if name.endswith(".c") else os.path.join(inc, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    exe = os.path.join(tmp, "t")
    cmd = ["gcc"] + CFLAGS + ["-I%s/include" % tmp, "-I%s/include" % APP, "-I%s/include/crypto" % APP] + FW_INCS + \
          ["-I%s/include" % APP, "-o", exe, os.path.join(FW, "tests", "test_codeplug_chandel.c"), src_c]
    cp = subprocess.run(cmd, capture_output=True, text=True)
    if cp.returncode != 0:
        return False, -1, cp.stderr[-600:]
    r = subprocess.run([exe], capture_output=True, text=True, timeout=120)
    return True, r.returncode, r.stdout[-400:]


def test_mutants():
    texts = {"codeplug.c": open(os.path.join(APP, "source", "functions", "codeplug.c"), encoding="utf-8").read(),
             "codeplug_chandel.h": open(os.path.join(APP, "include", "functions", "codeplug_chandel.h"), encoding="utf-8").read()}
    with tempfile.TemporaryDirectory() as t0:
        built, rc, out = build_and_run(t0, {})
        check(built and rc == 0, "Z6: немутований код -- тест прошивки зелений (собрано=%s, код=%s)" % (built, rc))
    for title, fname, old, new in MUTANTS:
        src = texts[fname]
        if src.count(old) != 1:
            check(False, "Z6: мутант «%s»: шаблон знайдено %d раз(ів), треба рівно 1 (код змінився -- онови мутант)" % (title, src.count(old)))
            continue
        with tempfile.TemporaryDirectory() as t:
            built, rc, out = build_and_run(t, {fname: src.replace(old, new)})
            check(built and rc != 0, "Z6: мутант «%s» -- тест прошивки ловить (зібралось=%s, код=%s)" % (title, built, rc))


# ------------------------------------------------------------------------------------------ Z7
def test_default_identity():
    """Типова збірка без ENABLE_CHANNEL_DELETE: препроцесор дає той самий текст, що й стара версія (R41_BASE=<стара application>)."""
    base = os.environ.get("R41_BASE")
    if not base:
        print("  --   Z7 пропущено: задай R41_BASE=<каталог application старої версії> (git archive <база> MDUV380_firmware/application)")
        return
    files = ["source/functions/codeplug.c", "source/user_interface/uiChannelMode.c", "source/user_interface/uiLocalisation.c",
             "source/user_interface/menuSystem.c", "source/user_interface/menuChannelDetails.c", "source/user_interface/uiVFOMode.c"]   # + через них усі змінені заголовки
    configs = {"AES0": [], "UA": ["-DENABLE_AES", "-DENABLE_DMR_DATA", "-DLANGUAGE_BUILD_UKRAINIAN", "-DENABLE_CALL_REPLAY", "-DENABLE_APRS_RX"],
               "EN": ["-DENABLE_AES", "-DENABLE_DMR_DATA", "-DENABLE_CALL_REPLAY"]}
    common = ["-DUSE_HAL_DRIVER", "-DSTM32F405xx", "-DPLATFORM_MDUV380", "-DPLATFORM_VARIANT_UV380_PLUS_10W", "-DNDEBUG", "-DGITVERSION=x"]

    def pp(appdir, rel, extra):
        inc = ["-I%s/include" % appdir]
        fw_incs = [x.replace(FW + "/application/include", appdir + "/include") for x in FW_INCS]
        cmd = ["gcc", "-E", "-P", "-x", "c", "-std=gnu11"] + common + extra + inc + fw_incs + ["-I%s/include" % appdir, os.path.join(appdir, rel)]
        r = subprocess.run(cmd, capture_output=True)       # байти: мовні таблиці в cp1251
        # порівнюємо потік токенів: розриви рядків і пробіли (їх додає багаторядкова умова з #if) на код не впливають
        txt = re.sub(rb"\s+", b"", r.stdout)
        return r.returncode, txt
    for cname, extra in configs.items():
        for rel in files:
            if rel.endswith(".h"):
                continue            # заголовки перевіряються через .c, що їх включають
            rc1, a = pp(base, rel, extra)
            rc2, b = pp(APP, rel, extra)
            check(rc1 == 0 and rc2 == 0 and a == b, "Z7 [%s] %s: після препроцесора без ENABLE_CHANNEL_DELETE == стара версія (%d / %d символів)" %
                  (cname, rel, len(a), len(b)))


def main():
    test_tools_with_hole()
    test_layout_matches_tools()
    test_mutants()
    test_default_identity()
    if FAILS:
        print("\nПРОВАЛІВ: %d" % len(FAILS))
        sys.exit(1)
    print("test_r41: усе гаразд")


if __name__ == "__main__":
    main()
