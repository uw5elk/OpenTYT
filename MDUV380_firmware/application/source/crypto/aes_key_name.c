/*
 * aes_key_name.c -- R64C: перетворення cp1251 <-> UTF-16LE для імен слотів AES-ключів. Див. aes_key_name.h.
 */
#include "functions/aes_key_name.h"

#if defined(AES_KEY_NAMES_ENABLED)

#include <string.h>

/* Unicode для байтів cp1251 0x80..0xBF (решта: 0x00..0x7F -- ті самі; 0xC0..0xFF -- U+0410..U+044F). 0x0000 -- байта нема в cp1251 (0x98). Згенеровано з Python cp1251. */
static const uint16_t s_cp1251Hi[64] =
{
	0x0402, 0x0403, 0x201A, 0x0453, 0x201E, 0x2026, 0x2020, 0x2021,   /* 0x80.. */
	0x20AC, 0x2030, 0x0409, 0x2039, 0x040A, 0x040C, 0x040B, 0x040F,   /* 0x88.. */
	0x0452, 0x2018, 0x2019, 0x201C, 0x201D, 0x2022, 0x2013, 0x2014,   /* 0x90.. */
	0x0000, 0x2122, 0x0459, 0x203A, 0x045A, 0x045C, 0x045B, 0x045F,   /* 0x98.. */
	0x00A0, 0x040E, 0x045E, 0x0408, 0x00A4, 0x0490, 0x00A6, 0x00A7,   /* 0xA0.. */
	0x0401, 0x00A9, 0x0404, 0x00AB, 0x00AC, 0x00AD, 0x00AE, 0x0407,   /* 0xA8.. */
	0x00B0, 0x00B1, 0x0406, 0x0456, 0x0491, 0x00B5, 0x00B6, 0x00B7,   /* 0xB0.. */
	0x0451, 0x2116, 0x0454, 0x00BB, 0x0458, 0x0405, 0x0455, 0x0457,   /* 0xB8.. */
};

uint16_t aesNameCp1251ToUnicode(uint8_t b)
{
	if (b < 0x20U)
	{
		return 0x003FU;
	}
	if (b < 0x80U)
	{
		return (uint16_t)b;
	}
	if (b >= 0xC0U)
	{
		return (uint16_t)(0x0410U + (b - 0xC0U));
	}

	return (s_cp1251Hi[b - 0x80U] != 0U) ? s_cp1251Hi[b - 0x80U] : 0x003FU;
}

uint8_t aesNameUnicodeToCp1251(uint16_t u)
{
	if (u == 0U)
	{
		return 0U;
	}
	if (u < 0x20U)
	{
		return (uint8_t)'?';
	}
	if (u < 0x80U)
	{
		return (uint8_t)u;
	}
	if ((u >= 0x0410U) && (u <= 0x044FU))
	{
		return (uint8_t)(0xC0U + (u - 0x0410U));
	}

	for (unsigned i = 0U; i < 64U; i++)
	{
		if (s_cp1251Hi[i] == u)
		{
			return (uint8_t)(0x80U + i);
		}
	}

	return (uint8_t)'?';
}

unsigned aesNameFromField(const uint8_t *field32, char *out)
{
	unsigned n = 0U;

	while (n < AESN_CHARS)
	{
		uint16_t u = (uint16_t)(field32[n * 2U] | ((uint16_t)field32[(n * 2U) + 1U] << 8));

		if ((u == 0U) || (u == 0xFFFFU))
		{
			break;
		}
		out[n] = (char)aesNameUnicodeToCp1251(u);
		n++;
	}
	out[n] = 0;

	return n;
}

unsigned aesNameToField(const char *cp1251, uint8_t *field32)
{
	unsigned n = 0U;

	memset(field32, 0, AESN_FIELD_LEN);

	if (cp1251 == NULL)
	{
		return 0U;
	}

	while ((n < AESN_CHARS) && ((uint8_t)cp1251[n] >= 0x20U))
	{
		n++;
	}
	while ((n > 0U) && (cp1251[n - 1U] == ' '))
	{
		n--;
	}
	for (unsigned i = 0U; i < n; i++)
	{
		uint16_t u = aesNameCp1251ToUnicode((uint8_t)cp1251[i]);

		field32[i * 2U] = (uint8_t)(u & 0xFFU);
		field32[(i * 2U) + 1U] = (uint8_t)(u >> 8);
	}

	return n;
}

bool aesNameIsDefault(uint8_t keyId, const uint8_t *field32)
{
	uint8_t def[AESN_FIELD_LEN];
	unsigned n = 0U;

	memset(def, 0, sizeof(def));
	if (keyId >= 10U)
	{
		def[n * 2U] = (uint8_t)('0' + (keyId / 10U));
		n++;
	}
	def[n * 2U] = (uint8_t)('0' + (keyId % 10U));

	if (memcmp(field32, def, AESN_FIELD_LEN) == 0)
	{
		return true;
	}

	/* порожнє: перший символ U+0000 або U+FFFF (стерта флеш) */
	return ((field32[0] == 0U) && (field32[1] == 0U)) || ((field32[0] == 0xFFU) && (field32[1] == 0xFFU));
}

#endif /* AES_KEY_NAMES_ENABLED */
