# -*- coding: utf-8 -*-
"""CpsApp -- головне вікно: ліворуч дерево розділів, праворуч панель обраного розділу, внизу рядок стану й журнал, що згортається.

Оболонка дає панелям спільні сервіси (панелі їх не дублюють):
  log / set_status / set_progress     -- журнал, рядок стану, смуга прогресу (одні на все вікно);
  run_task(...)                       -- фонова операція: stdout -> журнал, одна операція за раз (один USB), блокування кнопок;
  confirm_from_worker(text, plan)     -- запитати підтвердження з робочого потоку (діалог показує головний потік);
  post(fn) / post_progress / cps_progress -- безпечне оновлення інтерфейсу з робочого потоку;
  conn                                -- єдине підключення до рації (пошук один раз + кеш);
  show(key) / get_panel(key)          -- перейти до розділу / отримати його панель.

Тема лише темна (gui_theme). Розмір вікна, останній розділ і видимість журналу запам'ятовуються між запусками (settings.py).
"""
import queue
import sys
import threading
import traceback

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

import cps_link as cps
import gui_dialogs as gd
import gui_theme as gt

from .common import APP_TITLE, QueueWriter, load_usb_backend, read_build_info
from .connection import RadioConnection
from .p_aes import AesPanel
from .p_aprs import AprsPanel
from .p_backup import BackupPanel
from .p_connect import ConnectionPanel
from .p_csv import CsvPanel
from .p_flash import FlashPanel
from .p_rctl import RctlPanel
from .p_screenshot import ScreenshotPanel
from .p_viewer import ViewerPanel
from .panel import Panel, ScrollFrame
from .settings import Settings

# Дерево розділів: (ключ групи, назва, опис, [класи панелей]). Новий розділ = новий клас Panel + рядок тут.
SECTIONS = [
    ("grp_radio", "Рація", "Підключення до рації, прошивка і знімок екрана.",
     [ConnectionPanel, FlashPanel, ScreenshotPanel]),
    ("grp_codeplug", "Кодплаг", "Бекап і відновлення, перегляд кодплага, обмін з CSV.",
     [BackupPanel, ViewerPanel, CsvPanel]),
    ("grp_settings", "Налаштування рації", "Параметри, що пишуться в рацію через USB: APRS, AES-ключі, віддалене керування.",
     [AprsPanel, AesPanel, RctlPanel]),
]
DEFAULT_SECTION = "conn"
STATUS_COLORS = {"ok": "ok", "info": "info", "err": "err", "warn": "warn", "muted": "muted"}


class GroupPanel(Panel):
    """Панель-вітрина групи дерева: короткий опис і кнопки переходу до розділів групи."""
    scroll = False

    def __init__(self, parent, shell, key, title, text, children):
        super().__init__(parent, shell)
        self.key = key
        self.title = title
        self.header(title, text)
        for cls in children:
            ttk.Button(self, text=cls.title, command=lambda k=cls.key: shell.show(k)).pack(anchor="w", padx=12, pady=3)


class CpsApp(tk.Tk):
    def __init__(self, settings=None, autoprobe=True):
        super().__init__()
        gt.apply(self)            # темна тема -- до створення будь-яких віджетів
        self.title(APP_TITLE)
        self.minsize(760, 520)
        self.settings = settings or Settings()
        self.queue = queue.Queue()
        self.backend = load_usb_backend()
        self.build_info = read_build_info()
        self.conn = RadioConnection()
        self.busy = False
        self._task = None
        self._panels = {}
        self._hosts = {}
        self._current = None
        self._normal_size = None
        self._defs = {}
        for gkey, gtitle, gtext, classes in SECTIONS:
            self._defs[gkey] = {"cls": None, "title": gtitle, "text": gtext, "children": classes}
            for cls in classes:
                self._defs[cls.key] = {"cls": cls, "title": cls.title, "group": gkey}

        self._build_ui()
        self._apply_saved_window()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Configure>", self._on_configure)
        self._poll_id = self.after(50, self._poll_queue)
        start = self.settings.get("section")
        self.show(start if start in self._defs else DEFAULT_SECTION)
        if autoprobe:
            self.after(150, lambda: self.refresh_connection(force=False))

    # --- вікно: розмір, закриття ----------------------------------------------------------

    def _maximize(self):
        """Вікно відкривається розгорнутим на весь екран. «zoomed» є лише в Windows/macOS-Tk, на Linux -- атрибут «-zoomed»; якщо немає
        ні того, ні іншого -- розмір екрана вручну. Обгорнуто в try/except: збій тут не має заважати запуску."""
        try:
            self.state("zoomed")
            return
        except tk.TclError:
            pass
        try:
            self.attributes("-zoomed", True)
            return
        except tk.TclError:
            pass
        try:
            self.geometry("%dx%d+0+0" % (self.winfo_screenwidth(), self.winfo_screenheight()))
        except tk.TclError:
            pass

    def _is_maximized(self):
        try:
            return self.state() == "zoomed"
        except tk.TclError:
            pass
        try:
            return bool(self.attributes("-zoomed"))
        except tk.TclError:
            return False

    def _apply_saved_window(self):
        w, h = self.settings.get("width"), self.settings.get("height")
        if isinstance(w, int) and isinstance(h, int) and w >= 600 and h >= 400:
            self.geometry("%dx%d" % (min(w, self.winfo_screenwidth()), min(h, self.winfo_screenheight())))
            self._normal_size = (w, h)
            if self.settings.get("zoomed"):
                self._maximize()
        else:
            self.geometry("1000x680")        # перший запуск: на весь екран, як було завжди
            self._maximize()

    def _on_configure(self, e):
        if e.widget is self and not self._is_maximized():
            self._normal_size = (e.width, e.height)

    def save_settings(self):
        w, h = self._normal_size or (self.winfo_width(), self.winfo_height())
        if w >= 600 and h >= 400:         # згорнуте вікно дає безглуздий розмір -- його не запам'ятовуємо
            self.settings.set("width", int(w))
            self.settings.set("height", int(h))
        self.settings.set("zoomed", bool(self._is_maximized()))
        self.settings.set("section", self._current)
        self.settings.set("log_open", bool(self._log_open))
        return self.settings.save()

    def _on_close(self):
        if self.busy and not messagebox.askyesno(
                "Іде операція", "Операція з рацією ще триває. Закрити програму зараз? Це може перервати запис.", default="no"):
            return
        self.save_settings()
        self.destroy()

    # --- побудова ---------------------------------------------------------------------

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        body = ttk.Frame(self)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(2, weight=1)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body, width=300)
        left.grid(row=0, column=0, sticky="ns")
        left.grid_propagate(False)
        ttk.Label(left, text=APP_TITLE, font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=12, pady=(10, 0))
        ttk.Label(left, text=self.build_info, foreground=gt.P["muted"], wraplength=270, justify="left").pack(anchor="w", padx=12)
        ttk.Label(left, text="Автор: UW5ELK", foreground=gt.P["muted"]).pack(anchor="w", padx=12, pady=(0, 8))
        style = ttk.Style(self)
        style.configure("Nav.Treeview", rowheight=28)
        self.tree = ttk.Treeview(left, show="tree", selectmode="browse", style="Nav.Treeview")
        self.tree.column("#0", width=270, stretch=True)
        self.tree.pack(fill="both", expand=True, padx=(8, 4), pady=(0, 8))
        self.tree.tag_configure("dim", foreground=gt.P["muted"])
        for gkey, gtitle, _gtext, classes in SECTIONS:
            self.tree.insert("", "end", iid=gkey, text=gtitle, open=True)
            for cls in classes:
                self.tree.insert(gkey, "end", iid=cls.key, text=cls.title)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        ttk.Separator(body, orient="vertical").grid(row=0, column=1, sticky="ns")
        self.right = ttk.Frame(body)
        self.right.grid(row=0, column=2, sticky="nsew")
        self.right.columnconfigure(0, weight=1)
        self.right.rowconfigure(0, weight=1)

        # журнал (згортається)
        self.log_frame = ttk.Frame(self)
        self.log_frame.columnconfigure(0, weight=1)
        head = ttk.Frame(self.log_frame)
        head.grid(row=0, column=0, sticky="ew", padx=8, pady=(4, 0))
        ttk.Label(head, text="Журнал").pack(side="left")
        self.clear_btn = ttk.Button(head, text="Очистити", command=self.clear_log)
        self.clear_btn.pack(side="right")
        self.log_text = scrolledtext.ScrolledText(self.log_frame, height=9, state="disabled", font=("Consolas", 9))
        gt.style_text(self.log_text)
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=8, pady=(2, 6))
        self._log_open = bool(self.settings.get("log_open", True))
        if self._log_open:
            self.log_frame.grid(row=1, column=0, sticky="ew")

        # рядок стану
        bar = ttk.Frame(self)
        bar.grid(row=2, column=0, sticky="ew")
        ttk.Separator(bar, orient="horizontal").pack(fill="x")
        inner = ttk.Frame(bar)
        inner.pack(fill="x", padx=8, pady=4)
        self.status_label = ttk.Label(inner, text="Готово до роботи.", foreground=gt.P["ok"])
        self.status_label.pack(side="left")
        self.log_toggle = ttk.Button(inner, text="", command=self.toggle_log)
        self.log_toggle.pack(side="right")
        self.progress = ttk.Progressbar(inner, mode="determinate", maximum=100, length=220)
        self.progress.pack(side="right", padx=8)
        self._update_log_toggle()

    # --- дерево і розділи -------------------------------------------------------------------

    def _on_tree_select(self, _e):
        sel = self.tree.selection()
        if sel:
            self._show(sel[0])

    def get_panel(self, key):
        """Панель розділу (створюється при першому зверненні)."""
        if key not in self._panels:
            d = self._defs[key]
            if d["cls"] is None:
                panel = GroupPanel(self.right, self, key, d["title"], d["text"], d["children"])
                host = panel
            elif d["cls"].scroll:
                host = ScrollFrame(self.right)
                panel = d["cls"](host.inner, self)
                panel.pack(fill="both", expand=True)
            else:
                panel = d["cls"](self.right, self)
                host = panel
            self._panels[key] = panel
            self._hosts[key] = host
        return self._panels[key]

    def show(self, key):
        """Перейти до розділу (так само, як клацнути його в дереві)."""
        if key not in self._defs:
            key = DEFAULT_SECTION
        if self.tree.selection() != (key,):
            self.tree.selection_set(key)
        self.tree.see(key)
        self._show(key)

    def _show(self, key):
        if key not in self._defs:
            return
        panel = self.get_panel(key)
        if self._current is not None and self._current != key:
            self._hosts[self._current].grid_remove()
        self._hosts[key].grid(row=0, column=0, sticky="nsew")
        changed = key != self._current
        self._current = key
        panel.on_show()
        if changed:
            self.settings.set("section", key)
            self.settings.save()

    @property
    def current_key(self):
        return self._current

    def section_keys(self):
        return list(self._defs)

    def _refresh_all(self):
        """Оновити стан кнопок поточної панелі й приглушення пунктів дерева."""
        if self._current is not None and self._current in self._panels:
            self._panels[self._current].refresh_state()
        for key, d in self._defs.items():
            cls = d["cls"]
            dim = bool(cls is not None and cls.radio_only and not self.conn.found)
            self.tree.item(key, tags=("dim",) if dim else ())

    # --- журнал, стан, прогрес -----------------------------------------------------------------

    def log(self, text):
        if threading.current_thread() is not threading.main_thread():
            self.queue.put(("log", text))
            return
        self.log_text.config(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def clear_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    def _update_log_toggle(self):
        self.log_toggle.config(text="Сховати журнал" if self._log_open else "Показати журнал")

    def toggle_log(self):
        self._log_open = not self._log_open
        if self._log_open:
            self.log_frame.grid(row=1, column=0, sticky="ew")
        else:
            self.log_frame.grid_remove()
        self._update_log_toggle()
        self.settings.set("log_open", self._log_open)
        self.settings.save()

    def set_status(self, text, kind="info"):
        self.status_label.config(text=text, foreground=gt.P[STATUS_COLORS.get(kind, "info")])

    def set_progress(self, value):
        self.progress["value"] = value

    def post(self, fn):
        """Виконати fn() у головному потоці (безпечно викликати з робочого)."""
        self.queue.put(("call", fn))

    def post_progress(self, pct):
        self.queue.put(("progress", pct))

    def cps_progress(self, pct, text):
        self.queue.put(("progress", pct))
        self.queue.put(("status", text))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                try:
                    if kind == "log":
                        self.log(payload)
                    elif kind == "progress":
                        self.progress["value"] = payload
                    elif kind == "status":
                        self.set_status(payload, "info")
                    elif kind == "call":
                        payload()
                    elif kind == "confirm":
                        self._on_confirm_request(*payload)
                    elif kind == "taskdone":
                        self._on_task_done(*payload)
                except Exception:  # noqa: BLE001 -- помилка в обробнику не повинна зупиняти опитування черги
                    self.log("!!! Внутрішня помилка інтерфейсу:\n" + traceback.format_exc())
        except queue.Empty:
            pass
        self._poll_id = self.after(50, self._poll_queue)

    def destroy(self):
        try:
            self.after_cancel(self._poll_id)
        except (AttributeError, tk.TclError):
            pass
        super().destroy()

    # --- підтвердження з робочого потоку ----------------------------------------------------------

    def confirm_from_worker(self, text, _plan=None):
        """Викликається з робочого потоку: питання показує головний потік, цей потік чекає на відповідь."""
        done = threading.Event()
        answer = {"yes": False}
        self.queue.put(("confirm", (text, done, answer)))
        done.wait()
        return answer["yes"]

    def _on_confirm_request(self, text, done, answer):
        try:
            answer["yes"] = bool(gd.confirm_dialog(self, "Підтвердження запису в рацію", text, yes="Записати в рацію", no="Скасувати"))
        finally:
            done.set()

    # --- підключення ---------------------------------------------------------------------------------

    def refresh_connection(self, force=False):
        """Знайти рацію й прочитати її RADIO_INFO (у фоні). Не плутається під ногами іншої операції: чекає, поки вона закінчиться."""
        if self.busy:
            if force:
                self.set_status("Зачекай завершення поточної операції, тоді натисни «Оновити».", "warn")
            else:
                self.after(1500, self.refresh_connection)
            return
        self.conn.invalidate()
        self._refresh_all()
        self.run_task(self.conn.probe, "Шукаю рацію...", quiet=True, ok_status=None, on_done=self._probe_done)

    def _probe_done(self, conn):
        if conn.found:
            self.set_status("Рацію знайдено: {}.".format(conn.port), "ok")
        else:
            self.set_status("Рацію не знайдено.", "warn")
        self.set_progress(0)

    # --- виконавець фонових операцій -------------------------------------------------------------------

    def run_task(self, fn, status_text, on_done=None, fail_suffix="\n\nФайл не збережено.", plain_errors=False, ok_status="Готово.",
                 quiet=False, reconnect_ms=None):
        """Запустити fn() у потоці (stdout -> журнал). Одна операція за раз.
        on_done(result)  -- після успіху (у головному потоці); без неї для звичайних (не plain) завдань показується «Збережено: ...».
        fail_suffix      -- дописується до тексту помилки у вікні;
        plain_errors     -- помилка = str(виняток) у вікні «Щось пішло не так: ...» (так було в AES, RCTL, APRS);
        ok_status        -- текст рядка стану після успіху (None -- не чіпати, його виставить on_done);
        quiet            -- без розділювача в журналі й без вікон помилок (фонове опитування);
        reconnect_ms     -- після завершення повторно знайти рацію (вона перезавантажується / змінила порт)."""
        if self.busy:
            return False
        self.busy = True
        self._task = {"on_done": on_done, "fail_suffix": fail_suffix, "plain": plain_errors, "ok_status": ok_status, "quiet": quiet,
                      "reconnect_ms": reconnect_ms}
        self.progress["value"] = 0
        self.set_status(status_text, "info")
        if not quiet:
            self.log("=" * 30)
            self.log(status_text)
        self._refresh_all()

        def worker():
            old_stdout = sys.stdout
            sys.stdout = QueueWriter(self.queue)
            ok, reason, result = False, None, None
            try:
                result = fn()
                ok = True
            except cps.CpsError as e:
                reason = str(e)
            except SystemExit as e:
                reason = "exit_{}".format(e.code)
            except Exception as e:  # noqa: BLE001 -- показуємо будь-яку помилку, не ховаємо
                reason = str(e) if plain_errors else "несподівана помилка: {}".format(e)
            finally:
                sys.stdout = old_stdout
                self.queue.put(("taskdone", (ok, reason, result)))

        threading.Thread(target=worker, daemon=True).start()
        return True

    def _on_task_done(self, ok, reason, result):
        t, self._task = self._task, None
        self.busy = False
        if not ok and reason and "рацію не знайдено" in reason.lower():
            self.conn.mark_absent()
        self._refresh_all()
        if t["reconnect_ms"]:
            self.after(t["reconnect_ms"], self.refresh_connection)
        if ok:
            if t["ok_status"]:
                self.progress["value"] = 100
                self.set_status(t["ok_status"], "ok")
            if t["on_done"] is not None:
                t["on_done"](result)
            elif not t["plain"] and not t["quiet"]:
                messagebox.showinfo("Готово", "Збережено:\n" + "\n".join(result or []))
            return
        self.set_status("Помилка." if t["plain"] else "Не вдалося.", "err")
        self.log("!!! Помилка: {}".format(reason))
        if t["quiet"]:
            return
        if t["plain"]:
            messagebox.showerror("Помилка", "Щось пішло не так: {}".format(reason))
            return
        full = "{}{}".format(reason, t["fail_suffix"])
        if full.count("\n") > 8 or len(full) > 700:          # довгий перелік проблем імпорту -- у темному вікні з прокруткою
            gd.text_dialog(self, "Помилка", full)
        else:
            messagebox.showerror("Помилка", full)


def main():
    try:
        app = CpsApp()
        app.mainloop()
    except Exception as e:  # noqa: BLE001 -- останній рубіж: показати хоч щось, а не мовчки згаснути
        detail = traceback.format_exc()
        try:
            messagebox.showerror("Помилка запуску", "{}\n\n{}".format(e, detail))
        except Exception:
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(0, "{}\n\n{}".format(e, detail), "TYT MD-UV390UKR -- Помилка запуску", 0x10)
            except Exception:
                pass
        sys.exit(1)
