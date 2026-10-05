/*
 * dmr_sms_pdu.c -- чиста побудова SMS-кадрів (див. dmr_sms_pdu.h).
 *
 * Функції контрольних сум і відкритого тексту перенесено з dmr_sms.c БЕЗ змін логіки
 * (звірено з 438ec23 -- ідентичні). Порожній модуль без ENABLE_AES + ENABLE_DMR_DATA.
 */
#include "functions/dmr_sms_pdu.h"

#if defined(ENABLE_DMR_DATA) && defined(ENABLE_AES)

#include "functions/dmr_sms.h"   /* DMR_SMS_TEXT_MAX */
#include "functions/dmr_sms_text.h" /* ui4: cp1251 -> UTF-16LE */
#include <string.h>

/* ============================ контрольні суми / CRC ====================== */
uint16_t dmrSmsPduIpCksum(const uint8_t *b, int len)
{
	uint32_t s = 0;
	for (int i = 0; i < len; i += 2)
	{
		s += ((uint32_t)b[i] << 8) | ((i + 1 < len) ? b[i + 1] : 0);
	}
	while (s >> 16) { s = (s & 0xFFFF) + (s >> 16); }
	return (uint16_t)(~s & 0xFFFF);
}

uint16_t dmrSmsPduCrc16(const uint8_t *data, int len)   /* CCITT, poly 0x1021, ^0xFFFF */
{
	uint16_t crc = 0;
	for (int i = 0; i < len; i++)
	{
		for (int k = 7; k >= 0; k--)
		{
			int bit = (data[i] >> k) & 1;
			if (((crc >> 15) & 1) ^ bit) { crc = (uint16_t)((crc << 1) ^ 0x1021); }
			else                         { crc = (uint16_t)(crc << 1); }
		}
	}
	return (uint16_t)(crc ^ 0xFFFF);
}

void dmrSmsPduHdrCrc(const uint8_t *h, int len, uint16_t mask, uint8_t out2[2])
{
	uint16_t v = (uint16_t)(dmrSmsPduCrc16(h, len) ^ mask);
	out2[0] = (uint8_t)(v >> 8); out2[1] = (uint8_t)(v & 0xFF);
}

/* CRC32 data-PDU: перестановка байтів у парах, поліном 0x04C11DB7, (len*8-32) бітів. */
uint32_t dmrSmsPduCrc32(const uint8_t *pdu, int len)
{
	uint32_t crc = 0;
	int nbits = len * 8 - 32;
	int bitno = 0;
	for (int i = 0; i + 1 < len; i += 2)
	{
		for (int pass = 0; pass < 2; pass++)
		{
			uint8_t byte = (pass == 0) ? pdu[i + 1] : pdu[i];
			for (int k = 7; k >= 0; k--)
			{
				if (bitno >= nbits) { goto done; }
				int bit = (byte >> k) & 1;
				if (((crc >> 31) & 1) ^ bit) { crc = (crc << 1) ^ 0x04C11DB7; }
				else                         { crc = (crc << 1); }
				bitno++;
			}
		}
	}
done:
	/* byte-reverse to wire order */
	return ((crc & 0xFF) << 24) | ((crc & 0xFF00) << 8) | ((crc >> 8) & 0xFF00) | ((crc >> 24) & 0xFF);
}

/* Програмна перевірка CRC заголовка (див. dmr_sms_pdu.h). Навіщо: апаратний прапорець CRC
 * HR-C6000 для відповіді, що приходить одразу після нашої передачі, буває хибно «невалідним»
 * (так було з квитанцією RCTL-CSBK); тоді рішення приймаємо самі, за тими самими байтами. */
int dmrSmsPduHdrCrcOk(const uint8_t p12[12], uint16_t mask)
{
	uint8_t c[2];
	dmrSmsPduHdrCrc(p12, 10, mask, c);
	return (c[0] == p12[10]) && (c[1] == p12[11]);
}

/* ============================ відкритий текст ============================ */
/* IPv4/UDP/TMS відкритий текст у out (>=160 Б). Повертає довжину. */
int dmrSmsPduBuildPlaintext(const char *text, int tlen, uint32_t src, uint32_t dst, int group,
                           uint8_t seq, uint16_t ipid, uint8_t *out)
{
	uint8_t tms[16 + 2 * DMR_SMS_TEXT_MAX];
	int L = tlen * 2;            /* UTF-16LE byte count */
	int ti = 0;
	tms[ti++] = (uint8_t)((8 + L) >> 8); tms[ti++] = (uint8_t)(8 + L);   /* 2-byte TMS length */
	tms[ti++] = 0xA0; tms[ti++] = 0x00; tms[ti++] = seq; tms[ti++] = 0x04;
	tms[ti++] = 0x0D; tms[ti++] = 0x00;   /* fixed CRLF header (stock uses 0d/0a here, NOT L+3/L) */
	tms[ti++] = 0x0A; tms[ti++] = 0x00;
	/* ui4: текст рації -- cp1251 (1 байт = 1 символ); в ефір -- UTF-16LE. Раніше кожен байт
	 * ішов як U+00xx, тож кирилиця виходила латиницею-1. ASCII -- побайтово як і раніше. */
	for (int i = 0; i < tlen; i++)
	{
		uint16_t u = dmrSmsCp1251ToUcs2((uint8_t)text[i]);
		tms[ti++] = (uint8_t)u; tms[ti++] = (uint8_t)(u >> 8);
	}

	int udpLen = 8 + ti;
	/* MotoTRBO CAI IP = prefix.<id[23:16]>.<id[15:8]>.<id[7:0]> — the FULL 24-bit DMR ID/TG.
	 * (Byte 1 was hardcoded 0x00, truncating to 16 bits; correct only for ids <= 65535, wrong
	 * for real 7-digit DMR ids.) src = individual radio (12.x.x.x), group dst = 225.x.x.x.
	 * ui4: приватний dst -- теж 12.x.x.x, як шле стокова (запис BBD_0004: 12.38.234.41 ->
	 * 12.38.234.15); раніше dst завжди був 225.x. Псевдозаголовок UDP бере той самий dstIp. */
	uint8_t srcIp[4] = { 0x0C, (uint8_t)(src >> 16), (uint8_t)(src >> 8), (uint8_t)src };
	uint8_t dstIp[4] = { group ? 0xE1 : 0x0C, (uint8_t)(dst >> 16), (uint8_t)(dst >> 8), (uint8_t)dst };

	uint8_t udp[8 + 16 + 2 * DMR_SMS_TEXT_MAX];
	udp[0] = UDP_SMS_PORT >> 8; udp[1] = UDP_SMS_PORT & 0xFF;
	udp[2] = UDP_SMS_PORT >> 8; udp[3] = UDP_SMS_PORT & 0xFF;
	udp[4] = (uint8_t)(udpLen >> 8); udp[5] = (uint8_t)udpLen; udp[6] = 0; udp[7] = 0;
	memcpy(udp + 8, tms, ti);

	/* UDP checksum (pseudo-header) */
	{
		uint8_t pseudo[12 + 8 + 16 + 2 * DMR_SMS_TEXT_MAX];
		int p = 0;
		memcpy(pseudo + p, srcIp, 4); p += 4;
		memcpy(pseudo + p, dstIp, 4); p += 4;
		pseudo[p++] = 0; pseudo[p++] = 0x11;
		pseudo[p++] = (uint8_t)(udpLen >> 8); pseudo[p++] = (uint8_t)udpLen;
		memcpy(pseudo + p, udp, udpLen); p += udpLen;
		if (p & 1) { pseudo[p++] = 0; }
		uint16_t uc = dmrSmsPduIpCksum(pseudo, p);
		if (uc == 0) { uc = 0xFFFF; }
		udp[6] = (uint8_t)(uc >> 8); udp[7] = (uint8_t)uc;
	}

	int totLen = 20 + udpLen;
	uint8_t *ip = out;
	ip[0] = 0x45; ip[1] = 0x00; ip[2] = (uint8_t)(totLen >> 8); ip[3] = (uint8_t)totLen;
	ip[4] = (uint8_t)(ipid >> 8); ip[5] = (uint8_t)ipid; ip[6] = 0; ip[7] = 0;
	ip[8] = 0x40; ip[9] = 0x11; ip[10] = 0; ip[11] = 0;
	memcpy(ip + 12, srcIp, 4); memcpy(ip + 16, dstIp, 4);
	uint16_t ic = dmrSmsPduIpCksum(ip, 20);
	ip[10] = (uint8_t)(ic >> 8); ip[11] = (uint8_t)ic;
	memcpy(out + 20, udp, udpLen);
	return totLen;
}

int dmrSmsPduAppendBurst(uint8_t *q, int n, uint8_t typeByte, const uint8_t *payload, int plen)
{
	q[n * BURST_STRIDE + 0] = typeByte;
	memset(q + n * BURST_STRIDE + 1, 0, DMR_DATA_BURST_LEN);
	memcpy(q + n * BURST_STRIDE + 1, payload, (size_t)plen);
	return n + 1;
}

/* ============================ режим 0: Без підтвердження ================= */
/* ДОСЛІВНО шлях dmrSmsSend() з 438ec23 (останній, що працював у полі до CONFIRMED):
 * pdu = ct + нулі(poc) + CRC32, вирівняно так, щоб (ct+4) заповнило цілі 12-байтні блоки;
 * 6 CSBK-преамбул, Unconfirmed data header (DPF=2, o9=0x00), [ENC ext header],
 * сирі 12-байтні rate-1/2 блоки БЕЗ DBSN/CRC9. Відмінність від 438ec23 лише у
 * розмітці черги: stride BURST_STRIDE (19) замість 13 -- у чип іде ті самі 12 байт
 * (HR-C6000.c: для типу 0x70 plen = LC_DATA_LENGTH = 12), хвіст stride нульовий.
 * Еталон байт-у-байт -- tests/test_dmr_sms_unconf.c. */
int dmrSmsPduBuildUnconf(uint8_t *q, int maxBursts, const uint8_t *ct, int ctLen,
                         uint32_t src, uint32_t dst, int group, int encrypt, uint8_t keyId)
{
	int totalData = (((ctLen + 4) + 11) / 12) * 12;
	int poc = totalData - ctLen - 4;
	uint8_t pdu[384];
	if (totalData > (int)sizeof pdu) { return -4; }
	memcpy(pdu, ct, ctLen);
	memset(pdu + ctLen, 0, poc);
	memset(pdu + totalData - 4, 0, 4);                 /* місце поля CRC32 -- нулі */
	uint32_t crc = dmrSmsPduCrc32(pdu, totalData);
	pdu[totalData - 4] = (uint8_t)(crc >> 24); pdu[totalData - 3] = (uint8_t)(crc >> 16);
	pdu[totalData - 2] = (uint8_t)(crc >> 8);  pdu[totalData - 1] = (uint8_t)crc;
	int nDataBlocks = totalData / 12;
	int nblocks = (encrypt ? 1 : 0) + nDataBlocks;     /* +1 ENC ext header лише при шифруванні */

	int n = 0;
	int preamble = 6;
	int tail = (encrypt ? 2 : 1) + nDataBlocks;        /* заголовки (Unconfirmed [+ ENC]) + блоки після CSBK */
	uint8_t g = group ? 0x80 : 0x00;
	uint8_t gc = group ? 0xC0 : 0x80;
	for (int i = 0; i < preamble; i++)
	{
		uint8_t body[10];
		body[0] = 0xBD; body[1] = 0x00; body[2] = gc; body[3] = (uint8_t)((preamble - 1 - i) + tail);
		body[4] = (uint8_t)(dst >> 16); body[5] = (uint8_t)(dst >> 8); body[6] = (uint8_t)dst;
		body[7] = (uint8_t)(src >> 16); body[8] = (uint8_t)(src >> 8); body[9] = (uint8_t)src;
		uint8_t p12[12]; memcpy(p12, body, 10); dmrSmsPduHdrCrc(body, 10, 0xA5A5, p12 + 10);
		if (n >= maxBursts) { return -5; }
		n = dmrSmsPduAppendBurst(q, n, DTB_CSBK, p12, 12);
	}
	/* Unconfirmed data header. SAP 09 [EXTD HDR] при шифруванні (далі йде ENC ext header);
	 * SAP 04 [IP] для чистого тексту -- стокова TYT відкидає SAP09 без розширеного
	 * заголовка (декодовано з ефірного запису стокової, 2026-07-04). */
	{
		uint8_t h[10];
		h[0] = (uint8_t)(g | 0x02); h[1] = (uint8_t)(((encrypt ? 9 : 4) << 4) | (poc & 0x0F));
		h[2] = (uint8_t)(dst >> 16); h[3] = (uint8_t)(dst >> 8); h[4] = (uint8_t)dst;
		h[5] = (uint8_t)(src >> 16); h[6] = (uint8_t)(src >> 8); h[7] = (uint8_t)src;
		h[8] = (uint8_t)(0x80 | (nblocks & 0x7F)); h[9] = 0x00;
		uint8_t p12[12]; memcpy(p12, h, 10); dmrSmsPduHdrCrc(h, 10, 0xCCCC, p12 + 10);
		if (n >= maxBursts) { return -5; }
		n = dmrSmsPduAppendBurst(q, n, DTB_DATA_HEADER, p12, 12);
	}
	/* ENC extended header (SAP04 IP, MFID Moto, ALG05 AES256, key id, MI=0) -- лише шифроване */
	if (encrypt)
	{
		uint8_t e[10] = { 0x4F, 0x10, 0x51, keyId, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00 };
		uint8_t p12[12]; memcpy(p12, e, 10); dmrSmsPduHdrCrc(e, 10, 0xCCCC, p12 + 10);
		if (n >= maxBursts) { return -5; }
		n = dmrSmsPduAppendBurst(q, n, DTB_DATA_HEADER, p12, 12);
	}
	/* rate-1/2 блоки: сирі 12 байт PDU */
	for (int b = 0; b < nDataBlocks; b++)
	{
		if (n >= maxBursts) { return -5; }
		n = dmrSmsPduAppendBurst(q, n, DTB_RATE12_DATA, pdu + b * 12, 12);
	}
	return n;
}

/* ============================ квитанція ================================== */
/* Response data header (DPF=1), SAP=4 (IP), BF=0.
 * o9 = Class(2 біти, 7-6)=00 | Type(3, 5-3)=001 (ACK) | Status(3, 2-0)=N(S) відправника.
 * (b7eedd6 помилково писав N(S) у біти 6-4 -- це ламало Class/Type, напр. N(S)=3 -> 0x38.) */
void dmrSmsPduAckHeader(uint32_t to, uint32_t from, uint8_t ns, uint8_t out12[12])
{
	uint8_t h[10];
	h[0] = 0x01; h[1] = 0x40;                          /* Response, SAP=4 IP */
	h[2] = (uint8_t)(to >> 16);   h[3] = (uint8_t)(to >> 8);   h[4] = (uint8_t)to;
	h[5] = (uint8_t)(from >> 16); h[6] = (uint8_t)(from >> 8); h[7] = (uint8_t)from;
	h[8] = 0x00;                                       /* Blocks-to-Follow = 0 */
	h[9] = (uint8_t)(0x08 | (ns & 7));                 /* ACK, Status = N(S) */
	memcpy(out12, h, 10);
	dmrSmsPduHdrCrc(h, 10, 0xCCCC, out12 + 10);
}

/* Черга квитанції (див. dmr_sms_pdu.h). Преамбула: BD 00 80 <лишилось burst-ів> <до> <від>,
 * CRC ^ 0xA5A5 -- та сама, що перед звичайним повідомленням. */
int dmrSmsPduBuildAckQueue(uint8_t *q, int maxBursts, uint32_t to, uint32_t from, uint8_t ns,
                           int preambles, int repeats)
{
	uint8_t p12[12];
	dmrSmsPduAckHeader(to, from, ns, p12);
	if ((preambles < 0) || (repeats < 0) || ((preambles + repeats) > maxBursts)) { return -5; }
	int n = 0;
	for (int i = 0; i < preambles; i++)
	{
		uint8_t body[10];
		body[0] = 0xBD; body[1] = 0x00; body[2] = 0x80;   /* індивідуальна data-преамбула */
		body[3] = (uint8_t)((preambles - 1 - i) + repeats);
		body[4] = (uint8_t)(to >> 16);   body[5] = (uint8_t)(to >> 8);   body[6] = (uint8_t)to;
		body[7] = (uint8_t)(from >> 16); body[8] = (uint8_t)(from >> 8); body[9] = (uint8_t)from;
		uint8_t pb[12]; memcpy(pb, body, 10); dmrSmsPduHdrCrc(body, 10, 0xA5A5, pb + 10);
		n = dmrSmsPduAppendBurst(q, n, DTB_CSBK, pb, 12);
	}
	for (int i = 0; i < repeats; i++)
	{
		n = dmrSmsPduAppendBurst(q, n, DTB_DATA_HEADER, p12, 12);
	}
	return n;
}

int dmrSmsPduNextAckPause(int ms)
{
	return (ms == 80) ? 50 : ((ms == 50) ? 20 : 80);
}

int dmrSmsPduUseFastEnd(int txMode, int fastEndFlag)
{
	return ((txMode == 1) || (txMode == 2)) && (fastEndFlag != 0);
}

#endif /* ENABLE_DMR_DATA && ENABLE_AES */
