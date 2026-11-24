# -*- coding: utf-8 -*-
"""test_r106smsstore.py -- R106-SMSSTORE: сховище SMS DMR у власному кільці секторів SPI-флешу (0x48000..0x4FFFF) замість custom-data блока 7.

Хост, частина 1: СПРАВЖНІЙ sms_flash_store.c (-DSMS_STORE_HOST_TEST) з МОДЕЛЛЮ NOR-флешу (стирання сектора -> 0xFF, програмування лише 1 -> 0,
обрив живлення до операції або ПОСЕРЕДИНІ неї -- половина байтів/половина сектора).
  А  туди-назад: образи 10, 11, 300, 1352 Б (байт-у-байт, хвіст обнуляється); межі довжини (9, 1353 -> відмова без стирання)
  Б  обрив після КОЖНОЇ операції стирання/програмування (і посеред неї) за заповнення 0, 1, 7, 8, 9 слотів: завантажується РІВНО попередній
     або новий образ, ніколи частковий; слота «цілий заголовок + нецілий образ» нема; поза ділянкою -- нуль операцій
  В  пошкодження: байт образу найновішого -> попередній; заголовок -> попередній; старший слот із підробленим seq -> відкинуто; усі -> -1
     (образ обнулено); сміття в ділянці -> -1 без падінь; переповнення seq (0xFFFFFFFF -> 0)
  Г  знос: 16 записів -> кожен з 8 слотів рівно двічі; найновіший цілий слот ніколи не стирається
  Д  «той самий»: smsfSameCore -- так для щойно записаного, ні для зміненого байта/іншої довжини/порожнього кільця
  Е  звірка: «залиплий» біт при програмуванні -> запис = false
Частина 2: СПРАВЖНІ dmr_sms.c + sms_flash_store.c з -DENABLE_SMS_STORE_FLASH -- tests/test_dmr_sms_flash.c (той самий бінарник, що в run_tests.sh):
     міграція «б», політика запису, тиша/квитанція, меню, дозапис при вимкненні, кільце по колу.
  Ж  проводка: прапорець у Makefile/CI/syntax_check, тік після dmrSmsRxTick, дозапис в обох шляхах вимкнення, programBytes і під SMS_STORE_FLASH,
     store_save/store_add під прапорцем, без SPI_Flash_sectorbuffer і без нових статичних змінних у dmr_sms.c
  З  мутанти ядра: заголовок перед образом, запис у найновіший слот, без CRC образу, без CRC заголовка, без звірки -- ловляться;
     мутанти dmr_sms.c: запис без відкладення, без тиші в каналі, меню перечитує сховище, блок 7 не очищується, без дозапису відкладених -- ловляться
"""
import os, re, subprocess, sys, tempfile, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)
APP = os.path.join(FW, "application")
CORE = os.path.join(APP, "source", "functions", "sms_flash_store.c")
SMS = os.path.join(APP, "source", "functions", "dmr_sms.c")
ITEST = os.path.join(FW, "tests", "test_dmr_sms_flash.c")
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
#include <stdlib.h>
#include <setjmp.h>
#include "functions/sms_flash_store.h"

#define FL_SIZE 0x60000UL
static uint8_t fl[FL_SIZE];
static long opCount = 0, cutAt = -1; static int cutMode = 0; static jmp_buf cutJmp;
static long erases[SMSF_SLOTS];
static uint32_t outside = 0;
static int stuck = 0;   /* 1: наступне програмування образу «залипає» в одному біті */
static int eraseNewest = 0;   /* стерто слот, що був найновішим цілим */

static uint32_t crc32(const uint8_t *p, int n) { uint32_t c = ~0U; while (n--) { c ^= *p++; for (int k = 0; k < 8; k++) c = (c >> 1) ^ (0xEDB88320U & (0U - (c & 1U))); } return ~c; }
static int slotValid(int i, uint32_t *seq)
{
	const uint8_t *h = &fl[SMSF_REGION_ADDR + i * 4096U];
	uint32_t magic, sq, ci, ch; uint16_t len;
	memcpy(&magic, h, 4); memcpy(&len, h + 6, 2); memcpy(&sq, h + 8, 4); memcpy(&ci, h + 12, 4); memcpy(&ch, h + 16, 4);
	if ((magic != SMSF_MAGIC) || (h[4] != SMSF_VERSION) || (len < 10) || (len > 1352) || (crc32(h, 16) != ch)) return 0;
	if (crc32(h + 32, len) != ci) return -1;   /* цілий заголовок, нецілий образ */
	if (seq) *seq = sq;
	return 1;
}
/* незалежно від модуля: найновіший цілий слот */
static int newestIndep(void)
{
	int best = -1; uint32_t bs = 0, s;
	for (int i = 0; i < (int)SMSF_SLOTS; i++) if (slotValid(i, &s) == 1) { if ((best < 0) || ((int32_t)(s - bs) > 0)) { best = i; bs = s; } }
	return best;
}
static int halfValid(void) { int n = 0; for (int i = 0; i < (int)SMSF_SLOTS; i++) if (slotValid(i, NULL) < 0) n++; return n; }

static int cutNow(void) { long k = opCount++; return (cutAt >= 0) && (k == cutAt); }
bool SPI_Flash_read(uint32_t a, uint8_t *buf, int n) { for (int i = 0; i < n; i++) buf[i] = (a + i < FL_SIZE) ? fl[a + i] : 0xFF; return true; }
bool SPI_Flash_eraseSector(uint32_t a)
{
	if (a % 4096U) { outside += 1000; return false; }
	if ((a < SMSF_REGION_ADDR) || (a >= SMSF_REGION_ADDR + SMSF_SLOTS * 4096U)) outside++;
	if ((int)((a - SMSF_REGION_ADDR) / 4096U) == newestIndep()) eraseNewest++;
	if (cutNow()) { if (cutMode) memset(&fl[a], 0xFF, 2048); longjmp(cutJmp, 1); }
	memset(&fl[a], 0xFF, 4096); erases[(a - SMSF_REGION_ADDR) / 4096U]++; return true;
}
bool SPI_Flash_programBytes(uint32_t a, const uint8_t *buf, int n)
{
	if ((n <= 0) || ((a & 0xFFU) + (uint32_t)n > 256U)) { outside += 1000; return false; }
	if ((a < SMSF_REGION_ADDR) || (a + n > SMSF_REGION_ADDR + SMSF_SLOTS * 4096U)) outside++;
	if (cutNow()) { if (cutMode) for (int i = 0; i < n / 2; i++) fl[a + i] &= buf[i]; longjmp(cutJmp, 1); }
	for (int i = 0; i < n; i++) fl[a + i] &= buf[i];
	if (stuck && ((a % 4096U) >= 32U))   /* один біт, що мав стати 0, лишився 1 */
		for (int i = 0; i < n; i++) if ((buf[i] & 0x01) == 0) { fl[a + i] |= 0x01; stuck = 0; break; }
	return true;
}

static int fails = 0, checks = 0;
#define CHECK(c, ...) do { checks++; if (!(c)) { printf("FAIL "); printf(__VA_ARGS__); printf("\n"); fails++; } } while (0)

/* образ: «MSGV», 3, 0, used, nextSeq + used байтів; k -- варіант вмісту */
static uint32_t mkimg(uint8_t *img, uint32_t len, int k)
{
	memset(img, 0, 1352);
	memcpy(img, "MSGV", 4); img[4] = 3; img[5] = 0;
	uint16_t used = (uint16_t)(len - 10); memcpy(img + 6, &used, 2); img[8] = (uint8_t)k; img[9] = 0;
	for (uint32_t i = 10; i < len; i++) img[i] = (uint8_t)(i * 7 + k * 13 + 1);
	return len;
}
static void wipe(void) { memset(fl, 0xFF, sizeof fl); memset(erases, 0, sizeof erases); opCount = 0; cutAt = -1; outside = 0; eraseNewest = 0; }

int main(void)
{
	static uint8_t a[1352], b[1352], r[1352];
	/* А: туди-назад */
	{
		static const uint32_t lens[] = { 10, 11, 300, 1352 };
		for (unsigned i = 0; i < 4; i++)
		{
			wipe(); mkimg(a, lens[i], (int)i + 1);
			memset(r, 0x5A, sizeof r);
			CHECK(smsfSaveCore(a, lens[i]), "А: запис %u", lens[i]);
			int n = smsfLoadCore(r, 1352);
			CHECK((n == (int)lens[i]) && (memcmp(a, r, 1352) == 0), "А: читання %u -> %d, байт-у-байт, хвіст 0", lens[i], n);
		}
		wipe(); mkimg(a, 300, 1);
		CHECK(!smsfSaveCore(a, 9) && !smsfSaveCore(a, 1353) && (opCount == 0), "А: довжина 9 / 1353 -- відмова без жодної операції");
		CHECK(smsfLoadCore(r, 1352) == -1, "А: порожнє кільце -> -1");
		CHECK(outside == 0, "А: поза ділянкою -- нуль");
	}
	/* Б: обрив у кожній операції */
	{
		static const int prior[] = { 0, 1, 7, 8, 9 };
		int casesB = 0, badB = 0, half = 0;
		for (unsigned p = 0; p < 5; p++)
			for (int mode = 0; mode < 2; mode++)
				for (long cut = 0; cut < 40; cut++)   /* 1 стирання + 6 програмувань образу + заголовок = 8 операцій */
				{
					wipe();
					for (int k = 0; k < prior[p]; k++) { mkimg(a, 50 + 10 * k, 100 + k); smsfSaveCore(a, 50 + 10 * k); }
					volatile uint32_t la = prior[p] ? mkimg(a, 50 + 10 * (prior[p] - 1), 100 + prior[p] - 1) : 0;
					uint32_t lb = mkimg(b, 1352, 7);
					opCount = 0; cutAt = cut; cutMode = mode;
					volatile int done = 0;
					if (setjmp(cutJmp) == 0) { smsfSaveCore(b, lb); done = 1; }
					cutAt = -1;
					if (done && cut > 0) break;   /* обрив уже після всіх операцій */
					casesB++;
					int n = smsfLoadCore(r, 1352);
					int okOld = (prior[p] == 0) ? (n == -1) : ((n == (int)la) && (memcmp(r, a, 1352) == 0));
					int okNew = (n == (int)lb) && (memcmp(r, b, 1352) == 0);
					if (!(okOld || okNew)) { badB++; printf("FAIL Б: заповнення %d, режим %d, обрив %ld -> %d\n", prior[p], mode, cut, n); }
					half += halfValid();
				}
		CHECK(badB == 0, "Б: після обриву -- рівно старий або новий образ (%d випадків, поганих %d)", casesB, badB);
		CHECK(half == 0, "Б: слотів «цілий заголовок + нецілий образ» -- %d", half);
		CHECK(casesB == 80, "Б: випадків обриву перевірено %d (5 заповнень x 2 режими x 8 операцій)", casesB);
		CHECK(outside == 0, "Б: поза ділянкою -- нуль");
	}
	/* В: пошкодження */
	{
		wipe(); mkimg(a, 400, 1); smsfSaveCore(a, 400); mkimg(b, 500, 2); smsfSaveCore(b, 500);
		int nw = newestIndep();
		CHECK(nw >= 0, "В: є найновіший цілий слот");
		if (nw >= 0) fl[SMSF_REGION_ADDR + nw * 4096U + 32 + 200] ^= 0x10;
		CHECK((smsfLoadCore(r, 1352) == 400) && (memcmp(r, a, 1352) == 0), "В: зіпсований байт образу найновішого -> попередній");
		wipe(); mkimg(a, 400, 1); smsfSaveCore(a, 400); mkimg(b, 500, 2); smsfSaveCore(b, 500);
		nw = newestIndep(); if (nw >= 0) fl[SMSF_REGION_ADDR + nw * 4096U + 6] ^= 0x01;   /* довжина в заголовку */
		CHECK((smsfLoadCore(r, 1352) == 400) && (memcmp(r, a, 1352) == 0), "В: зіпсований заголовок найновішого -> попередній");
		/* старший слот із підробленим seq (CRC образу цілий, CRC заголовка -- ні) */
		wipe(); mkimg(a, 400, 1); smsfSaveCore(a, 400); mkimg(b, 500, 2); smsfSaveCore(b, 500);
		{
			int old = -1; uint32_t s;
			for (int i = 0; i < (int)SMSF_SLOTS; i++) if (slotValid(i, &s) == 1 && i != newestIndep()) old = i;
			uint32_t big = 0x7FFFFFF0U; CHECK(old >= 0, "В: є старший цілий слот"); if (old >= 0) memcpy(&fl[SMSF_REGION_ADDR + old * 4096U + 8], &big, 4);   /* 1->0 недосяжно на NOR, але це модель пошкодження */
			CHECK((smsfLoadCore(r, 1352) == 500) && (memcmp(r, b, 1352) == 0), "В: старший слот із підробленим seq без CRC заголовка -- відкинуто");
		}
		wipe(); mkimg(a, 400, 1); smsfSaveCore(a, 400); mkimg(b, 500, 2); smsfSaveCore(b, 500);
		for (int i = 0; i < (int)SMSF_SLOTS; i++) fl[SMSF_REGION_ADDR + i * 4096U + 40] ^= 0xFF;
		memset(r, 0x5A, sizeof r);
		int n = smsfLoadCore(r, 1352); int z = 1; for (int i = 0; i < 1352; i++) if (r[i]) z = 0;
		CHECK((n == -1) && z, "В: усі слоти зіпсовані -> -1, образ обнулено");
		srand(7); for (uint32_t i = 0; i < SMSF_SLOTS * 4096U; i++) fl[SMSF_REGION_ADDR + i] = (uint8_t)rand();
		CHECK(smsfLoadCore(r, 1352) == -1, "В: сміття в ділянці -> -1 без падінь");
		CHECK(smsfSaveCore(a, 400) && (smsfLoadCore(r, 1352) == 400) && (memcmp(r, a, 1352) == 0), "В: після сміття -- запис і читання працюють");
		/* переповнення seq */
		wipe(); mkimg(a, 100, 1); smsfSaveCore(a, 100);
		{
			int s0 = newestIndep(); if (s0 < 0) s0 = 0; uint8_t *h = &fl[SMSF_REGION_ADDR + s0 * 4096U];
			uint32_t sq = 0xFFFFFFFEU; memset(h, 0xFF, 32);
			uint32_t mg = SMSF_MAGIC; uint16_t ln = 100; uint32_t ci = crc32(h + 32, 100);
			memcpy(h, &mg, 4); h[4] = SMSF_VERSION; h[5] = 0; memcpy(h + 6, &ln, 2); memcpy(h + 8, &sq, 4); memcpy(h + 12, &ci, 4);
			uint32_t ch = crc32(h, 16); memcpy(h + 16, &ch, 4);
		}
		mkimg(b, 200, 2); smsfSaveCore(b, 200);   /* seq 0xFFFFFFFF */
		static uint8_t c[1352]; mkimg(c, 300, 3); smsfSaveCore(c, 300);   /* seq 0 */
		uint32_t s = 1; int nwc = newestIndep(); if (nwc >= 0) slotValid(nwc, &s);
		CHECK((s == 0U) && (smsfLoadCore(r, 1352) == 300) && (memcmp(r, c, 1352) == 0), "В: переповнення seq 0xFFFFFFFF -> 0, найновіший -- seq 0 (%u)", s);
	}
	/* Г: знос */
	{
		wipe();
		for (int k = 0; k < 16; k++) { mkimg(a, 60 + k, k); CHECK(smsfSaveCore(a, 60 + k), "Г: запис %d", k); }
		int eq = 1; for (int i = 0; i < (int)SMSF_SLOTS; i++) if (erases[i] != 2) eq = 0;
		CHECK(eq, "Г: 16 записів -> кожен слот стерто рівно двічі (%ld %ld %ld %ld %ld %ld %ld %ld)",
				erases[0], erases[1], erases[2], erases[3], erases[4], erases[5], erases[6], erases[7]);
		CHECK(eraseNewest == 0, "Г: найновіший цілий слот не стирався (%d)", eraseNewest);
		CHECK((smsfLoadCore(r, 1352) == 75) && (memcmp(r, a, 1352) == 0), "Г: після кола -- останній образ");
	}
	/* Д: «той самий» */
	{
		wipe(); mkimg(a, 300, 1);
		CHECK(!smsfSameCore(a, 300), "Д: порожнє кільце -- не той самий");
		smsfSaveCore(a, 300);
		CHECK(smsfSameCore(a, 300), "Д: щойно записаний -- той самий");
		a[100] ^= 1; CHECK(!smsfSameCore(a, 300), "Д: змінений байт -- не той самий"); a[100] ^= 1;
		CHECK(!smsfSameCore(a, 299), "Д: інша довжина -- не той самий");
	}
	/* Е: звірка */
	{
		wipe(); mkimg(a, 300, 1); smsfSaveCore(a, 300);
		mkimg(b, 600, 2); stuck = 1;
		CHECK(!smsfSaveCore(b, 600), "Е: «залиплий» біт -> запис = false (звірка читанням)");
		stuck = 0;
	}
	printf("CHECKS %d FAILS %d\n", checks, fails);
	return fails ? 1 : 0;
}
'''

INC = ["-I", os.path.join(APP, "include")]


def run_core(src_text, tmp, tag):
    d = os.path.join(tmp, tag)
    os.makedirs(os.path.join(d, "functions"), exist_ok=True)
    src = os.path.join(d, "sms_flash_store.c")
    open(src, "w", encoding="utf-8").write(src_text)
    h = os.path.join(d, "h.c")
    open(h, "w", encoding="utf-8").write(HARNESS)
    exe = os.path.join(d, "t")
    r = subprocess.run(["gcc", "-O1", "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-DSMS_STORE_HOST_TEST"] + INC +
                       ["-o", exe, h, src], capture_output=True, text=True)
    if r.returncode != 0:
        return None, r.stderr
    p = subprocess.run([exe], capture_output=True, text=True, errors="replace", timeout=300)
    return p.returncode, p.stdout


def itest_cmd(sms_src, exe):
    """Те саме, що tests/run_tests.sh для test_dmr_sms_flash (джерела й прапорці беруться з run_tests.sh)."""
    rt = rd(os.path.join(FW, "tests", "run_tests.sh"))
    m = re.search(r'\[test_dmr_sms_flash\]="([^"]*)"', rt)
    srcs = m.group(1) if m else ""
    flags = re.findall(r'\[test_dmr_sms_flash\]="([^"]*)"', rt)
    flags = flags[1] if len(flags) > 1 else ""
    fw_incs = re.search(r'FW_INCS="(.*?)"', rt, re.S).group(1).replace("\\\n", " ")
    env = {"APP": APP, "FW": FW, "FW_INCS": fw_incs, "TESTS_DIR": os.path.join(FW, "tests")}
    def sub(s):
        for _ in range(3):
            for k, v in sorted(env.items(), key=lambda kv: -len(kv[0])):   # $FW_INCS раніше за $FW
                s = s.replace("$" + k, v)
        return s
    srcs = sub(srcs).split()
    flags = sub(flags).split()
    srcs = [sms_src if s.endswith("functions/dmr_sms.c") else s for s in srcs]
    return (["gcc", "-O2", "-Wall", "-Wextra", "-std=gnu11", "-DENABLE_AES", "-DENABLE_DMR_DATA", "-DENABLE_CALL_REPLAY",
             "-I", os.path.join(APP, "include"), "-I", os.path.join(APP, "include", "crypto")] + flags + ["-o", exe, ITEST] + srcs), bool(m)


def run_itest(sms_text, tmp, tag):
    d = os.path.join(tmp, tag)
    os.makedirs(d, exist_ok=True)
    src = os.path.join(d, "dmr_sms.c")
    open(src, "w", encoding="utf-8").write(sms_text)
    exe = os.path.join(d, "t")
    cmd, found = itest_cmd(src, exe)
    if not found:
        return None, "test_dmr_sms_flash нема в run_tests.sh"
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return None, r.stderr[-2000:]
    p = subprocess.run([exe], capture_output=True, text=True, errors="replace", timeout=600)
    return p.returncode, p.stdout


def main():
    if shutil.which("gcc") is None:
        print("ПРОВАЛ: gcc не знайдено -- тест не можна виконати (пропуск не рахується пройденим)")
        return 1
    tmp = tempfile.mkdtemp(prefix="r106_")
    try:
        core = rd(CORE)
        sms = rd(SMS)
        # --- ядро
        rc, out = run_core(core, tmp, "core")
        check(rc == 0, "ядро: справжній sms_flash_store.c з моделлю NOR -- 0 провалів:\n%s" % out)
        m = re.search(r"CHECKS (\d+) FAILS (\d+)", out or "")
        check(bool(m) and int(m.group(1)) >= 30, "ядро: перевірок виконано %s" % (m.group(1) if m else "?"))
        if m:
            N[0] += int(m.group(1))
        # --- інтеграція (справжній dmr_sms.c)
        rc, out = run_itest(sms, tmp, "itest")
        check(rc == 0, "інтеграція: tests/test_dmr_sms_flash.c на справжньому dmr_sms.c -- 0 провалів:\n%s" % (out or "")[-3000:])
        m = re.search(r"CHECKS (\d+) FAILS (\d+)", out or "")
        check(bool(m) and int(m.group(1)) >= 25, "інтеграція: перевірок виконано %s" % (m.group(1) if m else "?"))
        if m:
            N[0] += int(m.group(1))

        # --- Ж: проводка
        mk = rd(os.path.join(FW, "Makefile"))
        check("ifeq ($(ENABLE_SMS_STORE_FLASH),1)\nDEFS += -DENABLE_SMS_STORE_FLASH\nendif" in mk, "Ж1: прапорець у Makefile")
        yml = rd(os.path.join(os.path.dirname(FW), ".github", "workflows", "build.yml"))
        runs = [l for l in yml.splitlines() if "run: make" in l and "ENABLE_SMS_STORE_FLASH=1" in l]
        check(len(runs) == 1 and "ENABLE_TONE_REPLY=1" in runs[0], "Ж2: ENABLE_SMS_STORE_FLASH=1 лише в build-ukrainian: %d" % len(runs))
        sc = rd(os.path.join(HERE, "syntax_check.sh"))
        check(" SMSF SMSFEN SMSFBARE)" in sc and 'DEFS_SMSF=("${DEFS_TONE[@]}" -DENABLE_SMS_STORE_FLASH)' in sc, "Ж3: конфігурації SMSF/SMSFEN/SMSFBARE у syntax_check")
        h = rd(os.path.join(APP, "include", "functions", "sms_flash_store.h"))
        check("#if defined(ENABLE_SMS_STORE_FLASH) && defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)\n#define SMS_STORE_FLASH 1" in h, "Ж4: SMS_STORE_FLASH лише з AES і DMR_DATA")
        check("#define SMSF_REGION_ADDR    0x48000UL" in h and "#define SMSF_SLOTS          8U" in h and "#define SMSF_DEFER_S        60U" in h,
              "Ж5: ділянка 0x48000, 8 слотів, відкладення 60 с (рішення 1)")
        check("AMS_REGION_ADDR" in h and "<= 0x50000UL" in h and ">= 0x30000UL" in h, "Ж6: _Static_assert -- проміжок 0x30000..0x4FFFF і без перетину з APRS")
        am = rd(os.path.join(APP, "source", "applicationMain.c"))
        check(re.search(r"dmrSmsRxTick\(\);[^\n]*\n#if defined\(SMS_STORE_FLASH\)\n\t\tdmrSmsStoreTick\(\);", am) is not None, "Ж7: тік одразу після dmrSmsRxTick")
        bp = rd(os.path.join(APP, "source", "interfaces", "batteryAndPowerManagement.c"))
        check(len(re.findall(r"aprsMsgStoreFlush\(\);[^\n]*\n#endif\n#if defined\(SMS_STORE_FLASH\)\n\tdmrSmsStoreFlush\(\);", bp)) == 2,
              "Ж8: дозапис в ОБОХ шляхах вимкнення (після APRS)")
        sp = rd(os.path.join(APP, "source", "hardware", "SPI_Flash.c"))
        check("#if defined(APRS_MSG1_UI) || defined(SMS_STORE_FLASH)\n/* R101-APRSMSG" in sp, "Ж9: SPI_Flash_programBytes і під SMS_STORE_FLASH")
        check("sectorbuffer" not in core and "SPI_Flash_write(" not in core and "SPI_Flash_writePage" not in core, "Ж10: ядро без SPI_Flash_sectorbuffer/SPI_Flash_write/writePage")
        ss = sms[sms.index("static void store_save(void)"):]
        ss = ss[:ss.index("\n}\n")]
        check("#if defined(SMS_STORE_FLASH)\n\tstore_mark(0);" in ss and "#else\n\tdmrAesEnsureCustomDataRegion();" in ss, "Ж11: store_save під прапорцем лише позначає (відкладено)")
        sa = sms[sms.index("static void store_add("):]
        sa = sa[:sa.index("\n}\n")]
        check(sa.rstrip().endswith("#if defined(SMS_STORE_FLASH)\n\tstore_mark(1);   /* R106: нове SMS -- у кільце при першій нагоді (після вікна квитанції, у тиші) */\n#else\n\tstore_save();\n#endif"),
              "Ж12: store_add під прапорцем -- «термінове»")
        flagged = re.findall(r"#if defined\(SMS_STORE_FLASH\)(.*?)#endif", sms, re.S)
        statics = [l for blk in flagged for l in blk.splitlines() if re.match(r"^static\s+(volatile\s+)?(uint|int|bool|char|dmr)\w*\s+\w+(\[.*\])?\s*(DMR_AES_CCM)?\s*(=.*)?;", l)]
        check(not statics, "Ж13: у dmr_sms.c під SMS_STORE_FLASH -- жодної нової статичної змінної (рішення 4, В1): %s" % statics)
        rr = sms[sms.index("void dmrSmsReloadStore(void)"):]
        rr = rr[:rr.index("#else")]
        check("if (s_loaded == 0U)" in rr and "smsfLegacyBlank();" in rr and "smsfLoadRing();" in rr, "Ж14: сховище з флешу -- лише раз після старту (меню не перечитує)")
        cr = rd(os.path.join(HERE, "custom_region.py"))
        check('7: ("MESSAGES", "SMS: повідомлення"' in cr and "R106" in cr.split("7: (\"MESSAGES\"")[1].split("\n")[0], "Ж15: CPS -- опис блока 7 оновлено (R106: порожній, SMS у власних секторах)")

        # --- З: мутанти ядра
        QUIET[0] = True
        img_step = "\tif (programSpan(slotAddr((unsigned)target) + SMSF_HDR_LEN, img, len) == false)\n\t{\n\t\treturn false;\n\t}\n"
        hdr_step = "\tif (SPI_Flash_programBytes(slotAddr((unsigned)target), (const uint8_t *)&h, (int)SMSF_HDR_PROG_LEN) == false)\n\t{\n\t\treturn false;\n\t}\n"
        check(img_step in core and hdr_step in core, "З: кроки запису знайдено в sms_flash_store.c (для мутантів)")
        swapped = core.replace(img_step, "@@IMG@@").replace(hdr_step, img_step).replace("@@IMG@@", hdr_step)
        mutants = [
            ("заголовок перед образом", swapped),
            ("запис у найновіший слот", core.replace("\tif (target < 0)\n\t{\n\t\treturn false;\n\t}\n\n\tmemset(&h, 0xFF",
                                                       "\tif (nw >= 0) { target = nw; }\n\tif (target < 0)\n\t{\n\t\treturn false;\n\t}\n\n\tmemset(&h, 0xFF")),
            ("без CRC образу", core.replace("return (crc == h->crcImg);", "(void)crc; return true;")
                                  .replace("(smsfCrc(0U, img, h.len) == h.crcImg)", "true")),
            ("без CRC заголовка", core.replace("(h->crcHdr == smsfCrc(0U, (const uint8_t *)h, SMSF_HDR_CRC_LEN))", "true")),
            ("без звірки", core.replace("\treturn verifySpan(slotAddr((unsigned)target), (const uint8_t *)&h, SMSF_HDR_PROG_LEN) &&\n\t\t\tverifySpan(slotAddr((unsigned)target) + SMSF_HDR_LEN, img, len);",
                                       "\t(void)verifySpan;\n\treturn true;")),
        ]
        for name, txt in mutants:
            if txt == core:
                check(False, "З: мутант «%s» не застосувався" % name)
                continue
            rc, out = run_core(txt, tmp, "m_" + re.sub(r"\W+", "_", name))
            check(rc not in (0, None), "З: мутант ядра «%s» ловиться (rc=%s)" % (name, rc))

        # --- З: мутанти dmr_sms.c
        smut = [
            ("запис без відкладення", sms.replace("(age > SMSF_DEFER_S)) && smsfWriteAllowed()", "(age > 0U)) && smsfWriteAllowed()")),
            ("без тиші в каналі", sms.replace("((uint32_t)(ticksGetMillis() - s_lastRxBurstMs) >= SMSF_QUIET_MS) &&", "")),
            ("меню перечитує сховище", sms.replace("\tif (s_loaded == 0U)\n\t{\n\t\ts_loaded = SMSF_ST_LOADED;", "\tif (1)\n\t{\n\t\ts_loaded = SMSF_ST_LOADED;")),
            ("блок 7 не очищується", sms.replace("\t\t(void)codeplugSetOpenGD77CustomData(CODEPLUG_CUSTOM_DATA_TYPE_MESSAGES, (uint8_t *)&s_store, (int)sizeof s_store);", "")),
            ("без дозапису відкладених при вимкненні", sms.replace("\tif (s_pendInbox)\n\t{\n\t\tstore_add(s_pendInboxFlags, s_pendInboxPeer, s_pendInboxText, s_pendInboxLen);\n\t\ts_pendInbox = 0;\n\t}\n\tif (SMSF_ST_AGE(s_loaded) != 0U)",
                                                              "\tif (SMSF_ST_AGE(s_loaded) != 0U)")),
        ]
        for name, txt in smut:
            if txt == sms:
                check(False, "З: мутант «%s» не застосувався" % name)
                continue
            rc, out = run_itest(txt, tmp, "s_" + re.sub(r"\W+", "_", name))
            check(rc not in (0, None), "З: мутант dmr_sms.c «%s» ловиться (rc=%s)" % (name, rc))
        QUIET[0] = False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_r106smsstore: перевірок %d, провалів %d" % (N[0], len(FAILS)))
    for f in FAILS:
        print("ПРОВАЛ: " + f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
