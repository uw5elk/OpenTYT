#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R107-CPSUSB, частина А (В2): запис custom-data з CPS -- лише на екрані CPS ('C' 0 ... 'C' 6 1 або 'C' 5).

Підставна рація -- test_cps_restore.FakeRadioX (записує кожну C-команду в c_calls і кожну X-команду в x_calls).
Перевіряємо (без рації):
  А1  custom_region.apply_plan (групи по секторах): 'C' 0 ПЕРЕД першою X-командою, 'C' 5 після останньої; без C на «нічого писати».
  А2  _apply_plan_per_block (план без cur_data): те саме.
  А3  restore_region / apply_settings з перезавантаженням: 'C' 0 ... 'C' 6 1, БЕЗ 'C' 5 (рація й так перезавантажується).
  А4  doc_region.write_region без перезавантаження: 'C' 0 ... 'C' 5.
  А5  doc_write.write_document (лише налаштування; кодплаг + налаштування): рівно одне 'C' 0, останнє -- 'C' 6 1, 'C' 5 нема.
  А6  екран уже відкритий (restore_codeplug без перезавантаження, потім область): 'C' 0 не надсилається вдруге.
  А7  виняток посеред запису (порт «замовк») -> 'C' 5 у finally; збій запису без винятку й без перезавантаження -> 'C' 5.
  А8  скасування в діалозі -> жодної C-команди.
  А9  мутанти: «без 'C' 0» і «без 'C' 5 у finally» -- ловляться цими ж перевірками.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cps_link as cl            # noqa: E402
import cps_restore as crest      # noqa: E402
import custom_region as cr       # noqa: E402
import doc_region as dr          # noqa: E402
import test_cps_restore as tcr   # noqa: E402
import test_r73 as t73           # noqa: E402

FAILS = []
C0, C5, C61 = bytes([0]), bytes([5]), bytes([6, 1])


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def quiet(*_a, **_k):
    pass


A = [(4, b"\x04" * 64), (5, b"\x05" * 64), (9, b"\x09" * 8)]
B = [(t, bytes(x ^ 0x55 for x in pl)) for t, pl in A]


class Radio(tcr.FakeRadioX):
    """FakeRadioX, що пам'ятає порядок УСІХ C- і X-команд (щоб довести «C 0 раніше першого X»)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.seq = []

    def write(self, data):
        d = bytes(data)
        if d[:1] in (b"C", b"X"):
            self.seq.append(d[:1] + d[1:3] if d[:1] == b"C" else b"X")
        return super().write(data)


def radio(blocks=A):
    r = t73.radio_with_region(t73.make_region(blocks))
    rr = Radio(r.spi)
    return rr


def order_ok(r):
    """'C' 0 -- до першого X; після останнього X -- лише C."""
    xs = [i for i, s in enumerate(r.seq) if s == b"X"]
    if not xs:
        return False
    first_c0 = next((i for i, s in enumerate(r.seq) if s[:2] == b"C\x00"), None)
    return first_c0 is not None and first_c0 < xs[0]


def plan_for(r, per_block=False):
    cur = t73.make_region(A)
    plan = cr.plan_restore(t73.make_region(B), cur, selected={4, 5, 9})
    if per_block:
        plan.cur_data = None
    return plan


def test_a1_a2():
    for per_block in (False, True):
        tag = "А2" if per_block else "А1"
        r = radio()
        link = cl.CpsLink(r)
        res = cr.apply_plan(link, plan_for(r, per_block), log=quiet)
        check(not res["failed"] and len(res["written"]) == 3, "%s: записано 3 блоки: %r" % (tag, res["failed"]))
        check(r.c_calls[:1] == [C0] and r.c_calls[-1:] == [C5] and r.c_calls.count(C0) == 1, "%s: C 0 ... C 5: %r" % (tag, r.c_calls))
        check(order_ok(r), "%s: C 0 раніше першої X-команди: %r" % (tag, r.seq[:4]))
        check(not crest.screen_is_open(link), "%s: після apply_plan екран позначено закритим" % tag)
    # нічого писати -> жодної C
    r = radio()
    plan = cr.plan_restore(t73.make_region(A), t73.make_region(A), selected={4, 5, 9})
    cr.apply_plan(cl.CpsLink(r), plan, log=quiet)
    check(r.c_calls == [] and r.x_total == 0, "А1: нічого писати -- жодної C/X: %r" % r.c_calls)


def test_a3():
    tmp = tempfile.mkdtemp(prefix="r107_")
    src = os.path.join(tmp, "b.zip")
    import zipfile
    import json
    reg = t73.make_region(B)
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("customdata.bin", reg)
        z.writestr("manifest.json", json.dumps({"parts": {cr.PART_KEY: {"file": "customdata.bin", "sha256": cr.sha256(reg), "length": len(reg),
                                                                       "start": cr.REGION_RAW_START}}}))
    r = radio()
    out = cr.restore_region(cl.CpsLink(r), src, lambda *_: True, selected={4, 5, 9}, log=quiet, safety_dir=tmp)
    check(out.get("result") and not out["result"]["failed"], "А3: restore_region записав: %r" % out.get("text"))
    check(r.c_calls == [C0, C61], "А3: restore_region -- C 0, C 6 1 (без C 5): %r" % r.c_calls)
    check(order_ok(r), "А3: C 0 раніше першої X")
    r = radio()
    out = cr.restore_region(cl.CpsLink(r), src, lambda *_: False, selected={4, 5, 9}, log=quiet, safety_dir=tmp)
    check(out.get("cancelled") and r.c_calls == [] and r.x_total == 0, "А8: restore_region «Скасувати» -- жодної C/X: %r" % r.c_calls)
    r = radio()
    blocks = cr.parse_region(t73.make_region(B)).blocks
    out = cr.apply_settings(cl.CpsLink(r), blocks, {4, 5, 9}, log=quiet)
    check(out.get("result") and not out["result"]["failed"], "А3: apply_settings записав")
    check(r.c_calls == [C0, C61], "А3: apply_settings -- C 0, C 6 1 (без C 5): %r" % r.c_calls)
    r = radio()
    out = cr.apply_settings(cl.CpsLink(r), blocks, {4, 5, 9}, log=quiet, post_reset=False)
    check(r.c_calls == [C0, C5], "А3: apply_settings без перезавантаження -- C 0, C 5: %r" % r.c_calls)
    r = radio()
    out = cr.apply_settings(cl.CpsLink(r), blocks, {4, 5, 9}, confirm=lambda *_: False, log=quiet)
    check(out.get("cancelled") and r.c_calls == [] and r.x_total == 0, "А8: apply_settings «Скасувати» -- жодної C/X: %r" % r.c_calls)


def test_a4():
    tmp = tempfile.mkdtemp(prefix="r107_")
    r = radio()
    cur = t73.make_region(A)
    plan = plan_for(r)
    out = dr.write_region(cl.CpsLink(r), plan, cur, out_dir=tmp, log=quiet, post_reset=False)
    check(not out["failed"] and out["regionMatchesExpected"], "А4: write_region записав і звірив")
    check(r.c_calls == [C0, C5], "А4: write_region без перезавантаження -- C 0, C 5: %r" % r.c_calls)
    r = radio()
    out = dr.write_region(cl.CpsLink(r), plan_for(r), cur, out_dir=tmp, log=quiet, post_reset=True)
    check(r.c_calls == [C0, C61], "А4: write_region з перезавантаженням -- C 0, C 6 1: %r" % r.c_calls)


def test_a5():
    import test_r75 as t75
    import rctl_config as rctl
    import roam_cfg as rc
    tmp = tempfile.mkdtemp(prefix="r107_")
    # лише налаштування
    r = t75.new_radio()
    r = Radio(r.spi)
    import cps_ui.document as D
    doc = D.from_radio(cl.CpsLink(r))
    t75.rctl_edit(doc, rctl.ALLOW_CHECK | rctl.ALLOW_REVIVE)
    out = t75.write(r, doc, t75.Conf(), tmp)
    check(out.get("regionWritten"), "А5: налаштування записано")
    check(r.c_calls == [C0, C61], "А5: лише налаштування -- C 0, C 6 1: %r" % r.c_calls)
    check(order_ok(r), "А5: C 0 раніше першої X")
    # кодплаг + налаштування
    r = Radio(t75.new_radio().spi)
    doc = D.from_radio(cl.CpsLink(r))
    doc.edit_contacts([{"op": "add", "name": "Львів", "id": 2551, "type": 0}])
    t75.rctl_edit(doc, rctl.ALLOW_MONITOR)
    sc = doc.scratch_region()
    sc.write_block(None, 15, rc.build_payload(True, 2))
    doc.apply_region(sc, {15: "Роумінг"})
    out = t75.write(r, doc, t75.Conf(), tmp)
    check(r.c_calls.count(C0) == 1 and r.c_calls[-1:] == [C61] and C5 not in r.c_calls,
          "А5/А6: кодплаг + налаштування -- одне C 0 (не вдруге), C 6 1 останньою, без C 5: %r" % r.c_calls)
    check(order_ok(r), "А5: C 0 раніше першої X")
    # «Скасувати»
    r = Radio(t75.new_radio().spi)
    doc = D.from_radio(cl.CpsLink(r))
    t75.rctl_edit(doc, rctl.ALLOW_MONITOR)
    out = t75.write(r, doc, t75.Conf(answer=False), tmp)
    check(out.get("cancelled") and r.c_calls == [] and r.x_total == 0, "А8: write_document «Скасувати» -- жодної C/X: %r" % r.c_calls)


def test_a6_nested():
    r = radio()
    link = cl.CpsLink(r)
    crest.screen_open(link)                  # як restore_codeplug(post_reset=False)
    crest.screen_open(link)
    check(r.c_calls == [C0], "А6: повторне screen_open не шле C 0 вдруге: %r" % r.c_calls)
    with crest.cps_screen(link, open_now=False):
        cr.apply_plan(link, plan_for(r), log=quiet)
        check(r.c_calls == [C0], "А6: вкладений apply_plan -- ні C 0, ні C 5: %r" % r.c_calls)
        crest._send_c(link, 6, 1)
    check(r.c_calls == [C0, C61], "А6: після C 6 1 зовнішній блок C 5 не шле: %r" % r.c_calls)


class Boom(Exception):
    pass


def test_a7_failures():
    # виняток посеред запису
    r = radio()
    link = cl.CpsLink(r)
    import flash_guard as fg
    real = fg.write_group

    def bad(*a, **k):
        raise Boom("порт замовк")
    import custom_data as cd
    real_read = cd._read_region
    calls = {"n": 0}

    def read_then_die(ser, off, ln):
        calls["n"] += 1
        if calls["n"] > 1:
            raise Boom("порт замовк при читанні")
        return real_read(ser, off, ln)
    cd._read_region = read_then_die
    try:
        try:
            cr.apply_plan(link, plan_for(r), log=quiet)
            check(False, "А7: виняток мав пройти назовні")
        except Boom:
            pass
    finally:
        cd._read_region = real_read
    check(r.c_calls == [C0, C5], "А7: виняток -> C 5 у finally: %r" % r.c_calls)
    check(not crest.screen_is_open(link), "А7: після винятку екран позначено закритим")
    # збій запису (без винятку) у restore-подібному шляху без перезавантаження
    r = radio()
    fg.write_group = bad
    try:
        out = cr.apply_settings(cl.CpsLink(r), cr.parse_region(t73.make_region(B)).blocks, {4, 5, 9}, log=quiet)
    finally:
        fg.write_group = real
    check(out["result"]["failed"] and not out["result"]["written"], "А7: збій запису повернуто як failed")
    check(r.c_calls == [C0, C5], "А7: збій без записаних блоків -> перезавантаження нема, C 5: %r" % r.c_calls)


def test_a9_mutants():
    """Мутанти: перевірки А1 мають їх ловити."""
    global FAILS
    saved = FAILS
    # 1) без 'C' 0
    FAILS = []
    real_open = crest.screen_open
    crest.screen_open = lambda link: crest._mark_screen(link, True)
    try:
        test_a1_a2()
    finally:
        crest.screen_open = real_open
    caught1 = bool(FAILS)
    # 2) без 'C' 5 у finally
    FAILS = []
    real_exit = crest.cps_screen.__exit__

    def no_close(self, *exc):
        self.link._cps_screen_depth = getattr(self.link, "_cps_screen_depth", 1) - 1
        return False
    crest.cps_screen.__exit__ = no_close
    try:
        test_a7_failures()
    finally:
        crest.cps_screen.__exit__ = real_exit
    caught2 = bool(FAILS)
    FAILS = saved
    check(caught1, "А9: мутант «без C 0» не спіймано")
    check(caught2, "А9: мутант «без C 5 у finally» не спіймано")


def main():
    print_ = print
    import builtins
    tests = [test_a1_a2, test_a3, test_a4, test_a5, test_a6_nested, test_a7_failures]
    for t in tests:
        t()
    # мутанти друкують свої ПРОВАЛ -- глушимо їх вивід
    builtins.print = lambda *a, **k: None
    try:
        test_a9_mutants()
    finally:
        builtins.print = print_
    for m in FAILS:
        if m.startswith("А9"):
            print("ПРОВАЛ:", m)
    if FAILS:
        print("test_r107cps: ПРОВАЛІВ: %d" % len(FAILS))
        sys.exit(1)
    print("test_r107cps: усе гаразд (екран CPS навколо запису custom-data, вкладення, винятки, скасування, 2 мутанти)")


if __name__ == "__main__":
    main()
