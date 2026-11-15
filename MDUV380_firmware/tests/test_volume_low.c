/*
 * test_volume_low.c -- R78: «Мін.гучність» (постійний тихий нижній рівень). Чиста крива/таблиці (volume_low_logic.h) + СПРАВЖНІЙ functions/volume_low.c
 * із заглушками обладнання (radioWriteReg2byte, режим, custom-data блок, APRS). Перевіряється:
 *  1  крива: extra(0) = D; extra(n >= K) = 0; неперервність у n = K; монотонність (extra не зростає із зростанням n); цілі дБ; K = 0 -- нуль;
 *  2  «заглушено» (-99) == мінімум (-31) -- нічого не міняється; позиція обрізається до 0..62;
 *  3  таблиці: DMR Q15 = round(32768*10^(-x/20)); FM low-byte = round(0xCC*10^(-x/20)) не нижче 0x0F; монотонні; межі; ціль мінімуму (36 дБ; 0x0F);
 *  4  повний рівень (стоковий + extra) не зменшується із зростанням n для всіх режимів (DMR і FM);
 *  5  рампа: ≤ кроку за відлік, доходить до цілі, без перельоту; множник: одиничний -- без змін, знак зберігається;
 *  6  режим 0 -- жодного запису в регістр; 0x44 пишеться лише через radioWriteReg2byte, лише старший байт 0x06, лише в аналоговому режимі,
 *     ніколи 0x07 (DMR); значення не нижче 0x0F;
 *  7  захисти: передача, APRS-приймач, режим APRS, відкрита проба (імітація), хотспот -- стокове 0xCC; повернення з цих станів -- знову за n;
 *     StopForTx повертає 0xCC ДО передачі; зміна режиму на цифровий не пише 0x44;
 *  8  R81 / R98-FIX7: режим фіксований, K = VOLLOW_KNEE = 32 (було 16): блок 17 = 0/1/2/3/сміття або немає блоку -- завжди K 32, жодного запису в блок;
 *  9  DMR-ціль: у цифровому режимі за n; в аналоговому, при хотспоті -- одиниця.
 */
#include <stdio.h>
#include <math.h>
#include <string.h>
#include "functions/volume_low.h"
#include "functions/volume_probe.h"
#include "functions/trx.h"
#include "functions/settings.h"

static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

/* --- заглушки обладнання --- */
volatile bool trxTransmissionEnabled;
volatile int settingsUsbMode;
static int s_mode = RADIO_MODE_ANALOG;
static bool s_aprsRx, s_aprsMode;
static int s_wrN;
static struct { uint8_t reg, hi, lo; } s_wr[512];
static int s_bad;                 /* недозволені записи: не 0x44, не 0x06, нижче 0x0F */
static uint8_t s_blk; static bool s_blkHas; static int s_blkWrites;
static bool s_probe;              /* імітація відкритої діагностичної проби (R77A) */
static uint8_t s_cache44 = 0xCC;  /* імітація кешу: чи справді піде в I2C */
static int s_i2c;

bool radioWriteReg2byte(uint8_t reg, uint8_t v1, uint8_t v2)
{
	if (s_wrN < 512) { s_wr[s_wrN].reg = reg; s_wr[s_wrN].hi = v1; s_wr[s_wrN].lo = v2; s_wrN++; }
	if ((reg != 0x44) || (v1 != 0x06) || ((v2 != 0xCC) && (v2 < 0x0F))) { s_bad++; }
	if (v2 != s_cache44) { s_i2c++; s_cache44 = v2; }
	return true;
}
int trxGetMode(void) { return s_mode; }
#if defined(VOLUME_PROBE)
bool volumeProbeIsOn(void) { return s_probe; }
#endif
bool aprsRxIsRunning(void) { return s_aprsRx; }
bool aprsModeIsActive(void) { return s_aprsMode; }
bool codeplugGetOpenGD77CustomDataBounded(CodeplugCustomDataType_t t, uint8_t *b, int m)
{
	if ((t != CODEPLUG_CUSTOM_DATA_TYPE_VOLUME_LOW_CFG) || (m < 1) || !s_blkHas) { return false; }
	b[0] = s_blk; return true;
}
bool codeplugSetOpenGD77CustomData(CodeplugCustomDataType_t t, uint8_t *b, int len)
{
	if ((t != CODEPLUG_CUSTOM_DATA_TYPE_VOLUME_LOW_CFG) || (len != 1)) { s_bad++; return false; }
	s_blk = b[0]; s_blkHas = true; s_blkWrites++; return true;
}

static void reset(void)
{
	trxTransmissionEnabled = false;
	settingsUsbMode = USB_MODE_CPS;
	s_probe = false;
	s_mode = RADIO_MODE_ANALOG; s_aprsRx = s_aprsMode = false; s_wrN = 0; s_bad = 0; s_blkHas = false; s_blk = 0; s_blkWrites = 0;
	volumeLowSetMode(0); volumeLowPotSettled(31); volumeLowTick(); volumeLowTick();
	s_wrN = 0; s_cache44 = 0xCC; s_i2c = 0;
}
static uint8_t last44(void) { return (s_wrN > 0) ? s_wr[s_wrN - 1].lo : 0xCC; }
static void settle(int8_t v) { volumeLowPotSettled(v); volumeLowTick(); }

int main(void)
{
	printf("test_volume_low\n");
#if !defined(VOLUME_LOW)
	printf("  FAIL VOLUME_LOW не визначено (потрібні -DENABLE_VOLUME_LOW -DLANGUAGE_BUILD_UKRAINIAN і Plus 10W)\n");
	return 1;
#else
	/* 1: крива */
	{
		static const uint8_t knees[5] = { 8, 16, 24, 32, VOLLOW_KNEE };   /* R98-FIX7: + 32 (нове K) */
		int mono = 1, cont = 1, zero = 1, ends = 1, ints = 1;
		for (int k = 0; k < 5; k++)
		{
			for (int d = 0; d < 2; d++)
			{
				const uint8_t D = d ? VOLLOW_DEPTH_FM_DB : VOLLOW_DEPTH_DMR_DB, K = knees[k];
				if (vlExtraDb(0, K, D) != D) { ends = 0; }
				for (uint8_t n = 0; n <= VOLLOW_POS_MAX; n++)
				{
					uint8_t e = vlExtraDb(n, K, D);
					double ex = (n < K) ? (double)D * (K - n) / K : 0.0;
					if (n >= K && e != 0) { zero = 0; }
					if (fabs((double)e - ex) > 0.5001) { ints = 0; }
					if (n > 0 && e > vlExtraDb(n - 1, K, D)) { mono = 0; }
					if (n >= 1 && vlExtraDb(n - 1, K, D) - e > (D + K - 1) / K + 1) { cont = 0; }   /* крок між сусідніми позиціями не більше ceil(D/K)+1 дБ */
				}
				if (vlExtraDb(K - 1, K, D) > (D + K - 1) / K) { cont = 0; }
				if (vlExtraDb(K, K, D) != 0) { cont = 0; }
			}
		}
		CHECK(ends, "extra(0) == D для K 8/16/24/32 (DMR 36, FM 23)");
		CHECK(zero, "extra(n >= K) == 0");
		CHECK(mono, "extra не зростає із зростанням n (монотонність)");
		CHECK(cont, "неперервність: у n = K нуль, крок між сусідніми позиціями обмежений");
		CHECK(ints, "extra == round(D*(K-n)/K) у цілих дБ (відхилення <= 0,5)");
		CHECK(vlExtraDb(3, 0, 36) == 0 && vlExtraDb(0, 0, 36) == 0, "K = 0 (вимкнено): нуль");
		CHECK(VOLLOW_KNEE == 32U && vlKnee(0) == 0 && vlKnee(1) == VOLLOW_KNEE && vlKnee(2) == VOLLOW_KNEE && vlKnee(3) == VOLLOW_KNEE && vlKnee(4) == 0 && vlKnee(255) == 0, "R98-FIX7: коліно -- одна константа VOLLOW_KNEE = 32 для режимів 1..3; 0 і сміття -- вимкнено");
		CHECK(((2U * 36U * 62U) + 62U) < 65536U && vlExtraDb(0, 62, 36) == 36 && vlExtraDb(61, 62, 36) == 1, "R98-FIX7: округлення (2*D*(K-n)+K)/(2K) без переповнення до K = 62");
		CHECK(vlModeSanitize(0) == 0 && vlModeSanitize(3) == 3 && vlModeSanitize(4) == 0 && vlModeSanitize(0xFF) == 0, "режим із флеша: 0..3, решта -- 0");
	}
	/* 2: заглушено і межі позиції */
	CHECK(vlPos(-99) == 0 && vlPos(-31) == 0 && vlPos(-32) == 0 && vlPos(0) == 31 && vlPos(31) == 62 && vlPos(100) == 62, "позиція: -99 і -31 -> 0, 0 -> 31, 31 -> 62");
	CHECK(vlExtraDb(vlPos(-99), VOLLOW_KNEE, 36) == vlExtraDb(vlPos(-31), VOLLOW_KNEE, 36), "заглушено -- те саме ослаблення, що в мінімумі (без сплеску при виході зі заглушення)");
	/* 3: таблиці */
	{
		int ok = 1, mono = 1;
		for (unsigned x = 0; x <= 36; x++)
		{
			double ex = floor(32768.0 * pow(10.0, -(double)x / 20.0) + 0.5);
			if ((double)vlDmrGainQ15(x) != ex) { ok = 0; }
			if (x && vlDmrGainQ15(x) >= vlDmrGainQ15(x - 1)) { mono = 0; }
		}
		CHECK(ok, "DMR: Q15[x] == round(32768*10^(-x/20)), x = 0..36 (37 значень)");
		CHECK(mono && vlDmrGainQ15(0) == 32768 && vlDmrGainQ15(36) == 519 && vlDmrGainQ15(99) == 519, "DMR: монотонна, [0] = 32768, [36] = 519, x > 36 обрізається");
		ok = 1; mono = 1; int floorOk = 1;
		for (unsigned x = 0; x <= 23; x++)
		{
			double ex = floor(204.0 * pow(10.0, -(double)x / 20.0) + 0.5);
			if (ex < 15) { ex = 15; }
			if ((double)vlFmLow(x) != ex) { ok = 0; }
			if (vlFmLow(x) < VOLLOW_FM_FLOOR_LOW) { floorOk = 0; }
			if (x && vlFmLow(x) > vlFmLow(x - 1)) { mono = 0; }
		}
		CHECK(ok, "FM: low[x] == round(0xCC*10^(-x/20)), не нижче 0x0F, x = 0..23 (24 значення)");
		CHECK(floorOk && mono, "FM: усі >= 0x0F, не зростають");
		CHECK(vlFmLow(0) == 0xCC && vlFmLow(23) == 0x0F && vlFmLow(200) == 0x0F && VOLLOW_FM_HIGH == 0x06, "FM: x=0 -> 0xCC (стокове), мінімум 0x0F (6 %%), x > 23 обрізається");
		CHECK(20.0 * log10(204.0 / 15.0) > 22.6 && 20.0 * log10(204.0 / 15.0) < 22.8 && VOLLOW_DEPTH_FM_DB == 23, "D_FM = 23 -- ціле з 20*log10(0xCC/0x0F) = 22,7");
	}
	/* 3b: таблиці істинності умов (усі 32 комбінації) */
	{
		int okF = 1, okD = 1;
		for (int m = 0; m < 32; m++)
		{
			bool analog = m & 1, tx = m & 2, aprs = m & 4, probe = m & 8, usb = m & 16;
			if (vlFmAllowed(analog, tx, aprs, probe, usb) != (analog && !tx && !aprs && !probe && usb)) { okF = 0; }
			if (vlDmrAllowed(analog, probe, usb) != (analog && !probe && usb)) { okD = 0; }
		}
		CHECK(okF && okD, "умови дії: FM лише аналог, не TX, не APRS, без проби, USB-CPS; DMR лише цифра, без проби, USB-CPS (32 комбінації)");
		CHECK(VOLLOW_FM_FLOOR_LOW == 0x0F && VOLLOW_FM_STOCK_LOW == 0xCC && VOLLOW_FM_REG == 0x44 && VOLLOW_FM_HIGH == 0x06, "константи регістра: 0x44, 0x06, стокове 0xCC, підлога 0x0F");
	}
	/* 4: повний рівень (стоковий + (-extra)) не зменшується із зростанням n */
	{
		int ok = 1;
		static const uint8_t kk[5] = { 8, 16, 24, 32, VOLLOW_KNEE };
		for (int k = 0; k < 5; k++)
		{
			for (int d = 0; d < 2; d++)
			{
				const uint8_t D = d ? VOLLOW_DEPTH_FM_DB : VOLLOW_DEPTH_DMR_DB;
				for (int n = 1; n <= 62; n++)
				{
					int a = (n - 31) - (int)vlExtraDb(n, kk[k], D), b = (n - 1 - 31) - (int)vlExtraDb(n - 1, kk[k], D);
					if (a < b) { ok = 0; }
				}
			}
		}
		CHECK(ok, "повний рівень = стоковий - extra не зменшується із зростанням n (K 8/16/24/32, DMR і FM)");
	}
	/* 5: рампа і множник */
	{
		uint16_t g = 32768; int steps = 0, ok = 1;
		while (g != 519 && steps < 1000) { uint16_t nx = vlRamp(g, 519); if ((g - nx) > VOLLOW_RAMP_STEP) ok = 0; g = nx; steps++; }
		CHECK(ok && g == 519 && steps > 100 && steps < 300, "рампа 0 -> -36 дБ: за %d відліків, крок <= %u, рівно в ціль", steps, VOLLOW_RAMP_STEP);
		g = 519; steps = 0;
		while (g != 32768 && steps < 1000) { uint16_t nx = vlRamp(g, 32768); if ((nx - g) > VOLLOW_RAMP_STEP) ok = 0; if (nx < g) ok = 0; g = nx; steps++; }
		CHECK(ok && g == 32768, "рампа вгору: монотонна, у ціль, без перельоту");
		CHECK(vlRamp(5000, 5000) == 5000 && vlRamp(5000, 5050) == 5050 && vlRamp(5050, 5000) == 5000, "рампа: уже в цілі / ближче за крок -- рівно ціль");
		CHECK(vlApply(1234, 32768) == 1234 && vlApply(-1234, 32768) == -1234, "множник 1.0 -- відлік без змін");
		CHECK(vlApply(32767, 16423) == 16422, "множник -6 дБ (16423/32768): 32767 -> 16422");
		CHECK(vlApply(-32768, 16384) == -16384 && vlApply(0, 519) == 0 && vlApply(-1000, 16384) < 0, "знак зберігається, нуль -- нуль, край діапазону");
		CHECK(vlApply(20000, 519) == 316 && vlApply(-20000, 519) == -317, "-36 дБ: 20000 -> 316 (арифметичний зсув: від'ємні округлюються вниз)");
	}
	/* 6: режим 0 -- жодного запису */
	reset();
	for (int8_t v = -31; v <= 31; v += 3) { settle(v); }
	settle(-99);
	CHECK(s_wrN == 0 && s_i2c == 0 && volumeLowDmrGainQ15 == 32768, "режим «Вимк»: жодного запису в регістр, DMR-множник 1.0 на всіх положеннях");
	/* 6b: FM, режим 2 (K = VOLLOW_KNEE = 32), аналог */
	reset();
	volumeLowSetMode(2); settle(-31);
	CHECK(last44() == 0x0F && s_bad == 0, "K32, ручка -31: 0x0F (6 %%)");
	settle(-99);
	CHECK(last44() == 0x0F, "заглушено: те саме 0x0F (нічого не міняється)");
	settle(-23);                      /* n = 8 -> extra = round(23*24/32) = 17 (17,25 -> 17) */
	CHECK(last44() == vlFmLow(vlExtraDb(8, 32, 23)) && vlExtraDb(8, 32, 23) == 17, "K32, n = 8: extra 17 дБ -> 0x%02X", vlFmLow(17));
	settle(-15);                      /* n = 16 -> половина: round(23*16/32) = 12 (11,5 -> 12); при K 16 тут уже було стокове */
	CHECK(last44() == vlFmLow(12) && vlExtraDb(16, 32, 23) == 12, "K32, n = 16: extra 12 дБ (середина коліна) -> 0x%02X", vlFmLow(12));
	settle(0);                        /* n = 31 -> round(23*1/32) = 1 */
	CHECK(last44() == vlFmLow(1) && s_bad == 0, "K32, ручка 0 (n = 31): extra 1 дБ -> 0x%02X", vlFmLow(1));
	settle(1);                        /* n = 32 -> коліно */
	CHECK(last44() == 0xCC && s_bad == 0, "K32, n = 32 (коліно): стокове 0xCC");
	/* кеш: повторні тіки не штовхають I2C */
	{
		int before = s_i2c;
		for (int i = 0; i < 100; i++) { volumeLowTick(); }
		CHECK(s_i2c == before, "100 тіків на тому ж стані -- жодного нового I2C-запису (кеш регістра)");
	}
	/* 6c: перезапис налаштувань FM (канал/смуга) повертає 0xCC у кеш -- наступний тік відновлює ослаблення */
	reset();
	volumeLowSetMode(1); settle(-31);
	CHECK(last44() == 0x0F, "режим 1 (K 32), мінімум: 0x0F");
	s_cache44 = 0xCC;                 /* AT1846FMSettings переписали регістр */
	volumeLowTick();
	CHECK(s_cache44 == 0x0F, "після перезапису налаштувань FM ослаблення відновлено за один тік");
	/* 7: захисти */
	reset();
	volumeLowSetMode(3); settle(-31);
	CHECK(last44() == 0x0F, "режим 3 (K 32), мінімум: 0x0F");
	{
		struct { const char *name; int how; } c[] = { {"передача", 0}, {"APRS-приймач", 1}, {"режим APRS", 2}, {"хотспот", 3} };
		for (unsigned i = 0; i < 4; i++)
		{
			reset(); volumeLowSetMode(3); settle(-31); int n0 = s_wrN;
			switch (c[i].how) { case 0: trxTransmissionEnabled = true; break; case 1: s_aprsRx = true; break; case 2: s_aprsMode = true; break; case 3: settingsUsbMode = USB_MODE_HOTSPOT; break; }
			volumeLowTick();
			if (c[i].how == 0) { CHECK(s_wrN == n0, "[%s] під час передачі в регістр НЕ пишемо нічого", c[i].name); }
			else { CHECK(last44() == 0xCC && s_wrN > n0, "[%s] ослаблення знято: 0xCC", c[i].name); }
			trxTransmissionEnabled = false; s_aprsRx = s_aprsMode = false; settingsUsbMode = USB_MODE_CPS;
			volumeLowTick();
			CHECK(last44() == 0x0F && s_bad == 0, "[%s] повернення зі стану: знову 0x0F за поточною позицією", c[i].name);
		}
	}
	reset(); volumeLowSetMode(2); settle(-31);
	volumeLowStopForTx();
	CHECK(last44() == 0xCC, "StopForTx: 0xCC повернуто ДО передачі");
	trxTransmissionEnabled = true; volumeLowTick(); trxTransmissionEnabled = false; volumeLowTick();
	CHECK(last44() == 0x0F, "після передачі ослаблення відновлено");
	/* цифровий режим: 0x44 не пишемо взагалі, DMR-ціль за n */
	reset(); volumeLowSetMode(2); s_mode = RADIO_MODE_DIGITAL; settle(-31);
	CHECK(s_wrN == 0 && volumeLowDmrGainQ15 == vlDmrGainQ15(36), "цифра: регістр не чіпаємо (0x44 = 0x07FF лишається), DMR-ціль -36 дБ");
	settle(-23);
	CHECK(volumeLowDmrGainQ15 == vlDmrGainQ15(vlExtraDb(8, 32, 36)) && vlExtraDb(8, 32, 36) == 27, "цифра, K32, n = 8: -27 дБ");
	settle(1);
	CHECK(volumeLowDmrGainQ15 == 32768, "цифра: від коліна (n = 32) -- 1.0");
	settingsUsbMode = USB_MODE_HOTSPOT; settle(-31);
	CHECK(volumeLowDmrGainQ15 == 32768, "хотспот: DMR-множник 1.0");
	settingsUsbMode = USB_MODE_CPS; s_mode = RADIO_MODE_ANALOG; settle(-31);
	CHECK(volumeLowDmrGainQ15 == 32768, "аналог: DMR-множник 1.0");
	/* перехід аналог -> цифра зі змінним 0x44: у цифрі нічого не пишемо */
	reset(); volumeLowSetMode(2); settle(-31); int nA = s_wrN; s_mode = RADIO_MODE_DIGITAL; volumeLowTick();
	CHECK(s_wrN == nA, "перехід у цифру: 0x44 не чіпаємо (його вже переписали як 0x07FF)");
	/* жодного запису 0x07 за весь тест */
	CHECK(s_bad == 0, "за весь прогін жодного запису не в 0x44, не з 0x06 або нижче 0x0F");
	/* 7b: діагностична проба має пріоритет, після виходу з неї відновлюється */
#if defined(VOLUME_PROBE)
	reset(); volumeLowSetMode(2); settle(-31);
	CHECK(last44() == 0x0F, "(з пробою у збірці) проба закрита: ослаблення діє");
	s_probe = true; volumeLowTick();
	CHECK(last44() == 0xCC, "проба відкрилась: 0x44 стокове -- проба керує сама");
	{ int n0 = s_wrN; for (int i = 0; i < 50; i++) { volumeLowTick(); } CHECK(s_wrN == n0, "поки проба відкрита -- ми в регістр не пишемо"); }
	s_probe = false; volumeLowTick();
	CHECK(last44() == 0x0F, "проба закрилась: постійне ослаблення відновилось само");
	reset(); volumeLowSetMode(2); s_mode = RADIO_MODE_DIGITAL; settle(-31);
	CHECK(volumeLowDmrGainQ15 == vlDmrGainQ15(36), "цифра: ціль -36 дБ");
	s_probe = true; volumeLowTick();
	CHECK(volumeLowDmrGainQ15 == 32768, "проба відкрита: DMR-множник R78 = 1.0 (проба має свій зсув)");
	s_probe = false; volumeLowTick();
	CHECK(volumeLowDmrGainQ15 == vlDmrGainQ15(36), "проба закрита: DMR-ціль повернулась");
#endif
	/* 8 (R81 / R98-FIX7): режим ФІКСОВАНИЙ (mode 2), K = VOLLOW_KNEE = 32 -- блок 17 не читається і не пишеться, що б у ньому не лежало */
	reset();
	{
		static const uint8_t vals[] = { 0, 1, 2, 3, 4, 7, 0x7F, 0xFF };
		s_blkHas = false; volumeLowLoad(); CHECK(volumeLowGetMode() == VOLLOW_FIXED_MODE && vlKnee(volumeLowGetMode()) == 32, "немає блоку -> K 32");
		for (unsigned i = 0; i < sizeof vals; i++)
		{
			s_blkHas = true; s_blk = vals[i]; volumeLowLoad();
			CHECK(volumeLowGetMode() == 2 && vlKnee(volumeLowGetMode()) == 32, "блок = %u (0/1/2/3/сміття) -> K 32", (unsigned)vals[i]);
			CHECK(vlEffectiveMode(vals[i]) == 2, "vlEffectiveMode(%u) == 2", (unsigned)vals[i]);
		}
		CHECK(VOLLOW_FIXED_MODE == 2U && vlKnee(VOLLOW_FIXED_MODE) == 32U, "VOLLOW_FIXED_MODE = 2 -> коліно 32 (R98-FIX7)");
		/* поведінка на старій конфігурації «блок = 0 (вимкнено в R78)»: тепер усе одно діє K 32 (крива D 36 / 23 дБ -- пункти 6b/9) */
		s_blkHas = true; s_blk = 0; volumeLowLoad(); settle(-31);
		CHECK(last44() == 0x0F, "старий блок 0: FM на мінімумі все одно 0x0F (K 32 діє)");
		CHECK(s_blkWrites == 0 && s_bad == 0, "жодного запису в блок 17 (немає меню -- немає збереження)");
		/* мінімум (-31): повна глибина D */
		s_blkHas = false; volumeLowLoad(); s_mode = RADIO_MODE_DIGITAL; settle(-31);
		CHECK(volumeLowDmrGainQ15 == vlDmrGainQ15(36), "K 32: мінімум ручки -- D_DMR 36 дБ");
	}
	CHECK(CODEPLUG_CUSTOM_DATA_TYPE_VOLUME_LOW_CFG == 17, "номер блока 17");
	CHECK(s_bad == 0, "жодного недозволеного запису в блок");
#endif
	printf(fails ? "ПРОВАЛІВ: %d\n" : "усе гаразд\n", fails);
	return fails ? 1 : 0;
}
