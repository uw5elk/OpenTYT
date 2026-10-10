/*
 * aprs_demod_cli.c -- хостовий запуск ТОГО САМОГО демодулятора, що в прошивці
 * (application/source/functions/aprs_afsk.c + aprs_probe_dsp.c), на файлі сирих відліків.
 * Збирає й викликає tools/aprs_offline.py; вручну:
 *
 *   cc -O2 -DENABLE_APRS_RX_PROBE -Iapplication/include -o aprs_demod_cli tools/aprs_demod_cli.c \
 *      application/source/functions/aprs_afsk.c application/source/functions/aprs_probe_dsp.c -lm
 *   ./aprs_demod_cli файл.s16 [--notch Гц] [--fs Гц] [--auto-notch]
 *
 * Вхід: int16 LE, моно, 8000 Гц. Вихід (рядки для розбору python-скриптом):
 *   OK <довжина> <SRC>DST> <info>      -- кадр з правильним FCS
 *   BAD <довжина> <hex перших 16> <адреси як є>
 *   SUMMARY ok=N bad=N flagseq=N notch=Гц
 *   PLL h0 h1 ... h7
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "functions/aprs_afsk.h"

static int s_ok, s_bad;

static void onFrame(const uint8_t *f, uint16_t len, bool ok, void *ctx)
{
	(void)ctx;
	if (ok)
	{
		char sd[24], info[64];
		s_ok++;
		if (!ax25Summary(f, len, sd, sizeof(sd), info, sizeof(info)))
		{
			strcpy(sd, "?");
			info[0] = 0;
		}
		printf("OK %u %s %s\n", (unsigned)len, sd, info);
	}
	else
	{
		char la[24];
		s_bad++;
		printf("BAD %u ", (unsigned)len);
		for (int i = 0; i < 16 && i < len; i++)
		{
			printf("%02X", f[i]);
		}
		ax25LooseAddr(f, (len < 16) ? len : 16, la, sizeof(la));
		printf(" %s\n", la[0] ? la : "-");
	}
}

int main(int argc, char **argv)
{
	if (argc < 2)
	{
		fprintf(stderr, "usage: %s file.s16 [--notch Hz] [--fs Hz] [--auto-notch]\n", argv[0]);
		return 2;
	}
	float notch = 0.0f;
	unsigned fs = 0;
	int autoNotch = 0;
	for (int i = 2; i < argc; i++)
	{
		if (!strcmp(argv[i], "--notch") && i + 1 < argc) { notch = (float)atof(argv[++i]); }
		else if (!strcmp(argv[i], "--fs") && i + 1 < argc) { fs = (unsigned)atoi(argv[++i]); }
		else if (!strcmp(argv[i], "--auto-notch")) { autoNotch = 1; }
	}
	FILE *f = fopen(argv[1], "rb");
	if (!f)
	{
		perror(argv[1]);
		return 2;
	}
	static afskDemod_t d;
	static apBg_t bg;
	afskInit(&d, onFrame, NULL);
	if (fs) { afskSetSampleRate(&d, fs); }
	afskSetNotchHz(&d, notch);
	apBgInit(&bg);

	int16_t blk[160];
	unsigned flagSeq = 0;
	int quiet = 1000;
	float curNotch = notch;
	size_t n;
	while ((n = fread(blk, sizeof(int16_t), 160, f)) > 0)
	{
		afskProcess(&d, blk, (int)n);
		if (d.nFlagSeq) { flagSeq += d.nFlagSeq; d.nFlagSeq = 0; quiet = 0; } else if (quiet < 1000) { quiet++; }
		if (autoNotch && n == 160)
		{
			apBgResult_t r;
			/* як у прошивці: режекція з розгортки фону, лише поза пакетами */
			if (apBgBlock(&bg, blk, &r) && quiet >= 100 && !d.inFrame)
			{
				float hz = apBgNotchHz(&r);
				if ((int)(hz + 0.5f) != (int)(curNotch + 0.5f)) { afskSetNotchHz(&d, hz); curNotch = hz; }
			}
		}
	}
	fclose(f);
	printf("SUMMARY ok=%d bad=%d flagseq=%u notch=%.1f\n", s_ok, s_bad, flagSeq, (double)curNotch);
	printf("PLL");
	for (int i = 0; i < 8; i++) { printf(" %u", d.pllHist[i]); }
	printf("\n");
	return 0;
}
