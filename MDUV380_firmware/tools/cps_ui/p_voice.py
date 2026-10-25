# -*- coding: utf-8 -*-
"""Розділ «Налаштування рації → Голосові підказки» (R35 D): область AMBE-фраз, які рація промовляє (формат 'VP', версія 9, 0xAF400..0xD8000).

ЩО РОБИТЬ: показує перелік фраз із рації (номер, призначення, зміщення, довжина, кадри AMBE+2), зберігає область у файл і записує образ із файла назад (для відновлення
або для готового образу від виробника/спільноти), стирає підказки. Власні фрази НЕ створюються: для цього потрібен кодер AMBE+2 (вокодер), якого тут нема, -- див. TESTING.md.
Запис: спершу страхова копія й підтвердження, далі заголовок обнуляється, пишуться дані, справжній заголовок -- останнім (обірваний запис = «підказок нема», а не «зіпсовані»).
Область №2 бази позивних у режимі 'n' лежить НА ТОМУ САМОМУ місці: якщо база її затерла, запис блокується з поясненням. Логіка -- у tools/voice_prompts.py."""
import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import cps_link as cps
import gui_theme as gt
import voice_prompts as vp

from .common import output_dir
from .panel import Panel


class VoicePanel(Panel):
    key = "voice"
    title = "Голосові підказки"

    def __init__(self, parent, shell):
        super().__init__(parent, shell)
        self.info = None                 # voice_prompts.Info того, що показано в таблиці
        self.source = ""                 # "рація" або ім'я файла
        self.file_image = None           # образ із файла (для запису)
        self.file_name = ""
        self.conflict = ("none", "")
        self.cancel_event = threading.Event()
        self.only_present = tk.BooleanVar(value=True)
        self._build_ui()
        self._redraw()

    # --- побудова ---------------------------------------------------------------------------------

    def _build_ui(self):
        self.header("Голосові підказки", "Фрази, які рація промовляє у режимі голосових підказок. Область лежить у флеші рації окремо від кодплага; «Записати з файла» і «Стерти» "
                                         "змінюють рацію одразу. Власних фраз цей розділ не створює (потрібен кодер AMBE+2), але зберігає область у файл і повертає з файла.",
                    purpose="зберегти, переглянути або повернути в рацію голосові підказки.")
        self.db_label = ttk.Label(self, text="", foreground=gt.P["warn"], wraplength=640, justify="left")
        self.db_label.pack(anchor="w", padx=12, pady=(0, 4))
        box = ttk.LabelFrame(self, text="1. Рація")
        box.pack(fill="x", padx=12, pady=6)
        bar = ttk.Frame(box)
        bar.pack(fill="x", padx=8, pady=(6, 2))
        self.read_btn = ttk.Button(bar, text="Що зараз у рації", command=self._on_read)
        self.read_btn.pack(side="left")
        self.reg(self.read_btn)
        self.save_btn = ttk.Button(bar, text="Зберегти з рації у файл...", command=self._on_save)
        self.save_btn.pack(side="left", padx=8)
        self.reg(self.save_btn)
        self.erase_btn = ttk.Button(bar, text="Стерти підказки в рації...", command=self._on_erase)
        self.erase_btn.pack(side="left", padx=8)
        self.reg(self.erase_btn, radio=True, write=True)
        bar2 = ttk.Frame(box)
        bar2.pack(fill="x", padx=8, pady=(2, 2))
        self.open_btn = ttk.Button(bar2, text="Відкрити файл підказок...", command=self._on_open_file)
        self.open_btn.pack(side="left")
        self.reg(self.open_btn, radio=False)
        self.write_btn = ttk.Button(bar2, text="Записати з файла в рацію...", command=self._on_write)
        self.write_btn.pack(side="left", padx=8)
        self.reg(self.write_btn, radio=True, write=True)
        self.cancel_btn = ttk.Button(bar2, text="Скасувати запис", command=self._on_cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=8)
        self.summary_label = ttk.Label(box, text="Рацію ще не читали, файл не відкрито.", wraplength=640, justify="left")
        self.summary_label.pack(anchor="w", padx=8, pady=(4, 6))

        lst = ttk.LabelFrame(self, text="2. Перелік фраз")
        lst.pack(fill="both", expand=True, padx=12, pady=6)
        top = ttk.Frame(lst)
        top.pack(fill="x", padx=8, pady=(6, 2))
        ttk.Checkbutton(top, text="лише наявні фрази", variable=self.only_present, command=self._redraw).pack(side="left")
        self.list_btn = ttk.Button(top, text="Зберегти перелік у файл...", command=self._on_save_list)
        self.list_btn.pack(side="left", padx=12)
        cols = ("n", "label", "off", "len", "frames", "note")
        self.tree = ttk.Treeview(lst, columns=cols, show="headings", height=14, selectmode="browse")
        for c, t, w in (("n", "№", 44), ("label", "Призначення", 220), ("off", "Зміщення", 80), ("len", "Довжина, Б", 90), ("frames", "Кадрів", 60), ("note", "Примітка", 200)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w", stretch=(c == "note"))
        sb = ttk.Scrollbar(lst, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(2, 8))
        sb.pack(side="left", fill="y", pady=(2, 8))

    # --- вигляд -----------------------------------------------------------------------------------

    def _redraw(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        info = self.info
        if info is not None and info.toc:
            for r in vp.rows(info):
                if self.only_present.get() and r["length"] <= 0:
                    continue
                note = []
                if r["silent"]:
                    note.append("нема")
                if r["remainder"]:
                    note.append("не кратна 27")
                if r["oversize"]:
                    note.append("довша за буфер")
                self.tree.insert("", "end", values=(r["index"], r["label"], r["offset"], r["length"], r["frames"], "; ".join(note)))
        self.db_label.config(text=self.conflict[1] if self.conflict[0] != "none" else "")
        if info is None:
            self.summary_label.config(text="Рацію ще не читали, файл не відкрито.")
        else:
            self.summary_label.config(text="Показано: %s.\n%s" % (self.source, vp.summary_text(info)))

    def show_info(self, info, source, conflict=None):
        self.info, self.source = info, source
        if conflict is not None:
            self.conflict = conflict
        self._redraw()

    # --- читання з рації --------------------------------------------------------------------------

    def _on_read(self):
        if self.shell.busy:
            return
        self.shell.run_task(self._read_worker, "Читаю заголовок підказок з рації...", plain_errors=True, ok_status="Прочитано.")

    def _read_worker(self):
        ser = cps.open_radio()
        try:
            link = cps.CpsLink(ser)
            info = vp.read_info(link)
            try:
                conflict = vp.db_conflict(link)
            except Exception as e:  # noqa: BLE001 -- заголовок бази може бути нечитабельним: це не привід не показати підказки
                conflict = ("none", "")
                print("Заголовок бази позивних не прочитано: %s" % e)
        finally:
            ser.close()
        self.shell.post(lambda: self.show_info(info, "рація", conflict))

    def _on_save(self):
        if self.shell.busy:
            return
        path = filedialog.asksaveasfilename(parent=self.shell, title="Зберегти голосові підказки з рації", defaultextension=".bin", initialdir=output_dir(),
                                            initialfile=cps.timestamp_name("voiceprompts", ".bin"), filetypes=[("Образ підказок", "*.bin"), ("Усі файли", "*.*")])
        if not path:
            return
        self.shell.run_task(lambda: self._save_worker(path), "Читаю голосові підказки з рації...", plain_errors=True,
                            on_done=lambda t: messagebox.showinfo("Голосові підказки", t, parent=self.shell), ok_status="Збережено.")

    def _save_worker(self, path):
        ser = cps.open_radio()
        try:
            image = vp.read_image(cps.CpsLink(ser), self.shell.cps_progress)
        finally:
            ser.close()
        with open(path, "wb") as f:
            f.write(image)
        with open(path, "rb") as f:
            if f.read() != image:
                raise vp.VpError("файл підказок записано, але звірка читанням не збіглася: %s" % path)
        info = vp.parse_image(image)
        self.shell.post(lambda: self.show_info(info, "рація (щойно збережено у файл)"))
        text = "Підказки збережено: %s\n%d Б, фраз %d." % (path, len(image), info.present)
        print(text)
        return text

    # --- файл -------------------------------------------------------------------------------------

    def load_file(self, path):
        """Прочитати файл образу. Повертає (образ, Info) або кидає VpError."""
        with open(path, "rb") as f:
            data = f.read()
        if len(data) > vp.VP_MAX:
            raise vp.VpError("файл %d Б більший за область підказок (%d Б)" % (len(data), vp.VP_MAX))
        info = vp.parse_image(data)
        return data, info

    def _on_open_file(self):
        path = filedialog.askopenfilename(parent=self.shell, title="Відкрити файл голосових підказок", initialdir=output_dir(),
                                          filetypes=[("Образ підказок", "*.bin"), ("Усі файли", "*.*")])
        if not path:
            return
        try:
            data, info = self.load_file(path)
        except (OSError, vp.VpError) as e:
            messagebox.showerror("Голосові підказки", str(e), parent=self.shell)
            return
        self.file_image, self.file_name = data, os.path.basename(path)
        self.show_info(info, "файл " + self.file_name)

    def _on_save_list(self):
        if self.info is None or not self.info.toc:
            messagebox.showinfo("Голосові підказки", "Спершу прочитай підказки з рації або відкрий файл.", parent=self.shell)
            return
        path = filedialog.asksaveasfilename(parent=self.shell, title="Зберегти перелік фраз", defaultextension=".txt", initialdir=output_dir(),
                                            initialfile=cps.timestamp_name("voiceprompts_list", ".txt"), filetypes=[("Текст", "*.txt"), ("Усі файли", "*.*")])
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(vp.list_text(self.info, self.only_present.get()) + "\n")
        messagebox.showinfo("Голосові підказки", "Перелік збережено: %s" % path, parent=self.shell)

    # --- запис / стирання -------------------------------------------------------------------------

    def _on_write(self):
        if self.shell.busy:
            return
        if self.file_image is None:
            messagebox.showinfo("Голосові підказки", "Спершу відкрий файл підказок.", parent=self.shell)
            return
        info = vp.parse_image(self.file_image)
        if not info.valid:
            messagebox.showerror("Голосові підказки", "Цей файл записувати не можна: " + "; ".join(info.problems), parent=self.shell)
            return
        image = self.file_image
        self.cancel_event.clear()
        self.cancel_btn.config(state="normal")
        self.shell.run_task(lambda: self._write_worker(image), "Записую голосові підказки в рацію...", plain_errors=True, on_done=self._write_done,
                            fail_suffix="\n\nСтан описано в журналі.", reconnect_ms=8000)

    def _write_worker(self, image):
        ser = cps.open_radio()
        try:
            return vp.write_image(cps.CpsLink(ser), image, self.shell.confirm_from_worker, progress=self.shell.cps_progress, log=print, safety_dir=output_dir(),
                                  cancel=self.cancel_event.is_set)
        finally:
            try:
                ser.close()
            except Exception:  # noqa: BLE001
                pass

    def _write_done(self, res):
        self.cancel_btn.config(state="disabled")
        bad = res.get("failed") or (res.get("written") and res.get("verified") is False)
        (messagebox.showerror if bad else messagebox.showinfo)("Голосові підказки", res["text"], parent=self.shell)

    def _on_cancel(self):
        self.cancel_event.set()
        self.shell.set_status("Скасування: зупинюсь на межі поточного сектора...", "warn")

    def _on_erase(self):
        if self.shell.busy:
            return
        self.cancel_event.clear()
        self.cancel_btn.config(state="normal")
        self.shell.run_task(self._erase_worker, "Стираю голосові підказки в рації...", plain_errors=True, on_done=self._erase_done, fail_suffix="\n\nСтан описано в журналі.",
                            reconnect_ms=8000)

    def _erase_worker(self):
        ser = cps.open_radio()
        try:
            return vp.erase(cps.CpsLink(ser), self.shell.confirm_from_worker, progress=self.shell.cps_progress, log=print, safety_dir=output_dir(),
                            cancel=self.cancel_event.is_set)
        finally:
            try:
                ser.close()
            except Exception:  # noqa: BLE001
                pass

    def _erase_done(self, res):
        self.cancel_btn.config(state="disabled")
        ok = res.get("erased") or res.get("cancelled")
        (messagebox.showinfo if ok else messagebox.showerror)("Голосові підказки", res["text"], parent=self.shell)
