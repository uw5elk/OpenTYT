/*
 * test_aprs_mode.c -- хостовий тест налаштувань «Режиму APRS» (R10, functions/aprs_mode_cfg.c).
 *
 * Що перевіряє (чистий C, без заліза):
 *  - збереження/читання нового custom-data блоку (72 Б): круговий обхід, зіпсований/чужий/коротший блок,
 *    поля з недопустимим значенням знімаються з оверрайдів;
 *  - підстановка типових значень з конфігу APRS кодплуга (і запасних, коли конфігу нема);
 *  - ефективні значення (типові + оверрайди), позиція з окремих широти/довготи;
 *  - складання структури бікона з відредагованими шляхами й символом (те, що піде в aprsSendPacket());
 *  - коментар cp1251 -> UTF-8 для ефіру (круговий обхід з aprsDecodeText(), межі, керівні символи);
 *  - частота/координати: розбір і форматування, межі; 24-бітна позиція кодплуга; таблиця інтервалів; символи.
 *
 * Кадр AFSK/AX.25 сам (aprsSendPacket()) -- стоковий код прошивки, тут його немає: перевіряється все, що ми
 * в нього подаємо. Кирилиця в тесті -- лише байтами cp1251 (файл у UTF-8).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "functions/aprs_mode_cfg.h"
#include "functions/aprs_rx_parse.h"
#include "functions/dmr_sms_text.h"

static int s_fail = 0;
static int s_checks = 0;
#define CHECK(c, ...) do { s_checks++; if (!(c)) { s_fail++; printf("ПРОВАЛ %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

/* кодплуг: ціла частина << 15 | частка (1E-4), знак -- біт 23 */
static void fixed24(uint8_t b[3], int neg, unsigned ip, unsigned dp)
{
	uint32_t v = ((uint32_t)ip << 15) | (dp & 0x7FFFU) | (neg ? 0x800000U : 0U);

	b[0] = (uint8_t)(v & 0xFF);
	b[1] = (uint8_t)((v >> 8) & 0xFF);
	b[2] = (uint8_t)((v >> 16) & 0xFF);
}

static void fillRaw(aprsModeRawCfg_t *r)
{
	memset(r, 0xFF, sizeof(*r));   /* як стерта пам'ять кодплуга */
	memset(r->name, 0, sizeof(r->name));
	memcpy(r->name, "CFG1", 4);
	r->senderSSID = 9;
	fixed24(r->latitude, 0, 50, 4501);
	fixed24(r->longitude, 0, 30, 5234);
	memset(r->paths, 0, sizeof(r->paths));
	memcpy(r->paths[0].name, "WIDE1", 5);
	r->paths[0].ssid = 1;
	memcpy(r->paths[1].name, "WIDE2", 5);
	r->paths[1].ssid = 2;
	r->iconTable = 1;
	r->iconIndex = '[' - '!';
	memset(r->comment, 0, sizeof(r->comment));
	memcpy(r->comment, "Test", 4);
	r->txFrequency = 14482500UL;
	r->reserved[0] = r->reserved[1] = 0;
	r->flags = (uint8_t)(APRSM_RAW_FLAG_USE_POSITION | (3U << 5));
	r->magicVer = 0;
}

static void testStruct(void)
{
	CHECK(sizeof(aprsModeRawCfg_t) == 64, "aprsModeRawCfg_t = %zu, має бути 64 (як CodeplugAPRSConfig_t)", sizeof(aprsModeRawCfg_t));
}

static void testBlock(void)
{
	aprsModeCfg_t c, d;
	uint8_t blk[APRSM_BLOCK_LEN], blk2[APRSM_BLOCK_LEN];

	aprsModeCfgInit(&c);
	CHECK(c.ov == 0 && c.interval == 0 && c.sql == 0, "Init: ov/interval/sql");
	aprsModeCfgToBytes(&c, blk);
	CHECK(aprsModeCfgFromBytes(&d, blk, sizeof(blk)), "порожній блок читається");
	CHECK(d.ov == 0 && d.interval == 0 && d.sql == 0, "порожній блок -- без оверрайдів");

	/* усі поля */
	aprsModeCfgInit(&c);
	c.ov = APRSM_OV_ALL;
	c.freq = 14482500UL;
	memcpy(c.call, "UW5ELK", 7);
	c.ssid = 7;
	memcpy(c.path[0], "WIDE1", 6); c.pathSsid[0] = 1;
	memcpy(c.path[1], "WIDE2", 6); c.pathSsid[1] = 2;
	c.iconTable = 1; c.iconIndex = 29;
	memset(c.comment, 0, sizeof(c.comment));
	memcpy(c.comment, "\xCF\xF0\xE8\xE2\xBF\xF2 APRS", 11);   /* «Привіт APRS» (cp1251) */
	c.latU = 50450100; c.lonU = -30523400;
	c.ambiguity = 3;
	c.interval = 4;
	c.sql = 12;
	aprsModeCfgToBytes(&c, blk);
	memset(&d, 0xAA, sizeof(d));
	CHECK(aprsModeCfgFromBytes(&d, blk, sizeof(blk)), "повний блок читається");
	CHECK(d.ov == APRSM_OV_ALL, "ov = %04X", d.ov);
	CHECK(d.freq == c.freq, "freq");
	CHECK(strcmp(d.call, "UW5ELK") == 0 && d.ssid == 7, "позивний/ssid");
	CHECK(strcmp(d.path[0], "WIDE1") == 0 && d.pathSsid[0] == 1, "шлях 1");
	CHECK(strcmp(d.path[1], "WIDE2") == 0 && d.pathSsid[1] == 2, "шлях 2");
	CHECK(d.iconTable == 1 && d.iconIndex == 29, "символ");
	CHECK(strcmp(d.comment, c.comment) == 0, "коментар");
	CHECK(d.latU == 50450100 && d.lonU == -30523400, "позиція");
	CHECK(d.ambiguity == 3 && d.interval == 4 && d.sql == 12, "неточність/інтервал/шумодав");
	aprsModeCfgToBytes(&d, blk2);
	CHECK(memcmp(blk, blk2, sizeof(blk)) == 0, "повторний запис дає ті самі байти");

	/* довжина блоку незмінна, байти 0..1 -- 'A','M' */
	CHECK(blk[0] == 'A' && blk[1] == 'M', "магія");

	/* зіпсований (контрольна сума), чужа магія, інша версія, коротший блок */
	{
		uint8_t bad[APRSM_BLOCK_LEN];

		memcpy(bad, blk, sizeof(bad));
		bad[20] ^= 0x01;
		memset(&d, 0xAA, sizeof(d));
		CHECK(aprsModeCfgFromBytes(&d, bad, sizeof(bad)) == false, "зіпсований байт -- відмова");
		CHECK(d.ov == 0 && d.interval == 0, "після відмови -- усе типове");

		memcpy(bad, blk, sizeof(bad));
		bad[0] = 'X';
		CHECK(aprsModeCfgFromBytes(&d, bad, sizeof(bad)) == false, "чужа магія");

		memcpy(bad, blk, sizeof(bad));
		bad[2] = 9;
		CHECK(aprsModeCfgFromBytes(&d, bad, sizeof(bad)) == false, "інша версія");

		CHECK(aprsModeCfgFromBytes(&d, blk, sizeof(blk) - 1) == false, "коротший блок");
		CHECK(aprsModeCfgFromBytes(&d, NULL, 0) == false, "порожній блок (немає в флеші)");
		memset(bad, 0, sizeof(bad));
		CHECK(aprsModeCfgFromBytes(&d, bad, sizeof(bad)) == false, "блок з нулів (нова установка)");
		memset(bad, 0xFF, sizeof(bad));
		CHECK(aprsModeCfgFromBytes(&d, bad, sizeof(bad)) == false, "блок з 0xFF (стертий)");
	}

	/* поле з недопустимим значенням знімається з оверрайдів, решта живе */
	aprsModeCfgInit(&c);
	c.ov = APRSM_OV_FREQ | APRSM_OV_CALL | APRSM_OV_SSID;
	c.freq = 5000000UL;                    /* 50 МГц -- поза діапазоном */
	memcpy(c.call, "uw5elk", 7);           /* малі літери -- недопустимо в збереженому */
	c.ssid = 7;
	aprsModeCfgToBytes(&c, blk);
	CHECK(aprsModeCfgFromBytes(&d, blk, sizeof(blk)), "блок з поганими полями читається");
	CHECK((d.ov & APRSM_OV_FREQ) == 0, "частота поза діапазоном знята");
	CHECK((d.ov & APRSM_OV_CALL) == 0, "позивний з малими літерами знятий");
	CHECK((d.ov & APRSM_OV_SSID) != 0 && d.ssid == 7, "ssid лишився");
	aprsModeCfgInit(&c);
	c.ov = APRSM_OV_SSID;
	c.ssid = 16;
	aprsModeCfgToBytes(&c, blk);
	CHECK(aprsModeCfgFromBytes(&d, blk, sizeof(blk)), "читається");
	CHECK((d.ov & APRSM_OV_SSID) == 0, "ssid 16 знято");
}

static void testDefaults(void)
{
	aprsModeRawCfg_t raw;
	aprsModeDefaults_t d;

	fillRaw(&raw);
	aprsModeDefaultsBuild(&d, &raw, true, "UW5ELK\0\0", true, 1000000, 2000000);
	CHECK(d.hasCfg, "конфіг є");
	CHECK(d.freq == 14482500UL, "freq з конфігу = %lu", (unsigned long)d.freq);
	CHECK(strcmp(d.call, "UW5ELK") == 0, "позивний з імені рації");
	CHECK(d.ssid == 9, "ssid з конфігу");
	CHECK(strcmp(d.path[0], "WIDE1") == 0 && d.pathSsid[0] == 1, "шлях 1 з конфігу");
	CHECK(strcmp(d.path[1], "WIDE2") == 0 && d.pathSsid[1] == 2, "шлях 2 з конфігу");
	CHECK(d.iconTable == 1 && d.iconIndex == ('[' - '!'), "символ з конфігу");
	CHECK(strcmp(d.comment, "Test") == 0, "коментар з конфігу: '%s'", d.comment);
	CHECK(d.ambiguity == 3, "неточність з прапорців");
	CHECK(d.hasPos && d.latU == 50450100 && d.lonU == 30523400, "позиція з конфігу (USE_POSITION): %d %d", (int)d.latU, (int)d.lonU);

	/* USE_POSITION не задано -- позиція з налаштувань рації */
	raw.flags = 0;
	aprsModeDefaultsBuild(&d, &raw, true, "UW5ELK", true, 1000000, -2000000);
	CHECK(d.hasPos && d.latU == 1000000 && d.lonU == -2000000, "позиція з налаштувань рації");
	aprsModeDefaultsBuild(&d, &raw, true, "UW5ELK", false, 0, 0);
	CHECK(d.hasPos == false, "позиції нема ніде");

	/* порожній другий шлях у конфігу -- його нема */
	fillRaw(&raw);
	memset(raw.paths[1].name, 0, 6);
	aprsModeDefaultsBuild(&d, &raw, true, "UW5ELK", true, 0, 0);
	CHECK(d.path[1][0] == 0, "порожній другий шлях лишається порожнім");
	/* порожній перший шлях -- без шляху */
	fillRaw(&raw);
	memset(raw.paths[0].name, 0, 6);
	aprsModeDefaultsBuild(&d, &raw, true, "UW5ELK", true, 0, 0);
	CHECK(d.path[0][0] == 0, "порожній перший шлях лишається порожнім");

	/* стерті поля кодплуга (0xFF) */
	memset(&raw, 0xFF, sizeof(raw));
	aprsModeDefaultsBuild(&d, &raw, true, "ab 12", false, 0, 0);
	CHECK(strcmp(d.call, "AB") == 0, "ім'я рації до пробілу, верхній регістр: '%s'", d.call);
	CHECK(d.ssid == 0, "ssid 0xFF -> 0");
	CHECK(d.iconIndex == ('>' - '!'), "стертий символ -> автомобіль");

	/* конфігу нема -- запасні значення */
	aprsModeDefaultsBuild(&d, NULL, false, "UW5ELK", true, 5000000, 6000000);
	CHECK(d.hasCfg == false && d.freq == 0, "конфігу нема");
	CHECK(strcmp(d.path[0], "WIDE1") == 0 && d.pathSsid[0] == 1 && strcmp(d.path[1], "WIDE2") == 0 && d.pathSsid[1] == 1,
			"запасні шляхи WIDE1-1, WIDE2-1");
	CHECK(d.iconTable == 0 && d.iconIndex == ('>' - '!'), "запасний символ");
	CHECK(d.hasPos && d.latU == 5000000, "позиція з налаштувань");
	aprsModeDefaultsBuild(&d, NULL, false, NULL, false, 0, 0);
	CHECK(d.call[0] == 0, "імені нема -- позивного нема");
}

static void testEffective(void)
{
	aprsModeRawCfg_t raw;
	aprsModeDefaults_t d;
	aprsModeCfg_t c;
	aprsModeEff_t e;

	fillRaw(&raw);
	aprsModeDefaultsBuild(&d, &raw, true, "UW5ELK", true, 0, 0);
	aprsModeCfgInit(&c);
	aprsModeEffective(&c, &d, &e);
	CHECK(e.freq == 14482500UL && e.ssid == 9 && strcmp(e.call, "UW5ELK") == 0, "без оверрайдів -- типове");
	CHECK(e.hasPos && e.latU == 50450100, "позиція типова");
	CHECK(e.interval == 0 && e.sql == 0, "інтервал/шумодав");

	c.ov = APRSM_OV_FREQ | APRSM_OV_CALL | APRSM_OV_PATH1 | APRSM_OV_ICON | APRSM_OV_COMMENT | APRSM_OV_AMB;
	c.freq = 14480000UL;
	memcpy(c.call, "R2ABC", 6);
	memcpy(c.path[0], "WIDE2", 6); c.pathSsid[0] = 2;
	c.iconTable = 0; c.iconIndex = 29;
	memset(c.comment, 0, sizeof(c.comment)); memcpy(c.comment, "Hi", 2);
	c.ambiguity = 1;
	c.interval = 3; c.sql = 5;
	aprsModeEffective(&c, &d, &e);
	CHECK(e.freq == 14480000UL, "частота з рації");
	CHECK(strcmp(e.call, "R2ABC") == 0 && e.ssid == 9, "позивний з рації, ssid типовий");
	CHECK(strcmp(e.path[0], "WIDE2") == 0 && e.pathSsid[0] == 2 && strcmp(e.path[1], "WIDE2") == 0 && e.pathSsid[1] == 2, "шлях 1 з рації, шлях 2 типовий");
	CHECK(e.iconTable == 0 && e.iconIndex == 29, "символ з рації");
	CHECK(strcmp(e.comment, "Hi") == 0 && e.ambiguity == 1, "коментар/неточність");
	CHECK(e.interval == 3 && e.sql == 5, "інтервал/шумодав");

	/* змінений конфіг у CPS підхоплюється для полів, яких не чіпали */
	raw.txFrequency = 14482500UL + 2500;
	aprsModeDefaultsBuild(&d, &raw, true, "UW5ELK", true, 0, 0);
	c.ov = 0;
	aprsModeEffective(&c, &d, &e);
	CHECK(e.freq == 14485000UL, "нова типова частота підхоплена");

	/* поганий типовий freq -- запасна 144.800 */
	raw.txFrequency = 1234;
	aprsModeDefaultsBuild(&d, &raw, true, "UW5ELK", true, 0, 0);
	aprsModeEffective(&c, &d, &e);
	CHECK(e.freq == APRSM_FREQ_DEFAULT, "типова частота поза діапазоном -> 144.800");
	raw.txFrequency = 0;
	aprsModeDefaultsBuild(&d, &raw, true, "UW5ELK", true, 0, 0);
	aprsModeEffective(&c, &d, &e);
	CHECK(e.freq == APRSM_FREQ_DEFAULT, "txFrequency 0 -> 144.800");

	/* позиція: лише широта з рації, типової нема -> позиції нема; обидві -> є */
	aprsModeDefaultsBuild(&d, NULL, false, "UW5ELK", false, 0, 0);
	aprsModeCfgInit(&c);
	c.ov = APRSM_OV_LAT;
	c.latU = 10000000;
	aprsModeEffective(&c, &d, &e);
	CHECK(e.hasPos == false, "лише широта -- позиції нема");
	c.ov |= APRSM_OV_LON;
	c.lonU = -20000000;
	aprsModeEffective(&c, &d, &e);
	CHECK(e.hasPos && e.latU == 10000000 && e.lonU == -20000000, "обидві -- позиція є");
	/* типова позиція є; перекрито лише довготу */
	aprsModeDefaultsBuild(&d, NULL, false, "UW5ELK", true, 7000000, 8000000);
	c.ov = APRSM_OV_LON;
	c.lonU = 9000000;
	aprsModeEffective(&c, &d, &e);
	CHECK(e.hasPos && e.latU == 7000000 && e.lonU == 9000000, "широта типова, довгота з рації");
}

static void testBeaconCfg(void)
{
	aprsModeEff_t e;
	aprsModeRawCfg_t out;

	memset(&e, 0, sizeof(e));
	memcpy(e.call, "UW5ELK", 7);
	e.ssid = 7;
	memcpy(e.path[0], "WIDE1", 6); e.pathSsid[0] = 1;
	memcpy(e.path[1], "WIDE2", 6); e.pathSsid[1] = 2;
	e.iconTable = 1; e.iconIndex = 29;
	e.ambiguity = 2;
	aprsModeToBeaconCfg(&e, &out);
	CHECK(out.senderSSID == 7, "ssid");
	CHECK(memcmp(out.paths[0].name, "WIDE1", 5) == 0 && out.paths[0].name[5] == 0 && out.paths[0].ssid == 1, "шлях 1");
	CHECK(memcmp(out.paths[1].name, "WIDE2", 5) == 0 && out.paths[1].ssid == 2, "шлях 2");
	CHECK(out.iconTable == 1 && out.iconIndex == 29, "символ");
	CHECK(out.txFrequency == 0, "QSY не потрібен");
	CHECK(((out.flags & APRSM_RAW_FLAG_AMB_MASK) >> 5) == 2, "неточність у прапорцях");
	CHECK((out.flags & APRSM_RAW_FLAG_USE_POSITION) == 0, "USE_POSITION не ставимо -- позиція йде окремо");

	/* перший шлях порожній, другий є -> другий стає першим */
	memset(e.path[0], 0, 7); e.pathSsid[0] = 0;
	aprsModeToBeaconCfg(&e, &out);
	CHECK(memcmp(out.paths[0].name, "WIDE2", 5) == 0 && out.paths[0].ssid == 2, "другий шлях став першим");
	CHECK(out.paths[1].name[0] == 0, "другого нема");

	/* другий порожній */
	memcpy(e.path[0], "WIDE1", 6); e.pathSsid[0] = 1;
	memset(e.path[1], 0, 7); e.pathSsid[1] = 0;
	aprsModeToBeaconCfg(&e, &out);
	CHECK(memcmp(out.paths[0].name, "WIDE1", 5) == 0 && out.paths[1].name[0] == 0, "один шлях");

	/* обидва порожні -> WIDE1-1 (повністю без шляху прошивка не вміє) */
	memset(e.path[0], 0, 7); e.pathSsid[0] = 0;
	aprsModeToBeaconCfg(&e, &out);
	CHECK(memcmp(out.paths[0].name, "WIDE1", 5) == 0 && out.paths[0].ssid == 1 && out.paths[1].name[0] == 0, "обидва порожні -> WIDE1-1");

	/* повне 6-символьне ім'я шляху поміщається без NUL */
	memcpy(e.path[0], "ABCDEF", 7); e.pathSsid[0] = 0;
	aprsModeToBeaconCfg(&e, &out);
	CHECK(memcmp(out.paths[0].name, "ABCDEF", 6) == 0, "6 символів шляху");
}

static void testUtf8(void)
{
	char out[80];
	uint8_t back[80];
	char dec[80];
	size_t n;

	/* «Привіт» у cp1251: П=CF р=F0 и=E8 в=E2 і=B3 т=F2 */
	n = aprsModeCommentToUtf8("\xCF\xF0\xE8\xE2\xB3\xF2", out, sizeof(out));
	CHECK(n == 12, "6 кириличних літер = 12 байт UTF-8, є %zu", n);
	CHECK(memcmp(out, "\xD0\x9F\xD1\x80\xD0\xB8\xD0\xB2\xD1\x96\xD1\x82", 12) == 0, "байти UTF-8 «Привіт»");
	/* круговий обхід через приймальний декодер R8 */
	memcpy(back, out, n);
	size_t m = aprsDecodeText(back, n, dec, sizeof(dec));
	CHECK(m == 6 && memcmp(dec, "\xCF\xF0\xE8\xE2\xB3\xF2", 6) == 0, "aprsDecodeText повертає cp1251 (%zu)", m);

	/* власна таблиця cp1251 -> Unicode збігається з dmrSmsCp1251ToUcs2() для всієї кирилиці й українських літер
	 * (у збірці без AES цієї функції нема -- aprs_mode_cfg.c має власну) */
	for (int c = 0xC0; c <= 0xFF; c++)
	{
		char src[2] = { (char)c, 0 };
		uint16_t u = dmrSmsCp1251ToUcs2((uint8_t)c);

		n = aprsModeCommentToUtf8(src, out, sizeof(out));
		CHECK(n == 2 && (uint8_t)out[0] == (0xC0 | (u >> 6)) && (uint8_t)out[1] == (0x80 | (u & 0x3F)), "літера 0x%02X -> U+%04X", c, u);
	}
	{
		static const uint8_t sp[] = { 0xA8, 0xB8, 0xA5, 0xB4, 0xAA, 0xBA, 0xB2, 0xB3, 0xAF, 0xBF };

		for (size_t k = 0; k < sizeof(sp); k++)
		{
			char src[2] = { (char)sp[k], 0 };
			uint16_t u = dmrSmsCp1251ToUcs2(sp[k]);

			n = aprsModeCommentToUtf8(src, out, sizeof(out));
			CHECK(n == 2 && (uint8_t)out[0] == (0xC0 | (u >> 6)) && (uint8_t)out[1] == (0x80 | (u & 0x3F)), "спец. літера 0x%02X -> U+%04X", sp[k], u);
		}
	}

	/* ASCII як є; керівні -> пробіл */
	n = aprsModeCommentToUtf8("Hi\tthere", out, sizeof(out));
	CHECK(n == 8 && strcmp(out, "Hi there") == 0, "ASCII і керівний: '%s'", out);

	/* Ґ, Є, ї, № (0xB9 не має гліфа, але має кодову точку) */
	n = aprsModeCommentToUtf8("\xA5\xAA\xBF", out, sizeof(out));
	CHECK(n == 6 && memcmp(out, "\xD2\x90\xD0\x84\xD1\x97", 6) == 0, "Ґ Є ї: %zu", n);

	/* межа 43 байти: 22 літери по 2 байти = 44 -> лише 21 (42 байти), символ не рветься */
	{
		char src[40];
		memset(src, 0xE0, 22);   /* а */
		src[22] = 0;
		n = aprsModeCommentToUtf8(src, out, sizeof(out));
		CHECK(n == 42, "ліміт ефіру 43 -> 42 байти (21 літера), є %zu", n);
		CHECK(aprsIsUtf8((const uint8_t *)out, n), "результат -- коректний UTF-8");
	}
	/* малий буфер */
	n = aprsModeCommentToUtf8("\xE0\xE0\xE0\xE0", out, 6);
	CHECK(n == 4 && aprsIsUtf8((const uint8_t *)out, n) && out[4] == 0, "буфер 6 -> 2 літери (4 байти), NUL на місці: %zu", n);
	n = aprsModeCommentToUtf8("abc", out, 1);
	CHECK(n == 0 && out[0] == 0, "буфер 1 -> порожньо");
	n = aprsModeCommentToUtf8("", out, sizeof(out));
	CHECK(n == 0 && out[0] == 0, "порожній коментар");
}

static void testFreqCoord(void)
{
	uint32_t f = 0;
	int32_t u = 0;
	char b[24];

	CHECK(aprsModeParseFreq("144.825", &f) && f == 14482500UL, "144.825");
	CHECK(aprsModeParseFreq("144,8", &f) && f == 14480000UL, "144,8 (кома)");
	CHECK(aprsModeParseFreq("145", &f) && f == 14500000UL, "145");
	CHECK(aprsModeParseFreq("430.0075", &f) && f == 43000750UL, "430.0075");
	CHECK(aprsModeParseFreq("144.80125", &f) && f == 14480125UL, "крок 10 Гц");
	CHECK(aprsModeParseFreq("", &f) == false, "порожньо");
	CHECK(aprsModeParseFreq("abc", &f) == false, "не число");
	CHECK(aprsModeParseFreq("99", &f) == false, "99 МГц поза діапазоном");
	CHECK(aprsModeParseFreq("1000", &f) == false, "1000 МГц");
	CHECK(aprsModeParseFreq("144.8251234", &f) == false, "забагато знаків");
	CHECK(aprsModeParseFreq("144.8.2", &f) == false, "дві крапки");
	CHECK(aprsModeParseFreq("-144.8", &f) == false, "мінус");
	CHECK(aprsModeParseFreq("175", &f) == false, "175 МГц поза діапазоном");
	CHECK(aprsModeParseFreq("136", &f) && f == 13600000UL, "136 МГц ок");
	CHECK(aprsModeFreqValid(13500000UL) && aprsModeFreqValid(17400000UL) && aprsModeFreqValid(40000000UL) && aprsModeFreqValid(48000000UL), "межі діапазонів включно");
	CHECK(!aprsModeFreqValid(13499999UL) && !aprsModeFreqValid(17400001UL) && !aprsModeFreqValid(39999999UL) && !aprsModeFreqValid(48000001UL), "поза межами");

	aprsModeFormatFreq(b, sizeof(b), 14482500UL);
	CHECK(strcmp(b, "144.825") == 0, "формат 144.825: '%s'", b);
	aprsModeFormatFreq(b, sizeof(b), 14480000UL);
	CHECK(strcmp(b, "144.800") == 0, "формат 144.800: '%s'", b);
	aprsModeFormatFreq(b, sizeof(b), 43000750UL);
	CHECK(strcmp(b, "430.0075") == 0, "формат 430.0075: '%s'", b);
	aprsModeFormatFreq(b, sizeof(b), 14480125UL);
	CHECK(strcmp(b, "144.80125") == 0, "формат 144.80125: '%s'", b);

	CHECK(aprsModeParseCoord("50.4501", true, &u) && u == 50450100, "широта 50.4501");
	CHECK(aprsModeParseCoord("-50.4501", true, &u) && u == -50450100, "широта -50.4501");
	CHECK(aprsModeParseCoord("90", true, &u) && u == 90000000, "широта 90");
	CHECK(aprsModeParseCoord("90.000001", true, &u) == false, "широта >90");
	CHECK(aprsModeParseCoord("91", true, &u) == false, "широта 91");
	CHECK(aprsModeParseCoord("180", false, &u) && u == 180000000, "довгота 180");
	CHECK(aprsModeParseCoord("-180", false, &u) && u == -180000000, "довгота -180");
	CHECK(aprsModeParseCoord("180.5", false, &u) == false, "довгота >180");
	CHECK(aprsModeParseCoord("30,5234", false, &u) && u == 30523400, "довгота з комою");
	CHECK(aprsModeParseCoord("30.1234567", false, &u) == false, "7 знаків після крапки");
	CHECK(aprsModeParseCoord("", true, &u) == false, "порожньо");
	CHECK(aprsModeParseCoord("-", true, &u) == false, "лише мінус");
	CHECK(aprsModeParseCoord("5-0", true, &u) == false, "мінус посередині");
	CHECK(aprsModeParseCoord("1000", false, &u) == false, "4 цифри цілої частини");

	aprsModeFormatCoord(b, sizeof(b), 50450100);
	CHECK(strcmp(b, "50.4501") == 0, "формат 50.4501: '%s'", b);
	aprsModeFormatCoord(b, sizeof(b), -30523456);
	CHECK(strcmp(b, "-30.523456") == 0, "формат -30.523456: '%s'", b);
	aprsModeFormatCoord(b, sizeof(b), 0);
	CHECK(strcmp(b, "0.0000") == 0, "формат 0: '%s'", b);
	aprsModeFormatCoord(b, sizeof(b), -90000000);
	CHECK(strcmp(b, "-90.0000") == 0, "формат -90: '%s'", b);
	/* круговий обхід */
	for (int32_t v = -179999999; v < 180000000; v += 7777777)
	{
		int32_t back = 0;

		aprsModeFormatCoord(b, sizeof(b), v);
		CHECK(aprsModeParseCoord(b, false, &back) && back == v, "круговий обхід координати %d -> '%s' -> %d", (int)v, b, (int)back);
	}
}

static void testFixed24(void)
{
	uint8_t b[3];

	fixed24(b, 0, 50, 4501);
	CHECK(aprsModeFixed24ToMicro(b) == 50450100, "50.4501 -> %d", (int)aprsModeFixed24ToMicro(b));
	fixed24(b, 1, 50, 4501);
	CHECK(aprsModeFixed24ToMicro(b) == -50450100, "-50.4501");
	fixed24(b, 0, 0, 0);
	CHECK(aprsModeFixed24ToMicro(b) == 0, "0");
	fixed24(b, 0, 179, 9999);
	CHECK(aprsModeFixed24ToMicro(b) == 179999900, "179.9999");
	fixed24(b, 1, 30, 5234);
	CHECK(aprsModeFixed24ToMicro(b) == -30523400, "-30.5234");
}

static void testMisc(void)
{
	char b[8];
	static const uint8_t mins[APRSM_INTERVALS] = { 0, 5, 10, 15, 30, 60 };
	uint8_t t, i;

	for (int k = 0; k < APRSM_INTERVALS; k++)
	{
		CHECK(aprsModeIntervalMinutes((uint8_t)k) == mins[k], "інтервал %d хв", k);
		CHECK(aprsModeIntervalMs((uint8_t)k) == (uint32_t)mins[k] * 60000UL, "інтервал %d мс", k);
	}
	CHECK(aprsModeIntervalMs(200) == 0, "поганий індекс -- вимкнено");

	CHECK(aprsModeCallValid("UW5ELK") && aprsModeCallValid("A") && aprsModeCallValid("R2ABC"), "позивні");
	CHECK(!aprsModeCallValid("") && !aprsModeCallValid("TOOLONG") && !aprsModeCallValid("uw5elk") && !aprsModeCallValid("UW-5") && !aprsModeCallValid(NULL), "не позивні");
	CHECK(aprsModePathValid("") && aprsModePathValid("WIDE1") && !aprsModePathValid("WIDE1-1") && !aprsModePathValid(NULL), "шляхи");
	CHECK(aprsModeNormCall(b, sizeof(b), "uw5-elk x") == 6 && strcmp(b, "UW5ELK") == 0, "норма: '%s'", b);
	CHECK(aprsModeNormCall(b, sizeof(b), "abcdefghij") == 6 && strcmp(b, "ABCDEF") == 0, "обрізання до 6");
	CHECK(aprsModeNormCall(b, 4, "abcdef") == 3 && strcmp(b, "ABC") == 0, "малий буфер");

	/* символи: назви лише для первинної таблиці */
	CHECK(aprsModeSymbolName(0, '>' - '!') != NULL, "авто має назву");
	CHECK(aprsModeSymbolName(1, '>' - '!') != NULL, "R14: у додатковій таблиці назви є (вікно маяка)");
	CHECK(aprsModeSymbolName(0, 1) == NULL, "'\"' (зарезервовано) без назви");
	t = 0; i = '>' - '!';
	int names = 0;
	uint8_t startI = i;
	do
	{
		aprsModeSymbolNextNamed(&t, &i);
		CHECK(t == 0 && aprsModeSymbolName(0, i) != NULL, "наступний названий має назву");
		names++;
	} while ((i != startI) && (names < 50));
	CHECK(names == 10, "10 названих символів по колу, є %d", names);
	t = 1; i = 5;
	aprsModeSymbolNextNamed(&t, &i);
	CHECK(t == 0 && aprsModeSymbolName(0, i) != NULL, "з не названого -- до першого названого");
}

int main(void)
{
	testStruct();
	testBlock();
	testDefaults();
	testEffective();
	testBeaconCfg();
	testUtf8();
	testFreqCoord();
	testFixed24();
	testMisc();
	if (s_fail != 0)
	{
		printf("test_aprs_mode: ПРОВАЛІВ %d з %d перевірок\n", s_fail, s_checks);
		return 1;
	}
	printf("test_aprs_mode: усі %d перевірок пройшли\n", s_checks);
	return 0;
}
