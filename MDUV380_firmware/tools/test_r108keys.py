#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R108-FLUSHFIX (правка 2): запис таблиці ключів AES (сектор 0xDA000) з CPS -- лише на екрані CPS.

Підставна рація -- test_cps_restore.FakeRadioX (порядок C/X-команд записується). Перевіряємо:
  К1  aes_keys_backup.apply_plan: 'C' 0 ПЕРЕД першою X-командою, 'C' 5 після (перезавантаження нема); жодної C, коли писати нічого.
  К2  restore_keys з перезавантаженням: C 0 ... C 6 1, БЕЗ C 5, рівно одне C 0.
  К3  restore_keys без перезавантаження (post_reset=False): C 0 ... C 5.
  К4  «Скасувати» в діалозі: жодної C/X.
  К5  виняток посеред запису (порт замовк): 'C' 5 у finally; екран позначено закритим.
  К6  екран уже відкритий (restore_codeplug без перезавантаження) -- 'C' 0 вдруге не шлеться; повний цикл кодплаг + ключі: рівно одне C 0 і один C 6 1.
  К7  мутант «без 'C' 0» ловиться тими ж перевірками.
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aes_keys_backup as akb      # noqa: E402
import cps_link as cl              # noqa: E402
import cps_restore as crest        # noqa: E402
import test_cps_restore as tcr     # noqa: E402
import test_r31 as t31             # noqa: E402

FAILS = []
N = [0]
C0, C5, C61 = bytes([0]), bytes([5]), bytes([6, 1])
OCC = {2, 5, 9}


def check(cond, msg):
    N[0] += 1
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def quiet(*_a, **_k):
    pass


class Radio(tcr.FakeRadioX):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.seq = []

    def write(self, data):
        d = bytes(data)
        if d[:1] in (b"C", b"X"):
            self.seq.append(d[:1] + d[1:3] if d[:1] == b"C" else b"X")
        return super().write(data)


def order_ok(r):
    xs = [i for i, s in enumerate(r.seq) if s == b"X"]
    c0 = next((i for i, s in enumerate(r.seq) if s[:2] == b"C\x00"), None)
    return bool(xs) and c0 is not None and c0 < xs[0]


def setup():
    """(архів із ключами 2, 5, 9; образ рації B, де цих ключів нема)."""
    table_a = t31.make_table(1, OCC)
    spi_a = t31.put_table(tcr.spi_a(), table_a)
    path, _data, _m, _r = t31.mk_zip(spi_a)
    tb = bytearray(table_a)
    for s in (2, 5):
        tb[s * 100:(s + 1) * 100] = t31.make_table(0, set())[s * 100:(s + 1) * 100]
    tb[9 * 100:10 * 100] = t31.make_table(7, {9})[900:1000]
    spi_b = t31.put_table(tcr.spi_b(tcr.spi_a()), bytes(tb))
    return path, spi_b


def plan_for(path, spi_b):
    r = Radio(bytearray(spi_b))
    src = akb.read_backup_keys(path)
    cur = akb.read_radio_keys(cl.CpsLink(r))
    r.seq = []
    return r, akb.plan_restore(src, cur, None)


def test_apply_plan(path, spi_b):
    r, plan = plan_for(path, spi_b)
    link = cl.CpsLink(r)
    res = akb.apply_plan(link, plan, log=quiet)
    check(res["written"] == [2, 5, 9] and not res["failed"], "К1: записано слоти 2, 5, 9: %r" % (res,))
    check(r.c_calls == [C0, C5], "К1: apply_plan -- C 0 ... C 5: %r" % r.c_calls)
    check(order_ok(r), "К1: C 0 раніше першої X-команди: %r" % r.seq[:3])
    check(not crest.screen_is_open(link), "К1: після apply_plan екран позначено закритим")
    # нічого писати
    r2 = Radio(bytearray(spi_b))
    src = akb.read_backup_keys(path)
    plan0 = akb.plan_restore(src, src, None)
    akb.apply_plan(cl.CpsLink(r2), plan0, log=quiet)
    check(r2.c_calls == [] and r2.x_total == 0, "К1: нічого писати -- жодної C/X: %r" % r2.c_calls)


def test_restore_keys(path, spi_b):
    r = Radio(bytearray(spi_b))
    res = akb.restore_keys(cl.CpsLink(r), path, lambda *a: True, log=quiet)
    check(res["result"]["written"] == [2, 5, 9], "К2: restore_keys записав")
    check(r.c_calls == [C0, C61], "К2: C 0, C 6 1 (без C 5, одне C 0): %r" % r.c_calls)
    check(order_ok(r), "К2: C 0 раніше першої X")
    r = Radio(bytearray(spi_b))
    akb.restore_keys(cl.CpsLink(r), path, lambda *a: True, log=quiet, post_reset=False)
    check(r.c_calls == [C0, C5], "К3: без перезавантаження -- C 0, C 5: %r" % r.c_calls)
    r = Radio(bytearray(spi_b))
    res = akb.restore_keys(cl.CpsLink(r), path, lambda *a: False, log=quiet)
    check(res["cancelled"] and r.c_calls == [] and r.x_total == 0, "К4: «Скасувати» -- жодної C/X: %r" % r.c_calls)


class Boom(Exception):
    pass


def test_failure(path, spi_b):
    import flash_guard as fg
    r, plan = plan_for(path, spi_b)
    link = cl.CpsLink(r)
    real = fg.write_group

    def bad(*a, **k):
        raise Boom("порт замовк")
    fg.write_group = bad
    try:
        res = akb.apply_plan(link, plan, log=quiet)       # apply_plan ловить виняток запису сам
    finally:
        fg.write_group = real
    check(res["failed"] and not res["written"], "К5: збій запису повернуто як failed")
    check(r.c_calls == [C0, C5], "К5: збій -- C 0, C 5 (екран закрито): %r" % r.c_calls)
    check(not crest.screen_is_open(link), "К5: екран закрито")
    # виняток, що проходить назовні (читання після запису)
    r, plan = plan_for(path, spi_b)
    link = cl.CpsLink(r)

    def read_die(self, *a, **k):
        raise Boom("порт замовк при читанні")
    real_read = cl.CpsLink.read
    cl.CpsLink.read = read_die
    try:
        try:
            akb.apply_plan(link, plan, log=quiet)
            check(False, "К5: виняток читання мав пройти назовні")
        except Boom:
            pass
    finally:
        cl.CpsLink.read = real_read
    check(r.c_calls == [C0, C5] and not crest.screen_is_open(link), "К5: виняток -- C 5 у finally: %r" % r.c_calls)


def test_nested(path, spi_b):
    r = Radio(bytearray(spi_b))
    link = cl.CpsLink(r)
    crest.screen_open(link)                 # як restore_codeplug(post_reset=False)
    r2, plan = plan_for(path, spi_b)
    r.seq = []
    src = akb.read_backup_keys(path)
    plan = akb.plan_restore(src, akb.read_radio_keys(link), None)
    with crest.cps_screen(link, open_now=False):
        akb.apply_plan(link, plan, log=quiet)
        check(r.c_calls == [C0], "К6: вкладений apply_plan -- ні C 0 вдруге, ні C 5: %r" % r.c_calls)
        crest._send_c(link, 6, 1)
    check(r.c_calls == [C0, C61], "К6: після C 6 1 зовнішній блок C 5 не шле: %r" % r.c_calls)


def run_all():
    path, spi_b = setup()
    test_apply_plan(path, spi_b)
    test_restore_keys(path, spi_b)
    test_failure(path, spi_b)
    test_nested(path, spi_b)


def main():
    old = time.sleep
    time.sleep = lambda *_: None
    try:
        run_all()
        # К7: мутант «без C 0»
        global FAILS
        saved, FAILS = FAILS, []
        import builtins
        p = builtins.print
        real_open = crest.screen_open
        crest.screen_open = lambda link: crest._mark_screen(link, True)
        builtins.print = lambda *a, **k: None
        try:
            path, spi_b = setup()
            test_apply_plan(path, spi_b)
            test_restore_keys(path, spi_b)
        finally:
            builtins.print = p
            crest.screen_open = real_open
        caught = bool(FAILS)
        FAILS = saved
        check(caught, "К7: мутант «без C 0» не спіймано")
    finally:
        time.sleep = old
    if FAILS:
        print("test_r108keys: перевірок %d, провалів %d" % (N[0], len(FAILS)))
        return 1
    print("test_r108keys: усе гаразд (%d перевірок: ключі AES на екрані CPS; послідовності, вкладення, збій, скасування, мутант)" % N[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
