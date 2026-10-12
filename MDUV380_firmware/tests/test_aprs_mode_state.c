/*
 * test_aprs_mode_state.c -- хостовий тест СТАНУ «Режиму APRS» (R10, functions/aprs_mode.c).
 *
 * Лінкує РЕАЛЬНІ aprs_mode.c, aprs_mode_cfg.c і callReplay.c (той самий код, що йде в прошивку); усе залізо
 * (радіо, меню, кодплуг, приймач, бікон) -- заглушки нижче, що записують виклики. Перевіряє те, що не видно
 * без рації, але видно в логіці:
 *  - вхід: відмови (не канал/VFO, хотспот, TX), збережений канал, «канал» режиму (аналоговий FM, 12,5 кГц,
 *    частота), приймач хоче слухати, позичений буфер "Переслухати" інвалідовано;
 *  - вихід: вказівник каналу, режим, "Запис RX", таймери й стоковий авто-бікон -- як було; ідемпотентність;
 *    вихід посеред TX; вихід при зміні екрана (тік);
 *  - налаштування: зміна частоти перелаштовує радіо, відкладений запис у флеш (2 с) і запис при виході,
 *    повторний вхід читає збережене;
 *  - маяк: ручний / від PTT (проміжок 3 с) / періодичний; зайнята частота -- очікування 3 с і повтор через
 *    10 с; відмови (нема позивного / позиції) не зациклюють повтор;
 *  - «останній пакет» для монітора.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "functions/aprs_mode.h"
#include "functions/aprs.h"
#include "functions/callReplay.h"
#include "functions/codeplug.h"
#include "functions/settings.h"
#include "functions/sound.h"
#include "functions/trx.h"
#include "user_interface/menuSystem.h"
#include "user_interface/uiGlobals.h"
#include "functions/aprs_rx.h"

#if !defined(APRS_RX) || !defined(ENABLE_CALL_REPLAY)
#error "потрібні APRS_RX і ENABLE_CALL_REPLAY"
#endif

static int s_fail = 0;
static int s_checks = 0;
#define CHECK(c, ...) do { s_checks++; if (!(c)) { s_fail++; printf("ПРОВАЛ %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

/* ---- стан заглушок -------------------------------------------------------------------------------------- */
static uint32_t s_now = 100000;
static int s_rootMenu = UI_CHANNEL_MODE;
static int s_curMenu = MENU_APRS_HUB;

static int s_tuneCalls, s_loadChanCalls, s_loadVfoCalls, s_resetTimers, s_setSuspendTrue, s_setSuspendFalse, s_rxSuspend, s_abortTx, s_stopScanCh, s_stopScanVfo, s_replayStop;
static uint32_t s_tuneFreq;
static int s_tuneMode = -1;
static int s_tuneBw = -1;
static aprsBeaconingMode_t s_bcnMode = APRS_BEACONING_MODE_AUTO;
static bool s_bcnSuspended = false;
static bool s_rxBusy = false;
static bool s_led = false;
static int s_txCalls;
static aprsModeTxResult_t s_txResult = APRS_MODE_TX_OK;
static aprsModeEff_t s_txLastEff;
static int s_melody, s_notify;
static uint8_t s_flash[APRSM_BLOCK_LEN];
static bool s_flashValid = false;
static int s_flashWrites;
static CodeplugAPRSConfig_t s_apc;
static bool s_apcValid = true;
static char s_radioName[16] = "UW5ELK";
static bool s_locValid = true;

uiDataGlobal_t uiDataGlobal;
CodeplugChannel_t *currentChannelData;
volatile int settingsUsbMode = 0;
volatile bool trxTransmissionEnabled = false;
volatile bool trxIsTransmitting = false;
volatile aprsSendProgress_t aprsTxProgress = APRS_TX_IDLE;
const int16_t MELODY_ERROR_BEEP[] = { 0 };

static aprsRxUi_t s_rxUi;
aprsRxUi_t *aprsRxUi(void) { return &s_rxUi; }
uint32_t ticksGetMillis(void) { return s_now; }
uint8_t LedRead(LEDs_t l) { (void)l; return s_led ? 1 : 0; }
void vTaskDelay(uint32_t t) { (void)t; }
void soundSetMelody(const int16_t *m) { (void)m; s_melody++; }
void uiNotificationShow(uiNotificationType_t t, uiNotificationID_t i, uint32_t ms, const char *m, bool r) { (void)t; (void)i; (void)ms; (void)m; (void)r; s_notify++; }

int menuSystemGetRootMenuNumber(void) { return s_rootMenu; }
int menuSystemGetCurrentMenuNumber(void) { return s_curMenu; }
void uiChannelModeStopScanning(void) { s_stopScanCh++; uiDataGlobal.Scan.active = false; }
void uiVFOModeStopScanning(void) { s_stopScanVfo++; uiDataGlobal.Scan.active = false; }
void uiChannelModeLoadChannelData(bool a, bool b) { (void)a; (void)b; s_loadChanCalls++; }
void uiVFOModeLoadChannelData(bool a) { (void)a; s_loadVfoCalls++; }

RadioDevice_t radioSetTRxDevice(RadioDevice_t d) { return d; }
void trxSetFrequency(uint32_t rx, uint32_t tx, int m) { (void)tx; (void)m; s_tuneFreq = rx; s_tuneCalls++; }
void trxSetModeAndBandwidth(int mode, bool bw25) { s_tuneMode = mode; s_tuneBw = bw25 ? 25 : 12; }
void trxSetRxCSS(RadioDevice_t d, uint16_t t) { (void)d; (void)t; }
void trxSetTxCSS(uint16_t t) { (void)t; }
void trxPostponeReadRSSIAndNoise(uint32_t ms) { (void)ms; }

aprsBeaconingMode_t aprsBeaconingGetMode(void) { return s_bcnMode; }
bool aprsBeaconingIsSuspended(void) { return s_bcnSuspended; }
void aprsBeaconingSetSuspend(bool s) { s_bcnSuspended = s; if (s) { s_setSuspendTrue++; } else { s_setSuspendFalse++; } }
void aprsBeaconingResetTimers(void) { s_resetTimers++; }
void aprsModeAbortTx(void) { s_abortTx++; aprsTxProgress = APRS_TX_IDLE; }
aprsModeTxResult_t aprsModeTxBeacon(const aprsModeEff_t *e)
{
	s_txCalls++;
	s_txLastEff = *e;
	return s_txResult;
}

bool aprsRxBusy(uint32_t ms) { (void)ms; return s_rxBusy; }
void aprsRxSuspendForAudio(void) { s_rxSuspend++; }
void callReplayStop(void) { s_replayStop++; }

bool codeplugGetOpenGD77CustomDataBounded(CodeplugCustomDataType_t t, uint8_t *buf, int maxLen)
{
	if ((t != CODEPLUG_CUSTOM_DATA_TYPE_APRS_MODE_CFG) || (s_flashValid == false) || (maxLen < APRSM_BLOCK_LEN)) { return false; }
	memcpy(buf, s_flash, APRSM_BLOCK_LEN);
	return true;
}
bool codeplugSetOpenGD77CustomData(CodeplugCustomDataType_t t, uint8_t *buf, int len)
{
	if ((t != CODEPLUG_CUSTOM_DATA_TYPE_APRS_MODE_CFG) || (len != APRSM_BLOCK_LEN)) { return false; }
	memcpy(s_flash, buf, APRSM_BLOCK_LEN);
	s_flashValid = true;
	s_flashWrites++;
	return true;
}
uint8_t codeplugChannelSetFlag(CodeplugChannel_t *c, ChannelFlag_t f, uint8_t v)
{
	if (f == CHANNEL_FLAG_BW_25K) { c->flag4 = (uint8_t)((c->flag4 & ~0x02U) | (v ? 0x02U : 0U)); }
	return v;
}
void codeplugGetRadioName(char *b) { memcpy(b, s_radioName, 16); }
int codeplugAPRSConfigGetCount(void) { return s_apcValid ? 1 : 0; }
bool codeplugAPRSGetDataForIndex(int i, CodeplugAPRSConfig_t *b) { if (!s_apcValid || (i < 1)) { return false; } memcpy(b, &s_apc, sizeof(*b)); return true; }
bool settingsLocationIsValid(void) { return s_locValid; }
double settingsLocationGetLatitude(void) { return 50.45; }
double settingsLocationGetLongitude(void) { return 30.52; }

/* ---- допоміжне ------------------------------------------------------------------------------------------ */

static CodeplugChannel_t s_userChan;

static void resetWorld(void)
{
	s_now = 100000;
	s_rootMenu = UI_CHANNEL_MODE; s_curMenu = MENU_APRS_HUB;
	s_tuneCalls = s_loadChanCalls = s_loadVfoCalls = s_resetTimers = s_setSuspendTrue = s_setSuspendFalse = 0;
	s_rxSuspend = s_abortTx = s_stopScanCh = s_stopScanVfo = s_replayStop = s_txCalls = s_melody = s_notify = 0;
	s_flashWrites = 0;
	s_tuneFreq = 0; s_tuneMode = -1; s_tuneBw = -1;
	s_bcnMode = APRS_BEACONING_MODE_OFF; s_bcnSuspended = false;
	s_rxBusy = false; s_led = false; s_txResult = APRS_MODE_TX_OK;
	s_flashValid = false;
	memset(s_flash, 0, sizeof(s_flash));
	settingsUsbMode = 0; trxTransmissionEnabled = false; trxIsTransmitting = false; aprsTxProgress = APRS_TX_IDLE;
	memset(&uiDataGlobal, 0, sizeof(uiDataGlobal));
	memset(&s_userChan, 0, sizeof(s_userChan));
	s_userChan.rxFreq = 43025000UL;   /* DMR-канал користувача */
	s_userChan.chMode = RADIO_MODE_DIGITAL;
	currentChannelData = &s_userChan;
	memset(&s_rxUi, 0, sizeof(s_rxUi));
	memset(&s_apc, 0xFF, sizeof(s_apc));
	memset(s_apc.name, 0, sizeof(s_apc.name));
	s_apc.senderSSID = 7;
	s_apc.txFrequency = 14480000UL;
	memset(s_apc.paths, 0, sizeof(s_apc.paths));
	memcpy(s_apc.paths[0].name, "WIDE1", 5); s_apc.paths[0].SSID = 1;
	memcpy(s_apc.paths[1].name, "WIDE2", 5); s_apc.paths[1].SSID = 1;
	s_apc.iconTable = 0; s_apc.iconIndex = 29;
	memset(s_apc.comment, 0, sizeof(s_apc.comment));
	s_apc.flags = 0;
	s_apcValid = true;
	s_locValid = true;
	strcpy(s_radioName, "UW5ELK");
}

static void fillRing(int groups)
{
	uint8_t g[CALL_REPLAY_GROUP_BYTES];

	callReplayInit();
	callReplaySetRecordingEnabled(true);
	for (int i = 0; i < groups; i++)
	{
		memset(g, (uint8_t)(i + 1), sizeof(g));
		callReplayCaptureTick(g, false, (uint32_t)(i * 60));
	}
}

static void tickMs(uint32_t ms) { s_now += ms; aprsModeTick(); }

/* ---- тести ---------------------------------------------------------------------------------------------- */

static void testEnterExit(void)
{
	CodeplugChannel_t *modeChan;

	resetWorld();
	fillRing(40);
	CHECK(callReplayGroupCount() == 40, "у кільці 40 груп до входу: %lu", (unsigned long)callReplayGroupCount());
	callReplaySetRecordingEnabled(true);

	CHECK(aprsModeIsActive() == false, "режим не активний до входу");
	CHECK(aprsModeEnter(), "вхід з каналу має вдатися");
	CHECK(aprsModeIsActive() && s_rxUi.modeOn == 1, "активний, modeOn = 1");
	CHECK(s_replayStop == 1, "відтворення «Переслухати» зупинено перед позичанням");
	CHECK(s_rxSuspend >= 1, "приймач R8 зупинено перед перебудовою радіо");
	CHECK(callReplayIsBorrowed(), "кільце позичене");
	CHECK(callReplayGroupCount() == 0 && callReplayIsEmpty(), "запис «Переслухати» явно інвалідовано (count = 0)");
	modeChan = currentChannelData;
	CHECK(modeChan != &s_userChan, "currentChannelData вказує на «канал» режиму");
	CHECK(modeChan->chMode == RADIO_MODE_ANALOG, "аналоговий FM");
	CHECK(modeChan->rxFreq == 14480000UL && modeChan->txFreq == 14480000UL, "частота каналу режиму = 144.800 (з конфігу кодплуга)");
	CHECK(s_tuneCalls == 1 && s_tuneFreq == 14480000UL, "радіо перелаштовано на 144.800");
	CHECK(s_tuneMode == RADIO_MODE_ANALOG && s_tuneBw == 12, "аналог, 12,5 кГц");
	CHECK(aprsModeUi()->page == APRS_MODE_PAGE_MONITOR, "початкова сторінка -- Монітор");
	CHECK(aprsModeEff()->ssid == 7 && strcmp(aprsModeEff()->call, "UW5ELK") == 0, "позивний з імені рації, ssid з конфігу");

	/* повторний вхід -- ідемпотентний */
	CHECK(aprsModeEnter() && s_tuneCalls == 1, "повторний вхід нічого не міняє");

	/* власна інформація для приймача */
	{
		char call[8]; uint8_t ssid; bool hp; int32_t la, lo;
		CHECK(aprsModeOwnInfo(call, &ssid, &hp, &la, &lo) && strcmp(call, "UW5ELK") == 0 && ssid == 7 && hp, "aprsModeOwnInfo у режимі");
	}

	/* вихід */
	aprsModeExit();
	CHECK(aprsModeIsActive() == false && s_rxUi.modeOn == 0, "неактивний, modeOn = 0");
	CHECK(currentChannelData == &s_userChan, "вказівник каналу повернуто");
	CHECK(s_userChan.rxFreq == 43025000UL && s_userChan.chMode == RADIO_MODE_DIGITAL, "канал користувача не зіпсовано");
	CHECK(s_loadChanCalls == 1 && s_loadVfoCalls == 0, "канал перезавантажено (режим каналу)");
	CHECK(callReplayIsBorrowed() == false, "кільце повернуто");
	CHECK(callReplayGroupCount() == 0, "старий запис свідомо втрачено, кільце порожнє");
	CHECK(callReplayIsRecordingEnabled(), "«Запис RX» повернуто (був увімкнений)");
	CHECK(s_resetTimers == 1, "таймери бікона скинуто");
	{
		char call[8]; uint8_t ssid; bool hp; int32_t la, lo;
		CHECK(aprsModeOwnInfo(call, &ssid, &hp, &la, &lo) == false, "після виходу aprsModeOwnInfo = false");
	}
	aprsModeExit();
	CHECK(s_loadChanCalls == 1 && s_resetTimers == 1, "повторний вихід -- нічого не робить");

	/* кільце знову працює */
	{
		uint8_t g[CALL_REPLAY_GROUP_BYTES];
		memset(g, 9, sizeof(g));
		callReplayCaptureTick(g, false, 1000);
		CHECK(callReplayGroupCount() == 1, "після виходу «Переслухати» знову пише");
	}
}

static void testRecordingOff(void)
{
	resetWorld();
	fillRing(5);
	callReplaySetRecordingEnabled(false);   /* користувач вимкнув "Запис RX" */
	CHECK(aprsModeEnter(), "вхід");
	aprsModeExit();
	CHECK(callReplayIsRecordingEnabled() == false, "«Запис RX» лишився вимкнений");
}

static void testVfo(void)
{
	resetWorld();
	s_rootMenu = UI_VFO_MODE;
	uiDataGlobal.Scan.active = true;
	CHECK(aprsModeEnter(), "вхід з VFO");
	CHECK(s_stopScanVfo == 1 && s_stopScanCh == 0, "сканування VFO зупинено");
	aprsModeExit();
	CHECK(s_loadVfoCalls == 1 && s_loadChanCalls == 0, "VFO перезавантажено");
}

static void testRefusals(void)
{
	resetWorld();
	s_rootMenu = UI_LOCK_SCREEN;
	CHECK(aprsModeEnter() == false, "не канал і не VFO -- відмова");
	s_rootMenu = UI_CHANNEL_MODE;
	settingsUsbMode = USB_MODE_HOTSPOT;
	CHECK(aprsModeEnter() == false, "хотспот -- відмова");
	settingsUsbMode = 0;
	aprsTxProgress = APRS_TX_IN_PROGRESS;
	CHECK(aprsModeEnter() == false, "йде маяк -- відмова");
	aprsTxProgress = APRS_TX_IDLE;
	trxIsTransmitting = true;
	CHECK(aprsModeEnter() == false, "йде передача -- відмова");
	trxIsTransmitting = false;
	trxTransmissionEnabled = true;
	CHECK(aprsModeEnter() == false, "TX увімкнено -- відмова");
	trxTransmissionEnabled = false;
	CHECK(aprsModeIsActive() == false && currentChannelData == &s_userChan && callReplayIsBorrowed() == false, "після відмов нічого не змінено");
	CHECK(s_tuneCalls == 0, "радіо не чіпали");
}

static void testStockBeaconing(void)
{
	resetWorld();
	s_bcnMode = APRS_BEACONING_MODE_AUTO;
	CHECK(aprsModeEnter(), "вхід");
	CHECK(s_setSuspendTrue == 1 && s_bcnSuspended, "стоковий авто-бікон призупинено");
	aprsModeExit();
	CHECK(s_setSuspendFalse == 1 && s_bcnSuspended == false, "і відновлено при виході");

	resetWorld();
	s_bcnMode = APRS_BEACONING_MODE_AUTO;
	s_bcnSuspended = true;   /* користувач сам призупинив */
	CHECK(aprsModeEnter(), "вхід");
	CHECK(s_setSuspendTrue == 0, "уже призупинений -- не чіпаємо");
	aprsModeExit();
	CHECK(s_setSuspendFalse == 0 && s_bcnSuspended, "вихід не знімає чужу паузу");

	resetWorld();
	s_bcnMode = APRS_BEACONING_MODE_OFF;
	CHECK(aprsModeEnter(), "вхід");
	aprsModeExit();
	CHECK(s_setSuspendTrue == 0 && s_setSuspendFalse == 0, "бікон вимкнений -- не чіпаємо");
}

static void testExitPaths(void)
{
	resetWorld();
	CHECK(aprsModeEnter(), "вхід");
	aprsTxProgress = APRS_TX_IN_PROGRESS;
	aprsModeExit();
	CHECK(s_abortTx == 1 && aprsModeIsActive() == false && currentChannelData == &s_userChan, "вихід посеред TX: передачу перервано, канал повернуто");

	resetWorld();
	CHECK(aprsModeEnter(), "вхід");
	s_curMenu = MENU_GENERAL;   /* екран змінився (push меню, таймаут) */
	aprsModeTick();
	CHECK(aprsModeIsActive() == false && currentChannelData == &s_userChan, "тік: екран не «Опції рації» -- вихід");

	resetWorld();
	CHECK(aprsModeEnter(), "вхід");
	settingsUsbMode = USB_MODE_HOTSPOT;
	aprsModeTick();
	CHECK(aprsModeIsActive() == false, "тік: хотспот вхопив рацію -- вихід");
}

static void testSettings(void)
{
	aprsModeCfg_t *c;
	uint8_t blk[APRSM_BLOCK_LEN];

	resetWorld();
	CHECK(aprsModeEnter(), "вхід");
	c = aprsModeCfg();
	c->freq = 14482500UL;
	c->ov |= APRSM_OV_FREQ;
	aprsModeCfgChanged(APRSM_OV_FREQ);
	CHECK(s_tuneCalls == 2 && s_tuneFreq == 14482500UL, "зміна частоти перелаштовує радіо");
	CHECK(currentChannelData->rxFreq == 14482500UL && aprsModeEff()->freq == 14482500UL, "«канал» режиму на новій частоті");
	CHECK(s_flashWrites == 0, "у флеш ще не писали (відкладений запис)");
	tickMs(1000);
	CHECK(s_flashWrites == 0, "через 1 с ще не пишемо");
	tickMs(1500);
	CHECK(s_flashWrites == 1, "через 2,5 с після останньої зміни -- один запис");
	tickMs(5000);
	CHECK(s_flashWrites == 1, "без нових змін -- більше не пишемо");

	/* зміна під час редагування кілька разів поспіль -- один запис */
	c->ssid = 3; c->ov |= APRSM_OV_SSID; aprsModeCfgChanged(APRSM_OV_SSID);
	tickMs(500);
	c->ssid = 4; aprsModeCfgChanged(APRSM_OV_SSID);
	tickMs(500);
	c->ssid = 5; aprsModeCfgChanged(APRSM_OV_SSID);
	CHECK(s_flashWrites == 1, "поки редагуємо -- не пишемо");
	/* вихід зберігає невідкладене */
	aprsModeExit();
	CHECK(s_flashWrites == 2, "при виході -- запис");
	CHECK(s_loadChanCalls == 1, "вихід відновив канал");

	/* у флеші -- те, що треба */
	{
		aprsModeCfg_t chk;
		memcpy(blk, s_flash, sizeof(blk));
		CHECK(aprsModeCfgFromBytes(&chk, blk, sizeof(blk)) && chk.freq == 14482500UL && chk.ssid == 5 && (chk.ov & APRSM_OV_FREQ), "збережений блок розбирається і збігається");
	}

	/* повторний вхід читає збережене */
	CHECK(aprsModeEnter(), "повторний вхід");
	CHECK(aprsModeEff()->freq == 14482500UL && aprsModeEff()->ssid == 5, "налаштування підхоплено з флеша");
	CHECK(s_tuneFreq == 14482500UL, "радіо одразу на збереженій частоті");
	aprsModeExit();
	CHECK(s_flashWrites == 2, "вихід без змін -- не пишемо");

	/* «Скинути» */
	CHECK(aprsModeEnter(), "вхід");
	aprsModeCfgReset();
	CHECK(aprsModeEff()->freq == 14480000UL && aprsModeEff()->ssid == 7 && aprsModeCfg()->ov == 0, "скидання повертає типові значення з кодплуга");
	CHECK(s_tuneFreq == 14480000UL, "і частоту радіо");
	aprsModeExit();

	/* зіпсований блок у флеші -- усе типове */
	s_flash[10] ^= 0x55;
	CHECK(aprsModeEnter(), "вхід зі зіпсованим блоком");
	CHECK(aprsModeEff()->freq == 14480000UL && aprsModeCfg()->ov == 0, "зіпсований блок ігноровано");
	aprsModeExit();
}

static void testDefaultsFallback(void)
{
	resetWorld();
	s_apcValid = false;     /* у кодплузі конфігу APRS нема */
	s_locValid = false;
	CHECK(aprsModeEnter(), "вхід без конфігу APRS");
	CHECK(aprsModeEff()->freq == APRSM_FREQ_DEFAULT && s_tuneFreq == 14480000UL, "запасна частота 144.800");
	CHECK(strcmp(aprsModeEff()->path[0], "WIDE1") == 0 && aprsModeEff()->pathSsid[1] == 1, "запасні шляхи");
	CHECK(aprsModeEff()->hasPos == false, "позиції нема");
	aprsModeExit();

	resetWorld();
	s_apc.txFrequency = 14482500UL;
	s_userChan.aprsConfigIndex = 1;
	CHECK(aprsModeEnter(), "вхід");
	CHECK(s_tuneFreq == 14482500UL, "частота з txFrequency конфігу каналу");
	aprsModeExit();
}

static void testBeacons(void)
{
	aprsModeCfg_t *c;

	/* ручний маяк */
	resetWorld();
	CHECK(aprsModeEnter(), "вхід");
	tickMs(100);
	CHECK(s_txCalls == 0, "без запиту маяк не йде");
	aprsModeRequestBeacon();
	tickMs(10);
	CHECK(s_txCalls == 1, "ручний маяк передано");
	CHECK(aprsModeBeaconCount() == 1 && aprsModeBeaconState() == APRS_MODE_BCN_SENT, "лічильник і стан");
	CHECK(aprsModeLastBeaconAgeSec() < 2, "вік останнього маяка");
	CHECK(strcmp(s_txLastEff.call, "UW5ELK") == 0 && s_txLastEff.ssid == 7, "у маяк пішли ефективні налаштування");
	tickMs(4000);
	CHECK(aprsModeBeaconState() == APRS_MODE_BCN_NONE, "«Передано» зникає через кілька секунд");
	CHECK(s_txCalls == 1, "один запит -- один маяк");
	aprsModeExit();

	/* PTT: 3 с між маяками */
	resetWorld();
	CHECK(aprsModeEnter(), "вхід");
	aprsModeOnPtt();
	tickMs(10);
	CHECK(s_txCalls == 1, "PTT -- маяк");
	aprsModeOnPtt();   /* дзвінкіт/повтор через 1 с */
	tickMs(1000);
	CHECK(s_txCalls == 1, "повторний PTT раніше 3 с ігнорується");
	tickMs(3000);
	aprsModeOnPtt();
	tickMs(10);
	CHECK(s_txCalls == 2, "PTT після 3 с -- знову маяк");
	aprsModeExit();

	/* періодичний: 5 хв */
	resetWorld();
	CHECK(aprsModeEnter(), "вхід");
	c = aprsModeCfg();
	c->interval = 1;   /* 5 хв */
	aprsModeCfgChanged(0);
	CHECK(aprsModeNextBeaconSec() != 0xFFFFFFFFUL && aprsModeNextBeaconSec() <= 300 && aprsModeNextBeaconSec() >= 299, "до наступного маяка ~300 с: %lu", (unsigned long)aprsModeNextBeaconSec());
	tickMs(299000);
	CHECK(s_txCalls == 0, "за 299 с маяка ще нема");
	tickMs(2000);
	CHECK(s_txCalls == 1, "через 5 хв -- перший маяк");
	CHECK(aprsModeNextBeaconSec() >= 298 && aprsModeNextBeaconSec() <= 300, "наступний знову через 5 хв: %lu", (unsigned long)aprsModeNextBeaconSec());
	tickMs(300000);
	CHECK(s_txCalls == 2, "ще через 5 хв -- другий маяк");
	/* вимкнули інтервал */
	c->interval = 0;
	aprsModeCfgChanged(0);
	CHECK(aprsModeNextBeaconSec() == 0xFFFFFFFFUL, "інтервал 0 -- наступного нема");
	tickMs(600000);
	CHECK(s_txCalls == 2, "вручну -- більше не йде");
	aprsModeExit();

	/* інтервал не збивається від зміни інших полів */
	resetWorld();
	CHECK(aprsModeEnter(), "вхід");
	c = aprsModeCfg();
	c->interval = 2;   /* 10 хв */
	aprsModeCfgChanged(0);
	tickMs(120000);
	c->ssid = 3; c->ov |= APRSM_OV_SSID;
	aprsModeCfgChanged(APRSM_OV_SSID);
	CHECK(aprsModeNextBeaconSec() <= 480 && aprsModeNextBeaconSec() >= 478, "зміна SSID не скидає відлік: %lu", (unsigned long)aprsModeNextBeaconSec());
	aprsModeExit();

	/* зайнята частота: чекаємо до 3 с, потім відмова і повтор через 10 с */
	resetWorld();
	CHECK(aprsModeEnter(), "вхід");
	s_rxBusy = true;
	aprsModeRequestBeacon();
	tickMs(10);
	CHECK(s_txCalls == 0 && aprsModeBeaconState() == APRS_MODE_BCN_BUSY_CH, "частота зайнята -- чекаємо");
	tickMs(1500);
	CHECK(s_txCalls == 0, "через 1,5 с ще чекаємо");
	s_rxBusy = false;
	tickMs(10);
	CHECK(s_txCalls == 1, "частота звільнилась -- маяк пішов");
	aprsModeExit();

	resetWorld();
	CHECK(aprsModeEnter(), "вхід");
	s_rxBusy = true;
	aprsModeRequestBeacon();
	tickMs(10);
	tickMs(3100);
	CHECK(s_txCalls == 0 && s_notify == 1, "зайнято весь час очікування -- відмова зі сповіщенням");
	s_rxBusy = false;
	tickMs(1000);
	CHECK(s_txCalls == 0, "ручний запит скасовано, сам не повторюється");
	aprsModeExit();

	/* індикатор несучої: шумодав відкрито на 0 % (sql == 1) -- не рахується зайнятістю */
	resetWorld();
	CHECK(aprsModeEnter(), "вхід");
	aprsModeCfg()->sql = 1;
	aprsModeCfgChanged(0);
	s_led = true;
	aprsModeRequestBeacon();
	tickMs(10);
	CHECK(s_txCalls == 1, "відкритий шумодав 0 %%: світіння LED -- не зайнятість");
	aprsModeExit();
	resetWorld();
	CHECK(aprsModeEnter(), "вхід");
	s_led = true;   /* шумодав типовий */
	aprsModeRequestBeacon();
	tickMs(10);
	CHECK(s_txCalls == 0, "несуча при звичайному шумодаві -- частота зайнята");
	aprsModeExit();

	/* відмова через налаштування: сповіщення тільки для ручного, періодичний повторюється через 10 с, а не щотіка */
	resetWorld();
	CHECK(aprsModeEnter(), "вхід");
	s_txResult = APRS_MODE_TX_NOPOS;
	aprsModeRequestBeacon();
	tickMs(10);
	CHECK(s_txCalls == 1 && aprsModeBeaconState() == APRS_MODE_BCN_NOPOS && s_notify == 1, "нема позиції: ручний маяк -- сповіщення");
	tickMs(100);
	CHECK(s_txCalls == 1, "ручна відмова не зациклюється");
	aprsModeCfg()->interval = 1;
	aprsModeCfgChanged(0);
	tickMs(301000);
	CHECK(s_txCalls == 2 && s_notify == 1, "періодичний: спроба без сповіщення");
	tickMs(500);
	CHECK(s_txCalls == 2, "і не щотіка");
	tickMs(10000);
	CHECK(s_txCalls == 3, "повтор через 10 с після невдачі");
	aprsModeExit();

	/* йде передача -- нових запитів не обробляємо */
	resetWorld();
	CHECK(aprsModeEnter(), "вхід");
	aprsTxProgress = APRS_TX_IN_PROGRESS;
	aprsModeRequestBeacon();
	tickMs(100);
	CHECK(s_txCalls == 0 && aprsModeIsTransmitting(), "під час передачі маяк не запускається вдруге");
	aprsTxProgress = APRS_TX_IDLE;
	aprsModeExit();
}

static void testLastFrame(void)
{
	aprsAx25_t ax;
	aprsPacket_t pkt;

	resetWorld();
	CHECK(aprsModeEnter(), "вхід");
	CHECK(aprsModeLast()->valid == false, "пакетів ще нема");
	memset(&ax, 0, sizeof(ax)); memset(&pkt, 0, sizeof(pkt));
	snprintf(ax.src, sizeof(ax.src), "UW5ELK-7");
	snprintf(ax.dst, sizeof(ax.dst), "APDR16");
	pkt.type = APRS_T_POSITION;
	aprsModeOnFrame(&ax, &pkt, true, 3200, 45);
	CHECK(aprsModeLast()->valid && strcmp(aprsModeLast()->src, "UW5ELK-7") == 0 && strcmp(aprsModeLast()->dst, "APDR16") == 0, "останній пакет записано");
	CHECK(aprsModeLast()->hasGeo && aprsModeLast()->distM == 3200 && aprsModeLast()->bearing == 45 && aprsModeLast()->type == APRS_T_POSITION, "відстань і азимут");
	aprsModeExit();
	/* поза режимом виклик нічого не робить і не чіпає позичений буфер */
	aprsModeOnFrame(&ax, &pkt, true, 1, 1);
	CHECK(callReplayIsBorrowed() == false, "поза режимом aprsModeOnFrame не позичає кільце");
}

/* R12: прапорець позиченого кільця живе в CCM (на залізі при старті сміття). applicationMain.c на старті кличе callReplayInit() і
 * callReplayBorrowReset(): після них кільце НЕ позичене, запис працює; позика й повернення зберігають справжній перемикач. */
static void testBootInit(void)
{
	uint8_t g[CALL_REPLAY_GROUP_BYTES];

	callReplayInit();
	callReplayBorrowReset();
	CHECK(callReplayIsBorrowed() == false, "після старту кільце не позичене");
	CHECK(callReplayIsRecordingEnabled(), "після старту «Запис RX» увімкнено");
	memset(g, 7, sizeof(g));
	callReplayCaptureTick(g, false, 100);
	CHECK(callReplayGroupCount() == 1, "після старту «Переслухати» пише");
	callReplaySetRecordingEnabled(false);
	{
		size_t n = 0;

		(void)callReplayBorrow(&n);
		CHECK(callReplayIsBorrowed(), "кільце позичене");
		callReplayRelease();
	}
	CHECK(callReplayIsBorrowed() == false && callReplayIsRecordingEnabled() == false, "справжній перемикач (вимкнено) повернуто після позики");
	callReplaySetRecordingEnabled(true);
}

int main(void)
{
	testBootInit();
	testEnterExit();
	testRecordingOff();
	testVfo();
	testRefusals();
	testStockBeaconing();
	testExitPaths();
	testSettings();
	testDefaultsFallback();
	testBeacons();
	testLastFrame();
	if (s_fail != 0)
	{
		printf("test_aprs_mode_state: ПРОВАЛІВ %d з %d перевірок\n", s_fail, s_checks);
		return 1;
	}
	printf("test_aprs_mode_state: усі %d перевірок пройшли\n", s_checks);
	return 0;
}
