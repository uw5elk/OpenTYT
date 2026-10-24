#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""theme_edit.py -- R28: теми рації (кольори екрана). ЛОГІКА без Tk: формат блока, стокові значення, готові набори, файл теми, перевірка
читабельності, опис попереднього перегляду і читання/запис блока в рацію. Панель -- cps_ui/p_themes.py.

ЩО ТАКЕ ТЕМА (усе виведено з коду прошивки, не з пам'яті):
  * тема = 32 кольори (THEME_ITEM_MAX у application/include/hardware/HX8353E.h, enum themeItem_t -- порядок у блоці ТАКИЙ САМИЙ);
    денна (CODEPLUG_CUSTOM_DATA_TYPE_THEME_DAY = 4) і нічна (THEME_NIGHT = 5) -- два окремі custom-data блоки по 64 байти;
  * блок лежить у SPI-флеші в «області OpenGD77»: сирі адреси 0x20000 (FLASH_ADDRESS_OFFSET) .. +0x10000; заголовок області --
    "OpenGD77" (12 байтів), далі блоки {int dataType; int dataLength;} + дані (формат і сканування -- custom_data.py);
  * колір = uint16 RGB565 (R у старших 5 бітах), у флеші -- СТАРШИЙ байт першим (big-endian): HX8353E_display.c зберігає
    PLATFORM_COLOUR_FORMAT_SWAP_BYTES(RGB888_TO_PLATFORM_COLOUR_FORMAT(x)), а applicationMain.c для MDUV380 завжди ставить
    DIPLAYLCD_TYPE_RGB (тому не BGR). RGB888 -> RGB565 прошивка робить відкиданням молодших бітів ((R&0xF8)<<8 | (G&0xFC)<<3 | B>>3);
  * themeInit() при старті спершу заповнює обидві теми стоковими значеннями (themeInitToDefaultValues), потім, якщо блок є, копіює
    поверх нього РІВНО 64 байти (memcpy sizeof(themingTmp)) -- тож блок коротший за 64 Б дав би «хвіст» зі сміття стека;
    CPS мусить писати рівно 64. Теми читаються ЛИШЕ при вмиканні рації: після запису її треба вимкнути й увімкнути;
  * довжину наявного блока прошивка (і custom_data.write_block) міняти забороняє; новий блок -- у перший вільний слот області.

ТЕМИ НЕ Є ЧАСТИНОЮ ДОКУМЕНТА КОДПЛАГА: область custom-data лежить ПОЗА EEPROM і поза діапазоном флешу, який відновлює cps_restore
(він починається з ~0x9B000), тому «Записати в рацію» над документом теми не чіпає. Панель пише їх в рацію негайно, тим самим шляхом,
що бікон APRS (custom_data.write_block + звірка читанням). З R30 область custom-data (разом з темами) потрапляє у файл бекапу окремим
файлом і відновлюється окремим прапорцем (custom_region.py).

ФАЙЛ ТЕМИ -- ОФІЦІЙНИЙ ФОРМАТ `.gtm` (стоковий CPS OpenGD77, R30): рівно 64 байти -- вміст блока теми, без заголовка й контрольної суми:
32 значення uint16, порядок як у themeItem_t, RGB565 big-endian. Денна чи нічна -- у файлі НЕ позначено, лише в імені (d.gtm / n.gtm).
Тому `.gtm` = encode_block() напряму (save_gtm/load_gtm), без жодних перетворень. Власний текстовий формат `OpenTYT-theme-1` (to_file_text)
лишено другим варіантом: він читається людиною й несе позначку day/night.

ЗБІГ ІЗ СТОКОВОЮ ТЕМОЮ. Тема в флеші перекриває вбудовану при КОЖНОМУ ввімкненні, тому «стокова» тема на рації може бути збережена
користувачем з будь-якої з двох гілок themeInitToDefaultValues (українська чи класична). match_counts() показує, скільки з 32 елементів
збігаються з кожною з двох таблиць -- обчислено, не вписано.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TYPE_THEME_DAY = 4              # CODEPLUG_CUSTOM_DATA_TYPE_THEME_DAY
TYPE_THEME_NIGHT = 5            # CODEPLUG_CUSTOM_DATA_TYPE_THEME_NIGHT
ITEM_COUNT = 32                 # THEME_ITEM_MAX
BLOCK_LEN = ITEM_COUNT * 2      # 64 байти
DAYTIMES = ("day", "night")
DAYTIME_NAMES = {"day": "Денна", "night": "Нічна"}
TYPE_OF = {"day": TYPE_THEME_DAY, "night": TYPE_THEME_NIGHT}
FILE_FORMAT = "OpenTYT-theme-1"

# (ключ без префікса THEME_ITEM_, коротка назва, що саме фарбує). Порядок -- як у themeItem_t.
ITEMS = (
    ("FG_DEFAULT", "Звичайний текст", "основний текст на тлі екрана"),
    ("BG", "Тло екрана", "загальне тло більшості екранів"),
    ("FG_DECORATION", "Рамки й роздільники", "рамки, лінії між пунктами меню, тіні"),
    ("FG_TEXT_INPUT", "Введення тексту", "текст у полях введення"),
    ("FG_SPLASHSCREEN", "Заставка: текст", "текст екрана вмикання"),
    ("BG_SPLASHSCREEN", "Заставка: тло", "тло екрана вмикання"),
    ("FG_NOTIFICATION", "Сповіщення: текст", "текст сповіщень і смуга шумодава"),
    ("FG_WARNING_NOTIFICATION", "Попередження", "текст попереджень"),
    ("FG_ERROR_NOTIFICATION", "Помилка", "текст повідомлень про помилку"),
    ("BG_NOTIFICATION", "Сповіщення: тло", "тло сповіщень"),
    ("FG_MENU_NAME", "Заголовок меню: текст", "текст назви меню"),
    ("BG_MENU_NAME", "Заголовок меню: тло", "смуга назви меню"),
    ("FG_MENU_ITEM", "Пункти меню", "текст пунктів меню"),
    ("BG_MENU_ITEM_SELECTED", "Виділений пункт: заливка", "заливка виділеного пункту (його текст малюється кольором «Тло екрана»)"),
    ("FG_OPTIONS_VALUE", "Значення налаштувань", "значення в меню опцій, швидкому меню, деталях каналу"),
    ("FG_HEADER_TEXT", "Рядок стану: текст", "режим, потужність, батарея у верхньому рядку каналу/VFO"),
    ("BG_HEADER_TEXT", "Рядок стану: тло", "тло верхнього рядка каналу/VFO"),
    ("FG_RSSI_BAR", "Смуга сигналу до S9", "шкала RSSI до S9"),
    ("FG_RSSI_BAR_S9P", "Смуга сигналу понад S9", "частина шкали RSSI вище S9"),
    ("FG_CHANNEL_NAME", "Назва каналу", "назва каналу на головному екрані"),
    ("FG_CHANNEL_CONTACT", "Контакт (TG/PC)", "назва контакту: група або приват"),
    ("FG_CHANNEL_CONTACT_INFO", "Інфо контакту", "рядок додаткових даних контакту (DB/Ct/TA)"),
    ("FG_ZONE_NAME", "Назва зони", "зона на головному екрані"),
    ("FG_RX_FREQ", "Частота прийому", "частота RX"),
    ("FG_TX_FREQ", "Частота передачі", "частота TX"),
    ("FG_CSS_SQL_VALUES", "Тони й шумодав", "значення CSS і шумодава на екранах каналу/VFO"),
    ("FG_TX_COUNTER", "Таймер передачі", "лічильник часу на екрані передачі"),
    ("FG_POLAR_DRAWING", "Полярна сітка", "сітка на екранах супутників і GPS"),
    ("FG_SATELLITE_COLOUR", "Точки супутників", "супутники на екрані супутників"),
    ("FG_GPS_NUMBER", "Номери GPS", "числа на екрані GPS"),
    ("FG_GPS_COLOUR", "Смуги й точки GPS", "смуги й точки GPS"),
    ("FG_BD_COLOUR", "Смуги й точки BeiDou", "смуги й точки BeiDou"),
)
KEYS = tuple(it[0] for it in ITEMS)
INDEX = {k: i for i, k in enumerate(KEYS)}
assert len(ITEMS) == ITEM_COUNT


# ---------------------------------------------------------------------------------------------------------------------------------
#  Стокові значення: ПОБАЙТОВА копія таблиць themeDefaults у application/source/hardware/HX8353E_display.c (themeInitToDefaultValues),
#  RGB888, у порядку themeItem_t. _UA -- гілка #if defined(LANGUAGE_BUILD_UKRAINIAN) (збірка рації з українською мовою), _CLASSIC -- гілка #else
#  (усі інші мови). Збіг із вихідним кодом перевіряє tools/test_r28.py (коли прошивка поруч).
# ---------------------------------------------------------------------------------------------------------------------------------
_UA = {
    "day": (
        0x000000, 0xFFFFFF, 0x1C1C1C, 0x000000, 0x0A2F44, 0xFFFFFF,
        0x0A3550, 0x804000, 0xC80000, 0xFFFFFF, 0xFFFFFF, 0x0A4A6E,
        0x000000, 0x0A4A6E, 0x0A4A6E, 0x000000, 0xD2DCE3, 0x006400,
        0xC80000, 0x0A4A6E, 0x8C0A00, 0x8C0A00, 0x3F4F5A, 0x000000,
        0xC80000, 0x0A4A6E, 0xC80000, 0x404040, 0x006400, 0x000000,
        0x000078, 0xC80000,
    ),
    "night": (
        0xE8EEF2, 0x05080C, 0x6F8493, 0xE8EEF2, 0x9FD3F0, 0x05080C,
        0x9FD3F0, 0xFFCC55, 0xFF7676, 0x05080C, 0xFFFFFF, 0x1B4F72,
        0xA9D6F0, 0xD8A93F, 0xE3B454, 0xA9D6F0, 0x05080C, 0x33FF33,
        0xFF6A2A, 0x7FD8B5, 0xFFCC55, 0xFFCC55, 0xC5CED5, 0xE8EEF2,
        0xFF7676, 0x7FD8B5, 0xFF7676, 0x86B9D6, 0x7FD8B5, 0xE8EEF2,
        0x93B4FF, 0xFF7676,
    ),
}

_CLASSIC = {
    "day": (
        0x000000, 0xFFFFFF, 0x101010, 0x000000, 0x0D1826, 0xFFFFFF,
        0x00243F, 0x804000, 0xC80000, 0xFFFFFF, 0xFFFFFF, 0x00243F,
        0x000000, 0x00243F, 0x00243F, 0x000000, 0xC4C4C4, 0x006400,
        0xC80000, 0x00243F, 0x8C0A00, 0x8C0A00, 0x7A0000, 0x000000,
        0xC80000, 0x00243F, 0xC80000, 0x404040, 0x006400, 0x000000,
        0x000078, 0xC80000,
    ),
    "night": (
        0xFFFFFF, 0x000000, 0xDADADA, 0xFFFFFF, 0xB8E8FF, 0x000000,
        0xB8E8FF, 0xFFCC55, 0xFF7676, 0x000000, 0xFFFFFF, 0x0E5A88,
        0xB8E8FF, 0xFFA81E, 0xFFCC55, 0xB8E8FF, 0x000000, 0x33FF33,
        0xFF6A2A, 0x33FFA0, 0xFFCC55, 0xFFCC55, 0xE0E0E0, 0xFFFFFF,
        0xFF7676, 0x33FFA0, 0xFF7676, 0xB8E8FF, 0x33FFA0, 0xFFFFFF,
        0x93B4FF, 0xFF7676,
    ),
}

DEFAULT_VARIANT = "ua"
VARIANT_NAMES = {"ua": "Стокова (українська збірка)", "classic": "Класична (збірки іншими мовами)"}
_TABLES = {"ua": _UA, "classic": _CLASSIC}


# ---------------------------------------------------------------------------------------------------------------------------------
#  Кольори: RGB888 <-> RGB565
# ---------------------------------------------------------------------------------------------------------------------------------

def rgb888_to_565(x):
    """Як RGB888_TO_PLATFORM_COLOUR_FORMAT для RGB-дисплея: ((x&0xf80000)>>8) + ((x&0xfc00)>>5) + ((x&0xf8)>>3)."""
    return ((x & 0xF80000) >> 8) + ((x & 0xFC00) >> 5) + ((x & 0xF8) >> 3)


def rgb565_to_888(v):
    """RGB565 -> найближчий RGB888 з добудовою молодших бітів повторенням старших (0xFFFF -> 0xFFFFFF, 0 -> 0). Обернене до
    rgb888_to_565 на всіх 65536 значеннях (перевіряє test_r28)."""
    r5, g6, b5 = (v >> 11) & 0x1F, (v >> 5) & 0x3F, v & 0x1F
    r, g, b = (r5 << 3) | (r5 >> 2), (g6 << 2) | (g6 >> 4), (b5 << 3) | (b5 >> 2)
    return (r << 16) | (g << 8) | b


def to_hex(v565):
    """RGB565 -> '#RRGGBB' (точний колір, який покаже екран)."""
    return "#%06X" % rgb565_to_888(v565)


def from_hex(text):
    """'#RRGGBB' (або 'RRGGBB') -> RGB565. ValueError, якщо це не 6 шістнадцяткових цифр."""
    t = text.strip()
    if t.startswith("#"):
        t = t[1:]
    if len(t) != 6 or any(c not in "0123456789abcdefABCDEF" for c in t):
        raise ValueError("колір має вигляд #RRGGBB, а не %r" % text)
    return rgb888_to_565(int(t, 16))


def stock_colors(daytime, variant=DEFAULT_VARIANT):
    """Стокова тема: список з 32 значень RGB565."""
    return [rgb888_to_565(x) for x in _TABLES[variant][daytime]]


# ---------------------------------------------------------------------------------------------------------------------------------
#  Блок у флеші
# ---------------------------------------------------------------------------------------------------------------------------------

def encode_block(colors):
    """32 значення RGB565 -> 64 байти (кожне big-endian)."""
    if len(colors) != ITEM_COUNT or any(not isinstance(c, int) or not 0 <= c <= 0xFFFF for c in colors):
        raise ValueError("тема: потрібно %d кольорів RGB565 (0..0xFFFF)" % ITEM_COUNT)
    return b"".join(struct.pack(">H", c) for c in colors)


def decode_block(data):
    """Перші 64 байти блока -> 32 значення RGB565 (прошивка теж копіює рівно 64)."""
    if len(data) < BLOCK_LEN:
        raise ValueError("блок теми коротший за %d байтів (%d)" % (BLOCK_LEN, len(data)))
    return list(struct.unpack(">%dH" % ITEM_COUNT, data[:BLOCK_LEN]))


# ---------------------------------------------------------------------------------------------------------------------------------
#  Файл `.gtm` (R30): рівно вміст блока теми. Денна/нічна -- лише в імені файла (d.gtm / n.gtm), у самому файлі цього немає.
# ---------------------------------------------------------------------------------------------------------------------------------
GTM_EXT = ".gtm"


class GtmError(ValueError):
    """Файл .gtm не 64 байти: пояснення словами, кольори в панелі не змінюються."""


def save_gtm(path, colors):
    """Записати .gtm: ті самі 64 байти, що пішли б у блок рації (encode_block), без перетворень."""
    data = encode_block(colors)
    with open(path, "wb") as f:
        f.write(data)
    return data


def gtm_from_bytes(data):
    """64 байти -> список з 32 значень RGB565. Інша довжина -- GtmError (прошивка копіює рівно 64, довший/коротший файл -- не тема)."""
    if len(data) != BLOCK_LEN:
        raise GtmError("це не файл теми .gtm: у ньому %d байтів, а тема -- рівно %d (32 кольори по 2 байти). Кольори в панелі не змінено."
                       % (len(data), BLOCK_LEN))
    return decode_block(data)


def load_gtm(path):
    try:
        with open(path, "rb") as f:
            data = f.read(BLOCK_LEN + 1 + 4096)     # з запасом: довжину перевіряє gtm_from_bytes, величезний файл не читаємо весь
    except OSError as e:
        raise GtmError("не вдалося прочитати файл: %s" % e)
    return gtm_from_bytes(data)


def gtm_name_hint(path):
    """Підказка за ІМЕНЕМ файла: 'day' / 'night' / None. Лише підказка -- у файлі цього немає, вибір завжди за відкритою темою."""
    base = os.path.basename(path).lower()
    if base.startswith("d"):
        return "day"
    if base.startswith("n"):
        return "night"
    return None


def match_counts(colors, daytime):
    """Скільки з 32 елементів збігаються зі стоковою таблицею кожної з двох гілок: {'ua': n, 'classic': n}."""
    return {v: sum(1 for a, b in zip(colors, stock_colors(daytime, v)) if a == b) for v in VARIANT_NAMES}


# ---------------------------------------------------------------------------------------------------------------------------------
#  Читабельність: пари «колір на своєму тлі», зібрані з викликів displayThemeApply(fg, bg) у прошивці
# ---------------------------------------------------------------------------------------------------------------------------------
TEXT_MIN = 4.5          # WCAG AA для тексту (так само перевіряли стокові теми в HX8353E_display.c)
GRAPHIC_MIN = 3.0       # для смуг, ліній і графіки
HIGH_MIN = 7.0          # WCAG AAA -- для наборів «високий контраст»

# (колір, тло, текст?) -- тло береться з другого аргумента displayThemeApply(); виділений пункт меню малює текст кольором BG на заливці
# BG_MENU_ITEM_SELECTED. Де прошивка дає THEME_ITEM_COLOUR_NONE (тло лишається поточним), пару не складено. Не включено навмисно:
# FG_DECORATION на BG_MENU_NAME (це тінь заголовка вікна PIN, а не текст -- uiMessageBox.c) і FG_CHANNEL_CONTACT_INFO на заливці виділення
# (menuLastHeard.c: заливка малюється інверсією, текст ідуть кольором тла) -- стокові теми цих пар не тримають, тож вони не критерій.
PAIRS = (
    ("FG_DEFAULT", "BG", True), ("FG_TEXT_INPUT", "BG", True), ("FG_SPLASHSCREEN", "BG_SPLASHSCREEN", True),
    ("FG_NOTIFICATION", "BG_NOTIFICATION", True), ("FG_NOTIFICATION", "BG", True),
    ("FG_WARNING_NOTIFICATION", "BG_NOTIFICATION", True), ("FG_WARNING_NOTIFICATION", "BG", True),
    ("FG_ERROR_NOTIFICATION", "BG_NOTIFICATION", True), ("FG_ERROR_NOTIFICATION", "BG", True),
    ("FG_MENU_NAME", "BG_MENU_NAME", True), ("FG_MENU_ITEM", "BG", True), ("BG", "BG_MENU_ITEM_SELECTED", True),
    ("FG_OPTIONS_VALUE", "BG", True), ("FG_HEADER_TEXT", "BG_HEADER_TEXT", True), ("FG_CHANNEL_NAME", "BG", True),
    ("FG_CHANNEL_CONTACT", "BG", True), ("FG_CHANNEL_CONTACT_INFO", "BG", True),
    ("FG_ZONE_NAME", "BG", True), ("FG_RX_FREQ", "BG", True), ("FG_TX_FREQ", "BG", True), ("FG_CSS_SQL_VALUES", "BG", True),
    ("FG_TX_COUNTER", "BG", True), ("FG_TX_COUNTER", "BG_HEADER_TEXT", True), ("FG_GPS_NUMBER", "BG", True),
    ("FG_DECORATION", "BG", False), ("FG_DECORATION", "BG_NOTIFICATION", False),
    ("FG_RSSI_BAR", "BG", False), ("FG_RSSI_BAR", "BG_HEADER_TEXT", False), ("FG_RSSI_BAR", "BG_NOTIFICATION", False),
    ("FG_RSSI_BAR_S9P", "BG", False), ("FG_RSSI_BAR_S9P", "BG_HEADER_TEXT", False),
    ("FG_POLAR_DRAWING", "BG", False), ("FG_SATELLITE_COLOUR", "BG", False),
    ("FG_GPS_COLOUR", "BG", False), ("FG_GPS_COLOUR", "BG_NOTIFICATION", False), ("FG_BD_COLOUR", "BG", False),
)


def _lin(c8):
    c = c8 / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(v565):
    x = rgb565_to_888(v565)
    return 0.2126 * _lin((x >> 16) & 0xFF) + 0.7152 * _lin((x >> 8) & 0xFF) + 0.0722 * _lin(x & 0xFF)


def contrast(a565, b565):
    """Контраст за WCAG (1..21) для двох кольорів RGB565 -- уже ПІСЛЯ квантування, тобто так, як побачить екран."""
    la, lb = luminance(a565), luminance(b565)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def weak_pairs(colors, text_min=TEXT_MIN, graphic_min=GRAPHIC_MIN):
    """Пари, де контраст нижчий за норму: [(колір, тло, контраст, мінімум, текст?)] -- у порядку PAIRS."""
    out = []
    for fg, bg, is_text in PAIRS:
        need = text_min if is_text else graphic_min
        c = contrast(colors[INDEX[fg]], colors[INDEX[bg]])
        if c + 1e-9 < need:
            out.append((fg, bg, round(c, 2), need, is_text))
    return out


def worst_contrast(colors):
    """Найгірший контраст серед текстових пар (для підпису наборів)."""
    return min(contrast(colors[INDEX[fg]], colors[INDEX[bg]]) for fg, bg, t in PAIRS if t)


def pair_label(fg, bg):
    names = dict((k, n) for k, n, _d in ITEMS)
    return "%s на тлі «%s»" % (names[fg], names[bg]) if fg != "BG" else "Текст виділеного пункту на заливці"


# ---------------------------------------------------------------------------------------------------------------------------------
#  Готові набори (T4). Кожен колір -- RGB888 з ролі; усі набори перевіряє test_r28 за PAIRS після квантування в RGB565.
# ---------------------------------------------------------------------------------------------------------------------------------

def _from_roles(roles):
    missing = [k for k in KEYS if k not in roles]
    extra = [k for k in roles if k not in INDEX]
    assert not missing and not extra, (missing, extra)
    return [rgb888_to_565(roles[k]) for k in KEYS]


# «Ніч: червона» -- чорне тло й лише червоно-бурштинові відтінки: не засліплюють і не збивають темнову адаптацію ока.
# Підсвітку (яскравість екрана) колір не змінює -- це робиться в меню рації.
_N_RED = {
    "FG_DEFAULT": 0xFF4D4D, "BG": 0x000000, "FG_DECORATION": 0xC83030, "FG_TEXT_INPUT": 0xFF4D4D,
    "FG_SPLASHSCREEN": 0xFF6A4D, "BG_SPLASHSCREEN": 0x000000, "FG_NOTIFICATION": 0xFF6A4D,
    "FG_WARNING_NOTIFICATION": 0xFF9A33, "FG_ERROR_NOTIFICATION": 0xFF3333, "BG_NOTIFICATION": 0x000000,
    "FG_MENU_NAME": 0xFFB0B0, "BG_MENU_NAME": 0x600000, "FG_MENU_ITEM": 0xFF4D4D, "BG_MENU_ITEM_SELECTED": 0xFF4D4D,
    "FG_OPTIONS_VALUE": 0xFF9A33, "FG_HEADER_TEXT": 0xFF6A4D, "BG_HEADER_TEXT": 0x000000,
    "FG_RSSI_BAR": 0xFF4D4D, "FG_RSSI_BAR_S9P": 0xFF9A33, "FG_CHANNEL_NAME": 0xFF6A4D,
    "FG_CHANNEL_CONTACT": 0xFF9A33, "FG_CHANNEL_CONTACT_INFO": 0xFF8040, "FG_ZONE_NAME": 0xE04040,
    "FG_RX_FREQ": 0xFF4D4D, "FG_TX_FREQ": 0xFF9A33, "FG_CSS_SQL_VALUES": 0xE04040, "FG_TX_COUNTER": 0xFF9A33,
    "FG_POLAR_DRAWING": 0xC83030, "FG_SATELLITE_COLOUR": 0xFF6A4D, "FG_GPS_NUMBER": 0xFF4D4D,
    "FG_GPS_COLOUR": 0xFF8040, "FG_BD_COLOUR": 0xFF4D4D,
}

# «Ніч: високий контраст» -- чисто чорне тло, яскравий текст (кожна текстова пара не нижча за 7:1).
_N_HC = {
    "FG_DEFAULT": 0xFFFFFF, "BG": 0x000000, "FG_DECORATION": 0xFFFFFF, "FG_TEXT_INPUT": 0xFFFFFF,
    "FG_SPLASHSCREEN": 0x00E5FF, "BG_SPLASHSCREEN": 0x000000, "FG_NOTIFICATION": 0x00E5FF,
    "FG_WARNING_NOTIFICATION": 0xFFE600, "FG_ERROR_NOTIFICATION": 0xFF6B6B, "BG_NOTIFICATION": 0x000000,
    "FG_MENU_NAME": 0xFFFFFF, "BG_MENU_NAME": 0x0033A0, "FG_MENU_ITEM": 0xFFFFFF, "BG_MENU_ITEM_SELECTED": 0xFFE600,
    "FG_OPTIONS_VALUE": 0xFFE600, "FG_HEADER_TEXT": 0xFFFFFF, "BG_HEADER_TEXT": 0x000000,
    "FG_RSSI_BAR": 0x39FF14, "FG_RSSI_BAR_S9P": 0xFF6B6B, "FG_CHANNEL_NAME": 0x00E5FF,
    "FG_CHANNEL_CONTACT": 0xFFE600, "FG_CHANNEL_CONTACT_INFO": 0xFFE600, "FG_ZONE_NAME": 0xFFFFFF,
    "FG_RX_FREQ": 0xFFFFFF, "FG_TX_FREQ": 0xFF6B6B, "FG_CSS_SQL_VALUES": 0x39FF14, "FG_TX_COUNTER": 0xFF6B6B,
    "FG_POLAR_DRAWING": 0xFFFFFF, "FG_SATELLITE_COLOUR": 0x39FF14, "FG_GPS_NUMBER": 0xFFFFFF,
    "FG_GPS_COLOUR": 0x00E5FF, "FG_BD_COLOUR": 0xFF6B6B,
}

# «День: високий контраст» -- біле тло, чорний і темні насичені кольори (кожна текстова пара не нижча за 7:1) -- для яскравого сонця.
_D_HC = {
    "FG_DEFAULT": 0x000000, "BG": 0xFFFFFF, "FG_DECORATION": 0x000000, "FG_TEXT_INPUT": 0x000000,
    "FG_SPLASHSCREEN": 0x000080, "BG_SPLASHSCREEN": 0xFFFFFF, "FG_NOTIFICATION": 0x000080,
    "FG_WARNING_NOTIFICATION": 0x703000, "FG_ERROR_NOTIFICATION": 0xB00000, "BG_NOTIFICATION": 0xFFFFFF,
    "FG_MENU_NAME": 0xFFFFFF, "BG_MENU_NAME": 0x000080, "FG_MENU_ITEM": 0x000000, "BG_MENU_ITEM_SELECTED": 0x000080,
    "FG_OPTIONS_VALUE": 0x000080, "FG_HEADER_TEXT": 0x000000, "BG_HEADER_TEXT": 0xE0E0E0,
    "FG_RSSI_BAR": 0x006400, "FG_RSSI_BAR_S9P": 0xB00000, "FG_CHANNEL_NAME": 0x000080,
    "FG_CHANNEL_CONTACT": 0x7A0000, "FG_CHANNEL_CONTACT_INFO": 0x7A0000, "FG_ZONE_NAME": 0x000000,
    "FG_RX_FREQ": 0x000000, "FG_TX_FREQ": 0xB00000, "FG_CSS_SQL_VALUES": 0x000080, "FG_TX_COUNTER": 0x8A0000,
    "FG_POLAR_DRAWING": 0x000000, "FG_SATELLITE_COLOUR": 0x006400, "FG_GPS_NUMBER": 0x000000,
    "FG_GPS_COLOUR": 0x000080, "FG_BD_COLOUR": 0xB00000,
}

# ключ набору -> (назва, на які теми, опис, мінімум контрасту, який набір ГАРАНТУЄ для всіх текстових пар, кольори)
READY_SETS = {
    "night_red": ("Ніч: червона, мінімум світла", ("night",),
                  "чорне тло й лише червоно-бурштинові відтінки (не засліплює в темряві); текст не нижче 4.5:1", TEXT_MIN, _from_roles(_N_RED)),
    "night_hc": ("Ніч: високий контраст", ("night",),
                 "чисто чорне тло, яскравий білий/жовтий/блакитний текст; не нижче 7:1", HIGH_MIN, _from_roles(_N_HC)),
    "day_hc": ("День: високий контраст на сонці", ("day",),
               "біле тло, чорний і темні насичені кольори; не нижче 7:1", HIGH_MIN, _from_roles(_D_HC)),
}


def available_sets(daytime):
    """Список (ключ, назва, опис, кольори) для обраної теми: стокова, класична й готові набори, що підходять."""
    out = []
    for var in ("ua", "classic"):
        out.append(("stock_" + var, VARIANT_NAMES[var], "значення з прошивки (themeInitToDefaultValues)", stock_colors(daytime, var)))
    for key, (name, dts, desc, _min, cols) in READY_SETS.items():
        if daytime in dts:
            out.append((key, name, desc, list(cols)))
    return out


# ---------------------------------------------------------------------------------------------------------------------------------
#  Файл теми -- другий варіант: текстовий формат OpenTYT-theme-1 (кодування UTF-8); основний формат -- .gtm (вище)
# ---------------------------------------------------------------------------------------------------------------------------------

class ThemeFileError(ValueError):
    pass


def to_file_text(daytime, colors):
    """Тема -> текст файла (другий варіант файла; основний -- .gtm). Детермінований: однакові кольори дають побайтово однаковий файл."""
    if daytime not in DAYTIMES:
        raise ThemeFileError("тема має бути day або night")
    encode_block(colors)           # перевірка кількості/меж
    lines = ["# OpenTYT: тема кольорів рації TYT MD-UV390 Plus (формат 1)",
             "# Кожен колір -- RGB565, записаний як #RRGGBB: це точно той колір, який покаже екран. Рядки, що починаються з #, -- коментарі;",
             "# після ; пояснення, його можна не чіпати. Усі 32 кольори обов'язкові.",
             "format = %s" % FILE_FORMAT,
             "daytime = %s" % daytime]
    for (key, name, _d), c in zip(ITEMS, colors):
        lines.append("%-24s = %s    ; %s" % (key, to_hex(c), name))
    return "\n".join(lines) + "\n"


def from_file_text(text):
    """Текст файла -> (daytime, список з 32 значень RGB565). ThemeFileError з поясненням українською."""
    if text.startswith("\ufeff"):
        text = text[1:]
    fmt = None
    daytime = None
    vals = {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ThemeFileError("рядок %d: очікується «ключ = значення»" % n)
        key, val = [x.strip() for x in line.split("=", 1)]
        val = val.split(";", 1)[0].strip()
        if key == "format":
            fmt = val
        elif key == "daytime":
            daytime = val
        elif key in INDEX:
            if key in vals:
                raise ThemeFileError("рядок %d: колір %s вказано двічі" % (n, key))
            try:
                vals[key] = from_hex(val)
            except ValueError as e:
                raise ThemeFileError("рядок %d (%s): %s" % (n, key, e))
        else:
            raise ThemeFileError("рядок %d: невідомий ключ %r" % (n, key))
    if fmt != FILE_FORMAT:
        raise ThemeFileError("це не файл теми OpenTYT (очікується format = %s, у файлі: %s)" % (FILE_FORMAT, fmt if fmt else "нічого"))
    if daytime not in DAYTIMES:
        raise ThemeFileError("у файлі немає daytime = day або night")
    missing = [k for k in KEYS if k not in vals]
    if missing:
        raise ThemeFileError("у файлі бракує кольорів (%d): %s" % (len(missing), ", ".join(missing)))
    return daytime, [vals[k] for k in KEYS]


def save_file(path, daytime, colors):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(to_file_text(daytime, colors))


def load_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return from_file_text(f.read())
    except UnicodeDecodeError:
        raise ThemeFileError("файл не в кодуванні UTF-8")


# ---------------------------------------------------------------------------------------------------------------------------------
#  Попередній перегляд: ОПИС малюнка (без Tk). Екран рації 160x128; кольори -- ключі елементів теми. Наближений: розташування й шрифти
#  не збігаються піксель-у-піксель із прошивкою, але кожен елемент теми намальовано тим самим кольором і на тому самому тлі.
# ---------------------------------------------------------------------------------------------------------------------------------
SCREEN_W, SCREEN_H = 160, 128
PREVIEW_SCREENS = (("channel", "Канал"), ("menu", "Меню"), ("alert", "Сповіщення і передача"), ("splash", "Заставка й супутники"))


def preview_ops(screen):
    """[(вид, ...)]: ("rect", x0, y0, x1, y1, fill_item, tag), ("line", x0, y0, x1, y1, item, tag), ("oval", x0, y0, x1, y1, item, tag),
    ("text", x, y, рядок, item, розмір_px, tag). tag -- ключ елемента, який змінить клацання (для вибору рядка в списку)."""
    R = lambda x0, y0, x1, y1, fill, tag=None: ("rect", x0, y0, x1, y1, fill, tag or fill)           # noqa: E731
    L = lambda x0, y0, x1, y1, item: ("line", x0, y0, x1, y1, item, item)                              # noqa: E731
    T = lambda x, y, s, item, size=10: ("text", x, y, s, item, size, item)                             # noqa: E731
    if screen == "channel":
        return [R(0, 0, 160, 128, "BG"),
                R(0, 0, 160, 14, "BG_HEADER_TEXT"), T(3, 2, "DMR", "FG_HEADER_TEXT"), T(40, 2, "10W", "FG_HEADER_TEXT"), T(122, 2, "87%", "FG_HEADER_TEXT"),
                L(0, 15, 160, 15, "FG_DECORATION"),
                T(3, 19, "Київ-ретр.", "FG_CHANNEL_NAME", 14),
                T(3, 38, "TG 91 Всесвіт", "FG_CHANNEL_CONTACT", 11), T(3, 51, "DB:91  Ct:--", "FG_CHANNEL_CONTACT_INFO", 9),
                T(3, 64, "Зона: Київ", "FG_ZONE_NAME", 10),
                T(3, 77, "RX 438.8000", "FG_RX_FREQ", 12), T(3, 91, "TX 431.2000", "FG_TX_FREQ", 12),
                T(104, 77, "CC1", "FG_CSS_SQL_VALUES", 10), T(104, 91, "TS2", "FG_CSS_SQL_VALUES", 10),
                L(0, 106, 160, 106, "FG_DECORATION"),
                T(3, 109, "S", "FG_DEFAULT", 10),
                R(14, 111, 92, 123, "FG_RSSI_BAR"), R(92, 111, 126, 123, "FG_RSSI_BAR_S9P")]
    if screen == "menu":
        return [R(0, 0, 160, 128, "BG"),
                R(0, 0, 160, 14, "BG_MENU_NAME"), T(4, 2, "Опції", "FG_MENU_NAME"), L(0, 15, 160, 15, "FG_DECORATION"),
                T(4, 19, "Яскравість", "FG_MENU_ITEM"), T(118, 19, "5", "FG_OPTIONS_VALUE"),
                R(0, 32, 160, 46, "BG_MENU_ITEM_SELECTED"), T(4, 34, "Підсвітка", "BG"), T(118, 34, "10 с", "BG"),
                T(4, 49, "Тон клавіш", "FG_MENU_ITEM"), T(118, 49, "Так", "FG_OPTIONS_VALUE"),
                T(4, 64, "Контакт: ", "FG_MENU_ITEM"), T(4, 82, "Введення: AB_", "FG_TEXT_INPUT"),
                L(0, 100, 160, 100, "FG_DECORATION"), T(4, 106, "Звичайний текст", "FG_DEFAULT")]
    if screen == "alert":
        return [R(0, 0, 160, 128, "BG"),
                R(0, 0, 160, 14, "BG_HEADER_TEXT"), T(3, 2, "TX", "FG_HEADER_TEXT"), T(110, 2, "00:12", "FG_TX_COUNTER"),
                T(4, 20, "Передача", "FG_TX_COUNTER", 12),
                R(14, 38, 146, 108, "BG_NOTIFICATION"), L(14, 38, 146, 38, "FG_DECORATION"), L(14, 108, 146, 108, "FG_DECORATION"),
                L(14, 38, 14, 108, "FG_DECORATION"), L(146, 38, 146, 108, "FG_DECORATION"),
                T(22, 46, "Сповіщення", "FG_NOTIFICATION"), T(22, 62, "Увага: батарея", "FG_WARNING_NOTIFICATION"),
                T(22, 78, "Помилка: канал", "FG_ERROR_NOTIFICATION"), R(22, 94, 100, 102, "FG_NOTIFICATION")]
    if screen == "splash":
        return [R(0, 0, 160, 128, "BG"),
                R(0, 0, 160, 50, "BG_SPLASHSCREEN"), T(30, 14, "OpenTYT", "FG_SPLASHSCREEN", 16),
                ("oval", 6, 56, 62, 112, "FG_POLAR_DRAWING", "FG_POLAR_DRAWING"), ("oval", 22, 72, 46, 96, "FG_POLAR_DRAWING", "FG_POLAR_DRAWING"),
                ("oval", 30, 80, 36, 86, "FG_SATELLITE_COLOUR", "FG_SATELLITE_COLOUR"), ("oval", 14, 64, 20, 70, "FG_SATELLITE_COLOUR", "FG_SATELLITE_COLOUR"),
                T(74, 58, "GPS 08", "FG_GPS_NUMBER", 10),
                R(74, 74, 86, 110, "FG_GPS_COLOUR"), R(90, 86, 102, 110, "FG_GPS_COLOUR"),
                R(110, 80, 122, 110, "FG_BD_COLOUR"), R(126, 92, 138, 110, "FG_BD_COLOUR")]
    raise KeyError(screen)


def preview_items_covered():
    """Усі елементи теми, що трапляються в попередньому перегляді (тест вимагає, щоб це були всі 32)."""
    seen = set()
    for key, _t in PREVIEW_SCREENS:
        for op in preview_ops(key):
            seen.add(op[5] if op[0] in ("rect", "line", "oval") else op[4])
    return seen


# ---------------------------------------------------------------------------------------------------------------------------------
#  Рація: читання/запис блока через custom_data (той самий шлях, що в бікона APRS: scan -> sector-safe запис -> звірка читанням)
# ---------------------------------------------------------------------------------------------------------------------------------
# стан блока в рації
ST_OK = "ok"               # блок є, 64 байти
ST_ABSENT = "absent"       # блока нема, але є місце -- рація показує стокову тему; запис створить блок
ST_NOREGION = "noregion"   # області OpenGD77 нема (або в ній немає місця) -- записати тему не можна
ST_BADLEN = "badlen"       # блок є, але не 64 байти -- прошивка заборонила б міняти довжину; змінювати не можна

STATE_TEXT = {
    ST_OK: "блок теми є в рації",
    ST_ABSENT: "блока теми в рації нема -- вона показує стокову; запис створить блок",
    ST_NOREGION: "у флеші рації нема області даних OpenGD77 (або в ній немає місця) -- записати тему не можна",
    ST_BADLEN: "блок теми в рації має нестандартну довжину -- прошивка забороняє її міняти, запис неможливий",
}


def read_theme(ser, daytime):
    """-> (стан, кольори|None). Для ST_ABSENT/ST_NOREGION кольорів нема (використайте stock_colors); для ST_BADLEN -- перші 64 байти, якщо є."""
    import custom_data as cd
    dtype = TYPE_OF[daytime]
    kind, addr, ln = cd.find_or_alloc_block(ser, dtype, BLOCK_LEN)
    if kind is None:
        return ST_NOREGION, None
    if kind == "empty":
        return ST_ABSENT, None
    if ln < BLOCK_LEN:
        return ST_BADLEN, None
    data = cd._read_region(ser, addr + cd.HDR_LEN, BLOCK_LEN)
    colors = decode_block(data)
    return (ST_OK if ln == BLOCK_LEN else ST_BADLEN), colors


def write_theme(ser, daytime, colors):
    """Записати тему й перечитати для звірки. Повертає текст підсумку; RuntimeError -- збій або НЕЗБІГ."""
    import custom_data as cd
    payload = encode_block(colors)
    ok, msg = cd.write_block(ser, TYPE_OF[daytime], payload)
    if not ok:
        raise RuntimeError("тема %s не записана: %s" % (DAYTIME_NAMES[daytime].lower(), msg))
    back = cd.read_block(ser, TYPE_OF[daytime], BLOCK_LEN)
    if back != payload:
        raise RuntimeError("тема %s записана, але звірка читанням НЕ збіглася -- повторіть запис" % DAYTIME_NAMES[daytime].lower())
    return "%s тема записана (%s). Звірка читанням: OK." % (DAYTIME_NAMES[daytime], msg)
