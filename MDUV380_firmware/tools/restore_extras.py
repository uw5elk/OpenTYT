# -*- coding: utf-8 -*-
"""Відновлення з бекапу: кодплаг + (за окремими прапорцями) область custom-data та ключі AES (R31).

`cps_restore` не змінено: порядок той самий, що в custom_region.restore_codeplug_and_region (R30) -- спершу restore_codeplug без перезавантаження,
далі область custom-data, далі ключі AES, і ОДНЕ перезавантаження рації в кінці (C 6 1). Кожен додатковий крок -- окремий прапорець, типово вимкнений.
Скасований крок кодплага зупиняє решту."""
import aes_keys_backup as akb
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
