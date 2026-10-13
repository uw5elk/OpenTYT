/*
 * R8-fix: хостовий тест екрана «APRS станції» (menuAprsStations.c) -- справжній файл екрана,
 * дисплей і приймач -- заглушки. Перевіряє: усі сторінки (список/картка/діагностика/діагностика 2) на
 * ПОРОЖНІЙ і ЗАПОВНЕНІЙ базі завершуються (немає нескінченних циклів: сторожовий alarm), жоден
 * рядок не ширший за 26 символів, заголовок <= 16, навігація не виходить за межі (по колу), `0`
 * скидає лічильники, RED з картки повертає у список, RED зі списку закриває екран.
 * Збирається: див. tests/run_tests.sh (SRCS/XFLAGS, конфігурація UA).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include "../application/source/user_interface/menuAprsStations.c"

static int failures;
#define CHECK(c, ...) do { if (!(c)) { failures++; printf("ПРОВАЛ %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

/* ---- заглушки дисплея/годинника ---- */
static uint32_t s_now = 100000;
uint32_t ticksGetMillis(void) { return s_now; }
static char s_rows[64][80];
static int  s_nrows, s_renders, s_maxWidth;
static char s_title[80];
void displayClearBuf(void) { s_nrows = 0; }
void displayRender(void) { s_renders++; }
void displayPrintAt(uint16_t x, uint16_t y, const char *t, ucFont_t f) { (void)x; (void)y; (void)f;
	if (s_nrows < 64) { snprintf(s_rows[s_nrows++], 80, "%s", t); }
	if ((int)strlen(t) > s_maxWidth) { s_maxWidth = (int)strlen(t); } }
void displayPrintCentered(uint16_t y, const char *t, ucFont_t f) { displayPrintAt(0, y, t, f); }
void menuDisplayTitle(const char *t) { snprintf(s_title, sizeof(s_title), "%s", t); }

/* ---- заглушки приймача ---- */
static aprsRxUi_t s_ui;
static aprsRxDb_t s_db;
static aprsRxStats_t s_st;
aprsRxUi_t *aprsRxUi(void) { return &s_ui; }
const aprsRxDb_t *aprsRxDb(void) { return &s_db; }
const aprsRxStats_t *aprsRxStats(void) { return &s_st; }
bool aprsRxStationGeo(const aprsStation_t *st, uint32_t *d, uint16_t *b) { if (!(st->flags & APRS_ST_HASPOS)) return false; *d = 3200; *b = 45; return true; }
void aprsRxFormatGeo(char *buf, size_t n, uint32_t d, uint16_t b) { snprintf(buf, n, "%lu.%luкм %s", (unsigned long)(d / 1000), (unsigned long)((d % 1000) / 100), aprsBearingName(b)); }
uint32_t aprsRxAgeSec(const aprsStation_t *st) { return (s_now - st->lastMs) / 1000U; }
/* R11: «Відповісти» з картки станції -- відкриває набір повідомлення; тут лише фіксуємо виклик */
static int s_replyCalls = 0;
static char s_replyCall[16];
/* R11-fix2: екран DIAG2 показує лічильники фонової черги повідомлень/ACK (постійний блок aprsModeMsgBox()) */
static aprsMsgBox_t s_box;
aprsMsgBox_t *aprsModeMsgBox(void) { return &s_box; }
unsigned aprsMsgQueueLen(const aprsMsgBox_t *b) { (void)b; return 4U; }
bool menuAprsModeReplyTo(const char *call) { s_replyCalls++; snprintf(s_replyCall, sizeof(s_replyCall), "%s", call); return true; }
void aprsRxClear(void) { memset(&s_st, 0, sizeof(s_st)); aprsDbInit(&s_db); }
/* R16: історія прийому (блок резерву «Переслухати»), вікно маяка станції і сповіщення -- заглушки; логіка історії -- справжня (aprs_rx_parse.c) */
static aprsHist_t s_hist;
aprsHist_t *aprsModeHist(void) { return &s_hist; }
static int s_showAgain = 0, s_showStation = 0, s_notes = 0;
static char s_lastNote[80], s_lastShown[APRS_CALL_LEN];
static const aprsStation_t *byCall(const char *c) { for (int i = 0; i < APRS_STATIONS_MAX; i++) { if (s_db.st[i].call[0] && !strcmp(s_db.st[i].call, c)) { return &s_db.st[i]; } } return NULL; }
bool aprsRxBeaconAvail(const char *call)
{
	int i;
	if (call == NULL) { return aprsHistBeaconLast(&s_hist, &i) != NULL; }
	return (byCall(call) != NULL) && (aprsHistBeaconOf(&s_hist, &s_db, byCall(call)) != NULL);
}
void aprsRxWindowShowAgain(void) { s_showAgain++; }
bool aprsRxWindowShowStation(const char *call)
{
	if (!aprsRxBeaconAvail(call)) { return false; }
	s_showStation++; snprintf(s_lastShown, sizeof(s_lastShown), "%s", call);
	return true;
}
void uiNotificationShow(uiNotificationType_t type, uiNotificationID_t id, uint32_t ms, const char *msg, bool imm) { (void)type; (void)id; (void)ms; (void)imm; s_notes++; snprintf(s_lastNote, sizeof(s_lastNote), "%s", msg ? msg : ""); }
/* R16: час прийому в журналі (у прошивці -- uiSmsTimeStr() з місцевим часом) */
int uiSmsTimeStr(uint32_t t, int mode, char *out, int outsz) { (void)mode; if (t == 0U) { return 0; } return snprintf(out, (size_t)outsz, "%02u:%02u", (unsigned)((t / 3600U) % 24U), (unsigned)((t / 60U) % 60U)); }
static int s_tri = 0;
void displayFillTriangle(int16_t x0, int16_t y0, int16_t x1, int16_t y1, int16_t x2, int16_t y2, bool c) { (void)x0; (void)y0; (void)x1; (void)y1; (void)x2; (void)y2; (void)c; s_tri++; }

static void key(char k, uint8_t ev)
{
	uiEvent_t e; memset(&e, 0, sizeof(e));
	e.hasEvent = true; e.events = KEY_EVENT; e.keys.key = k; e.keys.event = ev;
	menuAprsStationsTick(&e);
}
static void click(char k) { key(k, KEY_MOD_PRESS); key(k, KEY_MOD_UP); }

static void checkScreen(const char *what)
{
	CHECK(s_nrows > 0, "%s: нічого не намальовано", what);
	if (s_maxWidth > 26) { for (int i = 0; i < s_nrows; i++) { if (strlen(s_rows[i]) > 26) { printf("   [%s]\n", s_rows[i]); } } }
	CHECK(s_maxWidth <= 26, "%s: рядок шириною %d > 26", what, s_maxWidth);
	if (s_maxWidth > 26) { for (int i = 0; i < s_nrows; i++) { if (strlen(s_rows[i]) > 26) { printf("   [%s]\n", s_rows[i]); } } }
	CHECK(strlen(s_title) <= 16, "%s: заголовок «%s» > 16", what, s_title);
	s_maxWidth = 0;
}

static void fill(int n)
{
	aprsDbInit(&s_db);
	for (int i = 0; i < n; i++)
	{
		aprsStation_t *s = &s_db.st[i];
		snprintf(s->call, sizeof(s->call), "UW5EL%c-%d", 'A' + (i % 26), i % 16);
		s->type = (uint8_t)(i % 4); s->flags = (i & 1) ? APRS_ST_HASPOS : 0; s->count = (uint16_t)(i * 1000 + 1);
		s->latU = 50000000; s->lonU = 30000000; s->lastMs = s_now - (uint32_t)i * 400000U;
		snprintf(s->path, sizeof(s->path), "WIDE1-1,WIDE2-1*");
		memset(s->text, 'Ж', sizeof(s->text) - 1); s->text[sizeof(s->text) - 1] = 0;   /* найдовший текст */
	}
}

static void walkAll(const char *tag)
{
	char w[64];
	s_maxWidth = 0;
	menuAprsStationsEnter();
	snprintf(w, sizeof(w), "%s: список", tag); checkScreen(w);
	for (int i = 0; i < 40; i++) { click(KEY_DOWN); }            /* по колу, без виходу за межі */
	for (int i = 0; i < 40; i++) { click(KEY_UP); }
	checkScreen("прокрутка");
	click(KEY_GREEN);                                            /* картка (якщо є станції) */
	for (int i = 0; i < 20; i++) { click(KEY_DOWN); }
	for (int i = 0; i < 20; i++) { click(KEY_UP); }
	snprintf(w, sizeof(w), "%s: картка", tag); checkScreen(w);
	if (s_ui.view == APRS_RX_VIEW_CARD)
	{
		int before = s_replyCalls;
		click(KEY_GREEN);
		CHECK(s_replyCalls == before + 1 && s_replyCall[0] != 0, "GREEN на картці -- «Відповісти» зі станцією");
	}
	click(KEY_RED);                                              /* картка -> список */
	if (s_ui.on == 0) { menuAprsStationsEnter(); }                /* порожня база: картки нема, RED зі списку закрив екран -- це правильно */
	CHECK(s_ui.on == 1 && s_ui.view == APRS_RX_VIEW_LIST, "після RED з картки -- список");
	{ uint8_t keepState = s_st.state, keepWhy = s_st.why; memset(&s_st, 0, sizeof(s_st)); s_st.state = keepState; s_st.why = keepWhy;
	  s_st.starts = s_st.startFails = 999; s_st.blocks = 99999; s_st.overflows = s_st.gateDrops = 999; }   /* реалістичні межі сторінки R8 */
	click(KEY_HASH); CHECK(s_ui.view == APRS_RX_VIEW_DIAG, "# -> DIAG"); snprintf(w, sizeof(w), "%s: діагностика", tag); checkScreen(w);
	s_box.stats.rx = s_box.stats.ackFormed = s_box.stats.ackSent = s_box.stats.ackLost = 0xFFFF; snprintf(s_box.lastAckText, sizeof(s_box.lastAckText), ":WWWWWWWWW :ackWWWWW");   /* крайні значення лічильників ACK */
	memset(&s_st.stops, 0xFF, sizeof(s_st.stops)); s_st.wsTimeouts = s_st.syncStops = s_st.abortTimeouts = 0xFFFF; s_st.starts = s_st.startFails = 0xFFFFFFFFU;   /* крайні значення DIAG2 */
	click(KEY_HASH); CHECK(s_ui.view == APRS_RX_VIEW_DIAG2, "# -> DIAG2"); snprintf(w, sizeof(w), "%s: діагностика 2", tag); checkScreen(w);
	click(KEY_HASH); CHECK(s_ui.view == APRS_RX_VIEW_DIAG, "# -> назад у DIAG");
	click(KEY_HASH); CHECK(s_ui.view == APRS_RX_VIEW_DIAG2, "# -> DIAG2");
	s_st.wsTimeouts = 7; s_st.syncStops = 3; s_st.abortTimeouts = 2; s_st.starts = 9;
	click(KEY_0); CHECK(s_st.wsTimeouts == 0 && s_st.syncStops == 0 && s_st.abortTimeouts == 0, "0 скидає лічильники");
	click(KEY_RED); CHECK(s_ui.view == APRS_RX_VIEW_LIST && s_ui.on == 1, "RED з діагностики -> список");
	uiEvent_t e; memset(&e, 0, sizeof(e)); e.hasEvent = true; e.events = KEY_EVENT; e.keys.key = KEY_RED; e.keys.event = KEY_MOD_UP;
	CHECK(menuAprsStationsTick(&e) == false && s_ui.on == 0, "RED зі списку закриває екран");
}

/* R16: додати запис у журнал так, як це робить aprsJrnAdd() (кадр уже у вигляді TNC-2) */
static void jrnPush(const char *text, uint32_t secs)
{
	aprsJrnEntry_t *e = &s_hist.jrn[s_hist.jrnHead];

	snprintf(e->text, sizeof(e->text), "%s", text);
	e->rxSecs = secs;
	s_hist.jrnRssi[s_hist.jrnHead] = (int8_t)(-60 - (int)(secs % 30U));
	s_hist.jrnHead = (uint8_t)((s_hist.jrnHead + 1U) % APRS_JRN_SLOTS);
	if (s_hist.jrnCount < APRS_JRN_SLOTS) { s_hist.jrnCount++; }
}

static void keyUp(char k)
{
	uiEvent_t e; memset(&e, 0, sizeof(e)); e.hasEvent = true; e.events = KEY_EVENT; e.keys.key = k; e.keys.event = KEY_MOD_UP;
	menuAprsStationsTick(&e);
}

/* R16: «Пакети» (з меню і з картки), '*' на картці -- маяк цієї станції, «Останній маяк» */
static void testPacketScreens(void)
{
	char w[64];
	int tri0;

	fill(3);
	aprsHistClear(&s_hist);
	/* з меню «APRS»: журнал порожній -> «Пакетів ще не було», RED виходить */
	menuAprsPacketEnter();
	CHECK(s_ui.on == 1 && s_ui.view == APRS_RX_VIEW_PKTLIST && s_ui.cardCall[0] == 0, "пункт «Пакети» відкриває список журналу");
	checkScreen("журнал: порожньо");
	{ int found = 0; for (int i = 0; i < s_nrows; i++) { if (!strcmp(s_rows[i], APRSRX_PKT_EMPTY)) { found = 1; } } CHECK(found, "порожній журнал -- «Пакетів ще не було»"); }
	click(KEY_GREEN); CHECK(s_ui.view == APRS_RX_VIEW_PKTLIST, "GREEN на порожньому журналі нічого не відкриває");
	click(KEY_DOWN); click(KEY_UP);
	checkScreen("журнал: порожній, U/D");
	click(KEY_RED);
	CHECK(s_ui.on == 0, "RED з екрана, відкритого з меню, закриває його");

	/* 10 кадрів -> у списку 8 найновіших */
	for (int i = 1; i <= 10; i++)
	{
		char t[160];
		snprintf(t, sizeof(t), "UW5EL%c-%d>APRS,WIDE1-1*:!4903.50N/07201.75W>pkt %d", 'A' + i, i, i);
		jrnPush(t, 1800000000U + (uint32_t)i * 60U);
	}
	/* найдовший: 127 символів */
	{ char t[160]; memset(t, 0, sizeof(t)); snprintf(t, sizeof(t), "N0CALL-9>APRS:`"); for (size_t i = strlen(t); i < 127; i++) { t[i] = (char)('a' + (i % 26)); } t[127] = 0; jrnPush(t, 1800001000U); }
	menuAprsPacketEnter();
	checkScreen("журнал: 8 записів");
	CHECK(s_nrows == 10, "статус + 8 рядків + підказка (є %d)", s_nrows);
	CHECK(strstr(s_rows[1], "N0CALL-9") != NULL && s_rows[1][0] == '>', "найновіший зверху й виділений: «%s»", s_rows[1]);
	CHECK(strstr(s_rows[8], "UW5ELE-4") != NULL, "восьмий -- 4-й кадр з десяти (1..3 витіснено): «%s»", s_rows[8]);
	CHECK(s_rows[1][strlen(s_rows[1]) - 6] == '`', "DTI Mic-E перед RSSI: «%s»", s_rows[1]);
	CHECK(strstr(s_rows[2], "UW5ELK-10") != NULL && strlen(s_rows[2]) <= 26, "довгий позивний вміщується: «%s»", s_rows[2]);
	CHECK(strlen(s_rows[1]) >= 5 && s_rows[1][strlen(s_rows[1]) - 3] == '-' && strlen(s_rows[1]) <= 26, "рядок списку закінчується RSSI (-NN): «%s»", s_rows[1]);
	for (int i = 0; i < 8; i++) { click(KEY_DOWN); }
	CHECK(s_ui.scroll == 0, "8 разів DOWN -- по колу (scroll=%d)", s_ui.scroll);
	click(KEY_UP);
	CHECK(s_ui.scroll == 7, "UP з нуля -> останній запис (scroll=%d)", s_ui.scroll);
	checkScreen("журнал: виділено останній");
	click(KEY_DOWN);
	/* R17 (Г3): ручка (KEY_RIGHT/KEY_LEFT) гортає список так само, як DOWN/UP; у шапці «n/m» */
	CHECK(s_ui.scroll == 0 && !strcmp(s_rows[0] + strlen(s_rows[0]) - 3, "1/8"), "шапка списку: «n/m» (%s)", s_rows[0]);
	key(KEY_RIGHT, KEY_MOD_PRESS); key(KEY_RIGHT, KEY_MOD_UP);
	CHECK(s_ui.scroll == 1 && !strcmp(s_rows[0] + strlen(s_rows[0]) - 3, "2/8"), "ручка вправо -> наступний запис (scroll=%d, %s)", s_ui.scroll, s_rows[0]);
	key(KEY_LEFT, KEY_MOD_PRESS); key(KEY_LEFT, KEY_MOD_UP); key(KEY_LEFT, KEY_MOD_PRESS); key(KEY_LEFT, KEY_MOD_UP);
	CHECK(s_ui.scroll == 7, "ручка вліво з нуля -> останній запис (scroll=%d)", s_ui.scroll);
	key(KEY_RIGHT, KEY_MOD_PRESS); key(KEY_RIGHT, KEY_MOD_UP);
	CHECK(s_ui.scroll == 0, "ручка вправо з останнього -> перший (scroll=%d)", s_ui.scroll);

	/* GREEN -> повний кадр (127 символів = 5 рядків по 26), RED -> назад із тим самим виділенням */
	click(KEY_GREEN);
	CHECK(s_ui.view == APRS_RX_VIEW_PACKET, "GREEN відкриває повний кадр");
	checkScreen("повний кадр 127");
	CHECK(s_nrows == 1 + 5 + 1, "рядок довжини + 5 рядків тексту + підказка (є %d)", s_nrows);
	CHECK(!strncmp(s_rows[1], "N0CALL-9>APRS:`", 15), "перший рядок -- початок кадру: «%s»", s_rows[1]);
	tri0 = s_tri;
	/* R17 (Г3): кадр вміщується на екран (5 рядків з 9) -- тексту гортати нема чого, тож стрілки перемикають на сусідній запис журналу */
	click(KEY_DOWN);
	CHECK(s_ui.view == APRS_RX_VIEW_PACKET && !strncmp(s_rows[1], "UW5ELK-10>", 10), "DOWN у кадрі -> старіший запис: «%s»", s_rows[1]);
	CHECK(!strcmp(s_rows[0] + strlen(s_rows[0]) - 3, "2/8"), "у шапці кадру номер запису «n/8»: «%s»", s_rows[0]);
	CHECK(strchr(s_rows[0], '-') != NULL && strlen(s_rows[0]) <= 26, "у шапці кадру видно RSSI: «%s»", s_rows[0]);
	click(KEY_UP);
	CHECK(!strncmp(s_rows[1], "N0CALL-9>APRS:`", 15), "UP у кадрі -> назад на найновіший: «%s»", s_rows[1]);
	click(KEY_UP);
	CHECK(!strncmp(s_rows[1], "UW5ELE-4>", 9), "UP з найновішого -- по колу на найстаріший: «%s»", s_rows[1]);
	key(KEY_RIGHT, KEY_MOD_PRESS); key(KEY_RIGHT, KEY_MOD_UP);
	CHECK(!strncmp(s_rows[1], "N0CALL-9>APRS:`", 15), "ручка вправо (RIGHT) у кадрі -- як DOWN (по колу): «%s»", s_rows[1]);
	CHECK(s_tri == tri0 && (s_ui.scroll & 0x0F) == 0, "стрілок прокрутки тексту нема (scroll=%02x)", s_ui.scroll);
	jrnPush("A1B>APRS:>new", 1800002000U);
	checkScreen("повний кадр після нового"); CHECK(!strncmp(s_rows[1], "N0CALL-9>APRS:`", 15), "новий кадр не підміняє кадр на екрані");
	click(KEY_RED);
	CHECK(s_ui.view == APRS_RX_VIEW_PKTLIST && s_ui.on == 1 && s_ui.scroll == 1, "RED з кадру -> список, виділено той самий запис (scroll=%d)", s_ui.scroll);
	click(KEY_RED);
	CHECK(s_ui.on == 0, "RED зі списку (відкрито з меню) -> вихід");

	/* з картки: # -> список журналу, RED -> назад на картку */
	menuAprsStationsEnter();
	click(KEY_GREEN);
	CHECK(s_ui.view == APRS_RX_VIEW_CARD && s_ui.cardCall[0] != 0, "картка відкрита");
	click(KEY_HASH);
	CHECK(s_ui.view == APRS_RX_VIEW_PKTLIST, "# на картці -> «Пакети»");
	snprintf(w, sizeof(w), "журнал з картки"); checkScreen(w);
	click(KEY_RED);
	CHECK(s_ui.on == 1 && s_ui.view == APRS_RX_VIEW_CARD, "RED зі списку, відкритого з картки -> картка");

	/* вбудована сторінка «Станцій» «Режиму APRS» */
	click(KEY_HASH);
	menuAprsStationsDrawEmbedded();
	CHECK(s_ui.view == APRS_RX_VIEW_PKTLIST, "вбудований екран лишає список журналу");
	{ uiEvent_t e; memset(&e, 0, sizeof(e)); e.hasEvent = true; e.events = KEY_EVENT; e.keys.key = KEY_GREEN; e.keys.event = KEY_MOD_UP;
	  CHECK(menuAprsStationsKeyEmbedded(&e) == 1 && s_ui.view == APRS_RX_VIEW_PACKET, "вбудований: GREEN -> повний кадр");
	  menuAprsStationsDrawEmbedded(); checkScreen("вбудований: кадр");
	  e.keys.key = KEY_RED;
	  CHECK(menuAprsStationsKeyEmbedded(&e) == 1 && s_ui.view == APRS_RX_VIEW_PKTLIST, "вбудований: RED з кадру -> список");
	  CHECK(menuAprsStationsKeyEmbedded(&e) == 1 && s_ui.view == APRS_RX_VIEW_CARD, "вбудований: RED зі списку -> картка"); }
	{ uiEvent_t e; memset(&e, 0, sizeof(e)); e.hasEvent = true; e.events = KEY_EVENT; e.keys.key = KEY_HASH; e.keys.event = KEY_MOD_UP;
	  CHECK(menuAprsStationsKeyEmbedded(&e) == 1 && s_ui.view == APRS_RX_VIEW_PKTLIST, "вбудований: # з картки -> «Пакети»"); }

	/* «Останній маяк»: нема даних -> сповіщення, ShowAgain не викликається */
	aprsHistClearBeacons(&s_hist);
	s_notes = 0; s_showAgain = 0;
	menuAprsBeaconShow();
	CHECK(s_notes == 1 && s_showAgain == 0 && !strcmp(s_lastNote, APRSRX_BCN_NONE), "порожньо: «Маяків ще не було», вікно не відкрито");
	/* маяк однієї станції (ІНДЕКС 2) -> вікно */
	{
		aprsPacket_t pk; memset(&pk, 0, sizeof(pk)); pk.type = APRS_T_POSITION; pk.hasPos = true; pk.symTable = '/'; pk.symCode = '[';
		aprsHistBeaconFill(&s_hist, &s_db, &s_db.st[2], &pk, true, 3200, 45, 1800000000U, -87);
	}
	menuAprsBeaconShow();
	CHECK(s_notes == 1 && s_showAgain == 1, "є дані: вікно відкрито, сповіщення нема");

	/* на картці: '*' відкриває маяк САМЕ цієї станції; без позиційних пакетів -- сповіщення */
	menuAprsStationsEnter();
	click(KEY_GREEN);   /* станція №0 за новизною */
	CHECK(s_ui.cardCall[0] != 0 && strcmp(s_ui.cardCall, s_db.st[2].call) != 0, "картка станції без маяка");
	s_notes = 0; s_showStation = 0;
	click(KEY_STAR);
	CHECK(s_showStation == 0 && s_notes == 1 && !strcmp(s_lastNote, APRSRX_BCN_NONE_ST), "'*' на картці станції без маяка -- «Маяків від цієї станції не було», вікна нема");
	menuAprsStationsDrawEmbedded();
	{ int found = 0; for (int i = 0; i < s_nrows; i++) { if (!strcmp(s_rows[i], APRSRX_HINT_CARD2)) { found = 1; } } CHECK(found, "підказка без «*:маяк» для станції без маяка"); }
	snprintf(s_ui.cardCall, sizeof(s_ui.cardCall), "%s", s_db.st[2].call);
	s_notes = 0; s_showStation = 0;
	click(KEY_STAR);
	CHECK(s_showStation == 1 && s_notes == 0 && !strcmp(s_lastShown, s_db.st[2].call), "'*' на картці станції з маяком -- вікно саме цієї станції");
	menuAprsStationsDrawEmbedded();
	{
		/* R17 Г6: у картці станції з маяком видно RSSI (-87 дБм), у картці без маяка -- нема */
		int found = 0; for (int i = 0; i < s_nrows; i++) { if (strstr(s_rows[i], "-87") != NULL) { found = 1; } }
		CHECK(found, "картка станції з маяком показує RSSI -87");
	}
	CHECK(s_nrows > 0, "вбудована картка з підказкою маяка");
	{ int found = 0; for (int i = 0; i < s_nrows; i++) { if (!strcmp(s_rows[i], APRSRX_HINT_CARD2B)) { found = 1; } } CHECK(found, "підказка «#:пакет  *:маяк» на картці"); }
	s_maxWidth = 0;
	(void)keyUp;
}

int main(void)
{
	alarm(20);   /* сторож: нескінченний цикл в екрані = провал, а не зависання тесту */
	/* лічильники у крайніх значеннях -- ширина рядків */
	memset(&s_st, 0xFF, sizeof(s_st));
	s_st.state = 2;
	aprsDbInit(&s_db);  walkAll("порожня база");
	memset(&s_st, 0xFF, sizeof(s_st)); s_st.state = 0; s_st.why = APRS_RX_WHY_TX;
	fill(1);            walkAll("1 станція");
	memset(&s_st, 0, sizeof(s_st));
	fill(APRS_STATIONS_MAX); walkAll("повна база");
	/* R10: вбудована сторінка «Станції» «Режиму APRS» не повинна лишатися на діагностичних сторінках */
	for (int v = APRS_RX_VIEW_DIAG; v <= APRS_RX_VIEW_DIAG2; v++)
	{
		s_ui.view = (uint8_t)v; menuAprsStationsDrawEmbedded();
		CHECK(s_ui.view == APRS_RX_VIEW_LIST, "вбудований екран має скинути діагностику (%d) у список", v);
	}
	testPacketScreens();
	/* періодичне перемальовування без подій не повинно падати */
	menuAprsStationsEnter();
	for (int i = 0; i < 100; i++) { s_now += 100; uiEvent_t e; memset(&e, 0, sizeof(e)); menuAprsStationsTick(&e); }
	CHECK(s_renders > 10, "тікер не перемальовує");
	if (failures == 0) { printf("test_aprs_stations_ui: ПРОЙДЕНО\n"); return 0; }
	printf("test_aprs_stations_ui: %d провалів\n", failures);
	return 1;
}
