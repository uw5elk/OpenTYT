#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_r112stockfix.py -- R112-STOCKFIX: стокові дрібниці R104 Д1, Д2, Д3 (codeplug.c, SPI_Flash.c) на хості.

Беруться СПРАВЖНІ тексти функцій з файлів прошивки (вирізаються за сигнатурою) і збираються хостовим gcc разом з моделлю NOR-флешу
(стирання сектора -> 0xFF, програмування сторінки -> AND, лічильник стирань на сектор, примусові збої запису).
  Д2  SPI_Flash_write: запис рівно до межі сектора -- стирається лише зайнятий сектор, сусідній не стирається й не змінюється; через межу -- 2 сектори;
      1 байт; 4096 Б з межі -- 1 сектор; 4097 Б з межі -- 2; size = 0 -- жодного стирання, true; у кожному випадку решта байтів секторів збережена.
  Д1  обхід ланцюга custom-data: dataLength = 0, 8, на межі області, 0xFFFFFFF8, 0xFFFFFFFF, 0x7FFFFFFF, довжина за областю -- обхід ЗАВЖДИ завершується
      (сторож у моделі: > 100000 читань -- «завис»); коректні ланцюги (200 випадкових) читаються так само, як старою функцією (без рядків R112).
  Д3  codeplugSetOpenGD77CustomData: збій першого (заголовок) або другого (дані) SPI_Flash_write -> false; обидва успішні -> true; обидва записи
      виконуються навіть після збою першого (як до R112).
  М   мутанти: Д2 «(pos + size) / 4096», Д2 без перевірки size <= 0, Д1 без перевірки довжини, Д3 «return true» -- ловляться.
"""
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.normpath(os.path.join(HERE, ".."))
SPI = os.path.join(FW, "application", "source", "hardware", "SPI_Flash.c")
CP = os.path.join(FW, "application", "source", "functions", "codeplug.c")
FAILS = []
N = [0]
QUIET = [False]

D1_BLOCK = '''			// R112 Д1: довжина блока більша за всю область custom-data (MAX_BLOCK_ADDRESS) -- ланцюг пошкоджений: обхід завершується як «блока нема».
			// Без цього адреса нижче «загортається» по модулю 2^32 (напр. dataLength = 0xFFFFFFF8 -> та сама адреса), і цикл на старті міг бути нескінченним.
			if ((uint32_t)blockHeader->dataLength > MAX_BLOCK_ADDRESS)
			{
				return 0;
			}

'''


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m)
        if not QUIET[0]:
            print("ПРОВАЛ:", m)


def rd(p):
    return open(p, encoding="utf-8").read()


def fn(text, sig):
    a = text.index(sig)
    b = text.index("\n}\n", a) + 3
    return text[a:b]


PRE = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#define FLASH_SIZE (0x40000)
#define FLASH_ADDRESS_OFFSET (128 * 1024)
static uint8_t g_flash[FLASH_SIZE];
static int g_erase[FLASH_SIZE / 4096];
static long g_reads;
static int g_writeCall, g_failWriteCall;      /* SPI_Flash_write: номер виклику, що «не вдається» (0 -- ні) */
uint8_t SPI_Flash_sectorbuffer[4096];
bool SPI_Flash_read(uint32_t addr, uint8_t *dataBuf, int size)
{
	if (++g_reads > 100000) { printf("HANG\n"); exit(0); }
	if ((addr + (uint32_t)size) > FLASH_SIZE) { memset(dataBuf, 0xFF, size); return true; }
	memcpy(dataBuf, g_flash + addr, size); return true;
}
bool SPI_Flash_eraseSector(uint32_t a) { g_erase[a / 4096]++; memset(g_flash + a, 0xFF, 4096); return true; }
bool SPI_Flash_writePage(uint32_t a, uint8_t *d) { for (int i = 0; i < 256; i++) g_flash[a + i] &= d[i]; return true; }
'''


def build_and_run(spi_text, cp_text, main):
    d = tempfile.mkdtemp(prefix="r112_")
    try:
        w = fn(spi_text, "bool SPI_Flash_write(uint32_t addr, uint8_t *dataBuf, int size)\n{")
        w = w.replace("bool SPI_Flash_write(uint32_t addr, uint8_t *dataBuf, int size)\n{",
                      "static bool SPI_Flash_write_real(uint32_t addr, uint8_t *dataBuf, int size)\n{", 1)
        wrap = ("bool SPI_Flash_write(uint32_t addr, uint8_t *dataBuf, int size)\n{\n\tg_writeCall++;\n"
                "\tbool r = SPI_Flash_write_real(addr, dataBuf, size);\n\treturn (g_writeCall == g_failWriteCall) ? false : r;\n}\n")
        cp = ("typedef int CodeplugCustomDataType_t;\n#define CODEPLUG_CUSTOM_DATA_TYPE_EMPTY ((int)0xFFFFFFFF)\n"
              "typedef struct\n{\n\tint dataType;\n\tint dataLength;\n} codeplugCustomDataBlockHeader_t;\n")
        for sig in ("static uint32_t codeplugGetOpenGD77CustomDataStartAddressForType(", "static uint32_t codeplugGetOpenGD77CustomDataFirstEmptySlot(int len)",
                    "bool codeplugGetOpenGD77CustomDataBounded(", "bool codeplugSetOpenGD77CustomData("):
            cp += fn(cp_text, sig) + "\n"
        src = PRE + "static bool SPI_Flash_write_real(uint32_t addr, uint8_t *dataBuf, int size);\n" + w + wrap + cp + main
        cp_ = os.path.join(d, "t.c")
        open(cp_, "w", encoding="utf-8").write(src)
        exe = os.path.join(d, "t")
        r = subprocess.run(["gcc", "-std=gnu11", "-O1", "-w", "-o", exe, cp_], capture_output=True, text=True)
        if r.returncode != 0:
            return None, r.stderr[-1500:]
        p = subprocess.run([exe], capture_output=True, text=True, timeout=120)
        return p.stdout, ""
    finally:
        shutil.rmtree(d, ignore_errors=True)


MAIN_D2D3 = r'''
static void fillPattern(void) { for (int i = 0; i < FLASH_SIZE; i++) g_flash[i] = (uint8_t)(i * 7 + 3); memset(g_erase, 0, sizeof g_erase); }
static void wcase(const char *tag, uint32_t pos, int size)
{
	static uint8_t data[8192]; static uint8_t before[FLASH_SIZE];
	fillPattern(); memcpy(before, g_flash, FLASH_SIZE);
	for (int i = 0; i < size; i++) data[i] = (uint8_t)(0xA5 ^ i);
	bool ok = SPI_Flash_write(pos, data, size);
	int bad = 0, er = 0; char list[64] = ""; int n = 0;
	for (int i = 0; i < FLASH_SIZE; i++)
	{
		uint8_t want = ((i >= (int)pos) && (i < (int)pos + size)) ? data[i - pos] : before[i];
		if (g_flash[i] != want) bad++;
	}
	for (int s = 0; s < FLASH_SIZE / 4096; s++) { if (g_erase[s]) { er += g_erase[s]; n += snprintf(list + n, sizeof list - n, "%d,", s); } }
	printf("W %s ok=%d erases=%d sectors=%s bad=%d\n", tag, (int)ok, er, list, bad);
}
static void initRegion(void) { memset(g_flash, 0xFF, FLASH_SIZE); memcpy(g_flash + FLASH_ADDRESS_OFFSET, "OpenGD77\0\0\0\0", 12); }
static void putHdr(uint32_t at, int type, int len) { memcpy(g_flash + FLASH_ADDRESS_OFFSET + at, &type, 4); memcpy(g_flash + FLASH_ADDRESS_OFFSET + at + 4, &len, 4); }
int main(void)
{
	wcase("END_ON_BOUNDARY", 0x1F00, 0x100);
	wcase("CROSS", 0x1F80, 0x100);
	wcase("ONE", 0x2345, 1);
	wcase("ALIGNED_4096", 0x3000, 4096);
	wcase("ALIGNED_4097", 0x3000, 4097);
	wcase("ZERO", 0x3000, 0);
	wcase("ZERO_MID", 0x3456, 0);
	wcase("LAST_BYTE", 0x4FFF, 1);
	wcase("FIRST_BYTE", 0x5000, 1);
	/* Д3 */
	uint8_t b8[8] = { 1, 2, 3, 4, 5, 6, 7, 8 };
	for (int f = 0; f <= 2; f++)
	{
		initRegion(); putHdr(12, 19, 8); memset(g_flash + FLASH_ADDRESS_OFFSET + 20, 0, 8);
		g_writeCall = 0; g_failWriteCall = f;
		bool ok = codeplugSetOpenGD77CustomData(19, b8, 8);
		printf("D3 fail=%d ok=%d calls=%d data=%d\n", f, (int)ok, g_writeCall, memcmp(g_flash + FLASH_ADDRESS_OFFSET + 20, b8, 8) == 0);
	}
	g_failWriteCall = 0;
	return 0;
}
'''

MAIN_D1 = r'''
static void initRegion(void) { memset(g_flash, 0xFF, FLASH_SIZE); memcpy(g_flash + FLASH_ADDRESS_OFFSET, "OpenGD77\0\0\0\0", 12); }
static void putHdr(uint32_t at, int type, int len) { memcpy(g_flash + FLASH_ADDRESS_OFFSET + at, &type, 4); memcpy(g_flash + FLASH_ADDRESS_OFFSET + at + 4, &len, 4); }
int main(void)
{
	unsigned lens[] = { 0U, 8U, 0x10000U - 20U, 0x10000U - 12U, 0x10000U, 0x10001U, 0xFFFFFFF8U, 0xFFFFFFF4U, 0xFFFFFFFFU, 0x7FFFFFFFU, 0x80000000U };
	for (int i = 0; i < 11; i++)
	{
		uint8_t buf[16];
		initRegion(); putHdr(12, 5, (int)lens[i]); g_reads = 0;
		bool got = codeplugGetOpenGD77CustomDataBounded(19, buf, 8);   /* шукаємо блок, якого нема, -- обхід має закінчитися */
		g_reads = 0;
		bool set = codeplugSetOpenGD77CustomData(19, buf, 8);
		printf("D1 len=%08x got=%d set=%d\n", lens[i], (int)got, (int)set);
	}
	/* випадкові коректні ланцюги: тип -> адреса, як у старої функції */
	unsigned seed;
	while (scanf("%u", &seed) == 1)
	{
		srand(seed); initRegion();
		uint32_t at = 12; int n = 1 + rand() % 12;
		for (int k = 0; k < n; k++)
		{
			int len = 1 + rand() % 2600;
			if (at + 8 + len >= 0x10000) break;
			putHdr(at, 1 + k, len);
			for (int j = 0; j < len; j++) g_flash[FLASH_ADDRESS_OFFSET + at + 8 + j] = (uint8_t)rand();
			at += 8 + len;
		}
		printf("R %u", seed);
		for (int t = 1; t <= 14; t++)
		{
			codeplugCustomDataBlockHeader_t h; g_reads = 0;
			uint32_t a = codeplugGetOpenGD77CustomDataStartAddressForType(t, &h);
			uint8_t buf[64]; memset(buf, 0, sizeof buf);
			bool ok = codeplugGetOpenGD77CustomDataBounded(t, buf, 64);
			unsigned sum = 0; for (int j = 0; j < 64; j++) sum = sum * 31 + buf[j];
			printf(" %u:%u:%d:%u", (unsigned)t, (unsigned)a, (int)ok, sum);
		}
		codeplugCustomDataBlockHeader_t h; printf(" E:%u\n", (unsigned)codeplugGetOpenGD77CustomDataStartAddressForType(CODEPLUG_CUSTOM_DATA_TYPE_EMPTY, &h));
	}
	return 0;
}
'''


def build_and_run_input(spi_text, cp_text, main, inp):
    d = tempfile.mkdtemp(prefix="r112i_")
    try:
        out, err = None, ""
        src_main = main
        # той самий збирач, але з вводом
        w = fn(spi_text, "bool SPI_Flash_write(uint32_t addr, uint8_t *dataBuf, int size)\n{")
        w = w.replace("bool SPI_Flash_write(uint32_t addr, uint8_t *dataBuf, int size)\n{",
                      "static bool SPI_Flash_write_real(uint32_t addr, uint8_t *dataBuf, int size)\n{", 1)
        wrap = ("bool SPI_Flash_write(uint32_t addr, uint8_t *dataBuf, int size)\n{\n\tg_writeCall++;\n"
                "\tbool r = SPI_Flash_write_real(addr, dataBuf, size);\n\treturn (g_writeCall == g_failWriteCall) ? false : r;\n}\n")
        cp = ("typedef int CodeplugCustomDataType_t;\n#define CODEPLUG_CUSTOM_DATA_TYPE_EMPTY ((int)0xFFFFFFFF)\n"
              "typedef struct\n{\n\tint dataType;\n\tint dataLength;\n} codeplugCustomDataBlockHeader_t;\n")
        for sig in ("static uint32_t codeplugGetOpenGD77CustomDataStartAddressForType(", "static uint32_t codeplugGetOpenGD77CustomDataFirstEmptySlot(int len)",
                    "bool codeplugGetOpenGD77CustomDataBounded(", "bool codeplugSetOpenGD77CustomData("):
            cp += fn(cp_text, sig) + "\n"
        src = PRE + "static bool SPI_Flash_write_real(uint32_t addr, uint8_t *dataBuf, int size);\n" + w + wrap + cp + src_main
        cp_ = os.path.join(d, "t.c")
        open(cp_, "w", encoding="utf-8").write(src)
        exe = os.path.join(d, "t")
        r = subprocess.run(["gcc", "-std=gnu11", "-O1", "-w", "-o", exe, cp_], capture_output=True, text=True)
        if r.returncode != 0:
            return None, r.stderr[-1500:]
        p = subprocess.run([exe], input=inp, capture_output=True, text=True, timeout=120)
        return p.stdout, ""
    finally:
        shutil.rmtree(d, ignore_errors=True)


def checks_d2d3(out, tag=""):
    ok = [True]

    def want(c, m):
        ok[0] = ok[0] and bool(c)
        check(c, m + tag)
    W = {m.group(1): m.groups()[1:] for m in re.finditer(r"^W (\S+) ok=(\d) erases=(\d+) sectors=(\S*) bad=(\d+)$", out, re.M)}
    exp = {"END_ON_BOUNDARY": ("1", "1", "1,", "0"), "CROSS": ("1", "2", "1,2,", "0"), "ONE": ("1", "1", "2,", "0"), "ALIGNED_4096": ("1", "1", "3,", "0"),
           "ALIGNED_4097": ("1", "2", "3,4,", "0"), "ZERO": ("1", "0", "", "0"), "ZERO_MID": ("1", "0", "", "0"), "LAST_BYTE": ("1", "1", "4,", "0"),
           "FIRST_BYTE": ("1", "1", "5,", "0")}
    for k, v in exp.items():
        want(W.get(k) == v, "Д2: %s -- (ok, стирань, сектори, зіпсованих байтів) = %r, очікується %r" % (k, W.get(k), v))
    D3 = {m.group(1): m.groups()[1:] for m in re.finditer(r"^D3 fail=(\d) ok=(\d) calls=(\d+) data=(\d)$", out, re.M)}
    want(D3.get("0") == ("1", "2", "1"), "Д3: обидва записи вдались -- true: %r" % (D3.get("0"),))
    want(D3.get("1") == ("0", "2", "1"), "Д3: збій запису заголовка -- false (дані однаково записано, 2 виклики): %r" % (D3.get("1"),))
    want(D3.get("2") == ("0", "2", "1"), "Д3: збій запису даних -- false: %r" % (D3.get("2"),))
    return ok[0]


def checks_d1(out, ref_lines, tag=""):
    ok = [True]

    def want(c, m):
        ok[0] = ok[0] and bool(c)
        check(c, m + tag)
    want("HANG" not in out, "Д1: обхід завершується для всіх довжин (без «HANG»)")
    D1 = dict(re.findall(r"^D1 len=([0-9a-f]{8}) (got=\d set=\d)$", out, re.M))
    for ln in ("00000000", "00000008", "0000ffec", "0000fff4", "00010000", "00010001", "fffffff8", "fffffff4", "ffffffff", "7fffffff", "80000000"):
        want(ln in D1 and D1[ln].startswith("got=0"), "Д1: dataLength=0x%s -- блок 19 «нема», без зависання: %r" % (ln, D1.get(ln)))
    want(D1.get("fffffff8") == "got=0 set=0" and D1.get("7fffffff") == "got=0 set=0", "Д1: пошкоджений ланцюг -- новий блок не пишеться (місця не знайдено): %r" % D1)
    R = [l for l in out.splitlines() if l.startswith("R ")]
    if ref_lines is not None:
        want(R == ref_lines and len(R) == 200, "Д1: 200 випадкових коректних ланцюгів читаються так само, як старою функцією (розбіжностей %d)" %
             sum(1 for a, b in zip(R, ref_lines) if a != b))
    return ok[0]


def main():
    if not shutil.which("gcc"):
        print("ПРОПУСК: gcc нема -- test_r112stockfix не виконано (це не «пройдено»)")
        FAILS.append("gcc нема")
        return 1
    spi, cp = rd(SPI), rd(CP)
    # джерела: правки на місці
    check("flashEndSector = (flashWritePos + size - 1) / 4096;" in spi and "if (size <= 0)\n\t{\n\t\treturn (size == 0);\n\t}" in spi, "Д2: правка в SPI_Flash_write на місці")
    check(D1_BLOCK in cp, "Д1: перевірка довжини в обході ланцюга на місці")
    check("return (okHeader && okData);" in cp, "Д3: кон'юнкція результатів на місці")
    out, err = build_and_run(spi, cp, MAIN_D2D3)
    check(out is not None, "0: хостова збірка SPI_Flash_write + codeplugSetOpenGD77CustomData: %s" % err)
    if out is None:
        print("test_r112stockfix: перевірок %d, провалів %d" % (N[0], len(FAILS)))
        return 1
    checks_d2d3(out)
    seeds = list(range(1, 201))
    old_cp = cp.replace(D1_BLOCK, "")
    ref, err = build_and_run_input(spi, old_cp, MAIN_D1.replace("for (int i = 0; i < 11; i++)", "for (int i = 0; i < 0; i++)"), "\n".join(map(str, seeds)) + "\n")
    check(ref is not None, "Д1: хостова збірка старої функції: %s" % err)
    ref_lines = [l for l in (ref or "").splitlines() if l.startswith("R ")]
    out1, err = build_and_run_input(spi, cp, MAIN_D1, "\n".join(map(str, seeds)) + "\n")
    check(out1 is not None, "Д1: хостова збірка: %s" % err)
    if out1 is not None:
        checks_d1(out1, ref_lines)

    # М: мутанти
    def mut(name, which, a, b, kind):
        s_spi, s_cp = spi, cp
        if which == "spi":
            s_spi = spi.replace(a, b, 1)
            changed = s_spi != spi
        else:
            s_cp = cp.replace(a, b, 1)
            changed = s_cp != cp
        if not changed:
            check(False, "М (%s): шаблон не знайдено" % name)
            return
        n0 = len(FAILS)
        QUIET[0] = True
        if kind == "d2d3":
            o, _e = build_and_run(s_spi, s_cp, MAIN_D2D3)
            good = (o is not None) and checks_d2d3(o, " [m]")
        else:
            o, _e = build_and_run_input(s_spi, s_cp, MAIN_D1, "1\n")
            good = (o is not None) and checks_d1(o, None, " [m]")
        QUIET[0] = False
        del FAILS[n0:]
        check(not good, "М (%s): ловиться" % name)
    mut("Д2: (pos + size) / 4096", "spi", "flashEndSector = (flashWritePos + size - 1) / 4096;", "flashEndSector = (flashWritePos + size) / 4096;", "d2d3")
    mut("Д2: без size <= 0", "spi", "if (size <= 0)\n\t{\n\t\treturn (size == 0);\n\t}", "", "d2d3")
    mut("Д1: без перевірки довжини", "cp", D1_BLOCK, "", "d1")
    mut("Д3: return true", "cp", "return (okHeader && okData);", "(void)okHeader; (void)okData; return true;", "d2d3")
    print("test_r112stockfix: перевірок %d, провалів %d" % (N[0], len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
