# -*- coding: utf-8 -*-
"""Розділ «Налаштування рації → Мелодія вмикання» (R35 C): мелодія, яку рація грає при вмиканні разом із заставкою (custom-data блок BEEP, 512 Б).

Блок НЕ є частиною кодплага: «Записати мелодію в рацію» змінює рацію одразу. Формат (з коду прошивки, див. tools/boot_melody.py): пари {нота 0..63, тривалість у одиницях по 27 мс},
нульова тривалість -- кінець; перші два байти 0 -- рація пропускає заставку разом із мелодією. Частоти нот -- таблиця прошивки, тож тон «з будь-якою частотою» неможливий:
редактор підбирає найближчу ноту. Прослухати можна лише на Windows (winsound); деінде показуються самі ноти."""
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import boot_melody as bm
import cps_link as cps
import gui_dialogs as gd
import gui_theme as gt

from .layout import FitTable
from .panel import Panel

NO_MELODY = "(без заставки і мелодії)"


class MelodyPanel(Panel):
    key = "melody"
    title = "Мелодія вмикання"

    def __init__(self, parent, shell):
        super().__init__(parent, shell)
        self.tones = []                  # робочий список bm.Tone
        self.skip_splash = False         # режим «рація пропускає заставку й мелодію»
        self.radio_state = None
        self.radio_len = None
        self.radio_warns = []
        self.stop_event = threading.Event()
        self.playing = False
        self.note_var = tk.StringVar(value=bm.note_name(33))
        self.ms_var = tk.StringVar(value="150")
        self.preset_var = tk.StringVar(value=bm.PRESETS[0][1])
        self.morse_var = tk.StringVar(value="73")
        self.skip_var = tk.BooleanVar(value=False)
        self._build_ui()
        self._redraw()

    # --- побудова ---------------------------------------------------------------------------------

    def _build_ui(self):
        self.header("Мелодія вмикання", "Звук при вмиканні рації. Мелодія лежить в окремому блоці флеша рації (512 Б), тому «Записати мелодію в рацію» тут змінює рацію одразу, окремо від "
                                        "кодплага. Тривалість тону кратна 27 мс, частоти -- лише з таблиці нот прошивки (63 ноти від 104 Гц).",
                    purpose="змінити звук вмикання рації або вимкнути заставку разом із мелодією.")
        box = ttk.LabelFrame(self, text="1. Рація")
        box.pack(fill="x", padx=12, pady=6)
        bar = ttk.Frame(box)
        bar.pack(fill="x", padx=8, pady=(6, 2))
        self.read_btn = ttk.Button(bar, text="Прочитати з рації", command=self._on_read)
        self.read_btn.pack(side="left")
        self.reg(self.read_btn)
        self.write_btn = ttk.Button(bar, text="Записати мелодію в рацію...", command=self._on_write)
        self.write_btn.pack(side="left", padx=8)
        self.reg(self.write_btn)
        self.restore_btn = ttk.Button(bar, text="Повернути вбудовану...", command=self._on_restore)
        self.restore_btn.pack(side="left", padx=8)
        self.reg(self.restore_btn)
        self.state_label = ttk.Label(box, text="Рацію ще не читали.", foreground=gt.P["muted"], wraplength=640, justify="left")
        self.state_label.pack(anchor="w", padx=8, pady=(0, 6))

        ed = ttk.LabelFrame(self, text="2. Мелодія")
        ed.pack(fill="x", padx=12, pady=6)
        row = ttk.Frame(ed)
        row.pack(fill="x", padx=8, pady=(6, 2))
        ttk.Label(row, text="Готова мелодія:").pack(side="left")
        names = [p[1] for p in bm.PRESETS] + [NO_MELODY]
        combo = ttk.Combobox(row, textvariable=self.preset_var, values=names, state="readonly", width=34)
        combo.pack(side="left", padx=6)
        self.preset_btn = ttk.Button(row, text="Підставити", command=self._on_preset)
        self.preset_btn.pack(side="left")
        self.preset_note = ttk.Label(ed, text="", foreground=gt.P["muted"], wraplength=640, justify="left")
        self.preset_note.pack(anchor="w", padx=8)
        self.skip_check = ttk.Checkbutton(ed, text="Без заставки і мелодії (рація при вмиканні нічого не показує й не грає)", variable=self.skip_var, command=self._on_skip_toggled)
        self.skip_check.pack(anchor="w", padx=8, pady=(4, 2))

        tbl = FitTable(ed, [("n", "№", 40, 0), ("note", "Нота", 120, 1), ("hz", "Частота, Гц", 100, 0), ("ms", "Тривалість, мс", 110, 0)], height=9)
        self.tree = tbl.tree
        tbl.pack(fill="x", padx=8, pady=4)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_selected())
        self.total_label = ttk.Label(ed, text="")
        self.total_label.pack(anchor="w", padx=8)
        self.warn_label = ttk.Label(ed, text="", foreground=gt.P["warn"], wraplength=640, justify="left")
        self.warn_label.pack(anchor="w", padx=8)

        form = ttk.Frame(ed)
        form.pack(fill="x", padx=8, pady=(6, 2))
        ttk.Label(form, text="Нота").grid(row=0, column=0, sticky="w")
        self.note_box = ttk.Combobox(form, textvariable=self.note_var, values=[bm.note_name(i) for i in range(64)], state="readonly", width=12)
        self.note_box.grid(row=1, column=0, sticky="w", padx=(0, 8))
        ttk.Label(form, text="Тривалість, мс (крок 27)").grid(row=0, column=1, sticky="w")
        ttk.Entry(form, textvariable=self.ms_var, width=10).grid(row=1, column=1, sticky="w", padx=(0, 8))
        self.add_btn = ttk.Button(form, text="Додати в кінець", command=self._on_add)
        self.add_btn.grid(row=1, column=2, padx=4)
        self.set_btn = ttk.Button(form, text="Замінити вибраний", command=self._on_replace)
        self.set_btn.grid(row=1, column=3, padx=4)
        self.del_btn = ttk.Button(form, text="Прибрати", command=self._on_delete)
        self.del_btn.grid(row=1, column=4, padx=4)
        self.up_btn = ttk.Button(form, text="Вгору", command=lambda: self._move(-1), width=7)
        self.up_btn.grid(row=1, column=5, padx=4)
        self.dn_btn = ttk.Button(form, text="Вниз", command=lambda: self._move(1), width=7)
        self.dn_btn.grid(row=1, column=6, padx=4)
        form2 = ttk.Frame(ed)
        form2.pack(fill="x", padx=8, pady=(4, 2))
        ttk.Label(form2, text="Додати текст морзе (цифри, латиниця):").pack(side="left")
        ttk.Entry(form2, textvariable=self.morse_var, width=14).pack(side="left", padx=6)
        self.morse_btn = ttk.Button(form2, text="Додати", command=self._on_morse)
        self.morse_btn.pack(side="left")
        self.clear_btn = ttk.Button(form2, text="Очистити список", command=self._on_clear)
        self.clear_btn.pack(side="left", padx=12)

        form3 = ttk.Frame(ed)
        form3.pack(fill="x", padx=8, pady=(6, 8))
        self.play_btn = ttk.Button(form3, text="Прослухати", command=self._on_play)
        self.play_btn.pack(side="left")
        self.play_label = ttk.Label(form3, text="", foreground=gt.P["muted"], wraplength=520, justify="left")
        self.play_label.pack(side="left", padx=10)

    # --- стан списку ------------------------------------------------------------------------------

    def _note_index(self):
        name = self.note_var.get()
        for i in range(64):
            if bm.note_name(i) == name:
                return i
        raise bm.MelodyError("нота «%s» не з таблиці" % name)

    def _ms(self):
        t = (self.ms_var.get() or "").strip().replace(",", ".")
        try:
            v = float(t)
        except ValueError:
            raise bm.MelodyError("тривалість «%s» не число (мс)" % self.ms_var.get())
        if not (bm.UNIT_MS / 2.0 <= v <= 255 * bm.UNIT_MS + bm.UNIT_MS / 2.0):
            raise bm.MelodyError("тривалість має бути від %d до %d мс" % (bm.UNIT_MS, 255 * bm.UNIT_MS))
        return bm.ms_to_units(v)

    def selected(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _redraw(self, select=None):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for i, t in enumerate(self.tones):
            self.tree.insert("", "end", iid=str(i), values=(i + 1, bm.note_name(t.note), t.hz if t.note else "", t.ms))
        if select is not None and 0 <= select < len(self.tones):
            self.tree.selection_set(str(select))
        if self.skip_splash:
            self.total_label.config(text="Режим «без заставки і мелодії»: блок у рації буде з нулів.")
            self.warn_label.config(text="")
        else:
            need = 2 * len(self.tones) + (0 if len(self.tones) == bm.MAX_NOTES else 2)
            self.total_label.config(text="Тонів %d, разом %.2f с; займає %d Б із %d." % (len(self.tones), bm.total_ms(self.tones) / 1000.0, need, bm.BLOCK_LEN))
            w = []
            if not self.tones:
                w.append("Список порожній -- записати мелодію не можна. Для «нічого не грати» оберіть «Тиша» або режим «без заставки і мелодії».")
            if need > bm.BLOCK_LEN:
                w.append("Не вміщується в блок %d Б." % bm.BLOCK_LEN)
            if self.radio_state == bm.ST_OK and self.radio_len is not None and need > self.radio_len:
                w.append("Блок у рації лише %d Б: щоб записати, його доведеться вилучити й створити новий на %d Б (старе місце лишиться зайнятим)." % (self.radio_len, bm.BLOCK_LEN))
            self.warn_label.config(text=" ".join(w))
        state = "disabled" if self.skip_splash else "normal"
        for b in (self.add_btn, self.set_btn, self.del_btn, self.up_btn, self.dn_btn, self.morse_btn, self.clear_btn, self.play_btn, self.preset_btn):
            b.config(state=state if b is not self.preset_btn else "normal")
        self._update_state_label()

    def _update_state_label(self):
        if self.radio_state is None:
            text = "Рацію ще не читали."
        else:
            text = "У рації: " + bm.STATE_TEXT[self.radio_state] + "."
            if self.radio_len is not None:
                text += " Довжина блока %d Б." % self.radio_len
            for w in self.radio_warns:
                text += " Зауваження: " + w + "."
        self.state_label.config(text=text)

    def _on_selected(self):
        i = self.selected()
        if i is None:
            return
        t = self.tones[i]
        self.note_var.set(bm.note_name(t.note))
        self.ms_var.set(str(t.ms))

    def _error(self, e):
        messagebox.showerror("Мелодія", str(e), parent=self.shell)

    def _on_add(self):
        try:
            self.tones.append(bm.Tone(self._note_index(), self._ms()))
        except bm.MelodyError as e:
            self._error(e)
            return
        self._redraw(len(self.tones) - 1)

    def _on_replace(self):
        i = self.selected()
        if i is None:
            messagebox.showinfo("Мелодія", "Спершу вибери тон у списку.", parent=self.shell)
            return
        try:
            self.tones[i] = bm.Tone(self._note_index(), self._ms())
        except bm.MelodyError as e:
            self._error(e)
            return
        self._redraw(i)

    def _on_delete(self):
        i = self.selected()
        if i is None:
            return
        del self.tones[i]
        self._redraw(min(i, len(self.tones) - 1))

    def _move(self, d):
        i = self.selected()
        if i is None or not (0 <= i + d < len(self.tones)):
            return
        self.tones[i], self.tones[i + d] = self.tones[i + d], self.tones[i]
        self._redraw(i + d)

    def _on_clear(self):
        self.tones = []
        self._redraw()

    def _on_morse(self):
        try:
            add = bm.morse_tones(self.morse_var.get())
        except bm.MelodyError as e:
            self._error(e)
            return
        if len(self.tones) + len(add) > bm.MAX_NOTES:
            self._error("Разом було б %d тонів, а прошивка грає не більше %d." % (len(self.tones) + len(add), bm.MAX_NOTES))
            return
        self.tones.extend(add)
        self._redraw(len(self.tones) - 1)

    def _on_preset(self):
        name = self.preset_var.get()
        if name == NO_MELODY:
            self.skip_var.set(True)
            self._on_skip_toggled()
            self.preset_note.config(text="Рація при вмиканні не покаже заставку й не зіграє мелодію (перші два байти блока нульові).")
            return
        for k, t, d, _make in bm.PRESETS:
            if t == name:
                self.skip_var.set(False)
                self.skip_splash = False
                self.tones = bm.preset(k)
                self.preset_note.config(text=d)
                self._redraw(0)
                return

    def _on_skip_toggled(self):
        self.skip_splash = bool(self.skip_var.get())
        self._redraw()

    # --- програвання ------------------------------------------------------------------------------

    def _on_play(self):
        if self.playing:
            self.stop_event.set()
            return
        if not self.tones:
            self.play_label.config(text="Список порожній.")
            return
        if bm.player() is None:
            lines = ["%d. %s" % (i + 1, t.text()) for i, t in enumerate(self.tones)]
            self.play_label.config(text="Програвання на цьому комп'ютері недоступне (потрібен Windows). Ноти: " + "; ".join(lines[:12]) + ("; ..." if len(lines) > 12 else ""))
            return
        self.stop_event.clear()
        self.playing = True
        self.play_btn.config(text="Стоп")
        tones = list(self.tones)

        def run():
            try:
                bm.play(tones, should_stop=self.stop_event.is_set)
            except Exception as e:  # noqa: BLE001 -- звук не має ламати вікно
                self.shell.post(lambda: self.play_label.config(text="Не вдалося зіграти: %s" % e))
            finally:
                self.shell.post(self._play_done)
        threading.Thread(target=run, daemon=True).start()

    def _play_done(self):
        self.playing = False
        try:
            self.play_btn.config(text="Прослухати")
        except tk.TclError:
            pass

    # --- рація ------------------------------------------------------------------------------------

    def _on_read(self):
        if self.shell.busy:
            return
        self.shell.run_task(self._read_worker, "Читаю мелодію з рації...", plain_errors=True)

    def _read_worker(self):
        ser = cps.open_radio()
        try:
            state, ln, raw = bm.read_melody(ser)
        finally:
            ser.close()
        self.shell.post(lambda: self.apply_read(state, ln, raw))

    def apply_read(self, state, ln, raw):
        self.radio_state, self.radio_len, self.radio_warns = state, ln, []
        if raw is not None:
            tones, skip, warns = bm.parse(raw)
            self.radio_warns = warns
            self.tones, self.skip_splash = tones, skip
            self.skip_var.set(skip)
        self._redraw(0 if self.tones else None)

    def _check_ready(self):
        if self.radio_state == bm.ST_NOREGION:
            self._error("Записати не можна: %s." % bm.STATE_TEXT[bm.ST_NOREGION])
            return False
        if not self.skip_splash and not self.tones:
            messagebox.showinfo("Мелодія", "Список порожній. Додай тони, обери готову мелодію або режим «без заставки і мелодії».", parent=self.shell)
            return False
        return True

    def _on_write(self):
        if self.shell.busy or not self._check_ready():
            return
        skip = self.skip_splash
        tones = list(self.tones)
        replace = False
        lines = []
        if skip:
            lines.append("У рацію буде записано режим «без заставки і мелодії»: при вмиканні рація не покаже заставку й не зіграє мелодію.")
        else:
            lines.append("У рацію буде записано мелодію: %d тонів, %.2f с." % (len(tones), bm.total_ms(tones) / 1000.0))
        need = 2 * len(tones) + (0 if len(tones) == bm.MAX_NOTES else 2)
        if (not skip) and self.radio_state == bm.ST_OK and self.radio_len is not None and need > self.radio_len:
            replace = True
            lines += ["", "Блок мелодії в рації лише %d Б -- мелодія в нього не вміщується, а змінювати довжину наявного блока не можна." % self.radio_len,
                      "Тому старий блок буде ВИЛУЧЕНО (рація його більше не бачитиме), а новий створено на %d Б у вільному місці області. Місце старого блока лишиться зайнятим." % bm.BLOCK_LEN]
        elif self.radio_state == bm.ST_OK:
            lines.append("Поточна мелодія в рації буде замінена.")
        elif self.radio_state is None:
            lines.append("Рацію ще не читали: невідомо, чи є в ній своя мелодія.")
        lines += ["", "Це змінює рацію одразу (поза кодплагом). Кодплаг, ключі, теми й база позивних не чіпаються."]
        if not gd.confirm_dialog(self.shell, "Записати мелодію в рацію?", "\n".join(lines), yes="Записати", no="Скасувати"):
            return
        self.shell.run_task(lambda: self._write_worker(tones, skip, replace), "Записую мелодію в рацію...", plain_errors=True,
                            on_done=lambda t: messagebox.showinfo("Мелодія", t, parent=self.shell))

    def _write_worker(self, tones, skip, replace):
        ser = cps.open_radio()
        try:
            text = bm.write_melody(ser, tones, skip_splash=skip, replace=replace)
            state, ln, raw = bm.read_melody(ser)
        finally:
            ser.close()
        print(text)
        self.shell.post(lambda: self.apply_read(state, ln, raw))
        return text

    def _on_restore(self):
        if self.shell.busy:
            return
        if not gd.confirm_dialog(self.shell, "Повернути вбудовану мелодію?", "Блок мелодії в рації буде вилучено: рація знову гратиме вбудовану мелодію вмикання.\n\n"
                                 "Місце блока (%d Б) лишиться зайнятим в області custom-data -- нова мелодія піде у вільне місце. Кодплаг й інші блоки не чіпаються." % bm.BLOCK_LEN,
                                 yes="Вилучити", no="Скасувати"):
            return
        self.shell.run_task(self._restore_worker, "Вилучаю блок мелодії...", plain_errors=True, on_done=lambda t: messagebox.showinfo("Мелодія", t, parent=self.shell))

    def _restore_worker(self):
        ser = cps.open_radio()
        try:
            text = bm.remove_melody(ser)
        finally:
            ser.close()
        print(text)
        self.shell.post(lambda: self.apply_read(bm.ST_ABSENT, None, None))
        return text
