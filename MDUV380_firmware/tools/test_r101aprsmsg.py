# -*- coding: utf-8 -*-
"""test_r101aprsmsg.py -- R101-APRSMSG: список «Повідом. APRS» зберігається у власних вирівняних секторах SPI-флешу.

Хост: СПРАВЖНІ aprs_msg_store.c + aprs_msg.c (-DAPRS_MSG_STORE_HOST_TEST) з МОДЕЛЛЮ NOR-флешу (стирання сектора -> 0xFF, програмування лише 1 -> 0,
обрив живлення до операції або ПОСЕРЕДИНІ неї -- половина байтів/половина сектора).
  А  туди-назад: вхідні/вихідні, стани, непрочитані, номер, текст; «чекає»/«надіслано» -> «!»; лічильник непрочитаних; lastNum і numSeeded
  Б  обрив після КОЖНОЇ операції стирання/програмування (і посеред неї), за різного заповнення слотів (0, 3, 8, 9 записів раніше): завантажується
     РІВНО попередній або новий стан, ніколи частковий; інші адреси флешу не змінюються ніколи
  В  CRC-пошкодження найновішого слота -> попередній стан; усіх -> порожній список (-1), без падінь; переповнення seq (0xFFFFFFFF -> 0)
  Г  знос: 16 записів -> кожен з 8 слотів рівно двічі, по колу; найновіший слот ніколи не стирається
  Д  час: годинник є -> після «перезапуску» вік правильний (ms «до старту» за модулем 2^32); годинника нема при завантаженні -> noTime=2,
     коли з'явився -> вік; годинника нема при записі -> noTime=1; вік понад 45 діб -> невідомий
  Е  політика: без змін -- жодного запису; зміна -> один запис через 60 с; безперервні зміни -> не частіше ніж раз на 60 с; заборона запису
     (передача/CPS) відкладає; дозапис при вимкненні; «Видалити все» і «усі прочитані» переживають перезапуск; дедуплікація після перезапуску
  Ж  проводка: завантаження після menuSystemInit, тік після aprsMsgBgTick, дозапис у обох шляхах вимкнення, усе під APRS_MSG1_UI; ділянка
     0x40000..0x47FFF у вільному проміжку; програмування без SPI_Flash_sectorbuffer і без 256-Б буфера
  З  мутанти: заголовок перед даними, без CRC, стирається найновіший слот, час не абсолютний, запис на кожному тіку -- ловляться
"""
import os, re, subprocess, sys, tempfile, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)
APP = os.path.join(FW, "application")
SRC = os.path.join(APP, "source", "functions", "aprs_msg_store.c")
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
#include <setjmp.h>
#include "functions/aprs_msg_store.h"

uint16_t aprsModeCp1251ToUcs2(uint8_t c) { return c; }   /* як у test_r98msg1: перетворення в UTF-8 тут не перевіряється */

#define FL_SIZE 0x60000UL
static uint8_t fl[FL_SIZE];
static long opCount = 0, cutAt = -1; static int cutMode = 0; static jmp_buf cutJmp;
static long erases[AMS_SLOTS];
static uint32_t outsideWrites = 0;

static int cutNow(void) { long k = opCount++; return (cutAt >= 0) && (k == cutAt); }
bool SPI_Flash_read(uint32_t a, uint8_t *buf, int n) { for (int i = 0; i < n; i++) buf[i] = (a + i < FL_SIZE) ? fl[a + i] : 0xFF; return true; }
bool SPI_Flash_eraseSector(uint32_t a)
{
	if (a % 4096U) return false;
	if ((a < AMS_REGION_ADDR) || (a >= AMS_REGION_ADDR + AMS_SLOTS * 4096U)) outsideWrites++;
	if (cutNow()) { if (cutMode) memset(&fl[a], 0xFF, 2048); longjmp(cutJmp, 1); }
	memset(&fl[a], 0xFF, 4096); erases[(a - AMS_REGION_ADDR) / 4096U]++; return true;
}
bool SPI_Flash_programBytes(uint32_t a, const uint8_t *buf, int n)
{
	if ((n <= 0) || ((a & 0xFFU) + (uint32_t)n > 256U)) { outsideWrites += 1000; return false; }
	if ((a < AMS_REGION_ADDR) || (a + n > AMS_REGION_ADDR + AMS_SLOTS * 4096U)) outsideWrites++;
	if (cutNow()) { if (cutMode) for (int i = 0; i < n / 2; i++) fl[a + i] &= buf[i]; longjmp(cutJmp, 1); }
	for (int i = 0; i < n; i++) fl[a + i] &= buf[i];
	return true;
}

static uint32_t crc32(const uint8_t *p, int n) { uint32_t c = ~0U; while (n--) { c ^= *p++; for (int k = 0; k < 8; k++) c = (c >> 1) ^ (0xEDB88320U & (0U - (c & 1U))); } return ~c; }
/* незалежна від модуля перевірка: слотів із цілим заголовком, але НЕцілими даними («напівзаписаний слот виглядає валідним») */
static int halfValid(void)
{
	int n = 0;
	for (int i = 0; i < AMS_SLOTS; i++)
	{
		const uint8_t *h = &fl[AMS_REGION_ADDR + i * 4096U];
		uint32_t magic, crcHdr, crcData; uint16_t len;
		memcpy(&magic, h, 4); memcpy(&crcHdr, h + 24, 4); memcpy(&crcData, h + 16, 4); memcpy(&len, h + 12, 2);
		if ((magic != AMS_MAGIC) || (crc32(h, 24) != crcHdr) || (len > AMS_PAYLOAD_MAX)) continue;
		if (crc32(h + AMS_HDR_LEN, len) != crcData) n++;
	}
	return n;
}

#define CLK 1790000000UL
static aprsMsgBox_t B;
static void fresh(aprsMsgBox_t *b) { aprsMsgInit(b, 7); }

/* стан A: 5 записів; стан B: A + ще 2 і змінений непрочитаний */
static void stateA(aprsMsgBox_t *b, uint32_t now)
{
	fresh(b);
	aprsMsgOnIncoming(b, "UR5ABC", "Привіт, як справи?", "12", now - 3600000U);
	aprsMsgSend(b, "US5EX-7", "Тест ACK", now - 1800000U, "UW5ELK");
	aprsMsgOnIncoming(b, "R1ABC-9", "Без номера", "", now - 600000U);
	aprsMsgOnIncoming(b, "SP5XYZ", "Довгий текст повідомлення, щоб перевірити повну довжину запису у сховищі, 67 бт", "99999", now - 120000U);
	aprsMsgSend(b, "UT1AA", "Ще одне", now - 60000U, "UW5ELK");
	b->list[3].status = AMSG_ST_ACK;   /* [0] -- найновіше: «Ще одне» (чекає), [3] -- «Тест ACK» (підтверджено) */
	b->numSeeded = 1U; b->lastNum = 42U;
}
static void stateB(aprsMsgBox_t *b, uint32_t now)
{
	stateA(b, now);
	aprsMsgOnIncoming(b, "UR0X", "B-1", "7", now - 5000U);
	aprsMsgOnIncoming(b, "UR0Y", "B-2", "", now - 4000U);
	aprsMsgMarkRead(b, 4);
}

static void dump(const char *tag, const aprsMsgBox_t *b, uint32_t now)
{
	printf("%s n=%u unread=%u lastNum=%u seeded=%u", tag, aprsMsgListCount(b), aprsMsgUnreadCount(b), b->lastNum, b->numSeeded);
	for (int i = 0; i < APRS_MSG_LIST_MAX; i++)
	{
		const aprsMsgEntry_t *e = &b->list[i];
		if (!e->used) continue;
		printf(" |%d:%u:%u:%u:%u:%s:%s:%s:nt%u:age%ld", i, e->dir, e->status, e->unread, e->attempts, e->call, e->id, e->text, e->noTime,
				e->noTime ? -1L : (long)((uint32_t)(now - e->ms) / 1000U));
	}
	printf("\n");
}
/* підпис стану без часу -- для порівняння A/B після обриву */
static void sig(const aprsMsgBox_t *b, char *out)
{
	out[0] = 0;
	for (int i = 0; i < APRS_MSG_LIST_MAX; i++)
	{
		const aprsMsgEntry_t *e = &b->list[i]; char t[160];
		if (!e->used) continue;
		snprintf(t, sizeof t, "%u%u%u%s/%s/%s;", e->dir, e->status == AMSG_ST_SENT || e->status == AMSG_ST_WAIT ? AMSG_ST_NOACK : e->status, e->unread, e->call, e->id, e->text);
		strcat(out, t);
	}
}

int main(void)
{
	setvbuf(stdout, NULL, _IONBF, 0);
	uint32_t now = 10000000U;
	static char sa[2048], sb[2048], sl[2048];
	memset(fl, 0x5A, sizeof fl);                         /* поза ділянкою -- «чужі» дані */
	memset(&fl[AMS_REGION_ADDR], 0xFF, AMS_SLOTS * 4096U);   /* ділянка стерта */
	uint8_t guardSnap[64]; memcpy(guardSnap, &fl[AMS_REGION_ADDR - 32], 32); memcpy(guardSnap + 32, &fl[AMS_REGION_ADDR + AMS_SLOTS * 4096U], 32);

	/* ---- А ---- */
	fresh(&B); printf("EMPTYLOAD %d\n", aprsMsgStoreLoadCore(&B, 5000U, CLK));
	stateA(&B, now); dump("A0", &B, now);
	printf("SAVE %d\n", (int)aprsMsgStoreSaveCore(&B, now, CLK));
	fresh(&B); { uint32_t now2 = 20000U; int s = aprsMsgStoreLoadCore(&B, now2, CLK + 600U); printf("LOADSLOT %d\n", s); dump("A1", &B, now2); }
	/* дедуплікація після перезапуску */
	printf("DEDUP %d\n", (int)aprsMsgOnIncoming(&B, "UR5ABC", "Привіт, як справи?", "12", 30000U));

	/* ---- Б: обрив живлення ---- */
	{
		int pre[] = { 0, 3, 8, 9 };
		static uint8_t snap[AMS_SLOTS * 4096];
		long bad = 0, okA = 0, okB = 0, total = 0, outside = 0, half = 0;
		for (int pi = 0; pi < 4; pi++)
		{
			memset(&fl[AMS_REGION_ADDR], 0xFF, AMS_SLOTS * 4096U);
			for (int k = 0; k < pre[pi]; k++) { stateA(&B, now); B.list[0].attempts = (uint8_t)(k + 10); aprsMsgStoreSaveCore(&B, now, CLK); }
			stateA(&B, now); aprsMsgStoreSaveCore(&B, now, CLK); sig(&B, sa);
			memcpy(snap, &fl[AMS_REGION_ADDR], sizeof snap);
			stateB(&B, now); sig(&B, sb);
			opCount = 0; cutAt = -1; aprsMsgStoreSaveCore(&B, now, CLK); long ops = opCount;
			for (cutMode = 0; cutMode < 2; cutMode++)
				for (long c = 0; c <= ops; c++)
				{
					memcpy(&fl[AMS_REGION_ADDR], snap, sizeof snap);
					stateB(&B, now);
					opCount = 0; cutAt = c;
					if (setjmp(cutJmp) == 0) { aprsMsgStoreSaveCore(&B, now, CLK); }
					cutAt = -1;
					half += halfValid();
					fresh(&B); aprsMsgStoreLoadCore(&B, now, CLK); sig(&B, sl);
					total++;
					if (strcmp(sl, sa) == 0) okA++; else if (strcmp(sl, sb) == 0) okB++; else { bad++; if (bad < 3) printf("BADCUT pre=%d mode=%d cut=%ld got=%s\n", pre[pi], cutMode, c, sl); }
				}
		}
		outside = (memcmp(guardSnap, &fl[AMS_REGION_ADDR - 32], 32) != 0) || (memcmp(guardSnap + 32, &fl[AMS_REGION_ADDR + AMS_SLOTS * 4096U], 32) != 0);
		printf("CUTS total=%ld A=%ld B=%ld bad=%ld outside=%ld ow=%u half=%ld\n", total, okA, okB, bad, outside, outsideWrites, half);
	}

	/* ---- В: пошкодження ---- */
	{
		memset(&fl[AMS_REGION_ADDR], 0xFF, AMS_SLOTS * 4096U);
		stateA(&B, now); aprsMsgStoreSaveCore(&B, now, CLK); sig(&B, sa);
		stateB(&B, now); aprsMsgStoreSaveCore(&B, now, CLK); sig(&B, sb);
		fresh(&B); int s = aprsMsgStoreLoadCore(&B, now, CLK); sig(&B, sl); printf("CORR0 %d %d\n", s, strcmp(sl, sb) == 0);
		fl[AMS_REGION_ADDR + (uint32_t)s * 4096U + AMS_HDR_LEN + 10] ^= 0x01;   /* байт даних найновішого */
		fresh(&B); int s2 = aprsMsgStoreLoadCore(&B, now, CLK); sig(&B, sl); printf("CORR1 %d %d\n", s2 != s, strcmp(sl, sa) == 0);
		for (int i = 0; i < AMS_SLOTS; i++) fl[AMS_REGION_ADDR + i * 4096U + 9] ^= 0x40;   /* заголовки всіх */
		fresh(&B); int s3 = aprsMsgStoreLoadCore(&B, now, CLK); printf("CORRALL %d %u\n", s3, aprsMsgListCount(&B));
		memset(&fl[AMS_REGION_ADDR], 0x00, AMS_SLOTS * 4096U);   /* сміття */
		fresh(&B); printf("JUNK %d %u\n", aprsMsgStoreLoadCore(&B, now, CLK), aprsMsgListCount(&B));
		/* переповнення seq: найновіший має seq 0xFFFFFFFF, наступний запис -- 0 */
		memset(&fl[AMS_REGION_ADDR], 0xFF, AMS_SLOTS * 4096U);
		stateA(&B, now); aprsMsgStoreSaveCore(&B, now, CLK);
		{ uint8_t *h = &fl[AMS_REGION_ADDR]; h[8] = h[9] = h[10] = h[11] = 0xFF; uint32_t c = crc32(h, 24); memcpy(h + 24, &c, 4); }
		/* (програмування 1->0 у моделі, тож тут пишемо прямо -- це підготовка, не операція модуля) */
		stateB(&B, now); aprsMsgStoreSaveCore(&B, now, CLK);
		uint32_t seq1; memcpy(&seq1, &fl[AMS_REGION_ADDR + 4096U + 8], 4);
		fresh(&B); int s4 = aprsMsgStoreLoadCore(&B, now, CLK); sig(&B, sl); printf("SEQWRAP seq=%u slot=%d isB=%d\n", seq1, s4, strcmp(sl, sb) == 0);
	}

	/* ---- Г: знос ---- */
	{
		memset(&fl[AMS_REGION_ADDR], 0xFF, AMS_SLOTS * 4096U); memset(erases, 0, sizeof erases);
		printf("WEAR");
		for (int k = 0; k < 16; k++)
		{
			stateA(&B, now); B.list[0].attempts = (uint8_t)k;
			aprsMsgStoreSaveCore(&B, now, CLK);
			fresh(&B); printf(" %d", aprsMsgStoreLoadCore(&B, now, CLK));
		}
		printf(" |");
		for (int i = 0; i < AMS_SLOTS; i++) printf(" %ld", erases[i]);
		printf("\n");
	}

	/* ---- Д: час ---- */
	{
		memset(&fl[AMS_REGION_ADDR], 0xFF, AMS_SLOTS * 4096U);
		fresh(&B); aprsMsgOnIncoming(&B, "UR5ABC", "t1", "1", now - 3600000U);   /* годину тому, годинник CLK */
		aprsMsgStoreSaveCore(&B, now, CLK);
		fresh(&B); aprsMsgStoreLoadCore(&B, 15000U, CLK + 600U);   /* «перезапуск» через 10 хв, тики з нуля */
		printf("TIME1 nt=%u age=%u\n", B.list[0].noTime, (uint32_t)(15000U - B.list[0].ms) / 1000U);
		fresh(&B); aprsMsgStoreLoadCore(&B, 15000U, 0U);           /* годинник не виставлено */
		printf("TIME2 nt=%u ms=%u\n", B.list[0].noTime, B.list[0].ms);
		B.storeSec = 99; aprsMsgStoreTickCore(&B, 17000U, CLK + 600U, false);   /* годинник з'явився */
		printf("TIME3 nt=%u age=%u\n", B.list[0].noTime, (uint32_t)(17000U - B.list[0].ms) / 1000U);
		fresh(&B); aprsMsgOnIncoming(&B, "UR5ABC", "t2", "2", now); aprsMsgStoreSaveCore(&B, now, 0U);   /* годинника нема при записі */
		fresh(&B); aprsMsgStoreLoadCore(&B, 15000U, CLK);
		printf("TIME4 nt=%u\n", B.list[0].noTime);
		fresh(&B); aprsMsgOnIncoming(&B, "UR5ABC", "t3", "3", now); aprsMsgStoreSaveCore(&B, now, CLK);
		fresh(&B); aprsMsgStoreLoadCore(&B, 15000U, CLK + 50U * 86400U);   /* 50 діб потому */
		printf("TIME5 nt=%u\n", B.list[0].noTime);
	}

	/* ---- Е: політика ---- */
	{
		memset(&fl[AMS_REGION_ADDR], 0xFF, AMS_SLOTS * 4096U);
		fresh(&B); aprsMsgStoreLoadCore(&B, 1000U, CLK);
		uint32_t t;
		opCount = 0;
		for (t = 1000; t < 300000; t += 50) { aprsMsgStoreTickCore(&B, t, CLK + t / 1000, true); }
		printf("POLICY idle_ops=%ld\n", opCount);
		/* зміна на 10 с -> один запис через ~60 с */
		long firstWrite = -1; int writes = 0;
		for (t = 300000; t < 600000; t += 50)
		{
			if (t == 310000) aprsMsgOnIncoming(&B, "UR0X", "p1", "", t);
			if (aprsMsgStoreTickCore(&B, t, CLK + t / 1000, true)) { writes++; if (firstWrite < 0) firstWrite = (long)(t - 310000) / 1000; }
		}
		printf("POLICY one writes=%d after=%ld\n", writes, firstWrite);
		/* безперервні зміни щосекунди 300 с */
		writes = 0;
		for (t = 600000; t < 900000; t += 50)
		{
			if ((t % 1000) == 0) B.list[0].attempts++;   /* зміст змінюється щосекунди */
			if (aprsMsgStoreTickCore(&B, t, CLK + t / 1000, true)) writes++;
		}
		printf("POLICY busy writes=%d\n", writes);
		/* заборона запису (передача/CPS) */
		writes = 0; aprsMsgOnIncoming(&B, "UR0Z", "p2", "", t);
		for (; t < 1100000; t += 50) { if (aprsMsgStoreTickCore(&B, t, CLK + t / 1000, false)) writes++; }
		int dirty = aprsMsgStoreDirtyCore(&B, t, CLK + t / 1000);
		int fl1 = aprsMsgStoreFlushCore(&B, t, CLK + t / 1000);
		int dirty2 = aprsMsgStoreDirtyCore(&B, t, CLK + t / 1000);
		int fl2 = aprsMsgStoreFlushCore(&B, t, CLK + t / 1000);
		printf("POLICY blocked writes=%d dirty=%d flush=%d dirty2=%d flush2=%d\n", writes, dirty, fl1, dirty2, fl2);
		/* «усі прочитані» і «Видалити все» */
		for (int i = 0; i < APRS_MSG_LIST_MAX; i++) if (B.list[i].used) aprsMsgMarkRead(&B, i);
		aprsMsgStoreFlushCore(&B, t, CLK);
		fresh(&B); aprsMsgStoreLoadCore(&B, 1000U, CLK); printf("MARKALL n=%u unread=%u\n", aprsMsgListCount(&B), aprsMsgUnreadCount(&B));
		aprsMsgDeleteAll(&B); aprsMsgStoreFlushCore(&B, 2000U, CLK);
		fresh(&B); printf("DELALL slot=%d n=%u\n", aprsMsgStoreLoadCore(&B, 1000U, CLK), aprsMsgListCount(&B));
	}
	return 0;
}
'''


def build(src_text):
    d = tempfile.mkdtemp(prefix="r101_")
    try:
        sp = os.path.join(d, "aprs_msg_store.c"); open(sp, "w", encoding="utf-8").write(src_text)
        hp = os.path.join(d, "h.c"); open(hp, "w", encoding="utf-8").write(HARNESS)
        exe = os.path.join(d, "h")
        cmd = ["gcc", "-std=gnu11", "-Wall", "-Wno-unused-function", "-Wno-unused-result", "-DAPRS_MSG_STORE_HOST_TEST", "-DENABLE_APRS_RX", "-DLANGUAGE_BUILD_UKRAINIAN", "-DENABLE_AES", "-DENABLE_DMR_DATA",
               "-I" + os.path.join(APP, "include"), "-I" + os.path.join(FW, "tools", "hoststub"), "-o", exe, hp, sp,
               os.path.join(APP, "source", "functions", "aprs_msg.c")]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            return None, r.stderr[-2500:]
        return subprocess.run([exe], capture_output=True, text=True, errors="replace", timeout=300).stdout, ""
    finally:
        shutil.rmtree(d, ignore_errors=True)


def lines(out):
    L = {}
    for l in out.splitlines():
        p = l.split(" ", 1)
        L.setdefault(p[0], []).append(p[1] if len(p) > 1 else "")
    return L


def core(out, tag=""):
    ok = [True]

    def want(c, m):
        ok[0] = ok[0] and bool(c)
        check(c, m + tag)
    L = lines(out)
    g = lambda k, i=0: (L.get(k) or [""] * (i + 1))[i]
    want(g("EMPTYLOAD") == "-1", "А0: порожня ділянка -- -1, порожній список: %r" % g("EMPTYLOAD"))
    want(g("SAVE") == "1", "А1: запис -- true (звірено читанням)")
    a0, a1 = g("A0"), g("A1")
    strip = lambda s: re.sub(r":nt\d+:age-?\d+", "", s)
    want(strip(a1) == re.sub(r"(\|\d+:1:)[12](:)", r"\g<1>4\2", strip(a0)), "А2: туди-назад: усі записи, стани («чекає/надіслано» -> «!»), непрочитані, номер, текст:\n   %s\n   %s" % (a0, a1))
    want("unread=3" in a1 and "lastNum=42 seeded=1" in a1, "А3: лічильник непрочитаних і номер {NN} після перезавантаження: %r" % a1[:60])
    want(g("LOADSLOT") == "0", "А4: завантажено слот 0")
    want(g("DEDUP") == "0", "А5: повтор уже збереженого кадра після перезапуску -- не новий запис")
    m = re.match(r"total=(\d+) A=(\d+) B=(\d+) bad=(\d+) outside=(\d+) ow=(\d+) half=(\d+)", g("CUTS"))
    want(m and int(m.group(4)) == 0 and int(m.group(2)) > 0 and int(m.group(3)) > 0 and m.group(5) == "0" and m.group(6) == "0" and m.group(7) == "0",
         "Б1: обрив після/посеред КОЖНОЇ операції (заповнення 0/3/8/9): лише цілий A або B, поза ділянкою нічого, слота «цілий заголовок + нецілі дані» не буває: %r %r" % (g("CUTS"), L.get("BADCUT")))
    want(g("CORR0") == "%s 1" % g("CORR0").split()[0] and g("CORR1") == "1 1", "В1: зіпсовані дані найновішого -> попередній стан: %r %r" % (g("CORR0"), g("CORR1")))
    want(g("CORRALL") == "-1 0" and g("JUNK") == "-1 0", "В2: зіпсовані всі / сміття -> порожній список без падінь: %r %r" % (g("CORRALL"), g("JUNK")))
    want(g("SEQWRAP") == "seq=0 slot=1 isB=1", "В3: переповнення seq 0xFFFFFFFF -> 0, новішим лишається 0: %r" % g("SEQWRAP"))
    w = g("WEAR")
    seq, er = w.split("|") if "|" in w else ("", "")
    want(seq.split() == [str(i % 8) for i in range(16)] and er.split() == ["2"] * 8, "Г1: 16 записів -- слоти по колу, кожен стертий рівно двічі: %r" % w)
    want(g("TIME1") == "nt=0 age=4200", "Д1: годинник є -- вік після перезапуску правильний (1 год + 10 хв): %r" % g("TIME1"))
    want(re.match(r"nt=2 ms=1789996400$", g("TIME2") or "") is not None, "Д2: годинника нема при завантаженні -- noTime=2, абсолютний час у ms: %r" % g("TIME2"))
    want(g("TIME3") == "nt=0 age=4200", "Д3: годинник з'явився -- абсолютний час переведено у вік: %r" % g("TIME3"))
    want(g("TIME4") == "nt=1", "Д4: годинника нема при записі -- час невідомий: %r" % g("TIME4"))
    want(g("TIME5") == "nt=2", "Д5: вік понад 45 діб -- час не показується: %r" % g("TIME5"))
    pol = L.get("POLICY") or []
    want(len(pol) == 4 and pol[0] == "idle_ops=%s" % pol[0].split("=")[1] and int(pol[0].split("=")[1]) == 0, "Е1: без змін -- жодного стирання/програмування: %r" % pol[:1])
    want(len(pol) > 1 and re.match(r"one writes=1 after=(59|60|61)$", pol[1]) is not None, "Е2: зміна -> один запис через ~60 с: %r" % pol[1:2])
    mb = re.match(r"busy writes=(\d+)", pol[2] if len(pol) > 2 else "")
    want(mb and 3 <= int(mb.group(1)) <= 6, "Е3: безперервні зміни 300 с -- не частіше ніж раз на 60 с: %r" % pol[2:3])
    want(len(pol) > 3 and pol[3] == "blocked writes=0 dirty=1 flush=1 dirty2=0 flush2=0", "Е4: заборона відкладає; дозапис при вимкненні; повторний -- не пише: %r" % pol[3:4])
    want(g("MARKALL") == "n=2 unread=0", "Е5: «усі прочитані» переживають перезапуск: %r" % g("MARKALL"))
    want(re.match(r"slot=\d+ n=0$", g("DELALL") or "") is not None, "Е6: «Видалити все» переживає перезапуск: %r" % g("DELALL"))
    return ok[0]


def main():
    if not shutil.which("gcc"):
        print("ПРОПУСК: gcc нема -- НЕ «пройдено»"); FAILS.append("gcc"); return finish()
    src = rd(SRC)
    out, err = build(src)
    check(out is not None, "0: хостова збірка (aprs_msg_store.c + aprs_msg.c + модель NOR): %s" % err)
    if out is None:
        return finish()
    core(out)

    # ---- Ж: проводка
    h = rd(os.path.join(APP, "include", "functions", "aprs_msg_store.h"))
    am = rd(os.path.join(APP, "source", "applicationMain.c"))
    bp = rd(os.path.join(APP, "source", "interfaces", "batteryAndPowerManagement.c"))
    sp = rd(os.path.join(APP, "source", "hardware", "SPI_Flash.c"))
    msg_h = rd(os.path.join(APP, "include", "functions", "aprs_msg.h"))
    check("#define AMS_REGION_ADDR     0x40000UL" in h and "#define AMS_SLOTS           8U" in h and "#define AMS_DEFER_S         60U" in h,
          "Ж1: ділянка 0x40000, 8 слотів, T = 60 с")
    check(re.search(r"menuSystemInit\(getRtcTime_custom\(\)\);\n#if defined\(APRS_MSG1_UI\)\n\taprsMsgStoreLoad\(\);", am) is not None,
          "Ж2: завантаження ПІСЛЯ menuSystemInit (годинник уже прочитано), під APRS_MSG1_UI")
    check(re.search(r"aprsMsgBgTick\(\);[^\n]*\n#if defined\(APRS_MSG1_UI\)\n\t\taprsMsgStoreTick\(\);", am) is not None, "Ж3: тік у головному циклі після aprsMsgBgTick")
    check(len(re.findall(r"dcFlushPending\(\);[^\n]*\n#endif\n#if defined\(APRS_MSG1_UI\)\n\taprsMsgStoreFlush\(\);", bp)) == 2, "Ж4: дозапис в ОБОХ шляхах вимкнення")
    pb = sp[sp.index("bool SPI_Flash_programBytes"):]
    pb = pb[:pb.index("\n}\n")]
    check("#if defined(APRS_MSG1_UI)\n/* R101" in sp and "sectorbuffer" not in pb and "0x100" not in pb and "PAGE_PGM, addr >> 16, addr >> 8, addr" in pb,
          "Ж5: програмування без RMW, без SPI_Flash_sectorbuffer і без 256-Б буфера, лише під APRS_MSG1_UI")
    st = rd(SRC)
    check("sectorbuffer" not in st and "SPI_Flash_write(" not in st, "Ж6: модуль не використовує SPI_Flash_write (RMW) і SPI_Flash_sectorbuffer")
    check("#if defined(APRS_MSG1_UI) || defined(APRS_MSG_STORE_HOST_TEST)\n\t/* R101" in msg_h and "_Static_assert(sizeof(aprsMsgBox_t) == 1336U" in st,
          "Ж7: стан -- у вирівнюванні aprsMsgBox_t (1336 Б), нової пам'яті нема")

    # ---- З: мутанти
    def mut(name, a, b):
        s2 = src.replace(a, b, 1)
        if s2 == src:
            check(False, "З (%s): шаблон не знайдено" % name); return
        o2, e2 = build(s2)
        if o2 is None:
            check(True, "З (%s): не збирається -- ловиться" % name); return
        n0 = len(FAILS); QUIET[0] = True
        ok = core(o2, " [m]")
        QUIET[0] = False; del FAILS[n0:]
        check(not ok, "З (%s): ловиться" % name)
    data_blk = '''	/* 1) дані */
	memset(&s, 0, sizeof(s));
	s.program = true;
	s.ok = true;
	s.addr = slotAddr((unsigned)target) + AMS_HDR_LEN;
	(void)serialize(b, now, clk, &s);
	sinkFlush(&s);
	if (s.ok == false)
	{
		return false;
	}
'''
    hdr_blk = '''	/* 2) заголовок -- ОСТАННІМ: до цього слот не вважається цілим */
	if (SPI_Flash_programBytes(slotAddr((unsigned)target), (const uint8_t *)&h, AMS_HDR_PROG_LEN) == false)
	{
		return false;
	}
'''
    mut("заголовок перед даними", data_blk + hdr_blk, hdr_blk + data_blk)
    mut("без CRC", "(h->crcHdr == amsCrc(0U, (const uint8_t *)h, AMS_HDR_CRC_LEN))", "true")
    mut("без CRC даних", "return (crc == h->crcData);", "return true;")
    mut("стирається найновіший слот", "\t/* заголовок -- із «сухого» проходу", "\tif (nw >= 0) { target = nw; }\n\t/* заголовок -- із «сухого» проходу")
    mut("час не абсолютний", "\treturn clk - age;\n}", "\treturn e->ms;\n}")
    mut("запис на кожному тіку", "if ((b->storeAge < AMS_DEFER_S) || (writeAllowed == false))", "if (writeAllowed == false)")
    return finish()


def finish():
    print("test_r101aprsmsg: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
