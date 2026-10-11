/*
 * aprs_fault.h -- R10-fix4: обробник збою Cortex-M і програмний сторож для «Режиму APRS».
 *
 * НАВІЩО. Зависання маяка «Режиму APRS» (екран застигає на кроці трасування 402, передавач лишається увімкненим) не
 * вдавалося локалізувати: номер на екрані НЕ дорівнює місцю збою (екран відстає від коду), а стокові обробники
 * HardFault/BusFault/UsageFault/MemManage -- порожні цикли while(1). Тепер:
 *   1) будь-який збій (HardFault/MemManage/BusFault/UsageFault) ЗБЕРІГАЄ PC, LR, CFSR, HFSR, MMFAR/BFAR, SP, xPSR, R0 і
 *      адреси повернення зі стека в backup-регістри RTC (вони переживають програмне скидання), показує їх на екрані
 *      великими цифрами кількома сторінками і ПЕРЕЗАВАНТАЖУЄ рацію (передавач гасне);
 *   2) програмний сторож (TIM7, найвищий пріоритет -- не маскується критичними секціями FreeRTOS): якщо активний «Режим
 *      APRS» і головний цикл не відгукувався ~2 с -- зберігає, де застряло головне завдання, і перезавантажує рацію;
 *   3) після перезавантаження ПЕРЕД головним циклом показується звіт (кнопка -- наступна сторінка), потім запис стирається.
 * Адреси розшифровуються за .map ТОГО САМОГО коміту: tools/fault_lookup.py.
 *
 * Усе під APRS_RX (ENABLE_APRS_RX + українська збірка); у типовій збірці макроси порожні -- байт-у-байт стоковий OpenGD77.
 * RAM не додається: стан сторожа й останній крок трасування лежать у backup-регістрах RTC (RTC->BKP0R..BKP19R).
 */
#ifndef _OPENGD77_APRS_FAULT_H_
#define _OPENGD77_APRS_FAULT_H_

#include <stdint.h>
#include <stdbool.h>
#include "functions/aprs_rx_cfg.h"

#if defined(APRS_RX)

void aprsFaultInit(void);                    /* на старті головного завдання: доступ до BKP, TIM7 (сторож), дескриптор завдання */
bool aprsFaultBootReport(void);              /* показати збережений звіт про збій; true -- показано (екран треба перемалювати) */
void aprsFaultKick(void);                    /* «головний цикл живий» */
void aprsFaultArm(bool on);                  /* увімкнути/вимкнути сторож (вимикати перед вимкненням/сном рації!) */
void aprsFaultLoopTick(bool modeActive);     /* викликається щоітерації головного циклу: kick + арм/дизарм за станом режиму */
/* Запам'ятати крок трасування (backup-регістри); повертає мс від початку серії (для рядка t=). */
uint32_t aprsFaultTraceNote(uint32_t n, uint32_t v);
void aprsFaultTraceMark(void);               /* початок серії: t=0 (перед trxSetTX) */

#define APRS_FAULT_KICK()          aprsFaultKick()
#define APRS_FAULT_DISARM()        aprsFaultArm(false)
#define APRS_FAULT_LOOP(active)    aprsFaultLoopTick(active)

#else

#define APRS_FAULT_KICK()          ((void)0)
#define APRS_FAULT_DISARM()        ((void)0)
#define APRS_FAULT_LOOP(active)    ((void)0)

#endif /* APRS_RX */
#endif /* _OPENGD77_APRS_FAULT_H_ */
