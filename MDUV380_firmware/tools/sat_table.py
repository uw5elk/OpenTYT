# -*- coding: utf-8 -*-
"""R54: таблиця частот супутників (формат `satellites.txt` офіційного OpenGD77 CPS), автозаповнення слотів, перевірка частот і шлях APRS.

Формат файла -- той самий, що в офіційного CPS (реальний файл користувача від 2026-11-01 -- tools/testdata/satellites_user_2026-11-01.txt):

    Cat  #,Name    ,    Rx1,    Tx1, CTCSS, ArmCTCSS,    Rx2,    Tx2,    Rx3,    Tx3,APRS Config
    25544U,ISS     ,437.800,145.990,     67,       0,145.825,145.825,145.800,      0,RS0ISS

Поля через кому, стовпці вирівняні пробілами; частоти в МГц, субтони в Гц; «Cat #» = номер NORAD + літера U; ім'я до 8 символів; Rx -- те, що слухає
рація (downlink супутника), Tx -- те, що вона передає (uplink). Набори: 1 -- голос (FM), 2 -- APRS, 3 -- «CW Rx» (маяк, лише прийом). Tx1 = 0 НЕ означає
«передачі нема»: набір 2 перевіряється окремо.

СУБТОНИ (R55): стовпці CTCSS і ArmCTCSS -- субтон ПЕРЕДАЧІ голосового набору (CTCSS) і «взводний» субтон передачі (ArmCTCSS, SK2 + PTT). Приймання завжди без субтону:
прошивка ставить rxTone = NONE при кожному вході на екран супутників (menuSatelliteScreen.c); у наборів APRS і маяк субтону передачі нема (satellite.c: обидва = 0).

ЗВ'ЯЗОК З ПРОШИВКОЮ (усе -- з коду, не з брифу):
  * одиниці слота: частоти в Гц (menuSatelliteScreen.c, calculateActiveSatelliteData: rxFreq / 10 -> одиниці 10 Гц каналу), субтон у 0,1 Гц, ім'я 8 Б;
  * «APRS Config» -> 24 Б AdditionalData слота: [0..5] ім'я 1, [6] '0'+SSID, [7..12] ім'я 2, [13] '0'+SSID (aprs.c, aprsBeaconingPrepareSatelliteConfig:
    memcpy 6 Б імені й SSID = байт - '0'; порожня перша буква -- шляху нема; друге ім'я порожнє -- шлях з одного елемента). SSID у ефір іде як (SSID + '0') << 1
    (aprs.c, збирання заголовка AX.25), тож коректні лише 0..9. Припущення: рядок «RS0ISS» у файлі офіційного CPS означає ім'я RS0ISS з SSID 0 -- це ГІПОТЕЗА
    (як сам офіційний CPS пише SSID, невідомо), на залізі НЕ ПЕРЕВІРЕНО (TESTING.md, DC3);
  * смуги рації й межі передачі за замовчуванням -- з trx.c (RADIO_HARDWARE_FREQUENCY_BANDS, DEFAULT_USER_FREQUENCY_BANDS), звіряються тестом test_r54.py.

Дані JE9PEL і SatNOGS у репозиторій НЕ вбудовуються (claude/satellite-sources.md). Модуль без Tk і без рації."""
import os
import re

import sat_tle as st

TABLE_FILE = "satellites.txt"
STARTER_VERIFIED_DATE = "2026-11-01"       # R55: коли стартову таблицю звірено з документацією (claude/satellite-sources.md); пишеться в sat_table_data.VERIFIED_DATE
TABLE_RECHECK_DAYS = 90                    # R55: після цього строку CPS нагадує звірити частоти з AMSAT «FM Satellites»
AMSAT_FM_URL = "https://www.amsat.org/live-fm-satellites/"

# Смуги приймання рації, Гц (trx.c, RADIO_HARDWARE_FREQUENCY_BANDS: .minFreq/.maxFreq в одиницях 10 Гц -> ×10): VHF, 220 МГц, UHF.
HW_BANDS_HZ = ((127_000_000, 178_000_000), (190_000_000, 282_000_000), (380_000_000, 564_000_000))
# Межі передачі за замовчуванням, Гц (trx.c, DEFAULT_USER_FREQUENCY_BANDS; settings.c: txFreqLimited = BAND_LIMITS_ON_LEGACY_DEFAULT): VHF, 220 МГц, UHF.
TX_BANDS_HZ = ((144_000_000, 148_000_000), (222_000_000, 225_000_000), (420_000_000, 450_000_000))

SET_NAMES = (("голос", "RX1", "TX1"), ("APRS", "RX2", "TX2"), ("маяк", "RX3", "TX3"))
MAX_MHZ = 4000.0
MAX_TONE_HZ = 300.0


# ---------------------------------------------------------------------------------------------------------------------------------
#  Шлях APRS (AdditionalData)
# ---------------------------------------------------------------------------------------------------------------------------------

_APRS_TOKEN = re.compile(r"^([A-Za-z0-9]{1,6})(?:-([0-9]))?$")


def parse_aprs_text(text):
    """«RS0ISS», «RS0ISS-1», «WIDE1-1 RS0ISS» (до двох елементів; роздільники: пробіл, кома, «;», «/») -> [(ІМ'Я, SSID)]. SatError -- пояснення словами."""
    toks = [t for t in re.split(r"[\s,;/]+", (text or "").strip()) if t]
    if len(toks) > 2:
        raise st.SatError("шлях APRS: не більше двох елементів (у слоті їх два)")
    out = []
    for t in toks:
        m = _APRS_TOKEN.match(t)
        if not m:
            raise st.SatError("шлях APRS: «%s» -- очікується позивний до 6 символів і необов'язковий «-N», N від 0 до 9 (SSID у ефір іде цифрою)" % t)
        out.append((m.group(1).upper(), int(m.group(2) or 0)))
    return out


def aprs_to_text(path):
    return " ".join(n if s == 0 else "%s-%d" % (n, s) for n, s in path)


def encode_aprs(text, old=b""):
    """-> 24 байти AdditionalData. Хвіст [14..23] береться зі старого значення (прошивка його не читає, але стирати чуже не треба)."""
    path = parse_aprs_text(text)
    base = bytearray(bytes(old).ljust(st.ADDITIONAL_LEN, b"\x00")[:st.ADDITIONAL_LEN])
    base[0:14] = b"\x00" * 14
    for k, (name, ssid) in enumerate(path):
        nb = name.encode("ascii")
        base[7 * k:7 * k + len(nb)] = nb
        base[7 * k + 6] = ord("0") + ssid
    return bytes(base)


def decode_aprs(extra):
    """24 байти AdditionalData -> текст шляху ('' якщо шляху нема). Нечитний SSID показується як «-?»."""
    b = bytes(extra).ljust(st.ADDITIONAL_LEN, b"\x00")
    if b[0] == 0:
        return ""
    parts = []
    for k in range(2):
        raw = b[7 * k:7 * k + 6]
        name = raw.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
        if not name:
            break
        s = b[7 * k + 6]
        if ord("0") <= s <= ord("9"):
            ssid = s - ord("0")
            parts.append(name if ssid == 0 else "%s-%d" % (name, ssid))
        else:
            parts.append(name + "-?")
    return " ".join(parts)


# ---------------------------------------------------------------------------------------------------------------------------------
#  Таблиця
# ---------------------------------------------------------------------------------------------------------------------------------

class Row:
    """Один рядок таблиці. Частоти в Гц, субтони в 0,1 Гц (як у слоті)."""

    def __init__(self, norad, name, rx1=0, tx1=0, ctcss=0, arm=0, rx2=0, tx2=0, rx3=0, tx3=0, aprs="", line=0):
        self.norad = norad
        self.name = name
        self.rx1, self.tx1, self.ctcss, self.arm = rx1, tx1, ctcss, arm
        self.rx2, self.tx2, self.rx3, self.tx3 = rx2, tx2, rx3, tx3
        self.aprs = aprs
        self.line = line

    def freqs(self):
        return (self.rx1, self.tx1, self.rx2, self.tx2, self.rx3, self.tx3)

    def __repr__(self):
        return "Row(%s, %r, rx1=%d tx1=%d)" % (self.norad, self.name, self.rx1, self.tx1)


def _mhz(field, what):
    t = field.strip()
    if not t:
        return 0
    try:
        v = float(t)
    except ValueError:
        raise st.SatError("%s «%s» не число (МГц)" % (what, t))
    if not (0 <= v <= MAX_MHZ):
        raise st.SatError("%s %s МГц поза розумними межами" % (what, t))
    return int(round(v * 1e6))


def _tone(field, what):
    t = field.strip()
    if not t:
        return 0
    try:
        v = float(t)
    except ValueError:
        raise st.SatError("%s «%s» не число (Гц)" % (what, t))
    if not (0 <= v <= MAX_TONE_HZ):
        raise st.SatError("%s %s Гц поза межами" % (what, t))
    return int(round(v * 10))


_CAT = re.compile(r"^(\d{1,9})\s*[uU]?$")


def norad_of(tle):
    """NORAD набору TLE (число) або None (напр., літерний номер формату Alpha-5)."""
    c = (tle.catalog or "").strip()
    return int(c) if c.isdigit() else None


def parse_table(text):
    """Текст `satellites.txt` -> (рядки Row, повідомлення). Стійкий до пробілів, порожніх рядків, регістру «U», дробових субтонів; некоректний рядок
    пропускається з повідомленням, решта читається."""
    if isinstance(text, (bytes, bytearray)):
        try:
            text = bytes(text).decode("utf-8-sig")
        except UnicodeDecodeError:
            text = bytes(text).decode("cp1251", errors="replace")
    text = text.replace("﻿", "")
    rows, notes, seen = [], [], {}
    for n, raw in enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"), 1):
        if not raw.strip():
            continue
        f = [x.strip() for x in raw.split(",")]
        m = _CAT.match(f[0])
        if not m:
            if not rows and not notes and f[0].lower().startswith("cat"):
                continue            # рядок заголовка
            notes.append("рядок %d: перше поле «%s» не схоже на номер NORAD -- пропущено" % (n, f[0][:20]))
            continue
        if len(f) < 10:
            notes.append("рядок %d (%s): полів %d, потрібно щонайменше 10 -- пропущено" % (n, f[0], len(f)))
            continue
        name = f[1]
        if not name or len(name) > st.NAME_LEN or any(not (0x20 <= ord(c) < 0x7F) for c in name):
            notes.append("рядок %d (%s): ім'я «%s» має бути від 1 до %d символів ASCII -- пропущено" % (n, f[0], name[:20], st.NAME_LEN))
            continue
        try:
            rx1, tx1 = _mhz(f[2], "Rx1"), _mhz(f[3], "Tx1")
            ctcss, arm = _tone(f[4], "CTCSS"), _tone(f[5], "ArmCTCSS")
            rx2, tx2, rx3, tx3 = _mhz(f[6], "Rx2"), _mhz(f[7], "Tx2"), _mhz(f[8], "Rx3"), _mhz(f[9], "Tx3")
        except st.SatError as e:
            notes.append("рядок %d (%s %s): %s -- пропущено" % (n, f[0], name, e))
            continue
        aprs = ",".join(f[10:]).strip()
        if aprs:
            try:
                aprs = aprs_to_text(parse_aprs_text(aprs))
            except st.SatError as e:
                notes.append("рядок %d (%s %s): %s -- шлях APRS проігноровано, решту рядка прочитано" % (n, f[0], name, e))
                aprs = ""
        norad = int(m.group(1))
        if norad in seen:
            notes.append("рядок %d (%s): номер NORAD уже був у рядку %d -- пропущено" % (n, name, seen[norad]))
            continue
        seen[norad] = n
        rows.append(Row(norad, name, rx1, tx1, ctcss, arm, rx2, tx2, rx3, tx3, aprs, n))
    return rows, notes


def read_table_file(path):
    with open(path, "rb") as fh:
        return parse_table(fh.read())


def by_norad(rows):
    return {r.norad: r for r in rows}


def by_name(rows):
    """{нормалізована назва: [Row]} -- для слотів, прочитаних з рації (NORAD у слоті нема)."""
    d = {}
    for r in rows:
        d.setdefault(st.norm_name(r.name), []).append(r)
    return d


def default_rows():
    """Вбудована стартова таблиця (sat_table_data.py згенеровано з tools/satellites.txt -- PyInstaller вбудовує імпортований модуль, а файл-довідник у .exe не потрапив би)."""
    import sat_table_data
    return parse_table("\n".join(sat_table_data.LINES) + "\n")


# ---------------------------------------------------------------------------------------------------------------------------------
#  Слоти
# ---------------------------------------------------------------------------------------------------------------------------------

def slot_has_freqs(slot):
    return any((slot.rx1, slot.tx1, slot.rx2, slot.tx2, slot.rx3, slot.tx3))


def slot_is_blank(slot):
    """Слот без жодних введених вручну даних про частоти: усі частоти, субтони й шлях APRS нульові."""
    return not slot_has_freqs(slot) and not slot.ctcss and not slot.arm and not any(bytes(slot.extra))


def fill_slot(slot, row):
    """Записати в слот частоти, субтони й шлях APRS з рядка таблиці (назву не чіпає)."""
    slot.rx1, slot.tx1, slot.ctcss, slot.arm = row.rx1, row.tx1, row.ctcss, row.arm
    slot.rx2, slot.tx2, slot.rx3, slot.tx3 = row.rx2, row.tx2, row.rx3, row.tx3
    slot.extra = encode_aprs(row.aprs, slot.extra) if row.aprs else bytes(slot.extra)
    return slot


def merge_add_table(slots, tles, table, replace=False):
    """Як sat_tle.merge_add, але за NORAD набору підставляє з таблиці (dict NORAD -> Row) назву й частоти. Немає запису -- слот з нулями й назвою з Celestrak.
    -> (новий список, скільки не влізло)."""
    base = [] if replace else [s.copy() for s in slots]
    dropped = 0
    for t in tles:
        if not t.ok:
            continue
        if len(base) >= st.NUM_SLOTS:
            dropped += 1
            continue
        row = table.get(norad_of(t)) if table else None
        s = st.Slot.from_tle(t, name=row.name if row else None)
        if row:
            fill_slot(s, row)
        base.append(s)
    return base, dropped


class AddReport:
    def __init__(self):
        self.added = []        # імена доданих
        self.missing = []      # [(ім'я, NORAD)] немає TLE
        self.exists = []       # імена, що вже є в слотах
        self.dropped = []      # імена, що не влізли


def add_from_table(slots, rows, tles):
    """«Додати з таблиці»: для кожного рядка за порядком файла бере TLE за NORAD із завантажених (кілька наборів одного номера -- найсвіжіша епоха).
    Рядок без TLE перелічується в звіті (це не помилка). Слот з тією ж назвою вже є -- не дублюється. Понад 25 не додається.
    -> (новий список, AddReport)."""
    best = {}
    for t in tles:
        if not t.ok:
            continue
        k = norad_of(t)
        if k is None:
            continue
        cur = best.get(k)
        if cur is None or (t.epoch is not None and (cur.epoch is None or t.epoch > cur.epoch)):
            best[k] = t
    out = [s.copy() for s in slots]
    have = {st.norm_name(s.name) for s in out}
    rep = AddReport()
    for r in rows:
        t = best.get(r.norad)
        if t is None:
            rep.missing.append((r.name, r.norad))
            continue
        if st.norm_name(r.name) in have:
            rep.exists.append(r.name)
            continue
        if len(out) >= st.NUM_SLOTS:
            rep.dropped.append(r.name)
            continue
        s = st.Slot.from_tle(t, name=r.name)
        fill_slot(s, r)
        out.append(s)
        have.add(st.norm_name(r.name))
        rep.added.append(r.name)
    return out, rep


def report_text(rep, rows_count):
    lines = ["Рядків у таблиці: %d. Додано в слоти: %d%s." % (rows_count, len(rep.added), (" (" + ", ".join(rep.added) + ")") if rep.added else "")]
    if rep.exists:
        lines.append("Уже є в слотах (за назвою), не дублюю: %s." % ", ".join(rep.exists))
    if rep.missing:
        lines.append("Немає TLE: %s. Це не помилка (напр., супутник зійшов з орбіти або його нема у вибраному файлі TLE)." % ", ".join("%s (%d)" % (n, k) for n, k in rep.missing))
    if rep.dropped:
        lines.append("Не влізло (слотів лише %d): %s." % (st.NUM_SLOTS, ", ".join(rep.dropped)))
    return "\n".join(lines)


def fill_existing(slots, rows):
    """«Заповнити порожні слоти з таблиці»: слоти, прочитані з рації (NORAD там нема), зіставляються з рядками ЗА НАЗВОЮ. Слот, де вже щось введено
    (частоти, субтони чи шлях), не змінюється. -> (новий список, filled [імена], manual [імена], nomatch [імена], ambiguous [імена])."""
    names = by_name(rows)
    out = [s.copy() for s in slots]
    filled, manual, nomatch, ambiguous = [], [], [], []
    for s in out:
        if not slot_is_blank(s):
            manual.append(s.name)
            continue
        hits = names.get(st.norm_name(s.name), [])
        if not hits:
            nomatch.append(s.name)
        elif len(hits) > 1:
            ambiguous.append(s.name)
        else:
            fill_slot(s, hits[0])
            filled.append(s.name)
    return out, filled, manual, nomatch, ambiguous


# ---------------------------------------------------------------------------------------------------------------------------------
#  Перевірка частот перед записом в рацію
# ---------------------------------------------------------------------------------------------------------------------------------

def in_bands(hz, bands):
    return any(lo <= hz <= hi for lo, hi in bands)


def _bands_text(bands):
    return ", ".join("%g-%g" % (lo / 1e6, hi / 1e6) for lo, hi in bands) + " МГц"


def check_slot(slot):
    """-> [(рівень, текст)]; рівні: 'error' (запис у рацію неможливий), 'warn', 'nofreq' («слот без частот»). Кожен набір -- окремо."""
    out = []
    if not slot_has_freqs(slot):
        out.append(("nofreq", "слот без частот: екран супутників не покаже частот, а передача буде заблокована"))
        return out
    vals = (slot.rx1, slot.tx1, slot.rx2, slot.tx2, slot.rx3, slot.tx3)
    for k, (setname, rxl, txl) in enumerate(SET_NAMES):
        for j, label in ((0, rxl), (1, txl)):
            hz = vals[2 * k + j]
            if not hz:
                continue
            if not in_bands(hz, HW_BANDS_HZ):
                out.append(("error", "%s (%s) %.6g МГц поза смугами рації (%s)" % (label, setname, hz / 1e6, _bands_text(HW_BANDS_HZ))))
            elif j == 1 and not in_bands(hz, TX_BANDS_HZ):
                out.append(("warn", "%s (%s) %.6g МГц поза межами передачі за замовчуванням (%s): за стандартних обмежень передачі в рації вона не передаватиме" % (
                    label, setname, hz / 1e6, _bands_text(TX_BANDS_HZ))))
    return out


def validate_slots(slots):
    """-> (errors, warns, nofreq): списки рядків «слот N «ім'я»: ...»."""
    errors, warns, nofreq = [], [], []
    for i, s in enumerate(slots):
        for lvl, txt in check_slot(s):
            line = "слот %d «%s»: %s" % (i + 1, s.name, txt)
            {"error": errors, "warn": warns, "nofreq": nofreq}[lvl].append(line)
    return errors, warns, nofreq


# ---------------------------------------------------------------------------------------------------------------------------------
#  Генерація вбудованого модуля
# ---------------------------------------------------------------------------------------------------------------------------------

def here(*parts):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), *parts)


def generate_data_module(src=None, dst=None, verified=STARTER_VERIFIED_DATE):
    """tools/satellites.txt -> tools/sat_table_data.py (запускати після зміни стартової таблиці: python3 MDUV380_firmware/tools/sat_table.py). verified -- дата звірки
    таблиці (R55), потрапляє в VERIFIED_DATE."""
    src = src or here(TABLE_FILE)
    dst = dst or here("sat_table_data.py")
    with open(src, "rb") as f:
        lines = f.read().decode("ascii").replace("\r\n", "\n").rstrip("\n").split("\n")
    body = "".join("    %r,\n" % ln for ln in lines)
    text = ('# -*- coding: utf-8 -*-\n'
            '"""ЗГЕНЕРОВАНО tools/sat_table.py з tools/satellites.txt -- НЕ РЕДАГУВАТИ РУКАМИ (правити satellites.txt і перегенерувати: '
            'python3 MDUV380_firmware/tools/sat_table.py). Вбудована стартова таблиця частот супутників: PyInstaller вбудовує імпортований модуль, '
            'а файл-довідник у .exe не потрапив би (так само, як aprs_icons_data.py)."""\n'
            'VERIFIED_DATE = %r          # коли таблицю звірено з документацією (sat_table.STARTER_VERIFIED_DATE)\n' % verified +
            'LINES = (\n' + body + ')\n')
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return dst


# ---------------------------------------------------------------------------------------------------------------------------------
#  Дата перевірки таблиці (R55)
# ---------------------------------------------------------------------------------------------------------------------------------

def builtin_verified_date():
    """datetime.date звірки вбудованої таблиці (sat_table_data.VERIFIED_DATE) або None."""
    import datetime
    import sat_table_data
    try:
        return datetime.date.fromisoformat(sat_table_data.VERIFIED_DATE)
    except (AttributeError, ValueError):
        return None


def file_date(path):
    """Дата зміни файла таблиці (datetime.date) або None."""
    import datetime
    try:
        return datetime.date.fromtimestamp(os.path.getmtime(path))
    except OSError:
        return None


def table_age_days(verified, today=None):
    """Скільки діб минуло від дати звірки (ціле, не менше 0); None -- дата невідома. today -- параметр для тестів."""
    import datetime
    if verified is None:
        return None
    today = today or datetime.date.today()
    return max(0, (today - verified).days)


def table_date_text(kind, verified, today=None):
    """«вбудована, перевірена 2026-11-01 (3 діб тому)» / «файл, змінено 2026-10-01 (31 діб тому)» / «дата перевірки невідома»."""
    n = table_age_days(verified, today)
    if n is None:
        return "%s, дата перевірки невідома" % kind
    word = "перевірена" if kind.startswith("вбудована") else "змінено"
    return "%s, %s %s (%d діб тому)" % (kind, word, verified.isoformat(), n)


def table_recheck_text(verified, today=None):
    """Жовте нагадування, коли від звірки минуло більше TABLE_RECHECK_DAYS діб; інакше ''."""
    n = table_age_days(verified, today)
    if n is None or n <= TABLE_RECHECK_DAYS:
        return ""
    return ("Таблицю частот звіряли %d діб тому (понад %d). Частоти й стан супутників змінюються: звір їх з AMSAT «FM Satellites» (%s)." % (
        n, TABLE_RECHECK_DAYS, AMSAT_FM_URL))


if __name__ == "__main__":
    print(generate_data_module())
