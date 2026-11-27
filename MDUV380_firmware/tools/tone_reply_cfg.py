#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tone_reply_cfg.py -- R100/R102/R110: налаштування «Тон-відгуку» (custom-data блок типу 19, CODEPLUG_CUSTOM_DATA_TYPE_TONE_REPLY_CFG) для CPS і командного рядка.

Межі й типові значення беруться з application/include/functions/tone_reply.h (константи TONE_REPLY_*), коли дерево прошивки поруч (запуск
з репозиторію). У зібраному .exe (PyInstaller) заголовка нема -- тоді діє дзеркало MIRROR нижче; tools/test_r100cps.py звіряє MIRROR із заголовком
у кожному CI, тож розійтися вони не можуть.

Формат блока v4 (8 Б, дзеркалить tone_reply.h; R110):
    [0] версія = 4 | [1] тривалість, с | [2] затримка, с | [3] біт 0 -- «увімкнено» | [4..5] частота, Гц, uint16 LE |
    [6] поріг сигналу, ДЕСЯТІ частки секунди (0..50 = 0..5,0 с, крок 0,1 с; більше -- обрізається до 50) | [7] резерв = 0
Усередині модуля поріг -- ціле число десятих («thresh_ds»); у людському вводі/виводі -- секунди з однією десятковою (кома або крапка).
Версія 3 (R102): [6] -- цілі секунди (0..5). Читається з міграцією: десяті = секунди ×10 (обрізання до 50), решта як є.
Версія 2 (R100): те саме, [6..7] = 0, поріг -- константа 1 с. Читається з міграцією: поріг = типовий (1 с), решта як є, «увімкнено» зберігається.
Версія 1 (R99-TONE): [1] і [2] -- ×100 мс, «увімкнено» не зберігалось. Читається з міграцією, як у прошивці: секунди = округлення ВГОРУ, далі межі,
«увімкнено» = вимкнено, поріг = типовий. Записується завжди v4.
Блоку нема / версія невідома -- 1000 Гц, 10 с, 2 с, поріг 1,0 с, вимкнено (так само читає прошивка).
R102: паузи-сторожа після відгуку НЕМАЄ, захисту від зациклення двох рацій з увімкненою функцією НЕМАЄ (рішення власника) -- див. warnings().

Блок існує лише в збірці прошивки з -DENABLE_TONE_REPLY (build-ukrainian); інші збірки його не читають і не псують.

Використання (рація ввімкнена ЗВИЧАЙНО, не в DFU):
  python3 tone_reply_cfg.py --show
  python3 tone_reply_cfg.py --enable --freq 1000 --dur 10 --delay 2 --thresh 0.5
  python3 tone_reply_cfg.py --disable
"""
import argparse
import datetime
import decimal
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HEADER = os.path.join(os.path.dirname(HERE), "application", "include", "functions", "tone_reply.h")

TYPE_TONE_REPLY_CFG = 19      # CODEPLUG_CUSTOM_DATA_TYPE_TONE_REPLY_CFG (codeplug.h)
PAYLOAD_LEN = 8
FLAG_ENABLED = 0x01
LONG_TONE_S = 10              # попередження: довший тон -- довга передача без позивного


# Дзеркало констант tone_reply.h (для .exe без дерева прошивки). Міняючи заголовок, міняй і тут -- інакше впаде test_r100cps.
MIRROR = {"CFG_VERSION": 4, "CFG_V3": 3, "CFG_V2": 2, "CFG_V1": 1, "CFG_LEN": 8, "FREQ_MIN": 300, "FREQ_MAX": 3000, "FREQ_STEP": 50, "FREQ_DEF": 1000,
          "DUR_MIN_S": 1, "DUR_MAX_S": 60, "DUR_DEF_S": 10, "DELAY_MIN_S": 0, "DELAY_MAX_S": 10, "DELAY_DEF_S": 2, "STEP_S": 1,
          "FLAG_ENABLED": 1, "THRESH_MIN_DS": 0, "THRESH_MAX_DS": 50, "THRESH_DEF_DS": 10, "THRESH_STEP_DS": 1, "THRESH_UNIT_MS": 100}


def parse_header(path=HEADER):
    """{ім'я без TONE_REPLY_: число} для всіх `#define TONE_REPLY_<...> <число>U` у tone_reply.h; None -- файла нема."""
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return None
    return {m.group(1): int(m.group(2), 0) for m in re.finditer(r"#define\s+TONE_REPLY_(\w+)\s+(0x[0-9A-Fa-f]+|\d+)U?\b", text)}


_H = parse_header()
K = _H if _H else dict(MIRROR)
SOURCE = HEADER if _H else "MIRROR"
VERSION = K["CFG_VERSION"]
VERSION_V3 = K["CFG_V3"]
VERSION_V2 = K["CFG_V2"]
VERSION_V1 = K["CFG_V1"]
FREQ_MIN, FREQ_MAX, FREQ_STEP, FREQ_DEF = K["FREQ_MIN"], K["FREQ_MAX"], K["FREQ_STEP"], K["FREQ_DEF"]
DUR_MIN, DUR_MAX, DUR_DEF = K["DUR_MIN_S"], K["DUR_MAX_S"], K["DUR_DEF_S"]
DELAY_MIN, DELAY_MAX, DELAY_DEF = K["DELAY_MIN_S"], K["DELAY_MAX_S"], K["DELAY_DEF_S"]
STEP_S = K["STEP_S"]
# R110: поріг у ДЕСЯТИХ частках секунди (0,1 с)
THRESH_MIN, THRESH_MAX, THRESH_DEF, THRESH_STEP = K["THRESH_MIN_DS"], K["THRESH_MAX_DS"], K["THRESH_DEF_DS"], K["THRESH_STEP_DS"]
THRESH_UNIT_MS = K["THRESH_UNIT_MS"]
if K.get("CFG_LEN") != PAYLOAD_LEN:
    raise RuntimeError("tone_reply.h: TONE_REPLY_CFG_LEN = %r, а CPS знає 8" % K.get("CFG_LEN"))


class ToneCfgError(ValueError):
    pass


def fmt_thresh(ds, sep=","):
    """Десяті частки секунди -> «1,0» (людський вигляд; sep="." -- як у меню рації «Поріг:1.0с»)."""
    return "%d%s%d" % (ds // 10, sep, ds % 10)


def parse_thresh_s(text):
    """Людський ввід порогу в секундах («1,5», «1.5», «2», « 0,25 ») -> ціле число десятих, округлення до 0,1 (половина -- вгору).
    ToneCfgError -- не число або поза THRESH_MIN..THRESH_MAX."""
    s = str(text).strip().replace(",", ".")
    try:
        d = decimal.Decimal(s)
    except decimal.InvalidOperation:
        raise ToneCfgError("поріг сигналу: число секунд %s..%s (крок 0,1), а не %r" % (fmt_thresh(THRESH_MIN), fmt_thresh(THRESH_MAX), text))
    if not d.is_finite():
        raise ToneCfgError("поріг сигналу: число секунд, а не %r" % (text,))
    ds = int((d * 10).quantize(decimal.Decimal(1), rounding=decimal.ROUND_HALF_UP))
    if not (THRESH_MIN <= ds <= THRESH_MAX):
        raise ToneCfgError("поріг сигналу: %s..%s с, а не %s" % (fmt_thresh(THRESH_MIN), fmt_thresh(THRESH_MAX), str(text).strip()))
    return ds


def default_state():
    return {"version": 0, "enabled": False, "freq": FREQ_DEF, "dur": DUR_DEF, "delay": DELAY_DEF, "thresh_ds": THRESH_DEF}


def clamp(st):
    """Як toneReplyCfgClamp(): межі й крок частоти (до найближчого кратного FREQ_STEP)."""
    f = min(max(st["freq"], FREQ_MIN), FREQ_MAX)
    f = ((f + FREQ_STEP // 2) // FREQ_STEP) * FREQ_STEP
    st["freq"] = min(f, FREQ_MAX)
    st["dur"] = min(max(st["dur"], DUR_MIN), DUR_MAX)
    st["delay"] = min(max(st["delay"], DELAY_MIN), DELAY_MAX)
    st["thresh_ds"] = min(max(st["thresh_ds"], THRESH_MIN), THRESH_MAX)
    return st


def parse_payload(payload):
    """Як toneReplyCfgParse(): -> dict {"version", "enabled", "freq", "dur", "delay", "thresh_ds"}. version 0 -- блока нема / невідома версія / сміття (типові, вимкнено);
    1 -- мігровано з v1; 2 -- мігровано з v2 (поріг типовий); 3 -- мігровано з v3 (секунди ×10); 4 -- поточний формат."""
    st = default_state()
    if payload is None or len(payload) < PAYLOAD_LEN or payload[0] not in (VERSION, VERSION_V3, VERSION_V2, VERSION_V1):
        return st
    st["version"] = payload[0]
    st["freq"] = payload[4] | (payload[5] << 8)
    if payload[0] == VERSION_V1:
        st["dur"] = (payload[1] + 9) // 10            # ×100 мс -> с, вгору
        st["delay"] = (payload[2] + 9) // 10
    else:
        st["dur"] = payload[1]
        st["delay"] = payload[2]
        st["enabled"] = bool(payload[3] & FLAG_ENABLED)
        if payload[0] == VERSION:
            st["thresh_ds"] = payload[6]                                   # десяті; > 50 обрізає clamp()
        elif payload[0] == VERSION_V3:
            st["thresh_ds"] = THRESH_MAX if payload[6] >= THRESH_MAX // 10 else payload[6] * 10   # секунди -> десяті (як у C: обрізання до множення)
    return clamp(st)


def check_values(freq, dur, delay, thresh_ds=THRESH_DEF):
    """Для вводу користувача: значення поза межами або частота не кратна кроку -- помилка (прошивка мовчки обрізала б, а людина мала б інше на увазі)."""
    for name, v, lo, hi, unit in (("частота", freq, FREQ_MIN, FREQ_MAX, "Гц"), ("тривалість", dur, DUR_MIN, DUR_MAX, "с"), ("затримка", delay, DELAY_MIN, DELAY_MAX, "с"), ("поріг сигналу (десяті с)", thresh_ds, THRESH_MIN, THRESH_MAX, "×0,1 с")):
        if isinstance(v, bool) or not isinstance(v, int) or not (lo <= v <= hi):
            raise ToneCfgError("%s: ціле число %d..%d %s, а не %r" % (name, lo, hi, unit, v))
    if freq % FREQ_STEP:
        raise ToneCfgError("частота: крок %d Гц (%d не кратне)" % (FREQ_STEP, freq))
    return freq, dur, delay, thresh_ds


def build_payload(enabled, freq, dur, delay, thresh_ds=THRESH_DEF):
    """-> 8 байтів блока v4 (поріг -- ціле число десятих секунди). ToneCfgError -- значення поза межами."""
    check_values(freq, dur, delay, thresh_ds)
    return bytes([VERSION, dur, delay, FLAG_ENABLED if enabled else 0, freq & 0xFF, freq >> 8, thresh_ds, 0])


def warnings(enabled, dur, thresh_ds=THRESH_DEF):
    """Попередження (не блокують запис)."""
    w = []
    if enabled:
        w.append("Тон-відгук увімкнено: рація сама передаватиме тон у FM після кожного почутого сигналу (без позивного). Вмикайте лише на час перевірки.")
        if thresh_ds == 0:
            w.append("Поріг сигналу 0 с: відгук запуститься від будь-якого відкриття шумодава, у тому числі від сплесків шуму.")
        w.append("Захисту від зациклення НЕМАЄ: дві рації з увімкненою функцією відповідатимуть одна одній без кінця. Вмикайте лише на одній.")
        if dur > LONG_TONE_S:
            w.append("Тривалість %d с -- понад %d с безперервної передачі на кожен сигнал: нагрів і зайнятий канал." % (dur, LONG_TONE_S))
    return w


def describe(st):
    if st["version"] == 0:
        head = "блока нема (або він недійсний) -- "
    elif st["version"] == VERSION_V1:
        head = "старий формат R99 (буде записано новим) -- "
    elif st["version"] == VERSION_V2:
        head = "формат R100, поріг сигналу типовий (буде записано новим) -- "
    elif st["version"] == VERSION_V3:
        head = "формат R102, поріг у цілих секундах переведено в десяті (буде записано новим) -- "
    else:
        head = ""
    return head + "%s, %d Гц, тривалість %d с, затримка %d с, поріг сигналу %s с" % ("увімкнено" if st["enabled"] else "вимкнено", st["freq"], st["dur"], st["delay"], fmt_thresh(st["thresh_ds"]))


# ---------------------------------------------------------------------------------------------------------------------------------
#  Рація / документ (custom-data)
# ---------------------------------------------------------------------------------------------------------------------------------

def read_state(ser, store=None):
    """-> (state, raw|None). store (doc_region.RegionStore) -- читати з документа замість рації."""
    import custom_data as cd
    src = store if store is not None else cd
    raw = src.read_block(ser, TYPE_TONE_REPLY_CFG, PAYLOAD_LEN)
    return parse_payload(raw), raw


def write_state(ser, enabled, freq, dur, delay, thresh_ds=THRESH_DEF, safety_dir=None, now=None, log=print, store=None):
    """Запис блока. У документ (store) -- просто правка. У рацію -- як «Роумінг»: перевірка меж -> страхова копія наявного блока у файл -> запис ->
    звірка читанням. Повертає (текст, шлях страхової копії|None). ToneCfgError -- погані значення; RuntimeError -- відмова/збій/незбіг."""
    payload = build_payload(enabled, freq, dur, delay, thresh_ds)
    if store is not None:
        ok, msg = store.write_block(None, TYPE_TONE_REPLY_CFG, payload)
        if not ok:
            raise RuntimeError("«Тон-відгук» не змінено в документі: " + msg)
        return "«Тон-відгук» змінено в документі.", None
    import custom_data as cd
    old = cd.read_block(ser, TYPE_TONE_REPLY_CFG, PAYLOAD_LEN)
    safety = None
    if old is not None:
        d = safety_dir or os.getcwd()
        if not os.access(d, os.W_OK):
            raise RuntimeError("нема права писати в теку %s, де має лежати страхова копія блока «Тон-відгуку». Нічого не записано." % d)
        ts = (now or datetime.datetime.now()).strftime("%Y%m%d_%H%M%S")
        safety = os.path.join(d, "tonereply_pre-write_%s.bin" % ts)
        n = 1
        while os.path.exists(safety):
            n += 1
            safety = os.path.join(d, "tonereply_pre-write_%s_%d.bin" % (ts, n))
        with open(safety, "xb") as f:
            f.write(old)
        with open(safety, "rb") as f:
            if f.read() != old:
                raise RuntimeError("страхову копію блока не вдалося перевірити -- нічого не записано")
        log("Страхова копія блока «Тон-відгуку»: %s" % safety)
    ok, msg = cd.write_block(ser, TYPE_TONE_REPLY_CFG, payload)
    if not ok:
        raise RuntimeError("«Тон-відгук» не записано: " + msg)
    back = cd.read_block(ser, TYPE_TONE_REPLY_CFG, PAYLOAD_LEN)
    if back != payload:
        raise RuntimeError("«Тон-відгук» записано, але звірка читанням НЕ збіглася -- повторіть запис" + (("; стара копія: %s" % safety) if safety else ""))
    text = "«Тон-відгук» записано (%s): %s. Звірка читанням: OK. Рація читає блок на старті -- перезапустіть її." % (msg, describe(parse_payload(payload)))
    if safety:
        text += "\nСтрахова копія попереднього блока:\n" + safety
    return text, safety


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--enable", action="store_true", help="увімкнути тон-відгук")
    ap.add_argument("--disable", action="store_true", help="вимкнути")
    ap.add_argument("--freq", type=int, default=None, help="частота %d..%d Гц, крок %d" % (FREQ_MIN, FREQ_MAX, FREQ_STEP))
    ap.add_argument("--dur", type=int, default=None, help="тривалість %d..%d с" % (DUR_MIN, DUR_MAX))
    ap.add_argument("--delay", type=int, default=None, help="затримка %d..%d с" % (DELAY_MIN, DELAY_MAX))
    ap.add_argument("--thresh", default=None, help="поріг сигналу, с: %s..%s, крок 0,1 (кома або крапка; 0 -- будь-яке відкриття шумодава)" % (fmt_thresh(THRESH_MIN), fmt_thresh(THRESH_MAX)))
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
        if a.show or not (a.enable or a.disable or a.freq is not None or a.dur is not None or a.delay is not None or a.thresh is not None):
            return
        en = True if a.enable else (False if a.disable else st["enabled"])
        f = a.freq if a.freq is not None else st["freq"]
        du = a.dur if a.dur is not None else st["dur"]
        dl = a.delay if a.delay is not None else st["delay"]
        try:
            th = parse_thresh_s(a.thresh) if a.thresh is not None else st["thresh_ds"]
        except ToneCfgError as e:
            sys.exit("ЗАПИС НЕ ВДАВСЯ: %s" % e)
        for w in warnings(en, du, th):
            print("УВАГА:", w)
        try:
            text, _s = write_state(ser, en, f, du, dl, th)
        except (ToneCfgError, RuntimeError) as e:
            sys.exit("ЗАПИС НЕ ВДАВСЯ: %s" % e)
        print(text)


if __name__ == "__main__":
    main()
