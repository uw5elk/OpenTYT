# -*- coding: utf-8 -*-
"""reorder.py -- R53: змінити ПОРЯДОК каналів, зон, контактів і списків прийому в образі кодплага. ЛОГІКА без Tk і без рації.

Чому не через CSV (table_edit.py): імпорт CSV зіставляє рядки за НАЗВАМИ й займає ті самі слоти, тож порядок слотів ним не змінити. Тут правка іде
прямо по образу (cps_csv.Image) і є ПЕРЕСТАНОВКОЮ ВМІСТУ ЗАЙНЯТИХ СЛОТІВ:

  * множина зайнятих слотів (маска каналів, маска зон, довжини списків, дірки) НЕ змінюється -- змінюється лише те, який запис у якому слоті лежить;
  * тому посилання на «порожній» номер як були порожніми, так і лишаються: після перестановки вони ніколи не вказують на неіснуючий елемент;
  * усі посилання на переставлені записи перераховуються (карта посилань -- claude/r53-result.md, F1).

Що перераховується (ідентичність запису: канал -- номер; контакт і список прийому -- слот+1; зона -- біт маски):
  канал   -> номери каналів у зонах; LUCZ «Всіх каналів» (int16 = номер-1, EEPROM 0x6048);
  контакт -> номери контактів у списках прийому; O_CONTACT у каналах (усіх режимів) і в VFO A / VFO B;
  список  -> O_GROUP у каналах (усіх режимів) і в VFO A / VFO B;
  зона    -> LUCZ зони (байт за БІТОМ, EEPROM 0x6004+біт); `currentZone` (ОРДИНАЛ, 0x604B+58) -- щоб активною лишилась та сама зона.
Чого CPS виправити не може: квіккеї 0x7524..0x7537 -- запис у рацію їх не переписує (прошивка свідомо), тож образ їх не чіпає, а користувачу
показується попередження, які клавіші можуть розійтись.

LUCZ і `currentZone` правляться лише коли вони в образі справжні (тег "LUCZ" на 0x6000, магічне число налаштувань 0x4780 на 0x604B): інакше прошивка їх
однаково ігнорує/скидає, і вигадувати там нічого не треба."""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cps_csv as cc  # noqa: E402
import cps_link as cl  # noqa: E402
import table_edit as te  # noqa: E402
import vfo_edit as ve  # noqa: E402

KINDS = ("channel", "contact", "tg", "zone")
SECTIONS = {"channel": "Канали", "contact": "Контакти", "tg": "Списки прийому", "zone": "Зони"}

LUCZ_ADDR = 0x6000
LUCZ_TAG = b"LUCZ"
LUCZ_DATA = LUCZ_ADDR + 4
LUCZ_ALL_OFFSET = 68                    # codeplugGetLastUsedChannelInZone(-1): SAFE_MIN(-1, 68u) = 68 -> int16 на 0x6004 + 68
SETTINGS_ADDR = 0x604B
SETTINGS_MAGIC = 0x4780                 # settings.c: STORAGE_MAGIC_NUMBER
CURRENT_ZONE_OFFSET = 58                # nonVolatileSettings.currentZone (виміряно gcc, R39; MDUV380: LOG_GPS_DATA увімкнено)
QUICKKEYS_ADDR = 0x7524
QUICKKEYS_N = 10
LOG_LINES_MAX = 6                       # скільки переміщень описувати поштучно (далі -- одним рядком)


class ReorderError(te.TableEditError):
    """Перестановку відхилено ДО будь-якої зміни."""


# ---------------------------------------------------------------------------------------------------------------------------------
#  Перелік у порядку слотів
# ---------------------------------------------------------------------------------------------------------------------------------

def idents(img, kind):
    """Ідентифікатори записів у ПОРЯДКУ СЛОТІВ (так само їх показують усі таблиці): канал -- номер; контакт, список -- слот (0-based); зона -- біт."""
    if kind == "channel":
        return [n for n, _r in img.channels()]
    if kind == "contact":
        return [s for s, _r in img.contacts()]
    if kind == "tg":
        return [s for s, _r, _l in img.groups()]
    if kind == "zone":
        return [b for b, _r in img.zones()]
    raise ReorderError(["невідомий вид запису: %r" % (kind,)])


def _names(img, kind):
    return dict(te.entity_names(img, kind))


def _label(kind, ident, name):
    if kind == "channel":
        return "№%d «%s»" % (ident, name)
    if kind in ("contact", "tg"):
        return "№%d «%s»" % (ident + 1, name)
    return "«%s»" % name


def _u16(buf, off):
    return buf[off] | (buf[off + 1] << 8)


# ---------------------------------------------------------------------------------------------------------------------------------
#  Квіккеї (лише читання: запис у рацію їх не переписує)
# ---------------------------------------------------------------------------------------------------------------------------------

def quickkeys(img):
    """[(клавіша 0..9, значення)] непорожніх квіккеїв за правилом прошивки (quickkeyIsEmpty): 0x8000 і «контакт» поза 1..1024 -- порожні; 0xFFFF -- стерта EEPROM."""
    out = []
    for k in range(QUICKKEYS_N):
        v = _u16(img.ee(QUICKKEYS_ADDR, 2 * QUICKKEYS_N), 2 * k)
        if v in (0x8000, 0xFFFF):
            continue
        if not v & 0x8000 and not 1 <= v <= 1024:
            continue
        out.append((k, v))
    return out


# ---------------------------------------------------------------------------------------------------------------------------------
#  LUCZ і налаштування
# ---------------------------------------------------------------------------------------------------------------------------------

def lucz_present(img):
    return img.ee(LUCZ_ADDR, 4) == LUCZ_TAG


def lucz_zone(img, bit):
    """Позиція «останнього каналу» в зоні з бітом bit (байт) або None, якщо блоку LUCZ у кодплазі нема."""
    return img.ee(LUCZ_DATA + bit, 1)[0] if lucz_present(img) else None


def lucz_all_channels(img):
    """Номер «останнього каналу» у «Всіх каналах» або None."""
    if not lucz_present(img):
        return None
    return struct.unpack("<h", img.ee(LUCZ_DATA + LUCZ_ALL_OFFSET, 2))[0] + 1


def settings_valid(img):
    return struct.unpack("<I", img.ee(SETTINGS_ADDR, 4))[0] == SETTINGS_MAGIC


def current_zone(img):
    """Ординал активної зони (n-й зайнятий біт; «Всі канали» = кількість зон) або None, якщо налаштувань у кодплазі нема / значення поза межами."""
    if not settings_valid(img):
        return None
    v = struct.unpack("<h", img.ee(SETTINGS_ADDR + CURRENT_ZONE_OFFSET, 2))[0]
    return v if v >= 0 else None


def _set_current_zone(img, ordinal):
    img.set_ee(SETTINGS_ADDR + CURRENT_ZONE_OFFSET, struct.pack("<h", ordinal))


# ---------------------------------------------------------------------------------------------------------------------------------
#  Перерахунок посилань
# ---------------------------------------------------------------------------------------------------------------------------------

def _remap_zone_members(img, nm):
    """Номери каналів у списках усіх зон (щільна частина до першого 0). Повертає число змінених зон."""
    n = img.zone_format()
    changed = 0
    for bit, rec in img.zones():
        rec = bytearray(rec)
        dirty = False
        for k in range(n):
            v = _u16(rec, 16 + 2 * k)
            if v == 0:
                break
            if v in nm and nm[v] != v:
                struct.pack_into("<H", rec, 16 + 2 * k, nm[v])
                dirty = True
        if dirty:
            img.set_zone(bit, bytes(rec))
            changed += 1
    return changed


def _remap_group_members(img, nm):
    """Номери контактів у списках прийому. Повертає число змінених списків."""
    changed = 0
    for slot, rec, ln in img.groups():
        rec = bytearray(rec)
        dirty = False
        for k in range(ln):
            v = _u16(rec, 16 + 2 * k)
            if v == 0:
                break
            if v in nm and nm[v] != v:
                struct.pack_into("<H", rec, 16 + 2 * k, nm[v])
                dirty = True
        if dirty:
            img.set_group(slot, bytes(rec), ln)
            changed += 1
    return changed


def _fixer(off, two, nm):
    def fix(rec):
        v = _u16(rec, off) if two else rec[off]
        if v in nm and nm[v] != v:
            if two:
                struct.pack_into("<H", rec, off, nm[v])
            else:
                rec[off] = nm[v]
            return True
        return False
    return fix


def _remap_channels_field(img, off, two, nm):
    """Поле-посилання (uint16 або uint8) у записах УСІХ каналів (і аналогових: там воно «не діє», але лишається в записі). Повертає число змінених каналів."""
    fix = _fixer(off, two, nm)
    chans = 0
    for num, rec in img.channels():
        rec = bytearray(rec)
        if fix(rec):
            img.set_channel_rec(num, bytes(rec))
            chans += 1
    return chans


def _remap_vfo_field(img, off, two, nm):
    """Те саме у VFO A / VFO B (власні 56-Б записи в EEPROM). Повертає число змінених VFO."""
    fix = _fixer(off, two, nm)
    vfos = 0
    for n in (0, 1):
        rec = bytearray(ve.vfo_rec(img, n))
        if fix(rec):
            img.set_ee(ve.vfo_addr(n), bytes(rec))
            vfos += 1
    return vfos


def _vfo_text(count):
    return "" if not count else ", VFO: %d" % count


# ---------------------------------------------------------------------------------------------------------------------------------
#  Перестановка
# ---------------------------------------------------------------------------------------------------------------------------------

def _problems(kind, old, new_order):
    if kind not in KINDS:
        return ["невідомий вид запису: %r" % (kind,)]
    if len(set(new_order)) != len(new_order):
        return ["новий порядок містить повторення -- перестановку не виконано"]
    if sorted(new_order) != sorted(old):
        return ["новий порядок не збігається з наявними записами (є зайві або бракує) -- перестановку не виконано"]
    return []


def permute(img, kind, new_order):
    """Новий образ, у якому записи виду kind стоять у порядку new_order (список ЇХНІХ ТЕПЕРІШНІХ ідентифікаторів). Усі посилання перераховано.
    Образ-аргумент не змінюється. Помилка -- ReorderError (нічого не змінено)."""
    new_order = list(new_order)
    old = idents(img, kind)
    bad = _problems(kind, old, new_order)
    if bad:
        raise ReorderError(bad)
    res = cc.ImportResult()
    out = cc.Image(img.eeprom, img.flash, img.base)
    res.image = out
    mapping = {ident: old[k] for k, ident in enumerate(new_order)}        # було -> стало
    moved = {a: b for a, b in mapping.items() if a != b}
    if not moved:
        return res
    names = _names(img, kind)
    section = SECTIONS[kind]
    lines = []
    for a, b in sorted(moved.items(), key=lambda x: x[1]):
        if kind == "zone":
            lines.append("«%s»: місце %d -> %d" % (names.get(a, ""), old.index(a) + 1, old.index(b) + 1))
        else:
            lines.append("%s -> %s" % (_label(kind, a, names.get(a, "")), _label(kind, b, names.get(a, "")).split(" ")[0]))
    if len(lines) <= LOG_LINES_MAX:
        for ln in lines:
            res.changed.append((section, ln))
    else:
        res.changed.append((section, "змінено порядок: переставлено %d записів" % len(lines)))
    {"channel": _permute_channels, "contact": _permute_contacts, "tg": _permute_groups, "zone": _permute_zones}[kind](img, out, mapping, moved, old, res)
    return res


def _permute_channels(src, out, mapping, moved, old, res):
    recs = {n: src.channel_rec(n) for n in moved}
    for a, b in moved.items():
        out.set_channel_rec(b, recs[a])
    zones = _remap_zone_members(out, mapping)
    if zones:
        res.changed.append(("Зони", "оновлено номери каналів у зонах: %d" % zones))
    _fix_lucz_all(out, mapping, res)


def _permute_contacts(src, out, mapping, moved, old, res):
    recs = {s: src.fl(cl.CP_ADDR_CONTACTS + s * cl.CP_CONTACT_SIZE, cl.CP_CONTACT_SIZE) for s in moved}
    for a, b in moved.items():
        out.set_contact(b, recs[a])
    nm = {a + 1: b + 1 for a, b in mapping.items()}
    groups = _remap_group_members(out, nm)
    chans = _remap_channels_field(out, cc.O_CONTACT, True, nm)
    vfos = _remap_vfo_field(out, cc.O_CONTACT, True, nm)
    res.changed.append(("Посилання", "контакти: списків прийому %d, каналів %d%s" % (groups, chans, _vfo_text(vfos))))
    names = _names(out, "contact")
    for key, v in quickkeys(src):
        if not v & 0x8000 and (v - 1) in moved:
            res.warnings.append("Квіккей «%d» вказує на контакт №%d: запис у рацію квіккеї НЕ змінює, тож після запису ця клавіша викличе контакт №%d «%s» "
                                "(раніше -- «%s»). Перепризначте клавішу на рації." % (key, v, v, names.get(v - 1, ""), _names(src, "contact").get(v - 1, "")))


def _permute_groups(src, out, mapping, moved, old, res):
    lens = {s: (rec, ln) for s, rec, ln in src.groups()}
    for a, b in moved.items():
        out.set_group(b, lens[a][0], lens[a][1])
    nm = {a + 1: b + 1 for a, b in mapping.items()}
    chans = _remap_channels_field(out, cc.O_GROUP, False, nm)
    vfos = _remap_vfo_field(out, cc.O_GROUP, False, nm)
    res.changed.append(("Посилання", "списки прийому: каналів %d%s" % (chans, _vfo_text(vfos))))


def _permute_zones(src, out, mapping, moved, old, res):
    recs = dict(src.zones())
    for a, b in moved.items():
        out.set_zone(b, recs[a])
    _fix_lucz_zones(src, out, moved)
    _fix_current_zone(src, out, mapping, old, res)
    menu_keys = [k for k, v in quickkeys(src) if v & 0x8000]
    if menu_keys:
        res.warnings.append("Є квіккеї меню (клавіші: %s). Деякі з них -- позиції у списку «Зони». Запис у рацію квіккеї НЕ змінює, тож вони можуть "
                            "відкрити іншу зону. Перевірте їх на рації." % ", ".join(str(k) for k in menu_keys))


def _fix_lucz_all(out, mapping, res):
    """LUCZ «Всіх каналів»: int16 = номер-1 -> номер того самого каналу."""
    cur = lucz_all_channels(out)
    if cur is not None and cur in mapping and mapping[cur] != cur:
        out.set_ee(LUCZ_DATA + LUCZ_ALL_OFFSET, struct.pack("<h", mapping[cur] - 1))
        res.changed.append(("Налаштування", "«Всі канали»: останній канал тепер №%d (той самий канал)" % mapping[cur]))


def _fix_lucz_zones(src, out, moved):
    """LUCZ зон: байт за БІТОМ (позиція в списку зони) їде разом із записом зони."""
    if not lucz_present(src):
        return
    luczs = {b: lucz_zone(src, b) for b in moved}
    for a, b in moved.items():
        out.set_ee(LUCZ_DATA + b, bytes([luczs[a]]))


def _fix_current_zone(src, out, mapping, old, res):
    """currentZone -- ОРДИНАЛ: після перестановки активною лишається та сама зона (за вмістом), а не та, що опинилась на тому ж місці."""
    cur = current_zone(src)
    if cur is not None and cur < len(old):
        new_cur = old.index(mapping[old[cur]])
        if new_cur != cur:
            _set_current_zone(out, new_cur)
            res.changed.append(("Налаштування", "активна зона: місце %d -> %d (та сама зона)" % (cur + 1, new_cur + 1)))


# ---------------------------------------------------------------------------------------------------------------------------------
#  Зручні обгортки: крок і перенесення на місце
# ---------------------------------------------------------------------------------------------------------------------------------

def move_order(img, kind, ident, step):
    """Новий порядок при зсуві запису на step позицій (±1) серед ЗАЙНЯТИХ. На межі -- порядок не змінюється."""
    order = idents(img, kind)
    if ident not in order:
        raise ReorderError(["запису нема в кодплазі (можливо, його вже видалено)"])
    i = order.index(ident)
    j = max(0, min(len(order) - 1, i + step))
    new = list(order)
    new.insert(j, new.pop(i))
    return new


def move(img, kind, ident, step):
    """Підняти (step < 0) або опустити (step > 0) запис на step позицій. Повертає ImportResult."""
    return permute(img, kind, move_order(img, kind, ident, step))


def move_to(img, kind, ident, target):
    """Перенести запис ident на місце, яке зараз займає запис target (перетягування мишею)."""
    order = idents(img, kind)
    if ident not in order or target not in order:
        raise ReorderError(["запису нема в кодплазі (можливо, його вже видалено)"])
    new = list(order)
    new.insert(order.index(target), new.pop(order.index(ident)))
    return permute(img, kind, new)


def ident_after_move(img, kind, ident, step=None, target=None):
    """Ідентифікатор, який матиме запис ПІСЛЯ переміщення (слот того місця, куди він став); для виділення в таблиці."""
    order = idents(img, kind)
    if ident not in order:
        return None
    if target is not None and target in order:
        return target
    return order[max(0, min(len(order) - 1, order.index(ident) + (step or 0)))]
