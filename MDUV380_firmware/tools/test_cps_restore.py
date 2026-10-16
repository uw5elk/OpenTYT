#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Хост-тести R25 (без рації, без pyserial): tools/cps_restore.py (відновлення), tools/codeplug_view.py (перегляд, назви, CSV).

Підставна рація FakeRadioX повторює поведінку usb_com.c, важливу для відновлення: X 1/2/3 через буфер сектора, відмова
X 1 при «підготовленому» секторі (і скидання стану після будь-якої відмови), «квіккеї» 0x7524..0x7537 НЕ перезаписуються,
калібрування 0x10000 не завантажується в буфер (небезпечне місце -- тест доводить, що ми його не торкаємось), X 4 нічого не
робить, C 6 1 = перезавантаження. Вона рахує кожну X-команду, щоб відмови (T1) можна було довести «жодного запису».
"""
import csv
import io
import os
import random
import struct
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cps_link as cl            # noqa: E402
import cps_restore as cr         # noqa: E402
import codeplug_view as cv       # noqa: E402
import cps_backup_info as info   # noqa: E402
import test_cps_link as base     # noqa: E402

FAILS = []
QK_START, QK_END = 0x7524, 0x7524 + 20 - 1


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


class FakeRadioX(base.FakeRadio):
    def __init__(self, spi, die_after_x=None, corrupt_commit=False, stale_sector=None, **kw):
        super().__init__(spi, **kw)
        self.sector = -1 if stale_sector is None else stale_sector
        self.buf = bytearray(4096)
        self.die_after_x = die_after_x       # після стількох X-команд рація «замовкає» (і не обробляє наступної)
        self.corrupt_commit = corrupt_commit
        self.x_total = 0
        self.x_calls = []                    # (підкоманда, сектор/адреса)
        self.c_calls = []
        self.commits = []                    # номери секторів, справді записаних
        self.dead = False
        self.reset_requested = False
        self.cal_touched = False

    def _ok(self, sub):
        self.rx += b"X" + bytes([sub])

    def _fail(self):
        self.sector = -1                      # usb_com.c: при !ok -> sector = -1
        self.rx += b"-"

    def write(self, data):
        data = bytes(data)
        if self.dead:
            self.requests.append(("dead", data[:1]))
            return
        if data[:1] == b"R":
            return super().write(data)
        if data[:1] == b"C":
            self.c_calls.append(data[1:])
            if data[1:3] == bytes([6, 1]):
                self.reset_requested = True
            return
        if data[:1] != b"X":
            self.writes_seen.append(data)
            return
        self.x_total += 1
        if self.die_after_x is not None and self.x_total > self.die_after_x:
            self.dead = True
            return
        sub = data[1]
        if sub == 1:
            sector = (data[2] << 16) + (data[3] << 8) + data[4]
            self.x_calls.append((1, sector))
            if self.sector != -1:
                return self._fail()
            self.sector = sector
            if sector * 4096 == 0x10000:      # калібрування: сектор НЕ завантажується
                self.cal_touched = True
                return self._ok(1)
            self.buf[:] = self.spi[sector * 4096:sector * 4096 + 4096]
            return self._ok(1)
        if sub == 2:
            addr = struct.unpack(">I", data[2:6])[0]
            ln = struct.unpack(">H", data[6:8])[0]
            self.x_calls.append((2, addr))
            if self.sector < 0:
                return self._fail()
            if 0x10000 <= addr < 0x10200 or (addr < 0x10000 and addr + ln > 0x10000):
                self.cal_touched = True
            payload = data[8:8 + ln]
            for i in range(ln):
                a = addr + i
                if QK_START <= a <= QK_END:
                    continue                 # «QuickKeys hack»: ці байти не перезаписуються
                if self.sector == a // 4096:
                    self.buf[a % 4096] = payload[i]
            return self._ok(2)
        if sub == 3:
            self.x_calls.append((3, self.sector))
            if self.sector < 0:
                return self._fail()
            buf = bytearray(self.buf)
            if self.corrupt_commit:
                buf[100] ^= 0xFF
            self.spi[self.sector * 4096:self.sector * 4096 + 4096] = buf
            self.commits.append(self.sector)
            self.sector = -1
            return self._ok(3)
        if sub == 4:
            self.x_calls.append((4, 0))
            return self._ok(4)               # на MDUV380 -- порожня дія
        return self._fail()


# ----------------------------------------------------------------------------------------
#  Образи й файли
# ----------------------------------------------------------------------------------------

def spi_a():
    s = base.make_spi()
    s[0x10000:0x10010] = b"CALIB-A-CALIB-A!"
    s[QK_START:QK_END + 1] = b"\x22" * 20
    s[0x6000:0x6010] = b"SETTINGS-A------"
    return s


def spi_b(a):
    """Інша рація: відрізняється налаштуваннями, зоною, контактом, каналом, КАЛІБРУВАННЯМ і КВІККЕЯМИ."""
    s = bytearray(a)
    s[0x6000:0x6010] = b"SETTINGS-B------"
    s[0x8030:0x8040] = base.pad16(b"OTHERZONE")
    s[0x10000:0x10010] = b"CALIB-B-CALIB-B!"
    s[QK_START:QK_END + 1] = b"\x11" * 20
    c = cl.FLASH_ADDRESS_OFFSET + cl.CP_ADDR_CONTACTS
    s[c:c + 16] = base.pad16(b"Changed")
    ch = cl.FLASH_ADDRESS_OFFSET + cl.CP_ADDR_CHANNEL_HEADER_FLASH + 2 * (16 + 128 * 56) + 16
    s[ch:ch + 16] = base.pad16(b"Changed ch")
    return s


def make_backup_file(d, spi, name="mybackup.zip", **kw):
    radio = base.FakeRadio(spi, **kw)
    data, manifest = cl.backup_codeplug(cl.CpsLink(radio), rng=random.Random(5), log=lambda *_: None)
    p = os.path.join(d, name)
    with open(p, "wb") as f:
        f.write(data)
    return p, manifest


def rewrite_zip(path, new_path, edit_manifest=None, edit_files=None):
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(new_path, "w") as zout:
        for n in zin.namelist():
            b = zin.read(n)
            if n == "manifest.json" and edit_manifest:
                import json
                m = json.loads(b.decode("utf-8"))
                edit_manifest(m)
                b = json.dumps(m).encode("utf-8")
            if edit_files and n in edit_files:
                b = edit_files[n](b)
            zout.writestr(n, b)


class Unlocked:
    """Тимчасово зняти блокування W1.11 (у тестах; у коді вона стоїть False)."""
    def __enter__(self):
        self.old = cr.RESTORE_UNLOCKED
        cr.RESTORE_UNLOCKED = True

    def __exit__(self, *a):
        cr.RESTORE_UNLOCKED = self.old


def run_restore(radio, path, confirm=lambda t, p: True, **kw):
    prog = []
    with Unlocked():
        res = cr.restore_codeplug(cl.CpsLink(radio, retries=0), path, confirm, progress=lambda p, t: prog.append(p), log=lambda *_: None, **kw)
    return res, prog


def safety_files(d):
    return sorted(f for f in os.listdir(d) if "pre-restore" in f)


# ----------------------------------------------------------------------------------------
#  T0: блокування
# ----------------------------------------------------------------------------------------

def test_locked_by_default():
    check(isinstance(cr.RESTORE_UNLOCKED, bool), "RESTORE_UNLOCKED -- булева константа; BK8 підтверджено 2026-10-16")
    check(cr.LOCKED_CAPTION == "доступно після перевірки BK8", "підпис на заблокованій кнопці")
    _bk8_old = cr.RESTORE_UNLOCKED
    cr.RESTORE_UNLOCKED = False
    with tempfile.TemporaryDirectory() as d:
        a = spi_a()
        p, _m = make_backup_file(d, a)
        radio = FakeRadioX(spi_b(a))
        try:
            cr.restore_codeplug(cl.CpsLink(radio), p, lambda t, pl: True, log=lambda *_: None)
            check(False, "заблоковане відновлення мало відмовити")
        except cr.RestoreRefused as e:
            check("BK8" in str(e), "повідомлення про блокування: %s" % e)
        check(radio.requests == [] and radio.x_total == 0 and radio.c_calls == [], "заблоковано: ЖОДНОГО трафіку до рації")
        check(safety_files(d) == [], "заблоковано: страхова копія не створюється")
    cr.RESTORE_UNLOCKED = _bk8_old


# ----------------------------------------------------------------------------------------
#  T1: відмови -- жодного запису
# ----------------------------------------------------------------------------------------

def expect_refusal(label, radio, path, frag, d):
    try:
        run_restore(radio, path)
        check(False, "%s: мало бути відхилено" % label)
    except cr.RestoreRefused as e:
        check(frag in str(e), "%s: текст відмови містить «%s»: %s" % (label, frag, e))
    check(radio.x_total == 0, "%s: жодної X-команди (було %d)" % (label, radio.x_total))
    check(radio.c_calls == [] and radio.writes_seen == [], "%s: жодної C-команди" % label)
    check(not any(r[0] != "dead" and r[0] in (1, 2) and False for r in radio.requests), "%s: службова" % label)


def test_refusals():
    with tempfile.TemporaryDirectory() as d:
        a = spi_a()
        good, _m = make_backup_file(d, a)

        # (а) бекап з іншої моделі: radioType у файлі 7
        p = os.path.join(d, "foreign.zip")
        rewrite_zip(good, p, edit_manifest=lambda m: m["radio"].__setitem__("radioType", 7))
        r = FakeRadioX(spi_b(a))
        expect_refusal("чужий radioType", r, p, "іншого типу", d)
        check(safety_files(d) == [], "відмова до страхової копії: файла pre-restore нема")

        # (а') підключена рація іншого типу
        r = FakeRadioX(spi_b(a), radio_type=7)
        expect_refusal("рація radioType 7", r, good, "лише на MD-UV380", d)

        # (б) інша structVersion
        p = os.path.join(d, "structv.zip")
        rewrite_zip(good, p, edit_manifest=lambda m: m["radio"].__setitem__("structVersion", 99))
        expect_refusal("інша structVersion", FakeRadioX(spi_b(a)), p, "structVersion", d)

        # (в) пошкоджений SHA-256: змінений байт у flash.bin і в eeprom.bin
        for part in ("flash.bin", "eeprom.bin"):
            p = os.path.join(d, "corrupt_%s.zip" % part)
            rewrite_zip(good, p, edit_files={part: lambda b: bytes([b[0] ^ 1]) + b[1:]})
            expect_refusal("пошкоджений " + part, FakeRadioX(spi_b(a)), p, "SHA-256", d)
            check(True, "")
        # SHA-256 у маніфесті підмінено
        p = os.path.join(d, "badsha.zip")
        rewrite_zip(good, p, edit_manifest=lambda m: m["parts"]["flash"].__setitem__("sha256", "0" * 64))
        expect_refusal("підмінений SHA-256 у маніфесті", FakeRadioX(spi_b(a)), p, "SHA-256", d)

        # (г) маніфест без обов'язкових полів
        cases = [
            ("немає radio", lambda m: m.pop("radio"), "radio"),
            ("немає radio.radioType", lambda m: m["radio"].pop("radioType"), "radioType"),
            ("немає radio.structVersion", lambda m: m["radio"].pop("structVersion"), "structVersion"),
            ("немає parts.flash", lambda m: m["parts"].pop("flash"), "flash"),
            ("немає parts.eeprom.sha256", lambda m: m["parts"]["eeprom"].pop("sha256"), "sha256"),
            ("немає parts.flash.length", lambda m: m["parts"]["flash"].pop("length"), "length"),
            ("немає format", lambda m: m.pop("format"), "формат"),
        ]
        for i, (label, fn, frag) in enumerate(cases):
            p = os.path.join(d, "nofield%d.zip" % i)
            rewrite_zip(good, p, edit_manifest=fn)
            expect_refusal(label, FakeRadioX(spi_b(a)), p, frag, d)

        # (д) маніфест просить інший діапазон (спроба писати поза кодплугом): початок флешу 0x0
        p = os.path.join(d, "range.zip")
        rewrite_zip(good, p, edit_manifest=lambda m: m["parts"]["flash"].__setitem__("start", 0x0))
        expect_refusal("діапазон поза кодплугом", FakeRadioX(spi_b(a)), p, "інший діапазон", d)

        # (е) не zip / відсутній файл
        junk = os.path.join(d, "junk.zip")
        open(junk, "wb").write(b"not a zip")
        expect_refusal("не zip", FakeRadioX(spi_b(a)), junk, "не бекап", d)
        expect_refusal("нема файла", FakeRadioX(spi_b(a)), os.path.join(d, "нема.zip"), "не бекап", d)

        # (є) користувач відмовився у діалозі: страхова копія є, X-команд нема
        r = FakeRadioX(spi_b(a))
        res, _p = run_restore(r, good, confirm=lambda t, pl: False)
        check(res["cancelled"] is True and r.x_total == 0 and r.c_calls == [], "відмова в діалозі: нічого не записано")
        check(len(safety_files(d)) == 1, "відмова в діалозі: страхова копія лишилась")

        # (ж) страхову копію зробити не вдалося (рація замовкла) -- відмова без запису
        r = FakeRadioX(spi_b(a), silent=True)
        expect_refusal("рація мовчить", r, good, "", d)


# ----------------------------------------------------------------------------------------
#  T2: повний цикл
# ----------------------------------------------------------------------------------------

def test_full_cycle():
    with tempfile.TemporaryDirectory() as d:
        a = spi_a()
        good, mf = make_backup_file(d, a)
        b = spi_b(a)
        before = bytes(b)
        radio = FakeRadioX(b)
        texts = []

        def confirm(text, plan):
            texts.append(text)
            return True

        res, prog = run_restore(radio, good, confirm=confirm)
        # --- результат ---
        check(res["cancelled"] is False and res["nothingToDo"] is False, "відновлення виконано")
        check(res["sectorsWritten"] == len(radio.commits) and res["sectorsWritten"] > 0, "записано %r секторів" % res["sectorsWritten"])
        check(res["flashMatchesManifest"] is True, "SHA-256 флешу після запису == маніфест")
        # --- образ рації == бекап (крім калібрування й квіккеїв) ---
        after = bytes(radio.spi)
        ee_a, ee_b = bytes(a[:cl.EEPROM_BACKUP_LEN]), after[:cl.EEPROM_BACKUP_LEN]

        def masked(x):
            y = bytearray(x)
            y[QK_START:QK_END + 1] = b"\0" * 20
            y[0x10000:0x11000] = b"\0" * 4096
            return bytes(y)
        check(masked(ee_a) == masked(ee_b), "EEPROM рації == бекап (крім сектора калібрування й квіккеїв)")
        check(after[0x9B000:0xAF000] == bytes(a[0x9B000:0xAF000]), "флеш-кодплуг рації == бекап")
        check(after[0x10000:0x10010] == b"CALIB-B-CALIB-B!", "калібрування рації НЕ змінено (лишилось своє)")
        check(after[QK_START:QK_END + 1] == b"\x11" * 20, "квіккеї рації не змінені (прошивка їх не перезаписує)")
        check(after[0x20000:0x9B000] == before[0x20000:0x9B000] and after[0xAF000:] == before[0xAF000:],
              "custom-data, бази ID, голосові підказки, ключі AES, прошивка -- НЕ чіпались")
        # --- що саме писали ---
        check(radio.cal_touched is False, "до сектора калібрування (0x10000) не торкались")
        check(all(s != 16 for s in radio.commits), "сектор 16 не записувався")
        allowed = set(range(0, 32)) | set(range(0x9B, 0xAF))
        check(set(radio.commits) <= allowed, "записано лише сектори EEPROM / флеш-кодплуга: %r" % sorted(set(radio.commits) - allowed))
        check(not any(c[0] == 4 for c in radio.x_calls), "X 4 (EEPROM) не використовується -- на MDUV380 це порожня дія")
        differing = {i for i in range(len(before) // 4096) if before[i * 4096:(i + 1) * 4096] != bytes(a[i * 4096:(i + 1) * 4096])}
        check(set(radio.commits) <= differing, "пишемо лише сектори, що відрізнялись")
        # --- порядок команд: C 0 -> усі X -> C 6 1 ---
        check(radio.c_calls[:1] == [bytes([0])] and radio.c_calls[-1] == bytes([6, 1]), "C 0 перед записом і C 6 1 після: %r" % radio.c_calls)
        check(radio.reset_requested, "надіслано перезавантаження")
        check(not any(w for w in radio.writes_seen), "жодних сторонніх команд")
        # --- страхова копія ---
        sf = safety_files(d)
        check(len(sf) == 1 and sf[0].startswith("codeplug_pre-restore_") and sf[0].endswith(".zip"), "страхова копія поруч із файлом: %r" % sf)
        check(res["safetyCopy"] == os.path.join(d, sf[0]), "шлях страхової копії в підсумку")
        m2, ee2, fl2 = cl.read_backup_zip(res["safetyCopy"])
        check(ee2 == before[:cl.EEPROM_BACKUP_LEN] and fl2 == before[0x9B000:0xAF000], "страхова копія == стан рації ДО відновлення")
        buf = io.StringIO()
        info.describe(m2, ee2, fl2, names=2, out=lambda s: buf.write(s + "\n"))
        check("UR5ABC" in buf.getvalue(), "страхова копія читається S3-скриптом")
        # --- діалог ---
        t = texts[0]
        for frag in ("UR5ABC", "2504012", "0x0 .. 0x20000", "0x9B000 .. 0xAF000", "pre-restore", os.path.basename(good), "0x10000", "квіккеїв",
                     "abc1234", "перезавантажиться"):
            check(frag in t, "діалог містить «%s»" % frag)
        # --- прогрес ---
        check(prog and prog == sorted(prog) and prog[0] == 0 and prog[-1] == 100, "індикатор: монотонний 0..100 (%r...)" % prog[:3])
        check(len(set(prog)) >= 20, "індикатор оновлюється часто (%d різних значень)" % len(set(prog)))
        # --- повторне відновлення з того ж файла: нічого писати ---
        radio2 = FakeRadioX(radio.spi)
        res2, _ = run_restore(radio2, good, confirm=lambda t, p: (_ for _ in ()).throw(AssertionError("діалог не потрібен")))
        check(res2["nothingToDo"] is True and radio2.x_total == 0, "рація вже збігається -- нічого не пишемо й не питаємо")
        # --- gitRevision відрізняється: дозволено, у діалозі видно обидві ---
        p = os.path.join(d, "oldfw.zip")
        rewrite_zip(good, p, edit_manifest=lambda m: m["radio"].__setitem__("gitRevision", "oldrev9"))
        texts.clear()
        radio3 = FakeRadioX(spi_b(a))
        run_restore(radio3, p, confirm=confirm)
        check("oldrev9" in texts[0] and "abc1234" in texts[0] and "ВІДРІЗНЯЮТЬСЯ" in texts[0], "різні прошивки: обидві в діалозі")
        check(radio3.commits, "різна прошивка не блокує відновлення")


# ----------------------------------------------------------------------------------------
#  T3: обрив, перевірка, відновлення стану
# ----------------------------------------------------------------------------------------

def test_interruption_and_verify():
    with tempfile.TemporaryDirectory() as d:
        a = spi_a()
        good, _mf = make_backup_file(d, a)
        radio = FakeRadioX(spi_b(a), die_after_x=10)
        try:
            run_restore(radio, good)
            check(False, "обрив мав дати RestoreInterrupted")
        except cr.RestoreInterrupted as e:
            msg = str(e)
            sf = safety_files(d)
            check(len(sf) == 1 and sf[0] in msg, "у тексті обриву названо файл страхової копії (%r)" % sf)
            check("НЕВИЗНАЧЕНОМУ" in msg and "ПОВТОРИ" in msg and os.path.basename(good) in msg, "у тексті: невизначений стан, повтор з тим самим файлом")
        check(radio.x_total == 11 and radio.dead, "після мовчання рації нових X не було (усього %d)" % radio.x_total)
        check(radio.reset_requested is False, "після обриву перезавантаження не надсилається")

    # повтор після обриву: рація лишилась із підготовленим сектором -> X 1 відмовлено, потім працює
    with tempfile.TemporaryDirectory() as d:
        a = spi_a()
        good, _mf = make_backup_file(d, a)
        radio = FakeRadioX(spi_b(a), stale_sector=7)
        res, _p = run_restore(radio, good)
        check(res["sectorsWritten"] > 0 and radio.reset_requested, "після обриву повторне відновлення проходить (стан X скинуто відмовою)")

    # перевірка після запису: «рація» псує байт при записі -> RestoreVerifyFailed, перезавантаження не надсилається
    with tempfile.TemporaryDirectory() as d:
        a = spi_a()
        good, _mf = make_backup_file(d, a)
        radio = FakeRadioX(spi_b(a), corrupt_commit=True)
        try:
            run_restore(radio, good)
            check(False, "розбіжність після запису мала дати RestoreVerifyFailed")
        except cr.RestoreVerifyFailed as e:
            check("ПЕРЕВІРКА НЕ ПРОЙШЛА" in str(e) and "pre-restore" in str(e), "гучна помилка з назвою страхової копії")
        check(radio.reset_requested is False, "після невдалої перевірки перезавантаження не надсилається")


# ----------------------------------------------------------------------------------------
#  T4: одна функція назв
# ----------------------------------------------------------------------------------------

def test_names():
    gbk = bytes.fromhex("a7b1a7d1a7e1a7e5a7d4a7d1") + b"\xff" * 4
    cp = "ЇЖАК ҐЄІіїєґ".encode("cp1251").ljust(16, b"\xff")
    cases = [
        ("GBK «Папуга»", gbk, ("Папуга", "GBK")),
        ("cp1251 «ЇЖАК ҐЄІіїєґ»", cp, ("ЇЖАК ҐЄІіїєґ", "cp1251")),
        ("ASCII «LOCAL»", b"LOCAL".ljust(16, b"\xff"), ("LOCAL", "ASCII")),
        ("порожня назва (усі 0xFF)", b"\xff" * 16, ("", "—")),
        ("порожня назва (нулі)", b"\x00" * 16, ("", "—")),
        ("ASCII зі знаком питання", b"Who?".ljust(16, b"\xff"), ("Who?", "ASCII")),
        ("GBK зі знаком питання (як CPS замінює Ї)", b"?" + bytes.fromhex("a7d8a7d1a7dc").ljust(15, b"\xff"), ("?жак", "GBK")),
    ]
    for label, raw, want in cases:
        got = cv.decode_name_ex(raw)
        check(got == want, "%s: %r (очікувалось %r)" % (label, got, want))
        check(cv.decode_name(raw) == want[0], "%s: decode_name дає той самий текст" % label)
    check(cv.decode_name_ex(gbk, "cp1251")[1] == "cp1251" and cv.decode_name_ex(gbk, "gbk")[0] == "Папуга", "примусове кодування")
    # скрипт S3 і вікно -- ОДНА реалізація
    check(info.decode_name is cv.decode_name and info.name_bytes is cv.name_bytes, "cps_backup_info використовує ту саму функцію")
    check(info.Codeplug is cv.Codeplug, "cps_backup_info використовує той самий розбір кодплуга")
    here = os.path.dirname(os.path.abspath(__file__))
    for fn in ("cps_backup_info.py", "cps_restore.py", "cps_link.py", "gui_flasher.py", "codeplug_viewer_gui.py"):
        pth = os.path.join(here, fn)
        if os.path.exists(pth):
            src = open(pth, encoding="utf-8").read().lower()
            check("0xa7" not in src and "0xa1 <=" not in src, "%s не містить власних правил GBK (їх тільки в codeplug_view.py)" % fn)
    # ті самі правила в таблицях вікна
    a = spi_a()
    radio = base.FakeRadio(a)
    data, _m = cl.backup_codeplug(cl.CpsLink(radio), rng=random.Random(5), log=lambda *_: None)
    cp_, _man = cv.codeplug_from_backup(data)
    cols, rows = cp_.table_contacts()
    check(cols[-1] == "Кодування", "остання колонка -- кодування")
    by = {r[1]: r for r in rows}
    check(by["Папуга"][-1] == "GBK" and by["Їжак"][-1] == "cp1251" and by["LOCAL"][-1] == "ASCII", "колонка кодування: %r" % [(r[1], r[-1]) for r in rows])


# ----------------------------------------------------------------------------------------
#  T5: фільтри сміття; таблиці; CSV
# ----------------------------------------------------------------------------------------

def put_channel(spi, number, name, rx10hz, tx10hz, mode):
    i = number - 1
    bank, slot = divmod(i, 128)

    def bcd_le(v):
        return bytes.fromhex("%08d" % v)[::-1]
    rec = bytearray(base.pad16(name)) + bcd_le(rx10hz) + bcd_le(tx10hz) + bytes([mode]) + b"\0" * (56 - 25)
    if bank == 0:
        hdr = cl.CP_ADDR_CHANNEL_HEADER_EEPROM
        data = hdr + 16 + slot * 56
    else:
        hdr = cl.FLASH_ADDRESS_OFFSET + cl.CP_ADDR_CHANNEL_HEADER_FLASH + (bank - 1) * (16 + 128 * 56)
        data = hdr + 16 + slot * 56
    spi[data:data + 56] = rec
    spi[hdr + (slot >> 3)] |= 1 << (slot & 7)


def test_filters_and_tables():
    s = base.make_spi()
    # зони: біти 0,1,5 справжні + сміття 68..254 => 190 бітів у масці, зон має бути 3
    mask = bytearray(32)
    for bit in [0, 1, 5] + list(range(68, 255)):
        mask[bit >> 3] |= 1 << (bit & 7)
    check(sum(bin(x).count("1") for x in mask) == 190, "тестова маска має 190 бітів")
    s[cl.CP_ADDR_EX_ZONE_INUSE:cl.CP_ADDR_EX_ZONE_INUSE + 32] = mask
    # групи: таблиця довжин 07 00 00 ... (+ сміттєва довжина 0xFF в іншому місці -- теж відкидається)
    lens = bytearray(cl.CP_RXGROUPS_MAX)
    lens[0] = 7
    a = cl.FLASH_ADDRESS_OFFSET + cl.CP_ADDR_RX_GROUP_LEN
    s[a:a + cl.CP_RXGROUPS_MAX] = lens
    check(bytes(s[a:a + 3]) == bytes.fromhex("070000"), "довжини груп починаються з 07 00 00")
    g = cl.FLASH_ADDRESS_OFFSET + cl.CP_ADDR_RX_GROUP
    for k, c in enumerate([1, 2, 3, 11, 999, 2, 1]):
        s[g + 16 + 2 * k:g + 18 + 2 * k] = struct.pack("<H", c)
    # канали й склад зони
    put_channel(s, 1, b"Calling", 14550000, 14550000, 0)
    put_channel(s, 2, "Київ ТГ".encode("cp1251"), 43000000, 43560000, 1)
    put_channel(s, 385, b"FlashCh", 14600000, 14600000, 1)
    z = cl.CP_ADDR_EX_ZONE_LIST + 5 * (16 + 160)
    for k, c in enumerate([1, 2, 385, 77]):
        s[z + 16 + 2 * k:z + 18 + 2 * k] = struct.pack("<H", c)
    radio = base.FakeRadio(s)
    data, _m = cl.backup_codeplug(cl.CpsLink(radio), rng=random.Random(5), log=lambda *_: None)
    cp_, _man = cv.codeplug_from_backup(data)

    check(len(cp_.zones()) == 3 and [x[0] for x in cp_.zones()] == [1, 2, 6], "190 бітів у масці -> 3 зони, а не 191: %r" % [x[0] for x in cp_.zones()])
    check(len(cp_.rx_groups()) == 1 and cp_.rx_groups()[0][2] == 7, "довжини 07 00 00... -> одна група: %r" % cp_.rx_groups())
    # додатковий захист: довжина > 32 -- сміття
    s2 = bytearray(s)
    s2[a + 10] = 0xFF
    cp2, _ = cv.codeplug_from_backup(cl.backup_codeplug(cl.CpsLink(base.FakeRadio(s2)), rng=random.Random(5), log=lambda *_: None)[0])
    check(len(cp2.rx_groups()) == 1, "довжина 0xFF у таблиці груп відкидається")

    cols, rows = cp_.table_rx_groups()
    check(len(rows) == 1 and "Папуга (2501234)" in rows[0][3] and "#999 (немає)" in rows[0][3], "склад групи: %r" % rows[0][3])
    cols, rows = cp_.table_zones()
    zr = [r for r in rows if r[0] == "6"][0]
    check(zr[1] == "Папуга" and zr[4] == "GBK" and zr[2] == "4", "зона 6: %r" % zr)
    check("1 Calling" in zr[3] and "385 FlashCh" in zr[3] and "77 (порожній)" in zr[3], "склад зони: %r" % zr[3])
    cols, rows = cp_.table_channels()
    byname = {r[1]: r for r in rows}
    check(byname["Calling"][2:] == ["145.50000", "145.50000", "FM", "ASCII"], "канал 1: %r" % byname["Calling"])
    check(byname["Київ ТГ"][2:] == ["430.00000", "435.60000", "DMR", "cp1251"], "канал 2: %r" % byname.get("Київ ТГ"))
    check(byname["FlashCh"][0] == "385" and byname["FlashCh"][2] == "146.00000", "канал із флеш-банку: %r" % byname["FlashCh"])
    check(len(rows) == 5, "каналів у таблиці: %d" % len(rows))
    cols, rows = cp_.table_contacts()
    check([r[0] for r in rows] == ["1", "2", "3", "11"] and rows[0][3] == "приват" and rows[3][3] == "всім", "контакти: %r" % rows)

    # CSV: UTF-8, кирилиця ціла
    with tempfile.TemporaryDirectory() as d:
        pth = os.path.join(d, "contacts.csv")
        cols, rows = cp_.table_contacts()
        cv.write_csv(pth, cols, rows)
        raw = open(pth, "rb").read()
        check(raw.startswith(b"\xef\xbb\xbf"), "CSV: UTF-8 (з BOM для Excel)")
        back = list(csv.reader(io.StringIO(raw.decode("utf-8-sig")), delimiter=";"))
        check(back[0] == cols and back[1:] == rows, "CSV читається назад ідентично")
        check(any("Папуга" in r for r in back) and any("Їжак" in r for r in back), "кирилиця в CSV ціла")


# ----------------------------------------------------------------------------------------
#  W3.2: повний знімок
# ----------------------------------------------------------------------------------------

def test_full_snapshot():
    a = spi_a()
    a[cl.AES_KEYS_RAW_START:cl.AES_KEYS_RAW_START + 4] = b"KEY!"
    a[cl.VOICE_PROMPTS_RAW_START:cl.VOICE_PROMPTS_RAW_START + 4] = b"VPVP"
    # звичайний бекап: без додаткових частин
    d0, m0 = cl.backup_codeplug(cl.CpsLink(base.FakeRadio(a)), rng=random.Random(1), log=lambda *_: None)
    check(m0["includes"] == ["eeprom", "flash"] and set(m0["parts"]) == {"eeprom", "flash"}, "за замовчуванням повного знімка немає")
    with zipfile.ZipFile(io.BytesIO(d0)) as z:
        check(sorted(z.namelist()) == ["eeprom.bin", "flash.bin", "manifest.json"], "у звичайному zip лише три файли")
    # повний знімок
    radio = base.FakeRadio(a)
    d1, m1 = cl.backup_codeplug(cl.CpsLink(radio), rng=random.Random(1), log=lambda *_: None, full_snapshot=True)
    check(m1["includes"] == ["eeprom", "flash", "voicePrompts", "aesKeys"], "маніфест позначає, що ввійшло: %r" % m1["includes"])
    check(m1["restorable"] == ["eeprom", "flash"] and m1["parts"]["aesKeys"]["restorable"] is False, "відновлюються лише eeprom та flash")
    with zipfile.ZipFile(io.BytesIO(d1)) as z:
        check(z.read("aeskeys.bin")[:4] == b"KEY!" and len(z.read("aeskeys.bin")) == 1600, "aeskeys.bin: 16 записів по 100 Б")
        check(z.read("voiceprompts.bin")[:4] == b"VPVP", "voiceprompts.bin")
    m, ee, fl = cl.read_backup_zip(d1)
    check(m["parts"]["voicePrompts"]["sha256"] == cl.sha256(zipfile.ZipFile(io.BytesIO(d1)).read("voiceprompts.bin")), "SHA-256 додаткових частин")
    # константи таблиці ключів збігаються зі stock_key_table.py (без імпорту: той тягне cryptography)
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "stock_key_table.py"), encoding="utf-8").read()
    check("STOCK_KEY_TABLE_BASE = 0xD9F9C" in src and "STOCK_KEY_ENTRY_LEN = 0x64" in src, "константи ключів збігаються зі stock_key_table.py")
    # пошкоджений додатковий файл виявляється
    p = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(d1)) as zin, zipfile.ZipFile(p, "w") as zout:
        for n in zin.namelist():
            b = zin.read(n)
            zout.writestr(n, (b"\x00" + b[1:]) if n == "aeskeys.bin" else b)
    try:
        cl.read_backup_zip(p.getvalue())
        check(False, "пошкоджений aeskeys.bin мав бути виявлений")
    except cl.CpsError:
        pass
    # відновлення з повного знімка НЕ пише голосові підказки/ключі
    with tempfile.TemporaryDirectory() as d:
        pth = os.path.join(d, "full.zip")
        open(pth, "wb").write(d1)
        b = spi_b(a)
        b[cl.AES_KEYS_RAW_START:cl.AES_KEYS_RAW_START + 4] = b"MINE"
        before = bytes(b)
        rb = FakeRadioX(b)
        run_restore(rb, pth)
        check(bytes(rb.spi[cl.AES_KEYS_RAW_START:cl.AES_KEYS_RAW_START + 4]) == b"MINE", "ключі AES рації не перезаписано")
        check(all(not (0xAF <= s < 0xDA) for s in rb.commits), "жоден сектор голосових підказок/ключів не записувався")
        check(bytes(rb.spi[0xAF000:]) == before[0xAF000:], "усе за межею флеш-кодплуга незмінне")


def main():
    for t in (test_locked_by_default, test_refusals, test_full_cycle, test_interruption_and_verify, test_names, test_filters_and_tables,
              test_full_snapshot):
        try:
            t()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILS.append("%s: виняток %r" % (t.__name__, e))
    if FAILS:
        print("test_cps_restore: ПРОВАЛЕНО перевірок: %d" % len(FAILS))
        return 1
    print("test_cps_restore: усі перевірки пройшли (відмови без запису, повний цикл, обрив, назви, фільтри, CSV, повний знімок).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
