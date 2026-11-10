#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R81 (хост, без заліза): переноси пунктів меню рації. Перевіряє ВИХІДНИЙ КОД (меню малюються лише на залізі):
  1  «Опції рації»: немає пунктів SMS монітор / SMS підтв. / Затр.шуму / Мін.гучн.; в enum лишились стокові + (VOLUME_PROBE) діагностика;
  2  «Звук»: «Затр.шуму» -- ОСТАННІЙ пункт enum (індекси QuickKey стокових пунктів ті самі), те саме поле (nonVolatileSettings.UNUSED_1), ті самі
     функції sql_open_delay.h, усі згадки під #if SQL_OPEN_DELAY_ENABLED, без голосової підказки (поле поза діапазоном);
  3  «Повідомлення»: «SMS монітор» -> BIT_SMS_MONITOR_ALL, «SMS підтв.» -> dmrSmsTxMode()/dmrSmsTxModeSet() (ті самі місця збереження, що й до R81);
  4  розділення DMR/APRS: меню/рядки APRS не мають «SMS» і не читають налаштувань SMS DMR; рядки SMS DMR не мають «APRS» (крім підпису відправника
     повідомлення DMR з прапорцем APRS); BIT_SMS_MONITOR_ALL читає лише dmr_sms.c (+ меню «Повідомлення»);
  5  біти не перенумеровано: BIT_SMS_MONITOR_ALL = банк 0, біт 2; BIT_SMS_FONT_SMALL = банк 0, біт 29; UNUSED_1 є в settingsStruct_t;
  6  «Шрифт SMS» в українській збірці не налаштовується (R19 Е5): UI_SMS_FONT_SMALL() = false, пункт лише !LANGUAGE_BUILD_UKRAINIAN, дубля в «Повідомленнях» немає;
  7  мутанти: кожна перевірка має ловити зламаний варіант тексту.
Запуск: python3 tools/test_r81.py"""
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)
APP = os.path.join(FW, "application")
UI = os.path.join(APP, "source", "user_interface")
LANG = os.path.join(APP, "include", "user_interface", "languages")
FAILS = []
N = [0]


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m)
        print("ПРОВАЛ: " + m)


def rd(p):
    b = open(p, "rb").read()
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("cp1251")


def enum_items(text, first_re):
    """Імена пунктів першого enum, у якому є first_re (з вкладеними #if -- ім'я береться як є)."""
    m = re.search(r"enum\s*\{(.*?)\};", text, re.S)
    while m:
        if re.search(first_re, m.group(1)):
            body = re.sub(r"/\*.*?\*/|//[^\n]*", "", m.group(1), flags=re.S)
            return [x for x in re.findall(r"^\s*([A-Z][A-Z0-9_]+)", body, re.M)]
        m = re.search(r"enum\s*\{(.*?)\};", text[m.end():], re.S) if False else None
    return []


def literals(text):
    return re.findall(r'"((?:[^"\\\n]|\\.)*)"', text)


def unguarded(text, needle, guard):
    """Рядки з needle поза #if, що містить guard (стек умов)."""
    stack, bad = [], []
    for i, l in enumerate(text.split("\n"), 1):
        s = l.strip()
        if s.startswith("#if"):
            stack.append(guard in s)
        elif s.startswith("#else") or s.startswith("#elif"):
            if stack:
                stack[-1] = guard in s
        elif s.startswith("#endif"):
            if stack:
                stack.pop()
        elif re.search(needle, l) and not any(stack) and not s.startswith(("/*", "*", "//")):
            bad.append(i)
    return bad


def check_radio(t):
    ok = re.search(r"SMS|SQL_OPEN_DELAY|sqlOpenDelay|VOL_LOW|VOLUME_LOW|volumeLow|vollow|MSGS_SET_|BIT_SMS_MONITOR_ALL|dmrSmsTxMode", re.sub(r"/\*.*?\*/|//[^\n]*", "", t, flags=re.S)) is None
    return ok


def check_sound(t):
    items = enum_items(t, r"OPTIONS_MENU_TIMEOUT_BEEP")
    last_ok = len(items) >= 2 and items[-1] == "NUM_SOUND_MENU_ITEMS" and items[-2] == "OPTIONS_SQL_OPEN_DELAY"
    uses = ("sqlOpenDelaySteps(nonVolatileSettings.UNUSED_1)" in t and "sqlOpenDelayStepsInc(" in t and "sqlOpenDelayStepsDec(" in t
            and "sqlOpenDelayPack(" in t and "currentLanguage->sql_open_delay;" in t and "sqlDelayNoPrompt = true;" in t and "SQL_OPEN_DELAY_STEP_MS" in t)
    guarded = not unguarded(t, r"OPTIONS_SQL_OPEN_DELAY|sqlOpenDelay|sqlDelayNoPrompt", "SQL_OPEN_DELAY_ENABLED")
    return last_ok and uses and guarded


def check_msgs(t):
    return ("BIT_SMS_MONITOR_ALL" in t and "dmrSmsTxModeSet(" in t and "dmrSmsTxMode()" in t and "settingsSaveIfNeeded(true)" in t
            and re.search(r"case MSGS_HOME_SET_MONITOR:\s*\{\s*bool on = settingsIsOptionBitSet\(BIT_SMS_MONITOR_ALL\)", t) is not None
            and "MSGS_SET_MONITOR" in t and "MSGS_SET_TXCONF" in t and "BIT_SMS_FONT_SMALL" not in t and "MSGS_SET_FONT" not in t)


def main():
    radio = rd(os.path.join(UI, "menuRadioOptions.c"))
    sound = rd(os.path.join(UI, "menuSoundOptions.c"))
    msgs = rd(os.path.join(UI, "menuMessages.c"))
    disp = rd(os.path.join(UI, "menuDisplayOptions.c"))
    ua = rd(os.path.join(LANG, "messages_ua.h"))

    # 1
    check(check_radio(radio), "«Опції рації»: немає пунктів SMS/Затр.шуму/Мін.гучн. (поза коментарями)")
    check(not check_radio(radio + "\n#if defined(SQL_OPEN_DELAY_ENABLED)\ncase RADIO_OPTIONS_MENU_SQL_OPEN_DELAY:\n#endif\n"), "мутант: «Затр.шуму» знову в «Опціях рації» ловиться")
    check(not check_radio(radio + "\nx = BIT_SMS_MONITOR_ALL;\n"), "мутант: SMS-біт у «Опціях рації» ловиться")
    items = enum_items(radio, r"RADIO_OPTIONS_MENU_TX_FREQ_LIMITS")
    check(items[:1] == ["RADIO_OPTIONS_MENU_TX_FREQ_LIMITS"] and items[-1] == "NUM_RADIO_OPTIONS_MENU_ITEMS", "«Опції рації»: enum розібрано (%d пунктів)" % len(items))
    check(not [x for x in items if re.search(r"SMS|SQL|VOL_LOW", x)], "«Опції рації»: в enum немає SMS/SQL/VOL_LOW")
    check(items[-2] in ("RADIO_OPTIONS_MENU_VOL_PROBE", "RADIO_OPTIONS_MENU_DMR_CRC", "RADIO_OPTIONS_MENU_FORCE_10W"), "«Опції рації»: стокові пункти не зсунуто (хвіст: %s)" % items[-2])

    # 2
    check(check_sound(sound), "«Звук»: «Затр.шуму» останній, ті самі поле/функції, під #if, без голосової підказки")
    check(not check_sound(sound.replace("nonVolatileSettings.UNUSED_1", "nonVolatileSettings.UNUSED_2")), "мутант: інше поле ловиться")
    check(not check_sound(sound.replace("\tOPTIONS_SQL_OPEN_DELAY,", "\tOPTIONS_SQL_OPEN_DELAY_X,\n\tOPTIONS_AUDIO_DMR_RX_AGC_Y,\n\tOPTIONS_SQL_OPEN_DELAY,", 1) if False else sound.replace("#endif\n#if defined(SQL_OPEN_DELAY_ENABLED)\n\tOPTIONS_SQL_OPEN_DELAY,", "#endif\n\tOPTIONS_SQL_OPEN_DELAY,\n#if defined(ENABLE_CALL_REPLAY)\n\tOPTIONS_EXTRA,\n#endif\n#if defined(SQL_OPEN_DELAY_ENABLED)\n", 1)), "мутант: пункт не останній ловиться")
    check(not check_sound(sound.replace("sqlDelayNoPrompt = true;", "")), "мутант: голосова підказка за межами діапазону ловиться")
    sitems = enum_items(sound, r"OPTIONS_MENU_TIMEOUT_BEEP")
    stock = ["OPTIONS_MENU_TIMEOUT_BEEP", "OPTIONS_MENU_BEEP_VOLUME", "OPTIONS_MENU_DMR_BEEP", "OPTIONS_MENU_RX_BEEP", "OPTIONS_MENU_RX_TALKER_BEGIN_BEEP",
             "OPTIONS_MIC_GAIN_DMR", "OPTIONS_MIC_GAIN_FM", "OPTIONS_VOX_THRESHOLD", "OPTIONS_VOX_TAIL", "OPTIONS_AUDIO_PROMPT_MODE", "OPTIONS_AUDIO_DMR_RX_AGC"]
    check(sitems[:len(stock)] == stock, "«Звук»: порядок стокових пунктів не змінено (QuickKey)")

    # 3
    check(check_msgs(msgs), "«Повідомлення»: SMS монітор -> BIT_SMS_MONITOR_ALL, SMS підтв. -> dmrSmsTxMode/Set, збереження одразу, без шрифту")
    check(not check_msgs(msgs.replace("BIT_SMS_MONITOR_ALL", "BIT_SMS_FONT_SMALL")), "мутант: інший біт ловиться")
    check(not check_msgs(msgs.replace("dmrSmsTxModeSet(", "dmrSmsTxModeSetX(")), "мутант: інше місце збереження режиму TX ловиться")
    check(not check_msgs(msgs + "\nx = MSGS_SET_FONT;\n"), "мутант: дубль шрифту в «Повідомленнях» ловиться")
    check("MSGS_HOME_SET_MONITOR 3" in msgs and "MSGS_HOME_SET_TXMODE  4" in msgs, "«Повідомлення»: рядки налаштувань після Нове/Вхідні/Надіслані")
    for k, v in (("MSGS_SET_MONITOR", "SMS"), ("MSGS_SET_TXCONF", "SMS")):
        m = re.search(r'#define\s+%s\s+"([^"]*)"' % k, ua)
        check(m is not None and v in m.group(1), "messages_ua.h: %s містить «SMS»" % k)

    # 4
    aprs_files = sorted(glob.glob(os.path.join(LANG, "aprs*_ua.h")) + glob.glob(os.path.join(UI, "menuAprs*.c")) + glob.glob(os.path.join(UI, "menuAPRS*.c"))
                        + glob.glob(os.path.join(APP, "source", "functions", "aprs*.c")))
    check(len(aprs_files) >= 8, "знайдено файли APRS (%d)" % len(aprs_files))
    for p in aprs_files:
        t = rd(p)
        n = os.path.basename(p)
        check(not [l for l in literals(t) if re.search(r"SMS", l)], "%s: у рядках APRS немає «SMS»" % n)
        check(re.search(r"BIT_SMS_MONITOR_ALL|dmrSmsTxMode|MSGS_SET_(MONITOR|TXCONF)", t) is None, "%s: APRS не читає налаштувань SMS DMR" % n)
    dmr_lits = [l for l in literals(ua) + literals(msgs) if "APRS" in l]
    check(dmr_lits == ["APRS"], "рядки SMS DMR не містять «APRS» (крім підпису відправника повідомлення DMR з прапорцем APRS): %r" % dmr_lits)
    check([l for l in literals("x = \"Повідом. APRS\";") if "APRS" in l] != ["APRS"], "мутант: APRS-рядок у SMS DMR ловиться")
    readers = []
    for dp, _, fs in os.walk(os.path.join(APP, "source")):
        for f in fs:
            if f.endswith(".c") and "BIT_SMS_MONITOR_ALL" in rd(os.path.join(dp, f)):
                readers.append(f)
    check(sorted(readers) == ["dmr_sms.c", "menuMessages.c"], "BIT_SMS_MONITOR_ALL читають лише dmr_sms.c і меню «Повідомлення»: %r" % sorted(readers))

    # 5
    st = rd(os.path.join(APP, "include", "functions", "settings.h"))
    check(re.search(r"BIT_SMS_MONITOR_ALL\s*=\s*\(SETTINGS_BITS_BANK_0 \| \(1 << 2\)\)", st) is not None, "BIT_SMS_MONITOR_ALL = банк 0, біт 2 (не перенумеровано)")
    check(re.search(r"BIT_SMS_FONT_SMALL\s*=\s*\(SETTINGS_BITS_BANK_0 \| \(1 << 29\)\)", st) is not None, "BIT_SMS_FONT_SMALL = банк 0, біт 29 (не перенумеровано)")
    check(re.search(r"\bUNUSED_1\b", st) is not None, "settingsStruct_t: поле UNUSED_1 на місці")

    # 6
    check(re.search(r"#if defined\(LANGUAGE_BUILD_UKRAINIAN\)\s*\n#define UI_USES_DOUBLE_HEIGHT\(\)\s+\(false\)\s*\n#define UI_SMS_FONT_SMALL\(\)\s+\(false\)", st) is not None, "українська збірка: UI_SMS_FONT_SMALL() = false (шрифт SMS завжди великий)")
    check(re.search(r"#if defined\(ENABLE_AES\) && defined\(ENABLE_DMR_DATA\) && !defined\(LANGUAGE_BUILD_UKRAINIAN\)\s*\n#define DISPLAY_HAS_SMS_FONT 1", disp) is not None, "«Дисплей»: пункт «Шрифт SMS» лише в неукраїнських збірках")

    if FAILS:
        print("test_r81: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
        return 1
    print("test_r81: усе гаразд (%d перевірок)" % N[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
