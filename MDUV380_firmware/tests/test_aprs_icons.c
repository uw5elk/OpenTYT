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

#define ICON_BYTES  (APRS_ICON_W * APRS_ICON_H / 8)
static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

int main(void)
{
	bool ov;
	const uint8_t *a, *b;

	printf("== піктограми ==\n");
	CHECK(aprsIconCount() >= 20, "піктограм: %u (%u Б у flash)", aprsIconCount(), aprsIconCount() * 74U);
	{
		const char prim[] = ">[-b<kvjU#r&_YO^$I(!";
		int missing = 0, empty = 0, same = 0;

		for (size_t i = 0; prim[i]; i++)
		{
			a = aprsIconFind('/', prim[i], &ov);
			if (a == NULL) { missing++; printf("  FAIL нема піктограми /%c\n", prim[i]); continue; }
			int nz = 0;
			for (int k = 0; k < ICON_BYTES; k++) { nz += (a[k] != 0); }
			if (nz < 24) { empty++; }
			for (size_t j = i + 1; prim[j]; j++)
			{
				b = aprsIconFind('/', prim[j], &ov);
				if ((b != NULL) && (memcmp(a, b, ICON_BYTES) == 0)) { same++; printf("  FAIL /%c і /%c однакові\n", prim[i], prim[j]); }
			}
		}
		CHECK((missing == 0) && (empty == 0) && (same == 0), "20 первинних із брифу є, непорожні й попарно різні");
	}
	CHECK(APRS_ICON_W == 24 && APRS_ICON_H == 24 && ICON_BYTES == 72, "R17: піктограми 24x24, %d байтів кожна", ICON_BYTES);
	{
		/* суцільний контур: у кожної піктограми лівий/правий/верхній/нижній крайній шар ліній не рвано -- є хоч 2 суміжні пікселі
		 * по горизонталі й вертикалі, а самих пікселів не менше 60 (силует, а не крапки) і не більше 80% площі (є деталі) */
		int bad = 0;
		const char prim[] = ">[-b<kvjU#r&_YO^$I(!";

		for (size_t i = 0; prim[i]; i++)
		{
			const uint8_t *ic = aprsIconFind('/', prim[i], &ov);
			int ink = 0, hpair = 0, vpair = 0;

			if (ic == NULL) { bad++; continue; }
			for (int y = 0; y < 24; y++)
			{
				for (int x = 0; x < 24; x++)
				{
					int on = (ic[y * 3 + x / 8] >> (x % 8)) & 1;
					int onR = (x < 23) ? ((ic[y * 3 + (x + 1) / 8] >> ((x + 1) % 8)) & 1) : 0;
					int onD = (y < 23) ? ((ic[(y + 1) * 3 + x / 8] >> (x % 8)) & 1) : 0;

					ink += on;
					hpair += (on && onR);
					vpair += (on && onD);
				}
			}
			if ((ink < 60) || (ink > 24 * 24 * 8 / 10) || (hpair < 20) || (vpair < 20)) { bad++; printf("  FAIL піктограма /%c: ink=%d hpair=%d vpair=%d\n", prim[i], ink, hpair, vpair); }
		}
		CHECK(bad == 0, "усі 20 піктограм: силует із суцільними лініями (не крапки, не залита пляма)");
	}
	CHECK(aprsIconFind('/', 'Q', &ov) == NULL, "зарезервований /Q -> NULL (рамка зі знаком символу)");
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

	printf("== R20: повна таблиця ==\n");
	{
		int icons = 0, names = 0, nameNoIcon = 0, iconNoName = 0, empty = 0, bad = 0;
		static const char reservedP[] = "\"DJQ{}", reservedA[] = "\"1234567Z]}q";

		for (int c = '!'; c <= '~'; c++)
		{
			for (int tb = 0; tb < 2; tb++)
			{
				char t = tb ? '\\' : '/';
				const uint8_t *ic = aprsIconFind(t, (char)c, &ov);
				const char *nm = aprsSymbolNameEx(t, (char)c);
				int resv = (strchr(tb ? reservedA : reservedP, c) != NULL);

				icons += (ic != NULL);
				names += (nm != NULL);
				if ((nm != NULL) && (ic == NULL)) { nameNoIcon++; printf("  FAIL %c%c має назву «%s», але нема піктограми\n", t, c, nm); }
				if ((nm == NULL) && (ic != NULL)) { iconNoName++; printf("  FAIL %c%c має піктограму, але нема назви\n", t, c); }
				if (resv && (ic != NULL)) { bad++; printf("  FAIL зарезервований %c%c має піктограму\n", t, c); }
				if ((ic == NULL) && !resv) { bad++; printf("  FAIL %c%c: нема піктограми, а код не зарезервований\n", t, c); }
				if (ic != NULL)
				{
					int nz = 0;
					for (int k = 0; k < ICON_BYTES; k++) { nz += (ic[k] != 0); }
					if (nz < 6) { empty++; printf("  FAIL %c%c: майже порожня піктограма\n", t, c); }
				}
			}
		}
		CHECK((icons == 170) && ((unsigned)icons == aprsIconCount()), "піктограм %d (aprsIconCount() = %u), очікувано 170 (88 первинних + 82 додаткових; решта 18 кодів зарезервовані специфікацією)", icons, aprsIconCount());
		CHECK((nameNoIcon == 0) && (iconNoName == 0) && (names == icons), "кожен названий символ має піктограму й навпаки (назв %d)", names);
		CHECK((empty == 0) && (bad == 0), "піктограми непорожні, зарезервовані коди їх не мають");
	}
	{
		/* первинна таблиця -- пул A (є і в діагностичній збірці): кожна піктограма різна, крім навмисних повторів (накладка на ті самі зображення) */
		int same = 0;

		for (int c1 = '!'; c1 <= '~'; c1++)
		{
			const uint8_t *i1 = aprsIconFind('/', (char)c1, &ov);

			for (int c2 = c1 + 1; (i1 != NULL) && (c2 <= '~'); c2++)
			{
				const uint8_t *i2 = aprsIconFind('/', (char)c2, &ov);

				if ((i2 != NULL) && (memcmp(i1, i2, ICON_BYTES) == 0)) { same++; printf("  FAIL /%c і /%c однакові\n", c1, c2); }
			}
		}
		CHECK(same == 0, "усі первинні піктограми попарно різні");
	}
	CHECK(aprsIconFind('/', 0x7F, &ov) == NULL && aprsIconFind('/', ' ', &ov) == NULL, "код поза '!'...'~' -> NULL");

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
