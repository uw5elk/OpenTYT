# -*- coding: utf-8 -*-
"""База позивних DMR ID: формат, збірка з CSV/JSON, фільтри, запис у рацію (R31, частина 2).

ФОРМАТ -- ПРОЧИТАНО З ПРОШИВКИ (application/source/user_interface/uiUtilities.c: dmrIDCacheInit, dmrIDReadContactInFlash, dmrDbTextDecode, dmrIDLookup).
Усі числа нижче -- з коду, не з пам'яті; докладна таблиця -- у claude/codeplug-map.md.

  область №1   сира адреса 0x50000 = DMRID_MEMORY_LOCATION_1 (0x30000 + FLASH_ADDRESS_OFFSET 0x20000); у розрахунку прошивки -- 0x40000 Б разом із заголовком
  заголовок    12 Б (DMRID_HEADER_LENGTH): [0..1] 'I','d'; [2] 'N' | 'n' | будь-що інше; [3] довжина запису + 0x4A; [4..7] прошивка не читає; [8..11] LE32 кількість записів
  [2]          'N' -- ID 3 байти (DMRID_IdLength = 3), текст стиснутий 6-бітно; 'n' -- те саме, АЛЕ область №2 лежить на голосових підказках (0xAF400);
               інше -- ID 4 байти (BCD), текст ASCII як є (не обов'язково із закінчувальним нулем)
  запис        рівно (header[3] - 0x4A) байт: ID (3 або 4 байти, little-endian) + текст; прошивка відхиляє довжину > sizeof(dmrIdDataStruct_t) = 4 + 51
  ID           'N': двійкове число; інше: BCD (int2bcd: десяткові цифри як шістнадцяткові; 2550001 -> 0x02550001). Записи відсортовані за зростанням -- пошук двійковий
  текст 'N'    6 біт на символ, 4 символи в 3 байтах; таблиця DECOMPRESS_LUT: ' ', '0'-'9', 'A'-'Z', 'a'-'z', '.' (64 символи); хвостові пробіли обрізаються
  місткість    область №1: contactLength * floor((0x40000 - 12) / contactLength) байт, далі -- область №2 з 0xD8000 (DMRID_MEMORY_LOCATION_2), де ЛЕЖИТЬ таблиця ключів AES (0xD9F9C)
  кінець бази  прошивка не шукає кінця: лише header[8..11] записів; індексу нема, окрім 14 «зрізів», які вона будує при старті зі значень ID в самій базі

Цей модуль ПИШЕ лише в область №1 (вікно "dmrdb" у flash_guard) і лише бази, що в неї ВМІЩУЮТЬСЯ; область №2 (з ключами AES) і голосові підказки не чіпає.
Пише базу формату 'N' (3-байтний ID, стиснутий текст); читає (для перегляду, збереження у файл і страхової копії) ще й 4-байтний формат."""
import csv
import datetime
import hashlib
import io
import json
import os
import random
import re
import struct
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile

import cps_link as cl
import flash_guard as fg

AREA1_START = 0x30000 + cl.FLASH_ADDRESS_OFFSET        # 0x50000
AREA1_LEN = 0x40000
AREA2_START = 0xB8000 + cl.FLASH_ADDRESS_OFFSET        # 0xD8000
HEADER_LEN = 12
LEN_BIAS = 0x4A
MAX_REC_LEN = 4 + 51                                   # sizeof(dmrIdDataStruct_t)
MIN_ENTRIES_BEFORE_USING_SLICES = 40
SECTOR = 4096
LUT = " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz."
DEFAULT_TEXT_CHARS = 16                                # 12 Б стиснутого тексту + 3 Б ID = запис 15 Б
TEXT_CHARS_CHOICES = (16, 20, 24)
PART_KEY = "dmrIdDb"
PART_FILE = "dmriddb.bin"
CONTACTLISTS_URL = "https://raw.githubusercontent.com/ContactLists/NORMAL-ContactLists/master/RADIODDITY/GD77/GD77_WW_default.csv"   # R33: формат перевірено завантаженням 2026-10-25 (за брифом): Radio ID,Callsign,Name,Nickname,City,State,Country,Remarks
RADIOID_JSON_URL = "https://database.radioid.net/static/users.json"   # адреса з конфіга стороннього застосунку (Russell-KV4S/DMR.UserDB.RadioConverter); НЕ перевірено -- є кнопка «Перевірити джерело»
RADIOID_CSV_URL = "https://radioid.net/static/user.csv"               # R50: перевірено Богданом 2026-10-31: HTTP 200, 17 197 867 Б, колонки RADIO_ID,CALLSIGN,FIRST_NAME,LAST_NAME,CITY,STATE,COUNTRY
DEFAULT_COUNTRIES = ("Ukraine",)                                      # R50: типовий фільтр «Україна» -- значення колонки COUNTRY (редагується в панелі)
DEFAULT_PREFIXES = ("255",)                                           # ...і/або початок DMR ID (MCC 255); обидва фільтри діють як «АБО»
COLUMN_NAMES = ("callsign", "first", "last", "city", "state", "country")
COLUMN_TITLES = {"callsign": "позивний", "first": "ім'я", "last": "прізвище", "city": "місто", "state": "область", "country": "країна"}
DEFAULT_COLUMNS = ("callsign", "first")


class DbError(cl.CpsError):
    pass


class Cancelled(Exception):
    pass


# ---------------------------------------------------------------------------------------------
#  Стиснення тексту (дзеркало dmrDbTextDecode)
# ---------------------------------------------------------------------------------------------

CYR = {"а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e", "є": "ye", "ж": "zh", "з": "z", "и": "y", "і": "i", "ї": "yi", "й": "y",
       "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch",
       "ш": "sh", "щ": "shch", "ь": "", "ю": "yu", "я": "ya", "ы": "y", "э": "e", "ъ": "", "ё": "yo", "'": "", "’": "", "ʼ": "", "-": " ", "_": " "}


def sanitize(text):
    """Привести рядок до 64 символів таблиці прошивки: кирилиця -> латиниця, діакритика знімається, решта -> пробіл, пробіли зводяться до одного."""
    out = []
    for ch in str(text or ""):
        if ch in LUT:
            out.append(ch)
            continue
        low = ch.lower()
        if low in CYR:
            t = CYR[low]
            out.append(t.capitalize() if ch != low and t else t)
            continue
        base = unicodedata.normalize("NFKD", ch)
        base = "".join(c for c in base if not unicodedata.combining(c))
        out.append("".join(c if c in LUT else " " for c in base) or " ")
    return " ".join("".join(out).split())


def compress_text(text, nbytes):
    """Текст -> рівно nbytes байт (nbytes кратне 3): 4 символи в 3 байтах, хвіст добито пробілами (індекс 0). Символи поза таблицею -> пробіл."""
    if nbytes % 3:
        raise DbError("стиснений текст має бути кратним 3 байтам, а не %d" % nbytes)
    nchars = nbytes // 3 * 4
    t = sanitize(text)[:nchars].ljust(nchars)
    idx = [LUT.index(c) for c in t]
    out = bytearray()
    for i in range(0, nchars, 4):
        a, b, c, d = idx[i:i + 4]
        out += bytes([(a << 2) | (b >> 4), ((b & 0x0F) << 4) | (c >> 2), ((c & 0x03) << 6) | d])
    return bytes(out)


def decompress_text(data):
    """Точна копія dmrDbTextDecode: ті самі розгалуження за довжиною й обрізання хвостових пробілів."""
    out = []
    d = 0
    n = len(data)
    while True:
        cb1 = data[d]
        d += 1
        out.append(LUT[cb1 >> 2])
        if d == n:
            break
        cb2 = data[d]
        d += 1
        out.append(LUT[((cb1 & 0x03) << 4) + (cb2 >> 4)])
        if d == n:
            break
        cb3 = data[d]
        d += 1
        out.append(LUT[((cb2 & 0x0F) << 2) + (cb3 >> 6)])
        out.append(LUT[cb3 & 0x3F])
        if d >= n:
            break
    return "".join(out).rstrip(" ")


def int2bcd(v):
    return int(str(v), 16)


def bcd2int(v):
    s = "%x" % v
    return int(s) if s.isdigit() else None


# ---------------------------------------------------------------------------------------------
#  Образ бази: збірка й розбір
# ---------------------------------------------------------------------------------------------

def capacity(rec_len):
    """Скільки записів уміщується в область №1 (firmware: dmrIdDataArea_1_Size / contactLength)."""
    return (AREA1_LEN - HEADER_LEN) // rec_len


def rec_len_for(text_chars):
    if text_chars not in TEXT_CHARS_CHOICES:
        raise DbError("довжина тексту має бути одна з %s" % (", ".join(str(c) for c in TEXT_CHARS_CHOICES)))
    return 3 + text_chars // 4 * 3


def make_header(rec_len, count, mode=b"N"):
    return b"Id" + mode + bytes([rec_len + LEN_BIAS]) + b"\x00\x00\x00\x00" + struct.pack("<I", count)


def build_image(records, text_chars=DEFAULT_TEXT_CHARS):
    """records -- [(id, text)] -> байти образу (заголовок + записи 'N'), відсортовані за ID. Кидає DbError, якщо не вміщується в область №1."""
    rec_len = rec_len_for(text_chars)
    recs = {}
    for rid, text in records:
        if not (0 < int(rid) <= 0xFFFFFF):
            raise DbError("ID %s не вміщується в 3 байти (формат 'N')" % rid)
        recs.setdefault(int(rid), text)
    if len(recs) > capacity(rec_len):
        raise DbError("записів %d, а в область №1 уміщується лише %d (запис %d Б)" % (len(recs), capacity(rec_len), rec_len))
    body = bytearray()
    for rid in sorted(recs):
        body += struct.pack("<I", rid)[:3] + compress_text(recs[rid], rec_len - 3)
    return make_header(rec_len, len(recs)) + bytes(body)


class Image:
    """Розібраний образ бази (з рації, зі збереженого файла)."""
    def __init__(self):
        self.valid = False
        self.problems = []          # фатальні: образ не можна записати
        self.warnings = []
        self.mode = None            # 'N' | 'n' | 'plain'
        self.id_len = 4
        self.rec_len = 0
        self.count = 0
        self.records = []           # [(id, text)] -- лише ті, що є в даних
        self.extent = 0             # HEADER_LEN + count*rec_len
        self.in_area1 = True        # весь образ у межах області №1
        self.data = b""


def parse_image(data, want_records=True):
    img = Image()
    img.data = bytes(data)
    d = img.data
    if len(d) < HEADER_LEN:
        img.problems.append("менше за 12 байтів заголовка")
        return img
    if d[0:2] != b"Id":
        img.problems.append("нема підпису 'Id' на початку -- це не база позивних (у рації бази нема або вона пошкоджена)")
        return img
    mode = d[2:3]
    img.mode = "N" if mode == b"N" else ("n" if mode == b"n" else "plain")
    img.id_len = 3 if mode in (b"N", b"n") else 4
    img.rec_len = d[3] - LEN_BIAS
    img.count = struct.unpack("<I", d[8:12])[0]
    if img.rec_len <= img.id_len or img.rec_len > MAX_REC_LEN:
        img.problems.append("довжина запису %d Б поза допустимою (%d..%d)" % (img.rec_len, img.id_len + 1, MAX_REC_LEN))
        return img
    img.extent = HEADER_LEN + img.count * img.rec_len
    cap = capacity(img.rec_len)
    img.in_area1 = img.count <= cap
    if not img.in_area1:
        img.warnings.append("записів %d, а область №1 вміщує %d: решта бази лежить в області №2 (з 0x%X), де також таблиця ключів AES" % (img.count, cap, AREA2_START))
    if img.mode == "n":
        img.warnings.append("база формату 'n': область №2 лежить на голосових підказках")
    if img.mode in ("N", "n") and (img.rec_len - 3) % 3:
        img.warnings.append("довжина стисненого тексту не кратна 3 -- прошивка розгортає такий текст з похибкою")
    avail = (len(d) - HEADER_LEN) // img.rec_len
    n_read = min(img.count, avail)
    if want_records and n_read < img.count and img.in_area1:        # лише коли дані розібрано повністю (заголовок з рації сам по собі не «обрізаний»)
        img.problems.append("дані містять %d записів із %d, заявлених у заголовку (файл обрізано)" % (n_read, img.count))
    if want_records:
        prev = -1
        for i in range(n_read):
            off = HEADER_LEN + i * img.rec_len
            raw = d[off:off + img.id_len]
            rid = int.from_bytes(raw, "little")
            if img.id_len == 4:
                rid = bcd2int(rid)
                if rid is None:
                    img.problems.append("запис %d: ID не є BCD" % i)
                    break
            if rid <= prev:
                img.problems.append("записи не відсортовані за зростанням ID (запис %d: %d після %d) -- двійковий пошук прошивки їх не знайде" % (i, rid, prev))
                break
            prev = rid
            body = d[off + img.id_len:off + img.rec_len]
            text = decompress_text(body) if img.id_len == 3 else body.split(b"\x00", 1)[0].decode("latin-1").rstrip(" ")
            img.records.append((rid, text))
    if 1 < img.count <= MIN_ENTRIES_BEFORE_USING_SLICES:
        img.warnings.append("записів %d (≤ %d): у прошивці для НАЙБІЛЬШОГО ID пошук без «зрізів» читає запис №0 -- замість найбільшого ID покаже текст першого "
                            "(за кодом dmrIDLookup; на залізі не перевірено). Для справжньої бази неістотно" % (img.count, MIN_ENTRIES_BEFORE_USING_SLICES))
    img.valid = not img.problems
    return img


def validate_for_write(img):
    """Список причин, чому образ НЕ можна записати в область №1 (порожній -- можна)."""
    bad = list(img.problems)
    if img.mode == "n":
        bad.append("формат 'n' кладе область №2 на голосові підказки -- такі бази цей інструмент не пише")
    if img.valid and not img.in_area1:
        bad.append("образ більший за область №1 (%d записів при місткості %d) -- запис в область №2 заборонено, бо там таблиця ключів AES" % (img.count, capacity(img.rec_len)))
    if img.valid and img.extent > AREA1_LEN:
        bad.append("образ виходить за область №1")
    return bad


# ---------------------------------------------------------------------------------------------
#  Джерела: CSV / JSON, завантаження
# ---------------------------------------------------------------------------------------------

ID_KEYS = ("RADIO_ID", "DMR_ID", "DMRID", "RADIOID", "ID")
KEYS_BY_COL = {
    "callsign": ("CALLSIGN", "CALL", "CALL_SIGN"),
    "first": ("FIRST_NAME", "FNAME", "FIRSTNAME", "NAME"),
    "last": ("LAST_NAME", "LNAME", "SURNAME", "LASTNAME"),
    "city": ("CITY", "TOWN"),
    "state": ("STATE", "PROVINCE", "REGION"),
    "country": ("COUNTRY",),
    "date": ("LAST_HEARD", "LASTHEARD", "LAST_SEEN", "LASTSEEN", "LAST_ACTIVITY", "LAST_ACTIVE", "UPDATED", "UPDATED_AT", "DATE"),
}


def _norm(k):
    return "".join(c if c.isalnum() else "_" for c in str(k).strip().upper())


def decode_bytes(raw):
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def parse_date(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)) or str(v).isdigit():
        try:
            n = float(v)
            if n > 1e11:
                n /= 1000.0
            return datetime.datetime.fromtimestamp(n, datetime.timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# --- T3 (R32): розбір, терпимий до назв колонок; колонку знаходимо ЗА ЗМІСТОМ, якщо за іменем не вийшло -------------------------------------
RE_DMR_ID = re.compile(r"^\d{7}$")                                                     # DMR ID за змістом: рівно 7 цифр
RE_CALLSIGN = re.compile(r"^[A-Z0-9]{1,3}[0-9][A-Z0-9]{0,3}[A-Z](?:[-/][A-Z0-9]{1,4})?$")   # позивний за змістом: префікс, цифра, суфікс
SAMPLE_ROWS = 300                                                                       # скільки перших рядків дивимось, щоб вгадати колонки
SHOW_LINES = 3                                                                          # скільки перших рядків файла показуємо, коли не розпізнано
ORDER_AFTER_CALLSIGN = ("first", "last", "city", "state", "country")                    # порядок Radioid після позивного (лише коли заголовка нема)
FIELD_TITLES = {"id": "DMR ID", "callsign": "позивний", "first": "ім'я", "last": "прізвище", "city": "місто", "state": "область", "country": "країна",
                "date": "остання активність"}
_NORM_CACHE = {}


def _normc(k):
    v = _NORM_CACHE.get(k)
    if v is None:
        v = _NORM_CACHE[k] = _norm(k)
    return v


def first_lines(text, n=SHOW_LINES, width=160):
    """Перші `n` рядків тексту для повідомлення про помилку (довгі обрізаються)."""
    out = []
    for i, line in enumerate(text.splitlines()[:n], 1):
        line = line.rstrip()
        out.append("  %d: %s" % (i, (line[:width] + "…") if len(line) > width else line))
    return "\n".join(out) if out else "  (файл порожній)"


def _unrecognized(raw, text, why):
    """DbError з поясненням і перевіркою «що саме прийшло» (T3.2): перші три рядки файла, а не лише «не знайдено колонки»."""
    hint = ""
    if isinstance(raw, (bytes, bytearray)) and b"\x00" in raw[:4096]:
        hint = " Схоже на бінарний файл, а не на текст (CSV/JSON)."
        shown = "  (перші байти: %s)" % bytes(raw[:32]).hex()
    else:
        shown = first_lines(text)
        if text.lstrip()[:1] == "<":
            hint = " Схоже на веб-сторінку (HTML), а не на базу -- можливо, сервер віддав сторінку помилки."
    return DbError("Файл не розпізнано: %s.%s Ось що прийшло (перші рядки):\n%s" % (why, hint, shown))


def _map_by_name(names):
    """names -- список нормалізованих назв колонок -> {поле: індекс}. Одна колонка не може бути двома полями."""
    out, used = {}, set()
    for field, keys in (("id", ID_KEYS),) + tuple(KEYS_BY_COL.items()):
        for k in keys:
            if k in names and names.index(k) not in used:
                out[field] = names.index(k)
                used.add(names.index(k))
                break
    return out


def _detect_by_content(sample, mapped, headerless):
    """Доповнює `mapped` колонками, знайденими за змістом, і повертає пояснення (список рядків). `sample` -- рядки-списки."""
    notes = []
    ncols = max((len(r) for r in sample), default=0)

    def col(i):
        return [r[i].strip() for r in sample if i < len(r) and r[i].strip()]

    def pick(pred, need, skip):
        best = None
        for i in range(ncols):
            if i in skip:
                continue
            vals = col(i)
            if not vals:
                continue
            frac = sum(1 for v in vals if pred(v)) / float(len(vals))
            if frac >= need and (best is None or frac > best[0]):
                best = (frac, i)
        return best[1] if best else None

    if "id" not in mapped:
        i = pick(lambda v: bool(RE_DMR_ID.match(v)), 0.9, set(mapped.values()))
        if i is not None:
            mapped["id"] = i
            notes.append("колонку з DMR ID знайдено за змістом (7-значні числа): колонка %d" % (i + 1))
    if "id" in mapped and "callsign" not in mapped:
        i = pick(lambda v: bool(RE_CALLSIGN.match(v.upper())), 0.8, set(mapped.values()))
        if i is not None:
            mapped["callsign"] = i
            notes.append("колонку з позивним знайдено за змістом: колонка %d" % (i + 1))
    if headerless and "callsign" in mapped:
        nxt = mapped["callsign"] + 1
        for f in ORDER_AFTER_CALLSIGN:
            if f not in mapped and nxt < ncols and nxt not in mapped.values():
                mapped[f] = nxt
                notes.append("%s: колонка %d (за порядком Radioid; заголовка в файлі нема)" % (FIELD_TITLES[f], nxt + 1))
            nxt += 1
    return notes


def _make_row(get):
    try:
        rid = int(str(get("id") or "").strip())
    except ValueError:
        return None
    r = {"id": rid}
    for f in ("callsign", "first", "last", "city", "state", "country"):
        r[f] = " ".join(str(get(f) or "").split())            # зайві пробіли всередині й по краях -- прибрати
    r["date"] = parse_date(get("date"))
    return r


class Source:
    """Рядки з файла + що в ньому розпізнано (notes -- як саме знайдено колонки, columns -- поле -> опис колонки)."""
    def __init__(self, rows, skipped, has_date, name="", notes=None, columns=None):
        self.rows, self.skipped, self.has_date, self.name = rows, skipped, has_date, name
        self.notes = list(notes or [])
        self.columns = dict(columns or {})

    def describe(self):
        return "; ".join("%s -- %s" % (FIELD_TITLES[f], self.columns[f]) for f in FIELD_TITLES if f in self.columns)


def parse_source(raw, name=""):
    """CSV (з заголовком або без) чи JSON (список або {"users":[...]}/{"result":[...]}) -> Source. Колонки шукаємо за назвою, а якщо не вийшло --
    за змістом (7-значний DMR ID, позивний). Нерозпізнаний файл -> DbError з першими трьома рядками файла."""
    text = decode_bytes(raw) if isinstance(raw, (bytes, bytearray)) else raw
    stripped = text.lstrip()
    rows, skipped = [], 0
    if stripped[:1] in "[{":
        try:
            doc = json.loads(stripped)
        except ValueError as e:
            raise _unrecognized(raw, text, "файл схожий на JSON, але не читається (%s)" % e)
        items = doc if isinstance(doc, list) else next((doc[k] for k in ("users", "result", "results", "data") if isinstance(doc.get(k), list)), None)
        if items is None:
            raise _unrecognized(raw, text, "у JSON не знайдено списку користувачів (очікувалось поле users/result)")
        keys = []
        for it in items[:SAMPLE_ROWS]:
            if isinstance(it, dict):
                for k in it:
                    if k not in keys:
                        keys.append(k)
        names = [_normc(k) for k in keys]
        mapped = _map_by_name(names)
        sample = [[("" if it.get(k) is None else str(it.get(k))) for k in keys] for it in items[:SAMPLE_ROWS] if isinstance(it, dict)]
        notes = _detect_by_content(sample, mapped, headerless=False)
        if "id" not in mapped:
            raise _unrecognized(raw, text, "у записах JSON не знайдено поля з DMR ID (поля: %s)" % (", ".join(keys[:12]) or "нема"))
        field_key = {f: keys[i] for f, i in mapped.items()}
        for it in items:
            if not isinstance(it, dict):
                skipped += 1
                continue
            r = _make_row(lambda f, it=it: it.get(field_key[f]) if f in field_key else None)
            if r is None:
                skipped += 1
                continue
            rows.append(r)
        columns = {f: "поле «%s»" % k for f, k in field_key.items()}
    else:
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        matrix = [rec for rec in csv.reader(io.StringIO(text), dialect) if rec and any(c.strip() for c in rec)]
        if not matrix:
            raise _unrecognized(raw, text, "файл порожній або не містить таблиці")
        first = [c.strip() for c in matrix[0]]
        headerless = any(RE_DMR_ID.match(c) for c in first)              # у першому рядку вже є 7-значний ID -- це дані, а не заголовок
        if headerless:
            names, data = [], matrix
        else:
            names, data = [_norm(c) for c in first], matrix[1:]
        mapped = _map_by_name(names)
        notes = _detect_by_content(data[:SAMPLE_ROWS], mapped, headerless)
        if "id" not in mapped:
            raise _unrecognized(raw, text, "не знайдено колонки з DMR ID ні за назвою (RADIO_ID, DMR_ID, ID ...), ні за змістом (7-значні числа)")
        for rec in data:
            r = _make_row(lambda f, rec=rec: rec[mapped[f]] if f in mapped and mapped[f] < len(rec) else None)
            if r is None:
                skipped += 1
                continue
            rows.append(r)
        columns = {f: ("колонка %d" % (i + 1)) + (" «%s»" % first[i] if not headerless and i < len(first) and first[i] else "") for f, i in mapped.items()}
    has_date = any(r["date"] is not None for r in rows)
    return Source(rows, skipped, has_date, name, notes, columns)


def _partial_json_items(text):
    """Повні об'єкти зі шматка JSON-списку (початок файла, обірваний посередині): те, що вдалося прочитати до першого обриву."""
    start = text.find("[")
    if start < 0:
        return []
    dec = json.JSONDecoder()
    items, pos = [], start + 1
    while True:
        while pos < len(text) and text[pos] in " \t\r\n,":
            pos += 1
        if pos >= len(text) or text[pos] != "{":
            break
        try:
            obj, pos = dec.raw_decode(text, pos)
        except ValueError:
            break
        items.append(obj)
    return items


def probe_bytes(raw):
    """P2.2: що можна сказати про джерело за його ПОЧАТКОМ (кілька КБ). Повертає словник:
    head -- перші три рядки як є; ok -- розбір впізнав колонки; rows -- скільки повних записів у шматку; columns -- опис; notes; why -- чому ні."""
    text = decode_bytes(raw) if isinstance(raw, (bytes, bytearray)) else raw
    res = {"head": first_lines(text) if not (isinstance(raw, (bytes, bytearray)) and b"\x00" in raw[:4096]) else "  (бінарні дані: %s)" % bytes(raw[:32]).hex(),
           "ok": False, "rows": 0, "columns": "", "notes": [], "why": ""}
    stripped = text.lstrip()
    try:
        if stripped[:1] in "[{":
            items = _partial_json_items(stripped)
            if not items:
                res["why"] = "у початку JSON нема жодного повного запису (можливо, записи завеликі для шматка в 2 КБ)"
                return res
            src = parse_source(json.dumps(items), "probe")
        else:
            cut = text if text.endswith("\n") else text[:text.rfind("\n") + 1]     # остання рядок могла обірватись -- відкидаємо
            if not cut.strip():
                res["why"] = "у початку файла нема жодного повного рядка"
                return res
            src = parse_source(cut, "probe")
    except DbError as e:
        res["why"] = str(e).split("\n")[0]
        return res
    res.update(ok=True, rows=len(src.rows), columns=src.describe(), notes=list(src.notes))
    if not src.rows:
        res["why"] = "заголовок впізнано, але повних рядків даних у початку файла нема"
    return res


def probe_url(url, nbytes=2048, timeout=30):
    """P2.2: запит ЛИШЕ початку файла (Range + читання не більше `nbytes`), без завантаження всього. Викликається за явним натисканням.
    Повертає словник probe_bytes + status, contentType, size (з заголовків), error."""
    if not url.lower().startswith(("http://", "https://")):
        raise DbError("адреса має починатися з http:// або https://")
    req = urllib.request.Request(url, headers={"User-Agent": "OpenTYT-CPS/R33", "Range": "bytes=0-%d" % (nbytes - 1)})
    out = {"status": None, "contentType": "", "size": "", "error": ""}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(nbytes)
            out["status"] = getattr(resp, "status", None)
            out["contentType"] = resp.headers.get("Content-Type", "")
            cr = resp.headers.get("Content-Range", "")
            out["size"] = cr.split("/")[-1] if "/" in cr else (resp.headers.get("Content-Length") or "")
    except urllib.error.HTTPError as e:
        out.update(status=e.code, contentType=e.headers.get("Content-Type", "") if e.headers else "")
        raw = e.read(nbytes)
        out["error"] = "сервер відповів кодом %s" % e.code
    except (urllib.error.URLError, OSError) as e:
        raise DbError("з'єднатися не вдалося: %s" % getattr(e, "reason", e))
    res = probe_bytes(raw)
    res.update(out)
    return res


def probe_text(res):
    """Людський текст за результатом probe_url / probe_bytes."""
    lines = []
    if res.get("status") is not None:
        lines.append("Відповідь: код %s%s%s." % (res["status"], (", тип " + res["contentType"]) if res.get("contentType") else "",
                                                 (", розмір файла %s Б" % res["size"]) if res.get("size") else ""))
    lines.append("Початок файла (перші три рядки):\n" + res["head"])
    if res["ok"] and not res["why"]:
        lines.append("Розбір ПІДХОДИТЬ: у початку %d повних записів; %s." % (res["rows"], res["columns"]))
        if res["notes"]:
            lines.append("; ".join(res["notes"]) + ".")
    else:
        lines.append("Розбір НЕ розпізнає цей початок: %s." % (res["why"] or "невідома причина"))
    return "\n".join(lines)


def read_source_file(path):
    with open(path, "rb") as f:
        raw = f.read()
    return parse_source(raw, os.path.basename(path))


def download(url, dest, progress=None, log=print, timeout=60):
    """Завантажити URL у файл `dest` (шлях обирає користувач). Викликається ЛИШЕ за явним натисканням. Повертає (байтів, секунд).
    Нічого не кешується: файл лишається там, куди його поклали. Часткове завантаження не лишається під цим іменем."""
    if not url.lower().startswith(("http://", "https://")):
        raise DbError("адреса має починатися з http:// або https://")
    req = urllib.request.Request(url, headers={"User-Agent": "OpenTYT-CPS/R31"})
    t0 = time.time()
    tmp = dest + ".part"
    got = 0
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp, "wb") as f:
            total = int(resp.headers.get("Content-Length") or 0)
            log("З'єднано. Розмір за заголовком: %s." % (("%.1f МБ" % (total / 1048576.0)) if total else "невідомий"))
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if progress:
                    progress(int(100.0 * got / total) if total else 0, "Завантажено %.1f МБ за %.0f с" % (got / 1048576.0, time.time() - t0))
        os.replace(tmp, dest)
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise DbError("завантаження не вдалося: %s" % e)
    return got, time.time() - t0


# ---------------------------------------------------------------------------------------------
#  Фільтри й складання тексту
# ---------------------------------------------------------------------------------------------

def parse_prefixes(text):
    out = []
    for p in str(text or "").replace(";", ",").replace(" ", ",").split(","):
        p = p.strip()
        if not p:
            continue
        if not p.isdigit():
            raise DbError("префікс DMR ID має складатися з цифр, а не «%s»" % p)
        out.append(p)
    return out


def parse_countries(text):
    """Країни через кому або «;» (значення колонки COUNTRY). Порожньо -- без фільтра за країною."""
    return [c.strip() for c in str(text or "").replace(";", ",").split(",") if c.strip()]


def parse_columns(text):
    names = [c.strip().lower() for c in str(text or "").replace(";", ",").split(",") if c.strip()]
    if not names:
        raise DbError("не обрано жодної колонки для тексту запису")
    bad = [n for n in names if n not in COLUMN_NAMES]
    if bad:
        raise DbError("невідомі колонки: %s. Доступні: %s" % (", ".join(bad), ", ".join(COLUMN_NAMES)))
    return names


def compose(row, columns):
    return sanitize(" ".join(str(row.get(c) or "").strip() for c in columns if str(row.get(c) or "").strip()))


def apply_filters(rows, prefixes=(), max_inactive_days=None, limit=None, today=None, has_date=None, countries=()):
    """Повертає (відібрані рядки, інфо). Дублікати за ID -- перший. ID поза 1..0xFFFFFF відкидаються (формат 'N' має 3 байти).
    Бездіяльність: лише якщо в джерелі є колонка з датою; інакше інфо["inactiveUnavailable"] і фільтр НЕ застосовується (мовчки не відкидаємо нічого).
    R50: `countries` -- значення колонки COUNTRY (без урахування регістру). Регіон = початок ID З `prefixes` АБО країна зі `countries`. Якщо в джерелі нема
    жодної країни -- фільтр країн НЕ застосовується (інфо["countryUnavailable"]), діють лише префікси."""
    today = today or datetime.date.today()
    info = {"input": len(rows), "badId": 0, "dups": 0, "region": 0, "inactive": 0, "limited": 0, "inactiveUnavailable": False, "countryUnavailable": False}
    if has_date is None:
        has_date = any(r.get("date") for r in rows)
    want_countries = {c.strip().casefold() for c in countries if c and c.strip()}
    if want_countries and not any(r.get("country") for r in rows):
        want_countries = set()
        info["countryUnavailable"] = True
    seen, out = set(), []
    for r in rows:
        rid = r["id"]
        if not (0 < rid <= 0xFFFFFF):
            info["badId"] += 1
            continue
        if rid in seen:
            info["dups"] += 1
            continue
        seen.add(rid)
        if prefixes or want_countries:
            by_id = bool(prefixes) and any(str(rid).startswith(p) for p in prefixes)
            by_country = bool(want_countries) and (r.get("country") or "").strip().casefold() in want_countries
            if not (by_id or by_country):
                info["region"] += 1
                continue
        if max_inactive_days is not None:
            if not has_date:
                info["inactiveUnavailable"] = True
            else:
                d = r.get("date")
                if d is None or (today - d).days > max_inactive_days:
                    info["inactive"] += 1
                    continue
        out.append(r)
    if limit is not None and len(out) > limit:
        if has_date:
            out.sort(key=lambda r: (r.get("date") or datetime.date.min), reverse=True)
        else:
            out.sort(key=lambda r: r["id"])
        info["limited"] = len(out) - limit
        out = out[:limit]
    out.sort(key=lambda r: r["id"])
    info["selected"] = len(out)
    return out, info


class Job:
    """Усе, що панель показує до запису: скільки в файлі, скільки відібрано, скільки вміститься й скільки буде записано (D3.3, R33 P1.3/P4.3)."""
    def __init__(self, source, prefixes, max_inactive_days, limit, columns, text_chars, today=None, countries=()):
        self.file_rows = len(source.rows)
        self.rows, self.info = apply_filters(source.rows, prefixes, max_inactive_days, limit, today, source.has_date, countries)
        self.columns = columns
        self.text_chars = text_chars
        self.rec_len = rec_len_for(text_chars)
        self.cap = capacity(self.rec_len)
        self.selected = len(self.rows)
        self.fits = self.selected <= self.cap
        self.written = min(self.selected, self.cap)          # рядки відсортовані за ID: що не влізло -- ОСТАННІ за ID
        self.dropped = self.selected - self.written

    def records(self, truncate=False):
        rows = self.rows[:self.written] if truncate else self.rows
        return [(r["id"], compose(r, self.columns)) for r in rows]

    def stored_text(self, text):
        """Те, що справді ляже в запис і що рація покаже: текст обрізано до довжини запису."""
        return decompress_text(compress_text(text, self.rec_len - 3))

    def preview(self, n=5):
        return ["%d  %s" % (rid, self.stored_text(t)) for rid, t in self.records()[:n]]

    def table_rows(self):
        """Усі записи, що підуть у рацію (P4.1): [(ID, позивний з файла, текст у записі)] -- рівно min(відібрано, місткість), за зростанням ID."""
        return [(r["id"], r.get("callsign") or "", self.stored_text(compose(r, self.columns))) for r in self.rows[:self.written]]

    def counts(self):
        return {"file": self.file_rows, "filtered": self.selected, "cap": self.cap, "written": self.written, "dropped": self.dropped}

    def counts_line(self):
        """Один рядок над таблицею (P4.3)."""
        return "У файлі %d, після фільтрів %d, влізе %d, буде записано %d." % (self.file_rows, self.selected, self.cap, self.written)

    def dropped_text(self):
        """Слова про те, що відкинеться, коли відібрано більше, ніж влізе (порожньо, якщо все влазить)."""
        if not self.dropped:
            return ""
        first_dropped = self.rows[self.written]["id"]
        return ("Не вміщається %d записів: у рацію потраплять перші %d за зростанням ID (до %d включно); відкинуться ОСТАННІ за ID (від %d до %d)."
                % (self.dropped, self.written, self.rows[self.written - 1]["id"] if self.written else 0, first_dropped, self.rows[-1]["id"]))

    def summary(self):
        i = self.info
        lines = [self.counts_line(),
                 "Відкинуто фільтрами: хибний ID %d, дублікатів %d, не з обраних регіонів %d, неактивних %d, понад ліміт %d." % (
                     i["badId"], i["dups"], i["region"], i["inactive"], i["limited"]),
                 "Запис %d Б; у область №1 вміщується %d." % (self.rec_len, self.cap)]
        if i["inactiveUnavailable"]:
            lines.append("УВАГА: у файлі нема колонки з датою активності -- фільтр бездіяльності НЕ застосовано.")
        if i.get("countryUnavailable"):
            lines.append("УВАГА: у файлі нема колонки з країною (COUNTRY) -- фільтр за країною НЕ застосовано, діє лише початок DMR ID.")
        if not self.fits:
            lines.append("НЕ ВМІЩУЄТЬСЯ: на %d записів більше. %s Звуж фільтри або задай ліміт записів. У область №2 пишу не буду (там таблиця ключів AES)."
                         % (self.selected - self.cap, self.dropped_text()))
        return "\n".join(lines)

    def image(self, truncate=False):
        """Образ для запису. Без truncate, якщо не вміщується, -- DbError. З truncate=True (панель питає підтвердження словами) -- перші `cap` за ID."""
        if not self.fits and not truncate:
            raise DbError("відібрано %d записів, а вміщується %d" % (self.selected, self.cap))
        if not self.written:
            raise DbError("після фільтрів не лишилось жодного запису -- писати нічого")
        return build_image(self.records(truncate=truncate), self.text_chars)


# ---------------------------------------------------------------------------------------------
#  Файл бази (збереження / завантаження) і читання з рації
# ---------------------------------------------------------------------------------------------

def trim_image(data):
    """Обрізати до HEADER_LEN + count*rec_len (якщо це все в даних); для образу з областю №2 -- до того, що в даних."""
    img = parse_image(data, want_records=False)
    if img.problems and not img.rec_len:
        return bytes(data)
    return bytes(data[:min(len(data), img.extent)])


def load_db_file(path):
    """Файл бази -> байти образу. .zip (повний знімок) -- частина dmrIdDb; інакше сирий образ."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                manifest = json.loads(z.read("manifest.json").decode("utf-8"))
                part = manifest.get("parts", {}).get(PART_KEY)
                if part is None:
                    raise DbError("в цьому архіві бази позивних нема (вона лише в повному знімку)")
                data = z.read(part["file"])
        except (zipfile.BadZipFile, KeyError, ValueError) as e:
            raise DbError("архів не читається: %s" % e)
        if hashlib.sha256(data).hexdigest() != part.get("sha256") or len(data) != part.get("length"):
            raise DbError("база в архіві пошкоджена (SHA-256 або довжина не збігаються з маніфестом)")
        raw = data
    img = parse_image(raw, want_records=False)
    if not img.rec_len:
        raise DbError("файл не є базою позивних: %s" % "; ".join(img.problems))
    return trim_image(raw)


SOURCE_EXTS = (".csv", ".json", ".txt", ".tsv")


def detect_file_kind(path):
    """R50: що за файл бази -- 'image' (готовий образ .bin або повний знімок .zip) чи 'source' (CSV/JSON для складання). За змістом, а не лише за розширенням:
    початок 'PK' -- архів; розширення .csv/.json/.txt/.tsv -- джерело; .bin -- образ; інакше -- нуль-байти в початку файла означають образ."""
    with open(path, "rb") as f:
        head = f.read(1024)
    if head[:2] == b"PK":
        return "image"
    ext = os.path.splitext(path)[1].lower()
    if ext in SOURCE_EXTS:
        return "source"
    if ext == ".bin":
        return "image"
    return "image" if b"\0" in head else "source"


def save_db_file(path, image):
    with open(path, "wb") as f:
        f.write(image)


def read_radio_header(link):
    return parse_image(link.read(cl.CPS_ACCESS_FLASH, AREA1_START, HEADER_LEN), want_records=False)


def read_radio_db(link, progress=None):
    """Образ бази з рації: заголовок + записи в межах області №1 (якщо база довша -- лише частина з області №1, це видно в img.in_area1)."""
    h = read_radio_header(link)
    if not h.rec_len:
        raise DbError("у рації бази позивних нема або заголовок пошкоджено: %s" % "; ".join(h.problems))
    n = min(h.extent, AREA1_LEN)
    data = link.read(cl.CPS_ACCESS_FLASH, AREA1_START, n, progress)
    return data


# ---------------------------------------------------------------------------------------------
#  Запис у рацію
# ---------------------------------------------------------------------------------------------

def _round_up(n, q=SECTOR):
    return (n + q - 1) // q * q


def plan_text(img, old, sectors):
    lines = ["Записати базу позивних в область №1 (SPI 0x%X..0x%X):" % (AREA1_START, AREA1_START + AREA1_LEN - 1),
             "  нова база: %d записів по %d Б (%s), займе %d Б; секторів до запису: %d." % (
                 img.count, img.rec_len, "3-байтний ID, стиснутий текст" if img.id_len == 3 else "4-байтний ID", img.extent, sectors)]
    if old.rec_len and old.valid:
        lines.append("  зараз у рації: %d записів по %d Б (формат %s)." % (old.count, old.rec_len, old.mode))
    else:
        lines.append("  зараз у рації валідної бази нема.")
    for w in old.warnings:
        lines.append("  у рації: " + w)
    for w in img.warnings:
        lines.append("  нова база: " + w)
    lines += ["", "Порядок: спершу заголовок бази обнуляється (прошивка перестає бачити стару), далі пишуться сектори, заголовок -- останнім.",
              "Якщо запис обірвати, бази в рації не буде (позивні покажуть номери), але нічого іншого не зіпсовано; стара база збережена у страховій копії.",
              "Область №2 (там таблиця ключів AES) і все поза областю №1 не чіпаю. Після запису рація перезавантажується."]
    return "\n".join(lines)


def write_db(link, image, confirm, progress=None, log=print, safety_dir=None, now=None, cancel=None, rng=None, post_reset=True):
    """Записати образ бази в область №1. confirm(text, info) -> bool після страхової копії, до першого запису. cancel() -> True зупиняє на межі сектора.
    Повертає словник: cancelled, nothingToDo, written, text, safetyCopy, sectorsWritten, verified."""
    def prog(p, t):
        if progress:
            progress(max(0, min(100, int(p))), t)

    img = parse_image(image)
    bad = validate_for_write(img)
    if bad:
        raise DbError("цю базу записувати не можна: " + "; ".join(bad))
    payload = bytes(image[:img.extent])
    if len(payload) != img.extent:
        raise DbError("образ коротший за заявлений заголовком")
    import phase_timing
    ph = phase_timing.Phases(link)                          # R73: час, запити, КіБ і ЧИСЛО СТИРАНЬ секторів по фазах -- у журнал
    with ph.phase("читання заголовка бази"):
        old = read_radio_header(link)
    old_extent = min(old.extent, AREA1_LEN) if old.rec_len else 0
    span = max(SECTOR, _round_up(max(old_extent, len(payload))))
    prog(2, "Читаю поточну область бази (страхова копія)...")
    with ph.phase("читання поточної області (страхова копія)"):
        old_bytes = link.read(cl.CPS_ACCESS_FLASH, AREA1_START, span, lambda d, t: prog(2 + 18.0 * d / max(1, t), "Читаю поточну область бази..."))
    d = safety_dir or os.getcwd()
    if not os.access(d, os.W_OK):
        raise DbError("нема права писати в теку %s, де має лежати страхова копія бази. Нічого не записано." % d)
    safety = cl.unique_path(d, cl.timestamp_name("dmrdb_pre-write", ".bin", now))
    try:
        with open(safety, "xb") as f:
            f.write(old_bytes)
        with open(safety, "rb") as f:
            if f.read() != old_bytes:
                raise OSError("записаний файл відрізняється від прочитаного")
    except OSError as e:
        try:
            os.unlink(safety)
        except OSError:
            pass
        raise DbError("не вдалося зберегти страхову копію бази (%s). Нічого не записано." % e)
    log("Страхова копія області бази збережена й перевірена: %s" % safety)

    new_span = max(SECTOR, _round_up(len(payload)))
    buf = bytearray(old_bytes[:new_span].ljust(new_span, b"\xff"))
    buf[:len(payload)] = payload
    invalid = bytearray(buf)
    invalid[:HEADER_LEN] = b"\x00" * HEADER_LEN
    sectors = [(k, bytes(invalid[k * SECTOR:(k + 1) * SECTOR])) for k in range(new_span // SECTOR)]

    def old_sector(k):
        return bytes(old_bytes[k * SECTOR:(k + 1) * SECTOR]).ljust(SECTOR, b"\xff")
    todo = [(k, s) for k, s in sectors if s != old_sector(k)]
    if all(bytes(buf[k * SECTOR:(k + 1) * SECTOR]) == old_sector(k) for k in range(new_span // SECTOR)):
        text = "Така сама база вже в рації -- записувати нічого."
        log(text)
        return {"cancelled": False, "nothingToDo": True, "written": False, "text": text, "safetyCopy": safety, "sectorsWritten": 0, "verified": None}
    if not confirm(plan_text(img, old, len(todo) + 1), {"image": img, "old": old, "sectors": len(todo)}):
        log("Скасовано користувачем; база в рації не змінена.")
        return {"cancelled": True, "nothingToDo": False, "written": False, "text": "Скасовано; базу в рації не змінено.", "safetyCopy": safety,
                "sectorsWritten": 0, "verified": None}

    total = len(todo) + 1
    done = [0]

    def on_sector(_k, _n):
        if cancel is not None and cancel():
            raise Cancelled()
        prog(20 + 70.0 * done[0] / total, "Пишу сектор %d з %d" % (done[0] + 1, total))

    header_cleared = bytes(old_bytes[:HEADER_LEN]) == b"\x00" * HEADER_LEN        # заголовок вже нульовий -- обнуляти нічого
    try:
        # сектор 0 (якщо він змінюється) іде першим, з обнуленим заголовком: обірваний запис = «бази нема», а не «база зі сміттям»
        with ph.phase("запис змінених секторів") as rec_w:
            for k, s in sorted(todo):
                fg.write_span(link.ser, AREA1_START + k * SECTOR, s, "dmrdb", on_sector)
                done[0] += 1
                if k == 0:
                    header_cleared = True
            rec_w["note"] = "секторів змінено %d з %d у зайнятій частині" % (len(todo), new_span // SECTOR)
        on_sector(0, 1)
        with ph.phase("запис заголовка останнім"):
            fg.write_span(link.ser, AREA1_START, payload[:HEADER_LEN], "dmrdb")
        done[0] += 1
    except Cancelled:
        text = ("Запис ПЕРЕРВАНО користувачем після %d з %d секторів. Заголовок бази обнулено, тож рація бази не бачить (позивні покажуть номери); "
                "решта рації не зачеплена. Щоб повернути стару базу, завантаж страхову копію:\n%s" % (done[0], total, safety))
        log(text)
        if post_reset and done[0]:
            _reset(link)
        return {"cancelled": True, "nothingToDo": False, "written": False, "text": text, "safetyCopy": safety, "sectorsWritten": done[0], "verified": None}
    except Exception as e:  # noqa: BLE001
        text = ("ПОМИЛКА під час запису бази (записано секторів: %d з %d): %s. Заголовок бази %s; решта рації не зачеплена. Страхова копія:\n%s" % (
            done[0], total, e, "обнулено -- бази в рації зараз нема" if header_cleared else "ще не чіпано", safety))
        log(text)
        return {"cancelled": False, "nothingToDo": False, "written": False, "failed": str(e), "text": text, "safetyCopy": safety, "sectorsWritten": done[0],
                "verified": None}

    prog(92, "Звіряю заголовок і випадкові записи...")
    rng = rng or random.SystemRandom()
    with ph.phase("звірка (заголовок і випадкові записи)"):
        ok, why = verify(link, payload, img, rng)
    log(ph.summary())
    text = "База записана: %d записів (%d Б), секторів записано %d. " % (img.count, img.extent, done[0])
    text += "Звірка читанням: %s." % ("пройшла (заголовок і %s)" % why if ok else "НЕ ПРОЙШЛА -- " + why)
    text += "\nСтрахова копія попередньої області:\n%s" % safety
    if post_reset:
        prog(97, "Перезавантажую рацію...")
        _reset(link)
    prog(100, "Готово")
    return {"cancelled": False, "nothingToDo": False, "written": True, "text": text, "safetyCopy": safety, "sectorsWritten": done[0], "verified": ok}


def _reset(link):
    import cps_restore
    cps_restore._send_c(link, 6, cps_restore.POST_RESTORE_SUB)


def verify(link, payload, img, rng, samples=8):
    """Звірка читанням: заголовок і кілька записів (перший, останній і випадкові). Повертає (ok, пояснення)."""
    head = link.read(cl.CPS_ACCESS_FLASH, AREA1_START, HEADER_LEN)
    if head != payload[:HEADER_LEN]:
        return False, "заголовок у рації відрізняється від записаного"
    idx = set()
    if img.count:
        idx = {0, img.count - 1}
        while len(idx) < min(samples, img.count):
            idx.add(rng.randrange(img.count))
    for i in sorted(idx):
        off = HEADER_LEN + i * img.rec_len
        back = link.read(cl.CPS_ACCESS_FLASH, AREA1_START + off, img.rec_len)
        if back != payload[off:off + img.rec_len]:
            return False, "запис №%d у рації відрізняється від записаного" % i
    return True, "%d записів" % len(idx)
