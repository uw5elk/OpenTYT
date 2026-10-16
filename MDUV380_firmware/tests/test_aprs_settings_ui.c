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
const uint16_t initialIntervalsInSecs[APRS_BEACON_INITIAL_INTERVAL_MAX + 1] = { 12U, 30U, 60U, 120U, 180U, 300U, 600U, 1200U, 1800U, 3600U };
const char *getPowerLevel(uint8_t level) { static char b[8]; snprintf(b, sizeof(b), "%u", (unsigned)(level + 1U)); return b; }
const char *getPowerLevelUnit(uint8_t level) { (void)level; return "W"; }
static uint8_t s_bcnWin;
uint8_t aprsRxBcnWinMode(void) { return s_bcnWin; }
void aprsRxBcnWinSetMode(uint8_t m) { s_bcnWin = m; }
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
	CHECK(aprsModeCfg()->ov & APRSM_OV_ICON, "біт оверрайду символу виставлено");
	t0 = aprsModeEff()->iconTable; i0 = aprsModeEff()->iconIndex;
	s_now += 3000; tickMs(0);   /* пауза в редагуванні */
	(void)menuAprsSettingsTick(&(uiEvent_t){ 0 });
	CHECK(s_flashWrites >= 1 && s_flashValid, "символ записано у флеш після паузи");
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
	CHECK(aprsModeCfg()->qsyOff == 0U, "типово QSY увімкнено");
	click(KEY_LEFT);
	CHECK(aprsModeCfg()->qsyOff == 1U, "ручка вліво -- QSY вимкнено");
	click(KEY_GREEN);
	CHECK(aprsModeCfg()->qsyOff == 0U, "GREEN -- перемикач, QSY знов увімкнено");
	click(KEY_LEFT);
	CHECK(aprsModeCfg()->qsyOff == 1U, "QSY вимкнено перед скиданням");
	click(KEY_UP);
	selectRow(AS_G_SMART, 0);
	click(KEY_RIGHT);
	CHECK(aprsSettingsCopy.smart.slowRate == APRS_SMART_BEACON_SLOW_RATE_DEFAULT + 1, "повільний +1");
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
	CHECK(aprsModeCfg()->ov & APRSM_OV_SSID, "SSID змінено");
	AS_LEVEL(u) = AS_LEVEL_GROUPS; u->scroll = AS_G_RESET;
	click(KEY_GREEN);
	CHECK(u->resetArmed == 1 && (aprsModeCfg()->ov & APRSM_OV_SSID), "перше GREEN -- лише запит підтвердження");
	asDraw(); CHECK(rowHas(APRSM_G_RESET_ASK), "на екрані запит «GREEN ще раз»");
	click(KEY_DOWN);
	CHECK(u->resetArmed == 0, "рух по списку скасовує підтвердження");
	u->scroll = AS_G_RESET; click(KEY_GREEN); click(KEY_GREEN);
	CHECK((aprsModeCfg()->ov & APRSM_OV_SSID) == 0 && u->resetArmed == 0, "друге GREEN -- налаштування скинуто");
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

int main(void)
{
	testWalk();
	testNavigation();
	testSymbol();
	testStock();
	testReset();
	testEditor();
	if (s_fail != 0)
	{
		printf("test_aprs_settings_ui: ПРОВАЛІВ %d з %d перевірок\n", s_fail, s_checks);
		return 1;
	}
	printf("test_aprs_settings_ui: усі %d перевірок пройшли\n", s_checks);
	return 0;
}
