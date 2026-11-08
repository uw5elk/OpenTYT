#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""roam_cfg.py -- R59: налаштування «Роумінгу» (автоперехід на наступний канал зі списку, коли ретранслятор не відповідає на пробудження під PTT).

Що де лежить (одне джерело істини для кожного):
  * СПИСКИ роумінгу (R60: їх 10) -- НОМЕР СПИСКУ каналу (0 = жодного, 1..10) У КОДПЛАЗІ, у байті 37 запису каналу з міткою: 0xC0 | N. Канал належить
    ОДНОМУ списку. Редагується як решта кодплага: колонка «Роум. список» у «Каналах», колонка «RoamList» у CSV, розділ «Роумінг»; у рацію потрапляє дією
    «Записати кодплаг у рацію». Радіо редагує ті самі списки з меню «Роумінг» (запис ОДНОГО запису каналу). Формат дзеркалить roam_cfg.h (прошивка).
    СТАРИЙ прапорець R59 (CHANNEL_FLAG_ROAMING, LibreDMR_flag1 0x01) прошивка R60 не читає: CPS одноразово переносить його в список 1 (з підтвердженням).
  * НАЛАШТУВАННЯ -- custom-data блок типу 15 (CODEPLUG_CUSTOM_DATA_TYPE_ROAM_CFG), 8 байтів, поза кодплагом: пишеться в рацію негайно власною кнопкою.
    Блока немає (нова/нечіпана рація) -- автоперехід ВИМКНЕНО, макс. стрибків 2 (так само читає прошивка).

Формат блока (дзеркалить application/include/functions/roam_cfg.h; міняючи тут, змінюй там):
    0..3 "ROAM" | 4 версія=1 | 5 enabled (0/1) | 6 maxHops (1..5; поза межами прошивка читає як 2) | 7 резерв=0

Блок існує лише в збірках прошивки з -DENABLE_ROAM_RETRY; у інших збірках прошивка його не читає (і не псує: невідомий тип блока просто пропускається).

Використання (рація ввімкнена ЗВИЧАЙНО, не в DFU):
  python3 roam_cfg.py --show
  python3 roam_cfg.py --enable --hops 3
  python3 roam_cfg.py --disable
"""
import argparse
import datetime
import os
import struct
import sys

TYPE_ROAM_CFG = 15            # CODEPLUG_CUSTOM_DATA_TYPE_ROAM_CFG (codeplug.h): явне число, а не «наступний у enum»
MAGIC = b"ROAM"
VERSION = 1
PAYLOAD_LEN = 8
HOPS_MIN, HOPS_MAX, HOPS_DEFAULT = 1, 5, 2        # ROAM_HOPS_MIN / MAX / DEFAULT

# R60: байт номера списку в записі каналу (дзеркалить roam_cfg.h: ROAM_LIST_BYTE_OFFSET / TAG / TAG_MASK / VALUE_MASK / ROAM_LISTS_COUNT)
LISTS_COUNT = 10
LIST_BYTE_OFFSET = 37
LIST_TAG = 0xC0
LIST_TAG_MASK = 0xF0
LIST_VALUE_MASK = 0x0F

# біти запису каналу (cps_csv.py): СТАРИЙ прапорець роумінгу R59 і «примусово DMO» (CODEPLUG_CHANNEL_LIBREDMR_FLAG1_FORCE_DMO)
FL_ROAM = 0x01
FL_FORCE_DMO = 0x04
F4_RXONLY = 0x04              # LibreDMR_flag4: «лише прийом»


class RoamCfgError(ValueError):
    pass


def clamp_hops(hops):
    """Так само, як roamCfgClampHops() у прошивці: 1..5 лишається, решта (0, 6, 255) -> типове 2."""
    if isinstance(hops, bool) or not isinstance(hops, int):
        raise RoamCfgError("макс. стрибків: потрібне ціле число, а не %r" % (hops,))
    return hops if HOPS_MIN <= hops <= HOPS_MAX else HOPS_DEFAULT


def check_hops(hops):
    """Для вводу користувача: значення поза 1..5 -- помилка (прошивка мовчки взяла б 2, а людина мала б інше на увазі)."""
    if isinstance(hops, bool) or not isinstance(hops, int) or not (HOPS_MIN <= hops <= HOPS_MAX):
        raise RoamCfgError("макс. стрибків: ціле число %d..%d, а не %r" % (HOPS_MIN, HOPS_MAX, hops))
    return hops


def default_state():
    return {"version": VERSION, "enabled": False, "max_hops": HOPS_DEFAULT}


def build_payload(enabled, max_hops):
    """-> 8 байтів блока. RoamCfgError -- макс. стрибків поза 1..5."""
    check_hops(max_hops)
    p = bytearray(PAYLOAD_LEN)
    p[0:4] = MAGIC
    p[4] = VERSION
    p[5] = 1 if enabled else 0
    p[6] = max_hops
    p[7] = 0
    return bytes(p)


def parse_payload(payload):
    """Як roamCfgParse(): None -- блок недійсний (коротший за 8, інший magic або версія). Інакше {"version", "enabled", "max_hops"}; max_hops уже обмежений."""
    if payload is None or len(payload) < PAYLOAD_LEN or bytes(payload[0:4]) != MAGIC or payload[4] != VERSION:
        return None
    return {"version": payload[4], "enabled": payload[5] != 0, "max_hops": clamp_hops(payload[6])}


# ---------------------------------------------------------------------------------------------------------------------------------
#  Список роумінгу у кодплазі (образ документа)
# ---------------------------------------------------------------------------------------------------------------------------------

def list_from_byte(b):
    """Байт запису -> номер списку 0..10; нерозпізнане (0x00, 0xFF, 0xCB..0xCF, чужа мітка) -> 0. Як roamListFromByte()."""
    n = b & LIST_VALUE_MASK
    if (b & LIST_TAG_MASK) != LIST_TAG or not 1 <= n <= LISTS_COUNT:
        return 0
    return n


def list_to_byte(n):
    """Номер списку -> байт запису: поза 1..10 -> 0x00; N -> 0xC0|N. Як roamListToByte()."""
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= LISTS_COUNT:
        return 0
    return LIST_TAG | n


def list_of(rec):
    """Номер списку каналу 0..10."""
    return list_from_byte(rec[LIST_BYTE_OFFSET])


def is_listed(rec):
    return list_of(rec) != 0


def legacy_flag(rec):
    """Старий прапорець R59 (лише для одноразового перенесення в список 1)."""
    return bool(rec[38] & FL_ROAM)


def roam_channels(img, lst=None):
    """[(номер, запис)] каналів зі списку lst (None -- з будь-якого), за зростанням номера (як у прошивці: «за номерами»)."""
    return [(n, r) for n, r in img.channels() if (list_of(r) == lst if lst is not None else list_of(r) != 0)]


def with_list(rec, lst):
    """Копія запису каналу з номером списку lst (0 -- без списку); старий прапорець R59 знімається (як це робить прошивка); решта байтів -- ні на біт."""
    r = bytearray(rec)
    r[LIST_BYTE_OFFSET] = list_to_byte(lst)
    r[38] &= ~FL_ROAM & 0xFF
    return bytes(r)


def _freq(rec, off):
    # частота -- 4 байти BCD (cps_csv: _freq_dec); для порівняння пар достатньо сирих байтів
    return bytes(rec[off:off + 4])


def pair_key(rec):
    """(RX, TX, колір-код) -- те, за чим прошивка вважає канали «тим самим» і пропускає вдруге в одному PTT."""
    return (_freq(rec, 16), _freq(rec, 20), rec[44])


def problem_of(rec):
    """Чому канал зі списку прошивка пропускатиме: текст або None. Дзеркалить wakeHopChannelUsable() (аналог / DMO / симплекс / лише прийом)."""
    if rec[24] == 0:
        return "аналоговий (роумінг лише для цифрових)"
    if rec[38] & FL_FORCE_DMO:
        return "примусово DMO"
    if _freq(rec, 16) == _freq(rec, 20):
        return "симплекс (RX = TX)"
    if rec[51] & F4_RXONLY:
        return "лише прийом"
    return None


def check_list(img, enabled=False, block_absent=False):
    """Попередження (НЕ блокують запис). enabled -- чи автоперехід увімкнено (у формі або в рації); block_absent -- відомо, що блока налаштувань у рації
    немає (її прочитали, і там порожньо). -> список рядків українською."""
    from cps_csv import readable_text
    out = []
    ch = roam_channels(img)
    by_list = {k: [] for k in range(1, LISTS_COUNT + 1)}
    for n, r in ch:
        by_list[list_of(r)].append((n, r))
    if enabled and not any(len(v) >= 2 for v in by_list.values()):
        out.append("Автоперехід увімкнено, а жоден список не має 2 і більше каналів (поточний і запасний): переходити нікуди.")
    elif enabled:
        for k, v in by_list.items():
            if len(v) == 1:
                out.append("У списку %d лише один канал (№%d): переходити нікуди." % (k, v[0][0]))
    for k, v in by_list.items():
        seen = {}
        for n, r in v:
            why = problem_of(r)
            if why:
                out.append("Канал №%d «%s» у списку %d, але %s -- прошивка його пропустить." % (n, readable_text(r[:16]), k, why))
        for n, r in v:
            key = pair_key(r)
            if key in seen:
                out.append("Канали №%d і №%d у списку %d мають однакові частоти й колір-код -- другий прошивка вважатиме вже випробуваним." % (seen[key], n, k))
            else:
                seen[key] = n
    old = legacy_channels(img)
    if old:
        out.append("Каналів зі СТАРИМ прапорцем роумінгу R59 (без списку): %d. Прошивка R60 його не читає -- натисніть «Перенести старі позначки в список 1»." % len(old))
    if block_absent and ch:
        out.append("У кодплазі каналів у списках: %d, але блока налаштувань «Роумінгу» в рації немає -- автоперехід вимкнено. "
                   "Запишіть налаштування або приберіть канали зі списків." % len(ch))
    return out


def legacy_channels(img):
    """Номери каналів зі старим прапорцем R59, які ще не в жодному списку (їх перенос ще попереду)."""
    return [n for n, r in img.channels() if legacy_flag(r) and list_of(r) == 0]


def clear_lists(img):
    """-> новий образ без списків на всіх каналах (старий прапорець теж знято) і кількість змінених каналів."""
    import cps_csv as cc
    out = cc.Image(img.eeprom, img.flash, img.base)
    n = 0
    for num, rec in img.channels():
        if is_listed(rec) or legacy_flag(rec):
            out.set_channel_rec(num, with_list(rec, 0))
            n += 1
    return out, n


# ---------------------------------------------------------------------------------------------------------------------------------
#  R64: імена списків (custom-data блок типу 16)
# ---------------------------------------------------------------------------------------------------------------------------------
# Формат (дзеркалить roam_cfg.h: ROAM_NAME_LEN / ROAM_NAMES_BLOCK_LEN, roamNameDecode/roamNameEncode): 160 байтів = 10 імен по 16; ім'я списку N -- слот (N-1)*16;
# байти cp1251, ДО 16 символів, решта слота 0x00. Порожнє ім'я (перший байт 0x00 або самі пробіли) = «імені нема» (рація показує «Список N»). Байт < 0x20 у слоті --
# кінець імені. Блока нема (нова/нечіпана рація) = усі імена порожні. Блок пишеться в РАЦІЮ, не в документ кодплага (як блок налаштувань).
TYPE_ROAM_NAMES = 16          # CODEPLUG_CUSTOM_DATA_TYPE_ROAM_NAMES (codeplug.h): явне число
NAME_LEN = 16                 # ROAM_NAME_LEN
NAMES_BLOCK_LEN = LISTS_COUNT * NAME_LEN
NAME_ENCODING = "cp1251"


def check_name(name):
    """Для вводу користувача: -> байти cp1251 (без кінцевих пробілів, до 16). RoamCfgError -- довше 16, символ поза cp1251 або керівний символ (< 0x20)."""
    if not isinstance(name, str):
        raise RoamCfgError("ім'я списку: потрібен текст, а не %r" % (name,))
    name = name.rstrip(" ")
    try:
        raw = name.encode(NAME_ENCODING)
    except UnicodeEncodeError as e:
        raise RoamCfgError("ім'я списку «%s»: символ «%s» немає в cp1251 (шрифт рації його не має)" % (name, name[e.start:e.end]))
    if len(raw) > NAME_LEN:
        raise RoamCfgError("ім'я списку «%s»: %d символів, найбільше %d" % (name, len(raw), NAME_LEN))
    if any(b < 0x20 for b in raw):
        raise RoamCfgError("ім'я списку «%s»: керівні символи не допускаються" % name)
    return raw


def build_names(names):
    """names -- 10 рядків (список 1 першим) -> 160 байтів блока. RoamCfgError -- не 10 імен або погане ім'я."""
    if len(names) != LISTS_COUNT:
        raise RoamCfgError("потрібно рівно %d імен, а не %d" % (LISTS_COUNT, len(names)))
    out = bytearray()
    for nm in names:
        raw = check_name(nm)
        out += raw + b"\x00" * (NAME_LEN - len(raw))
    return bytes(out)


def parse_names(payload):
    """Як roamNameDecode() для кожного слота: -> список з 10 рядків; None -- блока нема. Коротший блок добивається нулями (прошивка читає в обнулений буфер).
    Байт, якого нема в cp1251 (0x98), показується як «?»."""
    if payload is None:
        return None
    blk = bytes(payload[:NAMES_BLOCK_LEN]).ljust(NAMES_BLOCK_LEN, b"\x00")
    out = []
    for i in range(LISTS_COUNT):
        slot = blk[i * NAME_LEN:(i + 1) * NAME_LEN]
        n = 0
        while n < NAME_LEN and slot[n] >= 0x20:
            n += 1
        while n > 0 and slot[n - 1] == 0x20:
            n -= 1
        out.append(slot[:n].decode(NAME_ENCODING, errors="replace"))
    return out


def list_title(names, n):
    """Як показує рація: «N ім'я» або «Список N»."""
    nm = names[n - 1] if names else ""
    return "%d %s" % (n, nm) if nm else "Список %d" % n


# ---------------------------------------------------------------------------------------------------------------------------------
#  Рація (custom-data)
# ---------------------------------------------------------------------------------------------------------------------------------

def read_state(ser, store=None):
    """-> (state|None, raw|None). raw -- байти блока як у рації (None -- блока немає); state None -- блока немає АБО він недійсний.
    R75: store (doc_region.RegionStore) -- читати з документа замість рації."""
    import custom_data as cd
    cd = store if store is not None else cd
    raw = cd.read_block(ser, TYPE_ROAM_CFG, PAYLOAD_LEN)
    return parse_payload(raw), raw


def write_state(ser, enabled, max_hops, safety_dir=None, now=None, log=print):
    """Безпечний запис блока: перевірка меж -> страхова копія наявного блока у файл -> запис -> звірка читанням.
    Повертає (текст, шлях страхової копії|None). RoamCfgError -- погані значення; RuntimeError -- відмова/збій/незбіг."""
    import custom_data as cd
    payload = build_payload(enabled, max_hops)
    old = cd.read_block(ser, TYPE_ROAM_CFG, PAYLOAD_LEN)
    safety = None
    if old is not None:
        d = safety_dir or os.getcwd()
        if not os.access(d, os.W_OK):
            raise RuntimeError("нема права писати в теку %s, де має лежати страхова копія блока «Роумінгу». Нічого не записано." % d)
        ts = (now or datetime.datetime.now()).strftime("%Y%m%d_%H%M%S")
        safety = os.path.join(d, "roam_pre-write_%s.bin" % ts)
        n = 1
        while os.path.exists(safety):
            n += 1
            safety = os.path.join(d, "roam_pre-write_%s_%d.bin" % (ts, n))
        with open(safety, "xb") as f:
            f.write(old)
        with open(safety, "rb") as f:
            if f.read() != old:
                raise RuntimeError("страхову копію блока не вдалося перевірити -- нічого не записано")
        log("Страхова копія блока «Роумінгу»: %s" % safety)
    ok, msg = cd.write_block(ser, TYPE_ROAM_CFG, payload)
    if not ok:
        raise RuntimeError("налаштування «Роумінгу» не записані: " + msg)
    back = cd.read_block(ser, TYPE_ROAM_CFG, PAYLOAD_LEN)
    if back != payload:
        raise RuntimeError("налаштування «Роумінгу» записані, але звірка читанням НЕ збіглася -- повторіть запис" + (("; стара копія: %s" % safety) if safety else ""))
    text = "Налаштування «Роумінгу» записані (%s): автоперехід %s, макс. стрибків %d. Звірка читанням: OK." % (msg, "увімкнено" if enabled else "вимкнено", max_hops)
    if safety:
        text += "\nСтрахова копія попереднього блока:\n" + safety
    return text, safety


def read_names(ser, store=None):
    """-> (імена|None, raw|None). None -- блока імен у рації нема (усі імена порожні). R75: store -- читати з документа."""
    import custom_data as cd
    cd = store if store is not None else cd
    raw = cd.read_block(ser, TYPE_ROAM_NAMES, NAMES_BLOCK_LEN)
    return parse_names(raw), raw


def write_names(ser, names, safety_dir=None, now=None, log=print):
    """Безпечний запис блока імен: перевірка -> страхова копія наявного блока -> запис -> звірка читанням. -> (текст, шлях копії|None).
    RoamCfgError -- погані імена; RuntimeError -- відмова/збій/незбіг. Блок іншої довжини (чужий) не перезаписується (довжину блока міняти не можна)."""
    import custom_data as cd
    payload = build_names(names)
    old = cd.read_block(ser, TYPE_ROAM_NAMES, NAMES_BLOCK_LEN)
    safety = None
    if old is not None:
        d = safety_dir or os.getcwd()
        if not os.access(d, os.W_OK):
            raise RuntimeError("нема права писати в теку %s, де має лежати страхова копія блока імен. Нічого не записано." % d)
        ts = (now or datetime.datetime.now()).strftime("%Y%m%d_%H%M%S")
        safety = os.path.join(d, "roam-names_pre-write_%s.bin" % ts)
        n = 1
        while os.path.exists(safety):
            n += 1
            safety = os.path.join(d, "roam-names_pre-write_%s_%d.bin" % (ts, n))
        with open(safety, "xb") as f:
            f.write(old)
        with open(safety, "rb") as f:
            if f.read() != old:
                raise RuntimeError("страхову копію блока імен не вдалося перевірити -- нічого не записано")
        log("Страхова копія блока імен списків: %s" % safety)
    ok, msg = cd.write_block(ser, TYPE_ROAM_NAMES, payload)
    if not ok:
        raise RuntimeError("імена списків не записані: " + msg)
    back = cd.read_block(ser, TYPE_ROAM_NAMES, NAMES_BLOCK_LEN)
    if back != payload:
        raise RuntimeError("імена списків записані, але звірка читанням НЕ збіглася -- повторіть запис" + (("; стара копія: %s" % safety) if safety else ""))
    text = "Імена списків «Роумінгу» записані (%s). Звірка читанням: OK." % msg
    if safety:
        text += "\nСтрахова копія попереднього блока:\n" + safety
    return text, safety


def describe(state):
    if state is None:
        return "блока нема (або він недійсний) -- автоперехід вимкнено, макс. стрибків %d" % HOPS_DEFAULT
    return "автоперехід %s, макс. стрибків %d" % ("увімкнено" if state["enabled"] else "вимкнено", state["max_hops"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--enable", action="store_true", help="увімкнути автоперехід")
    ap.add_argument("--disable", action="store_true", help="вимкнути автоперехід")
    ap.add_argument("--hops", type=int, default=None, help="макс. стрибків 1..5 (без --enable/--disable лишається стан автопереходу)")
    ap.add_argument("--show", action="store_true", help="лише прочитати")
    ap.add_argument("--port", default=None)
    a = ap.parse_args()
    if a.enable and a.disable:
        sys.exit("--enable і --disable разом не мають сенсу")
    import aes_key_store as aks
    port = a.port or aks.find_port()
    if not port:
        sys.exit("рацію не знайдено (1fc9:0094); передай --port")
    with aks.serial.Serial(port, 115200, timeout=0.6) as ser:
        aks.show_cps(ser)
        st, _raw = read_state(ser)
        print("поточний стан:", describe(st))
        if a.show or not (a.enable or a.disable or a.hops is not None):
            return
        cur = st or default_state()
        en = True if a.enable else (False if a.disable else cur["enabled"])
        hops = a.hops if a.hops is not None else cur["max_hops"]
        try:
            text, _s = write_state(ser, en, hops)
        except (RoamCfgError, RuntimeError) as e:
            sys.exit("ЗАПИС НЕ ВДАВСЯ: %s" % e)
        print(text)


if __name__ == "__main__":
    main()
