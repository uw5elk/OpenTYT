#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Хост-тести R24 (без рації, без pyserial): tools/cps_link.py і tools/cps_backup_info.py.

    python3 tools/test_cps_link.py

T1  складання PNG: відомий буфер 160x128 -> PNG -> незалежний декодер дає ті самі пікселі; порядок байтів RGB565
    звірено з формулами драйвера HX8353E_display.c / HX8353E.h (див. шапку cps_link.py);
T2  маніфест і .zip: SHA-256 і довжини, виявлення пошкодженого файла;
T3  S3-скрипт на синтетичному кодплузі: позивний, DMR ID, зони, назва в GBK («Папуга»), назва в cp1251 («Їжак»);
    плюс протокол: відмова, тайм-аут, неповна відповідь, самоперевірка бекапу, і те, що в рацію НІЧОГО не пишеться.
"""
import io
import os
import random
import struct
import sys
import tempfile
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cps_link as cl            # noqa: E402
import cps_backup_info as info   # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


# ----------------------------------------------------------------------------------------
#  Підставна «рація»: той самий формат запитів 'R', що в usb_com.c, і лише читання
# ----------------------------------------------------------------------------------------

class FakeRadio:
    """Об'єкт, схожий на serial.Serial. spi -- спільний образ SPI-флеша (EEPROM = його початок, як у прошивці)."""

    def __init__(self, spi, display=None, radio_type=6, refuse_area=None, short_by=0, silent=False, flip_after=None, display_changes=0):
        self.spi = spi
        self.display = display if display is not None else bytes(cl.DISPLAY_BYTES)
        self.radio_type = radio_type
        self.refuse_area = refuse_area
        self.short_by = short_by           # віддати на стільки байтів менше, ніж обіцяно в заголовку
        self.silent = silent               # не відповідати зовсім
        self.flip_after = flip_after       # після стількох запитів змінювати байти (імітація запису налаштувань)
        self.display_changes = display_changes   # скільки перших читань екрана «перемальовують» буфер між шматками
        self.display_reads = 0
        self.rx = bytearray()
        self.requests = []                 # усі запити (щоб довести, що писання не було)
        self.writes_seen = []              # усе, що не 'R'
        self.count = 0

    def reset_input_buffer(self):
        self.rx = bytearray()

    def flush(self):
        pass

    def write(self, data):
        data = bytes(data)
        if data[:1] != b"R":
            self.writes_seen.append(data)
            return
        area, addr, ln = data[1], struct.unpack(">I", data[2:6])[0], struct.unpack(">H", data[6:8])[0]
        self.requests.append((area, addr, ln))
        self.count += 1
        if self.silent:
            return
        if area == self.refuse_area:
            self.rx += b"-"
            return
        if area in (cl.CPS_ACCESS_FLASH, cl.CPS_ACCESS_EEPROM):
            body = bytearray(self.spi[addr:addr + ln])
            if self.flip_after is not None and self.count > self.flip_after and body:
                body[0] ^= 0xFF
        elif area == cl.CPS_ACCESS_DISPLAY_BUFFER:
            body = bytearray(self.display[addr:addr + ln])
            if addr == 0:
                self.display_reads += 1
            if self.display_reads <= self.display_changes and addr >= 20480:
                body = bytearray(bytes([0x40 + self.display_reads % 100]) * len(body))     # друга половина кадру «нова» і щоразу інша
        elif area == cl.CPS_ACCESS_RADIO_INFO:
            body = bytearray(struct.pack("<II", 3, self.radio_type) + b"abc1234".ljust(16, b"\0")
                             + b"20261017120000".ljust(16, b"\0") + struct.pack("<IH", 0xEF4018, 0x0006))
            ln = len(body)
        else:
            self.rx += b"-"
            return
        self.rx += b"R" + struct.pack(">H", len(body) - 0) + bytes(body)
        if self.short_by:
            del self.rx[len(self.rx) - self.short_by:]

    def read(self, n):
        out = bytes(self.rx[:n])
        del self.rx[:n]
        return out


# ----------------------------------------------------------------------------------------
#  Незалежний мінімальний декодер PNG (лише наш вихід: 8 біт RGB, фільтр 0)
# ----------------------------------------------------------------------------------------

def decode_png(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "немає сигнатури PNG"
    pos = 8
    idat = b""
    w = h = None
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        crc = struct.unpack(">I", data[pos + 8 + ln:pos + 12 + ln])[0]
        assert crc == (zlib.crc32(tag + body) & 0xFFFFFFFF), "CRC чанка %r" % tag
        if tag == b"IHDR":
            w, h, depth, ctype, comp, filt, inter = struct.unpack(">IIBBBBB", body)
            assert (depth, ctype, comp, filt, inter) == (8, 2, 0, 0, 0)
        elif tag == b"IDAT":
            idat += body
        pos += 12 + ln
    raw = zlib.decompress(idat)
    stride = w * 3
    rgb = bytearray()
    for y in range(h):
        row = raw[y * (stride + 1):(y + 1) * (stride + 1)]
        assert row[0] == 0, "очікувався фільтр 0"
        rgb += row[1:]
    return w, h, bytes(rgb)


def has_pillow():
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


# ----------------------------------------------------------------------------------------
#  T1
# ----------------------------------------------------------------------------------------

def firmware_pixel(rgb888):
    """Слово в пам'яті рації -- 2 байти, як лежать у screenBufData: формули HX8353E.h для RGB-панелі (MDUV380)
    + PLATFORM_COLOUR_FORMAT_SWAP_BYTES, записане як little-endian uint16."""
    x = rgb888
    v = ((x & 0xF80000) >> 8) + ((x & 0xFC00) >> 5) + ((x & 0xF8) >> 3)
    swapped = ((v & 0xFF) << 8) | ((v & 0xFF00) >> 8)
    return struct.pack("<H", swapped)


def expand(v5, bits):
    return (v5 << (8 - bits)) | (v5 >> (2 * bits - 8))


def test_png():
    # колір з драйвера -> байти -> наш декодер: має вийти той самий колір, квантований до RGB565
    samples = [0xFFFFFF, 0x000000, 0xFF0000, 0x00FF00, 0x0000FF, 0x123456, 0xC8A064, 0x804020]
    for c in samples:
        raw = firmware_pixel(c) * (cl.DISPLAY_W * cl.DISPLAY_H)
        px = cl.rgb565_to_rgb888(raw, "big")[:3]
        r, g, b = (c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF
        want = bytes([expand(r >> 3, 5), expand(g >> 2, 6), expand(b >> 3, 5)])
        check(px == want, "піксель драйвера 0x%06X: %s != %s" % (c, px.hex(), want.hex()))
        # інший порядок байтів тут дав би інший колір (крім симетричних)
    check(cl.rgb565_to_rgb888(firmware_pixel(0xFFFFFF) * (cl.DISPLAY_W * cl.DISPLAY_H), "big")[:3] == b"\xff\xff\xff", "білий = 255,255,255")
    check(cl.rgb565_to_rgb888(firmware_pixel(0x000000) * (cl.DISPLAY_W * cl.DISPLAY_H), "big")[:3] == b"\x00\x00\x00", "чорний = 0,0,0")

    # весь кадр: градієнт, PNG, читаємо назад
    rnd = random.Random(1)
    words = [rnd.randrange(0x10000) for _ in range(cl.DISPLAY_W * cl.DISPLAY_H)]
    raw = struct.pack(">%dH" % len(words), *words)
    rgb = cl.rgb565_to_rgb888(raw, "big")
    png = cl.encode_png(cl.DISPLAY_W, cl.DISPLAY_H, rgb)
    w, h, back = decode_png(png)
    check((w, h) == (160, 128), "розмір PNG %dx%d" % (w, h))
    check(back == rgb, "піксельна рівність PNG")
    for i in (0, 1, 160, 5000, 20479):
        wd = words[i]
        want = bytes([expand((wd >> 11) & 31, 5), expand((wd >> 5) & 63, 6), expand(wd & 31, 5)])
        check(rgb[i * 3:i * 3 + 3] == want, "піксель %d за формулою" % i)
    if has_pillow():
        from PIL import Image
        im = Image.open(io.BytesIO(png)).convert("RGB")
        check(im.size == (160, 128) and im.tobytes() == rgb, "Pillow читає PNG так само")
    # little-endian дає ІНШІ пікселі для довільного кадру (тест на те, що перемикач порядку реально працює)
    check(cl.rgb565_to_rgb888(raw, "little") != rgb, "порядок little відрізняється від big")
    try:
        cl.encode_png(10, 10, b"\x00" * 5)
        check(False, "encode_png мав відмовити на хибний розмір")
    except ValueError:
        pass
    try:
        cl.rgb565_to_rgb888(b"\x00" * 100, "big")
        check(False, "короткий буфер мав дати помилку")
    except cl.CpsError:
        pass


def test_screenshot_flow():
    spi = bytearray(0x100000)
    screen = firmware_pixel(0x00FF00) * (cl.DISPLAY_W * cl.DISPLAY_H)
    radio = FakeRadio(spi, display=screen)
    with tempfile.TemporaryDirectory() as d:
        import datetime
        t = datetime.datetime(2026, 10, 17, 12, 0, 0)
        a = cl.take_screenshot(cl.CpsLink(radio), d, now=t)
        b = cl.take_screenshot(cl.CpsLink(radio), d, now=t)    # той самий момент -- не затирає
        check(len(a) == 1 and len(b) == 1 and a[0] != b[0] and os.path.exists(a[0]) and os.path.exists(b[0]), "два знімки поспіль різні файли")
        w, h, rgb = decode_png(open(a[0], "rb").read())
        check(rgb[:3] == bytes([0, 0xFF, 0]) or rgb[:3] == bytes([0, 255, 0]), "зелений піксель %s" % rgb[:3].hex())
        diag = cl.take_screenshot(cl.CpsLink(radio), d, diagnostic=True, now=t)
        check(len(diag) == 3, "діагностика: PNG, PNG_LE, сирий буфер")
        check(os.path.getsize([p for p in diag if p.endswith(".bin")][0]) == cl.DISPLAY_BYTES, "сирий буфер 40960 Б")
    check(all(r[0] in (cl.CPS_ACCESS_RADIO_INFO, cl.CPS_ACCESS_DISPLAY_BUFFER) for r in radio.requests), "знімок читає лише RADIO_INFO і DISPLAY_BUFFER")
    check(radio.writes_seen == [], "знімок не надсилає жодних команд, окрім 'R' (зокрема 'C',0 -- він би показав екран CPS)")
    disp_reqs = [r for r in radio.requests if r[0] == cl.CPS_ACCESS_DISPLAY_BUFFER]
    check(len([r for r in disp_reqs[:40]]) == 40 and sum(r[2] for r in disp_reqs[:40]) == 40960, "40 запитів по 1024 Б")
    check(len(disp_reqs) % 40 == 0 and len(disp_reqs) >= 80, "кадр читається двічі для перевірки стабільності")

    # рваний кадр: перше читання перемальоване посередині -- беремо стабільний (збіг двох читань)
    torn = FakeRadio(spi, display=screen, display_changes=1)
    raw, stable = cl.capture_screen_stable(cl.CpsLink(torn), log=lambda *_: None)
    check(stable and raw == screen, "рваний кадр відкинуто, взято стабільний")
    always = FakeRadio(spi, display=screen, display_changes=99)
    msgs = []
    raw, stable = cl.capture_screen_stable(cl.CpsLink(always), attempts=3, log=msgs.append)
    check((not stable) and len(msgs) == 1, "постійно змінний екран -> попередження, не нескінченний цикл")
    check(len([q for q in always.requests if q[0] == 6]) == 3 * 40, "рівно 3 спроби по 40 запитів")

    # S1.6: рація не відповідає / віддає менше / відмовляє
    for kw, frag in ((dict(silent=True), "не відповіла"), (dict(short_by=100), "менше байтів"), (dict(refuse_area=6), "відмовила")):
        r = FakeRadio(spi, display=screen, **kw)
        with tempfile.TemporaryDirectory() as d:
            try:
                cl.take_screenshot(cl.CpsLink(r, retries=1), d, log=lambda *_: None)
                check(False, "очікувалась помилка (%s)" % frag)
            except cl.CpsError as e:
                check(frag in str(e), "повідомлення '%s' містить '%s'" % (e, frag))
            check(os.listdir(d) == [], "при збої не лишається порожнього файла (%s)" % frag)
    # чужа рація (не MDUV380) -- відмова з поясненням
    r = FakeRadio(spi, display=screen, radio_type=8)
    with tempfile.TemporaryDirectory() as d:
        try:
            cl.take_screenshot(cl.CpsLink(r), d)
            check(False, "інший radioType мав дати помилку")
        except cl.CpsError as e:
            check("radioType" in str(e), "повідомлення про radioType: %s" % e)


# ----------------------------------------------------------------------------------------
#  Синтетичний кодплуг для T2/T3
# ----------------------------------------------------------------------------------------

def bcd4(n):
    return bytes.fromhex("%08d" % n)


def pad16(b):
    return (b + b"\xff" * 16)[:16]


def make_spi():
    spi = bytearray(b"\xff" * 0x100000)
    # EEPROM-частина
    spi[cl.CP_ADDR_USER_CALLSIGN:cl.CP_ADDR_USER_CALLSIGN + 8] = b"UR5ABC" + b"\xff\xff"
    spi[cl.CP_ADDR_USER_DMRID:cl.CP_ADDR_USER_DMRID + 4] = bcd4(2504012)
    # зони: біти 0, 1, 5 (+ сміттєвий біт 70 за межею 68 -- не має рахуватись, R22 Z1.2)
    mask = bytearray(32)
    for bit in (0, 1, 5, 70):
        mask[bit >> 3] |= 1 << (bit & 7)
    spi[cl.CP_ADDR_EX_ZONE_INUSE:cl.CP_ADDR_EX_ZONE_INUSE + 32] = mask
    stride = 16 + 2 * 80
    for bit, name in ((0, "Київ".encode("cp1251")), (1, "Local"), (5, "Папуга".encode("gbk"))):
        base = cl.CP_ADDR_EX_ZONE_LIST + bit * stride
        spi[base:base + 16] = pad16(name if isinstance(name, bytes) else name.encode("ascii"))
        spi[base + 16:base + stride] = b"\x00" * (stride - 16)
    # канали: банк 0 -- 3 канали, банк 3 (флеш) -- 2
    spi[cl.CP_ADDR_CHANNEL_HEADER_EEPROM:cl.CP_ADDR_CHANNEL_HEADER_EEPROM + 16] = bytes([0x07]) + b"\x00" * 15
    bank = 16 + cl.CP_CHANNELS_PER_BANK * cl.CP_CHANNEL_SIZE
    for b in range(1, 8):
        a = cl.CP_ADDR_CHANNEL_HEADER_FLASH + (b - 1) * bank + cl.FLASH_ADDRESS_OFFSET
        spi[a:a + 16] = (bytes([0x03]) if b == 3 else b"\x00") + b"\x00" * 15
    # контакти у флеші: 0xFF = порожньо
    def contact(i, name, ident, ctype):
        a = cl.FLASH_ADDRESS_OFFSET + cl.CP_ADDR_CONTACTS + i * cl.CP_CONTACT_SIZE
        spi[a:a + 24] = pad16(name) + bcd4(ident) + bytes([ctype]) + b"\x00\x00\x00"
    contact(0, "Папуга".encode("gbk"), 2501234, 1)      # як із CPS: GBK
    contact(1, "Їжак".encode("cp1251"), 91, 0)           # набрано на рації: cp1251
    contact(2, b"LOCAL", 9, 0)
    contact(10, b"All call", 16777215, 2)
    # RX-групи
    lens = bytearray(cl.CP_RXGROUPS_MAX)
    lens[0] = 3
    lens[4] = 1
    a = cl.FLASH_ADDRESS_OFFSET + cl.CP_ADDR_RX_GROUP_LEN
    spi[a:a + cl.CP_RXGROUPS_MAX] = lens
    a = cl.FLASH_ADDRESS_OFFSET + cl.CP_ADDR_RX_GROUP
    spi[a:a + 16] = pad16(b"Ukraine")
    spi[a + 4 * 80:a + 4 * 80 + 16] = pad16("Група".encode("cp1251"))
    return spi


def test_flash_range():
    r = cl.flash_backup_range()
    check(r["codeplug_start"] == 0x7B000 and r["codeplug_end"] == 0x8F000, "межі кодплуга 0x%X..0x%X" % (r["codeplug_start"], r["codeplug_end"]))
    check(r["raw_start"] == 0x9B000 and r["raw_end"] == 0xAF000, "сирі межі")
    check(r["length"] == 0x14000 and r["length"] % cl.SECTOR == 0 and r["raw_start"] % cl.SECTOR == 0, "кратність сектору")
    check(r["exact_start"] == 0x7B1B0 and r["exact_end"] == 0x8EE60, "точні межі до округлення")
    # ключі AES (stock_key_table: 0xD9F9C...) у бекап не входять
    check(not (r["raw_start"] <= 0xD9F9C < r["raw_end"]), "таблиця ключів поза флеш-частиною")
    check(cl.EEPROM_BACKUP_LEN <= cl.FLASH_ADDRESS_OFFSET, "EEPROM не заходить на custom-data (0x20000)")


def run_backup(spi, **kw):
    radio = FakeRadio(spi, **kw)
    data, manifest = cl.backup_codeplug(cl.CpsLink(radio), rng=random.Random(7), log=lambda *_: None)
    return radio, data, manifest


def test_manifest_and_zip():
    spi = make_spi()
    seen = []
    radio = FakeRadio(spi)
    data, manifest = cl.backup_codeplug(cl.CpsLink(radio), progress=lambda p, t: seen.append(p), rng=random.Random(7), log=lambda *_: None)
    check(seen and seen[-1] == 100 and seen == sorted(seen), "індикатор поступу монотонний і доходить до 100")
    check(len(seen) > 100, "багато проміжних кроків поступу (%d)" % len(seen))
    m2, ee, fl = cl.read_backup_zip(data)
    check(ee == bytes(spi[:cl.EEPROM_BACKUP_LEN]), "eeprom.bin == перші 0x20000 байтів образу")
    check(fl == bytes(spi[0x9B000:0xAF000]), "flash.bin == 0x9B000..0xAF000")
    check(m2["parts"]["eeprom"]["sha256"] == cl.sha256(ee) and m2["parts"]["flash"]["sha256"] == cl.sha256(fl), "SHA-256 у маніфесті")
    check(m2["radio"]["radioType"] == 6 and m2["radio"]["gitRevision"] == "abc1234" and m2["radio"]["buildDateTime"] == "20261017120000", "radio у маніфесті")
    check(m2["radio"]["structVersion"] == 3, "structVersion")
    check(m2["parts"]["flash"]["start"] == 0x9B000 and m2["parts"]["flash"]["codeplugStart"] == 0x7B000, "межі флешу в маніфесті")
    check("createdUtc" in m2 and m2["selfCheck"]["result"] == "ok", "дата й результат самоперевірки")
    # лише читання
    check(radio.writes_seen == [], "жодної не-'R' команди")
    check(all(q[0] in (1, 2, 9) for q in radio.requests), "лише області FLASH/EEPROM/RADIO_INFO")
    nflash = len([q for q in radio.requests if q[0] == 1])
    neep = len([q for q in radio.requests if q[0] == 2])
    check(neep == 128 + 3 and nflash == 80 + 3, "запитів: EEPROM %d, флеш %d" % (neep, nflash))
    # те саме читання двічі -- ті самі SHA-256 (BK8 на моделі)
    _r, data2, m3 = run_backup(spi)
    check(m3["parts"]["eeprom"]["sha256"] == m2["parts"]["eeprom"]["sha256"] and m3["parts"]["flash"]["sha256"] == m2["parts"]["flash"]["sha256"], "повторний бекап дає ті самі SHA-256")
    # пошкодження: змінений байт у zip -> CpsError
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as zin, zipfile.ZipFile(buf, "w") as zout:
        for n in zin.namelist():
            b = zin.read(n)
            if n == "flash.bin":
                b = b"\x00" + b[1:]
            zout.writestr(n, b)
    try:
        cl.read_backup_zip(buf.getvalue())
        check(False, "пошкоджений flash.bin мав бути виявлений")
    except cl.CpsError as e:
        check("SHA-256" in str(e), "повідомлення про SHA-256: %s" % e)
    try:
        cl.read_backup_zip(b"not a zip")
        check(False, "не-zip мав дати помилку")
    except cl.CpsError:
        pass
    # S2.6: рація змінює дані між читаннями -> бекап недійсний і НЕ збирається
    bad_radio = FakeRadio(spi, flip_after=40)
    try:
        cl.backup_codeplug(cl.CpsLink(bad_radio), rng=random.Random(3), log=lambda *_: None)
        check(False, "розбіжність при самоперевірці мала дати BackupInvalid")
    except cl.BackupInvalid as e:
        check("НЕ збережено" in str(e), "повідомлення BackupInvalid: %s" % e)


def test_backup_info():
    spi = make_spi()
    _radio, data, _m = run_backup(spi)
    manifest, ee, fl = cl.read_backup_zip(data)
    cp = info.Codeplug(manifest, ee, fl)
    check(cp.callsign() == "UR5ABC", "позивний %r" % cp.callsign())
    check(cp.dmr_id() == 2504012, "DMR ID %r" % cp.dmr_id())
    check(cp.zone_bits() == [0, 1, 5], "біти зон %r (сміттєвий біт 70 відкинуто)" % cp.zone_bits())
    check(cp.channels_per_zone() == 80, "80 каналів у зоні")
    check(cp.zone_names() == ["Київ", "Local", "Папуга"], "назви зон %r" % cp.zone_names())
    check(cp.channel_count() == 3 + 2, "каналів %d" % cp.channel_count())
    contacts = cp.contacts()
    check([c[0] for c in contacts] == [1, 2, 3, 11], "номери контактів %r" % [c[0] for c in contacts])
    check(contacts[0][1] == "Папуга", "GBK-назва з CPS читається: %r" % contacts[0][1])
    check(contacts[1][1] == "Їжак", "cp1251-назва з рації читається: %r" % contacts[1][1])
    check(contacts[2][1] == "LOCAL" and contacts[2][2] == 9, "латинська назва")
    check(contacts[0][2] == 2501234 and contacts[3][2] == 16777215, "ID за BCD: %r" % [c[2] for c in contacts])
    check(contacts[3][3] == 2, "тип «всім»")
    groups = cp.rx_groups()
    check([(g[0], g[1], g[2]) for g in groups] == [(1, "Ukraine", 3), (5, "Група", 1)], "групи %r" % groups)
    # вихід людською мовою
    lines = []
    info.describe(manifest, ee, fl, names=5, out=lines.append)
    text = "\n".join(lines)
    for frag in ("UR5ABC", "2504012", "Зон:       3", "Каналів:   5", "Контактів: 4", "Папуга", "Їжак", "Ukraine", "SHA-256 перевірено"):
        check(frag in text, "у виводі є «%s»" % frag)
    # режими кодування
    check(info.decode_name(b"\xa7\xb1\xa7\xd1\xa7\xe1\xa7\xe5\xa7\xd4\xa7\xd1\xff\xff", "auto") == "Папуга", "auto: GBK")
    check(info.decode_name(b"\xaf\xe6\xe0\xea\xff", "auto") == "Їжак", "auto: cp1251")
    check(info.decode_name(b"\xa7\xb1\xa7\xd1\xff", "cp1251") != "Па", "явний cp1251 не декодує GBK")
    check(info.decode_name(b"\xa7\xb1\xa7\xd1\xff", "gbk") == "Па", "явний gbk")
    check(info.name_bytes(b"AB\xffCD") == b"AB", "назва обривається на 0xFF")
    check(info.bcd_to_int(bytes.fromhex("02504012")) == 2504012, "BCD")
    # CLI з файлом
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "b.zip")
        open(p, "wb").write(data)
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            info.main([p, "--names", "3", "--raw"])
        finally:
            sys.stdout = old
        check("Папуга" in buf.getvalue() and "[" in buf.getvalue(), "CLI друкує назву й сирі байти")
        try:
            info.main([os.path.join(d, "нема.zip")])
            check(False, "відсутній файл мав дати помилку")
        except SystemExit as e:
            check("ПОМИЛКА" in str(e), "помилка для відсутнього файла")


def test_protocol():
    spi = bytearray(range(256)) * 16
    r = FakeRadio(spi)
    link = cl.CpsLink(r)
    check(link.read(cl.CPS_ACCESS_EEPROM, 10, 3000) == bytes(spi[10:3010]), "читання по шматках 1024")
    check([q[2] for q in r.requests] == [1024, 1024, 952], "шматки 1024+1024+952")
    check(r.requests[0][1] == 10 and r.requests[1][1] == 1034, "адреси шматків")
    inf = link.radio_info()
    check(inf["radioType"] == 6 and inf["flashId"] == 0xEF4018 and inf["features"] == 6, "RADIO_INFO розібрано: %r" % inf)
    # повтор при короткій відповіді рахується, відмова -- ні
    r2 = FakeRadio(spi, refuse_area=2)
    try:
        cl.CpsLink(r2, retries=3).request(2, 0, 16)
    except cl.CpsError:
        pass
    check(len(r2.requests) == 1, "відмову не повторюємо (%d запитів)" % len(r2.requests))
    r3 = FakeRadio(spi, silent=True)
    try:
        cl.CpsLink(r3, retries=2).request(2, 0, 16)
    except cl.CpsError:
        pass
    check(len(r3.requests) == 3, "тайм-аут повторюємо (%d запитів)" % len(r3.requests))


def main():
    for t in (test_png, test_screenshot_flow, test_flash_range, test_manifest_and_zip, test_backup_info, test_protocol):
        try:
            t()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILS.append("%s: виняток %r" % (t.__name__, e))
    if FAILS:
        print("test_cps_link: ПРОВАЛЕНО перевірок: %d" % len(FAILS))
        return 1
    print("test_cps_link: усі перевірки пройшли (PNG, маніфест/zip, S3, протокол, лише читання).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
