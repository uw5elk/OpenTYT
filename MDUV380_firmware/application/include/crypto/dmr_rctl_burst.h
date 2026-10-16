/*
 * dmr_rctl_burst.h -- R21 З2: розкладка черги бургстів, яку віддають RCTL-збирачі драйверу dmrDataTxLoad*().
 *
 * Запис черги = 1 байт типу + DMR_DATA_BURST_LEN байтів навантаження (functions/dmr_data.h). Коли 2026-09-29 (ae083d1, CONFIRMED rate-3/4 для SMS) довжину
 * навантаження підняли з 12 до 18, крок запису став 19 -- а RCTL-збирачі (стокові команди, квитанції, власний PDU) лишились на кроці 13. Драйвер читав
 * чергу з кроком 19: перший бургст був правильний, решта -- зсунуті/сміттєві, тож стокова рація команд адміністрування не розпізнавала.
 * Константа живе тут (а не береться з dmr_data.h), бо збирачі -- чисті функції без залежності від драйвера й збираються в хост-тестах; збіг з драйвером
 * перевіряють _Static_assert у functions/dmr_rctl_tx.c і хост-тест tests/test_dmr_rctl_stock.c.
 */
#ifndef _OPENGD77_DMR_RCTL_BURST_H_
#define _OPENGD77_DMR_RCTL_BURST_H_

#include <stdint.h>
#include <string.h>

#define DMR_RCTL_BURST_PAYLOAD   18                              /* = DMR_DATA_BURST_LEN */
#define DMR_RCTL_BURST_STRIDE    (1 + DMR_RCTL_BURST_PAYLOAD)    /* = BURST_STRIDE (dmr_sms_pdu.h) */

/* Покласти n-й запис черги: тип + 12 байт CSBK/даних, решта навантаження -- нулі (для типів, крім 0x80, драйвер читає лише перші 12 байтів). */
static inline void dmr_rctl_burst_put(uint8_t *q, int n, uint8_t typeByte, const uint8_t *p12)
{
	uint8_t *r = q + ((size_t)n * DMR_RCTL_BURST_STRIDE);

	r[0] = typeByte;
	memcpy(r + 1, p12, 12);
	memset(r + 13, 0, DMR_RCTL_BURST_PAYLOAD - 12);
}

#endif /* _OPENGD77_DMR_RCTL_BURST_H_ */
