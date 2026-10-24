# -*- coding: utf-8 -*-
"""Розділ «Налаштування рації → Усі налаштування» (R30 W4): уся область custom-data рації (теми, SMS-пресети й повідомлення, RCTL, APRS, вибір ключа AES)
одним файлом -- щоб перенести налаштування на іншу рацію або повернути їх після дослідів.

«Зберегти всі налаштування у файл» читає область з рації (лише читання) і пише JSON-файл OpenTYT-settings-1 (кожен блок з SHA-256).
«Завантажити з файлу» показує блоки з файла з прапорцями: що застосувати. Типово НЕ позначені: лічильники RCTL (RCTL_STATE -- стан прошивки, а не налаштування)
і блок AES із ключовим матеріалом. «Записати вибране в рацію» пише блок за блоком (custom_data.write_block + звірка читанням); збій на блоці зупиняє решту.
Усе записане в область не стосується кодплага (документ не змінюється). Логіка -- у tools/custom_region.py; тут лише вікно."""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import cps_link as cps
import custom_region as cr
import gui_theme as gt

from .common import output_dir
from .panel import Panel


class AllSettingsPanel(Panel):
    key = "allsettings"
    title = "Усі налаштування"

    def __init__(self, parent, shell):
        super().__init__(parent, shell)
        self.blocks = []             # блоки з завантаженого файла
        self.file_doc = None
        self.file_path = None
        self.sel_vars = {}           # тип блока -> BooleanVar
        self._rows = []
        self._build_ui()

    def _build_ui(self):
        self.header("Усі налаштування рації", "Одним файлом -- уся область custom-data рації: теми екрана, SMS (пресети й повідомлення), RCTL, APRS, вибір ключа AES. "
                                              "Це не кодплаг: канали, зони й контакти тут не зберігаються (для них -- «Бекап і відновлення»).")
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=12, pady=(4, 4))
        self.save_btn = ttk.Button(bar, text="Зберегти всі налаштування у файл...", command=self._on_save)
        self.save_btn.pack(side="left")
        self.reg(self.save_btn)
        self.load_btn = ttk.Button(bar, text="Завантажити з файлу...", command=self._on_load)
        self.load_btn.pack(side="left", padx=8)
        self.reg(self.load_btn, radio=False)          # файл читається з диска, рація не потрібна

        self.file_label = ttk.Label(self, text="Файл не завантажено.", foreground=gt.P["muted"], wraplength=600, justify="left")
        self.file_label.pack(anchor="w", padx=12, pady=(2, 2))
        self.list_box = ttk.LabelFrame(self, text="Блоки у файлі: що застосувати до рації")
        self.list_box.pack(fill="x", padx=12, pady=4)
        self.empty_label = ttk.Label(self.list_box, text="Завантаж файл, щоб побачити блоки.", foreground=gt.P["muted"])
        self.empty_label.pack(anchor="w", padx=8, pady=6)

        self.apply_btn = ttk.Button(self, text="Записати вибране в рацію", command=self._on_apply)
        self.apply_btn.pack(anchor="w", padx=12, pady=(4, 2))
        self.reg(self.apply_btn, radio=True, write=True)
        self.warn = ttk.Label(self, text=("Блок записується в рацію одразу, поза кодплагом, і перезаписує наявний блок такого ж типу. Довжину наявного блока змінити не можна "
                                          "(так само, як у прошивці) -- такий блок буде пропущено з поясненням. Перед записом зроби бекап (він теж зберігає цю область). "
                                          "Після запису рація перезавантажується сама (без збереження пам'яті), щоб тема, повідомлення й лічильники взялися зі щойно записаного."),
                              wraplength=600, justify="left", foreground=gt.P["muted"])
        self.warn.pack(anchor="w", padx=12, pady=(0, 6))

    # --- файл ---------------------------------------------------------------------------------------

    def _on_save(self):
        if self.shell.busy:
            return
        path = filedialog.asksaveasfilename(parent=self.shell, title="Зберегти всі налаштування у файл", defaultextension=".json", initialdir=output_dir(),
                                            initialfile=cps.timestamp_name("radio_settings", ".json"),
                                            filetypes=[("Налаштування рації OpenTYT (*.json)", "*.json"), ("Усі файли", "*.*")])
        if not path:
            return
        self.shell.run_task(lambda: self.save_worker(path), "Читаю налаштування з рації...", plain_errors=True,
                            on_done=lambda r: messagebox.showinfo("Налаштування збережено", r, parent=self.shell), ok_status="Налаштування збережено.")

    def save_worker(self, path):
        """Читає область з рації й пише файл. Повертає текст підсумку."""
        ser = cps.open_radio()
        try:
            link = cps.CpsLink(ser)
            info = link.radio_info()
            blocks, _region = cr.read_settings_from_radio(link, self.shell.cps_progress)
        finally:
            ser.close()
        cr.save_settings_file(path, blocks, info)
        print("Збережено: %s" % path)
        text = "Збережено блоків: %d (%s).\n%s" % (len(blocks), ", ".join(b.title for b in blocks) or "жодного", path)
        if any(b.secret for b in blocks):
            text += "\n\nУВАГА: у блоці AES є ключовий матеріал -- зберігай цей файл як секрет."
        if any(b.type == 7 for b in blocks):
            text += "\nУ файлі є SMS-повідомлення (особисті тексти)."
        return text

    def _on_load(self):
        path = filedialog.askopenfilename(parent=self.shell, title="Завантажити налаштування з файлу", initialdir=output_dir(),
                                          filetypes=[("Налаштування рації OpenTYT (*.json)", "*.json"), ("Усі файли", "*.*")])
        if not path:
            return
        try:
            self.load_file(path)
        except cr.SettingsFileError as e:
            messagebox.showerror("Усі налаштування", "Файл не підійшов: %s" % e, parent=self.shell)

    def load_file(self, path):
        """Завантажити файл налаштувань і показати блоки з прапорцями. SettingsFileError -- пояснення, список не змінюється."""
        blocks, doc = cr.load_settings_file(path)
        self.blocks, self.file_doc, self.file_path = blocks, doc, path
        self._rebuild_list()

    def _rebuild_list(self):
        for w in self.list_box.winfo_children():
            w.destroy()
        self.sel_vars = {}
        self._rows = []
        created = (self.file_doc or {}).get("createdUtc", "?")
        self.file_label.config(text="Файл: %s (створено %s UTC; блоків: %d)." % (self.file_path, created, len(self.blocks)))
        if not self.blocks:
            ttk.Label(self.list_box, text="У файлі немає жодного блока.", foreground=gt.P["muted"]).pack(anchor="w", padx=8, pady=6)
            return
        for b in self.blocks:
            v = tk.BooleanVar(value=cr.default_selected(b))
            self.sel_vars[b.type] = v
            note = ""
            if b.kind == "state":
                note = " -- стан прошивки, не налаштування; типово не застосовується"
            elif b.secret:
                note = " -- містить ключовий матеріал AES; типово не застосовується"
            cb = ttk.Checkbutton(self.list_box, text="%s (%s, %d Б)%s" % (b.title, b.name, b.length, note), variable=v)
            cb.pack(anchor="w", padx=8, pady=1)
            self._rows.append(cb)

    def selected_types(self):
        return {t for t, v in self.sel_vars.items() if v.get()}

    # --- запис у рацію ------------------------------------------------------------------------------

    def _on_apply(self):
        if self.shell.busy:
            return
        if not self.blocks:
            messagebox.showinfo("Усі налаштування", "Спершу завантаж файл налаштувань.", parent=self.shell)
            return
        sel = self.selected_types()
        if not sel:
            messagebox.showinfo("Усі налаштування", "Не позначено жодного блока.", parent=self.shell)
            return
        blocks = list(self.blocks)
        self.shell.run_task(lambda: self.apply_worker(blocks, sel), "Записую налаштування в рацію...", plain_errors=True,
                            on_done=self._show_done, ok_status="Готово.")

    def apply_worker(self, blocks, selected):
        ser = cps.open_radio()
        try:
            return cr.apply_settings(cps.CpsLink(ser), blocks, selected, confirm=self.shell.confirm_from_worker, progress=self.shell.cps_progress, log=print)
        finally:
            try:
                ser.close()
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _show_done(res):
        failed = bool(res.get("result") and res["result"].get("failed"))
        (messagebox.showerror if failed else messagebox.showinfo)("Усі налаштування", res["text"])
