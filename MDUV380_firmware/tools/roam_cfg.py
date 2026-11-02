#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""roam_cfg.py -- R59: налаштування «Роумінгу» (автоперехід на наступний канал зі списку, коли ретранслятор не відповідає на пробудження під PTT).

Що де лежить (одне джерело істини для кожного):
  * СПИСОК роумінгу -- прапорець каналу CHANNEL_FLAG_ROAMING (LibreDMR_flag1, маска 0x01) У КОДПЛАЗІ. Редагується як решта кодплага: колонка «Роум.» у «Каналах»,
    колонка «Roam» у CSV, кнопки панелі «Роумінг»; у рацію потрапляє дією «Записати кодплаг у рацію».
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

# біти запису каналу (cps_csv.py): прапорець роумінгу і «примусово DMO» (CODEPLUG_CHANNEL_LIBREDMR_FLAG1_FORCE_DMO)
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

def is_listed(rec):
    return bool(rec[38] & FL_ROAM)


def roam_channels(img):
    """[(номер, запис)] каналів зі списку, за зростанням номера (як у прошивці: «за номерами»)."""
    return [(n, r) for n, r in img.channels() if is_listed(r)]


def with_flag(rec, on):
    """Копія запису каналу з виставленим/знятим прапорцем; решта байтів не змінюється ні на біт."""
    r = bytearray(rec)
    r[38] = (r[38] | FL_ROAM) if on else (r[38] & ~FL_ROAM & 0xFF)
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
    if enabled and len(ch) < 2:
        out.append("Автоперехід увімкнено, а у списку %d %s: потрібно щонайменше 2 канали (поточний і запасний), інакше переходити нікуди." % (
            len(ch), "канал" if len(ch) == 1 else "каналів"))
    for n, r in ch:
        why = problem_of(r)
        if why:
            out.append("Канал №%d «%s» у списку, але %s -- прошивка його пропустить." % (n, readable_text(r[:16]), why))
    seen = {}
    for n, r in ch:
        k = pair_key(r)
        if k in seen:
            out.append("Канали №%d і №%d у списку мають однакові частоти й колір-код -- другий прошивка вважатиме вже випробуваним." % (seen[k], n))
        else:
            seen[k] = n
    if block_absent and ch:
        out.append("У кодплазі позначено каналів: %d, але блока налаштувань «Роумінгу» в рації немає -- автоперехід вимкнено. "
                   "Запишіть налаштування або зніміть позначки." % len(ch))
    return out


def clear_flags(img):
    """-> новий образ без прапорців роумінгу на всіх каналах і кількість знятих."""
    import cps_csv as cc
    out = cc.Image(img.eeprom, img.flash, img.base)
    n = 0
    for num, rec in img.channels():
        if is_listed(rec):
            out.set_channel_rec(num, with_flag(rec, False))
            n += 1
    return out, n


# ---------------------------------------------------------------------------------------------------------------------------------
#  Рація (custom-data)
# ---------------------------------------------------------------------------------------------------------------------------------

def read_state(ser):
    """-> (state|None, raw|None). raw -- байти блока як у рації (None -- блока немає); state None -- блока немає АБО він недійсний."""
    import custom_data as cd
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
