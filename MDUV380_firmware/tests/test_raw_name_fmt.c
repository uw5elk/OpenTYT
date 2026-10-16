/* test_raw_name_fmt.c -- R22 Z2: форматування вікна «сирі байти назви» (functions/raw_name_fmt.h). */
#include <stdio.h>
#include <string.h>
#include "functions/raw_name_fmt.h"

static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

int main(void)
{
	char line[24];
	/* «Папуга» у UTF-8: D0 9F D0 B0 D0 BF D1 83 D0 B3 D0 B0, далі 0xFF-дописка */
	static const uint8_t utf8[16] = { 0xD0,0x9F, 0xD0,0xB0, 0xD0,0xBF, 0xD1,0x83, 0xD0,0xB3, 0xD0,0xB0, 0xFF,0xFF, 0xFF,0xFF };
	/* той самий текст у cp1251: CF E0 EF F3 E3 E0 */
	static const uint8_t cp[16] = { 0xCF,0xE0,0xEF,0xF3,0xE3,0xE0, 0xFF,0xFF, 0xFF,0xFF, 0xFF,0xFF, 0xFF,0xFF, 0xFF,0xFF };
	static const uint8_t lat[16] = { 'L','O','C','A','L',' ','1', 0,0,0,0,0,0,0,0,0 };

	printf("test_raw_name_fmt:\n");
	rawNameHexRow(&utf8[0], line);
	CHECK(strcmp(line, "D09F D0B0 D0BF D183") == 0, "UTF-8 рядок 1: '%s'", line);
	CHECK(strlen(line) == 19, "довжина 19 знаків (влізає в 160 px шрифтом 8x8)");
	rawNameHexRow(&utf8[8], line);
	CHECK(strcmp(line, "D0B3 D0B0 FFFF FFFF") == 0, "UTF-8 рядок 2: '%s'", line);
	rawNameHexRow(&cp[0], line);
	CHECK(strcmp(line, "CFE0 EFF3 E3E0 FFFF") == 0, "cp1251 рядок 1: '%s'", line);
	rawNameAscii(utf8, line);
	CHECK(strcmp(line, "................") == 0, "кирилиця у UTF-8 -> усі '.'");
	rawNameAscii(lat, line);
	CHECK(strcmp(line, "LOCAL 1.........") == 0, "латиниця видна, NUL -> '.' ('%s')", line);
	static const uint8_t edge[16] = { 0x1F, 0x20, 0x7E, 0x7F, 0x80, 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K' };
	rawNameAscii(edge, line);
	CHECK(strcmp(line, ". ~..ABCDEFGHIJK") == 0, "межі 0x20/0x7E/0x7F ('%s')", line);
	printf(fails ? "ПРОВАЛЕНО: %d\n" : "ПРОЙДЕНО\n", fails);
	return fails ? 1 : 0;
}
