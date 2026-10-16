/*
 * aprs_fault_fmt.h -- R10-fix4: ЧИСТА (без заліза) частина обробника збою «Режиму APRS»: запис про збій, hex-текст,
 * розшифрування CFSR, пошук адрес повернення в стеку. Той самий файл збирає хост-тест tests/test_aprs_fault.c.
 * Залізна частина (регістри Cortex-M, backup-регістри RTC, екран, сторож) -- aprs_fault.c / aprs_fault.h.
 *
 * Під ENABLE_APRS_RX; у типовій збірці -- порожній translation unit (код не потрапляє в прошивку).
 */
#ifndef _OPENGD77_APRS_FAULT_FMT_H_
#define _OPENGD77_APRS_FAULT_FMT_H_

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include "functions/aprs_rx_cfg.h"

#if defined(ENABLE_APRS_RX)

/* Вид запису (молодший байт у слові магії). */
#define AFLT_KIND_NONE      0U
#define AFLT_KIND_HARD      1U   /* HardFault */
#define AFLT_KIND_MEM       2U   /* MemManage */
#define AFLT_KIND_BUS       3U   /* BusFault */
#define AFLT_KIND_USAGE     4U   /* UsageFault */
#define AFLT_KIND_WDG       5U   /* програмний сторож: головний цикл не відгукувався ~2 с */
#define AFLT_KIND_IWDG      6U   /* скидання апаратним IWDG (лише збірка з APRS_FAULT_IWDG) */

#define AFLT_MAGIC_BASE     0xFA170000UL
#define AFLT_MAGIC_MASK     0xFFFF0000UL

/* Скільки адрес повернення зі стека зберігаємо. R21 З1.1: чотирьох кадрів замало (збій у printf-ланцюжку: перші кадри -- це libc, до коду прошивки
 * не доходило). Користувацька збірка не має трасування (APRS_MODE_TRACE), тож backup-регістри 16..18 (S_TRN/S_TRV/S_T0) вільні і йдуть під стек:
 * 4 + 3 = 7. Діагностична збірка тримає трасування у цих регістрах -- там 4, як було. RAM не росте: це регістри RTC. */
#if defined(APRS_MODE_TRACE)
#define AFLT_NSTK           4
#else
#define AFLT_NSTK           7
#endif

/* Запис про збій. Для KIND_WDG: pc/lr/sp -- збережений контекст ГОЛОВНОГО завдання (де воно застрягло);
 * addr/r0 -- PC/LR того, що виконував процесор у мить спрацювання сторожа (напр. IDLE). */
typedef struct
{
	uint32_t kind;
	uint32_t pc, lr, cfsr, hfsr, addr, sp, exc, xpsr, r0;
	uint32_t stk[AFLT_NSTK];
	uint32_t trace;      /* номер останнього кроку трасування (0 -- нема) */
	uint32_t traceV;     /* його значення v */
	uint32_t traceMs;    /* мс від початку серії трасування до цього кроку */
} aprsFaultRec_t;

/* 8 hex-цифр верхнім регістром + NUL (out -- мін. 9 байт). */
void aprsFaultHex8(char *out, uint32_t v);
/* Десяткове число без printf; повертає довжину (out -- мін. 11 байт). */
size_t aprsFaultDec(char *out, uint32_t v);
/* Коротка назва виду; завжди ненульовий рядок. */
const char *aprsFaultKindName(uint32_t kind);
/* Назва «головної» причини за CFSR (старший за пріоритетом виставлений біт); "" -- жодного біта. */
const char *aprsFaultCfsrName(uint32_t cfsr);
/* Адреса схожа на повернення в код: Thumb (непарна) і в [textLo, textHi) -- межі секції .text (символи лінкера __text_start/_etext).
 * R21 З1.1: раніше брали будь-що у флеші, і в звіт потрапляли вказівники на .rodata (напр. font_6x8) -- вони збивали з пантелику. */
bool aprsFaultAddrIsCode(uint32_t v, uint32_t textLo, uint32_t textHi);
/* Перші maxOut адрес повернення з масиву слів стека (від вершини вгору); повертає скільки знайдено. Беруться лише адреси в [textLo, textHi).
 * Дублікати поспіль пропускаються. Це ЕВРИСТИКА: у стеку лишаються й старі значення. */
int aprsFaultScanStack(const uint32_t *words, size_t n, uint32_t *out, int maxOut, uint32_t textLo, uint32_t textHi);
/* Чи слово магії відповідає валідному запису (повертає вид або 0). */
uint32_t aprsFaultKindFromMagic(uint32_t magicWord);
uint32_t aprsFaultMagicFromKind(uint32_t kind);

#endif /* ENABLE_APRS_RX */
#endif /* _OPENGD77_APRS_FAULT_FMT_H_ */
