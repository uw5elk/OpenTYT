#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""codeplug_view.py -- R25 W2: розбір вмісту кодплуга (контакти, групи RX, зони, канали) з байтів бекапу або прямого читання.

ТІЛЬКИ ЧИТАННЯ. Жодного запису в рацію. Лише стандартна бібліотека (pyserial підтягується лише через cps_link
у функції прямого читання).

ЄДИНЕ МІСЦЕ ДЕКОДУВАННЯ НАЗВ (R25 W2.3): decode_name_ex() нижче -- нею користуються і вікно перегляду
(gui_flasher.py), і скрипт cps_backup_info.py (R24 S3). Другої копії правил у проєкті нема.

КОДУВАННЯ НАЗВ (docs/codeplug-encoding.md; 16 байтів, дописка 0xFF):
  * CPS від TYT пише GBK; кирилиця -- пари 0xA7 xx (xx = A1..C1 великі, D1..F1 малі);
  * назва, набрана на самій рації (R23 Y2), -- cp1251;
  * обидва бувають у ОДНОМУ кодплузі (контакт 1 «Папуга» -- GBK, контакт 2 «ЇЖАК ҐЄІіїєґ» -- cp1251).
Правило: є пара 0xA7 + (A1..C1 | D1..F1) -> GBK; інакше, якщо є байти >= 0x80 -> cp1251; інакше ASCII.

ФІЛЬТРИ СМІТТЯ (R25 W2.2): у справжньому кодплузі сміття лежить у «порожніх» ділянках, тож
  * зони: лише перші CODEPLUG_ZONES_MAX = 68 бітів маски 0x8010 (у маски 32 байти = 256 бітів, справжні лише 68);
  * групи RX: лише ті, де довжина в таблиці 0x8D620 більша за нуль (і не більша за 32 -- стільки місць у записі).
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cps_link as cl  # noqa: E402

# позначки кодування в колонці таблиці
ENC_GBK = "GBK"
ENC_CP1251 = "cp1251"
ENC_ASCII = "ASCII"
ENC_EMPTY = "—"

CALL_TYPES = {0: "група", 1: "приват", 2: "всім"}
CHANNEL_MODES = {0: "FM", 1: "DMR"}          # codeplug.c: chMode 0 -> RADIO_MODE_ANALOG, інакше DIGITAL
RXGROUP_MAX_CONTACTS = 32                    # CodeplugRxGroup_t.contacts[32]
CP_ADDR_ZONE_FORMAT_BYTE = 0x806F            # codeplugInitChannelsPerZone(): 0..4 -> зони на 80 каналів


# =========================================================================================
#  Назви
# =========================================================================================

def name_bytes(raw):
    """Байти назви до першого 0xFF/0x00 (codeplugUtilConvertBufToString зупиняється на 0xFF)."""
    out = bytearray()
    for b in raw:
        if b in (0xFF, 0x00):
            break
        out.append(b)
    return bytes(out)


def gbk_cyrillic_pair(raw):
    """Чи є пара 0xA7 xx з діапазону кирилиці GBK (A1..C1 великі, D1..F1 малі) -- та сама вузька ознака, що в прошивці."""
    for i in range(len(raw) - 1):
        if raw[i] == 0xA7 and (0xA1 <= raw[i + 1] <= 0xC1 or 0xD1 <= raw[i + 1] <= 0xF1):
            return True
    return False


def classify_name(raw):
    """Кодування назви за правилом вище: 'GBK' / 'cp1251' / 'ASCII' / '—' (порожня)."""
    b = name_bytes(raw)
    if not b:
        return ENC_EMPTY
    if gbk_cyrillic_pair(b):
        return ENC_GBK
    if any(x >= 0x80 for x in b):
        return ENC_CP1251
    return ENC_ASCII


def decode_name_ex(raw, force=None):
    """ЄДИНА функція декодування назв. Повертає (текст Unicode, кодування).
    force -- None/'auto' (за правилом) або 'gbk'/'cp1251' (примусово; кодування в результаті тоді те, що задано)."""
    b = name_bytes(raw)
    if force in ("gbk", ENC_GBK):
        return b.decode("gbk", errors="replace"), (ENC_GBK if b else ENC_EMPTY)
    if force in ("cp1251", ENC_CP1251):
        return b.decode("cp1251", errors="replace"), (ENC_CP1251 if b else ENC_EMPTY)
    enc = classify_name(b)
    if enc == ENC_GBK:
        return b.decode("gbk", errors="replace"), enc
    return b.decode("cp1251", errors="replace"), enc      # cp1251 збігається з ASCII для < 0x80


def decode_name(raw, encoding="auto"):
    """Лише текст (сумісність із R24: cps_backup_info.decode_name)."""
    return decode_name_ex(raw, encoding)[0]


def bcd_to_int(raw4):
    """Поле BCD, байти в порядку «старший спершу» (ID контактів, DMR ID): цифри = шістнадцяткові цифри байтів."""
    v = 0
    for byte in raw4:
        v = v * 100 + (byte >> 4) * 10 + (byte & 0x0F)
    return v


def freq_bcd_le(raw4):
    """Частота каналу: u32 у little-endian, BCD (codeplug.c: bcd2int(rxFreq)) -> одиниці по 10 Гц.
    Повертає None, якщо в полі не-BCD цифри (сміття)."""
    for byte in raw4:
        if (byte >> 4) > 9 or (byte & 0x0F) > 9:
            return None
    return bcd_to_int(bytes(reversed(bytes(raw4))))


def freq_text(raw4):
    v = freq_bcd_le(raw4)
    if v is None or v == 0:
        return "—" if v == 0 else "?"
    return "%d.%05d" % (v // 100000, v % 100000)


def popcount_bytes(b):
    return sum(bin(x).count("1") for x in b)


# =========================================================================================
#  Кодплуг
# =========================================================================================

class Codeplug:
    """Доступ до адрес кодплуга всередині eeprom.bin / flash.bin (адреси -- як у codeplug.c, без FLASH_ADDRESS_OFFSET)."""

    def __init__(self, manifest, eeprom, flash):
        self.manifest = manifest
        self.eeprom = eeprom
        self.flash = flash
        self.flash_cp_start = manifest["parts"]["flash"]["codeplugStart"]

    def ee(self, addr, n):
        return self.eeprom[addr:addr + n]

    def fl(self, cp_addr, n):
        off = cp_addr - self.flash_cp_start
        if off < 0 or off + n > len(self.flash):
            raise cl.CpsError("адреса кодплуга 0x%X поза флеш-частиною бекапу" % cp_addr)
        return self.flash[off:off + n]

    # --- загальне ---
    def callsign(self, enc="auto"):
        return decode_name(self.ee(cl.CP_ADDR_USER_CALLSIGN, 8), enc)

    def dmr_id(self):
        return bcd_to_int(self.ee(cl.CP_ADDR_USER_DMRID, 4))

    # --- зони ---
    def zone_bits(self):
        """Номери бітів зон у роботі: ЛИШЕ перші CODEPLUG_ZONES_MAX (68) бітів маски (решта -- сміття, R22)."""
        mask = self.ee(cl.CP_ADDR_EX_ZONE_INUSE, 32)
        return [bit for bit in range(cl.CP_ZONES_MAX) if (mask[bit >> 3] >> (bit & 7)) & 1]

    def channels_per_zone(self):
        """Як codeplugInitChannelsPerZone(): байт 0x806F у 0..4 -> формат на 80 каналів у зоні, інакше 16."""
        return 80 if 0x00 <= self.ee(CP_ADDR_ZONE_FORMAT_BYTE, 1)[0] <= 0x04 else 16

    def zone_names(self, enc="auto"):
        return [z[1] for z in self.zones(enc)]

    def zones(self, enc="auto"):
        """[(номер біта 1.., назва, кодування, [номери каналів])] для зон у роботі."""
        n = self.channels_per_zone()
        stride = 16 + 2 * n
        out = []
        for bit in self.zone_bits():
            rec = self.ee(cl.CP_ADDR_EX_ZONE_LIST + bit * stride, stride)
            text, e = decode_name_ex(rec[:16], enc)
            chans = []
            for k in range(n):
                v = rec[16 + 2 * k] | (rec[17 + 2 * k] << 8)
                if v == 0:
                    break                       # прошивка рахує канали зони до першого нуля
                chans.append(v)
            out.append((bit + 1, text, e, chans))
        return out

    # --- канали ---
    def _channel_header(self, bank):
        if bank == 0:
            return self.ee(cl.CP_ADDR_CHANNEL_HEADER_EEPROM, 16)
        return self.fl(cl.CP_ADDR_CHANNEL_HEADER_FLASH + (bank - 1) * (16 + cl.CP_CHANNELS_PER_BANK * cl.CP_CHANNEL_SIZE), 16)

    def channel_in_use(self, number):
        """number 1..1024; біт (number-1) % 8 байта (number-1) // 8 у масці банку (codeplugAllChannelsIndexIsInUse)."""
        i = number - 1
        bank, slot = divmod(i, cl.CP_CHANNELS_PER_BANK)
        hdr = self._channel_header(bank)
        return bool((hdr[slot >> 3] >> (slot & 7)) & 1)

    def channel_record(self, number):
        i = number - 1
        bank, slot = divmod(i, cl.CP_CHANNELS_PER_BANK)
        if bank == 0:
            return self.ee(cl.CP_ADDR_CHANNEL_HEADER_EEPROM + 16 + slot * cl.CP_CHANNEL_SIZE, cl.CP_CHANNEL_SIZE)
        base = cl.CP_ADDR_CHANNEL_HEADER_FLASH + (bank - 1) * (16 + cl.CP_CHANNELS_PER_BANK * cl.CP_CHANNEL_SIZE) + 16
        return self.fl(base + slot * cl.CP_CHANNEL_SIZE, cl.CP_CHANNEL_SIZE)

    def channel_count(self):
        n = 0
        for b in range(cl.CP_CHANNELS_BANKS):
            n += popcount_bytes(self._channel_header(b))
        return n

    def channels(self, enc="auto"):
        """[(номер 1.., назва, кодування, RX МГц, TX МГц, режим)] для каналів у роботі."""
        out = []
        for number in range(1, cl.CP_CHANNELS_BANKS * cl.CP_CHANNELS_PER_BANK + 1):
            if not self.channel_in_use(number):
                continue
            rec = self.channel_record(number)
            text, e = decode_name_ex(rec[:16], enc)
            mode = CHANNEL_MODES.get(rec[24], "?")
            out.append((number, text, e, freq_text(rec[16:20]), freq_text(rec[20:24]), mode))
        return out

    # --- контакти ---
    def contacts(self, enc="auto"):
        """Список (номер 1.., назва, id, тип, сирі 16 байтів назви, кодування) для контактів у роботі (перший байт назви != 0xFF)."""
        out = []
        for i in range(cl.CP_CONTACTS_MAX):
            rec = self.fl(cl.CP_ADDR_CONTACTS + i * cl.CP_CONTACT_SIZE, cl.CP_CONTACT_SIZE)
            if rec[0] == 0xFF:
                continue
            text, e = decode_name_ex(rec[:16], enc)
            out.append((i + 1, text, bcd_to_int(rec[16:20]), rec[20], bytes(rec[:16]), e))
        return out

    # --- RX-групи ---
    def rx_groups(self, enc="auto"):
        """[(номер 1.., назва, довжина за таблицею, кодування, [номери контактів])]; ЛИШЕ групи з довжиною > 0 (і <= 32)."""
        lens = self.fl(cl.CP_ADDR_RX_GROUP_LEN, cl.CP_RXGROUPS_MAX)
        out = []
        for i in range(cl.CP_RXGROUPS_MAX):
            if 0 < lens[i] <= RXGROUP_MAX_CONTACTS:
                rec = self.fl(cl.CP_ADDR_RX_GROUP + i * cl.CP_RXGROUP_SIZE, cl.CP_RXGROUP_SIZE)
                text, e = decode_name_ex(rec[:16], enc)
                members = []
                for k in range(lens[i]):               # склад -- не довше, ніж каже таблиця довжин
                    v = rec[16 + 2 * k] | (rec[17 + 2 * k] << 8)
                    if v == 0:
                        break                   # як у codeplugRxGroupGetDataForIndex: порожні місця -- нулі
                    members.append(v)
                out.append((i + 1, text, lens[i], e, members))
        return out

    # =====================================================================================
    #  Таблиці для вікна й CSV: (колонки, рядки-списки рядків)
    # =====================================================================================

    def table_contacts(self, enc="auto"):
        cols = ["№", "Назва", "TG / ID", "Тип", "Кодування"]
        rows = [[str(n), name, str(ident), CALL_TYPES.get(ct, "тип %d" % ct), e]
                for (n, name, ident, ct, _raw, e) in self.contacts(enc)]
        return cols, rows

    def _contact_label(self, number, by_number):
        c = by_number.get(number)
        if c is None:
            return "#%d (немає)" % number
        return "%s (%d)" % (c[1], c[2])

    def table_rx_groups(self, enc="auto"):
        cols = ["№", "Назва", "Контактів", "Склад", "Кодування"]
        by_number = {c[0]: c for c in self.contacts(enc)}
        rows = [[str(n), name, str(length), "; ".join(self._contact_label(m, by_number) for m in members), e]
                for (n, name, length, e, members) in self.rx_groups(enc)]
        return cols, rows

    def table_zones(self, enc="auto"):
        cols = ["№", "Назва", "Каналів", "Канали", "Кодування"]
        chan_names = {}
        rows = []
        for (n, name, e, chans) in self.zones(enc):
            labels = []
            for ch in chans:
                if ch not in chan_names:
                    if 1 <= ch <= cl.CP_CHANNELS_BANKS * cl.CP_CHANNELS_PER_BANK and self.channel_in_use(ch):
                        chan_names[ch] = decode_name_ex(self.channel_record(ch)[:16], enc)[0]
                    else:
                        chan_names[ch] = None
                labels.append("%d %s" % (ch, chan_names[ch]) if chan_names[ch] is not None else "%d (порожній)" % ch)
            rows.append([str(n), name, str(len(chans)), "; ".join(labels), e])
        return cols, rows

    def table_channels(self, enc="auto"):
        cols = ["№", "Назва", "RX, МГц", "TX, МГц", "Режим", "Кодування"]
        rows = [[str(n), name, rx, tx, mode, e] for (n, name, e, rx, tx, mode) in self.channels(enc)]
        return cols, rows

    def tables(self, enc="auto"):
        """Усі чотири таблиці: [(ключ, заголовок, колонки, рядки)]."""
        out = []
        for key, title, fn in (("contacts", "Контакти", self.table_contacts), ("groups", "Групи RX", self.table_rx_groups),
                               ("zones", "Зони", self.table_zones), ("channels", "Канали", self.table_channels)):
            cols, rows = fn(enc)
            out.append((key, title, cols, rows))
        return out


def write_csv(path, columns, rows):
    """CSV у UTF-8 з BOM (щоб Excel на ПК не зіпсував кирилицю), роздільник «;» -- видимий вміст таблиці як є."""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(columns)
        for r in rows:
            w.writerow(r)


# =========================================================================================
#  Джерела: бекап-файл або пряме читання з рації
# =========================================================================================

def codeplug_from_backup(path_or_bytes):
    """(Codeplug, manifest) із .zip бекапу; SHA-256 перевіряє cps_link.read_backup_zip."""
    manifest, eeprom, flash = cl.read_backup_zip(path_or_bytes)
    return Codeplug(manifest, eeprom, flash), manifest


def codeplug_from_radio(link, progress=None):
    """Те саме, що читає бекап (ті самі діапазони), але без збереження файла: (Codeplug, manifest-lite).
    progress(percent, text)."""
    rng = cl.flash_backup_range()
    total = cl.EEPROM_BACKUP_LEN + rng["length"]

    def step(done_before):
        def cb(done, _t):
            if progress:
                progress(int(100.0 * (done_before + done) / total), "Читаю з рації: %d з %d КБ" % ((done_before + done) // 1024, total // 1024))
        return cb

    info = link.radio_info()
    eeprom = link.read(cl.CPS_ACCESS_EEPROM, 0, cl.EEPROM_BACKUP_LEN, step(0))
    flash = link.read(cl.CPS_ACCESS_FLASH, rng["raw_start"], rng["length"], step(cl.EEPROM_BACKUP_LEN))
    manifest = {
        "radio": dict(info),
        "parts": {
            "eeprom": {"start": 0, "length": len(eeprom)},
            "flash": {"start": rng["raw_start"], "length": len(flash), "codeplugStart": rng["codeplug_start"]},
        },
    }
    return Codeplug(manifest, eeprom, flash), manifest
