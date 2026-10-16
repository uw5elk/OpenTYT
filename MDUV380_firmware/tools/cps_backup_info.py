#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cps_backup_info.py -- R24 S3: друкує людською мовою зміст бекапу кодплуга (.zip з tools/cps_link.py).

ТІЛЬКИ ЧИТАЄ ФАЙЛ. До рації не торкається, pyserial не потрібен.

    python3 cps_backup_info.py codeplug_backup_20261017_120000.zip [--names 15] [--encoding auto|gbk|cp1251] [--raw]

Що друкує: прошивку з маніфесту, позивний і DMR ID, кількість зон / каналів / контактів / груп, назви перших
контактів, груп і зон. Назви в кодплузі -- 16 байтів, дописка 0xFF; CPS від TYT пише їх у GBK (кирилиця -- пари
0xA7 xx, docs/codeplug-encoding.md), а назви, набрані на самій рації, -- у cp1251. Режим `auto` вгадує так: якщо в
назві є пара 0xA7 xx з діапазону кирилиці GBK -- декодує як GBK, інакше -- як cp1251.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cps_link as cl  # noqa: E402


def _gbk_cyrillic_pair(raw):
    """Чи є в байтах пара 0xA7 xx з діапазону кирилиці GBK (A1..C1 великі, D1..F1 малі) -- та сама вузька ознака, що в прошивці."""
    for i in range(len(raw) - 1):
        if raw[i] == 0xA7 and (0xA1 <= raw[i + 1] <= 0xC1 or 0xD1 <= raw[i + 1] <= 0xF1):
            return True
    return False


def name_bytes(raw):
    """Байти назви до першого 0xFF/0x00 (codeplugUtilConvertBufToString зупиняється на 0xFF)."""
    out = bytearray()
    for b in raw:
        if b in (0xFF, 0x00):
            break
        out.append(b)
    return bytes(out)


def decode_name(raw, encoding="auto"):
    b = name_bytes(raw)
    if encoding == "gbk" or (encoding == "auto" and _gbk_cyrillic_pair(b)):
        return b.decode("gbk", errors="replace")
    return b.decode("cp1251", errors="replace")


def bcd_to_int(raw4):
    """Поле BCD як у прошивці: bcd2int(byteSwap32(LE-слово)) == десяткові цифри із шістнадцяткового запису байтів."""
    v = 0
    for byte in raw4:
        v = v * 100 + (byte >> 4) * 10 + (byte & 0x0F)
    return v


def popcount_bytes(b):
    return sum(bin(x).count("1") for x in b)


class Codeplug:
    """Зручний доступ до адрес кодплуга всередині eeprom.bin / flash.bin."""

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
        mask = self.ee(cl.CP_ADDR_EX_ZONE_INUSE, 32)
        return [bit for bit in range(cl.CP_ZONES_MAX) if (mask[bit >> 3] >> (bit & 7)) & 1]

    def channels_per_zone(self):
        """Як codeplugInitChannelsPerZone(): байт 0x806F у 0..4 -> формат на 80 каналів у зоні, інакше 16."""
        return 80 if 0x00 <= self.ee(0x806F, 1)[0] <= 0x04 else 16

    def zone_names(self, enc="auto"):
        stride = 16 + 2 * self.channels_per_zone()
        return [decode_name(self.ee(cl.CP_ADDR_EX_ZONE_LIST + bit * stride, 16), enc) for bit in self.zone_bits()]

    # --- канали ---
    def channel_count(self):
        n = popcount_bytes(self.ee(cl.CP_ADDR_CHANNEL_HEADER_EEPROM, 16))
        bank = 16 + cl.CP_CHANNELS_PER_BANK * cl.CP_CHANNEL_SIZE
        for b in range(1, cl.CP_CHANNELS_BANKS):
            n += popcount_bytes(self.fl(cl.CP_ADDR_CHANNEL_HEADER_FLASH + (b - 1) * bank, 16))
        return n

    # --- контакти ---
    def contacts(self, enc="auto"):
        """Список (номер 1.., назва, id, тип) для контактів у роботі (перший байт назви != 0xFF)."""
        out = []
        for i in range(cl.CP_CONTACTS_MAX):
            rec = self.fl(cl.CP_ADDR_CONTACTS + i * cl.CP_CONTACT_SIZE, cl.CP_CONTACT_SIZE)
            if rec[0] == 0xFF:
                continue
            out.append((i + 1, decode_name(rec[:16], enc), bcd_to_int(rec[16:20]), rec[20], bytes(rec[:16])))
        return out

    # --- RX-групи ---
    def rx_groups(self, enc="auto"):
        lens = self.fl(cl.CP_ADDR_RX_GROUP_LEN, cl.CP_RXGROUPS_MAX)
        out = []
        for i in range(cl.CP_RXGROUPS_MAX):
            if lens[i] > 0:
                rec = self.fl(cl.CP_ADDR_RX_GROUP + i * cl.CP_RXGROUP_SIZE, cl.CP_RXGROUP_SIZE)
                out.append((i + 1, decode_name(rec[:16], enc), lens[i]))
        return out


CALL_TYPES = {0: "група", 1: "приват", 2: "всім"}


def describe(manifest, eeprom, flash, names=10, enc="auto", raw=False, out=print):
    cp = Codeplug(manifest, eeprom, flash)
    r = manifest["radio"]
    out("Бекап створено: %s UTC, читання тривало %s с" % (manifest.get("createdUtc", "?"), manifest.get("durationSeconds", "?")))
    out("Рація: radioType %s, прошивка %s, зібрана %s" % (r.get("radioType"), r.get("gitRevision"), r.get("buildDateTime")))
    out("Частини: EEPROM %d Б, флеш %d Б (сирі адреси від 0x%X). SHA-256 перевірено." %
        (len(eeprom), len(flash), manifest["parts"]["flash"]["start"]))
    out("")
    out("Позивний:  %s" % (cp.callsign(enc) or "(порожньо)"))
    out("DMR ID:    %d" % cp.dmr_id())
    zones = cp.zone_names(enc)
    out("Зон:       %d (+ віртуальна «Всі канали»), формат: %d каналів у зоні" % (len(zones), cp.channels_per_zone()))
    out("Каналів:   %d" % cp.channel_count())
    contacts = cp.contacts(enc)
    by_type = {}
    for c in contacts:
        by_type[c[3]] = by_type.get(c[3], 0) + 1
    out("Контактів: %d (%s)" % (len(contacts), ", ".join("%s %d" % (CALL_TYPES.get(t, "тип %d" % t), n) for t, n in sorted(by_type.items())) or "—"))
    groups = cp.rx_groups(enc)
    out("Груп RX:   %d" % len(groups))
    if names > 0 and zones:
        out("")
        out("Перші зони:")
        for i, z in enumerate(zones[:names], 1):
            out("  %2d  %s" % (i, z))
    if names > 0 and contacts:
        out("")
        out("Перші контакти:")
        for num, name, ident, ctype, rawname in contacts[:names]:
            line = "  №%-4d %-18s %9d  %s" % (num, name, ident, CALL_TYPES.get(ctype, "тип %d" % ctype))
            if raw:
                line += "   [%s]" % name_bytes(rawname).hex()
            out(line)
    if names > 0 and groups:
        out("")
        out("Перші групи RX:")
        for num, name, n in groups[:names]:
            out("  №%-3d %-18s контактів у списку: %d" % (num, name, n))


def main(argv=None):
    ap = argparse.ArgumentParser(description="R24 S3: що лежить у бекапі кодплуга (лише читання файла).")
    ap.add_argument("zip")
    ap.add_argument("--names", type=int, default=10, help="скільки перших зон/контактів/груп показати")
    ap.add_argument("--encoding", choices=("auto", "gbk", "cp1251"), default="auto")
    ap.add_argument("--raw", action="store_true", help="поряд із назвою контакту показати її сирі байти (hex)")
    a = ap.parse_args(argv)
    try:
        manifest, eeprom, flash = cl.read_backup_zip(a.zip)
    except (OSError, cl.CpsError) as e:
        raise SystemExit("ПОМИЛКА: %s" % e)
    describe(manifest, eeprom, flash, a.names, a.encoding, a.raw)


if __name__ == "__main__":
    main()
