# -*- coding: utf-8 -*-
"""CpsApp -- головне вікно: ліворуч дерево розділів, праворуч панель обраного розділу, внизу рядок стану й журнал, що згортається.

Оболонка дає панелям спільні сервіси (панелі їх не дублюють):
  log / set_status / set_progress     -- журнал, рядок стану, смуга прогресу (одні на все вікно);
  run_task(...)                       -- фонова операція: stdout -> журнал, одна операція за раз (один USB), блокування кнопок;
  confirm_from_worker(text, plan)     -- запитати підтвердження з робочого потоку (діалог показує головний потік);
  post(fn) / post_progress / cps_progress -- безпечне оновлення інтерфейсу з робочого потоку;
  conn                                -- єдине підключення до рації (пошук один раз + кеш);
  show(key) / get_panel(key)          -- перейти до розділу / отримати його панель;
  doc                                 -- ДОКУМЕНТ кодплага (cps_ui/document.py) або None: один образ у пам'яті, з якого працюють усі
                                         панелі групи «Кодплаг»; дії над ним (відкрити / зберегти / записати / відкинути) -- doc_actions.py.

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
from .doc_actions import DocActions
from .p_aes import AesPanel
from .p_aprs import AprsPanel
from .p_backup import BackupPanel
from .p_basic import BasicInfoPanel
from .p_channels import ChannelsPanel
from .p_connect import ConnectionPanel
from .p_csv import CsvPanel
from .p_flash import FlashPanel
from .p_rctl import RctlPanel
from .p_screenshot import ScreenshotPanel
from .p_tglists import TgListsPanel
from .p_viewer import ViewerPanel
from .p_zones import ZonesPanel
from .panel import BUSY_REASON, HINT_NO_DOC, ScrollFrame
from .settings import Settings

# Дерево розділів: (ключ групи, назва, опис, [класи панелей]). Новий розділ = новий клас Panel + рядок тут.
SECTIONS = [
    ("grp_radio", "Рація", [ConnectionPanel, FlashPanel, ScreenshotPanel]),
    ("grp_codeplug", "Кодплаг", [BackupPanel, ViewerPanel, BasicInfoPanel, ChannelsPanel, ZonesPanel, TgListsPanel, AprsPanel,
                                  CsvPanel]),
    ("grp_settings", "Налаштування рації", [AesPanel, RctlPanel]),
]
DEFAULT_SECTION = "conn"
STATUS_COLORS = {"ok": "ok", "info": "info", "err": "err", "warn": "warn", "muted": "muted"}


class CpsApp(DocActions, tk.Tk):
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
        self.aes_slots = None         # {"occupied": (номери,)} після «Оновити список зайнятих слотів»; матеріалу ключів тут нема
        self._task = None
        self.init_document()
        self._panels = {}
        self._hosts = {}
        self._current = None
        self._normal_size = None
        self._defs = {}
        for gkey, gtitle, classes in SECTIONS:
            self._defs[gkey] = {"cls": None, "title": gtitle, "children": classes}
            for cls in classes:
                self._defs[cls.key] = {"cls": cls, "title": cls.title, "group": gkey}

        self._build_ui()
        self.update_doc_ui()
        self._apply_saved_window()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Configure>", self._on_configure)
        self._poll_id = self.after(50, self._poll_queue)
        start = self.settings.get("section")
        self.show(start if start in self._defs else DEFAULT_SECTION)
        self._sash_done = False
        self.bind("<Map>", self._on_first_map)
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
        lw, lh = self._measure_sashes()
        if lw and lw >= 120:
            self.settings.set("left_width", lw)
        if lh and lh >= 40:
            self._log_h = lh
        if self._log_h >= 40:
            self.settings.set("log_height", int(self._log_h))
        return self.settings.save()

    def _on_close(self):
        if self.busy and not messagebox.askyesno(
                "Іде операція", "Операція з рацією ще триває. Закрити програму зараз? Це може перервати запис.", default="no"):
            return
        if not self.confirm_leave_document("закрити програму"):
            return
        self.save_settings()
        self.destroy()

    # --- побудова ---------------------------------------------------------------------

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        style = ttk.Style(self)
        style.configure("Sash", sashthickness=6, gripcount=0)
        # Дерево зливається з лівою колонкою (без власної рамки й окремого тла): порожнє місце під пунктами не виглядає «коробкою».
        style.configure("Nav.Treeview", rowheight=24, background=gt.P["bg"], fieldbackground=gt.P["bg"], bordercolor=gt.P["bg"],
                        lightcolor=gt.P["bg"], darkcolor=gt.P["bg"], borderwidth=0)
        style.map("Nav.Treeview", background=[("selected", gt.P["select_bg"])], foreground=[("selected", gt.P["select_fg"])])
        style.layout("Nav.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

        # Вертикальна межа: зверху дерево + панель, знизу журнал (перетягується). Горизонтальна: дерево | панель (перетягується).
        self.vpane = ttk.PanedWindow(self, orient="vertical")
        self.vpane.grid(row=0, column=0, sticky="nsew")
        self.hpane = ttk.PanedWindow(self.vpane, orient="horizontal")
        self.vpane.add(self.hpane, weight=1)

        left = ttk.Frame(self.hpane, width=int(self.settings.get("left_width", 300) or 300))
        self.hpane.add(left, weight=0)
        ttk.Label(left, text=APP_TITLE, font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=12, pady=(10, 0))
        ttk.Label(left, text=self.build_info, foreground=gt.P["muted"], wraplength=270, justify="left").pack(anchor="w", padx=12)
        ttk.Label(left, text="Автор: UW5ELK", foreground=gt.P["muted"]).pack(anchor="w", padx=12, pady=(0, 8))
        self.tree = ttk.Treeview(left, show="tree", selectmode="browse", style="Nav.Treeview")
        self.tree.column("#0", width=200, stretch=True)
        self.tree.pack(fill="both", expand=True, padx=(8, 0), pady=0)
        self.tree.tag_configure("dim", foreground=gt.P["muted"])
        for gkey, gtitle, classes in SECTIONS:
            self.tree.insert("", "end", iid=gkey, text=gtitle, open=True)
            for cls in classes:
                self.tree.insert(gkey, "end", iid=cls.key, text=cls.title)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        self.right = ttk.Frame(self.hpane)
        self.hpane.add(self.right, weight=1)
        self.right.columnconfigure(0, weight=1)
        self.right.rowconfigure(1, weight=1)
        self._build_docbar()

        # журнал (згортається; висота за замовчуванням -- 4 рядки, межу можна тягнути)
        self.log_frame = ttk.Frame(self.vpane)
        self.log_frame.columnconfigure(0, weight=1)
        self.log_frame.rowconfigure(1, weight=1)
        head = ttk.Frame(self.log_frame)
        head.grid(row=0, column=0, sticky="ew", padx=8, pady=(2, 0))
        ttk.Label(head, text="Журнал").pack(side="left")
        self.clear_btn = ttk.Button(head, text="Очистити", command=self.clear_log)
        self.clear_btn.pack(side="right")
        self.log_text = scrolledtext.ScrolledText(self.log_frame, height=4, state="disabled", font=("Consolas", 9))
        gt.style_text(self.log_text)
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=8, pady=(2, 4))
        self._log_open = bool(self.settings.get("log_open", True))
        self._log_h = int(self.settings.get("log_height", 0) or 0)
        if self._log_open:
            self.vpane.add(self.log_frame, weight=0)

        # рядок стану: текст зліва; смужка прогресу з'являється ЛИШЕ на час операції; кнопка журналу справа
        bar = ttk.Frame(self)
        bar.grid(row=1, column=0, sticky="ew")
        ttk.Separator(bar, orient="horizontal").pack(fill="x")
        inner = ttk.Frame(bar)
        inner.pack(fill="x", padx=8, pady=4)
        self.status_label = ttk.Label(inner, text="Готово до роботи.", foreground=gt.P["ok"])
        self.status_label.pack(side="left")
        self.log_toggle = ttk.Button(inner, text="", command=self.toggle_log)
        self.log_toggle.pack(side="right")
        self.doc_label = ttk.Label(inner, text="Кодплаг не відкрито", foreground=gt.P["muted"])
        self.doc_label.pack(side="right", padx=12)
        self.progress = ttk.Progressbar(inner, mode="determinate", maximum=100, length=220)    # не пакується, доки нема операції
        self._progress_shown = False
        self._update_log_toggle()

    # --- межі панелей: збереження й відновлення ---------------------------------------------------

    def _on_first_map(self, e):
        """Межі панелей можна ставити лише коли вікно вже показано (до цього віджети мають розмір 1x1): одразу й ще раз за мить,
        коли вікно встигло розгорнутись на весь екран."""
        if e.widget is not self or self._sash_done:
            return
        self._sash_done = True
        self.after_idle(self._restore_sashes)
        self.after(250, self._restore_sashes)

    def _restore_sashes(self):
        """Після першого показу вікна: ширина лівої колонки й висота журналу з налаштувань (або типові)."""
        try:
            self.update_idletasks()
            lw = self.settings.get("left_width")
            if isinstance(lw, int) and lw >= 120:
                self.hpane.sashpos(0, lw)
            self._place_log_sash()
        except tk.TclError:
            pass

    def _default_log_height(self):
        return 100        # заголовок + 4 рядки

    def _place_log_sash(self):
        if not self._log_open:
            return
        try:
            h = self.vpane.winfo_height()
            if h <= 1:
                return
            want = self._log_h if self._log_h >= 40 else self._default_log_height()
            self.vpane.sashpos(0, max(100, h - want))
        except tk.TclError:
            pass

    def _measure_sashes(self):
        """(ширина лівої колонки, висота журналу) за поточним положенням меж; None, якщо не виміряти."""
        left_w = log_h = None
        try:
            left_w = int(self.hpane.sashpos(0))
        except tk.TclError:
            pass
        if self._log_open:
            try:
                log_h = int(self.vpane.winfo_height() - self.vpane.sashpos(0))
            except tk.TclError:
                pass
        return left_w, log_h

    # --- панель документа -------------------------------------------------------------------

    def _build_docbar(self):
        """Над усіма розділами: дії над документом кодплага. Недоступне не зникає, а вимкнено з причиною (docbar_note)."""
        bar = ttk.Frame(self.right)
        bar.grid(row=0, column=0, sticky="ew")
        self.docbar = bar
        row = ttk.Frame(bar)
        row.pack(fill="x", padx=12, pady=(6, 2))
        self._docbtn_row = row
        self._docbtn_items = [ttk.Label(row, text="Кодплаг:", font=("Segoe UI", 10, "bold"))]
        self.docbtn = {}
        for key, text, cmd in (("open_radio", "Відкрити з рації", lambda: self.doc_open_radio()),
                               ("open_file", "Відкрити з бекапу...", lambda: self.doc_open_file()),
                               ("save_as", "Зберегти як...", lambda: self.doc_save_as()),
                               ("write", "Записати в рацію", lambda: self.doc_write()),
                               ("discard", "Відкинути зміни", lambda: self.doc_discard())):
            b = ttk.Button(row, text=text, command=cmd)
            self.docbtn[key] = b
            self._docbtn_items.append(b)
        self._docbtn_layout = None
        row.bind("<Configure>", self._relayout_docbar)
        self._relayout_docbar()
        self.docbar_note = ttk.Label(bar, text="", wraplength=700, justify="left", foreground=gt.P["warn"])
        self._docbar_note_shown = False
        ttk.Separator(bar, orient="horizontal").pack(fill="x", pady=(4, 0), side="bottom")

    def _relayout_docbar(self, _e=None):
        """Кнопки документа в один рядок, а коли вікно вузьке -- переносяться на наступний (нічого не обрізається)."""
        w = self._docbtn_row.winfo_width()
        if w <= 1:
            w = 100000                      # ще не показано: усе в один рядок, перекладемо при першому <Configure>
        plan, x, r, c = [], 0, 0, 0
        for it in self._docbtn_items:
            iw = it.winfo_reqwidth() + 8
            if c and x + iw > w:
                r, c, x = r + 1, 0, 0
            plan.append((it, r, c))
            x += iw
            c += 1
        sig = [(id(it), rr, cc_) for it, rr, cc_ in plan]
        if sig == self._docbtn_layout:
            return
        self._docbtn_layout = sig
        for it, rr, cc_ in plan:
            it.grid(row=rr, column=cc_, padx=(0, 8), pady=2, sticky="w")

    def refresh_docbar(self):
        """Стан кнопок документа й підпис-причина поруч (кодплаг заблоковано, рації нема, тип рації не той тощо)."""
        if not hasattr(self, "docbtn"):
            return
        reasons = self.doc_reasons()
        for key, b in self.docbtn.items():
            try:
                b.config(state="disabled" if reasons.get(key) else "normal")
            except tk.TclError:
                pass
        # причина показується один раз: насамперед для «Записати», далі для «Відкрити з рації»; «Відкрийте кодплаг…» -- не причина, а підказка
        shown = ""
        for key in ("write", "open_radio"):
            r = reasons.get(key)
            if r and r not in (HINT_NO_DOC, BUSY_REASON):
                shown = ("Запис у рацію: " if key == "write" else "") + r
                break
        self.docbar_note.config(text=shown)
        if shown and not self._docbar_note_shown:
            self.docbar_note.pack(anchor="w", padx=12, pady=(0, 2))
            self._docbar_note_shown = True
        elif not shown and self._docbar_note_shown:
            self.docbar_note.pack_forget()
            self._docbar_note_shown = False

    # --- дерево і розділи -------------------------------------------------------------------

    def _on_tree_select(self, _e):
        sel = self.tree.selection()
        if sel:
            self._show(sel[0])

    def get_panel(self, key):
        """Панель розділу (створюється при першому зверненні)."""
        if key not in self._panels:
            d = self._defs[key]
            if d["cls"].scroll:
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
        """Перейти до розділу (так само, як клацнути його в дереві). Ключ групи веде до її ПЕРШОГО розділу."""
        key = self._resolve(key)
        if self.tree.selection() != (key,):
            self.tree.selection_set(key)
        self.tree.see(key)
        self._show(key)

    def _resolve(self, key):
        """Група дерева -> її перший розділ (і розгортається); невідомий ключ -> стандартний розділ."""
        if key not in self._defs:
            return DEFAULT_SECTION
        d = self._defs[key]
        if d["cls"] is None:
            self.tree.item(key, open=True)
            return d["children"][0].key
        return key

    def _show(self, key):
        if key not in self._defs:
            return
        if self._defs[key]["cls"] is None:       # клік по групі: розгорнути її й відкрити перший розділ
            self.show(key)
            return
        panel = self.get_panel(key)
        if self._current is not None and self._current != key:
            self._hosts[self._current].grid_remove()
        self._hosts[key].grid(row=1, column=0, sticky="nsew")
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
        """Оновити стан кнопок поточної панелі, панелі документа й приглушення пунктів дерева."""
        self.refresh_docbar()
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
        if self._log_open:
            _lw, lh = self._measure_sashes()
            if lh and lh >= 40:
                self._log_h = lh               # висота, яку лишив користувач, -- для наступного показу
            self.vpane.forget(self.log_frame)
            self._log_open = False
        else:
            self._log_open = True
            self.vpane.add(self.log_frame, weight=0)
            self.update_idletasks()
            self._place_log_sash()
        self._update_log_toggle()
        self.settings.set("log_open", self._log_open)
        self.settings.save()

    def set_status(self, text, kind="info"):
        self.status_label.config(text=text, foreground=gt.P[STATUS_COLORS.get(kind, "info")])

    def set_progress(self, value):
        self.progress["value"] = value

    def _show_progress(self, on):
        """Смужка прогресу видна лише під час операції (після завершення й після помилки ховається)."""
        if on and not self._progress_shown:
            self.progress.pack(side="right", padx=8)
            self._progress_shown = True
        elif not on and self._progress_shown:
            self.progress.pack_forget()
            self._progress_shown = False

    def on_aes_slots_changed(self):
        """Головний потік: панель «AES-ключі» оновила список зайнятих слотів -- редактор каналу перемальовує підказки."""
        for p in self._panels.values():
            if hasattr(p, "on_aes_slots"):
                p.on_aes_slots()

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
        self._show_progress(not quiet)
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
        self._show_progress(False)        # і після успіху, і після помилки
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
