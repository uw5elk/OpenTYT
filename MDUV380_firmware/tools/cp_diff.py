# -*- coding: utf-8 -*-
"""R45 V2: «що змінила остання операція» -- знімок кодплага до і після ручної дії на рації й ОСМИСЛЕНА різниця (не в байтах).

Потік: кнопка «Запам'ятати стан» -> `capture()` + `save_state()` (файл поруч зі звітом) -> користувач щось робить на рації (видаляє канал, контакт, зону...)
-> кнопка «Порівняти» -> `capture()` ще раз -> `compare()` -> `Diff.lines()` -- людською мовою: які канали з'явились чи зникли, що змінилось у зонах і контактах,
які сектори мають зміни. Окремо (V2.3) -- чи змінилось те, чого не мало: калібрування, ключі AES, теми, база позивних, підказки; і, якщо назвати, що саме
робилось (`Expected`), -- чи змінились інші канали, зони й контакти. Те, що є НАСЛІДКОМ операції (видалили контакт -> у каналах він став «Немає»; видалили канал ->
він зник із зон), відокремлено від несподіваного.

Лише читання: модуль працює з образами (`cps_csv.Image`) і хешами; у файл стану ключів AES НЕ потрапляє нічого (лише SHA-256), а EEPROM-образ містить калібрування
(несекретне). Без Tk і без рації."""
import datetime
import hashlib
import io
import json
import struct
import zipfile

import codeplug_view as cv
import cps_csv as cc
import cps_link as cl

STATE_VERSION = 1
SECTOR = 4096
CALIB = (0x10000, 0x11000)                       # сектор калібрування в EEPROM -- НІКОЛИ не має змінитись від звичайної роботи
SHOW = 12

# --- поля запису каналу (CodeplugChannel_t, 56 Б) ---
CHAN_FIELDS = (("назва", 0, 16), ("частота прийому", 16, 20), ("частота передачі", 20, 24), ("режим FM/DMR", 24, 25), ("потужність", 25, 26), ("TOT", 27, 28),
               ("тон прийому", 32, 34), ("тон передачі", 34, 36), ("DMR ID каналу", 38, 42), ("TG-список", 43, 44), ("колірний код", 44, 45),
               ("APRS-слот", 45, 46), ("контакт", 46, 48), ("прапорці (таймслот, пропуск у скані, лише прийом...)", 48, 52), ("шумодав", 55, 56))
CONTACT_FIELDS = (("ім'я", 0, 16), ("номер", 16, 20), ("тип виклику", 20, 21))

# --- де в EEPROM що лежить (для підпису «неопоясненого»; адреси з claude/codeplug-map.md і cps_csv) ---
EE_AREAS = (
    (0x00E0, 0x0108, "позивний і загальні налаштування"),
    (cc.ADDR_APRS, cc.ADDR_APRS + cc.APRS_MAX * cc.APRS_SIZE, "слоти APRS"),
    (cc.ADDR_DTMF, cc.ADDR_DTMF + cc.DTMF_MAX * cc.DTMF_SIZE, "DTMF-контакти"),
    (cl.CP_ADDR_CHANNEL_HEADER_EEPROM, cl.CP_ADDR_CHANNEL_HEADER_EEPROM + 16 + cl.CP_CHANNELS_PER_BANK * cl.CP_CHANNEL_SIZE, "канали 1..128 (маска й записи)"),
    (0x6000, 0x604B, "«останній канал у зоні» (LUCZ)"),
    (0x604B, 0x7000, "налаштування рації (поточні зона й канал, гучність...; область з 0x604B, кінець не виміряно)"),
    (0x7518, 0x7524, "екран вітання й пароль"),
    (0x7524, 0x7538, "швидкі клавіші"),
    (0x7590, 0x7600, "VFO A і B"),
    (cl.CP_ADDR_EX_ZONE_INUSE, cl.CP_ADDR_EX_ZONE_INUSE + 32, "маска зон"),
)


def _sha(b):
    return hashlib.sha256(bytes(b)).hexdigest()


def _name(raw16):
    try:
        return cc.readable_text(bytes(raw16)).strip() or "?"
    except Exception:  # noqa: BLE001 -- назва лише для підпису
        return "?"


# =============================================================================================================================
#  Знімок стану
# =============================================================================================================================

class State:
    """Знімок: образ кодплага (EEPROM + флеш-частина) + SHA-256 того, чого торкатись не можна (калібрування, ключі AES, теми, заголовки бази й підказок)."""

    def __init__(self, eeprom, flash, flash_cp_start, guards, created):
        self.eeprom = bytes(eeprom)
        self.flash = bytes(flash)
        self.base = flash_cp_start
        self.guards = dict(guards)
        self.created = created

    def image(self):
        return cc.Image(bytearray(self.eeprom), bytearray(self.flash), self.base)


def capture(img, guards=None, now=None):
    """Знімок з образу `cc.Image` (guards -- {назва: SHA-256 або «не прочитано: ...»})."""
    created = (now or datetime.datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    return State(img.eeprom, img.flash, img.base, guards or {}, created)


def save_state(state, path):
    """Файл стану: zip з manifest.json, eeprom.bin, flash.bin. Ключів AES у ньому немає (лише SHA-256 у guards)."""
    man = {"version": STATE_VERSION, "created": state.created, "flashCpStart": state.base, "eepromLen": len(state.eeprom), "flashLen": len(state.flash),
           "guards": state.guards, "sha256": {"eeprom": _sha(state.eeprom), "flash": _sha(state.flash)}}
    with zipfile.ZipFile(path, "x", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(man, ensure_ascii=False, indent=1))
        z.writestr("eeprom.bin", state.eeprom)
        z.writestr("flash.bin", state.flash)
    return path


class StateError(ValueError):
    pass


def load_state(path):
    try:
        with zipfile.ZipFile(path) as z:
            man = json.loads(z.read("manifest.json").decode("utf-8"))
            ee, fl = z.read("eeprom.bin"), z.read("flash.bin")
    except (OSError, KeyError, zipfile.BadZipFile, ValueError) as e:
        raise StateError("файл стану не читається: %s" % e)
    if man.get("version") != STATE_VERSION:
        raise StateError("файл стану версії %r, очікувалась %d" % (man.get("version"), STATE_VERSION))
    if _sha(ee) != man["sha256"]["eeprom"] or _sha(fl) != man["sha256"]["flash"]:
        raise StateError("файл стану пошкоджено: SHA-256 не збігається")
    return State(ee, fl, man["flashCpStart"], man.get("guards", {}), man.get("created", "?"))


# =============================================================================================================================
#  Що очікувалось змінити (необов'язково)
# =============================================================================================================================

class Expected:
    """Що користувач збирався змінити: номери каналів, назви (або біти) зон, номери контактів. None -- не вказано (несподіване не оцінюється)."""

    def __init__(self, channels=(), zones=(), contacts=()):
        self.channels = set(int(x) for x in channels)
        self.zones = set(str(x).strip().casefold() for x in zones)
        self.contacts = set(int(x) for x in contacts)

    @classmethod
    def parse(cls, channels="", zones="", contacts=""):
        """З тексту полів панелі: номери через кому/пробіл; зони -- назви через «;» або кому. Порожні поля -- None (не вказано)."""
        def nums(t):
            out = []
            for part in str(t or "").replace(";", ",").replace(" ", ",").split(","):
                part = part.strip()
                if part:
                    out.append(int(part))
            return out

        def names(t):
            return [p.strip() for p in str(t or "").replace(",", ";").split(";") if p.strip()]
        c, z, k = nums(channels), names(zones), nums(contacts)
        if not (c or z or k):
            return None
        return cls(c, z, k)


# =============================================================================================================================
#  Різниця
# =============================================================================================================================

class Diff:
    def __init__(self):
        self.channels_added, self.channels_removed, self.channels_changed = [], [], []      # [(n, назва)] / [(n, назва, [поля])]
        self.zones_added, self.zones_removed, self.zones_changed = [], [], []               # [(bit, назва, к-сть каналів)] / [(bit, назва, [описи])]
        self.contacts_added, self.contacts_removed, self.contacts_changed = [], [], []      # [(№, назва)] / [(№, назва, [поля])]
        self.groups_changed, self.aprs_changed, self.dtmf_changed = [], [], []              # [(№, текст)]
        self.vfo_changed = []                                                              # ["VFO A", ...]
        self.service = []                                                                  # службові ділянки, що рація пише сама
        self.consequences = []                                                             # [(текст)] -- наслідки видалення
        self.unexplained = []                                                              # [(адреса_від, адреса_до, де)] байти, яких не пояснив жоден розділ
        self.hidden = []                                                                   # зміни запису каналу поза маскою тощо
        self.sectors_ee, self.sectors_fl = [], []                                          # адреси секторів із змінами
        self.bytes_ee = self.bytes_fl = 0
        self.protected = []                                                                # [(назва, змінилось: True/False/None, пояснення)]
        self.unexpected = []                                                               # [(текст)] -- поза Expected
        self.expected_given = False
        self.calibration_bytes = 0

    # --- ключі для тестів і звірки ---
    def items(self):
        """Множина (вид, ідентифікатор) усього, що змінилось у розділах (без службового й наслідків)."""
        s = set()
        s |= {("канал додано", n) for n, _t in self.channels_added}
        s |= {("канал видалено", n) for n, _t in self.channels_removed}
        s |= {("канал змінено", n) for n, _t, _f in self.channels_changed if not _is_consequence_fields(_f)}
        s |= {("зона додана", b) for b, _t, _c in self.zones_added}
        s |= {("зона видалена", b) for b, _t, _c in self.zones_removed}
        s |= {("зона змінена", b) for b, _t, _d in self.zones_changed}
        s |= {("контакт додано", n) for n, _t in self.contacts_added}
        s |= {("контакт видалено", n) for n, _t in self.contacts_removed}
        s |= {("контакт змінено", n) for n, _t, _f in self.contacts_changed}
        s |= {("TG-список", n) for n, _t in self.groups_changed}
        s |= {("APRS", n) for n, _t in self.aprs_changed}
        s |= {("DTMF", n) for n, _t in self.dtmf_changed}
        return s

    @property
    def any_change(self):
        return bool(self.bytes_ee or self.bytes_fl)

    @property
    def protected_changed(self):
        return [p for p in self.protected if p[1] is True]

    # --- текст ---
    def lines(self, limit=SHOW):
        out = []

        def block(title, rows):
            if not rows:
                return
            out.append(title)
            for r in rows[:limit]:
                out.append("  - " + r)
            if len(rows) > limit:
                out.append("  - ... і ще %d" % (len(rows) - limit))
        if not self.any_change:
            return ["Кодплаг не змінився: жодного байта (EEPROM і флеш-частина однакові)."]
        block("Канали, що з'явились:", ["№%d «%s»" % (n, t) for n, t in self.channels_added])
        block("Канали, що зникли:", ["№%d «%s»" % (n, t) for n, t in self.channels_removed])
        block("Канали, що змінились:", ["№%d «%s»: %s" % (n, t, ", ".join(f)) for n, t, f in self.channels_changed])
        block("Зони, що з'явились:", ["«%s» (біт %d, каналів %d)" % (t, b, c) for b, t, c in self.zones_added])
        block("Зони, що зникли:", ["«%s» (біт %d, було каналів %d)" % (t, b, c) for b, t, c in self.zones_removed])
        block("Зони, що змінились:", ["«%s» (біт %d): %s" % (t, b, "; ".join(d)) for b, t, d in self.zones_changed])
        block("Контакти, що з'явились:", ["№%d «%s»" % (n, t) for n, t in self.contacts_added])
        block("Контакти, що зникли:", ["№%d «%s»" % (n, t) for n, t in self.contacts_removed])
        block("Контакти, що змінились:", ["№%d «%s»: %s" % (n, t, ", ".join(f)) for n, t, f in self.contacts_changed])
        block("Списки прийому (TG):", ["№%d: %s" % (n, t) for n, t in self.groups_changed])
        block("Слоти APRS:", ["№%d: %s" % (n, t) for n, t in self.aprs_changed])
        block("DTMF-контакти:", ["№%d: %s" % (n, t) for n, t in self.dtmf_changed])
        block("Наслідки (каскад видалення, не окремі правки):", self.consequences)
        if self.vfo_changed:
            out.append("VFO змінено: %s (рація пише VFO сама при вимкненні й зміні частоти)." % ", ".join(self.vfo_changed))
        block("Службові ділянки, що рація пише сама:", self.service)
        block("Запис каналу поза маскою змінено (канал у кодплазі не значиться):", self.hidden)
        if self.unexplained:
            block("Змінені байти, яких не пояснив жоден розділ:", ["0x%X..0x%X (%s)" % (a, b - 1, w) for a, b, w in self.unexplained])
        out.append("Змінено байтів: EEPROM %d, флеш-частина %d." % (self.bytes_ee, self.bytes_fl))
        if self.sectors_ee or self.sectors_fl:
            sec = ["EEPROM 0x%X" % a for a in self.sectors_ee] + ["флеш 0x%X" % a for a in self.sectors_fl]
            out.append("Сектори (4 КіБ) із змінами: %d -- %s%s." % (len(sec), ", ".join(sec[:SHOW]), (" ... і ще %d" % (len(sec) - SHOW)) if len(sec) > SHOW else ""))
        return out


def _is_consequence_fields(fields):
    return bool(fields) and all(f.startswith("↳") for f in fields)


def _field_changes(a, b, table):
    names, covered = [], set()
    for label, lo, hi in table:
        covered.update(range(lo, hi))
        if a[lo:hi] != b[lo:hi]:
            names.append(label)
    other = [i for i in range(min(len(a), len(b))) if i not in covered and a[i] != b[i]]
    if other:
        names.append("інші байти (%d)" % len(other))
    return names


def _changed_ranges(a, b):
    """Суцільні діапазони змінених байтів [(від, до)) між двома буферами (однакової довжини)."""
    out, start = [], None
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            if start is None:
                start = i
        elif start is not None:
            out.append((start, i))
            start = None
    if start is not None:
        out.append((start, min(len(a), len(b))))
    return out


def _sectors(ranges, phys_base):
    """Адреси 4-КіБ секторів, у яких є змінені байти (phys_base -- фізична адреса початку буфера)."""
    out = set()
    for lo, hi in ranges:
        for sec in range((phys_base + lo) // SECTOR, (phys_base + hi - 1) // SECTOR + 1):
            out.add(sec * SECTOR)
    return sorted(out)


def _area_of(addr, areas):
    for lo, hi, label in areas:
        if lo <= addr < hi:
            return label
    return None


def compare(before, after, expected=None):
    """Різниця між двома `State`. `expected` -- `Expected` або None."""
    d = Diff()
    A, B = before.image(), after.image()
    d.expected_given = expected is not None
    ee_a, ee_b, fl_a, fl_b = before.eeprom, after.eeprom, before.flash, after.flash
    ranges_ee = _changed_ranges(ee_a, ee_b)
    ranges_fl = _changed_ranges(fl_a, fl_b)
    d.bytes_ee = sum(h - l for l, h in ranges_ee)
    d.bytes_fl = sum(h - l for l, h in ranges_fl)
    d.sectors_ee = _sectors(ranges_ee, 0)
    d.sectors_fl = _sectors(ranges_fl, cl.FLASH_ADDRESS_OFFSET + before.base)

    # ---------------- канали ----------------
    ca, cb = dict(A.channels()), dict(B.channels())
    removed_ch = set(ca) - set(cb)
    added_ch = set(cb) - set(ca)
    for n in sorted(added_ch):
        d.channels_added.append((n, _name(cb[n][:16])))
    for n in sorted(removed_ch):
        d.channels_removed.append((n, _name(ca[n][:16])))
    removed_contacts = {slot + 1 for slot, _r in A.contacts()} - {slot + 1 for slot, _r in B.contacts()}
    removed_groups = {s + 1 for s, _r, _l in A.groups()} - {s + 1 for s, _r, _l in B.groups()}
    aprs_a, aprs_b = len(A.aprs()), len(B.aprs())
    for n in sorted(set(ca) & set(cb)):
        if ca[n] == cb[n]:
            continue
        fields = _field_changes(ca[n], cb[n], CHAN_FIELDS)
        # наслідок видалення: поле «контакт»/«TG-список»/«APRS-слот» стало 0 (або слот зник), а решта запису та сама
        only = set(fields)
        cons = []
        if only <= {"контакт", "TG-список", "APRS-слот"}:
            oc = ca[n][cc.O_CONTACT] | (ca[n][cc.O_CONTACT + 1] << 8)
            nc = cb[n][cc.O_CONTACT] | (cb[n][cc.O_CONTACT + 1] << 8)
            if "контакт" in only and oc in removed_contacts and nc == 0:
                cons.append("↳ контакт №%d видалено -> «Немає»" % oc)
            og, ng = ca[n][cc.O_GROUP], cb[n][cc.O_GROUP]
            if "TG-список" in only and og in removed_groups and ng == 0:
                cons.append("↳ TG-список №%d видалено -> «Немає»" % og)
            oa, na = ca[n][cc.O_APRS], cb[n][cc.O_APRS]
            if "APRS-слот" in only and oa > aprs_b and na == 0:
                cons.append("↳ APRS-слот №%d видалено -> «Немає»" % oa)
            if len(cons) == len(only):
                d.consequences.append("канал №%d «%s»: %s" % (n, _name(ca[n][:16]), "; ".join(c[2:] for c in cons)))
                d.channels_changed.append((n, _name(ca[n][:16]), cons))
                continue
        d.channels_changed.append((n, _name(cb[n][:16]), fields))
    # записи поза маскою, які змінились без зміни маски (рація стирає запис видаленого каналу 0xFF -- це не «зміна каналу»)
    for n in range(1, cl.CP_CHANNELS_BANKS * cl.CP_CHANNELS_PER_BANK + 1):
        if n in ca or n in cb:
            continue
        try:
            ra, rb = A.channel_rec(n), B.channel_rec(n)
        except cc.CsvError:
            continue
        if ra != rb and set(rb) != {0xFF}:
            d.hidden.append("канал №%d" % n)

    # ---------------- зони ----------------
    za = {bit: rec for bit, rec in A.zones()}
    zb = {bit: rec for bit, rec in B.zones()}
    fmt_a, fmt_b = A.zone_format(), B.zone_format()

    def vis(rec, fmt):
        vals = list(struct.unpack_from("<%dH" % fmt, rec, 16))
        z = vals.index(0) if 0 in vals else len(vals)
        return vals[:z]
    for bit in sorted(set(zb) - set(za)):
        d.zones_added.append((bit, _name(zb[bit][:16]), len(vis(zb[bit], fmt_b))))
    for bit in sorted(set(za) - set(zb)):
        d.zones_removed.append((bit, _name(za[bit][:16]), len(vis(za[bit], fmt_a))))
    for bit in sorted(set(za) & set(zb)):
        if za[bit] == zb[bit]:
            continue
        desc = []
        if za[bit][:16] != zb[bit][:16]:
            desc.append("назву змінено: «%s» -> «%s»" % (_name(za[bit][:16]), _name(zb[bit][:16])))
        la, lb = vis(za[bit], fmt_a), vis(zb[bit], fmt_b)
        add, rem = [x for x in lb if x not in la], [x for x in la if x not in lb]
        cons_rem = [x for x in rem if x in removed_ch]
        if add:
            desc.append("додано канали %s" % ", ".join("№%d" % x for x in add))
        if rem:
            plain = [x for x in rem if x not in removed_ch]
            if plain:
                desc.append("вийнято канали %s" % ", ".join("№%d" % x for x in plain))
            if cons_rem:
                d.consequences.append("зона «%s»: канал %s видалено з кодплага -> зник зі списку" % (_name(zb[bit][:16]), ", ".join("№%d" % x for x in cons_rem)))
                desc.append("↳ зникли видалені канали %s" % ", ".join("№%d" % x for x in cons_rem))
        if not add and not rem and la != lb:
            desc.append("порядок каналів змінено")
        if za[bit][16:] != zb[bit][16:] and not (add or rem or la != lb):
            desc.append("змінено байти за кінцем списку")
        if desc:
            d.zones_changed.append((bit, _name(zb[bit][:16]), desc))

    # ---------------- контакти ----------------
    ka, kb = {s + 1: r for s, r in A.contacts()}, {s + 1: r for s, r in B.contacts()}
    for n in sorted(set(kb) - set(ka)):
        d.contacts_added.append((n, _name(kb[n][:16])))
    for n in sorted(set(ka) - set(kb)):
        d.contacts_removed.append((n, _name(ka[n][:16])))
    for n in sorted(set(ka) & set(kb)):
        if ka[n] != kb[n]:
            d.contacts_changed.append((n, _name(kb[n][:16]), _field_changes(ka[n], kb[n], CONTACT_FIELDS)))

    # ---------------- TG-списки, APRS, DTMF ----------------
    ga, gb = {s + 1: (r, ln) for s, r, ln in A.groups()}, {s + 1: (r, ln) for s, r, ln in B.groups()}
    for n in sorted(set(ga) | set(gb)):
        if n not in ga:
            d.groups_changed.append((n, "список з'явився «%s»" % _name(gb[n][0][:16])))
        elif n not in gb:
            d.groups_changed.append((n, "список зник «%s»" % _name(ga[n][0][:16])))
        elif ga[n] != gb[n]:
            d.groups_changed.append((n, "список «%s» змінено (контактів %d -> %d)" % (_name(gb[n][0][:16]), ga[n][1], gb[n][1])))
    aa, ab = {s + 1: r for s, r in A.aprs()}, {s + 1: r for s, r in B.aprs()}
    for n in sorted(set(aa) | set(ab)):
        if n not in aa:
            d.aprs_changed.append((n, "слот з'явився"))
        elif n not in ab:
            d.aprs_changed.append((n, "слот зник"))
        elif aa[n] != ab[n]:
            d.aprs_changed.append((n, "слот змінено"))
    da, db = {s + 1: r for s, r in A.dtmf()}, {s + 1: r for s, r in B.dtmf()}
    for n in sorted(set(da) | set(db)):
        if n not in da:
            d.dtmf_changed.append((n, "контакт з'явився"))
        elif n not in db:
            d.dtmf_changed.append((n, "контакт зник"))
        elif da[n] != db[n]:
            d.dtmf_changed.append((n, "контакт змінено"))

    # ---------------- VFO, службове ----------------
    for k, label in enumerate(("VFO A", "VFO B")):
        lo = 0x7590 + 56 * k
        if ee_a[lo:lo + 56] != ee_b[lo:lo + 56]:
            d.vfo_changed.append(label)
    for lo, hi, label in EE_AREAS:
        if label.startswith("«останній") or label.startswith("налаштування рації") or label in ("швидкі клавіші", "екран вітання й пароль", "позивний і загальні налаштування"):
            n = sum(1 for l, h in ranges_ee for i in range(max(l, lo), min(h, hi)))
            if n:
                d.service.append("%s: змінено байтів %d (0x%X..0x%X)" % (label, n, lo, hi - 1))

    # ---------------- байти, яких ніхто не пояснив ----------------
    zone_fmt = fmt_b
    stride = 16 + 2 * zone_fmt
    ee_areas = list(EE_AREAS) + [(cl.CP_ADDR_EX_ZONE_LIST, cl.CP_ADDR_EX_ZONE_LIST + cl.CP_ZONES_MAX * stride, "список зон")]
    fl_areas = [(cl.CP_ADDR_CHANNEL_HEADER_FLASH, cl.CP_ADDR_CHANNEL_HEADER_FLASH + 7 * (16 + cl.CP_CHANNELS_PER_BANK * cl.CP_CHANNEL_SIZE), "канали 129..1024"),
                (cl.CP_ADDR_CONTACTS, cl.CP_ADDR_CONTACTS + cl.CP_CONTACTS_MAX * cl.CP_CONTACT_SIZE, "контакти"),
                (cl.CP_ADDR_RX_GROUP_LEN, cl.CP_ADDR_RX_GROUP_LEN + cl.CP_RXGROUPS_MAX, "довжини списків прийому"),
                (cl.CP_ADDR_RX_GROUP, cl.CP_ADDR_RX_GROUP + cl.CP_RXGROUPS_MAX * cl.CP_RXGROUP_SIZE, "списки прийому")]
    for l, h in ranges_ee:
        if CALIB[0] <= l < CALIB[1]:
            d.calibration_bytes += min(h, CALIB[1]) - l
            continue
        run_lo = None
        for a in range(l, h):
            known = _area_of(a, ee_areas)
            if known is None:
                if run_lo is None:
                    run_lo = a
            elif run_lo is not None:
                d.unexplained.append((run_lo, a, "EEPROM"))
                run_lo = None
        if run_lo is not None:
            d.unexplained.append((run_lo, h, "EEPROM"))
    for l, h in ranges_fl:
        run_lo = None
        for a in range(l, h):
            known = _area_of(before.base + a, fl_areas)
            if known is None:
                if run_lo is None:
                    run_lo = a
            elif run_lo is not None:
                d.unexplained.append((before.base + run_lo, before.base + a, "флеш-частина"))
                run_lo = None
        if run_lo is not None:
            d.unexplained.append((before.base + run_lo, before.base + h, "флеш-частина"))

    # ---------------- V2.3: що не мало змінитись ----------------
    cal_a, cal_b = ee_a[CALIB[0]:CALIB[1]], ee_b[CALIB[0]:CALIB[1]]
    if len(cal_a) == SECTOR and len(cal_b) == SECTOR:
        d.protected.append(("калібрування (EEPROM 0x10000..0x10FFF, образ)", cal_a != cal_b,
                            "змінено байтів: %d" % d.calibration_bytes if cal_a != cal_b else "однакове"))
    else:
        d.protected.append(("калібрування (EEPROM 0x10000..0x10FFF, образ)", None, "образ EEPROM коротший за 0x11000 -- не порівняно"))
    for name in sorted(set(before.guards) | set(after.guards)):
        x, y = before.guards.get(name), after.guards.get(name)
        if x is None or y is None:
            d.protected.append((name, None, "немає в одному зі знімків -- не порівняно"))
        elif str(x).startswith("не прочитано") or str(y).startswith("не прочитано"):
            d.protected.append((name, None, "не вдалося прочитати -- не порівняно"))
        else:
            d.protected.append((name, x != y, "однаковий SHA-256 (%s)" % x[:12] if x == y else "ЗМІНИВСЯ: %s -> %s" % (x[:12], y[:12])))

    # ---------------- несподіване (лише коли названо, що робилось) ----------------
    if expected is not None:
        names_ok = expected.zones
        for n, t, f in d.channels_changed:
            if n not in expected.channels and not _is_consequence_fields(f):
                d.unexpected.append("канал №%d «%s» змінився (%s), а в очікуваному його нема" % (n, t, ", ".join(f)))
        for n, t in d.channels_added:
            if n not in expected.channels:
                d.unexpected.append("канал №%d «%s» з'явився, а в очікуваному його нема" % (n, t))
        for n, t in d.channels_removed:
            if n not in expected.channels:
                d.unexpected.append("канал №%d «%s» зник, а в очікуваному його нема" % (n, t))
        for kind, rows in (("з'явилась", d.zones_added), ("зникла", d.zones_removed)):
            for bit, t, _c in rows:
                if t.casefold() not in names_ok and str(bit) not in names_ok:
                    d.unexpected.append("зона «%s» %s, а в очікуваному її нема" % (t, kind))
        for bit, t, desc in d.zones_changed:
            real = [x for x in desc if not x.startswith("↳")]
            if real and t.casefold() not in names_ok and str(bit) not in names_ok:
                d.unexpected.append("зона «%s» змінилась (%s), а в очікуваному її нема" % (t, "; ".join(real)))
        for lbl, rows in (("з'явився", d.contacts_added), ("зник", d.contacts_removed)):
            for n, t in rows:
                if n not in expected.contacts:
                    d.unexpected.append("контакт №%d «%s» %s, а в очікуваному його нема" % (n, t, lbl))
        for n, t, f in d.contacts_changed:
            if n not in expected.contacts:
                d.unexpected.append("контакт №%d «%s» змінився (%s), а в очікуваному його нема" % (n, t, ", ".join(f)))
        for lbl, rows in (("TG-список", d.groups_changed), ("APRS-слот", d.aprs_changed), ("DTMF-контакт", d.dtmf_changed)):
            for n, t in rows:
                d.unexpected.append("%s №%d: %s -- операції над каналами, зонами й контактами цього не чіпають" % (lbl, n, t))
    return d
