/*
 * test_aprs_icons.c -- R14: піктограми 16x16 і назви символів APRS для вікна маяка.
 *
 * Перевіряє: усі піктограми різні й непорожні; пошук для первинної/додаткової таблиці й накладок; невідомий символ -> NULL;
 * назви -- до 12 символів, без дублікатів; перебір власного символу лишився по перших десяти (як до R14).
 * Збирається з aprs_icons.c + aprs_mode_cfg.c (див. run_tests.sh).
 */
#include <stdio.h>
#include <string.h>
#include "functions/aprs_icons.h"
#include "functions/aprs_mode_cfg.h"
#include "user_interface/languages/aprsmode_ua.h"

static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

int main(void)
{
	bool ov;
	const uint8_t *a, *b;

	printf("== піктограми ==\n");
	CHECK(aprsIconCount() >= 20, "піктограм: %u (%u Б у flash)", aprsIconCount(), aprsIconCount() * 34U);
	{
		const char prim[] = ">[-b<kvjU#r&_YO^$I(!";
		int missing = 0, empty = 0, same = 0;

		for (size_t i = 0; prim[i]; i++)
		{
			a = aprsIconFind('/', prim[i], &ov);
			if (a == NULL) { missing++; printf("  FAIL нема піктограми /%c\n", prim[i]); continue; }
			int nz = 0;
			for (int k = 0; k < 32; k++) { nz += (a[k] != 0); }
			if (nz < 8) { empty++; }
			for (size_t j = i + 1; prim[j]; j++)
			{
				b = aprsIconFind('/', prim[j], &ov);
				if ((b != NULL) && (memcmp(a, b, 32) == 0)) { same++; printf("  FAIL /%c і /%c однакові\n", prim[i], prim[j]); }
			}
		}
		CHECK((missing == 0) && (empty == 0) && (same == 0), "20 первинних із брифу є, непорожні й попарно різні");
	}
	CHECK(aprsIconFind('/', 'Z', &ov) == NULL, "невідомий символ /Z -> NULL (рамка з кодом)");
	a = aprsIconFind('/', '&', &ov);
	CHECK((a != NULL) && !ov, "/& -- без накладки");
	b = aprsIconFind('R', '&', &ov);
	CHECK((b != NULL) && ov && (b == a), "таблиця 'R' код '&' (шлюз із логу) -> піктограма шлюзу + накладка");
	b = aprsIconFind('\\', '&', &ov);
	CHECK((b == a) && !ov, "\\& -- та сама піктограма без накладки");
	CHECK((aprsIconFind('7', '>', &ov) == aprsIconFind('/', '>', &ov)), "накладка '7' на авто -> піктограма авто");
	CHECK((aprsIconFind('1', '#', &ov) != NULL) && ov && (aprsIconFind('1', '#', &ov) != aprsIconFind('/', '#', &ov)), "накладка на діджі -- піктограма додаткової таблиці");
	CHECK(aprsIconFind('~', '>', &ov) == NULL, "таблиці '~' нема -> NULL");
	CHECK((aprsIconFind('A', 'q', &ov) == NULL) && !ov, "невідомий код в додатковій -> NULL, накладки нема");

	printf("== назви символів ==\n");
	{
		int n1 = 0, n2 = 0, bad = 0;

		for (int c = '!'; c <= '~'; c++)
		{
			const char *p = aprsSymbolNameEx('/', (char)c);
			const char *q = aprsSymbolNameEx('\\', (char)c);

			if (p != NULL) { n1++; if ((strlen(p) == 0) || (strlen(p) > 12)) { bad++; printf("  FAIL назва /%c «%s»\n", c, p); } }
			if (q != NULL) { n2++; if ((strlen(q) == 0) || (strlen(q) > 12)) { bad++; printf("  FAIL назва \\%c «%s»\n", c, q); } }
		}
		CHECK((n1 >= 45) && (n2 >= 15) && (bad == 0), "первинних назв %d, додаткових %d, усі 1..12 символів", n1, n2);
	}
	CHECK(!strcmp(aprsSymbolNameEx('/', 'r'), APRSM_SYM_REPEATER), "/r -- «ретранслятор»");
	CHECK(!strcmp(aprsSymbolNameEx('/', '['), APRSM_SYM_HUMAN), "/[ -- «людина»");
	CHECK((aprsSymbolNameEx('R', '&') != NULL) && (aprsSymbolNameEx('R', '&') == aprsSymbolNameEx('\\', '&')), "накладка -> назва додаткової таблиці");
	CHECK(aprsSymbolNameEx('/', 0x7F) == NULL, "невідомий код -> NULL");
	CHECK(!strcmp(aprsModeSymbolName(0, '>' - '!'), APRSM_SYM_CAR) && (aprsModeSymbolName(1, '>' - '!') != NULL), "aprsModeSymbolName: стара поведінка + додаткова таблиця");

	printf("== перебір власного символу ==\n");
	{
		uint8_t t = 0, i = (uint8_t)('>' - '!');
		char seen[16];
		int n = 0;

		for (int k = 0; k < 12; k++)
		{
			aprsModeSymbolNextNamed(&t, &i);
			seen[n++] = (char)('!' + i);
			if (n >= 2 && seen[n - 1] == '>') { break; }
		}
		CHECK((n == 10) && (t == 0), "рівно 10 кроків по колу (було 10): %d", n);
		i = (uint8_t)('Z' - '!');
		aprsModeSymbolNextNamed(&t, &i);
		CHECK(('!' + i) == '>', "з довільного символу -- до першого названого");
	}

	printf(fails ? "ПРОВАЛЕНО: %d\n" : "ПРОЙДЕНО\n", fails);
	return fails ? 1 : 0;
}
