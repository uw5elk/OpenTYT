/*
 * test_sms_multitap.c -- хостовий тест multitap набору SMS (ui4, functions/sms_multitap.c).
 *
 * run_tests.sh збирає його двічі: як є (латиниця + «123») і з -DLANGUAGE_BUILD_UKRAINIAN
 * (бінарник test_sms_multitap_ua) -- кирилиця, «АБВ»/«абв», усі 66 літер.
 *
 * Кирилиця тут -- лише байтами cp1251 (файл у UTF-8).
 */
#include <stdio.h>
#include <string.h>
#include "functions/sms_multitap.h"

static int s_fail = 0;
#define CHECK(c, ...) do { if (!(c)) { s_fail++; printf("ПРОВАЛ %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

static const char KEYS[] = "0123456789*";

/* Знайти клавішу й номер натискання, що дають символ c у режимі mode. */
static int findKey(uint8_t mode, char c, char *key, int *presses)
{
	for (const char *k = KEYS; *k; k++)
	{
		const char *m = smsMtKeyMap(mode, *k);
		const char *p = strchr(m, c);
		if ((p != NULL) && (c != 0)) { *key = *k; *presses = (int)(p - m) + 1; return 1; }
	}
	return 0;
}

/* «Набрати» рядок так, як оператор: та сама клавіша поспіль -- спершу чекаємо таймаут
 * (smsMtCommit), інша -- одразу. Повертає 0, якщо якогось символу немає в розкладці. */
static int typeStr(uint8_t mode, const char *s, char *buf, int16_t *pos, smsMt_t *st, int cap)
{
	for (; *s; s++)
	{
		char key; int n;
		if (!findKey(mode, *s, &key, &n)) { return 0; }
		if (st->key == key) { smsMtCommit(st, pos); }           /* таймаут між однаковими */
		for (int i = 0; i < n; i++)
		{
			int r = smsMtKey(st, mode, key, i > 0, buf, pos, cap);
			if (r == 0) { return 0; }
			/* інваріант: за символом перегляду (або за підтвердженим текстом) -- нуль */
			CHECK(buf[*pos + (st->key ? 1 : 0)] == 0, "інваріант кінця рядка, pos=%d", *pos);
		}
	}
	smsMtCommit(st, pos);
	return 1;
}

static void testModes(void)
{
	/* Цикл '#': обходить усі режими й повертається. */
	uint8_t m = SMS_MT_DEFAULT;
	int seen = 0;
	for (int i = 0; i < SMS_MT_MODES; i++) { seen |= 1 << m; m = smsMtModeNext(m); }
	CHECK(m == SMS_MT_DEFAULT, "цикл режимів не замкнувся");
	CHECK(seen == (1 << SMS_MT_MODES) - 1, "не всі режими досяжні");
	CHECK(smsMtModeNext(200) == SMS_MT_DEFAULT, "неприпустимий режим -> типовий");
	CHECK(strcmp(smsMtModeLabel(SMS_MT_LAT_UP), "ABC") == 0, "підпис ABC");
	CHECK(strcmp(smsMtModeLabel(SMS_MT_LAT_LO), "abc") == 0, "підпис abc");
	CHECK(strcmp(smsMtModeLabel(SMS_MT_NUM), "123") == 0, "підпис 123");
	CHECK(smsMtModeNext(SMS_MT_LAT_LO) == SMS_MT_NUM, "abc -> 123");
#if defined(LANGUAGE_BUILD_UKRAINIAN)
	CHECK(SMS_MT_DEFAULT == SMS_MT_UA_LO, "типовий -- абв");
	CHECK(smsMtModeNext(SMS_MT_UA_UP) == SMS_MT_UA_LO, "АБВ -> абв");
	CHECK(smsMtModeNext(SMS_MT_UA_LO) == SMS_MT_LAT_UP, "абв -> ABC");
	CHECK(smsMtModeNext(SMS_MT_NUM) == SMS_MT_UA_UP, "123 -> АБВ");
	CHECK(strcmp(smsMtModeLabel(SMS_MT_UA_UP), "\xC0\xC1\xC2") == 0, "підпис АБВ");
	CHECK(strcmp(smsMtModeLabel(SMS_MT_UA_LO), "\xE0\xE1\xE2") == 0, "підпис абв");
#else
	CHECK(SMS_MT_DEFAULT == SMS_MT_LAT_LO, "типовий -- abc");
	CHECK(smsMtModeNext(SMS_MT_NUM) == SMS_MT_LAT_UP, "123 -> ABC");
#endif
	CHECK(smsMtKeyMap(SMS_MT_DEFAULT, '#') == NULL, "'#' -- не текстова");
	CHECK(smsMtKeyMap(SMS_MT_DEFAULT, 1) == NULL, "стрілка -- не текстова");
}

static void testLatin(void)
{
	char buf[64] = {0}; int16_t pos = 0; smsMt_t st = {0};
	CHECK(typeStr(SMS_MT_LAT_LO, "hello world 42", buf, &pos, &st, 60), "латиниця abc");
	CHECK(strcmp(buf, "hello world 42") == 0, "abc: '%s'", buf);
	CHECK(pos == 14, "pos %d", pos);

	memset(buf, 0, sizeof buf); pos = 0;
	CHECK(typeStr(SMS_MT_LAT_UP, "SOS QTH?", buf, &pos, &st, 60), "латиниця ABC");
	CHECK(strcmp(buf, "SOS QTH?") == 0, "ABC: '%s'", buf);

	/* Цикл клавіші '2' в abc: a b c 2 a ... */
	memset(buf, 0, sizeof buf); pos = 0;
	const char want[] = "abc2a";
	for (int i = 0; i < 5; i++)
	{
		CHECK(smsMtKey(&st, SMS_MT_LAT_LO, '2', i > 0, buf, &pos, 60) == 1, "перегляд");
		CHECK(buf[0] == want[i] && pos == 0, "крок %d: '%c'", i, buf[0]);
	}
	/* Вікно минуло -> та сама клавіша починає НОВИЙ символ. */
	CHECK(smsMtKey(&st, SMS_MT_LAT_LO, '2', false, buf, &pos, 60) == 1, "нове місце");
	CHECK(pos == 1 && strcmp(buf, "aa") == 0, "після таймауту: '%s' pos %d", buf, pos);
	smsMtCommit(&st, &pos);
	CHECK(pos == 2 && st.key == 0, "commit");
	smsMtCommit(&st, &pos);
	CHECK(pos == 2, "повторний commit -- без змін");
}

static void testNumAndStar(void)
{
	char buf[64] = {0}; int16_t pos = 0; smsMt_t st = {0};
	/* «123»: цифри підтверджуються одразу, навіть та сама клавіша поспіль. */
	for (const char *d = "0012399"; *d; d++)
	{
		CHECK(smsMtKey(&st, SMS_MT_NUM, *d, true, buf, &pos, 60) == 2, "цифра одразу");
	}
	CHECK(strcmp(buf, "0012399") == 0 && pos == 7 && st.key == 0, "123: '%s'", buf);

	/* '*' -- пробіл, далі спецсимволи; у «123» теж (номер «+380...»). */
	CHECK(smsMtKey(&st, SMS_MT_NUM, '*', false, buf, &pos, 60) == 1, "* перегляд");
	CHECK(buf[7] == ' ', "* перше -- пробіл");
	smsMtKey(&st, SMS_MT_NUM, '*', true, buf, &pos, 60);
	smsMtKey(&st, SMS_MT_NUM, '*', true, buf, &pos, 60);
	CHECK(buf[7] == '+', "* третє -- '+', є '%c'", buf[7]);
	/* Інша клавіша підтверджує '+'. */
	CHECK(smsMtKey(&st, SMS_MT_NUM, '3', false, buf, &pos, 60) == 2, "3");
	CHECK(strcmp(buf, "0012399+3") == 0, "'%s'", buf);

	/* '0' у буквених режимах: спершу пробіл, потім 0. */
	CHECK(smsMtKeyMap(SMS_MT_LAT_LO, '0')[0] == ' ', "0 -> пробіл");
	CHECK(smsMtKeyMap(SMS_MT_LAT_LO, '0')[1] == '0', "0 -> 0");
	/* Кожна клавіша має свою цифру (крім '*') у кожному режимі. */
	for (int m = 0; m < SMS_MT_MODES; m++)
	{
		for (char k = '0'; k <= '9'; k++)
		{
			CHECK(strchr(smsMtKeyMap((uint8_t)m, k), k) != NULL, "режим %d клавіша %c без цифри", m, k);
		}
	}
}

static void testBackspaceAndCap(void)
{
	char buf[16]; int16_t pos = 0; smsMt_t st = {0};
	memset(buf, 0, sizeof buf);
	CHECK(typeStr(SMS_MT_LAT_LO, "ab", buf, &pos, &st, 3), "ab");
	smsMtKey(&st, SMS_MT_LAT_LO, '3', false, buf, &pos, 3);      /* 'd' у перегляді */
	CHECK(strcmp(buf, "abd") == 0 && pos == 2 && st.key == '3', "перегляд d");
	/* Стерти: спершу перегляд. */
	smsMtBackspace(&st, buf, &pos);
	CHECK(strcmp(buf, "ab") == 0 && pos == 2 && st.key == 0, "стерто перегляд: '%s'", buf);
	smsMtBackspace(&st, buf, &pos);
	CHECK(strcmp(buf, "a") == 0 && pos == 1, "стерто b");
	smsMtBackspace(&st, buf, &pos);
	smsMtBackspace(&st, buf, &pos);
	CHECK(buf[0] == 0 && pos == 0, "порожньо, і зайве стирання не ламає");

	/* Ліміт cap = 3: четвертий символ не вміщається. */
	CHECK(typeStr(SMS_MT_LAT_LO, "xyz", buf, &pos, &st, 3), "xyz");
	CHECK(smsMtKey(&st, SMS_MT_LAT_LO, '2', false, buf, &pos, 3) == 0, "понад ліміт -- 0");
	CHECK(strcmp(buf, "xyz") == 0 && pos == 3, "текст не змінено: '%s'", buf);
	/* Гортання ОСТАННЬОГО символу на межі ліміту працює. */
	smsMtBackspace(&st, buf, &pos);
	CHECK(smsMtKey(&st, SMS_MT_LAT_LO, '2', false, buf, &pos, 3) == 1, "на межі -- можна");
	CHECK(smsMtKey(&st, SMS_MT_LAT_LO, '2', true, buf, &pos, 3) == 1, "гортати на межі");
	CHECK(strcmp(buf, "xyb") == 0 && buf[3] == 0, "'%s'", buf);
	/* Не текстова клавіша нічого не чіпає. */
	CHECK(smsMtKey(&st, SMS_MT_LAT_LO, '#', false, buf, &pos, 3) == 0, "#");
	CHECK(st.key == '2', "перегляд лишився");
}


/* R23 Y2.8: ліміт назви контакту -- 16 символів. Розкладка буфера, як у menuContactDetails.c: contactName[20], [16] -- NUL, [17..19] -- чужі байти
 * (там живе стан multitap, див. коментар у menuContactDetails.c): multitap не має їх чіпати за жодних обставин. */
static void testContactNameCap(void)
{
	char name[20]; int16_t pos = 0; smsMt_t st = {0};
	const uint8_t mode = SMS_MT_LAT_LO;

	memset(name, 0, sizeof name);
	name[17] = (char)0xA1; name[18] = (char)0xB2; name[19] = (char)0xC3;   /* охоронні байти */

	/* 15 символів: клавіші 2 і 3 по черзі (кожна нова -- підтверджує попередню) */
	for (int i = 0; i < 15; i++)
	{
		char key = (i & 1) ? '3' : '2';
		CHECK(smsMtKey(&st, mode, key, false, name, &pos, 16) == 1, "символ %d вміщається", i + 1);
	}
	smsMtCommit(&st, &pos);
	CHECK(pos == 15 && strlen(name) == 15, "15 підтверджених, довжина %d", (int)strlen(name));

	/* 16-й символ -- у перегляді на межі: стоїть у [15], [16] лишається NUL */
	CHECK(smsMtKey(&st, mode, '2', false, name, &pos, 16) == 1, "16-й символ вміщається");
	CHECK(smsMtKey(&st, mode, '2', true, name, &pos, 16) == 1, "гортається на межі");
	CHECK(strlen(name) == 16 && name[16] == 0, "довжина 16, NUL у [16]");
	smsMtCommit(&st, &pos);

	/* 17-й і далі -- не вводяться, нічого не змінюється */
	for (int i = 0; i < 6; i++)
	{
		CHECK(smsMtKey(&st, mode, (i & 1) ? '3' : '4', false, name, &pos, 16) == 0, "понад 16 -- відмова (%d)", i);
	}
	CHECK(strlen(name) == 16 && pos == 16 && name[16] == 0, "довжина лишилась 16, pos=%d", pos);
	CHECK((uint8_t)name[17] == 0xA1 && (uint8_t)name[18] == 0xB2 && (uint8_t)name[19] == 0xC3, "охоронні байти [17..19] не зачеплено");

	/* стирання на межі: останній символ можна замінити */
	smsMtBackspace(&st, name, &pos);
	CHECK(strlen(name) == 15 && pos == 15, "після стирання 15");
	CHECK(smsMtKey(&st, mode, '5', false, name, &pos, 16) == 1, "після стирання знову вміщається");
	CHECK(name[16] == 0 && (uint8_t)name[17] == 0xA1, "[16] NUL, [17] цілий");
#if defined(LANGUAGE_BUILD_UKRAINIAN)
	/* те саме кирилицею: 16 літер «АБВГҐДЕЄЖЗИІЇЙКЛ» не вилазять за 16 */
	memset(name, 0, sizeof name); pos = 0; st.key = 0; st.idx = 0;
	name[17] = (char)0xA1; name[18] = (char)0xB2; name[19] = (char)0xC3;
	for (int i = 0; i < 20; i++)
	{
		smsMtKey(&st, SMS_MT_UA_UP, (i & 1) ? '3' : '2', false, name, &pos, 16);
	}
	smsMtCommit(&st, &pos);
	CHECK(strlen(name) == 16 && name[16] == 0 && (uint8_t)name[17] == 0xA1 && (uint8_t)name[19] == 0xC3, "кирилиця: 16 літер, межі цілі");
#endif
}

/* R23-fix F2: стирання в редакторі назви контакту -- та сама послідовність, що cdNameBackspace() (menuContactDetails.c): p = довжина
 * підтвердженого тексту (strlen, мінус символ перегляду), далі smsMtBackspace. Спершу гине символ, що гортається, потім останній підтверджений. */
static void contactBackspace(smsMt_t *st, char *name)
{
	int16_t p = (int16_t)strlen(name);

	if (st->key != 0) { p--; }
	smsMtBackspace(st, name, &p);
}

static int16_t contactConfirmed(const smsMt_t *st, const char *name)
{
	return (int16_t)(strlen(name) - ((st->key != 0) ? 1U : 0U));
}

static void testContactNameErase(void)
{
	char name[20]; smsMt_t st = {0};
	const uint8_t mode = SMS_MT_LAT_LO;
	int16_t pos;

	memset(name, 0, sizeof name);
	name[17] = (char)0xA1; name[18] = (char)0xB2; name[19] = (char)0xC3;

	/* "a" (клавіша 2) і "d" (клавіша 3) -- "d" ще гортається */
	pos = contactConfirmed(&st, name);
	CHECK(smsMtKey(&st, mode, '2', false, name, &pos, 16) == 1, "a");
	pos = contactConfirmed(&st, name);
	CHECK(smsMtKey(&st, mode, '3', false, name, &pos, 16) == 1, "d");
	CHECK(strcmp(name, "ad") == 0 && st.key == '3', "назва \"ad\", d гортається");

	contactBackspace(&st, name);
	CHECK(strcmp(name, "a") == 0 && st.key == 0, "перше стирання знімає символ, що гортається");
	contactBackspace(&st, name);
	CHECK(name[0] == 0, "друге стирання знімає останній підтверджений");
	contactBackspace(&st, name);
	contactBackspace(&st, name);
	CHECK(name[0] == 0 && st.key == 0, "стирання порожньої назви безпечне");

	/* після повного стирання набір знову з початку */
	pos = contactConfirmed(&st, name);
	CHECK(smsMtKey(&st, mode, '2', false, name, &pos, 16) == 1 && strcmp(name, "a") == 0, "набір після повного стирання");
	smsMtCommit(&st, &pos);

	/* на межі 16: стирання символу, що гортається, звільняє місце, охоронні байти цілі */
	memset(name, 0, 17); st.key = 0; st.idx = 0;
	for (int i = 0; i < 16; i++)
	{
		pos = contactConfirmed(&st, name);
		smsMtKey(&st, mode, (i & 1) ? '3' : '2', false, name, &pos, 16);
	}
	CHECK(strlen(name) == 16 && st.key != 0, "16 символів, останній гортається");
	contactBackspace(&st, name);
	CHECK(strlen(name) == 15 && st.key == 0 && name[16] == 0, "стерто символ, що гортається: 15");
	pos = contactConfirmed(&st, name);
	CHECK(smsMtKey(&st, mode, '5', false, name, &pos, 16) == 1 && strlen(name) == 16, "після стирання 16-й знову вміщається");
	CHECK((uint8_t)name[17] == 0xA1 && (uint8_t)name[18] == 0xB2 && (uint8_t)name[19] == 0xC3, "охоронні байти [17..19] цілі");
}

#if defined(LANGUAGE_BUILD_UKRAINIAN)
/* 33 великі + 33 малі українські літери, cp1251. */
static const unsigned char UA_UP[] = {
	0xC0,0xC1,0xC2,0xC3,0xA5,0xC4,0xC5,0xAA,0xC6,0xC7,0xC8,0xB2,0xAF,0xC9,0xCA,0xCB,0xCC,
	0xCD,0xCE,0xCF,0xD0,0xD1,0xD2,0xD3,0xD4,0xD5,0xD6,0xD7,0xD8,0xD9,0xDC,0xDE,0xDF };
static const unsigned char UA_LO[] = {
	0xE0,0xE1,0xE2,0xE3,0xB4,0xE4,0xE5,0xBA,0xE6,0xE7,0xE8,0xB3,0xBF,0xE9,0xEA,0xEB,0xEC,
	0xED,0xEE,0xEF,0xF0,0xF1,0xF2,0xF3,0xF4,0xF5,0xF6,0xF7,0xF8,0xF9,0xFC,0xFE,0xFF };

static void testUkrainian(void)
{
	/* Усі 66 літер: кожна велика -- у «АБВ», кожна мала -- у «абв», рівно один раз,
	 * і в тій самій позиції на тій самій клавіші (регістр не міняє розкладку). */
	int total = 0;
	for (int i = 0; i < 33; i++)
	{
		char ku, kl; int nu, nl;
		int fu = findKey(SMS_MT_UA_UP, (char)UA_UP[i], &ku, &nu);
		int fl = findKey(SMS_MT_UA_LO, (char)UA_LO[i], &kl, &nl);
		CHECK(fu && fl, "літера %d не знайдена", i);
		CHECK(ku == kl && nu == nl, "літера %d: регістри на різних місцях", i);
		CHECK(findKey(SMS_MT_UA_LO, (char)UA_UP[i], &kl, &nl) == 0, "велика %d у «абв»", i);
		CHECK(findKey(SMS_MT_UA_UP, (char)UA_LO[i], &ku, &nu) == 0, "мала %d у «АБВ»", i);
		total += fu + fl;
	}
	CHECK(total == 66, "літер %d з 66", total);
	/* Порядок за брифом: 2 АБВГҐ ... 9 ЬЮЯ'. */
	CHECK(strcmp(smsMtKeyMap(SMS_MT_UA_UP, '2'), "\xC0\xC1\xC2\xC3\xA5" "2") == 0, "2 АБВГҐ");
	CHECK(strcmp(smsMtKeyMap(SMS_MT_UA_UP, '3'), "\xC4\xC5\xAA\xC6\xC7" "3") == 0, "3 ДЕЄЖЗ");
	CHECK(strcmp(smsMtKeyMap(SMS_MT_UA_UP, '4'), "\xC8\xB2\xAF\xC9" "4") == 0, "4 ИІЇЙ");
	CHECK(strcmp(smsMtKeyMap(SMS_MT_UA_LO, '9'), "\xFC\xFE\xFF" "'9") == 0, "9 ьюя'");
	CHECK(strcmp(smsMtKeyMap(SMS_MT_UA_LO, '1'), ".,?!-1") == 0, "1 .,?!-1");
	/* ui8: «№» з «*» прибрано в усіх режимах (на клавіатурі його немає, у 6x8 гліф порожній). */
	for (int m = 0; m < SMS_MT_MODES; m++)
	{
		CHECK(strchr(smsMtKeyMap((uint8_t)m, '*'), 0xB9) == NULL, "режим %d: * без №", m);
	}

	/* «Привіт, Ґанок! Їжак є.» -- регістр перемикаємо, як оператор ('#' у UI -- тут
	 * просто інший режим для великих). */
	const unsigned char want[] = { 0xCF,0xF0,0xE8,0xE2,0xB3,0xF2,',',' ',0xA5,0xE0,0xED,0xEE,0xEA,'!',' ',
		0xAF,0xE6,0xE0,0xEA,' ',0xBA,'.',0 };
	char buf[64] = {0}; int16_t pos = 0; smsMt_t st = {0};
	const unsigned char *s = want;
	while (*s)
	{
		char one[2] = { (char)*s, 0 };
		uint8_t mode = SMS_MT_UA_LO;
		for (int i = 0; i < 33; i++) { if (UA_UP[i] == *s) { mode = SMS_MT_UA_UP; } }
		smsMtCommit(&st, &pos);   /* '#' у UI теж спершу підтверджує */
		CHECK(typeStr(mode, one, buf, &pos, &st, 60), "символ 0x%02X", *s);
		s++;
	}
	CHECK(memcmp(buf, want, sizeof want) == 0, "фраза набрана не так");
	CHECK(pos == (int16_t)(sizeof want - 1), "довжина %d", pos);
}
#endif

int main(void)
{
	testModes();
	testLatin();
	testNumAndStar();
	testBackspaceAndCap();
	testContactNameCap();
	testContactNameErase();
#if defined(LANGUAGE_BUILD_UKRAINIAN)
	testUkrainian();
	printf("(українська збірка)\n");
#endif
	if (s_fail) { printf("ПРОВАЛЕНО перевірок: %d\n", s_fail); return 1; }
	printf("ПРОЙДЕНО\n");
	return 0;
}
