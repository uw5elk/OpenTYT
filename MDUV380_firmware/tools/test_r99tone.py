# -*- coding: utf-8 -*-
"""test_r99tone.py -- R99-TONE: «Тон-відгук» (FM).

Хост: СПРАВЖНІЙ application/source/functions/tone_reply.c (-DTONE_REPLY_HOST_TEST) -- стан-машина, межі, блок 19.
  А  одна рація: сигнал >= порогу -> після затримки тон заданої тривалості; короткий сигнал (< порогу) -- без відгуку; новий сигнал у затримці --
     відгук після нього; сторож після відгуку; заборона TX -- мовчить; скасування (PTT/клавіша) у затримці й у тоні; вимкнення під час тону
  Б  межі: частота 300..3000 крок 50, тривалість 0,1..5 с (жорстка межа навіть при «зламаному» значенні), затримка 0..5 с; блок 19 туди-назад,
     невідома версія -- типові значення
  В  дві рації з функцією, що чують одна одну: після чужого сигналу обмін затухає (кожна відповідає не більше разу), для всіх поєднань меж
  Г  проводка на рації (за текстом коду): PTT скасовує, тік у головному циклі, після старту вимкнено, заборони TX, блок 19, меню в кінці,
     індикатор у шапці, прапорець у Makefile / build-ukrainian / syntax_check
  Д  мутанти: без порогу, без сторожа, без скасування, без межі тривалості -- ловляться
"""
import os, re, subprocess, sys, tempfile, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)
APP = os.path.join(FW, "application")
SRC = os.path.join(APP, "source", "functions", "tone_reply.c")
HDR = os.path.join(APP, "include", "functions", "tone_reply.h")
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


HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include "functions/tone_reply.h"

static toneReplyCfg_t cfgOf(int f, int d, int dl) { toneReplyCfg_t c; c.freqHz = (uint16_t)f; c.durDs = (uint8_t)d; c.delayDs = (uint8_t)dl; return c; }

/* одна рація: сигнал [0, sig) мс, далі тиша; повертає моменти START/STOP */
static void one(const char *tag, uint32_t sig, toneReplyCfg_t c, int allowed, uint32_t cancelAt, uint32_t disableAt, uint32_t sig2From, uint32_t sig2To)
{
	toneReplySm_t s; memset(&s, 0, sizeof s);
	printf("%s", tag);
	for (uint32_t t = 0; t <= 40000; t += 10)
	{
		int rx = ((t < sig) || ((t >= sig2From) && (t < sig2To))) && (s.state != TR_ST_TX);
		int act = toneReplyStep(&s, 100000U + t, (disableAt == 0) || (t < disableAt), rx, allowed, (cancelAt != 0) && (t == cancelAt), &c);
		if (act == TR_ACT_START) printf(" S%u", (unsigned)t);
		if (act == TR_ACT_STOP) printf(" E%u", (unsigned)t);
	}
	printf("\n");
}

/* дві рації: людина передає [0, 2000) мс; кожна чує людину або тон іншої */
static void two(int dA, int lA, int dB, int lB)
{
	toneReplySm_t a, b; memset(&a, 0, sizeof a); memset(&b, 0, sizeof b);
	toneReplyCfg_t ca = cfgOf(1000, dA, lA), cb = cfgOf(1200, dB, lB);
	int nA = 0, nB = 0, txA = 0, txB = 0;
	for (uint32_t t = 0; t <= 120000; t += 10)
	{
		int human = (t < 2000);
		int ra = (human || txB) && !txA, rb = (human || txA) && !txB;
		int x = toneReplyStep(&a, t, 1, ra, 1, 0, &ca), y = toneReplyStep(&b, t, 1, rb, 1, 0, &cb);
		if (x == TR_ACT_START) { txA = 1; nA++; } else if (x == TR_ACT_STOP) txA = 0;
		if (y == TR_ACT_START) { txB = 1; nB++; } else if (y == TR_ACT_STOP) txB = 0;
	}
	printf("TWO %d %d %d %d %d %d %d %d\n", dA, lA, dB, lB, nA, nB, txA, txB);
}

int main(void)
{
	toneReplyCfg_t c = cfgOf(1000, 10, 5);
	one("BASE", 2000, c, 1, 0, 0, 0, 0);            /* сигнал 2 с, затримка 0,5 с, тон 1 с */
	one("SHORT", 900, c, 1, 0, 0, 0, 0);            /* коротший за поріг -- мовчить */
	one("THR", 1000, c, 1, 0, 0, 0, 0);             /* рівно поріг -- відповідає */
	one("AGAIN", 2000, c, 1, 0, 0, 2200, 3500);     /* у затримці знову сигнал -- відгук після нього */
	one("NOTX", 2000, c, 0, 0, 0, 0, 0);            /* передача заборонена -- мовчить */
	one("CANCD", 2000, c, 1, 2200, 0, 0, 0);        /* клавіша/PTT у затримці -- відгуку нема */
	one("CANCT", 2000, c, 1, 2800, 0, 0, 0);        /* PTT під час тону -- зупинка негайно */
	one("DISAB", 2000, c, 1, 0, 2800, 0, 0);        /* вимкнення під час тону -- зупинка */
	one("GUARD", 2000, c, 1, 0, 0, 4000, 6000);     /* сигнал у сторожі -- без нового відгуку */
	one("AFTER", 2000, c, 1, 0, 0, 16000, 18000);   /* сигнал після сторожа -- новий відгук */
	toneReplyCfg_t big = cfgOf(1000, 200, 0);        /* «зламана» тривалість (повз межі) -- однаково не більше 5 с */
	one("HARD", 2000, big, 1, 0, 0, 0, 0);
	/* межі */
	int fs[] = { 0, 299, 300, 324, 325, 1000, 2999, 3000, 3001, 65535 };
	printf("CLAMPF");
	for (int i = 0; i < 10; i++) { toneReplyCfg_t k = cfgOf(fs[i], 10, 5); toneReplyCfgClamp(&k); printf(" %u", k.freqHz); }
	printf("\nCLAMPD");
	int ds[] = { 0, 1, 50, 51, 255 };
	for (int i = 0; i < 5; i++) { toneReplyCfg_t k = cfgOf(1000, ds[i], ds[i]); toneReplyCfgClamp(&k); printf(" %u/%u", k.durDs, k.delayDs); }
	printf("\n");
	/* блок */
	{
		toneReplyOnFlash_t raw; toneReplyCfg_t k = cfgOf(2450, 37, 12), r;
		toneReplyCfgBuild(&raw, &k);
		int ok = toneReplyCfgParse(&raw, &r);
		const uint8_t *p = (const uint8_t *)&raw;
		printf("BLOCK %d %u %u %u size=%u bytes=%02x%02x%02x%02x%02x%02x%02x%02x\n", ok, r.freqHz, r.durDs, r.delayDs, (unsigned)sizeof raw, p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7]);
		raw.version = 7; ok = toneReplyCfgParse(&raw, &r);
		printf("BADVER %d %u %u %u\n", ok, r.freqHz, r.durDs, r.delayDs);
	}
	/* дві рації */
	int lv[] = { 0, 5, 50 }, dv[] = { 1, 10, 50 };
	for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) for (int k = 0; k < 3; k++) for (int l = 0; l < 3; l++) two(dv[i], lv[j], dv[k], lv[l]);
	return 0;
}
'''


def build(src_text):
    d = tempfile.mkdtemp(prefix="r99tone_")
    try:
        srcp = os.path.join(d, "tone_reply.c"); open(srcp, "w", encoding="utf-8").write(src_text)
        hp = os.path.join(d, "h.c"); open(hp, "w").write(HARNESS)
        exe = os.path.join(d, "h")
        r = subprocess.run(["gcc", "-std=gnu11", "-Wall", "-DTONE_REPLY_HOST_TEST", "-I" + os.path.join(APP, "include"), "-o", exe, hp, srcp], capture_output=True, text=True)
        if r.returncode != 0:
            return None, r.stderr[-1500:]
        return subprocess.run([exe], capture_output=True, text=True, timeout=120).stdout, ""
    finally:
        shutil.rmtree(d, ignore_errors=True)


def parse(out):
    res = {}
    for l in out.splitlines():
        p = l.split()
        if p and p[0] not in ("TWO", "CLAMPF", "CLAMPD", "BLOCK", "BADVER"):
            res[p[0]] = [(x[0], int(x[1:])) for x in p[1:]]
    two = [tuple(int(v) for v in l.split()[1:]) for l in out.splitlines() if l.startswith("TWO")]
    return res, two


def core_checks(out, tag=""):
    r, two = parse(out)
    ok = True

    def want(c, m):
        nonlocal ok
        ok = ok and c
        check(c, m + tag)
    want(r.get("BASE") == [("S", 2500), ("E", 3500)], "А1: сигнал 2 с -> тон після затримки 0,5 с (2500 мс) тривалістю 1 с: %r" % r.get("BASE"))
    want(r.get("SHORT") == [], "А2: сигнал коротший за поріг 1 с -- без відгуку: %r" % r.get("SHORT"))
    want(r.get("THR") == [("S", 1500), ("E", 2500)], "А3: сигнал рівно 1 с -- відгук: %r" % r.get("THR"))
    want(r.get("AGAIN") == [("S", 4000), ("E", 5000)], "А4: новий сигнал у затримці -- відгук після нього: %r" % r.get("AGAIN"))
    want(r.get("NOTX") == [], "А5: передача заборонена -- мовчить: %r" % r.get("NOTX"))
    want(r.get("CANCD") == [], "А6: PTT/клавіша в затримці -- відгуку нема: %r" % r.get("CANCD"))
    want(r.get("CANCT") == [("S", 2500), ("E", 2800)], "А7: PTT під час тону -- зупинка в той самий тік: %r" % r.get("CANCT"))
    want(r.get("DISAB") == [("S", 2500), ("E", 2800)], "А8: вимкнення під час тону -- зупинка: %r" % r.get("DISAB"))
    want(r.get("GUARD") == [("S", 2500), ("E", 3500)], "А9: сигнал у сторожі -- нового відгуку нема: %r" % r.get("GUARD"))
    g = r.get("AFTER") or []
    want(len(g) == 4 and g[2] == ("S", 18500), "А10: сигнал після сторожа (11 с) -- новий відгук: %r" % g)
    want(r.get("HARD") == [("S", 2010), ("E", 7010)], "Б1: «зламана» тривалість 20 с -- однаково не більше 5 с (жорстка межа): %r" % r.get("HARD"))
    worst = max((t[4] + t[5]) for t in two) if two else 99
    hang = [t for t in two if t[6] or t[7]]
    want(two and len(two) == 81 and all(t[4] <= 1 and t[5] <= 1 for t in two) and not hang,
         "В1: дві рації (81 поєднання меж затримки/тривалості): кожна відповідає не більше разу, обмін затухає, ніхто не лишився в передачі: найгірше %d відгуків; %r" %
         (worst, [t for t in two if t[4] > 1 or t[5] > 1][:3]))
    return ok


def main():
    if not shutil.which("gcc"):
        print("ПРОПУСК: gcc нема"); return finish()
    src = rd(SRC)
    out, err = build(src)
    check(out is not None, "0: хостова збірка tone_reply.c: %s" % err)
    if out is None:
        return finish()
    core_checks(out)
    m = re.search(r"CLAMPF (.*)", out)
    check(m and m.group(1).split() == ["300", "300", "300", "300", "350", "1000", "3000", "3000", "3000", "3000"], "Б2: частота -- 300..3000 Гц, крок 50: %r" % (str(m and m.group(1)),))
    m = re.search(r"CLAMPD (.*)", out)
    check(m and m.group(1).split() == ["1/0", "1/1", "50/50", "50/50", "50/50"], "Б3: тривалість 1..50 (×100 мс), затримка 0..50: %r" % (str(m and m.group(1)),))
    m = re.search(r"BLOCK (\d) (\d+) (\d+) (\d+) size=(\d+) bytes=(\w+)", out)
    check(m and m.groups() == ("1", "2450", "37", "12", "8", "01250c0092090000"), "Б4: блок 19 -- 8 Б, [0] версія 1, [1] тривалість, [2] затримка, [4..5] частота LE: %r" % (str(m and m.groups()),))
    m = re.search(r"BADVER (\d) (\d+) (\d+) (\d+)", out)
    check(m and m.groups() == ("0", "1000", "10", "5"), "Б5: невідома версія -- типові 1000 Гц / 1,0 с / 0,5 с: %r" % (str(m and m.groups()),))

    # ---- Г: проводка
    h = rd(HDR)
    check("#if defined(ENABLE_TONE_REPLY) && defined(LANGUAGE_BUILD_UKRAINIAN) && defined(PLATFORM_MDUV380)\n#define TONE_REPLY_ENABLED 1" in h,
          "Г1: TONE_REPLY_ENABLED -- лише ENABLE_TONE_REPLY + українська + UV380")
    check("#define TR_GUARD_MS         ((TR_DELAY_MAX * 100U) + (TR_DUR_MAX * 100U) + TR_THRESH_MS)" in h and "#define TR_THRESH_MS        1000U" in h and "#define TR_DUR_MAX          50U" in h,
          "Г2: поріг 1 с, жорстка межа 5 с, сторож = макс. затримка + макс. тривалість + поріг")
    ld = src[src.index("void toneReplyLoad(void)"):]
    ld = ld[:ld.index("\n}\n")]
    check("s_trEnabled = 0U;" in ld and "enabled" not in h[h.index("typedef struct\n{\n\tuint8_t version;"):h.index("} toneReplyOnFlash_t;")],
          "Г3: «увімкнено» не зберігається (блок без такого поля), після старту -- вимкнено")
    al = src[src.index("static bool trTxAllowed(void)"):]
    al = al[:al.index("\n}\n")]
    need = ["UI_CHANNEL_MODE", "UI_VFO_MODE", "RADIO_MODE_ANALOG", "txFreq == 0U", "CHANNEL_FLAG_RX_ONLY", "BIT_TX_INHIBIT", "trxCheckFrequencyInAmateurBand",
            "USB_MODE_HOTSPOT", "Scan.active", "dcIsEnabled()", "dmrRctlIsInhibited()", "trxTransmissionEnabled", "aprsBeaconingIsTransmitting()"]
    check(all(k in al for k in need), "Г4: заборони передачі: %r" % [k for k in need if k not in al])
    am = rd(os.path.join(APP, "source", "applicationMain.c"))
    check(re.search(r"dmrRctlMonitorCancel\(\);\n#if defined\(TONE_REPLY_ENABLED\)\n\t+toneReplyAbort\(\);", am) is not None, "Г5: PTT -- toneReplyAbort() до відкриття екрана передачі")
    check(re.search(r"aprsBeaconingTick\(&ev\);\n#if defined\(TONE_REPLY_ENABLED\)\n\t+toneReplyTick\(&ev\);", am) is not None and
          re.search(r"#if defined\(TONE_REPLY_ENABLED\)\n\ttoneReplyLoad\(\);", am) is not None, "Г6: тік у головному циклі (UI-задача), завантаження на старті")
    tk = src[src.index("void toneReplyTick(const void *evp)"):]
    tk = tk[:tk.index("\n}\n")]
    check("(KEY_EVENT | BUTTON_EVENT)" in tk and "currentChannelData->txFreq != s_trTxFreq" in tk, "Г7: будь-яка клавіша/кнопка і зміна каналу -- скасування")
    cp = rd(os.path.join(APP, "include", "functions", "codeplug.h"))
    check("CODEPLUG_CUSTOM_DATA_TYPE_TONE_REPLY_CFG = 19" in cp, "Г8: custom-data блок 19")
    mro = rd(os.path.join(APP, "source", "user_interface", "menuRadioOptions.c"))
    en = mro[mro.index("enum\n{\n\tRADIO_OPTIONS_MENU_TX_FREQ_LIMITS"):mro.index("NUM_RADIO_OPTIONS_MENU_ITEMS\n};")]
    check(en.rstrip().endswith("RADIO_OPTIONS_MENU_TONE_DELAY,\n#endif") and en.index("RADIO_OPTIONS_MENU_TONE_REPLY") > en.index("RADIO_OPTIONS_MENU_TA_DIAG"),
          "Г9: пункти «Тон-відгук» -- останні в enum (номери швидких клавіш не зсуваються)")
    check("toneReplySave();" in mro and "toneReplyMenuCancel();" in mro and "toneReplyMenuBegin();" in mro, "Г10: меню: GREEN -- запис блоку 19, RED/вихід -- скасування")
    uu = rd(os.path.join(APP, "source", "user_interface", "uiUtilities.c"))
    check("TONEREPLY_HDR" in uu and "toneReplyIsEnabled()" in uu and "(radioMode == RADIO_MODE_ANALOG) && toneReplyIsEnabled()" in uu, "Г11: індикатор «ТВ» у шапці FM (місце CC)")
    mk = rd(os.path.join(FW, "Makefile"))
    check("ifeq ($(ENABLE_TONE_REPLY),1)\nDEFS += -DENABLE_TONE_REPLY" in mk, "Г12: прапорець у Makefile")
    yml = rd(os.path.join(os.path.dirname(FW), ".github", "workflows", "build.yml"))
    runs = [l for l in yml.splitlines() if "run: make" in l and "ENABLE_TONE_REPLY=1" in l]
    check(len(runs) == 1 and "ENABLE_DUAL_CHANNEL=1" in runs[0], "Г13: ENABLE_TONE_REPLY=1 лише в build-ukrainian (її вбудовує прошивальник): %d" % len(runs))
    sc = rd(os.path.join(FW, "tools", "syntax_check.sh"))
    check(re.search(r"CONFIGS=\([^)]* TONE TONEEN TONEBARE\)", sc) is not None, "Г14: syntax_check -- конфігурації TONE/TONEEN/TONEBARE")
    ua = open(os.path.join(APP, "include", "user_interface", "languages", "tonereply_ua.h"), "rb").read().decode("cp1251")
    mm = dict(re.findall(r'#define\s+(TONEREPLY_\w+)\s+"([^"]*)"', ua))
    lines = [mm["TONEREPLY_MENU_ON"] + ":" + max(mm["TONEREPLY_ON"], mm["TONEREPLY_OFF"], key=len), mm["TONEREPLY_MENU_FREQ"] + ":3000",
             mm["TONEREPLY_MENU_DUR"] + ":5.0" + mm["TONEREPLY_SEC"], mm["TONEREPLY_MENU_DELAY"] + ":5.0" + mm["TONEREPLY_SEC"]]
    check(all(len(l) <= 16 for l in lines) and len(mm["TONEREPLY_HDR"]) == 2, "Г15: рядки меню <= 16 символів (найгірші значення), індикатор 2 символи: %r" % lines)

    # ---- Д: мутанти
    def mut(name, a, b):
        s2 = src.replace(a, b, 1)
        if s2 == src:
            check(False, "Д (%s): шаблон не знайдено" % name); return
        o2, e2 = build(s2)
        if o2 is None:
            check(True, "Д (%s): не збирається -- ловиться" % name); return
        n0 = len(FAILS); QUIET[0] = True
        ok = core_checks(o2, " [m]")
        QUIET[0] = False; del FAILS[n0:]
        check(not ok, "Д (%s): ловиться" % name)
    mut("без порогу", "if ((now - s->t) >= TR_THRESH_MS)", "if (1)")
    mut("без сторожа", "if (((now - s->t) >= TR_GUARD_MS) && (rxOpen == false))", "if (rxOpen == false)")
    mut("без скасування в тоні", "if (cancel || (txAllowed == false) || ((now - s->t) >= dur))", "if ((txAllowed == false) || ((now - s->t) >= dur))")
    mut("без межі тривалості", "dur = (uint32_t)((cfg->durDs > TR_DUR_MAX) ? TR_DUR_MAX : cfg->durDs) * 100U;", "dur = (uint32_t)cfg->durDs * 100U;")
    return finish()


def finish():
    print("test_r99tone: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
