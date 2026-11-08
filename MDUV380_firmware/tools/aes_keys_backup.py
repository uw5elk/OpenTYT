# -*- coding: utf-8 -*-
"""Таблиця ключів AES у бекапі й відновленні (R31, частина 1).

Що це за область (усе з коду, application/source/crypto/dmr_aes_hook.c, claude/codeplug-map.md):
  початок          0xD9F9C (STOCK_KEY_TABLE_BASE; сира адреса SPI, БЕЗ FLASH_ADDRESS_OFFSET)
  запис            100 Б (STOCK_KEY_ENTRY_LEN) за адресою 0xD9F9C + 100*keyId; keyId 1..15 (STOCK_KEY_MIN_ID/MAX_ID)
  таблиця в архіві 16 записів (keyId 0..15) = 0x640 Б = 0xD9F9C..0xDA5DB; запис 0 прошивка не читає й не пише
  запис            [0] тип (0x04/0x07 = AES-256) [1..3] службові [4..35] назва UTF-16LE [36..67] ключ у «загорнутому» вигляді [68..99] нулі
  слот зайнятий    тип 0x04/0x07 І розгорнутий ключ не нульовий і не «порожній» (BLANK = 31 нуль і 0x01) -- stockKeyRead/stockKeyIsPresent
Слоти 1..15 лежать в одному секторі 0xDA000; запис 0 -- наприкінці попереднього (0xD9000), ділить його з областю №2 бази позивних, тому його НЕ відновлюємо.

Розгортання ключа вимагає `cryptography`, а бекап має працювати без неї. Обгортка фіксована (однакова на кожній рації), тож «порожній слот» -- це два
відомі 32-байтові значення (обгортка нуля й обгортка BLANK); їх звірено з stock_key_table.wrap_key у тесті."""
import hashlib
import json
import os
import zipfile

import cps_link as cl
import flash_guard as fg

KEYS_START = cl.AES_KEYS_RAW_START          # 0xD9F9C
ENTRY_LEN = cl.AES_KEYS_ENTRY_LEN           # 100
ENTRIES = cl.AES_KEYS_ENTRIES               # 16 (keyId 0..15)
KEYS_LEN = cl.AES_KEYS_RAW_LEN              # 0x640
SLOT_MIN, SLOT_MAX = 1, 15
PART_KEY = "aesKeys"
PART_FILE = "aeskeys.bin"
TYPE_OFF, NAME_OFF, KEY_OFF = 0, 4, 36
TYPES_AES256 = (0x04, 0x07)
WRAPPED_ZERO = bytes.fromhex("785c2c416004954f1f3845e36c35b5b9b1386422593e7039fbc5221463e7ac64")    # wrap_key(32 нулі)
WRAPPED_BLANK = bytes.fromhex("db2c41759739368ec19c94515ce8cf85b1386422593e7039fbc5221463e7ac64")   # wrap_key(BLANK)


class KeysError(cl.CpsError):
    pass


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def slot_addr(slot):
    if not (SLOT_MIN <= slot <= SLOT_MAX):
        raise ValueError("слот має бути 1..15")
    return KEYS_START + ENTRY_LEN * slot


def entry_of(data, slot):
    off = ENTRY_LEN * slot
    return bytes(data[off:off + ENTRY_LEN])


def slot_occupied(entry):
    """Той самий висновок, що stockKeyRead() у прошивці: тип AES-256 і ключ не нульовий та не BLANK."""
    if len(entry) != ENTRY_LEN or entry[TYPE_OFF] not in TYPES_AES256:
        return False
    wrapped = bytes(entry[KEY_OFF:KEY_OFF + 32])
    return wrapped not in (WRAPPED_ZERO, WRAPPED_BLANK)


def occupied_slots(data):
    """Номери зайнятих слотів 1..15 (не ключі)."""
    if len(data) != KEYS_LEN:
        raise KeysError("таблиця ключів має бути %d Б, а не %d" % (KEYS_LEN, len(data)))
    return [s for s in range(SLOT_MIN, SLOT_MAX + 1) if slot_occupied(entry_of(data, s))]


def slots_text(slots):
    return ", ".join(str(s) for s in slots) if slots else "жодного"


def manifest_part(data):
    """Запис для manifest["parts"]["aesKeys"]. Лише НОМЕРИ зайнятих слотів; ключів у маніфесті немає."""
    return {
        "file": PART_FILE, "area": cl.CPS_ACCESS_FLASH, "start": KEYS_START, "length": len(data), "sha256": sha256(data),
        "restorable": False, "restoredBy": "aes_keys_backup.restore_keys (окремий прапорець, типово вимкнено)",
        "containsSecrets": True, "entryLen": ENTRY_LEN, "slotRange": [SLOT_MIN, SLOT_MAX], "occupiedSlots": occupied_slots(data),
    }


def read_radio_keys(link, progress=None):
    return link.read(cl.CPS_ACCESS_FLASH, KEYS_START, KEYS_LEN, progress)


def read_backup_keys(source):
    """Таблиця з .zip (шлях або байти) -> bytes, або None, якщо архів її не містить. SHA-256 і межі перевіряються; CpsError, якщо файл пошкоджено."""
    import io
    f = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
    try:
        with zipfile.ZipFile(f) as z:
            manifest = json.loads(z.read("manifest.json").decode("utf-8"))
            part = manifest.get("parts", {}).get(PART_KEY)
            if part is None:
                return None
            data = z.read(part["file"])
    except (zipfile.BadZipFile, KeyError, ValueError, OSError) as e:
        raise cl.CpsError("це не бекап кодплага або файл пошкоджено: %s" % e)
    if len(data) != part.get("length") or sha256(data) != part.get("sha256"):
        raise cl.CpsError("таблиця ключів AES у бекапі пошкоджена (довжина або SHA-256 не збігаються з маніфестом)")
    if part.get("start") != KEYS_START or len(data) != KEYS_LEN:
        raise cl.CpsError("таблиця ключів у бекапі описує інший діапазон (початок 0x%X, довжина %d), ніж відомий цій прошивці (0x%X, %d). "
                          "Записувати поза відомою областю заборонено." % (part.get("start") or 0, len(data), KEYS_START, KEYS_LEN))
    return data


def describe_archive(source, restored=False):
    """Один рядок про ключі в архіві для підсумку відновлення (K4.2): є/нема, які слоти (номери), чи відновлювались. Не кидає за пошкоджений архів."""
    try:
        data = read_backup_keys(source)
    except cl.CpsError as e:
        return "Ключі AES: таблиця в архіві не читається (%s) -- ключі в рації не чіпав." % e
    if data is None:
        return "Ключі AES: у цьому архіві їх нема (створено без них або до R31) -- ключі в рації не чіпав."
    slots = occupied_slots(data)
    if restored:
        return "Ключі AES: в архіві слоти %s." % slots_text(slots)
    return "Ключі AES: в архіві є слоти %s; НЕ відновлювались (прапорець вимкнено) -- ключі в рації не чіпав." % slots_text(slots)


# --- план ----------------------------------------------------------------------------------------------

ST_SAME, ST_OVERWRITE, ST_CREATE, ST_EMPTY = "same", "overwrite", "create", "empty"
STATUS_TEXT = {ST_SAME: "без змін (вже такий самий)", ST_OVERWRITE: "буде перезаписано (слот у рації зараз зайнятий)",
               ST_CREATE: "буде записано (слот у рації порожній)", ST_EMPTY: "порожній у бекапі -- не чіпаю"}


class PlanItem:
    def __init__(self, slot, status, entry):
        self.slot, self.status, self.entry = slot, status, entry


class Plan:
    def __init__(self, items):
        self.items = items

    def writes(self):
        return [i for i in self.items if i.status in (ST_OVERWRITE, ST_CREATE)]

    def overwritten_occupied(self):
        return [i.slot for i in self.items if i.status == ST_OVERWRITE]

    def text(self):
        w = self.writes()
        lines = ["Слоти до запису: %s." % slots_text([i.slot for i in w])]
        occ = self.overwritten_occupied()
        lines.append("З них у рації зараз зайняті (ключі буде ЗАМІНЕНО): %s." % slots_text(occ))
        same = [i.slot for i in self.items if i.status == ST_SAME]
        if same:
            lines.append("Вже такі самі в рації: %s." % slots_text(same))
        empty = [i.slot for i in self.items if i.status == ST_EMPTY]
        if empty:
            lines.append("Порожні в бекапі (в рації не чіпаю): %s." % slots_text(empty))
        return "\n".join(lines)


def plan_restore(src, cur, selected=None):
    items = []
    for s in range(SLOT_MIN, SLOT_MAX + 1):
        e_src, e_cur = entry_of(src, s), entry_of(cur, s)
        if selected is not None and s not in selected:
            items.append(PlanItem(s, ST_EMPTY, e_src))
        elif not slot_occupied(e_src):
            items.append(PlanItem(s, ST_EMPTY, e_src))
        elif e_src == e_cur:
            items.append(PlanItem(s, ST_SAME, e_src))
        else:
            items.append(PlanItem(s, ST_OVERWRITE if slot_occupied(e_cur) else ST_CREATE, e_src))
    return Plan(items)


def expected_table(cur, plan):
    out = bytearray(cur)
    for i in plan.writes():
        out[ENTRY_LEN * i.slot:ENTRY_LEN * (i.slot + 1)] = i.entry
    return bytes(out)


def apply_plan(link, plan, log=print, progress=None):
    """R73: слоти ОДНОГО сектора пишуться одним записом (X 1, X 2 на кожен слот, X 3 -- одне стирання), а не слот за слотом (усі слоти 1..15 лежать у секторі 0xDA000,
    тож було до 15 стирань замість 1). Далі звірка читанням: усі слоти групи за один прохід. Групи (сектори) йдуть по черзі; перший збій групи зупиняє решту.
    Збій ЗАПИСУ групи: жоден слот групи не вважається записаним, у повідомленні перелічено слоти групи (стан невідомий -- перевір). Розбіжність звірки: слоти, що збіглися,
    -- записані; перший, що не збігся, -- помилка. Повертає {written, failed, untouched}; за збій запису винятків не кидає."""
    import phase_timing
    res = {"written": [], "failed": None, "untouched": []}
    todo = plan.writes()
    groups = {}
    for it in todo:
        groups.setdefault(slot_addr(it.slot) // fg.SECTOR, []).append(it)
    ph = phase_timing.Phases(link)
    order = list(groups.values())
    for k, grp in enumerate(order):
        slots = [i.slot for i in grp]
        if progress:
            progress(int(100.0 * k / max(1, len(order))), "Пишу слоти %s (%d з %d)" % (slots_text(slots), k + 1, len(order)))
        later = [i.slot for g in order[k + 1:] for i in g]
        try:
            with ph.phase("запис слотів %s" % slots_text(slots)):
                fg.write_group(link.ser, [(slot_addr(i.slot), i.entry) for i in grp], "keys")
        except Exception as e:  # noqa: BLE001
            res["failed"] = {"slot": slots[0], "message": "%s (запис слотів %s робиться одним записом сектора; їх стан невідомий -- перевір)" % (e, slots_text(slots))}
            res["untouched"] = later
            return res
        lo = slot_addr(grp[0].slot)
        hi = slot_addr(grp[-1].slot) + ENTRY_LEN
        with ph.phase("звірка слотів %s" % slots_text(slots)):
            back = link.read(cl.CPS_ACCESS_FLASH, lo, hi - lo)
        bad = []
        for i in grp:
            o = slot_addr(i.slot) - lo
            if bytes(back[o:o + ENTRY_LEN]) == i.entry:
                log("Слот %d записано й звірено." % i.slot)
                res["written"].append(i.slot)
            else:
                bad.append(i.slot)
        if bad:
            res["failed"] = {"slot": bad[0], "message": "після запису слот читається інакше, ніж записано (звірка не пройшла; слоти з розбіжністю: %s)" % slots_text(bad)}
            res["untouched"] = later
            return res
    if progress:
        progress(100, "Готово")
    if ph.items:
        log(ph.summary())
    return res


def result_text(res, plan=None):
    lines = []
    if res["written"]:
        lines.append("Записано й звірено слоти: %s." % slots_text(res["written"]))
    f = res["failed"]
    if f:
        lines.append("ПОМИЛКА на слоті %d: %s." % (f["slot"], f["message"]))
        lines.append("Цей слот міг лишитися записаним частково або старим -- перевір його.")
        if res["written"]:
            lines.append("Слоти до помилки ЗАПИСАНІ й залишаються записаними.")
        if res["untouched"]:
            lines.append("Не торкався (лишились такими, як були): %s." % slots_text(res["untouched"]))
    elif not res["written"]:
        lines.append("Нічого не записано.")
    return "\n".join(lines)


def confirm_text(plan, source_name):
    return "\n".join(["Відновити ключі AES рації з %s." % source_name, "",
                      "Ключі НЕ входять у відновлення кодплага; це окремий крок. Буде так:", plan.text(), "",
                      "Слоти пишуться ПО ОДНОМУ зі звіркою читанням; якщо один не запишеться, решта лишається як була.",
                      "Перед записом поточна таблиця ключів рації зберігається окремим файлом поруч із бекапом (він секретний)."])


def restore_keys(link, source, confirm, progress=None, log=print, now=None, post_reset=True, source_name=None, safety_dir=None, selected=None):
    """Відновити ключі AES з .zip бекапу. confirm(text, plan) -> bool викликається ПІСЛЯ перевірок і страхової копії, ПЕРЕД першим записом.
    Повертає словник: absent (архів без ключів -- рацію не чіпали), cancelled, nothingToDo, result, text, safetyCopy."""
    def prog(p, t):
        if progress:
            progress(max(0, min(100, int(p))), t)

    prog(0, "Читаю ключі з бекапу...")
    src = read_backup_keys(source)
    if src is None:
        text = "У цьому архіві ключів AES нема (створено без них або до R31) -- ключі в рації не чіпав."
        log(text)
        return {"absent": True, "cancelled": False, "nothingToDo": True, "text": text}
    prog(5, "Читаю таблицю ключів з рації...")
    cur = read_radio_keys(link)
    plan = plan_restore(src, cur, selected)
    if not plan.writes():
        text = ("У бекапі немає зайнятих слотів ключів -- ключі в рації не чіпав." if not occupied_slots(src)
                else "Таблиця ключів рації вже містить усе з бекапу (слоти %s) -- записувати нічого." % slots_text(occupied_slots(src)))
        log(text)
        return {"absent": False, "cancelled": False, "nothingToDo": True, "text": text, "plan": plan}
    d = safety_dir or (os.path.dirname(os.path.abspath(source)) if isinstance(source, (str, os.PathLike)) else os.getcwd())
    if not os.access(d, os.W_OK):
        raise KeysError("нема права писати в теку %s, де має лежати страхова копія таблиці ключів. Нічого не записано." % d)
    safety = cl.unique_path(d, cl.timestamp_name("aeskeys_pre-restore", ".bin", now))
    try:
        with open(safety, "xb") as f:
            f.write(cur)
        with open(safety, "rb") as f:
            if f.read() != cur:
                raise OSError("записаний файл відрізняється від прочитаного")
    except OSError as e:
        try:
            os.unlink(safety)
        except OSError:
            pass
        raise KeysError("не вдалося зберегти страхову копію таблиці ключів (%s). Нічого не записано." % e)
    log("Страхова копія таблиці ключів збережена й перевірена: %s (секретна)." % safety)
    name = source_name or (os.path.basename(source) if isinstance(source, (str, os.PathLike)) else "бекапу")
    if not confirm(confirm_text(plan, name), plan):
        log("Скасовано користувачем; ключі в рації не змінено.")
        return {"absent": False, "cancelled": True, "nothingToDo": False, "text": "Скасовано; ключі в рації не змінено.", "plan": plan,
                "safetyCopy": safety}
    res = apply_plan(link, plan, log, lambda p, t: prog(10 + 0.85 * p, t))
    text = result_text(res, plan)
    matches = None
    if not res["failed"]:
        matches = read_radio_keys(link) == expected_table(cur, plan)
        if not matches:
            text += "\nУВАГА: після запису таблиця в рації не збігається з очікуваною (поза записаними слотами щось відрізняється). Страхова копія: %s" % safety
    if post_reset and res["written"]:
        import cps_restore
        prog(97, "Перезавантажую рацію...")
        cps_restore._send_c(link, 6, cps_restore.POST_RESTORE_SUB)
    prog(100, "Готово")
    return {"absent": False, "cancelled": False, "nothingToDo": False, "text": text, "plan": plan, "result": res, "safetyCopy": safety,
            "tableMatchesExpected": matches}
