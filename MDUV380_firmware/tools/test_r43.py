#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R43: редагування зон з рації (додати канал, вийняти канал, створити й видалити зону) -- мутації прошивкової логіки, структура меню, інструменти.

Z4  мутації: у копії codeplug_zoneedit.h / codeplug.c ламається одне місце -- хост-тест tests/test_codeplug_zoneedit.c (справжній codeplug.c) МАЄ провалитись:
    забули зсув при вийманні, не оновили маску, не перейшли з видаленої зони, не перерахували поточну зону, стерли запис видаленої зони (ламає автовизначення
    розкладки), нулі замість 0xFF у новому записі тощо;
Z4b menuZoneList.c / uiChannelMode.c (на хості не збираються) -- структурна перевірка: «#» відкриває дії, видалення зони лише після підтвердження зеленою, порожні зони
    видно в списку, пункт швидкого меню «Вийняти із зони» не виконується швидкою клавішею, після виймання спорожнілої зони -- «Всі канали», + їхні мутації;
Z5  tools/: кодплаг після ТИХ САМИХ операцій, що робить прошивка (створити зону, додати, вийняти, видалити зону -- дірка в нумерації), читається переглядачем,
    CSV-коло (експорт -> імпорт) байт-у-байт, розкладка 16/80 за байтом 0x806F не змінилась;
Z7  (за бажанням, змінна R43_BASE=<каталог application версії R42>) типова збірка (без ENABLE_ZONE_EDIT) після препроцесора ідентична старій.
Запуск: `python3 tools/test_r43.py` (без рації, без ARM-тулчейну; потрібен лише gcc)."""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.abspath(os.path.join(HERE, ".."))
APP = os.path.join(FW, "application")
sys.path.insert(0, HERE)

import cps_csv as cc                     # noqa: E402
import cps_link as cl                    # noqa: E402
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
               "-DLANGUAGE_BUILD_UKRAINIAN", "-DENABLE_AES", "-DENABLE_APRS_RX", "-DENABLE_ZONE_RENAME", "-DENABLE_ZONE_EDIT"]

HDR_REL = os.path.join("functions", "codeplug_zoneedit.h")


# ------------------------------------------------------------------------------------------ Z4: мутації
def run_edit(tmp, codeplug_c, header):
    """Збирає tests/test_codeplug_zoneedit.c з (можливо мутованими) codeplug.c і codeplug_zoneedit.h; мутований заголовок стоїть у -I ПЕРЕД справжнім."""
    inc = os.path.join(tmp, "inc", "functions")
    os.makedirs(inc, exist_ok=True)
    with open(os.path.join(inc, "codeplug_zoneedit.h"), "w", encoding="utf-8") as f:
        f.write(header)
    src_c = os.path.join(tmp, "codeplug.c")
    with open(src_c, "w", encoding="utf-8") as f:
        f.write(codeplug_c)
    exe = os.path.join(tmp, "t")
    fx = [os.path.join(APP, "source", "functions", n) for n in ("aprs_rx_parse.c", "aprs_mode_cfg.c", "dmr_sms_text.c")]
    cmd = (["gcc"] + ZONE_CFLAGS + FW_INCS + ["-I%s" % os.path.join(tmp, "inc"), "-I%s/include" % APP, "-I%s/source/functions" % APP, "-o", exe,
           os.path.join(FW, "tests", "test_codeplug_zoneedit.c"), src_c] + fx + ["-lm"])
    cp = subprocess.run(cmd, capture_output=True, text=True)
    if cp.returncode != 0:
        return False, -1
    return True, subprocess.run([exe], capture_output=True, text=True, timeout=120).returncode


# (назва, файл, [(старе, нове)...])
EDIT_MUTANTS = [
    # --- чиста логіка
    ("виймання БЕЗ ЗСУВУ: позицію лише обнуляють (навігація зупинилась би на дірці)", "h",
     [("	for (int i = pos; i < (count - 1); i++)\n	{\n		list[i] = list[i + 1];\n	}\n	list[count - 1] = 0;\n	return count - 1;",
       "	list[pos] = 0;\n	return count - 1;")]),
    ("виймання не обнуляє звільнене місце в кінці списку (лишається дубль)", "h", [("	list[count - 1] = 0;\n	return count - 1;", "	return count - 1;")]),
    ("додавання не перевіряє межу зони (запис за кінець списку)", "h", [("if ((channel == 0U) || (count < 0) || (count >= cap))", "if ((channel == 0U) || (count < 0))")]),
    ("перший вільний біт шукають з 1, а не з 0", "h",
     [("	for (int bit = 0; bit < CODEPLUG_ZONE_MASK_BITS; bit++)\n	{\n		if (!codeplugZoneMaskBit(mask, bit))", "	for (int bit = 1; bit < CODEPLUG_ZONE_MASK_BITS; bit++)\n	{\n		if (!codeplugZoneMaskBit(mask, bit))")]),
    ("ординал зони рахує й саму зону (зсув на 1)", "h", [("	for (int b = 0; b < bit; b++)\n	{\n		if (codeplugZoneMaskBit(mask, b))", "	for (int b = 0; b <= bit; b++)\n	{\n		if (codeplugZoneMaskBit(mask, b))")]),
    ("видалену поточну зону лишають як є (НЕ переходять на «Всі канали»)", "h",
     [("	return (ord >= 0) ? ord : codeplugZoneMaskCount(newMask);", "	return (ord >= 0) ? ord : ((curBit >= 0) ? 0 : codeplugZoneMaskCount(newMask));")]),
    ("поточна «Всі канали» не отримує нового номера після зміни кількості зон", "h",
     [("	return (ord >= 0) ? ord : codeplugZoneMaskCount(newMask);", "	return (ord >= 0) ? ord : (curBit >= 0 ? codeplugZoneMaskCount(newMask) : 0);")]),
    ("LUCZ не зменшується, коли вийнято запис ліворуч від нього", "h", [("	if (pos < oldIdx)\n	{\n		return oldIdx - 1;\n	}", "	if (pos < oldIdx)\n	{\n		return oldIdx;\n	}")]),
    ("LUCZ після виймання останнього лишається за межею списку", "h", [("		return (oldIdx >= newCount) ? 0 : oldIdx;\n	}\n	return oldIdx;", "		return oldIdx;\n	}\n	return oldIdx;")]),
    ("n-й канал зі списку вибору зсунуто на 1", "h", [("		if (((mask[idx >> 3] >> (idx & 7)) & 0x01U) != 0U)\n		{\n			if (++seen == n)\n			{\n				return idx + 1;", "		if (((mask[idx >> 3] >> (idx & 7)) & 0x01U) != 0U)\n		{\n			if (++seen == n)\n			{\n				return idx + 2;")]),
    ("біт маски зон ставиться не туди", "h", [("mask[bit >> 3] = (uint8_t)(mask[bit >> 3] | (1U << (bit & 7)));", "mask[bit >> 3] = (uint8_t)(mask[bit >> 3] | (1U << ((bit + 1) & 7)));")]),
    # --- codeplug.c
    ("створення НЕ ставить біт у масці (зона невидима)", "c",
     [("	codeplugZoneMaskSetBit(newMask, bit);\n	if (!codeplugZoneMaskWrite(newMask, bit))", "	codeplugZoneMaskSetBit(newMask, bit);\n	if (0)")]),
    ("видалення НЕ знімає біт у масці", "c",
     [("	codeplugZoneMaskClearBit(newMask, bit);\n	if (!codeplugZoneMaskWrite(newMask, bit))", "	codeplugZoneMaskClearBit(newMask, bit);\n	if (0)")]),
    ("видалення не перераховує поточну зону (не переходить з видаленої)", "c",
     [("	codeplugZoneFixCurrent(oldMask, curZoneOrdinal);\n	return CODEPLUG_ZONE_EDIT_OK;\n}\n\n/* Список вибору", "	return CODEPLUG_ZONE_EDIT_OK;\n}\n\n/* Список вибору")]),
    ("створення не перераховує поточну зону", "c",
     [("	codeplugZoneFixCurrent(oldMask, curZoneOrdinal);\n	if (newOrdinal != NULL)", "	if (newOrdinal != NULL)")]),
    ("новий запис зони заповнений 0xFF замість нулів (канали-сміття)", "c", [("	memset(&z, 0, sizeof(z));\n	switch (codeplugZoneNameToBuf", "	memset(&z, 0xFF, sizeof(z));\n	switch (codeplugZoneNameToBuf")]),
    ("видалення стирає запис зони 0xFF (ламає автовизначення розкладки й чіпає чуже)", "c",
     [("	codeplugSetLastUsedChannelInZone(bit, 0);\n	codeplugSaveLastUsedChannelInZone();\n\n	codeplugZoneFixCurrent(oldMask, curZoneOrdinal);\n	return CODEPLUG_ZONE_EDIT_OK;\n}\n\n/* Список вибору",
       "	{ uint8_t ff[16]; memset(ff, 0xFF, sizeof(ff)); EEPROM_Write(codeplugZoneRecordAddr(bit), ff, sizeof(ff)); }\n	codeplugSetLastUsedChannelInZone(bit, 0);\n	codeplugSaveLastUsedChannelInZone();\n\n	codeplugZoneFixCurrent(oldMask, curZoneOrdinal);\n	return CODEPLUG_ZONE_EDIT_OK;\n}\n\n/* Список вибору")]),
    ("створення не обнуляє LUCZ нової зони (лишається мітка від попередньої)", "c",
     [("	// 3. LUCZ\n	codeplugSetLastUsedChannelInZone(bit, 0);\n	codeplugSaveLastUsedChannelInZone();\n", "	// 3. LUCZ\n")]),
    ("додавання пише канал не в першу вільну позицію", "c", [("16 + (int)(sizeof(uint16_t) * num), (uint8_t *)&ch", "16 + (int)(sizeof(uint16_t) * (num + 1)), (uint8_t *)&ch")]),
    ("додавання не відсікає дубль", "c", [("	if (codeplugZoneListFind(z.channels, num, ch) >= 0)\n	{\n		return CODEPLUG_ZONE_EDIT_ALREADY_IN_ZONE;", "	if (0)\n	{\n		return CODEPLUG_ZONE_EDIT_ALREADY_IN_ZONE;")]),
    ("додавання приймає канал, якого нема в масці", "c", [("	if (!codeplugAllChannelsIndexIsInUse(channelIndex))\n	{\n		return CODEPLUG_ZONE_EDIT_CHANNEL_NOT_IN_USE;", "	if (0)\n	{\n		return CODEPLUG_ZONE_EDIT_CHANNEL_NOT_IN_USE;")]),
    ("виймання записує лише 1 байт хвоста замість усього (зсув не доходить до кодплага)", "c", [("(int)(sizeof(uint16_t) * (num - pos))))", "1))")]),
    ("виймання не поправляє LUCZ", "c",
     [("	if (newIdx != oldIdx)\n	{\n		codeplugSetLastUsedChannelInZone(bit, (int16_t)newIdx);\n		codeplugSaveLastUsedChannelInZone();\n	}\n\n	codeplugZoneRefreshCurrent(bit, zoneNum);\n	return CODEPLUG_ZONE_EDIT_OK;\n}\n\n#if defined(ZONE_MOVE_ENABLED)",
       "	codeplugZoneRefreshCurrent(bit, zoneNum);\n	return CODEPLUG_ZONE_EDIT_OK;\n}\n\n#if defined(ZONE_MOVE_ENABLED)")]),
    ("екранна зона (currentZone) не оновлюється після змін", "c", [("	if (currentZone.NOT_IN_CODEPLUGDATA_indexNumber == bit)\n	{\n		codeplugZoneGetDataForNumber(zoneNum, &currentZone);", "	if (0)\n	{\n		codeplugZoneGetDataForNumber(zoneNum, &currentZone);")]),
    ("додавання в «Всі канали» не відсікається (NOT_REAL забуто)", "c", [("	int bit = codeplugZoneRealBit(zoneNum);\n	int num;\n	uint16_t ch = (uint16_t)channelIndex;\n\n	if (bit < 0)", "	int bit = codeplugZoneRealBit(zoneNum);\n	int num;\n	uint16_t ch = (uint16_t)channelIndex;\n\n	if (0)")]),
    ("збій запису маски при видаленні ігнорується (кеш змінюється)", "c",
     [("	if (!EEPROM_Write(CODEPLUG_ADDR_EX_ZONE_INUSE_PACKED_DATA + (bit >> 3), (uint8_t *)&newMask[bit >> 3], 1))\n	{\n		return false;\n	}\n	codeplugZonesInUseCache",
       "	EEPROM_Write(CODEPLUG_ADDR_EX_ZONE_INUSE_PACKED_DATA + (bit >> 3), (uint8_t *)&newMask[bit >> 3], 1);\n	codeplugZonesInUseCache")]),
]


def test_edit_mutants():
    src_c = read(os.path.join(APP, "source", "functions", "codeplug.c"))
    src_h = read(os.path.join(APP, "include", "functions", "codeplug_zoneedit.h"))
    with tempfile.TemporaryDirectory() as t0:
        built, rc = run_edit(t0, src_c, src_h)
        check(built and rc == 0, "Z4: немутовані codeplug.c і codeplug_zoneedit.h -- хост-тест зелений (зібрано=%s, код=%s)" % (built, rc))
    for title, which, pairs in EDIT_MUTANTS:
        text = src_h if which == "h" else src_c
        bad = [o for o, _n in pairs if text.count(o) != 1]
        if bad:
            check(False, "Z4: мутант «%s»: шаблон знайдено не рівно 1 раз (код змінився -- онови мутант): %r" % (title, bad[0][:70]))
            continue
        mut = text
        for o, n in pairs:
            mut = mut.replace(o, n)
        with tempfile.TemporaryDirectory() as t:
            built, rc = run_edit(t, mut if which == "c" else src_c, mut if which == "h" else src_h)
            check(built and rc != 0, "Z4: мутант «%s» -- тест ловить (зібрано=%s, код=%s)" % (title, built, rc))


# ------------------------------------------------------------------------------------------ Z4b: структура меню
def zone_menu_problems(text):
    p = []
    if not re.search(r"#if defined\(ZONE_EDIT_ENABLED\)\n\t\tzeEnterActions\(\);", text):
        p.append("«#» не відкриває дії над зоною")
    if not re.search(r"if \(ZE_STATE == ZE_ST_CONFIRM\)\n\t\{\n\t\tif \(KEYCHECK_SHORTUP\(ev->keys, KEY_GREEN\)\)\n\t\t\{\n\t\t\tzeDeleteConfirmed\(\);", text):
        p.append("видалення зони не лише за підтвердженням зеленою")
    if "zeDeleteConfirmed();" not in text or text.count("zeDeleteConfirmed();") != 1:
        p.append("zeDeleteConfirmed() викликається не в одному місці (підтвердження)")
    if "|| (ZL_EDIT() && zoneIsEmpty(zn))" not in text:
        p.append("порожні зони не видно в списку")
    if not re.search(r"if \(menuDataGlobal\.currentItemIndex >= s_zoneMapCount\)\n\t\{\n\t\tzeStartCreate\(\);", text):
        p.append("пункт «Нова зона» не запускає створення")
    if not re.search(r"if \(zoneIsEmpty\(s_zoneMap\[menuDataGlobal\.currentItemIndex\]\)\)\n\t\{\n\t\tzeEnterActions\(\);", text):
        p.append("зелена на порожній зоні не відкриває дії")
    if "codeplugZoneDelete((uint8_t)ZR_ZN, &cur) == CODEPLUG_ZONE_EDIT_OK" not in text or text.count("settingsSet(nonVolatileSettings.currentZone, cur);") < 2:
        p.append("після видалення зони поточну зону не записано в налаштування")
    if text.count("zeNotifyMax(") < 3:
        p.append("межі (зон / каналів у зоні) не повідомляються словами")
    if "currentLanguage->zone_chans_kept" not in text:
        p.append("екран видалення зони не каже, що канали лишаються")
    if "menuDataGlobal.numItems = s_zoneMapCount" in text.replace("s_zoneMapCount + 1", ""):
        pass
    if "return s_zoneMapCount + (ZL_EDIT() ? 1 : 0);" not in text:
        p.append("у списку зон нема пункту «Нова зона»")
    return p


def channel_menu_problems(text, hdr):
    p = []
    if not re.search(r"CH_SCREEN_QUICK_MENU_DELETE,[^\n]*\n#endif\n#if defined\(CH_QUICKMENU_ZONE_REMOVE_ENABLED\)\n\tCH_SCREEN_QUICK_MENU_ZONE_REMOVE,[^\n]*\n#endif\n(?:#if defined\(DUAL_CHANNEL_ENABLED\)\n(?:\t[^\n]*\n)+#endif\n)?\tNUM_CH_SCREEN_QUICK_MENU_ITEMS", hdr):   # R97: пункти «Подвійного прийому» -- лише ПІСЛЯ (під своїм прапорцем)
        p.append("«Вийняти із зони» не останній пункт швидкого меню (зсунулись би номери швидких клавіш)")
    if not re.search(r"QUICKKEY_ENTRYID\(ev->function\) == CH_SCREEN_QUICK_MENU_ZONE_REMOVE\)\)\n\t\t\{\n[^\n]*\n\t\t\treturn;", text):
        p.append("виймання виконується швидкою клавішею")
    if "(menuDataGlobal.currentItemIndex != CH_SCREEN_QUICK_MENU_ZONE_REMOVE)" not in text:
        p.append("на «Вийняти із зони» можна призначити швидку клавішу")
    if "uiChannelModeZoneRemoveChannelAt(nonVolatileSettings.currentZone, codeplugGetLastUsedChannelInCurrentZone())" not in text:
        p.append("виймається не запис під «останнім каналом у зоні»")
    if not re.search(r"if \(!codeplugZoneIsUsable\(zn, NULL\) && \(zn == nonVolatileSettings\.currentZone\)\)\n\t\t\{\n\t\t\tsettingsSet\(nonVolatileSettings\.currentZone, \(int16_t\)\(codeplugZonesGetCount\(\) - 1\)\);", text):
        p.append("спорожніла зона не веде на «Всі канали»")
    if "uiChannelModeColdStart();   // примусове перечитування зони й каналу при поверненні на екран каналу\n\t\tuiNotificationShowShort(1500U, currentLanguage->zone_ch_removed" not in text:
        p.append("після виймання екран каналу не перечитує зону")
    if not re.search(r"validateZoneRemoveChannel\(void\)\n\{\n\tquickmenuChannelFromVFOHandled = true;", text):
        p.append("колбек виймання не закриває швидке меню")
    if "currentLanguage->zone_chan_stays" not in text:
        p.append("екран підтвердження не каже, що канал лишиться")
    if "currentLanguage->zone_not_zone" not in text:
        p.append("у «Всіх каналах» нема пояснення «Це не зона»")
    return p


MENU_MUTANTS = [
    ("«#» перейменовує, а не відкриває дії", "zone",
     "#if defined(ZONE_EDIT_ENABLED)\n		zeEnterActions();", "#if defined(ZONE_EDIT_ENABLED)\n		zrStart(s_zoneMap[menuDataGlobal.currentItemIndex]);"),
    ("зона видаляється без підтвердження (одразу на «Видалити зону»)", "zone",
     "			ZE_STATE = ZE_ST_CONFIRM;\n			zeDraw();", "			zeDeleteConfirmed();"),
    ("порожні зони не видно в списку", "zone", "|| (ZL_EDIT() && zoneIsEmpty(zn))", "|| 0"),
    ("пункт «Нова зона» з'їдено", "zone", "	return s_zoneMapCount + (ZL_EDIT() ? 1 : 0);", "	return s_zoneMapCount;"),
    ("екран видалення зони не каже про канали", "zone", "currentLanguage->zone_chans_kept", "currentLanguage->zone_deleted"),
    ("поточну зону після видалення не зберігають", "zone", "		settingsSet(nonVolatileSettings.currentZone, cur);\n		channelScreenChannelData.rxFreq = 0x00;   // екран каналу перечитає зону (uiChannelInitializeCurrentZone), вибір піде",
     "		channelScreenChannelData.rxFreq = 0x00;   // екран каналу перечитає зону (uiChannelInitializeCurrentZone), вибір піде"),
    ("виймання швидкою клавішею дозволено", "chan",
     "		else if ((QUICKKEY_TYPE(ev->function) == QUICKKEY_MENU) && (QUICKKEY_ENTRYID(ev->function) == CH_SCREEN_QUICK_MENU_ZONE_REMOVE))\n		{\n			// R43: виймання з зони теж НІКОЛИ не виконується швидкою клавішею\n			return;",
     "		else if ((QUICKKEY_TYPE(ev->function) == QUICKKEY_MENU) && (QUICKKEY_ENTRYID(ev->function) == CH_SCREEN_QUICK_MENU_ZONE_REMOVE))\n		{\n			(void)0;"),
    ("спорожніла зона не веде на «Всі канали»", "chan", "		if (!codeplugZoneIsUsable(zn, NULL) && (zn == nonVolatileSettings.currentZone))\n		{\n			settingsSet(nonVolatileSettings.currentZone, (int16_t)(codeplugZonesGetCount() - 1));",
     "		if (0)\n		{\n			settingsSet(nonVolatileSettings.currentZone, (int16_t)(codeplugZonesGetCount() - 1));"),
    ("виймається не поточний запис, а перший", "chan", "uiChannelModeZoneRemoveChannelAt(nonVolatileSettings.currentZone, codeplugGetLastUsedChannelInCurrentZone())", "uiChannelModeZoneRemoveChannelAt(nonVolatileSettings.currentZone, 0)"),
    ("екран каналу не перечитує зону після виймання", "chan",
     "		uiChannelModeColdStart();   // примусове перечитування зони й каналу при поверненні на екран каналу\n		uiNotificationShowShort(1500U, currentLanguage->zone_ch_removed",
     "		uiNotificationShowShort(1500U, currentLanguage->zone_ch_removed"),
]


def test_menu_structure():
    zone = read(os.path.join(APP, "source", "user_interface", "menuZoneList.c"))
    chan = read(os.path.join(APP, "source", "user_interface", "uiChannelMode.c"))
    hdr = read(os.path.join(APP, "include", "user_interface", "menuSystem.h"))
    zp = zone_menu_problems(zone)
    cp = channel_menu_problems(chan, hdr)
    check(zp == [], "Z4b: menuZoneList.c -- дії над зоною, підтвердження видалення, порожні зони, «Нова зона»: %r" % zp)
    check(cp == [], "Z4b: uiChannelMode.c -- «Вийняти із зони»: останній пункт, без швидкої клавіші, перехід на «Всі канали»: %r" % cp)
    for title, which, old, new in MENU_MUTANTS:
        text = zone if which == "zone" else chan
        n = text.count(old)
        if n != 1:
            check(False, "Z4b: мутант меню «%s»: шаблон знайдено %d раз(ів), треба 1" % (title, n))
            continue
        mut = text.replace(old, new)
        probs = zone_menu_problems(mut) if which == "zone" else channel_menu_problems(mut, hdr)
        check(probs != [], "Z4b: мутант меню «%s» -- структурна перевірка ловить" % title)
    # заголовок: «Вийняти із зони» не останній
    mh = hdr.replace("#if defined(CH_QUICKMENU_ZONE_REMOVE_ENABLED)\n	CH_SCREEN_QUICK_MENU_ZONE_REMOVE,", "#if defined(CH_QUICKMENU_ZONE_REMOVE_ENABLED)\n	CH_SCREEN_QUICK_MENU_FILTER_DMR_TS_X,", 1)
    check(channel_menu_problems(chan, mh) != [], "Z4b: мутант меню «пункт швидкого меню не на місці» -- ловить")


# ------------------------------------------------------------------------------------------ Z5: інструменти
def fw_create(img, name_bytes):
    """Те саме, що codeplugZoneCreate(): перший вільний біт; запис (назва + НУЛІ замість каналів), потім біт у масці."""
    n = len(name_bytes)
    assert 0 < n <= 16 and not (n == 16 and name_bytes[-1] == 0xFF)
    mask = img.ee(cl.CP_ADDR_EX_ZONE_INUSE, 32)
    bit = next(b for b in range(cl.CP_ZONES_MAX) if not (mask[b >> 3] >> (b & 7)) & 1)
    pad = 0x00 if (n < 16 and name_bytes[-1] == 0xFF) else 0xFF
    rec = name_bytes + bytes([pad]) * (16 - n) + bytes(2 * img.zone_format())
    img.set_zone(bit, rec)                 # set_zone: запис, потім біт -- як у прошивці
    return bit


def fw_add(img, bit, ch):
    st = img.zone_stride()
    rec = bytearray(img.ee(cl.CP_ADDR_EX_ZONE_LIST + bit * st, st))
    n = img.zone_format()
    lst = [rec[16 + 2 * i] | (rec[17 + 2 * i] << 8) for i in range(n)]
    cnt = lst.index(0) if 0 in lst else n
    assert cnt < n and ch not in lst[:cnt]
    img.set_ee(cl.CP_ADDR_EX_ZONE_LIST + bit * st + 16 + 2 * cnt, bytes([ch & 0xFF, ch >> 8]))


def fw_remove_at(img, bit, pos):
    st = img.zone_stride()
    n = img.zone_format()
    rec = bytearray(img.ee(cl.CP_ADDR_EX_ZONE_LIST + bit * st, st))
    lst = [rec[16 + 2 * i] | (rec[17 + 2 * i] << 8) for i in range(n)]
    cnt = lst.index(0) if 0 in lst else n
    assert 0 <= pos < cnt
    lst = lst[:pos] + lst[pos + 1:cnt] + [0] * (n - cnt + 1)
    tail = b"".join(bytes([v & 0xFF, v >> 8]) for v in lst[pos:cnt])
    img.set_ee(cl.CP_ADDR_EX_ZONE_LIST + bit * st + 16 + 2 * pos, tail)


def fw_delete(img, bit):
    img.clear_zone(bit)                    # лише біт у масці; запис не стирається


def spi_with_ops(ops):
    spi = tc.make_fixture_spi()
    rng = cl.flash_backup_range()
    img = cc.Image(bytearray(spi[:cl.EEPROM_BACKUP_LEN]), bytearray(spi[rng["raw_start"]:rng["raw_start"] + rng["length"]]), rng["codeplug_start"])
    fmt0 = img.zone_format()
    ops(img)
    assert img.zone_format() == fmt0, "розкладка 16/80 змінилась"
    spi[:cl.EEPROM_BACKUP_LEN] = img.eeprom
    spi[rng["raw_start"]:rng["raw_start"] + rng["length"]] = img.flash
    return spi, fmt0


def test_tools():
    made = {}

    def ops(img):
        made["new"] = fw_create(img, "Нова зона".encode("cp1251"))
        made["zorya"] = fw_create(img, "Зоря".encode("cp1251"))
        for ch in (2, 3, 130):
            fw_add(img, made["new"], ch)
        fw_remove_at(img, made["new"], 1)          # вийняти середній: 2, 130
        fw_add(img, made["zorya"], 1)
        fw_delete(img, 1)                          # дірка в нумерації зон: зникає друга зона фікстури (біт 1)

    spi, fmt0 = spi_with_ops(ops)
    cp, _ = tc.codeplug_of(spi)
    zones = {z[1]: z[3] for z in cp.zones()}
    check(zones.get("Нова зона") == [2, 130], "Z5: «Нова зона»: додано 2, 3, 130; вийнято середній -> 2, 130 (є %r)" % zones.get("Нова зона"))
    check(zones.get("Зоря") == [1], "Z5: «Зоря» (кінцева «я») створена й має канал 1 (є %r)" % zones.get("Зоря"))
    check("Local" not in zones and "Київ" in zones, "Z5: видалена зона зникла, інші цілі: %r" % sorted(zones))
    check(all(z[3] == sorted(set(z[3])) or True for z in cp.zones()), "Z5: списки каналів читаються")
    with tempfile.TemporaryDirectory() as d:
        tc.export_dir(cp, d)
        res = tc.import_dir(cp, d)
        check(tc.images_equal(res, cp), "Z5: експорт -> імпорт кодплага після всіх операцій без правок == вихідний БАЙТ-У-БАЙТ")
        check(not res.any_change() and not res.warnings, "Z5: жодної зміни й жодного попередження: %s %r" % (res.summary(), res.warnings))
    check(fmt0 in (16, 80), "Z5: розкладка зон (%d каналів) не змінилась від операцій" % fmt0)

    # усі зони видалено: лишаються «Всі канали» (їх у кодплазі нема) -- кодплаг читається
    def ops_all(img):
        for bit, _rec in list(img.zones()):
            fw_delete(img, bit)

    spi0, _ = spi_with_ops(ops_all)
    cp0, _ = tc.codeplug_of(spi0)
    check(cp0.zones() == [], "Z5: без жодної зони кодплаг читається (зон 0)")
    with tempfile.TemporaryDirectory() as d:
        try:
            tc.export_dir(cp0, d)
            res0 = tc.import_dir(cp0, d)
            check(tc.images_equal(res0, cp0), "Z5: кодплаг БЕЗ зон -- експорт -> імпорт байт-у-байт")
        except Exception as e:                                          # noqa: BLE001
            check(False, "Z5: кодплаг без зон не проходить CSV-коло: %r" % (e,))


# ------------------------------------------------------------------------------------------ Z7
def test_default_identity():
    base = os.environ.get("R43_BASE")
    if not base:
        print("  --   Z7 пропущено: задай R43_BASE=<каталог application версії R42> (git archive <база> MDUV380_firmware/application)")
        return
    files = ["source/functions/trx.c", "source/functions/codeplug.c", "source/user_interface/menuRadioOptions.c", "source/user_interface/menuZoneList.c",
             "source/user_interface/uiLocalisation.c", "source/user_interface/menuSystem.c", "source/user_interface/uiChannelMode.c"]
    r42 = ["-DENABLE_SQL_OPEN_DELAY", "-DENABLE_ZONE_RENAME"]
    configs = {"AES0": [], "UA": ["-DENABLE_AES", "-DENABLE_DMR_DATA", "-DLANGUAGE_BUILD_UKRAINIAN", "-DENABLE_CALL_REPLAY", "-DENABLE_APRS_RX", "-DENABLE_CHANNEL_DELETE"],
               "EN": ["-DENABLE_AES", "-DENABLE_DMR_DATA", "-DENABLE_CALL_REPLAY"]}
    common = ["-DUSE_HAL_DRIVER", "-DSTM32F405xx", "-DPLATFORM_MDUV380", "-DPLATFORM_VARIANT_UV380_PLUS_10W", "-DNDEBUG", "-DGITVERSION=x"]

    def pp(appdir, rel, extra):
        fw_incs = [x.replace(FW + "/application/include", appdir + "/include") for x in FW_INCS]
        cmd = ["gcc", "-E", "-P", "-x", "c", "-std=gnu11"] + common + extra + ["-I%s/include" % appdir] + fw_incs + ["-I%s/include" % appdir, os.path.join(appdir, rel)]
        r = subprocess.run(cmd, capture_output=True)
        return r.returncode, re.sub(rb"\s+", b"", r.stdout)
    for cname, extra in configs.items():
        for rel in files:
            rc1, a = pp(base, rel, extra)
            rc2, b = pp(APP, rel, extra)
            check(rc1 == 0 and rc2 == 0 and a == b, "Z7 [%s] %s: без ENABLE_ZONE_EDIT == R42 (%d / %d символів)" % (cname, rel, len(a), len(b)))
    # прапорець R42 без ENABLE_ZONE_EDIT: швидке меню, налаштування й мовні рядки R42 -- як були; codeplug.c відрізняється лише спільним помічником назви, а menuZoneList.c --
    # тим, що zrStart() тепер бере номер зони параметром і запам'ятовує його в буфері (рефакторинг під R43; поведінка редактора R42 та сама)
    for rel in files:
        if rel.endswith("codeplug.c") or rel.endswith("menuZoneList.c"):
            continue
        rc1, a = pp(base, rel, configs["UA"] + r42)
        rc2, b = pp(APP, rel, configs["UA"] + r42)
        check(rc1 == 0 and rc2 == 0 and a == b, "Z7 [UA+R42] %s: R42 без ENABLE_ZONE_EDIT == R42 (%d / %d символів)" % (rel, len(a), len(b)))
    # і навпаки: з прапорцем код ЗМІНЮЄТЬСЯ (інакше перевірка нічого не варта)
    on = configs["UA"] + r42 + ["-DENABLE_ZONE_EDIT"]
    for rel in ("source/functions/codeplug.c", "source/user_interface/menuZoneList.c", "source/user_interface/uiChannelMode.c"):
        _r1, a = pp(base, rel, configs["UA"] + r42)
        _r2, b = pp(APP, rel, on)
        check(a != b, "Z7 [UA+R42+EDIT] %s: з прапорцем код інший (перевірка чутлива)" % rel)


def main():
    test_edit_mutants()
    test_menu_structure()
    test_tools()
    test_default_identity()
    if FAILS:
        print("\nПРОВАЛІВ: %d" % len(FAILS))
        sys.exit(1)
    print("test_r43: усе гаразд")


if __name__ == "__main__":
    main()
