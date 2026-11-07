/* icon_fw_dump.c -- допоміжна програма tools/test_r70.py (R70 B6): для КОЖНОЇ пари байтів слота APRS (таблиця 0..1, індекс 0..93) проганяє її РЕАЛЬНИМ кодом
 * aprs_mode_cfg.c (типові значення з слота -> ефективні -> структура для aprsSendPacket) і друкує, що піде в ефір за правилом aprs.c:581-582
 * (`symbol = iconIndex + '!'`, `symTable = iconTable == 0 ? '/' : '\\'`; ці два рядки test_r70.py окремо звіряє з вихідним текстом aprs.c).
 * Вивід: "<table_raw> <index_raw> <stock_table_ascii> <stock_code> <mode_table_ascii> <mode_code>" -- stock = правило aprs.c для сирих байтів слота;
 * mode = те саме для того, що дає «Режим APRS» (aprsModeToBeaconCfg). */
#include <stdio.h>
#include <string.h>
#include "functions/aprs_mode_cfg.h"

int main(void)
{
	for (unsigned t = 0; t <= 1; t++)
	{
		for (unsigned i = 0; i <= 93; i++)
		{
			aprsModeRawCfg_t raw;
			aprsModeDefaults_t d;
			aprsModeCfg_t c;
			aprsModeEff_t e;
			aprsModeRawCfg_t out;

			memset(&raw, 0, sizeof(raw));
			raw.iconTable = (uint8_t)t;
			raw.iconIndex = (uint8_t)i;
			memset(&c, 0, sizeof(c));
			aprsModeDefaultsBuild(&d, &raw, true, "UW5ELK", false, 0, 0);
			aprsModeEffective(&c, &d, &e);
			aprsModeToBeaconCfg(&e, &out);
			printf("%u %u %c %u %c %u\n", t, i, (raw.iconTable == 0) ? '/' : '\\', (unsigned)(uint8_t)(raw.iconIndex + '!'),
					(out.iconTable == 0) ? '/' : '\\', (unsigned)(uint8_t)(out.iconIndex + '!'));
		}
	}
	return 0;
}
