/*
 * test_aprs_frame.c -- хостовий тест СКЛАДАННЯ КАДРУ AX.25 (R10-fix2, functions/aprs.c: aprsSendPacket()).
 *
 * Підключає САМ aprs.c (#include) -- той самий код, що йде в прошивку, разом зі статичними enqueue*; залізо
 * (радіо, таймер TIM6, SPI-флеш, аудіо) -- заглушки нижче. Еталон кадру -- НЕЗАЛЕЖНА реалізація NRZI + бітстаффінгу
 * + CRC-16 у самому тесті (ref_*), складена з ЛОГІЧНИХ байтів; порівнюється весь packetBuffer і довжина в бітах.
 *
 * Що перевіряється (те, що не видно без рації):
 *  - шлях РІВНО 6 символів без нуля, порожній шлях, один/два шляхи -- strlen() не виходить за межі поля;
 *  - коментар кодплуга РІВНО 24 символи без нуля (за ним -- ненульові байти конфігу) -- рівно 24 символи в кадрі;
 *  - позивний 6 символів / порожній, координати 0/0;
 *  - коментар режиму: найдовший кирилицею (UTF-8, 43 байти), кадр влазить у буфер із запасом;
 *  - переповнення: надто довгий рядок -- кадр НЕ передається (false, стан «завершено»), буфер не виходить за межі;
 *  - aprsModeTxBeacon(): після виклику aprsConfig НЕ висить на мертвому стеку; друга передача поспіль і стоковий
 *    маяк після маяка режиму бачать валідний конфіг (біт «безшумно» береться з аргументу, а не зі сміття).
 * Збирається з -fsanitize=address,undefined (див. run_tests.sh): вихід за межі буфера -- провал.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../application/source/functions/aprs.c"

#if !defined(ENABLE_APRS_RX)
#error "потрібен ENABLE_APRS_RX"
#endif

static int s_fail = 0;
static int s_checks = 0;
#define CHECK(c, ...) do { s_checks++; if (!(c)) { s_fail++; printf("ПРОВАЛ %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

/* ---- заглушки заліза -------------------------------------------------------------------------------------- */
static uint32_t s_now = 100000;
static int s_ampEnable, s_ampDisable, s_timStart, s_setTX;

TIM_HandleTypeDef htim6;
HAL_StatusTypeDef HAL_TIM_Base_Init(TIM_HandleTypeDef *h) { (void)h; return HAL_OK; }
HAL_StatusTypeDef HAL_TIMEx_MasterConfigSynchronization(TIM_HandleTypeDef *h, const TIM_MasterConfigTypeDef *c) { (void)h; (void)c; return HAL_OK; }
HAL_StatusTypeDef HAL_TIM_Base_Start_IT(TIM_HandleTypeDef *h) { (void)h; s_timStart++; return HAL_OK; }
HAL_StatusTypeDef HAL_TIM_Base_Stop_IT(TIM_HandleTypeDef *h) { (void)h; return HAL_OK; }
void Error_Handler(void) { printf("Error_Handler\n"); s_fail++; }
void HAL_GPIO_WritePin(GPIO_TypeDef *g, uint16_t p, GPIO_PinState s) { (void)g; (void)p; (void)s; }
void HRC6000SetMic(bool b) { (void)b; }
bool AT1846sWriteTone1Reg(uint16_t t) { (void)t; return true; }
void trxSelectVoiceChannel(uint8_t c) { (void)c; }
int8_t getVolumeControl(void) { return 0; }
bool radioWriteReg2byte(uint8_t r, uint8_t a, uint8_t b) { (void)r; (void)a; (void)b; return true; }
void audioAmpEnable(audioAmpChannel_t c) { (void)c; s_ampEnable++; }
void audioAmpDisable(audioAmpChannel_t c) { (void)c; s_ampDisable++; }
uint32_t ticksGetMillis(void) { return s_now; }
void vTaskDelay(uint32_t t) { s_now += (t == 0U) ? 1U : t; }

/* стан, який читає aprsModeTxBeacon() */
settingsStruct_t nonVolatileSettings;
uiDataGlobal_t uiDataGlobal;
CodeplugChannel_t *currentChannelData;
volatile bool trxTransmissionEnabled = false;
volatile bool trxIsTransmitting = false;
bool PTTToggledDown = false;
static int s_rxStop, s_ecoCalls;
void aprsRxStopForTx(void) { s_rxStop++; }
bool aprsModeIsActive(void) { return false; }
void rxPowerSavingSetState(ecoPhase_t st) { (void)st; s_ecoCalls++; }
void LedWrite(LEDs_t l, uint8_t v) { (void)l; (void)v; }
void HRC6000ClearIsWakingState(void) { }
void trxSetTX(void) { s_setTX++; trxIsTransmitting = true; }
int trxGetMode(void) { return RADIO_MODE_ANALOG; }
bool settingsIsOptionBitSet(bitfieldOptions_t b) { (void)b; return false; }
bool trxCheckFrequencyInAmateurBand(uint32_t f) { (void)f; return true; }

/* завершення передачі (aprsBeaconingTxStateTick): відновлення приймача */
static int s_activateRx;
void trxSetRxCSS(RadioDevice_t d, uint16_t t) { (void)d; (void)t; }
void trxActivateRx(bool b) { (void)b; s_activateRx++; }
void trxSetModeAndBandwidth(int m, bool bw) { (void)m; (void)bw; }
uint8_t codeplugChannelGetFlag(CodeplugChannel_t *c, ChannelFlag_t f) { (void)c; (void)f; return 0; }

/* "ім'я рації" -- читається з SPI-флешу; у тесті -- довільний вміст */
static char s_radioName[16] = "RADIO1";
void codeplugGetRadioName(char *buf) { memset(buf, 0, 9); strncpy(buf, s_radioName, 8); }

/* ---- еталонний кодувальник ------------------------------------------------------------------------------- */
typedef struct { uint8_t buf[512]; unsigned bits; int ones; int nrzi; uint16_t crc; } ref_t;

static void ref_bit(ref_t *r, int b)
{
	if (b) { r->buf[r->bits / 8U] |= (uint8_t)(1U << (r->bits % 8U)); }
	r->bits++;
}
static void ref_char(ref_t *r, uint8_t d, int stuff)
{
	for (int i = 0; i < 8; i++)
	{
		int bit = d & 1;
		unsigned x = (r->crc ^ (unsigned)bit) & 1U;

		r->crc >>= 1;
		if (x) { r->crc ^= 0x8408U; }
		if (bit)
		{
			ref_bit(r, r->nrzi);
			r->ones++;
			if (stuff && (r->ones == 5)) { r->nrzi ^= 1; ref_bit(r, r->nrzi); r->ones = 0; }
		}
		else
		{
			r->nrzi ^= 1;
			ref_bit(r, r->nrzi);
			r->ones = 0;
		}
		d >>= 1;
	}
}
static void ref_str(ref_t *r, const char *s, size_t n)
{
	for (size_t i = 0; (i < n) && (s[i] != 0); i++) { ref_char(r, (uint8_t)s[i], 1); }
}
static void ref_pad6(ref_t *r, const char *s, size_t n)   /* до 6 символів <<1, добиваємо пробілами */
{
	size_t l = 0;

	while ((l < n) && (l < 6U) && (s[l] != 0)) { ref_char(r, (uint8_t)(s[l] << 1), 1); l++; }
	for (; l < 6U; l++) { ref_char(r, (uint8_t)(' ' << 1), 1); }
}

/* Складає очікуваний кадр: позивний, SSID, до двох шляхів (name без нуля -- рівно n символів), символ, рядок позиції, коментар. */
static void ref_frame(ref_t *r, const char *call, int ssid, const char (*pname)[6], const int *pssid, int npaths,
		char table, char sym, const char *lat, const char *lon, const char *comment, size_t commentMax)
{
	memset(r, 0, sizeof(*r));
	for (int i = 0; i < 16; i++) { ref_char(r, 0x7E, 0); }
	r->crc = 0xFFFF;
	for (const char *d = "APOG77"; *d; d++) { ref_char(r, (uint8_t)(*d << 1), 1); }
	ref_char(r, (uint8_t)('0' << 1), 1);
	ref_pad6(r, call, 6U);
	ref_char(r, (uint8_t)((ssid + '0') << 1), 1);
	for (int p = 0; p < npaths; p++)
	{
		ref_pad6(r, pname[p], 6U);
		ref_char(r, (uint8_t)(((pssid[p] + '0') << 1) + ((p == (npaths - 1)) ? 1 : 0)), 1);
	}
	ref_char(r, 0x03, 1);
	ref_char(r, 0xF0, 1);
	ref_char(r, '!', 1);
	ref_str(r, lat, 16U);
	ref_char(r, (uint8_t)table, 1);
	ref_str(r, lon, 16U);
	ref_char(r, (uint8_t)sym, 1);
	ref_str(r, comment, commentMax);
	{
		uint8_t lo = (uint8_t)(r->crc ^ 0xFF), hi = (uint8_t)((r->crc >> 8) ^ 0xFF);

		ref_char(r, lo, 1);
		ref_char(r, hi, 1);
	}
	for (int i = 0; i < 3; i++) { ref_char(r, 0x7E, 0); }
}

/* ---- допоміжне ----------------------------------------------------------------------------------------- */
static void cfg_init(CodeplugAPRSConfig_t *c)
{
	memset(c, 0, sizeof(*c));
	c->iconTable = 0;          /* '/' */
	c->iconIndex = ('>' - '!');
}
static void loc_init(aprsBeaconingLocation_t *l, double lat, double lon)
{
	memset(l, 0, sizeof(*l));
	l->coords.latitude = lat;
	l->coords.longitude = lon;
	l->bearing = UINT16_MAX;
}
static aprsChannelSettingsInUse_t s_chs;

/* Викликає aprsSendPacket() і порівнює кадр з еталоном. */
static void expect_frame(const char *tag, CodeplugAPRSConfig_t *cfg, aprsBeaconingLocation_t *loc, const ref_t *want, bool wantOk)
{
	bool ok;

	aprsTxProgress = APRS_TX_IDLE;
	ok = aprsSendPacket(cfg, loc, loc, &s_chs, false);
	CHECK(ok == wantOk, "%s: aprsSendPacket повернув %d, очікували %d", tag, ok, wantOk);
	if (wantOk)
	{
		CHECK(encoderData.packetBufferBitPosition == want->bits, "%s: довжина кадру %u біт, еталон %u", tag,
				(unsigned)encoderData.packetBufferBitPosition, want->bits);
		CHECK(encoderData.packetBufferBitPosition <= (AX25_PACKET_BUFFER_SIZE * 8U), "%s: кадр довший за буфер", tag);
		CHECK(memcmp(encoderData.packetBuffer, want->buf, (want->bits + 7U) / 8U) == 0, "%s: вміст кадру відрізняється від еталона", tag);
		CHECK(aprsTxProgress == APRS_TX_IN_PROGRESS, "%s: передача не запущена", tag);
	}
}

#if defined(APRS_FRAME_TEST_SMALL_BUFFER)
/* Буфер 40 байт (320 біт) -- менший за будь-який кадр: перевіряємо гілку «кадр завеликий» у aprsSendPacket() і в aprsModeTxBeacon(). */
int ovf_test(void)
{
	CodeplugAPRSConfig_t cfg;
	aprsBeaconingLocation_t loc;
	int f0 = s_fail;

	cfg_init(&cfg);
	loc_init(&loc, 50.5, 30.25);
	memset(&s_chs, 0, sizeof(s_chs));
	aprsTxProgress = APRS_TX_IDLE;
	s_timStart = 0;
	s_modeCall = "UW5ELK";
	s_modeComment = "TYT MD-UV390";
	bool ok = aprsSendPacket(&cfg, &loc, &loc, &s_chs, false);
	CHECK(ok == false, "кадр завеликий: aprsSendPacket мав відмовити");
	CHECK(aprsTxProgress == APRS_TX_FINISHED, "після відмови очікували APRS_TX_FINISHED, є %d", (int)aprsTxProgress);
	CHECK(s_timStart == 0, "після відмови TIM6 не запускається");
	CHECK(encoderData.packetBufferBitPosition == AX25_BITS_OVERFLOW, "позиція мала стати сигнальним значенням, є %u", (unsigned)encoderData.packetBufferBitPosition);
	s_modeCall = NULL;
	s_modeComment = NULL;

	/* повний шлях: aprsModeTxBeacon() -> TOOBIG, передавач вимкнено, стан IDLE, приймач відновлено */
	{
		aprsModeEff_t e;
		CodeplugChannel_t ch;

		memset(&e, 0, sizeof(e));
		strcpy(e.call, "UW5ELK");
		strcpy(e.path[0], "WIDE1"); e.pathSsid[0] = 1;
		e.hasPos = true; e.latU = 50500000; e.lonU = 30250000;
		memset(&ch, 0, sizeof(ch));
		ch.chMode = RADIO_MODE_ANALOG; ch.rxFreq = 14480000U; ch.txFreq = 14480000U;
		currentChannelData = &ch;
		nonVolatileSettings.txFreqLimited = BAND_LIMITS_NONE;
		aprsTxProgress = APRS_TX_IDLE;
		trxIsTransmitting = false;
		s_activateRx = 0;
		aprsModeTxResult_t r = aprsModeTxBeacon(&e);
		CHECK(r == APRS_MODE_TX_TOOBIG, "aprsModeTxBeacon мав повернути TOOBIG, є %d", (int)r);
		CHECK(aprsTxProgress == APRS_TX_IDLE, "передачу не завершено: стан %d", (int)aprsTxProgress);
		CHECK(trxIsTransmitting == false && trxTransmissionEnabled == false, "передавач лишився ввімкненим");
		CHECK(s_activateRx > 0, "приймач не відновлено");
		CHECK(aprsConfig == &aprsBcnData.aprsConfig[APRS_CONFIG_CHANNEL], "aprsConfig висить");
		CHECK(s_modeCall == NULL && s_modeComment == NULL, "s_modeCall/s_modeComment не обнулено");
		CHECK(s_timStart == 0, "TIM6 не мав запускатися");
	}
	return s_fail - f0;
}
#endif

int main(void)
{
#if defined(APRS_FRAME_TEST_SMALL_BUFFER)
	{
		extern int ovf_test(void);

		(void)ovf_test();
		printf("test_aprs_frame_ovf: %d перевірок, %d провалів\n", s_checks, s_fail);
		return (s_fail == 0) ? 0 : 1;
	}
#else
	CodeplugAPRSConfig_t cfg;
	aprsBeaconingLocation_t loc;
	ref_t ref;
	char p6[2][6];
	int ps[2];

	memset(&s_chs, 0, sizeof(s_chs));
	s_chs.chMode = RADIO_MODE_ANALOG;
	s_chs.rxFreq = 14480000U;
	s_chs.txFreq = 14480000U;
	memset(&aprsBcnData, 0, sizeof(aprsBcnData));

	/* 1. Стоковий шлях: позивний з імені рації, один шлях WIDE1-1 (в name -- з нулем), коментар «TYT MD-UV390». */
	cfg_init(&cfg);
	strcpy(cfg.comment, "TYT MD-UV390");
	memcpy(cfg.paths[0].name, "WIDE1\0", 6); cfg.paths[0].SSID = 1;
	cfg.senderSSID = 7;
	loc_init(&loc, 50.5, 30.25);
	memcpy(p6[0], "WIDE1\0", 6); ps[0] = 1;
	ref_frame(&ref, "RADIO1", 7, (const char (*)[6])p6, ps, 1, '/', '>', "5030.00N", "03015.00E", "TYT MD-UV390", 24U);
	expect_frame("стоковий, 1 шлях", &cfg, &loc, &ref, true);

	/* 2. Два шляхи, кожен РІВНО 6 символів без нуля, далі в конфігу -- ненульові байти (strlen пішов би далі). */
	cfg_init(&cfg);
	memset(&cfg.paths[1], 'Z', sizeof(cfg.paths[1]));   /* name[6]='ZZZZZZ' + SSID 'Z' -- і далі в структурі нулі, тож ставимо сміття після */
	memcpy(cfg.paths[0].name, "ABCDEF", 6); cfg.paths[0].SSID = 2;
	memcpy(cfg.paths[1].name, "UVWXYZ", 6); cfg.paths[1].SSID = 3;
	cfg.senderSSID = 9;
	memset(cfg.comment, 'c', sizeof(cfg.comment));      /* коментар теж без нуля (24 символи) */
	cfg.txFrequency = 0xFFFFFFFFU;                       /* QSY-прапора нема -- не використовується; ненульові байти після comment */
	loc_init(&loc, 50.5, 30.25);
	memcpy(p6[0], "ABCDEF", 6); memcpy(p6[1], "UVWXYZ", 6); ps[0] = 2; ps[1] = 3;
	ref_frame(&ref, "RADIO1", 9, (const char (*)[6])p6, ps, 2, '/', '>', "5030.00N", "03015.00E", "cccccccccccccccccccccccc", 24U);
	expect_frame("2 шляхи по 6 без нуля + коментар 24 без нуля", &cfg, &loc, &ref, true);

	/* 3. Порожній перший шлях і порожній другий: стокова логіка -- завжди щонайменше одна ланка (порожня, 6 пробілів). */
	cfg_init(&cfg);
	loc_init(&loc, 50.5, 30.25);
	memset(p6[0], 0, 6); ps[0] = 0;
	ref_frame(&ref, "RADIO1", 0, (const char (*)[6])p6, ps, 1, '/', '>', "5030.00N", "03015.00E", "", 24U);
	expect_frame("порожні шляхи, без коментаря", &cfg, &loc, &ref, true);

	/* 4. Координати 0/0, символ із вторинної таблиці. */
	cfg_init(&cfg);
	cfg.iconTable = 1; cfg.iconIndex = 20;
	loc_init(&loc, 0.0, 0.0);
	ref_frame(&ref, "RADIO1", 0, (const char (*)[6])p6, ps, 1, '\\', (char)(20 + '!'), "0000.00N", "00000.00E", "", 24U);
	expect_frame("координати 0/0", &cfg, &loc, &ref, true);

	/* 5. Режим: позивний РІВНО 6 символів, коментар режиму -- найдовший, кирилицею (cp1251 24 символи -> UTF-8 43 байти). */
	{
		static const char cp[] = "\xC0\xC1\xC2\xC3\xC4\xC5\xC6\xC7\xC8\xC9\xCA\xCB\xCC\xCD\xCE\xCF\xD0\xD1\xD2\xD3\xD4\xD5\xD6\xD7";   /* А..Ч, 24 */
		char utf[APRSM_COMMENT_AIR_MAX + 1U];
		size_t n = aprsModeCommentToUtf8(cp, utf, sizeof(utf));

		CHECK(n <= APRSM_COMMENT_AIR_MAX, "коментар UTF-8 довший за ліміт: %u", (unsigned)n);
		CHECK(n >= 42U, "кирилицею 24 символи мали дати ~42 байти, є %u", (unsigned)n);
		cfg_init(&cfg);
		memcpy(cfg.paths[0].name, "WIDE1\0", 6); cfg.paths[0].SSID = 1;
		memcpy(cfg.paths[1].name, "WIDE2\0", 6); cfg.paths[1].SSID = 2;
		loc_init(&loc, 50.5, 30.25);
		s_modeCall = "UW5ELK";
		s_modeComment = utf;
		memcpy(p6[0], "WIDE1\0", 6); memcpy(p6[1], "WIDE2\0", 6); ps[0] = 1; ps[1] = 2;
		ref_frame(&ref, "UW5ELK", 0, (const char (*)[6])p6, ps, 2, '/', '>', "5030.00N", "03015.00E", utf, APRSM_COMMENT_AIR_MAX);
		expect_frame("режим: UTF-8 коментар найдовший", &cfg, &loc, &ref, true);
		CHECK(encoderData.packetBufferBitPosition < (AX25_PACKET_BUFFER_SIZE * 8U) / 2U, "кадр режиму займає понад половину буфера: %u біт",
				(unsigned)encoderData.packetBufferBitPosition);

		/* порожній позивний режиму -- шість пробілів, без виходу за межі */
		s_modeCall = "";
		ref_frame(&ref, "", 0, (const char (*)[6])p6, ps, 2, '/', '>', "5030.00N", "03015.00E", utf, APRSM_COMMENT_AIR_MAX);
		expect_frame("режим: порожній позивний", &cfg, &loc, &ref, true);
		s_modeCall = NULL;
		s_modeComment = NULL;
	}

	/* 6. Захист довжини: «коментар режиму» без нуля й набагато довший за ліміт (600 байт) -- у кадр іде рівно APRSM_COMMENT_AIR_MAX
	 *    байт (рахуємо БАЙТИ, не символи); кадр влазить, нічого не пишеться за межі. */
	{
		static char big[600];

		memset(big, 'x', sizeof(big));   /* БЕЗ нуля в кінці */
		cfg_init(&cfg);
		memcpy(cfg.paths[0].name, "WIDE1\0", 6); cfg.paths[0].SSID = 1;
		loc_init(&loc, 50.5, 30.25);
		s_modeCall = "UW5ELK";
		s_modeComment = big;
		memcpy(p6[0], "WIDE1\0", 6); ps[0] = 1;
		ref_frame(&ref, "UW5ELK", 0, (const char (*)[6])p6, ps, 1, '/', '>', "5030.00N", "03015.00E", big, APRSM_COMMENT_AIR_MAX);
		expect_frame("режим: коментар без нуля 600 байт обрізано до ліміту", &cfg, &loc, &ref, true);
		s_modeCall = NULL;
		s_modeComment = NULL;
	}

	/* 7. Цикли по рядку завершуються: довший за буфер рядок з «важких» для стаффінгу байтів переповнює кадр -- без виходу за межі
	 *    (раніше лічильник uint8_t на рядку від 256 байт переходив через 0 і цикл не закінчувався б). */
	{
		static char big[400];
		AX25Encoder_t e;

		memset(big, 0x7F, sizeof(big) - 1U);   /* сім одиниць підряд -- максимум стаффінгу */
		big[sizeof(big) - 1U] = 0;
		memset(&e, 0, sizeof(e));
		enqueueString(&e, big);   /* має повернутися */
		CHECK(e.packetBufferBitPosition == AX25_BITS_OVERFLOW, "довгий рядок мав переповнити кадр, позиція %u", (unsigned)e.packetBufferBitPosition);
		memset(&e, 0, sizeof(e));
		enqueueStringN(&e, big, 24U);
		CHECK(e.packetBufferBitPosition >= 24U * 8U, "обмежений рядок 24: %u біт", (unsigned)e.packetBufferBitPosition);
		CHECK(e.packetBufferBitPosition != AX25_BITS_OVERFLOW, "24 символи не мали переповнити");
		/* після переповнення подальші біти ігноруються */
		memset(&e, 0, sizeof(e));
		e.packetBufferBitPosition = AX25_BITS_MAX;
		enqueueBit(&e, true);
		enqueueBit(&e, true);
		CHECK(e.packetBufferBitPosition == AX25_BITS_OVERFLOW, "біт за межею мав дати сигнальне значення");
	}

	/* 7а. Недійсна позиція (NaN, поза діапазоном) -- кадр НЕ складається (приведення NaN до цілого -- невизначена поведінка). */
	{
		static const double badLat[] = { 0.0 / 0.0, 95.0, -91.0, 50.5, 50.5 };
		static const double badLon[] = { 30.25, 30.25, 30.25, 181.0, 1.0 / 0.0 };

		for (unsigned k = 0; k < sizeof(badLat) / sizeof(badLat[0]); k++)
		{
			cfg_init(&cfg);
			loc_init(&loc, badLat[k], badLon[k]);
			aprsTxProgress = APRS_TX_IDLE;
			s_timStart = 0;
			bool ok = aprsSendPacket(&cfg, &loc, &loc, &s_chs, false);
			CHECK(ok == false, "недійсна позиція #%u: aprsSendPacket мав відмовити", k);
			CHECK(aprsTxProgress == APRS_TX_FINISHED, "недійсна позиція #%u: стан %d", k, (int)aprsTxProgress);
			CHECK(s_timStart == 0, "недійсна позиція #%u: TIM6 не мав запускатися", k);
			CHECK(encoderData.packetBufferBitPosition != AX25_BITS_OVERFLOW, "недійсна позиція #%u: це не переповнення буфера", k);
		}
		/* граничні дійсні значення проходять */
		cfg_init(&cfg);
		loc_init(&loc, 90.0, 180.0);
		aprsTxProgress = APRS_TX_IDLE;
		CHECK(aprsSendPacket(&cfg, &loc, &loc, &s_chs, false) == true, "позиція 90/180 має проходити");
		loc_init(&loc, -90.0, -180.0);
		aprsTxProgress = APRS_TX_IDLE;
		CHECK(aprsSendPacket(&cfg, &loc, &loc, &s_chs, false) == true, "позиція -90/-180 має проходити");
	}

	/* 8. aprsModeTxBeacon(): aprsConfig після виклику -- НЕ на стеку; друга передача; стоковий маяк далі бачить свій конфіг. */
	{
		/* ця частина потребує заглушок TX-ланцюжка -- див. нижче tx_chain_test() */
		extern int tx_chain_test(void);
		s_fail += tx_chain_test();
	}

	printf("test_aprs_frame: %d перевірок, %d провалів\n", s_checks, s_fail);
	return (s_fail == 0) ? 0 : 1;
#endif
}

/* ---- ланцюжок aprsModeTxBeacon() ----------------------------------------------------------------------- */
static uint8_t s_cfgFlagsSeen;
int tx_chain_test(void)
{
	int fail0 = s_fail;

	/* 8а. Висячий вказівник: після aprsModeTxBeacon() глобальний aprsConfig -- у aprsBcnData (статика), не на стеку. */
	{
		aprsModeEff_t e;
		int dummy;

		memset(&e, 0, sizeof(e));
		strcpy(e.call, "UW5ELK");
		strcpy(e.path[0], "WIDE1"); e.pathSsid[0] = 1;
		strcpy(e.comment, "TYT MD-UV390");
		e.hasPos = true; e.latU = 50500000; e.lonU = 30250000;
		e.iconTable = 0; e.iconIndex = ('>' - '!');

		CodeplugChannel_t ch;
		memset(&ch, 0, sizeof(ch));
		ch.chMode = RADIO_MODE_ANALOG; ch.rxFreq = 14480000U; ch.txFreq = 14480000U;
		currentChannelData = &ch;
		nonVolatileSettings.txFreqLimited = BAND_LIMITS_NONE;
		aprsTxProgress = APRS_TX_IDLE;

		aprsModeTxResult_t r = aprsModeTxBeacon(&e);

		CHECK(r == APRS_MODE_TX_OK, "aprsModeTxBeacon повернув %d", (int)r);
		CHECK(aprsConfig == &aprsBcnData.aprsConfig[APRS_CONFIG_CHANNEL], "aprsConfig не повернуто на статичний конфіг (висить на стеку?)");
		CHECK(((uintptr_t)aprsConfig < (uintptr_t)&dummy - 65536U) || ((uintptr_t)aprsConfig > (uintptr_t)&dummy + 65536U),
				"aprsConfig лежить поруч зі стеком");
		CHECK(s_modeCall == NULL && s_modeComment == NULL, "s_modeCall/s_modeComment не обнулено");

		/* недійсна позиція режиму (широта 95°): маяк не йде, передавач вимкнено, результат -- «нема позиції» */
		{
			aprsModeEff_t bad = e;

			bad.latU = 95000000;
			aprsTxProgress = APRS_TX_IDLE;
			trxIsTransmitting = false;
			r = aprsModeTxBeacon(&bad);
			CHECK(r == APRS_MODE_TX_NOPOS, "широта 95°: очікували NOPOS, є %d", (int)r);
			CHECK(aprsTxProgress == APRS_TX_IDLE && trxIsTransmitting == false, "широта 95°: передачу не завершено");
			CHECK(aprsConfig == &aprsBcnData.aprsConfig[APRS_CONFIG_CHANNEL], "широта 95°: aprsConfig висить");
		}

		/* друга передача поспіль */
		aprsTxProgress = APRS_TX_IDLE;
		trxIsTransmitting = false;
		r = aprsModeTxBeacon(&e);
		CHECK(r == APRS_MODE_TX_OK, "друга передача: %d", (int)r);
		CHECK(aprsConfig == &aprsBcnData.aprsConfig[APRS_CONFIG_CHANNEL], "друга передача: aprsConfig висить");

		/* стоковий маяк після маяка режиму: «безшумно» береться з АРГУМЕНТУ, а не зі сміття на колишньому стеку */
		CodeplugAPRSConfig_t sc;
		aprsBeaconingLocation_t sl;

		cfg_init(&sc);
		sc.flags = CODEPLUG_APRS_CONFIG_FLAG_BEACONING_SILENTLY;
		loc_init(&sl, 50.5, 30.25);
		aprsTxProgress = APRS_TX_IDLE;
		s_ampEnable = s_ampDisable = 0;
		(void)aprsSendPacket(&sc, &sl, &sl, &s_chs, false);
		CHECK(s_ampDisable > 0 && s_ampEnable == 0, "стоковий маяк із прапором «безшумно»: amp вмикався (%d/%d)", s_ampEnable, s_ampDisable);

		sc.flags = 0;
		aprsTxProgress = APRS_TX_IDLE;
		s_ampEnable = s_ampDisable = 0;
		(void)aprsSendPacket(&sc, &sl, &sl, &s_chs, false);
		CHECK(s_ampEnable > 0 && s_ampDisable == 0, "стоковий маяк без прапора: amp не вмикався (%d/%d)", s_ampEnable, s_ampDisable);
		(void)s_cfgFlagsSeen;
	}
	return s_fail - fail0;
}
