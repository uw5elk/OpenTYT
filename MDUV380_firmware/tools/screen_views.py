# -*- coding: utf-8 -*-
"""screen_views.py -- R33 R2: екрани рації (MD-UV390 Plus 10W, українська збірка), намальовані дисплейним рівнем screen_sim.Display тими ж викликами в тому
самому порядку, що й код прошивки. Кожна функція вказує в коментарі файл і функцію прошивки, з якої взято порядок малювання й координати.

ЩО ТУТ З КОДУ, А ЩО -- ПРИКЛАД.
  * Координати, шрифти, порядок малювання, пари «елемент теми / тло», формули (положення смуги S-метра, зсув у шапці тощо) -- з вихідного коду
    прошивки; константи розкладки (DISPLAY_Y_POS_*, SMETER_*, MENU_*) зведені в LAYOUT, і test_r33.py ЗВІРЯЄ кожну з файлами прошивки.
  * Мовні рядки -- UA: поле структури stringsTable_t -> текст; test_r33.py звіряє з languages/ukrainian.h (cp1251).
  * Дані екрана (позивний, рівень сигналу, назви каналу й зони, номери й положення супутників, значення GPS) -- ПРИКЛАД, у SAMPLE: рація покаже
    свої. Приклад підібрано так, щоб на екрані з'явилося якомога більше різних елементів теми.
  * Стан, що залежить від рації й не моделюється (позначка AES, конверти SMS/APRS, годинник замість заряду тощо) -- у NOT_MODELLED.

ЯК ДОДАТИ ЕКРАН: функція `scr_<ключ>(d, st)` + рядок у SCREENS; кожну координату -- з коду прошивки (джерело в коментарі), нову константу -- у LAYOUT.
"""
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import screen_sim as sim                       # noqa: E402
from screen_sim import (IT, NONE, FONT_1, FONT_1_BOLD, FONT_2, FONT_3, FONT_4,       # noqa: E402,F401
                        ALIGN_LEFT, ALIGN_CENTER, ALIGN_RIGHT)

# ---------------------------------------------------------------------------------------------------------------------------------
#  Розкладка MDUV380 (PLATFORM_MDUV380, не DM1701): значення ОБЧИСЛЕНІ з #define у прошивці; test_r33 перераховує їх із файлів і порівнює.
#  Ключ = ім'я #define; значення = що вийшло для цієї плати. Файл-джерело і гілка #if -- у test_r33.LAYOUT_SOURCES.
# ---------------------------------------------------------------------------------------------------------------------------------
LAYOUT = {
    "DISPLAY_H_OFFSET": 16, "DISPLAY_V_EXTRA_PIXELS": 64, "DISPLAY_V_OFFSET": 32,
    "MENU_ENTRY_HEIGHT": 16, "MENU_HEADER_HEIGHT": 14, "MENU_MAX_DISPLAYED_ENTRIES": 7,
    "OVERRIDE_FRAME_HEIGHT": 16, "V_OFFSET": 0,
    "DISPLAY_Y_POS_HEADER": 2, "DISPLAY_X_POS_MENU_OFFSET": 4, "DISPLAY_X_POS_MENU_TEXT_OFFSET": 8,
    "DISPLAY_Y_POS_MENU_START": 32, "DISPLAY_Y_POS_MENU_ENTRY_HIGHLIGHT": 64,
    "DISPLAY_Y_POS_BAR": 10, "DISPLAY_Y_POS_CONTACT": 24, "DISPLAY_Y_POS_CONTACT_TX": 66, "DISPLAY_Y_POS_CONTACT_TX_FRAME": 66,
    "DISPLAY_Y_POS_CHANNEL_FIRST_LINE": 64, "DISPLAY_Y_POS_CHANNEL_SECOND_LINE": 96,
    "DISPLAY_Y_POS_CSS_INFO": 24, "DISPLAY_Y_POS_SQL_INFO": 33, "DISPLAY_Y_POS_TX_TIMER": 24,
    "DISPLAY_Y_POS_RX_FREQ": 80, "DISPLAY_Y_POS_TX_FREQ": 96, "DISPLAY_Y_POS_ZONE": 114,
    "FREQUENCY_X_POS": 28, "VFO_LETTER_Y_OFFSET": 8,
    "SMETER_BLOCK_Y": 41, "SMETER_BLOCK_H": 23, "SMETER_FRAME_X": 0, "SMETER_FRAME_W": 160, "SMETER_FRAME_H": 12,
    "SMETER_BAR_X": 1, "SMETER_BAR_WIDTH": 158, "SMETER_BAR_H": 8, "SMETER_BAR_Y": 43, "SMETER_TICK_Y": 53,
    "SMETER_TICK_H_MAJOR": 3, "SMETER_TICK_H_MINOR": 2, "SMETER_SCALE_Y": 57, "SMETER_VALUE_RIGHT": 159, "SMETER_VALUE_MIN_X": 132,
    "SMETER_FONT_W": 6, "SMETER_GLYPH_INK_CX": 2, "SMETER_S9_POS": 125, "SMETER_ABOVE_S9_DB": 20,
    "SMETER_S0": -129, "SMETER_S9": -93, "SMETER_TEXT_SHIFT": 8,
    "TITLE_BOX_HEIGHT": 21,
    "BEARING_RADIUS": 24, "BEARING_CIRCLE_X_OFFSET": 13, "BEARING_BOX_H": 68, "BEARING_CIRCLE_X_POS": 37, "BEARING_BOX_Y": 30,
    "TOP_ARROW_OFFSET": 16, "BASE_ARROW_OFFSET": -16, "BEARING_AND_DIST_X_CENTER": 110,
}
# menuGPS.c: блок для PLATFORM_MDUV380 (інший за MD9600/RD5R) -- ключі з префіксом GPS_ (в прошивці імена без префікса).
LAYOUT_GPS = {"RSSI_X_OFFSET": 2, "RSSI_BARS_Y_POS": 120, "NUM_BARS": 17, "MAX_RSSI_Y_PIXELS": 59, "MAIDENHEAD_HDOP_MARGIN": 8, "MAIDENHEAD_HDOP_Y_POS": 32}
# menuSatelliteScreen.c: константи екрана польоту (локальні const / #define усередині updateScreen).
LAYOUT_SAT = {"POLAR_GRAPHICS_X_OFFSET": 24, "MAX_RADIUS": 44, "DOT_RADIUS": 2}
LG, L_SAT = LAYOUT_GPS, LAYOUT_SAT
L = LAYOUT

# Мовні рядки (українська збірка), поле stringsTable_t -> текст. Звіряється з languages/ukrainian.h (cp1251) у test_r33.
UA = {
    "menu": "Меню", "options": "Налаштування", "general_options": "Загальні опції", "contacts": "Контакти", "last_heard": "Останні виклики",
    "firmware_info": "Про прошивку", "satellite": "Супутники", "gps": "GPS", "messages": "Повідомлення", "remote_control": "Адміністрування",
    "zone": "Зона", "channel_details": "Канал", "tg": "TG", "ts": "TS", "none": "Немає", "private_call": "Приватний виклик",
    "error": "ПОМИЛКА", "timeout": "ТАЙМАУТ", "tg_entry": "Ввід TG", "key_long": "Довге нат.", "key_repeat": "Повтор", "auto_lock": "Автоблок.",
    "hotspot_mode": "Hotspot", "temperature_calibration": "Temp Cal", "battery_calibration": "Batt. Cal", "eco_level": "Рівень Eco",
    "off": "Off", "celcius": "°C", "maximum": "Макс", "radio_options": "Опції рації", "display_options": "Дисплей",
    "radio_info": "Параметри", "aprs_options": "APRS", "rx_only": "Тільки RX", "symbols": "NSEW",
}
# Рядки, що не є полями stringsTable_t: #define у languages/slogans_ua.h та languages/txerr_ua.h.
SLOGAN_POWER_ON = "СЛАВА УКРАЇНІ!"
TXERR_RPT_LINE1, TXERR_RPT_LINE2 = "Ретранслятор", "не відповідає"
# Головне меню (mainMenuItems[] в українській збірці з APRS, AES і DMR-даними; пункт «RSSI» там прибрано, пункт «GPS» теж: FORK_NO_GPS_MENU в applicationMain.h). Поле stringsTable_t за номером пункту.
MAIN_MENU_FIELDS = ("zone", "contacts", "channel_details", "firmware_info", "options", "last_heard", "radio_info", "satellite",
                    "messages", "aprs_options", "remote_control")
# Меню «Загальні опції»: перші 7 пунктів (enum GENERAL_OPTIONS_MENU_* у menuGeneralOptions.c для MDUV380): ліва частина -- поле, права -- значення при
# заводських налаштуваннях (settings.c: keypadTimerLong 5, keypadTimerRepeat 3, autolockTimer 0, hotspotType 0, temperatureCalibration 0, batteryCalibration 5, ecoLevel 1).
GENERAL_OPTIONS_ROWS = (("key_long", "0.5s"), ("key_repeat", "0.3s"), ("auto_lock", "off"), ("hotspot_mode", "off"),
                        ("temperature_calibration", " 0.0°C"), ("battery_calibration", " 0.0V"), ("eco_level", "1"))

# Те, що залежить від стану рації й тут НЕ малюється (екран із цими елементами виглядав би інакше).
NOT_MODELLED = (
    "позначка AES (замок) на каналі з шифруванням -- залежить від налаштування каналу (uiDrawAesEnabledIcon)",
    "конверти непрочитаних SMS DMR і повідомлень APRS у шапці (drawMsgEnvelope) та напис APRS на час маяка",
    "годинник замість заряду, заряд у вольтах, значок GPS у шапці, блимання під час сканування, закреслення при вимкненому звуку",
    "режими «подвійна висота тексту» та «додаткова інформація на екрані» (показ TS/потужності каналу жирним)",
    "зображення заставки з кодплага (customdata) -- є лише текстова заставка",
    "рівні гучності/потужності/шумодава, що малюються фіксованими кольорами поза темою",
)

# Приклад даних (вигадані; на рації будуть свої).
SAMPLE = {
    "battery_pct": 87, "power": "1W", "cc": 1, "ts": 2,
    "rssi_idle": -118, "rssi_rx": -85, "mic_bar": 70, "tx_secs": 12,
    "zone": "Київ", "channel_no": 3, "channel": "Київ R1", "contact": "Україна", "talkgroup": "Україна",
    "callsign": "UR1AAA", "caller_rest": "Ivan",
    "rx_freq": 145600000 // 10, "tx_freq": 145000000 // 10,       # 10 Гц одиниці не потрібні: див. freq_text, частота подається у форматі «МГц.5 знаків»
    "ctcss": "88.5", "squelch_pct": 45, "rssi_sat": -105,
}

KEY_TO_ITEM = IT


def _it(key):
    return IT[key]


# ---------------------------------------------------------------------------------------------------------------------------------
#  Загальні шматки: uiUtilities.c
# ---------------------------------------------------------------------------------------------------------------------------------

def smeter_pixel_pos(dbm):
    """smeterPixelPos(): положення на смузі S-метра в пікселях (цілочислова арифметика, як у C)."""
    if dbm <= L["SMETER_S0"]:
        return 0
    if dbm <= L["SMETER_S9"]:
        return ((dbm - L["SMETER_S0"]) * L["SMETER_S9_POS"]) // (L["SMETER_S9"] - L["SMETER_S0"])
    above = max(0, min(dbm - L["SMETER_S9"], L["SMETER_ABOVE_S9_DB"]))
    return L["SMETER_S9_POS"] + (above * (L["SMETER_BAR_WIDTH"] - L["SMETER_S9_POS"])) // L["SMETER_ABOVE_S9_DB"]


def draw_smeter_block(d, rssi_dbm):
    """drawSMeterBlock() (uiUtilities.c): повний блок S-метра y=41..63. Вмикається завжди в українській збірці на екранах каналу й VFO."""
    bar_w = max(0, min(smeter_pixel_pos(rssi_dbm), L["SMETER_BAR_WIDTH"]))
    s9 = L["SMETER_S9_POS"]
    # 0) гасимо тонку смугу під шапкою (y=10..13) кольором тла шапки
    d.theme_apply(_it("FG_RSSI_BAR"), _it("BG_HEADER_TEXT"))
    d.fill_rect(0, L["DISPLAY_Y_POS_BAR"], sim.W, 4, True)
    d.theme_reset()
    # 1) очищення блока
    d.theme_apply(_it("FG_DEFAULT"), _it("BG"))
    d.fill_rect(0, L["SMETER_BLOCK_Y"], sim.W, L["SMETER_BLOCK_H"], True)
    d.theme_reset()
    # 2) заповнення смуги
    if bar_w:
        d.theme_apply(_it("FG_RSSI_BAR"), _it("BG"))
        d.fill_rect(L["SMETER_BAR_X"], L["SMETER_BAR_Y"], bar_w, L["SMETER_BAR_H"], False)
        d.theme_reset()
    if bar_w > s9:
        d.theme_apply(_it("FG_RSSI_BAR_S9P"), _it("BG"))
        d.fill_rect(L["SMETER_BAR_X"] + s9, L["SMETER_BAR_Y"], bar_w - s9, L["SMETER_BAR_H"], False)
        d.theme_reset()
    # 3) рамка
    d.theme_apply(_it("FG_DECORATION"), _it("BG"))
    d.draw_rect(L["SMETER_FRAME_X"], L["SMETER_BLOCK_Y"], L["SMETER_FRAME_W"], L["SMETER_FRAME_H"], True)
    d.theme_reset()
    # 4) поділки
    d.theme_apply(_it("FG_DECORATION"), _it("BG"))
    for s in range(1, 10):
        tx = L["SMETER_BAR_X"] + smeter_pixel_pos(L["SMETER_S0"] + s * 4)
        d.fast_vline(tx, L["SMETER_TICK_Y"], L["SMETER_TICK_H_MAJOR"] if (s & 1) else L["SMETER_TICK_H_MINOR"], True)
    d.theme_reset()
    # 5) цифри шкали 1 3 5 7 9
    d.theme_apply(_it("FG_DECORATION"), _it("BG"))
    for s in range(1, 10, 2):
        d.print_at(L["SMETER_BAR_X"] + smeter_pixel_pos(L["SMETER_S0"] + s * 4) - L["SMETER_GLYPH_INK_CX"], L["SMETER_SCALE_Y"], str(s), FONT_1)
    d.theme_reset()
    # 6) значення в дБм
    buf = str(rssi_dbm)
    text_x = max(L["SMETER_VALUE_RIGHT"] - len(buf) * L["SMETER_FONT_W"], L["SMETER_VALUE_MIN_X"])
    d.theme_apply(_it("FG_DEFAULT"), _it("BG"))
    d.print_at(text_x, L["SMETER_SCALE_Y"], buf, FONT_1)
    d.theme_reset()


def draw_header_bar(d, bar_width, bar_height=4):
    """drawHeaderBar(): тонка смуга сигналу/мікрофона під текстом шапки (y=10..)."""
    bar_width = max(0, min(bar_width, sim.W))
    d.theme_apply(_it("FG_RSSI_BAR"), _it("BG_HEADER_TEXT"))
    if bar_width:
        d.fill_rect(0, L["DISPLAY_Y_POS_BAR"], bar_width, bar_height, False)
    if bar_width < sim.W:
        d.fill_rect(bar_width, L["DISPLAY_Y_POS_BAR"], sim.W - bar_width, bar_height, True)
    d.theme_reset()


def draw_header(d, st, mode="dmr", transmitting=False, rssi=None):
    """uiUtilityRenderHeader() для звичайного екрана каналу: цифровий (dmr) чи аналоговий (fm) режим, без сканування, без хотспота.
    Заводські значення з settings.c: фільтр призначення = NONE, dmrCcTsFilter = CC_TS (обидва фільтри ввімкнені -- нічого не інвертується),
    заряд у відсотках, годинника немає, apo = 0, потужність 4 -> «1W» (POWER_LEVELS 10W-Plus)."""
    pct = st["battery_pct"]
    item_offset = 1 if pct < 100 else 0                              # itemOffset (не MD9600)
    filter_text_x, power_x, cc_x = 37, 65, 92                        # FILTER_TEXT_X_CENTER, POWER_X_CENTER, COLOR_CODE_X_CENTER
    # 1) смуга сигналу або мікрофона (до заливки шапки)
    if not transmitting:
        draw_smeter_block(d, st["rssi"] if rssi is None else rssi)
    else:
        draw_header_bar(d, st["mic_bar"])
    # 2) шапка
    d.theme_apply(_it("FG_HEADER_TEXT"), _it("BG_HEADER_TEXT"))
    d.fill_rect(0, 0, sim.W, L["DISPLAY_Y_POS_BAR"], True)
    y = L["DISPLAY_Y_POS_HEADER"]
    if mode == "fm":
        d.print_core(1, y, "FMN", FONT_1, ALIGN_LEFT, False)          # trxGetBandwidthIs25kHz() == false -> "FMN"
        # тон CTCSS є (txTone != NONE): "CT"; фільтр аналогового режиму = CSS -> не інвертується
        buf = "CT"
        css_x = (filter_text_x + item_offset) - ((len(buf) * 6) >> 1)
        d.print_core(css_x, y, buf, FONT_1, ALIGN_LEFT, False)
    else:
        d.print_core(1, y, "DMR", FONT_1, ALIGN_LEFT, False)
        buf = "%s%d" % (UA["ts"], st["ts"])                           # contactTSActive == false (у контакта немає перевизначення TS)
        ts_x = (filter_text_x + item_offset) - ((len(buf) * 6) >> 1)
        d.print_core(ts_x, y, buf, FONT_1, ALIGN_LEFT, False)
    # потужність
    buf = st["power"]
    d.print_core((power_x + item_offset * 2) - ((len(buf) * 6) >> 1), y, buf, FONT_1, ALIGN_LEFT, False)
    # колірний код (лише цифровий режим)
    if mode != "fm":
        buf = "C%d" % st["cc"]
        d.print_core((cc_x + item_offset * 3) - ((len(buf) * 6) >> 1), y, buf, FONT_1, ALIGN_LEFT, False)
    # заряд (відсотки), праворуч
    buf = "%d%%" % pct
    d.print_core(sim.W - len(buf) * 6, y, buf, FONT_1, ALIGN_LEFT, False)
    d.theme_reset()


def display_information(d, text, line, y_override=-1):
    """uiUtilityDisplayInformation() (uiUtilities.c) для режимів, що потрібні екранам."""
    inverted = False
    if line == "contact_inverted":
        d.theme_apply(_it("FG_CHANNEL_CONTACT"), _it("BG"))
        d.fill_rect(0, L["DISPLAY_Y_POS_CONTACT"], sim.W, L["MENU_ENTRY_HEIGHT"], False)
        inverted = True
        line = "contact"
    if line == "contact":
        d.theme_apply(_it("FG_CHANNEL_CONTACT"), _it("BG"))
        d.print_core(0, L["DISPLAY_Y_POS_CONTACT"] + L["V_OFFSET"] if y_override == -1 else y_override, text, FONT_3, ALIGN_CENTER, inverted)
    elif line == "contact_frame":
        d.theme_apply(_it("FG_CHANNEL_CONTACT"), _it("BG"))
        d.draw_rect(0, L["DISPLAY_Y_POS_CONTACT"] if y_override == -1 else y_override, sim.W, L["OVERRIDE_FRAME_HEIGHT"], True)
    elif line == "channel":
        if not d.theme_fg_is(_it("FG_CHANNEL_CONTACT_INFO")):          # displayContactTextInfos() підміняє колір на FG_CHANNEL_CONTACT_INFO
            d.theme_apply(_it("FG_CHANNEL_NAME"), _it("BG"))
        d.print_core(0, channel_first_line_y() if y_override == -1 else y_override, text, FONT_3, ALIGN_CENTER, False)
    elif line == "tx_timer":
        d.theme_apply(_it("FG_TX_COUNTER"), _it("BG"))
        d.print_centered(L["DISPLAY_Y_POS_TX_TIMER"] if y_override == -1 else y_override, text, FONT_4)
    elif line == "zone":
        if y_override == -2:                                           # показ зони (не рядок «назва каналу / частота» з QSO)
            d.theme_apply(_it("FG_ZONE_NAME"), _it("BG"))
        d.print_centered(L["DISPLAY_Y_POS_ZONE"], text, FONT_1)
    else:
        raise KeyError(line)
    d.theme_reset()


def channel_first_line_y():
    """uiUtilityChannelFirstLineY(): блок S-метра дозволений -> +SMETER_TEXT_SHIFT."""
    return L["DISPLAY_Y_POS_CHANNEL_FIRST_LINE"] + L["SMETER_TEXT_SHIFT"]


def display_frequency(d, y, is_tx, freq_text):
    """uiUtilityDisplayFrequency() для нескануючого режиму каналу без «подвійної висоти» та без позначки VFO."""
    d.theme_apply(_it("FG_TX_FREQ") if is_tx else _it("FG_RX_FREQ"), _it("BG"))
    d.print_at(0, y, " " + ("T" if is_tx else "R"), FONT_3)
    d.print_at(L["FREQUENCY_X_POS"], y, freq_text, FONT_3)
    d.print_at(sim.W - 3 * 8, y, "MHz", FONT_3)
    d.theme_reset()


def freq_text(freq_10hz):
    """«%d.%05d» з частоти в одиницях 10 Гц (так її зберігає прошивка)."""
    return "%d.%05d" % (freq_10hz // 100000, freq_10hz - (freq_10hz // 100000) * 100000)


# ---------------------------------------------------------------------------------------------------------------------------------
#  Екрани
# ---------------------------------------------------------------------------------------------------------------------------------

def scr_channel(d, st):
    """Канал DMR, очікування: uiChannelModeUpdateScreen() -> QSO_DISPLAY_DEFAULT_SCREEN (uiChannelMode.c).
    st["mode"] == "fm" (R39, самоперевірка S3): аналоговий канал -- шапка FM і без рядка контакту (контакт малюється лише в цифровому режимі)."""
    st = dict(st, rssi=st["rssi_idle"])
    mode = st.get("mode", "dmr")
    d.theme_reset()
    d.clear_buf()
    draw_header(d, st, mode)
    display_information(d, "%s Ch:%d" % (st["zone"], st["channel_no"]), "zone", -2)
    display_information(d, st["channel"], "channel", -1)
    if mode != "fm":
        display_information(d, st["contact"], "contact", -1)


def scr_channel_qso(d, st):
    """Канал DMR, іде виклик: uiUtilityRenderQSOData() (uiUtilities.c) -- група у верхньому рядку, позивний і ім'я нижче. Вигадані дані."""
    st = dict(st, rssi=st["rssi_rx"])
    d.theme_reset()
    d.clear_buf()
    draw_header(d, st, "dmr")
    d.theme_apply(_it("FG_CHANNEL_CONTACT_INFO"), _it("BG"))
    display_information(d, st["talkgroup"], "contact", -1)                         # група, не інвертована (збігається з поточним TG/TS/CC)
    d.theme_apply(_it("FG_CHANNEL_CONTACT_INFO"), _it("BG"))
    # displayContactTextInfos(): splitContact == ON_TWO_LINES; "UR1AAA Ivan" -> позивник у рядку каналу, решта -- нижче
    display_information(d, st["callsign"], "channel", -1)                            # fg == FG_CHANNEL_CONTACT_INFO -> колір лишається
    d.theme_apply(_it("FG_CHANNEL_CONTACT_INFO"), _it("BG"))
    d.print_centered(L["DISPLAY_Y_POS_CHANNEL_SECOND_LINE"], st["caller_rest"], FONT_3)       # displaySplitOrSpanText(y=96): len<=16 -> по центру FONT_SIZE_3
    d.theme_reset()


def scr_channel_details(d, st):
    """Канал FM, режим «параметри каналу» (displayChannelSettings): uiUtilityDisplayInformation(CHANNEL_DETAILS) + частоти RX/TX."""
    st = dict(st, rssi=st["rssi_idle"])
    d.theme_reset()
    d.clear_buf()
    draw_header(d, st, "fm")
    buf = "Rx:%sHz|Tx:%sHz" % (st["ctcss"], st["ctcss"])
    d.theme_apply(_it("FG_CSS_SQL_VALUES"), _it("BG"))
    d.print_centered(L["DISPLAY_Y_POS_CSS_INFO"], buf, FONT_1)
    d.print_centered(L["DISPLAY_Y_POS_SQL_INFO"], "SQL:%d%%" % st["squelch_pct"], FONT_1)
    d.theme_reset()
    display_frequency(d, L["DISPLAY_Y_POS_RX_FREQ"], False, freq_text(st["rx_freq"]))
    display_frequency(d, L["DISPLAY_Y_POS_TX_FREQ"], True, freq_text(st["tx_freq"]))


def scr_transmit(d, st):
    """Канал DMR, передача: uiChannelModeUpdateScreen(txTimeSecs) -- таймер FONT_SIZE_4, назва каналу на 96, контакт на 66, смуга мікрофона."""
    d.theme_reset()
    d.clear_buf()
    draw_header(d, st, "dmr", transmitting=True)
    display_information(d, " %d " % st["tx_secs"], "tx_timer", -1)
    display_information(d, st["channel"], "channel", L["DISPLAY_Y_POS_CHANNEL_SECOND_LINE"])
    display_information(d, st["contact"], "contact", L["DISPLAY_Y_POS_CONTACT_TX"])


# ---------------------------------------------------------------------------------------------------------------------------------
#  Меню (menuSystem.c, menuDisplayMenuList.c, menuGeneralOptions.c)
# ---------------------------------------------------------------------------------------------------------------------------------
MENU_OFFSET_BEFORE_FIRST_ENTRY, MENU_OFFSET_AFTER_LAST_ENTRY = -1, -2


def menu_iteration_range():
    """MENU_START_ITERATION_VALUE .. MENU_END_ITERATION_VALUE (menuSystem.h) для MENU_MAX_DISPLAYED_ENTRIES."""
    n = L["MENU_MAX_DISPLAYED_ENTRIES"]
    if n & 1:
        return 1 - ((n - 1) // 2) - 1, n - ((n - 1) // 2) - 1
    return 1 - (n // 2), n - (n // 2)


def menu_get_offset(max_items, loop_offset, current):
    """menuGetMenuOffset(): номер пункту для рядка `loop_offset` відносно виділеного; список замикається по колу."""
    n = L["MENU_MAX_DISPLAYED_ENTRIES"]
    offset = current + loop_offset
    start_offset = 0
    it = loop_offset + (n // 2) + (1 if (n & 1) else 0)
    if max_items < n:
        start_offset = ((n - (0 if (n & 1) else 1)) - max_items) // 2
        if it <= start_offset:
            return MENU_OFFSET_BEFORE_FIRST_ENTRY
        if it > start_offset + max_items:
            return MENU_OFFSET_AFTER_LAST_ENTRY
    if offset < 0:
        offset = (n - 1) if (max_items == 1 and max_items < n) else (max_items + offset)
    if offset >= max_items:
        offset -= max_items
    return offset


def menu_display_title(d, title):
    """menuDisplayTitle(): смуга BG_MENU_NAME, лінія FG_DECORATION внизу, назва по центру."""
    fg, bg = d.theme_get()
    d.theme_apply(_it("BG_MENU_NAME"), NONE)
    d.fill_rect(0, 0, sim.W, L["MENU_HEADER_HEIGHT"], False)
    d.theme_apply(_it("FG_DECORATION"), _it("BG"))
    d.fast_hline(0, L["MENU_HEADER_HEIGHT"] - 1, sim.W, True)
    d.theme_apply(_it("FG_MENU_NAME"), _it("BG"))
    d.print_core(0, 3, title, FONT_2, ALIGN_CENTER, False)
    d.theme_apply(fg, bg)


def menu_display_entry(d, loop_offset, focused, text, opt_start, fg, fg_opt, bg):
    """menuDisplayEntry(): виділений пункт -- закруглена заливка BG_MENU_ITEM_SELECTED і текст кольором тла; невиділений із opt_start != 0 --
    значення після `opt_start` символів кольором fg_opt (opt_start < 0 -- весь рядок кольором fg_opt)."""
    y = L["DISPLAY_Y_POS_MENU_ENTRY_HIGHLIGHT"] + loop_offset * L["MENU_ENTRY_HEIGHT"]
    if focused:
        d.theme_apply(_it("BG_MENU_ITEM_SELECTED"), bg)
        d.fill_round_rect(L["DISPLAY_X_POS_MENU_OFFSET"], y, sim.W - L["DISPLAY_X_POS_MENU_OFFSET"] * 2, L["MENU_ENTRY_HEIGHT"], 2, True)
    d.theme_apply(fg, bg)
    x = L["DISPLAY_X_POS_MENU_TEXT_OFFSET"]
    if (not focused) and opt_start != 0:
        first = text[:opt_start] if opt_start > 0 else text
        if opt_start < 0:
            d.theme_apply(fg_opt, bg)
        d.print_core(x, y, first, FONT_3, ALIGN_LEFT, focused)
        if opt_start > 0:
            d.theme_apply(fg_opt, bg)
            d.print_core(x + opt_start * 8, y, text[opt_start:], FONT_3, ALIGN_LEFT, focused)
    else:
        d.print_core(x, y, text, FONT_3, ALIGN_LEFT, focused)
    d.theme_reset()


def scr_menu(d, st):
    """Головне меню: updateScreen() у menuDisplayMenuList.c. Виділений пункт -- «Налаштування»."""
    names = [UA[k] for k in MAIN_MENU_FIELDS]
    current = MAIN_MENU_FIELDS.index("options")
    d.theme_reset()
    d.clear_buf()
    menu_display_title(d, UA["menu"])
    a, b = menu_iteration_range()
    for i in range(a, b + 1):
        m = menu_get_offset(len(names), i, current)
        if m == MENU_OFFSET_BEFORE_FIRST_ENTRY:
            continue
        if m == MENU_OFFSET_AFTER_LAST_ENTRY:
            break
        menu_display_entry(d, i, m == current, names[m], 0, _it("FG_MENU_ITEM"), NONE, _it("BG"))


def scr_options(d, st):
    """Меню налаштувань зі значеннями: updateScreen() у menuGeneralOptions.c (рядок «ліва частина:значення», значення -- FG_OPTIONS_VALUE)."""
    current = 3                                                        # «Hotspot» -- тоді на екрані пункти 0..6 без «обертання» списку
    d.theme_reset()
    d.clear_buf()
    menu_display_title(d, UA["general_options"])
    a, b = menu_iteration_range()
    for i in range(a, b + 1):
        m = menu_get_offset(len(GENERAL_OPTIONS_ROWS) + 9, i, current)       # у списку пунктів більше за 7 (решта нижче) -- обертання не потрібне
        if m < 0 or m >= len(GENERAL_OPTIONS_ROWS):
            continue
        left, right = GENERAL_OPTIONS_ROWS[m]
        left = UA[left]
        right = UA["off"] if right == "off" else right
        menu_display_entry(d, i, m == current, "%s:%s" % (left, right), len(left) + 1, _it("FG_MENU_ITEM"), _it("FG_OPTIONS_VALUE"), _it("BG"))


# ---------------------------------------------------------------------------------------------------------------------------------
#  Сповіщення, помилки передачі, заставка (uiNotification.c, uiTxScreen.c, uiSplashScreen.c)
# ---------------------------------------------------------------------------------------------------------------------------------
DEG_TO_RAD = struct.unpack("<f", struct.pack("<f", 0.017453292519943295769236907684886))[0]       # float у C


def scr_notification(d, st):
    """Сповіщення «пеленг» (NOTIFICATION_TYPE_BEARING, uiNotificationRefresh): поверх екрана каналу -- картка з компасом, стрілкою, кутом і відстанню.
    Картки гучності/потужності/шумодава малюються фіксованими кольорами поза темою (displayLevelCard), тому передпоказ показує цю."""
    scr_channel(d, st)
    bearing, dist_x10 = 45.0, 123                                  # приклад: 45 градусів, 12.3 км
    cx, cy = L["BEARING_CIRCLE_X_POS"], (sim.H >> 1) - 3
    r = L["BEARING_RADIUS"]
    d.theme_apply(_it("FG_DECORATION"), _it("BG_NOTIFICATION"))
    d.draw_round_rect_with_shadow(1, L["BEARING_BOX_Y"], sim.W - 4, L["BEARING_BOX_H"], 3, True)
    d.theme_apply(_it("FG_NOTIFICATION"), _it("BG_NOTIFICATION"))
    for i in range(0, 360, 15):
        ang = _f32(i * DEG_TO_RAD)
        x1 = int(cx + r * math.cos(ang))
        y1 = int(cy + r * math.sin(ang))
        rr = r - (2 if (i % 45) else 4)
        x2 = int(cx + rr * math.cos(ang))
        y2 = int(cy + rr * math.sin(ang))
        if i == 270:
            d.theme_apply(_it("FG_GPS_COLOUR"), _it("BG_NOTIFICATION"))
            d.draw_line(x1 - 1, y1, x2 - 1, y2, True)
        d.draw_line(x1, y1, x2, y2, True)
        if i == 270:
            d.draw_line(x1 + 1, y1, x2 + 1, y2, True)
            d.theme_apply(_it("FG_DECORATION"), _it("BG_NOTIFICATION"))
    d.theme_apply(_it("FG_DECORATION"), _it("BG_NOTIFICATION"))
    d.draw_circle(cx, cy, r + 1, True)
    d.theme_apply(_it("FG_GPS_COLOUR"), _it("BG_NOTIFICATION"))
    needle = bearing - 90.0
    if needle > 360.0:
        needle -= 360.0
    needle *= DEG_TO_RAD
    top, base = L["TOP_ARROW_OFFSET"], L["BASE_ARROW_OFFSET"]
    x1 = int(cx + top * math.cos(needle))
    y1 = int(cy + top * math.sin(needle))
    x2 = int(cx + base * math.cos(needle + (30 * DEG_TO_RAD)))
    y2 = int(cy + base * math.sin(needle + (30 * DEG_TO_RAD)))
    x3 = int(cx + base * math.cos(needle - (30 * DEG_TO_RAD)))
    y3 = int(cy + base * math.sin(needle - (30 * DEG_TO_RAD)))
    d.fill_triangle(x1, y1, x2, y2, x3, y3, True)
    d.theme_apply(_it("FG_NOTIFICATION"), _it("BG_NOTIFICATION"))
    buf = "%d%c" % (int(bearing), 176)
    cc = L["BEARING_AND_DIST_X_CENTER"]
    d.print_at(cc - ((len(buf) * 8) >> 1), cy - 16, buf, FONT_3)
    buf = "%d.%d km" % (dist_x10 // 10, dist_x10 - (dist_x10 // 10) * 10)
    d.print_at(cc - ((len(buf) * 8) >> 1), cy + 2, buf, FONT_3)
    d.theme_reset()


def _tx_stop_frame(d):
    """menuTxScreenHandleTxTermination(): очищення, рамка з тінню (FG_DECORATION на BG_NOTIFICATION)."""
    d.theme_reset()
    d.clear_buf()
    d.theme_apply(_it("FG_DECORATION"), _it("BG_NOTIFICATION"))
    d.draw_round_rect_with_shadow(4, 4, 120 + 32, sim.H - 6, 5, True)


def scr_tx_error(d, st):
    """Передача заборонена (TXSTOP_RX_ONLY): «ПОМИЛКА» кольором помилки, нижче причина (канал «лише прийом»)."""
    _tx_stop_frame(d)
    d.theme_apply(_it("FG_ERROR_NOTIFICATION"), _it("BG_NOTIFICATION"))
    d.print_centered(4 + (L["DISPLAY_V_EXTRA_PIXELS"] // 4), UA["error"], FONT_4)
    d.print_centered((sim.H - 24) - (L["DISPLAY_V_EXTRA_PIXELS"] // 4), UA["rx_only"], FONT_3)
    d.theme_reset()


def scr_tx_timeout(d, st):
    """Перевищено час передачі (TXSTOP_TIMEOUT): «ТАЙМАУТ» кольором попередження посередині рамки."""
    _tx_stop_frame(d)
    d.theme_apply(_it("FG_WARNING_NOTIFICATION"), _it("BG_NOTIFICATION"))
    d.print_centered((sim.H - 32) // 2, UA["timeout"], FONT_4)
    d.theme_reset()


def scr_splash(d, st):
    """Заставка української збірки: updateScreen() у uiSplashScreen.c -- лише гасло по центру; тло екрана -- BG_SPLASHSCREEN."""
    d.theme_reset()
    d.theme_apply(_it("FG_SPLASHSCREEN"), _it("BG_SPLASHSCREEN"))
    d.clear_buf()
    d.print_centered((sim.H - 16) // 2, SLOGAN_POWER_ON, FONT_3)
    d.theme_reset()


# ---------------------------------------------------------------------------------------------------------------------------------
#  Супутник і GPS (menuSatelliteScreen.c, menuGPS.c)
# ---------------------------------------------------------------------------------------------------------------------------------

def _f32(x):
    """Округлення до float32 (у C ці величини -- float)."""
    return struct.unpack("<f", struct.pack("<f", x))[0]


def sample_pass():
    """Приклад траєкторії польоту: (азимут, висота) у градусах кожні 30 с від AOS до LOS -- ВИГАДАНІ, але з тим самим перетворенням, що у прошивці
    (результати мають цілу частину -- azimuthAsInteger/elevationAsInteger)."""
    pts = []
    for k in range(0, 21):
        t = k / 20.0
        az = int(215 + 150 * t) % 360
        el = int(52 * math.sin(math.pi * t))
        pts.append((az, el))
    return pts


def scr_satellite(d, st):
    """Екран супутника, полярний вигляд до початку польоту: SATELLITE_SCREEN_SELECTED_SATELLITE_POLAR (menuSatelliteScreen.c). Траєкторія й час -- приклад."""
    d.theme_reset()
    d.clear_buf()
    sx = L_SAT["POLAR_GRAPHICS_X_OFFSET"] + (sim.W // 2)
    max_r = L_SAT["MAX_RADIUS"]
    d.theme_apply(_it("FG_CHANNEL_NAME"), _it("BG"))
    d.print_at(4, (sim.H // 2) - 4, "SO-50", FONT_2)
    d.theme_apply(_it("FG_POLAR_DRAWING"), _it("BG"))
    d.draw_circle(sx, sim.H // 2, max_r, True)
    d.draw_circle(sx, sim.H // 2, (max_r // 3) * 2, True)
    d.draw_circle(sx, sim.H // 2, (max_r // 3), True)
    d.fast_vline(sx, (sim.H // 2) - (max_r + 4), (max_r + 4) * 2, True)
    d.fast_hline(sx - (max_r + 4), sim.H // 2, (max_r + 4) * 2, True)
    d.theme_reset()
    # до початку польоту: «Макс:52°» знизу, зворотний відлік зверху (12:34 до AOS)
    d.print_at(4, (sim.H - 16) - 4, "%s:%02d%c" % (UA["maximum"], 52, 176), FONT_3)
    d.print_at(8, 4, "-%d:%02d" % (12, 34), FONT_2)
    last_x = last_y = 0.0
    sat_x = sat_y = None
    for n, (az_i, el_i) in enumerate(sample_pass()):
        az = _f32(math.radians(az_i))
        el_factor = _f32((1 - (abs(el_i) / 90)) * max_r)
        s_, c_ = _f32(math.sin(az)), _f32(math.cos(az))
        x = _f32(sx + (s_ * el_factor))
        y = _f32((sim.H // 2) - (c_ * el_factor))
        if n == 0:
            sat_x, sat_y = int(x), int(y)
        else:
            d.draw_line(int(last_x), int(last_y), int(x), int(y), True)
        last_x, last_y = x, y
    d.theme_apply(_it("FG_SATELLITE_COLOUR"), _it("BG"))
    d.fill_circle(sat_x, sat_y, L_SAT["DOT_RADIUS"] + 1, True)
    d.theme_reset()
    # вертикальний S-метр праворуч (8 пікселів): рівень -105 дБм
    bar_w = 8
    rssi = min(max(0, st["rssi_sat"] - L["SMETER_S0"]), (L["SMETER_S9"] - L["SMETER_S0"]))
    rssi = (rssi * sim.H) // (L["SMETER_S9"] - L["SMETER_S0"])
    d.theme_apply(_it("FG_RSSI_BAR"), _it("BG"))
    d.fill_rect(sim.W - bar_w, 0, bar_w, sim.H - rssi, True)
    d.fill_rect(sim.W - bar_w, sim.H - rssi, bar_w, rssi, False)
    d.theme_reset()


def maidenhead(lat, lon):
    """coordsToMaidenhead() (uiUtilities.c): шестизнаковий локатор."""
    out = [""] * 6
    ll = lon
    for i in range(2):
        ll = ll / (20.0 if i == 0 else 10.0) + 9.0
        c = int(ll)
        out[0 + i] = chr(c + ord("A"))
        ll -= c
        ll *= 10.0
        c = int(ll)
        out[2 + i] = chr(c + ord("0"))
        ll -= c
        ll *= 24.0
        c = int(ll)
        out[4 + i] = chr(c + ord("A"))
        ll = lat
    return "".join(out)


# Приклад супутників GNSS (номер, відношення сигнал/шум): вигадані.
GPS_SATS = ((5, 38), (12, 45), (15, 30), (18, 42), (21, 33), (25, 47), (29, 26))
BD_SATS = ((6, 35), (9, 41), (13, 28), (22, 36))


def _gps_bars(d, sats, pos, fg_item):
    """displayBars() (menuGPS.c): стовпчик на супутник, цифри номера над ним (FG_GPS_NUMBER), стовпчик -- fg_item."""
    spacing = 9
    for number, snr in sats:
        if snr <= 0:
            continue
        x = LG["RSSI_X_OFFSET"] + 2 + pos * spacing
        if x > (sim.W - spacing + 2):
            break
        rssi = min(LG["MAX_RSSI_Y_PIXELS"], int(LG["MAX_RSSI_Y_PIXELS"] * 0.020 * snr))
        d.theme_apply(_it("FG_GPS_NUMBER"), _it("BG"))
        n = number % 100
        d.print_at(x + 1, LG["RSSI_BARS_Y_POS"], str(n % 10), FONT_1)
        d.print_at(x + 1, LG["RSSI_BARS_Y_POS"] - 8, str(n // 10), FONT_1)
        d.theme_apply(fg_item, _it("BG"))
        d.fill_rect(x, LG["RSSI_BARS_Y_POS"] - 12 - 2 - rssi, spacing - 2, rssi, False)
        d.theme_reset()
        pos += 1
        if pos > (LG["NUM_BARS"] - 1):
            return pos
    return pos


def scr_gps(d, st):
    """Екран GPS, сторінка 1/3 (координати + смуги сигналу): updateScreen() і displayCoords()/displayRSSI() у menuGPS.c. Координати й супутники -- приклад.
    УВАГА: в цій збірці (FORK_NO_GPS_MENU, applicationMain.h) пункт «GPS» з меню прибрано, а menuGPS() -- заглушка (рація без GPS-приймача), тож цей екран на ній
    НЕ З'ЯВЛЯЄТЬСЯ. Він лишений у передпоказі, бо лише на ньому видно три елементи теми «GPS ...»; у збірці з GPS-приймачем екран виглядав би так."""
    d.theme_reset()
    d.clear_buf()
    menu_display_title(d, UA["gps"])
    d.theme_apply(_it("FG_MENU_NAME"), _it("BG"))
    d.print_core(0, 3, "1/3", FONT_1, ALIGN_RIGHT, False)
    d.theme_reset()
    lat, lon = (50, 4501), (30, 5234)                               # 50.4501 N, 30.5234 E (ціла частина, десятитисячні)
    sym = UA["symbols"]
    lat_s = "%02d.%04d%s" % (lat[0], lat[1], sym[0])
    lon_s = "%03d.%04d%s" % (lon[0], lon[1], sym[2])
    mh = maidenhead(lat[0] + lat[1] / 10000.0, lon[0] + lon[1] / 10000.0)
    d.print_at(5, 16, lat_s, FONT_3)
    d.print_at(sim.W - ((9 * 8) + 5), 16, lon_s, FONT_3)
    d.print_at(LG["MAIDENHEAD_HDOP_MARGIN"], LG["MAIDENHEAD_HDOP_Y_POS"], mh, FONT_3)
    acc = "+/-%dm" % 3
    d.print_at(sim.W - ((len(acc) * 8) + LG["MAIDENHEAD_HDOP_MARGIN"]), LG["MAIDENHEAD_HDOP_Y_POS"], acc, FONT_3)
    spacing = 9
    for i in range(LG["NUM_BARS"]):                                  # основа кожного стовпчика -- 2 рядки FG_DEFAULT
        d.fill_rect(LG["RSSI_X_OFFSET"] + 2 + i * spacing, LG["RSSI_BARS_Y_POS"] - 12 - 2, spacing - 2, 2, False)
    pos = _gps_bars(d, GPS_SATS, 0, _it("FG_GPS_COLOUR"))
    _gps_bars(d, BD_SATS, pos, _it("FG_BD_COLOUR"))


def scr_input(d, st):
    """Ввід номера TG: updateScreen() у uiTxTgPcContactOwnId.c -- заголовок у рамці з тінню, число й курсор кольором FG_TEXT_INPUT."""
    title = UA["tg_entry"]
    digits = "255"
    d.theme_reset()
    d.clear_buf()
    d.theme_apply(_it("FG_DECORATION"), _it("BG_MENU_NAME"))
    d.draw_round_rect_with_shadow(2, 8 - 1, sim.W - 6, L["TITLE_BOX_HEIGHT"], 3, True)
    d.theme_apply(_it("FG_MENU_NAME"), _it("BG_MENU_NAME"))
    d.print_at(((sim.W - len(title) * 8) >> 1) - 2, 8, title, FONT_3)
    d.theme_apply(_it("FG_TEXT_INPUT"), _it("BG"))
    d.print_centered((sim.H // 2), digits, FONT_3)
    slen = len(digits) * 8
    d.print_core(((sim.W - slen) >> 1) + slen, sim.H // 2, "_", FONT_3, ALIGN_LEFT, False)       # курсор (фаза «видно»)
    d.theme_reset()


# ---------------------------------------------------------------------------------------------------------------------------------
SCREENS = [
    ("channel", "Канал: очікування", scr_channel),
    ("channel_qso", "Канал: виклик", scr_channel_qso),
    ("channel_details", "Канал FM: параметри", scr_channel_details),
    ("transmit", "Передача", scr_transmit),
    ("tx_error", "Передача: помилка", scr_tx_error),
    ("tx_timeout", "Передача: таймаут", scr_tx_timeout),
    ("menu", "Меню", scr_menu),
    ("options", "Налаштування", scr_options),
    ("input", "Ввід номера", scr_input),
    ("notification", "Сповіщення", scr_notification),
    ("splash", "Заставка", scr_splash),
    ("satellite", "Супутник", scr_satellite),
    ("gps", "GPS (у цій збірці екрана нема)", scr_gps),
]
SCREEN_FUNCS = {k: f for k, _t, f in SCREENS}
SCREEN_TITLES = {k: t for k, t, _f in SCREENS}


def render(key, st=None):
    """Display з намальованим екраном `key`."""
    d = sim.Display()
    SCREEN_FUNCS[key](d, dict(SAMPLE if st is None else st))
    return d
