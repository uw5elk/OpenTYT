/*
 * menuMessages.c — on-radio encrypted DMR SMS UX (Inbox / Sent / New Message).
 *
 * Modelled on menuAESKeys.c. A small screen state-machine:
 *   HOME         : Inbox (n) / Sent (n) / New Message
 *   LIST         : the messages of a folder + a "[Delete all]" row
 *   READ         : full text of one message
 *   COMPOSE      : keypad text entry (multi-tap, like the contact-name editor)
 *   RECIPIENT    : destination DMR ID / talkgroup + Group/Private + send
 *   PICK_CONTACT : browse the existing codeplug Contact List instead of typing an ID
 *
 * Key combos (2026-08-31 pass — moved into the main menu, added Reply/Resend, a
 * contacts-based recipient picker, and "mark all read", on top of what already existed):
 *   HOME/LIST : GREEN opens/selects, SK2+GREEN deletes (single, or "[Delete all]" row),
 *               SK2+RED marks every Inbox message read in one go.
 *   READ      : SK2+GREEN deletes; plain GREEN = Reply (Inbox: blank text, recipient
 *               pre-set to the sender) or Resend (Sent: text AND recipient both
 *               pre-filled, lands straight on RECIPIENT); RED goes back.
 *   RECIPIENT : SK1 opens PICK_CONTACT, browsing the Contact List filtered by the
 *               current Group/Private toggle (U/D), so the entry you land on already
 *               matches what you're about to pick.
 *
 * Sending and the store live in functions/dmr_sms.c (the on-air-validated AES-256-ECB
 * scheme a stock TYT decrypts). Compiles to nothing unless -DENABLE_AES -DENABLE_DMR_DATA.
 *
 * LEGAL: encrypted traffic is illegal on amateur bands in most jurisdictions. PMR/commercial.
 */
#include "user_interface/uiGlobals.h"
#include "user_interface/menuSystem.h"
#include "user_interface/uiLocalisation.h"
#include "user_interface/uiUtilities.h"
#include "functions/trx.h"
#include "functions/dmr_sms.h"
#include "functions/ticks.h"   // ticksTimer_t: реальний час замість лічби тіків
#include "functions/codeplug.h"   /* Contact List browsing for the recipient picker */
#include "crypto/dmr_aes.h"
#include "io/keyboard.h"

/*
 * Рядки цього екрана перемикаються на етапі компіляції, а не через stringsTable_t:
 * SMS -- функція саме цього форку, а таблицю рядків читає ще й мовний файл від CPS,
 * тож три десятки нових полів зламали б ту сумісність і з'їли б ~1 КБ флеша в кожній
 * збірці. Українські значення лежать у languages/messages_ua.h (кодування cp1251).
 */
#if defined(LANGUAGE_BUILD_UKRAINIAN)
#include "user_interface/languages/messages_ua.h"
#else
#define MSGS_TITLE               "Messages"
#define MSGS_INBOX_FMT           "Inbox (%d)"
#define MSGS_SENT_FMT            "Sent (%d)"
#define MSGS_NEW                 "New Message"
#define MSGS_TITLE_SENT          "Sent"
#define MSGS_TITLE_INBOX         "Inbox"
#define MSGS_EMPTY               "(empty)"
#define MSGS_HINT_BACK           "RED:back"
#define MSGS_DELETE_ALL          "[Delete all]"
#define MSGS_TO                  "To"
#define MSGS_FROM                "From"
#define MSGS_HINT_SENT_ITEM      "SK2+GRN:del GRN:resend"
#define MSGS_HINT_INBOX_ITEM     "SK2+GRN:del GRN:reply"
#define MSGS_TITLE_NEW           "New Message"
#define MSGS_CHARS_FMT           "%d/%d chars"
#define MSGS_HINT_PRESET         "U:preset  L:del"
#define MSGS_HINT_TO_CANCEL      "GRN:to  RED:cancel"
#define MSGS_TITLE_RCPT          "Recipient"
#define MSGS_TO_FMT              "To: %s"
#define MSGS_TYPE_FMT            "Type: %s"
#define MSGS_GROUP               "Group"
#define MSGS_PRIVATE             "Private"
#define MSGS_HINT_ID             "0-9:id  L:del"
#define MSGS_HINT_GRP_PRIV       "U/D:Group/Private"
#define MSGS_HINT_CONTACTS       "SK1:contacts"
#define MSGS_HINT_SEND_BACK      "GRN:send  RED:back"
#define MSGS_TITLE_PICK_TG       "Pick TG contact"
#define MSGS_TITLE_PICK_PC       "Pick PC contact"
#define MSGS_NO_CONTACTS         "(no contacts)"
#define MSGS_SENT_OK             "Message sent"
#define MSGS_KEYED_TX            "(keyed TX)"
#define MSGS_SEND_FAILED         "Send failed"
#define MSGS_ERR_GENERIC         "error"
#define MSGS_ERR_TX_BUSY         "TX busy"
#define MSGS_ERR_BAD_TEXT        "bad text"
#define MSGS_ERR_TOO_LONG        "too long"
#define MSGS_FAIL_FMT            "%s (ret %d)"
#define MSGS_HINT_ANY_KEY        "any key: back"
#define MSGS_MONITOR_FMT         "Monitor: %s"
#define MSGS_MON_ON              "on"
#define MSGS_MON_OFF             "off"
#define MSGS_FOREIGN             " (not yours)"
#define MSGS_TX_MODE_FMT         "TX: %s"
#define MSGS_TX_MODE_UNCONF      "Unconfirmed"
#define MSGS_TX_MODE_R12         "Confirmed 1/2"
#define MSGS_TX_MODE_R34         "Confirmed 3/4"
/* Екран «Діагностика» (2026-09-30): лічильники ланцюга квитанції. */
#define MSGS_DIAG                "Diagnostics"
#define MSGS_DG_ACK1_FMT         "Ack RX: seen %u q %u"
#define MSGS_DG_ACK2_FMT         "  sent %u stale %u"
#define MSGS_DG_ACK3_FMT         "  delay %u ms"
#define MSGS_DG_DATA1_FMT        "Data: rej %u start %u"
#define MSGS_DG_DATA2_FMT        "  tmo %u nostart %u"
#define MSGS_DG_CONF_FMT         "Our CONF: %u"
#define MSGS_DG_RESP_FMT         "Resp %u tous %u match %u"
#define MSGS_DG_HDR_FMT          "Hdr6 HW %u SW %u bad %u"
#define MSGS_DG_FAST_FMT         "%cFast end: %s"
#define MSGS_DG_HINT             "DN:page 2 long GRN:reset"
/* Сторінка 2 (fix3): лічильники ISR і перемикачі. */
#define MSGS_DIAG2               "Diagnostics 2"
#define MSGS_DG_ISR_FMT          "ISR: t6 %u t8 %u"
#define MSGS_DG_FILT_FMT         "RX filter: t6 %u t8 %u"
#define MSGS_DG_REAL_FMT         "Ack real: %u ms"
#define MSGS_DG_BYP_FMT          "%cRX bypass: %s"
#define MSGS_DG_PRE_FMT          "%cAck preamb: %u"
#define MSGS_DG_TERM_FMT         "%cAck term: %s"
#define MSGS_DG_YES              "yes"
#define MSGS_DG_NO               "no"
#define MSGS_DG_HINT2            "U/D GRN:set long:reset RED"
/* ui1/fix4: етапи затримки квитанції і перемикач цільової паузи. */
#define MSGS_DG_STG_FMT          "Stages: %u+%u+%u+%u"
#define MSGS_DG_PAUSE_FMT        "%cAck pause: %u ms"
/* diag5: сторінка 3 -- де гине вхідний PDU. */
#define MSGS_DIAG3               "Diagnostics 3"
#define MSGS_DG3_PDU_FMT         "PDU: ok %u CRC bad %u"
#define MSGS_DG3_BLK1_FMT        "Blk: nohdr %u busy %u"
#define MSGS_DG3_BLK2_FMT        "  ovf %u extra %u"
#define MSGS_DG3_TICK_FMT        "Loop: notus %u bad %u"
#define MSGS_DG3_PICK_FMT        "Pickup max: %u ms"
#define MSGS_DG3_HINT            "U:page2 D:page4 long:reset"
/* diag6: сторінка 4 -- знімок останнього PDU з «CRC bad». */
#define MSGS_DIAG4               "Diagnostics 4"
#define MSGS_DG4_NONE            "No snapshot yet"
#define MSGS_DG4_SNAP_FMT        "Snap #%u: blk %u HW %02x"
#define MSGS_DG4_CRC_FMT         "CRC w %08lx g %08lx"
#define MSGS_DG4_CNT_FMT         "DBSN bad %u HW t8 ok %u"
#define MSGS_DG4_HDR             "Hdr "
#define MSGS_DG4_HINT            "U/D:scroll long GRN:reset"
/* fix7: сторінка 3 -- корекція трибітів rate-3/4. */
#define MSGS_DG3_FIX1_FMT        "Fix: ok %u ambig %u"
#define MSGS_DG3_FIX2_FMT        "  none %u ms %u max %u"
#endif
#include <string.h>
#include <stdlib.h>

#if defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)

/* Позивний/ім'я замість голого DMR ID: спершу список контактів кодплага, потім база DMR ID
 * (та сама логіка, що й для вхідного дзвінка -- uiPrivateCall.c). Якщо ніде не знайдено --
 * пишемо номер. out має бути >= 20 байт. */
static void smsWhoStr(uint32_t id, char *out, int outsz)
{
	if (contactIDLookup(id, CONTACT_CALLTYPE_PC, out))
	{
		return;
	}
	dmrIdDataStruct_t rec;
	if (dmrIDLookup(id, &rec) && rec.text[0] != 0)
	{
		strncpy(out, rec.text, outsz - 1);
		out[outsz - 1] = 0;
		return;
	}
	snprintf(out, outsz, "%lu", (unsigned long)id);
}

enum { MSG_HOME = 0, MSG_LIST, MSG_READ, MSG_COMPOSE, MSG_RECIPIENT, MSG_PICK_CONTACT, MSG_RESULT, MSG_DIAG };

static struct
{
	uint8_t  view;
	uint8_t  folder;        // 0 = Inbox, 1 = Sent
	int16_t  readIdx;       // message being read
	char     compose[DMR_SMS_TEXT_MAX + 1];
	int16_t  composePos;
	char     rcpt[10];      // numeric recipient entry
	int16_t  rcptPos;
	uint8_t  rcptGroup;     // 1 = talkgroup, 0 = private call
	int8_t   presetIdx;     // last quick-text preset cycled in (-1 = none)
	uint8_t  rcptPreset;    // 1 = rcpt/rcptGroup already set by Reply/Resend; composeEvent's
	                        // GREEN must not clobber it with the usual default-recipient prefill
	int8_t   result;        // dmrSmsSend() return for the result screen
	ticksTimer_t resultTimer;    // скільки ще показувати результат -- РЕАЛЬНИЙ час
	ticksTimer_t resultGuard;    // поки не сплив -- клавіші не закривають екран (див. doSend)
	uint8_t  diagPage;      // екран «Діагностика»: 0 = лічильники, 1 = ISR + перемикачі (fix3), 2 = збирач PDU (diag5)
	uint8_t  diagSel;       // виділений перемикач на сторінці 2 (0..DIAG_TOGGLES-1)
	uint8_t  diagScroll;    // diag6: перший видимий рядок сторінки 4 (знімок «CRC пог»)
} s_msg DMR_AES_CCM;

static void homeUpdate(void);
static void listUpdate(void);
static void readUpdate(void);
static void composeUpdate(void);
static void recipientUpdate(void);
static void pickContactUpdate(void);
static void resultUpdate(void);
static void homeEvent(uiEvent_t *ev, menuStatus_t *ec);
static void listEvent(uiEvent_t *ev);
static void readEvent(uiEvent_t *ev);
static void composeEvent(uiEvent_t *ev);
static void recipientEvent(uiEvent_t *ev);
static void pickContactEvent(uiEvent_t *ev);
static void diagUpdate(void);
static void diagEvent(uiEvent_t *ev);

/* Вхідні / Надіслані / Нове / Монітор / TX режим / Діагностика */
#define MSGS_HOME_ITEMS   6
#define MSGS_DIAG_REFRESH_MS 500   /* екран діагностики оновлюється сам -- лічильники живі */

static void gotoHome(void)
{
	keypadAlphaEnable = false;
	s_msg.view = MSG_HOME;
	menuDataGlobal.currentItemIndex = 0;
	menuDataGlobal.numItems = MSGS_HOME_ITEMS;
	homeUpdate();
}

menuStatus_t menuMessages(uiEvent_t *ev, bool isFirstRun)
{
	if (isFirstRun)
	{
		memset(&s_msg, 0, sizeof s_msg);
		/* Лише перечитати сховище. НЕ dmrSmsInit(): той скидав стан прийому, відкладену
		 * квитанцію, адресата очікуваного ACK, N(S) і всі лічильники діагностики. */
		dmrSmsReloadStore();
		gotoHome();
		return (MENU_STATUS_LIST_TYPE | MENU_STATUS_SUCCESS);
	}

	menuStatus_t exitCode = MENU_STATUS_SUCCESS;

	if (s_msg.view == MSG_RESULT)
	{
		// Клавіші ігноруються, поки не сплив короткий "запобіжник": та сама GREEN, якою
		// надіслали повідомлення, інакше могла б закрити екран результату ще до того, як
		// його встигнуть прочитати (подія відпускання/довгого натискання приходить уже
		// після переходу на цей екран).
		bool keyMayClose = ticksTimerHasExpired(&s_msg.resultGuard);

		if (ticksTimerHasExpired(&s_msg.resultTimer) ||
				(keyMayClose && ev->hasEvent && (ev->events & KEY_EVENT)))
		{
			gotoHome();
			return (MENU_STATUS_LIST_TYPE | MENU_STATUS_SUCCESS);
		}
		return exitCode;
	}

	if (s_msg.view == MSG_DIAG)
	{
		if (ev->hasEvent) { diagEvent(ev); }
		// Живе оновлення: лічильники міняються в ISR, поки оператор дивиться на екран.
		if ((s_msg.view == MSG_DIAG) && ticksTimerHasExpired(&s_msg.resultTimer))
		{
			diagUpdate();
		}
		return exitCode;
	}

	if (ev->hasEvent)
	{
		switch (s_msg.view)
		{
			case MSG_HOME:         homeEvent(ev, &exitCode); break;
			case MSG_LIST:         listEvent(ev);            break;
			case MSG_READ:         readEvent(ev);            break;
			case MSG_COMPOSE:      composeEvent(ev);         break;
			case MSG_RECIPIENT:    recipientEvent(ev);       break;
			case MSG_PICK_CONTACT: pickContactEvent(ev);     break;
		}
	}
	return exitCode;
}

/* ============================ HOME ===================================== */
static void homeUpdate(void)
{
	char buf[24];
	displayClearBuf();
	menuDisplayTitle(MSGS_TITLE);

	for (int i = MENU_START_ITERATION_VALUE; i <= MENU_END_ITERATION_VALUE; i++)
	{
		int mNum = menuGetMenuOffset(MSGS_HOME_ITEMS, i);
		if (mNum == MENU_OFFSET_BEFORE_FIRST_ENTRY) { continue; }
		if (mNum == MENU_OFFSET_AFTER_LAST_ENTRY)   { break; }

		switch (mNum)
		{
			case 0:  snprintf(buf, sizeof buf, MSGS_INBOX_FMT, dmrSmsCount(0)); break;
			case 1:  snprintf(buf, sizeof buf, MSGS_SENT_FMT,  dmrSmsCount(1)); break;
			case 2:  snprintf(buf, sizeof buf, MSGS_NEW);                       break;
			// Монітор: приймати чужі повідомлення (ті, де адресат -- не ми). Вимкнено за
			// замовчуванням; докладніше -- у smsIsForUs() в dmr_sms.c.
			case 3:  snprintf(buf, sizeof buf, MSGS_MONITOR_FMT,
					settingsIsOptionBitSet(BIT_SMS_MONITOR_ALL) ? MSGS_MON_ON : MSGS_MON_OFF); break;
			// Режим TX SMS: Без підтв. / Підтв. rate-1/2 / Підтв. rate-3/4 (Task #31).
			case 4:
			{
				static const char * const modes[] = { MSGS_TX_MODE_UNCONF, MSGS_TX_MODE_R12, MSGS_TX_MODE_R34 };
				int m = dmrSmsTxMode();
				snprintf(buf, sizeof buf, MSGS_TX_MODE_FMT, (m >= 0 && m <= 2) ? modes[m] : modes[0]);
				break;
			}
			// Лічильники ланцюга квитанції -- окремий екран (2026-09-30).
			default: snprintf(buf, sizeof buf, MSGS_DIAG); break;
		}
		menuDisplayEntry(i, mNum, buf, 0, THEME_ITEM_FG_MENU_ITEM, THEME_ITEM_FG_OPTIONS_VALUE, THEME_ITEM_BG);
	}

	displayRender();
}

static void openFolder(int folder)
{
	s_msg.folder = (uint8_t)folder;
	s_msg.view = MSG_LIST;
	menuDataGlobal.currentItemIndex = 0;
	menuDataGlobal.numItems = dmrSmsCount(folder) + 1;   // +1 for "[Delete all]"
	listUpdate();
}

static void startCompose(void)
{
	memset(s_msg.compose, 0, sizeof s_msg.compose);
	s_msg.composePos = 0;
	s_msg.presetIdx = -1;
	// A plain "New Message" always falls back to the default-recipient prefill, never a
	// stale Reply/Resend target left over from an earlier, possibly cancelled, attempt.
	// startReplyOrResend() re-sets this to 1 itself AFTER calling this function.
	s_msg.rcptPreset = 0;
	s_msg.view = MSG_COMPOSE;
	keypadAlphaEnable = true;
	composeUpdate();
}

/* Cycle the next non-empty quick-text preset into the compose buffer. */
static void cyclePreset(void)
{
	int total = dmrSmsPresetCount();
	if (total == 0) { return; }
	for (int tries = 0; tries < DMR_SMS_NUM_PRESETS; tries++)
	{
		s_msg.presetIdx = (int8_t)((s_msg.presetIdx + 1) % DMR_SMS_NUM_PRESETS);
		const char *p = dmrSmsPresetGet(s_msg.presetIdx);
		if (p != NULL)
		{
			int cap = dmrSmsMaxLen();
			strncpy(s_msg.compose, p, cap);
			s_msg.compose[cap] = 0;
			s_msg.composePos = (int16_t)strlen(s_msg.compose);
			if (s_msg.composePos > cap - 1) { s_msg.composePos = cap - 1; }
			composeUpdate();
			return;
		}
	}
}

static void homeEvent(uiEvent_t *ev, menuStatus_t *ec)
{
	if ((ev->events & KEY_EVENT) == 0) { return; }

	if (KEYCHECK_PRESS(ev->keys, KEY_DOWN))
	{
		menuSystemMenuIncrement(&menuDataGlobal.currentItemIndex, MSGS_HOME_ITEMS);
		*ec |= MENU_STATUS_LIST_TYPE; homeUpdate(); return;
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_UP))
	{
		menuSystemMenuDecrement(&menuDataGlobal.currentItemIndex, MSGS_HOME_ITEMS);
		*ec |= MENU_STATUS_LIST_TYPE; homeUpdate(); return;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		menuSystemPopPreviousMenu(); return;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		switch (menuDataGlobal.currentItemIndex)
		{
			case 0: openFolder(0);  break;
			case 1: openFolder(1);  break;
			case 2: startCompose(); break;
			case 3:
				settingsSetOptionBit(BIT_SMS_MONITOR_ALL,
						(settingsIsOptionBitSet(BIT_SMS_MONITOR_ALL) == false));
				homeUpdate();
				break;
			case 4:
				/* Цикл режимів TX SMS: Без підтв. → Підтв.½ → Підтв.¾ → Без підтв. */
				dmrSmsTxModeSet((uint8_t)((dmrSmsTxMode() + 1) % 3));
				homeUpdate();
				break;
			case 5:
				s_msg.view = MSG_DIAG;
				s_msg.diagPage = 0;
				s_msg.diagScroll = 0;
				s_msg.diagSel = 0;
				diagUpdate();
				break;
		}
		return;
	}
}

/* ============================ DIAG ===================================== */
/* Лічильники ланцюга квитанції одним поглядом, без USB-ПК (2026-09-30). Розшифровка
 * скорочень -- TESTING.md, блоки M і N. FONT_SIZE_1: 26 символів у рядок.
 * Сторінка 1 -- лічильники; DOWN -> сторінка 2 (fix3): лічильники ISR до фільтрів, фактична
 * затримка квитанції і 4 перемикачі (UP/DOWN -- вибір, GREEN -- змінити; UP з першого
 * перемикача -- назад на сторінку 1). Довге GREEN скидає лічильники ВСІХ сторінок.
 * diag5: DOWN з останнього перемикача -> сторінка 3 (де гине вхідний PDU), UP -> назад. */
#define DIAG_TOGGLES 5

static void diagPage1(const dmrSmsDiagScreen_t *d)
{
	char buf[40];
	int y = 16;
	menuDisplayTitle(MSGS_DIAG);
	snprintf(buf, sizeof buf, MSGS_DG_ACK1_FMT, (unsigned)d->ackSeen, (unsigned)d->ackQueued);
	displayPrintAt(2, y, buf, FONT_SIZE_1); y += 10;
	snprintf(buf, sizeof buf, MSGS_DG_ACK2_FMT, (unsigned)d->ackSent, (unsigned)d->ackStale);
	displayPrintAt(2, y, buf, FONT_SIZE_1); y += 10;
	snprintf(buf, sizeof buf, MSGS_DG_ACK3_FMT, (unsigned)d->ackDelayMs);
	displayPrintAt(2, y, buf, FONT_SIZE_1); y += 10;
	snprintf(buf, sizeof buf, MSGS_DG_DATA1_FMT, (unsigned)d->dataRejected, (unsigned)d->dataStarted);
	displayPrintAt(2, y, buf, FONT_SIZE_1); y += 10;
	snprintf(buf, sizeof buf, MSGS_DG_DATA2_FMT, (unsigned)d->dataTimeout, (unsigned)d->dataNoStart);
	displayPrintAt(2, y, buf, FONT_SIZE_1); y += 10;
	snprintf(buf, sizeof buf, MSGS_DG_CONF_FMT, (unsigned)d->txConf);
	displayPrintAt(2, y, buf, FONT_SIZE_1); y += 10;
	snprintf(buf, sizeof buf, MSGS_DG_RESP_FMT, (unsigned)d->respAll, (unsigned)d->respForUs, (unsigned)d->respMatch);
	displayPrintAt(2, y, buf, FONT_SIZE_1); y += 10;
	snprintf(buf, sizeof buf, MSGS_DG_HDR_FMT, (unsigned)d->hdrHwOk, (unsigned)d->hdrSwOk, (unsigned)d->hdrBad);
	displayPrintAt(2, y, buf, FONT_SIZE_1);
	displayPrintCentered(112, MSGS_DG_HINT, FONT_SIZE_1);
}

static void diagPage2(const dmrSmsDiagScreen_t *d)
{
	char buf[40];
	int y = 16;
	menuDisplayTitle(MSGS_DIAG2);
	snprintf(buf, sizeof buf, MSGS_DG_ISR_FMT, (unsigned)d->isr6, (unsigned)d->isr8);
	displayPrintAt(2, y, buf, FONT_SIZE_1); y += 10;
	snprintf(buf, sizeof buf, MSGS_DG_FILT_FMT, (unsigned)d->filt6, (unsigned)d->filt8);
	displayPrintAt(2, y, buf, FONT_SIZE_1); y += 10;
	snprintf(buf, sizeof buf, MSGS_DG_REAL_FMT, (unsigned)d->ackRealMs);
	displayPrintAt(2, y, buf, FONT_SIZE_1); y += 10;
	/* ui1/fix4: «Квит факт» по етапах: тиша->черга + черга->ключування + ключування->старт TX
	 * + старт->перший burst. Сума ~ «Квит факт». */
	snprintf(buf, sizeof buf, MSGS_DG_STG_FMT, (unsigned)d->stgQ, (unsigned)d->stgK, (unsigned)d->stgS, (unsigned)d->stgB);
	displayPrintAt(2, y, buf, FONT_SIZE_1); y += 12;
	/* Перемикачі (не зберігаються; типові -- DMR_SMS_DEFAULT_* у dmr_sms_pdu.h). */
	for (int i = 0; i < DIAG_TOGGLES; i++)
	{
		char mark = (s_msg.diagSel == i) ? '>' : ' ';
		switch (i)
		{
			case 0:  snprintf(buf, sizeof buf, MSGS_DG_FAST_FMT, mark, dmrSmsDiagFastEnd() ? MSGS_MON_ON : MSGS_MON_OFF); break;
			case 1:  snprintf(buf, sizeof buf, MSGS_DG_BYP_FMT, mark, dmrSmsRxBypass() ? MSGS_MON_ON : MSGS_MON_OFF); break;
			case 2:  snprintf(buf, sizeof buf, MSGS_DG_PRE_FMT, mark, (unsigned)dmrSmsDiagAckPreambles()); break;
			case 3:  snprintf(buf, sizeof buf, MSGS_DG_TERM_FMT, mark, dmrSmsDiagAckTerm() ? MSGS_DG_YES : MSGS_DG_NO); break;
			default: snprintf(buf, sizeof buf, MSGS_DG_PAUSE_FMT, mark, (unsigned)dmrSmsDiagAckPause()); break;
		}
		displayPrintAt(2, y, buf, FONT_SIZE_1); y += 10;
	}
	displayPrintCentered(112, MSGS_DG_HINT2, FONT_SIZE_1);
}

/* diag5: сторінка 3 -- шлях вхідного SMS від ISR до головного циклу. Порівнювати з
 * «ISR: т6/т8» і «Квит RX: бач/черг»: якщо burst-и дійшли, а «PDU» менше за кількість
 * спроб -- рядки нижче кажуть, на якому кроці PDU загинув (TESTING.md, блок R). */
static void diagPage3(const dmrSmsDiagScreen_t *d)
{
	char buf[40];
	int y = 16;
	menuDisplayTitle(MSGS_DIAG3);
	snprintf(buf, sizeof buf, MSGS_DG_ISR_FMT, (unsigned)d->isr6, (unsigned)d->isr8);
	displayPrintAt(2, y, buf, FONT_SIZE_1); y += 10;
	snprintf(buf, sizeof buf, MSGS_DG_ACK1_FMT, (unsigned)d->ackSeen, (unsigned)d->ackQueued);
	displayPrintAt(2, y, buf, FONT_SIZE_1); y += 10;
	snprintf(buf, sizeof buf, MSGS_DG3_PDU_FMT, (unsigned)d->pduOk, (unsigned)d->crcFail);
	displayPrintAt(2, y, buf, FONT_SIZE_1); y += 10;
	snprintf(buf, sizeof buf, MSGS_DG3_BLK1_FMT, (unsigned)d->blkNoHdr, (unsigned)d->blkBusy);
	displayPrintAt(2, y, buf, FONT_SIZE_1); y += 10;
	snprintf(buf, sizeof buf, MSGS_DG3_BLK2_FMT, (unsigned)d->blkOvf, (unsigned)d->blkExtra);
	displayPrintAt(2, y, buf, FONT_SIZE_1); y += 10;
	snprintf(buf, sizeof buf, MSGS_DG3_TICK_FMT, (unsigned)d->tickNotUs, (unsigned)d->tickBad);
	displayPrintAt(2, y, buf, FONT_SIZE_1); y += 10;
	snprintf(buf, sizeof buf, MSGS_DG3_PICK_FMT, (unsigned)d->pickMaxMs);
	displayPrintAt(2, y, buf, FONT_SIZE_1); y += 10;
	/* fix7: корекція трибітів -- виправлено / неоднозначно; не знайдено, час останньої і найдовшої */
	snprintf(buf, sizeof buf, MSGS_DG3_FIX1_FMT, (unsigned)d->fixOk, (unsigned)d->fixAmb);
	displayPrintAt(2, y, buf, FONT_SIZE_1); y += 10;
	snprintf(buf, sizeof buf, MSGS_DG3_FIX2_FMT, (unsigned)d->fixNone, (unsigned)d->fixLastMs, (unsigned)d->fixMaxMs);
	displayPrintAt(2, y, buf, FONT_SIZE_1);
	displayPrintCentered(112, MSGS_DG3_HINT, FONT_SIZE_1);
}

/* diag6: сторінка 4 -- знімок ОСТАННЬОГО PDU з «CRC пог»: сирі блоки так, як їх віддав чип
 * (rate-3/4: 2 службові DBSN+CRC9 + 16 навантаження), для порівняння з декодом HackRF.
 * Рядки (гортаються UP/DOWN): номер знімка, блоків, маска HW-CRC; CRC32 очікуваний/фактичний;
 * лічильники DBSN/HW; сирий заголовок (2 рядки); далі по 2 рядки на блок:
 *   «Nm ммммм hhhhhhhhhhhhhhhhhh» -- номер блока, '*' якщо HW CRC валідний, мс від заголовка,
 *   перша половина байтів; другий рядок -- решта байтів під першою. */
#define DIAG4_VISIBLE 9

static void hexAppend(char *buf, int bufsz, const uint8_t *p, int n)
{
	int l = (int)strlen(buf);
	for (int i = 0; (i < n) && (l + 2 < bufsz); i++, l += 2)
	{
		snprintf(buf + l, (size_t)(bufsz - l), "%02x", p[i]);
	}
}

static int diagPage4Rows(void)
{
	dmrSmsBadSnapInfo_t si;
	return (dmrSmsBadSnapInfo(&si) == 0) ? 2 : (5 + 2 * si.n);
}

static bool diagPage4Row(int r, const dmrSmsDiagScreen_t *d, char *buf, int bufsz)
{
	dmrSmsBadSnapInfo_t si;
	int n = dmrSmsBadSnapInfo(&si);
	buf[0] = 0;
	if (n == 0)
	{
		if (r == 0) { snprintf(buf, bufsz, "%s", MSGS_DG4_NONE); return true; }
		if (r == 1) { snprintf(buf, bufsz, MSGS_DG4_CNT_FMT, (unsigned)d->dbsnBad, (unsigned)d->hw8Ok); return true; }
		return false;
	}
	switch (r)
	{
		case 0: snprintf(buf, bufsz, MSGS_DG4_SNAP_FMT, (unsigned)si.seq, (unsigned)n, (unsigned)si.hwOk); return true;
		case 1: snprintf(buf, bufsz, MSGS_DG4_CRC_FMT, (unsigned long)si.crcWant, (unsigned long)si.crcGot); return true;
		case 2: snprintf(buf, bufsz, MSGS_DG4_CNT_FMT, (unsigned)d->dbsnBad, (unsigned)d->hw8Ok); return true;
		case 3: snprintf(buf, bufsz, "%s", MSGS_DG4_HDR); hexAppend(buf, bufsz, si.hdr, 8); return true;
		case 4: snprintf(buf, bufsz, "    "); hexAppend(buf, bufsz, si.hdr + 8, 4); return true;
		default: break;
	}
	int b = (r - 5) / 2;
	uint16_t ms = 0;
	const uint8_t *blk = dmrSmsBadSnapBlock(b, &ms);
	if (blk == NULL) { return false; }
	int half = (si.len + 1) / 2;
	if (((r - 5) & 1) == 0)
	{
		snprintf(buf, bufsz, "%u%c%5u ", (unsigned)(b & 7), (si.hwOk & (1u << b)) ? '*' : ' ', (unsigned)ms);
		hexAppend(buf, bufsz, blk, half);
	}
	else
	{
		snprintf(buf, bufsz, "        ");
		hexAppend(buf, bufsz, blk + half, si.len - half);
	}
	return true;
}

static void diagPage4(const dmrSmsDiagScreen_t *d)
{
	char buf[40];
	menuDisplayTitle(MSGS_DIAG4);
	int rows = diagPage4Rows();
	if (s_msg.diagScroll + DIAG4_VISIBLE > rows) { s_msg.diagScroll = (uint8_t)((rows > DIAG4_VISIBLE) ? (rows - DIAG4_VISIBLE) : 0); }
	for (int k = 0; k < DIAG4_VISIBLE; k++)
	{
		if (!diagPage4Row(s_msg.diagScroll + k, d, buf, sizeof buf)) { break; }
		displayPrintAt(2, 16 + 10 * k, buf, FONT_SIZE_1);
	}
	displayPrintCentered(112, MSGS_DG4_HINT, FONT_SIZE_1);
}

static void diagUpdate(void)
{
	dmrSmsDiagScreen_t d;
	dmrSmsDiagScreenGet(&d);

	displayClearBuf();
	if (s_msg.diagPage == 0)      { diagPage1(&d); }
	else if (s_msg.diagPage == 1) { diagPage2(&d); }
	else if (s_msg.diagPage == 2) { diagPage3(&d); }
	else                          { diagPage4(&d); }
	displayRender();

	ticksTimerStart(&s_msg.resultTimer, MSGS_DIAG_REFRESH_MS);
}

static void diagToggle(int sel)
{
	switch (sel)
	{
		case 0:  dmrSmsDiagFastEndToggle();     break;   /* «Шв. кінець»: наше CONFIRMED без термінатора */
		case 1:  dmrSmsDiagRxBypassToggle();    break;   /* «RX обхід» фільтра RX-стану */
		case 2:  dmrSmsDiagAckPreamblesToggle(); break;  /* преамбули квитанції 0 <-> 6 */
		case 3:  dmrSmsDiagAckTermToggle();     break;   /* квитанція з термінатором чи без */
		default: dmrSmsDiagAckPauseToggle();    break;   /* цільова пауза квитанції 80/50/20 мс */
	}
}

static void diagEvent(uiEvent_t *ev)
{
	if ((ev->events & KEY_EVENT) == 0) { return; }
	if (KEYCHECK_LONGDOWN(ev->keys, KEY_GREEN))
	{
		dmrSmsDiagScreenReset();   /* лічильники обох сторінок */
		diagUpdate();
		return;
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_DOWN))
	{
		if (s_msg.diagPage == 0)                     { s_msg.diagPage = 1; s_msg.diagSel = 0; }
		else if (s_msg.diagPage == 2)                { s_msg.diagPage = 3; s_msg.diagScroll = 0; }   /* diag6: стор. 4 */
		else if (s_msg.diagPage == 3)
		{
			if ((s_msg.diagScroll + DIAG4_VISIBLE) < diagPage4Rows()) { s_msg.diagScroll++; }
		}
		else if (s_msg.diagSel < (DIAG_TOGGLES - 1)) { s_msg.diagSel++; }
		else                                         { s_msg.diagPage = 2; }   /* diag5: стор. 3 */
		diagUpdate();
		return;
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_UP))
	{
		if (s_msg.diagPage == 3)
		{
			if (s_msg.diagScroll > 0) { s_msg.diagScroll--; }
			else                      { s_msg.diagPage = 2; }   /* назад на стор. 3 */
		}
		else if (s_msg.diagPage == 2)
		{
			s_msg.diagPage = 1;   /* назад на стор. 2, на останній перемикач */
			s_msg.diagSel = DIAG_TOGGLES - 1;
		}
		else if (s_msg.diagPage == 1)
		{
			if (s_msg.diagSel > 0) { s_msg.diagSel--; }
			else                   { s_msg.diagPage = 0; }
		}
		diagUpdate();
		return;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		if (s_msg.diagPage == 1) { diagToggle(s_msg.diagSel); }
		diagUpdate();
		return;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		gotoHome();
		menuDataGlobal.currentItemIndex = 5;   // повернутись на рядок «Діагностика»
		homeUpdate();
	}
}

/* ============================ LIST ===================================== */
static void listUpdate(void)
{
	char buf[DMR_SMS_TEXT_MAX + 24];
	int count = dmrSmsCount(s_msg.folder);
	displayClearBuf();
	menuDisplayTitle(s_msg.folder ? MSGS_TITLE_SENT : MSGS_TITLE_INBOX);

	if (count == 0)
	{
		displayPrintCentered(56, MSGS_EMPTY, FONT_SIZE_3);
		displayPrintCentered(112, MSGS_HINT_BACK, FONT_SIZE_1);
		displayRender();
		return;
	}

	for (int i = MENU_START_ITERATION_VALUE; i <= MENU_END_ITERATION_VALUE; i++)
	{
		int mNum = menuGetMenuOffset(count + 1, i);
		if (mNum == MENU_OFFSET_BEFORE_FIRST_ENTRY) { continue; }
		if (mNum == MENU_OFFSET_AFTER_LAST_ENTRY)   { break; }

		if (mNum == count)
		{
			snprintf(buf, sizeof buf, MSGS_DELETE_ALL);
		}
		else
		{
			const dmrSmsMessage_t *m = dmrSmsGet(s_msg.folder, mNum);
			if (m == NULL) { continue; }
			char txt[DMR_SMS_TEXT_MAX + 1];
			int n = (m->textLen < (int)sizeof txt - 1) ? m->textLen : (int)sizeof txt - 1;
			memcpy(txt, m->text, n); txt[n] = 0;
			char mark = (m->flags & DMR_SMS_FLAG_UNREAD) ? '*' : ' ';
			// ">" = перехоплене монітором, адресоване НЕ нам. Позначка стоїть перед номером
			// відправника, бо саме його оператор бачить першим і може прийняти за адресата.
			const char *foreign = (m->flags & DMR_SMS_FLAG_FOREIGN) ? ">" : "";
			char who[20];
			smsWhoStr(m->peerId, who, sizeof who);   // позивний/ім'я замість номера
			snprintf(buf, sizeof buf, "%c%s%s:%s", mark, foreign, who, txt);
		}
		menuDisplayEntry(i, mNum, buf, 0, THEME_ITEM_FG_MENU_ITEM, THEME_ITEM_FG_OPTIONS_VALUE, THEME_ITEM_BG);

		/* ui1 (2026-10-04): у «Надісланих» доставлене (квитанція отримана) -- маленька галочка
		 * в першій клітинці рядка (там, де у «Вхідних» стоїть '*' непрочитаного; у
		 * «Надісланих» вона порожня). Клітинка FONT_SIZE_3 -- 8x16 px, галочка 7x6 px, 2 px.
		 * На виділеному рядку -- кольором тла (як інвертований текст), інакше зеленим з теми. */
		if ((s_msg.folder == 1) && (mNum < count))
		{
			const dmrSmsMessage_t *m = dmrSmsGet(1, mNum);
			if ((m != NULL) && (m->flags & DMR_SMS_FLAG_DELIVERED))
			{
				int16_t cx = DISPLAY_X_POS_MENU_TEXT_OFFSET;
				int16_t cy = (int16_t)(DISPLAY_Y_POS_MENU_ENTRY_HIGHLIGHT + (i * MENU_ENTRY_HEIGHT));
				bool focused = (mNum == menuDataGlobal.currentItemIndex);
				displayThemeApply(focused ? THEME_ITEM_BG : THEME_ITEM_FG_RSSI_BAR,
				                  focused ? THEME_ITEM_BG_MENU_ITEM_SELECTED : THEME_ITEM_BG);
				for (int16_t k = 0; k < 2; k++)
				{
					displayDrawLine(cx, (int16_t)(cy + 8 + k), (int16_t)(cx + 2), (int16_t)(cy + 11 + k), true);
					displayDrawLine((int16_t)(cx + 2), (int16_t)(cy + 11 + k), (int16_t)(cx + 7), (int16_t)(cy + 5 + k), true);
				}
				displayThemeResetToDefault();
			}
		}
	}
	displayRender();
}

static void listEvent(uiEvent_t *ev)
{
	if ((ev->events & KEY_EVENT) == 0) { return; }
	int count = dmrSmsCount(s_msg.folder);

	// SK2+RED marks every Inbox message read in one go (dmrSmsMarkAllRead() only ever
	// touches unread Inbox entries, so calling it from the Sent view is a harmless no-op).
	if (KEYCHECK_SHORTUP(ev->keys, KEY_RED) && BUTTONCHECK_DOWN(ev, BUTTON_SK2))
	{
		dmrSmsMarkAllRead();
		listUpdate();
		return;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_RED)) { gotoHome(); return; }

	if (count == 0) { return; }

	if (KEYCHECK_PRESS(ev->keys, KEY_DOWN))
	{
		menuSystemMenuIncrement(&menuDataGlobal.currentItemIndex, count + 1); listUpdate(); return;
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_UP))
	{
		menuSystemMenuDecrement(&menuDataGlobal.currentItemIndex, count + 1); listUpdate(); return;
	}

	int idx = menuDataGlobal.currentItemIndex;

	// SK2+GREEN deletes the selected message (deliberate combo).
	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN) && BUTTONCHECK_DOWN(ev, BUTTON_SK2))
	{
		if (idx == count) { dmrSmsDeleteAll(s_msg.folder); }   // delete-all row + SK2
		else              { dmrSmsDelete(s_msg.folder, idx); }
		int newCount = dmrSmsCount(s_msg.folder);
		menuDataGlobal.numItems = newCount + 1;
		if (menuDataGlobal.currentItemIndex >= menuDataGlobal.numItems)
		{
			menuDataGlobal.currentItemIndex = menuDataGlobal.numItems - 1;
		}
		listUpdate();
		return;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		if (idx == count) { return; }   // need SK2 to confirm delete-all
		s_msg.readIdx = (int16_t)idx;
		dmrSmsMarkRead(s_msg.folder, idx);
		s_msg.view = MSG_READ;
		readUpdate();
		return;
	}
}

/* ============================ READ ===================================== */
static void readUpdate(void)
{
	const dmrSmsMessage_t *m = dmrSmsGet(s_msg.folder, s_msg.readIdx);
	displayClearBuf();
	menuDisplayTitle(s_msg.folder ? MSGS_TITLE_SENT : MSGS_TITLE_INBOX);

	if (m == NULL) { displayRender(); return; }

	// Найважливіше саме на цьому екрані: тут оператор ЧИТАЄ наказ і за ним діє. Якщо
	// повідомлення перехоплене монітором і адресоване не нам -- це має бути написано словами,
	// а не лише позначкою у списку (FONT_SIZE_1: 26 символів у рядок, найдовший варіант
	// "From 16777215 (not yours)" = 25).
	char hdr[40];
	char who[20];
	smsWhoStr(m->peerId, who, sizeof who);   // позивний/ім'я, або номер якщо невідомий
	snprintf(hdr, sizeof hdr, "%s %s%s", (m->flags & DMR_SMS_FLAG_OUTGOING) ? MSGS_TO : MSGS_FROM,
			who, (m->flags & DMR_SMS_FLAG_FOREIGN) ? MSGS_FOREIGN : "");
	displayPrintAt(2, 16, hdr, FONT_SIZE_1);

	// word-free char wrap into ~21-char lines
	char txt[DMR_SMS_TEXT_MAX + 1];
	int n = (m->textLen < (int)sizeof txt - 1) ? m->textLen : (int)sizeof txt - 1;
	memcpy(txt, m->text, n); txt[n] = 0;

	const int perLine = 21;
	char line[perLine + 1];
	int y = 30;
	for (int i = 0; i < n && y < 104; i += perLine, y += 12)
	{
		int len = ((n - i) < perLine) ? (n - i) : perLine;
		memcpy(line, txt + i, len); line[len] = 0;
		displayPrintAt(2, y, line, FONT_SIZE_2);
	}

	displayPrintCentered(112, s_msg.folder ? MSGS_HINT_SENT_ITEM : MSGS_HINT_INBOX_ITEM, FONT_SIZE_1);
	displayRender();
}

/* Reply (Inbox: blank text, recipient pre-set to the sender) or Resend (Sent: text AND
 * recipient both pre-filled, straight to RECIPIENT — one GREEN press away from re-sending
 * unedited, or RED to go back into COMPOSE and change the wording first). */
static void startReplyOrResend(void)
{
	const dmrSmsMessage_t *m = dmrSmsGet(s_msg.folder, s_msg.readIdx);
	if (m == NULL) { return; }

	uint32_t peer = m->peerId;
	uint8_t  group = (m->flags & DMR_SMS_FLAG_GROUP) ? 1 : 0;

	if (s_msg.folder == 1)   // Sent -> Resend
	{
		int n = (m->textLen < (int)sizeof s_msg.compose - 1) ? m->textLen : (int)sizeof s_msg.compose - 1;
		memset(s_msg.compose, 0, sizeof s_msg.compose);
		memcpy(s_msg.compose, m->text, n);
		s_msg.composePos = (int16_t)n;
		s_msg.presetIdx = -1;
		snprintf(s_msg.rcpt, sizeof s_msg.rcpt, "%lu", (unsigned long)peer);
		s_msg.rcptPos = (int16_t)strlen(s_msg.rcpt);
		s_msg.rcptGroup = group;
		s_msg.view = MSG_RECIPIENT;
		keypadAlphaEnable = false;
		recipientUpdate();
	}
	else                     // Inbox -> Reply
	{
		startCompose();   // resets compose text/pos/presetIdx AND rcptPreset - must run first
		snprintf(s_msg.rcpt, sizeof s_msg.rcpt, "%lu", (unsigned long)peer);
		s_msg.rcptPos = (int16_t)strlen(s_msg.rcpt);
		s_msg.rcptGroup = group;
		s_msg.rcptPreset = 1;   // composeEvent's GREEN must skip the default-recipient prefill
	}
}

static void readEvent(uiEvent_t *ev)
{
	if ((ev->events & KEY_EVENT) == 0) { return; }

	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN) && BUTTONCHECK_DOWN(ev, BUTTON_SK2))
	{
		dmrSmsDelete(s_msg.folder, s_msg.readIdx);
		openFolder(s_msg.folder);
		return;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		startReplyOrResend();
		return;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		openFolder(s_msg.folder);
		return;
	}
}

/* ============================ COMPOSE ================================== */
static void composeUpdate(void)
{
	displayClearBuf();
	menuDisplayTitle(MSGS_TITLE_NEW);

	// show the text wrapped
	const int perLine = 21;
	int n = (int)strlen(s_msg.compose);
	char line[perLine + 1];
	int y = 22;
	if (n == 0)
	{
		displayPrintAt(2, y, "_", FONT_SIZE_2);
	}
	for (int i = 0; i < n && y < 92; i += perLine, y += 14)
	{
		int len = ((n - i) < perLine) ? (n - i) : perLine;
		memcpy(line, s_msg.compose + i, len); line[len] = 0;
		displayPrintAt(2, y, line, FONT_SIZE_2);
	}

	char cnt[20];
	snprintf(cnt, sizeof cnt, MSGS_CHARS_FMT, n, dmrSmsMaxLen());
	displayPrintCentered(96, cnt, FONT_SIZE_1);
	if (dmrSmsPresetCount() > 0)
	{
		displayPrintCentered(104, MSGS_HINT_PRESET, FONT_SIZE_1);
	}
	displayPrintCentered(116, MSGS_HINT_TO_CANCEL, FONT_SIZE_1);
	displayRender();
}

static void prefillRecipient(void)
{
	uint32_t defDst = 0;
	int defGroup = 1;
	dmrSmsDefaultRecipient(&defDst, &defGroup);

	uint32_t id;
	if (defDst != 0)
	{
		id = defDst;                 // CHIRP-configured default recipient
		s_msg.rcptGroup = defGroup ? 1 : 0;
	}
	else
	{
		id = trxTalkGroupOrPcId & 0x00FFFFFF;   // fall back to the current channel
		s_msg.rcptGroup = ((trxTalkGroupOrPcId >> 24) == PC_CALL_FLAG) ? 0 : 1;
	}
	snprintf(s_msg.rcpt, sizeof s_msg.rcpt, "%lu", (unsigned long)id);
	s_msg.rcptPos = (int16_t)strlen(s_msg.rcpt);
}

static void composeEvent(uiEvent_t *ev)
{
	if ((ev->events & KEY_EVENT) == 0) { return; }

	if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		gotoHome(); return;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		if (strlen(s_msg.compose) == 0) { return; }
		keypadAlphaEnable = false;
		if (s_msg.rcptPreset) { s_msg.rcptPreset = 0; }   // Reply: rcpt/rcptGroup already set
		else                  { prefillRecipient(); }
		s_msg.view = MSG_RECIPIENT;
		recipientUpdate();
		return;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_LEFT))
	{
		int n = (int)strlen(s_msg.compose);
		if (n > 0) { s_msg.compose[n - 1] = 0; if (s_msg.composePos > 0) s_msg.composePos--; }
		composeUpdate();
		return;
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_UP))   // insert a CHIRP-configured quick-text preset
	{
		cyclePreset();
		return;
	}
	// multi-tap alpha entry (keypadAlphaEnable handles cycling; same idiom as contact name)
	if (s_msg.composePos < dmrSmsMaxLen())
	{
		if (ev->keys.event == KEY_MOD_PREVIEW)
		{
			s_msg.compose[s_msg.composePos] = ev->keys.key;
			composeUpdate();
			return;
		}
		if (ev->keys.event == KEY_MOD_PRESS)
		{
			s_msg.compose[s_msg.composePos] = ev->keys.key;
			if (s_msg.composePos < (int)strlen(s_msg.compose) && s_msg.composePos < dmrSmsMaxLen() - 1)
			{
				s_msg.composePos++;
			}
			composeUpdate();
			return;
		}
	}
}

/* ============================ RECIPIENT =============================== */
static void recipientUpdate(void)
{
	char buf[24];
	displayClearBuf();
	menuDisplayTitle(MSGS_TITLE_RCPT);

	snprintf(buf, sizeof buf, MSGS_TO_FMT, s_msg.rcpt);
	displayPrintAt(2, 28, buf, FONT_SIZE_3);
	snprintf(buf, sizeof buf, MSGS_TYPE_FMT, s_msg.rcptGroup ? MSGS_GROUP : MSGS_PRIVATE);
	displayPrintAt(2, 52, buf, FONT_SIZE_2);

	displayPrintCentered(82,  MSGS_HINT_ID, FONT_SIZE_1);
	displayPrintCentered(92,  MSGS_HINT_GRP_PRIV, FONT_SIZE_1);
	displayPrintCentered(102, MSGS_HINT_CONTACTS, FONT_SIZE_1);
	displayPrintCentered(112, MSGS_HINT_SEND_BACK, FONT_SIZE_1);
	displayRender();
}

static void doSend(void)
{
	uint32_t dst = (uint32_t)strtoul(s_msg.rcpt, NULL, 10);
	if (dst == 0) { return; }
	s_msg.result = (int8_t)dmrSmsSend(s_msg.compose, dst, s_msg.rcptGroup ? 1 : 0, 0);
	s_msg.view = MSG_RESULT;
	// БУЛО: resultTicks = 600 з коментарем "~30 s", бо припускалось ~20 тіків/с. Насправді
	// головний цикл крутиться раз на МІЛІСЕКУНДУ і кличе тік меню щоразу (applicationMain.c),
	// тож виходило 600 мс -- звідси й скарга на "дуже короткі спливаючі вікна".
	// Тепер це реальний час і від частоти циклу не залежить.
	ticksTimerStart(&s_msg.resultTimer, 30000U);
	ticksTimerStart(&s_msg.resultGuard, 500U);
	resultUpdate();
}

static void recipientEvent(uiEvent_t *ev)
{
	// SK1 is a plain button press, not a KEY_EVENT - must be checked before the
	// KEY_EVENT-only early return below (same idiom as menuChannelDetails.c).
	if (ev->events & BUTTON_EVENT)
	{
		if (BUTTONCHECK_SHORTUP(ev, BUTTON_SK1))
		{
			s_msg.view = MSG_PICK_CONTACT;
			menuDataGlobal.currentItemIndex = 0;
			// count тут той самий callType, який побачить pickContactUpdate()/pickContactEvent()
			// нижче (rcptGroup визначає TG чи PC) - інакше UP/DOWN гортатиме за старим numItems.
			menuDataGlobal.numItems = codeplugContactsGetCount(s_msg.rcptGroup ? CONTACT_CALLTYPE_TG : CONTACT_CALLTYPE_PC);
			pickContactUpdate();
			return;
		}
	}

	if ((ev->events & KEY_EVENT) == 0) { return; }

	if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		s_msg.view = MSG_COMPOSE;
		keypadAlphaEnable = true;
		composeUpdate();
		return;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		doSend(); return;
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_UP) || KEYCHECK_PRESS(ev->keys, KEY_DOWN))
	{
		s_msg.rcptGroup = s_msg.rcptGroup ? 0 : 1; recipientUpdate(); return;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_LEFT))
	{
		int n = (int)strlen(s_msg.rcpt);
		if (n > 0) { s_msg.rcpt[n - 1] = 0; }
		recipientUpdate();
		return;
	}
	if (KEYCHECK_SHORTUP_NUMBER(ev->keys))
	{
		int n = (int)strlen(s_msg.rcpt);
		if (n < (int)sizeof s_msg.rcpt - 1)
		{
			s_msg.rcpt[n] = (char)ev->keys.key;
			s_msg.rcpt[n + 1] = 0;
		}
		recipientUpdate();
		return;
	}
}

/* ============================ PICK CONTACT ============================= */
/* Список контактів кодплагу (TG чи PC, залежно від s_msg.rcptGroup) для швидкого вибору
 * адресата замість ручного набору ID цифрами. Вхід - SK1 з екрану RECIPIENT, вихід - назад
 * туди ж (GREEN підставляє обраний контакт, RED повертається без змін). */
static void pickContactUpdate(void)
{
	uint32_t callType = s_msg.rcptGroup ? CONTACT_CALLTYPE_TG : CONTACT_CALLTYPE_PC;
	int count = codeplugContactsGetCount(callType);
	char buf[24];

	displayClearBuf();
	menuDisplayTitle(s_msg.rcptGroup ? MSGS_TITLE_PICK_TG : MSGS_TITLE_PICK_PC);

	if (count == 0)
	{
		displayPrintCentered(56, MSGS_NO_CONTACTS, FONT_SIZE_2);
		displayPrintCentered(112, MSGS_HINT_BACK, FONT_SIZE_1);
		displayRender();
		return;
	}

	for (int i = MENU_START_ITERATION_VALUE; i <= MENU_END_ITERATION_VALUE; i++)
	{
		int mNum = menuGetMenuOffset(count, i);
		if (mNum == MENU_OFFSET_BEFORE_FIRST_ENTRY) { continue; }
		if (mNum == MENU_OFFSET_AFTER_LAST_ENTRY)   { break; }

		CodeplugContact_t c;
		// 1-індексований API кодплагу: mNum йде з 0, тому +1.
		if (codeplugContactGetDataForNumberInType(mNum + 1, callType, &c))
		{
			char name[17];
			codeplugUtilConvertBufToString(c.name, name, 16);
			snprintf(buf, sizeof buf, "%s", name);
		}
		else
		{
			snprintf(buf, sizeof buf, "?");
		}
		menuDisplayEntry(i, mNum, buf, 0, THEME_ITEM_FG_MENU_ITEM, THEME_ITEM_FG_OPTIONS_VALUE, THEME_ITEM_BG);
	}
	displayRender();
}

static void pickContactEvent(uiEvent_t *ev)
{
	if ((ev->events & KEY_EVENT) == 0) { return; }

	uint32_t callType = s_msg.rcptGroup ? CONTACT_CALLTYPE_TG : CONTACT_CALLTYPE_PC;
	int count = codeplugContactsGetCount(callType);

	if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		// Відміна - повертаємось на RECIPIENT, s_msg.rcpt/rcptGroup не чіпаємо.
		s_msg.view = MSG_RECIPIENT;
		recipientUpdate();
		return;
	}

	if (count == 0) { return; }   // порожній список - тільки RED працює

	if (KEYCHECK_PRESS(ev->keys, KEY_DOWN))
	{
		menuSystemMenuIncrement(&menuDataGlobal.currentItemIndex, count); pickContactUpdate(); return;
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_UP))
	{
		menuSystemMenuDecrement(&menuDataGlobal.currentItemIndex, count); pickContactUpdate(); return;
	}

	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		CodeplugContact_t c;
		if (codeplugContactGetDataForNumberInType(menuDataGlobal.currentItemIndex + 1, callType, &c))
		{
			snprintf(s_msg.rcpt, sizeof s_msg.rcpt, "%lu", (unsigned long)c.tgNumber);
			s_msg.rcptPos = (int16_t)strlen(s_msg.rcpt);
			// s_msg.rcptGroup вже дорівнює тому, за яким типом (TG/PC) гортали список -
			// саме він визначив callType вище, тому явно його підтверджувати не потрібно.
		}
		s_msg.view = MSG_RECIPIENT;
		recipientUpdate();
		return;
	}
}

/* ============================ RESULT ================================== */
static void resultUpdate(void)
{
	displayClearBuf();
	menuDisplayTitle(MSGS_TITLE);
	if (s_msg.result == 0)
	{
		displayPrintCentered(44, MSGS_SENT_OK, FONT_SIZE_3);
		displayPrintCentered(72, MSGS_KEYED_TX, FONT_SIZE_2);
	}
	else
	{
		char buf[24];
		const char *why = MSGS_ERR_GENERIC;
		switch (s_msg.result)
		{
			case -2: why = MSGS_ERR_TX_BUSY;   break;
			case -1: why = MSGS_ERR_BAD_TEXT;  break;
			case -4: case -5: why = MSGS_ERR_TOO_LONG; break;
		}
		displayPrintCentered(44, MSGS_SEND_FAILED, FONT_SIZE_3);
		snprintf(buf, sizeof buf, MSGS_FAIL_FMT, why, s_msg.result);
		displayPrintCentered(72, buf, FONT_SIZE_2);
	}
	displayPrintCentered(112, MSGS_HINT_ANY_KEY, FONT_SIZE_1);
	displayRender();
}

#endif // ENABLE_AES && ENABLE_DMR_DATA
