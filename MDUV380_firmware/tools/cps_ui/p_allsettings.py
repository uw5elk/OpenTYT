# -*- coding: utf-8 -*-
"""Розділ «Налаштування рації → Усі налаштування» (R30 W4): уся область custom-data рації (теми, SMS-пресети й повідомлення, RCTL, APRS, вибір ключа AES)
одним файлом -- щоб перенести налаштування на іншу рацію або повернути їх після дослідів.

«Зберегти всі налаштування у файл» читає область з рації (лише читання) і пише JSON-файл OpenTYT-settings-1 (кожен блок з SHA-256).
«Завантажити з файлу» показує блоки з файла з прапорцями: що застосувати. Типово НЕ позначені: лічильники RCTL (RCTL_STATE -- стан прошивки, а не налаштування)
і блок AES із ключовим матеріалом. «Записати вибране в рацію» пише блок за блоком (custom_data.write_block + звірка читанням); збій на блоці зупиняє решту.
Усе записане в область не стосується кодплага (документ не змінюється). Логіка -- у tools/custom_region.py; тут лише вікно.

R37: блок «Стан області» -- скільки зайнято, скільки вільно, скільки займають вилучені (retire) блоки (числа читаються з області рації); кнопка «Ущільнити область»
(страхова копія -> безпечний запис -> звірка; tools/custom_compact.py) і «Відновити область зі страхової копії...»."""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import cps_link as cps
import custom_compact as cc
import custom_region as cr
import gui_theme as gt

from .common import output_dir
from .layout import FlowFrame, equal_buttons
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
                                              "Це не кодплаг: канали, зони й контакти тут не зберігаються (для них -- «Бекап і відновлення»).",
                    purpose="перенести налаштування рації (теми, SMS, RCTL, APRS, вибір ключа AES) на іншу рацію або повернути їх після дослідів.")
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=12, pady=(4, 4))
        self.save_btn = ttk.Button(bar, text="Зберегти всі налаштування у файл...", command=self._on_save)
        self.save_btn.pack(side="left")
        self.reg(self.save_btn)
        self.load_btn = ttk.Button(bar, text="Завантажити з файлу...", command=self._on_load)
        self.load_btn.pack(side="left", padx=8)
        self.reg(self.load_btn, radio=False)          # файл читається з диска, рація не потрібна

        # R37: стан області custom-data й ущільнення
        box = ttk.LabelFrame(self, text="Стан області custom-data в рації (64 КіБ на всі блоки разом)")
        box.pack(fill="x", padx=12, pady=(4, 4))
        self.state_label = ttk.Label(box, text="Стан ще не прочитано: натисни «Показати стан області» (рація читається, нічого не пишеться).", wraplength=600,
                                     justify="left")
        self.state_label.pack(anchor="w", padx=8, pady=(6, 2))
        self.state_warn = ttk.Label(box, text="", foreground=gt.P["warn"], wraplength=600, justify="left")
        self.state_warn.pack(anchor="w", padx=8, pady=(0, 2))
        sbar = FlowFrame(box)
        sbar.pack(fill="x", padx=8, pady=(2, 4))
        self.state_btn = ttk.Button(sbar, text="Показати стан області", command=self._on_state)
        self.compact_btn = ttk.Button(sbar, text="Ущільнити область", command=self._on_compact)
        self.safety_btn = ttk.Button(sbar, text="Відновити область зі страхової копії...", command=self._on_restore_safety)
        equal_buttons(self.state_btn, self.compact_btn)
        for b in (self.state_btn, self.compact_btn, self.safety_btn):
            sbar.add(b)
        self.reg(self.state_btn)
        self.reg(self.compact_btn, radio=True, write=True)
        self.reg(self.safety_btn, radio=True, write=True)
        ttk.Label(box, text=("Вилучення блока (картинка, мелодія) лише ховає його від рації, а місце не звільняє: область 64 КіБ поступово заповнюється. «Ущільнити область» "
                             "збирає живі блоки підряд і викидає вилучені. Перед записом зберігається страхова копія ВСІЄЇ області у файл (без успішної копії запис не "
                             "починається); запис іде так, що обірваний запис рація прочитає як «області нема» (типові налаштування), а не як покручений вміст; після запису "
                             "область перечитується й звіряється байт у байт, а рація перезавантажується."),
                  wraplength=600, justify="left", foreground=gt.P["muted"]).pack(anchor="w", padx=8, pady=(0, 6))

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

    # --- R37: стан області й ущільнення ------------------------------------------------------------------

    def _read_prog(self, done, total):
        self.shell.cps_progress(100.0 * done / max(1, total), "Читаю область з рації...")

    def _on_state(self):
        if self.shell.busy:
            return
        self.shell.run_task(self.state_worker, "Читаю область custom-data...", plain_errors=True, on_done=self.show_state, ok_status="Стан області прочитано.")

    def state_worker(self):
        ser = cps.open_radio()
        try:
            return cr.read_radio_region(cps.CpsLink(ser), self._read_prog)
        finally:
            ser.close()

    def show_state(self, data):
        """Показати стан області (байти з рації)."""
        lines = cc.state_text(data).split("\n")
        warn = [l for l in lines if l.startswith("УВАГА")]
        self.state_label.config(text="\n".join(l for l in lines if not l.startswith("УВАГА")))
        self.state_warn.config(text="\n".join(warn))

    def _on_compact(self):
        if self.shell.busy:
            return
        self.shell.run_task(self.compact_worker, "Ущільнюю область custom-data...", plain_errors=True, on_done=self._show_compacted, ok_status="Готово.",
                            reconnect_ms=6000)

    def compact_worker(self):
        ser = cps.open_radio()
        try:
            return cc.compact_region(cps.CpsLink(ser), self.shell.confirm_from_worker, output_dir(), progress=self.shell.cps_progress, log=print)
        finally:
            try:
                ser.close()
            except Exception:  # noqa: BLE001
                pass

    def _show_compacted(self, res):
        failed = not res.get("ok", True)
        if res.get("plan") is not None and res.get("ok") and not res.get("cancelled"):
            self.state_label.config(text="Щойно ущільнено. Натисни «Показати стан області», щоб побачити поточні числа після перезавантаження рації.")
            self.state_warn.config(text="")
        (messagebox.showerror if failed else messagebox.showinfo)("Ущільнення області", res["text"], parent=self.shell)

    def _on_restore_safety(self):
        if self.shell.busy:
            return
        path = filedialog.askopenfilename(parent=self.shell, title="Страхова копія області custom-data", initialdir=output_dir(),
                                          filetypes=[("Страхова копія області (*.bin)", "*.bin"), ("Усі файли", "*.*")])
        if not path:
            return
        self.shell.run_task(lambda: self.restore_safety_worker(path), "Повертаю область зі страхової копії...", plain_errors=True, on_done=self._show_compacted,
                            ok_status="Готово.", reconnect_ms=6000)

    def restore_safety_worker(self, path):
        ser = cps.open_radio()
        try:
            return cc.restore_safety_copy(cps.CpsLink(ser), path, self.shell.confirm_from_worker, progress=self.shell.cps_progress, log=print)
        finally:
            try:
                ser.close()
            except Exception:  # noqa: BLE001
                pass
