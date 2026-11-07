#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R65A (Tk + C): виправлення оформлення імен.

A1  CPS «Роумінг»: підписи «Список 1..10» вміщаються в клітинку при шрифтах 100/125/150 % (reqwidth >= ширина тексту);
A2  статус після читання імен: коректна відміна (1 ім'я / 2 імені / 5 імен / 11 імен / 21 ім'я) і перелік «N: ім'я»; без імен -- окремий текст;
A3  читання імен повністю перезаписує ВСІ десять полів (старий вміст не лишається), у т.ч. поле, яке стало порожнім;
A4  випадний «Список:» показує ім'я, якщо задане («1 Робочий (2)»), без імені -- «1 (2)», і розбір номера не ламається;
A5  nameEdFitLabel (C, хост): вміщається -- без змін; не вміщається -- «..» в кінці; довжина завжди <= total; мутанти.
Запуск: xvfb-run -a python3 tools/test_r65.py"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
FAILS = []
PASSED = [0]


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)
    else:
        PASSED[0] += 1


def gui():
    import font_scenarios as fs
    import layout_probe as lp
    import test_r50fix as t50
    import test_r59_ui as t59ui
    import tkinter as tk
    import tkinter.font as tkfont
    root = tk.Tk()
    scs = t50.sc_list(root)
    root.destroy()
    check({pc for _f, pc in scs} == {100, 125, 150}, "A1: сценарії 100/125/150 %%: %r" % (scs,))
    for sc in scs:
        app = t59ui.new_app(sc)
        try:
            app.show("roam")
            lp.spin(app, 0.4)
            p = app.get_panel("roam")
            for lb in p.name_labels:
                p.update_idletasks()
                f = tkfont.nametofont(str(lb.cget("font")) or "TkDefaultFont") if str(lb.cget("font")) else tkfont.nametofont("TkDefaultFont")
                check(int(str(lb.cget("width")) or 0) == 0, "A1: підпис «%s» без фіксованої width (природна ширина тексту)" % lb.cget("text"))
                need = f.measure(lb.cget("text"))
                check(lb.winfo_reqwidth() >= need and lb.winfo_width() >= need, "A1 [%s]: підпис «%s» тісний: reqwidth %d, width %d, текст %d" % (fs.label(sc), lb.cget("text"), lb.winfo_reqwidth(), lb.winfo_width(), need))
            if sc is not scs[0]:
                continue
            # A2
            st = type(p).names_status
            for names, exp in (
                    ([""] * 10, "імен не задано"),
                    (["ЕЖИҐ"] + [""] * 9, "задано 1 ім'я -- 1: ЕЖИҐ."),
                    (["А", "Б"] + [""] * 8, "задано 2 імені -- 1: А; 2: Б."),
                    (["А", "Б", "В", "Г", "Д"] + [""] * 5, "задано 5 імен"),
                    ([str(i) for i in range(10)], "задано 10 імен")):
                check(exp in st(names), "A2: статус %r має містити %r: %r" % (names[:3], exp, st(names)))
            check("задано 1 ім'я" in st(["x"] + [""] * 9) and "11" not in st(["x"] + [""] * 9), "A2: однина")
            # A3
            for v in p.v_names:
                v.set("Старе")
            p._apply_names(["ЕЖИҐ"] + [""] * 9, b"")
            check([v.get() for v in p.v_names] == ["ЕЖИҐ"] + [""] * 9, "A3: усі поля перезаписані: %r" % [v.get() for v in p.v_names])
            p._apply_names(None, None)
            check(all(v.get() == "" for v in p.v_names), "A3: «блока нема» очищає всі поля")
            # A4
            p._apply_names(["Робочий"] + [""] * 9, b"")
            check(p._list_label(1, 2, p._sel_name(1)) == "1 Робочий (2)", "A4: з іменем: %r" % p._list_label(1, 2, p._sel_name(1)))
            check(p._list_label(2, 0, p._sel_name(2)) == "2 (0)", "A4: без імені: %r" % p._list_label(2, 0, p._sel_name(2)))
            p.v_list.set("1 Робочий (2)")
            check(p.current_list() == 1, "A4: номер із підпису з іменем")
            p.v_list.set("3 (0)")
            check(p.current_list() == 3, "A4: номер із підпису без імені")
        finally:
            try:
                app.update()
            except Exception:  # noqa: BLE001
                pass


HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
void nameEdFitLabel(char *out, unsigned num, const char *name, unsigned total);
int main(void)
{
	char out[64];
	for (unsigned total = 3; total <= 14; total++)
		for (unsigned n = 0; n <= 16; n++)
			for (unsigned num = 1; num <= 10; num += 9)
			{
				char name[20];
				memset(name, 0, sizeof name);
				for (unsigned i = 0; i < n; i++) name[i] = (char)('a' + i);
				memset(out, 'Z', sizeof out); out[63] = 0;
				nameEdFitLabel(out, num, name, total);
				unsigned hl = (num >= 10) ? 3U : 2U;
				printf("%u %u %u %s\n", total, n, num, out);
				if (strlen(out) > total) { printf("LONG\n"); return 1; }
				if (total >= hl + n && strcmp(out + hl, name) != 0) { printf("CHANGED\n"); return 1; }
			}
	return 0;
}
'''


def c_part():
    if not shutil.which("gcc"):
        print("test_r65: нема gcc -- A5 пропущено")
        return
    with tempfile.TemporaryDirectory() as td:
        src = open(os.path.join(ROOT, "application", "source", "user_interface", "uiNameEditor.c"), encoding="utf-8", errors="replace").read()
        a = src.index("void nameEdFitLabel")
        b = src.index("#endif /* UI_NAME_EDITOR */")
        fn = src[a:b]
        for mut, patch in (("ok", None),
                           ("без_крапок", ("'.';\n\t\tout[h + room - 1U] = '.';", "'x';\n\t\tout[h + room - 1U] = 'x';")),
                           ("за_межу", ("memcpy(out + h, name, room - 2U);", "memcpy(out + h, name, room - 3U);")),
                           ("не_вміщається_межа", ("if (n <= room)", "if (n < room)"))):
            f = fn
            if patch:
                if patch[0] not in f:
                    check(False, "A5: мутант %s не застосовується" % mut)
                    continue
                f = f.replace(*patch)
            c = os.path.join(td, "t.c")
            open(c, "w", encoding="utf-8").write("#include <stdio.h>\n#include <string.h>\n" + f + HARNESS)
            exe = os.path.join(td, "t")
            r = subprocess.run(["gcc", "-O1", "-w", c, "-o", exe], capture_output=True, text=True)
            if r.returncode != 0:
                check(False, "A5: збірка %s: %s" % (mut, r.stderr[-300:]))
                continue
            p = subprocess.run([exe], capture_output=True, text=True)
            if mut == "ok":
                check(p.returncode == 0, "A5: оригінал: " + p.stdout[-200:])
                lines = p.stdout.splitlines()
                got = {tuple(l.split(" ", 3)[:3]): (l.split(" ", 3)[3] if len(l.split(" ", 3)) > 3 else "") for l in lines}
                check(got[("10", "7", "1")] == "1 abcdefg", "A5: влізло: %r" % got[("10", "7", "1")])
                check(got[("10", "9", "1")] == "1 abcdef..", "A5: обрізано з «..»: %r" % got[("10", "9", "1")])
            else:
                check(p.returncode != 0 or _differs(p.stdout), "A5: мутант %s вижив" % mut)


_REF = [None]


def _differs(out):
    # еталон для ok: перерахувати незалежно в Python
    for l in out.splitlines():
        parts = l.split(" ", 3)
        if len(parts) < 3:
            continue
        total, n, num = int(parts[0]), int(parts[1]), int(parts[2])
        got = parts[3] if len(parts) > 3 else ""
        name = "".join(chr(ord("a") + i) for i in range(n))
        head = "%d " % num
        room = max(total - len(head), 0)
        exp = head + (name if n <= room else (name[:room - 2] + ".." if room >= 3 else ""))
        if got != exp:
            return True
    return False


def main():
    c_part()
    try:
        import tkinter  # noqa: F401
        have = bool(os.environ.get("DISPLAY"))
    except ImportError:
        have = False
    if have:
        try:
            gui()
        except Exception as e:  # noqa: BLE001
            import traceback
            FAILS.append("gui: виняток %s: %s" % (type(e).__name__, e))
            traceback.print_exc()
    else:
        print("test_r65: нема tkinter/DISPLAY -- GUI-частину пропущено")
    if FAILS:
        print("test_r65: %d провалів" % len(FAILS))
        return 1
    print("test_r65: усе гаразд (%d перевірок)" % PASSED[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
