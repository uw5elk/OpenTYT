/*
 * test_sms_format.c -- ui6: перенесення за словами, форма слова «непрочитане», формат часу
 * (сьогодні / не сьогодні, часовий пояс). Лінкує СПРАВЖНІЙ functions/sms_format.c.
 * Кирилиця -- лише байтами cp1251 (файл UTF-8).
 */
#include <stdio.h>
#include <string.h>
#include "functions/sms_format.h"

static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

/* Розбити текст на рядки й склеїти через '|' -- зручно порівнювати. */
static void wrapAll(const char *s, int w, char *out, int outsz)
{
	int len = (int)strlen(s), pos = 0, o = 0, ls, nx;
	out[0] = 0;
	while (pos < len)
	{
		int l = smsWrapLine(s, len, pos, w, &ls, &nx);
		if (l > 0)
		{
			if (o > 0 && o < outsz - 1) { out[o++] = '|'; }
			for (int i = 0; i < l && o < outsz - 1; i++) { out[o++] = s[ls + i]; }
			out[o] = 0;
		}
		if (nx <= pos) { break; }
		pos = nx;
	}
}

int main(void)
{
	char buf[256];
	printf("test_sms_format:\n");

	/* 1. Перенесення за словами. */
	{
		/* «Привіт. Тест кирилиці на OpenTYT.» (cp1251) */
		static const char T1[] = "\317\360\350\342\263\362. \322\345\361\362 \352\350\360\350\353\350\366\263 \355\340 OpenTYT.";
		static const char W1[] = "\317\360\350\342\263\362. \322\345\361\362|\352\350\360\350\353\350\366\263 \355\340 OpenTYT.";
		wrapAll(T1, 20, buf, sizeof buf);
		CHECK(strcmp(buf, W1) == 0, "«Привіт. Тест кирилиці на OpenTYT.» W=20 -> «Привіт. Тест» / «кирилиці на OpenTYT.»");
		CHECK(smsWrapCount(T1, (int)strlen(T1), 20) == 2, "рядків: 2");

		/* Слово на 25 символів -- рубається по 20. */
		wrapAll("ABCDEFGHIJKLMNOPQRSTUVWXY ok", 20, buf, sizeof buf);
		CHECK(strcmp(buf, "ABCDEFGHIJKLMNOPQRST|UVWXY ok") == 0, "слово 25 символів: '%s'", buf);
		CHECK(smsWrapCount("ABCDEFGHIJKLMNOPQRSTUVWXY", 25, 20) == 2, "слово 25 символів -- 2 рядки");

		/* Кілька пробілів поспіль: на межі рядка -- пропускаються, всередині -- лишаються. */
		wrapAll("aaaa bbbb     cccc  dddddddddd eeee", 20, buf, sizeof buf);
		CHECK(strcmp(buf, "aaaa bbbb     cccc|dddddddddd eeee") == 0, "кілька пробілів: '%s'", buf);
		wrapAll("   start", 20, buf, sizeof buf);
		CHECK(strcmp(buf, "start") == 0, "пробіли на початку тексту пропущено");
		wrapAll("aaaaaaaaaaaaaaaaaaaa      bbb", 20, buf, sizeof buf);
		CHECK(strcmp(buf, "aaaaaaaaaaaaaaaaaaaa|bbb") == 0, "пробіли на початку наступного рядка пропущено: '%s'", buf);

		/* Порожній текст і самі пробіли. */
		CHECK(smsWrapCount("", 0, 20) == 0, "порожній текст -- 0 рядків");
		CHECK(smsWrapCount("     ", 5, 20) == 0, "самі пробіли -- 0 рядків");
		int ls, nx;
		CHECK(smsWrapLine("", 0, 0, 20, &ls, &nx) == 0 && nx == 0, "порожній: довжина 0, next = len");

		/* Рівно 20 символів -- один рядок; 21 без пробілу -- два. */
		CHECK(smsWrapCount("12345678901234567890", 20, 20) == 1, "рівно 20 -- 1 рядок");
		CHECK(smsWrapLine("12345678901234567890", 20, 0, 20, &ls, &nx) == 20 && nx == 20, "рівно 20: довжина 20");
		wrapAll("12345678901234567890 x", 20, buf, sizeof buf);
		CHECK(strcmp(buf, "12345678901234567890|x") == 0, "20 + пробіл + x: '%s'", buf);
		wrapAll("123456789012345678901", 20, buf, sizeof buf);
		CHECK(strcmp(buf, "12345678901234567890|1") == 0, "21 без пробілу: '%s'", buf);
		/* Пробіл рівно на позиції 20 від початку рядка -- розрив саме там, не раніше. */
		wrapAll("aaa bbbbbbbbbbbbbbbb cc", 20, buf, sizeof buf);
		CHECK(strcmp(buf, "aaa bbbbbbbbbbbbbbbb|cc") == 0, "пробіл одразу за 20-м: '%s'", buf);
	}

	/* 2. Форма слова. */
	{
		static const int N[]  = { 1, 2, 3, 4, 5, 10, 11, 12, 14, 15, 20, 21, 22, 24, 25, 101, 111, 112, 122, 0 };
		static const int F[]  = { 0, 1, 1, 1, 2,  2,  2,  2,  2,  2,  2,  0,  1,  1,  2,   0,   2,   2,   1, 2 };
		int ok = 1;
		for (unsigned i = 0; i < sizeof N / sizeof N[0]; i++)
		{
			if (smsPluralForm(N[i]) != F[i]) { ok = 0; printf("       %d -> %d (треба %d)\n", N[i], smsPluralForm(N[i]), F[i]); }
		}
		CHECK(ok, "1 непрочитане, 2-4 непрочитані, 5-20 непрочитаних, 21 непрочитане, 22-24 непрочитані, 11-14 непрочитаних");
	}

	/* 3. Часовий пояс -- як годинник головного екрана. */
	{
		CHECK(smsTzOffsetSecs(0x00 | 76) == 0, "біт 7 = 0 (UTC) -> зсув 0");
		CHECK(smsTzOffsetSecs(0x80 | 64) == 0, "місцевий, UTC+0");
		CHECK(smsTzOffsetSecs(0x80 | (64 + 8)) == 7200, "UTC+2 -> 7200 с");
		CHECK(smsTzOffsetSecs(0x80 | (64 + 12)) == 10800, "UTC+3 -> 10800 с");
		CHECK(smsTzOffsetSecs(0x80 | (64 - 20)) == -18000, "UTC-5 -> -18000 с");
	}

	/* 4. Формат часу. 2026-10-05 21:30:00 UTC = 1791235800. */
	{
		const uint32_t t = 1791235800U;
		smsTimeFormat(t, t + 60, 0, SMS_TIME_SHORT, buf, 12);
		CHECK(strcmp(buf, "21:30") == 0, "UTC, сьогодні -> «21:30» (%s)", buf);
		smsTimeFormat(t, t + 60, 10800, SMS_TIME_SHORT, buf, 12);
		CHECK(strcmp(buf, "00:30") == 0, "UTC+3: і повідомлення, і «зараз» -- 06.10 місцевого -> «00:30» (%s)", buf);
		smsTimeFormat(t, t - 3600, 10800, SMS_TIME_SHORT, buf, 12);
		CHECK(strcmp(buf, "06.10") == 0, "UTC+3: «зараз» 05.10 23:30 місцевого, повідомлення 06.10 -> дата (%s)", buf);
		smsTimeFormat(t, t - 3600, 0, SMS_TIME_SHORT, buf, 12);
		CHECK(strcmp(buf, "21:30") == 0, "той самий момент у UTC -- один день -> «21:30» (%s)", buf);
		smsTimeFormat(t, t + 86400, 0, SMS_TIME_SHORT, buf, 12);
		CHECK(strcmp(buf, "05.10") == 0, "вчорашнє -> «05.10» (%s)", buf);
		smsTimeFormat(t, 0, 0, SMS_TIME_SHORT, buf, 12);
		CHECK(strcmp(buf, "05.10") == 0, "годинник не виставлено -> дата (%s)", buf);
		smsTimeFormat(t, t, 10800, SMS_TIME_FULL, buf, 12);
		CHECK(strcmp(buf, "06.10 00:30") == 0, "повний, UTC+3 -> «06.10 00:30» (%s)", buf);
		smsTimeFormat(t, t, -18000, SMS_TIME_HM, buf, 12);
		CHECK(strcmp(buf, "16:30") == 0, "лише час, UTC-5 -> «16:30» (%s)", buf);
		CHECK(smsTimeFormat(0, t, 0, SMS_TIME_FULL, buf, 12) == 0 && buf[0] == 0, "час 0 -> порожньо");
		smsTimeFormat(1709251199U, 1709251199U, 0, SMS_TIME_FULL, buf, 12);   /* 2024-02-29 23:59:59 */
		CHECK(strcmp(buf, "29.02 23:59") == 0, "високосний 29.02 (%s)", buf);
		smsTimeFormat(1735689600U, 1735689600U, 0, SMS_TIME_FULL, buf, 12);   /* 2025-01-01 00:00 */
		CHECK(strcmp(buf, "01.01 00:00") == 0, "2025-01-01 (%s)", buf);
		smsTimeFormat(t, t, 0, SMS_TIME_FULL, buf, 6);
		CHECK(strlen(buf) < 6, "малий буфер не переповнюється (%s)", buf);
	}

	printf(fails ? "ПРОВАЛЕНО: %d\n" : "ПРОЙДЕНО\n", fails);
	return fails ? 1 : 0;
}
