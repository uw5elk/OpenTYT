# -*- coding: utf-8 -*-
"""R35, частина A: елементи орбіт супутників (custom-data блок SATELLITE_TLE = тип 3).

ФОРМАТ -- ЛИШЕ З КОДУ ПРОШИВКИ (application/include/functions/satellite.h, source/functions/satellite.c, user_interface/menuSatelliteScreen.c loadKeps()):

  Блок = union codeplugSatelliteCuctsomDataUnion_t: 25 записів codeplugSatelliteData_t по 100 Б (packed, little-endian) + 20 Б добивки до 2520 Б.
  Запис (зміщення в записі):
     0  char     TLE_Name[8]      назва, НЕ обов'язково з нулем (8 символів = усі 8 байтів); порожній слот -- TLE_Name[0] == 0
     8  uint8    TLE_Line1[12]    24 «нібли»-символи (див. нижче): рік(2) + епоха(12) + перша похідна середнього руху(10)
    20  uint8    TLE_Line2[28]    56 нібл-символів: нахил(8) РAAН(8) ексцентриситет(7, без крапки) аргумент перигею(8) серед.аномалія(8)
                                  серед.рух(11) номер витка(5) + 1 добивка
    48  uint32   rxFreq1  (Гц)    голосова частота приймання   (menuSatelliteScreen: rxFreq / 1E6 = МГц)
    52  uint32   txFreq1  (Гц)    голосова частота передачі
    56  uint16   txCTCSS1         субтон передачі (кладеться в currentChannelData->txTone, тобто в десятих долях Гц)
    58  uint16   armCTCSS1        «взводний» субтон (uiTxScreen: trxSetTxCSS(armCTCSS))
    60  uint32   rxFreq2, 64 txFreq2   APRS-частоти   (txCTCSS/armCTCSS для них прошивка ставить 0)
    68  uint32   rxFreq3, 72 txFreq3   «інші» частоти
    76  char     AdditionalData[24]    APRS-шлях супутника: [0..5] ім'я 1, [6] '0'+SSID, [7..12] ім'я 2, [13] '0'+SSID (aprs.c); решта не використовується
  Нібл-стиснення (satellite.c decompressTleData): кожен байт = два символи, СТАРШИЙ ніббл першим; таблиця "0123456789. +-*" (0..14); ніббл 15 в таблиці
  нема (читався б нуль-термінатор), тому ми його НЕ пишемо; добивка -- пробіл (11).
  Завантаження (loadKeps): слоти читаються підряд від 0 до першого з TLE_Name[0] == 0 -- порожніх «дірок» між супутниками бути не може, тож збірка
  блока ущільнює слоти. Довжину наявного блока міняти не можна (codeplugSetOpenGD77CustomData) -- тому завжди рівно 2520 Б.

Обмеження, яких у коді немає, але які є у даних: у блоці немає номера NORAD і бета-коефіцієнта (B*) -- лише перша похідна руху; з-за цього збіг «нових елементів зі старим слотом»
робиться за НАЗВОЮ (8 символів), а не за номером; такий збіг показується користувачу для підтвердження, мовчки його не застосовують.

Модуль без Tk і без рації; запис у рацію -- функції write_slots / read_slots (custom_data.*), ті самі, що в темах."""
import datetime
import os
import struct
import urllib.error
import urllib.request

BLOCK_TYPE = 3                    # CODEPLUG_CUSTOM_DATA_TYPE_SATELLITE_TLE
NUM_SLOTS = 25                    # NUM_SATELLITES
REC_LEN = 100
BLOCK_LEN = 2520                  # sizeof(codeplugSatelliteCuctsomDataUnion_t) (forceToSize)
PAD_LEN = BLOCK_LEN - NUM_SLOTS * REC_LEN        # 20
NAME_LEN = 8
LOOKUP = "0123456789. +-*"
MAX_AGE_DAYS = 30                 # старіші за місяць -- попередження (A5)

STRUCT = struct.Struct("<8s12s28sIIHHIIII24s")
assert STRUCT.size == REC_LEN

CELESTRAK_AMATEUR = "https://celestrak.org/NORAD/elements/gp.php?GROUP=amateur&FORMAT=tle"


class SatError(ValueError):
    """Помилка даних супутників (пояснення словами)."""


# ---------------------------------------------------------------------------------------------------------------------------------
#  Нібл-стиснення
# ---------------------------------------------------------------------------------------------------------------------------------

def pack_chars(text, nbytes):
    """Рядок (до 2*nbytes символів з таблиці LOOKUP) -> nbytes байтів; недостачу добиває пробілом. SatError, якщо є символ поза таблицею."""
    if len(text) > 2 * nbytes:
        raise SatError("рядок завдовжки %d символів не вміщується в %d байтів" % (len(text), nbytes))
    text = text.ljust(2 * nbytes, " ")
    out = bytearray()
    for i in range(0, 2 * nbytes, 2):
        pair = 0
        for ch in text[i:i + 2]:
            k = LOOKUP.find(ch)
            if k < 0 or k > 14:
                raise SatError("символ «%s» не можна записати в блок (дозволено: %s)" % (ch, LOOKUP))
            pair = (pair << 4) | k
        out.append(pair)
    return bytes(out)


def unpack_chars(raw):
    """Байти -> рядок так, як їх бачить decompressTleData (ніббл 15 -> '?', у прошивці це був би нуль-термінатор)."""
    out = []
    for b in raw:
        for nib in (b >> 4, b & 0x0F):
            out.append(LOOKUP[nib] if nib <= 14 else "?")
    return "".join(out)


# ---------------------------------------------------------------------------------------------------------------------------------
#  Розбір файла TLE
# ---------------------------------------------------------------------------------------------------------------------------------

class Tle:
    """Один набір елементів із файла TLE."""

    def __init__(self, name, line1, line2, problems=None, warnings=None):
        self.name = name
        self.line1 = line1
        self.line2 = line2
        self.problems = list(problems or [])         # з такими елементами запис у рацію неможливий
        self.warnings = list(warnings or [])

    @property
    def ok(self):
        return not self.problems

    @property
    def catalog(self):
        return self.line1[2:7].strip()

    @property
    def epoch(self):
        return epoch_of(self.line1[18:20], self.line1[20:32])

    def short_name(self):
        return suggest_name(self.name)

    def __repr__(self):
        return "Tle(%r, %s)" % (self.name, "ok" if self.ok else self.problems)


def tle_checksum(line):
    """Контрольна сума рядка TLE (перші 68 символів): сума цифр, кожен '-' = 1, mod 10."""
    s = 0
    for ch in line[:68]:
        if ch.isdigit():
            s += int(ch)
        elif ch == "-":
            s += 1
    return s % 10


def epoch_of(yy, day):
    """('08', '264.51782528') -> datetime (UTC) або None. Рік -- 2000+yy (як у прошивці: getElement(...) + 2000)."""
    try:
        y = 2000 + int(yy)
        d = float(day)
    except ValueError:
        return None
    if not (1.0 <= d < 367.0):
        return None
    return datetime.datetime(y, 1, 1) + datetime.timedelta(days=d - 1.0)


def _clean(line):
    return line.rstrip("\r\n").rstrip()


def _check_lines(line1, line2):
    """(problems, warnings) для пари рядків TLE."""
    problems, warnings = [], []
    if len(line1) < 68 or len(line2) < 68:
        problems.append("рядок TLE коротший за 68 символів")
        return problems, warnings
    if line1[2:7] != line2[2:7]:
        warnings.append("номери NORAD у рядках 1 і 2 різні")
    for tag, line in (("1", line1), ("2", line2)):
        if len(line) >= 69 and line[68].isdigit() and int(line[68]) != tle_checksum(line):
            problems.append("контрольна сума рядка %s не збігається (%s, а має бути %d) -- рядок пошкоджено" % (tag, line[68], tle_checksum(line)))
    try:
        fields1_text(line1)
        fields2_text(line2)
    except SatError as e:
        problems.append(str(e))
    if epoch_of(line1[18:20], line1[20:32]) is None:
        problems.append("не вдалося розібрати епоху (рік/день) у рядку 1")
    for nm, a, b in (("нахил", 8, 16), ("РAAН", 17, 25), ("серед. аномалія", 43, 51), ("серед. рух", 52, 63)):
        try:
            float(line2[a:b])
        except ValueError:
            problems.append("поле «%s» у рядку 2 не число: «%s»" % (nm, line2[a:b]))
    return problems, warnings


def fields1_text(line1):
    """24 нібл-символи рядка 1: рік(2) + епоха(12) + ndot(10)."""
    s = line1[18:20] + line1[20:32] + line1[33:43]
    _validate_chars(s, "рядок 1")
    return s


def fields2_text(line2):
    """56 нібл-символів рядка 2: нахил(8) РAAН(8) ексцентриситет(7) аргумент перигею(8) серед.аномалія(8) серед.рух(11) виток(5) + пробіл."""
    s = line2[8:16] + line2[17:25] + line2[26:33] + line2[34:42] + line2[43:51] + line2[52:63] + line2[63:68] + " "
    _validate_chars(s, "рядок 2")
    return s


def _validate_chars(s, what):
    for ch in s:
        k = LOOKUP.find(ch)
        if k < 0 or k > 14:
            raise SatError("у %s є символ «%s», якого блок не вміщує" % (what, ch))


def parse_tle_text(text):
    """Текст у форматі TLE (2 або 3 рядки на супутник; CRLF, зайві пробіли й порожні рядки дозволені) -> (список Tle, список зауважень про
    неповні/непізнані фрагменти). Кожен Tle з проблемами теж у списку (з tle.problems), щоб користувач бачив, що саме не так."""
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode("utf-8", errors="replace")
    lines = [_clean(x) for x in text.replace("﻿", "").split("\n")]
    lines = [x for x in lines if x.strip()]
    out, notes = [], []
    i = 0
    name = None
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("1 ") and len(ln) >= 60:
            if i + 1 < len(lines) and lines[i + 1].startswith("2 "):
                l1, l2 = ln, lines[i + 1]
                nm = name if name is not None else ("SAT %s" % l1[2:7].strip())
                probs, warns = _check_lines(l1, l2)
                out.append(Tle(nm, l1, l2, probs, warns))
                i += 2
                name = None
                continue
            notes.append("після рядка 1 (%s) нема рядка 2 -- неповний запис пропущено" % (name or ln[2:7]))
            i += 1
            name = None
            continue
        if ln.startswith("2 ") and len(ln) >= 60:
            notes.append("рядок 2 без рядка 1 (%s) пропущено" % ln[2:7])
            i += 1
            name = None
            continue
        # інакше -- рядок назви (формат 3LE допускає префікс "0 ")
        name = ln[2:].strip() if ln.startswith("0 ") else ln.strip()
        i += 1
    if name is not None and not out and not notes:
        notes.append("у тексті нема жодного рядка TLE")
    if not out and not notes:
        notes.append("у тексті нема жодного рядка TLE")
    return out, notes


def read_tle_file(path):
    with open(path, "rb") as f:
        return parse_tle_text(f.read())


def suggest_name(full):
    """Скоротити назву Celestrak (напр. 'ISS (ZARYA)', 'AO-91 (RADFXSAT / FOX-1B)') до 8 символів ASCII для рації. Правило: частина до дужки, якщо влізає;
    інакше вміст дужки до '/', якщо влізає; інакше перші 8 символів. Користувач може змінити назву у слоті."""
    full = (full or "").strip()
    head = full.split("(")[0].strip()
    cands = []
    if head:
        cands.append(head)
    if "(" in full:
        inner = full[full.index("(") + 1:].split(")")[0]
        for part in inner.split("/"):
            cands.append(part.strip())
    cands.append(full)
    for c in cands:
        c = _ascii(c)
        if 0 < len(c) <= NAME_LEN:
            return c
    return _ascii(full)[:NAME_LEN] or "SAT"


def _ascii(s):
    return "".join(ch if 0x20 <= ord(ch) < 0x7F else "?" for ch in s).strip()


def norm_name(s):
    return "".join(ch for ch in s.upper() if ch.isalnum())


# ---------------------------------------------------------------------------------------------------------------------------------
#  Слот (запис блока)
# ---------------------------------------------------------------------------------------------------------------------------------

class Slot:
    """Запис блока. name -- рядок ASCII ≤ 8; l1/l2 -- нібл-символи (24/56); частоти в Гц; extra -- 24 байти AdditionalData."""

    def __init__(self, name="", l1="", l2="", rx1=0, tx1=0, ctcss=0, arm=0, rx2=0, tx2=0, rx3=0, tx3=0, extra=b""):
        self.name = name
        self.l1 = l1
        self.l2 = l2
        self.rx1, self.tx1, self.ctcss, self.arm = rx1, tx1, ctcss, arm
        self.rx2, self.tx2, self.rx3, self.tx3 = rx2, tx2, rx3, tx3
        self.extra = bytes(extra).ljust(24, b"\x00")[:24]

    @classmethod
    def from_tle(cls, tle, name=None, keep=None):
        """Новий слот із Tle. keep -- слот, з якого переносяться частоти/субтони/AdditionalData (оновлення елементів наявного супутника)."""
        s = cls(name if name is not None else tle.short_name(), fields1_text(tle.line1), fields2_text(tle.line2))
        if keep is not None:
            s.take_freqs_from(keep)
        return s

    def take_freqs_from(self, other):
        self.rx1, self.tx1, self.ctcss, self.arm = other.rx1, other.tx1, other.ctcss, other.arm
        self.rx2, self.tx2, self.rx3, self.tx3 = other.rx2, other.tx2, other.rx3, other.tx3
        self.extra = other.extra

    def copy(self):
        return Slot(self.name, self.l1, self.l2, self.rx1, self.tx1, self.ctcss, self.arm, self.rx2, self.tx2, self.rx3, self.tx3, self.extra)

    # --- похідні величини для показу ---
    @property
    def epoch(self):
        return epoch_of(self.l1[0:2], self.l1[2:14])

    @property
    def inclination(self):
        return _f(self.l2[0:8])

    @property
    def mean_motion(self):
        return _f(self.l2[39:50])

    @property
    def period_min(self):
        m = self.mean_motion
        return 1440.0 / m if m else None

    @property
    def eccentricity(self):
        v = _f(self.l2[16:23])
        return None if v is None else v * 1e-7

    def age_days(self, now=None):
        e = self.epoch
        if e is None:
            return None
        now = now or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        return (now - e).total_seconds() / 86400.0

    def problems(self):
        out = []
        if not self.name:
            out.append("порожня назва")
        if len(self.name) > NAME_LEN:
            out.append("назва довша за %d символів" % NAME_LEN)
        if self.epoch is None:
            out.append("елементи не читаються (епоха)")
        return out

    def freq_text(self):
        def mhz(v):
            return ("%.6f" % (v / 1e6)).rstrip("0").rstrip(".") if v else "-"
        return "RX %s / TX %s МГц" % (mhz(self.rx1), mhz(self.tx1))

    def pack(self):
        name = self.name.encode("ascii", errors="replace")
        if not (0 < len(name) <= NAME_LEN):
            raise SatError("назва супутника має бути від 1 до %d символів" % NAME_LEN)
        if name[0] == 0:
            raise SatError("назва не може починатися з нуля")
        for v, what in ((self.rx1, "rx1"), (self.tx1, "tx1"), (self.rx2, "rx2"), (self.tx2, "tx2"), (self.rx3, "rx3"), (self.tx3, "tx3")):
            if not (0 <= int(v) <= 0xFFFFFFFF):
                raise SatError("частота %s поза діапазоном" % what)
        for v, what in ((self.ctcss, "субтон"), (self.arm, "взводний субтон")):
            if not (0 <= int(v) <= 0xFFFF):
                raise SatError("%s поза діапазоном" % what)
        return STRUCT.pack(name.ljust(NAME_LEN, b"\x00"), pack_chars(self.l1, 12), pack_chars(self.l2, 28), int(self.rx1), int(self.tx1),
                           int(self.ctcss), int(self.arm), int(self.rx2), int(self.tx2), int(self.rx3), int(self.tx3), self.extra)

    @classmethod
    def unpack(cls, raw):
        (name, k1, k2, rx1, tx1, c1, a1, rx2, tx2, rx3, tx3, extra) = STRUCT.unpack(bytes(raw))
        nm = name.split(b"\x00", 1)[0].decode("ascii", errors="replace")
        return cls(nm, unpack_chars(k1), unpack_chars(k2), rx1, tx1, c1, a1, rx2, tx2, rx3, tx3, extra)


def _f(s):
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------------------------------------------------------------
#  Блок
# ---------------------------------------------------------------------------------------------------------------------------------

class Block:
    """Розібраний блок: slots -- список Slot (лише ті, які рація ЗАВАНТАЖИТЬ: до першого порожнього); hidden -- скільки непорожніх записів стоїть ПІСЛЯ
    порожнього слота (прошивка їх не бачить); pad -- добивка 20 Б."""

    def __init__(self, slots, hidden=0, pad=b"", length=BLOCK_LEN):
        self.slots = slots
        self.hidden = hidden
        self.pad = pad
        self.length = length


def parse_block(data):
    data = bytes(data)
    if len(data) < NUM_SLOTS * REC_LEN:
        raise SatError("блок коротший за %d байтів (є %d) -- це не блок супутників" % (NUM_SLOTS * REC_LEN, len(data)))
    slots, hidden, gap = [], 0, False
    for k in range(NUM_SLOTS):
        rec = data[k * REC_LEN:(k + 1) * REC_LEN]
        if rec[0] == 0:
            gap = True
            continue
        if gap:
            hidden += 1
        else:
            slots.append(Slot.unpack(rec))
    return Block(slots, hidden, data[NUM_SLOTS * REC_LEN:], len(data))


def build_block(slots):
    """Список Slot (≤ 25) -> рівно 2520 байтів; слоти ущільнено (порожніх «дірок» нема), решта записів -- нулі."""
    if len(slots) > NUM_SLOTS:
        raise SatError("слотів %d, а в рації їх лише %d" % (len(slots), NUM_SLOTS))
    out = bytearray(BLOCK_LEN)
    for k, s in enumerate(slots):
        out[k * REC_LEN:(k + 1) * REC_LEN] = s.pack()
    return bytes(out)


def stale_text(slots, now=None, limit=MAX_AGE_DAYS):
    """Попередження про застарілі елементи (A5) або ''."""
    old = []
    for s in slots:
        a = s.age_days(now)
        if a is not None and a > limit:
            old.append("%s (%d дн.)" % (s.name, int(a)))
    if not old:
        return ""
    return ("Елементи старші за %d днів: %s. Прогноз прольотів із застарілих елементів дедалі неточніший -- завантаж свіжі." % (limit, ", ".join(old)))


def epoch_text(slot):
    e = slot.epoch
    return e.strftime("%Y-%m-%d") if e else "?"


# ---------------------------------------------------------------------------------------------------------------------------------
#  Відбір і злиття
# ---------------------------------------------------------------------------------------------------------------------------------

def filter_tles(tles, query):
    """Пошук за назвою (без урахування регістру) або номером NORAD."""
    q = (query or "").strip().lower()
    if not q:
        return list(tles)
    return [t for t in tles if q in t.name.lower() or q in t.catalog or q in t.short_name().lower()]


def counts_line(found, chosen, existing=0):
    """A4: «Знайдено N, відібрано K, влізе 25 (вільно F)»."""
    free = max(0, NUM_SLOTS - existing)
    return "Знайдено %d, відібрано %d; у рації слотів %d, вільних %d%s." % (
        found, chosen, NUM_SLOTS, free, ("; не влізе %d (буде взято перші %d)" % (chosen - NUM_SLOTS, NUM_SLOTS)) if chosen > NUM_SLOTS else "")


def match_updates(slots, tles):
    """Для кожного наявного слота -- які TLE за назвою йому відповідають. Повертає список (index, [Tle...]) лише для слотів, де є збіг. Збіг: нормалізована
    назва слота дорівнює нормалізованій короткій назві, повній назві або якійсь частині в дужках. Кілька збігів -- неоднозначність (користувач має вибрати)."""
    res = []
    for i, s in enumerate(slots):
        ns = norm_name(s.name)
        if not ns:
            continue
        hits = []
        for t in tles:
            if not t.ok:
                continue
            keys = {norm_name(t.short_name()), norm_name(t.name)}
            full = t.name
            if "(" in full:
                inner = full[full.index("(") + 1:].split(")")[0]
                keys.update(norm_name(p) for p in inner.split("/"))
                keys.add(norm_name(full.split("(")[0]))
            if ns in keys:
                hits.append(t)
        if hits:
            res.append((i, hits))
    return res


def apply_updates(slots, choices):
    """choices: {індекс слота: Tle} -> новий список слотів; назва, частоти, субтони й AdditionalData лишаються, міняються лише елементи орбіти."""
    out = [s.copy() for s in slots]
    for i, tle in choices.items():
        old = out[i]
        new = Slot.from_tle(tle, name=old.name, keep=old)
        out[i] = new
    return out


def merge_add(slots, tles, names=None, replace=False):
    """Додати вибрані TLE у вільні слоти (replace=True -- замінити весь список). Повертає (новий список, скільки не влізло)."""
    base = [] if replace else [s.copy() for s in slots]
    dropped = 0
    for k, t in enumerate(tles):
        if not t.ok:
            continue
        if len(base) >= NUM_SLOTS:
            dropped += 1
            continue
        base.append(Slot.from_tle(t, name=(names[k] if names else None)))
    return base, dropped


# ---------------------------------------------------------------------------------------------------------------------------------
#  Рація
# ---------------------------------------------------------------------------------------------------------------------------------

ST_OK, ST_ABSENT, ST_NOREGION, ST_BADLEN = "ok", "absent", "noregion", "badlen"
STATE_TEXT = {
    ST_OK: "блок супутників є в рації",
    ST_ABSENT: "блока супутників у рації нема (екран супутників порожній)",
    ST_NOREGION: "область custom-data у рації не знайдено (немає заголовка OpenGD77) -- записати не можна",
    ST_BADLEN: "блок супутників у рації має нестандартну довжину -- прошивка не дозволяє її міняти, записати не можна",
}


def read_slots(ser):
    """-> (стан, Block|None, сирі байти|None)."""
    import custom_data as cd
    kind, addr, ln = cd.find_or_alloc_block(ser, BLOCK_TYPE, 0)
    if kind is None:
        return ST_NOREGION, None, None
    if kind == "empty":
        return ST_ABSENT, Block([]), None
    raw = cd._read_region(ser, addr + cd.HDR_LEN, ln)
    if ln != BLOCK_LEN:
        return ST_BADLEN, (parse_block(raw) if ln >= NUM_SLOTS * REC_LEN else None), raw
    return ST_OK, parse_block(raw), raw


def write_slots(ser, slots, safety_dir=None, now=None, log=print):
    """Записати список слотів: страхова копія наявного блока у файл, запис, звірка читанням. Повертає (текст, шлях страхової копії|None).
    RuntimeError -- відмова/збій/незбіг."""
    import custom_data as cd
    payload = build_block(slots)
    state, _blk, old_raw = read_slots(ser)
    if state in (ST_NOREGION, ST_BADLEN):
        raise RuntimeError("супутники не записані: " + STATE_TEXT[state])
    safety = None
    if old_raw is not None:
        d = safety_dir or os.getcwd()
        if not os.access(d, os.W_OK):
            raise RuntimeError("нема права писати в теку %s, де має лежати страхова копія блока супутників. Нічого не записано." % d)
        ts = (now or datetime.datetime.now()).strftime("%Y%m%d_%H%M%S")
        safety = os.path.join(d, "satellites_pre-write_%s.bin" % ts)
        n = 1
        while os.path.exists(safety):
            n += 1
            safety = os.path.join(d, "satellites_pre-write_%s_%d.bin" % (ts, n))
        with open(safety, "xb") as f:
            f.write(old_raw)
        with open(safety, "rb") as f:
            if f.read() != old_raw:
                raise RuntimeError("страхову копію блока не вдалося перевірити -- нічого не записано")
        log("Страхова копія блока супутників: %s" % safety)
    ok, msg = cd.write_block(ser, BLOCK_TYPE, payload)
    if not ok:
        raise RuntimeError("супутники не записані: " + msg)
    back = cd.read_block(ser, BLOCK_TYPE, BLOCK_LEN)
    if back != payload:
        raise RuntimeError("супутники записані, але звірка читанням НЕ збіглася -- повторіть запис" + (("; стара копія: %s" % safety) if safety else ""))
    text = "Супутники записані: %d (%s). Звірка читанням: OK." % (len(slots), msg)
    stale = stale_text(slots, now=None)
    if stale:
        text += "\n" + stale
    if safety:
        text += "\nСтрахова копія попереднього блока:\n" + safety
    return text, safety


# ---------------------------------------------------------------------------------------------------------------------------------
#  Мережа (лише за явним натисканням кнопки; нічого не кешується)
# ---------------------------------------------------------------------------------------------------------------------------------

def probe_bytes(raw):
    """Що можна сказати про джерело за його ПОЧАТКОМ. -> словник: head (перші три рядки), ok, sets (скільки повних наборів), why."""
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else raw
    binary = isinstance(raw, (bytes, bytearray)) and b"\x00" in raw[:4096]
    head = "\n".join("  " + ln[:100] for ln in text.replace("\r", "").split("\n")[:3]) if not binary else "  (бінарні дані)"
    res = {"head": head, "ok": False, "sets": 0, "why": ""}
    cut = text if text.endswith("\n") else text[:text.rfind("\n") + 1]            # остання рядок могла обірватись
    tles, notes = parse_tle_text(cut)
    good = [t for t in tles if t.ok]
    res["sets"] = len(good)
    if good:
        res["ok"] = True
    else:
        res["why"] = (tles[0].problems[0] if tles else (notes[0] if notes else "нема жодного набору елементів"))
    return res


def probe_url(url, nbytes=2048, timeout=30):
    """Запит ЛИШЕ початку файла (Range + читання не більше nbytes). -> probe_bytes + status, contentType, size, error."""
    if not url.lower().startswith(("http://", "https://")):
        raise SatError("адреса має починатися з http:// або https://")
    req = urllib.request.Request(url, headers={"User-Agent": "OpenTYT-CPS/R35", "Range": "bytes=0-%d" % (nbytes - 1)})
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
        raise SatError("з'єднатися не вдалося: %s" % getattr(e, "reason", e))
    res = probe_bytes(raw)
    res.update(out)
    return res


def probe_text(res):
    lines = []
    if res.get("status") is not None:
        lines.append("Відповідь: код %s%s%s." % (res["status"], (", тип " + res["contentType"]) if res.get("contentType") else "",
                                                 (", розмір файла %s Б" % res["size"]) if res.get("size") else ""))
    lines.append("Початок файла (перші три рядки):\n" + res["head"])
    if res["ok"]:
        lines.append("Розбір ПІДХОДИТЬ: у початку %d повних наборів елементів." % res["sets"])
    else:
        lines.append("Розбір НЕ розпізнає цей початок: %s." % (res["why"] or "невідома причина"))
    return "\n".join(lines)


def download(url, dest, timeout=60):
    """Завантажити URL у файл dest (шлях обирає користувач). Повертає кількість байтів. Часткове завантаження під цим іменем не лишається."""
    if not url.lower().startswith(("http://", "https://")):
        raise SatError("адреса має починатися з http:// або https://")
    req = urllib.request.Request(url, headers={"User-Agent": "OpenTYT-CPS/R35"})
    tmp = dest + ".part"
    got = 0
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
        os.replace(tmp, dest)
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise SatError("завантаження не вдалося: %s" % e)
    return got

