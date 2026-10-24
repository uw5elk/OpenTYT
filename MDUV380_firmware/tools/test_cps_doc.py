#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Хост-тест CPS-doc (етап 2): кодплаг як документ (tools/cps_ui/document.py, codeplug_edit.py, дії та панелі вікна).

R6.1  відкрити з бекапу -> змінити контакт -> «Зберегти як…» -> відкрити файл ще раз -> зміна на місці;
R6.2  експорт CSV з документа -> імпорт того самого CSV у документ -> образ БАЙТ-У-БАЙТ той самий;
R6.3  імпорт CSV з помилкою -> документ не змінено (ні байта, ні журналу);
R6.4  димовий прогін під xvfb: КОЖНА панель і з відкритим, і з порожнім документом, без винятків;
плюс: основна інформація, APRS-слоти, злиття при записі документа з рації (рація встигла змінити «лічильники» -- вони НЕ затираються),
запис шляхом відновлення (калібрування не чіпається, C 6 1), заборона запису для іншої моделі рації, питання про незбережені зміни.

Без рації: підставна FakeRadioX (як у test_cps_restore). GUI-частина потребує tkinter і DISPLAY (`xvfb-run -a python3 tools/test_cps_doc.py`).
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cps_link as cl                # noqa: E402
import cps_csv as cc                 # noqa: E402
import cps_restore as cr             # noqa: E402
import codeplug_edit as ced          # noqa: E402
import codeplug_view as cv           # noqa: E402
import test_cps_csv as tc            # noqa: E402
import test_cps_restore as tr        # noqa: E402
from cps_ui import document as D     # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def snap(doc):
    return bytes(doc.image.eeprom), bytes(doc.image.flash)


def fixture_doc(origin=D.ORIGIN_FILE):
    spi = tc.make_fixture_spi()
    cp, data = tc.codeplug_of(spi)
    return D.Document(cp, origin, source_file="фікстура.zip"), spi, data


class ClosableRadio(tr.FakeRadioX):
    def close(self):
        pass


# ----------------------------------------------------------------------------------------
#  R6.1 / R6.2 / R6.3
# ----------------------------------------------------------------------------------------

def test_open_edit_save_reopen():
    spi = tc.make_fixture_spi()
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "orig.zip")
        _cp, data = tc.codeplug_of(spi)
        with open(src, "wb") as f:
            f.write(data)
        doc = D.from_backup(src)
        check(not doc.modified and doc.origin == D.ORIGIN_FILE and doc.title_text() == "orig.zip", "відкрито з бекапу: без зірочки, джерело файл")
        check(doc.write_block_reason() is None, "документ з файла тієї самої моделі: запис дозволений")
        events = []
        doc.add_listener(lambda x: events.append(x.modified))
        slot = 0
        raw = next(c for c in doc.view().contacts() if c[0] - 1 == slot)
        changed = doc.edit_contacts([{"op": "edit", "slot": slot, "expect_name": raw[4], "name": "Змінений", "id": 4242, "type": 1}])
        check(changed and doc.modified and doc.title_text().startswith("*"), "правка контакта: зірочка в назві")
        check(events and events[-1] is True, "слухачі отримали сповіщення про зміну")
        check(len(doc.changes) == 1 and doc.changes[0][0] == "changed", "журнал змін: %r" % doc.changes)
        out = os.path.join(d, "saved.zip")
        doc.save_as(out)
        check(not doc.modified and not doc.title_text().startswith("*"), "після «Зберегти як…» зірочки нема")
        # файл -- той самий формат, що й бекап: його приймає і відновлення (маніфест, SHA-256), і «Відкрити з бекапу»
        man, ee, fl = cr.load_backup_for_restore(out)
        check(len(ee) == cl.EEPROM_BACKUP_LEN and man["radio"]["radioType"] == cl.RADIO_TYPE_MDUV380, "збережений .zip проходить перевірку відновлення")
        doc2 = D.from_backup(out)
        c2 = next(c for c in doc2.view().contacts() if c[0] - 1 == slot)
        check(c2[1] == "Змінений" and c2[2] == 4242 and c2[3] == 1, "після повторного відкриття зміна на місці: %r" % (c2[:4],))
        check(not doc2.modified, "повторно відкритий файл -- без змін")
        # повернення до початкового -> зірочка зникає, журнал порожній
        doc3 = D.from_backup(src)
        c = next(c for c in doc3.view().contacts() if c[0] - 1 == slot)
        doc3.edit_contacts([{"op": "edit", "slot": slot, "expect_name": c[4], "name": "Тимч", "id": None, "type": None}])
        c = next(c for c in doc3.view().contacts() if c[0] - 1 == slot)
        doc3.edit_contacts([{"op": "edit", "slot": slot, "expect_name": c[4], "name": raw[1], "id": None, "type": None}])
        check(not doc3.modified and doc3.changes == [], "правку повернуто назад: зірочки й змін нема")
        # «Відкинути зміни»
        doc3.edit_contacts([{"op": "add", "name": "Новий", "id": 77, "type": 0}])
        before = snap(doc3)
        check(doc3.discard() and not doc3.modified and snap(doc3) != before, "«Відкинути зміни» повертає початковий стан")
        check(snap(doc3) == snap(D.from_backup(src)), "після відкидання образ байт-у-байт початковий")
        check(not doc3.discard(), "відкидати нічого -- False")
        # відкидання повертає до ОСТАННЬОГО збереження, а не до початку
        doc4 = D.from_backup(src)
        doc4.edit_basic(callsign="R2ABC")
        doc4.save_as(os.path.join(d, "s4.zip"))
        doc4.edit_basic(dmr_id=2500999)
        check(doc4.modified and len(doc4.changes) == 2, "після збереження нова правка знову дає зірочку")
        doc4.discard()
        check(doc4.view().callsign() == "R2ABC" and doc4.view().dmr_id() == 2504012 and not doc4.modified, "відкидання -> стан збереження (позивний лишився)")


def test_csv_roundtrip_and_errors():
    doc, spi, data = fixture_doc()
    with tempfile.TemporaryDirectory() as d:
        paths = doc.export_csv(d, ",", log=lambda *_: None)
        check(len(paths) == 6, "шість CSV з документа")
        base = snap(doc)
        res = doc.import_csv(cc.read_dir(d), ",")
        check(not res.any_change() and snap(doc) == base and not doc.modified, "експорт -> імпорт того самого CSV: образ байт-у-байт той самий")
        # документ ПІСЛЯ правок: експорт відображає документ, а не рацію/файл
        doc.edit_basic(callsign="R2ABC")
        doc.edit_contacts([{"op": "add", "name": "Київ", "id": 2550, "type": 0}])
        d2 = os.path.join(d, "two")
        doc.export_csv(d2, ",", log=lambda *_: None)
        rows = tc.read_csv_rows(os.path.join(d2, "Contacts.csv"))
        check(any("Київ" in r for r in rows), "CSV з документа містить правку, зроблену у вікні")
        # імпорт у ІНШИЙ документ дає той самий образ
        other, _s, _d = fixture_doc()
        other.import_csv(cc.read_dir(d2), ",")
        check(any(c[1] == "Київ" for c in other.view().contacts()) and other.modified, "імпорт у документ змінює документ (зірочка)")
        # зміна в CSV -> змінюється документ, рація/файл не чіпається, відкидання повертає
        d3 = os.path.join(d, "three")
        os.makedirs(d3)
        base3 = snap(other)
        for fn in os.listdir(d2):
            with open(os.path.join(d2, fn), "rb") as src, open(os.path.join(d3, fn), "wb") as dst:
                dst.write(src.read())
        rows = tc.read_csv_rows(os.path.join(d3, "Contacts.csv"))
        hdr = rows[0]
        name_col = hdr.index("Contact Name")
        check(name_col == 0, "перша колонка Contacts.csv -- Contact Name")
        rows[1][hdr.index("ID")] = "9999"
        tc.write_csv_rows(os.path.join(d3, "Contacts.csv"), rows)
        r = other.import_csv(cc.read_dir(d3), ",")
        check(r.any_change() and snap(other) != base3 and any(c[2] == 9999 for c in other.view().contacts()), "CSV зі зміненим ID -> документ змінено")
        other.discard()
        check(not other.modified, "«Відкинути зміни» після імпорту CSV")
        # R6.3: CSV з ПОМИЛКОЮ -> документ не змінено
        bad = os.path.join(d, "bad")
        os.makedirs(bad)
        for fn in os.listdir(d2):
            with open(os.path.join(d2, fn), "rb") as src, open(os.path.join(bad, fn), "wb") as dst:
                dst.write(src.read())
        zr = tc.read_csv_rows(os.path.join(bad, "Zones.csv"))
        zr[1][1] = "Неіснуючий канал"
        tc.write_csv_rows(os.path.join(bad, "Zones.csv"), zr)
        cr_rows = tc.read_csv_rows(os.path.join(bad, "Channels.csv"))
        cr_rows[1][cr_rows[0].index("Rx Frequency")] = "не число"
        tc.write_csv_rows(os.path.join(bad, "Channels.csv"), cr_rows)
        before, ch_before, rev = snap(other), list(other.changes), other.revision
        try:
            other.import_csv(cc.read_dir(bad), ",")
            check(False, "CSV з помилками мав бути відхилений")
        except cc.CsvImportRefused as e:
            check(len(e.problems) >= 2, "усі проблеми одним списком (%d)" % len(e.problems))
        check(snap(other) == before and other.changes == ch_before and other.revision == rev, "R6.3: після відмови документ не змінено (образ, журнал, ревізія)")


# ----------------------------------------------------------------------------------------
#  Основна інформація й APRS-слоти
# ----------------------------------------------------------------------------------------

def test_basic_info():
    doc, _s, _d = fixture_doc()
    b = ced.basic_values(doc.image)
    check(b["callsign"] == "UR5ABC" and b["dmr_id"] == 2504012, "початкові значення: %r" % b)
    check(doc.edit_basic(callsign="uw5elk", dmr_id=2500123, line1="Привіт", line2="UA"), "основну інформацію змінено")
    b = ced.basic_values(doc.image)
    check(b["callsign"] == "UW5ELK" and b["dmr_id"] == 2500123 and b["line1"] == "Привіт" and b["line2"] == "UA", "нові значення: %r" % b)
    check(bytes(doc.image.ee(cl.CP_ADDR_USER_CALLSIGN, 8)) == b"UW5ELK\xff\xff", "позивник: 8 байтів з дописаними 0xFF")
    check(bytes(doc.image.ee(cl.CP_ADDR_USER_DMRID, 4)) == bytes.fromhex("02500123"), "DMR ID: BCD, старший спершу")
    check(len(doc.image.ee(ced.ADDR_BOOT_LINE1, 16)) == 16 and doc.image.ee(ced.ADDR_BOOT_LINE2, 16)[2:] == b"\xff" * 14, "рядки вітання: по 16 Б з 0xFF")
    check(doc.edit_basic(callsign="UW5ELK", dmr_id=2500123) is False, "те саме значення -- змін немає")
    snap0, rev = snap(doc), doc.revision
    for kw, what in (({"callsign": "TOOLONG1"}, "позивний"), ({"callsign": "UW-5"}, "позивний"), ({"dmr_id": 0}, "DMR ID"),
                     ({"dmr_id": ced.DMR_ID_MAX + 1}, "DMR ID"), ({"line1": "Х" * 17}, "рядок"), ({"line1": "日本語😀"}, "рядок")):
        try:
            doc.edit_basic(**kw)
            check(False, "%r мало бути відмовою" % (kw,))
        except ced.CodeplugEditError as e:
            check(what in str(e), "відмова називає поле: %s" % e)
    try:
        doc.edit_basic(callsign="BAD-1", dmr_id=2500200)
    except ced.CodeplugEditError:
        pass
    check(snap(doc) == snap0 and doc.revision == rev, "відмова -- документ не змінено (навіть коректні поля поруч не застосовані)")


def test_aprs_slots():
    doc, _s, _d = fixture_doc()
    slots = doc.image.aprs()
    check(len(slots) == 1, "у фікстурі один APRS-слот")
    v = ced.aprs_values(slots[0][1])
    check(v["name"] == "APRS" and v["ssid"] == "7" and v["via1"] == "WIDE1" and v["use_position"] is True and v["comment"] == "TYT MD-UV390", "значення слота: %r" % v)
    raw0 = bytes(slots[0][1])
    v2 = dict(v, comment="Тест 1", ssid="9", baud300=True, silent=True, qsy=True, ambiguity="2", lat="50.4500", lon="30.5230", tx_freq="144.80000")
    v2["comment"] = "Test 1"
    check(doc.edit_aprs_slot(0, v2), "слот змінено")
    rec = dict(doc.image.aprs())[0]
    check(rec[8] == 9 and rec[61] & 0x01 and rec[61] & 0x08 and rec[61] & 0x04 and (rec[61] >> 5) == 2, "прапорці й неточність у байті 61: %02X" % rec[61])
    check(bytes(rec[31:55]).rstrip(b"\x00") == b"Test 1" and len(rec) == 64, "коментар у 24 байтах, довжина запису 64")
    check(struct_magic(rec) == cc.APRS_MAGIC, "сигнатура слота збережена")
    check([bytes(rec[i]) if False else rec[i] for i in range(62, 64)] == [raw0[62], raw0[63]], "сигнатура не змінилась")
    check(doc.changes[-1][1] == "APRS", "журнал: розділ APRS")
    # нескінченно довге й неправильне -> відмова, документ не змінено
    s0 = snap(doc)
    for bad in (dict(v2, ssid="99"), dict(v2, comment="x" * 25), dict(v2, ambiguity="8"), dict(v2, name=""), dict(v2, name="ДУЖЕДОВГАНАЗВА"),
                dict(v2, lat="95"), dict(v2, tx_freq="abc"), dict(v2, via1="TOOLONGV")):
        try:
            doc.edit_aprs_slot(0, bad)
            check(False, "%r мав бути відмовою" % (bad,))
        except ced.CodeplugEditError:
            pass
    check(snap(doc) == s0, "відмови не змінили документ")
    # новий слот у кінці
    nv = ced.new_aprs_values()
    nv["name"] = "ДОМ"
    check(doc.edit_aprs_slot(None, nv) and len(doc.image.aprs()) == 2, "новий слот став №2")
    try:
        doc.edit_aprs_slot(None, dict(nv))                  # така назва вже є
        check(False, "дубль назви мав бути відмовою")
    except ced.CodeplugEditError as e:
        check("уже є" in str(e), "дубль назви: %s" % e)
    # видалення: із середини не можна, з кінця можна
    try:
        doc.delete_aprs_slot(0)
        check(False, "видалення з середини мало бути відмовою")
    except ced.CodeplugEditError as e:
        check("з середини" in str(e), "видалення з середини: %s" % e)
    check(doc.delete_aprs_slot(1) and len(doc.image.aprs()) == 1, "видалено останній слот")
    check(bytes(doc.image.ee(cc.ADDR_APRS + cc.APRS_SIZE, cc.APRS_SIZE)) == b"\xff" * 64, "слот №2 стертий 0xFF")
    # таблиця у перегляді відповідає
    tabs = {k: (c, r) for k, _t, c, r in doc.tables()}
    check("aprs" in tabs and "dtmf" in tabs and len(tabs["aprs"][1]) == 1 and tabs["aprs"][1][0][1] == "APRS", "таблиці APRS і DTMF у перегляді")
    # CSV з документа і назад для APRS
    with tempfile.TemporaryDirectory() as d:
        doc.export_csv(d, ",", log=lambda *_: None)
        s1 = snap(doc)
        doc.import_csv(cc.read_dir(d), ",")
        check(snap(doc) == s1, "APRS після правок: CSV туди й назад -- образ той самий")


def struct_magic(rec):
    return rec[62] | (rec[63] << 8)


# ----------------------------------------------------------------------------------------
#  Запис: злиття, відновлення, заборони
# ----------------------------------------------------------------------------------------

def test_merge():
    o = cc.Image(bytes(8192), bytes(4096), 0x1000)
    cur = cc.Image(bytes(o.eeprom), bytes(o.flash), 0x1000)
    cur.eeprom[10] = 1
    cur.eeprom[5000] = 2
    fresh = cc.Image(bytes(o.eeprom), bytes(o.flash), 0x1000)
    fresh.eeprom[100] = 9                  # рація змінила інше місце -- лишається
    fresh.eeprom[5000] = 7                 # і те саме, що змінили ви -- конфлікт
    merged, conflicts = D.merge(o, cur, fresh)
    check(merged.eeprom[10] == 1 and merged.eeprom[100] == 9 and merged.eeprom[5000] == 2 and conflicts == 1,
          "злиття: ваша правка + зміна рації; конфлікт 1 (є %d)" % conflicts)
    try:
        D.merge(o, cur, cc.Image(bytes(10), bytes(4096), 0x1000))
        check(False, "інший розмір рації -- відмова")
    except D.DocumentError:
        pass


def test_write_from_radio_doc():
    """Документ з рації: рація встигла змінити «лічильники» (0x607F) -- запис НЕ затирає їх; калібрування не чіпається; C 6 1."""
    spi = tc.make_fixture_spi()
    spi[0x10000:0x10010] = b"CALIB-A-CALIB-A!"
    with tempfile.TemporaryDirectory() as d:
        radio = ClosableRadio(bytearray(spi))
        doc = D.from_radio(cl.CpsLink(radio, retries=0))
        check(doc.origin == D.ORIGIN_RADIO and not doc.modified, "відкрито з рації: без зірочки")
        check(doc.write_block_reason() == "Змін для запису немає: документ збігається зі станом рації.", "без змін запис не пропонується: %s" % doc.write_block_reason())
        doc.edit_contacts([{"op": "add", "name": "Київ", "id": 2550, "type": 0}])
        doc.edit_aprs_slot(0, dict(ced.aprs_values(doc.image.aprs()[0][1]), comment="Hello"))
        doc.edit_basic(callsign="R2ABC")
        check(doc.write_block_reason() is None, "з правками запис дозволено")
        radio.spi[0x607F] ^= 0x03                                     # рація сама змінила лічильник після читання
        drift_byte = radio.spi[0x607F]
        fresh = cc.Image.from_codeplug(cv.codeplug_from_radio(cl.CpsLink(radio, retries=0))[0])
        res, conflicts = doc.write_image(fresh)
        check(conflicts == 0 and res.image.eeprom[0x607F] == drift_byte, "образ для запису бере лічильник зі свіжого читання, а не зі старого документа")
        texts = []
        with tr.Unlocked():
            out = cc.write_image_via_restore(cl.CpsLink(radio, retries=0), res, lambda t, p: texts.append(t) or True, log=lambda *_: None,
                                             title="ТЕСТ", out_dir=d, zip_prefix="codeplug_document-write")
        check(out["sectorsWritten"] >= 1 and radio.c_calls[-1] == bytes([6, 1]), "записано шляхом відновлення, C 6 1 останньою")
        check(not radio.cal_touched and bytes(radio.spi[0x10000:0x10010]) == b"CALIB-A-CALIB-A!", "калібрування не чіпали")
        check(bytes(radio.spi[0x607F:0x6080]) == bytes([drift_byte]), "лічильник рації (0x607F) не затерто")
        check("Київ" in texts[0] and "R2ABC" in texts[0] and "APRS" in texts[0], "діалог підтвердження показує список змін документа")
        check(any(f.startswith("codeplug_document-write") for f in os.listdir(d)) and any("pre-restore" in f for f in os.listdir(d)),
              "лежать файл «що записали» і страхова копія")
        cp2, _m = cv.codeplug_from_radio(cl.CpsLink(radio, retries=0))
        check(cp2.callsign() == "R2ABC" and any(c[1] == "Київ" for c in cp2.contacts()), "у рації: позивний і контакт")
        doc.mark_written(res.image)
        check(not doc.modified and doc.origin == D.ORIGIN_RADIO and doc.changes == [], "після запису документ без змін, джерело -- рація")
        check(doc.write_block_reason() is not None, "після запису знову нічого писати")


def test_write_from_file_doc():
    doc, spi, _d = fixture_doc()
    doc.edit_basic(callsign="R2ABC")
    other = tc.make_fixture_spi()
    other[0x607F] = 0x55                                               # інша рація: інші налаштування
    other[0x10000:0x10010] = b"CALIB-B-CALIB-B!"
    with tempfile.TemporaryDirectory() as d:
        radio = ClosableRadio(bytearray(other))
        res, conflicts = doc.write_image(None)
        check(conflicts == 0 and any("відкрито з файла" in w for w in res.warnings), "документ з файла: попередження, що рація стане як файл")
        with tr.Unlocked():
            out = cc.write_image_via_restore(cl.CpsLink(radio, retries=0), res, lambda t, p: True, log=lambda *_: None, out_dir=d,
                                             zip_prefix="codeplug_document-write")
        check(out["sectorsWritten"] >= 1, "записано з файла-документа")
        check(bytes(radio.spi[0x10000:0x10010]) == b"CALIB-B-CALIB-B!", "калібрування цієї рації лишилось власним")
        cp2, _m = cv.codeplug_from_radio(cl.CpsLink(radio, retries=0))
        check(cp2.callsign() == "R2ABC", "у рації позивний з документа")


def test_write_refusals():
    doc, spi, _d = fixture_doc()
    doc.manifest["radio"]["radioType"] = 5            # бекап від MD-9600
    reason = doc.write_block_reason()
    check(reason and "іншої моделі" in reason, "документ з іншої моделі: запис заборонено з причиною: %s" % reason)
    doc2, _s, _d2 = fixture_doc()
    info = {"radioType": 6, "structVersion": 9, "gitRevision": "x"}
    r2 = doc2.write_block_reason(info)
    check(r2 and "structVersion" in r2, "не збігається версія структури: %s" % r2)
    # блокування: документ нічого не пише, restore відмовляє ДО трафіку
    doc2.edit_basic(callsign="R2ABC")
    with tempfile.TemporaryDirectory() as d:
        radio = ClosableRadio(bytearray(spi))
        res, _c = doc2.write_image(None)
        with tr.Locked():
            try:
                cc.write_image_via_restore(cl.CpsLink(radio, retries=0), res, lambda t, p: True, log=lambda *_: None, out_dir=d)
                check(False, "заблоковано -- відмова")
            except cl.CpsError as e:
                check("BK8" in str(e), "блокування: %s" % e)
        check(radio.x_total == 0, "при блокуванні жодної X-команди")
    # скасування в діалозі -- нічого не записано, документ як був
    with tempfile.TemporaryDirectory() as d:
        radio = ClosableRadio(bytearray(spi))
        res, _c = doc2.write_image(None)
        with tr.Unlocked():
            out = cc.write_image_via_restore(cl.CpsLink(radio, retries=0), res, lambda t, p: False, log=lambda *_: None, out_dir=d)
        check(out.get("cancelled") and radio.x_total == 0, "скасовано в діалозі: жодної X-команди")
        check(doc2.modified, "після скасування документ лишається зміненим")


# ----------------------------------------------------------------------------------------
#  GUI (R6.4 + питання про зміни + повний запис через вікно)
# ----------------------------------------------------------------------------------------

def _spin(app, seconds=0.5):
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.02)


def _wait_idle(app, limit=15):
    end = time.time() + limit
    while time.time() < end:
        app.update()
        if not app.busy:
            return True
        time.sleep(0.02)
    return False


def test_gui():
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("ПРОПУЩЕНО (GUI): нема tkinter")
        return
    if not os.environ.get("DISPLAY"):
        print("ПРОПУЩЕНО (GUI): нема DISPLAY (xvfb-run -a python3 tools/test_cps_doc.py)")
        return
    from cps_ui.app import CpsApp
    from cps_ui.settings import Settings
    import cps_ui.doc_actions as da
    import gui_dialogs as gd
    import tkinter.messagebox as mb
    from tkinter import filedialog

    tmp = tempfile.mkdtemp(prefix="cpsdoc_")
    spath = os.path.join(tmp, "ui.json")
    os.environ["TYT_CPS_SETTINGS"] = spath
    os.environ["HOME"] = tmp                                            # output_dir() не повинен писати в справжню домашню теку
    app = CpsApp(settings=Settings(spath), autoprobe=False)
    infos, errors = [], []
    orig = (mb.showinfo, mb.showerror, gd.confirm_dialog, gd.choice_dialog, gd.text_dialog, filedialog.askopenfilename, filedialog.asksaveasfilename,
            da.messagebox.showinfo, da.messagebox.showerror)
    mb.showinfo = lambda *a, **k: infos.append(a)
    mb.showerror = lambda *a, **k: errors.append(a)
    gd.text_dialog = lambda *a, **k: infos.append(a)
    try:
        app.update()
        # --- порожній документ: КОЖНА панель показує підказку або вимкнена, без винятків ---
        check(app.title() == "TYT MD-UV390UKR" and "не відкрито" in app.doc_label.cget("text"), "порожній документ: заголовок без назви, у стані «не відкрито»")
        for key in app.section_keys():
            app.show(key)
            app.update()
        v = app.get_panel("viewer")
        check(v.viewer is None and "Відкрийте кодплаг" in v.placeholder.cget("text"), "перегляд без документа: підказка «Відкрийте кодплаг з рації або з бекапу»")
        for key in ("csv", "basic", "aprs"):
            p = app.get_panel(key)
            p = getattr(p, "station", p)         # APRS: підказка живе в блоці «Станція (слоти)»
            check(p.hint.winfo_manager() == "pack", "%s: підказка «Відкрийте кодплаг…» без документа" % key)
        check(str(app.get_panel("csv").csv_export_button.cget("state")) == "disabled" and str(app.get_panel("csv").csv_import_button.cget("state")) == "disabled",
              "CSV без документа: кнопки вимкнені")
        check(all(str(app.docbtn[k].cget("state")) == "disabled" for k in ("save_as", "write", "discard")), "без документа: «Зберегти як / Записати / Відкинути» вимкнені")

        # --- відкрити з бекапу ---
        spi = tc.make_fixture_spi()
        _cp, data = tc.codeplug_of(spi)
        src = os.path.join(tmp, "orig.zip")
        with open(src, "wb") as f:
            f.write(data)
        check(app.doc_open_file(src) and app.doc is not None and app.title().startswith("orig.zip"), "відкрито з бекапу: заголовок із назвою файла, без зірочки")
        check(app.doc_label.cget("text").endswith("без змін"), "рядок стану документа: без змін")
        for key in app.section_keys():
            app.show(key)
            app.update()
        check(len(app.get_panel("viewer").viewer.contact_tree.get_children()) == 4, "перегляд показує контакти з документа")
        nb_titles = [app.get_panel("viewer").viewer.nb.tab(t, "text") for t in app.get_panel("viewer").viewer.nb.tabs()]
        check(len(nb_titles) == 6 and nb_titles[4].startswith("APRS") and nb_titles[5].startswith("DTMF"), "перегляд має шість вкладок, зокрема APRS і DTMF: %r" % nb_titles)

        # --- BY2: правка -> зірочка -> «Відкинути зміни» ---
        app.show("basic")
        bp = app.get_panel("basic")
        bp.vars["callsign"].set("R2ABC")
        app.update()
        check(str(bp.apply_button.cget("state")) == "normal", "основна інформація: «Застосувати» доступна після правки")
        bp._on_apply()
        app.update()
        check(app.title().startswith("*orig.zip") and "ЗМІНЕНО" in app.doc_label.cget("text"), "зірочка в заголовку й у рядку стану: %r" % app.title())
        check(str(app.docbtn["discard"].cget("state")) == "normal", "«Відкинути зміни» доступна")
        gd.confirm_dialog = lambda *a, **k: True
        check(app.doc_discard() and not app.doc.modified and bp.vars["callsign"].get() == "UR5ABC", "«Відкинути зміни»: зірочки нема, поле повернулось")

        # --- APRS-слоти: форма -> документ ---
        app.show("aprs")
        ap = app.get_panel("aprs").station
        app.update()
        check(len(ap.tree.get_children()) == 1 and ap.vars["name"].get() == "APRS", "APRS-слоти: список і форма з документа")
        ap.vars["comment"].set("Hello from test")
        app.update()
        check(str(ap.apply_button.cget("state")) == "normal", "APRS: «Застосувати» після правки")
        ap.vars["ssid"].set("99")
        app.update()
        check(str(ap.apply_button.cget("state")) == "disabled" and "SSID" in ap.msg.cget("text"), "APRS: SSID 99 -- відмова з поясненням (%s)" % ap.msg.cget("text"))
        ap.vars["ssid"].set("7")
        app.update()
        ap._on_apply()
        check(app.doc.modified and dict(app.doc.image.aprs())[0][31:46].startswith(b"Hello from tes"), "APRS: коментар у документі")
        ap._on_new()
        app.update()
        ap.vars["name"].set("ДОМ")
        app.update()
        check(str(ap.apply_button.cget("state")) == "normal", "APRS: новий слот можна застосувати")
        ap._on_apply()
        check(len(app.doc.image.aprs()) == 2 and len(ap.tree.get_children()) == 2, "APRS: новий слот з'явився у списку")

        # --- BY6: імпорт CSV у документ, рація не чіпається ---
        csvdir = os.path.join(tmp, "csv_out")
        app.doc.export_csv(csvdir, ",", log=lambda *_: None)
        rows = tc.read_csv_rows(os.path.join(csvdir, "Contacts.csv"))
        rows[1][rows[0].index("ID")] = "31337"
        tc.write_csv_rows(os.path.join(csvdir, "Contacts.csv"), rows)
        cp_ = app.get_panel("csv")
        cp_.csv_decimal_var.set("кома")
        res = cp_.import_folder(csvdir)
        check(res is not None and res.any_change() and any(c[2] == 31337 for c in app.doc.view().contacts()), "CSV імпортовано у документ")
        app.show("viewer")
        app.update()
        ids = [str(app.get_panel("viewer").viewer.contact_tree.item(i)["values"][2]) for i in app.get_panel("viewer").viewer.contact_tree.get_children()]
        check("31337" in ids, "таблиця перегляду оновилась одразу після імпорту: %r" % ids)

        # --- BY7: питання про незбережені зміни ---
        asked = []
        gd.choice_dialog = lambda parent, title, text, buttons, default=0: (asked.append(text), "cancel")[1]
        check(app.confirm_leave_document("закрити програму") is False and asked, "незбережені зміни: «Скасувати» -- лишаємось")
        gd.choice_dialog = lambda *a, **k: "drop"
        check(app.confirm_leave_document("закрити програму") is True, "«Не зберігати» -- можна йти")
        out_zip = os.path.join(tmp, "saved_via_dialog.zip")
        filedialog.asksaveasfilename = lambda **k: out_zip
        gd.choice_dialog = lambda *a, **k: "save"
        check(app.confirm_leave_document("відкрити інший кодплаг") is True and os.path.exists(out_zip) and not app.doc.modified,
              "«Зберегти як…» з питання: файл створено, зірочки нема")
        # відкрити інший документ при незбережених змінах -- питання
        app.doc.edit_basic(callsign="R2XYZ")
        asked.clear()
        gd.choice_dialog = lambda parent, title, text, buttons, default=0: (asked.append(text), "cancel")[1]
        check(app.doc_open_file(src) is False and asked and app.doc.view().callsign() == "R2XYZ", "відкриття іншого документа при змінах питає й скасовується")
        # закриття вікна при змінах: «Скасувати» -- вікно лишається
        closed = []
        orig_destroy = app.destroy
        app.destroy = lambda: closed.append(1)
        app._on_close()
        check(not closed and asked, "закриття вікна при змінах питає; «Скасувати» -- вікно лишилось")
        gd.choice_dialog = lambda *a, **k: "drop"
        app._on_close()
        check(closed == [1], "«Не зберігати» -- вікно закривається")
        app.destroy = orig_destroy
        app.doc_discard()

        # --- BY4/BY5: запис через вікно (підставна рація) ---
        radio = ClosableRadio(bytearray(spi))
        old_open = cl.open_radio
        cl.open_radio = lambda *a, **k: radio
        old_out = da.output_dir
        da.output_dir = lambda: tmp
        try:
            app.conn.state, app.conn.port, app.conn.searched = "found", "TEST", True
            app.conn.info = {"radioType": 6, "structVersion": 3, "gitRevision": "abc1234"}
            app._refresh_all()
            # docbar: блокування -> підпис біля кнопки
            old_lock = cr.RESTORE_UNLOCKED
            cr.RESTORE_UNLOCKED = False
            app._refresh_all()
            check(str(app.docbtn["write"].cget("state")) == "disabled" and cr.LOCKED_CAPTION in app.docbar_note.cget("text"), "блокування: підпис біля кнопки запису")
            cr.RESTORE_UNLOCKED = True
            # інша модель -> запис заборонено з причиною
            app.doc.manifest["radio"]["radioType"] = 5
            app._refresh_all()
            check(str(app.docbtn["write"].cget("state")) == "disabled" and "іншої моделі" in app.docbar_note.cget("text"), "документ іншої моделі: запис вимкнено з причиною")
            app.doc.manifest["radio"]["radioType"] = 6
            app.doc.edit_contacts([{"op": "add", "name": "Київ", "id": 2550, "type": 0}])
            app._refresh_all()
            check(str(app.docbtn["write"].cget("state")) == "normal", "рація є, не заблоковано, модель та сама: «Записати в рацію» доступна")
            shown = []
            gd.confirm_dialog = lambda parent, title, text, yes="Так", no="Ні": (shown.append(text), True)[1]
            check(app.doc_write(), "запис стартував")
            check(_wait_idle(app), "запис завершився")
            check(shown and "Київ" in shown[0] and "ЗАПИС КОДПЛАГА З ДОКУМЕНТА" in shown[0], "діалог підтвердження: заголовок і список змін")
            check(not app.doc.modified and app.doc.origin == "radio" and not app.title().startswith("*"), "після запису документ без змін, джерело -- рація")
            cp2, _m = cv.codeplug_from_radio(cl.CpsLink(radio, retries=0))
            check(any(c[1] == "Київ" for c in cp2.contacts()), "у (підставній) рації з'явився контакт")
            check(radio.c_calls and radio.c_calls[-1] == bytes([6, 1]), "після запису C 6 1")
            check(any("pre-restore" in f for f in os.listdir(tmp)), "страхова копія лежить поруч")
            cr.RESTORE_UNLOCKED = old_lock
        finally:
            cl.open_radio = old_open
            da.output_dir = old_out
        # «Відкрити з рації» через вікно
        cl.open_radio = lambda *a, **k: radio
        try:
            check(app.doc_open_radio() and _wait_idle(app) and app.doc.origin == "radio" and "рація" in app.doc.label(), "«Відкрити з рації»: документ з рації")
            check(any(c[1] == "Київ" for c in app.doc.view().contacts()) and not app.doc.modified, "документ з рації містить записане, без зірочки")
        finally:
            cl.open_radio = old_open
        # закрити документ
        app.set_document(None)
        for key in app.section_keys():
            app.show(key)
            app.update()
        check(app.title() == "TYT MD-UV390UKR" and app.get_panel("viewer").viewer is None, "документ закрито: порожні панелі з підказкою")
        check(not errors, "несподіваних вікон помилок не було: %r" % (errors,))
    finally:
        (mb.showinfo, mb.showerror, gd.confirm_dialog, gd.choice_dialog, gd.text_dialog, filedialog.askopenfilename, filedialog.asksaveasfilename) = orig[:7]
        app.destroy()


def main():
    for t in (test_open_edit_save_reopen, test_csv_roundtrip_and_errors, test_basic_info, test_aprs_slots, test_merge, test_write_from_radio_doc,
              test_write_from_file_doc, test_write_refusals, test_gui):
        try:
            t()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILS.append("%s: виняток %r" % (t.__name__, e))
    if FAILS:
        print("test_cps_doc: ПРОВАЛЕНО перевірок: %d" % len(FAILS))
        return 1
    print("test_cps_doc: усі перевірки пройшли (відкрити/змінити/зберегти/відкрити, CSV туди й назад, помилка CSV, основна інформація, APRS-слоти, "
          "злиття й запис, заборони, вікно).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
