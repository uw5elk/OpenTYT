# -*- coding: utf-8 -*-
"""CPS-fix3: сітка символів APRS (W1), злита панель APRS і два шляхи запису (W3), ключ AES у каналі й прибране з вікна (див. також test_cps_edit.py,
test_cps_ui.py). Запуск: xvfb-run -a python3 tools/test_cps_fix3.py (без дисплея GUI-частина друкує «ПРОПУЩЕНО»)."""
import os
import re
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import aprs_symbols as asym              # noqa: E402
import codeplug_edit as ced              # noqa: E402
import test_cps_csv as tc                # noqa: E402

FAILS = []
C_FILE = os.path.join(HERE, "..", "application", "source", "functions", "aprs_icons.c")


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def firmware_icons():
    """{(таблиця, код): 72 байти} з application/source/functions/aprs_icons.c: індекс iconNo + пули A і B."""
    text = open(C_FILE, encoding="utf-8").read()
    count_a = int(re.search(r"#define ICON_COUNT_A\s+(\d+)", text).group(1))
    idx = re.search(r"iconNo\[2\]\[94\]\s*=\s*\{(.*?)\n\};", text, re.S).group(1)
    tables = re.findall(r"\{\s*/\* таблиця [^*]*\*/(.*?)\n\t\}", idx, re.S)
    nums = [[(0xFF if t.strip() == "ICON_NONE" else int(t)) for t in re.findall(r"ICON_NONE|\d+", body)] for body in tables]
    pools = []
    for name in ("iconPoolA", "iconPoolB"):
        m = re.search(r"%s\[\]\[72\]\s*=\s*\{(.*?)\n\};" % name, text, re.S)
        pools += [bytes(int(h, 16) for h in re.findall(r"0x([0-9A-Fa-f]{2})", blk)) for blk in re.findall(r"\{ /\* №\d+ \*/(.*?)\n\t\}", m.group(1), re.S)]
    out = {}
    for ti, tch in enumerate(("/", "\\")):
        for k, no in enumerate(nums[ti]):
            if no != 0xFF:
                out[(tch, k + 0x21)] = pools[no]
    return out, count_a


def test_symbol_data():
    fw, count_a = firmware_icons()
    check(len(fw) == len(asym.ICONS) == 170, "кодів у прошивці й у даних CPS: %d / %d" % (len(fw), len(asym.ICONS)))
    bad = [k for k, v in asym.ICONS.items() if bytes.fromhex(v[1]) != fw.get((k[0], ord(k[1])))]
    check(not bad, "зображення CPS збігаються з aprs_icons.c байт у байт; розбіжні: %r" % bad[:5])
    rows = asym.decode(asym.ICONS["/>"][1])
    check(len(rows) == 24 and all(len(r) == 24 for r in rows) and any("#" in r for r in rows), "декодування дає 24x24 з пікселями")
    check(asym.table_char(47) == "/" and asym.table_char(92) == "\\" and asym.table_char(ord("5")) == "\\" and asym.table_char(ord("a")) is None,
          "таблиці: «/» і «\\», накладки 0-9/A-Z -- додаткова (як aprsIconFind), решта -- нема")
    check("Авто" in asym.symbol_text(47, ord(">")) or "авто" in asym.symbol_text(47, ord(">")), "підпис містить назву з txt: %s" % asym.symbol_text(47, ord(">")))
    check("накладка '5'" in asym.symbol_text(ord("5"), ord("#")), "підпис накладки")


def _all(w):
    yield w
    for c in w.winfo_children():
        yield from _all(c)


def _spin(app, n=3):
    for _ in range(n):
        app.update()


def test_gui():
    try:
        import tkinter as tk
    except ImportError:
        print("ПРОПУЩЕНО (GUI): нема tkinter")
        return
    if not os.environ.get("DISPLAY"):
        print("ПРОПУЩЕНО (GUI): нема DISPLAY")
        return
    import tkinter.messagebox as mb
    from cps_ui.app import CpsApp
    from cps_ui.settings import Settings

    tmp = tempfile.mkdtemp(prefix="cpsfix3_")
    spath = os.path.join(tmp, "ui.json")
    os.environ["TYT_CPS_SETTINGS"] = spath
    os.environ["HOME"] = tmp
    app = CpsApp(settings=Settings(spath), autoprobe=False)
    errors = []
    mb.showinfo = lambda *a, **k: None
    mb.showerror = lambda *a, **k: errors.append(a)
    try:
        app.geometry("1200x900")
        app.update()
        # --- V4.1: одна панель APRS у «Кодплаг», пункту в «Налаштування рації» нема ---
        tree = app.tree
        grp_keys = {g: list(tree.get_children(g)) for g in tree.get_children()}
        check("aprs" in grp_keys.get("grp_codeplug", []) and "aprs" not in grp_keys.get("grp_settings", []) and "aprs_slots" not in sum(grp_keys.values(), []),
              "V4.1: APRS лише в «Кодплаг»: %r" % grp_keys)
        # без документа: станція показує підказку, бікон -- кнопки вимкнені
        app.show("aprs")
        _spin(app)
        ap = app.get_panel("aprs")
        st = ap.station
        check(st.hint.winfo_manager() == "pack", "без документа: підказка «Відкрийте кодплаг…» у блоці станції")
        check(str(ap.write_beacon_btn.cget("state")) == "disabled" and str(ap.read_btn.cget("state")) == "disabled", "без рації: кнопки бікона вимкнені")
        # --- V4.2: два чітко відокремлені блоки ---
        # R50-fix: заголовок рамки скорочено (довгий не вміщувався на крупному шрифті) -- дію «Записати кодплаг у рацію» названо підписом усередині блоку
        inner = " ".join(str(w.cget("text")) for w in st.winfo_children() if w.winfo_class() == "TLabel")
        check("документ" in st.cget("text").lower() and "Записати кодплаг у рацію" in inner, "V4.2: блок станції підписано як частину документа: %s | %s" % (st.cget("text"), inner[:120]))
        check("РАЦІЮ негайно" in ap.radio_box.cget("text") and "НЕ частина документа" in ap.radio_box.cget("text"), "V4.2: блок бікона підписано: %s" % ap.radio_box.cget("text"))
        texts = [w.cget("text") for w in _all(ap.radio_box) if w.winfo_class() == "TLabel"]
        check(any("перезапусти рацію" in t.lower() for t in texts), "V4.4: підказка про перезапуск лишилась")
        # --- документ ---
        spi = tc.make_fixture_spi()
        _cp, data = tc.codeplug_of(spi)
        src = os.path.join(tmp, "orig.zip")
        with open(src, "wb") as f:
            f.write(data)
        check(app.doc_open_file(src), "відкрито з бекапу")
        app.show("aprs")
        _spin(app)
        check(st.hint.winfo_manager() == "" and len(st.tree.get_children()) == 1, "з документом: слот у списку")
        # --- V2.4: іконка поруч із числами ---
        st.vars["icon_table"].set("47")
        st.vars["icon"].set("62")
        _spin(app)
        check(st.symbol_preview.cget("image") != "" and "авто" in st.symbol_info.cget("text").lower(), "V2.4: поруч із полями іконка й підпис: %s" % st.symbol_info.cget("text"))
        st.vars["icon"].set("34")
        _spin(app)
        check("немає в наборі рації" in st.symbol_info.cget("text") and st.symbol_preview.cget("image") == "", "Y1.3: код без зображення: пояснено словами: %s" % st.symbol_info.cget("text"))
        st.vars["icon"].set("0")
        _spin(app)
        check("не обрано" in st.symbol_info.cget("text"), "Y1.3: код 0 -- «Символ не обрано»")
        # Y1.1: числових полів символу нема взагалі
        num_entries = [w for w in _all(st.form) if w.winfo_class() == "TEntry" and str(w.cget("textvariable")) in (str(st.vars["icon_table"]), str(st.vars["icon"]))]
        check(not num_entries and "icon" not in st.entries and "icon_table" not in st.entries, "Y1.1: у слоті нема полів вводу таблиці й символу")
        check(any(w.winfo_class() == "TButton" and w.cget("text") == "Обрати символ..." for w in _all(st.form)), "Y1.1: лишилась кнопка «Обрати символ...»")

        # --- W1: сітка кладе в поля ті самі числа, що й ручний ввід ---
        def drive(table_radio, code, then="ok"):
            """Знайти відкрите вікно вибору, перемкнути таблицю, клікнути піктограму коду й натиснути «Обрати»."""
            def run():
                win = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)][-1]
                try:
                    body(win)
                except Exception as e:  # noqa: BLE001 -- щоб модальне вікно не зависло, якщо драйвер помилився
                    FAILS.append("драйвер сітки: %r" % (e,))
                    win.destroy()

            def body(win):
                kids = list(_all(win))
                if table_radio is not None:
                    rb = [w for w in kids if w.winfo_class() == "TRadiobutton" and (table_radio in str(w.cget("text")))][0]
                    rb.invoke()
                    win.update()
                    kids = list(_all(win))
                labs = [w for w in kids if w.winfo_class() == "Label"]
                tab = "\\" if table_radio and table_radio.startswith("Дод") else "/"
                order = [c for c, _n in asym.codes(tab)]
                check(len(labs) == len(order), "сітка таблиці «%s»: %d іконок із %d" % (tab, len(labs), len(order)))
                labs[order.index(code)].event_generate("<Enter>")
                win.update()
                info = [w for w in kids if w.winfo_class() == "TLabel" and "код" in str(w.cget("text"))]
                check(info and ("(код %d)" % code) in info[0].cget("text"), "під курсором -- код і назва: %r" % [i.cget("text") for i in info])
                labs[order.index(code)].event_generate("<Button-1>")
                win.update()
                if then == "ok":
                    [w for w in kids if w.winfo_class() == "TButton" and w.cget("text") == "Обрати"][0].invoke()
                else:
                    [w for w in kids if w.winfo_class() == "TButton" and w.cget("text") == "Скасувати"][0].invoke()
            app.after(150, run)
        drive("Основна", ord("["))              # перемикач у першу таблицю; «[» -- людина
        st._on_pick_symbol()
        grid_vals = (st.vars["icon_table"].get(), st.vars["icon"].get())
        check(grid_vals == ("47", str(ord("["))), "W1: сітка (основна, «[») поклала в поля %r" % (grid_vals,))
        st._on_apply()
        _spin(app)
        rec = dict(app.doc.image.aprs())[0]
        rv = ced.aprs_values(rec)
        check((rv["icon_table"], rv["icon"]) == ("47", str(ord("["))) and app.doc.modified, "W1: у документі (47, 91), документ змінено: %r" % ((rv["icon_table"], rv["icon"]),))
        # те саме вручну на другому слоті: порівняння записів
        st._on_new()
        _spin(app)
        st.vars["name"].set("РУЧ")
        st.vars["icon_table"].set("92")
        st.vars["icon"].set(str(ord("#")))
        st._on_apply()
        _spin(app)
        manual = dict(app.doc.image.aprs())[1]
        st._on_new()
        _spin(app)
        st.vars["name"].set("СІТКА")
        drive("Додаткова", ord("#"))
        st._on_pick_symbol()
        st._on_apply()
        _spin(app)
        grid = dict(app.doc.image.aprs())[2]
        # Z4: уся 64-байтова запис слота після вибору в сітці = запис, який дає той самий набір значень «вручну» (API без сітки)
        base = app.doc.image
        again = ced.apply_aprs_slot(base, 2, dict(ced.aprs_values(grid), icon_table="92", icon=str(ord("#")))).image
        check(bytes(dict(again.aprs())[2]) == bytes(grid), "Z4: запис слота з сітки == запис із тих самих чисел без сітки (64 байти)")
        gv, mv = ced.aprs_values(grid), ced.aprs_values(manual)
        check((gv["icon_table"], gv["icon"]) == (mv["icon_table"], mv["icon"]) == ("92", str(ord("#"))),
              "W1: додаткова таблиця -- у записі ті самі числа, що при ручному вводі: %r / %r" % ((gv["icon_table"], gv["icon"]), (mv["icon_table"], mv["icon"])))
        # накладка зберігається, скасування нічого не міняє
        st.vars["icon_table"].set(str(ord("5")))
        st.vars["icon"].set(str(ord("#")))
        drive("Додаткова", ord("*"))
        st._on_pick_symbol()
        check(st.vars["icon_table"].get() == str(ord("5")) and st.vars["icon"].get() == str(ord("*")), "накладка «5» лишилась при виборі з додаткової таблиці")
        drive("Основна", ord("<"), then="cancel")
        st._on_pick_symbol()
        check(st.vars["icon_table"].get() == str(ord("5")) and st.vars["icon"].get() == str(ord("*")), "«Скасувати» поля не змінює")

        # --- W3: слот -> документ «змінено»; бікон -> документ не змінюється, пишеться в рацію ---
        import gui_dialogs as gd
        gd.confirm_dialog = lambda *a, **k: True
        app.doc_discard()
        _spin(app)
        app.show("aprs")
        _spin(app)
        check(not app.doc.modified, "W3: після «Відкинути» документ не змінено")
        ap.vars["fast"].set("45")
        ap.vars["mode"].set(ap.vars["mode"].get())
        ap.vars["power"].set("3")
        _spin(app)
        check(not app.doc.modified, "W3: правка полів бікона документ не змінює")
        calls = []
        ap._write_worker = lambda d, sql: calls.append((d, sql))
        app.conn.state, app.conn.port, app.conn.searched = "found", "COM9", True
        app.conn.info = {"radioType": 6, "gitRevision": "x", "buildDateTime": "x", "flashId": 1, "features": 0}
        app._refresh_all()
        _spin(app)
        check(str(ap.write_beacon_btn.cget("state")) == "normal", "з рацією: «Записати бікон і шумодав у рацію» доступна")
        ap._on_write_beacon()
        for _ in range(100):
            app.update()
            time.sleep(0.05)
            if calls and not app.busy:
                break
        check(len(calls) == 1 and calls[0][0]["fast"] == 45 and calls[0][0]["power"] == 3, "W3: бікон пишеться в рацію негайно власною кнопкою: %r" % (calls[:1],))
        _spin(app, 6)
        check(not app.doc.modified, "W3: запис бікона не робить документ зміненим")
        st.tree.selection_set(st.tree.get_children()[0])
        _spin(app)
        st.vars["comment"].set("Changed comment")
        _spin(app)
        st._on_apply()
        _spin(app)
        check(app.doc.modified, "W3: зміна слота ставить «змінено» документа (busy=%r, can=%r, msg=%r, cur=%r)" % (app.busy, st._can_apply, st.msg.cget("text"), st.current))
        check(len(calls) == 1, "W3: зміна слота рацію не чіпає")
    finally:
        app.destroy()
    check(not errors, "GUI: messagebox.showerror не викликався: %r" % (errors[:2],))


def main():
    import faulthandler
    faulthandler.dump_traceback_later(50, exit=True)
    for t in (test_symbol_data, test_gui):
        try:
            t()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILS.append("%s: виняток %r" % (t.__name__, e))
    if FAILS:
        print("test_cps_fix3: ПРОВАЛЕНО перевірок: %d" % len(FAILS))
        return 1
    print("test_cps_fix3: усе гаразд (іконки = таблиця прошивки, сітка символів, злита панель APRS, два шляхи запису).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
