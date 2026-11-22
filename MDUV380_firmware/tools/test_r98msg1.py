# -*- coding: utf-8 -*-
"""test_r98msg1.py -- R98-MSG1: «Повідом. APRS» у вигляді «SMS DMR» (APRS_MSG1_UI) і лічильники «n/m» у SMS DMR.

Хостовий гарнес: СПРАВЖНІЙ menuAprsMode.c + aprs_msg.c + sms_format.c + sms_multitap.c; справжні menuGetMenuOffset() (menuSystem.c)
і uiSmsTimeStr() (uiSms.c) вирізаються з файлів прошивки; дисплей і меню -- заглушки, що друкують кожен примітив (текст, координати,
шрифт, виділення). Сценарії натискають клавіші через menuAprsModeTick() і перевіряють те, що намальовано, та стан списку.

  А  головний екран: 3 пункти «Нове / Вхідні n/m / Надіслані m», виділення в центрі (menuGetMenuOffset), без підказки, без «[Видалити всі]»
  Б  список вхідних: «*позивний:текст» (14 стовпців) + час «ГГ:ХХ»/«ДД.ММ» на x=124; «[Видалити все]» -- останній пункт; заголовок n/m
  В  список надісланих: галочка = ACK, '!' = без ACK, '~' = чекає/надіслано; час
  Г  годинник не виставлено -> вік («12хв»), «чекає» -- словом; тик-лічильник переповнився після запису -> вік
  Д  читання: заголовок «Вхідні 1/2», «Від CALL» + «ДД.ММ ГГ:ХХ», підказки як у DMR; надіслане -- «Кому CALL стан {NN»
  Е  «ще раз»: GREEN на надісланому -> набір з адресатом і текстом, заголовок «Ще раз»; GREEN на вхідному -- «відповісти»
  Є  SK2+RED -- усі прочитані; RED -- назад
  Ж  «[Видалити все]»: по колу вгору з першого, підтвердження «Записів: N», видаляє лише цей напрямок
  З  U/D у читанні: гортає текст, на краю -- сусіднє, на краю списку -- сигнал помилки
  И  порожній список: «(порожньо)» + «RED:назад»
  К  діагностична збірка (ENABLE_APRS_RX_PROBE) -- без APRS_MSG1_UI: старий вигляд R19 (підказка, 4 пункти, вік)
  Л  SMS DMR: «Вхідні n/m» / «Надіслані m» (перший екран і заголовки списків), n обмежено m; стовпчик часу APRS = DMR
  М  мутанти: старий формат рядка, без «ще раз», без SK2+RED, «[Видалити все]» видаляє обидва напрямки
"""
import os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)
APP = os.path.join(FW, "application")
SRC_MODE = os.path.join(APP, "source", "user_interface", "menuAprsMode.c")
SRC_MSGS = os.path.join(APP, "source", "user_interface", "menuMessages.c")
FAILS = []
N = [0]


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m)
        print("ПРОВАЛ: " + m)


def rd(p):
    return open(p, encoding="utf-8").read()


def carve(src, head):
    """Функція від рядка-заголовка до закриваючої '}' на початку рядка."""
    i = src.find(head + "\n{")
    if i < 0:
        return None
    j = src.find("\n}\n", i)
    return src[i:j + 3] if j > 0 else None


def cstr(s):
    """Рядок Python -> C-літерал у cp1251 (\\xNN для не-ASCII)."""
    out = []
    for b in s.encode("cp1251"):
        out.append(chr(b) if 32 <= b < 127 and chr(b) not in '"\\' else "\\x%02x" % b)
    return '"' + "".join(out) + '" ""'   # порожній літерал: \xNN не зливається з наступною шістнадцятковою цифрою


NOW_MS = 100000000
CLOCK = 1795359600   # 2026-11-22 15:00:00 UTC, пояс 0
LONG = "абвгдежзийк " * 7   # слова по 11 літер: у рядок 20 стовпців влазить одне -> 7 рядків > 5 видимих (великий шрифт)
IN_ROWS = [  # call, text, unread, age_s
    ("UR5ABC", "Привіт, як справи?", 1, 12 * 60),
    ("UT1XYZ-7", "QSL", 1, 26 * 3600),
]
OUT_ROWS = [  # call, text, status, id, age_s
    ("UR5ABC-7", "Тест ACK", "AMSG_ST_ACK", "12", 3 * 60),
    ("UT1XYZ", "Нема ACK", "AMSG_ST_NOACK", "13", 40 * 60),
    ("UW5ELK", "Чекає", "AMSG_ST_WAIT", "14", 30),
    ("UY2QQQ", "Пішло", "AMSG_ST_SENT", "15", 90),
]

HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "functions/aprs_mode.h"
#include "functions/aprs_msg.h"
#include "functions/aprs_rx.h"
#include "functions/sms_format.h"
#include "functions/sound.h"
#include "functions/settings.h"
#include "user_interface/menuSystem.h"
#include "user_interface/uiGlobals.h"
#include "user_interface/uiUtilities.h"
#include "user_interface/menuAprsMode.h"
#include "user_interface/menuAprsStations.h"
#include "user_interface/uiSmsKeys.h"

uiDataGlobal_t uiDataGlobal;
menuDataGlobal_t menuDataGlobal;
settingsStruct_t nonVolatileSettings;
const int16_t MELODY_ERROR_BEEP[] = { 0 };
static aprsMsgBox_t s_box;
static aprsModeUi_t s_ui;
static aprsRxUi_t s_rxui;
static uint32_t s_now = __NOW__;
static int s_beeps = 0;
static int s_quiet = 0;
static char s_lastSendTo[16], s_lastSendText[96];

uint32_t ticksGetMillis(void) { return s_now; }
aprsMsgBox_t *aprsModeMsgBox(void) { return &s_box; }
aprsModeUi_t *aprsModeUi(void) { return &s_ui; }
aprsRxUi_t *aprsRxUi(void) { return &s_rxui; }
bool aprsModeMsgSessionOpen(void) { return true; }
void aprsModeMsgSessionClose(void) { printf("SESSIONCLOSE\n"); }
int aprsModeMsgSend(const char *to, const char *t) { snprintf(s_lastSendTo, sizeof s_lastSendTo, "%s", to); snprintf(s_lastSendText, sizeof s_lastSendText, "%s", t); printf("SEND\n"); return AMSG_OK; }
uint16_t aprsModeCp1251ToUcs2(uint8_t c) { return c; }
void soundSetMelody(const int16_t *m) { (void)m; s_beeps++; }
void uiNotificationShow(uiNotificationType_t a, uiNotificationID_t b, uint32_t c, const char *m, bool d) { printf("NOTIFY|%s\n", m); }
void uiSmsKeyHint(uint8_t mode, char key, uint8_t idx, int16_t x, int16_t y) { }
void uiSmsKeyLayoutDraw(uint8_t mode, const char *title, const char *hint) { }
void menuAprsStationsAgeStr(char *b, size_t n, uint32_t sec) { __AGESTR__ }
void displayClearBuf(void) { if (!s_quiet) printf("CLEAR\n"); }
void displayRender(void) { if (!s_quiet) printf("RENDER\n"); }
void displayThemeApply(themeItem_t f, themeItem_t b) { }
void displayThemeResetToDefault(void) { }
void displayFillRect(int16_t x, int16_t y, int16_t w, int16_t h, bool inv) { }
void displayFillTriangle(int16_t x0, int16_t y0, int16_t x1, int16_t y1, int16_t x2, int16_t y2, bool inv) { if (!s_quiet) printf("TRI|%d|%d\n", x0, y0); }
int displayPrintCore(int16_t x, int16_t y, const char *t, ucFont_t f, ucTextAlign_t a, bool inv) { if (!s_quiet) printf("CORE|%d|%d|%d|%d|%s\n", x, y, (int)f, (int)a, t); return 0; }
void displayPrintAt(uint16_t x, uint16_t y, const char *t, ucFont_t f) { if (!s_quiet) printf("AT|%d|%d|%d|%s\n", x, y, (int)f, t); }
void displayPrintCentered(uint16_t y, const char *t, ucFont_t f) { if (!s_quiet) printf("CENT|%d|%d|%s\n", y, (int)f, t); }
void menuDisplayTitle(const char *t) { if (!s_quiet) printf("TITLE|%s\n", t); }
void menuDisplayEntry(int lo, int item, const char *t, int32_t opt, themeItem_t a, themeItem_t b, themeItem_t c) { if (!s_quiet) printf("ENTRY|%d|%d|%d|%s\n", lo, item, (item == menuDataGlobal.currentItemIndex) ? 1 : 0, t); }
void uiDrawTickMark(int16_t cx, int16_t cy, themeItem_t fg, bool focused) { if (!s_quiet) printf("TICK|%d|%d|%d\n", cx, cy, focused ? 1 : 0); }
__MENUOFFSET__
__TIMESTR__

static void add(int i, int dir, const char *call, const char *text, int unread, int status, const char *id, uint32_t age)
{
	aprsMsgEntry_t *e = &s_box.list[i];
	memset(e, 0, sizeof(*e));
	e->used = 1; e->dir = (uint8_t)dir; e->unread = (uint8_t)unread; e->status = (uint8_t)status;
	snprintf(e->call, sizeof e->call, "%s", call); snprintf(e->id, sizeof e->id, "%s", id); snprintf(e->text, sizeof e->text, "%s", text);
	e->ms = s_now - age * 1000U;
}

static void key(char k, uint8_t ev, uint32_t buttons)
{
	uiEvent_t e;
	memset(&e, 0, sizeof e);
	e.hasEvent = true; e.events = KEY_EVENT; e.keys.key = k; e.keys.event = ev; e.buttons = buttons;
	printf("== KEY %d %d %lu\n", (int)k, (int)ev, (unsigned long)buttons);
	(void)menuAprsModeTick(&e);
}
#define SHORT(k)   key((k), KEY_MOD_UP, 0)
#define PRESS(k)   key((k), KEY_MOD_PRESS, 0)
#define SK2(k)     key((k), KEY_MOD_UP, BUTTON_SK2)

static void state(void)
{
	aprsMsgUi_t *mu = &s_ui.msg;
	unsigned un = 0, n = 0;
	for (int i = 0; i < (int)APRS_MSG_LIST_MAX; i++) { if (s_box.list[i].used) { n++; if (s_box.list[i].unread) un++; } }
	printf("STATE|view=%u|sel=%u|scroll=%u|dir=%u|top=%u|reply=%u|err=%u|used=%u|unread=%u|in=%u|out=%u|beeps=%d|call=%s|text=%s\n", mu->view, mu->sel, mu->scroll,
			mu->dirFilter, mu->readTop, mu->reply, mu->err, n, un, aprsMsgDirCount(&s_box, AMSG_DIR_IN), aprsMsgDirCount(&s_box, AMSG_DIR_OUT), s_beeps, mu->call, mu->text);
}

int main(int argc, char **argv)
{
	const char *sc = (argc > 1) ? argv[1] : "home";
	memset(&s_box, 0, sizeof s_box);
	uiDataGlobal.dateTimeSecs = __CLOCK__;
	nonVolatileSettings.timezone = 0;
	if ((strcmp(sc, "noclock") == 0) || (strcmp(sc, "noclockout") == 0)) { uiDataGlobal.dateTimeSecs = 0; }
	if (strcmp(sc, "empty") != 0)
	{
__FILL__
	}
	if (strcmp(sc, "wrap") == 0) { s_box.list[0].ms = s_now + 5000U; }   /* лічильник переповнився після запису */
	if (strcmp(sc, "long") == 0) { snprintf(s_box.list[0].text, sizeof s_box.list[0].text, "%s", __LONG__); snprintf(s_box.list[1].text, sizeof s_box.list[1].text, "%s", __LONG__); }
	printf("== ENTER\n");
	(void)menuAprsMsgEnter();
	if (strcmp(sc, "home") == 0) { state(); return 0; }
	PRESS(KEY_DOWN);
	if ((strcmp(sc, "out") == 0) || (strcmp(sc, "readout") == 0) || (strcmp(sc, "resend") == 0) || (strcmp(sc, "delout") == 0) || (strcmp(sc, "noclockout") == 0))
	{
		PRESS(KEY_DOWN);
	}
	SHORT(KEY_GREEN);
	state();
	if ((strcmp(sc, "read") == 0) || (strcmp(sc, "readout") == 0))
	{
		SHORT(KEY_GREEN);
		state();
	}
	return 0;
}
'''

# Скрипти сценаріїв після входу в список (окремо, щоб main лишався простим): виконуються з кодом C у гарнесі нижче.
SCRIPTS = {
    "in": "",
    "out": "",
    "noclock": "",
    "noclockout": "",
    "wrap": "",
    "empty": "",
    "read": "SHORT(KEY_GREEN); state();",
    "readout": "SHORT(KEY_GREEN); state();",
    "resend": "SHORT(KEY_GREEN); state(); SHORT(KEY_GREEN); state();",
    "reply": "SHORT(KEY_GREEN); state(); SHORT(KEY_GREEN); state();",
    "markall": "SK2(KEY_RED); state(); SHORT(KEY_RED); state();",
    "delall": "PRESS(KEY_UP); state(); SHORT(KEY_GREEN); state(); SHORT(KEY_GREEN); state();",
    "delout": "PRESS(KEY_UP); state(); SHORT(KEY_GREEN); state(); SHORT(KEY_GREEN); state();",
    "delone": "SK2(KEY_GREEN); state(); SHORT(KEY_GREEN); state();",
    "long": "SHORT(KEY_GREEN); state(); for (int k = 0; k < 12; k++) { PRESS(KEY_DOWN); state(); } for (int k = 0; k < 12; k++) { PRESS(KEY_DOWN); state(); }"
            " for (int k = 0; k < 30; k++) { PRESS(KEY_UP); state(); }",
}


def build_harness(src_mode, tmp, extra_defs=()):
    msys = rd(os.path.join(APP, "source", "user_interface", "menuSystem.c"))
    mo = carve(msys, "int menuGetMenuOffset(int maxMenuItems, int loopOffset)")
    usms = rd(os.path.join(APP, "source", "user_interface", "uiSms.c"))
    ts = carve(usms, "int uiSmsTimeStr(uint32_t t, int mode, char *out, int outsz)")
    stations = rd(os.path.join(APP, "source", "user_interface", "menuAprsStations.c"))
    age = carve(stations, "static void ageStr(char *b, size_t n, uint32_t sec)")
    ld = carve(stations, "void menuAprsListDraw(int count, int sel, aprsListItemFn_t fn)")
    if ld is None:
        return None, "не вирізано menuAprsListDraw"
    if mo is None or ts is None or age is None:
        return None, "не вирізано menuGetMenuOffset/uiSmsTimeStr/ageStr"
    age_body = age[age.index("{") + 1:age.rindex("}")]
    fill = []
    i = 0
    for call, text, unread, a in IN_ROWS:
        fill.append("\t\tadd(%d, AMSG_DIR_IN, %s, %s, %d, AMSG_ST_NONE, \"\", %dU);" % (i, cstr(call), cstr(text), unread, a)); i += 1
    for call, text, st, idd, a in OUT_ROWS:
        fill.append("\t\tadd(%d, AMSG_DIR_OUT, %s, %s, 0, %s, \"%s\", %dU);" % (i, cstr(call), cstr(text), st, idd, a)); i += 1
    h = HARNESS.replace("__NOW__", str(NOW_MS)).replace("__CLOCK__", str(CLOCK)).replace("__MENUOFFSET__", mo).replace("__TIMESTR__", ts + "\n" + ld)
    h = h.replace("__AGESTR__", age_body.replace("APRSRX_AGE", "H_AGE")).replace("__FILL__", "\n".join(fill)).replace("__LONG__", cstr(LONG))
    # вік -- ті самі формати, що в aprsrx_ua.h (cp1251)
    rx = open(os.path.join(APP, "include", "user_interface", "languages", "aprsrx_ua.h"), "rb").read().decode("cp1251")
    agedefs = "\n".join("#define H_AGE_%s %s" % (k, cstr(v)) for k, v in re.findall(r'#define\s+APRSRX_AGE_(\w)\s+"([^"]*)"', rx))
    h = h.replace("uiDataGlobal_t uiDataGlobal;", agedefs + "\nuiDataGlobal_t uiDataGlobal;")
    # сценарії: вставляємо гілки перед «return 0;» у кінці main
    branches = "".join('\tif (strcmp(sc, "%s") == 0) { %s }\n' % (k, v) for k, v in SCRIPTS.items() if v and k not in ("read", "readout"))
    h = h.replace("\tif ((strcmp(sc, \"read\") == 0) || (strcmp(sc, \"readout\") == 0))", branches + "\tif ((strcmp(sc, \"read\") == 0) || (strcmp(sc, \"readout\") == 0))", 1)
    hp = os.path.join(tmp, "h.c")
    open(hp, "w", encoding="utf-8").write(h)
    mp = os.path.join(tmp, "menuAprsMode.c")
    open(mp, "w", encoding="utf-8").write(src_mode)
    incs = ["-I" + os.path.join(FW, "tools", "hoststub"), "-include", os.path.join(FW, "tools", "hoststub", "host_compat.h"), "-I" + FW,
            "-I" + os.path.join(FW, "Core", "Inc"), "-I" + os.path.join(FW, "Drivers", "CMSIS", "Device", "ST", "STM32F4xx", "Include"),
            "-I" + os.path.join(FW, "Drivers", "CMSIS", "Include"), "-I" + os.path.join(FW, "Drivers", "STM32F4xx_HAL_Driver", "Inc"),
            "-I" + os.path.join(FW, "Middlewares", "Third_Party", "FreeRTOS", "Source", "include"),
            "-I" + os.path.join(FW, "Middlewares", "Third_Party", "FreeRTOS", "Source", "CMSIS_RTOS_V2"),
            "-I" + os.path.join(FW, "Middlewares", "Third_Party", "FreeRTOS", "Source", "portable", "GCC", "ARM_CM4F"),
            "-I" + os.path.join(APP, "include")]
    defs = ["-DUSE_HAL_DRIVER", "-DSTM32F405xx", "-DPLATFORM_MDUV380", "-DPLATFORM_VARIANT_UV380_PLUS_10W", "-DNDEBUG", "-DLANGUAGE_BUILD_UKRAINIAN",
            "-DENABLE_APRS_RX", "-DENABLE_AES", "-DENABLE_DMR_DATA"] + list(extra_defs)
    exe = os.path.join(tmp, "h")
    srcs = [hp, mp] + [os.path.join(APP, "source", "functions", f) for f in ("aprs_msg.c", "sms_format.c", "sms_multitap.c")]
    r = subprocess.run(["gcc", "-std=gnu11", "-w", "-o", exe] + defs + incs + srcs, capture_output=True, text=True, timeout=240)
    if r.returncode != 0:
        return None, (r.stdout + r.stderr)[-1500:]
    return exe, ""


def run(exe, sc):
    r = subprocess.run([exe, sc], capture_output=True, timeout=60)
    return r.stdout.decode("cp1251", "replace")


def frames(out):
    """Останній кадр (від останнього CLEAR до RENDER) і список станів."""
    lines = out.splitlines()
    fr = []
    cur = None
    for l in lines:
        if l == "CLEAR":
            cur = []
        elif l == "RENDER":
            if cur is not None:
                fr.append(cur)
            cur = None
        elif cur is not None:
            cur.append(l.split("|"))
    st = [dict(kv.split("=", 1) for kv in l.split("|")[1:]) for l in lines if l.startswith("STATE|")]
    return fr, st


def ents(fr):
    return [(int(p[1]), int(p[2]), int(p[3]), p[4]) for p in fr if p[0] == "ENTRY"]


def title(fr):
    t = [p[1] for p in fr if p[0] == "TITLE"]
    return t[-1] if t else None


def hhmm(age_s):
    import time
    return time.strftime("%H:%M", time.gmtime(CLOCK - age_s))


def ddmm(age_s):
    import time
    return time.strftime("%d.%m", time.gmtime(CLOCK - age_s))


def scenario_checks(exe, tag, msg1=True):
    res = {}
    for sc in ("home", "in", "out", "noclock", "noclockout", "wrap", "empty", "read", "readout", "resend", "reply", "markall", "delall", "delout", "delone", "long"):
        res[sc] = frames(run(exe, sc))
    return res


def main():
    src = rd(SRC_MODE)
    tmp = tempfile.mkdtemp(prefix="r98msg1_")
    try:
        exe, err = build_harness(src, tmp)
        check(exe is not None, "гарнес menuAprsMode.c (APRS_MSG1_UI) зібрався: %s" % err)
        if exe is None:
            return finish()
        R = scenario_checks(exe, "msg1")

        # ---- А: головний екран
        fr, st = R["home"]
        f = fr[-1]
        e = ents(f)
        check(title(f) is not None and "APRS" in title(f), "А0: заголовок першого екрана: %r" % title(f))
        check([x[3] for x in sorted(e, key=lambda x: x[1])] == ["Нове повідомлення", "Вхідні 2/2", "Надіслані 4"],
              "А1: 3 пункти «Нове повідомлення / Вхідні n/m (непрочитані/усього) / Надіслані m»: %r" % e)
        check([x for x in e if x[2] == 1] == [x for x in e if x[0] == 0] and len([x for x in e if x[2] == 1]) == 1,
              "А2: виділений пункт -- у центральному рядку (loopOffset 0), як у SMS DMR: %r" % e)
        check(not any(p[0] == "CENT" and p[1] == "112" for p in f) and not any("Видалити" in x[3] for x in e),
              "А3: без підказки внизу (y=112) і без «[Видалити всі]» на першому екрані")
        check(st[-1]["view"] == "4", "А4: вхід -- перший екран (APRS_MSG_VIEW_HOME): %r" % st[-1])

        # ---- Б: список вхідних
        fr, st = R["in"]
        f = fr[-1]
        e = sorted(ents(f), key=lambda x: x[1])
        check(title(f) == "Вхідні 2/2", "Б0: заголовок списку «Вхідні n/m»: %r" % title(f))
        exp0 = ("*UR5ABC:Привіт, як справи?")[:14]
        exp1 = ("*UT1XYZ-7:QSL")[:14]
        check([x[3] for x in e] == [exp0, exp1, "[Видалити все]"],
              "Б1: рядки «маркер+позивний:текст» обрізано до 14 стовпців (LIST_TEXT_COLS), останній -- «[Видалити все]»: %r" % [x[3] for x in e])
        check(len(e) == 3 and [x for x in e if x[2] == 1][0][0] == 0 and [x for x in e if x[2] == 1][0][1] == 0,
              "Б2: вибраний -- перший запис, у центральному рядку: %r" % e)
        times = [(int(p[1]), int(p[2]), int(p[3]), p[5]) for p in f if p[0] == "CORE"]
        y_of = {x[1]: 64 + x[0] * 16 for x in e}
        check((124, y_of[0] + 4, 0, hhmm(12 * 60)) in times and (124, y_of[1] + 4, 0, ddmm(26 * 3600)) in times,
              "Б3: час праворуч (x=124, y=рядок+4, FONT_SIZE_1): сьогодні «%s», учора «%s»: %r" % (hhmm(720), ddmm(26 * 3600), times))
        check(not any(p[0] == "AT" and p[2] == "116" for p in f) and not any(p[0] == "CENT" and p[1] == "112" for p in f),
              "Б4: підказки внизу списку нема (7 рядків, як у SMS DMR)")
        check(not any(p[0] == "TICK" for p in f), "Б5: у вхідних галочок нема")

        # ---- В: надіслані
        fr, st = R["out"]
        f = fr[-1]
        e = sorted(ents(f), key=lambda x: x[1])
        check(title(f) == "Надіслані 4", "В0: заголовок «Надіслані m»: %r" % title(f))
        exp = [(" UR5ABC-7:Тест ACK")[:14], ("!UT1XYZ:Нема ACK")[:14], ("~UW5ELK:Чекає")[:14], ("~UY2QQQ:Пішло")[:14], "[Видалити все]"]
        check([x[3] for x in e] == exp, "В1: маркери ✓(пробіл+галочка)/!/~ і «адресат:текст»: %r" % [x[3] for x in e])
        ticks = [(int(p[1]), int(p[2])) for p in f if p[0] == "TICK"]
        y_of = {x[1]: 64 + x[0] * 16 for x in e}
        check(ticks == [(8, y_of[0])], "В2: галочка лише на ACK-рядку, у першій клітинці (x=8): %r" % ticks)
        times = {int(p[2]): p[5] for p in f if p[0] == "CORE" and p[1] == "124"}
        check(times.get(y_of[2] + 4) == hhmm(30) and times.get(y_of[0] + 4) == hhmm(180), "В3: «чекає» з відомим годинником -- час: %r" % times)

        # ---- Г: годинник не виставлено / переповнення
        fr, st = R["noclock"]
        f = fr[-1]
        times = sorted(p[5] for p in f if p[0] == "CORE" and p[1] == "124")
        check(times == sorted(["12хв", "1д"]), "Г1: годинник не виставлено -> вік у стовпчику часу: %r" % times)
        fr, st = R["noclockout"]
        f = fr[-1]
        times = [p[5] for p in f if p[0] == "CORE" and p[1] == "124"]
        check("чекає" in times and "3хв" in times and "40хв" in times, "Г2: без годинника «чекає» -- словом, решта -- вік: %r" % times)
        fr, st = R["wrap"]
        f = fr[-1]
        e = sorted(ents(f), key=lambda x: x[1])
        times = {int(p[2]): p[5] for p in f if p[0] == "CORE" and p[1] == "124"}
        y0 = 64 + [x for x in e if x[1] == 0][0][0] * 16
        check(not re.match(r"^\d\d[:.]\d\d$", times.get(y0 + 4, "")), "Г3: тик-лічильник переповнився після запису -> не час (вік): %r" % times.get(y0 + 4))

        # ---- Д: читання
        fr, st = R["read"]
        f = fr[-1]
        check(title(f) == "Вхідні 1/2", "Д1: заголовок читання «Вхідні 1/2» (позиція/усього): %r" % title(f))
        check(["AT", "2", "16", "0", "Від UR5ABC"] in f, "Д2: рядок 1 «Від CALL» (x=2, y=16, FONT_SIZE_1)")
        full = "22.11 " + hhmm(720)
        check(["CORE", str(158 - len(full) * 6), "16", "0", "0", full] in f, "Д3: час «ДД.ММ ГГ:ХХ» праворуч у рядку 1: %r" % [p for p in f if p[0] == "CORE"])
        check(["CENT", "112", "0", "SK2+GRN:вид GRN:відпов"] in f, "Д4: підказка вхідного -- як у SMS DMR")
        txt = [p for p in f if p[0] == "CORE" and p[3] == "3"]
        check(txt and txt[0][2] == "26" and txt[0][1] == "0", "Д5: текст великим шрифтом з y=26, x=0: %r" % txt[:1])
        check(st[-1]["unread"] == "1", "Д6: відкрите стало прочитаним (2 -> 1): %r" % st[-1])
        fr, st = R["readout"]
        f = fr[-1]
        check(title(f) == "Надіслані 1/4", "Д7: заголовок читання надісланого: %r" % title(f))
        check(["AT", "2", "16", "0", "Кому UR5ABC-7 ACK {12"] in f, "Д8: «Кому CALL стан {NN»: %r" % [p for p in f if p[0] == "AT"])
        check(["CENT", "112", "0", "SK2+GRN:вид GRN:ще раз"] in f, "Д9: підказка надісланого -- «ще раз»")
        hdr = "Кому UR5ABC-7 ACK {12"
        full = "22.11 " + hhmm(180)
        row = "16" if (2 + len(hdr) * 6 + 6 + len(full) * 6) <= 158 else "25"
        check(["CORE", str(158 - len(full) * 6), row, "0", "0", full] in f, "Д10: час надісланого (рядок 1 або 2 за шириною): %r" % [p for p in f if p[0] == "CORE"][:2])

        # ---- Е: ще раз / відповісти
        fr, st = R["resend"]
        s = st[-1]
        check(s["view"] == "3" and s["call"] == "UR5ABC-7" and s["text"] == "Тест ACK" and s["reply"] == "2",
              "Е1: GREEN на надісланому -> набір тексту (VIEW_TEXT) з адресатом і текстом запису, reply=2: %r" % s)
        check(title(fr[-1]) == "Ще раз", "Е2: заголовок набору «Ще раз»: %r" % title(fr[-1]))
        fr, st = R["reply"]
        s = st[-1]
        check(s["view"] == "3" and s["call"] == "UR5ABC" and s["text"] == "" and s["reply"] == "1", "Е3: GREEN на вхідному -> «відповісти» (текст порожній): %r" % s)

        # ---- Є: SK2+RED
        fr, st = R["markall"]
        check(st[1]["unread"] == "0" and st[1]["view"] == "0", "Є1: SK2+RED у списку -- усі вхідні прочитані, лишаємось у списку: %r" % st[1])
        check(title(fr[-2]) == "Вхідні 0/2", "Є2: заголовок після SK2+RED «Вхідні 0/2»: %r" % title(fr[-2]))
        check(st[2]["view"] == "4", "Є3: RED без SK2 -- назад на перший екран: %r" % st[2])

        # ---- Ж: видалити все
        fr, st = R["delall"]
        check(st[1]["sel"] == "2" and st[1]["view"] == "0", "Ж1: ↑ з першого -- по колу на «[Видалити все]» (sel = count): %r" % st[1])
        check(st[2]["view"] == "5" and st[2]["err"] == "1", "Ж2: GREEN на ньому -> підтвердження (CONFIRM, усі): %r" % st[2])
        conf = fr[-2]
        check(["CENT", "58", "0", "Записів: 2"] in conf, "Ж3: «Записів: N» -- лише цього напрямку: %r" % [p for p in conf if p[0] == "CENT"])
        check(st[3]["in"] == "0" and st[3]["out"] == "4" and st[3]["view"] == "0", "Ж4: GREEN -- видалено лише вхідні, надіслані лишились, назад у список: %r" % st[3])
        fr, st = R["delout"]
        check(st[3]["in"] == "2" and st[3]["out"] == "0", "Ж5: з «Надісланих» -- лише надіслані: %r" % st[3])
        fr, st = R["delone"]
        check(st[1]["view"] == "5" and st[1]["err"] == "0" and st[2]["in"] == "1", "Ж6: SK2+GREEN -- одне з підтвердженням: %r" % st[1:])

        # ---- З: гортання в читанні
        fr, st = R["long"]
        tops = [int(s["top"]) for s in st]
        sels = [int(s["sel"]) for s in st]
        mx = max(tops)
        check(mx > 0, "З1: DOWN гортає довгий текст: %r" % tops[:8])
        i = tops.index(mx)
        check(sels[i + 1] == 1 and tops[i + 1] == 0, "З2: DOWN на краю тексту -> сусіднє повідомлення з першого рядка: sel %r top %r" % (sels[i:i + 3], tops[i:i + 3]))
        check(int(st[-1]["beeps"]) >= 1 and sels[-1] == 0, "З3: на краю списку -- сигнал помилки, UP повертає до першого: %r" % st[-1])
        downs_after_last = [s for s in st[1:25] if s["sel"] == "1"]
        check(len(set(s["sel"] for s in st[1:25])) == 2, "З4: за межі списку не виходимо")
        tris = [p for f in fr for p in f if p[0] == "TRI"]
        check(any(p[1] == str(160 - 9) for p in tris) and any(p[1] == "4" for p in tris), "З5: трикутники ▼/▲ є")

        # ---- И: порожній
        fr, st = R["empty"]
        f = fr[-1]
        check(["CENT", "56", "3", "(порожньо)"] in f and ["CENT", "112", "0", "RED:назад"] in f, "И1: порожній список як у SMS DMR: %r" % f)

        # ---- К: діагностична збірка -- старий вигляд
        tmp2 = os.path.join(tmp, "probe"); os.makedirs(tmp2)
        exe2, err2 = build_harness(src, tmp2, ("-DENABLE_APRS_RX_PROBE",))
        check(exe2 is not None, "К0: гарнес у діагностичній збірці (ENABLE_APRS_RX_PROBE) зібрався: %s" % err2)
        if exe2:
            fr, st = frames(run(exe2, "home"))
            f = fr[-1]
            e = sorted(ents(f), key=lambda x: x[1])
            check(len(e) == 4 and "Видалити" in e[3][3] and ["CENT", "112", "0", "GREEN:вибір RED:назад"] in f,
                  "К1: без APRS_MSG1_UI -- перший екран R19 (4 пункти з «[Видалити всі]», підказка): %r" % e)
            fr, st = frames(run(exe2, "in"))
            f = fr[-1]
            e = sorted(ents(f), key=lambda x: x[1])
            check(len(e) == 2 and ":" not in e[0][3] and "12хв" in e[0][3], "К2: без APRS_MSG1_UI -- старий рядок «*позивний  вік»: %r" % e)

        # ---- Л: SMS DMR і спільні константи
        ms = rd(SRC_MSGS)
        mua = open(os.path.join(APP, "include", "user_interface", "languages", "messages_ua.h"), "rb").read().decode("cp1251")
        check(re.search(r'#define MSGS_INBOX_FMT\s+"Вхідні %d/%d"', mua) is not None and re.search(r'#define MSGS_SENT_FMT\s+"Надіслані %d"', mua) is not None,
              "Л1: messages_ua.h -- «Вхідні %d/%d», «Надіслані %d»")
        check(re.search(r'#define MSGS_INBOX_FMT\s+"Inbox %d/%d"', ms) is not None and re.search(r'#define MSGS_SENT_FMT\s+"Sent %d"', ms) is not None,
              "Л2: англійська гілка #else -- з тими ж аргументами")
        fn = carve(ms, "static void smsInboxTitle(char *buf, int cap)")
        check(fn is not None and "dmrSmsUnreadCount()" in fn and "dmrSmsCount(0)" in fn and "(unread < total) ? unread : total" in fn,
              "Л3: smsInboxTitle -- непрочитані (обмежено усім) / усього")
        lu = carve(ms, "static void listUpdate(void)")
        check(lu is not None and "smsInboxTitle(title, sizeof title)" in lu and "MSGS_SENT_FMT, count" in lu and "menuDisplayTitle(title)" in lu,
              "Л4: заголовки списків SMS DMR -- з лічильниками")
        hu = carve(ms, "static void homeUpdate(void)")
        check(hu is not None and "smsInboxTitle(buf, sizeof buf)" in hu and "MSGS_SENT_FMT,  dmrSmsCount(1)" in hu, "Л5: перший екран SMS DMR -- «Вхідні n/m»")
        # компіляція smsInboxTitle із заглушками
        if fn:
            c = '#include <stdio.h>\n#define MSGS_INBOX_FMT "%%d/%%d"\nstatic int U, T;\nint dmrSmsCount(int o){return T;}\nint dmrSmsUnreadCount(void){return U;}\n%s\n' \
                'int main(void){char b[24]; int cs[][2]={{2,9},{0,0},{3,2},{1,1}}; for(int i=0;i<4;i++){U=cs[i][0];T=cs[i][1];smsInboxTitle(b,sizeof b);printf("%%s\\n",b);} return 0;}\n' % fn
            p = os.path.join(tmp, "t.c"); open(p, "w").write(c)
            r = subprocess.run(["gcc", "-o", p + ".x", p], capture_output=True, text=True)
            o = subprocess.run([p + ".x"], capture_output=True, text=True).stdout.split() if r.returncode == 0 else None
            check(o == ["2/9", "0/0", "2/2", "1/1"], "Л6: n обмежено m (відкладене вхідне не дає «3/2»): %r" % o)
        dmr_x = re.search(r"#define LIST_TIME_X\s+(.*)", ms).group(1).strip()
        dmr_c = re.search(r"#define LIST_TEXT_COLS\s+(.*)", ms).group(1).strip()
        check(re.search(r"#define AM_LIST_TIME_X\s+" + re.escape(dmr_x), src) is not None and
              re.search(r"#define AM_LIST_TEXT_COLS\s+" + re.escape(dmr_c.replace("LIST_TIME_X", "AM_LIST_TIME_X")), src) is not None,
              "Л7: стовпчик часу APRS (AM_LIST_TIME_X/AM_LIST_TEXT_COLS) = SMS DMR (LIST_TIME_X/LIST_TEXT_COLS)")
        cfg = rd(os.path.join(APP, "include", "functions", "aprs_rx_cfg.h"))
        check(re.search(r"#if defined\(APRS_RX\) && !defined\(ENABLE_APRS_RX_PROBE\) && defined\(ENABLE_AES\) && defined\(ENABLE_DMR_DATA\)\n#define APRS_MSG1_UI 1", cfg) is not None,
              "Л8: APRS_MSG1_UI -- лише користувацька збірка з SMS DMR (diag/probe не чіпаємо)")
        hm = rd(os.path.join(APP, "include", "functions", "aprs_msg.h"))
        check("char     text[APRS_MSG_TEXT_LEN];" in hm and "#define APRS_MSG_LIST_MAX      8U" in hm, "Л9: aprsMsgEntry_t і розмір списку не змінено")

        # ---- М: мутанти
        def mut(name, a, b, scen, pred):
            s2 = src.replace(a, b, 1)
            if s2 == src:
                check(False, "М (%s): шаблон мутанта не знайдено" % name)
                return
            d = os.path.join(tmp, "m%d" % N[0]); os.makedirs(d)
            ex, er = build_harness(s2, d)
            if ex is None:
                check(True, "М (%s): не збирається -- теж ловиться" % name)
                return
            check(pred(frames(run(ex, scen))) is False, "М (%s): ловиться" % name)
        mut("старий формат рядка", 'snprintf(buf, sizeof(buf), "%c%s:%s", msgListMark(e), e->call, e->text);',
            'snprintf(buf, sizeof(buf), "%c%-9.9s", msgListMark(e), e->call);', "in",
            lambda r: sorted(ents(r[0][-1]), key=lambda x: x[1])[0][3] == ("*UR5ABC:Привіт, як справи?")[:14])
        mut("нема «ще раз»", "msgComposeResend(&b->list[aprsMsgNth(b, mu->dirFilter, mu->sel)]);   /* R98-MSG1: надіслане -- «ще раз» */\n\t\t\t\treturn 1;",
            "", "resend", lambda r: r[1][-1]["text"] == "Тест ACK")
        mut("нема SK2+RED", "msgMarkAllRead(b);   /* R98-MSG1 (А)", "(void)b;   /* R98-MSG1 (А)", "markall", lambda r: r[1][1]["unread"] == "0")
        mut("видаляє обидва напрямки", "msgDeleteDir(b, mu->dirFilter);", "(void)aprsMsgDeleteAll(b);", "delall", lambda r: r[1][3]["out"] == "4")
        mut("час після переповнення тик-лічильника", " || (nowMs < e->ms))", ")", "wrap",
            lambda r: not any(re.match(r"^\d\d[:.]\d\d$", p[5]) and int(p[2]) == 64 + [x for x in ents(r[0][-1]) if x[1] == 0][0][0] * 16 + 4
                              for p in r[0][-1] if p[0] == "CORE" and p[1] == "124"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return finish()


def finish():
    print("перевірок: %d, провалів: %d" % (N[0], len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
