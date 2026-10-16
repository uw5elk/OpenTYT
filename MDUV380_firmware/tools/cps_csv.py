#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cps_csv.py -- R26 V1: обмін кодплуга з рації з CSV у форматі OpenGD77 CPS (Channels / Contacts / TG_Lists / Zones / APRS / DTMF).

Експорт ЛИШЕ ЧИТАЄ. Імпорт будує новий образ кодплуга в пам'яті, нічого не пише сам: у рацію він іде ТІЄЮ САМОЮ дорогою,
що й відновлення з бекапу (tools/cps_restore.py: страхова копія -> діалог зі списком змін -> лише відмінні сектори ->
перечитування -> SHA-256 -> C 6 1). Окремого «швидкого запису» нема.

ФОРМАТ (claude/cps-csv-format.md у проєкті): роздільник `;`, CRLF, UTF-8 без BOM, частоти з табуляцією попереду
(`\\t446,00625`), десяткова ознака -- кома АБО крапка (читаємо обидві; пишемо за системною локаллю або за явним параметром).

КИРИЛИЦЯ (V1.2). CPS бере сирі 16 байтів назви з кодплуга, читає їх як Latin-1 і пише в CSV у UTF-8. Тому «Папуга»
(в кодплузі GBK `A7 B1 A7 D1 ...`) у CSV виглядає як `§±§Ñ§á§å§Ô§Ñ`. Це оборотно: `поле.encode('latin-1')` -> сирі байти.
Ми пишемо ту саму «сумісну» колонку (CPS її читає) і додаємо в кінець рядка колонку `Name (readable)` з читабельною назвою
(через єдину codeplug_view.decode_name_ex). Правила імпорту назви:
  * сумісна колонка -- джерело істини, коли її змінено (або коли рядок новий і колонки не збігаються);
  * якщо сумісну не чіпали, а читабельну змінено -- береться читабельна (так редагує людина);
  * нова назва з читабельного тексту кодується за V1.9: усі символи є в GB2312 -> GBK (читається в CPS); є «і ї є ґ»
    -> cp1251 (в CPS виглядатиме зіпсовано -- один раз на сеанс про це попереджаємо);
  * посилання між розділами (зона -> канали, TG-список -> контакти, канал -> контакт / TG-список / APRS) -- ЗА НАЗВАМИ,
    у сумісному вигляді АБО в читабельному; не знайдено або неоднозначно -> ВІДМОВА з переліком усіх проблем (V1.6).

ПОВНА ОБОРОТНІСТЬ (T1). Імпорт міняє поле запису лише тоді, коли текст у CSV відрізняється від того, що експортується з
наявного запису (поля, яких у CSV нема -- VFO-зсув, STE, «roaming» тощо -- не чіпаються взагалі). Тож
експорт -> імпорт без правок повертає кодплуг байт-у-байт, навіть із сміттям у неописаних полях.

Значення полів каналу (потужність, шумодав, TA, координати), яких у проєктному документі нема в прикладах, ВИВЕДЕНО З КОДУ
ПРОШИВКИ (codeplug.c / menuChannelDetails.c), а не з зразка CPS -- кроки BM1/BM9/BM10. Нерозпізнане значення «м'якої»
колонки не ламає імпорт: поле лишається як було, у звіті з'являється попередження.
"""
import csv
import decimal
import io
import locale
import os
import re
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cps_link as cl  # noqa: E402
import codeplug_view as cv  # noqa: E402

FILE_NAMES = {"channels": "Channels.csv", "contacts": "Contacts.csv", "tg_lists": "TG_Lists.csv", "zones": "Zones.csv",
              "aprs": "APRS.csv", "dtmf": "DTMF.csv"}
READABLE = "Name (readable)"

CONTACT_HDR = ["Contact Name", "ID", "ID Type", "TS Override"]
TG_HDR = ["TG List Name"] + ["Contact%d" % i for i in range(1, 33)]
ZONE_HDR = ["Zone Name"] + ["Channel%d" % i for i in range(1, 81)]
CHANNEL_HDR = ["Channel Number", "Channel Name", "Channel Type", "Rx Frequency", "Tx Frequency", "Bandwidth (kHz)", "Colour Code",
               "Timeslot", "Contact", "TG List", "DMR ID", "TS1_TA_Tx", "TS2_TA_Tx ID", "RX Tone", "TX Tone", "Squelch", "Power",
               "Rx Only", "Zone Skip", "All Skip", "TOT", "VOX", "No Beep", "No Eco", "APRS", "Latitude", "Longitude", "Use Location"]
APRS_HDR = ["APRS config Name", "SSID", "Via1", "Via1 SSID", "Via2", "Via2 SSID", "Icon table", "Icon", "Comment text", "Ambiguity",
            "Use position", "Latitude", "Longitude", "TX Frequency", "Transmit QSY", "Baud rate setting"]
DTMF_HDR = ["Contact Name", "Code"]

# --- адреси (codeplug.c; кодплугові, без FLASH_ADDRESS_OFFSET) ---
ADDR_APRS = 0x1588            # CODEPLUG_ADDR_APRS_CONFIGS
APRS_SIZE = 64                # CODEPLUG_APRS_CONFIG_DATA_STRUCT_SIZE
APRS_MAX = 8                  # codeplugAPRSInitCache(): while (aprsIdx <= 8)
APRS_MAGIC = 0x4153           # APRS_MAGIC_VERSION (0x4152 -- старий формат, читається так само)
ADDR_DTMF = 0x2F88            # CODEPLUG_ADDR_DTMF_CONTACTS
DTMF_SIZE = 32
DTMF_MAX = 63
DTMF_ALPHABET = "0123456789ABCD*#"     # ГІПОТЕЗА: байт коду = індекс у цьому рядку (dtmfSequencePrepare шле байти як є)
CH_SIZE = cl.CP_CHANNEL_SIZE  # 56
TOT_STEP_S = 15               # tot * 15 секунд (uiTxScreen.c)

POWER_NAMES = ["50mW", "250mW", "500mW", "750mW", "1W", "2W", "3W", "5W", "10W"]   # POWER_LEVELS для MD-UV390 Plus 10W
TA_NAMES = ["Off", "APRS", "Text", "APRS & Text"]                                 # CodeplugTATxDestination_t
CALL_TYPE_NAMES = {0: "Group", 1: "Private", 2: "All Call"}
CTCSS_MIN, CTCSS_MAX = 600, 3000                       # десяті частки герца


class CsvError(cl.CpsError):
    pass


class CsvImportRefused(CsvError):
    """Імпорт відхилено ДО будь-якого запису: усі знайдені проблеми одним списком."""

    def __init__(self, problems):
        self.problems = list(problems)
        shown = self.problems[:40]
        text = "Імпорт CSV відхилено (проблем: %d). Нічого не записано.\n" % len(self.problems)
        text += "\n".join("  - " + p for p in shown)
        if len(self.problems) > len(shown):
            text += "\n  ... і ще %d" % (len(self.problems) - len(shown))
        super().__init__(text)


class Session:
    """Стан одного сеансу роботи (прапорець «про cp1251 вже попередили»)."""

    def __init__(self):
        self.warned_cp1251 = False


# =========================================================================================
#  Текст і числа
# =========================================================================================

def system_decimal_point():
    """Десятковий знак системної локалі ('.' чи ','). Нічого не міняє глобально: локаль повертається як була."""
    try:
        old = locale.setlocale(locale.LC_NUMERIC)
        try:
            locale.setlocale(locale.LC_NUMERIC, "")
            dp = locale.localeconv().get("decimal_point") or "."
        finally:
            locale.setlocale(locale.LC_NUMERIC, old)
    except (locale.Error, ValueError):
        return "."
    return dp if dp in (",", ".") else "."


def compat_text(raw16):
    """Сирі байти назви -> рядок, як його пише CPS (Latin-1 -> UTF-8)."""
    return cv.name_bytes(raw16).decode("latin-1")


def readable_text(raw16):
    return cv.decode_name_ex(raw16)[0]


def pad16(b):
    return bytes(b[:16]).ljust(16, b"\xff")


def encode_new_name(text, session=None):
    """V1.9: усі символи є в GB2312 -> GBK; інакше cp1251. Повертає (байти, кодування). Не кодується -> ValueError."""
    try:
        return text.encode("gb2312"), "GBK"
    except UnicodeEncodeError:
        pass
    try:
        return text.encode("cp1251"), "cp1251"
    except UnicodeEncodeError:
        bad = sorted({c for c in text if not _enc_ok(c)})
        raise ValueError("символи %s не кодуються ні в GB2312, ні в cp1251" % "".join(bad))


def _enc_ok(c):
    for e in ("gb2312", "cp1251"):
        try:
            c.encode(e)
            return True
        except UnicodeEncodeError:
            pass
    return False


def norm_text(s):
    """Для порівняння значень: без пробілів по краях і табуляції, кома = крапка, без регістру."""
    return (s or "").strip().strip("\t").strip().replace(",", ".").casefold()


def fmt_scaled(value, decimals, dp):
    """value (ціле) / 10**decimals у текст з десятковим знаком dp."""
    if decimals == 0:
        return str(value)
    sign = "-" if value < 0 else ""
    v = abs(value)
    return "%s%d%s%0*d" % (sign, v // 10 ** decimals, dp, decimals, v % 10 ** decimals)


def parse_scaled(text, decimals):
    """Текст ('446,00625' / '446.00625' / '\\t446,00625') -> ціле * 10**decimals. Забагато знаків -> ValueError."""
    t = (text or "").strip().strip("\t").strip().replace(",", ".")
    if not re.fullmatch(r"[+-]?\d+(\.\d*)?|[+-]?\.\d+", t):
        raise ValueError("не число: %r" % text)
    d = decimal.Decimal(t) * (10 ** decimals)
    if d != d.to_integral_value():
        raise ValueError("забагато знаків після коми (дозволено %d): %r" % (decimals, text))
    return int(d)


def bcd_le(value, nbytes=4):
    return bytes.fromhex("%0*d" % (nbytes * 2, value))[::-1]


YES = {"yes", "true", "on", "1", "y", "так", "enabled"}
NO = {"no", "false", "off", "0", "n", "ні", "disabled", "none", ""}


def parse_bool(text):
    t = (text or "").strip().casefold()
    if t in YES:
        return True
    if t in NO:
        return False
    raise ValueError("очікувалось Yes/No: %r" % text)


# =========================================================================================
#  Образ кодплуга
# =========================================================================================

class Image:
    """Змінюваний образ: EEPROM (адреси кодплуга) і флеш-частина (адреси кодплуга від flash_cp_start)."""

    def __init__(self, eeprom, flash, flash_cp_start):
        self.eeprom = bytearray(eeprom)
        self.flash = bytearray(flash)
        self.base = flash_cp_start

    @classmethod
    def from_codeplug(cls, cp):
        return cls(cp.eeprom, cp.flash, cp.flash_cp_start)

    def ee(self, a, n):
        return bytes(self.eeprom[a:a + n])

    def set_ee(self, a, b):
        self.eeprom[a:a + len(b)] = b

    def fl(self, a, n):
        o = a - self.base
        if o < 0 or o + n > len(self.flash):
            raise CsvError("адреса кодплуга 0x%X поза флеш-частиною образу" % a)
        return bytes(self.flash[o:o + n])

    def set_fl(self, a, b):
        o = a - self.base
        if o < 0 or o + len(b) > len(self.flash):
            raise CsvError("адреса кодплуга 0x%X поза флеш-частиною образу" % a)
        self.flash[o:o + len(b)] = b

    # --- канали ---
    def _bank_header_addr(self, bank):
        if bank == 0:
            return "ee", cl.CP_ADDR_CHANNEL_HEADER_EEPROM
        return "fl", cl.CP_ADDR_CHANNEL_HEADER_FLASH + (bank - 1) * (16 + cl.CP_CHANNELS_PER_BANK * CH_SIZE)

    def _get(self, where, a, n):
        return self.ee(a, n) if where == "ee" else self.fl(a, n)

    def _set(self, where, a, b):
        if where == "ee":
            self.set_ee(a, b)
        else:
            self.set_fl(a, b)

    def channel_in_use(self, number):
        bank, slot = divmod(number - 1, cl.CP_CHANNELS_PER_BANK)
        where, h = self._bank_header_addr(bank)
        return bool((self._get(where, h + (slot >> 3), 1)[0] >> (slot & 7)) & 1)

    def set_channel_in_use(self, number, on):
        bank, slot = divmod(number - 1, cl.CP_CHANNELS_PER_BANK)
        where, h = self._bank_header_addr(bank)
        b = self._get(where, h + (slot >> 3), 1)[0]
        b = (b | (1 << (slot & 7))) if on else (b & ~(1 << (slot & 7)) & 0xFF)
        self._set(where, h + (slot >> 3), bytes([b]))

    def channel_rec(self, number):
        bank, slot = divmod(number - 1, cl.CP_CHANNELS_PER_BANK)
        where, h = self._bank_header_addr(bank)
        return self._get(where, h + 16 + slot * CH_SIZE, CH_SIZE)

    def set_channel_rec(self, number, rec):
        assert len(rec) == CH_SIZE
        bank, slot = divmod(number - 1, cl.CP_CHANNELS_PER_BANK)
        where, h = self._bank_header_addr(bank)
        self._set(where, h + 16 + slot * CH_SIZE, bytes(rec))

    def channels(self):
        return [(n, self.channel_rec(n)) for n in range(1, cl.CP_CHANNELS_BANKS * cl.CP_CHANNELS_PER_BANK + 1) if self.channel_in_use(n)]

    # --- контакти (слот 0-based; номер = слот + 1) ---
    def contacts(self):
        out = []
        for i in range(cl.CP_CONTACTS_MAX):
            rec = self.fl(cl.CP_ADDR_CONTACTS + i * cl.CP_CONTACT_SIZE, cl.CP_CONTACT_SIZE)
            if rec[0] != 0xFF:             # codeplugInitContactsCache(): name[0] != 0xFF
                out.append((i, rec))
        return out

    def set_contact(self, slot, rec):
        self.set_fl(cl.CP_ADDR_CONTACTS + slot * cl.CP_CONTACT_SIZE, rec)

    # --- TG-списки ---
    def groups(self):
        lens = self.fl(cl.CP_ADDR_RX_GROUP_LEN, cl.CP_RXGROUPS_MAX)
        out = []
        for i in range(cl.CP_RXGROUPS_MAX):
            if 0 < lens[i] <= cv.RXGROUP_MAX_CONTACTS:
                out.append((i, self.fl(cl.CP_ADDR_RX_GROUP + i * cl.CP_RXGROUP_SIZE, cl.CP_RXGROUP_SIZE), lens[i]))
        return out

    def set_group(self, slot, rec, length):
        self.set_fl(cl.CP_ADDR_RX_GROUP + slot * cl.CP_RXGROUP_SIZE, rec)
        self.set_fl(cl.CP_ADDR_RX_GROUP_LEN + slot, bytes([length]))

    def clear_group_len(self, slot):
        self.set_fl(cl.CP_ADDR_RX_GROUP_LEN + slot, b"\x00")

    # --- зони ---
    def zone_format(self):
        return 80 if 0x00 <= self.ee(cv.CP_ADDR_ZONE_FORMAT_BYTE, 1)[0] <= 0x04 else 16

    def zone_stride(self):
        return 16 + 2 * self.zone_format()

    def zones(self):
        mask = self.ee(cl.CP_ADDR_EX_ZONE_INUSE, 32)
        st = self.zone_stride()
        return [(bit, self.ee(cl.CP_ADDR_EX_ZONE_LIST + bit * st, st)) for bit in range(cl.CP_ZONES_MAX) if (mask[bit >> 3] >> (bit & 7)) & 1]

    def set_zone(self, bit, rec):
        self.set_ee(cl.CP_ADDR_EX_ZONE_LIST + bit * self.zone_stride(), rec)
        self._zone_mask(bit, True)

    def clear_zone(self, bit):
        self._zone_mask(bit, False)

    def _zone_mask(self, bit, on):
        a = cl.CP_ADDR_EX_ZONE_INUSE + (bit >> 3)
        b = self.ee(a, 1)[0]
        b = (b | (1 << (bit & 7))) if on else (b & ~(1 << (bit & 7)) & 0xFF)
        self.set_ee(a, bytes([b]))

    # --- APRS ---
    def aprs(self):
        out = []
        for i in range(APRS_MAX):
            rec = self.ee(ADDR_APRS + i * APRS_SIZE, APRS_SIZE)
            magic = struct.unpack_from("<H", rec, 62)[0]
            if rec[0] != 0xFF and magic in (APRS_MAGIC, 0x4152):
                out.append((i, rec))
        return out

    def set_aprs(self, slot, rec):
        self.set_ee(ADDR_APRS + slot * APRS_SIZE, rec)

    # --- DTMF ---
    def dtmf(self):
        out = []
        for i in range(DTMF_MAX):
            rec = self.ee(ADDR_DTMF + i * DTMF_SIZE, DTMF_SIZE)
            if rec[0] not in (0xFF, 0x00):
                out.append((i, rec))
        return out

    def set_dtmf(self, slot, rec):
        self.set_ee(ADDR_DTMF + slot * DTMF_SIZE, rec)


# =========================================================================================
#  Поля каналу: розбір / запис
# =========================================================================================

# зсуви в 56-байтовому записі (CodeplugChannel_t, codeplug.h)
O_NAME, O_RX, O_TX, O_MODE, O_POWER = 0, 16, 20, 24, 25
O_LAT, O_TOT, O_LON_LO, O_RXTONE, O_TXTONE, O_LON2 = 26, 27, 30, 32, 34, 36
O_FLAG1L, O_DMRID, O_GROUP, O_COLOR, O_APRS, O_CONTACT = 38, 39, 43, 44, 45, 46
O_FLAG1, O_FLAG2, O_FLAG3, O_FLAG4, O_SQL = 48, 49, 50, 51, 55

F4_SQL, F4_BW25, F4_RXONLY, F4_ALLSKIP, F4_ZONESKIP, F4_VOX, F4_POWER = 0x01, 0x02, 0x04, 0x10, 0x20, 0x40, 0x80
FL_DMRID, FL_NOBEEP, FL_NOECO, FL_USELOC = 0x80, 0x40, 0x20, 0x08
F2_TS2 = 0x40


def new_channel_template(digital):
    """Новий канал: нульовий запис з типовими значеннями (за codeplug.c: ID за замовчуванням 0x001600, тони «нема»)."""
    r = bytearray(CH_SIZE)
    r[O_NAME:O_NAME + 16] = b"\xff" * 16
    r[O_MODE] = 1 if digital else 0
    struct.pack_into("<H", r, O_RXTONE, 0xFFFF)
    struct.pack_into("<H", r, O_TXTONE, 0xFFFF)
    r[O_DMRID] = 0x00
    r[O_DMRID + 1] = 0x16
    r[O_DMRID + 2] = 0x00
    r[O_COLOR] = 1
    return r


def tone_text(raw, dp):
    if raw in (0, 0xFFFF):
        return "None"
    if raw & 0x8000:
        return "D%03X%s" % (raw & 0x3FFF, "I" if raw & 0x4000 else "N") if (raw & 0x3FFF) <= 0xFFF and all(
            c in "01234567" for c in "%03X" % (raw & 0x3FFF)) else "0x%04X" % raw
    if raw & 0x4000:
        return "0x%04X" % raw
    nib = [(raw >> s) & 0xF for s in (12, 8, 4, 0)]
    if any(n > 9 for n in nib):
        return "0x%04X" % raw
    tenths = nib[0] * 1000 + nib[1] * 100 + nib[2] * 10 + nib[3]
    return fmt_scaled(tenths, 1, dp)


def parse_tone(text):
    t = (text or "").strip()
    if t.casefold() in ("none", "", "off", "disabled"):
        return 0xFFFF
    m = re.fullmatch(r"0x([0-9A-Fa-f]{4})", t)
    if m:
        return int(m.group(1), 16)
    m = re.fullmatch(r"[Dd]([0-7]{3})([NnIi])", t)
    if m:
        return 0x8000 | (0x4000 if m.group(2).upper() == "I" else 0) | int(m.group(1), 16)
    tenths = parse_scaled(t, 1)
    if not (CTCSS_MIN <= tenths <= CTCSS_MAX):
        raise ValueError("CTCSS поза межами 60,0..300,0 Гц: %r" % text)
    return int("%04d" % tenths, 16)


def latlon_text(b3, dp):
    v = b3[0] | (b3[1] << 8) | (b3[2] << 16)
    ip, dec = (v & 0x7FFFFF) >> 15, v & 0x7FFF
    if dec > 9999:
        return "0x%06X" % v
    return "%s%d%s%04d" % ("-" if v & 0x800000 else "", ip, dp, dec)


def parse_latlon(text, limit):
    t = (text or "").strip()
    m = re.fullmatch(r"0x([0-9A-Fa-f]{6})", t)
    if m:
        v = int(m.group(1), 16)
        return bytes([v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF])
    s = parse_scaled(t, 4)
    if abs(s) > limit * 10000:
        raise ValueError("поза межами ±%d°: %r" % (limit, text))
    v = ((abs(s) // 10000) << 15) + (abs(s) % 10000)
    if s < 0 or t.startswith("-"):
        v |= 0x800000
    return bytes([v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF])


def power_text(n):
    if n == 0:
        return "Master"
    if 1 <= n <= len(POWER_NAMES):
        return POWER_NAMES[n - 1]
    return "0x%02X" % n


def parse_power(text):
    t = (text or "").strip()
    tl = t.casefold()
    if tl in ("master", ""):
        return 0
    for i, nme in enumerate(POWER_NAMES):
        if tl == nme.casefold():
            return i + 1
    m = re.fullmatch(r"p(\d)", tl)
    if m and 1 <= int(m.group(1)) <= len(POWER_NAMES):
        return int(m.group(1))
    m = re.fullmatch(r"0x([0-9a-f]{2})", tl)
    if m:
        return int(m.group(1), 16)
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(mw|w)?", tl)
    if m:
        val = decimal.Decimal(m.group(1).replace(",", "."))
        unit = m.group(2) or ("w" if val <= 10 else "mw")
        mw = val if unit == "mw" else val * 1000
        for i, nme in enumerate(POWER_NAMES):
            ref = decimal.Decimal(nme[:-2]) if nme.endswith("mW") else decimal.Decimal(nme[:-1]) * 1000
            if ref == mw:
                return i + 1
    raise ValueError("невідома потужність: %r" % text)


def sql_text(n):
    if n == 0:
        return "Master"
    if 1 <= n <= 21:
        return "%d%%" % (5 * (n - 1))
    return "0x%02X" % n


def parse_sql(text):
    t = (text or "").strip().casefold()
    if t in ("master", ""):
        return 0
    m = re.fullmatch(r"(\d+)\s*%?", t)
    if m and int(m.group(1)) % 5 == 0 and int(m.group(1)) <= 100:
        return int(m.group(1)) // 5 + 1
    m = re.fullmatch(r"0x([0-9a-f]{2})", t)
    if m:
        return int(m.group(1), 16)
    raise ValueError("невідомий шумодав: %r" % text)


class Ctx:
    """Усе, що потрібне для перетворення полів, що посилаються на інші розділи (за ПОТОЧНИМИ назвами)."""

    def __init__(self, dp=",", contact_name=None, group_name=None, aprs_name=None, resolve=None):
        self.dp = dp
        self.contact_name = contact_name or (lambda n: "None")      # номер 1.. -> сумісний текст
        self.group_name = group_name or (lambda n: "None")
        self.aprs_name = aprs_name or (lambda n: "None")
        self.resolve = resolve                                        # resolve(kind, text) -> (номер, помилка)


def _ref_text(n, namefn):
    return "None" if n == 0 else namefn(n)


# Опис колонок каналу: (назва, застосовність 'A' аналог / 'D' цифра / 'B' обидва, м'яка?, decode(rec, ctx), encode(rec, text, ctx))
def _c_type_dec(r, c):
    return "Digital" if r[O_MODE] != 0 else "Analogue"


def _c_type_enc(r, t, c):
    tl = t.strip().casefold()
    if tl.startswith("dig"):
        r[O_MODE] = 1
    elif tl.startswith("ana"):
        r[O_MODE] = 0
    else:
        raise ValueError("Channel Type: Analogue або Digital, а не %r" % t)


def _freq_dec(off):
    def f(r, c):
        v = cv.freq_bcd_le(r[off:off + 4])
        if v is None:
            return "0x%08X" % struct.unpack_from("<I", r, off)[0]
        return "\t" + fmt_scaled(v, 5, c.dp)
    return f


def _freq_enc(off):
    def f(r, t, c):
        tt = t.strip().strip("\t").strip()
        m = re.fullmatch(r"0x([0-9A-Fa-f]{8})", tt)
        if m:
            r[off:off + 4] = struct.pack("<I", int(m.group(1), 16))
            return
        v = parse_scaled(tt, 5)
        if not (0 < v <= 99999999):
            raise ValueError("частота поза межами 0..999,99999 МГц: %r" % t)
        r[off:off + 4] = bcd_le(v)
    return f


def _flag(off, mask, invert=False):
    def dec(r, c):
        return "Yes" if bool(r[off] & mask) != invert else "No"

    def enc(r, t, c):
        on = parse_bool(t) != invert
        r[off] = (r[off] | mask) if on else (r[off] & ~mask & 0xFF)
    return dec, enc


_bw_dec = lambda r, c: ("25" if r[O_FLAG4] & F4_BW25 else fmt_scaled(125, 1, c.dp))   # noqa: E731


def _bw_enc(r, t, c):
    v = parse_scaled(t, 1)
    if v == 250:
        r[O_FLAG4] |= F4_BW25
    elif v == 125:
        r[O_FLAG4] &= ~F4_BW25 & 0xFF
    else:
        raise ValueError("Bandwidth: 12,5 або 25 кГц, а не %r" % t)


def _cc_enc(r, t, c):
    v = parse_scaled(t, 0)
    if not 0 <= v <= 15:
        raise ValueError("Colour Code 0..15, а не %r" % t)
    r[O_COLOR] = v


def _ts_enc(r, t, c):
    v = parse_scaled(t, 0)
    if v not in (1, 2):
        raise ValueError("Timeslot 1 або 2, а не %r" % t)
    r[O_FLAG2] = (r[O_FLAG2] | F2_TS2) if v == 2 else (r[O_FLAG2] & ~F2_TS2 & 0xFF)


def _ref_dec(off, kind):
    def f(r, c):
        n = r[off] | (r[off + 1] << 8) if kind == "contact" else r[off]
        return _ref_text(n, {"contact": c.contact_name, "group": c.group_name, "aprs": c.aprs_name}[kind])
    return f


def _ref_enc(off, kind):
    def f(r, t, c):
        tt = (t or "").strip()
        if tt.casefold() in ("none", ""):
            n = 0
        else:
            n, err = c.resolve(kind, tt)
            if err:
                raise LookupError(err)
        if kind == "contact":
            struct.pack_into("<H", r, off, n)
        else:
            r[off] = n
    return f


def _dmrid_dec(r, c):
    if not r[O_FLAG1L] & FL_DMRID:
        return "None"
    return str((r[O_DMRID] << 16) | (r[O_DMRID + 1] << 8) | r[O_DMRID + 2])


def _dmrid_enc(r, t, c):
    tt = (t or "").strip()
    if tt.casefold() in ("none", ""):
        r[O_FLAG1L] &= ~FL_DMRID & 0xFF
        r[O_DMRID:O_DMRID + 3] = bytes([0x00, 0x16, 0x00])        # як codeplugChannelSetOptionalDMRID() без ID
        return
    v = parse_scaled(tt, 0)
    if not 1 <= v <= 16777215:
        raise ValueError("DMR ID 1..16777215, а не %r" % t)
    r[O_FLAG1L] |= FL_DMRID
    r[O_DMRID:O_DMRID + 3] = bytes([(v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF])


def _ta(shift):
    def dec(r, c):
        return TA_NAMES[(r[O_FLAG1] >> shift) & 3]

    def enc(r, t, c):
        tl = re.sub(r"\s+", "", (t or "").casefold())
        table = {"off": 0, "aprs": 1, "text": 2, "aprs&text": 3, "both": 3}
        if tl not in table:
            raise ValueError("TA: Off / APRS / Text / APRS & Text, а не %r" % t)
        r[O_FLAG1] = (r[O_FLAG1] & ~(3 << shift) & 0xFF) | (table[tl] << shift)
    return dec, enc


def _tot_dec(r, c):
    return "Off" if r[O_TOT] == 0 else str(r[O_TOT] * TOT_STEP_S)


def _tot_enc(r, t, c):
    tl = (t or "").strip().casefold()
    if tl in ("off", "disabled", "", "0", "none"):
        r[O_TOT] = 0
        return
    v = parse_scaled(tl, 0)
    if v % TOT_STEP_S or not 0 < v // TOT_STEP_S <= 255:
        raise ValueError("TOT кратний %d с (до %d), а не %r" % (TOT_STEP_S, 255 * TOT_STEP_S, t))
    r[O_TOT] = v // TOT_STEP_S


def _vox_dec(r, c):
    return "On" if r[O_FLAG4] & F4_VOX else "Off"


def _vox_enc(r, t, c):
    on = parse_bool(t)
    r[O_FLAG4] = (r[O_FLAG4] | F4_VOX) if on else (r[O_FLAG4] & ~F4_VOX & 0xFF)


def _sql_enc(r, t, c):
    # «Disabled» CPS пише для значення, якого в коді прошивки нема (поле sql у стоковому CPS не використовується) --
    # лишаємо поле як є, без попередження (ГІПОТЕЗА, перевіряється кроком BM10).
    if (t or "").strip().casefold() == "disabled":
        return
    r[O_SQL] = parse_sql(t)


def _build_columns():
    cols = []

    def add(name, app, soft, dec, enc):
        cols.append({"name": name, "app": app, "soft": soft, "dec": dec, "enc": enc})

    add("Channel Type", "B", False, _c_type_dec, _c_type_enc)
    add("Rx Frequency", "B", False, _freq_dec(O_RX), _freq_enc(O_RX))
    add("Tx Frequency", "B", False, _freq_dec(O_TX), _freq_enc(O_TX))
    add("Bandwidth (kHz)", "A", False, _bw_dec, _bw_enc)
    add("Colour Code", "D", False, lambda r, c: str(r[O_COLOR]), _cc_enc)
    add("Timeslot", "D", False, lambda r, c: "2" if r[O_FLAG2] & F2_TS2 else "1", _ts_enc)
    add("Contact", "D", False, _ref_dec(O_CONTACT, "contact"), _ref_enc(O_CONTACT, "contact"))
    add("TG List", "D", False, _ref_dec(O_GROUP, "group"), _ref_enc(O_GROUP, "group"))
    add("DMR ID", "D", False, _dmrid_dec, _dmrid_enc)
    d, e = _ta(0)
    add("TS1_TA_Tx", "D", True, d, e)
    d, e = _ta(2)
    add("TS2_TA_Tx ID", "D", True, d, e)
    add("RX Tone", "A", False, lambda r, c: tone_text(struct.unpack_from("<H", r, O_RXTONE)[0], c.dp),
        lambda r, t, c: struct.pack_into("<H", r, O_RXTONE, parse_tone(t)))
    add("TX Tone", "A", False, lambda r, c: tone_text(struct.unpack_from("<H", r, O_TXTONE)[0], c.dp),
        lambda r, t, c: struct.pack_into("<H", r, O_TXTONE, parse_tone(t)))
    add("Squelch", "A", True, lambda r, c: sql_text(r[O_SQL]), _sql_enc)
    add("Power", "B", True, lambda r, c: power_text(r[O_POWER]), lambda r, t, c: r.__setitem__(O_POWER, parse_power(t)))
    d, e = _flag(O_FLAG4, F4_RXONLY)
    add("Rx Only", "B", False, d, e)
    d, e = _flag(O_FLAG4, F4_ZONESKIP)
    add("Zone Skip", "B", False, d, e)
    d, e = _flag(O_FLAG4, F4_ALLSKIP)
    add("All Skip", "B", False, d, e)
    add("TOT", "B", True, _tot_dec, _tot_enc)
    add("VOX", "B", True, _vox_dec, _vox_enc)
    d, e = _flag(O_FLAG1L, FL_NOBEEP)
    add("No Beep", "B", True, d, e)
    d, e = _flag(O_FLAG1L, FL_NOECO)
    add("No Eco", "B", True, d, e)
    add("APRS", "B", False, _ref_dec(O_APRS, "aprs"), _ref_enc(O_APRS, "aprs"))
    add("Latitude", "B", True, lambda r, c: latlon_text(r[O_LAT:O_LAT + 1] + r[O_LAT + 2:O_LAT + 4], c.dp),
        lambda r, t, c: r.__setitem__(slice(O_LAT, O_LAT + 1), parse_latlon(t, 90)[0:1]) or
        r.__setitem__(slice(O_LAT + 2, O_LAT + 4), parse_latlon(t, 90)[1:3]))
    add("Longitude", "B", True, lambda r, c: latlon_text(r[O_LON_LO:O_LON_LO + 2] + r[O_LON2:O_LON2 + 1], c.dp),
        lambda r, t, c: r.__setitem__(slice(O_LON_LO, O_LON_LO + 2), parse_latlon(t, 180)[0:2]) or
        r.__setitem__(slice(O_LON2, O_LON2 + 1), parse_latlon(t, 180)[2:3]))
    d, e = _flag(O_FLAG1L, FL_USELOC)
    add("Use Location", "B", True, d, e)
    return cols


CH_COLUMNS = _build_columns()
CH_COLUMN_BY_NAME = {c["name"]: c for c in CH_COLUMNS}


def applies(col, rec):
    digital = rec[O_MODE] != 0
    return col["app"] == "B" or (col["app"] == "D") == digital


# =========================================================================================
#  Експорт
# =========================================================================================

def _writer(f):
    return csv.writer(f, delimiter=";", lineterminator="\r\n")


def _open_out(path):
    return open(path, "w", encoding="utf-8", newline="")


def _names(entities, number_of):
    """{номер: сумісний текст} за наявними записами (щоб посилання експортувались за назвами)."""
    return {number_of(e): compat_text(e[1][:16]) for e in entities}


def make_ctx_for_export(img, dp):
    contacts = {slot + 1: compat_text(rec[:16]) for slot, rec in img.contacts()}
    groups = {slot + 1: compat_text(rec[:16]) for slot, rec, _l in img.groups()}
    aprs = {slot + 1: compat_text(rec[:16][:8]) for slot, rec in img.aprs()}
    return Ctx(dp,
               contact_name=lambda n: contacts.get(n, "#%d" % n),
               group_name=lambda n: groups.get(n, "#%d" % n),
               aprs_name=lambda n: aprs.get(n, "#%d" % n))


def channel_row(number, rec, ctx):
    row = [str(number), compat_text(rec[O_NAME:O_NAME + 16])]
    for col in CH_COLUMNS:
        row.append(col["dec"](rec, ctx) if applies(col, rec) else "")
    row.append(readable_text(rec[O_NAME:O_NAME + 16]))
    return row


def aprs_decode(rec, dp):
    def nm(b):
        return bytes(b).split(b"\x00", 1)[0].split(b"\xff", 1)[0].rstrip(b" ").decode("latin-1")
    flags = rec[61]
    return [nm(rec[0:8]), str(rec[8]), nm(rec[15:21]), str(rec[21]), nm(rec[22:28]), str(rec[28]), str(rec[29]), str(rec[30]),
            nm(rec[31:55]), str((flags >> 5) & 7), "True" if flags & 0x02 else "False", latlon_text(rec[9:12], dp),
            latlon_text(rec[12:15], dp), fmt_scaled(struct.unpack_from("<I", rec, 55)[0], 5, dp),
            "True" if flags & 0x04 else "False", str(flags & 0x01)]


def dtmf_code_text(code16):
    out = []
    for b in code16:
        if b == 0xFF:
            break
        out.append(DTMF_ALPHABET[b] if b < len(DTMF_ALPHABET) else "?")
    return "".join(out)


def export_files(cp_or_image, outdir, dp=None, log=print):
    """Записати шість CSV у outdir. cp_or_image -- codeplug_view.Codeplug або Image. Повертає список шляхів."""
    img = cp_or_image if isinstance(cp_or_image, Image) else Image.from_codeplug(cp_or_image)
    dp = dp or system_decimal_point()
    os.makedirs(outdir, exist_ok=True)
    ctx = make_ctx_for_export(img, dp)
    paths = []

    def out(key):
        p = os.path.join(outdir, FILE_NAMES[key])
        paths.append(p)
        return p

    with _open_out(out("channels")) as f:
        w = _writer(f)
        w.writerow(CHANNEL_HDR + [READABLE])
        for n, rec in img.channels():
            w.writerow(channel_row(n, rec, ctx))
    with _open_out(out("contacts")) as f:
        w = _writer(f)
        w.writerow(CONTACT_HDR + [READABLE])
        for _slot, rec in img.contacts():
            res1 = rec[22]
            ts = "Disabled" if res1 & 0x01 else str(((res1 & 0x02) >> 1) + 1)
            w.writerow([compat_text(rec[:16]), str(cv.bcd_to_int(rec[16:20])), CALL_TYPE_NAMES.get(rec[20], "Group"), ts, readable_text(rec[:16])])
    with _open_out(out("tg_lists")) as f:
        w = _writer(f)
        w.writerow(TG_HDR + [READABLE])
        names = {slot + 1: compat_text(rec[:16]) for slot, rec in img.contacts()}
        for _slot, rec, length in img.groups():
            members = []
            for k in range(length):
                v = rec[16 + 2 * k] | (rec[17 + 2 * k] << 8)
                if v == 0:
                    break
                members.append(names.get(v, "#%d" % v))
            w.writerow([compat_text(rec[:16])] + members + [""] * (32 - len(members)) + [readable_text(rec[:16])])
    with _open_out(out("zones")) as f:
        w = _writer(f)
        w.writerow(ZONE_HDR + [READABLE])
        chn = {n: compat_text(rec[:16]) for n, rec in img.channels()}
        n_per = img.zone_format()
        for _bit, rec in img.zones():
            members = []
            for k in range(n_per):
                v = rec[16 + 2 * k] | (rec[17 + 2 * k] << 8)
                if v == 0:
                    break
                members.append(chn.get(v, "#%d" % v))
            w.writerow([compat_text(rec[:16])] + members + [""] * (80 - len(members)) + [readable_text(rec[:16])])
    with _open_out(out("aprs")) as f:
        w = _writer(f)
        w.writerow(APRS_HDR + [READABLE])
        for _slot, rec in img.aprs():
            w.writerow(aprs_decode(rec, dp) + [readable_text(rec[:8])])
    with _open_out(out("dtmf")) as f:
        w = _writer(f)
        w.writerow(DTMF_HDR + [READABLE])
        for _slot, rec in img.dtmf():
            w.writerow([compat_text(rec[:16]), dtmf_code_text(rec[16:32]), readable_text(rec[:16])])
    log("Експорт: %s" % ", ".join(os.path.basename(p) for p in paths))
    return paths


# =========================================================================================
#  Читання CSV
# =========================================================================================

def _norm_header(h):
    return re.sub(r"[^a-z0-9]", "", (h or "").casefold())


class Table:
    def __init__(self, fname, header, rows):
        self.fname = fname
        self.header = header
        self.rows = rows            # [(номер рядка у файлі, [значення])]
        self.index = {}
        for i, h in enumerate(header):
            k = _norm_header(h)
            if k and k not in self.index:
                self.index[k] = i

    def col(self, *names):
        for n in names:
            k = _norm_header(n)
            if k in self.index:
                return self.index[k]
        return None

    def get(self, row, *names):
        i = self.col(*names)
        if i is None or i >= len(row):
            return None
        return row[i]

    def numbered(self, prefix):
        """Колонки Prefix1..PrefixN -> [індекси] за зростанням номера."""
        found = []
        for k, i in self.index.items():
            m = re.fullmatch(re.escape(_norm_header(prefix)) + r"(\d+)", k)
            if m:
                found.append((int(m.group(1)), i))
        return [i for _n, i in sorted(found)]


def read_table(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        data = list(csv.reader(f, delimiter=";"))
    if not data:
        raise CsvError("%s: порожній файл" % os.path.basename(path))
    rows = []
    for n, r in enumerate(data[1:], start=2):
        if r and any(c.strip() for c in r):
            rows.append((n, r))
    return Table(os.path.basename(path), data[0], rows)


def read_dir(directory):
    """Знайти й прочитати наявні з шести файлів (назви без урахування регістру). {ключ: Table}"""
    have = {n.casefold(): n for n in os.listdir(directory)}
    tables = {}
    for key, fname in FILE_NAMES.items():
        real = have.get(fname.casefold())
        if real:
            tables[key] = read_table(os.path.join(directory, real))
    return tables


# =========================================================================================
#  Імпорт: побудова нового образу
# =========================================================================================

CP1251_WARNING = ("Назви з літерами «і ї є ґ» записано в cp1251: у рації та в нашому переглядачі вони читаються нормально, а в CPS "
                  "виглядатимуть зіпсовано (це очікувано, CPS читає назви як Latin-1).")


def _match_rows(keys, olds):
    """keys: [(compat, readable)] по рядках CSV; olds: [(slot, old_compat, old_readable)].
    Повертає ([slot або None по рядках], [слоти старих записів без пари]). Спершу за сумісною назвою (k-й рядок з назвою X -> k-й
    запис з назвою X), потім -- за читабельною серед тих, що лишились (так перейменування «на місці» зберігає слот)."""
    taken = {}
    result = [None] * len(keys)
    pool = list(olds)
    for i, (c, _r) in enumerate(keys):
        for j, (slot, oc, _or) in enumerate(pool):
            if c is not None and oc == c:
                result[i] = slot
                del pool[j]
                break
    for i, (_c, r) in enumerate(keys):
        if result[i] is None and r:
            for j, (slot, _oc, orr) in enumerate(pool):
                if orr == r:
                    result[i] = slot
                    del pool[j]
                    break
    del taken
    return result, [p[0] for p in pool]


class ImportResult:
    def __init__(self):
        self.image = None
        self.added = []        # [(розділ, текст)]
        self.changed = []
        self.removed = []
        self.warnings = []

    def any_change(self):
        return bool(self.added or self.changed or self.removed)

    def report_lines(self, limit=60):
        """Текст для діалогу підтвердження: спершу видалення (великими), далі нові й змінені, далі попередження."""
        lines = []
        if self.removed:
            lines.append("УВАГА -- БУДЕ ВИДАЛЕНО (%d):" % len(self.removed))
            lines += ["  ВИДАЛЯЄТЬСЯ: [%s] %s" % x for x in self.removed[:limit]]
            if len(self.removed) > limit:
                lines.append("  ... і ще %d" % (len(self.removed) - limit))
            lines.append("")
        for title, items in (("Нові", self.added), ("Змінені", self.changed)):
            if items:
                lines.append("%s (%d):" % (title, len(items)))
                lines += ["  [%s] %s" % x for x in items[:limit]]
                if len(items) > limit:
                    lines.append("  ... і ще %d" % (len(items) - limit))
                lines.append("")
        if self.warnings:
            lines.append("Попередження (%d):" % len(self.warnings))
            lines += ["  - " + w for w in self.warnings[:limit]]
            lines.append("")
        if not lines:
            lines = ["Змін у кодплузі немає."]
        return lines[:-1] if lines and lines[-1] == "" else lines

    def summary(self):
        return "нових %d, змінених %d, видалених %d, попереджень %d" % (len(self.added), len(self.changed), len(self.removed),
                                                                       len(self.warnings))


class _Imp:
    def __init__(self, base_img, tables, dp, session):
        self.old = Image(base_img.eeprom, base_img.flash, base_img.base)
        self.img = Image(base_img.eeprom, base_img.flash, base_img.base)
        self.tables = tables
        self.dp = dp
        self.session = session
        self.problems = []
        self.reused = set()       # (вид, номер): звільнений слот віддано новому запису -- старі посилання на нього небезпечні
        self.res = ImportResult()
        # імена ДО (для порівняння полів і перевірки «нових висячих посилань»)
        self.old_names = {
            "contact": {s + 1: self._names_of(r[:16]) for s, r in self.old.contacts()},
            "group": {s + 1: self._names_of(r[:16]) for s, r, _l in self.old.groups()},
            "aprs": {s + 1: self._names_of(r[:8]) for s, r in self.old.aprs()},
            "channel": {n: self._names_of(r[:16]) for n, r in self.old.channels()},
        }
        self.old_ctx = Ctx(dp, contact_name=lambda n: self._old_disp("contact", n), group_name=lambda n: self._old_disp("group", n),
                           aprs_name=lambda n: self._old_disp("aprs", n))
        self.names = {}
        self.refresh_names()

    # --- імена ---
    @staticmethod
    def _names_of(raw):
        return (compat_text(raw), readable_text(raw))

    def _old_disp(self, kind, n):
        v = self.old_names[kind].get(n)
        return v[0] if v else "#%d" % n

    def refresh_names(self):
        im = self.img
        self.names = {
            "contact": {s + 1: self._names_of(r[:16]) for s, r in im.contacts()},
            "group": {s + 1: self._names_of(r[:16]) for s, r, _l in im.groups()},
            "aprs": {s + 1: self._names_of(r[:8]) for s, r in im.aprs()},
            "channel": {n: self._names_of(r[:16]) for n, r in im.channels()},
        }

    def alloc(self, kind, taken, pool, limit):
        """Слот для нового запису: СПЕРШУ слоти, що не були зайняті ніколи; звільнений слот -- лише коли інших нема
        (тоді старі посилання на нього небезпечні -- їх ловить перевірка висячих посилань)."""
        slot = _first_free(set(taken) | set(pool), limit)
        if slot is None and pool:
            slot = pool.pop(0)
            self.reused.add((kind, slot + 1))
        return slot

    def problem(self, fname, line, text):
        self.problems.append("%s%s: %s" % (fname, (", рядок %d" % line) if line else "", text))

    def warn(self, text):
        self.res.warnings.append(text)

    # --- вибір назви (V1.3) ---
    def pick_name(self, fname, line, c, r, old_raw, nbytes, fill=b"\xff"):
        """Повертає сирі байти назви (рівно nbytes) або None (проблему записано). Без змін -> old_raw як є."""
        c = c or None            # порожня сумісна клітинка = «не задано» (нові рядки людина заповнює лише читабельною)
        r = r or None
        if old_raw is not None:
            oc, orr = self._names_of(old_raw[:nbytes])
            c_changed = c is not None and c != oc
            r_changed = r is not None and r != orr
            if not c_changed and not r_changed:
                return bytes(old_raw[:nbytes])
            use_compat = c_changed
        else:
            use_compat = bool(c)
        text = c if use_compat else r
        if not text:
            self.problem(fname, line, "порожня назва")
            return None
        raw = None
        if use_compat:
            try:
                raw = text.encode("latin-1")
            except UnicodeEncodeError:
                use_compat = False      # у «сумісну» колонку вписали справжній Unicode -- трактуємо як читабельну назву
        if not use_compat:
            try:
                raw, enc = encode_new_name(text)
            except ValueError as e:
                self.problem(fname, line, "назва «%s»: %s" % (text, e))
                return None
            if readable_text(raw) != text:
                self.problem(fname, line, "назва «%s» не читається однаково після запису (декодується як «%s») -- змініть літери" % (text, readable_text(raw)))
                return None
            if enc == "cp1251" and any(ch in text for ch in "іїєґІЇЄҐ"):
                if self.session is None or not self.session.warned_cp1251:
                    self.warn(CP1251_WARNING)
                    if self.session is not None:
                        self.session.warned_cp1251 = True
        if len(raw) > nbytes:
            hint = ""
            try:
                alt = text.encode("cp1251")
                if len(alt) <= nbytes and not use_compat:
                    hint = " У cp1251 влізло б (%d байтів), але в CPS така назва виглядала б зіпсованою -- скороти назву." % len(alt)
            except UnicodeEncodeError:
                pass
            self.problem(fname, line, "назва «%s» займає %d байтів, дозволено %d (зайве: %d).%s" % (
                text, len(raw), nbytes, len(raw) - nbytes, hint))
            return None
        return raw.ljust(nbytes, fill)

    # --- посилання за назвами (V1.6) ---
    def lookup(self, kind, text):
        names = self.names[kind]
        hits = [n for n, (c, _r) in names.items() if c == text] or [n for n, (_c, r) in names.items() if r == text]
        if len(hits) == 1:
            return hits[0], None
        label = {"contact": "контакту", "group": "TG-списку", "aprs": "APRS-конфігу", "channel": "каналу"}[kind]
        if not hits:
            return None, "немає %s з назвою «%s»" % (label, text)
        return None, "назва %s «%s» неоднозначна (%d збігів: №%s)" % (label, text, len(hits), ", ".join(map(str, sorted(hits)[:6])))

    def kept_ref_ok(self, kind, n):
        """Посилання n (з ВІДОМОГО старого запису), чий текст не змінено: чи цільовий запис ще той самий. Висяче ДО імпорту -- лишаємо."""
        if n == 0:
            return True
        if n not in self.old_names[kind]:
            return True
        return self.names[kind].get(n) == self.old_names[kind][n]

    def members(self, fname, line, kind, texts, old_vals, limit, what):
        """Список номерів за переліком назв. old_vals -- номери зі старого запису (або [])."""
        vals = []
        texts = list(texts)
        while texts and not (texts[-1] or "").strip():
            texts.pop()
        if len(texts) > limit:
            self.problem(fname, line, "%s: %d елементів, дозволено %d" % (what, len(texts), limit))
            return None
        ok = True
        for k, t in enumerate(texts):
            t = t or ""
            if not t.strip():
                self.problem(fname, line, "%s: порожня клітинка №%d між заповненими (CPS так не допускає)" % (what, k + 1))
                ok = False
                continue
            if k < len(old_vals):
                od = self._old_disp(kind, old_vals[k]) if kind != "channel" else self._old_chan(old_vals[k])
                if t == od:
                    if self.kept_ref_ok(kind, old_vals[k]):
                        vals.append(old_vals[k])
                        continue
            n, err = self.lookup(kind, t)
            if err:
                self.problem(fname, line, "%s №%d: %s" % (what, k + 1, err))
                ok = False
            else:
                vals.append(n)
        return vals if ok else None

    def _old_chan(self, n):
        v = self.old_names["channel"].get(n)
        return v[0] if v else "#%d" % n

    # --- загальний каркас розділу «записи з назвою без номера» ---
    def keys_for(self, tab):
        ic, ir = tab.col(tab.header[0]) if tab.header else None, tab.col(READABLE)
        out = []
        for _ln, row in tab.rows:
            c = row[ic] if ic is not None and ic < len(row) else None
            r = row[ir] if ir is not None and ir < len(row) else None
            out.append((c or None, r or None))
        return out


def _first_free(taken, limit, start=0):
    for i in range(start, limit):
        if i not in taken:
            return i
    return None


def import_csv(base, tables, dp=None, session=None):
    """base -- Codeplug/Image (поточний стан рації); tables -- {ключ: Table} (відсутній файл = розділ не чіпаємо).
    Повертає ImportResult. Проблеми -> CsvImportRefused (нічого не змінено)."""
    img = base if isinstance(base, Image) else Image.from_codeplug(base)
    dp = dp or system_decimal_point()
    s = _Imp(img, tables, dp, session)
    for key in ("contacts", "aprs", "dtmf", "tg_lists", "channels", "zones"):
        tab = tables.get(key)
        if tab is None:
            continue
        getattr(sys.modules[__name__], "_sec_" + key)(s, tab)
        s.refresh_names()
    _dangling_check(s)
    if s.problems:
        raise CsvImportRefused(s.problems)
    s.res.image = s.img
    return s.res


# ------------------------------------------------------------------ контакти
def _sec_contacts(s, tab):
    f = tab.fname
    cn = tab.col("Contact Name")
    if cn is None:
        s.problem(f, 0, "немає колонки «Contact Name»")
        return
    ic_id, ic_ty, ic_ts = tab.col("ID"), tab.col("ID Type"), tab.col("TS Override")
    keys = s.keys_for(tab)
    olds = [(slot, *s._names_of(rec[:16])) for slot, rec in s.old.contacts()]
    slots, gone = _match_rows(keys, olds)
    used = set(x[0] for x in olds)                 # слоти, які були зайняті
    free_pool = sorted(gone)
    claimed = set(x for x in slots if x is not None)
    oldrec = dict(s.old.contacts())
    for (ln, row), slot, (c, r) in zip(tab.rows, slots, keys):
        old = oldrec.get(slot) if slot is not None else None
        raw = s.pick_name(f, ln, c, r, old[:16] if old else None, 16)
        if raw is None:
            continue
        rec = bytearray(old) if old else bytearray(b"\xff" * 16 + bytes(8))
        if not old:
            rec[16:20] = bytes(4)
            rec[22] = 0xFF
        rec[:16] = raw
        changes = []
        try:
            txt = row[ic_id] if ic_id is not None and ic_id < len(row) else None
            if txt is not None and (not old or norm_text(txt) != norm_text(str(cv.bcd_to_int(old[16:20])))):
                v = parse_scaled(txt, 0)
                if not 0 <= v <= 99999999:
                    raise ValueError("ID 0..99999999")
                rec[16:20] = bytes.fromhex("%08d" % v)
                changes.append("ID")
            elif txt is None and not old:
                s.problem(f, ln, "немає колонки ID")
            txt = row[ic_ty] if ic_ty is not None and ic_ty < len(row) else None
            if txt is not None and (not old or norm_text(txt) != norm_text(CALL_TYPE_NAMES.get(old[20], "Group"))):
                tl = re.sub(r"\s+", "", txt.casefold())
                tv = {"group": 0, "tg": 0, "private": 1, "pc": 1, "allcall": 2, "all": 2}.get(tl)
                if tv is None:
                    raise ValueError("ID Type: Group / Private / All Call, а не %r" % txt)
                rec[20] = tv
                changes.append("ID Type")
            txt = row[ic_ts] if ic_ts is not None and ic_ts < len(row) else None
            if old:
                old_ts = "Disabled" if old[22] & 1 else str(((old[22] & 2) >> 1) + 1)
            else:
                old_ts = None
            if txt is not None and (not old or norm_text(txt) != norm_text(old_ts)):
                tl = txt.strip().casefold()
                if tl in ("disabled", "off", "none", ""):
                    rec[22] |= 1
                elif tl in ("1", "2"):
                    rec[22] = (rec[22] & ~3 & 0xFF) | ((int(tl) - 1) << 1)
                else:
                    raise ValueError("TS Override: Disabled / 1 / 2, а не %r" % txt)
                changes.append("TS Override")
        except ValueError as e:
            s.problem(f, ln, "«%s»: %s" % (c or r, e))
            continue
        if old is None:
            slot = s.alloc("contact", used | claimed, free_pool, cl.CP_CONTACTS_MAX)
            if slot is None:
                s.problem(f, ln, "немає вільного місця для контакту (максимум %d)" % cl.CP_CONTACTS_MAX)
                continue
            claimed.add(slot)
            if slot not in oldrec:
                used.add(slot)
            s.img.set_contact(slot, bytes(rec))
            s.res.added.append(("Контакти", "%s (ID %d)" % (readable_text(rec[:16]), cv.bcd_to_int(rec[16:20]))))
        elif bytes(rec) != bytes(old):
            s.img.set_contact(slot, bytes(rec))
            s.res.changed.append(("Контакти", "%s: %s" % (readable_text(rec[:16]), ", ".join(changes) or "назва")))
    for slot in gone:
        if slot in free_pool:                       # слот не перевикористано -- стираємо
            s.img.set_contact(slot, b"\xff" * cl.CP_CONTACT_SIZE)
        s.res.removed.append(("Контакти", readable_text(oldrec[slot][:16])))


# ------------------------------------------------------------------ APRS
APRS_FIELDS = ["APRS config Name", "SSID", "Via1", "Via1 SSID", "Via2", "Via2 SSID", "Icon table", "Icon", "Comment text", "Ambiguity",
               "Use position", "Latitude", "Longitude", "TX Frequency", "Transmit QSY", "Baud rate setting"]


def _aprs_ascii(text, n, what):
    b = text.encode("latin-1") if all(ord(ch) < 256 for ch in text) else None
    if b is None or len(b) > n:
        raise ValueError("%s: до %d символів Latin-1" % (what, n))
    return b.ljust(n, b"\x00")


def _aprs_encode_field(rec, idx, text):
    """Записати поле idx (за APRS_FIELDS) у rec (bytearray 64). ValueError -- погане значення."""
    t = text or ""
    if idx == 1:
        v = parse_scaled(t, 0)
        if not 0 <= v <= 15:
            raise ValueError("SSID 0..15")
        rec[8] = v
    elif idx in (3, 5):
        v = parse_scaled(t, 0)
        if not 0 <= v <= 15:
            raise ValueError("SSID 0..15")
        rec[21 if idx == 3 else 28] = v
    elif idx in (2, 4):
        a = 15 if idx == 2 else 22
        rec[a:a + 6] = _aprs_ascii(t.strip(), 6, "Via")
    elif idx == 6:
        rec[29] = parse_scaled(t, 0)
    elif idx == 7:
        v = parse_scaled(t, 0)
        if not 0 <= v <= 255:
            raise ValueError("Icon 0..255")
        rec[30] = v
    elif idx == 8:
        rec[31:55] = _aprs_ascii(t, 24, "Comment")
    elif idx == 9:
        v = parse_scaled(t, 0)
        if not 0 <= v <= 7:
            raise ValueError("Ambiguity 0..7")
        rec[61] = (rec[61] & 0x1F) | (v << 5)
    elif idx in (10, 14):
        mask = 0x02 if idx == 10 else 0x04
        rec[61] = (rec[61] | mask) if parse_bool(t) else (rec[61] & ~mask & 0xFF)
    elif idx in (11, 12):
        a = 9 if idx == 11 else 12
        rec[a:a + 3] = parse_latlon(t, 90 if idx == 11 else 180)
    elif idx == 13:
        v = parse_scaled(t, 5)
        if not 0 <= v <= 0xFFFFFFFF:
            raise ValueError("TX Frequency поза межами")
        struct.pack_into("<I", rec, 55, v)
    elif idx == 15:
        v = parse_scaled(t, 0)
        if v not in (0, 1):
            raise ValueError("Baud rate setting: 0 (1200) або 1 (300)")
        rec[61] = (rec[61] & ~1 & 0xFF) | v


def _sec_aprs(s, tab):
    f = tab.fname
    if tab.col(APRS_FIELDS[0]) is None:
        s.problem(f, 0, "немає колонки «APRS config Name»")
        return
    col = [tab.col(n) for n in APRS_FIELDS]
    ic = col[0]
    ir = tab.col(READABLE)
    keys = []
    for _ln, row in tab.rows:
        keys.append(((row[ic] if ic < len(row) else None) or None, (row[ir] if ir is not None and ir < len(row) else None) or None))
    olds = [(slot, *s._names_of(rec[:8])) for slot, rec in s.old.aprs()]
    oldrec = dict(s.old.aprs())
    slots, gone = _match_rows(keys, olds)
    claimed = set(x for x in slots if x is not None)
    free_pool = sorted(gone)
    n_rows = 0
    for (ln, row), slot, (c, r) in zip(tab.rows, slots, keys):
        n_rows += 1
        old = oldrec.get(slot) if slot is not None else None
        raw = s.pick_name(f, ln, c, r, old[:8] if old else None, 8, fill=b"\x00")
        if raw is None:
            continue
        rec = bytearray(old) if old else bytearray(b"\x00" * 64)
        if not old:
            struct.pack_into("<H", rec, 62, APRS_MAGIC)
            rec[55:59] = bytes(4)
        rec[:8] = raw
        old_vals = aprs_decode(old, s.dp) if old else None
        changes = []
        try:
            for i in range(1, len(APRS_FIELDS)):
                if col[i] is None or col[i] >= len(row):
                    continue
                txt = row[col[i]]
                if old_vals is not None and norm_text(txt) == norm_text(old_vals[i]):
                    continue
                _aprs_encode_field(rec, i, txt)
                changes.append(APRS_FIELDS[i])
        except ValueError as e:
            s.problem(f, ln, "«%s»: %s" % (c or r, e))
            continue
        if old is None:
            slot = s.alloc("aprs", set(oldrec) | claimed, free_pool, APRS_MAX)
            if slot is None:
                s.problem(f, ln, "немає вільного місця для APRS-конфігу (максимум %d)" % APRS_MAX)
                continue
            claimed.add(slot)
            s.img.set_aprs(slot, bytes(rec))
            s.res.added.append(("APRS", readable_text(rec[:8])))
        elif bytes(rec) != bytes(old):
            s.img.set_aprs(slot, bytes(rec))
            s.res.changed.append(("APRS", "%s: %s" % (readable_text(rec[:8]), ", ".join(changes) or "назва")))
    for slot in gone:
        if slot in free_pool:
            s.img.set_aprs(slot, b"\xff" * APRS_SIZE)
        s.res.removed.append(("APRS", readable_text(oldrec[slot][:8])))


# ------------------------------------------------------------------ DTMF
def _dtmf_parse(text):
    out = bytearray()
    for ch in (text or "").strip().upper():
        if ch.isspace():
            continue
        i = DTMF_ALPHABET.find(ch)
        if i < 0:
            raise ValueError("недопустимий символ DTMF %r (дозволено %s)" % (ch, DTMF_ALPHABET))
        out.append(i)
    if len(out) > 16:
        raise ValueError("код довший за 16 знаків")
    return bytes(out).ljust(16, b"\xff")


def _sec_dtmf(s, tab):
    f = tab.fname
    if tab.col("Contact Name") is None:
        s.problem(f, 0, "немає колонки «Contact Name»")
        return
    ic_code = tab.col("Code")
    keys = s.keys_for(tab)
    olds = [(slot, *s._names_of(rec[:16])) for slot, rec in s.old.dtmf()]
    oldrec = dict(s.old.dtmf())
    slots, gone = _match_rows(keys, olds)
    claimed = set(x for x in slots if x is not None)
    free_pool = sorted(gone)
    for (ln, row), slot, (c, r) in zip(tab.rows, slots, keys):
        old = oldrec.get(slot) if slot is not None else None
        raw = s.pick_name(f, ln, c, r, old[:16] if old else None, 16)
        if raw is None:
            continue
        rec = bytearray(old) if old else bytearray(b"\xff" * 32)
        rec[:16] = raw
        try:
            txt = row[ic_code] if ic_code is not None and ic_code < len(row) else None
            if txt is not None and (not old or norm_text(txt) != norm_text(dtmf_code_text(old[16:32]))):
                rec[16:32] = _dtmf_parse(txt)
        except ValueError as e:
            s.problem(f, ln, "«%s»: %s" % (c or r, e))
            continue
        if old is None:
            if free_pool:
                slot = free_pool.pop(0)
            else:
                ok = [i for i in range(DTMF_MAX) if i not in claimed and i not in oldrec and s.img.ee(ADDR_DTMF + i * DTMF_SIZE, 1)[0] == 0xFF]
                if not ok:
                    s.problem(f, ln, "немає вільного місця для DTMF-контакту (максимум %d)" % DTMF_MAX)
                    continue
                slot = ok[0]
            claimed.add(slot)
            s.img.set_dtmf(slot, bytes(rec))
            s.res.added.append(("DTMF", readable_text(rec[:16])))
        elif bytes(rec) != bytes(old):
            s.img.set_dtmf(slot, bytes(rec))
            s.res.changed.append(("DTMF", readable_text(rec[:16])))
    for slot in gone:
        if slot in free_pool:
            s.img.set_dtmf(slot, b"\xff" * DTMF_SIZE)
        s.res.removed.append(("DTMF", readable_text(oldrec[slot][:16])))


# ------------------------------------------------------------------ TG-списки
def _sec_tg_lists(s, tab):
    f = tab.fname
    if tab.col("TG List Name") is None:
        s.problem(f, 0, "немає колонки «TG List Name»")
        return
    mcols = tab.numbered("Contact")
    keys = s.keys_for(tab)
    oldg = {slot: (rec, length) for slot, rec, length in s.old.groups()}
    olds = [(slot, *s._names_of(rec[:16])) for slot, (rec, _l) in oldg.items()]
    slots, gone = _match_rows(keys, olds)
    claimed = set(x for x in slots if x is not None)
    free_pool = sorted(gone)
    for (ln, row), slot, (c, r) in zip(tab.rows, slots, keys):
        old = oldg.get(slot) if slot is not None else None
        raw = s.pick_name(f, ln, c, r, old[0][:16] if old else None, 16)
        if raw is None:
            continue
        old_vals = []
        if old:
            for k in range(old[1]):
                v = old[0][16 + 2 * k] | (old[0][17 + 2 * k] << 8)
                if v == 0:
                    break
                old_vals.append(v)
        texts = [row[i] if i < len(row) else "" for i in mcols]
        vals = s.members(f, ln, "contact", texts, old_vals, 32, "TG-список «%s»" % (c or r))
        if vals is None:
            continue
        if not vals:
            s.warn("TG-список «%s» порожній -- рація такі не показує, його не буде в кодплузі." % readable_text(raw))
            if old:
                gone = list(gone) + [slot]
            continue
        rec = bytearray(old[0]) if old else bytearray(b"\xff" * 16 + bytes(64))
        rec[:16] = raw
        if vals != old_vals or not old:
            rec[16:80] = b"".join(struct.pack("<H", v) for v in vals).ljust(64, b"\x00")
        length = len(vals)
        if old is None:
            slot = s.alloc("group", set(oldg) | claimed, free_pool, cl.CP_RXGROUPS_MAX)
            if slot is None:
                s.problem(f, ln, "немає вільного місця для TG-списку (максимум %d)" % cl.CP_RXGROUPS_MAX)
                continue
            claimed.add(slot)
            s.img.set_group(slot, bytes(rec), length)
            s.res.added.append(("TG-списки", "%s (%d контактів)" % (readable_text(rec[:16]), length)))
        elif bytes(rec) != bytes(old[0]) or length != old[1]:
            s.img.set_group(slot, bytes(rec), length)
            s.res.changed.append(("TG-списки", "%s: склад/назва" % readable_text(rec[:16])))
    for slot in gone:
        s.img.clear_group_len(slot)
        if slot in oldg:
            s.res.removed.append(("TG-списки", readable_text(oldg[slot][0][:16])))


# ------------------------------------------------------------------ канали
def _sec_channels(s, tab):
    f = tab.fname
    name_i = tab.col("Channel Name")
    num_i = tab.col("Channel Number")
    if name_i is None:
        s.problem(f, 0, "немає колонки «Channel Name»")
        return
    ir = tab.col(READABLE)
    cols = {c["name"]: tab.col(c["name"]) for c in CH_COLUMNS}
    oldch = dict(s.old.channels())
    nmax = cl.CP_CHANNELS_BANKS * cl.CP_CHANNELS_PER_BANK

    # 1) номери
    assigned = []        # (ln, row, number|None)
    seen = {}
    for ln, row in tab.rows:
        num = None
        t = (row[num_i] if num_i is not None and num_i < len(row) else "").strip()
        if t:
            try:
                num = parse_scaled(t, 0)
            except ValueError:
                s.problem(f, ln, "Channel Number не число: %r" % t)
                continue
            if not 1 <= num <= nmax:
                s.problem(f, ln, "Channel Number %d поза межами 1..%d" % (num, nmax))
                continue
            if num in seen:
                s.problem(f, ln, "Channel Number %d вже є в рядку %d" % (num, seen[num]))
                continue
            seen[num] = ln
        assigned.append((ln, row, num))
    claimed = set(seen)
    pending = [a for a in assigned if a[2] is None]
    never = [n for n in range(1, nmax + 1) if n not in oldch and n not in claimed]
    reuse = [n for n in sorted(oldch) if n not in claimed]
    rowsnum = [a for a in assigned if a[2] is not None]

    ctx = Ctx(s.dp, contact_name=s.old_ctx.contact_name, group_name=s.old_ctx.group_name, aprs_name=s.old_ctx.aprs_name,
              resolve=lambda kind, text: s.lookup(kind, text))
    final = {}
    for ln, row, num in rowsnum + pending:
        if num is None:
            pool = never or reuse
            if not pool:
                s.problem(f, ln, "немає вільного номера каналу (максимум %d)" % nmax)
                continue
            num = pool.pop(0)
            if num in reuse:
                reuse.remove(num)
                s.reused.add(("channel", num))
        c = (row[name_i] if name_i < len(row) else None) or None
        r = row[ir] if ir is not None and ir < len(row) else None
        old = oldch.get(num)
        raw = s.pick_name(f, ln, c, r, old[:16] if old else None, 16)
        if raw is None:
            continue
        if old is not None:
            rec = bytearray(old)
        else:
            tt = row[cols["Channel Type"]] if cols["Channel Type"] is not None and cols["Channel Type"] < len(row) else ""
            rec = new_channel_template(tt.strip().casefold().startswith("dig"))
        rec[:16] = raw
        changed_cols = []
        # тип -- першим: від нього залежить застосовність решти колонок
        order = [CH_COLUMN_BY_NAME["Channel Type"]] + [c2 for c2 in CH_COLUMNS if c2["name"] != "Channel Type"]
        for col in order:
            ci = cols[col["name"]]
            if ci is None or ci >= len(row):
                if old is None and col["name"] in ("Rx Frequency", "Tx Frequency"):
                    s.problem(f, ln, "новий канал «%s»: немає колонки «%s»" % (readable_text(raw), col["name"]))
                continue
            if not applies(col, rec):
                continue
            txt = row[ci]
            if old is not None and norm_text(txt) == norm_text(col["dec"](old, ctx)) and applies(col, old):
                if col["name"] in ("Contact", "TG List", "APRS"):
                    kind = {"Contact": "contact", "TG List": "group", "APRS": "aprs"}[col["name"]]
                    n_old = (old[O_CONTACT] | (old[O_CONTACT + 1] << 8)) if kind == "contact" else old[O_GROUP if kind == "group" else O_APRS]
                    if s.kept_ref_ok(kind, n_old):
                        continue            # текст не змінено і ціль та сама -- поле не чіпаємо
                    # ціль зникла/змінилась: розв'язуємо за назвою заново (не знайдемо -- буде проблема)
                else:
                    continue
            if not (txt or "").strip() and col["soft"]:
                continue
            before = bytes(rec)
            try:
                col["enc"](rec, txt, ctx)
            except LookupError as e:
                s.problem(f, ln, "канал «%s», колонка «%s»: %s" % (readable_text(raw), col["name"], e))
                continue
            except ValueError as e:
                if col["soft"]:
                    s.warn("%s, рядок %d, колонка «%s»: %s -- поле лишено як було." % (f, ln, col["name"], e))
                    rec[:] = before
                else:
                    s.problem(f, ln, "канал «%s», колонка «%s»: %s" % (readable_text(raw), col["name"], e))
                continue
            if bytes(rec) != before:
                changed_cols.append(col["name"])
        if old is not None and bytes(rec) == bytes(old):
            final[num] = old
            continue
        final[num] = bytes(rec)
        if old is None:
            s.res.added.append(("Канали", "№%d %s" % (num, readable_text(rec[:16]))))
        else:
            s.res.changed.append(("Канали", "№%d %s: %s" % (num, readable_text(rec[:16]), ", ".join(changed_cols) or "назва")))
    # 2) записуємо
    for num, rec in final.items():
        if num not in oldch or bytes(rec) != oldch[num]:
            s.img.set_channel_rec(num, rec)
        if not s.img.channel_in_use(num):
            s.img.set_channel_in_use(num, True)
    for num in sorted(oldch):
        if num not in final:
            s.img.set_channel_in_use(num, False)     # рядка нема в CSV -- канал видаляється (лише біт «у роботі»)
            s.res.removed.append(("Канали", "№%d %s" % (num, readable_text(oldch[num][:16]))))


# ------------------------------------------------------------------ зони
def _sec_zones(s, tab):
    f = tab.fname
    if tab.col("Zone Name") is None:
        s.problem(f, 0, "немає колонки «Zone Name»")
        return
    mcols = tab.numbered("Channel")
    nper = s.img.zone_format()
    stride = s.img.zone_stride()
    keys = s.keys_for(tab)
    oldz = {bit: rec for bit, rec in s.old.zones()}
    olds = [(bit, *s._names_of(rec[:16])) for bit, rec in oldz.items()]
    slots, gone = _match_rows(keys, olds)
    claimed = set(x for x in slots if x is not None)
    free_pool = sorted(gone)
    gone = list(gone)
    for (ln, row), bit, (c, r) in zip(tab.rows, slots, keys):
        old = oldz.get(bit) if bit is not None else None
        raw = s.pick_name(f, ln, c, r, old[:16] if old else None, 16)
        if raw is None:
            continue
        old_vals = []
        if old:
            for k in range(nper):
                v = old[16 + 2 * k] | (old[17 + 2 * k] << 8)
                if v == 0:
                    break
                old_vals.append(v)
        texts = [row[i] if i < len(row) else "" for i in mcols]
        vals = s.members(f, ln, "channel", texts, old_vals, nper, "зона «%s»" % (c or r))
        if vals is None:
            continue
        if not vals:
            s.warn("Зона «%s» порожня -- рація таких не використовує, її не буде в кодплузі." % readable_text(raw))
            if old is not None and bit not in gone:
                gone.append(bit)
            continue
        rec = bytearray(old) if old else bytearray(b"\xff" * 16 + bytes(stride - 16))
        rec[:16] = raw
        if vals != old_vals or not old:
            rec[16:stride] = b"".join(struct.pack("<H", v) for v in vals).ljust(stride - 16, b"\x00")
        if old is None:
            if free_pool:
                bit = free_pool.pop(0)
            else:
                bit = _first_free(set(oldz) | claimed, cl.CP_ZONES_MAX)
                if bit is None:
                    s.problem(f, ln, "немає вільного місця для зони (максимум %d)" % cl.CP_ZONES_MAX)
                    continue
            claimed.add(bit)
            s.img.set_zone(bit, bytes(rec))
            s.res.added.append(("Зони", "%s (%d каналів)" % (readable_text(rec[:16]), len(vals))))
        elif bytes(rec) != bytes(old):
            s.img.set_zone(bit, bytes(rec))
            s.res.changed.append(("Зони", "%s: склад/назва" % readable_text(rec[:16])))
    for bit in gone:
        s.img.clear_zone(bit)
        if bit in oldz:
            s.res.removed.append(("Зони", readable_text(oldz[bit][:16])))


# ------------------------------------------------------------------ глобальна перевірка висячих посилань
def _dangling_check(s):
    """Після всіх розділів: НОВІ висячі посилання у розділах, чиїх CSV НЕ завантажено (наприклад, імпорт лише Contacts.csv
    видалив контакт, на який посилається канал). Розділи, чиї CSV завантажено, розв'язують посилання за назвами самі.
    Вада = ціль існувала до імпорту й тепер зникла, АБО її слот віддано іншому новому запису."""
    s.refresh_names()
    im, old, tabs = s.img, s.old, s.tables

    def bad(kind, v):
        if v == 0:
            return False
        if (kind, v) in s.reused:
            return True
        return v in s.old_names[kind] and v not in s.names[kind]

    def whynot(kind, v):
        return "видалено" if v not in s.names[kind] else "слот віддано іншому записові"

    if "channels" not in tabs:
        for n, rec in im.channels():
            oldrec = old.channel_rec(n) if old.channel_in_use(n) else None
            for kind, off, two in (("contact", O_CONTACT, True), ("group", O_GROUP, False), ("aprs", O_APRS, False)):
                v = (rec[off] | (rec[off + 1] << 8)) if two else rec[off]
                ov = ((oldrec[off] | (oldrec[off + 1] << 8)) if two else oldrec[off]) if oldrec is not None else None
                if v and v == ov and bad(kind, v):
                    lab = {"contact": "контакт", "group": "TG-список", "aprs": "APRS-конфіг"}[kind]
                    s.problem("(перевірка посилань)", 0, "канал №%d «%s» посилається на %s №%d, який %s" % (
                        n, readable_text(rec[:16]), lab, v, whynot(kind, v)))
    if "tg_lists" not in tabs:
        oldg = {slot: (rec, ln_) for slot, rec, ln_ in old.groups()}
        for slot, rec, length in im.groups():
            for k in range(length):
                v = rec[16 + 2 * k] | (rec[17 + 2 * k] << 8)
                if v == 0:
                    break
                same = slot in oldg and oldg[slot][0][16 + 2 * k:18 + 2 * k] == rec[16 + 2 * k:18 + 2 * k]
                if same and bad("contact", v):
                    s.problem("(перевірка посилань)", 0, "TG-список «%s» містить контакт №%d, який %s" % (
                        readable_text(rec[:16]), v, whynot("contact", v)))
    if "zones" not in tabs:
        nper = im.zone_format()
        oldz = dict(old.zones())
        for bit, rec in im.zones():
            for k in range(nper):
                v = rec[16 + 2 * k] | (rec[17 + 2 * k] << 8)
                if v == 0:
                    break
                same = bit in oldz and oldz[bit][16 + 2 * k:18 + 2 * k] == rec[16 + 2 * k:18 + 2 * k]
                if same and bad("channel", v):
                    s.problem("(перевірка посилань)", 0, "зона «%s» містить канал №%d, який %s" % (
                        readable_text(rec[:16]), v, whynot("channel", v)))


# =========================================================================================
#  Рація: експорт і імпорт (імпорт -- ТІЄЮ САМОЮ дорогою, що й відновлення з бекапу)
# =========================================================================================

IMPORT_TITLE = "ІМПОРТ CSV -- рація буде ПЕРЕЗАПИСАНА змінами з CSV."


def export_from_backup(zip_path, outdir, dp=None, log=print):
    cp, _m = cv.codeplug_from_backup(zip_path)
    return export_files(cp, outdir, dp, log)


def export_from_radio(link, outdir, dp=None, progress=None, log=print):
    cp, _m = cv.codeplug_from_radio(link, progress)
    return export_files(cp, outdir, dp, log)


def dry_run(base_zip_or_cp, directory, dp=None, session=None):
    """Те саме, що імпорт, але без рації: що змінилось би в образі. base -- шлях до бекапу або Codeplug."""
    cp = base_zip_or_cp
    if isinstance(cp, (str, bytes, os.PathLike)):
        cp, _m = cv.codeplug_from_backup(cp)
    tables = read_dir(directory)
    if not tables:
        raise CsvError("у теці %s немає жодного з файлів: %s" % (directory, ", ".join(FILE_NAMES.values())))
    return import_csv(cp, tables, dp, session)


def import_to_radio(link, directory, confirm, progress=None, log=print, session=None, dp=None, out_dir=None, now=None,
                    clock=time.time, post_reset=True):
    """Прочитати CSV з `directory`, прочитати ПОТОЧНИЙ кодплуг рації, побудувати новий образ і записати його через
    cps_restore.restore_codeplug (страхова копія -> діалог -> лише відмінні сектори -> перечитування -> SHA-256 -> C 6 1).
    Помилка CSV -> CsvImportRefused ДО будь-якого запису (і до страхової копії). out_dir -- де лежатиме файл «що записали»
    (codeplug_csv-import_*.zip) і страхова копія; типово -- тека з CSV."""

    def prog(pct, text):
        if progress:
            progress(max(0, min(100, int(pct))), text)

    tables = read_dir(directory)
    if not tables:
        raise CsvError("у теці %s немає жодного з файлів: %s" % (directory, ", ".join(FILE_NAMES.values())))
    prog(0, "Читаю поточний кодплуг рації...")
    cp, _m = cv.codeplug_from_radio(link, lambda p, t: prog(p * 0.25, t))
    prog(26, "Розбираю CSV...")
    res = import_csv(cp, tables, dp, session)
    if not res.any_change():
        prog(100, "Змін у кодплузі немає")
        log("CSV не відрізняється від кодплуга рації -- записувати нічого.")
        return {"cancelled": False, "nothingToDo": True, "sectorsWritten": 0, "report": res}
    out = write_image_via_restore(link, res, confirm, progress=lambda p, t: prog(27 + p * 0.73, t), log=log, now=now, clock=clock,
                                  post_reset=post_reset, title=IMPORT_TITLE, out_dir=out_dir or directory, zip_prefix="codeplug_csv-import",
                                  note="Образ, зібраний з CSV імпортом поверх поточного стану рації. Це те, що буде записано.")
    return out


def write_image_via_restore(link, res, confirm, progress=None, log=print, now=None, clock=time.time, post_reset=True, title=None,
                            out_dir=".", zip_prefix="codeplug_csv-import", note=""):
    """Спільний хвіст імпорту CSV (R26 V1) і редактора контактів (V2): `res` -- ImportResult з новим образом (res.image) поверх
    ПОТОЧНОГО стану рації. Образ пакується в .zip-бекап (файл «що саме записуємо» лишається в out_dir) і йде через
    cps_restore.restore_codeplug: страхова копія -> діалог зі списком змін -> лише відмінні сектори -> перечитування -> SHA-256 -> C 6 1.
    Заблоковано тією ж константою RESTORE_UNLOCKED. Повертає підсумок restore_codeplug + ключі report, importZip."""
    import cps_restore as cr
    info = link.radio_info()
    rng = cl.flash_backup_range()
    t0 = clock()
    manifest = cl.build_manifest(info, bytes(res.image.eeprom), bytes(res.image.flash), rng, t0, t0, 0)
    manifest["tool"] = "cps_csv.py (R26)"
    manifest["note"] = note or "Образ для запису, зібраний поверх поточного стану рації."
    os.makedirs(out_dir, exist_ok=True)
    zip_path = cl.unique_path(out_dir, cl.timestamp_name(zip_prefix, ".zip", now))
    with open(zip_path, "xb") as f:
        f.write(cl.make_zip(bytes(res.image.eeprom), bytes(res.image.flash), manifest))
    log("Образ для запису збережено: %s (%s)" % (zip_path, res.summary()))
    out = cr.restore_codeplug(link, zip_path, confirm, progress, log=log, clock=clock, now=now, post_reset=post_reset, title=title,
                              extra_lines=res.report_lines())
    out["report"] = res
    out["importZip"] = zip_path
    return out


# =========================================================================================
#  CLI
# =========================================================================================

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="R26: CSV-обмін кодплуга (формат OpenGD77 CPS).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export", help="експорт шести CSV (ЛИШЕ читає)")
    e.add_argument("--backup", help="бекап .zip (інакше -- читання з рації)")
    e.add_argument("--port")
    e.add_argument("--out", required=True)
    e.add_argument("--decimal", choices=("comma", "dot"), help="десятковий знак (типово -- за системною локаллю)")
    c = sub.add_parser("check", help="сухий прогін імпорту на бекапі: що зміниться (рація не потрібна)")
    c.add_argument("--backup", required=True)
    c.add_argument("--dir", required=True)
    c.add_argument("--decimal", choices=("comma", "dot"))
    i = sub.add_parser("import", help="імпорт у рацію (ЗАПИСУЄ; через шлях відновлення з бекапу)")
    i.add_argument("--dir", required=True)
    i.add_argument("--port")
    i.add_argument("--decimal", choices=("comma", "dot"))
    a = ap.parse_args(argv)
    dp = {"comma": ",", "dot": ".", None: None}[getattr(a, "decimal", None)]
    if a.cmd == "check":
        res = dry_run(a.backup, a.dir, dp)
        print("\n".join(res.report_lines()))
        print(res.summary())
        return 0
    if a.cmd == "export" and a.backup:
        export_from_backup(a.backup, a.out, dp)
        return 0
    ser = cl.open_radio(a.port, timeout=1.0)
    try:
        link = cl.CpsLink(ser)
        if a.cmd == "export":
            export_from_radio(link, a.out, dp, progress=lambda p, t: print("%3d%%  %s" % (p, t)))
            return 0

        def confirm(text, _plan):
            print(text)
            return input("Щоб продовжити, введи слово ЗАПИСАТИ: ").strip() == "ЗАПИСАТИ"
        out = import_to_radio(link, a.dir, confirm, progress=lambda p, t: print("%3d%%  %s" % (p, t)), session=Session(), dp=dp)
        print("Підсумок:", {k: v for k, v in out.items() if k != "report"})
        return 0
    finally:
        ser.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except cl.CpsError as ex:
        raise SystemExit("\nПОМИЛКА: %s" % ex)
