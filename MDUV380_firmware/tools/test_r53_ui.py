#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R53 (Tk): кнопки «Вище ↑ / Нижче ↓», Ctrl+↑ / Ctrl+↓ і перетягування в таблицях каналів, контактів, зон і списків прийому.

U1  стан кнопок: без кодплага / без вибраного запису / перший / середній / останній запис / активний фільтр;
U2  кнопка зсуває запис, виділення йде за записом, документ позначено «змінено», посилання на місці (за вмістом);
U3  Ctrl+↑ / Ctrl+↓ у таблиці; на межі -- без змін і без помилки; Ctrl+↑ / Ctrl+↓ у списку «У зоні» / «У списку» = «Вгору / Вниз» для членів;
U4  перетягування: подіями миші (натиснути, потягнути, відпустити) і прямим викликом drop_on;
U5  активний фільтр: порядок не змінюється, є пояснення;
U6  повідомлення після зсуву каналу згадує нові номери; підказка розділу пояснює, що порядок = номери;
U7  верстка нових кнопок при масштабі 100 / 125 / 150 % (система й DejaVu Sans): нічого не обрізано в чотирьох розділах (повний прохід усіх розділів -- test_r50fix.py S1).
Запуск: xvfb-run -a python3.12 tools/test_r53_ui.py"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FAILS = []

PANELS = (("channels", "channel"), ("contacts", "contact"), ("zones", "zone"), ("tglists", "tg"))


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def make_doc(seed=3):
    import test_r36 as t36
    import test_r53 as t53
    import cps_csv as cc
    from cps_ui import document as D
    doc = t36.doc_factory()()
    img = t53.world(seed)
    doc.image = cc.Image(img.eeprom, img.flash, doc.base)
    doc._origin_snap = D._snap(doc.image)
    doc._saved = (D._snap(doc.image), 0, [])
    doc.modified = False
    return doc


def new_app(sc=None):
    import font_scenarios as fs
    import test_r36 as t36
    spath = os.path.join(tempfile.mkdtemp(prefix="r53ui_"), "ui.json")
    os.environ["TYT_CPS_SETTINGS"] = spath
    app = t36.make_app(spath)
    if sc is not None:
        fs.apply(app, sc)
    t36.spin(app, 0.3)
    return app


def names(doc, kind):
    import reorder as ro
    import table_edit as te
    nm = dict(te.entity_names(doc.image, kind))
    return [nm[i] for i in ro.idents(doc.image, kind)]


def select(panel, ident):
    for item, i in panel._item_ident.items():
        if i == ident:
            panel.tree.selection_set(item)
            panel.tree.see(item)
            panel.update()
            return True
    return False


def state(btn):
    return str(btn.cget("state"))


def test_u1_u6():
    import layout_probe as lp
    import reorder as ro
    import test_r53 as t53
    app = new_app()
    try:
        # --- без кодплага: кнопки є і вимкнені ---
        app.show("channels")
        lp.spin(app, 0.3)
        p = app.get_panel("channels")
        check(hasattr(p, "btn_item_up") and hasattr(p, "btn_item_down"), "U1: кнопки «Вище / Нижче» є")
        check(state(p.btn_item_up) == "disabled" and state(p.btn_item_down) == "disabled", "U1: без кодплага кнопки вимкнені")
        check("Вище" in p.btn_item_up.cget("text") and "Нижче" in p.btn_item_down.cget("text"), "U1: підписи кнопок")
        doc = make_doc()
        app.set_document(doc)
        lp.spin(app, 0.4)
        for key, kind in PANELS:
            app.show(key)
            lp.spin(app, 0.4)
            p = app.get_panel(key)
            ids = ro.idents(doc.image, kind)
            check(p.reorderable, "U1 %s: порядок змінюється" % key)
            p.tree.selection_remove(*p.tree.selection())
            p.sel = None
            p.after_refresh()
            check(state(p.btn_item_up) == "disabled" and state(p.btn_item_down) == "disabled", "U1 %s: без вибраного запису кнопки вимкнені" % key)
            select(p, ids[0])
            check(state(p.btn_item_up) == "disabled" and state(p.btn_item_down) == "normal", "U1 %s: перший запис: вище -- ні, нижче -- так" % key)
            select(p, ids[len(ids) // 2])
            check(state(p.btn_item_up) == "normal" and state(p.btn_item_down) == "normal", "U1 %s: середній запис: обидві" % key)
            select(p, ids[-1])
            check(state(p.btn_item_up) == "normal" and state(p.btn_item_down) == "disabled", "U1 %s: останній запис: вище -- так, нижче -- ні" % key)
            # --- U2: кнопка ---
            ids = ro.idents(doc.image, kind)
            mid = ids[3]
            select(p, mid)
            before_names = names(doc, kind)
            nm = before_names[3]
            before_ref = t53.resolve(doc.image)
            p.btn_item_up.invoke()
            lp.spin(app, 0.2)
            after = names(doc, kind)
            exp = list(before_names)
            exp[2], exp[3] = exp[3], exp[2]
            check(after == exp, "U2 %s: кнопка «Вище» міняє місцями із сусідом: %r" % (key, after[:5]))
            check(doc.modified, "U2 %s: документ позначено зміненим" % key)
            check(t53.resolve(doc.image) == before_ref, "U2 %s: посилання на ті самі за вмістом записи" % key)
            sel_name = dict((i, n) for i, n in __import__("table_edit").entity_names(doc.image, kind)).get(p.sel)
            check(sel_name == nm, "U2 %s: виділено той самий запис (%r, а не %r)" % (key, sel_name, nm))
            check(len(p.tree.selection()) == 1, "U2 %s: у таблиці виділено рівно один рядок" % key)
            p.btn_item_down.invoke()
            lp.spin(app, 0.2)
            check(names(doc, kind) == before_names, "U2 %s: «Нижче» повертає порядок" % key)
            # --- U3: Ctrl+↑ / Ctrl+↓ ---
            select(p, ro.idents(doc.image, kind)[4])
            p.tree.focus_force()
            p.update()
            p.tree.event_generate("<Control-Up>")
            lp.spin(app, 0.2)
            exp = list(before_names)
            exp[3], exp[4] = exp[4], exp[3]
            check(names(doc, kind) == exp, "U3 %s: Ctrl+↑ у таблиці" % key)
            p.tree.event_generate("<Control-Down>")
            lp.spin(app, 0.2)
            check(names(doc, kind) == before_names, "U3 %s: Ctrl+↓ у таблиці" % key)
            # межі: Ctrl+↑ на першому, Ctrl+↓ на останньому -- без змін і без помилки
            select(p, ro.idents(doc.image, kind)[0])
            p.tree.event_generate("<Control-Up>")
            lp.spin(app, 0.2)
            select(p, ro.idents(doc.image, kind)[-1])
            p.tree.event_generate("<Control-Down>")
            lp.spin(app, 0.2)
            check(names(doc, kind) == before_names, "U3 %s: на межах Ctrl+↑ / Ctrl+↓ нічого не міняють" % key)
            # --- U4: перетягування ---
            ids = ro.idents(doc.image, kind)
            select(p, ids[0])
            items = {i: it for it, i in p._item_ident.items()}
            bb0, bb1 = p.tree.bbox(items[ids[0]]), p.tree.bbox(items[ids[3]])
            if bb0 and bb1:
                x = bb0[0] + 10
                y0, y1 = bb0[1] + bb0[3] // 2, bb1[1] + bb1[3] // 2
                p.tree.event_generate("<ButtonPress-1>", x=x, y=y0)
                p.tree.event_generate("<B1-Motion>", x=x, y=(y0 + y1) // 2)
                p.tree.event_generate("<B1-Motion>", x=x, y=y1)
                p.update()
                check(p._drop_item == items[ids[3]], "U4 %s: під час перетягування підсвічено рядок призначення" % key)
                p.tree.event_generate("<ButtonRelease-1>", x=x, y=y1)
                lp.spin(app, 0.2)
                exp = list(before_names)
                exp.insert(3, exp.pop(0))
                check(names(doc, kind) == exp, "U4 %s: перетягування мишею переносить запис: %r" % (key, names(doc, kind)[:5]))
                check(p._drop_item is None and str(p.tree.cget("cursor")) in ("", "{}"), "U4 %s: підсвічення й курсор прибрано" % key)
            else:
                check(False, "U4 %s: рядки таблиці не видно -- перетягування не перевірено" % key)
            ids = ro.idents(doc.image, kind)
            p.drop_on(ids[5], ids[1])
            lp.spin(app, 0.2)
            check(t53.resolve(doc.image) == before_ref, "U4 %s: після перетягувань посилання на місці" % key)
            # простий клік без руху -- не змінює порядок
            order_now = names(doc, kind)
            items = {i: it for it, i in p._item_ident.items()}
            bb = p.tree.bbox(items[ro.idents(doc.image, kind)[2]])
            p.tree.event_generate("<ButtonPress-1>", x=bb[0] + 10, y=bb[1] + 4)
            p.tree.event_generate("<ButtonRelease-1>", x=bb[0] + 10, y=bb[1] + 4)
            lp.spin(app, 0.2)
            check(names(doc, kind) == order_now, "U4 %s: клік без руху порядок не міняє" % key)
            # --- U5: фільтр ---
            order_now = names(doc, kind)
            p._filter.set("1")
            lp.spin(app, 0.2)
            if p.tree.get_children():
                select(p, p._item_ident[p.tree.get_children()[0]])
            check(state(p.btn_item_up) == "disabled" and state(p.btn_item_down) == "disabled", "U5 %s: з активним фільтром кнопки вимкнені" % key)
            p._on_reorder(1)
            p.tree.event_generate("<Control-Down>")
            lp.spin(app, 0.2)
            check(names(doc, kind) == order_now, "U5 %s: з активним фільтром порядок не змінюється" % key)
            check("фільтр" in p.msg.cget("text"), "U5 %s: є пояснення про фільтр: %r" % (key, p.msg.cget("text")))
            p._filter.set("")
            lp.spin(app, 0.2)
            # --- підказка розділу ---
            check("Нижче" in p.hint_text and "Ctrl" in p.hint_text, "U6 %s: підказка розділу згадує кнопки й Ctrl+↑/↓" % key)
        check("НОМЕРИ" in app.get_panel("channels").hint_text and "Всі канали" in app.get_panel("channels").hint_text,
              "U6: підказка каналів пояснює, що порядок = номери, і згадує «Всі канали»")
        # --- U6: повідомлення про нові номери ---
        app.show("channels")
        p = app.get_panel("channels")
        ids = ro.idents(doc.image, "channel")
        select(p, ids[5])
        p.btn_item_up.invoke()
        lp.spin(app, 0.2)
        txt = p.msg.cget("text")
        check("№%d" % ids[4] in txt and "№%d" % ids[5] in txt, "U6: повідомлення називає старий і новий номер каналу: %r" % txt)
        # --- U3б: Ctrl+↑ / ↓ у списку членів ---
        app.show("zones")
        p = app.get_panel("zones")
        select(p, ro.idents(doc.image, "zone")[0])
        lp.spin(app, 0.3)
        mem0 = list(p._cur_nums)
        check(len(mem0) >= 2, "U3б: у першій зоні є що пересувати")
        p.cur_lb.selection_clear(0, "end")
        p.cur_lb.selection_set(1)
        p.cur_lb.focus_force()
        p.update()
        p.cur_lb.event_generate("<Control-Up>")
        lp.spin(app, 0.2)
        exp = list(mem0)
        exp[0], exp[1] = exp[1], exp[0]
        check(list(p._cur_nums) == exp, "U3б: Ctrl+↑ у списку «У зоні» піднімає канал: %r -> %r" % (mem0, p._cur_nums))
        p.cur_lb.event_generate("<Control-Down>")
        lp.spin(app, 0.2)
        check(list(p._cur_nums) == mem0, "U3б: Ctrl+↓ повертає")
    finally:
        try:
            app.update()
        except Exception:  # noqa: BLE001
            pass
        app.destroy()


def test_u7_layout():
    import font_scenarios as fs
    import layout_probe as lp
    import tkinter as tk
    root = tk.Tk()
    scs = [sc for sc in fs.scenarios(root, families=(None, "DejaVu Sans")) if sc[1] in (100, 125, 150)]
    root.destroy()
    check({p for _f, p in scs} == {100, 125, 150}, "U7: сценарії охоплюють 100/125/150 %%: %r" % (scs,))
    for sc in scs:
        app = new_app(sc)
        try:
            app.set_document(make_doc())
            lp.spin(app, 0.4)
            for key, _kind in PANELS:
                app.show(key)
                lp.spin(app, 0.5)
                p = app.get_panel(key)
                bad = lp.probe_panel(app, key)
                check(not bad, "U7 [%s] %s: обрізано: %r" % (fs.label(sc), key, bad[:2]))
                for b in (p.btn_item_up, p.btn_item_down):
                    check(b.winfo_viewable() and not lp.probe_widget(b), "U7 [%s] %s: кнопка «%s» видима й не обрізана" % (fs.label(sc), key, b.cget("text")))
                check(p.btn_item_up.winfo_reqwidth() == p.btn_add.winfo_reqwidth() == p.btn_item_down.winfo_reqwidth(), "U7 [%s] %s: кнопки однакової ширини" % (fs.label(sc), key))
        finally:
            try:
                app.update()
            except Exception:  # noqa: BLE001
                pass
            app.destroy()


def main():
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("test_r53_ui: нема tkinter -- перевірки Tk пропущено")
        return 0
    for t in (test_u1_u6, test_u7_layout):
        print("--", t.__name__)
        t()
    print("ПРОВАЛІВ: %d" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
