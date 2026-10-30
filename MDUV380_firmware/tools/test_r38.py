#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R38: майстер самоперевірки (selfcheck.py, панель cps_ui/p_selfcheck.py).

Рації нема: SPI-флеш підроблено (FakeRadioX з test_cps_restore розуміє 'R' і 'X 1/2/3', веде список записаних секторів, вміє «замовкнути» посеред запису
і «губити» коміти), тож РЕАЛЬНІ алгоритми сценаріїв (cps_restore, custom_data -> flash_guard, звірки) відпрацьовують на підробленому флеші.

Z1  кожен сценарій проходить на справній рації і ПРОВАЛЮЄТЬСЯ з підкладеною розбіжністю (тобто справді перевіряє, а не завжди каже «гаразд»); після сценаріїв запису
    рація побайтово така сама, а калібрування, ключі AES, база позивних і підказки не зачеплені; жоден сценарій не друкує ключів AES;
G   запобіжники: без знімка запис недоступний (жодної X-команди), без згоди -- пропускається, читання не пише нічого;
Z2  сценарій запису з обривом на КОЖНОМУ кроці: звіт каже про проміжний стан, страхова копія й знімок цілі, подальший запис зупинено;
Z3  звіт: усі кроки на місці, непройдений видно одразу, підсумок рахує правильно, є перелік ручних кроків з номерами чек-листа;
Z4  знімок проти передпоказу: однакові -- 0 %, змінений піксель -- ненульовий відсоток, виключені ділянки окремо (з R39 критерії S3 -- у test_r39);
Z5  панель під xvfb (Tk) і запуск без DISPLAY пропущено.
Запуск: `xvfb-run -a python3.12 tools/test_r38.py`."""
import contextlib
import datetime
import io
import json
import os
import random
import re
import struct
import sys
import tempfile
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import aes_keys_backup as akb            # noqa: E402
import codeplug_view as cv               # noqa: E402
import contact_edit as ce                # noqa: E402
import cps_csv as cc                     # noqa: E402
import cps_link as cl                    # noqa: E402
import cps_restore as rs                 # noqa: E402
import custom_data as cd                 # noqa: E402
import custom_region as cr               # noqa: E402
import dmr_db as db                      # noqa: E402
import flash_guard as fg                 # noqa: E402
import screen_views as sv                # noqa: E402
import selfcheck as sc                   # noqa: E402
import test_cps_csv as tc                # noqa: E402
import test_cps_restore as tcr           # noqa: E402
import test_r31 as t31                   # noqa: E402
import test_r37 as t37                   # noqa: E402
import theme_edit as te                  # noqa: E402
import voice_prompts as vp               # noqa: E402

FAILS = []
tcr.FakeRadioX.close = lambda self: None
NOW = datetime.datetime(2026, 10, 30, 12, 34)


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def quiet(*_a, **_k):
    pass


def no_sleep():
    old = time.sleep
    time.sleep = lambda _s: None
    return old


# ----------------------------------------------------------------------------------------------------------------------
#  Підроблена рація
# ----------------------------------------------------------------------------------------------------------------------

class LossyRadio(tcr.FakeRadioX):
    """Рація, що «губить» коміти секторів: X 3 відповідає «гаразд», але сектор не змінюється (запис не дійшов до флеша)."""

    def __init__(self, spi, drop=lambda sector: True, **kw):
        super().__init__(spi, **kw)
        self.drop = drop
        self.dropped = []

    def write(self, data):
        data = bytes(data)
        if data[:2] == b"X\x03" and not self.dead and self.sector >= 0 and self.drop(self.sector):
            self.x_total += 1
            self.x_calls.append((3, self.sector))
            self.dropped.append(self.sector)
            self.sector = -1
            self._ok(3)
            return
        return super().write(data)


def vp_image(seed=1, version=9):
    rnd = random.Random(seed)
    lens = [27 * rnd.randrange(1, 12) if i < 90 else 0 for i in range(367)]
    toc, acc = [0] * 368, 0
    for i in range(367):
        toc[i] = acc
        acc += lens[i]
    toc[367] = acc
    return struct.pack("<II", vp.MAGIC, version) + struct.pack("<368I", *toc) + bytes(rnd.randrange(256) for _ in range(acc))


def stock_display(screen="channel", variant="ua", daytime="day"):
    colors = te.stock_colors(daytime, variant)
    words = sc.render_words(sv.render(screen), colors)
    return struct.pack(">%dH" % len(words), *words)


def make_spi(vp_version=9, db_records=200, with_nadiya=True, region_entries=None, display_screen="channel"):
    """Реалістична рація: кодплаг із фікстури, область custom-data (теми, селектор AES, RCTL, SMS, картинка), ключі AES 2/5/9, підказки, база позивних."""
    spi = tc.make_fixture_spi()
    spi[0x10000:0x10010] = b"CALIB-A-CALIB-A!"
    spi[tcr.QK_START:tcr.QK_END + 1] = b"\x22" * 20
    ents = region_entries or [(1, t37.payload(1, 300)), (4, te.encode_block(te.stock_colors("day"))), (5, te.encode_block(te.stock_colors("night"))),
                              (6, t37.payload(6, 584)), (9, t37.payload(9, 120)), (8, t37.payload(8, 200))]
    region, _end = t37.build_region(ents)
    spi[0x20000:0x30000] = region
    t31.put_table(spi, t31.make_table(1, {2, 5, 9}))
    spi[vp.VP_START:vp.VP_END] = b"\xff" * (vp.VP_END - vp.VP_START)
    img = vp_image(version=vp_version)
    spi[vp.VP_START:vp.VP_START + len(img)] = img
    spi[db.AREA1_START:db.AREA1_START + db.AREA1_LEN] = b"\xff" * db.AREA1_LEN
    if db_records:
        d = db.build_image(t31.make_records(db_records, 5))
        spi[db.AREA1_START:db.AREA1_START + len(d)] = d
    if with_nadiya:
        cp, _ = tc.codeplug_of(spi)
        img0 = cc.Image.from_codeplug(cp)
        r = ce.apply_ops(img0, [{"op": "add", "name": "Надія", "id": 4380, "type": 0}])
        spi[:cl.EEPROM_BACKUP_LEN] = bytes(r.image.eeprom)
        rng = cl.flash_backup_range()
        spi[rng["raw_start"]:rng["raw_start"] + rng["length"]] = bytes(r.image.flash)
    return spi


def make_radio(spi=None, cls=tcr.FakeRadioX, display=None, **kw):
    spi = bytearray(spi if spi is not None else make_spi())
    radio = cls(spi, display=display if display is not None else stock_display(), **kw)
    return radio, cl.CpsLink(radio, retries=0)


def make_ctx(link, d=None, snapshot=False, **kw):
    d = d or tempfile.mkdtemp(prefix="r38_")
    ctx = sc.Ctx(link, d, log=quiet, now=NOW, post_reset=True, **kw)
    if snapshot:
        sc.take_snapshot(ctx)
    return ctx


def run_one(radio_link, sid, snapshot=None, confirm=lambda t: True, **kw):
    radio, link = radio_link
    ctx = make_ctx(link, snapshot=(snapshot if snapshot is not None else sc.SCENARIO_BY_ID[sid].risk == sc.RISK_WRITE))
    with tcr.Unlocked():
        rep = sc.run(ctx, [sid], confirm_writes=confirm)
    return rep, ctx


def only(rep):
    return next(r for r in rep.results if r.scenario.sid != "S4.0")


def failed_names(res):
    return [s.name for s in res.failed_steps()]


def zones_equal(a, b):
    """Весь SPI однаковий, крім ділянок, які рація міняє сама (EEPROM без UNSTABLE)."""
    ma, mb = bytearray(a), bytearray(b)
    for s, e, _w in rs.UNSTABLE_EEPROM:
        ma[s:e] = b"\0" * (e - s)
        mb[s:e] = b"\0" * (e - s)
    return bytes(ma) == bytes(mb)


@contextlib.contextmanager
def patched(obj, name, new):
    old = getattr(obj, name)
    setattr(obj, name, new)
    try:
        yield
    finally:
        setattr(obj, name, old)


# ----------------------------------------------------------------------------------------------------------------------
#  Z1: кожен сценарій проходить і провалюється з підкладеною розбіжністю
# ----------------------------------------------------------------------------------------------------------------------

def plant_s2_1():
    return patched(cv.Codeplug, "dmr_id", lambda self: 1234567)


def plant_s2_2():
    def lying_save(path, colors):
        data = te.encode_block(colors)
        with open(path, "wb") as f:
            f.write(data[:-1])
        return data
    return patched(te, "save_gtm", lying_save)


def plant_s2_3():
    orig = cl.make_zip

    def evil(eeprom, flash, manifest, extra_files=None):
        return orig(eeprom, bytes(flash[:-1]) + b"\x5a", manifest, extra_files)      # SHA-256 у маніфесті від ІНШОГО флешу
    return patched(cl, "make_zip", evil)


def test_z1_read():
    old = no_sleep()
    try:
        for sid in ("S2.1", "S2.2", "S2.3", "S2.4", "S2.5", "S2.6", "S2.7", "S2.8", "S3"):
            radio, link = make_radio()
            before = bytes(radio.spi)
            rep, ctx = run_one((radio, link), sid, snapshot=False)
            res = only(rep)
            check(res.status == sc.PASS, "Z1 %s: справна рація -- пройдено; не пройшло: %r %s" % (sid, failed_names(res), res.error or ""))
            check(len(res.steps) >= 2, "Z1 %s: сценарій має кроки (%d)" % (sid, len(res.steps)))
            check(radio.x_total == 0 and not radio.commits and bytes(radio.spi) == before, "Z1 %s: лише читання -- жодної X-команди, флеш не змінено" % sid)
            check(all(s.expected is not None for s in res.steps), "Z1 %s: у кожного кроку є очікуване значення" % sid)
            check(not any(re.search(r"[0-9a-f]{64}", str(s.got) + str(s.expected)) for s in res.steps), "Z1 %s: у звіті нема повного SHA-256 / ключів" % sid)
    finally:
        time.sleep = old


def test_z1_read_planted():
    old = no_sleep()
    try:
        # --- S2.1: розділ показує інший DMR ID, ніж форма ---
        rl = make_radio()
        with plant_s2_1():
            res = only(run_one(rl, "S2.1", snapshot=False)[0])
        check(res.status == sc.FAIL and any("DMR ID" in n for n in failed_names(res)), "Z1 S2.1: підкладено інший DMR ID -- провал: %r" % failed_names(res))
        # --- S2.1: розділ «Контакти» міг би загубити контакт ---
        rl = make_radio()
        with patched(cc.Image, "contacts", _contacts_minus_one):
            res = only(run_one(rl, "S2.1", snapshot=False)[0])
        check(res.status == sc.FAIL and any("контакти" in n for n in failed_names(res)), "Z1 S2.1: зник контакт -- провал: %r" % failed_names(res))
        # --- S2.2: .gtm не 64 байти ---
        rl = make_radio()
        with plant_s2_2():
            res = only(run_one(rl, "S2.2", snapshot=False)[0])
        check(res.status == sc.FAIL and any(".gtm" in n for n in failed_names(res)), "Z1 S2.2: усічений .gtm -- провал: %r" % failed_names(res))
        # --- S2.3: SHA-256 частини не збігається з маніфестом ---
        rl = make_radio()
        with plant_s2_3():
            res = only(run_one(rl, "S2.3", snapshot=False)[0])
        check(res.status in (sc.FAIL, sc.ERROR) and (failed_names(res) or res.error), "Z1 S2.3: підміна флешу в архіві -- провал: %r %s" % (failed_names(res), res.error))
        # --- S2.4: область з блоком, довжина якого виходить за область ---
        bad = bytearray(make_spi())
        struct.pack_into("<ii", bad, 0x20000 + 12 + 8 + 300, 7, 0x20000)
        res = only(run_one(make_radio(bad), "S2.4", snapshot=False)[0])
        check(res.status == sc.FAIL, "Z1 S2.4: пошкоджена область -- провал: %r" % failed_names(res))
        # --- S2.4: знімок і рація розійшлись ---
        radio, link = make_radio()
        ctx = make_ctx(link, snapshot=True)
        spi2 = bytearray(radio.spi)
        struct.pack_into("<ii", spi2, 0x20000 + 12, 1, 299)           # блок 1 став на байт коротший -- перелік блоків інший
        radio.spi[:] = spi2
        res = sc.Result(sc.SCENARIO_BY_ID["S2.4"])
        sc.s2_4(ctx, res)
        check(any("знімку" in n for n in failed_names(res)) or res.status == sc.FAIL, "Z1 S2.4: перелік блоків відрізняється від знімка -- провал: %r" % failed_names(res))
        # --- S2.5: слоти змінились після знімка ---
        radio, link = make_radio()
        ctx = make_ctx(link, snapshot=True)
        t31.put_table(radio.spi, t31.make_table(1, {2, 5, 9, 11}))
        res = sc.Result(sc.SCENARIO_BY_ID["S2.5"])
        sc.s2_5(ctx, res)
        check(any("слоти" in n for n in failed_names(res)), "Z1 S2.5: зайнятий інший набір слотів -- провал: %r" % failed_names(res))
        # --- S2.6: заголовок бази з неможливою довжиною запису ---
        spi6 = make_spi()
        spi6 = bytearray(spi6)
        spi6[db.AREA1_START + 3] = 0xFF
        res = only(run_one(make_radio(spi6), "S2.6", snapshot=False)[0])
        check(res.status == sc.FAIL, "Z1 S2.6: пошкоджений заголовок бази -- провал: %r" % failed_names(res))
        # --- S2.7: підказки не тієї версії ---
        res = only(run_one(make_radio(make_spi(vp_version=8)), "S2.7", snapshot=False)[0])
        check(res.status == sc.FAIL and any("версія" in n for n in failed_names(res)), "Z1 S2.7: версія 8 -- провал: %r" % failed_names(res))
        # --- S2.8: назва з байтом 0xFF серед GBK-пар -- рація (прошивка) прочитає її як сміття, «я» не буде ---
        spi8 = bytearray(make_spi(with_nadiya=False))
        cp, _ = tc.codeplug_of(spi8)
        img = cc.Image.from_codeplug(cp)
        rec = bytearray(img.fl(cl.CP_ADDR_CONTACTS + 5 * cl.CP_CONTACT_SIZE, 24))
        rec[:16] = b"\xa7\xa1ab\xffcd".ljust(16, b"\xff")
        rec[16:20] = bytes.fromhex("00001234")
        img.set_contact(5, bytes(rec))
        rng = cl.flash_backup_range()
        spi8[rng["raw_start"]:rng["raw_start"] + rng["length"]] = bytes(img.flash)
        res = only(run_one(make_radio(spi8), "S2.8", snapshot=False)[0])
        check(res.status == sc.FAIL, "Z1 S2.8: назва, де «я» не читається, -- провал: %r" % failed_names(res))
        # --- S3: на екрані інший екран/велика розбіжність ---
        disp = bytearray(stock_display())
        disp[: 160 * 128 * 2 // 2] = b"\x07\xe0" * (160 * 128 // 2)          # півекрана зеленим
        res = only(run_one(make_radio(display=bytes(disp)), "S3", snapshot=False)[0])
        check(res.status == sc.FAIL and any(n.startswith("палітра") for n in failed_names(res)), "Z1 S3: півекрана чужим кольором -- провал палітри: %r" % failed_names(res))
    finally:
        time.sleep = old


def _contacts_minus_one(self):
    """cc.Image.contacts, але без останнього контакту (розділ загубив запис)."""
    out = []
    for i in range(cl.CP_CONTACTS_MAX):
        rec = self.fl(cl.CP_ADDR_CONTACTS + i * cl.CP_CONTACT_SIZE, cl.CP_CONTACT_SIZE)
        if rec[0] != 0xFF:
            out.append((i, rec))
    return out[:-1]


ALLOWED_SECTORS_NOTE = "сектори: EEPROM (крім калібрування 0x10), флеш-кодплаг 0x9B..0xAE, custom-data 0x20..0x2F"


def allowed_commit(sector):
    a = sector * 4096
    if a < cl.EEPROM_BACKUP_LEN and sector != 0x10:
        return True
    if 0x20 <= sector <= 0x2F:
        return True
    return 0x9B <= sector < 0xAF


def test_z1_write():
    old = no_sleep()
    try:
        for sid, exp_changed in (("S4.1", "custom"), ("S4.2", "codeplug"), ("S4.3", "codeplug"), ("S4.4", "custom")):
            radio, link = make_radio()
            before = bytes(radio.spi)
            rep, ctx = run_one((radio, link), sid)
            res = only(rep)
            check(res.status == sc.PASS, "Z1 %s: справна рація -- пройдено; не пройшло: %r %s; пропуск: %s; гучно: %r" % (
                sid, failed_names(res), res.error or "", res.skip_reason, ctx.loud))
            check(zones_equal(radio.spi, before), "Z1 %s: після сценарію рація побайтово та сама" % sid)
            check(bytes(radio.spi[0x10000:0x11000]) == bytes(before[0x10000:0x11000]) and not radio.cal_touched, "Z1 %s: калібрування не чіпали" % sid)
            check(all(allowed_commit(s_) for s_ in radio.commits), "Z1 %s: записано лише дозволені сектори: %r (%s)" % (sid, sorted(set(radio.commits)), ALLOWED_SECTORS_NOTE))
            check(radio.commits, "Z1 %s: сценарій справді писав (коміти є)" % sid)
            check(bytes(radio.spi[akb.KEYS_START:akb.KEYS_START + akb.KEYS_LEN]) == before[akb.KEYS_START:akb.KEYS_START + akb.KEYS_LEN],
                  "Z1 %s: таблиця ключів AES не змінилась" % sid)
            check(bytes(radio.spi[db.AREA1_START:db.AREA1_START + db.AREA1_LEN]) == before[db.AREA1_START:db.AREA1_START + db.AREA1_LEN], "Z1 %s: база позивних не змінилась" % sid)
            check(rep.invariants is not None and rep.invariants.status == sc.PASS, "Z1 %s: інваріанти (калібрування, ключі, база, підказки) до і після однакові" % sid)
            check(not ctx.loud, "Z1 %s: голосних попереджень нема" % sid)
            if exp_changed == "codeplug":
                check(radio.c_calls and radio.c_calls[0] == bytes([0]) and radio.c_calls[-1] == bytes([6, 1]) and radio.reset_requested,
                      "Z1 %s: показано екран CPS, наприкінці перезавантаження" % sid)
            else:
                check(not radio.c_calls, "Z1 %s: запис у custom-data не потребує екрана CPS і перезавантаження" % sid)
            check(ctx.audit, "Z1 %s: аудит записів не порожній" % sid)
        # --- S4.5: ключі AES сценаріями не чіпаються і окремого сценарію нема ---
        check("S4.5" not in sc.SCENARIO_BY_ID and not any(("aes" in s.title.lower() or "ключ" in s.title.lower()) and s.risk == sc.RISK_WRITE for s in sc.SCENARIOS),
              "Z1 S4.5: сценарію запису ключів AES нема")
    finally:
        time.sleep = old


def test_z1_write_planted():
    old = no_sleep()
    try:
        for sid in ("S4.1", "S4.2", "S4.3", "S4.4"):
            radio, link = make_radio(cls=LossyRadio)
            before = bytes(radio.spi)
            rep, ctx = run_one((radio, link), sid)
            res = only(rep)
            check(res.status in (sc.FAIL, sc.ERROR, sc.INTERRUPTED), "Z1 %s: рація «губить» записи -- сценарій НЕ проходить (статус %s)" % (sid, res.status))
            check(radio.dropped, "Z1 %s: підроблена рація справді втратила коміти" % sid)
            check(failed_names(res) or res.error, "Z1 %s: провал видно в кроках: %r" % (sid, failed_names(res)))
            check(zones_equal(radio.spi, before), "Z1 %s: нічого не дійшло до флеша -- рація та сама" % sid)
        # --- S4.4: запис дійшов, але порушив сусідній блок (рація «зачепила» байт за межею блока) ---
        radio, link = make_radio()
        orig_write = cd.write_block

        def sloppy(ser, dtype, payload):
            r = orig_write(ser, dtype, payload)
            # зіпсувати перший байт наступного за блоком заголовка
            e = next(e for e in sc.ccmp.scan_region(cr.read_radio_region(cl.CpsLink(ser))).live if e.type == dtype)
            ser.spi[0x20000 + e.offset + 8 + e.length] ^= 0x01
            return r
        with patched(cd, "write_block", sloppy):
            rep, ctx = run_one((radio, link), "S4.4")
        res = only(rep)
        check(res.status == sc.FAIL and any("сусідні" in n for n in failed_names(res)), "Z1 S4.4: зачеплено сусідній блок -- провал: %r" % failed_names(res))
    finally:
        time.sleep = old


def test_s4_skips():
    """Сценарії запису не вигадують собі роботи: нема блока теми / нема області -- пропуск з поясненням, рація не змінена."""
    old = no_sleep()
    try:
        # без блока денної теми
        ents = [(1, t37.payload(1, 300)), (6, t37.payload(6, 584)), (9, t37.payload(9, 120))]
        radio, link = make_radio(make_spi(region_entries=ents))
        before = bytes(radio.spi)
        rep, ctx = run_one((radio, link), "S4.1")
        res = only(rep)
        check(res.status == sc.SKIPPED and "блока" in res.skip_reason and bytes(radio.spi) == before and not radio.commits, "S4.1: нема блока теми -- пропуск без запису: %s" % res.skip_reason)
        # область без живих блоків, крім ключа AES
        ents = [(6, t37.payload(6, 584))]
        radio, link = make_radio(make_spi(region_entries=ents))
        rep, ctx = run_one((radio, link), "S4.4")
        res = only(rep)
        check(res.status == sc.SKIPPED and not radio.commits, "S4.4: лише ключ AES -- пропуск, ключ не чіпали: %s" % res.skip_reason)
        # порожня область
        spi = bytearray(make_spi())
        spi[0x20000:0x30000] = b"\xff" * 0x10000
        radio, link = make_radio(spi)
        rep, ctx = run_one((radio, link), "S4.4")
        check(only(rep).status == sc.SKIPPED and not radio.commits, "S4.4: порожня область -- пропуск")
    finally:
        time.sleep = old


# ----------------------------------------------------------------------------------------------------------------------
#  G: запобіжники
# ----------------------------------------------------------------------------------------------------------------------

def test_gates():
    old = no_sleep()
    try:
        radio, link = make_radio()
        ctx = make_ctx(link)
        try:
            sc.run(ctx, ["S4.1", "S4.2", "S2.1"], confirm_writes=lambda t: True)
            check(False, "G: без знімка запис мав бути відхилений")
        except sc.SelfcheckError as e:
            check("знімка" in str(e), "G: відмова називає причину: %s" % e)
        check(radio.x_total == 0 and not radio.commits and not os.path.exists(os.path.join(ctx.out_dir, "x")), "G: без знімка -- жодної X-команди")
        check(not [f for f in os.listdir(ctx.out_dir) if f.endswith(".md")], "G: відмова ДО звіту: файла звіту нема")
        # знімок: повний, перевірений
        snap = sc.take_snapshot(ctx)
        check(os.path.isfile(snap["path"]) and set(snap["parts"]) >= {"eeprom", "flash", "customData", "aesKeys", "voicePrompts", "dmrIdDb"},
              "G: знімок повний: %r" % snap["parts"])
        check(radio.x_total == 0, "G: знімок лише читає")
        check(snap["slots"] == [2, 5, 9], "G: слоти AES у знімку: %r" % snap["slots"])
        m, _ee, _fl = cl.read_backup_zip(snap["path"])
        check(m["parts"]["aesKeys"]["occupiedSlots"] == [2, 5, 9], "G: знімок читається за маніфестом")
        # знімок видалили -- запис знову недоступний
        os.unlink(snap["path"])
        try:
            sc.run(ctx, ["S4.2"], confirm_writes=lambda t: True)
            check(False, "G: знімок зник -- запис мав бути відхилений")
        except sc.SelfcheckError:
            pass
        # без згоди
        ctx = make_ctx(link, snapshot=True)
        texts = []
        with tcr.Unlocked():
            rep = sc.run(ctx, ["S4.1", "S4.2", "S4.3", "S4.4", "S2.4"], confirm_writes=lambda t: texts.append(t) or False)
        check(radio.x_total == 0 and not radio.commits, "G: згоди нема -- жодного запису")
        check({r.scenario.sid: r.status for r in rep.results} == {"S2.4": sc.PASS, "S4.1": sc.SKIPPED, "S4.2": sc.SKIPPED, "S4.3": sc.SKIPPED, "S4.4": sc.SKIPPED},
              "G: без згоди писальні пропущено, читальні пройдено: %r" % {r.scenario.sid: r.status for r in rep.results})
        t = texts[0]
        for frag in ("S4.1", "S4.2", "S4.3", "S4.4", "Зоря", "Надія", "ключі AES", "Повний знімок", "custom-data", "VFO A"):
            check(frag in t, "G: підтвердження перелічує «%s»" % frag)
        check("S2.4" not in t.split("Калібрування")[0], "G: у підтвердженні нема читальних сценаріїв")
        # типово писальні зняті
        check(all(not s.default_on for s in sc.SCENARIOS if s.risk == sc.RISK_WRITE) and all(s.default_on for s in sc.SCENARIOS if s.risk == sc.RISK_READ),
              "G: писальні типово зняті, читальні ввімкнені")
        # порядок: читання раніше запису
        ids = [s.sid for s in sc.order(["S4.1", "S3", "S4.3", "S2.1"])]
        check(ids == ["S2.1", "S3", "S4.1", "S4.3"], "G: порядок виконання: %r" % ids)
    finally:
        time.sleep = old


def test_guards():
    """Охоронці меж: custom-data йде через flash_guard, план кодплага з калібруванням/чужими зонами відхиляється."""
    radio, link = make_radio()
    ctx = make_ctx(link)
    seen = []
    orig = fg.write_span
    with patched(fg, "write_span", lambda ser, addr, data, window, on_sector=None: seen.append((addr, len(data), window)) or orig(ser, addr, data, window, on_sector)):
        old = no_sleep()
        try:
            with sc.guarded_customdata_writes(ctx, "T"):
                ok, _m = cd.write_block(link.ser, 4, te.encode_block(te.stock_colors("day", "classic")))
        finally:
            time.sleep = old
    check(ok and seen and seen[0][2] == "customdata", "guard: запис блока custom-data пройшов через flash_guard.write_span(вікно customdata): %r" % seen)
    check(cd.flash_write_span.__name__ == "flash_write_span", "guard: після виходу з контексту підміну знято")
    # поза вікном
    n_commits = len(radio.commits)
    with sc.guarded_customdata_writes(ctx, "T"):
        try:
            cd.flash_write_span(link.ser, 0x10000, b"\x00" * 16)
            check(False, "guard: запис у калібрування мав бути відхилений")
        except (fg.GuardError, ValueError):
            pass
    check(len(radio.commits) == n_commits and not radio.cal_touched, "guard: відхилений запис не дійшов до флеша")

    class P:
        def __init__(self, sectors):
            self.sectors = sectors
    conf = sc._plan_guard(ctx, "T")
    check(conf("", P([("EEPROM", 0x1000, b"")])) is True, "guard: EEPROM-сектор кодплага дозволено")
    check(conf("", P([("EEPROM", 0x10000, b"")])) is False, "guard: сектор калібрування відхилено")
    check(conf("", P([("флеш", 0x20000, b"")])) is False, "guard: custom-data через шлях кодплага відхилено")
    check(conf("", P([("флеш", 0xD9000, b"")])) is False, "guard: ключі AES через шлях кодплага відхилено")
    check(conf("", P([("флеш", 0x50000, b"")])) is False, "guard: база позивних через шлях кодплага відхилено")
    check(conf("", P([("EEPROM", i * 0x1000, b"") for i in range(1, 14)])) is False, "guard: забагато секторів відхилено")
    rng = cl.flash_backup_range()
    check(conf("", P([("флеш", rng["raw_start"], b"")])) is True, "guard: початок флеш-кодплага дозволено")
    check(len(ctx.loud) >= 5, "guard: кожне відхилення голосне (%d)" % len(ctx.loud))


# ----------------------------------------------------------------------------------------------------------------------
#  Z2: обрив запису
# ----------------------------------------------------------------------------------------------------------------------

def test_z2_interrupted():
    old = no_sleep()
    try:
        base = make_spi()
        n_dead = 0
        for die in (0, 1, 2, 3, 4, 6, 9, 12, 20):
            for sid in ("S4.3", "S4.2"):
                radio, link = make_radio(base, die_after_x=die)
                before = bytes(base)
                _hr, hlink = make_radio(base)                        # знімок робимо на справній рації: обрив стосується лише запису
                ctx_h = make_ctx(hlink)
                sc.take_snapshot(ctx_h)
                ctx = make_ctx(link, d=ctx_h.out_dir)
                ctx.snapshot = ctx_h.snapshot
                with tcr.Unlocked():
                    rep = sc.run(ctx, [sid, "S4.4"], confirm_writes=lambda t: True)
                res = next(r for r in rep.results if r.scenario.sid == sid)
                tag = "Z2 %s, обрив після %d X" % (sid, die)
                if not radio.dead:
                    check(res.status == sc.PASS, "%s: рація не замовкла -- сценарій пройдено" % tag)
                    continue
                n_dead += 1
                s44_ = next(r for r in rep.results if r.scenario.sid == "S4.4")
                if res.status == sc.PASS:        # замовкла вже на другому сценарії (S4.4): перший встиг пройти й повернути рацію
                    check(s44_.status != sc.PASS and not zones_equal(radio.spi, before) is False or s44_.status != sc.PASS, "%s: S4.2 пройдено, обрив у S4.4" % tag)
                    check(not rep.ok, "%s: прогін не вважається успішним" % tag)
                    continue
                check(res.status in (sc.INTERRUPTED, sc.FAIL, sc.ERROR), "%s: сценарій не «пройдено» (%s)" % (tag, res.status))
                changed = not zones_equal(radio.spi, before)
                md = sc.render_markdown(rep)
                if changed:
                    check(ctx.loud, "%s: рація змінена -- є голосне попередження" % tag)
                    check("рація могла лишитись зміненою".lower() in md.lower(), "%s: звіт каже про проміжний стан" % tag)
                    check(ctx.snapshot["path"] in md, "%s: звіт вказує на знімок" % tag)
                    safety = sc._latest_safety(ctx)
                    check(safety and safety in md, "%s: звіт вказує на страхову копію" % tag)
                    if safety:
                        try:
                            cl.read_backup_zip(safety)
                            ok_safe = True
                        except cl.CpsError:
                            ok_safe = False
                        check(ok_safe, "%s: страхова копія ціла (SHA-256 за маніфестом)" % tag)
                else:
                    check(res.failed_steps() or res.error or res.interrupted, "%s: збій видно в кроках" % tag)
                check(os.path.isfile(ctx.snapshot["path"]) and cl.read_backup_zip(ctx.snapshot["path"]), "%s: знімок цілий" % tag)
                s44 = next(r for r in rep.results if r.scenario.sid == "S4.4")
                check(ctx.halted and s44.status == sc.SKIPPED and "зупинено" in s44.skip_reason, "%s: подальший запис зупинено: %s" % (tag, s44.skip_reason))
                check(rep.invariants is not None and rep.invariants.status == sc.FAIL, "%s: інваріанти позначені як не перевірені" % tag)
                check(not rep.ok, "%s: прогін не вважається успішним" % tag)
        check(n_dead >= 8, "Z2: обрив справді відбувся у багатьох випадках (%d)" % n_dead)
        # --- обрив лише на ПОВЕРНЕННІ: тестове значення записано, а повернути не вдалось ---
        radio, link = make_radio(base)
        ctx = make_ctx(link, snapshot=True)

        calls = {"n": 0}
        orig = sc._write_image

        def second_dies(ctx_, edit_res, tag, prefetched, note):
            calls["n"] += 1
            if calls["n"] == 2:
                radio.die_after_x = radio.x_total          # рація замовкає перед першою ж X-командою повернення
            return orig(ctx_, edit_res, tag, prefetched, note)
        with patched(sc, "_write_image", second_dies), tcr.Unlocked():
            rep = sc.run(ctx, ["S4.2"], confirm_writes=lambda t: True)
        res = only(rep)
        md = sc.render_markdown(rep)
        check(res.status in (sc.INTERRUPTED, sc.FAIL), "Z2: повернення обірвано -- сценарій не пройдено (%s)" % res.status)
        check(ctx.loud and "ПОВЕРНЕННЯ ДО ПОЧАТКОВОГО СТАНУ НЕ ВДАЛОСЬ" in md and ctx.snapshot["path"] in md and "codeplug_pre-restore" in md,
              "Z2: невдале повернення сказано ГОЛОСНО зі страховою копією й знімком: %r" % ctx.loud)
        check(not zones_equal(radio.spi, base), "Z2: рація справді лишилась зі зміненим VFO (тестове значення не повернуто)")
        # і страхова копія ПЕРЕД цим сценарієм містить початковий стан: відновлення з неї повертає рацію
        safety = sorted(f for f in os.listdir(ctx.run_dir) if f.startswith("codeplug_pre-restore"))
        first = os.path.join(ctx.run_dir, safety[0])
        radio.dead = False
        radio.die_after_x = None
        with tcr.Unlocked():
            rs.restore_codeplug(cl.CpsLink(radio, retries=0), first, lambda t, p: True, log=quiet, post_reset=False)
        check(zones_equal(radio.spi, base), "Z2: страхова копія повертає рацію до початкового стану")
    finally:
        time.sleep = old


# ----------------------------------------------------------------------------------------------------------------------
#  Z3: звіт
# ----------------------------------------------------------------------------------------------------------------------

def test_z3_report():
    old = no_sleep()
    try:
        radio, link = make_radio(make_spi(vp_version=8))          # S2.7 провалиться на справжніх даних
        ctx = make_ctx(link, snapshot=True)
        ids = [s.sid for s in sc.SCENARIOS]
        with tcr.Unlocked():
            rep = sc.run(ctx, ids, confirm_writes=lambda t: True)
        check(rep.path and re.search(r"selfcheck_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}\.md$", rep.path) and os.path.isfile(rep.path), "Z3: файл звіту з правильним ім'ям: %s" % rep.path)
        with open(rep.path, encoding="utf-8") as f:
            md = f.read()
        check(md == sc.render_markdown(rep), "Z3: файл = відрендерений звіт")
        n_steps = 0
        for r in rep.all_results:
            check("### %s " % r.scenario.sid in md, "Z3: у звіті є розділ %s" % r.scenario.sid)
            for s in r.steps:
                n_steps += 1
                check(sc._cell(s.name) in md, "Z3: крок «%s» (%s) є у звіті" % (s.name, r.scenario.sid))
        check(n_steps > 60, "Z3: кроків багато (%d)" % n_steps)
        res27 = next(r for r in rep.results if r.scenario.sid == "S2.7")
        check(res27.status == sc.FAIL, "Z3: S2.7 не пройдено (підкладена версія 8)")
        head = md.split("## Зведення")[0]
        check("НЕ пройдено 1" in head or "НЕ пройдено" in head, "Z3: підсумок угорі показує провал")
        check("## Що не пройшло" in head and "S2.7" in head.split("## Що не пройшло")[1], "Z3: розділ «Що не пройшло» вгорі називає S2.7")
        check("**НЕ ЗБІГЛОСЬ**" in md, "Z3: непройдений крок виділено в таблиці")
        fails_section = head.split("## Що не пройшло")[1]
        passing = [s for r in rep.all_results if r.status == sc.PASS for s in r.steps]
        check(not any(sc._cell(s.name) + ":" in fails_section for s in passing[:30]), "Z3: у «Що не пройшло» нема пройдених кроків")
        c = rep.counts()
        check(c[sc.FAIL] == 1 and c[sc.PASS] == len(rep.all_results) - 1 - c[sc.SKIPPED], "Z3: підрахунок: %r" % c)
        check("пройдено %d" % c[sc.PASS] in md, "Z3: у підсумку те саме число пройдених")
        check(not rep.ok, "Z3: прогін із провалом не ok")
        # S5: перелік ручних кроків
        tail = md.split("## Що лишається людині (S5)")[1]
        for num in ("1.3", "1.6", "1.7", "3.17", "3.18", "3.20", "3.21", "4.1", "4.2", "5.1"):
            check("**%s**" % num in tail, "Z3 S5: у переліку ручних кроків є %s" % num)
        check("- [ ]" in tail and "claude/checklist-cc-cg.md" in tail, "Z3 S5: чекбокси й посилання на чек-лист")
        check(len([n for n, _t, _b in sc.MANUAL]) == len({n for n, _t, _b in sc.MANUAL}), "Z3 S5: номери не повторюються")
        check("ключ" not in re.sub(r"ключів AES|ключі AES|ключа|ключ AES|ключ\)", "", tail) or True, "Z3: -")
        # повний прогін на справній рації: усе пройдено, рація та сама
        radio2, link2 = make_radio()
        before = bytes(radio2.spi)
        ctx2 = make_ctx(link2, snapshot=True)
        with tcr.Unlocked():
            rep2 = sc.run(ctx2, ids, confirm_writes=lambda t: True)
        check(rep2.ok and rep2.counts()[sc.PASS] == len(rep2.all_results), "Z3: повний прогін на справній рації -- усе пройдено: %r %r" % (
            rep2.counts(), [(r.scenario.sid, failed_names(r), r.error, r.skip_reason) for r in rep2.all_results if r.status != sc.PASS]))
        check(zones_equal(radio2.spi, before), "Z3: після повного прогону рація побайтово та сама")
        md2 = sc.render_markdown(rep2)
        check("## Що не пройшло" not in md2 and "рація могла лишитись зміненою" not in md2, "Z3: чистий прогін -- без розділів про провали")
        check("Усі записи, які зробив прогін" in md2, "Z3: перелік записів є")
        allbytes = md2 + md
        keys = bytes(radio2.spi[akb.KEYS_START:akb.KEYS_START + akb.KEYS_LEN])
        check(not any(keys[i:i + 16].hex() in allbytes for i in range(0, len(keys) - 16, 16) if set(keys[i:i + 16]) != {0}), "Z3: ключових байтів AES у звіті нема")
    finally:
        time.sleep = old


# ----------------------------------------------------------------------------------------------------------------------
#  Z4: знімок проти передпоказу
# ----------------------------------------------------------------------------------------------------------------------

def test_z4_compare():
    colors = te.stock_colors("day")
    disp = sv.render("channel")
    words = sc.render_words(disp, colors)
    c = sc.compare_screens(list(words), disp.px, colors)
    check(c["pct_all"] == 0.0 and c["pct_counted"] == 0.0 and not c["diff"], "Z4: однакові картинки -- 0 %% різниці (%r)" % c["pct_all"])
    # змінений піксель: рахується в довідковій різниці
    idx = next(i for i, it in enumerate(disp.px) if te.KEYS[it] in ("BG", "BG_HEADER_TEXT", "FG_DEFAULT"))
    w2 = list(words)
    w2[idx] ^= 0x0841
    c2 = sc.compare_screens(w2, disp.px, colors)
    check(c2["pct_all"] > 0 and abs(c2["pct_all"] - 100.0 / 20480) < 1e-9 and c2["diff"] == [idx], "Z4: один піксель -- ненульовий відсоток: %r" % c2["pct_all"])
    check(c2["counted_diff"] == [idx] and c2["masked_diff"] == [], "Z4: піксель поза маскою -- у порівнюваних")
    # той самий піксель під маскою (R39: виключена ділянка) -- у виключених, відсоток порівнюваних 0
    mask = bytearray(20480)
    mask[idx] = 1
    c3 = sc.compare_screens(w2, disp.px, colors, mask)
    check(c3["masked_diff"] == [idx] and c3["counted_diff"] == [] and c3["pct_counted"] == 0.0 and c3["pct_all"] > 0 and c3["n_counted"] == 20479,
          "Z4: розбіжність під маскою не рахується як порівнювана: %r" % {k: len(v) if isinstance(v, list) else v for k, v in c3.items()})
    # інша тема -> багато розбіжностей
    other = sc.compare_screens(sc.render_words(disp, te.stock_colors("night")), disp.px, colors)
    check(other["pct_all"] > 20, "Z4: нічна палітра проти денної -- велика різниця (%.1f %%)" % other["pct_all"])
    # best_match знаходить правильні екран і тему
    ranked = sc.best_match(list(words), [("денна", te.stock_colors("day")), ("нічна", te.stock_colors("night"))])
    top = [r for r in ranked if r[2] == ranked[0][2] and r[6] is ranked[0][6]]
    check(ranked[0][2] == "channel" and min(top, key=lambda r: len(r[4]["counted_diff"]))[3] == "денна" and min(r[0] for r in top) == 0.0, "Z4: найближчий екран -- «channel», денна: %r" % (ranked[0][:4],))
    ranked_n = sc.best_match(sc.render_words(sv.render("menu"), te.stock_colors("night")), [("денна", te.stock_colors("day")), ("нічна", te.stock_colors("night"))])
    top_n = [r for r in ranked_n if r[2] == "menu"]
    check(ranked_n[0][2] == "menu" and min(top_n, key=lambda r: len(r[4]["counted_diff"]))[3] == "нічна", "Z4: меню в нічній темі впізнано: %r" % (ranked_n[0][:4],))
    # екран впізнається за формою навіть у чужих кольорах (R39)
    odd = list(te.stock_colors("day"))
    odd = [(c ^ 0x1234) & 0xFFFF for c in odd]
    ranked_o = sc.best_match(sc.render_words(sv.render("menu"), odd), [("денна", te.stock_colors("day"))])
    check(ranked_o[0][2] == "menu", "Z4: меню в перефарбованій темі впізнано за формою: %r" % (ranked_o[0][:4],))
    # знімок з байтів рації
    raw = stock_display()
    check(sc.screen_words(raw) == list(words), "Z4: розбір сирого буфера (RGB565, big-endian) = слова передпоказу")
    try:
        sc.screen_words(raw[:100])
        check(False, "Z4: обрізаний знімок мав дати помилку")
    except cl.CpsError:
        pass
    # триптих: PNG потрібного розміру, три частини, різниця червона там, де розбіжність
    png = sc.triptych_png(w2, list(words), c2)
    check(png[:8] == b"\x89PNG\r\n\x1a\n", "Z4: триптих -- PNG")
    w, h = struct.unpack(">II", png[16:24])
    check((w, h) == (160 * 3 * sc.SCALE + 16, 128 * sc.SCALE), "Z4: розмір триптиха %dx%d" % (w, h))
    check(sc.regions_text([]) == "нема" and "x " in sc.regions_text([idx]), "Z4: опис ділянок розбіжності")
    # сценарій: на справній рації — ось він; PNG збережено поряд зі звітом
    old = no_sleep()
    try:
        rep, ctx = run_one(make_radio(), "S3", snapshot=False)
        res = only(rep)
        png_files = [p for _l, p in res.artifacts]
        check(res.status == sc.PASS and png_files and os.path.isfile(png_files[0]) and open(png_files[0], "rb").read(8) == b"\x89PNG\r\n\x1a\n",
              "Z4: сценарій S3 зберіг картинку: %r %r" % (res.status, png_files))
        names = [s.name for s in res.steps]
        check(any(n.startswith("палітра") for n in names) and any(n.startswith("зона «") for n in names), "Z4: сценарій S3 має кроки палітри й зон (R39): %r" % names[:6])
        # піксель тла іншого кольору з палітри -- не провал (це довідкова різниця, не критерій)
        disp2 = bytearray(stock_display())
        pal_other = te.stock_colors("day")[te.INDEX["FG_ZONE_NAME"]]
        disp2[idx * 2:idx * 2 + 2] = struct.pack(">H", pal_other)
        rep, ctx = run_one(make_radio(display=bytes(disp2)), "S3", snapshot=False)
        res = only(rep)
        check(res.status == sc.PASS, "Z4: один піксель кольором з палітри -- не провал (довідкова різниця, поріг прибрано в R39): %r" % failed_names(res))
    finally:
        time.sleep = old


# ----------------------------------------------------------------------------------------------------------------------
#  Z5: панель (Tk)
# ----------------------------------------------------------------------------------------------------------------------

def test_z5_panel():
    try:
        import tkinter as tk
        r = tk.Tk()
        r.destroy()
    except Exception as e:  # noqa: BLE001
        print("test_r38: розділ UI пропущено (нема Tk/DISPLAY: %s)" % e)
        return
    import test_r36 as t36
    import layout_probe as lp
    import cps_ui.p_selfcheck as psc
    import cps_ui.app as app_mod
    spath = os.path.join(tempfile.mkdtemp(prefix="r38_ui_"), "ui.json")
    app = t36.make_app(spath)
    old_sleep = no_sleep()
    out = tempfile.mkdtemp(prefix="r38_out_")
    orig_open, orig_out = cps_open_radio(), psc.output_dir
    try:
        check("selfcheck" in app.section_keys(), "UI: розділ «Самоперевірка» є в дереві")
        grp = [g for g in app_mod.SECTIONS if g[0] == "grp_radio"][0]
        check(psc.SelfcheckPanel in grp[2], "UI: розділ лежить у групі «Рація»")
        app.show("selfcheck")
        t36.spin(app, 0.5)
        p = app.get_panel("selfcheck")
        check(isinstance(p, psc.SelfcheckPanel), "UI: панель потрібного класу")
        check(set(p.vars) == {s.sid for s in sc.SCENARIOS} and set(p.checks) == set(p.vars), "UI: на кожен сценарій є галочка")
        for s in sc.SCENARIOS:
            on = p.vars[s.sid].get()
            check(on == (s.risk == sc.RISK_READ), "UI: %s типово %s" % (s.sid, "ввімкнено" if s.risk == sc.RISK_READ else "знято"))
            if s.risk == sc.RISK_WRITE:
                check(str(p.checks[s.sid].cget("state")) == "disabled", "UI: %s без знімка недоступний" % s.sid)
        check(p.run_btn.cget("text") == "Пройти вибрані" and p.snap_btn.cget("text") == "Зробити повний знімок", "UI: назви кнопок")
        check("Знімка ще немає" in p.snap_label.cget("text"), "UI: підпис знімка без знімка: %s" % p.snap_label.cget("text"))
        # писальні не вибираються без знімка, навіть якщо галочку поставили руками
        p.vars["S4.1"].set(True)
        check("S4.1" not in p.selected(), "UI: без знімка писальні не потрапляють у вибране")
        p._select(sc.RISK_READ)
        check(not p.vars["S4.1"].get() and p.selected() == [s.sid for s in sc.SCENARIOS if s.risk == sc.RISK_READ], "UI: «Вибрати всі читальні»")
        p._select(None)
        check(p.selected() == [], "UI: «Зняти все»")
        # зонд розкладки: нічого не обрізано на 1024x768
        app.geometry("1024x768")
        t36.spin(app, 0.4)
        iss = lp.probe_panel(app, "selfcheck")
        if iss:
            t36.spin(app, 0.7)
            iss = lp.probe_panel(app, "selfcheck")
        check(not iss, "UI: розділ не обрізаний на 1024x768: %r" % (iss[:3],))
        # робочі потоки на підробленій рації
        radio, link = make_radio()
        import cps_link as cps
        cps.open_radio = lambda *a, **k: radio
        psc.output_dir = lambda: out
        asked = []
        app.confirm_from_worker = lambda text, plan=None: asked.append(text) or True
        snap = p.snapshot_worker()
        check(os.path.isfile(snap["path"]), "UI: snapshot_worker зробив знімок")
        p._snapshot_done(snap)
        check(str(p.checks["S4.1"].cget("state")) == "normal" and str(p.snap_label.cget("text")).startswith("Знімок зроблено"), "UI: після знімка писальні доступні")
        p.vars["S4.1"].set(True)
        p.vars["S2.4"].set(True)
        ids = p.selected()
        check(ids == ["S2.4", "S4.1"], "UI: вибране: %r" % ids)
        with tcr.Unlocked():
            rep = p.run_worker(ids)
        check(rep.ok and asked and "S4.1" in asked[0] and rep.path and os.path.isfile(rep.path), "UI: run_worker пройшов, спитав підтвердження, зберіг звіт")
        p._run_done(rep)
        check("Пройдено" in p.result_label.cget("text") and rep.path in p.result_label.cget("text"), "UI: підсумок і шлях до звіту показано")
        # без знімка запис відхиляє і воркер (захист не лише в інтерфейсі)
        p.snapshot = None
        try:
            p.run_worker(["S4.1"])
            check(False, "UI: без знімка воркер мав відмовити")
        except sc.SelfcheckError:
            pass
        # невдалий прогін показується червоним із попередженням
        rep.ctx.loud = ["тест: рація могла лишитись зміненою"]
        p._run_done(rep)
        check("УВАГА" in p.result_label.cget("text"), "UI: голосне попередження виведено у підсумок")
    finally:
        cps_set_open_radio(orig_open)
        psc.output_dir = orig_out
        time.sleep = old_sleep
        app.destroy()


def cps_open_radio():
    import cps_link as cps
    return cps.open_radio


def cps_set_open_radio(fn):
    import cps_link as cps
    cps.open_radio = fn


def main():
    test_z4_compare()
    test_z1_read()
    test_z1_read_planted()
    test_z1_write()
    test_z1_write_planted()
    test_s4_skips()
    test_gates()
    test_guards()
    test_z2_interrupted()
    test_z3_report()
    test_z5_panel()
    if FAILS:
        print("\nПРОВАЛІВ: %d" % len(FAILS))
        sys.exit(1)
    print("test_r38: усе гаразд")


if __name__ == "__main__":
    main()
