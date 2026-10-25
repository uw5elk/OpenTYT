# -*- coding: utf-8 -*-
"""Дії над документом кодплага (CPS-doc): відкрити з рації / з бекапу, зберегти як…, записати в рацію, відкинути зміни, питання про
незбережені зміни. Це домішка до CpsApp (self -- вікно): документ живе в self.doc, ніхто інший його не тримає.

Запис у рацію НЕ має власної дороги: образ іде в cps_csv.write_image_via_restore -> cps_restore.restore_codeplug (страхова копія -> діалог зі
списком змін -> лише відмінні сектори -> перечитування -> SHA-256 -> C 6 1). Сектор калібрування й 20 байтів квіккеїв там виключені.
"""
import os
from tkinter import filedialog, messagebox

import codeplug_view as cpview
import cps_csv as cc
import cps_link as cps
import cps_restore as cps_rest
import gui_dialogs as gd
import phase_timing

from . import document as D
from .common import APP_TITLE, output_dir
from .p_backup import close_quietly, show_restore_result
from .panel import BUSY_REASON, HINT_NO_DOC

WRITE_TITLE = "ЗАПИС КОДПЛАГА З ДОКУМЕНТА -- рація буде ПЕРЕЗАПИСАНА."
ZIP_TYPES = [("Бекап кодплага (.zip)", "*.zip"), ("Усі файли", "*.*")]


class DocActions:
    """Домішка: потребує від CpsApp полів doc, busy, conn, і методів run_task / cps_progress / confirm_from_worker / set_status / log."""

    # ----------------------------------------------------------------- стан

    def init_document(self):
        self.doc = None

    def set_document(self, doc):
        """Зробити doc поточним документом (або None -- закрити). Старий документ відпускається без питань: питати має той, хто викликає."""
        if self.doc is not None:
            try:
                self.doc._listeners.remove(self._on_doc_event)
            except ValueError:
                pass
        self.doc = doc
        if doc is not None:
            doc.add_listener(self._on_doc_event)
        self._on_doc_event(doc)

    def _on_doc_event(self, _doc):
        self.update_doc_ui()
        for key, panel in self._panels.items():
            panel.doc_event(visible=(key == self._current))

    def update_doc_ui(self):
        """Заголовок вікна (зірочка), рядок стану, кнопки панелі документа."""
        d = self.doc
        self.title("%s — %s" % (d.title_text(), APP_TITLE) if d is not None else APP_TITLE)
        self.doc_label.config(text=d.status_text() if d is not None else "Кодплаг не відкрито",
                              foreground=self._doc_color())
        self.refresh_docbar()

    def _doc_color(self):
        import gui_theme as gt
        if self.doc is None:
            return gt.P["muted"]
        return gt.P["warn"] if self.doc.modified else gt.P["ok"]

    # ----------------------------------------------------------------- причини вимкнення кнопок

    def doc_reasons(self):
        """{кнопка: причина або None}: причини, чому дії панелі документа зараз недоступні."""
        busy = BUSY_REASON if self.busy else None
        d = self.doc
        radio = None if self.conn.found else self.conn.reason()
        out = {"open_radio": busy or radio, "open_file": busy, "save_as": busy or (HINT_NO_DOC if d is None else None),
               "discard": busy or (HINT_NO_DOC if d is None else (None if d.modified else "Незбережених змін немає."))}
        if busy:
            w = busy
        elif d is None:
            w = HINT_NO_DOC
        elif not cps_rest.RESTORE_UNLOCKED:
            w = cps_rest.LOCKED_CAPTION
        elif d.write_block_reason(self.conn.info if self.conn.found else None):
            w = d.write_block_reason(self.conn.info if self.conn.found else None)
        elif radio:
            w = radio
        else:
            w = None
        out["write"] = w
        return out

    # ----------------------------------------------------------------- питання про незбережені зміни

    def confirm_leave_document(self, action):
        """True -- можна продовжувати `action` (текст дії для діалогу). Якщо є незбережені зміни, питає: зберегти / не зберігати / скасувати."""
        d = self.doc
        if d is None or not d.modified:
            return True
        text = ("У поточному кодплазі є незбережені зміни (%d).\n\nЩо робити перед тим, як %s?\n\n"
                "«Зберегти як…» запише їх у .zip (рація не чіпається), «Не зберігати» відкине їх." % (len(d.changes), action))
        choice = gd.choice_dialog(self, "Незбережені зміни", text,
                                  [("Скасувати", "cancel"), ("Не зберігати", "drop"), ("Зберегти як…", "save")], 0)
        if choice == "drop":
            return True
        if choice == "save":
            return self.doc_save_as()
        return False

    # ----------------------------------------------------------------- відкрити

    def doc_open_file(self, path=None):
        """Відкрити бекап у документ. path=None -- спитати файл."""
        if self.busy:
            return False
        if path is None:
            path = filedialog.askopenfilename(parent=self, title="Бекап кодплага", initialdir=output_dir(), filetypes=ZIP_TYPES)
            if not path:
                return False
        if not self.confirm_leave_document("відкрити інший кодплаг"):
            return False
        try:
            doc = D.from_backup(path)
        except (OSError, cps.CpsError) as e:
            messagebox.showerror("Помилка", "Не вдалося прочитати бекап:\n{}".format(e), parent=self)
            return False
        self.set_document(doc)
        self.set_status("Відкрито: {}.".format(os.path.basename(path)), "ok")
        return True

    def doc_open_radio(self):
        """Прочитати рацію в документ (у фоні)."""
        if self.busy:
            return False
        if not self.confirm_leave_document("прочитати кодплаг із рації"):
            return False
        return self.run_task(self._open_radio_worker, "Читаю кодплаг з рації...", on_done=self._doc_opened_from_radio, fail_suffix="")

    def _open_radio_worker(self):
        ser = cps.open_radio()
        try:
            return D.from_radio(cps.CpsLink(ser), self.cps_progress)
        finally:
            close_quietly(ser)

    def _doc_opened_from_radio(self, doc):
        self.set_document(doc)
        self.set_status("Кодплаг прочитано з рації.", "ok")

    # ----------------------------------------------------------------- зберегти

    def doc_save_as(self):
        """Зберегти документ у .zip (той самий формат, що й бекап). True -- збережено."""
        d = self.doc
        if d is None or self.busy:
            return False
        path = filedialog.asksaveasfilename(parent=self, title="Зберегти кодплаг як…", defaultextension=".zip", initialdir=output_dir(),
                                            initialfile=cps.timestamp_name("codeplug_document", ".zip"), filetypes=ZIP_TYPES)
        if not path:
            return False
        try:
            d.save_as(path)
        except (OSError, cps.CpsError) as e:
            messagebox.showerror("Помилка", "Не вдалося зберегти:\n{}".format(e), parent=self)
            return False
        self.log("Кодплаг збережено: {}".format(path))
        self.set_status("Збережено: {}.".format(os.path.basename(path)), "ok")
        return True

    # ----------------------------------------------------------------- відкинути

    def doc_discard(self):
        d = self.doc
        if d is None or self.busy or not d.modified:
            return False
        if not gd.confirm_dialog(self, "Відкинути зміни?", "Відкинути всі незбережені зміни (%d) і повернути кодплаг до стану "
                                 "останнього відкриття / збереження / запису?" % len(d.changes), yes="Відкинути", no="Скасувати"):
            return False
        d.discard()
        self.set_status("Зміни відкинуто.", "ok")
        return True

    # ----------------------------------------------------------------- записати в рацію

    def doc_write(self):
        d = self.doc
        if d is None or self.busy or self.doc_reasons()["write"]:
            return False
        rev = d.revision
        return self.run_task(lambda: self._write_worker(d), "Записую кодплаг у рацію...", on_done=lambda out: self._doc_written(d, rev, out),
                             fail_suffix="\n\nЯкщо про відмову сказано «Нічого не записано» -- рація не змінена.", reconnect_ms=6000)

    def _write_worker(self, d):
        ser = cps.open_radio()
        try:
            link = cps.CpsLink(ser)
            info = link.radio_info()
            reason = d.write_block_reason(info)
            if reason:
                raise cps.CpsError("{} Нічого не записано.".format(reason))
            fresh, share, prefetched = None, 0, None
            ph = phase_timing.Phases(link)
            if d.origin == D.ORIGIN_RADIO:
                print("Читаю свіжий стан рації: на нього накладуться лише ваші зміни, а не весь застарілий образ.")
                with ph.phase("свіже читання рації"):
                    cp, _m = cpview.codeplug_from_radio(link, lambda p, t: self.cps_progress(int(p * 0.25), t))
                fresh = cc.Image.from_codeplug(cp)
                prefetched = (cp.eeprom, cp.flash)      # R32 T2.2: страхова копія візьме звідси EEPROM і флеш, а не читатиме їх вдруге
                share = 25
            res, conflicts = d.write_image(fresh)
            if conflicts:
                print("Конфліктів зі змінами рації: {}.".format(conflicts))
            out = cc.write_image_via_restore(
                link, res, self.confirm_from_worker, lambda p, t: self.cps_progress(share + int(p * (100 - share) / 100.0), t), log=print,
                title=WRITE_TITLE, out_dir=output_dir(), zip_prefix="codeplug_document-write",
                note="Образ, зібраний із документа кодплага. Це те, що буде записано.", prefetched=prefetched, phases=ph)
            out["written_image"] = res.image
            return out
        finally:
            close_quietly(ser)

    def _doc_written(self, d, rev, out):
        if out.get("nothingToDo") and not out.get("safetyCopy"):
            messagebox.showinfo("Нічого записувати", "Документ не відрізняється від того, що вже є в рації.", parent=self)
        else:
            show_restore_result(out)
        if out.get("cancelled"):
            return
        if self.doc is d and d.revision == rev:
            d.mark_written(out["written_image"])
            self.set_status("Записано в рацію.", "ok")
        else:
            self.log("Документ змінився під час запису -- його стан не оновлено; прочитайте кодплаг з рації ще раз.")
