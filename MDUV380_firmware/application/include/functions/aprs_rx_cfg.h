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

/* R18: видалення повідомлень (Д1) -- APRS_R18_UI. У R18 його (разом з картками й піктограмами) було вирізано з діагностичної збірки (ENABLE_APRS_RX_PROBE):
 * до фіксованої адреси кодека 0x0807537C не вистачало ~0,9 КБ. R20 Ж3: після вилучення тік-трасування (R17) і пулу піктограм «A» видалення ПОВЕРНУТО в
 * обидві збірки (APRS_R18_UI = ENABLE_APRS_RX). */
#if defined(ENABLE_APRS_RX)
#define APRS_R18_UI 1
#endif
/* R20 Ж3: картки підтверджень (Д6) і позивний на «Переслухати» (Д10) -- APRS_R18_CARDS, найменш пріоритетні (порядок за брифом: піктограми ->
 * видалення -> картки). Піктограми й видалення повернуто в diag, картки лишились лише в user: з ними запас diag до кодека 1932 Б (< 2048), без них 2332 Б
 * (виміряно, STATUS.md, розділ R20). */
#if defined(ENABLE_APRS_RX) && !defined(ENABLE_APRS_RX_PROBE)
#define APRS_R18_CARDS 1
#endif

/* R21 З4: QSY у коментарі маяка (складач, перемикач у «Налаштуваннях») -- APRS_R21_QSY, лише в користувацькій збірці (як APRS_R18_CARDS): коштує 736 Б
 * флешу, і запас diag до кодека (2148 Б) упав би до 1412 Б (< 2048). У diag маяк іде без QSY; формат блоку налаштувань однаковий в обох збірках
 * (біт qsyOff зберігається, щоб diag не скидав вибір user). */
#if defined(ENABLE_APRS_RX) && !defined(ENABLE_APRS_RX_PROBE)
#define APRS_R21_QSY 1
#endif

/* R10-fix -> R12: трасування «Режиму APRS» на екран (великий номер кроку + негайний рендер, пауза ~30 мс на кадр): після
 * зависання на екрані лишається номер останнього кроку, який почався (таблиця номерів -- TESTING.md, блок AO). Причину
 * зависання знайдено й виправлено (R10-fix5, підтверджено на залізі), тож З R12 трасування лишається ЛИШЕ в діагностичній
 * збірці (ENABLE_APRS_RX_PROBE, «uadiag»); у користувацькій (ENABLE_APRS_RX) його НЕМАЄ -- ні коду, ні пауз у передачі.
 * Екран збою HardFault/сторожа (aprs_fault.c) лишається в ОБОХ збірках назавжди. Без APRS_RX -- порожні макроси (нуль коду).
 * Додатково вимикається прапорцем APRS_MODE_NO_TRACE (хост-тести).
 *   AM_TRACE(n)   -- безумовно (вхід, вихід, маяк: рідкісні події);
 *   AM_TRACE_T(n) -- лише коли режим активний і лише ПЕРШИЙ раз після входу/маяка (тіки: інакше затопило б екран). */
#if defined(APRS_RX) && defined(ENABLE_APRS_RX_PROBE) && !defined(APRS_MODE_NO_TRACE)
#define APRS_MODE_TRACE 1
void aprsModeTrace(unsigned int n);
void aprsModeTraceT(unsigned int n);
void aprsModeTraceV(unsigned int n, unsigned int v);   /* номер + додаткове значення (R10-fix2) */
void aprsModeTraceH(unsigned int n, unsigned long v);   /* номер + значення в hex, напр. адреса (R10-fix3) */
void aprsModeTraceMark(void);                            /* мітка часу початку передачі для рядка t= (R10-fix3) */
#define AM_TRACE(n)    aprsModeTrace(n)
#define AM_TRACE_V(n, v)  aprsModeTraceV((n), (unsigned int)(v))
#define AM_TRACE_H(n, v)  aprsModeTraceH((n), (unsigned long)(v))
#define AM_TRACE_MARK()   aprsModeTraceMark()
#if defined(APRS_FRAME_TRACE)
#define AM_TRACE_T(n)  aprsModeTraceT(n)
#else
/* R17: тік-трасування (60..91) за замовчуванням ВИМКНЕНО: зависання APRS закрито (R10-fix5), а ці виклики разом із трасуванням кадру (aprs.c)
 * не дають діагностичній збірці вміститися до фіксованої адреси кодека. -DAPRS_FRAME_TRACE повертає. */
#define AM_TRACE_T(n)  ((void)0)
#endif
#else
#define AM_TRACE(n)    ((void)0)
#define AM_TRACE_V(n, v)  ((void)0)
#define AM_TRACE_H(n, v)  ((void)0)
#define AM_TRACE_MARK()   ((void)0)
#define AM_TRACE_T(n)  ((void)0)
#endif

#endif /* _OPENGD77_APRS_RX_CFG_H_ */
