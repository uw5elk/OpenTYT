#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R71 (хост-перевірки; ТІЛЬКИ ЛІЧИЛЬНИКИ -- на підставній рації секунди нічого не означають).

1  вимір (етап 1): io_stats, обгортка measure() із підставним годинником, підключення до run_task, лічильники в читачах/писарях;
   сценарії r71_scenarios.py дають числа запитів/КіБ/очікувань тайм-ауту для кожної операції.
Запуск: python3 tools/test_r71.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import io_stats                    # noqa: E402
import aes_key_store as aks        # noqa: E402
import r71_scenarios as sc         # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ: " + msg)


def read(*p):
    with open(os.path.join(*p), encoding="utf-8") as f:
        return f.read()


def table():
    return {name: d for name, d in sc.table()}


def test_measure():
    lines = []
    t = iter([100.0, 103.4])
    b = io_stats.snapshot()
    with io_stats.measure("Читаю ключі AES", clock=lambda: next(t), out=lines.append):
        io_stats.add("read_req", 2)
        io_stats.add("read_bytes", 1536)
    check(len(lines) == 1 and "Читаю ключі AES" in lines[0] and "3.4 с" in lines[0] and "2 запитів" in lines[0] and "1.5 КіБ" in lines[0], "measure: рядок журналу: %r" % lines)
    check(io_stats.delta(b)["read_req"] == 2, "delta рахує різницю")
    out = []
    try:
        with io_stats.measure("збій", clock=lambda: 0.0, out=out.append):
            raise RuntimeError("x")
    except RuntimeError:
        pass
    check(len(out) == 1, "measure друкує підсумок і при помилці")
    app = read(HERE, "cps_ui", "app.py")
    check("io_stats.measure(status_text" in app and "if quiet:" in app, "run_task міряє кожну не фонову операцію")


def test_counters():
    env = sc.Env()
    try:
        b = io_stats.snapshot()
        aks.flash_read(env.radio, 0x20000, 12)
        d = io_stats.delta(b)
        check(d["read_req"] == 1 and d["read_bytes"] == 12, "flash_read рахує запит і байти: %r" % d)
    finally:
        env.close()


def test_fast_reader():
    """2.1: aks.flash_read -- тонка обгортка швидкого читача (довжина з заголовка відповіді), без очікувань тайм-ауту."""
    t = table()
    for name in ("AES: «Оновити слоти» (15 записів)", "RCTL: прочитати", "бікон/шумодав: прочитати"):
        d = t[name]
        check(d["port_timeouts"] + d["short_reads"] == 0, "%s: очікувань тайм-ауту у читанні 0, а є %r" % (name, d))
    # 2.2 (свідома заміна очікування «15 запитів» з етапу 1: таблиця ключів читається суцільною ділянкою 15x100 Б = 1500 Б, CpsLink.CHUNK=1024 -> 2 запити)
    check(t["AES: «Оновити слоти» (15 записів)"]["read_req"] == 2, "«Оновити слоти» = 2 запити (дані: %r)" % t["AES: «Оновити слоти» (15 записів)"])
    check(t["AES: «Оновити слоти» (15 записів)"]["read_bytes"] == 1500, "«Оновити слоти» читає рівно 1500 Б таблиці")
    src = read(HERE, "aes_key_store.py")
    i = src.index("def flash_read(")
    body = src[i:i + 900]
    check("time.sleep" not in body and "ser.read(" not in body, "flash_read не спить і не читає сирий порт")


def test_x_replies():
    """2.1b: запис через X без sleep і без 8-байтового очікування: тайм-аутів нема, пакетів рівно 3 (X1, X2, X3)."""
    d = table()["AES: записати ключ (читання+запис+звірка)"]
    check(d["x_packets"] == 3 and d["port_timeouts"] + d["short_reads"] == 0, "запис ключа: 3 X-пакети, 0 тайм-аутів: %r" % d)
    src = read(HERE, "aes_key_store.py")
    i = src.index("def flash_write_block(")
    j = src.index("def fresh_payload(")
    check("time.sleep" not in src[i:j] and "ser.read(" not in src[i:j], "flash_write_block не спить і не читає сирий порт")


def test_location_cache():
    import struct
    import custom_data as cd
    env = sc.Env()
    try:
        cd.invalidate()
        b = io_stats.snapshot()
        cold = cd.read_block(env.radio, 9, 8)
        n_cold = io_stats.delta(b)["read_req"]
        check(cold == bytes([9]) * 8, "холодне читання повертає дані блока")
        b = io_stats.snapshot()
        warm = cd.read_block(env.radio, 9, 8)
        dw = io_stats.delta(b)
        check(warm == cold and dw["read_req"] == 1 and n_cold > 1, "тепле читання = 1 запит (холодне %d): %r" % (n_cold, dw))
        # блок вперше читався при обході: інші типи теж запам'ятались -> їх перше читання теж 1 запит
        b = io_stats.snapshot()
        cd.read_block(env.radio, 4, 64)
        check(io_stats.delta(b)["read_req"] == 1, "блоки, пройдені під час обходу, теж відомі")
        # дані ЗАВЖДИ свіжі: рація змінила вміст блока -- читання це бачить
        addr = cd._LOCS[cd._key(env.radio)][9][0]
        env.radio.spi[0x20000 + addr + 8:0x20000 + addr + 16] = bytes(range(1, 9))
        check(cd.read_block(env.radio, 9, 8) == bytes(range(1, 9)), "дані з кешу не віддаються: змінений рацією вміст видно")
        # розбіжність заголовка -> повний обхід (рація «вилучила»/перемістила блок)
        env.radio.spi[0x20000 + addr:0x20000 + addr + 8] = struct.pack("<ii", 0x7E000009, 8)
        b = io_stats.snapshot()
        check(cd.read_block(env.radio, 9, 8) is None, "блок вилучено поза ПК -> None після повторного обходу")
        check(io_stats.delta(b)["read_req"] > 1, "розбіжність заголовка веде до повного обходу")
        # запис скидає кеш; після запису розташування відоме, звірка = 1 запит
        cd.invalidate()
        ok, _m = cd.write_block(env.radio, 4, bytes([5]) * 64)
        check(ok, "write_block працює з кешем")
        b = io_stats.snapshot()
        check(cd.read_block(env.radio, 4, 64) == bytes([5]) * 64, "після запису читання бачить нові дані")
        check(io_stats.delta(b)["read_req"] == 1, "після запису звірка = 1 запит")
        # сторонній запис у область (restore/compact) скидає кеш
        cd._remember(env.radio, 77, 12, 8)
        import aes_key_store as _a
        _a.notify_flash_write(0x20000 + 100, 10)
        check(not cd._LOCS, "запис у область custom-data скидає кеш")
        _a.notify_flash_write(0xD9F9C, 100)
        cd._remember(env.radio, 77, 12, 8)
        _a.notify_flash_write(0xD9F9C, 100)
        check(cd._LOCS, "запис ПОЗА областю (таблиця AES) кеш не чіпає")
    finally:
        cd.invalidate()
        env.close()
    # після ущільнення/відновлення (cps_restore.write_sector) кеш теж скидається
    src = read(HERE, "cps_restore.py")
    check("notify_flash_write(raw_addr" in src, "write_sector повідомляє про запис")
    check("_cd.invalidate()" in read(HERE, "codeplug_view.py"), "«відкрити з рації» скидає кеш")


def main():
    test_measure()
    test_counters()
    test_fast_reader()
    test_x_replies()
    test_location_cache()
    if FAILS:
        print("test_r71: ПРОВАЛІВ %d" % len(FAILS))
        sys.exit(1)
    print("test_r71: усе гаразд")


if __name__ == "__main__":
    main()
