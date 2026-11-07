/*
 * menuRxGroups.c -- R65B: пункт головного меню «Списки прийому» (ENABLE_RXGROUP_EDIT): створити, перейменувати, змінити склад і видалити TG-список з рації.
 *
 * Екрани (за зразком «Зон» і «Роумінгу» R64):
 *   перелік списків (існуючі за назвою) + «+ Новий список»; ЗЕЛЕНА на списку -- «Склад», «#» -- дії (Склад / Перейменувати / Видалити);
 *   «Склад»: контакти списку + «+ Додати контакт»; ЗЕЛЕНА на контакті -- «Вийняти?»; вибір контакту -- лише TG-контакти, без дублікатів, не більше 32;
 *   «Новий»: назва (спільний редактор uiNameEditor) -> ПЕРШИЙ контакт -> список створено (список без контактів не існує ні в стоці, ні в CPS);
 *   «Видалити» (і «Вийняти» останній контакт): питання з кількістю каналів, що посилаються на список; канали й VFO стають «Немає», потім довжина = 0, потім тіло.
 * Усі записи -- codeplug.c (codeplugRxGroup*): порядок записів і кеш описані там. Тут -- лише екрани й узгодження RAM-стану (lastLoadedRxGroup, поточний канал, VFO, позиції в списку).
 *
 * НОВОЇ пам'яті немає: стан екрана -- у uiDataGlobal.MessageBox.message[28..39] (редактор назви живе в [0..27], див. uiNameEditor.h; це вікно не показується, поки відкрите меню):
 *   [28] вид, [29] слот списку 1..76, [30] рядок переліку, куди повернутись, [31] 1 = створення (назва в [0..15] чекає перший контакт), [32] рядок складу, куди повернутись,
 *   [33] номер контакту, якого вийнято (позиція у складі), [34] 1 = видалення почато з «Вийняти» останнього контакту, [36..37] кількість каналів, що посилаються на список.
 */
#include "user_interface/uiGlobals.h"
#include "user_interface/menuSystem.h"
#include "user_interface/uiLocalisation.h"
#include "user_interface/uiUtilities.h"

#if defined(RXGROUP_UI_ENABLED)

#include <string.h>
#include "functions/codeplug.h"
#include "functions/settings.h"
#include "user_interface/uiNameEditor.h"
#include "io/keyboard.h"

#define RXG_BUF        (uiDataGlobal.MessageBox.message)
#define RXG_VIEW       (RXG_BUF[28])
#define RXG_SLOT       (RXG_BUF[29])
#define RXG_LISTIDX    (RXG_BUF[30])
#define RXG_NEW        (RXG_BUF[31])
#define RXG_MEMIDX     (RXG_BUF[32])
#define RXG_RMPOS      (RXG_BUF[33])
#define RXG_FROMLAST   (RXG_BUF[34])
#define RXG_STATE_LEN  40

enum { RXG_VIEW_LIST = 0, RXG_VIEW_ACTIONS, RXG_VIEW_MEMBERS, RXG_VIEW_PICK, RXG_VIEW_CFM_RM, RXG_VIEW_CFM_DEL, RXG_VIEW_RENAME };
enum { RXG_ACT_ROW_MEMBERS = 0, RXG_ACT_ROW_RENAME, RXG_ACT_ROW_DELETE, RXG_ACT_ROWS };

static void rxgUpdate(void);
static void rxgRenameDraw(void);

static uint16_t rxgChans(void)
{
	uint16_t v;
	memcpy(&v, &RXG_BUF[36], sizeof(v));
	return v;
}

static void rxgSetChans(uint16_t v)
{
	memcpy(&RXG_BUF[36], &v, sizeof(v));
}

static void rxgSetView(uint8_t view, int numItems, int idx)
{
	RXG_VIEW = (char)view;
	menuDataGlobal.numItems = numItems;
	menuDataGlobal.currentItemIndex = idx;
}

static bool rxgIsConfirm(void)
{
	return (RXG_VIEW == RXG_VIEW_CFM_RM) || (RXG_VIEW == RXG_VIEW_CFM_DEL);
}

static void rxgListShow(int idx)
{
	int count = codeplugRxGroupCount();

	if (idx > count) { idx = count; }
	rxgSetView(RXG_VIEW_LIST, count + 1, idx);
	rxgUpdate();
}

static void rxgContactName(uint16_t idx, char *out17)
{
	CodeplugContact_t c;

	if (codeplugContactGetDataForIndex((int)idx, &c))
	{
		codeplugUtilConvertBufToDisplayString(c.name, out17, 16);
	}
	else
	{
		snprintf(out17, 17, "#%u", (unsigned)idx);   /* контакт зі списку вилучено в CPS -- показуємо номер */
	}
}

static void rxgMembersShow(int idx)
{
	uint16_t mem[CODEPLUG_RXGROUP_MEMBERS_MAX];
	int n = codeplugRxGroupGetMembers(RXG_SLOT, mem);

	if (idx > n) { idx = n; }
	rxgSetView(RXG_VIEW_MEMBERS, n + 1, idx);
	rxgUpdate();
}

static void rxgActionsShow(int idx)
{
	rxgSetView(RXG_VIEW_ACTIONS, RXG_ACT_ROWS, idx);
	rxgUpdate();
}

static bool rxgReadOnly(void)
{
	if (settingsIsOptionBitSet(BIT_CHANNELS_ARE_READ_ONLY))
	{
		uiNotificationShowShort(1500, RXG_MSG_READONLY, true);
		return true;
	}
	return false;
}

static void rxgResultMsg(CodeplugRxGroupResult_t r)
{
	const char *m;

	switch (r)
	{
		case CODEPLUG_RXGROUP_NAME_EMPTY:  m = RXG_MSG_NAME_EMPTY; break;
		case CODEPLUG_RXGROUP_NAME_DUP:    m = RXG_MSG_NAME_DUP; break;
		case CODEPLUG_RXGROUP_NAME_TAIL:   m = RXG_MSG_NAME_TAIL; break;
		case CODEPLUG_RXGROUP_FULL:        m = RXG_MSG_FULL; break;
		case CODEPLUG_RXGROUP_DUP_MEMBER:  m = RXG_MSG_DUP_MEMBER; break;
		default:                           m = RXG_MSG_SAVE_ERR; break;
	}
	uiNotificationShowShort(1500, m, true);
}

/* Після зміни складу чи видалення: кеш поточного списку в RAM, позиції в списку (мусять не виходити за новий склад) і, при видаленні, посилання поточного каналу й VFO. */
static void rxgRamSync(int deletedSlot)
{
	lastLoadedRxGroup = -1;   /* примусово перечитати склад при наступному зверненні (канал/VFO) */

	for (int i = 0; i < 3; i++)
	{
		if (nonVolatileSettings.currentIndexInTRxGroupList[i] != 0)
		{
			settingsSet(nonVolatileSettings.currentIndexInTRxGroupList[i], 0);
		}
	}

	if (deletedSlot > 0)
	{
		for (int v = 0; v < 2; v++)
		{
			if (settingsVFOChannel[v].rxGroupList == (uint8_t)deletedSlot)
			{
				settingsVFOChannel[v].rxGroupList = 0;
				settingsSetVFODirty();
			}
		}
		if ((currentChannelData != NULL) && (currentChannelData->rxGroupList == (uint8_t)deletedSlot))
		{
			currentChannelData->rxGroupList = 0;
		}
		if (channelScreenChannelData.rxGroupList == (uint8_t)deletedSlot)
		{
			channelScreenChannelData.rxGroupList = 0;
		}
	}
}

/* ============================ МАЛЮВАННЯ ============================ */
static void rxgConfirmUpdate(void)
{
	char nm[17];
	char line[24];

	displayClearBuf();
	if (RXG_VIEW == RXG_VIEW_CFM_RM)
	{
		uint16_t mem[CODEPLUG_RXGROUP_MEMBERS_MAX];

		menuDisplayTitle(RXG_RM_TITLE);
		(void)codeplugRxGroupGetMembers(RXG_SLOT, mem);
		rxgContactName(mem[RXG_RMPOS], nm);
		displayPrintCentered(34, nm, FONT_SIZE_3);
	}
	else
	{
		menuDisplayTitle(RXG_DEL_TITLE);
		codeplugRxGroupGetName(RXG_SLOT, nm);
		if (RXG_FROMLAST != 0)
		{
			displayPrintCentered(22, RXG_RM_LAST_HINT, FONT_SIZE_3);
			displayPrintCentered(38, RXG_RM_LAST_HINT2, FONT_SIZE_3);
			snprintf(line, sizeof line, RXG_DEL_CHANS_FMT, (unsigned)rxgChans());
			displayPrintCentered(56, line, FONT_SIZE_1);
		}
		else
		{
			displayPrintCentered(24, nm, FONT_SIZE_3);
			snprintf(line, sizeof line, RXG_DEL_CHANS_FMT, (unsigned)rxgChans());
			displayPrintCentered(44, line, FONT_SIZE_3);
		}
	}
	displayDrawChoice(CHOICE_YESNO, false);
	displayRender();
}

static void rxgListUpdate(void)
{
	char nm[17];
	char title[24];
	const char *txt = RXG_MENU_NAME;
	uint16_t mem[CODEPLUG_RXGROUP_MEMBERS_MAX];
	int count = 0;
	uint8_t view = (uint8_t)RXG_VIEW;

	displayClearBuf();

	if ((view == RXG_VIEW_MEMBERS))
	{
		count = codeplugRxGroupGetMembers(RXG_SLOT, mem);
		codeplugRxGroupGetName(RXG_SLOT, nm);
		snprintf(title, sizeof title, RXG_MEM_TITLE_FMT, nm, (unsigned)count);
		txt = title;
	}
	else if (view == RXG_VIEW_ACTIONS)
	{
		codeplugRxGroupGetName(RXG_SLOT, title);
		txt = title;
	}
	else if (view == RXG_VIEW_PICK)
	{
		txt = (RXG_NEW != 0) ? RXG_PICK_FIRST_TITLE : RXG_PICK_TITLE;
	}
	menuDisplayTitle(txt);

	for (int i = MENU_START_ITERATION_VALUE; i <= MENU_END_ITERATION_VALUE; i++)
	{
		int mNum = menuGetMenuOffset((int)menuDataGlobal.numItems, i);

		if (mNum == MENU_OFFSET_BEFORE_FIRST_ENTRY) { continue; }
		if (mNum == MENU_OFFSET_AFTER_LAST_ENTRY)   { break; }

		nm[0] = 0;
		switch (view)
		{
			case RXG_VIEW_LIST:
				if (mNum == (int)(menuDataGlobal.numItems - 1))
				{
					txt = RXG_NEW_ROW;
				}
				else
				{
					codeplugRxGroupGetName(codeplugRxGroupNthSlot(mNum), nm);
					txt = nm;
				}
				break;
			case RXG_VIEW_ACTIONS:
				txt = (mNum == RXG_ACT_ROW_MEMBERS) ? RXG_ACT_MEMBERS : ((mNum == RXG_ACT_ROW_RENAME) ? RXG_ACT_RENAME : RXG_ACT_DELETE);
				break;
			case RXG_VIEW_MEMBERS:
				if (mNum >= count)
				{
					txt = RXG_ADD_ROW;
				}
				else
				{
					rxgContactName(mem[mNum], nm);
					txt = nm;
				}
				break;
			default:   /* RXG_VIEW_PICK */
			{
				CodeplugContact_t c;

				if (codeplugContactGetDataForNumberInType(mNum + 1, CONTACT_CALLTYPE_TG, &c) != 0)
				{
					codeplugUtilConvertBufToDisplayString(c.name, nm, 16);
				}
				txt = nm;
				break;
			}
		}
		menuDisplayEntry(i, mNum, txt, 0, THEME_ITEM_FG_MENU_ITEM, THEME_ITEM_FG_OPTIONS_VALUE, THEME_ITEM_BG);
	}

	displayRender();
}

static void rxgUpdate(void)
{
	if (RXG_VIEW == RXG_VIEW_RENAME)
	{
		rxgRenameDraw();
	}
	else if (rxgIsConfirm())
	{
		rxgConfirmUpdate();
	}
	else
	{
		rxgListUpdate();
	}
}

/* ============================ ДІЇ ============================ */
static void rxgRenameDraw(void)
{
	nameEdDraw(RXG_BUF, (RXG_NEW != 0) ? RXG_NEW_TITLE : RXG_REN_TITLE);
}

static void rxgNewStart(void)
{
	if (codeplugRxGroupCount() >= CODEPLUG_RX_GROUPLIST_MAX)
	{
		rxgResultMsg(CODEPLUG_RXGROUP_FULL);
		return;
	}
	if (codeplugContactsGetCount(CONTACT_CALLTYPE_TG) == 0)
	{
		uiNotificationShowShort(1500, RXG_MSG_NO_TG, true);   /* список без жодного контакту не існує -- спершу потрібен хоч один TG-контакт */
		return;
	}
	RXG_LISTIDX = (uint8_t)menuDataGlobal.currentItemIndex;
	RXG_NEW = 1;
	nameEdInit(RXG_BUF, NULL);
	RXG_VIEW = (char)RXG_VIEW_RENAME;
	rxgRenameDraw();
}

static void rxgRenameStart(void)
{
	char nm[17];

	RXG_NEW = 0;
	codeplugRxGroupGetName(RXG_SLOT, nm);
	nameEdInit(RXG_BUF, nm);
	RXG_VIEW = (char)RXG_VIEW_RENAME;
	rxgRenameDraw();
}

static void rxgPickOpen(void)
{
	int n = codeplugContactsGetCount(CONTACT_CALLTYPE_TG);

	if (n <= 0)
	{
		uiNotificationShowShort(1500, RXG_MSG_NO_TG, true);
		return;
	}
	RXG_MEMIDX = (uint8_t)menuDataGlobal.currentItemIndex;
	rxgSetView(RXG_VIEW_PICK, n, 0);
	rxgUpdate();
}

static void rxgRenameEvent(uiEvent_t *ev)
{
	if (ev->events & FUNCTION_EVENT)
	{
		if (ev->function == FUNC_REDRAW) { rxgRenameDraw(); }
		return;
	}
	if ((ev->events & KEY_EVENT) == 0) { return; }

	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		nameEdCommit(RXG_BUF);
		if (RXG_NEW != 0)
		{
			CodeplugRxGroupResult_t r = codeplugRxGroupNameCheck(RXG_BUF, 0);

			if (r != CODEPLUG_RXGROUP_OK) { rxgResultMsg(r); return; }   /* лишаємось у редакторі: набране не втрачено */
			nameEdClose(RXG_BUF);   /* назва лишається в [0..15] до створення списку */
			rxgPickOpen();
		}
		else
		{
			CodeplugRxGroupResult_t r;

			if (rxgReadOnly()) { return; }
			r = codeplugRxGroupRename(RXG_SLOT, RXG_BUF);
			if (r != CODEPLUG_RXGROUP_OK) { rxgResultMsg(r); return; }
			nameEdClose(RXG_BUF);
			rxgListShow(RXG_LISTIDX);
			uiNotificationShowShort(1500, RXG_MSG_RENAMED, true);
		}
	}
	else if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		nameEdClose(RXG_BUF);
		if (RXG_NEW != 0)
		{
			RXG_NEW = 0;
			rxgListShow(RXG_LISTIDX);
		}
		else
		{
			rxgActionsShow(RXG_ACT_ROW_RENAME);
		}
	}
	else
	{
		(void)nameEdHandleKey(RXG_BUF, (RXG_NEW != 0) ? RXG_NEW_TITLE : RXG_REN_TITLE, ev);
	}
}

static void rxgPickSelect(void)
{
	CodeplugContact_t c;
	uint16_t mem[CODEPLUG_RXGROUP_MEMBERS_MAX];
	int n;
	int idx = codeplugContactGetDataForNumberInType((int)menuDataGlobal.currentItemIndex + 1, CONTACT_CALLTYPE_TG, &c);
	CodeplugRxGroupResult_t r;

	if (idx == 0) { return; }
	if (rxgReadOnly()) { return; }

	if (RXG_NEW != 0)
	{
		int slot = 0;

		mem[0] = (uint16_t)idx;
		displayClearBuf();
		menuDisplayTitle(RXG_BUSY_TITLE);
		displayPrintCentered(44, RXG_BUSY_HINT, FONT_SIZE_3);
		displayRender();
		r = codeplugRxGroupCreate(RXG_BUF, mem, 1, &slot);
		if (r != CODEPLUG_RXGROUP_OK) { rxgResultMsg(r); rxgUpdate(); return; }
		rxgRamSync(0);
		RXG_NEW = 0;
		RXG_BUF[29] = (char)slot;
		RXG_LISTIDX = (uint8_t)(codeplugRxGroupCount() - 1);   /* орієнтовно: новий список -- десь у переліку; точний рядок знайдемо нижче */
		for (int o = 0; o < codeplugRxGroupCount(); o++)
		{
			if (codeplugRxGroupNthSlot(o) == slot) { RXG_LISTIDX = (uint8_t)o; break; }
		}
		rxgMembersShow(0);
		uiNotificationShowShort(1500, RXG_MSG_CREATED, true);
		return;
	}

	n = codeplugRxGroupGetMembers(RXG_SLOT, mem);
	if (n >= CODEPLUG_RXGROUP_MEMBERS_MAX) { uiNotificationShowShort(1500, RXG_MSG_MAX, true); return; }
	for (int i = 0; i < n; i++)
	{
		if (mem[i] == (uint16_t)idx) { uiNotificationShowShort(1500, RXG_MSG_DUP_MEMBER, true); return; }
	}
	mem[n] = (uint16_t)idx;
	r = codeplugRxGroupSetMembers(RXG_SLOT, mem, n + 1);
	if (r != CODEPLUG_RXGROUP_OK) { rxgResultMsg(r); rxgUpdate(); return; }
	rxgRamSync(0);
	rxgMembersShow(n);
	uiNotificationShowShort(1500, RXG_MSG_ADDED, true);
}

static void rxgDeleteOpen(bool fromLast)
{
	RXG_FROMLAST = fromLast ? 1 : 0;
	rxgSetChans((uint16_t)codeplugRxGroupCountChannels(RXG_SLOT));
	rxgSetView(RXG_VIEW_CFM_DEL, 1, 0);
	rxgUpdate();
}

static void rxgRemoveOpen(int pos)
{
	uint16_t mem[CODEPLUG_RXGROUP_MEMBERS_MAX];
	int n = codeplugRxGroupGetMembers(RXG_SLOT, mem);

	RXG_BUF[33] = (char)pos;
	RXG_MEMIDX = (uint8_t)pos;
	if (n <= 1)
	{
		rxgDeleteOpen(true);   /* останній контакт: список без контактів не існує -- питаємо про видалення списку */
		return;
	}
	rxgSetView(RXG_VIEW_CFM_RM, 1, 0);
	rxgUpdate();
}

static void rxgRemoveRun(void)
{
	uint16_t mem[CODEPLUG_RXGROUP_MEMBERS_MAX];
	int n = codeplugRxGroupGetMembers(RXG_SLOT, mem);
	int pos = (int)RXG_RMPOS;
	CodeplugRxGroupResult_t r;

	if (rxgReadOnly()) { rxgMembersShow(pos); return; }
	if ((pos >= n) || (n <= 1)) { rxgMembersShow(0); return; }
	for (int i = pos; i < (n - 1); i++) { mem[i] = mem[i + 1]; }
	r = codeplugRxGroupSetMembers(RXG_SLOT, mem, n - 1);
	rxgRamSync(0);
	rxgMembersShow(pos);
	uiNotificationShowShort(1500, (r == CODEPLUG_RXGROUP_OK) ? RXG_MSG_REMOVED : RXG_MSG_SAVE_ERR, true);
}

static void rxgDeleteRun(void)
{
	CodeplugRxGroupResult_t r;
	int slot = (int)RXG_SLOT;

	if (rxgReadOnly()) { rxgActionsShow(RXG_ACT_ROW_DELETE); return; }

	displayClearBuf();
	menuDisplayTitle(RXG_BUSY_TITLE);
	displayPrintCentered(44, RXG_BUSY_HINT, FONT_SIZE_3);
	displayRender();

	r = codeplugRxGroupDelete(slot);
	rxgRamSync(slot);   /* навіть після збою: канали, що вже скинуто, і кеші мусять відповідати кодплагу */
	if (r == CODEPLUG_RXGROUP_OK)
	{
		rxgListShow(RXG_LISTIDX);
		uiNotificationShowShort(1500, RXG_MSG_DELETED, true);
	}
	else
	{
		if (codeplugRxGroupExists(slot)) { rxgActionsShow(RXG_ACT_ROW_DELETE); }
		else { rxgListShow(RXG_LISTIDX); }
		uiNotificationShowShort(2000, RXG_MSG_SAVE_ERR, true);
	}
}

static void rxgGreen(void)
{
	int cur = (int)menuDataGlobal.currentItemIndex;

	switch (RXG_VIEW)
	{
		case RXG_VIEW_LIST:
			if (cur >= codeplugRxGroupCount())
			{
				rxgNewStart();
			}
			else
			{
				RXG_BUF[29] = (char)codeplugRxGroupNthSlot(cur);
				RXG_LISTIDX = (uint8_t)cur;
				rxgMembersShow(0);
			}
			break;
		case RXG_VIEW_ACTIONS:
			if (cur == RXG_ACT_ROW_MEMBERS) { rxgMembersShow(0); }
			else if (cur == RXG_ACT_ROW_RENAME) { rxgRenameStart(); }
			else { rxgDeleteOpen(false); }
			break;
		case RXG_VIEW_MEMBERS:
			if (cur >= (int)(menuDataGlobal.numItems - 1)) { rxgPickOpen(); }
			else { rxgRemoveOpen(cur); }
			break;
		case RXG_VIEW_PICK:
			rxgPickSelect();
			break;
		case RXG_VIEW_CFM_RM:
			rxgRemoveRun();
			break;
		case RXG_VIEW_CFM_DEL:
			rxgDeleteRun();
			break;
		default:
			break;
	}
}

static void rxgRed(menuStatus_t *ec)
{
	(void)ec;
	switch (RXG_VIEW)
	{
		case RXG_VIEW_LIST:
			menuSystemPopPreviousMenu();
			break;
		case RXG_VIEW_ACTIONS:
			rxgListShow(RXG_LISTIDX);
			break;
		case RXG_VIEW_MEMBERS:
			rxgListShow(RXG_LISTIDX);
			break;
		case RXG_VIEW_PICK:
			if (RXG_NEW != 0)
			{
				RXG_NEW = 0;   /* скасовано: список не створено, назва відкинута */
				rxgListShow(RXG_LISTIDX);
			}
			else
			{
				rxgMembersShow(RXG_MEMIDX);
			}
			break;
		case RXG_VIEW_CFM_RM:
			rxgMembersShow(RXG_RMPOS);
			break;
		case RXG_VIEW_CFM_DEL:
			if (RXG_FROMLAST != 0) { rxgMembersShow(RXG_RMPOS); }
			else { rxgActionsShow(RXG_ACT_ROW_DELETE); }
			break;
		default:
			break;
	}
}

menuStatus_t menuRxGroups(uiEvent_t *ev, bool isFirstRun)
{
	menuStatus_t exitCode = MENU_STATUS_SUCCESS;

	if (isFirstRun)
	{
		memset(RXG_BUF, 0, RXG_STATE_LEN);
		rxgListShow(0);
		return (MENU_STATUS_LIST_TYPE | MENU_STATUS_SUCCESS);
	}

	if (ev->hasEvent && (ev->events & FUNCTION_EVENT) && (ev->function == FUNC_REDRAW))
	{
		rxgUpdate();
		return exitCode;
	}

	if (RXG_VIEW == RXG_VIEW_RENAME)
	{
		if (ev->hasEvent) { rxgRenameEvent(ev); }
		return exitCode;
	}

	if (ev->hasEvent && (ev->events & KEY_EVENT))
	{
		bool down = KEYCHECK_PRESS(ev->keys, KEY_DOWN);
		bool up = KEYCHECK_PRESS(ev->keys, KEY_UP);
		int n = (int)menuDataGlobal.numItems;

		if ((down || up) && !rxgIsConfirm() && (n > 0))
		{
			menuDataGlobal.currentItemIndex = (((int)menuDataGlobal.currentItemIndex + (down ? 1 : -1)) % n + n) % n;
			rxgUpdate();
		}
		else if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
		{
			rxgRed(&exitCode);
		}
		else if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
		{
			rxgGreen();
		}
		else if (KEYCHECK_SHORTUP(ev->keys, KEY_HASH) && (RXG_VIEW == RXG_VIEW_LIST) && ((int)menuDataGlobal.currentItemIndex < codeplugRxGroupCount()))
		{
			RXG_BUF[29] = (char)codeplugRxGroupNthSlot((int)menuDataGlobal.currentItemIndex);
			RXG_LISTIDX = (uint8_t)menuDataGlobal.currentItemIndex;
			rxgActionsShow(0);
		}
	}

	return exitCode;
}

#endif /* RXGROUP_UI_ENABLED */
