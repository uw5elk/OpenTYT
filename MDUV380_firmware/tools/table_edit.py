# -*- coding: utf-8 -*-
"""table_edit.py -- CPS-fix2 / етап 3: правка списків прийому (TG-списків), зон і каналів ДОКУМЕНТА кодплага. ЛОГІКА без Tk і без рації.

ОДНА перевірка на все (T0.2). Окремого набору правил для редакторів нема: редактор бере ТІ САМІ рядки, що йдуть в експорт CSV
(cps_csv.export_rows), змінює потрібну клітинку/рядок і проганяє таблицю через cps_csv.import_csv -- тобто через ті самі межі, ті самі
посилання за назвами, те саме кодування назв (GB2312 -> GBK; «і ї є ґ» -> cp1251 з попередженням), ту саму перевірку висячих посилань і
те саме правило слотів («нові беруть слоти, що ніколи не були зайняті; звільнений -- лише коли інших нема», R26). Результат --
cps_csv.ImportResult з НОВИМ образом: документ або приймає його цілком (Document.apply), або (помилка TableEditError) лишається як був.

Єдине доповнення до CSV-імпорту -- посилання «#N» (за номером запису) для випадку, коли назви в кодплазі повторюються (звичайна річ для
каналів): воно вмикається лише для сеансу редактора (cps_csv.Session(numeric_refs=True)); для CSV-ФАЙЛІВ формат не змінено.

Ідентифікатори записів: TG-список -- слот (0-based, як у Image.groups()), зона -- біт (як у Image.zones()), канал -- номер (1-based),
контакт -- слот (0-based). Номер у посиланнях = слот + 1 (канал -- сам номер).
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cps_link as cl  # noqa: E402
import cps_csv as cc  # noqa: E402
import codeplug_view as cv  # noqa: E402
import contact_edit as ce  # noqa: E402

TG_MAX = cv.RXGROUP_MAX_CONTACTS        # 32
NAME_LEN = 16
KIND_TITLES = {"contact": "Контакти", "tg": "TG-списки", "zone": "Зони", "channel": "Канали", "dtmf": "DTMF-контакти"}
KIND_LABELS = {"contact": "контакт", "tg": "список прийому", "zone": "зона", "channel": "канал", "dtmf": "DTMF-контакт", "aprs": "APRS-слот"}


class TableEditError(cl.CpsError):
    """Правку відхилено ДО будь-якої зміни: problems -- усі знайдені проблеми."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("Правку відхилено, документ не змінено.\n" + "\n".join("  - " + p for p in self.problems))


# ---------------------------------------------------------------------------------------------------------------------------------
#  Каркас: рядки -> import_csv
# ---------------------------------------------------------------------------------------------------------------------------------

def _session():
    return cc.Session(numeric_refs=True)


def tables_of(img, dp):
    """{ключ: (заголовок, [рядки])} -- рядки можна міняти безпечно (це копії)."""
    return {k: (list(h), [list(r) for r in rows]) for k, (h, rows) in cc.export_rows(img, dp).items()}


_CSV_PREFIX = re.compile(r"^\S+\.csv(, рядок \d+)?: ")
_CSV_WARN_PREFIX = re.compile(r"^\S+\.csv, рядок \d+, ")


def _run(img, edits, dp):
    tabs = {k: cc.Table(cc.FILE_NAMES[k], list(h), [(i + 2, list(r)) for i, r in enumerate(rows)]) for k, (h, rows) in edits.items()}
    try:
        return cc.import_csv(img, tabs, dp, _session())
    except cc.CsvImportRefused as e:
        raise TableEditError([_CSV_PREFIX.sub("", p) for p in e.problems])


def _names(img):
    """Сумісні назви за номерами: {вид: {номер: compat}} для посилань."""
    return {"contact": {s + 1: cc.compat_text(r[:16]) for s, r in img.contacts()},
            "group": {s + 1: cc.compat_text(r[:16]) for s, r, _l in img.groups()},
            "aprs": {s + 1: cc.compat_text(r[:8]) for s, r in img.aprs()},
            "channel": {n: cc.compat_text(r[:16]) for n, r in img.channels()}}


class _Tokens:
    """Текст посилання на запис: його сумісна назва, а коли така назва не єдина (або схожа на службову «None») -- «#N»."""

    def __init__(self, img):
        self.names = _names(img)
        self.counts = {k: {} for k in self.names}
        for k, d in self.names.items():
            for v in d.values():
                self.counts[k][v] = self.counts[k].get(v, 0) + 1

    def __call__(self, kind, n):
        c = self.names[kind].get(n)
        if c is None or not c.strip() or c.strip().casefold() == "none" or self.counts[kind][c] != 1:
            return "#%d" % n
        return c


def name_problem(img, kind, name, exclude=None):
    """Текст проблеми з назвою нового/зміненого запису або None. Кодування й довжина -- ті самі правила, що в імпорті (contact_edit.check_name
    викликає cps_csv.encode_new_name); тут додано лише унікальність назви серед записів того ж виду (посилання йдуть за назвами)."""
    name = name if name is not None else ""
    if not name.strip():
        return "назва порожня"
    chk = ce.check_name(name, first_ff_empty=(kind in ("contact", "dtmf")))
    if not chk["ok"]:
        return chk["message"]
    for ident, nm in entity_names(img, kind):
        if ident != exclude and nm == name:
            return "«%s» уже є (назви мають бути різні, бо посилання йдуть за назвами)" % name
    return None


def entity_names(img, kind):
    if kind == "tg":
        return [(s, cc.readable_text(r[:16])) for s, r, _l in img.groups()]
    if kind == "zone":
        return [(b, cc.readable_text(r[:16])) for b, r in img.zones()]
    if kind == "channel":
        return [(n, cc.readable_text(r[:16])) for n, r in img.channels()]
    if kind == "contact":
        return [(s, cc.readable_text(r[:16])) for s, r in img.contacts()]
    if kind == "dtmf":
        return [(s, cc.readable_text(r[:16])) for s, r in img.dtmf()]
    raise ValueError(kind)


# ---------------------------------------------------------------------------------------------------------------------------------
#  Перелік записів для вікон
# ---------------------------------------------------------------------------------------------------------------------------------

def _members(rec, count):
    out = []
    for k in range(count):
        v = rec[16 + 2 * k] | (rec[17 + 2 * k] << 8)
        if v == 0:
            break
        out.append(v)
    return out


def tg_lists(img):
    """[(слот, назва, [номери контактів])]."""
    return [(s, cc.readable_text(r[:16]), _members(r, ln)) for s, r, ln in img.groups()]


def zones(img):
    """[(біт, назва, [номери каналів])]."""
    n = img.zone_format()
    return [(b, cc.readable_text(r[:16]), _members(r, n)) for b, r in img.zones()]


def zone_limit(img):
    return img.zone_format()


def dtmf_contacts(img):
    """[(слот, назва, код)] DTMF-контактів у порядку кодплага (код -- у тому ж записі, що й у DTMF.csv)."""
    return [(s, cc.readable_text(r[:16]), cc.dtmf_code_text(r[16:32])) for s, r in img.dtmf()]


def codeplug_counts(img):
    """[(підпис, кількість)] записів кодплага, які бачить рація (для підсумку в «Основній інформації»)."""
    return [("контактів", len(list(img.contacts()))), ("списків прийому", len(list(img.groups()))), ("зон", len(list(img.zones()))),
            ("каналів", len(list(img.channels()))), ("APRS-слотів", len(list(img.aprs()))), ("DTMF-контактів", len(list(img.dtmf())))]


def contacts(img):
    """[(номер, назва, ID, тип)]: усе, що треба для переліку «доступних» контактів."""
    return [(s + 1, cc.readable_text(r[:16]), cv.bcd_to_int(r[16:20]), cc.CALL_TYPE_NAMES.get(r[20], "Group")) for s, r in img.contacts()]


def channels(img, dp):
    """[(номер, назва, тип, RX)] для переліку каналів."""
    ctx = cc.make_ctx_for_export(img, dp)
    out = []
    for n, r in img.channels():
        out.append((n, cc.readable_text(r[:16]), cc.CH_COLUMN_BY_NAME["Channel Type"]["dec"](r, ctx),
                    cc.CH_COLUMN_BY_NAME["Rx Frequency"]["dec"](r, ctx).strip("\t").strip()))
    return out


# ---------------------------------------------------------------------------------------------------------------------------------
#  Посилання (T0.3)
# ---------------------------------------------------------------------------------------------------------------------------------

class Refs:
    """Хто посилається на запис. items -- [(розділ, текст)] для показу; also_removed -- записи, які зникнуть разом (порожні зона/список)."""

    def __init__(self):
        self.items = []
        self.also_removed = []

    def __bool__(self):
        return bool(self.items)

    def text(self, limit=12):
        lines = ["  [%s] %s" % x for x in self.items[:limit]]
        if len(self.items) > limit:
            lines.append("  ... і ще %d" % (len(self.items) - limit))
        for sec, t in self.also_removed:
            lines.append("  ПЕРЕСТАНЕ ІСНУВАТИ: [%s] %s (без елементів рація такі не використовує)" % (sec, t))
        return "\n".join(lines)


def references(img, kind, ident):
    """Усі, хто посилається на запис (kind: contact / tg / aprs / channel; ident -- як вище, для aprs -- 0-based слот). Для зони посилань нема."""
    r = Refs()
    if kind == "contact":
        n = ident + 1
        for _s, name, mem in tg_lists(img):
            if n in mem:
                r.items.append(("TG-списки", "«%s» містить цей контакт" % name))
                if mem == [n]:
                    r.also_removed.append(("TG-списки", name))
        for num, rec in img.channels():
            if (rec[cc.O_CONTACT] | (rec[cc.O_CONTACT + 1] << 8)) == n and rec[cc.O_MODE] != 0:
                r.items.append(("Канали", "№%d «%s» (поле «Контакт»)" % (num, cc.readable_text(rec[:16]))))
    elif kind == "tg":
        n = ident + 1
        for num, rec in img.channels():
            if rec[cc.O_GROUP] == n and rec[cc.O_MODE] != 0:
                r.items.append(("Канали", "№%d «%s» (поле «Список прийому»)" % (num, cc.readable_text(rec[:16]))))
    elif kind == "aprs":
        n = ident + 1
        for num, rec in img.channels():
            if rec[cc.O_APRS] == n:          # колонка APRS актуальна і для аналогових, і для цифрових каналів (на відміну від контакту/списку прийому)
                r.items.append(("Канали", "№%d «%s» (поле «APRS»)" % (num, cc.readable_text(rec[:16]))))
    elif kind == "channel":
        for _b, name, mem in zones(img):
            if ident in mem:
                r.items.append(("Зони", "«%s» містить цей канал" % name))
                if mem == [ident]:
                    r.also_removed.append(("Зони", name))
    return r


# ---------------------------------------------------------------------------------------------------------------------------------
#  Спільні операції над рядками
# ---------------------------------------------------------------------------------------------------------------------------------

def _ids(img, kind):
    return [i for i, _n in entity_names(img, kind)]


def _member_row(row, tokens, width):
    """Рядок TG-списку/зони з новим складом: [compat] + токени + порожні + [readable]."""
    return [row[0]] + list(tokens) + [""] * (width - len(tokens)) + [row[-1]]


def _check_members(kind, label, numbers, limit, valid, what):
    problems = []
    if not numbers:
        problems.append("%s не може бути порожнім: рація таких не використовує. Щоб прибрати його, скористайтеся «Видалити»." % label)
    if len(numbers) > limit:
        problems.append("%s: не більше %d %s (зараз %d) -- такий ліміт кодплага" % (label, limit, what, len(numbers)))
    if len(set(numbers)) != len(numbers):
        problems.append("%s: той самий запис двічі" % label)
    bad = [n for n in numbers if n not in valid]
    if bad:
        problems.append("%s: нема записів з номерами %s" % (label, ", ".join(str(b) for b in bad[:6])))
    if problems:
        raise TableEditError(problems)


_CFG = {
    "tg": {"key": "tg_lists", "width": TG_MAX, "ref_kind": "contact", "label": "список прийому", "what": "контактів"},
    "zone": {"key": "zones", "width": 80, "ref_kind": "channel", "label": "зона", "what": "каналів"},
}


def _limit(img, kind):
    return TG_MAX if kind == "tg" else img.zone_format()


def _valid(img, kind):
    return set(s + 1 for s, _r in img.contacts()) if kind == "tg" else set(n for n, _r in img.channels())


def _row_of(img, kind, ident):
    ids = _ids(img, kind)
    if ident not in ids:
        raise TableEditError(["%s №%s не знайдено в документі" % (KIND_LABELS[kind], ident)])
    return ids.index(ident)


def set_members(img, kind, ident, numbers, dp):
    """Новий склад (і порядок) списку прийому / зони. numbers -- номери контактів / каналів."""
    cfg = _CFG[kind]
    numbers = list(numbers)
    _check_members(kind, cfg["label"], numbers, _limit(img, kind), _valid(img, kind), cfg["what"])
    hdr, rows = tables_of(img, dp)[cfg["key"]]
    i = _row_of(img, kind, ident)
    tok = _Tokens(img)
    rows[i] = _member_row(rows[i], [tok(cfg["ref_kind"], n) for n in numbers], cfg["width"])
    return _run(img, {cfg["key"]: (hdr, rows)}, dp)


def add_entity(img, kind, name, numbers, dp):
    """Новий список прийому / зона з назвою і складом."""
    cfg = _CFG[kind]
    numbers = list(numbers)
    _check_members(kind, cfg["label"], numbers, _limit(img, kind), _valid(img, kind), cfg["what"])
    prob = name_problem(img, kind, name)
    if prob:
        raise TableEditError(["назва: " + prob])
    hdr, rows = tables_of(img, dp)[cfg["key"]]
    tok = _Tokens(img)
    rows.append(_member_row(["", ""], [tok(cfg["ref_kind"], n) for n in numbers], cfg["width"])[:-1] + [name])
    return _run(img, {cfg["key"]: (hdr, rows)}, dp)


def rename_entity(img, kind, ident, name, dp):
    cfg = _CFG.get(kind) or ({"key": "contacts"} if kind == "contact" else None)
    prob = name_problem(img, kind, name, exclude=ident)
    if prob:
        raise TableEditError(["назва: " + prob])
    if kind == "channel":
        return channel_edit(img, ident, {"Channel Name": name}, dp)
    if kind == "dtmf":
        hdr, rows = tables_of(img, dp)["dtmf"]
        rows[_row_of(img, "dtmf", ident)][-1] = name
        return _run(img, {"dtmf": (hdr, rows)}, dp)
    hdr, rows = tables_of(img, dp)[cfg["key"]]
    i = _row_of(img, kind, ident)
    rows[i][-1] = name
    return _run(img, {cfg["key"]: (hdr, rows)}, dp)


def unique_copy_name(img, kind, name):
    """Назва для копії: «Назва 2», «Назва 3»... (кінець назви скорочується, щоб влізти в 16 байтів; назва має бути унікальною)."""
    for k in range(2, 100):
        suffix = " %d" % k
        base = name
        while base:
            cand = base + suffix
            if ce.check_name(cand)["ok"]:
                if name_problem(img, kind, cand) is None:
                    return cand
                break
            base = base[:-1]
    raise TableEditError(["не вдалося підібрати назву для копії «%s»" % name])


def duplicate_entity(img, kind, ident, dp, name=None):
    """Копія запису з новою назвою (за замовчуванням «Назва 2»). Повертає ImportResult."""
    if name is None:
        name = unique_copy_name(img, kind, dict(entity_names(img, kind))[ident])
    if kind == "channel":
        return channel_duplicate(img, ident, name, dp)
    if kind == "dtmf":
        return dtmf_add(img, name, dict((s, c) for s, _n, c in dtmf_contacts(img))[ident], dp)
    if kind == "contact":
        return contact_duplicate(img, ident, name, dp)
    members = dict((i, m) for i, _n, m in (tg_lists(img) if kind == "tg" else zones(img)))
    return add_entity(img, kind, name, members[ident], dp)


# ---------------------------------------------------------------------------------------------------------------------------------
#  Видалення (з перевіркою посилань)
# ---------------------------------------------------------------------------------------------------------------------------------

def _set_cell(hdr, row, col, text):
    row[hdr.index(col)] = text


def aprs_delete_problem(img, slot):
    """Чому слот (0-based) не можна видалити, або None. Прошивка читає APRS-слоти підряд з №1 до першого порожнього (codeplugAPRSInitCache), тому
    видалити можна лише ОСТАННІЙ -- інакше наступні слоти зникли б для рації (те саме правило в імпорті CSV і в codeplug_edit.delete_aprs_slot)."""
    slots = [s for s, _r in img.aprs()]
    if slot not in slots:
        return "APRS-слот №%d порожній або не бачиться рацією" % (slot + 1)
    if slot != len(slots) - 1:
        return ("видалення APRS-слота з середини (№%d з %d) не підтримується: рація читає слоти підряд з №1 до першого порожнього, "
                "решта зникла б. Видаліть останній або змініть цей слот." % (slot + 1, len(slots)))
    return None


def delete_entity(img, kind, ident, dp, cascade=False):
    """Видалити запис. Є посилання і cascade=False -- TableEditError з переліком (нічого не змінено); cascade=True -- посилання
    прибираються тим самим імпортом (канал у зонах, контакт у списках і каналах, список прийому в каналах), зона/список без
    елементів зникають разом із записом, поле каналу стає «None». Усе -- ОДНА правка: або вся, або жодної."""
    refs = references(img, kind, ident)
    if refs and not cascade:
        raise TableEditError(["%s використовується:\n%s" % (KIND_LABELS[kind], refs.text())])
    T = tables_of(img, dp)
    tok = _Tokens(img)
    edits = {}
    n = ident + 1 if kind in ("contact", "tg", "aprs") else ident

    if kind == "aprs":
        hdr, rows = T["aprs"]
        prob = aprs_delete_problem(img, ident)
        if prob:
            raise TableEditError([prob])
        del rows[ident]
        edits["aprs"] = (hdr, rows)
        _clear_channel_ref(img, T, edits, "APRS", lambda rec: rec[cc.O_APRS] == n, digital_only=False)
    elif kind == "zone":
        hdr, rows = T["zones"]
        del rows[_row_of(img, "zone", ident)]
        edits["zones"] = (hdr, rows)
    elif kind == "channel":
        hdr, rows = T["channels"]
        del rows[_row_of(img, "channel", ident)]
        edits["channels"] = (hdr, rows)
        zh, zr = T["zones"]
        keep = []
        for (b, _nm, mem), row in zip(zones(img), zr):
            if ident in mem:
                new = [m for m in mem if m != ident]
                if not new:
                    continue                       # зона без каналів зникає разом з ним (імпорт зробив би те саме, але з попередженням)
                row = _member_row(row, [tok("channel", m) for m in new], 80)
            keep.append(row)
        edits["zones"] = (zh, keep)
    elif kind == "tg":
        hdr, rows = T["tg_lists"]
        del rows[_row_of(img, "tg", ident)]
        edits["tg_lists"] = (hdr, rows)
        _clear_channel_ref(img, T, edits, "TG List", lambda rec: rec[cc.O_GROUP] == n)
    elif kind == "dtmf":
        hdr, rows = T["dtmf"]
        del rows[_row_of(img, "dtmf", ident)]
        edits["dtmf"] = (hdr, rows)
    elif kind == "contact":
        hdr, rows = T["contacts"]
        del rows[_row_of(img, "contact", ident)]
        edits["contacts"] = (hdr, rows)
        gh, gr = T["tg_lists"]
        keep, dead = [], set()
        for (s, _nm, mem), row in zip(tg_lists(img), gr):
            if n in mem:
                new = [m for m in mem if m != n]
                if not new:
                    dead.add(s + 1)
                    continue
                row = _member_row(row, [tok("contact", m) for m in new], TG_MAX)
            keep.append(row)
        edits["tg_lists"] = (gh, keep)
        _clear_channel_ref(img, T, edits, "Contact", lambda rec: (rec[cc.O_CONTACT] | (rec[cc.O_CONTACT + 1] << 8)) == n)
        if dead:
            _clear_channel_ref(img, T, edits, "TG List", lambda rec: rec[cc.O_GROUP] in dead)
    else:
        raise ValueError(kind)
    return _run(img, edits, dp)


def _clear_channel_ref(img, T, edits, col, pred, digital_only=True):
    """Поле col (Contact / TG List / APRS) у каналах, що задовольняють pred(rec), -> «None». Таблицю каналів створює/доповнює edits.
    digital_only -- Contact і TG List є лише в цифрових каналах; APRS -- в усіх."""
    hdr, rows = edits.get("channels") or T["channels"]
    for (num, rec), row in zip(img.channels(), rows):
        if (not digital_only or rec[cc.O_MODE] != 0) and pred(rec):
            _set_cell(hdr, row, col, "None")
    edits["channels"] = (hdr, rows)


# ---------------------------------------------------------------------------------------------------------------------------------
#  DTMF-контакти (R-next, Y4): ім'я до 16 байтів + код до 16 знаків «0-9 A-D * #». Ті самі рядки, що в DTMF.csv; перевірка -- імпорту CSV.
#  Єдине, що редактор додає: код не може бути порожнім (контакт без коду нічого не передасть) -- CSV-імпорт порожній код приймає.
# ---------------------------------------------------------------------------------------------------------------------------------

def dtmf_code_problem(text):
    """Текст проблеми з кодом DTMF або None. Пробіли ігноруються, регістр не важливий (як в імпорті)."""
    t = "".join((text or "").split())
    if not t:
        return "код порожній: потрібен хоч один знак (%s)" % cc.DTMF_ALPHABET
    try:
        cc._dtmf_parse(t)
    except ValueError as e:
        return str(e)
    return None


def _dtmf_norm(text):
    return cc.dtmf_code_text(cc._dtmf_parse(text)) if text.strip() else ""


def dtmf_add(img, name, code, dp):
    """Новий DTMF-контакт. Слот вибирає імпорт (перший вільний, до 63)."""
    prob = name_problem(img, "dtmf", name)
    if prob:
        raise TableEditError(["назва: " + prob])
    prob = dtmf_code_problem(code)
    if prob:
        raise TableEditError(["код: " + prob])
    hdr, rows = tables_of(img, dp)["dtmf"]
    rows.append(["", _dtmf_norm(code), name])
    return _run(img, {"dtmf": (hdr, rows)}, dp)


def dtmf_set_code(img, slot, code, dp):
    """Змінити код DTMF-контакту (назва і слот лишаються)."""
    prob = dtmf_code_problem(code)
    if prob:
        raise TableEditError(["код: " + prob])
    hdr, rows = tables_of(img, dp)["dtmf"]
    rows[_row_of(img, "dtmf", slot)][1] = _dtmf_norm(code)
    return _run(img, {"dtmf": (hdr, rows)}, dp)


# ---------------------------------------------------------------------------------------------------------------------------------
#  Контакти (R33, Q1): розділ «Кодплаг → Контакти» править ті самі рядки Contacts.csv і проганяє їх через імпорт CSV, як усі інші редактори.
#  Колонки Contacts.csv: Contact Name, ID, ID Type, TS Override, <читабельна назва>. TS Override редактор не змінює (лише зберігає при копіюванні).
# ---------------------------------------------------------------------------------------------------------------------------------

CONTACT_TYPE_NAMES = dict(cc.CALL_TYPE_NAMES)          # 0 Group / 1 Private / 2 All Call -- як у Contacts.csv


def contact_rows(img):
    """[(слот, назва, ID, тип 0..2, TS Override-текст)] -- повний вигляд контактів для редактора."""
    out = []
    for s, r in img.contacts():
        ts = "Disabled" if r[23] & 0x01 else str(((r[23] & 0x02) >> 1) + 1)
        out.append((s, cc.readable_text(r[:16]), cv.bcd_to_int(r[16:20]), r[20] if r[20] in CONTACT_TYPE_NAMES else 0, ts))
    return out


def contact_id_problem(text):
    """Текст проблеми з TG / ID або None (0..16777215, як у contact_edit.parse_id)."""
    try:
        ce.parse_id(text)
    except ValueError as e:
        return str(e)
    return None


def contact_add(img, name, ident, ctype, dp, ts="Disabled"):
    """Новий контакт: назва, TG/ID, тип виклику 0/1/2. Слот вибирає імпорт (перший вільний)."""
    prob = name_problem(img, "contact", name)
    if prob:
        raise TableEditError(["назва: " + prob])
    prob = contact_id_problem(str(ident))
    if prob:
        raise TableEditError(["TG / ID: " + prob])
    if ctype not in CONTACT_TYPE_NAMES:
        raise TableEditError(["тип виклику: 0 (група), 1 (приват) або 2 (всім)"])
    hdr, rows = tables_of(img, dp)["contacts"]
    rows.append(["", str(int(ident)), CONTACT_TYPE_NAMES[ctype], ts, name])
    return _run(img, {"contacts": (hdr, rows)}, dp)


def contact_set(img, slot, ident=None, ctype=None, dp=None):
    """Змінити TG/ID і/або тип виклику контакту (назва лишається; її змінює rename_entity)."""
    dp = dp or cc.system_decimal_point()
    hdr, rows = tables_of(img, dp)["contacts"]
    row = rows[_row_of(img, "contact", slot)]
    if ident is not None:
        prob = contact_id_problem(str(ident))
        if prob:
            raise TableEditError(["TG / ID: " + prob])
        row[1] = str(int(ident))
    if ctype is not None:
        if ctype not in CONTACT_TYPE_NAMES:
            raise TableEditError(["тип виклику: 0 (група), 1 (приват) або 2 (всім)"])
        row[2] = CONTACT_TYPE_NAMES[ctype]
    return _run(img, {"contacts": (hdr, rows)}, dp)


def contact_duplicate(img, slot, name, dp):
    """Копія контакту з новою назвою (ID, тип і TS Override ті самі)."""
    prob = name_problem(img, "contact", name)
    if prob:
        raise TableEditError(["назва: " + prob])
    hdr, rows = tables_of(img, dp)["contacts"]
    src = rows[_row_of(img, "contact", slot)]
    rows.append(["", src[1], src[2], src[3], name])
    return _run(img, {"contacts": (hdr, rows)}, dp)


# ---------------------------------------------------------------------------------------------------------------------------------
#  Канали
# ---------------------------------------------------------------------------------------------------------------------------------

CHANNEL_COLUMNS = [c["name"] for c in cc.CH_COLUMNS]
DEFAULT_FREQ = "145.50000"            # типова частота нового каналу (змініть у формі); показ за локаллю -- у channel_values


def _ctx(img, dp):
    return cc.make_ctx_for_export(img, dp)


def channel_values(img, number, dp):
    """Значення форми каналу: {«Channel Name»: читабельна назва, «Channel Number»: ..., і за назвою кожної колонки CSV: текст}.
    Неактуальні для типу колонки (напр. «Colour Code» аналогового каналу) -- порожній рядок."""
    rec = img.channel_rec(number)
    ctx = _ctx(img, dp)
    out = {"Channel Number": str(number), "Channel Name": cc.readable_text(rec[:16])}
    for col in cc.CH_COLUMNS:
        out[col["name"]] = col["dec"](rec, ctx).strip("\t").strip() if cc.applies(col, rec) else ""
    return out


def applicable(col_name, digital):
    col = cc.CH_COLUMN_BY_NAME[col_name]
    return col["app"] == "B" or (col["app"] == "D") == digital


def _chan_index(img, number):
    for i, (n, _r) in enumerate(img.channels()):
        if n == number:
            return i
    raise TableEditError(["канал №%s не знайдено в документі" % number])


def _defaults_for(digital, dp):
    tmpl = cc.new_channel_template(digital)
    ctx = cc.Ctx(dp)
    return {c["name"]: c["dec"](tmpl, ctx).strip("\t").strip() for c in cc.CH_COLUMNS if cc.applies(c, tmpl)}


AES_ENCRYPT_OFF, AES_UNUSED2_OFF = 41, 42        # CodeplugChannel_t: encrypt, _UNUSED_2 (codeplug.h)


def aes_slot(rec):
    """AES-слот каналу (0 -- успадкувати, 1..15, 0xFF -- відкрито) так, як його читає прошивка (codeplugChannelGetAesKeySlot): на каналі з власним
    DMR ID байт encrypt зайнятий під ID, слот лежить у _UNUSED_2 з міткою 0xA0."""
    if rec[cc.O_FLAG1L] & cc.FL_DMRID:
        tagged = rec[AES_UNUSED2_OFF]
        if (tagged & 0xF0) != 0xA0:
            return 0
        return 0xFF if (tagged & 0x0F) == 0 else tagged & 0x0F
    return rec[AES_ENCRYPT_OFF]


AES_KEY_COLUMN = "AES Key"      # лише в редакторі: у CSV такої колонки немає (формат CSV не змінюємо), тож перевірки імпорту сюди не застосовуються
AES_SLOT_MAX = 15
AES_TAG = 0xA0


def aes_slot_set(rec, slot):
    """Записати слот у запис каналу так само, як codeplugChannelSetAesKeySlot(): на каналі з власним DMR ID -- у _UNUSED_2 з міткою 0xA0, інакше -- у
    байт encrypt. slot: 0 -- без ключа, 1..15 -- ключ, 0xFF -- примусово відкрито."""
    rec = bytearray(rec)
    if rec[cc.O_FLAG1L] & cc.FL_DMRID:
        rec[AES_UNUSED2_OFF] = 0 if slot == 0 else (AES_TAG | (0 if slot == 0xFF else slot & 0x0F))
    else:
        rec[AES_ENCRYPT_OFF] = slot
    return bytes(rec)


def channel_set_aes_slot(img, number, slot):
    """Ключ AES каналу (V3.1): 0 -- без шифрування, 1..15 -- слот ключа. Інші поля запису (зокрема DMR ID) не змінюються ні на біт. Повертає
    ImportResult, як і решта правок документа. Матеріал ключа тут не з'являється: канал зберігає лише НОМЕР слота."""
    if not isinstance(slot, int) or not (0 <= slot <= AES_SLOT_MAX):
        raise TableEditError(["ключ AES: очікується число 0..%d (0 -- без шифрування)" % AES_SLOT_MAX])
    rec = img.channel_rec(number) if any(n == number for n, _r in img.channels()) else None
    if rec is None:
        raise TableEditError(["канал №%s не знайдено в документі" % number])
    if rec[cc.O_MODE] == 0:
        raise TableEditError(["ключ AES задається лише для цифрового каналу"])
    before = aes_slot(rec)
    new_rec = aes_slot_set(rec, slot)
    out = cc.Image(img.eeprom, img.flash, img.base)
    res = cc.ImportResult()
    res.image = out
    if new_rec != bytes(rec):
        out.set_channel_rec(number, new_rec)
        name = cc.readable_text(rec[:16])
        def txt(v):
            return "без шифрування" if v in (0, 0xFF) else "ключ %d" % v
        res.changed.append(("Канали", "№%d %s: ключ AES %s -> %s" % (number, name, txt(before), txt(slot))))
        if rec[cc.O_FLAG1L] & cc.FL_DMRID:
            res.warnings.append("Канал №%d має власний DMR ID: слот ключа лежить у іншому байті (мітка 0xA0), тож DMR ID не зачеплено. Але будь-яка "
                                "зміна власного DMR ID каналу -- тут чи в меню рації -- скидає слот ключа." % number)
    return res


def channel_edit(img, number, changes, dp):
    """Змінити поля каналу. changes: {«Channel Name»|назва колонки CSV: текст}. Посилання (Contact / TG List / APRS) можна давати за
    назвою або «#N». Зміна типу підставляє типові значення для колонок, що стали актуальними."""
    hdr, rows = tables_of(img, dp)["channels"]
    i = _chan_index(img, number)
    row = rows[i]
    changes = dict(changes)
    if "Channel Name" in changes:
        prob = name_problem(img, "channel", changes["Channel Name"], exclude=number)
        if prob:
            raise TableEditError(["назва: " + prob])
        row[-1] = changes.pop("Channel Name")
    if "Channel Type" in changes:
        digital = changes["Channel Type"].strip().casefold().startswith("dig")
        defaults = _defaults_for(digital, dp)
        for name in CHANNEL_COLUMNS:
            j = hdr.index(name)
            if not applicable(name, digital):
                row[j] = ""
            elif not row[j].strip() and name not in changes:
                row[j] = defaults.get(name, "")
    for name, text in changes.items():
        if name not in hdr:
            raise TableEditError(["невідоме поле каналу: %s" % name])
        row[hdr.index(name)] = text
    res = _run(img, {"channels": (hdr, rows)}, dp)
    # «М'які» колонки (потужність, TOT, VOX, шумодав, позиція...) імпорт CSV при помилці лишає як було й лише попереджає. Для редактора це
    # мовчазна відмова від того, що людина щойно ввела, -- тому помилку в ЗМІНЕНОМУ полі повертаємо як відмову.
    bad = []
    for w in res.warnings:
        if "лишено як було" in w and any("колонка «%s»" % n in w for n in changes):
            bad.append(_CSV_WARN_PREFIX.sub("", w).replace(" -- поле лишено як було.", ""))
    if bad:
        raise TableEditError(bad)
    if "DMR ID" in changes:
        before, after = aes_slot(img.channel_rec(number)), aes_slot(res.image.channel_rec(number))
        if before != after:
            res.warnings.append("AES-слот каналу №%d (%s) скинуто: власний DMR ID каналу ділить байти зі слотом -- так само поводиться меню рації "
                                "при зміні DMR ID. Слот можна виставити знову." % (number, "відкрито" if before == 0xFF else "ключ %d" % before))
    return res


def channel_new(img, name, digital, dp, source=None):
    """Новий канал. source -- номер каналу, значення якого взяти за основу (інакше типові). Номер вибирає імпорт (R26: слот, що ніколи не
    був зайнятий; звільнений -- лише коли інших нема)."""
    prob = name_problem(img, "channel", name)
    if prob:
        raise TableEditError(["назва: " + prob])
    hdr, rows = tables_of(img, dp)["channels"]
    if source is not None:
        row = list(rows[_chan_index(img, source)])
        base_digital = row[hdr.index("Channel Type")].strip().casefold().startswith("dig")
        if base_digital != digital:
            raise TableEditError(["основа каналу має інший тип"])
    else:
        row = [""] * len(hdr)
        defaults = _defaults_for(digital, dp)
        row[hdr.index("Channel Type")] = "Digital" if digital else "Analogue"
        for c, v in defaults.items():
            row[hdr.index(c)] = v
        dec_sep = "," if dp == "," else "."
        for fc in ("Rx Frequency", "Tx Frequency"):
            row[hdr.index(fc)] = DEFAULT_FREQ.replace(".", dec_sep)
    row[0] = ""                              # Channel Number: порожньо -> номер призначає імпорт
    row[1] = ""                              # сумісна назва: порожньо -> береться читабельна
    row[-1] = name
    rows.append(row)
    return _run(img, {"channels": (hdr, rows)}, dp)


def channel_duplicate(img, number, name, dp):
    rec = img.channel_rec(number)
    return channel_new(img, name, rec[cc.O_MODE] != 0, dp, source=number)


def new_number_hint(img):
    """Найменший вільний номер каналу (лише підказка: справжній номер вибирає імпорт за правилом R26); None -- вільних нема."""
    nmax = cl.CP_CHANNELS_BANKS * cl.CP_CHANNELS_PER_BANK
    used = set(n for n, _r in img.channels())
    for n in range(1, nmax + 1):
        if n not in used:
            return n
    return None


# ---------------------------------------------------------------------------------------------------------------------------------
#  Вибір посилань у формі каналу (контакт / список прийому / APRS-конфіг -- зі списку наявних, а не текстом)
# ---------------------------------------------------------------------------------------------------------------------------------

def ref_options(img, kind):
    """[(номер, підпис)] наявних записів для поля каналу. kind: contact / group / aprs. Підпис містить номер, тож він унікальний."""
    if kind == "contact":
        return [(s + 1, "№%d %s (ID %d)" % (s + 1, cc.readable_text(r[:16]), cv.bcd_to_int(r[16:20]))) for s, r in img.contacts()]
    if kind == "group":
        return [(s + 1, "№%d %s (%d)" % (s + 1, cc.readable_text(r[:16]), ln)) for s, r, ln in img.groups()]
    if kind == "aprs":
        return [(s + 1, "№%d %s" % (s + 1, cc.readable_text(r[:8]))) for s, r in img.aprs()]
    raise ValueError(kind)


def ref_token(img, kind, number):
    """Текст посилання для channel_edit: «None» (0) / назва / «#N»."""
    return "None" if number == 0 else _Tokens(img)(kind, number)


def channel_refs(img, number):
    """Поточні посилання каналу: {«Contact»: n, «TG List»: n, «APRS»: n} (0 -- нема)."""
    rec = img.channel_rec(number)
    return {"Contact": rec[cc.O_CONTACT] | (rec[cc.O_CONTACT + 1] << 8), "TG List": rec[cc.O_GROUP], "APRS": rec[cc.O_APRS]}
