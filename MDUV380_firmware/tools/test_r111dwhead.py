#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_r111dwhead.py -- R111-DWHEAD: у шапці «Подвійного прийому» «A ✉ N» (APRS) починається з x=22, а не впритул до «DW» (x=16).

Геометрія -- за КОНСТАНТАМИ й формулами з uiUtilities.c (DW_HDR_*, MSG_ENV_*, msgEnvelopeWidth, обрізання лічильника > 99 до 99), а не «на око»:
  Ш1  DW_HDR_A_X == 22; DW_HDR_D_RIGHT, ширина й висота конверта, y -- як у R98-FIX13; static-assert dwHdrEnvFits на місці.
  Ш2  для лічильників 1, 9, 10, 99, 100, 255 (A і D разом і окремо): «DW» (x=1..12), «A ✉ N», «D ✉ N», заряд/годинник (з x=100) не перекриваються,
      проміжки >= 2 порожніх px; «A ✉» від «DW» -- >= 9 px (x=22); усе в межах екрана 160 px і рядка шапки (y < DISPLAY_Y_POS_BAR).
  Ш3  код: лише константа змінилась (drawMsgEnvelope(DW_HDR_A_X, ...)), усе під DUAL_CHANNEL_ENABLED; біжуча стрічка рядка 3 (dwMqA/dwMqB) не чіпана.
  Ш4  мутант «x=16» -- ловиться (менше 9 px до «DW»); мутант «x=30» -- ловиться (A і D злипаються при 99/99).
Справжній рендер пікселів шапки й проміжки в усіх комбінаціях заряду/годинника -- tools/test_r98fix13.py (розділ «В», PNG `--png`).
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.normpath(os.path.join(HERE, ".."))
UU = os.path.join(FW, "application", "source", "user_interface", "uiUtilities.c")
CM = os.path.join(FW, "application", "source", "user_interface", "uiChannelMode.c")
FAILS = []
N = [0]

SCREEN_W = 160            # DISPLAY_SIZE_X (HX8353E.h)
BAR_Y = 10                # DISPLAY_Y_POS_BAR (uiGlobals.h, MDUV380)
DW_X0, DW_X1 = 1, 13      # «DW»: MODE_TEXT_X_OFFSET = 1, два символи по 6 px -> [1, 13)
BAT_X0 = SCREEN_W - 33 - 27   # найлівіший заряд (режим напруги, коли показано годинник) -- те саме, що в dwHdrEnvFits


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m)
        print("ПРОВАЛ:", m)


def consts(text):
    k = {m.group(1): int(m.group(2)) for m in re.finditer(r"#define\s+(DW_HDR_\w+|MSG_ENV_\w+)\s+(\d+)\b", text)}
    return k


def env_w(k, count):
    """msgEnvelopeWidth(): літера + 1 + корпус + 2 + число (6 px на цифру); лічильник > 99 показується як 99."""
    c = min(count, 99)
    return k["MSG_ENV_LETTER_W"] + 1 + k["MSG_ENV_BODY_W"] + 2 + (12 if c > 9 else 6)


def layout(k, a, d):
    """Інтервали [x0, x1) елементів шапки DW для лічильників a (APRS) і d (SMS DMR)."""
    el = {"DW": (DW_X0, DW_X1), "bat": (BAT_X0, SCREEN_W)}
    if a > 0:
        el["A"] = (k["DW_HDR_A_X"], k["DW_HDR_A_X"] + env_w(k, a))
    if d > 0:
        el["D"] = (k["DW_HDR_D_RIGHT"] - env_w(k, d), k["DW_HDR_D_RIGHT"])
    return el


def problems(k):
    bad = []
    counts = (0, 1, 9, 10, 99, 100, 255)
    for a in counts:
        for d in counts:
            el = layout(k, a, d)
            names = sorted(el, key=lambda n: el[n][0])
            for i in range(len(names) - 1):
                l, r = el[names[i]], el[names[i + 1]]
                gap = r[0] - l[1]
                if gap < 2:
                    bad.append("A=%d D=%d: %s і %s -- проміжок %d px (< 2)" % (a, d, names[i], names[i + 1], gap))
            for n, (x0, x1) in el.items():
                if x0 < 0 or x1 > SCREEN_W:
                    bad.append("A=%d D=%d: %s поза екраном [%d, %d)" % (a, d, n, x0, x1))
            if "A" in el and el["A"][0] - DW_X1 < 9:
                bad.append("A=%d: «A ✉» лише %d px від «DW» (рішення власника -- x=22, >= 9 px)" % (a, el["A"][0] - DW_X1))
    if k["DW_HDR_ENV_Y"] + k["MSG_ENV_BODY_H"] > BAR_Y:
        bad.append("конверт виходить за рядок шапки: y=%d + %d > %d" % (k["DW_HDR_ENV_Y"], k["MSG_ENV_BODY_H"], BAR_Y))
    return bad


def main():
    uu = open(UU, encoding="utf-8").read()
    k = consts(uu)
    # Ш1
    check(k.get("DW_HDR_A_X") == 22, "Ш1: DW_HDR_A_X = 22 (було 16): %r" % k.get("DW_HDR_A_X"))
    check((k.get("DW_HDR_D_RIGHT"), k.get("DW_HDR_ENV_Y"), k.get("MSG_ENV_LETTER_W"), k.get("MSG_ENV_BODY_W"), k.get("MSG_ENV_BODY_H")) == (97, 1, 6, 13, 9),
          "Ш1: решта констант як у R98-FIX13 (D до x=96, y=1, літера 6, корпус 13x9): %r" % k)
    check("typedef char dwHdrEnvFits[" in uu, "Ш1: static-assert dwHdrEnvFits на місці")
    check("return (int16_t)(MSG_ENV_LETTER_W + 1 + MSG_ENV_BODY_W + 2 + ((count > 9U) ? 12 : 6));" in uu and
          'snprintf(nb, sizeof nb, "%u", (count > 99U) ? 99U : count);' in uu, "Ш1: ширина й обрізання лічильника > 99 -- як у моделі тесту")
    # Ш2
    p = problems(k)
    check(not p, "Ш2: шапка DW: %s" % "; ".join(p[:6]))
    w = layout(k, 99, 99)
    print("ШАПКА DW (A=99, D=99): DW %r, A %r, D %r, заряд з x=%d; проміжки: DW-A %d px, A-D %d px, D-заряд %d px"
          % (w["DW"], w["A"], w["D"], BAT_X0, w["A"][0] - w["DW"][1], w["D"][0] - w["A"][1], BAT_X0 - w["D"][1]))
    # Ш3
    m = re.search(r"#if defined\(DUAL_CHANNEL_ENABLED\)\n// kind: 'D'.*?#define DW_HDR_A_X", uu, re.S)
    check(m is not None, "Ш3: DW_HDR_A_X -- усередині #if defined(DUAL_CHANNEL_ENABLED)")
    fn = uu[uu.index("static void dwHeaderEnvelopes(unsigned aprsCount, unsigned dmrCount)"):]
    fn = fn[:fn.index("\n}\n")]
    check("drawMsgEnvelope(DW_HDR_A_X, DW_HDR_ENV_Y, 'A', aprsCount);" in fn and "drawMsgEnvelope((int16_t)(DW_HDR_D_RIGHT - msgEnvelopeWidth(dmrCount))" in fn,
          "Ш3: малювання -- через ті самі константи (A з DW_HDR_A_X, D -- до DW_HDR_D_RIGHT)")
    cm = open(CM, encoding="utf-8").read()
    check("dwMqA" in cm or "DW_ROW3_BUF" in cm, "Ш3: біжуча стрічка рядка 3 лишилась (R98-FIX15)")
    # Ш4: мутанти
    for name, val in (("x=16", 16), ("x=30", 30)):
        km = dict(k)
        km["DW_HDR_A_X"] = val
        check(bool(problems(km)), "Ш4: мутант «%s» ловиться" % name)
    print("test_r111dwhead: перевірок %d, провалів %d" % (N[0], len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
