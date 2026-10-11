/*
 * aprs_fault_fmt.c -- R10-fix4: чиста частина обробника збою «Режиму APRS». Опис -- aprs_fault_fmt.h.
 * Без заліза, без динамічної пам'яті, без printf: викликається і з обробника HardFault.
 */
#include "functions/aprs_fault_fmt.h"

#if defined(ENABLE_APRS_RX)

void aprsFaultHex8(char *out, uint32_t v)
{
	static const char digits[] = "0123456789ABCDEF";

	for (int i = 0; i < 8; i++)
	{
		out[i] = digits[(v >> (28 - (4 * i))) & 0xFU];
	}
	out[8] = 0;
}

size_t aprsFaultDec(char *out, uint32_t v)
{
	char tmp[10];
	size_t n = 0U;
	size_t len = 0U;

	do
	{
		tmp[n++] = (char)('0' + (v % 10U));
		v /= 10U;
	} while (v != 0U);
	while (n > 0U)
	{
		out[len++] = tmp[--n];
	}
	out[len] = 0;
	return len;
}

const char *aprsFaultKindName(uint32_t kind)
{
	switch (kind)
	{
		case AFLT_KIND_HARD:  return "HARDFAULT";
		case AFLT_KIND_MEM:   return "MEMMANAGE";
		case AFLT_KIND_BUS:   return "BUSFAULT";
		case AFLT_KIND_USAGE: return "USAGEFAULT";
		case AFLT_KIND_WDG:   return "WATCHDOG";
		case AFLT_KIND_IWDG:  return "IWDG RESET";
		default:              return "UNKNOWN";
	}
}

const char *aprsFaultCfsrName(uint32_t cfsr)
{
	/* UFSR (біти 16..25) */
	if (cfsr & (1UL << 25)) { return "DIVBYZERO"; }
	if (cfsr & (1UL << 24)) { return "UNALIGNED"; }
	if (cfsr & (1UL << 19)) { return "NOCOPROC"; }
	if (cfsr & (1UL << 18)) { return "INVPC"; }
	if (cfsr & (1UL << 17)) { return "INVSTATE"; }
	if (cfsr & (1UL << 16)) { return "UNDEFINSTR"; }
	/* BFSR (біти 8..15) */
	if (cfsr & (1UL << 10)) { return "IMPRECISE (PC after)"; }   /* відкладена помилка шини: PC НЕ точний */
	if (cfsr & (1UL << 9))  { return "PRECISERR"; }
	if (cfsr & (1UL << 8))  { return "IBUSERR"; }
	if (cfsr & (1UL << 12)) { return "BUS STKERR"; }
	if (cfsr & (1UL << 11)) { return "BUS UNSTKERR"; }
	if (cfsr & (1UL << 13)) { return "BUS LSPERR"; }
	/* MMFSR (біти 0..7) */
	if (cfsr & (1UL << 1))  { return "DACCVIOL"; }
	if (cfsr & (1UL << 0))  { return "IACCVIOL"; }
	if (cfsr & (1UL << 4))  { return "MM STKERR"; }
	if (cfsr & (1UL << 3))  { return "MM UNSTKERR"; }
	if (cfsr & (1UL << 5))  { return "MM LSPERR"; }
	return "";
}

bool aprsFaultAddrIsCode(uint32_t v)
{
	return ((v & 1U) != 0U) && (v > 0x08000001UL) && (v < 0x08100000UL);
}

int aprsFaultScanStack(const uint32_t *words, size_t n, uint32_t *out, int maxOut)
{
	int found = 0;

	for (size_t i = 0; (i < n) && (found < maxOut); i++)
	{
		uint32_t v = words[i];

		if (aprsFaultAddrIsCode(v) && ((found == 0) || (out[found - 1] != v)))
		{
			out[found++] = v;
		}
	}
	return found;
}

uint32_t aprsFaultMagicFromKind(uint32_t kind)
{
	return AFLT_MAGIC_BASE | (kind & 0xFFU);
}

uint32_t aprsFaultKindFromMagic(uint32_t magicWord)
{
	uint32_t kind = magicWord & 0xFFU;

	if (((magicWord & AFLT_MAGIC_MASK) != AFLT_MAGIC_BASE) || (kind < AFLT_KIND_HARD) || (kind > AFLT_KIND_IWDG))
	{
		return AFLT_KIND_NONE;
	}
	return kind;
}

#endif /* ENABLE_APRS_RX */
