#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R75 (хост-перевірки без Tk і без заліза): CPS-документ тепер = кодплаг + малі блоки налаштувань (custom-data), а «Записати в рацію» --
ОДНА дія. Перевіряється на підставній рації (test_cps_restore.FakeRadioX):
  1  цикл «прочитати → змінити → записати → прочитати» дає очікуваний образ, змінено рівно те, що змінював користувач;
  2  AES (блок 6, таблиця ключів) і інші блоки поза документом (теми, SMS) НЕ змінюються; калібрування 0x10000.. і 20 байтів quickkey -- теж;
  3  кодплаг + налаштування = один діалог підтвердження, одне перезавантаження (C 6 1), страхові копії обох частин;
  4  лише налаштування -- без restore_codeplug, кодплаг у рації не чіпається; лише кодплаг -- область налаштувань не читається для запису;
  5  відмова плану (блок іншої довжини в рації) -- ДО першого запису (жодного X-пакета);
  6  захист від застарілого образу: блок, якого користувач не міняв, а рація змінила, не затирається;
  7  файл: зберегти → відкрити → налаштування збережено; старий файл (без області) відкривається, налаштування недоступні й не пишуться;
  8  «Відкинути зміни» повертає й налаштування;
  9  сторож: запис іде лише крізь cps_restore / custom_region (у doc_write.py і doc_region.py нема прямого запису у флеш) -- мутант ловиться;
 10  межа «документ/сервіс»: DOC_TYPES не містить AES (6) і лічильників RCTL (10); apply_region відхиляє правку поза DOC_TYPES.
Запуск: python3 tools/test_r75.py"""
import os
import re
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cps_link as cl            # noqa: E402
import custom_data as cd         # noqa: E402
import custom_region as cr       # noqa: E402
import doc_region as dr          # noqa: E402
import rctl_config as rctl       # noqa: E402
import aprs_beacon_cfg as abc_   # noqa: E402
import roam_cfg as rc            # noqa: E402
import test_cps_restore as tcr   # noqa: E402
import cps_ui.document as D      # noqa: E402
import cps_ui.doc_write as dw    # noqa: E402

FAILS = []
QK = (0x7524, 0x7524 + 20)
CAL = (0x10000, 0x11000)
KEYS = (cl.AES_KEYS_RAW_START, cl.AES_KEYS_RAW_START + cl.AES_KEYS_RAW_LEN)


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ: " + msg)


def make_region(blocks):
    reg = bytearray(b"\xff" * cr.REGION_LEN)
    reg[0:12] = cr.MAGIC + b"\x00" * 4
    a = 12
    for t, pl in blocks:
        reg[a:a + 8] = struct.pack("<ii", t, len(pl))
        reg[a + 8:a + 8 + len(pl)] = pl
        a += 8 + len(pl)
    return bytes(reg)


AES_BLK = b"AESK" + bytes([1, 0]) + b"\x00\x00" + (bytes([1, 3, 0, 0]) + bytes(range(32))) * 1 + b"\x00" * (36 * 15)
BLOCKS = [(4, b"\x04" * 64), (6, AES_BLK), (7, b"\x07" * 100), (9, rctl.build_payload(0, 0, False)), (15, rc.build_payload(False, 3)),
          (14, abc_.beacon_build(dict(abc_.DEFAULT_BEACON))), (13, None)]
BLOCKS = [(t, p) for t, p in BLOCKS if p is not None]


def new_radio(blocks=None, mutate=None):
    spi = tcr.spi_a()
    spi[0x20000:0x30000] = make_region(blocks if blocks is not None else BLOCKS)
    spi[KEYS[0]:KEYS[0] + 64] = bytes(range(64))                     # «секретні» байти таблиці ключів
    if mutate:
        mutate(spi)
    return tcr.FakeRadioX(bytearray(spi))


def blocks_of(radio):
    return {b.type: b.payload for b in cr.parse_region(bytes(radio.spi[0x20000:0x30000])).blocks}


class Conf:
    def __init__(self, answer=True):
        self.texts = []
        self.answer = answer

    def __call__(self, text, _plan=None):
        self.texts.append(text)
        return self.answer


def quiet(*_a, **_k):
    pass


def write(radio, doc, conf, out_dir):
    return dw.write_document(cl.CpsLink(radio), doc, conf, lambda p, t: None, out_dir, log=quiet)


def rctl_edit(doc, mask, hidden=False):
    scratch = doc.scratch_region()
    ok, msg = scratch.write_block(None, 9, rctl.build_payload(mask, 0, hidden))
    check(ok, "scratch.write_block: " + str(msg))
    return doc.apply_region(scratch, {9: "RCTL"})


def untouched(radio, before):
    s = bytes(radio.spi)
    return (s[CAL[0]:CAL[1]] == before[CAL[0]:CAL[1]] and s[QK[0]:QK[1]] == before[QK[0]:QK[1]] and s[KEYS[0]:KEYS[1]] == before[KEYS[0]:KEYS[1]])


# ---------------------------------------------------------------------------------------------------------------------------------
def test_store_parity():
    """RegionStore.write_block = custom_data.write_block (та сама раскладка байтів)."""
    a = new_radio(blocks=[(4, b"\x04" * 8)])
    store = dr.RegionStore(bytes(a.spi[0x20000:0x30000]))
    link_ser = a
    seq = [(13, bytes([0, 0, 0, 0, 9, 0, 0, 0])), (14, abc_.beacon_build(dict(abc_.DEFAULT_BEACON))), (15, rc.build_payload(True, 2)), (9, rctl.build_payload(3, 0, True))]
    for t, pl in seq:
        ok1, _ = cd.write_block(link_ser, t, pl)
        ok2, _ = store.write_block(None, t, pl)
        check(ok1 and ok2, "паритет: запис типу %d" % t)
    check(store.data() == bytes(a.spi[0x20000:0x30000]), "паритет: область у пам'яті = область, записана custom_data (байт-у-байт)")
    check(store.read_block(None, 9, 99) == cd.read_block(link_ser, 9, 99), "паритет: читання блока")
    ok, _msg = store.write_block(None, 6, b"x")
    check(not ok, "RegionStore відмовляє блоку поза документом (AES, тип 6)")


def test_roundtrip_region_only():
    tmp = tempfile.mkdtemp(prefix="r75_")
    radio = new_radio()
    before = bytes(radio.spi)
    doc = D.from_radio(cl.CpsLink(radio))
    check(doc.region is not None and doc.origin == "radio", "прочитано з рації: документ має налаштування")
    check(not doc.modified and not doc.region_changed_types(), "після читання змін нема")
    check(rctl_edit(doc, rctl.ALLOW_CHECK | rctl.ALLOW_REVIVE), "правка RCTL прийнята")
    check(doc.modified and doc.region_changed_types() == [9] and doc.pending_write() and not doc.image_pending(), "змінено лише RCTL; кодплаг не чіпали")
    conf = Conf()
    out = write(radio, doc, conf, tmp)
    after = blocks_of(radio)
    exp = dict(blocks_of(new_radio()))
    exp[9] = rctl.build_payload(rctl.ALLOW_CHECK | rctl.ALLOW_REVIVE, 0, False)
    check(after == exp, "у рації змінився рівно блок 9 (RCTL), усі інші блоки (теми, AES-селектор, SMS, роумінг, бікон) такі самі")
    check(untouched(radio, before), "калібрування, quickkey і таблиця ключів AES не змінились")
    check(bytes(radio.spi[:0x20000]) == before[:0x20000] and bytes(radio.spi[0x30000:KEYS[0]]) == before[0x30000:KEYS[0]], "поза областю налаштувань рація не змінилась")
    check(len(conf.texts) == 1 and "Віддалене керування" in conf.texts[0], "один діалог підтвердження, у ньому розділ названо словами: %r" % conf.texts[:1])
    check(not out.get("importZip") and out.get("regionWritten") and out["regionResult"]["written"], "кодплаг не писався (restore_codeplug не запускався), налаштування записано")
    check(radio.c_calls.count(bytes([6, 1])) == 1, "одне перезавантаження C 6 1: %r" % radio.c_calls)
    check(any(f.startswith("customdata_pre-write") for f in os.listdir(tmp)), "страхова копія області збережена")
    safe = [f for f in os.listdir(tmp) if f.startswith("customdata_pre-write")][0]
    check(open(os.path.join(tmp, safe), "rb").read() == before[0x20000:0x30000], "страхова копія = область ДО запису")
    doc.mark_written(out["written_image"], region_written=out["regionWritten"])
    check(not doc.modified and not doc.region_changed_types(), "після запису документ без змін")
    # читаємо назад і порівнюємо
    back = D.from_radio(cl.CpsLink(radio))
    check(back.region.data() == bytes(radio.spi[0x20000:0x30000]), "читання назад збігається з тим, що в рації")
    check(back.region.read_block(None, 9, 8) == exp[9], "значення RCTL після читання назад")


def test_codeplug_and_region_one_dialog():
    tmp = tempfile.mkdtemp(prefix="r75_")
    radio = new_radio()
    before = bytes(radio.spi)
    doc = D.from_radio(cl.CpsLink(radio))
    doc.edit_contacts([{"op": "add", "name": "Київ", "id": 2550, "type": 0}])
    rctl_edit(doc, rctl.ALLOW_MONITOR)
    sc = doc.scratch_region()
    sc.write_block(None, 15, rc.build_payload(True, 2))
    doc.apply_region(sc, {15: "Роумінг"})
    conf = Conf()
    out = write(radio, doc, conf, tmp)
    check(len(conf.texts) == 1, "кодплаг + налаштування = ОДИН діалог (було викликів: %d)" % len(conf.texts))
    t = conf.texts[0]
    check("Київ" in t and "Віддалене керування" in t and "Роумінг" in t, "діалог показує і кодплаг, і налаштування: %r" % t[:300])
    check(radio.c_calls.count(bytes([6, 1])) == 1, "одне перезавантаження наприкінці (а не по одному на частину): %r" % radio.c_calls)
    cp2, _m = cl_view(radio)
    check(any(c[1] == "Київ" for c in cp2.contacts()), "контакт у рації")
    b = blocks_of(radio)
    check(b[9] == rctl.build_payload(rctl.ALLOW_MONITOR, 0, False) and b[15] == rc.build_payload(True, 2), "обидва блоки налаштувань у рації")
    check(untouched(radio, before), "калібрування, quickkey, ключі AES не змінились")
    check(b[6] == dict(BLOCKS)[6] and b[4] == dict(BLOCKS)[4] and b[7] == dict(BLOCKS)[7], "AES-селектор, тема й SMS не змінились")
    fs = os.listdir(tmp)
    check(any("pre-restore" in f for f in fs) and any(f.startswith("customdata_pre-write") for f in fs), "страхові копії обох частин: %r" % fs)
    check(out.get("importZip") and out["regionResult"]["written"], "відпрацювали обидва шляхи")


def cl_view(radio):
    import codeplug_view as cv
    return cv.codeplug_from_radio(cl.CpsLink(radio, retries=0))


def test_cancel_writes_nothing():
    tmp = tempfile.mkdtemp(prefix="r75_")
    radio = new_radio()
    before = bytes(radio.spi)
    doc = D.from_radio(cl.CpsLink(radio))
    rctl_edit(doc, rctl.ALLOW_CHECK)
    out = write(radio, doc, Conf(False), tmp)
    check(out.get("cancelled") and bytes(radio.spi) == before and not radio.c_calls, "«Скасувати» у діалозі: рація не змінена, перезавантаження нема")


def test_stale_protection():
    tmp = tempfile.mkdtemp(prefix="r75_")
    radio = new_radio()
    doc = D.from_radio(cl.CpsLink(radio))
    rctl_edit(doc, rctl.ALLOW_CHECK)
    # після читання рація САМА змінила роумінг (блок 15), користувач його не чіпав
    other = rc.build_payload(True, 4)
    ok, _ = cd.write_block(radio, 15, other)
    check(ok, "підготовка: рація змінила блок 15")
    write(radio, doc, Conf(), tmp)
    b = blocks_of(radio)
    check(b[15] == other, "блок, якого користувач не змінював, лишився таким, яким його зробила рація (застарілий образ не затирає)")
    check(b[9] == rctl.build_payload(rctl.ALLOW_CHECK, 0, False), "а змінений користувачем -- записано")


def test_refused_before_any_write():
    tmp = tempfile.mkdtemp(prefix="r75_")
    radio = new_radio(blocks=[(9, b"\x00" * 3)])           # у рації блок 9 іншої довжини: прошивка довжину наявного блока міняти не дозволяє
    doc_region = make_region([(9, rctl.build_payload(0, 0, False))])
    from_file = D.Document(cl_view(radio)[0], "file", source_file="x.zip", region=doc_region)
    n0 = len(radio.x_calls)
    try:
        write(radio, from_file, Conf(), tmp)
        check(False, "блок іншої довжини мав дати відмову")
    except cl.CpsError as e:
        check("Нічого не записано" in str(e), "відмова словами: %s" % e)
    check(len(radio.x_calls) == n0 and not radio.c_calls, "відмова ДО першого запису: жодного X-пакета, жодного перезавантаження")


def test_file_roundtrip_and_old_file():
    tmp = tempfile.mkdtemp(prefix="r75_")
    radio = new_radio()
    doc = D.from_radio(cl.CpsLink(radio))
    rctl_edit(doc, rctl.ALLOW_STUN, True)
    path = os.path.join(tmp, "doc.zip")
    doc.save_as(path)
    check(not doc.modified, "після «Зберегти у файл» незбережених змін нема")
    again = D.from_backup(path)
    check(again.region is not None and again.region.data() == dr.redact_secrets(doc.region.data())[0], "файл → документ: налаштування збережено (крім секретів)")
    check(again.region_changed_types() == [t for t in dr.DOC_TYPES if t in dr.block_map(again.region.data())], "документ з файла: до запису всі блоки документа (рація приводиться до файла)")
    # той самий .zip читає і звичайне відновлення/бекап (формат сумісний)
    m, ee, fl = cl.read_backup_zip(path)
    check(len(ee) == cl.EEPROM_BACKUP_LEN and "customData" in m.get("parts", {}), "zip читається як бекап; частина customData описана")
    # ключі AES не потрапляють у файл документа: у новому блоці 6 з «ключовим матеріалом» усе після заголовка обнулено
    saved = cr.read_backup_region(path)
    blk6 = cr.parse_region(saved).by_type()[6]
    check(not blk6.secret and len(blk6.payload) == len(AES_BLK) and bytes(range(32)) not in saved, "файл документа: ключового матеріалу AES нема (блок 6 обнулено, довжину збережено)")
    check(AES_BLK in doc.region.data(), "у самому документі (пам'ять) блок лишається як є -- у рацію він і так не пишеться")
    # запис файла в іншу рацію: тільки DOC_TYPES, AES/теми з файла НЕ потрапляють
    r2 = new_radio(blocks=[(4, b"\x44" * 64), (6, AES_BLK), (9, rctl.build_payload(0, 0, False)), (15, rc.build_payload(False, 3))])
    before = bytes(r2.spi)
    write(r2, again, Conf(), tmp)
    b2 = blocks_of(r2)
    check(b2[9] == rctl.build_payload(rctl.ALLOW_STUN, 0, True), "налаштування з файла записано")
    check(b2[4] == b"\x44" * 64 and b2[6] == AES_BLK, "тема й AES-селектор у рації НЕ замінені блоками з файла")
    check(untouched(r2, before), "калібрування, quickkey, ключі AES не змінились")
    # старий файл (без customdata.bin)
    old_doc = D.from_radio(cl.CpsLink(new_radio()))
    old_path = os.path.join(tmp, "old.zip")
    ee, fl = bytes(old_doc.image.eeprom), bytes(old_doc.image.flash)
    rng = cl.flash_backup_range()
    info = dict(old_doc.manifest.get("radio") or {})
    man = cl.build_manifest(info, ee, fl, rng, 0, 0, 0)
    open(old_path, "wb").write(cl.make_zip(ee, fl, man))
    old = D.from_backup(old_path)
    check(old.region is None and old.region_changed_types() == [], "старий файл відкривається; налаштувань у ньому нема й їх не пишемо")
    try:
        old.scratch_region()
        check(False, "scratch_region у старому файлі мав дати відмову")
    except D.DocumentError:
        pass
    r3 = new_radio()
    snap = bytes(r3.spi[0x20000:0x30000])
    old.edit_contacts([{"op": "add", "name": "Old", "id": 77, "type": 0}])
    write(r3, old, Conf(), tmp)
    check(bytes(r3.spi[0x20000:0x30000]) == snap, "запис старого файла налаштувань рації не чіпає")


def test_discard_restores_region():
    radio = new_radio()
    doc = D.from_radio(cl.CpsLink(radio))
    base = doc.region.data()
    rctl_edit(doc, rctl.ALLOW_CHECK)
    check(doc.modified and doc.region.data() != base, "правка в документі")
    doc.discard()
    check(not doc.modified and doc.region.data() == base and not doc.changes, "«Відкинути зміни» повертає і налаштування")


def test_boundary():
    check(set(dr.DOC_TYPES).isdisjoint(dr.NEVER_TYPES) and 6 not in dr.DOC_TYPES and 10 not in dr.DOC_TYPES, "межа: у документі нема AES (6) і лічильників RCTL (10)")
    check(set(dr.DOC_TYPES) <= {t for t, v in cr.BLOCK_TYPES.items() if v[4] == "setting"}, "межа: усе в документі -- налаштування (не дані й не стан)")
    radio = new_radio()
    doc = D.from_radio(cl.CpsLink(radio))
    sc = doc.scratch_region()
    cr.simulate_write(sc.buf, 4, b"\x99" * 64)           # правка теми в обхід RegionStore.write_block
    try:
        doc.apply_region(sc)
        check(False, "правка блока поза документом мала бути відхилена")
    except D.DocumentError:
        check(doc.region.data() == dr.RegionStore(bytes(radio.spi[0x20000:0x30000])).data(), "документ як був")
    sc2 = doc.scratch_region()
    cr.simulate_write(sc2.buf, 6, AES_BLK[:-1] + b"\x01")
    try:
        doc.apply_region(sc2)
        check(False, "правка AES мала бути відхилена")
    except D.DocumentError:
        pass
    try:
        dr.plan_for_radio([cr.Block(6, 0, AES_BLK)], bytes(radio.spi[0x20000:0x30000]))
        check(False, "план із AES мав впасти")
    except AssertionError:
        pass


def src(*p):
    return open(os.path.join(HERE, *p), encoding="utf-8").read()


FORBIDDEN = re.compile(r"flash_write_block|flash_write_span|\bwrite_span\(|\bwrite_group\(|_x_exchange|\.write\(b?[\"']X|ser\.write\(")


def test_guard_not_bypassed(mutate=False):
    for fn in ("cps_ui/doc_write.py", "doc_region.py"):
        text = src(fn)
        if mutate:
            text += "\n    aks.flash_write_block(ser, 0x10000, b'x')\n"
        hits = FORBIDDEN.findall(text)
        check(not hits or mutate, "%s: прямого запису у флеш нема (є: %r)" % (fn, hits))
        if mutate:
            return bool(hits)
    da = src("cps_ui/doc_actions.py")
    check(not FORBIDDEN.search(da), "doc_actions.py: прямого запису нема")
    wr = src("cps_ui/doc_write.py")
    check("write_image_via_restore" in wr and "cr.apply_plan" in src("doc_region.py").replace("cr.apply_plan", "cr.apply_plan") and "apply_plan" in src("doc_region.py"),
          "запис іде лише крізь write_image_via_restore (cps_restore) і custom_region.apply_plan")


def test_no_panel_writes_to_radio():
    """Панелі групи «Дані» не мають власних кнопок читання/запису рації (aprs-бікон, RCTL, роумінг)."""
    for fn in ("cps_ui/p_aprs.py", "cps_ui/p_rctl.py", "cps_ui/p_roam.py"):
        t = src(fn)
        check("open_radio" not in t and "custom_data" not in t and "CpsLink" not in t, "%s: без звернень до рації" % fn)
        check("Записати бікон" not in t and "Записати на рацію" not in t and "Записати налаштування в рацію" not in t and "Записати імена в рацію" not in t,
              "%s: старих кнопок запису в рацію нема" % fn)


def main():
    test_store_parity()
    test_roundtrip_region_only()
    test_codeplug_and_region_one_dialog()
    test_cancel_writes_nothing()
    test_stale_protection()
    test_refused_before_any_write()
    test_file_roundtrip_and_old_file()
    test_discard_restores_region()
    test_boundary()
    test_guard_not_bypassed()
    caught = test_guard_not_bypassed(mutate=True)
    check(caught, "мутант: прямий запис у обхід охоронця ловиться")
    test_no_panel_writes_to_radio()
    if FAILS:
        print("test_r75: ПРОВАЛІВ %d" % len(FAILS))
        sys.exit(1)
    print("test_r75: усе гаразд")


if __name__ == "__main__":
    main()
