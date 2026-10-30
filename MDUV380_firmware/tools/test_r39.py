#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R39: S3 «порівнювати те, що має сенс» (selfcheck.py, сценарій S3).

Рації нема: SPI підроблено (FakeRadioX з test_cps_restore, фікстури test_r38), екран рації -- підкладений буфер RGB565.

Z1  палітра: знімок із кольорів теми проходить; один піксель чужого кольору -- провал, у звіті названо колір; власна тема з рації береться за основу;
Z2  зони: смуга S-метра (до S9 і вище S9), назва каналу й тло шапки не тим кольором -- провал, хоч палітра ціла;
Z3  рендер із реальними даними кодплага: назви зони/каналу/контакту, TS, CC, потужність; поточний канал читається з налаштувань і LUCZ; не визначено --
    список для ручного вибору, перший канал НЕ підставляється;
Z4  виключені ділянки (сигнал, заряд/годинник, значки, замок AES) не впливають на результат, а такі самі зміни поза ними -- впливають;
Z5  мутації: тести ловлять зламану перевірку палітри, зон і S-метра; стабільність кадру: читання до двох однакових поспіль, рваний кадр не аналізується.
Z6  діалог ручного вибору каналу (Tk, xvfb): вибір, фільтр, скасування, виклик з робочого потоку.
Запуск: `xvfb-run -a python3.12 tools/test_r39.py`."""
import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cps_csv as cc                     # noqa: E402
import cps_link as cl                    # noqa: E402
import screen_views as sv                # noqa: E402
import selfcheck as sc                   # noqa: E402
import test_cps_restore as tcr           # noqa: E402
import test_r37 as t37                   # noqa: E402
import test_r38 as t38                   # noqa: E402
import theme_edit as te                  # noqa: E402

FAILS = t38.FAILS
check = t38.check
W, H = sc.W, sc.H

DAY = te.stock_colors("day")
IT = sv.IT


def words(display, colors=DAY):
    return sc.render_words(display, colors)


def buf(ws):
    return struct.pack(">%dH" % len(ws), *ws)


def real_selection_spi(zone_pos=0, lucz_idx=1, spi=None, all_channel=None):
    """SPI, у якому налаштування рації (магічне число + currentZone) і блок LUCZ задають поточну зону й канал."""
    spi = bytearray(spi if spi is not None else t38.make_spi())
    spi[sc.SETTINGS_EE_ADDR:sc.SETTINGS_EE_ADDR + 4] = struct.pack("<I", sc.SETTINGS_MAGIC)
    struct.pack_into("<h", spi, sc.SETTINGS_EE_ADDR + sc.SETTINGS_OFF_CURRENT_ZONE, zone_pos)
    spi[sc.LUCZ_ADDR:sc.LUCZ_ADDR + 4] = b"LUCZ"
    lucz = bytearray(sc.LUCZ_BYTES)
    if all_channel is None:
        cp, _ = t38.tc.codeplug_of(spi)
        bit = cp.zones()[zone_pos][0] - 1
        lucz[bit] = lucz_idx
    else:
        struct.pack_into("<h", lucz, sc.LUCZ_ALL_SLOT, all_channel - 1)
    spi[sc.LUCZ_ADDR + 4:sc.LUCZ_ADDR + 4 + sc.LUCZ_BYTES] = lucz
    return spi


def codeplug_of(spi):
    return t38.tc.codeplug_of(spi)[0]


def run_s3(display=None, spi=None, choose=None):
    """Прогін S3 на підробленій рації. Повертає (результат, ctx)."""
    radio, link = t38.make_radio(spi, display=display)
    ctx = t38.make_ctx(link)
    ctx.choose = choose
    with tcr.Unlocked():
        rep = sc.run(ctx, ["S3"])
    return t38.only(rep), ctx


def step(res, prefix):
    return next((s for s in res.steps if s.name.startswith(prefix)), None)


def failed(res):
    return t38.failed_names(res)


def hex_of(word):
    return te.to_hex(word)


def foreign_word(colors=DAY):
    pal = set(colors)
    for w in range(0x1234, 0x10000):
        if w not in pal:
            return w
    raise AssertionError


def paint(ws, where, word):
    ws = list(ws)
    for i in where:
        ws[i] = word
    return ws


def items_idx(display, *keys):
    want = {IT[k] for k in keys}
    return [i for i, v in enumerate(display.px) if v in want]


def rect_idx(rect):
    x1, y1, x2, y2 = rect
    return [y * W + x for y in range(y1, y2 + 1) for x in range(x1, x2 + 1)]


def state_with(**kw):
    return dict(sv.SAMPLE, **kw)


# ----------------------------------------------------------------------------------------------------------------------
#  Z1: палітра
# ----------------------------------------------------------------------------------------------------------------------

def test_z1_palette():
    base = words(sv.render("channel"))
    res, _ = run_s3(buf(base))
    pal = step(res, "палітра")
    check(res.status == sc.PASS and pal is not None and pal.ok, "Z1: знімок із кольорів теми проходить: %r" % failed(res))
    check(pal is not None and "денна" in pal.got, "Z1: у звіті названо тему: %s" % (pal.got if pal else None))
    # один піксель чужого кольору
    fw = foreign_word()
    planted = paint(base, [64 * W + 5], fw)
    res, _ = run_s3(buf(planted))
    pal = step(res, "палітра")
    check(res.status == sc.FAIL and pal is not None and not pal.ok, "Z1: один чужий піксель -- провал: %r" % failed(res))
    check(pal is not None and hex_of(fw) in pal.got and "x 5..5, y 64..64" in pal.got, "Z1: названо колір і місце чужого пікселя: %s" % (pal.got if pal else None))
    # власна тема в рації: знімок зі стандартними кольорами не проходить, зі своїми -- проходить
    custom = list(DAY)
    custom[IT["BG"]] = 0x07FF            # блакитне тло
    custom[IT["FG_CHANNEL_NAME"]] = 0xF81F
    ents = [(1, t37.payload(1, 300)), (4, te.encode_block(custom)), (5, te.encode_block(te.stock_colors("night"))),
            (6, t37.payload(6, 584)), (9, t37.payload(9, 120)), (8, t37.payload(8, 200))]
    spi = t38.make_spi(region_entries=ents)
    res, _ = run_s3(buf(words(sv.render("channel"), custom)), spi=spi)
    check(res.status == sc.PASS, "Z1: екран у кольорах теми з рації проходить: %r" % failed(res))
    res, _ = run_s3(buf(base), spi=spi)
    check(res.status == sc.FAIL and any(n.startswith("зона «") for n in failed(res)),
          "Z1: стандартні кольори на рації з власною темою -- тло не за темою (екран впізнано за формою): %r" % failed(res))
    # а ось колір, якого в палітрі теми з рації нема взагалі, -- чужий для палітри
    res, _ = run_s3(buf(paint(base, [64 * W + 5], 0x07FF)), spi=t38.make_spi(region_entries=[(1, t37.payload(1, 300)), (4, te.encode_block(DAY)),
                    (5, te.encode_block(te.stock_colors("night"))), (6, t37.payload(6, 584)), (9, t37.payload(9, 120)), (8, t37.payload(8, 200))]))
    check(res.status == sc.FAIL and not step(res, "палітра").ok and hex_of(0x07FF) in step(res, "палітра").got, "Z1: колір, якого нема в палітрі, -- чужий: %r" % failed(res))


# ----------------------------------------------------------------------------------------------------------------------
#  Z2: зони
# ----------------------------------------------------------------------------------------------------------------------

def test_z2_zones():
    st = state_with(rssi_idle=-85)
    disp = sv.render("channel", st)
    base = words(disp)
    res, _ = run_s3(buf(base))
    check(res.status == sc.PASS, "Z2: екран із сигналом -85 дБм проходить: %r" % failed(res))
    below, above = step(res, "смуга S-метра до S9"), step(res, "смуга S-метра вище S9")
    check(below is not None and above is not None and below.ok and above.ok and "-85" in below.name, "Z2: обидві частини смуги перевірено, рівень -85 прочитано з підпису")
    bg = DAY[IT["BG"]]
    # смуга до S9 намальована кольором тла
    res, _ = run_s3(buf(paint(base, items_idx(disp, "FG_RSSI_BAR"), bg)))
    check(res.status == sc.FAIL and any(n.startswith("смуга S-метра до S9") for n in failed(res)), "Z2: смуга до S9 кольором тла -- провал: %r" % failed(res))
    check(not any(n.startswith("палітра") for n in failed(res)), "Z2: при цьому палітра ціла (колір теми, але не на своєму місці)")
    # смуга вище S9
    res, _ = run_s3(buf(paint(base, items_idx(disp, "FG_RSSI_BAR_S9P"), bg)))
    check(res.status == sc.FAIL and any(n.startswith("смуга S-метра вище S9") for n in failed(res)) and not any(n.startswith("смуга S-метра до S9") for n in failed(res)),
          "Z2: смуга вище S9 кольором тла -- провал лише вище S9: %r" % failed(res))
    # смуга вище S9 кольором смуги до S9 (колір з теми, але не той)
    res, _ = run_s3(buf(paint(base, items_idx(disp, "FG_RSSI_BAR_S9P"), DAY[IT["FG_RSSI_BAR"]])))
    if DAY[IT["FG_RSSI_BAR"]] != DAY[IT["FG_RSSI_BAR_S9P"]]:
        check(res.status == sc.FAIL, "Z2: смуга вище S9 кольором смуги до S9 -- провал: %r" % failed(res))
    # назва каналу не тим кольором (колір є в палітрі)
    other = DAY[IT["FG_RSSI_BAR"]]
    name_ink = items_idx(sv.render("channel"), "FG_CHANNEL_NAME")
    wrong = paint(words(sv.render("channel")), name_ink, other)
    res, _ = run_s3(buf(wrong))
    check(res.status == sc.FAIL and any(n.startswith("зона «назва каналу»") for n in failed(res)), "Z2: назва каналу не тим кольором -- провал: %r" % failed(res))
    check(not any(n.startswith("палітра") for n in failed(res)), "Z2: палітра при цьому ціла")
    got = step(res, "зона «назва каналу»").got
    check(hex_of(other) in got, "Z2: названо колір, яким намальовано: %s" % got)
    # тло шапки не те
    hdr = rect_idx((0, 0, W - 1, 9))
    wrong = paint(words(sv.render("channel")), [i for i in hdr if sv.render("channel").px[i] == IT["BG_HEADER_TEXT"]], DAY[IT["FG_ZONE_NAME"]])
    res, _ = run_s3(buf(wrong))
    check(res.status == sc.FAIL and any(n.startswith("зона «шапка") for n in failed(res)), "Z2: тло шапки чужим кольором теми -- провал: %r" % failed(res))
    # рядок зони
    zone_ink = items_idx(sv.render("channel"), "FG_ZONE_NAME")
    res, _ = run_s3(buf(paint(words(sv.render("channel")), zone_ink, DAY[IT["FG_CHANNEL_NAME"]])))
    if DAY[IT["FG_CHANNEL_NAME"]] != DAY[IT["FG_ZONE_NAME"]]:
        check(res.status == sc.FAIL and any("нижній рядок" in n for n in failed(res)), "Z2: нижній рядок не тим кольором -- провал: %r" % failed(res))
    # екран, що не є екраном каналу: зони не перевіряються, діє палітра
    res, _ = run_s3(buf(words(sv.render("menu"))))
    check(res.status == sc.PASS and step(res, "зони екрана") is not None and not any(s.name.startswith("зона «") for s in res.steps),
          "Z2: меню замість каналу -- зони не перевіряються, але є примітка: %r" % failed(res))


# ----------------------------------------------------------------------------------------------------------------------
#  Z3: рендер із реальними даними
# ----------------------------------------------------------------------------------------------------------------------

def test_z3_real_data():
    # --- читання поточного вибору ---
    spi = real_selection_spi(zone_pos=0, lucz_idx=1)               # зона «Київ», 2-а позиція -> канал 3
    cp = codeplug_of(spi)
    sel = sc.read_current_selection(cp)
    check(sel["known"] and sel["zone_name"] == "Київ" and sel["pos_in_zone"] == 2 and sel["channel_no"] == 3 and not sel["all"], "Z3: вибір прочитано: %r" % (sel,))
    spi_all = real_selection_spi(zone_pos=3, all_channel=130)       # «Всі канали», канал 130
    sel_all = sc.read_current_selection(codeplug_of(spi_all))
    check(sel_all["known"] and sel_all["all"] and sel_all["channel_no"] == 130 and sel_all["zone_name"] == sc.ALL_CHANNELS_UA, "Z3: «Всі канали» прочитано: %r" % (sel_all,))
    # --- стан рендеру збігається з кодплагом (незалежний збір очікуваного) ---
    state, extra, _n = sc.real_state(cp, sel)
    chans = {n: (name, rx, tx, mode) for n, name, _e, rx, tx, mode in cp.channels()}
    contacts = {n: name for n, name, *_r in cp.contacts()}
    rec = cp.channel_record(3)
    check(state["zone"] == "Київ" and state["channel_no"] == 2, "Z3: зона й номер у зоні: %r %r" % (state["zone"], state["channel_no"]))
    check(state["channel"] == chans[3][0], "Z3: назва каналу з кодплага: %r / %r" % (state["channel"], chans[3][0]))
    check(state["contact"] == contacts[rec[cc.O_CONTACT]] == "Їжак", "Z3: контакт каналу з кодплага: %r" % state["contact"])
    check(state["ts"] == 1 and state["cc"] == 1 and state["mode"] == "dmr", "Z3: TS, CC, режим: %r" % ((state["ts"], state["cc"], state["mode"]),))
    check(state["rx_freq"] == 43050000 and state["tx_freq"] == 43850000 and chans[3][1] == "430.50000" and chans[3][2] == "438.50000", "Z3: частоти RX/TX з кодплага: %r %r" % (state["rx_freq"], state["tx_freq"]))
    check(any("Master" in n for n, _r in extra), "Z3: потужність «Master» -- ділянку виключено, а не вигадано: %r" % extra)
    sel1 = {"known": True, "all": False, "zone_name": "Київ", "zone_pos": 0, "pos_in_zone": 1, "channel_no": 1, "source": "тест"}
    st1, extra1, _n = sc.real_state(cp, sel1)
    check(st1["power"] == "10W" and st1["ts"] == 2 and st1["cc"] == 3 and st1["contact"] == "Папуга" and not extra1, "Z3: канал 1 -- потужність, TS2, CC3, контакт: %r %r" % (st1, extra1))
    fm = sc.real_state(cp, {"known": True, "all": False, "zone_name": "Local", "zone_pos": 1, "pos_in_zone": 1, "channel_no": 2, "source": "тест"})[0]
    check(fm["mode"] == "fm" and fm["power"] == "1W" and fm["channel"] == "PMR 1", "Z3: FM-канал -- режим fm, потужність 1W, назва: %r" % ((fm["mode"], fm["power"], fm["channel"]),))
    # --- рендер: назви в картинці = назви кодплага (інша реалізація: збираємо очікуване вручну) ---
    expect = state_with(mode="dmr", zone="Київ", channel_no=2, channel=chans[3][0], contact="Їжак", ts=1, cc=1, rx_freq=state["rx_freq"], tx_freq=state["tx_freq"])
    check(sv.render("channel", dict(state, battery_pct=99)).px == sv.render("channel", dict(expect, battery_pct=99, power=state["power"])).px,
          "Z3: рендер із реальним станом = рендер із вручну зібраним очікуваним")
    check(sv.render("channel", state).px != sv.render("channel").px, "Z3: рендер відрізняється від прикладного")
    # --- S3 на рації з вибором: знімок = рендер із реальними даними -> довідкова різниця 0 ---
    live = sv.render("channel", dict(state, battery_pct=99, rssi_idle=-101))
    res, _ = run_s3(buf(words(live)), spi=spi)
    ref = step(res, "довідково: пікселів")
    check(res.status == sc.PASS and ref is not None and ref.ok is None and ref.got.startswith("0.000 %"), "Z3: S3 із реальним каналом: 0 довідкової різниці: %r %s" % (failed(res), ref.got if ref else None))
    sel_info = step(res, "поточний канал рації")
    check(sel_info is not None and "«Київ»" in sel_info.got and "№2" in sel_info.got and "ЇЖАК" in sel_info.got.upper(), "Z3: у звіті названо зону й канал: %s" % (sel_info.got if sel_info else None))
    # інший канал на екрані (рація показує канал 1, а в налаштуваннях канал 3) -> довідкова різниця ненульова, але критерії цілі
    other = sv.render("channel", dict(st1, battery_pct=99))
    res, _ = run_s3(buf(words(other)), spi=spi)
    ref = step(res, "довідково: пікселів")
    check(res.status == sc.PASS and ref is not None and not ref.got.startswith("0.000 %"), "Z3: інший канал на екрані -- різниця довідкова, не провал: %r %s" % (failed(res), ref.got if ref else None))
    # --- не визначено: список для ручного вибору, перший канал НЕ підставляється ---
    asked = []

    def choose_none(title, text, labels):
        asked.append((title, text, list(labels)))
        return None
    res, _ = run_s3(buf(words(sv.render("channel"))), choose=choose_none)
    check(len(asked) == 1 and len(asked[0][2]) >= 10, "Z3: список для вибору запропоновано (%d рядків)" % (len(asked[0][2]) if asked else 0))
    check(asked and "Перший канал підставлено не буде" in asked[0][1] and "магічне число" in asked[0][1], "Z3: людині пояснено причину й правило")
    check(step(res, "піксельне порівняння з рендером") is not None and step(res, "довідково: пікселів") is None, "Z3: без вибору піксельне порівняння не робиться")
    check(res.status == sc.PASS, "Z3: палітра й зони працюють і без каналу: %r" % failed(res))
    check(step(res, "поточний канал рації").got == "не визначено", "Z3: у звіті сказано «не визначено»")
    # вибір вручну -> цей канал і використано (не перший у списку)
    labels_seen = []

    def choose_third(title, text, labels):
        labels_seen.extend(labels)
        return 2
    cp0 = codeplug_of(t38.make_spi())
    choices = sc.selection_choices(cp0)
    picked = choices[2][1]
    st_pick = sc.real_state(cp0, picked)[0]
    res, _ = run_s3(buf(words(sv.render("channel", dict(st_pick, battery_pct=99)))), choose=choose_third)
    ref = step(res, "довідково: пікселів")
    check(ref is not None and ref.got.startswith("0.000 %") and labels_seen == [lab for lab, _s in choices], "Z3: вручну обраний (третій) канал використано, різниця 0: %s" % (ref.got if ref else None))
    first = sc.real_state(cp0, choices[0][1])[0]
    check(first["channel"] != st_pick["channel"] or first["zone"] != st_pick["zone"] or first["channel_no"] != st_pick["channel_no"], "Z3: перший і обраний різні (перевірка осмислена)")
    # недійсні значення -> «не визначено» з причиною
    bad_spi = real_selection_spi(zone_pos=0, lucz_idx=9)
    check(not sc.read_current_selection(codeplug_of(bad_spi))["known"], "Z3: позиція поза зоною -- не визначено")
    bad2 = bytearray(real_selection_spi(zone_pos=0, lucz_idx=1))
    struct.pack_into("<h", bad2, sc.SETTINGS_EE_ADDR + sc.SETTINGS_OFF_CURRENT_ZONE, 40)
    check(not sc.read_current_selection(codeplug_of(bad2))["known"], "Z3: номер зони поза межами -- не визначено")
    bad3 = bytearray(real_selection_spi(zone_pos=0, lucz_idx=1))
    bad3[sc.LUCZ_ADDR:sc.LUCZ_ADDR + 4] = b"\xff" * 4
    check(not sc.read_current_selection(codeplug_of(bad3))["known"], "Z3: нема тегу LUCZ -- не визначено")
    # константи звіряються з прошивкою
    root = os.path.join(HERE, "..", "application")
    src = open(os.path.join(root, "source", "interfaces", "settingsStorage.c"), encoding="utf-8").read()
    check("(0x6000 + 0x4B" in src and sc.SETTINGS_EE_ADDR == 0x604B, "Z3: адреса налаштувань = STORAGE_BASE_ADDRESS у settingsStorage.c")
    st_c = open(os.path.join(root, "source", "functions", "settings.c"), encoding="utf-8").read()
    check("STORAGE_MAGIC_NUMBER          0x4780" in st_c and sc.SETTINGS_MAGIC == 0x4780, "Z3: магічне число = settings.c")
    uk = open(os.path.join(root, "include", "user_interface", "languages", "ukrainian.h"), "rb").read().decode("cp1251")
    check('.all_channels' in uk and '"%s"' % sc.ALL_CHANNELS_UA in uk, "Z3: «Всі канали» = languages/ukrainian.h")
    cpc = open(os.path.join(root, "source", "functions", "codeplug.c"), encoding="utf-8").read()
    check("lastUsedChannelInZoneData[CODEPLUG_ALL_ZONES_MAX + 1]" in cpc and sc.LUCZ_BYTES == 70, "Z3: розмір LUCZ = codeplug.c")


# ----------------------------------------------------------------------------------------------------------------------
#  Z4: виключені ділянки
# ----------------------------------------------------------------------------------------------------------------------

def test_z4_excluded():
    spi = real_selection_spi(zone_pos=0, lucz_idx=0)               # канал 1 (потужність 10W, контакт Папуга): нічого зайвого не виключено
    cp = codeplug_of(spi)
    sel = sc.read_current_selection(cp)
    state = sc.real_state(cp, sel)[0]
    base_disp = sv.render("channel", dict(state, battery_pct=99))
    base = words(base_disp)
    res, _ = run_s3(buf(base), spi=spi)
    ref0 = step(res, "довідково: пікселів")
    check(res.status == sc.PASS and ref0 is not None and ref0.got.startswith("0.000 %"), "Z4: основа -- 0 довідкової різниці: %r %s" % (failed(res), ref0.got if ref0 else None))
    # (а) інший сигнал і заряд: рендер тим самим кодом із іншими rssi/battery
    live = sv.render("channel", dict(state, battery_pct=57, rssi_idle=-70))
    res, _ = run_s3(buf(words(live)), spi=spi)
    ref = step(res, "довідково: пікселів")
    check(res.status == sc.PASS and ref is not None and ref.got.startswith("0.000 %"), "Z4: інший сигнал і заряд не впливають: %r %s" % (failed(res), ref.got if ref else None))
    # (б) шапка праворуч: годинник/значки (палітрові кольори в довільних пікселях)
    junk_hdr = [y * W + x for y in range(1, 9) for x in range(110, 155) if (x + y) % 3 == 0]
    res, _ = run_s3(buf(paint(base, junk_hdr, DAY[IT["FG_HEADER_TEXT"]])), spi=spi)
    ref = step(res, "довідково: пікселів")
    check(res.status == sc.PASS and ref.got.startswith("0.000 %"), "Z4: значки/годинник у шапці праворуч не впливають: %r %s" % (failed(res), ref.got))
    # (в) замок AES
    lock = [y * W + x for y in range(14, 23) for x in range(147, 157) if (x * y) % 2 == 0]
    res, _ = run_s3(buf(paint(base, lock, DAY[IT["FG_CHANNEL_CONTACT_INFO"]])), spi=spi)
    ref = step(res, "довідково: пікселів")
    check(res.status == sc.PASS and ref.got.startswith("0.000 %"), "Z4: замок AES не впливає: %r %s" % (failed(res), ref.got))
    # (г) такі самі зміни поза виключеними ділянками -- впливають
    inside_name = [y * W + x for y in range(74, 80) for x in range(10, 40)]
    res, _ = run_s3(buf(paint(base, inside_name, DAY[IT["FG_ZONE_NAME"]])), spi=spi)
    ref = step(res, "довідково: пікселів")
    check(ref is not None and not ref.got.startswith("0.000 %"), "Z4: зміна в назві каналу бачиться в різниці: %s" % (ref.got if ref else None))
    # (д) контрольна мутація: без виключень різниця від іншого сигналу ненульова (виключення справді працюють)
    saved = sc.EXCLUDED_ALWAYS
    try:
        sc.EXCLUDED_ALWAYS = ()
        res, _ = run_s3(buf(words(live)), spi=spi)
        ref = step(res, "довідково: пікселів")
        check(ref is not None and not ref.got.startswith("0.000 %"), "Z4: без виключень різниця від сигналу ненульова (мутація): %s" % (ref.got if ref else None))
    finally:
        sc.EXCLUDED_ALWAYS = saved
    # (е) канал із потужністю Master: рядок потужності виключено; без вибору контакту -- рядок контакту
    spi3 = real_selection_spi(zone_pos=0, lucz_idx=1)
    cp3 = codeplug_of(spi3)
    st3 = sc.real_state(cp3, sc.read_current_selection(cp3))[0]
    d3 = sv.render("channel", dict(st3, battery_pct=99, power="3W"))
    res, _ = run_s3(buf(words(d3)), spi=spi3)
    ref = step(res, "довідково: пікселів")
    check(res.status == sc.PASS and ref.got.startswith("0.000 %"), "Z4: «Master» -- інша потужність у шапці не впливає: %r %s" % (failed(res), ref.got))
    # (є) палітра в виключених ділянках все одно перевіряється
    res, _ = run_s3(buf(paint(base, junk_hdr, foreign_word())), spi=spi)
    check(res.status == sc.FAIL and any(n.startswith("палітра") for n in failed(res)), "Z4: чужий колір у виключеній ділянці -- провал палітри: %r" % failed(res))


# ----------------------------------------------------------------------------------------------------------------------
#  Z5: мутації й стабільність кадру
# ----------------------------------------------------------------------------------------------------------------------

def test_z5_mutants_and_stability():
    disp = sv.render("channel", state_with(rssi_idle=-85))
    base = words(disp)
    fw = foreign_word()
    cases = {
        "palette": (buf(paint(base, [64 * W + 5], fw)), "palette_report", lambda ws, sets: [(0, sets[0][0], sets[0][1], {})]),
        "zone": (buf(paint(words(sv.render("channel")), items_idx(sv.render("channel"), "FG_CHANNEL_NAME"), DAY[IT["FG_RSSI_BAR"]])), "zone_check",
                 lambda *a, **k: (True, "мутант", "мутант")),
        "smeter": (buf(paint(base, items_idx(disp, "FG_RSSI_BAR"), DAY[IT["BG"]])), "smeter_check", lambda ws, colors: (None, [])),
    }
    for name, (display, attr, mutant) in cases.items():
        res, _ = run_s3(display)
        check(res.status == sc.FAIL, "Z5: %s -- справжня перевірка ловить підкладений дефект: %r" % (name, failed(res)))
        old = getattr(sc, attr)
        setattr(sc, attr, mutant)
        try:
            res, _ = run_s3(display)
            check(res.status == sc.PASS, "Z5: %s -- зламана перевірка дефекту не бачить (тест чутливий): %r" % (name, failed(res)))
        finally:
            setattr(sc, attr, old)
    # стабільність: читання до двох однакових поспіль, число читань у звіті
    class Flaky:
        def __init__(self, frames):
            self.frames = list(frames)
            self.n = 0

        def read(self, *_a, **_k):
            f = self.frames[min(self.n, len(self.frames) - 1)]
            self.n += 1
            return f
    a, b, c = (bytes([i]) * (W * H * 2) for i in (1, 2, 3))
    orig = cl.capture_screen
    try:
        seq = [a, b, c, c]
        it = iter(seq)
        cl.capture_screen = lambda link, progress=None: next(it)
        raw, stable, reads = sc.capture_stable(None, log=t38.quiet)
        check(stable and reads == 4 and raw == c, "Z5: чотири читання, стабільний на четвертому: %r %r" % (stable, reads))
        it = iter([a, a])
        raw, stable, reads = sc.capture_stable(None, log=t38.quiet)
        check(stable and reads == 2, "Z5: два однакові поспіль -- 2 читання")
        cnt = [0]

        def always_new(link, progress=None):
            cnt[0] += 1
            return bytes([cnt[0] % 256]) * (W * H * 2)
        cl.capture_screen = always_new
        raw, stable, reads = sc.capture_stable(None, max_reads=5, log=t38.quiet)
        check(not stable and reads == 5 and cnt[0] == 5, "Z5: постійно новий кадр -- 5 читань, нестабільний: %r %r" % (stable, reads))
    finally:
        cl.capture_screen = orig
    # у сценарії: рваний кадр не аналізується, провал один -- про кадр
    cnt = [0]
    base_raw = buf(base)
    try:
        def torn(link, progress=None):
            cnt[0] += 1
            return bytes(base_raw[:-2]) + struct.pack(">H", cnt[0])
        cl.capture_screen = torn
        res, _ = run_s3()
        check(res.status == sc.FAIL and failed(res) == ["кадр стабільний (два читання поспіль збіглися)"] and step(res, "палітра") is None, "Z5: рваний кадр -- один провал, далі не аналізується: %r" % failed(res))
    finally:
        cl.capture_screen = orig
    # у звіті на справній рації: потрібно читань
    res, _ = run_s3(buf(base))
    st = step(res, "кадр стабільний")
    check(st is not None and "потрібно читань: 2" in st.got, "Z5: у звіті число читань: %s" % (st.got if st else None))
    # довільного порога нема
    check(not hasattr(sc, "UNEXPLAINED_MAX_PCT") and not hasattr(sc, "STATE_ITEMS"), "Z5: довільного порога 1 %% у коді нема")


# ----------------------------------------------------------------------------------------------------------------------
#  Z6: діалог ручного вибору каналу (Tk)
# ----------------------------------------------------------------------------------------------------------------------

def _find(widget, cls, acc=None):
    acc = [] if acc is None else acc
    for w in widget.winfo_children():
        if w.winfo_class() == cls:
            acc.append(w)
        _find(w, cls, acc)
    return acc


def test_z6_choose_dialog():
    try:
        import tkinter as tk
        r = tk.Tk()
        r.destroy()
    except Exception as e:  # noqa: BLE001
        print("test_r39: розділ UI пропущено (нема Tk/DISPLAY: %s)" % e)
        return
    import tempfile
    import threading
    import gui_dialogs as gd
    import test_r36 as t36
    import cps_ui.p_selfcheck as psc
    app = t36.make_app(os.path.join(tempfile.mkdtemp(prefix="r39_ui_"), "ui.json"))
    try:
        labels = ["Київ · №1 в зоні · Папуга (канал 1)", "Local · №1 в зоні · PMR 1 (канал 2)", "Всі канали · ЇЖАК (канал 3)"]

        def top():
            return [w for w in app.winfo_children() if w.winfo_class() == "Toplevel"][-1]

        def pick(index, via_filter=None):
            def act():
                win = top()
                if via_filter is not None:
                    ent = _find(win, "TEntry")[0]
                    ent.insert(0, via_filter)
                    app.update()
                lb = _find(win, "Listbox")[0]
                lb.selection_clear(0, "end")
                lb.selection_set(index)
                lb.event_generate("<<ListboxSelect>>")
                app.update()
                btn = [b for b in _find(win, "TButton") if b.cget("text") == "Обрати"][0]
                check(str(btn.cget("state")) == "normal", "Z6: «Обрати» доступна після вибору")
                btn.invoke()
            return act

        app.after(300, pick(1))
        got = gd.list_choice_dialog(app, "Тест", "Оберіть", labels)
        check(got == 1, "Z6: вибраний другий рядок -> індекс 1: %r" % (got,))
        app.after(300, pick(0, via_filter="ЇЖАК"))
        got = gd.list_choice_dialog(app, "Тест", "Оберіть", labels)
        check(got == 2, "Z6: після фільтра «ЇЖАК» перший видимий рядок -- індекс 2 у повному списку: %r" % (got,))

        def cancel():
            win = top()
            btn = [b for b in _find(win, "TButton") if b.cget("text") == "Обрати"][0]
            check(str(btn.cget("state")) == "disabled", "Z6: без вибору «Обрати» неактивна (перший рядок не підставляється)")
            [b for b in _find(win, "TButton") if b.cget("text") == "Не обирати"][0].invoke()
        app.after(300, cancel)
        got = gd.list_choice_dialog(app, "Тест", "Оберіть", labels)
        check(got is None, "Z6: «Не обирати» -> None: %r" % (got,))
        # з робочого потоку
        out = []
        th = threading.Thread(target=lambda: out.append(app.choose_from_worker("Т", "т", labels)))
        th.start()
        app.after(500, pick(2))
        t36.spin(app, 2.0)
        th.join(5)
        check(out == [2], "Z6: choose_from_worker з потоку повертає індекс: %r" % (out,))
        # панель підставляє діалог у контекст сценарію
        app.show("selfcheck")
        t36.spin(app, 0.4)
        p = app.get_panel("selfcheck")
        ctx = p._make_ctx(None)
        check(ctx.choose == app.choose_from_worker, "Z6: панель передає сценарієві вибір зі списку")
    finally:
        app.destroy()


def main():
    old = t38.no_sleep()
    try:
        test_z1_palette()
        test_z2_zones()
        test_z3_real_data()
        test_z4_excluded()
        test_z5_mutants_and_stability()
        test_z6_choose_dialog()
    finally:
        time.sleep = old
    if FAILS:
        print("\nПРОВАЛІВ: %d" % len(FAILS))
        sys.exit(1)
    print("test_r39: усе гаразд")


if __name__ == "__main__":
    main()
