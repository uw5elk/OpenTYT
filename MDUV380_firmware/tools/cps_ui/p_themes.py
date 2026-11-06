# -*- coding: utf-8 -*-
"""Розділ «Налаштування рації → Теми» (R28): кольори екрана рації -- денна й нічна теми (по 32 кольори).

ТЕМИ НЕ Є ЧАСТИНОЮ ДОКУМЕНТА КОДПЛАГА. Вони лежать в області custom-data SPI-флеша (блоки 4 і 5), поза EEPROM і поза діапазоном, який відновлює
cps_restore, тому «Записати кодплаг у рацію» над документом теми не змінює (з R30 область custom-data входить у бекап окремим файлом і відновлюється
окремим прапорцем -- див. «Бекап і відновлення»). Файл теми -- `.gtm` стокового CPS OpenGD77: рівно 64 байти, без заголовка (theme_edit.py). Панель працює як бікон APRS: «Прочитати з рації» і «Записати в рацію» --
негайно, тим самим шляхом (custom_data.write_block + звірка читанням). Рація читає теми ЛИШЕ при вмиканні -- після запису її треба вимкнути й увімкнути.

Усе, що не торкається рації (вибір кольорів, готові набори, «Скинути до стокової», файл теми, перегляд), працює й без підключеної рації, і без документа.
Логіка (формат блока, стокові значення, набори, файл, перевірка читабельності, опис перегляду) -- у tools/theme_edit.py; тут лише вікно."""
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser

import cps_link as cps
import gui_dialogs as gd
import gui_theme as gt
import screen_sim as sim
import theme_edit as te

from .common import output_dir
from .layout import FlowFrame, equal_buttons
from .panel import Panel, ScrollFrame

PREVIEW_SCALES = (2, 3, 4, 5)    # цілий масштаб без згладжування (PhotoImage.zoom -- найближчий піксель); 4 і 5 -- лише якщо вміщуються (R36)
PREVIEW_SCALE = 4


class ThemesPanel(Panel):
    key = "themes"
    title = "Тема"
    scroll = False          # список кольорів має власну прокрутку, перегляд лишається на місці

    def __init__(self, parent, shell):
        super().__init__(parent, shell)
        self.daytime = tk.StringVar(value="night")
        # робоча копія тем: те, що показано й що буде записано
        self.colors = {dt: te.stock_colors(dt) for dt in te.DAYTIMES}
        self.base = {dt: None for dt in te.DAYTIMES}              # що було в рації на момент читання/запису (None -- не читали)
        self.radio_state = {dt: None for dt in te.DAYTIMES}       # te.ST_* або None
        self.touched = {dt: False for dt in te.DAYTIMES}          # користувач змінив/завантажив і ще не записав
        self.set_vars = {}
        self._rows = []
        self._selected = None
        self._build_ui()
        self._redraw()

    # --- побудова ---------------------------------------------------------------------------------

    def _build_ui(self):
        # R36: ліворуч -- керування й список кольорів (прокручується), праворуч -- перегляд екрана (теж у власній прокрутці); між ними рухома межа.
        # Керування має мінімальну ширину (LEFT_MIN): перегляд його не «з'їдає» -- замість цього масштаб перегляду зменшується (_fit_scale),
        # а якщо не вміщується й найменший, перегляд прокручується.
        self.pane = ttk.PanedWindow(self, orient="horizontal")
        self.pane.pack(fill="both", expand=True)
        self.left_host = ScrollFrame(self.pane)
        self.right_host = ScrollFrame(self.pane)
        self.pane.add(self.left_host, weight=0)          # керування не ростуть разом із вікном: зайве місце отримує перегляд
        self.pane.add(self.right_host, weight=1)
        left = self.left_host.inner
        ttk.Label(left, text="Теми", font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=gt.PAD, pady=(10, 2))
        self._wrap = []
        hint = ttk.Label(left, text=("Кольори екрана рації: денна й нічна теми. Тема живе не в кодплазі, а в окремій області флеша рації, тому «Записати теми в рацію» "
                              "тут змінює рацію одразу, окремо від кодплага. Рація читає тему лише при вмиканні: після запису вимкни її й увімкни, а до того не "
                              "міняй тему з меню рації -- воно записало б поверх свої значення з пам'яті."),
                  wraplength=360, justify="left", foreground=gt.P["muted"])
        hint.pack(anchor="w", padx=gt.PAD, pady=(0, 6))
        self._wrap.append(hint)
        self.make_note(left)
        self._wrap.append(self.note)
        top = ttk.Frame(left)
        top.pack(fill="x", padx=gt.PAD, pady=(0, 4))
        ttk.Label(top, text="Тема:").pack(side="left")
        for dt in te.DAYTIMES:
            ttk.Radiobutton(top, text=te.DAYTIME_NAMES[dt], value=dt, variable=self.daytime, command=self._on_daytime).pack(side="left", padx=(gt.GAP, 0))
        sets = ttk.Frame(left)
        sets.pack(fill="x", padx=gt.PAD, pady=(0, 2))
        ttk.Label(sets, text="Набір:").pack(side="left")
        self.set_var = tk.StringVar()
        self.set_combo = ttk.Combobox(sets, textvariable=self.set_var, state="readonly", width=22)
        self.set_combo.pack(side="left", padx=6, fill="x", expand=True)
        self.set_combo.bind("<<ComboboxSelected>>", lambda _e: self._show_set_desc())
        sets2 = FlowFrame(left)
        sets2.pack(fill="x", padx=gt.PAD, pady=(0, 2))
        self.set_btn = ttk.Button(sets2, text="Застосувати набір", command=self._on_apply_set)
        sets2.add(self.set_btn)
        self.set_desc = ttk.Label(left, text="", foreground=gt.P["muted"], wraplength=340, justify="left")
        self.set_desc.pack(anchor="w", padx=gt.PAD, pady=(0, 2))
        self._wrap.append(self.set_desc)

        bar = FlowFrame(left)
        bar.pack(fill="x", padx=gt.PAD, pady=(6, 2))
        self.read_btn = ttk.Button(bar, text="Прочитати з рації", command=self._on_read)
        self.write_btn = ttk.Button(bar, text="Записати теми в рацію", command=self._on_write)
        equal_buttons(self.read_btn, self.write_btn)
        bar.add(self.read_btn)
        bar.add(self.write_btn)
        self.reg(self.read_btn)
        self.reg(self.write_btn)
        ttk.Label(left, text="Скинути до стокової:").pack(anchor="w", padx=gt.PAD, pady=(gt.GAP, 0))
        bar2 = FlowFrame(left)
        bar2.pack(fill="x", padx=gt.PAD, pady=(0, 4))
        self.reset_btn = ttk.Button(bar2, text="українська", command=self._on_reset)
        self.reset_classic_btn = ttk.Button(bar2, text="класична", command=self._on_reset_classic)
        equal_buttons(self.reset_btn, self.reset_classic_btn)
        bar2.add(self.reset_btn)
        bar2.add(self.reset_classic_btn)
        reset_note = ttk.Label(left, text=("Це дві гілки themeInitToDefaultValues() у прошивці: «українська» -- для української збірки, «класична» -- для збірок "
                                           "іншими мовами. Тема, збережена в рації, перекриває вбудовану при кожному ввімкненні, тож стокова на твоїй рації може "
                                           "бути з будь-якої гілки -- нижче видно, з якою вона збігається."),
                               foreground=gt.P["muted"], wraplength=360, justify="left")
        reset_note.pack(anchor="w", padx=gt.PAD, pady=(0, 4))
        self._wrap.append(reset_note)
        bar3 = FlowFrame(left)
        bar3.pack(fill="x", padx=gt.PAD, pady=(0, 4))
        self.save_btn = ttk.Button(bar3, text="Зберегти у файл...", command=self._on_save_file)
        self.load_btn = ttk.Button(bar3, text="Завантажити з файлу...", command=self._on_load_file)
        equal_buttons(self.save_btn, self.load_btn)
        bar3.add(self.save_btn)
        bar3.add(self.load_btn)

        self.info = ttk.Label(left, text="", foreground=gt.P["muted"], wraplength=360, justify="left")
        self.info.pack(anchor="w", padx=gt.PAD)
        self.match_label = ttk.Label(left, text="", foreground=gt.P["muted"], wraplength=360, justify="left")
        self.match_label.pack(anchor="w", padx=gt.PAD)
        self.warn_label = ttk.Label(left, text="", foreground=gt.P["warn"], wraplength=360, justify="left")
        self.warn_label.pack(anchor="w", padx=gt.PAD)
        self._wrap += [self.info, self.match_label, self.warn_label]
        for w in self._wrap:
            w._fixed_wrap = True          # переносом керує _on_left_width (за шириною лівої частини), а не загальне правило Panel
        self.left_host.width_listeners.append(self._on_left_width)

        lst = ttk.Frame(left)
        lst.pack(fill="x", padx=gt.PAD, pady=6)
        for i, (key, name, desc) in enumerate(te.ITEMS):
            row = ttk.Frame(lst)
            row.pack(fill="x", pady=1)
            nm = ttk.Label(row, text=name, width=24, anchor="w")
            nm.pack(side="left", padx=(2, 6))
            sw = tk.Label(row, width=6, relief="solid", borderwidth=1, cursor="hand2")
            sw._data_colour = True          # зразок показує колір, який вибрав користувач: тест темної теми його не перевіряє (test_gui_theme)
            sw.pack(side="left")
            hx = ttk.Label(row, text="", width=8, font=("Consolas", 9))
            hx.pack(side="left", padx=6)
            mk = ttk.Label(row, text="", width=2, foreground=gt.P["warn"])
            mk.pack(side="left")
            for w in (nm, sw, hx):
                w.bind("<Button-1>", lambda _e, i=i: self._on_pick(i))
            self._rows.append({"row": row, "name": nm, "swatch": sw, "hex": hx, "mark": mk, "desc": desc})

        right = self.right_host.inner
        # один великий екран + перемикач екранів; рендер точний (screen_sim/screen_views), масштаб цілий, без згладжування
        self._screens = te.preview_screens()
        self.screen_var = tk.StringVar(value=self._screens[0][0])
        self.scale_var = tk.IntVar(value=PREVIEW_SCALE)
        self._pref_scale = PREVIEW_SCALE          # масштаб, який вибрав користувач; діючий (scale_var) може бути меншим, якщо місця бракує
        self._display = None
        self._img = None
        bar = FlowFrame(right)
        bar.pack(fill="x", padx=4, pady=(10, 0))
        lab = ttk.Label(bar, text="Екран:")
        self.screen_combo = ttk.Combobox(bar, state="readonly", width=30, values=[t for _k, t in self._screens])
        self.screen_combo.current(0)
        self.screen_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_screen_change())
        bar.add(lab)
        bar.add(self.screen_combo)
        self.scale_radios = {}
        scales = ttk.Frame(right)
        scales.pack(anchor="w", padx=4)
        ttk.Label(scales, text="Масштаб:").pack(side="left")
        for n in PREVIEW_SCALES:
            rb = ttk.Radiobutton(scales, text="x%d" % n, value=n, variable=self.scale_var, command=self._on_scale)
            rb.pack(side="left", padx=2)
            self.scale_radios[n] = rb
        self.canvas = tk.Canvas(right, width=sim.W * PREVIEW_SCALE, height=sim.H * PREVIEW_SCALE, highlightthickness=1, highlightbackground=gt.P["muted"])
        self.canvas.pack(padx=4, pady=4, anchor="nw")
        self.canvas._data_colour = True          # перегляд екрана рації малює кольори теми, а не оформлення вікна
        self.canvas.bind("<Button-1>", self._on_preview_click)
        self.hit_label = ttk.Label(right, text="", foreground=gt.P["muted"], wraplength=sim.W * PREVIEW_SCALE, justify="left")
        self.hit_label.pack(anchor="w", padx=4)
        self.preview_note = ttk.Label(right, text=("Екран малюється тим самим кодом розкладки, що й прошивка (шрифти, координати, порядок малювання); дані на ньому -- приклад. "
                                                   "Клацни піксель -- у списку підсвітиться колір, що його фарбує. Те, що залежить від стану рації й тут не показано, "
                                                   "перелічено в TESTING.md (блок CJ)."),
                                      foreground=gt.P["muted"], wraplength=sim.W * PREVIEW_SCALE, justify="left")
        self.preview_note.pack(anchor="w", padx=4, pady=4)
        for w in (self.hit_label, self.preview_note):
            w._fixed_wrap = True
        self.right_host.width_listeners.append(lambda _w: self._fit_scale())
        self.shell.register_pane("themes", self.pane, default=self._default_left, min_first=self._min_left, min_second=lambda: 200)

    LEFT_MIN = 340
    LEFT_MAX = 520
    RIGHT_PAD = 2 * gt.PAD

    def _min_left(self):
        """Керування не вужчі за LEFT_MIN і не вужчі за те, що вимагають його віджети (але й не ширші за LEFT_MAX)."""
        return max(self.LEFT_MIN, min(self.LEFT_MAX, self.left_host.inner.winfo_reqwidth() + max(1, self.left_host.vbar.winfo_reqwidth())))

    def _default_left(self):
        """Типове положення межі: перегляду віддається стільки, щоб улізло бажаний масштаб (але керування не вужчі за мінімум)."""
        total = max(1, self.pane.winfo_width())
        want_right = sim.W * self._pref_scale + self.RIGHT_PAD + gt.SASH
        return max(self._min_left(), min(self.LEFT_MAX, total - want_right))

    def _fit_scale(self):
        """Діючий масштаб перегляду: вибраний користувачем, якщо вміщується у праву частину, інакше найбільший, що вміщується (не менше найменшого)."""
        if self.right_host.canvas.winfo_width() <= 1:
            return                    # ще не показано: розмір невідомий (масштаб лишається вибраним)
        avail = self.right_host.avail_width() - self.RIGHT_PAD
        fits = [n for n in PREVIEW_SCALES if sim.W * n <= avail]
        want = self._pref_scale if self._pref_scale in fits else (max(fits) if fits else min(PREVIEW_SCALES))
        for n, rb in self.scale_radios.items():
            try:
                rb.config(state="normal" if n in fits or n == want else "disabled")
            except tk.TclError:
                pass
        if int(self.scale_var.get()) != want:
            self.scale_var.set(want)
        self._draw_previews()

    def _on_left_width(self, avail):
        wl = max(200, avail - 2 * gt.PAD - 8)
        for w in self._wrap:
            try:
                w.config(wraplength=wl)
            except tk.TclError:
                pass

    # --- допоміжне --------------------------------------------------------------------------------

    @property
    def dt(self):
        return self.daytime.get()

    def _baseline(self, dt):
        return self.base[dt] if self.base[dt] is not None else te.stock_colors(dt)

    def _status(self, text, kind="info"):
        self.shell.set_status(text, kind)

    def _redraw(self):
        dt = self.dt
        cols = self.colors[dt]
        base = self._baseline(dt)
        for i, r in enumerate(self._rows):
            hexv = te.to_hex(cols[i])
            r["swatch"].config(bg=hexv)
            r["hex"].config(text=hexv)
            r["mark"].config(text="●" if cols[i] != base[i] else "")
            r["name"].config(foreground=gt.P["info"] if i == self._selected else gt.P["fg"])
        self._draw_previews()
        self._refresh_texts()

    def _screen_key(self):
        i = self.screen_combo.current()
        return self._screens[max(0, i)][0]

    def _on_screen_change(self):
        self._display = None
        self._draw_previews()

    def _on_scale(self):
        self._pref_scale = int(self.scale_var.get())
        self._fit_scale()

    def _draw_previews(self):
        """Малює вибраний екран поточними кольорами: буфер зберігає індекси елементів, тож перемальовується лише палітра."""
        if self._display is None:
            self._display = te.render_preview(self._screen_key())
        n = int(self.scale_var.get())
        img = tk.PhotoImage(width=sim.W, height=sim.H)
        img.put(" ".join(sim.render_rows(self._display, self.colors[self.dt])), to=(0, 0))
        self._img = img.zoom(n, n) if n > 1 else img
        self.canvas.config(width=sim.W * n, height=sim.H * n)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._img)
        for w in (self.hit_label, self.preview_note):
            w.config(wraplength=sim.W * n)

    def _refresh_texts(self):
        dt = self.dt
        parts = []
        for d in te.DAYTIMES:
            st = self.radio_state[d]
            parts.append("%s: %s" % (te.DAYTIME_NAMES[d].lower(), te.STATE_TEXT[st] if st else "з рації ще не читали"))
            if self.touched[d]:
                parts[-1] += " (є незаписані зміни)"
        self.info.config(text="Стан: " + "; ".join(parts) + ".")
        mc = te.match_counts(self.colors[dt], dt)
        self.match_label.config(text="Збіг зі стоковою (%s): українська %d з %d, класична %d з %d." % (
            te.DAYTIME_NAMES[dt].lower() + " тема", mc["ua"], te.ITEM_COUNT, mc["classic"], te.ITEM_COUNT))
        weak = te.weak_pairs(self.colors[dt])
        if weak:
            self.warn_label.config(text="Слабкий контраст (%d): %s." % (len(weak), "; ".join(
                "%s -- %.1f:1" % (te.pair_label(fg, bg), c) for fg, bg, c, _need, _t in weak[:4]) + ("; ..." if len(weak) > 4 else "")))
        else:
            self.warn_label.config(text="")
        names = [n for _k, n, _d, _c in te.available_sets(dt)]
        self._set_list = te.available_sets(dt)
        self.set_combo.config(values=names)
        if self.set_var.get() not in names:
            self.set_var.set(names[0])
        self._show_set_desc()

    def _show_set_desc(self):
        for _k, n, d, _c in getattr(self, "_set_list", []):
            if n == self.set_var.get():
                self.set_desc.config(text=d)
                return

    def after_refresh(self):
        pass

    # --- дії над робочою копією --------------------------------------------------------------------

    def _on_daytime(self):
        self._selected = None
        self._redraw()

    def set_color(self, index, v565, touch=True):
        self.colors[self.dt][index] = v565
        if touch:
            self.touched[self.dt] = True
        self._redraw()

    def _on_pick(self, index):
        self._selected = index
        key, name, desc = te.ITEMS[index]
        cur = te.to_hex(self.colors[self.dt][index])
        rgb, hexv = colorchooser.askcolor(color=cur, parent=self.shell, title="%s -- %s" % (name, te.DAYTIME_NAMES[self.dt].lower()))
        if not hexv:
            self._redraw()
            return
        new = te.from_hex(hexv)
        if new != self.colors[self.dt][index]:
            self.set_color(index, new)
        else:
            self._redraw()

    def _on_preview_click(self, event):
        if self._display is None:
            return
        n = int(self.scale_var.get())
        item = sim.hit_item(self._display, event.x // n, event.y // n)
        if item is None:
            return
        self.hit_label.config(text="Піксель (%d, %d): %s" % (event.x // n, event.y // n, te.ITEMS[item][1]))
        self.select_item(item)

    def select_item(self, index):
        """Підсвітити колір у списку й прокрутити до нього."""
        self._selected = index
        self._redraw()
        try:
            self.update_idletasks()
            host = self.left_host
            total = max(1, host.inner.winfo_reqheight())
            y = self._rows[index]["row"].winfo_rooty() - host.inner.winfo_rooty()
            host.canvas.yview_moveto(max(0.0, min(1.0, (y - 60) / float(total))))
        except tk.TclError:
            pass

    def apply_set(self, set_key):
        for k, n, _d, cols in te.available_sets(self.dt):
            if k == set_key:
                self.colors[self.dt] = list(cols)
                self.touched[self.dt] = True
                self._redraw()
                self._status("Набір «%s» застосовано до %s теми (ще не в рації)." % (n, te.DAYTIME_NAMES[self.dt].lower()[:-1] + "ої"), "info")
                return True
        return False

    def _on_apply_set(self):
        name = self.set_var.get()
        for k, n, _d, _c in te.available_sets(self.dt):
            if n == name:
                self.apply_set(k)
                return

    def _on_reset(self):
        self.reset_to_stock("ua")

    def _on_reset_classic(self):
        self.reset_to_stock("classic")

    def reset_to_stock(self, variant=te.DEFAULT_VARIANT):
        self.colors[self.dt] = te.stock_colors(self.dt, variant)
        self.touched[self.dt] = True
        self._redraw()
        self._status("%s тему скинуто до стокової (%s). У рацію вона потрапить після «Записати теми в рацію»."
                     % (te.DAYTIME_NAMES[self.dt], te.VARIANT_NAMES[variant].lower()), "info")

    # --- файл ---------------------------------------------------------------------------------------
    # Основний формат -- `.gtm` стокового CPS (рівно 64 байти). Другий варіант -- текстовий OpenTYT-theme-1 (розширення .txt).

    GTM_TYPES = [("Тема CPS OpenGD77 (*.gtm)", "*.gtm"), ("Текстовий формат OpenTYT (*.txt)", "*.txt"), ("Усі файли", "*.*")]

    @staticmethod
    def is_text_path(path):
        return path.lower().endswith(".txt")

    def save_file(self, path):
        """Зберегти відкриту тему: *.txt -- текстовий формат OpenTYT, інакше -- .gtm (ті самі 64 байти, що пішли б у блок рації)."""
        if self.is_text_path(path):
            te.save_file(path, self.dt, self.colors[self.dt])
        else:
            te.save_gtm(path, self.colors[self.dt])

    def load_file(self, path):
        """Завантажити файл у робочу копію. .gtm -- у ВІДКРИТУ тему (у файлі позначки день/ніч немає); *.txt -- у ту, що вказана в файлі
        (перемикає). ThemeFileError/GtmError -- пояснення для користувача, кольори не змінюються. Повертає daytime, до якої застосовано."""
        if self.is_text_path(path):
            dt, cols = te.load_file(path)
            self.daytime.set(dt)
        else:
            cols = te.load_gtm(path)
            dt = self.dt
        self.colors[dt] = cols
        self.touched[dt] = True
        self._selected = None
        self._redraw()
        print("Файл %s застосовано до %s теми." % (path, {"day": "денної", "night": "нічної"}[dt]))
        return dt

    def _on_save_file(self):
        path = filedialog.asksaveasfilename(parent=self.shell, title="Зберегти тему у файл", defaultextension=te.GTM_EXT, initialdir=output_dir(),
                                            initialfile=("d" if self.dt == "day" else "n") + te.GTM_EXT, filetypes=self.GTM_TYPES)
        if not path:
            return
        try:
            self.save_file(path)
        except (OSError, te.ThemeFileError, ValueError) as e:
            messagebox.showerror("Теми", "Не вдалося зберегти: %s" % e, parent=self.shell)
            return
        self._status("%s тему збережено: %s" % (te.DAYTIME_NAMES[self.dt], path), "ok")

    def _on_load_file(self):
        path = filedialog.askopenfilename(parent=self.shell, title="Завантажити тему з файлу", initialdir=output_dir(), filetypes=self.GTM_TYPES)
        if not path:
            return
        if not self.is_text_path(path):
            hint = te.gtm_name_hint(path)
            if hint and hint != self.dt:
                # лише підказка за ІМЕНЕМ файла: у самому .gtm день/ніч не позначено, тож вибору тут нема -- або в відкриту тему, або скасувати
                if not gd.confirm_dialog(self.shell, "Файл схожий на іншу тему",
                                         "Ім'я файла «%s» схоже на %s тему, а в панелі відкрита %s. У самому файлі .gtm день чи ніч не позначено, тож це лише "
                                         "здогад за іменем.\n\nЗавантажити файл у відкриту %s тему?" % (
                                             os.path.basename(path), "нічну" if hint == "night" else "денну", "нічна" if self.dt == "night" else "денна",
                                             "нічну" if self.dt == "night" else "денну"),
                                         yes="Завантажити у відкриту", no="Скасувати"):
                    return
        try:
            dt = self.load_file(path)
        except (OSError, te.ThemeFileError, te.GtmError) as e:
            extra = ("" if self.is_text_path(path) else " (Текстовий файл OpenTYT має мати розширення .txt.)")
            messagebox.showerror("Теми", "Файл не підійшов: %s%s" % (e, extra), parent=self.shell)
            return
        self._status("%s тему завантажено з файлу (ще не в рації)." % te.DAYTIME_NAMES[dt], "info")

    # --- рація --------------------------------------------------------------------------------------

    def _on_read(self):
        if self.shell.busy:
            return
        if any(self.touched.values()):
            if not gd.confirm_dialog(self.shell, "Прочитати з рації?", "Читання замінить усі кольори в цьому розділі тими, що зараз у рації; "
                                     "незаписані зміни пропадуть. Продовжити?", yes="Прочитати", no="Скасувати"):
                return
        self.shell.run_task(self._read_worker, "Читаю теми з рації...", plain_errors=True)

    def _read_worker(self):
        ser = cps.open_radio()
        try:
            result = {}
            for dt in te.DAYTIMES:
                result[dt] = te.read_theme(ser, dt)
                print("%s тема: %s" % (te.DAYTIME_NAMES[dt], te.STATE_TEXT[result[dt][0]]))
        finally:
            ser.close()
        self.shell.post(lambda: self.apply_read(result))

    def apply_read(self, result):
        """Головний потік: {daytime: (стан, кольори|None)} -> робоча копія."""
        for dt, (state, cols) in result.items():
            self.radio_state[dt] = state
            self.touched[dt] = False
            if cols is not None:
                self.colors[dt] = list(cols)
                self.base[dt] = list(cols)
            else:
                self.colors[dt] = te.stock_colors(dt)          # блока нема -- рація показує стокову
                self.base[dt] = te.stock_colors(dt)
        self._redraw()

    def write_plan(self):
        """Які теми буде записано: [daytime] -- ті, що змінені від останнього читання/запису."""
        return [dt for dt in te.DAYTIMES if self.touched[dt]]

    def _on_write(self):
        if self.shell.busy:
            return
        plan = self.write_plan()
        if not plan:
            messagebox.showinfo("Теми", "Немає що записувати: кольори не змінені. Змініть колір, застосуйте набір або завантажте файл.", parent=self.shell)
            return
        for dt in plan:
            if self.radio_state[dt] in (te.ST_NOREGION, te.ST_BADLEN):
                messagebox.showerror("Теми", "%s тему записати не можна: %s." % (te.DAYTIME_NAMES[dt], te.STATE_TEXT[self.radio_state[dt]]), parent=self.shell)
                return
        lines = ["У рацію буде записано: %s." % ", ".join(te.DAYTIME_NAMES[d].lower() for d in plan), ""]
        for dt in plan:
            weak = te.weak_pairs(self.colors[dt])
            if weak:
                lines.append("%s тема: слабкий контраст у %d парах кольорів -- текст може бути важко прочитати." % (te.DAYTIME_NAMES[dt], len(weak)))
        if self.radio_state[plan[0]] is None:
            lines.append("Рацію ще не читали: невідомо, що в ній зараз. Запис замінить тему повністю.")
        lines += ["", "Це змінює рацію одразу (поза кодплагом). Рація підхопить кольори, коли її вимкнути й увімкнути. Нагадування: стокову тему можна "
                  "повернути кнопкою «Скинути до стокової» і новим записом."]
        if not gd.confirm_dialog(self.shell, "Записати теми в рацію?", "\n".join(lines), yes="Записати", no="Скасувати"):
            return
        snapshot = {dt: list(self.colors[dt]) for dt in plan}
        self.shell.run_task(lambda: self._write_worker(snapshot), "Записую теми в рацію...", plain_errors=True)

    def _write_worker(self, snapshot):
        ser = cps.open_radio()
        done = []
        try:
            for dt, cols in snapshot.items():
                print(te.write_theme(ser, dt, cols))
                done.append(dt)
        finally:
            ser.close()
            if done:
                self.shell.post(lambda: self.mark_written({dt: snapshot[dt] for dt in done}))
        print("Вимкни рацію й увімкни: теми вона читає лише при вмиканні.")

    def mark_written(self, written):
        for dt, cols in written.items():
            self.base[dt] = list(cols)
            self.radio_state[dt] = te.ST_OK
            if self.colors[dt] == list(cols):
                self.touched[dt] = False
        self._redraw()
