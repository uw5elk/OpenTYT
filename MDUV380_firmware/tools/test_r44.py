#!/usr/bin/env python3
"""R44 -- єдиний розділ «Кодплаг» у меню рації + контакти. Перевірки без рації й без ARM-тулчейну (потрібен лише gcc).

Z1  макро-матриця (gcc -E -dM): CODEPLUG_MENU_ENABLED лише коли є ENABLE_CODEPLUG_MENU І видалення каналу І редагування зон; швидкі пункти меню каналу
    (CH_QUICKMENU_*) зникають саме тоді; без прапорця R41-R43 лишаються як були.
Z2  структура меню (текстові перевірки + мутанти): пункт «Кодплаг» одразу після «Деталей каналу», 3 підпункти, нові ID меню в кінці переліку (швидкі клавіші користувача
    не зсуваються), «#» і «Нова зона» зникли з РОБОЧОГО списку зон, видалення/виймання зі швидкого меню каналу прибрано.
Z3  видалення контакту (tests/test_codeplug_contact.c з мутованим codeplug.c): каскад по каналах, лічильник, стирання слота, збої запису.
Z4  екрани контактів: підтвердження показує «У каналах: N», каскад по VFO, відмова від 16 символів із кінцевою «я».
Z5  CSV-коло: кодплаг після видалення контакту (канал без контакту) проходить експорт -> імпорт байт-у-байт.
Z7  (за бажанням, змінна R44_BASE=<каталог application версії R43>) без ENABLE_CODEPLUG_MENU збірка після препроцесора ідентична R43 (де це не торкається рефакторингу).
Запуск: `python3 tools/test_r44.py`."""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.abspath(os.path.join(HERE, ".."))
APP = os.path.join(FW, "application")
sys.path.insert(0, HERE)

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


def rd(rel):
    return read(os.path.join(APP, rel))


FW_INCS = ["-I%s/tools/hoststub" % FW, "-include", "%s/tools/hoststub/host_compat.h" % FW, "-I%s" % FW, "-I%s/Core/Inc" % FW,
           "-I%s/Drivers/CMSIS/Device/ST/STM32F4xx/Include" % FW, "-I%s/Drivers/CMSIS/Include" % FW,
           "-I%s/Drivers/STM32F4xx_HAL_Driver/Inc" % FW, "-I%s/Drivers/STM32F4xx_HAL_Driver/Inc/Legacy" % FW,
           "-I%s/Middlewares/ST/STM32_USB_Device_Library/Class/CDC/Inc" % FW, "-I%s/Middlewares/ST/STM32_USB_Device_Library/Core/Inc" % FW,
           "-I%s/Middlewares/Third_Party/FreeRTOS/Source/CMSIS_RTOS_V2" % FW, "-I%s/Middlewares/Third_Party/FreeRTOS/Source/include" % FW,
           "-I%s/Middlewares/Third_Party/FreeRTOS/Source/portable/GCC/ARM_CM4F" % FW, "-I%s/USB_DEVICE/App" % FW, "-I%s/USB_DEVICE/Target" % FW]
COMMON = ["-DUSE_HAL_DRIVER", "-DSTM32F405xx", "-DPLATFORM_MDUV380", "-DPLATFORM_VARIANT_UV380_PLUS_10W", "-DNDEBUG", "-DGITVERSION=x"]
UA = ["-DENABLE_AES", "-DENABLE_DMR_DATA", "-DLANGUAGE_BUILD_UKRAINIAN", "-DENABLE_CALL_REPLAY", "-DENABLE_APRS_RX"]
R41 = ["-DENABLE_CHANNEL_DELETE"]
R42 = ["-DENABLE_SQL_OPEN_DELAY", "-DENABLE_ZONE_RENAME"]
R43 = ["-DENABLE_ZONE_EDIT"]
R44 = ["-DENABLE_CODEPLUG_MENU"]


# ------------------------------------------------------------------------------------------ Z1: макроси
def macros(extra):
    """Які з потрібних макросів визначені після препроцесора для codeplug.h."""
    src = '#include "functions/codeplug.h"\n'
    with tempfile.TemporaryDirectory() as t:
        f = os.path.join(t, "m.c")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(src)
        cmd = ["gcc", "-E", "-dM", "-std=gnu11"] + COMMON + extra + FW_INCS + ["-I%s/include" % APP, f]
        r = subprocess.run(cmd, capture_output=True, text=True)
    names = set()
    for line in r.stdout.splitlines():
        m = re.match(r"#define (\w+)", line)
        if m:
            names.add(m.group(1))
    return r.returncode, {n: (n in names) for n in ("CODEPLUG_MENU_ENABLED", "CH_QUICKMENU_DELETE_ENABLED", "CH_QUICKMENU_ZONE_REMOVE_ENABLED",
                                                   "CHANNEL_DELETE_ENABLED", "ZONE_EDIT_ENABLED")}


def test_macros():
    cases = [
        ("R41+R42+R43 без прапорця меню", UA + R41 + R42 + R43, dict(CODEPLUG_MENU_ENABLED=False, CH_QUICKMENU_DELETE_ENABLED=True, CH_QUICKMENU_ZONE_REMOVE_ENABLED=True)),
        ("усе + ENABLE_CODEPLUG_MENU", UA + R41 + R42 + R43 + R44, dict(CODEPLUG_MENU_ENABLED=True, CH_QUICKMENU_DELETE_ENABLED=False, CH_QUICKMENU_ZONE_REMOVE_ENABLED=False)),
        ("прапорець меню без редагування зон (R41 + меню)", UA + R41 + R44, dict(CODEPLUG_MENU_ENABLED=False, CH_QUICKMENU_DELETE_ENABLED=True, CH_QUICKMENU_ZONE_REMOVE_ENABLED=False)),
        ("прапорець меню без видалення каналу (R43 + меню)", UA + R42 + R43 + R44, dict(CODEPLUG_MENU_ENABLED=False, CH_QUICKMENU_DELETE_ENABLED=False, CH_QUICKMENU_ZONE_REMOVE_ENABLED=True)),
        ("лише меню", UA + R44, dict(CODEPLUG_MENU_ENABLED=False, CH_QUICKMENU_DELETE_ENABLED=False, CH_QUICKMENU_ZONE_REMOVE_ENABLED=False)),
        ("типова збірка (без AES)", [], dict(CODEPLUG_MENU_ENABLED=False, CH_QUICKMENU_DELETE_ENABLED=False, CH_QUICKMENU_ZONE_REMOVE_ENABLED=False)),
    ]
    for title, flags, want in cases:
        rc, got = macros(flags)
        bad = {k: (got.get(k), v) for k, v in want.items() if got.get(k) != v}
        check(rc == 0 and not bad, "Z1: %s -- макроси як треба (розбіжності: %r)" % (title, bad))


# ------------------------------------------------------------------------------------------ Z2: структура меню
def menu_problems(sys_c, sys_h, disp, zl, chm):
    """R46: розділ «Кодплаг» розформовано -- «Зона» (MENU_ZONE_LIST), «Канали», «Контакти» стоять у головному меню. Перевіряємо місце, склад, ID, прибрані швидкі пункти."""
    p = []
    m = re.search(r"\{\s*3,\s*MENU_ZONE_LIST\s*\},\s*\n#if defined\(CODEPLUG_MENU_ENABLED\)\n(?:\s*//[^\n]*\n)*\s*\{ \(int\)\(offsetof\(stringsTable_t, cp_channels\) / LANGUAGE_TEXTS_LENGTH\), MENU_CODEPLUG_CHANNELS \},\n#endif\s*\n\s*\{\s*6,\s*MENU_CONTACTS_MENU\s*\},\s*\n#if !defined\(CODEPLUG_MENU_ENABLED\)\n(?:\s*//[^\n]*\n)*\s*\{\s*12,\s*MENU_CHANNEL_DETAILS\s*\},\s*\n#endif", sys_c)
    if not m:
        p.append("головне меню не в порядку «Зона», «Канали», «Контакти» (або «Канали» не під CODEPLUG_MENU_ENABLED, або «Канал» (MENU_CHANNEL_DETAILS) не під #if !defined(CODEPLUG_MENU_ENABLED))")
    for name, text in (("menuSystem.c", sys_c), ("menuSystem.h", sys_h), ("menuDisplayMenuList.c", disp), ("menuZoneList.c", zl)):
        if re.search(r"\bMENU_CODEPLUG\b|MENU_CODEPLUG_ZONES|menuDataCodeplug|codeplug_menu", text):
            p.append("у %s лишилась згадка розформованого розділу «Кодплаг» (MENU_CODEPLUG / MENU_CODEPLUG_ZONES / menuDataCodeplug / codeplug_menu)" % name)
    if not re.search(r"MENU_COLOUR_PICKER,\s*\n#endif\s*\n#if defined\(CODEPLUG_MENU_ENABLED\)\n\s*MENU_CODEPLUG_CHANNELS,[^\n]*\n#endif\s*\n(?:#if defined\(ENABLE_ROAM_RETRY\)\n[^\n]*MENU_ROAM,[^\n]*\n#endif\s*\n)?\s*NUM_MENU_ENTRIES", sys_h) and \
            not re.search(r"MENU_CODEPLUG_CHANNELS,[^\n]*\n#endif\s*\n(?:#if defined\(ENABLE_ROAM_RETRY\)\n[^\n]*MENU_ROAM,[^\n]*\n#endif\s*\n)?\s*NUM_MENU_ENTRIES", sys_h):
        p.append("нове ID меню не в самому кінці переліку (швидкі клавіші користувача зсунулись би; R59: після «Каналів» дозволено лише MENU_ROAM під ENABLE_ROAM_RETRY)")
    if "menuCodeplugChannels,     NULL, NULL, 0 },// R46" not in sys_c:
        p.append("«Канали» не зареєстровані в menuFunctions[]")
    if not re.search(r"\[MENU_CODEPLUG_CHANNELS\] = NULL", sys_c):
        p.append("«Канали» не мають ЯВНОГО індексу в menuDataGlobal.data[]")
    if "<= 31" not in disp or "CODEPLUG_MENU_ENABLED" not in disp:
        p.append("SK2+цифра на пункті з ID > 31 («Канали») не захищена: QuickKey записав би ID & 0x1F -- швидку клавішу на чуже меню")
    if "#if defined(ZONE_RENAME_ENABLED) && !defined(CODEPLUG_MENU_ENABLED)" not in zl:
        p.append("«#» у списку зон не вимкнено в збірці з ENABLE_CODEPLUG_MENU")
    if "#if defined(ZONE_EDIT_ENABLED) && !defined(CODEPLUG_MENU_ENABLED)" not in zl:
        p.append("«#»-дії над зоною в setZoneToUserSelection не вимкнено")
    if "return s_zoneMapCount + (ZL_EDIT() ? 1 : 0);" not in zl:
        p.append("«Нова зона» зникла зі списку зон")
    if "#define ZE_ACTIONS_COUNT 4" not in zl:
        p.append("дій над зоною не чотири (Встановити / Перейменувати / Канали зони / Видалити)")
    am = re.search(r"static const char \*zeActionLabel\(int i\)\n\{\n#if defined\(CODEPLUG_MENU_ENABLED\)\n(?:\s*//[^\n]*\n)*\s*return \(i == 0\) \? currentLanguage->cp_set_zone : \(\(i == 1\) \? currentLanguage->cp_rename : \(\(i == 2\) \? currentLanguage->cp_zone_chans : currentLanguage->cp_delete\)\);", zl)
    if not am:
        p.append("підписи дій над зоною не в порядку «Встановити», «Перейменувати», «Канали зони», «Видалити»")
    se = re.search(r"static void zeSetActive\(int zn\)\n\{.*?\n\}\n", zl, re.S)
    if not se or "setZoneToUserSelection();" not in se.group(0) or "currentLanguage->zone_empty" not in se.group(0):
        p.append("«Встановити» не викликає наявний setZoneToUserSelection() (або не відсікає порожню зону)")
    elif se.group(0).count("settingsSet(") != 0:
        p.append("«Встановити» дублює код вибору зони замість виклику setZoneToUserSelection()")
    if "zeSetActive(zn);   // R46: «Всі канали»" not in zl:
        p.append("«Всі канали» не встановлюється одразу")
    if "#if defined(CH_QUICKMENU_DELETE_ENABLED)\n	CH_SCREEN_QUICK_MENU_DELETE" not in sys_h:
        p.append("пункт швидкого меню «Видалити канал» не під CH_QUICKMENU_DELETE_ENABLED")
    if "#if defined(CH_QUICKMENU_ZONE_REMOVE_ENABLED)\n	CH_SCREEN_QUICK_MENU_ZONE_REMOVE" not in sys_h:
        p.append("пункт швидкого меню «Вийняти із зони» не під CH_QUICKMENU_ZONE_REMOVE_ENABLED")
    # у швидкому меню каналу жодних згадок видалення/виймання поза цими двома макросами
    stripped = re.sub(r"#if defined\(CH_QUICKMENU_(DELETE|ZONE_REMOVE)_ENABLED\).*?#endif[^\n]*", "", chm, flags=re.S)
    if re.search(r"CH_SCREEN_QUICK_MENU_(DELETE|ZONE_REMOVE)", stripped):
        p.append("швидке меню каналу згадує видалення/виймання поза умовою CH_QUICKMENU_*")
    return p


def test_menu_structure():
    sys_c = rd("source/user_interface/menuSystem.c")
    sys_h = rd("include/user_interface/menuSystem.h")
    disp = rd("source/user_interface/menuDisplayMenuList.c")
    zl = rd("source/user_interface/menuZoneList.c")
    chm = rd("source/user_interface/uiChannelMode.c")
    pr = menu_problems(sys_c, sys_h, disp, zl, chm)
    check(pr == [], "Z2: головне меню «Зона/Канали/Контакти» -- місце, склад, ID, дії, прибрані швидкі пункти: %r" % pr)
    mutants = [
        ("«Канали» прибрано з головного меню", "c", "	{ (int)(offsetof(stringsTable_t, cp_channels) / LANGUAGE_TEXTS_LENGTH), MENU_CODEPLUG_CHANNELS },\n", ""),
        ("«Канали» переставлено після «Контактів»", "c", "	{ (int)(offsetof(stringsTable_t, cp_channels) / LANGUAGE_TEXTS_LENGTH), MENU_CODEPLUG_CHANNELS },\n#endif\n	{   6, MENU_CONTACTS_MENU   },\n",
         "#endif\n	{   6, MENU_CONTACTS_MENU   },\n	{ (int)(offsetof(stringsTable_t, cp_channels) / LANGUAGE_TEXTS_LENGTH), MENU_CODEPLUG_CHANNELS },\n"),
        ("«Контакти» прибрано з головного меню", "c", "	{   6, MENU_CONTACTS_MENU   },\n#if !defined(CODEPLUG_MENU_ENABLED)\n", "#if !defined(CODEPLUG_MENU_ENABLED)\n"),
        ("розділ «Кодплаг» повернули (MENU_CODEPLUG)", "c", "	{   3, MENU_ZONE_LIST       },\n#if defined(CODEPLUG_MENU_ENABLED)\n", "	{   3, MENU_ZONE_LIST       },\n	{ 1, MENU_CODEPLUG },\n#if defined(CODEPLUG_MENU_ENABLED)\n"),
        ("«Нова зона» прибрано зі списку", "zl", "return s_zoneMapCount + (ZL_EDIT() ? 1 : 0);", "return s_zoneMapCount;"),
        ("«#» повернули в список зон", "zl", "#if defined(ZONE_RENAME_ENABLED) && !defined(CODEPLUG_MENU_ENABLED)", "#if defined(ZONE_RENAME_ENABLED)"),
        ("«Встановити» не викликає setZoneToUserSelection", "zl", "	menuDataGlobal.currentItemIndex = zoneMapIndexForZone(zn);\n	setZoneToUserSelection();\n", "	menuDataGlobal.currentItemIndex = zoneMapIndexForZone(zn);\n"),
        ("«Встановити» дублює вибір зони", "zl", "	menuDataGlobal.currentItemIndex = zoneMapIndexForZone(zn);\n	setZoneToUserSelection();\n", "	settingsSet(nonVolatileSettings.currentZone, (int16_t) zn);\n	setZoneToUserSelection();\n"),
        ("«Встановити» не на першому місці", "zl", "return (i == 0) ? currentLanguage->cp_set_zone : ((i == 1) ? currentLanguage->cp_rename", "return (i == 1) ? currentLanguage->cp_set_zone : ((i == 0) ? currentLanguage->cp_rename"),
        ("захист швидкої клавіші ID > 31 прибрано", "d", " && (menuDataGlobal.currentMenuList[menuDataGlobal.currentItemIndex].menuNum <= 31))", ")"),
        ("«Видалити канал» повернули у швидке меню", "h", "#if defined(CH_QUICKMENU_DELETE_ENABLED)\n	CH_SCREEN_QUICK_MENU_DELETE", "#if defined(CHANNEL_DELETE_ENABLED)\n	CH_SCREEN_QUICK_MENU_DELETE"),
    ]
    for title, which, old, new in mutants:
        src = {"c": sys_c, "h": sys_h, "zl": zl, "d": disp}[which]
        if src.count(old) != 1:
            check(False, "Z2: мутант «%s»: шаблон знайдено %d раз(ів), треба 1 (код змінився -- онови мутант)" % (title, src.count(old)))
            continue
        mut = src.replace(old, new)
        args = dict(c=sys_c, h=sys_h, zl=zl, d=disp)
        args[which] = mut
        pr = menu_problems(args["c"], args["h"], args["d"], args["zl"], chm)
        check(pr != [], "Z2: мутант «%s» -- перевірка ловить" % title)


# ------------------------------------------------------------------------------------------ Z3: мутанти видалення контакту
CONTACT_CFLAGS = ["-O1", "-w", "-std=gnu11", "-funsigned-char", "-DUSE_HAL_DRIVER", "-DSTM32F405xx", "-DPLATFORM_MDUV380", "-DPLATFORM_VARIANT_UV380_PLUS_10W", "-DNDEBUG",
                  "-DLANGUAGE_BUILD_UKRAINIAN", "-DENABLE_AES", "-DENABLE_APRS_RX", "-DENABLE_ZONE_RENAME", "-DENABLE_ZONE_EDIT", "-DENABLE_CHANNEL_DELETE", "-DENABLE_CODEPLUG_MENU"]


def run_contact(tmp, codeplug_c):
    src_c = os.path.join(tmp, "codeplug.c")
    with open(src_c, "w", encoding="utf-8") as f:
        f.write(codeplug_c)
    exe = os.path.join(tmp, "t")
    fx = [os.path.join(APP, "source", "functions", n) for n in ("aprs_rx_parse.c", "aprs_mode_cfg.c", "dmr_sms_text.c")]
    cmd = (["gcc"] + CONTACT_CFLAGS + FW_INCS + ["-I%s/include" % APP, "-I%s/source/functions" % APP, "-o", exe,
           os.path.join(FW, "tests", "test_codeplug_contact.c"), src_c] + fx + ["-lm"])
    cp = subprocess.run(cmd, capture_output=True, text=True)
    if cp.returncode != 0:
        return False, -1
    return True, subprocess.run([exe], capture_output=True, text=True, timeout=120).returncode


CASCADE_IF = "if (codeplugAllChannelsIndexIsInUse(ch) && (codeplugChannelContactField(ch) == (uint16_t)contactIndex) && !codeplugChannelClearContactField(ch))\n\t\t{\n\t\t\treturn false;"
CONTACT_MUTANTS = [
    ("каскад по каналах забуто (канали лишились б із посиланням на стертий слот)", CASCADE_IF, "if (0)\n\t\t{\n\t\t\treturn false;"),
    ("збій запису каналу в каскаді ігнорується (повертається true)", CASCADE_IF,
     "if (codeplugAllChannelsIndexIsInUse(ch) && (codeplugChannelContactField(ch) == (uint16_t)contactIndex) && (codeplugChannelClearContactField(ch), 0))\n\t\t{\n\t\t\treturn false;"),
    ("каскад чіпає й канали поза маскою (рахує зайві)", "		if (codeplugAllChannelsIndexIsInUse(ch) && (codeplugChannelContactField(ch) == (uint16_t)contactIndex))\n		{\n			n++;",
     "		if ((codeplugChannelContactField(ch) == (uint16_t)contactIndex))\n		{\n			n++;"),
    ("лічильник завищує на 1", "			n++;\n		}\n	}\n	return n;", "			n++;\n		}\n	}\n	return n + 1;"),
    ("у EEPROM-каналі обнуляється лише 1 байт поля «контакт»", "EEPROM_Write(addr, zero, 2)", "EEPROM_Write(addr, zero, 1)"),
    ("у флеш-каналі обнуляється лише 1 байт поля «контакт»", "SPI_Flash_write(FLASH_ADDRESS_OFFSET + addr, zero, 2)", "SPI_Flash_write(FLASH_ADDRESS_OFFSET + addr, zero, 1)"),
    ("слот контакту не стирається повністю (тип лишається)", "	c.callType = 0xff;\n	return codeplugContactSaveDataForIndex", "	return codeplugContactSaveDataForIndex"),
    ("слот стирається ДО каскаду (канали лишаються з посиланням на стертий слот при збої)",
     "	for (int ch = CODEPLUG_CHDEL_CHANNELS_MIN; ch <= CODEPLUG_CHDEL_CHANNELS_MAX; ch++)\n	{\n		if (codeplugAllChannelsIndexIsInUse(ch) && (codeplugChannelContactField(ch) == (uint16_t)contactIndex) && !codeplugChannelClearContactField(ch))",
     "	{ CodeplugContact_t e = c; memset(e.name, 0xff, 16); e.tgNumber = 0; e.callType = 0xff; codeplugContactSaveDataForIndex(contactIndex, &e); }\n	for (int ch = CODEPLUG_CHDEL_CHANNELS_MIN; ch <= CODEPLUG_CHDEL_CHANNELS_MAX; ch++)\n	{\n		if (codeplugAllChannelsIndexIsInUse(ch) && (codeplugChannelContactField(ch) == (uint16_t)contactIndex) && !codeplugChannelClearContactField(ch))"),
]


def test_contact_mutants():
    src = rd("source/functions/codeplug.c")
    with tempfile.TemporaryDirectory() as t0:
        built, rc = run_contact(t0, src)
        check(built and rc == 0, "Z3: немутований codeplug.c -- хост-тест видалення контакту зелений (зібрано=%s, код=%s)" % (built, rc))
    for title, old, new in CONTACT_MUTANTS:
        if src.count(old) != 1:
            check(False, "Z3: мутант «%s»: шаблон знайдено %d раз(ів), треба 1 (код змінився -- онови мутант)" % (title, src.count(old)))
            continue
        with tempfile.TemporaryDirectory() as t:
            built, rc = run_contact(t, src.replace(old, new))
            check(built and rc != 0, "Z3: мутант «%s» -- тест ловить (зібрано=%s, код=%s)" % (title, built, rc))


# ------------------------------------------------------------------------------------------ Z4: екрани контактів
def contact_ui_problems(lst, det):
    p = []
    if "codeplugContactCountChannels(uiDataGlobal.currentSelectedContactIndex)" not in lst:
        p.append("підтвердження не показує, у скількох каналах стоїть контакт")
    if "currentLanguage->cp_becomes_none" not in lst:
        p.append("підтвердження не каже, що в каналах стане «Немає»")
    if "if (!codeplugContactDelete(uiDataGlobal.currentSelectedContactIndex))" not in lst:
        p.append("видалення контакту не через codeplugContactDelete (каскад по каналах)")
    if "settingsVFOChannel[v].contact = 0;" not in lst or "settingsSetVFODirty();" not in lst:
        p.append("каскад не зачіпає обидва VFO")
    if "settingsVFOChannel[v].contact == (uint16_t)uiDataGlobal.currentSelectedContactIndex" not in lst:
        p.append("VFO обнуляється без перевірки, що там саме цей контакт")
    if "(strlen(contactName) == 16U) && (((uint8_t)contactName[15]) == 0xFF)" not in det:
        p.append("нема відмови від 16 символів із кінцевою «я»")
    if "currentLanguage->zone_name_ya" not in det:
        p.append("відмова не пояснена словами")
    return p


def test_contact_ui():
    lst = rd("source/user_interface/menuContactList.c")
    det = rd("source/user_interface/menuContactDetails.c")
    pr = contact_ui_problems(lst, det)
    check(pr == [], "Z4: екрани контактів -- лічильник, каскад VFO, правило «я»: %r" % pr)
    mutants = [
        ("лічильник каналів не показано", "lst", "codeplugContactCountChannels(uiDataGlobal.currentSelectedContactIndex)", "0"),
        ("VFO не обнуляється", "lst", "settingsVFOChannel[v].contact = 0;", "(void)0;"),
        ("видалення без каскаду (стокове стирання)", "lst", "if (!codeplugContactDelete(uiDataGlobal.currentSelectedContactIndex))", "if (0)"),
        ("16 символів із «я» дозволено", "det", "(strlen(contactName) == 16U) && (((uint8_t)contactName[15]) == 0xFF)", "0"),
    ]
    for title, which, old, new in mutants:
        src = lst if which == "lst" else det
        if src.count(old) != 1:
            check(False, "Z4: мутант «%s»: шаблон знайдено %d раз(ів), треба 1" % (title, src.count(old)))
            continue
        mut = src.replace(old, new)
        pr = contact_ui_problems(mut if which == "lst" else lst, mut if which == "det" else det)
        check(pr != [], "Z4: мутант «%s» -- перевірка ловить" % title)


# ------------------------------------------------------------------------------------------ Z5: CSV-коло
def test_csv_roundtrip():
    import cps_csv as cc
    import cps_link as cl
    spi = tc.make_fixture_spi()
    rng = cl.flash_backup_range()
    img = cc.Image(bytearray(spi[:cl.EEPROM_BACKUP_LEN]), bytearray(spi[rng["raw_start"]:rng["raw_start"] + rng["length"]]), rng["codeplug_start"])
    # як робить прошивка (codeplugContactDelete): поле «контакт» усіх каналів із цим контактом -> 0, потім слот контакту стирається 0xFF
    import struct
    victim = None
    for ch, rec in img.channels():
        c = struct.unpack_from("<H", rec, 46)[0]
        if c:
            victim = c
            break
    check(victim is not None, "Z5: у фікстурі є канал із контактом (контакт %r)" % (victim,))
    n = 0
    for ch, rec in img.channels():
        if struct.unpack_from("<H", rec, 46)[0] == victim:
            r = bytearray(rec)
            r[46:48] = b"\x00\x00"
            img.set_channel_rec(ch, bytes(r))
            n += 1
    img.set_contact(victim - 1, b"\xff" * 24)
    spi2 = bytearray(spi)
    spi2[:cl.EEPROM_BACKUP_LEN] = img.eeprom
    spi2[rng["raw_start"]:rng["raw_start"] + rng["length"]] = img.flash
    cp2, _ = tc.codeplug_of(spi2)
    with tempfile.TemporaryDirectory() as d:
        tc.export_dir(cp2, d)
        res = tc.import_dir(cp2, d)
        check(tc.images_equal(res, cp2), "Z5: кодплаг після видалення контакту (%d каналів без контакту) -- експорт -> імпорт БАЙТ-У-БАЙТ" % n)
        check(not res.any_change() and not res.warnings, "Z5: жодної зміни й жодного попередження: %s %r" % (res.summary(), res.warnings))
    check(n >= 1, "Z5: каскад зачепив хоча б один канал (%d)" % n)


# ------------------------------------------------------------------------------------------ Z7: ідентичність з R43
def test_default_identity():
    base = os.environ.get("R44_BASE")
    if not base:
        print("  --   Z7 пропущено: задай R44_BASE=<каталог application версії R43> (git archive <база> MDUV380_firmware/application)")
        return
    files = ["source/functions/trx.c", "source/user_interface/menuRadioOptions.c", "source/user_interface/menuSystem.c", "source/user_interface/uiLocalisation.c",
             "source/user_interface/menuContactList.c", "source/user_interface/menuContactDetails.c", "source/user_interface/menuDisplayMenuList.c"]
    configs = {"AES0": [], "UA": UA, "EN": ["-DENABLE_AES", "-DENABLE_DMR_DATA", "-DENABLE_CALL_REPLAY"],
               "UA+R41+R42+R43": UA + R41 + R42 + R43}

    def pp(appdir, rel, extra):
        fw_incs = [x.replace(FW + "/application/include", appdir + "/include") for x in FW_INCS]
        cmd = ["gcc", "-E", "-P", "-x", "c", "-std=gnu11"] + COMMON + extra + ["-I%s/include" % appdir] + fw_incs + ["-I%s/include" % appdir, os.path.join(appdir, rel)]
        r = subprocess.run(cmd, capture_output=True)
        return r.returncode, re.sub(rb"\s+", b"", r.stdout)
    for cname, extra in configs.items():
        for rel in files:
            rc1, a = pp(base, rel, extra)
            rc2, b = pp(APP, rel, extra)
            check(rc1 == 0 and rc2 == 0 and a == b, "Z7 [%s] %s: без ENABLE_CODEPLUG_MENU == R43 (%d / %d символів)" % (cname, rel, len(a), len(b)))
    # типова збірка (R41-R43 вимкнені): і ці, що рефакторились, теж ідентичні
    for rel in ("source/functions/codeplug.c", "source/user_interface/menuZoneList.c", "source/user_interface/uiChannelMode.c"):
        for cname in ("AES0", "UA", "EN"):
            rc1, a = pp(base, rel, configs[cname])
            rc2, b = pp(APP, rel, configs[cname])
            check(rc1 == 0 and rc2 == 0 and a == b, "Z7 [%s] %s: типова збірка == R43 (%d / %d символів)" % (cname, rel, len(a), len(b)))
    # з прапорцем код ЗМІНЮЄТЬСЯ (інакше перевірка нічого не варта)
    on = UA + R41 + R42 + R43 + R44
    for rel in ("source/user_interface/menuSystem.c", "source/user_interface/menuZoneList.c", "source/user_interface/uiChannelMode.c", "source/user_interface/menuContactList.c"):
        _r1, a = pp(base, rel, UA + R41 + R42 + R43)
        _r2, b = pp(APP, rel, on)
        check(a != b, "Z7 [UA+R41+R42+R43+MENU] %s: з прапорцем код інший (перевірка чутлива)" % rel)


def main():
    test_macros()
    test_menu_structure()
    test_contact_mutants()
    test_contact_ui()
    test_csv_roundtrip()
    test_default_identity()
    if FAILS:
        print("\nПРОВАЛІВ: %d" % len(FAILS))
        sys.exit(1)
    print("test_r44: усе гаразд")


if __name__ == "__main__":
    main()
