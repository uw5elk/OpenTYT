/*
 * test_channel_vox.c -- ui8: умова «VOX доступний» (functions/channelVox.h), спільна для показу
 * пункту VOX у деталях каналу і обох обробників (вправо/вліво) у menuChannelDetails.c.
 */
#include <stdio.h>
#include "functions/channelVox.h"

static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

int main(void)
{
	printf("test_channel_vox:\n");
	CHECK(channelVoxIsAllowed(false, 0) == true,  "аналоговий без APRS -- VOX доступний");
	CHECK(channelVoxIsAllowed(false, 1) == false, "аналоговий з APRS-конфігом 1 -- «Н/Д», не змінюється");
	CHECK(channelVoxIsAllowed(false, 255) == false, "аналоговий з APRS-конфігом 255 -- «Н/Д»");
	CHECK(channelVoxIsAllowed(true, 0) == true,   "цифровий без APRS -- доступний");
	CHECK(channelVoxIsAllowed(true, 3) == true,   "цифровий з APRS -- доступний (бікон іде окремо, не в хвості FM)");
	printf(fails ? "ПРОВАЛЕНО: %d\n" : "ПРОЙДЕНО\n", fails);
	return fails ? 1 : 0;
}
