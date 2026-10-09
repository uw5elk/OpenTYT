/*
 * aprs_probe_dsp.h -- чиста (без заліза) обробка відліків для діагностичного екрана
 * «APRS проба» (R2, docs/aprs-rx-feasibility.md, розділ 3).
 *
 * Що рахує на одному джерелі (каналі) звуку:
 *   - середнє (DC), RMS змінної складової і пік відносно середнього -- у сирих одиницях
 *     джерела (I2S: int16; АЦП: 0..4095);
 *   - амплітуду тонів 1200 Гц і 2200 Гц -- Goertzel на блоках по blockLen відліків
 *     (частоти потрапляють рівно в біни: 160 відліків @ 8000 Гц і 192 @ 9600 Гц);
 *   - співвідношення амплітуд у дБ і «хто переважає».
 *
 * Жодного демодулятора AFSK -- лише вимірювання рівня й тонів.
 *
 * Відліки подаються по одному з переривання (I2S DMA або таймер АЦП). Кожні
 * blocksPerWin блоків вікно закривається, apChanPush() повертає true і заповнює
 * результат, а опорний рівень (ref) переходить на щойно виміряне середнє -- так
 * сума квадратів не втрачає точності на великому DC (АЦП ~2048).
 *
 * Пам'ять -- лише сам apChan_t, який кладе викликач (у прошивці -- CCM).
 * Хост-тест: tests/test_aprs_probe_dsp.c.
 */
#ifndef _OPENGD77_APRS_PROBE_DSP_H_
#define _OPENGD77_APRS_PROBE_DSP_H_

#include <stdint.h>
#include <stdbool.h>

#if defined(ENABLE_APRS_RX_PROBE)

/* Підтримані частоти дискретизації: коефіцієнти Goertzel -- константи (без cosf). */
#define AP_FS_I2S   8000U
#define AP_FS_ADC   9600U

/* Співвідношення обмежується цим значенням (дБ) -- і для 0 в знаменнику. */
#define AP_DB_LIMIT 60

enum
{
	AP_WIN_NONE = 0,   /* тони однакові з точністю до 6 дБ */
	AP_WIN_1200,
	AP_WIN_2200,
	AP_WIN_WEAK        /* обидва тони -- шум: сильніший < max(2, RMS/8) (чистий тон дає ~1,4*RMS,
	                    * пакет AFSK -- ~0,2-0,3*RMS кожен, голос на 1000 Гц -- ~0) */
};

typedef struct
{
	/* налаштування */
	float    c1200;       /* 2*cos(2*pi*1200/fs) */
	float    c2200;       /* 2*cos(2*pi*2200/fs) */
	uint16_t blockLen;    /* відліків на блок Goertzel */
	uint16_t blocksPerWin;
	/* поточний блок */
	float    q1a, q2a;    /* стан Goertzel 1200 */
	float    q1b, q2b;    /* стан Goertzel 2200 */
	uint16_t idx;         /* відлік у блоці */
	uint16_t blocks;      /* закритих блоків у вікні */
	/* поточне вікно */
	int32_t  ref;         /* опорний рівень (середнє попереднього вікна) */
	int64_t  sum;         /* сума (x - ref) */
	uint64_t sumSq;       /* сума (x - ref)^2 */
	int32_t  min, max;    /* сирі */
	float    p1200, p2200;/* сума потужностей блоків */
	uint32_t n;           /* відліків у вікні */
} apChan_t;

typedef struct
{
	int32_t  mean;        /* DC, сирі одиниці */
	uint32_t rms;         /* RMS змінної складової */
	uint32_t peak;        /* max |x - mean| */
	uint32_t a1200;       /* амплітуда тону 1200 Гц (як у синусоїди: пік) */
	uint32_t a2200;
	int16_t  ratioDb;     /* 20*lg(a1200/a2200), [-AP_DB_LIMIT..AP_DB_LIMIT] */
	uint8_t  winner;      /* AP_WIN_* */
	uint8_t  valid;       /* 1 -- результат є */
	uint32_t n;           /* відліків у вікні */
} apResult_t;

/* fs -- AP_FS_I2S або AP_FS_ADC (інша -> коефіцієнти 0, тони не міряються).
 * ref -- початковий опорний рівень (I2S: 0; АЦП: 2048). */
void apChanInit(apChan_t *c, uint32_t fs, uint16_t blockLen, uint16_t blocksPerWin, int32_t ref);

/* Один відлік. true -- вікно щойно закрилося, *out заповнено (out може бути NULL). */
bool apChanPush(apChan_t *c, int32_t x, apResult_t *out);

/* Допоміжні (для тесту теж). */
uint32_t apIsqrt64(uint64_t v);
int16_t  apRatioDb(uint32_t a, uint32_t b);
uint8_t  apWinner(uint32_t a1200, uint32_t a2200);

#endif /* ENABLE_APRS_RX_PROBE */
#endif /* _OPENGD77_APRS_PROBE_DSP_H_ */
