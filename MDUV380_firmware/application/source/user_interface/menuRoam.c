/*
 * menuRoam.c -- R59/R60: пункт головного меню «Роумінг» (ENABLE_ROAM_RETRY).
 *
 * Головний екран: «Автоперехід» (Вимк/Увімк), «Макс.стрибків» (1..5), «Списки» (перегляд і редагування) і, з ENABLE_WAKE_DIAG,
 * «Журнал пробудж.» (R58, перенесено сюди з «Повідомлень»; логіка журналу й USB 0xB7 без змін).
 *
 * «Списки» (R60): вибір номера 1..10 -> члени списку (номер каналу + ім'я; зелена на члені -- прибрати зі списку після підтвердження;
 * останній рядок «+ Додати канал...» -- вибір серед УСІХ каналів кодплагу, зелена призначає канал у цей список; якщо канал уже в ІНШОМУ
 * списку, спершу питання «Перенести?», бо канал належить лише до одного списку). Кожна зміна -- ОДИН запис одного каналу
 * (roamChannelAssign() -> codeplugChannelSaveDataForIndex), решта кодплагу не чіпається; ті самі дані читає CPS.
 *
 * R61: головний екран, вибір списку, члени, вибір каналу й питання «Прибрати/Перенести» малюються й гортаються спільним кодом
 * (listUpdate / listEvent), щоб прошивка вмістилась до фіксованої адреси кодека; поведінка та сама, що в R60.
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

enum { ROAM_VIEW_MAIN = 0, ROAM_VIEW_PICK, ROAM_VIEW_MEMBERS, ROAM_VIEW_ADD, ROAM_VIEW_CFM_REMOVE, ROAM_VIEW_CFM_MOVE, ROAM_VIEW_WAKE
#if defined(ROAM_NAMES_ENABLED)
	, ROAM_VIEW_ACTIONS, ROAM_VIEW_RENAME, ROAM_VIEW_CFM_CLEAR   /* R64: «#» на списку -- дії; редактор імені; підтвердження «Очистити список?» */
#endif
};

#if defined(ROAM_NAMES_ENABLED)
enum { ROAM_ACT_ROW_MEMBERS = 0, ROAM_ACT_ROW_RENAME, ROAM_ACT_ROW_CLEAR, ROAM_ACT_ROWS };
/* Стан редактора імені -- у спільному буфері (uiNameEditor.h): нової RAM немає. */
#define ROAM_ED_BUF   (uiDataGlobal.MessageBox.message)
#endif

enum { ROAM_ROW_AUTO = 0, ROAM_ROW_HOPS, ROAM_ROW_LISTS
#if defined(ENABLE_WAKE_DIAG)
	, ROAM_ROW_WAKE
#endif
	, ROAM_ROWS };

#define ROAM_REFRESH_MS    500    /* журнал оновлюється сам, поки оператор дивиться */
#define ROAM_JUMP          10     /* лівий/правий у виборі каналу: через стільки пунктів */

/* Видимі рядки списку: від -MENU_START_ITERATION_VALUE позицій над курсором до MENU_END_ITERATION_VALUE під ним. */
#define ROAM_ROWS_BACK     (-(MENU_START_ITERATION_VALUE))
#define ROAM_ROWS_SPAN     ((MENU_END_ITERATION_VALUE - MENU_START_ITERATION_VALUE) + 1)

/* Стан екрана -- у CCM (на старті там сміття: обнуляється на isFirstRun до будь-якого читання). */
static struct
{
	uint8_t  view;
	uint8_t  list;        /* вибраний список 1..10 (перегляд, додавання) */
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

static void listUpdate(void);
static void confirmUpdate(void);
static void listEvent(uiEvent_t *ev, menuStatus_t *ec);
static void confirmUpdate(void);
#if defined(ENABLE_WAKE_DIAG)
static void wakeUpdate(void);
static void wakeEvent(uiEvent_t *ev);
#endif

#if defined(ROAM_NAMES_ENABLED)
static void renameDraw(void);
static void renameEvent(uiEvent_t *ev);
#endif

static void redrawCurrent(void)
{
	switch (s_roam.view)
	{
#if defined(ENABLE_WAKE_DIAG)
		case ROAM_VIEW_WAKE:       wakeUpdate(); break;
#endif
#if defined(ROAM_NAMES_ENABLED)
		case ROAM_VIEW_RENAME:     renameDraw(); break;
#endif
		default:                   listUpdate(); break;
	}
}

menuStatus_t menuRoam(uiEvent_t *ev, bool isFirstRun)
{
	menuStatus_t exitCode = MENU_STATUS_SUCCESS;

	if (isFirstRun)
	{
		memset(&s_roam, 0, sizeof(s_roam));
		s_roam.view = ROAM_VIEW_MAIN;
		menuDataGlobal.currentItemIndex = 0;
		menuDataGlobal.numItems = ROAM_ROWS;
		listUpdate();
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
#if defined(ENABLE_WAKE_DIAG)
		case ROAM_VIEW_WAKE:
			if (ev->hasEvent) { wakeEvent(ev); }
			if ((s_roam.view == ROAM_VIEW_WAKE) && ticksTimerHasExpired(&s_roam.wakeTimer))
			{
				wakeUpdate();
			}
			break;
#endif
#if defined(ROAM_NAMES_ENABLED)
		case ROAM_VIEW_RENAME:
			if (ev->hasEvent) { renameEvent(ev); }
			break;
#endif
		default:
			if (ev->hasEvent) { listEvent(ev, &exitCode); }
			break;
	}

	return exitCode;
}

/* Текст значення списку: 0 -> «Вимк», 1..10 -> число. */
void roamListText(uint8_t list, char *buf, size_t len)
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

static void saveCfg(bool enabled, uint8_t hops)
{
	if (roamCfgSave(enabled, hops) == false)
	{
		uiNotificationShowShort(1500, ROAM_MSG_SAVE_ERR, true);
	}
}

/* Поточний канал кодплагу є (режим каналів, не VFO)? */
static bool inChannelMode(void)
{
	return (menuSystemGetRootMenuNumber() == UI_CHANNEL_MODE);
}

/* Зараз екран підтвердження («Прибрати?» / «Перенести?»), а не список. */
static bool isConfirm(void)
{
#if defined(ROAM_NAMES_ENABLED)
	if (s_roam.view == ROAM_VIEW_CFM_CLEAR) { return true; }
#endif
	return ((s_roam.view == ROAM_VIEW_CFM_REMOVE) || (s_roam.view == ROAM_VIEW_CFM_MOVE));
}

/* Одна точка зміни екрана: вид, кількість пунктів і курсор. */
static void setView(uint8_t view, int numItems, int idx)
{
	s_roam.view = view;
	menuDataGlobal.numItems = numItems;
	menuDataGlobal.currentItemIndex = idx;
}

/* ============================ ГОЛОВНИЙ ЕКРАН ============================ */
/* Текст рядка mNum головного екрана (buf або константа). Малюється спільним listUpdate(). */
static const char *mainRow(int mNum, char *buf, size_t len)
{
	switch (mNum)
	{
		case ROAM_ROW_AUTO: snprintf(buf, len, ROAM_ROW_AUTO_FMT, (roamCfgIsEnabled() ? ROAM_ON_S : ROAM_OFF_S)); break;
		case ROAM_ROW_HOPS: snprintf(buf, len, ROAM_ROW_HOPS_FMT, (unsigned)roamCfgMaxHops()); break;
		case ROAM_ROW_LISTS: return ROAM_ROW_LISTS_S;
#if defined(ENABLE_WAKE_DIAG)
		case ROAM_ROW_WAKE:  return WAKE_ITEM;
#endif
		default:             return "";
	}

	return buf;
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


/* Лівий/правий/зелена на рядку головного екрана (вгору/вниз/червона -- спільні, listEvent). */
static void mainKey(bool left, bool right, bool green)
{
	if ((right || left || green) == false) { return; }

	switch (menuDataGlobal.currentItemIndex)
	{
		case ROAM_ROW_AUTO:
			saveCfg((roamCfgIsEnabled() == false), roamCfgMaxHops());
			listUpdate();
			break;
		case ROAM_ROW_HOPS:
		{
			int hops = (int)roamCfgMaxHops();

			if (left)  { hops = (hops > (int)ROAM_HOPS_MIN) ? (hops - 1) : (int)ROAM_HOPS_MAX; }
			else       { hops = (hops < (int)ROAM_HOPS_MAX) ? (hops + 1) : (int)ROAM_HOPS_MIN; }

			saveCfg(roamCfgIsEnabled(), (uint8_t)hops);
			listUpdate();
			break;
		}
		case ROAM_ROW_LISTS:
			if (green)
			{
				uint8_t cur = (s_roam.list >= 1U) ? s_roam.list : (inChannelMode() ? roamCurrentList() : 0U);

				s_roam.mainIdx = (uint8_t)menuDataGlobal.currentItemIndex;
				setView(ROAM_VIEW_PICK, (int)ROAM_LISTS_COUNT, (cur != 0U) ? ((int)cur - 1) : 0);
				listUpdate();
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

/* ============================ СПИСКИ: ВИБІР 1..10, ЧЛЕНИ, ВИБІР КАНАЛУ ============================ */
/* Три екрани -- «вибір списку» (PICK), «члени» (MEMBERS: члени списку + останній рядок «+ Додати») і «вибір каналу» (ADD: усі зайняті канали) --
 * малюються й гортаються одним кодом (listUpdate / listEvent). Два останні мають курсор, що біжить по каналах: пункти доступні лише послідовно
 * (за номером каналу), тож тримаємо номер каналу під курсором (curChan) і сусідів знаходимо кроком від нього -- без повторного скану з початку.
 * menuDataGlobal.currentItemIndex -- порядковий номер пункту, numItems -- їх кількість. */

/* Крок курсора на одну позицію (dir = +1/-1) по колу. MEMBERS: пункти 0..count-1 -- канали списку, пункт count -- рядок «+ Додати» (канал 0). */
static void navStep(int *idx, int *chan, int dir)
{
	int n = (int)menuDataGlobal.numItems;
	int newIdx;

	if (n <= 0)
	{
		return;
	}

	newIdx = (((*idx + dir) % n) + n) % n;

	if (s_roam.view == ROAM_VIEW_MEMBERS)
	{
		*chan = (newIdx == (n - 1)) ? 0 : roamListStep(s_roam.list, *chan, dir);   /* з рядка «+ Додати» (канал 0): вперед -- перший член, назад -- останній */
	}
	else if (s_roam.view == ROAM_VIEW_ADD)
	{
		*chan = roamChannelStep(*chan, dir);
	}

	*idx = newIdx;
}

/* Курсор на times позицій (dir = +1/-1). */
static void cursorMove(int dir, int times)
{
	int idx = (int)menuDataGlobal.currentItemIndex;
	int chan = (int)s_roam.curChan;

	while (times-- > 0)
	{
		navStep(&idx, &chan, dir);
	}

	menuDataGlobal.currentItemIndex = idx;
	s_roam.curChan = (uint16_t)chan;
}

/* Канали видимих рядків: chAt[i + ROAM_ROWS_BACK] -- для рядка зі зсувом i від курсора. */
static void visibleChannels(int16_t *chAt)
{
	chAt[ROAM_ROWS_BACK] = (int16_t)s_roam.curChan;

	for (int dir = 1; dir >= -1; dir -= 2)
	{
		int idx = (int)menuDataGlobal.currentItemIndex;
		int chan = (int)s_roam.curChan;
		int last = (dir > 0) ? MENU_END_ITERATION_VALUE : ROAM_ROWS_BACK;

		for (int d = 1; d <= last; d++)
		{
			navStep(&idx, &chan, dir);
			chAt[ROAM_ROWS_BACK + (dir * d)] = (int16_t)chan;
		}
	}
}

/* Прочитати назву каналу (cp1251 для показу) і його список/придатність. */
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
	size_t room = 18U - strlen(suffix);
	size_t len = (size_t)snprintf(out, outLen, "%d %s", num, name17);

	if (len > room) { len = room; }
	strcpy(out + len, suffix);   /* out вміщає до 18 символів і суфікс (до 3): buf у викликачів 28/32 байти */
}

/* Рядок каналу num для екранів MEMBERS/ADD; num == 0 -- «+ Додати канал...». Повертає текст (buf або константу). */
static const char *channelRow(char *buf, size_t len, int num)
{
	char name[17];
	char suf[6];
	const char *sp = "";
	uint8_t lst;
	bool ok;

	if (num == 0)
	{
		return ROAM_ADD_ROW;
	}

	channelRowInfo(num, name, &lst, &ok);

	if (s_roam.view == ROAM_VIEW_ADD)
	{
		/* Суфікс: номер списку, у якому канал уже є; «-» -- у жодному; «!» -- не може бути в списку (аналог, DMO, симплекс, лише прийом, ...). */
		if (ok == false)       { sp = " !"; }
		else if (lst == 0U)    { sp = " -"; }
		else                   { snprintf(suf, sizeof suf, " %u", (unsigned)lst); sp = suf; }
	}

	channelRowText(buf, len, num, name, sp);
	return buf;
}

/* Рядок списку list (1..10) для екрана «Списки»: «Список N», а з іменем (R64) -- «N ім'я», до 18 символів. */
static void pickRowText(char *buf, size_t len, unsigned list)
{
#if defined(ROAM_NAMES_ENABLED)
	char nm[ROAM_NAME_LEN + 1U];

	if (roamNameGet((uint8_t)list, nm) && (nm[0] != 0))
	{
		snprintf(buf, len, "%u %s", list, nm);
		if (strlen(buf) > 18U) { buf[18] = 0; }
		return;
	}
#endif
	snprintf(buf, len, ROAM_PICK_ROW_FMT, list);
}

static void listUpdate(void)
{
	char buf[28];
	const char *txt;
	int16_t chAt[ROAM_ROWS_SPAN];
	uint8_t view = s_roam.view;
	bool chans = ((view == ROAM_VIEW_MEMBERS) || (view == ROAM_VIEW_ADD));

	if (isConfirm())
	{
		confirmUpdate();
		return;
	}

	if (chans)
	{
		visibleChannels(chAt);
	}

	displayClearBuf();

	txt = ((view == ROAM_VIEW_MAIN) ? ROAM_MENU_NAME : ROAM_PICK_TITLE);
	if (view == ROAM_VIEW_MEMBERS)
	{
		snprintf(buf, sizeof buf, ROAM_MEM_TITLE_FMT, (unsigned)s_roam.list, (unsigned)s_roam.count);
		txt = buf;
	}
	else if (view == ROAM_VIEW_ADD)
	{
		snprintf(buf, sizeof buf, ROAM_ADD_TITLE_FMT, (unsigned)s_roam.list);
		txt = buf;
	}
#if defined(ROAM_NAMES_ENABLED)
	if (view == ROAM_VIEW_ACTIONS)
	{
		pickRowText(buf, sizeof buf, s_roam.list);
		txt = buf;
	}
#endif
	menuDisplayTitle(txt);

	for (int i = MENU_START_ITERATION_VALUE; i <= MENU_END_ITERATION_VALUE; i++)
	{
		int mNum = menuGetMenuOffset((int)menuDataGlobal.numItems, i);

		if (mNum == MENU_OFFSET_BEFORE_FIRST_ENTRY) { continue; }
		if (mNum == MENU_OFFSET_AFTER_LAST_ENTRY)   { break; }

		if (chans)
		{
			txt = channelRow(buf, sizeof buf, chAt[i + ROAM_ROWS_BACK]);
		}
		else if (view == ROAM_VIEW_MAIN)
		{
			txt = mainRow(mNum, buf, sizeof buf);
		}
#if defined(ROAM_NAMES_ENABLED)
		else if (view == ROAM_VIEW_ACTIONS)
		{
			txt = ((mNum == ROAM_ACT_ROW_MEMBERS) ? ROAM_ACT_MEMBERS : ((mNum == ROAM_ACT_ROW_RENAME) ? ROAM_ACT_RENAME : ROAM_ACT_CLEAR));
		}
#endif
		else
		{
			pickRowText(buf, sizeof buf, (unsigned)(mNum + 1));
			txt = buf;
		}

		menuDisplayEntry(i, mNum, txt, 0, THEME_ITEM_FG_MENU_ITEM, THEME_ITEM_FG_OPTIONS_VALUE, THEME_ITEM_BG);
	}

	displayRender();
}

/* Екран «члени» списку: курсор на каналі cursorChan (якщо він тепер член), кількість перераховано; інакше -- на рядку «+ Додати». */
static void membersShow(int cursorChan)
{
	int pos = 0;
	int count = (int)roamListCount(s_roam.list);

	s_roam.count = (uint16_t)count;

	if ((cursorChan >= CODEPLUG_CHANNELS_MIN) && (roamChannelList(cursorChan) == s_roam.list))
	{
		for (int num = CODEPLUG_CHANNELS_MIN; num < cursorChan; num++)
		{
			if (roamChannelList(num) == s_roam.list) { pos++; }
		}
		s_roam.curChan = (uint16_t)cursorChan;
	}
	else
	{
		pos = count;   /* рядок «+ Додати» */
		s_roam.curChan = 0U;
	}

	setView(ROAM_VIEW_MEMBERS, count + 1, pos);
	listUpdate();
}

/* Вибір каналу для додавання: усі зайняті канали, курсор на поточному. */
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
	s_roam.curChan = (uint16_t)start;
	setView(ROAM_VIEW_ADD, total, pos);
	listUpdate();
}

/* Призначити каналу ch список list (0 -- прибрати зі списку) і повернутись до «членів» (при відмові -- на екран, звідки прийшли).
 * okMsg -- сповіщення при успіху. Курсор: на ch, коли той став членом; після прибирання -- на наступному члені або на «+ Додати». */
static void assignAndReturn(int ch, uint8_t list, const char *okMsg)
{
	roamAssign_t r = roamChannelAssign(ch, list);
	const char *msg = assignMessage(r, okMsg);

	if (r == ROAM_ASSIGN_OK)
	{
		if (list == 0U)
		{
			int next = roamListStep(s_roam.list, ch, 1);

			ch = (next > ch) ? next : 0;   /* прибрали останнього (оберт) або список порожній -- «+ Додати» */
		}
		membersShow(ch);
	}
	else
	{
		s_roam.view = (list == 0U) ? ROAM_VIEW_MEMBERS : ROAM_VIEW_ADD;
		listUpdate();
	}
	uiNotificationShowShort(1500, msg, true);
}

#if defined(ROAM_NAMES_ENABLED)
/* ============================ R64: ДІЇ НАД СПИСКОМ («#» на екрані «Списки»), ІМ'Я, ОЧИЩЕННЯ ============================ */
/* «#» на списку відкриває три дії: «Склад» (як зелена на списку), «Перейменувати» (спільний редактор uiNameEditor, ім'я -- у custom-data блоці 16),
 * «Очистити список» (прибрати всі канали зі списку; ім'я лишається). Зелена на списку, як і раніше, відкриває склад. */
static void actionsOpen(void)
{
	s_roam.pickIdx = (uint8_t)menuDataGlobal.currentItemIndex;
	s_roam.list = (uint8_t)(menuDataGlobal.currentItemIndex + 1);
	setView(ROAM_VIEW_ACTIONS, (int)ROAM_ACT_ROWS, 0);
	listUpdate();
}

static void renameTitle(char *buf, size_t len)
{
	snprintf(buf, len, ROAM_REN_TITLE_FMT, (unsigned)s_roam.list);
}

static void renameDraw(void)
{
	char title[24];

	renameTitle(title, sizeof title);
	nameEdDraw(ROAM_ED_BUF, title);
}

static void renameOpen(void)
{
	char nm[ROAM_NAME_LEN + 1U];

	(void)roamNameGet(s_roam.list, nm);   /* блоку нема -- порожнє ім'я */
	nameEdInit(ROAM_ED_BUF, nm);
	s_roam.view = ROAM_VIEW_RENAME;
	renameDraw();
}

static void renameClose(bool saved)
{
	nameEdClose(ROAM_ED_BUF);
	if (saved)
	{
		setView(ROAM_VIEW_PICK, (int)ROAM_LISTS_COUNT, s_roam.pickIdx);   /* ім'я видно вже в рядку списку */
	}
	else
	{
		setView(ROAM_VIEW_ACTIONS, (int)ROAM_ACT_ROWS, ROAM_ACT_ROW_RENAME);
	}
	listUpdate();
}

static void renameEvent(uiEvent_t *ev)
{
	char title[24];

	if (ev->events & FUNCTION_EVENT)
	{
		if (ev->function == FUNC_REDRAW) { renameDraw(); }
		return;
	}

	if ((ev->events & KEY_EVENT) == 0) { return; }

	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		nameEdCommit(ROAM_ED_BUF);
		if (roamNameSet(s_roam.list, ROAM_ED_BUF))
		{
			renameClose(true);
			uiNotificationShowShort(1500, ROAM_MSG_RENAMED, true);
		}
		else
		{
			uiNotificationShowShort(1500, ROAM_MSG_SAVE_ERR, true);   /* лишаємось у редакторі: набране не втрачено */
		}
	}
	else if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		renameClose(false);
	}
	else
	{
		renameTitle(title, sizeof title);
		(void)nameEdHandleKey(ROAM_ED_BUF, title, ev);
	}
}

/* Підтвердження «Очистити список?»: показує, скільки каналів буде прибрано (скан кодплага -- як для екрана «Склад»). */
static void clearOpen(void)
{
	unsigned n = roamListCount(s_roam.list);

	if (n == 0U)
	{
		uiNotificationShowShort(1500, ROAM_MSG_LIST_EMPTY, true);
		return;
	}

	s_roam.count = (uint16_t)n;
	s_roam.view = ROAM_VIEW_CFM_CLEAR;
	confirmUpdate();
}

/* Прибрати канали зі списку: НЕ БІЛЬШЕ ROAM_CLEAR_BATCH за одне підтвердження (кожен канал -- окремий запис кодплага: перечитання 4 КБ-сектора, стирання,
 * запис; запис не захищено від зникнення живлення). Решту лишаємо й кажемо про це -- оператор повторює. Хід видно на екрані (лічильник). */
static void clearRun(void)
{
	unsigned done = 0U;
	unsigned left = 0U;
	unsigned total = (unsigned)s_roam.count;
	roamAssign_t r = ROAM_ASSIGN_OK;
	char msg[NOTIFICATION_MESSAGE_LEN_MAX];
	char line[20];

	if (total > ROAM_CLEAR_BATCH) { total = ROAM_CLEAR_BATCH; }

	for (int num = CODEPLUG_CHANNELS_MIN; num <= CODEPLUG_CHANNELS_MAX; num++)
	{
		if (roamChannelList(num) != s_roam.list) { continue; }

		if (done >= ROAM_CLEAR_BATCH) { left++; continue; }

		displayClearBuf();
		menuDisplayTitle(ROAM_CLR_BUSY_TITLE);
		snprintf(line, sizeof line, ROAM_CLR_BUSY_FMT, done + 1U, total);
		displayPrintCentered(36, line, FONT_SIZE_3);
		displayPrintCentered(60, ROAM_CLR_BUSY_HINT, FONT_SIZE_1);
		displayRender();

		r = roamChannelAssign(num, 0U);
		if (r != ROAM_ASSIGN_OK) { break; }
		done++;
	}

	setView(ROAM_VIEW_ACTIONS, (int)ROAM_ACT_ROWS, ROAM_ACT_ROW_CLEAR);
	listUpdate();

	if (r == ROAM_ASSIGN_READONLY)
	{
		snprintf(msg, sizeof msg, "%s", ROAM_MSG_READONLY);
	}
	else if (r != ROAM_ASSIGN_OK)
	{
		snprintf(msg, sizeof msg, "%s\n" ROAM_MSG_CLEARED_FMT, ROAM_MSG_SAVE_ERR, done);
	}
	else if (left != 0U)
	{
		snprintf(msg, sizeof msg, ROAM_MSG_CLEARED_MORE_FMT, done, left);
	}
	else
	{
		snprintf(msg, sizeof msg, ROAM_MSG_CLEARED_FMT, done);
	}
	uiNotificationShowShort(2000, msg, true);
}
#endif /* ROAM_NAMES_ENABLED */

static void listGreen(void)
{
	int ch = (int)s_roam.curChan;

	switch (s_roam.view)
	{
#if defined(ROAM_NAMES_ENABLED)
		case ROAM_VIEW_ACTIONS:
			if (menuDataGlobal.currentItemIndex == ROAM_ACT_ROW_MEMBERS)
			{
				membersShow(roamListStep(s_roam.list, 0, 1));
			}
			else if (menuDataGlobal.currentItemIndex == ROAM_ACT_ROW_RENAME)
			{
				renameOpen();
			}
			else
			{
				clearOpen();
			}
			break;

		case ROAM_VIEW_CFM_CLEAR:
			clearRun();
			break;
#endif
		case ROAM_VIEW_PICK:
			s_roam.pickIdx = (uint8_t)menuDataGlobal.currentItemIndex;
			s_roam.list = (uint8_t)(menuDataGlobal.currentItemIndex + 1);
			membersShow(roamListStep(s_roam.list, 0, 1));   /* курсор на першому члені (або «+ Додати», коли список порожній) */
			break;

		case ROAM_VIEW_CFM_REMOVE:
			assignAndReturn(ch, 0U, ROAM_MSG_REMOVED);
			break;

		case ROAM_VIEW_CFM_MOVE:
			assignAndReturn(ch, s_roam.list, ROAM_MSG_MOVED);
			break;

		case ROAM_VIEW_MEMBERS:
			if (ch == 0)
			{
				addOpen();
			}
			else
			{
				s_roam.view = ROAM_VIEW_CFM_REMOVE;
				confirmUpdate();
			}
			break;

		default:   /* ROAM_VIEW_ADD */
		{
			char name[17];
			uint8_t where;
			bool ok;

			channelRowInfo(ch, name, &where, &ok);

			if (ok == false)
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
				assignAndReturn(ch, s_roam.list, ROAM_MSG_ADDED);
			}
			break;
		}
	}
}

static void listRed(void)
{
	switch (s_roam.view)
	{
		case ROAM_VIEW_MAIN:
			menuSystemPopPreviousMenu();
			break;
		case ROAM_VIEW_PICK:
			setView(ROAM_VIEW_MAIN, ROAM_ROWS, s_roam.mainIdx);
			listUpdate();
			break;
		case ROAM_VIEW_MEMBERS:
			setView(ROAM_VIEW_PICK, (int)ROAM_LISTS_COUNT, s_roam.pickIdx);
			listUpdate();
			break;
#if defined(ROAM_NAMES_ENABLED)
		case ROAM_VIEW_ACTIONS:
			setView(ROAM_VIEW_PICK, (int)ROAM_LISTS_COUNT, s_roam.pickIdx);
			listUpdate();
			break;
		case ROAM_VIEW_CFM_CLEAR:   /* відмова: назад до дій, на «Очистити список» */
			setView(ROAM_VIEW_ACTIONS, (int)ROAM_ACT_ROWS, ROAM_ACT_ROW_CLEAR);
			listUpdate();
			break;
#endif
		case ROAM_VIEW_CFM_REMOVE:
		case ROAM_VIEW_CFM_MOVE:   /* відмова: назад, на екран, звідки питали */
			s_roam.view = (s_roam.view == ROAM_VIEW_CFM_REMOVE) ? ROAM_VIEW_MEMBERS : ROAM_VIEW_ADD;
			listUpdate();
			break;
		default:   /* ROAM_VIEW_ADD: без змін -- курсор на рядку «+ Додати», звідки відкрили вибір */
			membersShow(0);
			break;
	}
}

/* Клавіші головного екрана й трьох екранів списків: вгору/вниз гортають, червона -- назад; решта -- по екрану. */
static void listEvent(uiEvent_t *ev, menuStatus_t *ec)
{
	bool down = KEYCHECK_PRESS(ev->keys, KEY_DOWN);
	bool up = KEYCHECK_PRESS(ev->keys, KEY_UP);
	bool right = KEYCHECK_PRESS(ev->keys, KEY_RIGHT);
	bool left = KEYCHECK_PRESS(ev->keys, KEY_LEFT);
	bool green = KEYCHECK_SHORTUP(ev->keys, KEY_GREEN);
	bool jump = ((s_roam.view == ROAM_VIEW_ADD) && (right || left));
#if defined(ROAM_NAMES_ENABLED)
	bool hash = KEYCHECK_SHORTUP(ev->keys, KEY_HASH);
#endif
	bool conf = isConfirm();   /* на екрані підтвердження стрілки не діють */

	if ((ev->events & KEY_EVENT) == 0) { return; }

	if ((down || up || jump) && (conf == false))
	{
		cursorMove((down || right) ? 1 : -1, jump ? ROAM_JUMP : 1);
		if (s_roam.view == ROAM_VIEW_MAIN)
		{
			*ec |= MENU_STATUS_LIST_TYPE;
		}
		listUpdate();
	}
	else if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		listRed();
	}
	else if (s_roam.view == ROAM_VIEW_MAIN)
	{
		mainKey(left, right, green);
	}
#if defined(ROAM_NAMES_ENABLED)
	else if (hash && (s_roam.view == ROAM_VIEW_PICK))
	{
		actionsOpen();
	}
#endif
	else if (green)
	{
		listGreen();
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
	bool remove = (s_roam.view == ROAM_VIEW_CFM_REMOVE);

#if defined(ROAM_NAMES_ENABLED)
	if (s_roam.view == ROAM_VIEW_CFM_CLEAR)
	{
		displayClearBuf();
		menuDisplayTitle(ROAM_CLR_TITLE);
		pickRowText(buf, sizeof buf, s_roam.list);
		displayPrintCentered(24, buf, FONT_SIZE_3);
		snprintf(buf, sizeof buf, ROAM_CLR_FMT, (unsigned)s_roam.count);
		displayPrintCentered(44, buf, FONT_SIZE_3);
		displayDrawChoice(CHOICE_YESNO, false);
		displayRender();
		return;
	}
#endif

	displayClearBuf();
	menuDisplayTitle(remove ? ROAM_CFM_REMOVE_TITLE : ROAM_CFM_MOVE_TITLE);
	channelRowInfo(ch, name, &lst, &ok);
	channelRowText(buf, sizeof buf, ch, name, "");
	displayPrintCentered(24, buf, FONT_SIZE_3);

	if (remove)
	{
		snprintf(buf, sizeof buf, ROAM_CFM_FROM_FMT, (unsigned)s_roam.list);
	}
	else
	{
		snprintf(buf, sizeof buf, ROAM_CFM_MOVE_FMT, (unsigned)s_roam.cfmFrom, (unsigned)s_roam.list);
	}
	displayPrintCentered(44, buf, FONT_SIZE_3);

	displayDrawChoice(CHOICE_YESNO, false);
	displayRender();
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
		listUpdate();
	}
}
#endif /* ENABLE_WAKE_DIAG */

#endif /* ENABLE_ROAM_RETRY */
