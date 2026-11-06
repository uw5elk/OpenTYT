#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R59/R60 (Tk): розділ «Роумінг» (10 списків) і колонка «Роум.» / поле «Роум. список» у «Каналах».

V1  розділ є в дереві «Кодплаг» одразу після «Каналів»; без кодплага кнопки списку вимкнені, кнопки рації залежать від рації;
V2  список: усі канали з номером списку, лічильники по списках, «Лише канали цього списку», вибір списку, фільтр; примітка біля каналу, який прошивка пропустить;
V3  «Додати виділені до списку» / «Прибрати зі списків» / «Очистити список...» міняють ЛИШЕ байт списку (документ позначено зміненим, виділення збережено); без виділення -- підказка;
    канал з іншого списку -- питання про ПЕРЕНОС (відмова нічого не міняє); «Перенести старі позначки R59 у список 1» -- з питанням, лише коли вони є;
V4  «Канали»: колонка «Роум.» (номер списку) і випадний список «Роум. список» у формі «Опції» -- вибір міняє документ (байт 37), решта запису не змінюється;
V5  рація (підміна): читання підставляє значення; запис передає значення форми в roam_cfg.write_state; погане число -- вікно помилки й НІЯКОГО запису;
    після читання «блока нема» при наявних прапорцях -- попередження про блок із пропозицією зняти позначки;
V6  попередження на панелі: увімкнено при <2 каналів; аналог / симплекс; чисто -- порожньо;
V7  верстка (сценарії шрифтів × 100/125/150 %): «Роумінг» і «Канали» без обрізання з кодплагом і без.
Запуск: xvfb-run -a python3.12 tools/test_r59_ui.py"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FAILS = []
PASSED = [0]


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)
    else:
        PASSED[0] += 1


def new_app(sc=None):
    import font_scenarios as fs
    import test_r36 as t36
    spath = os.path.join(tempfile.mkdtemp(prefix="r59ui_"), "ui.json")
    os.environ["TYT_CPS_SETTINGS"] = spath
    app = t36.make_app(spath)
    if sc is not None:
        fs.apply(app, sc)
    t36.spin(app, 0.3)
    return app


def make_doc(on=(1, 2, 5), image=None):
    import cps_csv as cc
    import test_r36 as t36
    import test_r59 as t59
    from cps_ui import document as D
    doc = t36.doc_factory()()
    img = image or t59.roam_world(on=on)
    doc.image = cc.Image(img.eeprom, img.flash, doc.base)
    doc._origin_snap = D._snap(doc.image)
    doc._saved = (D._snap(doc.image), 0, [])
    doc.modified = False
    return doc


def state(btn):
    return str(btn.cget("state"))


def rows(p):
    return [p.tree.item(i, "values") for i in p.tree.get_children()]


def pick(p, nums):
    items = [i for i, n in p._item_num.items() if n in nums]
    p.tree.selection_set(*items)
    p.update()


class Dialogs:
    def __init__(self, answer=True):
        from tkinter import messagebox
        self.mb = messagebox
        self.errors, self.asks = [], []
        self.answer = answer
        self._old = (messagebox.showerror, messagebox.askokcancel)
        messagebox.showerror = lambda t, m, **k: self.errors.append(m)
        messagebox.askokcancel = lambda t, m, **k: (self.asks.append(m), self.answer)[1]

    def restore(self):
        self.mb.showerror, self.mb.askokcancel = self._old


def test_v1_v6():
    import cps_link
    import layout_probe as lp
    import roam_cfg as rc
    import table_edit as te
    import test_r59 as t59
    app = new_app()
    dlg = Dialogs()
    try:
        app.show("roam")
        lp.spin(app, 0.4)
        p = app.get_panel("roam")
        keys = [k for k in app._defs]
        check(keys.index("roam") == keys.index("channels") + 1, "V1: «Роумінг» іде одразу після «Каналів»: %r" % keys[keys.index("channels"):keys.index("channels") + 3])
        check(p.title == "Роумінг" and p.doc_panel, "V1: назва «Роумінг», панель документа")
        for b in (p.add_btn, p.rem_btn, p.clr_btn):
            check(state(b) == "disabled", "V1: без кодплага кнопка списку вимкнена: %s" % b.cget("text"))
        check("Відкрийте кодплаг" in p.count_label.cget("text"), "V1: без кодплага підказка замість лічильника")
        check(rows(p) == [], "V1: таблиця порожня")
        # --- кодплаг ---
        doc = make_doc()
        app.set_document(doc)
        lp.spin(app, 0.4)
        for b in (p.add_btn, p.rem_btn, p.clr_btn):
            check(state(b) == "normal", "V2: з кодплагом кнопка списку доступна: %s" % b.cget("text"))
        r = rows(p)
        check(len(r) == 5 and [str(x[0]) for x in r] == ["1", "2", "3", "4", "5"], "V2: усі 5 каналів: %r" % [x[0] for x in r])
        check([x[5] for x in r] == ["1", "1", "", "", "1"], "V2: номер списку рівно на 1, 2, 5: %r" % [x[5] for x in r])
        check("1: 3" in p.count_label.cget("text") and "Усього: 3" in p.count_label.cget("text"), "V2: лічильник по списках: %s" % p.count_label.cget("text"))
        check(p.cb_list.cget("values")[0] == "1 (3)" and p.cb_list.cget("values")[1] == "2 (0)" and len(p.cb_list.cget("values")) == 10, "V2: у випадному списку 10 списків із лічильниками: %r" % (p.cb_list.cget("values"),))
        p.v_only.set(True)
        p._fill()
        check([str(x[0]) for x in rows(p)] == ["1", "2", "5"], "V2: «Лише канали цього списку» (список 1): %r" % [x[0] for x in rows(p)])
        p.v_list.set("2 (0)")
        p._fill()
        check(rows(p) == [] and p.current_list() == 2, "V2: вибір списку 2 -- порожньо: %r" % rows(p))
        p.v_list.set("1 (3)")
        p._fill()
        p.v_only.set(False)
        p.v_filter.set("RM4")
        lp.spin(app, 0.2)
        check([str(x[0]) for x in rows(p)] == ["4"], "V2: фільтр за назвою: %r" % [x[0] for x in rows(p)])
        p.v_filter.set("")
        lp.spin(app, 0.2)
        # --- примітка про каналі, які прошивка пропустить ---
        doc2 = make_doc(on=(1, 3, 4))
        app.set_document(doc2)
        lp.spin(app, 0.3)
        notes = {int(x[0]): x[6] for x in rows(p)}
        check("симплекс" in notes[3] and "аналог" in notes[4] and notes[1] == "" and notes[2] == "", "V2: примітки лише для каналів зі списку: %r" % notes)
        app.set_document(doc)
        lp.spin(app, 0.3)
        # --- V3: додати/прибрати ---
        p.v_only.set(False)
        p._fill()
        p._set_selected(True)
        check("Спершу виділіть" in p.msg.cget("text") and not doc.modified, "V3: без виділення -- підказка і документ не змінено")
        pick(p, [3, 4])
        p.add_btn.invoke()
        lp.spin(app, 0.2)
        check(te.roam_numbers(doc.image, 1) == [1, 2, 3, 4, 5] and doc.modified, "V3: додано 3 і 4 до списку 1: %r" % te.roam_numbers(doc.image))
        check(len(dlg.asks) == 0, "V3: канали без списку додаються без питання")
        check(set(p.selected_numbers()) == {3, 4}, "V3: виділення збережено: %r" % p.selected_numbers())
        check("1: 5" in p.count_label.cget("text"), "V3: лічильник оновлено: %s" % p.count_label.cget("text"))
        pick(p, [1, 2])
        p.rem_btn.invoke()
        lp.spin(app, 0.2)
        check(te.roam_numbers(doc.image) == [3, 4, 5], "V3: прибрано 1 і 2: %r" % te.roam_numbers(doc.image))
        before = t59.rec_of(doc.image, 3)
        pick(p, [3])
        p.add_btn.invoke()
        check(t59.rec_of(doc.image, 3) == before, "V3: повторне додавання нічого не змінює")
        # --- перенос між списками ---
        p.v_list.set("2 (0)")
        pick(p, [3, 1])
        n_ask = len(dlg.asks)
        dlg.answer = False
        p.add_btn.invoke()
        check(len(dlg.asks) == n_ask + 1 and "ПЕРЕНЕСЕНО" in dlg.asks[-1] and "№3" in dlg.asks[-1], "V3: канал 3 уже в списку 1 -- питання про перенос: %r" % dlg.asks[-1:])
        check(te.roam_numbers(doc.image, 1) == [3, 4, 5] and te.roam_numbers(doc.image, 2) == [], "V3: відмова від переносу нічого не змінила")
        dlg.answer = True
        p.add_btn.invoke()
        lp.spin(app, 0.2)
        check(te.roam_numbers(doc.image, 2) == [1, 3] and te.roam_numbers(doc.image, 1) == [4, 5], "V3: після підтвердження 1 і 3 у списку 2 (1 з нього не було -- без питання): %r %r" % (te.roam_numbers(doc.image, 1), te.roam_numbers(doc.image, 2)))
        # --- очищення вибраного списку ---
        p.v_list.set("1 (2)")
        dlg.answer = False
        n_ask = len(dlg.asks)
        p.clr_btn.invoke()
        check(te.roam_numbers(doc.image, 1) == [4, 5] and len(dlg.asks) == n_ask + 1, "V3: «Очистити список...» без підтвердження нічого не робить")
        dlg.answer = True
        p.clr_btn.invoke()
        lp.spin(app, 0.2)
        check(te.roam_numbers(doc.image, 1) == [] and te.roam_numbers(doc.image, 2) == [1, 3], "V3: «Очистити список...» зняла лише вибраний список: %r %r" % (te.roam_numbers(doc.image, 1), te.roam_numbers(doc.image, 2)))
        check(state(p.mig_btn) == "disabled", "V3: старих позначок нема -- кнопка перенесення вимкнена")
        # --- перенесення старих позначок R59 ---
        old_img = t59.set_flag(t59.set_flag(doc.image, 4, True), 5, True)
        doc.apply(type("Res", (), {"image": old_img, "changed": [("Канали", "тест")], "added": [], "removed": [], "warnings": [], "any_change": lambda self: True})())
        lp.spin(app, 0.2)
        check(state(p.mig_btn) == "normal" and "СТАРИМ" in p.warn_label.cget("text"), "V3: є старі позначки -- кнопка доступна, попередження показано: %r" % p.warn_label.cget("text"))
        dlg.answer = False
        p.mig_btn.invoke()
        check(rc.legacy_channels(doc.image) == [4, 5], "V3: перенесення без підтвердження нічого не робить")
        dlg.answer = True
        p.mig_btn.invoke()
        lp.spin(app, 0.2)
        check(rc.legacy_channels(doc.image) == [] and te.roam_numbers(doc.image, 1) == [4, 5], "V3: старі позначки -> список 1: %r" % te.roam_numbers(doc.image, 1))
        doc.apply(te.channels_set_roam(doc.image, te.roam_numbers(doc.image), 0))
        doc.apply(te.channels_set_roam(doc.image, [1, 2, 5], 1))
        lp.spin(app, 0.2)
        # --- V4: «Канали» ---
        app.show("channels")
        lp.spin(app, 0.4)
        ch = app.get_panel("channels")
        check(ch.columns[-1][:2] == ("roam", "Роум."), "V4: колонка «Роум.» у таблиці каналів")
        vals = {int(ch.tree.item(i, "values")[0]): ch.tree.item(i, "values")[-1] for i in ch.tree.get_children()}
        check(vals[1] == "1" and vals[2] == "1" and vals[5] == "1" and vals[3] == "" and vals[4] == "", "V4: номер списку на каналах зі списку: %r" % vals)
        check("RoamList" in ch.fields and ch.fields["RoamList"]["type"] == "roamlist" and "Roam" not in ch.fields, "V4: випадний список «Роум. список» у формі")
        check(list(ch.fields["RoamList"]["widget"].cget("values")) == ["0 -- без списку"] + [str(k) for k in range(1, 11)], "V4: у ньому «0 -- без списку», 1..10")
        for item, ident in ch._item_ident.items():
            if ident == 3:
                ch.tree.selection_set(item)
        ch.update()
        lp.spin(app, 0.3)
        check(ch.sel == 3 and ch.fields["RoamList"]["var"].get() == "0 -- без списку", "V4: форма каналу №3: без списку")
        old = t59.rec_of(doc.image, 3)
        ch.fields["RoamList"]["var"].set("7")
        ch.commit("RoamList")
        lp.spin(app, 0.2)
        new = t59.rec_of(doc.image, 3)
        check(te.roam_numbers(doc.image, 7) == [3] and te.roam_numbers(doc.image, 1) == [1, 2, 5], "V4: вибір «7» у формі поклав канал №3 у список 7: %r" % te.roam_numbers(doc.image))
        check([i for i in range(56) if old[i] != new[i]] == [37] and new[37] == 0xC7, "V4: змінився лише байт 37 (0xC7)")
        ch.load_form()
        check(ch.fields["RoamList"]["var"].get() == "7", "V4: форма показує 7 після перезавантаження")
        ch.fields["RoamList"]["var"].set("0 -- без списку")
        ch.commit("RoamList")
        check(te.roam_numbers(doc.image) == [1, 2, 5] and t59.rec_of(doc.image, 3)[37] == 0, "V4: і зняття (байт 37 = 0)")
        # --- V5: рація (підміна) ---
        app.show("roam")
        lp.spin(app, 0.3)
        store = {"state": {"version": 1, "enabled": True, "max_hops": 4}, "raw": b"ROAM\x01\x01\x04\x00"}
        writes = []
        old = (cps_link.open_radio, rc.read_state, rc.write_state, p.shell.run_task)
        cps_link.open_radio = lambda: type("Ser", (), {"close": lambda self: None})()
        rc.read_state = lambda ser: (store["state"], store["raw"])

        def fake_write(ser, en, hops, safety_dir=None, now=None, log=print):
            rc.check_hops(hops)
            writes.append((en, hops))
            store["state"] = {"version": 1, "enabled": en, "max_hops": hops}
            store["raw"] = rc.build_payload(en, hops)
            return "записано (тест)", None
        rc.write_state = fake_write

        def sync(fn, status, on_done=None, **k):
            fn()
            lp.spin(app, 0.1)
            return True
        p.shell.run_task = sync
        try:
            p._on_read()
            check(p.v_enabled.get() is True and p.v_hops.get() == "4", "V5: після читання форма = блок з рації: %r %r" % (p.v_enabled.get(), p.v_hops.get()))
            check("Прочитано" in p.radio_label.cget("text"), "V5: підпис стану: %s" % p.radio_label.cget("text"))
            p.v_hops.set("3")
            p.v_enabled.set(False)
            p._on_write()
            check(writes == [(False, 3)], "V5: запис передав значення форми: %r" % writes)
            check(store["raw"] == b"ROAM\x01\x00\x03\x00", "V5: блок у «рації» оновлено")
            for bad in ("0", "6", "abc", ""):
                p.v_hops.set(bad)
                n0 = len(dlg.errors)
                p._on_write()
                check(len(dlg.errors) == n0 + 1 and writes == [(False, 3)], "V5: макс. стрибків %r -- вікно помилки і жодного запису" % bad)
            # блока в рації нема, а прапорці є
            store["state"], store["raw"] = None, None
            p._on_read()
            txt = p.warn_label.cget("text")
            check("блока налаштувань" in txt and "Прибрати всі" not in txt and p.v_enabled.get() is False and p.v_hops.get() == "2",
                  "V5: блока нема -- форма типова, попередження про прапорці: %r" % txt)
            check("Блока налаштувань у рації немає" in p.radio_label.cget("text"), "V5: підпис про відсутній блок")
            # недійсний блок
            store["state"], store["raw"] = None, b"JUNKJUNK"
            p._on_read()
            check("недійсний" in p.radio_label.cget("text"), "V5: недійсний блок названо")
            # після запису попередження зникає
            p.v_hops.set("2")
            p.v_enabled.set(True)
            p._on_write()
            check("блока налаштувань" not in p.warn_label.cget("text"), "V5: після запису блока попередження про відсутній блок зникло: %r" % p.warn_label.cget("text"))
        finally:
            cps_link.open_radio, rc.read_state, rc.write_state, p.shell.run_task = old
        # --- V6: попередження ---
        p.v_enabled.set(True)
        doc.apply(te.channels_set_roam(doc.image, te.roam_numbers(doc.image), 0))
        doc.apply(te.channels_set_roam(doc.image, [1], 1))
        p._fill()
        t = p.warn_label.cget("text")
        check("жоден список" in t, "V6: увімкнено, 1 канал: %r" % t)
        doc.apply(te.channels_set_roam(doc.image, [1, 2, 5], 1))
        p._fill()
        check(p.warn_label.cget("text") == "", "V6: чистий список -- без попереджень: %r" % p.warn_label.cget("text"))
        doc.apply(te.channels_set_roam(doc.image, [3, 4], 1))
        p._fill()
        t = p.warn_label.cget("text")
        check("№3" in t and "симплекс" in t and "№4" in t and "аналог" in t, "V6: симплекс і аналог: %r" % t)
        p.v_enabled.set(False)
        p.refresh_warnings()
        check("жоден список" not in p.warn_label.cget("text"), "V6: вимкнено -- про кількість не нагадуємо")
    finally:
        dlg.restore()
        app.destroy()


def test_v7_layout():
    import font_scenarios as fs
    import layout_probe as lp
    import test_r50fix as t50
    import tkinter as tk
    root = tk.Tk()
    scs = t50.sc_list(root)
    root.destroy()
    check(len(scs) >= 3 and {pc for _f, pc in scs} == {100, 125, 150}, "V7: сценарії охоплюють 100/125/150 %%: %r" % (scs,))
    for sc in scs:
        app = new_app(sc)
        try:
            doc = make_doc()
            res = lp.run_all(app, sizes=((1024, 768),), keys=["roam", "channels"], doc_states=(None, lambda: doc))
            lines = lp.format_report(res)
            check(not lines, "V7 [%s]: «Роумінг» і «Канали» обрізано в %d місцях:\n  %s" % (fs.label(sc), len(lines), "\n  ".join(l[:230] for l in lines[:10])))
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
        print("test_r59_ui: нема tkinter/DISPLAY -- GUI-частину пропущено")
        return 0
    for t in (test_v1_v6, test_v7_layout):
        try:
            t()
        except Exception as e:  # noqa: BLE001
            import traceback
            FAILS.append("%s: виняток %s: %s" % (t.__name__, type(e).__name__, e))
            traceback.print_exc()
    if FAILS:
        print("test_r59_ui: %d провалів" % len(FAILS))
        return 1
    print("test_r59_ui: усе гаразд (%d перевірок: 10 списків, перенос, кнопки, «Канали», рація, попередження, верстка)." % PASSED[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
