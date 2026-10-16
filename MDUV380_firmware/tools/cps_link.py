#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cps_link.py -- R24: ЧИТАННЯ з рації за CPS-протоколом прошивки (usb_com.c, cpsHandleReadCommand):
знімок екрана (CPS_ACCESS_DISPLAY_BUFFER) і бекап кодплуга (EEPROM + флеш) у один .zip.

*** У ЦЬОМУ ФАЙЛІ НЕМАЄ ЖОДНОГО ЗАПИСУ В РАЦІЮ. *** Лише запити 'R'. Відновлення з бекапу (запис 'X') -- окремий
файл tools/cps_restore.py (R25); так видно одним поглядом, який код уміє писати.

Лише стандартна бібліотека + pyserial (імпортується ліниво, тільки там, де відкривається порт), тож усю
логіку (PNG, маніфест, zip, межі) тестує tools/test_cps_link.py без рації й без pyserial.

ПРОТОКОЛ ЧИТАННЯ ('R'), як у usb_com.c:
    запит  : 'R', area, addr[4] (big-endian), len[2] (big-endian)
    відповідь: 'R', len[2], дані[len]        -- або єдиний байт '-' (відмова)
Довжину даних беремо із заголовка ВІДПОВІДІ (для CPS_ACCESS_RADIO_INFO прошивка підставляє свою). Через це
читання не чекає фіксованих пауз: стара flash_read() з aes_key_store.py просить read(n + 8) і тому кожен запит
чекає до кінця тайм-ауту порту.

ОБЛАСТІ (area):
    1  CPS_ACCESS_FLASH           сирі адреси SPI-флеша (кодплуг: FLASH_ADDRESS_OFFSET 0x20000 + адреса з codeplug.c)
    2  CPS_ACCESS_EEPROM          емульований EEPROM = SPI-флеш від 0 (MDUV380_EMULATED_EEPROM_ADDRESS_OFFSET = 0)
    6  CPS_ACCESS_DISPLAY_BUFFER  екранний буфер: 160x128 x 2 байти
    9  CPS_ACCESS_RADIO_INFO      structVersion, radioType, gitRevision, buildDateTime, flashId, features
Повна карта -- docs/cps-protocol.md.

ФОРМАТ ПІКСЕЛЯ ЕКРАННОГО БУФЕРА (виведено з коду драйвера; ПІДТВЕРДЖЕНО НА ЗАЛІЗІ 16.10.2026, крок BK1: кольори правильні):
    HX8353E_display.c зберігає кольори як PLATFORM_COLOUR_FORMAT_SWAP_BYTES(RGB888_TO_PLATFORM_COLOUR_FORMAT(x)),
    тобто uint16_t зі ПОМІНЯНИМИ байтами. На little-endian STM32 це означає, що в пам'яті (а отже й у відповіді на
    запит) ПЕРШИМ іде СТАРШИЙ байт звичайного RGB565, другим -- молодший, тобто пікселі читаються як '>H'.
    Для MDUV380 applicationMain.c завжди додає DIPLAYLCD_TYPE_RGB, тож канали -- RGB (R у старших 5 бітах), не BGR.
    Діагностичний режим (зберігає обидва порядки байтів і сирий буфер) лишено як інструмент, але для MDUV380 він
    більше не потрібен.
"""
import datetime
import hashlib
import io
import json
import os
import random
import struct
import time
import zipfile
import zlib

# --- області CPS (usb_com.c: enum CPS_ACCESS_AREA) -------------------------------------
CPS_ACCESS_FLASH = 1
CPS_ACCESS_EEPROM = 2
CPS_ACCESS_MCU_ROM = 5
CPS_ACCESS_DISPLAY_BUFFER = 6
CPS_ACCESS_WAV_BUFFER = 7
CPS_COMPRESS_AND_ACCESS_AMBE_BUFFER = 8
CPS_ACCESS_RADIO_INFO = 9
CPS_ACCESS_FLASH_SECURITY_REGISTERS = 10

RADIO_VID, RADIO_PID = 0x1FC9, 0x0094
RADIO_TYPE_MDUV380 = 6            # usb_com.c: PLATFORM_MDUV380 -> radioType = 6
CHUNK = 1024                      # той самий розмір запиту, що й у aes_key_store.flash_read (ліміт прошивки -- 1533)

# --- екран (HX8353E.h: DISPLAY_SIZE_X / DISPLAY_SIZE_Y) -------------------------------
DISPLAY_W = 160
DISPLAY_H = 128
DISPLAY_BYTES = DISPLAY_W * DISPLAY_H * 2     # 40960

# --- кодплуг (константи з codeplug.c / codeplug.h; число поруч -- звідки воно) ---------
FLASH_ADDRESS_OFFSET = 0x20000                # codeplug.h: FLASH_ADDRESS_OFFSET (128 * 1024) для MDUV380
SECTOR = 4096
EEPROM_BACKUP_LEN = 0x20000                   # весь емульований EEPROM (розмір експорту .g77)

CP_ADDR_USER_CALLSIGN = 0x00E0                # codeplug.c: CODEPLUG_ADDR_USER_CALLSIGN (8 байтів)
CP_ADDR_USER_DMRID = 0x00E8                   # codeplug.c: CODEPLUG_ADDR_USER_DMRID (4 байти BCD)
CP_ADDR_CHANNEL_HEADER_EEPROM = 0x3780        # маска «канал у роботі» банку 0 (16 байтів), далі 128 каналів (CP_ADDR_CHANNEL_EEPROM)
CP_ADDR_EX_ZONE_INUSE = 0x8010                # маска «зона в роботі» (32 байти, справжні лише перші 68 бітів -- R22 Z1.2)
CP_ADDR_EX_ZONE_LIST = 0x8030                 # список зон: name[16] + channels[16 або 80]
CP_ZONES_MAX = 68                             # codeplug.h: CODEPLUG_ZONES_MAX
CP_ADDR_CHANNEL_HEADER_FLASH = 0x7B1B0        # codeplug.c: CODEPLUG_ADDR_CHANNEL_HEADER_FLASH (= CODEPLUG_ADDR_CHANNEL_FLASH - 16)
CP_CHANNEL_SIZE = 56                          # codeplug.h: CODEPLUG_CHANNEL_DATA_STRUCT_SIZE
CP_CHANNELS_PER_BANK = 128                    # codeplug.h: CODEPLUG_CHANNELS_PER_BANK
CP_CHANNELS_BANKS = 8                         # codeplug.h: CODEPLUG_CHANNELS_BANKS_MAX (банк 0 -- в EEPROM, 1..7 -- у флеші)
CP_ADDR_CONTACTS = 0x87620                    # codeplug.c: CODEPLUG_ADDR_CONTACTS
CP_CONTACT_SIZE = 24                          # codeplug.h: CODEPLUG_CONTACT_DATA_SIZE
CP_CONTACTS_MAX = 1024                        # codeplug.h: CODEPLUG_CONTACTS_MAX
CP_ADDR_RX_GROUP_LEN = 0x8D620                # codeplug.c: CODEPLUG_ADDR_RX_GROUP_LEN (76 байтів: к-сть контактів у списку)
CP_ADDR_RX_GROUP = 0x8D6A0                    # codeplug.c: CODEPLUG_ADDR_RX_GROUP
CP_RXGROUP_SIZE = 80                          # codeplug.h: CODEPLUG_RXGROUP_DATA_STRUCT_SIZE
CP_RXGROUPS_MAX = 76                          # codeplug.h: CODEPLUG_RX_GROUPLIST_MAX


# --- R25 W3.2: «повний знімок» (необов'язково; ВІДНОВЛЕННЯ цих двох ділянок у R25 НЕ реалізовано) --------
VOICE_PROMPTS_RAW_START = 0xAF400             # voicePrompts.c: VOICE_PROMPTS_FLASH_HEADER_ADDRESS = 0x8F400 + FLASH_ADDRESS_OFFSET
VOICE_PROMPTS_RAW_END = 0xD8000               # початок бази DMR ID №2 (uiUtilities.c: DMRID_MEMORY_LOCATION_2); кінець підказок ВИВЕДЕНО, не виміряно
AES_KEYS_RAW_START = 0xD9F9C                  # stock_key_table.py: STOCK_KEY_TABLE_BASE
AES_KEYS_ENTRY_LEN = 0x64                     # stock_key_table.py: STOCK_KEY_ENTRY_LEN
AES_KEYS_ENTRIES = 16                         # keyId 0..15 (використовуються 1..15)
AES_KEYS_RAW_LEN = AES_KEYS_ENTRY_LEN * AES_KEYS_ENTRIES
FULL_SNAPSHOT_PARTS = (
    # ключ у manifest["parts"], файл у zip, початок, довжина
    ("voicePrompts", "voiceprompts.bin", VOICE_PROMPTS_RAW_START, VOICE_PROMPTS_RAW_END - VOICE_PROMPTS_RAW_START),
    ("aesKeys", "aeskeys.bin", AES_KEYS_RAW_START, AES_KEYS_RAW_LEN),
)


class CpsError(RuntimeError):
    """Помилка зв'язку з рацією (зрозуміле повідомлення -- його показує GUI)."""


class BackupInvalid(CpsError):
    """Самоперевірка бекапу не пройшла -- бекап НЕ зберігати."""


def flash_backup_range():
    """Межі флеш-частини бекапу, ОБЧИСЛЕНІ з констант codeplug.c (не вгадані).

    Флеш-кодплуг -- безперервна ділянка від заголовка першого флеш-банку каналів до кінця таблиці RX-груп:
      банки каналів 1..7 : від CODEPLUG_ADDR_CHANNEL_HEADER_FLASH, кожен 16 + 128*56 = 7184 Б (16-байтова
                           маска «в роботі» + 128 каналів), банк 0 живе в EEPROM;
      контакти           : від CODEPLUG_ADDR_CONTACTS, 1024 * 24 Б;
      довжини RX-груп    : CODEPLUG_ADDR_RX_GROUP_LEN (76 Б, у проміжку до CODEPLUG_ADDR_RX_GROUP);
      RX-групи           : від CODEPLUG_ADDR_RX_GROUP, 76 * 80 Б.
    Початок округлюється ВНИЗ, кінець ВГОРУ до межі сектора 4096 Б. Повертає словник із числами й виведенням."""
    bank_size = 16 + CP_CHANNELS_PER_BANK * CP_CHANNEL_SIZE
    channels_end = CP_ADDR_CHANNEL_HEADER_FLASH + (CP_CHANNELS_BANKS - 1) * bank_size
    contacts_end = CP_ADDR_CONTACTS + CP_CONTACTS_MAX * CP_CONTACT_SIZE
    rxgroups_end = CP_ADDR_RX_GROUP + CP_RXGROUPS_MAX * CP_RXGROUP_SIZE
    # Самоперевірка: ділянки справді стикуються так, як описано в codeplug.c
    assert channels_end == CP_ADDR_CONTACTS, "банки каналів мусять впиратися в контакти"
    assert contacts_end == CP_ADDR_RX_GROUP_LEN, "контакти мусять впиратися в таблицю довжин RX-груп"
    assert CP_ADDR_RX_GROUP_LEN + CP_RXGROUPS_MAX <= CP_ADDR_RX_GROUP, "таблиця довжин мусить вміщатися до RX-груп"
    start = (CP_ADDR_CHANNEL_HEADER_FLASH // SECTOR) * SECTOR
    end = ((rxgroups_end + SECTOR - 1) // SECTOR) * SECTOR
    return {
        "codeplug_start": start,
        "codeplug_end": end,
        "raw_start": FLASH_ADDRESS_OFFSET + start,
        "raw_end": FLASH_ADDRESS_OFFSET + end,
        "length": end - start,
        "exact_start": CP_ADDR_CHANNEL_HEADER_FLASH,
        "exact_end": rxgroups_end,
        "derivation": ("початок: CODEPLUG_ADDR_CHANNEL_HEADER_FLASH 0x%X, вниз до сектора -> 0x%X; кінець: CODEPLUG_ADDR_RX_GROUP 0x%X + %d*%d = 0x%X, "
                       "вгору до сектора -> 0x%X; сирі адреси = +FLASH_ADDRESS_OFFSET 0x%X"
                       % (CP_ADDR_CHANNEL_HEADER_FLASH, start, CP_ADDR_RX_GROUP, CP_RXGROUPS_MAX, CP_RXGROUP_SIZE, rxgroups_end, end,
                          FLASH_ADDRESS_OFFSET)),
    }


# =========================================================================================
#  Зв'язок
# =========================================================================================

def find_port():
    """Порт рації (CDC 1fc9:0094) або None. pyserial імпортується тут, а не на рівні модуля."""
    try:
        from serial.tools import list_ports
    except ImportError:
        raise CpsError("потрібен pyserial: pip install pyserial")
    for p in list_ports.comports():
        if (p.vid == RADIO_VID) and (p.pid == RADIO_PID):
            return p.device
    return None


def open_radio(port=None, timeout=1.0):
    """Відкрити порт рації. НЕ надсилає жодних команд (зокрема 'C',0, що показало б на рації екран CPS)."""
    try:
        import serial
    except ImportError:
        raise CpsError("потрібен pyserial: pip install pyserial")
    port = port or find_port()
    if not port:
        raise CpsError("рацію не знайдено у звичайному режимі (VID:PID 1fc9:0094). Увімкни її звичайним способом (НЕ в DFU) "
                       "і перевір кабель.")
    try:
        return serial.Serial(port, 115200, timeout=timeout)
    except Exception as e:  # noqa: BLE001 -- будь-яку помилку порту показуємо людською мовою
        raise CpsError("не вдалося відкрити порт %s: %s" % (port, e))


class CpsLink:
    """Читання з рації через послідовний порт (або будь-який об'єкт з reset_input_buffer/write/flush/read)."""

    def __init__(self, ser, retries=2):
        self.ser = ser
        self.retries = retries

    def _read_exact(self, n):
        buf = b""
        while len(buf) < n:
            part = self.ser.read(n - len(buf))
            if not part:
                break           # тайм-аут порту
            buf += part
        return buf

    def _request_once(self, area, address, length, exact):
        req = bytes([ord("R"), area, (address >> 24) & 0xFF, (address >> 16) & 0xFF, (address >> 8) & 0xFF, address & 0xFF,
                     (length >> 8) & 0xFF, length & 0xFF])
        self.ser.reset_input_buffer()
        self.ser.write(req)
        self.ser.flush()
        first = self._read_exact(1)
        if not first:
            raise CpsError("рація не відповіла (область %d, адреса 0x%X): тайм-аут" % (area, address))
        if first == b"-":
            raise CpsError("рація відмовила у читанні (область %d, адреса 0x%X, довжина %d)" % (area, address, length))
        if first != b"R":
            raise CpsError("несподівана відповідь рації на читання (0x%02X) -- область %d, адреса 0x%X" % (first[0], area, address))
        rest = self._read_exact(2)
        if len(rest) < 2:
            raise CpsError("неповний заголовок відповіді (область %d, адреса 0x%X)" % (area, address))
        got = (rest[0] << 8) | rest[1]
        body = self._read_exact(got)
        if len(body) < got:
            raise CpsError("рація віддала менше байтів, ніж обіцяла: %d із %d (область %d, адреса 0x%X)"
                           % (len(body), got, area, address))
        if exact and (got != length):
            raise CpsError("рація віддала %d байтів замість %d (область %d, адреса 0x%X)" % (got, length, area, address))
        return body

    def request(self, area, address, length, exact=True):
        """Один запит 'R' з повторами при тайм-ауті/неповній відповіді. Відмову ('-') не повторює."""
        last = None
        for _attempt in range(self.retries + 1):
            try:
                return self._request_once(area, address, length, exact)
            except CpsError as e:
                last = e
                if "відмовила" in str(e):
                    raise
        raise last

    def read(self, area, address, length, progress=None):
        """Прочитати `length` байтів області `area` від `address` шматками по CHUNK.
        progress(done, total) -- необов'язковий зворотний виклик."""
        out = bytearray()
        pos = 0
        while pos < length:
            n = min(CHUNK, length - pos)
            out += self.request(area, address + pos, n)
            pos += n
            if progress:
                progress(pos, length)
        return bytes(out)

    def radio_info(self):
        """CPS_ACCESS_RADIO_INFO -> словник (див. usb_com.c, radioInfo)."""
        b = self.request(CPS_ACCESS_RADIO_INFO, 0, 46, exact=False)
        if len(b) < 42:
            raise CpsError("відповідь RADIO_INFO закоротка: %d байтів" % len(b))
        struct_version, radio_type = struct.unpack_from("<II", b, 0)
        git = b[8:24].split(b"\0", 1)[0].decode("ascii", "replace")
        built = b[24:40].split(b"\0", 1)[0].decode("ascii", "replace")
        flash_id = struct.unpack_from("<I", b, 40)[0] if len(b) >= 44 else 0
        features = struct.unpack_from("<H", b, 44)[0] if len(b) >= 46 else 0
        return {"structVersion": struct_version, "radioType": radio_type, "gitRevision": git,
                "buildDateTime": built, "flashId": flash_id, "features": features}


# =========================================================================================
#  S1. Знімок екрана
# =========================================================================================

def capture_screen(link, progress=None):
    """Сирий екранний буфер: DISPLAY_BYTES байтів (160*128*2)."""
    return link.read(CPS_ACCESS_DISPLAY_BUFFER, 0, DISPLAY_BYTES, progress)


def capture_screen_stable(link, attempts=3, progress=None, log=print):
    """Екран перемальовується в тому самому буфері, який ми читаємо 40 запитами, тож знімок може вийти «рваним»
    (частина кадру ще стара або вже очищена). Тому читаємо двічі поспіль і беремо кадр, що збігся з попереднім;
    якщо за `attempts` спроб стабільного кадру нема (екран постійно змінюється) -- повертаємо останній із попередженням.
    Повертає (дані, стабільний: bool)."""
    prev = capture_screen(link, progress)
    for _ in range(max(1, attempts) - 1):
        cur = capture_screen(link, progress)
        if cur == prev:
            return cur, True
        prev = cur
    log("Увага: екран змінювався під час читання -- кадр може бути «рваним». Спробуй ще раз, коли екран не змінюється.")
    return prev, False


def rgb565_to_rgb888(raw, byteorder="big", bgr=False, width=DISPLAY_W, height=DISPLAY_H):
    """RGB565 (2 байти на піксель) -> RGB888 (3 байти). byteorder -- порядок байтів слова: 'big' (так у буфері рації, див.
    шапку файла) або 'little'. bgr=True -- канали B,R поміняні (на MDUV380 не потрібно). Розгортання каналів до 8 біт
    повторює старші біти, тож білий 0xFFFF дає рівно 255,255,255."""
    n = width * height
    if len(raw) < n * 2:
        raise CpsError("знімок неповний: %d байтів із %d" % (len(raw), n * 2))
    fmt = (">" if byteorder == "big" else "<") + ("%dH" % n)
    words = struct.unpack(fmt, bytes(raw[:n * 2]))
    out = bytearray(n * 3)
    j = 0
    for w in words:
        r5 = (w >> 11) & 0x1F
        g6 = (w >> 5) & 0x3F
        b5 = w & 0x1F
        if bgr:
            r5, b5 = b5, r5
        out[j] = (r5 << 3) | (r5 >> 2)
        out[j + 1] = (g6 << 2) | (g6 >> 4)
        out[j + 2] = (b5 << 3) | (b5 >> 2)
        j += 3
    return bytes(out)


def encode_png(width, height, rgb):
    """PNG 8 біт RGB без фільтрів, лише zlib + struct зі стандартної бібліотеки."""
    if len(rgb) != width * height * 3:
        raise ValueError("розмір даних не збігається з %dx%d" % (width, height))
    stride = width * 3
    raw = b"".join(b"\x00" + rgb[y * stride:(y + 1) * stride] for y in range(height))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def timestamp_name(prefix, ext, now=None):
    now = now or datetime.datetime.now()
    return "%s_%s%s" % (prefix, now.strftime("%Y%m%d_%H%M%S"), ext)


def unique_path(directory, name):
    """Шлях, якого ще нема: якщо файл існує -- додає _2, _3 ... перед розширенням (серія знімків не затирає себе)."""
    base, ext = os.path.splitext(name)
    path = os.path.join(directory, name)
    k = 2
    while os.path.exists(path):
        path = os.path.join(directory, "%s_%d%s" % (base, k, ext))
        k += 1
    return path


def take_screenshot(link, directory, diagnostic=False, progress=None, now=None, log=print):
    """Зняти екран і зберегти PNG у `directory`. Повертає список збережених шляхів.
    diagnostic=True -- додатково другий порядок байтів і сирий буфер .bin (порядок байтів уже підтверджено, тож зазвичай не треба)."""
    info = None
    try:
        info = link.radio_info()
    except CpsError as e:
        log("Увага: тип рації перевірити не вдалося (%s) -- читаю екран 160x128." % e)
    if info is not None and info["radioType"] != RADIO_TYPE_MDUV380:
        raise CpsError("знімок розрахований на MD-UV380/390 (radioType %d), а в цій рації radioType %d"
                       % (RADIO_TYPE_MDUV380, info["radioType"]))
    raw, _stable = capture_screen_stable(link, 3, progress, log)
    if len(raw) != DISPLAY_BYTES:
        raise CpsError("знімок неповний: %d байтів із %d" % (len(raw), DISPLAY_BYTES))
    os.makedirs(directory, exist_ok=True)
    now = now or datetime.datetime.now()
    saved = []

    def save(suffix, data, ext):
        p = unique_path(directory, timestamp_name("screenshot" + suffix, ext, now))
        with open(p, "wb") as f:
            f.write(data)
        saved.append(p)

    # Підтверджено на залізі (BK1): слова big-endian, канали RGB.
    save("", encode_png(DISPLAY_W, DISPLAY_H, rgb565_to_rgb888(raw, "big")), ".png")
    if diagnostic:
        save("_LE", encode_png(DISPLAY_W, DISPLAY_H, rgb565_to_rgb888(raw, "little")), ".png")
        save("_raw", raw, ".bin")
    return saved


# =========================================================================================
#  S2. Бекап кодплуга
# =========================================================================================

def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_part(link, area, start, length, progress=None):
    return link.read(area, start, length, progress)


def verify_random_blocks(link, area, start, data, count=3, rng=None):
    """S2.6: перечитати `count` випадкових блоків (по CHUNK, вирівняних) і звірити з буфером. Повертає список невідповідних
    адрес (порожній -- усе гаразд)."""
    rng = rng or random.SystemRandom()
    blocks = (len(data) + CHUNK - 1) // CHUNK
    picks = rng.sample(range(blocks), min(count, blocks))
    bad = []
    for b in sorted(picks):
        off = b * CHUNK
        n = min(CHUNK, len(data) - off)
        again = link.request(area, start + off, n)
        if again != data[off:off + n]:
            bad.append(start + off)
    return bad


def build_manifest(info, eeprom, flash, rng_range, started, finished, verified_blocks, now_utc=None, extras=None):
    """extras -- {ключ частини: (файл, початок, дані)} для повного знімка (W3.2); у маніфесті їх позначено
    `includes` і `restorable` (відновлюються лише eeprom та flash)."""
    now_utc = now_utc or datetime.datetime.now(datetime.timezone.utc)
    m = {
        "format": 1,
        "tool": "cps_link.py (R24/R25)",
        "createdUtc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "durationSeconds": round(finished - started, 1),
        "radio": dict(info),
        "parts": {
            "eeprom": {"file": "eeprom.bin", "area": CPS_ACCESS_EEPROM, "start": 0, "length": len(eeprom), "sha256": sha256(eeprom)},
            "flash": {"file": "flash.bin", "area": CPS_ACCESS_FLASH, "start": rng_range["raw_start"], "length": len(flash),
                      "codeplugStart": rng_range["codeplug_start"], "flashAddressOffset": FLASH_ADDRESS_OFFSET,
                      "derivation": rng_range["derivation"], "sha256": sha256(flash)},
        },
        "selfCheck": {"randomBlocksRereadPerPart": verified_blocks, "result": "ok"},
        "note": "Лише читання; у рацію нічого не записувалось. Ключі AES (SPI 0xD9F9C...) у звичайний бекап не входять.",
    }
    m["includes"] = ["eeprom", "flash"]
    m["restorable"] = ["eeprom", "flash"]
    if extras:
        for key, (fname, start, data) in extras.items():
            m["parts"][key] = {"file": fname, "area": CPS_ACCESS_FLASH, "start": start, "length": len(data), "sha256": sha256(data),
                               "restorable": False}
            m["includes"].append(key)
        m["note"] = ("Лише читання; у рацію нічого не записувалось. ПОВНИЙ ЗНІМОК: додатково голосові підказки та таблиця ключів AES "
                     "(SPI 0xD9F9C) -- містить секретні ключі, зберігай файл як секрет. Відновлення цих двох ділянок не реалізовано.")
    return m


def make_zip(eeprom, flash, manifest, extra_files=None):
    """Один .zip: eeprom.bin, flash.bin, manifest.json (+ extra_files {ім'я: байти} для повного знімка). Повертає байти."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        z.writestr("eeprom.bin", eeprom)
        z.writestr("flash.bin", flash)
        for name, data in (extra_files or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


def read_backup_zip(source):
    """Прочитати бекап (шлях або байти). Перевіряє SHA-256 і довжини за маніфестом.
    Повертає (manifest, eeprom, flash); при розбіжності -- CpsError."""
    f = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
    try:
        with zipfile.ZipFile(f) as z:
            manifest = json.loads(z.read("manifest.json").decode("utf-8"))
            eeprom = z.read("eeprom.bin")
            flash = z.read("flash.bin")
    except (zipfile.BadZipFile, KeyError, ValueError) as e:
        raise CpsError("це не бекап кодплуга або файл пошкоджено: %s" % e)
    try:
        parts = manifest["parts"]
        checks = [("eeprom", eeprom), ("flash", flash)]
        # необов'язкові частини повного знімка (W3.2): якщо вони є в маніфесті -- перевіряємо й їх
        extra_names = [(k, v["file"]) for k, v in parts.items() if k not in ("eeprom", "flash")]
        if extra_names:
            with zipfile.ZipFile(io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source) as z:
                for k, fname in extra_names:
                    checks.append((k, z.read(fname)))
        for key, data in checks:
            part = parts[key]
            if len(data) != part["length"]:
                raise CpsError("%s: довжина %d, а в маніфесті %d" % (key, len(data), part["length"]))
            if sha256(data) != part["sha256"]:
                raise CpsError("%s: SHA-256 не збігається з маніфестом -- файл пошкоджено" % key)
    except (KeyError, TypeError, zipfile.BadZipFile) as e:
        raise CpsError("маніфест бекапу неповний або пошкоджений (немає поля %s)" % e)
    return manifest, eeprom, flash


def backup_codeplug(link, progress=None, rng=None, clock=time.time, now_utc=None, log=print, full_snapshot=False):
    """Прочитати EEPROM і флеш-частину кодплуга, самоперевірити й зібрати .zip.
    full_snapshot=True (R25 W3.2) -- додатково голосові підказки і таблицю ключів AES (за замовчуванням ВИМКНЕНО).
    progress(percent, text). Повертає (zip_bytes, manifest). При невдалій самоперевірці -- BackupInvalid."""
    started = clock()
    rng_range = flash_backup_range()
    flash_len = rng_range["length"]
    extra_len = sum(p[3] for p in FULL_SNAPSHOT_PARTS) if full_snapshot else 0
    total = EEPROM_BACKUP_LEN + flash_len + extra_len
    verify_cost = 6 * CHUNK

    def step(done_before):
        def cb(done, _total):
            if progress:
                progress(int(100.0 * (done_before + done) / (total + verify_cost)),
                         "Читаю: %d з %d КБ" % ((done_before + done) // 1024, total // 1024))
        return cb

    info = link.radio_info()
    log("Рація: тип %d, прошивка %s, зібрана %s." % (info["radioType"], info["gitRevision"], info["buildDateTime"]))
    log("EEPROM: 0x0 .. 0x%X (%d КБ)." % (EEPROM_BACKUP_LEN, EEPROM_BACKUP_LEN // 1024))
    log("Флеш: сирі 0x%X .. 0x%X (%d КБ). %s" % (rng_range["raw_start"], rng_range["raw_end"], flash_len // 1024, rng_range["derivation"]))

    eeprom = read_part(link, CPS_ACCESS_EEPROM, 0, EEPROM_BACKUP_LEN, step(0))
    flash = read_part(link, CPS_ACCESS_FLASH, rng_range["raw_start"], flash_len, step(EEPROM_BACKUP_LEN))
    extras = {}
    extra_files = {}
    if full_snapshot:
        done_before = EEPROM_BACKUP_LEN + flash_len
        for key, fname, start, length in FULL_SNAPSHOT_PARTS:
            log("Повний знімок: %s -- сирі 0x%X .. 0x%X (%d Б)." % (key, start, start + length, length))
            data = read_part(link, CPS_ACCESS_FLASH, start, length, step(done_before))
            done_before += length
            extras[key] = (fname, start, data)
            extra_files[fname] = data

    if progress:
        progress(int(100.0 * total / (total + verify_cost)), "Самоперевірка: перечитую випадкові блоки...")
    rng = rng or random.SystemRandom()
    bad = verify_random_blocks(link, CPS_ACCESS_EEPROM, 0, eeprom, 3, rng)
    bad_f = verify_random_blocks(link, CPS_ACCESS_FLASH, rng_range["raw_start"], flash, 3, rng)
    bad_x = []
    for key, (_fname, start, data) in extras.items():
        bad_x += ["%s 0x%X" % (key, a) for a in verify_random_blocks(link, CPS_ACCESS_FLASH, start, data, 3, rng)]
    if bad or bad_f or bad_x:
        where = ", ".join(["EEPROM 0x%X" % a for a in bad] + ["флеш 0x%X" % a for a in bad_f] + bad_x)
        raise BackupInvalid("самоперевірка не пройшла: повторне читання блоку дало інші байти (%s). Бекап НЕ збережено. "
                            "Рація могла записувати налаштування під час читання -- спробуй ще раз, не торкаючись кнопок." % where)

    finished = clock()
    manifest = build_manifest(info, eeprom, flash, rng_range, started, finished, 3, now_utc, extras or None)
    if progress:
        progress(100, "Готово")
    return make_zip(eeprom, flash, manifest, extra_files), manifest


# =========================================================================================
#  CLI
# =========================================================================================

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="R24: знімок екрана і бекап кодплуга (лише читання).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("screenshot", help="знімок екрана рації -> PNG")
    s.add_argument("--port")
    s.add_argument("--outdir", default=".")
    s.add_argument("--diag", action="store_true", help="додатково зберегти інший порядок байтів і сирий буфер")
    b = sub.add_parser("backup", help="бекап кодплуга -> .zip")
    b.add_argument("--port")
    b.add_argument("--outdir", default=".")
    b.add_argument("--full", action="store_true", help="повний знімок: ще й голосові підказки та ключі AES (секретно!)")
    a = ap.parse_args(argv)

    ser = open_radio(a.port)
    try:
        link = CpsLink(ser)
        if a.cmd == "screenshot":
            for p in take_screenshot(link, a.outdir, diagnostic=a.diag):
                print("Збережено:", p)
        else:
            last = [-1]

            def prog(pct, text):
                if pct != last[0] and pct % 5 == 0:
                    last[0] = pct
                    print("%3d%%  %s" % (pct, text))
            data, manifest = backup_codeplug(link, prog, full_snapshot=a.full)
            os.makedirs(a.outdir, exist_ok=True)
            path = unique_path(a.outdir, timestamp_name("codeplug_backup", ".zip"))
            with open(path, "wb") as f:
                f.write(data)
            print("Збережено:", path, "(%.1f с)" % manifest["durationSeconds"])
    finally:
        ser.close()


if __name__ == "__main__":
    try:
        main()
    except CpsError as e:
        raise SystemExit("ПОМИЛКА: %s" % e)
