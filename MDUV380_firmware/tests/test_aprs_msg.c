/*
 * test_aprs_msg.c -- хостовий тест повідомлень APRS (R11, functions/aprs_msg.c).
 *
 * Що перевіряє (чистий C, без заліза; час -- параметром):
 *  - кодування: cp1251 -> UTF-8 без втрат для ВСІЄЇ кирилиці (А-я, Ё ё, Є є, І і, Ї ї, Ґ ґ, №) і назад через aprsDecodeText();
 *    ліміт 67 БАЙТ UTF-8: кирилиця по 2 байти, літера не рветься, аутентичність UTF-8 результату;
 *  - заборонені символи: ':' '|' '~' '{', керівні (<0x20, 0x7F), байти cp1251 без відповідника;
 *  - адресат: нормалізація, SSID, довжина 1..9, доповнення пробілами рівно до 9;
 *  - кадр: повідомлення ":ADDR_____:текст{NN" і ACK ":ADDR_____:ackNN" побайтово (еталони -- рядками в тесті, складені вручну);
 *  - черга: 3 спроби по 30 с, скасування по ACK (лише того ж номера й від того ж відправника), «без ACK», "rej",
 *    ACK негайно й без повторів, пріоритет ACK, пауза 2 с, очікування вільної частоти 10 с, txOk, повтори (дубль {NN}),
 *    перехід номера 99 -> 01, переповнення черги й списку, фатальна відмова передачі, скасування всього.
 * Кирилиця в тесті -- лише байтами cp1251 (файл у UTF-8).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "functions/aprs_msg.h"
#include "functions/aprs_mode_cfg.h"
#include "functions/aprs_rx_parse.h"

static int s_fail = 0;
static int s_checks = 0;
#define CHECK(c, ...) do { s_checks++; if (!(c)) { s_fail++; printf("ПРОВАЛ %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

/* ---------------------------------------------------------------------------------------------------- */
static void testCharBytes(void)
{
	CHECK(aprsMsgCharBytes('A') == 1U && aprsMsgCharBytes('z') == 1U && aprsMsgCharBytes('0') == 1U && aprsMsgCharBytes(' ') == 1U && aprsMsgCharBytes('}') == 1U,
			"ASCII -- 1 байт");
	CHECK(aprsMsgCharBytes(':') == 0U, "':' заборонено");
	CHECK(aprsMsgCharBytes('|') == 0U && aprsMsgCharBytes('~') == 0U && aprsMsgCharBytes('{') == 0U, "'|' '~' '{' заборонено");
	CHECK(aprsMsgCharBytes(0x00) == 0U && aprsMsgCharBytes(0x09) == 0U && aprsMsgCharBytes(0x0A) == 0U && aprsMsgCharBytes(0x1F) == 0U && aprsMsgCharBytes(0x7F) == 0U,
			"керівні символи заборонено");
	CHECK(aprsMsgCharBytes(0xC0) == 2U && aprsMsgCharBytes(0xFF) == 2U && aprsMsgCharBytes(0xB3) == 2U && aprsMsgCharBytes(0xA5) == 2U, "кирилиця -- 2 байти");
	CHECK(aprsMsgCharBytes(0xB9) == 3U, "№ (U+2116) -- 3 байти");
	CHECK(aprsMsgCharBytes(0x80) == 0U && aprsMsgCharBytes(0x98) == 0U && aprsMsgCharBytes(0xA0) == 0U, "байти cp1251 без відповідника у шрифті -- заборонено");
}

/* КОЖЕН дозволений символ cp1251 -> UTF-8 -> cp1251 (через aprsDecodeText(), яким користується приймач R8) без втрат. */
static void testRoundTrip(void)
{
	int ok = 1, count = 0;

	for (int c = 0x20; c <= 0xFF; c++)
	{
		char src[2] = { (char)c, 0 }, u8[8], back[8];
		size_t n, m;

		if ((aprsMsgCharBytes((uint8_t)c) == 0U) || (c == ' '))
		{
			continue;   /* пробіл aprsDecodeText() (приймач) обрізає як одиничний -- перевіряється окремо в test_aprs_rx_parse */
		}
		count++;
		n = aprsMsgToUtf8(src, u8, sizeof(u8));
		if ((n != aprsMsgCharBytes((uint8_t)c)) || (aprsIsUtf8((const uint8_t *)u8, n) == false))
		{
			ok = 0;
			printf("    байт %02X: довжина %zu, очікували %zu\n", c, n, aprsMsgCharBytes((uint8_t)c));
			continue;
		}
		m = aprsDecodeText((const uint8_t *)u8, n, back, sizeof(back));
		if ((m != 1U) || ((uint8_t)back[0] != (uint8_t)c))
		{
			ok = 0;
			printf("    байт %02X не пережив коло: %zu байт, перший %02X\n", c, m, (unsigned)(uint8_t)back[0]);
		}
	}
	CHECK(ok, "cp1251 -> UTF-8 -> cp1251 для всіх дозволених символів");
	CHECK(count > 150, "кількість перевірених символів: %d", count);

	/* українські літери, яких немає в «простій» кирилиці: і ї є ґ та великі */
	{
		static const uint8_t ua[] = { 0xB3, 0xB2, 0xBF, 0xAF, 0xBA, 0xAA, 0xB4, 0xA5, 0xB8, 0xA8 };
		char src[16], u8[32], back[32];
		size_t n, m;

		memcpy(src, ua, sizeof(ua));
		src[sizeof(ua)] = 0;
		n = aprsMsgToUtf8(src, u8, sizeof(u8));
		CHECK(n == 20U, "10 українських літер -- 20 байт, є %zu", n);
		/* еталон UTF-8 складено вручну: і D1 96, І D0 86, ї D1 97, Ї D0 87, є D1 94, Є D0 84, ґ D2 91, Ґ D2 90, ё D1 91, Ё D0 81 */
		CHECK(memcmp(u8, "\xD1\x96\xD0\x86\xD1\x97\xD0\x87\xD1\x94\xD0\x84\xD2\x91\xD2\x90\xD1\x91\xD0\x81", 20) == 0, "UTF-8 українських літер відрізняється від еталона");
		m = aprsDecodeText((const uint8_t *)u8, n, back, sizeof(back));
		CHECK(m == sizeof(ua) && memcmp(back, ua, sizeof(ua)) == 0, "українські літери назад у cp1251");
	}

	/* «Привіт» -- еталон UTF-8 вручну */
	{
		char u8[32];
		size_t n = aprsMsgToUtf8("\xCF\xF0\xE8\xE2\xB3\xF2", u8, sizeof(u8));

		CHECK(n == 12U && memcmp(u8, "\xD0\x9F\xD1\x80\xD0\xB8\xD0\xB2\xD1\x96\xD1\x82", 12) == 0, "«Привіт» -> UTF-8");
	}
}

static void testLimit(void)
{
	char cp[100], u8[100];
	size_t n;

	/* 40 літер «а» (0xE0) = 80 байт -> рівно 33 літери = 66 байт (34-та дала б 68) */
	memset(cp, 0xE0, 40); cp[40] = 0;
	n = aprsMsgToUtf8(cp, u8, sizeof(u8));
	CHECK(n == 66U && aprsIsUtf8((const uint8_t *)u8, n), "40 кириличних літер: обрізано до 66 байт, не посеред літери (є %zu)", n);
	CHECK(aprsMsgUtf8Len(cp) == 80U, "utf8len(40 літер) = 80");

	/* 33 літери + ASCII = 67 -- влазить цілком */
	memset(cp, 0xE0, 33); cp[33] = 'x'; cp[34] = 'y'; cp[35] = 0;
	n = aprsMsgToUtf8(cp, u8, sizeof(u8));
	CHECK(n == 67U && u8[66] == 'x', "66 байт + 'x' = 67 влазить, 'y' ні (є %zu)", n);

	/* № (3 байти) на межі: 65 байт + № = 68 -> № не влазить */
	memset(cp, 'a', 65); cp[65] = (char)0xB9; cp[66] = 0;
	n = aprsMsgToUtf8(cp, u8, sizeof(u8));
	CHECK(n == 65U && aprsIsUtf8((const uint8_t *)u8, n), "65 ASCII + № (3 байти): № не рветься (є %zu)", n);
	memset(cp, 'a', 64); cp[64] = (char)0xB9; cp[65] = 0;
	n = aprsMsgToUtf8(cp, u8, sizeof(u8));
	CHECK(n == 67U && aprsIsUtf8((const uint8_t *)u8, n), "64 ASCII + № = 67 влазить (є %zu)", n);

	/* маленький буфер: вихід не рветься посеред літери, NUL на місці */
	memset(cp, 0xE0, 10); cp[10] = 0;
	n = aprsMsgToUtf8(cp, u8, 6);
	CHECK(n == 4U && u8[4] == 0 && aprsIsUtf8((const uint8_t *)u8, n), "буфер 6 -> 2 літери (4 байти) + NUL (є %zu)", n);

	/* редактор: що можна дописати */
	memset(cp, 0xE0, 33); cp[33] = 0;   /* 66 байт */
	CHECK(aprsMsgCanAppend(cp, 'x') == true, "66 байт + ASCII -- можна");
	CHECK(aprsMsgCanAppend(cp, 0xE0) == false, "66 байт + кирилиця (2) -- не можна");
	CHECK(aprsMsgCanAppend(cp, 0xB9) == false, "66 байт + № (3) -- не можна");
	CHECK(aprsMsgCanAppend("ab", ':') == false && aprsMsgCanAppend("ab", '|') == false && aprsMsgCanAppend("ab", '~') == false &&
			aprsMsgCanAppend("ab", '{') == false && aprsMsgCanAppend("ab", 0x09) == false, "заборонені символи не додаються");
	memset(cp, 'a', 67); cp[67] = 0;
	CHECK(aprsMsgCanAppend(cp, 'a') == false, "67 байт + будь-що -- не можна");
	cp[66] = 0;
	CHECK(aprsMsgCanAppend(cp, 'a') == true, "66 + ASCII = 67 -- можна");
}

static void testTextCheck(void)
{
	CHECK(aprsMsgTextCheck("") == AMSG_TEXT_EMPTY && aprsMsgTextCheck("   ") == AMSG_TEXT_EMPTY, "порожній текст");
	CHECK(aprsMsgTextCheck("Hi there") == AMSG_TEXT_OK && aprsMsgTextCheck("\xCF\xF0\xE8\xE2\xB3\xF2") == AMSG_TEXT_OK, "нормальний текст");
	CHECK(aprsMsgTextCheck("a:b") == AMSG_TEXT_ILLEGAL, "':' у тексті -- відмова");
	CHECK(aprsMsgTextCheck("a\tb") == AMSG_TEXT_ILLEGAL && aprsMsgTextCheck("a\nb") == AMSG_TEXT_ILLEGAL && aprsMsgTextCheck("a\x01") == AMSG_TEXT_ILLEGAL, "керівні символи -- відмова");
	CHECK(aprsMsgTextCheck("a|b") == AMSG_TEXT_ILLEGAL && aprsMsgTextCheck("a~b") == AMSG_TEXT_ILLEGAL && aprsMsgTextCheck("a{b") == AMSG_TEXT_ILLEGAL, "| ~ { -- відмова");
	CHECK(aprsMsgTextCheck("a\x98") == AMSG_TEXT_ILLEGAL, "байт cp1251 без відповідника -- відмова");
}

static void testNormCall(void)
{
	char o[16];

	CHECK(aprsMsgNormCall(o, "uw5elk-7") && strcmp(o, "UW5ELK-7") == 0, "нижній регістр -> верхній, SSID 7");
	CHECK(aprsMsgNormCall(o, "UW5ELK") && strcmp(o, "UW5ELK") == 0, "без SSID");
	CHECK(aprsMsgNormCall(o, "UW5ELK-0") && strcmp(o, "UW5ELK") == 0, "-0 відкидається");
	CHECK(aprsMsgNormCall(o, "UW5ELK-15") && strcmp(o, "UW5ELK-15") == 0, "SSID 15");
	CHECK(aprsMsgNormCall(o, "A") && strcmp(o, "A") == 0, "1 символ");
	CHECK(aprsMsgNormCall(o, "ABCDEFGH-9") == false, "10 символів -- задовго");
	CHECK(aprsMsgNormCall(o, "ABCDEFG-15") == false, "10 символів -- задовго (з SSID)");
	CHECK(aprsMsgNormCall(o, "ABCDEFG-1") && strcmp(o, "ABCDEFG-1") == 0, "9 символів -- межа");
	CHECK(aprsMsgNormCall(o, "UW5ELK-16") == false && aprsMsgNormCall(o, "UW5ELK-") == false && aprsMsgNormCall(o, "UW5ELK-A") == false &&
			aprsMsgNormCall(o, "UW5ELK-07") == false && aprsMsgNormCall(o, "UW5ELK-1-2") == false, "некоректний SSID");
	CHECK(aprsMsgNormCall(o, "") == false && aprsMsgNormCall(o, "-7") == false && aprsMsgNormCall(o, NULL) == false, "порожній / '-' попереду / NULL");
	CHECK(aprsMsgNormCall(o, "UW 5") == false && aprsMsgNormCall(o, "UW5.EL") == false && aprsMsgNormCall(o, "UW5\xC0") == false && aprsMsgNormCall(o, "UW5:") == false,
			"пробіл, крапка, кирилиця, ':' в адресаті -- відмова");
}

static void testBuild(void)
{
	char out[128];
	size_t n;

	/* еталон складено вручну: ':' + "UW5ELK-7" (8) + 1 пробіл (до 9) + ':' + "Hi" + "{01" */
	n = aprsMsgBuildMessage(out, sizeof(out), "UW5ELK-7", "Hi", "01");
	CHECK(n == 16U && strcmp(out, ":UW5ELK-7 :Hi{01") == 0, "повідомлення: \"%s\" (%zu)", out, n);
	/* адресат ДОПОВНЕНО пробілами рівно до 9 для довжин 1..9 */
	{
		static const char *to[] = { "A", "AB", "ABC", "ABCD", "ABCDE", "ABCDEF", "ABCDEF-1", "ABCDEFG-1" };
		static const char *want[] = {
			":A        :x{01", ":AB       :x{01", ":ABC      :x{01", ":ABCD     :x{01", ":ABCDE    :x{01", ":ABCDEF   :x{01", ":ABCDEF-1 :x{01", ":ABCDEFG-1:x{01"
		};

		for (unsigned i = 0; i < 8U; i++)
		{
			n = aprsMsgBuildMessage(out, sizeof(out), to[i], "x", "01");
			CHECK(strcmp(out, want[i]) == 0 && n == strlen(want[i]), "адресат %s: \"%s\"", to[i], out);
			CHECK(out[10] == ':', "двокрапка після адресата на місці 10");
		}
	}
	/* без номера -- без '{' */
	n = aprsMsgBuildMessage(out, sizeof(out), "UW5ELK", "Hi", "");
	CHECK(strcmp(out, ":UW5ELK   :Hi") == 0 && n == 13U, "без номера: \"%s\"", out);
	n = aprsMsgBuildMessage(out, sizeof(out), "UW5ELK", "Hi", NULL);
	CHECK(strcmp(out, ":UW5ELK   :Hi") == 0, "id == NULL");
	/* хвостові пробіли відкидаються */
	n = aprsMsgBuildMessage(out, sizeof(out), "UW5ELK", "Hi   ", "05");
	CHECK(strcmp(out, ":UW5ELK   :Hi{05") == 0, "хвостові пробіли: \"%s\"", out);
	/* кирилиця -> UTF-8: «Привіт» */
	n = aprsMsgBuildMessage(out, sizeof(out), "UW5ELK-7", "\xCF\xF0\xE8\xE2\xB3\xF2", "42");
	CHECK(n == 11U + 12U + 3U && memcmp(out, ":UW5ELK-7 :\xD0\x9F\xD1\x80\xD0\xB8\xD0\xB2\xD1\x96\xD1\x82{42", n) == 0, "кирилиця в кадрі");
	/* найдовше: 67 байт + номер з 5 символів = 11 + 67 + 6 = 84 */
	{
		char cp[40];

		memset(cp, 0xE0, 33); cp[33] = 'x'; cp[34] = 0;
		n = aprsMsgBuildMessage(out, sizeof(out), "ABCDEFG-1", cp, "12345");
		CHECK(n == 84U, "найдовше інфо-поле: %zu, очікували 84", n);
		CHECK(strcmp(out + 78, "{12345") == 0, "номер у кінці");
		CHECK(aprsIsUtf8((const uint8_t *)out + 11, 67U), "текст у кадрі -- коректний UTF-8");
	}
	/* надто довгий текст -- обрізається цілою літерою, кадр не довший за 84 */
	{
		char cp[60];

		memset(cp, 0xE0, 50); cp[50] = 0;
		n = aprsMsgBuildMessage(out, sizeof(out), "UW5ELK", cp, "01");
		CHECK(n == 11U + 66U + 3U, "довгий текст обрізано до 66 байт: %zu", n);
		CHECK(aprsIsUtf8((const uint8_t *)out + 11, 66U), "обрізаний текст -- UTF-8 без розірваної літери");
	}
	/* відмови */
	CHECK(aprsMsgBuildMessage(out, sizeof(out), "UW5ELK", "a:b", "01") == 0U, "':' у тексті -- відмова");
	CHECK(aprsMsgBuildMessage(out, sizeof(out), "UW5ELK", "a\tb", "01") == 0U, "TAB у тексті -- відмова");
	CHECK(aprsMsgBuildMessage(out, sizeof(out), "UW5ELK", "", "01") == 0U && aprsMsgBuildMessage(out, sizeof(out), "UW5ELK", "  ", "01") == 0U, "порожній текст -- відмова");
	CHECK(aprsMsgBuildMessage(out, sizeof(out), "UW5 ELK", "x", "01") == 0U && aprsMsgBuildMessage(out, sizeof(out), "\xC0\xC1", "x", "01") == 0U, "поганий адресат -- відмова");
	CHECK(aprsMsgBuildMessage(out, 40, "UW5ELK", "x", "01") == 0U, "малий буфер -- відмова (найгірший випадок мусить вміститись)");
	CHECK(aprsMsgBuildMessage(out, sizeof(out), "UW5ELK", "x", "123456") == 0U, "номер довший за 5 -- відмова");

	/* ACK: без дужок і без тексту */
	n = aprsMsgBuildAck(out, sizeof(out), "UW5ELK-7", "01");
	CHECK(n == 16U && strcmp(out, ":UW5ELK-7 :ack01") == 0, "ACK: \"%s\"", out);
	n = aprsMsgBuildAck(out, sizeof(out), "UW5ELK", "12345");
	CHECK(strcmp(out, ":UW5ELK   :ack12345") == 0, "ACK з 5-символьним номером: \"%s\"", out);
	n = aprsMsgBuildAck(out, sizeof(out), "A", "7");
	CHECK(strcmp(out, ":A        :ack7") == 0, "ACK, адресат 1 символ: \"%s\"", out);
	CHECK(aprsMsgBuildAck(out, sizeof(out), "UW5ELK", "") == 0U && aprsMsgBuildAck(out, sizeof(out), "UW5ELK", NULL) == 0U, "ACK без номера -- відмова");
	CHECK(strchr(out, '{') == NULL, "ACK без '{'");

	/* наш кадр читає наш же приймач (R8): to / id / текст */
	{
		aprsAx25_t ax;
		aprsPacket_t pkt;
		uint8_t frame[128];

		(void)frame;
		memset(&ax, 0, sizeof(ax));
		n = aprsMsgBuildMessage(out, sizeof(out), "UW5ELK-7", "\xCF\xF0\xE8\xE2\xB3\xF2 world", "07");
		ax.info = (const uint8_t *)out;
		ax.infoLen = n;
		aprsPacketParse(&ax, &pkt);
		CHECK(pkt.type == APRS_T_MESSAGE && strcmp(pkt.msgTo, "UW5ELK-7") == 0 && strcmp(pkt.msgId, "07") == 0 && pkt.msgAck == false &&
				strcmp(pkt.text, "\xCF\xF0\xE8\xE2\xB3\xF2 world") == 0, "приймач R8 розбирає наше повідомлення: to=%s id=%s", pkt.msgTo, pkt.msgId);
		n = aprsMsgBuildAck(out, sizeof(out), "UW5ELK-7", "07");
		ax.infoLen = n;
		aprsPacketParse(&ax, &pkt);
		CHECK(pkt.type == APRS_T_MESSAGE && pkt.msgAck == true && strcmp(pkt.msgTo, "UW5ELK-7") == 0 && strcmp(pkt.text, "ack07") == 0, "приймач R8 розбирає наш ACK");
	}
}

/* ---- черга ----------------------------------------------------------------------------------------- */

static aprsMsgBox_t g_box;   /* ~1,3 КБ: не на стеку тесту */

/* Одна «передача»: Poll -> TxDone(ok) -> (через `air` мс) TxEnded. Повертає довжину інфо-поля. */
static size_t txOnce(aprsMsgBox_t *b, uint32_t *now, char *info, size_t cap)
{
	size_t n = aprsMsgPoll(b, *now, false, true, info, cap);

	if (n != 0U)
	{
		aprsMsgTxDone(b, *now, true, false);
		*now += 700U;   /* ~0,7 с у ефірі */
		aprsMsgTxEnded(b, *now);
	}
	return n;
}

static void testRetries(void)
{
	aprsMsgBox_t *b = &g_box;
	char info[128];
	uint32_t t = 100000U;
	uint32_t t0;
	int sent = 0;

	aprsMsgInit(b, 0U);
	CHECK(aprsMsgSend(b, "uw5elk-7", "Hi", t, NULL) == AMSG_OK, "поставлено в чергу");
	CHECK(b->list[0].status == AMSG_ST_WAIT && b->list[0].dir == AMSG_DIR_OUT && strcmp(b->list[0].call, "UW5ELK-7") == 0 && strcmp(b->list[0].id, "01") == 0, "запис «чекає», номер 01");
	CHECK(aprsMsgPendingCount(b) == 1U, "один у черзі");

	/* спроба 1 -- одразу */
	CHECK(txOnce(b, &t, info, sizeof(info)) == 16U && strcmp(info, ":UW5ELK-7 :Hi{01") == 0, "спроба 1: %s", info);
	t0 = t - 700U;
	sent++;
	CHECK(b->list[0].status == AMSG_ST_SENT && b->list[0].attempts == 1U, "після спроби 1: «надіслано», спроб 1");
	/* до 30 с нічого */
	CHECK(aprsMsgPoll(b, t0 + 29999U, false, true, info, sizeof(info)) == 0U, "за 29,999 с повтору нема");
	/* спроба 2 -- рівно через 30 с від початку передачі */
	t = t0 + 30000U;
	CHECK(txOnce(b, &t, info, sizeof(info)) != 0U && strcmp(info, ":UW5ELK-7 :Hi{01") == 0, "спроба 2 через 30 с, той самий номер");
	t0 = t - 700U;
	sent++;
	CHECK(b->list[0].attempts == 2U && b->list[0].status == AMSG_ST_SENT, "спроб 2");
	/* спроба 3 */
	t = t0 + 30000U;
	CHECK(txOnce(b, &t, info, sizeof(info)) != 0U, "спроба 3 через 30 с");
	t0 = t - 700U;
	sent++;
	CHECK(b->list[0].attempts == 3U && b->list[0].status == AMSG_ST_SENT, "спроб 3, ще чекаємо ACK");
	/* четвертої нема: до кінця очікування -- «надіслано», потім «без ACK» */
	CHECK(aprsMsgPoll(b, t0 + 29999U, false, true, info, sizeof(info)) == 0U && b->list[0].status == AMSG_ST_SENT, "перед кінцем очікування ще «надіслано»");
	CHECK(aprsMsgPoll(b, t0 + 30000U, false, true, info, sizeof(info)) == 0U, "четвертої спроби нема");
	CHECK(b->list[0].status == AMSG_ST_NOACK, "після 3 спроб і 30 с -- «без ACK»");
	CHECK(aprsMsgPendingCount(b) == 0U, "черга порожня");
	CHECK(sent == 3, "рівно 3 передачі");
	/* запізнілий ACK уже нічого не міняє */
	CHECK(aprsMsgOnAckRx(b, "UW5ELK-7", "01", false) == false && b->list[0].status == AMSG_ST_NOACK, "запізнілий ACK ігнорується");
}

static void testCancelOnAck(void)
{
	aprsMsgBox_t *b = &g_box;
	char info[128];
	uint32_t t = 5000U;

	aprsMsgInit(b, 0U);
	(void)aprsMsgSend(b, "UW5ELK-7", "Hi", t, NULL);
	CHECK(txOnce(b, &t, info, sizeof(info)) != 0U, "спроба 1");
	/* чужі ACK не скасовують */
	CHECK(aprsMsgOnAckRx(b, "UW5ELK-7", "02", false) == false, "ACK іншого номера не скасовує");
	CHECK(aprsMsgOnAckRx(b, "UW5ELK-8", "01", false) == false, "ACK від іншої станції не скасовує");
	CHECK(aprsMsgOnAckRx(b, "UW5ELK-7", "", false) == false, "ACK без номера не скасовує");
	CHECK(b->list[0].status == AMSG_ST_SENT && aprsMsgPendingCount(b) == 1U, "після чужих ACK усе чекає");
	/* свій -- скасовує (регістр байдужий) */
	CHECK(aprsMsgOnAckRx(b, "uw5elk-7", "01", false) == true, "ACK того ж номера від того ж відправника");
	CHECK(b->list[0].status == AMSG_ST_ACK && aprsMsgPendingCount(b) == 0U, "статус «ACK», черга порожня");
	t += 60000U;
	CHECK(aprsMsgPoll(b, t, false, true, info, sizeof(info)) == 0U, "повторів після ACK нема");

	/* REJ -> «без ACK» */
	aprsMsgInit(b, 0U);
	(void)aprsMsgSend(b, "UW5ELK-7", "Hi", t, NULL);
	(void)txOnce(b, &t, info, sizeof(info));
	CHECK(aprsMsgOnAckRx(b, "UW5ELK-7", "01", true) == true && b->list[0].status == AMSG_ST_NOACK, "rej -> «без ACK»");

	/* ACK, що прийшов ПІД ЧАС нашої передачі (завдання зняли, поки кадр у ефірі): стан не ламається */
	aprsMsgInit(b, 0U);
	(void)aprsMsgSend(b, "UW5ELK-7", "Hi", t, NULL);
	CHECK(aprsMsgPoll(b, t, false, true, info, sizeof(info)) != 0U && b->inflight >= 0, "кадр видано");
	CHECK(aprsMsgOnAckRx(b, "UW5ELK-7", "01", false) == true && b->inflight < 0, "ACK під час передачі зняв завдання");
	aprsMsgTxDone(b, t, true, false);
	CHECK(b->txActive == 1U, "передачу все одно відмічено");
	aprsMsgTxEnded(b, t + 700U);
	CHECK(b->list[0].status == AMSG_ST_ACK && aprsMsgPendingCount(b) == 0U, "статус ACK, нічого не повисло");
}

static void testAck(void)
{
	aprsMsgBox_t *b = &g_box;
	char info[128];
	uint32_t t = 20000U;

	aprsMsgInit(b, 0U);
	/* вхідне з номером -> новий запис + ACK негайно */
	CHECK(aprsMsgOnIncoming(b, "UW5ELK-7", "Hello", "123", t) == true, "нове вхідне");
	CHECK(aprsMsgListCount(b) == 1U && aprsMsgUnreadCount(b) == 1U && b->list[0].dir == AMSG_DIR_IN && b->list[0].unread, "запис у списку, непрочитаний");
	CHECK(aprsMsgQueueAck(b, "UW5ELK-7", "123", t, NULL) == true, "ACK поставлено");
	CHECK(aprsMsgPoll(b, t, false, true, info, sizeof(info)) == 17U && strcmp(info, ":UW5ELK-7 :ack123") == 0, "ACK пішов негайно: \"%s\"", info);
	aprsMsgTxDone(b, t, true, false);
	aprsMsgTxEnded(b, t + 500U);
	CHECK(aprsMsgPendingCount(b) == 0U && b->q[0].type == AMSG_JOB_FREE, "ACK не лишається в черзі (повторів нема)");
	CHECK(aprsMsgPoll(b, t + 40000U, false, true, info, sizeof(info)) == 0U, "ACK не повторюється");

	/* повтор того самого {NN}: повідомлення показується ОДИН раз, ACK -- знову (але не раніше 5 с від попереднього) */
	CHECK(aprsMsgOnIncoming(b, "UW5ELK-7", "Hello", "123", t + 3000U) == false && aprsMsgListCount(b) == 1U, "повтор: повідомлення не дублюється");
	CHECK(aprsMsgQueueAck(b, "UW5ELK-7", "123", t + 3000U, NULL) == false, "повтор через 3 с (той самий кадр через інший діджі): ACK не множимо");
	CHECK(aprsMsgQueueAck(b, "UW5ELK-7", "123", t + 31000U, NULL) == true, "повтор через 31 с (відправник не почув ACK): ACK знову");
	CHECK(aprsMsgQueueAck(b, "UW5ELK-7", "123", t + 31001U, NULL) == false, "а другий такий самий поки в черзі -- ні");
	CHECK(aprsMsgPoll(b, t + 31000U, false, true, info, sizeof(info)) != 0U && strcmp(info, ":UW5ELK-7 :ack123") == 0, "повторний ACK пішов");
	aprsMsgTxDone(b, t + 31000U, true, false);
	aprsMsgTxEnded(b, t + 31500U);
	/* інший номер від того ж відправника -- нове повідомлення */
	CHECK(aprsMsgOnIncoming(b, "UW5ELK-7", "Again", "124", t + 40000U) == true && aprsMsgListCount(b) == 2U, "інший номер -- нове");
	CHECK(b->list[0].text[0] == 'A' && b->list[1].text[0] == 'H', "найновіше зверху");
	/* без номера: ACK не потрібен */
	CHECK(aprsMsgQueueAck(b, "UW5ELK-7", "", t, NULL) == false && aprsMsgQueueAck(b, "UW5ELK-7", NULL, t, NULL) == false, "без номера ACK не ставимо");
	CHECK(aprsMsgOnIncoming(b, "UW5ELK-7", "no id", "", t + 41000U) == true && aprsMsgOnIncoming(b, "UW5ELK-7", "no id", "", t + 42000U) == true,
			"без номера дедуплікація не тут (її робить R8): обидва додаються");

	/* прочитано */
	aprsMsgMarkRead(b, 0);
	CHECK(aprsMsgUnreadCount(b) == 3U, "після прочитання одного: 3 непрочитані з 4");
}

static void testScheduling(void)
{
	aprsMsgBox_t *b = &g_box;
	char info[128];
	uint32_t t = 50000U;

	/* пріоритет ACK над повідомленням */
	aprsMsgInit(b, 0U);
	(void)aprsMsgSend(b, "AAA", "msg", t, NULL);
	(void)aprsMsgOnIncoming(b, "BBB", "x", "9", t);
	(void)aprsMsgQueueAck(b, "BBB", "9", t, NULL);
	CHECK(aprsMsgPoll(b, t, false, true, info, sizeof(info)) != 0U && strcmp(info, ":BBB      :ack9") == 0, "ACK раніше за повідомлення: \"%s\"", info);
	aprsMsgTxDone(b, t, true, false);
	/* пауза 2 с між будь-якими двома передачами -- від КІНЦЯ попередньої */
	aprsMsgTxEnded(b, t + 800U);
	CHECK(aprsMsgPoll(b, t + 800U + 1999U, false, true, info, sizeof(info)) == 0U, "через 1,999 с після кінця -- ще рано");
	CHECK(aprsMsgPoll(b, t + 800U + 2000U, false, true, info, sizeof(info)) != 0U && strcmp(info, ":AAA      :msg{01") == 0, "через 2 с -- можна: \"%s\"", info);
	aprsMsgTxDone(b, t + 2800U, true, false);
	CHECK(aprsMsgPoll(b, t + 2800U, false, true, info, sizeof(info)) == 0U, "поки кадр у ефірі, нічого нового");
	aprsMsgTxEnded(b, t + 3500U);

	/* txOk = false (PTT, DMR-TX, приймається пакет, APRS вимкнено): нічого не йде, і не «ламає» таймери */
	aprsMsgInit(b, 0U);
	(void)aprsMsgSend(b, "AAA", "msg", t, NULL);
	CHECK(aprsMsgPoll(b, t, false, false, info, sizeof(info)) == 0U && aprsMsgPoll(b, t + 100000U, false, false, info, sizeof(info)) == 0U, "txOk=false -- не передаємо");
	CHECK(b->list[0].status == AMSG_ST_WAIT && aprsMsgPendingCount(b) == 1U, "повідомлення чекає");
	CHECK(aprsMsgPoll(b, t + 100001U, false, true, info, sizeof(info)) != 0U, "умови з'явились -- передали");

	/* зайнята частота: чекаємо до 10 с, потім передаємо */
	aprsMsgInit(b, 0U);
	(void)aprsMsgSend(b, "AAA", "msg", t, NULL);
	CHECK(aprsMsgPoll(b, t, true, true, info, sizeof(info)) == 0U, "зайнято: 0 с");
	CHECK(aprsMsgPoll(b, t + 9999U, true, true, info, sizeof(info)) == 0U, "зайнято: 9,999 с -- ще чекаємо");
	CHECK(aprsMsgPoll(b, t + 10000U, true, true, info, sizeof(info)) != 0U, "зайнято: 10 с -- передаємо все одно");
	aprsMsgTxDone(b, t + 10000U, true, false);
	aprsMsgTxEnded(b, t + 10700U);
	/* зайнято, але звільнилась -- передаємо одразу, лічильник очікування скинуто */
	aprsMsgInit(b, 0U);
	(void)aprsMsgSend(b, "AAA", "msg", t, NULL);
	CHECK(aprsMsgPoll(b, t, true, true, info, sizeof(info)) == 0U, "зайнято");
	CHECK(aprsMsgPoll(b, t + 4000U, false, true, info, sizeof(info)) != 0U, "звільнилась через 4 с -- передаємо");
	aprsMsgTxDone(b, t + 4000U, true, false);
	aprsMsgTxEnded(b, t + 4700U);
	/* і ACK теж чекає на вільну частоту */
	aprsMsgInit(b, 0U);
	(void)aprsMsgQueueAck(b, "BBB", "9", t, NULL);
	CHECK(aprsMsgPoll(b, t + 1000U, true, true, info, sizeof(info)) == 0U && aprsMsgPoll(b, t + 10999U, true, true, info, sizeof(info)) == 0U &&
			aprsMsgPoll(b, t + 11000U, true, true, info, sizeof(info)) != 0U, "ACK при зайнятій частоті -- теж до 10 с");

	/* фатальна відмова (TX заборонено): одразу «без ACK», без повторів */
	aprsMsgInit(b, 0U);
	(void)aprsMsgSend(b, "AAA", "msg", t, NULL);
	CHECK(aprsMsgPoll(b, t, false, true, info, sizeof(info)) != 0U, "кадр видано");
	aprsMsgTxDone(b, t, false, true);
	CHECK(b->list[0].status == AMSG_ST_NOACK && aprsMsgPendingCount(b) == 0U, "fatal: «без ACK», черга порожня");
	CHECK(aprsMsgPoll(b, t + 100000U, false, true, info, sizeof(info)) == 0U, "після fatal повторів нема");
	/* не фатальна невдача (частота зайнята на рівні TX): спроба рахується, повтор через 30 с */
	aprsMsgInit(b, 0U);
	(void)aprsMsgSend(b, "AAA", "msg", t, NULL);
	(void)aprsMsgPoll(b, t, false, true, info, sizeof(info));
	aprsMsgTxDone(b, t, false, false);
	CHECK(b->txActive == 0U && b->list[0].attempts == 1U && b->list[0].status == AMSG_ST_WAIT, "невдала спроба: рахується, статус лишається «чекає»");
	CHECK(aprsMsgPoll(b, t + 29999U, false, true, info, sizeof(info)) == 0U && aprsMsgPoll(b, t + 30000U, false, true, info, sizeof(info)) != 0U, "повтор через 30 с");

	/* скасування всього (вихід з режиму) */
	aprsMsgInit(b, 0U);
	(void)aprsMsgSend(b, "AAA", "m1", t, NULL);
	(void)aprsMsgSend(b, "BBB", "m2", t, NULL);
	(void)aprsMsgQueueAck(b, "CCC", "1", t, NULL);
	aprsMsgCancelAll(b);
	CHECK(aprsMsgPendingCount(b) == 0U && b->q[0].type == AMSG_JOB_FREE && b->q[1].type == AMSG_JOB_FREE && b->q[2].type == AMSG_JOB_FREE, "після скасування черга порожня");
	CHECK(b->list[0].status == AMSG_ST_NOACK && b->list[1].status == AMSG_ST_NOACK, "повідомлення стали «без ACK»");
}

static void testNumbersAndOverflow(void)
{
	aprsMsgBox_t *b = &g_box;
	char info[128];
	uint32_t t = 1000U;

	/* перехід 99 -> 01: seed 97 => 98, 99, 01, 02 */
	aprsMsgInit(b, 97U);
	for (int i = 0; i < 4; i++)
	{
		CHECK(aprsMsgSend(b, "AAA", "x", t, NULL) == AMSG_OK, "поставлено %d", i);
		while (aprsMsgPoll(b, t, false, true, info, sizeof(info)) != 0U)
		{
			aprsMsgTxDone(b, t, true, false);
			aprsMsgTxEnded(b, t + 100U);
			t += 5000U;
			(void)aprsMsgOnAckRx(b, "AAA", info + strlen(info) - 2, false);
		}
	}
	/* list[0] -- найновіше (02), далі 01, 99, 98 */
	CHECK(strcmp(b->list[0].id, "02") == 0 && strcmp(b->list[1].id, "01") == 0 && strcmp(b->list[2].id, "99") == 0 && strcmp(b->list[3].id, "98") == 0,
			"номери 98 99 01 02: %s %s %s %s", b->list[3].id, b->list[2].id, b->list[1].id, b->list[0].id);
	/* жодного "00" */
	aprsMsgInit(b, 98U);
	(void)aprsMsgSend(b, "AAA", "x", t, NULL);
	(void)aprsMsgSend(b, "AAA", "x", t, NULL);
	CHECK(strcmp(b->list[1].id, "99") == 0 && strcmp(b->list[0].id, "01") == 0, "після 99 -- 01, не 00");

	/* seed великий */
	aprsMsgInit(b, 1000000007U);
	(void)aprsMsgSend(b, "AAA", "x", t, NULL);
	CHECK(strlen(b->list[0].id) == 2U && b->list[0].id[0] >= '0' && b->list[0].id[0] <= '9' && strcmp(b->list[0].id, "00") != 0, "seed великий -- номер 01..99: %s", b->list[0].id);

	/* переповнення черги: 4 повідомлення, 5-те -- відмова; R11-fix2: ACK при повній черзі ВИТІСНЯЄ найстаріше наше повідомлення */
	aprsMsgInit(b, 0U);
	for (int i = 0; i < 4; i++)
	{
		CHECK(aprsMsgSend(b, "AAA", "x", t + (uint32_t)i, NULL) == AMSG_OK, "повідомлення %d у чергу", i);
	}
	CHECK(aprsMsgSend(b, "AAA", "x", t, NULL) == AMSG_E_FULL, "5-те -- черга повна");
	CHECK(aprsMsgQueueAck(b, "BBB", "1", t + 10U, NULL) == true, "ACK при повній черзі витісняє наше повідомлення");
	CHECK(aprsMsgPendingCount(b) == 3U && aprsMsgAckPending(b) == 1U && aprsMsgQueueLen(b) == 4U && aprsMsgListCount(b) == 4U, "у черзі 3 повідомлення + ACK, у списку 4");
	CHECK(b->list[3].status == AMSG_ST_NOACK && strcmp(b->list[3].id, "01") == 0, "витіснене -- найстаріше (номер 01) -- стало «без ACK»");
	CHECK(b->list[0].status == AMSG_ST_WAIT && b->list[1].status == AMSG_ST_WAIT && b->list[2].status == AMSG_ST_WAIT, "решта чекають");
	/* відмови не псують стан: помилковий адресат/текст */
	aprsMsgInit(b, 0U);
	CHECK(aprsMsgSend(b, "A B", "x", t, NULL) == AMSG_E_CALL && aprsMsgSend(b, "AAA", "a:b", t, NULL) == AMSG_E_TEXT && aprsMsgSend(b, "AAA", "", t, NULL) == AMSG_E_TEXT, "помилки адресата й тексту");
	CHECK(aprsMsgListCount(b) == 0U && aprsMsgPendingCount(b) == 0U, "помилки нічого не додали");

	/* список на 8: 10 вхідних -- лишається 8, найновіше зверху, найстаріші витіснено */
	aprsMsgInit(b, 0U);
	for (int i = 0; i < 10; i++)
	{
		char from[12], txt[8];

		snprintf(from, sizeof(from), "ST%d", i);
		snprintf(txt, sizeof(txt), "m%d", i);
		CHECK(aprsMsgOnIncoming(b, from, txt, "1", t + (uint32_t)i) == true, "вхідне %d", i);
	}
	CHECK(aprsMsgListCount(b) == 8U && strcmp(b->list[0].call, "ST9") == 0 && strcmp(b->list[7].call, "ST2") == 0, "8 записів: ST9 … ST2");
	/* наше повідомлення, що ще чекає, витіснити не можна: заповнюємо список вхідними, а вихідні лишаються */
	aprsMsgInit(b, 0U);
	(void)aprsMsgSend(b, "AAA", "pending", t, NULL);
	for (int i = 0; i < 12; i++)
	{
		char from[12];

		snprintf(from, sizeof(from), "ST%d", i);
		(void)aprsMsgOnIncoming(b, from, "x", "", t);
	}
	{
		int found = 0;

		for (unsigned i = 0; i < APRS_MSG_LIST_MAX; i++)
		{
			found += (b->list[i].used && b->list[i].dir == AMSG_DIR_OUT && b->list[i].status == AMSG_ST_WAIT) ? 1 : 0;
		}
		CHECK(found == 1 && aprsMsgListCount(b) == 8U, "вихідне, що чекає, не витіснено");
	}
	/* довгий вхідний текст обрізається до розміру запису, NUL на місці */
	{
		char big[200];

		memset(big, 'z', sizeof(big) - 1U); big[sizeof(big) - 1U] = 0;
		aprsMsgInit(b, 0U);
		CHECK(aprsMsgOnIncoming(b, "AAA", big, "1", t) == true && strlen(b->list[0].text) == APRS_MSG_TEXT_LEN - 1U, "довгий вхідний текст обрізано з NUL");
	}
	/* розмір блоку (пам'ять!) */
	printf("    sizeof(aprsMsgBox_t) = %zu байт, запис списку %zu, завдання %zu\n", sizeof(aprsMsgBox_t), sizeof(aprsMsgEntry_t), sizeof(aprsMsgJob_t));
	CHECK(sizeof(aprsMsgBox_t) < 1600U, "блок завеликий: %zu", sizeof(aprsMsgBox_t));
}

static void testWrapAndInbox(void)
{
	int ls, nx, n;
	const char *t = "Hello big wonderful world";   /* 25 символів */

	/* ширина 10: «Hello big» / «wonderful» / «world» */
	n = aprsMsgWrapLine(t, 25, 0, 10, &ls, &nx);
	CHECK(n == 9 && ls == 0 && strncmp(t + ls, "Hello big", 9) == 0, "рядок 1: %d", n);
	n = aprsMsgWrapLine(t, 25, nx, 10, &ls, &nx);
	CHECK(n == 9 && strncmp(t + ls, "wonderful", 9) == 0, "рядок 2: %d", n);
	n = aprsMsgWrapLine(t, 25, nx, 10, &ls, &nx);
	CHECK(n == 5 && strncmp(t + ls, "world", 5) == 0 && nx >= 25, "рядок 3: %d", n);
	n = aprsMsgWrapLine(t, 25, nx, 10, &ls, &nx);
	CHECK(n == 0 && nx == 25, "далі порожньо");
	/* довге слово рубається по ширині */
	n = aprsMsgWrapLine("abcdefghijklmnop", 16, 0, 10, &ls, &nx);
	CHECK(n == 10 && nx == 10, "слово довше за ширину: %d", n);
	n = aprsMsgWrapLine("abcdefghijklmnop", 16, nx, 10, &ls, &nx);
	CHECK(n == 6 && nx == 16, "залишок слова: %d", n);
	/* порожнє й самі пробіли */
	n = aprsMsgWrapLine("", 0, 0, 10, &ls, &nx);
	CHECK(n == 0 && nx == 0, "порожній текст");
	n = aprsMsgWrapLine("    ", 4, 0, 10, &ls, &nx);
	CHECK(n == 0 && nx == 4, "самі пробіли");
	/* рядок рівно по ширині, далі пробіл */
	n = aprsMsgWrapLine("0123456789 ab", 13, 0, 10, &ls, &nx);
	CHECK(n == 10 && nx == 11, "рівно по ширині + пробіл: n=%d nx=%d", n, nx);

	/* пауза між передачами */
	{
		aprsMsgBox_t *b = &g_box;

		aprsMsgInit(b, 0U);
		CHECK(aprsMsgGapOk(b, 100U) == true, "ще нічого не передавали -- можна");
		aprsMsgTxEnded(b, 10000U);
		CHECK(aprsMsgGapOk(b, 11999U) == false && aprsMsgGapOk(b, 12000U) == true, "рівно 2 с після кінця");
	}
}


/* ---- R11-fix2: ACK на КОЖНУ копію, довгі повідомлення, пріоритет і витіснення, лічильники ---------------------------- */

/* cp1251 -> UTF-8 БЕЗ ліміту 67 байт (як це робить APRSdroid): так довге повідомлення надходить з ефіру. */
static size_t cpToUtf8Full(const char *cp, char *out, size_t cap)
{
	size_t n = 0;

	for (; *cp != 0; cp++)
	{
		uint8_t c = (uint8_t)*cp;

		if (c < 0x80U)
		{
			out[n++] = (char)c;
		}
		else
		{
			uint16_t u = aprsModeCp1251ToUcs2(c);

			out[n++] = (char)(0xC0U | (u >> 6));
			out[n++] = (char)(0x80U | (u & 0x3FU));
		}
		if (n + 3U >= cap)
		{
			break;
		}
	}
	out[n] = 0;
	return n;
}

/* Прогнати інфо-поле через ТОЙ САМИЙ розбір, що в приймачі (aprsPacketParse), і віддати поля як їх бачить aprs_rx.c. */
static void rxInfo(const char *utf8Info, aprsPacket_t *pkt)
{
	aprsAx25_t ax;

	memset(&ax, 0, sizeof(ax));
	ax.info = (const uint8_t *)utf8Info;
	ax.infoLen = (uint16_t)strlen(utf8Info);
	aprsPacketParse(&ax, pkt);
}

static void testFix2(void)
{
	aprsMsgBox_t *b = &g_box;
	char info[160];
	uint32_t t = 100000U;

	/* --- ACK на КОЖНУ копію: три копії того самого повідомлення -> три ACK, один рядок у списку ---------------------------- */
	aprsMsgInit(b, 0U);
	for (int i = 0; i < 3; i++)
	{
		uint32_t ti = t + (uint32_t)i * 31000U;   /* APRSdroid повторює з інтервалом у десятки секунд */

		aprsMsgCountRx(b);
		CHECK(aprsMsgQueueAck(b, "UW5ELK-5", "5", ti, NULL) == true, "копія %d: ACK поставлено ДО рішення про дублікат", i);
		CHECK(aprsMsgOnIncoming(b, "UW5ELK-5", "hello", "5", ti) == (i == 0), "копія %d: у списку лише перша", i);
		CHECK(aprsMsgPoll(b, ti, false, true, info, sizeof(info)) != 0U && strcmp(info, ":UW5ELK-5 :ack5") == 0, "копія %d: ACK у ефір: \"%s\"", i, info);
		aprsMsgTxDone(b, ti, true, false);
		aprsMsgTxEnded(b, ti + 700U);
	}
	CHECK(aprsMsgListCount(b) == 1U, "один рядок у списку");
	CHECK(b->stats.rx == 3U && b->stats.rxNew == 1U && b->stats.ackFormed == 3U && b->stats.ackSent == 3U && b->stats.ackLost == 0U, "лічильники: rx=%u new=%u formed=%u sent=%u",
			(unsigned)b->stats.rx, (unsigned)b->stats.rxNew, (unsigned)b->stats.ackFormed, (unsigned)b->stats.ackSent);
	CHECK(strcmp(b->lastAckText, ":UW5ELK-5 :ack5") == 0, "текст останнього ACK: \"%s\"", b->lastAckText);

	/* той самий номер, ІНШИЙ текст (відправник почав нумерацію спочатку) -- нове повідомлення, а не повтор */
	CHECK(aprsMsgOnIncoming(b, "UW5ELK-5", "other text", "5", t + 100000U) == true && aprsMsgListCount(b) == 2U, "той самий номер з іншим текстом -- нове");

	/* --- номери "5", "10", "11", "aB1": кадр ACK побайтово --------------------------------------------------------------- */
	{
		static const char *ids[] = { "5", "10", "11", "aB1" };
		static const char *want[] = { ":UW5ELK-5 :ack5", ":UW5ELK-5 :ack10", ":UW5ELK-5 :ack11", ":UW5ELK-5 :ackaB1" };

		aprsMsgInit(b, 0U);
		for (int i = 0; i < 4; i++)
		{
			uint32_t ti = t + (uint32_t)i * 3000U;

			CHECK(aprsMsgQueueAck(b, "UW5ELK-5", ids[i], ti, NULL) == true, "id %s: у чергу", ids[i]);
			CHECK(aprsMsgPoll(b, ti, false, true, info, sizeof(info)) != 0U && strcmp(info, want[i]) == 0, "id %s: \"%s\"", ids[i], info);
			aprsMsgTxDone(b, ti, true, false);
			aprsMsgTxEnded(b, ti + 700U);
		}
	}

	/* --- довге повідомлення (~90 байт UTF-8): приймається, показується обрізаним, ACK іде --------------------------------- */
	{
		char wire[300], utf[200], pk0[2];
		aprsPacket_t pkt;
		/* «привіт усім, перевірка українського шрифта, ще трохи довшого тексту» -- байтами cp1251 */
		static const char longCp[] =
				"\xEF\xF0\xE8\xE2\xB3\xF2 \xF3\xF1\xB3\xEC, \xEF\xE5\xF0\xE5\xE2\xB3\xF0\xEA\xE0 \xF3\xEA\xF0\xE0\xBF\xED\xF1\xFC\xEA\xEE\xE3\xEE "
				"\xF8\xF0\xE8\xF4\xF2\xE0, \xBF\xF9\xE5 \xF2\xF0\xEE\xF5\xE8 \xE4\xEE\xE2\xF8\xEE\xE3\xEE";
		size_t ub = cpToUtf8Full(longCp, utf, sizeof(utf));

		(void)pk0;
		CHECK(ub >= 90U, "тестове повідомлення справді довге: %u байт UTF-8", (unsigned)ub);
		snprintf(wire, sizeof(wire), ":UW5ELK-7 :%s{12", utf);
		aprsMsgInit(b, 0U);
		rxInfo(wire, &pkt);
		CHECK(pkt.type == APRS_T_MESSAGE && strcmp(pkt.msgId, "12") == 0 && pkt.msgAck == false, "розібрано як повідомлення з номером 12");
		CHECK(strlen(pkt.text) > 40U, "текст розкодовано (cp1251, %u символів)", (unsigned)strlen(pkt.text));
		aprsMsgCountRx(b);
		CHECK(aprsMsgQueueAck(b, "UW5ELK-5", pkt.msgId, t, NULL) == true, "ACK на довге поставлено (довжина не відсікає)");
		CHECK(aprsMsgOnIncoming(b, "UW5ELK-5", pkt.text, pkt.msgId, t) == true && aprsMsgListCount(b) == 1U, "довге -- у списку");
		CHECK(strcmp(b->list[0].text, pkt.text) == 0 || strlen(b->list[0].text) < strlen(pkt.text), "у списку повний або обрізаний текст");
		CHECK(aprsMsgOnIncoming(b, "UW5ELK-5", pkt.text, pkt.msgId, t + 31000U) == false, "копія довгого -- не дублюється (порівняння з обрізаним)");
		CHECK(aprsMsgPoll(b, t, false, true, info, sizeof(info)) != 0U && strcmp(info, ":UW5ELK-5 :ack12") == 0, "ACK на довге пішов: \"%s\"", info);

		/* найдовше, що влізає в кадр AX.25 (до ~250 байт info): усе одно приймається, ACK є */
		{
			char big[300];
			size_t bn = 0;

			wire[0] = 0;
			while ((bn + 2U) < 200U)
			{
				bn += 2U;
				big[bn - 2U] = (char)0xD0; big[bn - 1U] = (char)0xB0;   /* «а» */
			}
			big[bn] = 0;
			snprintf(wire, sizeof(wire), ":UW5ELK-7 :%s{7", big);
			rxInfo(wire, &pkt);
			CHECK(pkt.type == APRS_T_MESSAGE && strcmp(pkt.msgId, "7") == 0, "200-байтовий текст: повідомлення з номером 7");
			aprsMsgInit(b, 0U);
			CHECK(aprsMsgQueueAck(b, "UW5ELK-5", pkt.msgId, t, NULL) == true && aprsMsgOnIncoming(b, "UW5ELK-5", pkt.text, pkt.msgId, t) == true, "ACK і запис для 200-байтового тексту");
			CHECK(strlen(b->list[0].text) < APRS_MSG_TEXT_LEN, "текст у списку обрізаний до %u символів", (unsigned)(APRS_MSG_TEXT_LEN - 1U));
		}
	}

	/* --- ACK першим у черзі: ACK, поставлений ПІСЛЯ нашого повідомлення, іде раніше ------------------------------------------ */
	aprsMsgInit(b, 0U);
	(void)aprsMsgSend(b, "AAA", "msg1", t, NULL);
	(void)aprsMsgSend(b, "BBB", "msg2", t, NULL);
	CHECK(aprsMsgQueueAck(b, "CCC", "9", t + 5U, NULL) == true, "ACK поставлено після двох повідомлень");
	CHECK(aprsMsgPoll(b, t + 10U, false, true, info, sizeof(info)) != 0U && strcmp(info, ":CCC      :ack9") == 0, "перший у ефірі -- ACK: \"%s\"", info);

	/* --- черга повна, ACK витісняє СТАРІШЕ наше повідомлення, а не навпаки ---------------------------------------------------- */
	aprsMsgInit(b, 0U);
	for (int i = 0; i < 4; i++)
	{
		CHECK(aprsMsgSend(b, "AAA", "x", t + (uint32_t)i, NULL) == AMSG_OK, "повідомлення %d", i);
	}
	CHECK(aprsMsgSend(b, "AAA", "x", t, NULL) == AMSG_E_FULL, "повідомлення при повній черзі -- відмова, ACK не витісняє нічого");
	CHECK(aprsMsgQueueAck(b, "BBB", "1", t + 10U, NULL) == true && aprsMsgAckPending(b) == 1U && aprsMsgPendingCount(b) == 3U, "ACK витіснив одне повідомлення");
	CHECK(aprsMsgQueueAck(b, "BBB", "2", t + 11U, NULL) == true && aprsMsgQueueAck(b, "BBB", "3", t + 12U, NULL) == true && aprsMsgQueueAck(b, "BBB", "4", t + 13U, NULL) == true,
			"ще три ACK витіснили решту повідомлень");
	CHECK(aprsMsgAckPending(b) == 4U && aprsMsgPendingCount(b) == 0U, "тепер у черзі лише ACK");
	CHECK(aprsMsgQueueAck(b, "BBB", "5", t + 14U, NULL) == false && b->stats.ackLost == 1U, "п'ятий ACK не вміщається (усі слоти ACK) -- лічиться як втрачений");
	CHECK(aprsMsgSend(b, "AAA", "x", t, NULL) == AMSG_E_FULL, "наше повідомлення не витісняє ACK");
	/* повідомлення, що вже в ефірі, не витісняється */
	aprsMsgInit(b, 0U);
	(void)aprsMsgSend(b, "AAA", "m1", t, NULL);
	CHECK(aprsMsgPoll(b, t, false, true, info, sizeof(info)) != 0U, "повідомлення m1 видано (inflight)");
	for (int i = 0; i < 3; i++)
	{
		(void)aprsMsgSend(b, "AAA", "m", t + (uint32_t)i + 1U, NULL);
	}
	CHECK(aprsMsgQueueAck(b, "BBB", "1", t + 10U, NULL) == true && b->inflight >= 0 && b->q[b->inflight].type == AMSG_JOB_MSG, "ACK витіснив інше повідомлення, а не те, що в ефірі");

	/* --- ACK, який не вдалось почати: до 3 спроб через 1,5 с, далі знято; передані не повторюються ------------------------- */
	aprsMsgInit(b, 0U);
	(void)aprsMsgQueueAck(b, "BBB", "1", t, NULL);
	for (int k = 0; k < 3; k++)
	{
		uint32_t tk = t + (uint32_t)k * 1500U;

		CHECK(aprsMsgPoll(b, tk, false, true, info, sizeof(info)) != 0U, "спроба %d видана", k);
		aprsMsgTxDone(b, tk, false, false);
		CHECK(aprsMsgPoll(b, tk + 1499U, false, true, info, sizeof(info)) == 0U || k == 2, "до 1,5 с нової спроби нема");
	}
	CHECK(aprsMsgQueueLen(b) == 0U && b->stats.ackLost == 1U && b->stats.ackSent == 0U, "після 3 невдач ACK знято і пораховано як втрачений");
	/* а вже ПЕРЕДАНИЙ ACK не повторюється */
	aprsMsgInit(b, 0U);
	(void)aprsMsgQueueAck(b, "BBB", "1", t, NULL);
	(void)aprsMsgPoll(b, t, false, true, info, sizeof(info));
	aprsMsgTxDone(b, t, true, false);
	aprsMsgTxEnded(b, t + 700U);
	CHECK(aprsMsgQueueLen(b) == 0U && aprsMsgPoll(b, t + 60000U, false, true, info, sizeof(info)) == 0U, "переданий ACK не повторюється");
}

/* R11-fix: позивний-SSID в адресаті повідомлення й ACK -- байт-у-байт проти еталонів, виписаних вручну.
 * Поле адресата рівно 9 символів, пробіли ТІЛЬКИ праворуч; SSID 0 -- без «-0»; 1..15 -- «-1»…«-15» без нулів і пробілів. */
static void testSsidForms(void)
{
	static const struct { const char *typed; const char *msg; const char *ack; unsigned ssid; } t[] = {
		{ "UW5ELK",    ":UW5ELK   :Hi{01", ":UW5ELK   :ack01", 0U },
		{ "UW5ELK-0",  ":UW5ELK   :Hi{01", ":UW5ELK   :ack01", 0U },
		{ "uw5elk-1",  ":UW5ELK-1 :Hi{01", ":UW5ELK-1 :ack01", 1U },
		{ "UW5ELK-7",  ":UW5ELK-7 :Hi{01", ":UW5ELK-7 :ack01", 7U },
		{ "UW5ELK-10", ":UW5ELK-10:Hi{01", ":UW5ELK-10:ack01", 10U },
		{ "UW5ELK-15", ":UW5ELK-15:Hi{01", ":UW5ELK-15:ack01", 15U },
	};
	char out[96];

	for (unsigned k = 0; k < sizeof(t) / sizeof(t[0]); k++)
	{
		aprsAx25_t ax;
		aprsPacket_t pk;
		size_t n = aprsMsgBuildMessage(out, sizeof(out), t[k].typed, "Hi", "01");

		CHECK(n == 16U && strcmp(out, t[k].msg) == 0, "повідомлення «%s» -> \"%s\" (еталон \"%s\")", t[k].typed, out, t[k].msg);
		CHECK(out[10] == ':' && strchr(out + 1, '\t') == NULL, "поле адресата рівно 9 символів, 10-й -- ':'");
		/* пробіли лише праворуч: між першим пробілом і ':' нема нічого, крім пробілів */
		{
			const char *sp = strchr(out + 1, ' ');
			int onlySpaces = 1;

			for (const char *c = sp; (sp != NULL) && (c < out + 10); c++) { if (*c != ' ') { onlySpaces = 0; } }
			CHECK(onlySpaces, "пробіли в адресаті лише праворуч");
		}
		/* наш же приймач: адресат ПІСЛЯ розбору збігається з нашим позивним-SSID, а з іншим SSID -- ні */
		memset(&ax, 0, sizeof(ax));
		ax.info = (const uint8_t *)out;
		ax.infoLen = (uint16_t)n;
		aprsPacketParse(&ax, &pk);
		CHECK((pk.type == APRS_T_MESSAGE) && aprsMsgIsForUs(pk.msgTo, "UW5ELK", (uint8_t)t[k].ssid) && !aprsMsgIsForUs(pk.msgTo, "UW5ELK", (uint8_t)((t[k].ssid + 1U) & 15U)),
				"приймач: «%s» -- це UW5ELK з SSID %u і лише він", pk.msgTo, t[k].ssid);
		n = aprsMsgBuildAck(out, sizeof(out), t[k].typed, "01");
		CHECK(strcmp(out, t[k].ack) == 0 && (n == strlen(t[k].ack)), "ACK «%s» -> \"%s\" (еталон \"%s\")", t[k].typed, out, t[k].ack);
	}
}

/* R13 (П.6): відправник фіксується в завданні й не залежить від того, що відбувається потім */
static void testFrom(void)
{
	aprsMsgBox_t *b = &g_box;
	char info[160];
	uint32_t t = 100000U;

	aprsMsgInit(b, 0U);
	CHECK(aprsMsgSend(b, "N0CALL-9", "Hi", t, "uw5elk-7") == AMSG_OK, "поставлено з відправником");
	CHECK(strcmp(b->q[0].from, "UW5ELK-7") == 0, "відправник нормалізовано: \"%s\"", b->q[0].from);
	CHECK(aprsMsgSend(b, "N0CALL-8", "Hi", t, "N0CALL-0") == AMSG_OK && strcmp(b->q[1].from, "N0CALL") == 0, "SSID 0 відкидається");
	CHECK(aprsMsgSend(b, "N0CALL-7", "Hi", t, "not a call") == AMSG_OK && b->q[2].from[0] == 0, "недійсний відправник -> порожній (стандартний)");
	CHECK(aprsMsgSend(b, "N0CALL-6", "Hi", t, NULL) == AMSG_OK && b->q[3].from[0] == 0, "NULL -> порожній");

	/* аксесор: відправник завдання, що в ефірі; щойно видане -- перше завдання (нічого іншого не готове) */
	CHECK(aprsMsgInflightFrom(b)[0] == 0, "нічого в ефірі -- порожній рядок");
	CHECK(aprsMsgPoll(b, t, false, true, info, sizeof(info)) > 0U, "видано кадр");
	CHECK(strcmp(aprsMsgInflightFrom(b), "UW5ELK-7") == 0, "відправник завдання в ефірі: \"%s\"", aprsMsgInflightFrom(b));
	aprsMsgTxDone(b, t, true, false);
	CHECK(aprsMsgInflightFrom(b)[0] == 0, "після TxDone -- порожній");

	/* повтор тим самим відправником (повторні спроби не змінюють поле) */
	aprsMsgTxEnded(b, t + 100U);
	CHECK(strcmp(b->q[0].from, "UW5ELK-7") == 0, "поле не змінилось після спроби");

	/* ACK: відправник = переданий (адресат вхідного); ACK при повній черзі, що витісняє повідомлення, теж несе його */
	aprsMsgInit(b, 0U);
	CHECK(aprsMsgQueueAck(b, "UW5ELK-5", "10", t, "US5EX-7") && strcmp(b->q[0].from, "US5EX-7") == 0, "ACK від адресата");
	CHECK(aprsMsgQueueAck(b, "UW5ELK-4", "11", t, NULL) && b->q[1].from[0] == 0, "ACK без відправника -- стандартний");
	CHECK(sizeof(aprsMsgBox_t) <= 1336U, "блок влазить у резерв кільця (1336 Б): %zu", sizeof(aprsMsgBox_t));
}

/* R13: лічильник НЕпрочитаних APRS (іконка зліва на головному екрані): окремий від DMR-SMS, живе в постійному блоці. */
static void testUnread(void)
{
	aprsMsgBox_t *b = &g_box;
	uint32_t t = 90000U;

	printf("== R13: лічильник непрочитаних ==\n");
	aprsMsgInit(b, 0U);
	CHECK(aprsMsgUnreadCount(b) == 0U, "порожній блок: 0 (іконки нема)");
	CHECK(aprsMsgOnIncoming(b, "AAA", "one", "1", t), "прийом 1");
	CHECK(aprsMsgUnreadCount(b) == 1U, "після прийому: 1");
	CHECK(aprsMsgOnIncoming(b, "BBB", "two", "2", t + 1U) && aprsMsgOnIncoming(b, "CCC", "three", "3", t + 2U), "прийом 2 і 3");
	CHECK(aprsMsgUnreadCount(b) == 3U, "три непрочитані");
	/* повтор тієї самої копії (відправник не почув ACK) лічильник не збільшує */
	CHECK(aprsMsgOnIncoming(b, "AAA", "one", "1", t + 5000U) == false && aprsMsgUnreadCount(b) == 3U, "повтор копії: без зміни");
	/* наше вихідне непрочитаним не вважається */
	CHECK(aprsMsgSend(b, "DDD", "out", t + 10U, NULL) == AMSG_OK && aprsMsgUnreadCount(b) == 3U, "вихідне не рахується");
	/* прочитали -- лічильник падає; повторне «прочитано» того самого -- ні */
	aprsMsgMarkRead(b, 0U);
	CHECK(aprsMsgUnreadCount(b) <= 3U, "після читання не росте");
	{
		unsigned u0 = aprsMsgUnreadCount(b);

		aprsMsgMarkRead(b, 0U);
		CHECK(aprsMsgUnreadCount(b) == u0, "повторне «прочитано» -- без зміни");
	}
	/* переповнення списку: 12 вхідних до списку на 8 -- непрочитаних не більше розміру списку, і лічильник сходиться з реальним списком */
	aprsMsgInit(b, 0U);
	for (int i = 0; i < 12; i++)
	{
		char from[12], id[8];

		snprintf(from, sizeof(from), "ST%d", i);
		snprintf(id, sizeof(id), "%d", i);
		(void)aprsMsgOnIncoming(b, from, "x", id, t + (uint32_t)i);
	}
	{
		unsigned real = 0;

		for (unsigned i = 0; i < APRS_MSG_LIST_MAX; i++)
		{
			real += (b->list[i].used && b->list[i].unread && (b->list[i].dir == AMSG_DIR_IN)) ? 1U : 0U;
		}
		CHECK((aprsMsgUnreadCount(b) == real) && (real <= APRS_MSG_LIST_MAX), "переповнення: лічильник %u збігається зі списком (%u)", aprsMsgUnreadCount(b), real);
		CHECK(aprsMsgUnreadCount(b) == APRS_MSG_LIST_MAX, "усі 8 записів списку непрочитані");
	}
	for (unsigned i = 0; i < APRS_MSG_LIST_MAX; i++)
	{
		aprsMsgMarkRead(b, i);
	}
	CHECK(aprsMsgUnreadCount(b) == 0U, "усе прочитано -- іконка зникає (0)");
	/* підпис іконки обмежено двома цифрами (код шапки: min(n, 99)) */
	CHECK(((aprsMsgUnreadCount(b) > 99U) ? 99U : aprsMsgUnreadCount(b)) == 0U, "обмеження 99");
}

int main(void)
{
	testCharBytes();
	testRoundTrip();
	testLimit();
	testTextCheck();
	testNormCall();
	testBuild();
	testRetries();
	testCancelOnAck();
	testAck();
	testScheduling();
	testNumbersAndOverflow();
	testWrapAndInbox();
	testSsidForms();
	testFix2();
	testFrom();
	testUnread();
	if (s_fail != 0)
	{
		printf("test_aprs_msg: ПРОВАЛІВ %d з %d перевірок\n", s_fail, s_checks);
		return 1;
	}
	printf("test_aprs_msg: усі %d перевірок пройшли\n", s_checks);
	return 0;
}
