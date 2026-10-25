# -*- coding: utf-8 -*-
"""Модель документа «кодплаг» (CPS-doc, етап 2). БЕЗ Tk і без рації: усе, що можна перевірити хост-тестами, лежить тут.

Документ -- ОДИН образ кодплага в пам'яті (cps_csv.Image: EEPROM + флеш-частина) плюс те, що потрібно, щоб з ним працювати як із
документом: звідки він узятий (рація / файл), чи є незбережені зміни, список змін, що вже зроблені, і дві «бази»:

  * baseline «збережено»  -- стан на момент відкриття / останнього «Зберегти як…» / останнього запису в рацію. Від нього рахується
                             ознака «змінено» (зірочка в заголовку) і до нього повертає «Відкинути зміни»;
  * база «стан рації»     -- стан, який рація мала в момент читання (або після останнього запису). Від неї рахується, ЩО саме
                             треба записати в рацію (для документа з рації: лише відмінності від цієї бази, накладені на СВІЖЕ читання
                             рації, -- так застарілі «лічильники» рації (поточний канал, зона) не затираються).

Усі правки (контакти, APRS-слоти, основна інформація, імпорт CSV) накладаються на образ документа так само, як раніше накладались на
образ рації: кожна функція повертає ImportResult з новим образом, а документ або приймає його ЦІЛКОМ, або (помилка) лишається як був.
Запис у рацію -- не тут: документ лише готує образ (write_image) і причину, чому запис заборонено (write_block_reason); сам запис іде
через cps_csv.write_image_via_restore -> cps_restore.restore_codeplug (страхова копія, діалог зі змінами, лише відмінні сектори,
перечитування, SHA-256, C 6 1).
"""
import copy
import datetime
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cps_link as cl  # noqa: E402
import cps_csv as cc  # noqa: E402
import cps_restore as cr  # noqa: E402
import codeplug_view as cv  # noqa: E402
import contact_edit as ce  # noqa: E402
import general_edit as ge  # noqa: E402
import codeplug_edit as ced  # noqa: E402

ORIGIN_RADIO = "radio"
ORIGIN_FILE = "file"
STEP = 256                       # крок порівняння при злитті (байти)

KIND_TITLES = (("added", "Нові"), ("changed", "Змінені"), ("removed", "Видалені"))


class DocumentError(cl.CpsError):
    pass


def _snap(img):
    return (bytes(img.eeprom), bytes(img.flash))


def _image(snap, base):
    return cc.Image(snap[0], snap[1], base)


def extra_tables(img):
    """Таблиці, яких нема в codeplug_view: APRS-слоти та DTMF (дані -- ті самі, що йдуть у CSV)."""
    cols = ["№", "Назва"] + cc.APRS_HDR[1:] + ["Без звуку"]
    rows = []
    for slot, rec in img.aprs():
        d = cc.aprs_decode(rec, ".")
        rows.append([str(slot + 1), cc.readable_text(rec[:ced.APRS_NAME_LEN])] + d[1:] + ["True" if rec[61] & ced.APRS_FLAG_SILENT else "False"])
    out = [("aprs", "APRS", cols, rows)]
    drows = [[str(slot + 1), cc.readable_text(rec[:16]), cc.dtmf_code_text(rec[16:32])] for slot, rec in img.dtmf()]
    out.append(("dtmf", "DTMF", ["№", "Назва", "Код"], drows))
    return out


class Document:
    """Один відкритий кодплаг. Конструктор -- з codeplug_view.Codeplug (та сама структура, що дають і бекап, і пряме читання рації)."""

    def __init__(self, codeplug, origin, source_file=None, opened_at=None):
        if origin not in (ORIGIN_RADIO, ORIGIN_FILE):
            raise DocumentError("origin: radio або file")
        self.manifest = copy.deepcopy(codeplug.manifest)
        self.base = codeplug.flash_cp_start
        self.image = cc.Image.from_codeplug(codeplug)
        self.origin = origin
        self.source_file = source_file            # шлях відкритого файла (origin = file)
        self.saved_path = None                    # куди збережено через «Зберегти як…»
        self.opened_at = opened_at or datetime.datetime.now()
        self.changes = []                         # [(kind, розділ, текст)], kind: added / changed / removed
        self.warnings = []
        self._origin_snap = _snap(self.image)     # стан рації на момент читання (для злиття при записі)
        self._saved = (_snap(self.image), 0, [])  # (знімок, довжина списку змін, попередження) на момент збереження
        self.modified = False
        self.revision = 0
        self._view = None
        self._listeners = []

    # ----------------------------------------------------------------- підписи

    def label(self):
        if self.origin == ORIGIN_RADIO:
            text = "рація, прочитано о %s" % self.opened_at.strftime("%H:%M")
            if self.saved_path:
                text += ", копія: %s" % os.path.basename(self.saved_path)
            return text
        return os.path.basename(self.source_file or self.saved_path or "") or "файл"

    def title_text(self):
        """Назва для заголовка вікна: зірочка спереду, коли є незбережені зміни."""
        return "%s%s" % ("*" if self.modified else "", self.label())

    def status_text(self):
        n = len(self.changes)
        if self.modified:
            return "Кодплаг: %s · ЗМІНЕНО (змін: %d)" % (self.label(), n)
        return "Кодплаг: %s · без змін" % self.label()

    def radio_model_type(self):
        return (self.manifest.get("radio") or {}).get("radioType")

    # ----------------------------------------------------------------- слухачі

    def add_listener(self, fn):
        self._listeners.append(fn)

    def _notify(self):
        for fn in list(self._listeners):
            fn(self)

    # ----------------------------------------------------------------- перегляд

    def view(self):
        """codeplug_view.Codeplug над ПОТОЧНИМ образом (для таблиць і декодування назв); кешується до наступної зміни."""
        if self._view is None or self._view[0] != self.revision:
            self._view = (self.revision, cv.Codeplug(self.manifest, bytes(self.image.eeprom), bytes(self.image.flash)))
        return self._view[1]

    def tables(self):
        """[(ключ, заголовок, колонки, рядки)]: контакти, групи RX, зони, канали, APRS, DTMF."""
        return self.view().tables() + extra_tables(self.image)

    def export_csv(self, outdir, dp=None, log=print):
        """Шість CSV з документа (формат не змінено)."""
        return cc.export_files(self.image, outdir, dp, log)

    # ----------------------------------------------------------------- правки

    def _same(self, a, b):
        return bytes(a.eeprom) == bytes(b.eeprom) and bytes(a.flash) == bytes(b.flash)

    def _refresh_flags(self):
        cur = _snap(self.image)
        self.modified = cur != self._saved[0]
        if cur == self._origin_snap:           # усе повернуто до стану при читанні: журнал порожній
            self.changes = []
            self.warnings = []
        if cur == self._saved[0]:
            self.changes = self.changes[:self._saved[1]]
            self.warnings = list(self._saved[2])
        self._saved = (self._saved[0], min(self._saved[1], len(self.changes)), self._saved[2])

    def apply(self, res):
        """Прийняти ImportResult (res.image -- новий образ ЦІЛКОМ). True -- щось справді змінилось."""
        new = res.image
        if new is None or self._same(new, self.image):
            return False
        self.image = cc.Image(new.eeprom, new.flash, new.base)
        for kind, items in (("added", res.added), ("changed", res.changed), ("removed", res.removed)):
            self.changes.extend((kind, s, t) for s, t in items)
        for w in res.warnings:
            if w not in self.warnings:
                self.warnings.append(w)
        self.revision += 1
        self._refresh_flags()
        self._notify()
        return True

    def edit_contacts(self, ops):
        """Операції contact_edit (edit / add / delete). Помилка (ContactEditError) -- документ не змінено."""
        return self.apply(ce.apply_ops(self.image, ops))

    def edit_basic(self, callsign=None, dmr_id=None, line1=None, line2=None, intro_text=None):
        return self.apply(ced.apply_basic_info(self.image, callsign, dmr_id, line1, line2, intro_text))

    def edit_general(self, **values):
        """Загальні налаштування (пароль на старті, тривалості DTMF): general_edit.apply_general."""
        return self.apply(ge.apply_general(self.image, **values))

    def edit_aprs_slot(self, slot, values):
        """slot=None -- новий слот у кінці."""
        return self.apply(ced.apply_aprs_slot(self.image, slot, values))

    def delete_aprs_slot(self, slot):
        return self.apply(ced.delete_aprs_slot(self.image, slot))

    def import_csv(self, tables, dp=None, session=None):
        """CSV -> у документ. Усі проблеми одним списком (CsvImportRefused) ДО будь-якої зміни: документ лишається як був.
        Повертає ImportResult; документ уже змінено, якщо res.any_change() або образ відрізнявся."""
        res = cc.import_csv(self.image, tables, dp, session)
        self.apply(res)
        return res

    def discard(self):
        """Повернути стан останнього збереження (відкриття / «Зберегти як…» / запису). True -- щось відкинуто."""
        if not self.modified:
            return False
        snap, n, warns = self._saved
        self.image = _image(snap, self.base)
        self.changes = self.changes[:n]
        self.warnings = list(warns)
        self.revision += 1
        self._refresh_flags()
        self._notify()
        return True

    def change_result(self):
        """Усі зміни від моменту читання як ImportResult (для діалогу підтвердження запису)."""
        res = cc.ImportResult()
        res.image = self.image
        for kind, section, text in self.changes:
            getattr(res, kind).append((section, text))
        res.warnings = list(self.warnings)
        return res

    # ----------------------------------------------------------------- збереження у файл

    def save_bytes(self):
        """Той самий .zip, що й бекап (eeprom.bin + flash.bin + manifest.json): його відкривають і «Відкрити з бекапу…», і «Відновити».
        Зберігається ЛИШЕ кодплаг (без голосових підказок і ключів AES, навіть якщо документ відкрито з повного знімка)."""
        rng = cl.flash_backup_range()
        ee, fl = bytes(self.image.eeprom), bytes(self.image.flash)
        if len(ee) != cl.EEPROM_BACKUP_LEN or len(fl) != rng["length"]:
            raise DocumentError("розмір образу (%d + %d Б) не відповідає відомому кодплагу (%d + %d Б) -- зберігати не можна"
                                % (len(ee), len(fl), cl.EEPROM_BACKUP_LEN, rng["length"]))
        info = dict(self.manifest.get("radio") or {})
        now = time.time()
        m = cl.build_manifest(info, ee, fl, rng, now, now, 0)
        m["tool"] = "cps_ui/document.py (CPS-doc)"
        m["note"] = ("Кодплаг-документ: образ, відкритий із %s і змінений у вікні (змін: %d). У рацію цим збереженням нічого не записувалось."
                     % ("рації" if self.origin == ORIGIN_RADIO else "файла", len(self.changes)))
        m["document"] = {"origin": self.origin, "source": self.label(), "changes": len(self.changes)}
        return cl.make_zip(ee, fl, m)

    def save_as(self, path):
        """Записати документ у .zip. Після цього «незбережених змін» нема (база «збережено» = поточний стан)."""
        data = self.save_bytes()
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        self.saved_path = path
        self._saved = (_snap(self.image), len(self.changes), list(self.warnings))
        self.modified = False
        self.revision += 1
        self._notify()
        return path

    # ----------------------------------------------------------------- запис у рацію

    def write_block_reason(self, radio_info=None):
        """Чому запис у рацію заборонено (None -- можна). Без radio_info перевіряється лише те, що видно з самого документа."""
        radio = self.manifest.get("radio")
        if not isinstance(radio, dict) or not isinstance(radio.get("radioType"), int):
            return "У документа нема даних про тип рації -- записувати його не можна."
        if radio["radioType"] != cl.RADIO_TYPE_MDUV380:
            return ("Документ відкрито з бекапу іншої моделі рації (radioType %d, потрібен %d) -- запис у цю рацію заборонено."
                    % (radio["radioType"], cl.RADIO_TYPE_MDUV380))
        if isinstance(radio_info, dict) and isinstance(radio_info.get("radioType"), int) and isinstance(radio_info.get("structVersion"), int):
            try:
                cr.check_radio(radio_info, self.manifest)
            except cr.RestoreRefused as e:
                return str(e)
        if self.origin == ORIGIN_RADIO and not self.pending_write():
            return "Змін для запису немає: документ збігається зі станом рації."
        return None

    def pending_write(self):
        """Чи є що записувати. Документ з файла -- завжди (запис = привести рацію до стану файла); з рації -- лише коли образ відрізняється."""
        return self.origin == ORIGIN_FILE or _snap(self.image) != self._origin_snap

    def write_image(self, fresh=None):
        """(ImportResult для запису, число конфліктів). Документ з файла: образ як є. Документ з рації: СВІЖЕ читання рації (fresh --
        cps_csv.Image) + лише ваші відмінності від стану при читанні; байти, які змінили і ви, і рація, беруться з вашої правки (конфлікт)."""
        res = self.change_result()
        if self.origin == ORIGIN_FILE:
            res.warnings.append("Кодплаг відкрито з файла «%s»: рація буде приведена до стану цього файла разом із вашими правками "
                                "(усе, чим вона відрізнялась від файла, -- зникне)." % self.label())
            return res, 0
        if fresh is None:
            raise DocumentError("для запису документа з рації потрібне свіже читання рації")
        merged, conflicts = merge(_image(self._origin_snap, self.base), self.image, fresh)
        res.image = merged
        if conflicts:
            res.warnings.append("Після читання рація змінила %d байт(ів), які ви теж змінили в документі; взято вашу правку." % conflicts)
        return res, conflicts

    def mark_written(self, image):
        """Після успішного запису: документ = те, що тепер у рації. Джерело -- рація, незбережених змін нема."""
        self.image = cc.Image(image.eeprom, image.flash, image.base)
        self.origin = ORIGIN_RADIO
        self.opened_at = datetime.datetime.now()
        self.source_file = None
        self.saved_path = None
        self.changes = []
        self.warnings = []
        self._origin_snap = _snap(self.image)
        self._saved = (_snap(self.image), 0, [])
        self.modified = False
        self.revision += 1
        self._notify()


def merge(origin, current, fresh):
    """Накласти відмінності current від origin на fresh. Повертає (cps_csv.Image, число конфліктів). Усі три образи -- однієї довжини."""
    out = {}
    conflicts = 0
    for name in ("eeprom", "flash"):
        o, c, f = bytes(getattr(origin, name)), bytes(getattr(current, name)), bytes(getattr(fresh, name))
        if not (len(o) == len(c) == len(f)):
            raise DocumentError("свіже читання рації має інший розмір, ніж документ (%s: %d проти %d Б) -- запис скасовано" % (name, len(f), len(o)))
        buf = bytearray(f)
        for a in range(0, len(o), STEP):
            if o[a:a + STEP] == c[a:a + STEP]:
                continue
            for i in range(a, min(a + STEP, len(o))):
                if o[i] != c[i]:
                    if f[i] != o[i] and f[i] != c[i]:
                        conflicts += 1
                    buf[i] = c[i]
        out[name] = buf
    return cc.Image(out["eeprom"], out["flash"], fresh.base), conflicts


def from_radio(link, progress=None, opened_at=None):
    """Прочитати рацію в документ (довга операція: EEPROM 128 КБ + флеш 80 КБ; викликати з робочого потоку)."""
    cp, _m = cv.codeplug_from_radio(link, progress)
    return Document(cp, ORIGIN_RADIO, opened_at=opened_at)


def from_backup(path):
    """Відкрити бекап (.zip) у документ. SHA-256 частин перевіряє cps_link.read_backup_zip."""
    cp, _m = cv.codeplug_from_backup(path)
    return Document(cp, ORIGIN_FILE, source_file=path)
