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
static void dualRenderScreen(void);
static uint16_t dualChannelA(void);
static void dualAutoResume(void);
static bool dualHoldScreen(void);
static bool dualSingle(void);
static bool dualRenderMeter(void);
static void dualQuietEnd(void);
static void dualQuickMenuApply(bool setB);
static void dualHotkeyToggle(void);
static void dualTune(bool toB);
static uint32_t s_dualKeyMs;   // час останньої клавіші на екрані каналу: чергування відновлюється через 1 с тиші (не між PRESS і SHORTUP)
static int16_t  s_dualTgIdxA;  // вибраний ТГ у списку прийому каналу A: завантаження B може скинути спільний індекс, повертаємо його з A
static bool     s_dualQuiet;   // R97-FIX4/5: придушити uiChannelModeUpdateScreen() на час обробки клавіші в режимі (S-метр звичайного екрана не спалахує); скидається наприкінці handleEvent()
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
					if (rxPowerSavingIsRxOn() && ((dualIsRunning() && (uiDataGlobal.Scan.state == SCAN_STATE_SCANNING)) == false))   // R97-FIX2: чергування -- статична шапка «[DW]», S-метра й виводу на екран нема
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

#if defined(DUAL_CHANNEL_ENABLED)
static void handleEventCore(uiEvent_t *ev);

// R97-FIX5: «тиша» (s_dualQuiet) охоплює весь обробник клавіші; наприкінці -- гарантоване скидання й один перемальований екран
static void handleEvent(uiEvent_t *ev)
{
	handleEventCore(ev);
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

		bool dwRunning = dualIsRunning();

		if (dwRunning || dualSingle())
		{
			if (dualHandleKey(ev))
			{
				return;
			}

			// R97: решта клавіш -- як без режиму: чергування зупиняється, клавіша обробляється нижче, режим лишається ввімкненим
			if (dwRunning)
			{
				dualSuspend();
			}
		}

		if (dcIsEnabled())
		{
			// R97-FIX5: стокова обробка клавіші (будь-якої) не малює свій екран із S-метром -- екран малює dualQuietEnd() після обробника
			s_dualQuiet = true;
		}

		if (dcIsOnB() && (ev->keys.key != KEY_GREEN) && (KEYCHECK_LONGDOWN(ev->keys, KEY_FRONT_DOWN) == false))
		{
			// R97-FIX4: рація стоїть на B (зупинено на обраному B, або чекає поновлення після меню). Зелена (головне меню) працює з обраним;
			// решта клавіш (ручка, цифри/прямий номер, зона SK2+▲/▼, ...) припускають, що канал на екрані -- канал зони (A): спершу на A.
			// Виняток -- довге ▼ (гаряча клавіша вимкнення): вимикає, лишаючись на обраному B.
			dualTune(false);
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
						if (currentRxGroupData.NOT_IN_CODEPLUG_numTGsInGroup > 1)
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

						uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
						uiNotificationShow(NOTIFICATION_TYPE_SQUELCH, NOTIFICATION_ID_SQUELCH, 1000, NULL, false);
						uiChannelModeUpdateScreen(0);
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
					if (currentRxGroupData.NOT_IN_CODEPLUG_numTGsInGroup > 1)
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
					announceItem(PROMPT_SEQUENCE_CONTACT_TG_OR_PC,PROMPT_THRESHOLD_3);
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

					uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
					uiNotificationShow(NOTIFICATION_TYPE_SQUELCH, NOTIFICATION_ID_SQUELCH, 1000, NULL, false);
					uiChannelModeUpdateScreen(0);
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
				case CH_SCREEN_QUICK_MENU_SET_B:          // R97
					rightSideConst = currentLanguage->dual_set_b;
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
				case CH_SCREEN_QUICK_MENU_DUAL_CHANNEL:   // R97: увімкнути/вимкнути режим
				case CH_SCREEN_QUICK_MENU_SET_B:          // R97: поточний канал стає B
				{
					// R97-FIX: пункт -- ДО menuSystemPopPreviousMenu(): Pop -> menuSystemPushMenuFirstRun() перезаписує currentItemIndex
					// індексом екрана каналу, і «Встановити як B» ішло гілкою On/Off (знайдено на рації).
					bool setB = (menuDataGlobal.currentItemIndex == CH_SCREEN_QUICK_MENU_SET_B);

					menuDataGlobal.menuOptionsTimeout = 0;
					menuSystemPopPreviousMenu();
					dualQuickMenuApply(setB);   // після повернення на екран каналу: сповіщення не перекриє меню
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

// R97-FIX3: шапка екрана режиму. Виклик/утримання (state != SCANNING) -- справжня шапка (рація на цьому каналі, S-метр). Чергування без
// активності -- СТАТИЧНА шапка ОБРАНОГО каналу (покажчик: A або B): режим, смуга, TS, CC, тони, потужність беруться з даних кодплага
// цього каналу (стек, без RAM-кешу), а не з налаштування радіо, яке чергується; S-метра нема. Перемикання A<->B шапку не чіпає.
static void dualRenderHeader(bool force)
{
	if (uiDataGlobal.Scan.state != SCAN_STATE_SCANNING)
	{
		uiUtilityRenderHeader(false, false, force);
		return;
	}

	CodeplugChannel_t tmp;
	uiHeaderOverride_t ov;
	uint16_t ch = (dcPointerB() ? dcChannelB() : dualChannelA());

	if ((ch < DC_CH_MIN) || (codeplugAllChannelsIndexIsInUse(ch) == false))
	{
		uiUtilityRenderHeader(false, false, force);   // не мало б траплятись (пару перевірено при старті)
		return;
	}

	codeplugChannelGetDataForIndex(ch, &tmp);
	ov.ch = &tmp;
	ov.mode = (uint8_t)tmp.chMode;
	ov.bw25 = (uint8_t)(codeplugChannelGetFlag(&tmp, CHANNEL_FLAG_BW_25K) != 0);
	ov.ts = (uint8_t)(codeplugChannelGetFlag(&tmp, CHANNEL_FLAG_TIMESLOT_TWO) != 0);
	ov.cc = tmp.txColor;
	uiUtilityRenderHeaderForChannel(&ov, force);
}

// Для applicationMain.c (headerRowIsDirty: заряд, зміна CC): true -- шапку намалювано тут (режим чергує без активності).
bool uiChannelModeDualHeader(bool force)
{
	if ((dualIsRunning() == false) || (uiDataGlobal.Scan.state != SCAN_STATE_SCANNING))
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
static void dualTune(bool toB)
{
	bool wasOnB = dcIsOnB();

	lastHeardClearLastID();

	if (toB)
	{
		if (wasOnB == false)
		{
			s_dualTgIdxA = nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE];
		}

		dcSetOnB(true);
		codeplugChannelGetDataForIndex(dcChannelB(), &channelScreenChannelData);
		uiChannelModeLoadChannelData(true, false);
	}
	else
	{
		dcSetOnB(false);

		if (wasOnB && (nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE] != s_dualTgIdxA))
		{
			// індекс ТГ спільний для всіх каналів (як у звичайному скануванні); B міг його скинути -- повернути вибір A
			settingsSet(nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE], s_dualTgIdxA);
		}

		uiChannelModeLoadChannelData(false, false);
	}
}

static uint16_t dualChannelA(void)
{
	return ((currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone > 0) ? (uint16_t)codeplugGetLastUsedChannelNumberInCurrentZone() : 0U);
}

static dcPairCheck_t dualCheckPair(void)
{
	uint16_t chB = dcChannelB();
	bool bInUse = (((chB >= DC_CH_MIN) && (chB <= DC_CH_MAX)) ? codeplugAllChannelsIndexIsInUse(chB) : false);

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
		if (dcIsOnB())
		{
			dualTune(false);   // чергування завжди починається з A
		}
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

	return (b && (dcChannelB() >= DC_CH_MIN) && (dcChannelB() <= DC_CH_MAX) && codeplugAllChannelsIndexIsInUse(dcChannelB()));
}

// Зупинити чергування, не вимикаючи режим: рація стає на ОБРАНИЙ канал (A або B; R97-FIX4 -- раніше завжди на A). Меню (швидке, головне,
// «Режим APRS») працюють з обраним; «чужі» клавіші, небезпечні для B, повертають на A самі (handleEvent, ручка на A).
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
static void dualLeaveOnB(void)
{
	uint16_t b = dcChannelB();
	int pos = -1;
	bool wasAll = CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone);

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

	uiChannelModeLoadChannelData(false, false);
}

// Вимкнути режим (довге ▼ або пункт швидкого меню; червона з R97-FIX4 не вимикає): лишаємось на ОБРАНОМУ каналі -- A лишається на A, B (dualLeaveOnB()).
// Якщо B уже не існує (видалено/не задано) -- як раніше, на A.
static void dualDisable(void)
{
	bool stayB = dualSelectedIsB();   // R97-FIX4: лишаємось на ОБРАНОМУ (активність -- де рація; чергування -- за покажчиком; з меню -- де стоїть)

	if (stayB)
	{
		uiDataGlobal.Scan.active = false;
		uiDataGlobal.Scan.scanType = SCAN_TYPE_NORMAL_STEP;
		uiDataGlobal.Scan.state = SCAN_STATE_SCANNING;
		scanNextChannelReady = false;
		dualLeaveOnB();
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

	if (dualChannelA() == dcChannelB())
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
	uint16_t b = dcChannelB();

	return (dcIsEnabled() && (dualIsRunning() == false) && (b >= DC_CH_MIN) && (b <= DC_CH_MAX) && (b == dualChannelA()) && codeplugAllChannelsIndexIsInUse(b));
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
static uint16_t dualZoneChannelAt(int pos, void *ctx)
{
	(void)ctx;

	if (CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone))
	{
		return (codeplugAllChannelsIndexIsInUse(pos + 1) ? (uint16_t)(pos + 1) : 0U);
	}

	return (((pos >= 0) && (pos < currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone)) ? currentZone.channels[pos] : 0U);
}

static void dualStepB(int dir)
{
	int n = (CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone) ? currentZone.NOT_IN_CODEPLUGDATA_highestIndex : currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone);
	uint16_t chA = dualChannelA();
	int from = dcFindPos(n, dcChannelB(), dualZoneChannelAt, NULL);

	if (from < 0)
	{
		from = dcFindPos(n, chA, dualZoneChannelAt, NULL);   // B не з цієї зони -- крок від A
	}

	int pos = dcStepPos(n, from, dir, 0U, dualZoneChannelAt, NULL);   // R97-FIX6: B може збігатися з A -- жодного каналу не пропускаємо

	if (pos < 0)
	{
		soundSetMelody(MELODY_ERROR_BEEP);   // у зоні нема іншого каналу, крім A
		return;
	}

	(void)dcSetChannelB(dualZoneChannelAt(pos, NULL), false);   // відкладений запис (3 с без змін)

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

// Клавіші під час чергування: true -- оброблено (решта -- як без режиму, через dualSuspend()).
static bool dualHandleKey(uiEvent_t *ev)
{
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

				if (dcPointerB())
				{
					dualStepB(dir);
				}
				else
				{
					// Покажчик на A -- звичайна зміна каналу зони (ті самі handleUpKey/handleDownKey); A не може стати B -- перескакуємо
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
			// R97-FIX4: червона режим НЕ вимикає (рішення власника): вимикають лише довге ▼ і пункт швидкого меню «Подв. прийом».
			// Клавішу з'їдаємо без дій -- стокова червона на цьому екрані нічого корисного не робить, а чергування не переривається.
			return true;

		default:
			break;
	}

	return false;
}

// Увімкнути/вимкнути режим -- ОДНА логіка для пункту швидкого меню й гарячої клавіші (довге ▼): перевірка пари (B не задано / канал B
// видалено / B збігається з A -- сповіщення й сигнал помилки, режим не стартує), запис блоку, старт/зупинка чергування.
// notify -- коротке сповіщення «вкл/вимк» (гаряча клавіша; у меню зміну видно і так).
static void dualSetMode(bool on, bool notify)
{
	if (on)
	{
		dcPairCheck_t chk = dualCheckPair();

		if (chk != DC_PAIR_OK)
		{
			dualShowPairError(chk);   // режим не стартує (B не задано / видалено); A==B -- не помилка (R97-FIX6)
			return;
		}

		dcSetTxHold(false);
		(void)dcSetEnabled(true, true);
		s_dualKeyMs = 0U;
		dualAutoResume();

		if (dualIsRunning() == false)
		{
			uiChannelModeUpdateScreen(0);   // A==B: чергування не стартує, але екран режиму потрібен одразу
		}
	}
	else
	{
		dualDisable();
		uiChannelModeUpdateScreen(0);
	}

	if (notify)
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
static void dualQuickMenuApply(bool setB)
{
	if (setB)
	{
		uint16_t ch = dualChannelA();

		// R97-FIX4: меню відкрито на B (зупинка на обраному B) -- на екрані B, а «поточний канал зони» (A) інший: безпечно нічого не змінювати
		if (dcIsOnB() || (ch < DC_CH_MIN) || (codeplugAllChannelsIndexIsInUse(ch) == false))
		{
			soundSetMelody(MELODY_ERROR_BEEP);
			return;
		}

		// При ввімкненому режимі поточний канал і є A: після «Встановити як B» режим чекає, доки A стане іншим каналом (dualAutoResume)
		(void)dcSetChannelB(ch, true);
		uiNotificationShowShort(1500U, currentLanguage->dual_b_saved, true);
		return;
	}

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
#define DW_SQ_X          3                                 // ліве квадратне поле з літерою A/B
#define DW_SQ_W          24
#define DW_SQ_DY         3
#define DW_SQ_H          51                                // y+3..53
#define DW_LETTER_X      (DW_SQ_X + ((DW_SQ_W - 16) / 2))  // літера FONT_SIZE_4: 16x32
#define DW_LETTER_DY     5
#define DW_ARROW_DY      40                                // ▸ під літерою: y+40..44
#define DW_TXT_X         30                                // текст праворуч від поля; до x=157 -- 128 px
#define DW_LINE1_DY      4                                 // рядок 1: номер + назва, FONT_SIZE_1 (до 21 символу = 126 px)
#define DW_LINE2_DY      15                                // рядок 2 (основний): абонент / ТГ / «FM»+частота, FONT_SIZE_3 (до 16 символів = 128 px)
#define DW_LINE3_DY      34                                // рядок 3 (службовий): TS/CC/ТГ або тон/смуга, FONT_SIZE_1 (до 19 символів = 114 px, x ≤ 143)
#define DW_LINE3_MAX     19
#define DW_LOCK_X        145                               // замок AES 10x9: x=145..154, y+33..41 (праворуч від рядка 3)
#define DW_LOCK_DY       33
#define DW_METER_DY      44                                // смуга активності: мітка RX + S-метр, y+44..53
#define DW_METER_H       10
#define DW_TAG_W         14                                // мітка «RX» 14x10, x=30..43
#define DW_METER_X       48                                // 9 сегментів 10x10 із кроком 12 px = x=48..153
#define DW_METER_SEG_W   10
#define DW_METER_STEP    12
#define DW_METER_SEGS    9

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

// Смуга активності картки: мітка «RX» + сегментований S-метр (9 сегментів). Лише для активної картки; перемальовує тільки свою ділянку.
static void dualMeterRow(int16_t y)
{
	int rssi = trxGetRSSIdBm(RADIO_DEVICE_PRIMARY);
	int16_t my = (y + DW_METER_DY);

	displayThemeApply(THEME_ITEM_FG_DEFAULT, THEME_ITEM_BG);
	displayFillRect(DW_TXT_X, my, ((DW_CARD_X + DW_CARD_W - 1) - DW_TXT_X), DW_METER_H, true);

	displayThemeApply(THEME_ITEM_FG_CHANNEL_NAME, THEME_ITEM_BG);
	displayFillRect(DW_TXT_X, my, DW_TAG_W, DW_METER_H, false);
	displayPrintCore((DW_TXT_X + 1), (my + 1), "RX", FONT_SIZE_1, TEXT_ALIGN_LEFT, true);

	for (int i = 1; i <= DW_METER_SEGS; i++)
	{
		int16_t sx = (DW_METER_X + ((i - 1) * DW_METER_STEP));

		if (rssi >= (SMETER_S0 + (i * 4)))   // та сама шкала, що в стоковому блоці: 4 дБ на S-одиницю
		{
			displayThemeApply(THEME_ITEM_FG_RSSI_BAR, THEME_ITEM_BG);
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

// Одна картка каналу: рамка, квадрат з літерою (обраний -- інвертований, під літерою ▸), рядок 1 (номер+назва), рядок 2 (абонент / контакт-ТГ / FM+частота),
// рядок 3 (TS/CC/ТГ виклику або тон/смуга FM), замок AES, смуга активності (RX + S-метр). Усе на стеку, з кодплага; імена в RAM не кешуються.
static void dualRenderRow(int16_t y, bool isB, uint16_t ch, bool selected, bool active, bool callerHere)
{
	CodeplugChannel_t tmp;
	char name[17];
	char l1[24];
	char l2[17];
	char l3[DW_LINE3_MAX + 1];
	char letter[2];
	bool known = ((ch >= DC_CH_MIN) && (ch <= DC_CH_MAX) && codeplugAllChannelsIndexIsInUse(ch));

	name[0] = 0;
	l2[0] = 0;
	l3[0] = 0;

	if (known)
	{
		codeplugChannelGetDataForIndex(ch, &tmp);
		codeplugUtilConvertBufToDisplayString(tmp.name, name, 16);

		if (tmp.chMode == RADIO_MODE_DIGITAL)
		{
			CodeplugContact_t ct;

			if ((tmp.contact != 0) && codeplugContactGetDataForIndex(tmp.contact, &ct))
			{
				codeplugUtilConvertBufToDisplayString(ct.name, l2, 16);   // ТГ/контакт каналу з кодплага

				if (l2[0] == 0)
				{
					snprintf(l2, sizeof(l2), "%s %u", ((ct.callType == CONTACT_CALLTYPE_PC) ? currentLanguage->pc : currentLanguage->tg), (unsigned)ct.tgNumber);   // ім'я порожнє -- «TG 91»
				}
			}

			if (l2[0] == 0)
			{
				snprintf(l2, sizeof(l2), "--");   // контакт не заданий
			}

			snprintf(l3, sizeof(l3), "TS%d CC%d", ((codeplugChannelGetFlag(&tmp, CHANNEL_FLAG_TIMESLOT_TWO) != 0) ? 2 : 1), (int)tmp.txColor);

			if (callerHere && (LinkHead != NULL))
			{
				size_t n = strlen(l3);

				snprintf((l3 + n), (sizeof(l3) - n), " %.11s", LinkHead->talkgroup);   // ТГ/ID призначення виклику, що триває
			}
		}
		else
		{
			int mhz = (int)(tmp.rxFreq / 100000U);
			size_t n;
			CodeplugCSSTypes_t type = codeplugGetCSSType(tmp.rxTone);

			snprintf(l2, sizeof(l2), "FM %d.%05d", mhz, (int)(tmp.rxFreq - ((uint32_t)mhz * 100000U)));

			if (type == CSS_TYPE_CTCSS)
			{
				snprintf(l3, sizeof(l3), "CTCSS %d.%d", (tmp.rxTone / 10), (tmp.rxTone % 10));
			}
			else if (type & CSS_TYPE_DCS)
			{
				n = (size_t)snprintf(l3, sizeof(l3), "DCS ");
				(void)dcsPrintf((l3 + n), (sizeof(l3) - n), NULL, tmp.rxTone);
			}
			else
			{
				snprintf(l3, sizeof(l3), "--");
			}

			n = strlen(l3);
			snprintf((l3 + n), (sizeof(l3) - n), " %s", ((codeplugChannelGetFlag(&tmp, CHANNEL_FLAG_BW_25K) != 0) ? "25k" : "12.5k"));   // смуга -- якщо влазить (обрізається snprintf)
		}
	}
	else
	{
		snprintf(name, sizeof(name), "---");
	}

	if (callerHere)
	{
		dualCallerText(l2);   // хто зараз говорить -- замість ТГ каналу
	}

	// рамка картки
	displayThemeApply(THEME_ITEM_FG_DECORATION, THEME_ITEM_BG);
	displayDrawRect(DW_CARD_X, y, DW_CARD_W, DW_CARD_H, true);

	// квадрат з літерою; обраний -- залитий, літера і ▸ кольором фону
	letter[0] = (isB ? 'B' : 'A');
	letter[1] = 0;
	displayThemeApply(THEME_ITEM_FG_CHANNEL_NAME, THEME_ITEM_BG);

	if (selected)
	{
		displayFillRect(DW_SQ_X, (y + DW_SQ_DY), DW_SQ_W, DW_SQ_H, false);
	}
	else
	{
		displayDrawRect(DW_SQ_X, (y + DW_SQ_DY), DW_SQ_W, DW_SQ_H, true);
	}

	displayPrintCore(DW_LETTER_X, (y + DW_LETTER_DY), letter, FONT_SIZE_4, TEXT_ALIGN_LEFT, selected);

	if (selected)
	{
		int16_t cx = (DW_SQ_X + (DW_SQ_W / 2));

		displayFillTriangle((cx - 2), (y + DW_ARROW_DY), (cx - 2), (y + DW_ARROW_DY + 4), (cx + 2), (y + DW_ARROW_DY + 2), false);   // ▸ під літерою
	}

	snprintf(l1, sizeof(l1), "%u %s", (unsigned)ch, name);
	displayPrintCore(DW_TXT_X, (y + DW_LINE1_DY), l1, FONT_SIZE_1, TEXT_ALIGN_LEFT, false);

	displayThemeApply((callerHere ? THEME_ITEM_FG_CHANNEL_CONTACT_INFO : THEME_ITEM_FG_CHANNEL_CONTACT), THEME_ITEM_BG);
	displayPrintCore(DW_TXT_X, (y + DW_LINE2_DY), l2, FONT_SIZE_3, TEXT_ALIGN_LEFT, false);

	displayThemeApply(THEME_ITEM_FG_CHANNEL_NAME, THEME_ITEM_BG);
	displayPrintCore(DW_TXT_X, (y + DW_LINE3_DY), l3, FONT_SIZE_1, TEXT_ALIGN_LEFT, false);

#if defined(ENABLE_AES)
	if (known && uiChannelDataHasAes(&tmp))
	{
		uiDrawAesIconAt(DW_LOCK_X, (y + DW_LOCK_DY));   // замок -- на картці каналу, що має ключ (не в шапці: там тепер картки)
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

	dualRenderRow(DW_CARD_A_Y, false, dualChannelA(), (selB == false), (active && (cardB == false)), (caller && (cardB == false)));
	dualRenderRow(DW_CARD_B_Y, true, dcChannelB(), selB, (active && cardB), (caller && cardB));
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
