#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R54 (Tk): розділ «Супутники» -- таблиця частот, форма всіх трьох наборів і шляху APRS, перевірка перед записом, верстка.

U1  розділ відкривається з вбудованою таблицею (9 рядків); секції «3. Таблиця частот» і «4. Відбір і слоти»; біля адреси Celestrak нема «НЕ ПЕРЕВІРЕНО»;
U2  форма слота показує й застосовує ВСІ набори: RX/TX, субтон, субтон взведення, APRS, маяк, шлях APRS; старий виклик із чотирма полями працює; хиба -- слот не змінено;
U3  мітки в таблиці слотів: «без частот» (тег nofreq), помилка (тег bad); підсумок перевірки під таблицею;
U4  запис в рацію: помилка частоти -- відмова ДО підтвердження; попередження про передачу й слоти без частот -- у тексті підтвердження;
U5  своя таблиця: відкрити файл, запам'ятати шлях, повернутись до вбудованої; хибний файл не руйнує поточну; ~/MD-UV390UKR/satellites.txt підхоплюється сам;
U6  «Додати з таблиці» і «Заповнити порожні слоти» з панелі: повідомлення, слоти, кнопки;
U7  верстка при масштабі 100 / 125 / 150 % (шрифт системи й DejaVu Sans): розділ «Супутники» без обрізання, з повними 25 слотами і довгим підсумком перевірки.
Запуск: xvfb-run -a python3.12 tools/test_r54_ui.py"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FAILS = []
PASSED = [0]
ORIG = os.path.join(HERE, "testdata", "satellites_user_2026-11-01.txt")


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)
    else:
        PASSED[0] += 1


def new_app(sc=None):
    import font_scenarios as fs
    import test_r36 as t36
    spath = os.path.join(tempfile.mkdtemp(prefix="r54ui_"), "ui.json")
    os.environ["TYT_CPS_SETTINGS"] = spath
    app = t36.make_app(spath)
    if sc is not None:
        fs.apply(app, sc)
    t36.spin(app, 0.3)
    return app


class Dialogs:
    """Підміна вікон: записує, що було показано."""

    def __init__(self):
        from tkinter import messagebox
        import gui_dialogs as gd
        self.mb, self.gd = messagebox, gd
        self.infos, self.errors, self.confirms = [], [], []
        self.answer = False
        self._old = (messagebox.showinfo, messagebox.showerror, gd.confirm_dialog)
        messagebox.showinfo = lambda t, m, **k: self.infos.append(m)
        messagebox.showerror = lambda t, m, **k: self.errors.append(m)
        gd.confirm_dialog = lambda parent, title, text, yes="Так", no="Ні": (self.confirms.append(text), self.answer)[1]

    def restore(self):
        self.mb.showinfo, self.mb.showerror, self.gd.confirm_dialog = self._old


def labels_of(w):
    out, stack = [], [w]
    while stack:
        x = stack.pop()
        stack.extend(x.winfo_children())
        try:
            out.append(str(x.cget("text")))
        except Exception:  # noqa: BLE001
            pass
    return out


def tles_for(norads):
    import sat_tle as st
    import test_r35 as t35
    out = []
    for n, nm in norads:
        a, l1, l2 = t35.mk_tle(nm, n, 26, 300.0)
        out.append(st.parse_tle_text("\n".join((a, l1, l2)))[0][0])
    return out


def test_u1_u6():
    import layout_probe as lp
    import sat_table as stb
    import sat_tle as st
    app = new_app()
    dlg = Dialogs()
    try:
        app.show("satellites")
        lp.spin(app, 0.4)
        p = app.get_panel("satellites")
        txt = "\n".join(labels_of(p))
        # --- U1 ---
        check(len(p.table_rows) == 9 and "вбудована стартова" in p.table_label.cget("text") and "рядків 9" in p.table_label.cget("text"), "U1: вбудована таблиця, 9 рядків: %s" % p.table_label.cget("text"))
        check("3. Таблиця частот" in txt and "4. Відбір і слоти" in txt and "3. Відбір і слоти" not in txt, "U1: секції пронумеровані 3 і 4")
        check("НЕ ПЕРЕВІРЕНО" not in p.src_var.get() and all("НЕ ПЕРЕВІРЕНО" not in s[0] for s in __import__("cps_ui.p_satellites", fromlist=["SOURCES"]).SOURCES), "U1: біля Celestrak нема «НЕ ПЕРЕВІРЕНО»")
        check("НЕ ПЕРЕВІРЕНО" not in txt.replace("на залізі НЕ ПЕРЕВІРЕНІ", ""), "U1: у підписах розділу «НЕ ПЕРЕВІРЕНО» лишилось лише про частоти на залізі")
        check("Додати з таблиці" in txt and "Заповнити порожні слоти з таблиці" in txt and "Відкрити свою таблицю" in txt and "Вбудована таблиця" in txt, "U1: кнопки таблиці")
        check(str(p.add_table_btn.cget("state")) != "disabled" and str(p.open_table_btn.cget("state")) != "disabled", "U1: кнопки таблиці не потребують рації")

        # --- U6: Додати з таблиці ---
        p._on_add_table()
        check(dlg.infos and "Спершу відкрий" in dlg.infos[-1], "U6: без TLE -- підказка")
        p.set_tles(tles_for([(43017, "AO-91"), (25544, "ISS (ZARYA)"), (59112, "SONATE-2"), (99999, "ІНШЕ")]), (), "тест")
        p._on_add_table()
        lp.spin(app, 0.2)
        rep = dlg.infos[-1]
        check([s.name for s in p.slots] == ["AO-91", "ISS", "SONATE-2"], "U6: додано три: %r" % [s.name for s in p.slots])
        check("Немає TLE" in rep and "AO-123 (61781)" in rep and "Додано в слоти: 3" in rep, "U6: звіт називає рядки без TLE: %s" % rep)
        check(p.is_dirty(), "U6: є незаписані зміни")
        iid = {p.slot_tree.set(i, "name"): i for i in p.slot_tree.get_children()}
        # --- U1/U2: форма показує все ---
        p.slot_tree.selection_set(iid["ISS"])
        lp.spin(app, 0.2)
        got = [v.get() for v in (p.name_var, p.rx_var, p.tx_var, p.ctcss_var, p.arm_var, p.rx2_var, p.tx2_var, p.rx3_var, p.tx3_var, p.aprs_var)]
        check(got == ["ISS", "437.8", "145.99", "67", "", "145.825", "145.825", "145.8", "", "RS0ISS"], "U2: форма ISS показує всі набори: %r" % got)
        check(p.slot_tree.item(iid["ISS"], "tags") in ((), ""), "U3: ISS без міток")
        p.slot_tree.selection_set(iid["SONATE-2"])
        lp.spin(app, 0.2)
        check(p.tx_var.get() == "" and p.tx2_var.get() == "145.825" and p.aprs_var.get() == "DP0SNX", "U2: SONATE-2: Tx1 порожнє, Tx2 є, шлях DP0SNX")

        # --- U2: застосування ---
        p.slot_tree.selection_set(iid["ISS"])
        lp.spin(app, 0.2)
        p.arm_var.set("74.4")
        p.tx3_var.set("")
        p.rx3_var.set("145,8")
        p.aprs_var.set("WIDE1-1 RS0ISS")
        p.rx2_var.set("145.826")
        p._on_apply_form()
        s = p.slots[1]
        check(s.arm == 744 and s.rx3 == 145_800_000 and s.rx2 == 145_826_000 and s.tx2 == 145_825_000 and stb.decode_aprs(s.extra) == "WIDE1-1 RS0ISS" and s.rx1 == 437_800_000,
              "U2: форма записала arm / маяк / APRS / шлях: %r" % ((s.arm, s.rx2, s.rx3, stb.decode_aprs(s.extra)),))
        before = p.slots[1].pack()
        dlg.errors.clear()
        p.aprs_var.set("TOOLONGCALL")
        p._on_apply_form()
        check(dlg.errors and "шлях APRS" in dlg.errors[-1] and p.slots[1].pack() == before, "U2: хибний шлях APRS -- повідомлення, слот не змінено")
        p.aprs_var.set("WIDE1-1 RS0ISS")
        p.rx_var.set("abc")
        dlg.errors.clear()
        p._on_apply_form()
        check(dlg.errors and p.slots[1].pack() == before, "U2: хибна частота -- слот не змінено")
        # старий виклик із чотирма полями не чіпає решту
        p.apply_form(1, "ISS", "437.8", "145.99", "67")
        check(p.slots[1].arm == 744 and p.slots[1].rx2 == 145_826_000 and stb.decode_aprs(p.slots[1].extra) == "WIDE1-1 RS0ISS", "U2: apply_form з чотирма полями решту не чіпає")
        # шлях APRS, який не змінювали, байтів не переписує (навіть якщо вони нестандартні)
        odd = bytearray(p.slots[1].extra)
        odd[6] = 0x07
        odd[20] = 0x55
        p.slots[1].extra = bytes(odd)
        p.apply_form(1, "ISS", "437.8", "145.99", "67", aprs=stb.decode_aprs(p.slots[1].extra))
        check(bytes(p.slots[1].extra) == bytes(odd), "U2: незмінений шлях APRS не переписується")
        p.slots[1].extra = stb.encode_aprs("RS0ISS")

        # --- U3: мітки ---
        p.slots.append(st.Slot("ПУСТО"))
        p.slots[-1].name = "EMPTY"
        p.slots.append(st.Slot("BADBAND", rx1=100_000_000, tx1=435_000_000))
        p._redraw_slots()
        iid = {p.slot_tree.set(i, "name"): i for i in p.slot_tree.get_children()}
        check("nofreq" in p.slot_tree.item(iid["EMPTY"], "tags") and "bad" in p.slot_tree.item(iid["BADBAND"], "tags"), "U3: теги nofreq / bad у таблиці слотів")
        check(p.slot_tree.set(iid["EMPTY"], "freq") == "без частот", "U3: підпис «без частот»")
        summ = p.issue_label.cget("text")
        check("ПОМИЛКИ" in summ and "BADBAND" in summ and "Без частот" in summ and "EMPTY" in summ, "U3: підсумок під таблицею: %s" % summ)

        # --- U4: запис ---
        dlg.errors.clear()
        dlg.confirms.clear()
        p._on_write()
        check(dlg.errors and "BADBAND" in dlg.errors[-1] and "RX1" in dlg.errors[-1] and not dlg.confirms, "U4: помилка частоти -- відмова до підтвердження: %r" % dlg.errors)
        p.slots[-1].rx1 = 145_900_000
        p.slots[-1].tx1 = 300_000_000 // 1
        p.slots[-1].tx1 = 270_000_000
        p._redraw_slots()
        dlg.errors.clear()
        p._on_write()
        check(not dlg.errors and dlg.confirms, "U4: без помилок -- доходить до підтвердження")
        t = dlg.confirms[-1]
        check("ПОПЕРЕДЖЕННЯ щодо передачі" in t and "BADBAND" in t and "TX1" in t and "Слоти без частот" in t and "EMPTY" in t, "U4: підтвердження містить попередження й слоти без частот: %s" % t[-400:])

        # --- U5: своя таблиця ---
        check(p.load_table_file(ORIG) and len(p.table_rows) == 11 and p.shell.settings.get("sat_table") == ORIG and ORIG in p.table_label.cget("text"), "U5: свою таблицю відкрито, шлях запам'ятано")
        p._on_builtin_table()
        check(len(p.table_rows) == 9 and not p.shell.settings.get("sat_table"), "U5: повернення до вбудованої, шлях забуто")
        bad = os.path.join(tempfile.mkdtemp(prefix="r54bad_"), "x.txt")
        open(bad, "w", encoding="utf-8").write("це не таблиця\nзовсім\n")
        dlg.errors.clear()
        check(p.load_table_file(bad) is False and dlg.errors and len(p.table_rows) == 9, "U5: файл без придатних рядків -- помилка, поточна таблиця лишається")
        check(p.load_table_file(os.path.join(os.path.dirname(bad), "нема.txt")) is False and len(p.table_rows) == 9, "U5: файла нема -- помилка")
        # ~/MD-UV390UKR/satellites.txt підхоплюється
        from pathlib import Path
        home = tempfile.mkdtemp(prefix="r54home_")
        os.makedirs(os.path.join(home, "MD-UV390UKR"))
        open(os.path.join(home, "MD-UV390UKR", "satellites.txt"), "wb").write(open(ORIG, "rb").read())
        old_home = Path.home
        Path.home = classmethod(lambda cls: Path(home))
        try:
            p.shell.settings.set("sat_table", "")
            check(p.user_table_path() == os.path.join(home, "MD-UV390UKR", "satellites.txt"), "U5: файл у ~/MD-UV390UKR знайдено")
            p._load_initial_table()
            check(len(p.table_rows) == 11, "U5: стартує зі своєї таблиці з ~/MD-UV390UKR")
        finally:
            Path.home = old_home
        p._on_builtin_table()

        # --- U6: заповнити порожні ---
        p.slots = [st.Slot("LilacSat"), st.Slot("ISS", rx1=145_000_000), st.Slot("NOPE")]
        p._redraw_slots()
        dlg.infos.clear()
        p._on_fill_table()
        msg = dlg.infos[-1]
        check(p.slots[0].rx1 == 437_200_000 and p.slots[1].rx1 == 145_000_000 and p.slots[1].tx1 == 0 and "Заповнено: LilacSat" in msg and "не чіпаю: ISS" in msg and "NOPE" in msg,
              "U6: заповнення порожніх: %s" % msg)
        p.slots = []
        dlg.infos.clear()
        p._on_fill_table()
        check(dlg.infos and "нічого нема" in dlg.infos[-1], "U6: без слотів -- підказка")
        # Додати вибрані: за NORAD підставляє з таблиці
        p.slots = []
        p.set_tles(tles_for([(27607, "SAUDISAT 1C (SO-50)")]), (), "тест")
        p.tle_tree.selection_set(*p.tle_tree.get_children())
        p._on_add()
        check(p.slots and p.slots[0].name == "SO-50" and p.slots[0].arm == 744, "U6: «Додати вибрані» підставляє частоти з таблиці за NORAD")
    finally:
        dlg.restore()
        try:
            app.update()
        except Exception:  # noqa: BLE001
            pass
        app.destroy()


def test_u7_layout():
    import font_scenarios as fs
    import layout_probe as lp
    import sat_table as stb
    import sat_tle as st
    import test_r36 as t36
    import test_r50fix as t50
    import tkinter as tk
    mk = t36.doc_factory()
    root = tk.Tk()
    scs = t50.sc_list(root)
    root.destroy()
    check(len(scs) >= 3 and {pc for _f, pc in scs} == {100, 125, 150}, "U7: сценарії охоплюють 100/125/150 %%: %r" % (scs,))
    for sc in scs:
        app = new_app(sc)
        try:
            p = app.get_panel("satellites")
            # найгірший випадок вмісту: 25 слотів, у частині помилки й попередження, довгі назви таблиці, зауваження парсера
            p.slots = [st.Slot("SAT%d" % i, rx1=145_960_000, tx1=435_250_000, rx2=145_825_000, tx2=145_825_000, rx3=145_800_000) for i in range(20)]
            p.slots += [st.Slot("BAD%d" % i, rx1=100_000_000 + i, tx1=300_000_000) for i in range(3)] + [st.Slot("ZERO1"), st.Slot("ZERO2")]
            p.set_table(stb.default_rows()[0], ["рядок %d: тестове зауваження про некоректний рядок таблиці частот -- пропущено" % i for i in range(1, 12)], "файл /home/користувач/MD-UV390UKR/satellites.txt")
            p._redraw_slots()
            res = lp.run_all(app, sizes=((1024, 768),), keys=["satellites"], doc_states=(None, mk))
            lines = lp.format_report(res)
            check(not lines, "U7 [%s]: «Супутники» обрізано в %d місцях:\n  %s" % (fs.label(sc), len(lines), "\n  ".join(l[:230] for l in lines[:10])))
        finally:
            try:
                app.update()
            except Exception:  # noqa: BLE001
                pass
            app.destroy()


def main():
    try:
        import tkinter  # noqa: F401
        have = bool(os.environ.get("DISPLAY"))
    except ImportError:
        have = False
    if not have:
        print("test_r54_ui: нема tkinter/DISPLAY -- GUI-частину пропущено")
        return 0
    for t in (test_u1_u6, test_u7_layout):
        try:
            t()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILS.append("%s: виняток %r" % (t.__name__, e))
    if FAILS:
        print("\nПРОВАЛІВ: %d" % len(FAILS))
        return 1
    print("test_r54_ui: усе гаразд (%d перевірок)." % PASSED[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
