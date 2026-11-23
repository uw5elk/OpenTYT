# -*- coding: utf-8 -*-
"""test_r100tone.py -- R100-TONE: «Тон-відгук» у головному меню, секунди, блок 19 v2, «увімкнено» зберігається.

Хост (справжній код):
  А  межі з констант tone_reply.h: частота 300..3000 крок 50, тривалість 1..60 с, затримка 0..10 с, крок 1 с; сторож = 10 + 60 + 1 = 71 с,
     ОБЧИСЛЕНИЙ з констант (зміна DUR_MAX_S змінює сторож); жорстка межа тривалості 60 с навіть при пошкодженому значенні
  Б  блок 19: v2 туди-назад з «увімкнено»; v1 -> міграція (секунди = округлення вгору, вимкнено); невідома версія / сміття -- типові, вимкнено
  В  обгортка (toneReplyLoad/Save/MenuCancel/SetEnabled з tone_reply.c, codeplug -- заглушка): блоку нема -- типові, вимкнено, без запису;
     v2 з «увімкнено» -- після старту ввімкнено, нічого не передається; v1 -- у флеші лишається v1, доки GREEN (тоді v2 навіть без змін);
     RED повертає збережене; GREEN без змін -- флеш не чіпається
  Г  підменю (trmChange з menuToneReply.c): ←/→ на межах не виходять за межі; Увімк/Вимк
Текст коду:
  Д  головне меню: MENU_TONE_REPLY після MENU_RXGROUPS, перед NUM_MENU_ENTRIES (ID > 31 -- поза QuickKey, наявні не зсуваються), під TONE_REPLY_ENABLED;
     явний індекс у data[], menuFunctions[], останній у mainMenuItems; назва -- TONEREPLY_MAIN без голосової підказки; підменю: 4 рядки, GREEN -- запис,
     RED -- повернення, exit-callback; «Опції рації» -- enum ідентичний стану до R99 (e2f20ed)
  Е  мутанти: без жорсткої межі тривалості, сторож числом, без міграції v1, v1 без примусового запису -- ловляться
"""
import os, re, subprocess, sys, tempfile, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)
APP = os.path.join(FW, "application")
INC = os.path.join(APP, "include")
SRC = os.path.join(APP, "source", "functions", "tone_reply.c")
HDR = os.path.join(INC, "functions", "tone_reply.h")
MENU = os.path.join(APP, "source", "user_interface", "menuToneReply.c")
FAILS = []
N = [0]
QUIET = [False]


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m)
        if not QUIET[0]:
            print("ПРОВАЛ: " + m)


def rd(p):
    return open(p, encoding="utf-8").read()


def carve(text, start, end_marker):
    a = text.index(start)
    return text[a:text.index(end_marker, a)]


# enum «Опцій рації» в e2f20ed (R98-FIX15, до R99) -- номери швидких клавіш наявних пунктів мають лишитися такими самими
PRE_R99_RADIO_ENUM = """enum
{
	RADIO_OPTIONS_MENU_TX_FREQ_LIMITS = 0U,
	RADIO_OPTIONS_TX_INHIBIT,
	RADIO_OPTIONS_MENU_DMR_MONITOR_CAPTURE_TIMEOUT,
	RADIO_OPTIONS_MENU_SCAN_DELAY,
	RADIO_OPTIONS_MENU_SCAN_STEP_TIME,
	RADIO_OPTIONS_MENU_SCAN_MODE,
	RADIO_OPTIONS_MENU_SCAN_ON_BOOT,
	RADIO_OPTIONS_MENU_SQUELCH_DEFAULT_VHF,
#if ! (defined(PLATFORM_MD9600) || defined(PLATFORM_MD380))
	RADIO_OPTIONS_MENU_SQUELCH_DEFAULT_220MHz,
#endif
	RADIO_OPTIONS_MENU_SQUELCH_DEFAULT_UHF,
	RADIO_OPTIONS_MENU_PTT_TOGGLE,
	RADIO_OPTIONS_MENU_PRIVATE_CALLS,
	RADIO_OPTIONS_MENU_USER_POWER,
	RADIO_OPTIONS_MENU_DMR_CRC,
#if defined(PLATFORM_MDUV380) && !defined(PLATFORM_VARIANT_UV380_PLUS_10W)
	RADIO_OPTIONS_MENU_FORCE_10W,
#endif
#if defined(VOLUME_PROBE)
	RADIO_OPTIONS_MENU_VOL_PROBE,        /* R77A: діагностика -- найостаннішим */
#endif
#if defined(TA_DIAG)
	RADIO_OPTIONS_MENU_TA_DIAG,          /* R88: діагностика Talker Alias / GPS-блока LC -- найостаннішим */
#endif
	"""

# Хост-обгортка: статичні змінні й Load/Save/Cancel з tone_reply.c + trmChange з menuToneReply.c; codeplug -- заглушка з 8 байтами «флешу».
WRAP_PRE = r'''
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include "functions/tone_reply.h"
#define CODEPLUG_CUSTOM_DATA_TYPE_TONE_REPLY_CFG 19
static uint8_t g_flash[8]; static int g_present = 0, g_writes = 0;
static bool codeplugGetOpenGD77CustomDataBounded(int type, uint8_t *d, int len)
{ if ((type != 19) || !g_present || (len != 8)) return false; memcpy(d, g_flash, 8); return true; }
static bool codeplugSetOpenGD77CustomData(int type, uint8_t *d, int len)
{ if ((type != 19) || (len != 8)) return false; memcpy(g_flash, d, 8); g_present = 1; g_writes++; return true; }
'''

WRAP_MAIN = r'''
enum { TRM_ON = 0, TRM_FREQ, TRM_DUR, TRM_DELAY, TRM_ROWS };
%(TRM)s
static void dump(const char *tag)
{
	toneReplyCfg_t *c = toneReplyCfg();
	printf("%%s en=%%d tx=%%d f=%%u d=%%u l=%%u w=%%d flash=", tag, (int)toneReplyIsEnabled(), (int)toneReplyIsTransmitting(), c->freqHz, c->durS, c->delayS, g_writes);
	for (int i = 0; i < 8; i++) printf("%%02x", g_flash[i]);
	printf("\n");
}
static void setFlash(const uint8_t *b) { memcpy(g_flash, b, 8); g_present = 1; g_writes = 0; }
int main(void)
{
	/* В1: блоку нема */
	g_present = 0; g_writes = 0; memset(g_flash, 0, 8); toneReplyLoad(); dump("NONE");
	toneReplySave(); dump("NONE_SAVE");
	/* В2: v2 з «увімкнено» */
	{ const uint8_t b[8] = { 2, 30, 5, 1, 0xB0, 0x04, 0, 0 }; setFlash(b); toneReplyLoad(); dump("V2ON"); }
	/* В3: v1 (×100 мс): тривалість 0,5 с -> 1 с, затримка 2,5 с -> 3 с; частота 1750 */
	{ const uint8_t b[8] = { 1, 5, 25, 0, 0xD6, 0x06, 0, 0 }; setFlash(b); toneReplyLoad(); dump("V1"); toneReplyMenuCancel(); dump("V1_RED"); toneReplySave(); dump("V1_GREEN"); toneReplyLoad(); dump("V1_RELOAD"); }
	/* В4: v1 з крайніми значеннями: 0 -> 1 с (мінімум), 255 (25,5 с) -> 26 с; затримка 50 (5 с) -> 5 с */
	{ const uint8_t b[8] = { 1, 255, 50, 0, 0xE8, 0x03, 0, 0 }; setFlash(b); toneReplyLoad(); dump("V1BIG"); }
	{ const uint8_t b[8] = { 1, 0, 0, 0, 0xE8, 0x03, 0, 0 }; setFlash(b); toneReplyLoad(); dump("V1ZERO"); }
	/* В5: сміття */
	{ const uint8_t b[8] = { 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF }; setFlash(b); toneReplyLoad(); dump("JUNK"); }
	/* В6: меню: змінити, RED -- повернення; змінити, GREEN -- запис; GREEN без змін -- без запису */
	{ const uint8_t b[8] = { 2, 10, 2, 0, 0xE8, 0x03, 0, 0 }; setFlash(b); toneReplyLoad();
	  trmChange(TRM_ON, 1); trmChange(TRM_FREQ, 1); dump("EDIT"); toneReplyMenuCancel(); dump("RED");
	  trmChange(TRM_ON, 1); trmChange(TRM_DUR, 1); toneReplySave(); dump("GREEN"); toneReplySave(); dump("GREEN2"); toneReplyLoad(); dump("RELOAD"); }
	/* Г: межі в підменю */
	{ toneReplyCfg_t *c = toneReplyCfg();
	  c->freqHz = 300; trmChange(TRM_FREQ, -1); printf("FMIN %%u\n", c->freqHz);
	  c->freqHz = 3000; trmChange(TRM_FREQ, 1); printf("FMAX %%u\n", c->freqHz);
	  c->freqHz = 350; trmChange(TRM_FREQ, -1); printf("FSTEP %%u\n", c->freqHz);
	  c->durS = 1; trmChange(TRM_DUR, -1); printf("DMIN %%u\n", c->durS);
	  c->durS = 60; trmChange(TRM_DUR, 1); printf("DMAX %%u\n", c->durS);
	  c->durS = 10; trmChange(TRM_DUR, 1); printf("DSTEP %%u\n", c->durS);
	  c->delayS = 0; trmChange(TRM_DELAY, -1); printf("LMIN %%u\n", c->delayS);
	  c->delayS = 10; trmChange(TRM_DELAY, 1); printf("LMAX %%u\n", c->delayS);
	  trmChange(TRM_ON, 1); printf("ON %%d\n", (int)toneReplyIsEnabled()); trmChange(TRM_ON, -1); printf("OFF %%d\n", (int)toneReplyIsEnabled()); }
	/* А: сторож і жорстка межа */
	printf("GUARD %%u\n", (unsigned)TONE_REPLY_GUARD_MS);
	{ toneReplySm_t s; memset(&s, 0, sizeof s); toneReplyCfg_t k = { 1000, 250, 0 }; uint32_t st = 0, en = 0;
	  for (uint32_t t = 0; t <= 300000; t += 10) { int a = toneReplyStep(&s, t, true, (t < 2000), true, false, &k); if (a == TR_ACT_START) st = t; if (a == TR_ACT_STOP) en = t; }
	  printf("HARD %%u\n", (unsigned)(en - st)); }
	return 0;
}
'''


def build_run(src_text, hdr_text, menu_text):
    d = tempfile.mkdtemp(prefix="r100tone_")
    try:
        os.makedirs(os.path.join(d, "functions"))
        open(os.path.join(d, "functions", "tone_reply.h"), "w", encoding="utf-8").write(hdr_text)
        pure = os.path.join(d, "pure.c"); open(pure, "w", encoding="utf-8").write(src_text)
        wrap = carve(src_text, "static toneReplySm_t  s_trSm;", "/* Чи можна передати тон зараз.")
        trm = carve(menu_text, "static void trmChange(int row, int dir)", "static void trmExit(void *data)")
        wp = os.path.join(d, "w.c")
        open(wp, "w", encoding="utf-8").write(WRAP_PRE + wrap + (WRAP_MAIN % {"TRM": trm}))
        exe = os.path.join(d, "h")
        r = subprocess.run(["gcc", "-std=gnu11", "-Wall", "-Wno-unused-function", "-DTONE_REPLY_HOST_TEST", "-I" + d, "-I" + INC, "-o", exe, wp, pure],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return None, r.stderr[-2000:]
        return subprocess.run([exe], capture_output=True, text=True, timeout=120).stdout, ""
    finally:
        shutil.rmtree(d, ignore_errors=True)


def consts(h):
    return {m.group(1): int(m.group(2)) for m in re.finditer(r"#define\s+(TONE_REPLY_\w+)\s+(\d+)U\b", h)}


def host_checks(out, hdr_text, tag=""):
    ok = [True]

    def want(c, m):
        ok[0] = ok[0] and bool(c)
        check(c, m + tag)
    L = {}
    for l in out.splitlines():
        p = l.split(None, 1)
        L[p[0]] = p[1] if len(p) > 1 else ""
    k = consts(hdr_text)
    want(L.get("NONE") == "en=0 tx=0 f=1000 d=10 l=2 w=0 flash=0000000000000000", "В1: блоку нема -- 1000 Гц / 10 с / 2 с, вимкнено: %r" % L.get("NONE"))
    want(L.get("NONE_SAVE", "").startswith("en=0 tx=0 f=1000 d=10 l=2 w=0"), "В1: GREEN без змін при типових -- флеш не чіпається: %r" % L.get("NONE_SAVE"))
    want(L.get("V2ON") == "en=1 tx=0 f=1200 d=30 l=5 w=0 flash=021e0501b0040000", "В2: v2 з «увімкнено» -- після старту ввімкнено, нічого не передається: %r" % L.get("V2ON"))
    want(L.get("V1") == "en=0 tx=0 f=1750 d=1 l=3 w=0 flash=01051900d6060000", "В3: v1 -- секунди вгору (0,5 -> 1, 2,5 -> 3), вимкнено, у флеші v1: %r" % L.get("V1"))
    want(L.get("V1_RED") == "en=0 tx=0 f=1750 d=1 l=3 w=0 flash=01051900d6060000", "В3: RED на v1 -- вимкнено, флеш не чіпається: %r" % L.get("V1_RED"))
    want(L.get("V1_GREEN") == "en=0 tx=0 f=1750 d=1 l=3 w=1 flash=02010300d6060000", "В3: GREEN на v1 без змін -- записано v2: %r" % L.get("V1_GREEN"))
    want(L.get("V1_RELOAD") == "en=0 tx=0 f=1750 d=1 l=3 w=1 flash=02010300d6060000", "В3: після перезапуску -- ті самі значення з v2: %r" % L.get("V1_RELOAD"))
    want((L.get("V1BIG") or "").startswith("en=0 tx=0 f=1000 d=26 l=5 w=0"), "В4: v1 25,5 с -> 26 с, затримка 5 с -> 5 с: %r" % L.get("V1BIG"))
    want((L.get("V1ZERO") or "").startswith("en=0 tx=0 f=1000 d=1 l=0 w=0"), "В4: v1 0 -> мінімум 1 с, затримка 0: %r" % L.get("V1ZERO"))
    want((L.get("JUNK") or "").startswith("en=0 tx=0 f=1000 d=10 l=2 w=0"), "В5: сміття (0xFF…) -- типові, вимкнено: %r" % L.get("JUNK"))
    want((L.get("EDIT") or "").startswith("en=1 tx=0 f=1050 d=10 l=2"), "В6: ←/→ змінюють поточні значення: %r" % L.get("EDIT"))
    want(L.get("RED") == "en=0 tx=0 f=1000 d=10 l=2 w=0 flash=020a0200e8030000", "В6: RED -- повернення збереженого, без запису: %r" % L.get("RED"))
    want(L.get("GREEN") == "en=1 tx=0 f=1000 d=11 l=2 w=1 flash=020b0201e8030000", "В6: GREEN -- запис v2 з «увімкнено»: %r" % L.get("GREEN"))
    want((L.get("GREEN2") or "").startswith("en=1 tx=0 f=1000 d=11 l=2 w=1"), "В6: повторний GREEN без змін -- флеш не чіпається: %r" % L.get("GREEN2"))
    want((L.get("RELOAD") or "").startswith("en=1 tx=0 f=1000 d=11 l=2 w=1"), "В6: «увімкнено» відновлюється після перезапуску: %r" % L.get("RELOAD"))
    exp = {"FMIN": str(k.get("TONE_REPLY_FREQ_MIN")), "FMAX": str(k.get("TONE_REPLY_FREQ_MAX")), "FSTEP": "300", "DMIN": str(k.get("TONE_REPLY_DUR_MIN_S")),
           "DMAX": str(k.get("TONE_REPLY_DUR_MAX_S")), "DSTEP": "11", "LMIN": str(k.get("TONE_REPLY_DELAY_MIN_S")), "LMAX": str(k.get("TONE_REPLY_DELAY_MAX_S")),
           "ON": "1", "OFF": "0"}
    want(all(L.get(x) == v for x, v in exp.items()), "Г1: підменю ←/→ -- у межах констант, крок 50 Гц / 1 с: %r" % {x: L.get(x) for x in exp})
    gexp = (k.get("TONE_REPLY_DELAY_MAX_S", 0) + k.get("TONE_REPLY_DUR_MAX_S", 0)) * 1000 + k.get("TONE_REPLY_THRESH_MS", 0)
    want(L.get("GUARD") == str(gexp), "А2: сторож = (макс. затримка + макс. тривалість) * 1000 + поріг = %d мс: %r" % (gexp, L.get("GUARD")))
    want(L.get("HARD") == str(k.get("TONE_REPLY_DUR_MAX_S", 0) * 1000), "А3: пошкоджена тривалість 250 с -- тон не довший за %d с: %r" % (k.get("TONE_REPLY_DUR_MAX_S", 0), L.get("HARD")))
    return ok[0]


def guard_follows_constants(src, hdr, menu):
    """А4: зміна DUR_MAX_S (60 -> 30) змінює сторож (71 с -> 41 с) -- сторож обчислюється з констант, а не записаний числом."""
    h2 = hdr.replace("#define TONE_REPLY_DUR_MAX_S     60U", "#define TONE_REPLY_DUR_MAX_S     30U", 1)
    if h2 == hdr:
        return False
    o, e = build_run(src, h2, menu)
    if o is None:
        return False
    m = re.search(r"^GUARD (\d+)$", o, re.M)
    return bool(m) and m.group(1) == "41000"


def main():
    if not shutil.which("gcc"):
        print("ПРОПУСК: gcc нема -- НЕ «пройдено»"); FAILS.append("gcc нема"); return finish()
    src, hdr, menu = rd(SRC), rd(HDR), rd(MENU)
    k = consts(hdr)
    check(k.get("TONE_REPLY_DUR_MIN_S") == 1 and k.get("TONE_REPLY_DUR_MAX_S") == 60 and k.get("TONE_REPLY_DELAY_MIN_S") == 0 and k.get("TONE_REPLY_DELAY_MAX_S") == 10 and
          k.get("TONE_REPLY_STEP_S") == 1 and k.get("TONE_REPLY_FREQ_MIN") == 300 and k.get("TONE_REPLY_FREQ_MAX") == 3000 and k.get("TONE_REPLY_FREQ_STEP") == 50 and
          k.get("TONE_REPLY_FREQ_DEF") == 1000 and k.get("TONE_REPLY_DUR_DEF_S") == 10 and k.get("TONE_REPLY_DELAY_DEF_S") == 2 and k.get("TONE_REPLY_CFG_VERSION") == 2,
          "А1: константи: тривалість 1..60 с, затримка 0..10 с, крок 1 с, 300..3000 Гц крок 50, типові 1000/10/2, версія 2: %r" % k)
    check("_Static_assert(TONE_REPLY_GUARD_MS >=" in hdr, "А1: _Static_assert на сторож")
    out, err = build_run(src, hdr, menu)
    check(out is not None, "0: хостова збірка (tone_reply.c + обгортка + trmChange): %s" % err)
    if out is None:
        return finish()
    host_checks(out, hdr)
    check(guard_follows_constants(src, hdr, menu), "А4: сторож обчислюється з констант (DUR_MAX_S 30 -> сторож 41 с)")

    # ---- Д: проводка за текстом
    sh = rd(os.path.join(INC, "user_interface", "menuSystem.h"))
    sc = rd(os.path.join(APP, "source", "user_interface", "menuSystem.c"))
    dl = rd(os.path.join(APP, "source", "user_interface", "menuDisplayMenuList.c"))
    en = sh[sh.index("enum MENU_SCREENS"):] if "enum MENU_SCREENS" in sh else sh
    en = en[:en.index("NUM_MENU_ENTRIES")]
    check(re.search(r"MENU_RXGROUPS,[^\n]*\n#endif\n#if defined\(TONE_REPLY_ENABLED\)\n\tMENU_TONE_REPLY,[^\n]*\n#endif\n\t$", en) is not None,
          "Д1: MENU_TONE_REPLY -- після MENU_RXGROUPS, останній перед NUM_MENU_ENTRIES, під TONE_REPLY_ENABLED (ID > 31: наявні швидкі клавіші не зсуваються)")
    check('#include "functions/tone_reply.h"' in sh, "Д1: menuSystem.h бачить TONE_REPLY_ENABLED")
    check(re.search(r"#if defined\(TONE_REPLY_ENABLED\)\n\t+\[MENU_TONE_REPLY\] = NULL,", sc) is not None, "Д2: явний індекс у menuDataGlobal.data[]")
    check(re.search(r"#if defined\(TONE_REPLY_ENABLED\)\n\t+\{ menuToneReply, +NULL, NULL, 0 \},", sc) is not None, "Д3: menuFunctions[] -- menuToneReply")
    mm = sc[sc.index("mainMenuItems"):]
    mm = mm[:mm.index("};")]
    check(re.search(r"#if defined\(TONE_REPLY_ENABLED\)\n(?:\s*//[^\n]*\n)*\s*\{ 0, MENU_TONE_REPLY \},\n#endif\n$", mm) is not None, "Д4: «Тон-відгук» -- останній пункт головного меню")
    check("menuName = TONEREPLY_MAIN;" in dl and re.search(r"#if defined\(TONE_REPLY_ENABLED\)\n\t+if \(isToneItem == false\)\n#endif", dl) is not None,
          "Д5: назва пункту -- TONEREPLY_MAIN, голосової підказки за вказівником на таблицю нема")
    check("#if defined(TONE_REPLY_ENABLED)" in menu and "TRM_ROWS };" in menu and "enum { TRM_ON = 0, TRM_FREQ, TRM_DUR, TRM_DELAY, TRM_ROWS };" in menu,
          "Д6: підменю -- 4 рядки, лише під TONE_REPLY_ENABLED")
    g = carve(menu, "if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))", "\n\t}\n")
    r = carve(menu, "if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))", "\n\t}\n")
    check("toneReplySave()" in g and "menuSystemPopPreviousMenu();" in g and "toneReplyMenuCancel();" in r and "menuSystemPopPreviousMenu();" in r and
          "menuSystemRegisterExitCallback(trmExit, NULL);" in menu and "toneReplyMenuCancel();" in carve(menu, "static void trmExit(void *data)\n{", "\n}\n"),
          "Д7: GREEN -- запис блоку 19 і вихід; RED і будь-який інший вихід -- повернення збереженого")
    mro = rd(os.path.join(APP, "source", "user_interface", "menuRadioOptions.c"))
    cur = mro[mro.index("enum\n{\n\tRADIO_OPTIONS_MENU_TX_FREQ_LIMITS"):mro.index("NUM_RADIO_OPTIONS_MENU_ITEMS\n};")]
    check(cur == PRE_R99_RADIO_ENUM, "Д8: enum «Опцій рації» -- як до R99 (номери інших пунктів не змінились)")
    check("toneReply" not in mro and "TONEREPLY" not in mro, "Д8: у «Опціях рації» про «Тон-відгук» нічого")

    # ---- Е: мутанти
    def mut(name, which, a, b):
        s2, h2, m2 = src, hdr, menu
        if which == "src":
            s2 = src.replace(a, b, 1); changed = s2 != src
        else:
            h2 = hdr.replace(a, b, 1); changed = h2 != hdr
        if not changed:
            check(False, "Е (%s): шаблон не знайдено" % name); return
        if name == "сторож числом":
            check(not guard_follows_constants(s2, h2, m2), "Е (%s): ловиться" % name); return
        o2, e2 = build_run(s2, h2, m2)
        if o2 is None:
            check(True, "Е (%s): не збирається -- ловиться" % name); return
        n0 = len(FAILS); QUIET[0] = True
        ok = host_checks(o2, h2, " [m]")
        QUIET[0] = False; del FAILS[n0:]
        check(not ok, "Е (%s): ловиться" % name)
    mut("без жорсткої межі тривалості", "src", "dur = (uint32_t)((cfg->durS > TONE_REPLY_DUR_MAX_S) ? TONE_REPLY_DUR_MAX_S : cfg->durS) * 1000U;",
        "dur = (uint32_t)cfg->durS * 1000U;")
    mut("сторож числом", "hdr", "#define TONE_REPLY_GUARD_MS      (((TONE_REPLY_DELAY_MAX_S + TONE_REPLY_DUR_MAX_S) * 1000U) + TONE_REPLY_THRESH_MS)",
        "#define TONE_REPLY_GUARD_MS      71000U")
    mut("без міграції v1", "src", "c->durS = trDsToS(raw->dur);", "c->durS = raw->dur;")
    mut("v1 без примусового запису", "src", "((ver == (int)TONE_REPLY_CFG_V1) ? TR_SAVED_V1 : s_trEnabled)", "s_trEnabled")
    mut("«увімкнено» не відновлюється", "src", "*enabled = ((raw->flags & TONE_REPLY_FLAG_ENABLED) != 0U);", "*enabled = false;")
    return finish()


def finish():
    print("test_r100tone: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
