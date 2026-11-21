#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R98-FIX10 -> R98-FIX11 А (хост): на звичайному екрані (канал/VFO) замок шифрування і конверт непрочитаних SMS «D ✉ N» не накладаються.
  R98-FIX10 зсував ЗАМОК ліворуч від конверта (x=118/112). R98-FIX11 А (рішення власника, однаковий порядок зі «Подвійним прийомом»):
  замок -- на стоковому місці x=147..156, y=14..22, а КОНВЕРТ -- ліворуч від нього, на тій самій висоті. Тест переведено на нову геометрію:
  А  СПРАВЖНІ msgEnvelopeWidth()/headerEnvelopeX() з uiUtilities.c (gcc-гарнес): правий край блока для лічильників 1..120, з замком і без.
  Б  ПІКСЕЛЬНА перевірка (screen_sim, шрифт прошивки, справжня бітмапа замка): для 1..99 -- без спільних пікселів, зазор >= 2 px, з APRS «A»;
     мутанти: «конверт на старому місці» (ігнорує замок), «зазор 0» -- ловляться.
  В  Смуга y=14..22: RSSI-смуга (y=10..13) і поле позивного (y>=24) не зачіпаються (конверт R98-FIX10 торкався y=24 -- тепер ні).
  Г  Збірки без режиму (DUAL_CHANNEL_ENABLED): стокові виклики на місці (гілки #else); uiAesPadlockX (R98-FIX10) прибрано.
  Повний розбір (порядок «D ✉ N, замок», висота, режими екрана, мутант «різна висота») -- tools/test_r98fix11.py, частина А.
Запуск: python3 tools/test_r98fix10.py"""
import os, re, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import screen_sim as sim  # noqa

FAILS = []; N = [0]


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m); print("ПРОВАЛ: " + m)


FW = os.path.dirname(HERE)
SRC = os.path.join(FW, "application", "source", "user_interface", "uiUtilities.c")


def rd(p):
    return open(p, encoding="utf-8").read()


def pick(src, start_pat, end_pat):
    a = src.find(start_pat)
    if a < 0:
        return None
    b = src.find(end_pat, a)
    return None if b < 0 else src[a:b + len(end_pat)]


def harness_code(src):
    defs = "\n".join(re.findall(r"^#define (?:MSG_ENV_\w+|UI_AES_PADLOCK_\w+|UI_ICON_GAP)[^\n]*$", src, re.M))
    w = pick(src, "static int16_t msgEnvelopeWidth(unsigned count)\n{", "\n}\n")
    hx = pick(src, "static int16_t headerEnvelopeX(unsigned count)\n{", "\n}\n")
    if not (w and hx):
        return None
    return r'''
#include <stdint.h>
#include <stdio.h>
#include <stdbool.h>
#define DISPLAY_SIZE_X 160
#define DISPLAY_Y_POS_BAR 10
enum { UI_CHANNEL_MODE = 7, UI_VFO_MODE = 8 };
''' + defs + r'''
static int g_aes;
static int menuSystemGetCurrentMenuNumber(void) { return UI_CHANNEL_MODE; }
static int uiChannelHasAesEnabled(void) { return g_aes; }
''' + w + "\n" + hx + r'''
int main(void)
{
	for (int a = 0; a < 2; a++)
		for (int n = 1; n <= 120; n++)
		{
			g_aes = a;
			printf("%d %d %d %d\n", a, n, headerEnvelopeX((unsigned)n), msgEnvelopeWidth((unsigned)n));
		}
	return 0;
}
'''


def run_harness(src):
    code = harness_code(src)
    if code is None:
        return None
    d = tempfile.mkdtemp(prefix="r98f10_")
    try:
        c = os.path.join(d, "h.c"); open(c, "w", encoding="utf-8").write(code)
        r = subprocess.run(["gcc", "-std=gnu11", "-w", "-o", os.path.join(d, "h"), c], capture_output=True)
        if r.returncode != 0:
            print(r.stderr.decode()[:2000]); return None
        out = subprocess.run([os.path.join(d, "h")], capture_output=True).stdout.decode().split("\n")
        res = {}
        for l in out:
            if l.strip():
                a, n, x, w = (int(v) for v in l.split())
                res[(a, n)] = (x, w)
        return res
    finally:
        shutil.rmtree(d, ignore_errors=True)


def lock_bitmap(src):
    m = re.search(r"uiAesPadlockBitmap\[\]\s*=\s*\{(.*?)\};", src, re.S)
    return bytes(int(v, 16) for v in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(1)))


def env_y(src):
    m = re.search(r"#define MSG_ENV_Y\s+\(DISPLAY_Y_POS_BAR \+ (\d+)\)", src)
    return (10 + int(m.group(1))) if m else None


def draw_env(d, x, y, letter, count):
    """Дзеркало drawMsgEnvelope() у збірці з режимом (текст на 1 px нижче верху корпуса)."""
    ex = x + 6 + 1
    d.print_core(x, y + 1, letter, sim.FONT_1, sim.ALIGN_LEFT, False)
    d.draw_rect(ex, y, 13, 9, True)
    d.draw_line(ex, y, ex + 6, y + 4, True)
    d.draw_line(ex + 12, y, ex + 6, y + 4, True)
    d.print_core(ex + 13 + 2, y + 1, str(min(count, 99)), sim.FONT_1, sim.ALIGN_LEFT, False)


def ink(d):
    return {(x, y) for y in range(sim.H) for x in range(sim.W) if d.px[y * sim.W + x] != d.bg}


def env_ink(x, y, count, letter="D"):
    d = sim.Display(); draw_env(d, x, y, letter, count); return ink(d)


def lock_ink(bm, x, y=14):
    d = sim.Display(); d.draw_xbitmap(x, y, bm, 10, 9, True); return ink(d)


def gap_cols(a, b):
    return min(x for x, _ in b) - max(x for x, _ in a) - 1


def geometry_ok(res, bm, ey):
    """Перелік зламаних властивостей для результатів гарнеса."""
    bad = []
    L = lock_ink(bm, 147)
    for n in range(1, 100):
        x, w = res[(1, n)]
        e = env_ink(x, ey, n)
        if (e & L) or gap_cols(e, L) < 2:
            bad.append(("перетин/зазор", n, len(e & L), gap_cols(e, L)))
        if x + w - 1 != 144:
            bad.append(("правий край", n, x + w - 1))
        x0, _ = res[(0, n)]
        if x0 + w - 1 != 157:
            bad.append(("без замка", n, x0 + w - 1))
    return bad


def main():
    src = rd(SRC)
    res = run_harness(src)
    check(res is not None, "А: гарнес msgEnvelopeWidth()/headerEnvelopeX() зібрався")
    if res is None:
        return 1
    bm = lock_bitmap(src); ey = env_y(src)
    check(len(bm) == 18 and ey == 14, "А0: бітмапа замка 10x9, конверт на висоті замка y=14 (MSG_ENV_Y): %s" % ey)
    check(re.search(r"displayDrawXBitmap\(DISPLAY_SIZE_X - UI_AES_PADLOCK_W - 3, 14, uiAesPadlockBitmap", src) is not None and "uiAesPadlockX" not in src,
          "А1: замок -- на стоковому місці x=147, y=14; зсув R98-FIX10 (uiAesPadlockX) прибрано")
    bad = geometry_ok(res, bm, ey)
    check(bad == [], "Б1: лічильники 1..99: конверт ліворуч від замка, правий край блока x=144 (2 px до замка), без перетину; без замка -- до x=157: %s" % bad[:3])
    # APRS «A» (x=2) разом
    ok = True
    for n in (1, 9, 10, 99):
        x, _ = res[(1, n)]
        ea = env_ink(2, ey, 99, "A"); e = env_ink(x, ey, n); L = lock_ink(bm, 147)
        ok = ok and not (ea & e) and not (ea & L) and gap_cols(ea, e) >= 4
    check(ok, "Б2: з конвертом APRS «A» (x=2): без перетинів")
    # В: смуги
    allp = set()
    for n in (1, 99):
        allp |= env_ink(res[(1, n)][0], ey, n)
    allp |= lock_ink(bm, 147)
    check(min(y for _, y in allp) >= 14 and max(y for _, y in allp) <= 22, "В1: замок і конверт -- y=14..22: нижче RSSI-смуги (10..13), вище поля позивного (24): %s..%s" % (min(y for _, y in allp), max(y for _, y in allp)))
    # мутанти
    def mut(name, a, b):
        s2 = src.replace(a, b, 1)
        r2 = run_harness(s2) if s2 != src else None
        check(r2 is not None and geometry_ok(r2, bm, ey) != [], "Б3 (мутант %s): ловиться" % name)
    mut("конверт на старому місці", "int16_t right = (lockShown ? (int16_t)(DISPLAY_SIZE_X - UI_AES_PADLOCK_W - 3 - UI_ICON_GAP) : (int16_t)(DISPLAY_SIZE_X - 2));",
        "int16_t right = (int16_t)(DISPLAY_SIZE_X - 2); (void)lockShown;")
    mut("зазор 0", "#define UI_ICON_GAP 2", "#define UI_ICON_GAP 0")
    # Г: збірки без режиму
    check("#else\n\t\t\tint16_t ex = (int16_t)(DISPLAY_SIZE_X - 2 - msgEnvelopeWidth((unsigned)unread));\n\t\t\tdrawMsgEnvelope(ex, DISPLAY_Y_POS_BAR + 6, 'D', (unsigned)unread);\n#endif" in src,
          "Г1: без DUAL_CHANNEL_ENABLED -- стоковий виклик конверта «D» (гілка #else)")
    check(re.search(r"#if defined\(DUAL_CHANNEL_ENABLED\) && defined\(ENABLE_AES\) && defined\(ENABLE_DMR_DATA\)\n// R98-FIX11 А4", src) is not None,
          "Г2: нові функції -- під DUAL_CHANNEL_ENABLED && ENABLE_AES && ENABLE_DMR_DATA")
    print("перевірок: %d, провалів: %d" % (N[0], len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
