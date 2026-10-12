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
	/* періодичне перемальовування без подій не повинно падати */
	menuAprsStationsEnter();
	for (int i = 0; i < 100; i++) { s_now += 100; uiEvent_t e; memset(&e, 0, sizeof(e)); menuAprsStationsTick(&e); }
	CHECK(s_renders > 10, "тікер не перемальовує");
	if (failures == 0) { printf("test_aprs_stations_ui: ПРОЙДЕНО\n"); return 0; }
	printf("test_aprs_stations_ui: %d провалів\n", failures);
	return 1;
}
