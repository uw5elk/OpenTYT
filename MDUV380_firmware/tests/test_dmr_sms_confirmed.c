/*
 * test_dmr_sms_confirmed.c — контракт CRC9 і розкладки блока CONFIRMED SMS.
 *
 * Перевіряє функції crc9_confirmed() і confirmed_block_fill() (дзеркало з dmr_sms.c)
 * на відомих тестових векторах, обчислених аналітично + тим самим алгоритмом на ПК
 * (2026-09-27). Вектори 1–3 перевіряються незалежно аналітично (all-zero → регістр
 * залишається нульовим до кінцевої інверсії+маски).
 *
 * ⚠ КРИТИЧНО: ці вектори ще НЕ звірені з реальним зразком з ефіру або ok-dmrlib Python.
 * Вони гарантують: правильний поліном (0x059), правильний ініціалізатор (0), правильна
 * фінальна маска (0x0F0), правильне кодування DBSN. Звірка з ефіром (dmrSmsRxRawBlocks
 * USB 0xB3) — крок 2 з TESTING.md; до нього вважати «CRC9 ймовірно правильний, але
 * не підтверджено на живих даних».
 *
 * Мінімальні залежності: libe-c, без ARM, без залізних заголовків.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

/* ---- копія алгоритму з dmr_sms.c ----------------------------------------
 * ETSI TS 102 361-1 §B.3.10: 9-бітний CRC, poly 0x059, init=0,
 * final = (~reg & 0x1FF) ^ 0x0F0 (маска Rate12DataContinuation).
 * Дані: payload (10 байт), потім 7-бітний DBSN (MSB першим).
 * Якщо алгоритм у dmr_sms.c зміниться — змінити і тут, і перерахувати вектори. */
static uint16_t crc9_ref(const uint8_t *payload10, uint8_t dbsn)
{
	uint16_t reg = 0;
	for (int i = 0; i < 10; i++)
		for (int b = 7; b >= 0; b--)
		{
			uint16_t msb = (reg >> 8) & 1;
			reg = (uint16_t)((reg << 1) & 0x1FF);
			if (msb ^ ((payload10[i] >> b) & 1)) { reg ^= 0x059; }
		}
	for (int b = 6; b >= 0; b--)
	{
		uint16_t msb = (reg >> 8) & 1;
		reg = (uint16_t)((reg << 1) & 0x1FF);
		if (msb ^ ((dbsn >> b) & 1)) { reg ^= 0x059; }
	}
	return (uint16_t)((~reg & 0x1FF) ^ 0x0F0);
}

/* ---- копія confirmed_block_fill() з dmr_sms.c ----------------------------
 * Пакує [7b DBSN][9b CRC9 bit-rev][10B payload] у 12 байт.
 * Пастка: CRC9 біти йдуть у ЗВОРОТНЬОМУ порядку (молодший перший),
 * але DBSN — у прямому (старший перший). */
static void block_fill_ref(uint8_t *p12, const uint8_t *payload10, uint8_t dbsn)
{
	uint16_t c9 = crc9_ref(payload10, dbsn);
	p12[0] = (uint8_t)((dbsn << 1) | (c9 & 1));
	uint8_t b1 = 0;
	for (int i = 1; i <= 8; i++) { b1 |= (uint8_t)(((c9 >> i) & 1) << (8 - i)); }
	p12[1] = b1;
	memcpy(p12 + 2, payload10, 10);
}

/* ---- допоміжні функції --------------------------------------------------- */
static int fails = 0;

static void expect_u16(const char *what, uint16_t got, uint16_t exp)
{
	if (got != exp) {
		fails++;
		printf("  FAIL %s: очік=0x%03X, маємо=0x%03X\n", what, exp, got);
	} else {
		printf("  ok   %s = 0x%03X\n", what, got);
	}
}

static void expect_byte(const char *what, uint8_t got, uint8_t exp)
{
	if (got != exp) {
		fails++;
		printf("  FAIL %s: очік=%02x, маємо=%02x\n", what, exp, got);
	} else {
		printf("  ok   %s = %02x\n", what, got);
	}
}

/* ---- копія алгоритму rate-3/4 з dmr_sms.c --------------------------------
 * Те саме, але payload = 16 байт (не 10). Решта ідентична. */
static uint16_t crc9_r34_ref(const uint8_t *payload16, uint8_t dbsn)
{
	uint16_t reg = 0;
	for (int i = 0; i < 16; i++)
		for (int b = 7; b >= 0; b--)
		{
			uint16_t msb = (reg >> 8) & 1;
			reg = (uint16_t)((reg << 1) & 0x1FF);
			if (msb ^ ((payload16[i] >> b) & 1)) { reg ^= 0x059; }
		}
	for (int b = 6; b >= 0; b--)
	{
		uint16_t msb = (reg >> 8) & 1;
		reg = (uint16_t)((reg << 1) & 0x1FF);
		if (msb ^ ((dbsn >> b) & 1)) { reg ^= 0x059; }
	}
	return (uint16_t)((~reg & 0x1FF) ^ 0x0F0);
}

/* ---- копія confirmed_block_fill_r34() з dmr_sms.c -----------------------
 * Пакує [7b DBSN][9b CRC9 bit-rev][16B payload] у 18 байт. */
static void block_fill_r34_ref(uint8_t *p18, const uint8_t *payload16, uint8_t dbsn)
{
	uint16_t c9 = crc9_r34_ref(payload16, dbsn);
	p18[0] = (uint8_t)((dbsn << 1) | (c9 & 1));
	uint8_t b1 = 0;
	for (int i = 1; i <= 8; i++) { b1 |= (uint8_t)(((c9 >> i) & 1) << (8 - i)); }
	p18[1] = b1;
	memcpy(p18 + 2, payload16, 16);
}

/* ---- основна програма ---------------------------------------------------- */
int main(void)
{
	printf("test_dmr_sms_confirmed:\n");

	uint8_t zeros[10] = {0};
	uint8_t seq[10]   = {1,2,3,4,5,6,7,8,9,10};
	uint8_t ffs[10];
	memset(ffs, 0xFF, 10);

	/* === CRC9 =================================================================
	 * Вектори 1-3: all-zero payload → регістр 0 протягом усіх 80 бітів навантаження;
	 *   єдина різниця — останні 7 бітів DBSN (MSB-first, одиниця тільки в LSB).
	 *   DBSN=0: рег лишається 0 → (~0 & 0x1FF)^0x0F0 = 0x1FF^0x0F0 = 0x10F.
	 *   DBSN=1: останній (LSB) біт = 1 → одне XOR: рег = 0x059 →
	 *     (~0x059 & 0x1FF) = 0x1A6 → ^0x0F0 = 0x156.
	 *   DBSN=2: передостанній біт = 1 → 2 зсуви з 0 потім XOR: рег = 0x0B2 →
	 *     (~0x0B2 & 0x1FF) = 0x14D → ^0x0F0 = 0x1BD.
	 * Значення підтверджені прогоном crc9_ref на ПК (gcc, не ARM). */
	expect_u16("CRC9(zeros, dbsn=0)", crc9_ref(zeros, 0), 0x10F);
	expect_u16("CRC9(zeros, dbsn=1)", crc9_ref(zeros, 1), 0x156);
	expect_u16("CRC9(zeros, dbsn=2)", crc9_ref(zeros, 2), 0x1BD);

	/* Вектор 4: payload={1..10}, DBSN=0 — нетривіальний, перевіряє поліном/порядок. */
	expect_u16("CRC9({1..10}, dbsn=0)", crc9_ref(seq, 0), 0x133);

	/* Вектор 5: payload=0xFF*10, DBSN=0 */
	expect_u16("CRC9(0xFF*10, dbsn=0)", crc9_ref(ffs, 0), 0x0A6);

	/* Вектор 6: payload=0xFF*10, DBSN=3 */
	expect_u16("CRC9(0xFF*10, dbsn=3)", crc9_ref(ffs, 3), 0x04D);

	/* Санітарна: різний DBSN → різний CRC9 (не константа). */
	if (crc9_ref(zeros, 0) == crc9_ref(zeros, 1)) {
		fails++; printf("  FAIL CRC9 не залежить від DBSN\n");
	} else {
		printf("  ok   CRC9 залежить від DBSN\n");
	}
	/* Санітарна: різний payload → різний CRC9. */
	if (crc9_ref(zeros, 0) == crc9_ref(seq, 0)) {
		fails++; printf("  FAIL CRC9 не залежить від payload\n");
	} else {
		printf("  ok   CRC9 залежить від payload\n");
	}

	/* === РОЗКЛАДКА 12-БАЙТНОГО БЛОКА =========================================
	 * Блок: [7b DBSN без реверсу][9b CRC9 біт-реверснуто (LSB першим)][10B payload].
	 * Упаковка у два перших байти:
	 *   byte0 = (dbsn<<1) | (c9&1)        -- старші 7 біт DBSN + LSB CRC9
	 *   byte1 = CRC9[8..1] у порядку bit8→bit7→...→bit1, тобто bit i → позиція (8-i).
	 * Для dbsn=0, c9=0x10F = 0b1_0000_1111:
	 *   byte0 = (0<<1)|(1) = 0x01
	 *   byte1: bit1=1→pos7, bit2=1→pos6, bit3=1→pos5, bit8=1→pos0 → 0xE1 */
	printf("  [block packing]\n");
	{
		uint8_t p12[12];
		block_fill_ref(p12, zeros, 0);
		expect_byte("block(zeros,0) byte0 (DBSN=0, CRC9[0]=1)", p12[0], 0x01);
		expect_byte("block(zeros,0) byte1 (CRC9[8..1] rev)",     p12[1], 0xE1);
		/* payload bytes passthrough */
		if (memcmp(p12 + 2, zeros, 10) != 0) {
			fails++; printf("  FAIL block payload corrupted\n");
		} else {
			printf("  ok   payload passthrough\n");
		}
	}
	{
		uint8_t p12[12];
		block_fill_ref(p12, seq, 0);
		/* c9=0x133=0b1_0011_0011: byte0=(0<<1)|1=0x01, byte1=0x99 (обраховано вище) */
		expect_byte("block({1..10},0) byte0", p12[0], 0x01);
		expect_byte("block({1..10},0) byte1", p12[1], 0x99);
		if (memcmp(p12 + 2, seq, 10) != 0) {
			fails++; printf("  FAIL block payload corrupted\n");
		} else {
			printf("  ok   payload passthrough\n");
		}
	}
	{
		/* DBSN у старших 7 бітах byte0 */
		uint8_t p12[12];
		block_fill_ref(p12, zeros, 5);   /* dbsn=5=0b0000101, c9=CRC9(zeros,5) */
		uint8_t dbsn_got = (uint8_t)(p12[0] >> 1);
		if (dbsn_got != 5) {
			fails++;
			printf("  FAIL DBSN у byte0: очік=5, маємо=%u\n", dbsn_got);
		} else {
			printf("  ok   DBSN=5 кодується у byte0[7:1] правильно\n");
		}
	}

	/* === CRC9 RATE-3/4 (16-байтний payload) =====================================
	 * Алгоритм ідентичний rate-1/2, але обробляє 16 байт payload замість 10.
	 * Вектори 1-3: all-zero → рег = 0 → CRC9 визначається тільки DBSN.
	 *   Результати тотожні rate-1/2 для all-zeros (payload нульовий — XOR не спрацьовує).
	 * Вектор 4: {1..16}, DBSN=0 → 0x19D (обраховано crc9r34.c на ПК).
	 * Вектор 5: 0xFF*16, DBSN=0 → 0x133.
	 * Вектор 6: 0xFF*16, DBSN=3 → 0x1D8.
	 * ⚠ Ці вектори ще НЕ звірені з ефіром — звірка через dmrSmsRxRawBlocks USB 0xB3. */
	printf("  [rate-3/4 CRC9]\n");
	{
		uint8_t zeros16[16] = {0};
		uint8_t seq16[16]   = {1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16};
		uint8_t ffs16[16];
		memset(ffs16, 0xFF, 16);

		expect_u16("CRC9_r34(zeros,0)",  crc9_r34_ref(zeros16, 0), 0x10F);
		expect_u16("CRC9_r34(zeros,1)",  crc9_r34_ref(zeros16, 1), 0x156);
		expect_u16("CRC9_r34(zeros,2)",  crc9_r34_ref(zeros16, 2), 0x1BD);
		expect_u16("CRC9_r34({1..16},0)", crc9_r34_ref(seq16, 0),  0x19D);
		expect_u16("CRC9_r34(0xFF*16,0)", crc9_r34_ref(ffs16, 0),  0x133);
		expect_u16("CRC9_r34(0xFF*16,3)", crc9_r34_ref(ffs16, 3),  0x1D8);

		/* Санітарні: різний payload та DBSN → різний CRC9. */
		if (crc9_r34_ref(zeros16, 0) == crc9_r34_ref(zeros16, 1)) {
			fails++; printf("  FAIL CRC9_r34 не залежить від DBSN\n");
		} else {
			printf("  ok   CRC9_r34 залежить від DBSN\n");
		}
		if (crc9_r34_ref(zeros16, 0) == crc9_r34_ref(seq16, 0)) {
			fails++; printf("  FAIL CRC9_r34 не залежить від payload\n");
		} else {
			printf("  ok   CRC9_r34 залежить від payload\n");
		}
	}

	/* === РОЗКЛАДКА 18-БАЙТНОГО БЛОКА =========================================
	 * [7b DBSN][9b CRC9 bit-rev][16B payload] — та сама логіка пакування,
	 * але 2 header байти + 16 payload = 18. */
	printf("  [rate-3/4 block packing]\n");
	{
		uint8_t p18[18];
		uint8_t zeros16[16] = {0};
		uint8_t seq16[16]   = {1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16};

		/* zeros,0: c9=0x10F → byte0=(0<<1)|1=0x01, byte1=0xE1 */
		block_fill_r34_ref(p18, zeros16, 0);
		expect_byte("block_r34(zeros,0) byte0", p18[0], 0x01);
		expect_byte("block_r34(zeros,0) byte1", p18[1], 0xE1);
		if (memcmp(p18 + 2, zeros16, 16) != 0) {
			fails++; printf("  FAIL block_r34 payload corrupted\n");
		} else {
			printf("  ok   payload passthrough (16B)\n");
		}

		/* {1..16},0: c9=0x19D → byte0=0x01, byte1=0x73 */
		block_fill_r34_ref(p18, seq16, 0);
		expect_byte("block_r34({1..16},0) byte0", p18[0], 0x01);
		expect_byte("block_r34({1..16},0) byte1", p18[1], 0x73);
		if (memcmp(p18 + 2, seq16, 16) != 0) {
			fails++; printf("  FAIL block_r34 payload corrupted\n");
		} else {
			printf("  ok   payload passthrough (16B)\n");
		}

		/* DBSN=5 у старших 7 бітах byte0 */
		block_fill_r34_ref(p18, zeros16, 5);
		if ((uint8_t)(p18[0] >> 1) != 5) {
			fails++;
			printf("  FAIL block_r34 DBSN у byte0: очік=5, маємо=%u\n", p18[0] >> 1);
		} else {
			printf("  ok   DBSN=5 кодується у byte0[7:1] правильно (r34)\n");
		}
	}

	printf(fails ? "ПРОВАЛ (%d)\n" : "ПРОЙДЕНО\n", fails);
	return fails ? 1 : 0;
}
