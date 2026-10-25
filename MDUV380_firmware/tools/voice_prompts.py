# -*- coding: utf-8 -*-
"""R35, частина D: голосові підказки (область SPI-флеша 0xAF400..0xD7FFF).

ФОРМАТ -- ЛИШЕ З КОДУ ПРОШИВКИ (functions/voicePrompts.c, include/functions/voicePrompts.h, usb/usb_com.c, user_interface/uiUtilities.c):

  Адреса       VOICE_PROMPTS_FLASH_HEADER_ADDRESS = 0x8F400 + FLASH_ADDRESS_OFFSET(0x20000) = 0xAF400.
               Є ще «стара» адреса 0xE0000 + 0x20000 = 0x100000 (voicePromptsCacheInit пробує її, якщо за новою заголовка нема) -- поза нашою областю; НЕ чіпаємо.
  Заголовок    8 Б: uint32 magic = 0x5056 ('VP'), uint32 version. Версія в цій збірці (HAS_COLOURS, MDUV380) = 9, TOC = 368 записів
               (для монохромних збірок -- 8 і 331). voicePromptsCheckMagicAndVersion вимагає точного збігу обох.
  TOC          368 x uint32 -- зміщення фраз ВІД початку даних (= 0xAF400 + 8 + 4*368 = 0xAF9C8). Довжина фрази i = toc[i+1] - toc[i]; тож toc[368-1] -- «кінець
               даних» останньої фрази. Нульове зміщення (крім фрази 0) або нульове наступне -- фрази нема, програється PROMPT_SILENCE.
  Дані         послідовно фрази; у коментарі прошивки: «76 x 27 byte ambe frames», буфер однієї фрази AMBE_DATA_BUFFER_SIZE = 2052 Б (фраза довша не читається).
               Тобто звук -- кадри кодека AMBE+2 по 27 Б, які рація подає в голосовий кодек HR-C6000 (voicePromptsTick) -- НЕ PCM.
  Адресація    voicePromptsAppendPrompt(номер): 0..86 -- фіксовані фрази voicePrompt_t, 87+k -- k-й рядок мови (зміщення поля у stringsTable_t / 17), див. vp_names.py.
  Межі         від 0xAF400 до початку області №2 бази позивних 0xD8000 (DMRID_MEMORY_LOCATION_2 = 0xB8000 + 0x20000); верхньої межі в самих підказках код не задає.
  Конфлікт     у режимі бази 'n' область №2 бази починається з VOICE_PROMPTS_FLASH_HEADER_ADDRESS (uiUtilities.c: dmrIDDatabaseMemoryLocation2 = ...; «overwrite the VP»):
               записи бази, що не влізли в область №1, лягають ПОВЕРХ підказок.
  USB-хак      usb_com.c: ЗАПИС по адресі заголовка підказок з правильним magic/version, що прийшов командою запису флеша ('W'), вмикає режим підказок рівня 1.
               Наш запис іде командами 'X' (сектор за сектором), цей хак не спрацьовує -- режим підказок вмикається в меню рації.

Створення власних підказок -- ПОЗА цим модулем: звук лежить у стиснутому кодеку рації (AMBE+2, 27-байтні кадри), для нього потрібен кодувальник; це окрема робота.
Модуль: розбір і перевірка образу, перелік фраз, читання/запис/стирання області з рації (страхова копія, порядок «заголовок обнулити -> дані -> заголовок»)."""
import os
import random
import struct

import cps_link as cl
import flash_guard as fg

import vp_names

VP_START = 0xAF400
VP_END = 0xD8000                                     # початок області №2 бази позивних
VP_MAX = VP_END - VP_START
MAGIC = 0x5056
VERSION = 9                                          # HAS_COLOURS
TOC_SIZE = 368
HDR_LEN = 8
TOC_LEN = 4 * TOC_SIZE
DATA_BASE = HDR_LEN + TOC_LEN                        # 1480
AMBE_FRAME = 27
AMBE_BUFFER = 2052                                   # AMBE_DATA_BUFFER_SIZE
SECTOR = 4096


class VpError(ValueError):
    """Образ підказок/стан області неприпустимий (пояснення словами)."""


class Cancelled(Exception):
    """Користувач скасував запис на межі сектора."""


class Info:
    def __init__(self):
        self.magic_ok = False
        self.version = None
        self.toc = []
        self.extent = 0                  # байтів даних після TOC (= max(toc))
        self.problems = []               # з цим образом записувати не можна
        self.warnings = []
        self.present = 0                 # скільки фраз реально є

    @property
    def total(self):
        """Довжина всього образу: заголовок + TOC + дані."""
        return DATA_BASE + self.extent

    @property
    def valid(self):
        return self.magic_ok and not self.problems


def parse_head(head):
    """Розбір перших DATA_BASE байтів (заголовок + TOC)."""
    info = Info()
    head = bytes(head)
    if len(head) < HDR_LEN:
        info.problems.append("образ коротший за заголовок")
        return info
    magic, version = struct.unpack("<II", head[:8])
    info.version = version
    info.magic_ok = magic == MAGIC
    if not info.magic_ok:
        info.problems.append("це не область голосових підказок: на початку 0x%X, а має бути 0x%X ('VP')" % (magic, MAGIC))
        return info
    if version != VERSION:
        info.problems.append("версія підказок %d, а ця збірка (кольоровий екран) приймає лише %d -- рація такі підказки не завантажить" % (version, VERSION))
    if len(head) < DATA_BASE:
        info.problems.append("образ коротший за заголовок і таблицю змісту (%d Б)" % DATA_BASE)
        return info
    info.toc = list(struct.unpack("<%dI" % TOC_SIZE, head[HDR_LEN:DATA_BASE]))
    prev = None
    for i, v in enumerate(info.toc):
        if v == 0 and i != 0:
            continue
        if prev is not None and v < prev[1]:
            info.problems.append("таблиця змісту не зростає: запис %d (%d) менший за запис %d (%d) -- довжину фрази не можна обчислити" % (i, v, prev[0], prev[1]))
            break
        prev = (i, v)
    info.extent = max(info.toc) if info.toc else 0
    if info.extent > VP_MAX - DATA_BASE:
        info.problems.append("дані (%d Б) виходять за область підказок 0x%X..0x%X (вміщується %d Б)" % (info.extent, VP_START, VP_END, VP_MAX - DATA_BASE))
    info.present = sum(1 for r in rows(info) if r["length"] > 0)
    if not info.present and not info.problems:
        info.warnings.append("жодної фрази в таблиці змісту нема")
    return info


def parse_image(image):
    """Повний образ -> Info; додатково перевіряє, що образ не коротший за те, що заявляє TOC."""
    info = parse_head(image[:DATA_BASE])
    if info.valid and len(image) < info.total:
        info.problems.append("образ обірваний: TOC заявляє %d Б, є %d" % (info.total, len(image)))
    if info.valid and len(image) > info.total:
        info.warnings.append("після кінця даних у файлі зайві %d Б -- вони не записуються" % (len(image) - info.total))
    return info


def prompt_label(i):
    if i < vp_names.NUM_VOICE_PROMPTS:
        return vp_names.PROMPT_NAMES[i]
    k = i - vp_names.NUM_VOICE_PROMPTS
    if k < len(vp_names.LANG_FIELDS):
        return "рядок мови: " + vp_names.LANG_FIELDS[k]
    return "рядок мови №%d (поза стоковою структурою)" % k


def rows(info):
    """Перелік фраз: [{index, label, offset, length, frames, remainder, silent, oversize}] -- за кодом voicePromptsPlay."""
    out = []
    if not info.toc:
        return out
    for i in range(TOC_SIZE - 1):
        off, nxt = info.toc[i], info.toc[i + 1]
        absent = (nxt == 0) or (off == 0)                 # voicePromptsPlay: tableOfContents[n+1] == 0 || tableOfContents[n] == 0 -> фраза мовчить (і №0 теж)
        ln = 0 if absent or nxt < off else nxt - off
        out.append({"index": i, "label": prompt_label(i), "offset": off, "length": ln, "frames": ln // AMBE_FRAME, "remainder": ln % AMBE_FRAME,
                    "silent": absent, "oversize": ln > AMBE_BUFFER})
    return out


def summary_text(info):
    """Короткий текст про образ."""
    if not info.magic_ok:
        return "Голосових підказок нема (заголовок не 'VP')."
    rs = rows(info)
    present = [r for r in rs if r["length"] > 0]
    odd = [r for r in present if r["remainder"]]
    big = [r for r in present if r["oversize"]]
    lines = ["Версія %s%s. Фраз у таблиці: %d з %d; даних %d Б (разом з таблицею %d Б)." % (
        info.version, "" if info.version == VERSION else " (рація приймає лише %d)" % VERSION, len(present), TOC_SIZE - 1, info.extent, info.total)]
    if present:
        lines.append("Найкоротша фраза %d Б, найдовша %d Б (буфер рації для однієї фрази %d Б)." % (min(r["length"] for r in present), max(r["length"] for r in present), AMBE_BUFFER))
    if odd:
        lines.append("Довжина %d фраз не кратна кадру AMBE (%d Б) -- приклад: №%d (%d Б)." % (len(odd), AMBE_FRAME, odd[0]["index"], odd[0]["length"]))
    if big:
        lines.append("УВАГА: %d фраз довші за буфер рації (%d Б) -- рація їх не читає." % (len(big), AMBE_BUFFER))
    for p in info.problems:
        lines.append("ПРОБЛЕМА: " + p)
    for w in info.warnings:
        lines.append("Зауваження: " + w)
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------------------------------------------
#  Конфлікт з базою позивних (D5)
# ---------------------------------------------------------------------------------------------------------------------------------

def db_conflict(link):
    """Чи бази позивних 'n' затирає підказки. Повертає (рівень, текст): рівень "none" -- конфлікту нема; "warn" -- режим 'n', але база вміщується в область №1
    (підказки цілі); "clobbered" -- база виходить за область №1 й лягла поверх підказок."""
    import dmr_db
    h = dmr_db.read_radio_header(link)
    if h.mode != "n":
        return "none", ""
    extent = h.extent
    over = extent - dmr_db.AREA1_LEN
    if over > 0:
        return "clobbered", ("База позивних у режимі 'n' виходить за область №1 на %d Б, і ці байти лежать від 0x%X -- ПОВЕРХ голосових підказок. "
                             "Підказки в рації затерті; записувати їх сюди не можна, доки база в такому режимі." % (over, VP_START))
    return "warn", ("База позивних у режимі 'n' (область №2 = місце підказок), але вміщується в область №1 (%d Б із %d): підказки поки цілі. "
                    "Якщо базу збільшити, вона затре підказки." % (extent, dmr_db.AREA1_LEN))


# ---------------------------------------------------------------------------------------------------------------------------------
#  Рація
# ---------------------------------------------------------------------------------------------------------------------------------

def read_info(link):
    """Заголовок + TOC з рації -> Info."""
    return parse_head(link.read(cl.CPS_ACCESS_FLASH, VP_START, DATA_BASE))


def read_image(link, progress=None):
    """Весь образ підказок з рації. VpError, якщо підказок нема або TOC суперечливий."""
    info = read_info(link)
    if not info.magic_ok:
        raise VpError("у рації голосових підказок нема: " + (info.problems[0] if info.problems else "заголовок не 'VP'"))
    if info.problems:
        raise VpError("область підказок у рації пошкоджена або не тієї версії: " + "; ".join(info.problems))
    return link.read(cl.CPS_ACCESS_FLASH, VP_START, info.total, progress)


def _safety_copy(link, n, safety_dir, now, log, progress=None):
    import datetime
    old = link.read(cl.CPS_ACCESS_FLASH, VP_START, n, progress)
    d = safety_dir or os.getcwd()
    if not os.access(d, os.W_OK):
        raise VpError("нема права писати в теку %s, де має лежати страхова копія підказок. Нічого не записано." % d)
    ts = (now or datetime.datetime.now()).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(d, "voiceprompts_pre-write_%s.bin" % ts)
    k = 1
    while os.path.exists(path):
        k += 1
        path = os.path.join(d, "voiceprompts_pre-write_%s_%d.bin" % (ts, k))
    with open(path, "xb") as f:
        f.write(old)
    with open(path, "rb") as f:
        if f.read() != old:
            os.unlink(path)
            raise VpError("страхову копію підказок не вдалося перевірити -- нічого не записано")
    log("Страхова копія області підказок збережена й перевірена: %s" % path)
    return old, path


def plan_text(new, old, conflict_text):
    lines = ["Записати голосові підказки в область SPI 0x%X..0x%X:" % (VP_START, VP_START + new.total - 1),
             "  новий образ: версія %s, фраз %d, разом %d Б." % (new.version, new.present, new.total)]
    if old.magic_ok and not old.problems:
        lines.append("  зараз у рації: версія %s, фраз %d, разом %d Б." % (old.version, old.present, old.total))
    else:
        lines.append("  зараз у рації придатних підказок нема.")
    if conflict_text:
        lines.append("  " + conflict_text)
    lines += ["", "Порядок: спершу заголовок підказок у рації обнуляється (рація перестає їх бачити), далі пишуться дані, заголовок -- останнім.",
              "Якщо запис обірвати, підказок у рації не буде (рація перейде на звичайні звуки), але нічого іншого не зіпсовано; стара область збережена у страховій копії.",
              "Поза областю підказок (0x%X..0x%X) нічого не чіпаю; база позивних і ключі AES недосяжні для цього запису. Після запису рація перезавантажується; " % (VP_START, VP_END - 1) +
              "режим підказок вмикається в меню рації."]
    return "\n".join(lines)


def write_image(link, image, confirm, progress=None, log=print, safety_dir=None, now=None, cancel=None, post_reset=True, rng=None):
    """Записати образ підказок у рацію (див. модульний коментар про порядок). confirm(text) -> bool після страхової копії, до першого запису.
    Повертає словник: written, cancelled, text, safetyCopy, verified, sectorsWritten."""
    def prog(p, t):
        if progress:
            progress(max(0, min(100, int(p))), t)

    new = parse_image(image)
    if not new.valid:
        raise VpError("цей образ записувати не можна: " + "; ".join(new.problems))
    payload = bytes(image[:new.total])
    # D5: база 'n' поверх підказок
    level, ctext = db_conflict(link)
    if level == "clobbered":
        raise VpError(ctext)
    old = read_info(link)
    span = max(new.total, old.total if (old.magic_ok and not old.problems) else 0)
    prog(2, "Читаю поточну область підказок (страхова копія)...")
    old_bytes, safety = _safety_copy(link, min(VP_MAX, span), safety_dir, now, log, lambda d, t: prog(2 + 18.0 * d / max(1, t), "Читаю поточну область підказок..."))
    if old_bytes[:len(payload)] == payload:
        text = "Такі самі підказки вже в рації -- записувати нічого."
        log(text)
        return {"written": False, "cancelled": False, "nothingToDo": True, "text": text, "safetyCopy": safety, "verified": None, "sectorsWritten": 0}
    if not confirm(plan_text(new, old, ctext)):
        log("Скасовано користувачем; підказки в рації не змінені.")
        return {"written": False, "cancelled": True, "text": "Скасовано; підказки в рації не змінено.", "safetyCopy": safety, "verified": None, "sectorsWritten": 0}
    done = [0]
    total_sectors = (len(payload) + SECTOR - 1) // SECTOR + 2

    def on_sector(_k, _n):
        if cancel is not None and cancel():
            raise Cancelled()
        prog(20 + 70.0 * done[0] / total_sectors, "Пишу сектор %d" % (done[0] + 1))
    header_cleared = False

    def tick(k, n):
        on_sector(k, n)
        done[0] += 1
    try:
        on_sector(0, 1)
        fg.write_span(link.ser, VP_START, b"\x00" * HDR_LEN, "voiceprompts")          # 1) заголовок -> нулі: рація підказок не бачить
        header_cleared = True
        done[0] += 1
        fg.write_span(link.ser, VP_START + HDR_LEN, payload[HDR_LEN:], "voiceprompts", tick)
        on_sector(0, 1)
        fg.write_span(link.ser, VP_START, payload[:HDR_LEN], "voiceprompts")           # 3) справжній заголовок -- останнім
        done[0] += 1
    except Cancelled:
        text = ("Запис ПЕРЕРВАНО користувачем. Заголовок підказок обнулено, тож рація їх не бачить (звуки звичайні); решта рації не зачеплена. "
                "Щоб повернути старі підказки, завантаж страхову копію:\n%s" % safety)
        log(text)
        return {"written": False, "cancelled": True, "text": text, "safetyCopy": safety, "verified": None, "sectorsWritten": done[0]}
    except Exception as e:  # noqa: BLE001
        text = ("ПОМИЛКА під час запису підказок: %s. Заголовок підказок %s; решта рації не зачеплена. Страхова копія:\n%s" % (
            e, "обнулено -- підказок у рації зараз нема" if header_cleared else "ще не чіпано", safety))
        log(text)
        return {"written": False, "cancelled": False, "failed": str(e), "text": text, "safetyCopy": safety, "verified": None, "sectorsWritten": done[0]}
    prog(92, "Звіряю заголовок і вибірку даних...")
    ok, why = verify(link, payload, new, rng)
    text = "Підказки записані: %d фраз, %d Б. Звірка читанням: %s." % (new.present, new.total, ("пройшла (" + why + ")") if ok else "НЕ ПРОЙШЛА -- " + why)
    text += "\nСтрахова копія попередньої області:\n" + safety
    if post_reset:
        prog(97, "Перезавантажую рацію...")
        _reset(link)
        text += "\nУвімкни голосові підказки в меню рації, якщо вони ще вимкнені."
    prog(100, "Готово")
    return {"written": True, "cancelled": False, "text": text, "safetyCopy": safety, "verified": ok, "sectorsWritten": done[0]}


def verify(link, payload, info, rng=None):
    """Звірка: заголовок + TOC повністю, плюс 8 випадкових ділянок по 512 Б і останні 512 Б. -> (ok, пояснення)."""
    rng = rng or random.SystemRandom()
    head = link.read(cl.CPS_ACCESS_FLASH, VP_START, DATA_BASE)
    if head != payload[:DATA_BASE]:
        return False, "заголовок або таблиця змісту не збіглися"
    n = len(payload)
    spots = [max(0, n - 512)]
    for _ in range(8):
        spots.append(rng.randrange(0, max(1, n - 512)))
    for s in spots:
        ln = min(512, n - s)
        if ln <= 0:
            continue
        if link.read(cl.CPS_ACCESS_FLASH, VP_START + s, ln) != payload[s:s + ln]:
            return False, "дані не збіглися біля зміщення %d" % s
    return True, "заголовок із таблицею та %d ділянок даних" % len(spots)


def erase(link, confirm, progress=None, log=print, safety_dir=None, now=None, cancel=None, post_reset=True):
    """Стерти підказки (записати 0xFF на всю використану частину). Спершу страхова копія; без неї стирання не починається. Заголовок затирається першим."""
    def prog(p, t):
        if progress:
            progress(max(0, min(100, int(p))), t)
    old = read_info(link)
    if not old.magic_ok:
        raise VpError("у рації голосових підказок нема -- стирати нічого")
    if old.problems:
        raise VpError("область підказок у рації виглядає пошкодженою (%s) -- її не чіпаю; збережи її копією й розберися" % "; ".join(old.problems))
    level, ctext = db_conflict(link)
    old_bytes, safety = _safety_copy(link, old.total, safety_dir, now, log, lambda d, t: prog(2 + 18.0 * d / max(1, t), "Читаю область підказок..."))
    if not confirm("Стерти голосові підказки (%d Б) у рації?\nСтрахова копія вже збережена:\n%s\n\nРація перейде на звичайні звуки; повернути підказки можна з цього файла "
                   "кнопкою «Записати з файла»." % (old.total, safety)):
        return {"erased": False, "cancelled": True, "text": "Скасовано; підказки не змінено.", "safetyCopy": safety}
    done = [0]
    nsec = (old.total + SECTOR - 1) // SECTOR + 1

    def on_sector(_k, _n):
        if cancel is not None and cancel():
            raise Cancelled()
        prog(20 + 70.0 * done[0] / nsec, "Стираю сектор %d" % (done[0] + 1))

    def tick(k, n):
        on_sector(k, n)
        done[0] += 1
    try:
        fg.write_span(link.ser, VP_START, b"\x00" * HDR_LEN, "voiceprompts")
        done[0] += 1
        fg.write_span(link.ser, VP_START + HDR_LEN, b"\xff" * (old.total - HDR_LEN), "voiceprompts", tick)
        fg.write_span(link.ser, VP_START, b"\xff" * HDR_LEN, "voiceprompts")
    except Cancelled:
        text = "Стирання ПЕРЕРВАНО. Заголовок підказок обнулено, рація їх не бачить. Повернути можна зі страхової копії:\n%s" % safety
        return {"erased": False, "cancelled": True, "text": text, "safetyCopy": safety}
    chk = read_info(link)
    ok = not chk.magic_ok
    text = "Підказки стерто (%d Б). Перевірка: %s.\nСтрахова копія:\n%s" % (old.total, "заголовка 'VP' більше нема" if ok else "НЕ ПРОЙШЛА -- заголовок ще є", safety)
    if post_reset:
        _reset(link)
    prog(100, "Готово")
    return {"erased": ok, "cancelled": False, "text": text, "safetyCopy": safety}


def _reset(link):
    import cps_restore
    cps_restore._send_c(link, 6, cps_restore.POST_RESTORE_SUB)


def list_text(info, only_present=False):
    """Таблиця фраз текстом (для файла-переліку й журналу)."""
    lines = ["№\tПризначення\tЗміщення\tДовжина, Б\tКадрів AMBE\tПримітка"]
    for r in rows(info):
        if only_present and r["length"] <= 0:
            continue
        note = []
        if r["silent"]:
            note.append("нема (тиша)")
        if r["remainder"]:
            note.append("довжина не кратна 27")
        if r["oversize"]:
            note.append("довша за буфер 2052")
        lines.append("%d\t%s\t%d\t%d\t%d\t%s" % (r["index"], r["label"], r["offset"], r["length"], r["frames"], "; ".join(note)))
    return "\n".join(lines)
