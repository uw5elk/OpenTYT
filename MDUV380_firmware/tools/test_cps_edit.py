#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Хост-тест CPS-fix2 + етап 3: редактори списків прийому / зон / каналів (tools/table_edit.py, cps_ui/editor_base.py, p_*.py) і дрібниці вікна.

U1  створити канал / зону / список у документі -> експорт CSV -> у CSV усе на місці;
U2  імпорт CSV -> редактор показує те саме, що в CSV;
U3  видалення запису з посиланнями: без підтвердження нічого не змінюється; «видалити разом із посиланнями» прибирає й посилання;
U4  межі: 33-й контакт у списку і (limit+1)-й канал у зоні не додаються, із поясненням;
U5  відкрити з бекапа -> нічого не чіпати (навіть обійти всі редактори й усі поля) -> зберегти -> ДАНІ (eeprom.bin, flash.bin) ті самі байт-у-байт;
U6  smoke під xvfb: кожен редактор відкривається з відкритим і з порожнім документом;
S1  позивний: у «APRS: бікон» лише перегляд, редагування -- лише в «Основній інформації»; S2 смуга прокрутки лише за потреби; S3 пояснення DFU під «Оновити».
Плюс: ТЕ САМЕ правило, що в імпорті CSV (кодування назв, унікальність, межі полів, посилання за назвами / «#N» для однакових назв, слоти R26).

GUI-частина потребує tkinter і DISPLAY (`xvfb-run -a python3 tools/test_cps_edit.py`).
"""
import csv
import os
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cps_link as cl                # noqa: E402
import cps_csv as cc                 # noqa: E402
import contact_edit as ce            # noqa: E402
import table_edit as te              # noqa: E402
import test_cps_csv as tc            # noqa: E402
import test_cps_restore as tr        # noqa: E402
from cps_ui import document as D     # noqa: E402

FAILS = []
DP = ","


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def fixture_doc(origin=D.ORIGIN_FILE):
    spi = tc.make_fixture_spi()
    cp, data = tc.codeplug_of(spi)
    return D.Document(cp, origin, source_file="фікстура.zip"), spi, data


def snap(doc):
    return bytes(doc.image.eeprom), bytes(doc.image.flash)


def refused(fn, *a, **k):
    try:
        fn(*a, **k)
    except te.TableEditError as e:
        return e
    return None


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, delimiter=";"))
    return rows[0], rows[1:]


# ----------------------------------------------------------------------------------------
#  Каркас
# ----------------------------------------------------------------------------------------

def test_export_rows_same_as_files():
    """Рефакторинг експорту: export_rows дає ті самі рядки, що пишуться у файли (формат CSV не змінено)."""
    _doc, spi, _d = fixture_doc()
    cp, _ = tc.codeplug_of(spi)
    img = cc.Image.from_codeplug(cp)
    with tempfile.TemporaryDirectory() as d:
        cc.export_files(img, d, DP, log=lambda *_: None)
        rows = cc.export_rows(img, DP)
        for key, fname in cc.FILE_NAMES.items():
            hdr, body = read_csv(os.path.join(d, fname))
            check(hdr == rows[key][0] and body == rows[key][1], "export_rows == файл %s" % fname)


def test_tg_lists():
    doc, _s, _d = fixture_doc()
    img = doc.image
    check(te.tg_lists(img) == [(0, "Ukraine", [1, 2, 3]), (4, "Група", [2])], "переліку списків: %r" % te.tg_lists(img))
    # склад і порядок
    res = te.set_members(img, "tg", 0, [3, 2, 1], DP)
    check(doc.apply(res) and te.tg_lists(doc.image)[0] == (0, "Ukraine", [3, 2, 1]), "порядок контактів у списку змінено")
    check([c[0] for c in te.tg_lists(doc.image)] == [0, 4], "інші списки на своїх слотах")
    # новий список бере слот, що ніколи не був зайнятий (T0.6)
    res = te.add_entity(doc.image, "tg", "My list", [1, 3], DP)
    doc.apply(res)
    names = {n: (s, m) for s, n, m in te.tg_lists(doc.image)}
    check(names["My list"] == (1, [1, 3]), "новий список -- у вільному слоті 1 (ніколи не займаному): %r" % names)
    # перейменування лишає слот
    doc.apply(te.rename_entity(doc.image, "tg", 1, "List 2", DP))
    check(dict((s, n) for s, n, _m in te.tg_lists(doc.image))[1] == "List 2", "перейменування: слот лишився")
    # дублікат назви
    e = refused(te.rename_entity, doc.image, "tg", 1, "Ukraine", DP)
    check(e is not None and "уже є" in str(e), "дубль назви відхилено: %s" % e)
    # копія
    res = te.duplicate_entity(doc.image, "tg", 0, DP)
    doc.apply(res)
    check("Ukraine 2" in [n for _s, n, _m in te.tg_lists(doc.image)], "копія «Ukraine 2»")
    # порожній список не створюється
    e = refused(te.add_entity, doc.image, "tg", "Empty", [], DP)
    check(e is not None and "порожн" in str(e), "порожній список відхилено: %s" % e)
    e = refused(te.set_members, doc.image, "tg", 0, [], DP)
    check(e is not None and "порожн" in str(e), "склад не можна спорожнити (є «Видалити»)")
    # неіснуючий контакт
    e = refused(te.set_members, doc.image, "tg", 0, [1, 99], DP)
    check(e is not None and "нема записів" in str(e), "неіснуючий контакт відхилено: %s" % e)
    # двічі той самий
    e = refused(te.set_members, doc.image, "tg", 0, [1, 1], DP)
    check(e is not None and "двічі" in str(e), "той самий контакт двічі відхилено")


def test_zones():
    doc, _s, _d = fixture_doc()
    before = {b: (n, m) for b, n, m in te.zones(doc.image)}
    res = te.set_members(doc.image, "zone", 0, [3, 1, 130], DP)
    doc.apply(res)
    after = {b: (n, m) for b, n, m in te.zones(doc.image)}
    check(after[0][1] == [3, 1, 130], "порядок каналів у зоні: %r" % (after[0],))
    check(all(after[b] == before[b] for b in before if b != 0), "інші зони не чіпаємо")
    # один канал у кількох зонах -- нормально
    doc.apply(te.add_entity(doc.image, "zone", "Dup chans", [1, 2], DP))
    z = {n: m for _b, n, m in te.zones(doc.image)}
    check(z["Dup chans"] == [1, 2] and 1 in z["Київ"], "той самий канал у двох зонах дозволено")
    # лічильник і ліміт
    check(te.zone_limit(doc.image) in (16, 80), "ліміт зони з документа: %r" % te.zone_limit(doc.image))


def test_channels_edit():
    doc, _s, _d = fixture_doc()
    img = doc.image
    v = te.channel_values(img, 1, DP)
    check(v["Channel Type"] == "Digital" and v["Colour Code"] == "3" and v["Timeslot"] == "2", "значення форми цифрового каналу: %r" % {k: v[k] for k in ("Channel Type", "Colour Code")})
    check(v["Bandwidth (kHz)"] == "" and v["RX Tone"] == "", "аналогові поля цифрового каналу порожні")
    v2 = te.channel_values(img, 2, DP)
    check(v2["Channel Type"] == "Analogue" and v2["Colour Code"] == "" and v2["Squelch"] != "", "аналоговий канал: цифрові поля порожні")
    # частота з комою й крапкою дають однаковий результат
    ra = te.channel_edit(img, 2, {"Rx Frequency": "433,5"}, DP)
    rb = te.channel_edit(img, 2, {"Rx Frequency": "433.5"}, DP)
    check(bytes(ra.image.eeprom) == bytes(rb.image.eeprom) and bytes(ra.image.flash) == bytes(rb.image.flash), "433,5 == 433.5")
    doc.apply(ra)
    check(te.channel_values(doc.image, 2, DP)["Rx Frequency"] == "433,50000", "RX показується за десятковим знаком: %s" % te.channel_values(doc.image, 2, DP)["Rx Frequency"])
    # відмови -- ті самі правила, що в імпорті CSV
    for col, text, frag in (("Rx Frequency", "abc", "не число"), ("Bandwidth (kHz)", "7", "12,5 або 25"), ("Colour Code", "16", "0..15"),
                            ("RX Tone", "5", "CTCSS"), ("Power", "99 kW", "потужн")):
        ch = 2 if col in ("Bandwidth (kHz)", "RX Tone") else 1
        e = refused(te.channel_edit, doc.image, ch if col != "Colour Code" else 1, {col: text}, DP)
        check(e is not None and frag in str(e), "%s=%r відхилено з поясненням (%s): %s" % (col, text, frag, e))
    # зміна типу: аналоговий -> цифровий отримує типові цифрові значення
    res = te.channel_edit(doc.image, 2, {"Channel Type": "Digital"}, DP)
    doc.apply(res)
    nv = te.channel_values(doc.image, 2, DP)
    check(nv["Channel Type"] == "Digital" and nv["Colour Code"] == "1" and nv["Timeslot"] == "1" and nv["Contact"] == "None", "тип -> цифровий: типові значення: %r" % nv)
    res = te.channel_edit(doc.image, 2, {"Channel Type": "Analogue"}, DP)
    doc.apply(res)
    check(te.channel_values(doc.image, 2, DP)["Channel Type"] == "Analogue", "тип назад на аналоговий")
    # посилання зі списку наявних
    opts = dict(te.ref_options(doc.image, "contact"))
    check(len(opts) == 4 and all(l.startswith("№") for l in opts.values()), "варіанти контактів: %r" % opts)
    res = te.channel_edit(doc.image, 1, {"Contact": te.ref_token(doc.image, "contact", 3)}, DP)
    doc.apply(res)
    check(te.channel_refs(doc.image, 1)["Contact"] == 3, "контакт каналу вибрано зі списку")
    res = te.channel_edit(doc.image, 1, {"Contact": "None", "TG List": te.ref_token(doc.image, "group", 5)}, DP)
    doc.apply(res)
    r = te.channel_refs(doc.image, 1)
    check(r["Contact"] == 0 and r["TG List"] == 5, "None і список прийому: %r" % r)
    e = refused(te.channel_edit, doc.image, 1, {"Contact": "Нема такого"}, DP)
    check(e is not None and "немає контакту" in str(e), "неіснуючий контакт відхилено: %s" % e)
    # новий канал
    n_before = len(doc.image.channels())
    res = te.channel_new(doc.image, "Test A", False, DP)
    doc.apply(res)
    new = [n for n, nm, _t, _r in te.channels(doc.image, DP) if nm == "Test A"]
    check(len(doc.image.channels()) == n_before + 1 and len(new) == 1, "новий аналоговий канал: %r" % new)
    nv = te.channel_values(doc.image, new[0], DP)
    check(nv["Channel Type"] == "Analogue" and nv["Rx Frequency"] == "145,50000", "типова частота нового каналу: %s" % nv["Rx Frequency"])
    res = te.channel_new(doc.image, "Test D", True, DP)
    doc.apply(res)
    nd = [n for n, nm, _t, _r in te.channels(doc.image, DP) if nm == "Test D"][0]
    check(te.channel_values(doc.image, nd, DP)["Channel Type"] == "Digital" and te.channel_values(doc.image, nd, DP)["Colour Code"] == "1", "новий цифровий канал")
    # дублювання
    res = te.duplicate_entity(doc.image, "channel", 1, DP)
    doc.apply(res)
    dup = [n for n, nm, _t, _r in te.channels(doc.image, DP) if nm.startswith("Папуга ")]
    check(len(dup) == 1, "копія каналу з номером: %r" % dup)
    a, b = te.channel_values(doc.image, 1, DP), te.channel_values(doc.image, dup[0], DP)
    same = all(a[k] == b[k] for k in a if k not in ("Channel Name", "Channel Number"))
    check(same, "копія збігається з оригіналом, крім назви й номера")
    # перейменування й назви
    doc.apply(te.rename_entity(doc.image, "channel", 2, "Ольга і Їжак", DP))
    check(te.channel_values(doc.image, 2, DP)["Channel Name"] == "Ольга і Їжак", "кирилиця з «і» в назві каналу")
    e = refused(te.rename_entity, doc.image, "channel", 2, "Дуже довга назва каналу що не влізе", DP)
    check(e is not None and "байт" in str(e), "задовга назва: %s" % e)
    e = refused(te.rename_entity, doc.image, "channel", 2, "Папуга", DP)
    check(e is not None and "уже є" in str(e), "дубль назви каналу відхилено")
    cp_name = te.unique_copy_name(doc.image, "channel", "ЇЖАК ҐЄІіїєґ")
    check(cp_name != "ЇЖАК ҐЄІіїєґ" and ce.check_name(cp_name)["ok"] and cp_name.endswith(" 2"), "назва копії вміщується в 16 байтів і закінчується « 2»: %r" % cp_name)


def test_aes_slot_warning():
    """DMR ID каналу ділить байти з AES-слотом (як у меню рації): зміна DMR ID скидає слот -- про це попереджаємо; інші правки слот не чіпають."""
    doc, _s, _d = fixture_doc()
    img = doc.image
    rec = bytearray(img.channel_rec(1))
    check(rec[cc.O_FLAG1L] & cc.FL_DMRID, "фікстура: канал №1 має власний DMR ID")
    rec[te.AES_UNUSED2_OFF] = 0xA3                       # слот 3 на каналі з власним DMR ID (мітка 0xA0)
    img.set_channel_rec(1, bytes(rec))
    check(te.aes_slot(img.channel_rec(1)) == 3, "aes_slot читає слот із _UNUSED_2")
    res = te.channel_edit(img, 1, {"Rx Frequency": "433,5"}, DP)
    check(not res.warnings and te.aes_slot(res.image.channel_rec(1)) == 3, "правка частоти слот AES не чіпає і не попереджає")
    res = te.channel_edit(img, 1, {"DMR ID": "None"}, DP)
    check(any("AES-слот" in w and "ключ 3" in w for w in res.warnings) and te.aes_slot(res.image.channel_rec(1)) == 0,
          "DMR ID -> None скидає слот і попереджає: %r" % res.warnings)
    res2 = te.channel_edit(img, 1, {"DMR ID": "2504012"}, DP)
    check(not res2.any_change(), "той самий DMR ID -- нічого не змінюється")


def _chan_rows(img):
    """Усі клітинки CSV-рядків каналів (як їх бачить експорт) -- для порівняння «що змінилося»."""
    hdr, rows = te.tables_of(img, DP)["channels"]
    return hdr, [list(r) for r in rows]


def test_aes_key_in_channel():
    """V3 / W2: ключ AES у каналі пишеться тим самим байтом, що читає прошивка; решта запису (зокрема DMR ID) і CSV-рядки не змінюються."""
    doc, _s, _d = fixture_doc()
    img = doc.image
    own = 1                                                                 # канал №1 -- цифровий, з власним DMR ID
    plain = [n for n, r in img.channels() if r[cc.O_MODE] != 0 and not (r[cc.O_FLAG1L] & cc.FL_DMRID)]
    analog = [n for n, r in img.channels() if r[cc.O_MODE] == 0]
    check(img.channel_rec(own)[cc.O_FLAG1L] & cc.FL_DMRID and plain and analog, "фікстура: є канал з DMR ID, цифровий без нього й аналоговий")
    plain = plain[0]
    for n in (plain, own):
        before_rec = img.channel_rec(n)
        before_hdr, before_rows = _chan_rows(img)
        res = te.channel_set_aes_slot(img, n, 7)
        after_rec = res.image.channel_rec(n)
        diff = [i for i in range(len(before_rec)) if before_rec[i] != after_rec[i]]
        want = te.AES_UNUSED2_OFF if n == own else te.AES_ENCRYPT_OFF
        check(diff == [want], "канал №%d: ключ 7 змінює лише байт %d, змінено %r" % (n, want, diff))
        check(te.aes_slot(after_rec) == 7, "канал №%d: прошивка (aes_slot) читає ключ 7" % n)
        hdr2, rows2 = _chan_rows(res.image)
        check(hdr2 == before_hdr and rows2 == before_rows, "канал №%d: CSV-рядки каналів після зміни ключа ті самі (DMR ID й решта полів цілі)" % n)
        check(bool(res.warnings) == (n == own), "канал №%d: попередження про спільні байти лише на каналі з власним DMR ID: %r" % (n, res.warnings))
        # знімаємо ключ: повертається вихідний запис
        res0 = te.channel_set_aes_slot(res.image, n, 0)
        check(te.aes_slot(res0.image.channel_rec(n)) == 0, "канал №%d: ключ 0 -- без шифрування" % n)
        # той самий ключ -- змін нема
        check(not te.channel_set_aes_slot(res.image, n, 7).any_change(), "канал №%d: той самий ключ -- нічого не змінюється" % n)
    # V3.3: порядок «ключ, потім DMR ID» -- попередження про скинутий слот; «DMR ID, потім ключ» -- DMR ID цілий
    keyed = te.channel_set_aes_slot(img, own, 4).image
    res = te.channel_edit(keyed, own, {"DMR ID": "None"}, DP)
    check(any("AES-слот" in w and "ключ 4" in w for w in res.warnings), "ключ -> зміна DMR ID: попередження про скинутий слот: %r" % res.warnings)
    dmr_before = te.channel_values(img, own, DP)["DMR ID"]
    res2 = te.channel_edit(img, own, {"DMR ID": "123456"}, DP)
    res3 = te.channel_set_aes_slot(res2.image, own, 9)
    check(te.channel_values(res3.image, own, DP)["DMR ID"] == "123456" and dmr_before != "123456", "DMR ID -> ключ: новий DMR ID цілий")
    check(te.aes_slot(res3.image.channel_rec(own)) == 9, "DMR ID -> ключ: слот встановлено")
    # відмови
    check(refused(te.channel_set_aes_slot, img, plain, 16) and refused(te.channel_set_aes_slot, img, plain, -1), "ключ поза 0..15 відхилено")
    check(refused(te.channel_set_aes_slot, img, analog[0], 3), "аналоговий канал: ключа нема")
    check(refused(te.channel_set_aes_slot, img, 999, 3), "невідомий канал відхилено")


def test_cp1251_warning():
    doc, _s, _d = fixture_doc()
    res = te.add_entity(doc.image, "tg", "Київ і Їжак", [1], DP)
    check(any("cp1251" in w for w in res.warnings), "літери «і ї є ґ» -> cp1251 з тим самим попередженням, що в CSV: %r" % res.warnings)
    res2 = te.add_entity(doc.image, "tg", "Папуга", [1], DP)
    check(not res2.warnings, "назва з GB2312 -- без попередження (GBK)")


def test_duplicate_names_numeric_refs():
    """Канали з однаковими назвами: посилання за назвою неоднозначні, редактор користується «#N»."""
    doc, _s, _d = fixture_doc()
    img = doc.image
    # два канали з назвою «R1»
    for n in (20, 21):
        img.set_channel_rec(n, tc.chan(b"R1", 43000000 + n, 43000000 + n, False))
        img.set_channel_in_use(n, True)
    doc.apply(cc.import_csv(img, {}, DP))     # нічого не змінює; лише перевіряємо, що образ приймається
    res = te.set_members(img, "zone", 0, [1, 20, 21], DP)
    check([m for _b, n, m in te.zones(res.image) if n == "Київ"][0] == [1, 20, 21], "два канали «R1» у зоні: обидва на місці")
    res2 = te.set_members(res.image, "zone", 0, [21, 20, 1], DP)
    check([m for _b, n, m in te.zones(res2.image) if n == "Київ"][0] == [21, 20, 1], "перестановка однойменних каналів зберігає, який є який")
    # те саме для CSV-файлів не діє: «#N» у файлі -- не посилання
    tabs = {"zones": cc.Table("Zones.csv", ["Zone Name", "Channel1", "Name (readable)"], [(2, ["Київ", "#20", "Київ"])])}
    try:
        cc.import_csv(img, tabs, DP)
        ok = False
    except cc.CsvImportRefused:
        ok = True
    check(ok, "для CSV-ФАЙЛІВ «#N» не працює (формат не змінено)")


def test_delete_with_references():
    doc, _s, _d = fixture_doc()
    before = snap(doc)
    # канал 1 є в зонах «Київ» і «Папуга»
    refs = te.references(doc.image, "channel", 1)
    check(len(refs.items) == 2 and {t.split("«")[1].split("»")[0] for _s2, t in refs.items} == {"Київ", "Папуга"}, "посилання на канал: %r" % refs.items)
    e = refused(te.delete_entity, doc.image, "channel", 1, DP)
    check(e is not None and "Київ" in str(e), "без підтвердження (cascade=False) -- відмова зі списком, хто посилається")
    check(snap(doc) == before, "після відмови документ НЕ змінено (U3)")
    res = te.delete_entity(doc.image, "channel", 1, DP, cascade=True)
    doc.apply(res)
    check(1 not in [n for n, _r in doc.image.channels()], "канал видалено")
    z = {n: m for _b, n, m in te.zones(doc.image)}
    check(z["Київ"] == [3] and z["Папуга"] == [2, 3, 130], "із зон канал викреслено, порядок решти збережено: %r" % z)
    # зона, що лишилась би порожньою, зникає разом із каналом -- і про це сказано
    doc2, _s, _d = fixture_doc()
    refs2 = te.references(doc2.image, "channel", 2)
    check(any(sec == "Зони" and nm == "Local" for sec, nm in refs2.also_removed), "попередження: зона «Local» стане порожньою й зникне: %r" % refs2.also_removed)
    res = te.delete_entity(doc2.image, "channel", 2, DP, cascade=True)
    check("Local" not in [n for _b, n, _m in te.zones(res.image)] and any(sec == "Зони" for sec, _t in res.removed), "порожня зона прибрана і показана серед видалених")
    # контакт: у списках і каналах
    doc3, _s, _d = fixture_doc()
    refs3 = te.references(doc3.image, "contact", 1)          # слот 1 = контакт №2
    check(len(refs3.items) >= 3 and refs3.also_removed, "контакт №2: у двох списках і каналі, список «Група» стане порожнім: %r %r" % (refs3.items, refs3.also_removed))
    b3 = snap(doc3)
    e = refused(te.delete_entity, doc3.image, "contact", 1, DP)
    check(e is not None and snap(doc3) == b3, "контакт без підтвердження: відмова, документ без змін")
    res = te.delete_entity(doc3.image, "contact", 1, DP, cascade=True)
    doc3.apply(res)
    tg = {n: m for _s2, n, m in te.tg_lists(doc3.image)}
    check(tg == {"Ukraine": [1, 3]}, "контакт викреслено зі списку «Ukraine», порожній список «Група» зник: %r" % tg)
    check(te.channel_refs(doc3.image, 3)["Contact"] == 0 and te.channel_refs(doc3.image, 3)["TG List"] == 0, "канал №3: поле «Контакт» -> None і список прийому, що зник, -> None")
    # список прийому, на який посилається канал
    doc4, _s, _d = fixture_doc()
    refs4 = te.references(doc4.image, "tg", 0)
    check([i for i in refs4.items if "№1" in i[1]], "список «Ukraine» використовує канал №1: %r" % refs4.items)
    e = refused(te.delete_entity, doc4.image, "tg", 0, DP)
    check(e is not None, "список без підтвердження: відмова")
    doc4.apply(te.delete_entity(doc4.image, "tg", 0, DP, cascade=True))
    check(te.channel_refs(doc4.image, 1)["TG List"] == 0 and 0 not in [s for s, _n, _m in te.tg_lists(doc4.image)], "список видалено, канал№1: TG List -> None")
    # без посилань -- видаляється без cascade
    doc5, _s, _d = fixture_doc()
    doc5.apply(te.add_entity(doc5.image, "zone", "Temp", [2], DP))
    z5 = [b for b, n, _m in te.zones(doc5.image) if n == "Temp"][0]
    doc5.apply(te.delete_entity(doc5.image, "zone", z5, DP))
    check("Temp" not in [n for _b, n, _m in te.zones(doc5.image)], "зона без посилань видаляється одразу")


def test_limits():
    doc, _s, _d = fixture_doc()
    # 33 контакти
    img = doc.image
    ops = [{"op": "add", "name": "К%02d" % i, "id": 1000 + i, "type": 0} for i in range(35)]
    doc.apply(ce.apply_ops(img, ops))
    nums = [n for n, *_r in te.contacts(doc.image)]
    check(len(nums) == 39, "додано 35 контактів: %d" % len(nums))
    res = te.set_members(doc.image, "tg", 0, nums[:32], DP)
    doc.apply(res)
    check(len(te.tg_lists(doc.image)[0][2]) == 32, "32 контакти в списку прийнято")
    e = refused(te.set_members, doc.image, "tg", 0, nums[:33], DP)
    check(e is not None and "не більше 32" in str(e) and "ліміт" in str(e), "33-й контакт відхилено з поясненням: %s" % e)
    check(len(te.tg_lists(doc.image)[0][2]) == 32, "після відмови список лишився з 32")
    e = refused(te.add_entity, doc.image, "tg", "Too many", nums[:33], DP)
    check(e is not None and "не більше 32" in str(e), "новий список із 33 відхилено")
    # зона: ліміт з документа
    lim = te.zone_limit(doc.image)
    im = doc.image
    base = max(n for n, _r in im.channels()) + 1
    made = []
    for k in range(lim + 2):
        n = 400 + k
        if n > cl.CP_CHANNELS_BANKS * cl.CP_CHANNELS_PER_BANK:
            break
        im.set_channel_rec(n, tc.chan(("Z%03d" % k).encode(), 43000000 + k, 43000000 + k, False))
        im.set_channel_in_use(n, True)
        made.append(n)
    del base
    check(len(made) >= lim + 1, "створено каналів для перевірки ліміту зони (%d): %d" % (lim, len(made)))
    res = te.set_members(im, "zone", 0, made[:lim], DP)
    check(len(te.zones(res.image)[0][2]) == lim, "зона з %d каналів прийнята" % lim)
    e = refused(te.set_members, im, "zone", 0, made[:lim + 1], DP)
    check(e is not None and "не більше %d" % lim in str(e), "(ліміт+1)-й канал у зоні відхилено з поясненням: %s" % e)


def test_csv_roundtrip_of_edits():
    """U1 + U2."""
    doc, _s, _d = fixture_doc()
    doc.apply(te.channel_new(doc.image, "New FM", False, DP))
    doc.apply(te.channel_edit(doc.image, [n for n, nm, _t, _r in te.channels(doc.image, DP) if nm == "New FM"][0], {"Rx Frequency": "433,5", "Tx Frequency": "433,5"}, DP))
    doc.apply(te.channel_new(doc.image, "New DMR", True, DP))
    new_dmr = [n for n, nm, _t, _r in te.channels(doc.image, DP) if nm == "New DMR"][0]
    doc.apply(te.channel_edit(doc.image, new_dmr, {"Colour Code": "5", "Timeslot": "2", "Contact": te.ref_token(doc.image, "contact", 1)}, DP))
    doc.apply(te.add_entity(doc.image, "tg", "My TG", [3, 1], DP))
    fm = [n for n, nm, _t, _r in te.channels(doc.image, DP) if nm == "New FM"][0]
    doc.apply(te.add_entity(doc.image, "zone", "My zone", [fm, new_dmr, 1], DP))
    with tempfile.TemporaryDirectory() as d:
        doc.export_csv(d, DP, log=lambda *_: None)
        hdr, rows = read_csv(os.path.join(d, "Channels.csv"))
        check(len(rows) == len(doc.image.channels()), "U1: усі канали в CSV")
        r = [x for x in rows if x[-1] == "New DMR"][0]
        check(r[hdr.index("Channel Type")] == "Digital" and r[hdr.index("Colour Code")] == "5" and r[hdr.index("Timeslot")] == "2", "U1: цифровий канал у CSV: %r" % r[:12])
        r = [x for x in rows if x[-1] == "New FM"][0]
        check(r[hdr.index("Rx Frequency")].strip() == "433,50000", "U1: частота у CSV (кома): %r" % r[hdr.index("Rx Frequency")])
        zh, zr = read_csv(os.path.join(d, "Zones.csv"))
        z = [x for x in zr if x[-1] == "My zone"][0]
        members = [c for c in z[1:-1] if c]
        compat = {n: cc.compat_text(rec[:16]) for n, rec in doc.image.channels()}
        check(members == [compat[fm], compat[new_dmr], compat[1]], "U1: склад зони в CSV (порядок): %r" % members)
        th, tr_ = read_csv(os.path.join(d, "TG_Lists.csv"))
        t = [x for x in tr_ if x[-1] == "My TG"][0]
        check([c for c in t[1:-1] if c] == [cc.compat_text(dict(doc.image.contacts())[2][:16]), cc.compat_text(dict(doc.image.contacts())[0][:16])],
              "U1: склад списку в CSV: %r" % [c for c in t[1:-1] if c])
        # U2: змінюємо CSV (додаємо канал, міняємо склад зони) -> імпорт у ІНШИЙ документ -> редактор показує те саме
        hdr, rows = read_csv(os.path.join(d, "Channels.csv"))
        row = list(rows[0])
        row[0] = ""
        row[1] = ""
        row[-1] = "From CSV"
        row[hdr.index("Rx Frequency")] = "\t145,60000"
        row[hdr.index("Tx Frequency")] = "\t145,60000"
        rows.append(row)
        with open(os.path.join(d, "Channels.csv"), "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, delimiter=";", lineterminator="\r\n")
            w.writerow(hdr)
            w.writerows(rows)
        doc2, _s2, _d2 = fixture_doc()
        doc2.import_csv(cc.read_dir(d), DP)
        names = [nm for _n, nm, _t, _r in te.channels(doc2.image, DP)]
        check("From CSV" in names and "New FM" in names and "New DMR" in names, "U2: редактор бачить канали з CSV: %r" % names)
        e = te.channels(doc2.image, DP)
        check(dict((nm, rx) for _n, nm, _t, rx in e)["From CSV"] == "145,60000", "U2: частота з CSV у редакторі")
        check({n: m for _b, n, m in te.zones(doc2.image)}["My zone"] == [fm, new_dmr, 1], "U2: зона з CSV у редакторі: %r" % {n: m for _b, n, m in te.zones(doc2.image)})
        check({n: m for _s3, n, m in te.tg_lists(doc2.image)}["My TG"] == [3, 1], "U2: список з CSV у редакторі")


def test_untouched_roundtrip():
    """U5: відкрити з бекапа, нічого не чіпати, зберегти -> дані ті самі байт-у-байт."""
    doc, spi, data = fixture_doc()
    # «порожні» операції редакторів теж нічого не міняють
    for fn in (lambda i: te.set_members(i, "tg", 0, te.tg_lists(i)[0][2], DP), lambda i: te.set_members(i, "zone", 0, te.zones(i)[0][2], DP),
               lambda i: te.channel_edit(i, 1, {"Rx Frequency": te.channel_values(i, 1, DP)["Rx Frequency"]}, DP),
               lambda i: te.channel_edit(i, 2, {"Channel Name": "PMR 1"}, DP), lambda i: te.rename_entity(i, "zone", 0, "Київ", DP),
               lambda i: te.channel_edit(i, 1, {"Contact": te.ref_token(i, "contact", 1)}, DP)):
        res = fn(doc.image)
        check(not doc.apply(res) and not doc.modified, "порожня правка не змінює документ")
    check(snap(doc) == snap(D.Document(tc.codeplug_of(spi)[0], D.ORIGIN_FILE)), "образ документа == образ бекапа")
    with tempfile.TemporaryDirectory() as d:
        orig = os.path.join(d, "orig.zip")
        with open(orig, "wb") as f:
            f.write(data)
        d1 = D.from_backup(orig)
        out = os.path.join(d, "saved.zip")
        d1.save_as(out)
        with zipfile.ZipFile(orig) as a, zipfile.ZipFile(out) as b:
            for part in ("eeprom.bin", "flash.bin"):
                check(a.read(part) == b.read(part), "U5: %s у збереженому файлі той самий байт-у-байт" % part)
        d2 = D.from_backup(out)
        check(snap(d2) == snap(d1), "U5: повторне відкриття -- той самий образ")


def test_write_edited_document():
    """Записане в рацію через шлях відновлення: нові зона/канал на місці, калібрування не чіпали."""
    import test_cps_doc as tdoc
    doc, spi, _d = fixture_doc()
    doc.apply(te.channel_new(doc.image, "Edited", False, DP))
    ch = [n for n, nm, _t, _r in te.channels(doc.image, DP) if nm == "Edited"][0]
    doc.apply(te.add_entity(doc.image, "zone", "New zone", [ch, 1], DP))
    other = bytearray(spi)
    other[0x10000:0x10010] = b"CALIB-C-CALIB-C!"
    with tempfile.TemporaryDirectory() as d:
        radio = tdoc.ClosableRadio(other)
        res, _c = doc.write_image(None)
        with tr.Unlocked():
            out = cc.write_image_via_restore(cl.CpsLink(radio, retries=0), res, lambda t, p: True, log=lambda *_: None, out_dir=d,
                                             zip_prefix="codeplug_document-write")
        check(out["sectorsWritten"] >= 1, "відредагований документ записано")
        check(bytes(radio.spi[0x10000:0x10010]) == b"CALIB-C-CALIB-C!", "калібрування не чіпали")
        import codeplug_view as cv
        cp2, _m = cv.codeplug_from_radio(cl.CpsLink(radio, retries=0))
        img2 = cc.Image.from_codeplug(cp2)
        check("New zone" in [n for _b, n, _m in te.zones(img2)] and "Edited" in [n for _n, n, _t, _r in te.channels(img2, DP)], "у рації нова зона і новий канал")


# ----------------------------------------------------------------------------------------
#  GUI
# ----------------------------------------------------------------------------------------

def _spin(app, n=3):
    for _ in range(n):
        app.update()


def test_gui():
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("ПРОПУЩЕНО (GUI): нема tkinter")
        return
    if not os.environ.get("DISPLAY"):
        print("ПРОПУЩЕНО (GUI): нема DISPLAY (xvfb-run -a python3 tools/test_cps_edit.py)")
        return
    from cps_ui.app import CpsApp
    from cps_ui.settings import Settings
    import gui_dialogs as gd
    import tkinter.messagebox as mb

    tmp = tempfile.mkdtemp(prefix="cpsedit_")
    spath = os.path.join(tmp, "ui.json")
    os.environ["TYT_CPS_SETTINGS"] = spath
    os.environ["HOME"] = tmp
    app = CpsApp(settings=Settings(spath), autoprobe=False)
    errors = []
    orig = (mb.showinfo, mb.showerror, gd.confirm_dialog, gd.choice_dialog, gd.name_dialog, gd.pick_dialog, gd.new_channel_dialog)
    mb.showinfo = lambda *a, **k: None
    mb.showerror = lambda *a, **k: errors.append(a)
    try:
        app.geometry("1200x800")
        app.update()
        # --- U6: кожен редактор без документа ---
        for key in ("channels", "zones", "tglists"):
            app.show(key)
            _spin(app)
            p = app.get_panel(key)
            check(p.hint.winfo_manager() == "pack" and not p.body.winfo_manager(), "%s: без документа -- підказка, форми нема" % key)
            check(all(str(b.cget("state")) == "disabled" for b in (p.btn_add, p.btn_dup, p.btn_ren, p.btn_del)), "%s: без документа кнопки вимкнені" % key)
        spi = tc.make_fixture_spi()
        _cp, data = tc.codeplug_of(spi)
        src = os.path.join(tmp, "orig.zip")
        with open(src, "wb") as f:
            f.write(data)
        check(app.doc_open_file(src), "відкрито з бекапу")
        before = snap(app.doc)
        # --- U5 (GUI): обійти всі редактори, вибрати кожен запис, «торкнутись» кожного поля -- документ не змінюється ---
        for key in ("channels", "zones", "tglists"):
            app.show(key)
            _spin(app)
            p = app.get_panel(key)
            check(p.hint.winfo_manager() == "" and p.body.winfo_manager() == "pack", "%s: з документом -- список і форма" % key)
            for item in p.tree.get_children():
                p.tree.selection_set(item)
                _spin(app, 2)
        app.show("channels")
        _spin(app)
        c = app.get_panel("channels")
        for item in c.tree.get_children():
            c.tree.selection_set(item)
            _spin(app, 2)
            for col in c.fields:
                if col != "Channel Number":
                    c.commit(col)
        check(snap(app.doc) == before and not app.doc.modified, "U5: обхід усіх редакторів і полів нічого не змінив (зірочки нема)")
        # --- каналі: поле -> одразу в документ; помилка -> повідомлення, документ той самий ---
        item = [i for i in c.tree.get_children() if c._item_ident[i] == 2][0]
        c.tree.selection_set(item)
        _spin(app)
        check(c._digital is False and str(c.fields["Colour Code"]["widget"].cget("state")) == "disabled", "T3.1: аналоговий канал -- цифрові поля вимкнені")
        check(str(c.fields["RX Tone"]["widget"].cget("state")) != "disabled", "T3.1: аналогові поля доступні")
        c.fields["Rx Frequency"]["var"].set("abc")
        c.commit("Rx Frequency")
        check(not app.doc.modified and "не число" in c.msg.cget("text"), "помилка поля: документ не змінено, повідомлення: %s" % c.msg.cget("text"))
        c.fields["Rx Frequency"]["var"].set("433,5")
        c.commit("Rx Frequency")
        _spin(app)
        check(app.doc.modified and te.channel_values(app.doc.image, 2, cc.system_decimal_point())["Rx Frequency"].replace(",", ".") == "433.50000", "поле застосовано до документа одразу")
        c.fields["Channel Type"]["var"].set("Цифровий")
        c.commit("Channel Type")
        _spin(app)
        check(c._digital and str(c.fields["Colour Code"]["widget"].cget("state")) != "disabled" and str(c.fields["Bandwidth (kHz)"]["widget"].cget("state")) == "disabled",
              "зміна типу перемикає доступність полів")
        # посилання зі списку
        labels = [l for l in c.fields["Contact"]["widget"].cget("values")]
        check(labels[0] == "Немає (None)" and len(labels) == 5, "контакти каналу -- список наявних: %r" % labels)
        c.fields["Contact"]["var"].set(labels[2])
        c.commit("Contact")
        check(te.channel_refs(app.doc.image, 2)["Contact"] == 2, "контакт обрано зі списку")
        # V3: ключ AES у каналі -- випадний список 0..15; зайнятість слотів лише з даних «AES-ключі», матеріалу ключа нема
        aes = c.fields[te.AES_KEY_COLUMN]
        vals = list(aes["widget"].cget("values"))
        check(len(vals) == 16 and vals[0].startswith("0 ") and str(aes["widget"].cget("state")) != "disabled", "V3.1: поле «Ключ AES» -- 16 пунктів, на цифровому каналі доступне")
        check("невідомо" in c._aes_hint.cget("text"), "V3.2: до читання слотів -- підказка, що зайнятість невідома")
        aes["var"].set(vals[5])
        c.commit(te.AES_KEY_COLUMN)
        check(te.aes_slot(app.doc.image.channel_rec(2)) == 5 and app.doc.modified, "V3.1: ключ 5 потрапив у документ")
        app.aes_slots = {"occupied": (5, 9)}
        app.on_aes_slots_changed()
        _spin(app)
        check("ключ є" in c._aes_label(5) and "порожній" in c._aes_label(3) and "5, 9" in c._aes_hint.cget("text"), "V3.2: зайняті слоти позначені: %s / %s" % (c._aes_label(5), c._aes_hint.cget("text")))
        check(c._display(te.AES_KEY_COLUMN) == "5" and "ключ є" in aes["var"].get(), "підпис оновився, вибір лишився")
        aes["var"].set(c._aes_label(3))
        c.commit(te.AES_KEY_COLUMN)
        check(te.aes_slot(app.doc.image.channel_rec(2)) == 3 and "немає ключа" in c.msg.cget("text"), "слот без ключа в рації: ключ записано, попередження в повідомленні")
        # фільтр
        c._filter.set("pmr")
        _spin(app)
        check(len(c.tree.get_children()) == 1, "T3.5: фільтр за назвою: %d" % len(c.tree.get_children()))
        c._filter.set("")
        _spin(app)
        # додати канал через діалог
        gd.new_channel_dialog = lambda *a, **k: ("Dialog", True, False)
        n_before = len(app.doc.image.channels())
        c._on_add()
        _spin(app)
        check(len(app.doc.image.channels()) == n_before + 1 and c.form_title.cget("text").endswith("«Dialog»"), "«Додати»: канал створено й вибрано: %s" % c.form_title.cget("text"))
        # перейменувати
        gd.name_dialog = lambda *a, **k: "Renamed"
        c._on_rename()
        _spin(app)
        check("«Renamed»" in c.form_title.cget("text"), "«Перейменувати»")
        c._on_dup()
        _spin(app)
        check("Renamed 2" in c.form_title.cget("text"), "«Дублювати»: %s" % c.form_title.cget("text"))
        # видалення: канал із посиланнями -- спершу «Скасувати» (нічого не змінюється), потім «разом із посиланнями»
        item = [i for i in c.tree.get_children() if c._item_ident[i] == 1][0]
        c.tree.selection_set(item)
        _spin(app)
        snap_before = snap(app.doc)
        gd.choice_dialog = lambda *a, **k: "cancel"
        c._on_delete()
        _spin(app)
        check(snap(app.doc) == snap_before, "U3 (GUI): «Скасувати» -- нічого не змінилось")
        shown = []
        gd.choice_dialog = lambda parent, title, text, buttons, d=0: (shown.append(text), "cascade")[1]
        c._on_delete()
        _spin(app)
        check(shown and "Київ" in shown[0] and "Папуга" in shown[0], "діалог називає зони, що посилаються: %r" % (shown[0][:200] if shown else None))
        check(1 not in [n for n, _r in app.doc.image.channels()] and all(1 not in m for _b, _n, m in te.zones(app.doc.image)), "«разом із посиланнями»: канал і посилання зникли")
        # --- зони (GUI) ---
        app.show("zones")
        _spin(app)
        z = app.get_panel("zones")
        z.tree.selection_set(z.tree.get_children()[0])
        _spin(app)
        check("з %d каналів" % te.zone_limit(app.doc.image) in z.counter.cget("text"), "T2.4: лічильник «N з %d»: %s" % (te.zone_limit(app.doc.image), z.counter.cget("text")))
        cur0 = list(z._cur_nums)
        if z._avail_nums:
            z.avail_lb.selection_set(0)
            z._on_in()
            _spin(app)
            check(len(z._cur_nums) == len(cur0) + 1, "зона: «Додати →» переносить канал")
        if len(z._cur_nums) >= 2:
            last = z._cur_nums[-1]
            z.cur_lb.selection_clear(0, "end")
            z.cur_lb.selection_set(len(z._cur_nums) - 1)
            z._on_move(-1)
            _spin(app)
            check(z._cur_nums[-2] == last, "зона: «Вгору ↑» піднімає вибраний канал на одну позицію")
            z.cur_lb.selection_clear(0, "end")
            z.cur_lb.selection_set(len(z._cur_nums) - 2)
            z._on_move(1)
            _spin(app)
            check(z._cur_nums[-1] == last, "зона: «Вниз ↓» повертає назад")
        z.cur_lb.selection_set(0)
        keep = list(z._cur_nums)
        for _i in range(len(keep) - 1):
            z.cur_lb.selection_clear(0, "end")
            z.cur_lb.selection_set(0)
            z._on_out()
            _spin(app)
        check(len(z._cur_nums) == 1, "зону можна спорожнити до одного елемента")
        z.cur_lb.selection_set(0)
        z._on_out()
        check("Не можна прибрати всі" in z.msg.cget("text") and len(z._cur_nums) == 1, "останній елемент не прибирається: %s" % z.msg.cget("text"))
        # --- списки прийому (GUI): ліміт 32 ---
        ops = [{"op": "add", "name": "К%02d" % i, "id": 2000 + i, "type": 0} for i in range(35)]
        app.doc.apply(ce.apply_ops(app.doc.image, ops))
        app.show("tglists")
        _spin(app)
        t = app.get_panel("tglists")
        t.tree.selection_set(t.tree.get_children()[0])
        _spin(app)
        t.avail_lb.selection_set(0, "end")
        t._on_in()
        _spin(app)
        check(len(t._cur_nums) <= 32 and "не більше 32" in t.msg.cget("text") and "ліміт" in t.msg.cget("text"), "T1.3 (GUI): понад 32 -- відмова з поясненням: %s" % t.msg.cget("text"))
        t.avail_lb.selection_clear(0, "end")
        t.avail_lb.selection_set(0, 28)
        t._on_in()
        _spin(app)
        check(len(t._cur_nums) == 32 and "ліміт кодплага досягнуто" in t.counter.cget("text"), "список наповнено до 32: %s" % t.counter.cget("text"))
        check(app.doc.modified, "документ позначено зміненим")
        # --- S1: позивний ---
        app.show("aprs")
        _spin(app)
        ap = app.get_panel("aprs")
        check(not hasattr(ap, "write_call_btn"), "S1: кнопки «Записати позивний» нема")
        texts = [w.cget("text") for w in _all(ap) if w.winfo_class() == "TLabel"]
        check(any("Позивний у документі" in t for t in texts) and any("Позивний у рації" in t for t in texts), "S1: показано позивний документа й рації")
        check(not any(w.winfo_class() == "TEntry" and str(w.cget("textvariable")) == str(ap.vars["call"]) for w in _all(ap)), "S1: поле позивного нередаговане")
        ap._radio_call = "UR5XYZ"
        ap.on_document_changed()
        check("Різні позивні" in ap.call_note.cget("text") and "UR5ABC" in ap.call_note.cget("text") and "UR5XYZ" in ap.call_note.cget("text"),
              "S1: різні позивні -- показано обидва й що запишеться: %s" % ap.call_note.cget("text"))
        app.show("basic")
        bp = app.get_panel("basic")
        bp.vars["callsign"].set("R2ABC")
        _spin(app)
        bp._on_apply()
        _spin(app)
        app.show("aprs")
        _spin(app)
        check("R2ABC" in ap.vars["call_doc"].get(), "S1: позивний документа оновлюється в панелі бікона: %s" % ap.vars["call_doc"].get())
        # --- S3: пояснення DFU під «Оновити» ---
        app.show("conn")
        _spin(app)
        cp_ = app.get_panel("conn")
        slaves = cp_.pack_slaves()
        i_btn = slaves.index(cp_.refresh_btn)
        check(slaves[i_btn + 1].winfo_class() == "TLabel" and "DFU" in slaves[i_btn + 1].cget("text") and slaves[i_btn + 1].cget("text").count(".") == 1,
              "S3: одне речення про DFU одразу під «Оновити»")
        # --- S2: смуга прокрутки ---
        app.geometry("1200x900")
        _spin(app, 6)
        host = app._hosts["conn"]
        check(host.winfo_manager() != "" and not host.vbar.winfo_manager(), "S2: коротка панель (Підключення) -- смуги нема")
        app.geometry("900x560")
        app.show("flash")
        _spin(app, 8)
        host = app._hosts["flash"]
        check(host.inner.winfo_reqheight() > host.canvas.winfo_height() and host.vbar.winfo_manager() == "pack", "S2: висока панель у малому вікні -- смуга є")
        app.geometry("1200x1400")
        _spin(app, 8)
        check(host.inner.winfo_reqheight() <= host.canvas.winfo_height() and not host.vbar.winfo_manager(), "S2: те саме вікно, що виросло, -- смуга зникла")
        # таблиці перегляду: смуга лише коли рядків більше, ніж місця
        app.show("contacts")
        _spin(app, 6)
        tree = app.get_panel("contacts").tree
        parent = tree.master
        vs = [w for w in parent.winfo_children() if w.winfo_class() == "TScrollbar" and str(w.cget("orient")) == "vertical"][0]
        check(vs.winfo_manager() == "" or len(tree.get_children()) > 10, "S2: таблиця з кількома рядками -- смуги нема")
    finally:
        (mb.showinfo, mb.showerror, gd.confirm_dialog, gd.choice_dialog, gd.name_dialog, gd.pick_dialog, gd.new_channel_dialog) = orig
        app.destroy()
    check(not errors, "GUI: messagebox.showerror не викликався: %r" % (errors[:2],))


def _all(w):
    yield w
    for c in w.winfo_children():
        yield from _all(c)


def main():
    for t in (test_export_rows_same_as_files, test_tg_lists, test_zones, test_channels_edit, test_aes_slot_warning, test_aes_key_in_channel, test_cp1251_warning, test_duplicate_names_numeric_refs,
              test_delete_with_references, test_limits, test_csv_roundtrip_of_edits, test_untouched_roundtrip, test_write_edited_document, test_gui):
        try:
            t()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILS.append("%s: виняток %r" % (t.__name__, e))
    if FAILS:
        print("test_cps_edit: ПРОВАЛЕНО перевірок: %d" % len(FAILS))
        return 1
    print("test_cps_edit: усі перевірки пройшли (спільна перевірка через імпорт CSV, списки/зони/канали, видалення з посиланнями, межі, U1-U6, S1-S3).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
