#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cps_restore.py -- R25 W1: ВІДНОВЛЕННЯ кодплуга з бекапу (.zip з tools/cps_link.py) у рацію.

*** ЦЕ ПЕРША ФУНКЦІЯ ПРОШИВАЛЬНИКА, ЯКА ПИШЕ В КОДПЛУГ РАЦІЇ. *** Увесь запис 'X' зібрано в цьому файлі (cps_link.py
лишається суто читальним). Лише стандартна бібліотека + pyserial (через cps_link.open_radio).

БЛОКУВАННЯ (W1.11): RESTORE_UNLOCKED = False, доки Богдан не підтвердить BK8 (два підряд бекапи з однаковим SHA-256).
Перевірка стоїть у самій restore_codeplug(), тож жоден шлях -- ні кнопка GUI, ні CLI -- її не обходить. Зняти
блокування = змінити цю одну константу окремим однорядковим комітом.

ЯК ПИШЕМО (виведено з usb_com.c, cpsHandleWriteCommand; на залізі це підтвердить крок BL7):
  * 'X' 1 + сектор (24 біти)   -> прошивка читає 4096 Б сектора в RAM-буфер;
  * 'X' 2 + addr[4] + len[2] + дані (<= 1528 Б) -> байти, що потрапляють у підготовлений сектор, лягають у буфер;
  * 'X' 3                      -> стерти сектор і записати 16 сторінок по 256 Б.
  * 'X' 4 (EEPROM) на MDUV380 НІЧОГО НЕ РОБИТЬ (ok = true без запису), тож EEPROM (= той самий SPI-флеш від адреси 0,
    MDUV380_EMULATED_EEPROM_ADDRESS_OFFSET = 0) пишеться тим самим механізмом секторів, що й флеш-кодплуг.
  Збій будь-якої команди X скидає внутрішній стан прошивки (sector = -1), тож повторний X 1 після обриву працює.

ЧОГО НЕ ЧІПАЄМО І ЧОМУ:
  * сектор калібрування 0x10000..0x10FFF: 'X' 1 для нього НЕ завантажує сектор у буфер, а шматок 1024 Б прошивка не
    розпізнає як калібрування (воно розпізнається лише в межах 0x10000..0x10200) -- 'X' 3 стер би сектор і записав
    застарілий буфер. Тому сектор калібрування НІКОЛИ не пишемо (береться з рації як є);
  * 20 байтів квіккеїв 0x7524..0x7537: прошивка їх навмисно не перезаписує ("QuickKeys hack"), тож вони залишаються
    такими, які були в рації; у перевірці після запису ці байти виключено;
  * голосові підказки, ключі AES, база DMR ID, прошивка -- маніфест їх не називає (або вони позначені restorable=false),
    ми їх не пишемо ніколи (W1.7, W3.3).

ПІСЛЯ ЗАПИСУ: 'C' 6 1 (перезавантаження без збереження RAM-налаштувань). НЕ 'C' 6 0, як у CPS: та підкоманда спершу
викликає settingsSaveSettings() і записала б у EEPROM (0x604B) НАЛАШТУВАННЯ З RAM -- тобто затерла б щойно відновлені.
Налаштування лежать у відновлюваній частині (EEPROM 0x604B), тож після перезавантаження рація бере їх з бекапу разом
із зонами й каналами; `currentZone` з бекапу узгоджений з відновленими зонами. (Це висновок з коду, не з заліза: BL8.)
"""
import json
import os
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cps_link as cl  # noqa: E402
import codeplug_view as cv  # noqa: E402

# *** Зняти блокування = змінити False на True окремим однорядковим комітом, коли Богдан підтвердить BK8. ***
RESTORE_UNLOCKED = False
LOCKED_CAPTION = "доступно після перевірки BK8"

SECTOR = cl.SECTOR
CAL_START = 0x10000                       # usb_com.c: "Local calibration" (сектор 16)
CAL_END = CAL_START + SECTOR
QUICKKEYS_START = 0x7524                  # codeplug.h: CODEPLUG_ADDR_QUICKKEYS
QUICKKEYS_LEN = 10 * 2                    # CODEPLUG_QUICKKEYS_SIZE * sizeof(uint16_t)
X_CHUNK = 1024                            # ліміт прошивки 1528; беремо 1024 як у решті інструментів
X_TIMEOUT = 2.0                           # секунд на відповідь X 1 / X 2
X_COMMIT_TIMEOUT = 8.0                    # X 3: стирання сектора + 16 сторінок
POST_RESTORE_SUB = 1                      # 'C' 6 1 -- див. шапку

REQUIRED_RADIO_FIELDS = ("radioType", "structVersion")
REQUIRED_PART_FIELDS = ("file", "area", "start", "length", "sha256")


class RestoreRefused(cl.CpsError):
    """Відновлення ВІДХИЛЕНО ДО будь-якого запису в рацію (причина -- у тексті)."""


class RestoreInterrupted(cl.CpsError):
    """Запис обірвався/відмовлений ПІСЛЯ початку: кодплуг рації у невизначеному стані."""


class RestoreVerifyFailed(cl.CpsError):
    """Запис закінчився, але перечитування не збіглося з бекапом."""


class _XSilent(cl.CpsError):
    pass


class _XRefused(cl.CpsError):
    pass


# =========================================================================================
#  Перевірка файла й рації
# =========================================================================================

def validate_manifest(m):
    """W1.3/W1.4: обов'язкові поля й межі. Повертає None або кидає RestoreRefused. Нічого не пише."""
    if not isinstance(m, dict):
        raise RestoreRefused("маніфест бекапу не є об'єктом JSON")
    if m.get("format") != 1:
        raise RestoreRefused("невідомий формат маніфесту (format = %r, очікується 1)" % (m.get("format"),))
    radio = m.get("radio")
    if not isinstance(radio, dict):
        raise RestoreRefused("у маніфесті немає розділу radio (тип рації) -- без нього не можна переконатися, що бекап від такої самої рації")
    for k in REQUIRED_RADIO_FIELDS:
        if not isinstance(radio.get(k), int):
            raise RestoreRefused("у маніфесті немає обов'язкового поля radio.%s" % k)
    parts = m.get("parts")
    if not isinstance(parts, dict):
        raise RestoreRefused("у маніфесті немає розділу parts")
    rng = cl.flash_backup_range()
    expect = {
        "eeprom": ("eeprom.bin", cl.CPS_ACCESS_EEPROM, 0, cl.EEPROM_BACKUP_LEN),
        "flash": ("flash.bin", cl.CPS_ACCESS_FLASH, rng["raw_start"], rng["length"]),
    }
    for key, (fname, area, start, length) in expect.items():
        part = parts.get(key)
        if not isinstance(part, dict):
            raise RestoreRefused("у маніфесті немає частини %s" % key)
        for f in REQUIRED_PART_FIELDS:
            if f not in part:
                raise RestoreRefused("у маніфесті немає обов'язкового поля parts.%s.%s" % (key, f))
        if (part["file"], part["area"], part["start"], part["length"]) != (fname, area, start, length):
            raise RestoreRefused(
                "частина %s у маніфесті описує інший діапазон (файл %s, область %s, початок 0x%X, довжина %s), ніж відомий кодплуг цієї "
                "прошивки (файл %s, область %d, початок 0x%X, довжина %d). Записувати поза відомим кодплугом заборонено."
                % (key, part["file"], part["area"], part["start"] if isinstance(part["start"], int) else 0, part["length"],
                   fname, area, start, length))


def load_backup_for_restore(source):
    """Відкрити бекап, перевірити маніфест і SHA-256 УСІХ частин. Повертає (manifest, eeprom, flash) або кидає RestoreRefused."""
    try:
        f = source
        if isinstance(source, (bytes, bytearray)):
            import io
            f = io.BytesIO(source)
        with zipfile.ZipFile(f) as z:
            manifest = json.loads(z.read("manifest.json").decode("utf-8"))
    except (OSError, zipfile.BadZipFile, KeyError, ValueError) as e:
        raise RestoreRefused("це не бекап кодплуга або файл пошкоджено: %s" % e)
    validate_manifest(manifest)
    try:
        manifest, eeprom, flash = cl.read_backup_zip(source)
    except cl.CpsError as e:
        raise RestoreRefused("файл бекапу не пройшов перевірку цілісності (SHA-256): %s. Відновлення з нього заборонено." % e)
    except OSError as e:
        raise RestoreRefused("не вдалося прочитати файл бекапу: %s" % e)
    return manifest, eeprom, flash


def check_radio(info, manifest):
    """W1.3: тип і версія структури мусять збігатися. gitRevision може відрізнятися (лише показується)."""
    if info["radioType"] != cl.RADIO_TYPE_MDUV380:
        raise RestoreRefused("підключена рація має radioType %d, а відновлення розраховане лише на MD-UV380/390 (radioType %d)."
                             % (info["radioType"], cl.RADIO_TYPE_MDUV380))
    mr = manifest["radio"]
    if mr["radioType"] != info["radioType"]:
        raise RestoreRefused("бекап зроблено з рації іншого типу: radioType у файлі %d, у підключеній рації %d. Нічого не записано."
                             % (mr["radioType"], info["radioType"]))
    if mr["structVersion"] != info["structVersion"]:
        raise RestoreRefused("не збігається версія структури кодплуга: structVersion у файлі %d, у підключеній рації %d. Нічого не записано."
                             % (mr["structVersion"], info["structVersion"]))


# =========================================================================================
#  План
# =========================================================================================

class Plan:
    """Що саме писатимемо: список секторів (мітка, сира адреса, 4096 байтів бажаного вмісту) + бажані образи для перевірки."""

    def __init__(self, sectors, want_ee, want_fl, total_sectors, raw_flash_start):
        self.sectors = sectors
        self.want_ee = want_ee
        self.want_fl = want_fl
        self.total_sectors = total_sectors
        self.raw_flash_start = raw_flash_start

    def count(self, label):
        return sum(1 for s in self.sectors if s[0] == label)


def compute_plan(cur_ee, cur_fl, bk_ee, bk_fl):
    """Порівнює поточний вміст рації з бекапом по секторах. Бажаний образ = бекап, КРІМ сектора калібрування й квіккеїв
    (там лишається те, що зараз у рації). Пишемо лише сектори, що відрізняються (менше зносу флеша й менше ризику)."""
    if len(cur_ee) != len(bk_ee) or len(cur_fl) != len(bk_fl):
        raise RestoreRefused("внутрішня помилка: розміри поточного образу й бекапу не збігаються")
    want_ee = bytearray(bk_ee)
    want_ee[CAL_START:CAL_END] = cur_ee[CAL_START:CAL_END]
    want_ee[QUICKKEYS_START:QUICKKEYS_START + QUICKKEYS_LEN] = cur_ee[QUICKKEYS_START:QUICKKEYS_START + QUICKKEYS_LEN]
    want_fl = bytearray(bk_fl)
    rng = cl.flash_backup_range()
    sectors = []
    for i in range(len(want_ee) // SECTOR):
        a = i * SECTOR
        if want_ee[a:a + SECTOR] != cur_ee[a:a + SECTOR]:
            sectors.append(("EEPROM", a, bytes(want_ee[a:a + SECTOR])))
    for i in range(len(want_fl) // SECTOR):
        a = i * SECTOR
        if want_fl[a:a + SECTOR] != cur_fl[a:a + SECTOR]:
            sectors.append(("флеш", rng["raw_start"] + a, bytes(want_fl[a:a + SECTOR])))
    total = len(want_ee) // SECTOR + len(want_fl) // SECTOR
    return Plan(sectors, bytes(want_ee), bytes(want_fl), total, rng["raw_start"])


def _mask_quickkeys(ee):
    b = bytearray(ee)
    b[QUICKKEYS_START:QUICKKEYS_START + QUICKKEYS_LEN] = b"\0" * QUICKKEYS_LEN
    return bytes(b)


def confirm_text(manifest, bk_ee, bk_fl, info, plan, safety_path, zip_path):
    """W1.6: конкретний текст підтвердження."""
    cp = cv.Codeplug(manifest, bk_ee, bk_fl)
    mr = manifest["radio"]
    rng = cl.flash_backup_range()
    lines = [
        "ВІДНОВЛЕННЯ КОДПЛУГА -- рація буде ПЕРЕЗАПИСАНА.",
        "",
        "Файл: %s" % os.path.basename(zip_path),
        "Бекап створено: %s UTC" % manifest.get("createdUtc", "?"),
        "У бекапі: позивний %s, DMR ID %d" % (cp.callsign() or "(порожньо)", cp.dmr_id()),
        "Прошивка рації в момент бекапу: %s; зараз у рації: %s%s" % (
            mr.get("gitRevision", "?"), info.get("gitRevision", "?"),
            "" if mr.get("gitRevision") == info.get("gitRevision") else "  <-- ВІДРІЗНЯЮТЬСЯ (відновлення дозволене, але перевір)"),
        "",
        "Буде перезаписано:",
        "  - EEPROM: адреси 0x0 .. 0x%X (%d КБ); секторів, що відрізняються: %d з %d. Не чіпаються: сектор калібрування "
        "0x%X..0x%X і 20 байтів квіккеїв (0x%X)." % (cl.EEPROM_BACKUP_LEN, cl.EEPROM_BACKUP_LEN // 1024, plan.count("EEPROM"),
                                                     cl.EEPROM_BACKUP_LEN // SECTOR, CAL_START, CAL_END - 1, QUICKKEYS_START),
        "  - Флеш-кодплуг: сирі адреси 0x%X .. 0x%X (%d КБ); секторів, що відрізняються: %d з %d."
        % (rng["raw_start"], rng["raw_end"], rng["length"] // 1024, plan.count("флеш"), rng["length"] // SECTOR),
        "Не чіпаються: голосові підказки, ключі AES, база DMR ID, прошивка.",
        "",
        "Страхова копія ПОТОЧНОГО стану рації вже збережена:",
        "  %s" % safety_path,
        "",
        "Не вимикай рацію і не виймай кабель, доки не з'явиться підсумок. Після запису рація перезавантажиться.",
        "Відновити?",
    ]
    return "\n".join(lines)


# =========================================================================================
#  Запис 'X'
# =========================================================================================

def _set_timeout(ser, t):
    old = getattr(ser, "timeout", None)
    try:
        ser.timeout = t
    except Exception:  # noqa: BLE001 -- підставні порти можуть не мати timeout
        pass
    return old


def _x_exchange(link, payload, sub, timeout):
    """Надіслати один пакет 'X' і прочитати рівно 2 байти відповіді ('X', sub). '-' = відмова прошивки."""
    ser = link.ser
    old = _set_timeout(ser, timeout)
    try:
        ser.reset_input_buffer()
        ser.write(payload)
        ser.flush()
        first = link._read_exact(1)
        if not first:
            raise _XSilent("рація не відповіла (тайм-аут %.0f с)" % timeout)
        if first == b"-":
            raise _XRefused("рація відмовила ('-')")
        second = link._read_exact(1)
        if first != b"X" or second != bytes([sub]):
            raise _XSilent("несподівана відповідь рації: %r" % (first + second))
    finally:
        if old is not None:
            _set_timeout(ser, old)


def _x1(sector):
    return bytes([ord("X"), 1, (sector >> 16) & 0xFF, (sector >> 8) & 0xFF, sector & 0xFF])


def _x2(addr, chunk):
    n = len(chunk)
    return bytes([ord("X"), 2, (addr >> 24) & 0xFF, (addr >> 16) & 0xFF, (addr >> 8) & 0xFF, addr & 0xFF,
                  (n >> 8) & 0xFF, n & 0xFF]) + chunk


def write_sector(link, raw_addr, data, log=print):
    """Записати ОДИН сектор (4096 Б) за адресою raw_addr (кратна 4096): X 1 -> X 2 (по X_CHUNK) -> X 3.
    Кидає _XSilent/_XRefused (їх обгортає restore_codeplug)."""
    if raw_addr % SECTOR or len(data) != SECTOR:
        raise ValueError("write_sector: адреса мусить бути кратна %d, дані -- рівно %d Б" % (SECTOR, SECTOR))
    if CAL_START <= raw_addr < CAL_END:
        raise ValueError("сектор калібрування 0x%X писати заборонено" % raw_addr)
    sector = raw_addr // SECTOR
    try:
        _x_exchange(link, _x1(sector), 1, X_TIMEOUT)
    except _XRefused:
        # Прошивка відмовляє в X 1, якщо попередній запис лишив підготовлений сектор; сама відмова скидає цей стан
        # (usb_com.c: при !ok -> sector = -1), тож один повтор допустимий.
        log("X 1 відмовлено -- у прошивки лишався підготовлений сектор після обриву; повторюю.")
        _x_exchange(link, _x1(sector), 1, X_TIMEOUT)
    for off in range(0, SECTOR, X_CHUNK):
        _x_exchange(link, _x2(raw_addr + off, data[off:off + X_CHUNK]), 2, X_TIMEOUT)
    _x_exchange(link, bytes([ord("X"), 3]), 3, X_COMMIT_TIMEOUT)


def _send_c(link, *args, wait=0.3):
    """Команда 'C' + аргументи (відповідь не важлива -- як у aes_key_store.show_cps)."""
    ser = link.ser
    old = _set_timeout(ser, wait)
    try:
        ser.reset_input_buffer()
        ser.write(bytes([ord("C")] + list(args)))
        ser.flush()
        ser.read(8)
    except Exception:  # noqa: BLE001
        pass
    finally:
        if old is not None:
            _set_timeout(ser, old)


# =========================================================================================
#  Головна функція
# =========================================================================================

def safety_backup_path(zip_path, now=None):
    d = os.path.dirname(os.path.abspath(zip_path))
    return cl.unique_path(d, cl.timestamp_name("codeplug_pre-restore", ".zip", now))


def restore_codeplug(link, zip_path, confirm, progress=None, log=print, clock=time.time, now=None, post_reset=True):
    """Відновити кодплуг рації з бекапу `zip_path`.

    confirm(text, plan) -> bool викликається ПІСЛЯ всіх перевірок і страхового бекапу, ПЕРЕД першим записом.
    progress(percent, text). Повертає словник-підсумок; при відхиленні -- RestoreRefused (нічого не записано),
    при обриві -- RestoreInterrupted (стан невизначений), при розбіжності перевірки -- RestoreVerifyFailed."""
    t0 = clock()

    def prog(pct, text):
        if progress:
            progress(max(0, min(100, int(pct))), text)

    if not RESTORE_UNLOCKED:
        raise RestoreRefused("відновлення заблоковано (%s). Нічого не записано." % LOCKED_CAPTION)

    # --- W1.4 + W1.3: файл і рація (нічого не пишемо) ---
    prog(0, "Перевіряю файл бекапу...")
    manifest, bk_ee, bk_fl = load_backup_for_restore(zip_path)
    prog(2, "Перевіряю рацію...")
    try:
        info = link.radio_info()
    except cl.CpsError as e:
        raise RestoreRefused("не вдалося зв'язатися з рацією (%s). Нічого не записано." % e)
    check_radio(info, manifest)
    log("Рація: прошивка %s; бекап з прошивки %s." % (info["gitRevision"], manifest["radio"].get("gitRevision")))

    # --- W1.5: страхова копія ---
    d = os.path.dirname(os.path.abspath(zip_path))
    if not os.access(d, os.W_OK):
        raise RestoreRefused("нема права писати в теку %s, де має лежати страхова копія. Нічого не записано." % d)
    safety = safety_backup_path(zip_path, now)

    def back_prog(pct, text):
        prog(3 + pct * 0.32, "Страхова копія: " + text)

    try:
        data, bmanifest = cl.backup_codeplug(link, back_prog, log=log)
    except cl.CpsError as e:
        raise RestoreRefused("не вдалося зробити страхову копію поточного стану рації (%s). Нічого не записано." % e)
    try:
        with open(safety, "xb") as f:
            f.write(data)
        _m, cur_ee, cur_fl = cl.read_backup_zip(safety)
        with open(safety, "rb") as f:
            if f.read() != data:
                raise cl.CpsError("записаний файл відрізняється від прочитаного")
    except (OSError, cl.CpsError) as e:
        try:
            os.unlink(safety)
        except OSError:
            pass
        raise RestoreRefused("не вдалося зберегти й перевірити страхову копію %s: %s. Нічого не записано." % (safety, e))
    log("Страхова копія збережена й перевірена: %s" % safety)

    # --- план і підтвердження (W1.6) ---
    plan = compute_plan(cur_ee, cur_fl, bk_ee, bk_fl)
    if not plan.sectors:
        prog(100, "Рація вже містить цей кодплуг")
        log("Усі сектори збігаються з бекапом (крім калібрування й квіккеїв) -- записувати нічого.")
        return {"cancelled": False, "nothingToDo": True, "sectorsWritten": 0, "sectorsTotal": plan.total_sectors,
                "safetyCopy": safety, "seconds": round(clock() - t0, 1)}
    text = confirm_text(manifest, bk_ee, bk_fl, info, plan, safety, zip_path)
    if not confirm(text, plan):
        log("Скасовано користувачем; рація не змінена. Страхова копія лишилась: %s" % safety)
        return {"cancelled": True, "safetyCopy": safety, "seconds": round(clock() - t0, 1)}

    # --- запис (W1.7: лише сектори з плану, тобто лише в межах eeprom/flash із маніфесту) ---
    _send_c(link, 0)       # показати на рації екран CPS (як робить справжній CPS перед записом)
    t_write = clock()
    n = len(plan.sectors)
    for k, (label, raw_addr, sec) in enumerate(plan.sectors):
        prog(35 + 35.0 * k / n, "Пишу сектор %d з %d (%s, 0x%X)..." % (k + 1, n, label, raw_addr))
        try:
            write_sector(link, raw_addr, sec, log)
        except (_XSilent, _XRefused) as e:
            raise RestoreInterrupted(
                "ЗАПИС ОБІРВАНО на секторі %d з %d (%s, адреса 0x%X): %s.\n"
                "Кодплуг рації тепер у НЕВИЗНАЧЕНОМУ стані: частина секторів уже з бекапу, частина ще ні.\n"
                "Страхова копія стану ДО відновлення: %s\n"
                "Що робити: вимкни й увімкни рацію (щоб скинути її внутрішній стан запису), перевір кабель і ПОВТОРИ відновлення з ТИМ САМИМ "
                "файлом %s. Якщо рація не вмикається нормально -- відновлення зі страхової копії робиться так само."
                % (k + 1, n, label, raw_addr, e, safety, os.path.basename(zip_path)))
    log("Записано секторів: %d з %d, %.1f с." % (n, plan.total_sectors, clock() - t_write))

    # --- W1.8: перечитати все й звірити ---
    def ver_prog(pct, text):
        prog(70 + pct * 0.29, "Перевіряю: " + text)

    try:
        rb_ee = link.read(cl.CPS_ACCESS_EEPROM, 0, cl.EEPROM_BACKUP_LEN,
                          lambda d_, t_: ver_prog(50.0 * d_ / t_, "EEPROM %d%%" % (100 * d_ // t_)))
        rb_fl = link.read(cl.CPS_ACCESS_FLASH, plan.raw_flash_start, len(plan.want_fl),
                          lambda d_, t_: ver_prog(50.0 + 50.0 * d_ / t_, "флеш %d%%" % (100 * d_ // t_)))
    except cl.CpsError as e:
        raise RestoreInterrupted(
            "ЗАПИС ЗАВЕРШЕНО, але перечитати рацію для перевірки не вдалося: %s.\n"
            "Стан кодплуга не підтверджено. Страхова копія стану ДО відновлення: %s\n"
            "Що робити: перепідключи рацію й повтори відновлення з тим самим файлом %s." % (e, safety, os.path.basename(zip_path)))
    sha_ee_got = cl.sha256(_mask_quickkeys(rb_ee))
    sha_ee_want = cl.sha256(_mask_quickkeys(plan.want_ee))
    sha_fl_got = cl.sha256(rb_fl)
    sha_fl_want = cl.sha256(plan.want_fl)
    if sha_ee_got != sha_ee_want or sha_fl_got != sha_fl_want:
        bad = []
        if sha_ee_got != sha_ee_want:
            bad.append("EEPROM")
        if sha_fl_got != sha_fl_want:
            bad.append("флеш-кодплуг")
        raise RestoreVerifyFailed(
            "ПЕРЕВІРКА НЕ ПРОЙШЛА: після запису %s не збігається з бекапом (SHA-256 різні).\n"
            "Відновлення НЕ можна вважати успішним. Страхова копія стану ДО відновлення: %s\n"
            "Що робити: повтори відновлення з тим самим файлом %s. Якщо знову розбіжність -- не користуйся рацією для важливого, "
            "пришли лог." % (" і ".join(bad), safety, os.path.basename(zip_path)))
    log("Перевірка пройшла: SHA-256 EEPROM (без квіккеїв) %s, флеш %s." % (sha_ee_got[:16], sha_fl_got[:16]))

    prog(99, "Перезавантажую рацію...")
    if post_reset:
        _send_c(link, 6, POST_RESTORE_SUB)
    prog(100, "Готово")
    return {"cancelled": False, "nothingToDo": False, "sectorsWritten": n, "sectorsTotal": plan.total_sectors, "safetyCopy": safety,
            "sha256Eeprom": sha_ee_got, "sha256Flash": sha_fl_got, "flashMatchesManifest": sha_fl_got == manifest["parts"]["flash"]["sha256"],
            "writeSeconds": round(clock() - t_write, 1), "seconds": round(clock() - t0, 1)}


# =========================================================================================
#  CLI
# =========================================================================================

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="R25: відновлення кодплуга з бекапу (ЗАПИСУЄ в рацію).")
    ap.add_argument("zip")
    ap.add_argument("--port")
    a = ap.parse_args(argv)
    if not RESTORE_UNLOCKED:
        raise SystemExit("ВІДНОВЛЕННЯ ЗАБЛОКОВАНО: %s." % LOCKED_CAPTION)

    def confirm(text, _plan):
        print(text)
        return input("Щоб продовжити, введи слово ВІДНОВИТИ: ").strip() == "ВІДНОВИТИ"

    last = [-1]

    def prog(pct, text):
        if pct != last[0]:
            last[0] = pct
            print("%3d%%  %s" % (pct, text))

    ser = cl.open_radio(a.port, timeout=1.0)
    try:
        res = restore_codeplug(cl.CpsLink(ser), a.zip, confirm, prog)
        print("Підсумок:", res)
    finally:
        ser.close()


if __name__ == "__main__":
    try:
        main()
    except cl.CpsError as e:
        raise SystemExit("\nПОМИЛКА: %s" % e)
