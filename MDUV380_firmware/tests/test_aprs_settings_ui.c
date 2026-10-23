/*
 * test_aprs_settings_ui.c -- хостовий тест меню «Налаштування» (R17 Г1, menuAprsSettings.c): РЕАЛЬНИЙ екран + РЕАЛЬНИЙ aprs_mode.c
 * (світ заглушок -- з test_aprs_mode_state.c, який підключається цілком, але без його main). Перевіряє: групи й рядки гортаються ручкою і ↑↓, жоден
 * рядок не ширший за 26 символів, заголовок <= 16, символ змінюється й ПЕРЕЖИВАЄ вихід-вхід (ланцюг Г2 через справжній екран), стокові рядки
 * правлять aprsSettingsCopy і застосовуються при закритті, «Скинути» вимагає підтвердження, числовий редактор приймає частоту.
 */
#define main aprsModeStateMain
#include "test_aprs_mode_state.c"
#undef main
#include "../application/source/user_interface/menuAprsSettings.c"

/* ---- заглушки дисплея ---- */
static char s_rows[64][80];
static int  s_nrows, s_maxWidth;
static char s_title[80];
void displayClearBuf(void) { s_nrows = 0; s_maxWidth = 0; }
void displayRender(void) { }
void displayPrintAt(uint16_t x, uint16_t y, const char *t, ucFont_t f) { (void)x; (void)y; (void)f;
	if (s_nrows < 64) { snprintf(s_rows[s_nrows++], 80, "%s", t); }
	if ((int)strlen(t) > s_maxWidth) { s_maxWidth = (int)strlen(t); } }
void displayPrintCentered(uint16_t y, const char *t, ucFont_t f) { displayPrintAt(0, y, t, f); }
int displayPrintCore(int16_t x, int16_t y, const char *t, ucFont_t f, ucTextAlign_t a, bool inv) { (void)a; (void)inv; displayPrintAt((uint16_t)x, (uint16_t)y, t, f); return 0; }
void displayDrawRect(int16_t x, int16_t y, int16_t w, int16_t h, bool inv) { (void)x; (void)y; (void)w; (void)h; (void)inv; }
void displayFillRect(int16_t x, int16_t y, int16_t w, int16_t h, bool inv) { (void)x; (void)y; (void)w; (void)h; (void)inv; }
void displayDrawXBitmap(int16_t x, int16_t y, const uint8_t *b, int16_t w, int16_t h, bool inv) { (void)x; (void)y; (void)b; (void)w; (void)h; (void)inv; }
/* стокові допоміжні, що в прошивці живуть у uiUtilities.c / codeplug.c / aprs.c / aprs_rx.c */
const int CODEPLUG_MIN_PER_CHANNEL_POWER = 1;
const char *getPowerLevel(uint8_t level) { static char b[8]; snprintf(b, sizeof(b), "%u", (unsigned)(level + 1U)); return b; }
const char *getPowerLevelUnit(uint8_t level) { (void)level; return "W"; }
void menuDisplayTitle(const char *t) { snprintf(s_title, sizeof(s_title), "%s", t); }
/* R19 Е1: списки -- стокові пункти меню. menuAprsListDraw() справжній живе в menuAprsStations.c (його перевіряє test_aprs_stations_ui); тут -- те саме вікно з 6 рядків */
static int s_entryMax, s_entryRows;
void menuAprsListDraw(int count, int sel, aprsListItemFn_t fn)
{
	char buf[APRS_LIST_COLS + 8];
	int top = sel - 2;

	if (top > (count - APRS_LIST_ROWS)) { top = count - APRS_LIST_ROWS; }
	if (top < 0) { top = 0; }
	s_entryRows = 0;
	for (int k = 0; (k < APRS_LIST_ROWS) && ((top + k) < count); k++)
	{
		int opt = 0; buf[0] = 0;
		fn(top + k, buf, sizeof(buf), &opt);
		buf[APRS_LIST_COLS] = 0;
		if (s_nrows < 64) { snprintf(s_rows[s_nrows++], 80, "%s%s", ((top + k) == sel) ? ">" : " ", buf); }   /* '>' лише в тесті -- щоб було видно, який рядок виділено */
		if ((int)strlen(buf) > s_entryMax) { s_entryMax = (int)strlen(buf); }
		s_entryRows++;
	}
}

static void key(char k, uint8_t ev)
{
	uiEvent_t e; memset(&e, 0, sizeof(e));
	e.hasEvent = true; e.events = KEY_EVENT; e.keys.key = k; e.keys.event = ev;
	(void)menuAprsSettingsTick(&e);
}
static void click(char k) { key(k, KEY_MOD_PRESS); key(k, KEY_MOD_UP); }

static bool rowHas(const char *needle)
{
	for (int i = 0; i < s_nrows; i++) { if (strstr(s_rows[i], needle) != NULL) { return true; } }
	return false;
}

static void checkWidths(const char *what)
{
	CHECK(s_nrows > 0, "%s: нічого не намальовано", what);
	CHECK(s_maxWidth <= 26, "%s: рядок шириною %d > 26", what, s_maxWidth);
	CHECK(strlen(s_title) <= 16, "%s: заголовок «%s» > 16", what, s_title);
}

static void testWalk(void)
{
	resetWorld();
	CHECK(menuAprsSettingsEnter(), "налаштування відкрились");
	CHECK(aprsModeCfgSessionActive(), "сесія активна");
	checkWidths("список груп");
	CHECK(rowHas(APRSM_G_STATION) && rowHas(APRSM_G_RESET), "у списку є «Моя станція» і «Скинути налаштування»");
	/* кожна група: відкрити, пройти всі рядки вниз і вправо/вліво (ручка), перевірити ширину */
	for (int g = 0; g < AS_G_RESET; g++)
	{
		click(KEY_RED);   /* рівень груп (або вихід -- повертаємо знову нижче) */
		if (!aprsModeCfgSessionActive()) { CHECK(menuAprsSettingsEnter(), "повторно відкрито"); }
		aprsModeUi()->msg.view = 0; aprsModeUi()->scroll = (uint8_t)g;
		click(KEY_GREEN);
		CHECK(AS_LEVEL(aprsModeUi()) == AS_LEVEL_ROWS, "група %d відкрилась", g);
		checkWidths("рядки групи");
		for (int r = 0; r < asGroups[g].n + 1; r++)
		{
			for (int d = 0; d < 6; d++) { click(KEY_RIGHT); checkWidths("рядок, ручка вправо"); }
			for (int d = 0; d < 12; d++) { click(KEY_LEFT); checkWidths("рядок, ручка вліво"); }
			click(KEY_DOWN);
			checkWidths("рядок, вниз");
		}
		CHECK(aprsModeUi()->sel < asGroups[g].n, "вибраний рядок у межах групи %d", g);
	}
	aprsModeMsgSessionClose();
}

static void testNavigation(void)
{
	aprsModeUi_t *u;

	resetWorld();
	CHECK(menuAprsSettingsEnter(), "налаштування");
	u = aprsModeUi();
	CHECK(AS_LEVEL(u) == AS_LEVEL_GROUPS && u->scroll == 0, "починаємо зі списку груп, «Моя станція»");
	click(KEY_RIGHT); CHECK(u->scroll == 1, "ручка вправо -- наступна група");
	click(KEY_DOWN);  CHECK(u->scroll == 2, "вниз -- наступна група");
	click(KEY_LEFT);  CHECK(u->scroll == 1, "ручка вліво -- попередня група");
	click(KEY_UP);    CHECK(u->scroll == 0, "вгору -- попередня група");
	click(KEY_UP);    CHECK(u->scroll == AS_G_RESET, "вгору з першої -- по колу на «Скинути»");
	click(KEY_DOWN);  CHECK(u->scroll == 0, "вниз з останньої -- по колу на першу");
	click(KEY_GREEN); CHECK(AS_LEVEL(u) == AS_LEVEL_ROWS && u->sel == 0, "GREEN -- рядки групи");
	click(KEY_DOWN);  CHECK(u->sel == 1, "вниз -- наступний рядок");
	click(KEY_UP);    click(KEY_UP);
	CHECK(u->sel == asGroups[0].n - 1, "вгору з першого -- по колу на останній");
	click(KEY_RED);   CHECK(AS_LEVEL(u) == AS_LEVEL_GROUPS && aprsModeCfgSessionActive(), "RED з рядків -- назад до груп");
	click(KEY_RED);   CHECK(aprsModeCfgSessionActive() == false, "RED з груп -- вихід, сесію закрито");
}

static void selectRow(int group, int row)
{
	aprsModeUi_t *u = aprsModeUi();

	AS_LEVEL(u) = AS_LEVEL_GROUPS; u->scroll = (uint8_t)group;
	click(KEY_GREEN);
	u->sel = (uint8_t)row;
}

/* Г2: символ через справжній екран -- ручка на пункті «Символ», вихід, повторний вхід, "перезавантаження" (нова сесія) */
static void testSymbol(void)
{
	uint8_t t0, i0;

	resetWorld();
	CHECK(menuAprsSettingsEnter(), "налаштування");
	selectRow(AS_G_STATION, 2);
	CHECK(asRowId(aprsModeUi()) == APRSM_F_SYMBOL, "третій рядок «Моєї станції» -- «Символ»");
	t0 = aprsModeEff()->iconTable; i0 = aprsModeEff()->iconIndex;
	click(KEY_RIGHT);
	CHECK((aprsModeEff()->iconTable != t0) || (aprsModeEff()->iconIndex != i0), "ручка змінила символ в ефективних налаштуваннях");
	CHECK((aprsModeCfg()->ov & APRSM_OV_ICON) == 0, "APRS-unify: чернетку складено в слот (ov-біт знято)");
	t0 = aprsModeEff()->iconTable; i0 = aprsModeEff()->iconIndex;
	s_now += 3000; tickMs(0);   /* пауза в редагуванні */
	(void)menuAprsSettingsTick(&(uiEvent_t){ 0 });
	CHECK(s_flashWrites >= 1 && s_flashValid, "блок режиму записано у флеш після паузи");
	CHECK(s_apcWrites == 1 && s_apc.iconTable == t0 && s_apc.iconIndex == i0, "символ записано в слот конфігу APRS після паузи (%d)", s_apcWrites);
	aprsModeMsgSessionClose();
	/* повторний вхід у меню */
	CHECK(menuAprsSettingsEnter(), "повторний вхід");
	CHECK(aprsModeEff()->iconTable == t0 && aprsModeEff()->iconIndex == i0, "символ пережив вихід-вхід");
	aprsModeMsgSessionClose();
	/* «перезавантаження»: кільце знову зарезервоване, стан модуля скинуто, у флеші лишився блок */
	callReplayBorrowReset(); aprsMsgBgInit();
	CHECK(aprsModeEnter(), "вхід у «Слухати» після перезавантаження");
	CHECK(aprsModeEff()->iconTable == t0 && aprsModeEff()->iconIndex == i0, "символ видно в «Слухати APRS» (і значить -- в ефірі)");
	aprsModeExit();
}

static void testStock(void)
{
	resetWorld();
	memset(&s_stockSettings, 0, sizeof(s_stockSettings)); s_stockSettings.mode = APRS_BEACONING_MODE_OFF; s_stockSettings.initialInterval = APRS_BEACON_INITIAL_INTERVAL_DEFAULT; s_stockSettings.smart.slowRate = APRS_SMART_BEACON_SLOW_RATE_DEFAULT; s_stockSetCalls = 0;
	CHECK(menuAprsSettingsEnter(), "налаштування");
	selectRow(AS_G_BEACON, 0);
	CHECK(asRowId(aprsModeUi()) == AS_S_MODE, "«Маяк» -> «Режим»");
	click(KEY_RIGHT); click(KEY_RIGHT);
	CHECK(aprsSettingsCopy.mode == APRS_BEACONING_MODE_PTT, "ручка двічі: режим PTT (у копії)");
	CHECK(s_stockSetCalls == 0, "до виходу стокове не застосовано");
	click(KEY_DOWN); click(KEY_RIGHT);   /* потужність */
	CHECK(aprsSettingsCopy.power == 1, "потужність +1");
	click(KEY_DOWN); click(KEY_RIGHT);   /* інтервал */
	CHECK(aprsSettingsCopy.initialInterval == APRS_BEACON_INITIAL_INTERVAL_DEFAULT + 1, "інтервал +1");
	click(KEY_DOWN); click(KEY_DOWN); click(KEY_DOWN);   /* стиснення (після шляхів) */
	CHECK(asRowId(aprsModeUi()) == AS_S_COMPR, "рядок «Стиснення»");
	click(KEY_LEFT);
	CHECK((aprsSettingsCopy.state & APRS_BEACONING_STATE_COMPRESSED_FORMAT) == 0, "ручка вліво -- стиснення вимк");
	click(KEY_GREEN);
	CHECK((aprsSettingsCopy.state & APRS_BEACONING_STATE_COMPRESSED_FORMAT) != 0, "GREEN -- перемикач, стиснення знов увімк");
	/* R21 З4: «QSY інфо» -- наступний рядок після «Стиснення»; типово увімкнено, зберігається в блоці режиму (qsyOff) */
	click(KEY_DOWN);
	CHECK(asRowId(aprsModeUi()) == AS_S_QSY, "рядок «QSY інфо»");
	CHECK((aprsModeEff()->flags & APRSM_RAW_FLAG_QSY) != 0U, "QSY увімкнено -- прапорець у слоті");
	click(KEY_LEFT);
	CHECK((aprsModeEff()->flags & APRSM_RAW_FLAG_QSY) == 0U, "ручка вліво -- QSY вимкнено");
	click(KEY_GREEN);
	CHECK((aprsModeEff()->flags & APRSM_RAW_FLAG_QSY) != 0U, "GREEN -- перемикач, QSY знов увімкнено");
	click(KEY_LEFT);
	CHECK((aprsModeEff()->flags & APRSM_RAW_FLAG_QSY) == 0U, "QSY вимкнено перед скиданням");
	click(KEY_UP);
	selectRow(AS_G_SMART, 0);
	click(KEY_RIGHT);
	CHECK(aprsSettingsCopy.smart.slowRate == APRS_SMART_BEACON_SLOW_RATE_DEFAULT + 1, "повільний +1");
	/* R21 З5: цифри 0..6 -- пресети розумного маяка, як у стоковому екрані */
	click('1');
	CHECK((aprsSettingsCopy.smart.slowRate == 30U) && (aprsSettingsCopy.smart.fastRate == 180U) && (aprsSettingsCopy.smart.highSpeed == 90U), "цифра 1 -- пресет «Car»");
	click('0');
	CHECK((aprsSettingsCopy.smart.slowRate == APRS_SMART_BEACON_SLOW_RATE_DEFAULT) && (aprsSettingsCopy.smart.turnTime == APRS_SMART_BEACON_TURN_TIME_DEFAULT), "цифра 0 -- пресет «Default»");
	click('9');
	CHECK(aprsSettingsCopy.smart.slowRate == APRS_SMART_BEACON_SLOW_RATE_DEFAULT, "цифра 9 -- нема пресета, нічого не змінилось");
	selectRow(AS_G_BEACON, 0);
	click('1');
	CHECK(aprsSettingsCopy.smart.slowRate == APRS_SMART_BEACON_SLOW_RATE_DEFAULT, "цифри поза групою «Розумний маяк» пресетів не вмикають");
	selectRow(AS_G_SMART, 0);
	click(KEY_RED); click(KEY_RED);   /* вихід */
	CHECK(s_stockSetCalls == 1 && s_stockSettings.mode == APRS_BEACONING_MODE_PTT && s_stockSettings.power == 1, "при виході стокові параметри застосовано (%d)", s_stockSetCalls);
}

static void testReset(void)
{
	aprsModeUi_t *u;

	resetWorld();
	CHECK(menuAprsSettingsEnter(), "налаштування");
	u = aprsModeUi();
	selectRow(AS_G_STATION, 1);
	click(KEY_RIGHT);   /* SSID */
	CHECK(aprsModeEff()->ssid == 8U, "SSID змінено (слот 7 -> 8)");
	AS_LEVEL(u) = AS_LEVEL_GROUPS; u->scroll = AS_G_RESET;
	click(KEY_GREEN);
	CHECK(u->resetArmed == 1 && aprsModeEff()->ssid == 8U, "перше GREEN -- лише запит підтвердження");
	asDraw(); CHECK(rowHas(APRSM_G_RESET_ASK), "на екрані запит «GREEN ще раз»");
	click(KEY_DOWN);
	CHECK(u->resetArmed == 0, "рух по списку скасовує підтвердження");
	u->scroll = AS_G_RESET; click(KEY_GREEN); click(KEY_GREEN);
	CHECK(aprsModeEff()->ssid == 8U && aprsModeCfg()->ov == APRSM_OV_MIGRATED && u->resetArmed == 0, "друге GREEN -- скинуто чернетку й шумодав; станційні поля у кодплузі не чіпає");
	aprsModeMsgSessionClose();
}

static void typeKeys(const char *s)
{
	for (; *s; s++) { click(*s == '.' ? KEY_STAR : *s); }
}

static void testEditor(void)
{
	resetWorld();
	CHECK(menuAprsSettingsEnter(), "налаштування");
	selectRow(AS_G_RX, 0);
	CHECK(asRowId(aprsModeUi()) == APRSM_F_FREQ, "«Приймач» -> «Частота»");
	click(KEY_GREEN);
	CHECK(aprsModeUi()->edit.active, "GREEN відкрив редактор частоти");
	asDraw(); checkWidths("редактор частоти");
	typeKeys("144.5");
	click(KEY_GREEN);
	CHECK(aprsModeUi()->edit.active == 0, "GREEN прийняв значення");
	CHECK(aprsModeEff()->freq == 14450000UL, "частота 144.5 діє (%lu)", (unsigned long)aprsModeEff()->freq);
	CHECK(s_tuneCalls == 0, "рація не перебудовувалась (радіо не чіпали)");
	/* помилкове значення не приймається */
	click(KEY_GREEN);
	typeKeys("9");
	click(KEY_GREEN);
	CHECK(aprsModeUi()->edit.active && aprsModeUi()->edit.err, "хибна частота -- редактор лишається з помилкою");
	click(KEY_RED);
	CHECK(aprsModeUi()->edit.active == 0, "RED закрив редактор");
	/* під час передачі частоту не міняємо і кажемо про це */
	aprsTxProgress = APRS_TX_IN_PROGRESS;
	s_notify = 0;
	click(KEY_RIGHT);
	CHECK(s_notify == 1 && aprsModeEff()->freq == 14450000UL, "ручка під час передачі: частота та сама, сповіщення «Йде передача»");
	aprsTxProgress = APRS_TX_IDLE;
	aprsModeMsgSessionClose();
}

/* APRS-unify: позивний -- ім'я рації; прапорці слота в меню; назва слота в шапці; запис у кодплуг лише коли байти змінилися */
static int rowIndexOf(const uint8_t *rows, int n, int id)
{
	for (int i = 0; i < n; i++) { if (rows[i] == id) { return i; } }
	return -1;
}

static void testUnify(void)
{
	uint8_t fl;
	int ib, ip;

	resetWorld();
	memset(s_apc.name, 0xFF, sizeof(s_apc.name)); memcpy(s_apc.name, "MYSLOT", 6);
	CHECK(menuAprsSettingsEnter(), "налаштування");
	asDraw();
	CHECK(strcmp(s_title, "APRS:MYSLOT") == 0, "у шапці -- назва слота (%s)", s_title);

	/* позивний */
	CHECK(aprsModeSetCall("r2abc") && strcmp(aprsModeEff()->call, "R2ABC") == 0, "позивний r2abc -> R2ABC в ефективних");
	CHECK(aprsModeSetCall("") == false && aprsModeSetCall("--") == false, "порожній/недопустимий позивний відхилено");
	CHECK(strcmp(s_radioName, "UW5ELK") == 0 && s_nameWrites == 0, "до паузи ім'я рації в кодплуг не писали");
	s_now += 3000; tickMs(0);
	(void)menuAprsSettingsTick(&(uiEvent_t){ 0 });
	CHECK(strcmp(s_radioName, "R2ABC") == 0 && s_nameWrites == 1, "після паузи ім'я рації = позивний (%s, записів %d)", s_radioName, s_nameWrites);
	CHECK(s_apcWrites == 0, "слот не чіпали, бо байти не змінилися");
	(void)aprsModeSetCall("R2ABC");
	s_now += 3000; tickMs(0);
	(void)menuAprsSettingsTick(&(uiEvent_t){ 0 });
	CHECK(s_nameWrites == 1, "той самий позивник -- без нового запису");

	/* прапорці слота: 300 бод, «тихо» (група «Маяк»), «використовувати позицію» (група «Позиція») */
	ib = rowIndexOf(asRowsBeacon, AS_N(asRowsBeacon), AS_S_BAUD);
	CHECK(ib >= 0, "у групі «Маяк» є рядок «Бод»");
	selectRow(AS_G_BEACON, ib);
	click(KEY_RIGHT);
	CHECK((aprsModeEff()->flags & APRSM_RAW_FLAG_300_BAUDS) != 0U, "300 бод увімкнено");
	asDraw(); CHECK(rowHas(APRSM_L_BAUD ":" APRSM_V_BAUD1), "на екрані «Бод:300»");
	ib = rowIndexOf(asRowsBeacon, AS_N(asRowsBeacon), AS_S_SILENT);
	selectRow(AS_G_BEACON, ib);
	click(KEY_GREEN);
	CHECK((aprsModeEff()->flags & APRSM_RAW_FLAG_SILENT) != 0U, "«Тихо» увімкнено");
	ip = rowIndexOf(asRowsPos, AS_N(asRowsPos), AS_S_USEPOS);
	selectRow(AS_G_POS, ip);
	click(KEY_GREEN);
	CHECK((aprsModeEff()->flags & APRSM_RAW_FLAG_USE_POSITION) != 0U, "«Поз.слота» увімкнено");
	s_now += 3000; tickMs(0);
	(void)menuAprsSettingsTick(&(uiEvent_t){ 0 });
	fl = s_apc.flags;
	CHECK(s_apcWrites == 1 && (fl & (APRSM_RAW_FLAG_300_BAUDS | APRSM_RAW_FLAG_SILENT | APRSM_RAW_FLAG_USE_POSITION)) == (APRSM_RAW_FLAG_300_BAUDS | APRSM_RAW_FLAG_SILENT | APRSM_RAW_FLAG_USE_POSITION) &&
			(fl & APRSM_RAW_FLAG_QSY) != 0U, "три прапорці в слоті одним записом (%d, %02X); QSY лишився", s_apcWrites, fl);
	/* стокові рядки більше не містять окремого «Період» */
	CHECK(rowIndexOf(asRowsBeacon, AS_N(asRowsBeacon), AS_S_BINT) >= 0, "інтервал -- стоковий рядок «Інтервал»");
	aprsModeMsgSessionClose();
	CHECK(s_bflashValid && s_bflashWrites >= 1, "при закритті записано блок налаштувань бікона");
}

int main(void)
{
	testWalk();
	testNavigation();
	testSymbol();
	testStock();
	testReset();
	testEditor();
	testUnify();
	if (s_fail != 0)
	{
		printf("test_aprs_settings_ui: ПРОВАЛІВ %d з %d перевірок\n", s_fail, s_checks);
		return 1;
	}
	printf("test_aprs_settings_ui: усі %d перевірок пройшли\n", s_checks);
	return 0;
}
