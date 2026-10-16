#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Хост-тест R26 V2: редактор контактів (tools/contact_edit.py + вкладка «Контакти» у вікні перегляду).

Логіка -- без Tk. Частина з Tk (вікно, діалог) -- лише коли є tkinter і DISPLAY (xvfb-run -a python3.12 ...), інакше «ПРОПУЩЕНО».
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cps_link as cl            # noqa: E402
import cps_csv as cc             # noqa: E402
import codeplug_view as cv       # noqa: E402
import contact_edit as ce        # noqa: E402
import test_cps_csv as tc        # noqa: E402
import test_cps_restore as tr    # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def fixture():
    spi = tc.make_fixture_spi()
    cp, _data = tc.codeplug_of(spi)
    return spi, cp


def orig_of(cp, number):
    return next(c for c in cp.contacts() if c[0] == number)


def test_check_name():
    r = ce.check_name("АБВГДЕЁЖ")
    check(r["ok"] and r["nbytes"] == 16 and r["remaining"] == 0 and r["enc"] == "GBK", "8 кирилічних літер у GBK = 16 байтів, залишилось 0: %r" % r)
    r = ce.check_name("АБВГДЕЁЖЗ")
    check(not r["ok"] and r["nbytes"] == 18 and r["remaining"] == -2 and "2 байт" in r["message"], "9 літер -- на 2 байти більше ліміту: %r" % r)
    r = ce.check_name("Київ")
    check(r["ok"] and r["enc"] == "cp1251" and r["nbytes"] == 4 and r["remaining"] == 12, "«Київ» -- cp1251, 4 байти, залишилось 12: %r" % r)
    check(not ce.check_name("")["ok"] and not ce.check_name("Test ★")["ok"], "порожня назва й символ поза кодуваннями відхиляються")
    check(ce.check_name("LOCAL")["enc"] == "GBK" and ce.check_name("LOCAL")["remaining"] == 11, "ASCII: 5 байтів, залишилось 11")
    for bad in ("", "abc", "-1", "16777216", "1.5"):
        try:
            ce.parse_id(bad)
            check(False, "parse_id(%r) мав відхилити" % bad)
        except ValueError:
            pass
    check(ce.parse_id("16777215") == 16777215 and ce.parse_id(" 91 ") == 91, "parse_id приймає межі")


def test_apply_ops():
    spi, cp = fixture()
    base_img = cc.Image.from_codeplug(cp)
    before = (bytes(base_img.eeprom), bytes(base_img.flash))
    papuga = orig_of(cp, 1)
    # --- редагування: назва, ID, тип ---
    res = ce.apply_ops(base_img, [{"op": "edit", "slot": 0, "expect_name": papuga[4], "name": "Дракон", "id": 4321, "type": 2}])
    check((bytes(base_img.eeprom), bytes(base_img.flash)) == before, "apply_ops не псує вхідний образ")
    new = {s_: r for s_, r in res.image.contacts()}[0]
    check(cv.decode_name_ex(new[:16]) == ("Дракон", "GBK") and cv.bcd_to_int(new[16:20]) == 4321 and new[20] == 2, "контакт змінено: %r" % new)
    check(new[21:24] == bytes(base_img.fl(cl.CP_ADDR_CONTACTS, 24))[21:24], "ringStyle/rxTone/TS-override НЕ чіпались")
    check(len(res.changed) == 1 and not res.added and not res.removed, "звіт: одна зміна")
    # --- лише зміна типу -> решта байтів контакту ті самі ---
    res = ce.apply_ops(base_img, [{"op": "edit", "slot": 0, "expect_name": papuga[4], "name": None, "id": None, "type": 0}])
    new = {s_: r for s_, r in res.image.contacts()}[0]
    old = {s_: r for s_, r in base_img.contacts()}[0]
    check(new[:20] == old[:20] and new[20] == 0 and new[21:] == old[21:], "змінено лише тип виклику")
    # --- додавання ---
    res = ce.apply_ops(base_img, [{"op": "add", "name": "Одеса", "id": 2550, "type": 0}])
    check(len(res.added) == 1, "додано контакт")
    slots = {s_: r for s_, r in res.image.contacts()}
    check(len(slots) == len(base_img.contacts()) + 1, "у кодплузі на один контакт більше")
    free_slot = [s_ for s_ in slots if s_ not in dict(base_img.contacts())][0]
    check(free_slot == 3, "перший вільний слот, на який ніхто не посилається: %d" % free_slot)
    rec = slots[free_slot]
    check(cv.decode_name_ex(rec[:16])[0] == "Одеса" and cv.bcd_to_int(rec[16:20]) == 2550 and rec[20] == 0 and rec[22] == 0xFF, "поля нового контакту")
    # --- видалення: маркер порожнього запису і попередження про групу ---
    lokal = orig_of(cp, 3)
    res = ce.apply_ops(base_img, [{"op": "delete", "slot": 2, "expect_name": lokal[4]}])
    check(res.image.fl(cl.CP_ADDR_CONTACTS + 2 * 24, 24) == b"\xff" * 24, "видалений контакт -- 24 байти 0xFF (name[0] == 0xFF)")
    check(2 not in dict(res.image.contacts()), "видалений контакт зник зі списку")
    check(len(res.warnings) == 1 and "Ukraine" in res.warnings[0] and "LOCAL" in res.warnings[0], "попередження називає TG-список: %r" % res.warnings)
    check(len(res.removed) == 1, "звіт: одне видалення")
    # контакт, яким ніхто не користується: без попередження
    allc = orig_of(cp, 11)
    res = ce.apply_ops(base_img, [{"op": "delete", "slot": 10, "expect_name": allc[4]}])
    check(not res.warnings, "видалення невикористаного контакту -- без попередження")
    check(ce.delete_warning(base_img, 10) is None and "Ukraine" in ce.delete_warning(base_img, 2), "delete_warning для GUI")
    # --- відмови ---
    for label, ops, frag in (
            ("назва задовга", [{"op": "add", "name": "АБВГДЕЁЖЗ", "id": 1, "type": 0}], "2 байт"),
            ("слот чужий (назва інша)", [{"op": "edit", "slot": 0, "expect_name": b"Other".ljust(16, b"\xff"), "name": "X", "id": None, "type": None}],
             "вже не такий"),
            ("слот порожній", [{"op": "delete", "slot": 500, "expect_name": b"x" * 16}], "вже не такий"),
            ("символ поза кодуваннями", [{"op": "edit", "slot": 0, "expect_name": papuga[4], "name": "A✓", "id": None, "type": None}], "не кодуються"),
    ):
        try:
            ce.apply_ops(base_img, ops)
            check(False, "%s: мало бути відхилено" % label)
        except ce.ContactEditError as e:
            check(frag in str(e) and "Нічого не записано" in str(e), "%s: %s" % (label, e))
    # --- cp1251-попередження один раз ---
    res = ce.apply_ops(base_img, [{"op": "add", "name": "Київ", "id": 1, "type": 0}, {"op": "add", "name": "Їжак2", "id": 2, "type": 0}])
    check(sum("cp1251" in w for w in res.warnings) == 1, "попередження про cp1251 -- один раз: %r" % res.warnings)


def test_radio_flow():
    spi, cp = fixture()
    papuga = orig_of(cp, 1)
    with tempfile.TemporaryDirectory() as d:
        radio = tr.FakeRadioX(bytearray(spi))
        texts = []
        ops = [{"op": "edit", "slot": 0, "expect_name": papuga[4], "name": "Дракон", "id": None, "type": None},
               {"op": "delete", "slot": 2, "expect_name": orig_of(cp, 3)[4]}, {"op": "add", "name": "Одеса", "id": 2550, "type": 0}]
        with tr.Unlocked():
            res = ce.apply_to_radio(cl.CpsLink(radio, retries=0), ops, lambda t, p: texts.append(t) or True, log=lambda *_: None, out_dir=d)
        check(res["sectorsWritten"] >= 1 and radio.c_calls[:1] == [bytes([0])] and radio.c_calls[-1] == bytes([6, 1]), "запис пройшов шляхом відновлення")
        t = texts[0]
        for frag in ("ЗМІНА КОНТАКТІВ", "ВИДАЛЯЄТЬСЯ", "Ukraine", "Дракон", "Одеса", "pre-restore"):
            check(frag in t, "діалог містить «%s»" % frag)
        check(all(0x9B <= s_ < 0xAF for s_ in radio.commits), "записано лише сектори флеш-кодплуга: %r" % radio.commits)
        cp2, _ = cv.codeplug_from_radio(cl.CpsLink(tr.FakeRadioX(radio.spi), retries=0))
        names = {c[0]: c[1] for c in cp2.contacts()}
        check(names.get(1) == "Дракон" and 3 not in names and any(v == "Одеса" for v in names.values()), "у рації: %r" % names)
        check(bytes(radio.spi[0x10000:0x11000]) == bytes(spi[0x10000:0x11000]), "калібрування не чіпали")
        # --- рація змінилась після читання: відмова без жодного X ---
        spi2 = bytearray(spi)
        a = cl.FLASH_ADDRESS_OFFSET + cl.CP_ADDR_CONTACTS
        spi2[a:a + 16] = b"Renamed".ljust(16, b"\xff")
        radio2 = tr.FakeRadioX(spi2)
        with tr.Unlocked():
            try:
                ce.apply_to_radio(cl.CpsLink(radio2, retries=0), ops, lambda t, p: True, log=lambda *_: None, out_dir=d)
                check(False, "контакт змінився в рації -- мала бути відмова")
            except ce.ContactEditError as e:
                check("вже не такий" in str(e), "відмова: %s" % e)
        check(radio2.x_total == 0 and not radio2.c_calls, "відмова: жодної X/C-команди")
        # --- заблоковано ---
        radio3 = tr.FakeRadioX(bytearray(spi))
        with tr.Locked():
            try:
                ce.apply_to_radio(cl.CpsLink(radio3, retries=0), ops, lambda t, p: True, log=lambda *_: None, out_dir=d)
                check(False, "заблоковано")
            except cl.CpsError as e:
                check("заблоковано" in str(e), "блокування: %s" % e)
        check(radio3.x_total == 0, "при блокуванні жодної X-команди")


def test_gui():
    try:
        import tkinter as tk
    except ImportError:
        print("ПРОПУЩЕНО (GUI): нема tkinter")
        return
    if not os.environ.get("DISPLAY"):
        print("ПРОПУЩЕНО (GUI): нема DISPLAY")
        return
    import gui_flasher as gf
    import codeplug_viewer_gui as cvg
    spi, cp = fixture()
    app = gf.FlasherApp()
    try:
        sent = []
        v = cvg.CodeplugViewerWindow(app, cp, "тест", HERE, write_contacts=lambda ops, w: sent.append(ops))
        v.update()
        tree = v.contact_tree
        hdr = [tree.heading(c)["text"] for c in tree["columns"]]
        check(hdr[-1] == "Стан", "є колонка «Стан»: %r" % hdr)
        rows = [tree.item(i)["values"] for i in tree.get_children()]
        check(len(rows) == 4 and all(r[-1] == "" for r in rows), "спершу зміни відсутні: %r" % rows)
        # додати через діалог
        def fill_add():
            dlg = None
            for w in v.winfo_children() + app.winfo_children():
                if isinstance(w, cvg.ContactDialog):
                    dlg = w
            dlg.name_var.set("АБВГДЕЁЖЗ")
            dlg.update()
            check(str(dlg.ok_btn.cget("state")) == "disabled" and "18 з 16" in dlg.name_info.cget("text"), "задовга назва: лічильник і вимкнене «Готово»: %s" % dlg.name_info.cget("text"))
            dlg.name_var.set("Київ")
            dlg.id_var.set("2550")
            dlg.update()
            check(str(dlg.ok_btn.cget("state")) == "normal" and "4 з 16" in dlg.name_info.cget("text") and "залишилось 12" in dlg.name_info.cget("text"),
                  "вкладка: лічильник байтів: %s" % dlg.name_info.cget("text"))
            dlg._ok()
        app.after(200, fill_add)
        v._on_add_contact()
        rows = [tree.item(i)["values"] for i in tree.get_children()]
        check(len(rows) == 5 and rows[-1][0] == "нов." and rows[-1][-1] == "новий" and rows[-1][1] == "Київ", "новий контакт у таблиці зі словом «новий»: %r" % rows[-1])
        # видалити виділений (LOCAL, яким користується TG-список): діалог-попередження -- закриваємо «Додати в чергу»
        item = [i for i in tree.get_children() if tree.item(i)["values"][1] == "LOCAL"][0]
        tree.selection_set(item)

        def press_yes():
            for w in v.winfo_children() + app.winfo_children():
                if w.winfo_class() == "Toplevel" and hasattr(w, "_dialog_text"):
                    txt = w._dialog_text.get("1.0", "end")
                    check("Ukraine" in txt, "попередження називає групу: %r" % txt[:120])
                    for ch in w.winfo_children():
                        for b in ch.winfo_children():
                            if b.winfo_class() == "TButton" and b.cget("text") == "Додати в чергу":
                                b.invoke()
                                return
        app.after(200, press_yes)
        v._on_delete_contact()
        rows = {tree.item(i)["values"][1]: tree.item(i)["values"][-1] for i in tree.get_children()}
        check(rows.get("LOCAL") == "видалятиметься", "видалення позначено словом: %r" % rows)
        check(len(v.ops) == 2, "у черзі 2 операції")
        # «Записати» вимкнено, поки відновлення заблоковане (RESTORE_UNLOCKED == False) -- і працює, коли розблоковане
        import cps_restore as cr
        old = cr.RESTORE_UNLOCKED
        try:
            cr.RESTORE_UNLOCKED = False
            v._refresh_contacts()
            check(str(v.btn_write.cget("state")) == "disabled" and cr.LOCKED_CAPTION in v.edit_note.cget("text"), "заблоковано: кнопка запису вимкнена, є пояснення")
            v._on_write()
            check(not sent, "заблоковано: обробник запису не викликано")
            cr.RESTORE_UNLOCKED = True
            v._refresh_contacts()
            check(str(v.btn_write.cget("state")) == "normal", "розблоковано: кнопка запису активна")
            v._on_write()
            check(len(sent) == 1 and len(sent[0]) == 2, "обробник отримав 2 операції")
        finally:
            cr.RESTORE_UNLOCKED = old
        v._on_undo_all()
        check(not v.ops and len(tree.get_children()) == 4, "скасування змін")
        # вікно «з бекапу» -- без редактора
        v2 = cvg.CodeplugViewerWindow(app, cp, "файл", HERE)
        check(v2.contact_tree is None, "перегляд бекап-файла не має редактора")
    finally:
        app.destroy()


def main():
    for t in (test_check_name, test_apply_ops, test_radio_flow, test_gui):
        try:
            t()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILS.append("%s: виняток %r" % (t.__name__, e))
    if FAILS:
        print("test_contact_edit: ПРОВАЛЕНО перевірок: %d" % len(FAILS))
        return 1
    print("test_contact_edit: усі перевірки пройшли (назва/ліміт, операції, запис шляхом відновлення, відмови, вікно).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
