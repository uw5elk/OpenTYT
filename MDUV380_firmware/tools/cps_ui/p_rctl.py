# -*- coding: utf-8 -*-
"""Розділ «Дані → Віддалене керування (RCTL)» (R75: частина документа, власних кнопок читання/запису рації нема): дозволи «приймати команди віддаленого керування» (RCTL --
functions/dmr_rctl_cfg.c). Пише блок "RCTL" у custom-data (CHIRP-стиль: прошивка лише читає, сама не пише).

Модель довіри (2026-09-03, за зразком Motorola/Hytera): жодного окремого списку довірених ID -- сам канальний AES-ключ (той самий,
що голос/SMS) є межею довіри.

2026-09-18: окремого перемикача «enabled» більше немає. Єдина точка правди -- які САМЕ команди дозволені (по чекбоксу на тип:
Ввімкнення/Перевірка/Моніторинг/Вимкнення). enabled похідний: позначено хоч одну -> RCTL увімкнено; жодної -> вимкнено.
build_payload() виставляє байт enabled сам, тож поля у флеші не можуть розійтися.

Окремо -- чекбокс видимості пункту «Доступ RCTL» в меню Опцій рації (це вигляд, не дозволи: гейт дозволів діє незалежно від того,
чи видно пункт).

ВАЖЛИВО: ця панель НЕ надсилає саму команду Radio Check в ефір -- команда йде рація-рації по DMR, а не через USB/CPS. Тут лише
налаштовуються дозволи (fail closed: порожня маска = вимкнено, доки не позначено явно). Логіку перенесено з
gui_flasher.RctlConfigWindow без змін."""
import tkinter as tk
from tkinter import ttk, messagebox

import rctl_config as rctl
import gui_theme as gt

from . import document as D
from .panel import Panel


class RctlPanel(Panel):
    key = "rctl"
    title = "Віддалене керування (RCTL)"
    doc_panel = True

    def __init__(self, parent, shell):
        super().__init__(parent, shell)
        self._build_ui()

    def _build_ui(self):
        self.header("Віддалене керування (RCTL)")
        ttk.Label(
            self,
            text=("Познач, які САМЕ команди ця рація прийматиме від БУДЬ-КОГО, хто знає "
                  "ключ шифрування каналу (як у Motorola/Hytera -- окремого списку ID "
                  "немає). Жодної позначки = RCTL вимкнено (рація не приймає нічого). "
                  "Окремого перемикача «увімкнено» більше немає: увімкнено = дозволена "
                  "хоч одна команда. Зміни вносяться в документ кнопкою «Застосувати до документа»; у рацію вони йдуть дією «Записати в рацію»."),
            wraplength=600, justify="left", foreground=gt.P["warn"],
        ).pack(anchor="w", padx=12, pady=(0, 6))

        # 2026-09-18: замість одного «enabled» -- по чекбоксу на КОЖЕН тип команди, тими ж назвами, що й у меню рації «Доступ RCTL».
        # Порядок за вимогою: Ввімкнення, Перевірка, Моніторинг, Вимкнення.
        cmd_frame = ttk.LabelFrame(self, text="Дозволені команди")
        cmd_frame.pack(fill="x", padx=12, pady=(4, 0))
        self.cmd_vars = {}
        RCTL_CMDS = [
            ("revive",  "Ввімкнення", rctl.ALLOW_REVIVE),
            ("check",   "Перевірка",  rctl.ALLOW_CHECK),
            ("monitor", "Моніторинг", rctl.ALLOW_MONITOR),
            ("stun",    "Вимкнення",  rctl.ALLOW_STUN),
        ]
        self._rctl_cmd_bits = {key: bit for key, _lbl, bit in RCTL_CMDS}
        for key, label, _bit in RCTL_CMDS:
            v = tk.BooleanVar(value=False)
            self.cmd_vars[key] = v
            ttk.Checkbutton(cmd_frame, text=label, variable=v).pack(anchor="w", padx=8, pady=1)

        self.menu_visible_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self, text="Показувати пункт «Доступ RCTL» в меню Опцій на рації",
                        variable=self.menu_visible_var).pack(anchor="w", padx=12, pady=(4, 0))
        ttk.Label(
            self,
            text=("Лише вигляд: сховати пункт можна, щоб боєць не міг сам собі вимкнути "
                  "приймання команд у полі. Дозволи (checkbox вище) працюють незалежно "
                  "від видимості пункту."),
            wraplength=600, justify="left", foreground=gt.P["muted"],
        ).pack(anchor="w", padx=12, pady=(0, 0))

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=12, pady=6)
        self.apply_btn = ttk.Button(btn_row, text="Застосувати до документа", command=self._on_apply)
        self.apply_btn.pack(side="left")
        self.reload_btn = ttk.Button(btn_row, text="Повернути значення з документа", command=self.on_document_changed)
        self.reload_btn.pack(side="left", padx=8)
        self.note_lbl = ttk.Label(self, text="", wraplength=600, justify="left", foreground=gt.P["muted"])
        self.note_lbl.pack(anchor="w", padx=12)
        self.on_document_changed()

    def _state_from_doc(self):
        d = self.doc
        payload = d.region.read_block(None, rctl.TYPE_RCTL_CONFIG, rctl.PAYLOAD_LEN) if d is not None and d.region is not None else None
        return rctl.parse_payload(payload) if payload else {"version": rctl.VERSION, "enabled": False, "allow": 0, "menu_hidden": False, "monitor_secs": 0}

    def on_document_changed(self):
        d = self.doc
        ok = d is not None and d.region is not None
        if ok:
            self._apply_state(self._state_from_doc())
            self.note_lbl.config(text="")
        else:
            self.note_lbl.config(text=("У документа нема налаштувань рації (файл створено старою версією) -- відкрий кодплаг з рації, щоб їх змінити."
                                       if d is not None else "Відкрий кодплаг з рації або з файла."))
        for b in (self.apply_btn, self.reload_btn):
            b.config(state="normal" if ok and not self.shell.busy else "disabled")

    def after_refresh(self):
        d = self.doc
        ok = d is not None and d.region is not None and not self.shell.busy
        for b in (self.apply_btn, self.reload_btn):
            b.config(state="normal" if ok else "disabled")

    def _apply_state(self, state):
        # Показуємо ЕФЕКТИВНУ маску (state["allow"]): на legacy-рації, де enabled=0 при ненульовій сирій масці, галочки будуть зняті --
        # і запис нормалізує до чесного вимкненого стану, не воскрешаючи прихований дозвіл.
        allow = state.get("allow", 0)
        for key, bit in self._rctl_cmd_bits.items():
            self.cmd_vars[key].set(bool(allow & bit))
        self.menu_visible_var.set(not state.get("menu_hidden", False))

    def _selected_mask(self):
        mask = 0
        for key, bit in self._rctl_cmd_bits.items():
            if self.cmd_vars[key].get():
                mask |= bit
        return mask

    # --- дії користувача -----------------------------------------------------------

    def _on_apply(self):
        d = self.doc
        if d is None or d.region is None or self.shell.busy:
            return
        mask = self._selected_mask()
        menu_hidden = not self.menu_visible_var.get()
        if mask:
            if not messagebox.askokcancel(
                "Увімкнути RCTL?",
                "Ця рація прийматиме позначені команди віддаленого керування від "
                "БУДЬ-КОГО, хто знає ключ шифрування каналу -- без окремого списку "
                "довірених ID (як у Motorola/Hytera). Продовжити?",
            ):
                return
        if menu_hidden:
            if not messagebox.askokcancel(
                "Сховати пункт меню?",
                "Пункт «Доступ RCTL» зникне з меню Опцій на рації -- боєць не зможе сам "
                "собі увімкнути/вимкнути приймання команд у полі. Повернути видимість "
                "можна лише звідси, з прошивальника. Продовжити?",
            ):
                return
        # monitor_secs -- зберігаємо те, що вже є в документі (тривалістю Monitor ця панель не керує). enabled похідний від маски (build_payload).
        monitor_secs = self._state_from_doc().get("monitor_secs", 0)
        try:
            payload = rctl.build_payload(mask, monitor_secs, menu_hidden)
            scratch = d.scratch_region()
            ok, msg = scratch.write_block(None, rctl.TYPE_RCTL_CONFIG, payload)
            if not ok:
                raise D.DocumentError(msg)
            changed = d.apply_region(scratch, {rctl.TYPE_RCTL_CONFIG: "Віддалене керування (RCTL)"})
        except (ValueError, D.DocumentError) as e:
            messagebox.showerror("RCTL", str(e), parent=self.shell)
            return
        self.shell.set_status("Налаштування RCTL змінено в документі." if changed else "Змін немає.", "ok" if changed else "info")
