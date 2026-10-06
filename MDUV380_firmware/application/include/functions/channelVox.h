/*
 * channelVox.h -- чи доступний VOX для каналу (ui8, форк).
 *
 * Стоковий OpenGD77 (menuChannelDetails.c) показує VOX лише для цифрового каналу або каналу без
 * APRS-конфігу (на аналоговому APRS-каналі -- «Н/Д»: VOX і бікон у хвості передачі несумісні),
 * але обробники вправо/вліво ставили/знімали CHANNEL_FLAG_VOX без цієї перевірки -- прапорець
 * мінявся, хоча на екрані «Н/Д». Тепер умова одна для показу й обох обробників.
 *
 * Чиста функція без заліза -- хостовий тест tests/test_channel_vox.c. Лише під ENABLE_AES
 * (типова збірка -- стоковий апстрім без змін).
 */
#ifndef _OPENGD77_CHANNEL_VOX_H_
#define _OPENGD77_CHANNEL_VOX_H_

#include <stdbool.h>
#include <stdint.h>

#if defined(ENABLE_AES)
static inline bool channelVoxIsAllowed(bool isDigital, uint8_t aprsConfigIndex)
{
	return isDigital || (aprsConfigIndex == 0);
}
#endif

#endif /* _OPENGD77_CHANNEL_VOX_H_ */
