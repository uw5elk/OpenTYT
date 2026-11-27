#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_r100cps.py -- R100-CPS / R102 / R110: розділ «Тон-відгук» (custom-data блок 19, v4 з порогом сигналу в десятих частках секунди) у CPS.

Без Tk:
  К1  межі й типові з tone_reply.h: tone_reply_cfg бере їх із заголовка; дзеркало MIRROR (для .exe) == заголовок, усі ключі
  К2  розбір блока Python == справжній toneReplyCfgParse (tone_reply.c на хості): v4, v3 (поріг ×10), v2 (поріг типовий), v1 з міграцією (вгору), невідомі версії, сміття, межі --
      тисячі байтових комбінацій; збирання Python == toneReplyCfgBuild
  К3  ввід: поза межами / частота не кратна 50 / не число -- помилка; межі включно -- можна
  К4  документ: тип 19 у DOC_TYPES і DOC_TITLES, не в NEVER_TYPES; правка через RegionStore; v1 у документі -> показ мігрований, запис v2
  К5  бекап/знімок/файл налаштувань/відновлення: тип 19 -- налаштування (kind setting), розбирається в області, проходить файл налаштувань туди
      й назад, типово відновлюється (plan_restore пише його)
  К6  попередження: увімкнено (передаватиме сама + НЕМАЄ захисту від зациклення); + поріг 0; + тривалість > 10 с; вимкнено -- без попереджень
  К7  мутанти: дзеркало розійшлось із заголовком, міграція вниз замість угору, 19 поза DOC_TYPES, без перевірки меж -- ловляться
З Tk (xvfb):
  Т1  розділ «Тон-відгук» у групі «Дані» після «RCTL»; без документа кнопки вимкнені
  Т2  форма = блок документа; «Застосувати» змінює рівно блок 19; погані значення -- вікно помилки й документ без змін; v1 -- підпис і запис v2;
      блока нема -- типові; попередження оновлюються
  Т3  верстка: сценарії шрифтів × 100/125/150 % -- без обрізання, з документом і без
Запуск: xvfb-run -a python3 tools/test_r100cps.py"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FW = os.path.dirname(HERE)
APP = os.path.join(FW, "application")
FAILS = []
PASSED = [0]
QUIET = [False]


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        if not QUIET[0]:
            print("ПРОВАЛ:", msg)
    else:
        PASSED[0] += 1


def load_module(name, path, src=None):
    """Модуль із (можливо, зміненого) тексту, з __file__ справжнього файла (шляхи до заголовка лишаються ті самі)."""
    m = types.ModuleType(name)
    m.__file__ = path
    exec(compile(src if src is not None else open(path, encoding="utf-8").read(), path, "exec"), m.__dict__)
    return m


# ---------------------------------------------------------------------------------------------------------------------------------
#  Хостовий розбір/збирання з tone_reply.c
# ---------------------------------------------------------------------------------------------------------------------------------

HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include "functions/tone_reply.h"
int main(void)
{
	unsigned b[8];
	while (scanf("%x %x %x %x %x %x %x %x", &b[0], &b[1], &b[2], &b[3], &b[4], &b[5], &b[6], &b[7]) == 8)
	{
		toneReplyOnFlash_t raw; uint8_t *p = (uint8_t *)&raw; toneReplyCfg_t c; bool en = false;
		for (int i = 0; i < 8; i++) p[i] = (uint8_t)b[i];
		int v = toneReplyCfgParse(&raw, &c, &en);
		toneReplyOnFlash_t o; toneReplyCfgBuild(&o, &c, en); const uint8_t *q = (const uint8_t *)&o;
		printf("%d %d %u %u %u %u ", v, (int)en, c.freqHz, c.durS, c.delayS, c.threshDs);
		for (int i = 0; i < 8; i++) printf("%02x", q[i]);
		printf("\n");
	}
	return 0;
}
'''


def payload_grid():
    out = []
    freqs = [0, 1, 299, 300, 324, 325, 1000, 1750, 2999, 3000, 3001, 65535]
    for ver in (0, 1, 2, 3, 4, 5, 0xFF):
        for d in range(256):
            for k, f in enumerate(freqs):
                dl = (d * 7 + k * 31) % 256
                fl = (d + k) % 4
                th = (d + 3 * k) % 61 if d % 17 else (d * 5 + k) % 256    # R110: 0..60 (межі v4 0..50, v3 0..5 с) і зрідка довільний байт
                out.append(bytes([ver, d, dl, fl, f & 0xFF, f >> 8, th, (d + k) % 3]))
    return out


def c_reference(payloads):
    if not shutil.which("gcc"):
        return None, "gcc нема"
    d = tempfile.mkdtemp(prefix="r100cps_")
    try:
        hp = os.path.join(d, "h.c")
        open(hp, "w").write(HARNESS)
        exe = os.path.join(d, "h")
        r = subprocess.run(["gcc", "-std=gnu11", "-Wall", "-DTONE_REPLY_HOST_TEST", "-I" + os.path.join(APP, "include"), "-o", exe, hp,
                            os.path.join(APP, "source", "functions", "tone_reply.c")], capture_output=True, text=True)
        if r.returncode != 0:
            return None, r.stderr[-1500:]
        inp = "\n".join(" ".join("%x" % x for x in p) for p in payloads) + "\n"
        o = subprocess.run([exe], input=inp, capture_output=True, text=True, timeout=120).stdout.splitlines()
        return o, ""
    finally:
        shutil.rmtree(d, ignore_errors=True)


def py_line(trc, p):
    st = trc.parse_payload(p)
    return "%d %d %d %d %d %d %s" % (st["version"], int(st["enabled"]), st["freq"], st["dur"], st["delay"], st["thresh_ds"],
                                     trc.build_payload(st["enabled"], st["freq"], st["dur"], st["delay"], st["thresh_ds"]).hex())


def core(trc, dr, ref, payloads, tag=""):
    """К1..К6 для модулів trc (tone_reply_cfg) і dr (doc_region). Повертає True, якщо все гаразд."""
    import custom_region as cr
    ok = [True]

    def want(c, m):
        ok[0] = ok[0] and bool(c)
        check(c, m + tag)
    # К1
    hdr = trc.parse_header()
    want(hdr is not None and trc.SOURCE == trc.HEADER, "К1: межі взято з tone_reply.h")
    want(hdr is not None and all(hdr.get(k) == v for k, v in trc.MIRROR.items()),
         "К1: дзеркало для .exe == tone_reply.h: %r" % {k: (v, (hdr or {}).get(k)) for k, v in trc.MIRROR.items() if (hdr or {}).get(k) != v})
    want((trc.FREQ_MIN, trc.FREQ_MAX, trc.FREQ_STEP, trc.FREQ_DEF, trc.DUR_MIN, trc.DUR_MAX, trc.DUR_DEF, trc.DELAY_MIN, trc.DELAY_MAX, trc.DELAY_DEF,
          trc.THRESH_MIN, trc.THRESH_MAX, trc.THRESH_DEF, trc.THRESH_STEP) == (300, 3000, 50, 1000, 1, 60, 10, 0, 10, 2, 0, 50, 10, 1),
         "К1: 300..3000/50 Гц, 1..60 с, 0..10 с, поріг 0..50 десятих с (крок 1 = 0,1 с), типові 1000/10/2/10")
    want(not hasattr(trc, "GUARD_S") and not hasattr(trc, "THRESH_MS") and "GUARD" not in "".join(trc.K), "К1: сторожа в константах CPS нема")
    # К2
    if ref is not None:
        mism = [(p.hex(), r, py_line(trc, p)) for p, r in zip(payloads, ref) if py_line(trc, p) != r]
        want(len(ref) == len(payloads) and not mism, "К2: розбір/збирання Python == tone_reply.c на %d блоках; розбіжностей %d, перші: %r" % (len(payloads), len(mism), mism[:3]))
    v1 = trc.parse_payload(bytes([1, 5, 25, 1, 0xD6, 0x06, 0, 0]))
    want(v1 == {"version": 1, "enabled": False, "freq": 1750, "dur": 1, "delay": 3, "thresh_ds": 10}, "К2: v1 0,5 с / 2,5 с -> 1 с / 3 с, вимкнено (навіть з бітом 0), поріг типовий: %r" % v1)
    v2 = trc.parse_payload(bytes([2, 20, 4, 1, 0xB8, 0x0B, 0, 0]))
    want(v2 == {"version": 2, "enabled": True, "freq": 3000, "dur": 20, "delay": 4, "thresh_ds": 10}, "К2: v2 -> «увімкнено» зберігається, поріг типовий 1,0 с: %r" % v2)
    v2b = trc.parse_payload(bytes([2, 20, 4, 1, 0xB8, 0x0B, 4, 0]))
    want(v2b["thresh_ds"] == 10, "К2: у v2 байт [6] ігнорується (поріг типовий): %r" % v2b)
    v3 = trc.parse_payload(bytes([3, 20, 4, 1, 0xB8, 0x0B, 4, 0]))
    want(v3 == {"version": 3, "enabled": True, "freq": 3000, "dur": 20, "delay": 4, "thresh_ds": 40}, "К2: v3 (R102): поріг 4 с -> 40 десятих, решта повністю: %r" % v3)
    v3c = trc.parse_payload(bytes([3, 20, 4, 1, 0xB8, 0x0B, 200, 0]))
    want(v3c["thresh_ds"] == 50, "К2: v3 з порогом поза межами -- 5,0 с (50): %r" % v3c)
    v4 = trc.parse_payload(bytes([4, 20, 4, 1, 0xB8, 0x0B, 25, 0]))
    want(v4 == {"version": 4, "enabled": True, "freq": 3000, "dur": 20, "delay": 4, "thresh_ds": 25}, "К2: v4 (R110): поріг 2,5 с як є: %r" % v4)
    want(trc.parse_payload(bytes([4, 20, 4, 1, 0xB8, 0x0B, 51, 0]))["thresh_ds"] == 50, "К2: v4 з порогом 51 -- обрізання до 50")
    want(trc.parse_payload(None)["version"] == 0 and trc.parse_payload(b"\x02\x0a") ["version"] == 0, "К2: блока нема / короткий -- типові")
    want(trc.parse_payload(None)["thresh_ds"] == 10 and trc.parse_payload(bytes([9] * 8))["version"] == 0, "К2: сміття -- типові, поріг 1,0 с")
    # К3
    bad = [(3001, 10, 2, 1), (299, 10, 2, 1), (1025, 10, 2, 1), (1000, 0, 2, 1), (1000, 61, 2, 1), (1000, 10, 11, 1), (1000, 10, -1, 1), (True, 10, 2, 1), ("1000", 10, 2, 1),
           (1000, 10, 2, 51), (1000, 10, 2, -1), (1000, 10, 2, True), (1000, 10, 2, "1"), (1000, 10, 2, 1.5)]
    errs = 0
    for b in bad:
        try:
            trc.build_payload(False, *b)
        except trc.ToneCfgError:
            errs += 1
    want(errs == len(bad), "К3: значення поза межами -- помилка (%d з %d)" % (errs, len(bad)))
    try:
        edge = [trc.build_payload(True, 300, 1, 0, 0), trc.build_payload(False, 3000, 60, 10, 50)]
    except trc.ToneCfgError:
        edge = []
    want(len(edge) == 2 and edge[1].hex() == "043c0a00b80b3200" and edge[0].hex() == "04010001 2c010000".replace(" ", ""), "К3: межі включно -- можна: %r" % [e.hex() for e in edge])
    # К4
    want(19 in dr.DOC_TYPES and dr.DOC_TITLES.get(19) == "Тон-відгук" and 19 not in dr.NEVER_TYPES and dr.TYPE_TONE_REPLY_CFG == 19,
         "К4: тип 19 у документі з назвою, не в NEVER_TYPES")
    reg = bytearray(b"\xff" * cr.REGION_LEN)
    reg[0:12] = cr.MAGIC + b"\x00" * 4
    store = dr.RegionStore(bytes(reg))
    store.write_block(None, 19, bytes([1, 5, 25, 0, 0xE8, 0x03, 0, 0]))
    st, raw = trc.read_state(None, store=store)
    want(st["version"] == 1 and st["dur"] == 1 and st["delay"] == 3 and st["thresh_ds"] == 10 and raw[0] == 1, "К4: v1 у документі читається мігрованим: %r" % st)
    try:
        trc.write_state(None, st["enabled"], st["freq"], st["dur"], st["delay"], st["thresh_ds"], store=store)
        back = store.read_block(None, 19, 8)
    except Exception as e:  # noqa: BLE001
        back = repr(e)
    want(back == bytes([4, 1, 3, 0, 0xE8, 0x03, 10, 0]), "К4: v1 записується як v4 (та сама довжина 8 Б, поріг 1,0 с): %r" % (back,))
    store.write_block(None, 19, bytes([2, 20, 4, 1, 0xE8, 0x03, 0, 0]))
    st2, raw2 = trc.read_state(None, store=store)
    try:
        trc.write_state(None, st2["enabled"], st2["freq"], st2["dur"], st2["delay"], st2["thresh_ds"], store=store)
        back2 = store.read_block(None, 19, 8)
    except Exception as e:  # noqa: BLE001
        back2 = repr(e)
    want(st2["version"] == 2 and back2 == bytes([4, 20, 4, 1, 0xE8, 0x03, 10, 0]), "К4: v2 (R100) -> v4, поріг 1,0 с, «увімкнено» і решта збережені: %r" % (back2,))
    try:
        trc.write_state(None, True, 1000, 10, 2, 50, store=store)
        back3 = store.read_block(None, 19, 8)
    except Exception as e:  # noqa: BLE001
        back3 = repr(e)
    want(back3 == bytes([4, 10, 2, 1, 0xE8, 0x03, 50, 0]) and trc.read_state(None, store=store)[0]["thresh_ds"] == 50, "К4: v4 з порогом 5,0 с: запис і читання назад: %r" % (back3,))
    # К5
    want(cr.BLOCK_TYPES.get(19, (None,))[0] == "TONE_REPLY_CFG" and cr.BLOCK_TYPES[19][4] == "setting" and "версія 4" in cr.BLOCK_TYPES[19][2],
         "К5: тип 19 -- TONE_REPLY_CFG, налаштування, опис v4")
    parsed = cr.parse_region(store.data())
    by = parsed.by_type()
    want(19 in by and by[19].kind == "setting" and not parsed.problems and cr.default_selected(by[19]), "К5: розбирається в області, типово відновлюється")
    text = cr.settings_to_text(parsed.blocks)
    blocks, _d = cr.settings_from_text(text)
    want(any(b.type == 19 and b.payload == by[19].payload for b in blocks) and "TONE_REPLY_CFG" in text, "К5: проходить файл налаштувань туди й назад")
    cur = bytearray(b"\xff" * cr.REGION_LEN)
    cur[0:12] = cr.MAGIC + b"\x00" * 4
    plan = cr.plan_restore(store.data(), bytes(cur))
    want(any(it.block.type == 19 for it in plan.writes()), "К5: відновлення з бекапу/знімка типово пише блок 19")
    # К6
    w0, w1, w2 = trc.warnings(False, 60, 0), trc.warnings(True, 10, 10), trc.warnings(True, 11, 10)
    w3 = trc.warnings(True, 10, 0)
    want(w0 == [] and len(w1) == 2 and len(w2) == 3 and "11 с" in w2[-1] and len(w3) == 3,
         "К6: попередження: вимкнено -- нема; увімкнено -- 2 (сама передаватиме, НЕМАЄ захисту); +11 с -- 3; +поріг 0 -- 3: %r" % ((w0, w1, w2, w3),))
    want("сплесків шуму" in w3[1] and "НЕМАЄ" in w1[1] and "без кінця" in w1[1] and "лише на одній" in w1[1],
         "К6: текст: поріг 0 -- сплески шуму; зациклення -- НЕМАЄ, без кінця, лише на одній: %r" % ((w3, w1),))
    want(not any("сторож" in x.lower() or "71" in x for x in w1 + w2 + w3), "К6: про сторож/71 с нічого")
    return ok[0]


def run_core():
    import doc_region as dr
    import tone_reply_cfg as trc
    payloads = payload_grid()
    ref, err = c_reference(payloads)
    check(ref is not None, "К2: хостова збірка tone_reply.c: %s" % err)
    core(trc, dr, ref, payloads)

    # К7: мутанти
    trc_path, dr_path = trc.__file__, dr.__file__
    trc_src, dr_src = open(trc_path, encoding="utf-8").read(), open(dr_path, encoding="utf-8").read()

    def mut(name, which, a, b):
        src = trc_src if which == "trc" else dr_src
        s2 = src.replace(a, b, 1)
        if s2 == src:
            check(False, "К7 (%s): шаблон не знайдено" % name)
            return
        n0 = len(FAILS)
        QUIET[0] = True
        try:
            m_trc = load_module("trc_m", trc_path, s2) if which == "trc" else trc
            m_dr = load_module("dr_m", dr_path, s2) if which == "dr" else dr
            good = core(m_trc, m_dr, ref, payloads, " [m]")
        except Exception:  # noqa: BLE001 -- мутант, що падає, теж ловиться
            good = False
        QUIET[0] = False
        del FAILS[n0:]
        check(not good, "К7 (%s): ловиться" % name)
    mut("дзеркало розійшлось", "trc", '"DUR_MAX_S": 60,', '"DUR_MAX_S": 50,')
    mut("міграція вниз", "trc", 'st["dur"] = (payload[1] + 9) // 10', 'st["dur"] = payload[1] // 10')
    mut("19 поза документом", "dr", ", TYPE_VOLUME_LOW_CFG, TYPE_TONE_REPLY_CFG)", ", TYPE_VOLUME_LOW_CFG)")
    mut("без перевірки меж", "trc", "    check_values(freq, dur, delay, thresh_ds)\n    return bytes(", "    return bytes(")
    mut("поріг не пишеться", "trc", "freq & 0xFF, freq >> 8, thresh_ds, 0])", "freq & 0xFF, freq >> 8, 10, 0])")
    mut("поріг v2 береться з байта", "trc", "        if payload[0] == VERSION:\n            st[\"thresh_ds\"] = payload[6]", "        if payload[0] != VERSION_V3:\n            st[\"thresh_ds\"] = payload[6]")
    mut("v3 не множиться на 10", "trc", "else payload[6] * 10", "else payload[6]")
    mut("попередження про зациклення зникло", "trc", "Захисту від зациклення НЕМАЄ", "Захист від зациклення є")


# ---------------------------------------------------------------------------------------------------------------------------------
#  Tk
# ---------------------------------------------------------------------------------------------------------------------------------

def tk_part():
    import layout_probe as lp
    import test_r59_ui as u
    import doc_region as dr_
    import struct as st_
    app = u.new_app()
    dlg = u.Dialogs()
    try:
        app.show("tonereply")
        lp.spin(app, 0.3)
        p = app.get_panel("tonereply")
        keys = list(app._defs)
        check(keys.index("tonereply") == keys.index("rctl") + 1 and p.title == "Тон-відгук" and p.doc_panel, "Т1: «Тон-відгук» у «Даних» після «RCTL», панель документа: %r" % keys)
        check(u.state(p.apply_btn) == "disabled" and u.state(p.reload_btn) == "disabled", "Т1: без документа кнопки вимкнені")
        doc = u.make_doc()
        app.set_document(doc)
        lp.spin(app, 0.3)

        def region_of(blocks):
            reg = bytearray(b"\xff" * 0x10000)
            reg[0:12] = b"OpenGD77" + b"\x00" * 4
            at = 12
            for t_, pl_ in blocks:
                reg[at:at + 8] = st_.pack("<ii", t_, len(pl_))
                reg[at + 8:at + 8 + len(pl_)] = pl_
                at += 8 + len(pl_)
            return bytes(reg)

        def set_region(reg):
            doc.region = dr_.RegionStore(reg)
            doc._region_origin = reg
            doc._region_saved = reg
            p.on_document_changed()
            lp.spin(app, 0.1)

        set_region(region_of([(19, bytes([4, 30, 5, 1, 0xB0, 0x04, 30, 0]))]))
        check(p.v_enabled.get() is True and (p.v_freq.get(), p.v_dur.get(), p.v_delay.get(), p.v_thresh.get()) == ("1200", "30", "5", "3.0") and u.state(p.apply_btn) == "normal",
              "Т2: форма = блок документа (v4, поріг 3,0 с): %r" % ((p.v_enabled.get(), p.v_freq.get(), p.v_dur.get(), p.v_delay.get(), p.v_thresh.get()),))
        t = p.warn_label.cget("text")
        check("увімкнено" in t and "30 с" in t and "НЕМАЄ" in t and "шуму" not in t, "Т2: попередження (увімкнено, 30 с, НЕМАЄ захисту; поріг 3 -- без «шуму»): %r" % t)
        p.v_thresh.set("0")
        p.refresh_warnings()
        t = p.warn_label.cget("text")
        check("сплесків шуму" in t, "Т2: поріг 0 + увімкнено -- попередження про шум: %r" % t)
        p.v_thresh.set("1,0")
        p.v_enabled.set(False)
        p.v_freq.set("2450")
        p.v_dur.set("7")
        p.v_delay.set("0")
        p.refresh_warnings()
        check(p.warn_label.cget("text") == "", "Т2: вимкнено -- без попереджень")
        p._on_apply()
        check(doc.region.read_block(None, 19, 8) == bytes([4, 7, 0, 0, 0x92, 0x09, 10, 0]), "Т2: блок 19 у документі оновлено (v4, поріг «1,0» з комою): %r" % doc.region.read_block(None, 19, 8))
        check(doc.region_changed_types() == [19], "Т2: до запису піде лише блок 19: %r" % doc.region_changed_types())
        for bad in (("3050", "7", "0", "1"), ("2425", "7", "0", "1"), ("2450", "61", "0", "1"), ("2450", "0", "0", "1"), ("2450", "7", "11", "1"), ("abc", "7", "0", "1"),
                    ("2450", "", "0", "1"), ("2450", "7", "0", "5,1"), ("2450", "7", "0", "6"), ("2450", "7", "0", "-0,1"), ("2450", "7", "0", ""), ("2450", "7", "0", "x"), ("2450", "7", "0", "1,2,3")):
            p.v_freq.set(bad[0])
            p.v_dur.set(bad[1])
            p.v_delay.set(bad[2])
            p.v_thresh.set(bad[3])
            n0 = len(dlg.errors)
            p._on_apply()
            check(len(dlg.errors) == n0 + 1 and doc.region.read_block(None, 19, 8) == bytes([4, 7, 0, 0, 0x92, 0x09, 10, 0]), "Т2: %r -- вікно помилки, документ без змін" % (bad,))
        p.v_freq.set("2450")
        p.v_dur.set("7")
        p.v_delay.set("0")
        p.v_thresh.set("5")
        p._on_apply()
        check(doc.region.read_block(None, 19, 8) == bytes([4, 7, 0, 0, 0x92, 0x09, 50, 0]), "Т2: поріг 5 с записано (50): %r" % doc.region.read_block(None, 19, 8))
        for txt, want_ds in (("0.25", 3), ("0,04", 0), ("2,3", 23), (" 0.1 ", 1)):
            p.v_thresh.set(txt)
            p._on_apply()
            check(doc.region.read_block(None, 19, 8)[6] == want_ds, "Т2: поріг «%s» -> %d десятих (округлення до 0,1, кома/крапка): %r" % (txt, want_ds, doc.region.read_block(None, 19, 8)))
        set_region(region_of([(19, bytes([3, 30, 5, 1, 0xB0, 0x04, 3, 0]))]))
        check(p.v_thresh.get() == "3.0" and "формат R102" in p.state_label.cget("text"), "Т2: v3 (R102) показано як 3,0 с, з поясненням: %r" % ((p.v_thresh.get(), p.state_label.cget("text")),))
        p._on_apply()
        check(doc.region.read_block(None, 19, 8) == bytes([4, 30, 5, 1, 0xB0, 0x04, 30, 0]), "Т2: v3 -> «Застосувати» записує v4 (3 с -> 30): %r" % doc.region.read_block(None, 19, 8))
        set_region(region_of([(19, bytes([2, 30, 5, 1, 0xB0, 0x04, 0, 0]))]))
        check((p.v_dur.get(), p.v_delay.get(), p.v_freq.get(), p.v_enabled.get(), p.v_thresh.get()) == ("30", "5", "1200", True, "1.0") and "формат R100" in p.state_label.cget("text"),
              "Т2: v2 (R100) показано з типовим порогом 1,0 с, з поясненням: %r" % p.state_label.cget("text"))
        p._on_apply()
        check(doc.region.read_block(None, 19, 8) == bytes([4, 30, 5, 1, 0xB0, 0x04, 10, 0]), "Т2: v2 -> «Застосувати» записує v4 (поріг 1,0 с, «увімкнено» збережено): %r" % doc.region.read_block(None, 19, 8))
        set_region(region_of([(19, bytes([1, 5, 25, 0, 0xD6, 0x06, 0, 0]))]))
        check((p.v_dur.get(), p.v_delay.get(), p.v_freq.get(), p.v_enabled.get(), p.v_thresh.get()) == ("1", "3", "1750", False, "1.0") and "старий формат" in p.state_label.cget("text"),
              "Т2: v1 показано мігрованим, з поясненням: %r" % p.state_label.cget("text"))
        p._on_apply()
        check(doc.region.read_block(None, 19, 8) == bytes([4, 1, 3, 0, 0xD6, 0x06, 10, 0]), "Т2: v1 -> «Застосувати» записує v4: %r" % doc.region.read_block(None, 19, 8))
        set_region(region_of([]))
        check((p.v_enabled.get(), p.v_freq.get(), p.v_dur.get(), p.v_delay.get(), p.v_thresh.get()) == (False, "1000", "10", "2", "1.0") and "немає" in p.state_label.cget("text"),
              "Т2: блока нема -- типові значення: %r" % p.state_label.cget("text"))
        set_region(region_of([(19, b"\xff" * 8)]))
        check("недійсний" in p.state_label.cget("text"), "Т2: сміття названо недійсним")
    finally:
        dlg.restore()
        app.destroy()

    # Т3: верстка
    import font_scenarios as fs
    import test_r50fix as t50
    import tkinter as tk
    root = tk.Tk()
    scs = t50.sc_list(root)
    root.destroy()
    check(len(scs) >= 6 and {pc for _f, pc in scs} == {100, 125, 150}, "Т3: сценарії (>= 6) охоплюють 100/125/150 %%: %r" % (scs,))
    for sc in scs:
        app = u.new_app(sc)
        try:
            doc = u.make_doc()
            res = lp.run_all(app, sizes=((1024, 768),), keys=["tonereply"], doc_states=(None, lambda: doc))
            lines = lp.format_report(res)
            check(not lines, "Т3 [%s]: «Тон-відгук» обрізано в %d місцях:\n  %s" % (fs.label(sc), len(lines), "\n  ".join(l[:230] for l in lines[:10])))
        finally:
            try:
                app.update()
            except Exception:  # noqa: BLE001
                pass
            app.destroy()
    return len(scs)


def main():
    run_core()
    try:
        import tkinter  # noqa: F401
        have = bool(os.environ.get("DISPLAY"))
    except ImportError:
        have = False
    nsc = 0
    if have:
        try:
            nsc = tk_part()
        except Exception as e:  # noqa: BLE001
            import traceback
            FAILS.append("Tk: виняток %s: %s" % (type(e).__name__, e))
            traceback.print_exc()
    else:
        print("test_r100cps: нема tkinter/DISPLAY -- Tk-частину ПРОПУЩЕНО (це не «пройдено»)")
    if FAILS:
        print("test_r100cps: %d провалів (пройдено %d)" % (len(FAILS), PASSED[0]))
        return 1
    print("test_r100cps: усе гаразд (%d перевірок%s)." % (PASSED[0], ", Tk: %d сценаріїв верстки" % nsc if have else ", БЕЗ Tk"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
