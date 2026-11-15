/*
 * Copyright (C) 2019-2025 Roger Clark, VK3KYY / G4KYF
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
#include "user_interface/uiGlobals.h"
#include "functions/roaming_gate.h"   /* R74: ROAMING_EFFECTIVE() */
#include "functions/codeplug_zone.h"
#include "functions/trx.h"
#include "user_interface/menuSystem.h"
#include "user_interface/uiUtilities.h"
#include "user_interface/uiLocalisation.h"
#include "functions/voicePrompts.h"
#include "functions/rxPowerSaving.h"
#if defined(ENABLE_ROAM_RETRY)
#include "functions/wake_hop.h"   // R59: roamIsActive()/roamClear() -- стан «знайдений канал»
#include "functions/roam_cfg.h"
#include "user_interface/roam_ui.h"   // R59: індикатори (ROAM_IND_LIST/ROAM_IND_SPARE)
#endif
#if defined(APRS_RX)
#include "functions/aprs_mode.h"   // R18 Д5: aprsModeBeaconHotkey()/aprsModeBeaconOnceBusy()
#endif
#if defined(PLATFORM_MD9600) || defined(PLATFORM_MD380) || defined(PLATFORM_MDUV380) || defined(PLATFORM_RT84_DM1701) || defined(PLATFORM_MD2017)
#include "hardware/radioHardwareInterface.h"
#endif
#include "interfaces/gps.h"
#if defined(ENABLE_DUAL_CHANNEL)
#include "functions/dual_channel.h"   // R97: «Подвійний прийом»
#if defined(DUAL_CHANNEL_ENABLED)
#include "crypto/dmr_aes_hook.h"      // R98-FIX2 Е: dmrAesRxRetune() (без ENABLE_AES -- порожня заглушка); лише коли режим справді збирається
#endif
#if defined(ENABLE_LC_DISTANCE)
#include "functions/lc_distance.h"    // R97: відстань R92 у рядку абонента режиму
#endif
#endif

#if defined(HAS_COLOURS)
#define NAME_BUFFER_LEN   25
#else
#define NAME_BUFFER_LEN   22
#endif

typedef struct
{
	uint16_t index;
	int32_t	 distance;
} channelDistance_t;

#if defined(PLATFORM_GD77S)
typedef enum
{
	GD77S_UIMODE_TG_OR_SQUELCH,
	GD77S_UIMODE_SCAN,
	GD77S_UIMODE_TS,
	GD77S_UIMODE_CC,
	GD77S_UIMODE_FILTER,
	GD77S_UIMODE_DTMF_CONTACTS,
	GD77S_UIMODE_ZONE,
	GD77S_UIMODE_POWER,
	GD77S_UIMODE_ECO,
	GD77S_UIMODE_MAX
} GD77S_UIMODES_t;

typedef struct
{
	bool             firstRun;
	GD77S_UIMODES_t  uiMode;
	bool             channelOutOfBounds;
	uint16_t         dtmfListSelected;
	int32_t          dtmfListCount;
} GD77SParameters_t;

static GD77SParameters_t GD77SParameters =
{
		.firstRun = true,
		.uiMode = GD77S_UIMODE_TG_OR_SQUELCH,
		.channelOutOfBounds = false,
		.dtmfListSelected = 0,
		.dtmfListCount = 0
};

static void buildSpeechUiModeForGD77S(GD77S_UIMODES_t uiMode);

static void checkAndUpdateSelectedChannelForGD77S(uint16_t chanNum, bool forceSpeech);
static void handleEventForGD77S(uiEvent_t *ev);
static uint16_t getCurrentChannelInCurrentZoneForGD77S(void);

#else // ! PLATFORM_GD77S

static void selectPrevNextZone(bool nextZone);
static void handleUpKey(uiEvent_t *ev);
static void handleDownKey(uiEvent_t *ev);

#endif // PLATFORM_GD77S

static void handleEvent(uiEvent_t *ev);

static void updateQuickMenuScreen(bool isFirstRun);
static void handleQuickMenuEvent(uiEvent_t *ev);

static void scanning(void);
static void scanStart(bool longPressBeep);
static void scanSearchForNextChannel(void);
static void scanApplyNextChannel(void);
static void scanStop(bool loadChannel);
static void updateTrxID(void);
static void initSortedChannels(void);
#if defined(DUAL_CHANNEL_ENABLED)
// R97: «Подвійний прийом» (реалізація -- після uiChannelModeIsScanning())
static bool dualIsRunning(void);
static void dualSuspend(void);
static void dualScanning(void);
static bool dualHandleKey(uiEvent_t *ev);
static void dualStepB(int dir) __attribute__((noinline));   // R98-FIX5 А3: те саме (зона B на стеку)
static void dualRedToggle(void);
static bool dualIsVfoStepKey(const uiEvent_t *ev);
static void dualRenderScreen(void);
static uint16_t dualChannelA(void);
static void dualAutoResume(void);
static bool dualHoldScreen(void);
static bool dualSingle(void);
static bool dualRenderMeter(void);
static void dualQuietEnd(void);
static void dualQuickMenuApply(void);
static void dualHotkeyToggle(void);
static void dualTune(bool toB);
static bool dualBExists(void);
static uint8_t dualVfoIdx(void);
static bool dualCardIsVfo(bool isB);
static uint8_t dualCardVfo(bool isB);
static bool dualOnVfoNow(void);
static uint8_t  s_dualTgIdxB;  // R98-FIX5 А2: вибраний ТГ у списку прийому картки B = канал (індекс SETTINGS_CHANNEL_MODE спільний з A -- на час B підставляється цей); скидається при зміні B
static uint8_t  s_dualBKeep;   // R98-FIX5 А5 (замість s_dualSqlB R98-FIX3): 1 -- робоча копія B (канал) з правками картки (шумодав, потужність, режим, смуга) збережена в пам'яті й не перечитується з кодплага; скидається при зміні B. Оголошено ПЕРЕД рештою: gcc кладе ці змінні в .bss у зворотному порядку, тож байти стають у кінець групи (у вирівнювання), а не між 1- і 2-байтовими
static uint8_t  s_dualZoneB;   // R98-FIX5 А3: зона картки B, вибрана SK2 + ручкою (номер зони + 1; 0 -- не вибрано: ручка на B ходить по поточній зоні, як раніше)
static void dualBReset(void);
static void dualZoneStepB(int dir) __attribute__((noinline));   // R98-FIX5: запис зони (188 Б) на стеку -- лише на час кроку, не в кадрі uiChannelMode()
static uint32_t s_dualKeyMs;   // час останньої клавіші на екрані каналу: чергування відновлюється через 1 с тиші (не між PRESS і SHORTUP)
static int16_t  s_dualTgIdxA;  // вибраний ТГ у списку прийому каналу A: завантаження B може скинути спільний індекс, повертаємо його з A
static bool     s_dualQuiet;   // R97-FIX4/5: придушити uiChannelModeUpdateScreen() на час обробки клавіші в режимі (S-метр звичайного екрана не спалахує); скидається наприкінці handleEvent()
static bool dualEntryKey(uiEvent_t *ev);
static bool dualIsSquelchKey(const uiEvent_t *ev);
static void dualSquelchStep(int dir);
static void dualEntryText(char *l2, size_t size);
#endif

static char currentZoneName[SCREEN_LINE_BUFFER_SIZE];
static int directChannelNumber = 0;

static CodeplugChannel_t scanNextChannelData = { .rxFreq = 0 };
static bool scanNextChannelReady = false;
static int scanNextChannelIndex = 0;
static bool scobAlreadyTriggered = false;
static bool quickmenuChannelFromVFOHandled = false; // Quickmenu new channel confirmation window
static const uint32_t ROAMING_DISTANCE_KM_ARRAY[] = { 5, 10, 20 };
static const uint32_t ROAMING_POSITION_SAMPLING_PERIOD = 5000U;

static menuStatus_t menuChannelExitStatus = MENU_STATUS_SUCCESS;
static menuStatus_t menuQuickChannelExitStatus = MENU_STATUS_SUCCESS;


static void checkChannelLocation(CodeplugChannel_t *channelData)
{
	if (settingsLocationIsValid() && codeplugChannelGetFlag(channelData, CHANNEL_FLAG_USE_LOCATION))
	{
		uint32_t tmp1 = channelData->locationLat2;
		tmp1 = (tmp1 << 8) + channelData->locationLat1;
		tmp1 = (tmp1 << 8) + channelData->locationLat0;

		if (tmp1 != 0)
		{
			uint32_t tmp2 = channelData->locationLon2;
			tmp2 = (tmp2 << 8) + channelData->locationLon1;
			tmp2 = (tmp2 << 8) + channelData->locationLon0;

			if (tmp2 != 0)
			{
				double lat = latLonFixed24ToDouble(tmp1);
				double lon = latLonFixed24ToDouble(tmp2);

				channelData->NOT_IN_CODEPLUG_CALCULATED_DISTANCE_X10 = distanceToLocation(lat, lon) * 10;
				return;
			}
		}
	}

	channelData->NOT_IN_CODEPLUG_CALCULATED_DISTANCE_X10 = -1;
}

static menuStatus_t uiChannelModeFirstRun(void)
{
#if ! defined(PLATFORM_GD77S)
		bool isLockMenu = (menuSystemGetPreviouslyPushedMenuNumber(true) == UI_LOCK_SCREEN);
		// We're coming back from the lock screen (hence no channel init is needed, at all).
		if (isLockMenu || lockscreenIsRearming)
		{
			if (isLockMenu)
			{
				menuSystemGetPreviouslyPushedMenuNumber(false); // Clear the previous lock screen trace
			}

			uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
			uiChannelModeUpdateScreen(0);

			return MENU_STATUS_SUCCESS;
		}

		// GD77S speech can be triggered in main(), so let it ends
		voicePromptsTerminate();
#endif

		settingsSet(nonVolatileSettings.initialMenuNumber, (uint8_t) UI_CHANNEL_MODE);// This menu.
		uiDataGlobal.displayChannelSettings = false;
		scanNextChannelReady = false;
		uiDataGlobal.Scan.refreshOnEveryStep = false;

		uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;

		lastHeardClearLastID();
		uiDataGlobal.displayQSOStatePrev = QSO_DISPLAY_IDLE;
		currentChannelData = &channelScreenChannelData;// Need to set this as currentChannelData is used by functions called by loadChannelData()

#if defined(DUAL_CHANNEL_ENABLED)
		if (dualOnVfoNow())
		{
			// R98-FIX4 Б1/Б3: режим ввімкнено, рація на картці VFO (A = VFO після вмикання з екрана VFO, або B = VFO) -- налаштовуємо цей VFO ізольовано
			// (рання гілка uiChannelModeLoadChannelData), зону лише ініціалізуємо, якщо канальний буфер порожній (для подальших переходів ручкою).
			if (channelScreenChannelData.rxFreq == 0U)
			{
				uiChannelInitializeCurrentZone();
			}
			uiChannelModeLoadChannelData(true, false);
		}
		else
#endif
		if (currentChannelData->rxFreq != 0U)
		{
			uiChannelModeLoadChannelData(true, false);
		}
		else
		{
			uiChannelInitializeCurrentZone();
#if defined(PLATFORM_RD5R) || defined(PLATFORM_MD9600)
			settingsSet(nonVolatileSettings.currentChannelIndexInZone, codeplugGetLastUsedChannelInCurrentZone());
#endif
			uiChannelModeLoadChannelData(false, false);
		}

		if ((uiDataGlobal.displayQSOState == QSO_DISPLAY_CALLER_DATA) && (trxGetMode() == RADIO_MODE_ANALOG))
		{
			uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
		}

#if defined(PLATFORM_GD77S)
		trxSetPowerFromLevel(nonVolatileSettings.txPowerLevel);// ensure the power level is available for the Power announcement

		//Reset to first UiMode if the radio is in Analog mode and the current UiMode only applies to DMR
		if ((trxGetMode() == RADIO_MODE_ANALOG) &&
			((GD77SParameters.uiMode == GD77S_UIMODE_TS ) ||
			(GD77SParameters.uiMode == GD77S_UIMODE_CC ) ||
			(GD77SParameters.uiMode == GD77S_UIMODE_FILTER )))
		{
			GD77SParameters.uiMode = GD77S_UIMODE_TG_OR_SQUELCH;
		}

		// Ensure the correct channel is loaded, on the very first run
		if (GD77SParameters.firstRun)
		{
			if (voicePromptsIsPlaying() == false)
			{
				GD77SParameters.firstRun = false;
				checkAndUpdateSelectedChannelForGD77S(rotarySwitchGetPosition(), true);
			}


			GD77SParameters.dtmfListCount = codeplugDTMFContactsGetCount();
		}
#endif
		uiChannelModeUpdateScreen(0);

		if (uiDataGlobal.Scan.active == false)
		{
			uiDataGlobal.Scan.state = SCAN_STATE_SCANNING;
		}

		// Need to do this last, as other things in the screen init, need to know whether the main screen has just changed
		if (uiDataGlobal.VoicePrompts.inhibitInitial)
		{
			uiDataGlobal.VoicePrompts.inhibitInitial = false;
		}

		// Scan On Boot is enabled, but has to be run only once.
		if (settingsIsOptionBitSet(BIT_SCAN_ON_BOOT_ENABLED) && (scobAlreadyTriggered == false))
		{
			scanStart(false);
		}

		// Disable ScOB for this session, and also prevent false triggering (like exiting the Options screen)
		scobAlreadyTriggered = true;

		return MENU_STATUS_SUCCESS; // Due to Orange Quick Menu
}


menuStatus_t uiChannelMode(uiEvent_t *ev, bool isFirstRun)
{
	static uint32_t m = 0;

	if (isFirstRun)
	{
		return uiChannelModeFirstRun();
	}
	else
	{
		menuChannelExitStatus = MENU_STATUS_SUCCESS;

#if defined(PLATFORM_GD77S)
		uiChannelModeHeartBeatActivityForGD77S(ev);
#else
		// Don't go any further while APRS is beaconing
		if (aprsBeaconingForcedManualBeaconingTriggered() && aprsBeaconingIsTransmitting())
		{
			return menuChannelExitStatus;
		}
#endif
#if defined(APRS_RX)
		// R18 Д5: поки іде разовий маяк (SK1+3), рація «запаркована» на частоті APRS, currentChannelData -- власний канал режиму: події екрана
		// (ручка, клавіші) його не чіпають, інакше змінили б не те.
		if (aprsModeBeaconOnceBusy())
		{
			return menuChannelExitStatus;
		}
#endif

		if (ev->events == NO_EVENT)
		{
#if defined(DUAL_CHANNEL_ENABLED)
			dualAutoResume();   // R97: увімкнений режим, який зупинила клавіша/меню/передача, -- відновити (і відкладений запис блоку 18)
#endif
			bool updateLHDisplay = ((nonVolatileSettings.lastTalkerOnScreenTimer > 0U) &&
					(uiDataGlobal.lastHeardCount > 0) &&
					(uiDataGlobal.Scan.active == false) &&
					ticksTimerIsEnabled(&uiDataGlobal.DMRLastTalkerOnScreen.timer) &&
					ticksTimerHasExpired(&uiDataGlobal.DMRLastTalkerOnScreen.timer) &&
					((audioAmpGetStatus() & AUDIO_AMP_CHANNEL_RF) == 0));

#if defined(PLATFORM_GD77S)
			// Just ensure rotary's selected channel is matching the already loaded one
			// as rotary selector could be turned while the GD is OFF, or in hotspot mode.
			if ((uiDataGlobal.Scan.active == false) && ((rotarySwitchGetPosition() != getCurrentChannelInCurrentZoneForGD77S()) || GD77SParameters.firstRun))
			{
				if (voicePromptsIsPlaying() == false)
				{
					checkAndUpdateSelectedChannelForGD77S(rotarySwitchGetPosition(), GD77SParameters.firstRun);

					// Opening channel number announce has not took place yet, probably because it was telling
					// parameter like new hotspot mode selection.
					if (GD77SParameters.firstRun)
					{
						GD77SParameters.firstRun = false;
					}
				}
			}
#endif

			// is there an incoming DMR signal
			if ((uiDataGlobal.displayQSOState != QSO_DISPLAY_IDLE) || updateLHDisplay)
			{
				if (updateLHDisplay)
				{
					uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
				}

				uiChannelModeUpdateScreen(0);
			}
			else
			{
				if ((ev->time - m) > RSSI_UPDATE_COUNTER_RELOAD)
				{
#if defined(DUAL_CHANNEL_ENABLED)
					if (rxPowerSavingIsRxOn() && ((dualIsRunning() && (uiDataGlobal.Scan.state == SCAN_STATE_SCANNING)) == false))   // R97-FIX2: чергування без активності -- шапка режиму статична, S-метра й виводу на екран нема
#else
					if (rxPowerSavingIsRxOn())
#endif
					{
						if (uiDataGlobal.Scan.active && (uiDataGlobal.Scan.state == SCAN_STATE_PAUSED))
						{
#if defined(DUAL_CHANNEL_ENABLED)
							if (uiChannelModeDualScreenShown() == false)   // R97-FIX6: картки починаються з y=11 -- рядки 0..2 (y<24) очищати не можна; шапка сама очищає y=0..9
							{
#endif
#if defined(PLATFORM_RD5R)
							displayClearRows(0, 1, false);
#else
							displayClearRows(0, 2, false);
#endif
#if defined(DUAL_CHANNEL_ENABLED)
							}
#endif
							uiUtilityRenderHeader(false, false, ((ev->buttons & BUTTON_SK1) == BUTTON_SK1));
						}
						else
						{
							uiUtilityDrawRSSIBarGraph();
						}

#if defined(DUAL_CHANNEL_ENABLED)
						if (uiChannelModeDualScreenShown())
						{
							// R97-FIX6: екран режиму -- S-метр у смузі активної картки (стоковий блок вимкнено); один displayRender, лише коли щось змінено
							bool meterDrawn = dualRenderMeter();

							if (meterDrawn || uiNotificationIsVisible() || (uiDataGlobal.Scan.active && (uiDataGlobal.Scan.state == SCAN_STATE_PAUSED)))
							{
								displayRender();
							}
						}
						else
#endif
						if (uiNotificationIsVisible())
						{
							displayRender();
						}
						else
						{
							// Only render the second row which contains the bar graph, if we're not scanning,
							// as there is no need to redraw the rest of the screen
							displayRenderRows(((uiDataGlobal.Scan.active && (uiDataGlobal.Scan.state == SCAN_STATE_PAUSED)) ? 0 : 1), uiUtilityRSSIRenderEndRow(2));
						}
					}
					m = ev->time;
				}
			}
#if ! (defined(PLATFORM_MD380) || defined(PLATFORM_MDUV380) || defined(PLATFORM_RT84_DM1701) || defined(PLATFORM_MD2017))
			if (uiDataGlobal.Scan.active)
			{
				scanning();
			}
#endif

			if ((uiDataGlobal.Scan.active == false) &&
					settingsLocationIsValid() &&
					(SETTINGS_CHANNEL_DISTANCE_EFFECTIVE() || (ROAMING_EFFECTIVE() != ROAMING_OFF))
#if defined(HAS_GPS)
					&& ((SETTINGS_GPS_MODE_EFFECTIVE(nonVolatileSettings) <= GPS_MODE_OFF) ||
							((SETTINGS_GPS_MODE_EFFECTIVE(nonVolatileSettings) >= GPS_MODE_ON) && ((gpsData.Status & (GPS_STATUS_HAS_FIX | GPS_STATUS_POSITION_UPDATED)) != 0)))
#endif
			)
			{
				uint32_t m = ticksGetMillis();

				if ((m - uiDataGlobal.lastDistanceMillis) > ROAMING_POSITION_SAMPLING_PERIOD)
				{
					bool newChannelLoaded = false;

					uiDataGlobal.lastDistanceMillis = m;
#if defined(HAS_GPS)
					gpsData.Status &= ~GPS_STATUS_POSITION_UPDATED; // Clear GPS position updated flag.
#endif

					if ((ROAMING_EFFECTIVE() >= ROAMING_5KM) &&
							(CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone) == false))
					{
						double lat1 = settingsLocationGetLatitude();
						double lon1 = settingsLocationGetLongitude();
						double d = distanceBetweenTwoCoords(lat1, lon1, uiDataGlobal.lastDistanceSortLocationLat, uiDataGlobal.lastDistanceSortLocationLon, true);

						if (d >= (double)ROAMING_DISTANCE_KM_ARRAY[ROAMING_EFFECTIVE() - ROAMING_5KM])
						{
							codeplugSetLastUsedChannelInZone(currentZone.NOT_IN_CODEPLUGDATA_indexNumber, 0);

							uint16_t currentChannel = currentZone.channels[0];

							initSortedChannels();

							if (currentChannel != currentZone.channels[0])
							{
								newChannelLoaded = true;
								uiChannelModeLoadChannelData(false, false);
								displayLightTrigger(true);
								soundSetMelody(MELODY_ACK_BEEP);
							}
						}
					}

					if (newChannelLoaded ||
							(uiDataGlobal.displayQSOStatePrev == QSO_DISPLAY_IDLE) || (uiDataGlobal.displayQSOStatePrev == QSO_DISPLAY_DEFAULT_SCREEN))
					{
						checkChannelLocation(currentChannelData);

						if (newChannelLoaded || (uiDataGlobal.lastDistanceDisplayed != currentChannelData->NOT_IN_CODEPLUG_CALCULATED_DISTANCE_X10))
						{
							uiDataGlobal.lastDistanceDisplayed = currentChannelData->NOT_IN_CODEPLUG_CALCULATED_DISTANCE_X10;
							uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
							uiChannelModeUpdateScreen(0);
						}
					}
				}
			}
		}
		else
		{
			if (ev->hasEvent)
			{
				handleEvent(ev);
			}
		}

#if defined(PLATFORM_MD380) || defined(PLATFORM_MDUV380) || defined(PLATFORM_RT84_DM1701) || defined(PLATFORM_MD2017)
		if (uiDataGlobal.Scan.active)
		{
			scanning();
		}
#endif

#if defined(PLATFORM_GD77S)
		dtmfSequenceTick(false);
#endif
	}
	return menuChannelExitStatus;
}

static void hidesChannelDetails(void)
{
	if (uiDataGlobal.displayChannelSettings)
	{
		uiDataGlobal.displayChannelSettings = false;
		uiDataGlobal.displayQSOState = uiDataGlobal.displayQSOStatePrev;

		// Maybe QSO State has been overridden, double check if we could now
		// display QSO Data
		if (uiDataGlobal.displayQSOState == QSO_DISPLAY_DEFAULT_SCREEN)
		{
			if (isQSODataAvailableForCurrentTalker())
			{
				uiDataGlobal.displayQSOState = QSO_DISPLAY_CALLER_DATA;
			}
		}

		uiChannelModeUpdateScreen(0);
	}
}

static bool canCurrentZoneBeScanned(int *availableChannels)
{
	int enabledChannels = 0;
	int chanIdx = codeplugGetLastUsedChannelNumberInCurrentZone();

	if (currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone > 1)
	{
		int chansInZone = currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone;

		if (CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone))
		{
			do
			{
				do
				{
					chanIdx = ((chanIdx % currentZone.NOT_IN_CODEPLUGDATA_highestIndex) + 1);
				} while (!codeplugAllChannelsIndexIsInUse(chanIdx));

				chansInZone--;
				// Get flag4 only
				codeplugChannelGetDataWithOffsetAndLengthForIndex(chanIdx, &scanNextChannelData, CODEPLUG_CHANNEL_FLAG4_OFFSET, 1);

				if (codeplugChannelGetFlag(&scanNextChannelData, CHANNEL_FLAG_ALL_SKIP) == 0)
				{
					enabledChannels++;
				}

			} while (chansInZone > 0);
		}
		else
		{
			do
			{
				chanIdx = ((chanIdx + 1) % currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone);

				chansInZone--;
				// Get flag4 only
				codeplugChannelGetDataWithOffsetAndLengthForIndex(currentZone.channels[chanIdx], &scanNextChannelData, CODEPLUG_CHANNEL_FLAG4_OFFSET, 1);

				if (codeplugChannelGetFlag(&scanNextChannelData, CHANNEL_FLAG_ZONE_SKIP) == 0)
				{
					enabledChannels++;
				}

			} while (chansInZone > 0);
		}
	}

	*availableChannels = enabledChannels;

	return (enabledChannels > 1);
}

static void scanSearchForNextChannel(void)
{
	int channel = 0;

	// All Channels virtual zone
	if (CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone))
	{
		do
		{
			do
			{
				// rollover (up/down) CODEPLUG_CHANNELS_MIN .. currentZone.NOT_IN_CODEPLUGDATA_highestIndex
				scanNextChannelIndex = ((uiDataGlobal.Scan.direction == 1) ?
						((scanNextChannelIndex % currentZone.NOT_IN_CODEPLUGDATA_highestIndex) + 1) :
						((((scanNextChannelIndex - 1) + currentZone.NOT_IN_CODEPLUGDATA_highestIndex - 1) % currentZone.NOT_IN_CODEPLUGDATA_highestIndex) + 1));
			} while (!codeplugAllChannelsIndexIsInUse(scanNextChannelIndex));

			// Check if the channel is skipped.
			// Get flag4 only
			codeplugChannelGetDataWithOffsetAndLengthForIndex(scanNextChannelIndex, &scanNextChannelData, CODEPLUG_CHANNEL_FLAG4_OFFSET, 1);

		} while ((codeplugChannelGetFlag(&scanNextChannelData, CHANNEL_FLAG_ALL_SKIP) != 0));

		channel = scanNextChannelIndex;
		codeplugChannelGetDataForIndex(scanNextChannelIndex, &scanNextChannelData);
	}
	else
	{
		do
		{
			// rollover (up/down) 0 .. (currentZone.NOT_IN_CODEPLUGDATA_highestIndex - 1)
			scanNextChannelIndex = ((uiDataGlobal.Scan.direction == 1) ?
					((scanNextChannelIndex + 1) % currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone) :
					((scanNextChannelIndex + currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone - 1) % currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone));

			// Check if the channel is skipped.
			// Get flag4 only
			codeplugChannelGetDataWithOffsetAndLengthForIndex(currentZone.channels[scanNextChannelIndex], &scanNextChannelData, CODEPLUG_CHANNEL_FLAG4_OFFSET, 1);

		} while ((codeplugChannelGetFlag(&scanNextChannelData, CHANNEL_FLAG_ZONE_SKIP) != 0));

		channel = currentZone.channels[scanNextChannelIndex];
		codeplugChannelGetDataForIndex(currentZone.channels[scanNextChannelIndex], &scanNextChannelData);
	}

	//check all nuisance delete entries and skip channel if there is a match
	for (int i = 0; i < MAX_ZONE_SCAN_NUISANCE_CHANNELS; i++)
	{
		if (uiDataGlobal.Scan.nuisanceDelete[i] == -1)
		{
			break;
		}
		else
		{
			if(uiDataGlobal.Scan.nuisanceDelete[i] == channel)
			{
				return;
			}
		}
	}

	scanNextChannelReady = true;
}

static void scanApplyNextChannel(void)
{
	codeplugSetLastUsedChannelInZone(currentZone.NOT_IN_CODEPLUGDATA_indexNumber, scanNextChannelIndex);

	lastHeardClearLastID();

	memcpy(&channelScreenChannelData, &scanNextChannelData, CODEPLUG_CHANNEL_DATA_STRUCT_SIZE);

	uiChannelModeLoadChannelData(true, false);
	uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
	uiChannelModeUpdateScreen(0);

	// In DIGITAL Slow mode, we need at least 120ms to see the HR-C6000 to start the TS ISR.
	if (trxGetMode() == RADIO_MODE_DIGITAL)
	{
		int dwellTime;
		if(uiDataGlobal.Scan.stepTimeMilliseconds > 150)				// if >150ms use DMR Slow mode
		{
			dwellTime = ((currentRadioDevice->trxDMRModeRx == DMR_MODE_DMO) ? SCAN_DMR_SIMPLEX_SLOW_MIN_DWELL_TIME : SCAN_DMR_DUPLEX_SLOW_MIN_DWELL_TIME);
		}
		else
		{
			dwellTime = ((currentRadioDevice->trxDMRModeRx == DMR_MODE_DMO) ? SCAN_DMR_SIMPLEX_FAST_MIN_DWELL_TIME : (SCAN_DMR_DUPLEX_FAST_MIN_DWELL_TIME + SCAN_DMR_DUPLEX_FAST_EXTRA_DWELL_TIME));
		}

		uiDataGlobal.Scan.dwellTime = ((uiDataGlobal.Scan.stepTimeMilliseconds < dwellTime) ? dwellTime : uiDataGlobal.Scan.stepTimeMilliseconds);
	}
	else
	{
		uiDataGlobal.Scan.dwellTime = uiDataGlobal.Scan.stepTimeMilliseconds;
	}

	uiDataGlobal.Scan.timer.timeout = uiDataGlobal.Scan.dwellTime;
	uiDataGlobal.Scan.state = SCAN_STATE_SCANNING;
	scanNextChannelReady = false;
}

void uiChannelModeLoadChannelData(bool useChannelDataInMemory, bool loadVoicePromptAnnouncement)
{
	bool rxGroupValid = true;
#if ! defined(PLATFORM_GD77S) // GD77S handle voice prompts on its own
	bool wasLoadingZone = (currentChannelData->rxFreq == 0U);
#endif
	int previousSelectedChannelNumber = uiDataGlobal.currentSelectedChannelNumber;

#if defined(DUAL_CHANNEL_ENABLED)
	if (useChannelDataInMemory && dualOnVfoNow())
	{
		// R98 В2: рація на картці VFO (B, а з R98-FIX4 Б3 -- і A) (повернення з екрана передачі/меню): у пам'яті -- запис VFO, налаштовуємо його ізольовано
		// (uiVFOModeDualLoad): стокові канальні гілки нижче (група каналу, ТГ каналу, номер каналу) для VFO не годяться. Нічого не пишемо в налаштування.
		uiDataGlobal.currentSelectedChannelNumber = CH_DETAILS_VFO_CHANNEL;
		uiVFOModeDualLoad(dualCardVfo(dcIsOnB()), false);
		return;
	}
	else
	if (useChannelDataInMemory && dcIsOnB())
	{
		// R97: рація на каналі B «Подвійного прийому» -- у пам'яті саме його запис, тож номер -- B (як у роумінгу R59: збереження каналу
		// піде в його власний запис); «останній канал зони», зона й налаштування НЕ змінюються.
		uiDataGlobal.currentSelectedChannelNumber = dcChannelB();
	}
	else
#endif
#if defined(ENABLE_ROAM_RETRY)
	if (useChannelDataInMemory && roamIsActive())
	{
		// R59: повернення з екрана передачі/меню на канал, знайдений автопереходом -- у пам'яті саме його запис, тож
		// лишаємо ЙОГО номер (а не «останній канал зони»): інакше збереження каналу пішло б у чужий запис.
		uiDataGlobal.currentSelectedChannelNumber = roamActiveChannel();
	}
	else
	{
		roamClear();   // явна зміна каналу (або вихід із «знайденого») -- рація знову на каналі зони
		uiDataGlobal.currentSelectedChannelNumber = codeplugGetLastUsedChannelNumberInCurrentZone();
	}
#else
	uiDataGlobal.currentSelectedChannelNumber = codeplugGetLastUsedChannelNumberInCurrentZone();
#endif

	if (!useChannelDataInMemory)
	{
		if (currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone > 0)
		{
			codeplugChannelGetDataForIndex(uiDataGlobal.currentSelectedChannelNumber, &channelScreenChannelData);
		}
		else
		{
			char buffer[SCREEN_LINE_BUFFER_SIZE];

			snprintf(buffer, SCREEN_LINE_BUFFER_SIZE, "! %.*s !", 12, currentLanguage->zone_empty); // Limits the language string to 12 characters.

			codeplugUtilConvertStringToBuf(buffer, (char *)&channelScreenChannelData.name, 16);
			channelScreenChannelData.chMode = RADIO_MODE_ANALOG;
			channelScreenChannelData.txFreq = channelScreenChannelData.rxFreq = 14400000;
			channelScreenChannelData.txTone = channelScreenChannelData.rxTone = CODEPLUG_CSS_TONE_NONE;
			channelScreenChannelData.flag4 = CODEPLUG_CHANNEL_FLAG4_RX_ONLY;
			channelScreenChannelData.sql = 10U;
			channelScreenChannelData.NOT_IN_CODEPLUG_flag = 0x00;
			channelScreenChannelData.NOT_IN_CODEPLUG_CALCULATED_DISTANCE_X10 = -1;
		}
	}

	HRC6000ClearActiveDMRID();

#if defined(PLATFORM_MD9600)
	// This could happen if a MK22 codeplug contains out of band channel(s) (like 220MHz) on an PLATFORM_MD9600.
	if ((trxGetBandFromFrequency(currentChannelData->rxFreq) == FREQUENCY_OUT_OF_BAND) || (trxGetBandFromFrequency(currentChannelData->txFreq) == FREQUENCY_OUT_OF_BAND))
	{
		// Flag it as out of band channel
		if (codeplugChannelGetFlag(currentChannelData, CHANNEL_FLAG_OUT_OF_BAND) == 0)
		{
			codeplugChannelSetFlag(currentChannelData, CHANNEL_FLAG_OUT_OF_BAND, 1);
		}

		trxSetFrequency(OUT_OF_BAND_FALLBACK_FREQUENCY, OUT_OF_BAND_FALLBACK_FREQUENCY, (((currentChannelData->chMode == RADIO_MODE_DIGITAL) && (uiDataGlobal.reverseRepeaterChannel || codeplugChannelGetFlag(currentChannelData, CHANNEL_FLAG_FORCE_DMO))) ? DMR_MODE_DMO : DMR_MODE_AUTO));
	}
	else
#endif
	{
		uint32_t rxFreq = (uiDataGlobal.reverseRepeaterChannel ? currentChannelData->txFreq : currentChannelData->rxFreq);
		uint32_t txFreq = (uiDataGlobal.talkaround ? rxFreq : (uiDataGlobal.reverseRepeaterChannel ? currentChannelData->rxFreq : currentChannelData->txFreq));

#if defined(PLATFORM_MD9600)
		// Was flagged as out of band channel, it was probably edited and now it's fine, clear the flag
		if (codeplugChannelGetFlag(currentChannelData, CHANNEL_FLAG_OUT_OF_BAND) != 0)
		{
			codeplugChannelSetFlag(currentChannelData, CHANNEL_FLAG_OUT_OF_BAND, 0);
		}
#endif

		// If reverseRepeater mode is enabled (and mode is DIGITAL), force to DMR Active mode.
		trxSetFrequency(rxFreq, txFreq, (((currentChannelData->chMode == RADIO_MODE_DIGITAL) && (uiDataGlobal.reverseRepeaterChannel || codeplugChannelGetFlag(currentChannelData, CHANNEL_FLAG_FORCE_DMO))) ? DMR_MODE_DMO : DMR_MODE_AUTO));
	}

	trxSetModeAndBandwidth(currentChannelData->chMode, (codeplugChannelGetFlag(currentChannelData, CHANNEL_FLAG_BW_25K) != 0));

	if (currentChannelData->chMode == RADIO_MODE_ANALOG)
	{
		CodeplugAPRSConfig_t aprsConfig;
		bool aprsConfigUnsetOrQSY = (currentChannelData->aprsConfigIndex == 0) ||
				(codeplugAPRSGetDataForIndex(currentChannelData->aprsConfigIndex, &aprsConfig) && (aprsConfig.txFrequency != 0U));

		if (aprsConfigUnsetOrQSY == false)
		{
			currentChannelData->rxTone = CODEPLUG_CSS_TONE_NONE;
			currentChannelData->txTone = CODEPLUG_CSS_TONE_NONE;
			codeplugChannelSetFlag(currentChannelData, CHANNEL_FLAG_VOX, 0);
		}

		trxSetRxCSS(RADIO_DEVICE_PRIMARY, currentChannelData->rxTone);
	}
	else
	{
		uint32_t channelDMRId = codeplugChannelGetOptionalDMRID(currentChannelData);

		if (uiDataGlobal.manualOverrideDMRId == 0)
		{
			if (channelDMRId == 0)
			{
				trxDMRID = uiDataGlobal.userDMRId;
			}
			else
			{
				trxDMRID = channelDMRId;
			}
		}
		else
		{
			trxDMRID = uiDataGlobal.manualOverrideDMRId;
		}

		// Set CC when:
		//  - scanning
		//  - CC Filter is ON
		//  - CC Filter is OFF but not held anymore or loading a new channel (this avoids restoring Channel's CC when releasing the PTT key, or getting out of menus)
		if (uiDataGlobal.Scan.active ||
				((nonVolatileSettings.dmrCcTsFilter & DMR_CC_FILTER_PATTERN) ||
						(((nonVolatileSettings.dmrCcTsFilter & DMR_CC_FILTER_PATTERN) == 0) &&
								((HRC6000CCIsHeld() == false) || (previousSelectedChannelNumber != uiDataGlobal.currentSelectedChannelNumber)))))
		{
			trxSetDMRColourCode(currentChannelData->txColor);
			HRC6000ClearColorCodeSynchronisation();
		}

		if (currentChannelData->rxGroupList != lastLoadedRxGroup)
		{
			rxGroupValid = codeplugRxGroupGetDataForIndex(currentChannelData->rxGroupList, &currentRxGroupData);
			if (rxGroupValid)
			{
				lastLoadedRxGroup = currentChannelData->rxGroupList;
			}
			else
			{
				lastLoadedRxGroup = -1;// RxGroup Contacts are not valid
			}
		}

		// Current contact index is out of group list bounds, select first contact
		if (rxGroupValid && (nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE] > (currentRxGroupData.NOT_IN_CODEPLUG_numTGsInGroup - 1)))
		{
			settingsSet(nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE], 0);
			menuChannelExitStatus |= (MENU_STATUS_LIST_TYPE | MENU_STATUS_FORCE_FIRST);
		}

		// Check if this channel has an Rx Group
		if (rxGroupValid && nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE] < currentRxGroupData.NOT_IN_CODEPLUG_numTGsInGroup)
		{
			codeplugContactGetDataForIndex(currentRxGroupData.contacts[nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE]], &currentContactData);
		}
		else
		{
			codeplugContactGetDataForIndex(currentChannelData->contact, &currentContactData);
		}

		trxUpdateTsForCurrentChannelWithSpecifiedContact(&currentContactData);

		if (nonVolatileSettings.overrideTG == 0)
		{
			trxTalkGroupOrPcId = codeplugContactGetPackedId(&currentContactData);
		}
		else
		{
			trxTalkGroupOrPcId = nonVolatileSettings.overrideTG;
		}
	}

	int nextMenu = menuSystemGetPreviouslyPushedMenuNumber(false); // used to determine if this screen has just been loaded after Tx ended (in loadChannelData()))
#if ! defined(PLATFORM_GD77S) // GD77S handle voice prompts on its own
	if (((uiDataGlobal.VoicePrompts.inhibitInitial == false) || loadVoicePromptAnnouncement) &&
			((uiDataGlobal.Scan.active == false) ||
					(uiDataGlobal.Scan.active && ((uiDataGlobal.Scan.state == SCAN_STATE_SHORT_PAUSED) || (uiDataGlobal.Scan.state == SCAN_STATE_PAUSED)))))
	{
		announceItem((wasLoadingZone ? PROMPT_SEQUENCE_ZONE_NAME_CHANNEL_NAME_AND_CONTACT_OR_VFO_FREQ_AND_MODE : PROMPT_SEQUENCE_CHANNEL_NAME_AND_CONTACT_OR_VFO_FREQ_AND_MODE),
				((nextMenu == UI_TX_SCREEN) || (nextMenu == UI_LOCK_SCREEN) || (nextMenu == UI_PRIVATE_CALL) || uiDataGlobal.Scan.active) ? PROMPT_THRESHOLD_NEVER_PLAY_IMMEDIATELY : PROMPT_THRESHOLD_2);
	}
#else
	(void)nextMenu;
	// Force GD77S to always use the Master power level
	currentChannelData->libreDMR_Power = 0x00;
#endif

	if (uiDataGlobal.Scan.active == false)
	{
		checkChannelLocation(currentChannelData);

		if (useChannelDataInMemory == false)
		{
			aprsBeaconingResetTimers();
		}
	}
}

void uiChannelModeUpdateScreen(int txTimeSecs)
{
	char nameBuf[NAME_BUFFER_LEN];
	char buffer[SCREEN_LINE_BUFFER_SIZE];
#if defined(DUAL_CHANNEL_ENABLED)
	if (s_dualQuiet)
	{
		return;
	}
#endif
#if defined(PLATFORM_VARIANT_DM1701)
	bool dblHeight = UI_USES_DOUBLE_HEIGHT();
#endif
	bool isTransmitting = isTransmittingIgnoringAPRSBeaconing();

#if defined(DUAL_CHANNEL_ENABLED)
	if ((dualIsRunning() || dualHoldScreen()) && (uiDataGlobal.displayChannelSettings == false) && (isTransmitting == false))
	{
		dualRenderScreen();   // R97: власний екран режиму (два рядки каналів); стоковий нижче не малюється (R97-FIX5: і в паузі після клавіші)
		uiDataGlobal.displayQSOState = QSO_DISPLAY_IDLE;
		return;
	}
#endif

	// Only render the header, then wait for the next run
	// Otherwise the screen could remain blank if TG and PC are == 0
	// since uiDataGlobal.displayQSOState won't be set to QSO_DISPLAY_IDLE
	if ((trxGetMode() == RADIO_MODE_DIGITAL) && (HRC6000GetReceivedTgOrPcId() == 0) &&
			((uiDataGlobal.displayQSOState == QSO_DISPLAY_CALLER_DATA) || (uiDataGlobal.displayQSOState == QSO_DISPLAY_CALLER_DATA_UPDATE)))
	{
		uiUtilityRedrawHeaderOnly(false, false, false);
		return;
	}

	// We're currently displaying details, and it shouldn't be overridden by QSO data
	if (uiDataGlobal.displayChannelSettings && ((uiDataGlobal.displayQSOState == QSO_DISPLAY_CALLER_DATA)
			|| (uiDataGlobal.displayQSOState == QSO_DISPLAY_CALLER_DATA_UPDATE)))
	{
		// We will not restore the previous QSO Data as a new caller just arose.
		uiDataGlobal.displayQSOStatePrev = QSO_DISPLAY_DEFAULT_SCREEN;
		uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
	}

	displayClearBuf();
	uiUtilityRenderHeader(false, false,
#if defined(PLATFORM_MD9600) || defined(CPU_MK22FN512VLL12)
			false
#else
			((buttonsRead() & BUTTON_SK1) == BUTTON_SK1)
#endif
	);

	switch(uiDataGlobal.displayQSOState)
	{
		case QSO_DISPLAY_DEFAULT_SCREEN:
			lastHeardClearLastID();
			uiDataGlobal.displayQSOStatePrev = QSO_DISPLAY_DEFAULT_SCREEN;
			uiDataGlobal.isDisplayingQSOData = false;
			uiDataGlobal.receivedPcId = 0x00;

			if (isTransmitting)
			{
				int8_t yOverride =
#if defined(PLATFORM_VARIANT_DM1701)
						// Because of the screen height reduction, we need to move Contact
						// and Channel name slightly higher when double height font is enabled.
						(DISPLAY_Y_POS_TX_TIMER - (dblHeight ? 4 : 0));
#else
						-1;
#endif

#if defined(ENABLE_ROAM_RETRY)
				// R59: на екрані передачі -- позначка «знайдений канал» перед таймером
				if (roamIsActive())
				{
					snprintf(buffer, SCREEN_LINE_BUFFER_SIZE, "%s %d ", ROAM_IND_SPARE, txTimeSecs);
				}
				else
#endif
				snprintf(buffer, SCREEN_LINE_BUFFER_SIZE, " %d ", txTimeSecs);
				uiUtilityDisplayInformation(buffer, DISPLAY_INFO_TX_TIMER, yOverride);
			}
			else
			{
				// Display some channel settings
				if (uiDataGlobal.displayChannelSettings)
				{
					uint32_t rxFreq = (uiDataGlobal.reverseRepeaterChannel ? currentChannelData->txFreq : currentChannelData->rxFreq);
					uint32_t txFreq = (uiDataGlobal.talkaround ? rxFreq : (uiDataGlobal.reverseRepeaterChannel ? currentChannelData->rxFreq : currentChannelData->txFreq));

					uiUtilityDisplayInformation(NULL, DISPLAY_INFO_CHANNEL_DETAILS, -1);

					uiUtilityDisplayFrequency(DISPLAY_Y_POS_RX_FREQ, false, false, rxFreq, false, false, 0);
					uiUtilityDisplayFrequency(DISPLAY_Y_POS_TX_FREQ, true, false, txFreq, false, false, 0);
				}
				else
				{
					bool channelIsSkipped = (((uiDataGlobal.Scan.active == false) || (uiDataGlobal.Scan.active && (uiDataGlobal.Scan.state == SCAN_STATE_PAUSED))) &&
							((CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone) && codeplugChannelGetFlag(currentChannelData, CHANNEL_FLAG_ALL_SKIP)) ||
									((CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone) == false) && codeplugChannelGetFlag(currentChannelData, CHANNEL_FLAG_ZONE_SKIP))));

					if (directChannelNumber > 0)
					{
						snprintf(nameBuf, NAME_BUFFER_LEN, "%s %d", UI_SAFE_STR(currentLanguage->gotoChannel), directChannelNumber);
					}
					else
					{
						if (((uiDataGlobal.Scan.active == false) || (uiDataGlobal.Scan.active && (uiDataGlobal.Scan.state == SCAN_STATE_PAUSED))) &&
								((ROAMING_EFFECTIVE() != ROAMING_OFF) || (SETTINGS_CHANNEL_DISTANCE_EFFECTIVE() && (CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone) == false))))
						{
							if (currentChannelData->NOT_IN_CODEPLUG_CALCULATED_DISTANCE_X10 != -1)
							{
								int decLen;
								char distBuf[SCREEN_LINE_BUFFER_SIZE];
								char zNameBuf[SCREEN_LINE_BUFFER_SIZE];
								uint32_t intPart = (currentChannelData->NOT_IN_CODEPLUG_CALCULATED_DISTANCE_X10 / 10);
								uint32_t decPart = (currentChannelData->NOT_IN_CODEPLUG_CALCULATED_DISTANCE_X10 - (intPart * 10));

								if (decPart != 0)
								{
									decLen = snprintf(distBuf, SCREEN_LINE_BUFFER_SIZE, "%c %u.%u km", (channelIsSkipped ? '^' : '|'), intPart, decPart);
								}
								else
								{
									decLen = snprintf(distBuf, SCREEN_LINE_BUFFER_SIZE, "%c %u km", (channelIsSkipped ? '^' : '|'), intPart);
								}

								int zLen = snprintf(zNameBuf, SCREEN_LINE_BUFFER_SIZE, "%s", currentZoneName);

								// Truncate (with ellipsis) the zone name if the whole string doesn't fit the screen
								if ((zLen + decLen + 1) > (NAME_BUFFER_LEN - 1))
								{
									int nOffset = MAX(0, (zLen - (((decLen + zLen + 1) - (NAME_BUFFER_LEN - 1)) + 3)));

									memset(zNameBuf + nOffset, '.', 3);
									zNameBuf[nOffset + 3] = 0;
							     }

								snprintf(nameBuf, NAME_BUFFER_LEN, "%s %s", zNameBuf, distBuf);
							}
							else
							{
								snprintf(nameBuf, NAME_BUFFER_LEN, "%s %c --- km", currentZoneName, (channelIsSkipped ? '^' : '|'));
							}
						}
						else
						{
							snprintf(nameBuf, NAME_BUFFER_LEN, "%s Ch%c%d",
									(CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone) ? UI_SAFE_STR(currentLanguage->all_channels) : currentZoneName),
									(channelIsSkipped ? '^' : ':'),
									(codeplugGetLastUsedChannelInCurrentZone() + (CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone) ? 0 : 1)));
						}
					}

#if defined(ENABLE_ROAM_RETRY)
					// R59: індикатор «Роумінгу». На каналі, знайденому автопереходом, «зона Ch:N» не має сенсу (канал не з поточної зони) --
					// показуємо «R> канал N» (R67A: латинська R). Інакше, якщо функція ввімкнена і поточний канал у списку, дописуємо позначку «R».
					if (directChannelNumber > 0)
					{
						// набір номера каналу -- рядок «Перейти до каналу» лишаємо як є
					}
					else if (roamIsActive())
					{
						snprintf(nameBuf, NAME_BUFFER_LEN, ROAM_ZONE_SPARE_FMT, (int)roamActiveChannel());
					}
					else if (roamCfgIsEnabled() && (roamCurrentList() != 0U))
					{
						// R60: «R» з номером списку (« R1»..« R10»); не вміщається з номером -- голе « R»; зовсім нема місця -- без позначки,
						// наявні елементи рядка не зсуваємо.
						size_t zl = strlen(nameBuf);
						char indBuf[8];
						size_t il = (size_t)snprintf(indBuf, sizeof(indBuf), " %s%u", ROAM_IND_LIST, (unsigned)roamCurrentList());

						if ((zl + il) < NAME_BUFFER_LEN)
						{
							memcpy(nameBuf + zl, indBuf, il + 1U);
						}
						else if ((zl + 3U) < NAME_BUFFER_LEN)
						{
							snprintf(nameBuf + zl, NAME_BUFFER_LEN - zl, " %s", ROAM_IND_LIST);
						}
					}
#endif
					uiUtilityDisplayInformation(nameBuf, DISPLAY_INFO_ZONE, -2);
				}
			}

			if (!uiDataGlobal.displayChannelSettings)
			{
				int8_t yOverride = (isTransmitting ?
						DISPLAY_Y_POS_CHANNEL_SECOND_LINE
#if defined(PLATFORM_VARIANT_DM1701)
						// Because of the screen height reduction, we need to move Contact
						// and Channel name slightly higher when double height font is enabled.
						- (dblHeight ? 4 : 0)
#endif
						: -1);

#if defined(PLATFORM_MD9600)
				if (codeplugChannelGetFlag(currentChannelData, CHANNEL_FLAG_OUT_OF_BAND) != 0)
				{
					snprintf(nameBuf, NAME_BUFFER_LEN, "%s", currentLanguage->out_of_band);
				}
				else
#endif
				{
					codeplugUtilConvertBufToDisplayString(currentChannelData->name, nameBuf, 16);
				}

#if defined(DUAL_CHANNEL_ENABLED)
				if (dualOnVfoNow() && (currentChannelData == &settingsVFOChannel[dualCardVfo(dcIsOnB())]))
				{
					snprintf(nameBuf, NAME_BUFFER_LEN, "VFO %c", (char)('A' + dualCardVfo(dcIsOnB())));   // R98: передача з картки VFO -- стокове ім'я VFO зазвичай порожнє
				}
#endif

				uiUtilityDisplayInformation(nameBuf, (uiDataGlobal.reverseRepeaterChannel ? DISPLAY_INFO_CHANNEL_INVERTED : DISPLAY_INFO_CHANNEL), yOverride);
			}

			if (trxGetMode() == RADIO_MODE_DIGITAL)
			{
				if (!uiDataGlobal.displayChannelSettings)
				{
					int8_t yOverride = 0;

					if ((trxTransmissionEnabled == false) && (aprsBeaconingIsTransmitting() == false) &&
							(uiDataGlobal.Scan.active == false) &&
							((nonVolatileSettings.lastTalkerOnScreenTimer > 0U) &&
									ticksTimerHasExpired(&uiDataGlobal.DMRLastTalkerOnScreen.timer))
					)
					{
						ticksTimerStart(&uiDataGlobal.DMRLastTalkerOnScreen.timer, (nonVolatileSettings.lastTalkerOnScreenTimer * 1000U));
						uiDataGlobal.DMRLastTalkerOnScreen.visible = (((audioAmpGetStatus() & AUDIO_AMP_CHANNEL_RF) || (uiDataGlobal.lastHeardCount < 1)) ? false : !uiDataGlobal.DMRLastTalkerOnScreen.visible);

						if (uiDataGlobal.DMRLastTalkerOnScreen.visible)
						{
							if (uiDataGlobal.lastHeardCount > 0)
							{
								bool displayTA = false;
								LinkItem_t *item = LinkHead;

								switch (nonVolatileSettings.contactDisplayPriority)
								{
									case CONTACT_DISPLAY_PRIO_CC_DB_TA:
									case CONTACT_DISPLAY_PRIO_DB_CC_TA:
										// No contact found in codeplug and DMRIDs, use TA as fallback, if any.
										if ((strncmp(item->contact, "ID:", 3) == 0) && (item->talkerAlias[0] != 0x00))
										{
											displayTA = true;
										}
										break;

									case CONTACT_DISPLAY_PRIO_TA_CC_DB:
									case CONTACT_DISPLAY_PRIO_TA_DB_CC:
										if (item->talkerAlias[0] != 0x00)
										{
											displayTA = true;
										}
										break;
								}

								if (displayTA)
								{
									getCallsignOnly(nameBuf, item->talkerAlias);
								}
								else
								{
									getCallsignOnly(nameBuf, item->contact);
								}
							}
							else
							{
								goto displayContactName;
							}
						}
						else
						{
							goto displayContactName;
						}
					}
					else
					{
						displayContactName:

						if (nonVolatileSettings.overrideTG != 0)
						{
							yOverride = (isTransmitting ?
									DISPLAY_Y_POS_CONTACT_TX_FRAME
#if defined(PLATFORM_VARIANT_DM1701)
									// Because of the screen height reduction, we need to move Contact
									// and Channel name slightly higher when double height font is enabled.
									- (dblHeight ? 8 : 0)
#endif
									: -1);

							uiUtilityBuildTgOrPCDisplayName(nameBuf, SCREEN_LINE_BUFFER_SIZE);
							uiUtilityDisplayInformation(NULL, DISPLAY_INFO_CONTACT_OVERRIDE_FRAME, yOverride);
						}
						else
						{
							codeplugUtilConvertBufToDisplayString(currentContactData.name, nameBuf, 16);
						}
					}

					yOverride = (isTransmitting ?
							DISPLAY_Y_POS_CONTACT_TX
#if defined(PLATFORM_VARIANT_DM1701)
							// Because of the screen height reduction, we need to move Contact
							// and Channel name slightly higher when double height font is enabled.
							- (dblHeight ? 8 : 0)
#endif
							: -1);

					uiUtilityDisplayInformation(nameBuf, DISPLAY_INFO_CONTACT, yOverride);
				}

			}
			else
			{
				if (ticksTimerIsEnabled(&uiDataGlobal.DMRLastTalkerOnScreen.timer))
				{
					ticksTimerReset(&uiDataGlobal.DMRLastTalkerOnScreen.timer);
					uiDataGlobal.DMRLastTalkerOnScreen.visible = false;
				}
			}

#if defined(ENABLE_AES)
			// Постійна позначка "цей канал налаштовано на шифрування" на екрані очікування
			// (цей case виконується на кожному оновленні екрана очікування, незалежно від
			// активного співрозмовника -- на відміну від uiUtilityRenderQSOData(), яка малює
			// лише під час активного виклику або останнього почутого).
			uiDrawAesEnabledIcon();
#endif

			displayRender();
			break;

		case QSO_DISPLAY_CALLER_DATA:
		case QSO_DISPLAY_CALLER_DATA_UPDATE:
			uiDataGlobal.displayQSOStatePrev = QSO_DISPLAY_CALLER_DATA;
			uiDataGlobal.isDisplayingQSOData = true;
			uiDataGlobal.displayChannelSettings = false;
			uiUtilityRenderQSOData();
			displayRender();
			break;

		case QSO_DISPLAY_IDLE:
			break;
	}

	uiDataGlobal.displayQSOState = QSO_DISPLAY_IDLE;
}

// R98-FIX3 Б: крок порогу шумодава FM поточного каналу (currentChannelData) -- стокова логіка ▲/▼ екрана каналу, винесена без змін: старт від типового для
// діапазону, якщо sql == 0; межі CODEPLUG_MIN/MAX_VARIABLE_SQUELCH; голосова підказка, сповіщення NOTIFICATION_ID_SQUELCH, перемальовування. always_inline --
// у кожному місці виклику код той самий, що стоковий (збірка без прапорця не змінюється). dir > 0 -- вище, інакше нижче.
static inline __attribute__((always_inline)) void channelSquelchStep(int dir)
{
	if(currentChannelData->sql == 0)			//If we were using default squelch level
	{
		currentChannelData->sql = nonVolatileSettings.squelchDefaults[currentRadioDevice->trxCurrentBand[TRX_RX_FREQ_BAND]];			//start the adjustment from that point.
	}

	if (dir > 0)
	{
		if (currentChannelData->sql < CODEPLUG_MAX_VARIABLE_SQUELCH)
		{
			currentChannelData->sql++;
		}
	}
	else
	{
		if (currentChannelData->sql > CODEPLUG_MIN_VARIABLE_SQUELCH)
		{
			currentChannelData->sql--;
		}
	}

	announceItem(PROMPT_SQUENCE_SQUELCH, PROMPT_THRESHOLD_3);

	uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
	uiNotificationShow(NOTIFICATION_TYPE_SQUELCH, NOTIFICATION_ID_SQUELCH, 1000, NULL, false);
	uiChannelModeUpdateScreen(0);
}

// R98-FIX5 А2: крок ТГ у списку прийому поточного DMR-каналу (currentRxGroupData, індекс SETTINGS_CHANNEL_MODE) -- стокова логіка ▲/▼ екрана каналу,
// винесена без змін (обидві гілки: «вгору» -- по колу на 0 з FORCE_FIRST; «вниз» -- по колу на останній, FORCE_FIRST на 0); скидання overrideTG,
// menuPrivateCallClear(), updateTrxID(), таймер показу абонента, перемальовування, підказка. always_inline -- як channelSquelchStep(). dir > 0 -- вгору.
static inline __attribute__((always_inline)) void channelTgStep(int dir)
{
	if (currentRxGroupData.NOT_IN_CODEPLUG_numTGsInGroup > 1)
	{
		if (dir > 0)
		{
			if (nonVolatileSettings.overrideTG == 0)
			{
				settingsIncrement(nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE], 1);
				if (nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE] > (currentRxGroupData.NOT_IN_CODEPLUG_numTGsInGroup - 1))
				{
					settingsSet(nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE], 0);
					menuChannelExitStatus |= (MENU_STATUS_LIST_TYPE | MENU_STATUS_FORCE_FIRST);
				}
			}
		}
		else
		{
			// To Do change TG in on same channel freq
			if (nonVolatileSettings.overrideTG == 0)
			{
				settingsDecrement(nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE], 1);
				if (nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE] < 0)
				{
					settingsSet(nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE],
							(int16_t) (currentRxGroupData.NOT_IN_CODEPLUG_numTGsInGroup - 1));
				}

				if (nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE] == 0)
				{
					menuChannelExitStatus |= (MENU_STATUS_LIST_TYPE | MENU_STATUS_FORCE_FIRST);
				}
			}
		}
	}
	settingsSet(nonVolatileSettings.overrideTG, 0);// setting the override TG to 0 indicates the TG is not overridden
	menuPrivateCallClear();
	updateTrxID();
	// We're in digital mode, RXing, and current talker is already at the top of last heard list,
	// hence immediately display complete contact/TG info on screen
	uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;//(isQSODataAvailableForCurrentTalker() ? QSO_DISPLAY_CALLER_DATA : QSO_DISPLAY_DEFAULT_SCREEN);
	if (isQSODataAvailableForCurrentTalker())
	{
		(void)addTimerCallback(uiUtilityRenderQSODataAndUpdateScreen, 2000, UI_CHANNEL_MODE, true);
	}
	uiChannelModeUpdateScreen(0);
	announceItem(PROMPT_SEQUENCE_CONTACT_TG_OR_PC, PROMPT_THRESHOLD_3);
}

#if defined(DUAL_CHANNEL_ENABLED)
static void handleEventCore(uiEvent_t *ev);

// R97-FIX5: «тиша» (s_dualQuiet) охоплює весь обробник клавіші; наприкінці -- гарантоване скидання й один перемальований екран
// R98-FIX5 А5: клавіша-параметр на картці VFO (A або B) пройшла стоковий обробник екрана каналу, який пише ТС-перекриття у «відро» каналу
// (tsSetManualOverride(CHANNEL_CHANNEL, ...)) -- переносимо зміну у відро цього VFO (як у стоковому екрані VFO), відро каналу повертаємо, VFO перечитуємо
// ізольовано (ТС/контакт за правилами VFO); запис VFO (потужність, режим, смуга) -- стоково settingsSetVFODirty().
static void dualVfoKeyDone(const uiEvent_t *ev, uint16_t tsBefore)
{
	if (((ev->events & KEY_EVENT) == 0) || (dualOnVfoNow() == false) || (menuSystemGetCurrentMenuNumber() != UI_CHANNEL_MODE))
	{
		return;
	}

	uint16_t now = nonVolatileSettings.tsManualOverride;
	uint8_t vfo = dualCardVfo(dcIsOnB());

	if (now != tsBefore)
	{
		int v = ((int)CHANNEL_VFO_A + (int)vfo);
		int c = (int)CHANNEL_CHANNEL;
		uint16_t res = tsBefore;

		res = (uint16_t)((res & ~(0x03U << (2 * v))) | (((now >> (2 * c)) & 0x03U) << (2 * v)));
		res = (uint16_t)((res & ~(0x01U << (6 + v))) | (((now >> (6 + c)) & 0x01U) << (6 + v)));
		settingsSet(nonVolatileSettings.tsManualOverride, res);
		uiVFOModeDualLoad(vfo, false);
	}

	if ((ev->keys.key == KEY_STAR) || (ev->keys.key == KEY_HASH) ||
			(BUTTONCHECK_DOWN(ev, BUTTON_SK2) && ((ev->keys.key == KEY_INCREASE) || (ev->keys.key == KEY_DECREASE))))
	{
		settingsSetVFODirty();
	}
}

static void handleEvent(uiEvent_t *ev)
{
	uint16_t tsBefore = nonVolatileSettings.tsManualOverride;

	handleEventCore(ev);
	dualVfoKeyDone(ev, tsBefore);
	dualQuietEnd();
}

static void handleEventCore(uiEvent_t *ev)
#else
static void handleEvent(uiEvent_t *ev)
#endif
{
#if defined(PLATFORM_GD77S)
	handleEventForGD77S(ev);
	return;
#else

#if defined(DUAL_CHANNEL_ENABLED)
	if (ev->events & KEY_EVENT)
	{
		s_dualKeyMs = ticksGetMillis();

		// R98-FIX3 А: цифри -- набір для картки з покажчиком (номер каналу / частота VFO); поки триває набір, ВСІ клавіші йдуть сюди
		if (dualEntryKey(ev))
		{
			return;
		}

		bool dwRunning = dualIsRunning();

		// R98-FIX5 А0: у режимі КОЖНА клавіша спершу йде в правила режиму -- і під час чергування, і в паузі після клавіші (раніше в паузі, коли A != B,
		// ручка й ▲/▼ потрапляли в стокові обробники: ручка міняла канал A навіть при покажчику на B, ▲/▼ -- ТГ/шумодав замість покажчика).
		if (dcIsEnabled())
		{
			if (dualHandleKey(ev))
			{
				return;
			}

			// R97: решта клавіш -- стокові обробники нижче; чергування зупиняється, режим лишається ввімкненим
			if (dwRunning)
			{
				dualSuspend();
			}

			// R97-FIX5: стокова обробка клавіші (будь-якої) не малює свій екран із S-метром -- екран малює dualQuietEnd() після обробника
			s_dualQuiet = true;

			// R98-FIX5 А5: решта клавіш (`*`, `#`, SK2 + ▲/▼ -- потужність, SK2 + `*`/`#`, ...) діють на КАРТКУ З ПОКАЖЧИКОМ: рація спершу стає на неї
			// (A == B -- один канал, A). Винятки: зелена (головне меню / деталі -- на ОБРАНОМУ, як і раніше) і довге ▼ (гаряча клавіша, тут не буває).
			// Правки картки зберігаються: A -- канальний буфер (+ копія R98-FIX2 Є), B = канал -- робоча копія B (А5), VFO -- запис VFO (dualVfoKeyDone()).
			bool toB = (dcPointerB() && (dualSingle() == false));

			if ((dcIsOnB() != toB) && (ev->keys.key != KEY_GREEN) && (KEYCHECK_LONGDOWN(ev->keys, KEY_FRONT_DOWN) == false))
			{
				dualTune(toB);
			}
		}
	}
#endif

	if (uiDataGlobal.Scan.active && (ev->events & KEY_EVENT))
	{
		// Key pressed during scanning

		if (BUTTONCHECK_DOWN(ev, BUTTON_SK2) == 0)
		{
			// if we are scanning and down key is pressed then enter current channel into nuisance delete array.
			if((uiDataGlobal.Scan.state == SCAN_STATE_PAUSED) &&
#if defined(PLATFORM_MDUV380) || defined(PLATFORM_MD380)
					(ev->keys.key == KEY_STAR)
#else
					(ev->keys.key == KEY_RIGHT)
#endif
			)
			{
				// There is two channels available in the Zone, just stop scanning
				if (uiDataGlobal.Scan.nuisanceDeleteIndex == (uiDataGlobal.Scan.availableChannelsCount - 2))
				{
					uiDataGlobal.Scan.lastIteration = true;
				}

				uiDataGlobal.Scan.nuisanceDelete[uiDataGlobal.Scan.nuisanceDeleteIndex] = uiDataGlobal.currentSelectedChannelNumber;
				uiDataGlobal.Scan.nuisanceDeleteIndex = (uiDataGlobal.Scan.nuisanceDeleteIndex + 1) % MAX_ZONE_SCAN_NUISANCE_CHANNELS;
				uiDataGlobal.Scan.timer.timeout = SCAN_SKIP_CHANNEL_INTERVAL;	//force scan to continue;
				uiDataGlobal.Scan.state = SCAN_STATE_SCANNING;
				keyboardReset();
				return;
			}

			// KEY_DOWN/KEY_LEFT reverse the scan direction
			if (
#if defined(PLATFORM_MDUV380) || defined(PLATFORM_MD380)
					(ev->keys.key == KEY_FRONT_DOWN)
#else
					(ev->keys.key == KEY_LEFT)
#endif
			)
			{
				uiDataGlobal.Scan.direction *= -1;
				keyboardReset();
				return;
			}
		}

		// stop the scan on any button except:
		//    - MD9600: UP without Shift (allows scan to be manually continued), or Right
		//    - MDUV380/DM1701/MD2017: UP/ROTARY_INC without SK2 (allows scan to be manually continued)
		//    - MK22: UP without Shift (allows scan to be manually continued)
		// or SK2 on its own (allows Backlight to be triggered)
		if ((
#if defined(PLATFORM_MDUV380) || defined(PLATFORM_MD380) || defined(PLATFORM_RT84_DM1701) || defined(PLATFORM_MD2017)
				((ev->keys.key == KEY_FRONT_UP) || (ev->keys.key == KEY_ROTARY_INCREMENT))
#elif defined(PLATFORM_MD9600)
				((ev->keys.key == KEY_UP) || (ev->keys.key == KEY_RIGHT))
#else
				(ev->keys.key == KEY_UP)
#endif
				&& (BUTTONCHECK_DOWN(ev, BUTTON_SK2) == 0)) == false)
		{
			scanStop(true);
			keyboardReset();
			return;
		}
	}

	if (ev->events & FUNCTION_EVENT)
	{
		if (ev->function == FUNC_START_SCANNING)
		{
			directChannelNumber = 0;
			if (uiDataGlobal.Scan.active == false)
			{
				scanStart(false);
			}
			return;
		}
		else if (ev->function == FUNC_REDRAW)
		{
			uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
			uiChannelModeUpdateScreen(0);
			return;
		}
	}

	if (handleMonitorMode(ev))
	{
		uiDataGlobal.displayChannelSettings = false;
		return;
	}

	if (ev->events & BUTTON_EVENT)
	{
		if (rebuildVoicePromptOnExtraLongSK1(ev))
		{
			return;
		}

		if (repeatVoicePromptOnSK1(ev))
		{
			return;
		}

#if defined(ENABLE_CALL_REPLAY)
		if (callReplayToggleOnSK1(ev))
		{
			return;
		}
#endif

		uint32_t tg = (LinkHead->talkGroupOrPcId & 0xFFFFFF);

		// If Blue button is pressed during reception it sets the Tx TG to the incoming TG
		if (uiDataGlobal.isDisplayingQSOData && BUTTONCHECK_SHORTUP(ev, BUTTON_SK2) && (trxGetMode() == RADIO_MODE_DIGITAL) &&
				((trxTalkGroupOrPcId != tg) ||
						((dmrMonitorCapturedTS != -1) && (dmrMonitorCapturedTS != trxGetDMRTimeSlot())) ||
						(trxGetDMRColourCode() != currentChannelData->txColor)))
		{
			lastHeardClearLastID();

			// Set TS to overriden TS
			if ((dmrMonitorCapturedTS != -1) && (dmrMonitorCapturedTS != trxGetDMRTimeSlot()))
			{
				trxSetDMRTimeSlot(dmrMonitorCapturedTS, false);
				tsSetManualOverride(CHANNEL_CHANNEL, (dmrMonitorCapturedTS + 1));
			}

			if (trxTalkGroupOrPcId != tg)
			{
				trxTalkGroupOrPcId = tg;
				settingsSet(nonVolatileSettings.overrideTG, trxTalkGroupOrPcId);
			}

			currentChannelData->txColor = trxGetDMRColourCode();// Set the CC to the current CC, which may have been determined by the CC finding algorithm in C6000.c

			announceItem(PROMPT_SEQUENCE_CONTACT_TG_OR_PC,PROMPT_THRESHOLD_NEVER_PLAY_IMMEDIATELY);

			uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
			uiChannelModeUpdateScreen(0);
			uiDataGlobal.displayQSOState = QSO_DISPLAY_CALLER_DATA_UPDATE;
			soundSetMelody(MELODY_ACK_BEEP);
			return;
		}

		// Display channel settings (RX/TX/etc) while SK1 is pressed
		if ((uiDataGlobal.displayChannelSettings == false) && (monitorModeData.isEnabled == false) && BUTTONCHECK_DOWN(ev, BUTTON_SK1))
		{
			if ((uiDataGlobal.Scan.active == false) || (uiDataGlobal.Scan.active && (uiDataGlobal.Scan.state == SCAN_STATE_PAUSED)))
			{
				int prevQSODisp = uiDataGlobal.displayQSOStatePrev;
				uiDataGlobal.displayChannelSettings = true;
				headerRowIsDirty = true;
				uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
				uiChannelModeUpdateScreen(0);
				uiDataGlobal.displayQSOStatePrev = prevQSODisp;
			}
			return;

		}
		else if (uiDataGlobal.displayChannelSettings && (BUTTONCHECK_DOWN(ev, BUTTON_SK1) == 0))
		{
			hidesChannelDetails();
			return;
		}

#if !defined(PLATFORM_RD5R)
		if (BUTTONCHECK_SHORTUP(ev, BUTTON_ORANGE) && (BUTTONCHECK_DOWN(ev, BUTTON_SK1) == 0))
		{
			if (BUTTONCHECK_DOWN(ev, BUTTON_SK2))
			{
				announceItem(PROMPT_SEQUENCE_BATTERY, AUDIO_PROMPT_MODE_VOICE_LEVEL_1);
			}
			else
			{
				// Quick Menu
				menuSystemPushNewMenu(UI_CHANNEL_QUICK_MENU);

				// Trick to beep (AudioAssist), since ORANGE button doesn't produce any beep event
				ev->keys.event |= KEY_MOD_UP;
				ev->keys.key = 127;
				menuChannelExitStatus |= (MENU_STATUS_LIST_TYPE | MENU_STATUS_FORCE_FIRST);
				// End Trick
			}

			return;
		}
#endif
	}

	if (ev->events & KEY_EVENT)
	{
#if defined(PLATFORM_MD9600)
		if (KEYCHECK_LONGDOWN(ev->keys, KEY_GREEN))
		{
			if (uiDataGlobal.Scan.active)
			{
				uiChannelModeStopScanning();
			}

			menuSystemPushNewMenu(UI_CHANNEL_QUICK_MENU);

			// Trick to beep (AudioAssist), since ORANGE button doesn't produce any beep event
			ev->keys.event |= KEY_MOD_UP;
			ev->keys.key = 127;
			menuChannelExitStatus |= (MENU_STATUS_LIST_TYPE | MENU_STATUS_FORCE_FIRST);
			// End Trick
			return;
		}
		else
#endif
		if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
		{
			if (directChannelNumber > 0)
			{
				if(CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone))
				{
					// All Channels virtual zone
					if (codeplugAllChannelsIndexIsInUse(directChannelNumber))
					{
						codeplugSetLastUsedChannelInZone(currentZone.NOT_IN_CODEPLUGDATA_indexNumber, directChannelNumber);
						uiChannelModeLoadChannelData(false, true);

					}
					else
					{
						soundSetMelody(MELODY_ERROR_BEEP);
					}
				}
				else
				{
					if ((directChannelNumber - 1) < currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone)
					{
						codeplugSetLastUsedChannelInZone(currentZone.NOT_IN_CODEPLUGDATA_indexNumber, (directChannelNumber - 1));
						uiChannelModeLoadChannelData(false, true);
					}
					else
					{
						soundSetMelody(MELODY_ERROR_BEEP);
					}

				}
				directChannelNumber = 0;
				uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
				uiChannelModeUpdateScreen(0);
			}
			else if (BUTTONCHECK_DOWN(ev, BUTTON_SK2))
			{
				menuSystemPushNewMenu(MENU_CHANNEL_DETAILS);
			}
			else
			{
				menuSystemPushNewMenu(MENU_MAIN_MENU);
			}
			return;
		}
		else if (KEYCHECK_SHORTUP(ev->keys, KEY_HASH))
		{
			if (BUTTONCHECK_DOWN(ev, BUTTON_SK2))
			{
				// Assignment for SK2 + #
				menuSystemPushNewMenu(MENU_CONTACT_QUICKLIST);
			}
			else
			{
				menuSystemPushNewMenu(MENU_NUMERICAL_ENTRY);
			}
			return;
		}
		else if (KEYCHECK_LONGDOWN(ev->keys, KEY_RED) && (KEYCHECK_LONGDOWN_REPEAT(ev->keys, KEY_RED) == false) && BUTTONCHECK_DOWN(ev, BUTTON_SK1))
		{
			uiChannelModeOrVFOModeThemeDaytimeChange(false, true);
			return;
		}
		else if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
		{
			if (BUTTONCHECK_DOWN(ev, BUTTON_SK1))
			{
				uiChannelModeOrVFOModeThemeDaytimeChange(true, true);
				return;
			}
			else if (BUTTONCHECK_DOWN(ev, BUTTON_SK2) && (uiDataGlobal.tgBeforePcMode != 0))
			{
				settingsSet(nonVolatileSettings.overrideTG, uiDataGlobal.tgBeforePcMode);
				menuPrivateCallClear();

				updateTrxID();
				uiDataGlobal.displayQSOState= QSO_DISPLAY_DEFAULT_SCREEN;// Force redraw
				uiChannelModeUpdateScreen(0);
				return;// The event has been handled
			}

			if(directChannelNumber > 0)
			{
				announceItem(PROMPT_SEQUENCE_CHANNEL_NAME_OR_VFO_FREQ, PROMPT_THRESHOLD_NEVER_PLAY_IMMEDIATELY);

				directChannelNumber = 0;
				uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
				uiChannelModeUpdateScreen(0);
			}
			else
			{
#if ! (defined(PLATFORM_DM1801) || defined(PLATFORM_RD5R))
				menuSystemSetCurrentMenu(UI_VFO_MODE);
#endif
				return;
			}
		}
#if defined(PLATFORM_DM1801) || defined(PLATFORM_RD5R)
		else if (KEYCHECK_SHORTUP(ev->keys, KEY_VFO_MR))
		{
			directChannelNumber = 0;
			menuSystemSetCurrentMenu(UI_VFO_MODE);
			return;
		}
#endif
#if defined(PLATFORM_RD5R)
		else if (KEYCHECK_LONGDOWN(ev->keys, KEY_VFO_MR) && (BUTTONCHECK_DOWN(ev, BUTTON_SK1) == 0))
		{
			if (BUTTONCHECK_DOWN(ev, BUTTON_SK2))
			{
				announceItem(PROMPT_SEQUENCE_BATTERY, AUDIO_PROMPT_MODE_VOICE_LEVEL_1);
			}
			else
			{
				menuSystemPushNewMenu(UI_CHANNEL_QUICK_MENU);

				// Trick to beep (AudioAssist), since ORANGE button doesn't produce any beep event
				ev->keys.event |= KEY_MOD_UP;
				ev->keys.key = 127;
				menuChannelExitStatus |= (MENU_STATUS_LIST_TYPE | MENU_STATUS_FORCE_FIRST);
				// End Trick
			}

			return;
		}
#endif
		else if (KEYCHECK_LONGDOWN(ev->keys, KEY_INCREASE) // set as KEY_RIGHT on some platforms
#if defined(PLATFORM_MD380) || defined(PLATFORM_MDUV380)
				&& BUTTONCHECK_DOWN(ev, BUTTON_SK2)
#endif
		)
		{
			// Long press allows the 5W+ power setting to be selected immediately
#if defined(PLATFORM_MD380) || defined(PLATFORM_MDUV380)
			if (increasePowerLevel(true))
			{
				uiUtilityRedrawHeaderOnly(false, false, false);
			}
#else
			if (BUTTONCHECK_DOWN(ev, BUTTON_SK2))
			{
				if (increasePowerLevel(true))
				{
					uiUtilityRedrawHeaderOnly(false, false, false);
				}
			}
#endif
		}
		else if (KEYCHECK_SHORTUP(ev->keys, KEY_INCREASE)) // set as KEY_RIGHT on some platforms
#if defined(PLATFORM_MD9600) || defined(PLATFORM_MD380) || defined(PLATFORM_MDUV380)
		{
			if (uiDataGlobal.Scan.active)
			{
				handleUpKey(ev);
			}
			else
#endif
			{
				if (BUTTONCHECK_DOWN(ev, BUTTON_SK2))
				{
					if (increasePowerLevel(false))
					{
						uiUtilityRedrawHeaderOnly(false, false, false);
					}
				}
				else
				{
					if (trxGetMode() == RADIO_MODE_DIGITAL)
					{
						channelTgStep(1);   // R98-FIX5 А2: та сама логіка, спільна з «Подвійним прийомом» (SK1 + ручка на DMR-картці)
					}
					else
					{
						channelSquelchStep(1);   // R98-FIX3 Б: та сама логіка, спільна з «Подвійним прийомом» (SK1 + ручка)
					}
				}
#if defined(PLATFORM_MD9600) || defined(PLATFORM_MD380) || defined(PLATFORM_MDUV380)
			}
#endif
		}
		else if (KEYCHECK_SHORTUP(ev->keys, KEY_DECREASE)) // set as KEY_LEFT on some platforms
		{
			if (BUTTONCHECK_DOWN(ev, BUTTON_SK2))
			{
				if (decreasePowerLevel())
				{
					uiUtilityRedrawHeaderOnly(false, false, false);
				}

				if (trxGetPowerLevel() == 0)
				{
					menuChannelExitStatus |= (MENU_STATUS_LIST_TYPE | MENU_STATUS_FORCE_FIRST);
				}
			}
			else
			{
				if (trxGetMode() == RADIO_MODE_DIGITAL)
				{
					channelTgStep(-1);   // R98-FIX5 А2
				}
				else
				{
					channelSquelchStep(-1);   // R98-FIX3 Б
				}

			}
		}
		else if (KEYCHECK_SHORTUP(ev->keys, KEY_STAR))
		{
			if (BUTTONCHECK_DOWN(ev, BUTTON_SK2))  // Toggle Channel Mode
			{
				if (trxGetMode() == RADIO_MODE_ANALOG)
				{
					currentChannelData->chMode = RADIO_MODE_DIGITAL;
					uiDataGlobal.VoicePrompts.inhibitInitial = true;// Stop VP playing in loadChannelData
					uiChannelModeLoadChannelData(true, false);
					uiDataGlobal.VoicePrompts.inhibitInitial = false;
					menuChannelExitStatus |= MENU_STATUS_FORCE_FIRST;
				}
				else
				{
					currentChannelData->chMode = RADIO_MODE_ANALOG;
					trxSetModeAndBandwidth(currentChannelData->chMode, (codeplugChannelGetFlag(currentChannelData, CHANNEL_FLAG_BW_25K) != 0));
					trxSetRxCSS(RADIO_DEVICE_PRIMARY, currentChannelData->rxTone);
				}

				announceItem(PROMPT_SEQUENCE_MODE, PROMPT_THRESHOLD_1);
				uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
				uiChannelModeUpdateScreen(0);
			}
			else
			{
				if (trxGetMode() == RADIO_MODE_DIGITAL)
				{
					// Toggle timeslot
					trxSetDMRTimeSlot(1 - trxGetDMRTimeSlot(), true);
					tsSetManualOverride(CHANNEL_CHANNEL, (trxGetDMRTimeSlot() + 1));

					if ((nonVolatileSettings.overrideTG == 0) && (currentContactData.reserve1 & CODEPLUG_CONTACT_FLAG_NO_TS_OVERRIDE) == 0x00)
					{
						tsSetContactHasBeenOverriden(CHANNEL_CHANNEL, true);
					}

					audioAmpDisable(AUDIO_AMP_CHANNEL_RF);
					lastHeardClearLastID();
					uiDataGlobal.displayQSOState = uiDataGlobal.displayQSOStatePrev;
					uiChannelModeUpdateScreen(0);

					if (trxGetDMRTimeSlot() == 0)
					{
						menuChannelExitStatus |= MENU_STATUS_FORCE_FIRST;
					}
					announceItem(PROMPT_SEQUENCE_TS,PROMPT_THRESHOLD_3);
				}
				else
				{
					uint8_t bw25k = codeplugChannelSetFlag(currentChannelData, CHANNEL_FLAG_BW_25K, !(codeplugChannelGetFlag(currentChannelData, CHANNEL_FLAG_BW_25K)));

					if (bw25k)
					{
						nextKeyBeepMelody = (int16_t *)MELODY_KEY_BEEP_FIRST_ITEM;
					}

					// ToDo announce VP for bandwidth perhaps
					trxSetModeAndBandwidth(RADIO_MODE_ANALOG, (bw25k != 0));
					soundSetMelody(MELODY_NACK_BEEP);
					headerRowIsDirty = true;
					uiDataGlobal.displayQSOState = uiDataGlobal.displayQSOStatePrev;
					uiChannelModeUpdateScreen(0);
				}
			}
		}
		else if (KEYCHECK_LONGDOWN(ev->keys, KEY_STAR) && (BUTTONCHECK_DOWN(ev, BUTTON_SK2) == 0))
		{
			if (trxGetMode() == RADIO_MODE_DIGITAL)
			{
				tsSetManualOverride(CHANNEL_CHANNEL, TS_NO_OVERRIDE);
				tsSetContactHasBeenOverriden(CHANNEL_CHANNEL, false);

				if ((currentRxGroupData.name[0] != 0) && (nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE] < currentRxGroupData.NOT_IN_CODEPLUG_numTGsInGroup))
				{
					codeplugContactGetDataForIndex(currentRxGroupData.contacts[nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE]], &currentContactData);
				}
				else
				{
					codeplugContactGetDataForIndex(currentChannelData->contact, &currentContactData);
				}

				trxUpdateTsForCurrentChannelWithSpecifiedContact(&currentContactData);

				lastHeardClearLastID();
				uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
				uiChannelModeUpdateScreen(0);
				announceItem(PROMPT_SEQUENCE_TS, PROMPT_THRESHOLD_1);
			}
		}
		else if (KEYCHECK_LONGDOWN(ev->keys, KEY_HASH) && (KEYCHECK_LONGDOWN_REPEAT(ev->keys, KEY_HASH) == false))
		{
			uiDataGlobal.talkaround = false; // Talkaround and reverseRepeater are mutually exclusive.
			uiDataGlobal.reverseRepeaterChannel = !uiDataGlobal.reverseRepeaterChannel;

			uint32_t rxFreq = (uiDataGlobal.reverseRepeaterChannel ? currentChannelData->txFreq : currentChannelData->rxFreq);
			uint32_t txFreq = (uiDataGlobal.reverseRepeaterChannel ? currentChannelData->rxFreq : currentChannelData->txFreq);

			// If reverseRepeater mode is enabled (and mode is DIGITAL), force to DMR Active mode.
			trxSetFrequency(rxFreq, txFreq, (((currentChannelData->chMode == RADIO_MODE_DIGITAL) && (uiDataGlobal.reverseRepeaterChannel || codeplugChannelGetFlag(currentChannelData, CHANNEL_FLAG_FORCE_DMO))) ? DMR_MODE_DMO : DMR_MODE_AUTO));

			// Play a special beep when Reverse Repeater is enabled or disabled.
			soundSetMelody((uiDataGlobal.reverseRepeaterChannel ? MELODY_KEY_BEEP_FIRST_ITEM : MELODY_BEEP_LOW_SHORT));
			nextKeyBeepMelody = NULL;
			ev->keys.event &= ~(KEY_MOD_LONG | KEY_MOD_DOWN | KEY_MOD_PRESS | KEY_MOD_UP);
			ev->keys.key = 0;

			announceItem(PROMPT_SEQUENCE_CHANNEL_NAME_AND_CONTACT_OR_VFO_FREQ_AND_MODE, PROMPT_THRESHOLD_NEVER_PLAY_IMMEDIATELY);
			uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
			uiChannelModeUpdateScreen(0);
			return;
		}
		else if (
#if defined(PLATFORM_MD380) || defined(PLATFORM_MDUV380) || defined(PLATFORM_RT84_DM1701) || defined(PLATFORM_MD2017)
				KEYCHECK_SHORTUP(ev->keys, KEY_ROTARY_DECREMENT)
#if defined(PLATFORM_RT84_DM1701) || defined(PLATFORM_MD2017)
				|| KEYCHECK_SHORTUP(ev->keys, KEY_FRONT_DOWN)
#endif
#else
				(KEYCHECK_SHORTUP(ev->keys, KEY_DOWN) || KEYCHECK_LONGDOWN_REPEAT(ev->keys, KEY_DOWN))
#endif
		)
		{
			uiDataGlobal.talkaround = false;
			handleDownKey(ev);
			return;
		}
		else if (
#if defined(PLATFORM_MD380) || defined(PLATFORM_MDUV380) || defined(PLATFORM_RT84_DM1701) || defined(PLATFORM_MD2017)
				KEYCHECK_SHORTUP(ev->keys, KEY_ROTARY_INCREMENT)
#if defined(PLATFORM_RT84_DM1701) || defined(PLATFORM_MD2017)
				|| KEYCHECK_SHORTUP(ev->keys, KEY_FRONT_UP)
#endif
#else
				(KEYCHECK_SHORTUP(ev->keys, KEY_UP) || KEYCHECK_LONGDOWN_REPEAT(ev->keys, KEY_UP))
#endif
		)
		{
			uiDataGlobal.talkaround = false;
			handleUpKey(ev);
			return;
		}
#if defined(DUAL_CHANNEL_ENABLED)
		else if (KEYCHECK_LONGDOWN(ev->keys, KEY_FRONT_DOWN) && (KEYCHECK_LONGDOWN_REPEAT(ev->keys, KEY_FRONT_DOWN) == false) &&
				(BUTTONCHECK_DOWN(ev, BUTTON_SK2) == 0) && (BUTTONCHECK_DOWN(ev, BUTTON_SK1) == 0) && (directChannelNumber == 0))
		{
			// R97-FIX2: гаряча клавіша -- довге ▼ перемикає «Подвійний прийом» (та сама логіка, що пункт швидкого меню); коротке ▼ -- як було
			dualHotkeyToggle();
			return;
		}
#endif
		else if (KEYCHECK_LONGDOWN(ev->keys,
#if defined(PLATFORM_MD380) || defined(PLATFORM_MDUV380) || defined(PLATFORM_RT84_DM1701) || defined(PLATFORM_MD2017)
				KEY_FRONT_UP
#else
				KEY_UP
#endif
				) && (BUTTONCHECK_DOWN(ev, BUTTON_SK2) == 0))
		{
			if (uiDataGlobal.Scan.active == false)
			{
				scanStart(true);
#if defined(PLATFORM_MD380) || defined(PLATFORM_MDUV380) || defined(PLATFORM_RT84_DM1701) || defined(PLATFORM_MD2017)
				return;
#endif
			}
		}
		else if (KEYCHECK_LONGDOWN(ev->keys, KEY_0) && (KEYCHECK_LONGDOWN_REPEAT(ev->keys, KEY_0) == false))
		{
			char buf[SCREEN_LINE_BUFFER_SIZE];
			bool muted = audioAmpIsMuted();

			// Clear entered numbers
			if (directChannelNumber != 0)
			{
				directChannelNumber = 0;
				uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
				uiChannelModeUpdateScreen(0);
			}

			audioAmpMute(!muted);

			snprintf(buf, SCREEN_LINE_BUFFER_SIZE, "%s: %s", currentLanguage->mute, (muted ? currentLanguage->no : currentLanguage->yes));
			uiNotificationShowShort(1000U, buf, true);

			if (muted)
			{
				soundSetMelody(MELODY_KEY_BEEP_FIRST_ITEM);
				nextKeyBeepMelody = NULL;
				ev->keys.event &= ~(KEY_MOD_LONG | KEY_MOD_DOWN | KEY_MOD_PRESS | KEY_MOD_UP);
				ev->keys.key = 0;

				voicePromptsInit();
				voicePromptsAppendPrompt(PROMPT_SILENCE);
				voicePromptsAppendLanguageString(currentLanguage->mute);
				voicePromptsAppendPrompt(PROMPT_SILENCE);
				voicePromptsAppendLanguageString(currentLanguage->no);
				voicePromptsPlay();
			}
		}
		else if (KEYCHECK_LONGDOWN(ev->keys, KEY_8) && (KEYCHECK_LONGDOWN_REPEAT(ev->keys, KEY_8) == false))
		{
			// Clear entered numbers
			if (directChannelNumber != 0)
			{
				directChannelNumber = 0;
				uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
				uiChannelModeUpdateScreen(0);
			}

			if (currentChannelData->NOT_IN_CODEPLUG_CALCULATED_DISTANCE_X10 != -1)
			{
				uint32_t chanLat = ((currentChannelData->locationLat2 << 16) | (currentChannelData->locationLat1 << 8) | currentChannelData->locationLat0);
				uint32_t chanLon = ((currentChannelData->locationLon2 << 16) | (currentChannelData->locationLon1 << 8) | currentChannelData->locationLon0);
				double myLat = settingsLocationGetLatitude();
				double myLon = settingsLocationGetLongitude();
				double repLat = latLonFixed24ToDouble(chanLat);
				double repLon = latLonFixed24ToDouble(chanLon);
				double bearing = courseTo(myLat, myLon, repLat, repLon);
				uiNotificationBearingInfo_t bearingNotifData = { .bearing = bearing, .distanceX10 = currentChannelData->NOT_IN_CODEPLUG_CALCULATED_DISTANCE_X10 };

				uiNotificationBearingShow(&bearingNotifData, 2000U, true);
			}
		}
		else
		{
			int keyval = menuGetKeypadKeyValue(ev, true);

			if ((keyval < 10) && BUTTONCHECK_DOWN(ev, BUTTON_SK1) && (BUTTONCHECK_DOWN(ev, BUTTON_SK2) == false))
			{
				if (keyval == 1)
				{
					aprsBeaconingToggles();
				}
#if defined(APRS_RX)
				else if (keyval == 3)
				{
					aprsModeBeaconHotkey();   // R18 Д5: разовий маяк «Режиму APRS» (колишній пункт меню «Передати маяк»)
				}
#endif
				else if (keyval == 2)
				{
					switch (aprsBeaconingGetMode())
					{
						case APRS_BEACONING_MODE_MANUAL:
						case APRS_BEACONING_MODE_AUTO:
						case APRS_BEACONING_MODE_SMART_BEACONING:
							if (txInhibitCheckAndWarn() == false)
							{
								aprsBeaconingSendBeacon(false, true);
							}
							break;

						default: // Ignore other APRS modes.
							break;
					}
				}
			}
			else if ((keyval < 10) && (!BUTTONCHECK_DOWN(ev, BUTTON_SK2)))
			{
				directChannelNumber = (directChannelNumber * 10) + keyval;
				if (CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone))
				{
					// All Channels virtual zone
					if(directChannelNumber > CODEPLUG_CONTACTS_MAX)
					{
						directChannelNumber = 0;
						soundSetMelody(MELODY_ERROR_BEEP);
					}
				}
				else
				{
					if(directChannelNumber > currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone)
					{
						directChannelNumber = 0;
						soundSetMelody(MELODY_ERROR_BEEP);
					}
				}

				if (directChannelNumber > 0)
				{
					voicePromptsInit();
					if (directChannelNumber < 10)
					{
						voicePromptsAppendLanguageString(currentLanguage->gotoChannel);
					}
					voicePromptsAppendPrompt(PROMPT_0 + keyval);
					voicePromptsPlay();
				}
				else
				{
					announceItem(PROMPT_SEQUENCE_CHANNEL_NAME_OR_VFO_FREQ, PROMPT_THRESHOLD_3);
				}

				uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
				uiChannelModeUpdateScreen(0);
			}
		}
	}
#endif // ! PLATFORM_GD77S
}

#if ! defined(PLATFORM_GD77S)
/* R22 Z1.3: той самий предикат, що й у меню «Зони» (buildZoneMap) -- codeplugZoneIsUsable() у codeplug.c. */
static bool zoneStepUsable(int zoneNum, void *ctx)
{
	(void)ctx;
	return codeplugZoneIsUsable(zoneNum, NULL);
}

static void selectPrevNextZone(bool nextZone)
{
	// Пропускаємо все, що не є СПРАВЖНЬОЮ зоною: порожні (позначені "в роботі", але без каналів), "сміттєві"
	// (канали не існують) та зони з видаленим першим каналом. R22: раніше тут перевірялась лише кількість
	// каналів, тож валкодер зупинявся на сміттєвих зонах, яких немає в меню "Зони" (їхні "канали" -- байти
	// флешу, а це й давало HardFault R19/R21). Віртуальну "Всі канали" (остання зона) не пропускаємо ніколи;
	// цикл у codeplugZoneStep() обмежено кількістю зон -- захист від зациклення, якщо несправжні всі.
	settingsSet(nonVolatileSettings.currentZone,
			(int16_t) codeplugZoneStep(nonVolatileSettings.currentZone, codeplugZonesGetCount(), nextZone, zoneStepUsable, NULL));

	currentChannelData->rxFreq = 0U; // Flag to the Channel screen that the channel data is now invalid and needs to be reloaded
}

static void handleUpKey(uiEvent_t *ev)
{
	if (BUTTONCHECK_DOWN(ev, BUTTON_SK2))
	{
		selectPrevNextZone(true);
		menuSystemPopAllAndDisplaySpecificRootMenu(UI_CHANNEL_MODE, false);
		uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN; // Force screen redraw

		if (nonVolatileSettings.currentZone == 0)
		{
			menuChannelExitStatus |= (MENU_STATUS_LIST_TYPE | MENU_STATUS_FORCE_FIRST);
		}
		return;
	}
	else
	{
		int16_t nextChan = -1;

		if (uiDataGlobal.Scan.active)
		{
			// We are scanning downward
			if (uiDataGlobal.Scan.state == SCAN_STATE_PAUSED)
			{
				if (uiDataGlobal.Scan.direction == -1)
				{
					handleDownKey(ev);
					return;
				}

				// Let's select the next channel
			}
			else
			{
				// We're not paused, we shouldn't change the current channel
				return;
			}
		}

		if (CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone))
		{
			if (currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone > 1)
			{
				nextChan = codeplugGetLastUsedChannelInCurrentZone();

				// All Channels virtual zone
				do
				{
					nextChan = ((nextChan % currentZone.NOT_IN_CODEPLUGDATA_highestIndex) + 1);

				} while (!codeplugAllChannelsIndexIsInUse(nextChan));

				if (codeplugSetLastUsedChannelInZone(currentZone.NOT_IN_CODEPLUGDATA_indexNumber, nextChan) == CODEPLUG_CHANNELS_MIN)
				{
					menuChannelExitStatus |= (MENU_STATUS_LIST_TYPE | MENU_STATUS_FORCE_FIRST);
				}
			}
		}
		else
		{
			if (currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone > 1)
			{
				nextChan = ((codeplugGetLastUsedChannelInCurrentZone() + 1) % currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone);

				if (codeplugSetLastUsedChannelInZone(currentZone.NOT_IN_CODEPLUGDATA_indexNumber, nextChan) == 0)
				{
					menuChannelExitStatus |= (MENU_STATUS_LIST_TYPE | MENU_STATUS_FORCE_FIRST);
				}
			}
		}

		if (uiDataGlobal.Scan.active && (nextChan != -1))
		{
			scanNextChannelIndex = nextChan;
			scanNextChannelReady = true;
		}

		uiDataGlobal.Scan.timer.timeout = (uiDataGlobal.Scan.active ? 0 : 500); // when scanning is running, don't let it pick another channel
		uiDataGlobal.Scan.state = SCAN_STATE_SCANNING;
	}

	lastHeardClearLastID();
	uiChannelModeLoadChannelData(false, true);
	uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
	uiChannelModeUpdateScreen(0);
}

static void handleDownKey(uiEvent_t *ev)
{
	if (BUTTONCHECK_DOWN(ev, BUTTON_SK2))
	{
		selectPrevNextZone(false);
		menuSystemPopAllAndDisplaySpecificRootMenu(UI_CHANNEL_MODE, false);
		uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN; // Force screen redraw

		if (nonVolatileSettings.currentZone == 0)
		{
			menuChannelExitStatus |= (MENU_STATUS_LIST_TYPE | MENU_STATUS_FORCE_FIRST);
		}

		return;
	}
	else
	{
		int16_t prevChan = -1;

		if (uiDataGlobal.Scan.active)
		{
			// We are scanning downward
			if (uiDataGlobal.Scan.state == SCAN_STATE_PAUSED)
			{
				if (uiDataGlobal.Scan.direction == 1)
				{
					handleUpKey(ev);
					return;
				}

				// Let's select the previous channel
			}
			else
			{
				// We're not paused, we shouldn't change the current channel
				return;
			}
		}

		if (CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone))
		{
			if (currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone > 1)
			{
				prevChan = codeplugGetLastUsedChannelInCurrentZone();

				// All Channels virtual zone
				do
				{
					prevChan = ((((prevChan - 1) + currentZone.NOT_IN_CODEPLUGDATA_highestIndex - 1) % currentZone.NOT_IN_CODEPLUGDATA_highestIndex) + 1);

				} while (!codeplugAllChannelsIndexIsInUse(prevChan));

				if (codeplugSetLastUsedChannelInZone(currentZone.NOT_IN_CODEPLUGDATA_indexNumber, prevChan) == CODEPLUG_CHANNELS_MIN)
				{
					menuChannelExitStatus |= (MENU_STATUS_LIST_TYPE | MENU_STATUS_FORCE_FIRST);
				}
			}
		}
		else
		{
			if (currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone > 1)
			{
				prevChan = ((codeplugGetLastUsedChannelInCurrentZone() + currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone - 1) % currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone);

				if (codeplugSetLastUsedChannelInZone(currentZone.NOT_IN_CODEPLUGDATA_indexNumber, prevChan) == 0)
				{
					menuChannelExitStatus |= (MENU_STATUS_LIST_TYPE | MENU_STATUS_FORCE_FIRST);
				}
			}
		}

		if (uiDataGlobal.Scan.active && (prevChan != -1))
		{
			scanNextChannelIndex = prevChan;
			scanNextChannelReady = true;
		}

		uiDataGlobal.Scan.timer.timeout = (uiDataGlobal.Scan.active ? 0 : 500); // when scanning is running, don't let it pick another channel
		uiDataGlobal.Scan.state = SCAN_STATE_SCANNING;
	}

	lastHeardClearLastID();
	uiChannelModeLoadChannelData(false, true);
	uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
	uiChannelModeUpdateScreen(0);
}

#endif // ! PLATFORM_GD77S


// ---------------------------------------- Quick Menu functions -------------------------------------------------------------------
menuStatus_t uiChannelModeQuickMenu(uiEvent_t *ev, bool isFirstRun)
{
	if (isFirstRun)
	{
		if (quickmenuChannelFromVFOHandled)
		{
			quickmenuChannelFromVFOHandled = false;
			menuSystemPopAllAndDisplayRootMenu();
			return MENU_STATUS_SUCCESS;
		}

		uiChannelModeStopScanning();
		uiDataGlobal.QuickMenu.tmpDmrDestinationFilterLevel = nonVolatileSettings.dmrDestinationFilter;
		uiDataGlobal.QuickMenu.tmpDmrCcTsFilterLevel = nonVolatileSettings.dmrCcTsFilter;
		uiDataGlobal.QuickMenu.tmpAnalogFilterLevel = nonVolatileSettings.analogFilterLevel;
		uiDataGlobal.QuickMenu.tmpTalkaround = uiDataGlobal.talkaround;
		uiDataGlobal.QuickMenu.tmpRoaming = nonVolatileSettings.roaming;
		uiDataGlobal.QuickMenu.tmpAudioMute = audioAmpIsMuted();
#if defined(DUAL_CHANNEL_ENABLED)
		dcSetMenuValue(dcIsEnabled());   // R97: тимчасове значення пункту «Подв. прийом»
#endif

		menuDataGlobal.numItems = NUM_CH_SCREEN_QUICK_MENU_ITEMS;
#if defined(ROAMING_STOCK_HIDDEN)
		if (menuDataGlobal.currentItemIndex == CH_SCREEN_QUICK_MENU_ROAMING)   /* R74: на прихованому пункті стояти не можна */
		{
			menuDataGlobal.currentItemIndex = CH_SCREEN_QUICK_MENU_AUDIO_MUTE;
		}
#endif

		menuDataGlobal.menuOptionsSetQuickkey = 0;
		menuDataGlobal.menuOptionsTimeout = 0;
		menuDataGlobal.newOptionSelected = true;

		voicePromptsInit();
		voicePromptsAppendPrompt(PROMPT_SILENCE);
		voicePromptsAppendPrompt(PROMPT_SILENCE);
		voicePromptsAppendLanguageString(currentLanguage->quick_menu);
		voicePromptsAppendPrompt(PROMPT_SILENCE);
		voicePromptsAppendPrompt(PROMPT_SILENCE);

		updateQuickMenuScreen(true);
		return (MENU_STATUS_LIST_TYPE | MENU_STATUS_SUCCESS);
	}
	else
	{
		menuQuickChannelExitStatus = MENU_STATUS_SUCCESS;

		if ((ev->hasEvent) || (menuDataGlobal.menuOptionsTimeout > 0))
		{
			handleQuickMenuEvent(ev);
		}
	}

	return menuQuickChannelExitStatus;
}

static bool validateOverwriteChannel(void)
{
	quickmenuChannelFromVFOHandled = true;

	if (uiDataGlobal.MessageBox.keyPressed == KEY_GREEN)
	{
		CodeplugContact_t vfoContact;
		int8_t vfoTS = -1;

		uiVFOLoadContact(&vfoContact);
		memcpy(&currentChannelData->rxFreq, &settingsVFOChannel[nonVolatileSettings.currentVFONumber].rxFreq, CODEPLUG_CHANNEL_DATA_STRUCT_SIZE - 16);// Don't copy the name of the vfo, which are in the first 16 bytes
		// Find out which TS was in use.
		if ((nonVolatileSettings.overrideTG == 0) && (vfoContact.reserve1 & CODEPLUG_CONTACT_FLAG_NO_TS_OVERRIDE) == 0x00)
		{
			vfoTS = ((vfoContact.reserve1 & CODEPLUG_CONTACT_FLAG_TS_OVERRIDE_TIMESLOT_MASK) != 0);
		}
		else
		{
			vfoTS = tsGetManualOverride((Channel_t)nonVolatileSettings.currentVFONumber);

			// No Override, use the TS from the Channel
			if (vfoTS == 0)
			{
				vfoTS = ((codeplugChannelGetFlag(&settingsVFOChannel[nonVolatileSettings.currentVFONumber], CHANNEL_FLAG_TIMESLOT_TWO) != 0) ? 1 : 0);
			}
			else
			{
				vfoTS--; // convert to real TS
			}
		}

		codeplugChannelSetFlag(currentChannelData, CHANNEL_FLAG_TIMESLOT_TWO, ((vfoTS == 0) ? 0 : 1));
		codeplugChannelSaveDataForIndex(uiDataGlobal.currentSelectedChannelNumber, currentChannelData);
	}

	return true;
}

#if defined(CHANNEL_DELETE_ENABLED)
/* R41 (R44: винесено окремою функцією, ТЕКСТ ТОЙ САМИЙ): видаляє канал channelNumber і приводить екран каналу до ладу. Викликається і з колбека швидкого меню (R41, видаляє
 * ПОТОЧНИЙ канал), і з пункту головного меню «Канали» (R44/R46, довільний канал). Повертає true, якщо канал видалено. */
bool uiChannelModeDeleteChannel(int channelNumber)
{
	if (codeplugChannelDelete(channelNumber) == CODEPLUG_CHANNEL_DELETE_OK)
	{
		// Зона, з якої видалили канал, могла спорожніти (тоді вона стала «непридатною»): переходимо на «Всі канали», на їхній перший канал.
		// Якщо зона жива, LUCZ уже вказує на наступний канал (codeplugChannelDelete поправив позицію).
		if (!codeplugZoneIsUsable(nonVolatileSettings.currentZone, NULL))
		{
			codeplugSetLastUsedChannelInZone(-1, (int16_t)codeplugChannelNextInUse(0));
			codeplugSaveLastUsedChannelInZone();
		}

		uiChannelModeColdStart();   // примусове перечитування зони й каналу при поверненні на екран каналу
		uiNotificationShowShort(1500U, currentLanguage->channel_deleted, false);
		return true;
	}

	uiNotificationShowShort(1500U, currentLanguage->error, false);
	return false;
}
#endif // CHANNEL_DELETE_ENABLED

#if defined(CH_QUICKMENU_DELETE_ENABLED)
/* R41: колбек MessageBox «Видалити?» (ТАК/НІ). Викликається і на ТАК, і на НІ: як і в validateOverwriteChannel, прапорець змушує швидке меню при
 * поверненні закритися й показати корінь (екран каналу), тож і підтвердження, і скасування приводять на екран каналу. Видаляємо ПОТОЧНИЙ канал екрана. */
static bool validateDeleteChannel(void)
{
	quickmenuChannelFromVFOHandled = true;

	if (uiDataGlobal.MessageBox.keyPressed == KEY_GREEN)
	{
		uiChannelModeDeleteChannel(uiDataGlobal.currentSelectedChannelNumber);
	}

	return true;
}
#endif // CH_QUICKMENU_DELETE_ENABLED

#if defined(ZONE_EDIT_ENABLED)
/* R43 (R44: винесено окремою функцією, ТЕКСТ ТОЙ САМИЙ, крім умови zn == поточна зона): виймає з зони zn запис на позиції pos. Сам канал не видаляється: лишається у «Всіх каналах» і в
 * інших зонах. Викликається і з колбека швидкого меню (R43, ПОТОЧНА зона й позиція «останнього каналу в зоні»), і з пункту «Зона» -> дії -> Канали зони (R44/R46, довільна зона й позиція). */
bool uiChannelModeZoneRemoveChannelAt(int zn, int pos)
{
	if (codeplugZoneRemoveChannelAt(zn, pos) == CODEPLUG_ZONE_EDIT_OK)
	{
		// Зона спорожніла -> «непридатна»: якщо це ПОТОЧНА зона -- переходимо на «Всі канали». Інакше LUCZ уже вказує на наступний канал зони (з останнього -- на перший).
		if (!codeplugZoneIsUsable(zn, NULL) && (zn == nonVolatileSettings.currentZone))
		{
			settingsSet(nonVolatileSettings.currentZone, (int16_t)(codeplugZonesGetCount() - 1));
		}

		uiChannelModeColdStart();   // примусове перечитування зони й каналу при поверненні на екран каналу
		uiNotificationShowShort(1500U, currentLanguage->zone_ch_removed, false);
		return true;
	}

	uiNotificationShowShort(1500U, currentLanguage->error, false);
	return false;
}
#endif // ZONE_EDIT_ENABLED

#if defined(CH_QUICKMENU_ZONE_REMOVE_ENABLED)
/* R43: колбек MessageBox «Вийняти?» (ТАК/НІ): виймає ПОТОЧНИЙ канал екрана з ПОТОЧНОЇ зони (запис списку на позиції «останнього каналу в зоні»). Сам канал не видаляється:
 * лишається в «Всіх каналах» і в інших зонах. Як і validateDeleteChannel, і на ТАК, і на НІ закриває швидке меню й показує екран каналу. */
static bool validateZoneRemoveChannel(void)
{
	quickmenuChannelFromVFOHandled = true;

	if (uiDataGlobal.MessageBox.keyPressed == KEY_GREEN)
	{
		uiChannelModeZoneRemoveChannelAt(nonVolatileSettings.currentZone, codeplugGetLastUsedChannelInCurrentZone());
	}

	return true;
}
#endif // CH_QUICKMENU_ZONE_REMOVE_ENABLED

#if defined(ROAMING_STOCK_HIDDEN)
/* R74: номер пункту швидкого меню, що стоїть на `loopOffset` рядків від поточного, ПРОПУСКАЮЧИ прихований стоковий «Roaming». Нумерація (enum) не змінюється --
 * швидкі клавіші зберігають саме номер пункту (QUICKKEY_ENTRYID, див. обробник нижче), тож пункти після колишнього «Roaming» викликаються як і раніше. */
static int quickMenuVisibleItem(int loopOffset)
{
	int idx = menuDataGlobal.currentItemIndex;
	int steps = (loopOffset < 0) ? -loopOffset : loopOffset;
	int dir = (loopOffset < 0) ? (NUM_CH_SCREEN_QUICK_MENU_ITEMS - 1) : 1;

	while (steps-- > 0)
	{
		do
		{
			idx = (idx + dir) % NUM_CH_SCREEN_QUICK_MENU_ITEMS;
		} while (idx == CH_SCREEN_QUICK_MENU_ROAMING);
	}
	return idx;
}
#endif

static void updateQuickMenuScreen(bool isFirstRun)
{
	int mNum = 0;
	char buf[SCREEN_LINE_BUFFER_SIZE];
	const char *leftSide;// initialise to please the compiler
	const char *rightSideConst;// initialise to please the compiler
	char rightSideVar[SCREEN_LINE_BUFFER_SIZE];


	displayClearBuf();
	bool settingOption = uiQuickKeysShowChoices(buf, SCREEN_LINE_BUFFER_SIZE, currentLanguage->quick_menu);

	for (int i = MENU_START_ITERATION_VALUE; i <= MENU_END_ITERATION_VALUE; i++)
	{
		if ((settingOption == false) || (i == 0))
		{
			mNum = menuGetMenuOffset(NUM_CH_SCREEN_QUICK_MENU_ITEMS, i);
#if defined(ROAMING_STOCK_HIDDEN)
			if (mNum >= 0)
			{
				mNum = quickMenuVisibleItem(i);   /* R74: сусідні рядки списку теж пропускають прихований пункт */
			}
#endif
			if (mNum == MENU_OFFSET_BEFORE_FIRST_ENTRY)
			{
				continue;
			}
			else if (mNum == MENU_OFFSET_AFTER_LAST_ENTRY)
			{
				break;
			}

			buf[0] = 0;
			rightSideVar[0] = 0;
			rightSideConst = NULL;
			leftSide = NULL;

			switch(mNum)
			{
				case CH_SCREEN_QUICK_MENU_COPY2VFO:
					rightSideConst = currentLanguage->channelToVfo;
					break;
				case CH_SCREEN_QUICK_MENU_COPY_FROM_VFO:
					rightSideConst = currentLanguage->vfoToChannel;
					break;
				case CH_SCREEN_QUICK_MENU_FILTER_FM:
					leftSide = currentLanguage->filter;
					if (uiDataGlobal.QuickMenu.tmpAnalogFilterLevel == 0)
					{
						rightSideConst = currentLanguage->none;
					}
					else
					{
						snprintf(rightSideVar, SCREEN_LINE_BUFFER_SIZE, "%s", ANALOG_FILTER_LEVELS[uiDataGlobal.QuickMenu.tmpAnalogFilterLevel - 1]);
					}
					break;
				case CH_SCREEN_QUICK_MENU_FILTER_DMR:
					leftSide = currentLanguage->dmr_filter;
					if (uiDataGlobal.QuickMenu.tmpDmrDestinationFilterLevel == 0)
					{
						rightSideConst = currentLanguage->none;
					}
					else
					{
						snprintf(rightSideVar, SCREEN_LINE_BUFFER_SIZE, "%s", DMR_DESTINATION_FILTER_LEVELS[uiDataGlobal.QuickMenu.tmpDmrDestinationFilterLevel - 1]);
					}
					break;
				case CH_SCREEN_QUICK_MENU_DMR_CC_SCAN:
					leftSide = currentLanguage->dmr_cc_scan;
					rightSideConst = (uiDataGlobal.QuickMenu.tmpDmrCcTsFilterLevel & DMR_CC_FILTER_PATTERN) ? currentLanguage->off : currentLanguage->on;
					break;
				case CH_SCREEN_QUICK_MENU_FILTER_DMR_TS:
					leftSide = currentLanguage->dmr_ts_filter;
					rightSideConst = (uiDataGlobal.QuickMenu.tmpDmrCcTsFilterLevel & DMR_TS_FILTER_PATTERN) ? currentLanguage->on : currentLanguage->off;
					break;
				case CH_SCREEN_QUICK_MENU_TALKAROUND:
#if defined(LANGUAGE_BUILD_UKRAINIAN)
					leftSide = currentLanguage->talkaround_menu;   // R94: «Без репітера» (спільне talkaround -- голосова підказка -- не чіпаємо)
#else
					leftSide = currentLanguage->talkaround;
#endif
					rightSideConst = ((currentChannelData->txFreq != currentChannelData->rxFreq) ? (uiDataGlobal.QuickMenu.tmpTalkaround ? currentLanguage->on : currentLanguage->off) : currentLanguage->n_a);
					break;
				case CH_SCREEN_QUICK_MENU_ROAMING:
					leftSide = currentLanguage->roaming;
					{
						if (CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone))
						{
							rightSideConst = currentLanguage->n_a;
						}
						else
						{
							switch (uiDataGlobal.QuickMenu.tmpRoaming)
							{
								case ROAMING_OFF:
									rightSideConst = currentLanguage->off;
									break;
								case ROAMING_MANUAL:
									rightSideConst = currentLanguage->manual;
									break;
								default:
									snprintf(rightSideVar, SCREEN_LINE_BUFFER_SIZE, "%ukm", ROAMING_DISTANCE_KM_ARRAY[uiDataGlobal.QuickMenu.tmpRoaming - ROAMING_5KM]);
									break;
							}
						}

					}
					break;
				case CH_SCREEN_QUICK_MENU_AUDIO_MUTE:
					leftSide = currentLanguage->mute;
					rightSideConst = (uiDataGlobal.QuickMenu.tmpAudioMute ? currentLanguage->yes : currentLanguage->no);
					break;
#if defined(CH_QUICKMENU_DELETE_ENABLED)
				case CH_SCREEN_QUICK_MENU_DELETE:
					rightSideConst = currentLanguage->delete_channel;
					break;
#endif
#if defined(CH_QUICKMENU_ZONE_REMOVE_ENABLED)
				case CH_SCREEN_QUICK_MENU_ZONE_REMOVE:
					rightSideConst = currentLanguage->zone_ch_remove;
					break;
#endif
#if defined(DUAL_CHANNEL_ENABLED)
				case CH_SCREEN_QUICK_MENU_DUAL_CHANNEL:   // R97
					leftSide = currentLanguage->dual_rx;
					rightSideConst = (dcMenuValue() ? currentLanguage->on : currentLanguage->off);
					break;
#endif
				default:
					buf[0] = 0;
			}

			if (leftSide != NULL)
			{
				snprintf(buf, SCREEN_LINE_BUFFER_SIZE, "%s:%s", leftSide, (rightSideVar[0] ? rightSideVar : rightSideConst));
			}
			else
			{
				snprintf(buf, SCREEN_LINE_BUFFER_SIZE, "%s", (rightSideVar[0] ? rightSideVar : rightSideConst));
			}

			if (i == 0)
			{
				if (!isFirstRun && (menuDataGlobal.menuOptionsSetQuickkey == 0))
				{
					voicePromptsInit();
				}

				if ((leftSide != NULL) || menuDataGlobal.newOptionSelected)
				{
					voicePromptsAppendLanguageString(leftSide);
				}

				if (rightSideVar[0] != 0)
				{
					if (mNum == CH_SCREEN_QUICK_MENU_ROAMING)
					{
						char numBuf[8];
						snprintf(numBuf, 8, "%u", ROAMING_DISTANCE_KM_ARRAY[uiDataGlobal.QuickMenu.tmpRoaming - ROAMING_5KM]);
						voicePromptsAppendString(numBuf);
						voicePromptsAppendPrompt(PROMPT_KILOMETERS);
					}
					else
					{
						voicePromptsAppendString(rightSideVar);
					}
				}
				else
				{
					voicePromptsAppendLanguageString(rightSideConst);
				}

				if (menuDataGlobal.menuOptionsTimeout != -1)
				{
					promptsPlayNotAfterTx();
				}
				else
				{
					menuDataGlobal.menuOptionsTimeout = 0;// clear flag indicating that a QuickKey has just been set
				}
			}

			// QuickKeys
			if (menuDataGlobal.menuOptionsTimeout > 0)
			{
				menuDisplaySettingOption(leftSide, (rightSideVar[0] ? rightSideVar : rightSideConst));
			}
			else
			{
				switch (mNum)
				{
					case CH_SCREEN_QUICK_MENU_FILTER_FM:
					case CH_SCREEN_QUICK_MENU_FILTER_DMR:
					case CH_SCREEN_QUICK_MENU_DMR_CC_SCAN:
					case CH_SCREEN_QUICK_MENU_FILTER_DMR_TS:
					case CH_SCREEN_QUICK_MENU_TALKAROUND:
					case CH_SCREEN_QUICK_MENU_ROAMING:
					case CH_SCREEN_QUICK_MENU_AUDIO_MUTE:
#if defined(DUAL_CHANNEL_ENABLED)
					case CH_SCREEN_QUICK_MENU_DUAL_CHANNEL:   // R97: значення On/Off -- кольором значення
#endif
						menuDisplayEntry(i, mNum, buf, (strlen(leftSide) + 1), THEME_ITEM_FG_MENU_ITEM, THEME_ITEM_FG_OPTIONS_VALUE, THEME_ITEM_BG);
						break;

					default:
						menuDisplayEntry(i, mNum, buf, 0, THEME_ITEM_FG_MENU_ITEM, THEME_ITEM_COLOUR_NONE, THEME_ITEM_BG);
						break;
				}
			}
		}
	}

	displayRender();
}

static void handleQuickMenuEvent(uiEvent_t *ev)
{
	bool isDirty = false;
	bool executingQuickKey = false;

	if ((menuDataGlobal.menuOptionsTimeout > 0) && (!BUTTONCHECK_DOWN(ev, BUTTON_SK2)))
	{
		menuDataGlobal.menuOptionsTimeout--;
		if (menuDataGlobal.menuOptionsTimeout == 0)
		{
			// Let the QuickKey's VP playback to ends before
			// going back to the previous menu
			if (voicePromptsIsPlaying())
			{
				menuDataGlobal.menuOptionsTimeout++;
				return;
			}

			menuSystemPopPreviousMenu();
			return;
		}
	}

	if (ev->events & BUTTON_EVENT)
	{
		if (repeatVoicePromptOnSK1(ev))
		{
			return;
		}
	}

	if (ev->events & FUNCTION_EVENT)
	{
		isDirty = true;
		if (ev->function == FUNC_REDRAW)
		{
			updateQuickMenuScreen(false);
			return;
		}
#if defined(ROAMING_STOCK_HIDDEN)
		else if ((QUICKKEY_TYPE(ev->function) == QUICKKEY_MENU) && (QUICKKEY_ENTRYID(ev->function) == CH_SCREEN_QUICK_MENU_ROAMING))
		{
			// R74: клавіша, колись призначена на прихований стоковий «Roaming», нічого не робить (пункту нема, значення не змінюємо)
			return;
		}
#endif
#if defined(CH_QUICKMENU_DELETE_ENABLED)
		else if ((QUICKKEY_TYPE(ev->function) == QUICKKEY_MENU) && (QUICKKEY_ENTRYID(ev->function) == CH_SCREEN_QUICK_MENU_DELETE))
		{
			// R41: видалення каналу НІКОЛИ не виконується швидкою клавішею (одна випадкова цифра не повинна стирати канал)
			return;
		}
#endif
#if defined(CH_QUICKMENU_ZONE_REMOVE_ENABLED)
		else if ((QUICKKEY_TYPE(ev->function) == QUICKKEY_MENU) && (QUICKKEY_ENTRYID(ev->function) == CH_SCREEN_QUICK_MENU_ZONE_REMOVE))
		{
			// R43: виймання з зони теж НІКОЛИ не виконується швидкою клавішею
			return;
		}
#endif
		else if ((QUICKKEY_TYPE(ev->function) == QUICKKEY_MENU) && (QUICKKEY_ENTRYID(ev->function) < NUM_CH_SCREEN_QUICK_MENU_ITEMS))
		{
			menuDataGlobal.currentItemIndex = QUICKKEY_ENTRYID(ev->function);
		}

		if ((QUICKKEY_FUNCTIONID(ev->function) != 0))
		{
			menuDataGlobal.menuOptionsTimeout = 1000;
			executingQuickKey = true;
		}
	}

	if ((ev->events & KEY_EVENT) && (menuDataGlobal.menuOptionsSetQuickkey == 0) && (menuDataGlobal.menuOptionsTimeout == 0))
	{
		if (KEYCHECK_PRESS(ev->keys, KEY_DOWN) && (menuDataGlobal.numItems != 0))
		{
			isDirty = true;
			menuSystemMenuIncrement(&menuDataGlobal.currentItemIndex, NUM_CH_SCREEN_QUICK_MENU_ITEMS);
#if defined(ROAMING_STOCK_HIDDEN)
			if (menuDataGlobal.currentItemIndex == CH_SCREEN_QUICK_MENU_ROAMING)   /* R74: прихований пункт перестрибуємо, нумерація не змінюється */
			{
				menuSystemMenuIncrement(&menuDataGlobal.currentItemIndex, NUM_CH_SCREEN_QUICK_MENU_ITEMS);
			}
#endif
			menuDataGlobal.newOptionSelected = true;
			menuQuickChannelExitStatus |= MENU_STATUS_LIST_TYPE;
		}
		else if (KEYCHECK_PRESS(ev->keys, KEY_UP))
		{
			isDirty = true;
			menuSystemMenuDecrement(&menuDataGlobal.currentItemIndex, NUM_CH_SCREEN_QUICK_MENU_ITEMS);
#if defined(ROAMING_STOCK_HIDDEN)
			if (menuDataGlobal.currentItemIndex == CH_SCREEN_QUICK_MENU_ROAMING)
			{
				menuSystemMenuDecrement(&menuDataGlobal.currentItemIndex, NUM_CH_SCREEN_QUICK_MENU_ITEMS);
			}
#endif
			menuDataGlobal.newOptionSelected = true;
			menuQuickChannelExitStatus |= MENU_STATUS_LIST_TYPE;
		}
		else if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
		{
			quickKeyApply: // branching here when to quickkey was used.

#if defined(DUAL_CHANNEL_ENABLED)
			if (dualOnVfoNow())
			{
				// R98 В6: обраний -- VFO (картка B; R98-FIX4 Б3 -- або A). Пункти, що мають сенс лише для каналу кодплага, не виконуємо: сигнал помилки, меню лишається,
				// стан (канал/VFO/зона/B) не змінюється.
				switch (menuDataGlobal.currentItemIndex)
				{
					case CH_SCREEN_QUICK_MENU_COPY2VFO:
					case CH_SCREEN_QUICK_MENU_COPY_FROM_VFO:
					case CH_SCREEN_QUICK_MENU_TALKAROUND:
					case CH_SCREEN_QUICK_MENU_ROAMING:   // R98-FIX1 Г: його застосування ставить currentChannelData->rxFreq = 0 («перечитати зону») -- на VFO стерло б частоту VFO
#if defined(CH_QUICKMENU_DELETE_ENABLED)
					case CH_SCREEN_QUICK_MENU_DELETE:
#endif
#if defined(CH_QUICKMENU_ZONE_REMOVE_ENABLED)
					case CH_SCREEN_QUICK_MENU_ZONE_REMOVE:
#endif
						soundSetMelody(MELODY_ERROR_BEEP);
						return;

					default:
						break;
				}
			}
#endif

			switch(menuDataGlobal.currentItemIndex)
			{
				case CH_SCREEN_QUICK_MENU_COPY2VFO:
				{
					int8_t currentTS = trxGetDMRTimeSlot();

					memcpy(&settingsVFOChannel[nonVolatileSettings.currentVFONumber].rxFreq, &currentChannelData->rxFreq, CODEPLUG_CHANNEL_DATA_STRUCT_SIZE - 16);// Don't copy the name of channel, which are in the first 16 bytes
					settingsVFOChannel[nonVolatileSettings.currentVFONumber].rxTone = currentChannelData->rxTone;
					settingsVFOChannel[nonVolatileSettings.currentVFONumber].txTone = currentChannelData->txTone;

					if (nonVolatileSettings.overrideTG == 0)
					{
						nonVolatileSettings.overrideTG = trxTalkGroupOrPcId;
					}

					// Set TS override
					tsSetManualOverride(((Channel_t)nonVolatileSettings.currentVFONumber), currentTS + 1);

					codeplugChannelSetFlag(&settingsVFOChannel[nonVolatileSettings.currentVFONumber], CHANNEL_FLAG_TIMESLOT_TWO, ((currentTS == 0) ? 0 : 1));

					menuSystemPopAllAndDisplaySpecificRootMenu(UI_VFO_MODE, true);
					return;
				}
				break;

				case CH_SCREEN_QUICK_MENU_COPY_FROM_VFO:
				{
					bool displayMessageBox = false;
					const char *vp1 = NULL;
					const char *vp2 = NULL;

					if (settingsIsOptionBitSet(BIT_CHANNELS_ARE_READ_ONLY) == false)
					{
						if (quickmenuChannelFromVFOHandled == false)
						{
							displayMessageBox = true;
							vp1 = currentLanguage->overwrite_qm;
							vp2 = currentLanguage->please_confirm;
							uiDataGlobal.MessageBox.buttons = MESSAGEBOX_BUTTONS_YESNO;
							uiDataGlobal.MessageBox.validatorCallback = validateOverwriteChannel;
						}
					}
					else
					{
						displayMessageBox = true;
						vp1 = currentLanguage->aprs_channel;
						vp2 = currentLanguage->locked;
						uiDataGlobal.MessageBox.buttons =
#if defined(PLATFORM_MD9600)
								MESSAGEBOX_BUTTONS_ENT;
#else
								MESSAGEBOX_BUTTONS_OK;
#endif
						uiDataGlobal.MessageBox.validatorCallback = NULL;

					}

					if (displayMessageBox)
					{
						snprintf(uiDataGlobal.MessageBox.message, MESSAGEBOX_MESSAGE_LEN_MAX, "%s\n%s", vp1, vp2);
						uiDataGlobal.MessageBox.type = MESSAGEBOX_TYPE_INFO;
						uiDataGlobal.MessageBox.decoration = MESSAGEBOX_DECORATION_FRAME;

						menuSystemPushNewMenu(UI_MESSAGE_BOX);

						voicePromptsInit();
						voicePromptsAppendLanguageString(vp1);
						voicePromptsAppendLanguageString(vp2);
						voicePromptsPlay();
					}

					return;
				}
					break;

#if defined(CH_QUICKMENU_DELETE_ENABLED)
				case CH_SCREEN_QUICK_MENU_DELETE:
				{
					const char *vp1;
					const char *vp2;
					char chName[17];   // має жити до кінця case: на нього вказує vp2 для голосових підказок

					if (!codeplugAllChannelsIndexIsInUse(uiDataGlobal.currentSelectedChannelNumber))
					{
						// На екрані не справжній канал (порожня зона, особливий режим): видаляти нічого -- просто виходимо зі швидкого меню
						menuSystemPopPreviousMenu();
						return;
					}

					if (settingsIsOptionBitSet(BIT_CHANNELS_ARE_READ_ONLY))
					{
						// «Канали лише для читання» (Загальні -> Блокування): так само, як для копіювання з VFO
						vp1 = currentLanguage->aprs_channel;
						vp2 = currentLanguage->locked;
						uiDataGlobal.MessageBox.buttons = MESSAGEBOX_BUTTONS_OK;
						uiDataGlobal.MessageBox.validatorCallback = NULL;
						snprintf(uiDataGlobal.MessageBox.message, MESSAGEBOX_MESSAGE_LEN_MAX, "%s\n%s", vp1, vp2);
					}
					else if (codeplugChannelCountInUse() <= 1)
					{
						// Єдиний канал у кодплазі: рація без жодного каналу не має що показувати -- не видаляємо, пояснюємо
						vp1 = currentLanguage->last_channel;
						vp2 = currentLanguage->cannot_delete;
						uiDataGlobal.MessageBox.buttons = MESSAGEBOX_BUTTONS_OK;
						uiDataGlobal.MessageBox.validatorCallback = NULL;
						snprintf(uiDataGlobal.MessageBox.message, MESSAGEBOX_MESSAGE_LEN_MAX, "%s\n%s", vp1, vp2);
					}
					else
					{
						// Екран підтвердження: «Видалити?» / назва каналу / «У зонах: N». Лише номер каналу й число зон -- без вигадок.
						char zonesLine[SCREEN_LINE_BUFFER_SIZE];

						codeplugUtilConvertBufToString(currentChannelData->name, chName, 16);
						snprintf(zonesLine, SCREEN_LINE_BUFFER_SIZE, "%s %d", currentLanguage->in_zones, codeplugChannelCountZones(uiDataGlobal.currentSelectedChannelNumber));
						vp1 = currentLanguage->delete_channel_qm;
						vp2 = NULL;   // назву каналу озвучуємо як звичайний рядок (вона не з мовної таблиці)
						uiDataGlobal.MessageBox.buttons = MESSAGEBOX_BUTTONS_YESNO;
						uiDataGlobal.MessageBox.validatorCallback = validateDeleteChannel;
						snprintf(uiDataGlobal.MessageBox.message, MESSAGEBOX_MESSAGE_LEN_MAX, "%s\n%s\n%s", vp1, chName, zonesLine);
					}

					uiDataGlobal.MessageBox.type = MESSAGEBOX_TYPE_INFO;
					uiDataGlobal.MessageBox.decoration = MESSAGEBOX_DECORATION_FRAME;
					menuSystemPushNewMenu(UI_MESSAGE_BOX);

					voicePromptsInit();
					voicePromptsAppendLanguageString(vp1);
					if (vp2 != NULL)
					{
						voicePromptsAppendLanguageString(vp2);
					}
					else
					{
						voicePromptsAppendString(chName);
					}
					voicePromptsPlay();

					return;
				}
					break;
#endif

#if defined(DUAL_CHANNEL_ENABLED)
				case CH_SCREEN_QUICK_MENU_DUAL_CHANNEL:   // R97: увімкнути/вимкнути режим (R98-FIX1: «Встановити як B» прибрано -- B вибирається ручкою на картці B)
				{
					menuDataGlobal.menuOptionsTimeout = 0;
					menuSystemPopPreviousMenu();
					dualQuickMenuApply();   // після повернення на екран каналу: сповіщення не перекриє меню
					return;
				}
#endif

#if defined(CH_QUICKMENU_ZONE_REMOVE_ENABLED)
				case CH_SCREEN_QUICK_MENU_ZONE_REMOVE:
				{
					const char *vp1;
					const char *vp2;
					char chName[17];   // мають жити до кінця case: на них вказують vp-рядки для голосових підказок
					char zName[17];
					int pos = codeplugGetLastUsedChannelInCurrentZone();

					if (CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone))
					{
						// «Всі канали» -- віртуальна зона: з неї нічого виймати, канал видаляє «Видалити канал»
						vp1 = currentLanguage->all_channels;
						vp2 = currentLanguage->zone_not_zone;
						uiDataGlobal.MessageBox.buttons = MESSAGEBOX_BUTTONS_OK;
						uiDataGlobal.MessageBox.validatorCallback = NULL;
						snprintf(uiDataGlobal.MessageBox.message, MESSAGEBOX_MESSAGE_LEN_MAX, "%s\n%s", vp1, vp2);
					}
					else if ((pos < 0) || (pos >= currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone) ||
							(currentZone.channels[pos] != (uint16_t)uiDataGlobal.currentSelectedChannelNumber))
					{
						// На екрані не той канал, що в списку зони (порожня зона, особливий режим): виймати нічого -- просто виходимо зі швидкого меню
						menuSystemPopPreviousMenu();
						return;
					}
					else if (settingsIsOptionBitSet(BIT_CHANNELS_ARE_READ_ONLY))
					{
						vp1 = currentLanguage->aprs_channel;
						vp2 = currentLanguage->locked;
						uiDataGlobal.MessageBox.buttons = MESSAGEBOX_BUTTONS_OK;
						uiDataGlobal.MessageBox.validatorCallback = NULL;
						snprintf(uiDataGlobal.MessageBox.message, MESSAGEBOX_MESSAGE_LEN_MAX, "%s\n%s", vp1, vp2);
					}
					else
					{
						// Екран підтвердження: «Вийняти?» / назва каналу / назва зони / «Канал лишиться» -- щоб було видно, що канал НЕ видаляється
						codeplugUtilConvertBufToString(currentChannelData->name, chName, 16);
						snprintf(zName, sizeof(zName), "%s", currentZoneName);
						vp1 = currentLanguage->zone_remove_qm;
						vp2 = currentLanguage->zone_chan_stays;
						uiDataGlobal.MessageBox.buttons = MESSAGEBOX_BUTTONS_YESNO;
						uiDataGlobal.MessageBox.validatorCallback = validateZoneRemoveChannel;
						snprintf(uiDataGlobal.MessageBox.message, MESSAGEBOX_MESSAGE_LEN_MAX, "%s\n%.14s\n%.14s\n%s", vp1, chName, zName, vp2);
					}

					uiDataGlobal.MessageBox.type = MESSAGEBOX_TYPE_INFO;
					uiDataGlobal.MessageBox.decoration = MESSAGEBOX_DECORATION_FRAME;
					menuSystemPushNewMenu(UI_MESSAGE_BOX);

					voicePromptsInit();
					voicePromptsAppendLanguageString(vp1);
					voicePromptsAppendLanguageString(vp2);
					voicePromptsPlay();

					return;
				}
					break;
#endif

				default:
					// CH_SCREEN_QUICK_MENU_FILTER_FM
					if (nonVolatileSettings.analogFilterLevel != uiDataGlobal.QuickMenu.tmpAnalogFilterLevel)
					{
						settingsSet(nonVolatileSettings.analogFilterLevel, uiDataGlobal.QuickMenu.tmpAnalogFilterLevel);
						trxSetAnalogFilterLevel(nonVolatileSettings.analogFilterLevel);
					}

					// CH_SCREEN_QUICK_MENU_FILTER_DMR
					if (nonVolatileSettings.dmrDestinationFilter != uiDataGlobal.QuickMenu.tmpDmrDestinationFilterLevel)
					{
						settingsSet(nonVolatileSettings.dmrDestinationFilter, uiDataGlobal.QuickMenu.tmpDmrDestinationFilterLevel);
						if (trxGetMode() == RADIO_MODE_DIGITAL)
						{
							HRC6000InitDigitalDmrRx();
							audioAmpDisable(AUDIO_AMP_CHANNEL_RF);
						}
					}

					// CH_SCREEN_QUICK_MENU_FILTER_DMR_CC
					// CH_SCREEN_QUICK_MENU_FILTER_DMR_TS
					if (nonVolatileSettings.dmrCcTsFilter != uiDataGlobal.QuickMenu.tmpDmrCcTsFilterLevel)
					{
						settingsSet(nonVolatileSettings.dmrCcTsFilter, uiDataGlobal.QuickMenu.tmpDmrCcTsFilterLevel);
						if (trxGetMode() == RADIO_MODE_DIGITAL)
						{
							HRC6000InitDigitalDmrRx();
							HRC6000ResyncTimeSlot();
							audioAmpDisable(AUDIO_AMP_CHANNEL_RF);
						}
					}

					// CH_SCREEN_QUICK_MENU_TALKAROUND
					if ((currentChannelData->txFreq != currentChannelData->rxFreq) && (uiDataGlobal.talkaround != uiDataGlobal.QuickMenu.tmpTalkaround))
					{
						uiDataGlobal.talkaround = uiDataGlobal.QuickMenu.tmpTalkaround;

						// Talkaround and reverseRepeater are mutually exclusive.
						if (uiDataGlobal.reverseRepeaterChannel && uiDataGlobal.talkaround)
						{
							uiDataGlobal.reverseRepeaterChannel = false;
						}
					}

					// CH_SCREEN_QUICK_MENU_ROAMING
					if (nonVolatileSettings.roaming != uiDataGlobal.QuickMenu.tmpRoaming)
					{
						nonVolatileSettings.roaming = uiDataGlobal.QuickMenu.tmpRoaming;

						codeplugSetLastUsedChannelInZone(currentZone.NOT_IN_CODEPLUGDATA_indexNumber, 0);
						currentChannelData->rxFreq = 0U; // force reload of zone
					}
					else if ((ROAMING_EFFECTIVE() == ROAMING_MANUAL) && (menuDataGlobal.currentItemIndex == CH_SCREEN_QUICK_MENU_ROAMING))
					{
						codeplugSetLastUsedChannelInZone(currentZone.NOT_IN_CODEPLUGDATA_indexNumber, 0);
						currentChannelData->rxFreq = 0U; // force reload of zone, hence execute distance sort.
					}

					// CH_SCREEN_QUICK_MENU_MUTE
					if (audioAmpIsMuted() != uiDataGlobal.QuickMenu.tmpAudioMute)
					{
						audioAmpMute(uiDataGlobal.QuickMenu.tmpAudioMute);
					}
					break;
			}

			if (executingQuickKey)
			{
				updateQuickMenuScreen(false);
			}
			else
			{
				menuSystemPopPreviousMenu();
			}
			return;
		}
		else if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
		{
			uiChannelModeStopScanning();
			menuSystemPopPreviousMenu();
			return;
		}
		else if (KEYCHECK_SHORTUP_NUMBER(ev->keys) && BUTTONCHECK_DOWN(ev, BUTTON_SK2)
#if defined(CH_QUICKMENU_DELETE_ENABLED)
				&& (menuDataGlobal.currentItemIndex != CH_SCREEN_QUICK_MENU_DELETE)   // R41: на «Видалити» швидку клавішу призначити не можна
#endif
#if defined(CH_QUICKMENU_ZONE_REMOVE_ENABLED)
				&& (menuDataGlobal.currentItemIndex != CH_SCREEN_QUICK_MENU_ZONE_REMOVE)   // R43: і на «Вийняти із зони»
#endif
				)
		{
			isDirty = true;
			menuDataGlobal.menuOptionsSetQuickkey = ev->keys.key;
		}
	}

	if ((ev->events & (KEY_EVENT | FUNCTION_EVENT)) && (menuDataGlobal.menuOptionsSetQuickkey == 0))
	{
		if (KEYCHECK_PRESS(ev->keys, KEY_RIGHT)
#if defined(PLATFORM_RT84_DM1701) || defined(PLATFORM_MD2017)
				|| KEYCHECK_SHORTUP(ev->keys, KEY_ROTARY_INCREMENT)
#endif
				|| (QUICKKEY_FUNCTIONID(ev->function) == FUNC_RIGHT))
		{
			if (menuDataGlobal.menuOptionsTimeout > 0)
			{
				menuDataGlobal.menuOptionsTimeout = 1000;
			}
			isDirty = true;
			menuDataGlobal.newOptionSelected = false;

			switch(menuDataGlobal.currentItemIndex)
			{
				case CH_SCREEN_QUICK_MENU_FILTER_FM:
					if (uiDataGlobal.QuickMenu.tmpAnalogFilterLevel < NUM_ANALOG_FILTER_LEVELS - 1)
					{
						uiDataGlobal.QuickMenu.tmpAnalogFilterLevel++;
					}
					break;
				case CH_SCREEN_QUICK_MENU_FILTER_DMR:
					if (uiDataGlobal.QuickMenu.tmpDmrDestinationFilterLevel < NUM_DMR_DESTINATION_FILTER_LEVELS - 1)
					{
						uiDataGlobal.QuickMenu.tmpDmrDestinationFilterLevel++;
					}
					break;
				case CH_SCREEN_QUICK_MENU_DMR_CC_SCAN:
					if ((uiDataGlobal.QuickMenu.tmpDmrCcTsFilterLevel & DMR_CC_FILTER_PATTERN))
					{
						uiDataGlobal.QuickMenu.tmpDmrCcTsFilterLevel &= ~DMR_CC_FILTER_PATTERN;
					}
					break;
				case CH_SCREEN_QUICK_MENU_FILTER_DMR_TS:
					if (!(uiDataGlobal.QuickMenu.tmpDmrCcTsFilterLevel & DMR_TS_FILTER_PATTERN))
					{
						uiDataGlobal.QuickMenu.tmpDmrCcTsFilterLevel |= DMR_TS_FILTER_PATTERN;
					}
					break;
				case CH_SCREEN_QUICK_MENU_TALKAROUND:
					if (currentChannelData->txFreq != currentChannelData->rxFreq)
					{
						if (uiDataGlobal.QuickMenu.tmpTalkaround == false)
						{
							uiDataGlobal.QuickMenu.tmpTalkaround = true;
						}
					}
					break;
				case CH_SCREEN_QUICK_MENU_ROAMING:
					if (CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone) == false)
					{
#if defined(HAS_GPS)
						if (uiDataGlobal.QuickMenu.tmpRoaming < ((SETTINGS_GPS_MODE_GET(nonVolatileSettings) != GPS_NOT_DETECTED) ? (ROAMING_MAX_NUM - 1) : ROAMING_MANUAL))
#else
						if (uiDataGlobal.QuickMenu.tmpRoaming < ROAMING_MANUAL)
#endif
						{
							uiDataGlobal.QuickMenu.tmpRoaming++;
						}
					}
					break;
				case CH_SCREEN_QUICK_MENU_AUDIO_MUTE:
					uiDataGlobal.QuickMenu.tmpAudioMute = true;
					break;
#if defined(DUAL_CHANNEL_ENABLED)
				case CH_SCREEN_QUICK_MENU_DUAL_CHANNEL:   // R97
					dcSetMenuValue(true);
					break;
#endif
			}

			if (executingQuickKey) // Instantly apply new setting
			{
				goto quickKeyApply;
			}
		}
		else if (KEYCHECK_PRESS(ev->keys, KEY_LEFT)
#if defined(PLATFORM_RT84_DM1701) || defined(PLATFORM_MD2017)
				|| KEYCHECK_SHORTUP(ev->keys, KEY_ROTARY_DECREMENT)
#endif
				|| (QUICKKEY_FUNCTIONID(ev->function) == FUNC_LEFT))
		{
			if (menuDataGlobal.menuOptionsTimeout > 0)
			{
				menuDataGlobal.menuOptionsTimeout = 1000;
			}
			isDirty = true;
			menuDataGlobal.newOptionSelected = false;

			switch(menuDataGlobal.currentItemIndex)
			{
				case CH_SCREEN_QUICK_MENU_FILTER_FM:
					if (uiDataGlobal.QuickMenu.tmpAnalogFilterLevel > ANALOG_FILTER_NONE)
					{
						uiDataGlobal.QuickMenu.tmpAnalogFilterLevel--;
					}
					break;
				case CH_SCREEN_QUICK_MENU_FILTER_DMR:
					if (uiDataGlobal.QuickMenu.tmpDmrDestinationFilterLevel > DMR_DESTINATION_FILTER_NONE)
					{
						uiDataGlobal.QuickMenu.tmpDmrDestinationFilterLevel--;
					}
					break;
				case CH_SCREEN_QUICK_MENU_DMR_CC_SCAN:
					if (!(uiDataGlobal.QuickMenu.tmpDmrCcTsFilterLevel & DMR_CC_FILTER_PATTERN))
					{
						uiDataGlobal.QuickMenu.tmpDmrCcTsFilterLevel |= DMR_CC_FILTER_PATTERN;
					}
					break;
				case CH_SCREEN_QUICK_MENU_FILTER_DMR_TS:
					if ((uiDataGlobal.QuickMenu.tmpDmrCcTsFilterLevel & DMR_TS_FILTER_PATTERN))
					{
						uiDataGlobal.QuickMenu.tmpDmrCcTsFilterLevel &= ~DMR_TS_FILTER_PATTERN;
					}
					break;
				case CH_SCREEN_QUICK_MENU_TALKAROUND:
					if (currentChannelData->txFreq != currentChannelData->rxFreq)
					{
						if (uiDataGlobal.QuickMenu.tmpTalkaround)
						{
							uiDataGlobal.QuickMenu.tmpTalkaround = false;
						}
					}
					break;
				case CH_SCREEN_QUICK_MENU_ROAMING:
					if (!CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone))
					{
						if (uiDataGlobal.QuickMenu.tmpRoaming > ROAMING_OFF)
						{
							uiDataGlobal.QuickMenu.tmpRoaming--;
							//codeplugSetLastUsedChannelInZone(currentZone.NOT_IN_CODEPLUGDATA_indexNumber, 0);
							//currentChannelData->rxFreq = 0U;// force reload of zone
						}
					}
					break;
				case CH_SCREEN_QUICK_MENU_AUDIO_MUTE:
					uiDataGlobal.QuickMenu.tmpAudioMute = false;
					break;
#if defined(DUAL_CHANNEL_ENABLED)
				case CH_SCREEN_QUICK_MENU_DUAL_CHANNEL:   // R97
					dcSetMenuValue(false);
					break;
#endif
			}

			if (executingQuickKey) // Instantly apply new setting
			{
				goto quickKeyApply;
			}
		}
		else if ((ev->keys.event & KEY_MOD_PRESS) && (menuDataGlobal.menuOptionsTimeout > 0))
		{
			menuDataGlobal.menuOptionsTimeout = 0;
			menuSystemPopPreviousMenu();
			return;
		}
	}

	if (uiQuickKeysIsStoring(ev))
	{
		uiQuickKeysStore(ev, &menuQuickChannelExitStatus);
		isDirty = true;
	}

	if (isDirty)
	{
		updateQuickMenuScreen(false);
	}
}

//Scan Mode
static void scanStart(bool longPressBeep)
{
	// At least two channels are needed to run a scan process.
	if (canCurrentZoneBeScanned(&uiDataGlobal.Scan.availableChannelsCount) == false)
	{
		menuChannelExitStatus |= MENU_STATUS_ERROR;
		return;
	}

	if (voicePromptsIsPlaying())
	{
		voicePromptsTerminate();
	}

	directChannelNumber = 0;
	uiDataGlobal.Scan.direction = 1;
	uiDataGlobal.talkaround = false;

	// Clear all nuisance delete channels at start of scanning
	for (int i = 0; i < MAX_ZONE_SCAN_NUISANCE_CHANNELS; i++)
	{
		uiDataGlobal.Scan.nuisanceDelete[i] = -1;
	}
	uiDataGlobal.Scan.nuisanceDeleteIndex = 0;

	uiDataGlobal.Scan.active = true;
	uiDataGlobal.Scan.state = SCAN_STATE_SCANNING;
	uiDataGlobal.Scan.lastIteration = false;

	uiDataGlobal.Scan.stepTimeMilliseconds = settingsGetScanStepTimeMilliseconds();

	// In DIGITAL (slow) mode, we need at least 120ms to see the HR-C6000 to start the TS ISR.
	if (trxGetMode() == RADIO_MODE_DIGITAL)
	{
		int dwellTime;
		if(uiDataGlobal.Scan.stepTimeMilliseconds > 150)				// if >150ms use DMR Slow mode
		{
			dwellTime = ((currentRadioDevice->trxDMRModeRx == DMR_MODE_DMO) ? SCAN_DMR_SIMPLEX_SLOW_MIN_DWELL_TIME : SCAN_DMR_DUPLEX_SLOW_MIN_DWELL_TIME);
		}
		else
		{
			dwellTime = ((currentRadioDevice->trxDMRModeRx == DMR_MODE_DMO) ? SCAN_DMR_SIMPLEX_FAST_MIN_DWELL_TIME : (SCAN_DMR_DUPLEX_FAST_MIN_DWELL_TIME + SCAN_DMR_DUPLEX_FAST_EXTRA_DWELL_TIME));
		}

		uiDataGlobal.Scan.dwellTime = ((uiDataGlobal.Scan.stepTimeMilliseconds < dwellTime) ? dwellTime : uiDataGlobal.Scan.stepTimeMilliseconds);
	}
	else
	{
		uiDataGlobal.Scan.dwellTime = uiDataGlobal.Scan.stepTimeMilliseconds;
	}

	uiDataGlobal.Scan.timer.timeout = uiDataGlobal.Scan.dwellTime;
	uiDataGlobal.Scan.scanType = SCAN_TYPE_NORMAL_STEP;

	// Need to set the melody here, otherwise long press will remain silent
	// since beeps aren't allowed while scanning
	if (longPressBeep)
	{
		soundSetMelody(MELODY_KEY_LONG_BEEP);
	}

	// Set current channel index
	scanNextChannelIndex = codeplugGetLastUsedChannelNumberInCurrentZone();
	scanNextChannelReady = false;
}

static void updateTrxID(void)
{
	if (nonVolatileSettings.overrideTG != 0)
	{
		trxTalkGroupOrPcId = nonVolatileSettings.overrideTG;
	}
	else
	{
		/*
		 * VK3KYY
		 * I can't see a compelling reason to remove the TS override when changing TG
		 * The function trxUpdateTsForCurrentChannelWithSpecifiedContact(), used below, is used to handle the TS
		 *
			tsSetManualOverride(CHANNEL_CHANNEL, TS_NO_OVERRIDE);
		*/
		if ((currentRxGroupData.name[0] != 0) && (nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE] < currentRxGroupData.NOT_IN_CODEPLUG_numTGsInGroup))
		{
			codeplugContactGetDataForIndex(currentRxGroupData.contacts[nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE]], &currentContactData);
		}
		else
		{
			codeplugContactGetDataForIndex(currentChannelData->contact, &currentContactData);
		}

		tsSetContactHasBeenOverriden(CHANNEL_CHANNEL, false);

		trxUpdateTsForCurrentChannelWithSpecifiedContact(&currentContactData);
		trxTalkGroupOrPcId = codeplugContactGetPackedId(&currentContactData);
	}
	lastHeardClearLastID();
	menuPrivateCallClear();
}

static void scanning(void)
{
#if defined(DUAL_CHANNEL_ENABLED)
	if (uiDataGlobal.Scan.scanType == SCAN_TYPE_DUAL_CHANNEL)
	{
		dualScanning();   // R97: окремий рушій (звичайне сканування нижче не зачеплене)
		return;
	}
#endif
	// After initial settling time
	if((uiDataGlobal.Scan.state == SCAN_STATE_SCANNING) && (uiDataGlobal.Scan.timer.timeout > SCAN_SKIP_CHANNEL_INTERVAL) && (uiDataGlobal.Scan.timer.timeout < (uiDataGlobal.Scan.dwellTime - SCAN_FREQ_CHANGE_SETTLING_INTERVAL)))
	{
		//Signal detect for DMR channels
		if (trxGetMode() == RADIO_MODE_DIGITAL)
		{
			if(uiDataGlobal.Scan.stepTimeMilliseconds > 150)  // if >150ms use DMR Slow mode
			{                                                 // DMR Scan Slow mode for signal detect
				if (((nonVolatileSettings.dmrCcTsFilter & DMR_TS_FILTER_PATTERN)
						&&
						((slotState != DMR_STATE_IDLE) && ((dmrMonitorCapturedTS != -1) &&
								(((currentRadioDevice->trxDMRModeRx == DMR_MODE_DMO) && (dmrMonitorCapturedTS == trxGetDMRTimeSlot())) ||
										(currentRadioDevice->trxDMRModeRx == DMR_MODE_RMO)))))
						||
						// As soon as the HRC6000 get sync, timeCode != -1 or TS ISR is running
						HRC6000HasGotSync())
				{
					uiDataGlobal.Scan.state = SCAN_STATE_SHORT_PAUSED;
#if defined(PLATFORM_MD9600)
					uiDataGlobal.Scan.clickDiscriminator = CLICK_DISCRIMINATOR;
#endif

#if ! defined(PLATFORM_GD77S) // GD77S handle voice prompts on its own
					// Reload the channel as voice prompts aren't set while scanning
					if (nonVolatileSettings.audioPromptMode >= AUDIO_PROMPT_MODE_VOICE_THRESHOLD)
					{
						uiChannelModeLoadChannelData(false, true);
					}
#endif
					uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN; // Force screen refresh
					uiDataGlobal.Scan.timer.timeout = ((TIMESLOT_DURATION * 12) + TIMESLOT_DURATION) * 4; // (1 superframe + 1 TS) * 4 = TS Sync + incoming audio
				}
			}
			else //DMR Scan fast mode signal detect
			{
				if(trxCarrierDetected(RADIO_DEVICE_PRIMARY))
				{
#if ! defined(PLATFORM_GD77S) // GD77S handle voice prompts on its own
					// Reload the channel as voice prompts aren't set while scanning
					if (nonVolatileSettings.audioPromptMode >= AUDIO_PROMPT_MODE_VOICE_THRESHOLD)
					{
						uiChannelModeLoadChannelData(false, true);
					}
#endif
					uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN; // Force screen refresh

					if (((nonVolatileSettings.dmrCcTsFilter & DMR_TS_FILTER_PATTERN) == 0))
					{
						uiDataGlobal.Scan.timer.timeout = SCAN_SHORT_PAUSE_TIME * 2;	//needs longer delay if in DMR mode and TS Filter is off to allow full detection of signal
					}
					else
					{
						uiDataGlobal.Scan.timer.timeout = SCAN_SHORT_PAUSE_TIME;	//start short delay to allow full detection of signal
					}

					uiDataGlobal.Scan.state = SCAN_STATE_SHORT_PAUSED;		//state 1 = pause and test for valid signal that produces audio
#if defined(PLATFORM_MD9600)
					uiDataGlobal.Scan.clickDiscriminator = CLICK_DISCRIMINATOR;
#endif
				}
			}
		}
		else //Signal Detect for FM channels
		{
			if(trxCarrierDetected(RADIO_DEVICE_PRIMARY))
			{
#if ! defined(PLATFORM_GD77S) // GD77S handle voice prompts on its own
				// Reload the channel as voice prompts aren't set while scanning
				if (nonVolatileSettings.audioPromptMode >= AUDIO_PROMPT_MODE_VOICE_THRESHOLD)
				{
					uiChannelModeLoadChannelData(false, true);
				}
#endif
				uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN; // Force screen refresh

				uiDataGlobal.Scan.timer.timeout = SCAN_SHORT_PAUSE_TIME;	//start short delay to allow full detection of signal
				uiDataGlobal.Scan.state = SCAN_STATE_SHORT_PAUSED;		//state 1 = pause and test for valid signal that produces audio
#if defined(PLATFORM_MD9600)
				uiDataGlobal.Scan.clickDiscriminator = CLICK_DISCRIMINATOR;
#endif
			}
		}
	}

	// Only do this once if scan mode is PAUSE do it every time if scan mode is HOLD
	if(((uiDataGlobal.Scan.state == SCAN_STATE_PAUSED) && (nonVolatileSettings.scanModePause == SCAN_MODE_HOLD)) || (uiDataGlobal.Scan.state == SCAN_STATE_SHORT_PAUSED))
	{
#if defined(PLATFORM_MD9600)
		if (uiDataGlobal.Scan.clickDiscriminator > 0)
		{
			uiDataGlobal.Scan.clickDiscriminator--;
		}
		else
		{
#endif
			if (audioAmpGetStatus() & AUDIO_AMP_CHANNEL_RF)
			{
				bool needsToUpdateDistanceDisplay = (settingsLocationIsValid() &&
						(SETTINGS_CHANNEL_DISTANCE_EFFECTIVE() || (ROAMING_EFFECTIVE() != ROAMING_OFF))
#if defined(HAS_GPS)
						&& ((SETTINGS_GPS_MODE_EFFECTIVE(nonVolatileSettings) <= GPS_MODE_OFF) ||
								((SETTINGS_GPS_MODE_EFFECTIVE(nonVolatileSettings) >= GPS_MODE_ON) && ((gpsData.Status & (GPS_STATUS_HAS_FIX | GPS_STATUS_POSITION_UPDATED)) != 0)))
#endif
				);

				if (nonVolatileSettings.scanModePause == SCAN_MODE_STOP)
				{
					uiChannelModeStopScanning();

					if (needsToUpdateDistanceDisplay)
					{
						checkChannelLocation(currentChannelData);
					}

					return;
				}
				else
				{
					uiDataGlobal.Scan.timer.timeout = nonVolatileSettings.scanDelay * 1000;

					if ((uiDataGlobal.Scan.state == SCAN_STATE_SHORT_PAUSED) && needsToUpdateDistanceDisplay)
					{
						checkChannelLocation(currentChannelData);
						uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
					}

					uiDataGlobal.Scan.state = SCAN_STATE_PAUSED;
				}
			}
#if defined(PLATFORM_MD9600)
		}
#endif
	}

	if(uiDataGlobal.Scan.timer.timeout > 0)
	{
		if (scanNextChannelReady == false)
		{
			scanSearchForNextChannel();
		}

		uiDataGlobal.Scan.timer.timeout--;
	}
	else
	{
		if (scanNextChannelReady)
		{
			hidesChannelDetails();

			scanApplyNextChannel();

			// When less than 2 channel remain in the Zone
			if (uiDataGlobal.Scan.lastIteration)
			{
				scanStop(false);
				return;
			}
		}

		uiDataGlobal.Scan.state = SCAN_STATE_SCANNING;
	}
}

static void scanStop(bool loadChannel)
{
	int prevTS = dmrMonitorCapturedTS; // Always -1 on Simplex
	bool wasRXingDigital = ((trxGetMode() == RADIO_MODE_DIGITAL) && (slotState != DMR_STATE_IDLE) && (prevTS != -1));

	uiChannelModeStopScanning();
	uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
	uiChannelModeUpdateScreen(0);

	// It loads the channel data when exiting scan mode (as it was partialy readed)
	if (loadChannel)
	{
		uiChannelModeLoadChannelData(false, true);
	}

	// We were receiving something in Digital (Duplex), but since the TS filtering is OFF, we
	// will double check if selected TS stills match the previous one, when scan was paused.
	if (wasRXingDigital && ((nonVolatileSettings.dmrCcTsFilter & DMR_TS_FILTER_PATTERN) == 0))
	{
		int retries = 120;

		// Wait a bit until the TS is detected
		watchdogRun(false); // Temporary disable the watchdog here, as it could take too much time for it.
		do
		{
			vTaskDelay((10U / portTICK_PERIOD_MS));
		}
		while ((dmrMonitorCapturedTS == -1) && (retries-- > 0));
		watchdogRun(true);

		// Okay, we can now toggle the TS, if required
		if (((dmrMonitorCapturedTS != -1) && (prevTS != -1)) && (prevTS != dmrMonitorCapturedTS))
		{
			trxSetDMRTimeSlot(trxGetDMRTimeSlot(), true);
		}
	}
}

void uiChannelModeStopScanning(void)
{
#if defined(DUAL_CHANNEL_ENABLED)
	if (dualIsRunning())
	{
		dualSuspend();   // R97: швидке меню, «Режим APRS» тощо -- зупинити чергування (рація на A), режим лишається ввімкненим
		return;
	}
#endif
	uiDataGlobal.Scan.active = false;
	uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN; // Force screen refresh

#if ! defined(PLATFORM_GD77S) // GD77S handle voice prompts on its own
	// Reload the channel as voice prompts aren't set while scanning
	if (nonVolatileSettings.audioPromptMode >= AUDIO_PROMPT_MODE_VOICE_THRESHOLD)
	{
#if defined(DUAL_CHANNEL_ENABLED)
		if (dcIsEnabled() && (dcIsOnB() || dcAIsVfo()))
		{
			// R98-FIX4 Б3: те саме для A = VFO. R98-FIX1 В3: режим ввімкнено, зупинено на ОБРАНОМУ B (канал або VFO) -- перезавантажуємо саме його з пам'яті (ранні гілки
			// uiChannelModeLoadChannelData), а не A з «останнього каналу зони»: без стрибка на A при виході з меню/старті швидкого меню.
			uiChannelModeLoadChannelData(true, true);
		}
		else
#endif
		uiChannelModeLoadChannelData(false, true);
	}

	// We're exiting scan mode, and Roaming is auto-updating, but
	// we don't want to do that right now, as the operator probably
	// stopped scanning for a good reason (Rx || Rx/Tx).
	// Hence we start tracking (location & time) from here.
	if ((ROAMING_EFFECTIVE() >= ROAMING_5KM) &&
			settingsLocationIsValid() &&
			(CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone) == false))
	{
		uiDataGlobal.lastDistanceMillis = ticksGetMillis();
		uiDataGlobal.lastDistanceSortLocationLat = settingsLocationGetLatitude();
		uiDataGlobal.lastDistanceSortLocationLon = settingsLocationGetLongitude();
	}
#endif
}

bool uiChannelModeIsScanning(void)
{
	return uiDataGlobal.Scan.active;
}

#if defined(DUAL_CHANNEL_ENABLED)
/*
 * ============================================================================================================================
 * R97: «Подвійний прийом» по каналах кодплага. A = поточний канал зони (звичайний вибір), B = закріплений канал з будь-якої
 * зони (custom-data блок 18, dual_channel.c). Рушій -- наявне сканування (uiDataGlobal.Scan) з окремим scanType, тож звичайне
 * сканування зони, VFO Dual Watch і роумінг поводяться як до R97: усі вставки в спільних гілках -- за dualIsRunning().
 *
 * Стани: SCANNING -- по черзі A/B (витримка як у scanApplyNextChannel); SHORT_PAUSED -- є несуча/синхронізація; PAUSED -- є звук,
 * утримання «Затр. скан.» (scanDelay), ЗАВЖДИ як HOLD. Будь-яка «чужа» клавіша, меню чи передача лише ЗУПИНЯЮТЬ чергування
 * (dualSuspend: рація на A), режим лишається ввімкненим; dualAutoResume() відновлює його на екрані каналу.
 * ============================================================================================================================
 */

#define DUAL_RESUME_QUIET_MS   1000U   // скільки тиші на клавіатурі перед відновленням чергування

static bool dualIsRunning(void)
{
	return (uiDataGlobal.Scan.active && (uiDataGlobal.Scan.scanType == SCAN_TYPE_DUAL_CHANNEL));
}

static uint32_t dualDestination(const CodeplugChannel_t *ch, char *out, bool *numOnly, uint8_t *tsFlags, int16_t tgIdx);
static uint8_t dualEffectiveTs(const CodeplugChannel_t *ch, uint8_t tsFlags);

// R98 В3: який «канал» TS/ТГ-стану описує запис: VFO A/B (прапорці NOT_IN_CODEPLUG_flag, як tsGetManualOverrideFromCurrentChannel()) чи канал кодплага.
static Channel_t dualChanOf(const CodeplugChannel_t *ch)
{
	return (((ch->NOT_IN_CODEPLUG_flag & 0x01) == 0x01) ? (((ch->NOT_IN_CODEPLUG_flag & 0x02) == 0x02) ? CHANNEL_VFO_B : CHANNEL_VFO_A) : CHANNEL_CHANNEL);
}

// R98-FIX5 Б1: шапка екрана режиму -- лише «DW», заряд і час, у будь-якому стані (чергування, виклик, утримання, пауза): режим, TS, CC, потужність і
// S-метр -- у картках (рядки 3-5), без дублювання. Раніше (R97-FIX3) -- шапка обраного каналу з кодплага або справжня шапка під час виклику.
static void dualRenderHeader(bool force)
{
	uiUtilityRenderHeaderDw(force);
}

// R97-FIX7: для uiUtilityRedrawHeaderOnly() -- та сама шапка екрана режиму без залежності від стану сканування.
void uiChannelModeDualRenderHeader(bool force)
{
	dualRenderHeader(force);
}

// Для applicationMain.c (headerRowIsDirty: заряд, зміна CC): true -- шапку намалювано тут (режим чергує без активності).
bool uiChannelModeDualHeader(bool force)
{
	if (uiChannelModeDualScreenShown() == false)   // R98-FIX5 Б1: шапка режиму -- щоразу, коли показано екран режиму (не лише під час чергування без активності)
	{
		return false;
	}

	dualRenderHeader(force);
	return true;
}

// Витримка на каналі -- той самий розрахунок, що в scanApplyNextChannel() (DMR slow/fast, FM).
static void dualSetDwell(void)
{
	if (trxGetMode() == RADIO_MODE_DIGITAL)
	{
		int dwellTime;

		if (uiDataGlobal.Scan.stepTimeMilliseconds > 150)
		{
			dwellTime = ((currentRadioDevice->trxDMRModeRx == DMR_MODE_DMO) ? SCAN_DMR_SIMPLEX_SLOW_MIN_DWELL_TIME : SCAN_DMR_DUPLEX_SLOW_MIN_DWELL_TIME);
		}
		else
		{
			dwellTime = ((currentRadioDevice->trxDMRModeRx == DMR_MODE_DMO) ? SCAN_DMR_SIMPLEX_FAST_MIN_DWELL_TIME : (SCAN_DMR_DUPLEX_FAST_MIN_DWELL_TIME + SCAN_DMR_DUPLEX_FAST_EXTRA_DWELL_TIME));
		}

		uiDataGlobal.Scan.dwellTime = ((uiDataGlobal.Scan.stepTimeMilliseconds < dwellTime) ? dwellTime : uiDataGlobal.Scan.stepTimeMilliseconds);
	}
	else
	{
		uiDataGlobal.Scan.dwellTime = uiDataGlobal.Scan.stepTimeMilliseconds;
	}

	uiDataGlobal.Scan.timer.timeout = uiDataGlobal.Scan.dwellTime;
}

// Налаштувати рацію на A (поточний канал зони) або B, НЕ змінюючи «останній канал зони», зону й налаштування (на відміну від
// scanApplyNextChannel()). Для B -- гілка R97 у uiChannelModeLoadChannelData() (номер каналу = B, як у роумінгу R59).
// R98-FIX2 Є: незбережені правки каналу A (потужність/ТС/CC/«без репітера» зі швидкого меню) живуть ЛИШЕ в channelScreenChannelData (канальний буфер екрана).
// Канал B (не VFO) раніше вантажився в той самий буфер, а повернення на A перечитувало A з кодплага -- правки губились при кожному заході на B (а чергування
// ходить A<->B безперервно). Тепер: поки B -- канал, копію A тримає наявний статичний scanNextChannelData (його використовує лише стокове сканування, яке
// режим не запускає; нових буферів у RAM нема), і повернення на A відновлює її з пам'яті (uiChannelModeLoadChannelData(true,...)), нічого не пишучи в кодплаг.
// Ознака «буфер зараз містить B»: рація на B і currentChannelData -- канальний буфер (для B = VFO запис VFO лежить в settingsVFOChannel, буфер -- це A).
static bool dualBufHoldsB(void)
{
	return (dcIsOnB() && (currentChannelData == &channelScreenChannelData));
}

// R98-FIX5 А5: правки картки B = канал (шумодав, потужність, режим, смуга -- клавіші картки з покажчиком) живуть у робочій копії B, як правки A (R98-FIX2 Є).
// Буферів не додано: коли рація на B, B -- у канальному буфері, а копія A -- у scanNextChannelData; при поверненні на A обидва МІНЯЮТЬСЯ місцями (dualSwapBufs),
// тож копія B лежить у scanNextChannelData (A = канал) або лишається в канальному буфері (A = VFO -- буфер йому не потрібен). Ознака «копія є» -- s_dualBKeep;
// перед використанням копія звіряється з кодплагом (назва й частоти): якщо стоковий код за цей час переписав буфер (сканування, меню, A: VFO -> канал),
// B читається з кодплага, як раніше.
static void dualSwapBufs(void)
{
	uint8_t *a = (uint8_t *)&channelScreenChannelData;
	uint8_t *b = (uint8_t *)&scanNextChannelData;

	for (size_t i = 0; i < sizeof(CodeplugChannel_t); i++)
	{
		uint8_t t = a[i];

		a[i] = b[i];
		b[i] = t;
	}
}

static bool dualBCopyValid(const CodeplugChannel_t *copy)
{
	CodeplugChannel_t ref;

	if (s_dualBKeep == 0U)
	{
		return false;
	}

	codeplugChannelGetDataForIndex(dcChannelB(), &ref);
	return ((memcmp(ref.name, copy->name, sizeof(ref.name)) == 0) && (ref.rxFreq == copy->rxFreq) && (ref.txFreq == copy->txFreq));
}

// Новий B (інший канал, VFO, інша зона, вмикання): копія B і вибраний ТГ B -- з нуля (B читається з кодплага).
static void dualBReset(void)
{
	s_dualBKeep = 0U;
	s_dualTgIdxB = 0U;
}

static void dualTune(bool toB)
{
	bool wasOnB = dcIsOnB();
	bool bufHoldsB = dualBufHoldsB();   // R98-FIX2 Є: до зміни currentChannelData

	lastHeardClearLastID();
	dmrAesRxRetune();   // R98-FIX2 Е: стан RX AES попереднього каналу (ключ останнього виклику, кандидат PI) не переходить на наступний -- різні ключі на A і B

	if (toB)
	{
		if (wasOnB == false)
		{
			s_dualTgIdxA = nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE];
		}

		dcSetOnB(true);

		if (dcBIsVfo())
		{
			// R98 В2: B = VFO. Запис VFO лишається в settingsVFOChannel (канальний буфер channelScreenChannelData не чіпаємо -- там A);
			// стан стока (overrideTG, currentVFONumber, previousVFONumber) ізольований у uiVFOModeDualLoad().
			if (bufHoldsB && (dcAIsVfo() == false))
			{
				dualSwapBufs();   // R98-FIX2 Є: B (канал) -> B (VFO): A знову в канальному буфері (R98-FIX4 Б11: лише якщо A -- канал)
			}

			currentChannelData = &settingsVFOChannel[dualVfoIdx()];
			uiDataGlobal.currentSelectedChannelNumber = CH_DETAILS_VFO_CHANNEL;
			uiVFOModeDualLoad(dualVfoIdx(), true);
		}
		else
		{
			if ((bufHoldsB == false) && (dcAIsVfo() == false))
			{
				// R98-FIX2 Є: A (з незбереженими правками) -> scanNextChannelData; R98-FIX5 А5: копія B, якщо є, -- звідти в буфер (обмін місцями)
				if (dualBCopyValid(&scanNextChannelData))
				{
					dualSwapBufs();
				}
				else
				{
					memcpy(&scanNextChannelData, &channelScreenChannelData, sizeof(CodeplugChannel_t));
					codeplugChannelGetDataForIndex(dcChannelB(), &channelScreenChannelData);
				}
			}
			else if (dualBCopyValid(&channelScreenChannelData) == false)
			{
				// A = VFO (копія B -- у самому канальному буфері) або повторне налаштування на B: копії нема / не та -- з кодплага
				codeplugChannelGetDataForIndex(dcChannelB(), &channelScreenChannelData);
			}

			currentChannelData = &channelScreenChannelData;
			s_dualBKeep = 1U;   // з цієї миті буфер -- робоча копія B

			// R98-FIX5 А2: свій вибраний ТГ для B (індекс спільний -- підставляємо на час B прямим присвоєнням, без «брудного» прапорця налаштувань)
			nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE] = (int16_t)s_dualTgIdxB;
			uiChannelModeLoadChannelData(true, false);
			s_dualTgIdxB = (uint8_t)nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE];   // стокове завантаження могло скинути на 0 (поза списком)
		}
	}
	else
	{
		dcSetOnB(false);

		if (wasOnB)
		{
			if (dcBIsVfo() == false)
			{
				s_dualTgIdxB = (uint8_t)nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE];   // R98-FIX5 А2: вибір B (SK1 + ручка) -- зберегти
			}

			// індекс ТГ спільний для всіх каналів; на час B там був ТГ B -- повернути вибір A (пряме присвоєння: значення A вже збережене раніше)
			nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE] = s_dualTgIdxA;
		}

		if (dcAIsVfo())
		{
			// R98-FIX4 Б3: A = VFO -- той самий шлях, що для B = VFO (R98 В2): запис VFO в settingsVFOChannel, ізоляція стока в uiVFOModeDualLoad();
			// канальний буфер (там може бути копія B) не чіпаємо й копію A (scanNextChannelData) не відновлюємо (Б11).
			currentChannelData = &settingsVFOChannel[dualCardVfo(false)];
			uiDataGlobal.currentSelectedChannelNumber = CH_DETAILS_VFO_CHANNEL;
			uiVFOModeDualLoad(dualCardVfo(false), true);
			return;
		}

		currentChannelData = &channelScreenChannelData;   // R98: після VFO на B -- знову канальний буфер (A)

		if (bufHoldsB)
		{
			dualSwapBufs();   // R98-FIX2 Є: A -- з копії (правки збережено); R98-FIX5 А5: копія B -- у scanNextChannelData
		}

		uiChannelModeLoadChannelData((channelScreenChannelData.rxFreq != 0U), false);   // R98-FIX2 Є: A уже в пам'яті (канальний буфер) -- не перечитувати з кодплага; rxFreq == 0 (меню зон/кодплага скинули буфер) -- читаємо зону, як стока
	}
}

static uint16_t dualChannelA(void)
{
	return ((currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone > 0) ? (uint16_t)codeplugGetLastUsedChannelNumberInCurrentZone() : 0U);
}

// R98: B = VFO завжди існує (запис VFO є завжди); B = канал -- як раніше. Ключ рівності -- пара (тип, індекс), не «-1».
static uint8_t dualVfoIdx(void)
{
	return ((dcTypeB() == DC_TYPE_VFO_B) ? 1U : 0U);
}

// R98-FIX4 Б3: картка A або B -- VFO? Номер VFO картки (0 = A, 1 = B). Рація зараз на картці VFO (режим ввімкнено).
static bool dualCardIsVfo(bool isB)
{
	return (isB ? dcBIsVfo() : dcAIsVfo());
}

static uint8_t dualCardVfo(bool isB)
{
	return (((isB ? dcTypeB() : dcTypeA()) == DC_TYPE_VFO_B) ? 1U : 0U);
}

static bool dualOnVfoNow(void)
{
	return (dcIsEnabled() && dualCardIsVfo(dcIsOnB()));
}

static bool dualBExists(void)
{
	uint16_t b = dcChannelB();

	return (dcBIsVfo() || ((b >= DC_CH_MIN) && (b <= DC_CH_MAX) && codeplugAllChannelsIndexIsInUse(b)));
}

// A (канал кодплага; тип A лише «канал») збігається з B: лише канал з тим самим номером; пара «канал A, VFO B» -- ніколи.
static bool dualBSameAsA(void)
{
	return dcSameTarget(dcTypeA(), dualChannelA(), dcTypeB(), dcChannelB());   // R98-FIX4 Б5: ключ (тип, індекс) і для A
}

static dcPairCheck_t dualCheckPair(void)
{
	uint16_t chB = dcChannelB();
	bool bInUse = (((chB >= DC_CH_MIN) && (chB <= DC_CH_MAX)) ? codeplugAllChannelsIndexIsInUse(chB) : false);

	if (dcBIsVfo())
	{
		return DC_PAIR_OK;   // R98: VFO -- валідна ціль B без номера каналу
	}

	return dcCheckPair(dualChannelA(), chB, bInUse);
}

static void dualShowPairError(dcPairCheck_t err)
{
	// R97-FIX6: A==B -- не помилка (dual_err_b_is_a у коді не використовується, поле мови лишено для сталої розкладки)
	const char *msg = ((err == DC_PAIR_NO_B) ? currentLanguage->dual_err_no_b : currentLanguage->dual_err_b_gone);

	soundSetMelody(MELODY_ERROR_BEEP);
	uiNotificationShowShort(2000U, msg, true);
}

// Запустити чергування. holdCurrent -- після власної передачі: рація вже на каналі передачі, утримати його «Затр. скан.».
static bool dualStart(bool holdCurrent)
{
	if (voicePromptsIsPlaying())
	{
		voicePromptsTerminate();
	}

	directChannelNumber = 0;
	uiDataGlobal.talkaround = false;
	uiDataGlobal.Scan.active = true;
	uiDataGlobal.Scan.scanType = SCAN_TYPE_DUAL_CHANNEL;
	uiDataGlobal.Scan.lastIteration = false;
	uiDataGlobal.Scan.direction = 1;
	uiDataGlobal.Scan.stepTimeMilliseconds = settingsGetScanStepTimeMilliseconds();
	uiDataGlobal.Scan.state = SCAN_STATE_SCANNING;
	scanNextChannelReady = false;

	if (holdCurrent)
	{
		dualSetDwell();
		uiDataGlobal.Scan.timer.timeout = (nonVolatileSettings.scanDelay * 1000);
		uiDataGlobal.Scan.state = SCAN_STATE_PAUSED;
	}
	else
	{
		// R98-FIX6 Б1: чергування починається з картки, на якій рація вже стоїть (раніше -- завжди з A: при вмиканні з «A для повернення»
		// рація з B у ту ж мить стрибала на A). Перша витримка -- на поточній картці, далі -- як завжди.
		dualSetDwell();
	}

	uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
	uiChannelModeUpdateScreen(0);
	return true;
}

// R97-FIX4: ОБРАНИЙ канал. Виклик/утримання (state != SCANNING) -- де рація зараз (dcIsOnB()); чергування без активності -- за покажчиком;
// режим уже зупинений (меню) -- де стоїть рація. B вважається обраним, лише якщо він існує (задано й використовується).
static bool dualSelectedIsB(void)
{
	bool b = (dualIsRunning() ? ((uiDataGlobal.Scan.state != SCAN_STATE_SCANNING) ? dcIsOnB() : dcPointerB()) : dcIsOnB());

	return (b && dualBExists());
}

// Зупинити чергування, не вимикаючи режим: рація стає на ОБРАНИЙ канал (A або B; R97-FIX4 -- раніше завжди на A). Меню (швидке, головне,
// «Режим APRS») працюють з обраним; решта клавіш після цього переводить рацію на картку з покажчиком (handleEventCore, R98-FIX5 А5).
static void dualSuspend(void)
{
	bool selB = dualSelectedIsB();

	if (selB != dcIsOnB())
	{
		dualTune(selB);
	}

	uiDataGlobal.Scan.active = false;
	uiDataGlobal.Scan.scanType = SCAN_TYPE_NORMAL_STEP;
	uiDataGlobal.Scan.state = SCAN_STATE_SCANNING;
	uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
}

// R97-FIX3: режим вимикається, а рація зараз на B -- лишаємось на B як на звичайному каналі.
//  * B є в поточній зоні -- «останній канал зони» = позиція B у списку зони (для «Всіх каналів» -- номер B), зона та сама;
//  * B не з поточної зони -- відкриваємо B у зоні «Всі канали» (зона змінюється, коротке сповіщення), «останній канал» зони -1 = номер B.
// Канал завантажується звичайним шляхом (uiChannelModeLoadChannelData(false, ...)), тож номер, голосові підказки, збереження, TX і швидкі
// клавіші працюють на ньому, а вибраний ТГ у списку прийому лишається таким, яким його залишив B (не повертається до A).
static uint16_t dualZoneChannelAt(int pos, void *ctx);

// R98 В6: B = VFO і режим вимикається, а обраний саме він -- лишаємось на цьому VFO як у стоку: екран VFO з цим VFO поточним (currentVFONumber).
// Налаштування VFO не губляться (запис VFO -- той самий settingsVFOChannel). Перемикання поточного VFO -- стокове settingsSet(currentVFONumber).
// Вихід у VFO-екран -- стоковою menuSystemPopAllAndDisplaySpecificRootMenu() (як «Канал -> VFO»): стек меню чистий, перша ініціалізація VFO-екрана
// сама виставляє currentChannelData/номер вибраного. Канальний буфер (A) не чіпаємо -- повернення на канал працює як звичайно.
static void dualLeaveOnVfo(uint8_t v)
{

	dcSetOnB(false);
	lastHeardClearLastID();

	if (nonVolatileSettings.currentVFONumber != v)
	{
		settingsSet(nonVolatileSettings.currentVFONumber, v);
	}

	currentChannelData = &settingsVFOChannel[v];
	menuSystemPopAllAndDisplaySpecificRootMenu(UI_VFO_MODE, true);
}

static void dualLeaveOnB(void)
{
	uint16_t b = dcChannelB();
	int pos = -1;
	bool wasAll = CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone);

	// R98-FIX6 Б2: рація могла стояти на A (чергування за покажчиком на B) -- спершу прямо на B: канальний буфер = робоча копія B (незбережені правки
	// картки), спільний індекс ТГ = ТГ B. Раніше B перечитувався з кодплага (правки губились), а ТГ лишався від A.
	if (dualBufHoldsB() == false)
	{
		dualTune(true);
	}

	dcSetOnB(false);
	lastHeardClearLastID();

	if (wasAll == false)
	{
		pos = dcFindPos(currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone, b, dualZoneChannelAt, NULL);
	}

	if (wasAll || (pos >= 0))
	{
		codeplugSetLastUsedChannelInZone(currentZone.NOT_IN_CODEPLUGDATA_indexNumber, (int16_t)(wasAll ? b : pos));
	}
	else
	{
		settingsSet(nonVolatileSettings.currentZone, (int16_t)(codeplugZonesGetCount() - 1));   // «Всі канали» -- остання (віртуальна) зона
		uiChannelInitializeCurrentZone();                                                         // currentZone + назва зони
		codeplugSetLastUsedChannelInZone(currentZone.NOT_IN_CODEPLUGDATA_indexNumber, (int16_t)b);
		uiNotificationShowShort(2000U, currentLanguage->dual_zone_all, true);
	}

	uiChannelModeLoadChannelData(true, false);   // R98-FIX6 Б2: B уже в канальному буфері (з правками); номер -- «останній канал зони» = B
}

// Вимкнути режим (довге ▼ або пункт швидкого меню; червона з R97-FIX4 не вимикає): лишаємось на ОБРАНОМУ каналі -- A лишається на A, B (dualLeaveOnB()).
// Якщо B уже не існує (видалено/не задано) -- як раніше, на A.
static void dualDisable(void)
{
	if (directChannelNumber != 0)
	{
		// R98-FIX6 Б2: набір цифр режиму (номер каналу -- АБСОЛЮТНИЙ, або -1 -- частота) не переходить у звичайний екран: там стоковий набір
		// трактує directChannelNumber як позицію в зоні (зелена відкрила б інший канал). Вимкнення з набору можливе через швидке меню.
		directChannelNumber = 0;
		freqEnterReset();
	}

	bool stayB = dualSelectedIsB();   // R97-FIX4: лишаємось на ОБРАНОМУ (активність -- де рація; чергування -- за покажчиком; з меню -- де стоїть)
	uint8_t retType = dcTypeA();                                  // R98-FIX4 А1: «A для повернення» -- до будь-яких змін «останнього каналу зони»
	uint16_t retIdx = (dcAIsVfo() ? 0U : dualChannelA());

	if (stayB)
	{
		uiDataGlobal.Scan.active = false;
		uiDataGlobal.Scan.scanType = SCAN_TYPE_NORMAL_STEP;
		uiDataGlobal.Scan.state = SCAN_STATE_SCANNING;
		scanNextChannelReady = false;

		if (dcBIsVfo())
		{
			// R98: режим вимкнено ДО виходу на VFO-екран (запис блоку 18 -- як раніше, одразу)
			dcSetTxHold(false);
			(void)dcDisableWithReturnA(retType, retIdx);   // R98-FIX4 А1: «A для повернення» -- тим самим записом
			dualLeaveOnVfo(dualVfoIdx());
		}
		else
		{
			dcSetTxHold(false);
			(void)dcDisableWithReturnA(retType, retIdx);   // R98-FIX4 А1: «A для повернення» (канал/VFO A) -- тим самим записом, що й вимкнення
			dualLeaveOnB();
		}

		uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
		return;
	}
	else if (dualIsRunning())
	{
		dualSuspend();
	}
	else if (dcIsOnB())
	{
		dualTune(false);   // B не існує, а рація ще на ньому (після передачі) -- повернути на A
	}

	dcSetTxHold(false);
	(void)dcSetEnabled(false, true);
	uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;

	if (dcAIsVfo())
	{
		// R98-FIX4 Б6: обраний A = VFO -- вихід на екран VFO з цим VFO (як для B = VFO, R98 В6). Канальний буфер міг тримати B (картка B = канал) --
		// позначаємо його порожнім: наступний вхід на екран каналів перечитає канал зони стоковим шляхом, а не покаже B як поточний.
		if (dcBIsVfo() == false)
		{
			channelScreenChannelData.rxFreq = 0U;
		}

		dualLeaveOnVfo(dualCardVfo(false));
	}
}

static void dualAutoResume(void)
{
	dcSaveIfDue(ticksGetMillis());

	if ((dcIsEnabled() == false) || uiDataGlobal.Scan.active || uiDataGlobal.Scan.toneActive ||
			(menuSystemGetCurrentMenuNumber() != UI_CHANNEL_MODE) || (directChannelNumber != 0) ||
			uiDataGlobal.displayChannelSettings || monitorModeData.isEnabled || trxTransmissionEnabled ||
#if defined(APRS_RX)
			aprsModeIsActive() ||   // «Режим APRS» слухає свою частоту -- режим чекає його завершення
#endif
			((ticksGetMillis() - s_dualKeyMs) < DUAL_RESUME_QUIET_MS))
	{
		return;
	}

	dcPairCheck_t chk = dualCheckPair();

	if (chk != DC_PAIR_OK)
	{
		dcSetTxHold(false);
		dualDisable();
		dualShowPairError(chk);
		uiChannelModeUpdateScreen(0);
		return;
	}

	if (dualBSameAsA())
	{
		// R97-FIX6: A == B -- не помилка: режим лишається ввімкненим, чергування не крутиться (той самий канал), екран режиму показано,
		// рація стоїть на каналі. Щойно A і B стануть різними -- наступний виклик запустить чергування саме; без сповіщень.
		dcSetTxHold(false);
		return;
	}

	bool hold = dcTxHoldPending();

	dcSetTxHold(false);
	(void)dualStart(hold);
}

// R97-FIX5: режим ввімкнено, чергування призупинене клавішею (набір номера або пауза DUAL_RESUME_QUIET_MS) і ми на екрані каналу --
// тоді екран малює dualRenderScreen(), а не стоковий (S-метр не спалахує). Умови -- ті самі, що в dualAutoResume().
static bool dualHoldScreen(void)
{
	return (dcIsEnabled() && (dualIsRunning() == false) && (uiDataGlobal.Scan.active == false) && (uiDataGlobal.Scan.toneActive == false) &&
			(menuSystemGetCurrentMenuNumber() == UI_CHANNEL_MODE) && (uiDataGlobal.displayChannelSettings == false) &&
			(monitorModeData.isEnabled == false) && (trxTransmissionEnabled == false) &&
#if defined(APRS_RX)
			(aprsModeIsActive() == false) &&
#endif
			((directChannelNumber != 0) || ((ticksGetMillis() - s_dualKeyMs) < DUAL_RESUME_QUIET_MS) || dualSingle()));
}

// R97-FIX6: режим ввімкнено, пара коректна, але A == B: чергування не потрібне (один канал); екран режиму лишається, ручка/▲▼ працюють за правилами обраного.
static bool dualSingle(void)
{
	return (dcIsEnabled() && (dualIsRunning() == false) && dualBSameAsA() && dualBExists());   // R98-FIX4 Б5: A==B за ключем (тип, індекс) -- і для двох однакових VFO
}

// R97-FIX5: кінець обробника клавіші: «тишу» знято безумовно (інваріант), екран каналу перемальовано рівно один раз
// (UpdateScreen сам вибере dualRenderScreen() у режимі/паузі або стоковий -- сканування, деталі, передача); інше меню -- нічого не малюємо.
static void dualQuietEnd(void)
{
	if (s_dualQuiet)
	{
		s_dualQuiet = false;

		if (menuSystemGetCurrentMenuNumber() == UI_CHANNEL_MODE)
		{
			uiChannelModeUpdateScreen(0);
		}
	}
}

static void dualScanning(void)
{
	if ((uiDataGlobal.Scan.state == SCAN_STATE_SCANNING) && (uiDataGlobal.Scan.timer.timeout > SCAN_SKIP_CHANNEL_INTERVAL) &&
			(uiDataGlobal.Scan.timer.timeout < (uiDataGlobal.Scan.dwellTime - SCAN_FREQ_CHANGE_SETTLING_INTERVAL)))
	{
		bool found = false;
		int pause = SCAN_SHORT_PAUSE_TIME;

		// Виявлення -- те саме, що в scanning() (DMR slow: синхронізація/захоплений слот; DMR fast і FM: несуча)
		if (trxGetMode() == RADIO_MODE_DIGITAL)
		{
			if (uiDataGlobal.Scan.stepTimeMilliseconds > 150)
			{
				if (((nonVolatileSettings.dmrCcTsFilter & DMR_TS_FILTER_PATTERN) &&
						((slotState != DMR_STATE_IDLE) && ((dmrMonitorCapturedTS != -1) &&
								(((currentRadioDevice->trxDMRModeRx == DMR_MODE_DMO) && (dmrMonitorCapturedTS == trxGetDMRTimeSlot())) ||
										(currentRadioDevice->trxDMRModeRx == DMR_MODE_RMO))))) ||
						HRC6000HasGotSync())
				{
					found = true;
					pause = ((TIMESLOT_DURATION * 12) + TIMESLOT_DURATION) * 4;
				}
			}
			else if (trxCarrierDetected(RADIO_DEVICE_PRIMARY))
			{
				found = true;
				pause = (((nonVolatileSettings.dmrCcTsFilter & DMR_TS_FILTER_PATTERN) == 0) ? (SCAN_SHORT_PAUSE_TIME * 2) : SCAN_SHORT_PAUSE_TIME);
			}
		}
		else if (trxCarrierDetected(RADIO_DEVICE_PRIMARY))
		{
			found = true;
		}

		if (found)
		{
			uiDataGlobal.Scan.state = SCAN_STATE_SHORT_PAUSED;
			uiDataGlobal.Scan.timer.timeout = pause;
			uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;   // виділити рядок, що приймає
		}
	}

	// Утримання: ЗАВЖДИ як HOLD (поки є звук -- таймер «Затр. скан.» перезапускається); «Тип скану» STOP/PAUSE режим не вимикає
	if ((uiDataGlobal.Scan.state == SCAN_STATE_PAUSED) || (uiDataGlobal.Scan.state == SCAN_STATE_SHORT_PAUSED))
	{
		if (audioAmpGetStatus() & AUDIO_AMP_CHANNEL_RF)
		{
			uiDataGlobal.Scan.timer.timeout = (nonVolatileSettings.scanDelay * 1000);
			uiDataGlobal.Scan.state = SCAN_STATE_PAUSED;
		}
	}

	if (uiDataGlobal.Scan.timer.timeout > 0)
	{
		uiDataGlobal.Scan.timer.timeout--;
	}
	else
	{
		bool wasPaused = (uiDataGlobal.Scan.state != SCAN_STATE_SCANNING);

		hidesChannelDetails();
		uiDataGlobal.Scan.state = SCAN_STATE_SCANNING;
		dualTune(dcIsOnB() == false);
		dualSetDwell();

		if (wasPaused)
		{
			uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;   // зняти виділення / рядок абонента; повний екран -- шапка стає статичною «[DW]»
		}
		// R97-FIX2: у звичайному перемиканні A/B шапку НЕ перемальовуємо: під час чергування вона статична («[DW]», без TS/CC/S-метра),
		// тож зміна каналу нічого на екрані не міняє (раніше перемальовування кожні ~кілька сотень мс давало мерехтіння).
	}
}

// ---- валкодер на рядку B: крок по каналах ПОТОЧНОЇ зони ----
// ctx -- зона (CodeplugZone_t *); NULL -- поточна зона (R98-FIX5 А3: картка B може ходити по своїй зоні, вибраній SK2 + ручкою).
static uint16_t dualZoneChannelAt(int pos, void *ctx)
{
	const CodeplugZone_t *z = ((ctx != NULL) ? (const CodeplugZone_t *)ctx : &currentZone);

	if (CODEPLUG_ZONE_IS_ALLCHANNELS(*z))
	{
		return (codeplugAllChannelsIndexIsInUse(pos + 1) ? (uint16_t)(pos + 1) : 0U);
	}

	return (((pos >= 0) && (pos < z->NOT_IN_CODEPLUGDATA_numChannelsInZone)) ? z->channels[pos] : 0U);
}

// R98-FIX5 А3: зона картки B для ручки -- вибрана SK2 + ручкою (s_dualZoneB), якщо вона ще придатна й не поточна; інакше NULL (поточна зона, як раніше).
static const CodeplugZone_t *dualZoneB(CodeplugZone_t *buf)
{
	int zn = ((int)s_dualZoneB - 1);

	if ((zn < 0) || (zn >= codeplugZonesGetCount()) || (zn == nonVolatileSettings.currentZone) || (codeplugZoneIsUsable(zn, buf) == false))
	{
		return NULL;
	}

	return buf;
}

// R98-FIX7 А1: ручка на картці B = канал -- лише КАНАЛИ (зона, вибрана SK2 + ручкою, інакше поточна), коло замикається на каналах (dcStepPos, A == B
// дозволено -- нічого не пропускаємо). VFO з кола прибрано: канал <-> VFO -- червоною (dualRedToggle); на картці VFO ручка -- частота (dualIsVfoStepKey).
// B не з цієї зони -- крок від позиції A (як раніше).
static void dualStepB(int dir)
{
	CodeplugZone_t zb;
	const CodeplugZone_t *z = dualZoneB(&zb);   // R98-FIX5 А3: зона B, вибрана SK2 + ручкою; NULL -- поточна
	const CodeplugZone_t *zz = ((z != NULL) ? z : &currentZone);
	void *ctx = (void *)z;
	int n = (CODEPLUG_ZONE_IS_ALLCHANNELS(*zz) ? zz->NOT_IN_CODEPLUGDATA_highestIndex : zz->NOT_IN_CODEPLUGDATA_numChannelsInZone);
	int from = dcFindPos(n, dcChannelB(), dualZoneChannelAt, ctx);

	if ((from < 0) && (z == NULL))
	{
		from = dcFindPos(n, dualChannelA(), dualZoneChannelAt, NULL);   // B не з цієї зони -- крок від A
	}

	int pos = dcStepPos(n, from, dir, 0U, dualZoneChannelAt, ctx);

	if (pos < 0)
	{
		soundSetMelody(MELODY_ERROR_BEEP);
		return;
	}

	dualBReset();   // R98-FIX3 Б / R98-FIX5 А5: новий B -- з кодплага (копія й ТГ B -- з нуля)
	(void)dcSetChannelB(dualZoneChannelAt(pos, ctx), false);   // відкладений запис (3 с без змін); тип -> «канал»

	if (dualIsRunning() == false)
	{
		s_dualKeyMs = 0U;   // R97-FIX6: був A==B -- після зміни B чергування стартує саме (або лишається A==B)
		dualAutoResume();
	}
	else if (dcIsOnB())
	{
		uiDataGlobal.Scan.state = SCAN_STATE_SCANNING;
		dualTune(true);
		dualSetDwell();
	}
}

// R98-FIX5 А3: SK2 + ручка на картці B = канал -- «великий крок»: B = ПЕРШИЙ використаний канал наступної/попередньої зони. Порядок і пропуск зон -- стокові
// (codeplugZoneStep + codeplugZoneIsUsable, як SK2 + ручка на звичайному екрані; «Всі канали» -- остання, віртуальна, перший канал -- найменший використаний номер).
// Відлік -- від зони, вибраної для B раніше (s_dualZoneB), інакше від поточної. Поточна зона, A й «останній канал зони» не змінюються; запис блоку 18 --
// відкладений, як ручкою; копія й ТГ B -- з нуля. Коротке сповіщення -- назва зони B. Далі ручка на B ходить по цій зоні.
static void dualZoneStepB(int dir)
{
	CodeplugZone_t z;
	int count = codeplugZonesGetCount();
	int from = ((((int)s_dualZoneB - 1) >= 0) && (((int)s_dualZoneB - 1) < count)) ? ((int)s_dualZoneB - 1) : (int)nonVolatileSettings.currentZone;
	int zn = codeplugZoneStep(from, count, (dir > 0), zoneStepUsable, NULL);
	uint16_t ch = 0U;

	if ((zn >= 0) && codeplugZoneGetDataForNumber(zn, &z))
	{
		int n = (CODEPLUG_ZONE_IS_ALLCHANNELS(z) ? z.NOT_IN_CODEPLUGDATA_highestIndex : z.NOT_IN_CODEPLUGDATA_numChannelsInZone);

		for (int i = 0; (i < n) && (ch == 0U); i++)
		{
			ch = dualZoneChannelAt(i, &z);
		}
	}

	if ((ch == 0U) || (zn > 254))
	{
		soundSetMelody(MELODY_ERROR_BEEP);
		return;
	}

	char zname[17];

	codeplugUtilConvertBufToDisplayString(z.name, zname, 16);
	s_dualZoneB = (uint8_t)(zn + 1);
	dualBReset();
	(void)dcSetChannelB(ch, false);   // відкладений запис (3 с без змін); тип -> «канал»
	uiNotificationShowShort(1500U, zname, true);

	if (dualIsRunning() == false)
	{
		s_dualKeyMs = 0U;
		dualAutoResume();
	}
	else if (dcIsOnB())
	{
		uiDataGlobal.Scan.state = SCAN_STATE_SCANNING;
		dualTune(true);
		dualSetDwell();
	}
}

// R98-FIX7 Б: червона на картці з покажчиком -- канал <-> VFO, як стокова червона на екранах каналів/VFO (канали -> VFO, VFO -> канали):
// картка A: канал -> VFO A; VFO (A або B) -> канал A, що був до VFO (стоковий «останній канал зони» -- його VFO не чіпає). Картка B: канал -> VFO B;
// VFO (B або старий запис R98..R98-FIX5 «B = VFO A») -> закріплений канал B (номер у блоці 18 тип VFO не затирає). Нових змінних нема.
// Правки каналу на VFO не переносяться (як у стоку: VFO -- свій запис); канал після VFO -- з кодплага (A -- як ручкою з VFO у R98-FIX4 Б11, B -- dualBReset).
// A == B після перемикання (напр. A = VFO B з екрана VFO і B -> VFO B) -- допустимо: режим лишається, чергування тихо стоїть (dualAutoResume).
static void dualRedToggle(void)
{
	// Діє на картку з покажчиком і при A == B (інакше червона на B у стані «A = VFO B, B = VFO B» перемкнула б A, а не повернула B на його канал)
	if (dcPointerB())
	{
		if (dcBIsVfo() && ((dcChannelB() == 0U) || (codeplugAllChannelsIndexIsInUse(dcChannelB()) == false)))
		{
			soundSetMelody(MELODY_ERROR_BEEP);   // закріпленого каналу B нема / видалено -- лишаємось на VFO
			return;
		}

		dualSuspend();
		dualBReset();   // новий B: канал -- з кодплага, VFO -- свій запис; копія й ТГ B -- з нуля

		if (dcBIsVfo())
		{
			dcSetTypeB(DC_TYPE_CHANNEL);   // відкладений запис; номер каналу B той самий
		}
		else
		{
			dcSetTypeB(DC_TYPE_VFO_B);     // відкладений запис; номер каналу B лишається для повернення
		}

		if (dcIsOnB())
		{
			dualTune(true);
		}
	}
	else
	{
		dualSuspend();

		if (dcAIsVfo())
		{
			if (dcIsOnB())
			{
				dualTune(false);   // з B -- спершу на A (індекс ТГ A, рація на A)
			}

			s_dualBKeep = 0U;   // R98-FIX5 А5: канал A вантажиться в канальний буфер -- там була копія B (A = VFO); B перечитається з кодплага
			dcSetTypeA(DC_TYPE_CHANNEL);
			currentChannelData = &channelScreenChannelData;
			uiChannelModeLoadChannelData(false, true);   // стоковий «останній канал зони» -- той самий, що до VFO
		}
		else
		{
			if ((dcIsOnB() == false) && (s_dualBKeep != 0U))
			{
				dualSwapBufs();   // R98-FIX5 А5: робоча копія B переходить туди, де вона живе при A = VFO (канальний буфер)
			}

			dcSetTypeA(DC_TYPE_VFO_A);   // відкладений запис блоку 18 (тип поточного A)
			dualTune(false);             // налаштувати на VFO (ізольовано); канальний буфер не чіпаємо
		}
	}

	s_dualKeyMs = 0U;   // чергування -- одразу
	uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
	dualAutoResume();

	if (dualIsRunning() == false)
	{
		uiChannelModeUpdateScreen(0);
	}
}

// R98-FIX4 Б4 / R98-FIX5 А0: dualIsAKey() прибрано -- у режимі всі клавіші й так ідуть у правила режиму (handleEventCore), тож ручка при A = VFO теж.

// R98 В8 / R98-FIX7 А2: ручка (без SK1) на картці VFO з покажчиком (режим ввімкнено, екран каналу) -- крок частоти цього VFO, як ручка в стоковому
// екрані VFO (handleUpKey/handleDownKey: stepFrequency на крок VFO). SK2 + ручка -- те саме, що було з R98 (у стоку SK2 + ручка вибирає поле RX/TX --
// у картці його нема). Ручка з VFO на канал не виводить: канал <-> VFO -- червоною.
static bool dualIsVfoStepKey(const uiEvent_t *ev)
{
	return (dcIsEnabled() && dualCardIsVfo(dcPointerB()) && (menuSystemGetCurrentMenuNumber() == UI_CHANNEL_MODE) &&   // R98-FIX4 Б3: картка з покажчиком -- VFO (A або B)
			(BUTTONCHECK_DOWN(ev, BUTTON_SK1) == false) &&
			((ev->keys.key == KEY_ROTARY_INCREMENT) || (ev->keys.key == KEY_ROTARY_DECREMENT)));
}

// Клавіші під час чергування: true -- оброблено (решта -- як без режиму, через dualSuspend()).
static bool dualHandleKey(uiEvent_t *ev)
{
	if (dualIsVfoStepKey(ev))
	{
		// R98 В8 / R98-FIX7 А2: ручка (і SK2 + ручка) на картці VFO -- крок частоти цього VFO (стокова stepFrequency(), VFO_FREQ_STEP_TABLE).
		// Чергування призупиняється на картці (тиша DUAL_RESUME_QUIET_MS), далі -- як після будь-якої клавіші.
		if (KEYCHECK_SHORTUP(ev->keys, ev->keys.key))
		{
			dualSuspend();   // чергування стоп; рація на обраному

			if (dcIsOnB() != dcPointerB())
			{
				dualTune(dcPointerB());   // рація на картці з покажчиком (VFO); currentChannelData -- запис цього VFO
			}

			if (dualOnVfoNow())
			{
				uiVFOModeDualStep(dualCardVfo(dcIsOnB()), ((ev->keys.key == KEY_ROTARY_INCREMENT) ? 1 : -1));
			}

			uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
			uiChannelModeUpdateScreen(0);
		}
		return true;
	}

	if (dualIsSquelchKey(ev))
	{
		// R98-FIX3 Б: SK1 + ручка -- поріг шумодава FM картки з покажчиком (у стоку ▲/▼; у режимі ▲/▼ -- покажчик)
		if (KEYCHECK_SHORTUP(ev->keys, ev->keys.key))
		{
			dualSquelchStep((ev->keys.key == KEY_ROTARY_INCREMENT) ? 1 : -1);
		}
		return true;
	}

	if (BUTTONCHECK_DOWN(ev, BUTTON_SK2) && (BUTTONCHECK_DOWN(ev, BUTTON_SK1) == false) &&
			((ev->keys.key == KEY_ROTARY_INCREMENT) || (ev->keys.key == KEY_ROTARY_DECREMENT)))
	{
		// R98-FIX5 А3: SK2 + ручка на картці-каналі (картку VFO обробив dualIsVfoStepKey вище) -- «великий крок»: зона
		if (KEYCHECK_SHORTUP(ev->keys, ev->keys.key))
		{
			int dir = ((ev->keys.key == KEY_ROTARY_INCREMENT) ? 1 : -1);

			if (dcPointerB() && (dualSingle() == false))
			{
				dualZoneStepB(dir);   // B -- перший канал наступної/попередньої зони; зона A не змінюється
				uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
				uiChannelModeUpdateScreen(0);
			}
			else
			{
				// A -- стокова зміна зони (handleUpKey/handleDownKey з SK2: наступна придатна зона, A = її останній канал, екран перезапускається)
				dualSuspend();

				if (dcIsOnB())
				{
					dualTune(false);
				}

				s_dualQuiet = true;

				if (dir > 0)
				{
					handleUpKey(ev);
				}
				else
				{
					handleDownKey(ev);
				}
			}
		}
		return true;
	}

	if (BUTTONCHECK_DOWN(ev, BUTTON_SK2) || BUTTONCHECK_DOWN(ev, BUTTON_SK1))
	{
		return false;
	}

	switch (ev->keys.key)
	{
		case KEY_FRONT_UP:     // покажчик на A
		case KEY_FRONT_DOWN:   // покажчик на B; довге ▼ -- гаряча клавіша (вимкнути режим), автоповтор ігноруємо
			if ((ev->keys.key == KEY_FRONT_DOWN) && KEYCHECK_LONGDOWN(ev->keys, KEY_FRONT_DOWN) && (KEYCHECK_LONGDOWN_REPEAT(ev->keys, KEY_FRONT_DOWN) == false))
			{
				dualHotkeyToggle();
				return true;
			}

			if (KEYCHECK_SHORTUP(ev->keys, ev->keys.key))
			{
				dcSetPointerB(ev->keys.key == KEY_FRONT_DOWN);
				uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
				uiChannelModeUpdateScreen(0);
			}
			return true;       // PRESS/LONG теж наші: довге «вгору» (старт сканування зони) у режимі не діє

		case KEY_ROTARY_INCREMENT:
		case KEY_ROTARY_DECREMENT:
			if (KEYCHECK_SHORTUP(ev->keys, ev->keys.key))
			{
				int dir = ((ev->keys.key == KEY_ROTARY_INCREMENT) ? 1 : -1);

				// R98-FIX7 А1: тут картка з покажчиком -- канал (картку VFO обробив dualIsVfoStepKey вище): лише канали, без VFO в колі
				if (dcPointerB())
				{
					dualStepB(dir);
				}
				else
				{
					// Покажчик на A -- звичайна зміна каналу зони (ті самі стокові handleUpKey/handleDownKey -- коло по каналах зони)
					dualSuspend();

					if (dcIsOnB())
					{
						dualTune(false);   // R97-FIX4: виклик на B (обраний B), покажчик на A -- канал зони міняємо з A
					}

					s_dualQuiet = true;   // R97-FIX4: стокове перемальовування (з S-метром) на час кроку каналу придушено -- екран малює лише dualRenderScreen

					// R97-FIX6: A може стати B -- тоді чергування тихо зупиняється (режим лишається ввімкненим, A==B)
					if (dir > 0)
					{
						handleUpKey(ev);
					}
					else
					{
						handleDownKey(ev);
					}

					s_dualQuiet = false;
					s_dualKeyMs = 0U;   // чергування -- одразу, без паузи тиші
					dualAutoResume();

					if (dualIsRunning() == false)
					{
						uiChannelModeUpdateScreen(0);   // чергування не стартувало (B==A чекає, помилка пари) -- звичайний екран, а не порожній
					}

					return true;
				}

				uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
				uiChannelModeUpdateScreen(0);
			}
			return true;

		case KEY_RED:
			// R97-FIX4: червона режим НЕ вимикає (вимикають лише довге ▼ і пункт швидкого меню «Подв. прийом»).
			// R98-FIX7 Б: коротка червона -- канал <-> VFO картки з покажчиком (як стокова червона: канали -> VFO і назад), див. dualRedToggle().
			// Набір цифр має пріоритет: його червона скасовує раніше (dualEntryKey), сюди не доходить. Довге/повтор/PRESS -- з'їдаємо без дій (як було).
			if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
			{
				dualRedToggle();
			}
			return true;

		default:
			break;
	}

	return false;
}

// ---- R98-FIX3 А: набір цифр у режимі ----------------------------------------------------------------------------------------------------------------------
// Причина «неадекватності» до R98-FIX3 (А0): цифри йшли в стоковий набір прямого номера (directChannelNumber -- ПОЗИЦІЯ в зоні, не номер з рядка 1 картки),
// handleEvent() перед цим повертав рацію на A (dualTune(false)), тож обраною ставала картка A, хоч покажчик був на B; набране ніде не показувалось (нижній
// рядок «# n» прибрано у FIX6), чергування не поновлювалось (dualAutoResume() чекає directChannelNumber == 0), а ручка/▲▼ поза чергуванням ішли в стокові
// обробники (ручка -- зміна каналу A, ▲/▼ -- ТГ/шумодав), а не в покажчик. Тепер набір -- власний стан режиму на тих самих змінних (нових нема):
//   directChannelNumber > 0   -- набирається НОМЕР КАНАЛУ (абсолютний, як у рядку 1 картки) для картки з покажчиком;
//   directChannelNumber == -1 -- набирається ЧАСТОТА для картки VFO (цифри -- у стоковому uiDataGlobal.FreqEnter, правила стокового екрана VFO).
// Поки набір триває: цифри доповнюють, ▼ стирає останню (як у стоковому введенні частоти), зелена підтверджує, червона скасовує (R98-FIX7: набір має
// пріоритет над «червона = канал <-> VFO»), решта клавіш (ручка, ▲, довге ▼, SK1/SK2 + ...) з'їдається -- картки й канали не перемикаються. Довге 0 / довге 8 -- як у стоку
// (без звуку, відкриття пеленга): набір скасовується, клавіша йде стоковому обробнику. Тайм-ауту нема (у стоку його теж нема). PTT набору не чіпає: передача --
// на каналі, де рація стоїть (набране не застосовано). Після підтвердження/скасування -- dualAutoResume().
#define DUAL_ENTRY_FREQ    (-1)
#define DUAL_ENTRY_FREQ_N  8     // цифр частоти, як у стоковому екрані VFO (8 -- підтвердження саме)

static void dualEntryEnd(void)
{
	directChannelNumber = 0;
	freqEnterReset();
	s_dualKeyMs = 0U;   // чергування -- одразу, без паузи тиші
	uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
	dualAutoResume();
}

// Номер каналу для картки A (лише якщо він є в поточній зоні; у «Всіх каналах» -- будь-який використаний) або B (будь-який використаний).
static bool dualEntryApplyChannel(int num)
{
	if ((num < (int)DC_CH_MIN) || (num > (int)DC_CH_MAX) || (codeplugAllChannelsIndexIsInUse(num) == false))
	{
		return false;
	}

	if (dcPointerB())
	{
		dualBReset();   // R98-FIX3 Б / R98-FIX5 А5: новий B -- з кодплага (копія й ТГ B -- з нуля)
		s_dualZoneB = 0U;   // R98-FIX5 А3: номер з будь-якої зони -- ручка знову ходить по поточній зоні
		(void)dcSetChannelB((uint16_t)num, false);   // відкладений запис (3 с без змін), як ручкою

		if (dcIsOnB())
		{
			dualTune(true);   // рація стоїть на B -- одразу на новий B
		}
		return true;
	}

	bool allCh = CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone);
	int pos = (allCh ? num : dcFindPos(currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone, (uint16_t)num, dualZoneChannelAt, NULL));

	if (pos < 0)
	{
		return false;   // A -- лише канал поточної зони
	}

	if (dcIsOnB())
	{
		dualTune(false);
	}

	codeplugSetLastUsedChannelInZone(currentZone.NOT_IN_CODEPLUGDATA_indexNumber, (int16_t)pos);   // як стоковий прямий номер (позиція / абсолютний номер)
	uiChannelModeLoadChannelData(false, true);
	return true;
}

// Частота з набраних цифр -- для VFO на картці B (рація спершу налаштовується на цей VFO, як для SK2 + ручка).
static bool dualEntryApplyFreq(void)
{
	if (dcIsOnB() != dcPointerB())
	{
		dualTune(dcPointerB());   // R98-FIX4 Б3: картка VFO з покажчиком -- A або B
	}

	return (dualOnVfoNow() && uiVFOModeDualFreqEnter(dualCardVfo(dcIsOnB()), freqEnterRead(0, DUAL_ENTRY_FREQ_N, false)));
}

static void dualEntryDigit(int keyval)
{
	if (directChannelNumber == DUAL_ENTRY_FREQ)
	{
		if (uiDataGlobal.FreqEnter.index >= DUAL_ENTRY_FREQ_N)
		{
			return;
		}

		voicePromptsInit();
		voicePromptsAppendPrompt(PROMPT_0 + keyval);

		if (uiDataGlobal.FreqEnter.index == 2)
		{
			voicePromptsAppendPrompt(PROMPT_POINT);
		}

		voicePromptsPlay();
		uiDataGlobal.FreqEnter.digits[uiDataGlobal.FreqEnter.index] = (char)('0' + keyval);
		uiDataGlobal.FreqEnter.index++;

		if (uiDataGlobal.FreqEnter.index == DUAL_ENTRY_FREQ_N)
		{
			// стоково: восьма цифра -- підтвердження; недопустима частота -- остання цифра стирається, звук помилки (у dualEntryApplyFreq)
			if (dualEntryApplyFreq())
			{
				dualEntryEnd();
			}
			else
			{
				uiDataGlobal.FreqEnter.index--;
				uiDataGlobal.FreqEnter.digits[uiDataGlobal.FreqEnter.index] = '-';
			}
		}
		return;
	}

	int n = ((directChannelNumber * 10) + keyval);

	if (n > (int)DC_CH_MAX)
	{
		soundSetMelody(MELODY_ERROR_BEEP);   // номерів більше 1024 нема -- цифру не беремо
		return;
	}

	directChannelNumber = n;
	voicePromptsInit();
	voicePromptsAppendPrompt(PROMPT_0 + keyval);
	voicePromptsPlay();
}

// true -- клавішу оброблено (набір почато / триває / завершено).
static bool dualEntryKey(uiEvent_t *ev)
{
	if ((dcIsEnabled() == false) || (menuSystemGetCurrentMenuNumber() != UI_CHANNEL_MODE) || uiDataGlobal.displayChannelSettings)
	{
		return false;
	}

	bool sk = (BUTTONCHECK_DOWN(ev, BUTTON_SK1) || BUTTONCHECK_DOWN(ev, BUTTON_SK2));
	int keyval = (sk ? 99 : menuGetKeypadKeyValue(ev, true));

	if (directChannelNumber == 0)
	{
		if (keyval >= 10)
		{
			return false;
		}

		bool freq = dualCardIsVfo(dcPointerB());   // R98-FIX4 Б3: картка VFO з покажчиком (A або B) -- введення частоти

		if (keyval == 0)
		{
			return true;   // перша цифра 0: номерів каналів з 0 нема, частот < 100 МГц -- теж (як у стоку); довге 0 (без звуку) прийде окремою подією
		}

		dualSuspend();   // чергування стоп (як для будь-якої клавіші), режим лишається

		if (freq)
		{
			freqEnterReset();
			directChannelNumber = DUAL_ENTRY_FREQ;
		}

		dualEntryDigit(keyval);
		uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
		return true;
	}

	// набір триває
	if ((KEYCHECK_LONGDOWN(ev->keys, KEY_0) || KEYCHECK_LONGDOWN(ev->keys, KEY_8)) && (sk == false))
	{
		directChannelNumber = 0;   // стоково довге 0/8 теж скидає набір; далі -- стокова дія (без звуку / пеленг)
		freqEnterReset();
		return false;
	}

	if (keyval < 10)
	{
		dualEntryDigit(keyval);
	}
	else if ((sk == false) && KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		bool ok = ((directChannelNumber == DUAL_ENTRY_FREQ) ? dualEntryApplyFreq() : dualEntryApplyChannel(directChannelNumber));

		if (ok || (directChannelNumber != DUAL_ENTRY_FREQ))
		{
			if (ok == false)
			{
				soundSetMelody(MELODY_ERROR_BEEP);   // номер не використовується / канал A не з поточної зони -- нічого не змінюється
			}
			dualEntryEnd();
		}
		// недопустима частота -- як у стоку: цифри лишаються (звук помилки дав uiVFOModeDualFreqEnter)
	}
	else if ((sk == false) && KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		if (directChannelNumber == DUAL_ENTRY_FREQ)
		{
			soundSetMelody(MELODY_NACK_BEEP);   // як скасування введення частоти в стоковому екрані VFO
		}
		dualEntryEnd();
	}
	else if ((sk == false) && KEYCHECK_PRESS(ev->keys, KEY_FRONT_DOWN))
	{
		// ▼ -- стерти останню цифру (як KEY_DECREASE у стоковому введенні частоти); стерли все -- набір завершено
		if (directChannelNumber == DUAL_ENTRY_FREQ)
		{
			if (uiDataGlobal.FreqEnter.index > 0)
			{
				uiDataGlobal.FreqEnter.index--;
				uiDataGlobal.FreqEnter.digits[uiDataGlobal.FreqEnter.index] = '-';
			}

			if (uiDataGlobal.FreqEnter.index == 0)
			{
				dualEntryEnd();
			}
		}
		else
		{
			directChannelNumber /= 10;

			if (directChannelNumber == 0)
			{
				dualEntryEnd();
			}
		}
	}
	// решта (ручка, ▲, довге ▼, SK1/SK2 + ..., *, #) -- з'їдається: картки й канали під час набору не перемикаються

	uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
	return true;
}

// Рядок 2 картки під час набору: «До 12_» (номер каналу) або «435.12---» (частота, як у стоковому екрані VFO: 3 цифри МГц, крапка, 5 цифр).
static void dualEntryText(char *l2, size_t size)
{
	if (directChannelNumber == DUAL_ENTRY_FREQ)
	{
		const char *d = uiDataGlobal.FreqEnter.digits;

		snprintf(l2, size, "%c%c%c.%c%c%c%c%c", d[0], d[1], d[2], d[3], d[4], d[5], d[6], d[7]);
	}
	else
	{
		snprintf(l2, size, "%.8s %d_", currentLanguage->gotoChannel, directChannelNumber);
	}
}

// ---- R98-FIX3 Б: шумодав FM з режиму -- SK1 + ручка (у стоку на екрані каналу SK1 + ручка -- та сама зміна каналу, що й без SK1; у режимі канал вибирає
// ручка без SK1, тож комбінація вільна). Утримання SK1 показує стокову панель деталей -- вона не заважає: сповіщення шумодава малюється поверх неї, після
// відпускання SK1 панель ховається, як завжди.
static bool dualIsSquelchKey(const uiEvent_t *ev)
{
	return (dcIsEnabled() && (menuSystemGetCurrentMenuNumber() == UI_CHANNEL_MODE) && (directChannelNumber == 0) &&
			BUTTONCHECK_DOWN(ev, BUTTON_SK1) && (BUTTONCHECK_DOWN(ev, BUTTON_SK2) == false) &&
			((ev->keys.key == KEY_ROTARY_INCREMENT) || (ev->keys.key == KEY_ROTARY_DECREMENT)));
}

// Картка з покажчиком (A == B -- це один канал, A): рація стає на неї (чергування -- пауза, як після будь-якої клавіші), далі -- параметр прийому картки.
// R98-FIX5 А2: FM -- стоковий крок шумодава (channelSquelchStep); DMR -- ТГ зі списку прийому картки (канал -- стоковий channelTgStep, індекс B -- свій, s_dualTgIdxB;
// VFO -- uiVFOModeDualTgStep, індекс SETTINGS_VFO_A_MODE + VFO); немає списку прийому (лише контакт каналу) -- звук помилки.
// Збереження: A -- у канальному буфері (як у стоку; копія R98-FIX2 Є); B = канал -- у робочій копії B (R98-FIX5 А5); VFO -- запис VFO + settingsSetVFODirty().
static void dualSquelchStep(int dir)
{
	bool toB = (dcPointerB() && (dualSingle() == false));

	dualSuspend();

	if (toB != dcIsOnB())
	{
		dualTune(toB);
	}

	if (currentChannelData->chMode != RADIO_MODE_ANALOG)
	{
		if ((currentChannelData->rxGroupList == 0) || (currentRxGroupData.name[0] == 0) || (currentRxGroupData.NOT_IN_CODEPLUG_numTGsInGroup < 1))
		{
			soundSetMelody(MELODY_ERROR_BEEP);   // лише контакт каналу -- кроку нема
			return;
		}

		if (dualOnVfoNow())
		{
			uiVFOModeDualTgStep(dualCardVfo(dcIsOnB()), dir);
			uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
			uiChannelModeUpdateScreen(0);
			announceItem(PROMPT_SEQUENCE_CONTACT_TG_OR_PC, PROMPT_THRESHOLD_3);
		}
		else
		{
			channelTgStep(dir);

			if (dcIsOnB())
			{
				s_dualTgIdxB = (uint8_t)nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE];
			}
		}
		return;
	}

	channelSquelchStep(dir);

	if (dualOnVfoNow())
	{
		settingsSetVFODirty();   // картка VFO (A або B, R98-FIX4 Б3) -- запис VFO
	}
}

// R98-FIX4 А2: «A для повернення» придатний (канал використовується й є в ПОТОЧНІЙ зоні -- зону не перемикаємо, А3; VFO -- завжди) і не збігається з B.
// Тоді: A = він, покажчик на B, рація лишається на B (поточна ціль -- це B). Повертає true, якщо застосовано.
static bool dualApplyReturnA(uint8_t rt, uint16_t ri)
{
	int pos = -1;

	if (dcSameTarget(rt, ri, dcTypeB(), dcChannelB()))
	{
		return false;
	}

	if (rt == DC_TYPE_CHANNEL)
	{
		if (codeplugAllChannelsIndexIsInUse(ri) == false)
		{
			return false;   // колишній A видалено -- A = поточний
		}

		bool allCh = CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone);

		pos = (allCh ? (int)ri : dcFindPos(currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone, ri, dualZoneChannelAt, NULL));

		if (pos < 0)
		{
			return false;   // колишній A не в поточній зоні (зону змінили) -- A = поточний
		}
	}

	bool bufHadB = (currentChannelData == &channelScreenChannelData);   // рація зараз на каналі == B (канал) -- канальний буфер тримає B

	dcSetOnB(true);
	dcSetPointerB(true);
	dcSetTypeA(rt);

	// R98-FIX6 Б1: рація лишається на B (поточна ціль): канальний буфер -- уже робоча копія B (з незбереженими правками звичайного режиму), ТГ A
	// невідомий -- той самий індекс, що зараз (інакше перший перехід на A взяв би індекс попереднього сеансу).
	s_dualTgIdxA = nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE];

	if (bufHadB)
	{
		s_dualBKeep = 1U;
		s_dualTgIdxB = (uint8_t)nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE];   // ТГ B -- той, що стоїть зараз (рація на B)
	}

	if (rt == DC_TYPE_CHANNEL)
	{
		codeplugSetLastUsedChannelInZone(currentZone.NOT_IN_CODEPLUGDATA_indexNumber, (int16_t)pos);   // як dualLeaveOnB/набір FIX3
		// дані A -- туди, звідки їх візьме dualTune(false): буфер тримає B -> копія A (scanNextChannelData, R98-FIX2 Є); B = VFO -> сам канальний буфер
		codeplugChannelGetDataForIndex(ri, (bufHadB ? &scanNextChannelData : &channelScreenChannelData));
	}

	return true;
}

// R98-FIX4: увімкнути режим з поточної цілі typeCur (канал зони з екрана каналів або VFO A/B з екрана VFO) -- одна логіка для пункту меню й гарячих
// клавіш обох екранів. Перевірка пари (B не задано -> авто B = A; B видалено -> помилка), «A для повернення» (частина А), запис блоку 18 одразу.
static bool dualEnable(uint8_t typeCur)
{
	uint16_t idxCur = ((typeCur == DC_TYPE_CHANNEL) ? dualChannelA() : 0U);

	dualBReset();      // R98-FIX5: копія B і ТГ B попереднього сеансу не переносяться
	s_dualZoneB = 0U;

	dcSetTypeA(typeCur);
	dcSetOnB(false);

	dcPairCheck_t chk = dualCheckPair();

	if (chk == DC_PAIR_NO_B)
	{
		// R98-FIX1: B не задано -- автоматично B = поточна ціль A (канал: абсолютний індекс; R98-FIX4 Б1: VFO -- той самий VFO), запис блоку 18 одразу.
		// Далі -- як A==B (R97-FIX6): помилки й звуку нема. Якщо в A немає допустимого абсолютного індексу -- нічого не вигадуємо:
		// лишається «B не задано», режим не вмикається.
		if (typeCur != DC_TYPE_CHANNEL)
		{
			dualBReset();
			dcSetTypeB(typeCur);
			chk = dualCheckPair();
		}
		else if ((idxCur >= DC_CH_MIN) && (idxCur <= DC_CH_MAX) && codeplugAllChannelsIndexIsInUse(idxCur))
		{
			dualBReset();   // R98-FIX3 Б / R98-FIX5 А5
			(void)dcSetChannelB(idxCur, true);
			chk = dualCheckPair();
		}
	}

	if (chk != DC_PAIR_OK)
	{
		dualShowPairError(chk);   // режим не стартує (B не задано / видалено); A==B -- не помилка (R97-FIX6)
		return false;
	}

	// R98-FIX4 А2: поточна ціль -- це B (вийшли з режиму на картці B) і є «A для повернення» -- картки як до виходу
	uint8_t rt;
	uint16_t ri;

	if (dcSameTarget(typeCur, idxCur, dcTypeB(), dcChannelB()) && dcGetReturnA(&rt, &ri))
	{
		(void)dualApplyReturnA(rt, ri);
	}

	dcSetTxHold(false);
	(void)dcSetEnabled(true, true);
	s_dualKeyMs = 0U;
	dualAutoResume();

	if ((dualIsRunning() == false) && (menuSystemGetCurrentMenuNumber() == UI_CHANNEL_MODE))
	{
		uiChannelModeUpdateScreen(0);   // A==B: чергування не стартує, але екран режиму потрібен одразу
	}

	return true;
}

// R98-FIX4 Б1: увімкнення з екрана VFO (довге ▼ або пункт швидкого меню VFO). Двигун і екран режиму -- у режимі каналів: A = поточний VFO, далі --
// стоковий перехід на екран каналів (зона, канал, «останній канал зони» не змінюються; перший запуск екрана бачить A = VFO і налаштовує його ізольовано).
bool uiChannelModeDualEnableFromVfo(uint8_t vfo)
{
	if (dualEnable((vfo == 1U) ? (uint8_t)DC_TYPE_VFO_B : (uint8_t)DC_TYPE_VFO_A) == false)
	{
		return false;
	}

	menuSystemPopAllAndDisplaySpecificRootMenu(UI_CHANNEL_MODE, true);   // перший запуск екрана каналів: рація на картці VFO -- рання гілка (без читання каналу зони)

	if (menuSystemGetCurrentMenuNumber() == UI_CHANNEL_MODE)
	{
		s_dualKeyMs = 0U;
		dualAutoResume();   // одразу екран режиму (без проміжного стокового екрана каналу)

		if (dualIsRunning() == false)
		{
			uiChannelModeUpdateScreen(0);
		}
	}

	uiNotificationShowShort(1500U, currentLanguage->dual_on, true);
	return true;
}

// Увімкнути/вимкнути режим -- ОДНА логіка для пункту швидкого меню й гарячої клавіші (довге ▼): перевірка пари (B не задано / канал B
// видалено / B збігається з A -- сповіщення й сигнал помилки, режим не стартує), запис блоку, старт/зупинка чергування.
// notify -- коротке сповіщення «вкл/вимк» (гаряча клавіша; у меню зміну видно і так).
static void dualSetMode(bool on, bool notify)
{
	if (on)
	{
		if (dualEnable((uint8_t)DC_TYPE_CHANNEL) == false)   // R98-FIX4: з екрана каналів A -- канал зони
		{
			return;
		}
	}
	else
	{
		dualDisable();

		if (menuSystemGetCurrentMenuNumber() == UI_CHANNEL_MODE)   // R98: «лишитись на VFO» перейшло на VFO-екран -- канальний екран не малюємо
		{
			uiChannelModeUpdateScreen(0);
		}
	}

	if (notify && (menuSystemGetCurrentMenuNumber() == UI_CHANNEL_MODE))
	{
		uiNotificationShowShort(1500U, (on ? currentLanguage->dual_on : currentLanguage->dual_off), true);
	}
}

// Гаряча клавіша -- довге ▼ без SK2/SK1 на екрані каналу: перемкнути режим (ввімкнено -> вимкнути, інакше -> ввімкнути).
static void dualHotkeyToggle(void)
{
	dualSetMode((dcIsEnabled() == false), true);
}

// Пункти швидкого меню (викликається вже на екрані каналу).
static void dualQuickMenuApply(void)
{
	if (dcMenuValue() == dcIsEnabled())
	{
		return;
	}

	dualSetMode(dcMenuValue(), false);
}

// PTT на екрані каналу під час чергування (applicationMain.c): канал передачі -- за станом (прийом/утримання -- де рація зараз,
// інакше -- за покажчиком); режим НЕ вимикається, передача стартує цим же натисканням, після неї -- утримання «Затр. скан.».
bool uiChannelModeDualPrepareTx(void)
{
	if ((dualIsRunning() == false) || (menuSystemGetCurrentMenuNumber() != UI_CHANNEL_MODE))
	{
		return false;
	}

	bool toB = dcTxOnB((uiDataGlobal.Scan.state != SCAN_STATE_SCANNING), dcIsOnB(), dcPointerB());

	if (toB != dcIsOnB())
	{
		dualTune(toB);
	}

	dcSetTxHold(true);
	uiDataGlobal.Scan.active = false;   // екран передачі однаково скидає; scanType лишається -- dualAutoResume() поверне режим
	return true;
}

// ---- екран режиму (R97-FIX6): шапка (y=0..9), дві картки A/B на весь простір під нею. Екран 160x128 ----
// Висоти шрифтів: FONT_SIZE_1 = 8 (6 px завширшки), FONT_SIZE_3 = 16 (8 px), FONT_SIZE_4 = 32 (16 px). Шапка займає y=0..DISPLAY_Y_POS_BAR-1 (=0..9).
// Таблиця координат -- у звіті r97-fix6-result.md.
#define DW_CARD_X        1                                 // картка: рамка x=1..158
#define DW_CARD_W        158
#define DW_CARD_H        57                                // y..y+56
#define DW_CARD_A_Y      (DISPLAY_Y_POS_BAR + 1)           // 11: одразу під рядком шапки
#define DW_CARD_B_Y      (DW_CARD_A_Y + DW_CARD_H + 3)     // 71; картка B закінчується на y=127 (останній рядок екрана)
// R98-FIX6 В/Г: «дві рівні картки, 4 рядки». Рамка: обрана картка -- 2 px кольором виділення теми (THEME_ITEM_BG_MENU_ITEM_SELECTED), інша -- 1 px
// приглушеним кольором декору (THEME_ITEM_FG_DECORATION). Поле вмісту однакове для обох: x=DW_IN_L..DW_IN_R (по 3 px від рамки з кожного боку --
// однакові поля), y+3..y+53. Рядки: 1 і 2 -- 8x16, 3 і 4 -- 8 px; інтервал між рядками однаковий -- 1 px. Таблиця координат -- у r98-fix6-result.md.
#define DW_FRAME_SEL     2                                 // товщина рамки обраної картки
#define DW_IN_L          4                                 // перший стовпчик вмісту (рамка x=1..2, зазор x=3)
#define DW_IN_R          155                               // останній стовпчик вмісту (зазор x=156, рамка x=157..158)
#define DW_ROW1_DY       3                                 // рядок 1 (8x16): літера + «номер назва» ліворуч, значки праворуч, y+3..18
#define DW_ROW2_DY       20                                // рядок 2 (8x16): абонент / призначення / «FM частота» / поле набору, y+20..35
#define DW_ROW3_DY       37                                // рядок 3 (6x8): TS/CC/ТГ або тони ліворуч; режим + потужність (або відстань + стрілка під час виклику) праворуч, y+37..44
#define DW_ROW4_DY       46                                // рядок 4 (8 px): RX + S-метр (лише активна картка), y+46..53
#define DW_LET_W         10                                // рамка літери 10x16: x=DW_IN_L..13, y+3..18 (обрана -- залита, інша -- контур)
#define DW_LET_X         (DW_IN_L + 1)                     // літера 8x16: x=5..12
#define DW_ROW1_TX       (DW_IN_L + DW_LET_W + 2)          // 16: «номер назва» -- одразу за рамкою літери
#define DW_ICON_DY       7                                 // значки рядка 1 (висота 8..9) -- по вертикальному центру рядка 1: y+7..15
#define DW_ICON_GAP      2                                 // зазор між значками і перед ними
#define DW_LOCK_W        10                                // замок AES 10x9
#define DW_UN_W          22                                // значок SMS DMR: «D» 6 + 1 + конверт 8 + 1 + число 6
#define DW_AP_W          14                                // маркер APRS (інвертований бокс «A»+число) 14x9
#define DW_AP_H          9
#define DW_ROW3_MAX      25                                // (DW_IN_R + 1 - DW_IN_L) / 6
#define DW_ARROW_DY      36                                // комірка стрілки 10x10 (lcDistArrowAfter): y+36..45 -- між рядками 2 і 4, по центру рядка 3
#define DW_ARROW_CELL    10
#define DW_ARROW_GAP     2                                 // = LC_ARROW_GAP (lc_distance.h); свій, бо заголовок дає макроси лише з LC_DISTANCE
#define DW_R3_SIZE       24                                // буфер правої частини рядка 3 (= LC_DIST_LABEL_SIZE 16 + 8)
#define DW_METER_H       8
#define DW_TAG_W         14                                // мітка «RX» 14x8, x=4..17
#define DW_METER_SEG_W   10
#define DW_METER_STEP    12
#define DW_METER_SEGS    11                                // 1..9 -- S1..S9 (стокова шкала 4 дБ), 10 -- S9+10 дБ, 11 -- S9+20 дБ
#define DW_METER_X       (DW_IN_R + 1 - (((DW_METER_SEGS - 1) * DW_METER_STEP) + DW_METER_SEG_W))   // 26: сегменти вирівняні до правого краю вмісту, x=26..155
#define DW_METER_HOT     2                                 // R98-FIX3 В: скільки останніх сегментів -- кольором «понад S9» (червоні): S9+10 і S9+20

// Текст абонента за тим самим правилом, що «останній абонент» звичайного екрана (contactDisplayPriority).
static void dualCallerText(char *text17)
{
	LinkItem_t *item = LinkHead;
	bool useTA = false;

	switch (nonVolatileSettings.contactDisplayPriority)
	{
		case CONTACT_DISPLAY_PRIO_CC_DB_TA:
		case CONTACT_DISPLAY_PRIO_DB_CC_TA:
			useTA = ((strncmp(item->contact, "ID:", 3) == 0) && (item->talkerAlias[0] != 0x00));
			break;
		default:
			useTA = (item->talkerAlias[0] != 0x00);
			break;
	}

	snprintf(text17, 17, "%.16s", (useTA ? item->talkerAlias : item->contact));
	(void)chomp(text17);
}

// Смуга активності картки (рядок 4, R98-FIX6 Г): мітка «RX» ліворуч + сегментований S-метр, вирівняний до правого краю вмісту (11 сегментів). Лише для активної
// картки; перемальовує тільки свою ділянку. Сегменти 1..9 -- стокова шкала (SMETER_S0 + 4 дБ на S-одиницю, S9 = SMETER_S9), 10 і 11 -- S9+10 і S9+20 дБ (червоні).
static void dualMeterRow(int16_t y)
{
	int rssi = trxGetRSSIdBm(RADIO_DEVICE_PRIMARY);
	int16_t my = (y + DW_ROW4_DY);

	displayThemeApply(THEME_ITEM_FG_DEFAULT, THEME_ITEM_BG);
	displayFillRect(DW_IN_L, my, (DW_IN_R + 1 - DW_IN_L), DW_METER_H, true);

	displayThemeApply(THEME_ITEM_FG_CHANNEL_NAME, THEME_ITEM_BG);
	displayFillRect(DW_IN_L, my, DW_TAG_W, DW_METER_H, false);
	displayPrintCore((DW_IN_L + 1), my, "RX", FONT_SIZE_1, TEXT_ALIGN_LEFT, true);

	for (int i = 1; i <= DW_METER_SEGS; i++)
	{
		int16_t sx = (DW_METER_X + ((i - 1) * DW_METER_STEP));
		int thr = ((i <= 9) ? (SMETER_S0 + (i * 4)) : (SMETER_S9 + ((i - 9) * 10)));

		if (rssi >= thr)
		{
			displayThemeApply(((i > (DW_METER_SEGS - DW_METER_HOT)) ? THEME_ITEM_FG_RSSI_BAR_S9P : THEME_ITEM_FG_RSSI_BAR), THEME_ITEM_BG);
			displayFillRect(sx, my, DW_METER_SEG_W, DW_METER_H, false);
		}
		else
		{
			displayThemeApply(THEME_ITEM_FG_DECORATION, THEME_ITEM_BG);
			displayDrawRect(sx, my, DW_METER_SEG_W, DW_METER_H, true);
		}
	}

	displayThemeResetToDefault();
}

// Призначення передачі (PTT) для картки каналу -- ті самі правила, що в стоковому завантаженні каналу (uiChannelModeLoadChannelData) і updateTrxID():
//  1) перекриття ТГ (nonVolatileSettings.overrideTG != 0; ставиться SK2 під час прийому, вибором контакту/ПК, «Копіювати у VFO») -- ГЛОБАЛЬНЕ: стокове
//     завантаження каналу застосовує його до БУДЬ-ЯКОГО каналу, а при зміні каналу ручкою не скидається (скидають лише клавіші ТГ ◀/▶, зміна зони,
//     меню кодплага), тож PTT з будь-якої картки піде з ним -- показуємо його на ОБОХ DMR-картках (R98 Д3);
//  2) список прийому каналу (rxGroupList): контакт на позиції tgIdx -- вибраний ТГ картки (R98-FIX5 А2; поза списком -> перший);
//  3) інакше контакт самого каналу. codeplugContactGetDataForIndex() для 0/недійсного індексу ПОВЕРТАЄ «TG 9» -- саме так рація й передає (ТГ 9),
//     тож «контакт не заданий» показуємо чесно як ТГ 9, а не прочерком.
// out -- до 16 символів (ім'я контакту або «TG n»/«PC n»); *numOnly -- true, якщо ім'я порожнє й показано лише тип+номер. Повертає ID: (прапорець<<24)|номер.
static uint32_t dualDestination(const CodeplugChannel_t *ch, char *out, bool *numOnly, uint8_t *tsFlags, int16_t tgIdx)
{
	CodeplugContact_t ct;
	uint32_t packed;
	bool pc;

	out[0] = 0;
	*numOnly = false;
	*tsFlags = CODEPLUG_CONTACT_FLAG_NO_TS_OVERRIDE;   // перекриття ТГ -- ТС контакту не діє (trx.c)

	if (nonVolatileSettings.overrideTG != 0)
	{
		packed = nonVolatileSettings.overrideTG;
		pc = ((packed >> 24) != TG_CALL_FLAG);   // як uiUtilityBuildTgOrPCDisplayName(): не ТГ -- приватний

		if ((pc == false) && ((packed & 0x00FFFFFFU) == ALL_CALL_VALUE))
		{
			snprintf(out, 17, "%.16s", currentLanguage->all_call);
			return packed;
		}

		if (codeplugContactIndexByTGorPC((packed & 0x00FFFFFFU), (pc ? CONTACT_CALLTYPE_PC : CONTACT_CALLTYPE_TG), &ct,
				(uint8_t)((codeplugChannelGetFlag((CodeplugChannel_t *)ch, CHANNEL_FLAG_TIMESLOT_TWO) != 0) ? 2 : 1)) != -1)
		{
			codeplugUtilConvertBufToDisplayString(ct.name, out, 16);
		}
	}
	else
	{
		int num;
		int ci = codeplugRxGroupGetContactAt(ch->rxGroupList, tgIdx, &num);   // R98-FIX5 А2: вибраний ТГ САМЕ ЦІЄЇ картки (dualCardTgIdx)

		if (ci == 0)
		{
			ci = ch->contact;
		}

		(void)codeplugContactGetDataForIndex(ci, &ct);   // недійсний -> «TG 9» (як на PTT)
		*tsFlags = ct.reserve1;
		packed = codeplugContactGetPackedId(&ct);
		pc = (ct.callType == CONTACT_CALLTYPE_PC);
		codeplugUtilConvertBufToDisplayString(ct.name, out, 16);
	}

	if (out[0] == 0)
	{
		snprintf(out, 17, "%s %u", (pc ? currentLanguage->pc : currentLanguage->tg), (unsigned)(packed & 0x00FFFFFFU));
		*numOnly = true;
	}

	return packed;
}

// R98 Д2: ЕФЕКТИВНИЙ ТС передачі (1/2) -- те саме правило, що trxUpdateTsForCurrentChannelWithSpecifiedContact() (trx.c), але ЛИШЕ читання:
//  - немає перекриття ТГ і контакт не має NO_TS_OVERRIDE: ТС ручного вибору, якщо користувач перемкнув його після вибору контакту (tsIsContactHasBeenOverridden),
//    інакше ТС контакту (біт TS_OVERRIDE_TIMESLOT_MASK);
//  - інакше: ручне перекриття ТС каналу (tsGetManualOverride), інакше ТС запису каналу.
// tsFlags -- reserve1 контакту призначення (dualDestination). Канал -- CHANNEL_CHANNEL (картки каналів).
static uint8_t dualEffectiveTs(const CodeplugChannel_t *ch, uint8_t tsFlags)
{
	Channel_t chan = dualChanOf(ch);   // R98: VFO A/B або канал
	int8_t man = tsGetManualOverride(chan);
	uint8_t chTs = ((codeplugChannelGetFlag((CodeplugChannel_t *)ch, CHANNEL_FLAG_TIMESLOT_TWO) != 0) ? 2U : 1U);

	if ((nonVolatileSettings.overrideTG == 0) && ((tsFlags & CODEPLUG_CONTACT_FLAG_NO_TS_OVERRIDE) == 0x00))
	{
		if (tsIsContactHasBeenOverridden(chan) && (man != 0))
		{
			return (uint8_t)man;
		}

		return (((tsFlags & CODEPLUG_CONTACT_FLAG_TS_OVERRIDE_TIMESLOT_MASK) != 0) ? 2U : 1U);
	}

	return ((man != 0) ? (uint8_t)man : chTs);
}

// R98-FIX6 Г: праворуч у рядку 3 -- режим («DMR»/«FM») і потужність ЦІЄЇ картки (потужність каналу, якщо задана в записі, інакше загальна -- як стокова шапка:
// рівень = libreDMR_Power - 1 або nonVolatileSettings.txPowerLevel; VFO -- завжди загальна).
static void dualModePowerText(char *out, size_t size, const CodeplugChannel_t *rec)
{
	uint8_t lvl = ((rec->libreDMR_Power != 0x00) ? (uint8_t)(rec->libreDMR_Power - 1U) : nonVolatileSettings.txPowerLevel);

	snprintf(out, size, "%s %s%s", ((rec->chMode == RADIO_MODE_DIGITAL) ? "DMR" : "FM"), UI_SAFE_STR(getPowerLevel(lvl)), UI_SAFE_STR(getPowerLevelUnit(lvl)));
}

// R98-FIX6 Г: під час виклику праворуч у рядку 3 замість режиму/потужності -- відстань до кореспондента (R98-FIX2 К1: ті самі умови, що в підписі «[відстань]»
// шапки виклику) і, якщо азимут визначений, стрілка напрямку біля правого краю. false -- відстані нема (тоді -- режим і потужність).
static bool dualDistText(char *out, size_t size, bool callerHere, uint16_t *bearing, bool *bearingKnown)
{
	*bearing = 0U;
	*bearingKnown = false;
	out[0] = 0;

#if defined(LC_DISTANCE)
	if (callerHere && (LinkHead != NULL) && (LinkHead->locationLat <= 90) && settingsLocationIsValid() &&
			lcDistLabel(out, size, true, settingsLocationGetLatitude(), settingsLocationGetLongitude(), LinkHead->locationLat, LinkHead->locationLon, bearing, bearingKnown))
	{
		return true;
	}
	out[0] = 0;
#else
	(void)size;
	(void)callerHere;
#endif
	*bearingKnown = false;
	return false;
}

// R98-FIX2 К2: один тон для рядка 3 картки FM: CTCSS «67.0» або DCS у стоковому форматі «D023N»/«D023I» (dcsPrintf); mark -- префікс «R»/«T» або порожній.
// Без тону -- порожньо (0). Повертає довжину.
static size_t dualToneOne(char *dst, size_t size, const char *mark, uint16_t tone)
{
	CodeplugCSSTypes_t type = codeplugGetCSSType(tone);

	dst[0] = 0;

	if (type == CSS_TYPE_CTCSS)
	{
		return (size_t)snprintf(dst, size, "%s%d.%d", mark, (tone / 10), (tone % 10));
	}

	if (type & CSS_TYPE_DCS)
	{
		size_t n = (size_t)snprintf(dst, size, "%s", mark);

		return (n + dcsPrintf((dst + n), (size - n), NULL, tone));
	}

	return 0U;
}

// R98-FIX2 К2: рядок 3 картки FM -- тони прийому і передачі та смуга (найдовший випадок -- 19 символів): однакові -- «67.0 25k»; різні -- «R67.0 T88.5 25k»;
// лише один -- з позначкою «R»/«T»; без тонів -- лише смуга. Найдовший випадок «R254.1 T254.1 12.5k» = 19 символів.
static void dualFmToneLine(char *l3, size_t size, uint16_t rxTone, uint16_t txTone, bool bw25)
{
	char r[10];
	char t[10];
	bool same = (rxTone == txTone);
	size_t nr = dualToneOne(r, sizeof(r), (same ? "" : "R"), rxTone);
	size_t nt = (same ? 0U : dualToneOne(t, sizeof(t), "T", txTone));

	if (same || (nt == 0U))
	{
		t[0] = 0;
	}

	snprintf(l3, size, "%s%s%s%s%s", r, (((nr != 0U) && (nt != 0U)) ? " " : ""), t, (((nr != 0U) || (nt != 0U)) ? " " : ""), (bw25 ? "25k" : "12.5k"));
}

// R98-FIX5 Б2: дані картки для показу -- те, що рація справді використає: правки в пам'яті (A -- канальний буфер або копія scanNextChannelData, R98-FIX2 Є;
// B = канал -- робоча копія B, А5), якщо копія та сама (назва й частоти збігаються з кодплагом, як dualBCopyValid), інакше запис з кодплага (tmp).
static const CodeplugChannel_t *dualCardMem(bool isB, const CodeplugChannel_t *tmp)
{
	const CodeplugChannel_t *m = NULL;

	if (dualSingle())
	{
		isB = false;   // A == B -- одна картка (A)
	}

	if (isB)
	{
		if (dualBufHoldsB())
		{
			m = &channelScreenChannelData;
		}
		else if (s_dualBKeep != 0U)
		{
			m = (dcAIsVfo() ? &channelScreenChannelData : &scanNextChannelData);
		}
	}
	else if (dcAIsVfo() == false)
	{
		m = (dualBufHoldsB() ? &scanNextChannelData : &channelScreenChannelData);
	}

	if ((m != NULL) && (memcmp(m->name, tmp->name, sizeof(tmp->name)) == 0) && (m->rxFreq == tmp->rxFreq) && (m->txFreq == tmp->txFreq))
	{
		return m;
	}

	return tmp;
}

// R98-FIX5 А2: вибраний ТГ у списку прийому картки. VFO -- свій індекс (SETTINGS_VFO_A_MODE + VFO); канал -- спільний індекс, якщо рація зараз на цій картці,
// інакше збережений вибір картки (A -- s_dualTgIdxA, B -- s_dualTgIdxB). A == B -- одна картка (A).
static int16_t dualCardTgIdx(bool isB, uint8_t vfoType)
{
	if (vfoType != DC_TYPE_CHANNEL)
	{
		return nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_VFO_A_MODE + ((vfoType == DC_TYPE_VFO_B) ? 1 : 0)];
	}

	if (dualSingle())
	{
		isB = false;
	}

	if (dcIsOnB() == isB)
	{
		return nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE];
	}

	return (isB ? (int16_t)s_dualTgIdxB : s_dualTgIdxA);
}

// Одна картка (R98-FIX6 В/Г, 4 рядки). Рамка: обрана -- 2 px кольором виділення теми, інша -- 1 px кольором декору. Рядок 1 (8x16): літера A/B у рамці
// (обрана -- залита) і «номер назва» / «VFO A частота» ліворуч; значки праворуч, вирівняні до правого краю: SMS «D» (картка-джерело), APRS «A» (картка B), замок AES.
// Рядок 2 (8x16): абонент / призначення / «FM частота» / поле набору. Рядок 3 (6x8): TS/CC/ТГ або тони ліворуч; праворуч -- режим і потужність картки, під час
// виклику -- відстань і стрілка. Рядок 4: RX + S-метр (лише активна; неактивна -- порожньо). Довгий текст обрізається до місця, що лишилось. Усе на стеку.
static void dualRenderRow(int16_t y, bool isB, uint16_t ch, uint8_t vfoType, bool selected, bool active, bool callerHere)
{
	CodeplugChannel_t tmp;
	const CodeplugChannel_t *rec = &tmp;
	char name[17];
	char l1[24];
	char l2[17];
	char l3[DW_ROW3_MAX + 1];
	char r3[DW_R3_SIZE];
	char letter[2];
	uint16_t bearing = 0U;
	bool bearingKnown = false;
	bool isVfo = (vfoType != DC_TYPE_CHANNEL);   // R98 В3: картка VFO -- дані прямо із запису VFO
	bool known = (isVfo || ((ch >= DC_CH_MIN) && (ch <= DC_CH_MAX) && codeplugAllChannelsIndexIsInUse(ch)));
	bool aes = false;

	name[0] = 0;
	l1[0] = 0;
	l2[0] = 0;
	l3[0] = 0;
	r3[0] = 0;

	if (known)
	{
		if (isVfo)
		{
			rec = &settingsVFOChannel[(vfoType == DC_TYPE_VFO_B) ? 1 : 0];
		}
		else
		{
			codeplugChannelGetDataForIndex(ch, &tmp);
			codeplugUtilConvertBufToDisplayString(tmp.name, name, 16);
			rec = dualCardMem(isB, &tmp);   // R98-FIX5 Б2: незбережені правки картки (потужність, режим, ...) -- видно на картці
#if defined(ENABLE_AES)
			aes = (uiChannelDataHasAes((CodeplugChannel_t *)rec) != 0);
#endif
		}

		if (rec->chMode == RADIO_MODE_DIGITAL)
		{
			bool numOnly;
			uint8_t tsFlags;
			uint32_t dest = dualDestination(rec, l2, &numOnly, &tsFlags, dualCardTgIdx(isB, vfoType));   // куди піде виклик (PTT) -- ТГ цієї картки
			size_t n;

			snprintf(l3, sizeof(l3), "TS%d CC%d", (int)dualEffectiveTs(rec, tsFlags), (int)rec->txColor);   // ефективний ТС передачі (Д2)
			n = strlen(l3);

			if (callerHere && (LinkHead != NULL))
			{
				snprintf((l3 + n), (sizeof(l3) - n), " %.11s", LinkHead->talkgroup);   // ТГ/ID призначення виклику, що триває
			}
			else if (numOnly == false)
			{
				char num[24];

				snprintf(num, sizeof(num), "%s%u", (((dest >> 24) != TG_CALL_FLAG) ? currentLanguage->pc : currentLanguage->tg), (unsigned)(dest & 0x00FFFFFFU));
				snprintf((l3 + n), (sizeof(l3) - n), " %s", num);
			}
		}
		else
		{
			int mhz = (int)(rec->rxFreq / 100000U);

			snprintf(l2, sizeof(l2), "FM %d.%05d", mhz, (int)(rec->rxFreq - ((uint32_t)mhz * 100000U)));
			dualFmToneLine(l3, sizeof(l3), rec->rxTone, rec->txTone, (codeplugChannelGetFlag((CodeplugChannel_t *)rec, CHANNEL_FLAG_BW_25K) != 0));   // R98-FIX2 К2
		}

		if (dualDistText(r3, sizeof(r3), callerHere, &bearing, &bearingKnown) == false)
		{
			dualModePowerText(r3, sizeof(r3), rec);
		}
	}
	// каналу нема (не задано/видалено) -- рядки порожні (без прочерків)

	if (callerHere)
	{
		dualCallerText(l2);   // хто зараз говорить -- замість ТГ каналу
	}

	if ((directChannelNumber != 0) && (isB == dcPointerB()))
	{
		dualEntryText(l2, sizeof(l2));   // R98-FIX3 А1: набір цифр для цієї картки -- поле введення в рядку 2
	}

	// рамка картки (R98-FIX6 В1): обрана -- 2 px кольором виділення теми; інша -- 1 px приглушеним кольором декору
	if (selected)
	{
		displayThemeApply(THEME_ITEM_BG_MENU_ITEM_SELECTED, THEME_ITEM_BG);
		for (int16_t k = 0; k < DW_FRAME_SEL; k++)
		{
			displayDrawRect((DW_CARD_X + k), (y + k), (DW_CARD_W - (2 * k)), (DW_CARD_H - (2 * k)), true);
		}
	}
	else
	{
		displayThemeApply(THEME_ITEM_FG_DECORATION, THEME_ITEM_BG);
		displayDrawRect(DW_CARD_X, y, DW_CARD_W, DW_CARD_H, true);
	}

	// літера в рамці: обрана -- залита рамка, літера кольором фону; інша -- контур
	letter[0] = (isB ? 'B' : 'A');
	letter[1] = 0;
	displayThemeApply(THEME_ITEM_FG_CHANNEL_NAME, THEME_ITEM_BG);

	if (selected)
	{
		displayFillRect(DW_IN_L, (y + DW_ROW1_DY), DW_LET_W, 16, false);
	}
	else
	{
		displayDrawRect(DW_IN_L, (y + DW_ROW1_DY), DW_LET_W, 16, true);
	}

	displayPrintCore(DW_LET_X, (y + DW_ROW1_DY), letter, FONT_SIZE_3, TEXT_ALIGN_LEFT, selected);

	if (isVfo)
	{
		// R98 В3: картка VFO -- «VFO A»/«VFO B» (латиниця) і частота
		int mhz = (int)(rec->rxFreq / 100000U);

		if (rec->chMode == RADIO_MODE_DIGITAL)
		{
			snprintf(l1, sizeof(l1), "VFO%c %d.%05d", ((vfoType == DC_TYPE_VFO_B) ? 'B' : 'A'), mhz, (int)(rec->rxFreq - ((uint32_t)mhz * 100000U)));   // 14 символів 8x16; у FM частота -- у рядку 2
		}
		else
		{
			snprintf(l1, sizeof(l1), "VFO %c", ((vfoType == DC_TYPE_VFO_B) ? 'B' : 'A'));
		}
	}
	else if (ch >= DC_CH_MIN)
	{
		snprintf(l1, sizeof(l1), ((name[0] != 0) ? "%u %s" : "%u"), (unsigned)ch, name);
	}

	// значки рядка 1 -- справа наліво від правого краю вмісту: замок, APRS, SMS; рядок 1 обрізається до місця, що лишилось
	unsigned un = uiUnreadCountCard(isB);
	unsigned aprsUn = (isB ? uiUnreadCount('A') : 0U);
	int16_t cur = (DW_IN_R + 1);
	int16_t lockX = -1;
	int16_t apX = -1;
	int16_t unX = -1;

	if (aes)
	{
		cur -= DW_LOCK_W;
		lockX = cur;
		cur -= DW_ICON_GAP;
	}

	if (aprsUn > 0U)
	{
		cur -= DW_AP_W;
		apX = cur;
		cur -= DW_ICON_GAP;
	}

	if (un > 0U)
	{
		cur -= DW_UN_W;
		unX = cur;
		cur -= DW_ICON_GAP;
	}

	size_t l1max = (size_t)((cur - DW_ROW1_TX) / 8);

	if (strlen(l1) > l1max)
	{
		l1[l1max] = 0;
	}

	displayPrintCore(DW_ROW1_TX, (y + DW_ROW1_DY), l1, FONT_SIZE_3, TEXT_ALIGN_LEFT, false);

#if defined(ENABLE_AES)
	if (lockX >= 0)
	{
		uiDrawAesIconAt(lockX, (y + DW_ICON_DY));   // замок -- на картці каналу, що має ключ
	}
#endif

	if (apX >= 0)
	{
		char ap[3];

		ap[0] = 'A';
		ap[1] = ((aprsUn > 9U) ? '+' : (char)('0' + aprsUn));
		ap[2] = 0;
		displayThemeApply(THEME_ITEM_FG_CHANNEL_NAME, THEME_ITEM_BG);
		displayFillRect(apX, (y + DW_ICON_DY), DW_AP_W, DW_AP_H, false);
		displayPrintCore((apX + 1), (y + DW_ICON_DY + 1), ap, FONT_SIZE_1, TEXT_ALIGN_LEFT, true);
	}

	if (unX >= 0)
	{
		char num[2];
		int16_t ey = (y + DW_ICON_DY + 1);

		num[0] = ((un > 9U) ? '+' : (char)('0' + un));
		num[1] = 0;
		displayThemeApply(THEME_ITEM_FG_CHANNEL_NAME, THEME_ITEM_BG);
		displayPrintCore(unX, (y + DW_ICON_DY + 1), "D", FONT_SIZE_1, TEXT_ALIGN_LEFT, false);
		displayDrawRect((unX + 7), ey, 8, 6, true);
		displayDrawLine((unX + 7), ey, (unX + 11), (ey + 3), true);
		displayDrawLine((unX + 14), ey, (unX + 11), (ey + 3), true);
		displayPrintCore((unX + 16), (y + DW_ICON_DY + 1), num, FONT_SIZE_1, TEXT_ALIGN_LEFT, false);
	}

	displayThemeApply((callerHere ? THEME_ITEM_FG_CHANNEL_CONTACT_INFO : THEME_ITEM_FG_CHANNEL_CONTACT), THEME_ITEM_BG);
	displayPrintCore(DW_IN_L, (y + DW_ROW2_DY), l2, FONT_SIZE_3, TEXT_ALIGN_LEFT, false);

	// рядок 3: праворуч -- режим/потужність або відстань (+ стрілка біля правого краю); ліворуч -- решта ширини
	int16_t rw = (int16_t)(strlen(r3) * 6) + (bearingKnown ? (DW_ARROW_CELL + DW_ARROW_GAP) : 0);
	int16_t rx = (DW_IN_R + 1 - rw);
	size_t l3max = (size_t)(((rx - 6) - DW_IN_L) / 6);

	if (strlen(l3) > l3max)
	{
		l3[l3max] = 0;
	}

	displayThemeApply(THEME_ITEM_FG_CHANNEL_NAME, THEME_ITEM_BG);
	displayPrintCore(DW_IN_L, (y + DW_ROW3_DY), l3, FONT_SIZE_1, TEXT_ALIGN_LEFT, false);
	displayPrintCore(rx, (y + DW_ROW3_DY), r3, FONT_SIZE_1, TEXT_ALIGN_LEFT, false);

#if defined(LC_DISTANCE)
	if (bearingKnown)
	{
		// R98-FIX3 Г / R93: стрілка одразу після «відстань» (комірка 10x10 біля правого краю, та сама форма й центр, що в шапці виклику)
		lcDistArrow_t a;
		lcDistSpan_t tail = { .x0 = rx, .x1 = (int16_t)(rx + (strlen(r3) * 6)), .y = (int16_t)(y + DW_ARROW_DY), .h = 8 };
		lcDistSpan_t above = { .x0 = 0, .x1 = 0, .y = 0, .h = 0 };

		lcDistArrowAfter(&a, &tail, &above, (DW_IN_R + 1), bearing);
		displayThemeApply(THEME_ITEM_FG_CHANNEL_CONTACT_INFO, THEME_ITEM_BG);
		displayFillTriangle(a.g.tx, a.g.ty, a.g.lx, a.g.ly, a.g.nx, a.g.ny, true);
		displayFillTriangle(a.g.tx, a.g.ty, a.g.rx, a.g.ry, a.g.nx, a.g.ny, true);
		displayDrawLine(a.g.tx, a.g.ty, a.g.lx, a.g.ly, true);
		displayDrawLine(a.g.lx, a.g.ly, a.g.nx, a.g.ny, true);
		displayDrawLine(a.g.nx, a.g.ny, a.g.rx, a.g.ry, true);
		displayDrawLine(a.g.rx, a.g.ry, a.g.tx, a.g.ty, true);
	}
#endif

	if (active)
	{
		dualMeterRow(y);
	}

	displayThemeResetToDefault();
}

// Активність на екрані режиму: чергування -- state != SCANNING на картці, де рація (dcIsOnB()); A==B (режим не чергує) -- несуча на каналі, картка за покажчиком.
static bool dualActivity(bool *cardB)
{
	if (dualIsRunning())
	{
		*cardB = dcIsOnB();
		return (uiDataGlobal.Scan.state != SCAN_STATE_SCANNING);
	}

	*cardB = (dualSingle() ? dcPointerB() : dcIsOnB());
	return (dualSingle() && trxCarrierDetected(RADIO_DEVICE_PRIMARY));
}

// Оновлення S-метра в тіку: перемальовується лише смуга активної картки; true -- щось змінено в буфері (тік виконає один displayRender).
static bool dualRenderMeter(void)
{
	bool cardB = false;

	if (dualActivity(&cardB) == false)
	{
		return false;
	}

	dualMeterRow(cardB ? DW_CARD_B_Y : DW_CARD_A_Y);
	return true;
}

bool uiChannelModeDualScreenShown(void)
{
	return (dualIsRunning() || dualHoldScreen());
}

// R98-FIX1 В2: панель деталей каналу (SK1) при ввімкненому режимі: стоковий екран деталей ОБРАНОГО каналу (рація стоїть на ньому), але без S-метра
// в шапці (uiUtilityDrawRSSIBarGraph() не малює). Окремий предикат: uiChannelModeDualScreenShown() для панелі деталей лишається false,
// інакше тік RSSI (вище) малював би смугу режиму поверх панелі.
bool uiChannelModeDualDetailsShown(void)
{
	return (dcIsEnabled() && uiDataGlobal.displayChannelSettings && (menuSystemGetCurrentMenuNumber() == UI_CHANNEL_MODE));
}

// R98-FIX2 Д: вхідне SMS DMR прийнято на картці B? Так лише коли режим ввімкнено, рація стоїть на B і B != A (A == B -> картка A; режим вимкнено -> 0).
bool uiChannelModeDualOnCardB(void)
{
	return (dcIsEnabled() && dcIsOnB() && (dualBSameAsA() == false));
}

// R98-FIX1 Г: рація на B = VFO при ввімкненому режимі. Меню відкриваються з кореня «екран каналу», тож стокова логіка вважає, що діє на канал.
bool uiChannelModeDualOnVfo(void)
{
	return dualOnVfoNow();   // R98-FIX4 Б3: картка VFO -- B або A
}

// «Відро» ТС-перекриття (tsSetManualOverride) -- ті самі біти, що вибирають відро в trxUpdateTsForCurrentChannelWithSpecifiedContact(): обраний VFO -- його відро.
int uiChannelModeDualTsBucket(void)
{
	return (uiChannelModeDualOnVfo() ? (int)(CHANNEL_VFO_A + dualCardVfo(dcIsOnB())) : (int)CHANNEL_CHANNEL);
}

static void dualRenderScreen(void)
{
	bool cardB = false;
	bool active = dualActivity(&cardB);
	bool caller = (((uiDataGlobal.displayQSOState == QSO_DISPLAY_CALLER_DATA) || (uiDataGlobal.displayQSOState == QSO_DISPLAY_CALLER_DATA_UPDATE)) &&
			(trxGetMode() == RADIO_MODE_DIGITAL) && (HRC6000GetReceivedTgOrPcId() != 0) && (LinkHead != NULL) && (directChannelNumber == 0));
	bool selB = (dualSingle() ? dcPointerB() : dualSelectedIsB());

	if (caller && dualSingle())
	{
		active = true;   // A==B: виклик DMR, що триває, вважається активністю
	}

	displayClearBuf();
	// R97-FIX3: чергування -- статична шапка ОБРАНОГО каналу з кодплага; виклик/утримання -- справжня шапка. Передача сюди не потрапляє.
	dualRenderHeader((buttonsRead() & BUTTON_SK1) == BUTTON_SK1);

	if (caller)
	{
		uiDataGlobal.displayQSOStatePrev = QSO_DISPLAY_CALLER_DATA;
		uiDataGlobal.isDisplayingQSOData = true;
	}
	else
	{
		lastHeardClearLastID();
		uiDataGlobal.displayQSOStatePrev = QSO_DISPLAY_DEFAULT_SCREEN;
		uiDataGlobal.isDisplayingQSOData = false;
		uiDataGlobal.receivedPcId = 0x00;
	}

	dualRenderRow(DW_CARD_A_Y, false, dualChannelA(), dcTypeA(), (selB == false), (active && (cardB == false)), (caller && (cardB == false)));   // R98-FIX4 Б3: A -- канал або VFO
	dualRenderRow(DW_CARD_B_Y, true, dcChannelB(), dcTypeB(), selB, (active && cardB), (caller && cardB));
	displayRender();
}
#endif // DUAL_CHANNEL_ENABLED

void uiChannelModeColdStart(void)
{
	currentChannelData->rxFreq = 0U;	// Force to re-read codeplug data (needed due to "All Channels" translation)
}

// This can also be called from the VFO, on VFO -> New Channel, as currentZone could be uninitialized.
void uiChannelInitializeCurrentZone(void)
{
#if ! defined(PLATFORM_GD77S)
	// R22 Z1.4: збережена зона могла бути "сміттєвою" (її вибрав валкодер до R22) або зникнути після запису кодплага --
	// тоді замість сміттєвих каналів стартуємо з віртуальної "Всі канали" (остання зона).
	if (!codeplugZoneIsUsable(nonVolatileSettings.currentZone, &currentZone))
	{
		settingsSet(nonVolatileSettings.currentZone, (int16_t) (codeplugZonesGetCount() - 1));
	}
#endif
	codeplugZoneGetDataForNumber(nonVolatileSettings.currentZone, &currentZone);
	codeplugUtilConvertBufToDisplayString(currentZone.name, currentZoneName, 16);// need to convert to zero terminated string

	if ((ROAMING_EFFECTIVE() != ROAMING_OFF) &&
			settingsLocationIsValid() &&
			(CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone) == false))
	{
		initSortedChannels();
		uiDataGlobal.lastDistanceMillis = ticksGetMillis();
	}
}

static void quicksortChannelByDistance(channelDistance_t *channelDistances, uint16_t first, uint16_t last)
{
	channelDistance_t temp;
	uint16_t i, j, pivot;

	if(first < last)
	{
		pivot = first;
		i = first;
		j = last;

		while (i < j)
		{
			while ((channelDistances[i].distance <= channelDistances[pivot].distance) && (i < last))
			{
				i++;
			}

			while (channelDistances[j].distance > channelDistances[pivot].distance)
			{
				j--;
			}

			if (i < j)
			{
				memcpy(&temp, &channelDistances[i], sizeof(channelDistance_t));
				memcpy(&channelDistances[i], &channelDistances[j], sizeof(channelDistance_t));
				memcpy(&channelDistances[j], &temp, sizeof(channelDistance_t));
			}
		}

		memcpy(&temp, &channelDistances[pivot], sizeof(channelDistance_t));
		memcpy(&channelDistances[pivot], &channelDistances[j], sizeof(channelDistance_t));
		memcpy(&channelDistances[j], &temp, sizeof(channelDistance_t));

		if (j > 0)
		{
			quicksortChannelByDistance(channelDistances, first, (j - 1));
		}

		quicksortChannelByDistance(channelDistances, (j + 1), last);
	}
}

static void initSortedChannels(void)
{
	if (currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone > 0)
	{
		channelDistance_t channelDistances[80];// Temporary storage while sorting a zone
		CodeplugChannel_t channelData;

		for (uint16_t i = 0; i < currentZone.NOT_IN_CODEPLUGDATA_highestIndex; i++)
		{
			channelDistances[i].index = currentZone.channels[i];

			codeplugChannelGetDataForIndex(channelDistances[i].index, &channelData);
			checkChannelLocation(&channelData);

			if ((channelData.NOT_IN_CODEPLUG_CALCULATED_DISTANCE_X10 != -1) &&
					(channelData.NOT_IN_CODEPLUG_CALCULATED_DISTANCE_X10 < 65535) &&
					codeplugChannelGetFlag(&channelData, CHANNEL_FLAG_USE_LOCATION))
			{
				channelDistances[i].distance = channelData.NOT_IN_CODEPLUG_CALCULATED_DISTANCE_X10;
			}
			else
			{
				// Use large positive value for any channel which does not have a location, so that is sorted to be at the end of the list
				// Max real value is the radius of the Earth at the equator 40,075
				// This value is in steps of 0.1km   hence 50,000 * 10 is outside of the actual possible range and is used to indicate a channel with no location
				// the index value is added so that each channel with no location, is sorted correctly to retain its position in the zone, relatative to the other channels with no location

				channelDistances[i].distance = (500000 + i);
			}
		}

		quicksortChannelByDistance(channelDistances, 0U, (uint16_t)(currentZone.NOT_IN_CODEPLUGDATA_highestIndex - 1));

		for (uint16_t i = 0; i < currentZone.NOT_IN_CODEPLUGDATA_highestIndex; i++)
		{
			currentZone.channels[i] = channelDistances[i].index;
		}

		uiDataGlobal.lastDistanceSortLocationLat = settingsLocationGetLatitude();
		uiDataGlobal.lastDistanceSortLocationLon = settingsLocationGetLongitude();
	}
}


#if defined(PLATFORM_GD77S)
bool uiChannelModeTransmitDTMFContactForGD77S(void)
{
	if (GD77SParameters.uiMode == GD77S_UIMODE_DTMF_CONTACTS)
	{
		if (GD77SParameters.dtmfListCount > 0)
		{
			// start dtmf sequence
			if(dtmfSequenceIsKeying() == false)
			{
				CodeplugDTMFContact_t dtmfContact;

				if (voicePromptsIsPlaying())
				{
					voicePromptsTerminate();
				}

				codeplugDTMFContactGetDataForNumber(GD77SParameters.dtmfListSelected + 1, &dtmfContact);
				dtmfSequencePrepare(dtmfContact.code, true);
			}
			else
			{
				dtmfSequenceStop();
				dtmfSequenceTick(false);
				dtmfSequenceReset();
			}
		}
		else
		{
			voicePromptsInit();
			voicePromptsAppendLanguageString(currentLanguage->list_empty);
			voicePromptsPlay();
		}

		return true;
	}

	return false;
}

void toggleTimeslotForGD77S(void)
{
	if (trxGetMode() == RADIO_MODE_DIGITAL)
	{
		// Toggle timeslot
		trxSetDMRTimeSlot(1 - trxGetDMRTimeSlot(), true);
		tsSetManualOverride(CHANNEL_CHANNEL, (trxGetDMRTimeSlot() + 1));

		audioAmpDisable(AUDIO_AMP_CHANNEL_RF);
		HRC6000ClearActiveDMRID();
		lastHeardClearLastID();
		uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
		uiChannelModeUpdateScreen(0);
	}
}

void uiChannelModeHeartBeatActivityForGD77S(uiEvent_t *ev)
{
	static const uint32_t periods[] = { 6000, 100, 100, 100, 100, 100 };
	static const uint32_t periodsScan[] = { 2000, 50, 2000, 50, 2000, 50 };
	static uint8_t        beatRoll = 0;
	static uint32_t       mTime = 0;

	// <paranoid_mode>
	//   We use real time GPIO readouts, as LED could be turned on/off by another task.
	// </paranoid_mode>
	if ((LedRead(LED_RED) || LedRead(LED_GREEN)) // Any led is ON
			&& (trxTransmissionEnabled || (uiDataGlobal.DTMFContactList.isKeying) || (ev->buttons & BUTTON_PTT) || (audioAmpGetStatus() & (AUDIO_AMP_CHANNEL_RF | AUDIO_AMP_CHANNEL_BEEP | AUDIO_AMP_CHANNEL_PROMPT)) || trxCarrierDetected() || ev->hasEvent)) // we're transmitting, or receiving, or user interaction.
	{
		// Turn off the red LED, if not transmitting
		if (LedRead(LED_RED) // Red is ON
				&& ((uiDataGlobal.DTMFContactList.isKeying == false) && ((trxTransmissionEnabled == false) || ((ev->buttons & BUTTON_PTT) == 0)))) // No TX
		{
			if ((rxPowerSavingIsRxOn() == false) && (ev->hasEvent == false))
			{
				rxPowerSavingSetState(ECOPHASE_POWERSAVE_INACTIVE);
			}

			LedWrite(LED_RED, 0);
		}

		// Turn off the green LED, if not receiving, or no AF output
		if (LedRead(LED_GREEN)) // Green is ON
		{
			if ((trxTransmissionEnabled || (uiDataGlobal.DTMFContactList.isKeying) || (ev->buttons & BUTTON_PTT))
					|| ((trxGetMode() == RADIO_MODE_DIGITAL) && (slotState != DMR_STATE_IDLE))
					|| (((audioAmpGetStatus() & (AUDIO_AMP_CHANNEL_RF | AUDIO_AMP_CHANNEL_BEEP | AUDIO_AMP_CHANNEL_PROMPT)) != 0) || trxCarrierDetected()))
			{
				if ((ev->buttons & BUTTON_PTT) && (trxTransmissionEnabled == false)) // RX Only or Out of Band
				{
					if ((rxPowerSavingIsRxOn() == false) && (ev->hasEvent == false))
					{
						rxPowerSavingSetState(ECOPHASE_POWERSAVE_INACTIVE);
					}

					LedWrite(LED_GREEN, 0);
				}
			}
			else
			{
				if ((rxPowerSavingIsRxOn() == false) && (ev->hasEvent == false))
				{
					rxPowerSavingSetState(ECOPHASE_POWERSAVE_INACTIVE);
				}

				LedWrite(LED_GREEN, 0);
			}
		}

		// Reset pattern sequence
		beatRoll = 0;
		// And update the timer for the next first starting (OFF for 5 seconds) blink sequence.
		mTime = ev->time;
		return;
	}

	if (!rxPowerSavingIsRxOn())
	{
		return;
	}

	// Nothing is happening, blink
	if (((trxTransmissionEnabled == false) && (uiDataGlobal.DTMFContactList.isKeying == false) && ((ev->buttons & BUTTON_PTT) == 0))
			&& ((ev->hasEvent == false) && ((audioAmpGetStatus() & (AUDIO_AMP_CHANNEL_RF | AUDIO_AMP_CHANNEL_BEEP | AUDIO_AMP_CHANNEL_PROMPT)) == 0) && (trxCarrierDetected() == false)))
	{
		// Blink both LEDs to have Orange color
		if ((ev->time - mTime) > (uiDataGlobal.Scan.active ? periodsScan[beatRoll] : periods[beatRoll]))
		{
			if ((nonVolatileSettings.ecoLevel > 0) && (ev->hasEvent == false))
			{
				rxPowerSavingSetState(ECOPHASE_POWERSAVE_INACTIVE);
			}

			mTime = ev->time;
			beatRoll = (beatRoll + 1) % (uiDataGlobal.Scan.active ? (sizeof(periodsScan) / sizeof(periodsScan[0])) : (sizeof(periods) / sizeof(periods[0])));
			LedWrite(LED_RED, (beatRoll % 2));
			LedWrite(LED_GREEN, (beatRoll % 2));
		}
	}
	else
	{
		// Reset pattern sequence
		beatRoll = 0;
		// And update the timer for the next first starting (OFF for 5 seconds) blink sequence.
		mTime = ev->time;
	}
}

static uint16_t getCurrentChannelInCurrentZoneForGD77S(void)
{
	int16_t chanIdx = codeplugGetLastUsedChannelInCurrentZone();
	return (CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone) ? chanIdx : (chanIdx + 1));
}

static void checkAndUpdateSelectedChannelForGD77S(uint16_t chanNum, bool forceSpeech)
{
	bool updateDisplay = false;

	if(CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone))
	{
		GD77SParameters.channelOutOfBounds = false;
		if (codeplugAllChannelsIndexIsInUse(chanNum))
		{
			if (chanNum != codeplugGetLastUsedChannelInCurrentZone())
			{
				codeplugSetLastUsedChannelInZone(currentZone.NOT_IN_CODEPLUGDATA_indexNumber, chanNum);
				uiChannelModeLoadChannelData(false, false);
				updateDisplay = true;
			}
		}
		else
		{
			GD77SParameters.channelOutOfBounds = true;
			voicePromptsInit();
			voicePromptsAppendPrompt(PROMPT_CHANNEL);
			voicePromptsAppendLanguageString(currentLanguage->error);
			voicePromptsPlay();
		}
	}
	else
	{
		if ((chanNum - 1) < currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone)
		{
			GD77SParameters.channelOutOfBounds = false;
			if ((chanNum - 1) != codeplugGetLastUsedChannelInCurrentZone())
			{
				codeplugSetLastUsedChannelInZone(currentZone.NOT_IN_CODEPLUGDATA_indexNumber, (chanNum - 1));
				uiChannelModeLoadChannelData(false, false);
				updateDisplay = true;
			}
		}
		else
		{
			GD77SParameters.channelOutOfBounds = true;
			voicePromptsInit();
			voicePromptsAppendPrompt(PROMPT_CHANNEL);
			voicePromptsAppendLanguageString(currentLanguage->error);
			voicePromptsPlay();
		}
	}

	// Prevent TXing while an invalid channel is selected
	if (getCurrentChannelInCurrentZoneForGD77S() != chanNum)
	{
		PTTLocked = true;
	}
	else
	{
		if (PTTLocked)
		{
			PTTLocked = false;
			forceSpeech = true;
		}
	}

	if (updateDisplay || forceSpeech)
	{
		// Remove TS override when a new channel is selected, otherwise it will be set until the zone is changed.
		if (updateDisplay && (tsGetManualOverride(CHANNEL_CHANNEL) != 0))
		{
			tsSetManualOverride(CHANNEL_CHANNEL, TS_NO_OVERRIDE);
		}

		if (GD77SParameters.channelOutOfBounds == false)
		{
			char buf[17];

			voicePromptsInit();
			voicePromptsAppendPrompt(PROMPT_CHANNEL);
			voicePromptsAppendInteger(chanNum);
			voicePromptsAppendPrompt(PROMPT_SILENCE);
			codeplugUtilConvertBufToDisplayString(currentChannelData->name, buf, 16);
			voicePromptsAppendString(buf);
			voicePromptsPlay();
		}

		if (!forceSpeech)
		{
			uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
			uiChannelModeUpdateScreen(0);
		}
	}
}

static void buildSpeechChannelDetailsForGD77S()
{
	char buf[17];

	codeplugUtilConvertBufToDisplayString(currentChannelData->name, buf, 16);
	voicePromptsAppendString(buf);

	voicePromptsAppendPrompt(PROMPT_SILENCE);
	announceFrequency();
	voicePromptsAppendPrompt(PROMPT_SILENCE);

	if (trxGetMode() == RADIO_MODE_DIGITAL)
	{
		announceContactNameTgOrPc(voicePromptsIsPlaying());
		voicePromptsAppendPrompt(PROMPT_SILENCE);
		announceTS();
		voicePromptsAppendPrompt(PROMPT_SILENCE);
		announceCC();
	}
	else
	{
		CodeplugCSSTypes_t type = codeplugGetCSSType(currentChannelData->rxTone);
		if ((type & CSS_TYPE_NONE) == 0)
		{
			buildCSSCodeVoicePrompts(currentChannelData->rxTone, type, DIRECTION_RECEIVE, true);
			voicePromptsAppendPrompt(PROMPT_SILENCE);
		}

		type = codeplugGetCSSType(currentChannelData->txTone);
		if ((type & CSS_TYPE_NONE) == 0)
		{
			buildCSSCodeVoicePrompts(currentChannelData->txTone, type, DIRECTION_TRANSMIT, true);
		}
	}
}

static void buildSpeechUiModeForGD77S(GD77S_UIMODES_t uiMode)
{
	char buf[17];

	if (voicePromptsIsPlaying())
	{
		voicePromptsTerminate();
	}

	switch (uiMode)
	{
		case GD77S_UIMODE_TG_OR_SQUELCH: // Channel
			codeplugUtilConvertBufToDisplayString(currentChannelData->name, buf, 16);
			voicePromptsAppendString(buf);

			if (trxGetMode() == RADIO_MODE_DIGITAL)
			{
				announceTS();
			}
			else
			{
				announceSquelchLevel(voicePromptsIsPlaying());
			}
			break;

		case GD77S_UIMODE_SCAN: // Scan
			voicePromptsAppendLanguageString(currentLanguage->scan);
			voicePromptsAppendLanguageString(uiDataGlobal.Scan.active ? currentLanguage->on : currentLanguage->off);
			break;

		case GD77S_UIMODE_TS: // Timeslot
			if (trxGetMode() == RADIO_MODE_DIGITAL)
			{
				announceTS();
			}
			break;

		case GD77S_UIMODE_CC: // Color code
			if (trxGetMode() == RADIO_MODE_DIGITAL)
			{
				announceCC();
			}
			break;

		case GD77S_UIMODE_FILTER: // DMR/Analog filter
			voicePromptsAppendLanguageString(currentLanguage->filter);
			if (trxGetMode() == RADIO_MODE_DIGITAL)
			{
				if (nonVolatileSettings.dmrDestinationFilter == DMR_DESTINATION_FILTER_NONE)
				{
					voicePromptsAppendLanguageString(currentLanguage->none);
				}
				else
				{
					voicePromptsAppendString(DMR_DESTINATION_FILTER_LEVELS[nonVolatileSettings.dmrDestinationFilter - 1]);
				}

			}
			else
			{
				if (nonVolatileSettings.analogFilterLevel == ANALOG_FILTER_NONE)
				{
					voicePromptsAppendLanguageString(currentLanguage->none);
				}
				else
				{
					voicePromptsAppendString((char *)ANALOG_FILTER_LEVELS[nonVolatileSettings.analogFilterLevel - 1]);
				}
			}
			break;

		case GD77S_UIMODE_DTMF_CONTACTS:
			if (GD77SParameters.dtmfListCount > 0)
			{
				CodeplugDTMFContact_t dtmfContact;

				codeplugDTMFContactGetDataForNumber(GD77SParameters.dtmfListSelected + 1, &dtmfContact);
				codeplugUtilConvertBufToDisplayString(dtmfContact.name, buf, 16);
				voicePromptsAppendString(buf);
			}
			else
			{
				voicePromptsAppendLanguageString(currentLanguage->list_empty);
			}
			break;

		case GD77S_UIMODE_ZONE: // Zone
			announceZoneName(voicePromptsIsPlaying());
			break;

		case GD77S_UIMODE_POWER: // Power
			announcePowerLevel(voicePromptsIsPlaying());
			break;

		case GD77S_UIMODE_ECO:
			announceEcoLevel(voicePromptsIsPlaying());
			break;

		case GD77S_UIMODE_MAX:
			break;
	}
}

static void handleEventForGD77S(uiEvent_t *ev)
{
	if (ev->events & ROTARY_EVENT)
	{
		if (dtmfSequenceIsKeying())
		{
			dtmfSequenceStop();
		}

		if (!trxTransmissionEnabled && (ev->rotary > 0))
		{
			if (uiDataGlobal.Scan.active)
			{
				scanStop(false);
			}

			settingsSet(nonVolatileSettings.overrideTG, 0);
			checkAndUpdateSelectedChannelForGD77S(ev->rotary, false);
			HRC6000ClearActiveDMRID();
			lastHeardClearLastID();
		}
	}

	if (handleMonitorMode(ev))
	{
		return;
	}

	if (ev->events & BUTTON_EVENT)
	{
		if (dtmfSequenceIsKeying() && (ev->buttons & (BUTTON_SK1 | BUTTON_SK2 | BUTTON_ORANGE)))
		{
			dtmfSequenceStop();
		}

		if (BUTTONCHECK_SHORTUP(ev, BUTTON_ORANGE) && uiDataGlobal.Scan.active)
		{
			scanStop(false);

			voicePromptsInit();
			buildSpeechUiModeForGD77S(GD77S_UIMODE_SCAN);
			voicePromptsPlay();
			return;
		}

		if (BUTTONCHECK_LONGDOWN(ev, BUTTON_ORANGE) && (uiDataGlobal.DTMFContactList.isKeying == false))
		{
			announceItem(PROMPT_SEQUENCE_BATTERY, PROMPT_THRESHOLD_3);
			return;
		}
		else if (BUTTONCHECK_SHORTUP(ev, BUTTON_ORANGE) && (uiDataGlobal.DTMFContactList.isKeying == false))
		{
			voicePrompt_t vp = NUM_VOICE_PROMPTS;
			const char *vpString = NULL;

			GD77SParameters.uiMode = (GD77S_UIMODES_t) (GD77SParameters.uiMode + 1) % GD77S_UIMODE_MAX;

			//skip over Digital controls if the radio is in Analog mode
			if (trxGetMode() == RADIO_MODE_ANALOG)
			{
				// Analog
				if ((GD77SParameters.uiMode == GD77S_UIMODE_TS) ||
					(GD77SParameters.uiMode == GD77S_UIMODE_CC))
				{
					GD77SParameters.uiMode = GD77S_UIMODE_FILTER;
				}
			}
			else
			{
				// digital
				if (GD77SParameters.uiMode == GD77S_UIMODE_DTMF_CONTACTS)
				{
					GD77SParameters.uiMode = GD77S_UIMODE_ZONE;
				}
			}

			switch (GD77SParameters.uiMode)
			{
				case GD77S_UIMODE_TG_OR_SQUELCH: // Channel Mode
					if (trxGetMode() == RADIO_MODE_DIGITAL)
					{
						vp = PROMPT_CHANNEL_MODE;
					}
					else
					{
						vpString = currentLanguage->squelch;
					}
					break;

				case GD77S_UIMODE_SCAN:
					vp = PROMPT_SCAN_MODE;
					break;

				case GD77S_UIMODE_TS: // Timeslot Mode
					vp = PROMPT_TIMESLOT_MODE;
					break;

				case GD77S_UIMODE_CC: // ColorCode Mode
					vp = PROMPT_COLORCODE_MODE;
					break;

				case GD77S_UIMODE_FILTER: // DMR/Analog Filter
					vp = PROMPT_FILTER_MODE;
					break;

				case GD77S_UIMODE_DTMF_CONTACTS:
					vpString = currentLanguage->dtmf_contact_list;
					break;

				case GD77S_UIMODE_ZONE: // Zone Mode
					vp = PROMPT_ZONE_MODE;
					break;

				case GD77S_UIMODE_POWER: // Power Mode
					vp = PROMPT_POWER_MODE;
					break;

				case GD77S_UIMODE_ECO:
					vp = PROMPT_ECO_MODE;
					break;

				case GD77S_UIMODE_MAX:
					break;
			}

			if ((vp != NUM_VOICE_PROMPTS) || (vpString != NULL))
			{
				voicePromptsInit();
				if (vpString)
				{
					voicePromptsAppendLanguageString(vpString);
					voicePromptsAppendPrompt(PROMPT_MODE);
				}
				else
				{
					voicePromptsAppendPrompt(vp);
				}
				voicePromptsAppendPrompt(PROMPT_SILENCE);
				buildSpeechUiModeForGD77S(GD77SParameters.uiMode);
				voicePromptsPlay();
			}
		}
		else if (BUTTONCHECK_LONGDOWN(ev, BUTTON_SK1) && (monitorModeData.isEnabled == false) && (uiDataGlobal.DTMFContactList.isKeying == false))
		{
			if (GD77SParameters.channelOutOfBounds == false)
			{
				voicePromptsInit();
				buildSpeechChannelDetailsForGD77S();
				voicePromptsPlay();
			}
		}
		else if (BUTTONCHECK_SHORTUP(ev, BUTTON_SK1) && (uiDataGlobal.DTMFContactList.isKeying == false))
		{
			switch (GD77SParameters.uiMode)
			{
				case GD77S_UIMODE_TG_OR_SQUELCH:
					if (trxGetMode() == RADIO_MODE_DIGITAL)
					{
						// Next in TGList
						if (nonVolatileSettings.overrideTG == 0)
						{
							settingsIncrement(nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE], 1);
							if (nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE] > (currentRxGroupData.NOT_IN_CODEPLUG_numTGsInGroup - 1))
							{
								settingsSet(nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE], 0);
							}
						}
						settingsSet(nonVolatileSettings.overrideTG, 0);// setting the override TG to 0 indicates the TG is not overridden
						menuPrivateCallClear();
						updateTrxID();
						uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
						uiChannelModeUpdateScreen(0);
						announceItem(PROMPT_SEQUENCE_CONTACT_TG_OR_PC, PROMPT_THRESHOLD_3);
					}
					else
					{
						if(currentChannelData->sql == 0)			//If we were using default squelch level
						{
							currentChannelData->sql = nonVolatileSettings.squelchDefaults[currentRadioDevice->trxCurrentBand[TRX_RX_FREQ_BAND]];			//start the adjustment from that point.
						}

						if (currentChannelData->sql < CODEPLUG_MAX_VARIABLE_SQUELCH)
						{
							currentChannelData->sql++;
						}

						announceItem(PROMPT_SQUENCE_SQUELCH, PROMPT_THRESHOLD_3);
					}
					break;

				case GD77S_UIMODE_SCAN:
					if (uiDataGlobal.Scan.active)
					{
						scanStop(false);
					}
					else
					{
						scanStart(false);
					}

					voicePromptsInit();
					voicePromptsAppendLanguageString(currentLanguage->scan);
					voicePromptsAppendLanguageString(uiDataGlobal.Scan.active ? currentLanguage->on : currentLanguage->off);
					voicePromptsPlay();
					break;

				case GD77S_UIMODE_TS:
					if (trxGetMode() == RADIO_MODE_DIGITAL)
					{
						toggleTimeslotForGD77S();
						announceItem(PROMPT_SEQUENCE_TS, PROMPT_THRESHOLD_3);
					}
					break;

				case GD77S_UIMODE_CC:
					if (trxGetMode() == RADIO_MODE_DIGITAL)
					{
						if (currentChannelData->txColor < 15)
						{
							currentChannelData->txColor++;
							trxSetDMRColourCode(currentChannelData->txColor);
						}

						voicePromptsInit();
						announceCC();
						voicePromptsPlay();
					}
					break;

				case GD77S_UIMODE_FILTER:
					if (trxGetMode() == RADIO_MODE_DIGITAL)
					{
						if (nonVolatileSettings.dmrDestinationFilter < NUM_DMR_DESTINATION_FILTER_LEVELS - 1)
						{
							settingsIncrement(nonVolatileSettings.dmrDestinationFilter, 1);
							HRC6000InitDigitalDmrRx();
							audioAmpDisable(AUDIO_AMP_CHANNEL_RF);
						}
					}
					else
					{
						if (nonVolatileSettings.analogFilterLevel < NUM_ANALOG_FILTER_LEVELS - 1)
						{
							settingsIncrement(nonVolatileSettings.analogFilterLevel, 1);
							trxSetAnalogFilterLevel(nonVolatileSettings.analogFilterLevel);
						}
					}

					voicePromptsInit();
					buildSpeechUiModeForGD77S(GD77SParameters.uiMode);
					voicePromptsPlay();
					break;

				case GD77S_UIMODE_DTMF_CONTACTS:
					// select next DTMF contact and spell it
					if (GD77SParameters.dtmfListCount > 0)
					{
						GD77SParameters.dtmfListSelected = (GD77SParameters.dtmfListSelected + 1) % GD77SParameters.dtmfListCount;
					}
					voicePromptsInit();
					buildSpeechUiModeForGD77S(GD77SParameters.uiMode);
					voicePromptsPlay();
					break;

				case GD77S_UIMODE_ZONE: // Zones
					// No "All Channels" on GD77S
					nonVolatileSettings.currentZone = (nonVolatileSettings.currentZone + 1) % (codeplugZonesGetCount() - 1);

					settingsSet(nonVolatileSettings.overrideTG, 0); // remove any TG override
					tsSetManualOverride(CHANNEL_CHANNEL, TS_NO_OVERRIDE);
					currentChannelData->rxFreq = 0U; // Flag to the Channel screen that the channel data is now invalid and needs to be reloaded

					menuSystemPopAllAndDisplaySpecificRootMenu(UI_CHANNEL_MODE, true);
					checkAndUpdateSelectedChannelForGD77S(rotarySwitchGetPosition(), false);
					GD77SParameters.uiMode = GD77S_UIMODE_ZONE;

					announceItem(PROMPT_SEQUENCE_ZONE, PROMPT_THRESHOLD_3);
					break;

				case GD77S_UIMODE_POWER: // Power
					increasePowerLevel(true);// true = Allow 5W++
					break;

				case GD77S_UIMODE_ECO:
					if (nonVolatileSettings.ecoLevel < ECO_LEVEL_MAX)
					{
						settingsIncrement(nonVolatileSettings.ecoLevel, 1);
						rxPowerSavingSetLevel(nonVolatileSettings.ecoLevel);
					}
					voicePromptsInit();
					buildSpeechUiModeForGD77S(GD77SParameters.uiMode);
					voicePromptsPlay();
					break;

				case GD77S_UIMODE_MAX:
					break;
			}
		}
		else if (BUTTONCHECK_LONGDOWN(ev, BUTTON_SK2) && (monitorModeData.isEnabled == false) && (uiDataGlobal.DTMFContactList.isKeying == false))
		{
			uint32_t tg = (LinkHead->talkGroupOrPcId & 0xFFFFFF);

			// If Blue button is long pressed during reception it sets the Tx TG to the incoming TG
			if (uiDataGlobal.isDisplayingQSOData && BUTTONCHECK_DOWN(ev, BUTTON_SK2) && (trxGetMode() == RADIO_MODE_DIGITAL) &&
					((trxTalkGroupOrPcId != tg) ||
							((dmrMonitorCapturedTS != -1) && (dmrMonitorCapturedTS != trxGetDMRTimeSlot())) ||
							(trxGetDMRColourCode() != currentChannelData->txColor)))
			{
				lastHeardClearLastID();

				// Set TS to overriden TS
				if ((dmrMonitorCapturedTS != -1) && (dmrMonitorCapturedTS != trxGetDMRTimeSlot()))
				{
					trxSetDMRTimeSlot(dmrMonitorCapturedTS, true);
					tsSetManualOverride(CHANNEL_CHANNEL, (dmrMonitorCapturedTS + 1));
				}
				if (trxTalkGroupOrPcId != tg)
				{
					if ((tg >> 24) & PC_CALL_FLAG)
					{
						acceptPrivateCall(tg & 0xffffff, -1);
					}
					else
					{
						trxTalkGroupOrPcId = tg;
						settingsSet(nonVolatileSettings.overrideTG, trxTalkGroupOrPcId);
					}
				}

				currentChannelData->txColor = trxGetDMRColourCode();// Set the CC to the current CC, which may have been determined by the CC finding algorithm in C6000.c

				uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
				uiChannelModeUpdateScreen(0);

				voicePromptsInit();
				voicePromptsAppendLanguageString(currentLanguage->select_tx);
				voicePromptsPlay();
				return;
			}
		}
		else if (BUTTONCHECK_SHORTUP(ev, BUTTON_SK2) && (uiDataGlobal.DTMFContactList.isKeying == false))
		{
			switch (GD77SParameters.uiMode)
			{
				case GD77S_UIMODE_TG_OR_SQUELCH: // Previous in TGList
					if (trxGetMode() == RADIO_MODE_DIGITAL)
					{
						// To Do change TG in on same channel freq
						if (nonVolatileSettings.overrideTG == 0)
						{
							settingsDecrement(nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE], 1);
							if (nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE] < 0)
							{
								settingsSet(nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE], (int16_t) (currentRxGroupData.NOT_IN_CODEPLUG_numTGsInGroup - 1));
							}
						}
						settingsSet(nonVolatileSettings.overrideTG, 0);// setting the override TG to 0 indicates the TG is not overridden
						menuPrivateCallClear();
						updateTrxID();
						uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
						uiChannelModeUpdateScreen(0);
						announceItem(PROMPT_SEQUENCE_CONTACT_TG_OR_PC, PROMPT_THRESHOLD_3);
					}
					else
					{
						if(currentChannelData->sql == 0)			//If we were using default squelch level
						{
							currentChannelData->sql = nonVolatileSettings.squelchDefaults[currentRadioDevice->trxCurrentBand[TRX_RX_FREQ_BAND]];			//start the adjustment from that point.
						}

						if (currentChannelData->sql > CODEPLUG_MIN_VARIABLE_SQUELCH)
						{
							currentChannelData->sql--;
						}

						announceItem(PROMPT_SQUENCE_SQUELCH, PROMPT_THRESHOLD_3);
					}
					break;

				case GD77S_UIMODE_SCAN:
					if (uiDataGlobal.Scan.active)
					{
						// if we are scanning and down key is pressed then enter current channel into nuisance delete array.
						if(uiDataGlobal.Scan.state == SCAN_STATE_PAUSED)
						{
							// There is two channels available in the Zone, just stop scanning
							if (uiDataGlobal.Scan.nuisanceDeleteIndex == (uiDataGlobal.Scan.availableChannelsCount - 2))
							{
								uiDataGlobal.Scan.lastIteration = true;
							}

							uiDataGlobal.Scan.nuisanceDelete[uiDataGlobal.Scan.nuisanceDeleteIndex] = uiDataGlobal.currentSelectedChannelNumber;
							uiDataGlobal.Scan.nuisanceDeleteIndex = (uiDataGlobal.Scan.nuisanceDeleteIndex + 1) % MAX_ZONE_SCAN_NUISANCE_CHANNELS;
							uiDataGlobal.Scan.timer.timeout = SCAN_SKIP_CHANNEL_INTERVAL;	//force scan to continue;
							uiDataGlobal.Scan.state = SCAN_STATE_SCANNING;
							return;
						}

						// Left key reverses the scan direction
						if (uiDataGlobal.Scan.state == SCAN_STATE_SCANNING)
						{
							uiDataGlobal.Scan.direction *= -1;
							return;
						}
					}
					break;

				case GD77S_UIMODE_TS:
					if (trxGetMode() == RADIO_MODE_DIGITAL)
					{
						toggleTimeslotForGD77S();
						announceItem(PROMPT_SEQUENCE_TS, PROMPT_THRESHOLD_3);
					}
					break;

				case GD77S_UIMODE_CC:
					if (trxGetMode() == RADIO_MODE_DIGITAL)
					{
						if (currentChannelData->txColor > 0)
						{
							currentChannelData->txColor--;
							trxSetDMRColourCode(currentChannelData->txColor);
						}

						voicePromptsInit();
						announceCC();
						voicePromptsPlay();
					}
					break;

				case GD77S_UIMODE_FILTER:
					if (trxGetMode() == RADIO_MODE_DIGITAL)
					{
						if (nonVolatileSettings.dmrDestinationFilter > DMR_DESTINATION_FILTER_NONE)
						{
							settingsDecrement(nonVolatileSettings.dmrDestinationFilter, 1);
							HRC6000InitDigitalDmrRx();
							audioAmpDisable(AUDIO_AMP_CHANNEL_RF);
						}
					}
					else
					{
						if (nonVolatileSettings.analogFilterLevel > ANALOG_FILTER_NONE)
						{
							settingsDecrement(nonVolatileSettings.analogFilterLevel, 1);
							trxSetAnalogFilterLevel(nonVolatileSettings.analogFilterLevel);
						}
					}

					voicePromptsInit();
					buildSpeechUiModeForGD77S(GD77SParameters.uiMode);
					voicePromptsPlay();
					break;

				case GD77S_UIMODE_DTMF_CONTACTS:
					// select previous DTMF contact and spell it
					if (GD77SParameters.dtmfListCount > 0)
					{
						GD77SParameters.dtmfListSelected = (GD77SParameters.dtmfListSelected + GD77SParameters.dtmfListCount - 1) % GD77SParameters.dtmfListCount;
					}
					voicePromptsInit();
					buildSpeechUiModeForGD77S(GD77SParameters.uiMode);
					voicePromptsPlay();
					break;

				case GD77S_UIMODE_ZONE: // Zones
					// No "All Channels" on GD77S
					nonVolatileSettings.currentZone = (nonVolatileSettings.currentZone + (codeplugZonesGetCount() - 1) - 1) % (codeplugZonesGetCount() - 1);

					settingsSet(nonVolatileSettings.overrideTG, 0); // remove any TG override
					tsSetManualOverride(CHANNEL_CHANNEL, TS_NO_OVERRIDE);
					currentChannelData->rxFreq = 0U; // Flag to the Channel screeen that the channel data is now invalid and needs to be reloaded

					menuSystemPopAllAndDisplaySpecificRootMenu(UI_CHANNEL_MODE, true);
					checkAndUpdateSelectedChannelForGD77S(rotarySwitchGetPosition(), false);
					GD77SParameters.uiMode = GD77S_UIMODE_ZONE;

					announceItem(PROMPT_SEQUENCE_ZONE, PROMPT_THRESHOLD_3);
					break;

				case GD77S_UIMODE_POWER: // Power
					decreasePowerLevel();
					break;

				case GD77S_UIMODE_ECO:
					if (nonVolatileSettings.ecoLevel > 0)
					{
						settingsDecrement(nonVolatileSettings.ecoLevel, 1);
						rxPowerSavingSetLevel(nonVolatileSettings.ecoLevel);
					}
					voicePromptsInit();
					buildSpeechUiModeForGD77S(GD77SParameters.uiMode);
					voicePromptsPlay();
					break;

				case GD77S_UIMODE_MAX:
					break;
			}
		}
	}
}
#endif // PLATFORM_GD77S
