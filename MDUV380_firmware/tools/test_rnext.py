# -*- coding: utf-8 -*-
"""R-next (Y2-Y5, Z1-Z4): загальні налаштування, екран вітання, DTMF-редактор, VFO. Логіка -- у будь-якому python3; GUI -- лише з tkinter + DISPLAY
(`xvfb-run -a python3.12 tools/test_rnext.py`; інакше частину з Tk пропущено й сказано про це)."""
import os
import re
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cps_csv as cc                     # noqa: E402
import cps_link as cl                    # noqa: E402
import codeplug_edit as ced              # noqa: E402
import general_edit as ge                # noqa: E402
import table_edit as te                  # noqa: E402
import vfo_edit as ve                    # noqa: E402
import test_cps_csv as tc                # noqa: E402
import test_cps_restore as tr            # noqa: E402

FAILS = []
APP = os.path.join(HERE, "..", "application")
DP = ","


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def fixture_img(blank=False):
    spi = tc.base.make_spi() if blank else tc.make_fixture_spi()
    cp, _data = tc.codeplug_of(spi)
    return cc.Image.from_codeplug(cp), spi, cp


def diff_addrs(a, b):
    return [i for i in range(len(a.eeprom)) if a.eeprom[i] != b.eeprom[i]]


def refused(fn, *a, **k):
    try:
        fn(*a, **k)
    except (te.TableEditError, ced.CodeplugEditError) as e:
        return e
    return None


# ----------------------------------------------------------------------------------------------------------------------
#  Зв'язок з кодом прошивки: адреси й межі в інструментах = ті, що в C
# ----------------------------------------------------------------------------------------------------------------------

def test_firmware_constants():
    c = open(os.path.join(APP, "source", "functions", "codeplug.c"), encoding="utf-8").read()
    h = open(os.path.join(APP, "include", "functions", "codeplug.h"), encoding="utf-8").read()
    trx = open(os.path.join(APP, "source", "functions", "trx.c"), encoding="utf-8").read()
    ui = open(os.path.join(APP, "source", "user_interface", "uiUtilities.c"), encoding="utf-8").read()

    def const(name):
        m = re.search(r"const int %s\s*=\s*(0x[0-9A-Fa-f]+)" % name, c)
        return int(m.group(1), 16) if m else None
    check(const("CODEPLUG_ADDR_BOOT_PASSWORD_ENABLE") == ge.ADDR_PWD_FLAGS, "адреса прапорця пароля = codeplug.c")
    check(const("CODEPLUG_ADDR_BOOT_PASSWORD_AREA") == ge.ADDR_PWD_PIN, "адреса PIN = codeplug.c")
    check(const("CODEPLUG_ADDR_BOOT_INTRO_SCREEN") == ced.ADDR_BOOT_INTRO, "адреса типу екрана вітання = codeplug.c")
    check(const("CODEPLUG_ADDR_BOOT_LINE1") == ced.ADDR_BOOT_LINE1 and const("CODEPLUG_ADDR_BOOT_LINE2") == ced.ADDR_BOOT_LINE2, "адреси рядків вітання")
    check(const("CODEPLUG_ADDR_VFO_A_CHANNEL") == ve.ADDR_VFO_A, "адреса VFO A = codeplug.c")
    check(const("CODEPLUG_ADDR_DTMF_CONTACTS") == cc.ADDR_DTMF, "адреса DTMF-контактів = codeplug.c")
    base = const("CODEPLUG_ADDR_SIGNALLING_DTMF")
    off = int(re.search(r"CODEPLUG_ADDR_SIGNALLING_DTMF_DURATIONS = \(CODEPLUG_ADDR_SIGNALLING_DTMF \+ (0x[0-9A-Fa-f]+)\)", c).group(1), 16)
    check(base + off == ge.ADDR_DTMF_DURATIONS == ge.DTMF_FIELDS[0][1], "адреса тривалостей DTMF = codeplug.c")
    check([f[1] for f in ge.DTMF_FIELDS] == [ge.ADDR_DTMF_DURATIONS + k for k in range(5)], "п'ять тривалостей -- підряд")
    st = re.search(r"typedef struct\s*\{\s*uint8_t\s+fstDigitDly;.*?\}\s*CodeplugSignallingDTMFDurations_t", h, re.S).group(0)
    names = re.findall(r"uint8_t\s+(\w+);", st)
    check(names == ["fstDigitDly", "fstDur", "otherDur", "rate", "libreDMR_Tail"], "порядок полів тривалостей у структурі: %r" % names)
    check(re.search(r"CODEPLUG_CHANNEL_DATA_STRUCT_SIZE\s+56", h) is not None and ve.VFO_SIZE == 56, "розмір запису VFO = 56")
    check("fstDur * 10" in ui and "otherDur * 10" in ui and "fstDigitDly * 100" in ui and "libreDMR_Tail * 100" in ui and "1000 / (uiDataGlobal.DTMFContactList.durations.rate * 2)" in ui,
          "одиниці тривалостей (x10, x100 мс; 1000/(rate*2)) -- як у uiUtilities.c")
    check("libreDMR_Tail > 10" in c, "хвіст > 10 прошивка підміняє -- межа 0..10")
    bands = re.search(r"#else\s*const frequencyHardwareBand_t RADIO_HARDWARE_FREQUENCY_BANDS.*?\n};", trx, re.S).group(0)
    nums = [int(x) for x in re.findall(r"\.(?:minFreq|maxFreq)=(\d+)", bands)]
    # у збірці з ENABLE_SPECTRUM VHF мінімум нижчий -- беремо звичайну гілку (#else всередині)
    flat = [x for lo, hi in ve.HARDWARE_BANDS for x in (lo, hi)]
    check(flat[1:] == nums[-5:] and flat[0] == 12700000 and 12700000 in nums, "діапазони VFO = trx.c: %r / %r" % (flat, nums))
    check("CODEPLUG_DTMF_CONTACTS_MAX" in h and "63" in re.search(r"CODEPLUG_DTMF_CONTACTS_MAX\s+(\d+)", h).group(1) and cc.DTMF_MAX == 63, "DTMF: максимум 63")


# ----------------------------------------------------------------------------------------------------------------------
#  Y2: загальні налаштування
# ----------------------------------------------------------------------------------------------------------------------

def test_general():
    for pin in ("1", "12", "123456", "007", "000000"):
        check(ge.pin_decode(ge.pin_encode(pin)) == (pin, False), "PIN %s: запис -> читання" % pin)
    check(ge.pin_encode("1234") == bytes([0x12, 0x34, 0xFF]) and ge.pin_encode("123") == bytes([0x12, 0x3F, 0xFF]), "PIN у BCD, дописка нібблами 0xF")
    check(ge.pin_decode(bytes([0x1A, 0xFF, 0xFF])) == ("1?", True), "нестандартний ніббл розпізнано")
    img, _spi, _cp = fixture_img()
    cur = ge.general_values(img)
    check(cur["pwd_enable"] is False and cur["pwd_pin"] == "" and cur["dtmf_rate"] == 255 and img.eeprom[0x7519] == 0xFF,
          "порожній кодплаг: біт 0x7519 піднято, але PIN нема -- пароль НЕ питатиметься (pwd_enable=False); байти DTMF = 0xFF: %r" % cur)
    bad = ge.check_values({"pwd_enable": True, "pwd_pin": "", "dtmf_first_delay": 1, "dtmf_first_dur": 1, "dtmf_other_dur": 1, "dtmf_rate": 0, "dtmf_tail": 11})
    check(set(bad) == {"pwd_pin", "dtmf_rate", "dtmf_tail"}, "межі: швидкість 0, хвіст 11, пароль без PIN: %r" % bad)
    check("pwd_pin" in ge.check_values({"pwd_enable": False, "pwd_pin": "12a", "dtmf_first_delay": 1, "dtmf_first_dur": 1, "dtmf_other_dur": 1,
                                        "dtmf_rate": 1, "dtmf_tail": 1}), "PIN лише цифри")
    check("pwd_pin" in ge.check_values({"pwd_enable": True, "pwd_pin": "١٢٣", "dtmf_first_delay": 1, "dtmf_first_dur": 1, "dtmf_other_dur": 1,
                                        "dtmf_rate": 1, "dtmf_tail": 1}), "арабські цифри не PIN")
    check("pwd_pin" in ge.check_values({"pwd_enable": True, "pwd_pin": "1234567"}), "PIN довше 6 цифр відхилено")
    # запис: змінюються лише потрібні байти
    img.eeprom[0x7519] = 0xA4
    img.eeprom[0x751C:0x751F] = b"\xff\xff\xff"
    img.eeprom[0x751A], img.eeprom[0x751B] = 0x5A, 0x6B
    res = ge.apply_general(img, pwd_enable=True, pwd_pin="4321", dtmf_rate=4, dtmf_tail=3)
    new = res.image
    changed = diff_addrs(img, new)
    check(changed == [0x1475, 0x1476, 0x7519, 0x751C, 0x751D], "змінено рівно потрібні адреси: %r" % [hex(a) for a in changed])
    check(new.eeprom[0x7519] == 0xA5 and new.eeprom[0x751A] == 0x5A and new.eeprom[0x751B] == 0x6B, "біт 0 прапорця; решта біт і байти 0x751A/B цілі")
    check(bytes(new.eeprom[0x751C:0x751F]) == bytes([0x43, 0x21, 0xFF]) and new.eeprom[0x1475] == 4 and new.eeprom[0x1476] == 3, "PIN і тривалості записано")
    check(bytes(new.flash) == bytes(img.flash) and bytes(img.eeprom[0x7519:0x751A]) == bytes([0xA4]), "вихідний образ і флеш не змінено")
    v = ge.general_values(new)
    check(v["pwd_enable"] and v["pwd_pin"] == "4321" and v["dtmf_rate"] == 4, "читання назад")
    res2 = ge.apply_general(new, pwd_enable=False)
    check(res2.image.eeprom[0x7519] == 0xA4 and bytes(res2.image.eeprom[0x751C:0x751F]) == bytes([0x43, 0x21, 0xFF]), "вимкнення знімає лише біт; PIN лишається")
    check(not ge.apply_general(new, pwd_enable=True, pwd_pin="4321", dtmf_rate=4).changed and diff_addrs(new, ge.apply_general(new).image) == [], "те саме -> байтів не змінює")
    check(refused(ge.apply_general, new, dtmf_rate=0) is not None and refused(ge.apply_general, new, dtmf_tail=11) is not None, "швидкість 0 / хвіст 11 відхилено")
    check(refused(ge.apply_general, img, pwd_enable=True) is not None, "увімкнути пароль без PIN -- відмова")
    # поле поза межами в кодплузі не заважає змінити пароль (перевіряються лише змінені поля)
    check(ge.apply_general(img, pwd_enable=True, pwd_pin="1").image.eeprom[0x7519] & 1 == 1, "255 у швидкості не блокує зміну пароля")
    rows = ge.field_table()
    check(len(rows) == 7 and all(len(r) == 4 for r in rows) and "0x1475" in rows[5][1], "таблиця поле -> адреса -> діапазон: 7 рядків")


# ----------------------------------------------------------------------------------------------------------------------
#  Y3: тип екрана вітання
# ----------------------------------------------------------------------------------------------------------------------

def test_intro():
    img, _spi, _cp = fixture_img()
    check(ced.basic_values(img)["intro_text"] is True, "байт 0xFF прошивка читає як «текст» (bootScreenType != 0)")
    r = ced.apply_basic_info(img, intro_text=True)
    check(not r.changed and diff_addrs(img, r.image) == [], "«текст» при вже ненульовому байті не чіпає його")
    r = ced.apply_basic_info(img, intro_text=False)
    check(r.image.eeprom[0x7518] == 0 and diff_addrs(img, r.image) == [0x7518], "«картинка» -> 0")
    r2 = ced.apply_basic_info(r.image, intro_text=True)
    check(r2.image.eeprom[0x7518] == 1 and diff_addrs(r.image, r2.image) == [0x7518], "«текст» -> 1")
    r3 = ced.apply_basic_info(img, line1="Привіт", line2="CQ UA", intro_text=True)
    check(ced.basic_values(r3.image)["line1"] == "Привіт", "рядки вітання як раніше")


# ----------------------------------------------------------------------------------------------------------------------
#  Y4 / Z2: DTMF-редактор
# ----------------------------------------------------------------------------------------------------------------------

def test_dtmf():
    img, _spi, _cp = fixture_img()
    base = te.dtmf_contacts(img)
    r = te.dtmf_add(img, "Тест", "123#a", DP)
    got = te.dtmf_contacts(r.image)
    check(len(got) == len(base) + 1 and got[-1][1:] == ("Тест", "123#A"), "додано: %r" % got)
    check(bytes(r.image.eeprom[0x2F88 + 32 + 16:0x2F88 + 32 + 21]) == bytes([1, 2, 3, 15, 10]), "байти коду: індекс у «0123456789ABCD*#»")
    check(bytes(r.image.eeprom[0x2F88 + 32 + 21:0x2F88 + 64]) == b"\xff" * 11, "код добито 0xFF (кінець коду)")
    # Z2: межі
    for name, code, what in (("", "1", "порожня назва"), ("A" * 17, "1", "назва 17 байтів"), ("Ok", "", "порожній код"), ("Ok", "1" * 17, "код 17 знаків"),
                             ("Ok", "12E", "знак поза алфавітом"), ("Test DTMF", "1", "дубль назви")):
        before = (bytes(img.eeprom), bytes(img.flash))
        e = refused(te.dtmf_add, img, name, code, DP)
        check(e is not None and before == (bytes(img.eeprom), bytes(img.flash)), "відмова і нічого не змінено: %s" % what)
    ok16 = te.dtmf_add(img, "N" * 16, "1" * 16, DP)
    check(te.dtmf_contacts(ok16.image)[-1][2] == "1" * 16, "16 знаків коду і 16 байтів імені приймаються")
    # зміна коду, перейменування, дублювання, видалення
    r = te.dtmf_set_code(img, 0, "9 *", DP)
    check(te.dtmf_contacts(r.image)[0][1:] == ("Test DTMF", "9*"), "код змінено, ім'я лишилось")
    r = te.rename_entity(img, "dtmf", 0, "Новий", DP)
    check(te.dtmf_contacts(r.image)[0][1:] == ("Новий", "123ABCD*") and diff_addrs(img, r.image) != [], "перейменовано, код цілий")
    check(refused(te.rename_entity, te.dtmf_add(img, "Другий", "5", DP).image, "dtmf", 0, "Другий", DP) is not None, "перейменування на наявну назву відмовлено")
    d = te.duplicate_entity(img, "dtmf", 0, DP)
    check(len(te.dtmf_contacts(d.image)) == len(base) + 1 and te.dtmf_contacts(d.image)[-1][2] == base[0][2], "копія: нова назва, той самий код")
    check(not te.references(img, "dtmf", 0), "на DTMF-контакт ніхто не посилається")
    r = te.delete_entity(img, "dtmf", 0, DP)
    check(te.dtmf_contacts(r.image) == [] and bytes(r.image.eeprom[0x2F88:0x2F88 + 32]) == b"\xff" * 32, "видалено: слот чистий (0xFF)")
    # заповнення до межі 63
    cur = img
    for k in range(len(base), cc.DTMF_MAX):
        cur = te.dtmf_add(cur, "C%02d" % k, "1", DP).image
    check(len(te.dtmf_contacts(cur)) == 63, "заповнено 63")
    e = refused(te.dtmf_add, cur, "Зайвий", "1", DP)
    check(e is not None and "вільного місця" in "\n".join(e.problems), "64-й відхилено з поясненням: %r" % (e.problems if e else None))
    # дві правки в різних контактах -- чужі байти не зачеплено
    two = te.dtmf_add(img, "Другий", "5", DP).image
    r = te.dtmf_set_code(two, 1, "77", DP)
    check(bytes(r.image.eeprom[0x2F88:0x2F88 + 32]) == bytes(two.eeprom[0x2F88:0x2F88 + 32]), "правка одного контакту не чіпає інших")


# ----------------------------------------------------------------------------------------------------------------------
#  Y5: VFO
# ----------------------------------------------------------------------------------------------------------------------

def test_vfo():
    img, _spi, _cp = fixture_img()
    check(ve.vfo_values(img, 0, DP)["freq_ok"] is False, "порожній VFO (0xFF): частота не в діапазоні, про це сказано")
    r = ve.vfo_init(img, 0, DP)
    check(ve.vfo_values(r.image, 0, DP)["freq_ok"] and diff_addrs(img, r.image) and all(0x7590 <= a < 0x75C8 for a in diff_addrs(img, r.image)),
          "заповнення типовим: змінено лише VFO A")
    cur = r.image
    r = ve.vfo_edit(cur, 0, {"Rx Frequency": "433,5", "Tx Frequency": "438,1", "RX Tone": "67,0", "Bandwidth (kHz)": "25"}, DP)
    v = ve.vfo_values(r.image, 0, DP)
    check(v["Rx Frequency"] == "433,50000" and v["Tx Frequency"] == "438,10000" and v["RX Tone"] == "67,0" and v["Bandwidth (kHz)"] == "25", "поля: %r" % v)
    check(all(0x7590 <= a < 0x75C8 for a in diff_addrs(cur, r.image)), "змінено лише байти VFO A (0x7590..0x75C7)")
    check(bytes(r.image.eeprom[0x75C8:0x7600]) == bytes(cur.eeprom[0x75C8:0x7600]), "VFO B не зачеплено")
    # межі
    for ch, what in (({"Rx Frequency": "50"}, "RX поза діапазоном"), ({"Tx Frequency": "700"}, "TX поза діапазоном"), ({"Rx Frequency": "abc"}, "не число"),
                     ({"Bandwidth (kHz)": "7"}, "смуга"), ({"RX Tone": "999"}, "тон"), ({"Channel Name": "x"}, "назва VFO не редагується"),
                     ({"Zone Skip": "Yes"}, "прапорець зони не для VFO")):
        before = bytes(cur.eeprom)
        e = refused(ve.vfo_edit, cur, 0, ch, DP)
        check(e is not None and bytes(cur.eeprom) == before, "відмова: %s" % what)
    r = ve.vfo_edit(cur, 1, {"Rx Frequency": "145,5", "Tx Frequency": "145,5"}, DP)
    check(bytes(r.image.eeprom[0x7590:0x75C8]) == bytes(cur.eeprom[0x7590:0x75C8]), "правка VFO B не чіпає VFO A")
    # цифровий VFO: контакт і список
    r = ve.vfo_edit(cur, 0, {"Channel Type": "Digital"}, DP)
    r = ve.vfo_edit(r.image, 0, {"Colour Code": "3", "Timeslot": "2"}, DP, refs={"Contact": 1, "TG List": 1})
    v = ve.vfo_values(r.image, 0, DP)
    check(v["Channel Type"] == "Digital" and v["Colour Code"] == "3" and v["Timeslot"] == "2" and ve.vfo_refs(r.image, 0) == {"Contact": 1, "TG List": 1}, "цифровий VFO: %r" % v)
    check(refused(ve.vfo_edit, r.image, 0, {}, DP, refs={"Contact": 999}) is not None, "контакт, якого нема, відмовлено")
    # запис у рацію звичайним відновленням: байти VFO доходять, C 6 1 останньою, калібрування ціле
    spi = tc.make_fixture_spi()
    spi[0x10000:0x10010] = b"CALIB-A-CALIB-A!"
    import test_cps_doc as td
    import cps_ui.document as D
    cp, _data = tc.codeplug_of(spi)
    doc = D.Document(cp, D.ORIGIN_RADIO, source_file="x")
    doc.apply(ve.vfo_init(doc.image, 0, DP))
    doc.apply(ve.vfo_edit(doc.image, 0, {"Rx Frequency": "433,5", "Tx Frequency": "433,5"}, DP))
    want = bytes(doc.image.eeprom[0x7590:0x75C8])
    with tempfile.TemporaryDirectory() as d:
        radio = td.ClosableRadio(bytearray(spi))
        fresh = cc.Image.from_codeplug(tc.cv.codeplug_from_radio(cl.CpsLink(radio, retries=0))[0])
        res, conflicts = doc.write_image(fresh)
        with tr.Unlocked():
            out = cc.write_image_via_restore(cl.CpsLink(radio, retries=0), res, lambda t, p: True, log=lambda *_: None, title="ТЕСТ", out_dir=d,
                                             zip_prefix="codeplug_document-write")
        check(out["sectorsWritten"] >= 1 and radio.c_calls[-1] == bytes([6, 1]), "VFO записано звичайним відновленням, C 6 1 останньою")
        check(bytes(radio.spi[0x7590:0x75C8]) == want, "у рації лежить VFO A, який змінено в документі")
        check(bytes(radio.spi[0x10000:0x10010]) == b"CALIB-A-CALIB-A!" and not radio.cal_touched, "калібрування не чіпали")


# ----------------------------------------------------------------------------------------------------------------------
#  Z3: експорт -> імпорт без правок = той самий образ (з усіма новими полями)
# ----------------------------------------------------------------------------------------------------------------------

def test_roundtrip():
    import cps_ui.document as D
    img, _spi, cp = fixture_img()
    doc = D.Document(cp, D.ORIGIN_FILE, source_file="x")
    doc.apply(ve.vfo_init(doc.image, 0, DP))
    doc.apply(te.dtmf_add(doc.image, "Київ", "380#", DP))
    doc.edit_general(pwd_enable=True, pwd_pin="2024", dtmf_rate=5, dtmf_tail=2, dtmf_first_delay=3, dtmf_first_dur=4, dtmf_other_dur=6)
    doc.edit_basic(intro_text=False, line1="Привіт")
    snap = (bytes(doc.image.eeprom), bytes(doc.image.flash))
    with tempfile.TemporaryDirectory() as d:
        doc.export_csv(d, DP, log=lambda *_: None)
        res = doc.import_csv(cc.read_dir(d), DP)
    check(not res.any_change() and snap == (bytes(doc.image.eeprom), bytes(doc.image.flash)), "Z3: експорт -> імпорт без правок -- образ байт-у-байт той самий")
    # імпорт CSV не зачіпає загальні налаштування й VFO (їх у CSV нема)
    other = D.Document(cp, D.ORIGIN_FILE, source_file="y")
    with tempfile.TemporaryDirectory() as d:
        doc.export_csv(d, DP, log=lambda *_: None)
        other.import_csv(cc.read_dir(d), DP)
    check(bytes(other.image.eeprom[0x7518:0x7519]) == b"\xff" and bytes(other.image.eeprom[0x7590:0x75C8]) == b"\xff" * 56, "CSV не переносить пароль/VFO/екран вітання")
    check(te.dtmf_contacts(other.image)[-1][1:] == ("Київ", "380#"), "а DTMF-контакт переноситься")


# ----------------------------------------------------------------------------------------------------------------------
#  Z1: GUI
# ----------------------------------------------------------------------------------------------------------------------

def _all(w):
    yield w
    for c in w.winfo_children():
        yield from _all(c)


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
    import tkinter.messagebox as mb
    import gui_dialogs as gd
    import cps_ui.document as D
    from cps_ui.app import CpsApp
    from cps_ui.settings import Settings

    tmp = tempfile.mkdtemp(prefix="rnext_")
    spath = os.path.join(tmp, "ui.json")
    os.environ["TYT_CPS_SETTINGS"] = spath
    os.environ["HOME"] = tmp
    app = CpsApp(settings=Settings(spath), autoprobe=False)
    errors = []
    mb.showinfo = lambda *a, **k: None
    mb.showerror = lambda *a, **k: errors.append(a)
    gd.confirm_dialog = lambda *a, **k: True
    try:
        app.geometry("1200x900")
        app.update()
        # --- Z1: без документа кожна нова панель відкривається й показує підказку ---
        for key in ("basic", "general", "vfo", "dtmf"):
            app.show(key)
            _spin(app)
            p = app.get_panel(key)
            check(p.hint.winfo_manager() == "pack", "Z1: %s без документа -- підказка «Відкрийте кодплаг…»" % key)
        # --- порожній кодплаг (усе 0xFF) ---
        src = os.path.join(tmp, "blank.zip")
        spi_b = tc.base.make_spi()
        _cp, data = tc.codeplug_of(spi_b)
        with open(src, "wb") as f:
            f.write(data)
        check(app.doc_open_file(src), "відкрито порожній кодплаг")
        for key in ("basic", "general", "vfo", "dtmf"):
            app.show(key)
            _spin(app)
            check(app.get_panel(key).hint.winfo_manager() == "", "Z1: %s з порожнім кодплагом відкрилась" % key)
        # --- повна фікстура ---
        _cp, data = tc.codeplug_of(tc.make_fixture_spi())
        src = os.path.join(tmp, "full.zip")
        with open(src, "wb") as f:
            f.write(data)
        check(app.doc_open_file(src), "відкрито фікстуру")
        # Y2: загальні налаштування
        app.show("general")
        _spin(app)
        gp = app.get_panel("general")
        check(str(gp.apply_button.cget("state")) == "disabled", "загальні: без змін «Застосувати» вимкнена")
        gp.dt["dtmf_rate"].set("0")
        _spin(app)
        check(str(gp.apply_button.cget("state")) == "disabled" and "1..10" in gp.infos["dtmf_rate"].cget("text"), "загальні: швидкість 0 -- помилка й кнопка вимкнена: %s" % gp.infos["dtmf_rate"].cget("text"))
        gp.dt["dtmf_rate"].set("5")
        _spin(app)
        check(str(gp.apply_button.cget("state")) == "normal", "загальні: 5 -- можна застосувати")
        gp.enable.set(True)
        _spin(app)
        check(str(gp.apply_button.cget("state")) == "disabled", "загальні: пароль без PIN -- не можна")
        gp.pin.set("12ab")
        _spin(app)
        check(str(gp.apply_button.cget("state")) == "disabled" and gp.infos["pwd_pin"].cget("text"), "загальні: PIN з літерами відхилено")
        gp.pin.set("2468")
        _spin(app)
        gp._on_apply()
        _spin(app)
        v = ge.general_values(app.doc.image)
        check(v["pwd_enable"] and v["pwd_pin"] == "2468" and v["dtmf_rate"] == 5 and app.doc.modified, "загальні: застосовано до документа %r" % v)
        gp.on_document_changed()
        check(gp.pin.get() == "2468" and gp.enable.get() and gp.dt["dtmf_rate"].get() == "5", "загальні: форма читає документ назад")
        # Y3: екран вітання
        app.show("basic")
        _spin(app)
        bp = app.get_panel("basic")
        check(bp.intro_var.get().startswith("Текст"), "вітання: байт 0xFF показано як «Текст»")
        bp.intro_var.set("Картинка")
        bp._validate()
        _spin(app)
        check(str(bp.apply_button.cget("state")) == "normal", "вітання: зміна типу вмикає «Застосувати»")
        bp._on_apply()
        _spin(app)
        check(app.doc.image.eeprom[0x7518] == 0, "вітання: у документі 0x7518 = 0")
        check("НЕ малюються" in bp.intro_label.cget("text"), "вітання: пояснено, що в українській збірці рядки на екран не виходять")
        # Y4: DTMF
        app.show("dtmf")
        _spin(app)
        dp_ = app.get_panel("dtmf")
        check(len(dp_.tree.get_children()) == 1, "DTMF: у списку один контакт із фікстури")
        gd_two = gd.two_field_dialog
        before = bytes(app.doc.image.eeprom)
        gd.two_field_dialog = lambda *a, **k: None
        dp_._on_add()
        _spin(app)
        check(bytes(app.doc.image.eeprom) == before, "DTMF: «Скасувати» в діалозі додавання нічого не міняє")
        gd.two_field_dialog = lambda *a, **k: ("Київ", "380#")
        dp_._on_add()
        _spin(app)
        check(len(dp_.tree.get_children()) == 2 and te.dtmf_contacts(app.doc.image)[-1][1:] == ("Київ", "380#"), "DTMF: додано через діалог")
        check(dp_.sel == 1, "DTMF: новий контакт вибрано")
        dp_.code_var.set("77")
        _spin(app)
        check(str(dp_.code_apply.cget("state")) == "normal", "DTMF: зміна коду вмикає «Застосувати код»")
        dp_.code_var.set("77Z")
        _spin(app)
        check(str(dp_.code_apply.cget("state")) == "disabled" and "недопустимий" in dp_.code_info.cget("text"), "DTMF: поганий код -- пояснення й вимкнена кнопка")
        dp_.code_var.set("77")
        dp_.commit_code()
        _spin(app)
        check(te.dtmf_contacts(app.doc.image)[-1][2] == "77", "DTMF: код змінено")
        gd.name_dialog = lambda *a, **k: "Львів"
        dp_._on_rename()
        _spin(app)
        check(te.dtmf_contacts(app.doc.image)[-1][1] == "Львів", "DTMF: перейменовано")
        dp_._on_dup()
        _spin(app)
        check(len(te.dtmf_contacts(app.doc.image)) == 3, "DTMF: дубльовано")
        dp_._on_delete()
        _spin(app)
        check(len(te.dtmf_contacts(app.doc.image)) == 2, "DTMF: видалено (підтвердження)")
        gd.two_field_dialog = gd_two
        # Y5: VFO
        app.show("vfo")
        _spin(app)
        vp = app.get_panel("vfo")
        check(vp.init_button.winfo_manager() == "pack" and "порожній" in vp.state_label.cget("text"), "VFO: порожній VFO -- пояснення й кнопка заповнення")
        vp._on_init()
        _spin(app)
        check(ve.vfo_values(app.doc.image, 0, vp.dp)["freq_ok"] and vp.init_button.winfo_manager() == "", "VFO: заповнено типовими")
        vp.vars["Rx Frequency"].set("50")
        _spin(app)
        vp._on_apply()
        _spin(app)
        check("поза діапазонами" in vp.info.cget("text"), "VFO: частота поза діапазоном -- відмова словами: %s" % vp.info.cget("text"))
        vp.on_document_changed()
        vp.vars["Rx Frequency"].set("433" + vp.dp + "5")
        vp.vars["Tx Frequency"].set("433" + vp.dp + "5")
        _spin(app)
        check(str(vp.apply_button.cget("state")) == "normal", "VFO: правильні частоти -- можна застосувати")
        vp._on_apply()
        _spin(app)
        check(ve.vfo_values(app.doc.image, 0, vp.dp)["Rx Frequency"].startswith("433"), "VFO: у документі 433,5")
        vp.vars["Channel Type"].set("Цифровий")
        vp._on_type()
        _spin(app)
        check(ve.vfo_values(app.doc.image, 0, vp.dp)["Channel Type"] == "Digital" and str(vp.widgets["Colour Code"].cget("state")) != "disabled", "VFO: тип «Цифровий» -- відкрились цифрові поля")
        vp.which.set(1)
        vp._on_switch()
        _spin(app)
        check(vp.init_button.winfo_manager() == "pack", "VFO B окремо: порожній")
    finally:
        app.destroy()
    check(not errors, "GUI: messagebox.showerror не викликався: %r" % (errors[:2],))


def main():
    import faulthandler
    faulthandler.dump_traceback_later(150, exit=True)
    for t in (test_firmware_constants, test_general, test_intro, test_dtmf, test_vfo, test_roundtrip, test_gui):
        try:
            t()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILS.append("%s: виняток %r" % (t.__name__, e))
    if FAILS:
        print("test_rnext: ПРОВАЛЕНО перевірок: %d" % len(FAILS))
        return 1
    print("test_rnext: усе гаразд (константи = прошивка, загальні налаштування, вітання, DTMF-редактор, VFO, експорт->імпорт, панелі).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
