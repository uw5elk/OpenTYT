#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R37: стан і ущільнення області custom-data (custom_compact.py, вікно `customdata` у flash_guard.py, хук нестачі місця в custom_data.write_block,
розділ «Усі налаштування»).

Рації нема: SPI-флеш підроблено (FakeRadioX з test_cps_restore розуміє 'R' і 'X 1/2/3', веде список записаних секторів і вміє «замовкнути» посеред запису),
тож РЕАЛЬНІ алгоритми (custom_compact -> flash_guard.write_span -> aes_key_store.flash_write_block) відпрацьовують на підробленому флеші.

Z1  область із трьома вилученими блоками: після ущільнення живі блоки побайтово ті самі, вилучені зникли, вільного більше рівно на їхній розмір, хвіст 0xFF,
    решта флеша не змінилась, страхова копія == область до запису, рація перезавантажується;
Z2  обрив на КОЖНОМУ кроці запису: область у рації або як була, або вже ущільнена, або без заголовка («нема»); покрученого вмісту із заголовком не буває;
    страхова копія ціла; звірка після запису ловить зіпсований коміт;
Z3  порожня область, область без вилучених блоків, область заповнена під зав'язку, пошкоджена область;
Z4  жоден запис не виходить за межі області (сектори 0x20..0x2F, калібрування не чіпається, сусідні ділянки не змінюються; охоронець відхиляє вихід за межі);
U1  стан області (числа з вмісту) і попередження «замало місця для орбіт»;
U3  нестача місця при записі блока: пояснення з числами, пропозиція ущільнення (хук), відмова, марне ущільнення;
R   повернення області зі страхової копії після обірваного запису;
UI  розділ «Усі налаштування» (Tk): стан, кнопки, хук у застосунку.
Запуск: `xvfb-run -a python3.12 tools/test_r37.py` (без DISPLAY розділ UI пропущено)."""
import os
import random
import struct
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import aes_key_store as aks              # noqa: E402
import cps_link as cl                    # noqa: E402
import custom_compact as cc              # noqa: E402
import custom_data as cd                 # noqa: E402
import custom_region as cr               # noqa: E402
import flash_guard as fg                 # noqa: E402
import sat_tle                           # noqa: E402
import test_cps_restore as tcr           # noqa: E402

FAILS = []
tcr.FakeRadioX.close = lambda self: None
RET = cr.RETIRED_BASE
BASE = 0x20000
LEN = 0x10000
RESERVED = b"\x00\x11\x22\x33"


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def quiet(*_a, **_k):
    pass


def payload(seed, n):
    r = random.Random(seed)
    return bytes(r.randrange(0, 255) for _ in range(n))          # без 0xFF: відрізняється від стертого


def raw(t, data):
    return struct.pack("<ii", t, len(data)) + data


def build_region(entries, terminator=True):
    """entries -- [(тип, дані)] підряд; решта 0xFF. Повертає bytes області (64 КіБ)."""
    out = bytearray(b"\xff" * LEN)
    out[:12] = cr.MAGIC + RESERVED
    pos = 12
    for t, d in entries:
        r = raw(t, d)
        out[pos:pos + len(r)] = r
        pos += len(r)
    return bytes(out), pos


def make_spi(region):
    spi = tcr.spi_a()
    if len(spi) < 0x40000:
        spi.extend(b"\xff" * (0x40000 - len(spi)))
    spi[BASE:BASE + LEN] = region
    spi[0x1F000:0x20000] = b"\xA5" * 0x1000          # сусіди області: мають лишитись як були
    spi[0x30000:0x31000] = b"\x5A" * 0x1000
    return spi


def region_of(spi):
    return bytes(spi[BASE:BASE + LEN])


def no_sleep():
    old = time.sleep
    time.sleep = lambda _s: None
    return old


def run_compact(spi, confirm=lambda *_a: True, die_after_x=None, corrupt_commit=False, safety_dir=None, post_reset=True):
    radio = tcr.FakeRadioX(spi, die_after_x=die_after_x, corrupt_commit=corrupt_commit)
    d = safety_dir or tempfile.mkdtemp(prefix="r37_")
    res = cc.compact_region(cl.CpsLink(radio), confirm, d, log=quiet, post_reset=post_reset)
    return radio, res, d


# Типова область з трьома вилученими блоками: перший вилучений -- глибоко (за межею першого сектора), щоб було видно, що чіпаються лише потрібні сектори
LIVE_A = [(7, payload(1, 1352)), (8, payload(2, 493)), (100, payload(3, 3000))]


def sample_entries():
    return [LIVE_A[0], LIVE_A[1], LIVE_A[2], (RET + 1, payload(4, 1024)), (4, payload(5, 64)), (RET + 3, payload(6, 2520)), (5, payload(7, 64)),
            (RET + 2, payload(8, 512)), (9, payload(9, 8))]


# ----------------------------------------------------------------------------------------------------------------------
#  Z1
# ----------------------------------------------------------------------------------------------------------------------

def test_z1():
    ents = sample_entries()
    region, old_end = build_region(ents)
    spi = make_spi(region)
    before_all = bytes(spi)
    retired_size = sum(8 + len(d) for t, d in ents if cr.is_retired(t))
    live = [(t, d) for t, d in ents if not cr.is_retired(t)]
    live_size = sum(8 + len(d) for t, d in live)
    check(retired_size == 8 * 3 + 1024 + 2520 + 512, "Z1: розрахунок розміру вилучених: %d" % retired_size)

    scan, st = cc.stats_of(region)
    check(st is not None and st.retired_count == 3 and st.retired_bytes == retired_size and st.live_count == 6 and st.live_bytes == live_size,
          "Z1: стан ДО -- вилучені %s шт. %s Б, живі %s шт. %s Б" % (st and st.retired_count, st and st.retired_bytes, st and st.live_count, st and st.live_bytes))
    check(st.used == old_end and st.free == LEN - old_end, "Z1: зайнято %d, вільно %d (очікувано %d / %d)" % (st.used, st.free, old_end, LEN - old_end))

    radio, res, d = run_compact(spi)
    check(res["ok"] and res["verified"] and not res["cancelled"] and not res["nothingToDo"], "Z1: ущільнення виконано й звірено: %s" % res.get("text", "")[:200])
    after = region_of(spi)
    # живі блоки побайтово ті самі, у тому самому порядку
    exp = bytearray(b"\xff" * LEN)
    exp[:12] = cr.MAGIC + RESERVED
    pos = 12
    for t, dd in live:
        r = raw(t, dd)
        exp[pos:pos + len(r)] = r
        pos += len(r)
    check(pos == 12 + live_size, "Z1: нова межа блоків = 12 + живі")
    check(after == bytes(exp), "Z1: область після ущільнення == заголовок + живі блоки підряд + 0xFF (побайтово)")
    reg2 = cr.parse_region(after)
    check([(b.type, b.payload) for b in reg2.blocks] == live, "Z1: живі блоки (тип і вміст) ті самі, порядок збережено")
    check(not any(cr.is_retired(b.type) for b in reg2.blocks), "Z1: вилучених блоків нема")
    check(not reg2.problems, "Z1: область розбирається без проблем: %r" % reg2.problems)
    scan2, st2 = cc.stats_of(after)
    check(st2.free - st.free == retired_size, "Z1: вільного більше рівно на розмір вилучених (%d, очікувано %d)" % (st2.free - st.free, retired_size))
    check(st2.retired_count == 0 and st2.retired_bytes == 0, "Z1: лічильник вилучених = 0")
    check(after[pos:] == b"\xff" * (LEN - pos), "Z1: увесь хвіст після блоків -- 0xFF (прошивка шукає перший вільний слот за довжиною 0xFFFFFFFF)")
    check(after[8:12] == RESERVED, "Z1: 4 зарезервованих байти заголовка збережено")
    check(bytes(spi[:BASE]) == before_all[:BASE] and bytes(spi[BASE + LEN:]) == before_all[BASE + LEN:], "Z1: за межами області флеш не змінився ні на байт")
    check(bytes(spi[0x1F000:0x20000]) == b"\xA5" * 0x1000 and bytes(spi[0x30000:0x31000]) == b"\x5A" * 0x1000, "Z1: сусідні сектори (до і після області) цілі")
    # страхова копія
    sp = res["safetyCopy"]
    check(sp and os.path.dirname(sp) == d and os.path.basename(sp).startswith("customdata_pre-compact_") and sp.endswith(".bin"), "Z1: ім'я страхової копії: %s" % sp)
    with open(sp, "rb") as f:
        check(f.read() == region, "Z1: страхова копія == область ДО запису")
    check(radio.reset_requested, "Z1: після успіху рація перезавантажується (C 6 1)")
    check(not radio.cal_touched, "Z1: калібрування не чіпали")
    # що записано: заголовок двічі (обнулення, запис), а сектори даних -- лише змінені
    first_ret = min(e.offset for e in scan.retired)
    diff_sectors = sorted({s for s in range(LEN // 4096) if (s + 1) * 4096 > first_ret and s * 4096 < old_end})
    want_sectors = {0x20 + s for s in diff_sectors} | {0x20}
    check(set(radio.commits) == want_sectors, "Z1: записані сектори %s, очікувано %s" % (sorted(hex(x) for x in set(radio.commits)), sorted(hex(x) for x in want_sectors)))
    check(radio.commits[0] == 0x20 and radio.commits[-1] == 0x20, "Z1: порядок -- спершу заголовок (сектор 0x20), останнім теж заголовок: %r" % radio.commits)
    check(first_ret > 4096 and 0 not in diff_sectors, "Z1: у цьому прикладі перший вилучений блок лежить за першим сектором, тож сектор даних 0 не переписується")
    # відхилене підтвердження -- нічого не записано, але копія зберігається
    spi2 = make_spi(region)
    r2, res2, d2 = run_compact(spi2, confirm=lambda *_a: False)
    check(res2["cancelled"] and region_of(spi2) == region and not r2.commits and not r2.reset_requested, "Z1: скасовано -- область і рація не чіпались")
    check(os.path.exists(res2["safetyCopy"]), "Z1: страхова копія створена ще до питання")
    # текст підтвердження показує «до» і «після»
    asked = []
    run_compact(make_spi(region), confirm=lambda t, p: asked.append(t) or True)
    t0 = asked[0] if asked else ""
    check("ДО:" in t0 and "ПІСЛЯ:" in t0 and "ПРИБИРАЄТЬСЯ" in t0 and "зсув" in t0 and "Звільнено: %d Б" % retired_size in t0, "Z1/U2.5: підтвердження показує до, після, що зникне і скільки звільнено")
    check(d in res["safetyCopy"] and "Область ущільнено й звірено байт у байт" in res["text"] and "ДО:" in res["text"], "Z1/U2.5: підсумок -- до і після")


# ----------------------------------------------------------------------------------------------------------------------
#  Z2
# ----------------------------------------------------------------------------------------------------------------------

def test_z2():
    ents = sample_entries()
    region, _end = build_region(ents)
    plan, why = cc.plan_compaction(region)
    expected = plan.expected
    radio, res, _d = run_compact(make_spi(region))
    total_x = radio.x_total
    check(total_x >= 9, "Z2: повний запис складається з %d X-команд" % total_x)
    outcomes = {"as_is": 0, "no_region": 0, "done": 0}
    for k in range(0, total_x + 1):
        spi = make_spi(region)
        radio, res, d = run_compact(spi, die_after_x=k)
        now = region_of(spi)
        sc = cr.parse_region(now)
        if now == region:
            kind = "as_is"
        elif now == expected:
            kind = "done"
        elif not sc.magic_ok:
            kind = "no_region"
        else:
            kind = None
        check(kind is not None, "Z2: обрив після %d X-команд: область і не стара, і не нова, і не «нема» (заголовок %r є, а вміст покручений)" % (k, now[:8]))
        if kind:
            outcomes[kind] += 1
        check(os.path.exists(res["safetyCopy"]) and open(res["safetyCopy"], "rb").read() == region, "Z2: після обриву (k=%d) страхова копія ЦІЛА й == початкова" % k)
        if kind != "done":
            check(not res["ok"], "Z2: обрив (k=%d) не видано за успіх" % k)
            check(res["safetyCopy"] in res["text"] and "Відновити" in res["text"], "Z2: текст помилки (k=%d) вказує страхову копію й що з нею робити" % k)
        if kind == "no_region":
            check("«нема»" in res["text"] or "нема" in res["text"] and "ТИПОВИМИ" in res["text"], "Z2: текст помилки (k=%d) пояснює, що рація тепер читає область як «нема»" % k)
        check(not radio.cal_touched, "Z2: калібрування не чіпали (k=%d)" % k)
    check(outcomes["as_is"] >= 1 and outcomes["no_region"] >= 3 and outcomes["done"] >= 1, "Z2: усі три види наслідків зустрілись: %r" % outcomes)
    # обірваний запис -- рація читає область як «нема»: прошивка (дзеркало алгоритму) не знаходить жодного блока
    for k in range(total_x):
        spi = make_spi(region)
        run_compact(spi, die_after_x=k)
        now = region_of(spi)
        if now != region and now != expected:
            fk, _a, _l = cd.find_or_alloc_block(tcr.FakeRadioX(spi), 7, 0)          # справжній пошук блока так, як його веде прошивка
            check(fk is None, "Z2: обірваний запис (k=%d) -- прошивка не знаходить жодного блока (область читається як «нема»)" % k)
    # зіпсований коміт: звірка після запису це ловить
    spi = make_spi(region)
    radio, res, d = run_compact(spi, corrupt_commit=True)
    check(not res["ok"] and res["verified"] is False and "ПОМИЛКА ЗВІРКИ" in res["text"] and res["safetyCopy"] in res["text"] and not radio.reset_requested,
          "Z2/U2.4: розбіжність після запису -- голосна помилка зі страхової копією, перезавантаження не робиться: %s" % res.get("text", "")[:160])
    check("перший" in res["text"] and "зсуві" in res["text"], "Z2/U2.4: помилка називає перший розбіжний зсув")
    # без страхової копії нічого не пишеться
    bad_dir = os.path.join(tempfile.mkdtemp(prefix="r37_"), "нема-такої-теки")
    spi = make_spi(region)
    radio = tcr.FakeRadioX(spi)
    try:
        cc.compact_region(cl.CpsLink(radio), lambda *_a: True, bad_dir, log=quiet)
        check(False, "Z2/U2.2: без теки для копії ущільнення мало відмовити")
    except cc.CompactError as e:
        check("страхов" in str(e) and "Нічого не записано" in str(e), "Z2/U2.2: відмова пояснена: %s" % e)
    check(region_of(spi) == region and radio.x_total == 0, "Z2/U2.2: без копії -- жодної X-команди, область як була")
    # копія, що не читається назад -> не пишемо
    spi = make_spi(region)
    radio = tcr.FakeRadioX(spi)
    orig_open = open
    d3 = tempfile.mkdtemp(prefix="r37_")

    import builtins

    class Liar:
        """Файл, що нічого не пише (диск «з'їв» дані): перевірка читанням має це виявити."""

        def __init__(self, *a, **k):
            self.f = orig_open(*a, **k)

        def __getattr__(self, n):
            return getattr(self.f, n)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.f.close()

        def write(self, data):
            return len(data)

    builtins.open = lambda p, m="r", *a, **k: Liar(p, m, *a, **k) if (str(p).startswith(d3) and "x" in m) else orig_open(p, m, *a, **k)
    try:
        try:
            cc.compact_region(cl.CpsLink(radio), lambda *_a: True, d3, log=quiet)
            check(False, "Z2/U2.2: копія, що не читається назад, мала зупинити запис")
        except cc.CompactError as e:
            check("страхов" in str(e), "Z2/U2.2: збій копії пояснено: %s" % e)
    finally:
        builtins.open = orig_open
    check(radio.x_total == 0 and region_of(spi) == region, "Z2/U2.2: копія не пройшла перевірку -- запису не було")
    check(os.listdir(d3) == [], "Z2/U2.2: непридатну копію прибрано")


# ----------------------------------------------------------------------------------------------------------------------
#  Z3
# ----------------------------------------------------------------------------------------------------------------------

def test_z3():
    # порожня (стерта) область
    spi = make_spi(b"\xff" * LEN)
    radio, res, d = run_compact(spi)
    check(res["nothingToDo"] and radio.x_total == 0 and os.listdir(d) == [] and not radio.reset_requested, "Z3: стерта область -- нічого не робимо, копії/запису нема: %s" % res["text"])
    check("нема" in res["text"], "Z3: стерта область -- пояснено: %s" % res["text"])
    # область без заголовка, але не стерта
    junk = bytearray(b"\xff" * LEN)
    junk[:8] = b"NotOpenG"
    radio, res, d = run_compact(make_spi(bytes(junk)))
    check(res["nothingToDo"] and radio.x_total == 0, "Z3: область без заголовка OpenGD77 -- відмова без запису")
    # порожня, але з заголовком (жодного блока)
    reg, _e = build_region([])
    radio, res, d = run_compact(make_spi(reg))
    check(res["nothingToDo"] and radio.x_total == 0 and "нема" in res["text"], "Z3: заголовок без блоків -- ущільнювати нічого")
    # без вилучених блоків
    reg, _e = build_region([(4, payload(1, 64)), (5, payload(2, 64)), (7, payload(3, 1352))])
    spi = make_spi(reg)
    radio, res, d = run_compact(spi)
    check(res["nothingToDo"] and radio.x_total == 0 and region_of(spi) == reg and os.listdir(d) == [] and "вилучених блоків нема" in res["text"],
          "Z3: без вилучених блоків -- ущільнювати нічого, жодних записів і копій: %s" % res["text"])
    # заповнена під зав'язку (область = рівно 64 КіБ, без вільного слота), без вилучених
    big = 0x10000 - 12 - 8 - 8 - 64
    reg_full, end = build_region([(4, payload(1, 64)), (100, payload(2, big))])
    pad = LEN - end
    ents = [(4, payload(1, 64)), (100, payload(2, big + pad))]
    reg_full, end = build_region(ents)
    check(end == LEN, "Z3: область заповнена рівно до кінця (%d з %d)" % (end, LEN))
    scan, st = cc.stats_of(reg_full)
    check(st is not None and st.free == 0 and st.max_payload == 0 and not scan.terminated, "Z3: стан повної області: вільно 0, нового блока не вмістити")
    spi = make_spi(reg_full)
    radio, res, d = run_compact(spi)
    check(res["nothingToDo"] and radio.x_total == 0, "Z3: повна область без вилучених -- ущільнювати нічого")
    check("УВАГА" in cc.state_text(reg_full), "Z3: повна область -- в стані є попередження")
    # повна область З вилученим блоком: ущільнення працює, і вільне місце з'являється саме на його розмір
    ents = [(4, payload(1, 64)), (RET + 1, payload(2, 1024))]
    fill = LEN - 12 - sum(8 + len(d) for _t, d in ents)
    ents.append((100, payload(3, fill - 8)))
    reg_full2, end2 = build_region(ents)
    check(end2 == LEN, "Z3: друга повна область -- рівно до кінця")
    spi = make_spi(reg_full2)
    radio, res, d = run_compact(spi)
    after = region_of(spi)
    sc2, st2 = cc.stats_of(after)
    check(res["ok"] and res["verified"] and st2 is not None and st2.free == 8 + 1024 and st2.retired_count == 0 and after[LEN - (8 + 1024):] == b"\xff" * (8 + 1024),
          "Z3: повна область з вилученим блоком -- ущільнено, вільно %s Б: %s" % (st2 and st2.free, res["text"][:160]))
    check(all(c in range(0x20, 0x30) for c in radio.commits) and bytes(spi[0x30000:0x31000]) == b"\x5A" * 0x1000, "Z3/Z4: запис повної області не вийшов за її межі")
    # пошкоджена область: довжина блока виходить за межі -- нічого не пишемо
    bad = bytearray(build_region([(4, payload(1, 64)), (RET + 1, payload(2, 100)), (5, payload(3, 64))])[0])
    struct.pack_into("<ii", bad, 12 + 8 + 64, RET + 1, 0x20000)
    radio, res, d = run_compact(make_spi(bytes(bad)))
    check(res["nothingToDo"] and radio.x_total == 0 and "помилками" in res["text"], "Z3: пошкоджена область -- ущільнення вимкнено, нічого не пишемо: %s" % res["text"])
    # затінений дублікат (прошивка бачить лише перший) не чіпається; вилучені прибираються
    d1, d2 = payload(1, 64), payload(2, 64)
    reg, _e = build_region([(4, d1), (RET + 5, payload(3, 100)), (4, d2)])
    spi = make_spi(reg)
    radio, res, d = run_compact(spi)
    after = region_of(spi)
    check(res["ok"] and cr.parse_region(after).by_type()[4].payload == d1, "Z3: дублікат типу -- перший лишається першим")
    check(raw(4, d1) + raw(4, d2) == after[12:12 + 2 * 72], "Z3: затінений дублікат збережено байт у байт")
    check("Затінені дублікати" in cc.state_text(reg), "Z3: стан показує затінені дублікати")


# ----------------------------------------------------------------------------------------------------------------------
#  Z4
# ----------------------------------------------------------------------------------------------------------------------

def test_z4():
    # охоронець: вікно customdata -- рівно 0x20000..0x2FFFF
    check(fg.WINDOWS["customdata"] == (0x20000, 0x30000), "Z4: вікно customdata = 0x20000..0x2FFFF (є %r)" % (fg.WINDOWS.get("customdata"),))
    check(fg.check_windows() == [], "Z4: жодне вікно не перетинає чужу захищену зону: %r" % fg.check_windows())
    spi = make_spi(build_region([])[0])
    radio = tcr.FakeRadioX(spi)
    for addr, n, why in ((0x1FFFF, 2, "починається на байт до області"), (0x2FFFF, 2, "виходить на байт за область"), (0x30000, 1, "повністю за областю"), (0x10000, 16, "калібрування"),
                         (0x20000, 0x10001, "довше за область"), (0x2F000, 0x1001, "сектор 0x2F + байт")):
        try:
            fg.write_span(radio, addr, b"\x00" * n, "customdata")
            check(False, "Z4: запис %s (0x%X, %d Б) мав бути відхилений" % (why, addr, n))
        except fg.GuardError:
            pass
    check(radio.x_total == 0, "Z4: відхилені записи не дійшли до флеша (жодної X-команди)")
    fg.write_span(radio, 0x2FFFF, b"\x00", "customdata")
    fg.write_span(radio, 0x20000, b"\x00", "customdata")
    check(radio.commits == [0x2F, 0x20], "Z4: крайні байти області дозволені й потрапляють у сектори 0x2F та 0x20")
    # інші вікна не можуть писати в область custom-data
    for w in ("keys", "dmrdb", "rawarea"):
        try:
            fg.write_span(radio, 0x20000, b"\x00", w)
            check(False, "Z4: вікно %s не повинне діставати області custom-data" % w)
        except fg.GuardError:
            pass
    # повна ущільнювальна дія на області, де вилучений блок -- останній, а після області лежать «чужі» дані
    ents = [(4, payload(1, 64)), (7, payload(2, 20000)), (100, payload(3, 30000))]
    fill = LEN - 12 - sum(8 + len(d) for _t, d in ents) - (8 + 100) - 8
    ents.append((101, payload(4, fill)))
    ents.append((RET + 7, payload(5, 100)))
    reg, end = build_region(ents)
    check(end == LEN, "Z4: побудована область рівно до кінця (%d)" % end)
    spi = make_spi(reg)
    before = bytes(spi)
    radio, res, d = run_compact(spi)
    after = bytes(spi)
    check(res["ok"], "Z4: ущільнення області, де вилучений блок в самому кінці: %s" % res["text"][:120])
    check(after[:BASE] == before[:BASE] and after[BASE + LEN:] == before[BASE + LEN:], "Z4: нічого не змінено за межами області (до і після)")
    check(set(radio.commits) <= set(range(0x20, 0x30)), "Z4: записано лише сектори 0x20..0x2F: %r" % sorted(hex(c) for c in set(radio.commits)))
    check(not radio.cal_touched, "Z4: калібрування не чіпали")
    for kind, addr, ln in [(c[0], c[1], 0) for c in radio.x_calls if c[0] == 2]:
        check(BASE <= addr < BASE + LEN, "Z4: X 2 на адресу 0x%X поза областю" % addr)
    # згенерований тестом перебір: на випадкових областях запис завжди в межах
    rnd = random.Random(37)
    for it in range(12):
        n_live = rnd.randrange(1, 6)
        ents = []
        for j in range(n_live):
            ents.append((20 + j, payload(it * 10 + j, rnd.randrange(1, 4000))))
            if rnd.random() < 0.7:
                ents.append((RET + 20 + j, payload(it * 10 + j + 500, rnd.randrange(1, 3000))))
        reg, end = build_region(ents)
        if end >= LEN - 16:
            continue
        spi = make_spi(reg)
        before = bytes(spi)
        radio, res, d = run_compact(spi)
        after = bytes(spi)
        ok_bounds = after[:BASE] == before[:BASE] and after[BASE + LEN:] == before[BASE + LEN:] and set(radio.commits) <= set(range(0x20, 0x30))
        check(ok_bounds and (res["ok"] or res["nothingToDo"]), "Z4: випадкова область №%d -- у межах, результат %s" % (it, res["text"][:80]))
        if res["ok"] and not res["nothingToDo"]:
            sc = cr.parse_region(region_of(spi))
            live = [(t, dd) for t, dd in ents if not cr.is_retired(t)]
            check([(b.type, b.payload) for b in sc.blocks] == live, "Z4: випадкова область №%d -- живі блоки цілі" % it)


# ----------------------------------------------------------------------------------------------------------------------
#  U1
# ----------------------------------------------------------------------------------------------------------------------

def test_u1():
    ents = sample_entries()
    reg, end = build_region(ents)
    txt = cc.state_text(reg)
    st = cc.stats_of(reg)[1]
    for frag in ("Зайнято %d з %d Б" % (end, LEN), "вилучені блоки %d Б у кількості 3" % st.retired_bytes, "Вільно %d Б" % (LEN - end),
                 "Вилучений блок (було: %s)" % cr.type_title(1)):
        check(frag in txt, "U1: у стані є «%s»" % frag)
    check(st.retired_bytes == 3 * 8 + 1024 + 2520 + 512, "U1: вилучені = %d Б (читається з області)" % st.retired_bytes)
    # попередження: вільно менше за 2520
    check(cc.BIGGEST_BLOCK == sat_tle.BLOCK_LEN == 2520, "U1: найбільший блок = орбіти %d Б" % sat_tle.BLOCK_LEN)
    ample, _e = build_region([(4, payload(1, 64))])
    check("УВАГА" not in cc.state_text(ample), "U1: вільного багато -- попередження нема")
    tight_entries = [(4, payload(1, 64)), (RET + 1, payload(2, 1024)), (100, payload(3, 100))]
    fill = LEN - 12 - sum(8 + len(d) for _t, d in tight_entries) - (8 + 2000)       # залишаємо ~2000 Б вільними: менше за 2520
    tight_entries.insert(2, (101, payload(4, fill - 8)))
    tight, e2 = build_region(tight_entries)
    sc, s2 = cc.stats_of(tight)
    check(s2.free < 2520 + 8 and LEN - e2 == s2.free, "U1: вільно %d Б -- менше за блок орбіт" % s2.free)
    w = cc.warning_text(s2, sc)
    check(w.startswith("УВАГА") and "2520" in w and "бракує" in w, "U1/U1.2: попередження про орбіти: %s" % w[:140])
    check("«Ущільнити область» звільнить %d Б" % s2.retired_bytes in w and "вмістилась" in w + "вмістилась" or "вміститься" in w, "U1/U1.2: попередження каже, чи допоможе ущільнення: %s" % w[-120:])
    # вільного майже нема і вилучених нема -- попередження каже, що прибирати нічого
    nofree, e3 = build_region([(4, payload(1, 64)), (100, payload(2, LEN - 12 - 8 - 64 - 8 - 100))])
    sc3, s3 = cc.stats_of(nofree)
    check("Вилучених блоків, які можна було б прибрати, нема" in cc.warning_text(s3, sc3), "U1/U1.2: без вилучених попередження чесне")
    # блок орбіт вже є -- примітка
    withsat, _e = build_region([(3, payload(1, 2520)), (100, payload(2, LEN - 12 - 8 - 2520 - 8 - 100))])
    scs, ss = cc.stats_of(withsat)
    check("вже є" in cc.warning_text(ss, scs), "U1/U1.2: якщо блок орбіт уже є, попередження це зазначає")
    # немає області / не розібрано
    check("нема" in cc.state_text(b"\xff" * LEN), "U1: стерта область -- «нема»")
    check(cc.stats_of(b"\xff" * LEN)[1] is None, "U1: без області статистики нема")
    # через рацію: числа беруться з байтів рації, а не з теорії (інший вміст -- інші числа)
    spi = make_spi(reg)
    radio = tcr.FakeRadioX(spi)
    got = cr.read_radio_region(cl.CpsLink(radio))
    check(cc.state_text(got) == txt, "U1: стан, прочитаний з рації, збігається зі станом з образу")


# ----------------------------------------------------------------------------------------------------------------------
#  U3
# ----------------------------------------------------------------------------------------------------------------------

def tight_region(retired=1024):
    """Область, де новий блок на 1024 Б не вміщається, а після ущільнення (retired > 0) вміщається."""
    ents = [(4, payload(1, 64)), (7, payload(2, 1352))]
    if retired:
        ents.append((RET + 1, payload(3, retired)))
    used = 12 + sum(8 + len(d) for _t, d in ents)
    ents.append((100, payload(4, LEN - used - 8 - 600)))          # лишаємо 600 Б вільними
    reg, end = build_region(ents)
    return reg, end


def test_u3():
    import splash_image as si
    import boot_melody as bm
    reg, end = tight_region()
    cd.ROOM_HOOK = None
    # без хука: write_block повертає пояснення з числами (а не глуху помилку)
    spi = make_spi(reg)
    radio = tcr.FakeRadioX(spi)
    payload1 = payload(9, 1024)
    ok, msg = cd.write_block(radio, 1, payload1)
    check(not ok and "бракує місця" in msg and "1024" in msg and "Вилучені блоки займають 1032" in msg and "Ущільнити область" in msg,
          "U3: без хука -- пояснення з числами та вказівкою на ущільнення: %s" % msg)
    check(region_of(spi) == reg, "U3: відмова нічого не змінила")
    # читач стану: повна область -- це «блока нема», а не «області нема»
    state, _ink, _ln = si.read_image(radio)
    check(state == si.ST_ABSENT, "U3: read_image на майже повній області = ST_ABSENT, а не ST_NOREGION (%s)" % state)
    check(bm.read_melody(radio)[0] == bm.ST_ABSENT, "U3: read_melody на майже повній області = ST_ABSENT")
    # хук погоджується: ущільнення -> запис -> звірка
    asked = []
    d = tempfile.mkdtemp(prefix="r37_")
    cd.ROOM_HOOK = lambda ser, t, n: cc.ensure_room(ser, t, n, confirm=lambda text, plan: asked.append(text) or True, safety_dir=d, log=quiet)
    try:
        spi = make_spi(reg)
        radio = tcr.FakeRadioX(spi)
        ok, msg = cd.write_block(radio, 1, payload1)
        check(ok, "U3: хук погодився -- блок записано: %s" % msg)
        check(asked and "Ущільнити область зараз, а тоді записати блок?" in asked[0] and "бракує місця" in asked[0], "U3: користувачу показано причину й пропозицію")
        after = region_of(spi)
        sc = cr.parse_region(after)
        check(sc.by_type().get(1) is not None and sc.by_type()[1].payload == payload1, "U3: новий блок записано й читається")
        check(not any(cr.is_retired(b.type) for b in sc.blocks) and sc.by_type()[7].payload == payload(2, 1352), "U3: вилучені зникли, живі цілі")
        check(not radio.reset_requested, "U3: у цьому шляху рацію не перезавантажують (запис блока триває в тій самій сесії)")
        check(len(os.listdir(d)) == 1, "U3: страхова копія створена")
    finally:
        cd.ROOM_HOOK = None
    # хук відмовляє користувач
    spi = make_spi(reg)
    radio = tcr.FakeRadioX(spi)
    cd.ROOM_HOOK = lambda ser, t, n: cc.ensure_room(ser, t, n, confirm=lambda *_a: False, safety_dir=d, log=quiet)
    try:
        ok, msg = cd.write_block(radio, 1, payload1)
    finally:
        cd.ROOM_HOOK = None
    check(not ok and "відхилено" in msg and region_of(spi) == reg, "U3: користувач відмовився -- блок не записано, область не змінено: %s" % msg[-100:])
    # ущільнення не допоможе
    reg2, _e = tight_region(retired=0)
    spi = make_spi(reg2)
    radio = tcr.FakeRadioX(spi)
    cd.ROOM_HOOK = lambda ser, t, n: cc.ensure_room(ser, t, n, confirm=lambda *_a: True, safety_dir=d, log=quiet)
    try:
        ok, msg = cd.write_block(radio, 1, payload1)
    finally:
        cd.ROOM_HOOK = None
    check(not ok and "Вилучених блоків, які можна було б прибрати, нема" in msg and region_of(spi) == reg2 and radio.x_total == 0, "U3: ущільнення не допоможе -- чесна відмова без запису: %s" % msg[-120:])
    # блок, що вже є, місця не потребує навіть у повній області
    spi = make_spi(reg)
    radio = tcr.FakeRadioX(spi)
    ok, msg = cd.write_block(radio, 7, payload(2, 1352))
    check(ok, "U3: блок, що вже є, оновлюється на місці й у тісній області: %s" % msg)
    # custom_region: застосування файла налаштувань при нестачі місця -- пояснення, а не «області нема або немає місця»
    buf = bytearray(reg)
    okk, why = cr.simulate_write(buf, 1, payload1)
    check(not okk and "бракує місця" in why and "Ущільнити область" in why, "U3: simulate_write пояснює нестачу місця: %s" % why[:100])
    okk, why = cr.simulate_write(bytearray(b"\xff" * LEN), 1, payload1)
    check(not okk and why == "області OpenGD77 нема", "U3: без області повідомлення старе")


# ----------------------------------------------------------------------------------------------------------------------
#  R: повернення області зі страхової копії
# ----------------------------------------------------------------------------------------------------------------------

def test_restore_copy():
    reg, _e = build_region(sample_entries())
    plan, _w = cc.plan_compaction(reg)
    # обрив посеред запису -> область без заголовка
    spi = make_spi(reg)
    radio, res, d = run_compact(spi, die_after_x=7)
    check(not res["ok"] and not cr.parse_region(region_of(spi)).magic_ok, "R: після обриву область читається як «нема»")
    # нова «жива» рація з тим самим зіпсованим флешем
    radio2 = tcr.FakeRadioX(spi)
    out = cc.restore_safety_copy(cl.CpsLink(radio2), res["safetyCopy"], lambda *_a: True, log=quiet)
    check(out["ok"] and out["verified"], "R: повернення виконано й звірено: %s" % out["text"][:120])
    check(region_of(spi) == reg, "R: область == страхова копія (побайтово)")
    check(radio2.reset_requested, "R: рація перезавантажується")
    check(set(radio2.commits) <= set(range(0x20, 0x30)) and not radio2.cal_touched, "R: записано лише в межах області")
    # ще раз -- нічого робити
    out = cc.restore_safety_copy(cl.CpsLink(tcr.FakeRadioX(spi)), res["safetyCopy"], lambda *_a: True, log=quiet)
    check(out["nothingToDo"], "R: область уже збігається -- нічого не пишемо")
    # чужий файл
    p = os.path.join(tempfile.mkdtemp(prefix="r37_"), "x.bin")
    with open(p, "wb") as f:
        f.write(b"\x00" * 100)
    try:
        cc.restore_safety_copy(cl.CpsLink(tcr.FakeRadioX(spi)), p, lambda *_a: True, log=quiet)
        check(False, "R: файл неправильної довжини мав відхилитись")
    except cc.CompactError as e:
        check("довжина" in str(e), "R: пояснено: %s" % e)
    with open(p, "wb") as f:
        f.write(b"\xff" * LEN)
    try:
        cc.restore_safety_copy(cl.CpsLink(tcr.FakeRadioX(spi)), p, lambda *_a: True, log=quiet)
        check(False, "R: стертий образ мав відхилитись")
    except cc.CompactError as e:
        check("справної області" in str(e), "R: стертий образ відхилено: %s" % e)
    # відмова користувача
    spi3 = make_spi(b"\xff" * LEN)
    r3 = tcr.FakeRadioX(spi3)
    o = cc.restore_safety_copy(cl.CpsLink(r3), res["safetyCopy"], lambda *_a: False, log=quiet)
    check(o["cancelled"] and r3.x_total == 0, "R: відмова користувача -- нічого не записано")


# ----------------------------------------------------------------------------------------------------------------------
#  UI
# ----------------------------------------------------------------------------------------------------------------------

def test_ui():
    try:
        import tkinter as tk
        r = tk.Tk()
        r.destroy()
    except Exception as e:  # noqa: BLE001
        print("test_r37: розділ UI пропущено (нема Tk/DISPLAY: %s)" % e)
        return
    import test_r36 as t36
    from cps_ui.p_allsettings import AllSettingsPanel
    spath = os.path.join(tempfile.mkdtemp(prefix="r37_ui_"), "ui.json")
    app = t36.make_app(spath)
    try:
        check(cd.ROOM_HOOK == app._room_hook, "UI: застосунок ставить хук «не вистачає місця» в custom_data")
        app.show("allsettings")
        t36.spin(app, 0.5)
        p = app.get_panel("allsettings")
        check(isinstance(p, AllSettingsPanel) and all(hasattr(p, n) for n in ("state_btn", "compact_btn", "restore_link", "state_label", "state_warn")),
              "UI: у розділі «Усі налаштування» є блок стану й кнопки")
        check(p.compact_btn.cget("text") == "Ущільнити область", "UI: кнопка називається «Ущільнити область»")
        check("не прочитано" in p.state_label.cget("text"), "UI: до читання стан пояснює, що робити")
        reg, end = build_region(sample_entries())
        p.show_state(reg)
        txt = p.state_label.cget("text")
        check("Зайнято %d з %d" % (end, LEN) in txt and "Вилучені блоки" in txt and "Вільно %d" % (LEN - end) in txt, "UI: показано числа з області: %s" % txt[:100])
        tight, _e = tight_region()
        p.show_state(tight)
        check(p.state_warn.cget("text").startswith("УВАГА") and "орбіт" in p.state_warn.cget("text"), "UI: попередження про орбіти показано окремо")
        p.show_state(b"\xff" * LEN)
        check("нема" in p.state_label.cget("text") and p.state_warn.cget("text") == "", "UI: порожня область -- «нема», без попередження")
        # без рації кнопки неактивні, з поясненням
        p.refresh_state()
        check(str(p.compact_btn.cget("state")) == "disabled" and str(p.state_btn.cget("state")) == "disabled", "UI: без рації кнопки вимкнено")
        # робочий потік: читання стану й ущільнення через підроблену рацію
        spi = make_spi(reg)
        radio = tcr.FakeRadioX(spi)
        import cps_link as cps
        orig = cps.open_radio
        cps.open_radio = lambda *a, **k: radio
        try:
            data = p.state_worker()
            check(data == reg, "UI: state_worker читає область з рації")
            asked = []
            app.confirm_from_worker = lambda text, plan=None: asked.append(text) or True
            import cps_ui.p_allsettings as pa
            old_out = pa.output_dir
            tmp = tempfile.mkdtemp(prefix="r37_ui_")
            pa.output_dir = lambda: tmp
            try:
                res = p.compact_worker()
            finally:
                pa.output_dir = old_out
            check(res["ok"] and res["verified"] and asked and len(os.listdir(tmp)) == 1, "UI: compact_worker ущільнив область, спитав підтвердження, зберіг копію")
            check(cr.parse_region(region_of(spi)).by_type()[7].payload == dict(sample_entries())[7], "UI: блок SMS цілий")
        finally:
            cps.open_radio = orig
    finally:
        app.destroy()
    check(cd.ROOM_HOOK is None, "UI: після закриття застосунку хук знято")


def main():
    old = no_sleep()
    try:
        test_z1()
        test_z2()
        test_z3()
        test_z4()
        test_u1()
        test_u3()
        test_restore_copy()
        test_ui()
    finally:
        time.sleep = old
        cd.ROOM_HOOK = None
    if FAILS:
        print("test_r37: ПРОВАЛІВ %d" % len(FAILS))
        sys.exit(1)
    print("test_r37: усе гаразд (ущільнення області, обрив на кожному кроці, межі запису, стан і попередження, нестача місця, повернення зі страхової копії).")


if __name__ == "__main__":
    main()
