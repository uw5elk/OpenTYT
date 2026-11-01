/*
 * wake_hop.h -- R58: ПРОТОТИП «перехід на інший канал під утримуваним PTT» (лише діагностична збірка).
 *
 * Перевіряє гіпотезу R57: чи прокидає ретранслятор рація, яку перекинули на сусідній цифровий
 * канал зони, не відпускаючи PTT. Не готова функція: максимум 2 стрибки, лише наступний канал
 * поточної зони по колу, один оберт. Компілюється лише з -DENABLE_WAKE_HOP_TEST (потребує
 * ENABLE_WAKE_DIAG -- без журналу стрибок не виміряти; Makefile це перевіряє). Без дефайна файл
 * порожній, а виклики в uiTxScreen.c загорнуті в той самий #if -- типова збірка байт-у-байт та сама.
 *
 * Розділення: wake_hop_sel.c -- чиста логіка вибору кандидата (без заліза, тестується на хості);
 * wake_hop.c -- клей до кодплагу/трансівера/ UI (лише задача UI, не ISR).
 */
#ifndef FUNCTIONS_WAKE_HOP_H_
#define FUNCTIONS_WAKE_HOP_H_

#include <stdint.h>
#include <stdbool.h>

#if defined(ENABLE_WAKE_HOP_TEST)

#define WAKE_HOP_MAX_HOPS    2U     /* стрибків за одне утримання PTT */
#define WAKE_HOP_SCAN_CAP   64U     /* скільки позицій кільця переглянути, шукаючи придатний канал */

/* Ознаки каналу-кандидата, які перевіряє вибір (клей заповнює їх із запису кодплагу). */
typedef struct
{
	bool     digital;     /* chMode == RADIO_MODE_DIGITAL */
	bool     forceDmo;    /* CHANNEL_FLAG_FORCE_DMO */
	bool     rxOnly;      /* CHANNEL_FLAG_RX_ONLY */
	bool     txAllowed;   /* txFreqLimited / аматорський діапазон дозволяє передачу */
	bool     inBand;      /* RX і TX не поза діапазоном трансівера */
	bool     inhibited;   /* dmrRctlIsInhibited() -- віддалене блокування */
	uint32_t rxFreq;
	uint32_t txFreq;
} wakeHopChan_t;

/* Чи придатний канал для стрибка: цифровий, не DMO/FORCE_DMO (симплекс), не лише-приймання,
 * передача дозволена, у діапазоні, не заблокований, rx != tx (ретрансляторний зсув). */
bool wakeHopChannelUsable(const wakeHopChan_t *c);

/* Чи можна ще стрибати (hopsDone вже зроблено). */
bool wakeHopMayHop(uint8_t hopsDone);

/* Позиція кільця на k кроків від start (count > 0; k може бути більшим за count). */
unsigned wakeHopRingPos(unsigned start, unsigned count, unsigned k);

/* Колбек перевірки позиції кільця: true -- придатна. */
typedef bool (*wakeHopUsableFn)(unsigned pos, void *ctx);

/* Шукає наступну придатну позицію після start (кроки 1..min(count-1, WAKE_HOP_SCAN_CAP)) -- не
 * більше одного оберту, саму стартову позицію не повертає. true і *outPos -- знайдено. */
bool wakeHopFindNext(unsigned start, unsigned count, wakeHopUsableFn fn, void *ctx, unsigned *outPos);

/* ---- клей (wake_hop.c) -- лише для прошивки, не для хостового тесту ---- */
#if !defined(WAKE_HOP_HOST_TEST)
void wakeHopBegin(void);     /* на початку екрана передачі: скинути лічильник, зберегти вихідний канал */
bool wakeHopTry(void);       /* спроба стрибка; true -- перейшли на новий канал, пробудження перезапущено */
void wakeHopRestore(void);   /* у кінці передачі: повернути вихідний канал, якщо були на іншому */

/* Реалізація -- у HR-C6000.c. Оголошено ТУТ, а не в HR-C6000.h: той заголовок підключає пів прошивки, і зміна в ньому
 * міняла б токени невідомих цьому прототипу файлів у діагностичній конфігурації (tools/test_r46.py W5, test_r47.py V2). */
void HRC6000RestartWakeForRoam(void);
#endif

#endif /* ENABLE_WAKE_HOP_TEST */

#endif /* FUNCTIONS_WAKE_HOP_H_ */
