/*
 * aprs_rx_cfg.h -- перемикачі збірки прийому APRS (R8). Єдине місце, де зведено прапорці.
 *
 *   ENABLE_APRS_RX        -- справжній фоновий приймач APRS (aprs_rx.c): користувацька українська
 *                            збірка CI. DSP (aprs_afsk.c, aprs_probe_dsp.c) і розбір пакетів
 *                            (aprs_rx_parse.c) збираються під ним.
 *   ENABLE_APRS_RX_PROBE  -- діагностичний екран «APRS проба» (R2-R7); ВКЛЮЧАЄ приймач: діагностична
 *                            збірка має і пробу, і приймач (приймач на час проби призупиняється).
 *   APRS_RX               -- інтеграція в прошивку (екран, банер, I2S): лише українська збірка, як і
 *                            в проби (рядки -- languages/aprsrx_ua.h, cp1251).
 *
 * Без жодного з прапорців нічого з цього не збирається: типова збірка -- байт-у-байт стоковий OpenGD77.
 */
#ifndef _OPENGD77_APRS_RX_CFG_H_
#define _OPENGD77_APRS_RX_CFG_H_

#if defined(ENABLE_APRS_RX_PROBE) && !defined(ENABLE_APRS_RX)
#define ENABLE_APRS_RX
#endif

#if defined(ENABLE_APRS_RX) && defined(LANGUAGE_BUILD_UKRAINIAN)
#define APRS_RX 1
#endif

#endif /* _OPENGD77_APRS_RX_CFG_H_ */
