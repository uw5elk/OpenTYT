/*
 * raw_name_fmt.h -- R22 Z2: ЧИСТЕ форматування вікна «сирі байти назви» (menuContactList.c): hex по 8 байтів у рядок
 * (пари байтів розділені пробілом, щоб у рядок на 160 px шрифтом 8x8 влізло 19 знаків) і ті самі байти як ASCII.
 * Лише static inline; той самий файл збирає хост-тест tests/test_raw_name_fmt.c. Жодного перекодування.
 */
#ifndef _OPENGD77_RAW_NAME_FMT_H_
#define _OPENGD77_RAW_NAME_FMT_H_

#include <stdint.h>

/* 8 байтів raw -> "D09F D0B0 D0BF D183" (19 знаків + NUL, out >= 20). */
static inline void rawNameHexRow(const uint8_t *raw, char *out)
{
	static const char hx[] = "0123456789ABCDEF";

	for (int i = 0; i < 8; i++)
	{
		*out++ = hx[raw[i] >> 4];
		*out++ = hx[raw[i] & 0x0FU];
		if (((i & 1) != 0) && (i < 7))
		{
			*out++ = ' ';
		}
	}
	*out = 0;
}

/* 16 байтів raw -> 16 знаків ASCII ('.' для байтів поза 0x20..0x7E) + NUL (out >= 17). */
static inline void rawNameAscii(const uint8_t *raw, char *out)
{
	for (int i = 0; i < 16; i++)
	{
		out[i] = ((raw[i] >= 0x20U) && (raw[i] < 0x7FU)) ? (char)raw[i] : '.';
	}
	out[16] = 0;
}

#endif /* _OPENGD77_RAW_NAME_FMT_H_ */
