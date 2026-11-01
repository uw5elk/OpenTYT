#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R55 (Tk): розділ «Супутники» -- субтон лише на передачу, вік TLE, підтвердження запису зі старими елементами, дата перевірки таблиці, верстка.

V1  підписи форми: «Субтон передачі, Гц» і «Субтон взведення (передача), Гц», підказка «Приймання завжди без субтону»; поля субтона приймання НЕМАЄ ніде (підписи, змінні панелі, параметри apply_form);
V2  підсумок слота й підтвердження запису показують субтон як «TX 67» (SO-50: ще «взведення TX 74.4»), без «RX ... Гц»;
V3  вік TLE у таблиці слотів: колонка «Вік TLE», теги none / stale / old, кольори warn / err, підпис під таблицею (поріг 7 / 30 діб, ISS 3 доби);
V4  вік показано і для слотів, ПРОЧИТАНИХ З РАЦІЇ (apply_read), не лише доданих;
V5  запис: без старих елементів -- одне підтвердження; зі старими -- окреме явне підтвердження (перелік слотів і діб), «Скасувати» зупиняє запис, «Записати все одно» НЕ блокує;
V6  дата таблиці: «вбудована, перевірена 2026-11-01 (N діб тому)»; за 90 діб -- нічого, за 91 -- жовте нагадування з адресою AMSAT; своя таблиця -- дата зміни файла;
V7  мутанти: пороги віку, особливий поріг ISS, поле субтона приймання -- тест їх бачить;
V8  верстка при масштабі 100 / 125 / 150 % (шрифт системи й DejaVu Sans) з найгіршим вмістом: старі слоти, довгі підсумки, нагадування про таблицю.
Запуск: xvfb-run -a python3.12 tools/test_r55_ui.py"""
import datetime
import inspect
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FAILS = []
PASSED = [0]
NOW = datetime.datetime(2026, 11, 1)
DAY_NOW = 305                      # 2026-11-01 -- 305-й день року


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)
    else:
        PASSED[0] += 1


def tles_aged(items):
    """items: [(назва TLE, NORAD, вік у добах)] -> розібрані TLE з епохою NOW - вік."""
    import sat_tle as st
    import test_r35 as t35
    out = []
    for nm, n, age in items:
        a, l1, l2 = t35.mk_tle(nm, n, 26, float(DAY_NOW - age))
        out.append(st.parse_tle_text("\n".join((a, l1, l2)))[0][0])
    return out


# Очікувані результати -- ЧИСЛАМИ, не через константи модуля (щоб мутант константи був помітний).
# (назва в TLE, NORAD, вік, очікуваний тег, очікуваний текст віку)
AGES = [
    ("AO-91", 43017, 7, "", "7 дн."),
    ("SO-50", 27607, 8, "stale", "8 дн. застарів"),
    ("LILACSAT", 40908, 30, "stale", "30 дн. застарів"),
    ("PO-101", 43678, 31, "old", "31 дн. старий"),
]
ISS_AGES = [(3, "", "3 дн."), (4, "stale", "4 дн. застарів")]


def ui_tags(p):
    """-> {ім'я слота: (тег, текст віку)}."""
    out = {}
    for i in p.slot_tree.get_children():
        tags = p.slot_tree.item(i, "tags")
        tag = tags[0] if tags else ""
        out[p.slot_tree.set(i, "name")] = (tag, p.slot_tree.set(i, "age"))
    return out


def age_mismatches(p, iss_age):
    """Порівняти таблицю слотів із літеральними очікуваннями. -> список розбіжностей (порожній -- усе збігається)."""
    got = ui_tags(p)
    bad = []
    names = {43017: "AO-91", 27607: "SO-50", 40908: "LilacSat", 43678: "PO-101"}
    for _nm, n, _age, tag, txt in AGES:
        if got.get(names[n]) != (tag, txt):
            bad.append((names[n], got.get(names[n]), (tag, txt)))
    exp_iss = [x for x in ISS_AGES if x[0] == iss_age][0]
    if got.get("ISS") != (exp_iss[1], exp_iss[2]):
        bad.append(("ISS", got.get("ISS"), (exp_iss[1], exp_iss[2])))
    return bad


def rx_tone_leaks(p):
    """Усе, що вказує на поле субтона ПРИЙМАННЯ у формі: підписи, змінні панелі, параметри apply_form. -> список знахідок."""
    import re
    import test_r54_ui as t54
    found = []
    for t in t54.labels_of(p):
        low = t.lower()
        if "субтон" in low and ("прийман" in low and "завжди без" not in low):
            found.append("підпис: " + t)
        if re.search(r"\brx\b.*(субтон|ctcss)", low) or "субтон rx" in low:
            found.append("підпис: " + t)
    for k in vars(p):
        kl = k.lower()
        if ("rx" in kl and ("ctcss" in kl or "tone" in kl or "css" in kl)) or "rxtone" in kl or "rx_tone" in kl:
            found.append("атрибут: " + k)
    for prm in inspect.signature(p.apply_form).parameters:
        pl = prm.lower()
        if ("rx" in pl and ("ctcss" in pl or "tone" in pl)) or pl in ("rxtone", "rx_tone", "rxctcss"):
            found.append("параметр apply_form: " + prm)
    return found


class Dlg2:
    """Підміна підтверджень із різними відповідями за заголовком вікна."""

    def __init__(self, answers):
        import gui_dialogs as gd
        self.gd = gd
        self.answers = answers          # {заголовок: True/False}
        self.shown = []                 # [(заголовок, текст)]
        self._old = gd.confirm_dialog
        gd.confirm_dialog = self._fn

    def _fn(self, parent, title, text, yes="Так", no="Ні"):
        self.shown.append((title, text))
        return self.answers.get(title, False)

    def restore(self):
        self.gd.confirm_dialog = self._old


def test_v1_v6():
    import layout_probe as lp
    import sat_table as stb
    import sat_tle as st
    import test_r54_ui as t54
    import gui_theme as gt
    app = t54.new_app()
    dlg = t54.Dialogs()
    try:
        app.show("satellites")
        lp.spin(app, 0.4)
        p = app.get_panel("satellites")
        p.now_override = NOW
        txt = "\n".join(t54.labels_of(p))

        # --- V1: форма ---
        check("Субтон передачі, Гц" in txt and "Субтон взведення (передача), Гц" in txt, "V1: підписи форми про передачу")
        check("Приймання завжди без субтону" in txt, "V1: підказка про приймання без субтону")
        check("Субтон, Гц" not in txt and "Субтон взведення, Гц" not in txt, "V1: старих підписів без «передачі» нема")
        check(rx_tone_leaks(p) == [], "V1: поля субтона приймання нема ніде: %r" % rx_tone_leaks(p))

        # --- V2: підсумок слота й підтвердження запису ---
        p.set_tles(tles_aged([("SAUDISAT 1C (SO-50)", 27607, 2), ("ISS (ZARYA)", 25544, 2)]), (), "тест")
        p.add_chosen(p.chosen_tles() if False else None, replace=True) if False else None
        p.slots = []
        p.add_chosen(tles_aged([("SAUDISAT 1C (SO-50)", 27607, 2), ("ISS (ZARYA)", 25544, 2)]), replace=True)
        iid = {p.slot_tree.set(i, "name"): i for i in p.slot_tree.get_children()}
        so = p.slot_tree.set(iid["SO-50"], "freq")
        iss = p.slot_tree.set(iid["ISS"], "freq")
        check("TX 67 Гц" in so and "взведення TX 74.4 Гц" in so, "V2: SO-50 в таблиці слотів: %s" % so)
        check("TX 67 Гц" in iss and "взведення" not in iss, "V2: ISS в таблиці слотів: %s" % iss)
        check("RX 67" not in so and "RX 67" not in iss and "приймання 67" not in so.lower(), "V2: субтон не подано як RX")
        p.radio_state = st.ST_OK
        calls = []
        old_run = p.shell.run_task
        p.shell.run_task = lambda *a, **k: (calls.append(a), True)[1]
        d2 = Dlg2({"Записати супутники в рацію?": True})
        try:
            p._on_write()
        finally:
            d2.restore()
            p.shell.run_task = old_run
        wr = [t for ttl, t in d2.shown if ttl == "Записати супутники в рацію?"]
        check(len(wr) == 1 and "TX 67 Гц" in wr[0] and "взведення TX 74.4 Гц" in wr[0], "V2: підтвердження запису показує «TX 67»: %s" % (wr[0][:300] if wr else d2.shown))
        check(len(d2.shown) == 1 and len(calls) == 1, "V5: без старих елементів -- одне підтвердження, запис запущено (%d вікон, %d запусків)" % (len(d2.shown), len(calls)))

        # --- V3: вік TLE, пороги, кольори ---
        for iss_age in (3, 4):
            p.slots = []
            p.add_chosen(tles_aged([(a[0], a[1], a[2]) for a in AGES] + [("ISS (ZARYA)", 25544, iss_age)]), replace=True)
            lp.spin(app, 0.1)
            check(age_mismatches(p, iss_age) == [], "V3: вік і теги (ISS %d діб): %r" % (iss_age, age_mismatches(p, iss_age)))
        check("Вік TLE" in [p.slot_tree.heading(c, "text") for c in p.slot_tree["columns"]], "V3: колонка «Вік TLE»")
        check(str(p.slot_tree.tag_configure("stale", "foreground")) == str(gt.P["warn"]) and str(p.slot_tree.tag_configure("old", "foreground")) == str(gt.P["err"]),
              "V3: жовтий -- warn, червоний -- err")
        lab = p.stale_label.cget("text")
        check("Старі елементи, понад 30 діб" in lab and "PO-101 (31 дн.)" in lab and "SO-50 (8 дн.)" in lab and "ISS (4 дн.)" in lab, "V3: підпис під таблицею: %s" % lab)
        check(str(p.stale_label.cget("foreground")) == str(gt.P["err"]), "V3: є червоні -- підпис червоний")
        p.slots = []
        p.add_chosen(tles_aged([("SAUDISAT 1C (SO-50)", 27607, 10)]), replace=True)
        check(str(p.stale_label.cget("foreground")) == str(gt.P["warn"]) and "Застаріли" in p.stale_label.cget("text"), "V3: лише жовті -- підпис жовтий")
        p.slots = []
        p.add_chosen(tles_aged([("SAUDISAT 1C (SO-50)", 27607, 1)]), replace=True)
        check(p.stale_label.cget("text") == "", "V3: усе свіже -- підпису нема")

        # --- V4: прочитані з рації ---
        src = tles_aged([("SAUDISAT 1C (SO-50)", 27607, 20), ("PO-101", 43678, 45)])
        p.slots = []
        p.add_chosen(src, replace=True)
        blk_slots = [s.copy() for s in p.slots]
        blk = st.parse_block(st.build_block(blk_slots)) if hasattr(st, "parse_block") else None
        if blk is None:
            blk = type("B", (), {"slots": blk_slots, "hidden": 0})()
        p.slots = []
        p.apply_read(st.ST_OK, blk)
        got = ui_tags(p)
        check(got.get("SO-50") == ("stale", "20 дн. застарів") and got.get("PO-101") == ("old", "45 дн. старий"), "V4: прочитані з рації слоти мають вік: %r" % (got,))

        # --- V5: запис зі старими елементами ---
        p.radio_state = st.ST_OK
        for ans_old, ans_main, want_run, want_main in ((False, True, 0, 0), (True, True, 1, 1), (True, False, 0, 1)):
            calls.clear()
            d2 = Dlg2({"Старі елементи орбіти": ans_old, "Записати супутники в рацію?": ans_main})
            p.shell.run_task = lambda *a, **k: (calls.append(a), True)[1]
            try:
                p._on_write()
            finally:
                d2.restore()
                p.shell.run_task = old_run
            titles = [t for t, _x in d2.shown]
            check(titles and titles[0] == "Старі елементи орбіти" and titles.count("Старі елементи орбіти") == 1, "V5: перше -- окреме підтвердження про старі елементи (%r)" % titles)
            check(len(calls) == want_run and titles.count("Записати супутники в рацію?") == want_main, "V5: відповіді (старі=%s, запис=%s) -> запусків %d, основних вікон %d (є %d, %d)" % (
                ans_old, ans_main, want_run, want_main, len(calls), titles.count("Записати супутники в рацію?")))
        old_txt = [t for ttl, t in d2.shown if ttl == "Старі елементи орбіти"][0]
        check("PO-101 -- 45 діб" in old_txt and "SO-50" not in old_txt and "старші за 30 діб" in old_txt, "V5: у вікні лише червоні слоти з числом діб: %s" % old_txt)
        main_txt = [t for ttl, t in d2.shown if ttl == "Записати супутники в рацію?"][0]
        check("Старі елементи, понад 30 діб" in main_txt and "PO-101" in main_txt, "V5: основне підтвердження теж називає червоні слоти")

        # --- V6: дата таблиці ---
        p.load_builtin_table()
        tl = p.table_label.cget("text")
        check("вбудована, перевірена 2026-11-01 (0 діб тому)" in tl, "V6: підпис вбудованої: %s" % tl)
        check(p.recheck_label.cget("text") == "", "V6: у день звірки нагадування нема")
        for days, want in ((90, False), (91, True)):
            p.now_override = NOW + datetime.timedelta(days=days)
            p.load_builtin_table()
            rt = p.recheck_label.cget("text")
            check(bool(rt) == want, "V6: %d діб -- нагадування %s: %r" % (days, "є" if want else "нема", rt))
            if want:
                check("91 діб" in rt and "https://www.amsat.org/live-fm-satellites/" in rt and "FM Satellites" in rt, "V6: нагадування має число діб і адресу AMSAT: %s" % rt)
                check(str(p.recheck_label.cget("foreground")) == str(gt.P["warn"]), "V6: нагадування жовте")
        p.now_override = NOW
        # своя таблиця: дата зміни файла
        path = os.path.join(tempfile.mkdtemp(prefix="r55tbl_"), "satellites.txt")
        open(path, "wb").write(open(os.path.join(HERE, "satellites.txt"), "rb").read())
        mt = (NOW - datetime.timedelta(days=100)).replace(tzinfo=datetime.timezone.utc).timestamp()
        os.utime(path, (mt, mt))
        check(p.load_table_file(path), "V6: свою таблицю прочитано")
        tl = p.table_label.cget("text")
        check("змінено" in tl and "(100 діб тому)" in tl and "вбудована" not in tl, "V6: своя таблиця -- дата зміни файла: %s" % tl)
        check("100 діб" in p.recheck_label.cget("text"), "V6: для своєї таблиці нагадування за 100 діб: %r" % p.recheck_label.cget("text"))
        p._on_builtin_table()
    finally:
        dlg.restore()
        try:
            app.update()
        except Exception:  # noqa: BLE001
            pass
        app.destroy()


def test_v7_mutants():
    import layout_probe as lp
    import sat_tle as st
    import tkinter as tk
    from tkinter import ttk
    import test_r54_ui as t54
    app = t54.new_app()
    dlg = t54.Dialogs()
    try:
        app.show("satellites")
        lp.spin(app, 0.3)
        p = app.get_panel("satellites")
        p.now_override = NOW

        def fill(iss_age=4):
            p.slots = []
            p.add_chosen(tles_aged([(a[0], a[1], a[2]) for a in AGES] + [("ISS (ZARYA)", 25544, iss_age)]), replace=True)

        fill()
        check(age_mismatches(p, 4) == [], "V7: базова лінія збігається")
        # мутанти порогів: тест має бачити зміну
        for const, val in (("TLE_AGE_GOOD_DAYS", 6), ("TLE_AGE_GOOD_DAYS", 8), ("TLE_AGE_STALE_DAYS", 29), ("TLE_AGE_STALE_DAYS", 31), ("TLE_AGE_GOOD_DAYS_ISS", 4), ("TLE_AGE_GOOD_DAYS_ISS", 2)):
            old = getattr(st, const)
            setattr(st, const, val)
            try:
                p._redraw_slots()
                # ISS_GOOD=2 видно лише на 3-й добі (там очікується «без позначки»), решта -- на 4-й
                iss_age = 3 if val == 2 else 4
                if iss_age == 3:
                    fill(3)
                check(age_mismatches(p, iss_age) != [], "V7/мутант: %s = %d -- тест це бачить" % (const, val))
            finally:
                setattr(st, const, old)
        fill()
        check(age_mismatches(p, 4) == [], "V7: після мутантів стан відновлено")
        # мутант «ISS як усі»
        old_is = st.is_iss
        st.is_iss = lambda slot, norad=None: False
        try:
            p._redraw_slots()
            check(age_mismatches(p, 4) != [], "V7/мутант: без суворості для ISS на 4-й добі -- тест це бачить")
        finally:
            st.is_iss = old_is
        p._redraw_slots()
        # мутант «поле субтона приймання з'явилось»
        check(rx_tone_leaks(p) == [], "V7: базова лінія -- субтона приймання нема")
        lbl = ttk.Label(p, text="Субтон приймання, Гц")
        check(rx_tone_leaks(p) != [], "V7/мутант: підпис «Субтон приймання, Гц» -- тест це бачить")
        lbl.destroy()
        lbl = ttk.Label(p, text="RX CTCSS, Гц")
        check(rx_tone_leaks(p) != [], "V7/мутант: підпис «RX CTCSS, Гц» -- тест це бачить")
        lbl.destroy()
        p.rx_ctcss_var = tk.StringVar()
        check(rx_tone_leaks(p) != [], "V7/мутант: змінна rx_ctcss_var -- тест це бачить")
        del p.rx_ctcss_var
        check(rx_tone_leaks(p) == [], "V7: після мутантів знову чисто")
        # мутант «тон показано як RX»
        s = p.slots[0]
        s.ctcss = 670
        old_ft = st.Slot.freq_text
        st.Slot.freq_text = lambda self: old_ft(self).replace("TX 67 Гц", "RX 67 Гц")
        try:
            p._redraw_slots()
            iid = p.slot_tree.get_children()[0]
            check("TX 67" not in p.slot_tree.set(iid, "freq"), "V7/мутант: тон як «RX 67» -- перевірка «TX 67» це бачить")
        finally:
            st.Slot.freq_text = old_ft
        p._redraw_slots()
        iid = p.slot_tree.get_children()[0]
        check("TX 67 Гц" in p.slot_tree.set(iid, "freq"), "V7: після мутантів «TX 67 Гц» повернулось")
    finally:
        dlg.restore()
        try:
            app.update()
        except Exception:  # noqa: BLE001
            pass
        app.destroy()


def test_v8_layout():
    import font_scenarios as fs
    import layout_probe as lp
    import sat_table as stb
    import sat_tle as st
    import test_r36 as t36
    import test_r50fix as t50
    import test_r54_ui as t54
    import tkinter as tk
    mk = t36.doc_factory()
    root = tk.Tk()
    scs = t50.sc_list(root)
    root.destroy()
    check(len(scs) >= 3 and {pc for _f, pc in scs} == {100, 125, 150}, "V8: сценарії охоплюють 100/125/150 %%: %r" % (scs,))
    for sc in scs:
        app = t54.new_app(sc)
        try:
            p = app.get_panel("satellites")
            p.now_override = NOW
            items = [("SAT%d" % i, 40000 + i, 3 + i * 3) for i in range(20)]
            p.slots = []
            p.add_chosen(tles_aged([(nm, n, age) for nm, n, age in items]), replace=True)
            for s in p.slots:
                s.rx1, s.tx1, s.ctcss, s.arm, s.rx2, s.tx2, s.rx3 = 145_960_000, 435_250_000, 670, 744, 145_825_000, 145_825_000, 145_800_000
            p.slots += [st.Slot("ZERO1"), st.Slot("ZERO2"), st.Slot("BAD0", rx1=100_000_000, tx1=300_000_000)]
            d0 = stb.builtin_verified_date() - datetime.timedelta(days=200)   # давня звірка -> нагадування
            p.set_table(stb.default_rows()[0], ["рядок %d: тестове зауваження про некоректний рядок таблиці частот -- пропущено" % i for i in range(1, 8)], "вбудована", verified=d0, kind="вбудована")
            p._redraw_slots()
            res = lp.run_all(app, sizes=((1024, 768),), keys=["satellites"], doc_states=(None, mk))
            lines = lp.format_report(res)
            check(not lines, "V8 [%s]: «Супутники» обрізано в %d місцях:\n  %s" % (fs.label(sc), len(lines), "\n  ".join(l[:230] for l in lines[:10])))
            check("діб тому" in p.table_label.cget("text") and p.recheck_label.cget("text") != "", "V8 [%s]: у найгіршому вмісті є і дата таблиці, і нагадування" % fs.label(sc))
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
        print("test_r55_ui: нема tkinter/DISPLAY -- GUI-частину пропущено")
        return 0
    for t in (test_v1_v6, test_v7_mutants, test_v8_layout):
        try:
            t()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILS.append("%s: виняток %r" % (t.__name__, e))
    if FAILS:
        print("\nПРОВАЛІВ: %d" % len(FAILS))
        return 1
    print("test_r55_ui: усе гаразд (%d перевірок)." % PASSED[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
