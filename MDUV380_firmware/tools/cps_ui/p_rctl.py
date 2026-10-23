# -*- coding: utf-8 -*-
"""Розділ «Налаштування рації → Віддалене керування (RCTL)»: дозволи «приймати команди віддаленого керування» (RCTL --
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

import aes_key_store
import custom_data as cd
import rctl_config as rctl
import gui_theme as gt

from .panel import Panel

try:
    import serial
except ImportError:
    serial = None


class RctlPanel(Panel):
    key = "rctl"
    title = "Віддалене керування (RCTL)"
    radio_only = True

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
                  "хоч одна команда. Рація має бути УВІМКНЕНА У ЗВИЧАЙНОМУ РЕЖИМІ (не в DFU)."),
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
        self.read_btn = ttk.Button(btn_row, text="Прочитати поточний стан", command=self._on_read)
        self.read_btn.pack(side="left")
        self.write_btn = ttk.Button(btn_row, text="Записати на рацію", command=self._on_write)
        self.write_btn.pack(side="left", padx=8)
        self.reg(self.read_btn)
        self.reg(self.write_btn)
        ttk.Label(self, text="Натисни «Прочитати поточний стан».", foreground=gt.P["info"]).pack(anchor="w", padx=12)

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

    def _run(self, fn, text):
        self.shell.run_task(fn, text, plain_errors=True)

    def _on_read(self):
        if self.shell.busy:
            return
        self._run(self._read_worker, "Читаю поточний стан...")

    def _on_write(self):
        if self.shell.busy:
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
        self._run(lambda: self._write_worker(mask, menu_hidden), "Записую...")

    # --- фонові операції -----------------------------------------------------------

    def _connect(self):
        port = aes_key_store.find_port()
        if not port:
            raise RuntimeError(
                "рацію не знайдено у звичайному режимі (VID:PID 1fc9:0094). "
                "Переконайся, що вона увімкнена звичайним способом (НЕ в DFU) і кабель підключено."
            )
        ser = serial.Serial(port, 115200, timeout=0.6)
        aes_key_store.show_cps(ser)
        return ser

    def _read_worker(self):
        with self._connect() as ser:
            payload = cd.read_block(ser, rctl.TYPE_RCTL_CONFIG, rctl.PAYLOAD_LEN)
            state = rctl.parse_payload(payload) if payload else {
                "version": rctl.VERSION, "enabled": False, "allow": 0,
                "menu_hidden": False, "monitor_secs": 0,
            }
            self.shell.post(lambda: self._apply_state(state))
            names = [n for n, b in rctl.ALLOW_NAMES if state.get("allow", 0) & b] or ["-"]
            print("Стан: RCTL={}, дозволи=[{}], пункт меню={}".format(
                "увімкнено" if state.get("allow") else "вимкнено",
                ",".join(names),
                "схований" if state.get("menu_hidden") else "видимий"))

    def _write_worker(self, mask, menu_hidden):
        with self._connect() as ser:
            # monitor_secs -- зберігаємо те, що вже є на рації (тривалістю Monitor ця панель не керує: rctl_config.py, за потреби).
            # enabled НЕ пишемо окремо -- він похідний від маски (build_payload виставляє його сам). Маска -- єдина точка правди.
            current = cd.read_block(ser, rctl.TYPE_RCTL_CONFIG, rctl.PAYLOAD_LEN)
            cur = rctl.parse_payload(current) if current else None
            monitor_secs = cur["monitor_secs"] if cur else 0

            payload = rctl.build_payload(mask, monitor_secs, menu_hidden)
            ok, msg = cd.write_block(ser, rctl.TYPE_RCTL_CONFIG, payload)
            if not ok:
                raise RuntimeError(msg)
            rb = cd.read_block(ser, rctl.TYPE_RCTL_CONFIG, rctl.PAYLOAD_LEN)
            verify_ok = (rb == payload)
            names = [n for n, b in rctl.ALLOW_NAMES if mask & b] or ["-"]
            print("Записано ({}), RCTL={}, дозволи=[{}], пункт меню={}. Звірка читанням: {}.".format(
                msg, "увімкнено" if mask else "вимкнено", ",".join(names),
                "схований" if menu_hidden else "видимий",
                "OK" if verify_ok else "НЕЗБІГ"))
