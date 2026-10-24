#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vfo_edit.py -- R-next / Y5: VFO A і VFO B кодплага (перегляд і правка). ЛОГІКА без Tk і без рації.

Де лежить VFO: EEPROM 0x7590 (VFO A) і 0x75C8 (VFO B), по 56 байтів -- той самий CodeplugChannel_t, що й канал (codeplug.c:
CODEPLUG_ADDR_VFO_A_CHANNEL + sizeof(CodeplugChannel_t) * номер). Рація читає їх з кодплага ПРИ ВМИКАННІ (settings.c:139) і записує назад з пам'яті
лише при вимкненні (batteryAndPowerManagement.c) та по команді 'C' 6 2. Тому:
  * показуємо ЗБЕРЕЖЕНЕ в кодплузі, а не те, що рація має в пам'яті просто зараз (воно може відрізнятись, доки рацію не вимкнено);
  * запис працює через звичайний cps_restore (ті ж EEPROM-адреси, що й решта кодплага; сектор калібрування не зачіпається): після нього рація
    перезавантажується командою 'C' 6 1 БЕЗ збереження пам'яті, тож завантажує VFO з кодплага.
Поля -- ті ж колонки, що й у каналу (cps_csv.CH_COLUMNS), тільки без назви, номера й прапорців зон/пропуску, які для VFO не мають сенсу. Частоти
перевіряються за апаратними діапазонами прошивки (trx.c RADIO_HARDWARE_FREQUENCY_BANDS): якщо RX чи TX поза ними, settingsVFOSanityCheck() МОВЧКИ
замінює весь VFO значеннями за замовчуванням -- тому такі значення відхиляються тут.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cps_csv as cc  # noqa: E402
import codeplug_edit as ced  # noqa: E402
import codeplug_view as cv  # noqa: E402

ADDR_VFO_A = 0x7590
VFO_SIZE = cc.CH_SIZE                 # 56
VFO_NAMES = ("VFO A", "VFO B")
SECTION = "VFO"

# trx.c: RADIO_HARDWARE_FREQUENCY_BANDS (збірка без USE_DATASHEET_RANGES і без ENABLE_SPECTRUM), одиниці 10 Гц; VHF, 220 МГц, UHF
HARDWARE_BANDS = ((12700000, 17800000), (19000000, 28200000), (38000000, 56400000))

# колонки, що показуються для VFO (порядок = порядок у формі)
VFO_COLUMNS = ("Channel Type", "Rx Frequency", "Tx Frequency", "Bandwidth (kHz)", "RX Tone", "TX Tone", "Squelch", "Colour Code", "Timeslot",
               "Contact", "TG List", "Power")
REF_COLUMNS = {"Contact": "contact", "TG List": "group"}


def vfo_addr(n):
    if n not in (0, 1):
        raise ValueError("VFO: 0 (A) або 1 (B)")
    return ADDR_VFO_A + VFO_SIZE * n


def vfo_rec(img, n):
    return img.ee(vfo_addr(n), VFO_SIZE)


def in_band(freq10hz):
    return any(lo <= freq10hz <= hi for lo, hi in HARDWARE_BANDS)


def band_text():
    return "; ".join("%s..%s МГц" % (cc.fmt_scaled(lo, 5, ","), cc.fmt_scaled(hi, 5, ",")) for lo, hi in HARDWARE_BANDS)


def vfo_values(img, n, dp):
    """{колонка: текст} для форми (неактуальні для типу -- порожній рядок) + «freq_ok»: чи обидві частоти BCD-коректні й у діапазонах."""
    rec = bytearray(vfo_rec(img, n))
    ctx = cc.make_ctx_for_export(img, dp)
    out = {}
    for name in VFO_COLUMNS:
        col = cc.CH_COLUMN_BY_NAME[name]
        out[name] = col["dec"](rec, ctx).strip("\t").strip() if cc.applies(col, rec) else ""
    rx, tx = cv.freq_bcd_le(rec[cc.O_RX:cc.O_RX + 4]), cv.freq_bcd_le(rec[cc.O_TX:cc.O_TX + 4])
    out["freq_ok"] = rx is not None and tx is not None and in_band(rx) and in_band(tx)
    return out


def vfo_refs(img, n):
    rec = vfo_rec(img, n)
    return {"Contact": rec[cc.O_CONTACT] | (rec[cc.O_CONTACT + 1] << 8), "TG List": rec[cc.O_GROUP]}


def vfo_edit(img, n, changes, dp, refs=None):
    """Змінити поля VFO n (0 -- A, 1 -- B). changes: {колонка CSV: текст} (ті самі розбір і межі, що в каналів: cps_csv.CH_COLUMNS); refs:
    {«Contact»|«TG List»: номер запису, 0 -- немає}. Повертає ImportResult; помилки -- CodeplugEditError (образ не змінюється)."""
    changes, refs = dict(changes), dict(refs or {})
    rec = bytearray(vfo_rec(img, n))
    old = bytes(rec)
    ctx = cc.make_ctx_for_export(img, dp)
    problems = []
    names = list(changes)
    if "Channel Type" in names:                          # тип першим: від нього залежить, які колонки актуальні
        names.remove("Channel Type")
        names.insert(0, "Channel Type")
    for name in names:
        if name not in VFO_COLUMNS or name in REF_COLUMNS:
            problems.append("поле «%s» для VFO не редагується" % name)
            continue
        col = cc.CH_COLUMN_BY_NAME[name]
        try:
            col["enc"](rec, str(changes[name]), ctx)
        except (ValueError, LookupError) as e:
            problems.append("%s: %s" % (name, e))
    for name, num in refs.items():
        if name not in REF_COLUMNS:
            problems.append("поле «%s» не є посиланням" % name)
            continue
        valid = set(s + 1 for s, _r in img.contacts()) if name == "Contact" else set(s + 1 for s, _r, _l in img.groups())
        if num != 0 and num not in valid:
            problems.append("%s: запису №%s нема в документі" % (name, num))
            continue
        if name == "Contact":
            struct.pack_into("<H", rec, cc.O_CONTACT, num)
        else:
            rec[cc.O_GROUP] = num
    for label, off in (("RX", cc.O_RX), ("TX", cc.O_TX)):
        f = cv.freq_bcd_le(bytes(rec[off:off + 4]))
        if f is None or not in_band(f):
            if f is None or bytes(rec[off:off + 4]) != old[off:off + 4]:
                problems.append("частота %s поза діапазонами рації (%s): прошивка при вмиканні замінила б весь VFO значеннями за замовчуванням"
                                % (label, band_text()))
    if problems:
        raise ced.CodeplugEditError(problems)
    out = cc.Image(img.eeprom, img.flash, img.base)
    res = cc.ImportResult()
    res.image = out
    if bytes(rec) != old:
        out.set_ee(vfo_addr(n), bytes(rec))
        what = [c for c in VFO_COLUMNS if (c in changes or c in refs)]
        res.changed.append((SECTION, "%s: %s" % (VFO_NAMES[n], ", ".join(what))))
    return res


def vfo_init(img, n, dp, digital=False):
    """Пустий VFO (у кодплузі 0xFF або сміття) -> типові значення: канал-шаблон cps_csv + RX = TX = 145,5 МГц (у діапазоні VHF рації). Те саме, що зробила б
    прошивка при вмиканні (settingsVFOSanityCheck: аналоговий режим, перша частота VHF), але без її вибору «за замовчуванням» наосліп."""
    rec = cc.new_channel_template(digital)
    ctx = cc.make_ctx_for_export(img, dp)
    for name in ("Rx Frequency", "Tx Frequency"):
        cc.CH_COLUMN_BY_NAME[name]["enc"](rec, "145.5", ctx)
    out = cc.Image(img.eeprom, img.flash, img.base)
    res = cc.ImportResult()
    res.image = out
    if bytes(rec) != vfo_rec(img, n):
        out.set_ee(vfo_addr(n), bytes(rec))
        res.changed.append((SECTION, "%s: заповнено типовими значеннями (%s, 145,5 МГц)" % (VFO_NAMES[n], "цифровий" if digital else "аналоговий")))
    return res
