# -*- coding: utf-8 -*-
"""R45 V1: цілісність кодплага -- чи не лишилось у ньому ВИСЯЧИХ посилань.

Навіщо. Прошивка не перевіряє, чи існує те, на що посилається запис: зона бере номер каналу зі списку й читає запис за номером (R41: сміття), канал бере контакт
за номером і читає стертий слот (R44: ім'я 0xFF, TG 0), позиція «останній канал у зоні» (LUCZ) виходить за список і дає чужий номер. Каскади в R41/R44 закривають це для
операцій з рації, але стокове CPS, ручна правка чи обрив живлення можуть лишити вади. Цей модуль лише ЧИТАЄ образ (`cps_csv.Image`) і називає КОНКРЕТНЕ місце вади.
Нічого не виправляє (V3.2): виправлення -- через CPS (відкрити кодплаг, виправити поле, записати назад), підказка -- у `hint()`.

Без Tk і без рації: вхід -- `cps_csv.Image` (з прочитаного кодплага або з файла). Адреси й розкладки -- з `cps_link`/`cps_csv`/`claude/codeplug-map.md`:
  канал 56 Б: контакт u16 LE на зсуві 46 (1..1024, 0 -- «Немає»), TG-список u8 на 43 (1..76), APRS u8 на 45 (1..8); маска «канал у роботі» -- 8 банків по 128;
  зона: name[16] + channels u16 LE [16 або 80] -- ЩІЛЬНИЙ список до першого нуля (R43 виймає зі зсувом саме тому); маска зон 0x8010 (68 бітів);
  VFO A/B -- EEPROM 0x7590/0x75C8, той самий запис 56 Б; налаштування рації -- 0x604B (магія 0x4780, currentZone на зсуві 58); LUCZ -- 0x6000 (тег, потім байт на зону)."""
import struct

import codeplug_view as cv
import cps_csv as cc
import cps_link as cl

CHANNELS_MAX = cl.CP_CHANNELS_BANKS * cl.CP_CHANNELS_PER_BANK      # 1024
ADDR_VFO = (0x7590, 0x75C8)                                        # vfo_edit.ADDR_VFO_A/B (звіряється в test_r45)
VFO_NAMES = ("VFO A", "VFO B")
LUCZ_ADDR = 0x6000                                                 # codeplug.h: CODEPLUG_ADDR_LUCZ
LUCZ_BYTES = 70
LUCZ_ALL_SLOT = 68
SETTINGS_EE_ADDR = 0x6000 + 0x4B
SETTINGS_MAGIC = 0x4780
SETTINGS_OFF_CURRENT_ZONE = 58

SHOW = 8                  # скільки місць називати у звіті; решта -- лічильником

# --- як виправляти (V3.1). Автоматично нічого не виправляється ---
HINTS = {
    "V1.1": "Через CPS: розділ «Зони» -> зона -> прибрати номер каналу, якого нема (або створити канал із цим номером) -> записати в рацію. На рації: «Кодплаг» -> «Зони» -> зона -> «Канали зони» -> вийняти.",
    "V1.2": "Через CPS: розділ «Зони» -> зона -> перенести канали до початку списку без порожніх місць -> записати в рацію. Прошивка бачить зону лише до першого порожнього місця.",
    "V1.3": "Через CPS: розділ «Канали» -> у колонці «Контакт» вибрати існуючий контакт або «None» для цього каналу -> записати в рацію (або створити контакт із цим номером у розділі «Контакти»).",
    "V1.4": "Через CPS: розділ «Канали» -> колонка «TG List» -> існуючий список або «None»; для списку прийому -- розділ «TG-списки» -> прибрати контакт, якого нема -> записати в рацію.",
    "V1.5": "Через CPS: розділ «Канали» -> колонка «APRS» -> існуючий слот або «None» -> записати в рацію.",
    "V1.6": "VFO міняється на рації (екран VFO) або в розділі «VFO» CPS: вибрати існуючий контакт/список або «Немає» -> записати в рацію.",
    "V1.7": "Через CPS: розділ «Канали» -> дописати канал (назва, частоти) або видалити його з кодплага; посилання на канал поза маскою прибрати із зони. Якщо «Всі канали» посилаються на стертий канал -- на рації перемкнути канал, рація перепише позицію сама.",
    "V1.8": "Через CPS: розділ «Зони» -> дати зоні назву; поточну зону на рації вибрати заново (меню «Зони»), «останній канал у зоні» перепишеться при вимкненні рації.",
}


class Check:
    """Результат однієї перевірки: скільки об'єктів перевірено, які знайдено проблеми (кожна -- з конкретним місцем), довідкові примітки."""
    __slots__ = ("cid", "title", "checked", "unit", "problems", "notes")

    def __init__(self, cid, title, unit):
        self.cid, self.title, self.unit = cid, title, unit
        self.checked = 0
        self.problems = []
        self.notes = []

    @property
    def ok(self):
        return not self.problems

    def summary(self):
        return "перевірено %d %s, проблем: %d" % (self.checked, self.unit, len(self.problems))

    def places(self, limit=SHOW):
        """Рядок із конкретними місцями проблем (перші `limit`, далі лічильник)."""
        if not self.problems:
            return ""
        txt = "; ".join(self.problems[:limit])
        if len(self.problems) > limit:
            txt += "; ... і ще %d" % (len(self.problems) - limit)
        return txt


# =============================================================================================================================
#  Модель: одне читання образу, на якому працюють усі перевірки
# =============================================================================================================================

def _name(raw16):
    try:
        return cc.readable_text(bytes(raw16)).strip() or "?"
    except Exception:  # noqa: BLE001 -- назва лише для підпису місця
        return "?"


class Model:
    def __init__(self, img):
        self.img = img
        self.fmt = img.zone_format()
        self.chan = {n: rec for n, rec in img.channels()}                       # канали за маскою "в роботі": номер -> запис 56 Б
        self.bad = {n for n, rec in self.chan.items() if _meaningful(rec)}      # записи в масці без назви/частот/режиму -- V1.7; V1.3-V1.5 їх не читають (там сміття)
        self.contacts = {slot + 1 for slot, _r in img.contacts()}               # існуючі контакти (name[0] != 0xFF, як кеш прошивки)
        self.contact_rec = {slot + 1: rec for slot, rec in img.contacts()}
        self.groups = {slot + 1: (rec, ln) for slot, rec, ln in img.groups()}   # існуючі TG-списки
        self.aprs_count = len(img.aprs())                                       # слоти APRS підряд з №1
        self.zones = []                                                         # [{bit, ord, name, vals, visible, tail}]
        for ordinal, (bit, rec) in enumerate(img.zones()):
            vals = list(struct.unpack_from("<%dH" % self.fmt, rec, 16))
            z = vals.index(0) if 0 in vals else len(vals)
            self.zones.append({"bit": bit, "ord": ordinal, "name": _name(rec[:16]), "raw0": rec[0], "vals": vals, "visible": vals[:z],
                               "tail": [(p, v) for p, v in enumerate(vals) if p > z and v != 0], "hole": z if z < len(vals) else None})
        ee = img.eeprom
        self.settings = None
        self.lucz = None
        if len(ee) >= SETTINGS_EE_ADDR + SETTINGS_OFF_CURRENT_ZONE + 2 and struct.unpack_from("<I", ee, SETTINGS_EE_ADDR)[0] == SETTINGS_MAGIC:
            self.settings = {"currentZone": struct.unpack_from("<h", ee, SETTINGS_EE_ADDR + SETTINGS_OFF_CURRENT_ZONE)[0]}
        if len(ee) >= LUCZ_ADDR + 4 + LUCZ_BYTES and bytes(ee[LUCZ_ADDR:LUCZ_ADDR + 4]) == b"LUCZ":
            self.lucz = bytes(ee[LUCZ_ADDR + 4:LUCZ_ADDR + 4 + LUCZ_BYTES])

    def vfo(self, k):
        """Запис VFO або None, якщо область порожня (0xFF -- кодплаг без VFO)."""
        rec = self.img.ee(ADDR_VFO[k], cl.CP_CHANNEL_SIZE)
        return None if rec == b"\xff" * cl.CP_CHANNEL_SIZE else rec

    @staticmethod
    def contact_of(rec):
        return rec[cc.O_CONTACT] | (rec[cc.O_CONTACT + 1] << 8)

    @staticmethod
    def digital(rec):
        return rec[cc.O_MODE] != 0

    def zone_label(self, z):
        return "зона «%s» (№%d у списку, біт %d)" % (z["name"], z["ord"] + 1, z["bit"])

    def chan_label(self, n):
        rec = self.chan.get(n)
        return "канал №%d «%s»" % (n, _name(rec[:16])) if rec is not None else "канал №%d" % n


# =============================================================================================================================
#  Перевірки
# =============================================================================================================================

def v1_1(m):
    """Зони -> канали: кожен номер у ВИДИМОМУ списку зони (до першого нуля) є в масці «канал у роботі»."""
    c = Check("V1.1", "зони → канали", "посилань")
    for z in m.zones:
        for pos, n in enumerate(z["visible"]):
            c.checked += 1
            if n > CHANNELS_MAX:
                c.problems.append("%s, позиція %d: номер %d поза межами 1..%d" % (m.zone_label(z), pos + 1, n, CHANNELS_MAX))
            elif n not in m.chan:
                c.problems.append("%s, позиція %d: канал №%d поза маскою (його нема в кодплазі)" % (m.zone_label(z), pos + 1, n))
    c.notes.append("зон: %d, формат %d каналів у зоні" % (len(m.zones), m.fmt))
    return c


def v1_2(m):
    """Щільність списків: канали зони йдуть підряд з початку, після першого нуля -- лише нулі."""
    c = Check("V1.2", "щільність списків зон", "зон")
    for z in m.zones:
        c.checked += 1
        if z["tail"]:
            p, v = z["tail"][0]
            c.problems.append("%s: порожнє місце на позиції %d, а далі (позиція %d) стоїть канал №%d -- прошивка його не побачить (усього за дірою: %d)" % (
                m.zone_label(z), z["hole"] + 1, p + 1, v, len(z["tail"])))
    return c


def v1_3(m):
    """Канали -> контакти: цифровий канал із контактом вказує на ІСНУЮЧИЙ контакт (після R44 видалений контакт замінюється на «Немає» = 0)."""
    c = Check("V1.3", "канали → контакти", "цифрових каналів")
    analog_refs = 0
    skipped = 0
    for n in sorted(m.chan):
        rec = m.chan[n]
        if n in m.bad:
            skipped += 1
            continue
        k = m.contact_of(rec)
        if not m.digital(rec):
            analog_refs += 1 if k else 0
            continue
        c.checked += 1
        if k == 0:
            continue
        if k > cl.CP_CONTACTS_MAX:
            c.problems.append("%s: контакт №%d поза межами 1..%d" % (m.chan_label(n), k, cl.CP_CONTACTS_MAX))
        elif k not in m.contacts:
            c.problems.append("%s: контакт №%d стертий (рація прочитає ім'я 0xFF і TG 0; має бути «Немає»)" % (m.chan_label(n), k))
    if analog_refs:
        c.notes.append("аналогових каналів з ненульовим полем «контакт»: %d (рація їх не читає, не проблема)" % analog_refs)
    if skipped:
        c.notes.append("пропущено каналів з неосмисленим записом: %d (див. V1.7)" % skipped)
    return c


def v1_4(m):
    """Канали -> списки прийому (+ списки прийому -> контакти: та сама вада з іншого боку)."""
    c = Check("V1.4", "канали → списки прийому", "посилань")
    analog_refs = 0
    skipped = 0
    for n in sorted(m.chan):
        rec = m.chan[n]
        if n in m.bad:
            skipped += 1
            continue
        g = rec[cc.O_GROUP]
        if g == 0:
            continue
        if not m.digital(rec):
            analog_refs += 1
            continue
        c.checked += 1
        if g > cl.CP_RXGROUPS_MAX:
            c.problems.append("%s: список прийому №%d поза межами 1..%d" % (m.chan_label(n), g, cl.CP_RXGROUPS_MAX))
        elif g not in m.groups:
            c.problems.append("%s: список прийому №%d порожній або стертий" % (m.chan_label(n), g))
    for slot, (rec, ln) in sorted(m.groups.items()):
        for k in range(ln):
            v = rec[16 + 2 * k] | (rec[17 + 2 * k] << 8)
            if v == 0:
                break
            c.checked += 1
            if v > cl.CP_CONTACTS_MAX or v not in m.contacts:
                c.problems.append("список прийому №%d «%s», позиція %d: контакт №%d стертий" % (slot, _name(rec[:16]), k + 1, v))
    if analog_refs:
        c.notes.append("аналогових каналів з ненульовим полем «TG-список»: %d (рація їх не читає, не проблема)" % analog_refs)
    if skipped:
        c.notes.append("пропущено каналів з неосмисленим записом: %d (див. V1.7)" % skipped)
    c.notes.append("списків прийому: %d" % len(m.groups))
    return c


def v1_5(m):
    """Канали -> слоти APRS (колонка «APRS» актуальна і для аналогових, і для цифрових)."""
    c = Check("V1.5", "канали → слоти APRS", "каналів")
    skipped = 0
    for n in sorted(m.chan):
        if n in m.bad:
            skipped += 1
            continue
        a = m.chan[n][cc.O_APRS]
        c.checked += 1
        if a == 0:
            continue
        if a > cc.APRS_MAX or a > m.aprs_count:
            c.problems.append("%s: слот APRS №%d, а дійсних слотів підряд з №1 лише %d" % (m.chan_label(n), a, m.aprs_count))
    if skipped:
        c.notes.append("пропущено каналів з неосмисленим записом: %d (див. V1.7)" % skipped)
    return c


def v1_6(m):
    """Обидва VFO не посилаються на стерті контакти чи списки (VFO -- той самий запис 56 Б, у EEPROM 0x7590/0x75C8)."""
    c = Check("V1.6", "VFO", "VFO")
    for k in (0, 1):
        rec = m.vfo(k)
        if rec is None:
            c.notes.append("%s: у кодплазі порожній (0xFF) -- рація візьме значення за замовчуванням" % VFO_NAMES[k])
            continue
        c.checked += 1
        if m.digital(rec):
            ct = m.contact_of(rec)
            if ct and (ct > cl.CP_CONTACTS_MAX or ct not in m.contacts):
                c.problems.append("%s: контакт №%d стертий або поза межами" % (VFO_NAMES[k], ct))
            g = rec[cc.O_GROUP]
            if g and (g > cl.CP_RXGROUPS_MAX or g not in m.groups):
                c.problems.append("%s: список прийому №%d порожній або стертий" % (VFO_NAMES[k], g))
        a = rec[cc.O_APRS]
        if a and (a > cc.APRS_MAX or a > m.aprs_count):
            c.problems.append("%s: слот APRS №%d, а дійсних лише %d" % (VFO_NAMES[k], a, m.aprs_count))
    return c


def _meaningful(rec):
    """Чому запис каналу НЕосмислений (список причин; порожній -- осмислений)."""
    why = []
    if rec[0] in (0x00, 0xFF):
        why.append("нема назви")
    for label, off in (("RX", cc.O_RX), ("TX", cc.O_TX)):
        f = cv.freq_bcd_le(rec[off:off + 4])
        if f is None:
            why.append("частота %s не BCD (%s)" % (label, bytes(rec[off:off + 4]).hex()))
        elif f == 0:
            why.append("частота %s нульова" % label)
    if rec[cc.O_MODE] not in (0, 1):
        why.append("режим %d (очікувалось 0 -- FM, 1 -- DMR)" % rec[cc.O_MODE])
    return why


def v1_7(m):
    """Маска проти записів: канал у масці має осмислений запис; канал поза маскою ніде не згадується (зони, «Всі канали» в налаштуваннях)."""
    c = Check("V1.7", "маска проти записів", "каналів у масці")
    for n in sorted(m.chan):
        c.checked += 1
        why = _meaningful(m.chan[n])
        if why:
            c.problems.append("канал №%d у масці, але запис неосмислений: %s" % (n, ", ".join(why)))
    mentions = {}
    for z in m.zones:
        for pos, n in enumerate(z["vals"]):
            if n and 1 <= n <= CHANNELS_MAX and n not in m.chan:
                mentions.setdefault(n, []).append("%s, позиція %d" % (m.zone_label(z), pos + 1))
    if m.lucz is not None and m.settings is not None and m.settings["currentZone"] == len(m.zones):
        n = struct.unpack_from("<h", m.lucz, LUCZ_ALL_SLOT)[0] + 1
        if 1 <= n <= CHANNELS_MAX and n not in m.chan:
            mentions.setdefault(n, []).append("«Всі канали» -- останній канал (LUCZ)")
    for n in sorted(mentions):
        c.problems.append("канал №%d поза маскою, але згаданий: %s" % (n, "; ".join(mentions[n][:3]) + ("; ..." if len(mentions[n]) > 3 else "")))
    c.notes.append("каналів у масці: %d" % len(m.chan))
    return c


def v1_8(m):
    """Зони в масці: зона має назву; поточна зона з налаштувань існує; «останній канал у зоні» (LUCZ) не виходить за список."""
    c = Check("V1.8", "зони в масці", "зон")
    for z in m.zones:
        c.checked += 1
        if z["raw0"] in (0x00, 0xFF):
            c.problems.append("%s: немає назви" % m.zone_label(z))
    if m.settings is None:
        c.notes.append("налаштування рації в EEPROM не записані (магія не збігається) -- поточну зону не перевіряю")
    else:
        cz = m.settings["currentZone"]
        c.checked += 1
        if not (0 <= cz <= len(m.zones)):
            c.problems.append("налаштування: поточна зона №%d, а зон у масці %d (допустимо 0..%d, остання -- «Всі канали»)" % (cz, len(m.zones), len(m.zones)))
    if m.lucz is None:
        c.notes.append("запису «останній канал у зоні» (тег LUCZ) нема -- позиції не перевіряю")
    else:
        for z in m.zones:
            if z["bit"] >= LUCZ_ALL_SLOT:
                continue
            cnt = len(z["visible"])
            idx = m.lucz[z["bit"]]
            if cnt and idx >= cnt:
                c.problems.append("%s: збережена позиція %d, а каналів у зоні %d (рація візьме чужий номер)" % (m.zone_label(z), idx + 1, cnt))
        cz = m.settings["currentZone"] if m.settings else None
        n = struct.unpack_from("<h", m.lucz, LUCZ_ALL_SLOT)[0] + 1
        if not (1 <= n <= CHANNELS_MAX) or n not in m.chan:
            msg = "«Всі канали»: збережено канал №%d, якого в кодплазі нема" % n
            if cz is not None and cz == len(m.zones):
                c.problems.append(msg + " (і це ПОТОЧНА зона)")
            else:
                c.notes.append(msg + " (зона не поточна)")
    return c


CHECKS = (v1_1, v1_2, v1_3, v1_4, v1_5, v1_6, v1_7, v1_8)


def run_checks(img):
    """Усі перевірки V1 на образі. Лише читання."""
    m = Model(img)
    return [f(m) for f in CHECKS]


def hint(checks):
    """V3.1: для кожної знайденої проблеми -- якою дією вона виправляється (рядки без повторів, у порядку перевірок)."""
    out = []
    for c in checks:
        if c.problems and c.cid in HINTS:
            out.append("%s %s: %s" % (c.cid, c.title, HINTS[c.cid]))
    return out
