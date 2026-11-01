# -*- coding: utf-8 -*-
"""Розділ «Кодплаг → Канали» (CPS-fix2, T3): редактор каналів документа. Список (з фільтром за назвою / номером / частотою) ліворуч, форма з 28 полів
праворуч, розбита на групи: Основне, Частоти, Аналогові, Цифрові, Опції, APRS і позиція. Поля, що не стосуються типу каналу, вимкнені (як у «Деталях
каналу» рації). Контакт, список прийому і конфіг APRS вибираються зі списку наявних. Частоти й числа вводяться як у CSV (кома або крапка), показуються за
десятковим знаком системної локалі. Кожна зміна поля застосовується до документа одразу й проходить ті самі перевірки, що й імпорт CSV (table_edit.py)."""
import tkinter as tk
from tkinter import ttk

import cps_csv as cc
import gui_dialogs as gd
import gui_theme as gt
import table_edit as te

from .editor_base import EditorPanel
from .panel import ScrollFrame

CTCSS = ("67.0 69.3 71.9 74.4 77.0 79.7 82.5 85.4 88.5 91.5 94.8 97.4 100.0 103.5 107.2 110.9 114.8 118.8 123.0 127.3 131.8 136.5 141.3 146.2 "
         "151.4 156.7 159.8 162.2 165.5 167.9 171.3 173.8 177.3 179.9 183.5 186.2 189.9 192.8 196.6 199.5 203.5 206.5 210.7 218.1 225.7 229.1 "
         "233.6 241.8 250.3 254.1").split()

# (група, [(колонка CSV, підпис, тип поля)]). Типи: name, type, number, entry, bw, tone, sql, spin, ts, ref:<вид>, ta, power, tot, check, aes (лише редактор; у CSV колонки нема)
GROUPS = [
    ("Основне", [("Channel Name", "Назва", "name"), ("Channel Type", "Тип", "type"), ("Channel Number", "Номер", "number")]),
    ("Частоти", [("Rx Frequency", "RX, МГц", "entry"), ("Tx Frequency", "TX, МГц", "entry"), ("Bandwidth (kHz)", "Смуга, кГц (аналог)", "bw")]),
    ("Аналогові", [("RX Tone", "Тон RX (None / CTCSS / DCS)", "tone"), ("TX Tone", "Тон TX (None / CTCSS / DCS)", "tone"),
                   ("Squelch", "Шумодав", "sql")]),
    ("Цифрові", [("Colour Code", "Колір-код (0..15)", "spin"), ("Timeslot", "Таймслот", "ts"), ("Contact", "Контакт", "ref:contact"),
                 ("TG List", "Список прийому", "ref:group"), ("DMR ID", "DMR ID (None -- загальний)", "entry"),
                 ("TS1_TA_Tx", "TA на таймслоті 1", "ta"), ("TS2_TA_Tx ID", "TA на таймслоті 2", "ta"),
                 (te.AES_KEY_COLUMN, "Ключ AES (0 -- без шифрування)", "aes")]),
    ("Опції", [("Power", "Потужність", "power"), ("Rx Only", "Лише прийом", "check"), ("Zone Skip", "Пропуск у зоні", "check"),
               ("All Skip", "Пропуск у всіх", "check"), ("TOT", "TOT, с (Off -- вимкнено)", "tot"), ("VOX", "VOX", "check"),
               ("No Beep", "Без звуку", "check"), ("No Eco", "Без еко", "check")]),
    ("APRS і позиція", [("APRS", "Конфіг APRS", "ref:aprs"), ("Latitude", "Широта, °", "entry"), ("Longitude", "Довгота, °", "entry"),
                        ("Use Location", "Використовувати позицію", "check")]),
]
TYPE_LABELS = {"Analogue": "Аналоговий", "Digital": "Цифровий"}
NONE_LABEL = "Немає (None)"


class ChannelsPanel(EditorPanel):
    key = "channels"
    title = "Канали"
    kind = "channel"
    noun = "канал"
    list_width = 370
    reorderable = True
    hint_text = ("Канали кодплага: 28 полів, згруповані за призначенням. Кожна зміна поля застосовується до документа одразу (Enter або вихід з поля); "
                 "рація змінюється лише за дією «Записати кодплаг у рацію». «Вище ↑ / Нижче ↓» (Ctrl+↑ / Ctrl+↓ або перетягування рядка) змінює порядок, "
                 "а з ним і НОМЕРИ каналів: «Всі канали» йдуть за номером, тож їхній порядок теж зміниться; зони, останній вибраний канал і всі посилання "
                 "оновлюються самі.")
    columns = (("n", "№", 45, False), ("name", "Назва", 140, True), ("type", "Тип", 50, False), ("rx", "RX, МГц", 80, False))

    def entities(self, img):
        return [(n, (n, name, "Ц" if ty == "Digital" else "А", rx)) for n, name, ty, rx in te.channels(img, self.dp)]

    # ------------------------------------------------------------------ форма

    def build_form(self, parent):
        self.fields = {}
        self._loaded = {}
        self._digital = False
        self._ref_numbers = {}
        self._rows = []
        self._narrow = False
        sf = ScrollFrame(parent)
        sf.pack(fill="both", expand=True)
        self.form_host = sf
        form = sf.inner
        self.form_title = ttk.Label(form, text="", font=("Segoe UI", 11, "bold"))
        self.form_title.pack(anchor="w", pady=(0, 4))
        sep = self.dp
        for gname, fields in GROUPS:
            box = ttk.LabelFrame(form, text=gname)
            box.pack(fill="x", pady=4, padx=(0, 8))
            for col, label, ftype in fields:
                row = ttk.Frame(box)
                row.pack(fill="x", padx=8, pady=2)
                if ftype == "check":
                    var = tk.BooleanVar()
                    w = ttk.Checkbutton(row, text=label, variable=var, command=lambda c=col: self.commit(c))
                    w.pack(anchor="w")
                else:
                    lab = ttk.Label(row, text=label, width=30)
                    lab.pack(side="left")
                    var = tk.StringVar()
                    w = self._make_widget(row, ftype, var, col, sep)
                    w.pack(side="left")
                    self._rows.append((lab, w))
                    if ftype in ("entry", "name", "tone", "tot", "spin", "sql"):
                        w.bind("<Return>", lambda _e, c=col: self.commit(c))
                        w.bind("<FocusOut>", lambda _e, c=col: self.commit(c))
                self.fields[col] = {"var": var, "widget": w, "type": ftype}
                if ftype == "aes":
                    self._aes_hint = ttk.Label(box, text=self._aes_hint_text(), wraplength=420, justify="left", foreground=gt.P["muted"])
                    self._aes_hint.pack(anchor="w", padx=8, pady=(0, 4))
        self._hint = ttk.Label(form, text=("Частоти без «\\t» і з комою або крапкою -- як у CSV. Тони: None, CTCSS у герцах (напр. 67%s0) або DCS (D023N, D023I). "
                              "Контакт, список прийому і конфіг APRS вибираються зі списку наявних; записи з однаковими назвами розрізняються за №." % sep),
                  wraplength=520, justify="left", foreground=gt.P["muted"])
        self._hint.pack(anchor="w", pady=(4, 8))

    def relayout(self, form_width):
        """Вузька форма (< 470 px): підпис над полем, а не ліворуч від нього; довгий підказковий текст переноситься по ширині."""
        if not getattr(self, "_rows", None):
            return
        narrow = form_width < 420
        self._hint.config(wraplength=max(180, form_width - 40))
        self._aes_hint.config(wraplength=max(180, form_width - 60))
        if narrow == self._narrow:
            return
        self._narrow = narrow
        for lab, w in self._rows:
            lab.pack_forget()
            w.pack_forget()
            if narrow:
                lab.config(width=0)
                lab.pack(side="top", anchor="w")
                w.pack(side="top", anchor="w")
            else:
                lab.config(width=30)
                lab.pack(side="left")
                w.pack(side="left")

    def _make_widget(self, parent, ftype, var, col, sep):
        if ftype == "type":
            w = ttk.Combobox(parent, textvariable=var, values=[TYPE_LABELS["Analogue"], TYPE_LABELS["Digital"]], state="readonly", width=24)
        elif ftype == "number":
            w = ttk.Label(parent, textvariable=var)
        elif ftype == "bw":
            w = ttk.Combobox(parent, textvariable=var, values=["12%s5" % sep, "25"], state="readonly", width=24)
        elif ftype == "tone":
            w = ttk.Combobox(parent, textvariable=var, values=["None"] + [t.replace(".", sep) for t in CTCSS], width=24)
        elif ftype == "sql":
            w = ttk.Combobox(parent, textvariable=var, values=["Master"] + ["%d%%" % (5 * (k - 1)) for k in range(1, 22)], width=24)
        elif ftype == "spin":
            w = ttk.Spinbox(parent, textvariable=var, from_=0, to=15, width=8, command=lambda: self.commit(col))
        elif ftype == "ts":
            w = ttk.Combobox(parent, textvariable=var, values=["1", "2"], state="readonly", width=24)
        elif ftype.startswith("ref:"):
            w = ttk.Combobox(parent, textvariable=var, values=[NONE_LABEL], state="readonly", width=36)
        elif ftype == "aes":
            w = ttk.Combobox(parent, textvariable=var, values=self._aes_labels(), state="readonly", width=36)
        elif ftype == "ta":
            w = ttk.Combobox(parent, textvariable=var, values=cc.TA_NAMES, state="readonly", width=24)
        elif ftype == "power":
            w = ttk.Combobox(parent, textvariable=var, values=["Master"] + cc.POWER_NAMES, state="readonly", width=24)
        elif ftype == "tot":
            w = ttk.Combobox(parent, textvariable=var, values=["Off"] + [str(15 * k) for k in range(1, 21)], width=24)
        else:
            w = ttk.Entry(parent, textvariable=var, width=26)
        if isinstance(w, ttk.Combobox):
            w.bind("<<ComboboxSelected>>", lambda _e, c=col: self.commit(c))
        return w

    # ------------------------------------------------------------------ значення форми

    def clear_form(self):
        self.form_title.config(text="")
        self._loading = True
        try:
            for f in self.fields.values():
                f["var"].set(False if f["type"] == "check" else "")
        finally:
            self._loading = False
        self._loaded = {}
        self.form_state(False)

    def load_form(self):
        d = self.doc
        if d is None or self.sel is None or self.sel not in dict(te.entity_names(d.image, "channel")):
            self.clear_form()
            if d is not None:
                self.form_title.config(text="Оберіть канал ліворуч або натисніть «Додати...»")
            return
        img = d.image
        vals = te.channel_values(img, self.sel, self.dp)
        refs = te.channel_refs(img, self.sel)
        self._digital = vals["Channel Type"].strip().casefold().startswith("dig")
        self.form_title.config(text="№%d «%s»" % (self.sel, vals["Channel Name"]))
        self._loading = True
        try:
            for col, f in self.fields.items():
                ftype, var = f["type"], f["var"]
                if ftype == "type":
                    var.set(TYPE_LABELS["Digital" if self._digital else "Analogue"])
                elif ftype == "number":
                    var.set(vals["Channel Number"])
                elif ftype == "check":
                    var.set(vals[col].strip().casefold() in ("yes", "on", "true"))
                elif ftype.startswith("ref:"):
                    kind = ftype[4:]
                    opts = te.ref_options(img, kind)
                    labels = {n: lab for n, lab in opts}
                    self._ref_numbers[col] = {lab: n for n, lab in opts}
                    self._ref_numbers[col][NONE_LABEL] = 0
                    n = refs[col]
                    label = NONE_LABEL if n == 0 else labels.get(n, "#%d (відсутній запис)" % n)
                    if n and n not in labels:
                        self._ref_numbers[col][label] = n
                        f["widget"].config(values=[NONE_LABEL] + [lab for _n, lab in opts] + [label])
                    else:
                        f["widget"].config(values=[NONE_LABEL] + [lab for _n, lab in opts])
                    var.set(label if self._digital or ftype == "ref:aprs" else "")
                elif ftype == "aes":
                    slot = te.aes_slot(img.channel_rec(self.sel))
                    f["widget"].config(values=self._aes_labels())
                    var.set(self._aes_label(0 if slot == 0xFF else slot) if self._digital else "")
                else:
                    var.set(vals.get(col, ""))
                self._loaded[col] = self._display(col)
        finally:
            self._loading = False
        self.after_refresh()

    def _display(self, col):
        f = self.fields[col]
        v = f["var"].get()
        if f["type"] == "aes":          # порівнюємо за номером слота: підпис змінюється, коли оновлюється список зайнятих слотів
            return str(v).split(" ")[0]
        return bool(v) if f["type"] == "check" else str(v).strip()

    # --- ключ AES: номери слотів і чи зайняті вони (за останнім читанням «AES-ключі»; матеріалу ключа тут нема) ---

    def _aes_occupied(self):
        info = getattr(self.shell, "aes_slots", None)
        return None if info is None else set(info["occupied"])

    def _aes_label(self, slot):
        if slot == 0:
            return "0 -- без шифрування"
        occ = self._aes_occupied()
        mark = "" if occ is None else (" -- ключ є" if slot in occ else " -- порожній")
        return "%d%s" % (slot, mark)

    def _aes_labels(self):
        return [self._aes_label(k) for k in range(0, te.AES_SLOT_MAX + 1)]

    def _aes_hint_text(self):
        occ = self._aes_occupied()
        if occ is None:
            return ("Які слоти зайняті, невідомо: відкрийте «AES-ключі» і натисніть «Оновити список зайнятих слотів». "
                    "Саме ключі лише в рації і тут не показуються.")
        return "Зайняті слоти в рації: %s. Саме ключі тут не показуються." % (", ".join(map(str, sorted(occ))) if occ else "немає")

    def on_aes_slots(self):
        """Оболонка повідомила про свіже читання зайнятих слотів: перемалювати підписи списку й підказку."""
        if not hasattr(self, "_aes_hint"):
            return
        self._aes_hint.config(text=self._aes_hint_text())
        f = self.fields.get(te.AES_KEY_COLUMN)
        if f is None:
            return
        f["widget"].config(values=self._aes_labels())
        cur = self._display(te.AES_KEY_COLUMN)
        if cur.isdigit():
            self._loading = True
            try:
                f["var"].set(self._aes_label(int(cur)))
            finally:
                self._loading = False

    def form_state(self, enabled):
        for col, f in self.fields.items():
            if col == "Channel Number":
                continue
            if col == te.AES_KEY_COLUMN:
                ok = enabled and self._digital
            else:
                ok = enabled and (col in ("Channel Name", "Channel Type") or te.applicable(col, self._digital))
            w, ftype = f["widget"], f["type"]
            if ftype in ("type", "bw", "ts", "ta", "power", "aes") or ftype.startswith("ref:"):
                w.config(state="readonly" if ok else "disabled")
            else:
                w.config(state="normal" if ok else "disabled")

    # ------------------------------------------------------------------ правка поля

    def _edit_text(self, col, img):
        f = self.fields[col]
        ftype, v = f["type"], f["var"].get()
        if ftype == "type":
            return "Digital" if v == TYPE_LABELS["Digital"] else "Analogue"
        if ftype == "check":
            return "Yes" if v else "No"
        if ftype.startswith("ref:"):
            n = self._ref_numbers.get(col, {}).get(v, 0)
            return te.ref_token(img, ftype[4:], n)
        return str(v).strip()

    def commit(self, col):
        d = self.doc
        if self._loading or d is None or self.sel is None or self.shell.busy:
            return
        if self._display(col) == self._loaded.get(col):
            return
        num = self.sel
        text = self._edit_text(col, d.image)
        label = [lab for _g, fs in GROUPS for c, lab, _t in fs if c == col][0]
        if col == te.AES_KEY_COLUMN:
            slot = int(text.split(" ")[0])
            if not self.run_edit(lambda img: te.channel_set_aes_slot(img, num, slot)):
                self.show_message("Поле «%s»: %s" % (label, self.msg.cget("text")), "err")
                return
            occ = self._aes_occupied()
            if slot and occ is not None and slot not in occ:
                self.show_message(self.msg.cget("text") + "\nУвага: у слоті %d на рації немає ключа (за останнім читанням «AES-ключі»): канал не шифруватиме, "
                                  "доки ключ не запишуть." % slot, "warn")
            return
        if not self.run_edit(lambda img: te.channel_edit(img, num, {col: text}, self.dp)):
            self.show_message("Поле «%s»: %s" % (label, self.msg.cget("text")), "err")

    # ------------------------------------------------------------------ додати

    def ask_new(self, img):
        base_label = None
        if self.sel is not None:
            ent = dict(self.entities(img)).get(self.sel)
            if ent:
                base_label = "№%d «%s»" % (ent[0], ent[1])
        got = gd.new_channel_dialog(self.shell, "Новий канал", check=lambda t: te.name_problem(img, "channel", t), base_label=base_label)
        if got is None:
            return None
        name, digital, use_base = got
        source = self.sel if use_base else None
        if source is not None:
            digital = img.channel_rec(source)[cc.O_MODE] != 0
        return lambda im: te.channel_new(im, name, digital, self.dp, source=source)
