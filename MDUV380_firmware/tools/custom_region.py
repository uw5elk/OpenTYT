#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""custom_region.py -- R30: область custom-data рації (SPI-флеш, сирі адреси 0x20000..0x2FFFF) у бекапі, відновленні й файлі налаштувань.

ЧОМУ ЦЕ ОКРЕМИЙ МОДУЛЬ. Область custom-data лежить ПОЗА тим, що бекапить і відновлює кодплаг (cps_link/cps_restore): EEPROM -- сирі 0..0x1FFFF, флеш-кодплаг --
від ~0x9B000. Тут же живуть теми екрана, SMS-повідомлення й пресети, RCTL, APRS-режим і бікон, вибір ключа AES, заставка. cps_restore цей модуль НЕ чіпає
і не змінено: відновлення області -- окремий крок з окремим прапорцем.

ЩО ВОНО РОБИТЬ
  * parse_region()   -- розбір 64 КБ області на блоки (той самий алгоритм сканування, що в прошивці codeplug.c і custom_data.find_or_alloc_block);
  * manifest_part()  -- опис області для маніфесту бекапу (діапазон, SHA-256, список знайдених блоків з типами й довжинами);
  * read_backup_region() -- область з .zip бекапу; старий архів без області дає None (тоді при відновленні область НЕ чіпаємо);
  * plan_restore() / restore_region() -- відновлення БЛОК ЗА БЛОКОМ через custom_data.write_block (sector-safe) зі звіркою читанням КОЖНОГО блока;
    збій на блоці зупиняє решту: уже записані лишаються записаними, решта -- як були, і звіт про це сказано словами;
  * файл налаштувань (OpenTYT-settings-1, JSON): усі блоки області в одному файлі, щоб перенести налаштування на іншу рацію або повернути після дослідів.

ЩО НІКОЛИ НЕ ПИШЕМО
  * сектор калібрування 0x10000..0x10FFF -- він поза областю (область 0x20000..0x2FFFF), і custom_data.flash_write_span відмовляє будь-якому запису
    поза областю, тож навіть помилка в розрахунку адреси не дійде до флеша;
  * RCTL_STATE (тип 10) -- не налаштування, а стан: лічильники anti-replay, які веде сама прошивка. Типово НЕ застосовується (include_state=False);
    відновлення чужих лічильників могло б або ослабити захист (старіші номери), або заблокувати зв'язок (занадто великі);
  * AES_KEYS (тип 6), якщо в ньому є ключовий матеріал (слот valid=1 з ненульовим ключем): прошивка більше не читає ключі з цього блока (лише байт 5 --
    вибір ключа TX), але в блоці від старих версій ключі можуть лишатися. Такий блок типово НЕ застосовується, а файл з ним помічено як секретний.
"""
import datetime
import hashlib
import json
import os
import struct
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cps_link as cl  # noqa: E402

# --- межі: з codeplug.h/codeplug.c (FLASH_ADDRESS_OFFSET, MAX_BLOCK_ADDRESS) і usb_com.c (калібрування). Звіряються з custom_data у тесті. ---
REGION_RAW_START = 0x20000          # FLASH_ADDRESS_OFFSET (MDUV380)
REGION_LEN = 0x10000                # MAX_BLOCK_ADDRESS
REGION_RAW_END = REGION_RAW_START + REGION_LEN
CAL_START = 0x10000                 # сектор калібрування (usb_com.c "Local calibration"); поза областю
CAL_END = CAL_START + 0x1000
MAGIC = b"OpenGD77"
REGION_HDR = 12                     # "OpenGD77" + 4 зарезервованих байти
BLOCK_HDR = 8                       # {int32 type; int32 length}
TYPE_EMPTY = -1                     # 0xFFFFFFFF як int32

PART_KEY = "customData"             # ключ у manifest["parts"]
PART_FILE = "customdata.bin"        # файл у .zip
SETTINGS_FORMAT = "OpenTYT-settings-1"

TYPE_AES_KEYS = 6
TYPE_RCTL_STATE = 10

# Тип -> (ім'я з enum, назва українською, що зберігає, хто пише, вид). Вид: "data" -- дані користувача, "setting" -- налаштування, "state" -- стан прошивки.
# Розміри й автори -- з коду (дивись claude/codeplug-map.md, розділ «Область custom-data»); тут лише те, що потрібне для списків і типових прапорців.
BLOCK_TYPES = {
    1: ("IMAGE", "Зображення заставки", "картинка екрана вітання", "CPS", "data"),
    2: ("BEEP", "Мелодія вмикання", "мелодія при ввімкненні", "CPS", "data"),
    3: ("SATELLITE_TLE", "Супутники (TLE)", "елементи орбіт для екрана супутників", "CPS", "data"),
    4: ("THEME_DAY", "Тема екрана: денна", "32 кольори RGB565", "прошивка і CPS", "setting"),
    5: ("THEME_NIGHT", "Тема екрана: нічна", "32 кольори RGB565", "прошивка і CPS", "setting"),
    6: ("AES_KEYS", "AES: вибір ключа", "селектор ключа TX (і, у старих версіях, ключовий матеріал)", "прошивка і CPS", "setting"),
    7: ("MESSAGES", "SMS: повідомлення", "вхідні й надіслані повідомлення", "прошивка", "data"),
    8: ("MSG_CONFIG", "SMS: пресети й отримувач", "швидкі тексти, отримувач, шифрування SMS", "CHIRP", "setting"),
    9: ("RCTL_CONFIG", "RCTL: налаштування", "дозвіл команд і вигляд", "прошивка і CHIRP", "setting"),
    10: ("RCTL_STATE", "RCTL: лічильники", "лічильники anti-replay (стан, не налаштування)", "прошивка", "state"),
    11: ("CALL_REPLAY_CONFIG", "Переслухати: налаштування", "перемикач «Запис RX»", "прошивка і ПК", "setting"),
    12: ("SMS_TX_MODE", "SMS: режим передачі", "режим TX SMS (1 байт)", "прошивка", "setting"),
    13: ("APRS_MODE_CFG", "APRS: режим", "оверрайди «Режиму APRS»", "прошивка і ПК", "setting"),
    14: ("APRS_BEACON_CFG", "APRS: бікон", "налаштування стокового бікона", "прошивка і ПК", "setting"),
    15: ("ROAM_CFG", "Роумінг: налаштування", "автоперехід увімк./вимк., макс. стрибків", "прошивка і ПК", "setting"),
    16: ("ROAM_NAMES", "Роумінг: імена списків", "10 імен списків роумінгу по 16 символів (cp1251)", "прошивка і ПК", "setting"),
    17: ("VOLUME_LOW_CFG", "Мін. гучність", "тихий нижній рівень гучності: 1 байт, 0 вимк / 1 = коліно 8 / 2 = 16 / 3 = 24 позицій ручки", "прошивка і ПК", "setting"),
    18: ("DUAL_CHANNEL_CFG", "Подвійний прийом", "8 Б (формат -- dual_channel.h): [0] версія, [1] біти увімкнено/покажчик B, [2..3] номер каналу картки B (обраний ручкою; червона з VFO B повертає на нього), [4] тип B (0 канал, 1 VFO A, 2 VFO B), [5] біти 0..1 тип поточного A, біти 2..3 тип «A для повернення» (0 нема, 1 канал, 2 VFO A, 3 VFO B), [6..7] номер каналу «A для повернення»", "прошивка", "setting"),
    19: ("TONE_REPLY_CFG", "Тон-відгук", "8 Б (формат -- tone_reply.h): [0] версія 3, [1] тривалість с, [2] затримка с, [3] біт 0 «увімкнено», [4..5] частота Гц LE, [6] поріг сигналу с 0..5 (v2 R100: без порогу, v1 R99: ×100 мс -- мігруються)", "прошивка", "setting"),
}


class RegionError(cl.CpsError):
    """Область не розібрано / не можна записати (пояснення словами)."""


class SettingsFileError(cl.CpsError):
    """Файл налаштувань пошкоджено або це не він."""


def type_name(t):
    if t in BLOCK_TYPES:
        return BLOCK_TYPES[t][0]
    if t >= 0x7E000000 and t < 0x7E000000 + 0x100000:
        return "ВИЛУЧЕНО_%d" % (t - 0x7E000000)
    return "ТИП_%d" % t


RETIRED_BASE = 0x7E000000           # R35: вилучений блок (custom_data.retire_block): тип = RETIRED_BASE + колишній тип; прошивка його пропускає


def is_retired(t):
    return RETIRED_BASE <= t < RETIRED_BASE + 0x100000


def type_title(t):
    if t in BLOCK_TYPES:
        return BLOCK_TYPES[t][1]
    if is_retired(t):
        return "Вилучений блок (було: %s)" % type_title(t - RETIRED_BASE)
    return "Невідомий блок (тип %d)" % t


def sha256(data):
    return hashlib.sha256(data).hexdigest()


# =========================================================================================
#  Розбір області
# =========================================================================================

class Block:
    def __init__(self, type_, offset, payload):
        self.type = type_
        self.offset = offset            # зсув заголовка блока від початку області
        self.payload = bytes(payload)

    @property
    def length(self):
        return len(self.payload)

    @property
    def name(self):
        return type_name(self.type)

    @property
    def title(self):
        return type_title(self.type)

    @property
    def kind(self):
        return BLOCK_TYPES[self.type][4] if self.type in BLOCK_TYPES else "data"

    @property
    def secret(self):
        return has_secret(self.type, self.payload)


class Region:
    def __init__(self, data):
        self.data = bytes(data)
        self.magic_ok = False
        self.erased = False             # перші 12 байтів усі 0xFF: області ще не створено
        self.blocks = []
        self.problems = []
        self.end = REGION_HDR           # зсув першого вільного слота (або де сканування зупинилось)

    def by_type(self):
        return {b.type: b for b in self.blocks}


def parse_region(data):
    """Розбір області тим самим алгоритмом, що codeplugGetOpenGD77CustomDataStartAddressForType(): заголовки {type,len} від зсуву 12, доки не
    натрапимо на порожній слот (довжина 0 або 0xFFFFFFFF). Нічого не кидає: проблеми збираються в Region.problems."""
    r = Region(data)
    if len(data) != REGION_LEN:
        r.problems.append("довжина області %d, а має бути %d" % (len(data), REGION_LEN))
        return r
    r.erased = all(x == 0xFF for x in data[:REGION_HDR])
    r.magic_ok = data[:8] == MAGIC
    if not r.magic_ok:
        r.problems.append("область без заголовка OpenGD77" + (" (порожня, стерта)" if r.erased else ""))
        return r
    seen = set()
    addr = REGION_HDR
    while addr + BLOCK_HDR <= REGION_LEN:
        dtype, dlen = struct.unpack("<ii", data[addr:addr + BLOCK_HDR])
        if dlen == 0 or dlen == TYPE_EMPTY:
            r.end = addr
            return r
        if dlen < 0 or addr + BLOCK_HDR + dlen > REGION_LEN:
            r.problems.append("блок типу %d у зсуві %d має довжину %d, що виходить за область -- розбір зупинено" % (dtype, addr, dlen))
            r.end = addr
            return r
        if dtype in seen and not is_retired(dtype):
            r.problems.append("тип %d зустрівся двічі (зсув %d) -- прошивка бачить лише перший" % (dtype, addr))
        else:
            seen.add(dtype)
            r.blocks.append(Block(dtype, addr, data[addr + BLOCK_HDR:addr + BLOCK_HDR + dlen]))
        addr += BLOCK_HDR + dlen
    r.end = addr
    return r


def has_secret(type_, payload):
    """AES_KEYS: чи є слот valid=1 з ненульовим ключем (розкладка: 'AESK', ver, txkey, rsvd2, 16 x (valid, keyid, rsvd2, key[32]))."""
    if type_ != TYPE_AES_KEYS or payload[:4] != b"AESK":
        return False
    for i in range(16):
        e = 8 + i * 36
        if e + 36 > len(payload):
            break
        if payload[e] == 1 and any(payload[e + 4:e + 36]):
            return True
    return False


def default_selected(block, include_state=False):
    """Що застосовувати типово: налаштування й дані; НЕ стан (RCTL_STATE), НЕ блок із ключовим матеріалом і НЕ вилучений блок (R35)."""
    if is_retired(block.type):
        return False
    if block.kind == "state" and not include_state:
        return False
    if block.secret:
        return False
    return True


def blocks_text(blocks):
    return ", ".join("%s (%d Б)" % (b.title, b.length) for b in blocks) if blocks else "жодного"


# =========================================================================================
#  Маніфест бекапу
# =========================================================================================

def manifest_part(data):
    """Запис для manifest["parts"]["customData"]. `restorable` -- у сенсі cps_restore (він цю частину не відновлює); область відновлює restore_region."""
    reg = parse_region(data)
    part = {
        "file": PART_FILE, "area": cl.CPS_ACCESS_FLASH, "start": REGION_RAW_START, "length": len(data), "sha256": sha256(data),
        "restorable": False, "restoredBy": "custom_region.restore_region (окремий прапорець, типово вимкнено)",
        "magicOk": reg.magic_ok,
        "blocks": [{"type": b.type, "name": b.name, "offset": b.offset, "length": b.length, "sha256": sha256(b.payload),
                    **({"secret": True} if b.secret else {})} for b in reg.blocks],
    }
    if reg.problems:
        part["problems"] = list(reg.problems)
    return part


def read_backup_region(source):
    """Область з .zip бекапу (шлях або байти) -> bytes, або None, якщо архів її не містить (старий бекап до R30). SHA-256 і довжину звіряє
    cps_link.read_backup_zip; тут -- ще раз і межі. CpsError, якщо файл пошкоджено."""
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
        raise cl.CpsError("область custom-data в бекапі пошкоджена (довжина або SHA-256 не збігаються з маніфестом)")
    if part.get("start") != REGION_RAW_START or len(data) != REGION_LEN:
        raise cl.CpsError("область custom-data в бекапі описує інший діапазон (початок 0x%X, довжина %d), ніж відомий цій прошивці (0x%X, %d). "
                          "Записувати поза відомою областю заборонено." % (part.get("start") or 0, len(data), REGION_RAW_START, REGION_LEN))
    return data


def read_radio_region(link, progress=None):
    """Прочитати область з рації (лише читання)."""
    return link.read(cl.CPS_ACCESS_FLASH, REGION_RAW_START, REGION_LEN, progress)


# =========================================================================================
#  План і симуляція запису (чиста логіка на байтах; дзеркало custom_data.find_or_alloc_block)
# =========================================================================================

def _find_slot(buf, type_, new_len):
    """(kind, addr, existLen) як у custom_data.find_or_alloc_block, але над байтами області."""
    if bytes(buf[:8]) != MAGIC:
        return (None, None, None)
    addr = REGION_HDR
    while addr < REGION_LEN:
        if addr + BLOCK_HDR > REGION_LEN:
            return (None, None, None)
        dtype, dlen = struct.unpack("<ii", bytes(buf[addr:addr + BLOCK_HDR]))
        if dtype == type_:
            return ("existing", addr, dlen)
        if dlen == 0 or dlen == TYPE_EMPTY:
            if (addr + BLOCK_HDR + new_len) < REGION_LEN:
                return ("empty", addr, None)
            return (None, None, None)
        addr += BLOCK_HDR + dlen
    return (None, None, None)


def simulate_write(buf, type_, payload):
    """Застосувати запис блока до bytearray області так само, як custom_data.write_block. Повертає (True, kind) або (False, причина)."""
    kind, addr, exist = _find_slot(buf, type_, len(payload))
    if kind is None:
        if bytes(buf[:8]) == MAGIC:
            import custom_compact as cc          # R37: область є -- значить, не вистачає місця: пояснити числами й підказати ущільнення
            return False, cc.room_check(bytes(buf), type_, len(payload)).text + " Розділ «Усі налаштування» -> «Ущільнити область» прибирає вилучені блоки."
        return False, "області OpenGD77 нема"
    if kind == "existing" and exist != len(payload):
        return False, "блок уже є, але має іншу довжину (%d, а не %d) -- довжину наявного блока міняти не можна" % (exist, len(payload))
    buf[addr:addr + BLOCK_HDR + len(payload)] = struct.pack("<ii", type_, len(payload)) + payload
    return True, kind


ST_SAME = "same"            # у рації вже такий самий вміст -- не пишемо
ST_OVERWRITE = "overwrite"  # блок є, вміст відрізняється -- буде перезаписано
ST_CREATE = "create"        # блока в рації нема -- буде створено у вільному слоті
ST_REFUSED = "refused"      # записати не можна (інша довжина / нема місця) -- причина в note
ST_SKIPPED = "skipped"      # не обрано (або типово не застосовується)

STATUS_TEXT = {ST_SAME: "без змін (вже такий самий)", ST_OVERWRITE: "буде перезаписано", ST_CREATE: "буде створено",
               ST_REFUSED: "записати не можна", ST_SKIPPED: "пропущено"}


class PlanItem:
    def __init__(self, block, status, note=""):
        self.block = block
        self.status = status
        self.note = note

    @property
    def writes(self):
        return self.status in (ST_OVERWRITE, ST_CREATE)


class Plan:
    def __init__(self, items, header_needed, problems, cur_data=None):
        self.cur_data = cur_data                # R73: байти області рації, на яких побудовано план (для групування записів по секторах)
        self.items = items
        self.header_needed = header_needed      # поточна область стерта (усі 0xFF): спершу буде записано 12-байтовий заголовок
        self.problems = problems

    def writes(self):
        return [i for i in self.items if i.writes]

    def refused(self):
        return [i for i in self.items if i.status == ST_REFUSED]

    def text(self):
        lines = []
        for i in self.items:
            line = "  %s -- %s" % (i.block.title, STATUS_TEXT[i.status])
            if i.note:
                line += ": " + i.note
            lines.append(line)
        return "\n".join(lines)


def plan_restore(src_region, cur_region, selected=None, include_state=False):
    """План застосування блоків `src_region` (bytes області з бекапу/файла) до поточної області рації `cur_region`.
    selected -- множина типів, які користувач обрав (None -- типові: default_selected). Нічого не пише."""
    src = parse_region(src_region)
    cur = parse_region(cur_region)
    problems = list(src.problems)
    if not src.magic_ok:
        raise RegionError("область custom-data в джерелі не в форматі OpenGD77 -- відновлювати нічого. %s" % "; ".join(src.problems))
    return plan_blocks(src.blocks, cur, selected, include_state, problems)


def plan_blocks(blocks, cur, selected=None, include_state=False, problems=()):
    """Те саме, але джерело -- готовий список Block. cur -- Region поточної області."""
    header_needed = (not cur.magic_ok) and cur.erased
    if not cur.magic_ok and not cur.erased:
        raise RegionError("область custom-data у рації не стерта й без заголовка OpenGD77 (%s) -- нічого не записано." % "; ".join(cur.problems))
    work = bytearray(cur.data)
    if header_needed:
        work[:REGION_HDR] = MAGIC + b"\x00" * 4
    curtypes = cur.by_type()
    items = []
    for b in blocks:
        want = (b.type in selected) if selected is not None else default_selected(b, include_state)
        if not want:
            items.append(PlanItem(b, ST_SKIPPED))
            continue
        have = curtypes.get(b.type)
        if have is not None and have.payload == b.payload:
            items.append(PlanItem(b, ST_SAME))
            continue
        ok, info = simulate_write(work, b.type, b.payload)
        if not ok:
            items.append(PlanItem(b, ST_REFUSED, info))
            continue
        items.append(PlanItem(b, ST_CREATE if info == "empty" else ST_OVERWRITE))
    return Plan(items, header_needed, list(problems), bytes(cur.data))


def expected_region(cur_region, plan):
    """Область, яка має вийти після виконання плану (для підсумкової звірки)."""
    work = bytearray(cur_region)
    if plan.header_needed:
        work[:REGION_HDR] = MAGIC + b"\x00" * 4
    for it in plan.writes():
        simulate_write(work, it.block.type, it.block.payload)
    return bytes(work)


# =========================================================================================
#  Запис блок за блоком
# =========================================================================================

def apply_plan(link, plan, log=print, progress=None):
    """Виконати план. R73: коли план знає поточну область (plan.cur_data), блоки, що лежать в ОДНОМУ 4-КіБ секторі, пишуться ОДНИМ записом сектора
    (одне стирання) замість «блок за блоком = стирання на кожен». Порядок безпеки: заголовок області (якщо область стерта) -- у першій групі; групи йдуть по черзі;
    перший збій групи зупиняє решту. Перед першим записом кожне місце блока звіряється з рацією (заголовок за планованою адресою = той, що в плані): якщо область
    змінилась після читання -- нічого не записано. Після запису групи -- звірка кожного блока читанням. Повертає {written, unchanged, failed, untouched, headerWritten, refused};
    жодних винятків за збій запису."""
    if plan.cur_data is None or len(plan.cur_data) != REGION_LEN:
        return _apply_plan_per_block(link, plan, log, progress)
    import custom_data as cd
    import flash_guard as fg
    import phase_timing
    ser = link.ser
    res = {"written": [], "unchanged": [i.block for i in plan.items if i.status == ST_SAME], "failed": None, "untouched": [], "headerWritten": False,
           "refused": [i for i in plan.items if i.status == ST_REFUSED]}
    todo = plan.writes()
    if not todo:
        return res
    work = bytearray(plan.cur_data)
    patches = []            # [(абсолютна адреса, байти, блок або None, підпис)]
    if plan.header_needed:
        work[:REGION_HDR] = MAGIC + b"\x00" * 4
        patches.append((cd.FLASH_BASE, MAGIC + b"\x00" * 4, None, "заголовок області"))
    for it in todo:
        b = it.block
        kind, addr, _e = _find_slot(work, b.type, len(b.payload))
        ok, info = simulate_write(work, b.type, b.payload)
        if not ok or kind is None:
            res["failed"] = {"block": b, "message": str(info)}
            res["untouched"] = [i.block for i in todo]
            return res
        patches.append((cd.FLASH_BASE + addr, struct.pack("<ii", b.type, len(b.payload)) + b.payload, b, "оновлено існуючий блок @+%d" % addr if kind == "existing" else "створено новий блок @+%d" % addr))
    # область не змінилась після читання? (місце кожного блока: заголовок у рації = заголовок у плані)
    for a, _d, b, _m in patches:
        if b is None:
            continue
        live = cd._read_region(ser, a - cd.FLASH_BASE, cd.HDR_LEN)
        if bytes(live) != bytes(plan.cur_data[a - cd.FLASH_BASE:a - cd.FLASH_BASE + cd.HDR_LEN]):
            res["failed"] = {"block": b, "message": "область custom-data в рації змінилась після того, як її було прочитано для плану -- нічого не записано; повтори дію"}
            res["untouched"] = [i.block for i in todo]
            return res
    groups = {}
    for p_ in patches:
        groups.setdefault((p_[0] - 0) // fg.SECTOR, []).append(p_)
    order = list(groups.values())
    ph = phase_timing.Phases(link)
    nblocks = len(todo)
    done_blocks = 0
    for k, grp in enumerate(order):
        blocks = [p_[2] for p_ in grp if p_[2] is not None]
        if progress:
            progress(int(100.0 * k / max(1, len(order))), "Пишу блоки %d з %d: %s" % (done_blocks + 1, nblocks, ", ".join(x.title for x in blocks) or "заголовок області"))
        later = [x for g in order[k + 1:] for x in (p_[2] for p_ in g) if x is not None]
        try:
            with ph.phase("запис сектора (%d ділянок)" % len(grp)):
                fg.write_group(ser, [(p_[0], p_[1]) for p_ in grp], "customdata")
        except Exception as e:  # noqa: BLE001
            # частина секторів групи могла встигнути записатись (блок, що перетинає межу сектора): що саме є в рації -- показує читання
            bad = None
            for a, d, b, msg in grp:
                if b is None:
                    continue
                try:
                    ok_ = bytes(cd._read_region(ser, a - cd.FLASH_BASE, len(d))) == bytes(d)
                except Exception:  # noqa: BLE001
                    ok_ = False
                if ok_ and bad is None:
                    log("Блок «%s» (%d Б): уже записаний (збій стався пізніше), звірено." % (b.title, b.length))
                    res["written"].append(b)
                elif bad is None:
                    bad = b
            res["failed"] = {"block": bad or (blocks[0] if blocks else None), "message": "%s (сектор пишеться одним записом; стан блоків, що не збіглися з планом, невідомий: %s)" % (
                e, ", ".join(x.title for x in blocks if x not in res["written"]) or "лише заголовок")}
            res["untouched"] = later
            return res
        if any(p_[2] is None for p_ in grp):
            res["headerWritten"] = True
            log("Область custom-data у рації стерта -- записано заголовок OpenGD77 (12 байтів).")
        for a, d, b, msg in grp:
            if b is None:
                continue
            with ph.phase("звірка «%s»" % b.title):
                back = cd._read_region(ser, a - cd.FLASH_BASE, len(d))
            if bytes(back) != bytes(d):
                res["failed"] = {"block": b, "message": "після запису блок читається інакше, ніж записано (звірка не пройшла)"}
                res["untouched"] = later
                return res
            log("Блок «%s» (%d Б): %s, звірено." % (b.title, b.length, msg))
            res["written"].append(b)
            done_blocks += 1
    if progress:
        progress(100, "Готово")
    if ph.items:
        log(ph.summary())
    return res


def _apply_plan_per_block(link, plan, log=print, progress=None):
    """Виконати план: (за потреби) заголовок області, далі кожен блок окремо через custom_data.write_block + звірка читанням.
    Збій зупиняє решту. Повертає словник {written, unchanged, failed, untouched, headerWritten}; жодних винятків за збій запису."""
    import custom_data as cd
    ser = link.ser
    res = {"written": [], "unchanged": [i.block for i in plan.items if i.status == ST_SAME], "failed": None, "untouched": [], "headerWritten": False,
           "refused": [i for i in plan.items if i.status == ST_REFUSED]}
    todo = plan.writes()
    if plan.header_needed and todo:
        log("Область custom-data у рації стерта -- пишу заголовок OpenGD77 (12 байтів).")
        try:
            cd.flash_write_span(ser, cd.FLASH_BASE, MAGIC + b"\x00" * 4)
        except Exception as e:  # noqa: BLE001
            res["failed"] = {"block": None, "message": "заголовок області: %s" % e}
            res["untouched"] = [i.block for i in todo]
            return res
        res["headerWritten"] = True
    for k, it in enumerate(todo):
        b = it.block
        if progress:
            progress(int(100.0 * k / max(1, len(todo))), "Пишу блок %d з %d: %s" % (k + 1, len(todo), b.title))
        try:
            ok, msg = cd.write_block(ser, b.type, b.payload)
            if not ok:
                raise RuntimeError(msg)
            back = cd.read_block(ser, b.type, b.length)
            if back != b.payload:
                raise RuntimeError("після запису блок читається інакше, ніж записано (звірка не пройшла)")
        except Exception as e:  # noqa: BLE001
            res["failed"] = {"block": b, "message": str(e)}
            res["untouched"] = [i.block for i in todo[k + 1:]]
            return res
        log("Блок «%s» (%d Б): %s, звірено." % (b.title, b.length, msg))
        res["written"].append(b)
    if progress:
        progress(100, "Готово")
    return res


def result_text(res):
    """Підсумок словами (українською)."""
    lines = []
    if res["written"]:
        lines.append("Записано й звірено: %s." % blocks_text(res["written"]))
    if res["unchanged"]:
        lines.append("Без змін (у рації вже такі): %s." % blocks_text(res["unchanged"]))
    if res.get("refused"):
        lines.append("Не можна було записати: " + "; ".join("%s -- %s" % (i.block.title, i.note) for i in res["refused"]) + ".")
    f = res["failed"]
    if f:
        name = f["block"].title if f["block"] is not None else "заголовок області"
        lines.append("ПОМИЛКА на «%s»: %s." % (name, f["message"]))
        if f["block"] is not None:
            lines.append("Цей блок міг лишитися записаним частково або старим -- перевір його в рації.")
        if res["written"]:
            lines.append("Блоки до помилки ЗАПИСАНІ й залишаються записаними.")
        if res["untouched"]:
            lines.append("Не торкався (лишились такими, як були): %s." % blocks_text(res["untouched"]))
    elif not res["written"] and not res["unchanged"] and not res.get("refused"):
        lines.append("Нічого не обрано -- область рації не змінено.")
    return "\n".join(lines)


# =========================================================================================
#  Відновлення області з бекапу
# =========================================================================================

def confirm_text(plan, source_name, include_state):
    lines = ["Відновити область custom-data рації з %s." % source_name, "",
             "Область рації НЕ входить у відновлення кодплага; це окремий крок. Буде так:", plan.text(), ""]
    if not include_state:
        lines.append("Лічильники RCTL (стан, не налаштування) типово НЕ застосовуються. Блок AES із ключовим матеріалом (якщо є) теж пропускається.")
    lines += ["Блоки пишуться ПО ОДНОМУ зі звіркою читанням; якщо один не запишеться, решта лишається як була.",
              "Перед записом поточна область рації зберігається окремим файлом поруч із бекапом."]
    return "\n".join(lines)


def restore_region(link, source, confirm, selected=None, include_state=False, progress=None, log=print, now=None, post_reset=True,
                   source_name=None, safety_dir=None):
    """Відновити область custom-data рації з .zip бекапу (`source` -- шлях). confirm(text, plan) -> bool викликається ПІСЛЯ перевірок і страхової копії,
    ПЕРЕД першим записом. Повертає словник: absent (архів без області -- рацію не чіпали), cancelled, nothingToDo, result (apply_plan), text, safetyCopy."""
    def prog(p, t):
        if progress:
            progress(max(0, min(100, int(p))), t)

    prog(0, "Читаю область з бекапу...")
    src = read_backup_region(source)
    if src is None:
        text = "У цьому бекапі області custom-data нема (архів створено до R30) -- область рації не чіпав."
        log(text)
        return {"absent": True, "cancelled": False, "nothingToDo": True, "text": text}
    prog(5, "Читаю область з рації...")
    cur = read_radio_region(link)
    plan = plan_restore(src, cur, selected, include_state)
    d = safety_dir or (os.path.dirname(os.path.abspath(source)) if isinstance(source, (str, os.PathLike)) else os.getcwd())
    if not plan.writes() and not plan.refused():
        text = "Область custom-data рації вже містить усе обране з бекапу -- записувати нічого."
        log(text)
        return {"absent": False, "cancelled": False, "nothingToDo": True, "text": text, "plan": plan}
    if not os.access(d, os.W_OK):
        raise RegionError("нема права писати в теку %s, де має лежати страхова копія області. Нічого не записано." % d)
    safety = cl.unique_path(d, cl.timestamp_name("customdata_pre-restore", ".bin", now))
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
        raise RegionError("не вдалося зберегти страхову копію області (%s). Нічого не записано." % e)
    log("Страхова копія області збережена й перевірена: %s" % safety)
    name = source_name or (os.path.basename(source) if isinstance(source, (str, os.PathLike)) else "бекапу")
    if not confirm(confirm_text(plan, name, include_state), plan):
        log("Скасовано користувачем; область рації не змінено.")
        return {"absent": False, "cancelled": True, "nothingToDo": False, "text": "Скасовано; область рації не змінено.", "plan": plan,
                "safetyCopy": safety}
    res = apply_plan(link, plan, log, lambda p, t: prog(10 + 0.85 * p, t))
    text = result_text(res)
    matches = None
    if not res["failed"]:
        after = read_radio_region(link)
        matches = after == expected_region(cur, plan)
        if not matches:
            text += "\nУВАГА: після запису область у рації не збігається з очікуваною (поза записаними блоками щось відрізняється). Страхова копія: %s" % safety
    if post_reset and res["written"]:
        import cps_restore
        prog(97, "Перезавантажую рацію...")
        cps_restore._send_c(link, 6, cps_restore.POST_RESTORE_SUB)
    prog(100, "Готово")
    return {"absent": False, "cancelled": False, "nothingToDo": False, "text": text, "plan": plan, "result": res, "safetyCopy": safety,
            "regionMatchesExpected": matches}


def restore_codeplug_and_region(link, zip_path, confirm, progress=None, log=print, with_region=False, include_state=False, now=None):
    """Відновити кодплаг (як завжди: cps_restore.restore_codeplug) і, якщо `with_region`, ПІСЛЯ нього -- область custom-data (окремий прапорець,
    типово вимкнено). Перезавантаження рації робиться один раз у кінці, а не всередині restore_codeplug (post_reset=False), щоб рація не пішла
    на перезавантаження між двома кроками. Повертає {"codeplug": підсумок restore_codeplug, "region": підсумок restore_region або None}.
    Якщо відновлення кодплага скасоване, область не чіпається."""
    import cps_restore
    out = {"codeplug": None, "region": None}
    cp = cps_restore.restore_codeplug(link, zip_path, confirm, progress, log=log, now=now, post_reset=not with_region)
    out["codeplug"] = cp
    if not with_region or cp.get("cancelled"):
        return out
    wrote_cp = not cp.get("nothingToDo")
    try:
        out["region"] = restore_region(link, zip_path, confirm, include_state=include_state, progress=progress, log=log, now=now, post_reset=False)
    finally:
        reg = out["region"]
        if wrote_cp or (reg and reg.get("result") and reg["result"]["written"]):
            cps_restore._send_c(link, 6, cps_restore.POST_RESTORE_SUB)
    return out


# =========================================================================================
#  Файл налаштувань (усі блоки області в одному файлі)
# =========================================================================================

def settings_to_text(blocks, radio_info=None, now_utc=None):
    """Блоки -> текст файла (JSON). Детермінований для тих самих блоків і часу."""
    now_utc = now_utc or datetime.datetime.now(datetime.timezone.utc)
    doc = {
        "format": SETTINGS_FORMAT,
        "createdUtc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "radio": dict(radio_info) if radio_info else None,
        "note": ("Налаштування з області custom-data рації OpenTYT (теми, SMS, RCTL, APRS, вибір ключа AES). "
                 "Лічильники RCTL (RCTL_STATE) -- стан, а не налаштування: типово не застосовуються. "
                 + ("УВАГА: у файлі є ключовий матеріал AES -- зберігай його як секрет. " if any(b.secret for b in blocks) else "")
                 + "Повідомлення SMS містять особисті тексти."),
        "containsSecrets": any(b.secret for b in blocks),
        "blocks": [{"type": b.type, "name": b.name, "title": b.title, "length": b.length, "sha256": sha256(b.payload), "hex": b.payload.hex()}
                   for b in blocks],
    }
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def settings_from_text(text):
    """Текст файла -> (список Block, словник-документ). SettingsFileError з поясненням словами."""
    try:
        doc = json.loads(text.lstrip("﻿"))
    except ValueError as e:
        raise SettingsFileError("це не файл налаштувань (не JSON): %s" % e)
    if not isinstance(doc, dict) or doc.get("format") != SETTINGS_FORMAT:
        raise SettingsFileError("це не файл налаштувань OpenTYT (очікується format = %s)" % SETTINGS_FORMAT)
    items = doc.get("blocks")
    if not isinstance(items, list):
        raise SettingsFileError("у файлі немає списку блоків")
    out = []
    seen = set()
    for n, it in enumerate(items, 1):
        try:
            t = int(it["type"])
            payload = bytes.fromhex(it["hex"])
            want_len = int(it["length"])
            want_sha = it["sha256"]
        except (KeyError, TypeError, ValueError) as e:
            raise SettingsFileError("блок %d у файлі пошкоджено (%s)" % (n, e))
        if len(payload) != want_len or sha256(payload) != want_sha:
            raise SettingsFileError("блок %d (%s): довжина або SHA-256 не збігаються -- файл пошкоджено" % (n, type_name(t)))
        if t in seen:
            raise SettingsFileError("блок типу %d у файлі двічі" % t)
        if t < 1 or len(payload) == 0 or REGION_HDR + BLOCK_HDR + len(payload) >= REGION_LEN:
            raise SettingsFileError("блок %d (тип %d, довжина %d) не може лежати в області" % (n, t, len(payload)))
        seen.add(t)
        out.append(Block(t, 0, payload))
    return out, doc


def save_settings_file(path, blocks, radio_info=None, now_utc=None):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(settings_to_text(blocks, radio_info, now_utc))


def load_settings_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return settings_from_text(f.read())
    except UnicodeDecodeError:
        raise SettingsFileError("файл не в кодуванні UTF-8")
    except OSError as e:
        raise SettingsFileError("не вдалося прочитати файл: %s" % e)


def read_settings_from_radio(link, progress=None):
    """Прочитати область з рації й повернути (список Block, Region). Лише читання."""
    region = parse_region(read_radio_region(link, progress))
    if not region.magic_ok:
        raise RegionError("у рації немає області налаштувань OpenGD77 (%s) -- зберігати нічого." % "; ".join(region.problems))
    return region.blocks, region


def apply_settings(link, blocks, selected, include_state=False, confirm=None, progress=None, log=print, post_reset=True):
    """Застосувати обрані блоки з файла до рації (той самий рушій, що й відновлення області). confirm(text, plan) -> bool, якщо задано.
    Повертає словник як restore_region (без страхового файла: перед цим GUI радить зробити бекап). Після запису рація перезавантажується
    (`C 6 1`, без збереження пам'яті), інакше прошивка могла б при першій же події записати поверх свою копію з ОЗП (SMS-сховище, теми)."""
    cur = read_radio_region(link)
    plan = plan_blocks(blocks, parse_region(cur), selected, include_state)
    if not plan.writes() and not plan.refused():
        text = "У рації вже все обране з файла -- записувати нічого."
        return {"cancelled": False, "nothingToDo": True, "text": text, "plan": plan}
    if confirm is not None and not confirm(confirm_text(plan, "файла налаштувань", include_state), plan):
        return {"cancelled": True, "nothingToDo": False, "text": "Скасовано; область рації не змінено.", "plan": plan}
    res = apply_plan(link, plan, log, progress)
    text = result_text(res)
    matches = None
    if not res["failed"]:
        matches = read_radio_region(link) == expected_region(cur, plan)
        if not matches:
            text += "\nУВАГА: після запису область у рації не збігається з очікуваною."
    if post_reset and res["written"]:
        import cps_restore
        cps_restore._send_c(link, 6, cps_restore.POST_RESTORE_SUB)
        text += "\nРація перезавантажується."
    return {"cancelled": False, "nothingToDo": False, "text": text, "plan": plan, "result": res, "regionMatchesExpected": matches}
