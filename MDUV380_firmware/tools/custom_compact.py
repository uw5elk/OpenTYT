# -*- coding: utf-8 -*-
"""custom_compact.py -- R37: стан і ущільнення області custom-data рації (SPI-флеш, сирі адреси 0x20000..0x2FFFF, 64 КіБ на всі блоки разом).

ЧОМУ. Прошивка не вміє видаляти блок. «Вилучення» (R35, custom_data.retire_block) лише міняє тип блока на 0x7E000000+тип -- прошивка його пропускає, але
МІСЦЕ не звільняється: нова картинка йде в перший вільний слот у кінці. Кожен цикл «залив картинку -> прибрав -> залив іншу» з'їдає 1 КіБ безповоротно,
а орбіти (2520 Б) колись просто не вмістяться. Тут: показати справжній стан області (числа з області, не теорія) і ущільнити її -- зібрати живі блоки
підряд, викинути вилучені.

СКАНУВАННЯ -- той самий алгоритм, що в прошивці (codeplug.c: codeplugGetOpenGD77CustomDataStartAddressForType): заголовок «OpenGD77» (12 байтів), далі блоки
{int32 тип; int32 довжина}+дані до першого слота з довжиною 0 або 0xFFFFFFFF. Порожній хвіст МУСИТЬ лишатись 0xFF: «перший вільний слот» прошивки
(codeplugGetOpenGD77CustomDataFirstEmptySlot) вимагає довжину саме 0xFFFFFFFF. Тому ущільнення заповнює звільнену ділянку 0xFF.

ЩО РОБИТЬ ущільнення. Прибирає ЛИШЕ вилучені (retire) блоки; решта (у тому числі «затінені» дублікати типу, яких прошивка не бачить) лишається в тому ж порядку
й байт у байт. Зсуваються лише зсуви блоків, змісту це не змінює (прошивка шукає блок за типом при кожному зверненні й адрес не кешує).

ЗАПИС (U2.3) -- у порядку, що робить обрив безпечним:
  1) обнулити 8 байтів «OpenGD77» (відтепер область читається як «нема» -- рація підніме типові налаштування, а не покручений вміст);
  2) записати змінені ділянки даних (секторами; сектори, що вже збігаються, не чіпаються);
  3) записати заголовок «OpenGD77» ОСТАННІМ.
  Усі записи -- через flash_guard.write_span у вікні `customdata` (0x20000..0x2FFFF); калібрування, ключі AES, база позивних і кодплаг недосяжні.
ПЕРЕД записом -- страхова копія ВСІЄЇ області у файл із перевіркою, що файл читається назад; без успішної копії нічого не пишеться. ПІСЛЯ запису -- повне
перечитування й побайтова звірка з очікуваним образом; розбіжність -- голосна помилка зі шляхом до страхової копії. Повернути область з копії можна
(restore_safety_copy) тим самим безпечним порядком запису.

Обмеження, яке не обійти: прошивка рації перезаписує сектор флеша «прочитати -> стерти -> записати»; якщо живлення зникне саме в цю мить, пошкоджується
цей сектор. Тому страхова копія обов'язкова, а перед ущільненням рація має бути заряджена й не передавати."""
import hashlib
import os
import struct

import cps_link as cl
import custom_region as cr
import flash_guard as fg

REGION_LEN = cr.REGION_LEN
REGION_HDR = cr.REGION_HDR
BLOCK_HDR = cr.BLOCK_HDR
MAGIC = cr.MAGIC
REGION_RAW_START = cr.REGION_RAW_START
SECTOR = fg.SECTOR
WINDOW = "customdata"                 # вікно flash_guard
BIGGEST_BLOCK = 2520                  # найбільший блок, що може знадобитись: орбіти супутників (sat_tle.BLOCK_LEN; звіряється в тесті)
SAFETY_PREFIX = "customdata_pre-compact"


class CompactError(cl.CpsError):
    """Ущільнення / повернення області не виконано (пояснення словами)."""


class CompactWriteError(CompactError):
    """Збій під час запису: stage -- на якому кроці, header_zeroed -- чи встиг заголовок бути обнуленим (область у рації тоді читається як «нема»)."""

    def __init__(self, message, stage, header_zeroed):
        super().__init__(message)
        self.stage = stage
        self.header_zeroed = header_zeroed


def sha256(data):
    return hashlib.sha256(data).hexdigest()


# =========================================================================================
#  Розбір (усі записи, включно з вилученими й дублікатами)
# =========================================================================================

class Entry:
    def __init__(self, type_, offset, payload):
        self.type = type_
        self.offset = offset
        self.payload = bytes(payload)

    @property
    def length(self):
        return len(self.payload)

    @property
    def size(self):
        return BLOCK_HDR + len(self.payload)

    @property
    def retired(self):
        return cr.is_retired(self.type)

    @property
    def title(self):
        return cr.type_title(self.type)

    @property
    def raw(self):
        return struct.pack("<ii", self.type, len(self.payload)) + self.payload


class Scan:
    def __init__(self, data):
        self.data = bytes(data)
        self.entries = []
        self.problems = []
        self.end = REGION_HDR
        self.magic_ok = False
        self.erased = False
        self.terminated = False         # знайдено порожній слот (а не впертись у кінець області)

    @property
    def live(self):
        return [e for e in self.entries if not e.retired]

    @property
    def retired(self):
        return [e for e in self.entries if e.retired]

    def shadowed(self):
        """Живі записи, тип яких уже зустрівся раніше: прошивка бачить лише перший."""
        seen, out = set(), []
        for e in self.live:
            if e.type in seen:
                out.append(e)
            seen.add(e.type)
        return out


def scan_region(data):
    """Розбір області тим самим алгоритмом, що прошивка. Нічого не кидає: проблеми -- у Scan.problems."""
    s = Scan(data)
    if len(data) != REGION_LEN:
        s.problems.append("довжина області %d, а має бути %d" % (len(data), REGION_LEN))
        return s
    s.erased = all(x == 0xFF for x in data[:REGION_HDR])
    s.magic_ok = bytes(data[:8]) == MAGIC
    if not s.magic_ok:
        s.problems.append("область без заголовка OpenGD77" + (" (порожня, стерта)" if s.erased else ""))
        return s
    addr = REGION_HDR
    while addr + BLOCK_HDR <= REGION_LEN:
        dtype, dlen = struct.unpack("<ii", data[addr:addr + BLOCK_HDR])
        if dlen == 0 or dlen == cr.TYPE_EMPTY:
            s.end = addr
            s.terminated = True
            return s
        if dlen < 0 or addr + BLOCK_HDR + dlen > REGION_LEN:
            s.problems.append("блок типу %d у зсуві %d має довжину %d, що виходить за область -- розбір зупинено" % (dtype, addr, dlen))
            s.end = addr
            return s
        s.entries.append(Entry(dtype, addr, data[addr + BLOCK_HDR:addr + BLOCK_HDR + dlen]))
        addr += BLOCK_HDR + dlen
    s.end = addr
    return s


class Stats:
    """Числа, прочитані з самої області."""

    def __init__(self, scan):
        self.total = REGION_LEN
        self.end = scan.end
        self.live_count = len(scan.live)
        self.live_bytes = sum(e.size for e in scan.live)
        self.retired_count = len(scan.retired)
        self.retired_bytes = sum(e.size for e in scan.retired)
        self.shadowed_count = len(scan.shadowed())
        self.shadowed_bytes = sum(e.size for e in scan.shadowed())

    @property
    def used(self):
        return self.end

    @property
    def free(self):
        return self.total - self.end

    @property
    def max_payload(self):
        """Найбільший НОВИЙ блок (дані без заголовка), що вміститься: прошивка вимагає addr+8+len < 0x10000 (строго менше)."""
        return max(0, self.total - self.end - BLOCK_HDR - 1)

    @property
    def max_payload_after(self):
        return max(0, self.total - (self.end - self.retired_bytes) - BLOCK_HDR - 1)

    def text(self):
        return ("Зайнято %d з %d Б (заголовок %d Б; живі блоки %d Б у кількості %d; вилучені блоки %d Б у кількості %d). Вільно %d Б; найбільший новий блок, "
                "що вміститься, -- %d Б." % (self.used, self.total, REGION_HDR, self.live_bytes, self.live_count, self.retired_bytes, self.retired_count,
                                             self.free, self.max_payload))


def stats_of(data):
    """-> (Scan, Stats|None). Stats нема, якщо області немає або її не розібрано."""
    s = scan_region(data)
    if not s.magic_ok or s.problems:
        return s, None
    return s, Stats(s)


def warning_text(stats, scan=None):
    """Попередження (U1.2), якщо вільного менше за найбільший блок, який може знадобитись (орбіти, 2520 Б). '' -- все гаразд."""
    if stats is None or stats.max_payload >= BIGGEST_BLOCK:
        return ""
    t = ("УВАГА: вільного місця замало для блока орбіт супутників (%d Б даних + %d Б заголовка): новий блок такого розміру вміщається лише до %d Б даних, "
         "тобто бракує %d Б." % (BIGGEST_BLOCK, BLOCK_HDR, stats.max_payload, BIGGEST_BLOCK - stats.max_payload))
    if scan is not None and any(e.type == 3 and not e.retired for e in scan.entries):
        t += " (Блок орбіт у рації вже є, тож його оновлення місця не потребує; тривога стосується лише створення нових блоків.)"
    if stats.retired_bytes:
        if stats.max_payload_after >= BIGGEST_BLOCK:
            t += " «Ущільнити область» звільнить %d Б -- тоді блок орбіт вміститься." % stats.retired_bytes
        else:
            t += " «Ущільнити область» звільнить %d Б, але й тоді блок орбіт не вмістився б (вільно було б %d Б даних)." % (stats.retired_bytes, stats.max_payload_after)
    else:
        t += " Вилучених блоків, які можна було б прибрати, нема."
    return t


def state_text(data):
    """Повний опис стану області словами (U1.1): числа з вмісту. Для панелі й журналу."""
    scan, st = stats_of(data)
    if not scan.magic_ok:
        return "Області custom-data в рації нема (%s). Рація працює з типовими налаштуваннями; перший запис блока створить область." % "; ".join(scan.problems)
    if st is None:
        return "Область custom-data розібрати не вдалося: %s. Ущільнення вимкнено." % "; ".join(scan.problems)
    lines = [st.text()]
    if scan.retired:
        lines.append("Вилучені блоки (можна звільнити ущільненням): " + "; ".join(
            "%s -- %d Б" % (cr.type_title(e.type), e.size) for e in scan.retired) + ". Разом %d Б." % st.retired_bytes)
    else:
        lines.append("Вилучених блоків нема -- ущільнювати нічого.")
    if st.shadowed_count:
        lines.append("Затінені дублікати (прошивка їх не бачить; ущільнення їх НЕ чіпає): %d шт., %d Б." % (st.shadowed_count, st.shadowed_bytes))
    w = warning_text(st, scan)
    if w:
        lines.append(w)
    return "\n".join(lines)


# =========================================================================================
#  План ущільнення
# =========================================================================================

class CompactPlan:
    def __init__(self, scan, stats, expected, kept, dropped, after_stats, slices):
        self.scan = scan
        self.before = stats
        self.expected = expected          # образ області, який має вийти
        self.kept = kept                  # [(Entry, новий зсув)]
        self.dropped = dropped            # [Entry] -- вилучені, що зникнуть
        self.after = after_stats
        self.slices = slices              # [(від, до)] -- що реально буде записано (зсуви від початку області)

    @property
    def freed(self):
        return self.before.end - self.after.end

    def report(self):
        """До і після (U2.5)."""
        lines = ["ДО:  %s" % self.before.text(), "ПІСЛЯ: зайнято %d Б (живі блоки %d Б, вилучених 0), вільно %d Б; найбільший новий блок -- %d Б. Звільнено: %d Б." % (
            self.after.used, self.after.live_bytes, self.after.free, self.after.max_payload, self.freed), "", "Блоки (зсув від початку області):"]
        new = {id(e): n for e, n in self.kept}
        for e in self.scan.entries:
            if id(e) in new:
                moved = "лишається" + ("" if new[id(e)] == e.offset else ", зсув %d -> %d" % (e.offset, new[id(e)]))
                lines.append("  %-6d %s (%d Б): %s" % (e.offset, e.title, e.length, moved))
            else:
                lines.append("  %-6d %s (%d Б): ПРИБИРАЄТЬСЯ, звільняє %d Б" % (e.offset, e.title, e.length, e.size))
        return "\n".join(lines)


def _diff_slices(cur, target):
    """Ділянки [від, до) всередині секторів, де cur != target (заголовок 0..12 не рахуємо: його пише окремий крок)."""
    out = []
    for s in range(0, REGION_LEN, SECTOR):
        a, b = max(s, REGION_HDR), s + SECTOR
        if cur[a:b] == target[a:b]:
            continue
        i, j = a, b
        while cur[i] == target[i]:
            i += 1
        while cur[j - 1] == target[j - 1]:
            j -= 1
        out.append((i, j))
    return out


def plan_compaction(data):
    """-> (CompactPlan|None, причина). Нічого не пише. План немає, якщо області нема, її не розібрано, або ущільнювати нічого."""
    scan = scan_region(data)
    if not scan.magic_ok:
        return None, "області custom-data в рації нема (%s) -- ущільнювати нічого" % "; ".join(scan.problems)
    if scan.problems:
        return None, "область розібрано з помилками (%s) -- ущільнення вимкнено, щоб не зіпсувати те, що ще читається" % "; ".join(scan.problems)
    if not scan.retired:
        return None, "вилучених блоків нема -- ущільнювати нічого"
    out = bytearray(data)
    pos = REGION_HDR
    kept = []
    for e in scan.live:
        raw = e.raw
        out[pos:pos + len(raw)] = raw
        kept.append((e, pos))
        pos += len(raw)
    out[pos:scan.end] = b"\xff" * (scan.end - pos)          # звільнена ділянка -- стерта (0xFF): прошивка так шукає «перший вільний слот»
    expected = bytes(out)
    after_scan = scan_region(expected)
    if after_scan.problems or after_scan.end != pos:
        raise CompactError("внутрішня помилка плану ущільнення: образ не розбирається (%s)" % "; ".join(after_scan.problems))
    plan = CompactPlan(scan, Stats(scan), expected, kept, scan.retired, Stats(after_scan), _diff_slices(bytes(data), expected))
    return plan, ""


# =========================================================================================
#  Запис образу (безпечний порядок) і звірка
# =========================================================================================

def write_image(link, cur, target, progress=None, log=print):
    """Записати `target` замість `cur` у порядку: обнулити заголовок -> змінені ділянки даних -> заголовок. Усе через flash_guard (вікно customdata).
    CompactWriteError -- збій (з відомостями, на якому кроці й чи заголовок уже обнулено). Повертає кількість записаних ділянок даних."""
    cur, target = bytes(cur), bytes(target)
    if len(cur) != REGION_LEN or len(target) != REGION_LEN:
        raise CompactError("образ області має довжину %d / %d, а має бути %d" % (len(cur), len(target), REGION_LEN))
    if target[:8] != MAGIC:
        raise CompactError("образ для запису без заголовка OpenGD77 -- нічого не записано")
    ser = link.ser
    slices = _diff_slices(cur, target)
    total = len(slices) + 2
    zeroed = False
    stage = "обнулення заголовка"

    def prog(k, text):
        if progress:
            progress(int(100.0 * k / total), text)

    try:
        if cur[:8] == MAGIC:
            prog(0, "Обнуляю заголовок області...")
            log("Крок 1: обнуляю заголовок «OpenGD77» (область читатиметься як «нема», доки запис не завершено).")
            fg.write_span(ser, REGION_RAW_START, b"\x00" * 8, WINDOW)
            zeroed = True
            head = link.read(cl.CPS_ACCESS_FLASH, REGION_RAW_START, REGION_HDR)
            if bytes(head[:8]) != b"\x00" * 8:
                raise CompactError("заголовок після обнулення читається як %r, а не нулі" % bytes(head[:8]))
        else:
            zeroed = True            # заголовка й так нема
        # R73: усі ділянки даних -- одним проходом по секторах: сектор, у якому змінилось кілька відокремлених ділянок, стирається ОДИН раз (було -- на кожну ділянку)
        stage = "дані (%d ділянок)" % len(slices)
        fg.write_group(ser, [(REGION_RAW_START + a, target[a:b]) for a, b in slices], WINDOW,
                       on_sector=lambda k, n: prog(1 + min(k, max(0, len(slices) - 1)), "Пишу сектор даних %d з %d..." % (k + 1, n)))
        stage = "запис заголовка"
        prog(total - 1, "Пишу заголовок області...")
        log("Крок 3: пишу заголовок «OpenGD77» останнім.")
        fg.write_span(ser, REGION_RAW_START, target[:REGION_HDR], WINDOW)
    except CompactWriteError:
        raise
    except Exception as e:  # noqa: BLE001 -- будь-який збій запису перетворюємо на пояснену помилку
        raise CompactWriteError("збій на кроці «%s»: %s" % (stage, e), stage, zeroed)
    prog(total, "Записано")
    return len(slices)


def verify_image(link, expected, progress=None):
    """Перечитати всю область і порівняти з очікуваним. -> (збіглося, текст про розбіжності)."""
    after = cr.read_radio_region(link, progress)
    if after == expected:
        return True, ""
    bad = [i for i in range(min(len(after), len(expected))) if after[i] != expected[i]]
    first = bad[0] if bad else 0
    return False, "після запису область у рації відрізняється від очікуваної у %d байтах, перший -- у зсуві %d (є 0x%02X, мало бути 0x%02X)" % (
        len(bad), first, after[first] if after else 0, expected[first] if expected else 0)


# =========================================================================================
#  Страхова копія
# =========================================================================================

def save_safety_copy(data, directory, now=None):
    """Зберегти область у файл і прочитати назад. -> шлях. CompactError, якщо не вдалося (тоді файл прибрано)."""
    if not os.path.isdir(directory) or not os.access(directory, os.W_OK):
        raise CompactError("нема права писати в теку %s, де має лежати страхова копія області. Нічого не записано." % directory)
    path = cl.unique_path(directory, cl.timestamp_name(SAFETY_PREFIX, ".bin", now))
    try:
        with open(path, "xb") as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        with open(path, "rb") as f:
            back = f.read()
        if back != data or len(back) != REGION_LEN:
            raise OSError("записаний файл відрізняється від прочитаного з рації")
    except OSError as e:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise CompactError("не вдалося зберегти страхову копію області (%s). Нічого не записано." % e)
    return path


def _failure_text(err, safety):
    t = "ПОМИЛКА запису: %s." % err
    if getattr(err, "header_zeroed", False):
        t += ("\nЗаголовок області обнулено, тож рація зараз читає область як «нема» і працює з ТИПОВИМИ налаштуваннями (теми, SMS, RCTL, APRS, картинка, "
              "мелодія, орбіти не видно, але дані в флеші лишились).")
    else:
        t += "\nЗаголовок ще не чіпали -- область у рації лишилась як була."
    t += "\nСтрахова копія всієї області ЦІЛА: %s\nПовернути її можна в розділі «Бекап і відновлення» вікном «Відновити…» (джерело -- автоматична страхова копія)." % safety
    return t


# =========================================================================================
#  Ущільнити область в рації
# =========================================================================================

def compact_region(link, confirm, safety_dir, progress=None, log=print, now=None, post_reset=True):
    """Ущільнити область custom-data рації. confirm(text, plan) -> bool викликається ПІСЛЯ страхової копії, ПЕРЕД першим записом.
    Повертає словник: nothingToDo, cancelled, ok, verified, text, plan, safetyCopy. Жодних винятків за збій ЗАПИСУ (він у text і ok=False);
    CompactError -- лише коли страхову копію не вдалося створити (тоді нічого не записано)."""
    def prog(p, t):
        if progress:
            progress(max(0, min(100, int(p))), t)

    prog(0, "Читаю область з рації...")
    cur = cr.read_radio_region(link, lambda d, t: prog(8.0 * d / max(1, t), "Читаю область з рації..."))
    plan, why = plan_compaction(cur)
    if plan is None:
        text = "Ущільнення не потрібне або неможливе: %s." % why
        log(text)
        return {"nothingToDo": True, "cancelled": False, "ok": True, "verified": None, "text": text, "plan": None, "safetyCopy": None, "state": state_text(cur)}
    prog(8, "Зберігаю страхову копію...")
    safety = save_safety_copy(cur, safety_dir, now)
    log("Страхова копія області збережена й перевірена читанням: %s (SHA-256 %s)." % (safety, sha256(cur)[:16]))
    ask = ("Ущільнити область custom-data рації.\n\n" + plan.report() +
           "\n\nПорядок запису: обнулити заголовок «OpenGD77» -> змінені ділянки даних -> заголовок останнім. Якщо запис обірветься, рація прочитає область "
           "як «нема» і працюватиме з типовими налаштуваннями; повна страхова копія вже збережена:\n" + safety +
           "\n\nПісля запису область буде повністю перечитана й звірена байт у байт, а рація перезавантажиться. Не вимикай і не відключай рацію під час запису.")
    if not confirm(ask, plan):
        log("Скасовано користувачем; область рації не змінено.")
        return {"nothingToDo": False, "cancelled": True, "ok": True, "verified": None, "text": "Скасовано; область рації не змінено.", "plan": plan,
                "safetyCopy": safety}
    try:
        n = write_image(link, cur, plan.expected, lambda p, t: prog(10 + 0.7 * p, t), log)
    except CompactWriteError as e:
        text = _failure_text(e, safety)
        log(text)
        return {"nothingToDo": False, "cancelled": False, "ok": False, "verified": False, "text": text, "plan": plan, "safetyCopy": safety}
    prog(82, "Перечитую область і звіряю...")
    same, why = verify_image(link, plan.expected, lambda d, t: prog(82 + 14.0 * d / max(1, t), "Перечитую область і звіряю..."))
    if not same:
        text = "ПОМИЛКА ЗВІРКИ: %s.\nСтрахова копія області ЦІЛА: %s\nНе вимикай рацію; повернути область можна в розділі «Бекап і відновлення» вікном «Відновити…» (джерело -- автоматична страхова копія)." % (why, safety)
        log(text)
        return {"nothingToDo": False, "cancelled": False, "ok": False, "verified": False, "text": text, "plan": plan, "safetyCopy": safety}
    text = ("Область ущільнено й звірено байт у байт (записано ділянок: %d).\n" % n + plan.report() + "\n\nСтрахова копія попередньої області:\n" + safety)
    log(text)
    if post_reset:
        import cps_restore
        prog(97, "Перезавантажую рацію...")
        cps_restore._send_c(link, 6, cps_restore.POST_RESTORE_SUB)
        text += "\nРація перезавантажується."
    prog(100, "Готово")
    return {"nothingToDo": False, "cancelled": False, "ok": True, "verified": True, "text": text, "plan": plan, "safetyCopy": safety}


def restore_safety_copy(link, path, confirm, progress=None, log=print, post_reset=True):
    """Повернути область у рацію зі страхової копії (.bin) тим самим безпечним порядком запису. Повертає словник як compact_region."""
    try:
        with open(path, "rb") as f:
            img = f.read()
    except OSError as e:
        raise CompactError("не вдалося прочитати файл: %s" % e)
    if len(img) != REGION_LEN:
        raise CompactError("це не страхова копія області: довжина файла %d, а має бути %d" % (len(img), REGION_LEN))
    sc = scan_region(img)
    if not sc.magic_ok or sc.problems:
        raise CompactError("у файлі немає справної області OpenGD77 (%s) -- відновлювати нічого" % "; ".join(sc.problems))
    cur = cr.read_radio_region(link)
    if cur == img:
        return {"nothingToDo": True, "cancelled": False, "ok": True, "verified": True, "text": "Область у рації вже збігається з файлом -- записувати нічого."}
    ask = ("Повернути область custom-data рації зі страхової копії:\n%s\n\nУ копії: %s\nЗараз у рації: %s\n\nПорядок запису: обнулити заголовок -> змінені ділянки -> "
           "заголовок останнім. Після запису область буде перечитана й звірена, а рація перезавантажиться." % (
               path, state_text(img).splitlines()[0], state_text(cur).splitlines()[0]))
    if not confirm(ask, None):
        return {"nothingToDo": False, "cancelled": True, "ok": True, "verified": None, "text": "Скасовано; область рації не змінено."}
    try:
        write_image(link, cur, img, progress, log)
    except CompactWriteError as e:
        text = "ПОМИЛКА запису: %s.\nФайл із копією не змінено: %s" % (e, path)
        return {"nothingToDo": False, "cancelled": False, "ok": False, "verified": False, "text": text}
    same, why = verify_image(link, img)
    if not same:
        return {"nothingToDo": False, "cancelled": False, "ok": False, "verified": False, "text": "ПОМИЛКА ЗВІРКИ: %s.\nФайл із копією: %s" % (why, path)}
    text = "Область повернуто зі страхової копії й звірено байт у байт.\n%s" % state_text(img)
    if post_reset:
        import cps_restore
        cps_restore._send_c(link, 6, cps_restore.POST_RESTORE_SUB)
        text += "\nРація перезавантажується."
    return {"nothingToDo": False, "cancelled": False, "ok": True, "verified": True, "text": text}


# =========================================================================================
#  U3: місце перед записом нового блока
# =========================================================================================

class RoomCheck:
    def __init__(self, status, need, stats, text):
        self.status = status           # ok | noregion | noroom
        self.need = need
        self.stats = stats
        self.text = text

    @property
    def can_compact(self):
        """Ущільнення звільнить достатньо місця."""
        return self.status == "noroom" and self.stats is not None and self.stats.max_payload_after >= self.need


def room_check(data, data_type, new_len):
    """Чи вміститься запис блока (data_type, new_len) за правилами прошивки. Чиста логіка над образом області."""
    scan = scan_region(data)
    if not scan.magic_ok:
        return RoomCheck("noregion", new_len, None, "області custom-data в рації нема")
    if scan.problems:
        return RoomCheck("noregion", new_len, None, "область розібрано з помилками: " + "; ".join(scan.problems))
    for e in scan.entries:
        if e.type == data_type:
            return RoomCheck("ok", new_len, Stats(scan), "блок такого типу вже є (довжину міняє/перевіряє сам запис)")
    st = Stats(scan)
    if scan.terminated and scan.end + BLOCK_HDR + new_len < REGION_LEN:
        return RoomCheck("ok", new_len, st, "місце є")
    t = ("У області custom-data бракує місця для нового блока: треба %d Б даних (+%d Б заголовка), а вміщається лише %d Б даних (вільно %d Б)." % (
        new_len, BLOCK_HDR, st.max_payload, st.free))
    if st.retired_bytes:
        if st.max_payload_after >= new_len:
            t += " Вилучені блоки займають %d Б: після ущільнення області вміститься до %d Б даних." % (st.retired_bytes, st.max_payload_after)
        else:
            t += " Вилучені блоки займають %d Б, але й після ущільнення вміститься лише %d Б даних -- решту займають живі блоки (%d Б)." % (
                st.retired_bytes, st.max_payload_after, st.live_bytes)
    else:
        t += " Вилучених блоків, які можна було б прибрати, нема; живі блоки займають %d Б." % st.live_bytes
    return RoomCheck("noroom", new_len, st, t)


def ensure_room(ser, data_type, new_len, confirm=None, safety_dir=None, progress=None, log=print):
    """Для запису блока: якщо місця нема, а ущільнення його дасть, -- запропонувати ущільнення (confirm) і виконати. Повертає True, якщо після виклику
    місце є (можна повторити пошук слота). RuntimeError з поясненням, коли місця нема й ущільнення не допоможе або користувач відмовився.
    Перезавантаження рації тут НЕ робиться: запис блока йде далі в тій самій сесії."""
    link = cl.CpsLink(ser)
    data = cr.read_radio_region(link)
    rc = room_check(data, data_type, new_len)
    if rc.status != "noroom":
        return rc.status == "ok"
    if not rc.can_compact:
        raise RuntimeError(rc.text)
    if confirm is None or safety_dir is None:
        raise RuntimeError(rc.text + " Розділ «Усі налаштування» -> «Ущільнити область».")

    def ask(text, plan):
        return confirm(rc.text + "\n\nУщільнити область зараз, а тоді записати блок?\n\n" + text, plan)

    res = compact_region(link, ask, safety_dir, progress, log, post_reset=False)
    if res["cancelled"]:
        raise RuntimeError(rc.text + " Ущільнення відхилено -- блок не записано.")
    if not res["ok"]:
        raise RuntimeError(res["text"])
    log(res["text"])
    return True
