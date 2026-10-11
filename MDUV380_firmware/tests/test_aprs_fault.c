/*
 * test_aprs_fault.c -- R10-fix4: хостовий тест ЧИСТОЇ частини обробника збою (functions/aprs_fault_fmt.c): hex/десяткове
 * форматування, розшифрування CFSR, пошук адрес повернення у стеку, магія запису. Залізна частина (aprs_fault.c) на хості
 * не виконується -- її перевіряє дизасемблювання й залізо (TESTING.md, блок AR).
 */
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include "functions/aprs_fault_fmt.h"

static int s_fail = 0;
#define CHECK(c, ...) do { if (!(c)) { s_fail++; printf("ПРОВАЛ %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

int main(void)
{
	char b[16];

	/* hex: завжди 8 цифр, верхній регістр, NUL */
	memset(b, 'x', sizeof(b));
	aprsFaultHex8(b, 0x0800ABCDU);
	CHECK(strcmp(b, "0800ABCD") == 0, "hex8 = %s", b);
	aprsFaultHex8(b, 0U);
	CHECK(strcmp(b, "00000000") == 0, "hex8 0 = %s", b);
	aprsFaultHex8(b, 0xFFFFFFFFU);
	CHECK(strcmp(b, "FFFFFFFF") == 0, "hex8 max = %s", b);

	/* десяткове */
	CHECK((aprsFaultDec(b, 0U) == 1U) && (strcmp(b, "0") == 0), "dec 0 = %s", b);
	CHECK((aprsFaultDec(b, 402U) == 3U) && (strcmp(b, "402") == 0), "dec 402 = %s", b);
	CHECK((aprsFaultDec(b, 4294967295U) == 10U) && (strcmp(b, "4294967295") == 0), "dec max = %s", b);

	/* види */
	for (uint32_t k = 0; k <= 9; k++)
	{
		CHECK(aprsFaultKindName(k)[0] != 0, "kind %u без назви", (unsigned)k);
	}
	CHECK(strcmp(aprsFaultKindName(AFLT_KIND_HARD), "HARDFAULT") == 0, "HARD");
	CHECK(strcmp(aprsFaultKindName(AFLT_KIND_WDG), "WATCHDOG") == 0, "WDG");

	/* магія: туди й назад; чужі слова відкидаються */
	for (uint32_t k = AFLT_KIND_HARD; k <= AFLT_KIND_IWDG; k++)
	{
		CHECK(aprsFaultKindFromMagic(aprsFaultMagicFromKind(k)) == k, "магія виду %u", (unsigned)k);
	}
	CHECK(aprsFaultKindFromMagic(0U) == AFLT_KIND_NONE, "магія 0");
	CHECK(aprsFaultKindFromMagic(0xFFFFFFFFU) == AFLT_KIND_NONE, "магія FFFFFFFF");
	CHECK(aprsFaultKindFromMagic(0xFA170000UL | 7U) == AFLT_KIND_NONE, "магія вид 7");
	CHECK(aprsFaultKindFromMagic(0xFA180001UL) == AFLT_KIND_NONE, "магія чужа база");

	/* CFSR: найважливіший біт виграє; нуль -- порожній рядок */
	CHECK(aprsFaultCfsrName(0U)[0] == 0, "cfsr 0");
	CHECK(strcmp(aprsFaultCfsrName(1UL << 16), "UNDEFINSTR") == 0, "UNDEFINSTR");
	CHECK(strcmp(aprsFaultCfsrName(1UL << 17), "INVSTATE") == 0, "INVSTATE");
	CHECK(strcmp(aprsFaultCfsrName(1UL << 25), "DIVBYZERO") == 0, "DIVBYZERO");
	CHECK(strncmp(aprsFaultCfsrName(1UL << 10), "IMPRECISE", 9) == 0, "IMPRECISE");
	CHECK(strcmp(aprsFaultCfsrName(1UL << 9), "PRECISERR") == 0, "PRECISERR");
	CHECK(strcmp(aprsFaultCfsrName(1UL << 1), "DACCVIOL") == 0, "DACCVIOL");
	CHECK(strcmp(aprsFaultCfsrName((1UL << 17) | (1UL << 9) | 1UL), "INVSTATE") == 0, "UFSR старший за BFSR/MMFSR");
	CHECK(strlen(aprsFaultCfsrName(1UL << 10)) <= 20U, "назва має вміщатись у рядок екрана 160 px / 8 px");
	for (int bit = 0; bit < 26; bit++)
	{
		const char *n = aprsFaultCfsrName(1UL << bit);
		CHECK(strlen(n) <= 20U, "біт %d: назва задовга", bit);
	}

	/* адреса коду: Thumb (непарна) у флеші */
	CHECK(aprsFaultAddrIsCode(0x0800ABCDU), "код");
	CHECK(!aprsFaultAddrIsCode(0x0800ABCCU), "парна адреса -- не Thumb");
	CHECK(!aprsFaultAddrIsCode(0x20001235U), "RAM");
	CHECK(!aprsFaultAddrIsCode(0x08100001U), "за межею флешу");
	CHECK(!aprsFaultAddrIsCode(1U), "1");

	/* пошук у стеку: порядок збережено, порожнє/сміття пропущено, дублікати поспіль злиті, ліміт */
	{
		uint32_t st[] = { 0U, 0x20001235U, 0x0800AAAB, 0x0800AAAB, 0xFFFFFFFFU, 0x0800BBBB, 0x08001001, 0x0800CCC1, 0x0800DDD1 };
		uint32_t out[AFLT_NSTK] = { 0 };
		int n = aprsFaultScanStack(st, sizeof(st) / sizeof(st[0]), out, AFLT_NSTK);

		CHECK(n == 4, "знайдено %d", n);
		CHECK(out[0] == 0x0800AAABU && out[1] == 0x0800BBBBU && out[2] == 0x08001001U && out[3] == 0x0800CCC1U, "порядок: %08X %08X %08X %08X",
				(unsigned)out[0], (unsigned)out[1], (unsigned)out[2], (unsigned)out[3]);
		CHECK(aprsFaultScanStack(st, 0, out, AFLT_NSTK) == 0, "порожній стек");
		CHECK(aprsFaultScanStack(st, 3, out, AFLT_NSTK) == 1, "обмежена довжина");
	}

	if (s_fail != 0)
	{
		printf("test_aprs_fault: %d провалів\n", s_fail);
		return 1;
	}
	printf("test_aprs_fault: усе гаразд\n");
	return 0;
}
