/*
 * Copyright (C) 2023-2025 Roger Clark, VK3KYY / G4KYF
 *                         Daniel Caujolle-Bert, F1RMB
 *
 *
 * Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions
 * are met:
 *
 * 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
 *
 * 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer
 *    in the documentation and/or other materials provided with the distribution.
 *
 * 3. Neither the name of the copyright holder nor the names of its contributors may be used to endorse or promote products derived
 *    from this software without specific prior written permission.
 *
 * 4. Use of this source code or binary releases for commercial purposes is strictly forbidden. This includes, without limitation,
 *    incorporation in a commercial product or incorporation into a product or project which allows commercial use.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
 * HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 * LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
 * ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE
 * USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 *
 */

#ifndef _OPENGD77_APRS_H_
#define _OPENGD77_APRS_H_

#if !defined(PLATFORM_GD77S)

#include "functions/codeplug.h"
#include "functions/aprs_rx_cfg.h"
#include "functions/aprs_mode_cfg.h"   /* R10: aprsModeEff_t (ENABLE_APRS_RX) */

//#define RATE_MESSAGE_FEATURE 1 // Enable this to enable the send a special beacon message each settings.messageInterval frame

#define APRS_BEACON_DECAY_MULT_MIN            1U
#define APRS_BEACON_DECAY_MULT_STEP           2U
#define APRS_BEACON_DECAY_MULT_MAX           32U

#define APRS_BEACON_INITIAL_INTERVAL_MIN      0U
#define APRS_BEACON_INITIAL_INTERVAL_DEFAULT  2U
#define APRS_BEACON_INITIAL_INTERVAL_MAX      9U

#define APRS_SMART_BEACON_SLOW_RATE_MIN       1U
#define APRS_SMART_BEACON_SLOW_RATE_DEFAULT  30U
#define APRS_SMART_BEACON_SLOW_RATE_MAX     100U

#define APRS_SMART_BEACON_FAST_RATE_MIN      10U
#define APRS_SMART_BEACON_FAST_RATE_DEFAULT 120U
#define APRS_SMART_BEACON_FAST_RATE_MAX     180U

#define APRS_SMART_BEACON_LOW_SPEED_MIN       2U
#define APRS_SMART_BEACON_LOW_SPEED_DEFAULT   5U
#define APRS_SMART_BEACON_LOW_SPEED_MAX      30U

#define APRS_SMART_BEACON_HIGH_SPEED_MIN      2U
#define APRS_SMART_BEACON_HIGH_SPEED_DEFAULT 70U
#define APRS_SMART_BEACON_HIGH_SPEED_MAX     90U

#define APRS_SMART_BEACON_TURN_ANGLE_MIN      5U
#define APRS_SMART_BEACON_TURN_ANGLE_DEFAULT 28U
#define APRS_SMART_BEACON_TURN_ANGLE_MAX     90U

#define APRS_SMART_BEACON_TURN_SLOPE_MIN      1U
#define APRS_SMART_BEACON_TURN_SLOPE_DEFAULT 26U
#define APRS_SMART_BEACON_TURN_SLOPE_MAX    255U

#define APRS_SMART_BEACON_TURN_TIME_MIN       5U
#define APRS_SMART_BEACON_TURN_TIME_DEFAULT  60U
#define APRS_SMART_BEACON_TURN_TIME_MAX     180U

#define APRS_BEACON_MESSAGE_INTERVAL_MIN      3U
#define APRS_BEACON_MESSAGE_INTERVAL_DEFAULT 10U
#define APRS_BEACON_MESSAGE_INTERVAL_MAX     30U

#define APRS_BEACON_DECAY_RESET_DISTANCE_MIN 15.0 // m

#define APRS_XMIT_TX_DELAY                   50U

#define APRS_BEACONING_FAILURE_MAX            4U

typedef enum
{
	APRS_TX_IDLE = 0,
	APRS_TX_IN_PROGRESS,
	APRS_TX_FINISHED,
	APRS_TX_TERMINATE,
	APRS_TX_WAIT_PTT_OFF,
	APRS_TX_FAILED_WAITING_TO_BEACON,
	APRS_TX_FINAL_STAGE,
} aprsSendProgress_t;

typedef enum
{
	APRS_BEACONING_STATE_ENABLED                    = (1 << 0),
	APRS_BEACONING_STATE_LOCATION_FROM_CHANNEL      = (1 << 1),
	APRS_BEACONING_STATE_LOCATION_FROM_GPS          = (1 << 2),
	APRS_BEACONING_STATE_DECAY_ALGO_ENABLED         = (1 << 3),
	APRS_BEACONING_STATE_COMPRESSED_FORMAT          = (1 << 4),
	APRS_BEACONING_STATE_HAS_APRS_CONFIG            = (1 << 5),
	APRS_BEACONING_STATE_HAS_APRS_SATELLITE_CONFIG  = (1 << 6),
	APRS_BEACONING_STATE_HAS_GPS_FIX                = (1 << 7)
} aprsBeaconingStates_t;

#if defined(HAS_GPS)
#define APRS_BEACONING_STATE_LOCATION_MAX   APRS_BEACONING_STATE_LOCATION_FROM_GPS
#else
#define APRS_BEACONING_STATE_LOCATION_MAX   APRS_BEACONING_STATE_LOCATION_FROM_CHANNEL
#endif
#define APRS_BEACONING_STATE_LOCATION_MIN   APRS_BEACONING_STATE_LOCATION_FROM_CHANNEL

typedef enum
{
	APRS_BEACONING_MODE_OFF = 0,
	APRS_BEACONING_MODE_MANUAL,
	APRS_BEACONING_MODE_PTT,
	APRS_BEACONING_MODE_AUTO,
	APRS_BEACONING_MODE_SMART_BEACONING
} aprsBeaconingMode_t;

typedef struct
{
	uint8_t                      slowRate; // in minutes (1..**30**..100) /// 7 bits
	uint8_t                      fastRate; // in seconds (10..**120**..180) /// 8 bits

	uint8_t                      lowSpeed; // in km/h (2..**5**..30) /// 5 bits
	uint8_t                      highSpeed; // in km/h (2..**70**..90) /// 7 bits

	uint8_t                      turnAngle; // in degrees (5..**28**..90) /// 7 bits
	uint8_t                      turnSlope; // (10degree/speed) (1.**26**.255) /// 8 bits
	uint8_t                      turnTime; // in seconds (5..**60**..180) /// 8 bits
} aprsSmartBeaconingSettings_t;

typedef struct
{
	aprsBeaconingStates_t        state; // bitfield /// 8 bits
	aprsBeaconingMode_t          mode; /// 3 bits
	uint8_t                      initialInterval; // offset in initialIntervalsInSecs[] (0.2, 0.5, **1**, 2, 3, 5, 10, 20, 30, 60 min) /// 4 bits  [APRS_BEACON_INITIAL_INTERVAL_*]
#if defined(RATE_MESSAGE_FEATURE)
	uint8_t                      messageInterval; // 3 .. 30 /// 4 bits
#endif
	uint8_t                      power; // 0..11 /// 4 bits
	aprsSmartBeaconingSettings_t smart;
} aprsBeaconingSettings_t;

extern volatile aprsSendProgress_t aprsTxProgress;

void aprsBitStreamSender(void);
#if defined(PLATFORM_GD77)
void FTM1_IRQHandler(void);
#endif

void aprsBeaconingUpdateConfigurationFromSystemSettings(void);
void aprsBeaconingUpdateSystemSettingsFromConfiguration(void);

void aprsBeaconingGetSettings(aprsBeaconingSettings_t *dest);
void aprsBeaconingSetSettings(aprsBeaconingSettings_t *src);

void aprsBeaconingInit(void);
void aprsBeaconingStart(void);
void aprsBeaconingStop(void);
void aprsBeaconingResetTimers(void);
void aprsBeaconingPrepareSatelliteConfig(void);
void aprsBeaconingSetCurrentLocation(double lat, double lon);
void aprsBeaconingInvalidateFixedPosition(void);
bool aprsBeaconingIsSuspended(void);
void aprsBeaconingSetSuspend(bool suspend);
void aprsBeaconingToggles(void);
aprsBeaconingMode_t aprsBeaconingGetMode(void);
#if defined(ENABLE_APRS_RX)
/* R8 (форк): дані конфігу APRS для фонового приймача (functions/aprs_rx.c). */
typedef struct
{
	uint32_t freq;        /* частота APRS з конфігу каналу (txFrequency; ті самі одиниці, що rxFreq каналу) */
	char     call[9];     /* власний позивний (радіо-ім'я з кодплага, до 6 симв.) */
	uint8_t  ssid;        /* SSID відправника з конфігу APRS */
	bool     hasPos;      /* власна позиція відома (з конфігу каналу або GPS) */
	double   lat, lon;    /* градуси; значущі лише при hasPos */
} aprsRxInfo_t;
/* true -- APRS увімкнено (режим не «Вимкнено»), у каналу є конфіг із частотою APRS. false -- приймати не треба.
 * full == false -- лише freq (без читання EEPROM з іменем і без позиції): для частої перевірки «чи це канал APRS». */
bool aprsBeaconingGetRxInfo(aprsRxInfo_t *info, bool full);

/* R10 (форк): маяк «Режиму APRS» (functions/aprs_mode.c) -- без QSY, зі своїм позивним/шляхом/символом/
 * коментарем/позицією. Деталі -- коментар біля реалізації в aprs.c. */
typedef enum
{
	APRS_MODE_TX_OK = 0,
	APRS_MODE_TX_BUSY,        /* вже йде передача / сканування */
	APRS_MODE_TX_INHIBIT,     /* заборона TX у налаштуваннях */
	APRS_MODE_TX_NOT_FM,      /* рація не в аналоговому FM */
	APRS_MODE_TX_BAND,        /* частота поза любительським діапазоном (обмеження TX) */
	APRS_MODE_TX_NOPOS,
	APRS_MODE_TX_NOCALL,
	APRS_MODE_TX_TOOBIG       /* R10-fix2: кадр AX.25 не влазить у буфер -- передачу скасовано */
} aprsModeTxResult_t;
aprsModeTxResult_t aprsModeTxBeacon(const aprsModeEff_t *e);
/* R11: повідомлення/ACK APRS (info -- з aprs_msg.c). R13 (П.6): from — позивний-SSID відправника з завдання черги («CALL[-SS]»): замінює позивний
 * режиму; NULL або "" — позивний режиму, як було. */
aprsModeTxResult_t aprsModeTxMessage(const aprsModeEff_t *e, const char *info, const char *from);
/* R11-fix2: повідомлення/ACK APRS ПОЗА «Режимом APRS» -- тим самим шляхом, що стоковий бікон «Вручну»: aprsRxStopForTx(), QSY на
 * частоту APRS з конфігу каналу (якщо вона є), анти-колізія, TX, а повернення каналу -- стоковою машиною aprsBeaconingTxStateTick()
 * (APRS_TX_FINAL_STAGE). Позивний/SSID/шлях -- зі стокового конфігу APRS (як у бікона). Позиція не потрібна. Бікон призупинено
 * клавішею (aprsBeaconingToggles()) або APRS вимкнено -- APRS_MODE_TX_INHIBIT / NOCALL (марно повторювати). */
aprsModeTxResult_t aprsBeaconingSendMessage(const char *info, const char *from);   /* R13 (П.6): from — як в aprsModeTxMessage(); NULL/"" — ім'я рації + SSID зі стокового конфігу */
/* APRS увімкнено у стокових налаштуваннях і не призупинено клавішею: можна передавати повідомлення поза режимом. */
bool aprsBeaconingMessagesAllowed(void);
void aprsModeAbortTx(void);   /* примусово обірвати маяк режиму (вихід посеред передачі) */
#endif
bool aprsBeaconingSendBeacon(bool fromSatScreen, bool forcedManualBeaconing);
bool aprsBeaconingIsTransmitting(void);
bool aprsBeaconingForcedManualBeaconingTriggered(void);
bool aprsBeaconingOnDifferentFrequency(void);
bool aprsBeaconingHasSatelliteConfiguration(void);
#if defined(ENABLE_AES)
/* ui8 (форк): бікон у режимі PTT. Що робити, коли відпустили PTT (uiTxScreen.c): */
typedef enum
{
	APRS_PTT_BEACON_NONE = 0,   /* бікона не буде (ще не минув інтервал, не той режим, немає конфігу...) */
	APRS_PTT_BEACON_TAIL,       /* як в апстрімі: аналоговий канал без частоти APRS -- у хвіст голосу */
	APRS_PTT_BEACON_DEFERRED,   /* у конфігу є TX-частота: голос завершується звичайно, бікон -- потім,
	                             * із QSY, як «Вручну» (aprsBeaconingTick) */
	APRS_PTT_BEACON_NO_FREQ     /* цифровий канал без частоти APRS: AFSK у DMR не модулюється -- лише
	                             * повідомлення, «APRS Tx» не показувати */
} aprsPttBeaconRequest_t;
aprsPttBeaconRequest_t aprsBeaconingPttRequest(bool isDigital);
/* PTT натиснуто знову: скасувати бікон, що очікує, або ПЕРЕРВАТИ відкладений бікон, що вже
 * передається, і повернути частоту/режим каналу -- синхронно, до ключування голосу. */
void aprsBeaconingPttAbort(void);
#endif

#else //PLATFORM_GD77S

#define aprsBeaconingPrepareSatelliteConfig() do {} while(0)
#define aprsBeaconingInvalidateFixedPosition() do {} while(0)
#define aprsBeaconingResetTimers() do {} while(0)
#define aprsBeaconingSetCurrentLocation(lat, lon) do {} while(0)
#define aprsBeaconingIsTransmitting()  (false)

#endif // PLATFORM_GD77S

#endif // _OPENGD77_APRS_H_
