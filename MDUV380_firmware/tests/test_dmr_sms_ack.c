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

	printf(fails ? "ПРОВАЛ (%d)\n" : "ПРОЙДЕНО\n", fails);
	return fails ? 1 : 0;
}
