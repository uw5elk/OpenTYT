#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R73 (хост-перевірки; ТІЛЬКИ ЛІЧИЛЬНИКИ -- секунд на підставній рації нема): запис -- по секторах, фіксовані очікування, перемикач розміру запиту, прапорець звірки документа.
Запуск: python3 tools/test_r73.py (GUI-частини -- під xvfb)"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import io_stats                    # noqa: E402
import aes_key_store as aks        # noqa: E402
import aes_keys_backup as akb      # noqa: E402
import cps_link as cl              # noqa: E402
import custom_region as cr         # noqa: E402
import flash_guard as fg           # noqa: E402
import test_cps_restore as tcr     # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ: " + msg)


def read(*p):
    with open(os.path.join(*p), encoding="utf-8") as f:
        return f.read()


def erases(fn):
    b = io_stats.snapshot()
    out = fn()
    return io_stats.delta(b)["sector_erases"], out


# ---------------------------------------------------------------------------------------------------------------------------------
def make_region(blocks):
    """blocks: [(type, bytes)] -> 64 КіБ області з заголовком OpenGD77."""
    reg = bytearray(b"\xff" * cr.REGION_LEN)
    reg[0:12] = cr.MAGIC + b"\x00" * 4
    a = 12
    for t, pl in blocks:
        reg[a:a + 8] = struct.pack("<ii", t, len(pl))
        reg[a + 8:a + 8 + len(pl)] = pl
        a += 8 + len(pl)
    return bytes(reg)


def radio_with_region(reg):
    spi = tcr.spi_a()
    spi[0x20000:0x30000] = reg
    return tcr.FakeRadioX(bytearray(spi))


def blocks_of(radio):
    return {b.type: b.payload for b in cr.parse_region(bytes(radio.spi[0x20000:0x30000])).blocks}


def test_write_group_primitive():
    radio = tcr.FakeRadioX(tcr.spi_a())
    ser = radio
    n, order = erases(lambda: fg.write_group(ser, [(0x20010, b"A" * 10), (0x20100, b"B" * 10), (0x20FF8, b"C" * 16)], "customdata"))
    check(order == [0x20, 0x21] and n == 2, "write_group: 3 ділянки у 2 секторах (одна перетинає межу) = 2 стирання: %r %r" % (order, n))
    check(bytes(radio.spi[0x20010:0x2001A]) == b"A" * 10 and bytes(radio.spi[0x20FF8:0x21008]) == b"C" * 16, "write_group: байти на місці")
    n0 = io_stats.snapshot()
    try:
        fg.write_group(ser, [(0x20010, b"X"), (0x10010, b"Y")], "customdata")
        check(False, "write_group: ділянка поза вікном має відхилятись")
    except fg.GuardError:
        check(io_stats.delta(n0)["sector_erases"] == 0 and radio.spi[0x20010] == ord("A"), "write_group: відхилено ДО першого звернення до флеша (перша ділянка теж не записана)")
    # стара поведінка для порівняння: кожна ділянка окремо = окреме стирання
    n_old, _ = erases(lambda: [aks.flash_write_block(ser, a, d) for a, d in ((0x22010, b"A"), (0x22100, b"B"), (0x22200, b"C"))])
    n_new, _ = erases(lambda: fg.write_group(ser, [(0x23010, b"A"), (0x23100, b"B"), (0x23200, b"C")], "customdata"))
    check(n_old == 3 and n_new == 1, "три ділянки одного сектора: окремо 3 стирання, групою 1 (було %d, стало %d)" % (n_old, n_new))


def test_keys_restore_one_erase():
    import test_r31 as t31
    old = t31.no_sleep()
    try:
        occ = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15}
        table_a = t31.make_table(2, occ)
        path, _d, _m, _r = t31.mk_zip(t31.put_table(tcr.spi_a(), table_a))
        spi_b = t31.put_table(tcr.spi_b(tcr.spi_a()), t31.make_table(9, set()))
        radio = tcr.FakeRadioX(bytearray(spi_b))
        n, res = erases(lambda: akb.restore_keys(cl.CpsLink(radio), path, t31.confirm_recorder()[0], log=t31.quiet, post_reset=False))
        check(res["result"]["written"] == sorted(occ) and not res["result"]["failed"], "ключі: усі 15 слотів записано й звірено")
        check(n == 1, "ключі: 15 слотів = %d стирання сектора (до R73 було 15)" % n)
        check(t31.table_of(radio.spi) == table_a or all(akb.entry_of(t31.table_of(radio.spi), s) == akb.entry_of(table_a, s) for s in occ), "ключі: вміст збігся з бекапом")
    finally:
        import time
        time.sleep = old


def test_custom_region_groups():
    a = [(4, b"\x04" * 64), (5, b"\x05" * 64), (7, b"\x07" * 1352), (8, b"\x08" * 493), (9, b"\x09" * 8)]
    b = [(t, bytes(x ^ 0x55 for x in pl)) for t, pl in a]
    reg_cur, reg_src = make_region(a), make_region(b)
    # --- нова поведінка: усі 5 блоків лежать в секторі 0 -> одне стирання ---
    radio = radio_with_region(reg_cur)
    link = cl.CpsLink(radio)
    plan = cr.plan_restore(reg_src, reg_cur, selected={4, 5, 7, 8, 9})
    n_new, res = erases(lambda: cr.apply_plan(link, plan, log=lambda *_: None))
    check(not res["failed"] and len(res["written"]) == 5 and blocks_of(radio) == dict(b), "custom-data: 5 блоків записано й звірено")
    check(n_new == 1, "custom-data: 5 блоків одного сектора = %d стирання (до R73 було 5)" % n_new)
    # --- стара поведінка (для порівняння лічильників) ---
    radio_o = radio_with_region(reg_cur)
    n_old, res_o = erases(lambda: cr._apply_plan_per_block(cl.CpsLink(radio_o), plan, log=lambda *_: None))
    check(n_old == 5 and blocks_of(radio_o) == dict(b), "custom-data: блок за блоком давав %d стирань (контроль лічильника)" % n_old)
    check(bytes(radio.spi[0x20000:0x30000]) == bytes(radio_o.spi[0x20000:0x30000]), "custom-data: підсумкова область байт-у-байт та сама, що при записі блок за блоком")


def test_custom_region_multi_sector_failure():
    big = [(4, b"\x04" * 3000), (5, b"\x05" * 3000), (7, b"\x07" * 3000), (8, b"\x08" * 3000)]       # 4: сектор 0; 5: 0..1; 7: 1..2; 8: 2..3
    new = [(t, bytes(x ^ 0x33 for x in pl)) for t, pl in big]
    reg_cur, reg_src = make_region(big), make_region(new)
    plan = cr.plan_restore(reg_src, reg_cur, selected={4, 5, 7, 8})
    radio = radio_with_region(reg_cur)
    real = aks.flash_write_sector
    calls = []

    def failing(ser, sector, parts):
        calls.append(sector)
        if len(calls) == 2:
            raise RuntimeError("імітація збою другого сектора")
        return real(ser, sector, parts)
    aks.flash_write_sector = failing
    try:
        res = cr.apply_plan(cl.CpsLink(radio), plan, log=lambda *_: None)
    finally:
        aks.flash_write_sector = real
    check(res["failed"] is not None and calls[0] < calls[1], "кілька секторів: збій на другому секторі зупиняє запис: %r" % calls)
    check(len(calls) == 2, "кілька секторів: після збою нових записів нема")
    got = blocks_of(radio)
    check(got[4] == dict(new)[4], "кілька секторів: блок першої групи записаний і лишається записаним")
    check(all(got[t] == dict(big)[t] for t in (7, 8)), "кілька секторів: блоки, що не дійшли, лишились як були")
    check(res["written"] and res["written"][0].type == 4, "кілька секторів: звіт називає записаний блок")


def test_custom_region_stale_plan_and_verify():
    a = [(4, b"\x04" * 64), (5, b"\x05" * 64)]
    reg_cur = make_region(a)
    reg_src = make_region([(4, b"\x44" * 64), (5, b"\x55" * 64)])
    plan = cr.plan_restore(reg_src, reg_cur, selected={4, 5})
    # рація змінила область після читання (інша довжина блока 4): нічого не записуємо
    other = bytearray(reg_cur)
    other[12:20] = struct.pack("<ii", 4, 80)
    radio = radio_with_region(bytes(other))
    n, res = erases(lambda: cr.apply_plan(cl.CpsLink(radio), plan, log=lambda *_: None))
    check(res["failed"] and "змінилась" in res["failed"]["message"] and n == 0 and bytes(radio.spi[0x20000:0x30000]) == bytes(other),
          "застарілий план: область змінилась -> нічого не записано (стирань %d)" % n)
    # звірка: рація «псує» читання блока 5 після запису
    radio2 = radio_with_region(reg_cur)
    link = cl.CpsLink(radio2)
    import custom_data as cd
    # (звірка йде через cd._read_region -> aks.flash_read; псуємо на рівні aks)
    real_fr = aks.flash_read

    def bad_fr(ser, addr, ln):
        d = bytearray(real_fr(ser, addr, ln))
        if addr == 0x20000 + 12 + 8 + 64 and ln == 72:
            d[0] ^= 0xFF
        return bytes(d)
    aks.flash_read = bad_fr
    try:
        res2 = cr.apply_plan(link, plan, log=lambda *_: None)
    finally:
        aks.flash_read = real_fr
    check(res2["failed"] and res2["failed"]["block"].type == 5 and [b.type for b in res2["written"]] == [4], "звірка: розбіжність блока 5 -> помилка; блок 4 записаний: %r" % res2["failed"])


def test_header_needed_in_first_group():
    radio = tcr.FakeRadioX(tcr.spi_a())
    radio.spi[0x20000:0x30000] = b"\xff" * 0x10000
    src = make_region([(4, b"\x04" * 64), (5, b"\x05" * 64)])
    plan = cr.plan_restore(src, b"\xff" * 0x10000, selected={4, 5})
    n, res = erases(lambda: cr.apply_plan(cl.CpsLink(radio), plan, log=lambda *_: None))
    check(plan.header_needed and not res["failed"] and res["headerWritten"] and n == 1, "стерта область: заголовок і блоки одним записом сектора (стирань %d)" % n)
    check(bytes(radio.spi[0x20000:0x2000C]) == cr.MAGIC + b"\x00" * 4 and blocks_of(radio) == {4: b"\x04" * 64, 5: b"\x05" * 64}, "стерта область: заголовок і блоки на місці")


def test_compact_erases():
    """Ущільнення: ділянки даних, що змінюються, пишуться по секторах -- кожен сектор даних стирається раз. Контроль: число стирань = число різних секторів,
    у яких щось змінилось, + 2 для сектора заголовка (обнулення й запис заголовка останнім -- порядок безпеки, не чіпано)."""
    import test_r37 as t37
    import custom_compact as cc
    spi = t37.make_spi(t37.build_region(t37.sample_entries())[0])
    before = bytes(spi[t37.BASE:t37.BASE + t37.LEN])
    radio = tcr.FakeRadioX(spi)
    import tempfile
    n, res = erases(lambda: cc.compact_region(cl.CpsLink(radio), lambda *_a: True, tempfile.mkdtemp(prefix="r73_"), log=lambda *_: None, post_reset=False))
    after = bytes(radio.spi[t37.BASE:t37.BASE + t37.LEN])
    changed = sorted({i // 4096 for i in range(len(before)) if before[i] != after[i]})
    check(res and after != before, "ущільнення виконано")
    data_sectors = [x for x in changed if x != 0]
    check(n == len(data_sectors) + 2, "ущільнення: %d стирань = %d секторів даних + 2 (заголовок) (змінені сектори %r)" % (n, len(data_sectors), changed))
    check(len(radio.commits) == len(set(radio.commits[1:-1])) + 2, "ущільнення: кожен сектор даних стерто один раз: %r" % radio.commits)


def test_phase_erases():
    import phase_timing
    ph = phase_timing.Phases(None)
    with ph.phase("запис"):
        io_stats.add("sector_erases", 3)
    check(ph.items[0]["erases"] == 3 and "стирань секторів: 3" in ph.summary(), "фаза показує число стирань секторів: %s" % ph.summary())
    check("стирань секторів" in io_stats.describe(io_stats.delta(io_stats.snapshot()), 0.0), "рядок «Вимір …» містить стирання секторів")


def main():
    test_write_group_primitive()
    test_keys_restore_one_erase()
    test_custom_region_groups()
    test_custom_region_multi_sector_failure()
    test_custom_region_stale_plan_and_verify()
    test_header_needed_in_first_group()
    test_compact_erases()
    test_phase_erases()
    if FAILS:
        print("test_r73: ПРОВАЛІВ %d" % len(FAILS))
        sys.exit(1)
    print("test_r73: усе гаразд")


if __name__ == "__main__":
    main()
