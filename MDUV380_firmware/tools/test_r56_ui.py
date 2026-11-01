#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R56 (Tk): розділ «Супутники» з однією кнопкою «Оновити супутники» і згорнутим «Детально ▸».

W1  головний вигляд: рядок стану рації, рядок таблиці, велика кнопка з реченням, «Детально ▸»; усе старе -- у згорнутому блоці й розгортається без втрат;
W2  потік кнопки з підміною мережі й рації: читання слотів, TLE, ОДНЕ вікно підсумку з п'яти рядків, запис безпечним шляхом (st.write_slots), перечитування, «Готово: N ...»;
W3  «Скасувати» і «Лише в документ» НІЧОГО не пишуть у рацію; без мережі -- текст «Немає зв'язку...» і нічого не змінено; без рації запис не пропонується;
W4  старі TLE -- кнопка «Записати все одно» без окремого другого підтвердження, запис НЕ заблоковано; помилки частот блокують запис;
W5  кеш: повторне натискання не робить запитів; нічого оновлювати -- вікно без вибору;
W6  МУТАНТИ: запис без підтвердження, «Лише в документ» як запис, зайве вікно -- тест їх бачить;
W7  верстка (шість сценаріїв шрифтів × 100/125/150 %): звичайний головний вигляд вміщується БЕЗ прокрутки при мінімальному розмірі вікна; з найгіршим вмістом (нагадування про таблицю,
    пропущені рядки) він може прокручуватись, але не обрізається; «Детально» розгортається без обрізання.
Запуск: xvfb-run -a python3.12 tools/test_r56_ui.py"""
import datetime
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FAILS = []
PASSED = [0]
NOW = datetime.datetime(2026, 11, 1)


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)
    else:
        PASSED[0] += 1


class Radio:
    """Підміна рації: зберігає блок слотів, рахує читання/запис."""

    def __init__(self, slots, state=None):
        import sat_tle as st
        self.st = st
        self.slots = [s.copy() for s in slots]
        self.state = state or st.ST_OK
        self.reads = 0
        self.writes = []                # знімки слотів, які записано

    def read(self):
        self.reads += 1
        return self.state, self.st.Block([s.copy() for s in self.slots])

    def write(self, ser, slots, safety_dir=None, now=None, log=print):
        self.writes.append([s.copy() for s in slots])
        self.slots = [s.copy() for s in slots]
        return "Супутники записані: %d (тест). Звірка читанням: OK." % len(slots), "/safety/x.bin"


class Dlgs:
    """Підміна вікон: що показано, які відповіді дати."""

    def __init__(self, choice=None):
        import gui_dialogs as gd
        from tkinter import messagebox
        self.gd, self.mb = gd, messagebox
        self.choice = choice            # "radio" | "doc" | "cancel" | None (закрити вікно)
        self.choices = []               # [(текст, [підписи кнопок])]
        self.texts = []                 # text_dialog
        self.confirms = []
        self.infos, self.errors = [], []
        self._old = (gd.choice_dialog, gd.confirm_dialog, gd.text_dialog, messagebox.showinfo, messagebox.showerror)
        gd.choice_dialog = lambda parent, title, text, buttons, default_index=0: (self.choices.append((text, [b[0] for b in buttons], [b[1] for b in buttons], default_index)), self.choice)[1]
        gd.confirm_dialog = lambda parent, title, text, yes="Так", no="Ні": (self.confirms.append(text), False)[1]
        gd.text_dialog = lambda parent, title, text, close="Закрити": self.texts.append(text)
        messagebox.showinfo = lambda t, m, **k: self.infos.append(m)
        messagebox.showerror = lambda t, m, **k: self.errors.append(m)

    def restore(self):
        (self.gd.choice_dialog, self.gd.confirm_dialog, self.gd.text_dialog, self.mb.showinfo, self.mb.showerror) = self._old


class Env:
    """Панель + підміни мережі/рації на один сценарій."""

    def __init__(self, app, p, radio, routes, found=True, choice="radio"):
        import cps_link
        import sat_tle as st
        import test_r56 as t56
        self.app, self.p, self.radio = app, p, radio
        self.cps, self.st = cps_link, st
        self.net = t56.Net(routes)
        self.d = Dlgs(choice)
        self.errors = []
        p.fetch_fn = self.net
        p.cache_dir = tempfile.mkdtemp(prefix="r56ui_c_")
        p.now_override = NOW
        app.conn.state = "found" if found else "absent"
        self._old = (cps_link.open_radio, st.write_slots, p.shell.run_task, p._read_radio)
        cps_link.open_radio = lambda: type("Ser", (), {"close": lambda self: None})()
        st.write_slots = radio.write
        p._read_radio = radio.read
        p.shell.run_task = self._sync
        p.slots, p.radio_state, p.base_bytes, p.radio_info = [], None, None, ""
        p._redraw_slots()

    def _sync(self, fn, status, on_done=None, **k):
        if self.p.shell.busy:
            return False
        try:
            r = fn()
        except Exception as e:  # noqa: BLE001
            self.errors.append(str(e))
            return True
        if on_done:
            on_done(r)
        return True

    def press(self):
        self.p._on_update_all()

    def restore(self):
        self.d.restore()
        (self.cps.open_radio, self.st.write_slots, self.p.shell.run_task, self.p._read_radio) = self._old
        self.p.fetch_fn = None


def lines_ok(text):
    return all(k in text for k in ("Оновлено TLE:", "Додано:", "Без змін:", "Немає TLE:"))


def routes_for(group_ages, extra=None):
    import sat_tle as st
    import test_r56 as t56
    r = {st.CELESTRAK_AMATEUR: t56.tle_text([(t56.NAMES[n], n, a) for n, a in group_ages]).encode()}
    r.update(extra or {})
    return r


def radio_slots():
    """У рації: AO-91 з ручною зміною RX1 і TLE 20 діб, свій MYSAT."""
    import sat_table as stb
    import test_r56 as t56
    by = {r.name: r for r in stb.default_rows()[0]}
    return [t56.slot_from("AO-91", 43017, 20, by["AO-91"], rx1=145_970_000), t56.slot_from("MYSAT", 43017, 5, None, rx1=145_500_000, tx1=145_500_000, ctcss=1000)]


GROUP = [(43017, 1), (61781, 1), (25544, 1), (40908, 2), (43678, 3), (27607, 3)]
EXTRA_OK = {}


def make_routes():
    import sat_tle as st
    import test_r56 as t56
    r = routes_for(GROUP)
    r[__import__("sat_update").CELESTRAK_CATNR % 59112] = t56.tle_text([("SONATE-2", 59112, 1)]).encode()
    return r


def test_w1_main():
    import test_r54_ui as t54
    import gui_theme as gt
    app = t54.new_app()
    dlg = t54.Dialogs()
    try:
        app.show("satellites")
        import layout_probe as lp
        lp.spin(app, 0.4)
        p = app.get_panel("satellites")
        p.now_override = NOW
        p.load_builtin_table()
        check(p.update_btn_all.cget("text") == "Оновити супутники" and str(p.update_btn_all.cget("style")) == "Big.TButton", "W1: велика кнопка «Оновити супутники»")
        check(p.radio_status_label.cget("text") == "Рація не прочитана", "W1: рядок стану: %r" % p.radio_status_label.cget("text"))
        check("вбудована, перевірена 2026-11-01 (0 діб тому)" in p.table_label.cget("text"), "W1: рядок таблиці: %s" % p.table_label.cget("text"))
        check(p.detail_btn.cget("text") == "Детально ▸" and not p.detail_open and not p.detail.winfo_ismapped(), "W1: «Детально ▸» згорнуто")
        shown = [w for w in lp.walk_viewable(p) if w.winfo_class() in ("Treeview", "TLabelframe", "TEntry")]
        check(not shown, "W1: у згорнутому вигляді не видно ні таблиць, ні полів, ні рамок (%d)" % len(shown))
        texts = t54.labels_of(p)
        check(any("Бере свіжі TLE" in t for t in texts), "W1: під кнопкою одне речення про те, що вона робить")
        p.toggle_detail()
        lp.spin(app, 0.3)
        check(p.detail_open and p.detail.winfo_ismapped() and p.detail_btn.cget("text") == "Детально ▾", "W1: «Детально» розгортається")
        allt = "\n".join(t54.labels_of(p))
        for need in ("1. Що в рації (25 слотів)", "2. Джерело елементів", "3. Таблиця частот", "4. Відбір і слоти", "Прочитати з рації", "Записати в рацію...", "Прибрати слот", "Застосувати до слота",
                     "Додати з таблиці", "Заповнити порожні слоти з таблиці", "Відкрити свою таблицю...", "Вбудована таблиця", "Додати вибрані у вільні слоти", "Замінити всі слоти вибраними",
                     "Оновити елементи наявних слотів за назвою", "Перевірити джерело", "Завантажити з мережі у файл...", "Відкрити файл TLE...", "Субтон передачі, Гц"):
            check(need in allt, "W1: у «Детально» збереглось: %s" % need)
        p.toggle_detail()
        check(not p.detail_open and not p.detail.winfo_ismapped(), "W1: повторне натискання знову згортає")
        # рядок таблиці з пропущеними рядками і нагадування займають місце лише коли є текст
        check(not p.recheck_label.winfo_ismapped(), "W1: порожнє нагадування не займає місця")
        p.now_override = NOW + datetime.timedelta(days=100)
        p.load_builtin_table()
        lp.spin(app, 0.2)
        check(p.recheck_label.winfo_ismapped() and "amsat.org" in p.recheck_label.cget("text"), "W1: нагадування з'являється в головному вигляді")
    finally:
        dlg.restore()
        try:
            app.update()
        except Exception:  # noqa: BLE001
            pass
        app.destroy()


def test_w2_w6_flow():
    import test_r54_ui as t54
    import sat_tle as st
    import sat_update as su
    import layout_probe as lp
    app = t54.new_app()
    try:
        app.show("satellites")
        lp.spin(app, 0.4)
        p = app.get_panel("satellites")
        p.load_builtin_table()

        # ---------- W2: усе гаразд, запис ----------
        env = Env(app, p, Radio(radio_slots()), make_routes(), found=True, choice="radio")
        try:
            check(p.radio_state is None and p.radio_status_label.cget("text") == "Рація не прочитана", "W2: до натискання рацію не прочитано")
            env.press()
            d = env.d
            check(not env.errors, "W2: без помилок: %r" % env.errors)
            check(len(d.choices) == 1 and not d.confirms and not d.texts, "W2: ОДНЕ вікно підсумку, жодного окремого підтвердження (%d вікон, %d підтверджень)" % (len(d.choices), len(d.confirms)))
            text, btns, vals, dflt = d.choices[0]
            check(lines_ok(text) and "Частоти відрізняються від таблиці" in text and "AO-91 (вік було 20 дн., стало 1 дн.)" in text, "W2: підсумок має п'ять рядків і вік нових TLE:\n" + text[:900])
            check(btns[:3] == ["Записати в рацію", "Лише в документ", "Скасувати"] and vals == ["radio", "doc", "cancel"] and btns[dflt] == "Скасувати", "W2: кнопки й безпечний фокус: %r %d" % (btns, dflt))
            check("повний знімок" in text and "страхову копію" in text.replace("файл-страхову копію", "страхову копію"), "W2: нагадування про знімок і страхову копію (перший запис за сесію)")
            check(env.radio.reads == 2 and len(env.radio.writes) == 1, "W2: читання до (1) і після запису (2), запис один: читань %d, записів %d" % (env.radio.reads, len(env.radio.writes)))
            w = env.radio.writes[0]
            by = {s.name: s for s in w}
            ao = by["AO-91"]
            check(ao.rx1 == 145_970_000 and abs(ao.age_days(NOW) - 1) < 0.01, "W2: AO-91: ручний RX1 лишився, TLE оновлено")
            check("MYSAT" in by and by["MYSAT"].ctcss == 1000, "W2: ручний слот поза таблицею записано без змін")
            check({"AO-123", "ISS", "LilacSat", "SO-50", "PO-101", "SONATE-2"} <= set(by) and "UmKA-1" not in by, "W2: додано з таблиці лише ті, для кого є TLE: %r" % sorted(by))
            check(any("Готово: %d супутників" % len(w) in m or "Готово: %d супутники" % len(w) in m for m in d.infos), "W2: після запису «Готово: N супутників, найстаріший TLE X діб»: %r" % (d.infos[-1][:120] if d.infos else d.infos))
            check(p.radio_state == st.ST_OK and not p.is_dirty() and "У рації: %d" % len(w) in p.radio_status_label.cget("text"), "W2: слоти перечитано з рації, рядок стану оновлено: %s" % p.radio_status_label.cget("text"))
            # --- W5: кеш: друге натискання в межах інтервалу ---
            calls = len(env.net.calls)
            d.choices.clear()
            d.texts.clear()
            env.press()
            check(len(env.net.calls) == calls, "W5: друге натискання -- жодного запиту в мережу (%d -> %d)" % (calls, len(env.net.calls)))
            check(not d.choices and len(d.texts) == 1 and "Оновлено TLE: нічого." in d.texts[0], "W5: нічого оновлювати -- вікно без вибору, запису нема: %r" % (d.texts[:1],))
            check(len(env.radio.writes) == 1, "W5: зайвого запису нема")
            # підказка про знімок -- один раз за сесію: на новому плані її вже немає
            env.p.slots = []
            p.radio_state = None
            p.base_bytes = None
            p._redraw_slots()
        finally:
            env.restore()

        # ---------- W3: скасувати ----------
        for choice in ("cancel", None):
            env = Env(app, p, Radio(radio_slots()), make_routes(), found=True, choice=choice)
            try:
                env.press()
                before = [s.pack() for s in env.radio.slots]
                check(len(env.d.choices) == 1 and not env.radio.writes and [s.pack() for s in p.slots] == before and not p.is_dirty(),
                      "W3: відповідь %r -- у рацію нічого, слоти не змінено (записів %d)" % (choice, len(env.radio.writes)))
            finally:
                env.restore()
        # ---------- W3: лише в документ ----------
        env = Env(app, p, Radio(radio_slots()), make_routes(), found=True, choice="doc")
        try:
            env.press()
            plan = p.last_plan
            check(not env.radio.writes and env.radio.reads == 1, "W3: «Лише в документ» -- у рацію нічого, читань 1 (записів %d, читань %d)" % (len(env.radio.writes), env.radio.reads))
            check([s.pack() for s in p.slots] == [s.pack() for s in plan.slots] and p.is_dirty(), "W3: слоти = план, є незаписані зміни")
            check("У рації: 2 супутники" in p.radio_status_label.cget("text") and "незаписані" in p.radio_status_label.cget("text"), "W3: рядок стану показує те, що в рації, і незаписані зміни: %s" % p.radio_status_label.cget("text"))
        finally:
            env.restore()
        # ---------- W3: без мережі ----------
        env = Env(app, p, Radio(radio_slots()), {st.CELESTRAK_AMATEUR: su.NetError("з'єднатися не вдалося: Network is unreachable")}, found=True, choice="radio")
        try:
            env.press()
            check(env.d.errors and "Немає зв'язку. Детально → відкрити файл TLE." in env.d.errors[-1] and "Нічого не змінено" in env.d.errors[-1], "W3: без мережі -- текст з брифу: %r" % (env.d.errors,))
            check(not env.d.choices and not env.radio.writes, "W3: без мережі вікна підсумку й запису нема")
            check(p.radio_state == st.ST_OK and "У рації: 2" in p.radio_status_label.cget("text"), "W3: прочитане з рації не втрачено: %s" % p.radio_status_label.cget("text"))
        finally:
            env.restore()
        # ---------- W3: без рації ----------
        env = Env(app, p, Radio(radio_slots()), make_routes(), found=False, choice="doc")
        try:
            env.press()
            text, btns, vals, _d = env.d.choices[0]
            check(env.radio.reads == 0 and "radio" not in vals and "Записати" not in " ".join(btns), "W3: без рації нічого не читаємо й запис не пропонуємо: %r" % btns)
            check("Рацію не знайдено -- запис не пропонується" in text, "W3: підсумок говорить про це")
            check(len(p.slots) == 7 and not env.radio.writes, "W3: результат лишився в слотах (%d)" % len(p.slots))
            env.d.errors.clear()
            p.update_apply_choice(p.last_plan, "radio")                      # страховка: навіть примусова відповідь «запис» без рації нічого не пише
            check(not env.radio.writes and env.d.errors, "W3: примусовий запис без рації відхилено (записів %d)" % len(env.radio.writes))
        finally:
            env.restore()

        # ---------- W4: старі TLE -- кнопка «Записати все одно», без другого підтвердження ----------
        import test_r56 as t56
        import sat_table as stb
        by = {r.name: r for r in stb.default_rows()[0]}
        old_slots = radio_slots() + [t56.slot_from("SO-50", 27607, 45, by["SO-50"])]
        routes = routes_for([(43017, 1), (61781, 1)])                            # SO-50 у файлі нема -- лишається старий
        env = Env(app, p, Radio(old_slots), routes, found=True, choice="radio")
        try:
            env.press()
            text, btns, vals, _d = env.d.choices[0]
            check(btns[0] == "Записати все одно (є старі TLE)" and "СТАРІ елементи" in text and "SO-50 (45 діб)" in text, "W4: старі TLE названо, кнопка явна: %r" % btns)
            check(not env.d.confirms and len(env.radio.writes) == 1, "W4: окремого другого підтвердження нема, запис НЕ заблоковано (записів %d, підтверджень %d)" % (len(env.radio.writes), len(env.d.confirms)))
        finally:
            env.restore()
        # ---------- W4: помилка частот блокує запис ----------
        bad_slots = [t56.slot_from("AO-91", 43017, 20, by["AO-91"], rx1=100_000_000)]
        env = Env(app, p, Radio(bad_slots), routes_for([(43017, 1), (61781, 1)]), found=True, choice="radio")
        try:
            env.press()
            text, btns, vals, _d = env.d.choices[0] if env.d.choices else ("", [], [], 0)
            check(env.d.choices and "radio" not in vals and "ПОМИЛКИ" in text and not env.radio.writes and not env.errors and env.d.errors, "W4: помилка частоти -- запис не пропонується: %r | ПОМИЛКИ в тексті %s | записів %d | %s" % (btns, "ПОМИЛКИ" in text, len(env.radio.writes), text[:700]))
        finally:
            env.restore()
        # ---------- зайнято ----------
        env = Env(app, p, Radio(radio_slots()), make_routes(), found=True, choice="radio")
        try:
            app.busy = True
            env.press()
            app.busy = False
            check(not env.net.calls and not env.d.choices, "W2: поки триває інша операція, кнопка нічого не робить")
        finally:
            app.busy = False
            env.restore()

        # ---------- W6: мутанти ----------
        def scenario_cancel():
            """-> список невдач сценарію «Скасувати»: у рацію не пишемо, вікно рівно одне."""
            e = Env(app, p, Radio(radio_slots()), make_routes(), found=True, choice="cancel")
            try:
                e.press()
                bad = []
                if e.radio.writes:
                    bad.append("запис при «Скасувати»")
                if len(e.d.choices) != 1:
                    bad.append("вікон підсумку не одне")
                return bad
            finally:
                e.restore()

        def scenario_doc():
            e = Env(app, p, Radio(radio_slots()), make_routes(), found=True, choice="doc")
            try:
                e.press()
                return ["запис при «Лише в документ»"] if e.radio.writes else []
            finally:
                e.restore()
        check(scenario_cancel() == [] and scenario_doc() == [], "W6: базові сценарії чисті")
        orig_choice = p.update_apply_choice
        p.update_apply_choice = lambda plan, choice: orig_choice(plan, "radio")                      # мутант: будь-яка відповідь = запис
        try:
            check(scenario_cancel() != [] and scenario_doc() != [], "W6/мутант: будь-яка відповідь вважається записом -- тест це бачить")
        finally:
            p.update_apply_choice = orig_choice
        orig_ask = p.update_ask
        p.update_ask = lambda res: orig_choice(su.build_plan(p.slots, p.table_rows, res.tles, NOW), "radio")      # мутант: запис без вікна підтвердження
        try:
            check(scenario_cancel() != [], "W6/мутант: запис без вікна підтвердження -- тест це бачить")
        finally:
            p.update_ask = orig_ask
        orig_apply = p.update_apply_choice
        p.update_apply_choice = lambda plan, choice: (orig_apply(plan, choice), orig_apply(plan, choice))[0] if choice == "radio" else orig_apply(plan, choice)
        try:
            e = Env(app, p, Radio(radio_slots()), make_routes(), found=True, choice="radio")
            try:
                e.press()
                check(len(e.radio.writes) != 1, "W6/мутант: подвійний запис -- перевірка «рівно один запис» це бачить (записів %d)" % len(e.radio.writes))
            finally:
                e.restore()
        finally:
            p.update_apply_choice = orig_apply
        # мутант: мережа не обробляється -- тест на «без мережі»
        orig_fetch = p.update_fetch

        def raising(rows, need_read):
            raise su.NetError("boom")
        p.update_fetch = raising
        try:
            e = Env(app, p, Radio(radio_slots()), make_routes(), found=True, choice="radio")
            try:
                e.press()
                check(e.errors and not e.d.errors, "W6/мутант: виняток мережі без обробки губить прочитане з рації -- тест це бачить")
            finally:
                e.restore()
        finally:
            p.update_fetch = orig_fetch
    finally:
        try:
            app.update()
        except Exception:  # noqa: BLE001
            pass
        app.destroy()


def test_w7_layout():
    import font_scenarios as fs
    import layout_probe as lp
    import sat_table as stb
    import sat_tle as st
    import test_r36 as t36
    import test_r50fix as t50
    import test_r54_ui as t54
    import test_r56 as t56
    import tkinter as tk
    mk = t36.doc_factory()
    root = tk.Tk()
    scs = t50.sc_list(root)
    root.destroy()
    check(len(scs) >= 3 and {pc for _f, pc in scs} == {100, 125, 150}, "W7: сценарії охоплюють 100/125/150 %%: %r" % (scs,))
    for sc in scs:
        app = t54.new_app(sc)
        try:
            app.apply_min_size()
            W, H = app.min_window_size()
            app.geometry("%dx%d" % (W, H))
            lp.spin(app, 0.4)
            p = app.get_panel("satellites")
            p.now_override = NOW
            app.show("satellites")
            lp.spin(app, 0.5)
            # --- головний вигляд при мінімальному розмірі вікна, найгірший вміст: довгий рядок стану, нагадування про таблицю, пропущені рядки таблиці ---
            p.slots = [t56.slot_from("SAT%d" % i, 43017, 40 + i, None, rx1=145_960_000, tx1=435_250_000) for i in range(25)]
            p.radio_state = st.ST_OK
            p.base_bytes = st.build_block(p.slots)
            p.now_override = NOW + datetime.timedelta(days=200)
            p.set_table(stb.default_rows()[0], ["рядок %d: тестове зауваження про некоректний рядок таблиці частот -- пропущено" % i for i in range(1, 9)], "вбудована",
                        verified=stb.builtin_verified_date(), kind="файл /home/користувач/MD-UV390UKR/satellites.txt")
            p._redraw_slots()
            lp.spin(app, 0.6)
            host = p._host
            res = lp.probe_panel(app, "satellites")
            check(not res, "W7 [%s]: головний вигляд з найгіршим вмістом (25 слотів, нагадування, пропущені рядки) не обрізано: %r" % (fs.label(sc), res[:3]))
            # --- без найгіршого вмісту: те саме для звичайного стану ---
            p.slots, p.radio_state, p.base_bytes = [], None, None
            p.now_override = NOW
            p.load_builtin_table()
            p._redraw_slots()
            lp.spin(app, 0.5)
            check(not host._bar_shown and not host._hbar_shown, "W7 [%s]: звичайний головний вигляд у вікні %dx%d без смуг прокрутки (потрібно %d px, є %d)" % (
                fs.label(sc), W, H, host.inner.winfo_reqheight(), host.winfo_height()))
            res = lp.probe_panel(app, "satellites")
            check(not res, "W7 [%s]: звичайний головний вигляд не обрізано: %r" % (fs.label(sc), res[:3]))
            # --- «Детально» розгорнуто: повний прохід верстки з 25 слотами ---
            p.slots = [st.Slot("SAT%d" % i, rx1=145_960_000, tx1=435_250_000, rx2=145_825_000, tx2=145_825_000, rx3=145_800_000) for i in range(25)]
            p.toggle_detail(True)
            p._redraw_slots()
            res = lp.run_all(app, sizes=((1024, 768),), keys=["satellites"], doc_states=(None, mk))
            lines = lp.format_report(res)
            check(not lines, "W7 [%s]: «Детально» розгорнуто, обрізано в %d місцях:\n  %s" % (fs.label(sc), len(lines), "\n  ".join(l[:230] for l in lines[:10])))
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
        print("test_r56_ui: нема tkinter/DISPLAY -- GUI-частину пропущено")
        return 0
    for t in (test_w1_main, test_w2_w6_flow, test_w7_layout):
        try:
            t()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILS.append("%s: виняток %r" % (t.__name__, e))
    if FAILS:
        print("\nПРОВАЛІВ: %d" % len(FAILS))
        return 1
    print("test_r56_ui: усе гаразд (%d перевірок)." % PASSED[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
