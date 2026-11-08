# -*- coding: utf-8 -*-
"""R71: сценарії виміру ЛІЧИЛЬНИКІВ обміну на підставній рації (tools/test_cps_restore.FakeRadioX). Секунд тут нема й бути не може: підставна рація відповідає миттєво.
Використання: python3 r71_scenarios.py  -- друкує таблицю «операція -> запитів, КіБ, очікувань тайм-ауту, пакетів X» (для звіту й порівняння до/після)."""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import io_stats                    # noqa: E402
import cps_link as cl              # noqa: E402
import aes_key_store as aks        # noqa: E402
import custom_data as cd           # noqa: E402
import stock_key_table as skt      # noqa: E402
import test_cps_link as base       # noqa: E402
import test_cps_restore as tr      # noqa: E402

# Типова область custom-data на працюючій рації: заставка, мелодія, TLE, теми дня/ночі, AES-селектор, повідомлення, ..., RCTL (9) пізніше. Довжини з кодів модулів.
REGION_BLOCKS = [(1, 1024), (2, 512), (3, 2520), (4, 64), (5, 64), (6, 584), (7, 1200), (8, 300), (9, 8), (14, 16), (15, 8)]


def make_radio_image():
    spi = tr.spi_a()
    reg = bytearray(b"\xff" * 0x10000)
    reg[0:12] = b"OpenGD77" + b"\x00\x00\x00\x00"
    addr = 12
    for t, ln in REGION_BLOCKS:
        reg[addr:addr + 8] = struct.pack("<ii", t, ln)
        reg[addr + 8:addr + 8 + ln] = bytes([t]) * ln
        addr += 8 + ln
    spi[0x20000:0x30000] = reg
    # таблиця ключів AES: 15 записів по 100 Б, кожен із типом AES-256 (як у стокової таблиці)
    for k in range(skt.STOCK_KEY_MIN_ID, skt.STOCK_KEY_MAX_ID + 1):
        a = skt.entry_addr(k)
        spi[a:a + 100] = skt.build_entry(k, bytes([k]) * 32)
    return spi


class Env:
    def __init__(self):
        self.radio = tr.FakeRadioX(make_radio_image())
        self.link = cl.CpsLink(self.radio, retries=0)
        self._sleep = aks.time.sleep
        aks.time.sleep = lambda _s: None       # підставна рація не потребує пауз; секунд ми тут не міряємо

    def close(self):
        aks.time.sleep = self._sleep


def run(name, fn, env):
    cd.invalidate()
    b = io_stats.snapshot()
    fn(env)
    d = io_stats.delta(b)
    if hasattr(env, "warm"):
        d = env.warm                                         # для «гарячих» сценаріїв рахується лише друга частина
    return name, d


def op_open_document(env):
    import codeplug_view as cv
    cv.codeplug_from_radio(env.link)


def op_aes_refresh(env):
    a, n = skt.table_span()                                  # те, що робить p_aes._refresh_slots_worker
    skt.split_table(aks.flash_read(env.radio, a, n))


def op_aes_write_key(env):
    k = 3
    a = skt.entry_addr(k)
    existing = aks.flash_read(env.radio, a, 100)
    entry = skt.build_entry(k, bytes([77]) * 32, existing_entry100=existing)
    aks.flash_write_block(env.radio, a, entry)
    aks.flash_read(env.radio, a, 100)


def op_rctl_read(env):
    cd.read_block(env.radio, 9, 8)


def op_rctl_read_warm(env):
    cd.invalidate()
    cd.read_block(env.radio, 9, 8)                          # перше читання у сесії -- холодне (обхід області)
    b = io_stats.snapshot()
    cd.read_block(env.radio, 9, 8)                          # друге -- розташування вже відоме: 1 запит
    env.warm = io_stats.delta(b)


def op_rctl_write(env):
    cd.read_block(env.radio, 9, 8)                          # p_rctl._write_worker: поточний стан
    ok, _m = cd.write_block(env.radio, 9, bytes([1, 2, 3, 4, 5, 6, 7, 8]))
    assert ok
    cd.read_block(env.radio, 9, 8)                          # звірка


def op_beacon_read(env):
    import aprs_beacon_cfg as ab
    ab.read_state(env.radio)


def op_backup(env):
    cl.backup_codeplug(env.link, log=lambda *_: None)


OPS = [("відкрити документ з рації (EEPROM+флеш)", op_open_document), ("AES: «Оновити слоти» (15 записів)", op_aes_refresh),
       ("AES: записати ключ (читання+запис+звірка)", op_aes_write_key), ("RCTL: прочитати", op_rctl_read), ("RCTL: прочитати вдруге (розташування відоме)", op_rctl_read_warm), ("RCTL: записати (стан+запис+звірка)", op_rctl_write),
       ("бікон/шумодав: прочитати", op_beacon_read), ("бекап (EEPROM+флеш+custom-data+ключі)", op_backup)]


def table():
    rows = []
    for name, fn in OPS:
        env = Env()
        try:
            rows.append(run(name, fn, env))
        finally:
            env.close()
    return rows


if __name__ == "__main__":
    print("%-52s %8s %8s %10s %8s" % ("операція", "запитів", "КіБ", "тайм-аутів", "X-пакетів"))
    for name, d in table():
        print("%-52s %8d %8.1f %10d %8d" % (name, d["read_req"], d["read_bytes"] / 1024.0, d["port_timeouts"] + d["short_reads"], d["x_packets"]))
