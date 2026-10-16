#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cps_backup_info.py -- R24 S3: друкує людською мовою зміст бекапу кодплуга (.zip з tools/cps_link.py).

ТІЛЬКИ ЧИТАЄ ФАЙЛ. До рації не торкається, pyserial не потрібен.

    python3 cps_backup_info.py codeplug_backup_20261017_120000.zip [--names 15] [--encoding auto|gbk|cp1251] [--raw]

Що друкує: прошивку з маніфесту, позивний і DMR ID, кількість зон / каналів / контактів / груп, назви перших
контактів, груп і зон. Назви в кодплузі -- 16 байтів, дописка 0xFF; CPS від TYT пише їх у GBK (кирилиця -- пари
A7 xx, docs/codeplug-encoding.md), а назви, набрані на самій рації, -- у cp1251. Режим `auto` вгадує так: якщо в
назві є пара A7 xx з діапазону кирилиці GBK -- декодує як GBK, інакше -- як cp1251.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cps_link as cl  # noqa: E402


# Усе декодування назв і розбір кодплуга -- у codeplug_view.py (R25 W2.3: одна спільна реалізація для цього скрипта й вікна перегляду).
from codeplug_view import (Codeplug, CALL_TYPES, bcd_to_int, decode_name, decode_name_ex, name_bytes,  # noqa: E402,F401
                           gbk_cyrillic_pair as _gbk_cyrillic_pair, popcount_bytes)


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
        for num, name, ident, ctype, rawname, _enc in contacts[:names]:
            line = "  №%-4d %-18s %9d  %s" % (num, name, ident, CALL_TYPES.get(ctype, "тип %d" % ctype))
            if raw:
                line += "   [%s]" % name_bytes(rawname).hex()
            out(line)
    if names > 0 and groups:
        out("")
        out("Перші групи RX:")
        for num, name, n, _enc, _members in groups[:names]:
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
