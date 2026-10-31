# -*- coding: utf-8 -*-
"""R50: логіка вікна «Відновити…» БЕЗ Tk -- які прапорці доступні за файлом (state_for) і що буде записано та якими запобіжниками (summary_text).
Вікно (cps_ui/restore_dialog.py) лише показує результат; тут усе тестується без дисплея (test_r50.py)."""
import restore_extras as rx


def state_for(info, current=None):
    """Які прапорці доступні й які їхні значення за файлом `info` (результат rx.inspect_source).
    `current` -- {"codeplug","region","state","keys"} попередні значення користувача (зберігаються там, де прапорець лишається доступним).
    -> {"codeplug": (значення, доступний), "region": ..., "state": ..., "keys": ..., "ok": bool, "note": str}"""
    cur = dict(current or {})
    kind = info.get("kind")
    out = {"codeplug": (False, False), "region": (False, False), "state": (False, False), "keys": (False, False), "ok": False, "note": ""}
    if kind == rx.KIND_ZIP:
        cp = bool(info["codeplug"])
        out["codeplug"] = (bool(cur.get("codeplug", True)) and cp, cp)
        rg = bool(info["region"])
        out["region"] = (bool(cur.get("region", False)) and rg, rg)
        out["state"] = (bool(cur.get("state", False)) and out["region"][0], out["region"][0])
        ks = bool(info["keys"])
        out["keys"] = (bool(cur.get("keys", False)) and ks, ks)
        notes = []
        if not rg:
            notes.append("в архіві області custom-data нема (його створено до R30 або з вимкненою галочкою) -- її не відновити")
        if not ks:
            notes.append("в архіві ключів AES нема -- їх не відновити")
        out["note"] = "; ".join(notes)
    elif kind == rx.KIND_REGION_BIN:
        out["region"] = (True, False)           # страхова копія області відновлює лише область, і прапорець не знімається
        out["note"] = "це страхова копія ВСІЄЇ області custom-data: відновлюється лише вона (кодплаг і ключі AES у такому файлі не зберігаються)"
    else:
        out["note"] = info.get("why") or ""
    out["ok"] = any(out[k][0] for k in ("codeplug", "region", "keys"))
    return out


def summary_text(info, st):
    """Одне пояснення: що буде записано і які запобіжники діють -- ДО натискання."""
    if not st["ok"]:
        return st["note"] or "Нічого не вибрано для відновлення."
    parts, guards = [], []
    if st["codeplug"][0]:
        parts.append("кодплаг (канали, зони, контакти...)")
        guards.append("страхова копія кодплага поруч з архівом, перелік змін до запису, запис лише відмінних секторів, звірка")
    if st["region"][0]:
        parts.append("область custom-data (теми, SMS, RCTL, APRS, вибір ключа AES%s)" % (", разом з лічильниками RCTL" if st["state"][0] else "; лічильники RCTL не чіпаю"))
        guards.append("страхова копія області, перелік блоків до запису, запис блок за блоком зі звіркою" if info["kind"] == rx.KIND_ZIP
                      else "порядок запису: обнулити заголовок -> змінені ділянки -> заголовок останнім, потім звірка байт у байт")
    if st["keys"][0]:
        parts.append("ключі AES (слоти %s)" % (info.get("keysText") or "з архіву"))
        guards.append("страхова копія таблиці ключів (секретна), перелік слотів до запису, перечитування кожного слота")
    return "Буде відновлено: %s.\nЗапобіжники: %s.\nПісля запису рація перезавантажиться." % ("; ".join(parts), "; ".join(guards))
