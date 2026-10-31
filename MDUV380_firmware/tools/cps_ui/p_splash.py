# -*- coding: utf-8 -*-
"""Розділ «Налаштування рації → Заставка» (R35 B): картинка, яку рація показує при вмиканні (custom-data блок IMAGE).

ВАЖЛИВО (з коду прошивки, див. tools/splash_image.py): картинка -- МОНОХРОМНА 128 x 64 точки, 1 біт на точку (1024 Б), а не кольорова 160 x 128. Дві фарби беруться з ТЕМИ
екрана (колір переднього плану й тла заставки), тож у денній і нічній темі вона виглядає по-різному; передпоказ малюється рендером екрана з розділу «Теми» (x4).
Блок не є частиною кодплага: «Записати заставку в рацію» змінює рацію одразу. Рація показує картинку лише коли в кодплазі (розділ «Основна інформація») екран вітання = картинка.
«Прибрати картинку» вилучає блок; без блока рація сама малює текстову заставку.
Файли: PNG (усі типи), BMP, PBM/PGM/PPM. JPEG без зовнішньої бібліотеки не читається -- збережи його як PNG."""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import cps_link as cps
import gui_dialogs as gd
import gui_theme as gt
import screen_sim as sim
import splash_image as si
import theme_edit as te

from .common import output_dir
from .panel import Panel

SCALES = (4, 5)


class SplashPanel(Panel):
    key = "splash"
    title = "Заставка"

    def __init__(self, parent, shell):
        super().__init__(parent, shell)
        self.gray = None                 # si.Gray з файла
        self.src_name = ""
        self.ink = None                  # що буде записано / показано (128x64, 1 = передній план)
        self.radio_ink = None            # що зараз у рації
        self.radio_state = None
        self.radio_len = None
        self.daytime = tk.StringVar(value="night")
        self.fit_var = tk.StringVar(value="fit")
        self.quant_var = tk.StringVar(value="dither")
        self.thr_var = tk.IntVar(value=128)
        self.invert_var = tk.BooleanVar(value=False)
        self.scale_var = tk.IntVar(value=4)
        self._build_ui()
        self._redraw()

    # --- побудова ---------------------------------------------------------------------------------

    def _build_ui(self):
        self.header("Заставка", "Картинка при вмиканні рації. Рація показує МОНОХРОМНУ картинку 128 x 64 (дві фарби з теми екрана), а не кольорову: джерело буде зведено до "
                                "двох кольорів, а передпоказ нижче -- саме те, що намалює рація в обраній темі. Блок лежить в окремій області флеша, тому запис змінює рацію одразу.",
                    purpose="поставити власну картинку на екран вітання рації або повернути текстову заставку.")
        top = ttk.LabelFrame(self, text="1. Картинка")
        top.pack(fill="x", padx=12, pady=6)
        row = ttk.Frame(top)
        row.pack(fill="x", padx=8, pady=(6, 2))
        self.open_btn = ttk.Button(row, text="Відкрити файл (PNG, BMP, PBM/PGM/PPM)...", command=self._on_open)
        self.open_btn.pack(side="left")
        self.reg(self.open_btn, radio=False)
        self.use_radio_btn = ttk.Button(row, text="Показати картинку з рації", command=self._on_show_radio)
        self.use_radio_btn.pack(side="left", padx=8)
        self.src_label = ttk.Label(top, text="Файл не відкрито.", foreground=gt.P["muted"], wraplength=640, justify="left")
        self.src_label.pack(anchor="w", padx=8, pady=(0, 4))
        opts = ttk.Frame(top)
        opts.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Label(opts, text="Вписування:").grid(row=0, column=0, sticky="w")
        for i, (k, t) in enumerate(si.FIT_MODES):
            ttk.Radiobutton(opts, text=t, value=k, variable=self.fit_var, command=self._on_option).grid(row=0, column=1 + i, sticky="w", padx=(8, 0))
        ttk.Label(opts, text="Зведення до 2 кольорів:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        for i, (k, t) in enumerate(si.QUANT_MODES):
            ttk.Radiobutton(opts, text=t, value=k, variable=self.quant_var, command=self._on_option).grid(row=1, column=1 + i, sticky="w", padx=(8, 0), pady=(4, 0))
        ttk.Label(opts, text="Поріг яскравості:").grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.thr_scale = ttk.Scale(opts, from_=1, to=254, orient="horizontal", variable=self.thr_var, command=lambda _v: self._on_option(), length=260)
        self.thr_scale.grid(row=2, column=1, columnspan=3, sticky="w", padx=8, pady=(4, 0))
        ttk.Checkbutton(opts, text="Інвертувати (поміняти місцями колір переднього плану й тла)", variable=self.invert_var, command=self._on_option).grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(4, 0))
        prow = ttk.Frame(top)
        prow.pack(fill="x", padx=8, pady=(4, 6))
        ttk.Label(prow, text="Тема передпоказу:").pack(side="left")
        for k, t in (("night", "нічна"), ("day", "денна")):
            ttk.Radiobutton(prow, text=t, value=k, variable=self.daytime, command=self._on_option).pack(side="left", padx=(8, 0))
        ttk.Label(prow, text="Масштаб:").pack(side="left", padx=(16, 0))
        for n in SCALES:
            ttk.Radiobutton(prow, text="x%d" % n, value=n, variable=self.scale_var, command=self._on_option).pack(side="left", padx=(8, 0))
        self.info_label = ttk.Label(top, text="", foreground=gt.P["muted"], wraplength=640, justify="left")
        self.info_label.pack(anchor="w", padx=8, pady=(0, 6))
        self.canvas = tk.Canvas(self, bg=gt.P["bg"], highlightthickness=1, highlightbackground=gt.P["muted"])
        self.canvas.pack(padx=12, pady=6, anchor="w")
        ttk.Label(self, text=("Передпоказ використовує стокові кольори обраної теми (розділ «Теми»); на рації береться активна тема з її власними кольорами. "
                              "Поля навколо картинки (екран 160 x 128, картинка 128 x 64 з відступом 16 x 32) -- колір тла заставки."),
                  wraplength=640, justify="left", foreground=gt.P["muted"]).pack(anchor="w", padx=12)

        rad = ttk.LabelFrame(self, text="2. Рація")
        rad.pack(fill="x", padx=12, pady=6)
        bar = ttk.Frame(rad)
        bar.pack(fill="x", padx=8, pady=(6, 2))
        self.read_btn = ttk.Button(bar, text="Прочитати з рації", command=self._on_read)
        self.read_btn.pack(side="left")
        self.reg(self.read_btn)
        self.write_btn = ttk.Button(bar, text="Записати заставку в рацію...", command=self._on_write)
        self.write_btn.pack(side="left", padx=8)
        self.reg(self.write_btn)
        self.remove_btn = ttk.Button(bar, text="Прибрати картинку...", command=self._on_remove)
        self.remove_btn.pack(side="left", padx=8)
        self.reg(self.remove_btn)
        bar2 = ttk.Frame(rad)
        bar2.pack(fill="x", padx=8, pady=(2, 4))
        self.save_radio_btn = ttk.Button(bar2, text="Зберегти картинку з рації у PNG...", command=self._on_save_radio_png)
        self.save_radio_btn.pack(side="left")
        self.save_prev_btn = ttk.Button(bar2, text="Зберегти передпоказ у PNG...", command=self._on_save_preview_png)
        self.save_prev_btn.pack(side="left", padx=8)
        self.state_label = ttk.Label(rad, text="Рацію ще не читали.", foreground=gt.P["muted"], wraplength=640, justify="left")
        self.state_label.pack(anchor="w", padx=8, pady=(0, 2))
        self.boot_label = ttk.Label(rad, text="", foreground=gt.P["warn"], wraplength=640, justify="left")
        self.boot_label.pack(anchor="w", padx=8, pady=(0, 6))

    # --- перетворення -----------------------------------------------------------------------------

    @property
    def bright_is_ink(self):
        """Яскраві точки джерела стають кольором ПЕРЕДНЬОГО плану, якщо передній план світліший за тло обраної теми (нічна: світле на темному); «Інвертувати» міняє це."""
        cols = te.stock_colors(self.daytime.get())
        names = [k for k, _n, _d in te.ITEMS]
        fg = te.rgb565_to_888(cols[names.index("FG_SPLASHSCREEN")])
        bg = te.rgb565_to_888(cols[names.index("BG_SPLASHSCREEN")])
        def lum(v):
            return ((v >> 16) & 255) * 299 + ((v >> 8) & 255) * 587 + (v & 255) * 114
        bright = lum(fg) >= lum(bg)
        return bright != self.invert_var.get()

    def recompute(self):
        """Джерело -> self.ink за поточними параметрами (без вікон). Нічого не робить, якщо файл не відкрито."""
        if self.gray is None:
            return
        self.ink = si.convert(self.gray, self.fit_var.get(), self.quant_var.get(), int(self.thr_var.get()), self.bright_is_ink)

    def load_image_bytes(self, data, name=""):
        """Прийняти байти файла (PNG/BMP/PNM). ImageError -- пояснення; поточний стан не змінюється."""
        g = si.decode(data)
        self.gray, self.src_name = g, name
        self.recompute()
        return g

    def _on_open(self):
        path = filedialog.askopenfilename(parent=self.shell, title="Картинка заставки", initialdir=output_dir(),
                                          filetypes=[("Картинки", "*.png *.bmp *.pbm *.pgm *.ppm"), ("Усі файли", "*.*")])
        if not path:
            return
        try:
            with open(path, "rb") as f:
                data = f.read()
            g = self.load_image_bytes(data, path.replace("\\", "/").split("/")[-1])
        except (OSError, si.ImageError) as e:
            messagebox.showerror("Заставка", "Файл не підійшов: %s" % e, parent=self.shell)
            return
        self.src_label.config(text="%s: %d x %d точок." % (self.src_name, g.w, g.h))
        self._redraw()

    def _on_show_radio(self):
        if self.radio_ink is None:
            messagebox.showinfo("Заставка", "Спершу прочитай картинку з рації.", parent=self.shell)
            return
        self.gray = None
        self.ink = self.radio_ink
        self.src_label.config(text="Показано картинку, прочитану з рації.")
        self._redraw()

    def _on_option(self, *_a):
        self.recompute()
        self._redraw()

    # --- малювання --------------------------------------------------------------------------------

    def preview_display(self):
        """Екран заставки з поточною картинкою (або порожній, якщо картинки нема) -- рендер із «Тем»."""
        ink = self.ink if self.ink is not None else bytes(si.W * si.H)
        return si.splash_display(ink, sim.IT["FG_SPLASHSCREEN"], sim.IT["BG_SPLASHSCREEN"])

    def _redraw(self):
        d = self.preview_display()
        n = int(self.scale_var.get())
        img = tk.PhotoImage(width=sim.W, height=sim.H)
        img.put(" ".join(sim.render_rows(d, te.stock_colors(self.daytime.get()))), to=(0, 0))
        self._img = img.zoom(n, n) if n > 1 else img
        self.canvas.config(width=sim.W * n, height=sim.H * n)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._img)
        if self.ink is None:
            self.info_label.config(text="Картинку не вибрано: на передпоказі лише тло заставки.")
        else:
            lit = sum(self.ink)
            self.info_label.config(text="Блок для запису: %d Б. Точок переднього плану %d з %d." % (si.BLOCK_LEN, lit, si.W * si.H))
        self._update_state_label()

    def _update_state_label(self):
        if self.radio_state is None:
            text = "Рацію ще не читали."
        else:
            text = "У рації: " + si.STATE_TEXT[self.radio_state] + "."
            if self.radio_len is not None and self.radio_state == si.ST_BADLEN:
                text += " Довжина блока %d Б." % self.radio_len
        self.state_label.config(text=text)
        doc = self.shell.doc
        warn = ""
        if doc is not None:
            try:
                import codeplug_edit as ce
                if ce.basic_values(doc.image)["intro_text"]:
                    warn = ("У відкритому кодплазі екран вітання = ТЕКСТ: рація не покаже картинку, поки в «Основній інформації» не обрати «картинка» і не записати кодплаг. "
                            "(Записана картинка від цього не зникає.)")
            except Exception:  # noqa: BLE001 -- документ без цих полів не має ламати вікно
                warn = ""
        else:
            warn = "Картинка показується лише коли в кодплазі екран вітання = «картинка» (розділ «Основна інформація»)."
        self.boot_label.config(text=warn)

    # --- рація ------------------------------------------------------------------------------------

    def _on_read(self):
        if self.shell.busy:
            return
        self.shell.run_task(self._read_worker, "Читаю картинку з рації...", plain_errors=True)

    def _read_worker(self):
        ser = cps.open_radio()
        try:
            state, ink, ln = si.read_image(ser)
        finally:
            ser.close()
        self.shell.post(lambda: self.apply_read(state, ink, ln))

    def apply_read(self, state, ink, ln):
        self.radio_state, self.radio_ink, self.radio_len = state, ink, ln
        if ink is not None and self.ink is None:
            self.ink = ink
            self.src_label.config(text="Показано картинку, прочитану з рації.")
        self._redraw()

    def _on_write(self):
        if self.shell.busy:
            return
        if self.ink is None:
            messagebox.showinfo("Заставка", "Спершу відкрий картинку.", parent=self.shell)
            return
        if self.radio_state in (si.ST_NOREGION, si.ST_BADLEN):
            messagebox.showerror("Заставка", "Записати не можна: %s." % si.STATE_TEXT[self.radio_state], parent=self.shell)
            return
        lines = ["У рацію буде записано картинку заставки: 128 x 64, 1 біт на точку (1024 Б).", ""]
        if self.radio_state == si.ST_OK:
            lines.append("Поточна картинка в рації буде замінена.")
        elif self.radio_state is None:
            lines.append("Рацію ще не читали: невідомо, чи є в ній картинка.")
        lines += ["", "Це змінює рацію одразу (поза кодплагом). Картинку рація показує при вмиканні, якщо екран вітання в кодплазі = «картинка»."]
        if not gd.confirm_dialog(self.shell, "Записати картинку в рацію?", "\n".join(lines), yes="Записати", no="Скасувати"):
            return
        ink = bytes(self.ink)
        self.shell.run_task(lambda: self._write_worker(ink), "Записую картинку в рацію...", plain_errors=True,
                            on_done=lambda t: messagebox.showinfo("Заставка", t, parent=self.shell))

    def _write_worker(self, ink):
        ser = cps.open_radio()
        try:
            text = si.write_image(ser, ink)
        finally:
            ser.close()
        print(text)
        self.shell.post(lambda: self.apply_read(si.ST_OK, ink, si.BLOCK_LEN))
        return text

    def _on_remove(self):
        if self.shell.busy:
            return
        if not gd.confirm_dialog(self.shell, "Прибрати картинку?", "Блок картинки в рації буде вилучено: прошивка перестане його бачити й малюватиме текстову заставку.\n\n"
                                 "Місце, яке займала картинка (1032 Б), лишиться зайнятим у області — нова картинка піде в наступний вільний слот. "
                                 "Це не зачіпає кодплаг і інші блоки.", yes="Прибрати", no="Скасувати"):
            return
        self.shell.run_task(self._remove_worker, "Прибираю картинку з рації...", plain_errors=True, on_done=lambda t: messagebox.showinfo("Заставка", t, parent=self.shell))

    def _remove_worker(self):
        ser = cps.open_radio()
        try:
            text = si.remove_image(ser)
        finally:
            ser.close()
        print(text)
        self.shell.post(lambda: self.apply_read(si.ST_ABSENT, None, None))
        return text

    # --- збереження у PNG -------------------------------------------------------------------------

    def _save_png(self, data, title, name):
        path = filedialog.asksaveasfilename(parent=self.shell, title=title, defaultextension=".png", initialdir=output_dir(), initialfile=name,
                                            filetypes=[("PNG", "*.png"), ("Усі файли", "*.*")])
        if not path:
            return None
        with open(path, "wb") as f:
            f.write(data)
        messagebox.showinfo("Заставка", "Збережено: %s" % path, parent=self.shell)
        return path

    def radio_png(self):
        if self.radio_ink is None:
            raise si.ImageError("картинку з рації ще не прочитано (або її там нема)")
        return si.ink_to_gray_png(self.radio_ink)

    def preview_png(self):
        if self.ink is None:
            raise si.ImageError("картинку не вибрано")
        cols = te.stock_colors(self.daytime.get())
        names = [k for k, _n, _d in te.ITEMS]
        fg = te.rgb565_to_888(cols[names.index("FG_SPLASHSCREEN")])
        bg = te.rgb565_to_888(cols[names.index("BG_SPLASHSCREEN")])
        rgb = lambda v: ((v >> 16) & 255, (v >> 8) & 255, v & 255)       # noqa: E731
        return si.screen_png(self.ink, rgb(fg), rgb(bg), int(self.scale_var.get()))

    def _on_save_radio_png(self):
        try:
            data = self.radio_png()
        except si.ImageError as e:
            messagebox.showinfo("Заставка", str(e), parent=self.shell)
            return
        self._save_png(data, "Зберегти картинку з рації", cps.timestamp_name("splash_radio", ".png"))

    def _on_save_preview_png(self):
        try:
            data = self.preview_png()
        except si.ImageError as e:
            messagebox.showinfo("Заставка", str(e), parent=self.shell)
            return
        self._save_png(data, "Зберегти передпоказ", cps.timestamp_name("splash_preview", ".png"))
