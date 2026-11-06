/*
 * menuRoam.c -- R59/R60: пункт головного меню «Роумінг» (ENABLE_ROAM_RETRY).
 *
 * Головний екран: «Автоперехід» (Вимк/Увімк), «Макс.стрибків» (1..5), «Спис.каналу» (Вимк, 1..10 -- список ПОТОЧНОГО каналу; лівий/правий
 * міняє значення, зелена ЗБЕРІГАЄ: один запис каналу; поки не збережено, поруч «*»), «Списки» (перегляд і редагування) і, з ENABLE_WAKE_DIAG,
 * «Журнал пробудж.» (R58, перенесено сюди з «Повідомлень»; логіка журналу й USB 0xB7 без змін).
 *
 * «Списки» (R60): вибір номера 1..10 -> члени списку (номер каналу + ім'я; зелена на члені -- прибрати зі списку після підтвердження;
 * останній рядок «+ Додати канал...» -- вибір серед УСІХ каналів кодплагу, зелена призначає канал у цей список; якщо канал уже в ІНШОМУ
 * списку, спершу питання «Перенести?», бо канал належить лише до одного списку). Кожна зміна -- ОДИН запис одного каналу
 * (roamChannelAssign() -> codeplugChannelSaveDataForIndex), решта кодплагу не чіпається; ті самі дані читає CPS.
 *
 * Налаштування (увімкнено/стрибки) пишуться в custom-data блок №15 лише при зміні користувачем (roam_cfg.c).
 * Рядки -- roam_ui.h (укр. з languages/roam_ua.h), не stringsTable_t. Сама логіка автопереходу -- wake_hop*.c.
 */
#include "user_interface/uiGlobals.h"
#include "user_interface/menuSystem.h"
#include "user_interface/uiLocalisation.h"
#include "user_interface/uiUtilities.h"

#if defined(ENABLE_ROAM_RETRY)

#include <string.h>
#include "user_interface/roam_ui.h"
#include "functions/roam_cfg.h"
#include "functions/wake_hop.h"
#include "functions/codeplug.h"
#include "functions/ticks.h"
#include "io/keyboard.h"
#if defined(ENABLE_WAKE_DIAG)
#include "functions/wake_diag.h"
#endif

enum { ROAM_VIEW_MAIN = 0, ROAM_VIEW_PICK, ROAM_VIEW_MEMBERS, ROAM_VIEW_ADD, ROAM_VIEW_CFM_REMOVE, ROAM_VIEW_CFM_MOVE, ROAM_VIEW_WAKE };

enum { ROAM_ROW_AUTO = 0, ROAM_ROW_HOPS, ROAM_ROW_CHLIST, ROAM_ROW_LISTS
#if defined(ENABLE_WAKE_DIAG)
	, ROAM_ROW_WAKE
#endif
	, ROAM_ROWS };

#define ROAM_REFRESH_MS    500    /* журнал оновлюється сам, поки оператор дивиться */
#define ROAM_PEND_NONE     0xFFU  /* «Спис.каналу»: зміну ще не робили */
#define ROAM_JUMP          10     /* лівий/правий у виборі каналу: через стільки пунктів */

/* Видимі рядки списку: від -MENU_START_ITERATION_VALUE позицій над курсором до MENU_END_ITERATION_VALUE під ним. */
#define ROAM_ROWS_BACK     (-(MENU_START_ITERATION_VALUE))
#define ROAM_ROWS_SPAN     ((MENU_END_ITERATION_VALUE - MENU_START_ITERATION_VALUE) + 1)

/* Стан екрана -- у CCM (на старті там сміття: обнуляється на isFirstRun до будь-якого читання). */
static struct
{
	uint8_t  view;
	uint8_t  list;        /* вибраний список 1..10 (перегляд, додавання) */
	uint8_t  pend;        /* «Спис.каналу»: очікуване значення 0..10 або ROAM_PEND_NONE */
	uint8_t  cfmFrom;     /* підтвердження «Перенести»: список, з якого переносимо */
	uint8_t  mainIdx;     /* рядок головного екрана, куди повернутись */
	uint8_t  pickIdx;     /* рядок вибору списку, куди повернутись */
	uint16_t count;       /* члени: скільки каналів у списку; вибір каналу: скільки зайнятих каналів у кодплазі */
	uint16_t curChan;     /* канал під курсором (0 -- рядок «+ Додати канал...») */
#if defined(ENABLE_WAKE_DIAG)
	uint8_t  wakeAge;     /* який сеанс журналу показано (0 = найновіший) */
	ticksTimer_t wakeTimer;
#endif
} s_roam __attribute__((section(".ccmram")));   /* CCM-INIT(menuRoam) -- memset(&s_roam) на isFirstRun, до будь-якого читання */

static void mainUpdate(void);
static void mainEvent(uiEvent_t *ev, menuStatus_t *ec);
static void pickUpdate(void);
static void pickEvent(uiEvent_t *ev);
static void membersOpen(uint8_t list);
static void membersUpdate(void);
static void membersEvent(uiEvent_t *ev);
static void addOpen(void);
static void addUpdate(void);
static void addEvent(uiEvent_t *ev);
static void confirmUpdate(void);
static void confirmEvent(uiEvent_t *ev);
#if defined(ENABLE_WAKE_DIAG)
static void wakeUpdate(void);
static void wakeEvent(uiEvent_t *ev);
#endif

static void redrawCurrent(void)
{
	switch (s_roam.view)
	{
		case ROAM_VIEW_PICK:       pickUpdate(); break;
		case ROAM_VIEW_MEMBERS:    membersUpdate(); break;
		case ROAM_VIEW_ADD:        addUpdate(); break;
		case ROAM_VIEW_CFM_REMOVE:
		case ROAM_VIEW_CFM_MOVE:   confirmUpdate(); break;
#if defined(ENABLE_WAKE_DIAG)
		case ROAM_VIEW_WAKE:       wakeUpdate(); break;
#endif
		default:                   mainUpdate(); break;
	}
}

menuStatus_t menuRoam(uiEvent_t *ev, bool isFirstRun)
{
	menuStatus_t exitCode = MENU_STATUS_SUCCESS;

	if (isFirstRun)
	{
		memset(&s_roam, 0, sizeof(s_roam));
		s_roam.view = ROAM_VIEW_MAIN;
		s_roam.pend = ROAM_PEND_NONE;
		menuDataGlobal.currentItemIndex = 0;
		menuDataGlobal.numItems = ROAM_ROWS;
		mainUpdate();
		return (MENU_STATUS_LIST_TYPE | MENU_STATUS_SUCCESS);
	}

	/* Синтетична FUNC_REDRAW (картку-сповіщення закрито, у буфері лишилась лише вона) -- перемалювати поточний екран. */
	if (ev->hasEvent && (ev->events & FUNCTION_EVENT) && (ev->function == FUNC_REDRAW))
	{
		redrawCurrent();
		return exitCode;
	}

	switch (s_roam.view)
	{
		case ROAM_VIEW_PICK:
			if (ev->hasEvent) { pickEvent(ev); }
			break;
		case ROAM_VIEW_MEMBERS:
			if (ev->hasEvent) { membersEvent(ev); }
			break;
		case ROAM_VIEW_ADD:
			if (ev->hasEvent) { addEvent(ev); }
			break;
		case ROAM_VIEW_CFM_REMOVE:
		case ROAM_VIEW_CFM_MOVE:
			if (ev->hasEvent) { confirmEvent(ev); }
			break;
#if defined(ENABLE_WAKE_DIAG)
		case ROAM_VIEW_WAKE:
			if (ev->hasEvent) { wakeEvent(ev); }
			if ((s_roam.view == ROAM_VIEW_WAKE) && ticksTimerHasExpired(&s_roam.wakeTimer))
			{
				wakeUpdate();
			}
			break;
#endif
		default:
			if (ev->hasEvent) { mainEvent(ev, &exitCode); }
			break;
	}

	return exitCode;
}

/* Текст значення списку: 0 -> «Вимк», 1..10 -> число. */
static void listValueText(uint8_t list, char *buf, size_t len)
{
	if (list == 0U)
	{
		snprintf(buf, len, "%s", ROAM_OFF_S);
	}
	else
	{
		snprintf(buf, len, "%u", (unsigned)list);
	}
}

/* ============================ ГОЛОВНИЙ ЕКРАН ============================ */
static void mainUpdate(void)
{
	char buf[24];
	char val[8];

	displayClearBuf();
	menuDisplayTitle(ROAM_MENU_NAME);

	for (int i = MENU_START_ITERATION_VALUE; i <= MENU_END_ITERATION_VALUE; i++)
	{
		int mNum = menuGetMenuOffset(ROAM_ROWS, i);

		if (mNum == MENU_OFFSET_BEFORE_FIRST_ENTRY) { continue; }
		if (mNum == MENU_OFFSET_AFTER_LAST_ENTRY)   { break; }

		switch (mNum)
		{
			case ROAM_ROW_AUTO: snprintf(buf, sizeof buf, ROAM_ROW_AUTO_FMT, (roamCfgIsEnabled() ? ROAM_ON_S : ROAM_OFF_S)); break;
			case ROAM_ROW_HOPS: snprintf(buf, sizeof buf, ROAM_ROW_HOPS_FMT, (unsigned)roamCfgMaxHops()); break;
			case ROAM_ROW_CHLIST:
				/* У режимі VFO поточного «каналу кодплагу» нема -- показуємо «-» (дія дасть пояснення). */
				if (menuSystemGetRootMenuNumber() == UI_CHANNEL_MODE)
				{
					listValueText((s_roam.pend == ROAM_PEND_NONE) ? roamCurrentList() : s_roam.pend, val, sizeof val);
				}
				else
				{
					snprintf(val, sizeof val, "-");
				}
				snprintf(buf, sizeof buf, ROAM_ROW_CHLIST_FMT, val, (s_roam.pend == ROAM_PEND_NONE) ? "" : "*");
				break;
			case ROAM_ROW_LISTS: snprintf(buf, sizeof buf, "%s", ROAM_ROW_LISTS_S); break;
#if defined(ENABLE_WAKE_DIAG)
			case ROAM_ROW_WAKE: snprintf(buf, sizeof buf, WAKE_ITEM); break;
#endif
			default:            buf[0] = 0; break;
		}

		menuDisplayEntry(i, mNum, buf, 0, THEME_ITEM_FG_MENU_ITEM, THEME_ITEM_FG_OPTIONS_VALUE, THEME_ITEM_BG);
	}

	displayRender();
}

static void saveCfg(bool enabled, uint8_t hops)
{
	if (roamCfgSave(enabled, hops) == false)
	{
		uiNotificationShowShort(1500, ROAM_MSG_SAVE_ERR, true);
	}
}

/* Повідомлення за результатом призначення списку. okMsg -- що казати при успіху. */
static const char *assignMessage(roamAssign_t r, const char *okMsg)
{
	switch (r)
	{
		case ROAM_ASSIGN_OK:         return okMsg;
		case ROAM_ASSIGN_UNSUITABLE: return ROAM_MSG_UNSUITABLE;
		case ROAM_ASSIGN_READONLY:   return ROAM_MSG_READONLY;
		case ROAM_ASSIGN_BAD:        return ROAM_MSG_NOT_CHANNEL;
		default:                     return ROAM_MSG_SAVE_ERR;
	}
}

/* Зберегти «Спис.каналу» (green): один запис поточного каналу. */
static void commitChannelList(void)
{
	const char *msg;
	uint8_t was;
	roamAssign_t r;

	if (s_roam.pend == ROAM_PEND_NONE)
	{
		return;
	}

	was = roamCurrentList();

	if (s_roam.pend == was)   /* вибрали те, що вже є -- нічого не пишемо і не повідомляємо */
	{
		s_roam.pend = ROAM_PEND_NONE;
		mainUpdate();
		return;
	}

	r = roamCurrentAssign(s_roam.pend);
	msg = assignMessage(r, ((s_roam.pend == 0U) ? ROAM_MSG_REMOVED : ((was == 0U) ? ROAM_MSG_ADDED : ROAM_MSG_MOVED)));
	s_roam.pend = ROAM_PEND_NONE;   /* і при успіху, і при відмові показуємо те, що справді в записі */
	mainUpdate();
	uiNotificationShowShort(1500, msg, true);
}

static void mainEvent(uiEvent_t *ev, menuStatus_t *ec)
{
	if ((ev->events & KEY_EVENT) == 0) { return; }

	if (KEYCHECK_PRESS(ev->keys, KEY_DOWN))
	{
		menuSystemMenuIncrement(&menuDataGlobal.currentItemIndex, ROAM_ROWS);
		*ec |= MENU_STATUS_LIST_TYPE; mainUpdate(); return;
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_UP))
	{
		menuSystemMenuDecrement(&menuDataGlobal.currentItemIndex, ROAM_ROWS);
		*ec |= MENU_STATUS_LIST_TYPE; mainUpdate(); return;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		menuSystemPopPreviousMenu(); return;
	}

	bool right = KEYCHECK_PRESS(ev->keys, KEY_RIGHT);
	bool left  = KEYCHECK_PRESS(ev->keys, KEY_LEFT);
	bool green = KEYCHECK_SHORTUP(ev->keys, KEY_GREEN);

	if ((right || left || green) == false) { return; }

	switch (menuDataGlobal.currentItemIndex)
	{
		case ROAM_ROW_AUTO:
			saveCfg((roamCfgIsEnabled() == false), roamCfgMaxHops());
			mainUpdate();
			break;
		case ROAM_ROW_HOPS:
		{
			int hops = (int)roamCfgMaxHops();

			if (left)  { hops = (hops > (int)ROAM_HOPS_MIN) ? (hops - 1) : (int)ROAM_HOPS_MAX; }
			else       { hops = (hops < (int)ROAM_HOPS_MAX) ? (hops + 1) : (int)ROAM_HOPS_MIN; }

			saveCfg(roamCfgIsEnabled(), (uint8_t)hops);
			mainUpdate();
			break;
		}
		case ROAM_ROW_CHLIST:
			if (menuSystemGetRootMenuNumber() != UI_CHANNEL_MODE)
			{
				uiNotificationShowShort(1500, ROAM_MSG_NOT_CHANNEL, true);
			}
			else if (green)
			{
				commitChannelList();
			}
			else
			{
				/* Лівий/правий лише міняють очікуване значення (0..10 по колу); запис -- зеленою, щоб гортання не пекло флеш. */
				int v = (s_roam.pend == ROAM_PEND_NONE) ? (int)roamCurrentList() : (int)s_roam.pend;
				int span = (int)ROAM_LISTS_COUNT + 1;

				v = (v + (left ? (span - 1) : 1)) % span;
				s_roam.pend = (uint8_t)v;
				mainUpdate();
			}
			break;
		case ROAM_ROW_LISTS:
			if (green)
			{
				s_roam.mainIdx = (uint8_t)menuDataGlobal.currentItemIndex;
				s_roam.view = ROAM_VIEW_PICK;
				menuDataGlobal.numItems = (int)ROAM_LISTS_COUNT;
				menuDataGlobal.currentItemIndex = (int)((s_roam.list >= 1U) ? (s_roam.list - 1U) : (((menuSystemGetRootMenuNumber() == UI_CHANNEL_MODE) && (roamCurrentList() != 0U)) ? (roamCurrentList() - 1U) : 0U));
				pickUpdate();
			}
			break;
#if defined(ENABLE_WAKE_DIAG)
		case ROAM_ROW_WAKE:
			if (green)
			{
				s_roam.view = ROAM_VIEW_WAKE;
				s_roam.wakeAge = 0;
				wakeUpdate();
			}
			break;
#endif
		default:
			break;
	}
}

static void backToMain(void)
{
	s_roam.view = ROAM_VIEW_MAIN;
	menuDataGlobal.numItems = ROAM_ROWS;
	menuDataGlobal.currentItemIndex = s_roam.mainIdx;
	mainUpdate();
}

/* ============================ ВИБІР СПИСКУ 1..10 ============================ */
static void pickUpdate(void)
{
	char buf[24];

	displayClearBuf();
	menuDisplayTitle(ROAM_PICK_TITLE);

	for (int i = MENU_START_ITERATION_VALUE; i <= MENU_END_ITERATION_VALUE; i++)
	{
		int mNum = menuGetMenuOffset((int)ROAM_LISTS_COUNT, i);

		if (mNum == MENU_OFFSET_BEFORE_FIRST_ENTRY) { continue; }
		if (mNum == MENU_OFFSET_AFTER_LAST_ENTRY)   { break; }

		snprintf(buf, sizeof buf, ROAM_PICK_ROW_FMT, (unsigned)(mNum + 1));
		menuDisplayEntry(i, mNum, buf, 0, THEME_ITEM_FG_MENU_ITEM, THEME_ITEM_FG_OPTIONS_VALUE, THEME_ITEM_BG);
	}

	displayRender();
}

static void pickEvent(uiEvent_t *ev)
{
	if ((ev->events & KEY_EVENT) == 0) { return; }

	if (KEYCHECK_PRESS(ev->keys, KEY_DOWN))
	{
		menuSystemMenuIncrement(&menuDataGlobal.currentItemIndex, (int)ROAM_LISTS_COUNT);
		pickUpdate();
	}
	else if (KEYCHECK_PRESS(ev->keys, KEY_UP))
	{
		menuSystemMenuDecrement(&menuDataGlobal.currentItemIndex, (int)ROAM_LISTS_COUNT);
		pickUpdate();
	}
	else if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		s_roam.pickIdx = (uint8_t)menuDataGlobal.currentItemIndex;
		membersOpen((uint8_t)(menuDataGlobal.currentItemIndex + 1));
	}
	else if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		backToMain();
	}
}

/* ============================ КУРСОР ПО СПИСКУ КАНАЛІВ ============================ */
/* Два екрани мають курсор, що біжить по каналах: «члени» (члени списку + останній рядок «+ Додати») і «вибір каналу» (усі зайняті канали).
 * Пункти доступні лише послідовно (за номером каналу), тож тримаємо номер каналу під курсором (curChan) і сусідів знаходимо кроком
 * від нього -- без повторного скану з початку. menuDataGlobal.currentItemIndex -- порядковий номер пункту, numItems -- їх кількість. */

/* Крок курсора на одну позицію (dir = +1/-1) по колу. members: пункти 0..count-1 -- канали списку, пункт count -- рядок «+ Додати» (канал 0). */
static void navStep(bool members, int *idx, int *chan, int dir)
{
	int n = (int)menuDataGlobal.numItems;
	int newIdx;

	if (n <= 0)
	{
		return;
	}

	newIdx = (((*idx + dir) % n) + n) % n;

	if (members)
	{
		*chan = (newIdx == (n - 1)) ? 0 : roamListStep(s_roam.list, *chan, dir);   /* з рядка «+ Додати» (канал 0): вперед -- перший член, назад -- останній */
	}
	else
	{
		*chan = roamChannelStep(*chan, dir);
	}

	*idx = newIdx;
}

/* Канали видимих рядків: chAt[i + ROAM_ROWS_BACK] -- для рядка зі зсувом i від курсора. */
static void visibleChannels(bool members, int16_t *chAt)
{
	int idx = (int)menuDataGlobal.currentItemIndex;
	int chan = (int)s_roam.curChan;

	chAt[ROAM_ROWS_BACK] = (int16_t)chan;

	for (int d = 1; d <= MENU_END_ITERATION_VALUE; d++)
	{
		navStep(members, &idx, &chan, 1);
		chAt[ROAM_ROWS_BACK + d] = (int16_t)chan;
	}

	idx = (int)menuDataGlobal.currentItemIndex;
	chan = (int)s_roam.curChan;

	for (int d = 1; d <= ROAM_ROWS_BACK; d++)
	{
		navStep(members, &idx, &chan, -1);
		chAt[ROAM_ROWS_BACK - d] = (int16_t)chan;
	}
}

/* Прочитати назву каналу (cp1251 для показу) і, за потреби, його список/придатність. */
static void channelRowInfo(int num, char *name17, uint8_t *list, bool *suitable)
{
	CodeplugChannel_t rec;

	codeplugChannelGetDataForIndex(num, &rec);
	codeplugUtilConvertBufToDisplayString(rec.name, name17, 16);
	*list = roamRecList(&rec);
	*suitable = roamRecSuitable(&rec);
}

/* Рядок «номер ім'я» у ширину екрана (до 18 символів FONT_SIZE_3): ім'я скорочується, суфікс (список/позначка) лишається. */
static void channelRowText(char *out, size_t outLen, int num, const char *name17, const char *suffix)
{
	char numBuf[8];
	int avail = 18;
	int nl;
	int sl = (int)strlen(suffix);
	char nameCut[17];

	snprintf(numBuf, sizeof numBuf, "%d", num);
	nl = avail - (int)strlen(numBuf) - 1 - sl;
	if (nl < 0) { nl = 0; }
	if (nl > 16) { nl = 16; }
	snprintf(nameCut, sizeof nameCut, "%.*s", nl, name17);
	snprintf(out, outLen, "%s %s%s", numBuf, nameCut, suffix);
}

/* ============================ ЧЛЕНИ СПИСКУ ============================ */
static void membersOpen(uint8_t list)
{
	s_roam.list = list;
	s_roam.count = (uint16_t)roamListCount(list);
	s_roam.view = ROAM_VIEW_MEMBERS;
	menuDataGlobal.numItems = (int)s_roam.count + 1;   /* + рядок «+ Додати канал...» */
	menuDataGlobal.currentItemIndex = 0;
	s_roam.curChan = (uint16_t)((s_roam.count > 0U) ? roamListStep(list, 0, 1) : 0);
	membersUpdate();
}

static void membersUpdate(void)
{
	char buf[28];
	char name[17];
	int16_t chAt[ROAM_ROWS_SPAN];
	uint8_t lst;
	bool ok;

	visibleChannels(true, chAt);

	displayClearBuf();
	snprintf(buf, sizeof buf, ROAM_MEM_TITLE_FMT, (unsigned)s_roam.list, (unsigned)s_roam.count);
	menuDisplayTitle(buf);

	for (int i = MENU_START_ITERATION_VALUE; i <= MENU_END_ITERATION_VALUE; i++)
	{
		int mNum = menuGetMenuOffset((int)menuDataGlobal.numItems, i);
		int num;

		if (mNum == MENU_OFFSET_BEFORE_FIRST_ENTRY) { continue; }
		if (mNum == MENU_OFFSET_AFTER_LAST_ENTRY)   { break; }

		num = chAt[i + ROAM_ROWS_BACK];

		if (num == 0)
		{
			snprintf(buf, sizeof buf, "%s", ROAM_ADD_ROW);
		}
		else
		{
			channelRowInfo(num, name, &lst, &ok);
			channelRowText(buf, sizeof buf, num, name, "");
		}

		menuDisplayEntry(i, mNum, buf, 0, THEME_ITEM_FG_MENU_ITEM, THEME_ITEM_FG_OPTIONS_VALUE, THEME_ITEM_BG);
	}

	displayRender();
}

static void membersMove(int dir)
{
	int idx = (int)menuDataGlobal.currentItemIndex;
	int chan = (int)s_roam.curChan;

	navStep(true, &idx, &chan, dir);
	menuDataGlobal.currentItemIndex = idx;
	s_roam.curChan = (uint16_t)chan;
}

static void membersEvent(uiEvent_t *ev)
{
	if ((ev->events & KEY_EVENT) == 0) { return; }

	if (KEYCHECK_PRESS(ev->keys, KEY_DOWN))
	{
		membersMove(1);
		membersUpdate();
	}
	else if (KEYCHECK_PRESS(ev->keys, KEY_UP))
	{
		membersMove(-1);
		membersUpdate();
	}
	else if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		if (s_roam.curChan == 0U)
		{
			addOpen();
		}
		else
		{
			s_roam.view = ROAM_VIEW_CFM_REMOVE;
			confirmUpdate();
		}
	}
	else if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		s_roam.view = ROAM_VIEW_PICK;
		menuDataGlobal.numItems = (int)ROAM_LISTS_COUNT;
		menuDataGlobal.currentItemIndex = s_roam.pickIdx;
		pickUpdate();
	}
}

/* ============================ ВИБІР КАНАЛУ ДЛЯ ДОДАВАННЯ ============================ */
static void addOpen(void)
{
	int start = (int)uiDataGlobal.currentSelectedChannelNumber;
	int total = 0;
	int pos = 0;

	for (int num = CODEPLUG_CHANNELS_MIN; num <= CODEPLUG_CHANNELS_MAX; num++)
	{
		if (codeplugAllChannelsIndexIsInUse(num))
		{
			if (num < start) { pos++; }
			total++;
		}
	}

	if (total == 0)
	{
		uiNotificationShowShort(1500, ROAM_MSG_SAVE_ERR, true);
		return;
	}

	if ((start < CODEPLUG_CHANNELS_MIN) || (start > CODEPLUG_CHANNELS_MAX) || (codeplugAllChannelsIndexIsInUse(start) == false))
	{
		start = roamChannelStep(0, 1);   /* поточного каналу нема (VFO) -- починаємо з першого */
		pos = 0;
	}

	s_roam.count = (uint16_t)total;
	s_roam.view = ROAM_VIEW_ADD;
	menuDataGlobal.numItems = total;
	menuDataGlobal.currentItemIndex = pos;
	s_roam.curChan = (uint16_t)start;
	addUpdate();
}

static void addUpdate(void)
{
	char buf[28];
	char name[17];
	char suf[6];
	int16_t chAt[ROAM_ROWS_SPAN];
	uint8_t lst;
	bool ok;

	visibleChannels(false, chAt);

	displayClearBuf();
	snprintf(buf, sizeof buf, ROAM_ADD_TITLE_FMT, (unsigned)s_roam.list);
	menuDisplayTitle(buf);

	for (int i = MENU_START_ITERATION_VALUE; i <= MENU_END_ITERATION_VALUE; i++)
	{
		int mNum = menuGetMenuOffset((int)menuDataGlobal.numItems, i);
		int num;

		if (mNum == MENU_OFFSET_BEFORE_FIRST_ENTRY) { continue; }
		if (mNum == MENU_OFFSET_AFTER_LAST_ENTRY)   { break; }

		num = chAt[i + ROAM_ROWS_BACK];
		channelRowInfo(num, name, &lst, &ok);

		/* Суфікс: номер списку, у якому канал уже є; «-» -- у жодному; «!» -- не може бути в списку (аналог, DMO, симплекс, лише прийом, ...). */
		if (ok == false)       { snprintf(suf, sizeof suf, " !"); }
		else if (lst == 0U)    { snprintf(suf, sizeof suf, " -"); }
		else                   { snprintf(suf, sizeof suf, " %u", (unsigned)lst); }

		channelRowText(buf, sizeof buf, num, name, suf);
		menuDisplayEntry(i, mNum, buf, 0, THEME_ITEM_FG_MENU_ITEM, THEME_ITEM_FG_OPTIONS_VALUE, THEME_ITEM_BG);
	}

	displayRender();
}

static void addMove(int dir)
{
	int idx = (int)menuDataGlobal.currentItemIndex;
	int chan = (int)s_roam.curChan;

	navStep(false, &idx, &chan, dir);
	menuDataGlobal.currentItemIndex = idx;
	s_roam.curChan = (uint16_t)chan;
}

/* Вернутись на екран «члени» після зміни: курсор на каналі ch (якщо він тепер член), кількість перераховано. */
static void backToMembers(int cursorChan)
{
	s_roam.count = (uint16_t)roamListCount(s_roam.list);
	s_roam.view = ROAM_VIEW_MEMBERS;
	menuDataGlobal.numItems = (int)s_roam.count + 1;

	if ((cursorChan >= CODEPLUG_CHANNELS_MIN) && (roamChannelList(cursorChan) == s_roam.list))
	{
		int pos = 0;

		for (int num = CODEPLUG_CHANNELS_MIN; num < cursorChan; num++)
		{
			if (roamChannelList(num) == s_roam.list) { pos++; }
		}
		menuDataGlobal.currentItemIndex = pos;
		s_roam.curChan = (uint16_t)cursorChan;
	}
	else
	{
		menuDataGlobal.currentItemIndex = (int)s_roam.count;   /* рядок «+ Додати» */
		s_roam.curChan = 0U;
	}

	membersUpdate();
}

/* Призначити канал ch у вибраний список і повернутись до «членів». okMsg -- сповіщення при успіху. */
static void assignAndReturn(int ch, const char *okMsg)
{
	roamAssign_t r = roamChannelAssign(ch, s_roam.list);
	const char *msg = assignMessage(r, okMsg);

	if (r == ROAM_ASSIGN_OK)
	{
		backToMembers(ch);
	}
	else
	{
		s_roam.view = ROAM_VIEW_ADD;
		addUpdate();
	}
	uiNotificationShowShort(1500, msg, true);
}

static void addEvent(uiEvent_t *ev)
{
	if ((ev->events & KEY_EVENT) == 0) { return; }

	if (KEYCHECK_PRESS(ev->keys, KEY_DOWN))
	{
		addMove(1);
		addUpdate();
	}
	else if (KEYCHECK_PRESS(ev->keys, KEY_UP))
	{
		addMove(-1);
		addUpdate();
	}
	else if (KEYCHECK_PRESS(ev->keys, KEY_RIGHT) || KEYCHECK_PRESS(ev->keys, KEY_LEFT))
	{
		int dir = KEYCHECK_PRESS(ev->keys, KEY_RIGHT) ? 1 : -1;

		for (int k = 0; k < ROAM_JUMP; k++)
		{
			addMove(dir);
		}
		addUpdate();
	}
	else if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		int ch = (int)s_roam.curChan;
		uint8_t where = roamChannelList(ch);
		CodeplugChannel_t rec;

		codeplugChannelGetDataForIndex(ch, &rec);

		if (roamRecSuitable(&rec) == false)
		{
			uiNotificationShowShort(1500, ROAM_MSG_UNSUITABLE, true);   /* показуємо, але не додаємо */
		}
		else if (where == s_roam.list)
		{
			uiNotificationShowShort(1500, ROAM_MSG_ALREADY, true);
		}
		else if (where != 0U)
		{
			s_roam.cfmFrom = where;   /* канал вже в ІНШОМУ списку -- спершу питаємо */
			s_roam.view = ROAM_VIEW_CFM_MOVE;
			confirmUpdate();
		}
		else
		{
			assignAndReturn(ch, ROAM_MSG_ADDED);
		}
	}
	else if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		backToMembers(0);   /* без змін -- курсор на рядку «+ Додати», звідки відкрили вибір */
	}
}

/* ============================ ПІДТВЕРДЖЕННЯ ============================ */
static void confirmUpdate(void)
{
	char name[17];
	char buf[32];
	uint8_t lst;
	bool ok;
	int ch = (int)s_roam.curChan;

	displayClearBuf();

	if (s_roam.view == ROAM_VIEW_CFM_REMOVE)
	{
		menuDisplayTitle(ROAM_CFM_REMOVE_TITLE);
		channelRowInfo(ch, name, &lst, &ok);
		channelRowText(buf, sizeof buf, ch, name, "");
		displayPrintCentered(24, buf, FONT_SIZE_3);
		snprintf(buf, sizeof buf, ROAM_CFM_FROM_FMT, (unsigned)s_roam.list);
		displayPrintCentered(44, buf, FONT_SIZE_3);
	}
	else
	{
		menuDisplayTitle(ROAM_CFM_MOVE_TITLE);
		channelRowInfo(ch, name, &lst, &ok);
		channelRowText(buf, sizeof buf, ch, name, "");
		displayPrintCentered(24, buf, FONT_SIZE_3);
		snprintf(buf, sizeof buf, ROAM_CFM_MOVE_FMT, (unsigned)s_roam.cfmFrom, (unsigned)s_roam.list);
		displayPrintCentered(44, buf, FONT_SIZE_3);
	}

	displayDrawChoice(CHOICE_YESNO, false);
	displayRender();
}

static void confirmEvent(uiEvent_t *ev)
{
	if ((ev->events & KEY_EVENT) == 0) { return; }

	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		if (s_roam.view == ROAM_VIEW_CFM_REMOVE)
		{
			int old = (int)s_roam.curChan;
			roamAssign_t r = roamChannelAssign(old, 0U);
			const char *msg = assignMessage(r, ROAM_MSG_REMOVED);

			s_roam.view = ROAM_VIEW_MEMBERS;
			if (r == ROAM_ASSIGN_OK)
			{
				int idx = (int)menuDataGlobal.currentItemIndex;

				s_roam.count = (uint16_t)roamListCount(s_roam.list);
				menuDataGlobal.numItems = (int)s_roam.count + 1;

				if (idx >= (int)s_roam.count)
				{
					menuDataGlobal.currentItemIndex = (int)s_roam.count;   /* прибрали останній -- курсор на «+ Додати» */
					s_roam.curChan = 0U;
				}
				else
				{
					s_roam.curChan = (uint16_t)roamListStep(s_roam.list, old, 1);   /* наступний член займає місце прибраного */
				}
			}
			membersUpdate();
			uiNotificationShowShort(1500, msg, true);
		}
		else
		{
			assignAndReturn((int)s_roam.curChan, ROAM_MSG_MOVED);
		}
	}
	else if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		s_roam.view = (s_roam.view == ROAM_VIEW_CFM_REMOVE) ? ROAM_VIEW_MEMBERS : ROAM_VIEW_ADD;
		redrawCurrent();
	}
}

#if defined(ENABLE_WAKE_DIAG)
/* ============================ ЖУРНАЛ ПРОБУДЖЕННЯ (R58, перенесено з «Повідомлень») ============================ */
/* Журнал сеансів пробудження ретранслятора (functions/wake_diag.c): по одному сеансу на екран, 9 рядків FONT_SIZE_1.
 * DOWN -- старіший сеанс, UP -- новіший, довге GREEN -- скинути журнал, RED -- назад. Розшифровка -- TESTING.md, блок DF/DG.
 * Журнал тепер показує й стрибки автопереходу (поле «hop» останнього рядка). */
static void wakeUpdate(void)
{
	char buf[40];
	wakeDiagSession_t ws;
	unsigned total = wakeDiagCount();

	displayClearBuf();
	if (total == 0U)
	{
		snprintf(buf, sizeof buf, WAKE_TITLE_FMT, 0U, 0U);
		menuDisplayTitle(buf);
		displayPrintCentered(50, WAKE_EMPTY, FONT_SIZE_1);
	}
	else
	{
		if (s_roam.wakeAge >= total) { s_roam.wakeAge = (uint8_t)(total - 1U); }
		(void)wakeDiagGet(s_roam.wakeAge, &ws);
		snprintf(buf, sizeof buf, WAKE_TITLE_FMT, (unsigned)s_roam.wakeAge + 1U, total);
		menuDisplayTitle(buf);
		for (unsigned line = 0U; line < WAKE_DIAG_LINES; line++)
		{
			if (wakeDiagLine(&ws, s_roam.wakeAge, total, wakeDiagDirectTx(), line, buf, (int)sizeof buf))
			{
				displayPrintAt(2, (int16_t)(16 + (10 * (int)line)), buf, FONT_SIZE_1);
			}
		}
	}
	displayPrintCentered(112, WAKE_HINT, FONT_SIZE_1);
	displayRender();

	ticksTimerStart(&s_roam.wakeTimer, ROAM_REFRESH_MS);
}

static void wakeEvent(uiEvent_t *ev)
{
	if ((ev->events & KEY_EVENT) == 0) { return; }
	if (KEYCHECK_LONGDOWN(ev->keys, KEY_GREEN))
	{
		wakeDiagReset();
		s_roam.wakeAge = 0;
		wakeUpdate();
		return;
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_DOWN))
	{
		if (((unsigned)s_roam.wakeAge + 1U) < wakeDiagCount()) { s_roam.wakeAge++; }
		wakeUpdate();
		return;
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_UP))
	{
		if (s_roam.wakeAge > 0U) { s_roam.wakeAge--; }
		wakeUpdate();
		return;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		s_roam.view = ROAM_VIEW_MAIN;
		menuDataGlobal.currentItemIndex = ROAM_ROW_WAKE;   // повернутись на рядок «Журнал пробудж.»
		mainUpdate();
	}
}
#endif /* ENABLE_WAKE_DIAG */

#endif /* ENABLE_ROAM_RETRY */
