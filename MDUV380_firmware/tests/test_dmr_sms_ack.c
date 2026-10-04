/*
 * test_dmr_sms_ack.c — контракт формату SMS-квитанції (link-layer ACK на CONFIRMED SMS).
 *
 * Формат знято з ефіру HackRF-ом (BBD_0005, 2026-09-12): стокова TYT 0x26EA3D квитує
 * CONFIRMED SMS від RT4D 0x26EA1B. Декодовано власним декодером (tools/dmr_data_rx.py):
 *
 *   квитанція (Response data header, DPF=1):
 *       01 40 26 ea 1b 26 ea 3d 00 08 e5 0b
 *   заголовок оригіналу (Confirmed data header, DPF=3, біт A=1):
 *       43 4b 26 ea 1b 26 ea 3d 83 38 35 b8   (тут перевіряємо лише CRC-контракт)
 *
 * CRC усіх data-заголовків: crc16d (CCITT poly 0x1021, ^0xFFFF) ^ 0xCCCC, big-endian.
 * Цей тест дублює побудову з dmr_sms.c (dmrSmsAckTick) БЕЗ залізних залежностей файлу
 * й звіряє байт-у-байт із ефірним зразком. Якщо колись зміниться CRC-маска, порядок полів
 * чи опкод -- тест впаде.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

/* 2026-09-30: тест лінкує СПРАВЖНІЙ functions/dmr_sms_pdu.c (раніше тут була копія коду --
 * вона могла розійтися з прошивкою непомітно, що й сталося з o9 у b7eedd6). */
#include "functions/dmr_sms_pdu.h"
#define hdr_crc dmrSmsPduHdrCrc

/* Ефірний зразок BBD_0005 -- квитанція стокової з o9=0x08, тобто Status=0. Номер N(S)
 * повідомлення RT4D, на яке вона відповідала, із запису не відомий (заголовок confAir нижче --
 * це ВЛАСНЕ повідомлення стокової до RT4D, не те, що квитується). Тому зразок звіряємо з ns=0. */
static void build_ack(uint32_t to, uint32_t from, uint8_t out12[12])
{
	dmrSmsPduAckHeader(to, from, 0, out12);
}

static int fails = 0;
static void expect_eq(const char *what, const uint8_t *got, const uint8_t *exp, int n)
{
	if (memcmp(got, exp, n) != 0)
	{
		fails++;
		printf("  FAIL %s\n    очік:", what);
		for (int i = 0; i < n; i++) printf(" %02x", exp[i]);
		printf("\n    маєм:");
		for (int i = 0; i < n; i++) printf(" %02x", got[i]);
		printf("\n");
	}
	else
	{
		printf("  ok   %s\n", what);
	}
}

int main(void)
{
	printf("test_dmr_sms_ack:\n");

	/* 1) Квитанція байт-у-байт як в ефірі (BBD_0005). */
	const uint8_t ackAir[12] = { 0x01,0x40, 0x26,0xea,0x1b, 0x26,0xea,0x3d, 0x00, 0x08, 0xe5,0x0b };
	uint8_t ack[12];
	build_ack(0x26EA1B /*кому: RT4D*/, 0x26EA3D /*від кого: стокова*/, ack);
	expect_eq("Response header == ефірний зразок", ack, ackAir, 12);

	/* 1a) Регресія польового бага: o8 = BF = 0 (не лічильник блоків). */
	if (ack[8] != 0x00) { fails++; printf("  FAIL o8 має бути 00, а не %02x\n", ack[8]); }
	else { printf("  ok   o8=00 (BF)\n"); }

	/* 1b) o9 = Class(7-6)=00 | Type(5-3)=001 | Status(2-0)=N(S). b7eedd6 писав N(S) у біти 6-4
	 * (N(S)=3 -> 0x38 = Type 111), це ламало Class/Type. */
	{
		uint8_t a[12];
		dmrSmsPduAckHeader(0x26EA1B, 0x26EA3D, 3, a);
		if (a[9] != 0x0B) { fails++; printf("  FAIL N(S)=3 -> o9=%02x (очік. 0B)\n", a[9]); }
		else { printf("  ok   N(S)=3 -> o9=0B\n"); }
		dmrSmsPduAckHeader(0x26EA1B, 0x26EA3D, 0, a);
		if (a[9] != 0x08) { fails++; printf("  FAIL N(S)=0 -> o9=%02x (очік. 08)\n", a[9]); }
		else { printf("  ok   N(S)=0 -> o9=08\n"); }
		int cls = 1;
		for (uint8_t ns = 0; ns < 16; ns++)   /* і 8..15: зайві біти відкидаються */
		{
			dmrSmsPduAckHeader(1, 2, ns, a);
			uint8_t c[2]; hdr_crc(a, 10, 0xCCCC, c);
			if ((a[9] & 0xF8) != 0x08 || (a[9] & 7) != (ns & 7) || memcmp(c, a + 10, 2) != 0) { cls = 0; }
		}
		if (!cls) { fails++; printf("  FAIL Class/Type не 00/001 або Status != N(S)&7 або CRC\n"); }
		else { printf("  ok   для N(S)=0..15: Class=00, Type=001, Status=N(S)&7, CRC сходиться\n"); }
	}

	/* 2) CRC-контракт заголовка оригіналу (Confirmed data header): ті самі 10 байт -> ті самі CRC. */
	const uint8_t confAir[12] = { 0x43,0x4b, 0x26,0xea,0x1b, 0x26,0xea,0x3d, 0x83,0x38, 0x35,0xb8 };
	uint8_t crc2[2];
	hdr_crc(confAir, 10, 0xCCCC, crc2);
	expect_eq("Confirmed header CRC (^0xCCCC)", crc2, confAir + 10, 2);

	/* 3) Санітарна: інша адреса -> інший CRC (не константа). */
	uint8_t ack2[12];
	build_ack(0x123456, 0x654321, ack2);
	if (memcmp(ack2 + 10, ack + 10, 2) == 0) { fails++; printf("  FAIL CRC не залежить від адрес\n"); }
	else { printf("  ok   CRC залежить від вмісту\n"); }

	/* 4) diag3 / Завдання 0: програмна перевірка CRC data-заголовка (dmrSmsPduHdrCrcOk), якою
	 * ISR тепер приймає тип 6 з апаратним CRC «bad». Має пропускати і квитанцію стокової, і
	 * звичайні заголовки SMS (стокової 43.. та наш 02..), і відкидати зіпсоване. */
	{
		/* BBD_0000 (2026-09-30): квитанція стокової 0x26EA29 на наше CONFIRMED від 0x26EA0F. */
		const uint8_t ack0000[12] = { 0x01,0x40, 0x26,0xea,0x0f, 0x26,0xea,0x29, 0x00,0x08, 0x66,0x8d };
		int okAck  = dmrSmsPduHdrCrcOk(ack0000, 0xCCCC);
		int okConf = dmrSmsPduHdrCrcOk(confAir, 0xCCCC);          /* заголовок стокової 43 4b .. */
		uint8_t q[16 * BURST_STRIDE];
		uint8_t ct[40]; for (int i = 0; i < 40; i++) ct[i] = (uint8_t)(i * 7 + 1);
		int n = dmrSmsPduBuildUnconf(q, 16, ct, 40, 0x26EA0F, 0x26EA29, 0, 0, 0);
		const uint8_t *our = q + 6 * BURST_STRIDE + 1;               /* burst 6 = наш заголовок 02 .. */
		int okOur  = (n > 7) && (our[0] == 0x02) && dmrSmsPduHdrCrcOk(our, 0xCCCC);
		const uint8_t *csbk = q + 0 * BURST_STRIDE + 1;              /* CSBK-преамбула, маска A5A5 */
		int okCsbk = dmrSmsPduHdrCrcOk(csbk, 0xA5A5) && !dmrSmsPduHdrCrcOk(csbk, 0xCCCC);
		int badAll = 1;                                               /* будь-який 1 біт зіпсовано -> bad */
		for (int bit = 0; bit < 96; bit++)
		{
			uint8_t t[12]; memcpy(t, ack0000, 12); t[bit / 8] ^= (uint8_t)(0x80 >> (bit % 8));
			if (dmrSmsPduHdrCrcOk(t, 0xCCCC)) { badAll = 0; }
		}
		int wrongMask = !dmrSmsPduHdrCrcOk(ack0000, 0xA5A5);
		if (okAck && okConf && okOur && okCsbk && badAll && wrongMask)
		{
			printf("  ok   SW CRC: квитанція BBD_0000, заголовки 43../02.., CSBK(A5A5) -- ok; 96 однобітних псувань -- bad\n");
		}
		else
		{
			fails++;
			printf("  FAIL SW CRC: ack=%d conf=%d our=%d csbk=%d flips=%d mask=%d\n",
			       okAck, okConf, okOur, okCsbk, badAll, wrongMask);
		}
	}

	/* 5) fix3: черга квитанції. Типово БЕЗ преамбул -- одразу Response-заголовок; байти
	 * заголовка ті самі, що й з 6 преамбулами (лише без CSBK попереду). */
	{
		uint8_t hdr[12];
		dmrSmsPduAckHeader(0x26EA29, 0x26EA0F, 6, hdr);           /* BBD_0004: Status=N(S)=6 -> o9=0E */
		static uint8_t q0[8 * BURST_STRIDE], q6[8 * BURST_STRIDE];
		int n0 = dmrSmsPduBuildAckQueue(q0, 8, 0x26EA29, 0x26EA0F, 6, DMR_SMS_DEFAULT_ACK_PREAMBLES, 1);
		int n6 = dmrSmsPduBuildAckQueue(q6, 8, 0x26EA29, 0x26EA0F, 6, 6, 1);
		/* Ефірний зразок нашої ж квитанції з BBD_0004: 01 40 26ea29 26ea0f 00 0e 8ac4. */
		const uint8_t air0004[12] = { 0x01,0x40, 0x26,0xea,0x29, 0x26,0xea,0x0f, 0x00,0x0e, 0x8a,0xc4 };
		int ok = (DMR_SMS_DEFAULT_ACK_PREAMBLES == 0) && (n0 == 1) && (n6 == 7) && (memcmp(hdr, air0004, 12) == 0)
		         && (q0[0] == DTB_DATA_HEADER) && (memcmp(q0 + 1, hdr, 12) == 0)
		         && (q6[6 * BURST_STRIDE] == DTB_DATA_HEADER) && (memcmp(q6 + 6 * BURST_STRIDE + 1, hdr, 12) == 0);
		for (int i = 0; i < 6 && ok; i++)
		{
			const uint8_t *c = q6 + i * BURST_STRIDE;
			ok = (c[0] == DTB_CSBK) && (c[1] == 0xBD) && (c[4] == (uint8_t)(6 - i))   /* лишилось burst-ів */
			     && dmrSmsPduHdrCrcOk(c + 1, 0xA5A5);
		}
		int tooMany = dmrSmsPduBuildAckQueue(q0, 8, 1, 2, 0, 8, 1);   /* 9 > 8 -> -5 */
		if (ok && tooMany == -5)
		{
			printf("  ok   черга квитанції: типово 0 преамбул -> 1 burst (== ефір BBD_0004 `01 40 .. 00 0e 8ac4`); з 6 -- той самий заголовок після 6 CSBK\n");
		}
		else
		{
			fails++;
			printf("  FAIL черга квитанції: n0=%d n6=%d o9=%02x tooMany=%d\n", n0, n6, hdr[9], tooMany);
		}
	}

	/* 6) fix3: типові перемикачі й рішення «без термінатора». */
	{
		int ok = (DMR_SMS_DEFAULT_FAST_END == 1) && (DMR_SMS_DEFAULT_RX_BYPASS == 1) && (DMR_SMS_DEFAULT_ACK_TERM == 0)
		         && !dmrSmsPduUseFastEnd(0, DMR_SMS_DEFAULT_FAST_END)     /* «Без підтв.» -- завжди з термінатором */
		         && dmrSmsPduUseFastEnd(1, DMR_SMS_DEFAULT_FAST_END)
		         && dmrSmsPduUseFastEnd(2, DMR_SMS_DEFAULT_FAST_END)
		         && !dmrSmsPduUseFastEnd(2, 0) && !dmrSmsPduUseFastEnd(3, 1)
		         /* ui1/fix4: цільова пауза квитанції -- типово 80 мс, перемикач 80 -> 50 -> 20 -> 80 */
		         && (DMR_SMS_DEFAULT_ACK_PAUSE_MS == 80)
		         && (dmrSmsPduNextAckPause(80) == 50) && (dmrSmsPduNextAckPause(50) == 20)
		         && (dmrSmsPduNextAckPause(20) == 80) && (dmrSmsPduNextAckPause(37) == 80);
		if (ok) { printf("  ok   типово: «Шв. кінець» увімк для Підтв. 1/2 і 3/4, режим 0 -- з термінатором; RX обхід увімк; квит. без терм.; пауза 80 (80->50->20->80)\n"); }
		else    { fails++; printf("  FAIL типові перемикачі / dmrSmsPduUseFastEnd\n"); }
	}

	printf(fails ? "ПРОВАЛ (%d)\n" : "ПРОЙДЕНО\n", fails);
	return fails ? 1 : 0;
}
