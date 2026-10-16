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

	/* адреса коду: Thumb (непарна) і лише всередині .text [lo, hi) -- не будь-що у флеші (R21 З1.1) */
	{
		const uint32_t lo = 0x0800C100U, hi = 0x08040000U;   /* умовний .text; далі до 0x08075000 -- .rodata (шрифти) */

		CHECK(aprsFaultAddrIsCode(0x0800CBCDU, lo, hi), "код");
		CHECK(!aprsFaultAddrIsCode(0x0800CBCCU, lo, hi), "парна адреса -- не Thumb");
		CHECK(!aprsFaultAddrIsCode(0x20001235U, lo, hi), "RAM");
		CHECK(!aprsFaultAddrIsCode(0x10000011U, lo, hi), "CCM");
		CHECK(!aprsFaultAddrIsCode(0x0806961DU, lo, hi), "rodata (font_6x8) вище .text");
		CHECK(!aprsFaultAddrIsCode(0x0800C0FFU, lo, hi), "вектори/нижче .text");
		CHECK(aprsFaultAddrIsCode(0x0800C101U, lo, hi), "перша адреса .text");
		CHECK(!aprsFaultAddrIsCode(hi + 1U, lo, hi), "саме за кінцем .text");
		CHECK(aprsFaultAddrIsCode(hi - 1U, lo, hi), "остання непарна в .text");
		CHECK(!aprsFaultAddrIsCode(1U, lo, hi), "1");
	}

	/* пошук у стеку: порядок збережено, порожнє/сміття пропущено, дублікати поспіль злиті, ліміт */
	{
		const uint32_t lo = 0x0800C100U, hi = 0x08040000U;
		uint32_t st[] = { 0U, 0x20001235U, 0x0800AAAB, 0x0800AAAB, 0xFFFFFFFFU, 0x0800BBBB, 0x0800D001, 0x0800CCC1, 0x0800DDD1 };
		uint32_t out[AFLT_NSTK] = { 0 };
		int n = aprsFaultScanStack(st, sizeof(st) / sizeof(st[0]), out, AFLT_NSTK, lo - 0xC000U, hi);

		CHECK(n == 5 || AFLT_NSTK < 5, "знайдено %d", n);
		CHECK(out[0] == 0x0800AAABU && out[1] == 0x0800BBBBU && out[2] == 0x0800D001U && out[3] == 0x0800CCC1U, "порядок: %08X %08X %08X %08X",
				(unsigned)out[0], (unsigned)out[1], (unsigned)out[2], (unsigned)out[3]);
		CHECK(aprsFaultScanStack(st, 0, out, AFLT_NSTK, lo, hi) == 0, "порожній стек");
		CHECK(aprsFaultScanStack(st, 4, out, AFLT_NSTK, lo - 0xC000U, hi) == 1, "обмежена довжина");
	}

	/* R21 З1.1: суміш .text / .rodata / RAM / сміття -> у звіт лише .text, без font_* */
	{
		const uint32_t lo = 0x0800C100U, hi = 0x08040000U;
		uint32_t st[] = {
			0x0806961DU,   /* font_6x8 у .rodata (адреса з реального збою) */
			0x0800D235U,   /* .text */
			0x20007659U,   /* RAM, непарне */
			0x08100001U,   /* поза флешем */
			0x0801E3A9U,   /* .text */
			0x0805B9A9U,   /* _printf_i+0x1E0 (у реальній збірці це .text; тут за межею умовного hi) */
			0x08041001U,   /* .rodata умовного образу */
			0x0803FFFFU,   /* остання непарна .text */
			0x00000001U, 0xDEADBEEFU, 0xFFFFFFFFU,
			0x0800C101U    /* перша адреса .text */
		};
		uint32_t out[8] = { 0 };
		int n = aprsFaultScanStack(st, sizeof(st) / sizeof(st[0]), out, 8, lo, hi);

		CHECK(n == 4, "суміш: знайдено %d, чекали 4", n);
		CHECK(out[0] == 0x0800D235U && out[1] == 0x0801E3A9U && out[2] == 0x0803FFFFU && out[3] == 0x0800C101U,
				"суміш: %08X %08X %08X %08X", (unsigned)out[0], (unsigned)out[1], (unsigned)out[2], (unsigned)out[3]);
		for (int i = 0; i < n; i++)
		{
			CHECK(out[i] >= lo && out[i] < hi && (out[i] & 1U) != 0U, "кадр %d поза .text: %08X", i, (unsigned)out[i]);
		}
		/* ліміт maxOut і запас: кадрів у записі не менше 6 у користувацькій збірці */
		CHECK(aprsFaultScanStack(st, sizeof(st) / sizeof(st[0]), out, 2, lo, hi) == 2, "ліміт maxOut = 2");
	}
#if !defined(APRS_MODE_TRACE)
	CHECK(AFLT_NSTK >= 6, "R21 З1.1: у користувацькій збірці має бути не менше 6 кадрів стека (зараз %d)", AFLT_NSTK);
#endif

	if (s_fail != 0)
	{
		printf("test_aprs_fault: %d провалів\n", s_fail);
		return 1;
	}
	printf("test_aprs_fault: усе гаразд\n");
	return 0;
}
