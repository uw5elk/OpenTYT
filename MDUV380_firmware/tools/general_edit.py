#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""general_edit.py -- R-next / Y2: «Кодплаг → Загальні налаштування». ЛОГІКА без Tk і без рації.

Тут лише те, що є в кодплазі І справді читається прошивкою. Перелік складено з коду прошивки, а не з пам'яті:

  * пароль на старті: codeplug.c codeplugGetPasswordPin() читає 6 байтів від 0x7519; біт 0 першого байта -- «пароль увімкнено»; цифри PIN --
    3 байти BCD від 0x751C (старший ніббл першим), ніббл 0xF обриває PIN; uiSplashScreen.c питає PIN при кожному вмиканні;
  * тривалості DTMF: codeplug.c codeplugGetSignallingDTMFDurations() читає 5 байтів від 0x1472 (applicationMain.c:567, один раз при старті);
    uiUtilities.c: затримка перед першою цифрою = байт*100 мс, перша цифра = байт*10 мс (0 -- без подовження), «*» і «#» = байт*10 мс,
    тривалість тону й паузи = 1000/(швидкість*2) мс (швидкість 0 -- ділення на нуль, тому заборонена), «хвіст» TX = байт*100 мс
    (прошивка підміняє значення >10 на 5).

Решту 40-байтового блоку «загальних налаштувань» (0x00E0..0x0107: затримки ARS, VOX, таймери тощо) прошивка OpenGD77 НЕ читає
(settings.c:187 -- виклик закоментовано), тож показувати їх означало б обіцяти дію, якої немає. Швидкі клавіші (0x7524) прошивка захищає від
запису з CPS; блок пристрою (0x80) і LUCZ (0x6000) -- службові. Усе це свідомо НЕ показується.

Усі функції беруть cps_csv.Image і повертають cps_csv.ImportResult з НОВИМ образом (вихідний не змінюється).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cps_csv as cc  # noqa: E402
import codeplug_edit as ced  # noqa: E402

ADDR_PWD_FLAGS = 0x7519          # CODEPLUG_ADDR_BOOT_PASSWORD_ENABLE; біт 0 -- пароль увімкнено
ADDR_PWD_PIN = 0x751C            # CODEPLUG_ADDR_BOOT_PASSWORD_AREA: 3 байти BCD
PIN_BYTES = 3
PIN_DIGITS_MAX = 2 * PIN_BYTES
ADDR_DTMF_DURATIONS = 0x1400 + 0x72     # CODEPLUG_ADDR_SIGNALLING_DTMF_DURATIONS

# ключ -> (адреса, мін, макс)
DTMF_FIELDS = (
    ("dtmf_first_delay", 0x1472, 0, 255, "Затримка перед першою цифрою DTMF", 100, "мс"),
    ("dtmf_first_dur", 0x1473, 0, 255, "Тривалість першої цифри DTMF", 10, "мс"),
    ("dtmf_other_dur", 0x1474, 0, 255, "Тривалість «*» і «#»", 10, "мс"),
    ("dtmf_rate", 0x1475, 1, 10, "Швидкість DTMF (цифр за секунду)", 0, ""),
    ("dtmf_tail", 0x1476, 0, 10, "«Хвіст» передачі після DTMF", 100, "мс"),
)

SECTION = "Загальні налаштування"


def field_table():
    """Таблиця «поле -> адреса -> діапазон» (для звіту й для довідки в панелі): [(поле, адреса, діапазон, прошивка)]."""
    rows = [("Пароль при вмиканні (прапорець)", "EEPROM 0x7519, біт 0", "вимк. / увімк.", "codeplugGetPasswordPin, uiSplashScreen"),
            ("PIN-код", "EEPROM 0x751C..0x751E (BCD, 0xF -- кінець)", "1..%d цифр 0-9" % PIN_DIGITS_MAX, "codeplugGetPasswordPin")]
    for key, addr, lo, hi, label, mult, unit in DTMF_FIELDS:
        if mult:
            rng = "%d..%d (одиниця %d %s: %d..%d %s)" % (lo, hi, mult, unit, lo * mult, hi * mult, unit)
        else:
            rng = "%d..%d" % (lo, hi)
        rows.append((label, "EEPROM 0x%04X" % addr, rng, "uiUtilities.c (DTMF), applicationMain.c:567"))
    return rows


def pin_decode(raw3):
    """3 байти -> (рядок цифр, нестандартний?). Нестандартний -- серед нібблів до 0xF є A..E (прошивка їх сприйняла б як числа 10..14)."""
    digits, odd = "", False
    for i in range(PIN_DIGITS_MAX):
        nib = (raw3[i // 2] >> ((1 - (i % 2)) * 4)) & 0x0F
        if nib == 0x0F:
            break
        if nib > 9:
            odd = True
        digits += str(nib) if nib <= 9 else "?"
    return digits, odd


def pin_encode(digits):
    """Рядок цифр 1..6 -> 3 байти (дописка нібблами 0xF)."""
    nibs = [int(c) for c in digits] + [0x0F] * (PIN_DIGITS_MAX - len(digits))
    return bytes((nibs[2 * i] << 4) | nibs[2 * i + 1] for i in range(PIN_BYTES))


def general_values(img):
    """Поточні значення: {pwd_enable, pwd_pin, pwd_pin_odd, dtmf_*: int}. pwd_enable -- «рація справді питатиме PIN»: біт 0 УВІМКНЕНО І в PIN є хоч одна цифра
    (codeplugGetPasswordPin повертає довжину 0, а uiSplashScreen тоді PIN не питає; у порожньому кодплазі 0x7519 = 0xFF, тобто біт піднято, але PIN нема)."""
    pin, odd = pin_decode(img.ee(ADDR_PWD_PIN, PIN_BYTES))
    out = {"pwd_enable": bool(img.ee(ADDR_PWD_FLAGS, 1)[0] & 1) and bool(pin), "pwd_pin": pin, "pwd_pin_odd": odd}
    for key, addr, *_rest in DTMF_FIELDS:
        out[key] = img.ee(addr, 1)[0]
    return out


def check_values(v, keys=None):
    """Проблеми значень форми: {ключ: текст}. Порожній словник -- усе гаразд. keys -- перевіряти лише ці ключі (None -- усі)."""
    bad = {}
    pin = v.get("pwd_pin", "")
    if v.get("pwd_enable"):
        if not pin:
            bad["pwd_pin"] = "потрібен PIN: 1..%d цифр (без PIN рація пароль не питатиме)" % PIN_DIGITS_MAX
    if pin and (not pin.isdigit() or not pin.isascii() or len(pin) > PIN_DIGITS_MAX):
        bad["pwd_pin"] = "PIN -- лише цифри 0-9, до %d знаків" % PIN_DIGITS_MAX
    for key, _addr, lo, hi, label, mult, unit in DTMF_FIELDS:
        if keys is not None and key not in keys:
            continue
        x = v.get(key)
        if not isinstance(x, int) or isinstance(x, bool) or not lo <= x <= hi:
            extra = (", %d..%d %s" % (lo * mult, hi * mult, unit)) if mult else ""
            bad[key] = "ціле число %d..%d%s" % (lo, hi, extra)
    return bad


def apply_general(base_img, **values):
    """Накласти значення (ключі -- як у general_values; відсутній ключ -- поле не чіпати). Байти, що не змінилися, не чіпаються.
    PIN при вимкненому паролі й `pwd_pin=None` не змінюється; при `pwd_pin_odd` у кодплазі PIN лишається, доки його явно не задано."""
    img = cc.Image(base_img.eeprom, base_img.flash, base_img.base)
    res = cc.ImportResult()
    cur = general_values(img)
    new = dict(cur)
    new.update({k: v for k, v in values.items() if k in cur and k != "pwd_pin_odd"})
    pin_given = "pwd_pin" in values
    # перевіряються лише змінені поля: у порожньому кодплазі байти DTMF = 0xFF (поза межами), і це не заважає змінити, скажімо, пароль
    touched = [k for k, _a, *_r in DTMF_FIELDS if new[k] != cur[k]]
    problems = check_values(new if pin_given else dict(new, pwd_pin="1"), keys=touched)
    if not pin_given and new["pwd_enable"] and not cur["pwd_enable"] and (not cur["pwd_pin"] or cur["pwd_pin_odd"]):
        problems["pwd_pin"] = "щоб увімкнути пароль, задайте PIN: 1..%d цифр" % PIN_DIGITS_MAX
    if problems:
        raise ced.CodeplugEditError(["%s: %s" % (k, t) for k, t in problems.items()])

    flags = img.ee(ADDR_PWD_FLAGS, 1)[0]
    new_flags = flags
    if new["pwd_enable"]:
        new_flags = flags | 1
    elif cur["pwd_enable"]:
        new_flags = flags & 0xFE                     # вимкнення -- лише біт 0; PIN лишається (його можна ввімкнути знову)
    if new_flags != flags:
        img.set_ee(ADDR_PWD_FLAGS, bytes([new_flags]))
    if new["pwd_enable"] != cur["pwd_enable"]:
        res.changed.append((SECTION, "пароль при вмиканні: %s" % ("увімкнено" if new["pwd_enable"] else "вимкнено")))
        if new["pwd_enable"]:
            res.warnings.append("Пароль увімкнено: після запису рація питатиме PIN при кожному вмиканні. Запам'ятайте його.")
    if pin_given and new["pwd_pin"] and (new["pwd_pin"] != cur["pwd_pin"] or cur["pwd_pin_odd"]):
        img.set_ee(ADDR_PWD_PIN, pin_encode(new["pwd_pin"]))
        res.changed.append((SECTION, "PIN-код змінено"))
    for key, addr, _lo, _hi, label, *_rest in DTMF_FIELDS:
        if new[key] != cur[key]:
            img.set_ee(addr, bytes([new[key]]))
            res.changed.append((SECTION, "%s: %d -> %d" % (label, cur[key], new[key])))
    res.image = img
    return res
