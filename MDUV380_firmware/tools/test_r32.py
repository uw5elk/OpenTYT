# -*- coding: utf-8 -*-
"""R32 (Z1-Z5): перевірка термінології (check_terminology.py), розбір бази позивних, терпимий до колонок (dmr_db.parse_source + tools/testdata),
виміри фаз запису (phase_timing.py) і передача щойно прочитаного образу в страхову копію (cps_restore.restore_codeplug(prefetched=...)),
склад архіву у вікні бекапу.
Логіка -- у будь-якому python3; GUI -- лише з tkinter + DISPLAY (`xvfb-run -a python3.12 tools/test_r32.py`).
`python3 tools/test_r32.py --measure` друкує таблицю фаз (запити/КіБ) на підробленому флеші -- для звіту (секунди на підробленій рації нічого не означають)."""
import os
import random
import shutil
import sys
import tempfile
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import check_terminology as ct           # noqa: E402
import cps_csv as cc                     # noqa: E402
import cps_link as cl                    # noqa: E402
import cps_restore as cr                 # noqa: E402
import codeplug_view as cv               # noqa: E402
import contact_edit as ce                # noqa: E402
import dmr_db as db                      # noqa: E402
import test_cps_csv as tc                # noqa: E402
import test_cps_restore as tcr           # noqa: E402

FAILS = []
tcr.FakeRadioX.close = lambda self: None
TESTDATA = os.path.join(HERE, "testdata")


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def quiet(*_a, **_k):
    pass


def old_form(i=0, tail="а"):
    """Стара форма терміна, зібрана зі списку OLD_FORMS (у цьому файлі її літерала нема -- інакше сам тест порушував би перевірку)."""
    return ct.OLD_FORMS[i][0] + tail


# ----------------------------------------------------------------------------------------------------------------------
#  Z1. check_terminology.py
# ----------------------------------------------------------------------------------------------------------------------

def put(root, rel, data):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode("utf-8"))
    return p


def test_terminology():
    with tempfile.TemporaryDirectory() as root:
        put(root, "MDUV380_firmware/tools/clean.py", "# кодплаг у порядку\nprint('кодплага')\n")
        found, skipped = ct.find(root)
        check(found == [] and skipped == [], "Z1: чисте дерево -- нічого не знайдено")
        check(ct.main(["--root", root]) == 0, "Z1: чисте дерево -- код виходу 0")

        put(root, "MDUV380_firmware/tools/bad.py", "x = 1\n# правка %s рації\n" % old_form(0, "а"))
        found, _ = ct.find(root)
        check(len(found) == 1 and found[0][1] == 2 and found[0][0].endswith("bad.py"), "Z1: підкладений файл зі старою формою знайдено з номером рядка: %r" % (found,))
        check(ct.main(["--root", root]) == 1, "Z1: підкладений файл -- код виходу 1")

        # інші словоформи й регістр
        put(root, "STATUS.md", "У %s\nі %s\nта %s.\n" % (old_form(1, "і"), old_form(0, "ом"), old_form(0, "").upper()))
        found, _ = ct.find(root)
        check(len(found) == 4, "Z1: .md сканується; словоформи (друга основа, закінчення -ом) і ВЕЛИКІ літери ловляться: %d" % len(found))

        # винятки: прошивка, languages (cp1251), позначка term-ok, не-UTF-8
        cp = ("шрифт %s" % old_form(0, "а")).encode("cp1251")
        h = put(root, "MDUV380_firmware/application/include/user_interface/languages/ukrainian.h", cp)
        c = put(root, "MDUV380_firmware/application/source/x.c", "// %s\n" % old_form(0, "у"))
        put(root, "MDUV380_firmware/tools/languages/x.py", "# %s\n" % old_form(0, "а"))      # каталог languages поза прошивкою теж не сканується
        put(root, "MDUV380_firmware/tools/quote.py", "# цитата: %s  # term-ok\n" % old_form(0, "а"))
        put(root, "MDUV380_firmware/tools/legacy.txt", ("рядок %s" % old_form(0, "а")).encode("cp1251"))
        found, skipped = ct.find(root)
        files = {f[0].replace("\\", "/") for f in found}
        check(files == {"MDUV380_firmware/tools/bad.py", "STATUS.md"}, "Z1: languages/*.h, application/, рядок з term-ok -- не чіпаємо: %r" % files)
        check(len(skipped) == 1 and skipped[0].endswith("legacy.txt"), "Z1: не-UTF-8 файл пропущено з попередженням, а не падінням")
        before_h, before_c = open(h, "rb").read(), open(c, "rb").read()

        # --fix
        ch = ct.fix(root)
        check(set(k.replace("\\", "/") for k in ch) == {"MDUV380_firmware/tools/bad.py", "STATUS.md"}, "Z1: --fix правив лише скановані файли: %r" % ch)
        txt = open(os.path.join(root, "STATUS.md"), encoding="utf-8").read()
        check("кодплазі" in txt and "кодплагом" in txt and "КОДПЛАГ" in txt, "Z1: --fix зберігає регістр і закінчення: %r" % txt)
        check(open(h, "rb").read() == before_h and open(c, "rb").read() == before_c, "Z1: файли в cp1251 / прошивка байт-у-байт не змінені")
        check(ct.find(root)[0] == [], "Z1: після --fix знайдених нема")

        # нове слово -- одна правка у списку
        put(root, "tools/w.py", "# тестслово тут\n")
        ct.OLD_FORMS.append(("тестслово", "нове"))
        try:
            check(len(ct.find(root)[0]) == 1, "T1.4: додане в OLD_FORMS слово ловиться без інших змін")
        finally:
            ct.OLD_FORMS.pop()

    found, _ = ct.find()
    check(found == [], "Z1/Z5: на репозиторії чисто: %r" % (found[:3],))
    # самого файла перевірки та каталогів, що пропускаються, у скануванні нема
    scanned = [os.path.relpath(p, ct.DEFAULT_ROOT).replace("\\", "/") for p in ct.iter_files(ct.DEFAULT_ROOT)]
    check("MDUV380_firmware/tools/check_terminology.py" not in scanned and not any("/application/" in "/" + s for s in scanned), "Z1: сам файл перевірки й application/ не скануються")
    check(any(s.endswith("run_tests.sh") for s in scanned) and any(s == "STATUS.md" for s in scanned), "Z1: run_tests.sh і STATUS.md скануються")


# ----------------------------------------------------------------------------------------------------------------------
#  Z2 / Z3. Розбір джерел
# ----------------------------------------------------------------------------------------------------------------------

EXPECT_IDS = [2550001, 2550002, 2550003, 2550104, 2559999, 2600001, 2620002, 3100001, 3100002, 2300003]
EXPECT_CALLS = ["UR1AAA", "UR2BBB", "UR3CCC", "UT4DDD", "UR9ZZZ", "SP1PL", "DL2XYZ", "K1USA", "W2NYC", "OK1CZ"]


def load(name):
    return db.read_source_file(os.path.join(TESTDATA, name))


def test_sources():
    for name in ("radioid_users.json", "radioid_user.csv"):
        s = load(name)
        check([r["id"] for r in s.rows] == EXPECT_IDS and [r["callsign"] for r in s.rows] == EXPECT_CALLS and s.skipped == 0 and not s.has_date,
              "Z2: %s -- 10 записів, ID й позивні на місці" % name)
        check(s.rows[0]["first"] == "Ivan" and s.rows[0]["last"] == "Petrenko" and s.rows[5]["country"] == "Poland", "Z2: %s -- ім'я, прізвище, країна" % name)
        check(s.columns.get("id") and s.columns.get("callsign") and s.notes == [], "Z2: %s -- колонки знайдено за назвами, без здогадів" % name)
    a, b = load("radioid_users.json"), load("radioid_user.csv")
    check(a.rows == b.rows, "Z2: JSON і CSV того самого вмісту дають однакові рядки")

    # переставлені колонки, інші назви, ';', зайві пробіли, дата
    h = load("hamdigital_like.csv")
    check([r["id"] for r in h.rows] == EXPECT_IDS and [r["callsign"] for r in h.rows] == EXPECT_CALLS, "Z2: переставлені колонки й ';' -- ID та позивні")
    check(h.rows[0]["first"] == "Ivan Petrenko" and h.rows[4]["first"] == "", "Z2: зайві пробіли всередині й по краях прибрано; порожнє лишається порожнім")
    check(h.has_date and h.rows[0]["date"].isoformat() == "2026-10-20" and h.rows[9]["date"] is None, "Z2: колонка дати розпізнана")
    check(h.columns["id"].startswith("колонка 3") and h.columns["callsign"].startswith("колонка 1"), "Z2: опис колонок: %s" % h.describe())

    # без заголовка, колонки в довільному порядку -- за змістом
    n = load("no_header_swapped.csv")
    check([r["id"] for r in n.rows] == EXPECT_IDS and [r["callsign"] for r in n.rows] == EXPECT_CALLS, "T3.1/Z2: без заголовка -- ID та позивний знайдено за змістом")
    check(any("DMR ID" in x for x in n.notes) and any("позивним" in x for x in n.notes), "T3.1: у поясненні сказано, що колонки знайдено за змістом: %r" % (n.notes,))
    check(len(n.rows) == 10 and n.rows[0]["first"] == "Ivan", "T3.1: перший рядок не з'їдено заголовком (його нема)")

    # дрібні варіанти
    s = db.parse_source(("﻿ radio id ; call sign ;  FIRST name \r\n 2550001 ; ur1aaa ;  Ivan  \r\n").encode("utf-8"))
    check(len(s.rows) == 1 and s.rows[0]["id"] == 2550001, "Z2: BOM, CRLF, пробіли в назвах колонок: %r" % (s.rows,))
    s = db.parse_source("2550001\tUR1AAA\tIvan\n2550002\tUR2BBB\tOlena\n")
    check([r["id"] for r in s.rows] == [2550001, 2550002] and s.rows[1]["callsign"] == "UR2BBB", "Z2: табуляція, без заголовка")
    s = db.parse_source("NAME,CALLSIGN,ID\nIvan,UR1AAA,2550001\nBAD,UR2BBB,xx\n")
    check(len(s.rows) == 1 and s.skipped == 1, "Z2: колонка ID за назвою «ID»; рядок із нечисловим ID -- у пропущені")
    s = db.parse_source("Місто,Хто,Номер\nКиїв,UR1AAA,2550001\nЛьвів,UR2BBB,2550002\n")
    check([r["id"] for r in s.rows] == [2550001, 2550002] and s.rows[0]["callsign"] == "UR1AAA", "T3.1: заголовок нерозпізнаний, але ID і позивний знайдені за змістом")
    js = '{"result": [{"num": "2550001", "who": "UR1AAA"}, {"num": "2550002", "who": "UR2BBB"}]}'
    s = db.parse_source(js)
    check([r["id"] for r in s.rows] == [2550001, 2550002] and s.rows[0]["callsign"] == "UR1AAA", "T3.1: JSON з невідомими іменами полів -- за змістом")


def test_unrecognized():
    try:
        load("not_a_database.html")
        check(False, "Z3: сторінка помилки мала бути відхилена")
    except db.DbError as e:
        t = str(e)
        check("<!DOCTYPE html>" in t and "503 Service Unavailable" in t and "Try again later." in t, "Z3: у повідомленні видно перші три рядки файла: %s" % t)
        check("веб-сторінку" in t, "Z3: сказано, що це схоже на веб-сторінку")
    long_line = "x" * 500 + "\n2\n3\n4\n5\n"
    try:
        db.parse_source(long_line)
        check(False, "Z3: текст без ID мав бути відхилений")
    except db.DbError as e:
        t = str(e)
        check("  1: " in t and "  3: 3" in t and "  4: 4" not in t and "…" in t, "Z3: показано рівно три рядки, довгий обрізано: %s" % t[:200])
    for bad, frag in (("", "порожній"), ('{"x": 1}', "списку користувачів"), ('[{"a": "b"}]', "поля з DMR ID"), ("{не json", "не читається")):
        try:
            db.parse_source(bad)
            check(False, "Z3: %r мав бути відхилений" % bad)
        except db.DbError as e:
            check(frag in str(e), "Z3: %r -- причина «%s»: %s" % (bad, frag, e))
    try:
        db.parse_source(b"PK\x03\x04\x00\x00binary\x00\x00")
        check(False, "Z3: бінарний файл мав бути відхилений")
    except db.DbError as e:
        check("бінарний" in str(e) and "504b0304" in str(e), "Z3: бінарний файл -- видно перші байти: %s" % e)


# ----------------------------------------------------------------------------------------------------------------------
#  Z4. Виміри фаз і передача образу
# ----------------------------------------------------------------------------------------------------------------------

def blocks(n):
    return (n + cl.CHUNK - 1) // cl.CHUNK


def fresh_setup(d):
    """Підроблена рація з наповненим кодплагом, свіже читання, образ із доданим контактом. Повертає (radio, link, cp, res)."""
    radio = tcr.FakeRadioX(tc.make_fixture_spi())
    link = cl.CpsLink(radio, retries=0)
    cp, _m = cv.codeplug_from_radio(link)
    res = ce.apply_ops(cc.Image.from_codeplug(cp), [{"op": "add", "name": "Київ", "id": 2550, "type": 0}])
    return radio, link, cp, res


def do_write(d, prefetch, mutate=None):
    radio, link, cp, res = fresh_setup(d)
    if mutate:
        mutate(radio)
    texts, logs = [], []
    with tcr.Unlocked():
        out = cc.write_image_via_restore(link, res, lambda t, p: texts.append(t) or True, log=logs.append, now=None, out_dir=d,
                                         prefetched=(cp.eeprom, cp.flash) if prefetch else None)
    return radio, link, out, texts, logs


def zip_parts(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist() if n != "manifest.json"}


def test_prefetched():
    rng_len = cl.flash_backup_range()["length"]
    saved = blocks(cl.EEPROM_BACKUP_LEN) + blocks(rng_len)
    with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db_:
        ra, la, oa, ta, loga = do_write(da, prefetch=False)
        rb, lb, ob, tb, logb = do_write(db_, prefetch=True)
        check(oa["sectorsWritten"] >= 1 and ob["sectorsWritten"] == oa["sectorsWritten"], "Z4: записано однакову кількість секторів (%s і %s)" % (oa["sectorsWritten"], ob["sectorsWritten"]))
        check(bytes(ra.spi) == bytes(rb.spi), "Z4: підсумковий флеш рації БАЙТ-У-БАЙТ той самий (передане читання і повторне)")
        import re

        def norm(t_, d_):       # теку й мітки часу прибираємо; решта тексту має збігатися літера в літеру
            t_ = re.sub(r"\d{8}_\d{6}", "<T>", t_.replace(d_, "<DIR>"))
            return "\n".join(l for l in t_.split("\n") if not l.startswith("Бекап створено"))
        check(norm(ta[0], da) == norm(tb[0], db_) and "Київ" in ta[0], "Z4: текст підтвердження той самий (з точністю до теки)")
        pa, pb = zip_parts(oa["safetyCopy"]), zip_parts(ob["safetyCopy"])
        check(pa == pb and "eeprom.bin" in pa and "flash.bin" in pa, "Z4: страхові копії збігаються за вмістом файлів (%s)" % sorted(pa))
        check("customdata.bin" in pb and "aeskeys.bin" in pb, "Z4: страхова копія при передачі образу все одно містить область custom-data й ключі")
        check(os.path.exists(ob["safetyCopy"]) and cl.read_backup_zip(ob["safetyCopy"])[0] is not None, "Z4: страхова копія на місці й читається")
        check(not rb.cal_touched and rb.c_calls[-1] == bytes([6, 1]), "Z4: калібрування не чіпали; C 6 1 останньою")

        names = [p["name"] for p in ob["phases"]]
        check(names == ["перевірка файла і рації", "страхова копія", "запис секторів", "перечитування для звірки"],
              "Z4/T2.1: чотири фази запису по порядку: %r" % names)
        pha, phb = {p["name"]: p for p in oa["phases"]}, {p["name"]: p for p in ob["phases"]}
        check(pha["страхова копія"]["requests"] - phb["страхова копія"]["requests"] == saved,
              "Z4/T2.2: страхова копія з переданим образом читає на %d запитів менше (EEPROM+флеш): %d проти %d"
              % (saved, phb["страхова копія"]["requests"], pha["страхова копія"]["requests"]))
        check(pha["перечитування для звірки"]["requests"] == phb["перечитування для звірки"]["requests"] == saved,
              "Z4: звірка після запису НЕ скасована і читає все (%d запитів) в обох варіантах" % saved)
        check(phb["запис секторів"]["note"].startswith("%d з " % ob["sectorsWritten"]), "T2.1: у фазі запису видно кількість секторів: %r" % phb["запис секторів"]["note"])
        last = [l for l in logb if l.startswith("Час за фазами")]
        check(len(last) == 1 and "страхова копія" in last[0] and "запис секторів" in last[0] and "перечитування" in last[0], "T2.1: підсумок фаз запису в журналі: %r" % last)
        check(any("УВАГА: страхова копія міститиме ключі" in l for l in logb) and "ключі шифрування AES" in tb[0], "T4.2: про ключі в страховій копії сказано в журналі і в діалозі підтвердження")
        check(any("вдруге не читаю" in l for l in logb) and not any("вдруге не читаю" in l for l in loga), "Z4: у журналі видно, що образ узято з свіжого читання")

    # застаріле «передане»: рація змінилась між свіжим читанням і страховою копією -- самоперевірка відмовляє, нічого не записано
    def drift_all(radio):
        radio.spi_backup = bytes(radio.spi)

    with tempfile.TemporaryDirectory() as d:
        radio, link, cp, res = fresh_setup(d)
        n_before = radio.x_total
        for off in range(0, cl.EEPROM_BACKUP_LEN, cl.CHUNK):
            radio.spi[off + 3] ^= 0x55             # кожен блок EEPROM трохи інший -- жоден вибір випадкових блоків не промахнеться
        for off in range(cl.flash_backup_range()["raw_start"], cl.flash_backup_range()["raw_end"], cl.CHUNK):
            radio.spi[off + 3] ^= 0x55
        try:
            with tcr.Unlocked():
                cc.write_image_via_restore(link, res, lambda t, p: True, log=quiet, out_dir=d, prefetched=(cp.eeprom, cp.flash))
            check(False, "Z4: застаріле передане читання мало бути відхилене")
        except cr.RestoreRefused as e:
            check("Нічого не записано" in str(e) and radio.x_total == n_before, "Z4: застаріле читання -- відмова ДО запису (X-команд нема): %s" % str(e)[:120])
        check(not any("pre-restore" in f for f in os.listdir(d)), "Z4: відмова не лишає недіючої страхової копії")

    # неправильна довжина переданого
    with tempfile.TemporaryDirectory() as d:
        radio, link, cp, res = fresh_setup(d)
        try:
            with tcr.Unlocked():
                cc.write_image_via_restore(link, res, lambda t, p: True, log=quiet, out_dir=d, prefetched=(cp.eeprom[:100], cp.flash))
            check(False, "Z4: передане не тієї довжини мало бути відхилене")
        except cr.RestoreRefused as e:
            check("Нічого не записано" in str(e) and radio.x_total == 0, "Z4: передане не тієї довжини -- відмова без запису")


def count_reads(radio):
    return len(radio.requests)


def test_backup_switches():
    """T2.3: галочки custom-data й ключів справді пропускають читання (рахуємо запити до рації і частини архіву)."""
    region_blocks = blocks(0x10000)
    keys_blocks = blocks(1600)
    res = {}
    for custom, keys in ((True, True), (False, True), (True, False), (False, False)):
        radio = tcr.FakeRadioX(tc.make_fixture_spi())
        link = cl.CpsLink(radio, retries=0)
        logs = []
        data, man = cl.backup_codeplug(link, rng=random.Random(1), log=logs.append, custom_data=custom, aes_keys=keys)
        names = set(zipfile.ZipFile(__import__("io").BytesIO(data)).namelist())
        res[(custom, keys)] = (link.stats["requests"], names, man, logs)
    base_req = res[(True, True)][0]
    check(res[(False, True)][0] < base_req and res[(True, False)][0] < base_req and res[(False, False)][0] < res[(False, True)][0],
          "T2.3: вимкнена галочка -- менше запитів до рації: %r" % {k: v[0] for k, v in res.items()})
    # різниця: частина читається + кілька випадкових блоків самоперевірки (3 для custom-data, 1 для ключів)
    check(base_req - res[(False, True)][0] == region_blocks + 3, "T2.3: без custom-data на %d запитів менше (область %d блоків + 3 самоперевірки): %d" % (region_blocks + 3, region_blocks, base_req - res[(False, True)][0]))
    check(base_req - res[(True, False)][0] == keys_blocks + 1, "T2.3: без ключів на %d запитів менше: %d" % (keys_blocks + 1, base_req - res[(True, False)][0]))
    check("customdata.bin" in res[(True, True)][1] and "aeskeys.bin" in res[(True, True)][1], "T2.3: за замовчуванням обидва файли в архіві")
    check("customdata.bin" not in res[(False, True)][1] and "customData" not in res[(False, True)][2]["parts"], "T2.3: без галочки custom-data немає ні файла, ні запису в маніфесті")
    check("aeskeys.bin" not in res[(True, False)][1] and "aesKeys" not in res[(True, False)][2]["parts"], "T2.3: без галочки ключів немає ні файла, ні запису в маніфесті")
    check(any(l.startswith("Час читання за частинами") and "область custom-data" in l for l in res[(True, True)][3]), "T2.1: бекап пише час по частинах")
    check(not any("область custom-data" in l for l in res[(False, True)][3] if l.startswith("Час читання за частинами")), "T2.3: у вимкненому варіанті фази custom-data нема")


def test_phase_timing():
    import phase_timing as pt
    ticks = iter([0.0, 2.5, 3.0, 3.0, 10.0, 10.0])
    clock = lambda: next(ticks)               # noqa: E731
    class L:
        stats = {"requests": 0, "bytes": 0}
    link = L()
    ph = pt.Phases(link, clock)
    with ph.phase("читання") as r:
        link.stats["requests"] += 4
        link.stats["bytes"] += 4096
        r["note"] = "примітка"
    check(ph.items[0]["seconds"] == 2.5 and ph.items[0]["requests"] == 4 and ph.items[0]["bytes"] == 4096, "T2.1: фаза міряє секунди, запити, байти: %r" % ph.items[0])
    try:
        with ph.phase("збій"):
            raise ValueError("x")
    except ValueError:
        pass
    check(len(ph.items) == 2 and ph.items[1]["name"] == "збій", "T2.1: фаза, що впала, теж записується")
    s = ph.summary()
    check("читання: 2.5 с, 4 запитів, 4.0 КіБ, примітка" in s and s.endswith("разом 2.5 с."), "T2.1: підсумковий рядок: %s" % s)
    check(pt.Phases(None).summary() == "", "T2.1: без фаз -- порожній рядок; без лінка лічильники нульові")


# ----------------------------------------------------------------------------------------------------------------------
#  T4.1 / T2.3: вікно бекапу
# ----------------------------------------------------------------------------------------------------------------------

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
        print("ПРОПУЩЕНО (GUI): нема DISPLAY")
        return
    from cps_ui.app import CpsApp
    from cps_ui.settings import Settings

    tmp = tempfile.mkdtemp(prefix="r32g_")
    spath = os.path.join(tmp, "ui.json")
    os.environ["TYT_CPS_SETTINGS"] = spath
    os.environ["HOME"] = tmp
    app = CpsApp(settings=Settings(spath), autoprobe=False)
    try:
        app.geometry("1300x900")
        app.update()
        app.show("backup")
        _spin(app)
        bp = app.get_panel("backup")
        t = bp.contents_note.cget("text")
        check(t == "У архіві буде: EEPROM, флеш-кодплаг, область custom-data, ключі AES (секрет).", "T4.1/CH4: типовий склад архіву одним рядком: %s" % t)
        bp.custom_var.set(False)
        bp._update_keys_note()
        check("custom-data" not in bp.contents_note.cget("text") and "ключі AES" in bp.contents_note.cget("text"), "T4.1: без custom-data рядок це показує: %s" % bp.contents_note.cget("text"))
        bp.keys_var.set(False)
        bp.full_snapshot_var.set(True)
        bp._update_keys_note()
        t = bp.contents_note.cget("text")
        check(t == "У архіві буде: EEPROM, флеш-кодплаг, сира область 0xAF400..0xD8000, база позивних.", "T4.1: повний знімок без ключів і без custom-data: %s" % t)
        check(bp.custom_var.get() is False and "НЕ міститиме ключів AES" in bp.keys_note.cget("text"), "T4.1: окремий рядок про ключі збережено")
        bp.custom_var.set(True)
        bp.keys_var.set(True)
        bp.full_snapshot_var.set(False)
        bp._update_keys_note()
        check(bp.contents_note.cget("text").startswith("У архіві буде: EEPROM"), "T4.1: повернення до типового")
        # галочка доходить до читання: воркер передає custom_data у backup_codeplug
        seen = {}
        orig = cl.backup_codeplug

        class _Ser:
            def close(self):
                pass
        orig_open = cl.open_radio
        cl.open_radio = lambda *a, **k: _Ser()

        def spy(link, progress=None, **kw):
            seen.update(kw)
            raise cl.CpsError("зупинено тестом")
        cl.backup_codeplug = spy
        try:
            try:
                bp._backup_worker(False, True, False)
            except cl.CpsError:
                pass
        finally:
            cl.backup_codeplug = orig
            cl.open_radio = orig_open
        check(seen.get("custom_data") is False and seen.get("aes_keys") is True, "T2.3/CH2: вимкнена галочка custom-data доходить до backup_codeplug: %r" % seen)
    finally:
        try:
            app.destroy()
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(tmp, ignore_errors=True)


# ----------------------------------------------------------------------------------------------------------------------
#  --measure: таблиця для звіту
# ----------------------------------------------------------------------------------------------------------------------

def measure():
    print("Підроблена рація (запити/КіБ -- справжні лічильники; секунди на підробленій рації нічого не означають, їх міряє CH1 на залізі)")
    for pre in (False, True):
        with tempfile.TemporaryDirectory() as d:
            radio, link, cp, res = fresh_setup(d)
            ph = None
            import phase_timing as pt
            ph = pt.Phases(link)
            with ph.phase("свіже читання рації"):
                cp2, _m = cv.codeplug_from_radio(link)
            with tcr.Unlocked():
                cc.write_image_via_restore(link, res, lambda t, p: True, log=quiet, out_dir=d, prefetched=(cp2.eeprom, cp2.flash) if pre else None, phases=ph)
            print("\n%s:" % ("з переданим образом (T2.2)" if pre else "як було (повторне читання)"))
            tot_r = tot_b = 0
            for p in ph.items:
                print("  %-28s %5d запитів  %7.1f КіБ  %s" % (p["name"], p["requests"], p["bytes"] / 1024.0, p["note"]))
                tot_r += p["requests"]
                tot_b += p["bytes"]
            print("  %-28s %5d запитів  %7.1f КіБ" % ("РАЗОМ читання", tot_r, tot_b / 1024.0))


def main():
    if "--measure" in sys.argv:
        measure()
        return 0
    import faulthandler
    faulthandler.dump_traceback_later(400, exit=True)
    old_sleep = time.sleep
    time.sleep = lambda _s: None
    try:
        for t in (test_terminology, test_sources, test_unrecognized, test_phase_timing, test_prefetched, test_backup_switches, test_gui):
            try:
                t()
            except Exception as e:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                FAILS.append("%s: виняток %r" % (t.__name__, e))
    finally:
        time.sleep = old_sleep
    if FAILS:
        print("test_r32: ПРОВАЛЕНО перевірок: %d" % len(FAILS))
        return 1
    print("test_r32: усе гаразд (перевірка термінології, розбір джерел із testdata, виміри фаз і передача образу, склад архіву).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
