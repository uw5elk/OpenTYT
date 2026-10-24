# -*- coding: utf-8 -*-
"""Розділ «Налаштування рації → AES-ключі»: додавання/видалення AES-256 ключів шифрування голосу.

ІНША фізична фаза USB, ніж прошивка: рація тут має бути у ЗВИЧАЙНОМУ робочому режимі (VID:PID 1fc9:0094, той самий CPS-протокол,
яким користується офіційна CPS-програма) -- НЕ в DFU-завантажувачі.

Ключі зберігаються у форматі стокової таблиці TYT (не в кастомних даних OpenGD77) -- див. tools/stock_key_table.py й коментар при
STOCK_KEY_TABLE_BASE у dmr_aes_hook.c. Сам протокольний код читання/запису флеш (flash_read/flash_write_block/find_port) береться з
aes_key_store.py як є -- нічого не дублюється. Логіку перенесено з gui_flasher.AesKeyManagerWindow без змін."""
import tkinter as tk
from tkinter import ttk, messagebox

import aes_key_store
import stock_key_table as skt
import gui_theme as gt

from .common import enable_entry_clipboard
from .panel import Panel

try:
    import serial
except ImportError:
    serial = None


class AesPanel(Panel):
    key = "aes"
    title = "AES-ключі"
    radio_only = True

    def __init__(self, parent, shell):
        super().__init__(parent, shell)
        self._build_ui()

    def _build_ui(self):
        self.header("AES-ключі шифрування")
        ttk.Label(self, text=("Рація має бути УВІМКНЕНА У ЗВИЧАЙНОМУ РЕЖИМІ (не в DFU!). Матеріал ключа ніде на екрані не показується -- "
                              "лише факт \"зайнято/порожньо\"."), wraplength=600, justify="left", foreground=gt.P["warn"]).pack(anchor="w", padx=12, pady=(0, 6))

        key_frame = ttk.LabelFrame(self, text="Слот ключа (1..15)")
        key_frame.pack(fill="x", padx=12, pady=6)

        row1 = ttk.Frame(key_frame)
        row1.pack(fill="x", padx=8, pady=(6, 2))
        ttk.Label(row1, text="ID ключа:").pack(side="left")
        self.keyid_var = tk.IntVar(value=1)
        ttk.Spinbox(row1, from_=1, to=15, width=4, textvariable=self.keyid_var).pack(side="left", padx=6)

        row2 = ttk.Frame(key_frame)
        row2.pack(fill="x", padx=8, pady=2)
        ttk.Label(row2, text="Ключ (64 hex):").pack(side="left")
        self.key_var = tk.StringVar()
        self.key_entry = ttk.Entry(row2, textvariable=self.key_var, width=40, font=("Consolas", 9))
        self.key_entry.pack(side="left", padx=6, fill="x", expand=True)
        # Явно вмикаємо вставку/копіювання -- інакше на Windows з українською розкладкою клавіатури Ctrl+V у це поле не
        # спрацьовує (див. докладний коментар при enable_entry_clipboard() у common.py).
        enable_entry_clipboard(self.key_entry)

        self.show_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(key_frame, text="показувати введений ключ", variable=self.show_var,
                        command=self._toggle_key_visibility).pack(anchor="w", padx=8)

        row3 = ttk.Frame(key_frame)
        row3.pack(fill="x", padx=8, pady=(2, 8))
        self.write_btn = ttk.Button(row3, text="Записати ключ", command=self._on_write_key)
        self.write_btn.pack(side="left")
        self.clear_btn = ttk.Button(row3, text="Очистити ключ", command=self._on_clear_key)
        self.clear_btn.pack(side="left", padx=8)

        self.refresh_btn = ttk.Button(self, text="Оновити список зайнятих слотів", command=self._on_refresh_slots)
        self.refresh_btn.pack(anchor="w", padx=12, pady=(0, 6))
        for b in (self.write_btn, self.clear_btn, self.refresh_btn):
            self.reg(b)

    def _toggle_key_visibility(self):
        self.key_entry.config(show="" if self.show_var.get() else "*")

    # --- валідація вводу -------------------------------------------------------

    def _read_key32(self):
        text = self.key_var.get().strip().replace(" ", "")
        try:
            key = bytes.fromhex(text)
        except ValueError:
            messagebox.showerror("Невірний ключ", "Ключ має бути рядком із 64 шістнадцяткових символів (0-9, A-F).")
            return None
        if len(key) != 32:
            messagebox.showerror("Невірний ключ", "Ключ має бути рівно 64 hex-символи (32 байти), зараз {}.".format(len(text)))
            return None
        return key

    # --- дії користувача ---------------------------------------------------------

    def _run(self, fn, text):
        self.shell.run_task(fn, text, plain_errors=True)

    def _on_write_key(self):
        if self.shell.busy:
            return
        key32 = self._read_key32()
        if key32 is None:
            return
        key_id = self.keyid_var.get()
        if not messagebox.askokcancel(
            "Записати ключ?",
            "Записати ключ у слот {} на рації?\n\n"
            "Переконайся, що рація увімкнена у ЗВИЧАЙНОМУ режимі (не в DFU).".format(key_id),
        ):
            return
        self._run(lambda: self._write_key_worker(key_id, key32), "Записую ключ {}...".format(key_id))

    def _on_clear_key(self):
        if self.shell.busy:
            return
        key_id = self.keyid_var.get()
        if not messagebox.askokcancel(
            "Очистити ключ?",
            "Стерти ключ у слоті {} на рації? Цю дію не можна скасувати.".format(key_id),
        ):
            return
        self._run(lambda: self._clear_key_worker(key_id), "Очищую ключ {}...".format(key_id))

    def _on_refresh_slots(self):
        if self.shell.busy:
            return
        self._run(self._refresh_slots_worker, "Читаю зайняті слоти...")

    # --- фонові операції (у потоці) ------------------------------------------------

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

    def _write_key_worker(self, key_id, key32):
        with self._connect() as ser:
            addr = skt.entry_addr(key_id)
            existing = aes_key_store.flash_read(ser, addr, skt.STOCK_KEY_ENTRY_LEN)
            entry = skt.build_entry(key_id, key32, existing_entry100=existing if len(existing) == skt.STOCK_KEY_ENTRY_LEN else None)
            aes_key_store.flash_write_block(ser, addr, entry)
            readback = aes_key_store.flash_read(ser, addr, skt.STOCK_KEY_ENTRY_LEN)
            ok = (readback == entry)
            print("Ключ {}: записано, звірка {}.".format(key_id, "OK" if ok else "НЕЗБІГ (спробуй ще раз)"))

    def _clear_key_worker(self, key_id):
        with self._connect() as ser:
            addr = skt.entry_addr(key_id)
            existing = aes_key_store.flash_read(ser, addr, skt.STOCK_KEY_ENTRY_LEN)
            entry = skt.build_entry(key_id, skt.BLANK_KEY, existing_entry100=existing if len(existing) == skt.STOCK_KEY_ENTRY_LEN else None)
            aes_key_store.flash_write_block(ser, addr, entry)
            print("Ключ {}: очищено (позначено як порожній слот).".format(key_id))

    def _refresh_slots_worker(self):
        with self._connect() as ser:
            occupied = []
            for key_id in range(skt.STOCK_KEY_MIN_ID, skt.STOCK_KEY_MAX_ID + 1):
                entry = aes_key_store.flash_read(ser, skt.entry_addr(key_id), skt.STOCK_KEY_ENTRY_LEN)
                if len(entry) != skt.STOCK_KEY_ENTRY_LEN:
                    continue
                entry_type, _name, wrapped = skt.parse_entry(entry)
                if entry_type in (skt.STOCK_KEY_TYPE_AES256, skt.STOCK_KEY_TYPE_AES256B):
                    if skt.is_key_present(skt.unwrap_key(wrapped)):
                        occupied.append(key_id)

            # Зайняті слоти запам'ятовуємо для редактора каналу (V3.2): лише НОМЕРИ, матеріал ключа не зберігається нікуди.
            self.shell.aes_slots = {"occupied": tuple(occupied)}
            self.shell.post(self.shell.on_aes_slots_changed)

            empty = [i for i in range(skt.STOCK_KEY_MIN_ID, skt.STOCK_KEY_MAX_ID + 1) if i not in occupied]
            print("Зайняті слоти: {}".format(", ".join(map(str, occupied)) if occupied else "немає"))
            print("Порожні слоти: {}".format(", ".join(map(str, empty)) if empty else "немає"))
