# -*- coding: utf-8 -*-
"""Розділ «Кодплаг → Роумінг» (R59): автоперехід на наступний канал зі списку, коли ретранслятор не відповідає на пробудження під утримуваним PTT.

ДВА шляхи запису, чітко розділені (як в «APRS»):
  * «Налаштування в рації» (автоперехід увімк./вимк., макс. стрибків 1..5) -- custom-data блок типу 15 (tools/roam_cfg.py). Пишеться в РАЦІЮ негайно власною кнопкою,
    поза кодплагом; перед записом попередній блок зберігається у файл-страхову копію, після запису -- звірка читанням. Потрібна рація у звичайному режимі.
  * «Список у кодплазі» -- прапорець «Роумінг» на каналах (колонка «Роум.» в «Каналах» і «Roam» у CSV). Це частина ДОКУМЕНТА: у рацію потрапляє дією «Записати
    кодплаг у рацію». Тут його зручно набирати: позначити канали в таблиці й натиснути «Додати поточно виділений канал».
Попередження (не блокують запис): автоперехід увімкнено, а в списку менше 2 каналів; канал зі списку аналоговий / DMO / симплекс / лише прийом (прошивка його
пропустить); два канали з однаковими частотами й колір-кодом; прапорці є, а блока налаштувань у рації немає (з пропозицією зняти позначки).
Діє лише у збірці прошивки «роумінг» (ENABLE_ROAM_RETRY); в інших збірках блок і прапорці ігноруються."""
import tkinter as tk
from tkinter import ttk, messagebox

import cps_csv as cc
import cps_link as cps
import gui_theme as gt
import roam_cfg as rc
import table_edit as te

from .common import output_dir
from .layout import FitTable, equal_buttons
from .panel import Panel

COLUMNS = (("n", "№", 45, False), ("name", "Назва", 150, True), ("rx", "RX, МГц", 85, False), ("tx", "TX, МГц", 85, False),
           ("cc", "CC", 35, False), ("roam", "Роум.", 50, False), ("note", "Примітка", 170, True))


def channel_rows(img, dp, only_listed=False, needle=""):
    """[(номер, (№, назва, RX, TX, CC, ✓|"", примітка))] для таблиці. Примітка -- причина, чому прошивка пропустить канал зі списку (для каналів не зі списку порожня)."""
    ctx = cc.make_ctx_for_export(img, dp)
    rx, tx = cc.CH_COLUMN_BY_NAME["Rx Frequency"]["dec"], cc.CH_COLUMN_BY_NAME["Tx Frequency"]["dec"]
    needle = (needle or "").strip().casefold()
    out = []
    for n, r in img.channels():
        listed = rc.is_listed(r)
        if only_listed and not listed:
            continue
        vals = (n, cc.readable_text(r[:16]), rx(r, ctx).strip("\t").strip(), tx(r, ctx).strip("\t").strip(),
                str(r[cc.O_COLOR]) if r[cc.O_MODE] else "", "✓" if listed else "", (rc.problem_of(r) or "") if listed else "")
        if needle and not any(needle in str(v).casefold() for v in vals):
            continue
        out.append((n, vals))
    return out


class RoamPanel(Panel):
    key = "roam"
    title = "Роумінг"
    doc_panel = True            # список -- у документі кодплага; блок налаштувань пишеться в рацію окремою кнопкою (reg)

    def __init__(self, parent, shell):
        super().__init__(parent, shell)
        self._radio_cfg = None            # None -- з рації ще не читали; False -- блока там немає (або недійсний); dict -- {"enabled", "max_hops"}
        self._item_num = {}
        self.dp = cc.system_decimal_point()
        self._build_ui()

    # ------------------------------------------------------------------ побудова

    def _build_ui(self):
        self.header("Роумінг", purpose="коли ретранслятор мовчить на пробудження, рація сама переходить на наступний канал зі списку, не відпускаючи PTT.")
        ttk.Label(self, text=("Діє лише в прошивці зі збіркою «роумінг». Перехід можливий, лише якщо ПОТОЧНИЙ канал сам у списку. Кожен канал рація пробує "
                              "стільки разів, скільки задано кількістю спроб пробудження ретранслятора в кодплазі; переходить не більше ніж на «Макс. стрибків» каналів за одне натискання PTT, "
                              "один раз проходить коло. Знайдений канал лишається активним, у кодплаг нічого не пишеться."),
                  wraplength=620, justify="left", foreground=gt.P["muted"]).pack(anchor="w", padx=12, pady=(0, 6))

        # --- налаштування в рації ---
        box = ttk.LabelFrame(self, text="Налаштування в рації -- пишуться в РАЦІЮ негайно (НЕ частина документа)")
        box.pack(fill="x", padx=12, pady=4)
        self.v_enabled = tk.BooleanVar(value=False)
        self.v_hops = tk.StringVar(value=str(rc.HOPS_DEFAULT))
        cb = ttk.Checkbutton(box, text="Автоперехід увімкнено", variable=self.v_enabled, command=self.refresh_warnings)
        cb.pack(anchor="w", padx=8, pady=(4, 2))
        self.cb_enabled = cb
        row = ttk.Frame(box)
        row.pack(fill="x", padx=8, pady=2)
        ttk.Label(row, text="Макс. стрибків (%d..%d)" % (rc.HOPS_MIN, rc.HOPS_MAX), width=34).pack(side="left")
        self.sp_hops = ttk.Spinbox(row, from_=rc.HOPS_MIN, to=rc.HOPS_MAX, textvariable=self.v_hops, width=6)
        self.sp_hops.pack(side="left")
        btn = ttk.Frame(box)
        btn.pack(fill="x", padx=8, pady=6)
        self.read_btn = ttk.Button(btn, text="Прочитати з рації", command=self._on_read)
        self.write_btn = ttk.Button(btn, text="Записати налаштування в рацію", command=self._on_write)
        equal_buttons(self.read_btn, self.write_btn)
        self.read_btn.pack(side="left")
        self.write_btn.pack(side="left", padx=8)
        self.reg(self.read_btn)
        self.reg(self.write_btn)
        self.radio_label = ttk.Label(box, text="Натисни «Прочитати з рації», щоб підтягнути поточні значення.", foreground=gt.P["info"], wraplength=600,
                                     justify="left")
        self.radio_label.pack(anchor="w", padx=8, pady=(0, 6))

        # --- список у кодплазі ---
        lst = ttk.LabelFrame(self, text="Список у кодплазі -- частина документа (у рацію потрапляє дією «Записати кодплаг у рацію»)")
        lst.pack(fill="both", expand=True, padx=12, pady=4)
        top = ttk.Frame(lst)
        top.pack(fill="x", padx=8, pady=(4, 2))
        self.count_label = ttk.Label(top, text="", font=("Segoe UI", 10, "bold"))
        self.count_label.pack(side="left")
        self.v_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Лише канали зі списку", variable=self.v_only, command=self._fill).pack(side="right")
        frow = ttk.Frame(lst)
        frow.pack(fill="x", padx=8)
        ttk.Label(frow, text="Фільтр:").pack(side="left")
        self.v_filter = tk.StringVar()
        ttk.Entry(frow, textvariable=self.v_filter).pack(side="left", fill="x", expand=True, padx=4)
        self.v_filter.trace_add("write", lambda *_: self._fill())
        spec = [(cid, text, width, 1 if stretch else 0) for cid, text, width, stretch in COLUMNS]
        self.table = FitTable(lst, spec, height=9, selectmode="extended")
        self.tree = self.table.tree
        self.table.pack(fill="both", expand=True, padx=8, pady=4)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.refresh_state())
        bars = ttk.Frame(lst)
        bars.pack(fill="x", padx=8, pady=(0, 6))
        self.add_btn = ttk.Button(bars, text="Додати поточно виділений канал", command=lambda: self._set_selected(True))
        self.rem_btn = ttk.Button(bars, text="Прибрати", command=lambda: self._set_selected(False))
        self.clr_btn = ttk.Button(bars, text="Прибрати всі...", command=self._clear_all)
        equal_buttons(self.add_btn, self.rem_btn, self.clr_btn)
        for i, b in enumerate((self.add_btn, self.rem_btn, self.clr_btn)):
            b.grid(row=0, column=i, sticky="ew", padx=2)
            self.reg(b, radio=False, doc=True)
            bars.columnconfigure(i, weight=1, uniform="rb")
        self.msg = ttk.Label(lst, text="", wraplength=620, justify="left")
        self.msg.pack(anchor="w", padx=8, pady=(0, 4))

        self.warn_label = ttk.Label(self, text="", wraplength=620, justify="left", foreground=gt.P["warn"])
        self.warn_label.pack(anchor="w", padx=12, pady=(0, 8))
        self.on_document_changed()

    # ------------------------------------------------------------------ документ

    def on_document_changed(self):
        self._fill()

    def _fill(self):
        d = self.doc
        self.tree.delete(*self.tree.get_children())
        self._item_num = {}
        if d is None:
            self.count_label.config(text="Відкрийте кодплаг з рації або з бекапу")
            self.refresh_warnings()
            return
        for n, vals in channel_rows(d.image, self.dp, only_listed=self.v_only.get(), needle=self.v_filter.get()):
            item = self.tree.insert("", "end", values=vals)
            self._item_num[item] = n
        self.count_label.config(text="У списку каналів: %d" % len(te.roam_numbers(d.image)))
        self.refresh_warnings()

    def selected_numbers(self):
        return [self._item_num[i] for i in self.tree.selection() if i in self._item_num]

    def _say(self, text, kind="muted"):
        color = {"muted": gt.P["muted"], "ok": gt.P["ok"], "err": gt.P["err"], "warn": gt.P["warn"]}[kind]
        self.msg.config(text=text, foreground=color)

    def _apply(self, fn, what):
        d = self.doc
        if d is None or self.shell.busy:
            return False
        try:
            res = fn(d.image)
        except te.TableEditError as e:
            self._say("\n".join(e.problems), "err")
            return False
        keep = self.selected_numbers()
        if not d.apply(res):
            self._say("Змін немає: %s" % what, "muted")
            return True
        self._say("%s: змінено каналів %d." % (what, len(res.changed)), "ok")
        self.shell.set_status("Документ змінено: %s." % what, "ok")
        self._fill()
        for item, n in self._item_num.items():
            if n in keep:
                self.tree.selection_add(item)
        return True

    def _set_selected(self, on):
        nums = self.selected_numbers()
        if not nums:
            self._say("Спершу виділіть у таблиці один або кілька каналів.", "warn")
            return
        self._apply(lambda img: te.channels_set_roam(img, nums, on), "додано до списку" if on else "прибрано зі списку")

    def _clear_all(self):
        d = self.doc
        if d is None:
            return
        nums = te.roam_numbers(d.image)
        if not nums:
            self._say("У списку немає каналів.", "muted")
            return
        if not messagebox.askokcancel("Прибрати всі позначки?", "Прапорець «Роумінг» буде знято з %d каналів документа. Інші поля каналів не змінюються. "
                                      "Рація зміниться лише після «Записати кодплаг у рацію». Продовжити?" % len(nums)):
            return
        self._apply(lambda img: te.channels_set_roam(img, nums, False), "прибрано всі позначки")

    # ------------------------------------------------------------------ попередження

    def warnings(self):
        """Тексти попереджень за поточним документом і станом форми (НЕ за тим, що вже лежить у рації)."""
        d = self.doc
        if d is None:
            return []
        return rc.check_list(d.image, enabled=bool(self.v_enabled.get()), block_absent=(self._radio_cfg is False))

    def refresh_warnings(self):
        w = self.warnings()
        self.warn_label.config(text=("Увага:\n- " + "\n- ".join(w)) if w else "")

    # ------------------------------------------------------------------ рація

    def _collect(self):
        """Поля форми -> (enabled, max_hops). RoamCfgError -- погане значення."""
        try:
            hops = int(str(self.v_hops.get()).strip())
        except ValueError:
            raise rc.RoamCfgError("макс. стрибків: потрібне ціле число %d..%d" % (rc.HOPS_MIN, rc.HOPS_MAX))
        rc.check_hops(hops)
        return bool(self.v_enabled.get()), hops

    def _apply_radio(self, state, raw):
        """Головний потік: підставити в форму прочитане з рації. state None -- блока немає/недійсний."""
        if state is None:
            self._radio_cfg = False
            self.v_enabled.set(False)
            self.v_hops.set(str(rc.HOPS_DEFAULT))
            self.radio_label.config(text=("Блока налаштувань у рації немає -- автоперехід вимкнено, макс. стрибків %d." % rc.HOPS_DEFAULT) if raw is None else
                                    "Блок налаштувань у рації недійсний (прошивка читає його як «вимкнено, %d»)." % rc.HOPS_DEFAULT, foreground=gt.P["warn"])
        else:
            self._radio_cfg = {"enabled": state["enabled"], "max_hops": state["max_hops"]}
            self.v_enabled.set(state["enabled"])
            self.v_hops.set(str(state["max_hops"]))
            self.radio_label.config(text="Прочитано з рації: " + rc.describe(state) + ".", foreground=gt.P["ok"])
        self.refresh_warnings()

    def _run(self, fn, text):
        self.shell.run_task(fn, text, plain_errors=True)

    def _on_read(self):
        if not self.shell.busy:
            self._run(self._read_worker, "Читаю налаштування «Роумінгу»...")

    def _on_write(self):
        if self.shell.busy:
            return
        try:
            en, hops = self._collect()
        except rc.RoamCfgError as e:
            messagebox.showerror("Помилка", str(e))
            return
        self._run(lambda: self._write_worker(en, hops), "Записую налаштування «Роумінгу»...")

    def _read_worker(self):
        ser = cps.open_radio()
        try:
            st, raw = rc.read_state(ser)
            self.shell.post(lambda: self._apply_radio(st, raw))
            print("Роумінг: " + rc.describe(st))
        finally:
            ser.close()

    def _write_worker(self, en, hops):
        ser = cps.open_radio()
        try:
            text, _safety = rc.write_state(ser, en, hops, safety_dir=output_dir(), log=print)
            print(text)
            st, raw = rc.read_state(ser)
            self.shell.post(lambda: self._apply_radio(st, raw))
        finally:
            ser.close()
