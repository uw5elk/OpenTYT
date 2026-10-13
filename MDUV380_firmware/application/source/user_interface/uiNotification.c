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
#include "user_interface/menuSystem.h"
#include "user_interface/uiLocalisation.h"
#include "user_interface/uiUtilities.h"
#include "utils.h"


#if defined(PLATFORM_RD5R)
#define YCENTER         ((DISPLAY_SIZE_Y / 2) + 3)
#define INNERBOX_H      (FONT_SIZE_3_HEIGHT + 7)
#define YBAR            (YCENTER - ((FONT_SIZE_3_HEIGHT / 2) + 2))
#define YTEXT           (YBAR + 1)
#else
#define YCENTER         (DISPLAY_SIZE_Y / 2)
#define INNERBOX_H      (FONT_SIZE_3_HEIGHT + 6)
#define YBAR            (YCENTER - (FONT_SIZE_3_HEIGHT / 2))
#define YTEXT           (YBAR - 2)
#endif
#define XBAR            69
#define YBOX            (YCENTER - (INNERBOX_H / 2))


#if defined(CPU_MK22FN512VLL12) || defined(PLATFORM_MD9600)
#if defined(PLATFORM_RD5R)
#define BEARING_RADIUS              18
#define BEARING_CIRCLE_X_OFFSET     4
#define BEARING_BOX_H             ((BEARING_RADIUS + 5) * 2)
#else
#define BEARING_RADIUS              18
#define BEARING_CIRCLE_X_OFFSET     4
#define BEARING_BOX_H             ((BEARING_RADIUS + 5) * 2)
#endif
#else // defined(CPU_MK22FN512VLL12) || defined(PLATFORM_MD9600)
#define BEARING_RADIUS              24
#define BEARING_CIRCLE_X_OFFSET     13
#define BEARING_BOX_H             ((BEARING_RADIUS + 10) * 2)
#endif
#define BEARING_CIRCLE_X_POS       (BEARING_RADIUS + BEARING_CIRCLE_X_OFFSET)
#define BEARING_BOX_W              (DISPLAY_SIZE_X - 4)
#define BEARING_BOX_Y             ((DISPLAY_SIZE_Y - BEARING_BOX_H) / 2)
#define TOP_ARROW_OFFSET           (BEARING_RADIUS - 8)
#define BASE_ARROW_OFFSET         -(BEARING_RADIUS - 8)
#define BEARING_AND_DIST_X_CENTER (((DISPLAY_SIZE_X - ((BEARING_RADIUS * 2) + BEARING_CIRCLE_X_OFFSET)) / 2) + ((BEARING_RADIUS * 2) + BEARING_CIRCLE_X_OFFSET))


#if defined(PLATFORM_MD9600) || defined(PLATFORM_GD77) || defined(PLATFORM_GD77S) || defined(PLATFORM_DM1801) || defined(PLATFORM_DM1801A) || defined(PLATFORM_RD5R)
static __attribute__((section(".data.$RAM2"))) uint8_t screenNotificationBufData[((DISPLAY_SIZE_X * DISPLAY_SIZE_Y) >> 3)];
#else
/* Форк (2026-09-19, розвідка docs/notification-buffer.md): повноекранний бекап
 * (40960 Б = 62.5% усієї CCMRAM) прибрано. Раніше тут зберігалась копія ВСЬОГО
 * екрана на кожен тік, поки видима БУДЬ-ЯКА картка сповіщення -- аби живий фон
 * (годинник/S-метр/дані виклику) продовжував оновлюватись і коректно повертався
 * при закритті. Тепер так: для більшості типів (SQUELCH/VOLUME/POWER/SMS -- і так
 * на весь екран, фону не видно; звичайний MESSAGE/BEARING -- короткий таймаут,
 * 1-4 с) бекап/відновлення пропускається взагалі -- картка малюється прямо в
 * живий screenBufData, штовхається на LCD ОДИН раз при показі
 * (uiNotificationRefresh()), і при закритті екран перемальовується з нуля
 * (uiNotificationHide() -> menuSystemCallCurrentMenuTick(), той самий шлях, що
 * вже використовує daytimeThemeApply()).
 *
 * ЄДИНИЙ виняток -- NOTIFICATION_ID_USER_APO: попередження про автовимкнення,
 * до 60 с, і саме тому НЕБЕЗПЕЧНО лишати фон застиглим -- вхідний виклик, що
 * надійде за цей час, інакше не буде видно (докладніше -- notification-buffer.md,
 * розділ 3б). Для APO лишили старий бекап/відновлення, але не на весь екран --
 * лише на смугу рядків, яку може зачепити displayMessage() (той самий код, яким
 * малюється й сам APO-попап; максимум 4 рядки -- HAS_COLOURS).
 *
 * Межі смуги виведені з displayMessage()/displayDrawRoundRectWithDropShadow() для
 * linesCount=4 (максимум, який дозволяє сам код): y = ((128-64)>>1)-3 = 29;
 * displayDrawRoundRectWithDropShadow(1, y-1=28, 156, 16*4+6=70, 3, true) малює
 * тінь (зсув +2 по x, той самий y) і рамку (зсув -2 по y) -- об'єднана площа:
 * рядки [26, 97] (72 рядки), стовпці [1, 158]. NOTIFICATION_APO_BUF_H=72 --
 * достатньо для ЦЬОГО коду; якщо колись зміниться формат displayMessage()
 * (більше рядків, інший шрифт) -- цю константу треба перерахувати заново.
 * Помилка в цих межах не є небезпечною (памʼять не переповнюється -- memcpy
 * завжди рівно sizeof(screenNotificationBufData) в обидва боки), у гіршому
 * випадку -- косметичний артефакт на краю картки APO, не крах. */
#define NOTIFICATION_APO_BUF_Y0   26
#define NOTIFICATION_APO_BUF_H    72
static  __attribute__((section(".ccmram"))) uint16_t screenNotificationBufData[DISPLAY_SIZE_X * NOTIFICATION_APO_BUF_H];   /* CCM-OK(перед використанням завжди memcpy() повного розміру з основного екранного буфера) */
#endif

typedef struct
{
	bool                         visible;
	/* Форк (2026-09-19, фікс регресії immediateRender=false, a2211ac): true від
	 * моменту, коли visible стало true, і до першого фактичного
	 * uiNotificationRefresh() для ЦЬОГО показу. uiNotificationShow(...,
	 * immediateRender=false) більше не штовхає картку на LCD сама -- натомість
	 * лишає pendingRender=true, а displayRender() (HX8353E_display.c) перевіряє
	 * його щотіку й, поки true, примусово викликає uiNotificationRefresh() (так
	 * само, як і для APO), доки картка нарешті не буде намальована. Після цього
	 * pendingRender скидається, і для НЕ-APO типів подальші тіки знову нічого не
	 * роблять -- картка лишається на LCD такою, якою її намалював цей один виклик. */
	bool                         pendingRender;
	ticksTimer_t                 hideTimer;
	uiNotificationType_t         type;
	uiNotificationID_t           id;
	char                         message[NOTIFICATION_MESSAGE_LEN_MAX];
	uiNotificationBearingInfo_t  bearingInfo;
} uiNotificationData_t;

static uiNotificationData_t notificationData =
{
		.visible = false,
		.pendingRender = false,
		.hideTimer = { 0, 0 },
		.type = NOTIFICATION_TYPE_MAX,
		.id = NOTIFICATION_ID_NONE,
		.message = { 0 },
		.bearingInfo = { .bearing = 0.0, .distanceX10 = -1 }
};

#if defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)
#include "functions/dmr_sms.h"        /* dmrSmsUnreadCount(): скільки ще непрочитаних */
#include "functions/sms_format.h"     /* ui6: smsPluralForm, SMS_TIME_* */
#include "user_interface/uiSms.h"     /* ui6: позивний/ім'я, місцевий час, перенесення за словами */
#if defined(LANGUAGE_BUILD_UKRAINIAN)
#include "user_interface/languages/messages_ua.h"
#else
#define MSGS_FROM                "From"
/* ui6: загальна кількість непрочитаних (разом із показаним); англійською форма одна. */
#define MSGS_UNREAD1_FMT         "%d unread"
#define MSGS_UNREAD2_FMT         "%d unread"
#define MSGS_UNREAD5_FMT         "%d unread"
#endif
/* Банер Call Alert (форк, 2026-09-26) -- заголовок і підказка закриття; сам текст
 * абонента (ім'я/ID) приходить готовим у notificationData.message, як SMS/MESSAGE. */
#if defined(LANGUAGE_BUILD_UKRAINIAN)
#include "user_interface/languages/rctl_ua.h"
#else
#define RCTL_CALL_ALERT_TITLE    "Private Alert"
#define RCTL_CALL_ALERT_HINT     "GRN:call RED:close"
#endif
#endif

#if defined(APRS_RX)
#include "functions/aprs_rx.h"        /* R13: вікно маяка -- aprsRxWindow() */
#include "functions/aprs_mode_cfg.h"  /* aprsSymbolNameEx() */
#include "functions/aprs_icons.h"     /* R14: піктограми символів */
#include "functions/aprs_msg.h"       /* R15: aprsMsgWrapLine() -- коментар у два рядки */
#include "user_interface/languages/aprsrx_ua.h"
#endif
#if defined(ENABLE_CALL_REPLAY)
#include "functions/callReplay.h"     /* callReplayPlayedMs/PlayTotalMs/IsLastTransitionMode -- картка нижче */
#endif

static void displayMessage(void);
static void displaySmsFullScreen(void);
static void displayLevelCard(const char *title, const char *valueText, int16_t pct);
#if defined(ENABLE_APRS_RX)
static void displayMessageCard(void);
#endif
#if defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)
static void displayCallAlertFullScreen(void);
static void displaySmsAckedFullScreen(void);
#endif

void uiNotificationShow(uiNotificationType_t type, uiNotificationID_t id, uint32_t msTimeout, const char *message, bool immediateRender)
{
	bool valid = true;

	if (notificationData.visible)
	{
		if (notificationData.id != id)
		{
			notificationData.visible = false;
			displayRender();
		}
	}

	memset(notificationData.message, 0, sizeof(notificationData.message));

	notificationData.type = type;
	notificationData.id = id;

	switch (type)
	{
		case NOTIFICATION_TYPE_SQUELCH:
#if defined(HAS_SOFT_VOLUME)
		case NOTIFICATION_TYPE_VOLUME:
#endif
			break;

		case NOTIFICATION_TYPE_POWER:
			break;

#if defined(ENABLE_CALL_REPLAY)
		case NOTIFICATION_TYPE_CALL_REPLAY:
			// Контент -- живі callReplay* гетери, рахуються в uiNotificationRefresh()
			// на кожному показі/оновленні; тут зберігати нічого не треба (message
			// лишається порожнім, як і для SQUELCH/POWER/VOLUME вище).
			break;
#endif

		case NOTIFICATION_TYPE_MESSAGE:
		case NOTIFICATION_TYPE_SMS:
#if defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)
		case NOTIFICATION_TYPE_CALL_ALERT:
#endif
			if (message)
			{
				snprintf(&notificationData.message[0], sizeof(notificationData.message), "%s", message);
			}
			break;

		case NOTIFICATION_TYPE_BEARING:
			break;

#if defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)
		case NOTIFICATION_TYPE_SMS_ACKED:
			// Лише картинка (галочка) -- текст не зберігаємо, гасне по таймауту як звичайний банер.
			break;
#endif

		default:
			valid = false;
			break;
	}

	if (valid)
	{
		notificationData.visible = true;
		// Форк (2026-09-19): див. коментар біля поля pendingRender вище. Виставляємо
		// ЗАВЖДИ, а не лише коли immediateRender==false -- якщо immediateRender==true,
		// виклик uiNotificationRefresh() нижче одразу ж скине його назад у false,
		// тож для цього шляху нічого не змінюється.
		notificationData.pendingRender = true;
		if (immediateRender)
		{
			uiNotificationRefresh();
		}
		ticksTimerStart(&notificationData.hideTimer, msTimeout);
	}
}

void uiNotificationBearingShow(uiNotificationBearingInfo_t *bearing, uint32_t msTimeout, bool immediateRender)
{
	memcpy(&(notificationData.bearingInfo), bearing, sizeof(uiNotificationBearingInfo_t));
	uiNotificationShow(NOTIFICATION_TYPE_BEARING, NOTIFICATION_ID_BEARING, msTimeout, NULL, immediateRender);
}

void uiNotificationRefresh(void)
{
	if (notificationData.visible)
	{
		// Форк (2026-09-19): див. великий коментар біля оголошення screenNotificationBufData.
		bool isApo = (notificationData.id == NOTIFICATION_ID_USER_APO);

		// Форк (2026-09-19, фікс регресії immediateRender=false): цей виклик -- і є
		// той самий "перший фактичний рендер", на який чекає pendingRender (див.
		// коментар біля поля). Скидаємо одразу: функція нижче синхронно домальовує
		// й штовхає картку до кінця, тож на момент повернення показ уже відбувся.
		notificationData.pendingRender = false;

#if defined(PLATFORM_MD9600) || defined(PLATFORM_GD77) || defined(PLATFORM_GD77S) || defined(PLATFORM_DM1801) || defined(PLATFORM_DM1801A) || defined(PLATFORM_RD5R)
		// copy the primary screen content
		memcpy(screenNotificationBufData, displayGetPrimaryScreenBuffer(), sizeof(screenNotificationBufData));
		displayOverrideScreenBuffer(screenNotificationBufData);
#else
		if (isApo)
		{
			// Бекапимо лише смугу рядків APO-картки, не весь екран -- решта типів
			// сюди взагалі не заходить (isApo == false).
			memcpy(screenNotificationBufData,
					(displayGetPrimaryScreenBuffer() + (NOTIFICATION_APO_BUF_Y0 * DISPLAY_SIZE_X)),
					sizeof(screenNotificationBufData));
		}
#endif

		// Draw whatever
		switch (notificationData.type)
		{
			case NOTIFICATION_TYPE_SQUELCH:
#if defined(HAS_SOFT_VOLUME)
			case NOTIFICATION_TYPE_VOLUME:
#endif
			{
				// Форк: повноекранне вікно регулювання гучності / шумоподавлення (баг #5).
				// Саму картку малює спільна displayLevelCard() -- та сама, що й потужність.
				char valueText[SCREEN_LINE_BUFFER_SIZE];
				int16_t pct;
				const char *title;

#if defined(HAS_SOFT_VOLUME)
				if (notificationData.type == NOTIFICATION_TYPE_VOLUME)
				{
					uint16_t volValue = CLAMP((lastVolume + 32), 0, 62);

					pct = (int16_t)((volValue * 100) / 62);
					title = currentLanguage->volume;
				}
				else
#endif
				{
					pct = (int16_t)(((currentChannelData->sql - CODEPLUG_MIN_VARIABLE_SQUELCH) * 100) /
						(CODEPLUG_MAX_VARIABLE_SQUELCH - CODEPLUG_MIN_VARIABLE_SQUELCH));
					title = currentLanguage->squelch;
				}

				pct = CLAMP(pct, 0, 100);
				snprintf(valueText, SCREEN_LINE_BUFFER_SIZE, "%d%%", pct);
				displayLevelCard(title, valueText, pct);
			}
			break;

			case NOTIFICATION_TYPE_POWER:
			{
				// Форк: та сама повноекранна картка, що й гучність/шумоподавлення (раніше
				// була вузька рамка по центру, що перекривала S-метр і обрізалась праворуч
				// -- виглядала інакше й гірше читалась у польових умовах). Формат великого
				// значення лишився той самий -- "500mW"/"1W"/"5W" з getPowerLevel()+Unit().
				// Смуга -- позиція рівня потужності серед УСІХ можливих (0..MAX_POWER_SETTING_NUM),
				// а не відсоток від безперервного діапазону, як у гучності/шумоподавлення.
				char valueText[SCREEN_LINE_BUFFER_SIZE];
				uint8_t powerLevel = trxGetPowerLevel();
				int16_t pct = (int16_t)(((int32_t)powerLevel * 100) / MAX_POWER_SETTING_NUM);
				// Форк, виправлення 2026-09-18: currentLanguage->power існує лише в
				// українському блоці stringsTable_t (uiLanguage.h, під
				// LANGUAGE_BUILD_UKRAINIAN) -- розкладку структури там навмисно не
				// чіпаємо, щоб не зрушити її для збірок без цього прапорця. Тому й
				// звертання до поля тут МАЄ бути умовним; безумовне звертання ламало
				// збірки build(ENABLE_AES=0) і build(ENABLE_AES=1) у CI (їх немає в
				// stringsTable_t для тих конфігурацій), а syntax_check.sh цього не
				// ловив, бо сам завжди компілює з -DLANGUAGE_BUILD_UKRAINIAN.
#if defined(LANGUAGE_BUILD_UKRAINIAN)
				const char *powerTitle = currentLanguage->power;
#else
				const char *powerTitle = "Power";
#endif

				snprintf(valueText, SCREEN_LINE_BUFFER_SIZE, "%s%s", getPowerLevel(powerLevel), getPowerLevelUnit(powerLevel));
				displayLevelCard(powerTitle, valueText, pct);
			}
			break;

#if defined(ENABLE_CALL_REPLAY)
			case NOTIFICATION_TYPE_CALL_REPLAY:
			{
				// Форк (2026-09-20, задача "картка під час відтворення", варіант A з
				// макета): та сама спільна displayLevelCard(), що й гучність/потужність/
				// шумоподавлення вище -- жодного нового коду малювання. Заголовок --
				// режим АКТИВНОЇ сесії ("Останній виклик"/"Останні 30 с",
				// callReplayIsLastTransitionMode() -- та сама функція, що й картка-
				// сповіщення на старті в callReplayPlayback.c/uiUtilities.c). Велике
				// значення -- скільки ВЖЕ прозвучало, "m:ss" (задача: загальної
				// тривалості НЕ показувати окремим числом -- лише в смузі прогресу
				// нижче). Смуга -- played/total, той самий CLAMP(0..100), що й в decl
				// displayLevelCard() (тут теж рахуємо тут, а не покладаємось лише на
				// внутрішній clamp -- totalMs==0 (теоретично, якщо картку якимось чином
				// покликали для НЕ активної сесії) не повинен ділити на нуль).
				char valueText[SCREEN_LINE_BUFFER_SIZE];
				uint32_t playedMs = callReplayPlayedMs();
				uint32_t totalMs = callReplayPlayTotalMs();
				uint32_t playedS = (playedMs / 1000U);
				uint32_t mm = (playedS / 60U);
				uint32_t ss = (playedS % 60U);
				int16_t pct = (int16_t)((totalMs > 0U) ? (((uint64_t)playedMs * 100U) / totalMs) : 0U);
				const char *title = (callReplayIsLastTransitionMode() ?
						currentLanguage->call_replay_mode_last : currentLanguage->call_replay_mode_all);

				snprintf(valueText, SCREEN_LINE_BUFFER_SIZE, "%lu:%02lu", (unsigned long)mm, (unsigned long)ss);
				displayLevelCard(title, valueText, pct);
			}
			break;
#endif

			case NOTIFICATION_TYPE_MESSAGE:
#if defined(ENABLE_APRS_RX)
				if ((notificationData.id == NOTIFICATION_ID_CARD) || (notificationData.id == NOTIFICATION_ID_TX_INHIBIT))
				{
					displayMessageCard();   // R18 Д6: короткі підтвердження/відмови -- на весь екран, як гучність
				}
				else
#endif
				displayMessage();
				break;

			case NOTIFICATION_TYPE_SMS:
				displaySmsFullScreen();
				break;

#if defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)
			case NOTIFICATION_TYPE_CALL_ALERT:
				displayCallAlertFullScreen();
				break;

			case NOTIFICATION_TYPE_SMS_ACKED:
				displaySmsAckedFullScreen();
				break;
#endif

			case NOTIFICATION_TYPE_BEARING:
			{
				char buffer[SCREEN_LINE_BUFFER_SIZE];
				int16_t x1, x2, x3, y1, y2, y3;

				displayThemeApply(THEME_ITEM_FG_DECORATION, THEME_ITEM_BG_NOTIFICATION);
				displayDrawRoundRectWithDropShadow(1, BEARING_BOX_Y, (DISPLAY_SIZE_X - 4), BEARING_BOX_H, 3, true);
				displayThemeApply(THEME_ITEM_FG_NOTIFICATION, THEME_ITEM_BG_NOTIFICATION);

				// Circle
				for (int16_t i = 0; i < 360; i += 15)
				{
					x1 = (int16_t)(BEARING_CIRCLE_X_POS + (BEARING_RADIUS) * cos((double)(i * DEG_TO_RAD)));
					y1 = (int16_t)(((DISPLAY_SIZE_Y >> 1) - 3) + (BEARING_RADIUS) * sin((double)(i * DEG_TO_RAD)));

					x2 = (int16_t)(BEARING_CIRCLE_X_POS + (BEARING_RADIUS - ((i % 45) ? 2 : 4)) * cos((double)(i * DEG_TO_RAD)));
					y2 = (int16_t)(((DISPLAY_SIZE_Y >> 1) - 3) + (BEARING_RADIUS - ((i % 45) ? 2 : 4)) * sin((double)(i * DEG_TO_RAD)));

					if (i == 270)
					{
						displayThemeApply(THEME_ITEM_FG_GPS_COLOUR, THEME_ITEM_BG_NOTIFICATION);
						displayDrawLine((x1 - 1), y1, (x2 - 1), y2, true);
					}

					displayDrawLine(x1, y1, x2, y2, true);

					if (i == 270)
					{
						displayDrawLine((x1 + 1), y1, (x2 + 1), y2, true);
						displayThemeApply(THEME_ITEM_FG_DECORATION, THEME_ITEM_BG_NOTIFICATION);
					}
				}


				displayThemeApply(THEME_ITEM_FG_DECORATION, THEME_ITEM_BG_NOTIFICATION);
				displayDrawCircle(BEARING_CIRCLE_X_POS, ((DISPLAY_SIZE_Y >> 1) - 3), (BEARING_RADIUS + 1), true);
				displayThemeApply(THEME_ITEM_FG_GPS_COLOUR, THEME_ITEM_BG_NOTIFICATION);

				// Needle
				double needle = (notificationData.bearingInfo.bearing - 90.0);

				if (needle > 360.0)
				{
					needle -= 360.0;
				}

				needle *= DEG_TO_RAD;

				x1 = (int16_t)(BEARING_CIRCLE_X_POS + TOP_ARROW_OFFSET * cos(needle));
				y1 = (int16_t)(((DISPLAY_SIZE_Y >> 1) - 3) + TOP_ARROW_OFFSET * sin(needle));

				x2 = (int16_t)(BEARING_CIRCLE_X_POS + BASE_ARROW_OFFSET * cos(needle + (30 * DEG_TO_RAD)));
				y2 = (int16_t)(((DISPLAY_SIZE_Y >> 1) - 3) + BASE_ARROW_OFFSET * sin(needle + (30 * DEG_TO_RAD)));

				x3 = (int16_t)(BEARING_CIRCLE_X_POS + BASE_ARROW_OFFSET * cos(needle - (30 * DEG_TO_RAD)));
				y3 = (int16_t)(((DISPLAY_SIZE_Y >> 1) - 3) + BASE_ARROW_OFFSET * sin(needle - (30 * DEG_TO_RAD)));

				displayFillTriangle(x1, y1, x2, y2, x3, y3, true);

				// Bearing and Distance values
				displayThemeApply(THEME_ITEM_FG_NOTIFICATION, THEME_ITEM_BG_NOTIFICATION);

				snprintf(buffer, SCREEN_LINE_BUFFER_SIZE, "%u%c", ((uint32_t)notificationData.bearingInfo.bearing), 176);
				displayPrintAt((BEARING_AND_DIST_X_CENTER - ((strlen(buffer) * 8) >> 1)),
						(((DISPLAY_SIZE_Y >> 1) - 3) - FONT_SIZE_3_HEIGHT), buffer, FONT_SIZE_3);

				if (notificationData.bearingInfo.distanceX10 >= 0)
				{
					uint32_t intPart = (notificationData.bearingInfo.distanceX10 / 10);
					uint32_t decPart = (notificationData.bearingInfo.distanceX10 - (intPart * 10));

					snprintf(buffer, SCREEN_LINE_BUFFER_SIZE, "%u.%u km", intPart, decPart);
					displayPrintAt((BEARING_AND_DIST_X_CENTER - ((strlen(buffer) * 8) >> 1)),
							(((DISPLAY_SIZE_Y >> 1) - 3) + 2), buffer, FONT_SIZE_3);
				}
			}
			break;

			default:
				break;
		}

		displayThemeResetToDefault();
		displayRenderWithoutNotification();
#if defined(PLATFORM_MD9600) || defined(PLATFORM_GD77) || defined(PLATFORM_GD77S) || defined(PLATFORM_DM1801) || defined(PLATFORM_DM1801A) || defined(PLATFORM_RD5R)
		displayRestorePrimaryScreenBuffer();
#else
		if (isApo)
		{
			memcpy((displayGetPrimaryScreenBuffer() + (NOTIFICATION_APO_BUF_Y0 * DISPLAY_SIZE_X)),
					screenNotificationBufData, sizeof(screenNotificationBufData));
		}
		// Інакше -- нічого не відновлюємо: screenBufData лишається з щойно намальованою
		// карткою (саме так і задумано; фон повернеться при закритті, uiNotificationHide()).
#endif
	}
}

bool uiNotificationHasTimedOut(void)
{
	/* Банер вхідного SMS сам НЕ зникає: повідомлення могло прийти, коли рації не було в
	 * руках, і зникнувши за 4 с воно лишалось непоміченим. Прибирає його лише оператор
	 * червоною кнопкою (див. applicationMain.c). */
	if (notificationData.visible && (notificationData.type == NOTIFICATION_TYPE_SMS))
	{
		return false;
	}
#if defined(ENABLE_CALL_REPLAY)
	/* Картка "Переслухати" (задача 2026-09-20): висить до кінця відтворення, а не по
	 * таймауту -- закриває її сам callReplayStopInternal() (callReplayPlayback.c) явним
	 * uiNotificationHide(), тим самим шляхом, що й банер SMS вище. msTimeout, переданий
	 * у uiNotificationShow() для цього типу, свідомо великий і сюди й не має дійти. */
	if (notificationData.visible && (notificationData.type == NOTIFICATION_TYPE_CALL_REPLAY))
	{
		return false;
	}
#endif
#if defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)
	/* Банер Call Alert (2026-09-26) -- той самий патерн, що SMS: міг прийти, коли рації
	 * не було в руках, тож сам не зникає -- лише оператор через RED (applicationMain.c). */
	if (notificationData.visible && (notificationData.type == NOTIFICATION_TYPE_CALL_ALERT))
	{
		return false;
	}
#endif
	return (notificationData.visible && ticksTimerHasExpired(&notificationData.hideTimer));
}

/* Чи показано саме банер SMS -- щоб головний цикл знав, що RED має його закрити. */
bool uiNotificationIsSms(void)
{
	return (notificationData.visible && (notificationData.type == NOTIFICATION_TYPE_SMS));
}

#if defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)
/* Чи показано саме банер Call Alert -- щоб головний цикл знав, що RED має його закрити. */
bool uiNotificationIsCallAlert(void)
{
	return (notificationData.visible && (notificationData.type == NOTIFICATION_TYPE_CALL_ALERT));
}
#endif

bool uiNotificationIsVisible(void)
{
	return notificationData.visible;
}

void uiNotificationHide(bool immediateRender)
{
#if !(defined(PLATFORM_MD9600) || defined(PLATFORM_GD77) || defined(PLATFORM_GD77S) || defined(PLATFORM_DM1801) || defined(PLATFORM_DM1801A) || defined(PLATFORM_RD5R))
	bool wasApo = (notificationData.id == NOTIFICATION_ID_USER_APO);
#endif

	notificationData.visible = false;
	// Форк: разом із visible -- pendingRender стає нечинним (uiNotificationIsVisible()
	// у displayRender() і так відсіє його), скидаємо для охайності стану, щоб не
	// лишати "завислий" true поза вікном його чинності (показ-до-першого-рендера).
	notificationData.pendingRender = false;
	uiDataGlobal.displayQSOState = uiDataGlobal.displayQSOStatePrev;

	if (immediateRender)
	{
#if !(defined(PLATFORM_MD9600) || defined(PLATFORM_GD77) || defined(PLATFORM_GD77S) || defined(PLATFORM_DM1801) || defined(PLATFORM_DM1801A) || defined(PLATFORM_RD5R))
		if (!wasApo)
		{
			// Форк (2026-09-19): для типів БЕЗ безперервного бекапу (усе, крім APO --
			// docs/notification-buffer.md) screenBufData після закриття містить лише
			// саму картку, не живий фон. Перш ніж щось штовхати на LCD, перемальовуємо
			// поточний екран з нуля -- той самий шлях, що й daytimeThemeApply()
			// (uiUtilities.c): синтетична подія FUNC_REDRAW в обробник поточного меню.
			// Він сам завершується власним displayRender() (перевірений патерн,
			// вживаний саме для "перемалювати екран з нуля" деінде в кодовій базі),
			// тож окремий displayRender() нижче тут не потрібен -- інакше вийшов би
			// подвійний повний пуш на LCD (зайві ~12.5 мс DMA).
			uiEvent_t redrawEvent = { .buttons = 0, .keys = NO_KEYCODE, .rotary = 0,
					.function = FUNC_REDRAW, .events = FUNCTION_EVENT, .hasEvent = true,
					.time = ticksGetMillis() };

			menuSystemCallCurrentMenuTick(&redrawEvent);
		}
		else
#endif
		{
			displayRender();
		}
	}
}

uiNotificationID_t uiNotificationGetId(void)
{
	return notificationData.id;
}

bool uiNotificationIsPendingRender(void)
{
	return notificationData.pendingRender;
}

/* Форк: спільна повноекранна картка "заголовок + велике значення + смуга-індикатор".
 * Спершу писана для гучності/шумоподавлення (баг #5, 2026-09-11), тепер перевикористана й
 * для потужності (2026-09-18): та сама картка виглядає й поводиться однаково для всіх
 * трьох -- лише подача (значення для показу й позиція смуги) різна для кожного типу,
 * рахує її сам виклик у uiNotificationRefresh(). Керування (валкодер/таймаут) тут не
 * чіпаємо -- воно й так живе поза відмальовкою, у коді, що змінює currentChannelData->sql /
 * lastVolume / trxSetPowerFromLevel() і викликає uiNotificationShow().
 *
 * valueText -- вже ГОТОВИЙ рядок для великого числа по центру ("42%" для гучності/
 * шумоподавлення, "500mW"/"1W"/"5W" для потужності -- формат не змінюємо, лише переносимо
 * малювання). pct (0-100) -- де саме заповнена смуга; для потужності це позиція серед
 * дискретних рівнів (mW/W), а не відсоток від безперервного діапазону. */
static void displayLevelCard(const char *title, const char *valueText, int16_t pct)
{
	char buffer[SCREEN_LINE_BUFFER_SIZE];
	const int16_t barX = 14;
	const int16_t barW = (DISPLAY_SIZE_X - (2 * barX));
	const int16_t barY = 92;
	const int16_t barH = 18;
	int16_t fillW;

	pct = CLAMP(pct, 0, 100);

	// Форк: кольори за темою. НІЧ -- яскраво-жовтий на темному (максимальна
	// читабельність у русі/полі). ДЕНЬ -- темно-синій на білому (на прохання
	// fleet: жовтий на світлому тлі денної теми не читався б).
	uint16_t colBg, colFg, colDec;
	if (DAYTIME_CURRENT == NIGHT)
	{
		colBg  = PLATFORM_COLOUR_FORMAT_SWAP_BYTES(RGB888_TO_PLATFORM_COLOUR_FORMAT(0x0C0C14));
		colFg  = PLATFORM_COLOUR_FORMAT_SWAP_BYTES(RGB888_TO_PLATFORM_COLOUR_FORMAT(0xFFE000));
		colDec = PLATFORM_COLOUR_FORMAT_SWAP_BYTES(RGB888_TO_PLATFORM_COLOUR_FORMAT(0x786914));
	}
	else
	{
		colBg  = PLATFORM_COLOUR_FORMAT_SWAP_BYTES(RGB888_TO_PLATFORM_COLOUR_FORMAT(0xFFFFFF));  // біле тло
		colFg  = PLATFORM_COLOUR_FORMAT_SWAP_BYTES(RGB888_TO_PLATFORM_COLOUR_FORMAT(0x0A2A6B));  // темно-синій текст/смуга
		colDec = PLATFORM_COLOUR_FORMAT_SWAP_BYTES(RGB888_TO_PLATFORM_COLOUR_FORMAT(0x6E86C0));  // світліший синій -- рамка
	}

	// Фон на весь екран
	displaySetForegroundAndBackgroundColours(colFg, colBg);
	displayFillRect(0, 0, DISPLAY_SIZE_X, DISPLAY_SIZE_Y, true);

	// Рамка
	displaySetForegroundAndBackgroundColours(colDec, colBg);
	displayDrawRect(1, 1, (DISPLAY_SIZE_X - 2), (DISPLAY_SIZE_Y - 2), false);

	// Заголовок
	displaySetForegroundAndBackgroundColours(colFg, colBg);
	strncpy(buffer, title, (SCREEN_LINE_BUFFER_SIZE - 1));
	buffer[SCREEN_LINE_BUFFER_SIZE - 1] = 0;
	displayPrintCentered(16, buffer, FONT_SIZE_3);

	// Велике значення по центру (готовий рядок -- "42%" або "500mW" тощо)
	strncpy(buffer, valueText, (SCREEN_LINE_BUFFER_SIZE - 1));
	buffer[SCREEN_LINE_BUFFER_SIZE - 1] = 0;
	displayPrintCentered(44, buffer, FONT_SIZE_4);

	// Смуга-індикатор
	displaySetForegroundAndBackgroundColours(colDec, colBg);
	displayDrawRect(barX, barY, barW, barH, false);

	fillW = (int16_t)(((barW - 4) * pct) / 100);
	if (fillW > 0)
	{
		displaySetForegroundAndBackgroundColours(colFg, colBg);
		displayFillRect((barX + 2), (barY + 2), fillW, (barH - 4), false);
	}
}

#if defined(ENABLE_APRS_RX)
/* R18 Д6: повноекранна картка короткого підтвердження/відмови -- ТОЙ САМИЙ вигляд, що й displayLevelCard() (гучність, потужність, «Переслухати»): повне тло, рамка,
 * кольори за темою (ніч -- жовтий на темному, день -- темно-синій на білому). Без смуги-індикатора. Текст -- notificationData.message; '\n' -- розрив рядка;
 * довший за 19 символів рядок переноситься за пробілом. Шрифт 8x16 (FONT_SIZE_3): великий 16x32 не має частини кирилиці. До 4 рядків. */
#define CARD_COLS   19
#define CARD_LINES  4
static void displayMessageCard(void)
{
	char line[CARD_LINES][CARD_COLS + 1];
	int n = 0;
	const char *p = notificationData.message;
	uint16_t colBg, colFg, colDec;

	while ((*p != 0) && (n < CARD_LINES))
	{
		int len = 0;
		int cut;

		while ((p[len] != 0) && (p[len] != '\n'))
		{
			len++;
		}
		if (len > CARD_COLS)
		{
			cut = CARD_COLS;
			for (int i = CARD_COLS; i > 0; i--)
			{
				if (p[i] == ' ')
				{
					cut = i;   // розрив за пробілом
					break;
				}
			}
			memcpy(line[n], p, (size_t)cut);
			line[n][cut] = 0;
			p += cut;
			if (*p == ' ')
			{
				p++;
			}
		}
		else
		{
			memcpy(line[n], p, (size_t)len);
			line[n][len] = 0;
			p += len;
			if (*p == '\n')
			{
				p++;
			}
		}
		n++;
	}
	if (n == 0)
	{
		line[0][0] = 0;
		n = 1;
	}

	if (DAYTIME_CURRENT == NIGHT)
	{
		colBg  = PLATFORM_COLOUR_FORMAT_SWAP_BYTES(RGB888_TO_PLATFORM_COLOUR_FORMAT(0x0C0C14));
		colFg  = PLATFORM_COLOUR_FORMAT_SWAP_BYTES(RGB888_TO_PLATFORM_COLOUR_FORMAT(0xFFE000));
		colDec = PLATFORM_COLOUR_FORMAT_SWAP_BYTES(RGB888_TO_PLATFORM_COLOUR_FORMAT(0x786914));
	}
	else
	{
		colBg  = PLATFORM_COLOUR_FORMAT_SWAP_BYTES(RGB888_TO_PLATFORM_COLOUR_FORMAT(0xFFFFFF));
		colFg  = PLATFORM_COLOUR_FORMAT_SWAP_BYTES(RGB888_TO_PLATFORM_COLOUR_FORMAT(0x0A2A6B));
		colDec = PLATFORM_COLOUR_FORMAT_SWAP_BYTES(RGB888_TO_PLATFORM_COLOUR_FORMAT(0x6E86C0));
	}
	displaySetForegroundAndBackgroundColours(colFg, colBg);
	displayFillRect(0, 0, DISPLAY_SIZE_X, DISPLAY_SIZE_Y, true);
	displaySetForegroundAndBackgroundColours(colDec, colBg);
	displayDrawRect(1, 1, (DISPLAY_SIZE_X - 2), (DISPLAY_SIZE_Y - 2), false);
	displaySetForegroundAndBackgroundColours(colFg, colBg);
	{
		const int16_t lineStep = (FONT_SIZE_3_HEIGHT + 4);
		int16_t y = (int16_t)((DISPLAY_SIZE_Y - ((n * lineStep) - 4)) / 2);

		for (int i = 0; i < n; i++)
		{
			displayPrintCentered(y, line[i], FONT_SIZE_3);
			y = (int16_t)(y + lineStep);
		}
	}
}
#endif

#if defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)
#if defined(APRS_RX)
/* ============================================================================================================
 * R13: ВІКНО МАЯКА -- повноекранна картка за позиційним пакетом APRS, тримається до RED / нового пакета / повідомлення.
 * Малюється існуючими примітивами (лінії, коло, текст), без спрайтів; дані -- aprsRxWindow() (копія з пакета).
 *
 * Розкладка 160x128:  угорі позивний (8x16) і час; зліва -- відстань+сектор, азимут цифрою, курс, швидкість;
 * праворуч -- кільце R=31 зі стрілкою з центру на станцію (північ угорі, мітка «Пн» над кільцем: магнітометра в рації нема,
 * тож напрям рахується ВІД ПІВНОЧІ, а не від того, куди повернута рація); унизу -- символ APRS і коментар.
 * ============================================================================================================ */
#define APRS_WIN_CX      121
#define APRS_WIN_CY      64
#define APRS_WIN_R       31
#define APRS_WIN_ARROW   22    /* R17 Г5: довжина стрілки; кінчик (22) не заходить на риски кільця (R-6..R-2 = 25..29) */

/* R17 Г5: стрілка залитими трикутниками (aprsArrowPoly(): стрижень 4 px -- два трикутники, вістря -- один) + контур кожного (щоб шви між трикутниками
 * не лишали пропусків) і диск r = 2 у центрі. */
static void aprsWinDrawArrow(uint16_t bearing)
{
	aprsArrowPoly_t p;

	aprsArrowPoly(&p, APRS_WIN_CX, APRS_WIN_CY, APRS_WIN_ARROW, bearing);
	for (int i = 0; i < 3; i++)
	{
		const aprsTri_t *t = &p.t[i];

		displayFillTriangle(t->x[0], t->y[0], t->x[1], t->y[1], t->x[2], t->y[2], true);
		displayDrawLine(t->x[0], t->y[0], t->x[1], t->y[1], true);
		displayDrawLine(t->x[1], t->y[1], t->x[2], t->y[2], true);
		displayDrawLine(t->x[2], t->y[2], t->x[0], t->y[0], true);
	}
	displayFillCircle(APRS_WIN_CX, APRS_WIN_CY, 2, true);
}

/* R17 Г5: кільце з двох кіл (R і R-1: лінія завтовшки 2 px), чотири внутрішні риски R-2..R-6 (Пн, Сх, Пд, Зх) і мітка «Пн» над кільцем. */
static void aprsWinDrawRing(void)
{
	displayDrawCircle(APRS_WIN_CX, APRS_WIN_CY, APRS_WIN_R, true);
	displayDrawCircle(APRS_WIN_CX, APRS_WIN_CY, APRS_WIN_R - 1, true);
	displayDrawLine(APRS_WIN_CX, (int16_t)(APRS_WIN_CY - APRS_WIN_R + 2), APRS_WIN_CX, (int16_t)(APRS_WIN_CY - APRS_WIN_R + 6), true);
	displayDrawLine(APRS_WIN_CX, (int16_t)(APRS_WIN_CY + APRS_WIN_R - 2), APRS_WIN_CX, (int16_t)(APRS_WIN_CY + APRS_WIN_R - 6), true);
	displayDrawLine((int16_t)(APRS_WIN_CX - APRS_WIN_R + 2), APRS_WIN_CY, (int16_t)(APRS_WIN_CX - APRS_WIN_R + 6), APRS_WIN_CY, true);
	displayDrawLine((int16_t)(APRS_WIN_CX + APRS_WIN_R - 2), APRS_WIN_CY, (int16_t)(APRS_WIN_CX + APRS_WIN_R - 6), APRS_WIN_CY, true);
	displayPrintCore((int16_t)(APRS_WIN_CX - 6), 22, APRSRX_WIN_N, FONT_SIZE_1, TEXT_ALIGN_LEFT, false);
}

#define APRS_WIN_ROW_H    9
#define APRS_WIN_ROW_MAX  89   /* верх останнього рядка: рядок займає 8 px, далі -- рядок символу (y = 100) */
#define APRS_WIN_COLS     13   /* (APRS_WIN_CX - APRS_WIN_R - 4 - 4) / 6 */

static void aprsWinRow(int16_t *y, const char *txt)
{
	char b[APRS_WIN_COLS + 1];

	if (*y > APRS_WIN_ROW_MAX)
	{
		return;
	}
	snprintf(b, sizeof b, "%s", txt);
	displayPrintCore(4, *y, b, FONT_SIZE_1, TEXT_ALIGN_LEFT, false);
	*y = (int16_t)(*y + APRS_WIN_ROW_H);
}

/* Зсув у кГц -> «-7.6» / «+0.6» / «-12.5» (без зайвих нулів); 0 -- порожньо. */
static void aprsWinShiftStr(char *o, size_t size, int shiftKHz)
{
	unsigned a = (unsigned)((shiftKHz < 0) ? -shiftKHz : shiftKHz);
	unsigned frac = (a % 1000U) / 10U;   /* соті частки МГц */

	if (shiftKHz == 0)
	{
		o[0] = 0;
		return;
	}
	if ((frac % 10U) == 0U)
	{
		snprintf(o, size, "%c%u.%u", (shiftKHz < 0) ? '-' : '+', a / 1000U, frac / 10U);
	}
	else
	{
		snprintf(o, size, "%c%u.%02u", (shiftKHz < 0) ? '-' : '+', a / 1000U, frac);
	}
}

static void aprsWinInfoRows(const aprsRxWin_t *w, int16_t y)
{
	char buf[24];

	if (w->course != 0U)
	{
		snprintf(buf, sizeof buf, APRSRX_WIN_COURSE, (unsigned)w->course);
		aprsWinRow(&y, buf);
	}
	if (w->speedKn != 0U)
	{
		snprintf(buf, sizeof buf, APRSRX_WIN_SPEED, (unsigned)aprsKnotsToKmh(w->speedKn));
		aprsWinRow(&y, buf);
	}
	if (w->flags & AWIN_F_ALT)
	{
		snprintf(buf, sizeof buf, APRSRX_WIN_ALT, (long)w->altM);
		aprsWinRow(&y, buf);
	}
	if (w->wxMask != 0U)
	{
		/* погода: °F->°C і mph->км/год перераховані в парсері/тут; тиск 0.1 гПа */
		if ((w->wxMask & APRS_WX_TEMP) && (w->wxMask & APRS_WX_HUM))
		{
			snprintf(buf, sizeof buf, APRSRX_WIN_TEMPHUM, (int)w->u.wx.tempC, (unsigned)w->u.wx.humPct);
			aprsWinRow(&y, buf);
		}
		else if (w->wxMask & APRS_WX_TEMP)
		{
			snprintf(buf, sizeof buf, APRSRX_WIN_TEMP, (int)w->u.wx.tempC);
			aprsWinRow(&y, buf);
		}
		else if (w->wxMask & APRS_WX_HUM)
		{
			snprintf(buf, sizeof buf, APRSRX_WIN_HUM, (unsigned)w->u.wx.humPct);
			aprsWinRow(&y, buf);
		}
		if (w->wxMask & APRS_WX_PRESS)
		{
			snprintf(buf, sizeof buf, APRSRX_WIN_PRESS, (unsigned)(w->u.wx.pressDhPa / 10U), (unsigned)(w->u.wx.pressDhPa % 10U));
			aprsWinRow(&y, buf);
		}
		if (w->wxMask & APRS_WX_WIND)
		{
			snprintf(buf, sizeof buf, APRSRX_WIN_WIND, (unsigned)w->u.wx.windDeg);
			aprsWinRow(&y, buf);
			snprintf(buf, sizeof buf, APRSRX_WIN_SPEED, (unsigned)(((unsigned long)w->u.wx.windMph * 1609UL + 500UL) / 1000UL));
			aprsWinRow(&y, buf);
		}
		if (w->wxMask & APRS_WX_GUST)
		{
			snprintf(buf, sizeof buf, APRSRX_WIN_GUST, (unsigned)(((unsigned long)w->u.wx.gustMph * 1609UL + 500UL) / 1000UL));
			aprsWinRow(&y, buf);
		}
	}
	else
	{
		char sh[10];

		if (w->u.r.freqKHz != 0U)
		{
			snprintf(buf, sizeof buf, APRSRX_WIN_FREQ, (unsigned long)(w->u.r.freqKHz / 1000U), (unsigned long)(w->u.r.freqKHz % 1000U));
			aprsWinRow(&y, buf);
		}
		sh[0] = 0;
		if (w->flags & AWIN_F_SHIFT)
		{
			aprsWinShiftStr(sh, sizeof sh, w->u.r.shiftKHz);
		}
		if (w->u.r.tone[0] != 0)
		{
			snprintf(buf, sizeof buf, "%s%s%s%s", w->u.r.tone, (sh[0] != 0) ? " " : "", sh, (sh[0] != 0) ? APRSRX_WIN_MHZ : "");
			aprsWinRow(&y, buf);
		}
		else if (sh[0] != 0)
		{
			snprintf(buf, sizeof buf, "%s %s", sh, APRSRX_WIN_MHZ);
			aprsWinRow(&y, buf);
		}
		if ((w->extKind == APRS_EXT_PHG) || (w->extKind == APRS_EXT_DFS))
		{
			snprintf(buf, sizeof buf, "%s%04X", (w->extKind == APRS_EXT_PHG) ? "PHG" : "DFS", (unsigned)w->u.r.extVal);
			aprsWinRow(&y, buf);
		}
		{
			/* радіус: з коментаря/стисненої позиції (милі або км) або поле RNGnnnn (милі) */
			unsigned km = 0;

			if (w->u.r.rangeVal != 0U)
			{
				km = (w->flags & AWIN_F_RANGE_KM) ? (unsigned)w->u.r.rangeVal : (unsigned)(((unsigned long)w->u.r.rangeVal * 1609UL + 500UL) / 1000UL);
			}
			else if ((w->extKind == APRS_EXT_RNG) && (w->u.r.extVal != 0U))
			{
				km = (unsigned)(((unsigned long)w->u.r.extVal * 1609UL + 500UL) / 1000UL);
			}
			if (km != 0U)
			{
				snprintf(buf, sizeof buf, APRSRX_WIN_RANGE, km);
				aprsWinRow(&y, buf);
			}
		}
	}
}

/* Піктограма символу 24x24 (R17 Г5; була 16x16). Накладка (таблиця -- цифра/літера): знак у блоці 8x8 у правому нижньому куті піктограми з ІНВЕРСНИМ
 * тлом (суцільний блок кольору переднього плану, знак -- кольором тла): читається на будь-якій піктограмі. Невідомий символ -- рамка 24x24 з самим
 * знаком коду (FONT_SIZE_1, по центру). */
static void aprsWinDrawSymbol(int16_t x, int16_t y, const aprsRxWin_t *w)
{
	bool ov = false;
	const uint8_t *ic = aprsIconFind(w->symTable, w->symCode, &ov);
	char one[2];

	one[1] = 0;
	if (ic != NULL)
	{
		displayDrawXBitmap(x, y, ic, APRS_ICON_W, APRS_ICON_H, true);
		if (ov)
		{
			one[0] = w->symTable;
			displayFillRect((int16_t)(x + APRS_ICON_W - 8), (int16_t)(y + APRS_ICON_H - 8), 8, 8, false);   /* false -- колір переднього плану: інверсне тло */
			displayPrintCore((int16_t)(x + APRS_ICON_W - 7), (int16_t)(y + APRS_ICON_H - 8), one, FONT_SIZE_1, TEXT_ALIGN_LEFT, true);
		}
	}
	else
	{
		displayDrawRect(x, y, APRS_ICON_W, APRS_ICON_H, true);
		one[0] = ((w->symCode >= 0x20) && (w->symCode < 0x7F)) ? w->symCode : '?';
		displayPrintCore((int16_t)(x + (APRS_ICON_W / 2) - 3), (int16_t)(y + (APRS_ICON_H / 2) - 4), one, FONT_SIZE_1, TEXT_ALIGN_LEFT, false);
	}
}

static void displayAprsBeaconWindow(void)
{
	const aprsRxWin_t *w = aprsRxWindow();
	char buf[40];
	char tm[12];
	int tl;
	int16_t y;

	displayThemeApply(THEME_ITEM_FG_NOTIFICATION, THEME_ITEM_BG_NOTIFICATION);
	displayFillRect(0, 0, DISPLAY_SIZE_X, DISPLAY_SIZE_Y, true);
	displayThemeApply(THEME_ITEM_FG_DECORATION, THEME_ITEM_BG_NOTIFICATION);
	displayDrawRect(0, 0, DISPLAY_SIZE_X, DISPLAY_SIZE_Y, true);

	/* Позивний-SSID великим шрифтом і час прийому праворуч. */
	displayThemeApply(THEME_ITEM_FG_NOTIFICATION, THEME_ITEM_BG_NOTIFICATION);
	displayPrintCore(4, 3, w->call, FONT_SIZE_3, TEXT_ALIGN_LEFT, false);
	tl = uiSmsTimeStr(w->rxSecs, SMS_TIME_HM, tm, sizeof tm);
	if (tl > 0)
	{
		displayPrintCore((int16_t)(DISPLAY_SIZE_X - 4 - tl * 6), 3, tm, FONT_SIZE_1, TEXT_ALIGN_LEFT, false);
	}
	{
		/* R17 Г4: «n/m» -- номер станції в списку, між якою гортають стрілки; праворуч угорі, над часом (час -- y = 3, «n/m» -- y = 12). Одна станція -- нічого. */
		int pn, pm;

		if (aprsRxWindowPos(&pn, &pm) && (pm > 1))
		{
			char nm[8];
			int nl = snprintf(nm, sizeof nm, "%d/%d", pn, pm);

			if (nl > 0)
			{
				displayPrintCore((int16_t)(DISPLAY_SIZE_X - 4 - nl * 6), 12, nm, FONT_SIZE_1, TEXT_ALIGN_LEFT, false);
			}
		}
	}
	displayThemeApply(THEME_ITEM_FG_DECORATION, THEME_ITEM_BG_NOTIFICATION);
	displayDrawFastHLine(3, 20, DISPLAY_SIZE_X - 6, true);
	displayThemeApply(THEME_ITEM_FG_NOTIFICATION, THEME_ITEM_BG_NOTIFICATION);

	y = 26;
	if (w->hasGeo)
	{
		/* Ліва колонка: «відстань азимут°» одним рядком (R14: без буквеного сектора й пояснення «від Пн» -- є стрілка). */
		char d[12];

		aprsRxFormatDist(d, sizeof d, w->distM);
		snprintf(buf, sizeof buf, APRSRX_WIN_DIST_AZ, d, (unsigned)w->bearing);
		displayPrintCore(4, y, buf, FONT_SIZE_3, TEXT_ALIGN_LEFT, false);
		y += 18;

		/* Кільце, риски, мітка «Пн» і стрілка. Дистанція 0 -- азимут не визначений, стрілки нема. */
		aprsWinDrawRing();
		if (aprsBeaconArrowVisible(true, w->distM))
		{
			aprsWinDrawArrow(w->bearing);
		}
	}
	else
	{
		/* Нашої або станційної позиції нема: ні стрілки, ні відстані -- лише це й решта даних. */
		displayPrintCore(4, y, APRSRX_WIN_NOPOS, FONT_SIZE_3, TEXT_ALIGN_LEFT, false);
		y += 18;
	}

	/* R14: решта даних пакета -- по рядку, лише наявні, x = 4..86 (13 символів: правіше кільце), крок 9 px, до y = 97. */
	aprsWinInfoRows(w, y);

	/* Символ APRS: піктограма 24x24 (x = 4, y = 100..123), праворуч назва (R15: без другого рядка «таблиця+код» -- він лишається ЛИШЕ тоді, коли назви нема:
	 * кадр із кодом, якого немає в нашій таблиці назв), нижче коментар у ДВА рядки з перенесенням за словами (aprsMsgWrapLine()). R17 Г5: піктограма
	 * зайняла висоту обох рядків коментаря, тож з піктограмою ОБИДВА рядки йдуть праворуч від неї (x = 32, по 20 символів: 40 >= 27, коментар влізає
	 * цілком); без символу -- як було: x = 4, 25 символів. */
	bool haveSym = (w->symCode != 0);

	if (haveSym)
	{
		const char *nm = aprsSymbolNameEx(w->symTable, w->symCode);

		aprsWinDrawSymbol(4, 100, w);
		if (nm != NULL)
		{
			snprintf(buf, sizeof buf, "%s", nm);
		}
		else
		{
			snprintf(buf, sizeof buf, APRSRX_WIN_SYM2_FMT, (w->symTable != 0) ? w->symTable : ' ', w->symCode);
		}
		buf[(DISPLAY_SIZE_X - 36) / 6] = 0;
		displayPrintCore(32, 101, buf, FONT_SIZE_1, TEXT_ALIGN_LEFT, false);
	}
	if (w->text[0])
	{
		const int len = (int)strlen(w->text);
		const int16_t x1 = haveSym ? 32 : 4;
		const int w1 = (DISPLAY_SIZE_X - x1 - 4) / 6;
		const int w2 = w1;
		int ls = 0, nx = 0, n;

		n = aprsMsgWrapLine(w->text, len, 0, w1, &ls, &nx);
		if ((n > 0) && (n < (int)sizeof buf))
		{
			memcpy(buf, w->text + ls, (size_t)n);
			buf[n] = 0;
			displayPrintCore(x1, 109, buf, FONT_SIZE_1, TEXT_ALIGN_LEFT, false);
		}
		if (nx < len)
		{
			n = aprsMsgWrapLine(w->text, len, nx, w2, &ls, &nx);
			if ((n > 0) && (n < (int)sizeof buf))
			{
				memcpy(buf, w->text + ls, (size_t)n);
				buf[n] = 0;
				displayPrintCore(x1, 117, buf, FONT_SIZE_1, TEXT_ALIGN_LEFT, false);
			}
		}
	}
}
#endif /* APRS_RX */

/* Форк: вхідне SMS на ВЕСЬ екран, тримається до RED.
 * ui6 (2026-10-05): угорі -- відправник («Від ...», як на екрані читання; для перехопленого
 * монітором -- «ВІД -> КОМУ») і праворуч час прийому; нижче -- текст шрифтом 8x16 з перенесенням
 * за словами (uiSmsDrawWrapped/smsWrapLine -- та сама функція, що на екрані читання); унизу --
 * ЗАГАЛЬНА кількість непрочитаних разом із показаним («4 непрочитаних»), якщо їх більше одного.
 * Текст і відправник беруться зі сховища (dmrSmsNewestInbox: відкладене або найновіше вхідне),
 * а не з notificationData.message: той буфер лише 68 Б, тобто довше SMS обрізалось би ще до
 * екрана. message лишається запасним варіантом, коли вхідних немає. */
static void displaySmsFullScreen(void)
{
	const int16_t lineH = FONT_SIZE_3_HEIGHT;      /* 16: font_8x16, 8 px завширшки */
	const int16_t cntH  = FONT_SIZE_2_HEIGHT;      /* 8: рядок лічильника */
	const int16_t textY = 14;                      /* під рядком відправника і рискою */
	const int cols = (DISPLAY_SIZE_X - 6) / 8;     /* 19: x = 3, рамка по краях */
	uint32_t t = 0;
	const dmrSmsMessage_t *m = dmrSmsNewestInbox(&t);
	int unread = dmrSmsUnreadCount();

#if defined(APRS_RX)
	if (notificationData.id == NOTIFICATION_ID_APRS_BEACON)
	{
		displayAprsBeaconWindow();   /* R13: вікно маяка -- власна розкладка, сховище SMS не чіпаємо */
		return;
	}
#endif
#if defined(ENABLE_APRS_RX)
	if (notificationData.id == NOTIFICATION_ID_APRS_MSG)
	{
		/* R11-fix2: повідомлення APRS не лежить у сховищі SMS -- малюємо його власний текст, а не останнє SMS DMR, і лічильник DMR не чіпаємо */
		m = NULL;
		unread = 0;
	}
#endif

	int16_t reserved = (int16_t)((unread > 1) ? (cntH + 2) : 0);
	int16_t maxLines = (int16_t)((DISPLAY_SIZE_Y - textY - 2 - reserved) / lineH);
	if (maxLines < 1) { maxLines = 1; }

	/* Фон на весь екран + рамка (полярність isInverted -- як і раніше, див. displayFillRect/DrawRect). */
	displayThemeApply(THEME_ITEM_FG_NOTIFICATION, THEME_ITEM_BG_NOTIFICATION);
	displayFillRect(0, 0, DISPLAY_SIZE_X, DISPLAY_SIZE_Y, true);
	displayThemeApply(THEME_ITEM_FG_DECORATION, THEME_ITEM_BG_NOTIFICATION);
	displayDrawRect(0, 0, DISPLAY_SIZE_X, DISPLAY_SIZE_Y, true);

	if (m == NULL)
	{
		displayThemeApply(THEME_ITEM_FG_NOTIFICATION, THEME_ITEM_BG_NOTIFICATION);
		uiSmsDrawWrapped(notificationData.message, (int)strlen(notificationData.message), cols, 0, maxLines + 1,
				3, 2, lineH, FONT_SIZE_3, 1);
		return;
	}

	/* Рядок відправника (FONT_SIZE_1, 6 px): час праворуч, відправник -- скільки влізе ліворуч. */
	{
		char tm[12];
		char who[20], whom[20];
		char hdr[44];
		int tl = uiSmsTimeStr(t, SMS_TIME_HM, tm, sizeof tm);
		int maxChars = (DISPLAY_SIZE_X - 6 - (tl ? (tl * 6 + 6) : 0)) / 6;

#if defined(ENABLE_APRS_RX)
		if (m->flags & DMR_SMS_FLAG_APRS)
		{
			snprintf(who, sizeof who, "APRS");   /* R8: повідомлення APRS -- відправник уже в тексті («CALL: ...») */
		}
		else
#endif
		uiSmsWhoStr(m->peerId, 0, who, sizeof who);
		if (m->flags & DMR_SMS_FLAG_FOREIGN)
		{
			uiSmsWhoStr(dmrSmsLastRxDst(), (m->flags & DMR_SMS_FLAG_GROUP) ? 1 : 0, whom, sizeof whom);
			snprintf(hdr, sizeof hdr, "%s -> %s", who, whom);
		}
		else
		{
			snprintf(hdr, sizeof hdr, "%s %s", MSGS_FROM, who);
		}
		if (maxChars < 0) { maxChars = 0; }
		if (maxChars < (int)sizeof hdr) { hdr[maxChars] = 0; }   /* обрізати, щоб влізло в рядок */

		displayThemeApply((m->flags & DMR_SMS_FLAG_FOREIGN) ? THEME_ITEM_FG_WARNING_NOTIFICATION : THEME_ITEM_FG_NOTIFICATION,
				THEME_ITEM_BG_NOTIFICATION);
		displayPrintCore(3, 3, hdr, FONT_SIZE_1, TEXT_ALIGN_LEFT, false);
		displayThemeApply(THEME_ITEM_FG_NOTIFICATION, THEME_ITEM_BG_NOTIFICATION);
		if (tl > 0)
		{
			displayPrintCore((int16_t)(DISPLAY_SIZE_X - 3 - tl * 6), 3, tm, FONT_SIZE_1, TEXT_ALIGN_LEFT, false);
		}
		displayThemeApply(THEME_ITEM_FG_DECORATION, THEME_ITEM_BG_NOTIFICATION);
		displayDrawFastHLine(3, 12, DISPLAY_SIZE_X - 6, true);   /* true -- видима риска (полярність як у DrawRect) */
	}

	/* Текст: перенесення за словами; не влізло -- «...» в кінці останнього рядка. */
	displayThemeApply(THEME_ITEM_FG_NOTIFICATION, THEME_ITEM_BG_NOTIFICATION);
	uiSmsDrawWrapped(m->text, m->textLen, cols, 0, maxLines, 3, textY, lineH, FONT_SIZE_3, 1);

	/* Загальна кількість непрочитаних, разом із показаним (ui6; до ui6 -- «ще N» без нього). */
	if (unread > 1)
	{
		char cnt[24];
		int f = smsPluralForm(unread);
		snprintf(cnt, sizeof cnt, (f == 0) ? MSGS_UNREAD1_FMT : ((f == 1) ? MSGS_UNREAD2_FMT : MSGS_UNREAD5_FMT), unread);
		displayThemeApply(THEME_ITEM_FG_WARNING_NOTIFICATION, THEME_ITEM_BG_NOTIFICATION);
		displayPrintCentered((int16_t)(DISPLAY_SIZE_Y - cntH - 2), cnt, FONT_SIZE_2);
		displayThemeApply(THEME_ITEM_FG_NOTIFICATION, THEME_ITEM_BG_NOTIFICATION);
	}
}
#else
/* Форк: вхідне SMS на ВЕСЬ екран, з переносом по словах, тримається до RED.
 * Чому не звичайний банер: той малює 3-4 рядки по 14 символів у рамці й гасне за 4 с --
 * для повідомлення до 144 символів цього замало, а якщо рація лежала в розвантажці, воно
 * зникало непоміченим. Тут використовуємо всю площу й чекаємо на оператора. */
static void displaySmsFullScreen(void)
{
	/* ВЕЛИКИЙ шрифт: font_8x16 (FONT_SIZE_3) -- 8 px завширшки, 16 завввишки. Ширина
	 * символу та сама, що в FONT_SIZE_2, тож у рядок так само влазить 19 символів, а от
	 * рядків стає вдвічі менше. Тому підказку "RED" прибрано (оператор і так знає, а
	 * місце вона з'їдала цілим рядком), а лічильник непрочитаних лишили дрібним. */
	const int16_t charW = 8;
	const int16_t lineH = FONT_SIZE_3_HEIGHT;      /* 16 */
	const int16_t cntH  = FONT_SIZE_2_HEIGHT;      /* 8 -- рядок "ще N непрочит." */
	int16_t perLine = (int16_t)((DISPLAY_SIZE_X - 6) / charW);
	char line[32];
	int more = 0;

#if defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)
	more = dmrSmsUnreadCount() - 1;                /* показане теж рахується непрочитаним */
	if (more < 0) { more = 0; }
#endif

	/* Рядок лічильника з'їдає місце лише тоді, коли він справді є. */
	int16_t reserved = (int16_t)((more > 0) ? (cntH + 2) : 0);
	int16_t maxLines = (int16_t)((DISPLAY_SIZE_Y - 4 - reserved) / lineH);

	if (perLine > (int16_t)(sizeof line - 1)) { perLine = (int16_t)(sizeof line - 1); }
	if (maxLines < 1) { maxLines = 1; }

	/* Фон на весь екран + рамка. isInverted=true -> заливка КОЛЬОРОМ ФОНУ
	 * (displayFillRect: isInverted ? bg : fg); у displayDrawRect полярність обернена
	 * (лінія через !isInverted), тож видима рамка -- теж true. */
	displayThemeApply(THEME_ITEM_FG_NOTIFICATION, THEME_ITEM_BG_NOTIFICATION);
	displayFillRect(0, 0, DISPLAY_SIZE_X, DISPLAY_SIZE_Y, true);
	displayThemeApply(THEME_ITEM_FG_DECORATION, THEME_ITEM_BG_NOTIFICATION);
	displayDrawRect(0, 0, DISPLAY_SIZE_X, DISPLAY_SIZE_Y, true);
	displayThemeApply(THEME_ITEM_FG_NOTIFICATION, THEME_ITEM_BG_NOTIFICATION);

	const char *p = notificationData.message;
	int16_t y = 2;
	int16_t used = 0;

	while ((*p != 0) && (used < maxLines))
	{
		while (*p == ' ') { p++; }               /* не починати рядок із пробілу */
		if (*p == 0) { break; }

		int16_t n = 0;
		int16_t lastSpace = -1;
		while ((p[n] != 0) && (p[n] != '\n') && (n < perLine))
		{
			if (p[n] == ' ') { lastSpace = n; }
			n++;
		}
		/* Перенос по словах: рвемо на останньому пробілі, якщо рядок обірвався посеред слова. */
		if ((p[n] != 0) && (p[n] != '\n') && (lastSpace > 0)) { n = lastSpace; }

		memcpy(line, p, (size_t)n);
		line[n] = 0;

		p += n;
		if (*p == '\n') { p++; }
		used++;

		/* Не влізло все -- ставимо трикрапку в кінці останнього рядка, щоб оператор бачив,
		 * що текст обрізано, і відкрив «Вхідні». Без цього обрізання виглядає як повний текст. */
		if ((used == maxLines) && (*p != 0) && (n > 0))
		{
			/* Саме ТРИ крапки: одна читалась би як звичайна крапка в кінці речення. */
			int16_t cut = (int16_t)((n <= (perLine - 3)) ? n : (perLine - 3));
			if (cut < 0) { cut = 0; }
			line[cut] = '.'; line[cut + 1] = '.'; line[cut + 2] = '.';
			line[cut + 3] = 0;
		}

		displayPrintCore(3, y, line, FONT_SIZE_3, TEXT_ALIGN_LEFT, false);
		y += lineH;
	}

	/* Скільки ще НЕпрочитаних, крім показаного -- окремим кольором (колір попередження),
	 * щоб не злилось із текстом самого повідомлення. */
#if defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)
	if (more > 0)
	{
		char cnt[24];
		snprintf(cnt, sizeof cnt, MSGS_MORE_UNREAD_FMT, more);
		displayThemeApply(THEME_ITEM_FG_WARNING_NOTIFICATION, THEME_ITEM_BG_NOTIFICATION);
		displayPrintCentered((int16_t)(DISPLAY_SIZE_Y - cntH - 2), cnt, FONT_SIZE_2);
		displayThemeApply(THEME_ITEM_FG_NOTIFICATION, THEME_ITEM_BG_NOTIFICATION);
	}
#endif
}
#endif /* ENABLE_AES && ENABLE_DMR_DATA */

#if defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)
/* Форк (2026-09-26): вхідний Call Alert (RCTL, claude/call-alert-reverse.md) -- на весь
 * екран, тримається до RED, той самий фон/рамка, що й displaySmsFullScreen() вище. Вміст
 * короткий (заголовок + ім'я/ID абонента), тож, на відміну від SMS, є місце й для
 * підказки закриття внизу. */
static void displayCallAlertFullScreen(void)
{
	char buffer[SCREEN_LINE_BUFFER_SIZE];

	displayThemeApply(THEME_ITEM_FG_NOTIFICATION, THEME_ITEM_BG_NOTIFICATION);
	displayFillRect(0, 0, DISPLAY_SIZE_X, DISPLAY_SIZE_Y, true);
	displayThemeApply(THEME_ITEM_FG_DECORATION, THEME_ITEM_BG_NOTIFICATION);
	displayDrawRect(0, 0, DISPLAY_SIZE_X, DISPLAY_SIZE_Y, true);
	displayThemeApply(THEME_ITEM_FG_NOTIFICATION, THEME_ITEM_BG_NOTIFICATION);

	displayPrintCentered(16, RCTL_CALL_ALERT_TITLE, FONT_SIZE_3);

	strncpy(buffer, notificationData.message, (SCREEN_LINE_BUFFER_SIZE - 1));
	buffer[SCREEN_LINE_BUFFER_SIZE - 1] = 0;
	displayPrintCentered(44, buffer, FONT_SIZE_3); /* FONT_SIZE_3: довгі імена (напр. "UW5ELK Богдан") влазять у рядок (rev2 polish) */

	displayPrintCentered((int16_t)(DISPLAY_SIZE_Y - FONT_SIZE_1_HEIGHT - 4), RCTL_CALL_ALERT_HINT, FONT_SIZE_1);
}

/* Форк (ui1, 2026-10-04): «SMS доставлено» -- велика зелена галочка по центру, без тексту.
 * Чому не текстовий банер: «SMS: доставлено» шрифтом FONT_SIZE_3 у рамці на 14 символів
 * обрізався («SMS: доставлен»), а рамка не закривала екран під собою. Тут -- той самий фон
 * і рамка на весь екран, що й у displaySmsFullScreen(), і галочка ~48x36 px товщиною ~4 px.
 * Колір -- зелений із теми (THEME_ITEM_FG_RSSI_BAR: день 0x006400, ніч 0x33FF33), тож
 * контраст до тла сповіщення вже підібраний для обох тем. */
#define SMS_ACK_CHECK_X0     58   /* ліва точка короткого штриха */
#define SMS_ACK_CHECK_Y0     62
#define SMS_ACK_CHECK_XM     72   /* нижня точка (злам) */
#define SMS_ACK_CHECK_YM     76
#define SMS_ACK_CHECK_X1    104   /* верхня права точка довгого штриха */
#define SMS_ACK_CHECK_Y1     44
#define SMS_ACK_CHECK_THICK   5   /* паралельних ліній зі зсувом по вертикалі: ~3.5 px упоперек */
static void displaySmsAckedFullScreen(void)
{
	displayThemeApply(THEME_ITEM_FG_NOTIFICATION, THEME_ITEM_BG_NOTIFICATION);
	displayFillRect(0, 0, DISPLAY_SIZE_X, DISPLAY_SIZE_Y, true);
	displayThemeApply(THEME_ITEM_FG_DECORATION, THEME_ITEM_BG_NOTIFICATION);
	displayDrawRect(0, 0, DISPLAY_SIZE_X, DISPLAY_SIZE_Y, true);

	displayThemeApply(THEME_ITEM_FG_RSSI_BAR, THEME_ITEM_BG_NOTIFICATION);
	for (int16_t k = 0; k < SMS_ACK_CHECK_THICK; k++)
	{
		displayDrawLine(SMS_ACK_CHECK_X0, (SMS_ACK_CHECK_Y0 + k), SMS_ACK_CHECK_XM, (SMS_ACK_CHECK_YM + k), true);
		displayDrawLine(SMS_ACK_CHECK_XM, (SMS_ACK_CHECK_YM + k), SMS_ACK_CHECK_X1, (SMS_ACK_CHECK_Y1 + k), true);
	}
	displayThemeApply(THEME_ITEM_FG_NOTIFICATION, THEME_ITEM_BG_NOTIFICATION);
}
#endif

static void displayMessage(void)
{
	char msg[SCREEN_LINE_BUFFER_SIZE];
	size_t len = strlen(notificationData.message);
	char *pb = notificationData.message;
	char *pe = &notificationData.message[0] + len;
	char *p = strchr(notificationData.message, '\n');
	uint16_t count;
	uint16_t y = 0U;
	uint8_t linesCount = 1U;
	uint8_t maxLines =
#if defined(HAS_COLOURS) || defined(PLATFORM_RD5R)
			4U;
#else
			3U;
#endif

	while (p)
	{
		linesCount++;

		if (linesCount == maxLines)
		{
			break;
		}

		p = strchr(p + 1, '\n');
	}

	y = (((DISPLAY_SIZE_Y - (linesCount * FONT_SIZE_3_HEIGHT)) >> 1) - 3);

	displayThemeApply(THEME_ITEM_FG_DECORATION, THEME_ITEM_BG_NOTIFICATION);
	displayDrawRoundRectWithDropShadow(1, (y - 1), (DISPLAY_SIZE_X - 4), ((FONT_SIZE_3_HEIGHT * linesCount) + 6), 3, true);
	displayThemeApply(THEME_ITEM_FG_NOTIFICATION, THEME_ITEM_BG_NOTIFICATION);

	p = strchr(notificationData.message, '\n');

	while (linesCount > 1U)
	{
		count = SAFE_MIN((uint16_t)(p - pb), 14U);

		memcpy(msg, pb, count);
		msg[count] = '\0';

		displayPrintCentered(y, msg, FONT_SIZE_3);
		y += FONT_SIZE_3_HEIGHT;

		pb = p + 1;
		p = strchr(pb, '\n');

		linesCount--;
	}

	if (pb < pe)
	{
		count = SAFE_MIN((uint16_t)(pe - pb), 14U);

		p++;

		// Looking for another new line
		if ((p = strchr(pb, '\n')) != NULL)
		{
			count = (uint16_t)(p - pb);
		}

		memcpy(msg, pb, count);
		msg[count] = '\0';

		displayPrintCentered(y, msg, FONT_SIZE_3);
	}
}
