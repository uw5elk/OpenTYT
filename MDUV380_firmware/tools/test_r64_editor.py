#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R64B: спільний редактор назви (application/source/user_interface/uiNameEditor.c) ПОВОДИТЬСЯ ТАК САМО, як редактор назви зони до R64 (menuZoneList.c: zrGetMs/zrSetMs/zrMode/
zrDraw/zrCommit/zrKey і гілка «лівий -- стерти» в zrHandleEvent).

Диференційний тест: старий код БЕРЕТЬСЯ З GIT (коміт OLD_REF -- R63C, на якому стоїть R64) і збирається поруч із справжнім uiNameEditor.c; обидва отримують ті самі випадкові послідовності
натискань (цифри, «*», «#» коротко/довго, лівий, різні паузи між натисканнями) і ПІСЛЯ КОЖНОЇ клавіші мають мати однаковий буфер стану [0..27] і однаковий малюнок екрана
(заголовок, рядок з курсором, мітка режиму, підказка, лічильник). Якщо коміту нема в історії (git am створює нові хеші, але R63C -- у базі) -- тест пропускається і каже про це.
Окремо: токени решти menuZoneList.c (без перенесених функцій) -- у test_r46.py (W5)."""
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.normpath(os.path.join(HERE, ".."))
OLD_REF = os.environ.get("R64_OLD_REF", "8e31b00")
OLD_PATH = "MDUV380_firmware/application/source/user_interface/menuZoneList.c"
NEWSRC = os.path.join(FW, "application", "source", "user_interface", "uiNameEditor.c")
MULTITAP = os.path.join(FW, "application", "source", "functions", "sms_multitap.c")


def incs():
    return ["-I" + FW + "/tools/hoststub", "-include", FW + "/tools/hoststub/host_compat.h", "-I" + FW, "-I" + FW + "/Core/Inc",
            "-I" + FW + "/Drivers/CMSIS/Device/ST/STM32F4xx/Include", "-I" + FW + "/Drivers/CMSIS/Include",
            "-I" + FW + "/Drivers/STM32F4xx_HAL_Driver/Inc", "-I" + FW + "/Drivers/STM32F4xx_HAL_Driver/Inc/Legacy",
            "-I" + FW + "/Middlewares/ST/STM32_USB_Device_Library/Class/CDC/Inc", "-I" + FW + "/Middlewares/ST/STM32_USB_Device_Library/Core/Inc",
            "-I" + FW + "/Middlewares/Third_Party/FreeRTOS/Source/CMSIS_RTOS_V2", "-I" + FW + "/Middlewares/Third_Party/FreeRTOS/Source/include",
            "-I" + FW + "/Middlewares/Third_Party/FreeRTOS/Source/portable/GCC/ARM_CM4F", "-I" + FW + "/USB_DEVICE/App", "-I" + FW + "/USB_DEVICE/Target",
            "-I" + FW + "/application/include"]


DEFS = ["-DUSE_HAL_DRIVER", "-DSTM32F405xx", "-DPLATFORM_MDUV380", "-DPLATFORM_VARIANT_UV380_PLUS_10W", "-DNDEBUG", "-DLANGUAGE_BUILD_UKRAINIAN", "-DENABLE_AES",
        "-DENABLE_DMR_DATA", "-DENABLE_APRS_RX", "-DENABLE_ZONE_RENAME", "-funsigned-char"]


def func_text(src, name):
    m = re.search(r"^static [^\n]*\b%s\(" % re.escape(name), src, re.M)
    if not m:
        raise RuntimeError("у старому menuZoneList.c нема функції %s" % name)
    end = src.index("\n}\n", m.start()) + 3
    return src[m.start():end]


def old_tu(src):
    parts = [func_text(src, n) for n in ("zrGetMs", "zrSetMs", "zrMode", "zrDraw", "zrCommit", "zrKey")]
    h = re.search(r"static void zrHandleEvent\(uiEvent_t \*ev\)\n\{.*?\n\}\n", src, re.S).group(0)
    a = h.index("else if (KEYCHECK_PRESS(ev->keys, KEY_LEFT))")
    left_and_text = h[a:h.rindex("}")]
    return ('''#include "user_interface/uiGlobals.h"
#include "user_interface/menuSystem.h"
#include "user_interface/uiUtilities.h"
#include "user_interface/uiLocalisation.h"
#include "functions/sms_multitap.h"
#include "user_interface/languages/aprsmode_ua.h"
#define ZR_BUF     (uiDataGlobal.MessageBox.message)
#define ZR_CAP     16
#define ZR_KEY     ZR_BUF[17]
#define ZR_IDX     ZR_BUF[18]
#define ZR_MODE    ZR_BUF[19]
#define ZR_ACTIVE  ZR_BUF[20]
''' + "\n".join(parts) + '''
void old_start(const char *name)
{
	memset(ZR_BUF, 0, 28);
	strncpy(ZR_BUF, name, 16);
	ZR_KEY = 0;
	ZR_IDX = 0;
	ZR_MODE = (char)((ZR_BUF[0] == 0) ? SMS_MT_UA_UP : SMS_MT_UA_LO);
	zrSetMs(0);
	ZR_ACTIVE = 1;
	zrDraw();
}
void old_event(uiEvent_t *ev)
{
	if (0) { }
	''' + left_and_text + '''}
''')


HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "user_interface/uiGlobals.h"
#include "user_interface/menuSystem.h"
#include "user_interface/uiLocalisation.h"
#include "user_interface/uiNameEditor.h"
#include "functions/sms_multitap.h"

uiDataGlobal_t uiDataGlobal;
static stringsTable_t s_lang;
const stringsTable_t *currentLanguage = &s_lang;
static uint32_t s_now;
uint32_t ticksGetMillis(void) { return s_now; }

static char s_rec[4096];
static void rec(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
#include <stdarg.h>
static void rec(const char *fmt, ...) { va_list a; va_start(a, fmt); size_t n = strlen(s_rec); vsnprintf(s_rec + n, sizeof s_rec - n, fmt, a); va_end(a); }
void displayClearBuf(void) { rec("CLR;"); }
void displayRender(void) { rec("RND;"); }
void menuDisplayTitle(const char *t) { rec("TITLE[%s];", t); }
void displayThemeApply(themeItem_t fg, themeItem_t bg) { rec("TH%d,%d;", (int)fg, (int)bg); }
int displayPrintCore(int16_t x, int16_t y, const char *t, ucFont_t f, ucTextAlign_t a, bool inv) { rec("CORE(%d,%d,%s,%d,%d,%d);", x, y, t, (int)f, (int)a, (int)inv); return 0; }
void displayFillRect(int16_t x, int16_t y, int16_t w, int16_t h, bool inv) { rec("FILL(%d,%d,%d,%d,%d);", x, y, w, h, (int)inv); }
void displayPrintAt(uint16_t x, uint16_t y, const char *t, ucFont_t f) { rec("AT(%u,%u,%s,%d);", x, y, t, (int)f); }
/* R66B: рядок-підказка «Вниз: розкладка клавіш» (y=96) -- НОВИЙ, у старому редакторі зони його не було; тут не записується (розділ B у test_r66.py). Шпаргалка -- заглушка. */
void displayPrintCentered(uint16_t y, const char *t, ucFont_t f) { (void)y; (void)t; (void)f; }
void uiSmsKeyLayoutDraw(uint8_t mode, const char *title, const char *hint) { rec("SHEET(%d,%s,%s);", (int)mode, title, hint); }

void old_start(const char *name);
void old_event(uiEvent_t *ev);

int main(void)
{
	unsigned seed = 1;
	int seqs = 2500;
	char old28[28];
	char oldrec[4096];
	long steps = 0;
	srand(seed);
	for (int s = 0; s < seqs; s++)
	{
		char name[17];
		int len = (s % 3 == 0) ? 0 : rand() % 17;
		memset(name, 0, sizeof name);
		for (int i = 0; i < len; i++) { name[i] = (char)(0x20 + (rand() % 224)); if ((unsigned char)name[i] == 0x98) name[i] = 'x'; }
		s_now = 100000U + (unsigned)(rand() % 5000);
		s_rec[0] = 0;
		old_start(name);
		strcpy(oldrec, s_rec);
		memcpy(old28, uiDataGlobal.MessageBox.message, 28);
		s_rec[0] = 0;
		nameEdInit(uiDataGlobal.MessageBox.message, name);
		nameEdDraw(uiDataGlobal.MessageBox.message, "");
		/* old_start уже малює; новий init не малює, тож порівнюємо лише буфер, а малюнок -- після першої клавіші */
		if (memcmp(old28, uiDataGlobal.MessageBox.message, 28) != 0) { printf("FAIL init seq=%d\n", s); return 1; }
		if (strcmp(oldrec, s_rec) != 0) { printf("FAIL init draw seq=%d\n  old=%s\n  new=%s\n", s, oldrec, s_rec); return 1; }
		int nk = 1 + rand() % 40;
		for (int k = 0; k < nk; k++)
		{
			uiEvent_t e;
			static const char keys[] = "0123456789*#";
			int kind = rand() % 14;
			memset(&e, 0, sizeof e);
			e.hasEvent = true; e.events = KEY_EVENT;
			if (kind == 13) { e.keys.key = KEY_LEFT; e.keys.event = KEY_MOD_PRESS; }
			else
			{
				e.keys.key = keys[kind % 12];
				int ev = rand() % 4;
				e.keys.event = (ev == 0) ? (KEY_MOD_PRESS) : (ev == 1) ? (KEY_MOD_UP) : (ev == 2) ? (KEY_MOD_PRESS | KEY_MOD_LONG) : (KEY_MOD_UP);
			}
			int dt = rand() % 4;
			s_now += (dt == 0) ? 50U : (dt == 1) ? 400U : (dt == 2) ? 999U : 1500U;
			/* стан старого і нового ВИМІРЮЄМО на двох копіях буфера: гоняти по черзі на одному буфері не можна */
			char keep[68];
			memcpy(keep, uiDataGlobal.MessageBox.message, 68);
			s_rec[0] = 0;
			old_event(&e);
			strcpy(oldrec, s_rec);
			char afterOld[68];
			memcpy(afterOld, uiDataGlobal.MessageBox.message, 68);
			memcpy(uiDataGlobal.MessageBox.message, keep, 68);
			s_rec[0] = 0;
			(void)nameEdHandleKey(uiDataGlobal.MessageBox.message, "", &e);
			if (memcmp(afterOld, uiDataGlobal.MessageBox.message, 28) != 0 || strcmp(oldrec, s_rec) != 0)
			{
				printf("FAIL seq=%d key=%d: key='%c' ev=%u\n  old=%s\n  new=%s\n", s, k, e.keys.key, (unsigned)e.keys.event, oldrec, s_rec);
				return 1;
			}
			steps++;
		}
	}
	printf("OK %ld кроків у %d послідовностях\n", steps, seqs);
	return 0;
}
'''


def main():
    if not shutil.which("gcc") or not shutil.which("git"):
        print("test_r64_editor: нема gcc/git -- пропущено")
        return 0
    r = subprocess.run(["git", "-C", FW, "show", "%s:%s" % (OLD_REF, OLD_PATH)], capture_output=True)
    if r.returncode != 0:
        print("test_r64_editor: коміт %s недоступний -- пропущено (задай R64_OLD_REF)" % OLD_REF)
        return 0
    src = r.stdout.decode("utf-8")
    with tempfile.TemporaryDirectory() as td:
        oldc = os.path.join(td, "old.c")
        with open(oldc, "w", encoding="utf-8") as f:
            f.write(old_tu(src))
        hc = os.path.join(td, "h.c")
        with open(hc, "w", encoding="utf-8") as f:
            f.write(HARNESS)
        exe = os.path.join(td, "h")
        cmd = ["gcc", "-O1", "-w", "-std=gnu11"] + incs() + DEFS + [hc, oldc, NEWSRC, MULTITAP, "-Wl,--unresolved-symbols=ignore-all", "-o", exe]
        b = subprocess.run(cmd, capture_output=True, text=True)
        if b.returncode != 0:
            print("ПРОВАЛ: збірка тесту:\n" + b.stderr[-1500:])
            return 1
        p = subprocess.run([exe], capture_output=True, text=True, errors="replace", timeout=120)
        out = p.stdout.strip()
        if p.returncode != 0 or not out.startswith("OK"):
            print("ПРОВАЛ: " + out[-1500:] + p.stderr[-300:])
            return 1
        print("test_r64_editor: " + out + " -- спільний редактор == старий редактор зони (буфер [0..27] і малюнок після кожної клавіші).")
        return 0


if __name__ == "__main__":
    sys.exit(main())
