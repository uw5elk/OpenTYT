#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""contact_edit.py -- R26 V2: правка контактів кодплуга (назва, TG/ID, тип виклику; додати; видалити). ЛОГІКА без Tk.

Зміни НЕ пишуться «знімком»: вікно перегляду збирає СПИСОК ОПЕРАЦІЙ, а на «Записати» ми заново читаємо ПОТОЧНИЙ кодплуг рації,
перевіряємо, що змінюваний контакт ще той самий (назва збігається з тією, що бачив користувач), накладаємо операції й пишемо
ТІЄЮ САМОЮ дорогою, що відновлення з бекапу (cps_csv.write_image_via_restore -> cps_restore.restore_codeplug: страхова копія,
діалог зі списком змін, лише відмінні сектори, перечитування, SHA-256, C 6 1). Заблоковано тією ж RESTORE_UNLOCKED.

Операції (словники):
  {"op": "edit",   "slot": i, "expect_name": сирі 16 байтів, "name": текст|None, "id": int|None, "type": 0|1|2|None}
  {"op": "add",    "name": текст, "id": int, "type": 0|1|2}
  {"op": "delete", "slot": i, "expect_name": сирі 16 байтів}
slot -- 0-based слот контакту (номер у кодплузі = slot + 1). Порожній запис = name[0] == 0xFF (codeplugInitContactsCache).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cps_link as cl  # noqa: E402
import codeplug_view as cv  # noqa: E402
import cps_csv as cc  # noqa: E402

NAME_LIMIT = 16
ID_MAX = 16777215                    # 24-бітний DMR ID / «All Call»
CALL_TYPE_LABELS = {0: "Група", 1: "Приват", 2: "Всім"}


class ContactEditError(cl.CpsError):
    pass


def check_name(text):
    """Перевірка назви для вікна: {ok, raw, enc, nbytes, remaining, message}. Живий лічильник «байтів залишилось»."""
    out = {"ok": False, "raw": b"", "enc": "", "nbytes": 0, "remaining": NAME_LIMIT, "message": ""}
    if not text:
        out["message"] = "назва порожня"
        return out
    try:
        raw, enc = cc.encode_new_name(text)
    except ValueError as e:
        out["message"] = str(e)
        return out
    out.update(raw=raw, enc=enc, nbytes=len(raw), remaining=NAME_LIMIT - len(raw))
    if len(raw) > NAME_LIMIT:
        out["message"] = "на %d байт(ів) довше за ліміт %d (кодування %s)" % (len(raw) - NAME_LIMIT, NAME_LIMIT, enc)
        return out
    if cv.decode_name_ex(raw)[0] != text:
        out["message"] = "після запису читалась би як «%s» -- змініть літери" % cv.decode_name_ex(raw)[0]
        return out
    out["ok"] = True
    out["message"] = "кодування %s, залишилось %d байт(ів)" % (enc, NAME_LIMIT - len(raw))
    return out


def parse_id(text):
    t = (text or "").strip()
    if not t.isdigit():
        raise ValueError("TG / ID -- ціле число 0..%d" % ID_MAX)
    v = int(t)
    if not 0 <= v <= ID_MAX:
        raise ValueError("TG / ID поза межами 0..%d" % ID_MAX)
    return v


def users_of_contact(img, number):
    """Хто посилається на контакт №number: ([назви TG-списків], [(номер, назва) каналів])."""
    groups = []
    for _slot, rec, length in img.groups():
        for k in range(length):
            v = rec[16 + 2 * k] | (rec[17 + 2 * k] << 8)
            if v == 0:
                break
            if v == number:
                groups.append(cc.readable_text(rec[:16]))
                break
    chans = [(n, cc.readable_text(rec[:16])) for n, rec in img.channels() if (rec[cc.O_CONTACT] | (rec[cc.O_CONTACT + 1] << 8)) == number]
    return groups, chans


def delete_warning(img, slot):
    """Текст попередження перед видаленням (або None, якщо контакт ніким не використовується)."""
    groups, chans = users_of_contact(img, slot + 1)
    if not groups and not chans:
        return None
    parts = []
    if groups:
        parts.append("TG-список(и): %s" % ", ".join("«%s»" % g for g in groups))
    if chans:
        parts.append("канал(и): %s" % ", ".join("№%d «%s»" % c for c in chans[:8]) + (" ..." if len(chans) > 8 else ""))
    return "Контакт №%d «%s» використовується: %s. Після видалення там лишиться порожнє посилання." % (
        slot + 1, cc.readable_text(dict(img.contacts())[slot][:16]), "; ".join(parts))


def apply_ops(base_img, ops):
    """Накласти операції на образ. Повертає ImportResult (image, added/changed/removed/warnings). Помилка -- ContactEditError."""
    img = cc.Image(base_img.eeprom, base_img.flash, base_img.base)
    res = cc.ImportResult()
    problems = []
    contacts = dict(img.contacts())
    referenced = set()
    for _s, rec, length in img.groups():
        for k in range(length):
            v = rec[16 + 2 * k] | (rec[17 + 2 * k] << 8)
            if v == 0:
                break
            referenced.add(v)
    for _n, rec in img.channels():
        referenced.add(rec[cc.O_CONTACT] | (rec[cc.O_CONTACT + 1] << 8))
    for op in ops:
        kind = op["op"]
        if kind in ("edit", "delete"):
            slot = op["slot"]
            rec = contacts.get(slot)
            if rec is None or cv.name_bytes(rec[:16]) != cv.name_bytes(op["expect_name"]):
                problems.append("контакт №%d у рації вже не такий, яким його бачив перегляд (змінено або видалено) -- прочитайте кодплуг ще раз"
                                % (slot + 1))
                continue
        if kind == "delete":
            warn = delete_warning(img, slot)
            if warn:
                res.warnings.append(warn)
            res.removed.append(("Контакти", "№%d %s" % (slot + 1, cc.readable_text(rec[:16]))))
            img.set_contact(slot, b"\xff" * cl.CP_CONTACT_SIZE)
            del contacts[slot]
        elif kind == "edit":
            new = bytearray(rec)
            what = []
            if op.get("name") is not None:
                chk = check_name(op["name"])
                if not chk["ok"]:
                    problems.append("контакт №%d: назва «%s»: %s" % (slot + 1, op["name"], chk["message"]))
                    continue
                new[:16] = chk["raw"].ljust(NAME_LIMIT, b"\xff")
                what.append("назва")
                if chk["enc"] == "cp1251" and any(ch in op["name"] for ch in "іїєґІЇЄҐ"):
                    res.warnings.append(cc.CP1251_WARNING)
            if op.get("id") is not None:
                new[16:20] = bytes.fromhex("%08d" % op["id"])
                what.append("TG / ID")
            if op.get("type") is not None:
                new[20] = op["type"]
                what.append("тип")
            if bytes(new) != bytes(rec):
                img.set_contact(slot, bytes(new))
                contacts[slot] = bytes(new)
                res.changed.append(("Контакти", "№%d %s: %s" % (slot + 1, cc.readable_text(new[:16]), ", ".join(what))))
        elif kind == "add":
            chk = check_name(op["name"])
            if not chk["ok"]:
                problems.append("новий контакт: назва «%s»: %s" % (op["name"], chk["message"]))
                continue
            free = [i for i in range(cl.CP_CONTACTS_MAX) if i not in contacts]
            if not free:
                problems.append("нема вільного місця для контакту (максимум %d)" % cl.CP_CONTACTS_MAX)
                continue
            clean = [i for i in free if (i + 1) not in referenced]
            slot = (clean or free)[0]
            if not clean:
                res.warnings.append("усі вільні слоти контактів чимось згадані -- новий контакт №%d може «ожити» у старому посиланні" % (slot + 1))
            rec = bytearray(b"\xff" * 16 + bytes(8))
            rec[:16] = chk["raw"].ljust(NAME_LIMIT, b"\xff")
            rec[16:20] = bytes.fromhex("%08d" % op["id"])
            rec[20] = op["type"]
            rec[22] = 0xFF                    # як menuContactDetails.c для нового контакту
            img.set_contact(slot, bytes(rec))
            contacts[slot] = bytes(rec)
            res.added.append(("Контакти", "№%d %s (ID %d)" % (slot + 1, cc.readable_text(rec[:16]), op["id"])))
            if chk["enc"] == "cp1251" and any(ch in op["name"] for ch in "іїєґІЇЄҐ"):
                res.warnings.append(cc.CP1251_WARNING)
        else:
            problems.append("невідома операція %r" % kind)
    if problems:
        raise ContactEditError("Зміни контактів відхилено. Нічого не записано.\n" + "\n".join("  - " + p for p in problems))
    # одне й те саме попередження про cp1251 -- один раз
    seen, uniq = set(), []
    for w in res.warnings:
        if w not in seen:
            seen.add(w)
            uniq.append(w)
    res.warnings = uniq
    res.image = img
    return res


EDIT_TITLE = "ЗМІНА КОНТАКТІВ -- рація буде ПЕРЕЗАПИСАНА."


def apply_to_radio(link, ops, confirm, progress=None, log=print, out_dir=".", now=None, clock=None, post_reset=True):
    """Прочитати поточний кодплуг рації, накласти операції, записати через шлях відновлення з бекапу."""
    import time as _t
    clock = clock or _t.time

    def prog(pct, text):
        if progress:
            progress(max(0, min(100, int(pct))), text)

    prog(0, "Читаю поточний кодплуг рації...")
    cp, _m = cv.codeplug_from_radio(link, lambda p, t: prog(p * 0.25, t))
    res = apply_ops(cc.Image.from_codeplug(cp), ops)
    if not res.any_change():
        prog(100, "Змін немає")
        return {"cancelled": False, "nothingToDo": True, "sectorsWritten": 0, "report": res}
    return cc.write_image_via_restore(link, res, confirm, progress=lambda p, t: prog(27 + p * 0.73, t), log=log, now=now, clock=clock,
                                      post_reset=post_reset, title=EDIT_TITLE, out_dir=out_dir, zip_prefix="codeplug_contacts-edit",
                                      note="Образ після правки контактів поверх поточного стану рації. Це те, що буде записано.")
