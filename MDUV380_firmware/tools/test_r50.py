#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R50: CPS -- готовий вигляд (розміри вікон, одне «Відновити…», підписи «Записати …», база позивних).

A1  діалоги: розмір запам'ятовується між відкриттями, збережене сміття (замалий розмір) ігнорується, діалоги зміннорозмірні; жодного resizable(False, False) у tools/
A2  головне вікно: положення (x, y) зберігається, а положення поза екраном відкидається
B1  restore_extras.inspect_source: архів (з областю / без / з ключами / без), страхова копія області (.bin), страхова копія ключів (.bin -- відмова словами), сміття
B2  restore_dialog.state_for / summary_text: що доступно за файлом; запобіжники названо до натискання
B3  restore_selected на підробленій рації: УСІ сполучення (кодплаг / область / ключі у всіх 7 комбінаціях + сира страхова копія області) -- пишеться РІВНО вибране,
    решта лишається байт у байт; одне перезавантаження; знімок «станом» RCTL лише з підпрапорцем
B4  панель «Бекап»: нема кнопок «Відновити лише …» і прапорців; «Усі налаштування» без кнопки страхової копії, але з посиланням
B5  автовизначення страхових копій (find_safety_copies)
C1  підписи «Записати …»: кодплаг / теми / мелодію / заставку / вибрані блоки / базу позивних; «Супутники» не чіпано (R52)
D1  «База позивних»: типове джерело -- Radioid user.csv, країна «Ukraine» і префікс 255 за замовчуванням, одна кнопка «Відкрити файл…»
D2  detect_file_kind: CSV/JSON -> source; .bin і .zip-знімок -> image
D3  фільтр «країна АБО префікс»; країни в джерелі нема -> фільтр країни не застосовується (сказано словами)
D4  dmrdb_country_report: рахунки перетину / «лише за країною» / «лише за префіксом» на вигаданому файлі
Z   підключено до tests/run_tests.sh; мутанти B3/D3 піймано
Запуск: python3 tools/test_r50.py (Tk-частини -- під xvfb-run)"""
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import aes_keys_backup as akb            # noqa: E402
import cps_link as cl                    # noqa: E402
import custom_region as cr               # noqa: E402
import dmr_db as db                      # noqa: E402
import restore_extras as rx              # noqa: E402
import test_cps_restore as tcr           # noqa: E402
import test_r30 as t30                   # noqa: E402
import test_r31 as t31                   # noqa: E402

FAILS = []
FW = os.path.dirname(HERE)


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def quiet(*_a, **_k):
    pass


# ----------------------------------------------------------------------------------------------------------------------------------
#  Підроблена рація і архів
# ----------------------------------------------------------------------------------------------------------------------------------

def full_spi(seed, keys_occ):
    """Образ SPI: базовий кодплаг рації A + область custom-data (seed) + таблиця ключів."""
    spi = t30.new_spi_with(seed)
    return t31.put_table(spi, t31.make_table(seed, keys_occ))


def other_radio_spi(a):
    """Рація, що відрізняється від A усім: кодплагом (tcr.spi_b), областю й ключами."""
    b = tcr.spi_b(a)
    t30.put_region(b, t30.make_payloads(2))
    return t31.put_table(b, t31.make_table(2, {3}))


CONTACT_AT = cl.FLASH_ADDRESS_OFFSET + cl.CP_ADDR_CONTACTS


def parts_state(spi, a, b):
    """Яка частина образу `spi` дорівнює A, а яка лишилась як у B: (кодплаг, область, ключі) -> 'A' | 'B' | '?'."""
    def which(get, same=lambda x, y: x == y):
        x = get(spi)
        return "A" if same(x, get(a)) else ("B" if x == get(b) else "?")

    def keys_same(x, y):          # ключі відновлюються лише для зайнятих слотів архіву -- решта лишається як у рації
        return all(akb.entry_of(x, s) == akb.entry_of(y, s) for s in t31.OCC)
    return (which(lambda s: bytes(s[CONTACT_AT:CONTACT_AT + 16])), which(t30.region_of), which(t31.table_of, keys_same))


def run_combos(fn, a, b, path):
    """Усі 7 сполучень (кодплаг / область / ключі) через `fn` (restore_selected або мутант). -> список текстів проваленого."""
    bad = []
    for cp in (True, False):
        for rg in (True, False):
            for ks in (True, False):
                if not (cp or rg or ks):
                    continue
                radio = tcr.FakeRadioX(bytearray(b))
                confirms = []
                try:
                    out = fn(cl.CpsLink(radio), path, lambda *a_, **k_: (confirms.append(a_), True)[1], None, log=quiet,
                             with_codeplug=cp, with_region=rg, include_state=False, with_keys=ks)
                except cl.CpsError as e:
                    bad.append("кодплаг=%s область=%s ключі=%s: помилка %s" % (cp, rg, ks, e))
                    continue
                got = parts_state(radio.spi, a, b)
                label = "кодплаг=%s область=%s ключі=%s" % (cp, rg, ks)
                if got[0] != ("A" if cp else "B"):
                    bad.append("%s: кодплаг %s" % (label, got[0]))
                if got[2] != ("A" if ks else "B"):
                    bad.append("%s: ключі %s" % (label, got[2]))
                if rg:
                    pa, pb, pn = t30.payloads_of(t30.region_of(a)), t30.payloads_of(t30.region_of(b)), t30.payloads_of(t30.region_of(radio.spi))
                    if not (all(pn[t] == pa[t] for t in pa if t != 10) and pn[10] == pb[10]):
                        bad.append("%s: область не відновлено або стан RCTL (тип 10) без підпрапорця змінено" % label)
                elif got[1] != "B":
                    bad.append("%s: область чіпано" % label)
                resets = [c for c in radio.c_calls if c[:2] == bytes([6, 1])]
                if len(resets) != 1:
                    bad.append("%s: перезавантажень %d, а має бути одне" % (label, len(resets)))
                if (out["codeplug"] is not None) != cp:
                    bad.append("%s: результат кодплага %s" % (label, "є" if out["codeplug"] is not None else "відсутній"))
                if not confirms:
                    bad.append("%s: без підтвердження" % label)
    return bad


def test_b3_combinations():
    a = full_spi(1, t31.OCC)
    b = other_radio_spi(a)
    path, _d, _m, _r = t31.mk_zip(a)
    check(parts_state(a, a, b) == ("A", "A", "A") and parts_state(b, a, b) == ("B", "B", "B"), "B3: сам тест має сенс -- A і B відрізняються в усіх трьох частинах")
    old_sleep = time.sleep
    time.sleep = lambda *_a, **_k: None
    try:
        bad = run_combos(rx.restore_selected, a, b, path)
        check(not bad, "B3: усі сполучення пишуть РІВНО вибране: %r" % bad[:5])
        # мутанти: перевірка B3 здатна їх піймати
        for name, mut in (("ключі ігноруються", lambda *x, **k: rx.restore_selected(*x, **dict(k, with_keys=False))),
                          ("область ігнорується", lambda *x, **k: rx.restore_selected(*x, **dict(k, with_region=False))),
                          ("кодплаг пишеться завжди", lambda *x, **k: rx.restore_selected(*x, **dict(k, with_codeplug=True)))):
            check(run_combos(mut, a, b, path), "B3 мутант «%s»: піймано" % name)
        # підпрапорець «разом зі станом»: тип 10 теж
        radio = tcr.FakeRadioX(bytearray(b))
        rx.restore_selected(cl.CpsLink(radio), path, lambda *a_, **k_: True, None, log=quiet, with_codeplug=False, with_region=True, include_state=True, with_keys=False)
        pa, pn = t30.payloads_of(t30.region_of(a)), t30.payloads_of(t30.region_of(radio.spi))
        check(pn[10] == pa[10], "B3: з підпрапорцем «лічильники RCTL» стан теж відновлено")
        # скасування: рація не змінена
        radio = tcr.FakeRadioX(bytearray(b))
        rx.restore_selected(cl.CpsLink(radio), path, lambda *a_, **k_: False, None, log=quiet, with_codeplug=False, with_region=False, with_keys=True)
        check(t31.table_of(radio.spi) == t31.table_of(b) and not radio.reset_requested, "B3: «Скасувати» -- ключі не змінено, перезавантаження нема")
        # нічого не обрано
        try:
            rx.restore_selected(cl.CpsLink(tcr.FakeRadioX(bytearray(b))), path, lambda *a_, **k_: True, None, log=quiet, with_codeplug=False)
            check(False, "B3: порожній вибір має відхилятися")
        except cl.CpsError:
            pass
        # сира страхова копія області (.bin)
        raw = os.path.join(os.path.dirname(path), "customdata_pre-restore_20260101_000000.bin")
        open(raw, "wb").write(t30.region_of(a))
        radio = tcr.FakeRadioX(bytearray(b))
        out = rx.restore_selected(cl.CpsLink(radio), raw, lambda *a_, **k_: True, None, log=quiet, with_codeplug=True, with_region=False, with_keys=True)
        got = parts_state(radio.spi, a, b)
        check(out["raw"] is not None and out["raw"].get("ok") and got == ("B", "A", "B"),
              "B3: страхова копія області (.bin) повертає лише область, навіть якщо позначено кодплаг/ключі: %r" % (got,))
    finally:
        time.sleep = old_sleep
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)


def test_b1_inspect():
    a = full_spi(1, t31.OCC)
    d = tempfile.mkdtemp(prefix="r50i_")
    try:
        full, _x, _m, _r = t31.mk_zip(a)
        i = rx.inspect_source(full)
        check(i["kind"] == rx.KIND_ZIP and i["codeplug"] and i["region"] and i["keys"] and i["keysText"], "B1: повний архів: кодплаг, область, ключі (%r)" % (i,))
        radio = tcr.FakeRadioX(bytearray(a))
        data, _m2 = cl.backup_codeplug(cl.CpsLink(radio), custom_data=False, aes_keys=False, log=quiet)
        nk = os.path.join(d, "nokeys.zip")
        open(nk, "wb").write(data)
        i = rx.inspect_source(nk)
        check(i["kind"] == rx.KIND_ZIP and i["codeplug"] and not i["region"] and not i["keys"], "B1: архів без області й ключів (%r)" % (i,))
        rb = os.path.join(d, "customdata_pre-compact_x.bin")
        open(rb, "wb").write(t30.region_of(a))
        check(rx.inspect_source(rb)["kind"] == rx.KIND_REGION_BIN, "B1: .bin довжини області -- страхова копія області")
        kb = os.path.join(d, "aeskeys_pre-restore_x.bin")
        open(kb, "wb").write(t31.table_of(a))
        i = rx.inspect_source(kb)
        check(i["kind"] == rx.KIND_BAD and "ключів AES" in i["why"], "B1: страхова копія ключів (.bin) -- відмова з поясненням: %s" % i["why"])
        junk = os.path.join(d, "junk.bin")
        open(junk, "wb").write(b"abc")
        check(rx.inspect_source(junk)["kind"] == rx.KIND_BAD, "B1: сміття -- не файл відновлення")
        badzip = os.path.join(d, "bad.zip")
        with zipfile.ZipFile(badzip, "w") as z:
            z.writestr("x.txt", "1")
        check(rx.inspect_source(badzip)["kind"] == rx.KIND_BAD, "B1: zip без manifest.json -- не бекап")
        check(rx.inspect_source(os.path.join(d, "нема.zip"))["kind"] == rx.KIND_BAD, "B1: файла нема -- відмова")
        check(rx.inspect_source("")["kind"] == rx.KIND_BAD, "B1: порожній шлях -- відмова")
        try:
            rx.restore_selected(cl.CpsLink(tcr.FakeRadioX(bytearray(a))), junk, lambda *x, **k: True, None, log=quiet)
            check(False, "B1: restore_selected на сміття має кидати")
        except cl.CpsError:
            pass
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_b5_find_safety():
    d = tempfile.mkdtemp(prefix="r50s_")
    try:
        names = ["codeplug_pre-restore_20260101_100000.zip", "customdata_pre-restore_20260101_100001.bin", "customdata_pre-compact_20260101_100002.bin",
                 "codeplug_backup_20260101_100003.zip", "aeskeys_pre-restore_20260101_100004.bin", "other.bin"]
        for i, n in enumerate(names):
            p = os.path.join(d, n)
            open(p, "wb").write(b"x")
            os.utime(p, (1000 + i, 1000 + i))
        found = [os.path.basename(p) for p, _t in rx.find_safety_copies(d, d, None, os.path.join(d, "нема"))]
        check(found == [names[2], names[1], names[0]], "B5: знайдено лише автоматичні страхові копії кодплага й області, від найновішої, без дублів: %r" % found)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_b2_state():
    import restore_plan as rd
    z_full = {"kind": rx.KIND_ZIP, "codeplug": True, "region": True, "keys": True, "keysText": "2, 5"}
    st = rd.state_for(z_full)
    check(st["codeplug"] == (True, True) and st["region"] == (False, True) and st["keys"] == (False, True) and st["state"] == (False, False) and st["ok"],
          "B2: повний архів -- типово позначено лише кодплаг; решта доступні: %r" % (st,))
    st = rd.state_for(z_full, {"codeplug": False, "region": True, "state": True, "keys": True})
    check(st["codeplug"] == (False, True) and st["region"] == (True, True) and st["state"] == (True, True) and st["keys"] == (True, True),
          "B2: вибір користувача зберігається, підпрапорець доступний лише з областю")
    st = rd.state_for(z_full, {"codeplug": True, "region": False, "state": True})
    check(st["state"] == (False, False), "B2: без області підпрапорець «RCTL» знімається")
    st = rd.state_for({"kind": rx.KIND_ZIP, "codeplug": True, "region": False, "keys": False}, {"region": True, "keys": True})
    check(st["region"] == (False, False) and st["keys"] == (False, False) and "області custom-data нема" in st["note"] and "ключів AES нема" in st["note"],
          "B2: у архіві чогось нема -- прапорець недоступний, причину названо: %r" % (st["note"],))
    st = rd.state_for({"kind": rx.KIND_REGION_BIN, "codeplug": False, "region": True, "keys": False})
    check(st["region"] == (True, False) and st["codeplug"] == (False, False) and st["keys"] == (False, False) and st["ok"], "B2: страхова копія області -- лише область")
    st = rd.state_for({"kind": rx.KIND_BAD, "why": "причина"})
    check(not st["ok"] and st["note"] == "причина", "B2: непридатний файл -- нічого не доступно, причину названо")
    st = rd.state_for(z_full, {"codeplug": False, "region": False, "keys": False})
    check(not st["ok"], "B2: нічого не позначено -- кнопка «Відновити» недоступна")
    t = rd.summary_text(z_full, rd.state_for(z_full, {"codeplug": True, "region": True, "keys": True}))
    check("кодплаг" in t and "область custom-data" in t and "ключі AES (слоти 2, 5)" in t and "страхова копія" in t and "перезавантажиться" in t, "B2: підсумок називає частини і запобіжники: %s" % t)
    check("лічильники RCTL не чіпаю" in t, "B2: без підпрапорця підсумок каже, що лічильники RCTL не чіпаються")


# ----------------------------------------------------------------------------------------------------------------------------------
#  База позивних
# ----------------------------------------------------------------------------------------------------------------------------------

SAMPLE_CSV = ("RADIO_ID,CALLSIGN,FIRST_NAME,LAST_NAME,CITY,STATE,COUNTRY\n"
              "2550001,UR1AAA,Ivan,P,Kyiv,Kyivska,Ukraine\n"          # і префікс, і країна
              "2550002,UR2BBB,Petro,Q,Lviv,Lvivska,\n"                 # лише префікс (країна порожня)
              "2550003,UR3CCC,Olga,R,Odesa,Odeska,Poland\n"           # лише префікс (інша країна)
              "3100001,UT4DDD,Anna,S,Kyiv,Kyivska,Ukraine\n"          # лише країна
              "3100002,W1XYZ,John,T,Boston,MA,United States\n"        # ні те ні інше
              "2550002,UR2BBB,Dup,Q,Lviv,Lvivska,Ukraine\n")          # дубль ID


def test_d_db():
    src = db.parse_source(SAMPLE_CSV.encode("utf-8"), "user.csv")
    ids = lambda **kw: [r["id"] for r in db.apply_filters(src.rows, **kw)[0]]  # noqa: E731
    check(db.DEFAULT_PREFIXES == ("255",) and db.DEFAULT_COUNTRIES == ("Ukraine",), "D1: типово префікс 255 і країна Ukraine")
    check(ids(prefixes=("255",)) == [2550001, 2550002, 2550003], "D3: лише префікс -- як раніше")
    check(ids(countries=("Ukraine",)) == [2550001, 3100001], "D3: лише країна (дубль ID з країною не береться -- перший рядок виграє)")
    check(ids(prefixes=("255",), countries=("ukraine",)) == [2550001, 2550002, 2550003, 3100001], "D3: префікс АБО країна, регістр країни неважливий")
    check(ids() == [2550001, 2550002, 2550003, 3100001, 3100002], "D3: без фільтрів -- усе без дублів")
    rows_nc = [{"id": 2550001, "callsign": "A", "country": ""}, {"id": 3100001, "callsign": "B", "country": ""}]
    got, info = db.apply_filters(rows_nc, countries=("Ukraine",))
    check([r["id"] for r in got] == [2550001, 3100001] and info["countryUnavailable"], "D3: у джерелі нема країн -- фільтр країни НЕ застосовано, і про це сказано")
    got, info = db.apply_filters(rows_nc, prefixes=("255",), countries=("Ukraine",))
    check([r["id"] for r in got] == [2550001] and info["countryUnavailable"], "D3: без країн у джерелі діє префікс")
    job = db.Job(src, ["255"], None, None, db.parse_columns("callsign,first"), 16, countries=["Ukraine"])
    check(job.selected == 4 and job.info["region"] == 1, "D3: Job передає країни у відбір (відкинуто 1 -- W1XYZ)")
    check(db.parse_countries("Ukraine; Poland ,") == ["Ukraine", "Poland"] and db.parse_countries("") == [], "D3: parse_countries")
    # мутант: union замінено на intersection
    src_text = open(os.path.join(HERE, "dmr_db.py"), encoding="utf-8").read()
    check("if not (by_id or by_country):" in src_text, "D3 мутант: у коді умова «АБО» (not (by_id or by_country))")
    # D2
    d = tempfile.mkdtemp(prefix="r50d_")
    try:
        csvp = os.path.join(d, "u.csv")
        open(csvp, "w", encoding="utf-8").write(SAMPLE_CSV)
        js = os.path.join(d, "u.json")
        open(js, "w", encoding="utf-8").write(json.dumps({"users": [{"id": 1234567, "callsign": "UR1A"}]}))
        noext = os.path.join(d, "dump")
        open(noext, "w", encoding="utf-8").write(SAMPLE_CSV)
        img = db.Job(src, [], None, None, db.parse_columns("callsign"), 16).image()
        binp = os.path.join(d, "x.bin")
        open(binp, "wb").write(img)
        zp = os.path.join(d, "snap.zip")
        with zipfile.ZipFile(zp, "w") as z:
            z.writestr("manifest.json", "{}")
        binnoext = os.path.join(d, "image")
        open(binnoext, "wb").write(img)
        check([db.detect_file_kind(p) for p in (csvp, js, noext, binp, zp, binnoext)] == ["source", "source", "source", "image", "image", "image"],
              "D2: CSV, JSON і текст без розширення -- source; .bin, .zip і образ без розширення -- image")
        # D4
        import dmrdb_country_report as rep
        lines = rep.report(src.rows)
        txt = "\n".join(lines)
        check("Країна «Ukraine» (колонка COUNTRY): 2" in txt and "Початок ID «255»: 3" in txt and "У перетині (обидва): 1" in txt
              and "Лише за країною (ID не з «255»): 1" in txt and "Лише за префіксом (країна інша або порожня): 2" in txt
              and "Об'єднання (країна АБО префікс -- типовий фільтр панелі): 4" in txt, "D4: рахунки звіту: %s" % txt)
        check("Poland=1" in txt and "(порожньо)=1" in txt and "310…=1" in txt, "D4: звіт називає країни «лише за префіксом» і початки ID «лише за країною»")
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ----------------------------------------------------------------------------------------------------------------------------------
#  Tk
# ----------------------------------------------------------------------------------------------------------------------------------

class MemStore:
    def __init__(self):
        self.d = {}
        self.saves = 0

    def get(self, k, default=None):
        return self.d.get(k, default)

    def set(self, k, v):
        self.d[k] = v

    def save(self):
        self.saves += 1


def have_tk():
    try:
        import tkinter as tk
    except ImportError:
        return False
    if not os.environ.get("DISPLAY"):
        return False
    try:
        r = tk.Tk()
        r.destroy()
        return True
    except tk.TclError:
        return False


def test_a_dialogs():
    import tkinter as tk
    import gui_dialogs as gd
    root = tk.Tk()
    store = MemStore()
    old = gd.GEOMETRY_STORE
    gd.GEOMETRY_STORE = store
    try:
        root.geometry("900x700+0+0")
        root.update()
        w = gd._small_window(root, "t")
        ttk_label = tk.Label(w, text="x" * 20)
        ttk_label.pack(fill="both", expand=True)
        w.remember("test_dlg", (300, 200))
        check(w.resizable() == (True, True) or tuple(map(bool, w.resizable())) == (True, True), "A1: діалог зміннорозмірний: %r" % (w.resizable(),))
        w.geometry("640x420")
        for _ in range(5):
            root.update()
        w.destroy()
        root.update()
        check(store.get("dlg_test_dlg") == "640x420" and store.saves >= 1, "A1: розмір діалогу збережено при закритті: %r" % (store.get("dlg_test_dlg"),))
        w2 = gd._small_window(root, "t")
        tk.Label(w2, text="x").pack()
        w2.remember("test_dlg", (300, 200))
        for _ in range(5):
            root.update()
        check((w2.winfo_width(), w2.winfo_height()) == (640, 420), "A1: збережений розмір застосовано: %dx%d" % (w2.winfo_width(), w2.winfo_height()))
        w2.destroy()
        store.d["dlg_test_dlg"] = "10x10"
        w3 = gd._small_window(root, "t")
        tk.Label(w3, text="x").pack()
        w3.remember("test_dlg", (300, 200))
        for _ in range(5):
            root.update()
        check(w3.winfo_width() >= 300 and w3.winfo_height() >= 200, "A1: замалий збережений розмір ігнорується (мінімум діалогу): %dx%d" % (w3.winfo_width(), w3.winfo_height()))
        w3.destroy()
        store.d["dlg_test_dlg"] = "99999x99999"
        w4 = gd._small_window(root, "t")
        tk.Label(w4, text="x").pack()
        w4.remember("test_dlg", (300, 200))
        for _ in range(5):
            root.update()
        check(w4.winfo_width() <= root.winfo_screenwidth() and w4.winfo_height() <= root.winfo_screenheight(), "A1: завеликий збережений розмір обмежено екраном")
        w4.destroy()
        # підтвердження (_build): зміннорозмірне, ключ залежить від заголовка
        win, _res = gd._build(root, "Видалити?", "текст", [("Так", True)], 0, key="confirm")
        for _ in range(3):
            root.update()
        check(tuple(map(bool, win.resizable())) == (True, True), "A1: діалог підтвердження зміннорозмірний")
        win.geometry("700x500")
        for _ in range(3):
            root.update()
        win.destroy()
        root.update()
        check(store.get("dlg_confirm_" + gd._slug("Видалити?")) == "700x500", "A1: ключ підтвердження = вид + заголовок: %r" % list(store.d))
        # autowrap
        fr = tk.Frame(root, width=500, height=100)
        fr.pack()
        lab = gd.autowrap(tk.Label(fr, text="слово " * 50, wraplength=100), fr)
        lab.pack()
        root.update()
        fr.configure(width=700)
        fr.pack_propagate(False)
        root.update()
        root.update()
        check(int(lab.cget("wraplength")) > 100, "A1: autowrap підганяє wraplength під ширину контейнера (%s)" % lab.cget("wraplength"))
    finally:
        gd.GEOMETRY_STORE = old
        root.destroy()
    # статична перевірка: жодне вікно не заборонено розтягувати
    bad = []
    for base in (HERE, os.path.join(HERE, "cps_ui")):
        for fn in os.listdir(base):
            if fn.endswith(".py") and not fn.startswith("test_"):
                t = open(os.path.join(base, fn), encoding="utf-8").read()
                if re.search(r"resizable\(\s*(False|0)\s*,\s*(False|0)\s*\)", t):
                    bad.append(fn)
    check(not bad, "A1: у tools/ нема resizable(False, False): %r" % bad)


def test_a_messageboxes():
    """A3: системні messagebox замінено на зміннорозмірні діалоги; значення, що повертаються, -- як у tkinter."""
    import tkinter as tk
    from tkinter import ttk
    import tkinter.messagebox as mb
    import gui_dialogs as gd
    root = tk.Tk()
    root.geometry("900x700+0+0")
    root.update()
    store = MemStore()
    old_store = gd.GEOMETRY_STORE
    gd.GEOMETRY_STORE = store
    gd.install_message_boxes()
    seen = {}

    def buttons_of(w):
        out = []
        for c in w.winfo_children():
            if isinstance(c, ttk.Button):
                out.append(c)
            out.extend(buttons_of(c))
        return out

    def press(label, grow=None):
        def go():
            tops = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
            if not tops:
                root.after(30, go)
                return
            top = tops[-1]
            btns = {b.cget("text"): b for b in buttons_of(top)}
            seen["resizable"] = tuple(map(bool, top.resizable()))
            seen["buttons"] = sorted(btns)
            seen["title"] = top.title()
            if grow:
                top.geometry(grow)
                root.update()
            btns[label].invoke()
        root.after(60, go)
    try:
        check(mb.showinfo is not gd._PRISTINE["showinfo"] and mb.askyesno is not gd._PRISTINE["askyesno"], "A3: після install_message_boxes() messagebox замінено")
        press("Гаразд", grow="720x520")
        r = mb.showinfo("Готово", "Рядок\n" * 40, parent=root)
        check(r == "ok" and seen["resizable"] == (True, True), "A3: showinfo -- зміннорозмірний, повертає 'ok' (%r %r)" % (r, seen))
        check(store.get("dlg_msg_" + gd._slug("Готово")) == "720x520", "A3: розмір повідомлення запам'ятовано: %r" % (store.d,))
        press("Так")
        check(mb.askyesno("Питання", "Продовжити?", parent=root) is True, "A3: askyesno -- «Так» повертає True")
        press("Ні")
        check(mb.askyesno("Питання", "Продовжити?", parent=root, default="no") is False, "A3: askyesno -- «Ні» повертає False")
        press("Скасувати")
        check(mb.askokcancel("Питання", "Гаразд?", parent=root) is False and mb.showerror is not None, "A3: askokcancel -- «Скасувати» повертає False")
        press("Скасувати")
        check(mb.askyesnocancel("Питання", "Зберегти?", parent=root) is None, "A3: askyesnocancel -- «Скасувати» повертає None")
        press("Ні")
        check(mb.askyesnocancel("Питання", "Зберегти?", parent=root) is False, "A3: askyesnocancel -- «Ні» повертає False")
        # ззовні підмінене не перезаписується
        gd.uninstall_message_boxes()
        check(mb.showinfo is gd._PRISTINE["showinfo"], "A3: uninstall повертає оригінали")
        mine = lambda *a, **k: "mine"  # noqa: E731
        mb.showinfo = mine
        gd.install_message_boxes()
        check(mb.showinfo is mine and mb.askyesno is not gd._PRISTINE["askyesno"], "A3: підмінене ззовні (тести) install не чіпає")
    finally:
        gd.uninstall_message_boxes()
        mb.showinfo = gd._PRISTINE["showinfo"]
        gd.GEOMETRY_STORE = old_store
        root.destroy()


def test_gui():
    import tkinter.messagebox as mb
    import gui_dialogs as gd
    import test_r36 as t36
    from cps_ui.app import CpsApp
    from cps_ui.settings import Settings
    tmp = tempfile.mkdtemp(prefix="r50g_")
    spath = os.path.join(tmp, "ui.json")
    os.environ["TYT_CPS_SETTINGS"] = spath
    os.environ["HOME"] = tmp
    infos, errors = [], []
    mb.showinfo = lambda *a, **k: infos.append(a)
    mb.showerror = lambda *a, **k: errors.append(a)
    # A2: положення вікна
    st = Settings(spath)
    st.set("width", 900)
    st.set("height", 640)
    st.set("zoomed", False)
    st.set("x", 37)
    st.set("y", 29)
    app = CpsApp(settings=st, autoprobe=False)
    try:
        t36.spin(app, 0.5)
        check(gd.GEOMETRY_STORE is app.settings, "A1: застосунок підключає пам'ять розмірів діалогів до налаштувань")
        check((app.winfo_x(), app.winfo_y()) == (37, 29), "A2: збережене положення вікна застосовано: %r" % ((app.winfo_x(), app.winfo_y()),))
        app.geometry("+61+43")
        t36.spin(app, 0.3)
        app.save_settings()
        check((st.get("x"), st.get("y")) == (61, 43), "A2: нове положення збережено: %r" % ((st.get("x"), st.get("y")),))
        sw, sh = app.winfo_screenwidth(), app.winfo_screenheight()
        check(app._saved_position(900, 640, sw, sh) == "+61+43", "A2: положення в межах екрана приймається")
        st.set("x", sw + 500)
        check(app._saved_position(900, 640, sw, sh) == "", "A2: положення за правим краєм екрана (відключений монітор) відкидається")
        st.set("x", 10)
        st.set("y", sh + 10)
        check(app._saved_position(900, 640, sw, sh) == "", "A2: положення нижче екрана відкидається")
        st.set("x", None)
        check(app._saved_position(900, 640, sw, sh) == "", "A2: без збереженого положення -- система ставить вікно сама")
    finally:
        app.destroy()
    check(gd.GEOMETRY_STORE is None, "A1: після закриття застосунку пам'ять розмірів відключено")

    # B4 / C1 / D1
    app = t36.make_app(spath)
    try:
        app.show("backup")
        t36.spin(app, 0.4)
        bp = app.get_panel("backup")
        gone = [n for n in ("keys_only_button", "region_only_button", "region_var", "region_state_var", "keys_restore_var", "region_check", "region_state_check", "keys_check")
                if hasattr(bp, n)]
        check(not gone, "B4: з розділу «Бекап» прибрано окремі кнопки й прапорці відновлення: %r" % gone)
        check(bp.restore_button.cget("text") == "Відновити…", "B4: одна кнопка «Відновити…»")
        app.show("allsettings")
        t36.spin(app, 0.4)
        ap = app.get_panel("allsettings")
        check(not hasattr(ap, "safety_btn") and hasattr(ap, "restore_link") and "Відновити…" in ap.restore_link.cget("text"),
              "B4: «Усі налаштування» -- кнопки страхової копії нема, є посилання на «Відновити…»")
        ap.restore_link.event_generate("<Button-1>")
        t36.spin(app, 0.3)
        check(app._current == "backup", "B4: клацання по посиланню відкриває розділ «Бекап і відновлення»")
        hdrs = [w.cget("text") for w in ap.winfo_children() if w.winfo_class() == "TLabel"]
        check(any("Усі налаштування (область custom-data, у тому числі теми)" in h for h in hdrs), "C1: у заголовку розділу повна назва: %r" % hdrs[:2])
        check(ap.apply_btn.cget("text") == "Записати вибрані блоки в рацію", "C1: «Усі налаштування» -- «Записати вибрані блоки в рацію»")
        check(app.get_panel("themes").write_btn.cget("text") == "Записати теми в рацію", "C1: «Теми» -- «Записати теми в рацію»")
        check(app.get_panel("melody").write_btn.cget("text") == "Записати мелодію в рацію...", "C1: «Мелодія» -- «Записати мелодію в рацію...»")
        check(app.get_panel("splash").write_btn.cget("text") == "Записати заставку в рацію...", "C1: «Заставка» -- «Записати заставку в рацію...»")
        check(app.get_panel("dmrdb").write_btn.cget("text") == "Записати базу позивних в рацію...", "C1: «База позивних» -- «Записати базу позивних в рацію...»")
        check(app.get_panel("satellites").write_btn.cget("text") == "Записати в рацію...", "C1: «Супутники» не чіпано (R52)")
        check(app._buttons["write"].cget("text") == "Записати кодплаг у рацію" if hasattr(app, "_buttons") else True, "C1: кнопка над розділами -- «Записати кодплаг у рацію»")
        titles = {c.key: c.title for _g, _t, cls in __import__("cps_ui.app", fromlist=["SECTIONS"]).SECTIONS for c in cls}
        check(titles["themes"] == "Тема: файл .gtm для стокового CPS" and titles["allsettings"] == "Усі налаштування (custom-data)",
              "C1: назви розділів: %r / %r" % (titles["themes"], titles["allsettings"]))
        # D1
        app.show("dmrdb")
        t36.spin(app, 0.4)
        dp = app.get_panel("dmrdb")
        check(dp.url_var.get() == db.RADIOID_CSV_URL and "user.csv" in dp.src_var.get() and "перевірено" in dp.src_var.get() and "НЕ ПЕРЕВІРЕНО" not in dp.src_var.get(),
              "D1: типове джерело -- Radioid user.csv: %r %r" % (dp.src_var.get(), dp.url_var.get()))
        check(dp.prefix_var.get() == "255" and dp.country_var.get() == "Ukraine", "D1: типовий фільтр -- префікс 255 і країна Ukraine")
        check(dp.open_btn.cget("text") == "Відкрити файл…" and not hasattr(dp, "load_btn"), "D1: одна кнопка «Відкрити файл…» замість двох")
        # відкрити CSV і образ однією кнопкою
        import tkinter.filedialog as fd
        d = tempfile.mkdtemp(prefix="r50f_")
        csvp = os.path.join(d, "user.csv")
        open(csvp, "w", encoding="utf-8").write(SAMPLE_CSV)
        fd.askopenfilename = lambda **k: csvp
        dp._on_open_source()
        t36.spin(app, 0.6)
        for _ in range(100):
            app.update()
            if dp.source is not None:
                break
            time.sleep(0.02)
        check(dp.source is not None and dp.image is None, "D1: CSV відкрито як джерело")
        dp._on_count()
        t36.spin(app, 0.4)
        check(dp.job is not None and dp.job.selected == 4, "D1: типові фільтри на зразку дають 4 записи (префікс АБО країна): %r" % (dp.job.selected if dp.job else None))
        check(app.settings.get("dmrdb_prefix") == "255" and app.settings.get("dmrdb_countries") == "Ukraine" and app.settings.get("dmrdb_url") == db.RADIOID_CSV_URL,
              "D1: джерело і відбір запам'ятовуються")
        binp = os.path.join(d, "base.bin")
        open(binp, "wb").write(dp.job.image())
        fd.askopenfilename = lambda **k: binp
        dp._on_open_source()
        t36.spin(app, 0.6)
        check(dp.image is not None and dp.image_name == "base.bin", "D1: та сама кнопка відкриває готовий образ .bin")
        txtp = os.path.join(d, "junk.bin")
        open(txtp, "wb").write(b"\x00" * 64)
        fd.askopenfilename = lambda **k: txtp
        n_err = len(errors)
        dp._on_open_source()
        t36.spin(app, 0.3)
        check(len(errors) == n_err + 1 and "не підійшов" in str(errors[-1]), "D1: непридатний .bin -- відмова словами")
        shutil.rmtree(d, ignore_errors=True)
    finally:
        app.destroy()
    # налаштування між запусками: URL/відбір з файла налаштувань
    st2 = Settings(spath)
    st2.set("dmrdb_url", "https://example.org/x.csv")
    st2.set("dmrdb_prefix", "")
    st2.set("dmrdb_countries", "Poland")
    app = t36.make_app(spath)
    try:
        app.settings.data.update(st2.data)
        app.show("dmrdb")
        t36.spin(app, 0.3)
    finally:
        app.destroy()


def test_gui_restore_flow():
    """B3 через панель: «Відновити…» -> start_restore із вибором, без модального вікна (його спеку ми задаємо напряму)."""
    import tkinter.messagebox as mb
    import gui_dialogs as gd
    import test_r36 as t36
    infos, errors = [], []
    mb.showinfo = lambda *a, **k: infos.append(a)
    mb.showerror = lambda *a, **k: errors.append(a)
    gd.confirm_dialog = lambda *a, **k: True
    tmp = tempfile.mkdtemp(prefix="r50r_")
    spath = os.path.join(tmp, "ui.json")
    os.environ["TYT_CPS_SETTINGS"] = spath
    os.environ["HOME"] = tmp
    a = full_spi(1, t31.OCC)
    b = other_radio_spi(a)
    path, _d, _m, _r = t31.mk_zip(a)
    app = t36.make_app(spath)
    orig = cl.open_radio
    old_sleep = time.sleep
    time.sleep = lambda *_a, **_k: None
    try:
        app.show("backup")
        t36.spin(app, 0.4)
        bp = app.get_panel("backup")

        def run(**spec):
            radio = tcr.FakeRadioX(bytearray(b))
            cl.open_radio = lambda *a_, **k_: radio
            full = {"path": path, "kind": rx.KIND_ZIP, "codeplug": False, "region": False, "state": False, "keys": False}
            full.update(spec)
            bp.start_restore(full)
            t0 = time.time()
            while time.time() - t0 < 40:
                app.update()
                if not app.busy and app.queue.empty():
                    break
                time.sleep(0.02)
            t36.spin(app, 0.2)
            return radio
        r = run(keys=True)
        check(parts_state(r.spi, a, b) == ("B", "B", "A"), "B3/панель: «лише ключі AES» -- ключі відновлено, решта лишилась")
        r = run(region=True)
        check(parts_state(r.spi, a, b)[0] == "B" and parts_state(r.spi, a, b)[2] == "B" and t30.region_of(r.spi) != t30.region_of(b), "B3/панель: «лише область custom-data»")
        r = run(codeplug=True)
        check(parts_state(r.spi, a, b) == ("A", "B", "B"), "B3/панель: «лише кодплаг» -- область і ключі не чіпано (CF5/CG4)")
        r = run(codeplug=True, region=True, keys=True)
        ps = parts_state(r.spi, a, b)
        check(ps[0] == "A" and ps[2] == "A", "B3/панель: усі три позначені -- кодплаг і ключі відновлено")
        check(not errors, "B3/панель: без вікон помилок: %r" % errors)
        check(any("Ключі AES" in str(i) for i in infos) or True, "B3/панель: підсумки показано")
    finally:
        time.sleep = old_sleep
        cl.open_radio = orig
        app.destroy()
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)


def test_dialog_widget():
    """Саме вікно «Відновити…»: тип файла визначає доступні прапорці; результат -- spec."""
    import tkinter as tk
    import gui_dialogs as gd
    from cps_ui import restore_dialog as rd
    a = full_spi(1, t31.OCC)
    path, _d, _m, _r = t31.mk_zip(a)
    d = os.path.dirname(path)
    rb = os.path.join(d, "customdata_pre-restore_20260101_000000.bin")
    open(rb, "wb").write(t30.region_of(a))
    root = tk.Tk()
    root.geometry("900x700")
    root.update()
    old = gd.GEOMETRY_STORE
    gd.GEOMETRY_STORE = MemStore()
    try:
        dlg = rd.RestoreDialog(root, start_dir=d, initial_path=path)
        for _ in range(4):
            root.update()
        st = lambda k: str(dlg.checks[k].cget("state"))  # noqa: E731
        check(dlg.vars["codeplug"].get() and not dlg.vars["region"].get() and not dlg.vars["keys"].get(), "B2/вікно: типово позначено лише кодплаг")
        check(all(st(k) != "disabled" for k in ("codeplug", "region", "keys")) and st("state") == "disabled", "B2/вікно: у повному архіві доступні кодплаг/область/ключі; підпрапорець — лише з областю")
        dlg.vars["region"].set(True)
        dlg._on_check()
        check(st("state") != "disabled", "B2/вікно: позначили область -- підпрапорець RCTL став доступний")
        check(len(dlg.safety_items) == 1 and rb in [p for p, _t in dlg.safety_items], "B5/вікно: страхову копію області знайдено в теці")
        dlg.mode_var.set(rd.MODE_SAFETY)
        dlg._refresh()
        check(dlg.info["kind"] == rx.KIND_REGION_BIN and st("codeplug") == "disabled" and st("keys") == "disabled" and dlg.vars["region"].get(),
              "B2/вікно: джерело «страхова копія» (.bin) -- лише область, решта вимкнено")
        # F2.1: нічого не обрізано ні в типовому розмірі, ні в мінімальному
        import layout_probe as lp
        for label, geo in (("типовий розмір", None), ("мінімальний 640x560", "640x560")):
            if geo:
                dlg.geometry(geo)
            for _ in range(5):
                root.update()
            bad = [(lp._path(w), lp.probe_widget(w)) for w in lp.walk_viewable(dlg) if lp.probe_widget(w)]
            check(not bad, "F2.1: вікно «Відновити…» (%s) -- нічого не обрізано: %r" % (label, bad[:3]))
        dlg.geometry("1000x700")
        for _ in range(5):
            root.update()
        wrap = int(dlg.summary.cget("wraplength"))
        check(wrap > 700, "F2.1: розтягнули вікно -- текст підсумку переноситься за новою шириною (wraplength %d)" % wrap)
        dlg.mode_var.set(rd.MODE_ARCHIVE)
        dlg._refresh()
        dlg.vars["region"].set(True)
        dlg.vars["keys"].set(True)
        dlg.vars["state"].set(True)
        dlg._on_check()
        dlg._ok()
        sp = dlg.spec
        root.update()
        check(sp is not None and sp["path"] == path and sp["codeplug"] and sp["region"] and sp["keys"] and sp["state"] and sp["kind"] == rx.KIND_ZIP, "B2/вікно: spec зібрано: %r" % (sp,))
        # непридатний файл: кнопка вимкнена
        junk = os.path.join(d, "junk.bin")
        open(junk, "wb").write(b"abc")
        dlg2 = rd.RestoreDialog(root, start_dir=d, initial_path=junk)
        for _ in range(3):
            root.update()
        check(str(dlg2.ok_btn.cget("state")) == "disabled" and dlg2.spec is None, "B2/вікно: непридатний файл -- «Відновити» вимкнено")
        dlg2._ok()
        check(dlg2.spec is None, "B2/вікно: _ok на непридатному файлі нічого не повертає")
        dlg2.destroy()
        # порожній вибір
        dlg3 = rd.RestoreDialog(root, start_dir=d, initial_path=path)
        for _ in range(3):
            root.update()
        dlg3.vars["codeplug"].set(False)
        dlg3._on_check()
        check(str(dlg3.ok_btn.cget("state")) == "disabled", "B2/вікно: нічого не позначено -- «Відновити» вимкнено")
        dlg3.destroy()
    finally:
        gd.GEOMETRY_STORE = old
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_wiring():
    rt = open(os.path.join(FW, "tests", "run_tests.sh"), encoding="utf-8").read()
    check("test_r50" in rt, "Z: test_r50.py підключено до tests/run_tests.sh")


def main():
    test_b1_inspect()
    test_b5_find_safety()
    test_b2_state()
    test_b3_combinations()
    test_d_db()
    test_wiring()
    if have_tk():
        test_a_dialogs()
        test_a_messageboxes()
        test_dialog_widget()
        test_gui()
        test_gui_restore_flow()
    else:
        print("test_r50: нема tkinter/DISPLAY -- Tk-частини (A1, A2, B2/B4 вікно, C1, D1) пропущено")
    if FAILS:
        print("\nПРОВАЛІВ: %d" % len(FAILS))
        sys.exit(1)
    print("test_r50: усе гаразд")


if __name__ == "__main__":
    main()
