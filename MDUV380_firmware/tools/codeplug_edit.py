#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""codeplug_edit.py -- CPS-doc (етап 2): правка «Основної інформації» та APRS-слотів на ОБРАЗІ кодплага. ЛОГІКА без Tk і без рації.

Усі функції беруть cps_csv.Image і повертають cps_csv.ImportResult з НОВИМ образом (вихідний не змінюється) -- так само, як
contact_edit.apply_ops, aprs_beacon_cfg.apply_callsign та імпорт CSV. Документ (tools/cps_ui/document.py) накладає результат на свій
образ; у рацію нічого тут не пишеться (запис -- окрема дія документа через cps_restore).

Формати й довжини полів НЕ змінено: APRS-слот -- ті самі 64 байти CodeplugAPRSConfig_t (кодування полів -- ті самі функції cps_csv,
що й в імпорті CSV: cps_csv._aprs_encode_field), ім'я рації / позивний APRS -- EEPROM 0x00E0 (8 Б, дописка 0xFF), мій DMR ID -- EEPROM 0x00E8 (4 Б BCD),
рядки Talker Alias -- EEPROM 0x7540 і 0x7550 (по 16 Б, дописка 0xFF; CODEPLUG_ADDR_BOOT_LINE1/2).

ГІПОТЕЗА (не перевірено на залізі): рядки Talker Alias кодуються як назви каналів (GBK, якщо всі літери є в GB2312, інакше cp1251) --
саме так їх читає наш переглядач; чи покаже екран при вмиканні рації кирилицю -- залежить від шрифту прошивки.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cps_link as cl  # noqa: E402
import cps_csv as cc  # noqa: E402
import codeplug_view as cv  # noqa: E402
import aprs_beacon_cfg as ab  # noqa: E402

ADDR_BOOT_INTRO = 0x7518          # CODEPLUG_ADDR_BOOT_INTRO_SCREEN: 1 = текст, 0 = картинка
ADDR_BOOT_LINE1 = 0x7540          # CODEPLUG_ADDR_BOOT_LINE1 (16 Б)
ADDR_BOOT_LINE2 = 0x7550          # CODEPLUG_ADDR_BOOT_LINE2 (16 Б)
BOOT_LINE_LEN = 16
DMR_ID_MAX = 16777215

APRS_NAME_LEN = 8
APRS_FLAG_300 = 0x01
APRS_FLAG_POSITION = 0x02
APRS_FLAG_QSY = 0x04
APRS_FLAG_SILENT = 0x08          # CODEPLUG_APRS_CONFIG_FLAG_BEACONING_SILENTLY

# Ключ форми -> індекс поля за cps_csv.APRS_FIELDS (для кодування). Прапорці й назва обробляються окремо.
_APRS_TEXT_FIELDS = (("ssid", 1, "SSID"), ("via1", 2, "Via1"), ("via1_ssid", 3, "Via1 SSID"), ("via2", 4, "Via2"), ("via2_ssid", 5, "Via2 SSID"),
                     ("icon_table", 6, "Icon table"), ("icon", 7, "Icon"), ("comment", 8, "Comment"), ("ambiguity", 9, "Ambiguity"),
                     ("lat", 11, "Latitude"), ("lon", 12, "Longitude"), ("tx_freq", 13, "TX Frequency"))
_APRS_FLAG_FIELDS = (("use_position", 10, "Use position"), ("qsy", 14, "Transmit QSY"), ("baud300", 15, "300 бод"))

APRS_LABELS = {"name": "назва", "ssid": "SSID", "via1": "Via1", "via1_ssid": "Via1 SSID", "via2": "Via2", "via2_ssid": "Via2 SSID",
               "icon_table": "таблиця символів", "icon": "символ", "comment": "коментар", "ambiguity": "неточність", "use_position": "позиція",
               "lat": "широта", "lon": "довгота", "tx_freq": "частота TX", "qsy": "QSY", "baud300": "300 бод", "silent": "без звуку"}


class CodeplugEditError(cl.CpsError):
    """Правку відхилено: образ не змінено. Усі проблеми -- одним списком у тексті."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("Зміну відхилено. Нічого не змінено.\n" + "\n".join("  - " + p for p in self.problems))


def _copy(img):
    return cc.Image(img.eeprom, img.flash, img.base)


# =========================================================================================
#  Основна інформація: позивний, DMR ID, рядки вітання
# =========================================================================================

def basic_values(img):
    """Поточні значення для форми: {callsign, dmr_id, line1, line2, intro_text}."""
    return {
        "callsign": ab.callsign_decode(img.ee(cl.CP_ADDR_USER_CALLSIGN, 8)),
        "dmr_id": cv.bcd_to_int(img.ee(cl.CP_ADDR_USER_DMRID, 4)),
        "line1": cv.decode_name_ex(img.ee(ADDR_BOOT_LINE1, BOOT_LINE_LEN))[0],
        "line2": cv.decode_name_ex(img.ee(ADDR_BOOT_LINE2, BOOT_LINE_LEN))[0],
        "intro_text": img.ee(ADDR_BOOT_INTRO, 1)[0] != 0,       # uiSplashScreen.c: bootScreenType == 0 -- картинка, будь-що інше -- текст
        "intro_raw": img.ee(ADDR_BOOT_INTRO, 1)[0],
    }


def check_line(text):
    """Перевірка рядка вітання: {ok, raw, nbytes, message}. Порожній рядок допустимий (на екрані нічого не буде)."""
    out = {"ok": False, "raw": b"", "nbytes": 0, "message": ""}
    text = text or ""
    if not text:
        out.update(ok=True, message="порожньо")
        return out
    try:
        raw, enc = cc.encode_new_name(text)
    except ValueError as e:
        out["message"] = str(e)
        return out
    out.update(raw=raw, nbytes=len(raw))
    if len(raw) > BOOT_LINE_LEN:
        out["message"] = "на %d байт(ів) довше за ліміт %d (кодування %s)" % (len(raw) - BOOT_LINE_LEN, BOOT_LINE_LEN, enc)
        return out
    tail = cv.name_tail_problem(raw, BOOT_LINE_LEN)
    back = cv.decode_name_ex(cv.pad_name(raw, BOOT_LINE_LEN))[0]          # R34: так, як лежатиме в кодплазі (з хвостом)
    if tail or back != text:
        out["message"] = tail or ("після запису читалась би як «%s» -- змініть літери" % back)
        return out
    out.update(ok=True, message="кодування %s, залишилось %d байт(ів)" % (enc, BOOT_LINE_LEN - len(raw)))
    return out


def apply_basic_info(base_img, callsign=None, dmr_id=None, line1=None, line2=None, intro_text=None):
    """Накласти на образ нові значення (None -- поле не чіпати; значення, що збігається з наявним, байтів не змінює).
    intro_text: True -- екран вітання текстом (байт 0x7518 = 1), False -- картинкою (0). Якщо в байті вже будь-яке ненульове значення
    (прошивка читає його як «текст»), а просять «текст», байт не чіпається."""
    img = _copy(base_img)
    res = cc.ImportResult()
    problems = []
    cur = basic_values(img)
    if callsign is not None and callsign.strip().upper() != cur["callsign"]:
        try:
            new = ab.callsign_encode(callsign)
            img.set_ee(cl.CP_ADDR_USER_CALLSIGN, new)
            res.changed.append(("Основна інформація", "позивний: %s -> %s" % (cur["callsign"] or "(порожньо)", ab.callsign_decode(new))))
        except ab.AprsCfgError as e:
            problems.append("позивний: %s" % e)
    if dmr_id is not None and dmr_id != cur["dmr_id"]:
        if not isinstance(dmr_id, int) or not 1 <= dmr_id <= DMR_ID_MAX:
            problems.append("DMR ID: ціле число 1..%d" % DMR_ID_MAX)
        else:
            img.set_ee(cl.CP_ADDR_USER_DMRID, bytes.fromhex("%08d" % dmr_id))
            res.changed.append(("Основна інформація", "DMR ID: %d -> %d" % (cur["dmr_id"], dmr_id)))
    if intro_text is not None and bool(intro_text) != cur["intro_text"]:
        img.set_ee(ADDR_BOOT_INTRO, bytes([1 if intro_text else 0]))
        res.changed.append(("Основна інформація", "екран при вмиканні: %s -> %s" % ("гасло" if cur["intro_text"] else "картинка",
                                                                              "гасло" if intro_text else "картинка")))
    for key, addr, label in (("line1", ADDR_BOOT_LINE1, "Talker Alias, частина 1"), ("line2", ADDR_BOOT_LINE2, "Talker Alias, частина 2")):
        text = line1 if key == "line1" else line2
        if text is None or text == cur[key]:
            continue
        chk = check_line(text)
        if not chk["ok"]:
            problems.append("%s: %s" % (label, chk["message"]))
            continue
        img.set_ee(addr, cv.pad_name(chk["raw"], BOOT_LINE_LEN))
        res.changed.append(("Основна інформація", "%s: «%s» -> «%s»" % (label, cur[key], text)))
        if chk["raw"] and any(ch in text for ch in "іїєґІЇЄҐ") and cc.encode_new_name(text)[1] == "cp1251":
            if cc.CP1251_WARNING not in res.warnings:
                res.warnings.append(cc.CP1251_WARNING)
    if problems:
        raise CodeplugEditError(problems)
    res.image = img
    return res


# =========================================================================================
#  APRS-слоти (CodeplugAPRSConfig_t, 64 Б; слоти 1..8, зайняті підряд з №1)
# =========================================================================================

def aprs_values(rec):
    """Запис слота (64 Б) -> значення форми (тексти з крапкою як десятковим знаком + прапорці)."""
    d = cc.aprs_decode(rec, ".")
    flags = rec[61]
    return {"name": cc.readable_text(rec[:APRS_NAME_LEN]), "ssid": d[1], "via1": d[2], "via1_ssid": d[3], "via2": d[4], "via2_ssid": d[5],
            "icon_table": d[6], "icon": d[7], "comment": d[8], "ambiguity": d[9], "use_position": bool(flags & APRS_FLAG_POSITION),
            "lat": d[11], "lon": d[12], "tx_freq": d[13], "qsy": bool(flags & APRS_FLAG_QSY), "baud300": bool(flags & APRS_FLAG_300),
            "silent": bool(flags & APRS_FLAG_SILENT)}


def new_aprs_values():
    """Типові значення нового слота (форма «Додати»)."""
    return {"name": "", "ssid": "0", "via1": "WIDE1", "via1_ssid": "1", "via2": "WIDE2", "via2_ssid": "1", "icon_table": "47", "icon": "0",
            "comment": "", "ambiguity": "0", "use_position": False, "lat": "0.0000", "lon": "0.0000", "tx_freq": "0", "qsy": False,
            "baud300": False, "silent": False}


def _aprs_encode(old_rec, v, problems, warnings):
    """Збирає 64 байти з значень форми. Проблеми додає в `problems` (з назвою поля), не кидає."""
    rec = bytearray(old_rec) if old_rec else bytearray(64)
    if not old_rec:
        struct.pack_into("<H", rec, 62, cc.APRS_MAGIC)
    name = v.get("name", "")
    if old_rec and name == cc.readable_text(old_rec[:APRS_NAME_LEN]):
        rec[:APRS_NAME_LEN] = bytes(old_rec[:APRS_NAME_LEN])
    elif not name:
        problems.append("назва: порожня")
    else:
        try:
            raw, enc = cc.encode_new_name(name)
        except ValueError as e:
            problems.append("назва «%s»: %s" % (name, e))
        else:
            if len(raw) > APRS_NAME_LEN:
                problems.append("назва «%s»: %d байт(ів), ліміт %d (кодування %s)" % (name, len(raw), APRS_NAME_LEN, enc))
            elif cc.readable_text(raw) != name:
                problems.append("назва «%s» читалась би як «%s» -- змініть літери" % (name, cc.readable_text(raw)))
            else:
                rec[:APRS_NAME_LEN] = raw.ljust(APRS_NAME_LEN, b"\x00")
                if enc == "cp1251" and any(ch in name for ch in "іїєґІЇЄҐ") and cc.CP1251_WARNING not in warnings:
                    warnings.append(cc.CP1251_WARNING)
    for key, idx, label in _APRS_TEXT_FIELDS:
        try:
            cc._aprs_encode_field(rec, idx, str(v.get(key, "")))
        except ValueError as e:
            problems.append("%s: %s" % (label, e))
    for key, idx, label in _APRS_FLAG_FIELDS:
        try:
            cc._aprs_encode_field(rec, idx, ("1" if v.get(key) else "0") if key == "baud300" else ("True" if v.get(key) else "False"))
        except ValueError as e:
            problems.append("%s: %s" % (label, e))
    rec[61] = (rec[61] | APRS_FLAG_SILENT) if v.get("silent") else (rec[61] & ~APRS_FLAG_SILENT & 0xFF)
    return bytes(rec)


def apply_aprs_slot(base_img, slot, values):
    """Змінити слот `slot` (0-based) або створити новий (slot=None -- наступний за останнім зайнятим). Повертає ImportResult."""
    img = _copy(base_img)
    res = cc.ImportResult()
    problems = []
    slots = dict(img.aprs())
    old = None
    if slot is None:
        slot = len(slots)
        if slot >= cc.APRS_MAX:
            raise CodeplugEditError(["немає вільного місця для APRS-слота (максимум %d)" % cc.APRS_MAX])
    else:
        old = slots.get(slot)
        if old is None:
            raise CodeplugEditError(["APRS-слот №%d порожній або не бачиться рацією" % (slot + 1)])
    rec = _aprs_encode(old, values, problems, res.warnings)
    # назва має бути унікальною серед слотів: канали посилаються на слот за номером, але в CSV -- за назвою
    if old is None or rec[:APRS_NAME_LEN] != bytes(old[:APRS_NAME_LEN]):           # лише коли назву справді міняють
        for s, r in slots.items():
            if s != slot and cv.name_bytes(r[:APRS_NAME_LEN]) == cv.name_bytes(rec[:APRS_NAME_LEN]) and rec[0] != 0:
                problems.append("назва «%s» уже є в слоті №%d" % (values.get("name", ""), s + 1))
    if problems:
        raise CodeplugEditError(problems)
    if old is not None and rec == bytes(old):
        res.image = img
        return res
    img.set_aprs(slot, rec)
    if old is None:
        orphans = img.aprs_revived(slot + 1)       # приховані записи за кінцем ожили б як зайві слоти
        for sl in orphans:
            img.set_aprs(sl, b"\xff" * cc.APRS_SIZE)
        if orphans:
            res.warnings.append("Стерто приховані APRS-слоти №%s (вони були за розривом нумерації й рації не видні; після додавання ожили б)."
                                % ", ".join(str(x + 1) for x in orphans))
        res.added.append(("APRS", cc.readable_text(rec[:APRS_NAME_LEN])))
    else:
        ov, nv = aprs_values(old), aprs_values(rec)
        what = [APRS_LABELS[k] for k in nv if nv[k] != ov[k]]
        res.changed.append(("APRS", "№%d %s: %s" % (slot + 1, cc.readable_text(rec[:APRS_NAME_LEN]), ", ".join(what) or "назва")))
    res.image = img
    return res


def aprs_users(img, slot):
    """Канали, що посилаються на APRS-слот №slot+1: [(номер, назва)]."""
    return [(n, cc.readable_text(rec[:16])) for n, rec in img.channels() if rec[cc.O_APRS] == slot + 1]


def delete_aprs_slot(base_img, slot):
    """Видалити слот. Прошивка читає слоти підряд з №1 до першого порожнього, тож видаляти можна лише ОСТАННІЙ (як і в імпорті CSV)."""
    img = _copy(base_img)
    res = cc.ImportResult()
    slots = dict(img.aprs())
    if slot not in slots:
        raise CodeplugEditError(["APRS-слот №%d порожній або не бачиться рацією" % (slot + 1)])
    if slot != len(slots) - 1:
        raise CodeplugEditError(["видалення слота з середини (№%d з %d) не підтримується: рація читає слоти підряд з №1 до першого порожнього, "
                                 "решта зникла б. Видаліть останній або змініть цей слот." % (slot + 1, len(slots))])
    users = aprs_users(img, slot)
    if users:
        res.warnings.append("APRS-слот №%d «%s» використовують канали: %s. Після видалення там лишиться порожнє посилання."
                            % (slot + 1, cc.readable_text(slots[slot][:APRS_NAME_LEN]),
                               ", ".join("№%d «%s»" % u for u in users[:8]) + (" ..." if len(users) > 8 else "")))
    img.set_aprs(slot, b"\xff" * cc.APRS_SIZE)
    res.removed.append(("APRS", "№%d %s" % (slot + 1, cc.readable_text(slots[slot][:APRS_NAME_LEN]))))
    res.image = img
    return res
