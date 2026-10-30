#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R42: затримка відкриття шумодава, перейменування зони, дрібні правки -- сторона інструментів і мутації прошивкової логіки.

Z3  мутації: у копії sql_open_delay.h / codeplug.c ламається одне місце -- хост-тест (tests/test_sql_open_delay.c, tests/test_codeplug_zonerename.c) МАЄ провалитись;
    для trx.c (на хості не збирається) -- структурна перевірка, що затримка стоїть саме в умові відкриття динаміка й скидається при зникненні сигналу, + її мутації;
Z4  інструменти: кодплаг зі зоною, перейменованою ТАК, як це пише прошивка (зокрема кінцева «я» з хвостом 0x00), читається переглядачем, CSV-коло байт-у-байт;
Z5  tools/mem_report.py друкує флеш (зайнято/вільно/%), розрахунок збігається з розміром .bin на зразку, а ELF-вихід розбирається;
Z5b TS у шапці (C4): різниця рендера з іншим TS = 0 завдяки виключеній ділянці; без неї -- ненульова (мутація);
Z7  (за бажанням, змінна R42_BASE=<каталог application попередньої версії>) типова збірка (без ENABLE_SQL_OPEN_DELAY/ENABLE_ZONE_RENAME) після препроцесора ідентична старій.
Запуск: `python3 tools/test_r42.py` (без рації, без ARM-тулчейну; потрібен лише gcc)."""
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
import selfcheck as sc                   # noqa: E402
import mem_report as mr                  # noqa: E402
import test_cps_csv as tc                # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)
    else:
        print("  ok  ", msg)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


FW_INCS = ["-I%s/tools/hoststub" % FW, "-include", "%s/tools/hoststub/host_compat.h" % FW, "-I%s" % FW, "-I%s/Core/Inc" % FW,
           "-I%s/Drivers/CMSIS/Device/ST/STM32F4xx/Include" % FW, "-I%s/Drivers/CMSIS/Include" % FW,
           "-I%s/Drivers/STM32F4xx_HAL_Driver/Inc" % FW, "-I%s/Drivers/STM32F4xx_HAL_Driver/Inc/Legacy" % FW,
           "-I%s/Middlewares/ST/STM32_USB_Device_Library/Class/CDC/Inc" % FW, "-I%s/Middlewares/ST/STM32_USB_Device_Library/Core/Inc" % FW,
           "-I%s/Middlewares/Third_Party/FreeRTOS/Source/CMSIS_RTOS_V2" % FW, "-I%s/Middlewares/Third_Party/FreeRTOS/Source/include" % FW,
           "-I%s/Middlewares/Third_Party/FreeRTOS/Source/portable/GCC/ARM_CM4F" % FW, "-I%s/USB_DEVICE/App" % FW, "-I%s/USB_DEVICE/Target" % FW]
ZONE_CFLAGS = ["-O1", "-w", "-std=gnu11", "-DUSE_HAL_DRIVER", "-DSTM32F405xx", "-DPLATFORM_MDUV380", "-DPLATFORM_VARIANT_UV380_PLUS_10W", "-DNDEBUG",
               "-DLANGUAGE_BUILD_UKRAINIAN", "-DENABLE_AES", "-DENABLE_APRS_RX", "-DENABLE_ZONE_RENAME"]


# ------------------------------------------------------------------------------------------ Z3: затримка
def run_delay(tmp, header_text):
    inc = os.path.join(tmp, "include", "functions")
    os.makedirs(inc, exist_ok=True)
    with open(os.path.join(inc, "sql_open_delay.h"), "w", encoding="utf-8") as f:
        f.write(header_text)
    exe = os.path.join(tmp, "t")
    cp = subprocess.run(["gcc", "-O1", "-w", "-I%s/include" % tmp, "-o", exe, os.path.join(FW, "tests", "test_sql_open_delay.c")], capture_output=True, text=True)
    if cp.returncode != 0:
        return False, -1
    return True, subprocess.run([exe], capture_output=True, text=True, timeout=60).returncode


DELAY_MUTANTS = [
    ("сигнал зник -- мітку НЕ скидаємо (стара мітка робить наступну появу миттєвою)",
     "	if (!signalPresent)\n	{\n		*since = 0;\n		return false;\n	}", "	if (!signalPresent)\n	{\n		return false;\n	}"),
    ("сигнал зник, а перевірка каже «можна» (динамік відкрився б без сигналу)",
     "	if (!signalPresent)\n	{\n		*since = 0;\n		return false;\n	}", "	if (!signalPresent)\n	{\n		*since = 0;\n		return true;\n	}"),
    ("межа діапазону: 500 мс відкидається", "> SQL_OPEN_DELAY_STEPS_MAX))", ">= SQL_OPEN_DELAY_STEPS_MAX))"),
    ("межа діапазону: 550 мс дозволено", "	return (steps >= SQL_OPEN_DELAY_STEPS_MAX) ? (uint8_t)SQL_OPEN_DELAY_STEPS_MAX : (uint8_t)(steps + 1U);",
     "	return (steps > SQL_OPEN_DELAY_STEPS_MAX) ? (uint8_t)SQL_OPEN_DELAY_STEPS_MAX : (uint8_t)(steps + 1U);"),
    ("збережене слово без мітки приймається", "if (((w >> 8) != SQL_OPEN_DELAY_TAG) || ", "if ("),
    ("рівно затримка ще «рано» (> замість >=)", "return ((uint32_t)(now - *since) >= delayMs);", "return ((uint32_t)(now - *since) > delayMs);"),
    ("затримка 0 -- теж чекаємо", "	if (delayMs == 0U)\n	{\n		*since = 0;\n		return true;\n	}\n", ""),
    ("різниця часу не за модулем 2^32 (перехід годинника)", "return ((uint32_t)(now - *since) >= delayMs);", "return (now >= *since) && ((now - *since) >= delayMs);"),
    ("годинник рівно 0 лишає мітку «непозначеною»", "*since = (now != 0U) ? now : 0xFFFFFFFFU;", "*since = now;"),
    ("Dec йде нижче нуля", "	return (steps == 0U) ? 0U : (uint8_t)(steps - 1U);", "	return (uint8_t)(steps - 1U);"),
]


def test_delay_mutants():
    src = read(os.path.join(APP, "include", "functions", "sql_open_delay.h"))
    with tempfile.TemporaryDirectory() as t0:
        built, rc = run_delay(t0, src)
        check(built and rc == 0, "Z3: немутована логіка затримки -- тест зелений (зібрано=%s, код=%s)" % (built, rc))
    for title, old, new in DELAY_MUTANTS:
        if src.count(old) != 1:
            check(False, "Z3: мутант «%s»: шаблон знайдено %d раз(ів), треба рівно 1" % (title, src.count(old)))
            continue
        with tempfile.TemporaryDirectory() as t:
            built, rc = run_delay(t, src.replace(old, new))
            check(built and rc != 0, "Z3: мутант затримки «%s» -- тест ловить (зібрано=%s, код=%s)" % (title, built, rc))


# ------------------------------------------------------------------------------------------ Z3: trx.c (структура)
def trx_structure_ok(text):
    """Затримка стоїть в умові відкриття динаміка, скидається при закритті шумодава, у передачі, при завершенні, після відкриття; під сканом -- 0."""
    problems = []
    m = re.search(r"if \(currentRadioDevice->analogTriggeredAudio[^\n]*\n#if defined\(SQL_OPEN_DELAY_ENABLED\)\n\s*&& trxSqlOpenDelayReady\(\)[^\n]*\n#endif\n\s*\)\n\s*\{\n\s*taskENTER_CRITICAL\(\);", text)
    if not m:
        problems.append("умова відкриття динаміка без trxSqlOpenDelayReady()")
    if text.count("trxSqlOpenDelayReset();") < 4:
        problems.append("скидання мітки є не у всіх 4 місцях (закриття, передача, завершення, після відкриття): %d" % text.count("trxSqlOpenDelayReset();"))
    m = re.search(r"currentRadioDevice->analogTriggeredAudio = false;\n#if defined\(SQL_OPEN_DELAY_ENABLED\)\n\s*trxSqlOpenDelayReset\(\);[^\n]*\n#endif\n\s*trxCssMeasureCount = 0;\n\t\t\t}\n\t\t}\n\n\t\tbool cssFlag", text)
    if not m:
        problems.append("мітка не скидається у гілці гістерезису (сигнал зник)")
    if "uiDataGlobal.Scan.active ? 0U" not in text:
        problems.append("під час сканування затримка не обнуляється")
    if "sqlOpenDelayCheck(&trxSqlOpenSince, ticksGetMillis(), delayMs, true)" not in text:
        problems.append("trxSqlOpenDelayReady не викликає чисту логіку з поточним часом")
    return problems


def test_trx_structure():
    text = read(os.path.join(APP, "source", "functions", "trx.c"))
    check(trx_structure_ok(text) == [], "Z3: trx.c -- затримка в умові відкриття, скидання в 4 місцях, скан без затримки: %r" % trx_structure_ok(text))
    muts = [
        ("умову відкриття без затримки", "\n						&& trxSqlOpenDelayReady()   // R42: динамік відкриваємо лише коли сигнал пробув відкритим задану затримку", ""),
        ("без скидання при зникненні сигналу", "				trxSqlOpenDelayReset();   // R42: сигнал зник -- наступна поява починає відлік затримки заново\n", ""),
        ("без обнулення під час скану", "uiDataGlobal.Scan.active ? 0U", "0U"),
    ]
    for title, old, new in muts:
        n = text.count(old)
        if n != 1:
            check(False, "Z3: мутант trx.c «%s»: шаблон знайдено %d раз(ів), треба 1" % (title, n))
            continue
        check(trx_structure_ok(text.replace(old, new)) != [], "Z3: мутант trx.c «%s» -- структурна перевірка ловить" % title)


# ------------------------------------------------------------------------------------------ Z3: перейменування зони
ZONE_MUTANTS = [
    ("хвіст 0x00 для кінцевої «я» забуто", "codeplug.c",
     "pad = ((n > 0) && (n < len) && (((uint8_t)inBuf[n - 1]) == 0xFF)) ? 0x00 : 0xFF;", "pad = 0xFF;"),
    ("пишемо за номером зони в списку, а не за бітом", "codeplug.c",
     "EEPROM_Write(CODEPLUG_ADDR_EX_ZONE_LIST + (bit * (16 + (sizeof(uint16_t) * codeplugChannelsPerZone))), (uint8_t *)buf, 16)",
     "EEPROM_Write(CODEPLUG_ADDR_EX_ZONE_LIST + (zoneNum * (16 + (sizeof(uint16_t) * codeplugChannelsPerZone))), (uint8_t *)buf, 16)"),
    ("«Всі канали» можна перейменувати (знято обидва захисти: за межею списку й від'ємний біт)", "codeplug.c",
     (("(її назва береться з мовної таблиці): перейменувати нічого\n	if ((zoneNum < 0) || (zoneNum >= (codeplugZonesGetCount() - 1)))", "(її назва береться з мовної таблиці): перейменувати нічого\n	if ((zoneNum < 0) || (zoneNum >= codeplugZonesGetCount()))"),
      ("	bit = codeplugZoneMaskNthBit(codeplugZonesInUseCache, zoneNum);\n	if (bit < 0)\n	{\n		return CODEPLUG_ZONE_RENAME_NOT_REAL;\n	}",
       "	bit = codeplugZoneMaskNthBit(codeplugZonesInUseCache, zoneNum);")), None),
    ("16 символів з «я» не відхиляються", "codeplug.c",
     "if ((n == 16) && (((uint8_t)name[15]) == 0xFF))", "if (0)"),
    ("порожня назва пишеться", "codeplug.c", "	if (n == 0)\n	{\n		return CODEPLUG_ZONE_RENAME_EMPTY;", "	if (0)\n	{\n		return CODEPLUG_ZONE_RENAME_EMPTY;"),
    ("17 символів не відхиляються", "codeplug.c", "	if (n > 16)\n	{\n		return CODEPLUG_ZONE_RENAME_TOO_LONG;", "	if (0)\n	{\n		return CODEPLUG_ZONE_RENAME_TOO_LONG;"),
    ("пишемо 32 байти замість 16 (затирає початок списку каналів)", "codeplug.c", "(uint8_t *)buf, 16))", "(uint8_t *)buf, 32))"),
    ("екранна зона (currentZone) не оновлюється", "codeplug.c", "	if (currentZone.NOT_IN_CODEPLUGDATA_indexNumber == bit)\n	{\n		memcpy(currentZone.name, buf, 16);",
     "	if (0)\n	{\n		memcpy(currentZone.name, buf, 16);"),
    ("збій запису ігнорується", "codeplug.c", "		return CODEPLUG_ZONE_RENAME_WRITE_ERROR;\n	}\n\n	if (currentZone", "		(void)0;\n	}\n\n	if (currentZone"),
]


def run_zone(tmp, codeplug_c):
    src_c = os.path.join(tmp, "codeplug.c")
    with open(src_c, "w", encoding="utf-8") as f:
        f.write(codeplug_c)
    exe = os.path.join(tmp, "t")
    fx = [os.path.join(APP, "source", "functions", n) for n in ("aprs_rx_parse.c", "aprs_mode_cfg.c", "dmr_sms_text.c")]
    cmd = ["gcc"] + ZONE_CFLAGS + FW_INCS + ["-I%s/include" % APP, "-o", exe, os.path.join(FW, "tests", "test_codeplug_zonerename.c"), src_c] + fx + ["-lm"]
    cp = subprocess.run(cmd, capture_output=True, text=True)
    if cp.returncode != 0:
        return False, -1
    return True, subprocess.run([exe], capture_output=True, text=True, timeout=60).returncode


def test_zone_mutants():
    src = read(os.path.join(APP, "source", "functions", "codeplug.c"))
    with tempfile.TemporaryDirectory() as t0:
        built, rc = run_zone(t0, src)
        check(built and rc == 0, "Z3: немутований codeplug.c -- тест перейменування зелений (зібрано=%s, код=%s)" % (built, rc))
    for title, _f, old, new in ZONE_MUTANTS:
        pairs = old if isinstance(old, tuple) else ((old, new),)
        bad = [o for o, _n in pairs if src.count(o) != 1]
        if bad:
            check(False, "Z3: мутант зони «%s»: шаблон знайдено не рівно 1 раз (код змінився -- онови мутант)" % title)
            continue
        mutated = src
        for o, n in pairs:
            mutated = mutated.replace(o, n)
        with tempfile.TemporaryDirectory() as t:
            built, rc = run_zone(t, mutated)
            check(built and rc != 0, "Z3: мутант перейменування «%s» -- тест ловить (зібрано=%s, код=%s)" % (title, built, rc))


# ------------------------------------------------------------------------------------------ Z4: інструменти
def fw_rename(img, bit, name_bytes):
    """Те саме, що codeplugZoneRename() + codeplugUtilConvertStringToBuf(): 16 байтів назви; хвіст 0xFF, а для назви, що закінчується на 0xFF -- 0x00."""
    n = len(name_bytes)
    assert 0 < n <= 16 and not (n == 16 and name_bytes[-1] == 0xFF)
    pad = 0x00 if (n < 16 and name_bytes[-1] == 0xFF) else 0xFF
    st = img.zone_stride()
    rec = bytearray(img.ee(cl.CP_ADDR_EX_ZONE_LIST + bit * st, st))
    rec[0:16] = name_bytes + bytes([pad]) * (16 - n)
    img.set_zone(bit, bytes(rec))


def spi_with_renamed(renames):
    spi = tc.make_fixture_spi()
    rng = cl.flash_backup_range()
    cp_ee = bytearray(spi[:cl.EEPROM_BACKUP_LEN])
    fl = bytearray(spi[rng["raw_start"]:rng["raw_start"] + rng["length"]])
    img = cc.Image(cp_ee, fl, rng["codeplug_start"])
    for bit, nm in renames:
        fw_rename(img, bit, nm)
    spi[:cl.EEPROM_BACKUP_LEN] = img.eeprom
    spi[rng["raw_start"]:rng["raw_start"] + rng["length"]] = img.flash
    return spi


def test_tools_renamed_zone():
    zorya = "Зоря".encode("cp1251")
    nadiya = "Надія".encode("cp1251")
    n15 = ("Закарпаття-Захід".encode("cp1251"))[:14] + b"\xff"          # 15 байтів, останній «я»
    n16 = "ABCDEFGHIJKLMNOP".encode("cp1251")
    spi = spi_with_renamed([(0, zorya), (1, nadiya), (5, n15)])
    cp, _ = tc.codeplug_of(spi)
    names = {z[0]: z[1] for z in cp.zones()}
    check(names.get(1) == "Зоря", "переглядач: зона біта 0 -- «Зоря», кінцева «я» на місці (є %r)" % names.get(1))
    check(names.get(2) == "Надія", "переглядач: зона біта 1 -- «Надія» (є %r)" % names.get(2))
    check(names.get(6) == n15.decode("cp1251"), "переглядач: 15 символів із «я» наприкінці (є %r)" % names.get(6))
    members = {z[0]: z[3] for z in cp.zones()}
    check(members.get(1) == [1, 3] and members.get(2) == [2] and members.get(6) == [1, 2, 3, 130], "склад зон не змінився: %r" % members)
    # CSV: експорт -> імпорт без правок == вихідний байт-у-байт, назви цілі
    with tempfile.TemporaryDirectory() as d:
        tc.export_dir(cp, d)
        zrows = tc.read_csv_rows(os.path.join(d, "Zones.csv"))
        flat = " ".join(" ".join(r) for r in zrows)
        check("Зоря" in flat and "Надія" in flat, "Zones.csv містить «Зоря» й «Надія» з кінцевою «я»")
        res = tc.import_dir(cp, d)
        check(tc.images_equal(res, cp), "Z4: експорт -> імпорт кодплага з перейменованими зонами без правок == вихідний БАЙТ-У-БАЙТ")
        check(not res.any_change() and not res.warnings, "Z4: жодної зміни й жодного попередження: %s %r" % (res.summary(), res.warnings))
    # 16 символів без «я» -- без хвоста, читається цілою
    cp16, _ = tc.codeplug_of(spi_with_renamed([(0, n16)]))
    check({z[0]: z[1] for z in cp16.zones()}.get(1) == "ABCDEFGHIJKLMNOP", "переглядач: рівно 16 символів читаються цілими")
    # «Всі канали» у кодплазі нема: перейменувати нічого (віртуальна зона не потрапляє ні в zones(), ні в CSV)
    check(all(z[1] != "Всі канали" for z in cp.zones()), "віртуальної «Всі канали» немає серед зон кодплага")


# ------------------------------------------------------------------------------------------ Z5: mem_report (флеш)
def test_mem_report():
    sample = """\
build/openuv380-10w.elf  :
section               size        addr
.isr_vector            428    134266880
.text               524288    134267308
.rodata              90000    134791596
.data                 2048    536870912
.bss                 40960    536872960
._user_heap_stack     1536    536913920
.ccmram              40976    268435456
.ARM.attributes         50            0
Total               700286
"""
    full = mr.parse_size_A_full(sample)
    used = mr.flash_used(full)
    check(used == 428 + 524288 + 90000 + 2048 + 40976, "mem_report: зайнято = секції у флеші + образи .data і .ccmram (%d)" % used)
    check(mr.FLASH_SIZE == 999424 and mr.FLASH_ORIGIN == 0x0800C000, "mem_report: регіон флешу 999 424 Б від 0x0800C000")
    ld = read(os.path.join(FW, "STM32F405VGTX_FLASH.ld"))
    check(re.search(r"(?m)^\s*FLASH\s+\(rx\)\s*:\s*ORIGIN = 0x800C000,\s*LENGTH = 1024K - 48K", ld) is not None, "mem_report: розміри збігаються з лінкер-скриптом")
    # на зразку, де .bin повторює образ (секції щільно, без прогалин), розмір .bin збігається з розрахунком
    with tempfile.TemporaryDirectory() as d:
        binp = os.path.join(d, "x.bin")
        with open(binp, "wb") as f:
            f.write(b"\x00" * used)
        out = subprocess.run([sys.executable, os.path.join(HERE, "mem_report.py"), "--self-test"], capture_output=True, text=True)
        check(out.returncode == 0, "mem_report --self-test проходить")
        # друк звіту: підставний size-tool віддає зразок
        fake = os.path.join(d, "fakesize.py")
        with open(fake, "w") as f:
            f.write("#!%s\nimport sys\nprint(open(%r).read())\n" % (sys.executable, os.path.join(d, "size.txt")))
        os.chmod(fake, 0o755)
        with open(os.path.join(d, "size.txt"), "w") as f:
            f.write(sample)
        fakenm = os.path.join(d, "fakenm.py")
        with open(fakenm, "w") as f:
            f.write("#!%s\nprint('Name|Value|Class|Type|Size|Line|Section')\n" % sys.executable)
        os.chmod(fakenm, 0o755)
        r = subprocess.run([sys.executable, os.path.join(HERE, "mem_report.py"), "x.elf", "--size-tool", fake, "--nm-tool", fakenm, "--bin", binp],
                           capture_output=True, text=True)
        o = r.stdout
        check(r.returncode == 0 and "ФЛЕШ програми" in o, "mem_report друкує розділ про флеш (код %s)" % r.returncode)
        check(("ЗАЙНЯТО РАЗОМ:         %8d Б" % used).replace("  ", " ") in o.replace("  ", " ") or str(used) in o, "mem_report: друкується зайнятий флеш %d" % used)
        check(str(mr.FLASH_SIZE - used) in o, "mem_report: друкується вільний флеш %d" % (mr.FLASH_SIZE - used))
        check("%d Б (" % used in o and "розбіжність із розрахунком: +0 Б" in o, "mem_report: розмір .bin збігається з розрахунком (+0)")
        check(o.count("ВІЛЬНО:") == 3, "mem_report: тепер три рядки «ВІЛЬНО» (RAM, CCM, флеш): %d" % o.count("ВІЛЬНО:"))
        # мутація: .data не враховано -> розрахунок розходиться з .bin
        saved = mr.FLASH_LOAD_SECTIONS
        mr.FLASH_LOAD_SECTIONS = ()
        check(mr.flash_used(full) != used, "mem_report: без образів .data/.ccmram розрахунок інший (мутація ловиться)")
        mr.FLASH_LOAD_SECTIONS = saved


# ------------------------------------------------------------------------------------------ Z5b: TS у шапці (C4)
def test_ts_excluded():
    import screen_views as sv
    rect = [r for n, r in sc.EXCLUDED_ALWAYS if "таймслот" in n]
    check(len(rect) == 1, "C4: ділянка таймслота є серед виключених")
    if not rect:
        return
    x1, y1, x2, y2 = rect[0]
    # виміряна на залізі ділянка розбіжності (x 29..43, y 2..8) і всі варіанти положення тексту TS (itemOffset 0..2, три символи по 6 пікселів) мають в неї потрапляти
    check(x1 <= 29 and x2 >= 43 and y1 <= 2 and y2 >= 8, "C4: виміряні x 29..43, y 2..8 лежать усередині виключеної ділянки %r" % (rect[0],))
    for off in (0, 1, 2):
        tx = 37 + off - 9
        check(x1 <= tx - 1 and tx + 18 <= x2 + 1 and y1 <= 1 and y2 >= 9 - 1, "C4: текст TS при itemOffset=%d (x %d..%d) у ділянці" % (off, tx, tx + 17))
    pw = sc.POWER_BOX
    check(x2 < pw[0], "C4: ділянка TS не заходить на рядок потужності (%d < %d)" % (x2, pw[0]))
    # живий кадр рації показує ІНШИЙ TS, ніж кодплаг (кнопка перемкнула) -> піксельна різниця 0 завдяки виключеній ділянці; без неї -- ненульова
    import test_r39 as t39
    spi = t39.real_selection_spi(zone_pos=0, lucz_idx=0)
    cpx = t39.codeplug_of(spi)
    state = sc.real_state(cpx, sc.read_current_selection(cpx))[0]
    other_ts = 1 if state.get("ts") == 2 else 2
    live = sv.render("channel", dict(state, battery_pct=99, ts=other_ts))
    res, _ = t39.run_s3(t39.buf(t39.words(live)), spi=spi)
    ref = t39.step(res, "довідково: пікселів")
    check(res.status == sc.PASS and ref is not None and ref.got.startswith("0.000 %"),
          "C4: інший TS на екрані рації (TS%s проти кодплага TS%s) -- довідкова різниця 0.000 %%: %s" % (other_ts, state.get("ts"), ref.got if ref else None))
    saved = sc.EXCLUDED_ALWAYS
    try:
        sc.EXCLUDED_ALWAYS = tuple(x for x in saved if "таймслот" not in x[0])
        res, _ = t39.run_s3(t39.buf(t39.words(live)), spi=spi)
        ref = t39.step(res, "довідково: пікселів")
        check(ref is not None and not ref.got.startswith("0.000 %"), "C4: без виключеної ділянки TS різниця ненульова (мутація): %s" % (ref.got if ref else None))
    finally:
        sc.EXCLUDED_ALWAYS = saved


# ------------------------------------------------------------------------------------------ Z7
def test_default_identity():
    base = os.environ.get("R42_BASE")
    if not base:
        print("  --   Z7 пропущено: задай R42_BASE=<каталог application попередньої версії> (git archive <база> MDUV380_firmware/application)")
        return
    files = ["source/functions/trx.c", "source/functions/codeplug.c", "source/user_interface/menuRadioOptions.c", "source/user_interface/menuZoneList.c",
             "source/user_interface/uiLocalisation.c", "source/user_interface/menuSystem.c", "source/user_interface/uiChannelMode.c"]
    configs = {"AES0": [], "UA": ["-DENABLE_AES", "-DENABLE_DMR_DATA", "-DLANGUAGE_BUILD_UKRAINIAN", "-DENABLE_CALL_REPLAY", "-DENABLE_APRS_RX", "-DENABLE_CHANNEL_DELETE"],
               "EN": ["-DENABLE_AES", "-DENABLE_DMR_DATA", "-DENABLE_CALL_REPLAY"]}
    common = ["-DUSE_HAL_DRIVER", "-DSTM32F405xx", "-DPLATFORM_MDUV380", "-DPLATFORM_VARIANT_UV380_PLUS_10W", "-DNDEBUG", "-DGITVERSION=x"]

    def pp(appdir, rel, extra):
        fw_incs = [x.replace(FW + "/application/include", appdir + "/include") for x in FW_INCS]
        cmd = ["gcc", "-E", "-P", "-x", "c", "-std=gnu11"] + common + extra + ["-I%s/include" % appdir] + fw_incs + ["-I%s/include" % appdir, os.path.join(appdir, rel)]
        r = subprocess.run(cmd, capture_output=True)       # байти: мовні таблиці в cp1251
        return r.returncode, re.sub(rb"\s+", b"", r.stdout)       # потік токенів: розриви рядків і пробіли на код не впливають
    for cname, extra in configs.items():
        for rel in files:
            rc1, a = pp(base, rel, extra)
            rc2, b = pp(APP, rel, extra)
            check(rc1 == 0 and rc2 == 0 and a == b, "Z7 [%s] %s: без ENABLE_SQL_OPEN_DELAY/ENABLE_ZONE_RENAME == стара версія (%d / %d символів)" % (cname, rel, len(a), len(b)))
    # і навпаки: з прапорцями код ЗМІНЮЄТЬСЯ (інакше перевірка нічого не варта)
    on = configs["UA"] + ["-DENABLE_SQL_OPEN_DELAY", "-DENABLE_ZONE_RENAME"]
    for rel in ("source/functions/trx.c", "source/user_interface/menuRadioOptions.c", "source/user_interface/menuZoneList.c", "source/functions/codeplug.c"):
        _r1, a = pp(base, rel, configs["UA"])
        _r2, b = pp(APP, rel, on)
        check(a != b, "Z7 [UA+R42] %s: з прапорцями код інший (перевірка чутлива)" % rel)


def main():
    test_delay_mutants()
    test_trx_structure()
    test_zone_mutants()
    test_tools_renamed_zone()
    test_mem_report()
    test_ts_excluded()
    test_default_identity()
    if FAILS:
        print("\nПРОВАЛІВ: %d" % len(FAILS))
        sys.exit(1)
    print("test_r42: усе гаразд")


if __name__ == "__main__":
    main()
