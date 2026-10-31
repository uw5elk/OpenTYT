# -*- coding: utf-8 -*-
"""Відновлення з бекапу: кодплаг + (за окремими прапорцями) область custom-data та ключі AES (R31).

`cps_restore` не змінено: порядок той самий, що в custom_region.restore_codeplug_and_region (R30) -- спершу restore_codeplug без перезавантаження,
далі область custom-data, далі ключі AES, і ОДНЕ перезавантаження рації в кінці (C 6 1). Кожен додатковий крок -- окремий прапорець, типово вимкнений.
Скасований крок кодплага зупиняє решту."""
import glob
import json
import os
import zipfile

import aes_keys_backup as akb
import cps_link as cl
import custom_compact as cc
import custom_region as cr


def restore_codeplug_and_extras(link, zip_path, confirm, progress=None, log=print, with_region=False, include_state=False, with_keys=False, now=None):
    """Повертає {"codeplug": ..., "region": ... або None, "keys": ... або None}."""
    import cps_restore
    out = {"codeplug": None, "region": None, "keys": None, "keysNote": None}
    extra = bool(with_region or with_keys)
    cp = cps_restore.restore_codeplug(link, zip_path, confirm, progress, log=log, now=now, post_reset=not extra)
    out["codeplug"] = cp
    if not cp.get("cancelled"):
        out["keysNote"] = akb.describe_archive(zip_path, restored=bool(with_keys))
    if not extra or cp.get("cancelled"):
        return out
    wrote = not cp.get("nothingToDo")
    try:
        if with_region:
            out["region"] = cr.restore_region(link, zip_path, confirm, include_state=include_state, progress=progress, log=log, now=now, post_reset=False)
        # ключі -- окремий крок: збій запису блока області (результат із failed) його не скасовує; виняток піднімається після перезавантаження
        if with_keys:
            out["keys"] = akb.restore_keys(link, zip_path, confirm, progress=progress, log=log, now=now, post_reset=False)
    finally:
        reg, keys = out["region"], out["keys"]
        if wrote or (reg and reg.get("result") and reg["result"]["written"]) or (keys and keys.get("result") and keys["result"]["written"]):
            cps_restore._send_c(link, 6, cps_restore.POST_RESTORE_SUB)
    return out


# =========================================================================================
#  R50: одне «Відновити…» -- що є у файлі, що з нього можна відновити, і сам запис за вибраним
# =========================================================================================
KIND_ZIP = "zip"                  # архів бекапу (codeplug_backup_*.zip або codeplug_pre-restore_*.zip -- страхова копія кодплага)
KIND_REGION_BIN = "region_bin"    # страхова копія ВСІЄЇ області custom-data (.bin, 64 КіБ): customdata_pre-restore_*, customdata_pre-compact_*
KIND_BAD = "bad"

SAFETY_PATTERNS = ("codeplug_pre-restore_*.zip", "customdata_pre-restore_*.bin", "customdata_pre-compact_*.bin")


def inspect_source(path):
    """Що за файл і що з нього можна відновити. Не змінює нічого й не торкається рації.
    -> {"kind": zip|region_bin|bad, "codeplug": bool, "region": bool, "keys": bool, "keysText": str, "why": str}"""
    out = {"kind": KIND_BAD, "codeplug": False, "region": False, "keys": False, "keysText": "", "why": ""}
    if not path or not os.path.isfile(path):
        out["why"] = "файл не знайдено"
        return out
    try:
        with open(path, "rb") as f:
            head = f.read(4)
    except OSError as e:
        out["why"] = "не вдалося прочитати файл: %s" % e
        return out
    if head[:2] == b"PK":
        try:
            with zipfile.ZipFile(path) as z:
                manifest = json.loads(z.read("manifest.json").decode("utf-8"))
                names = set(z.namelist())
        except (zipfile.BadZipFile, KeyError, ValueError, OSError) as e:
            out["why"] = "це не бекап кодплага або файл пошкоджено: %s" % e
            return out
        parts = manifest.get("parts", {}) if isinstance(manifest, dict) else {}
        out["kind"] = KIND_ZIP
        out["codeplug"] = "eeprom.bin" in names and "flash.bin" in names
        out["region"] = cr.PART_KEY in parts
        k = parts.get(akb.PART_KEY)
        out["keys"] = k is not None
        if k:
            out["keysText"] = akb.slots_text(k.get("occupiedSlots") or [])
        if not out["codeplug"]:
            out["kind"], out["why"] = KIND_BAD, "в архіві нема eeprom.bin / flash.bin -- це не бекап кодплага"
        return out
    try:
        size = os.path.getsize(path)
    except OSError as e:
        out["why"] = str(e)
        return out
    if size == cc.REGION_LEN:
        out["kind"], out["region"] = KIND_REGION_BIN, True
        return out
    if size == akb.KEYS_LEN:
        out["why"] = ("це страхова копія таблиці ключів AES (.bin): ключі відновлюються лише з архіву .zip, у якому вони збережені "
                      "(так було й раніше -- окремої дії для цього .bin нема)")
    else:
        out["why"] = ("невідомий файл: довжина %d Б. Потрібен архів бекапу (.zip) або страхова копія області custom-data (.bin, %d Б)" % (size, cc.REGION_LEN))
    return out


def find_safety_copies(*directories):
    """Автоматичні страхові копії, які CPS сам зберігав перед записом: [(шлях, час зміни)] від найновішої. Шукає в заданих теках."""
    seen, found = set(), []
    for d in directories:
        if not d or not os.path.isdir(d):
            continue
        for pat in SAFETY_PATTERNS:
            for p in glob.glob(os.path.join(d, pat)):
                rp = os.path.abspath(p)
                if rp in seen:
                    continue
                seen.add(rp)
                try:
                    found.append((rp, os.path.getmtime(rp)))
                except OSError:
                    continue
    found.sort(key=lambda t: t[1], reverse=True)
    return found


def restore_selected(link, path, confirm, progress=None, log=print, with_codeplug=True, with_region=False, include_state=False, with_keys=False, now=None):
    """Одна точка входу «Відновити…». Повертає {"codeplug", "region", "keys", "keysNote", "raw"} (непройдене -- None).

    * страхова копія області (.bin): лише область (restore_safety_copy -- той самий безпечний порядок запису, що й раніше);
    * архів з кодплагом: restore_codeplug_and_extras -- РІВНО той самий шлях, що й «Відновити кодплаг…» з прапорцями;
    * архів без кодплага (лише область / лише ключі / обидва): restore_region / restore_keys. Один крок -- викликається як раніше (з перезавантаженням),
      два -- без перезавантаження кожного й з одним перезавантаженням в кінці (як у restore_codeplug_and_extras)."""
    out = {"codeplug": None, "region": None, "keys": None, "keysNote": None, "raw": None}
    info = inspect_source(path)
    if info["kind"] == KIND_BAD:
        raise cl.CpsError(info["why"])
    if info["kind"] == KIND_REGION_BIN:
        out["raw"] = cc.restore_safety_copy(link, path, confirm, progress=progress, log=log)
        return out
    if with_codeplug:
        return restore_codeplug_and_extras(link, path, confirm, progress, log=log, with_region=with_region, include_state=include_state,
                                           with_keys=with_keys, now=now)
    if not (with_region or with_keys):
        raise cl.CpsError("нічого не вибрано для відновлення")
    both = bool(with_region and with_keys)
    try:
        if with_region:
            out["region"] = cr.restore_region(link, path, confirm, include_state=include_state, progress=progress, log=log, now=now, post_reset=not both)
        if with_keys:
            out["keys"] = akb.restore_keys(link, path, confirm, progress=progress, log=log, now=now, post_reset=not both)
    finally:
        if both:
            import cps_restore
            reg, keys = out["region"], out["keys"]
            if (reg and reg.get("result") and reg["result"]["written"]) or (keys and keys.get("result") and keys["result"]["written"]):
                cps_restore._send_c(link, 6, cps_restore.POST_RESTORE_SUB)
    return out
