/*
 * dmr_sms_pdu.h -- чиста (без заліза) побудова SMS-кадрів: контрольні суми, IPv4/UDP/TMS,
 * черга burst-ів режиму «Без підтвердження», заголовок-квитанція.
 *
 * НАВІЩО ОКРЕМИЙ ФАЙЛ (2026-09-30). Хостові тести раніше КОПІЮВАЛИ цей код у себе й
 * перевіряли копію -- а прошивка тим часом могла розійтися з нею непомітно. Тепер
 * tests/test_dmr_sms_unconf.c і tests/test_dmr_sms_ack.c лінкують САМЕ цей файл, тож
 * перевіряється той код, що йде в рацію. Тут немає звертань до trx/codeplug/HR-C6000.
 *
 * Лише під ENABLE_DMR_DATA + ENABLE_AES -- типова збірка не змінюється.
 */
#ifndef _OPENGD77_DMR_SMS_PDU_H_
#define _OPENGD77_DMR_SMS_PDU_H_

#include <stdint.h>

#if defined(ENABLE_DMR_DATA) && defined(ENABLE_AES)

#include "functions/dmr_data.h"   /* DMR_DATA_BURST_LEN */

/* Тип burst-а в черзі dmrDataTxLoad() (старший ніббл = тип даних слота для HR-C6000). */
#define DTB_CSBK         0x30
#define DTB_DATA_HEADER  0x60
#define DTB_RATE12_DATA  0x70
#define DTB_RATE34_DATA  0x80   /* rate-3/4 CONFIRMED data block (18-байтне навантаження) */

#define UDP_SMS_PORT     0x0FA7 /* 4007, src==dst, стокова TYT */

/* Черга burst-ів: 1 байт типу + DMR_DATA_BURST_LEN (18) байтів навантаження. */
#define BURST_STRIDE     (1 + DMR_DATA_BURST_LEN)

uint16_t dmrSmsPduIpCksum(const uint8_t *b, int len);
uint16_t dmrSmsPduCrc16(const uint8_t *data, int len);      /* CCITT, poly 0x1021, ^0xFFFF */
void     dmrSmsPduHdrCrc(const uint8_t *h, int len, uint16_t mask, uint8_t out2[2]);
/* CRC32 data-PDU: len ВКЛЮЧАЄ 4 байти поля CRC (обробляється len*8-32 бітів). */
uint32_t dmrSmsPduCrc32(const uint8_t *pdu, int len);
/* IPv4/UDP/TMS відкритий текст у out (>= 360 Б). Повертає довжину. */
int      dmrSmsPduBuildPlaintext(const char *text, int tlen, uint32_t src, uint32_t dst,
                                 uint8_t seq, uint16_t ipid, uint8_t *out);
/* Додати burst у чергу; решта stride обнуляється. Повертає n+1. */
int      dmrSmsPduAppendBurst(uint8_t *q, int n, uint8_t typeByte, const uint8_t *payload, int plen);

/* Режим 0 «Без підтвердження»: РІВНО той шлях, що працював у полі до CONFIRMED (438ec23):
 * 6 CSBK + Unconfirmed-заголовок (DPF=2, o9=0x00) [+ ENC] + сирі 12-байтні rate-1/2 блоки
 * без DBSN/CRC9, CRC32 в останніх 4 байтах. ct -- вже зашифрований (або чистий) текст.
 * Повертає кількість burst-ів або <0: -4 задовге, -5 не влізло в maxBursts. */
int      dmrSmsPduBuildUnconf(uint8_t *q, int maxBursts, const uint8_t *ct, int ctLen,
                              uint32_t src, uint32_t dst, int group, int encrypt, uint8_t keyId);

/* Response data header (link-layer ACK) на CONFIRMED-повідомлення, 12 Б з CRC.
 * o9 = Class(7-6)=00 | Type(5-3)=001 | Status(2-0)=N(S) відправника. */
void     dmrSmsPduAckHeader(uint32_t to, uint32_t from, uint8_t ns, uint8_t out12[12]);

#endif /* ENABLE_DMR_DATA && ENABLE_AES */
#endif /* _OPENGD77_DMR_SMS_PDU_H_ */
