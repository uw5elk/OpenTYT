/*
 * wake_hop.h -- R59: «Роумінг»: автоперехід на наступний канал зі списку роумінгу, коли ретранслятор не відповідає
 * на пробудження під УТРИМУВАНИМ PTT (з R58-прототипу «стрибка на сусідній канал»).
 *
 * Список роумінгу -- канали кодплагу з прапорцем CHANNEL_FLAG_ROAMING (будь-яких зон, у порядку номерів,
 * по колу від поточного). Працює лише якщо ПОТОЧНИЙ канал сам у списку. Канал поза поточною зоною
 * вантажиться через roamLoadChannel() БЕЗ запису в кодплаг і БЕЗ зміни «останнього каналу зони».
 *
 * Компілюється лише з -DENABLE_ROAM_RETRY (Makefile). Без дефайна файл порожній, а виклики в uiTxScreen.c /
 * uiChannelMode.c / menuSystem.c загорнуті в той самий #if -- типова збірка байт-у-байт та сама.
 *
 * Розділення: wake_hop_sel.c -- чиста логіка вибору (без заліза, тестується на хості);
 * wake_hop.c -- клей до кодплагу/трансівера/UI (лише задача UI, не ISR).
 */
#ifndef FUNCTIONS_WAKE_HOP_H_
#define FUNCTIONS_WAKE_HOP_H_

#include <stdint.h>
#include <stdbool.h>
#include "functions/roam_cfg.h"

#if defined(ENABLE_ROAM_RETRY)

/* Скільки різних «ключів» (rx, tx, колір-код) пам'ятаємо за одне утримання PTT: вихідний + до ROAM_HOPS_MAX стрибків. */
#define WAKE_HOP_TRIED_MAX   (ROAM_HOPS_MAX + 1U)

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
	uint8_t  colourCode;
} wakeHopChan_t;

/* Чи придатний канал для стрибка: цифровий, не DMO/FORCE_DMO (симплекс), не лише-приймання,
 * передача дозволена, у діапазоні, не заблокований, rx != tx (ретрансляторний зсув). */
bool wakeHopChannelUsable(const wakeHopChan_t *c);

/* Множина вже випробуваних у цьому PTT «ключів» (rx, tx, колір-код). */
typedef struct
{
	uint8_t  n;
	uint32_t rx[WAKE_HOP_TRIED_MAX];
	uint32_t tx[WAKE_HOP_TRIED_MAX];
	uint8_t  cc[WAKE_HOP_TRIED_MAX];
} wakeHopTried_t;

void wakeHopTriedReset(wakeHopTried_t *t);
bool wakeHopTriedHas(const wakeHopTried_t *t, uint32_t rx, uint32_t tx, uint8_t cc);
bool wakeHopTriedAdd(wakeHopTried_t *t, uint32_t rx, uint32_t tx, uint8_t cc);   /* false -- повна */

/* Кандидат підходить: придатний І його (rx, tx, cc) ще не пробували в цьому PTT. */
bool wakeHopCandidateOk(const wakeHopChan_t *c, const wakeHopTried_t *t);

/* Чи взагалі роумити у цьому PTT: функція ввімкнена І поточний канал у списку. */
bool wakeHopMayRoam(bool cfgEnabled, bool currentInList);

/* Чи можна ще стрибати (hopsDone вже зроблено, ліміт maxHops; обмежується діапазоном 1..ROAM_HOPS_MAX). */
bool wakeHopMayHop(uint8_t hopsDone, uint8_t maxHops);

/* У кінці PTT повертати вихідний канал: були стрибки (away) і успіху (пробудження на новому каналі) не було. */
bool wakeHopShouldRestore(bool away, bool success);

/* Колбек перевірки номера каналу: true -- канал підходить як кандидат. */
typedef bool (*wakeHopCandFn)(unsigned num, void *ctx);

/* Шукає наступний підходящий номер каналу після startNum по колу в діапазоні minNum..maxNum -- не більше
 * одного оберту, сам startNum не повертає. true і *outNum -- знайдено. startNum поза діапазоном -> false. */
bool wakeHopFindNext(unsigned startNum, unsigned minNum, unsigned maxNum, wakeHopCandFn fn, void *ctx, unsigned *outNum);

/* ---- клей (wake_hop.c) -- лише для прошивки, не для хостового тесту ---- */
#if !defined(WAKE_HOP_HOST_TEST)
void wakeHopBegin(void);     /* початок екрана передачі: скинути лічильники, запам'ятати вихідний канал */
bool wakeHopTry(void);       /* спроба стрибка; true -- перейшли на новий канал, пробудження перезапущено */
void wakeHopPoll(void);      /* у циклі екрана передачі: помітити успіх, коли пробудження на новому каналі дійшло до AWAKEN */
void wakeHopRestore(void);   /* у кінці передачі: повернути вихідний канал, якщо стрибали і успіху не було */

/* Стан «рація на каналі, знайденому автопереходом» (не збігається з «останнім каналом зони»). */
bool     roamIsActive(void);
uint16_t roamActiveChannel(void);   /* номер каналу кодплагу, коли roamIsActive() */
void     roamClear(void);           /* будь-яка явна зміна каналу користувачем скидає стан */

/* Для меню «Роумінг». */
bool roamCurrentInList(void);       /* поточний канал має прапорець ROAMING */
bool roamCurrentSuitable(void);     /* поточний канал придатний для роумінгу (цифровий, ретранслятор, ...) */
bool roamToggleCurrent(void);       /* перемкнути прапорець поточного каналу стандартним збереженням; true -- виконано */
unsigned roamListCount(void);       /* скільки каналів у списку (скан усього кодплагу) */
int  roamListStep(int fromNum, int dir);   /* наступний (dir>0) чи попередній (dir<0) канал списку від fromNum по колу; fromNum=0 -- перший/останній; 0 -- списку нема */

/* Реалізація -- у HR-C6000.c. Оголошено ТУТ, а не в HR-C6000.h: той заголовок підключає пів прошивки, і зміна в ньому
 * міняла б токени невідомих цьому прототипу файлів у діагностичній конфігурації (tools/test_r46.py W5, test_r47.py V2). */
void HRC6000RestartWakeForRoam(void);
#endif

#endif /* ENABLE_ROAM_RETRY */

#endif /* FUNCTIONS_WAKE_HOP_H_ */
