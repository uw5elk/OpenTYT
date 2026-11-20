#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R98-FIX10 (хост): на звичайному екрані (канал/VFO) замок шифрування не налазить на конверт непрочитаних SMS «D ✉ N».
  А  СПРАВЖНІ uiAesPadlockX()/msgEnvelopeWidth() з uiUtilities.c (gcc-гарнес): положення замка для лічильників 0..120,
     з екраном «Подвійного прийому» і без нього; без непрочитаних -- стара позиція x=147.
  Б  ПІКСЕЛЬНА перевірка (screen_sim, шрифт прошивки, справжня бітмапа замка з вихідника): для лічильників 1..99 замок і
     конверт (літера, корпус, клапан, число) не мають спільних пікселів і між ними >= 1 вільний стовпчик; те саме разом
     з конвертом APRS «A» (x=2); мутанти: стара позиція, проміжок 0, умова «лічильник > 0» зламана -- ловляться.
  В  Інші елементи смуги y=14..24: смуга RSSI (y=10..13), рядок позивного (y>=24) -- замок/конверт їх не зачіпають;
     конверт і текст позивного FONT_3: перелік гліфів з чорнилом у верхньому рядку (інформативно).
  Г  Збірки без режиму (DUAL_CHANNEL_ENABLED) / без ENABLE_DMR_DATA: зміни під #if, токени стокового виклику не змінені.
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


# ------------------------------------------------------------------------------------------------ вихідник
def pick(src, start_pat, end_pat):
    a = src.find(start_pat)
    if a < 0:
        return None
    b = src.find(end_pat, a)
    return None if b < 0 else src[a:b + len(end_pat)]


def harness_code(src):
    """Справжні msgEnvelopeWidth()/uiAesPadlockX() + константи; стаби лічильника й ознаки екрана режиму."""
    defs = "\n".join(re.findall(r"^#define (?:MSG_ENV_\w+|UI_AES_PADLOCK_\w+)[^\n]*$", src, re.M))
    defs = "\n".join("#define " + l.split("#define ", 1)[1] if l.startswith("#define") else l for l in defs.split("\n"))
    w = pick(src, "static int16_t msgEnvelopeWidth(unsigned count)\n{", "\n}\n")
    px = pick(src, "static int16_t uiAesPadlockX(int16_t defaultX)\n{", "\n}\n")
    if not (w and px):
        return None
    return r'''
#include <stdint.h>
#include <stdio.h>
#include <stdbool.h>
#define DISPLAY_SIZE_X 160
#define DUAL_CHANNEL_ENABLED 1
''' + defs + r'''
static int g_unread; static int g_cards;
static int dmrSmsUnreadCount(void) { return g_unread; }
static bool dualEnvelopeInCards(void) { return g_cards != 0; }
''' + w + "\n" + px + r'''
int main(void)
{
	for (int cards = 0; cards < 2; cards++)
		for (int n = 0; n <= 120; n++)
		{
			g_unread = n; g_cards = cards;
			printf("%d %d %d %d\n", cards, n, uiAesPadlockX(147), msgEnvelopeWidth((unsigned)(n > 0 ? n : 1)));
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
                cards, n, x, w = (int(v) for v in l.split())
                res[(cards, n)] = (x, w)
        return res
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ------------------------------------------------------------------------------------------------ піксельна модель
def lock_bitmap(src):
    m = re.search(r"uiAesPadlockBitmap\[\]\s*=\s*\{(.*?)\};", src, re.S)
    return bytes(int(v, 16) for v in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(1)))


def draw_env(d, x, y, letter, count):
    """Дзеркало drawMsgEnvelope() (літера, корпус 13x9, клапан, число до 99)."""
    ex = x + 6 + 1
    d.print_core(x, y, letter, sim.FONT_1, sim.ALIGN_LEFT, False)
    d.draw_rect(ex, y, 13, 9, True)
    d.draw_line(ex, y, ex + 6, y + 4, True)
    d.draw_line(ex + 12, y, ex + 6, y + 4, True)
    d.print_core(ex + 13 + 2, y, str(min(count, 99)), sim.FONT_1, sim.ALIGN_LEFT, False)


def ink(d):
    return {(x, y) for y in range(sim.H) for x in range(sim.W) if d.px[y * sim.W + x] != d.bg}


def env_ink(count, letter="D", x=None):
    d = sim.Display()
    w = 6 + 1 + 13 + 2 + (12 if count > 9 else 6)
    draw_env(d, (160 - 2 - w) if x is None else x, 16, letter, count)
    return ink(d)


def lock_ink(bm, x):
    d = sim.Display()
    d.draw_xbitmap(x, 14, bm, 10, 9, True)
    return ink(d)


def gap_cols(a, b):
    """Мінімальна горизонтальна відстань (вільних стовпчиків) між чорнилом a (ліворуч) і b (праворуч); <0 -- перетин."""
    return min(x for x, _ in b) - max(x for x, _ in a) - 1


def main():
    src = rd(SRC)
    # --- А: справжній код
    res = run_harness(src)
    check(res is not None, "А: гарнес uiAesPadlockX()/msgEnvelopeWidth() зібрався")
    if res is None:
        return
    check(all(res[(0, 0)] == (147, res[(0, 0)][1]) for _ in [0]), "А1: без непрочитаних замок на старому місці x=147")
    check(all(res[(1, n)][0] == 147 for n in range(0, 121)), "А2: на екрані режиму (конверти в картках) замок -- на старому місці")
    exp = {}
    for n in range(1, 121):
        w = 6 + 1 + 13 + 2 + (12 if n > 9 else 6)
        exp[n] = 160 - 2 - w - 2 - 10
    check(all(res[(0, n)][0] == exp[n] for n in range(1, 121)), "А3: замок = 158 - ширина_блока - 2 - 10 для лічильників 1..120: %s" % [(n, res[(0, n)][0], exp[n]) for n in range(1, 121) if res[(0, n)][0] != exp[n]][:3])
    check(res[(0, 1)][0] == 118 and res[(0, 9)][0] == 118 and res[(0, 10)][0] == 112 and res[(0, 99)][0] == 112, "А4: x=118 для 1 цифри, x=112 для 2 цифр (%s %s)" % (res[(0, 9)][0], res[(0, 10)][0]))
    check(all(res[(0, n)][0] >= 40 for n in range(1, 121)), "А5: замок не заходить на ліву половину (конверт APRS «A» там)")

    # --- Б: пікселі
    bm = lock_bitmap(src)
    check(len(bm) == 18, "Б0: бітмапа замка 10x9 (18 байтів): %d" % len(bm))
    old_overlap = []
    bad = []
    for n in range(1, 100):
        e = env_ink(n)
        L = lock_ink(bm, res[(0, n)][0])
        if (e & L) or gap_cols(L, e) < 1:
            bad.append((n, len(e & L), gap_cols(L, e)))
        L0 = lock_ink(bm, 147)
        old_overlap.append(len(e & L0))
    check(bad == [], "Б1: лічильники 1..99: замок і конверт без спільних пікселів, між ними >= 1 вільний стовпчик: %s" % bad[:3])
    check(all(o > 0 for o in old_overlap), "Б2: стара позиція (x=147) перетиналась з конвертом для КОЖНОГО лічильника 1..99 (%d з 99 мали спільні пікселі)" % sum(1 for o in old_overlap if o > 0))
    # разом з APRS «A» (x=2)
    bad = []
    for n in (1, 9, 10, 99):
        for a in (1, 9, 10, 99):
            ea = env_ink(a, "A", 2)
            L = lock_ink(bm, res[(0, n)][0])
            if (ea & L) or (ea & env_ink(n)) or gap_cols(ea, L) < 4:
                bad.append((n, a))
    check(bad == [], "Б3: з конвертом APRS «A» (x=2): без перетину, між «A» і замком >= 4 стовпчики: %s" % bad)
    # мутанти (мають ловитись)
    def mut_check(name, repl_from, repl_to):
        s2 = src.replace(repl_from, repl_to, 1)
        r2 = run_harness(s2) if s2 != src else None
        if r2 is None:
            check(False, "Б4 (мутант %s): мутант не зібрався/не застосувався" % name); return
        caught = False
        for n in range(1, 100):
            e = env_ink(n)
            if (e & lock_ink(bm, r2[(0, n)][0])) or gap_cols(lock_ink(bm, r2[(0, n)][0]), e) < 1:
                caught = True; break
        if repl_from == "if (unread > 0)\n\t{\n\t\treturn (int16_t)(DISPLAY_SIZE_X - 2":
            caught = caught or any(r2[(0, n)][0] != exp[n] for n in range(1, 121))
        check(caught, "Б4 (мутант %s): перевірка його ловить" % name)
    mut_check("проміжок 0", "#define UI_AES_PADLOCK_ENV_GAP 2", "#define UI_AES_PADLOCK_ENV_GAP -1")
    mut_check("без зсуву", "- UI_AES_PADLOCK_ENV_GAP - UI_AES_PADLOCK_W);", "- UI_AES_PADLOCK_ENV_GAP - UI_AES_PADLOCK_W + 14);")
    mut_check("ширина 1 цифра завжди", "((count > 9U) ? 12 : 6)", "6")
    # умова «лічильник > 0»
    s3 = src.replace("if (unread > 0)\n\t{\n\t\treturn (int16_t)(DISPLAY_SIZE_X - 2", "if (unread > 5)\n\t{\n\t\treturn (int16_t)(DISPLAY_SIZE_X - 2", 1)
    r3 = run_harness(s3) if s3 != src else None
    check(r3 is not None and r3[(0, 3)][0] == 147, "Б4 (мутант умови): лічильник 3 -> замок лишається на 147 і перетин ловиться")
    if r3 is not None:
        check(bool(env_ink(3) & lock_ink(bm, r3[(0, 3)][0])), "Б4: мутант умови справді дає перетин на лічильнику 3")

    # --- В: інші елементи смуги
    lk = lock_ink(bm, 118); lk2 = lock_ink(bm, 112)
    check(min(y for _, y in lk | lk2) >= 14 and max(y for _, y in lk | lk2) <= 22, "В1: замок y=14..22 -- нижче смуги RSSI (y=10..13) і вище рядка позивного (y=24)")
    env = env_ink(99) | env_ink(5)
    check(min(y for _, y in env) >= 14, "В2: конверт не заходить у смугу RSSI (y=10..13): мін. y=%d" % min(y for _, y in env))
    check(max(y for _, y in env) == 24, "В3: нижній рядок конверта -- y=24 (перший рядок поля позивного FONT_SIZE_3; перевірено нижче)")
    # гліфи FONT_3 з чорнилом у верхньому рядку (y=24) -- лише ці можуть торкнутись нижньої лінії корпуса
    tops = []
    d = sim.Display()
    for c in range(33, 256):
        d.clear_buf()
        d.print_core(0, 24, bytes([c]).decode("cp1251", errors="replace"), sim.FONT_3, sim.ALIGN_LEFT, False)
        if any(d.px[24 * sim.W + x] != d.bg for x in range(8)):
            tops.append(bytes([c]).decode("cp1251", errors="replace"))
    # найгірший випадок: вирівнювання центром, 16 символів -> текст x=16..143, корпус конверта від x=131 (2 цифри)
    # (без чорнила в верхньому рядку перетин з нижньою лінією корпуса y=24 неможливий)
    check(len(tops) <= 8, "В4: гліфів FONT_3 з чорнилом у верхньому рядку мало (%d: %s) -- торкнутись корпуса конверта можуть лише вони" % (len(tops), "".join(tops)))
    print("ІНФО: гліфи з чорнилом на y=24 (верхній рядок поля позивного): %s" % "".join(tops))

    # --- Г: умови компіляції
    a = src.find("void uiDrawAesEnabledIcon(void)")
    blk = src[a:a + 1100]
    # збірки без режиму: токени uiDrawAesEnabledIcon() як у стоку (гілка #else -- та сама строка, що була)
    check("#if defined(ENABLE_DMR_DATA) && defined(DUAL_CHANNEL_ENABLED)" in blk and "displayDrawXBitmap(uiAesPadlockX(DISPLAY_SIZE_X - UI_AES_PADLOCK_W - 3), 14," in blk, "Г1: зсув замка в uiDrawAesEnabledIcon() -- лише під ENABLE_DMR_DATA && DUAL_CHANNEL_ENABLED")
    check("#else\n\t\tdisplayDrawXBitmap(DISPLAY_SIZE_X - UI_AES_PADLOCK_W - 3, 14, uiAesPadlockBitmap, UI_AES_PADLOCK_W, UI_AES_PADLOCK_H, true);\n#endif" in blk, "Г4: без режиму -- рядок малювання замка (x=147) ТОЙ САМИЙ, що у стоку")
    check(re.search(r"#if defined\(ENABLE_AES\) && defined\(ENABLE_DMR_DATA\) && defined\(DUAL_CHANNEL_ENABLED\)\n// R98-FIX10", src) is not None, "Г2: uiAesPadlockX() -- під ENABLE_AES && ENABLE_DMR_DATA && DUAL_CHANNEL_ENABLED")
    check("static int16_t uiAesPadlockX(int16_t defaultX);" in src[:src.find("void uiDrawAesEnabledIcon(void)")][-400:] and "#if defined(ENABLE_DMR_DATA) && defined(DUAL_CHANNEL_ENABLED)\nstatic int16_t uiAesPadlockX" in src, "Г3: попереднє оголошення -- під тими ж умовами")

    print("перевірок: %d, провалів: %d" % (N[0], len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
